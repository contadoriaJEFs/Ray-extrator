# Extrator DIRF — Integrado

Aplicativo único em Python + Streamlit para extração completa de DIRF e preparação dos dados para a **Planilha - Contr. Previdenciárias**.

## Fluxo

PDF DIRF → extração completa → JSON completo → filtros por Ano/Declarante/CNPJ → competências → **Copiar para Excel**.

## Saída para Excel

O botão **📋 COPIAR PARA EXCEL** copia somente, nesta ordem:

**Declarante | CNPJ | Competência | Rendimentos | Imposto | Previdência**

A cópia é feita em formato tabular para colar diretamente no Excel. O JSON continua completo e preserva todos os campos extraídos.

## Filtros

- Ano
- Declarante
- CNPJ
- Tipo de competência
- Competência

## JSON

O JSON é a base estruturada para a futura automação do cálculo previdenciário. O extrator não calcula alíquotas nem contribuições devidas.

## Publicação no GitHub + Streamlit

Coloque a pasta, por exemplo, em `Extrator-DIRF/` dentro do seu repositório.

No Streamlit Community Cloud:

- Branch: `main`
- Main file path: `Extrator-DIRF/app.py`

Não publique PDFs reais no GitHub.

## Execução local

```bash
pip install -r requirements.txt
streamlit run app.py
```
