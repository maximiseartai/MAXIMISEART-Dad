# Wpisanie raportów

Dad clicks `Wpisz raporty z maili`, the one main button in the header of Raporty, and `tak`/`nie` and the activities
from the Raporty wykonawców go into empty cells of INTERMAX (ADR 0028). Uruchomienia have no card of it (Maks's decision
of 11.11.2026, #1321), but they still show the Uruchomienie live and its result with `Otwórz Raporty`. Raporty set
INTERMAX (in one quiet line, with `Ustaw w Ustawieniach` while it is not set), turn the button off at a blocker from the server, and
read the view again by themselves when the Wpisanie ends, and show the last click under the button in the line „Ostatnio …”, from its Logi, with the button of its card. The button is off while any Uruchomienie procesu runs. The
view Raporty is the result of the last click, read from its file and not from the mailbox: the server gives the whole
window of the click (each day with its holiday, each Wykonawca with his days and the orders of each day as INTERMAX has
them after the click, #1322), and the page shows it as a Mapa cieplna (#1323): a row per Wykonawca in alphabetical
order, a column per day of the range from the address (by default Monday of last week to Sunday of this week, clipped
to the days of the window), a tile `wpisane/zlecenia` in the colour of the day's state (Komplet, Bez raportu,
Problem; Czeka, for yesterday or today without a mail, shows a clock instead of the figures), holidays as a yellow
column with `Św.`, a Sunday without orders struck through,
and a ring of the entered orders of the range. A tile of a day with a Przypomnienie o raporcie wears a violet bell in its
corner. A tile opens a popover with the day's figures, the course of its Przypomnienia and its orders, with each
problem's sentence and `Zostaw moją`. The range changes with the arrows and a calendar, the Status filter keeps the
Wykonawcy with a day of the chosen states, or with `Przypomniane` a day with a Przypomnienie, and dims the other tiles, and the Raporty from addresses outside the list
stand under the table. At a difference with Dad's own value, `Zostaw moją` keeps his value: the difference is gone at
once and does not come back at the next click. At a Wpis with `t`, `n`, `skuteczne` or `nieskuteczne` instead of `tak`/`nie` the popover
says what Wpis na życzenie writes (the day, `SKUTECZNE` and `CZYNNOŚCI ZREALIZOWANE`), and `Wpisz do INTERMAX` enters it
with one Wpisanie raportów that carries Dad's decision (ADR 0041); with INTERMAX open in Excel it refuses in one sentence.
The same button stands at each order whose latest mail is a Raport z błędem tematu (state Błąd tematu) and enters its
Wpis to the day of that order; when that Wpis takes over the order of another Wykonawca, the button says to whom the
order goes, and the click moves it like a correct Raport (#2040). The fault of the subject carries the same button under
the number of each such order in the tile where Dad sees it, and the tile that has the order stands as Problem, never
Komplet, until Dad decides.

## Sub-features

Printed by `scripts/sub_features.py --feature wpisanie-raportow` from the drive's steps and checks; refresh the section with it.

- `bez-karty-w-uruchomieniach`: Uruchomienia have the card of Uporządkowanie INTERMAX and no card or button Wpisz raporty z maili.
- `przycisk`: the button in the header of Raporty is on with the INTERMAX of the fixture and the folder okresów.
- `w-czasie-innego`: while another Uruchomienie procesu runs, `Wpisz raporty z maili` is off; with no Uruchomienie running the button is on again.
- `widok-przed-kliknieciem`: the view has today, 19.10.2026, among the days of its window, without a holiday.
- `blokada`: INTERMAX open in Excel turns the button off and the sentence under the header names its lock file.
- `klikniecie`: the click writes the Raporty of both Wykonawcy and has two problems: Dad's own value and a stranger; INTERMAX is written on disk; Raporty show the result of the click without a reload, and the button is on again; under the button, without a reload, „Ostatnio …” shows the click from its Logi with the button of its card.
- `widok`: the view has each Wykonawca of the day with the figures of the click; the view has the window of the click and at each Wykonawca the orders of the day as INTERMAX has them after the click, with Dad's own value and its state; the Mapa cieplna has the one day of the window; each tile and ring match the server's view: wpisane of zlecenia and the state of the day; the Raport from outside the list shows its address; Raporty is a menu section right after Uruchomienia; the popover of wykonawca.a has his figures and the orders of the day in the INTERMAX order; the order tak without a Kod czynności has „BRAK KODU” in the view and the popover, the order without a Wpis has not (ADR 0041); the Logi of the click have no address of the stranger: only the view shows it.
- `zostaw-moja`: the difference is gone at once; after „Zostaw moją” the order with Dad's own value is entered, and its tile turns Komplet without a reload; the decision is in the file of decisions; „Zostaw moją” leaves INTERMAX byte for byte.
- `przypisanie-nadawcy`: „Przypisz do Wykonawcy…” opens the choice and saves nothing; on a narrow window the choice fits without a horizontal scroll; the choice saves the address at the Wykonawca at once; Raporty, without a reload, show the stranger as assigned to the Wykonawca; the next click enters the Raport; after „Cofnij” the stranger is unknown again in Raporty.
- `dzien-bez-problemow`: the next click does not bring the kept difference back; a click without problems gives no Powiadomienie; the Logi of the next click have the decision of „Zostaw moją”; the day has no problems left.
- `waski-ekran`: on a narrow screen … scrolls sideways inside its card, while the page, the header and the toolbar stay inside the screen (page … px, table scrolls …, boxes …).
- `wpis-na-zyczenie-blad-tematu`: the Raport z błędem tematu enters nothing and gives one problem; its order has the state Błąd tematu and the view offers Wpis na życzenie with the day of the order, tak and the activities; before the click the order Błąd tematu says what it writes: the day, SKUTECZNE and CZYNNOŚCI ZREALIZOWANE; the click enters the order with one Uruchomienie and the fault of the subject is gone; INTERMAX is written on disk; after the click the order has tak and the activities of the Raport like any Wpis; the memory file and the Logi of the Uruchomienie have Dad's decision at the day of the order; the popover has the order entered, without the button and the fault, and the tile turns Komplet; the next click „Wpisz raporty z maili” does not bring the fault of the subject back.
- `wpis-na-zyczenie`: the Raport with `t` gives one problem and enters nothing; the view offers Wpis na życzenie with what it writes: the day, tak and the activities; before the click the popover says what it writes: the day, SKUTECZNE and CZYNNOŚCI ZREALIZOWANE; with INTERMAX open in Excel the button refuses in one sentence and INTERMAX stays byte for byte; the click enters the order with one Uruchomienie and leaves no problem; INTERMAX is written on disk; after the click the order has tak and the activities like any Wpis, and the problem is gone; the memory file and the Logi of the Uruchomienie have Dad's decision; the popover has the order entered, without the button, and the tile turns Komplet without a reload.
- `wpis-na-zyczenie-przeniesienie`: the order of wykonawca.a has the state Błąd tematu and Wpis na życzenie of wykonawca.b; the fault of the subject stands at wykonawca.b and at wykonawca.a, which has the order, both with its Wpis na życzenie; the tile of wykonawca.a is Problem, not Komplet, and its order says it goes to wykonawca.b and what it writes, with one button; the red tile of wykonawca.b has the button at its fault of the subject, with the number of the order and what it writes; the click leaves no problem; after the click the order stands at wykonawca.b with tak and the activities, like after a correct Raport; the Logi of the Uruchomienie have the Przeniesienie to wykonawca.b; the popover of wykonawca.b has the order taken over from wykonawca.a, without the button.
- `mapa-zakresu`: by default the range is Monday of last week to today: 2–11.11; 11.11 has the holiday column with „Św.” and Sunday 08.11 is struck through in every row; a day with a mail but no orders and no problem is an empty cell, on Sunday struck through; yesterday without a mail waits, an older order without a report is yellow, rings count the range; the popover of a tile shows the problem's sentence and, under the taken order, the calm note „przejęte od wykonawca.a” without a Problem badge, in the light and the dark theme; the popover of wykonawca.a shows „przekazane wykonawca.b” as a row of its own, without a badge.
- `przypomnienia`: the tiles with a Przypomnienie name its count; the popover of 05.11 lists its orders, both Przypomnienia in Dad's time and the Raport that came, 03.11 has no such list, and 10.11 of wykonawca.a, still without a Raport, ends with its Przypomnienie; the page says the footer file is missing; the popover of wykonawca.a 03.11 has both „przekazane wykonawca.b” and its Przypomnienie; the popover of wykonawca.c 09.11 has „dopisane z raportu, uzupełnij resztę” under its last order, entered and without a Problem badge (#1354); the arrow moves the range by its length; a reload keeps the range of the address; the arrows change columns and address, Back returns, and each arrow is off at its window end; two clicks in the calendar choose 03–06.11; days outside the window are off; Status Problem leaves wykonawca.b and dims his other tiles (opacity … vs …); „Pokaż wszystko” takes the filter off; Przypomniane leaves wykonawca.a and wykonawca.b, counts their Przypomnienia under the name and dims the days without one (opacity … vs …); „Bieżące dwa tygodnie” returns to the default range; on a narrow screen … scrolls sideways inside its card, while the page, the header and the toolbar stay inside the screen (page … px, table scrolls …, boxes …).
- `blad-tematu`: the tile of a day with a Raport z błędem tematu is Problem, the day without a Raport Bez raportu; the popover of 16.11 shows the kind of the fault „inne słowa”, the day Centrum counts it for and when it came, with the subject after the guard of the data rule, and its orders as Błąd tematu, not Bez raportu; the popover of 18.11 has the calm note of the mistaken subject without a Problem badge, and the Raport of wykonawca.b without a day is counted for no day.
- `zatrzymanie`: the Wpisanie with a broken INTERMAX stops; Raporty say in one sentence that the Wpisanie stopped and link to Uruchomienia; the link leads to Uruchomienia, where the stop stands with its Komunikat.

## How to get to it (user POV)

- The menu `Sekcje Centrum rozliczeń` → link `Raporty`, right after `Uruchomienia`.
- The result of `Wpisz raporty z maili` on Uruchomienia → `Otwórz Raporty`.
- The address `#/raporty/<od>/<do>` (days as `RRRR-MM-DD`; one day `#/raporty/<dzień>`), which the arrows of group `Zakres dni` and the calendar change.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wpisanie-raportow`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/raporty-*.json` and `state/` (the Logi of Wpisanie raportów).

The days, holidays and Przypomnienia of `mapa-zakresu` and `przypomnienia` come from a routed window.
`tests/test_centrum_wpisanie_raportow.py::test_widok_raporty_daje_kazdy_dzien_okna_z_nazwa_swieta` checks the server's
own window: every day of the window, with 11.11 named a public holiday;
`tests/test_centrum_wpisanie_raportow.py::test_widok_raporty_pokazuje_pory_przypomnien_przy_dniu_wykonawcy_a_brak_stopki_do_sprawdzenia_po_jej_wpisaniu`
checks that the view shows the moments of the Przypomnienia at each Wykonawca's day, and the missing footer until the
check after it is filled in.

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
- The calendar's popover stays in the page during its exit animation, at its place in the wide layout, so wait for it to go before narrowing the viewport, or the page measures wider than the screen.
- The feature points the Rejestr zleceń to its own INTERMAX and back, so in `all` it runs after every feature that reads the Rejestr zleceń, and it counts only the Logi of `report_entering`.
- A difference with Dad's value is a problem only while its Wpis is in the mailbox: the second click finds the same mails, and only the decision keeps the difference away.
