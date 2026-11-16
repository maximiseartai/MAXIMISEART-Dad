# Rozliczenia pracowników w Excelu

After Przebieg rozliczeń ran on the Plik zbiorczy Dad saved in Excel, he opens
each Rozliczenie pracownika in the Folder rozliczeń pracowników. Each opens with
no dialog, links to the same Słownik as the Wzorzec rozliczenia pracownika, and
shows exactly its Wykonawca's Zlecenia skuteczne with what he typed, the
Wzorzec's formulas calculating the amounts, and the Rejestr's Wyróżnienia, with the
Czerwone pole empty and the Zielone pole holding 1, both white (ADR 0039).

## Sub-features

- `bez-okna`: each of the three Rozliczenia pracowników opens in Excel with no dialog.
- `lacze`: Excel lists the same external workbook for each Rozliczenie pracownika as for the Wzorzec rozliczenia pracownika.
- `wiersze-a-at`: the Wiersze danych are the Wykonawca's Zlecenia skuteczne in Plik zbiorczy order, and each row's `A:AT` in Excel equals that row of the Plik zbiorczy after Gotowość, except the Ilości tylko dla INEA (ADR 0018): `AP` of the `gniazdo` order `PREP-SYN-ZL-8` (Darek Fikcyjny) and `AK` of the `Technicolor 3*globo` order `PREP-SYN-ZL-9` (Kamil Syntetyczny) are empty, while the Plik zbiorczy holds a value there (`inea_only_empty=1` in each of their files), and the Czerwone pole and Zielone pole of `PREP-SYN-ZL-8` (`WORKER_COLOURED_FIELDS`): `AM` and `AS` are empty and `AF` holds 1, while the Plik zbiorczy holds 1 in `AM`, 70 in `AS` and nothing in `AF` (`coloured_fields=3` in Darek Fikcyjny's file, 0 in the others).
- `hiperlacza`: each Wiersz danych has in the file Przebieg wrote the `A:AT` Hiperłącza of its row in the Plik zbiorczy Excel saved.
- `formuly`: every Wiersz danych has the R1C1 formulas of `AU18:AY18` of the Wzorzec rozliczenia pracownika, `AU:AX` shows no error, and the rows Dad filled show a positive amount in `AU`.
- `wyroznienia`: each file shows the Plik zbiorczy's Wyróżnienia of its own orders: Adrian Testowy the yellow ADRES with bold dark red text of `PREP-SYN-ZL-2` and the plain ADRES of `-7` (`cells=2`), Kamil Syntetyczny the blue ADRES and italic WYKONAWCA of `-4` (`cells=2`), Darek Fikcyjny the plain ADRES of `-6` (`cells=1`).
- `czerwone-i-zielone-pole`: Darek Fikcyjny's row of `PREP-SYN-ZL-8` shows `AS`, `AM` and `AF` white, the interior colour Excel shows for a cell without a fill, where the Plik zbiorczy has a red `AS` and `AM` and a green `AF` (`cells=3`); the other files have no order with Kody czynności (`cells=0`).
- `wyglad-wiersza`: rows with one line are the sheet's standard height and Adrian Testowy's two-line `PREP-SYN-ZL-2` is taller; DATA shows the same text as in the Plik zbiorczy (its number format, not the Wzorzec's).

## How to get to it (user POV)

- Centrum rozliczeń, Tablica okresów, the period with Status okresu `Rozliczenia pracowników gotowe`: the `Rozliczenia pracowników` button (its tooltip gives the file count, e.g. `Rozliczenia pracowników: 3`) opens the Folder rozliczeń pracowników, then a double click on a file.
- Finder: `INEA\<okres>\Rozliczenie pracowników <okres>\Rozliczenie <okres> - <Wykonawca>.xlsx`.

## Driving it with AppleScript

Preconditions: `gotowosc-w-excelu` passed and Przebieg rozliczeń ended `OK` with `Zapisane szablony` 3 (`przebieg.json`).

- **Open.** For Adrian Testowy, Darek Fikcyjny, Kamil Syntetyczny: copy the file to the desk, `excel.open_file`. `STEP … bez-okna | <Wykonawca> | open_seconds=…`.
- **Link.** `excel.link_names` equals the Wzorzec rozliczenia pracownika's list. `STEP … lacze | <Wykonawca> | links=1`.
- **Rows.** `NUMER ZL.` in rows 18–60 gives exactly `-2, -7` (Adrian), `-6, -8` (Darek), `-4, -9` (Kamil). Each row's `excel.read("A:AT")` equals the remembered Plik zbiorczy row cell by cell, except the `INEA_ONLY` cell, which is empty here and not empty there, and the `COLOURED_FIELDS` cells, which hold their value from `WORKER_COLOURED_FIELDS`; a difference names the columns.
- **Hiperłącza.** openpyxl reads `A:AT` hyperlinks of each row in the Folder okresu's file; they equal those `gotowosc-w-excelu` read from Excel's save.
- **Formulas.** As in `otwarcie-plikow-okresu`, against the worker Wzorzec's reference; `AU` above zero in the filled rows.
- **Wyróżnienia.** `excel.fill` as in `otwarcie-plikow-okresu`, for the cells whose order is in this file.
- **Czerwone pole i Zielone pole.** `excel.fill` of each `COLOURED_FIELDS` cell of the orders in this file shows interior colour `0xFFFFFF`. `STEP … czerwone-i-zielone-pole | <Wykonawca> | cells=…`.
- **Wygląd Wiersza danych.** Heights as in `otwarcie-plikow-okresu`; `excel.shown_text` of DATA equals the Plik zbiorczy's. `STEP … wyglad-wiersza | <Wykonawca> | one_line_pt=… | data_as_plik_zbiorczy=true`.
- **Close.** `excel.close` in `finally`, also after a failed check.

## Gotchas

- Dad's Wzorzec rozliczenia pracownika has its own rates in row 14, so its amounts differ from the Plik zbiorczy's (the `syntetyczne` Wzorce share one row 14); only their presence and the formulas are compared.
- Kamil's rows and Darek's `-8` were not typed in Excel: their `N:AT` must still equal the Plik zbiorczy's (the Ilości usług Przygotowanie wrote in `N:AP` and in `AQ:AT` what the Wzorzec holds) apart from the Ilości tylko dla INEA and the Czerwone pole and Zielone pole, which `wiersze-a-at` covers.
- `wiersze-a-at` compares Excel's reading of both files, so a date shows the same in both; a difference there is a real change of the cell, not of rendering.
