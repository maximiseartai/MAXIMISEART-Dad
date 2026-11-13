# Aktualizacja narzędzia

Dad clicks `Zaktualizuj narzędzie` in the window Ustawienia, section Narzędzie. On Windows that is Git for Windows moving the clone under a
running `pythonw.exe`, pip installing the new requirements with that same `pythonw.exe`, the old Centrum closing
itself, and the restart guardian (a detached `pythonw.exe` from its copy) starting the new version without a console;
the tab reloads by itself, still on Ustawienia, and says `Zaktualizowano`. A new version whose Centrum does not start is rolled back: the
guardian moves the clone back and starts the old version, and the tab says `Nowa wersja narzędzia nie wystartowała.`
Dad's `config/` stays byte for byte either way, and no guardian stays behind.

## Sub-features

- `zaktualizowano`: with GitHub's newest Wydanie on `newest`, the click ends within 150 s in the dialog `Zaktualizowano` with `Centrum działa w wersji <newest[:7]>.` in a reloaded tab; `health` has `newest[:7]` and another `instance`; the new port owner is another `pythonw.exe` running `<tool>\run_centrum.py … --bez-okienek` with no window or console; within 60 s nothing else runs from the tool's folder; the clone is on `newest` with no changed tracked file, `config/` has its bytes from before, and neither `centrum-aktualizacja.json` nor `centrum-aktualizacja-w-toku` remains; the log from `aktualizacja-start przed=<first>` has `zamkniecie z=aktualizacja`, `aktualizacja-koniec wynik=ok przed=<first> po=<newest> biblioteki=tak`, the old Centrum's `stop` and then one `start` with `konsola=nie`; list item `Wersja narzędzia` of the reopened section Narzędzie contains `<newest[:7]>`; no `Centrum rozliczeń` message box.
- `nie-wystartowala`: with the newest Wydanie on `not_starting`, the click ends within 150 s in a reloaded tab with the alert `Nowa wersja narzędzia nie wystartowała.` and `Narzędzie działa dalej w poprzedniej wersji. Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”.`, and no `Zaktualizowano`; `health` has `newest[:7]` and another `instance`; the port owner is again a windowless `pythonw.exe` started by the guardian; the clone, `config/` and leftovers are as before; the log has `aktualizacja-koniec wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed=<newest> po=<not_starting> biblioteki=nie` and the old Centrum's `stop` before the next `start`, which has `konsola=nie`; no message box.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer, section `Narzędzie` (`#/ustawienia/narzedzie`), button `Zaktualizuj narzędzie`. (The same button in the Diagnoza runs the same update; `verify-centrum-rozliczen` drives that entry point.)

## Driving it with the Windows harness

Preconditions:

- `start-skrotem` ran: Centrum from the shortcut on `first`, the doctor `DOCTOR OK`. In `all`, `wskazanie-folderow` ran too.
- Centrum's environment rewrites the tool's GitHub address to the run's origin (`windows_tool.boundaries`).

- **Updated.** Record the SHA-256 of every file in `<tool>\config`. Harness: `windows_tool.release(facts, "newest")`. Record `health` and the port owner; open the URL and reload, click link `Ustawienia` (exact), then link `Narzędzie` (heading `Ustawienia/Narzędzie`), wait for `[data-slot=settings-section]` to read `Jest nowsza wersja` (see Gotchas), set `window.przedPonownymStartem = true`, click `Zaktualizuj narzędzie` (exact) in it. Wait for region `Notifications` → dialog `Zaktualizowano`; the marker is gone; capture `zaktualizowano`. Check `health` (`api/health-po-aktualizacji.json`), the process, the guardian's end, the clone, `config/` and the log as in the sub-feature; the reloaded tab has Ustawienia open on Narzędzie again (its address), list item `Wersja narzędzia` contains `<newest[:7]>`; capture `ustawienia-nowa-wersja`.
- **Not starting.** Harness: `release(facts, "not_starting")`. Same path and click in Ustawienia, section Narzędzie. Wait for `alert` with `Nowa wersja narzędzia nie wystartowała.`; the marker is gone; no dialog `Zaktualizowano`; capture `nowa-wersja-nie-wystartowala`. Check `health` (`api/health-po-cofnieciu.json`), the process, the guardian's end, the clone, `config/` and the log. Harness: `release(facts, "newest")`.
- **Doctor.** The runner then writes `doctor-aktualizacja.txt`, which must be `DOCTOR OK` (the clone on `newest`).
- **Proof.** `screenshots/` and `pulpit/` `zaktualizowano`, `ustawienia-nowa-wersja`, `nowa-wersja-nie-wystartowala`; `api/health-po-*.json`; the update's log lines printed in `drive.txt`; `state/git-log.txt`.

## Gotchas

- `newest` changes only a comment in `requirements.txt`: pip runs (so `biblioteki=tak`) and finds every requirement satisfied, so the run needs no index. A failing installation is covered by `verify-centrum-rozliczen` (`aktualizacja-instalacja-nieudana`); upgrading a library whose files the running Centrum holds open is not driven here.
- The card's freshness (`Jest nowsza wersja`, `Aktualna`, `Nie sprawdzono`) comes from the real GitHub API, so after the update the row still reads `Jest nowsza wersja`, and since #319 the button is there only with `Jest nowsza wersja`. The run's clone is made of synthetic commits that never contain a real Wydanie, so the real API names a newer one as long as the real repository has a Wydanie (a `v*` tag on `main`); the drive waits for `Jest nowsza wersja` before each click. Without network, without a real Wydanie, or past GitHub's 60 unauthenticated requests per hour from the runner's address, the card shows `Nie sprawdzono` with no button and the run fails on that wait.
- Without restart pacing the transient statuses (`Pobieranie nowej wersji…`, `Instalowanie bibliotek…`, `Ponowne uruchamianie Centrum…`) can be gone before a check; `verify-centrum-rozliczen` paces them. This feature checks only end states.
- The restarted Centrum is started by the guardian, not by the drive; cleanup still finds it, because its command line contains the run root.
