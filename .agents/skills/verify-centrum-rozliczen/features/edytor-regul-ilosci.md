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

- `edytor-nowa-regula`: „Dodaj regułę” opens „Nowa reguła” whose preview says to choose an action; with the scope
  `Każde zlecenie` and `Wpisz w kolumnę` `Dojazd do klienta (V)` 2, the preview reads the rule `Wpisz 2 w Dojazd do
  klienta V.`, the server's count of changed rows and the Kontrola differences, the row of the server's first
  changed row, and in it `Dojazd do klienta (V) = 3, bo reguły:` with the rule of the Release `Wpisz 1 w Dojazd do
  klienta V.` and the new one.
- `edytor-zla-regula`: an empty value and „Zapisz” give `Wartość musi być liczbą całkowitą od 1 do 999.` at the column,
  and the file of Reguły ilości does not appear.
- `edytor-niezapisany`: Esc with the unsaved rule opens `Zamknąć bez zapisu?`; „Wróć” keeps the form.
- `edytor-zapis`: „Zapisz” returns to the list, where the group `Każde zlecenie` has the new sentence once, the
  server's rules end with `regula-1`, and `config/reguly-ilosci.yaml` exists.
- `edytor-historia`: the newest row of Historia reads `Reguła ilości` and `Dodano: Wpisz 2 w Dojazd do klienta V.`; its
  „Cofnij” adds a row `Usunięto: …` and the server's rules are the ones from before.
- `edytor-waskie-okno`: at 420×860 „Zmień regułę” of `Wpisz 1 w Dojazd do klienta V.` opens „Zmiana reguły” whose
  preview has that sentence and `Żaden wiersz się nie zmieni.`, without a horizontal scroll; „Anuluj” returns to the
  list.

## How to get to it (user POV)

- The gear in the menu's footer, then `Reguły ilości` in the group Ilości, then `Dodaj regułę` or the pencil
  `Zmień regułę` of a rule.

## Driving it with Playwright for Python

Preconditions: Centrum is served for this run with `DOCTOR OK`; `przebieg-rozliczen` settled `06_12_10_2026`, whose
Plik zbiorczy has two Wiersze danych with a component outside the Lista Urządzeń (rows 18 and 20) and one from the
description (row 19); run alone (`--feature edytor-regul-ilosci`) the drive runs `przebieg-rozliczen` first. The run's
`config/` has no Reguły ilości of Dad's, so the server shows the Reguły ilości z Wydania.

- **New rule.** `open_settings` on `Reguły ilości`, `Dodaj regułę`; the region list `Podgląd` contains `Wybierz, co
  reguła ma zrobić`. Choose the comboboxes `Zakres reguły` → `Każde zlecenie`, `Działanie` → `Wpisz w kolumnę`, `Kolumna`
  → `Dojazd do klienta (V)`, fill the spinbutton `Wartość` with 2. The item `Reguła` of `Podgląd` has the sentence. The
  harness asks the server for the same preview (`POST /api/settings/quantity-rules/preview`, evidence
  `api/edytor-podglad.json` with the row texts replaced): ready, with changed rows; the item `Skutek` has `Zmieni się
  <changed> ` and `różnice z Kontroli ilości: <before> → <after>`, and the item `Wiersz <row>` of the server's first
  row has the sum with both rules. Screenshot `360` with that row in view.
- **Bad value.** Empty `Wartość`, `Zapisz`: the item `Kolumna 1` has the alert with the sentence; no
  `config/reguly-ilosci.yaml`. Screenshot `361`. The value goes back to 2.
- **Unsaved.** Esc: the alertdialog has `Zamknąć bez zapisu?`; screenshot `362`; `Wróć` keeps `Nowa reguła`.
- **Save.** `Zapisz`: the region `Każde zlecenie` has one item with the sentence; `/api/settings/quantity-rules` ends
  with `regula-1` after the rules from before; the file exists. Screenshot `363`.
- **Historia.** `open_settings` on `Historia`: the first item of list `Zmiany` has `Reguła ilości` and `Dodano: …`.
  Screenshot `364`. Its `Cofnij: Reguła ilości` adds `Usunięto: …` on top, and the server's rule ids are those from
  before.
- **Narrow window.** Viewport 420×860, `goto` `#/ustawienia/reguly-ilosci`, the button `Zmień regułę` of the item with
  `Wpisz 1 w Dojazd do klienta V.`: `Zmiana reguły`, the preview items `Reguła` and `Skutek`, no horizontal scroll.
  Screenshot `365`. `Anuluj`, then the viewport goes back to 1440×1000 (also in `finally`).
- **Proof.** Screenshots `360`–`365` and the checks in `drive.txt`.

## Gotchas

- The rows of the preview show URZĄDZENIA and CZYNNOŚCI of the synthetic Plik zbiorczy, which carry the fixture's row
  marker: the drive replaces them in the ARIA snapshots and in the saved answer (`_capture`, `_preview`), like
  `uzupelnienie`, or the self-test fails on the marker.
- The preview answers about 400 ms after the last change of the form; expect on its items, never read them at once.
- The drive ends with the rules of the Release (the change undone in Historia), but `config/reguly-ilosci.yaml` stays
  with their content and Historia keeps both rows.
