# Lista Urządzeń

In the section Urządzenia of the window Ustawienia, Dad edits the Lista Urządzeń himself (ADR 0033, #1479): the pencil
at a component opens its form in place of its row (Nazwa, Inne zapisy with `Dodaj zapis`, Grupa), `Dodaj składnik`
opens an empty one at the end. A spelling saves as the engine reads URZĄDZENIA (lowercase, commas as spaces, no `xg`).
Below the list, `Z ostatnich okresów, spoza listy` shows the spellings of the Wiersze danych without a rule in the last
Pliki zbiorcze that Przebieg rozliczeń settled, with `Dodaj`: a new component or another spelling of one on the list.
A spelling of another component and removing a component a rule needs are refused with one sentence, the second with
that rule's sentence. Each change has its row in Historia as the component's sentence, with „Cofnij”.

## Sub-features

Printed by `scripts/sub_features.py --feature lista-urzadzen` from the drive's steps and checks; refresh the section with it.

- `lista-urzadzen-podpowiedzi`: the two Wiersze danych with a component outside the list are two suggestions, the one from the description none.
- `lista-urzadzen-inny-zapis`: „Zapisz” adds the other spelling as the engine reads it.
- `lista-urzadzen-odmowa`: a spelling of another component is one sentence at its field, naming that component; removing a component a rule needs is refused with that rule's sentence, and the list stays.
- `lista-urzadzen-dodaj-podpowiedz`: „Dodaj” and „Zapisz” add the suggestion as a new component, and it leaves the suggestions.
- `lista-urzadzen-historia`: Historia reads each change of the list as the component's sentence before and after; „Cofnij” of both changes in Historia brings the Lista Urządzeń of the Release back.
- `lista-urzadzen-nieczytelny-plik`: a Plik zbiorczy that cannot be read gives no suggestions and one sentence naming its period, as the preview; on a narrow window the sentence wraps without a horizontal scroll.
- `lista-urzadzen-waskie-okno`: on a narrow window the form of a component wraps without a horizontal scroll.

## How to get to it (user POV)

Dad opens Ustawienia with the gear in the menu's footer and chooses `Urządzenia` in the group Ilości. There he clicks
the pencil `Zmień <składnik>`, `Dodaj składnik`, or `Dodaj` at a suggestion. A bookmark of `#/ustawienia/urzadzenia`
opens the section too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature lista-urzadzen`.
Its proof adds `api/urzadzenia-*.json`.

## Gotchas

- The drive ends with the Lista Urządzeń of the Release (both changes undone), but `config/lista-urzadzen.yaml` stays
  with its content and Historia keeps every row, so the features after it find the same rows without a rule.
