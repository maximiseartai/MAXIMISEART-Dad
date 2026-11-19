# Układ folderów taty

Dad points the folder okresów at `Załączniki` in OneDrive, where each week sits
in `Rozliczenia {rok}\{miesiąc}\INEA\{okres}` and the month is his billing
cycle (ADR 0006). Okresy finds every Folder okresu across years and months,
shows its Status okresu, and opens its files from the month folder they live in.

## Sub-features

Printed by `scripts/sub_features.py --feature uklad-folderow-taty` from the drive's steps and checks; refresh the section with it.

- `taty-wskazany-tydzien`: the server describes the folder okresów as Załączniki of all years; section Foldery shows Załączniki with „wszystkie lata”, not the week Dad pointed to.
- `taty-tygodnie-ze-wszystkich-miesiecy`: the server finds every Folder okresu in Rozliczenia {rok}\{miesiąc}\INEA, newest first; the screen lists the same weeks except the one that has not started; folders that are not periods (Podpisane, Nowe rozliczenia) are absent.
- `taty-nastepny-krok`: Następny krok sees the prepared Plik zbiorczy of the last complete period in its month folder.
- `taty-otwieranie`: one click opens the Plik zbiorczy from the October INEA folder, once.
- `taty-przywrocenie`: pointing back to the flat INEA folder restores the board the next features expect.

## How to get to it (user POV)

Dad opens Ustawienia (the gear in the menu's footer), section Foldery, clicks `Wskaż Folder okresów` (`Zmień Folder okresów` once a folder is set) and chooses
`Załączniki` or any week, `INEA` or month folder inside it.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature uklad-folderow-taty`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/uklad-taty-ustawienia.json`, `api/uklad-taty-tablica.json` and `state/opened.jsonl`.

## Gotchas

- A period in two month folders is shown once, from the first, and opening it or starting an Uruchomienie of it is
  refused with 409 until Dad leaves it in one month; the drive does not drive it.
  `tests/test_centrum_rozliczen.py::test_w_ukladzie_folderow_taty_tydzien_w_dwoch_miesiacach_nie_jest_otwierany` checks
  that the board shows such a period once and that opening its Plik zbiorczy answers 409 naming both month folders and
  opens nothing; no test checks the refused start of an Uruchomienie.
