# Okno Ustawień

Dad opens Ustawienia with the gear in the menu's footer, right above `Zamknij Centrum rozliczeń`. The window opens
over the blurred Centrum, like the settings of T3 Code (ADR 0032): sections in groups on the left, the path
`Ustawienia / <sekcja>` and ✕ on top. Esc, ✕ and a click on the backdrop close it, and the page under it stays. The
address `#/ustawienia/<sekcja>` opens the window on that section over the current page, and the old address of
Konfiguracja, `#/konfiguracja`, opens Ustawienia. On a narrow browser window it fills the screen and the sections
are a combobox. Okresy, Uruchomienia and Raporty choose no file any more: an unset one is the link
`Ustaw w Ustawieniach` to the section Foldery.

## Sub-features

Printed by `scripts/sub_features.py --feature okno-ustawien` from the drive's steps and checks; refresh the section with it.

- `okno-stopka-menu`: the gear Ustawienia stands in the menu's footer right above „Zamknij Centrum rozliczeń”; the menu has no Konfiguracja.
- `okno-nad-strona`: the gear opens the window at #/ustawienia (…); the groups with a section show in the order of ADR 0032 (…); the sections stand in their groups (…).
- `okno-zamykanie`: … closes the window back to Metryki (…); opening and closing the window leaves Metryki as it was (… reads); after the window is closed, Back goes to Okresy, before Metryki (…).
- `okno-adres-sekcji`: #/ustawienia/wzorce opens the window on Wzorce over Uruchomienia; another section changes the address (…); Back in the browser closes the window instead of going through its sections; a new tab on #/ustawienia/kopie-intermax opens that section over the start page Okresy; an unknown section opens the first one, Foldery.
- `okno-stara-konfiguracja`: … the old address of Konfiguracja opens Ustawienia (…).
- `okno-foldery`: „Ustaw w Ustawieniach” on Okresy opens Foldery (…).
- `okno-linki-do-folderow`: … chooses no file, an unset one links to Foldery (…); a chosen INTERMAX on Raporty shows its name without „Ustaw w Ustawieniach”; a chosen INTERMAX in state … on Raporty links to Foldery.
- `okno-waskie`: on a narrow window Ustawienia fill the screen (…); the combobox goes to the section (…).

## How to get to it (user POV)

Dad clicks the gear `Ustawienia` in the menu's footer, above `Zamknij Centrum rozliczeń`, or `Ustaw w Ustawieniach`
next to an unset file on Okresy, Uruchomienia and Raporty. A bookmark of `#/ustawienia/<sekcja>` or of the old
`#/konfiguracja` opens the window too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature okno-ustawien`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP okno-ustawien` in `drive.txt` and screenshots `300`–`305`.

## Gotchas

- The section `Narzędzie` and its group `Narzędzie` share a name: find the group in the listbox by role `group`.
