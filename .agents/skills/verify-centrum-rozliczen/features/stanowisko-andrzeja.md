# Stanowisko Andrzeja

On Andrzej's laptop the same Centrum rozliczeń starts with the Stanowisko Andrzeja, which Maks writes once at the
installation (`config/stanowisko.txt`, ADR 0045), and without the Wzorce in `config/`. It opens on Uruchomienia with
only the card `Uporządkuj INTERMAX`: the menu has no other page, an address of a page outside his Zakres opens
Uruchomienia, and the page has no tab Historia of the Metryki. The window Ustawienia has only Foldery (the Rejestr
zleceń alone), Kopie INTERMAX, Zgłoszenia, Narzędzie (without the switch of the autostart), Wygląd and Historia.
No page shows a load failure, Centrum answers every read of his pages, and no page names the Stanowisko. Without the
file the computer has Dad's Stanowisko again, with every Function and the start on Okresy.

## Sub-features

Printed by `scripts/sub_features.py --feature stanowisko-andrzeja` from the drive's steps and checks; refresh the section with it.

- `start-bez-wzorcow`: Andrzej's Centrum starts without the Wzorce; its Zakres has only Uporządkowanie and Kopie INTERMAX (…).
- `strona-startowa`: the menu has only Uruchomienia (…); no card of a process with a period; Uruchomienia have no tab Historia of the Metryki; …: the page names no Stanowisko.
- `adres-spoza-zakresu`: each address outside the Zakres opens Uruchomienia.
- `ustawienia`: the window has only the groups of Andrzej's sections (…); the window has only Andrzej's sections (…); Foldery has only the Rejestr zleceń; Narzędzie has no switch of the autostart; …: the page names no Stanowisko.
- `bez-bledow-ladowania`: no page shows a load failure; Centrum answered every read of Andrzej's pages (…).
- `powrot-taty`: Dad's Centrum has every Function (…); Dad's menu starts with Okresy (…).

## How to get to it (user POV)

Andrzej clicks the desktop shortcut „Centrum rozliczeń” that Maks installed with
`py -3 install_centrum_shortcut.py --stanowisko andrzej`; Dad's computer has no such file and nothing to do.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature stanowisko-andrzeja`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/andrzej-zakres.json`, `api/tata-zakres.json`, `api/andrzej-start-server.txt` and `api/tata-start-server.txt`.

## Gotchas

- The Stanowisko is read once at the start, so the drive closes Centrum, writes the file and moves the run's Wzorce
  out of `config/` before it starts Centrum again, and restores both before Dad's start at the end; a run that fails
  in between leaves Andrzej's Stanowisko for the features after it.
- The installation step itself (`--stanowisko andrzej`, only the desktop shortcut) runs only on Windows:
  `tests/test_centrum_launcher.py::test_krok_instalacji_ze_stanowiskiem_andrzeja_zapisuje_je_i_daje_skrot_tylko_na_pulpicie_do_centrum_andrzeja`.
