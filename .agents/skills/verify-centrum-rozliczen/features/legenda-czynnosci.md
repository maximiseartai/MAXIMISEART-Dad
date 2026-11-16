# Legenda czynności

In the group Ilości of the window Ustawienia, Dad sees the Legenda czynności that the next Przygotowanie pliku
zbiorczego uses (ADR 0038). Each Kod czynności is one sentence built by the server from the engine's types: its
spellings (`#` for the number in a spelling) and what it gives, e.g. „spawpg: 1 w Spawanie w mufie AB, 70 w Uwagi -
kwota AS, AS na czerwono.”. A column of Ilości usług shows its price-list name from row 17 of the Wzorzec pliku
zbiorczego next to its letter, the amount stands in AS named „Uwagi - kwota”, and a filled column is its letter alone.
Without Dad's file `legenda-czynnosci.yaml` in `config` the section shows the legend of the Release. A file changed
outside Centrum is a row of Historia from outside Centrum; a bad file is a bad setting in one sentence over the last
good legend, which Centrum counts. The pencil at a code opens the form of the code in place of its row, „Dodaj kod” an empty one at the end of the list:
spellings (`#` for the number), the column of Ilości usług (one column or ranges of the number) with its value chosen
only from the columns the legend writes, by price-list name, the amount in AS and the colours. „Usuń kod” turns the
form into the question „Usunąć kod?” with „Nie usuwaj” and „Usuń”. „Zapisz” and „Usuń” are changes of Historia with
„Cofnij”, and a refusal is one sentence at its field, or above the form when it names no field. Every change of the form, the removal too, shows the preview of the
change it saves on the last Pliki zbiorcze after Przebieg rozliczeń, counted by the server with the row check of the
Kontrola ilości: how many rows change, in how many it will be as Dad typed, the Kontrola's legend differences before and
after, and each changed row that differs from Dad with its CZYNNOŚCI ZREALIZOWANE after the data guard (ADR 0025),
without the address, the order numbers and the date; a row left without a code shows Dad's entry. „Zapisz” and „Usuń”
save also with differences.

## Sub-features

Printed by `scripts/sub_features.py --feature legenda-czynnosci` from the drive's steps and checks; refresh the section with it.

- `legenda-zdania`: each of the … codes of the Release is one sentence on screen (…); column AB shows its price-list name next to the letter, the amount stands in „Uwagi - kwota” AS.
- `legenda-zly-plik`: a bad file of the legend is a bad setting in one sentence over the last good legend, which Centrum counts.
- `legenda-historia`: Historia has both changes outside Centrum, the good one as the code's sentence before and after.
- `legenda-dopisany-zapis`: the pencil, „Dodaj zapis” and „Zapisz” add the spelling the workers write to the code.
- `legenda-odmowa`: the column of a code is chosen by its price-list name, only from the … columns the legend writes; a spelling of another code is one sentence at its field, and the legend stays.
- `legenda-nowy-kod`: a new code with a range of the number, an amount in AS and a colour is one more sentence of the legend.
- `legenda-usuniecie-cofnij`: removing a code is a row of Historia, and its „Cofnij” brings the code back.
- `legenda-podglad`: an unchanged form of a code has no preview; the server's preview counts with the Kontrola's row check: spawpg at 80 changes 1 row, which differs from Dad's 70 in AS, and the row with a Błąd opisu beside spawpg does not change; the preview shows the server's counts, the row with its description, the legend's 80 and Dad's 70 in AS.
- `legenda-zapis-przy-roznicach`: „Zapisz” saves the change although the preview shows a difference from Dad.
- `legenda-podglad-usuniecia`: „Usuń kod” turns the form into the question „Usunąć kod?” without its fields; the server's preview of removing inst: row 18 changes to a Błąd opisu with its reason, with Dad's 1 in Y; before removing, the form shows the preview of the removal: the row's Błąd opisu with its reason and Dad's 1 in Y; „Usuń” under the preview removes the code it previewed.
- `legenda-waskie-okno`: the narrow window shows every code (…); on a narrow window the sentences wrap without a horizontal scroll; on a narrow window the form of a code with ranges wraps without a horizontal scroll.

## How to get to it (user POV)

Dad opens Ustawienia (the gear in the menu's footer) and chooses `Legenda czynności` in the group Ilości; a bookmark
of `#/ustawienia/legenda-czynnosci` opens the section too.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature legenda-czynnosci`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/legenda-czynnosci*.json`.
The harness writes Dad's file of the legend in the run's `config` (first good, then bad) and removes it at the end of the step `legenda-historia`; the editor's steps write it again, and the harness removes it after `legenda-usuniecie-cofnij` and again after `legenda-podglad-usuniecia`, so the features after this one find the legend of the Release.
The preview needs the Plik zbiorczy that `przebieg-rozliczen` settled, whose CZYNNOŚCI ZREALIZOWANE in the fixture has no code: the step `legenda-podglad` types codes and Dad's values into rows 18–20 and the harness puts the file's bytes back after `legenda-podglad-usuniecia`.
Its proof adds `api/legenda-czynnosci-podglad.json` and `api/legenda-czynnosci-podglad-usuniecia.json` with the descriptions replaced by `<tekst wiersza>`, as in the ARIA snapshots of `430` and `432`.

## Gotchas

The toast „Zapisano · Cofnij” stands over the last rows of the list; the drive closes it before the pencil of the
last code.
