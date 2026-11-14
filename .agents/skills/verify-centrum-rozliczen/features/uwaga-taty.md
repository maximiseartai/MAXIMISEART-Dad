# Uwaga taty

From any view Dad clicks the header icon `Napisz do Maksa` and writes an
Uwaga taty ogólna: a required one-line `Tytuł` and an optional `Treść`. The
figure `Maks dostanie` shows exactly the issue Maks will get, as the server
composed it (`POST /api/dad-notes/draft`), with the tool version under the
text. `Wyślij` puts the Uwaga in the skrzynka queue as its own issue labelled
`uwaga-taty` and waits for the skrzynka up to 5 s: `Uwaga wysłana do Maksa.`
when it took the issue, otherwise what it waits for, with no Komunikat: the
calm `Wyślę do Maksa, gdy będzie internet.`, or, without the Token do Zgłoszeń
or with one the skrzynka refuses, the error icon and `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.`, the one element
the Zgłoszenie and Powiadomienia show too (Q17). A waiting Uwaga goes out with
the next pass of the queue. When the skrzynka rejects its content, the error
icon and `Tej Uwagi nie da się wysłać. Skontaktuj się z Maksem.` promise
nothing; the queue tries it again only at the next start of Centrum. `config/sprawy-taty.json` keeps each Uwaga's title and, once sent,
its issue number.

The Uwaga can also be pinned to one Uruchomienie procesu from Centrum. Under
`Treść`, `Dotyczy` chooses `Ogólna` or `Do Uruchomienia`; the second shows a
radio list `Uruchomienie` of `GET /api/dad-notes/runs` (the newest Centrum
Uruchomienia with a run id, plus the one the dialog was opened from), each with
process, period, `podgląd` or `zapis`, date and result. The finished card on
Uruchomienia and each Historia row of a Centrum Uruchomienie with a run id have
the icon `Napisz do Maksa o tym Uruchomieniu`; it opens the same dialog with
`Do Uruchomienia` chosen and that Uruchomienie checked. The figure is the
server's draft with that `run_id`: its footer names the Uruchomienie and links
to the first comment of its Logi in the skrzynka (`[Logi Uruchomienia](<url>)`).
The figure shows the draft's `shown_body`, with that link as its text only, as GitHub shows it to Maks,
so Dad never sees the address. `config/sprawy-taty.json` keeps the pinned
`run_id`. When the Logi did not reach the skrzynka by the time the Uwaga goes
out, the issue says why instead of linking them: the skrzynka rejected their
content, or they were never in the queue. After rejected Logi the issue gets one
comment with the link once they arrive at a later Centrum start.

## Sub-features

Printed by `scripts/sub_features.py --feature uwaga-taty` from the drive's steps and checks; refresh the section with it.

- `uwaga-ikona`: the skrzynka queue is empty before the first Uwaga; …: the header has „…” left of the bell Powiadomienia.
- `uwaga-puste-okno`: the fields take their limits from the contract (Tytuł 120, Treść 10000); Tytuł shows the prototype's example as its placeholder; with no Tytuł the figure shows the placeholder.
- `uwaga-dlugi-tekst`: the form, its preview and „Wyślij” stay inside the dialog and on screen (…).
- `uwaga-niskie-okno`: at … the fields scroll only with „Maks dostanie” at its caption and first line and „Dotyczy” with the list at its switch and one row (…); at … the fields scroll only in the low window; at …×… (…, motyw …) „Wyślij” is inside the dialog and takes a click, „Dotyczy” clears „Maks dostanie”, and the dialog fits the window (…); the low windows were checked in both themes.
- `uwaga-pelne-okno-lista`: the fixture's metrics files hold at least … runs (…); Centrum keeps its Uruchomienia in config/…; at the full window the list gives up height and „Dotyczy” with it keeps the same share of its height as „Maks dostanie”, as on main (…); at … the fields scroll only with „Maks dostanie” at its caption and first line and „Dotyczy” with the list at its switch and one row (…); at the full window with the list the fields do not scroll; at the full window the fields do not scroll: all of … are on screen (…); at … the fields scroll; at … the checked row scrolled into view is wholly shown (…).
- `uwaga-szkic-po-bledzie`: a failed draft request is asked again without Dad typing; once Centrum answers the draft, „Wyślij” works without Dad typing again, and no Komunikat showed.
- `uwaga-bez-klucza`: the draft holds Dad's text; „Do Uruchomienia” without a checked Uruchomienie keeps Wyślij disabled (no Uruchomienia: the calm sentence); without a key the server says the Uwaga waits for the token (…); the sentence has the error icon; one queue file labelled uwaga-taty holds the issue the figure showed; config/… keeps the Uwaga's title without an issue number; without a key the Centrum log says the Uwaga waits; nothing reached the skrzynka.
- `uwaga-wyslana`: a new opening starts an empty Uwaga; the skrzynka has both Uwagi as uwaga-taty issues, each exactly as its figure showed it; config/… has both issue numbers; the Centrum log has neither the key nor the text of an Uwaga; the key never reaches the browser.
- `uwaga-przycisk-na-karcie`: the finished card has „Napisz do Maksa o tym Uruchomieniu” right of „Nowe Uruchomienie procesu”.
- `uwaga-z-karty`: a new, empty Uwaga; the server offers the Uruchomienie it was opened from; each row shows process, period, podgląd or zapis, date and result, newest first; exactly the Uruchomienie … is checked; the whole dialog fits the window; a long list scrolls inside it.
- `uwaga-przypieta`: the pinned Uwaga carries process, period, mode, result and date of the preview; the pinned Uwaga links [Logi Uruchomienia] to the first comment of the preview's Logi in the skrzynka; „Maks dostanie” shows the link as the words Logi Uruchomienia, without the address.
- `uwaga-ogolna-i-z-powrotem`: the general Uwaga ends with the general footer and has no Logi; each row shows process, period, podgląd or zapis, date and result, newest first; exactly the Uruchomienie … is checked.
- `uwaga-przypieta-wyslana`: the skrzynka has the pinned Uwaga as one uwaga-taty issue, exactly as its figure's draft; its link Logi Uruchomienia leads to the first comment of the preview's Logi; config/… keeps the issue number and the Uruchomienie of the pinned Uwaga.
- `uwaga-z-historii`: only the … rows of Uruchomienia from Centrum with a run id have „Napisz do Maksa o tym Uruchomieniu”; a new, empty Uwaga; the server offers the Uruchomienie it was opened from; each row shows process, period, podgląd or zapis, date and result, newest first; exactly the Uruchomienie … is checked; the whole dialog fits the window; a long list scrolls inside it; at …×… with the draft in „Maks dostanie” the checked oldest row and „Wyślij” are on screen without scrolling (dialog scrollTop …, row …, Wyślij …).
- `uwaga-spoza-historii`: the preview added no record to the read-only metrics file; the server offers other Uruchomienia, but not the preview without a metrics record; each row shows process, period, podgląd or zapis, date and result, newest first; no Uruchomienie is checked (… is not in the list); the sentence „Tego Uruchomienia nie ma w historii Centrum. Wybierz inne albo wyślij Uwagę ogólną.” stands above the list, nothing is checked and Wyślij stays disabled; checking another Uruchomienie keeps the sentence above the list, so the list does not jump; at … the fields scroll only with „Maks dostanie” at its caption and first line and „Dotyczy” with the list at its switch and one row (…); at … the fields scroll; at … the checked row scrolled into view is wholly shown (…).
- `uwaga-logi-odrzucone`: the rejected Logi wait in the queue; a new, empty Uwaga; the server offers the Uruchomienie it was opened from; each row shows process, period, podgląd or zapis, date and result, newest first; exactly the Uruchomienie … is checked; the whole dialog fits the window; a long list scrolls inside it; the draft says the preview's Logi are on their way; the skrzynka has the pinned Uwaga as one new uwaga-taty issue; the sent Uwaga says its Logi did not arrive because the skrzynka rejected them, with the Uruchomienie's id; while the skrzynka rejects the Logi, the Uwaga has no comment.
- `uwaga-odrzucona`: the server says the skrzynka rejected the Uwaga (…); the sentence has the error icon; the rejected Uwaga stays in the queue; the skrzynka got no new Uwaga.
- `uwaga-logi-dotarly`: once the skrzynka takes it, the rejected Uwaga is one issue, exactly as its figure showed it; the preview's Logi reached the skrzynka after the start; the Uwaga's issue got exactly one comment, linking the first comment of the Logi.
- `uwaga-logi-nie-powstaly`: a new, empty Uwaga; the server offers the Uruchomienie it was opened from; each row shows process, period, podgląd or zapis, date and result, newest first; exactly the Uruchomienie … is checked; the whole dialog fits the window; a long list scrolls inside it; the draft says the preview's Logi are on their way; the skrzynka has the pinned Uwaga as one new uwaga-taty issue; the sent Uwaga says its Logi were not made or cannot be sent, with the Uruchomienie's id; an Uwaga whose Logi were never queued gets no comment.

## How to get to it (user POV)

- Any page: the header icon `Napisz do Maksa` (a speech bubble with a plus), left of the bell.
- Uruchomienia, the card of a finished Uruchomienie: the same icon `Napisz do Maksa o tym Uruchomieniu` right of `Nowe Uruchomienie procesu`.
- Uruchomienia, tab Historia (the same table as on Metryki): the icon in the last column of each row of a Centrum Uruchomienie with a run id.
- After `Wyślij`: the answer replaces the form in the same dialog; `Zamknij` (or the corner button, or Escape) closes it, and the next opening starts empty.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature uwaga-taty`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP uwaga-taty` in `drive.txt`, screenshots `160`–`162`, `170`–`179` (with `170b`, `173b`, `174b`, `174c`,
`177b`) and `190`–`200`, and `api/uwaga-*.json`.

## Gotchas

- The figure lags the typed text by one draft request: wait until it equals the server's draft (`until`), never read it right after `fill`.
- The figure is the draft's `shown_body`, the body with the link to the Logi shown as its text; compare it with that field, and check the link itself in the draft's `body` and in the skrzynka issue.
- The `status` holds only the answer sentence; the `Zamknij` button is outside it.
- The rejected Uwaga goes out at the restart of Logi dotarły, before the Uwaga of Logi nie powstały, so `powiadomienia` still finds `NO_LOGS` as the newest Uwaga.
- The Kontrola ilości and the Zgłoszenia of earlier features take skrzynka numbers too; find Uwagi by the label `uwaga-taty`, never by number.
- Uwagi in `config/sprawy-taty.json` hold only titles. The queue file holds the body until the skrzynka takes it, so keep only synthetic text in the drive.
- The pinned figure links the Logi only once the preview's Logi are delivered; with the key written before the preview they go out at its end, so wait for the comment before opening the dialog, otherwise the draft says `Logi Uruchomienia: w drodze (Uruchomienie <run id>)`. The sent issue never says „w drodze”: the queue sends its files oldest first, so the line becomes the link when the skrzynka took the Logi, `Logi Uruchomienia: nie dotarły, Skrzynka odrzuciła ich treść (Uruchomienie <run id>). Odnośnik przyjdzie w komentarzu, gdy dotrą.` when it rejected them, and `Logi Uruchomienia: nie powstały albo nie da się ich wysłać (Uruchomienie <run id>)` when they were not in the queue; after rejected Logi the issue gets one comment with the link once they arrive at a later Centrum start (issue #374). Rejected Logi wait until the next start, so the drive restarts Centrum to see the comment.
- The radio rows have no value in the DOM; match them to the server's list by position and text (process, `<period> · <podgląd|zapis> · <date>` in Dad's time zone, result word) and read `aria-checked`.
- A dialog screenshot taken with `full_page` shows the page below the backdrop past the viewport; capture dialogs with `full_page=False`.
- The key would send later Kontrole ilości and Zgłoszenia at once, and `diagnoza` and `zgloszenie` start without it, so the drive empties its file at the end.
- The laptop check bites only when the list is longer than about four rows: in `all` the oldest row is the seventh, alone with one Centrum Uruchomienie it is one row and the dialog fits anyway.
- A Centrum Uruchomienie missing from the history cannot be reached from Historia (its row is not there), only from the finished card. The drive makes the metrics write fail with a read-only file because `run_process` reports that failure to Dad as a warning and goes on; restore the mode in `finally`, or every later Uruchomienie of the run loses its record.
- The dialog's own box ends at the window, so a `Wyślij` below it is cut off, not missing: check its box against the dialog's and every clipping ancestor's, never only its visibility. Playwright's `click` scrolls a clipped button into view first, so it cannot prove that Dad sees `Wyślij`.
- `Wyślij` is disabled while `Tytuł` is empty, and a disabled button has `pointer-events: none`, so `document.elementFromPoint` passes it by; test visibility by boxes, not by hit testing.
