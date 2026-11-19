# Wysyłka rozliczeń

After Przebieg rozliczeń Dad opens `Wysyłka rozliczeń` in the menu (`#/wysylka`): a vertical axis of the periods
with Rozliczenia pracowników, newest first. A period with files to send is a card (region named by the period) with
the bar „X z Y wysłane” and the Wykonawcy, each with his addresses, a ring and his state, ticked when his file still
waits; files without a mail (no address, no orders, not in the Lista) stand in one sentence under them. `Wyślij N
rozliczeń` opens a window that previews each mail (1 z N), and after `Wyślij N` every Wykonawca gets his own file from
the skrzynka raportów, one request per mail, while his row turns „Wysłane” and the bar grows. When all went, the card
says „Wszystkie rozliczenia wysłane” and closes into one line of the axis: „X z X · <time>”, a small bar, the
Wykonawcy's avatars and „kto i kiedy”. A file already sent and unchanged never goes twice. The header's switch shows
only the periods that wait (`Do wysłania`) or all of them; its link `Temat i treść` opens the section `Wysyłka
rozliczeń` of Ustawienia, with a preview; a subject with „raport” is refused (ADR 0040), and so is one whose `Re:`
reply the skrzynka raportów would take for a Raport („Temat wygląda jak temat raportu…”). The section shows the
subject and text of Dad's file, never the built-in ones in silence: while that file has a subject or text the rule
refuses, with no last good one, the page, the preview and the sending refuse in one sentence („Mail z rozliczeniem nie
pójdzie…”, #2074), and while that file, the file of Przypomnienia with the footer or the Lista Wykonawców cannot be
read, they refuse with the sentence of that file („Pliku … w folderze config nie da się teraz przeczytać…”). The drive
refuses only the subject with „raport”; the other refusals stand in
`tests/test_centrum_rozliczen.py::test_temat_taty_ktorego_regula_nie_przyjmuje_to_odmowa_strony_podgladu_i_wysylki_bez_maila`
and `::test_plik_tematu_stopki_albo_listy_bez_odczytu_to_odmowa_strony_podgladu_i_wysylki_bez_maila`.

## Sub-features

Printed by `scripts/sub_features.py --feature wysylka-rozliczen` from the drive's steps and checks; refresh the section with it.

- `strona`: the page reads the skrzynka raportów; the files of the settled period that never went are „do wysłania” and ticked; each Rozliczenie pracownika of the period has its row, ticked when it waits.
- `potwierdzenie`: the window only previews: no mail went yet; the next mail previews the next Wykonawca's file.
- `po-wysylce`: each Wykonawca gets his own file, byte for byte, on his addresses, with the subject from Ustawienia; the page reads the skrzynka raportów; the server reads every mail from „Wysłane” as sent by Centrum; the Centrum log has one line per mail with the period token, without names; the sent period closes into one line of the axis, „X z X”, and „kto i kiedy” shows each mail as sent.
- `bez-powtorki`: a second send of a file already sent and unchanged sends nothing.
- `ustawienia`: a subject with „raport” is refused and nothing is saved; the subject is saved and the preview fills its fields.

## How to get to it (user POV)

- The menu entry `Wysyłka rozliczeń` (`#/wysylka`), after `Raporty`.
- The gear `Ustawienia` in the menu's footer → section `Wysyłka rozliczeń` (group Praca, `#/ustawienia/wysylka-rozliczen`), also through `Temat i treść` in the page's header and „Zmień temat i treść w Ustawieniach” in the window of the send.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wysylka-rozliczen`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/wysylka-*.json`; the mails the atrapa SMTP took lie in `<root>/skrzynka-raportow/wyslane/` of the run, never in the evidence, because each carries a workbook.

## Gotchas

- The served Centrum sends through `AtrapaSmtp` of `serve_centrum.py`, which logs in with the run's access file; the
  drive writes that file for the feature and puts back what it found (`drive.common.atrapa_inbox_access`), so
  `ustawienia` and `wpisanie-raportow` see their own. The block ends with one read of Centrum, because Centrum writes
  the Historia row of a file changed outside it only at its next read: without it the next feature (`aktualizacja` in
  `--feature all` and in part 2/4 of CI) finds `config` changed after its start (#2029 W2 r1).
- The fixture's Rozliczenia pracowników have no header `WYKONAWCA`, so Centrum cannot tell an empty Szablon from them
  and offers every one; the state „Bez zleceń” is proved by `tests/test_centrum_rozliczen.py`.
- The card and the line it closes into are both regions named by the period, and both carry the progress bar
  `Wysłane: <period>`; the drive waits for the line's text „X z X · ” before it reads the bar, because the card stands
  for 1,5 s after the last mail.
