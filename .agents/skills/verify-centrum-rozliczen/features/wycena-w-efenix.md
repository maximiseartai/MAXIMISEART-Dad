# Wycena w efenix

After Uzupełnienie pliku zbiorczego Dad picks `Wycena w efenix` on Uruchomienia, the period with its Plik zbiorczy (`Plik zbiorczy przygotowany` or `Rozliczenia pracowników gotowe`), and
one of two buttons side by side (ADR 0027): `Uzupełnij bez zapisu` (he clicks the green „Zapisz” in efenix himself) or
`Uzupełnij i zapisz` (Centrum clicks it at the ready orders, the Przekazanie do akceptacji). Neither is the primary one
and Centrum remembers neither. Centrum opens the efenix window (at Dad's: his installed Google Chrome in the tool's own profile; here
Playwright's headless Chromium on the Atrapa efenix, never efenix.pl) and waits until Dad logs in; the time he takes
counts neither in `Czas uruchomienia` nor in the metrics. Then the live card counts the orders `n z m` with the current
Wykonawca, the result card lists the errors, Emmett's warnings and the Zlecenia rozliczone (status „Rozliczone” in efenix,
not an error) with the row, the order number and the Wykonawca, and counts the skipped orders, and a toast names the result and the period. The ready orders get the Znacznik efenix in
`ADRES` of the Plik zbiorczy, and the Status okresu stays. Dad looks at the efenix window or leaves the computer during
the Wycena, so the result also waits for him under the bell: a new Powiadomienie with the result, the period and the
counts, which opens the card of the Uruchomienie. The card, the Powiadomienie and the Logi name the mode, and on the
card of a Wycena „zapis” means only the green „Zapisz”: its badge is `Bez zapisu` or `Z zapisem`.

## Sub-features

Printed by `scripts/sub_features.py --feature wycena-w-efenix` from the drive's steps and checks; refresh the section with it.

- `przycisk`: the setup card offers Wycena w efenix for the period with a Plik zbiorczy, with the two modes and no Podgląd bez zapisu; the two buttons stand side by side with one look and size, and neither is the primary one.
- `logowanie`: the Uruchomienie without Przekazanie waits for Dad's login in the efenix window and says so on the card; no other Uruchomienie starts while it waits.
- `postep`: the live progress counts the orders of the Plik zbiorczy with the current Wykonawca.
- `karta`: the card counts the ready, the settled, the errors, Emmett's warnings and the skipped orders; the card lists each error and warning with its row, order number, Wykonawca and sentence, each Zlecenie rozliczone with its row, order number and Wykonawca, and a toast; the card has the badge … and no other word of „zapis” for its mode; the label Przekazane do akceptacji stands in one line, as high as Rozliczone.
- `plik-i-logi`: only the ready order's ADRES has the Znacznik efenix, the Zlecenie rozliczone's has none; the Status okresu stays Plik zbiorczy przygotowany; a Wycena w efenix that needs checking leaves its step of the Droga okresu current and the next step, with Przebieg rozliczeń reachable beside it; the Uruchomienie wrote one file of Logi Uruchomienia of efenix; the Logi trace every order by its row, the Zlecenie rozliczone as rozliczone, the trace without its order number, and no part of the Logi has the address; the Kopia wejścia of the Logi holds rows 18–21 of the Plik zbiorczy with NUMER ZL. and WYKONAWCA, without ADRES; the Logi read every efenix page (#843): the search results with status, realizator and differing address parts, and the opened order's status, realizator and every position's quantity; Otwórz Plik zbiorczy opens the Plik zbiorczy with the Znaczniki efenix.
- `powiadomienie`: the ended Wycena is a new Powiadomienie with the result, the period and the ready, settled, error and warning counts; the Powiadomienie opens the card of this Uruchomienie from its Logi in the side panel.
- `z-zapisem`: harness: the start request left the tab late; the Wycena with Przekazanie forwards the ready order: none ready, one forwarded, the settled one stays; the card has the badge … and no other word of „zapis” for its mode; the label Przekazane do akceptacji stands in one line, as high as Rozliczone; the forwarded order's ADRES has the Znacznik przekazania instead of the Znacznik efenix; the Logi have the mode in their start facts and trace the forwarded order as przekazane; the Powiadomienie has the mode and counts the forwarded order; the Powiadomienie row names the mode and the forwarded count.
- `uruchom-ponownie`: the Wycena of a Plik zbiorczy without the computed Kwota (AU) stops and offers Uruchom ponownie; Uruchom ponownie of a Wycena opens the setup card with Wycena w efenix and its period, and starts nothing.

## How to get to it (user POV)

- Uruchomienia → `Nowe Uruchomienie procesu` (after a result: the `+` first) → radio `Wycena w efenix` → combobox `Okres` → `Uzupełnij bez zapisu` or `Uzupełnij i zapisz` → the dialog's button of the same name → log in in the efenix window.
- After the Wycena: the bell in the header → the Powiadomienie → `Karta Uruchomienia`.

## Driving it with Playwright for Python

Run `.venv/bin/python .agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wycena-w-efenix`.
Its proof adds `api/efenix-*.json` and `state/` (the Logi, `opened.jsonl`).

## Gotchas

- The Atrapa restarts with Centrum (Aktualizacja narzędzia): it is logged out again, and its orders are fresh, so the feature does not depend on an earlier Wycena in the run.
- The second Wycena runs on the same Atrapa as the first: row 18 is then a complete Do wyceny order, so the mode with
  Przekazanie forwards it (the Atrapa turns it into „Do akceptacji”) and the dark Znacznik replaces the light one.
