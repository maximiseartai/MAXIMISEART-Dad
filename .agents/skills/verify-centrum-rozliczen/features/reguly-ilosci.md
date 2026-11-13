# Reguły ilości i Urządzenia

In the group Ilości of the window Ustawienia, Dad sees the Reguły ilości and the Lista Urządzeń that the next
Przygotowanie pliku zbiorczego uses (ADR 0033), read only: editing them is #1478 and #1479. Each rule is one sentence
„Jeśli … to …” built by the server from the engine's types, the rules stand in three groups by their scope, and a
column shows its price-list name from row 17 of the Wzorzec pliku zbiorczego next to its letter, or the letter alone
when the Wzorzec cannot be read. One sentence says the rules work from the next Przygotowanie and leave finished Pliki
zbiorcze unchanged. Urządzenia lists each component with its other spellings and its group.

## Sub-features

- `reguly-zdania`: the section Reguły ilości has the sentence about the next Przygotowanie, the groups `Gdy Lista Urządzeń zna każdy składnik`, `Gdy jest składnik spoza listy`, `Każde zlecenie`, and one list item per rule of `GET /api/settings/quantity-rules`, each ending with a full stop; the rule of `nokia` names column Z `Montaż ONT`.
- `reguly-bez-wzorca`: with the Wzorzec pliku zbiorczego moved away, the rule of `nokia` ends with the letter `Z` alone.
- `urzadzenia`: the section Urządzenia lists as many components as the server, and `gateway` shows `Też: zyxel` and `Router`.
- `waskie-okno`: at 420×860 both sections show every rule and component without a horizontal scroll.

## How to get to it (user POV)

- The gear in the menu's footer, then `Reguły ilości` or `Urządzenia` in the group Ilości.
- The address `#/ustawienia/reguly-ilosci` or `#/ustawienia/urzadzenia`.

## Driving it with Playwright for Python

Preconditions: Centrum is served for this run with `DOCTOR OK`; the run's `config/` has no Reguły ilości of Dad's, so
the server shows the Reguły ilości z Wydania, and the fixture's Wzorzec pliku zbiorczego has the synthetic price list
(`PRICE_LIST` of `atrapy.scenariusz_centrum`, column Z is `Montaż ONT`).

- **Sentences.** `run.api` reads `/api/settings/quantity-rules` (evidence `api/reguly-ilosci.json`). `open_settings`
  on `Reguły ilości`: the sentence about the next Przygotowanie; the regions are named by the three groups in order; the
  count of their list items equals the server's rules, each ending with `.`; the item with the `nokia` sentence
  contains `Montaż ONT`. Screenshot `350`.
- **Without the Wzorzec.** `move` the Wzorzec pliku zbiorczego beside itself, reopen the section: the `nokia` item reads
  exactly `… w Z.`. Screenshot `351`. The Wzorzec goes back in `finally`.
- **Urządzenia.** `open_settings` on `Urządzenia`: list `Lista Urządzeń` has the server's number of items; item
  `gateway` contains `Też: zyxel` and `Router`. Screenshot `352`.
- **Narrow window.** Viewport 420×860, `goto` `#/ustawienia/reguly-ilosci`, then the combobox to `Urządzenia`: both sections show all items and the page has no horizontal scroll.
  Screenshots `353`, `354`. The viewport goes back to 1440×1000 (also in `finally`).
- **Proof.** Screenshots `350`–`354` and the checks in `drive.txt`.

## Gotchas

- The rules list has no name per item: find a rule by its sentence text.
- The groups are regions, not headings: `open_settings` expects the window's title as its only heading.
- The price list comes from the Wzorzec as Centrum reads it now, so moving the Wzorzec changes the next read without
  a restart.
