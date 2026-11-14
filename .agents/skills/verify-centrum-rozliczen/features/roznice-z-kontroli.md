# Różnice z Kontroli ilości

The section Reguły ilości of the window Ustawienia lists „Tu wpisałeś inaczej niż reguła”: every cell of the last four
Pliki zbiorcze settled by Przebieg rozliczeń in which Dad wrote something else than the Reguły ilości, counted by the
server with the same computation as the Kontrola ilości (ADR 0033, #1480). Each difference shows the column with its
price-list name, the rule's value, Dad's entry, URZĄDZENIA and CZYNNOŚCI, and the period, row and day with the hour,
without the address, the order number and UMOWA. „Popraw regułę” opens the editor of Reguły ilości with a new rule whose
conditions come from URZĄDZENIA of that difference, not saved until „Zapisz”. „To był wyjątek” saves an exception with
„Zapisano · Cofnij”, the difference leaves the list for good, and „Cofnij” in Historia brings it back.

## Sub-features

Printed by `scripts/sub_features.py --feature roznice-z-kontroli` from the drive's steps and checks; refresh the section with it.

- `roznice-lista`: the server lists … differences of the Kontrola ilości of the settled period; the first difference shows the server's column, rule value, Dad's entry and row, without UMOWA.
- `roznice-popraw-regule`: „Popraw regułę” opens a new rule with the conditions of the server's form for this difference; the form from a difference is unsaved from the start, so „Zapisz” takes it as it is; the rule from a difference is not saved until Dad presses „Zapisz”.
- `roznice-wyjatek`: „To był wyjątek” hides the difference on the server; the exception is a setting in config/wyjatki-ilosci.yaml; the exception says „Zapisano” with „Cofnij” like every change of Ustawienia.
- `roznice-historia`: Historia reads the exception as a sentence with the period, the row and the column; „Cofnij” in Historia brings the difference back.
- `roznice-waskie-okno`: on a narrow window the list of differences wraps without a horizontal scroll.

## How to get to it (user POV)

Dad opens Ustawienia (the gear in the menu's footer) and chooses `Reguły ilości` in the group Ilości; the list stands
above the rules. A bookmark of `#/ustawienia/reguly-ilosci` opens it too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature roznice-z-kontroli`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP roznice-z-kontroli` in `drive.txt`, screenshots `400`–`404` and `api/roznice-*.json`.

## Gotchas

- The differences come from the fixture, not the drive: the Plik zbiorczy of `06_12_10_2026` that `przebieg-rozliczen`
  settles has Wiersze danych with a component outside the Lista Urządzeń, so the Reguły ilości z Wydania give V where
  Dad wrote nothing. A fixture without them fails the first check with no differences.
