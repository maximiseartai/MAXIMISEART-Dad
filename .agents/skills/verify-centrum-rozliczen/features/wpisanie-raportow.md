# Wpisanie raportów

Dad clicks `Wpisz raporty z maili`, the one main button in the header of Raporty, and `tak`/`nie` and the activities
from the Raporty wykonawców go into empty cells of INTERMAX (ADR 0028). Uruchomienia have no card of it (Maks's decision
of 11.11.2026, #1321), but they still show the Uruchomienie live and its result with `Otwórz Raporty`. Raporty set
INTERMAX (`Wskaż INTERMAX`/`Zmień INTERMAX` in one quiet line), turn the button off at a blocker from the server, and
read the view again by themselves when the Wpisanie ends. The view Raporty is the result of the last click, read from its
file and not from the mailbox, with the day (today by default), at each Wykonawca his orders of the day, the entered ones, the mails and the problems, a
list of problems with the reason and the order number, the orders without a report, and the Raporty from addresses
outside the list. At a difference with Dad's own value, `Zostaw moją` keeps his value: the difference is gone at once
and does not come back at the next click.

## Sub-features

- `bez-karty-w-uruchomieniach`: the setup of Uruchomienia has region `Uporządkuj INTERMAX` and no region or button `Wpisz raporty z maili`.
- `przycisk`: with the folder okresów set and `Wskaż INTERMAX`/`Zmień INTERMAX` of group `INTERMAX` on Raporty pointed to the fixture's INTERMAX of `wpisanie-raportow`, the header has the enabled button `Wpisz raporty z maili`, group `INTERMAX` names the file, no alert stands under the header; `GET /api/report-entering` has no `blocker` and no `open_in_excel`.
- `widok-przed-kliknieciem`: the page `Raporty` is on today 19.10.2026 (`today` and `day` of `GET /api/report-entering/view`); before any click it says `Jeszcze nie ma Raportów` and `Kliknij „Wpisz raporty z maili” powyżej.`.
- `blokada`: harness: Excel's lock file next to INTERMAX; at Dad's return to the window the button is off and an alert under the header says INTERMAX `jest otwarty w Excelu` with the lock file's name (`open_in_excel`); without the lock file the button is on again and the alert is gone.
- `klikniecie`: the header button writes the Raporty of `wykonawca.a` and `wykonawca.b`: the result figures `Wpisane 2`, `Problemy 2`, `Raporty 2`, INTERMAX changed on disk; without a reload Raporty show both Wykonawcy with the figures of the click and the button is on again; Uruchomienia show the result, and `Otwórz Raporty` in region `Podgląd na żywo` opens the view.
- `widok`: group `Dzień` shows `poniedziałek 19.10 · dziś`; list `Wykonawcy` has the items `wykonawca.a` (Zlecenia 2, Wpisane 1, Maile 1, Problemy 0, group `Bez raportu` with `40000102`) and `wykonawca.b` (1, 1, 1, 1; list `Problemy` with the difference from Dad's `montaż ręcznie` and the button `Zostaw moją`); region `Spoza listy adresów` shows `obcy@przyklad.invalid`, which no file of Logi has; the API answer has the same figures.
- `zostaw-moja`: `Zostaw moją` (the browser's `POST /api/report-entering/keep`) removes the difference at once (`Problemy 0` at `wykonawca.b`), writes it to `config/wpisanie-raportow-decyzje.json` and leaves INTERMAX byte for byte.
- `dzien-bez-problemow`: harness: the stranger's mail out of the Skrzynka raportów; the next click of the header button, with region `Spoza listy adresów` still on the page, has `Problemy 0`, gives no new Powiadomienie (`GET /api/notifications` unchanged), and its Logi have the decision in `report_entering.kept`; without a reload the view has no problem, no `Zostaw moją` and no region `Spoza listy adresów`.
- `waski-ekran`: at 390 px each Wykonawca keeps his name and all four figures inside the screen, so does the header button, and the page does not scroll sideways.
- `zatrzymanie`: harness: INTERMAX pointed to a file that is no workbook; the click stops (`ending` not `finished`), region `Zatrzymanie Wpisania raportów` says `<headline>. Komunikat jest w Uruchomieniach.`, and its link `Uruchomieniach` opens Uruchomienia with the stop banner.

## How to get to it (user POV)

- The menu `Sekcje Centrum rozliczeń` → link `Raporty`, right after `Uruchomienia`.
- The result of `Wpisz raporty z maili` on Uruchomienia → `Otwórz Raporty`.
- The address `#/raporty/<dzień>` (the day as `RRRR-MM-DD`), which the arrows of group `Dzień` change.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, its Skrzynka raportów is `FolderInbox` on `<root>/maile/`, never Gmail.
- `fixture.json` → `report_entering`: `register` (INTERMAX with ordered orders of 19.10.2026: `40000101` and `40000102` of `wykonawca.a`, `40000103` of `wykonawca.b` with `montaż ręcznie` in `CZYNNOŚCI ZREALIZOWANE`), `mails` (a Raport of each of them for 19.10 and one from `obcy@przyklad.invalid`), `stranger`.
- The fixture's "today" is Monday 19.10.2026, so the first click's window is that day only.

- **No card.** When `GET /api/settings` has no folder okresów: `#/okresy`, harness answers the picker, `Wskaż folder okresów`. `#/uruchomienia`, `Nowe Uruchomienie procesu` when a result is shown (`api/raporty-uruchomienia.json`); region `Uporządkuj INTERMAX` is there, region and button `Wpisz raporty z maili` are not.
- **Button.** Menu link `Raporty` and a reload; group `INTERMAX` → `Wskaż INTERMAX`/`Zmień INTERMAX` with `report_entering.register`; the button `Wpisz raporty z maili` inside `main` is enabled; `api/raporty-przycisk.json`. Capture `280`.
- **Before the click.** `api/raporty-widok-przed.json`.
- **Blocker.** Harness touches the lock file `~$…` of INTERMAX (`excel_lock`) and fires `focus`; `api/raporty-blokada.json`. Capture `285`. Lock file removed, `focus` again.
- **Click.** The header button → `api/raporty-wynik.json` with the three figures; rows of the view without a reload; menu link `Uruchomienia`, `Otwórz Raporty` in region `Podgląd na żywo`.
- **View.** `api/raporty-widok.json`; the rows by `list "Wykonawcy"` → `listitem` named after the Wykonawca, figures by labels `Zlecenia N`, `Wpisane N`, `Maile N`, `Problemy N`; the first button of a row opens it. In list `Sekcje Centrum rozliczeń` the first links are `Okresy`, `Uruchomienia`, `Raporty`, the last with `aria-current=page`, and the page has no other link `Uruchomienia`. Capture `281`.
- **Zostaw moją.** Click it while waiting for the response of `/api/report-entering/keep`; read `config/wpisanie-raportow-decyzje.json`. Capture `282`.
- **Day without problems.** Harness moves `raport-obcy.eml` to `<root>/maile-odlozone/` (back at the end of the step); `api/raporty-powiadomienia-przed.json` and `-po.json`, the header button on Raporty → `api/raporty-drugie.json`, the newest file of Logi of `report_entering`; `api/raporty-bez-problemow.json`. Capture `283`.
- **Narrow screen.** Viewport 390×844, row `wykonawca.a` opened, bounding boxes of the names, of `Problemy 0` and of the header button. Capture `284`. Viewport back to 1440×1000.
- **Stop.** Harness writes `<root>/INTERMAX/zepsuty/<name of INTERMAX>` with bytes that are no workbook; `Zmień INTERMAX` to it; the header button → `api/raporty-zatrzymanie.json`. Capture `286`. The link `Uruchomieniach` → the stop banner (`stop_banner`). Harness: the Rejestr zleceń from before the feature.
- **Proof.** Screenshots `280`–`286`, `api/raporty-*.json`, `state/` (the Logi), checks in `drive.txt`.

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
- The feature points the Rejestr zleceń to its own INTERMAX and back, so in `all` it runs after every feature that reads the Rejestr zleceń, and it counts only the Logi of `report_entering`.
- A difference with Dad's value is a problem only while its Wpis is in the mailbox: the second click finds the same mails, and only the decision keeps the difference away.
