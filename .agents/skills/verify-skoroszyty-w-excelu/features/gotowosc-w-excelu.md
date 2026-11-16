# Gotowość w Excelu

Dad fills the Plik zbiorczy in Excel: quantities in `N:AP`, the customer charge
and its description, a remark amount and the remarks in `AQ:AT`. Excel
calculates the amounts as he types. He saves and closes the file, which leaves
no `~$` lock, and the link to the Słownik and the Hiperłącze of each order
number are still in the file Excel wrote.

## Sub-features

- `wpisy`: typed `N:AT` in the rows of `PREP-SYN-ZL-2`, `-7` and `-6` holds exactly the typed numbers and texts, and `AU` of each shows a positive amount Excel calculated.
- `zapis-i-zamkniecie`: Excel saves (`saved` is true) and closes the Plik zbiorczy, and its `~$` lock is gone.
- `lacze-po-zapisie`: the saved file differs from Przygotowanie's, was last written by `Microsoft Macintosh Excel` (`docProps/app.xml`) and still has `xl/externalLinks/externalLink*.xml`.
- `hiperlacza-po-zapisie`: every Wiersz danych keeps in Excel's saved bytes the `A:AT` Hiperłącza Przygotowanie wrote, and `NUMER ZL.` of each has one.

## How to get to it (user POV)

- Excel, the Plik zbiorczy of the period opened from Centrum rozliczeń (Tablica okresów, `Plik zbiorczy`) or Finder: type into `N:AT`, Cmd+S, close the window. Before Przebieg rozliczeń, Centrum reminds him under the run's settings and in its `Uruchomić z zapisem?` question: `Zapisz i zamknij Plik zbiorczy w Excelu`; `Uruchom` confirms the Gotowość.

## Driving it with AppleScript

Preconditions: the Plik zbiorczy is open on the desk from `otwarcie-plikow-okresu`.

- **Type.** For row `i` of `PREP-SYN-ZL-2`, `-7`, `-6`: `excel.type_row(path, "N<r>:AT<r>", texts)` with `10·(i+1)+k` in the 29 quantity columns (`k` = 1 for N … 29 for AP), `PREP-SYN-OBC-<n>`, `25.5+i`, `10+i`, `PREP-SYN-UWAGI-<n>` in `AQ:AT`. `excel.read("N<r>:AT<r>")` matches each text (numbers as numbers), and `AU<r>` is a number above zero.
- **Remember.** `excel.read("A<r>:AT<r>")` of all six rows is what each Rozliczenie pracownika must show later, apart from the Ilości tylko dla INEA.
- **Save and close.** `excel.save`, then `excel.close`, which waits for `~$` to disappear.
- **Inspect the bytes.** The desk copy differs from the Folder okresu's, `docProps/app.xml` names `Microsoft Macintosh Excel`, the zip has an external link part. Copy it back into the Folder okresu; `excel.json` records its SHA-256.
- **Hiperłącza.** openpyxl reads `A:AT` hyperlinks of the six rows from Przygotowanie's file before typing and from Excel's saved copy after; they are equal (`rows=6 | column=F`). openpyxl, not Excel and not the tool's own reader, so the check depends on neither.

## Gotchas

- `excel.save` is `tell wb to save`; `save wb` from AppleScript reports nothing and saves nothing.
- Each entry recalculates every formula of the workbook (some 50 000 in Dad's Wzorce). `type_row` enters a whole row in one call; typed cell by cell, the synthetic Wzorce's first row ran past the 60 s call limit.
- Numbers are entered through `formula` with a decimal point (`25.5`), Excel's English input, so the system locale does not change them. Dad types `25,5`; that parsing is his locale's and is not covered here.
- Excel rewrites the external link part on save (its size changes); compare its presence, not its bytes.
- Before Excel's save, `NUMER ZL.` without a Hiperłącze fails the step, so an empty fixture cannot make the comparison pass.
