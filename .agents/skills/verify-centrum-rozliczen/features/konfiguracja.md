# Konfiguracja

Before a run, Dad sees in the window Ustawienia whether the tool is ready: in the
section Wzorce whether the three Wzorce are in place and pass the engine's
Sprawdzanie, in Wykonawcy which Wykonawcy the Lista Wykonawców lists, and
in Narzędzie which version of the tool runs. Wzorce and Narzędzie read one configuration
(`GET /api/configuration`) per opening of the window, Wykonawcy the Ustawienia (`GET /api/settings`,
`workers`); the view Konfiguracja is gone (ADR 0032). A
problem is a three-part message (what, where, what to do): a missing Wzorzec
(`Brak pliku`) and one that fails the Sprawdzanie or cannot be read
(`Nie przechodzi sprawdzenia`; either Wzorzec of Przygotowanie without access
is `NIEDOSTEPNY_WZORZEC`, not a damaged file) are a Zatrzymanie, a Wzorzec open in
Excel (`Otwarty w Excelu`) an Ostrzeżenie. The section Zgłoszenia says whether the key
to Zgłoszenia is there and whether the skrzynka accepts it (`Gotowe`, `Brak tokenu`, `Token odrzucony`;
driven in `zgloszenie.md`). Centrum never changes a Wzorzec or an Excel lock file
from these sections, and the Lista Wykonawców only through a change of a Wykonawca (`wykonawcy.md`); the section Kopie INTERMAX restores a Kopia (`kopie-intermax.md`).

## Sub-features

Printed by `scripts/sub_features.py --feature konfiguracja` from the drive's steps and checks; refresh the section with it.

- `konfiguracja-gotowa`: the server reports all three Wzorce present and readable; the server lists the Wykonawcy in the order of the Lista Wykonawców, with nothing left to settle; the configuration no longer carries the Wykonawcy: one source, the Ustawienia; the server reports the tool's commit and the day the tool moved there; the section Wykonawcy lists the active Wykonawcy in file order; the section Wykonawcy fits … px without scrolling sideways; the window shows the same Wzorce, Wykonawcy, and version, with no problem.
- `konfiguracja-tylko-do-odczytu`: the section Narzędzie has no `Zaktualizuj narzędzie` for the current tool; the server offers no Aktualizacja narzędzia for the current tool; the section Wzorce offers no action on the Wzorce: Dad changes them in Excel (Wykonawcy: wykonawcy.md).
- `konfiguracja-wzorzec-otwarty`: the server reports the Wzorzec as open in Excel; Centrum leaves Excel's lock file alone; a (simulated) return to the tab shows the Wzorzec ready once Excel has closed it.
- `konfiguracja-wzorzec-niedostepny`: a Wzorzec without access is niedostępny, never uszkodzony; the server reports the Wzorzec as not passing the Sprawdzanie; once access is back, a (simulated) return to the tab shows the Wzorzec ready without restarting Centrum.
- `konfiguracja-brak-wzorca`: the server reports the Wzorzec rozliczenia pracownika as missing.
- `konfiguracja-zla-lista-wykonawcow`: the section Wykonawcy never asks to save Ustawienia as a whole: only a change of a Wykonawca rewrites the list; a broken Lista Wykonawców keeps showing the last good list under the sentence, never an empty good list; the server reports the Lista Wykonawców as bad, with the sentence and the last good list; the section Wykonawcy fits … px without scrolling sideways.
- `konfiguracja-niedostepna-lista-wykonawcow`: a Lista Wykonawców without access is niedostępna, never uszkodzona or niepoprawna; the server reports the Lista Wykonawców as unreadable, with the sentence the section shows.
- `konfiguracja-do-rozstrzygniecia`: the matters stand above the unchanged list, one sentence each; the server gives the two matters with a good list; the section Wykonawcy fits … px without scrolling sideways.
- `konfiguracja-bez-zmian`: the Lista Wykonawców and every Wzorzec keep their bytes and modification times; no lock file is left.

## How to get to it (user POV)

Dad opens Ustawienia with the gear in the menu's footer and chooses the sections Wzorce, Wykonawcy and Narzędzie; no
settings are needed. A bookmark of `#/ustawienia/wzorce` opens the window too, and returning to the Centrum tab, or
reloading it, reads the configuration again.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature konfiguracja`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/konfiguracja-*.json`.

## Gotchas

- The worker names are synthetic and appear in evidence on purpose.
- `Wzorzec rozliczenia wewnętrznego` and `Wzorzec rozliczenia pracownika` share a prefix; use `exact=True` for the list
  items.
