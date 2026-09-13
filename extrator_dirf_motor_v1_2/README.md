# Extrator DIRF + Motor Previdenciário V1.2

Aplicação Streamlit para extração estruturada de DIRF em PDF, preservação do RAW e preparação da apuração previdenciária.

## Novidades da V1.2

1. **Classificação previdenciária ampliada**
   - 11%
   - 20%
   - PROGRESSIVA
   - não definida

2. **Base histórica do RGPS desde 2017** em `tabelas_previdenciarias.py`.
   - 2017–2019: metodologia tradicional (8%, 9%, 11%).
   - janeiro–fevereiro/2020: metodologia tradicional.
   - março/2020 em diante: metodologia progressiva.
   - 2023 possui duas vigências (jan–abr e mai–dez).

3. **Guia independente `🔎 Verificação`**
   - seleciona competência e fonte/CNPJ;
   - permite usar os valores extraídos da DIRF ou informar valores manualmente;
   - demonstra faixa por faixa;
   - calcula a contribuição;
   - compara com a Previdência Oficial informada na DIRF;
   - classifica o resultado como COMPATÍVEL, DIFERENÇA PARA ANÁLISE ou SEM COMPARAÇÃO.

4. **Tutorial contextual discreto** na própria página explicando a mudança da metodologia.

5. **Motor principal preservado:** 11% e 20% continuam seguindo a lógica da planilha-base. A categoria PROGRESSIVA é reconhecida, mas o motor principal retorna `PROGRESSIVA_EM_VALIDACAO` enquanto a regra de múltiplos vínculos estiver sendo validada na guia independente.

6. **Exportação** passa a incluir a base histórica utilizada.

## Fonte e escopo da base histórica

A base foi estruturada para **Empregado, Empregado Doméstico e Trabalhador Avulso do RGPS**. Não misturar automaticamente com tabelas de contribuinte individual, facultativo ou RPPS.

O PDF oficial do INSS fornecido no projeto contém as tabelas históricas de 2017, 2018, 2019 e janeiro-fevereiro de 2020, além das tabelas de outras categorias. A partir de março de 2020, o eSocial registra a adoção da sistemática progressiva. As vigências posteriores foram conferidas em fontes oficiais do Governo Federal.

## Múltiplos vínculos

A partir de março de 2020, a sistemática progressiva exige atenção especial aos múltiplos vínculos. O eSocial orienta que as remunerações de outros empregadores sejam consideradas para que as faixas seguintes sejam aplicadas corretamente, respeitado o teto.

Por isso, a V1.2 **não transforma automaticamente cada CNPJ em um cálculo progressivo independente**.

## Fluxo

```text
DIRF PDF
   ↓
EXTRAÇÃO RAW COMPLETA
   ↓
FILTROS
   ↓
AGRUPAMENTO DE VÍNCULOS
   ↓
CLASSIFICAÇÃO
  ├── 11%
  ├── 20%
  ├── PROGRESSIVA
  └── NÃO DEFINIDA
   ↓
🔎 VERIFICAÇÃO HISTÓRICA
   ↓
MOTOR 11% / 20%
   ↓
DEMONSTRAÇÃO HORIZONTAL
   ↓
EXPORTAÇÃO
```

## Validação já realizada

A DIRF de teste `Suzana Marine - DIRFs.pdf` foi extraída com:

- 135 páginas;
- 101 blocos de declaração;
- 1.414 registros estruturados;
- 101 verificações de totais;
- 0 divergências na soma dos meses contra o total informado pela DIRF.

## Streamlit Cloud

Main file path:

`extrator_dirf_motor_v1_2/app.py`

Não coloque PDFs de processos ou dados pessoais no repositório GitHub.
