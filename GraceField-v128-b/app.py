import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table, TableStyle, PageBreak, NextPageTemplate

from dirf_core import extract_pdf, validate_records
from motor_previdenciario import classify_declarante, observed_rate, apurar, verificar_tabela, verificar_13o, verificar_por_grupo, calcular_faixas, tabela_por_competencia
from classificador_previdenciario import classificar_fontes
from deduplicacao_documental import marcar_duplicatas_documentais
from tabelas_previdenciarias import TETOS, TABELAS_HISTORICAS

st.set_page_config(page_title='Extrator DIRF + Motor Previdenciário V1.2.28', page_icon='⚖️', layout='wide', initial_sidebar_state='expanded')

st.markdown("""<style>
:root{--jf-blue:#17365d;--jf-line:#d8dee8;--jf-bg:#f5f7fa;--jf-text:#1f2937}
.stApp{background:var(--jf-bg);color:var(--jf-text)}
[data-testid="stHeader"]{background:rgba(245,247,250,.94)}
.block-container{padding-top:1.2rem;padding-bottom:2rem;max-width:1500px}
section[data-testid="stSidebar"]{background:#eef2f7;border-right:1px solid var(--jf-line)}
section[data-testid="stSidebar"] h1,section[data-testid="stSidebar"] h2,section[data-testid="stSidebar"] h3{color:var(--jf-blue)}
.jf-brand{border:1px solid var(--jf-line);background:#fff;border-radius:10px;padding:14px 18px;margin-bottom:14px;box-shadow:0 1px 3px rgba(16,24,40,.06)}
.jf-brand-title{font-size:22px;font-weight:800;color:var(--jf-blue);letter-spacing:.2px}.jf-brand-sub{font-size:12px;color:#667085;margin-top:3px}
div[data-testid="stMetric"]{background:#fff;border:1px solid var(--jf-line);border-radius:9px;padding:10px 12px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.stButton>button,.stDownloadButton>button{border-radius:7px;font-weight:700;border:1px solid #c8d0dc}.stTabs [data-baseweb="tab"]{font-weight:700}.stTabs [aria-selected="true"]{color:var(--jf-blue)}
div[data-testid="stExpander"]{border:1px solid var(--jf-line);border-radius:8px;background:#fff}
</style>""", unsafe_allow_html=True)


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



def _pdf_text(v):
    s = '' if v is None else str(v)
    return s.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def _pdf_money(v, symbol=False):
    try: n=float(v or 0)
    except Exception: n=0.0
    txt=f'{n:,.2f}'.replace(',','X').replace('.',',').replace('X','.')
    return f'R$ {txt}' if symbol else txt

def _pdf_footer(canvas, doc):
    canvas.saveState(); w,h=doc.pagesize
    canvas.setStrokeColor(colors.HexColor('#D8DEE8')); canvas.line(doc.leftMargin,12*mm,w-doc.rightMargin,12*mm)
    canvas.setFont('Helvetica',8); canvas.setFillColor(colors.HexColor('#667085'))
    canvas.drawString(doc.leftMargin,7.5*mm,st.session_state.get('caso_processo','') or 'Processo não informado')
    canvas.drawRightString(w-doc.rightMargin,7.5*mm,f'Página {doc.page}'); canvas.restoreState()

def _pdf_table(data,widths=None,font=7.4,align_right_cols=None,header=True):
    t=Table(data,colWidths=widths,repeatRows=1 if header else 0,hAlign='LEFT')
    style=[('FONTNAME',(0,0),(-1,-1),'Helvetica'),('FONTSIZE',(0,0),(-1,-1),font),('TEXTCOLOR',(0,0),(-1,-1),colors.HexColor('#1F2937')),('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#CBD5E1')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]
    if header: style += [('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E9EEF5')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('TEXTCOLOR',(0,0),(-1,0),colors.HexColor('#17365D'))]
    for c in align_right_cols or []: style.append(('ALIGN',(c,1 if header else 0),(c,-1),'RIGHT'))
    t.setStyle(TableStyle(style)); return t

def _cnpj_from_horizontal_col(col):
    """Extrai o CNPJ de uma coluna da demonstração horizontal."""
    m = re.search(r'\|\s*([0-9./-]{14,18})\s+—\s+(?:Remuneração|Previdência)\s*$', str(col))
    return m.group(1) if m else ''


def gerar_relatorio_pdf(result_df=None, horiz_df=None, declarantes=None, periodo='—', decimos=None, dedup_stats=None):
    """Gera o relatório técnico integralmente em A4 paisagem.

    A demonstração horizontal usa cabeçalho em dois níveis: CNPJ agrupado
    acima de Remuneração/Previdência. Os nomes dos declarantes ficam em uma
    relação própria imediatamente antes da tabela. Quando houver muitos
    vínculos, a demonstração é dividida em blocos de até 6 CNPJs por página,
    mantendo a leitura horizontal e repetindo a identificação dos vínculos.
    """
    buf = BytesIO()
    land = landscape(A4)
    doc = BaseDocTemplate(
        buf,
        pagesize=land,
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=12 * mm,
        bottomMargin=15 * mm,
        title='Relatório de Apuração — Contribuições Previdenciárias',
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        land[0] - doc.leftMargin - doc.rightMargin,
        land[1] - doc.topMargin - doc.bottomMargin,
        id='landscape',
    )
    doc.addPageTemplates([
        PageTemplate(id='L', frames=frame, onPage=_pdf_footer, pagesize=land)
    ])

    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        'JFT', parent=styles['Title'], fontName='Helvetica-Bold', fontSize=20,
        leading=23, textColor=colors.HexColor('#17365D'), alignment=TA_CENTER,
        spaceAfter=5,
    )
    sub = ParagraphStyle(
        'JFSUB', parent=styles['BodyText'], fontName='Helvetica-Bold',
        fontSize=12, leading=14, textColor=colors.HexColor('#475467'),
        alignment=TA_CENTER, spaceAfter=5,
    )
    h1 = ParagraphStyle(
        'JFH1', parent=styles['Heading2'], fontName='Helvetica-Bold',
        fontSize=15, leading=17, textColor=colors.HexColor('#17365D'),
        spaceBefore=6, spaceAfter=5,
    )
    small = ParagraphStyle(
        'JFS', parent=styles['BodyText'], fontSize=10.5, leading=12.5,
        textColor=colors.HexColor('#475467'),
    )
    th = ParagraphStyle(
        'JFTH', parent=styles['BodyText'], fontName='Helvetica-Bold',
        fontSize=10.0, leading=11.5, textColor=colors.HexColor('#17365D'),
        alignment=TA_CENTER,
    )
    th_white = ParagraphStyle(
        'JFTHW', parent=th, textColor=colors.white, fontSize=10.0, leading=11.5,
    )
    th_comp = ParagraphStyle(
        'JFTHCOMP', parent=th_white, fontSize=10.0, leading=11.5,
    )

    story = [
        Paragraph('RELATÓRIO TÉCNICO DE APURAÇÃO', title),
        Paragraph('CONTRIBUIÇÕES PREVIDENCIÁRIAS ACIMA DO TETO', sub),
        Spacer(1, 2),
    ]

    processo = st.session_state.get('caso_processo', '') or '—'
    autor = st.session_state.get('caso_autor', '') or '—'
    reu = st.session_state.get('caso_reu', '') or '—'
    docid = st.session_state.get('caso_documento_id', '') or '—'

    ident = [
        ['IDENTIFICAÇÃO DOS AUTOS', ''],
        ['Nº do processo', _pdf_text(processo)],
        ['Autor', _pdf_text(autor)],
        ['Réu', _pdf_text(reu)],
        ['ID do documento analisado', _pdf_text(docid)],
    ]
    ti = _pdf_table(ident, [52 * mm, 215 * mm], 12.0, header=False)
    ti.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (1, 0), colors.HexColor('#E9EEF5')),
        ('FONTNAME', (0, 0), (1, 0), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (1, 0), colors.HexColor('#17365D')),
    ]))
    story += [ti, Spacer(1, 5)]

    story += [Paragraph('1. Declarantes utilizados na apuração', h1)]
    rows = [['Nº', 'Declarante', 'CNPJ', 'Enquadramento', 'Página(s)']]
    for i, d in enumerate(declarantes or [], 1):
        rows.append([
            str(i), _pdf_text(d.get('nome', '')), _pdf_text(d.get('cnpj', '')),
            _pdf_text(d.get('grupo', '')), _pdf_text(d.get('paginas', '')),
        ])
    if len(rows) == 1:
        rows.append(['—', 'Nenhum declarante selecionado', '—', '—', '—'])
    story.append(_pdf_table(rows, [10 * mm, 92 * mm, 48 * mm, 38 * mm, 79 * mm], 8.0))
    if dedup_stats and dedup_stats.get('blocos_duplicados'):
        story += [
            Spacer(1, 3),
            Paragraph(
                f"Auditoria documental: {dedup_stats.get('blocos_duplicados', 0)} bloco(s) repetido(s) identificado(s); "
                'as ocorrências duplicadas permanecem no RAW e não são contabilizadas novamente.', small
            ),
        ]

    story += [Paragraph('2. Período e critérios utilizados', h1)]
    story.append(_pdf_table([
        ['Item', 'Informação'],
        ['Período utilizado no cálculo', _pdf_text(periodo)],
        ['13º incluídos', _pdf_text(', '.join(f'13º/{a}' for a in (decimos or [])) if decimos else 'Nenhum')],
        ['Base documental', 'DIRF selecionadas pelo usuário'],
    ], [55 * mm, 212 * mm], 8.5))

    story += [PageBreak(), Paragraph('3. Resultado consolidado', h1)]
    if result_df is not None and not result_df.empty:
        # No relatório, o status não é necessário no resultado consolidado:
        # a análise de status permanece disponível na aplicação e no detalhamento.
        cols = [
            'Competência', 'Tipo', 'Recolhido', 'Teto', 'Máx. progressiva',
            'Máx. 11%', 'Máx. 20%', 'Máx. total', 'Acima do teto'
        ]
        body = ParagraphStyle(
            'JFBODYRESULT', parent=styles['BodyText'], fontName='Helvetica',
            fontSize=10.5, leading=12.0, textColor=colors.HexColor('#1F2937'),
            alignment=TA_LEFT,
        )
        body_right = ParagraphStyle(
            'JFBODYRESULTR', parent=body, alignment=TA_RIGHT,
        )
        body_bold = ParagraphStyle(
            'JFBODYRESULTB', parent=body_right, fontName='Helvetica-Bold',
        )
        data = [[Paragraph(_pdf_text(c), th) for c in cols]]
        for _, r in result_df.iterrows():
            row = [
                Paragraph(_pdf_text(r.get('Competência', '')), body),
                Paragraph(_pdf_text(r.get('Tipo', '')), body),
            ]
            for idx, c in enumerate(cols[2:], start=2):
                style = body_bold if idx == len(cols) - 1 else body_right
                row.append(Paragraph(_pdf_text(_format_money_value(r.get(c, 0))), style))
            data.append(row)
        # 9 colunas permitem uma tipografia maior sem comprimir o relatório.
        widths = [28 * mm, 20 * mm, 30 * mm, 29 * mm, 33 * mm, 31 * mm, 31 * mm, 32 * mm, 33 * mm]
        story.append(_pdf_table(data, widths, 11.0, align_right_cols=list(range(2, 9))))
        tr = float(result_df['Recolhido'].sum()) if 'Recolhido' in result_df else 0
        tm = float(result_df['Máx. total'].sum()) if 'Máx. total' in result_df else 0
        te = float(result_df['Acima do teto'].sum()) if 'Acima do teto' in result_df else 0
        story += [
            Spacer(1, 4),
            _pdf_table([
                ['Total das contribuições recolhidas', 'Total máximo considerado', 'Total acima do teto'],
                [
                    _pdf_money(tr, True),
                    _pdf_money(tm, True),
                    Paragraph(_pdf_text(_format_money_value(te)), ParagraphStyle(
                        'JFTOTALEXCESS', parent=styles['BodyText'], fontName='Helvetica-Bold',
                        fontSize=10.5, leading=12, textColor=colors.HexColor('#1F2937'),
                    )),
                ],
            ], [89 * mm, 89 * mm, 89 * mm], 10.5),
        ]
    else:
        story.append(_pdf_table(
            [['Resultado'], ['Não há apuração disponível para o escopo selecionado.']],
            [267 * mm], 8
        ))

    # Demonstração horizontal: CNPJ no cabeçalho e Remuneração/Previdência na linha inferior.
    if horiz_df is not None and not horiz_df.empty:
        story += [PageBreak(), Paragraph('4. Demonstração horizontal', h1)]
        story.append(Paragraph(
            'Os declarantes são identificados pelo CNPJ na tabela. O nome completo, enquadramento e páginas de origem permanecem na relação acima. '
            'Cada CNPJ ocupa um par fixo de colunas: Remuneração e Previdência.', small
        ))

        # Descobre os pares de colunas e preserva a ordem em que aparecem na demonstração.
        pares = []
        seen = set()
        for col in list(horiz_df.columns)[1:]:
            cnpj = _cnpj_from_horizontal_col(col)
            if cnpj and cnpj not in seen:
                seen.add(cnpj)
                rem_col = next((c for c in horiz_df.columns if c.endswith(f'{cnpj} — Remuneração')), None)
                prev_col = next((c for c in horiz_df.columns if c.endswith(f'{cnpj} — Previdência')), None)
                if rem_col and prev_col:
                    pares.append((cnpj, rem_col, prev_col))

        # Fallback para estruturas antigas que não carreguem CNPJ no cabeçalho.
        if not pares:
            labels = list(horiz_df.columns)[1:]
            for i in range(0, len(labels), 2):
                if i + 1 < len(labels):
                    pares.append((labels[i].replace(' — Remuneração', ''), labels[i], labels[i + 1]))

        # Até 6 CNPJs por página: 13 colunas incluindo competência.
        chunk_size = 6
        for chunk_idx in range(0, len(pares), chunk_size):
            chunk = pares[chunk_idx:chunk_idx + chunk_size]
            if chunk_idx:
                story.append(PageBreak())
                story.append(Paragraph('4. Demonstração horizontal — continuação', h1))

            # Relação compacta dos vínculos presentes neste bloco.
            rel = [['Nº', 'Declarante', 'CNPJ', 'Enquadramento', 'Página(s)']]
            decl_by_cnpj = {str(d.get('cnpj', '')): d for d in (declarantes or [])}
            for j, (cnpj, _, _) in enumerate(chunk, chunk_idx + 1):
                d = decl_by_cnpj.get(str(cnpj), {})
                rel.append([
                    str(j), _pdf_text(d.get('nome', '') or 'Declarante não identificado'),
                    _pdf_text(cnpj), _pdf_text(d.get('grupo', '') or '—'),
                    _pdf_text(d.get('paginas', '') or '—'),
                ])
            story += [Paragraph('Declarantes deste bloco', small), _pdf_table(rel, [10 * mm, 92 * mm, 48 * mm, 38 * mm, 79 * mm], 7.8), Spacer(1, 4)]

            # Cabeçalho agrupado em dois níveis.
            head1 = [Paragraph('COMPETÊNCIA', ParagraphStyle('JFTHCOMP2', parent=th_white, fontSize=11.0, leading=12, alignment=TA_CENTER))]
            head2 = [Paragraph('', th)]
            for cnpj, _, _ in chunk:
                head1.append(Paragraph(_pdf_text(cnpj), th_white))
                head1.append('')
                head2.extend([Paragraph('Remuneração', th), Paragraph('Previdência', th)])
            data = [head1, head2]

            for _, r in horiz_df.iterrows():
                row = [str(r.iloc[0])]
                for _, rem_col, prev_col in chunk:
                    row.extend([_pdf_money(r.get(rem_col, 0)), _pdf_money(r.get(prev_col, 0))])
                data.append(row)

            ncols = 1 + 2 * len(chunk)
            first = 29 * mm
            remaining = 267 * mm - first
            each = remaining / (ncols - 1)
            widths = [first] + [each] * (ncols - 1)
            font = max(8.5, min(10.0, 255 / ncols + 1.8))
            table = Table(data, colWidths=widths, repeatRows=2, hAlign='LEFT')
            ts = [
                ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), font),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#1F2937')),
                ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#CBD5E1')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 2), (-1, -1), 'RIGHT'),
                ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 3),
                ('RIGHTPADDING', (0, 0), (-1, -1), 3),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('SPAN', (0, 0), (0, 1)),
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#17365D')),
                ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#E9EEF5')),
                ('FONTNAME', (0, 0), (-1, 1), 'Helvetica-Bold'),
                ('TEXTCOLOR', (0, 1), (-1, 1), colors.HexColor('#17365D')),
            ]
            for i in range(len(chunk)):
                c0 = 1 + 2 * i
                ts.append(('SPAN', (c0, 0), (c0 + 1, 0)))
            table.setStyle(TableStyle(ts))
            story.append(table)

    doc.build(story)
    return buf.getvalue()

def _format_money_value(value):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            value = 0.0
        v = float(value)
    except Exception:
        return str(value or '0,00')
    return f"{v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')


def csv_bytes(df):
    return df.to_csv(index=False, sep=';', decimal=',', encoding='utf-8-sig', lineterminator='\r\n').encode('utf-8-sig')


def _first_nonempty(values):
    for v in values:
        if v is not None and str(v).strip() and str(v).strip().lower() not in {'nan', 'none'}:
            return str(v).strip()
    return ''


def extrair_dados_caso(registros):
    # Obtém dados de identificação já presentes no RAW.
    # Em PDFs judiciais é comum o número do processo estar no nome do arquivo
    # (ex.: 0031059-48.2026.4.05.8300_DIRF.pdf), e não dentro do formulário DIRF.
    if not registros:
        return {'processo': '', 'autor': '', 'reu': ''}
    # O número do processo só é preenchido automaticamente quando estiver
    # efetivamente presente nos dados extraídos da DIRF/TETOPREV. Não inferimos
    # o processo a partir do nome do arquivo, pois o arquivo pode ser apenas uma
    # cópia/documento auxiliar e isso criaria informação não comprovada.
    processo = _first_nonempty([r.get('numero_processo') for r in registros])
    autor = _first_nonempty([r.get('nome_beneficiario_cadastro') for r in registros] + [r.get('nome_beneficiario_dirf') for r in registros])
    return {'processo': processo, 'autor': autor, 'reu': ''}


def nome_arquivo_tetoprev(autor):
    # 4 primeiros nomes + HHMMSSmm. O conteúdo continua sendo JSON.
    nome = re.sub(r'[^\w\sÀ-ÿ-]', '', str(autor or ''), flags=re.UNICODE)
    partes = [x for x in re.split(r'\s+', nome.strip()) if x][:4] or ['DOCUMENTO']
    base = '_'.join(partes)
    base = ''.join(c for c in unicodedata.normalize('NFKD', base) if not unicodedata.combining(c))
    base = re.sub(r'[^A-Za-z0-9_-]+', '_', base).strip('_') or 'DOCUMENTO'
    agora = datetime.now()
    centesimos = agora.microsecond // 10000
    return f'{base}_{agora:%H%M%S}{centesimos:02d}.TETOPREV'


def carregar_tetoprev(uploaded_file):
    payload = json.loads(uploaded_file.getvalue().decode('utf-8-sig'))
    registros = payload.get('registros') or []
    if not isinstance(registros, list) or not registros:
        raise ValueError('O arquivo TETOPREV não contém registros válidos.')
    return registros, (payload.get('caso') or {}), payload


def normalize_cnpj(v):
    # Identidade canônica do declarante: o mesmo CNPJ pode aparecer com
    # pontuação diferente ou espaços em páginas distintas da DIRF.
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    raw = str(v).strip()
    digits = re.sub(r'\D', '', raw)
    # Aceita CNPJ acompanhado de texto/ruído de formatação no bloco,
    # desde que exista uma sequência inequívoca de 14 dígitos.
    if len(digits) >= 14:
        digits = digits[:14]
        return f'{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}'
    return raw

def cnpj_identity(v):
    """Chave interna estável do declarante.

    A identidade do vínculo é o CNPJ sem pontuação. Assim, blocos/páginas
    diferentes da mesma DIRF nunca criam uma nova coluna apenas por diferença
    de máscara, espaços ou formatação do CNPJ.
    """
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    digits = re.sub(r'\D', '', str(v))
    return digits if len(digits) == 14 else ''

def normalize_declarante_name(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ''
    return re.sub(r'\s+', ' ', str(v)).strip().upper()

def preencher_cnpjs_ausentes(df):
    # Quando uma página/bloco vier sem CNPJ, usa o nome do declarante apenas
    # se esse nome apontar inequivocamente para um único CNPJ já identificado.
    # Nunca mistura dois CNPJs diferentes apenas porque os nomes coincidem.
    out = df.copy()
    out['_nome_declarante_chave'] = out['nome_declarante_dirf'].map(normalize_declarante_name)
    mapa = {}
    conhecidos = out[out['cnpj_declarante'].astype(str).str.strip().ne('')].copy()
    for nome, g in conhecidos.groupby('_nome_declarante_chave'):
        cnpjs = sorted(set(g['cnpj_declarante'].astype(str)))
        if nome and len(cnpjs) == 1:
            mapa[nome] = cnpjs[0]
    mask = out['cnpj_declarante'].astype(str).str.strip().eq('')
    out.loc[mask, 'cnpj_declarante'] = out.loc[mask, '_nome_declarante_chave'].map(mapa).fillna('')
    return out.drop(columns=['_nome_declarante_chave'])


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


st.title('Extrator DIRF + Motor Previdenciário V1.2.22')
st.caption('Extração preservada + seleção inteligente de fontes + agrupamento de vínculos/declarantes + classificação separada + verificação anual/mensal + apuração por competência.')

with st.sidebar:
    st.header('Entrada')
    st.caption('Autos / documento previdenciário')
    arquivo_tetoprev = st.file_uploader(
        'Carregar arquivo TETOPREV / JSON',
        type=['tetoprev', 'json'],
        accept_multiple_files=False,
        key='arquivo_tetoprev'
    )
    files = st.file_uploader(
        'Ou selecione uma ou mais DIRFs em PDF',
        type=['pdf'],
        accept_multiple_files=True,
        key='arquivos_pdf'
    )
    st.divider()
    st.markdown('**Fluxo**')
    st.write('1. Entrada / identificação do caso')
    st.write('2. Extração RAW completa')
    st.write('3. Agrupamento dos vínculos/declarantes')
    st.write('4. Classificação 11% / 20% / Progressiva')
    st.write('5. Verificação da tabela previdenciária')
    st.write('6. Apuração do teto')
    st.write('7. Demonstração horizontal')
    st.info('O código DIRF e a alíquota efetiva observada não determinam, sozinhos, a classificação previdenciária.')

records, declarations, errors = [], [], []
carregado_tetoprev = False
metadados_carregados = {}

if arquivo_tetoprev:
    try:
        records, metadados_carregados, payload_carregado = carregar_tetoprev(arquivo_tetoprev)
        # Preferimos manter as chaves do caso separadas das configurações do motor.
        metadados_carregados['_classificacao_por_cnpj'] = payload_carregado.get('classificacao_por_cnpj') or {}
        metadados_carregados['_classificacao_metadados'] = payload_carregado.get('classificacao_metadados') or {}
        metadados_carregados['_vinculos_incluidos'] = payload_carregado.get('vinculos_incluidos') or []
        metadados_carregados['_decimos_terceiros_incluidos'] = payload_carregado.get('decimos_terceiros_incluidos') or []
        carregado_tetoprev = True
        declarations = payload_carregado.get('declaracoes') or []
        if not declarations:
            seen = set()
            for r in records:
                k = (r.get('arquivo_origem',''), r.get('pagina_pdf',''))
                if k not in seen:
                    seen.add(k)
                    declarations.append(r.copy())
        st.success(f'Arquivo TETOPREV carregado: {arquivo_tetoprev.name}. A ficha não precisa ser reenviada.')
    except Exception as exc:
        st.error(f'Não foi possível carregar o arquivo TETOPREV/JSON: {exc}')
elif files:
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

if carregado_tetoprev and not st.session_state.get('modal_tetoprev_exibido', False):
    @st.dialog('📂 Trabalho carregado')
    def _modal_trabalho():
        proc=_first_nonempty([metadados_carregados.get('processo')]) or 'Não informado'
        aut=_first_nonempty([metadados_carregados.get('autor')]) or 'Não informado'
        st.markdown('### Dados restaurados')
        st.write(f'**Processo:** {proc}')
        st.write(f'**Autor:** {aut}')
        st.caption(f'Arquivo: {arquivo_tetoprev.name}')
        if st.button('✓ Continuar análise', type='primary', use_container_width=True):
            st.session_state.modal_tetoprev_exibido=True; st.rerun()
    _modal_trabalho()

if errors:
    st.error('Falha em arquivo(s).')
    st.dataframe(pd.DataFrame(errors), hide_index=True, use_container_width=True)
if not records:
    st.info('Carregue um arquivo TETOPREV/JSON já processado ou envie uma ou mais DIRFs em PDF para iniciar.')
    st.stop()

df = pd.DataFrame(records)
df['cnpj_declarante'] = df['cnpj_declarante'].map(normalize_cnpj)
df = preencher_cnpjs_ausentes(df)
# Deduplicação documental conservadora: preserva o RAW e marca cópias integrais
# da mesma declaração para que não entrem duas vezes nas etapas previdenciárias.
df, dedup_stats = marcar_duplicatas_documentais(df)
# Chave de identidade independente de página/bloco/máscara.
df['cnpj_chave'] = df['cnpj_declarante'].map(cnpj_identity)
df['aliquota_efetiva_observada'] = observed_rate(df)
df['competencia_br'] = df.apply(lambda r: competencia_br(r['competencia'], r['tipo_competencia']), axis=1)
order = {'mensal': 1, '13º': 2, 'total': 3}
df['_ord'] = df.tipo_competencia.map(order).fillna(9)
df = df.sort_values(['ano_calendario', 'arquivo_origem', 'pagina_pdf', '_ord', 'competencia'], na_position='last').drop(columns='_ord')

# Restaura as escolhas gravadas no TETOPREV sem exigir nova alimentação manual.
if carregado_tetoprev and 'tetoprev_restaurado' not in st.session_state:
    st.session_state.assignments = dict(metadados_carregados.get('_classificacao_por_cnpj', {}))
    st.session_state.classification_meta = dict(metadados_carregados.get('_classificacao_metadados', {}))
    st.session_state.included_cnpjs = set(metadados_carregados.get('_vinculos_incluidos', []))
    st.session_state.decimos_terceiros_incluidos = set(metadados_carregados.get('_decimos_terceiros_incluidos', []))
    st.session_state.tetoprev_restaurado = True
    st.session_state.included_cnpjs_restaurados = True

if 'assignments' not in st.session_state:
    st.session_state.assignments = {}
if 'classification_meta' not in st.session_state:
    st.session_state.classification_meta = {}

df_calculo = df[~df['duplicata_documental']].copy()
fontes = [resumo_fonte(df_calculo, cnpj) for cnpj in sorted(df_calculo['cnpj_declarante'].dropna().astype(str).unique())]
sugeridas = {v['cnpj'] for v in fontes if v['sugerir']}
if 'included_cnpjs' not in st.session_state:
    st.session_state.included_cnpjs = set(sugeridas)
    st.session_state.included_cnpjs_restaurados = False
elif not st.session_state.get('included_cnpjs_restaurados', False):
    # Em uma leitura nova, fontes previdenciárias sugeridas podem entrar por padrão.
    st.session_state.included_cnpjs |= (sugeridas - set(st.session_state.included_cnpjs))

classified = classify_declarante(df_calculo, st.session_state.assignments)

if dedup_stats['blocos_duplicados']:
    st.warning(f"{dedup_stats['blocos_duplicados']} bloco(s) documental(is) repetido(s) identificado(s). {dedup_stats['registros_duplicados']} registro(s) permanecem no RAW, mas não serão contabilizados novamente.")
else:
    st.success('Nenhuma duplicação documental integral foi identificada no arquivo.')
st.success(f"{dedup_stats['blocos_identificados']} blocos identificados; {len(df)} registros estruturados; {dedup_stats['blocos_unicos']} bloco(s) canônico(s) para cálculo.")
m1, m2, m3, m4 = st.columns(4)
m1.metric('Arquivos', len(files) if files else (1 if carregado_tetoprev else 0))
m2.metric('Blocos DIRF', len(declarations))
m3.metric('Registros', len(df))
m4.metric('Declarantes/CNPJs', df['cnpj_declarante'].nunique())

# Identificação dos autos. Ao carregar um TETOPREV, a identificação gravada
# no arquivo tem prioridade; se estiver vazia, reconstruímos a partir do RAW
# (inclusive do nome do PDF, quando este contém um número CNJ).
caso_extraido = extrair_dados_caso(records)
processo_restaurado = _first_nonempty([metadados_carregados.get('processo'), caso_extraido['processo']])
autor_restaurado = _first_nonempty([metadados_carregados.get('autor'), caso_extraido['autor']])
reu_restaurado = _first_nonempty([metadados_carregados.get('reu')])
id_documento_restaurado = _first_nonempty([metadados_carregados.get('id_documento')])
if carregado_tetoprev and not st.session_state.get('identificacao_tetoprev_restaurada', False):
    st.session_state.caso_processo = processo_restaurado
    st.session_state.caso_autor = autor_restaurado
    st.session_state.caso_reu = reu_restaurado
    st.session_state.caso_documento_id = id_documento_restaurado
    st.session_state.identificacao_tetoprev_restaurada = True
else:
    if 'caso_processo' not in st.session_state:
        st.session_state.caso_processo = processo_restaurado
    if 'caso_autor' not in st.session_state:
        st.session_state.caso_autor = autor_restaurado
    if 'caso_reu' not in st.session_state:
        st.session_state.caso_reu = reu_restaurado
    if 'caso_documento_id' not in st.session_state:
        st.session_state.caso_documento_id = id_documento_restaurado

st.markdown('## Identificação dos autos')
case_box = st.container(border=True)
c1, c2 = case_box.columns([1.25, 1])
with c1:
    st.text_input('Nº do processo', key='caso_processo', placeholder='Ex.: 0000000-00.0000.0.00.0000')
    st.text_input('Nome do autor', key='caso_autor', placeholder='Nome do autor')
with c2:
    st.text_input('Nome do réu', key='caso_reu', placeholder='Nome do réu')
    st.text_input('ID do documento analisado', key='caso_documento_id', placeholder='ID do documento no PJe / SEI')

st.markdown('### Relatório documental')
st.caption('Identificação das declarações encontradas, organizada por página. O conteúdo é derivado da ficha extraída; o ID do documento é informado pelo usuário.')
with st.expander('📑 Abrir relatório por página', expanded=False):
    paginas = []
    seen_pages = set()
    for r in records:
        chave = (str(r.get('arquivo_origem','')), str(r.get('pagina_pdf','')))
        if chave in seen_pages:
            continue
        seen_pages.add(chave)
        paginas.append(r)
    paginas.sort(key=lambda x: (str(x.get('arquivo_origem','')), int(x.get('pagina_pdf') or 0)))
    for r in paginas:
        pagina = r.get('pagina_pdf', '—')
        with st.expander(f"Página {pagina} — {r.get('nome_declarante_dirf') or 'Declarante não identificado'}", expanded=False):
            info_rows = {
                'ID do documento analisado': st.session_state.caso_documento_id or '—',
                'Arquivo': r.get('arquivo_origem') or '—',
                'Página': pagina,
                'Beneficiário / Autor identificado na DIRF': r.get('nome_beneficiario_dirf') or r.get('nome_beneficiario_cadastro') or '—',
                'CPF beneficiário': r.get('cpf_beneficiario') or '—',
                'Declarante': r.get('nome_declarante_dirf') or r.get('nome_declarante_cadastro') or '—',
                'CNPJ declarante': r.get('cnpj_declarante') or '—',
                'Ano-calendário': r.get('ano_calendario') or '—',
                'Código de receita': codigo_label(r.get('codigo_receita'), r.get('descricao_codigo_receita')),
                'Tipo da declaração': r.get('tipo_declaracao') or '—',
                'Situação': r.get('situacao_declaracao') or '—',
                'Data de entrega': r.get('data_entrega') or '—',
                'Número do processo na DIRF': r.get('numero_processo') or '—',
                'Fundo/Clube': r.get('fundo_clube') or '—',
            }
            st.dataframe(pd.DataFrame(list(info_rows.items()), columns=['Informação','Valor']), hide_index=True, use_container_width=True)

if dedup_stats['blocos_duplicados']:
    st.markdown('### Auditoria das duplicidades documentais')
    st.caption('Comparação das declarações identificadas como repetidas. A ocorrência de menor página é a referência canônica; as demais permanecem no RAW, mas não são reutilizadas no cálculo.')
    dup_df = df[df['duplicata_documental']].copy()
    sigs = [x for x in dup_df['assinatura_documental'].dropna().unique() if str(x).strip()]
    with st.expander(f'🔎 Ver o que foi repetido — {len(sigs)} declaração(ões) duplicada(s)', expanded=False):
        for idx, sig in enumerate(sigs, 1):
            bloco = df[df['assinatura_documental'].eq(sig)].copy()
            if bloco.empty:
                continue
            blocos_pag = []
            for pagina, g in bloco.groupby('pagina_pdf', sort=True):
                primeira = g.iloc[0]
                blocos_pag.append((int(pagina), primeira, g))
            if len(blocos_pag) < 2:
                continue
            canon_pagina, canon_row, canon_g = blocos_pag[0]
            st.markdown(f'**Duplicidade {idx} — {canon_row.get("nome_declarante_dirf") or "Declarante não identificado"}**')
            ident = {
                'Ano-calendário': canon_row.get('ano_calendario') or '—',
                'CNPJ': canon_row.get('cnpj_declarante') or '—',
                'Declarante': canon_row.get('nome_declarante_dirf') or canon_row.get('nome_declarante_cadastro') or '—',
                'Tipo': canon_row.get('tipo_declaracao') or '—',
                'Data de entrega': canon_row.get('data_entrega') or '—',
                'Código': codigo_label(canon_row.get('codigo_receita'), canon_row.get('descricao_codigo_receita')),
            }
            st.dataframe(pd.DataFrame(list(ident.items()), columns=['Identificação','Valor']), hide_index=True, use_container_width=True)
            for pos, (pagina, row0, g0) in enumerate(blocos_pag):
                st.markdown(f'**Declaração {chr(65+pos)} — página {pagina}**')
                meses = g0[g0['tipo_competencia'].isin(['mensal','13º'])][['competencia_br','rendimento_tributavel','previdencia_oficial']].copy()
                if not meses.empty:
                    meses.columns = ['Competência','Remuneração','Previdência']
                    meses['Remuneração'] = meses['Remuneração'].map(fmt)
                    meses['Previdência'] = meses['Previdência'].map(fmt)
                    st.dataframe(meses, hide_index=True, use_container_width=True)
            st.warning(f'Duplicata documental: página(s) {[p for p, _, _ in blocos_pag[1:]]} repetem a declaração da página {canon_pagina}.')
            if idx < len(sigs):
                st.divider()


tabs = st.tabs(['📄 Extração e filtros', '🔗 Agrupamento de vínculos', '🧩 Classificação', '🔎 Verificação', '🧮 Apuração', '📊 Demonstração', '⬇️ Exportação'])

with tabs[0]:
    st.subheader('Declarações identificadas')
    cols = ['ano_calendario', 'cnpj_declarante', 'nome_declarante_dirf', 'codigo_receita', 'descricao_codigo_receita', 'pagina_pdf', 'arquivo_origem', 'status_documental', 'pagina_canonica']
    st.dataframe(df[cols].drop_duplicates().reset_index(drop=True), use_container_width=True, hide_index=True)
    if dedup_stats['blocos_duplicados']:
        st.caption('**DUPLICATA_DOCUMENTAL:** a ocorrência repetida continua disponível para auditoria, mas somente a ocorrência canônica participa das etapas de classificação, verificação, apuração e demonstração.')

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
    sugestoes = classificar_fontes(df_calculo, cnpjs, st.session_state.assignments, st.session_state.classification_meta)
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
            sub = df_calculo[df_calculo.cnpj_declarante.astype(str).eq(cnpj)]
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
                    widget_key = 'grp_' + re.sub(r'\W+', '_', cnpj)
                    val = st.selectbox(
                        'Editar classificação',
                        ['nao_definido', '11', '20', 'progressiva'],
                        index=['nao_definido', '11', '20', 'progressiva'].index(current),
                        key=widget_key,
                        format_func=lambda x: nomes_grupo.get(x, x),
                        label_visibility='collapsed',
                    )

                # A sugestão automática não deve ser tratada como confirmação
                # apenas porque o selectbox foi renderizado. A confirmação do
                # usuário é uma ação explícita. Isso também permite confirmar
                # a mesma opção sugerida (ex.: Progressiva -> Progressiva),
                # sem precisar escolher outra opção e voltar.
                anterior = st.session_state.assignments.get(cnpj)
                if anterior is not None and val != anterior:
                    st.session_state.assignments[cnpj] = val
                    st.session_state.classification_meta[cnpj] = {
                        **meta, 'classificacao_final': val, 'origem_classificacao': 'usuario',
                        'nivel_confianca': 'confirmada',
                        'data_classificacao': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'usuario_confirmador': 'usuario',
                    }
                elif anterior is None and cnpj not in st.session_state.classification_meta:
                    # Não persiste a sugestão como decisão do usuário.
                    # A sugestão permanece disponível apenas como orientação.
                    st.session_state.classification_meta[cnpj] = meta

                final_meta_pre = st.session_state.classification_meta.get(cnpj, meta)
                ja_confirmada = (
                    str(final_meta_pre.get('origem_classificacao', '')) == 'usuario'
                    and str(st.session_state.assignments.get(cnpj, '')) == str(val)
                )

                if not ja_confirmada and val != 'nao_definido':
                    label_confirmar = f'✓ Confirmar {nomes_grupo.get(val, val)}'
                    if st.button(label_confirmar, key='confirm_' + re.sub(r'\W+', '_', cnpj), use_container_width=True):
                        st.session_state.assignments[cnpj] = val
                        st.session_state.classification_meta[cnpj] = {
                            **meta, 'classificacao_final': val, 'origem_classificacao': 'usuario',
                            'nivel_confianca': 'confirmada',
                            'data_classificacao': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S'),
                            'usuario_confirmador': 'usuario',
                        }
                        st.rerun()

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
                    st.success(f'✓ Sugestão automática: {nomes_grupo[val]} — confiança {conf_label.get(meta["nivel_confianca"], meta["nivel_confianca"])}. **Confirme abaixo para registrar sua decisão.**')
                else:
                    st.warning(f'⚠️ Sugestão {nomes_grupo[val]} com confiança {conf_label.get(meta["nivel_confianca"], meta["nivel_confianca"])}. **Confirme abaixo para registrar sua decisão.**')

    st.caption('Regra de segurança: códigos DIRF e alíquota efetiva não são tratados isoladamente como fundamento jurídico. Sugestões com evidência insuficiente permanecem pendentes para confirmação humana.')

classified = classify_declarante(df_calculo, st.session_state.get('assignments', {}))
calc_df = classified[classified['cnpj_declarante'].isin(st.session_state.included_cnpjs)].copy()

with tabs[3]:
    st.subheader('Verificação da Alíquota Previdenciária')
    st.caption('Bancada independente para análise dos valores extraídos da DIRF e da tabela histórica. A navegação pode abranger um ano, um intervalo ou todo o histórico disponível; a verificação trata cada competência mensal e cada 13º separadamente. O cálculo previdenciário consolidado não é produzido nesta guia; ele é realizado na Apuração.')

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

A guia mantém a **Previdência Oficial da DIRF** como dado extraído e apresenta apenas uma coluna de **Análise**. O cálculo consolidado por tipo (Progressiva, 11% ou 20%), a aplicação do teto e o eventual excesso são realizados exclusivamente na guia **Apuração**. No **13º**, a referência individual não é conclusiva quando existem múltiplos vínculos; por isso o sistema o marca para **análise conjunta**, sem misturá-lo a dezembro.
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
            grupo_v = str(st.session_state.get('assignments', {}).get(str(cnpj_v), 'nao_definido'))
            grupo_v_label = {'11': '11%', '20': '20%', 'progressiva': 'Progressiva', 'nao_definido': 'Não definido'}.get(grupo_v, grupo_v)
            st.info(f'Classificação utilizada nesta verificação: **{grupo_v_label}**. Essa mesma classificação é a referência do vínculo para as etapas seguintes, inclusive a Demonstração e a Apuração.')
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
                # A classificação é propriedade persistente do CNPJ/vínculo.
                # Ao consolidar blocos/páginas da DIRF por competência, não podemos
                # perder o grupo_previdenciario. Se ele for descartado no groupby,
                # uma fonte já definida como 11% volta a ser tratada como
                # nao_definido e a verificação cai indevidamente na tabela progressiva.
                grupo_verificacao_cnpj = str(st.session_state.get('assignments', {}).get(str(cnpj_v), 'nao_definido'))
                sub_hist['_grupo_classificacao'] = grupo_verificacao_cnpj
                agrupado = sub_hist.groupby(['competencia', 'ano_calendario', 'tipo_competencia'], as_index=False).agg(
                    rendimento_tributavel=('rendimento_tributavel', 'sum'),
                    previdencia_oficial=('previdencia_oficial', 'sum'),
                    grupo_previdenciario=('_grupo_classificacao', 'first'),
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
                    if tipo == '13º' and grupo_fonte in ('11', '20', 'progressiva'):
                        # O 13º continua separado de dezembro, mas a classificação
                        # confirmada do vínculo deve acompanhar a fonte também aqui.
                        resultado = verificar_por_grupo(comp, rem, grupo_fonte, prev, tolerancia=tolerancia_v, tipo_competencia=tipo)
                        resultado['status'] = 'ANALISE_13O_CONJUNTA' if prev is not None else 'SEM_COMPARACAO'
                    elif tipo == '13º':
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
                m1, m2 = st.columns(2)
                m1.metric('Remuneração', fmt(total_rem))
                m2.metric('Previdência DIRF', fmt(total_prev))
                st.write(f'**✓ {compat} compatível(is)** · **⚠ {diffs} para análise** · **📌 {analise_13} 13º para análise conjunta** · **— {semcomp} sem comparação** · **! {semtabela} sem tabela cadastrada**')

                resumo_rows = []
                for r in resultados_v:
                    status_label = {'COMPATIVEL':'✓ Compatível','DIFERENCA_PARA_ANALISE':'⚠ Para análise','ANALISE_13O_CONJUNTA':'📌 13º — análise conjunta','SEM_COMPARACAO':'— Sem comparação','TABELA_NAO_CADASTRADA':'! Sem tabela'}.get(r['status'], r['status'])
                    resumo_rows.append({'Competência':competencia_br(r.get('competencia',''), r.get('tipo_competencia','mensal')),'Tipo': '13º' if r.get('tipo_competencia') == '13º' else 'Mensal','Metodologia':str(r.get('metodologia','')).upper() or '—','Tabela':r.get('tabela_id','—'),'Remuneração':r.get('remuneracao',0),'Previdência DIRF':r.get('previdencia_dirf',0) if r.get('previdencia_dirf') is not None else None,'Análise':status_label})
                resumo_df = pd.DataFrame(resumo_rows)
                st.dataframe(resumo_df, use_container_width=True, hide_index=True, column_config={'Remuneração':st.column_config.NumberColumn('Remuneração',format='R$ %.2f'),'Previdência DIRF':st.column_config.NumberColumn('Previdência DIRF',format='R$ %.2f')})

                copy_rows_v = []
                for rr in resumo_rows:
                    copy_rows_v.append([
                        str(rr['Competência'] or ''), str(rr['Tipo'] or ''), str(rr['Metodologia'] or ''), str(rr['Tabela'] or ''),
                        f"{float(rr['Remuneração'] or 0):.2f}".replace('.', ','),
                        '' if rr['Previdência DIRF'] is None else f"{float(rr['Previdência DIRF']):.2f}".replace('.', ','),
                        str(rr['Análise'] or '')
                    ])
                copy_payload_v = json.dumps(copy_rows_v, ensure_ascii=False)
                html_v = f"""<button id="copy_v" style="padding:11px 18px;border:0;border-radius:8px;background:#111827;color:white;font-weight:700;cursor:pointer">📋 COPIAR PARA EXCEL</button><span id="msg_v" style="margin-left:10px;font-size:13px;color:#475467"></span><script>const rows={copy_payload_v};const head=['Competência','Tipo','Metodologia','Tabela','Remuneração','Previdência DIRF','Análise'];function tsv(){{return [head,...rows].map(r=>r.join('\\t')).join('\\n');}}document.getElementById('copy_v').onclick=async()=>{{const text=tsv();const msg=document.getElementById('msg_v');try{{await navigator.clipboard.writeText(text);msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).';}}catch(e){{const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();try{{document.execCommand('copy');msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).';}}catch(err){{msg.textContent='Não foi possível acessar a área de transferência.';}}ta.remove();}}}};</script>"""
                st.components.v1.html(html_v, height=55)

                st.markdown('### Detalhamento por competência')
                st.caption('Este detalhamento é mantido competência a competência. O 13º aparece logo após dezembro de cada ano e permanece em apuração separada. As linhas começam recolhidas para facilitar a navegação.')
                for r in resultados_v:
                    comp = competencia_br(r.get('competencia',''), r.get('tipo_competencia','mensal'))
                    status = r.get('status','')
                    label = {'COMPATIVEL':'✓','DIFERENCA_PARA_ANALISE':'⚠','ANALISE_13O_CONJUNTA':'📌','SEM_COMPARACAO':'—','TABELA_NAO_CADASTRADA':'!'}.get(status,'•')
                    with st.expander(f'{label} {comp} — Remuneração {fmt(r.get("remuneracao",0))} — Análise: {status_label}'):
                        if status == 'TABELA_NAO_CADASTRADA':
                            st.error('Não há tabela histórica cadastrada para essa competência.')
                            continue
                        st.write(f"**Metodologia:** {r['metodologia'].upper()} · **Tabela:** {r['tabela_id']} · **Teto:** {fmt(r['teto'])}")
                        st.caption(f"Fonte registrada: {r['fonte']}")
                        st.caption(f"Critério de análise: tolerância {fmt(r.get('tolerancia_utilizada', tolerancia_v))} — {r.get('tolerancia_origem', origem_tolerancia)}. A tolerância serve somente para classificar o registro como compatível ou para análise.")
                        if r.get('observacao'):
                            st.info(r['observacao'])
                        if r.get('previdencia_dirf') is not None:
                            if status == 'COMPATIVEL':
                                st.success(f"COMPATÍVEL — Previdência DIRF {fmt(r['previdencia_dirf'])}.")
                            elif status == 'ANALISE_13O_CONJUNTA':
                                st.warning(f"13º — Previdência DIRF {fmt(r['previdencia_dirf'])}. A análise definitiva deve considerar o conjunto dos 13º dos vínculos do ano.")
                            else:
                                st.warning(f"PARA ANÁLISE — Previdência DIRF {fmt(r['previdencia_dirf'])}. O cálculo consolidado será realizado na guia Apuração.")
                        else:
                            st.info('SEM COMPARAÇÃO — não há Previdência Oficial informada na DIRF para esta competência.')
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
            # Chave cronológica escalar: evita comparações de tuplas dentro do
            # pandas, que podem falhar quando uma DIRF produz tipos/valores
            # heterogêneos. O 13º ocupa a posição 13 de cada ano.
            comp, tipo = item
            try:
                ano = int(str(comp)[:4])
            except Exception:
                ano = 9999
            if tipo == '13º':
                return ano * 100 + 13
            try:
                mes = int(str(comp)[5:7])
            except Exception:
                mes = 99
            return ano * 100 + mes

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

        # O 13º não entra automaticamente só porque o ano está dentro do período.
        # A inclusão é uma decisão explícita do usuário, por ano civil.
        ap_pre_scope = ap_base[ap_base['cnpj_declarante'].astype(str).isin(selecionados_cnpjs)].copy()
        ap_pre_scope['_ord_ap'] = ap_pre_scope.apply(lambda r: _ord_ap_item((str(r['competencia']), str(r['tipo_competencia']))), axis=1)
        ap_pre_scope = ap_pre_scope[(ap_pre_scope['_ord_ap'] >= inicio_ord) & (ap_pre_scope['_ord_ap'] <= fim_ord)].drop(columns='_ord_ap')

        # Anos civis abrangidos pelo período mensal selecionado.
        # O 13º é tratado separadamente e pode ser incluído mesmo que a competência
        # de dezembro esteja fora do intervalo mensal escolhido.
        anos_periodo = sorted({int(str(c)[:4]) for c, t in comp_items
                               if t == 'mensal' and _ord_ap_item((str(c), t)) >= inicio_ord
                               and _ord_ap_item((str(c), t)) <= fim_ord})
        if not anos_periodo:
            anos_periodo = sorted({int(str(c)[:4]) for c, t in comp_items
                                   if _ord_ap_item((str(c), t)) >= inicio_ord
                                   and _ord_ap_item((str(c), t)) <= fim_ord})

        treze_base = ap_base[(ap_base['cnpj_declarante'].astype(str).isin(selecionados_cnpjs)) &
                             (ap_base['tipo_competencia'].astype(str) == '13º')].copy()
        anos_13_disponiveis = sorted({int(str(c)[:4]) for c in treze_base['competencia'].dropna().astype(str)})
        anos_13_opcoes = [ano for ano in anos_periodo if ano in anos_13_disponiveis]

        st.markdown('### 3. 13º incluídos na apuração')
        st.caption('O 13º não é incluído automaticamente. Marque, por ano civil, somente os 13º que fazem parte do pedido/cálculo. Os 13º desmarcados permanecem nos dados extraídos, mas ficam fora desta apuração.')
        selecionados_13 = []
        if anos_13_opcoes:
            c13a, c13b = st.columns([1, 3])
            salvos_13 = set(st.session_state.get('decimos_terceiros_incluidos', []))
            for ano in anos_13_opcoes:
                marcado = c13a.checkbox(f'Incluir 13º/{ano}', value=(ano in salvos_13), key=f'apuracao_incluir_13_{ano}')
                if marcado:
                    selecionados_13.append(ano)
                    salvos_13.add(ano)
                else:
                    salvos_13.discard(ano)
            st.session_state.decimos_terceiros_incluidos = sorted(salvos_13)
            if selecionados_13:
                st.success('13º selecionados: ' + ', '.join(f'{a}' for a in selecionados_13))
            else:
                st.info('Nenhum 13º foi selecionado. A apuração considerará somente as competências mensais.')
        else:
            st.info('Não há 13º disponível, entre os declarantes selecionados, para os anos civis abrangidos pelo período.')

        # Filtra por intervalo cronológico mensal e pelos declarantes explicitamente escolhidos.
        # Depois, acrescenta somente os 13º marcados pelo usuário.
        ap_scope_mensal = ap_base[(ap_base['cnpj_declarante'].astype(str).isin(selecionados_cnpjs)) &
                                  (ap_base['tipo_competencia'].astype(str) == 'mensal')].copy()
        ap_scope_mensal['_ord_ap'] = ap_scope_mensal.apply(lambda r: _ord_ap_item((str(r['competencia']), 'mensal')), axis=1)
        ap_scope_mensal = ap_scope_mensal[(ap_scope_mensal['_ord_ap'] >= inicio_ord) & (ap_scope_mensal['_ord_ap'] <= fim_ord)].drop(columns='_ord_ap')

        ap_scope_13 = treze_base[treze_base['competencia'].astype(str).str[:4].isin({str(a) for a in selecionados_13})].copy()
        ap_scope = pd.concat([ap_scope_mensal, ap_scope_13], ignore_index=True)

        st.markdown('### 4. Resultado consolidado')
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
                st.caption('A consolidação considera todos os declarantes explicitamente selecionados acima. A ordem de ocupação do teto adotada nesta versão é: Progressiva → 11% → 20%. O 13º permanece separado de dezembro. Recolhimentos da DIRF são somados mesmo quando a fonte informa remuneração de R$ 0,00.')
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

                        sem_rem = rr.get('fontes_recolhimento_sem_remuneracao', []) or []
                        if sem_rem:
                            st.info('ℹ️ Há fonte(s) com Previdência DIRF recolhida e remuneração informada igual a R$ 0,00. O recolhimento é mantido integralmente na coluna **Recolhido** e participa do cálculo do **Acima do teto**. Como a remuneração é zero, essa fonte não consome o teto nem exige classificação para calcular o máximo da competência.')
                            fontes_sem = fontes_rr[fontes_rr['Remuneração'].apply(lambda x: abs(float(x or 0)) < 0.005)] if not fontes_rr.empty and 'Remuneração' in fontes_rr.columns else pd.DataFrame()
                            if not fontes_sem.empty and 'Previdência DIRF' in fontes_sem.columns:
                                fontes_sem = fontes_sem[fontes_sem['Previdência DIRF'].apply(lambda x: abs(float(x or 0)) >= 0.005)]
                                if not fontes_sem.empty:
                                    st.caption('Fontes identificadas com recolhimento sem remuneração:')
                                    st.dataframe(fontes_sem[cols], use_container_width=True, hide_index=True, column_config={
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

                st.download_button('Baixar apuração CSV', csv_bytes(result), 'apuracao_previdenciaria_v1_2_27.csv', 'text/csv')

with tabs[5]:
    st.subheader('Demonstração horizontal')
    st.caption('A estrutura é dinâmica: cada vínculo selecionado gera duas colunas, Remuneração e Previdência, como na planilha-base. O agrupamento é por identidade do CNPJ, independentemente da página ou bloco da DIRF.')
    mensal = (ap_scope_mensal.copy() if 'ap_scope_mensal' in locals() and isinstance(ap_scope_mensal, pd.DataFrame) and not ap_scope_mensal.empty else calc_df[calc_df.tipo_competencia.eq('mensal')].copy())
    comps = sorted(mensal.competencia.dropna().unique())
    if not comps:
        st.info('Sem dados mensais para os vínculos selecionados.')
    else:
        # Identidade única do vínculo: CNPJ canônico sem máscara.
        # Se um lançamento excepcional vier sem CNPJ válido, usa o nome
        # normalizado apenas como fallback; ele nunca substitui um CNPJ válido.
        mensal['_vinculo_chave'] = mensal['cnpj_chave'].astype(str)
        sem_cnpj = mensal['_vinculo_chave'].eq('')
        mensal.loc[sem_cnpj, '_vinculo_chave'] = mensal.loc[sem_cnpj, 'nome_declarante_dirf'].map(normalize_declarante_name).map(lambda x: 'NOME:' + x if x else 'SEM_IDENTIDADE')

        identidade = (
            mensal.sort_values(['_vinculo_chave', 'nome_declarante_dirf', 'cnpj_declarante'])
            .groupby('_vinculo_chave', dropna=False)
            .agg(
                nome=('nome_declarante_dirf', lambda s: next((str(x) for x in s if str(x).strip()), 'Declarante')),
                cnpj=('cnpj_declarante', lambda s: next((str(x) for x in s if cnpj_identity(x)), ''))
            )
            .to_dict('index')
        )

        rec = []
        for comp in comps:
            g = mensal[mensal.competencia.eq(comp)]
            row = {'Competência': competencia_br(comp, 'mensal')}
            for chave, sg in g.groupby('_vinculo_chave', dropna=False):
                info = identidade.get(chave, {})
                nome = str(info.get('nome') or sg.nome_declarante_dirf.iloc[0])
                cnpj = str(info.get('cnpj') or sg.cnpj_declarante.iloc[0])
                label = f'{nome} | {cnpj}' if cnpj else nome
                row[label + ' — Remuneração'] = float(sg.rendimento_tributavel.sum())
                row[label + ' — Previdência'] = float(sg.previdencia_oficial.sum())
            rec.append(row)
        horiz = pd.DataFrame(rec).fillna(0)
        st.dataframe(horiz, use_container_width=True, hide_index=True, column_config={c: st.column_config.NumberColumn(c, format='R$ %.2f') for c in horiz.columns if c != 'Competência'})
        st.write(f'**{mensal["_vinculo_chave"].nunique()} vínculo(s) representado(s) nas colunas.**')

with tabs[6]:
    st.subheader('Exportações')
    checks = validate_records(records)
    decimos_salvos = sorted(set(st.session_state.get('decimos_terceiros_incluidos', [])))
    json_payload = {
        'schema': 'extrator_dirf.tetoprev.v1',
        'formato_arquivo': 'JSON com extensão .TETOPREV',
        'descricao': 'Base completa + motor + classificações + seleção de vínculos + seleção de 13º + identificação dos autos + auditoria documental.',
        'caso': {
            'id_documento': st.session_state.get('caso_documento_id', ''),
            'processo': st.session_state.get('caso_processo', ''),
            'autor': st.session_state.get('caso_autor', ''),
            'reu': st.session_state.get('caso_reu', ''),
        },
        'registros': df.to_dict(orient='records'),
        'declaracoes': declarations,
        'classificacao_por_cnpj': st.session_state.get('assignments', {}),
        'classificacao_metadados': st.session_state.get('classification_meta', {}),
        'vinculos_incluidos': sorted(st.session_state.get('included_cnpjs', set())),
        'decimos_terceiros_incluidos': decimos_salvos,
        'tetos_utilizados': dict(TETOS),
        'tabelas_historicas': TABELAS_HISTORICAS,
        'validacao_totais': checks,
        'deduplicacao_documental': dedup_stats,
        'registros_utilizados_no_calculo': int((~df['duplicata_documental']).sum()),
    }
    declarantes_relatorio=[]
    if 'selecionados_cnpjs' in locals():
        for cnpj in sorted(selecionados_cnpjs):
            sub=df_calculo[(df_calculo['cnpj_declarante'].astype(str).eq(str(cnpj))) & (df_calculo['tipo_competencia'].isin(['mensal','13º']))].copy()
            if sub.empty: continue
            nomes=sorted(sub['nome_declarante_dirf'].dropna().astype(str).unique(),key=str.casefold)
            grupo=st.session_state.get('assignments',{}).get(str(cnpj),'nao_definido'); gl={'11':'11%','20':'20%','progressiva':'Progressiva','nao_definido':'Não definido'}.get(str(grupo),str(grupo))
            pags=sorted({str(x) for x in sub['pagina_pdf'].dropna().tolist() if str(x).strip()})
            declarantes_relatorio.append({'nome':' / '.join(nomes) or 'Declarante não identificado','cnpj':str(cnpj),'grupo':gl,'paginas':', '.join(pags) if pags else '—'})
    periodo_relatorio=f'{inicio_label} a {fim_label}' if 'inicio_label' in locals() and 'fim_label' in locals() else '—'
    horiz_relatorio=horiz.copy() if 'horiz' in locals() and isinstance(horiz,pd.DataFrame) else pd.DataFrame()
    # O PDF usa a mesma visão consolidada apresentada ao usuário na aba Apuração.
    # O motor mantém colunas técnicas, portanto não se deve passar esse DataFrame
    # técnico diretamente ao gerador que espera os nomes de apresentação.
    if 'resumo_ap_df' in locals() and isinstance(resumo_ap_df, pd.DataFrame):
        result_relatorio = resumo_ap_df.copy()
    elif 'result' in locals() and isinstance(result, pd.DataFrame) and not result.empty:
        _pdf_resumo = []
        for _, rr in result.iterrows():
            tipo = str(rr.get('tipo_competencia', 'mensal'))
            _pdf_resumo.append({
                'Competência': competencia_br(rr.get('competencia', ''), tipo),
                'Tipo': '13º' if tipo == '13º' else 'Mensal',
                'Recolhido': rr.get('soma_contribuicoes_recolhidas', 0),
                'Teto': rr.get('teto_previdenciario', 0),
                'Máx. progressiva': rr.get('contribuicao_maxima_progressiva', 0),
                'Máx. 11%': rr.get('contribuicao_maxima_11', 0),
                'Máx. 20%': rr.get('contribuicao_maxima_20', 0),
                'Máx. total': rr.get('contribuicao_maxima_total', 0),
                'Acima do teto': max(float(rr.get('contribuicao_acima_teto', 0) or 0), 0.0),
                'Status': str(rr.get('status', '')),
            })
        result_relatorio = pd.DataFrame(_pdf_resumo)
    else:
        result_relatorio = pd.DataFrame()
    pdf_relatorio=gerar_relatorio_pdf(result_relatorio,horiz_relatorio,declarantes_relatorio,periodo_relatorio,decimos_salvos,dedup_stats)
    st.download_button('📄 Baixar PDF — Relatório da Análise',pdf_relatorio,'relatorio_apuracao_previdenciaria.pdf','application/pdf',help='Relatório técnico estruturado; a demonstração horizontal é gerada em página paisagem.')

    teto_bytes = json.dumps(json_payload, ensure_ascii=False, indent=2).encode('utf-8')
    teto_nome = nome_arquivo_tetoprev(st.session_state.get('caso_autor', ''))
    st.download_button('⬇️ Baixar arquivo TETOPREV', teto_bytes, teto_nome, 'application/json', help='O conteúdo continua sendo JSON. Apenas a extensão do arquivo é .TETOPREV.')
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
    st.write('Todos os campos extraídos permanecem disponíveis no JSON e nesta visualização. Registros marcados como DUPLICATA_DOCUMENTAL permanecem no RAW para auditoria, mas não são reutilizados nas etapas de cálculo.')
    st.dataframe(df, use_container_width=True, hide_index=True)
