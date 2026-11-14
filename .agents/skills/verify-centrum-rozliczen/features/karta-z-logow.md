# Karta z Logów

After Centrum starts again, Uruchomienia shows the card of the last Uruchomienie
procesu from before, restored from its file of Logi Uruchomienia (ADR 0017):
the same headline, Komunikaty, summary and files as before closing, the note
`Ostatnie Uruchomienie · <date> · Centrum było od tego czasu zamknięte`, the
server's next action, `Nowe Uruchomienie procesu` and `Napisz do Maksa o tym
Uruchomieniu`, but no `Diagnoza`. An Urwane Uruchomienie (Centrum died during
it) is named after the next start from `logs/ostatnie-uruchomienie.json`, with
the advice for its mode and `Uruchom ponownie`; an urwana Wycena w efenix gets its Logi at that start, and its card shows the count tiles `Zlecenia przed zamknięciem Centrum` (not driven here). A last Uruchomienie without
Logi whose result is in Historia (Centrum died after the metrics record, before
the Logi, #722) shows that result with a short note instead. A Historia row opens the card
of its Uruchomienie in a side panel, read-only; a row without Logi says the
card is not there. Dad never reads the word Logi.

## Sub-features

Printed by `scripts/sub_features.py --feature karta-z-logow` from the drive's steps and checks; refresh the section with it.

- `karta-po-zamknieciu`: the preview left one file of Logi; …: Dad reads nothing about the Logi; after the start Centrum is without an Uruchomienie and its last one is the card before closing, without Diagnoza and Zgłoszenie; the card's Komunikaty are the Komunikaty of the newest file of Logi, with the link to Ustawienia.
- `karta-bez-szczegolow`: …: Dad reads nothing about the Logi; without its file of Logi the last Uruchomienie shows its result from the Historia row, not an Urwane Uruchomienie.
- `karta-przerwana`: the RUN waits for Dad's Decyzja; after the start the last Uruchomienie is the killed RUN, named after its start; the killed RUN left no file of Logi; the killed RUN left no metrics record; the Centrum log has the start of the killed RUN without its end; Nowe Uruchomienie procesu starts nothing.
- `karta-z-historii`: …: Dad reads nothing about the Logi; the Historia row opens the card of its Uruchomienie, the same as after the start.

## How to get to it (user POV)

Dad starts Centrum with the shortcut and opens Uruchomienia: the last Uruchomienie is there. In Uruchomienia, tab
`Historia`, the button `Karta Uruchomienia` of a row opens its card; Metryki have the same table.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature karta-z-logow`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines under
`STEP karta-z-logow` in `drive.txt`, the screenshots of its `Feature` in `scripts/drive/__init__.py`, `api/karta-*.json`
and `state/` (the Logi and the Centrum log).

## Gotchas

- Unreadable or refused Logi, or no last start, give the setup card after a start instead of the card of the last
  Uruchomienie.
- The file of Logi moved aside in `karta-bez-szczegolow` goes back before the next step without a restart: Centrum
  reads it on each request.
- In `all` the killed server is a successor of the runner's own process, because `aktualizacja` (the restart guardian)
  and `kontrola-ilosci` already restarted Centrum; alone it is the runner's own; cleanup stops whichever `server.json`
  names, and the runner's stop handles a process that is already dead.
- Kill only while the RUN waits for the Decyzja: nothing has been written to the Folder okresu then, so moving the
  folder back restores the fixture.
- The note's date is `started_at` of the file of Logi, which is a few milliseconds before the metrics record's; compare
  the panel with the card, not with the Historia row's date.
