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

- `lista`: `GET /api/intermax/copies` lists the three Kopie of the fixture (both names) newest first by the moment in their name, without a `problem`, each with `before` (`ordering`, `restore`); the card shows one group `Kopia z <date, time>` per Kopia in the same order, in Dad's time zone, with `przed uporządkowaniem` or `przed przywróceniem`.
- `ostrzezenie`: `Przywróć` on the oldest Kopia opens the dialog `Przywrócić kopię z <date, time>?` with the one sentence `Zmiany w INTERMAX wprowadzone po <time> znikną.`; `Anuluj` closes it and leaves INTERMAX and the Kopie as they were.
- `otwarty`: with Excel's lock file `~$…` next to INTERMAX, `Przywróć tę kopię` shows `INTERMAX jest otwarty w Excelu. INTERMAX nie został zmieniony.` with `Zapisz i zamknij INTERMAX w Excelu, potem przywróć kopię jeszcze raz.`; INTERMAX and the Kopie keep their bytes.
- `przywrocenie-dotykiem`: in a touch context with the CPU slowed 4× (Dad's laptop), a tap on `Przywróć` and on `Przywróć tę kopię` shows `Przywrócono kopię z <date, time>`; INTERMAX holds the oldest Kopia's bytes, one new Kopia `INTERMAX przed przywróceniem 2026-10-19 GG-MM-SS.xlsx` holds INTERMAX from before, and it is the first row of the list read again.

## How to get to it (user POV)

- The gear `Ustawienia` in the menu's footer → section `Kopie INTERMAX` (group Pliki, `#/ustawienia/kopie-intermax`).

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`.
- `<root>/INTERMAX/przywracanie/` holds this feature's INTERMAX and, in `kopie/`, three Kopie (`fixture.json` → `intermax.restore`): `przed uporządkowaniem 2026-10-16 07-30-00` (one ordered order fewer), `przed przywróceniem 2026-10-17 12-15-00`, `przed uporządkowaniem 2026-10-18 18-45-00`.
- Centrum's folder of Kopie is `<root>/Kopie INTERMAX` (`intermax.copies`); its clock for the restore is the fixture's today, Monday 19.10.2026, at the computer's time of day.

- **Harness.** The settings file gets `rejestr_zlecen` = this feature's INTERMAX (the rest kept), and the three Kopie are copied into the folder of Kopie.
- **List.** `#/ustawienia/kopie-intermax` and a reload; `api/kopie-lista.json`; region `Kopie INTERMAX` in dialog `Ustawienia`, its groups `Kopia z …` in the API's order, labels in `Europe/Warsaw` from the computer's local time in the name. Capture `240`.
- **Warning.** Group of the oldest Kopia → button `Przywróć`; `alertdialog` with heading `Przywrócić kopię z …?` and the sentence. Capture `241`. `Anuluj`: INTERMAX and the Kopie unchanged on disk.
- **Open in Excel.** Harness: `~$<name>` next to INTERMAX. `Przywróć` → `Przywróć tę kopię`; the card's banner with the Komunikat; INTERMAX and the Kopie unchanged. Capture `242`. Harness: the lock file removed.
- **Restore by touch.** A new context with `has_touch`, `Emulation.setCPUThrottlingRate` 4; tap `Przywróć` on the oldest Kopia, tap `Przywróć tę kopię`; the alert `Przywrócono kopię z …`; INTERMAX equals the oldest Kopia on disk; the one new file in the folder of Kopie matches `INTERMAX przed przywróceniem 2026-10-19 GG-MM-SS.xlsx` and holds INTERMAX from before; `api/kopie-po-przywroceniu.json` lists it first and so does the card. Capture `243`.
- **Harness, always.** The Kopie this feature added or made are removed, INTERMAX gets its bytes back, and `rejestr_zlecen` is what it was before the feature.
- **Proof.** Screenshots `240`–`243`, `api/kopie-*.json`, checks in `drive.txt`.

## Gotchas

- Run it after `uporzadkowanie-intermax` in `all`: that feature counts exactly one Kopia in the folder of Kopie, and its own Kopia (`… 2026-10-19 …`) is then the newest on this list.
- The names carry the computer's local time and the card shows Dad's (`Europe/Warsaw`); compare the card with labels converted from the name, not with the name's digits.
- Two restores in one second would collide on the name of the Kopia of the current state; the feature restores once.
