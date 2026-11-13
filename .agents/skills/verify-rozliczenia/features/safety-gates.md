# Safety gates

Safety gates prevent a settlement from guessing a worker, modifying the shared
Wzorzec rozliczenia pracownika, overwriting an existing output folder, or publishing partial files.

## Sub-features

- `safety-unknown` warns in dry-run and prevents publication for an unmapped source worker.
- `safety-worker-template` validates and copies the shared Wzorzec rozliczenia pracownika without modifying it.
- `safety-target-folder` rejects an existing output folder without changing it.
- `safety-lock` rejects a Wzorzec rozliczenia pracownika or a Plik zbiorczy with an Excel lock before creating output.
- `safety-rollback` removes staging files after a workbook processing failure.
- `safety-template-changed` stops in Zapisywanie, removes staging, and publishes nothing when the Wzorzec rozliczenia pracownika changes after Sprawdzanie: opened in Excel, deleted, or unreadable gives `BLAD_KOPII_WZORCA`; data in its Wiersze danych, merged cells in the Wiersze danych being written (both write routes, `template_file._ensure_unmerged`), or a header without `WYKONAWCA` in `H17` gives `BLAD_SZABLONU_PRACOWNIKA`.
- `safety-unreadable-source` stops on a damaged Plik zbiorczy with a safe Polish message and creates no output; a Plik zbiorczy the system will not hand over (no access, busy in another program, waiting for OneDrive) is `NIEDOSTEPNY_PLIK_ZBIORCZY`, never called damaged.
- `safety-worker-config` stops in Sprawdzanie on an unreadable, non-YAML, or invalid Lista Wykonawców and creates no output.

## How to get to it (user POV)

- Run a dry-run and a real settlement with an unknown `WYKONAWCA`.
- Create the output folder before a run and place a sentinel inside.
- Leave `~$Wzorzec rozliczenia pracownika.xlsx` beside the shared Wzorzec rozliczenia pracownika as Excel does while it is open.
- Inject a failure while processing the second synthetic workbook and retry.
- Open, delete, or change the Wzorzec rozliczenia pracownika after Sprawdzanie, before the first Szablon pracownika is written.
- Run against a Plik zbiorczy that is not a valid `.xlsx` (for example damaged), or one the user cannot read.
- Run with a `wykonawcy.yaml` that is not valid YAML or breaks a Lista Wykonawców rule.

## Driving it with PowerShell and the machine script

Preconditions:

- Use the orchestrator's isolated variant for each filesystem safety proof.
- The locked variant runs the doctor and dry-run before creating the Wzorzec rozliczenia pracownika lock.

- **Unknown worker.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant unmapped`. Dry-run warns with `BRAK_MAPOWANIA` naming `unknown.synthetic` and returns `2`; the real run stops with `NIEZNANY_WYKONAWCA` naming it too, returns `1`, and publishes no folder. The identifier may appear only in those two "Co się stało" texts, never elsewhere in the JSON.
- **Untouched Wzorzec rozliczenia pracownika.** Every Przebieg rozliczeń variant's assertion (`default`, `existing`, `locked`, `unmapped`, `chain`, `chain-real-templates`) fails unless the Wzorzec rozliczenia pracownika `sha256` matches the fixture manifest. The `preparation` variants have no Wzorzec rozliczenia pracownika.
- **Existing output folder.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing`; the sentinel `existing-synthetic.txt` remains the only file and `run.json` stops with `FOLDER_ROZLICZEN_ISTNIEJE`.
- **Excel lock.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant locked`; the run returns `1`, stops with `ZLY_WZORZEC_PRACOWNIKA` whose "Co się stało" says the Wzorzec is open or locked, and creates no output. A Plik zbiorczy open in Excel stops with `PLIK_ZBIORCZY_OTWARTY` and keeps its lock file. Both actions also tell Dad to delete the leftover `~$` file when Excel is closed and the message comes back (#493): `py -3 -m pytest tests/test_settlement_engine.py -k plik_zbiorczy_otwarty -q`.
- **Write failure.** Run `py -3 -m pytest tests/test_settlement_engine.py::test_failed_przetworzenie_szablonu_pracownika_emits_failure_without_false_completion -q`; it checks cleanup and successful retry.
- **Wzorzec changed after Sprawdzanie.** No variant drives it: the change has to land between Sprawdzanie and the first copy. Run `py -3 -m pytest tests/test_settlement_engine.py -k "otwarty_w_zapisywaniu or zepsuty_po_sprawdzaniu or blad_odczytu_wzorca" -q`; each case checks the code, that staging is gone, and that no folder is published.
- **Unreadable Plik zbiorczy.** Run `py -3 -m pytest tests/test_settlement_engine.py -k nieczytelny_plik_zbiorczy -q`; the run stops with `ZLY_PLIK_ZBIORCZY` in Odczyt danych with "Nie można odczytać Pliku zbiorczego …", no exception text and no output folder. The tests check the message, not the stage.
- **Plik zbiorczy without access.** No variant drives it. Create the default fixture with `create_fixture.py --root "$runRoot"`, remove read access to its Plik zbiorczy (`chmod 000` on macOS), run `py -3 tools\uruchom_proces.py settlement --source <fixture source> --wykonawcy <wykonawcy.yaml> --worker-template <wzorzec> --metrics <metrics>`, restore access, then run `cleanup.py --root "$runRoot"`. Expect exit `1`, stop `NIEDOSTEPNY_PLIK_ZBIORCZY` ("Nie można teraz odczytać Pliku zbiorczego …"), Sprawdzanie `completed`, Odczyt danych `failed`, and no output folder; `py -3 -m pytest tests/test_settlement_engine.py -k niedostepny_do_odczytu -q` covers it on every system.
- **Broken Lista Wykonawców.** No variant drives it. Create the default fixture with `create_fixture.py --root "$runRoot"`, overwrite `$runRoot\wykonawcy.yaml` with `schema_version: 1` and `wykonawcy: [unclosed`, run `py -3 tools\uruchom_proces.py settlement --source <fixture source> --wykonawcy <wykonawcy.yaml> --worker-template <wzorzec> --metrics <metrics>`, then run `cleanup.py --root "$runRoot"`. Expect exit `1` without JSON, the sentence `--wykonawcy: Plik wykonawcy.yaml w folderze config ma uszkodzoną treść. Zapisz Ustawienia jeszcze raz.` on stderr, and no `Rozliczenie pracowników` folder: the Skrypt dla maszyn reads the list with the rule of the Ustawienia Centrum owner before the process starts. `py -3 -m pytest tests/test_centrum_rozliczen.py -k lista_wykonawcow -q` covers the rules of the list.
- **Lista Wykonawców without access.** No variant drives it. Create the default fixture with `create_fixture.py --root "$runRoot"`, remove read access to `$runRoot\wykonawcy.yaml` (`chmod 000` on macOS), run the same `tools\uruchom_proces.py settlement` command, restore access, then run `cleanup.py --root "$runRoot"`. Expect exit `1` without JSON, `--wykonawcy: nie można teraz odczytać pliku wykonawcy.yaml` on stderr (never „niepoprawna”), and no `Rozliczenie pracowników` folder.
- **Evidence.** Each command retains its JSON result, exit code, metrics file, and read-only workbook assertions under its evidence directory. Do not log synthetic row values.

## Gotchas

- A missing mapping is a dry-run warning (`BRAK_MAPOWANIA`), but the real run stops with `NIEZNANY_WYKONAWCA` and does not publish an incomplete roster. A data row with an empty `WYKONAWCA` is the dry-run warning `BRAK_WYKONAWCY` and stops the real run the same way, with `WIERSZE_BEZ_WYKONAWCY`.
- A lock is represented by the exact `~$` filename; do not kill Excel or delete a user-owned lock as cleanup.
- Workbooks are always copied from the common Wzorzec rozliczenia pracownika, not reused from a previous period.
- Safety variants are independent fixtures; do not stack them unless the expected result is explicitly recalculated.
