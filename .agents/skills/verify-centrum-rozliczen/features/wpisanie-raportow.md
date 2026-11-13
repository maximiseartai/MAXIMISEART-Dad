# Wpisanie raportów

Dad clicks `Wpisz raporty z maili`, the one main button in the header of Raporty, and `tak`/`nie` and the activities
from the Raporty wykonawców go into empty cells of INTERMAX (ADR 0028). Uruchomienia have no card of it (Maks's decision
of 11.11.2026, #1321), but they still show the Uruchomienie live and its result with `Otwórz Raporty`. Raporty set
INTERMAX (in one quiet line, with `Ustaw w Ustawieniach` while it is not set), turn the button off at a blocker from the server, and
read the view again by themselves when the Wpisanie ends. The button is off while any Uruchomienie procesu runs. The
view Raporty is the result of the last click, read from its file and not from the mailbox: the server gives the whole
window of the click (each day with its holiday, each Wykonawca with his days and the orders of each day as INTERMAX has
them after the click, #1322), and the page shows it as a Mapa cieplna (#1323): a row per Wykonawca in alphabetical
order, a column per day of the range from the address (by default Monday of last week to Sunday of this week, clipped
to the days of the window), a tile `wpisane/zlecenia` in the colour of the day's state (Komplet, Bez raportu,
Problem; Czeka, for yesterday or today without a mail, shows a clock instead of the figures), holidays as a yellow
column with `Św.`, a Sunday without orders struck through,
and a ring of the entered orders of the range. A tile opens a popover with the day's figures and orders, with each
problem's sentence and `Zostaw moją`. The range changes with the arrows and a calendar, the Status filter keeps the
Wykonawcy with a day of the chosen states and dims the other tiles, and the Raporty from addresses outside the list
stand under the table. At a difference with Dad's own value, `Zostaw moją` keeps his value: the difference is gone at
once and does not come back at the next click.

## Sub-features

- `bez-karty-w-uruchomieniach`: the setup of Uruchomienia has region `Uporządkuj INTERMAX` and no region or button `Wpisz raporty z maili`.
- `przycisk`: with the folder okresów set and the Rejestr zleceń pointed in Foldery of Ustawienia, over Raporty, to the fixture's INTERMAX of `wpisanie-raportow`, the header has the enabled button `Wpisz raporty z maili`, group `INTERMAX` names the file, no alert stands under the header; `GET /api/report-entering` has no `blocker` and no `open_in_excel`.
- `w-czasie-innego`: harness: the Uruchomienia stream shows a Uporządkowanie INTERMAX that runs; the button `Wpisz raporty z maili` is off with no alert under the header, and on again once the stream shows no Uruchomienie running.
- `widok-przed-kliknieciem`: the page `Raporty` is on today 19.10.2026 (`today` of `GET /api/report-entering/view`, and the day in its `days` without a holiday); before any click it says `Jeszcze nie ma Raportów` and `Kliknij „Wpisz raporty z maili” powyżej.`.
- `blokada`: harness: Excel's lock file next to INTERMAX; at Dad's return to the window the button is off and an alert under the header says INTERMAX `jest otwarty w Excelu` with the lock file's name (`open_in_excel`); without the lock file the button is on again and the alert is gone.
- `klikniecie`: the header button writes the Raporty of `wykonawca.a` and `wykonawca.b`: the result figures `Wpisane 2`, `Problemy 2`, `Raporty 2`, INTERMAX changed on disk; without a reload the tiles of both Wykonawcy show the click and the button is on again; Uruchomienia show the result, and `Otwórz Raporty` in region `Podgląd na żywo` opens the view.
- `widok`: group `Zakres dni` shows `19 paź` and table `Mapa Raportów` has that one day; the tile of `wykonawca.a` is `Bez raportu, wpisane 1 z 2` (he sent a mail, so today is not `Czeka`) and of `wykonawca.b` `Problem, wpisane 1 z 1`, each ring `Wpisane <wpisane> z <zlecenia>` as in the API answer; the popover of `wykonawca.a` has `Zlecenia 2`, `Wpisane 1`, `Maile 1` and list `Zlecenia dnia` with `40000101` `tak` `wymiana routera` and `40000102` `Brak Wpisu w raporcie` `Bez raportu`; the popover of `wykonawca.b` has Dad's `montaż ręcznie` and the button `Zostaw moją`; region `Spoza listy adresów` shows `obcy@przyklad.invalid`, which no file of Logi has; the API answer has the same figures, `days` is only 19.10 without a holiday, and `orders_detail` of each Wykonawca has his orders in the INTERMAX order with `SKUTECZNE`, `CZYNNOŚCI ZREALIZOWANE` and state as after the click (`40000101` `tak` `wymiana routera` entered, `40000102` without a report, `40000103` `tak` with Dad's `montaż ręcznie` a problem).
- `zostaw-moja`: `Zostaw moją` in the popover (the browser's `POST /api/report-entering/keep`) removes the difference at once: the popover stays open without the button, the tile of `wykonawca.b` turns `Komplet, wpisane 1 z 1` and his line `Komplet` without a reload, `40000103` is entered in its `orders_detail`; the decision is in `config/wpisanie-raportow-decyzje.json` and INTERMAX stays byte for byte.
- `przypisanie-nadawcy` (#1475): region `Spoza listy adresów` has the button `Przypisz do Wykonawcy…` (screenshot `414`); it opens Ustawienia on Wykonawcy (`Ustawienia/Wykonawcy`) with group `Przypisz adres` naming `obcy@przyklad.invalid` and the Lista Wykonawców unchanged (screenshot `415`; at 390×844 without a horizontal scroll, screenshot `417`); choosing `Wykonawca Testowy D` in combobox `Wykonawca` saves the address at D at once (`api/raporty-przypisany-ustawienia.json`); after ✕ the region says `Przypisany do wykonawca.d.` without the button and without a reload, and `unknown_senders` has `worker` `wykonawca.d` (`api/raporty-przypisany.json`, screenshot `416`); `Cofnij: wykonawcy[wykonawca.d]` in Historia gives the Lista Wykonawców its bytes back and the button returns.
- `dzien-bez-problemow`: harness: the stranger's mail out of the Skrzynka raportów; the next click of the header button, with region `Spoza listy adresów` still on the page, has `Problemy 0`, gives no new Powiadomienie (`GET /api/notifications` unchanged), and its Logi have the decision in `report_entering.kept`; without a reload the view has no problem, no region `Spoza listy adresów`, and the tiles match the API answer.
- `waski-ekran`: at 390 px the page does not scroll sideways, the header keeps its button, group `Zakres dni` and the calendar button, the toolbar its search and `Status` inside the screen, and table `Mapa Raportów` scrolls sideways inside its card.
- `mapa-zakresu`: harness: the view answers a window of 26.10–11.11.2026 with today 11.11 (`api/raporty-mapa-okno.json`), as the fixture's clock stands on 19.10; by default the range is `2–11 lis` (10 columns), column `śr. 11.11, święto: Narodowe Święto Niepodległości` reads `11Św.`, Sunday 08.11 is struck through in every row; `wykonawca.c` sent a mail without orders and problems on 07.11 and 08.11, and both cells stay empty (08.11 struck through), as in the prototype; `Późniejsze dni` is off at the window's end; tiles `Czeka` (yesterday, no mail), `Problem`, `Bez raportu` (05.11) and `Komplet` and the ring `Wpisane 14 z 17` follow the answer, the lines say `1 problem · 1 bez raportu` and `Czeka na raport`; the popover of a problem has its sentence, and under the last order of that day the calm note `przejęte od wykonawca.a` (a Przeniesienie zlecenia, #1347) with the order's `Wpisane` badge and no `Problem`, in the light and the dark theme, and in the popover of `wykonawca.a` that day `przekazane wykonawca.b` as a row of its own with that order's number and no badge. `Wcześniejsze dni` moves to `26 paź – 4 lis` (`#/raporty/2026-10-26/2026-11-04`, column of 01.11 Wszystkich Świętych, the arrow off), a reload keeps it, `Późniejsze dni` and Back in the browser move between both, and back at `2–11 lis` `Późniejsze dni` is off again. In the calendar 12.11 is off; clicks on 3 and 6 November (`Kliknij ostatni dzień` in between) give `3–6 lis` and 4 columns; `Bieżące dwa tygodnie` returns to `2–11 lis`. In `Status` the list `Pokaż w widoku` counts `Problem 1`, `Bez raportu 1`, `Czeka 0`; `Problem` leaves only `wykonawca.b` (`1 z 3 Wykonawców`) and dims his other tiles; `Pokaż wszystko` shows all three again. At 390 px the same as `waski-ekran`.
- `przypomnienia`: harness: the routed window of `mapa-zakresu` has Przypomnienia o raporcie of `wykonawca.b` for 05.11 sent 06.11 at 8:00 and 18:00 in Dad's time and `reminders_without_footer`; the page says `Przypomnienia o raporcie idą bez Twojej stopki`, the popover of `wykonawca.b` 05.11 ends with `Przypomnienia 06.11 08:00, 06.11 18:00`, his popover of 03.11 has no Przypomnienie, and the popover of `wykonawca.a` 03.11 has both its row `przekazane wykonawca.b` and `Przypomnienie 04.11 08:00` (sent before his late Raport), and the popover of `wykonawca.c` 09.11 has under its last order the calm note `dopisane z raportu, uzupełnij resztę` (a Zlecenie dopisane z raportu without `ADRES`, #1354) with the order's `Wpisane` badge and no `Problem` (`tests/test_centrum_wpisanie_raportow.py` holds the server side: the times from the result of the reminders' work, the footer note gone after the next check with the file, no addresses or subjects, #1351).
- `zatrzymanie`: harness: INTERMAX pointed to a file that is no workbook; the click stops (`ending` not `finished`), region `Zatrzymanie Wpisania raportów` says `<headline>. Komunikat jest w Uruchomieniach.`, and its link `Uruchomieniach` opens Uruchomienia with the stop banner.

## How to get to it (user POV)

- The menu `Sekcje Centrum rozliczeń` → link `Raporty`, right after `Uruchomienia`.
- The result of `Wpisz raporty z maili` on Uruchomienia → `Otwórz Raporty`.
- The address `#/raporty/<od>/<do>` (days as `RRRR-MM-DD`; one day `#/raporty/<dzień>`), which the arrows of group `Zakres dni` and the calendar change.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, its Skrzynka raportów is `FolderInbox` on `<root>/maile/`, never Gmail.
- `fixture.json` → `report_entering`: `register` (INTERMAX with ordered orders of 19.10.2026: `40000101` and `40000102` of `wykonawca.a`, `40000103` of `wykonawca.b` with `montaż ręcznie` in `CZYNNOŚCI ZREALIZOWANE`), `mails` (a Raport of each of them for 19.10 and one from `obcy@przyklad.invalid`), `stranger`.
- The fixture's "today" is Monday 19.10.2026, so the first click's window is that day only.

- **No card.** When `GET /api/settings` has no folder okresów: `#/okresy`, `Ustaw w Ustawieniach`, harness answers the picker, `Wskaż Folder okresów`, Esc. `#/uruchomienia`, `Nowe Uruchomienie procesu` when a result is shown (`api/raporty-uruchomienia.json`); region `Uporządkuj INTERMAX` is there, region and button `Wpisz raporty z maili` are not.
- **Button.** Menu link `Raporty` and a reload; Ustawienia, Foldery → `Wskaż Rejestr zleceń`/`Zmień Rejestr zleceń` with `report_entering.register`, Esc; the button `Wpisz raporty z maili` inside `main` is enabled; `api/raporty-przycisk.json`. Capture `280`.
- **Before the click.** `api/raporty-widok-przed.json`.
- **Blocker.** Harness touches the lock file `~$…` of INTERMAX (`excel_lock`) and fires `focus`; `api/raporty-blokada.json`. Capture `285`. Lock file removed, `focus` again.
- **Click.** The header button → `api/raporty-wynik.json` with the three figures; tiles of the view without a reload; menu link `Uruchomienia`, `Otwórz Raporty` in region `Podgląd na żywo`.
- **View.** `api/raporty-widok.json`; a Wykonawca is `row` named after him in `table "Mapa Raportów"`, his tile the button whose name starts with `<Wykonawca>, <dd>. <DD.MM>: ` and reads `… <Stan>, wpisane N z M`, his ring the label `Wpisane N z M`; a click on the tile opens the `dialog` named `<Wykonawca>, <dd>. <DD.MM>` with figures by labels `Zlecenia N`, `Wpisane N`, `Maile N` and list `Zlecenia dnia`; Escape closes it. In list `Sekcje Centrum rozliczeń` the first links are `Okresy`, `Uruchomienia`, `Raporty`, the last with `aria-current=page`, and the page has no other link `Uruchomienia`. Capture `281` with the popover of `wykonawca.b`.
- **Zostaw moją.** Click it in the popover while waiting for the response of `/api/report-entering/keep`; read `config/wpisanie-raportow-decyzje.json`. Capture `282`.
- **Day without problems.** Harness moves `raport-obcy.eml` to `<root>/maile-odlozone/` (back at the end of the step); `api/raporty-powiadomienia-przed.json` and `-po.json`, the header button on Raporty → `api/raporty-drugie.json`, the newest file of Logi of `report_entering`; `api/raporty-bez-problemow.json`. Capture `283`.
- **Narrow screen.** Viewport 390×844; `document.documentElement.scrollWidth` against its `clientWidth` (the gutter Centrum keeps), the table's container `scrollWidth` against its `clientWidth`, bounding boxes of the header button, group `Zakres dni`, `Wybierz dni w kalendarzu`, `Szukaj Wykonawcy` and `Status`. Capture `284`. Viewport back to 1440×1000.
- **Range map.** `page.route` on `**/api/report-entering/view` answers the window of `_window_view` (also in `api/raporty-mapa-okno.json`); `#/raporty` and a reload. Column headers are named `<dd>. <DD.MM>` (a holiday adds `, święto: <name>`), a Sunday's cells without orders or problems are `td[data-day=…].niedziela` (a Sunday with orders gets a normal tile); the map without a popover, capture `293`. Popover of `wykonawca.b` 03.11 in the light theme (`288`) and the dark one (`289`), then the popover of `wykonawca.a` 03.11 without a capture, the theme back as it was. Przypomnienia: the popover of `wykonawca.b` 05.11, capture `294`; the popover of `wykonawca.a` 03.11 with the note and the Przypomnienie, capture `295`; the popover of `wykonawca.c` 09.11 with the note of the added order, capture `296`. Arrows by names `Wcześniejsze dni`/`Późniejsze dni`, `page.go_back()`/`go_forward()`. Calendar: `Wybierz dni w kalendarzu` → `dialog "Kalendarz dni"`, a day is `button[data-day="D.MM.RRRR"]`; hover 6 November before the second click, capture `290`. Status: button `Status` → `dialog "Pokaż w widoku"`, a state is the button `<Stan> <dni>` with `aria-pressed`; the dimmed tile has computed `opacity` below 0.5; capture `291`. 390 px as in the narrow screen, capture `292`. Unroute, then `#/raporty` shows `19 paź` again.
- **Another Uruchomienie.** `page.route` on `**/api/runs/events` answers one event of a running Uporządkowanie INTERMAX (`OTHER_RUN`); reload; capture `287` live (the menu's sign of the run turns); unroute and reload.
- **Stop.** Harness writes `<root>/INTERMAX/zepsuty/<name of INTERMAX>` with bytes that are no workbook; `Zmień Rejestr zleceń` in Ustawienia to it; the header button → `api/raporty-zatrzymanie.json`. Capture `286`. The link `Uruchomieniach` → the stop banner (`stop_banner`). Harness: the Rejestr zleceń from before the feature.
- **Proof.** Screenshots `280`–`296` and `414`–`417`, `api/raporty-*.json`, `state/` (the Logi), checks in `drive.txt`.

### Real mailbox (only on the machine with the access file, with Maks's consent)

The synthetic mails prove the rules; only Dad's real Raporty wykonawców show the forms no test has yet. On 11.11.2026
a review of them next to their Wpisy found two faults of the core that the probe's figures did not show: a mail app's
footer inside the activities, and contradicting Wpisy of one number. Run this path before a Wydanie that changes how
Raporty are recognised (`src/rozliczenia/worker_reports/`) or the IMAP port (`src/rozliczenia/worker_report_inbox.py`),
only on a machine that holds the access file (`config/skrzynka-raportow.txt` with the app password; today only Maks's
Mac), and only after Maks agreed to this run. Never open the access file yourself, and never run the probe without
that consent: it logs in to Dad's real Gmail (read-only, `EXAMINE` and `BODY.PEEK`). CI never runs this path.

- **Run.** `.venv/bin/python tools/proba_skrzynki_raportow.py --config ~/MAXIMISEART-Dad/config --przeglad ~/.t3/notes/<run>/wpisy.txt`
  (`--od RRRR-MM-DD` for another first day, by default 14 days back; `--nadpisz` replaces the file of an earlier run).
  Stdout is the probe's figures, unchanged, ending with `PROBA IMAP OK | …` or `PROBA IMAP FAIL | <powód>`. The file
  (rights `0600`) holds every Raport wykonawcy and every mail of a Wykonawca with an unrecognised subject, by arrival:
  the arrival, the Wykonawca as `Wykonawca A`, `B`, …, the subject, the day or the subject's fault, the body as the
  port gave it, and the core's Wpisy (number, `tak`/`nie` or `bez tak/nie: <fault>`, activities); at the end, every
  number with several Wpisy of one Wykonawca and day. Before it connects, the tool refuses a path inside a Git
  repository (the tool's clone included) and an existing file without `--nadpisz`.
- **Review checklist.** Read every body next to its Wpisy and count, per item, the mails that show it:
  - footers and signatures inside the activities (`Wysłane z …`, a name, a phone number, a greeting after the last Wpis);
  - an activity cut short, or glued to the next Wpis or to a quoted earlier mail;
  - contradicting Wpisy of one number (section `NUMERY Z KILKOMA WPISAMI …`): a later mail correcting an earlier one is
    the rule, but one number twice in one body is not, and the file shows only its first Wpis, as the core keeps it;
  - unrecognised subjects (`temat nierozpoznany: <fault>`): a form Dad's Wykonawcy write often is a missing rule;
  - Raporty outside the window (`dzien spoza okna proby`), which Wpisanie raportów skips silently, and numbers that are
    no order numbers (a phone number, a date, too few digits);
  - Polish letters: each one intact, with no `Ã`, `Ä`, `Å`, `Ă`, `Ĺ` or U+FFFD (also counted in `zepsute_znaki`).
- **What may leave the file.** The file holds real mails: names, addresses and clients' order numbers. In the chat, an
  issue or a PR go only the stdout lines, the counts per checklist item and each finding as a form rebuilt from
  synthetic data (`40000001 tak wymiana gniazdka` followed by `Wysłane z iPhone'a`), never a body, subject, activity,
  name, address or order number from the file. Keep it in `~/.t3/notes/<run>/` on that machine, never in the
  repository or in `/tmp`.
- **It does not replace tests.** Every finding gets a test with its synthetic form that fails before the fix, in
  `tests/test_rdzen_raportow.py` for the core or `tests/test_skrzynka_raportow.py` for the port; the next run on the
  real mailbox shows whether the form is gone.

## Gotchas

- `Otwórz Raporty` is an anchor rendered as a button, so its role is `button`, not `link`.
- The card of Uporządkowanie INTERMAX on Uruchomienia has the same group `INTERMAX`; on Raporty group `INTERMAX` is the only one.
- The header button changes its name to `Wpisuję raporty…` while the Wpisanie runs, so find it by `Wpisz raporty z maili` only before the click and after the end.
- The toast after a Wpisanie is a `dialog` too, so close a popover by waiting for that popover to go, not for every dialog.
- The calendar's popover stays in the page during its exit animation, at its place in the wide layout, so wait for it to go before narrowing the viewport, or the page measures wider than the screen.
- The fixture's clock stands on 19.10.2026 and the server never gives a day after today, so holidays, Sundays, `Czeka` and the range come from the routed window of `mapa-zakresu`; its tiles and lines follow `_window_view`, while `tests/test_centrum_wpisanie_raportow.py` holds the server's window with the 11.11 holiday (#1322).
- The feature points the Rejestr zleceń to its own INTERMAX and back, so in `all` it runs after every feature that reads the Rejestr zleceń, and it counts only the Logi of `report_entering`.
- A difference with Dad's value is a problem only while its Wpis is in the mailbox: the second click finds the same mails, and only the decision keeps the difference away.
