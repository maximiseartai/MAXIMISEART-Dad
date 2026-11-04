# Logi Uruchomienia

After every Uruchomienie procesu Dad starts in Centrum, Centrum writes one JSON
file of Logi Uruchomienia to `logs/uruchomienia/` next to its log (ADR 0015),
whatever the mode, result and ending. The file says whether it was a `podgląd`
or a `zapis`, carries the card's result, ending, Rodzaj Zatrzymania, summary and
Komunikaty in three parts with their codes, the number of problems, the call trace of a Zatrzymanie, the
Szablony pracowników with their outcome and time, the tool's commit and its Wydanie, and the process's files by
name (with size and whether OneDrive holds them only online). A Przebieg rozliczeń adds how many Ilości tylko dla
INEA it left empty (`inea_only_cleared`, ADR 0018), and an Uporządkowanie INTERMAX its Wpisy urządzenia i
czynności INTERMAX (`intermax_entries`, ADR 0019): INTERMAX row numbers and operator names, no other row content. Dad sees nothing of it on the
card: no alert, toast or text; only the previews of a Zgłoszenie
(`zgloszenie.md`) and of an Uwaga taty pinned to the Uruchomienie
(`uwaga-taty.md`) carry a line to its Logi. No path and no cell content
of a Wiersz danych reach the file. The same Logi wait in the queue of the skrzynka
Zgłoszeń (`config/zgloszenia/kolejka/`, like the Kontrola ilości) and go to the
period's issue labelled `logi-uruchomienia`, which they keep using after Maks
closes it, one comment per Uruchomienie: a summary ending with the link to its
full Logi in the Archiwum Logów okresu (#844), the GitHub Release `logi-<period>`
of the skrzynka's repository, which holds the file under its own name plus `.gz`.
Each Diagnoza with a new result (features/diagnoza.md) of the last Uruchomienie of this Centrum
rewrites the file with its `diagnosis`, replaces it in the Archiwum and changes the
comment of its Uruchomienie, so its file in the Archiwum is always the file; a Diagnoza of
an Uruchomienie from before a restart of Centrum adds nothing.

## Sub-features

- `logi-podglad`: a Podgląd bez zapisu of Przebieg rozliczeń for `29_05_10_2026` adds exactly one file with `mode: "podgląd"`; `run_id`, `result`, `ending`, `stop_kind`, `summary` and `technical_notes` equal the card, its one message is the card's warning in three parts with kind `warning` and code `BRAK_MAPOWANIA`, and `tool` names the commit Centrum runs and the Wydanie the clone's tags give it.
- `logi-zatrzymanie`: a RUN of the same period stops „dla taty” and adds exactly one file with `mode: "zapis"`, equal to the card, whose one message is the card's Zatrzymanie with kind `stop` and code `NIEZNANY_WYKONAWCA`.
- `logi-szablony`: the file of the written Przebieg rozliczeń of `06_12_10_2026` (the card `przebieg-rozliczen` recorded) lists every Wykonawca in order with outcome `ZAPISANO` (`PUSTY_SZABLON` for the one without orders), its rows and its time; the first Szablon pracownika, paced by the harness, took at least the pacing.
- `logi-kazde-uruchomienie`: every `uruchomienie-koniec` line of the Centrum log has exactly one file with the same process, mode, period, result and ending, in the same order, and no Uruchomienie has two.
- `logi-bez-sladu`: Uruchomienia, also after a reload, shows nothing about the Logi; no file holds a path in the run root or the fixture's row marker; the process's files are names only.
- `logi-w-skrzynce`: with a key, one more Podgląd bez zapisu wakes the queue and no Logi wait in it any more; the skrzynka has one issue labelled `logi-uruchomienia` and one Archiwum Logów okresu per period with Uruchomienia, and every file of Logi of the run is, unpacked, the file in the Archiwum that the one comment of its Uruchomienie in its period's issue links, character for character; every comment starts with the summary; every Uruchomienie has exactly one comment and one file, also a diagnosed one, whose Diagnoza changed both; neither the key nor the row marker is in the skrzynka; Dad reads nothing about it.

## How to get to it (user POV)

- None: Dad starts Uruchomienia procesu as always. Maks reads the files in `logs/uruchomienia/` on Dad's computer.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`.
- `przebieg-rozliczen` ran in this run (`api/przebieg-zapisane.json` exists). Run alone (`--feature logi-uruchomienia`), the drive runs it first, with its Przygotowanie pliku zbiorczego.
- `INEA/29_05_10_2026` still has Status okresu `Plik zbiorczy przygotowany`, with a Wykonawca the konfiguracja wykonawców does not know (`fixture.json` → `settlement.needs_check`).

- **Files of Logi.** The drive reads `<root>/logs/uruchomienia/*.json` before and after each Uruchomienie; exactly one name is new.
- **Preview.** `#/uruchomienia` → button `Nowe Uruchomienie procesu` → radio `Przebieg rozliczeń` (combobox `Okres` shows `29_05_10_2026`) → button `Podgląd bez zapisu`. Label `Wynik` shows `Podgląd wymaga sprawdzenia · nic nie zapisano`; `GET /api/runs/current` is `api/logi-podglad.json`. The new file has the card's `run.id`, `process`, `period`, `mode: "podgląd"`, the result's `result`, `ending`, `stop_kind`, `summary`, `technical_notes`, its `stops` then `warnings` as `messages` (`kind` `stop`/`warning`, the same `what`, `where`, `action`), codes `[warning BRAK_MAPOWANIA]`, and `tool` `{"wydanie": <the highest Wydanie whose tag in the clone, in `refs/tags/` or `refs/wydania/`, points at that commit, as `0.0.1`; `null` without one>, "commit": <the commit Centrum runs>}`. The page text has no `Logi`, `Logów`, `Logach`, `Logami` or `uruchomienia/`. Capture `160`.
- **Zatrzymanie.** The same choice, then button `Uruchom` and the alertdialog `Uruchomić z zapisem?` → `Uruchom`. Label `Zatrzymanie` shows `W Pliku zbiorczym jest WYKONAWCA`; `api/logi-zatrzymanie.json`. The new file equals the card with `mode: "zapis"`, codes `[stop NIEZNANY_WYKONAWCA]`, and the same `tool`. Capture `161`.
- **Szablony pracowników.** The file whose `run_id` is the `run.id` of `api/przebieg-zapisane.json` equals that card (its `tool` aside) and has `templates` `[(wykonawca, "ZAPISANO" or "PUSTY_SZABLON" when rows is 0, rows)]` for `fixture.json` → `workers` and `settlement.rows_per_worker`, each with an integer `duration_ms`, the first ≥ the Szablony pacing of `przebieg-rozliczen` (2500 ms).
- **Every Uruchomienie.** The `uruchomienie-koniec` lines of `logs/centrum-rozliczen.log` (`tryb` `DRY-RUN` is `podgląd`, `RUN` is `zapis`) equal the files sorted by `started_at`, and every `run_id` is unique. In `all` this covers every Uruchomienie of the run, with the unexpected exceptions of `diagnoza`.
- **No trace.** Reload `#/uruchomienia`: label `Zatrzymanie` is visible and the page text says nothing about the Logi. No file contains the run root or `CENTRUM-SYN-ROW`; every `environment.files[].name` has no `/` or `\`.
- **Skrzynka.** Harness: Maks writes `config/zgloszenia-klucz.txt`. The same Podgląd bez zapisu as above (`api/logi-skrzynka-podglad.json`); within 60 s no `*-logi-uruchomienia-*.json` is left in `config/zgloszenia/kolejka/`. In `<root>/skrzynka-zgloszen/` the issues labelled `logi-uruchomienia` have titles `Logi Uruchomienia <period>` and first lines `- Logi Uruchomienia okresu: <period>`, one per period of the files. Each comment ends with `- Pełne Logi: [<name>](https://github.com/<repository>/releases/download/logi-<period>/<name>)`; `<root>/skrzynka-archiwum/logi-<period>/<name>` unpacked with gzip, grouped by `run_id`, is the file of that Uruchomienie (one comment and one file per Uruchomienie, also after Diagnozy), each in its period's issue and Archiwum; `<root>/skrzynka-archiwum/archiwa.json` lists one Archiwum per period and one file per file of Logi; every comment starts with `**Logi Uruchomienia**: `. The drive removes the key. `api/logi-skrzynka.json` lists the issues; `api/logi-komentarz.md` is the comment of this Podgląd. Capture `162`.
- **Proof.** Screenshots `160`–`162`, `api/logi-*.json`, `api/logi-komentarz.md`, `state/uruchomienia/` (every file of Logi of the run, also checked by the self-test's evidence hygiene), checks in `drive.txt`.

## Gotchas

- The files are written before the card shows the result, so read them after the card is finished; a file read while the Uruchomienie runs is not there yet.
- File names start with the start time in whole seconds; sort by `started_at` inside the file, not by name, when two Uruchomienia start in the same second.
- The card's Komunikaty have no code; only the file has it, so the drive checks codes against the messages it knows for these runs.
- Logi surviving a restart of Centrum is proved only in `all`: `kontrola-ilosci` restarts Centrum twice after Przebieg rozliczeń, so `logi-kazde-uruchomienie` finds the files of the Uruchomienia before those restarts. Alone, the feature does not restart; `tests/test_centrum_logi_uruchomienia.py` covers it over HTTP.
- In `all`, `diagnoza` and `zgloszenie` diagnose several Uruchomienia, whose Diagnozy change their comment and replace their file in the Archiwum; alone, this feature diagnoses nothing.
- Every Uruchomienie queues its Logi, so before `logi-w-skrzynce` the queue holds Logi of the whole run; in `all`, the restart with a key in `kontrola-ilosci` and the key of `zgloszenie` already sent part of them. The check covers both: every file is one comment and one file in the Archiwum, wherever it went.
- `tool.commit` is the commit Centrum ran when the Uruchomienie ended. In `all`, `aktualizacja` moves the tool before Dad's week, so only the drive's own Uruchomienia are compared with `served_version`, and never with the clone's `HEAD`.
- `tool.wydanie` comes from the clone's tags on that commit. Alone, the clone stands on the fixture's first version, tagged `v0.0.1` like a README install, so the Logi name `0.0.1`. In `all`, `aktualizacja` withdraws and moves the origin's tags, so the Wydanie is whatever the clone's tags say then, possibly none.
