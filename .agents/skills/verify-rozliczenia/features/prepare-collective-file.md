# Przygotowanie pliku zbiorczego

The second process, run before the settlement. From a Rejestr zleceń it creates the Rozliczenie wewnętrzne and the
Plik zbiorczy of one period inside the Folder okresu, both together or neither: every period order in the Rozliczenie
wewnętrzne, every Zlecenie skuteczne in `A:K` of the Plik zbiorczy with its Ilości usług in `N:AP`: in each column the
sum of what the Reguły ilości give and what the Legenda czynności gives for the Kody czynności in `CZYNNOŚCI
ZREALIZOWANE`, which also write the amount in `AS` and their fills. The `assert-*` steps check both files, their
Hiperłącza and external links, what the Kody czynności wrote (`activity_codes=N:AP,AS,fills`), the inputs and the
metrics; their messages stand in `assert_preparation.py`.

## Sub-features

Printed by `scripts/workflow_sub_features.py --feature prepare-collective-file` from the plan of each variant; refresh the section with it.

Variant `preparation`:

- `fixture`: `create_preparation_fixture.py --root <run-root>`, exit 0.
- `doctor`: `preparation_doctor.py --root <run-root>`, exit 0.
- `dry-run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --dry-run --metrics <run-root>/metrics.jsonl`, exit 0.
- `assert-dry-run`: `assert_preparation.py --root <run-root> --expect dry-run --templates synthetic --metrics <run-root>/metrics.jsonl --result <evidence>/dry-run.json`, exit 0.
- `run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --metrics <run-root>/metrics.jsonl`, exit 2.
- `assert-run`: `assert_preparation.py --root <run-root> --expect run --templates synthetic --metrics <run-root>/metrics.jsonl --result <evidence>/run.json`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

Variant `preparation-real-templates`:

- `fixture`: `create_preparation_fixture.py --root <run-root> --templates-from <templates>`, exit 0.
- `doctor`: `preparation_doctor.py --root <run-root>`, exit 0.
- `dry-run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --dry-run --metrics <run-root>/metrics.jsonl`, exit 0.
- `assert-dry-run`: `assert_preparation.py --root <run-root> --expect dry-run --templates config --metrics <run-root>/metrics.jsonl --result <evidence>/dry-run.json`, exit 0.
- `run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --metrics <run-root>/metrics.jsonl`, exit 2.
- `assert-run`: `assert_preparation.py --root <run-root> --expect run --templates config --metrics <run-root>/metrics.jsonl --result <evidence>/run.json`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

## How to get to it (user POV)

Dad starts it in Centrum rozliczeń, which takes the Rejestr and the folder okresów from Ustawienia Centrum and proposes
the period; `verify-centrum-rozliczen` drives that route. In Dad's layout the folder okresów is `Załączniki` and the
Folder okresu is found in `Rozliczenia {rok}\{miesiąc}\INEA`; the synthetic fixture uses the flat layout.

## Driving it with PowerShell and the machine script

Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation` from the repository
root (macOS: `.venv/bin/python`). The proof is in the evidence folder that `VERIFY OK` names: `dry-run.json`,
`run.json`, their `-metrics.jsonl` and `assert-*.txt`.
`--variant preparation-real-templates` runs the same plan on byte copies of the real Wzorce in `config/` (or `--templates-dir`), as `SKILL.md`, Launch, says.

## Gotchas

- The variant reaches no stop, no warning but the three Ilości usług warnings of its Rejestr, no Wzorzec with Dad's
  leftovers and not every line of Dad's instruction; prove them with `py -3 -m pytest
  tests/test_collective_preparation.py tests/test_collective_preparation_stops.py tests/test_wyglad_wiersza_danych.py
  tests/test_ilosci_uslug.py tests/test_ostrzezenia_ilosci.py -q`. `tests/test_instrukcja_taty.py` keeps Dad's
  "komunikat → co zrobić" table in step with the message catalog.
- The machine script counts with the Legenda czynności of the Wydanie, never with Dad's from Ustawienia:
  `tests/test_centrum_przygotowanie.py::test_przygotowanie_liczy_legenda_z_chwili_startu_a_zapis_dopisany_w_sekcji_w_trakcie_dziala_od_nastepnego`
  checks that Przygotowanie in Centrum counts with Dad's legend as it was at the start, and a spelling he adds during
  the run from the next one.
- Without `--dry-run`, an incomplete period (last order before the Monday) asks a Decyzja taty after the Planowanie
  stage. The machine script refuses every Decyzja taty, so such a run stops with exit `1` and writes nothing; keep a
  Monday order in the fixture.
- The period token uses the Monday's month and year (`27_02_11_2026`, `29_04_01_2027`), as in Dad's folders; the
  Tuesday-month form is rejected.
- An existing Folder okresu is allowed; an existing period file stops the run (Nienadpisywanie).
- The synthetic Wzorce do not reproduce every style layer of the real ones. Before #66 the code skipped the row style
  of the real Wzorzec rozliczenia wewnętrznego and wrote Calibri 11 instead of 10; `--variant preparation` passed, only
  `preparation-real-templates` failed. The real Wzorce still carry leftovers (wrap, top alignment, stored heights)
  that only that variant exercises.
