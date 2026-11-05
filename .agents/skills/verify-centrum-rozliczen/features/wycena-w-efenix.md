# Wycena w efenix

After Uzupełnienie pliku zbiorczego Dad picks `Wycena w efenix` on Uruchomienia, the period with its Plik zbiorczy, and
`Uruchom`. Centrum opens the efenix window (at Dad's: his installed Google Chrome in the tool's own profile; here
Playwright's headless Chromium on the Atrapa efenix, never efenix.pl) and waits until Dad logs in; the time he takes
counts neither in `Czas uruchomienia` nor in the metrics. Then the live card counts the orders `n z m` with the current
Wykonawca, the result card lists the errors, Emmett's warnings and the Zlecenia rozliczone (status „Rozliczone” in efenix,
not an error) with the row, the order number and the Wykonawca, and counts the skipped orders, and a toast names the result and the period. The ready orders get the Znacznik efenix in
`ADRES` of the Plik zbiorczy, and the Status okresu stays. Dad looks at the efenix window or leaves the computer during
the Wycena, so the result also waits for him under the bell: a new Powiadomienie with the result, the period and the
counts, which opens the card of the Uruchomienie.

## Sub-features

- `przycisk`: radio `Wycena w efenix` (`Wyceny zleceń i Znaczniki efenix`) offers the period `08_14_09_2026` (`Plik zbiorczy przygotowany`) in combobox `Okres`, group `Plik zbiorczy` names its file, the footer has the primary `Uruchom` and no `Podgląd bez zapisu`; `GET /api/runs/setup` has the process with `preview_hint: null` and the period.
- `logowanie`: alertdialog `Uruchomić z zapisem?` names `Wycena w efenix · okres 08_14_09_2026` without `Nie było podglądu bez zapisu`; its `Uruchom` starts the Uruchomienie, region `Podgląd na żywo` shows status `Krok` with `Zaloguj się w oknie efenix` while the Atrapa is logged out, `GET /api/runs/current` is `running` with that step, and a second start (`POST /api/runs` of Przebieg rozliczeń) is refused with 409. The harness logs in.
- `postep`: progressbar `Zlecenia` with `Zlecenia · <Wykonawca>` and `n z 4`.
- `karta`: label `Wynik` `Wycena w efenix gotowa · wymaga sprawdzenia` with `Otwórz Plik zbiorczy`; the figures `Zlecenia w zakresie 4`, `Gotowe do przekazania 1`, `Rozliczone 1`, `Błędy zleceń 1`, `Ostrzeżenia Emmetta 1`; table `Błędy` with one row `wiersz 19 | QX9002 | beata.testowa | efenix nie zna zlecenia o numerze z NUMER ZL. …`, table `Ostrzeżenia Emmetta` with `wiersz 20 | QX9003 | celina.testowa | … efenix 2, plik 1 …`, table `Rozliczone` with `wiersz 21 | QX9004 | dorota.testowa` and no sentence; tiles `Pominięte` `Ze zdjęciami 0`, `Usterki 0`, `Nieznalezione w efenix 1` (zero is no warning here); the toast `Wycena w efenix gotowa · wymaga sprawdzenia` with `Okres 08_14_09_2026`.
- `plik-i-logi`: only row 18 of the Plik zbiorczy has the Znacznik efenix (`E0CCFF`) in `ADRES`, row 21 (rozliczone) has none; `/api/periods` still has the period `collective_file_prepared`, with the Droga okresu stages `done`, `done`, `now`, `later`, the next step `price_in_efenix` and `create_worker_settlements` beside it (a Wycena that needs checking is not passed); one new file of Logi `*-efenix-*.json` traces rows 18–21 (`gotowe`, `błąd`, `ostrzeżenie Emmetta`, `rozliczone`) without any order number in the trace and without any address of the file and the Atrapa anywhere, its Kopia wejścia (#841) holds the same rows with `NUMER ZL.` and `WYKONAWCA` and without `ADRES`, and it reads every efenix page (#843): row 19's search found nothing (`found` 0, no `results`), row 21's search found its order with `same_number`, the status `Rozliczone`, the realizator `dorota.testowa` and no differing address part, and row 18's opened order has the status `Do wyceny`, the realizator `adrian.testowy` and the quantity of every position; `Otwórz Plik zbiorczy` writes the Plik zbiorczy to `opened.jsonl`.
- `powiadomienie`: the bell in the header is `Powiadomienia, są nowe`; `GET /api/notifications` has a `wycena_w_efenix` item of this Uruchomienie, unread, with the card's headline, the period, `orders` `{"ready": 1, "settled": 1, "errors": 1, "warnings": 1}` and `stopped: null`; the bell opens the view Powiadomienia with the listitem `Wycena w efenix: Wycena w efenix gotowa · wymaga sprawdzenia` marked `nowe`, `Okres 08_14_09_2026` and the terms `Gotowe do przekazania`, `Rozliczone`, `Błędy zleceń`, `Ostrzeżenia Emmetta` with `1`, `1`, `1`, `1`; its button `Karta Uruchomienia` opens the side panel with label `Wynik` `Wycena w efenix gotowa · wymaga sprawdzenia`; after the visit `unread` is 0.

## How to get to it (user POV)

- Uruchomienia → `Nowe Uruchomienie procesu` (after a result: the `+` first) → radio `Wycena w efenix` → combobox `Okres` → `Uruchom` → the dialog's `Uruchom` → log in in the efenix window.
- After the Wycena: the bell in the header → the Powiadomienie → `Karta Uruchomienia`.

## Driving it with Playwright for Python

Preconditions:

- Centrum is served for this run with `DOCTOR OK`; `serve_centrum.py` serves the Atrapa efenix with `EFENIX_ORDERS` (rows 18–21: `#QX9001` of `adrian.testowy` ready after the Wycena Emmetta and `T` from the file, `#QX9002` of `beata.testowa` unknown to efenix, `#QX9003` of `celina.testowa` whose Emmett differs from the file, `#QX9004` of `dorota.testowa` with the status `Rozliczone`), logged out, each search answered after 1 s; its address is `<root>/efenix/adres.txt`.
- `<root>/efenix/08_14_09_2026/` holds the Plik zbiorczy of those orders with the Kwota (AU) Excel computed.

- **Button.** Harness: the folder okresów set through the picker if no feature before set it, and `<root>/efenix/08_14_09_2026` copied into it (removed again at the end of the feature). `#/uruchomienia`, `Nowe Uruchomienie procesu` when a result is shown, radio `Wycena w efenix`, option `period_choice("08_14_09_2026", "Plik zbiorczy przygotowany")`; `api/efenix-karta-startu.json`. Capture `260`.
- **Login.** `Uruchom`, the alertdialog's `Uruchom`; status `Krok` with `Zaloguj się w oknie efenix`; `api/efenix-logowanie.json`; the refused `POST /api/runs` (`api/efenix-drugie-uruchomienie.json`). Capture `261` (live). Harness: the login form of the Atrapa's `page_login.php` posted to its `action_login.php`, as Dad logs in.
- **Progress.** Progressbar `Zlecenia` and `Zlecenia · `; `api/efenix-postep.json`. Capture `262` (live).
- **Card.** `api/efenix-wynik.json` `finished`; label `Wynik`, the toast in region `Notifications`, tables `Błędy`, `Ostrzeżenia Emmetta` and `Rozliczone` cell by cell. Capture `263`.
- **File and Logi.** openpyxl reads the fill of `B18`–`B21`; `api/efenix-status-okresu.json`; the newest `logs/uruchomienia/*-efenix-*.json`; `Otwórz Plik zbiorczy` → last line of `opened.jsonl`.
- **Powiadomienie.** The bell's accessible name, `api/efenix-powiadomienia.json`; capture `264`; the bell → listitem cell by cell, capture `265`; `Karta Uruchomienia` → dialog label `Wynik`, capture `266`; Escape; `api/efenix-powiadomienia-przeczytane.json`.
- **Proof.** Screenshots `260`–`266`, `api/efenix-*.json`, `state/` (the Logi, `opened.jsonl`), checks in `drive.txt`. `scripts/check_centrum_wycena_w_efenix_mutations.py` shows the drive fails when the period with a prepared Plik zbiorczy has no button, when the window does not say it waits for the login, when the card has no order numbers and Wykonawcy, when the Logi lose the trace of the orders or the reading of the efenix pages, and when a Zlecenie rozliczone is an error again.

## Gotchas

- The efenix window is a second Chromium that Centrum starts itself (`EfenixWindow` in `serve_centrum.py`); the drive cannot click in it, so Dad's login is the harness posting the Atrapa's login form, which logs in the Atrapa's one session. The window notices it within 2 s (`LOGIN_POLL_MS`).
- The window on the Atrapa has no human pace (`pace=None`); with Dad's pace (about 20 s per order) the feature would take minutes.
- Without the 1 s search delay the four orders end in milliseconds and the progressbar `Zlecenia` cannot be seen.
- The Atrapa restarts with Centrum (Aktualizacja narzędzia): it is logged out again, and its orders are fresh, so the feature does not depend on an earlier Wycena in the run.
- In `all` the feature runs after every feature that counts periods or Logi, because its Folder okresu `08_14_09_2026` and its file of Logi would change their counts.
