# Aktualizacja narzędzia

In the window Ustawienia, the section `Narzędzie` (`#/ustawienia/narzedzie`) shows the tool's version, its commit
and the day the tool moved to it, and whether it is the newest (`Aktualna`, `Jest nowsza wersja`, `Nie
sprawdzono`). The section offers `Zaktualizuj narzędzie` only when there is a Wydanie newer than
the tool (`update_offered`, ADR 0014): not when it is current and not without GitHub's answer. The same
button sits in the Diagnoza (`aktualnosc-i-onedrive.md`) and in the section of the
Powiadomienie o nowej wersji (`powiadomienia.md`); there is one
update per Centrum, so while it runs every such button is disabled. Dad clicks
it: the page shows the step while Centrum fetches `main` with the Wydania and moves the tool's
clone forward. When the new
version changes `requirements.txt`, the section shows `Instalowanie bibliotek…`; a
failed installation moves the clone back and the section shows the Komunikat. After
a successful update Centrum closes itself, the restart guardian starts the new
version on the same port, and the tab waits, reloads by itself, and briefly
shows `Zaktualizowano`; a Wydanie the update does not take (a tag that never was the tip of
`main`, ADR 0014) gives `Masz najnowszą wersję.` During
the update a second update and closing Centrum are refused. Without internet
the section shows the Komunikat in three parts („brak połączenia z GitHubem”) with
`Wyślij do Maksa` and its preview, the tool stays as it was, and a second click
once the internet is back updates it. A new version whose Centrum does not
start goes back by itself: the restart guardian moves the clone back and starts
the old version, and the tab reloads on it with the Komunikat „Nowa wersja
narzędzia nie wystartowała.” under the title of whichever page it lands on; a tab opened later, by the
shortcut, shows it on Okresy too, until Dad clicks `Zaktualizuj narzędzie` again.
When the old version finds „ok” in the guardian's result file (the disk refused
the guardian both the removal of „ok” and the write of the failure), it shows
the Komunikat of an unexpected failure, not „Zaktualizowano”, because
the commit it runs is not the one „ok” names (#490). A result the Centrum log
already has does not come back on a later start (#491). A failure in the
result file whose commit before the update is not the commit Centrum runs is
old: the log gets `aktualizacja-wynik-stary` and the section says nothing, so
when the disk lets the guardian neither remove the file of
`NOWA_WERSJA_NIE_WYSTARTOWALA` from A to B nor write „ok” after Dad's next
click, B, which answers, shows no failure (#725).
A Centrum log that cannot be read lets the result through. The drive checks
only „ok” on the old version (`aktualizacja-ok-przy-starej-wersji`); the model of `verify-aktualizacja-narzedzia`
checks the rules, and `tests/test_centrum_aktualizacja.py` checks each:
`test_zgloszony_wynik_nie_wraca_gdy_dysk_nie_pozwala_usunac_jego_pliku` that a reported result does not come back
when the disk keeps its file,
`test_porazka_z_pliku_wyniku_przy_wersji_innej_niz_sprzed_aktualizacji_jest_stara_i_karta_jej_nie_pokazuje` that a
failure of another version is old and the card does not show it,
`test_nowa_dzialajaca_wersja_po_dwoch_odmowach_dysku_nie_pokazuje_porazki_poprzedniej_proby` that the working new
version shows no failure of the try before after two refusals of the disk, and
`test_wynik_aktualizacji_trafia_na_karte_gdy_dziennika_nie_da_sie_przeczytac` that the result reaches the card when
the log cannot be read.
The read of the configuration keeps GitHub's answer about the newest Wydanie (one answer shared with
Powiadomienia) for 10 minutes of Centrum's clock, so each harness change of the Wydanie also moves that clock on. In this run the tool
is the fixture's synthetic clone with a local "origin", and its Centrum is the
run's scripted Centrum, so the restarted Centrum keeps the run-local
boundaries; the verification never touches the checkout it runs from and never
reaches GitHub.

## Sub-features

Printed by `scripts/sub_features.py --feature aktualizacja` from the drive's steps and checks; refresh the section with it.

- `aktualizacja-jest-nowsza`: the run's tool clone stands on the first commit; Dad changed the tracked old Wykonawcy file in the clone; the server reports the clone's commit, the day the clone moved there, a newer version, and offers the update; no Aktualizacja narzędzia since Centrum started.
- `aktualizacja-brak-sieci`: trying again is the main action; `Wyślij do Maksa` is the second action; the server reports the Komunikat in three parts, a retry, and a Zgłoszenie ready to send; the clone stays on the commit Dad had; Dad's changed old Wykonawcy file is still there, still tracked; the Centrum log has the failed update with its code and commit, and no path; the Zgłoszenie has the log's facts, no path and no Git output; without GitHub's answer Ustawienia offer no update; the failed update's Komunikat stays in the card.
- `aktualizacja-postep`: the server reports the step `fetching`; a second Aktualizacja narzędzia is refused while one runs; closing Centrum is refused while the update runs; with the internet back, the double click started exactly one more Aktualizacja narzędzia.
- `aktualizacja-ponowny-start`: the old Centrum closed itself and logged its stop; the closing names the update, not the card.
- `aktualizacja-zaktualizowano`: the tab reloaded by itself; the reloaded tab is back on Ustawienia, section Narzędzie, in the new version; a new Centrum answers on the same address, in the new commit; the new Centrum reports the update's result; the clone moved forward to the origin's newest commit; Dad's files in the tool's config/ keep exactly their content, the changed old Wykonawcy file too; the new version no longer tracks the old Wykonawcy file that Dad still has; the run's configuration directory is untouched; Ustawienia report the new commit as current, since the day of the update, and offers no update; the new Centrum read the guardian's result once and removed it; the Centrum log has the retry's start and end with both commits, and no path; the old Centrum logged its stop, then the new Centrum the end of the update and its start.
- `aktualizacja-najnowsza`: the server reports the newest version; the clone stays on the newest commit; the Centrum log has the update that changed nothing.
- `aktualizacja-instalowanie`: with a newer Wydanie than the one the last update was up to date with, the server forgets that result; the server reports the step `installing`.
- `aktualizacja-instalacja-nieudana`: the server reports the three-part Komunikat of the failed installation, to be tried again; the clone is back on the commit before the click; the new version's requirements left with it; the clone has no changes left; Dad's files in the tool's config/ keep exactly their content, the changed old Wykonawcy file too; the new version no longer tracks the old Wykonawcy file that Dad still has; the run's configuration directory is untouched; the Centrum log has the failed installation with both commits, and no path or pip output.
- `aktualizacja-nie-wystartowala-ponowny-start`: while no Centrum answers, the card says „Ponowne uruchamianie Centrum…” and the update button waits.
- `aktualizacja-nie-wystartowala`: the tab reloaded by itself; the tab reloaded on Uruchomienia, a page with no button of its own, and shows the Komunikat there; `Wyślij do Maksa` is the main action; a new Centrum answers on the same address, in the old version; the old version reports the Komunikat in three parts and a Zgłoszenie to Maks; the guardian moved the clone back to the commit before the click; the clone has no changes left; Dad's files in the tool's config/ keep exactly their content, the changed old Wykonawcy file too; the new version no longer tracks the old Wykonawcy file that Dad still has; the run's configuration directory is untouched; the old version read the result once; the Centrum log has the update and its end in the old version, with both commits and no path; the Centrum before the click logged its stop; only the old version started again, the new one never logged a start; in Ustawienia the same Komunikat stands once, in the section Narzędzie, with the old version.
- `aktualizacja-start-ze-skrotu`: `Wyślij do Maksa` is the main action; a tab the restart did not reload shows the Komunikat under the title of Okresy, where Dad lands.
- `aktualizacja-ok-przy-starej-wersji`: the harness put „ok” back before the old version started; the tab reloaded by itself; the section Narzędzie shows the failure, no `Zaktualizowano`, and the old version; „ok” read by the old version is the unexpected failure, to be tried again; the old version runs; the clone stands on the commit before the click; the old version read the result once; the Centrum log has the update's end as the unexpected failure, with both commits; after the failed installation the tool is up to date on the newest commit; with GitHub's newest Wydanie on the tool's commit, Ustawienia show it current, with no button and no alert; the card no longer says „…”; with GitHub's newest Wydanie on the tool's commit, the server forgets the result about the other Wydanie.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer, section `Narzędzie` (`#/ustawienia/narzedzie`), button `Zaktualizuj narzędzie`.
- Powiadomienia (`#/powiadomienia`), the section `Nowa wersja <x.y.z>` above the list, button `Zaktualizuj narzędzie` (`powiadomienia.md`).
- Uruchomienia, region `Diagnoza`: in the explanation `Jest nowsza wersja narzędzia.` or in the note `Propozycja aktualizacji`, button `Zaktualizuj narzędzie`.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature aktualizacja`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines under
`STEP aktualizacja` in `drive.txt`, the screenshots of its `Feature` in `scripts/drive/__init__.py` and
`api/aktualizacja-*.json`.

## Gotchas

- `main-commit.txt` must go when the feature ends: later features expect `main` to be the tool's own commit. After the update the clone's `HEAD` is the new commit, so leaving the file would still read as current, but it would mask a feature that pins another `main`.
- The clone is moved by real Git on this machine. Its user configuration applies to the update; the fixture's own commits ignore it.
- The restarted Centrum is a new process started by the restart guardian, not by the runner: `server.txt` holds only the first server's console, the new server rewrites `server.json` with its pid, and cleanup stops that one. In `all`, every later feature drives the restarted Centrum.
- The version that does not start is only a `run_centrum.py` that fails at once. With the real launcher, `tests/test_opiekun_ponownego_startu.py::test_nowa_wersja_ktora_nie_wystartuje_wraca_do_starego_commitu_a_stara_startuje_z_komunikatem` checks that a new version that does not start goes back to the old commit and the old one starts with the Komunikat, and `tests/test_opiekun_ponownego_startu.py::test_polecenie_opiekuna_przyjmuje_launcher_kazdej_wersji_jako_start_bez_karty_i_bez_okienek` that the guardian starts it without a tab and without dialogs (`--bez-okienek`).
