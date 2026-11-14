# Tablica okresów

Okresy shows the Folders okresu from the folder okresów, newest first (which of them at once:
`tablica-skrocona.md`), with its Status okresu, its files, the number of Rozliczenia pracowników, and the
next step. The next step and the Droga okresu (Plik zbiorczy → Uzupełnienie w
Excelu → Wycena w efenix → Rozliczenia pracowników) also follow the period's last
Wycena w efenix in the Historia: a period with a Plik zbiorczy has the next step
Uzupełnij plik zbiorczy until the Historia has its Wycena w efenix, then Wycena w
efenix until one ends OK, with Przebieg rozliczeń reachable beside both. The last complete period is highlighted even without a Folder
okresu, and it is the subject of the `Następny krok` card. Period files and
folders open with one click, for paths the server derived itself; a file gone
since the last read gives the error toast `Nie udało się otworzyć` and the board
is read again. The view follows the disk on every read; a folder okresów or
Folder okresu Centrum cannot read (OneDrive, access rights) gives the Komunikat
`Nie udało się odczytać folderu <name>. …` instead of the board.

## Sub-features

Printed by `scripts/sub_features.py --feature tablica-okresow` from the drive's steps and checks; refresh the section with it.

- `tablica-kolejnosc-i-status`: the server lists every Folder okresu newest first with its Status okresu; the screen shows the same order, Status okresu, and highlighted last complete period; every process step carries its Podgląd bez zapisu hint; Uzupełnienie w Excelu and a closed period have none.
- `tablica-droga-okresu`: Droga okresu has four steps; a closed period without Wycena w efenix shows that step as not done; with a Plik zbiorczy and no Wycena w efenix, the next step is Uzupełnij plik zbiorczy, then Wycena w efenix (no preview), and Przebieg rozliczeń stays reachable beside it; the row of … offers Uzupełnij and, beside it, Wyceń w efenix and Utwórz rozliczenia pracowników; Wyceń w efenix opens a new Uruchomienie with the tile Wycena w efenix and that period chosen.
- `tablica-nastepny-krok`: Następny krok targets the last complete period, whose Folder okresu does not exist.
- `tablica-otwieranie`: one open per click, nothing else; a period file that does not exist cannot be opened.
- `tablica-brakujacy-plik`: hovering the missing Plik zbiorczy shows „jeszcze nie ma”; a click keeps the hint and opens nothing; Tab reaches the missing file's button and shows the same hint; a finger tap shows the hint, a tap beside hides it.
- `tablica-podwojne-klikniecie`: … on … asks the server once (… requests); … opens … once; … shows one Otwieram for … (…); no error toast after the repeated clicks.
- `tablica-zmiana-na-dysku`: after a reload the board shows a Plik zbiorczy added outside Centrum; a (simulated) return to the tab shows a Folder rozliczeń pracowników added outside Centrum.
- `tablica-powrot-z-menu`: back on Okresy from the menu, the board is read again: a Rozliczenie pracownika added meanwhile counts.
- `tablica-odczyt-w-tle-nieudany`: a failed read behind the last board (unreachable server, harness) shows the Komunikat, not the old board; once the server answers, a (simulated) return to the tab shows the board again.
- `tablica-podpowiedz`: Wyceń w efenix, Uzupełnij and Utwórz rozliczenia pracowników in the row explain themselves in tooltips; Podgląd bez zapisu on Następny krok shows the hint the board sent for its period.
- `tablica-ochrona`: an action from a foreign Origin is refused; a request with a foreign Host is refused; a refused request opens nothing.

## How to get to it (user POV)

Dad clicks `Okresy` in the sidebar menu; once the folder okresów is set, it is also the start page (`#/okresy`).
Returning to the Centrum tab, or reloading it, reads the board again.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature tablica-okresow`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP tablica-okresow` in `drive.txt`, screenshots `06`–`09`, `1a`, `17`, `156` and `157`, `api/tablica-*.json`,
`api/odmowa-obcy-*.json` and `state/opened.jsonl`.

## Gotchas

- A tooltip needs a 400 ms hover before it appears; later tooltips open instantly. Wait for the tooltip text, not a
  fixed delay.
- Centrum ignores a repeated open of the same file or folder until 1.5 s after the server's answer, so a step that
  opens one target twice on purpose waits longer between the clicks.
- The toast covers the bottom-right corner for a few seconds; take full-page screenshots after it is gone, or capture
  the viewport on purpose (`07`).
- Okresy keeps the last board of the tab: a step that expects the board read again must wait for the new text, since
  the old board shows first. A reload (`page.goto`) forgets it.
- A missing file's button is `aria-disabled`, not `disabled`: Playwright's `to_be_disabled()` counts it, but `click()`
  and `tap()` wait for an enabled element, so force them.
