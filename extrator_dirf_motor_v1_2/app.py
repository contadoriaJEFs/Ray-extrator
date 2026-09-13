import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from dirf_core import extract_pdf, validate_records
from motor_previdenciario import classify_declarante, observed_rate, apurar, verificar_tabela
from tabelas_previdenciarias import TETOS, TABELAS_HISTORICAS

st.set_page_config(page_title='Extrator DIRF + Motor Previdenciário', page_icon='📄', layout='wide')


def fmt(v):
    try:
        return f'R$ {float(v):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return ''


def competencia_br(c, t):
    if t == '13º' and isinstance(c, str):
        return f'13º/{c[:4]}' if c.endswith('-13') else '13º'
    if t == 'mensal' and isinstance(c, str):
        m = re.fullmatch(r'(\d{4})-(\d{2})', c)
        return f'01/{m.group(2)}/{m.group(1)}' if m else ''
    return ''


def csv_bytes(df):
    return df.to_csv(index=False, sep=';', decimal=',', encoding='utf-8-sig', lineterminator='\r\n').encode('utf-8-sig')


def normalize_cnpj(v):
    return str(v or '').strip()


def apply_filters(base, ano='Todos', declarante='Todos', cnpj='Todos', codigo='Todos', tipo='Todos', competencias=None, grupo='Todos'):
    out = base.copy()
    if ano != 'Todos':
        out = out[out['ano_calendario'].astype(str).eq(str(ano))]
    if declarante != 'Todos':
        out = out[out['nome_declarante_dirf'].astype(str).eq(str(declarante))]
    if cnpj != 'Todos':
        out = out[out['cnpj_declarante'].astype(str).eq(str(cnpj))]
    if codigo != 'Todos':
        out = out[out['codigo_receita'].astype(str).eq(str(codigo))]
    if tipo != 'Todos':
        out = out[out['tipo_competencia'].astype(str).eq(str(tipo))]
    if competencias:
        out = out[out['competencia_br'].isin(competencias)]
    if grupo != 'Todos' and 'grupo_previdenciario' in out.columns:
        out = out[out['grupo_previdenciario'].eq(grupo)]
    return out


st.title('Extrator DIRF + Motor Previdenciário V1.2')
st.caption('Extração preservada + agrupamento de vínculos/declarantes + classificação separada + apuração por competência.')

with st.sidebar:
    st.header('Entrada')
    files = st.file_uploader('Selecione uma ou mais DIRFs em PDF', type=['pdf'], accept_multiple_files=True)
    st.divider()
    st.markdown('**Fluxo**')
    st.write('1. Extração RAW completa')
    st.write('2. Consulta com filtros')
    st.write('3. Agrupamento dos vínculos/declarantes')
    st.write('4. Classificação 11% / 20% / Progressiva')
    st.write('5. Verificação da tabela previdenciária')
    st.write('6. Apuração do teto')
    st.write('7. Demonstração horizontal')
    st.info('O código DIRF e a alíquota efetiva observada não determinam, sozinhos, a classificação previdenciária.')

if not files:
    st.info('Envie uma ou mais DIRFs para iniciar.')
    st.stop()

records, declarations, errors = [], [], []
for uploaded in files:
    try:
        rs, ds, pages = extract_pdf(uploaded.getvalue())
        for r in rs:
            r['arquivo_origem'] = uploaded.name
        for d in ds:
            d['arquivo_origem'] = uploaded.name
            d['paginas_pdf'] = pages
        records.extend(rs)
        declarations.extend(ds)
    except Exception as exc:
        errors.append({'arquivo': uploaded.name, 'erro': str(exc)})

if errors:
    st.error('Falha em arquivo(s).')
    st.dataframe(pd.DataFrame(errors), hide_index=True, use_container_width=True)
if not records:
    st.error('Nenhum bloco DIRF reconhecível foi encontrado.')
    st.stop()

df = pd.DataFrame(records)
df['cnpj_declarante'] = df['cnpj_declarante'].map(normalize_cnpj)
df['aliquota_efetiva_observada'] = observed_rate(df)
df['competencia_br'] = df.apply(lambda r: competencia_br(r['competencia'], r['tipo_competencia']), axis=1)
order = {'mensal': 1, '13º': 2, 'total': 3}
df['_ord'] = df.tipo_competencia.map(order).fillna(9)
df = df.sort_values(['ano_calendario', 'arquivo_origem', 'pagina_pdf', '_ord', 'competencia'], na_position='last').drop(columns='_ord')

if 'assignments' not in st.session_state:
    st.session_state.assignments = {}
if 'included_cnpjs' not in st.session_state:
    st.session_state.included_cnpjs = set(df['cnpj_declarante'].dropna().astype(str).unique())

classified = classify_declarante(df, st.session_state.assignments)

st.success(f'{len(declarations)} blocos identificados; {len(df)} registros estruturados.')
m1, m2, m3, m4 = st.columns(4)
m1.metric('Arquivos', len(files))
m2.metric('Blocos DIRF', len(declarations))
m3.metric('Registros', len(df))
m4.metric('Declarantes/CNPJs', df['cnpj_declarante'].nunique())

tabs = st.tabs(['📄 Extração e filtros', '🔗 Agrupamento de vínculos', '🧩 Classificação', '🔎 Verificação', '🧮 Apuração', '📊 Demonstração', '⬇️ Exportação'])

with tabs[0]:
    st.subheader('Declarações identificadas')
    cols = ['ano_calendario', 'cnpj_declarante', 'nome_declarante_dirf', 'codigo_receita', 'descricao_codigo_receita', 'pagina_pdf', 'arquivo_origem']
    st.dataframe(df[cols].drop_duplicates().reset_index(drop=True), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader('Consulta para Excel')
    st.caption('Os filtros voltaram nesta versão. O resultado filtrado é independente do JSON RAW, que continua completo.')
    consulta = classified[classified.tipo_competencia.isin(['mensal', '13º'])].copy()

    f1, f2, f3 = st.columns(3)
    anos = sorted(consulta['ano_calendario'].dropna().astype(str).unique(), reverse=True)
    ano_sel = f1.selectbox('Ano', ['Todos'] + anos, key='filter_ano')
    base = consulta if ano_sel == 'Todos' else consulta[consulta['ano_calendario'].astype(str).eq(ano_sel)]

    decls = sorted(base['nome_declarante_dirf'].dropna().astype(str).unique(), key=str.casefold)
    decl_sel = f2.selectbox('Declarante', ['Todos'] + decls, key='filter_declarante')
    base = base if decl_sel == 'Todos' else base[base['nome_declarante_dirf'].astype(str).eq(decl_sel)]

    cnpjs = sorted(base['cnpj_declarante'].dropna().astype(str).unique())
    cnpj_sel = f3.selectbox('CNPJ', ['Todos'] + cnpjs, key='filter_cnpj')
    base = base if cnpj_sel == 'Todos' else base[base['cnpj_declarante'].astype(str).eq(cnpj_sel)]

    f4, f5, f6 = st.columns(3)
    codigos = sorted(base['codigo_receita'].dropna().astype(str).unique())
    codigo_sel = f4.selectbox('Código DIRF', ['Todos'] + codigos, key='filter_codigo')
    base = base if codigo_sel == 'Todos' else base[base['codigo_receita'].astype(str).eq(codigo_sel)]

    tipos = [x for x in ['mensal', '13º'] if x in set(base['tipo_competencia'].astype(str))]
    tipo_sel = f5.selectbox('Tipo', ['Todos'] + tipos, key='filter_tipo')
    base = base if tipo_sel == 'Todos' else base[base['tipo_competencia'].astype(str).eq(tipo_sel)]

    grupos = ['Todos', '11', '20', 'progressiva', 'nao_definido']
    grupo_sel = f6.selectbox('Grupo previdenciário', grupos, key='filter_grupo')
    base = base if grupo_sel == 'Todos' else base[base['grupo_previdenciario'].eq(grupo_sel)]

    comps = sorted(base['competencia_br'].dropna().astype(str).unique())
    comp_sel = st.multiselect('Competência', comps, default=comps, key='filter_competencia')
    if comp_sel:
        base = base[base['competencia_br'].isin(comp_sel)]
    else:
        base = base.iloc[0:0]

    saida = base[['nome_declarante_dirf', 'cnpj_declarante', 'competencia_br', 'rendimento_tributavel', 'irrf', 'previdencia_oficial']].copy()
    saida.columns = ['Declarante', 'CNPJ', 'Competência', 'Rendimentos', 'Imposto', 'Previdência']
    view = saida.copy()
    for c in ['Rendimentos', 'Imposto', 'Previdência']:
        view[c] = view[c].map(fmt)
    st.dataframe(view, use_container_width=True, hide_index=True)
    st.write(f'**{len(saida)} registro(s) no resultado filtrado.**')

    copy_rows = []
    for r in saida.itertuples(index=False):
        copy_rows.append([str(r[0] or ''), str(r[1] or ''), str(r[2] or ''), f'{float(r[3] or 0):.2f}'.replace('.', ','), f'{float(r[4] or 0):.2f}'.replace('.', ','), f'{float(r[5] or 0):.2f}'.replace('.', ',')])
    copy_payload = json.dumps(copy_rows, ensure_ascii=False)
    html = f'''<button id="copy" style="padding:11px 18px;border:0;border-radius:8px;background:#111827;color:white;font-weight:700;cursor:pointer">📋 COPIAR PARA EXCEL</button><span id="msg" style="margin-left:10px;font-size:13px;color:#475467"></span><script>const rows={copy_payload};const head=['Declarante','CNPJ','Competência','Rendimentos','Imposto','Previdência'];function tsv(){{return [head,...rows].map(r=>r.join('\\t')).join('\\n');}}document.getElementById('copy').onclick=async()=>{{const text=tsv();const msg=document.getElementById('msg');try{{await navigator.clipboard.writeText(text);msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).';}}catch(e){{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{{document.execCommand('copy');msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).';}}catch(err){{msg.textContent='Não foi possível acessar a área de transferência.';}}ta.remove();}}}};</script>'''
    st.components.v1.html(html, height=55)

with tabs[1]:
    st.subheader('Agrupamento de vínculos / declarantes')
    st.caption('Aqui você define quais fontes pagadoras entram no agrupamento da apuração. Cada CNPJ funciona como um vínculo/declarente dinâmico, equivalente aos pares Remuneração + Contribuição da planilha-base.')
    st.info('Marque “Incluir” para participar da apuração. Depois, na classificação, defina se o vínculo pertence ao grupo 11% ou 20%.')

    vinculos = []
    for cnpj in sorted(df['cnpj_declarante'].dropna().astype(str).unique()):
        sub = df[df['cnpj_declarante'].astype(str).eq(cnpj)]
        nomes = sorted(sub['nome_declarante_dirf'].dropna().astype(str).unique(), key=str.casefold)
        cods = sorted(sub['codigo_receita'].dropna().astype(str).unique())
        remun = float(sub[sub.tipo_competencia.eq('mensal')]['rendimento_tributavel'].sum())
        prev = float(sub[sub.tipo_competencia.eq('mensal')]['previdencia_oficial'].sum())
        vinculos.append({'cnpj': cnpj, 'nome': ' / '.join(nomes), 'codigos': ', '.join(cods), 'remuneracao': remun, 'previdencia': prev})

    for v in vinculos:
        key = 'include_' + re.sub(r'\W+', '_', v['cnpj'])
        default = v['cnpj'] in st.session_state.included_cnpjs
        include = st.checkbox(f"{v['nome']} — {v['cnpj']}", value=default, key=key)
        if include:
            st.session_state.included_cnpjs.add(v['cnpj'])
        else:
            st.session_state.included_cnpjs.discard(v['cnpj'])
        c1, c2, c3, c4 = st.columns([3, 1.3, 1.5, 1.5])
        c1.write(f"Códigos: {v['codigos']}")
        c2.write(f"{len(df[(df['cnpj_declarante'].eq(v['cnpj'])) & (df['tipo_competencia'].eq('mensal'))])} registros mensais")
        c3.write(f"Rem.: {fmt(v['remuneracao'])}")
        c4.write(f"Prev.: {fmt(v['previdencia'])}")
        st.divider()

    st.subheader('Resumo do agrupamento selecionado')
    selected = sorted(st.session_state.included_cnpjs)
    resumo = df[df['cnpj_declarante'].isin(selected) & df['tipo_competencia'].eq('mensal')].groupby(['cnpj_declarante', 'nome_declarante_dirf'], as_index=False).agg(remuneracao=('rendimento_tributavel', 'sum'), previdencia=('previdencia_oficial', 'sum'))
    if resumo.empty:
        st.warning('Nenhum vínculo selecionado.')
    else:
        st.dataframe(resumo, use_container_width=True, hide_index=True, column_config={'remuneracao': st.column_config.NumberColumn('Remuneração', format='R$ %.2f'), 'previdencia': st.column_config.NumberColumn('Previdência', format='R$ %.2f')})
        st.write(f'**{len(selected)} vínculo(s) selecionado(s).**')

# Apply the selected vínculo filter to the calculation layer only.
calc_df = classified[classified['cnpj_declarante'].isin(st.session_state.included_cnpjs)].copy()

with tabs[2]:
    st.subheader('Classificação previdenciária por vínculo/CNPJ')
    st.info('A classificação é manual e persistida durante a sessão. A alíquota efetiva observada serve apenas como diagnóstico. A opção PROGRESSIVA habilita a conferência da tabela histórica, mas permanece separada do cálculo principal enquanto a validação não for concluída.')
    cnpjs = sorted(df.cnpj_declarante.dropna().astype(str).unique())
    rows = []
    for cnpj in cnpjs:
        sub = df[df.cnpj_declarante.astype(str).eq(cnpj)]
        nomes = ' / '.join(sorted(sub.nome_declarante_dirf.dropna().astype(str).unique(), key=str.casefold))
        cod = ' / '.join(sorted(sub.codigo_receita.dropna().astype(str).unique()))
        rates = sub.loc[(sub.rendimento_tributavel > 0) & (sub.previdencia_oficial.notna()), 'aliquota_efetiva_observada']
        med = float(rates.median() * 100) if len(rates) else None
        current = st.session_state.assignments.get(cnpj, 'nao_definido')
        a, b, c, d = st.columns([2.1, 3.8, 2, 1.8])
        a.write(cnpj)
        b.write(nomes)
        c.write(f'{med:.2f}%' if med is not None else '—')
        val = d.selectbox('Grupo', ['nao_definido', '11', '20', 'progressiva'], index=['nao_definido', '11', '20', 'progressiva'].index(current), key='grp_' + re.sub(r'\W+', '_', cnpj))
        st.session_state.assignments[cnpj] = val
        rows.append({'CNPJ': cnpj, 'Declarante': nomes, 'Código DIRF': cod, 'Alíquota efetiva mediana': med, 'Grupo': val, 'Incluído': cnpj in st.session_state.included_cnpjs})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption('“nao_definido” impede a apuração silenciosa daquela competência. “progressiva” identifica o vínculo para a verificação histórica; o motor principal ainda sinaliza PROGRESSIVA_EM_VALIDACAO.')

classified = classify_declarante(df, st.session_state.get('assignments', {}))
calc_df = classified[classified['cnpj_declarante'].isin(st.session_state.included_cnpjs)].copy()

with tabs[3]:
    st.subheader('Verificação da Alíquota Progressiva')
    st.caption('Guia independente para validar a tabela histórica contra valores reais da DIRF. Esta guia não altera o motor principal.')

    with st.expander('ⓘ Como o sistema trata as tabelas históricas', expanded=True):
        st.markdown('''
**A competência determina a tabela.** O sistema não usa uma única alíquota para todo o período.

- **2017 a 2019:** faixas tradicionais de 8%, 9% e 11%; a alíquota da faixa atingida incide sobre a base inteira, respeitado o teto.
- **Janeiro e fevereiro de 2020:** permanece a tabela tradicional de 8%, 9% e 11%.
- **A partir de março de 2020:** passam a ser aplicadas alíquotas progressivas de 7,5%, 9%, 12% e 14%, incidindo cada percentual somente sobre a parcela correspondente.
- **Múltiplos vínculos:** para a sistemática progressiva, as remunerações da competência devem ser consideradas em conjunto, respeitado o limite máximo; a ordem dos vínculos pode afetar a parcela atribuída a cada fonte pagadora.
- **13º salário:** não é somado à remuneração mensal para enquadramento na tabela.

A classificação **PROGRESSIVA** e esta conferência são independentes do motor 11%/20%.
''')

    st.markdown('### Teste da competência')
    mensal_v = calc_df[calc_df.tipo_competencia.eq('mensal')].copy()
    comps_v = sorted(mensal_v.competencia.dropna().astype(str).unique())
    c1, c2 = st.columns([1.2, 1])
    comp_v = c1.selectbox('Competência', comps_v if comps_v else ['2026-01'], key='verif_comp')
    cnpjs_v = ['Manual / total da competência'] + sorted(mensal_v.cnpj_declarante.dropna().astype(str).unique())
    cnpj_v = c2.selectbox('Fonte / CNPJ', cnpjs_v, key='verif_cnpj')

    if cnpj_v == 'Manual / total da competência':
        sub_v = mensal_v[mensal_v.competencia.astype(str).eq(comp_v)]
        default_rem = float(sub_v.rendimento_tributavel.sum()) if not sub_v.empty else 0.0
        default_prev = float(sub_v.previdencia_oficial.sum()) if not sub_v.empty else 0.0
    else:
        sub_v = mensal_v[(mensal_v.competencia.astype(str).eq(comp_v)) & (mensal_v.cnpj_declarante.astype(str).eq(cnpj_v))]
        default_rem = float(sub_v.rendimento_tributavel.sum()) if not sub_v.empty else 0.0
        default_prev = float(sub_v.previdencia_oficial.sum()) if not sub_v.empty else 0.0

    c3, c4, c5 = st.columns(3)
    rem_v = c3.number_input('Remuneração / salário de contribuição', min_value=0.0, value=default_rem, step=100.0, format='%.2f', key='verif_rem_' + re.sub(r'\W+', '_', comp_v + '_' + cnpj_v))
    comparar_v = c4.checkbox('Comparar com Previdência da DIRF', value=not sub_v.empty, key='verif_compare')
    prev_v = c5.number_input('Previdência informada na DIRF', min_value=0.0, value=default_prev, step=10.0, format='%.2f', disabled=not comparar_v, key='verif_prev_' + re.sub(r'\W+', '_', comp_v + '_' + cnpj_v))

    ver = verificar_tabela(comp_v, rem_v, prev_v if comparar_v else None)
    if ver.get('status') == 'TABELA_NAO_CADASTRADA':
        st.error('Não há tabela histórica cadastrada para essa competência.')
    else:
        st.write(f"**Metodologia:** {ver['metodologia'].upper()}  ·  **Tabela:** {ver['tabela_id']}  ·  **Teto:** {fmt(ver['teto'])}")
        st.caption(f"Fonte registrada: {ver['fonte']}")
        if ver['status'] == 'COMPATIVEL':
            st.success(f"COMPATÍVEL — calculado {fmt(ver['contribuicao_calculada'])}; DIRF {fmt(ver['previdencia_dirf'])}; diferença {fmt(ver['diferenca_dirf_menos_calculado'])}.")
        elif ver['status'] == 'DIFERENCA_PARA_ANALISE':
            st.warning(f"DIFERENÇA PARA ANÁLISE — calculado {fmt(ver['contribuicao_calculada'])}; DIRF {fmt(ver['previdencia_dirf'])}; diferença {fmt(ver['diferenca_dirf_menos_calculado'])}.")
        else:
            st.info(f"SEM COMPARAÇÃO — contribuição calculada: {fmt(ver['contribuicao_calculada'])}.")

        faixas_df = pd.DataFrame(ver['faixas'])
        if not faixas_df.empty:
            faixas_df['faixa'] = faixas_df['faixa'].map(lambda x: f'Faixa {x}')
            faixas_df['limites'] = faixas_df.apply(lambda r: f"{fmt(r['limite_inferior'])} a {fmt(r['limite_superior'])}", axis=1)
            faixas_df['alíquota'] = faixas_df['aliquota'].map(lambda x: f'{x*100:.2f}%')
            faixas_df['base_na_faixa'] = faixas_df['base_na_faixa'].map(fmt)
            faixas_df['contribuicao'] = faixas_df['contribuicao'].map(fmt)
            cols = ['faixa', 'limites', 'alíquota', 'base_na_faixa', 'contribuicao']
            faixas_df = faixas_df[cols]
            faixas_df.columns = ['Faixa', 'Limite', 'Alíquota', 'Base na faixa', 'Contribuição']
            st.dataframe(faixas_df, use_container_width=True, hide_index=True)

    with st.expander('📚 Tabela histórica cadastrada — 2017 a 2026'):
        historico = []
        for t in TABELAS_HISTORICAS:
            historico.append({
                'Vigência': f"{t['inicio']} a {t['fim']}",
                'Metodologia': t['metodologia'],
                'Faixas': ' · '.join([f"{x[2]*100:g}% até {fmt(x[1])}" for x in t['faixas']]),
                'Teto': t['teto'],
                'Fonte': t['fonte'],
            })
        hist_df = pd.DataFrame(historico)
        st.dataframe(hist_df, use_container_width=True, hide_index=True, column_config={'Teto': st.column_config.NumberColumn('Teto', format='R$ %.2f')})

with tabs[4]:
    st.subheader('Motor de apuração')
    st.write('V1.2: 11% e 20% seguem a lógica da planilha-base. Vínculos classificados como PROGRESSIVA são identificados, mas permanecem em validação nesta versão; use a guia 🔎 Verificação para conferir a tabela histórica antes da incorporação ao motor principal.')
    result = apurar(calc_df, dict(TETOS))
    if result.empty:
        st.warning('Sem competências mensais para apurar.')
    else:
        st.dataframe(result, use_container_width=True, hide_index=True, column_config={
            'soma_contribuicoes_recolhidas': st.column_config.NumberColumn('Contr. recolhida', format='R$ %.2f'),
            'teto_previdenciario': st.column_config.NumberColumn('Teto', format='R$ %.2f'),
            'contribuicao_maxima_11': st.column_config.NumberColumn('Máx. 11%', format='R$ %.2f'),
            'contribuicao_maxima_20': st.column_config.NumberColumn('Máx. 20%', format='R$ %.2f'),
            'contribuicao_maxima_total': st.column_config.NumberColumn('Máx. total', format='R$ %.2f'),
            'contribuicao_acima_teto': st.column_config.NumberColumn('Acima do teto', format='R$ %.2f'),
        })
        pend = result[result.status != 'OK'] if 'status' in result.columns else pd.DataFrame()
        if not pend.empty:
            st.warning(f'{len(pend)} competência(s) dependem de classificação ou teto cadastrado.')

with tabs[5]:
    st.subheader('Demonstração horizontal')
    st.caption('A estrutura é dinâmica: cada vínculo selecionado gera duas colunas, Remuneração e Previdência, como na planilha-base.')
    mensal = calc_df[calc_df.tipo_competencia.eq('mensal')].copy()
    comps = sorted(mensal.competencia.dropna().unique())
    if not comps:
        st.info('Sem dados mensais para os vínculos selecionados.')
    else:
        rec = []
        for comp in comps:
            g = mensal[mensal.competencia.eq(comp)]
            row = {'Competência': comp}
            for cnpj, sg in g.groupby('cnpj_declarante', dropna=False):
                nome = str(sg.nome_declarante_dirf.iloc[0])
                label = f'{nome} | {cnpj}'
                row[label + ' — Remuneração'] = sg.rendimento_tributavel.sum()
                row[label + ' — Previdência'] = sg.previdencia_oficial.sum()
            rec.append(row)
        horiz = pd.DataFrame(rec).fillna(0)
        st.dataframe(horiz, use_container_width=True, hide_index=True, column_config={c: st.column_config.NumberColumn(c, format='R$ %.2f') for c in horiz.columns if c != 'Competência'})
        st.write(f'**{len(mensal["cnpj_declarante"].unique())} vínculo(s) representado(s) nas colunas.**')

with tabs[6]:
    st.subheader('Exportações')
    checks = validate_records(records)
    json_payload = {
        'schema': 'extrator_dirf.v3.2',
        'descricao': 'RAW completo + filtros/agrupamento + classificação 11/20/progressiva + tabela histórica + verificação independente + apuração.',
        'registros': df.to_dict(orient='records'),
        'classificacao_por_cnpj': st.session_state.get('assignments', {}),
        'vinculos_incluidos': sorted(st.session_state.get('included_cnpjs', set())),
        'tetos_utilizados': dict(TETOS),
        'tabelas_historicas': TABELAS_HISTORICAS,
        'validacao_totais': checks,
    }
    st.download_button('Baixar JSON completo + motor', json.dumps(json_payload, ensure_ascii=False, indent=2).encode('utf-8'), 'extracao_dirf_motor_v1_2.json', 'application/json')
    exp = classified.copy()
    exp['competencia_br'] = exp.apply(lambda r: competencia_br(r.competencia, r.tipo_competencia), axis=1)
    st.download_button('Baixar CSV normalizado', csv_bytes(exp), 'extracao_dirf_normalizada.csv', 'text/csv')
    if 'result' in locals() and not result.empty:
        st.download_button('Baixar apuração CSV', csv_bytes(result), 'apuracao_previdenciaria_v1_2.csv', 'text/csv')
    st.download_button('Baixar JSON RAW somente', json.dumps({'schema': 'extrator_dirf.v3.2', 'registros': records}, ensure_ascii=False, indent=2).encode('utf-8'), 'extracao_dirf_raw.json', 'application/json')
    if checks:
        diverg = [x for x in checks if x.get('status') != 'OK']
        st.subheader('Validação dos totais')
        st.dataframe(pd.DataFrame(checks), use_container_width=True, hide_index=True)
        if diverg:
            st.warning(f'{len(diverg)} grupo(s) apresentam divergência de soma mensal x total DIRF. Isso precisa ser auditado antes de usar o resultado como prova de cálculo.')

with st.expander('Registro bruto / auditoria'):
    st.write('Todos os campos extraídos permanecem disponíveis no JSON e nesta visualização.')
    st.dataframe(df, use_container_width=True, hide_index=True)
