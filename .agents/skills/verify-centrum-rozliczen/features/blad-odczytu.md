# Błąd odczytu

Every page that reads from the server shows a failed read the same way: the
alert `Nie udało się odczytać <what>` with the Komunikat and the button
`Spróbuj ponownie`. The button reads once more; a successful read replaces the
alert with the page, a re-read on its way makes the button wait with a spinner,
and a second failure keeps the alert and gives the button back. One shared
component draws it (`frontend/src/components/load-failure.tsx`), so a page
without it is a dead end this feature catches. A page with several reads
(Okresy: Ustawienia Centrum, the board, the key numbers) shows one alert, and its
button reads every failed one again. The card `Uporządkuj INTERMAX`
(`/api/intermax`, `Nie udało się odczytać Uporządkowania INTERMAX`, and its `dni INTERMAX`), the card `Kopie INTERMAX`
(`/api/intermax/copies`), the side panel `karty Uruchomienia` and Raporty (`/api/report-entering/view`,
`Raportów`, and apart from it `/api/report-entering`, `Wpisania raportów`, under the header button) use the same
component, but this feature does not drive their failed reads.

## Sub-features

Printed by `scripts/sub_features.py --feature blad-odczytu` from the drive's steps and checks; refresh the section with it.

- `blad-odczytu-ustawienia`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-tablica`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-okresy-jednym-kliknieciem`: three failed reads of Okresy show one „Nie udało się odczytać okresów”; one Spróbuj ponownie reads settings, periods and metrics again; the board and the key numbers are back (read …).
- `blad-odczytu-uruchomienia`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-historia`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-metryki`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-konfiguracja`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-ponowna-porazka`: the re-read is on its way (held, harness): Spróbuj ponownie keeps its name and the focus, waits with a spinner, and a second Enter reads nothing; a re-read that fails again keeps the Komunikat and gives the button back, still in focus; the next try reads Ustawienia.
- `blad-odczytu-aktualizacja`: a failed read of Aktualizacja narzędzia (unreachable, harness) says so in the section Narzędzie; the next entry reads Aktualizacja narzędzia and the sentence is gone.
- `blad-odczytu-powiadomienia`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-uwaga`: a failed read of … (unreachable server, harness) shows „Nie udało się odczytać …” with Spróbuj ponownie; Spróbuj ponownie reads … again and its content replaces the Komunikat.
- `blad-odczytu-uzupelnienie`: a failed read of … (unreachable, harness) shows „Nie udało się odczytać okresu”, and with the live re-read paused (hidden tab, harness) Spróbuj ponownie reads again (… read(s) on their way); once Centrum answers, the page replaces the Komunikat.
- `blad-odczytu-uzupelnienie-rodzaj`: a failed read of … (unreachable, harness) shows „Nie udało się odczytać okresu”, and with the live re-read paused (hidden tab, harness) Spróbuj ponownie reads again (… read(s) on their way); once Centrum answers, the page replaces the Komunikat.
- `blad-odczytu-strumien`: a stream event outside the contract (harness) shows „Podgląd przestał się aktualizować” on Uruchomienia; with the stream readable again the page starts as usual.

## How to get to it (user POV)

- Any page of the sidebar, the bell `Powiadomienia`, or the dialog `Napisz do Maksa`, while Centrum does not answer (a stopped server, a busy laptop). Dad sees the alert in place of the page and presses `Spróbuj ponownie` once Centrum answers again.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature blad-odczytu`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines under
`STEP blad-odczytu` in `drive.txt` and the screenshots of its `Feature` in `scripts/drive/__init__.py`.

## Gotchas

- `/api/metrics` is read on Okresy as well (its key numbers): leaving the route on while passing through Okresy fails
  that read too, which is harmless and not checked.
- Powiadomienia mark new rows read on entry, which reads them once more after the click; the step counts at least one
  read, not exactly one.
