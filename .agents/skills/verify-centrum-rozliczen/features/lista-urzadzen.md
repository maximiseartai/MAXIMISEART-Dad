# Lista Urządzeń

In the section Urządzenia of the window Ustawienia, Dad edits the Lista Urządzeń himself (ADR 0033, #1479): the pencil
at a component opens its form in place of its row (Nazwa, Inne zapisy with `Dodaj zapis`, Grupa), `Dodaj składnik`
opens an empty one at the end. A spelling saves as the engine reads URZĄDZENIA (lowercase, commas as spaces, no `xg`).
Below the list, `Z ostatnich okresów, spoza listy` shows the spellings of the Wiersze danych without a rule in the last
Pliki zbiorcze that Przebieg rozliczeń settled, with `Dodaj`: a new component or another spelling of one on the list.
A spelling of another component and removing a component a rule needs are refused with one sentence, the second with
that rule's sentence. Each change has its row in Historia as the component's sentence, with „Cofnij”.

## Sub-features

- `lista-urzadzen-podpowiedzi`: the region `Z ostatnich okresów` has two items, one per Wiersz danych with a component
  outside the list (rows 18 and 20), none for the one from the description (row 19); the server says one order each.
- `lista-urzadzen-inny-zapis`: `Zmień gateway`, `Dodaj zapis`, `Nowy Router`, `Zapisz`: the row `gateway` reads
  `Też: zyxel, nowy router`, and so does the server.
- `lista-urzadzen-odmowa`: `zyxel` added to `nokia` gives `Zapis „zyxel” ma już składnik „gateway”. …` at the form;
  `Usuń składnik` of `technicolor` gives `Składnika „technicolor” potrzebuje reguła: Jeśli URZĄDZENIA zawierają
  „technicolor” …`, and the server's list stays.
- `lista-urzadzen-dodaj-podpowiedz`: `Dodaj` of the first suggestion opens `Nowy składnik` with `Dodaj jako` set to
  `Nowy składnik`; `Zapisz` leaves one suggestion and one more component.
- `lista-urzadzen-historia`: the newest row of Historia reads `Lista Urządzeń` and `Dodano: Składnik „…”`, the next one
  `Po: Składnik „gateway”, też „zyxel”, „nowy router”, grupa router.`; „Cofnij” of both brings the list of the Release
  back.
- `lista-urzadzen-nieczytelny-plik`: with the settled Plik zbiorczy not a workbook, the region `Z ostatnich okresów`
  has no item and the sentence `Nie dało się przeczytać Pliku zbiorczego okresu 06_12_10_2026.` (the one of the rule
  preview), and the server says `unread` with that period; at 420×860 too, without a horizontal scroll.
- `lista-urzadzen-waskie-okno`: at 420×860 the form of `gateway` wraps without a horizontal scroll.

## How to get to it (user POV)

- The gear in the menu's footer, then `Urządzenia` in the group Ilości, then the pencil `Zmień <składnik>`,
  `Dodaj składnik`, or `Dodaj` at a suggestion.

## Driving it with Playwright for Python

Preconditions: Centrum is served for this run with `DOCTOR OK`; `przebieg-rozliczen` settled `06_12_10_2026`, whose
Plik zbiorczy has two Wiersze danych with a component outside the Lista Urządzeń (rows 18 and 20) and one from the
description (row 19); run alone (`--feature lista-urzadzen`) the drive runs `przebieg-rozliczen` first. The run's
`config/` has no Lista Urządzeń of Dad's.

- **Suggestions.** `open_settings` on `Urządzenia`; the region `Z ostatnich okresów` has as many items as
  `/api/settings/devices/suggestions` (evidence with the row markers masked): two, one order each. Screenshot `370`
  with the region in view.
- **Other spelling.** The pencil `Zmień gateway`; in the item `Zmiana gateway` `Dodaj zapis`, the textbox `Inny zapis 2`
  `Nowy Router`, `Zapisz`; the item `gateway` contains `Też: zyxel, nowy router`. Screenshot `371`.
- **Refusals.** `Zmień nokia`, `Dodaj zapis`, `Inny zapis 1` `zyxel`, `Zapisz`: the alert of the form has the sentence.
  Screenshot `372`, `Anuluj`. `Zmień technicolor`, `Usuń składnik`: the alert has the rule's sentence; the server's ids
  are those from before. Screenshot `373`, `Anuluj`.
- **Suggestion added.** `Dodaj` of the first suggestion; the item `Nowy składnik` has the combobox `Dodaj jako` with
  `Nowy składnik`; `Zapisz`: the region has one item, the server one suggestion and one more component. Screenshot
  `374` with the region in view.
- **Historia.** `open_settings` on `Historia`: the first item of `Zmiany` has `Lista Urządzeń` and `Dodano: Składnik „`,
  the second the gateway sentence after. Screenshot `375`. `Cofnij: Lista Urządzeń` of the first, then of the third
  item (the gateway change after the new undo row): the server's list equals the one from before.
- **Unreadable Plik zbiorczy.** The harness overwrites the settled Plik zbiorczy with bytes that are not a workbook;
  `open_settings` on `Urządzenia`: the region has the sentence and no item, the server `{"suggestions": [], "unread":
  ["06_12_10_2026"]}`. Screenshot `377`. Viewport 420×860, `goto` `#/ustawienia/urzadzenia`: the region has the
  sentence, no horizontal scroll. Screenshot `378`. In `finally` the viewport goes back and the file gets its bytes
  and modification time back.
- **Narrow window.** Viewport 420×860, `goto` `#/ustawienia/urzadzenia`, the title `Ustawienia/Urządzenia`, the pencil
  `Zmień gateway`: no horizontal scroll. Screenshot `376`. `Anuluj`, then the viewport goes back to 1440×1000 (also in
  `finally`).
- **Proof.** Screenshots `370`–`378` and the checks in `drive.txt`.

## Gotchas

- The suggestions are the synthetic rows' URZĄDZENIA, which carry the fixture's row marker (lowercase, as the engine
  reads it): the drive masks them in the ARIA snapshots and in the saved suggestions, or the self-test fails on the
  marker.
- The drive ends with the Lista Urządzeń of the Release (both changes undone), but `config/lista-urzadzen.yaml` stays
  with its content and Historia keeps every row, so the features after it find the same rows without a rule.
