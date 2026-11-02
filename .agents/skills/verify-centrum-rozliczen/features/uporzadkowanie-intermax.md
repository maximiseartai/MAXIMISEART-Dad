# Uporządkowanie INTERMAX

After pasting the orders of the next day at the bottom of INTERMAX (the Rejestr
zleceń), Dad saves and closes it and taps `Uporządkuj INTERMAX` on the card under
`Nowe Uruchomienie procesu` on Uruchomienia. The card stands outside the periods:
INTERMAX is the Rejestr zleceń from his settings, and the Uruchomienie belongs to
the period of today's date (ADR 0019). The result card counts the orders and the
Wykonawcy, names the ordered day and the Kopia INTERMAX from before the write,
and opens INTERMAX. Stops show the same three-part banner as the other
processes; „do Maksa” leads to the Diagnoza and the Zgłoszenie.

## Sub-features

- `bez-intermax`: without the Rejestr zleceń in the settings the card says `Najpierw wskaż INTERMAX.` and `INTERMAX: nie wskazano`, and its button is disabled; `GET /api/intermax` has the same `blocker`.
- `wskazanie`: `Wskaż INTERMAX` (or `Zmień INTERMAX`) on the card points the Rejestr zleceń to the fixture's INTERMAX through the native picker; the card has no blocker, the reminder `Zapisz i zamknij INTERMAX w Excelu`, and an enabled button.
- `dni`: under the INTERMAX row the list `Dni INTERMAX` shows today and the 6 days before it (13–19.10) and the later Dzień uporządkowany `wt 20.10`, each item named `<day>: uporządkowany` or `<day>: nieuporządkowany` (`pon 19.10` and `wt 20.10` ordered, `pon 19.10` with `aria-current="date"`); the day of the Surowe zlecenia `pon 26.10` is later than today and not ordered, so it is not on the card; `GET /api/intermax/days` has the same days.
- `otwarty`: with Excel's lock file `~$…` next to INTERMAX the card says `INTERMAX jest otwarty w Excelu. Zapisz go i zamknij.` and the button is disabled, while the days stay, read from its last saved version; without the lock file it is enabled again.
- `uporzadkowanie-dotykiem`: in a touch context with the CPU slowed 4× (Dad's laptop), a tap on the button orders the pasted day: label `Wynik` with `INTERMAX uporządkowany`, the figures `Zlecenia` and `Wykonawcy` equal to the fixture's pasted orders, the tile `pon 26.10.2026: 6`, `Kopia sprzed zapisu: INTERMAX przed uporządkowaniem 2026-10-19 GG-MM-SS.xlsx` whose file in `<root>/Kopie INTERMAX` holds the bytes from before, INTERMAX changed on disk, `Okres 13_19_10_2026` (the period of today) above the title, and a tap on `Otwórz INTERMAX` writes INTERMAX to `opened.jsonl`.
- `zatrzymanie-dla-taty`: the card shows `Ostatnio <date> · INTERMAX uporządkowany · pon 26.10.2026` from the Logi and `pon 26.10: uporządkowany` in `Dni INTERMAX`; the ordered INTERMAX has nothing left to order, so the button ends in the banner `Do poprawy` with `Na dole arkusza zleceń nie ma wklejonych zleceń do uporządkowania. …` and `Otwórz INTERMAX` (no `Otwórz Rejestr zleceń`: one name of the file on the card), and `Uruchom ponownie` repeats it with `Diagnoza`.
- `zatrzymanie-do-maksa`: INTERMAX whose pasted rows hold a formula stops „do Maksa” (`Błąd`); `Diagnoza` lists `Ustawienia taty` („INTERMAX jest na miejscu.”, the card's name of the file), `Pliki w OneDrive` and `INTERMAX` first and offers `Wyślij do Maksa` with a Zgłoszenie of Uporządkowanie INTERMAX (not sent).
- `historia`: four new files of Logi of `intermax`, each `zapis` in `13_19_10_2026`, the period of the fixture's today; Historia filtered by `INTERMAX` lists them, and `GET /api/metrics` has each as an Uruchomienie from Centrum; Metryki with Proces `INTERMAX` offer only the Tryb `RUN`, because Uporządkowanie INTERMAX has no Podgląd bez zapisu, and after Przygotowanie `DRY-RUN` that `RUN` is pressed with the chart of its runs, not the empty one.

## How to get to it (user POV)

- Uruchomienia → the card `Uporządkuj INTERMAX` under `Nowe Uruchomienie procesu` (after a result: `Nowe Uruchomienie procesu` first).

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`.
- `<root>/INTERMAX/` holds the fixture's two INTERMAX files (`fixture.json` → `intermax`): one with the Surowe zlecenia of Monday 26.10.2026 (6 orders of 3 Wykonawcy), one whose pasted rows hold a formula.
- The fixture's "today" is Monday 19.10.2026; Centrum's clock for the process is that day at the computer's time of day.

- **Without INTERMAX.** Harness: the settings file without `rejestr_zlecen` (its text kept). `#/uruchomienia`, `Nowe Uruchomienie procesu` when a result is shown; region `Uporządkuj INTERMAX` has `Najpierw wskaż INTERMAX.`, `INTERMAX: nie wskazano`, and button `Uporządkuj INTERMAX` disabled; `api/intermax-bez-intermax.json`. Capture `230`. Harness: the settings text back.
- **Pointing.** Harness answers the picker with `intermax.register`; the card's `Wskaż INTERMAX`/`Zmień INTERMAX` → `rejestr_zlecen` in the settings file, group `INTERMAX` shows its name; after a reload the button is enabled with the reminder; `api/intermax-gotowa.json`. Capture `231`.
- **Days.** `api/intermax-dni.json`; list `Dni INTERMAX` in the card has the eight items of `dni` by their names and no `pon 26.10`, `pon 19.10` with `aria-current="date"`.
- **Open in Excel.** Harness: `~$<name>` next to INTERMAX; reload: the sentence, the disabled button and the eight days. Capture `232`. Harness: the lock file removed; reload: enabled.
- **Ordering by touch.** A new context with `has_touch`, `Emulation.setCPUThrottlingRate` 4; tap the button; `api/intermax-wynik.json` is `finished`; region `Podgląd na żywo` as in the sub-feature. Capture `233` (the touch page). Tap `Otwórz INTERMAX` → the last line of `opened.jsonl` is INTERMAX.
- **Stop for Dad.** Back on the card: the `Ostatnio …` line and `pon 26.10: uporządkowany`, capture `238`; click the button → `api/intermax-nic-do-uporzadkowania.json` with `stop_kind` `for_tata` and the banner with `Otwórz INTERMAX`; `Uruchom ponownie` → `api/intermax-powtorka.json` with `repeated` and `Diagnoza` on the banner. Capture `234`.
- **Stop for Maks.** `Zmień INTERMAX` → `intermax.with_formula`; reload; click the button → `api/intermax-do-maksa.json` with `for_maks`, banner `Błąd`; `Diagnoza` → `api/intermax-diagnoza.json` (the browser's own request), region `Diagnoza` with `INTERMAX` and `Wyślij do Maksa`. Capture `235`.
- **Historia.** The four new files in `logs/uruchomienia/` named `*-intermax-*`; tab `Historia` → group `Proces w historii` → `INTERMAX`: as many rows `Uporządkowanie INTERMAX`; `api/intermax-metryki.json`. Capture `236`. Link `Metryki` → group `Proces` → `Przygotowanie`, group `Tryb` → `DRY-RUN` (pressed) → group `Proces` → `INTERMAX`: group `Tryb` has the one button `RUN`, pressed, and no „Ten proces nie był jeszcze uruchomiony w tym trybie”. Capture `237`. Harness: the Rejestr zleceń from before the feature (through the picker, or the settings text when there was none).
- **Proof.** Screenshots `230`–`238`, `api/intermax-*.json`, `state/` (the Logi, `opened.jsonl`), checks in `drive.txt`.

## Gotchas

- The setup card of Przygotowanie also has a Rejestr zleceń row; the INTERMAX card names its row `INTERMAX`, so `Zmień Rejestr zleceń` stays unique on the page.
- Every Uruchomienie of Uporządkowanie INTERMAX writes INTERMAX only on success, so the second and later ones of this feature stop before writing: the Kopia INTERMAX of the first is the only one, and two orderings in one second cannot collide on its name.
- In `all` the feature runs after every feature that reads the Rejestr zleceń and puts it back at the end; after it, Uruchomienia shows its last result, which `Nowe Uruchomienie procesu` sets aside.
