# Zgłoszenie

Under the Diagnoza of a stop „do Maksa” (or a repeated stop) Dad sees the
collapsed `Co zostanie wysłane` with the exact Zgłoszenie and `Wyślij do
Maksa`. One click, without a confirmation dialog, sends the Zgłoszenie to the
skrzynka Zgłoszeń (Maks's private repository on GitHub; here a directory).
Afterwards `Zgłoszenie wysłane do Maksa. Poczekaj na naprawę.` replaces the
button and stays after a reload. One problem has one open Zgłoszenie: the next
Uruchomienie with the same problem shows `Zgłoszenie tego problemu już jest
wysłane i czeka na naprawę.` instead of the button, and after its Diagnoza the
queue adds that Uruchomienie's Zgłoszenie to the open one as a comment
`## Zgłoszenie wróciło`, with no click (ADR 0007); once Maks closed it,
`Wyślij do Maksa` returns after the Diagnoza and the new Zgłoszenie links the
previous one. The click puts the Zgłoszenie into the queue of the skrzynka
(`config/zgloszenia/kolejka/`); without the key, with a refused key, or without
network it waits there and sends itself, with no click, a minute after the
cause is gone. The card says what it waits for: `Zgłoszenie czeka na internet.
Wyśle się samo.` (Powiadomienia: `Wyślę do Maksa, gdy będzie internet.`), or,
without the Token do Zgłoszeń or with one the skrzynka refuses, the error icon
and `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.` there and in Powiadomienia, the one element of Uwaga taty too (Q17).
When the skrzynka rejects the content of the Zgłoszenie, the card and
Powiadomienia say `Tego Zgłoszenia nie da się wysłać. Skontaktuj się z
Maksem.` and promise nothing: the queue tries it again only at the next start.
Only a queue file that cannot be written gives a Komunikat
(`ZGLOSZENIE_NIEZAPISANE`, with `Spróbuj ponownie`). Konfiguracja shows whether
the Token do Zgłoszeń is there and whether the skrzynka accepts it, never its value.

## Sub-features

- `zgloszenie-podglad`: a stop „do Maksa” has `report` `ready`; `Diagnoza` finds no cause and shows `Wyślij do Maksa` with `Co zostanie wysłane`: title `BRAK_WZORCA: …`, the Komunikat code, period, mode, `- Logi: jeszcze niewysłane, Uruchomienie <run id>` (no key yet, so the Logi wait in the queue), tool commit, every check (with `Aktualność narzędzia`), no workbook row and no full path.
- `zgloszenie-bez-klucza`: without `config/zgloszenia-klucz.txt`, `Wyślij do Maksa` turns into the `status` `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.` with no `Ostrzeżenie` (`report` `queued`, `waits_for` `key`); `config/zgloszenia/kolejka/*-zgloszenie-<id>.json` holds exactly the preview, `config/zgloszenia` holds only `kolejka`, the skrzynka stays empty, and Powiadomienia show the Zgłoszenie with the same `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.`.
- `zgloszenie-konfiguracja`: Konfiguracja reads `Zgłoszenia: brak tokenu`, after Maks writes the key (harness step) `Zgłoszenia: gotowe`, with the hook `odmawia-klucza` and another key `Zgłoszenia: token odrzucony` (`reports` `refused_key`), and with the hook gone and a third key `Zgłoszenia: gotowe` again; neither the answers nor the page hold a key.
- `zgloszenie-wyslane`: on Uruchomienia, once Centrum's clock moves a minute on (harness step), the card turns into `Zgłoszenie wysłane do Maksa. Poczekaj na naprawę.` with no click and the queue file is gone; the skrzynka has one issue labelled `zgloszenie`, equal to the preview; `config/sprawy-taty.json` keeps the fingerprint and that issue's number (with the tool's commit, the „Co się stało”, the sending time and, once known, Maks's closing, which Powiadomienia read); the Centrum log has `skrzynka-wyslano etykieta=zgloszenie` and no key.
- `zgloszenie-po-odswiezeniu`: a reload shows the confirmation again (`report` `sent`).
- `zgloszenie-kolejne-uruchomienie`: a new Podgląd bez zapisu with the same stop shows `Zgłoszenie tego problemu już jest wysłane i czeka na naprawę.` at once (`report` `waiting`); after `Diagnoza` it stays (`report` `waiting`), there is no `Wyślij do Maksa`, the skrzynka still has one Zgłoszenie, and with no click that Zgłoszenie gets exactly one comment: `## Zgłoszenie wróciło`, then the whole Zgłoszenie of this Uruchomienie with the same `- Odcisk problemu:` line, its Diagnoza, and `- Logi:` linking the comment of this Uruchomienie's Logi.
- `zgloszenie-zamkniete`: Maks closes that issue (harness step); the same stop again still shows the waiting `status` before the Diagnoza (the skrzynka's last answer in this Centrum); `Diagnoza` asks the skrzynka, the `status` goes, `Wyślij do Maksa` returns (`report` `ready`), and the preview has `- Poprzednie Zgłoszenie: #<its number>` and `- Logi: skrzynka-zgloszen/<n>.json#komentarz-<k>`, the comment of the Logi of this very Uruchomienie in its period's issue (the file skrzynka's address of a comment; GitHub's is the comment's URL).
- `zgloszenie-nowe-z-odnosnikiem`: `Wyślij do Maksa` shows the confirmation; the skrzynka has the first Zgłoszenie closed and a second one open, equal to the new preview; `config/sprawy-taty.json` has both numbers.
- `zgloszenie-inny-problem`: a stop without the Wzorzec pliku zbiorczego (same code, other three parts) has `report` `ready` and, after `Diagnoza`, `Wyślij do Maksa` next to the open second Zgłoszenie; nothing is sent.
- `zgloszenie-bez-sieci`: with the hook `brak-sieci`, `Wyślij do Maksa` shows `Zgłoszenie czeka na internet. Wyśle się samo.` (`report` `queued`, `waits_for` `internet`) and the skrzynka gets nothing; with the hook gone and Centrum's clock a minute on, the card turns into the confirmation with no click and the skrzynka's third Zgłoszenie is exactly the preview.
- `zgloszenie-odrzucone`: Maks closes that third Zgłoszenie and the skrzynka rejects the content of every Zgłoszenie (hook `odrzuca-zgloszenie`); the same stop after `Diagnoza` sends to `Tego Zgłoszenia nie da się wysłać. Skontaktuj się z Maksem.` with the error icon (`report` `rejected`), never `Zgłoszenie czeka na internet. Wyśle się samo.`; the Zgłoszenie stays in the queue, the skrzynka gets nothing, and Powiadomienia show the same sentence.
- `zgloszenie-odrzucone-po-starcie`: with the hook gone, Dad closes Centrum and starts it again: the queue tries the Zgłoszenie again, the skrzynka's fourth Zgłoszenie is exactly the preview, Powiadomienia have it as sent, and no row says it cannot be sent.

## How to get to it (user POV)

- Uruchomienia: a stop with `Diagnoza`; after it, region `Diagnoza` holds `Wyślij do Maksa` and `Co zostanie wysłane`, the confirmation, or the queued `status`.
- Before a Diagnoza (after a reload or in a new Uruchomienie) only the confirmation, the waiting `status`, or the queued `status` is shown under the stop.
- Konfiguracja: the page header reads `Zgłoszenia: gotowe`, `Zgłoszenia: brak tokenu` or `Zgłoszenia: token odrzucony`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`, with the file skrzynka `<root>/skrzynka-zgloszen/` (see `serve_centrum.py`). Run alone, the drive points Centrum to the fixture's folder okresów and Rejestr zleceń itself. The drive empties `config/zgloszenia-klucz.txt` first and at the end (an empty key file is no key for the server, and on Windows it can be emptied while the server reads it).

- **Podgląd.** On `#/uruchomienia` (after `Nowe Uruchomienie procesu` when a result is shown) choose `Przygotowanie pliku zbiorczego` and `wt 08.09 – pon 14.09 · Brak plików okresu · 08_14_09_2026`, rename the Wzorzec rozliczenia wewnętrznego aside, click `Podgląd bez zapisu` (exact), rename it back after the stop. `GET /api/runs/current` has `stop_kind` `for_maks` and `report` `{"state": "ready"}`. Reload, click `Diagnoza` on the stop banner, then button `Co zostanie wysłane` in region `Diagnoza`. Figure `Treść Zgłoszenia` shows the title in its caption and the Markdown body in `pre`.
- **Bez klucza.** Click `Wyślij do Maksa`. A `status` in region `Diagnoza` reads `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.`. The queue file's target title and joined parts are the title and body shown. The header button `Powiadomienia` opens the list, whose item `Zgłoszenie: <Co się stało>` reads the same sentence.
- **Konfiguracja.** Link `Konfiguracja`: text `Zgłoszenia: brak tokenu`. Write the synthetic key to `config/zgloszenia-klucz.txt` (harness: Maks's step), reload and wait for the page's own read of `/api/configuration` (`reload_with_answer`, which may take seconds on Windows CI, #1091): `Zgłoszenia: gotowe`; `api/zgloszenie-konfiguracja.json` has `reports` `ready`. Create `<root>/skrzynka-zgloszen/odmawia-klucza` and write another key, reload: `Zgłoszenia: token odrzucony` (`api/zgloszenie-konfiguracja-odrzucony.json`). Remove the hook, write the first key back, reload: `Zgłoszenia: gotowe` (`api/zgloszenie-konfiguracja-nowy-token.json`).
- **Wysłane.** Link `Uruchomienia`, add a minute to `<root>/zegar/przesuniecie-min.txt` (harness: the queue's retry is due). A `status` reads the confirmation without any click; `api/zgloszenie-skrzynka.json` is the issue in the skrzynka.
- **Po odświeżeniu.** Reload: the same `status`.
- **Kolejne Uruchomienie.** Repeat the Podgląd step: the waiting `status` is there before any Diagnoza. Wait until the Logi of this Uruchomienie left the queue, then `Diagnoza`: no `Wyślij do Maksa`, and the skrzynka file of the Zgłoszenie gets the comment (`api/zgloszenie-skrzynka-powrot.json`).
- **Zamknięte.** Set `"state": "closed"` in `<root>/skrzynka-zgloszen/<number>.json` of the Zgłoszenie (Maks closing it). Repeat the Podgląd step, wait until no `*-logi-uruchomienia-<first 8 of run id>.json` is left in `config/zgloszenia/kolejka/` (the key is there, so the queue sends them), then `Diagnoza`: `Wyślij do Maksa` and `Co zostanie wysłane` with the link line. Click `Wyślij do Maksa`: the confirmation `status`; `api/zgloszenie-skrzynka-nowe.json` holds both issues.
- **Inny problem.** Repeat the Podgląd step with the Wzorzec pliku zbiorczego (`collective_template` in `fixture.json`) renamed aside instead, reload, `Diagnoza`: `Wyślij do Maksa`.
- **Bez sieci.** Open `Co zostanie wysłane`, create `<root>/skrzynka-zgloszen/brak-sieci`, click `Wyślij do Maksa`: the `status` `Zgłoszenie czeka na internet. Wyśle się samo.`. Remove the hook and add a minute to the clock: the confirmation `status` with no click, and the skrzynka's newest Zgłoszenie is the preview.
- **Odrzucone.** Set `"state": "closed"` in the skrzynka file of the newest Zgłoszenie and create `<root>/skrzynka-zgloszen/odrzuca-zgloszenie`. Repeat the Podgląd step with the Wzorzec pliku zbiorczego renamed aside, reload, `Diagnoza`, open `Co zostanie wysłane`, click `Wyślij do Maksa`: the `status` in region `Diagnoza` reads the rejection sentence with one `svg`, and the internet sentence is not there; the result has `report` `{"state": "rejected"}`; the queue holds exactly the preview; still three Zgłoszenia in the skrzynka. Capture `74`. Header button `Powiadomienia`: the row of that problem with the sentence. Capture `74b`. Remove the hook, also in `finally`.
- **Odrzucone po starcie.** Close Centrum from the sidebar and start this run's scripted Centrum again (`kontrola_ilosci._close` and `_start`, console in `api/zgloszenie-start-po-odrzuceniu-server.txt`). Wait until no Zgłoszenie is left in the queue: the skrzynka's fourth Zgłoszenie is the preview. Wait until `GET /api/notifications` (`api/zgloszenie-odrzucone-po-starcie.json`) has `zgloszenie-<its number>-wyslana`; on `#/powiadomienia` no row reads the rejection sentence. Capture `75`.
- **Proof.** Screenshots `60`–`66` (with `61b`, `63b`) and `68`–`75` (with `74b`), `api/zgloszenie-*.json`, and the checks in `drive.txt`. `scripts/check_centrum_zgloszenie_mutations.py` shows the drive fails also when a rejected Zgłoszenie says it waits, when the token sentence promises the internet, and when the return of a problem with an open Zgłoszenie waits for a click.

## Gotchas

- Never point the app at the real GitHub skrzynka: `serve_centrum.py` injects the file skrzynka, and the key is synthetic.
- The preview belongs to the last Diagnoza of the Uruchomienie: a second `POST /api/runs/{id}/diagnosis` from the drive replaces it (its log tail differs), so compare the skrzynka with the preview shown in the tab, not with an extra API Diagnoza.
- `ZGLOSZENIE_NIEZAPISANE` and its `Spróbuj ponownie` (a queue file that cannot be written) only pytest covers; the drive cannot make the queue folder unwritable without breaking the Logi beside it.
- The queue retries a minute after a failed pass on the real clock too, so a slow step may see the Zgłoszenie go out before the clock moves; the steps check the end state, not the moment.
- The skrzynka rejects content only after it took the key, so `zgloszenie-odrzucone` runs with the key written; Centrum remembers the rejection only until it closes, and the next start tries the file again.
- Centrum remembers a refused key for a quarter of an hour, per key: after the hook `odmawia-klucza`, write a different key, never the refused one again.
- Rename the Wzorzec back right after the stop: the Diagnoza must find no cause, and later features need the Wzorzec.
- Before a Diagnoza the waiting `status` comes from the skrzynka's last answer in this Centrum, or from the local sent state when this Centrum has not asked yet; the Centrum asks the skrzynka for the open Zgłoszenie of the problem in the Diagnoza and again when sending, so in this Centrum a closed Zgłoszenie shows only after `Diagnoza`. After a restart, once Powiadomienia have asked the skrzynka and written Maks's closing into the sent state, the same stop shows `report` `ready` before any Diagnoza.
- The file skrzynka finds the open Zgłoszenie by the `- Odcisk problemu:` line of an `open` file; edit only `state` when closing one.
- The Logi line is fixed when the Diagnoza runs, so the preview and the sent Zgłoszenie are the same text: Logi still in the queue at that moment stay `jeszcze niewysłane` in the Zgłoszenie even after they are sent. Wait for the queue before `Diagnoza` when the step needs the link.
- In `all`, the Kontrola ilości of features/kontrola-ilosci.md is the skrzynka's first issue, and the `BLAD_NIEOCZEKIWANY` Zgłoszenie that features/diagnoza.md left in the queue goes out once this feature writes the key, so the Zgłoszenia are not `1.json` and `2.json`. Find them by the label `zgloszenie` and the title `BRAK_WZORCA: …` (`reports`), never by number.
