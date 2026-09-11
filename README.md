# Extrator DIRF

Aplicação Streamlit para extração estruturada de informações de DIRF em PDF.

## Escopo

- Identificação do beneficiário e do declarante
- CNPJ e nomes constantes no cadastro/DIRF
- Ano-calendário e situação da declaração
- Código e descrição da receita
- Valores da primeira tabela mensal
- Separação de competências mensais, 13º e total
- Rastreabilidade por arquivo e página
- Validação dos totais
- Exportação para JSON, CSV e Excel

> **Importante:** esta versão é um extrator. Não calcula alíquota, contribuição previdenciária devida ou diferença previdenciária. A classificação do código de receita é apenas auxiliar.

## Publicação no Streamlit Community Cloud

1. Crie um repositório no GitHub, por exemplo `extrator-dirf`.
2. Envie `app.py`, `requirements.txt`, `README.md` e `.gitignore`.
3. No Streamlit Community Cloud, conecte sua conta GitHub.
4. Selecione o repositório, a branch e o arquivo `app.py`.
5. Publique o aplicativo.

O aplicativo não contém PDFs reais do processo. O usuário faz o upload do PDF diretamente na aplicação.

## Execução local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Estrutura

```text
extrator-dirf/
├── app.py
├── requirements.txt
├── README.md
└── .gitignore
```

## Arquitetura

```text
DIRF PDF
   ↓
EXTRATOR
   ↓
BASE RAW / ESTRUTURADA
   ↓
CLASSIFICAÇÃO DO VÍNCULO
   ↓
REGRAS PREVIDENCIÁRIAS
   ↓
CONFERÊNCIA
```

Os dados extraídos devem permanecer rastreáveis à página e ao arquivo de origem. O tratamento previdenciário deve ser desenvolvido em uma camada separada.
