# CHANGELOG — Extrator DIRF + Motor Previdenciário


Histórico consolidado das versões V1.2.x. Os arquivos individuais de changelog foram reunidos neste documento para manter o repositório enxuto.


---

## V1.2.25

- Reformulação da Demonstração Horizontal no relatório PDF.
- Relatório PDF integralmente em A4 paisagem.
- Declarantes apresentados em lista própria com nome, CNPJ, enquadramento e páginas.
- Cabeçalho da demonstração passa a agrupar cada CNPJ sobre as colunas Remuneração e Previdência.
- Demonstração dividida em blocos de até 6 CNPJs por página para preservar legibilidade.
- Resultado consolidado passa a iniciar em página própria, evitando quebra no meio da tabela.
- Mantidas as regras do motor, deduplicação, classificação e apuração existentes.

---

<!-- Fonte: CHANGELOG_V1_2_24.md -->

# V1.2.24 — Confirmação explícita da classificação automática

## Correção

Na tela **Classificação**, uma sugestão automática que coincidia com a opção exibida no seletor podia ser registrada indevidamente como confirmação do usuário durante a renderização.

### Nova regra de interação
- A sugestão automática permanece apenas como sugestão até haver uma ação explícita do usuário.
- Alterar o `selectbox` para outra classificação continua registrando a alteração como decisão do usuário.
- Quando a classificação sugerida já estiver selecionada, o usuário pode clicar em **Confirmar [classificação]**.
- Assim, para uma sugestão **Progressiva**, basta manter **Progressiva** e clicar em **Confirmar Progressiva**.
- Não é mais necessário escolher outra classificação e retornar à original.

## Persistência
A confirmação continua vinculada ao CNPJ e é utilizada nas etapas posteriores de Verificação, Demonstração e Apuração.

## Testes
- `python -m py_compile app.py classificador_previdenciario.py motor_previdenciario.py`
- `python tests_smoke.py`

Todos os smoke tests existentes foram concluídos com sucesso.


---

<!-- Fonte: CHANGELOG_V1_2_23.md -->

# V1.2.23 — UX judicial e relatório técnico

## Mantido
- Motor previdenciário e metodologia atual.
- Deduplicação documental conservadora.
- Seleção de 13º por ano civil.
- Persistência em `.TETOPREV`.
- Classificação por CNPJ existente.
- CNIS, GERID e eSocial permanecem fora da implementação.

## Novidades
- Identidade visual mais sóbria e técnica no Streamlit.
- Cabeçalho visual de sistema de análise judicial.
- Modal de confirmação ao carregar trabalho `.TETOPREV`, mostrando processo e autor disponíveis.
- Processo não é mais inferido pelo nome do arquivo; somente dados efetivamente disponíveis no RAW/TETOPREV podem preencher o campo automaticamente.
- PDF de Relatório da Análise na aba Exportação.
- Relatório estruturado em tabelas, com identificação dos autos, declarantes utilizados, páginas, período, 13º incluídos, resultado consolidado e demonstração horizontal.
- Demonstração horizontal do relatório em página paisagem.
- Valores monetários no PDF em padrão brasileiro `1.234,56`, com `R$` somente nos quadros-resumo.
- Demonstração horizontal da interface acompanha o escopo mensal da apuração quando disponível.


---

<!-- Fonte: CHANGELOG_V1_2_22.md -->

# V1.2.22

## Correção — restauração do número do processo

- Corrigida a restauração da identificação dos autos ao carregar `.TETOPREV`.
- O processo gravado no bloco `caso` tem prioridade.
- Se o campo estiver vazio, o sistema procura o número CNJ nos registros e também no nome do arquivo PDF de origem.
- Exemplo suportado: `0031059-48.2026.4.05.8300_DIRF.pdf` → `0031059-48.2026.4.05.8300`.
- Ao carregar TETOPREV, os campos de identificação são restaurados explicitamente, evitando que valores antigos da sessão impeçam o preenchimento.
- Não foram implementadas regras de CNIS, GERID ou eSocial.
- Motor previdenciário e regras de apuração permanecem inalterados.


---

<!-- Fonte: CHANGELOG_V1_2_21.md -->

# V1.2.21

## Arquivo de trabalho TETOPREV + identificação judicial

- Mantido o motor previdenciário da V1.2.20.
- Exportação do JSON completo + motor passa a usar extensão `.TETOPREV`.
- O conteúdo do arquivo continua sendo JSON.
- Nome automático do arquivo: quatro primeiros nomes do autor, separados por `_`, seguidos de `HHMMSSmm.TETOPREV`.
- Novo carregador de `.TETOPREV`/JSON para retomar um trabalho sem reenviar a DIRF.
- O carregamento restaura classificação por CNPJ, vínculos incluídos, seleção de 13º e identificação dos autos gravada no arquivo.
- Entrada judicial com nº do processo, nome do autor, nome do réu e ID do documento analisado.
- Nº do processo e nome do autor são preenchidos automaticamente quando encontrados no RAW da DIRF.
- O réu permanece editável/manual, pois não é um campo confiável da DIRF extraída.
- Relatório documental recolhível, organizado por página, com identificação da declaração, CNPJ, declarante, ano, código, tipo, situação, data de entrega, processo e demais dados disponíveis.
- Auditoria recolhível das duplicidades documentais, com páginas e comparação de competências, remunerações e Previdência.
- Nenhuma regra nova de CNIS, GERID, eSocial ou matriz previdenciária foi implementada nesta versão.


---

<!-- Fonte: CHANGELOG_V1_2_20.md -->

# Changelog — V1.2.20

## Deduplicação documental conservadora

Correção para PDFs em que o advogado/documento juntado contém a mesma declaração DIRF repetida em páginas diferentes do mesmo arquivo.

### O que foi implementado

- O RAW continua preservando **todas as ocorrências extraídas**.
- Cada bloco recebe uma assinatura documental baseada no conteúdo integral da declaração.
- A página não participa da assinatura; portanto, a mesma declaração repetida em outra página é reconhecida como a mesma declaração.
- A primeira ocorrência, pela menor página, é marcada como `CANONICO`.
- As ocorrências posteriores idênticas são marcadas como `DUPLICATA_DOCUMENTAL`.
- A duplicata continua visível na auditoria e no JSON.
- Somente registros canônicos entram em:
  - agrupamento;
  - classificação;
  - verificação;
  - apuração;
  - demonstração horizontal.
- A identidade do vínculo continua sendo o CNPJ, independentemente de página/bloco.
- Uma declaração que tenha qualquer diferença material em seus dados não é eliminada pela deduplicação.

### Teste com o PDF do caso

No arquivo `0031059-48.2026.4.05.8300_DIRF.pdf` foram identificados 16 blocos, sendo 8 declarações únicas e 8 cópias integrais. Assim, os valores de setembro/outubro do FUNDO MUNICIPAL DE SAUDE — CNPJ 10.392.418/0001-45 — deixam de ser somados duas vezes.


---

<!-- Fonte: CHANGELOG_V1_2_19.md -->

# Changelog — V1.2.19

## Correção da filtragem cronológica da Apuração

A V1.2.18 introduziu a seleção explícita de 13º por ano, mas a filtragem do escopo da Apuração ainda utilizava uma tupla `(ano, mês)` como chave cronológica. Em algumas DIRFs, o pandas podia falhar nessa comparação e gerar `ValueError` durante o filtro do período.

### Correção

A chave cronológica agora é escalar e numérica:

- `AAAA01` a `AAAA12` para competências mensais;
- `AAAA13` para o 13º.

Exemplo:

```text
202501
202502
...
202512
202513  ← 13º
```

Isso mantém o 13º imediatamente após dezembro e elimina a comparação de Series com tuplas.

### O que permanece inalterado

- extração RAW;
- agrupamento de vínculos;
- classificação;
- verificação;
- motor previdenciário;
- hierarquia Progressiva → 11% → 20%;
- regra de remuneração zero com previdência positiva;
- seleção explícita de declarantes;
- seleção do 13º por ano civil.

A alteração desta versão é exclusivamente a correção da chave de ordenação/filtro da Apuração.


---

<!-- Fonte: CHANGELOG_V1_2_18.md -->

# Changelog — V1.2.18

## Inclusão explícita do 13º por ano civil na Apuração

Alteração pontual sobre o último modelo V1.2.17.

### Regra

O 13º deixa de entrar automaticamente na Apuração apenas por existir dentro do histórico ou por o respectivo ano estar dentro do período mensal selecionado.

A Apuração passa a apresentar uma seleção por ano civil:

- `☐ Incluir 13º/2021`
- `☐ Incluir 13º/2022`
- `☐ Incluir 13º/2023`
- etc.

Somente os anos marcados pelo usuário são acrescentados à Apuração.

### Exemplos

Período `01/2025 a 12/2025`:

- `13º/2025` aparece para seleção;
- permanece desmarcado por padrão;
- se não for marcado, não participa da Apuração.

Período `01/2021 a 12/2025`:

- o sistema apresenta os 13º disponíveis de 2021 a 2025;
- cada ano pode ser incluído ou excluído independentemente.

Isso permite, por exemplo, incluir 2021, 2022 e 2023, mas deixar 2024 e 2025 fora.

### Preservações

Não foram alterados nesta versão:

- motor de extração;
- RAW;
- classificação previdenciária;
- hierarquia Progressiva → 11% → 20%;
- motor de apuração mensal;
- regra de consolidação dos vínculos;
- tratamento de remuneração zero com Previdência DIRF positiva;
- guia de Verificação;
- Demonstração horizontal.

O 13º continua sendo competência própria, separada de dezembro.


---

<!-- Fonte: CHANGELOG_V1_2_17.md -->

# CHANGELOG V1.2.17

## Correção — Verificação deve respeitar a classificação persistente do vínculo

### Problema
Ao selecionar na guia **Verificação** um declarante/CNPJ que já havia sido definido como **11%**, a consolidação interna por competência removia a coluna de classificação. Como consequência, a linha podia cair em `nao_definido` e a função de verificação padrão aplicava indevidamente a **tabela progressiva**.

### Correção
A Verificação agora recupera explicitamente a classificação persistente do CNPJ selecionado em `st.session_state.assignments` antes de consolidar as ocorrências da DIRF.

A classificação é preservada durante o agrupamento por:
- competência;
- ano;
- tipo de competência;
- blocos e páginas diferentes da DIRF.

### Regra
```text
CNPJ selecionado
      ↓
classificação definida para o CNPJ
      ↓
11% / 20% / Progressiva
      ↓
Verificação utiliza o mesmo tipo
      ↓
Apuração e Demonstração utilizam o mesmo vínculo/classificação
```

### 13º
O 13º continua separado de dezembro, mas, quando o vínculo possui classificação definida, a Verificação passa a utilizar essa classificação também no cálculo individual de referência, mantendo o status de **análise conjunta**.

### Importante
A correção não altera a tela de Apuração nem sua hierarquia de cálculo:

```text
Progressiva → 11% → 20%
```

Ela apenas garante que a fonte chegue às etapas seguintes com a classificação que já foi definida para seu CNPJ.


---

<!-- Fonte: CHANGELOG_V1_2_16.md -->

# V1.2.16 — Hierarquia de ocupação do teto

- A Apuração passa a aplicar de forma fixa a hierarquia **Progressiva → 11% → 20%**.
- O Máximo Total é a soma das contribuições máximas dos três grupos, cada qual utilizando somente o saldo de teto remanescente após o grupo anterior.
- A existência de um vínculo 11% permanece independente do máximo disponível naquela competência. Se a Progressiva consumir todo o teto, o Máx. 11% pode ser R$ 0,00 sem que o vínculo seja encerrado.
- Mantida a regra de considerar a Previdência DIRF mesmo quando a remuneração da fonte é R$ 0,00.
- Atualizado o teste de março/2023 para refletir a planilha de referência.


---

<!-- Fonte: CHANGELOG_V1_2_15.md -->

# Changelog V1.2.16

## Correções

### 1. Identidade persistente do vínculo
- A classificação previdenciária passa a ser resolvida pela chave canônica do CNPJ.
- Páginas, blocos separados, lacunas de remuneração e retornos posteriores do mesmo CNPJ não criam novo vínculo nem nova classificação.
- A Demonstração e a Apuração continuam consolidadas por CNPJ.

### 2. Máximo de 11% em conjunto com fonte progressiva
- Quando existe grupo 11% na competência, o cálculo passa a ocupar o teto primeiro pelo grupo 11%, depois 20% e, por fim, progressiva, alinhando-se ao modelo da planilha Daniel Moreira.
- Assim, a presença posterior de uma fonte progressiva não zera indevidamente o Máx. 11% quando o vínculo 11% continua ativo.
- Quando não existe grupo 11%, preserva-se a ordem progressiva → 20%, compatível com a planilha prática de 2025 usada no projeto.

### 3. Regressão
- Incluído teste para CNPJ 11% persistente em blocos separados e para o cenário de março/2023 com 11% + 20% + progressiva.


---

<!-- Fonte: CHANGELOG_V1_2_14.md -->

# CHANGELOG V1.2.14

## Correção — identidade contínua do mesmo vínculo/CNPJ

Foi reforçada a identidade do vínculo na Demonstração horizontal e nas etapas que dependem da identidade do declarante.

### Regra

O mesmo declarante deve permanecer no mesmo vínculo/coluna durante todo o histórico quando possuir o mesmo CNPJ, mesmo que a DIRF esteja dividida em blocos e o declarante:

- apareça em páginas muito distantes;
- deixe de apresentar remuneração por várias competências;
- volte a aparecer posteriormente;
- apareça em blocos diferentes dentro do mesmo arquivo;
- tenha diferenças de máscara/formatação no CNPJ.

### Identidade

Foi criada uma chave interna `cnpj_chave`, formada pelos 14 dígitos do CNPJ, sem pontuação. A demonstração horizontal utiliza essa identidade para consolidar as ocorrências.

Quando uma ocorrência não possuir CNPJ válido, permanece o fallback pelo nome normalizado apenas quando não houver ambiguidade.

### Efeito esperado

Exemplo:

```text
04/2021 a 02/2023
SECRETARIA DE SAÚDE — CNPJ X

03/2023 a 12/2023
SECRETARIA DE SAÚDE — CNPJ X
```

Deve resultar em **uma única coluna** para o vínculo, com todas as remunerações e contribuições somadas por competência.

A existência de competências com remuneração R$ 0,00 não encerra o vínculo.

### Caso de teste de regressão

Um vínculo 11% que possui recolhimentos sem remuneração entre blocos intermediários e volta a apresentar remuneração posteriormente deve continuar sendo tratado como o mesmo vínculo até a última competência efetivamente existente.

Não deve ser criada uma nova coluna para o mesmo CNPJ.


---

<!-- Fonte: CHANGELOG_V1_2_13.md -->

# CHANGELOG V1.2.13

## Correção — agrupamento da Demonstração horizontal

- O agrupamento horizontal passa a utilizar o CNPJ em forma canônica, eliminando diferenças de pontuação/formatação entre páginas da mesma DIRF.
- Ocorrências do mesmo CNPJ em páginas/blocos distintos são consolidadas nas mesmas duas colunas: **Remuneração** e **Previdência**.
- Quando uma página/bloco vier sem CNPJ, o sistema tenta recuperar o CNPJ somente quando o nome do declarante apontar inequivocamente para um único CNPJ já identificado no arquivo.
- Nunca são mesclados CNPJs diferentes apenas por coincidência de nome.
- A soma por competência continua preservando todos os lançamentos encontrados no RAW.

## Testes

- `py_compile` dos módulos principais: OK.
- testes smoke existentes: OK.


---

<!-- Fonte: CHANGELOG_V1_2_12.md -->

# V1.2.13 — Verificação simplificada

## Alteração

A guia **Verificação** deixa de apresentar a contribuição previdenciária calculada e a diferença entre DIRF e cálculo como resultados da análise.

### Mantido
- Previdência Oficial extraída da DIRF;
- Remuneração;
- Metodologia;
- Tabela histórica;
- status de análise;
- análise específica do 13º;
- período e fonte selecionados;
- detalhamento por competência;
- cópia para Excel.

### Removido da apresentação da Verificação
- coluna **Calculada**;
- coluna **Diferença**;
- métricas de calculada/diferença;
- exibição da comparação numérica DIRF × calculada.

### Regra de arquitetura

A Verificação é uma camada de conferência/análise. O cálculo previdenciário consolidado definitivo ocorre exclusivamente na **Apuração**, onde os valores são somados por tipo (Progressiva, 11% e 20%), o teto é aplicado e somente então é determinado o eventual valor acima do teto.

A Previdência Oficial da DIRF continua sendo preservada como dado original e continua participando da Apuração, inclusive quando a remuneração da fonte for R$ 0,00.


---

<!-- Fonte: CHANGELOG_V1_2_11.md -->

# V1.2.11 — Recolhimento com remuneração zero

## Correção

- A Apuração agora preserva e soma a **Previdência Oficial da DIRF** mesmo quando a fonte informa **R$ 0,00 de remuneração**.
- Uma fonte com remuneração zero e recolhimento positivo não consome o teto e não bloqueia a competência por classificação pendente, pois sua base máxima é R$ 0,00.
- O detalhamento da Apuração identifica explicitamente essas fontes.
- O RAW permanece inalterado.

## Caso de regressão

Abril/2021, conforme planilha de referência:

- COOMEB: remuneração R$ 23.290,64; Previdência R$ 620,62.
- Secretaria Estadual de Saúde: remuneração R$ 0,00; Previdência R$ 366,35.
- Total recolhido: R$ 986,97.
- Contribuição máxima: R$ 707,69.
- Acima do teto: R$ 279,28.

## Testes

- Smoke tests anteriores preservados.
- Novo teste de recolhimento sem remuneração: OK.
- Novo teste sem classificação da fonte de remuneração zero: OK.


---

<!-- Fonte: CHANGELOG_V1_2_10.md -->

# V1.2.10 — Escopo explícito da Apuração

## Alterações

- A guia **🧮 Apuração** agora permite definir explicitamente o período da apuração.
- Opções de período: todo o histórico, intervalo personalizado ou um ano.
- A guia apresenta explicitamente os **declarantes utilizados**.
- O usuário pode selecionar/desselecionar declarantes por nome + CNPJ.
- A consolidação é realizada somente com os declarantes e competências dentro do escopo selecionado.
- O detalhamento de cada competência identifica os declarantes efetivamente consolidados.
- A extração RAW permanece intacta e não é alterada pela seleção do escopo da apuração.
- Mantida a separação do 13º em relação às competências mensais.
- Mantida a lógica de consolidação para N vínculos.

## Validação

- Smoke tests: OK.
- Testes de apuração conjunta: OK.
- Testes de classificação na verificação: OK.


---

<!-- Fonte: CHANGELOG_V1_2_9.md -->

# V1.2.9 — Apuração por competência

## Apuração
- Consolidação automática de N vínculos por competência.
- Tratamento conjunto dos grupos `progressiva`, `11` e `20`.
- Ordem de ocupação do teto: Progressiva → 11% → 20%, conforme a lógica prática da planilha-base usada nesta etapa.
- Cálculo de contribuição máxima e valor acima do teto.
- Preservação da contribuição efetivamente informada na DIRF.
- 13º tratado separadamente de dezembro.
- Detalhamento das fontes, bases, grupos e faixas progressivas.

## Verificação
- A classificação final da fonte passa a alimentar a coluna **Previdência Calculada**.
- A consolidação entre vínculos não é feita na Verificação; ela permanece exclusiva da Apuração.

## Validação
- Janeiro/2025: máximo total R$ 1.081,45 e excesso R$ 9,21 no caso prático de dois vínculos.
- Julho/2025: progressiva consome o teto; máximo 20% = R$ 0,00 e excesso R$ 718,77.
- Testes smoke e testes específicos de apuração/classificação concluídos.


---

<!-- Fonte: CHANGELOG_V1_2_8.md -->

# V1.2.8 — Classificação automática + edição pelo usuário

- Criado `classificador_previdenciario.py` com regras determinísticas e auditáveis.
- Cada fonte selecionada recebe `classificacao_sugerida`, `nivel_confianca`, `evidencias`, `regra_classificacao` e `versao_regra`.
- Padrões estáveis próximos de 11% ou 20% podem ser sugeridos automaticamente com alta confiança.
- Variação de taxas compatível com faixas progressivas pode gerar sugestão progressiva.
- Evidência insuficiente permanece `nao_definido` ou com confiança baixa/média, exigindo confirmação.
- A classificação final continua editável individualmente.
- Alterações feitas pelo usuário são registradas como `origem_classificacao = usuario`.
- Metadados de classificação são preservados na exportação JSON.
- Motor de extração não foi alterado.


---

<!-- Fonte: CHANGELOG_V1_2_7.md -->

# CHANGELOG V1.2.7

## 13º na Verificação

- A aba **Verificação** passou a carregar competências `mensal` e `13º`.
- O **13º aparece imediatamente após dezembro** de cada ano.
- O 13º permanece como tipo de competência separado e não é agregado a dezembro.
- A tabela histórica do 13º é identificada pela vigência de dezembro do respectivo ano.
- A verificação do 13º é marcada como **análise conjunta** quando há Previdência Oficial informada, evitando tratar uma comparação por fonte isolada como conclusão definitiva em situações com múltiplos vínculos.
- O detalhamento do 13º mantém tabela, teto, faixas e valores da DIRF para auditoria.
- Exportação/Cópia para Excel passou a incluir a coluna **Tipo** (Mensal/13º).


---

<!-- Fonte: CHANGELOG_V1_2_6.md -->

# CHANGELOG V1.2.6

## Classificação previdenciária — refinamento da interface

- Reorganizada a aba **Classificação** em cartões visuais por fonte/vínculo.
- Removida a coluna redundante **Incluído** da tabela-resumo inferior.
- Explicitado que **Alíquota efetiva observada** é apenas diagnóstico da DIRF e não define a classificação.
- Renomeado conceitualmente o campo de decisão para **Grupo previdenciário**.
- Opções do grupo passaram a ter descrição amigável:
  - Não definido — requer confirmação;
  - 11% — contribuição fixa;
  - 20% — contribuição fixa;
  - Progressiva — aplicar tabela histórica.
- Mantida a persistência da classificação durante a sessão.
- Mantida a alimentação da aba **Verificação** pela classificação selecionada.
- Mantido `nao_definido` como trava de segurança contra classificação silenciosa.
- Mantida a preservação integral do RAW.
- Mantido o detalhamento por competência da aba **Verificação** sem alterações.


---

<!-- Fonte: CHANGELOG_V1_2_5.md -->

# Changelog — V1.2.5

## Verificação histórica
- Substituída a navegação obrigatória por um único ano por três modos:
  - Todos os anos disponíveis;
  - Intervalo de anos;
  - Um ano.
- A escolha do período serve para navegação/consolidação; o cálculo continua competência a competência.
- Ao selecionar uma fonte, o sistema carrega automaticamente o histórico mensal encontrado dentro do período.
- Registros da mesma fonte e competência são consolidados antes da verificação para evitar duplicidade quando houver mais de um registro/código no mesmo mês.

## Usabilidade
- Mantido o padrão brasileiro de competência `MM/AAAA`.
- Adicionado botão explícito **📋 COPIAR PARA EXCEL** para a tabela consolidada da Verificação, com cabeçalho e valores.
- Mantido o detalhamento expansível por competência, inicialmente recolhido.
- Mantidos CSV e demais mecanismos de exportação.

## Tolerância
- Mantida tolerância padrão de R$ 0,01.
- Mantida tolerância personalizada pelo usuário, com identificação da origem do critério.
- A comparação continua usando a diferença interna antes do arredondamento visual.

## Preservação da lógica
- Não houve alteração da lógica principal de apuração 11%/20%.
- A metodologia progressiva continua na bancada de verificação e não foi incorporada silenciosamente ao motor principal.


---

<!-- Fonte: CHANGELOG_V1_2_4.md -->

# CHANGELOG — V1.2.4

## Interface brasileira
- Competências exibidas na interface no padrão `MM/AAAA` (ex.: `01/2020`).
- Datas completas exibidas no padrão `DD/MM/AAAA` quando apresentadas.
- Vigências históricas exibidas em padrão brasileiro.
- Valores e percentuais permanecem em padrão brasileiro na apresentação.

## Verificação da progressiva
- Mantida a navegação por ano-calendário + fonte/vínculo.
- Adicionada tolerância padrão do sistema de R$ 0,01.
- Adicionada opção de tolerância personalizada informada pelo usuário.
- O resultado registra a origem da tolerância: `SISTEMA — PADRÃO` ou `USUÁRIO`.
- A comparação utiliza a diferença interna antes do arredondamento visual.
- A diferença apresentada continua com duas casas; a auditoria pode exibir a diferença interna com quatro casas.
- A tolerância altera somente o status de compatibilidade; não altera o cálculo previdenciário.

## Auditoria
- Os resultados da verificação passam a carregar `tolerancia_utilizada`, `tolerancia_origem` e `diferenca_bruta`.

## Testes
- Smoke tests executados após as alterações.


---

<!-- Fonte: CHANGELOG_V1_2_3.md -->

# CHANGELOG — V1.2.3

## Verificação anual por fonte

- A guia de verificação deixou de operar apenas por competência isolada.
- O usuário seleciona primeiro o **ano-calendário** e uma **fonte/vínculo selecionado**.
- O sistema carrega automaticamente as competências mensais encontradas para aquela fonte no ano.
- Cada competência continua sendo calculada individualmente, com sua própria tabela e metodologia.
- O resumo anual mostra remuneração, Previdência DIRF, contribuição calculada, diferença e contagem de status.
- Cada competência pode ser expandida para auditoria das faixas, bases e contribuições.
- O modo continua independente do motor principal.
- A seleção de fontes da guia respeita o agrupamento: somente fontes incluídas em 🔗 Agrupamento aparecem para verificação.

## Regressão

- Smoke tests executados com sucesso.
- Base histórica 2017–2026 preservada.
- Motor 11%/20% preservado.
- Progressiva continua em validação antes da integração definitiva ao motor.


---

<!-- Fonte: CHANGELOG_V1_2.md -->

# CHANGELOG — V1.2.1

## Agrupamento inteligente de fontes

### Interface
- A fonte pagadora é identificada visualmente pelo nome; CNPJ fica como informação secundária.
- Código DIRF e descrição são exibidos junto à fonte.
- Inclusão/remoção continua sendo manual e persistida durante a sessão.

### Seleção inicial
- 5706, 5557, 6800, 6813 e 8053, quando exclusivos da fonte, são tratados como não previdenciários para a seleção inicial.
- Fonte sem remuneração mensal e sem Previdência Oficial também não é sugerida.
- Fontes com remuneração e/ou Previdência Oficial permanecem sugeridas para análise.

### Preservação de dados
- Nenhum registro é eliminado do RAW.
- A desmarcação afeta apenas as camadas de agrupamento, classificação/apuração e demonstração.
- Foi incluído botão para incluir todas as fontes, permitindo recuperar fontes inicialmente excluídas.

### Verificação
- Seleção de fonte na guia de verificação usa nome + CNPJ, evitando a lista de CNPJs isolados.

## Compatibilidade
- A base histórica 2017–2026 permanece.
- A lógica 11%/20% permanece.
- PROGRESSIVA continua separada do motor principal até a validação dos múltiplos vínculos.


## V1.2.2 — correções de fluxo e interface
- A guia 🧩 Classificação passa a exibir exclusivamente as fontes selecionadas em 🔗 Agrupamento de vínculos.
- Fontes não selecionadas continuam preservadas no RAW/auditoria, mas não recebem classificação nem entram na camada de cálculo.
- O resumo do agrupamento consolida cada CNPJ uma única vez, mesmo quando há nomes declarantes repetidos para o mesmo CNPJ.
- Corrigida a chave da guia 🔎 Verificação para a opção Manual / total da competência, evitando TypeError quando não existe CNPJ selecionado.
- Versão da aplicação atualizada para V1.2.2.
