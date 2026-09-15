# Extrator DIRF + Motor Previdenciário — V1.2.12

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
extrator_dirf_motor_v1_2_9/app.py
```


### V1.2.2
A classificação previdenciária recebe somente fontes selecionadas no agrupamento; fontes excluídas continuam no RAW. O resumo do agrupamento consolida CNPJ único e a verificação progressiva aceita corretamente o modo manual/total.

## V1.2.5 — verificação anual por fonte
A guia 🔎 Verificação agora permite selecionar ano-calendário + fonte/vínculo e auditar automaticamente as competências mensais encontradas. O ano organiza a análise; a competência continua sendo a unidade de cálculo. Cada mês identifica sua própria tabela histórica, inclusive nas mudanças de vigência de 2020 e 2023.


## V1.2.5
- Interface brasileira para competências (`MM/AAAA`) e datas (`DD/MM/AAAA`).
- Verificação anual por fonte com tolerância padrão de R$ 0,01 ou tolerância personalizada pelo usuário, registrada na auditoria.
- Comparação feita com precisão interna antes do arredondamento visual.


## V1.2.12 — Apuração por competência

- A guia 🧮 Apuração passou a consolidar N vínculos por competência.
- O cálculo usa a classificação final das fontes: Progressiva, 11% e 20%.
- A ocupação do teto segue, nesta versão, a ordem prática Progressiva → 11% → 20%.
- A contribuição efetivamente informada na DIRF é preservada separadamente.
- O sistema calcula o máximo permitido e o valor acima do teto por competência.
- O 13º permanece separado de dezembro e é apurado em competência própria.
- A guia 🔎 Verificação passou a usar a classificação confirmada da fonte somente para a coluna Previdência Calculada; a consolidação entre vínculos permanece na Apuração.
- A Apuração inclui detalhamento das fontes consolidadas, bases, máximos por grupo e faixas da parcela progressiva.
- Casos práticos de janeiro/2025 e julho/2025 foram incorporados aos testes.


## V1.2.12
Correção: a Previdência Oficial da DIRF é considerada na apuração mesmo quando a fonte informa remuneração zero.
