# Reguły ilości i Urządzenia

In the group Ilości of the window Ustawienia, Dad sees the Reguły ilości and the Lista Urządzeń that the next
Przygotowanie pliku zbiorczego uses (ADR 0033); the editor of a rule is `edytor-regul-ilosci.md`, and editing the
Lista Urządzeń is #1479. Each rule is one sentence
„Jeśli … to …” built by the server from the engine's types, the rules stand in three groups by their scope, and a
column shows its price-list name from row 17 of the Wzorzec pliku zbiorczego next to its letter, or the letter alone
when the Wzorzec cannot be read. One sentence says the rules work from the next Przygotowanie and leave finished Pliki
zbiorcze unchanged. Urządzenia lists each component with its other spellings and its group. A narrow window shows
every rule and every Urządzenie.

## Sub-features

Printed by `scripts/sub_features.py --feature reguly-ilosci` from the drive's steps and checks; refresh the section with it.

- `reguly-zdania`: the rules stand in the three groups of their scope, in order (…); each of the … rules of the server is one sentence on screen (…); column Z shows its price-list name „Montaż ONT” next to the letter.
- `reguly-bez-wzorca`: without a readable Wzorzec pliku zbiorczego the column is its letter alone.
- `urzadzenia`: the Lista Urządzeń shows its … components with other spellings and group.
- `waskie-okno`: the narrow window shows every rule (…); on a narrow window the sentences wrap without a horizontal scroll.

## How to get to it (user POV)

Dad opens Ustawienia (the gear in the menu's footer) and chooses `Reguły ilości` or `Urządzenia` in the group Ilości;
a bookmark of `#/ustawienia/reguly-ilosci` or `#/ustawienia/urzadzenia` opens the section too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature reguly-ilosci`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP reguly-ilosci` in `drive.txt`, screenshots `350`–`354` and `api/reguly-ilosci.json`.

## Gotchas

None known that the drive does not handle.
