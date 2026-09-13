import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from dirf_core import extract_pdf, validate_records
from motor_previdenciario import classify_declarante, observed_rate, apurar, verificar_tabela
from tabelas_previdenciarias import TETOS, TABELAS_HISTORICAS

st.set_page_config(page_title='Extrator DIRF + Motor Previdenciário', page_icon='📄', layout='wide')

TOLERANCIA_PADRAO = 0.01


def fmt(v):
    try:
        return f'R$ {float(v):,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return ''


def fmt4(v):
    try:
        return f'R$ {float(v):,.4f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception:
        return ''


def data_br(v):
    s = str(v or '').strip()
    m = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', s)
    return f'{m.group(3)}/{m.group(2)}/{m.group(1)}' if m else s


def competencia_br(c, t):
    if t == '13º' and isinstance(c, str):
        return f'13º/{c[:4]}' if c.endswith('-13') else '13º'
    if t == 'mensal' and isinstance(c, str):
        m = re.fullmatch(r'(\d{4})-(\d{2})', c)
        return f'{m.group(2)}/{m.group(1)}' if m else ''
    return ''


def csv_bytes(df):
    return df.to_csv(index=False, sep=';', decimal=',', encoding='utf-8-sig', lineterminator='\r\n').encode('utf-8-sig')


def normalize_cnpj(v):
    return str(v or '').strip()


# Códigos identificados na DIRF como rendimentos financeiros/investimentos,
# sem caráter de vínculo previdenciário para o agrupamento desta aplicação.
# Eles permanecem integralmente no RAW e na auditoria; apenas ficam fora da
# seleção inicial do agrupamento.
CODIGOS_NAO_PREVIDENCIARIOS = {
    '5706',  # juros remuneratórios do capital próprio
    '5557',  # mercado/renda variável
    '6800',  # fundos de investimento
    '6813',  # fundos de ações
    '8053',  # aplicações financeiras/renda fixa
}


def codigo_label(codigo, descricao=''):
    codigo = str(codigo or '').strip()
    desc = str(descricao or '').strip()
    return f'{codigo} — {desc}' if desc else codigo


def resumo_fonte(df, cnpj):
    sub = df[df['cnpj_declarante'].astype(str).eq(str(cnpj))].copy()
    nomes = sorted(sub['nome_declarante_dirf'].dropna().astype(str).unique(), key=str.casefold)
    cod_rows = sub[['codigo_receita', 'descricao_codigo_receita']].drop_duplicates()
    codigos = [codigo_label(r.codigo_receita, r.descricao_codigo_receita) for r in cod_rows.itertuples(index=False)]
    codigos_num = set(sub['codigo_receita'].dropna().astype(str).str.strip())
    mensal = sub[sub['tipo_competencia'].eq('mensal')]
    remun = float(mensal['rendimento_tributavel'].sum())
    prev = float(mensal['previdencia_oficial'].sum())
    somente_nao_prev = bool(codigos_num) and codigos_num.issubset(CODIGOS_NAO_PREVIDENCIARIOS)
    sem_movimento = abs(remun) < 0.005 and abs(prev) < 0.005
    if somente_nao_prev:
        status = 'não previdenciária'
        motivo = 'Código DIRF de investimento/rendimento financeiro'
        sugerir = False
    elif sem_movimento:
        status = 'sem movimento previdenciário'
        motivo = 'Sem remuneração e sem Previdência Oficial mensal'
        sugerir = False
    else:
        status = 'potencial previdenciária'
        motivo = 'Fonte com remuneração e/ou Previdência Oficial para análise'
        sugerir = True
    return {
        'cnpj': str(cnpj),
        'nome': ' / '.join(nomes) or 'Fonte sem nome identificado',
        'codigos': codigos,
        'codigos_num': codigos_num,
        'remuneracao': remun,
        'previdencia': prev,
        'status': status,
        'motivo': motivo,
        'sugerir': sugerir,
    }


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


st.title('Extrator DIRF + Motor Previdenciário V1.2.4')
st.caption('Extração preservada + seleção inteligente de fontes + agrupamento de vínculos/declarantes + classificação separada + verificação anual/mensal + apuração por competência.')

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

fontes = [resumo_fonte(df, cnpj) for cnpj in sorted(df['cnpj_declarante'].dropna().astype(str).unique())]
sugeridas = {v['cnpj'] for v in fontes if v['sugerir']}
if 'included_cnpjs' not in st.session_state:
    st.session_state.included_cnpjs = set(sugeridas)
else:
    # Novas fontes que apareçam após uma troca de arquivo entram apenas se
    # forem potencialmente previdenciárias; escolhas manuais existentes são preservadas.
    st.session_state.included_cnpjs |= (sugeridas - set(st.session_state.included_cnpjs))

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
    st.subheader('Agrupamento de vínculos / fontes pagadoras')
    st.caption('A identificação principal é o nome da fonte. O CNPJ permanece como dado de conferência. O agrupamento é operacional: a seleção define o que participa das etapas previdenciárias, sem excluir nada da extração RAW.')
    st.info('Fontes de investimentos/rendimentos financeiros identificadas pelos códigos DIRF 5706, 5557, 6800, 6813 e 8053 ficam desmarcadas por padrão. Fontes sem remuneração e sem Previdência Oficial mensal também ficam fora da seleção inicial.')

    b1, b2, b3 = st.columns(3)
    if b1.button('✓ Selecionar sugeridas', use_container_width=True, key='sel_sugeridas'):
        st.session_state.included_cnpjs = set(sugeridas)
        st.rerun()
    if b2.button('☑ Incluir todas', use_container_width=True, key='sel_todas'):
        st.session_state.included_cnpjs = {v['cnpj'] for v in fontes}
        st.rerun()
    if b3.button('☐ Limpar seleção', use_container_width=True, key='sel_nenhuma'):
        st.session_state.included_cnpjs = set()
        st.rerun()

    st.markdown(f'**{len(sugeridas)} fonte(s) sugerida(s)** · **{len(fontes) - len(sugeridas)} fora da seleção inicial** · **{len(st.session_state.included_cnpjs)} selecionada(s)**')

    sugeridas_rows = [v for v in fontes if v['sugerir']]
    outras_rows = [v for v in fontes if not v['sugerir']]

    if sugeridas_rows:
        st.markdown('### 🟢 Fontes sugeridas para análise previdenciária')
        for v in sugeridas_rows:
            key = 'include_' + re.sub(r'\W+', '_', v['cnpj'])
            default = v['cnpj'] in st.session_state.included_cnpjs
            include = st.checkbox(f"**{v['nome']}**", value=default, key=key)
            if include:
                st.session_state.included_cnpjs.add(v['cnpj'])
            else:
                st.session_state.included_cnpjs.discard(v['cnpj'])
            c1, c2, c3 = st.columns([3.5, 2.2, 2.2])
            c1.markdown(f"`CNPJ {v['cnpj']}`  \n**Código(s):** {' · '.join(v['codigos']) if v['codigos'] else '—'}")
            c2.write(f"Remuneração mensal acumulada: {fmt(v['remuneracao'])}")
            c3.write(f"Previdência mensal acumulada: {fmt(v['previdencia'])}")
            st.divider()

    with st.expander(f'⚪ Outras fontes — {len(outras_rows)} não selecionadas por padrão', expanded=False):
        if outras_rows:
            for v in outras_rows:
                key = 'include_other_' + re.sub(r'\W+', '_', v['cnpj'])
                default = v['cnpj'] in st.session_state.included_cnpjs
                include = st.checkbox(f"**{v['nome']}**", value=default, key=key)
                if include:
                    st.session_state.included_cnpjs.add(v['cnpj'])
                else:
                    st.session_state.included_cnpjs.discard(v['cnpj'])
                c1, c2, c3 = st.columns([3.5, 2.2, 2.2])
                c1.markdown(f"`CNPJ {v['cnpj']}`  \n**Código(s):** {' · '.join(v['codigos']) if v['codigos'] else '—'}  \n*{v['motivo']}.*")
                c2.write(f"Remuneração mensal: {fmt(v['remuneracao'])}")
                c3.write(f"Previdência mensal: {fmt(v['previdencia'])}")
                st.divider()

    st.subheader('Resumo do agrupamento selecionado')
    selected = sorted(st.session_state.included_cnpjs)
    resumo_base = df[df['cnpj_declarante'].isin(selected) & df['tipo_competencia'].eq('mensal')].copy()
    resumo = resumo_base.groupby('cnpj_declarante', as_index=False).agg(
        nome_declarante_dirf=('nome_declarante_dirf', lambda s: ' / '.join(sorted(set(str(x) for x in s.dropna()), key=str.casefold))),
        remuneracao=('rendimento_tributavel', 'sum'),
        previdencia=('previdencia_oficial', 'sum'),
    )
    if resumo.empty:
        st.warning('Nenhuma fonte selecionada.')
    else:
        resumo = resumo.sort_values(['nome_declarante_dirf', 'cnpj_declarante'])
        st.dataframe(resumo, use_container_width=True, hide_index=True, column_config={'remuneracao': st.column_config.NumberColumn('Remuneração', format='R$ %.2f'), 'previdencia': st.column_config.NumberColumn('Previdência', format='R$ %.2f')})
        st.write(f'**{len(selected)} fonte(s) selecionada(s).**')

# Apply the selected vínculo filter to the calculation layer only.
calc_df = classified[classified['cnpj_declarante'].isin(st.session_state.included_cnpjs)].copy()

with tabs[2]:
    st.subheader('Classificação previdenciária por fonte / vínculo')
    st.info('Somente as fontes selecionadas em 🔗 Agrupamento de vínculos aparecem aqui. As demais permanecem integralmente no RAW e na auditoria. A classificação é manual e persistida durante a sessão. A alíquota efetiva observada serve apenas como diagnóstico. A opção PROGRESSIVA habilita a conferência da tabela histórica, mas permanece separada do cálculo principal enquanto a validação não for concluída.')
    st.caption(f'**{len(st.session_state.included_cnpjs)} fonte(s) selecionada(s) para classificação.**')
    if not st.session_state.included_cnpjs:
        st.warning('Nenhuma fonte foi selecionada no agrupamento. Selecione pelo menos uma fonte em 🔗 Agrupamento de vínculos para classificá-la.')
    # A classificação trabalha somente com as fontes selecionadas no agrupamento.
    # Fontes não selecionadas continuam no RAW/auditoria, mas não recebem classificação.
    cnpjs = sorted(st.session_state.included_cnpjs)
    rows = []
    for cnpj in cnpjs:
        sub = df[df.cnpj_declarante.astype(str).eq(cnpj)]
        nomes = ' / '.join(sorted(sub.nome_declarante_dirf.dropna().astype(str).unique(), key=str.casefold))
        cod_rows = sub[['codigo_receita', 'descricao_codigo_receita']].drop_duplicates()
        cod = ' / '.join(codigo_label(r.codigo_receita, r.descricao_codigo_receita) for r in cod_rows.itertuples(index=False))
        rates = sub.loc[(sub.rendimento_tributavel > 0) & (sub.previdencia_oficial.notna()), 'aliquota_efetiva_observada']
        med = float(rates.median() * 100) if len(rates) else None
        current = st.session_state.assignments.get(cnpj, 'nao_definido')
        a, b, c, d = st.columns([3.2, 2.8, 2, 1.8])
        a.markdown(f'**{nomes or "Fonte sem nome identificado"}**\n\n`CNPJ {cnpj}`')
        b.write(cod)
        c.write(f'{med:.2f}%' if med is not None else '—')
        val = d.selectbox('Grupo', ['nao_definido', '11', '20', 'progressiva'], index=['nao_definido', '11', '20', 'progressiva'].index(current), key='grp_' + re.sub(r'\W+', '_', cnpj))
        st.session_state.assignments[cnpj] = val
        rows.append({'CNPJ': cnpj, 'Declarante': nomes, 'Código DIRF': cod, 'Alíquota efetiva mediana': med, 'Grupo': val, 'Incluído': cnpj in st.session_state.included_cnpjs})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption('“nao_definido” impede a apuração silenciosa daquela competência. “progressiva” identifica o vínculo para a verificação histórica; o motor principal ainda sinaliza PROGRESSIVA_EM_VALIDACAO.')

classified = classify_declarante(df, st.session_state.get('assignments', {}))
calc_df = classified[classified['cnpj_declarante'].isin(st.session_state.included_cnpjs)].copy()

with tabs[3]:
    st.subheader('Verificação da Alíquota Previdenciária')
    st.caption('Bancada independente para validar a tabela histórica contra os valores reais da DIRF. A navegação é anual por fonte, mas o cálculo permanece mensal, competência a competência.')

    with st.expander('ⓘ Como funciona esta verificação', expanded=True):
        st.markdown('''
**Selecione o ano e a fonte.** O sistema carrega automaticamente as competências mensais encontradas para aquela fonte naquele ano.

- O **ano civil** é apenas o nível de navegação e consolidação.
- Cada **competência** identifica sua própria tabela e metodologia.
- **2017 a 2019:** metodologia tradicional.
- **Janeiro e fevereiro de 2020:** metodologia tradicional.
- **A partir de março de 2020:** metodologia progressiva.
- Mudanças de vigência dentro do ano, como em 2020 e 2023, são respeitadas automaticamente.
- O 13º permanece separado da remuneração mensal.

A guia compara o valor calculado com a **Previdência Oficial da DIRF** quando houver informação. Uma diferença não significa, sozinha, erro: ela gera um ponto para análise.
''')

    mensal_v = calc_df[calc_df.tipo_competencia.eq('mensal')].copy()
    if mensal_v.empty:
        st.warning('Não há competências mensais nas fontes selecionadas. Selecione fontes em 🔗 Agrupamento de vínculos.')
    else:
        anos_v = sorted(mensal_v['ano_calendario'].dropna().astype(str).unique())
        c1, c2 = st.columns([1, 2.2])
        ano_v = c1.selectbox('Ano-calendário', anos_v, key='verif_ano')
        fontes_v = [v for v in fontes if v['cnpj'] in st.session_state.included_cnpjs]
        fonte_map = {f"{v['nome']} — CNPJ {v['cnpj']}": v['cnpj'] for v in fontes_v}
        if not fonte_map:
            st.warning('Nenhuma fonte selecionada para a verificação. Volte ao 🔗 Agrupamento de vínculos.')
        else:
            fonte_label = c2.selectbox('Fonte / vínculo', list(fonte_map.keys()), key='verif_fonte_anual')
            c3, c4 = st.columns([1.2, 2.8])
            usar_personalizada = c3.checkbox('Usar tolerância personalizada', value=False, key='verif_tol_personalizada')
            if usar_personalizada:
                tolerancia_v = c4.number_input('Tolerância para classificação (R$)', min_value=0.0, value=TOLERANCIA_PADRAO, step=0.001, format='%.3f', key='verif_tolerancia')
                origem_tolerancia = 'USUÁRIO'
            else:
                tolerancia_v = TOLERANCIA_PADRAO
                origem_tolerancia = 'SISTEMA — PADRÃO'
                c4.caption(f'Critério padrão: {fmt(tolerancia_v)}. A comparação usa a diferença interna, antes do arredondamento visual.')
            st.caption(f'Critério de comparação: tolerância {fmt(tolerancia_v)} — {origem_tolerancia}. A tolerância altera apenas o status da diferença; não altera o cálculo previdenciário.')
            cnpj_v = fonte_map[fonte_label]
            sub_ano = mensal_v[(mensal_v['ano_calendario'].astype(str).eq(str(ano_v))) & (mensal_v['cnpj_declarante'].astype(str).eq(str(cnpj_v)))].copy().sort_values('competencia')
            if sub_ano.empty:
                st.info('Não foram encontrados registros mensais dessa fonte no ano selecionado.')
            else:
                resultados_v = []
                for _, row in sub_ano.iterrows():
                    comp = str(row['competencia'])
                    rem = float(row.get('rendimento_tributavel', 0) or 0)
                    prev = float(row.get('previdencia_oficial', 0) or 0)
                    resultados_v.append(verificar_tabela(comp, rem, prev, tolerancia=tolerancia_v))

                for r in resultados_v:
                    r['tolerancia_utilizada'] = tolerancia_v
                    r['tolerancia_origem'] = origem_tolerancia

                total_rem = sum(r['remuneracao'] for r in resultados_v)
                total_prev = sum((r['previdencia_dirf'] or 0) for r in resultados_v)
                total_calc = sum(r.get('contribuicao_calculada', 0) for r in resultados_v)
                total_diff = round(total_prev - total_calc, 2)
                compat = sum(r['status'] == 'COMPATIVEL' for r in resultados_v)
                diffs = sum(r['status'] == 'DIFERENCA_PARA_ANALISE' for r in resultados_v)
                semcomp = sum(r['status'] == 'SEM_COMPARACAO' for r in resultados_v)
                semtabela = sum(r['status'] == 'TABELA_NAO_CADASTRADA' for r in resultados_v)

                nome_fonte = fonte_label.split(' — CNPJ ')[0]
                st.markdown(f'### {ano_v} — {nome_fonte}')
                st.caption(f'CNPJ {cnpj_v} · {len(resultados_v)} competência(s) encontrada(s)')
                m1, m2, m3, m4 = st.columns(4)
                m1.metric('Remuneração', fmt(total_rem))
                m2.metric('Previdência DIRF', fmt(total_prev))
                m3.metric('Calculada', fmt(total_calc))
                m4.metric('Diferença', fmt(total_diff))
                st.write(f'**✓ {compat} compatível(is)** · **⚠ {diffs} para análise** · **— {semcomp} sem comparação** · **! {semtabela} sem tabela cadastrada**')

                resumo_rows = []
                for r in resultados_v:
                    status_label = {'COMPATIVEL':'✓ Compatível','DIFERENCA_PARA_ANALISE':'⚠ Para análise','SEM_COMPARACAO':'— Sem comparação','TABELA_NAO_CADASTRADA':'! Sem tabela'}.get(r['status'], r['status'])
                    resumo_rows.append({'Competência':competencia_br(r.get('competencia',''), 'mensal'),'Metodologia':str(r.get('metodologia','')).upper() or '—','Tabela':r.get('tabela_id','—'),'Remuneração':r.get('remuneracao',0),'Previdência DIRF':r.get('previdencia_dirf',0) if r.get('previdencia_dirf') is not None else None,'Calculada':r.get('contribuicao_calculada',0),'Diferença':r.get('diferenca_dirf_menos_calculado',0) if r.get('diferenca_dirf_menos_calculado') is not None else None,'Status':status_label})
                resumo_df = pd.DataFrame(resumo_rows)
                st.dataframe(resumo_df, use_container_width=True, hide_index=True, column_config={'Remuneração':st.column_config.NumberColumn('Remuneração',format='R$ %.2f'),'Previdência DIRF':st.column_config.NumberColumn('Previdência DIRF',format='R$ %.2f'),'Calculada':st.column_config.NumberColumn('Calculada',format='R$ %.2f'),'Diferença':st.column_config.NumberColumn('Diferença',format='R$ %.2f')})

                st.markdown('### Detalhamento por competência')
                for r in resultados_v:
                    comp = competencia_br(r.get('competencia',''), 'mensal')
                    status = r.get('status','')
                    label = {'COMPATIVEL':'✓','DIFERENCA_PARA_ANALISE':'⚠','SEM_COMPARACAO':'—','TABELA_NAO_CADASTRADA':'!'}.get(status,'•')
                    with st.expander(f'{label} {comp} — Remuneração {fmt(r.get("remuneracao",0))} — Calculada {fmt(r.get("contribuicao_calculada",0))}'):
                        if status == 'TABELA_NAO_CADASTRADA':
                            st.error('Não há tabela histórica cadastrada para essa competência.')
                            continue
                        st.write(f"**Metodologia:** {r['metodologia'].upper()} · **Tabela:** {r['tabela_id']} · **Teto:** {fmt(r['teto'])}")
                        st.caption(f"Fonte registrada: {r['fonte']}")
                        st.caption(f"Critério de tolerância: {fmt(r.get('tolerancia_utilizada', tolerancia_v))} — {r.get('tolerancia_origem', origem_tolerancia)}. Diferença interna usada no status: {fmt4(r.get('diferenca_bruta')) if r.get('diferenca_bruta') is not None else '—'}")
                        if r.get('previdencia_dirf') is not None:
                            if status == 'COMPATIVEL':
                                st.success(f"COMPATÍVEL — calculado {fmt(r['contribuicao_calculada'])}; DIRF {fmt(r['previdencia_dirf'])}; diferença {fmt(r['diferenca_dirf_menos_calculado'])}.")
                            else:
                                st.warning(f"DIFERENÇA PARA ANÁLISE — calculado {fmt(r['contribuicao_calculada'])}; DIRF {fmt(r['previdencia_dirf'])}; diferença {fmt(r['diferenca_dirf_menos_calculado'])}.")
                        else:
                            st.info(f"SEM COMPARAÇÃO — contribuição calculada: {fmt(r['contribuicao_calculada'])}.")
                        faixas_df = pd.DataFrame(r['faixas'])
                        if not faixas_df.empty:
                            faixas_df['faixa'] = faixas_df['faixa'].map(lambda x: f'Faixa {x}')
                            faixas_df['limites'] = faixas_df.apply(lambda rr: f"{fmt(rr['limite_inferior'])} a {fmt(rr['limite_superior'])}", axis=1)
                            faixas_df['alíquota'] = faixas_df['aliquota'].map(lambda x: f'{x*100:.2f}%')
                            faixas_df['base_na_faixa'] = faixas_df['base_na_faixa'].map(fmt)
                            faixas_df['contribuicao'] = faixas_df['contribuicao'].map(fmt)
                            faixas_df = faixas_df[['faixa','limites','alíquota','base_na_faixa','contribuicao']]
                            faixas_df.columns = ['Faixa','Limite','Alíquota','Base na faixa','Contribuição']
                            st.dataframe(faixas_df, use_container_width=True, hide_index=True)

    with st.expander('📚 Tabela histórica cadastrada — 2017 a 2026'):
        historico = []
        for t in TABELAS_HISTORICAS:
            historico.append({'Vigência':f"{data_br(t['inicio'])} a {data_br(t['fim'])}",'Metodologia':t['metodologia'],'Faixas':' · '.join([f"{x[2]*100:g}% até {fmt(x[1])}" for x in t['faixas']]),'Teto':t['teto'],'Fonte':t['fonte']})
        hist_df = pd.DataFrame(historico)
        st.dataframe(hist_df, use_container_width=True, hide_index=True, column_config={'Teto':st.column_config.NumberColumn('Teto',format='R$ %.2f')})

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
            row = {'Competência': competencia_br(comp, 'mensal')}
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
        'schema': 'extrator_dirf.v3.3',
        'descricao': 'RAW completo + filtros + agrupamento inteligente por fonte + classificação 11/20/progressiva + tabela histórica + verificação independente + apuração.',
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
    st.download_button('Baixar JSON RAW somente', json.dumps({'schema': 'extrator_dirf.v3.3', 'registros': records}, ensure_ascii=False, indent=2).encode('utf-8'), 'extracao_dirf_raw.json', 'application/json')
    if checks:
        diverg = [x for x in checks if x.get('status') != 'OK']
        st.subheader('Validação dos totais')
        st.dataframe(pd.DataFrame(checks), use_container_width=True, hide_index=True)
        if diverg:
            st.warning(f'{len(diverg)} grupo(s) apresentam divergência de soma mensal x total DIRF. Isso precisa ser auditado antes de usar o resultado como prova de cálculo.')

with st.expander('Registro bruto / auditoria'):
    st.write('Todos os campos extraídos permanecem disponíveis no JSON e nesta visualização.')
    st.dataframe(df, use_container_width=True, hide_index=True)
