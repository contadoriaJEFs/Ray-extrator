
import io
import re
import json
import unicodedata
from pathlib import Path

import pandas as pd
import streamlit as st
import fitz


MONTHS = {
    "Jan": 1, "Fev": 2, "Mar": 3, "Abr": 4, "Mai": 5, "Jun": 6,
    "Jul": 7, "Ago": 8, "Set": 9, "Out": 10, "Nov": 11, "Dez": 12,
}

# Colunas que aparecem na primeira tabela da DIRF.
MAIN_COLUMNS = [
    "rendimento_tributavel",
    "irrf",
    "previdencia_oficial",
    "dependentes",
    "pensao_alimenticia",
    "desconto_simplificado",
    "previdencia_complementar",
    "compensacao_judicial_ano_calendario",
    "compensacao_judicial_anos_anteriores",
]

CODE_CLASSIFICATION = {
    "0561": "trabalho_assalariado",
    "0588": "trabalho_sem_vinculo",
    "3533": "aposentadoria_reserva_reforma_pensao_previdencia_publica",
    "5928": "decisao_justica_federal",
    "5706": "juros_sobre_capital_proprio",
    "5557": "mercado_renda_variavel",
    "6800": "fundos_investimento",
    "6813": "fundos_acoes",
    "8053": "aplicacoes_financeiras_renda_fixa",
}


def clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def money_to_float(value: str) -> float:
    value = value.strip()
    if not value:
        return 0.0
    # DIRF brasileira: 1.234,56
    return float(value.replace(".", "").replace(",", "."))


def normalize_key(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    return "".join(c for c in value if not unicodedata.combining(c)).lower()


def parse_prefixed(lines, prefix):
    for line in lines:
        if line.startswith(prefix):
            return clean_spaces(line[len(prefix):])
    return ""


def parse_cnpj(lines):
    for line in lines:
        m = re.match(r"^CNPJ:\s*(.+)$", line)
        if m:
            return m.group(1).strip()
    return ""


def parse_numbered_field(lines, label):
    for i, line in enumerate(lines):
        if line.startswith(label):
            value = line[len(label):].strip()
            if value:
                return value
            if i + 1 < len(lines):
                return lines[i + 1].strip()
    return ""


def numeric_tokens(lines, start_index, count=9):
    nums = []
    j = start_index
    while j < len(lines) and len(nums) < count:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}", lines[j]):
            nums.append(money_to_float(lines[j]))
        else:
            break
        j += 1
    return nums, j


def parse_main_table(lines, code_index):
    # A tabela começa depois do cabeçalho "Meses Rendimento..." e termina
    # antes da segunda tabela ("Meses Exigibilidade Suspensa").
    # A extração de texto quebra "Meses Rendimento" em várias linhas.
    # O primeiro mês real (Jan) marca o início da tabela de competências.
    start = next(
        (i for i in range(code_index, len(lines)) if lines[i] in MONTHS),
        None
    )
    if start is None:
        return []

    # A primeira ocorrência de "Meses" depois dos meses marca o início
    # da tabela de exigibilidade suspensa.
    end = next(
        (i for i in range(start, len(lines)) if lines[i] == "Meses"),
        len(lines)
    )

    rows = []
    i = start
    while i < end:
        token = lines[i]
        if token in MONTHS:
            vals, nxt = numeric_tokens(lines, i + 1, 9)
            if len(vals) == 8:
                legacy_columns = [
                    "rendimento_tributavel", "irrf", "previdencia_oficial",
                    "dependentes", "pensao_alimenticia",
                    "previdencia_complementar",
                    "compensacao_judicial_ano_calendario",
                    "compensacao_judicial_anos_anteriores",
                ]
                vals = dict(zip(legacy_columns, vals))
                vals["desconto_simplificado"] = 0.0
            elif len(vals) == 9:
                vals = dict(zip(MAIN_COLUMNS, vals))
            else:
                vals = None

            if vals is not None:
                row = {
                    "competencia": MONTHS[token],
                    "competencia_nome": token,
                }
                if isinstance(vals, dict):
                    row.update(vals)
                else:
                    row.update(dict(zip(MAIN_COLUMNS, vals)))
                row["tipo_competencia"] = "mensal"
                rows.append(row)
                i = nxt
                continue
        if token == "Tot":
            vals, nxt = numeric_tokens(lines, i + 1, 9)
            if len(vals) in (8, 9):
                row = {"competencia": None, "competencia_nome": "Tot", "tipo_competencia": "total"}
                if len(vals) == 8:
                    legacy = ["rendimento_tributavel","irrf","previdencia_oficial","dependentes",
                              "pensao_alimenticia","previdencia_complementar",
                              "compensacao_judicial_ano_calendario","compensacao_judicial_anos_anteriores"]
                    row.update(dict(zip(legacy, vals)))
                    row["desconto_simplificado"] = 0.0
                else:
                    row.update(dict(zip(MAIN_COLUMNS, vals)))
                rows.append(row)
                i = nxt
                continue
        if token == "13º":
            vals, nxt = numeric_tokens(lines, i + 1, 9)
            if len(vals) in (8, 9):
                row = {"competencia": 13, "competencia_nome": "13º", "tipo_competencia": "13º"}
                if len(vals) == 8:
                    legacy = ["rendimento_tributavel","irrf","previdencia_oficial","dependentes",
                              "pensao_alimenticia","previdencia_complementar",
                              "compensacao_judicial_ano_calendario","compensacao_judicial_anos_anteriores"]
                    row.update(dict(zip(legacy, vals)))
                    row["desconto_simplificado"] = 0.0
                else:
                    row.update(dict(zip(MAIN_COLUMNS, vals)))
                rows.append(row)
                i = nxt
                continue
        i += 1

    return rows


def extract_declaration(page, page_number):
    raw = page.get_text("text")
    lines = [clean_spaces(x) for x in raw.splitlines() if clean_spaces(x)]

    if "Dados do beneficiário:" not in lines:
        return []

    ano = parse_prefixed(lines, "Ano-calendário:")
    ano_int = int(ano) if ano.isdigit() else None

    code_idx = next(
        (i for i, x in enumerate(lines) if x.startswith("Código de receita:")),
        None
    )
    if code_idx is None:
        return []

    code_raw = lines[code_idx][len("Código de receita:"):].strip()
    m = re.match(r"(\d+)\s*-\s*(.*)", code_raw)
    codigo = m.group(1) if m else ""
    descricao = m.group(2).strip() if m else code_raw

    cadastro_benef = parse_prefixed(lines, "Nome constante no cadastro:")
    # A primeira ocorrência é do beneficiário; a segunda é do declarante.
    name_lines = [x for x in lines if x.startswith("Nome constante no cadastro:")]
    dirf_lines = [x for x in lines if x.startswith("Nome constante na Dirf:")]

    beneficiario_cadastro = clean_spaces(name_lines[0][len("Nome constante no cadastro:"):]) if name_lines else ""
    declarante_cadastro = clean_spaces(name_lines[1][len("Nome constante no cadastro:"):]) if len(name_lines) > 1 else ""
    beneficiario_dirf = clean_spaces(dirf_lines[0][len("Nome constante na Dirf:"):]) if dirf_lines else ""
    declarante_dirf = clean_spaces(dirf_lines[1][len("Nome constante na Dirf:"):]) if len(dirf_lines) > 1 else ""

    rows = parse_main_table(lines, code_idx)
    if not rows:
        return []

    fundo = parse_numbered_field(lines, "Fundo/Clube:")
    processo = parse_numbered_field(lines, "Número do processo:")

    meta = {
        "pagina_pdf": page_number,
        "cpf_beneficiario": parse_prefixed(lines, "CPF:"),
        "nome_beneficiario_cadastro": beneficiario_cadastro,
        "nome_beneficiario_dirf": beneficiario_dirf,
        "cnpj_declarante": parse_cnpj(lines),
        "nome_declarante_cadastro": declarante_cadastro,
        "nome_declarante_dirf": declarante_dirf,
        "ano_calendario": ano_int,
        "data_entrega": parse_prefixed(lines, "Data de entrega:"),
        "tipo_declaracao": parse_prefixed(lines, "Tipo:"),
        "situacao_declaracao": parse_prefixed(lines, "Situação:"),
        "situacao_especial": parse_prefixed(lines, "Situação especial:"),
        "total_codigos_receita": parse_prefixed(lines, "Total de códigos de receita:"),
        "codigo_receita": codigo,
        "descricao_codigo_receita": descricao,
        "classificacao_codigo": CODE_CLASSIFICATION.get(codigo, "nao_classificado"),
        "fundo_clube": fundo,
        "numero_processo": processo,
    }

    result = []
    for r in rows:
        item = {**meta, **r}
        if r["tipo_competencia"] == "mensal" and ano_int:
            item["competencia"] = f"{ano_int}-{r['competencia']:02d}"
        elif r["tipo_competencia"] == "13º" and ano_int:
            item["competencia"] = f"{ano_int}-13"
        result.append(item)
    return result


def extract_pdf(file_bytes):
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    records = []
    declarations = []
    for pno, page in enumerate(doc, start=1):
        if "Dados do beneficiário:" not in page.get_text("text"):
            continue
        page_records = extract_declaration(page, pno)
        if page_records:
            declarations.append(page_records[0])
            records.extend(page_records)
    return records, declarations, len(doc)


def validate_records(records):
    df = pd.DataFrame(records)
    checks = []
    if df.empty:
        return checks

    monthly = df[df["tipo_competencia"] == "mensal"].copy()
    block_keys = [
        "arquivo_origem", "pagina_pdf", "ano_calendario",
        "cnpj_declarante", "codigo_receita", "fundo_clube", "numero_processo"
    ]

    for keys, grp in monthly.groupby(block_keys, dropna=False):
        mask = pd.Series(True, index=df.index)
        for col, value in zip(block_keys, keys if isinstance(keys, tuple) else (keys,)):
            if pd.isna(value):
                mask &= df[col].isna()
            else:
                mask &= df[col].eq(value)
        total = df[mask & df["tipo_competencia"].eq("total")]
        if total.empty:
            continue
        expected = round(grp["rendimento_tributavel"].sum(), 2)
        informed = round(float(total.iloc[0]["rendimento_tributavel"]), 2)
        diff = round(expected - informed, 2)
        checks.append({
            "arquivo": keys[0], "pagina": keys[1], "ano": keys[2],
            "cnpj": keys[3], "codigo": keys[4], "fundo_clube": keys[5],
            "numero_processo": keys[6], "soma_meses": expected,
            "total_DIRF": informed, "diferenca": diff,
            "status": "OK" if abs(diff) < 0.01 else "DIVERGÊNCIA",
        })
    return checks


def fmt_brl(v):
    if pd.isna(v):
        return ""
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def competencia_br(competencia_iso, tipo):
    """Representação para planilha/CSV no padrão brasileiro."""
    if tipo == "13º":
        if isinstance(competencia_iso, str) and re.fullmatch(r"\d{4}-13", competencia_iso):
            return f"13º/{competencia_iso[:4]}"
        return "13º"
    if tipo == "mensal" and isinstance(competencia_iso, str):
        m = re.fullmatch(r"(\d{4})-(\d{2})", competencia_iso)
        if m:
            return f"01/{m.group(2)}/{m.group(1)}"
    return ""


def csv_bytes(selected_df):
    """CSV brasileiro: UTF-8 com BOM, ; como separador e vírgula decimal."""
    return selected_df.to_csv(
        index=False, sep=";", decimal=",", encoding="utf-8-sig", lineterminator="\r\n"
    ).encode("utf-8-sig")


st.set_page_config(page_title="Extrator DIRF", page_icon="📄", layout="wide")

st.title("Extrator DIRF")
st.caption("Extração estruturada da primeira tabela mensal da DIRF — sem cálculo previdenciário.")

with st.sidebar:
    st.header("Entrada")
    files = st.file_uploader(
        "Selecione uma ou mais DIRFs em PDF",
        type=["pdf"],
        accept_multiple_files=True
    )
    st.divider()
    st.markdown("**Escopo desta versão**")
    st.write("• Extração dos dados do beneficiário e declarante")
    st.write("• Código e descrição da receita")
    st.write("• Valores por competência")
    st.write("• 13º separado")
    st.write("• Validação dos totais")
    st.write("• Exportação CSV, Excel e JSON")
    st.warning("A classificação é apenas informativa. Nenhuma alíquota ou contribuição devida é calculada nesta versão.")

if not files:
    st.info("Envie uma ou mais DIRFs para iniciar a extração.")
    st.stop()

all_records = []
all_declarations = []
file_errors = []

for uploaded in files:
    try:
        records, declarations, pages = extract_pdf(uploaded.getvalue())
        for r in records:
            r["arquivo_origem"] = uploaded.name
        for d in declarations:
            d["arquivo_origem"] = uploaded.name
            d["paginas_pdf"] = pages
        all_records.extend(records)
        all_declarations.extend(declarations)
    except Exception as exc:
        file_errors.append({"arquivo": uploaded.name, "erro": str(exc)})

if file_errors:
    st.error("Um ou mais arquivos não puderam ser processados.")
    st.dataframe(pd.DataFrame(file_errors), use_container_width=True)

if not all_records:
    st.error("Nenhum bloco DIRF reconhecível foi encontrado.")
    st.stop()

df = pd.DataFrame(all_records)

# Ordenação lógica
order = {"mensal": 1, "13º": 2, "total": 3}
df["_ordem"] = df["tipo_competencia"].map(order).fillna(9)
df = df.sort_values(
    ["ano_calendario", "arquivo_origem", "pagina_pdf", "_ordem", "competencia"],
    na_position="last"
).drop(columns=["_ordem"])

st.success(f"{len(all_declarations)} blocos de declaração identificados e {len(df)} registros estruturados.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Arquivos", len(files))
c2.metric("Blocos DIRF", len(all_declarations))
c3.metric("Registros", len(df))
c4.metric("Anos", df["ano_calendario"].nunique())

st.subheader("Declarações identificadas")
decl_cols = [
    "ano_calendario", "cnpj_declarante", "nome_declarante_dirf",
    "codigo_receita", "descricao_codigo_receita",
    "tipo_declaracao", "situacao_declaracao", "pagina_pdf", "arquivo_origem"
]
st.dataframe(
    df[decl_cols].drop_duplicates().reset_index(drop=True),
    use_container_width=True,
    hide_index=True
)

st.subheader("Consulta para a Planilha - Contr. Previdenciárias")

consulta = df[df["tipo_competencia"].isin(["mensal", "13º"])].copy()
consulta["competencia_br"] = consulta.apply(
    lambda r: competencia_br(r["competencia"], r["tipo_competencia"]), axis=1
)

# Filtros: o resultado filtrado é o conjunto que será copiado para o Excel.
f1, f2, f3 = st.columns(3)
anos = sorted(consulta["ano_calendario"].dropna().astype(str).unique(), reverse=True)
ano_sel = f1.selectbox("Ano", ["Todos"] + anos)

base = consulta[consulta["ano_calendario"].astype(str).eq(ano_sel)] if ano_sel != "Todos" else consulta

decls = sorted(base["nome_declarante_dirf"].dropna().astype(str).unique(), key=str.casefold)
decl_sel = f2.selectbox("Declarante", ["Todos"] + decls)
base = base[base["nome_declarante_dirf"].astype(str).eq(decl_sel)] if decl_sel != "Todos" else base

cnpjs = sorted(base["cnpj_declarante"].dropna().astype(str).unique())
cnpj_sel = f3.selectbox("CNPJ", ["Todos"] + cnpjs)
base = base[base["cnpj_declarante"].astype(str).eq(cnpj_sel)] if cnpj_sel != "Todos" else base

f4, f5 = st.columns(2)
tipos = [x for x in ["mensal", "13º"] if x in set(base["tipo_competencia"].astype(str))]
tipo_sel = f4.selectbox("Tipo", ["Todos"] + tipos)
base = base[base["tipo_competencia"].astype(str).eq(tipo_sel)] if tipo_sel != "Todos" else base

comps = sorted(base["competencia_br"].dropna().astype(str).unique())
comp_sel = f5.multiselect("Competência", comps, default=comps)
if comp_sel:
    base = base[base["competencia_br"].isin(comp_sel)]
else:
    base = base.iloc[0:0]

# Saída operacional fixa: exatamente as seis colunas desejadas.
saida = base[[
    "nome_declarante_dirf", "cnpj_declarante", "competencia_br",
    "rendimento_tributavel", "irrf", "previdencia_oficial"
]].copy()
saida.columns = ["Declarante", "CNPJ", "Competência", "Rendimentos", "Imposto", "Previdência"]

st.markdown("**Resultado que será levado para o Excel**")
st.caption(
    "O filtro acima funciona como a segmentação. O botão copia somente as seis colunas abaixo. "
    "O JSON completo permanece preservado separadamente."
)

# Visualização formatada para conferência.
view = saida.copy()
for col in ["Rendimentos", "Imposto", "Previdência"]:
    view[col] = view[col].map(fmt_brl)
st.dataframe(view, use_container_width=True, hide_index=True)
st.write(f"**{len(saida)} registro(s) no resultado.**")

# Componente HTML embutido: um clique copia TSV diretamente para o clipboard.
# Valores financeiros são enviados como números com vírgula decimal; CNPJ permanece texto.
copy_rows = []
for r in saida.itertuples(index=False):
    copy_rows.append([
        str(r[0] or ""), str(r[1] or ""), str(r[2] or ""),
        f"{float(r[3] or 0):.2f}".replace(".", ","),
        f"{float(r[4] or 0):.2f}".replace(".", ","),
        f"{float(r[5] or 0):.2f}".replace(".", ","),
    ])

copy_payload = json.dumps(copy_rows, ensure_ascii=False)
copy_component = f"""
<!doctype html><html><body style='margin:0;font-family:Arial,sans-serif'>
<button id='copy' style='padding:11px 18px;border:0;border-radius:8px;background:#111827;color:white;font-weight:700;cursor:pointer'>
📋 COPIAR PARA EXCEL
</button>
<span id='msg' style='margin-left:10px;font-size:13px;color:#475467'></span>
<script>
const rows={copy_payload};
const head=['Declarante','CNPJ','Competência','Rendimentos','Imposto','Previdência'];
function tsv(){{return [head,...rows].map(r=>r.join('\\t')).join('\\n');}}
document.getElementById('copy').onclick=async()=>{{
  const text=tsv(); const msg=document.getElementById('msg');
  try {{ await navigator.clipboard.writeText(text); msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).'; }}
  catch(e) {{
    const ta=document.createElement('textarea'); ta.value=text; document.body.appendChild(ta); ta.select();
    try {{ document.execCommand('copy'); msg.textContent='✓ Copiado. Agora cole no Excel (Ctrl+V).'; }}
    catch(err) {{ msg.textContent='Não foi possível acessar a área de transferência neste navegador.'; }}
    ta.remove();
  }}
}};
</script></body></html>
"""
st.components.v1.html(copy_component, height=55, scrolling=False)

st.divider()
st.subheader("Exportações")

json_payload = {
    "schema": "extrator_dirf.v2",
    "descricao": "Extração completa e rastreável da DIRF. O JSON preserva todos os campos extraídos.",
    "registros": all_records,
}
json_data = json.dumps(json_payload, ensure_ascii=False, indent=2).encode("utf-8")

# CSV completo/personalizável continua disponível para auditoria e outras finalidades.
export_df = df.copy()
export_df["competencia_br"] = export_df.apply(
    lambda r: competencia_br(r["competencia"], r["tipo_competencia"]), axis=1
)
essential_cols = [
    "ano_calendario", "cnpj_declarante", "nome_declarante_dirf", "codigo_receita",
    "competencia_br", "tipo_competencia", "rendimento_tributavel", "irrf",
    "previdencia_oficial", "pagina_pdf", "arquivo_origem",
]
all_cols = list(export_df.columns)

preset = st.radio("CSV", ["Essenciais previdenciárias", "Todas as colunas", "Personalizado"], horizontal=True)
if preset == "Essenciais previdenciárias":
    selected_cols = [c for c in essential_cols if c in export_df.columns]
elif preset == "Todas as colunas":
    selected_cols = all_cols
else:
    selected_cols = st.multiselect("Colunas do CSV", all_cols, default=[c for c in essential_cols if c in export_df.columns])

if selected_cols:
    csv_df = export_df[selected_cols].copy()
    labels = {
        "ano_calendario":"Ano", "cnpj_declarante":"CNPJ Declarante", "nome_declarante_dirf":"Declarante",
        "codigo_receita":"Código Receita", "descricao_codigo_receita":"Descrição Código Receita",
        "competencia_br":"Competência", "competencia":"Competência ISO", "tipo_competencia":"Tipo",
        "rendimento_tributavel":"Rendimento Tributável", "irrf":"Imposto Retido", "previdencia_oficial":"Previdência Oficial",
        "dependentes":"Dependentes", "pensao_alimenticia":"Pensão Alimentícia", "desconto_simplificado":"Desconto Simplificado",
        "previdencia_complementar":"Previdência Complementar", "compensacao_judicial_ano_calendario":"Compensação Judicial Ano-Calendário",
        "compensacao_judicial_anos_anteriores":"Compensação Judicial Anos Anteriores", "fundo_clube":"Fundo/Clube",
        "numero_processo":"Número do Processo", "pagina_pdf":"Página PDF", "arquivo_origem":"Arquivo Origem",
    }
    csv_df = csv_df.rename(columns={k:v for k,v in labels.items() if k in csv_df.columns})
    st.download_button("Baixar CSV", csv_bytes(csv_df), "extracao_dirf_selecionado.csv", "text/csv")

st.download_button("Baixar JSON completo", json_data, "extracao_dirf_completa.json", "application/json")

with st.expander("Registro bruto / auditoria"):
    st.write("Todos os campos extraídos permanecem disponíveis no JSON e nesta visualização de auditoria.")
    st.dataframe(df, use_container_width=True, hide_index=True)
