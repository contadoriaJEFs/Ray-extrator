# Extrator DIRF — V2

Aplicação Streamlit para extração estruturada de informações de DIRF em PDF.

## Objetivo

Extrair os dados da DIRF por **declarante e competência**, preservando a base completa para uso futuro em um motor automatizado de cálculo previdenciário.

A extração principal contempla:

- Rendimento Tributável
- Imposto Retido
- Previdência Oficial

A aplicação também preserva todas as demais colunas extraídas da tabela DIRF.

## V2 — alterações

- **JSON sempre completo**, com todos os campos extraídos e rastreabilidade.
- **CSV com seleção de colunas**: essenciais previdenciárias, todas ou personalizado.
- Competência no CSV em **padrão brasileiro** (`01/01/2025`); o 13º permanece separado (`13º/2025`).
- JSON mantém a competência técnica (`YYYY-MM` e `YYYY-13`).
- CSV em UTF-8 com BOM, `;` como separador e `,` como decimal, adequado ao Excel brasileiro.
- Validação dos totais por bloco/página para evitar mistura de declarações.

## Arquitetura

```text
DIRF PDF
   ↓
EXTRATOR
   ↓
BASE COMPLETA / JSON
   ├── CSV com colunas escolhidas
   └── Excel
   ↓
FUTURO MOTOR PREVIDENCIÁRIO
   ↓
CÁLCULO / CONFERÊNCIA
```

O extrator não calcula alíquota ou contribuição devida. Essa etapa será desenvolvida separadamente, usando o JSON como fonte estruturada.

## Publicação no Streamlit Community Cloud

1. Crie um repositório no GitHub, por exemplo `extrator-dirf`.
2. Envie `app.py`, `requirements.txt`, `README.md` e `.gitignore`.
3. No Streamlit Community Cloud, conecte o GitHub.
4. Selecione o repositório, branch `main` e arquivo `app.py`.
5. Publique.

**Não coloque PDFs reais de processos no GitHub.** O PDF deve ser enviado pelo usuário à aplicação.

## Execução local

```bash
pip install -r requirements.txt
streamlit run app.py
```
