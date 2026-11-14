# Diagnoza

When an Uruchomienie procesu stops, Centrum tells Dad what kind of stop it is.
A stop Dad fixes himself („dla taty”) offers `Uruchom ponownie`, which starts
the same process for the same period in the same mode. A stop „do Maksa” (the
Komunikat tells him to pass it on, or an ending the process did not stop
itself: an unexpected error or an error after the engine) and the same
Komunikat coming back after `Uruchom ponownie` offer `Diagnoza` instead; after
such an ending the Diagnoza starts by itself. The Diagnoza checks Dad's
computer read-only and explains the cause in three parts; when Dad removes the
cause himself, `Uruchom ponownie` comes first. The server computes the kind of
stop, whether and how to offer the Diagnoza (`diagnosis`: `on_request` or
`automatic`), and the Diagnoza; the browser only shows them. A check that
fails itself (a nieoczekiwany wyjątek inside the Diagnoza) is `nie sprawdzono`
in its place and the rest still runs, so the Diagnoza always ends with an
explanation and `Wyślij do Maksa`. Dad sees nothing more, but Centrum adds each
Diagnoza with a new result to the Logi Uruchomienia of its Uruchomienie: the
file gets the field `diagnosis`, and the queue of the skrzynka Zgłoszeń replaces
the file in the Archiwum Logów okresu and changes the comment of its Uruchomienie
(#840, #844). The same explanation and every check with the
same state, code and (unless it passed) detail is the same result, whatever the
time, so the automatic Diagnoza at every showing of the card adds nothing.

## Sub-features

Printed by `scripts/sub_features.py --feature diagnoza` from the drive's steps and checks; refresh the section with it.

- `diagnoza-dla-taty`: a stop Dad fixes himself is „dla taty”, to fix in the Rejestr zleceń, with his files unchanged; the stop Dad fixes himself is yellow, not a red error; the stop offers Uruchom ponownie and no Diagnoza.
- `diagnoza-powtorka`: the same Komunikat after Uruchom ponownie is a repetition; Uruchom ponownie kept the period and mode; the repeated stop offers Diagnoza instead of Uruchom ponownie.
- `diagnoza-wyjasnienie`: the Diagnoza confirms the stop without repeating it and puts Uruchom ponownie on the banner; the Diagnoza explains the cause Dad removes himself and offers Uruchom ponownie first; the tool is up to date.
- `diagnoza-sprawdzono`: every check is listed in order; the Rejestr zleceń failed; the Diagnoza changed no file and kept the lock file.
- `diagnoza-inny-komunikat`: a different Komunikat after the fix is not a repetition.
- `diagnoza-do-maksa`: a stop that tells Dad to pass it on is „do Maksa”, an error; the stop „do Maksa” stays red and says it does not come from Dad's files; a cause only Maks removes has no Uruchom ponownie; the newer version is only a quiet proposal; the proposal holds `Zaktualizuj narzędzie` as a second action; `Wyślij do Maksa` stays the main one; a newer version does not cover the missing Wzorzec: the Diagnoza explains it and proposes the update.
- `diagnoza-bez-przyczyny`: with every check of the files passing the Diagnoza finds no cause; the missing key failed but is no cause; the Rejestr zleceń and the Wzorce are unchanged; the Centrum log records each Diagnoza with its cause code only.
- `diagnoza-w-logach`: the file of Logi of this Uruchomienie holds its last Diagnoza: the cause code and every check as Dad sees it; without a key the Logi with this Diagnoza wait in the queue as a new version of the one comment of the Uruchomienie, and their file for the Archiwum Logów okresu, in UTF-8 as the queue packs it, is the file byte for byte.
- `diagnoza-nieoczekiwany-wyjatek`: a nieoczekiwany wyjątek is „do Maksa” and its Diagnoza starts by itself; without a click Dad sees the Diagnoza, Wyślij do Maksa and the preview of the Zgłoszenie; the same failure in the Diagnoza leaves only the Rejestr zleceń unchecked; every check is listed; the Centrum log names the exception type and the check, never the text of the exception; the Zgłoszenie carries that log entry for Maks, without the exception text or a workbook row.
- `diagnoza-bez-powtorki`: the same result queues no more Logi: one version for the Uruchomienie and one for its first Diagnoza.
- `diagnoza-nieoczekiwany-wyjatek-zgloszenie`: Wyślij do Maksa works after the nieoczekiwany wyjątek: without a key the preview waits in the queue; the server keeps the queued Zgłoszenie in the result.
- `diagnoza-klucz-odrzucony`: a refused key is a failed check of the Diagnoza, never its explanation.
- `diagnoza-lista-wykonawcow`: a Lista Wykonawców Przygotowanie cannot use runs on the last good list: the stop is the period's, not the list's; the Diagnoza check of the Lista Wykonawców names the bad setting, so tata knows what to fix in Ustawienia.
- `diagnoza-lista-wykonawcow-niedostepna`: a Lista Wykonawców the system refuses to read refuses the start with a sentence, never „niepoprawna”.

## How to get to it (user POV)

When an Uruchomienie procesu on Uruchomienia stops, Dad reads the three-part banner: the yellow `Zatrzymanie do
poprawy` for a stop he fixes himself, the red `Zatrzymanie` for one „do Maksa”. The banner offers `Uruchom ponownie`
or `Diagnoza`, and `Otwórz Rejestr zleceń` when the fix is in the Rejestr zleceń; the Diagnoza shows under it.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature diagnoza`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP diagnoza` in `drive.txt`, screenshots `50`–`59`, `59b` and `59c`, and `api/diagnoza-*.json`.

## Gotchas

- Use a period no other feature fills: in `all`, earlier features put period files into the empty Folder okresu
  `15_21_09_2026`.
- After `Uruchom ponownie` the identical banner text comes back: wait for the server's new Uruchomienie (`run_again`),
  never for the text.
- Restore the Wzorzec by renaming it back, never by copying: the no-change check compares modification times.
- Delete `<root>/github/main-commit.txt` after `diagnoza-do-maksa`: with a newer Wydanie on `main` and no other cause,
  `diagnoza-bez-przyczyny` would read `Jest nowsza wersja narzędzia.`
- A Diagnoza on request lives only in the tab: a reload shows the stop with `Diagnoza` again, which
  `diagnoza-bez-przyczyny` uses.
- Keep the fault hook file `<root>/awaria/odczyt-rejestru` until the end of `diagnoza-bez-powtorki`. Deleted right
  after the start, it lets the Diagnoza read the Rejestr zleceń and hides a Diagnoza that breaks on the same failure;
  deleted during `diagnoza-bez-powtorki`, the Rejestr zleceń passes, which is a new result and rightly one more queued
  Logi.
- `diagnoza-w-logach` reads only the queue: that the file of Logi reaches the Archiwum Logów okresu once a key is there
  is checked by `logi-w-skrzynce` of `logi-uruchomienia` in `all`.
- Compare the saved Zgłoszenie with the preview in the tab; an extra `POST /api/runs/{id}/diagnosis` from the drive
  would replace the preview the button sends.
