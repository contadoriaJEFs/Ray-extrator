from dataclasses import dataclass
from typing import Optional
import pandas as pd

# Fonte: planilhas fornecidas no projeto. Não inclui valores futuros não presentes nas fontes.
TETOS = {}
for y,v in [(2020,6101.06),(2021,6433.57),(2022,7087.22),(2024,7786.02),(2025,8157.41)]:
    for m in range(1,13): TETOS[f'{y}-{m:02d}']=v
for m in (1,2): TETOS[f'2023-{m:02d}']=7087.22
for m in range(3,13): TETOS[f'2023-{m:02d}']=7507.49

def classify_declarante(df, assignments):
    """Aplica classificação MANUAL por CNPJ. assignments: {cnpj: '11'|'20'|'nao_definido'}."""
    out=df.copy()
    out['grupo_previdenciario']=out['cnpj_declarante'].map(assignments).fillna('nao_definido')
    return out

def observed_rate(df):
    out=df.copy(); base=out['rendimento_tributavel'].astype(float)
    out['aliquota_efetiva_observada']=out['previdencia_oficial'].astype(float).div(base.where(base.ne(0)))
    return out['aliquota_efetiva_observada']

def apurar_competencia(grupo, teto: Optional[float]):
    if teto is None:
        return {'status':'TETO_NAO_CADASTRADO'}
    mensal=grupo[grupo['tipo_competencia']=='mensal']
    rem11=float(mensal.loc[mensal['grupo_previdenciario']=='11','rendimento_tributavel'].sum())
    rem20=float(mensal.loc[mensal['grupo_previdenciario']=='20','rendimento_tributavel'].sum())
    contrib=float(mensal['previdencia_oficial'].sum())
    base11=min(rem11,teto)
    max11=base11*0.11
    saldo=max(teto-rem11,0.0)
    base20=min(rem20,saldo)
    max20=base20*0.20
    max_total=max11+max20
    excesso=contrib-max_total
    return {'status':'OK','remuneracao_11':rem11,'contribuicao_11_recolhida':float(mensal.loc[mensal['grupo_previdenciario']=='11','previdencia_oficial'].sum()),'remuneracao_20':rem20,'contribuicao_20_recolhida':float(mensal.loc[mensal['grupo_previdenciario']=='20','previdencia_oficial'].sum()),'soma_contribuicoes_recolhidas':contrib,'teto_previdenciario':teto,'base_maxima_11':base11,'contribuicao_maxima_11':max11,'saldo_teto_20':saldo,'base_maxima_20':base20,'contribuicao_maxima_20':max20,'contribuicao_maxima_total':max_total,'contribuicao_acima_teto':excesso}

def apurar(df,tetos):
    rows=[]
    for comp,g in df[df['tipo_competencia']=='mensal'].groupby('competencia',dropna=False):
        unknown=g[g['grupo_previdenciario']=='nao_definido']['cnpj_declarante'].dropna().unique().tolist()
        teto=tetos.get(comp)
        if unknown:
            r={'competencia':comp,'status':'CLASSIFICACAO_PENDENTE','cnpjs_pendentes':', '.join(unknown),'teto_previdenciario':teto}
        else:
            r={'competencia':comp,**apurar_competencia(g,teto)}
        rows.append(r)
    return pd.DataFrame(rows).sort_values('competencia') if rows else pd.DataFrame()
