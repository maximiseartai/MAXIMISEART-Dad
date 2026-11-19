# Uporządkowanie INTERMAX

After pasting the orders of the next day at the bottom of INTERMAX (the Rejestr
zleceń), Dad saves and closes it and taps `Uporządkuj INTERMAX` on the card under
`Nowe Uruchomienie procesu` on Uruchomienia. The card stands outside the periods:
INTERMAX is the Rejestr zleceń from his settings, and the Uruchomienie belongs to
the period of today's date (ADR 0019). The result card counts the orders, those
with Historia adresu from the Baza zleceń beside INTERMAX and the Wykonawcy, names the ordered day and the Kopia INTERMAX from before the write,
and opens INTERMAX. The Baza zleceń lies in the folder of INTERMAX under its fixed name (`ORDER_BASE_NAME` in
`src/rozliczenia/order_base.py`); each order with Historia adresu gets the Baza's rows of the same address after
`UWAGI`, every other block light grey, and its column A red. Without a Baza Dad can read, the day is still ordered:
a warning says „INTERMAX został uporządkowany bez Historii adresu…” and the card leaves the count out
(`tests/test_centrum_uporzadkowanie_intermax.py::test_uporzadkowanie_z_centrum_bez_bazy_zlecen_w_folderze_intermax_ostrzega_a_karta_i_logi_nie_maja_historii_adresu`;
the drive's fixture has a Baza). Stops show the same three-part banner as the other
processes; „do Maksa” leads to the Diagnoza and the Zgłoszenie.

## Sub-features

Printed by `scripts/sub_features.py --feature uporzadkowanie-intermax` from the drive's steps and checks; refresh the section with it.

- `bez-intermax`: without INTERMAX the card says what to set and its button is disabled.
- `wskazanie`: the card is ready with Dad's INTERMAX.
- `dni`: the card lists today, the 6 days before it and the later Dzień uporządkowany, each with its state, without the pasted day.
- `otwarty`: INTERMAX open in Excel disables the button with the sentence what to do; the days of INTERMAX open in Excel come from its last saved version; once Excel closes INTERMAX the button is enabled again.
- `uporzadkowanie-dotykiem`: the result card counts the orders, right after them those with Historia adresu from the Baza zleceń beside INTERMAX, and the Wykonawcy of the pasted day in the period of today; the Kopia INTERMAX holds the bytes from before the write and is named after the clock; Dad's INTERMAX is ordered on disk; the result opens Dad's INTERMAX.
- `zatrzymanie-dla-taty`: the card shows the last Uporządkowanie from its Logi with its day; after the Uporządkowanie the card shows the pasted day as ordered; the INTERMAX ordered before stops „dla taty”: nothing left to order; the stop offers „Otwórz INTERMAX”, the card's one name of the file; the same stop again offers Diagnoza.
- `zatrzymanie-do-maksa`: pasted rows with a formula stop „do Maksa”; the Diagnoza checks Dad's INTERMAX and offers the Zgłoszenie of Uporządkowanie INTERMAX.
- `historia`: four new files of Logi of Uporządkowanie INTERMAX, each with the period of the fixture's today; Historia lists every Uporządkowanie INTERMAX from Centrum; Metryki of INTERMAX offer only the mode RUN: Uporządkowanie INTERMAX has no Podgląd bez zapisu; from Przygotowanie DRY-RUN, INTERMAX shows its RUN pressed with the chart of its runs.

## How to get to it (user POV)

Dad opens Uruchomienia and taps `Uporządkuj INTERMAX` on the card under `Nowe Uruchomienie procesu`; after a result he
clicks `Nowe Uruchomienie procesu` first. He points INTERMAX in Ustawienia, section Foldery.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature uporzadkowanie-intermax`; the shared proof and the Windows form are in point 3 of [`README.md`](README.md).
Its proof adds `api/intermax-*.json` and `state/` (the Logi, `opened.jsonl`).

## Gotchas

- The setup card of Przygotowanie also has a Rejestr zleceń row; the INTERMAX card names its row `INTERMAX`. Neither
  chooses the file: only Foldery of Ustawienia does.
- Every Uruchomienie of Uporządkowanie INTERMAX writes INTERMAX only on success, so the second and later ones of this
  feature stop before writing: the Kopia INTERMAX of the first is the only one, and two orderings in one second cannot
  collide on its name.
