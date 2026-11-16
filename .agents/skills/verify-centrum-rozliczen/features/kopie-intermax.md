# Kopie INTERMAX

When INTERMAX breaks, Dad opens the section `Kopie INTERMAX` of Ustawienia:
the 10 newest Kopie INTERMAX from before an Uporządkowanie or a restore (each write
removes older ones of both names, `intermax_copies.KEPT`), newest first, each with its date and time from the file name and a quiet note of what
it was made before. `Przywróć` on a row asks one sentence: the changes made in
INTERMAX after that time disappear. `Przywróć tę kopię` first saves the current
INTERMAX as a Kopia `INTERMAX przed przywróceniem RRRR-MM-DD GG-MM-SS.xlsx`,
then replaces INTERMAX with the Kopia byte for byte (ADR 0019, #472). With
INTERMAX open in Excel it refuses with a Komunikat and changes nothing.

## Sub-features

Printed by `scripts/sub_features.py --feature kopie-intermax` from the drive's steps and checks; refresh the section with it.

- `lista`: INTERMAX of this feature is in the settings; the folder of Kopie reads without a Komunikat; the list has the Kopie of both names, the newest first, by the moment in their name; each Kopia says before what it was made; the card lists the Kopie in the same order with Dad's date and time from the name.
- `ostrzezenie`: one sentence warns that the changes after the Kopia's time disappear; „Anuluj” leaves INTERMAX and the Kopie as they were.
- `otwarty`: with INTERMAX open in Excel the restore refuses and changes neither INTERMAX nor the Kopie.
- `przywrocenie-dotykiem`: INTERMAX is the chosen Kopia byte for byte; the state before the restore lies as a new Kopia „przed przywróceniem” named after Centrum's clock; the new Kopia is the newest on the list; the card reads the list again and shows the new Kopia first.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer → section `Kopie INTERMAX` (group Pliki, `#/ustawienia/kopie-intermax`).

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature kopie-intermax`.
Its proof adds `api/kopie-*.json`.

## Gotchas

- Run it after `uporzadkowanie-intermax` in `all`: that feature counts exactly one Kopia in the folder of Kopie, and
  its own Kopia (`… 2026-10-19 …`) is then the newest on this list.
- Two restores in one second would collide on the name of the Kopia of the current state; the feature restores once.
  The second one is refused with „Przed chwilą przywrócono już kopię INTERMAX, więc ta kopia nie została przywrócona.”
  and changes neither INTERMAX nor the Kopie
  (`tests/test_centrum_przywracanie_kopii_intermax.py::test_drugie_przywrocenie_w_tej_samej_sekundzie_mowi_ze_kopie_przywrocono_przed_chwila`).
