# Edytor Reguł ilości

In the section Reguły ilości of the window Ustawienia, Dad adds, changes and removes a Reguła ilości himself (ADR 0033,
#1478). The editor opens in place of the list: the scope („Dla zleceń”), the conditions („Gdy” or „Ale nie gdy”, six
kinds), the action (three kinds, a column by its price-list name from row 17 next to its letter) and, below, the preview
of the change on the last four Pliki zbiorcze that Przebieg rozliczeń settled, counted by the server with the same
computation as the Kontrola ilości: how many rows change, in how many of them the rule gives what Dad wrote, the
differences of the Kontrola before → after, and each row whose rule differs from Dad's entry, without the address, the
order number and UMOWA. Two rules into one column show their sum with both rules. The rule saves only with „Zapisz”,
also with differences; a rule the server refuses is one sentence at its field. Closing the window with an unsaved rule
asks first. Each change has its row in Historia as the rule's sentence, with „Cofnij”.

## Sub-features

Printed by `scripts/sub_features.py --feature edytor-regul-ilosci` from the drive's steps and checks; refresh the section with it.

- `edytor-nowa-regula`: a new rule starts without an action, and the preview says to choose one; the server's preview changes … rows of the last settled Pliki zbiorcze; the preview shows the server's count of changed rows, the Kontrola differences and the rows; two rules into V show their sum with both rules („V = 3, bo reguły …”).
- `edytor-zla-regula`: a rule the server refuses is one sentence at its field, and nothing is saved.
- `edytor-niezapisany`: closing the window with an unsaved rule asks first, and „Wróć” keeps the form.
- `edytor-zapis`: „Zapisz” adds the rule at the end of the server's rules and writes the file of Reguły ilości.
- `edytor-historia`: Historia reads the change of a rule as its sentence, not the file's text; „Cofnij” in Historia brings the earlier rules back.
- `edytor-waskie-okno`: a rule opened without a change has its sentence and changes no row; on a narrow window the editor and its preview wrap without a horizontal scroll.

## How to get to it (user POV)

Dad opens Ustawienia with the gear in the menu's footer and chooses `Reguły ilości` in the group Ilości. There he
clicks `Dodaj regułę`, or the pencil `Zmień regułę` of a rule. A bookmark of `#/ustawienia/reguly-ilosci` opens the
section too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature edytor-regul-ilosci`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP edytor-regul-ilosci` in `drive.txt`, screenshots `380`–`385` and `api/edytor-*.json`.

## Gotchas

- The drive ends with the rules of the Release (the change undone in Historia), but `config/reguly-ilosci.yaml` stays
  with their content and Historia keeps both rows.
