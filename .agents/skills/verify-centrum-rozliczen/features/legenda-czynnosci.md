# Legenda czynności

In the group Ilości of the window Ustawienia, Dad sees the Legenda czynności that the next Przygotowanie pliku
zbiorczego uses (ADR 0038). Each Kod czynności is one sentence built by the server from the engine's types: its
spellings (`#` for the number in a spelling) and what it gives, e.g. „spawpg: 1 w Spawanie w mufie (AB), 70 w Uwagi -
kwota (AS), AS na czerwono.”. A column of Ilości usług shows its price-list name from row 17 of the Wzorzec pliku
zbiorczego next to its letter, the amount stands in AS named „Uwagi - kwota”, and a filled column is its letter alone.
Without Dad's file `legenda-czynnosci.yaml` in `config` the section shows the legend of the Release. A file changed
outside Centrum is a row of Historia from outside Centrum; a bad file is a bad setting in one sentence over the last
good legend, which Centrum counts. The editor of a code comes with #1944.

## Sub-features

Printed by `scripts/sub_features.py --feature legenda-czynnosci` from the drive's steps and checks; refresh the section with it.

- `legenda-zdania`: each of the … codes of the Release is one sentence on screen (…); column AB shows its price-list name next to the letter, the amount stands in „Uwagi - kwota” AS.
- `legenda-zly-plik`: a bad file of the legend is a bad setting in one sentence over the last good legend, which Centrum counts.
- `legenda-historia`: Historia has both changes outside Centrum, the good one as the code's sentence before and after.
- `legenda-waskie-okno`: the narrow window shows every code (…); on a narrow window the sentences wrap without a horizontal scroll.

## How to get to it (user POV)

Dad opens Ustawienia (the gear in the menu's footer) and chooses `Legenda czynności` in the group Ilości; a bookmark
of `#/ustawienia/legenda-czynnosci` opens the section too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature legenda-czynnosci`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/legenda-czynnosci*.json`.
The harness writes Dad's file of the legend in the run's `config` (first good, then bad) and removes it at the end of the step `legenda-historia`.

## Gotchas

None known that the drive does not handle.
