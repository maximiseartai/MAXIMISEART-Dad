# From Rejestr zleceń to Rozliczenia pracowników

Dad's whole weekly path, both processes in turn. Przygotowanie pliku zbiorczego
turns the Rejestr zleceń into the Rozliczenie wewnętrzne and the Plik zbiorczy;
Dad then fills quantities, charges, and remarks into the Plik zbiorczy by hand
and declares Gotowość by starting Przebieg rozliczeń on that file, which creates
the Folder rozliczeń pracowników. The separate variants each start from their
own synthetic input; only this one hands the output of one process to the other.

## Sub-features

- `chain-handover` runs `settlement --source` on the Plik zbiorczy that `preparation` wrote, without any other change than the Gotowość entries.
- `chain-readiness` fills `N:AP` with non-zero quantities and `AQ:AT` with a charge description, charge, remark amount, and remark in three Wiersze danych; every other cell, formula, and `xl/externalLinks/*` part of the Plik zbiorczy stays as Przygotowanie wrote it.
- `chain-routing` gives every Wykonawca exactly their Zlecenia skuteczne in Plik zbiorczy order from row 18; Adrian's two are split by Kamil's in the Plik zbiorczy.
- `chain-columns` makes `A:AT` of every Wiersz danych in a Rozliczenie pracownika equal to its Plik zbiorczy row, Gotowość entries included, except the Ilości tylko dla INEA (ADR 0018): `AP` of a row whose `URZĄDZENIA` contain `gniazdo` and `AK` of one whose `URZĄDZENIA` contain `technicolor`, in any case, are empty, while the Plik zbiorczy holds a value there. The emptied cell keeps its Wyróżnienia. That it also drops a Hiperłącze is unverified here, because the synthetic cells have none; `tests/test_ilosci_tylko_dla_inea.py` checks it. `assert_chain.py` derives these cells from `URZĄDZENIA` with its own `INEA_ONLY` table, not the product's, and fails when the Plik zbiorczy has no row for one of the two columns or no value in such a cell, so the exception cannot pass vacuously.
- `chain-highlights` gives every `A:AT` cell of those rows the Wyróżnienia (fill, font color, bold, italic) of its Plik zbiorczy cell; a cell absent from the Plik zbiorczy counts as without Wyróżnienia. The check fails when the Plik zbiorczy has no filled cell, so it cannot pass vacuously.
- `chain-row-look` gives `A:L` of those rows the number format of the Plik zbiorczy cell and the Wygląd Wiersza danych: font face and size of the Wzorzec's header cell, left and centre alignment, wrapping only for text with a line break, a thin automatic border, and no stored row height.
- `chain-hyperlinks` carries the Hiperłącze of every Rejestr `NUMER ZL.` cell through the Plik zbiorczy into each Rozliczenie pracownika: the `A:AT` hyperlinks of every Wiersz danych equal its Plik zbiorczy row, whose `NUMER ZL.` holds the Rejestr address, and hyperlinks outside the Wiersze danych stay from the Wzorzec rozliczenia pracownika.
- `chain-unsuccessful` keeps the Zlecenie nieskuteczne in the Rozliczenie wewnętrzne only, out of the Plik zbiorczy and every Rozliczenie pracownika.
- `chain-preserve` leaves the sheet names and every stored value and hyperlink of the Wzorzec rozliczenia pracownika outside the Wiersze danych unchanged in each Rozliczenie pracownika, with byte-identical external links; the synthetic Wzorzec has a `Stawki` sheet with values beyond the active one, and the check fails without it.
- `chain-safety` leaves the Rejestr zleceń and all three Wzorce byte-identical, and the Przebieg rozliczeń leaves the Rozliczenie wewnętrzne and the Plik zbiorczy byte-identical.
- `chain-metrics` appends one `DRY-RUN` and one `RUN` record to the history of each process; each `RUN` counts every file it wrote as a copy of its Wzorzec in `routes`, none by `openpyxl` (ADR 0008).
- `chain-real-templates` (local only) runs the same path on byte copies of the three real Wzorce from `config/`.

## How to get to it (user POV)

- Dad runs Przygotowanie pliku zbiorczego in Centrum rozliczeń, fills the Plik zbiorczy in Excel, saves and closes it, then runs Przebieg rozliczeń for the same period in Centrum.
- Verification passes every input explicitly: first `py -3 tools\uruchom_proces.py preparation --register <rejestr> --periods-directory <folder okresów> --period 08_14_09_2026 --wykonawcy <wykonawcy.yaml> --internal-template <wzorzec> --collective-template <wzorzec> --metrics <metrics> [--dry-run]`, then `py -3 tools\uruchom_proces.py settlement --source <Folder okresu>\Rozliczenie 08_14_09_2026 - zbiorcze.xlsx --wykonawcy <wykonawcy.yaml> --worker-template <wzorzec> --metrics <metrics> [--dry-run]`.

## Driving it with PowerShell and the machine script

Preconditions:

- The orchestrator builds the `preparation` fixture plus a synthetic Wzorzec rozliczenia pracownika in Dad's shape from `tools/lib/atrapy/wzorce.py` (`GODZINA` in A17, its own rate, an external link, a `Stawki` sheet beyond the active one), and the same three-worker mapping, under a fresh run root.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant chain`. It runs the fixture, the doctor with `--with-worker-template`, the Przygotowanie dry-run and write with `assert_preparation.py`, `fill_readiness.py`, the Przebieg dry-run and write with `assert_chain.py`, cleanup, and the self-test. Success prints `VERIFY OK | variant=chain`; `--variant all` includes it, so the CI E2E job runs it.
- **Read the counts.** The Przygotowanie counts match `preparation`. The `worker_settlements` of the Przebieg dry-run have 2 orders each for Adrian Testowy, Darek Fikcyjny, and Kamil Syntetyczny, with `Problemy` 0 and no `warnings`; the write reports `Zapisane szablony` 3, `Puste szablony` 0, and progress of 3 of 3 Szablony pracowników after the four stages in order. Gotowość fills Adrian's two rows and Darek's `PREP-SYN-ZL-6`; Darek's `gniazdo` order `PREP-SYN-ZL-8` and Kamil's two rows, one of them the `Technicolor 3*globo` order `PREP-SYN-ZL-9`, keep the Ilości usług Przygotowanie wrote over the Wzorzec's zeros in `N:AP` and an empty `AQ:AT`. So `AP` of Darek's second row and `AK` of Kamil's second row are the two Ilości tylko dla INEA.
- **Read the workbook proof.** `readiness.txt` has a `READINESS OK | … rows_filled=3 | columns=N:AT` line; the `ASSERT OK` line in `assert-settlement-run.txt` contains `rows_equal_plik_zbiorczy=A:AT | inea_only_empty=2 | highlights_equal_plik_zbiorczy=A:AT | number_formats_equal_plik_zbiorczy=A:L | row_look=A:L | hyperlinks_equal_plik_zbiorczy=A:AT | hyperlinks_from_rejestr=NUMER ZL. | readiness_carried=true | unsuccessful_absent=true | wzorzec_preserved=true | external_links_preserved=true | inputs_unchanged=true`. Every step's evidence holds its exit code. A failure names the worker, row, and columns, never a value.
- **Check the real Wzorce.** When `config/` holds all three Wzorce, run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant chain-real-templates`; a worktree whose own `config/` holds no Wzorzec reads the main checkout's, and `--templates-dir` overrides that. Without them it prints `VERIFY SKIP`. It takes under a minute; the real Wzorce have about 10 000 rows each.

## Gotchas

- Before this variant the synthetic Plik zbiorczy of `default` had empty `O:AT`, so cutting the copy into a Szablon pracownika down to `A:N` still passed (found at #76). The Gotowość entries make `chain` fail with the columns named; keep them non-zero in every column of `N:AT`.
- The Gotowość step saves with `save_workbook` (`workbook_files.py`), the openpyxl save that copies `xl/externalLinks/*` byte for byte, as the processes' openpyxl fallback does, then checks every other cell and every `xl/externalLinks/*` part itself. Excel keeps an external link only while a formula uses it, as in Dad's Wzorce; it drops the unused link of this variant's synthetic Wzorce on save. `verify-skoroszyty-w-excelu` covers Gotowość saved by the real Excel.
- Przebieg rozliczeń copies `A:AT` by position, not by header, so the check compares positions; the real Wzorzec rozliczenia pracownika has `GODZINA` where the Wzorzec pliku zbiorczego has `MIASTO`.
- The two processes keep separate metrics histories with different counters; never point both at one metrics file.
