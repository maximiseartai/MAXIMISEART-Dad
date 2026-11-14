# Powiadomienia

The bell in the header, right of `Napisz do Maksa`, opens the view Powiadomienia
(`#/powiadomienia`), which has no sidebar entry. The view lists Dad's sent Uwagi
taty and Zgłoszenia, newest first, each with its colored tag (`Uwaga`,
`Zgłoszenie`) and state, the same sentence and icon the Uwaga taty dialog and the
Zgłoszenie show (one element, `CaseStateLine`): `Uwaga wysłana do Maksa.` with the send icon, `Wyślę do Maksa, gdy będzie
internet.`, `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.` with the error icon (no token, or one the skrzynka
refuses), `Tej Uwagi nie da się wysłać. Skontaktuj się z Maksem.` with the
error icon (the skrzynka rejected its content; a Zgłoszenie: `Tego Zgłoszenia`), `Rozwiązana. Będzie w następnej wersji.` (Maks closed the issue as
`completed` or without a reason) or `Maks przeczytał.` (`not_planned` or
`duplicate`); a Zgłoszenie reads `Zgłoszenie wysłane do Maksa. Poczekaj na naprawę.` and
takes the neuter form `Rozwiązane. Będzie w następnej wersji.`. A Zgłoszenie is named by its
„Co się stało”, without the code; one recorded before Powiadomienia, without a
„Co się stało”, has no row. A Zgłoszenie that waits in the queue of the
skrzynka reads what it waits for like an Uwaga, and features/zgloszenie.md
checks those rows (`zgloszenie-bez-klucza`, `zgloszenie-odrzucone`), features/uwaga-taty.md
the rejected Uwaga (`uwaga-odrzucona`). Only Maks's states are new: they light a red
dot on the bell. Entering the view marks them read at once (the dot goes out),
and the rows that were new keep a small dot and a light background until Dad
leaves. Centrum asks the skrzynka Zgłoszeń about Dad's open cases at start and
at most once per 10 minutes of its clock, one question per kind of case (label);
no network passes silently with the last known state.

Every Wydanie among the last 30 published (GitHub Releases, no drafts or
pre-releases) up to the newest one on `main` is a
Powiadomienie o nowej wersji `Nowa wersja 0.x.y` with the green tag `Nowa
wersja`: its note under the heading `Co nowego`, with the intro sentence and each `- ` line of the note as a point of a
bulleted list (a note without points stays one paragraph), and the list `Rozwiązane sprawy` with the cases
sent from this computer that it solves (`Uwaga: <tytuł>`, `Zgłoszenie: <Co się
stało>`). The one Centrum offers the update to (`update_offered`, the same rule
as the section Narzędzie of Ustawienia) stands in its own card above the list with `Zaktualizuj
narzędzie`; once Dad is on it, it goes back to the list as history, read and
without the button. Only that card is new and lights the dot; older Wydania
are history. A higher Wydanie from outside `main` is no Powiadomienie.
Centrum asks GitHub for the Wydania with the same rhythm as the skrzynka, one
question for the list of Releases per 10 minutes.

## Sub-features

Printed by `scripts/sub_features.py --feature powiadomienia` from the drive's steps and checks; refresh the section with it.

- `powiadomienia-dzwonek`: …: the bell sits right of „…”; the sent Uwaga is a Powiadomienie, sent and not new; the open Zgłoszenie is a Powiadomienie named by its „Co się stało”, without the code; the unread count is the new Powiadomienia.
- `powiadomienia-zamkniete`: the 10 minutes passed, so Centrum asks once per kind of case; Centrum asked the skrzynka about Dad's open cases; a second read within 10 minutes does not ask the skrzynka again.
- `powiadomienia-oznaczenie-bez-odpowiedzi`: marking the Powiadomienia read without an answer (unreachable, harness) says so in a notification; the Powiadomienia stay new on the server, so the dot on the bell is true.
- `powiadomienia-widok`: the bell opens the view Powiadomienia in the same tab; a new row keeps its light background while Dad stays; config/… keeps them.
- `powiadomienia-po-wyjsciu`.
- `powiadomienia-brak-sieci`: after 10 minutes Centrum asks again.
- `powiadomienia-nowa-wersja`: after 10 minutes Centrum asks GitHub for the Wydania once; the button of a newer Wydanie has no earlier `Masz najnowszą wersję.`; the card stands above the list; the newest Wydanie on `main` offers the update, the older one does not, the one from outside `main` is no Powiadomienie, and entering the view marked both read.
- `powiadomienia-aktualizacja`: the update does not take a Wydanie that never was the tip of `main`, so the tool stays where it is; the clone stays on its commit.
- `powiadomienia-wydanie-aktualne`: a Wydanie Dad is on stays in the history, read, without the button.
- `powiadomienia-wydania-brak-sieci`: after 10 minutes Centrum asks GitHub again; without network the Powiadomienia about Wydania stay as they were, with no Komunikat.
- `powiadomienia-plik-niedostepny`: Centrum learned that Maks closed the Uwaga; a held file is niedostępny, never uszkodzony; while the files are held, Centrum does not pretend it saved them; the next read of Powiadomienia saves both files and the Komunikat is gone; config/… now keeps the Uwaga read; config/… now keeps Maks's closing of the Uwaga; the key is neither in the Centrum log nor in the browser.

## How to get to it (user POV)

- The bell icon `Powiadomienia` in the header of every page, right of `Napisz do Maksa`.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature powiadomienia`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP powiadomienia` in `drive.txt`, screenshots `180`–`189` (with `181b`, `181c`), `201` and `202`, and
`api/powiadomienia-*.json`.

## Gotchas

- Every `GET /api/notifications`, from the tab or from `run.api`, may ask the skrzynka; count questions in the log, not requests.
- The tab reads Powiadomienia on start, on every page change and on focus; the 10-minute limit keeps these from asking again.
- The Zgłoszenie that `zgloszenie` closed has no `state_reason`; Centrum reads it as `completed`, so it may already be new when this feature starts.
- Only the first failed save of a held state file waits for its retries (under a second); later reads try once. Poll the API with a timeout instead of expecting the Komunikat on the first answer: the Komunikat names `powiadomienia.json` only after the tab has marked the closed Uwaga read.
- The Linux lock was never driven: CI drives Centrum on Windows, and root ignores a read-only folder, so there the Komunikat never shows and the step fails.
- Run alone, the clone stands one commit behind the local origin; the Update step first makes the clone's `HEAD` the origin's only Wydanie, so the click never moves the clone.
