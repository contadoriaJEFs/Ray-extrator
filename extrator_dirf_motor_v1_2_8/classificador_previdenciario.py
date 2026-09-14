import math
import pandas as pd

REGRA_VERSAO = '1.0'
REGRA_ID = 'CLASSIFICACAO_DETERMINISTICA_V1'


def _rates(df):
    x = df.copy()
    x['rendimento_tributavel'] = pd.to_numeric(x.get('rendimento_tributavel'), errors='coerce').fillna(0)
    x['previdencia_oficial'] = pd.to_numeric(x.get('previdencia_oficial'), errors='coerce').fillna(0)
    x = x[(x['tipo_competencia'].eq('mensal')) & (x['rendimento_tributavel'] > 0) & (x['previdencia_oficial'] >= 0)].copy()
    if x.empty:
        return []
    x['rate'] = x['previdencia_oficial'] / x['rendimento_tributavel']
    return x.loc[x['rate'].notna(), 'rate'].tolist()


def _near(r, target, tol):
    return abs(r - target) <= tol


def sugerir_classificacao(df_fonte):
    """Sugere grupo previdenciário com regras conservadoras e auditáveis.

    A taxa observada é evidência auxiliar, nunca fundamento isolado para uma
    classificação jurídica. Sugestões fracas ficam como confirmação necessária.
    """
    sub = df_fonte.copy()
    rates = _rates(sub)
    evidencias = []
    regra = REGRA_ID
    sugestao = 'nao_definido'
    confianca = 'baixa'

    if rates:
        med = float(pd.Series(rates).median())
        min_r, max_r = min(rates), max(rates)
        n = len(rates)

        # Padrão estável de contribuição fixa de 20%.
        if n >= 2 and all(_near(r, 0.20, 0.0125) for r in rates):
            sugestao, confianca = '20', 'alta'
            evidencias.append(f'Padrão de alíquota observada estável próximo de 20% ({med*100:.2f}% mediana).')
        # Padrão estável de contribuição fixa de 11%.
        elif n >= 2 and all(_near(r, 0.11, 0.0125) for r in rates):
            sugestao, confianca = '11', 'alta'
            evidencias.append(f'Padrão de alíquota observada estável próximo de 11% ({med*100:.2f}% mediana).')
        else:
            # Evidência de progressividade: múltiplas taxas compatíveis com
            # faixas históricas e variação relevante entre competências.
            bandas = (0.075, 0.09, 0.12, 0.14)
            compat = [r for r in rates if any(_near(r, b, 0.006) for b in bandas)]
            variacao = max_r - min_r
            if len(set(round(r, 3) for r in compat)) >= 2 and variacao >= 0.015:
                sugestao, confianca = 'progressiva', 'alta'
                evidencias.append('Foram observadas taxas efetivas distintas compatíveis com faixas da metodologia progressiva.')
            elif med <= 0.145 and max_r - min_r >= 0.02:
                sugestao, confianca = 'progressiva', 'media'
                evidencias.append('Padrão observado é compatível com metodologia progressiva, mas não é conclusivo.')
            else:
                evidencias.append('Padrão de contribuição observado não permite distinguir com segurança 11%, 20% ou progressiva.')
    else:
        evidencias.append('Não há base mensal suficiente para inferência automática pela contribuição observada.')

    # Códigos DIRF são natureza de rendimento e não determinam, sozinhos,
    # o grupo previdenciário. Apenas registramos essa evidência contextual.
    codigos = set(sub.get('codigo_receita', pd.Series(dtype=str)).dropna().astype(str).str.strip())
    if codigos:
        evidencias.append('Código(s) DIRF registrado(s) como evidência contextual; não usado isoladamente para definir o grupo.')

    if sugestao == 'nao_definido':
        confianca = 'baixa'

    return {
        'classificacao_sugerida': sugestao,
        'classificacao_final': sugestao if confianca == 'alta' else 'nao_definido',
        'origem_classificacao': 'automatico' if confianca == 'alta' else 'pendente',
        'nivel_confianca': confianca,
        'evidencias': evidencias,
        'regra_classificacao': regra,
        'versao_regra': REGRA_VERSAO,
    }


def classificar_fontes(df, cnpjs, assignments=None, metadata=None):
    assignments = assignments or {}
    metadata = metadata or {}
    result = {}
    for cnpj in cnpjs:
        sub = df[df['cnpj_declarante'].astype(str).eq(str(cnpj))]
        sug = sugerir_classificacao(sub)
        if cnpj in assignments:
            final = assignments[cnpj]
            old = metadata.get(cnpj, {})
            sug.update({
                'classificacao_final': final,
                'origem_classificacao': 'usuario',
                'nivel_confianca': 'confirmada',
                'data_classificacao': old.get('data_classificacao'),
                'usuario_confirmador': old.get('usuario_confirmador'),
            })
        result[cnpj] = sug
    return result
