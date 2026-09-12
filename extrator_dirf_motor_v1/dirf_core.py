import re, unicodedata, fitz

MONTHS={"Jan":1,"Fev":2,"Mar":3,"Abr":4,"Mai":5,"Jun":6,"Jul":7,"Ago":8,"Set":9,"Out":10,"Nov":11,"Dez":12}
MAIN_COLUMNS=["rendimento_tributavel","irrf","previdencia_oficial","dependentes","pensao_alimenticia","desconto_simplificado","previdencia_complementar","compensacao_judicial_ano_calendario","compensacao_judicial_anos_anteriores"]
CODE_CLASSIFICATION={"0561":"trabalho_assalariado","0588":"trabalho_sem_vinculo","3533":"aposentadoria_reserva_reforma_pensao_previdencia_publica","5928":"decisao_justica_federal","5706":"juros_sobre_capital_proprio","5557":"mercado_renda_variavel","6800":"fundos_investimento","6813":"fundos_acoes","8053":"aplicacoes_financeiras_renda_fixa"}

def clean_spaces(v): return re.sub(r"\s+"," ",v or "").strip()
def money_to_float(v):
    v=v.strip()
    return float(v.replace('.','').replace(',','.')) if v else 0.0
def parse_prefixed(lines,prefix):
    for line in lines:
        if line.startswith(prefix): return clean_spaces(line[len(prefix):])
    return ""
def parse_cnpj(lines):
    for line in lines:
        m=re.match(r"^CNPJ:\s*(.+)$",line)
        if m:return m.group(1).strip()
    return ""
def parse_numbered_field(lines,label):
    for i,line in enumerate(lines):
        if line.startswith(label):
            value=line[len(label):].strip()
            return value or (lines[i+1].strip() if i+1<len(lines) else "")
    return ""
def numeric_tokens(lines,start,count=9):
    nums=[]; j=start
    while j<len(lines) and len(nums)<count:
        if re.fullmatch(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}",lines[j]): nums.append(money_to_float(lines[j])); j+=1
        else: break
    return nums,j

def parse_main_table(lines,code_index):
    start=next((i for i in range(code_index,len(lines)) if lines[i] in MONTHS),None)
    if start is None:return []
    end=next((i for i in range(start,len(lines)) if lines[i]=="Meses"),len(lines))
    rows=[]; i=start
    legacy=["rendimento_tributavel","irrf","previdencia_oficial","dependentes","pensao_alimenticia","previdencia_complementar","compensacao_judicial_ano_calendario","compensacao_judicial_anos_anteriores"]
    while i<end:
        token=lines[i]
        if token in MONTHS or token in ("Tot","13º"):
            vals,nxt=numeric_tokens(lines,i+1,9)
            if len(vals) in (8,9):
                d=dict(zip(MAIN_COLUMNS,vals)) if len(vals)==9 else dict(zip(legacy,vals))
                if len(vals)==8:d["desconto_simplificado"]=0.0
                if token in MONTHS: row={"competencia":MONTHS[token],"competencia_nome":token,"tipo_competencia":"mensal"}
                elif token=="13º": row={"competencia":13,"competencia_nome":token,"tipo_competencia":"13º"}
                else: row={"competencia":None,"competencia_nome":token,"tipo_competencia":"total"}
                row.update(d); rows.append(row); i=nxt; continue
        i+=1
    return rows

def extract_declaration(page,page_number):
    lines=[clean_spaces(x) for x in page.get_text('text').splitlines() if clean_spaces(x)]
    if "Dados do beneficiário:" not in lines:return []
    ano=parse_prefixed(lines,"Ano-calendário:"); ano_int=int(ano) if ano.isdigit() else None
    code_idx=next((i for i,x in enumerate(lines) if x.startswith("Código de receita:")),None)
    if code_idx is None:return []
    code_raw=lines[code_idx][len("Código de receita:"):].strip(); m=re.match(r"(\d+)\s*-\s*(.*)",code_raw)
    codigo=m.group(1) if m else ""; descricao=m.group(2).strip() if m else code_raw
    name_lines=[x for x in lines if x.startswith("Nome constante no cadastro:")]
    dirf_lines=[x for x in lines if x.startswith("Nome constante na Dirf:")]
    benef_cad=clean_spaces(name_lines[0][len("Nome constante no cadastro:"):]) if name_lines else ""
    decl_cad=clean_spaces(name_lines[1][len("Nome constante no cadastro:"):]) if len(name_lines)>1 else ""
    benef_dirf=clean_spaces(dirf_lines[0][len("Nome constante na Dirf:"):]) if dirf_lines else ""
    decl_dirf=clean_spaces(dirf_lines[1][len("Nome constante na Dirf:"):]) if len(dirf_lines)>1 else ""
    rows=parse_main_table(lines,code_idx)
    if not rows:return []
    meta={"pagina_pdf":page_number,"cpf_beneficiario":parse_prefixed(lines,"CPF:"),"nome_beneficiario_cadastro":benef_cad,"nome_beneficiario_dirf":benef_dirf,"cnpj_declarante":parse_cnpj(lines),"nome_declarante_cadastro":decl_cad,"nome_declarante_dirf":decl_dirf,"ano_calendario":ano_int,"data_entrega":parse_prefixed(lines,"Data de entrega:"),"tipo_declaracao":parse_prefixed(lines,"Tipo:"),"situacao_declaracao":parse_prefixed(lines,"Situação:"),"situacao_especial":parse_prefixed(lines,"Situação especial:"),"total_codigos_receita":parse_prefixed(lines,"Total de códigos de receita:"),"codigo_receita":codigo,"descricao_codigo_receita":descricao,"classificacao_codigo":CODE_CLASSIFICATION.get(codigo,"nao_classificado"),"fundo_clube":parse_numbered_field(lines,"Fundo/Clube:"),"numero_processo":parse_numbered_field(lines,"Número do processo:")}
    out=[]
    for r in rows:
        item={**meta,**r}
        if r['tipo_competencia']=='mensal' and ano_int:item['competencia']=f"{ano_int}-{r['competencia']:02d}"
        elif r['tipo_competencia']=='13º' and ano_int:item['competencia']=f"{ano_int}-13"
        out.append(item)
    return out

def extract_pdf(file_bytes):
    doc=fitz.open(stream=file_bytes,filetype='pdf'); records=[]; declarations=[]
    for pno,page in enumerate(doc,1):
        if "Dados do beneficiário:" not in page.get_text('text'):continue
        pr=extract_declaration(page,pno)
        if pr:
            declarations.append(pr[0]); records.extend(pr)
    return records,declarations,len(doc)
