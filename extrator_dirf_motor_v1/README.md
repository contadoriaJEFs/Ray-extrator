# Extrator DIRF + Motor Previdenciário V1

Pipeline:

`PDF DIRF → extração RAW → normalização → classificação por CNPJ → apuração por competência → demonstração horizontal`

## Princípios
- O JSON preserva os campos extraídos.
- O código DIRF não é tratado como prova automática de alíquota previdenciária.
- `aliquota_efetiva_observada` é apenas indicador diagnóstico.
- A classificação 11%/20% é feita por CNPJ na interface.
- CNPJ sem classificação fica `nao_definido` e bloqueia a apuração silenciosa daquela competência.
- O número de declarantes é dinâmico.
- O motor V1 reproduz a lógica da planilha-base fornecida: teto → base 11% → saldo → base 20% → contribuição máxima → excesso.

## Teto
A tabela V1 utiliza somente valores presentes nas planilhas fornecidas no projeto: 2020–2025. Não são inventados valores posteriores.

## Execução
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Arquivos
- `app.py`: interface Streamlit
- `dirf_core.py`: extração DIRF
- `motor_previdenciario.py`: regras do motor V1
