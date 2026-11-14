# From Rejestr zleceń to Rozliczenia pracowników

Dad's whole weekly path, both processes in turn. Przygotowanie pliku zbiorczego turns the Rejestr zleceń into the
Rozliczenie wewnętrzne and the Plik zbiorczy; Dad then fills quantities, charges, and remarks into the Plik zbiorczy by
hand and declares Gotowość by starting Przebieg rozliczeń on that file, which creates the Folder rozliczeń
pracowników. The `readiness` step plays Dad's hand (`fill_readiness.py`), and only this feature hands the output of
one process to the other. The `assert-settlement-*` steps check each Rozliczenie pracownika against the Plik zbiorczy
it read; their messages stand in `assert_chain.py`.

## Sub-features

Printed by `scripts/workflow_sub_features.py --feature prepare-and-settle` from the plan of each variant; refresh the section with it.

Variant `chain`:

- `fixture`: `create_preparation_fixture.py --root <run-root> --with-worker-template`, exit 0.
- `doctor`: `preparation_doctor.py --root <run-root> --with-worker-template`, exit 0.
- `preparation-dry-run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --dry-run --metrics <run-root>/preparation-metrics.jsonl`, exit 0.
- `assert-preparation-dry-run`: `assert_preparation.py --root <run-root> --expect dry-run --templates synthetic --metrics <run-root>/preparation-metrics.jsonl --result <evidence>/preparation-dry-run.json`, exit 0.
- `preparation-run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --metrics <run-root>/preparation-metrics.jsonl`, exit 2.
- `assert-preparation-run`: `assert_preparation.py --root <run-root> --expect run --templates synthetic --metrics <run-root>/preparation-metrics.jsonl --result <evidence>/preparation-run.json`, exit 0.
- `readiness`: `fill_readiness.py --root <run-root>`, exit 0.
- `settlement-dry-run`: `tools/uruchom_proces.py settlement --source "<run-root>/INEA/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/config/wykonawcy.yaml --worker-template "<run-root>/config/Wzorzec rozliczenia pracownika.xlsx" --dry-run --metrics <run-root>/settlement-metrics.jsonl`, exit 0.
- `assert-settlement-dry-run`: `assert_chain.py --root <run-root> --expect dry-run --result <evidence>/settlement-dry-run.json`, exit 0.
- `settlement-run`: `tools/uruchom_proces.py settlement --source "<run-root>/INEA/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/config/wykonawcy.yaml --worker-template "<run-root>/config/Wzorzec rozliczenia pracownika.xlsx" --metrics <run-root>/settlement-metrics.jsonl`, exit 0.
- `assert-settlement-run`: `assert_chain.py --root <run-root> --expect run --result <evidence>/settlement-run.json`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

Variant `chain-real-templates`:

- `fixture`: `create_preparation_fixture.py --root <run-root> --with-worker-template --templates-from <templates>`, exit 0.
- `doctor`: `preparation_doctor.py --root <run-root> --with-worker-template`, exit 0.
- `preparation-dry-run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --dry-run --metrics <run-root>/preparation-metrics.jsonl`, exit 0.
- `assert-preparation-dry-run`: `assert_preparation.py --root <run-root> --expect dry-run --templates config --metrics <run-root>/preparation-metrics.jsonl --result <evidence>/preparation-dry-run.json`, exit 0.
- `preparation-run`: `tools/uruchom_proces.py preparation --register "<run-root>/ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory <run-root>/INEA --period 08_14_09_2026 --wykonawcy <run-root>/config/wykonawcy.yaml --internal-template "<run-root>/config/Wzorzec rozliczenia wewnętrznego.xlsx" --collective-template "<run-root>/config/Wzorzec pliku zbiorczego.xlsx" --metrics <run-root>/preparation-metrics.jsonl`, exit 2.
- `assert-preparation-run`: `assert_preparation.py --root <run-root> --expect run --templates config --metrics <run-root>/preparation-metrics.jsonl --result <evidence>/preparation-run.json`, exit 0.
- `readiness`: `fill_readiness.py --root <run-root>`, exit 0.
- `settlement-dry-run`: `tools/uruchom_proces.py settlement --source "<run-root>/INEA/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/config/wykonawcy.yaml --worker-template "<run-root>/config/Wzorzec rozliczenia pracownika.xlsx" --dry-run --metrics <run-root>/settlement-metrics.jsonl`, exit 0.
- `assert-settlement-dry-run`: `assert_chain.py --root <run-root> --expect dry-run --result <evidence>/settlement-dry-run.json`, exit 0.
- `settlement-run`: `tools/uruchom_proces.py settlement --source "<run-root>/INEA/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/config/wykonawcy.yaml --worker-template "<run-root>/config/Wzorzec rozliczenia pracownika.xlsx" --metrics <run-root>/settlement-metrics.jsonl`, exit 0.
- `assert-settlement-run`: `assert_chain.py --root <run-root> --expect run --result <evidence>/settlement-run.json`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

## How to get to it (user POV)

Dad runs Przygotowanie pliku zbiorczego in Centrum rozliczeń, fills the Plik zbiorczy in Excel, saves and closes it,
then runs Przebieg rozliczeń for the same period in Centrum.

## Driving it with PowerShell and the machine script

Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant chain` from the repository root
(macOS: `.venv/bin/python`). The proof is in the evidence folder that `VERIFY OK` names: `readiness.txt`, the
`preparation-*` and `settlement-*` `.json` and `-metrics.jsonl`, and `assert-*.txt`. `--variant chain-real-templates`
runs the same plan on byte copies of the three real Wzorce in `config/` (or `--templates-dir`), only locally; it takes
under a minute, as the real Wzorce have about 10 000 rows each, and without them it prints `VERIFY SKIP`, which is a
skip.

## Gotchas

- Before this variant the synthetic Plik zbiorczy of `default` had empty `O:AT`, so cutting the copy into a Szablon
  pracownika down to `A:N` still passed (found at #76). The Gotowość entries make `chain` fail with the columns named;
  keep them non-zero in every column of `N:AT`.
- That emptying an Ilość tylko dla INEA also drops its Hiperłącze is not reached here, because the synthetic cells
  have none; `tests/test_ilosci_tylko_dla_inea.py` checks it.
- The `readiness` step saves with `save_workbook` (`workbook_files.py`), the openpyxl save the processes fall back to.
  Excel keeps an external link only while a formula uses it, as in Dad's Wzorce, and drops the unused link of this
  variant's synthetic Wzorce on save; `verify-skoroszyty-w-excelu` covers Gotowość saved by the real Excel.
- Przebieg rozliczeń copies `A:AT` by position, not by header: the real Wzorzec rozliczenia pracownika has `GODZINA`
  where the Wzorzec pliku zbiorczego has `MIASTO`.
- The two processes keep separate metrics histories with different counters; never point both at one metrics file.
