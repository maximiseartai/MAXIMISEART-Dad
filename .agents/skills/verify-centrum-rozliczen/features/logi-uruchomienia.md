# Logi Uruchomienia

After every Uruchomienie procesu Dad starts in Centrum, Centrum writes one JSON
file of Logi Uruchomienia to `logs/uruchomienia/` next to its log (ADR 0015),
whatever the mode, result and ending. The file says whether it was a `DRY-RUN`
or a `RUN`, carries the card's result, ending, Rodzaj Zatrzymania, summary and
Komunikaty in three parts with their codes, the number of problems, the call trace of a Zatrzymanie, the
Szablony pracowników with their outcome and time, the tool's commit and its Wydanie, and the process's files by
name (with size and whether OneDrive holds them only online). A Przebieg rozliczeń adds how many Ilości tylko dla
INEA it left empty (`inea_only_cleared`, ADR 0018), an Uporządkowanie INTERMAX its Wpisy urządzenia i
czynności INTERMAX (`intermax_entries`, ADR 0019): INTERMAX row numbers and operator names, a Wycena w efenix the
trace of every order (`efenix_orders`, `efenix_stop`), and a Wpisanie raportów its Wpisy, problems and changed cells
(`report_entering`, ADR 0028) without addresses or mail content. The Kopia wejścia (`input_copy`, #841) holds every
file of Dad's the Uruchomienie read, with its fingerprint and the rows it read, without `ADRES` and the Orange number;
for an Uporządkowanie INTERMAX (#842) the pasted rows it ordered, columns A to `UWAGI` without `ADRES` and `NUMER
UMOWY` (a row whose position it did not establish, in `uncertain_rows`, only with the cells allowed shifted and not). Dad sees nothing of it on the
card: no alert, toast or text; only the previews of a Zgłoszenie
(`zgloszenie.md`) and of an Uwaga taty pinned to the Uruchomienie
(`uwaga-taty.md`) carry a line to its Logi. No path reaches the file, and cell content of a Wiersz
danych only through the Kopia wejścia, after the data-rule guard (ADR 0025). The same Logi wait in the queue of the skrzynka
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

Printed by `scripts/sub_features.py --feature logi-uruchomienia` from the drive's steps and checks; refresh the section with it.

- `logi-podglad`: …: exactly one new file in … (…); the Logi name the card's Uruchomienie … and say it was a …; result, ending and Rodzaj Zatrzymania equal the card: …, …, …; the Logi hold the card's … Komunikaty in three parts with their link to Ustawienia, stops before warnings; the summary and the technical notes equal the card; the Logi name the commit of the tool Centrum runs and its Wydanie from the clone's tags (…); the warning keeps its code BRAK_MAPOWANIA, which the card does not show; …: Dad reads nothing about the Logi, on the card or in a toast.
- `logi-zatrzymanie`: …: exactly one new file in … (…); the Logi name the card's Uruchomienie … and say it was a …; result, ending and Rodzaj Zatrzymania equal the card: …, …, …; the Logi hold the card's … Komunikaty in three parts with their link to Ustawienia, stops before warnings; the summary and the technical notes equal the card; the Logi name the commit of the tool Centrum runs and its Wydanie from the clone's tags (…); the Zatrzymanie is one message of kind stop with its code NIEZNANY_WYKONAWCA; …: Dad reads nothing about the Logi, on the card or in a toast.
- `logi-szablony`: the Logi name the card's Uruchomienie … and say it was a …; result, ending and Rodzaj Zatrzymania equal the card: …, …, …; the Logi hold the card's … Komunikaty in three parts with their link to Ustawienia, stops before warnings; the summary and the technical notes equal the card; the Logi of the written Przebieg rozliczeń list every Wykonawca in order with his outcome and rows; each Szablon pracownika has its time; the first, paced … ms (harness), took … ms.
- `logi-kazde-uruchomienie`: each of the … Uruchomienia ended in the Centrum log has its own file of Logi, in the same order; no two files hold the same Uruchomienie.
- `logi-bez-sladu`: …: Dad reads nothing about the Logi, on the card or in a toast; no file of Logi holds a path in the run root or workbook row content; the files of each process are listed by name only.
- `logi-w-skrzynce`: the skrzynka has one issue labelled logi-uruchomienia per period with Uruchomienia: …; each comment ends with the link to its full Logi in the Archiwum Logów okresu; each of the … files of Logi is, unpacked, the file in the Archiwum its comment links, byte for byte; each Uruchomienie is one comment, also after a Diagnoza, which changes that comment and its file; each comment is in the issue of its own period and links the Archiwum of that period; the skrzynka has one Archiwum Logów okresu per period with Uruchomienia and one file per Uruchomienie: …; each comment starts with the summary of its Uruchomienie; the skrzynka has neither the key nor workbook content; …: Dad reads nothing about the Logi, on the card or in a toast.

## How to get to it (user POV)

Dad does nothing for it: he starts Uruchomienia procesu as always, on Uruchomienia or, for Wpisanie raportów, with
`Wpisz raporty z maili` in the header of Raporty (its Logi go to today's period). Maks reads the files in
`logs/uruchomienia/` on Dad's computer.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature logi-uruchomienia`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines under
`STEP logi-uruchomienia` in `drive.txt`, the screenshots of its `Feature` in `scripts/drive/__init__.py`,
`api/logi-*.json`, `api/logi-komentarz.md` and `state/uruchomienia/` (every file of Logi of the run, also checked by the
self-test's evidence hygiene).

## Gotchas

- The files are written before the card shows the result, so read them after the card is finished; a file read while
  the Uruchomienie runs is not there yet.
- File names start with the start time in whole seconds; sort by `started_at` inside the file, not by name, when two
  Uruchomienia start in the same second.
- Logi surviving a restart of Centrum is proved only in `all`: `kontrola-ilosci` restarts Centrum twice after Przebieg
  rozliczeń, so `logi-kazde-uruchomienie` finds the files of the Uruchomienia before those restarts. Alone, the feature
  does not restart; `tests/test_centrum_logi_uruchomienia.py::test_logi_przezywaja_zamkniecie_i_ponowny_start_centrum`
  checks over HTTP that the Logi survive closing and starting Centrum again.
- In `all`, `logi-kazde-uruchomienie` covers every Uruchomienie of the run, the nieoczekiwane wyjątki of `diagnoza`
  too, and `diagnoza` and `zgloszenie` diagnose several Uruchomienia, whose Diagnozy change their comment and replace
  their file in the Archiwum; alone, this feature diagnoses nothing.
- Every Uruchomienie queues its Logi, so before `logi-w-skrzynce` the queue holds Logi of the whole run; in `all`, the
  restart with a key in `kontrola-ilosci` and the key of `zgloszenie` already sent part of them. The check covers both:
  every file is one comment and one file in the Archiwum, wherever it went.
- `tool.commit` is the commit Centrum ran when the Uruchomienie ended. In `all`, `aktualizacja` moves the tool before
  Dad's week, so only the drive's own Uruchomienia are compared with `served_version`, and never with the clone's
  `HEAD`.
- `tool.wydanie` comes from the clone's tags on that commit. Alone, the clone stands on the fixture's first version,
  tagged `v0.0.1` like a README install, so the Logi name `0.0.1`. In `all`, `aktualizacja` withdraws and moves the
  origin's tags, so the Wydanie is whatever the clone's tags say then, possibly none.
