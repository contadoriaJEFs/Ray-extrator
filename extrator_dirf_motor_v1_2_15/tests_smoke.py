from motor_previdenciario import verificar_tabela, tabela_por_competencia
from dirf_core import extract_pdf, validate_records
from pathlib import Path
import pandas as pd

EXPECTED = {
    '2017-01':'2017','2019-12':'2019','2020-01':'2020_01_02','2020-03':'2020_03_12',
    '2021-12':'2021','2022-01':'2022','2023-04':'2023_01_04','2023-05':'2023_05_12',
    '2024-01':'2024','2025-01':'2025','2026-01':'2026'
}
for comp, ident in EXPECTED.items():
    assert tabela_por_competencia(comp)['id'] == ident
assert round(verificar_tabela('2019-01', 4000)['contribuicao_calculada'], 2) == 440.00
assert round(verificar_tabela('2020-03', 4000)['contribuicao_calculada'], 2) == 418.95
p = Path('/mnt/data/Suzana Marine - DIRFs.pdf')
if p.exists():
    records, declarations, pages = extract_pdf(p.read_bytes())
    for r in records: r['arquivo_origem'] = p.name
    checks = validate_records(records)
    assert len(records) == 1414
    assert len(declarations) == 101
    assert pages == 135
    assert len(checks) == 101
    assert not [x for x in checks if x['status'] != 'OK']
print('OK — smoke tests concluídos.')


# V1.2.4: tolerância usa diferença interna antes do arredondamento visual.
from motor_previdenciario import verificar_tabela
r = verificar_tabela('2023-02', 1674.66, 131.18, tolerancia=0.01)
assert r['status'] == 'COMPATIVEL'
r2 = verificar_tabela('2023-02', 1674.66, 131.201, tolerancia=0.01)
assert r2['status'] == 'DIFERENCA_PARA_ANALISE'
r3 = verificar_tabela('2023-02', 1674.66, 131.201, tolerancia=0.02)
assert r3['status'] == 'COMPATIVEL'

# V1.2.7 — 13º é competência própria e usa a tabela de dezembro do ano.
from motor_previdenciario import verificar_13o
r13 = verificar_13o(2024, 5500.63, 566.89)
assert r13['tipo_competencia'] == '13º'
assert r13['competencia'] == '2024-13'
assert r13['tabela_id'] == '2024'
assert r13['status'] == 'ANALISE_13O_CONJUNTA'

# V1.2.9 — apuração conjunta de múltiplos vínculos, seguindo a planilha-base.
from motor_previdenciario import apurar_competencia

def _caso(comp, rem_prog, prev_prog, rem20, prev20):
    return pd.DataFrame([
        {'competencia': comp, 'tipo_competencia': 'mensal', 'cnpj_declarante': 'A', 'nome_declarante_dirf': 'Sociedade Pernambucana', 'grupo_previdenciario': 'progressiva', 'rendimento_tributavel': rem_prog, 'previdencia_oficial': prev_prog},
        {'competencia': comp, 'tipo_competencia': 'mensal', 'cnpj_declarante': 'B', 'nome_declarante_dirf': 'Coopanest', 'grupo_previdenciario': '20', 'rendimento_tributavel': rem20, 'previdencia_oficial': prev20},
    ])

jan25 = apurar_competencia(_caso('2025-01', 5993.86, 657.95, 114310.77, 432.71), 8157.41)
assert jan25['status'] == 'OK'
assert round(jan25['contribuicao_maxima_progressiva'], 2) == 648.74
assert round(jan25['saldo_teto_apos_progressiva'], 2) == 2163.55
assert round(jan25['contribuicao_maxima_20'], 2) == 432.71
assert round(jan25['contribuicao_maxima_total'], 2) == 1081.45
assert round(jan25['soma_contribuicoes_recolhidas'], 2) == 1090.66
assert round(jan25['contribuicao_acima_teto'], 2) == 9.21

jul25 = apurar_competencia(_caso('2025-07', 13555.14, 1516.88, 71384.43, 153.53), 8157.41)
assert jul25['status'] == 'OK'
assert round(jul25['contribuicao_maxima_progressiva'], 2) == 951.64
assert round(jul25['saldo_teto_apos_progressiva'], 2) == 0.00
assert round(jul25['contribuicao_maxima_20'], 2) == 0.00
assert round(jul25['contribuicao_maxima_total'], 2) == 951.64
assert round(jul25['soma_contribuicoes_recolhidas'], 2) == 1670.41
assert round(jul25['contribuicao_acima_teto'], 2) == 718.77

print('OK — testes V1.2.9 de apuração conjunta concluídos.')


# V1.2.9 — a Verificação respeita a classificação da fonte apenas na coluna calculada.
from motor_previdenciario import verificar_por_grupo
r20 = verificar_por_grupo('2025-07', 71384.43, '20', 153.53)
assert round(r20['contribuicao_calculada'], 2) == 1631.48
r11 = verificar_por_grupo('2025-07', 5000, '11', 550)
assert round(r11['contribuicao_calculada'], 2) == 550.00
print('OK — testes V1.2.9 de classificação na verificação concluídos.')


# V1.2.11 — Previdência DIRF deve ser considerada mesmo quando a remuneração da fonte é zero.
caso_sem_rem = pd.DataFrame([
    {'competencia': '2021-04', 'tipo_competencia': 'mensal', 'cnpj_declarante': 'A', 'nome_declarante_dirf': 'COOMEB', 'grupo_previdenciario': '11', 'rendimento_tributavel': 23290.64, 'previdencia_oficial': 620.62},
    {'competencia': '2021-04', 'tipo_competencia': 'mensal', 'cnpj_declarante': 'B', 'nome_declarante_dirf': 'Secretaria Estadual de Saúde', 'grupo_previdenciario': '11', 'rendimento_tributavel': 0.00, 'previdencia_oficial': 366.35},
])
r_sem_rem = apurar_competencia(caso_sem_rem, 6433.57)
assert r_sem_rem['status'] == 'OK'
assert round(r_sem_rem['soma_contribuicoes_recolhidas'], 2) == 986.97
assert round(r_sem_rem['contribuicao_maxima_total'], 2) == 707.69
assert round(r_sem_rem['contribuicao_acima_teto'], 2) == 279.28
assert 'B' in r_sem_rem['fontes_recolhimento_sem_remuneracao']

# A fonte sem remuneração e com recolhimento não deve bloquear a apuração mesmo sem classificação.
caso_sem_class = caso_sem_rem.copy()
caso_sem_class.loc[caso_sem_class['cnpj_declarante'].eq('B'), 'grupo_previdenciario'] = 'nao_definido'
r_sem_class = apurar_competencia(caso_sem_class, 6433.57)
assert r_sem_class['status'] == 'OK'
assert round(r_sem_class['soma_contribuicoes_recolhidas'], 2) == 986.97
assert round(r_sem_class['contribuicao_acima_teto'], 2) == 279.28
print('OK — V1.2.11: recolhimento com remuneração zero preservado na apuração.')

# V1.2.15 — vínculo persistente por CNPJ e prioridade do grupo 11% quando ele existe.
from motor_previdenciario import classificar_declarante
split = pd.DataFrame([
    {'cnpj_declarante':'10.572.048/0001-28','cnpj_chave':'10572048000128','grupo_previdenciario':'nao_definido','rendimento_tributavel':0,'previdencia_oficial':366.35},
    {'cnpj_declarante':'10.572.048/0001-28','cnpj_chave':'10572048000128','grupo_previdenciario':'nao_definido','rendimento_tributavel':1000,'previdencia_oficial':110},
])
cs = classificar_declarante(split, {'10.572.048/0001-28':'11'})
assert cs['grupo_previdenciario'].tolist() == ['11','11']

caso_2023 = pd.DataFrame([
    {'competencia':'2023-03','tipo_competencia':'mensal','cnpj_declarante':'A','nome_declarante_dirf':'COOMEB','grupo_previdenciario':'11','rendimento_tributavel':11208.01,'previdencia_oficial':0},
    {'competencia':'2023-03','tipo_competencia':'mensal','cnpj_declarante':'B','nome_declarante_dirf':'FGH','grupo_previdenciario':'20','rendimento_tributavel':0,'previdencia_oficial':877.22},
    {'competencia':'2023-03','tipo_competencia':'mensal','cnpj_declarante':'C','nome_declarante_dirf':'RHP','grupo_previdenciario':'progressiva','rendimento_tributavel':14716.62,'previdencia_oficial':877.22},
])
r23 = apurar_competencia(caso_2023, 7507.49)
assert r23['status'] == 'OK'
assert round(r23['contribuicao_maxima_11'],2) == 825.82
assert round(r23['contribuicao_maxima_20'],2) == 0.00
assert round(r23['contribuicao_maxima_progressiva'],2) == 0.00
assert round(r23['contribuicao_maxima_total'],2) == 825.82
print('OK — V1.2.15: identidade persistente e prioridade do grupo 11% validadas.')
