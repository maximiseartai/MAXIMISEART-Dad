# Research: co dziś wiąże narzędzie z komputerem taty

Data researchu: 2026-11-08. Pytanie: issue #1148 (mapa #1145 „Centrum w chmurze”).
Źródła: kod i ADR-y tego repozytorium na `main` @ `604d12116`, cytowane jako `plik:linia`
(ścieżki kodu względem `src/rozliczenia/`, ADR-y względem `docs/adr/`).
Liczby linii to `wc -l` (z komentarzami i docstringami), więc są rzędem wielkości, nie miarą pracy.

## Wniosek

1. **Excel jako program, a nie format pliku, wiąże najmocniej.** Kod, który czyta i pisze `.xlsx`
   (openpyxl i podmiana XML części zip z ADR 0008/0019), nie potrzebuje Windows ani Excela i działa na
   serwerze z Linuksem. Excel jako program jest potrzebny do trzech rzeczy:
   - liczy formuły: `Kwota` (AU) Pliku zbiorczego i kwoty Rozliczeń pracowników powstają ze stawek
     we Wzorcach, a narzędzie tylko ustawia `fullCalcOnLoad` (`template_copy.py:240-243`, ADR 0008:56)
     i czyta wartość, którą Excel zapisał (`workbook_files.py:314-325`);
   - tata wpisuje w nim Ilości usług (N:AP, Uzupełnienie);
   - wygląd komórek niesie znaczenie domeny: krój Calibri 8 i żółty wiersz w Uporządkowaniu
     INTERMAX, kolor `ADRES` jako Znacznik efenix.
2. **Rdzeń „jeden użytkownik, jeden komputer” to ADR 0004.** Centrum słucha tylko na `127.0.0.1`,
   nie ma logowania ani bazy, a stan liczy przy każdym odczycie z plików w OneDrive i w katalogu
   narzędzia (ADR 0004:52-57).
   Wszystko inne, czyli blokady, kolejka w plikach i jedno Uruchomienie naraz, wynika z tej decyzji.
3. **Najtrudniej przenieść Wycenę w efenix.** Narzędzie pracuje w widocznym oknie Chrome taty, w
   sesji, w którą tata sam się loguje (ADR 0024:20). Na serwerze nie ma ani taty, ani ekranu.
4. **Rzeczy typowo windowsowe łatwo usunąć.** `pythonw`, skrót, Git for Windows, `winreg`, Job
   Objects, `msvcrt`, `tkinter` i `os.startfile` siedzą w kilku modułach startu i Aktualizacji
   narzędzia (~2,7 tys. linii) i w chmurze po prostu znikają.
5. **Około 6,9 tys. linii logiki domeny nie zna Excela** i przenosi się bez zmian albo po odpięciu
   kilku typów z `workbook_files`, razem z testami.
   Do tego dochodzi ~2 tys. linii katalogów Komunikatów, których treść trzeba przepisać.
   Wejście/wyjście Excela to ~6,8 tys. linii: w chmurze staje się importem i eksportem.

## Skala trudności

- **Łatwa:** zamiana adaptera albo konfiguracji, albo usunięcie kodu, który w chmurze traci sens; logika i testy bez zmian.
- **Średnia:** nowy adapter za istniejącym seamem (wstrzykiwane `Platform`, `ReportBox`, `Disk`, `DadFiles`, `Efenix`) albo zmiana kontraktu API, bez zmiany reguł domeny.
- **Trudna:** zmienia model danych albo źródło prawdy, przenosi logikę z formuł Excela do kodu, albo wymaga decyzji produktowej.

## Centrum rozliczeń jako gospodarz (wspólne dla wszystkich procesów)

| Zależność | Gdzie dziś | Co ją zastępuje w chmurze | Trudność |
|---|---|---|---|
| Nasłuch tylko na `127.0.0.1`, odmowa `Host` spoza localhost, `Origin` dla akcji, brak logowania | `tool_files.py:41`, `centrum/app.py:80-81`, `centrum/app.py:140-143`, ADR 0004:52-55, uzasadnienie ADR 0004:121 | HTTPS za reverse proxy, uwierzytelnianie (sesja albo OIDC), role (admin, właściciel, edytujący Rejestr, technik), CSRF zamiast sprawdzenia `Origin` na localhost | Średnia |
| Brak bazy: stan (Tablica okresów, Status okresu, Historia) liczony przy każdym odczycie z folderu okresów, plików metryk i konfiguracji | ADR 0004:54-57, `centrum/period_board.py:1-9`, `period_folder.py:225-235` | Baza SQL jako źródło prawdy; Status okresu i Historia z rekordów | Trudna |
| Jedno Uruchomienie naraz na cały serwer, blokada w pamięci procesu, wspólna z Aktualizacją i przywróceniem Kopii | `centrum/runs.py:1`, `centrum/runs.py:228-236`, `centrum/runs.py:276-311` | Blokada w bazie dla zasobu (okres, Rejestr), zadania w kolejce, kilku workerów | Średnia |
| Proces w tle bez konsoli: skrót `pythonw`, natywne okienko błędu startu, jedno Centrum na port | `centrum/shortcut.py:48-56`, `centrum/platform.py:40-90`, `centrum/launcher.py:1-12`, `tool_files.py:42` | Usługa systemd albo kontener; błąd startu jako alert dla Maksa | Łatwa |
| Otwarcie pliku w Excelu albo folderu w Eksploratorze na pulpicie taty (`os.startfile`) | `centrum/platform.py:109-113`, trasy `openPeriodPath` (`centrum/period_board.py:239`), `openRegister` (`centrum/settings_router.py:42`) | Pobranie wygenerowanego pliku albo link do pliku w OneDrive/SharePoint; w przeglądarce, także na telefonie | Średnia |
| Okna wyboru `tkinter` na Rejestr zleceń i folder okresów; Ustawienia taty w lokalnym YAML | `centrum/platform.py:115-121`, `centrum/settings.py:1-5`, ADR 0006:55 | Konfiguracja serwera; przy bazie Rejestr i okresy przestają być ścieżkami | Łatwa |
| „Zamknij Centrum rozliczeń” i odmowa zamknięcia w trakcie Uruchomienia | `centrum/shutdown.py:1-7` | Znika; serwer działa 24/7 | Łatwa |
| Pliki stanu w katalogu narzędzia: metryki `.jsonl`, dziennik pochodzenia, dziennik Centrum, działania taty | `tool_files.py:34-39`, `telemetry.py:180-212`, `centrum/run_origins.py:1-6`, `centrum/log.py:1-8`, `centrum/dad_actions.py:36` | Tabele w bazie i logi strukturalne z alertami (kryterium 4 mapy); działania przypisane do użytkownika, nie do „taty” | Łatwa |
| Atomowa podmiana pliku z ponowieniem, gdy Windows trzyma plik (antywirus, indeksowanie) | `centrum/atomic_file.py:1-5` | Transakcja w bazie | Łatwa |
| Czas lokalny komputera (`datetime.now().astimezone()`) | `centrum/app.py:104`, `intermax_copies.py:52` | Jawna strefa `Europe/Warsaw` na serwerze w UTC; dzień Uporządkowania i token okresu tego wymagają | Łatwa (łatwo przeoczyć) |

## Proces × zależność × odpowiednik w chmurze × trudność

| Proces | Zależność | Gdzie dziś | Co ją zastępuje w chmurze | Trudność |
|---|---|---|---|---|
| Uporządkowanie INTERMAX | Rejestr zleceń to jeden skoroszyt w OneDrive; zapis podmienia XML arkusza zleceń od bloku Surowych zleceń w dół | ADR 0019:28-59, `intermax_file.py` (563 l.), `intermax_ordering.py` | Rejestr zleceń jako tabela SQL; Uporządkowanie to transakcja, która przenosi zlecenia dnia. Dopóki Excel jest zabezpieczeniem: eksport albo synchronizacja do skoroszytu | Trudna |
| Uporządkowanie INTERMAX | Surowe zlecenia rozpoznaje po wyglądzie komórek: uporządkowany wiersz ma Calibri 8, dni dzieli żółty wiersz | `raw_orders.py:5-12`, `raw_orders.py:458` | Stan zlecenia (wklejone/uporządkowane) jako pole; wklejenie z aplikacji firmowej przez import albo formularz. Rozpoznanie po kroju znika, a plan dnia i Wpis urządzenia i czynności INTERMAX (ADR 0019) zostają | Średnia |
| Uporządkowanie INTERMAX | INTERMAX musi być zamknięty w Excelu (plik blokady `~$`) i zwolniony przez OneDrive (ponowienie podmiany) | `workbook_files.py:243-270`, `intermax_replace.py:10`, `intermax_replace.py:59-60`, ADR 0019:99 | Transakcje i blokady wierszy; przy wielu edytujących trzeba zdecydować, co robić z konfliktem edycji | Średnia |
| Uporządkowanie INTERMAX | Kopie INTERMAX w katalogu narzędzia na dysku lokalnym, poza OneDrive, 10 ostatnich | `intermax_copies.py:22`, `intermax_copies.py:41-44`, ADR 0019:92 | Kopie zapasowe bazy (punkt w czasie) i historia zmian wierszy | Łatwa |
| Przywrócenie Kopii INTERMAX | Przywrócenie podmienia cały INTERMAX bajtami Kopii, po Kopii stanu bieżącego, tą samą podmianą co Uporządkowanie | `intermax_restore.py:1-5`, `intermax_replace.py:1-15`, trasa `restoreIntermaxCopy` (`centrum/intermax_run.py:195`) | Cofnięcie zmian jednego Uporządkowania z historii zmian. Przywrócenie całości przy wielu użytkownikach cofnęłoby też pracę innych, więc to decyzja produktowa | Trudna |
| Przywrócenie Kopii INTERMAX | Te same blokady Excela i OneDrive co przy Uporządkowaniu | `intermax_restore.py:71` | Jak wyżej | Średnia |
| Przygotowanie pliku zbiorczego | Czyta okres z Rejestru zleceń przez openpyxl na zawężonym XML (dziesiątki tysięcy wierszy od 2021) | `workbook_parts.py:18-26`, `register_file.py` (533 l.), `preparation_register.py` | Zapytanie SQL o zlecenia okresu | Średnia |
| Przygotowanie pliku zbiorczego | Wzorzec pliku zbiorczego i Wzorzec rozliczenia wewnętrznego w `config/`; stawki, sumy i formuły są w skoroszycie; zapis z wymuszonym przeliczeniem przy otwarciu | `tool_files.py:28-30`, `template_file.py:88`, `template_file.py:101`, `template_file.py:502` | Krótko: Plik zbiorczy dalej jako `.xlsx` generowany na serwerze z tego samego Wzorca (kod działa bez Excela). Docelowo: Plik zbiorczy jako widok bazy, a stawki w tabeli cennika | Średnia (eksport) / Trudna (bez Excela) |
| Przygotowanie pliku zbiorczego | Folder okresu w OneDrive zakłada tata, a narzędzie go szuka; publikacja obu plików razem przez pliki tymczasowe obok celu | ADR 0006 pkt 2-3, `period_folder.py:225-235`, `preparation_files.py:146` | Okres jako rekord; pliki eksportu w magazynie obiektów albo zapis do OneDrive przez API; publikacja jako transakcja | Średnia |
| Uzupełnienie pliku zbiorczego (krok między Przygotowaniem a Przebiegiem) | Tata wpisuje Ilości usług w Excelu, a Centrum czyta zapisany plik, także gdy trzyma go Excel, i odpytuje znacznik zapisu przez `stat` | ADR 0016:11, `centrum/filling.py:1-10`, `centrum/live_file.py:1-8`, `workbook_files.py:257-270` | Formularz Ilości w aplikacji (web i telefon), zapis do bazy, wielu edytujących naraz. Dziś to główna ręczna praca taty | Trudna |
| Przebieg rozliczeń | Plik zbiorczy jest jedynym wejściem i czyta go openpyxl | GLOSSARY „Plik zbiorczy”, `collective_file.py:46`, `workbook_files.py:453-464` | Wiersze danych okresu z bazy | Średnia |
| Przebieg rozliczeń | Rozliczenie pracownika to kopia bajtów Wzorca z podmienionymi wierszami; formuły AU:AY i stawki pracownika liczy Excel przy otwarciu | ADR 0008:38-80, `template_copy.py` (1411 l.), `template_copy.py:240-243` | Krótko: dalej `.xlsx` z serwera, ten sam kod. Docelowo: kwoty pracownika liczone w kodzie z cennika pracownika | Łatwa (dalej `.xlsx`) / Trudna (bez Excela) |
| Przebieg rozliczeń | Konfiguracja wykonawców w YAML w `config/` | `tool_files.py:27`, `worker_config.py` | Tabela Pracowników (z profilami z grilla UX 26.10) | Łatwa |
| Przebieg rozliczeń | Folder rozliczeń pracowników powstaje w folderze tymczasowym w OneDrive i jest publikowany zmianą nazwy | `settlement_files.py:1-9` | Pliki w magazynie obiektów albo w OneDrive przez API, publikacja atomowa po stronie serwera | Średnia |
| Wycena w efenix | Widoczne okno zainstalowanego Google Chrome w trwałym profilu w katalogu narzędzia; tata loguje się sam, a narzędzie nie zna hasła | `efenix_browser.py:852-855`, `efenix_browser.py:921-942`, `centrum/efenix_chrome.py:1-9`, ADR 0024:20 | Sposób do decyzji. Możliwości: (a) Chromium na serwerze, w którym tata loguje się przez zdalny podgląd okna; (b) dane logowania jako sekret serwera, co odwraca ADR 0024; (c) mały agent przeglądarki na komputerze użytkownika, sterowany z serwera | Trudna |
| Wycena w efenix | Ludzkie tempo (~20 s na zlecenie z zapisem), wątek roboczy serwera, dziennik Wyceny na dysku do zamknięcia Urwanego Uruchomienia | ADR 0024 (Tempo), `centrum/logs_disk.py:24`, `centrum/logs_disk.py:70` | Długie zadanie w kolejce zadań z postępem i dziennikiem w bazie; zamknięcie przeglądarki taty nic nie przerywa | Średnia |
| Wycena w efenix | `Kwota` (AU) musi być już policzona przez Excel; bez niej Planowanie się zatrzymuje | `efenix_pricing.py:5`, `efenix_pricing.py:380`, `workbook_files.py:523-533` | `Kwota` liczona w kodzie z cennika (formuły Wzorca pliku zbiorczego przeniesione i sprawdzone na danych taty) | Trudna |
| Wycena w efenix | Znacznik efenix to wypełnienie komórki `ADRES` w Pliku zbiorczym, zapis XML bez openpyxl i bez pliku blokady | `efenix_marking.py:1-20`, `efenix_mark.py:17` | Pole stanu wyceny zlecenia w bazie; kolor tylko w eksporcie | Łatwa (po przeniesieniu Pliku zbiorczego) |
| Wycena w efenix | Obejście Windows (`TcpPortRandomizationWin`) | `efenix_browser.py:856-861` | Znika na Linuksie | Łatwa |
| Kolejka wysyłki i Skrzynka Zgłoszeń | Kolejka to pliki JSON w `config/zgloszenia/kolejka/`; jedno przejście naraz pilnuje blokada pliku `msvcrt`/`fcntl` | `centrum/outbox.py:8`, `centrum/outbox.py:95-98`, `centrum/outbox.py:156`, `centrum/outbox.py:177-215` | Tabela wysyłek w bazie i worker (`SELECT … FOR UPDATE SKIP LOCKED`). Semantyka dokładnie raz ze znaczników (#840) zostaje | Średnia |
| Kolejka wysyłki i Skrzynka Zgłoszeń | Token do Zgłoszeń w pliku `config/zgloszenia-klucz.txt` na komputerze taty | ADR 0007:46-48, `centrum/keyed_box.py:1-4` | Sekret serwera (zmienna środowiska albo menedżer sekretów) | Łatwa |
| Kolejka wysyłki i Skrzynka Zgłoszeń | Reguła danych mówi, czego „nigdy nie wysyła z komputera taty” | ADR 0025:51-58, `centrum/run_logs_guard.py` | Dane klientów będą już na serwerze. Strażnik zostaje dla wszystkiego, co wychodzi do GitHuba, ale ADR 0025 trzeba przepisać na granicę „serwer → zewnętrzne usługi” | Średnia (decyzja) |
| Kolejka wysyłki i Skrzynka Zgłoszeń | Logi Uruchomienia jako pliki JSON w `logs/uruchomienia/` na `C:`; Skrzynka to jedyna droga, którą Maks je widzi | ADR 0015:129, `centrum/run_logs.py:74`, `centrum/logs_disk.py:449-487` | Logi w bazie albo w magazynie na serwerze, wgląd Maksa jako admina. Skrzynka na GitHubie zostaje dla Zgłoszeń albo znika | Łatwa / Średnia |
| Kolejka wysyłki i Skrzynka Zgłoszeń | Diagnoza sprawdza granice komputera taty: plik „tylko online” OneDrive (atrybut pliku Windows) i Wydanie | `centrum/cloud_files.py:17`, `centrum/cloud_files.py:47-50`, `centrum/diagnosis.py:152` | Sprawdzenia serwera: baza, dostęp do OneDrive przez API, sesja efenix | Średnia |
| Kolejka wysyłki i Skrzynka Zgłoszeń | Sprawy taty w `config/sprawy-taty.json` | `centrum/dad_cases.py:15` | Tabela spraw z autorem | Łatwa |
| Powiadomienia | Przeczytane Powiadomienia w `config/powiadomienia.json`, czyli jeden czytelnik | `centrum/notifications.py:21` | Stan przeczytania dla każdego użytkownika w bazie | Łatwa |
| Powiadomienia | Źródła to sprawy wysłane „z tego komputera”, nowe Wydania i zakończone Wyceny z Logów na dysku | `centrum/notifications.py:1-2`, `centrum/notifications.py:8-12` | Zdarzenia z bazy. Powiadomienie o nowym Wydaniu z przyciskiem Aktualizacji traci sens; mail albo push na telefon to nowy kanał | Łatwa (źródła) / Średnia (push) |
| Aktualizacja narzędzia | Klon Gita u taty, Git for Windows szukany w rejestrze (`winreg`), `pip install` tym samym Pythonem | ADR 0009:52-65, `centrum/tool_update.py:271-278` | Wdrożenie na serwer z CI (obraz, migracje bazy, wycofanie). Przycisk taty znika | Łatwa (usunięcie) / Średnia (pipeline i migracje) |
| Aktualizacja narzędzia | Opiekun ponownego startu: odłączony proces `pythonw.exe`, Job Objects, dziennik „Aktualizacja w toku” i cofnięcie przy następnym starcie skrótu | `centrum/restart_guardian.py:72`, `centrum/restart_guardian.py:219-235`, `centrum/tool_update.py:825-933`, ADR 0009:66-90 | Sprawdzenie zdrowia po wdrożeniu i automatyczne wycofanie po stronie wdrożenia | Łatwa |
| Aktualizacja narzędzia | Wydania jako tagi `v*` na `main`; Aktualność pyta API GitHuba z adresu IP taty (limit 60 na godzinę bez tokenu) | ADR 0014:36, ADR 0014 (Aktualność) | Wydanie zostaje bramką wdrożenia na serwer; pytania o Aktualność znikają | Łatwa |

## Logika domeny, która nie zależy od Excela

„Bez zmian” znaczy, że moduł nie importuje openpyxl, `zipfile` ani XML i nie czyta plików taty.
„Po odpięciu” znaczy, że moduł bierze z `workbook_files` tylko typy wiersza (`DataRow`, `RegisterRow`) i pomocniki
(`is_blank`, `cell_datetime`) albo z `openpyxl.utils` zamianę numeru kolumny na literę; reguł nie trzeba zmieniać.

| Grupa | Moduły | Linie | Jak się przenosi |
|---|---|---|---|
| Reguły ilości, Kontrola ilości, fakty zlecenia, układ kolumn, okres | `quantity_rules`, `quantity_check`, `quantities_to_fill`, `order_facts`, `inea_only_quantities`, `collective_layout`, `register_columns`, `settlement_period`, `domain`, `text`, `preparation_plan` | 1 522 | Bez zmian (`quantity_rules`, `quantity_check`, `quantities_to_fill`, `settlement_period`, `domain`, `text`); po odpięciu (`order_facts`, `inea_only_quantities`, `preparation_plan`) |
| Plan dnia Uporządkowania INTERMAX | `raw_orders` | 690 | Czyste funkcje, ale rozpoznanie bloku stoi na kroju i wypełnieniu komórek (`raw_orders.py:5-12`); plan dnia zostaje, rozpoznanie po wyglądzie znika razem z Excelem |
| Reguły Wyceny w efenix bez przeglądarki | `efenix_address`, `efenix_window` (protokół okna), `efenix_checks`, `efenix_positions`, `efenix_pace`, `efenix_trace` | 1 178 | Bez zmian; `efenix_window` to seam, który implementuje dowolne okno (`efenix_window.py:1-13`) |
| Rdzeń Uruchomienia procesu: etapy, postęp, Decyzja taty, Komunikat | `process_run`, `phase_runner`, `progress`, `decision`, `message`, `run_clock`, `write_routes`, `call_trace` | 1 223 | Bez zmian; `process_run` zapisuje metryki przez `telemetry.MetricsStore` (plik `.jsonl`), który trzeba podmienić na tabelę |
| Reguła danych (maskowanie adresu, numeru Orange, telefonu, ulicy) | `client_data` | 229 | Bez zmian |
| Katalogi Komunikatów procesów | `settlement_messages`, `preparation_messages`, `intermax_messages`, `efenix_messages`, `workbook_messages`, `worker_config_messages` | 2 024 | Kod się przenosi, ale część treści mówi o Excelu i OneDrive („Zamknij Plik zbiorczy w Excelu, poczekaj, aż OneDrive…”, `efenix_messages.py:210`) i trzeba ją przepisać |
| **Razem bez Excela** | | **6 866** (~37% z 18 380 linii silnika) | plus ~2 tys. linii Komunikatów do przepisania |

W `centrum/` bez Excela i bez Windows są też:
- strażnik reguły danych dla Logów (`run_logs_guard`, 449 l.);
- schemat Logów Uruchomienia (`run_logs`, 682 l.);
- kontrakt API w pydantic (`contract`, 1 357 l.);
- logika kolejki dokładnie raz w `outbox`, z magazynem w plikach do podmiany.

To kod gospodarza, nie domeny, ale z testami przenosi się tak samo.

### Co dziś liczy Excel, a nie Python

Te reguły nie są w kodzie, więc nie przeniosą się razem z testami. Trzeba je wyjąć ze Wzorców:

- stawki i `Kwota` (AU) Pliku zbiorczego (`collective_layout.py:64`, „którą liczy formuła Pliku zbiorczego”);
- stawki i formuły AU:AY Rozliczenia pracownika (ADR 0008:38-80: formuły zostają bajt w bajt, Excel liczy je przy otwarciu);
- sumy i formuły Rozliczenia wewnętrznego.

## Liczby linii według grup modułów

| Grupa | Linie | Zależy od |
|---|---|---|
| Silnik: logika domeny bez Excela (tabela wyżej, z Komunikatami) | 6 866 | nic |
| Silnik: orkiestracja procesów (`engine`, `collective_preparation`, `efenix_pricing`, `intermax_ordering`, `run_context`, `*_process`, `efenix_orders`, `collective_file`) | 1 862 | wołają czytniki i zapis plików; kolejność etapów zostaje |
| Silnik: foldery i pliki lokalne (`period_folder`, `telemetry`, `worker_config`, `tool_files`, `settlement_files`, `preparation_files`, `intermax_copies`) | 1 345 | układ folderów w OneDrive, katalog narzędzia |
| Silnik: wejście/wyjście Excela (`workbook_files`, `workbook_parts`, `workbook_save`, `template_copy`, `template_file`, `register_file`, `intermax_file`, `intermax_restore`, `intermax_replace`, `efenix_marking`, `efenix_mark`, `highlights`, `hyperlinks`, `row_look`, `input_copy`, `dad_files`, `preparation_register`, `input_checks`) | 6 782 | openpyxl i XML części zip; bez Windows i bez programu Excel |
| Silnik: przeglądarka efenix (`efenix_browser`, `efenix_page`) | 1 524 | Playwright i Chrome taty |
| Centrum: start, Windows i Aktualizacja narzędzia (`launcher`, `server`, `platform`, `shortcut`, `restart_guardian`, `tool_update`, `tool_updates`, `version`, `shutdown`, `start_problems`, `cloud_files`, `efenix_chrome`, `update_messages`) | 2 671 | Windows, `pythonw`, Git u taty |
| Centrum: stan w plikach (`settings`, `atomic_file`, `dad_cases`, `notifications`, `outbox`, `logs_disk`, `run_origins`, `metrics`, `dad_actions`, `log`, `keyed_box`, `comment_versions`, `run_comments`, `case_delivery`, `dad_notes`) | 5 693 | `config/` i `logs/` w katalogu narzędzia |
| Centrum: GitHub (`github`, `report_box`, `tool_freshness`, `release_notes`, `reports`, `report_issue`, `report_messages`) | 1 969 | API GitHuba, Token do Zgłoszeń |
| Centrum: API i widoki (`app`, `contract`, `runs`, `run_view`, `run_cards`, `process_kind`, `catalog`, `period_board`, `period_start`, `filling`, `live_file`, `intermax_run`, `configuration`, `settings_router`, `stops`, `diagnosis` i drobne, `processes/*`) | 6 268 | FastAPI na localhost; stan liczony z plików |
| Centrum: Logi Uruchomienia i strażnik (`run_logs`, `run_logs_guard`, `logs_of_run`) | 1 260 | nic poza magazynem |
| Frontend (`frontend/src` bez `api/generated`; w tym 2 525 l. komponentów `ui`) | 11 588 | nic lokalnego poza przyciskami otwarcia pliku, wyboru ścieżki, zamknięcia i Aktualizacji (`lib/settings.tsx`, `pages/periods/open-period-path.ts`, `components/close-centrum.tsx`, `lib/tool-update.tsx`) |
| Testy (`tests/`) | 85 400 w 207 plikach `.py` | 67 plików czyta albo tworzy `.xlsx` |

Suma silnika to 18 380 linii, a Centrum 17 862 (`wc -l`).

## Granice tego researchu

- Grupy zbudowałem z importów (`openpyxl`, `zipfile`, `xml`, `playwright`, `sys.platform`) i z docstringów modułów.
  Funkcji pojedynczo nie sprawdzałem, więc moduł mieszany trafił do grupy według swojej głównej zależności.
- Nie sprawdziłem, które trasy API w grupie „API i widoki” da się przenieść bez zmian.
  Każda, która czyta folder okresów, wymaga nowego źródła stanu.
- Nie mierzyłem, ile formuł mają Wzorce. Ich przeniesienie do kodu wymaga otwarcia prawdziwych Wzorców taty, czego ten research celowo nie robił.
- Moduł `centrum/github.py` (`github.py`, docstring o proxy) zostawia otwarte pytanie Maksa, czemu Aktualność łączy się wprost, a Skrzynka przez proxy systemu.
  Na serwerze to pytanie znika razem z proxy komputera taty.
