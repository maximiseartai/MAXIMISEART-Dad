# Przebieg rozliczeń

From the Plik zbiorczy of a period, Przebieg rozliczeń creates one Rozliczenie pracownika for every configured
Wykonawca from the shared Wzorzec rozliczenia pracownika, copies each Wiersz danych from row 18 into its Wykonawca's
workbook, leaves a Wykonawca with no rows an empty one, and publishes the Folder rozliczeń pracowników only after
every workbook is ready. The dry-run reads the same inputs and writes a metrics record, but no folder or workbook.
The variants `existing`, `locked` and `unmapped` prepare one Zatrzymanie dla taty each and expect the run to stop
with nothing published; the messages of the `assert-*` steps stand in `assert_results.py`.

## Sub-features

Printed by `scripts/workflow_sub_features.py --feature settlement` from the plan of each variant; refresh the section with it.

Variant `default`:

- `fixture`: `create_fixture.py --root <run-root>`, exit 0.
- `doctor`: `doctor.py --root <run-root>`, exit 0.
- `dry-run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --dry-run --metrics <run-root>/metrics.jsonl`, exit 0.
- `assert-dry-run`: `assert_results.py --root <run-root> --expect dry-run --result <evidence>/dry-run.json`, exit 0.
- `run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --metrics <run-root>/metrics.jsonl`, exit 0.
- `assert-run`: `assert_results.py --root <run-root> --expect run --result <evidence>/run.json`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

Variant `existing`:

- `fixture`: `create_fixture.py --root <run-root>`, exit 0.
- `doctor`: `doctor.py --root <run-root>`, exit 0.
- `dry-run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --dry-run --metrics <run-root>/metrics.jsonl`, exit 0.
- `assert-dry-run`: `assert_results.py --root <run-root> --expect dry-run --result <evidence>/dry-run.json`, exit 0.
- `existing-output`: makes the Folder rozliczeń pracowników with a file in it in the run root.
- `run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --metrics <run-root>/metrics.jsonl`, exit 1.
- `assert-run`: `assert_results.py --root <run-root> --expect existing-output --result <evidence>/run.json --expected-stop FOLDER_ROZLICZEN_ISTNIEJE`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

Variant `locked`:

- `fixture`: `create_fixture.py --root <run-root>`, exit 0.
- `doctor`: `doctor.py --root <run-root>`, exit 0.
- `dry-run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --dry-run --metrics <run-root>/metrics.jsonl`, exit 0.
- `assert-dry-run`: `assert_results.py --root <run-root> --expect dry-run --result <evidence>/dry-run.json`, exit 0.
- `lock`: makes the Excel lock of the Wzorzec rozliczenia pracownika in the run root.
- `run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --metrics <run-root>/metrics.jsonl`, exit 1.
- `assert-run`: `assert_results.py --root <run-root> --expect no-publish --result <evidence>/run.json --expected-stop ZLY_WZORZEC_PRACOWNIKA --expected-what "Wzorzec rozliczenia pracownika jest otwarty lub zablokowany"`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

Variant `unmapped`:

- `fixture`: `create_fixture.py --root <run-root> --include-unmapped`, exit 0.
- `doctor`: `doctor.py --root <run-root>`, exit 0.
- `dry-run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --dry-run --metrics <run-root>/metrics.jsonl`, exit 2.
- `assert-dry-run`: `assert_results.py --root <run-root> --expect dry-run --result <evidence>/dry-run.json`, exit 0.
- `run`: `tools/uruchom_proces.py settlement --source "<run-root>/08_14_09_2026/Rozliczenie 08_14_09_2026 - zbiorcze.xlsx" --wykonawcy <run-root>/wykonawcy.yaml --worker-template "<run-root>/Wzorzec rozliczenia pracownika.xlsx" --metrics <run-root>/metrics.jsonl`, exit 1.
- `assert-run`: `assert_results.py --root <run-root> --expect no-publish --result <evidence>/run.json --expected-stop NIEZNANY_WYKONAWCA --expected-what unknown.synthetic`, exit 0.
- `cleanup`: `cleanup.py --root <run-root>`, exit 0.
- `self-test`: `self_test.py --evidence-root <evidence> --run-dir <run-dir>`, exit 0.

## How to get to it (user POV)

Dad starts it in Centrum rozliczeń from the `Uruchomienia` page with the period picked from a list (or from Okresy:
`Podgląd bez zapisu` in `Następny krok`, or the period row's `Utwórz rozliczenia pracowników`); the Plik zbiorczy comes
from that Folder okresu. `verify-centrum-rozliczen` drives that route, Metryki included.

## Driving it with PowerShell and the machine script

Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant default existing locked unmapped`
from the repository root (macOS: `.venv/bin/python`). The proof is in the evidence folder each `VERIFY OK` names:
`dry-run.json`, `run.json`, their `-metrics.jsonl` and `assert-*.txt`.

## Gotchas

- The variants reach none of these; each has its test:
  - a Plik zbiorczy open in Excel stops with `PLIK_ZBIORCZY_OTWARTY` and keeps its lock file (`py -3 -m pytest
    tests/test_settlement_engine.py -k plik_zbiorczy_otwarty -q`);
  - a failed save stops with `BLAD_SZABLONU_PRACOWNIKA`, removes staging and a retry then writes the folder; any other
    exception leaves the engine as the same exception, staging removed
    (`tests/test_settlement_engine.py::test_failed_przetworzenie_szablonu_pracownika_emits_failure_without_false_completion`,
    cases `blad-zapisu`, `nieoczekiwany-blad` and `nieoczekiwany-blad-wyszukiwania`), and Centrum shows it as the
    catalog's unexpected error for whoever maintains the tool, without the exception's text and without any file
    (`tests/test_centrum_przebieg.py::test_nieoczekiwany_wyjatek_pokazuje_komunikat_z_katalogu_bez_tekstu_wyjatku`);
  - a Wzorzec open in Excel, broken (no workbook, no `WYKONAWCA` in `H17`, data in its rows) or unreadable from disk
    after Sprawdzanie stops without publishing (`-k "otwarty_w_zapisywaniu or zepsuty_po_sprawdzaniu or
    blad_odczytu_wzorca"`);
  - a damaged or unavailable Plik zbiorczy stops in Odczyt danych after a completed Sprawdzanie, or already in
    Sprawdzanie when its folder gives no access (`-k "nieczytelny_plik_zbiorczy or niedostepny_do_odczytu"`);
  - a Wiersz danych without `WYKONAWCA` (`-k wiersz_danych_bez_wykonawcy`);
  - `WYKONAWCA` identifiers are compared without letter case, extra spaces and non-breaking spaces, so the stop and the
    preview name each unknown one once, in the spelling of its first row
    (`-k test_zatrzymanie_i_podglad_nazywaja_kazdego_nieznanego_wykonawce_raz`);
  - the rules of the Lista Wykonawców (`tests/test_centrum_rozliczen.py -k lista_wykonawcow`;
    `tests/test_uruchom_proces.py::test_zla_lista_wykonawcow_konczy_skrypt_kodem_1_ze_zdaniem_wlasciciela_ustawien_bez_uruchomienia`
    for a list against a rule given to the machine script);
  - every external link of a Rozliczenie pracownika written by openpyxl and by the copy
    (`tests/test_workbook_files.py::test_plik_z_wzorca_przez_openpyxl_ma_wiersze_danych_formuly_formatowanie_i_kazdy_link_zewnetrzny`,
    `::test_rozliczenie_pracownika_z_wzorca_zachowuje_wspolne_formuly_calcchain_i_flagi_przeliczania`);
  - the counters of a metrics record and a duration for each stage in it
    (`tests/test_uruchomienie_procesow.py::test_rekord_metryk_ma_liczniki_procesu_i_drogi_zapisu_bez_sciezek_i_danych_klientow`),
    and a metrics record that cannot be saved, which leaves the result as it is with a warning
    (`tests/test_uruchom_proces.py::test_nieudany_zapis_metryk_jest_ostrzezeniem_bez_zmiany_wyniku`).

  The Wyróżnienia of the Plik zbiorczy reach a Rozliczenie pracownika only in `--variant chain`
  (`prepare-and-settle.md`): the default fixture has none.
- An unparseable Lista Wykonawców is not reached either. By hand: create the default fixture with `create_fixture.py
  --root "$runRoot"`, overwrite `$runRoot\wykonawcy.yaml` with `schema_version: 1` and `wykonawcy: [unclosed`, run the
  `settlement` command of the `run` step above, then `cleanup.py --root "$runRoot"`. Expect exit `1` without JSON,
  `--wykonawcy: Plik wykonawcy.yaml w folderze config ma uszkodzoną treść. Poprawia go Maks.` on stderr and no
  `Rozliczenie pracowników` folder. An unreadable list gives `--wykonawcy: nie można teraz odczytać pliku
  wykonawcy.yaml`, never „niepoprawna”.
- The source file must be named `Rozliczenie {okres} - zbiorcze.xlsx` and live in a folder named after the same period
  token; a token that is not a Tuesday–Monday period (e.g. `09_15_09_2026`) stops with `ZLY_PLIK_ZBIORCZY` and creates
  no folder
  (`tests/test_settlement_engine.py::test_plik_zbiorczy_z_tokenem_ktory_nie_jest_okresem_zatrzymuje_przebieg_rozliczen`).
- A lock is the exact `~$` filename beside the file; do not kill Excel or delete a user's lock as cleanup.
