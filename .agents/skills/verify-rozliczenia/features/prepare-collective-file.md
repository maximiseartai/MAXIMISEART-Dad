# Przygotowanie pliku zbiorczego

The second process, run before the settlement. From a Rejestr zleceń it creates
the Rozliczenie wewnętrzne and the Plik zbiorczy of one period inside the Folder
okresu, both together or neither. Dad starts it in Centrum rozliczeń; outside
Centrum it runs as `tools/uruchom_proces.py preparation`.

## Sub-features

- `preparation-plan` dry-run reports order counts, skipped empty rows, orders per day, and both file names in `summary` and its warnings in `warnings`, and records the period in its metrics; it creates neither file nor the Folder okresu.
- `preparation-internal` writes every period order (successful or not) in Rejestr order to the Rozliczenie wewnętrzne, with `zwrot`/`UWAGI` empty; the Rejestr columns AKCJE, ZWROT and UWAGI reach neither period file.
- `preparation-collective` writes every Zlecenie skuteczne to `A:K` from row 18 of the Plik zbiorczy, leaving rates, sums, formulas, and sheets from the Wzorzec.
- `preparation-quantities` writes the non-zero Ilości usług from the Reguły ilości (ADR 0012) into `N:AP` of every Zlecenie skuteczne, in the Wzorzec cell's look; every other `N:AP` cell keeps the Wzorzec value (its zeros) and the Rozliczenie wewnętrzne gets none. The fixture covers a router with TV devices and printing (`u` in UMOWA), `gateway wifi6extra` with a Saturday usterka (AI and N = 45), `prewencja` (no quantities) and a Monday-evening usterka with an unknown component (only V, T and N = 45).
- `preparation-formatting` carries fill, font colour, bold, italic, and number format (dates included) from the Rejestr; widths and frozen header from the Wzorzec; the Wygląd Wiersza danych in `A:M` of the Rozliczenie wewnętrzne and `A:L` of the Plik zbiorczy (font face/size of the header cell, left and centre alignment, wrapping only for text with a line break, thin borders, no stored row height; `zwrot`/`UWAGI` too, though empty); every written ADRES has the fill of that order's ADRES in the Rejestr, in both files (yellow, blue, or none); autofilter covers header plus data rows.
- `preparation-hyperlinks` gives every written cell the Hiperłącze of its Rejestr cell (the order in the company app behind `NUMER ZL.`) in both period files; a written cell without one keeps no Wzorzec hyperlink, and the address never reaches the JSON result, metrics or evidence.
- `preparation-links` keeps every `xl/externalLinks/*` part of the Wzorzec pliku zbiorczego byte-identical.
- `preparation-safety` leaves the Rejestr and both Wzorce byte-identical and leaves no staging directory.
- `preparation-real-templates` (local only) runs the same Rejestr into copies of the real Wzorce from `config/`: data font equals the header font, Wzorzec cells outside the written rows are unchanged, Wzorce and external links are byte-identical.
- `preparation-metrics` appends to its own history with counters `period_orders`, `successful_orders`, `skipped_empty_rows`, `warnings`, and `routes` with the Rozliczenie wewnętrzne and the Plik zbiorczy each by `kopia` or `openpyxl` (`openpyxl` when the copy refuses the Wzorzec, ADR 0008) (`preparation_files.write_period_files`); `assert_preparation.py` requires both by `kopia`, for the synthetic and the real Wzorce.

## How to get to it (user POV)

- Dad starts it in Centrum rozliczeń, which takes the Rejestr and the folder okresów from Ustawienia Centrum and proposes the period; `verify-centrum-rozliczen` drives that route. In Dad's layout the folder okresów is `Załączniki` and the Folder okresu is found in `Rozliczenia {rok}\{miesiąc}\INEA`; the synthetic fixture uses the flat layout.
- The machine script never reads the Rejestr or the folder okresów from Ustawienia Centrum and requires the Rejestr, the folder okresów, and the period: `py -3 tools\uruchom_proces.py preparation --register <rejestr> --periods-directory <folder okresów> --period 08_14_09_2026 --wykonawcy <wykonawcy.yaml> --internal-template <wzorzec> --collective-template <wzorzec> --metrics <metrics> [--dry-run]`.

## Driving it with PowerShell and the machine script

Preconditions:

- The orchestrator builds the synthetic Rejestr in the layout of Dad's new Rejestr (empty column A, AKCJE in B, headers `ADRES`, `NUMER ZL.`, `NUMER UMOWY`, ZWROT and UWAGI at the end; decoy `lista` sheet, hidden `ARCHIWUM` sheet with an older order, empty export rows, orders outside the period, a late Monday order, highlights including a yellow and a blue ADRES, a Hiperłącze in `NUMER ZL.` of every order, every order row styled as already ordered so the Surowe zlecenia check does not stop it), both Wzorce (the Wzorzec pliku zbiorczego with an external link and an unprefixed `xl/workbook.xml` like Dad's, which `assert_preparation.py` requires), and a three-worker mapping under a fresh run root.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation`. It runs `create_preparation_fixture.py`, `preparation_doctor.py`, the dry-run, `assert_preparation.py --expect dry-run`, the real run, `assert_preparation.py --expect run`, cleanup, and the self-test. Success prints `VERIFY OK | variant=preparation`.
- **Read the counts.** The fixture yields 7 period orders, 6 Zlecenia skuteczne, 4 skipped empty rows (every fully empty row from the first to the last period order, including the one before the next-period order), orders on Tue (2), Wed, Sat, Sun, and Mon (2), and 3 warnings. Rows 18..23 of the Plik zbiorczy hold the Ilości usług of orders 2, 4, 7, 6, 8 (`gniazdo`) and 9 (`Technicolor 3*globo`) (`QUANTITIES` in `tools/lib/atrapy/scenariusz_rozliczen.py`), and rows 24 and 25 keep the Wzorzec's zeros. Adrian's Sunday order sits after the next-period order, so his two Zlecenia skuteczne are split by Kamil's in the Plik zbiorczy. Both JSON results carry this `summary`, `Ostrzeżenia` 3, and the same Ilości usług `warnings` with Plik zbiorczy rows: `NIEZNANE_URZADZENIA` (`wiersz 21`), `WIERSZE_Z_OPISU` (`wiersz 20`) and the reminder `KOLUMNY_Z_OPISU` (`EXPECTED_WARNINGS`). The dry-run exits `0` with `OK`; the write exits `2` with `WYMAGA_SPRAWDZENIA`, because Dad completes the written Plik zbiorczy.
- **Read the workbook proof.** `assert-run.txt` confirms both period files, routed values, formatting, the Rejestr Hiperłącze of every written `NUMER ZL.` cell (`hyperlinks_from_rejestr=NUMER ZL.`), the Rejestr fill of every written ADRES (`address_fill_from_rejestr=ADRES`), autofilters, preserved Wzorzec content, byte-identical external links, unchanged inputs, and two metrics records (`DRY-RUN`, `RUN`).
- **Check the real Wzorce.** When `config/` holds both Wzorce, run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant preparation-real-templates`; a worktree whose own `config/` holds no Wzorzec reads the main checkout's, and `--templates-dir` overrides that. Without both Wzorce it prints `VERIFY SKIP`, which is a skip. Counts, summary and Ilości usług match `preparation`; the `ASSERT OK` line in `assert-run.txt` contains `templates=config` and `address_fill_from_rejestr=ADRES`. A failure names the column and both fonts, never a cell value.
- **Drive stops, warnings, the Wygląd Wiersza danych on Wzorzec leftovers, and Dad's instruction.** The variant fixture reaches none of these; prove them with `py -3 -m pytest tests/test_collective_preparation.py tests/test_collective_preparation_stops.py tests/test_wyglad_wiersza_danych.py tests/test_ilosci_uslug.py -q`. They cover every stop and warning, including:
  - Wzorzec checks (missing, open in Excel, damaged, wrong header, WYKONAWCA outside H17 in the Wzorzec pliku zbiorczego) in Sprawdzanie, before the Rejestr's orders are read, also in `--dry-run`;
  - Surowe zlecenia in the period (`SUROWE_ZLECENIA_W_OKRESIE`, #471): Sprawdzanie reads the Rejestr with the INTERMAX reader and stops, also in `--dry-run`, while pasted orders at the bottom of the order sheet are not yet ordered; a Rejestr that reader cannot parse is a Rejestr-unusable stop there (`collective_preparation.py`, `preparation_register.raw_orders_in_period`); the Odczyt danych reads the same bytes of the Rejestr, read once in Sprawdzanie;
  - merged Wzorzec cells in the rows orders will fill, which stop the run in Planowanie;
  - the "too few zero rows" warning, which still writes both files;
  - the Wygląd Wiersza danych over Wzorce with Dad's leftovers (other font face, wrapping, top alignment, no border, stored row height) in all three written files (`tests/test_wyglad_wiersza_danych.py`);
  - every line of Dad's instruction, the 45 zł usterka surcharge around 17:00 and on Saturday, piece counts from `CZYNNOŚCI` for instalacja ręczna and wizja, new combinations, spelling variants, rows settled from the description and unknown components (`tests/test_ilosci_uslug.py`).

  `tests/test_instrukcja_taty.py` keeps Dad's "komunikat → co zrobić" table in step with the message catalog.

## Gotchas

- Without `--dry-run`, an incomplete period (last order before the Monday) asks a Decyzja taty after the Planowanie stage. The machine script refuses every Decyzja taty, so such a run stops with exit `1` and writes nothing; keep a Monday order in the fixture.
- The period token uses the Monday's month and year (`27_02_11_2026`, `29_04_01_2027`), as in Dad's folders; the Tuesday-month form is rejected.
- An existing Folder okresu is allowed; an existing period file stops the run (Nienadpisywanie).
- Without `--config`, `--internal-template`, or `--collective-template` the script takes the files Centrum uses from `config/`; the orchestrator passes the fixture's files, so no run reads `config/`.
- The JSON result carries no row content; the `PREP-SYN-` markers in the fixture, the Hiperłącze addresses included (`caseId=PREP-SYN-LINK`), exist so the assertions and the self-test can catch a leak.
- The synthetic Wzorce do not reproduce every style layer of the real ones. Before #66 the code skipped the row style of the real Wzorzec rozliczenia wewnętrznego and wrote Calibri 11 instead of 10; `--variant preparation` passed, only `preparation-real-templates` failed. Run it after any change to how template styles are applied. Since the Wygląd Wiersza danych (2026-10-22) the Wzorzec's data-cell, row and column styles no longer reach `A:M`/`A:L`, but the real Wzorce still carry leftovers (wrap, top alignment, stored heights) that only that variant exercises.
