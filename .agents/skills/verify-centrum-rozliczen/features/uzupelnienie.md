# Uzupełnienie pliku zbiorczego

After Przygotowanie pliku zbiorczego, Dad types the Ilości do uzupełnienia in
Excel. Three entries lead to the period's summary: the card `Następny krok` on
Okresy and the Tablica okresów row offer `Uzupełnij` for a period with Plik
zbiorczy przygotowany, and the written Plik zbiorczy's result card shows the
same summary with `Uzupełnij`. Droga okresu has `Uzupełnienie w Excelu` as its
current step. The summary is at
`#/uzupelnienie/<token>`: a counter „x z y” and the row numbers for `Wiersze bez
reguły` and `Wiersze z opisu` (done rows crossed out, a kind with no rows or
all rows done ticked, never red), how many rows hold a value in each column
from the technician's description, `Otwórz Plik zbiorczy` when the Plik
zbiorczy is in the Folder okresu, and `Gotowe, rozlicz
pracowników`, which opens Przebieg rozliczeń with the period chosen; its
dialog `Uruchomić z zapisem?` lists the rows still without quantity. Centrum reads
the saved Plik zbiorczy on every read, also while Excel holds it, and never
changes it. Each kind with rows opens its own page at
`#/uzupelnienie/<token>/<kind>`: a read-only table like Excel with only that
kind's rows, the row number and WYKONAWCA, URZĄDZENIA, CZYNNOŚCI and CZYNNOŚCI
ZREALIZOWANE pinned on the left, all 29 columns N:AP scrolling sideways under
their letter and price-list name, the tool's values grey, a row to fill yellow,
and Dad's value green in a green row. A Plik zbiorczy it cannot read is a calm
three-part Komunikat. The summary and the kind pages are live (#419): while
visible they ask every 3 s for the saved version
(`GET /api/periods/<token>/collective-file-version`, `stat` only) and read the
view again only when it changed; a failed read keeps the last good state with
its time for about a minute, then the Komunikat. After Przebieg rozliczeń
(Status okresu `Rozliczenia pracowników gotowe`) both pages are a preview:
`Przebieg rozliczeń się odbył · tylko podgląd`, no `Gotowe` and no hint about
saving in Excel, and a row Dad left empty is grey with the words „bez ilości”
on screen, not yellow.

## Sub-features

Printed by `scripts/sub_features.py --feature uzupelnienie` from the drive's steps and checks; refresh the section with it.

- `uzupelnienie-wynik`: …: the server read the Plik zbiorczy; right after Przygotowanie the server lists rows 18 and 20 without rule and row 19 from the description; …: counters, row numbers with their done state, and column counters match the server.
- `uzupelnienie-wynik-bez-starej-kopii`: harness: the summary's version checks answer the version from before, so its copy stays the one read before; harness: one value typed into column Y of row 18 while the summary is open; …: the server read the Plik zbiorczy; …: counters, row numbers with their done state, and column counters match the server; back on the result card the summary waits for its read instead of the summary page's older copy; Uzupełnij on the result card opens the same summary, and Wstecz returns to the result.
- `uzupelnienie-wynik-na-zywo`: harness: Dad's values typed into column Y of rows 18 and 20 and saved; the card shows 2 z 2 without a click, focus, tab switch or reload, after … check(s) of the saved version; …: the server read the Plik zbiorczy; …: counters, row numbers with their done state, and column counters match the server; the card has the summary page's hint about saving in Excel; with the tab hidden for … ms the card asks nothing about the Plik zbiorczy (…); back in the tab the card checks the saved version again; with the file back as it was the card goes back to 0 z 2 by itself.
- `uzupelnienie-wynik-po-przebiegu`: harness: the Folder rozliczeń pracowników a Przebieg rozliczeń creates exists, removed after this step; …: the server read the Plik zbiorczy; after Przebieg the server's answer is settled; …: counters, row numbers with their done state, and column counters match the server; after Przebieg the result card has no hint about saving in Excel; without the Folder rozliczeń pracowników the hint is back on the card.
- `uzupelnienie-wynik-bez-odpowiedzi`: harness: the card's reads of the Plik zbiorczy get no answer from the server; without an answer the result card says it could not read the Plik zbiorczy, never blank; once the server answers again the card shows the summary by itself.
- `uzupelnienie-wynik-bez-centrum`: harness: neither the version checks nor the reads of the Plik zbiorczy get an answer; a version check without an answer reads the file, so the card shows the failure, not old data; once Centrum answers again the card shows the summary by itself.
- `uzupelnienie-wynik-po-starcie`: …: the server read the Plik zbiorczy; …: counters, row numbers with their done state, and column counters match the server.
- `uzupelnienie-tablica`: exactly the rows with Status okresu Plik zbiorczy przygotowany (…) offer Uzupełnij; …: the server read the Plik zbiorczy; …: counters, row numbers with their done state, and column counters match the server.
- `uzupelnienie-droga`: Droga okresu has four steps, with Wycena w efenix before Rozliczenia pracowników, and shows Uzupełnienie w Excelu as the current step after Plik zbiorczy.
- `uzupelnienie-karta`: Następny krok offers Uzupełnij for the last complete period with Plik zbiorczy przygotowany, with Wyceń w efenix next to it.
- `uzupelnienie-podsumowanie`: …: the server read the Plik zbiorczy; the server lists rows 18 and 20 without rule and row 19 from the description, none done yet; …: counters, row numbers with their done state, and column counters match the server.
- `uzupelnienie-wpis-taty`: harness: one value typed into column Y of row …, saved and closed; the counter changed to 1 z 2 without a click or reload, after … check(s) of the saved version; …: the server read the Plik zbiorczy; row … is done and only column Y counts one more row; two more checks of the unchanged saved version read nothing again; …: counters, row numbers with their done state, and column counters match the server.
- `uzupelnienie-tabela-bez-reguly`: …: the server lists only this kind's rows, ascending; …: the answer carries the row texts and no address, order number or UMOWA; …: the server names the row texts by their Plik zbiorczy headers; …: every column N:AP carries its price-list name from row 17 of the Plik zbiorczy; …: row numbers, row states and every N:AP cell on screen equal the server's answer; …: a tap on a column header or on CZYNNOŚCI ZREALIZOWANE shows the full text; …: at … px with the menu open … columns N:AP fit next to the pinned texts; …: the row number stays in place while the quantity columns scroll sideways; Dad's value in Y18 comes back green with his value and makes row 18 done; row 20 stays to fill.
- `uzupelnienie-tabela-z-opisu`: …: the server lists only this kind's rows, ascending; …: the answer carries the row texts and no address, order number or UMOWA; …: the server names the row texts by their Plik zbiorczy headers; …: every column N:AP carries its price-list name from row 17 of the Plik zbiorczy; …: row numbers, row states and every N:AP cell on screen equal the server's answer; …: a tap on a column header or on CZYNNOŚCI ZREALIZOWANE shows the full text; …: at … px with the menu open … columns N:AP fit next to the pinned texts; …: the row number stays in place while the quantity columns scroll sideways.
- `uzupelnienie-tabela-na-zywo`: harness typed 1 into Y…: the row turns done with Dad's green value without a click or reload; harness deleted Y… again: the row is to fill again by itself.
- `uzupelnienie-blokada-excela`: …: the server read the Plik zbiorczy; with Excel's lock file next to the Plik zbiorczy the server reads its last saved version unchanged; …: counters, row numbers with their done state, and column counters match the server.
- `uzupelnienie-odczyt-nieudany`: …: the server read the Plik zbiorczy; a Plik zbiorczy Centrum cannot read keeps the last good state, marked as retried; …: counters, row numbers with their done state, and column counters match the server; once the file reads again the time disappears, without a click.
- `uzupelnienie-otworz`: one click on „Otwórz Plik zbiorczy” opens the period's Plik zbiorczy, once.
- `uzupelnienie-powrot`: the link Okresy leads back, and Wstecz returns to the summary of the same period.
- `uzupelnienie-gotowe`: harness: Dad closed Excel, so no lock file keeps Uruchom disabled; …: the server read the Plik zbiorczy; Gotowe chose Przebieg rozliczeń and …; without it the form shows the first process; the period's rows without quantity are 19 and 20, the summary's rows not done.
- `uzupelnienie-gotowe-potwierdzenie`: the confirm dialog lists the rows without quantity, and Dad may still start.
- `uzupelnienie-gotowe-po-podgladzie`: after the preview, the result card's Uruchom dialog lists the same rows, Dad's usual path.
- `uzupelnienie-gotowe-bez-odczytu`: harness: the Plik zbiorczy of … is damaged for this step and restored after it; Gotowe chose Przebieg rozliczeń and …; without it the form shows the first process; Gotowe on the summary of … selects it, not the preselected …, and its rows without quantity answer although its Plik zbiorczy cannot be read; the dialog says the rows could not be checked instead of staying silent, and Dad may start.
- `uzupelnienie-po-przebiegu`: harness: the Folder rozliczeń pracowników a Przebieg rozliczeń creates exists, removed after this step; …: the server read the Plik zbiorczy; after Przebieg the summary says so, Dad's row 18 stays done and rows 19 and 20 are without quantity; …: counters, row numbers with their done state, and column counters match the server; rows 19 and 20 read „bez ilości” on the screen next to their number, not only for a screen reader; after Przebieg the summary is a preview: no Gotowe, no hint about saving, Otwórz Plik zbiorczy stays; row 20 is no longer yellow (… before Przebieg) but grey (…), and not green like row 18; row 20 reads „bez ilości” on the screen under its number.
- `uzupelnienie-bez-pliku`: a period without a Plik zbiorczy shows the server's three-part Komunikat, calm and not as a failure; Otwórz Plik zbiorczy is there only when the Plik zbiorczy is in the Folder okresu (on_disk=…); the kind page of the same period follows the same rule; the failed read is in the Centrum log with the period.
- `uzupelnienie-gotowe-bez-okresu`: Gotowe of 15_21_09_2026, which Przebieg rozliczeń does not offer, says aloud which period it chose.

## How to get to it (user POV)

- Okresy → card `Następny krok` → `Uzupełnij` (when the last complete period has Plik zbiorczy przygotowany).
- Okresy → Tablica okresów → `Uzupełnij` in the row of any period with Plik zbiorczy przygotowany.
- Uruchomienia → result of Przygotowanie pliku zbiorczego z zapisem → `Uzupełnij`.
- The address `#/uzupelnienie/<token>` directly, also after a reload or Wstecz.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature uzupelnienie`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/uzupelnienie-*.json`.

The run does not wait a minute for the Komunikat after a failed read:
`tests/test_centrum_uzupelnienie_na_zywo.py::test_nieudany_odczyt_przez_minute_pokazuje_ostatni_dobry_stan_potem_komunikat`
checks that a read failing for a minute shows the last good state, then the Komunikat. The steps after Przebieg stand in
the Folder rozliczeń pracowników for a real Przebieg rozliczeń:
`tests/test_centrum_uzupelnienie.py::test_po_przebiegu_rozliczen_wiersze_bez_wpisu_taty_sa_bez_ilosci_na_kazdej_stronie`
runs one and checks that the rows without Dad's entry are „bez ilości” on every page.

## Gotchas

- `Uzupełnij` has role `button`, not `link`: it is a Base UI `Button` rendered as `<a>`, like the bell.
- Headless Chromium reports the tab as visible, so the page keeps asking for the saved version during the whole drive; a step that counts requests counts only its own.
- The rows without quantity are the listed kinds' rows not done (bez reguły and z opisu), never a row the Reguły ilości cover; an unreadable Plik zbiorczy makes them `unread`. The dialog reads them for its period when the card shows it, never the setup, because one read takes Dad's laptop over a second.
- The preview in `uzupelnienie-gotowe-po-podgladzie` adds one DRY-RUN of Przebieg rozliczeń to the week before `przebieg-rozliczen`; that feature counts its records from its own start.
- Delete the lock file in `finally`; a leftover `~$…` keeps `Uruchom` of Przebieg rozliczeń off, with the start card naming the Plik zbiorczy as open in Excel (`przebieg-plik-zbiorczy-otwarty-w-excelu` of `przebieg-rozliczen`).
- Remove the harness's `Rozliczenie pracowników 06_12_10_2026` in `finally`: a leftover folder closes the period, and `przebieg-rozliczen` would stop with Nienadpisywanie instead of settling it.
