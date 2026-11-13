# Workbook preparation

One settlement run creates the complete configured worker roster from the
shared Wzorzec rozliczenia pracownika, fills current-period rows, and publishes the output folder
only after every workbook is ready.

## Sub-features

- `prepare-roster` creates one named workbook for every configured worker.
- `prepare-copy` preserves Wzorzec rozliczenia pracownika sheets, formulas, rates, formatting, and external links (the live fixture has no external link; `tests/test_workbook_files.py::test_plik_z_wzorca_przez_openpyxl_ma_wiersze_danych_formuly_formatowanie_i_kazdy_link_zewnetrzny` proves that part for a Rozliczenie pracownika written by openpyxl, and `test_rozliczenie_pracownika_z_wzorca_zachowuje_wspolne_formuly_calcchain_i_flagi_przeliczania` for one written by the copy).
- `prepare-empty` creates an empty workbook for a configured worker without source rows.
- `prepare-atomic` stages the folder and publishes it only after all workbooks succeed.
- `prepare-rollback` removes staging files after a workbook failure, including a Wzorzec rozliczenia pracownika that changed after Sprawdzanie (`BLAD_KOPII_WZORCA`, `BLAD_SZABLONU_PRACOWNIKA`, see `safety-gates.md`) and a failed save (`OSError`, `WorkbookSaveError`: `BLAD_SZABLONU_PRACOWNIKA`); any other exception is an unexpected stop „do Maksa”; an unknown worker or a Wiersz danych without `WYKONAWCA` blocks a real run during planning, before staging starts.

## How to get to it (user POV)

- Dad starts it in Centrum rozliczeń from the `Uruchomienia` page with the period picked from a list (or from Okresy: `Podgląd bez zapisu` in `Następny krok`, or the period row's `Utwórz rozliczenia pracowników`); the Plik zbiorczy comes from that Folder okresu. `verify-centrum-rozliczen` drives that route.
- Outside Centrum, run `py -3 tools\uruchom_proces.py settlement --source <source> --wykonawcy <wykonawcy.yaml> --worker-template <worker-template> --metrics <metrics>` with a synthetic fixture.

## Driving it with PowerShell and the machine script

- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py` for the proof.
- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant unmapped` to prove an unknown WYKONAWCA prevents publication.
- Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py --variant existing` to prove an existing output folder is preserved.
- Run the write-failure test listed in `safety-gates.md` to prove staging cleanup and retry.

## Gotchas

- The output folder must be absent at start; existing content is never merged or replaced.
- The shared Wzorzec rozliczenia pracownika is read-only input, validated in Sprawdzanie and read again when the first Szablon pracownika is written.
- Temporary workbooks are not published under the final folder name until every configured worker is prepared.
- Dry-run plans the same roster but creates no output folder or workbook.
