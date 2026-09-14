from typing import Optional
import math
import pandas as pd

from tabelas_previdenciarias import TABELAS_HISTORICAS, TETOS, tabela_por_competencia

def calcular_faixas(remuneracao: float, tabela: dict):
    """Calcula a contribuição conforme a metodologia da tabela.

    Tradicional: identifica a faixa atingida e aplica a alíquota sobre a base inteira,
    respeitado o teto. Progressiva: distribui a base entre as faixas e soma as parcelas.
    """
    rem = max(float(remuneracao or 0), 0.0)
    teto = float(tabela['teto'])
    base = min(rem, teto)
    detalhes = []

    if tabela['metodologia'] == 'tradicional':
        faixa_escolhida = None
        for idx, (inferior, superior, aliquota) in enumerate(tabela['faixas'], start=1):
            if base <= superior:
                faixa_escolhida = (idx, inferior, superior, aliquota)
                break
        if faixa_escolhida is None:
            faixa_escolhida = (len(tabela['faixas']), *tabela['faixas'][-1])
        idx, inferior, superior, aliquota = faixa_escolhida
        contrib = base * aliquota
        for n, (inf, sup, aliq) in enumerate(tabela['faixas'], start=1):
            detalhes.append({
                'faixa': n,
                'limite_inferior': inf,
                'limite_superior': sup,
                'base_na_faixa': base if n == idx else 0.0,
                'aliquota': aliq,
                'contribuicao': contrib if n == idx else 0.0,
                'aplicada': n == idx,
            })
        return {'remuneracao': rem, 'base_limitada_ao_teto': base, 'contribuicao_calculada': contrib, 'faixas': detalhes}

    total = 0.0
    for idx, (inferior, superior, aliquota) in enumerate(tabela['faixas'], start=1):
        parcela = max(min(base, superior) - inferior, 0.0)
        contrib = parcela * aliquota
        detalhes.append({
            'faixa': idx,
            'limite_inferior': inferior,
            'limite_superior': superior,
            'base_na_faixa': parcela,
            'aliquota': aliquota,
            'contribuicao': contrib,
            'aplicada': parcela > 0,
        })
        total += contrib
        if base <= superior:
            break
    return {'remuneracao': rem, 'base_limitada_ao_teto': base, 'contribuicao_calculada': total, 'faixas': detalhes}


def classificar_declarante(df, assignments):
    out = df.copy()
    out['grupo_previdenciario'] = out['cnpj_declarante'].map(assignments).fillna('nao_definido')
    return out

# Alias usado pela V1.1.
def classify_declarante(df, assignments):
    return classificar_declarante(df, assignments)


def observed_rate(df):
    out = df.copy()
    base = out['rendimento_tributavel'].astype(float)
    out['aliquota_efetiva_observada'] = out['previdencia_oficial'].astype(float).div(base.where(base.ne(0)))
    return out['aliquota_efetiva_observada']


def verificar_tabela(competencia: str, remuneracao: float, previdencia_dirf: Optional[float] = None, tolerancia: float = 0.01):
    tabela = tabela_por_competencia(competencia)
    if tabela is None:
        return {'status': 'TABELA_NAO_CADASTRADA', 'competencia': competencia, 'remuneracao': float(remuneracao or 0)}
    calc = calcular_faixas(remuneracao, tabela)
    informado = None if previdencia_dirf in (None, '') else float(previdencia_dirf)
    diferenca_bruta = None if informado is None else float(informado - calc['contribuicao_calculada'])
    diferenca = None if diferenca_bruta is None else round(diferenca_bruta, 2)
    tolerancia = max(float(tolerancia or 0), 0.0)
    if informado is None:
        status = 'SEM_COMPARACAO'
    elif abs(diferenca_bruta) <= tolerancia:
        status = 'COMPATIVEL'
    else:
        status = 'DIFERENCA_PARA_ANALISE'
    return {
        'status': status,
        'competencia': competencia,
        'metodologia': tabela['metodologia'],
        'tabela_id': tabela['id'],
        'fonte': tabela['fonte'],
        'teto': tabela['teto'],
        'remuneracao': float(remuneracao or 0),
        'previdencia_dirf': informado,
        'contribuicao_calculada': round(calc['contribuicao_calculada'], 2),
        'diferenca_dirf_menos_calculado': diferenca,
        'diferenca_bruta': diferenca_bruta,
        'tolerancia_utilizada': tolerancia,
        'faixas': calc['faixas'],
    }



def verificar_13o(ano: int, remuneracao: float, previdencia_dirf: Optional[float] = None, tolerancia: float = 0.01):
    """Prepara a verificação do 13º sem misturá-lo às competências mensais.

    A tabela histórica é identificada pela vigência de dezembro do ano.
    A contribuição do 13º é calculada sobre sua própria base, separadamente
    da remuneração mensal. Quando a análise é feita por fonte isolada, o
    resultado é apenas indicativo, pois múltiplos vínculos podem exigir a
    apuração conjunta do 13º.
    """
    try:
        ano_i = int(ano)
    except Exception:
        return {'status': 'TABELA_NAO_CADASTRADA', 'competencia': f'{ano}-13', 'tipo_competencia': '13º', 'remuneracao': float(remuneracao or 0)}

    tabela = tabela_por_competencia(f'{ano_i:04d}-12')
    competencia = f'{ano_i:04d}-13'
    if tabela is None:
        return {'status': 'TABELA_NAO_CADASTRADA', 'competencia': competencia, 'tipo_competencia': '13º', 'remuneracao': float(remuneracao or 0)}

    calc = calcular_faixas(remuneracao, tabela)
    informado = None if previdencia_dirf in (None, '') else float(previdencia_dirf)
    diferenca_bruta = None if informado is None else float(informado - calc['contribuicao_calculada'])
    diferenca = None if diferenca_bruta is None else round(diferenca_bruta, 2)
    tolerancia = max(float(tolerancia or 0), 0.0)
    # A comparação individual do 13º não é conclusiva quando existem outros
    # vínculos no mesmo ano. Mantemos o cálculo como referência, mas sinalizamos
    # a necessidade de análise conjunta em vez de classificá-lo como compatível.
    status = 'ANALISE_13O_CONJUNTA' if informado is not None else 'SEM_COMPARACAO'
    return {
        'status': status,
        'competencia': competencia,
        'tipo_competencia': '13º',
        'metodologia': tabela['metodologia'],
        'tabela_id': tabela['id'],
        'fonte': tabela['fonte'],
        'teto': tabela['teto'],
        'remuneracao': float(remuneracao or 0),
        'previdencia_dirf': informado,
        'contribuicao_calculada': round(calc['contribuicao_calculada'], 2),
        'diferenca_dirf_menos_calculado': diferenca,
        'diferenca_bruta': diferenca_bruta,
        'tolerancia_utilizada': tolerancia,
        'faixas': calc['faixas'],
        'observacao': '13º separado da remuneração mensal; para múltiplos vínculos, validar a apuração conjunta do 13º.'
    }


def apurar_competencia(grupo, teto: Optional[float]):
    if teto is None:
        return {'status': 'TETO_NAO_CADASTRADO'}
    mensal = grupo[grupo['tipo_competencia'] == 'mensal']
    rem11 = float(mensal.loc[mensal['grupo_previdenciario'] == '11', 'rendimento_tributavel'].sum())
    rem20 = float(mensal.loc[mensal['grupo_previdenciario'] == '20', 'rendimento_tributavel'].sum())
    remprog = float(mensal.loc[mensal['grupo_previdenciario'] == 'progressiva', 'rendimento_tributavel'].sum())
    contrib = float(mensal['previdencia_oficial'].sum())
    if remprog > 0:
        return {'status': 'PROGRESSIVA_EM_VALIDACAO', 'remuneracao_progressiva': remprog, 'soma_contribuicoes_recolhidas': contrib, 'teto_previdenciario': teto}
    base11 = min(rem11, teto)
    max11 = base11 * 0.11
    saldo = max(teto - rem11, 0.0)
    base20 = min(rem20, saldo)
    max20 = base20 * 0.20
    max_total = max11 + max20
    excesso = contrib - max_total
    return {'status': 'OK', 'remuneracao_11': rem11, 'contribuicao_11_recolhida': float(mensal.loc[mensal['grupo_previdenciario'] == '11', 'previdencia_oficial'].sum()), 'remuneracao_20': rem20, 'contribuicao_20_recolhida': float(mensal.loc[mensal['grupo_previdenciario'] == '20', 'previdencia_oficial'].sum()), 'soma_contribuicoes_recolhidas': contrib, 'teto_previdenciario': teto, 'base_maxima_11': base11, 'contribuicao_maxima_11': max11, 'saldo_teto_20': saldo, 'base_maxima_20': base20, 'contribuicao_maxima_20': max20, 'contribuicao_maxima_total': max_total, 'contribuicao_acima_teto': excesso}


def apurar(df, tetos):
    rows = []
    for comp, g in df[df['tipo_competencia'] == 'mensal'].groupby('competencia', dropna=False):
        unknown = g[g['grupo_previdenciario'] == 'nao_definido']['cnpj_declarante'].dropna().unique().tolist()
        teto = tetos.get(comp)
        if unknown:
            r = {'competencia': comp, 'status': 'CLASSIFICACAO_PENDENTE', 'cnpjs_pendentes': ', '.join(unknown), 'teto_previdenciario': teto}
        else:
            r = {'competencia': comp, **apurar_competencia(g, teto)}
        rows.append(r)
    return pd.DataFrame(rows).sort_values('competencia') if rows else pd.DataFrame()
