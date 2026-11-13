# Różnice z Kontroli ilości

The section Reguły ilości of the window Ustawienia lists „Tu wpisałeś inaczej niż reguła”: every cell of the last four
Pliki zbiorcze settled by Przebieg rozliczeń in which Dad wrote something else than the Reguły ilości, counted by the
server with the same computation as the Kontrola ilości (ADR 0033, #1480). Each difference shows the column with its
price-list name, the rule's value, Dad's entry, URZĄDZENIA and CZYNNOŚCI, and the period, row and day with the hour,
without the address, the order number and UMOWA. „Popraw regułę” opens the editor of Reguły ilości with a new rule whose
conditions come from URZĄDZENIA of that difference, not saved until „Zapisz”. „To był wyjątek” saves an exception with
„Zapisano · Cofnij”, the difference leaves the list for good, and „Cofnij” in Historia brings it back.

## Sub-features

- `roznice-lista`: the region `Tu wpisałeś inaczej niż reguła` has the server's first difference with `reguła <rule> ·
  wpisałeś <tata>` and `<period> · wiersz <row> · <when>`.
- `roznice-popraw-regule`: its „Popraw regułę” opens „Nowa reguła” with as many conditions as the server's form, and
  „Zapisz” is enabled; „Anuluj” returns to the list with the server's rules and the rules file unchanged.
- `roznice-wyjatek`: its „To był wyjątek” takes it off the list and off the server's list, writes its id into
  `config/wyjatki-ilosci.yaml` and shows „Zapisano” with „Cofnij”.
- `roznice-historia`: the newest row of Historia reads `Wyjątek Kontroli ilości` and `Dodano: To był wyjątek: okres
  <period>, wiersz <row>`; its „Cofnij” adds `Usunięto: …` and the server lists the difference again.
- `roznice-waskie-okno`: at 420×860 `#/ustawienia/reguly-ilosci` shows the difference without a horizontal scroll.

## How to get to it (user POV)

- The gear in the menu's footer, then `Reguły ilości` in the group Ilości; the list stands above the rules.

## Driving it with Playwright for Python

Preconditions: Centrum is served for this run with `DOCTOR OK`; `przebieg-rozliczen` settled `06_12_10_2026`, whose
Plik zbiorczy has Wiersze danych with a component outside the Lista Urządzeń, so the Reguły ilości z Wydania give V where
Dad wrote nothing; run alone (`--feature roznice-z-kontroli`) the drive runs `przebieg-rozliczen` first.

- **List.** The harness reads `GET /api/settings/quantity-rules/differences` (evidence `api/roznice-lista.json` with the
  row texts replaced): ready, with differences. `open_settings` on `Reguły ilości`; the item `<column>, wiersz <row>` of
  the server's first difference in the region `Tu wpisałeś inaczej niż reguła` has the values and the row. Screenshot
  `390`.
- **Fix the rule.** Its `Popraw regułę`: heading `Nowa reguła`, the list `Warunki` has `Warunek 1` up to the number of
  the server's conditions and no more; `Zapisz` is enabled. Screenshot `391`. `Anuluj`: the list again; the server's
  rules and `config/reguly-ilosci.yaml` as before.
- **Exception.** Its `To był wyjątek`: the item goes; the server's list has no such id; `config/wyjatki-ilosci.yaml`
  has it; the toast `Zapisano` has `Cofnij`. Screenshot `392`.
- **Historia.** `open_settings` on `Historia`: the first item of list `Zmiany` has `Wyjątek Kontroli ilości` and the
  sentence. Screenshot `393`. Its `Cofnij: Wyjątek Kontroli ilości` adds `Usunięto: To był wyjątek` on top, and the
  server lists the id again.
- **Narrow window.** Viewport 420×860, `goto` `#/ustawienia/reguly-ilosci`: the item, no horizontal scroll. Screenshot
  `394`, then the viewport goes back to 1440×1000 (also in `finally`).
- **Proof.** Screenshots `390`–`394` and the checks in `drive.txt`.

## Gotchas

- URZĄDZENIA and CZYNNOŚCI of the synthetic Plik zbiorczy carry the fixture's row marker: the drive replaces them in
  the ARIA snapshots and in the saved answers (`_capture`, `_differences`), like `edytor-regul-ilosci`.
- The feature saves no rule: `edytor-regul-ilosci` after it in `all` expects its new rule to get `regula-1`.
- It ends with `config/wyjatki-ilosci.yaml` without exceptions and two rows in Historia.
