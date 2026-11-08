# Kontrola ilości

After every Przebieg rozliczeń RUN that Centrum shows as finished, Centrum
sends a Kontrola ilości to the skrzynka Zgłoszeń by itself (ADR 0013). Dad
sees nothing of it: no Komunikat, no file among his unsent Zgłoszenia, no
wait. Without a key or network the Kontrola waits as a JSON file in
`config/zgloszenia/kolejka/`, and Centrum sends it again at its next start, in
the background, so the start does not wait for the skrzynka, with every
later post to the queue (the Logi of the next Uruchomienie, an Uwaga taty), and
by itself a minute after a pass that stopped for no network or key, skipped an
unreadable file, or found another Centrum's pass on the folder (`RETRY_S`). The
queue sends its files oldest first, so the Logi of the same RUN, queued before
it, go first. A failure that every later file would meet (no key, no network,
refused key) stops the pass; content the skrzynka rejects stays in the queue,
and the pass goes on to the next file. Each period has one Kontrola issue:
a later RUN comments on the open one, and after Maks closes it the next one
opens a new issue.

## Sub-features

- `kontrola-w-kolejce`: the RUN of `06_12_10_2026` from `przebieg-rozliczen`, without a key, left one queue file labelled `kontrola-ilosci` for that period; the Centrum log says `skrzynka-w-kolejce etykieta=kontrola-ilosci okres=06_12_10_2026` and `skrzynka-czeka … przyczyna=brak-klucza` (for the first file of the queue, usually Logi Uruchomienia); `config/zgloszenia` holds only `kolejka`; Uruchomienia shows no alert and nothing about the skrzynka.
- `kontrola-bez-sieci-po-starcie`: with the key written and no network, Dad closes Centrum and starts it again; the start tries the queue again (`przyczyna=brak-sieci`, for its first file), the Kontrola's file stays, the skrzynka gets nothing, and Okresy shows no alert.
- `kontrola-wyslana-po-starcie`: with network back and a slow skrzynka, the next start shows Okresy before the skrzynka took the Kontrola; then the skrzynka has one issue labelled `kontrola-ilosci` titled `Kontrola ilości 06_12_10_2026: …` whose first line is `- Kontrola ilości okresu: 06_12_10_2026` and which names the queued Uruchomienie, the queue file is gone, and neither the key nor workbook content is in the Centrum log.

## How to get to it (user POV)

- Dad never sees it. He runs Przebieg rozliczeń with `Uruchom` (features/przebieg-rozliczen.md), closes Centrum with `Zamknij Centrum rozliczeń`, and starts it again from the desktop shortcut.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`.
- The RUN of `06_12_10_2026` from `przebieg-rozliczen` ended `Rozliczenia pracowników gotowe` without a key in `config/zgloszenia-klucz.txt`, so its Kontrola ilości waits in `config/zgloszenia/kolejka/`. Run alone (`--feature kontrola-ilosci`), the drive runs `przebieg-rozliczen` first.
- The skrzynka Zgłoszeń is `<root>/skrzynka-zgloszen/` (`serve_centrum.py`): unreachable while `brak-sieci` exists there, and slow by the milliseconds in `<root>/pacing/skrzynka-ms.txt` while that file exists.

- **In the queue.** Read the one `*-kontrola-ilosci-*.json` in `config/zgloszenia/kolejka/` (the Logi Uruchomienia of every Uruchomienie wait there in their own files): `target.label` is `kontrola-ilosci`, `period` is `06_12_10_2026`. The Centrum log has `skrzynka-w-kolejce etykieta=kontrola-ilosci okres=06_12_10_2026` and a `skrzynka-czeka … przyczyna=brak-klucza` line, labelled after the first file of the queue (usually `logi-uruchomienia`: the first failure ends the pass). `config/zgloszenia` lists only `kolejka`. On `#/uruchomienia` there is no `alert` and the page never says `skrzynka`. Capture `150`.
- **No network at the next start.** The harness writes the key and creates `skrzynka-zgloszen/brak-sieci`. Dad clicks `Zamknij Centrum rozliczeń`, then `Zamknij Centrum` in the dialog, and sees heading `Centrum rozliczeń jest zamknięte`; `/api/health` stops answering. The harness starts `serve_centrum.py` with the same root and port, as the shortcut would start Dad's Centrum; its console goes to `api/kontrola-start-bez-sieci-server.txt`. The log gets `skrzynka-czeka … przyczyna=brak-sieci` (for the first file of the queue, usually Logi Uruchomienia: the first failure ends the pass), the queue file is the same, and no `kontrola-ilosci` issue appears. Okresy shows no `alert`. Capture `151`.
- **Sent at the next start.** The harness removes `brak-sieci` and writes `4000` to `pacing/skrzynka-ms.txt`. Close and start again the same way. Heading `Okresy` is visible while the log has no new `skrzynka-wyslano etykieta=kontrola-ilosci`, so the start did not wait for the skrzynka. Capture `152`. Then the log gets `skrzynka-wyslano etykieta=kontrola-ilosci okres=06_12_10_2026`, the skrzynka has one more issue labelled `kontrola-ilosci` with the title and first line above and `- Uruchomienie: <run_id of the queue file>`, and the queue is empty. The pacing file is removed and the key file emptied.
- **Proof.** Screenshots `150`–`152`, `api/kontrola-skrzynka.json` (number, title, labels, state and first line only), the two server consoles in `api/`, checks in `drive.txt`.

## Gotchas

- The issue body holds CZYNNOŚCI and UMOWA of the synthetic Plik zbiorczy, which carry the fixture's row marker. Never copy the body into evidence: the self-test fails on the marker.
- The Kontrola issue takes a number in the skrzynka before the Zgłoszenia of features/zgloszenie.md. Drives look issues up by label (`box_issues`), never by `1.json`.
- After a restart `/api/runs/current` is idle; Uruchomienia shows the last card restored from its Logi (`karta-z-logow.md`), and later features start a new Uruchomienie from the form.
- `diagnoza` expects no key before `zgloszenie`, so the drive empties its file at the end (an empty key file is no key for the server, and on Windows it can be emptied while the server reads it).
