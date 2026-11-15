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
cause is gone. The card says what it waits for, in the same sentence as Powiadomienia and Uwaga taty: `Wyślę do Maksa, gdy będzie
internet.`, or,
without the Token do Zgłoszeń or with one the skrzynka refuses, the error icon
and `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.` there and in Powiadomienia, the one element of Uwaga taty too (Q17).
When the skrzynka rejects the content of the Zgłoszenie, the card and
Powiadomienia say `Tego Zgłoszenia nie da się wysłać. Skontaktuj się z
Maksem.` and promise nothing: the queue tries it again only at the next start.
Only a queue file that cannot be written gives a Komunikat
(`ZGLOSZENIE_NIEZAPISANE`, with `Spróbuj ponownie`). The section Zgłoszenia of Ustawienia shows whether
the Token do Zgłoszeń is there and whether the skrzynka accepts it, never its value.

## Sub-features

Printed by `scripts/sub_features.py --feature zgloszenie` from the drive's steps and checks; refresh the section with it.

- `zgloszenie-podglad`: the stop without its Wzorzec is „do Maksa”; the stop offers a Zgłoszenie not sent yet; the Zgłoszenie title is the code and „Co się stało”; the preview holds the Komunikat code, the period, and the mode; the preview holds the tool commit and every check of the Diagnoza; the preview holds no workbook row and no full path; without a key the Logi of this Uruchomienie wait in the queue, and the preview says so with its identifier.
- `zgloszenie-bez-klucza`: the queued Zgłoszenie is exactly the preview; the folder zgloszenia holds only the queue, no Markdown file; without a key nothing reaches the skrzynka Zgłoszeń; the server keeps the queued state, waiting for the key, in the result.
- `zgloszenie-konfiguracja`: Ustawienia report the key as ready; the key value never reaches the browser; Ustawienia report the refused key; Ustawienia report the new key as ready.
- `zgloszenie-wyslane`: the skrzynka got exactly the preview, labelled zgloszenie; the local sent state keeps the fingerprint and, once delivered, the issue number; the Centrum log records the sending; the key is neither in the log nor in the Zgłoszenie.
- `zgloszenie-po-odswiezeniu`: the confirmation survives a reload.
- `zgloszenie-kolejne-uruchomienie`: the stop without its Wzorzec is „do Maksa”; the same problem in a new Uruchomienie shows it is already sent and waits for the fix; no second Zgłoszenie of the same problem; the open Zgłoszenie has one comment „Zgłoszenie wróciło” with the whole Zgłoszenie of the returned problem; the Zgłoszenie has one Logi line with the address of a comment in the skrzynka: …; the Zgłoszenie links the comment of the Logi of its own Uruchomienie (…); Dad still sees that the Zgłoszenie waits for the fix.
- `zgloszenie-zamkniete`: the stop without its Wzorzec is „do Maksa”; after the Diagnoza asked the skrzynka, the closed Zgłoszenie lets Dad send again; the new Zgłoszenie links the previous one; the Zgłoszenie has one Logi line with the address of a comment in the skrzynka: …; the Zgłoszenie links the comment of the Logi of its own Uruchomienie (…).
- `zgloszenie-nowe-z-odnosnikiem`: the skrzynka got exactly the new preview as a second Zgłoszenie next to the closed one; the local sent state keeps both Zgłoszenia.
- `zgloszenie-inny-problem`: the stop without its Wzorzec is „do Maksa”; another problem (other three parts) is not waiting for the open Zgłoszenie; asking the skrzynka sends nothing.
- `zgloszenie-bez-sieci`: without network the Zgłoszenie waits in the queue for the internet; without network nothing reaches the skrzynka; once the network is back the Zgłoszenie sends itself, exactly the preview, with no click.
- `zgloszenie-odrzucone`: the stop without its Wzorzec is „do Maksa”; the rejection shows the error icon beside its sentence; the server says the skrzynka rejected the Zgłoszenie, not that it waits for the internet; the rejected Zgłoszenie stays in the queue; the skrzynka got no new Zgłoszenie.
- `zgloszenie-odrzucone-po-starcie`: once the skrzynka takes it, the Zgłoszenie is exactly the preview.

## How to get to it (user POV)

- Uruchomienia: a stop with `Diagnoza`; after it, region `Diagnoza` holds `Wyślij do Maksa` and `Co zostanie wysłane`, the confirmation, or the queued `status`.
- Raporty: a stop „do Maksa” of Wpisanie raportów (e.g. `RAPORTY_HASLO_ODRZUCONE`, an unreadable access file) shows region `Zatrzymanie Wpisania raportów` with the link `Uruchomieniach`, whose card has the same `Diagnoza` and Zgłoszenie; this feature does not drive it, and `tests/test_centrum_wpisanie_raportow.py::test_odrzucone_haslo_to_komunikat_do_maksa_ze_zgloszeniem_a_powtorka_komentarzem_w_otwartym_zgloszeniu` checks that a rejected password is a Komunikat „do Maksa” with a Zgłoszenie and its repeat a comment in the open Zgłoszenie.
- Before a Diagnoza (after a reload or in a new Uruchomienie) only the confirmation, the waiting `status`, or the queued `status` is shown under the stop.
- Ustawienia (gear in the menu's footer), section Zgłoszenia: `Skrzynka Zgłoszeń` reads `Gotowe`, `Brak tokenu` or `Token odrzucony`.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature zgloszenie`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines under
`STEP zgloszenie` in `drive.txt`, the screenshots of its `Feature` in `scripts/drive/__init__.py`, and
`api/zgloszenie-*.json`.

## Gotchas

- The preview belongs to the last Diagnoza of the Uruchomienie: a second `POST /api/runs/{id}/diagnosis` from the drive replaces it (its log tail differs), so compare the skrzynka with the preview shown in the tab, not with an extra API Diagnoza.
- `ZGLOSZENIE_NIEZAPISANE` (a queue file that cannot be written) is not driven: the drive cannot make the queue folder unwritable without breaking the Logi beside it. `tests/test_centrum_zgloszenie.py::test_zgloszenie_ktorego_nie_da_sie_zapisac_w_kolejce_daje_komunikat` checks that such a Zgłoszenie gives the Komunikat.
- The queue retries a minute after a failed pass on the real clock too, so a slow step may see the Zgłoszenie go out before the clock moves; the steps check the end state, not the moment.
- The skrzynka rejects content only after it took the key, so `zgloszenie-odrzucone` runs with the key written; Centrum remembers the rejection only until it closes, and the next start tries the file again.
- Before a Diagnoza the waiting `status` comes from the skrzynka's last answer in this Centrum, or from the local sent state when this Centrum has not asked yet; the Centrum asks the skrzynka for the open Zgłoszenie of the problem in the Diagnoza and again when sending, so in this Centrum a closed Zgłoszenie shows only after `Diagnoza`. After a restart, once Powiadomienia have asked the skrzynka and written Maks's closing into the sent state, the same stop shows `report` `ready` before any Diagnoza.
- The file skrzynka finds the open Zgłoszenie by the `- Odcisk problemu:` line of an `open` file; edit only `state` when closing one.
- The Logi line is fixed when the Diagnoza runs, so the preview and the sent Zgłoszenie are the same text: Logi still in the queue at that moment stay `jeszcze niewysłane` in the Zgłoszenie even after they are sent. Wait for the queue before `Diagnoza` when the step needs the link.
