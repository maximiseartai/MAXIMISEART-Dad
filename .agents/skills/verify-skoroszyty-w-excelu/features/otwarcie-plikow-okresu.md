# Otwarcie plików okresu

After Przygotowanie pliku zbiorczego, Dad opens the Rozliczenie wewnętrzne and
the Plik zbiorczy from the Folder okresu in Excel. Both open straight to the
sheet, with no repair question. The Plik zbiorczy links to the same Słownik as
its Wzorzec, every Wiersz danych has the Wzorzec's formulas with no error in
its amounts and the Ilości usług from the Reguły ilości and the Legenda
czynności, the Kody czynności show their amount in `AS` and their fills, the
Rejestr's Wyróżnienia show as they were, and Excel fits each row to its text.

## Sub-features

- `rozliczenie-wewnetrzne-bez-okna`: the Rozliczenie wewnętrzne opens in Excel with no dialog.
- `plik-zbiorczy-bez-okna`: the Plik zbiorczy opens in Excel with no dialog.
- `plik-zbiorczy-lacze`: Excel lists the same external workbook for the Plik zbiorczy as for the Wzorzec pliku zbiorczego.
- `plik-zbiorczy-formuly`: every Wiersz danych has the R1C1 formulas of `AU18:AY18` of the Wzorzec, and `AU:AX` shows no error.
- `plik-zbiorczy-ilosci`: Excel holds the Ilości usług Przygotowanie wrote from the Reguły ilości and the Legenda czynności in `N:AP` of the six Zlecenia skuteczne (none for `prewencja`; for the component the Reguły ilości do not know, only V, T and the 45 of a late usterka in N; `AB` and `AM` from the Kody czynności `spawpg rt2` of `PREP-SYN-ZL-8`), and the sums of row 15 of the Wzorzec count them.
- `plik-zbiorczy-wyroznienia`: as in the Rejestr, ADRES of `PREP-SYN-ZL-2` is yellow with bold dark red text, ADRES of `PREP-SYN-ZL-4` blue, ADRES of `PREP-SYN-ZL-7` and `PREP-SYN-ZL-6` without fill, and WYKONAWCA of `PREP-SYN-ZL-4` italic.
- `plik-zbiorczy-kody-czynnosci`: the row of `PREP-SYN-ZL-8`, whose CZYNNOŚCI ZREALIZOWANE are the Kody czynności `spawpg rt2`, shows 70 in `AS`, a red `AS` and `AM` and a green `AF` without a value (Legenda czynności z Wydania, ADR 0038).
- `plik-zbiorczy-wyglad-wiersza`: Excel auto-fits the Wiersze danych (Wygląd Wiersza danych, no stored height): every row with one line is exactly the sheet's standard height, and the row of `PREP-SYN-ZL-2`, whose CZYNNOŚCI ZREALIZOWANE has two lines, is taller.

## How to get to it (user POV)

- Centrum rozliczeń, Tablica okresów: the period's file links open the Rozliczenie wewnętrzne and the Plik zbiorczy in Excel.
- Finder: double click in `INEA\<okres>\` of the folder okresów.

## Driving it with AppleScript

Preconditions: the Baseline in `README.md`; both Wzorce were opened as the reference (step 4 of Drive).

- **Rozliczenie wewnętrzne.** Copy it to the desk; `excel.open_file` returns within the 180 s limit; `excel.close` removes `~$`. `STEP … rozliczenie-wewnetrzne-bez-okna | open_seconds=…`.
- **Plik zbiorczy.** Copy it to the desk and open it; it stays open for `gotowosc-w-excelu`.
- **Link.** `excel.link_names` equals the Wzorzec pliku zbiorczego's list (`links=1`).
- **Rows and formulas.** Headers of row 17 give `NUMER ZL.`, `ADRES`, `WYKONAWCA`, `DATA`, each exactly once; `NUMER ZL.` in rows 18–60 must include the six Zlecenia skuteczne, and every row found is checked (`rows=6`). For each, `excel.formulas_r1c1("AU:AY")` equals the reference and `excel.error_cells("AU:AX")` is none.
- **Ilości usług.** `excel.read` of `N:AP` of each order's row gives exactly `QUANTITIES` of `run_excel_verification.py` as non-zero numbers, and `N15:AP15` their column sums (`cells=29 | sums_row=15`).
- **Wyróżnienia.** `excel.fill` gives interior, font color, bold, italic: ADRES `(0xFFFF00, 0xC00000, True, False)` (`-2`), `(0x00B0F0, 0x000000, False, False)` (`-4`), `(0xFFFFFF, 0x000000, False, False)` (`-7`, `-6`), and WYKONAWCA `(0xFFFFFF, 0x000000, False, True)` (`-4`) (`cells=5`).
- **Kody czynności.** `excel.read` of `AS` of the row of each order in `CODE_CELLS` of `run_excel_verification.py` gives its amount, and `excel.fill` its interior colour in each filled column: `AS` and `AM` `0xFF0000`, `AF` `0x92D050` (`cells=4`).
- **Wygląd Wiersza danych.** `excel.row_heights` of each order's row against `excel.standard_height`; `excel.shown_text` of DATA is remembered for `rozliczenia-pracownikow-w-excelu`. `STEP … plik-zbiorczy-wyglad-wiersza | rows=6 | one_line_pt=…`.

## Gotchas

- `AY` looks up the Słownik through the external link and shows `#N/D` without the Słownik on this Mac; only `AU:AX` must be free of errors.
- A Wzorzec whose external link no formula uses proves nothing: Excel drops such a link on save. The doctor rejects that fixture; the old synthetic Wzorce of `verify-rozliczenia` have exactly that.
- Dad's real Wzorce had wrapping in rows 18–31: before the Wygląd Wiersza danych (2026-10-22) Excel showed those rows 30 pt high instead of 14–15 pt. `string value` gives the text in the cell's number format but not the `#####` of a too narrow column, so the DATA check compares the number format's text, not the rendering.
- A repair dialog surfaces here as `ExcelDialog … not open` with `Excel dialogs: [...]`; `features/okno-naprawy.md` shows what it looks like.
