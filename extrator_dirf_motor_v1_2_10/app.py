import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from dirf_core import extract_pdf, validate_records
from motor_previdenciario import classify_declarante, observed_rate, apurar, verificar_tabela, verificar_13o, verificar_por_grupo, calcular_faixas, tabela_por_competencia
from classificador_previdenciario import classificar_fontes
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


st.title('Extrator DIRF + Motor Previdenciário V1.2.9')
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
if 'classification_meta' not in st.session_state:
    st.session_state.classification_meta = {}

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
    st.info('O sistema gera uma sugestão automática com regras determinísticas e evidências auditáveis. Você pode aceitar a sugestão ou editar a classificação. A alíquota efetiva observada é apenas evidência auxiliar e não define, sozinha, o grupo previdenciário.')

    cnpjs = sorted(st.session_state.included_cnpjs)
    sugestoes = classificar_fontes(df, cnpjs, st.session_state.assignments, st.session_state.classification_meta)
    st.caption(f'**{len(cnpjs)} fonte(s) selecionada(s).** A intervenção manual fica restrita às classificações que exigirem confirmação ou às alterações feitas pelo usuário.')

    nomes_grupo = {
        'nao_definido': 'Não definido — requer confirmação',
        '11': '11% — contribuição fixa',
        '20': '20% — contribuição fixa',
        'progressiva': 'Progressiva — aplicar tabela histórica',
    }
    conf_label = {'alta': '🟢 Alta', 'media': '🟡 Média', 'baixa': '🔴 Baixa', 'confirmada': '🔵 Confirmada pelo usuário'}

    if not cnpjs:
        st.warning('Nenhuma fonte foi selecionada no agrupamento. Selecione pelo menos uma fonte em 🔗 Agrupamento de vínculos para classificá-la.')
    else:
        for cnpj in cnpjs:
            sub = df[df.cnpj_declarante.astype(str).eq(cnpj)]
            nomes = ' / '.join(sorted(sub.nome_declarante_dirf.dropna().astype(str).unique(), key=str.casefold))
            nome_exibicao = nomes or 'Fonte sem nome identificado'
            cod_rows = sub[['codigo_receita', 'descricao_codigo_receita']].drop_duplicates()
            cod = ' / '.join(codigo_label(r.codigo_receita, r.descricao_codigo_receita) for r in cod_rows.itertuples(index=False)) or '—'
            rates = sub.loc[(sub.rendimento_tributavel > 0) & (sub.previdencia_oficial.notna()), 'aliquota_efetiva_observada']
            med = float(rates.median() * 100) if len(rates) else None
            meta = sugestoes[cnpj]
            current = st.session_state.assignments.get(cnpj, meta['classificacao_sugerida'])

            with st.container(border=True):
                st.markdown(f'### {nome_exibicao}')
                st.caption(f'CNPJ {cnpj}')
                c1, c2, c3 = st.columns([2.6, 1.25, 2.15], vertical_alignment='top')
                with c1:
                    st.markdown('**Código(s) DIRF**')
                    st.write(cod)
                    st.markdown('**Sugestão automática**')
                    st.write(nomes_grupo.get(meta['classificacao_sugerida'], meta['classificacao_sugerida']))
                    st.caption(f'Confiança: {conf_label.get(meta["nivel_confianca"], meta["nivel_confianca"])}')
                with c2:
                    st.markdown('**Alíquota efetiva observada**')
                    st.markdown(f'### {f"{med:.2f}%".replace(".", ",") if med is not None else "—"}')
                    st.caption('Diagnóstico; não define o grupo.')
                with c3:
                    st.markdown('**Classificação final**')
                    val = st.selectbox(
                        'Editar classificação',
                        ['nao_definido', '11', '20', 'progressiva'],
                        index=['nao_definido', '11', '20', 'progressiva'].index(current),
                        key='grp_' + re.sub(r'\W+', '_', cnpj),
                        format_func=lambda x: nomes_grupo.get(x, x),
                        label_visibility='collapsed',
                    )
                anterior = st.session_state.assignments.get(cnpj)
                st.session_state.assignments[cnpj] = val
                if anterior is None and val == meta['classificacao_sugerida'] and val != 'nao_definido':
                    st.session_state.classification_meta[cnpj] = {
                        **meta, 'data_classificacao': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'usuario_confirmador': None,
                    }
                elif anterior is not None and val != anterior:
                    st.session_state.classification_meta[cnpj] = {
                        **meta, 'classificacao_final': val, 'origem_classificacao': 'usuario',
                        'nivel_confianca': 'confirmada',
                        'data_classificacao': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'usuario_confirmador': 'usuario',
                    }
                elif cnpj not in st.session_state.classification_meta:
                    st.session_state.classification_meta[cnpj] = meta

                with st.expander('🔍 Evidências e regra utilizada'):
                    for ev in meta['evidencias']:
                        st.write('• ' + ev)
                    st.caption(f"Regra: {meta['regra_classificacao']} · versão {meta['versao_regra']}")

                final_meta = st.session_state.classification_meta.get(cnpj, meta)
                if val == 'nao_definido':
                    st.warning('⚠️ Confirmação necessária. A Verificação não realizará classificação previdenciária silenciosa para esta fonte.')
                elif final_meta.get('origem_classificacao') == 'usuario':
                    st.info(f'✏️ Classificação definida pelo usuário: {nomes_grupo[val]}.')
                elif meta['nivel_confianca'] == 'alta':
                    st.success(f'✓ Classificação automática: {nomes_grupo[val]}.')
                else:
                    st.warning(f'⚠️ Sugestão {nomes_grupo[val]} com confiança {conf_label.get(meta["nivel_confianca"], meta["nivel_confianca"])}. Recomenda-se confirmar.')

    st.caption('Regra de segurança: códigos DIRF e alíquota efetiva não são tratados isoladamente como fundamento jurídico. Sugestões com evidência insuficiente permanecem pendentes para confirmação humana.')

classified = classify_declarante(df, st.session_state.get('assignments', {}))
calc_df = classified[classified['cnpj_declarante'].isin(st.session_state.included_cnpjs)].copy()

with tabs[3]:
    st.subheader('Verificação da Alíquota Previdenciária')
    st.caption('Bancada independente para validar a tabela histórica contra os valores reais da DIRF. A navegação pode abranger um ano, um intervalo ou todo o histórico disponível; a verificação trata cada competência mensal e cada 13º separadamente.')

    with st.expander('ⓘ Como funciona esta verificação', expanded=True):
        st.markdown("""
**Selecione a fonte e o período do histórico.** O sistema carrega automaticamente as competências mensais e os 13º encontrados para aquela fonte dentro do período escolhido.

- O **período selecionado** serve para navegação e consolidação; o cálculo continua sendo feito competência a competência.
- Você pode analisar **todos os anos disponíveis**, um **intervalo de anos** ou apenas um ano.
- Cada **competência** identifica sua própria tabela e metodologia.
- **2017 a 2019:** metodologia tradicional.
- **Janeiro e fevereiro de 2020:** metodologia tradicional.
- **A partir de março de 2020:** metodologia progressiva.
- Mudanças de vigência dentro do ano, como em 2020 e 2023, são respeitadas automaticamente.
- O **13º aparece imediatamente após dezembro de cada ano** e permanece separado da remuneração mensal para aplicação das faixas.

A guia compara o valor calculado com a **Previdência Oficial da DIRF** quando houver informação. No **13º**, a referência individual não é conclusiva quando existem múltiplos vínculos; por isso o sistema o marca para **análise conjunta**, sem misturá-lo a dezembro.
""")

    mensal_v = calc_df[calc_df.tipo_competencia.isin(['mensal', '13º'])].copy()
    if mensal_v.empty:
        st.warning('Não há competências mensais ou de 13º nas fontes selecionadas. Selecione fontes em 🔗 Agrupamento de vínculos.')
    else:
        anos_v = sorted(mensal_v['ano_calendario'].dropna().astype(str).unique())
        fontes_v = [v for v in fontes if v['cnpj'] in st.session_state.included_cnpjs]
        fonte_map = {f"{v['nome']} — CNPJ {v['cnpj']}": v['cnpj'] for v in fontes_v}
        if not fonte_map:
            st.warning('Nenhuma fonte selecionada para a verificação. Volte ao 🔗 Agrupamento de vínculos.')
        else:
            c1, c2 = st.columns([1.2, 2.8])
            modo_periodo = c1.selectbox('Período do histórico', ['Todos os anos disponíveis', 'Intervalo de anos', 'Um ano'], key='verif_modo_periodo')
            fonte_label = c2.selectbox('Fonte / vínculo', list(fonte_map.keys()), key='verif_fonte_historico')

            if modo_periodo == 'Todos os anos disponíveis':
                anos_selecionados = anos_v
                periodo_label = f'{anos_v[0]} a {anos_v[-1]}' if len(anos_v) > 1 else anos_v[0]
            elif modo_periodo == 'Um ano':
                ano_v = st.selectbox('Ano-calendário', anos_v, key='verif_ano_unico')
                anos_selecionados = [str(ano_v)]
                periodo_label = str(ano_v)
            else:
                ca, cb = st.columns(2)
                ano_inicio = ca.selectbox('Ano inicial', anos_v, index=0, key='verif_ano_inicio')
                ano_fim = cb.selectbox('Ano final', anos_v, index=len(anos_v)-1, key='verif_ano_fim')
                a, b = sorted([int(ano_inicio), int(ano_fim)])
                anos_disponiveis = set(anos_v)
                anos_selecionados = [str(x) for x in range(a, b + 1) if str(x) in anos_disponiveis]
                periodo_label = f'{a} a {b}'

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
            sub_hist = mensal_v[
                mensal_v['ano_calendario'].astype(str).isin(anos_selecionados)
                & mensal_v['cnpj_declarante'].astype(str).eq(str(cnpj_v))
            ].copy()

            if sub_hist.empty:
                st.info('Não foram encontrados registros mensais ou de 13º dessa fonte no período selecionado.')
            else:
                # Consolida registros da mesma fonte na mesma competência antes da verificação.
                # O 13º é mantido como tipo próprio e nunca é agregado ao mês de dezembro.
                sub_hist['competencia'] = sub_hist['competencia'].astype(str)
                sub_hist['tipo_competencia'] = sub_hist['tipo_competencia'].astype(str)
                agrupado = sub_hist.groupby(['competencia', 'ano_calendario', 'tipo_competencia'], as_index=False).agg(
                    rendimento_tributavel=('rendimento_tributavel', 'sum'),
                    previdencia_oficial=('previdencia_oficial', 'sum'),
                )

                # Ordem visual: janeiro...dezembro e, logo após dezembro, o 13º do ano.
                def chave_competencia(row):
                    ano = int(row['ano_calendario']) if str(row['ano_calendario']).isdigit() else 9999
                    tipo = str(row['tipo_competencia'])
                    if tipo == '13º':
                        return (ano, 13)
                    m = re.fullmatch(r'\d{4}-(\d{2})', str(row['competencia']))
                    mes = int(m.group(1)) if m else 99
                    return (ano, mes)

                agrupado['_ord_verificacao'] = agrupado.apply(chave_competencia, axis=1)
                agrupado = agrupado.sort_values('_ord_verificacao').drop(columns='_ord_verificacao')

                resultados_v = []
                for _, row in agrupado.iterrows():
                    comp = str(row['competencia'])
                    tipo = str(row['tipo_competencia'])
                    rem = float(row.get('rendimento_tributavel', 0) or 0)
                    prev = float(row.get('previdencia_oficial', 0) or 0)
                    grupo_fonte = str(row.get('grupo_previdenciario', 'nao_definido'))
                    if tipo == '13º':
                        resultado = verificar_13o(row.get('ano_calendario'), rem, prev, tolerancia=tolerancia_v)
                    elif grupo_fonte in ('11', '20', 'progressiva'):
                        resultado = verificar_por_grupo(comp, rem, grupo_fonte, prev, tolerancia=tolerancia_v, tipo_competencia=tipo)
                    else:
                        resultado = verificar_tabela(comp, rem, prev, tolerancia=tolerancia_v)
                    resultado['tipo_competencia'] = tipo
                    resultado['grupo_previdenciario'] = grupo_fonte
                    resultados_v.append(resultado)

                for r in resultados_v:
                    r['tolerancia_utilizada'] = tolerancia_v
                    r['tolerancia_origem'] = origem_tolerancia

                total_rem = sum(r['remuneracao'] for r in resultados_v)
                total_prev = sum((r['previdencia_dirf'] or 0) for r in resultados_v)
                total_calc = sum(r.get('contribuicao_calculada', 0) for r in resultados_v)
                total_diff = round(total_prev - total_calc, 2)
                compat = sum(r['status'] == 'COMPATIVEL' for r in resultados_v)
                diffs = sum(r['status'] == 'DIFERENCA_PARA_ANALISE' for r in resultados_v)
                analise_13 = sum(r['status'] == 'ANALISE_13O_CONJUNTA' for r in resultados_v)
                semcomp = sum(r['status'] == 'SEM_COMPARACAO' for r in resultados_v)
                semtabela = sum(r['status'] == 'TABELA_NAO_CADASTRADA' for r in resultados_v)

                nome_fonte = fonte_label.split(' — CNPJ ')[0]
                st.markdown(f'### Histórico — {nome_fonte}')
                n_mensais = sum(r.get('tipo_competencia') == 'mensal' for r in resultados_v)
                n_13 = sum(r.get('tipo_competencia') == '13º' for r in resultados_v)
                st.caption(f'CNPJ {cnpj_v} · período {periodo_label} · {n_mensais} competência(s) mensal(is) + {n_13} 13º encontrado(s)')
                m1, m2, m3, m4 = st.columns(4)
                m1.metric('Remuneração', fmt(total_rem))
                m2.metric('Previdência DIRF', fmt(total_prev))
                m3.metric('Calculada', fmt(total_calc))
                m4.metric('Diferença', fmt(total_diff))
                st.write(f'**✓ {compat} compatível(is)** · **⚠ {diffs} para análise** · **📌 {analise_13} 13º para análise conjunta** · **— {semcomp} sem comparação** · **! {semtabela} sem tabela cadastrada**')

                resumo_rows = []
                for r in resultados_v:
                    status_label = {'COMPATIVEL':'✓ Compatível','DIFERENCA_PARA_ANALISE':'⚠ Para análise','ANALISE_13O_CONJUNTA':'📌 13º — análise conjunta','SEM_COMPARACAO':'— Sem comparação','TABELA_NAO_CADASTRADA':'! Sem tabela'}.get(r['status'], r['status'])
                    resumo_rows.append({'Competência':competencia_br(r.get('competencia',''), r.get('tipo_competencia','mensal')),'Tipo': '13º' if r.get('tipo_competencia') == '13º' else 'Mensal','Metodologia':str(r.get('metodologia','')).upper() or '—','Tabela':r.get('tabela_id','—'),'Remuneração':r.get('remuneracao',0),'Previdência DIRF':r.get('previdencia_dirf',0) if r.get('previdencia_dirf') is not None else None,'Calculada':r.get('contribuicao_calculada',0),'Diferença':r.get('diferenca_dirf_menos_calculado',0) if r.get('diferenca_dirf_menos_calculado') is not None else None,'Status':status_label})
                resumo_df = pd.DataFrame(resumo_rows)
                st.dataframe(resumo_df, use_container_width=True, hide_index=True, column_config={'Remuneração':st.column_config.NumberColumn('Remuneração',format='R$ %.2f'),'Previdência DIRF':st.column_config.NumberColumn('Previdência DIRF',format='R$ %.2f'),'Calculada':st.column_config.NumberColumn('Calculada',format='R$ %.2f'),'Diferença':st.column_config.NumberColumn('Diferença',format='R$ %.2f')})

                copy_rows_v = []
                for rr in resumo_rows:
                    copy_rows_v.append([
                        str(rr['Competência'] or ''), str(rr['Tipo'] or ''), str(rr['Metodologia'] or ''), str(rr['Tabela'] or ''),
                        f"{float(rr['Remuneração'] or 0):.2f}".replace('.', ','),
                        '' if rr['Previdência DIRF'] is None else f"{float(rr['Previdência DIRF']):.2f}".replace('.', ','),
                        f"{float(rr['Calculada'] or 0):.2f}".replace('.', ','),
                        '' if rr['Diferença'] is None else f"{float(rr['Diferença']):.2f}".replace('.', ','),
                        str(rr['Status'] or '')
                    ])
                copy_payload_v = json.dumps(copy_rows_v, ensure_ascii=False)
                html_v = f"""<button id="copy_v" style="padding:11px 18px;border:0;border-radius:8px;background:#111827;color:white;font-weight:700;cursor:pointer">📋 COPIAR PARA EXCEL</button><span id="msg_v" style="margin-left:10px;font-size:13px;color:#475467"></span><script>const rows={copy_payload_v};const head=['Competência','Tipo','Metodologia','Tabela','Remuneração','Previdência DIRF','Calculada','Diferença','Status'];function tsv(){{return [head,...rows].map(r=>r.join('\\t')).join('\\n');}}document.getElementById('copy_v').onclick=async()=>{{const text=tsv();const msg=document.getElementById('msg_v');try{{await navigator.clipboard.writeText(text);msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).';}}catch(e){{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{{document.execCommand('copy');msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).';}}catch(err){{msg.textContent='Não foi possível acessar a área de transferência.';}}ta.remove();}}}};</script>"""
                st.components.v1.html(html_v, height=55)

                st.markdown('### Detalhamento por competência')
                st.caption('Este detalhamento é mantido competência a competência. O 13º aparece logo após dezembro de cada ano e permanece em apuração separada. As linhas começam recolhidas para facilitar a navegação.')
                for r in resultados_v:
                    comp = competencia_br(r.get('competencia',''), r.get('tipo_competencia','mensal'))
                    status = r.get('status','')
                    label = {'COMPATIVEL':'✓','DIFERENCA_PARA_ANALISE':'⚠','ANALISE_13O_CONJUNTA':'📌','SEM_COMPARACAO':'—','TABELA_NAO_CADASTRADA':'!'}.get(status,'•')
                    with st.expander(f'{label} {comp} — Remuneração {fmt(r.get("remuneracao",0))} — Calculada {fmt(r.get("contribuicao_calculada",0))}'):
                        if status == 'TABELA_NAO_CADASTRADA':
                            st.error('Não há tabela histórica cadastrada para essa competência.')
                            continue
                        st.write(f"**Metodologia:** {r['metodologia'].upper()} · **Tabela:** {r['tabela_id']} · **Teto:** {fmt(r['teto'])}")
                        st.caption(f"Fonte registrada: {r['fonte']}")
                        st.caption(f"Critério de tolerância: {fmt(r.get('tolerancia_utilizada', tolerancia_v))} — {r.get('tolerancia_origem', origem_tolerancia)}. Diferença interna usada no status: {fmt4(r.get('diferenca_bruta')) if r.get('diferenca_bruta') is not None else '—'}")
                        if r.get('observacao'):
                            st.info(r['observacao'])
                        if r.get('previdencia_dirf') is not None:
                            if status == 'COMPATIVEL':
                                st.success(f"COMPATÍVEL — calculado {fmt(r['contribuicao_calculada'])}; DIRF {fmt(r['previdencia_dirf'])}; diferença {fmt(r['diferenca_dirf_menos_calculado'])}.")
                            elif status == 'ANALISE_13O_CONJUNTA':
                                st.warning(f"13º — referência individual: calculado {fmt(r['contribuicao_calculada'])}; DIRF {fmt(r['previdencia_dirf'])}. A comparação definitiva deve considerar o conjunto dos 13º dos vínculos do ano.")
                            else:
                                st.warning(f"DIFERENÇA PARA ANÁLISE — calculado {fmt(r['contribuicao_calculada'])}; DIRF {fmt(r['previdencia_dirf'])}; diferença {fmt(r['diferenca_dirf_menos_calculado'])}.")
                        else:
                            st.info(f"SEM COMPARAÇÃO — contribuição calculada: {fmt(r['contribuicao_calculada'])}.")
                        faixas_df = pd.DataFrame(r['faixas'])
                        if not faixas_df.empty:
                            faixas_df['faixa'] = faixas_df['faixa'].map(lambda x: f'Faixa {x}')
                            faixas_df['limites'] = faixas_df.apply(lambda rr: f"{fmt(rr['limite_inferior'])} a {fmt(rr['limite_superior'])}", axis=1)
                            faixas_df['alíquota'] = faixas_df['aliquota'].map(lambda x: f'{x*100:.2f}%'.replace('.', ','))
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
    st.subheader('Apuração por competência')
    st.caption('Defina o período e, explicitamente, quais declarantes participarão da consolidação. Somente os dados selecionados abaixo entram nesta apuração; o RAW e a extração permanecem intactos.')

    # ---------- Escopo da apuração ----------
    ap_base = calc_df[calc_df['tipo_competencia'].isin(['mensal', '13º'])].copy()
    if ap_base.empty:
        st.warning('Não há competências mensais ou 13º disponíveis para os declarantes selecionados.')
    else:
        # Competências reais disponíveis, ordenadas cronologicamente, com 13º após dezembro.
        def _ord_ap_item(item):
            comp, tipo = item
            try:
                ano = int(str(comp)[:4])
            except Exception:
                ano = 9999
            if tipo == '13º':
                return (ano, 13)
            try:
                mes = int(str(comp)[5:7])
            except Exception:
                mes = 99
            return (ano, mes)

        comp_items = sorted(
            {(str(r.competencia), str(r.tipo_competencia)) for r in ap_base.itertuples()},
            key=_ord_ap_item
        )
        comp_labels = [competencia_br(c, t) for c, t in comp_items]
        comp_to_item = {competencia_br(c, t): (c, t) for c, t in comp_items}

        # Declarantes explícitos: nome principal + CNPJ secundário.
        decl_map = {}
        for cnpj, g in ap_base.groupby('cnpj_declarante'):
            nomes = sorted(g['nome_declarante_dirf'].dropna().astype(str).unique(), key=str.casefold)
            nome = nomes[0] if nomes else 'Declarante sem nome identificado'
            decl_map[f'{nome} — CNPJ {cnpj}'] = str(cnpj)
        decl_options = sorted(decl_map, key=str.casefold)

        st.markdown('### 1. Período da apuração')
        p1, p2, p3 = st.columns([1.1, 1.1, 1.2])
        periodo_tipo = p1.radio(
            'Escopo',
            ['Todo o histórico', 'Intervalo personalizado', 'Um ano'],
            horizontal=True,
            key='apuracao_periodo_tipo',
        )

        if periodo_tipo == 'Todo o histórico':
            inicio_label, fim_label = comp_labels[0], comp_labels[-1]
        elif periodo_tipo == 'Um ano':
            anos_ap = sorted({int(str(c)[:4]) for c, _ in comp_items}, reverse=True)
            ano_ap = p2.selectbox('Ano', anos_ap, key='apuracao_ano')
            ano_labels = [lab for lab in comp_labels if lab.endswith(f'/{ano_ap}')]
            inicio_label, fim_label = ano_labels[0], ano_labels[-1]
        else:
            inicio_label = p2.selectbox('Competência inicial', comp_labels, index=0, key='apuracao_inicio')
            fim_default = len(comp_labels) - 1
            fim_label = p3.selectbox('Competência final', comp_labels, index=fim_default, key='apuracao_fim')
            if comp_to_item[inicio_label] and _ord_ap_item(comp_to_item[inicio_label]) > _ord_ap_item(comp_to_item[fim_label]):
                st.error('A competência inicial não pode ser posterior à competência final.')
                inicio_label = fim_label

        inicio_item = comp_to_item[inicio_label]
        fim_item = comp_to_item[fim_label]
        inicio_ord = _ord_ap_item(inicio_item)
        fim_ord = _ord_ap_item(fim_item)

        st.info(f'**Período selecionado:** {inicio_label} até {fim_label}')

        st.markdown('### 2. Declarantes utilizados na apuração')
        st.caption('Marque somente os declarantes que devem participar da consolidação. A seleção abaixo não altera a extração RAW.')
        selecionados_labels = st.multiselect(
            'Declarantes considerados',
            decl_options,
            default=decl_options,
            key='apuracao_declarantes',
            help='Cada declarantes selecionado participa da consolidação por competência. O CNPJ é mostrado para conferência.'
        )
        selecionados_cnpjs = {decl_map[x] for x in selecionados_labels}
        st.markdown(f'**{len(selecionados_cnpjs)} declarante(s) selecionado(s)**')
        if selecionados_labels:
            for label in selecionados_labels:
                st.markdown(f'- {label}')
        else:
            st.warning('Nenhum declarante foi selecionado. A apuração não será calculada.')

        # Filtra por intervalo cronológico e pelos declarantes explicitamente escolhidos.
        ap_scope = ap_base[ap_base['cnpj_declarante'].astype(str).isin(selecionados_cnpjs)].copy()
        ap_scope['_ord_ap'] = ap_scope.apply(lambda r: _ord_ap_item((str(r['competencia']), str(r['tipo_competencia']))), axis=1)
        ap_scope = ap_scope[(ap_scope['_ord_ap'] >= inicio_ord) & (ap_scope['_ord_ap'] <= fim_ord)].drop(columns='_ord_ap')

        st.markdown('### 3. Resultado consolidado')
        if ap_scope.empty:
            st.warning('Nenhum dado encontrado para o período e os declarantes selecionados.')
        else:
            result = apurar(ap_scope, dict(TETOS))
            if result.empty:
                st.warning('Sem competências mensais ou 13º para apurar no escopo selecionado.')
            else:
                resumo_ap = []
                for _, rr in result.iterrows():
                    tipo = str(rr.get('tipo_competencia', 'mensal'))
                    comp = competencia_br(rr.get('competencia', ''), tipo)
                    status = str(rr.get('status', ''))
                    if status == 'OK':
                        status_label = '🟢 Concluída' if tipo == 'mensal' else '🟡 13º — apuração separada'
                    elif status == 'CLASSIFICACAO_PENDENTE':
                        status_label = '🟡 Classificação pendente'
                    elif status == 'TETO_NAO_CADASTRADO':
                        status_label = '🟡 Teto não cadastrado'
                    else:
                        status_label = '🟡 Requer análise'
                    resumo_ap.append({
                        'Competência': comp,
                        'Tipo': '13º' if tipo == '13º' else 'Mensal',
                        'Recolhido': rr.get('soma_contribuicoes_recolhidas', 0),
                        'Teto': rr.get('teto_previdenciario', 0),
                        'Máx. progressiva': rr.get('contribuicao_maxima_progressiva', 0),
                        'Máx. 11%': rr.get('contribuicao_maxima_11', 0),
                        'Máx. 20%': rr.get('contribuicao_maxima_20', 0),
                        'Máx. total': rr.get('contribuicao_maxima_total', 0),
                        'Acima do teto': max(float(rr.get('contribuicao_acima_teto', 0) or 0), 0.0),
                        'Status': status_label,
                    })
                resumo_ap_df = pd.DataFrame(resumo_ap)
                st.dataframe(resumo_ap_df, use_container_width=True, hide_index=True, column_config={
                    c: st.column_config.NumberColumn(c, format='R$ %.2f')
                    for c in ['Recolhido','Teto','Máx. progressiva','Máx. 11%','Máx. 20%','Máx. total','Acima do teto']
                })

                total_recolhido = float(result['soma_contribuicoes_recolhidas'].fillna(0).sum()) if 'soma_contribuicoes_recolhidas' in result else 0.0
                total_maximo = float(result['contribuicao_maxima_total'].fillna(0).sum()) if 'contribuicao_maxima_total' in result else 0.0
                total_excesso = float(result['contribuicao_acima_teto'].fillna(0).sum()) if 'contribuicao_acima_teto' in result else 0.0
                a1, a2, a3 = st.columns(3)
                a1.metric('Total recolhido', fmt(total_recolhido))
                a2.metric('Total máximo calculado', fmt(total_maximo))
                a3.metric('Total acima do teto', fmt(total_excesso))

                st.markdown('### Detalhamento da apuração')
                st.caption('A consolidação considera todos os declarantes explicitamente selecionados acima. A ordem de ocupação do teto adotada nesta versão é: Progressiva → 11% → 20%. O 13º permanece separado de dezembro.')
                for _, rr in result.iterrows():
                    tipo = str(rr.get('tipo_competencia', 'mensal'))
                    comp = competencia_br(rr.get('competencia', ''), tipo)
                    status = str(rr.get('status', ''))
                    icon = '🟢' if status == 'OK' and tipo == 'mensal' else ('🟡' if status == 'OK' and tipo == '13º' else '🟡')
                    excesso = float(rr.get('contribuicao_acima_teto', 0) or 0)
                    with st.expander(f'{icon} {comp} — Recolhido {fmt(rr.get("soma_contribuicoes_recolhidas",0))} — Acima do teto {fmt(max(excesso,0))}'):
                        if status != 'OK':
                            if status == 'CLASSIFICACAO_PENDENTE':
                                st.warning(f'Classificação pendente para: {rr.get("cnpjs_pendentes", "—")}')
                            elif status == 'TETO_NAO_CADASTRADO':
                                st.warning('Não há teto cadastrado para esta competência.')
                            else:
                                st.warning('Esta competência requer análise antes de ser utilizada como resultado final.')
                            continue

                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric('Teto', fmt(rr.get('teto_previdenciario', 0)))
                        c2.metric('Recolhido', fmt(rr.get('soma_contribuicoes_recolhidas', 0)))
                        c3.metric('Máximo permitido', fmt(rr.get('contribuicao_maxima_total', 0)))
                        c4.metric('Acima do teto', fmt(max(excesso, 0)))

                        st.markdown('**Declarantes utilizados nesta competência**')
                        fontes_rr = pd.DataFrame(rr.get('fontes', []))
                        if not fontes_rr.empty:
                            fontes_rr = fontes_rr.rename(columns={
                                'cnpj_declarante':'CNPJ','nome_declarante':'Fonte','grupo_previdenciario':'Grupo',
                                'remuneracao':'Remuneração','contribuicao_recolhida':'Previdência DIRF'
                            })
                            cols = [c for c in ['Fonte','CNPJ','Grupo','Remuneração','Previdência DIRF'] if c in fontes_rr.columns]
                            st.dataframe(fontes_rr[cols], use_container_width=True, hide_index=True, column_config={
                                'Remuneração': st.column_config.NumberColumn('Remuneração', format='R$ %.2f'),
                                'Previdência DIRF': st.column_config.NumberColumn('Previdência DIRF', format='R$ %.2f'),
                            })

                        st.markdown('**Composição do máximo permitido**')
                        comp_rows = [
                            ['Progressiva', rr.get('remuneracao_progressiva',0), rr.get('base_maxima_progressiva',0), rr.get('contribuicao_maxima_progressiva',0)],
                            ['11%', rr.get('remuneracao_11',0), rr.get('base_maxima_11',0), rr.get('contribuicao_maxima_11',0)],
                            ['20%', rr.get('remuneracao_20',0), rr.get('base_maxima_20',0), rr.get('contribuicao_maxima_20',0)],
                        ]
                        comp_df = pd.DataFrame(comp_rows, columns=['Grupo','Remuneração','Base considerada','Contribuição máxima'])
                        st.dataframe(comp_df, use_container_width=True, hide_index=True, column_config={
                            'Remuneração': st.column_config.NumberColumn('Remuneração', format='R$ %.2f'),
                            'Base considerada': st.column_config.NumberColumn('Base considerada', format='R$ %.2f'),
                            'Contribuição máxima': st.column_config.NumberColumn('Contribuição máxima', format='R$ %.2f'),
                        })

                        if rr.get('tabela_id'):
                            st.caption(f"Tabela: {rr.get('tabela_id')} · Metodologia: {str(rr.get('metodologia_tabela','')).upper()} · Fonte: {rr.get('fonte_tabela','—')}")
                        if rr.get('faixas_progressiva'):
                            fp = pd.DataFrame(rr['faixas_progressiva'])
                            fp['Faixa'] = fp['faixa'].map(lambda x: f'Faixa {x}')
                            fp['Limite'] = fp.apply(lambda x: f"{fmt(x['limite_inferior'])} a {fmt(x['limite_superior'])}", axis=1)
                            fp['Alíquota'] = fp['aliquota'].map(lambda x: f'{x*100:.2f}%'.replace('.', ','))
                            fp['Base'] = fp['base_na_faixa'].map(fmt)
                            fp['Contribuição'] = fp['contribuicao'].map(fmt)
                            st.markdown('**Faixas da parcela progressiva**')
                            st.dataframe(fp[['Faixa','Limite','Alíquota','Base','Contribuição']], use_container_width=True, hide_index=True)

                st.download_button('Baixar apuração CSV', csv_bytes(result), 'apuracao_previdenciaria_v1_2_9.csv', 'text/csv')

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
        'classificacao_metadados': st.session_state.get('classification_meta', {}),
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
