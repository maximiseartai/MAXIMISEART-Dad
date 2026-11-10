# Wpisanie raportów

Dad clicks `Wpisz raporty z maili` on the card under `Nowe Uruchomienie procesu` on Uruchomienia, and `tak`/`nie` and
the activities from the Raporty wykonawców go into empty cells of INTERMAX (ADR 0028). `Otwórz Raporty`, on the card and
at the result, opens the view Raporty: the result of the last click, read from its file and not from the mailbox, with
the day (today by default), at each Wykonawca his orders of the day, the entered ones, the mails and the problems, a
list of problems with the reason and the order number, the orders without a report, and the Raporty from addresses
outside the list. At a difference with Dad's own value, `Zostaw moją` keeps his value: the difference is gone at once
and does not come back at the next click.

## Sub-features

- `karta`: with the folder okresów set and the card's `Wskaż INTERMAX`/`Zmień INTERMAX` pointed to the fixture's INTERMAX of `wpisanie-raportow`, the card has no blocker, the enabled button `Wpisz raporty z maili` and the link `Otwórz Raporty`; `GET /api/report-entering` has no `blocker`.
- `widok-przed-kliknieciem`: `Otwórz Raporty` opens the page `Raporty` on today 19.10.2026 (`today` and `day` of `GET /api/report-entering/view`); before any click it says `Jeszcze nie ma Raportów`.
- `klikniecie`: the button writes the Raporty of `wykonawca.a` and `wykonawca.b`: the result figures `Wpisane 2`, `Problemy 2`, `Raporty 2`, INTERMAX changed on disk; `Otwórz Raporty` in region `Podgląd na żywo` opens the view.
- `widok`: group `Dzień` shows `poniedziałek 19.10 · dziś`; list `Wykonawcy` has the items `wykonawca.a` (Zlecenia 2, Wpisane 1, Maile 1, Problemy 0, group `Bez raportu` with `40000102`) and `wykonawca.b` (1, 1, 1, 1; list `Problemy` with the difference from Dad's `montaż ręcznie` and the button `Zostaw moją`); region `Spoza listy adresów` shows `obcy@przyklad.invalid`, which no file of Logi has; the API answer has the same figures.
- `zostaw-moja`: `Zostaw moją` (the browser's `POST /api/report-entering/keep`) removes the difference at once (`Problemy 0` at `wykonawca.b`), writes it to `config/wpisanie-raportow-decyzje.json` and leaves INTERMAX byte for byte.
- `dzien-bez-problemow`: harness: the stranger's mail out of the Skrzynka raportów; the next click has `Problemy 0`, gives no new Powiadomienie (`GET /api/notifications` unchanged), and its Logi have the decision in `report_entering.kept`; the view has no problem, no `Zostaw moją` and no region `Spoza listy adresów`.
- `waski-ekran`: at 390 px each Wykonawca keeps his name and all four figures inside the screen, and the page does not scroll sideways.

## How to get to it (user POV)

- Uruchomienia → the card `Wpisz raporty z maili` → `Otwórz Raporty` (after a result: `Nowe Uruchomienie procesu` first).
- The result of `Wpisz raporty z maili` → `Otwórz Raporty`.
- The address `#/raporty/<dzień>` (the day as `RRRR-MM-DD`), which the arrows of group `Dzień` change.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, its Skrzynka raportów is `FolderInbox` on `<root>/maile/`, never Gmail.
- `fixture.json` → `report_entering`: `register` (INTERMAX with ordered orders of 19.10.2026: `40000101` and `40000102` of `wykonawca.a`, `40000103` of `wykonawca.b` with `montaż ręcznie` in `CZYNNOŚCI ZREALIZOWANE`), `mails` (a Raport of each of them for 19.10 and one from `obcy@przyklad.invalid`), `stranger`.
- The fixture's "today" is Monday 19.10.2026, so the first click's window is that day only.

- **Card.** When `GET /api/settings` has no folder okresów: `#/okresy`, harness answers the picker, `Wskaż folder okresów`. `#/uruchomienia`, `Nowe Uruchomienie procesu` when a result is shown; region `Wpisz raporty z maili` → `Wskaż INTERMAX`/`Zmień INTERMAX` with `report_entering.register`; button enabled, button-styled link `Otwórz Raporty` (role `button`); `api/raporty-karta.json`. Capture `280`.
- **Before the click.** `Otwórz Raporty` → heading `Raporty`; `api/raporty-widok-przed.json`.
- **Click.** The card's button → `api/raporty-wynik.json` with the three figures; `Otwórz Raporty` in region `Podgląd na żywo`.
- **View.** `api/raporty-widok.json`; the rows by `list "Wykonawcy"` → `listitem` named after the Wykonawca, figures by labels `Zlecenia N`, `Wpisane N`, `Maile N`, `Problemy N`; the first button of a row opens it. Capture `281`.
- **Zostaw moją.** Click it while waiting for the response of `/api/report-entering/keep`; read `config/wpisanie-raportow-decyzje.json`. Capture `282`.
- **Day without problems.** Harness moves `raport-obcy.eml` to `<root>/maile-odlozone/` (back at the end of the step); `api/raporty-powiadomienia-przed.json` and `-po.json`, the click → `api/raporty-drugie.json`, the newest file of Logi of `report_entering`; `Otwórz Raporty`; `api/raporty-bez-problemow.json`. Capture `283`.
- **Narrow screen.** Viewport 390×844, row `wykonawca.a` opened, bounding boxes of the names and of `Problemy 0`. Capture `284`. Viewport back to 1440×1000. Harness: the Rejestr zleceń from before the feature.
- **Proof.** Screenshots `280`–`284`, `api/raporty-*.json`, `state/` (the Logi), checks in `drive.txt`.

## Gotchas

- `Otwórz Raporty` is an anchor rendered as a button, so its role is `button`, not `link`.
- The card of Uporządkowanie INTERMAX has the same group `INTERMAX`; find `Zmień INTERMAX` inside region `Wpisz raporty z maili`.
- The feature points the Rejestr zleceń to its own INTERMAX and back, so in `all` it runs after every feature that reads the Rejestr zleceń, and it counts only the Logi of `report_entering`.
- A difference with Dad's value is a problem only while its Wpis is in the mailbox: the second click finds the same mails, and only the decision keeps the difference away.
