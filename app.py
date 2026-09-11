
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
    for keys, grp in monthly.groupby(["ano_calendario", "cnpj_declarante", "codigo_receita"], dropna=False):
        total = df[
            (df["ano_calendario"] == keys[0]) &
            (df["cnpj_declarante"] == keys[1]) &
            (df["codigo_receita"] == keys[2]) &
            (df["tipo_competencia"] == "total")
        ]
        if total.empty:
            continue
        expected = grp["rendimento_tributavel"].sum()
        informed = float(total.iloc[0]["rendimento_tributavel"])
        diff = round(expected - informed, 2)
        checks.append({
            "ano": keys[0],
            "cnpj": keys[1],
            "codigo": keys[2],
            "soma_meses": expected,
            "total_DIRF": informed,
            "diferenca": diff,
            "status": "OK" if abs(diff) < 0.01 else "DIVERGÊNCIA",
        })
    return checks


def fmt_brl(v):
    if pd.isna(v):
        return ""
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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

st.subheader("Competências extraídas")

display = df[df["tipo_competencia"].isin(["mensal", "13º"])].copy()
display["competencia_exibicao"] = display["competencia"].astype(str)
for col in ["rendimento_tributavel", "irrf", "previdencia_oficial"]:
    display[col] = display[col].map(fmt_brl)

view_cols = [
    "ano_calendario", "competencia_exibicao", "cnpj_declarante",
    "nome_declarante_dirf", "codigo_receita",
    "rendimento_tributavel", "irrf", "previdencia_oficial",
    "tipo_competencia", "pagina_pdf"
]
st.dataframe(display[view_cols], use_container_width=True, hide_index=True)

st.subheader("Validação dos totais")
checks = validate_records(all_records)
if checks:
    cdf = pd.DataFrame(checks)
    st.dataframe(cdf, use_container_width=True, hide_index=True)
    if (cdf["status"] == "DIVERGÊNCIA").any():
        st.warning("Existem grupos cuja soma mensal não coincide com o total informado na DIRF.")
    else:
        st.success("As somas mensais conferem com os totais encontrados.")
else:
    st.info("Não foi possível formar grupos de validação com total mensal.")

st.subheader("Exportação")
json_data = json.dumps(all_records, ensure_ascii=False, indent=2).encode("utf-8")
csv_data = df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")

xlsx_buffer = io.BytesIO()
with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
    df.to_excel(writer, index=False, sheet_name="Dados")
    if checks:
        pd.DataFrame(checks).to_excel(writer, index=False, sheet_name="Validacao")
    pd.DataFrame(all_declarations).to_excel(writer, index=False, sheet_name="Declaracoes")
xlsx_buffer.seek(0)

b1, b2, b3 = st.columns(3)
b1.download_button("Baixar JSON", json_data, "extracao_dirf.json", "application/json")
b2.download_button("Baixar CSV", csv_data, "extracao_dirf.csv", "text/csv")
b3.download_button(
    "Baixar Excel",
    xlsx_buffer.getvalue(),
    "extracao_dirf.xlsx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

with st.expander("Registro bruto / auditoria"):
    st.write("Cada registro mantém a página de origem, o arquivo de origem e os metadados da declaração.")
    st.dataframe(df, use_container_width=True, hide_index=True)
