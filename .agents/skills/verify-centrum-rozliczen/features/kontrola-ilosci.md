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

Printed by `scripts/sub_features.py --feature kontrola-ilosci` from the drive's steps and checks; refresh the section with it.

- `kontrola-w-kolejce`: the RUN of … left its Kontrola ilości in config/zgloszenia/kolejka; the Centrum log says the Kontrola ilości of the RUN went into the queue; without a key the Centrum log says the queue waits (one line per pass, naming its first file), with no content; no Zgłoszenie file for Dad next to the queue: the Kontrola is not an unsent Zgłoszenie; Dad's tab says nothing about the skrzynka Zgłoszeń.
- `kontrola-bez-sieci-po-starcie`: the Kontrola file stays after another failure; nothing reached the skrzynka.
- `kontrola-wyslana-po-starcie`: Okresy is shown … s after the start, before the skrzynka took the Kontrola; the skrzynka got exactly one Kontrola ilości; the issue is the period's Kontrola ilości, labelled kontrola-ilosci; it is the Kontrola of the RUN from the queue; the Centrum log has neither the key nor workbook content; the key is not in the Kontrola.

## How to get to it (user POV)

Dad never sees it. He runs Przebieg rozliczeń with `Uruchom` (`przebieg-rozliczen.md`), and the Kontrola goes out by
itself; closing Centrum with `Zamknij Centrum rozliczeń` and starting it again from the desktop shortcut sends a waiting
one again.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature kontrola-ilosci`
from the repository root (Windows: `py -3`). The proof is in the evidence folder that `VERIFY OK` names: the lines
under `STEP kontrola-ilosci` in `drive.txt`, screenshots `150`–`152`, `api/kontrola-skrzynka.json` and the two server
consoles `api/kontrola-start-*-server.txt`.

## Gotchas

- After the drive's two restarts `/api/runs/current` is idle and Uruchomienia shows the last card restored from its
  Logi (`karta-z-logow.md`), so a later feature starts a new Uruchomienie from the form.
