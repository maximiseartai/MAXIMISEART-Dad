# Karta z Logów

After Centrum starts again, Uruchomienia shows the card of the last Uruchomienie
procesu from before, restored from its file of Logi Uruchomienia (ADR 0017):
the same headline, Komunikaty, summary and files as before closing, the note
`Ostatnie Uruchomienie · <date> · Centrum było od tego czasu zamknięte`, the
server's next action, `Nowe Uruchomienie procesu` and `Napisz do Maksa o tym
Uruchomieniu`, but no `Diagnoza`. An Urwane Uruchomienie (Centrum died during
it) is named after the next start from `logs/ostatnie-uruchomienie.json`, with
the advice for its mode and `Uruchom ponownie`. A last Uruchomienie without
Logi whose result is in Historia (Centrum died after the metrics record, before
the Logi, #722) shows that result with a short note instead. A Historia row opens the card
of its Uruchomienie in a side panel, read-only; a row without Logi says the
card is not there. Dad never reads the word Logi.

## Sub-features

- `karta-po-zamknieciu`: a Podgląd bez zapisu of Przebieg rozliczeń for `29_05_10_2026`, then Dad closes Centrum from the sidebar and starts it again; the card comes back equal to the one before closing without `diagnosis` and `report`, its Komunikaty are those of the newest file of Logi, and the page says nothing about the Logi.
- `karta-bez-szczegolow`: the same preview after its file of Logi is gone while Centrum is closed; the card shows the Historia row's result with the note `Centrum zamknęło się tuż po wyniku, więc szczegółów nie ma`, never the Urwane Uruchomienie.
- `karta-przerwana`: a RUN of Przygotowanie pliku zbiorczego for `06_12_10_2026` waits for the incomplete-period Decyzja, Centrum's process is killed and started again; the card names the killed RUN as an Urwane Uruchomienie with the zapis advice and `Uruchom ponownie`, with no new file of Logi, no metrics record and a start without an end in the Centrum log; `Nowe Uruchomienie procesu` starts nothing.
- `karta-z-historii`: the Historia row of the preview opens the side panel with its card from the Logi, without action buttons, equal to `GET /api/runs/{run_id}/card`; a `.cmd` row says `Karty tego Uruchomienia nie ma`.

## How to get to it (user POV)

- Dad starts Centrum with the shortcut and opens Uruchomienia: the last Uruchomienie is there.
- Uruchomienia → tab `Historia` → button `Karta Uruchomienia` in a row (also on Metryki, the same table).

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`; the drive points it to the fixture's files if no feature did (`ensure_files_set`).
- `INEA/29_05_10_2026` has Status okresu `Plik zbiorczy przygotowany`, with a Wykonawca the konfiguracja wykonawców does not know (`fixture.json` → `settlement.needs_check`).
- The Rejestr zleceń ends `06_12_10_2026` on a Saturday, so its RUN asks the incomplete-period Decyzja.

- **Before closing.** `#/uruchomienia` → `Nowe Uruchomienie procesu` → radio `Przebieg rozliczeń` (combobox `Okres` shows `29_05_10_2026`) → `Podgląd bez zapisu`. Label `Wynik` shows `Podgląd wymaga sprawdzenia · nic nie zapisano`; `api/karta-przed-zamknieciem.json`; exactly one new file in `logs/uruchomienia/`. Capture `210`.
- **After closing.** Sidebar `Zamknij Centrum rozliczeń` → `Zamknij Centrum`; harness: `start_centrum` serves this run's Centrum on the same port. Reload `#/uruchomienia`: region `Ostatnie Uruchomienie` has the note with the date of the file's `started_at` (Dad's time zone), label `Wynik` with the same headline, every warning of the card in three parts, `Plan plików (n)`, buttons `Uruchom ponownie`, `Nowe Uruchomienie procesu`, `Napisz do Maksa o tym Uruchomieniu`, and no `Diagnoza`. `api/karta-po-starcie.json` is `{"state": "idle", "previous": {"state": "restored", …}}` with `run`, `phases` (the card's `progress.phases`), `started_at` (the file's) and `result` (the card's without `diagnosis`, `report`, `files_unchanged`, `opens` and `order_notes`, which the Logi do not hold); its `stops` then `warnings` are the file's `messages` in three parts. Capture `211`.
- **Without the Logi.** Read the preview's Historia row from `api/karta-historia-podgladu.json`. Close Centrum from the sidebar again; harness: the preview's file of Logi is moved to `<root>/odlozone/` (the files Centrum finds after dying between the metrics record and the Logi; ADR 0017) and back at the end, then `start_centrum`. Reload: region `Ostatnie Uruchomienie` has `Ostatnie Uruchomienie · <date of the Historia row> · Centrum zamknęło się tuż po wyniku, więc szczegółów nie ma`, label `Wynik` with the same headline, buttons `Uruchom ponownie`, `Nowe Uruchomienie procesu` and `Napisz do Maksa o tym Uruchomieniu`, no `Ostrzeżenie` and nothing about the Logi. `api/karta-bez-szczegolow.json` is `{"state": "idle", "previous": {"state": "recorded", …}}` with the preview's `run`, the Historia row's `started_at`, and `result`, `headline` and `next_action` of the card before closing. Capture `211b`. The file goes back before the next step; Centrum reads it on each request, so no restart is needed.
- **Killed mid-run.** Harness: when `INEA/06_12_10_2026` exists (`all`, after Przygotowanie), it is moved to `<root>/odlozone/` and back at the end. `Nowe Uruchomienie procesu` → radio `Przygotowanie pliku zbiorczego` (combobox `Okres` shows `06_12_10_2026`) → `Uruchom` → alertdialog `Uruchomić z zapisem?` → `Uruchom`; alertdialog `Kontynuować mimo niepełnego okresu?` is open and `api/karta-decyzja.json` is `awaiting_decision`. Harness: `kill_centrum` kills the server through the pid in `server.json`, then `start_centrum`. Reload: region `Ostatnie Uruchomienie` has `Ostatnie Uruchomienie · <date> · Centrum zamknęło się w trakcie`, label `Ostrzeżenie` with `Centrum rozliczeń zamknęło się w trakcie tego Uruchomienia, więc nie ma jego wyniku.`, `Przygotowanie pliku zbiorczego, okres 06_12_10_2026` and the zapis advice, the badge `Z zapisem`, button `Uruchom ponownie`, and no `Napisz do Maksa o tym Uruchomieniu`. `api/karta-przerwana.json` has `previous.state` `interrupted` with the killed `run` and the `started_at` of `logs/ostatnie-uruchomienie.json`. No new file in `logs/uruchomienia/`, as many metrics records as before, and one more `uruchomienie-start` than `uruchomienie-koniec` in the Centrum log. Capture `212`. `Nowe Uruchomienie procesu` shows the radio `Przygotowanie pliku zbiorczego` and the server stays `idle`.
- **Historia.** Tab `Historia` → the newest row (the preview) → button `Karta Uruchomienia` → the dialog (side panel) has `Uruchomienie z <date>`, label `Wynik` with the same headline, and no `Uruchom`, `Uruchom ponownie`, `Nowe Uruchomienie procesu` or `Folder okresu`. `api/karta-historia.json` (`GET /api/runs/{run_id}/card`) equals the card after the start. Capture `213`. Escape; `Pokaż starsze` until it is gone; the first `.cmd` row → `Karta Uruchomienia` → `Karty tego Uruchomienia nie ma` and `Wystartowało spoza Centrum rozliczeń albo jego wynik nie został zachowany.` Capture `214`.
- **Proof.** Screenshots `210`–`214` and `211b`, `api/karta-*.json`, `state/` (the Logi and the Centrum log), checks in `drive.txt`.

## Gotchas

- After any start of Centrum, Uruchomienia opens on the card of the last Uruchomienie, not on the setup card. Recipes that click `Nowe Uruchomienie procesu` first keep working, because that card has the same button.
- In `all` the killed server is a successor of the runner's own process, because `aktualizacja` (the restart guardian) and `kontrola-ilosci` already restarted Centrum; alone it is the runner's own; cleanup stops whichever `server.json` names, and the runner's stop handles a process that is already dead.
- Kill only while the RUN waits for the Decyzja: nothing has been written to the Folder okresu then, so moving the folder back restores the fixture.
- The note's date is `started_at` of the file of Logi, which is a few milliseconds before the metrics record's; compare the panel with the card, not with the Historia row's date.
