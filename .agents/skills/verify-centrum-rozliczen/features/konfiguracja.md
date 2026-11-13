# Konfiguracja

Before a run, Dad sees in the window Ustawienia whether the tool is ready: in the
section Wzorce whether the three Wzorce are in place and pass the engine's
Sprawdzanie, in Wykonawcy which Wykonawcy the konfiguracja wykonawców lists, and
in Narzędzie which version of the tool runs. All three read one configuration
(`GET /api/configuration`) per opening of the window; the view Konfiguracja is gone (ADR 0032). A
problem is a three-part message (what, where, what to do): a missing Wzorzec
(`Brak pliku`) and one that fails the Sprawdzanie or cannot be read
(`Nie przechodzi sprawdzenia`; either Wzorzec of Przygotowanie without access
is `NIEDOSTEPNY_WZORZEC`, not a damaged file) are a Zatrzymanie, a Wzorzec open in
Excel (`Otwarty w Excelu`) an Ostrzeżenie. The section Zgłoszenia says whether the key
to Zgłoszenia is there and whether the skrzynka accepts it (`Gotowe`, `Brak tokenu`, `Token odrzucony`;
driven in `zgloszenie.md`). Centrum never changes the konfiguracja wykonawców, a Wzorzec, or an Excel lock file
from these sections; the section Kopie INTERMAX restores a Kopia (`kopie-intermax.md`).

## Sub-features

- `konfiguracja-gotowa`: all three Wzorce show as ready in Wzorce, the Wykonawcy match the konfiguracja wykonawców in order in Wykonawcy, and `Wersja narzędzia` in Narzędzie names the tool's commit and the day the tool moved to it.
- `konfiguracja-tylko-do-odczytu`: with the tool current Narzędzie has no `Zaktualizuj narzędzie` (it appears only with a newer Wydanie, see `aktualizacja.md`), and the sections Wzorce and Wykonawcy offer no button at all.
- `konfiguracja-wzorzec-otwarty`: an Excel lock file next to the Wzorzec pliku zbiorczego shows `Otwarty w Excelu` with the three-part message in Wzorce; after the lock goes away, a return to the tab shows it ready.
- `konfiguracja-wzorzec-niedostepny`: while the system refuses to read the Wzorzec rozliczenia wewnętrznego, it shows `Nie przechodzi sprawdzenia` with `Nie można teraz odczytać wzorca.`, never `uszkodzony`; once access is back (bytes, size and modification time unchanged), a return to the tab shows it ready without restarting Centrum.
- `konfiguracja-brak-wzorca`: a missing Wzorzec rozliczenia pracownika shows `Brak pliku` with the Przebieg rozliczeń's own stop message, which ends by telling Dad to tell the maintainer.
- `konfiguracja-nieczytelna-konfiguracja-wykonawcow`: a broken Lista Wykonawców replaces the list in Wykonawcy with the three-part message of `ZLA_LISTA_WYKONAWCOW`.
- `konfiguracja-niedostepna-konfiguracja-wykonawcow`: a Lista Wykonawców the system refuses to read replaces the Wykonawcy with the three-part message of `NIEDOSTEPNA_LISTA_WYKONAWCOW`, never `uszkodzona`.
- `konfiguracja-bez-zmian`: after all reads, the konfiguracja wykonawców, the adresy Wykonawców and the Wzorce keep their bytes and modification times.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer, sections Wzorce, Wykonawcy and Narzędzie (`#/ustawienia/wzorce`, …). No settings are needed.
- Returning to the Centrum tab, or reloading it, reads the configuration again.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`. `serve_centrum.py` points the configuration read at `<root>/config`, where `create_centrum_fixture.py` wrote the Lista Wykonawców `wykonawcy.yaml` (Wykonawcy `Wykonawca Testowy A`, `B`, `C`, and `D`, who has no orders, each with a synthetic address `@przyklad.invalid` for Wpisanie raportów) and the three synthetic Wzorce. Dad's real `config/` is never read.

- **Ready.** Open the URL, open Ustawienia on Wzorce (heading `Ustawienia/Wzorce`). `GET /api/configuration` (`api/konfiguracja-gotowa.json`) reports the three Wzorce `ready`, the fixture's Wykonawcy in order, and the version: `commit` is the first 7 characters of the tool clone's commit (`git rev-parse HEAD` in `<root>/aktualizacja/klon`, unless `<root>/github/tool-commit.txt` names another), `since` the day of the clone's last `HEAD` reflog entry (`git log --walk-reflogs -1 --date=short`) when that entry leads to that commit, else `null`. In dialog `Ustawienia` each list item `Wzorzec rozliczenia wewnętrznego` / `Wzorzec pliku zbiorczego` / `Wzorzec rozliczenia pracownika` (exact) holds img `Na miejscu i czytelny` and there is no `alert`; capture `10`. In Wykonawcy list `Wykonawcy` has the same items; in Narzędzie list item `Wersja narzędzia` shows `<commit> od <DD.MM.YYYY>` (`<commit>` without a day).
- **No action.** Narzędzie has no button `Zaktualizuj narzędzie`: the tool is current, so `GET /api/configuration` (`api/konfiguracja-tylko-do-odczytu.json`) has `freshness` `current` and `update_offered` `false`; capture `11`. The section content (`[data-slot=settings-section]`) of Wzorce and of Wykonawcy holds no button. Back to Wzorce.
- **Open in Excel.** Create `<root>/config/~$Wzorzec pliku zbiorczego.xlsx`, reload. List item `Wzorzec pliku zbiorczego` shows `Otwarty w Excelu` with a yellow badge icon (class `text-warning`, the server's `level` `warning`); the alert `Wzorzec jest otwarty w Excelu.` names the file and folder `config` and says to remove the leftover `~$…` file; the API answer has `problem` `open_in_excel` (`api/konfiguracja-wzorzec-otwarty.json`). The lock file still exists. Remove it, dispatch `focus`: the list item shows `Na miejscu i czytelny` again.
- **Wzorzec without access.** Harness, labelled in `drive.txt`: `Wzorzec rozliczenia wewnętrznego.xlsx` gets a modification time 1 s newer, as when OneDrive brings it again, so Centrum does not answer with the ready result it remembers; then the system refuses to read it without changing it (Windows: the drive locks its bytes with `msvcrt.locking`; macOS and Linux: `chmod 0`; always undone). Reload. List item `Wzorzec rozliczenia wewnętrznego` shows `Nie przechodzi sprawdzenia`; the alert `Nie można teraz odczytać wzorca. Plik może być zajęty przez inny program.` names `plik Wzorzec rozliczenia wewnętrznego.xlsx, folder config` and does not contain `uszkodzon`; the API has `problem` `unreadable` (`api/konfiguracja-wzorzec-niedostepny.json`). Screenshot `12a`. Give access back and dispatch `focus`: the list item shows `Na miejscu i czytelny`, there is no `alert`, and the API has the Wzorzec `ready` (`api/konfiguracja-wzorzec-dostepny.json`), without restarting Centrum. Screenshot `12b`. The old modification time comes back at the end of the step (also in `finally`).
- **Missing Wzorzec.** Rename `Wzorzec rozliczenia pracownika.xlsx` aside, reload. The list item shows `Brak pliku` with a red badge icon (class `text-destructive`, `level` `stop`); the alert `Nie można użyć Wzorca rozliczenia pracownika. Nie znaleziono Wzorca rozliczenia pracownika: Wzorzec rozliczenia pracownika.xlsx.` (the Przebieg rozliczeń's stop for this Wzorzec) ends with `W innym wypadku przekaż ten komunikat osobie utrzymującej narzędzie.`; the API has `problem` `missing`. Rename it back.
- **Broken Lista Wykonawców.** Rename `wykonawcy.yaml` aside, write invalid YAML in its place, reload and go to Wykonawcy. The alert `Lista Wykonawców ma złe ustawienie.` (the Diagnoza step of the Lista Wykonawców) says `Plik wykonawcy.yaml w folderze config ma uszkodzoną treść.` and names `Lista Wykonawców w Ustawieniach Centrum`; list `Wykonawcy` is gone; the API has `workers.state` `unreadable`. Delete the broken file and rename the original back.
- **Lista Wykonawców without access.** Harness, labelled in `drive.txt`: the system refuses to read `wykonawcy.yaml` without changing it (Windows: the drive locks its bytes with `msvcrt.locking`; macOS and Linux: `chmod 0`; always undone). Reload. The alert `Nie można teraz odczytać Listy Wykonawców. Plik może być zajęty przez inny program.` (`NIEDOSTEPNA_LISTA_WYKONAWCOW`) names `Lista Wykonawców w Ustawieniach Centrum` and contains neither `uszkodzon` nor `niepoprawn`; list `Wykonawcy` is gone; the API has `workers.state` `unreadable` (`api/konfiguracja-niedostepna-konfiguracja-wykonawcow.json`). Screenshot `14a`.
- **No changes.** Reload and go to Wzorce: all three Wzorce are ready. The snapshot of the five configuration files of `fixture.json` → `configuration` (bytes and `st_mtime_ns`) equals the one taken before the feature, and no `~$*` file is left.
- **Proof.** Screenshots `10`–`14` with `12a`, `12b` and `14a`, `api/konfiguracja-*.json`, and the `konfiguracja-bez-zmian` check in `drive.txt`.

## Gotchas

- Break files only by renaming or adding them and undo by renaming back. Rewriting a file changes its modification time and makes the `konfiguracja-bez-zmian` check meaningless.
- Centrum remembers each Wzorzec's Sprawdzanie result until the file's size or modification time, or its lock file, changes, but only a result that depends on the file's content (ready, unreadable, wrong layout, data in the Wzorzec); a byte-identical copy with the same timestamp would not be re-checked. A Wzorzec that is missing, open in Excel or without access is checked again on every read.
- The worker names are synthetic and appear in evidence on purpose. The Wzorce carry the row marker on a second sheet the Sprawdzanie never reads, so a leak of workbook content still fails the self-test.
- `Wzorzec rozliczenia wewnętrznego` and `Wzorzec rozliczenia pracownika` share a prefix; use `exact=True` for the list items.
