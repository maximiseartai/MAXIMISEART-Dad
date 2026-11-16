# Przygotowanie pliku zbiorczego

Dad prepares the Rozliczenie wewnętrzne and the Plik zbiorczy of a period
from Centrum: he picks the period (the last complete one is preselected),
looks at the plan without writing (`Podgląd bez zapisu`, DRY-RUN), confirms
the write (`Uruchom`, RUN) after a reminder to close the Rejestr zleceń, sees
the stages live over SSE, decides about an incomplete period in a dialog, and
gets the result: stops and warnings separately, each in three parts. Every
Uruchomienie procesu appends to the process's metrics file, and the history
marks it as started from Centrum. While the Rejestr zleceń is open in Excel (its lock file `~$…`
next to it), the start card warns, turns off `Uruchom` and keeps `Podgląd bez
zapisu` and the reminder; once the lock file is gone, Dad's return to the
window clears the warning without a reload.

## Sub-features

Printed by `scripts/sub_features.py --feature przygotowanie-pliku-zbiorczego` from the drive's steps and checks; refresh the section with it.

- `przygotowanie-wybor-okresu`: the row's next step opens Uruchomienia; the server preselects the last complete period and nothing is missing.
- `przygotowanie-rejestr-otwarty-w-excelu`.
- `przygotowanie-podglad`: a double click on … starts one Uruchomienie procesu (… requests); no error toast after the double click on …; the DRY-RUN plan has the Rejestr zleceń's counts and Zlecenia na dzień; after the preview the period file names are plain text: the files do not exist yet; … shows the Ilości usług warnings with Plik zbiorczy rows and no row content; the DRY-RUN created neither files nor the Folder okresu; the DRY-RUN appended one record to the process's metrics file.
- `przygotowanie-podglad-po-odswiezeniu`: the server remembers the successful preview per period from the metrics history; after a reload the confirmation warns only for the period without a preview, not for the previewed one.
- `przygotowanie-potwierdzenie`: Uruchom asks to confirm the write and reminds to close the Rejestr zleceń; a double click on … starts one Uruchomienie procesu (… requests); no error toast after the double click on ….
- `przygotowanie-decyzja`: the server waits for Dad's decision; the live counters show the projection's Ostrzeżenia (as many as the preview's warnings) while the decision waits; a second Uruchomienie procesu is refused; closing Centrum is refused while the Uruchomienie procesu waits for the decision; the decision survives a reload of the tab.
- `przygotowanie-znak-decyzji`: on Okresy, where the decision dialog does not open, the header says „Czeka na decyzję”; the header link leads to Uruchomienia, where the decision waits; there it is gone.
- `przygotowanie-przerwij`: the refusal in Dad's decision is calm, not a red error; the refusal is a declined stop with the three-part message, no Diagnoza and the Rejestr zleceń to open; Przerwij bez zapisu wrote nothing; Otwórz Rejestr zleceń opens the Rejestr zleceń from Dad's settings.
- `przygotowanie-podwojne-klikniecie`: a double click on … starts one Uruchomienie procesu (… requests); no error toast after the double click on …; harness: the stream's next view arrives late (the page reports itself hidden), as at CPU 6×; Kontynuuj clicked three times sends one decision (… requests); no error toast after Kontynuuj clicked three times; the decision's buttons wait until the stream shows that the Uruchomienie no longer waits; with the stream back, the dialog closes on the result; a double click on the result's main action Otwórz Plik zbiorczy opens the Plik zbiorczy once (… requests).
- `przygotowanie-kontynuuj`: the RUN needs review only for the preview's warnings: Dad completes the written Plik zbiorczy; … shows the Ilości usług warnings with Plik zbiorczy rows and no row content; both period files are in the Folder okresu; every Uruchomienie procesu appended one record to the process's metrics file; the Centrum log records the start and end of each Uruchomienie procesu with safe facts only.
- `przygotowanie-otwieranie`: each period file name in the result opens its own file, one per click.
- `przygotowanie-status-okresu`: the Status okresu on Tablica okresów is Plik zbiorczy przygotowany, and the next step Uzupełnij plik zbiorczy.
- `przygotowanie-nienadpisywanie`: Nienadpisywanie is a stop Dad fixes himself, with no file of his to open; Nienadpisywanie: both files are unchanged.
- `przygotowanie-historia`: the metrics history marks the four Uruchomienia from Centrum without a schema change; the Historia tab shows the newest Uruchomienie without the .cmd badge.

## How to get to it (user POV)

Dad starts it from Okresy: `Podgląd bez zapisu` on the card `Następny krok`, while the last complete period has no
period files, or the row button `Przygotuj plik zbiorczy, okres <token>` of Tablica okresów, which opens Uruchomienia
with that period chosen. From the sidebar he goes to `Uruchomienia` (`#/uruchomienia`) and `Nowe Uruchomienie
procesu`; the tabs `Uruchomienie` and `Historia` show the live run and the past ones.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature przygotowanie-pliku-zbiorczego`.
Its proof adds `api/przygotowanie-*.json`.

## Gotchas

- After `przygotowanie-kontynuuj` the drive runs the steps `uzupelnienie-wynik…` of `features/uzupelnienie.md` on this
  result card (`drive_result_card` of `drive/uzupelnienie.py`): they print under `STEP uzupelnienie` and are not part
  of this section, and the next steps work on the card `Ostatnie Uruchomienie` from Logi.
- The preview of `06_12_10_2026` carries five warnings: the incomplete period, the rows without zeros (the Wzorzec
  pliku zbiorczego has none), `wiersze 18, 20` with an unknown device, `wiersz 19` settled from the description, and
  the reminder of columns Y, AB, AD, AJ, AK, AL and AM.
- Count metrics records through `/api/metrics`, not by lines: the metrics store cuts off the invalid record that ends
  the fixture's Przygotowanie file on the next append.
- The start card reads `/api/runs/setup` again on `focus` and `visibilitychange`, after an Uruchomienie ends and after
  `Nowe Uruchomienie procesu`, never by itself; after changing a lock file, fire `focus` or the card keeps the old
  answer.
- The result toast appears only after a finished write and covers the bottom-right corner for a few seconds.
- `Uruchom` is also the confirmation dialog's button; scope the second click to the alertdialog.
- A repeated click is a no-op until the stream shows its effect. The decision buttons and the setup card's `Uruchom`
  and `Podgląd bez zapisu` are disabled then: click them again with `force=True`, or Playwright waits for them to be
  enabled. The result's `Uruchom ponownie` and `Uruchom` and the `Następny krok` button stay enabled and drop the
  repeat in the tab.
- Two identical stops „dla taty” in a row are a Powtórka: the second offers `Diagnoza` instead of `Uruchom ponownie`
  (`diagnoza.md`). The drive's stops keep `Uruchom ponownie` only because a finished Uruchomienie stands between them.
- Faking `document.visibilityState` pauses the stream without a reload; always restore it (`finally`), or every later
  step sees a stale Uruchomienie.
