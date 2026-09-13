# Changelog — V1.2

## Histórico previdenciário

- Criada `tabelas_previdenciarias.py` como base independente.
- Cobertura cadastrada de 2017 a 2026.
- Separadas as vigências de janeiro-fevereiro/2020 e março-dezembro/2020.
- Separadas as vigências janeiro-abril/2023 e maio-dezembro/2023.
- Registrada a metodologia de cada período: `tradicional` ou `progressiva`.

## Classificação

- Adicionada categoria `progressiva`.
- Mantidas `11`, `20` e `nao_definido`.

## Verificação

- Criada guia independente `🔎 Verificação da Alíquota Progressiva`.
- Cálculo faixa a faixa.
- Comparação opcional com Previdência Oficial extraída da DIRF.
- Status de compatibilidade.
- Tabela histórica consultável.

## Motor

- Mantido o cálculo 11%/20% da V1.1.
- Vínculos progressivos não são calculados silenciosamente: retornam `PROGRESSIVA_EM_VALIDACAO`.
- Isso evita aplicar uma regra de múltiplos vínculos ainda não homologada pelo projeto.

## Auditoria

- Exportação JSON passou para schema `extrator_dirf.v3.2`.
- A base histórica passa a acompanhar a exportação.
