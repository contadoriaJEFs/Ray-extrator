from motor_previdenciario import verificar_tabela, tabela_por_competencia
from dirf_core import extract_pdf, validate_records
from pathlib import Path

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
