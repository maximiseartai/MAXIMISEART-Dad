# Worker settlement

Worker settlement creates one workbook per configured worker from the shared
Wzorzec rozliczenia pracownika, copies every Wiersz danych (from row 18, a value in `A:K`) into its worker's
workbook, and leaves a worker with no rows empty.

## Sub-features

- `settle-map` maps each `WYKONAWCA` identifier, compared without case, extra spaces, or non-breaking spaces, to its configured worker name, which names the workbook.
- `settle-copy` writes source values into `A:AT` starting at row 18, except the Ilości tylko dla INEA, which it leaves empty (ADR 0018, `inea_only_quantities.py`; `prepare-and-settle.md` checks them).
- `settle-highlights` gives every written `A:AT` cell the Wyróżnienia of its Plik zbiorczy cell (fill, font color, bold, italic). `A:L` get the Wygląd Wiersza danych: font face and size of the Wzorzec's header cell, left and centre alignment, wrapping only for text with a line break, thin borders, the number format of the Plik zbiorczy cell and no stored row height; in `M:AT` font face and size, number format, borders, alignment, and protection stay from the Wzorzec rozliczenia pracownika. A source cell without Wyróżnienia clears them, as Przygotowanie does from the Rejestr.
- `settle-hyperlinks` gives every written `A:AT` cell the Hiperłącze of its Plik zbiorczy cell (an external address, e.g. the order in the company app behind `NUMER ZL.`); a Wzorzec hyperlink in a written Wiersz danych is replaced or cleared, and the address never reaches the JSON result, metrics or evidence.
- `settle-preserve` keeps the template `AU` formulas and structure.
- `settle-empty` leaves a mapped worker with no rows an empty Rozliczenie pracownika (`empty: true` in `worker_settlements` of the JSON result).
- `settle-roster` creates exactly one workbook for every configured worker.

## How to get to it (user POV)

- Dad starts it in Centrum rozliczeń from the `Uruchomienia` page with the period picked from a list; the Plik zbiorczy comes from that Folder okresu. `verify-centrum-rozliczen` drives that route.
- Outside Centrum, run `py -3 tools\uruchom_proces.py settlement --source <source> --wykonawcy <wykonawcy.yaml> --worker-template <worker-template> --metrics <metrics>` with a synthetic fixture.

## Driving it with PowerShell and the machine script

Preconditions:

- Run the one-command orchestrator.
- Its default fixture contains mapped rows for Adrian Testowy and Darek Fikcyjny and no rows for Kamil Syntetyczny. The output folder is absent before the run.

- **Run the proof.** Run `py -3 .agents\skills\verify-rozliczenia\scripts\run_verification.py`. The dry-run and write both return `0` for the default fixture.
- **Observe progress.** `assert-run.txt` reports `progress_reported=true`: in `run.json` the progress has `templates_completed` 3 of `template_total` 3 with `Zapisane szablony` 2 and `Puste szablony` 1, and the summary has `Zapisane szablony` 2, `Puste szablony` 1, and the `worker_settlements` of all three workers.
- **Verify workbook state.** Read `assert-run.txt`; it returns `ASSERT OK` with exit code `0` after checking exactly three files, routed values, the Hiperłącze of every `NUMER ZL.` cell (`hyperlinks_equal_plik_zbiorczy=F`), preserved formulas/sheets/formatting, an empty Kamil workbook, and an untouched Wzorzec rozliczenia pracownika.

## Gotchas

- The source file must be named `Rozliczenie {okres} - zbiorcze.xlsx` and live in a folder named after the same period token; the fixture uses `08_14_09_2026`. A token that is not a Tuesday–Monday period (e.g. `09_15_09_2026`) stops with `ZLY_PLIK_ZBIORCZY`.
- The configured shared Wzorzec rozliczenia pracownika is copied into each new workbook and is
  never modified. The final output folder appears only after all files are ready.
- The proof must inspect formulas with `data_only=False`; cached formula results are not the template-preservation proof.
- The default fixture's Plik zbiorczy carries a Hiperłącze in `F` of every Wiersz danych (`caseId=SYNTHETIC-LINK`); `self_test.py` rejects that marker in the evidence, so an address leaking into the JSON result or metrics fails the proof. The `chain` variants carry the Rejestr's Hiperłącza through Przygotowanie pliku zbiorczego (`chain-hyperlinks`).
- The default fixture's Plik zbiorczy has no Wyróżnienia, so `settle-highlights` is proven by `chain` (`highlights_equal_plik_zbiorczy=A:AT`), whose Plik zbiorczy carries the Rejestr's highlighted cells and the Wzorzec pliku zbiorczego's fills. When comparing looks with openpyxl, take the set of cells in the file right after loading: `iter_rows` on a full workbook adds the missing cells, which then show the default font instead of no Wyróżnienia.
- An unmapped WYKONAWCA stops the real run before creating the output folder;
  verify that path with `--variant unmapped` under the safety-gates feature.
