# Wysyłka rozliczeń

After Przebieg rozliczeń Dad opens `Wysyłka rozliczeń` in the menu (`#/wysylka`): the periods with Rozliczenia
pracowników on the left, the Wykonawcy of the chosen period on the right, each with his addresses, his file and its
state, ticked when his file still waits. `Wyślij N rozliczeń` opens a window that previews each mail (1 z N), and
after `Wyślij N` every Wykonawca gets his own file from the skrzynka raportów, one request per mail, while his row turns
„Wysłane”; a toast says how many went. A file already sent and unchanged never goes twice. The subject and the text are
in the section `Wysyłka rozliczeń` of Ustawienia, with a preview; a subject with „raport” is refused (ADR 0040).

## Sub-features

Printed by `scripts/sub_features.py --feature wysylka-rozliczen` from the drive's steps and checks; refresh the section with it.

- `strona`: the page reads the skrzynka raportów; the files of the settled period that never went are „do wysłania” and ticked; each Rozliczenie pracownika of the period has its row, ticked when it waits.
- `potwierdzenie`: the window only previews: no mail went yet; the next mail previews the next Wykonawca's file.
- `po-wysylce`: each Wykonawca gets his own file, byte for byte, on his addresses, with the subject from Ustawienia; the page reads the skrzynka raportów; the server reads every mail from „Wysłane” as sent by Centrum; the Centrum log has one line per mail with the period token, without names.
- `bez-powtorki`: a second send of a file already sent and unchanged sends nothing.
- `ustawienia`: a subject with „raport” is refused and nothing is saved; the subject is saved and the preview fills its fields.

## How to get to it (user POV)

- The menu entry `Wysyłka rozliczeń` (`#/wysylka`), after `Raporty`.
- The gear `Ustawienia` in the menu's footer → section `Wysyłka rozliczeń` (group Praca, `#/ustawienia/wysylka-rozliczen`), also through „Zmień temat i treść w Ustawieniach” in the window of the send.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wysylka-rozliczen`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/wysylka-*.json`; the mails the atrapa SMTP took lie in `<root>/skrzynka-raportow/wyslane/` of the run, never in the evidence, because each carries a workbook.

## Gotchas

- The served Centrum sends through `AtrapaSmtp` of `serve_centrum.py`, which logs in with the run's access file; the
  drive writes that file for the feature and puts back what it found, so `ustawienia` and `wpisanie-raportow` see their
  own.
- The fixture's Rozliczenia pracowników have no header `WYKONAWCA`, so Centrum cannot tell an empty Szablon from them
  and offers every one; the state „Bez zleceń” is proved by `tests/test_centrum_rozliczen.py`.
