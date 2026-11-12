# Układ folderów taty

Dad points the folder okresów at `Załączniki` in OneDrive, where each week sits
in `Rozliczenia {rok}\{miesiąc}\INEA\{okres}` and the month is his billing
cycle (ADR 0006). Okresy finds every Folder okresu across years and months,
shows its Status okresu, and opens its files from the month folder they live in.

## Sub-features

- `taty-tygodnie-ze-wszystkich-miesiecy`: the board lists weeks from the September, October, and November `INEA` folders, newest first; non-period folders are absent.
- `taty-nastepny-krok`: `Następny krok` sees the prepared Plik zbiorczy of the last complete period in the October folder.
- `taty-otwieranie`: `Plik zbiorczy, okres 06_12_10_2026` opens the file inside `10_Październik_2026\INEA`.
- `taty-przywrocenie`: pointing back to the flat `INEA` restores the board the following features expect.

## How to get to it (user POV)

- Okresy, card `Ustawienia`, group `Folder okresów`, button `Zmień` (or `Wskaż folder okresów` on the empty state), choosing `Załączniki`.
- Uruchomienia, `Zmień Folder okresów` in the run setup.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. The fixture's `dad_layout` holds `Załączniki` with `Rozliczenia 2026\09_Wrzesień_2026\INEA\22_28_09_2026` (empty) and `Podpisane`, `10_Październik_2026\INEA\{29_05_10_2026, 06_12_10_2026}` (both period files) and `13_19_10_2026` (empty), `11_Listopad_2026\INEA\27_02_11_2026` (empty), and `Nowe rozliczenia wzór od 01_2026` without `INEA`.

- **Point to Załączniki.** Write the `Załączniki` path to `picker/answer.txt`, click `Zmień Folder okresów` (exact; `Wskaż folder okresów` when no folder is set). The settings file's `folder_okresow` becomes that path.
- **Weeks from every month.** `GET /api/periods` (`api/uklad-taty-tablica.json`) lists `27_02_11_2026`, `13_19_10_2026`, `06_12_10_2026` (collective_file_prepared, last complete), `29_05_10_2026` (collective_file_prepared), `22_28_09_2026`, in that order. Table `Tablica okresów` shows the same tokens; row `06_12_10_2026` shows `Plik zbiorczy przygotowany`.
- **Następny krok.** Region `Następny krok` contains `06_12_10_2026` and heading `Uzupełnij plik zbiorczy` with current step `Uzupełnienie w Excelu` and main button `Uzupełnij`, as the row's last button, and not `Brak Folderu okresu`.
- **Open.** Click `Plik zbiorczy, okres 06_12_10_2026`; the last line of `opened.jsonl` is the file in `10_Październik_2026\INEA\06_12_10_2026`.
- **Restore.** Point back to `INEA` the same way; row `15_21_09_2026` is visible again.
- **Proof.** Screenshots `15`–`16`, `api/uklad-taty-tablica.json`, `state/opened.jsonl`.

## Gotchas

- The settings button's accessible name is the verb plus the label: `Zmień Folder okresów` with a capital F, while the empty state's button is `Wskaż folder okresów`.
- `29_05_10_2026` crosses the month; the fixture puts it in the October folder. Centrum does not decide a period's month: it searches every month folder, so a period in any one month is on the board (a period in two months is shown once, from the first, but opening it or starting an Uruchomienie of it is refused with 409 until Dad leaves it in one month; not driven).
- The step changes the remembered folder okresów; it must restore `INEA` before the next feature, which expects the flat fixture.
