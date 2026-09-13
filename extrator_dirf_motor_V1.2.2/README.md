# Extrator DIRF + Motor Previdenciário — V1.2.2

Refinamento da V1.2 com seleção inteligente de fontes pagadoras no agrupamento.

## Novidades da V1.2.2

- Nome da fonte pagadora passou a ser a identificação principal na tela.
- CNPJ continua visível como dado de conferência, mas não domina a interface.
- Código DIRF e descrição aparecem junto da fonte.
- Códigos claramente financeiros/investimentos (5706, 5557, 6800, 6813 e 8053) ficam desmarcados por padrão quando são exclusivos daquela fonte.
- Fontes sem remuneração mensal e sem Previdência Oficial ficam desmarcadas por padrão.
- Fontes com remuneração e/ou Previdência Oficial são sugeridas para análise.
- Botões para selecionar sugeridas, incluir todas ou limpar seleção.
- Fontes não selecionadas ficam em seção recolhida, sem serem excluídas do RAW.
- A classificação previdenciária continua separada da natureza do código DIRF.
- A guia de verificação progressiva passou a apresentar a fonte por nome + CNPJ.

## V1.2

- Base histórica RGPS 2017–2026.
- Separação entre metodologia tradicional e progressiva.
- Guia independente de Verificação da Alíquota Progressiva.
- Motor principal ainda mantém PROGRESSIVA_EM_VALIDACAO.

## Streamlit Cloud

Main file path:

```text
extrator_dirf_motor_v1_2_1/app.py
```


### V1.2.2
A classificação previdenciária recebe somente fontes selecionadas no agrupamento; fontes excluídas continuam no RAW. O resumo do agrupamento consolida CNPJ único e a verificação progressiva aceita corretamente o modo manual/total.
