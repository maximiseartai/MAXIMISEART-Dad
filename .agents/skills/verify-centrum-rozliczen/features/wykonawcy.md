# Wykonawcy

Dad keeps the Lista Wykonawców himself in the section Wykonawcy of the window Ustawienia (ADR 0032): he adds a
Wykonawca with the login from INTERMAX, the name of his Rozliczenie pracownika and addresses, changes a Wykonawca with
`Edytuj` and `Zapisz` (name, addresses, a second login), switches Przypomnienia o raporcie and Nieaktywny at once, and
removes a Wykonawca whose login no period has. A saved login has no text field: it can only go (×) or get a second one
beside it. Each rule is the server's: a bad value comes back as a sentence at its field, a Wykonawca or login with
orders in the Rejestr zleceń or a Plik zbiorczy stays with a sentence that proposes Nieaktywny, and a new name while a
Rozliczenie pracownika with the old one lies in a period asks first. Closing Ustawienia with an unsaved form asks
`Zamknąć bez zapisu?`. Under the list the section suggests the logins of the ordered orders of the current period and
the 4 before it in the Rejestr zleceń that no Wykonawca has, each with `Dodaj Wykonawcę`, and says in one sentence when
the Rejestr is not set or cannot be read (#1475), or when the file of the Lista Wykonawców cannot be read; then a
change of the list is refused too. The drive does not drive the file of Ustawienia that cannot be read
now, the Historia row of a change or what the processes do with the list:
`tests/test_centrum_rozliczen.py::test_odczyty_okna_centrum_przy_pliku_ustawien_bez_odczytu_odmawiaja_zdaniem_o_nim`
checks that the suggestions then say a sentence about that file instead of „wskaż Rejestr zleceń”,
`tests/test_centrum_rozliczen.py::test_kazda_zmiana_wykonawcy_ma_wiersz_historii_a_zgloszenie_nie_ma_loginu_nazwy_ani_adresu`
checks that every change of a Wykonawca has its Historia row and that the Zgłoszenie has no login, name or address,
`tests/test_centrum_rozliczen.py::test_proces_bez_dobrej_listy_wykonawcow_nie_startuje_a_odmowa_mowi_co_poprawic` that
a process without a good Lista Wykonawców does not start and its refusal says what to fix, and
`tests/test_centrum_wpisanie_raportow.py::test_nieaktywny_i_bez_przypomnien_z_ustawien_nie_dostaja_przypomnienia_od_nastepnego_sprawdzenia`
that a Nieaktywny Wykonawca and one without Przypomnienia get none from the next check.

## Sub-features

Printed by `scripts/sub_features.py --feature wykonawcy` from the drive's steps and checks; refresh the section with it.

- `wykonawcy-podpowiedz`: the login of today's order that no Wykonawca has is the one suggestion, with its number of orders; on a narrow window the suggestion fits without a horizontal scroll.
- `wykonawcy-dodanie-z-podpowiedzi`: the suggestion opens the form and saves nothing before Zapisz; after Zapisz the Wykonawca is on the list and the suggestion is gone.
- `wykonawcy-rejestr-nieczytelny`: a Rejestr zleceń that cannot be read is a sentence in the section, not an empty list of suggestions.
- `wykonawcy-dodanie`: the new Wykonawca is on the list, active and with Przypomnienia o raporcie; the Lista Wykonawców file has the new login.
- `wykonawcy-odmowa-przy-polu`: an address of another Wykonawca is not saved.
- `wykonawcy-zamkniecie-bez-zapisu`: closing Ustawienia with an unsaved form asks first, and Wróć keeps what Dad typed.
- `wykonawcy-stara-nazwa`: nothing is saved before Dad confirms; the Rozliczenie pracownika with the old name stays as it was: Centrum renames none of Dad's files.
- `wykonawcy-odmowa-usuniecia`: a Wykonawca with orders in the Rejestr zleceń stays.
- `wykonawcy-przelaczniki`: the Nieaktywny Wykonawca stands below the active ones (…).
- `wykonawcy-waskie-okno`: on a narrow window the form fits without a horizontal scroll.
- `wykonawcy-usuniecie-i-powrot`: a Wykonawca whose login no period has is removed.

## How to get to it (user POV)

Dad opens Ustawienia with the gear in the menu's footer and chooses the section Wykonawcy; a bookmark of
`#/ustawienia/wykonawcy` opens it too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wykonawcy`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/wykonawcy-*.json`.

## Gotchas

- A suggestion's button is named `Dodaj Wykonawcę: <login>`, so `Dodaj Wykonawcę` alone stays the one under the list.
- Removal checks every Plik zbiorczy of the folder okresów, so the button shows `Sprawdzam okresy…` until the server
  answers; wait for the list item or the alert, never a fixed time.
- The window Ustawienia is a modal: `Zamknąć bez zapisu?` and `Zmienić nazwę?` are alertdialogs above it, found on the
  page, not inside the window.
