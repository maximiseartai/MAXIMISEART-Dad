# Przebieg rozliczeń

Dad continues his week from the Plik zbiorczy that Przygotowanie pliku
zbiorczego published: he fills it in Excel, saves and closes it (Gotowość),
then creates the Rozliczenia pracowników from Centrum without pointing to any
file. The Okres list offers only periods with Status okresu `Plik zbiorczy
przygotowany`; `Podgląd bez zapisu` shows the plan per Wykonawca; `Uruchom`,
confirmed in a dialog, is his confirmation of Gotowość. The live view shows
the Szablony pracowników progress, closing Centrum is refused meanwhile, the
Folder rozliczeń pracowników appears at once, and the Status okresu moves to
`Rozliczenia pracowników gotowe`. The result lists every Rozliczenie
pracownika with the Wykonawca, his orders and `Otwórz`, marks the empty one
`pusty`, and opens the Folder rozliczeń pracowników as its main action. Every
stop and problem has three parts. While the Plik zbiorczy is open in Excel (its lock file `~$…`
next to it), the start card warns, turns off `Uruchom` and keeps `Podgląd bez
zapisu` and the reminder; once the lock file is gone, Dad's return to the
window clears the warning without a reload.

## Sub-features

Printed by `scripts/sub_features.py --feature przebieg-rozliczen` from the drive's steps and checks; refresh the section with it.

- `przebieg-gotowosc`: Gotowość (Excel simulated by the harness): quantities typed into every Wiersz danych, saved and closed.
- `przebieg-wybor-okresu`: only periods with Status Plik zbiorczy przygotowany are offered; the Plik zbiorczy follows from the period.
- `przebieg-plik-zbiorczy-otwarty-w-excelu`.
- `przebieg-wzorzec-pozostawiony-plik-blokady`: only the Wzorzec blocks Uruchom, so the footer does not tell Dad to close the Plik zbiorczy; Nowe Uruchomienie procesu shows the files as they are now, without Dad's return to the window.
- `przebieg-podglad`: Następny krok offers Przebieg rozliczeń once the Wycena w efenix of the period ended OK (harness: its record in the Historia); before it, Uzupełnij and then Wyceń w efenix; the DRY-RUN plans one Rozliczenie pracownika per Wykonawca with his orders, the one without orders empty; the plan names each Wykonawca, his file and orders, marks the empty one, and opens nothing; the DRY-RUN created no Folder rozliczeń pracowników; the DRY-RUN appended one record to the Przebieg rozliczeń metrics file.
- `przebieg-potwierdzenie`: Uruchom asks to confirm the write; the click is Dad's confirmation of Gotowość, and the result card's dialog lists the rows without quantity: ….
- `przebieg-na-zywo`: the live view shows the Szablony pracowników progress from the projection (harness pacing on); the live counters (Wiersze danych, Zapisane szablony) update from the projection during the run; closing Centrum is refused while the Przebieg rozliczeń runs.
- `przebieg-znak-uruchomienia`: on Okresy during the RUN the menu and the header show „Trwa Uruchomienie” (harness pacing on); the header link leads back to the live view; there it is gone.
- `przebieg-zapisane`: the RUN finished OK and lists every written Rozliczenie pracownika, the one without orders empty; the Folder rozliczeń pracowników holds one Rozliczenie pracownika per Wykonawca; no staging folder is left in the Folder okresu: the folder was published at once; both Uruchomienia appended one record each to the process's metrics file, marked as started from Centrum; the Centrum log records the Przebieg rozliczeń with safe facts only; the result lists the Rozliczenia pracowników without a click and marks the empty one pusty.
- `przebieg-otwieranie`: each Otwórz opens exactly its Wykonawca's Rozliczenie pracownika, the main action the folder, one per click; a Wykonawca name leading out of the Folder rozliczeń pracowników is refused and opens nothing.
- `przebieg-odczyt-po-uruchomieniu`: the Historia tab shows the finished RUN and its preview at the top; the period choice is read again: the closed period is no longer offered.
- `przebieg-status-okresu`: the Status okresu is Rozliczenia pracowników gotowe with a Rozliczenie pracownika per Wykonawca.
- `przebieg-nienadpisywanie`: a second RUN of the closed period starts (the Okres list no longer offers it); the stop has three parts and no full path; Nienadpisywanie: the Rozliczenia pracowników are unchanged.
- `przebieg-wymaga-sprawdzenia`: a Wykonawca missing from the Lista Wykonawców gives Wymaga sprawdzenia, not a success; the preview wrote nothing.
- `przebieg-nieznany-wykonawca`: the RUN stops naming the Wykonawca missing from the Lista Wykonawców and Co zrobić starts with column H; Co zrobić sends Dad to no Podgląd bez zapisu for rows: the preview of the same Plik zbiorczy names none; the stopped RUN wrote nothing.

## How to get to it (user POV)

Dad starts it from Okresy: `Podgląd bez zapisu` on the card `Następny krok`, once the last complete period has the
Status okresu `Plik zbiorczy przygotowany` and its last Wycena w efenix ended OK, or the row button `Utwórz
rozliczenia pracowników, okres <token>` of Tablica okresów (beside `Wyceń w efenix` before such a Wycena), which opens
Uruchomienia with the tile `Przebieg rozliczeń` and that period chosen. From the sidebar he goes to `Uruchomienia`
(`#/uruchomienia`), `Nowe Uruchomienie procesu` and the tile `Przebieg rozliczeń`.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature przebieg-rozliczen`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines under
`STEP przebieg-rozliczen` in `drive.txt`, the screenshots of its `Feature` in `scripts/drive/__init__.py`, and
`api/przebieg-*.json`.

## Gotchas

- The counters strip is a description list, not a landmark; find it with `live.locator('dl[aria-label="Liczniki"]')`.
  Its text joins label and value without a space (`Zapisane szablony1`).
- A `POST /api/shutdown` sent after the RUN ends really closes Centrum: keep the pacing on until the refusal and the
  sign on Okresy are recorded; at 2500 ms per Szablon pracownika both fit before the last one ends.
- After the RUN, `06_12_10_2026` leaves the Okres list; the Nienadpisywanie step therefore starts through the API, as
  a second tab or a stale page would.
- `Plan plików` is open after a preview and its file names are plain text, since the files do not exist yet; after a
  RUN table `Rozliczenia pracowników` replaces it.
- The tab drops a repeated click on the same file for 1.5 s after the server's answer, so each `Otwórz` names another
  file.
- The result toast covers the bottom-right corner for a few seconds after a RUN.
- `Uruchom` is also the confirmation dialog's button; scope the second click to the alertdialog.
