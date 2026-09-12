# Extrator DIRF + Motor Previdenciário V1.1

Aplicação Streamlit para extração estruturada de DIRF em PDF e preparação da apuração de contribuições acima do teto.

## Fluxo
1. Extração RAW completa.
2. Consulta com filtros por ano, declarante, CNPJ, código, tipo, competência e grupo.
3. Agrupamento de vínculos/declarantes: cada CNPJ pode ser incluído ou excluído da apuração.
4. Classificação manual por CNPJ em 11%, 20% ou não definido.
5. Apuração por competência com teto histórico cadastrado.
6. Demonstração horizontal dinâmica: cada vínculo selecionado gera Remuneração + Previdência.
7. Exportação JSON/CSV.

## Regra importante
Código DIRF e alíquota efetiva observada não são tratados como prova automática de enquadramento previdenciário.

## Streamlit
Main file path:

`extrator_dirf_motor_v1/app.py`

Não coloque PDFs de processos ou dados pessoais no repositório GitHub.
