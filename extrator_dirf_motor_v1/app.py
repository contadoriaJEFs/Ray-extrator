import io, json, re
import pandas as pd
import streamlit as st
from dirf_core import extract_pdf
from motor_previdenciario import TETOS, classify_declarante, observed_rate, apurar

st.set_page_config(page_title='Extrator DIRF + Motor Previdenciário', page_icon='📄', layout='wide')

def fmt(v):
    try: return f'R$ {float(v):,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    except: return ''

def competencia_br(c,t):
    if t=='13º' and isinstance(c,str): return f'13º/{c[:4]}' if c.endswith('-13') else '13º'
    if t=='mensal' and isinstance(c,str):
        m=re.fullmatch(r'(\d{4})-(\d{2})',c)
        return f'01/{m.group(2)}/{m.group(1)}' if m else ''
    return ''

def csv_bytes(df): return df.to_csv(index=False,sep=';',decimal=',',encoding='utf-8-sig',lineterminator='\r\n').encode('utf-8-sig')

def load_reference_tetos(): return dict(TETOS)

st.title('Extrator DIRF + Motor Previdenciário V1')
st.caption('Extração preservada + classificação separada + apuração por competência. O motor não presume alíquota legal a partir do código DIRF.')
with st.sidebar:
    st.header('Entrada')
    files=st.file_uploader('Selecione uma ou mais DIRFs em PDF',type=['pdf'],accept_multiple_files=True)
    st.divider(); st.markdown('**Fluxo V1**')
    st.write('1. Extração RAW completa')
    st.write('2. Normalização por competência')
    st.write('3. Classificação por CNPJ')
    st.write('4. Apuração do teto')
    st.write('5. Demonstração horizontal')

if not files:
    st.info('Envie uma ou mais DIRFs para iniciar.')
    st.stop()

records=[]; declarations=[]; errors=[]
for uploaded in files:
    try:
        rs,ds,pages=extract_pdf(uploaded.getvalue())
        for r in rs:r['arquivo_origem']=uploaded.name
        for d in ds:d['arquivo_origem']=uploaded.name; d['paginas_pdf']=pages
        records.extend(rs); declarations.extend(ds)
    except Exception as e: errors.append({'arquivo':uploaded.name,'erro':str(e)})
if errors: st.error('Falha em arquivo(s).'); st.dataframe(pd.DataFrame(errors),hide_index=True,use_container_width=True)
if not records: st.error('Nenhum bloco DIRF reconhecível.'); st.stop()

df=pd.DataFrame(records)
df['aliquota_efetiva_observada']=observed_rate(df)
df['competencia_br']=df.apply(lambda r:competencia_br(r['competencia'],r['tipo_competencia']),axis=1)
order={'mensal':1,'13º':2,'total':3}; df['_ord']=df.tipo_competencia.map(order).fillna(9)
df=df.sort_values(['ano_calendario','arquivo_origem','pagina_pdf','_ord','competencia'],na_position='last').drop(columns='_ord')

st.success(f'{len(declarations)} blocos identificados; {len(df)} registros estruturados.')
tabs=st.tabs(['📄 Extração','🧩 Classificação','🧮 Apuração','📊 Demonstração','⬇️ Exportação'])

with tabs[0]:
    st.subheader('Declarações identificadas')
    cols=['ano_calendario','cnpj_declarante','nome_declarante_dirf','codigo_receita','descricao_codigo_receita','classificacao_codigo','pagina_pdf','arquivo_origem']
    st.dataframe(df[cols].drop_duplicates().reset_index(drop=True),use_container_width=True,hide_index=True)
    st.subheader('Consulta para Excel')
    consulta=df[df.tipo_competencia.isin(['mensal','13º'])].copy()
    f1,f2,f3=st.columns(3)
    anos=['Todos']+sorted(consulta.ano_calendario.dropna().astype(str).unique(),reverse=True)
    a=f1.selectbox('Ano',anos); base=consulta if a=='Todos' else consulta[consulta.ano_calendario.astype(str)==a]
    decl=['Todos']+sorted(base.nome_declarante_dirf.dropna().astype(str).unique(),key=str.casefold); dsel=f2.selectbox('Declarante',decl); base=base if dsel=='Todos' else base[base.nome_declarante_dirf.astype(str)==dsel]
    cnp=['Todos']+sorted(base.cnpj_declarante.dropna().astype(str).unique()); csel=f3.selectbox('CNPJ',cnp); base=base if csel=='Todos' else base[base.cnpj_declarante.astype(str)==csel]
    saida=base[['nome_declarante_dirf','cnpj_declarante','competencia_br','rendimento_tributavel','irrf','previdencia_oficial']].copy(); saida.columns=['Declarante','CNPJ','Competência','Rendimentos','Imposto','Previdência']
    view=saida.copy()
    for c in ['Rendimentos','Imposto','Previdência']: view[c]=view[c].map(fmt)
    st.dataframe(view,use_container_width=True,hide_index=True)
    payload=json.dumps([[str(x or '') for x in row] for row in saida.itertuples(index=False,name=None)],ensure_ascii=False)
    html=f'''<button onclick="navigator.clipboard.writeText([{json.dumps(['Declarante','CNPJ','Competência','Rendimentos','Imposto','Previdência'])},...{payload}].map(x=>x.join('\\t')).join('\\n')).then(()=>this.innerText='✓ COPIADO PARA EXCEL')" style="padding:11px 18px;border:0;border-radius:8px;background:#111827;color:white;font-weight:700">📋 COPIAR PARA EXCEL</button>'''
    st.components.v1.html(html,height=55)

with tabs[1]:
    st.subheader('Classificação previdenciária por CNPJ')
    st.info('A alíquota efetiva observada é somente diagnóstico. A classificação do grupo 11%/20% é definida aqui por CNPJ e fica separada do código DIRF.')
    cnpjs=sorted(df.cnpj_declarante.dropna().astype(str).unique())
    if 'assignments' not in st.session_state: st.session_state.assignments={}
    rows=[]
    for cnpj in cnpjs:
        sub=df[df.cnpj_declarante.astype(str)==cnpj]
        nomes=' / '.join(sorted(sub.nome_declarante_dirf.dropna().astype(str).unique(),key=str.casefold))
        cod=' / '.join(sorted(sub.codigo_receita.dropna().astype(str).unique()))
        rates=sub.loc[(sub.rendimento_tributavel>0)&(sub.previdencia_oficial.notna()),'aliquota_efetiva_observada']
        med=float(rates.median()*100) if len(rates) else None
        col1,col2,col3,col4=st.columns([2,4,2,2])
        col1.write(cnpj); col2.write(nomes); col3.write(f'{med:.2f}%' if med is not None else '—')
        current=st.session_state.assignments.get(cnpj,'nao_definido')
        val=col4.selectbox('Grupo', ['nao_definido','11','20'],index=['nao_definido','11','20'].index(current),key='grp_'+cnpj)
        st.session_state.assignments[cnpj]=val
    st.caption('“nao_definido” impede a apuração daquela competência, evitando inferência silenciosa.')

classified=classify_declarante(df,st.session_state.get('assignments',{}))

with tabs[2]:
    st.subheader('Motor de apuração')
    st.write('Fórmulas V1: base 11% = menor entre remuneração 11% e teto; saldo = teto − remuneração 11% (mínimo zero); base 20% = menor entre remuneração 20% e saldo; excesso = contribuições recolhidas − contribuição máxima total.')
    result=apurar(classified,load_reference_tetos())
    if result.empty: st.warning('Sem competências mensais para apurar.'); st.stop()
    st.dataframe(result,use_container_width=True,hide_index=True,column_config={
        'soma_contribuicoes_recolhidas':st.column_config.NumberColumn('Contr. recolhida',format='R$ %.2f'),
        'teto_previdenciario':st.column_config.NumberColumn('Teto',format='R$ %.2f'),
        'contribuicao_maxima_11':st.column_config.NumberColumn('Máx. 11%',format='R$ %.2f'),
        'contribuicao_maxima_20':st.column_config.NumberColumn('Máx. 20%',format='R$ %.2f'),
        'contribuicao_maxima_total':st.column_config.NumberColumn('Máx. total',format='R$ %.2f'),
        'contribuicao_acima_teto':st.column_config.NumberColumn('Acima do teto',format='R$ %.2f'),})
    pend=result[result.status!='OK']
    if not pend.empty: st.warning(f'{len(pend)} competência(s) dependem de classificação ou teto cadastrado.')

with tabs[3]:
    st.subheader('Demonstração horizontal')
    mensal=classified[classified.tipo_competencia=='mensal'].copy()
    comps=sorted(mensal.competencia.dropna().unique())
    if not comps: st.info('Sem dados mensais.'); st.stop()
    rec=[]
    for comp in comps:
        g=mensal[mensal.competencia==comp]
        row={'Competência':comp}
        for cnpj,sg in g.groupby('cnpj_declarante',dropna=False):
            nome=str(sg.nome_declarante_dirf.iloc[0]); short=f"{nome} | {cnpj}"
            row[short+' — Remuneração']=sg.rendimento_tributavel.sum(); row[short+' — Previdência']=sg.previdencia_oficial.sum()
        rec.append(row)
    horiz=pd.DataFrame(rec).fillna(0)
    st.dataframe(horiz,use_container_width=True,hide_index=True,column_config={c:st.column_config.NumberColumn(c,format='R$ %.2f') for c in horiz.columns if c!='Competência'})
    st.caption('As colunas de declarantes são dinâmicas: cada CNPJ encontrado gera o par Remuneração/Previdência.')

with tabs[4]:
    st.subheader('Exportações')
    json_payload={'schema':'extrator_dirf.v3','descricao':'RAW completo + indicadores diagnósticos; classificação e apuração ficam separadas.','registros':df.to_dict(orient='records'),'classificacao_por_cnpj':st.session_state.get('assignments',{}),'tetos_utilizados':load_reference_tetos()}
    st.download_button('Baixar JSON completo + motor',json.dumps(json_payload,ensure_ascii=False,indent=2).encode('utf-8'),'extracao_dirf_motor_v1.json','application/json')
    exp=classified.copy(); exp['competencia_br']=exp.apply(lambda r:competencia_br(r.competencia,r.tipo_competencia),axis=1)
    st.download_button('Baixar CSV normalizado',csv_bytes(exp),'extracao_dirf_normalizada.csv','text/csv')
    if 'result' in locals(): st.download_button('Baixar apuração CSV',csv_bytes(result),'apuracao_previdenciaria_v1.csv','text/csv')
    st.download_button('Baixar JSON RAW somente',json.dumps({'schema':'extrator_dirf.v3','registros':records},ensure_ascii=False,indent=2).encode('utf-8'),'extracao_dirf_raw.json','application/json')
