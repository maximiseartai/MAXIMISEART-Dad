# MAXIMISEART-Dad: rozliczenia pracowników

Lokalne narzędzie z dwoma procesami uruchamianymi co tydzień, w tej kolejności:

1. [Przygotowanie pliku zbiorczego](#przygotowanie-pliku-zbiorczego) tworzy z
   Rejestru zleceń Rozliczenie wewnętrzne i Plik zbiorczy okresu.
2. Przebieg rozliczeń rozdziela dane z Pliku zbiorczego na osobne szablony
   pracowników.

Narzędzie nie używa AI. Łączy się tylko z API GitHuba: przy Zgłoszeniach do
Maksa i sprawdzaniu ich stanu oraz przy sprawdzeniu aktualności narzędzia w
Diagnozie ([ADR 0007](docs/adr/0007-zgloszenia-do-maksa-w-prywatnym-repo.md)).
Instrukcja dla taty jest w
[`docs/tata-instrukcja.md`](docs/tata-instrukcja.md).

## Reguły Przebiegu rozliczeń

- Wejście: `Rozliczenie {okres} - zbiorcze.xlsx`.
- Folder wejścia ma nazwę identyczną jak `{okres}`, a `{okres}` jest tokenem okresu od wtorku do poniedziałku.
- Wyjście: `Rozliczenie pracowników {okres}`.
- Każdy skoroszyt pracownika powstaje z kopii wspólnego Wzorca rozliczenia pracownika.
- Powstaje dokładnie jeden skoroszyt dla każdego pracownika z konfiguracji.
- Wykonawca jest odczytywany z kolumny `H=WYKONAWCA`.
- Identyfikatory wykonawców są mapowane jawnie w `config/worker_mapping.yaml`
  (zob. [Konfiguracja wykonawców](#konfiguracja-wykonawców)).
- Kopiowane są wartości `A:AT` od wiersza 18, zwarte od wiersza 18.
- Arkusze, formuły, stawki i formatowanie Wzorca rozliczenia pracownika pozostają zachowane.
- Pusty szablon pozostaje pusty.
- Istniejący Folder rozliczeń pracowników nie jest nadpisywany ani scalany.
- Nieznany wykonawca lub błąd tworzenia skoroszytu wstrzymuje publikację całego folderu.

## Instalacja lokalna

Wymagany jest Python 3.11 lub nowszy na komputerze taty. Narzędzie to klon
publicznego repozytorium na gałęzi `main` ustawionej na najnowsze Wydanie
([ADR 0014](docs/adr/0014-tata-dostaje-tylko-wydania.md)), bo sam `git clone`
daje najnowszy `main`, także zmiany, które nie weszły do żadnego Wydania. Wydanie
wybiera się tak jak Centrum: najwyższy numer `vMAJOR.MINOR.PATCH` (bez
`-rc1` i innych dopisków) z tagów na commitach, które były czubkiem `main` (linia
pierwszych rodziców). Gdy `$wydanie` wyjdzie puste, na GitHubie nie ma jeszcze
Wydania i narzędzia nie instaluj:

```powershell
git clone https://github.com/maximiseartai/MAXIMISEART-Dad.git
cd MAXIMISEART-Dad
$czubki = git rev-list --first-parent origin/main
$wydanie = git tag --list "v*" --sort=-version:refname |
    Where-Object { $_ -cmatch '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' } |
    Where-Object { $czubki -contains (git rev-parse "$_^{commit}") } | Select-Object -First 1
git reset --hard $wydanie
py -3 -m pip install -r requirements.txt
```

Potem jednorazowo w folderze narzędzia:

```powershell
py -3 install_centrum_shortcut.py
```

Polecenie tworzy na pulpicie skrót „Centrum rozliczeń” (zob.
[Centrum rozliczeń](#centrum-rozliczeń-rozwój)). Powtórz je po przeniesieniu
folderu narzędzia albo po instalacji nowego Pythona. Tata pracuje wyłącznie w
Centrum rozliczeń ([ADR 0010](docs/adr/0010-centrum-jedynym-wejsciem-taty.md)).
Osoba utrzymująca narzędzie, testy E2E i pomiary czasu uruchamiają procesy
[skryptem dla maszyn](#skrypt-dla-maszyn)
([ADR 0011](docs/adr/0011-bez-cli-i-adapterow-terminala.md)).

Żeby „Wyślij do Maksa” zakładało Zgłoszenia, Maks tworzy w ustawieniach
GitHuba token fine-grained (tylko repozytorium
`MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia`, uprawnienie Issues: odczyt i
zapis, ważność do roku) i wpisuje go jako jedyną linię do
`config\zgloszenia-klucz.txt` na komputerze taty. Plik jest poza Gitem. Bez
niego Zgłoszenia czekają w Kolejce wysyłki w `config\zgloszenia\kolejka\` i
wychodzą same, gdy token się pojawi, a Konfiguracja pokazuje „Zgłoszenia: brak
tokenu”. Gdy GitHub nie przyjmuje tokenu (wygasł albo nie ma uprawnień),
Konfiguracja pokazuje „Zgłoszenia: token odrzucony”. W obu przypadkach tata
widzi przy Zgłoszeniu, Uwadze taty i w Powiadomieniach „Token do Zgłoszeń nie
działa. Skontaktuj się z Maksem.”

Wspólny Wzorzec rozliczenia pracownika leży domyślnie w
`config\Wzorzec rozliczenia pracownika.xlsx`. Plik wcześniej nazywał się
`config\placeholder.xlsx`. Gdy brakuje Wzorca rozliczenia pracownika, a obok
leży `placeholder.xlsx`, komunikat podpowiada zmianę nazwy pliku.

Przed pierwszym prawdziwym Przebiegiem rozliczeń użyj w Centrum `Podgląd bez
zapisu`. Podgląd sprawdza, czy folder wynikowy jest wolny, i pokazuje nazwy
wszystkich planowanych plików oraz liczbę wierszy dla każdego wykonawcy. Nie
tworzy folderu ani skoroszytów. Zwykły przebieg przygotowuje wszystkie kopie i
uzupełnia je w katalogu tymczasowym, a Folder rozliczeń pracowników publikuje
dopiero po powodzeniu całej partii. Błąd nie zostawia częściowego folderu.
Historia czasów jest dopisywana lokalnie do `.rozliczenia-metrics.jsonl`. P50 i
P95 pojawiają się w Metrykach Centrum po pięciu ukończonych obserwacjach tego
samego trybu (`RUN` albo `DRY-RUN`).

### Konfiguracja wykonawców

Prawdziwa Konfiguracja wykonawców zawiera imiona i nazwiska pracowników taty,
więc leży tylko na jego komputerze, tak jak Wzorce: `config/worker_mapping.yaml`
jest w `.gitignore`. W repozytorium jest tylko
`config/worker_mapping.example.yaml` z syntetycznymi Wykonawcami, który pokazuje
format. Przy instalacji skopiuj na komputer taty jego prawdziwy plik jako
`config\worker_mapping.yaml`; bez niego oba procesy zatrzymują się w Sprawdzaniu
z komunikatem o Konfiguracji wykonawców. Testy i skrypty weryfikacyjne używają
wyłącznie syntetycznych Wykonawców i nie czytają tego pliku.

Plik był kiedyś śledzony w repozytorium. Commit, który przestał go śledzić,
usuwa go przy `git pull` z kopii, w której jeszcze był śledzony. Pierwszą
aktualizację po tej zmianie u taty zrób więc tak (`git checkout` cofa lokalną
zmianę pliku, przez którą `git pull` by się zatrzymał; kopia ją zachowuje):

```powershell
Copy-Item config\worker_mapping.yaml "$env:TEMP\worker_mapping.yaml"
git checkout -- config/worker_mapping.yaml
git pull
Copy-Item "$env:TEMP\worker_mapping.yaml" config\worker_mapping.yaml
```

Jeśli `git pull` przeszedł bez tego kroku, odzyskaj plik ze stanu sprzed
aktualizacji i przestań go śledzić:

```powershell
git checkout ORIG_HEAD -- config/worker_mapping.yaml
git rm --cached config/worker_mapping.yaml
```

## Przygotowanie pliku zbiorczego

Proces poprzedzający Przebieg rozliczeń, uruchamiany osobno. Z Rejestru zleceń
tworzy w Folderze okresu razem Rozliczenie wewnętrzne i Plik zbiorczy. Oba pliki
powstają razem albo żaden.

### Reguły procesu

- Wejście: Rejestr zleceń (`ZLECENIA INTERMAX OD 08_11_2021.xlsx`), folder
  okresów (u taty `Załączniki`, w układzie płaskim np. `INEA`) i token okresu.
- Okres rozliczeniowy trwa od wtorku 00:00 do następnego wtorku 00:00. Token
  `dd_dd_mm_rrrr` zawiera dzień wtorku, dzień poniedziałku oraz miesiąc i rok
  poniedziałku, np. `08_14_09_2026`, a na przełomie miesięcy `27_02_11_2026`
  (27.10–02.11.2026) i lat `29_04_01_2027` (29.12.2026–04.01.2027).
- Arkusz ze zleceniami jest wybierany po wymaganych nagłówkach w pierwszym
  wierszu, nie po nazwie. Inne arkusze są ignorowane. Kolumny Rejestru są
  rozpoznawane po nagłówkach, nie po literach, więc ich kolejność i dodatkowe
  kolumny (np. `AKCJE`, `ZWROT`, `UWAGI`) nie zmieniają plików okresu.
- Zlecenie należy do okresu po dacie w `DATA GODZ. POCZ.`, niezależnie od
  miejsca w arkuszu. Kolejność z Rejestru jest zachowana, a całkowicie puste
  wiersze są pomijane.
- Zakres okresu w Rejestrze to wiersze od pierwszego do ostatniego zlecenia
  okresu. `Pominięte puste wiersze` to liczba wszystkich całkowicie pustych
  wierszy w tym zakresie, także leżących między zleceniami innych okresów
  (np. przed spóźnionym zleceniem dopisanym na końcu). W tym samym zakresie
  wiersz z danymi bez poprawnej daty zatrzymuje proces.
- Rozliczenie wewnętrzne (`Rozliczenie wew. {okres}.xlsx`) zawiera wszystkie
  zlecenia okresu, skuteczne i nieskuteczne, w kolumnach dopasowanych po
  nagłówkach. `zwrot` i `UWAGI` zostają puste.
- Kolumny docelowe są ustalane wyłącznie po nagłówkach wzorca. Pary o innym
  zapisie są jawne w mapowaniu: `DATA GODZ. POCZ.` → `DATA`, `NUMER UMOWY` →
  `NUMER UMOWY/ZLECENIA ORANGE`. Wielkość liter i spacje w nagłówkach nie mają
  znaczenia (`adres` to `ADRES`). Dwa nagłówki Rejestru mają po dwa przyjmowane
  zapisy: `NUMER ZL.` albo `nr zlecenia` oraz `NUMER UMOWY` albo
  `NUMER UMOWY/ZLECENIA ORANGE`; pierwszy to zapis nowego Rejestru taty, drugi
  starszej kopii. Oba zapisy jednej kolumny naraz to powtórzony nagłówek.
  Wzorzec z nagłówkiem w zapisie Rejestru zamiast własnego oznacza zatrzymanie.
- Plik zbiorczy (`Rozliczenie {okres} - zbiorcze.xlsx`) zawiera każde Zlecenie
  skuteczne w `A:K` od wiersza 18, bez przerw, a w `N:AP` jego Ilości usług
  według Reguł ilości (ADR 0012), tylko różne od zera i w wyglądzie komórki
  wzorca. Pozostałe komórki `N:AP` (np. zera), wiersze 1–17, formuły i odwołania
  zewnętrzne (`xl/externalLinks/*`) zostają z wzorca.
  openpyxl nie zapisuje wyników formuł, więc Plik zbiorczy, tak jak Szablony
  pracowników, prosi Excela o przeliczenie formuł przy otwarciu.
- Reguły ilości czytają `URZĄDZENIA` jako składniki (`nokia zte`, `n*fut`,
  `wifi6extra`, `usterka`, `gniazdo`). T wynika z pierwszego słowa `UMOWA`, a
  liczba sztuk instalacji ręcznej z `CZYNNOŚCI`. Usterka od poniedziałku do
  piątku od 17:00 i w sobotę dostaje dodatek 45 w N według `DATA`. Wiersz z
  prewencją, niedostępnością usług albo pustymi `URZĄDZENIA` zostaje bez
  ilości, a wiersz z nieznanym składnikiem dostaje tylko V, T i N. Oba
  rodzaje wierszy dają ostrzeżenie z numerami wierszy Pliku zbiorczego. Każde
  Przygotowanie przypomina też o kolumnach z opisu technika (`Y`, `AB`, `AD`,
  `AJ`, `AK`, `AL`, `AM`), które uzupełnia tata. Dlatego zapis kończy się
  wynikiem wymagającym sprawdzenia, a podgląd bez zapisu z tymi samymi
  ostrzeżeniami wynikiem OK.
- Reguły ilości są w `src/rozliczenia/quantity_rules.py`, a
  `tests/test_ilosci_uslug.py` sprawdza je z każdą linią instrukcji taty.
  `tools/pomiar_regul_ilosci.py` porównuje je z Plikami zbiorczymi, które
  wypełnił tata. Uruchamia go tylko Maks na swoim Macu, a wynik to same liczby
  i teksty `URZĄDZENIA`.
- Wypełnienia, kolory czcionki, pogrubienia, kursywa i formaty dat przechodzą z
  Rejestru. Krój i rozmiar czcionki, szerokości kolumn, wysokości wierszy,
  nagłówek i blokada nagłówka pochodzą z wzorca. Autofiltr obejmuje nagłówek i
  wiersze danych.
- Folder okresu leży w układzie folderów taty w
  `{folder okresów}\Rozliczenia {rok}\{miesiąc}\INEA\{okres}`, a w układzie
  płaskim w `{folder okresów}\{okres}`. Układ folderów taty obowiązuje, gdy
  folder okresów ma foldery `Rozliczenia {rok}`. Miesiąc to cykl rozliczeniowy
  taty, więc Folder okresu jest szukany we wszystkich miesiącach, a nie
  wyliczany. W układzie folderów taty brak Folderu okresu albo ten sam okres w
  dwóch miesiącach zatrzymuje proces; w płaskim brakujący Folder okresu powstaje
  przy zapisie ([ADR 0006](docs/adr/0006-uklad-folderow-taty-i-wspolne-ustawienia.md)).
- Folder okresu może już istnieć. Nienadpisywanie: jeśli istnieje w nim
  którykolwiek z dwóch plików okresu, proces się zatrzymuje.
- Oba pliki są przygotowywane w katalogu tymczasowym i publikowane razem. Błąd
  nie zostawia żadnego z nich ani nowo założonego Folderu okresu. Wyjątek
  zaakceptowany w [ADR 0005](docs/adr/0005-przerwana-publikacja-plikow-okresu.md):
  do istniejącego Folderu okresu pliki trafiają dwoma przeniesieniami, więc
  proces zamknięty między nimi zostawia samo Rozliczenie wewnętrzne.
- Rejestr zleceń i wzorce są tylko czytane.
- Zatrzymania i ostrzeżenia mają trzy części: co się stało, gdzie, co zrobić.
  Pełna lista z instrukcją postępowania jest w tabeli „komunikat → co zrobić”
  w [`docs/tata-instrukcja.md`](docs/tata-instrukcja.md). Wykonawcy Zleceń
  skutecznych są sprawdzani w tej samej `config/worker_mapping.yaml` co w
  Przebiegu rozliczeń.

### Wzorce

Oba wzorce leżą w katalogu konfiguracji obok Wzorca rozliczenia pracownika
używanego przez Przebieg rozliczeń:

- `config\Wzorzec rozliczenia wewnętrznego.xlsx`: nagłówki w wierszu 1
  aktywnego arkusza, bez zleceń;
- `config\Wzorzec pliku zbiorczego.xlsx`: stawki i sumy w wierszach 1–16,
  nagłówki `A17:K17`, wiersze przygotowane zerami w `N:AP`, formuły i link do
  Słownika.

Pliki `*.xlsx` nie trafiają do repozytorium. Wzorce przygotowuje człowiek z
pustych plików taty; kod nie poprawia ich wyglądu. Komórki wzorca, do których
trafiają zlecenia, nie mogą być scalone; sprawdza to już `Podgląd bez zapisu`.

### Uruchomienie

Tata uruchamia proces w Centrum rozliczeń. Rejestr zleceń i folder okresów
pochodzą z Ustawień taty (`config\centrum-ustawienia.yaml`), a Centrum
proponuje ostatni pełny okres przed dzisiejszą datą.

`Podgląd bez zapisu` wykonuje w całości etapy Sprawdzanie, Odczyt danych i
Planowanie, łącznie z Nienadpisywaniem, regułami zleceń i ostrzeżeniami.
Pokazuje plan: liczbę zleceń okresu, Zleceń skutecznych i pominiętych pustych
wierszy, liczby zleceń na każdy dzień, ostrzeżenia oraz nazwy obu plików. Nie
tworzy plików ani Folderu okresu; dopisuje tylko rekord do historii czasów.

Przy zapisie, gdy ostatnie zlecenie okresu jest sprzed poniedziałku, Centrum po
etapie Planowanie, a przed Zapisywaniem, pokazuje ostrzeżenie o niepełnym
okresie z liczbami na dzień. `Kontynuuj` zapisuje oba pliki, `Przerwij bez
zapisu` kończy Zatrzymaniem. Silnik o nic nie pyta: przekazuje plan, a decyzję
podejmuje tata. Rejestr jest czytany raz, a czas oczekiwania na odpowiedź nie
wlicza się do czasu uruchomienia ani do historii czasów.

Historia czasów jest dopisywana do `.przygotowanie-pliku-zbiorczego-metrics.jsonl`,
osobno od historii Przebiegu rozliczeń, w tym samym formacie rekordu i trybach
`RUN`/`DRY-RUN`. Liczniki to zlecenia okresu, Zlecenia skuteczne, pominięte
puste wiersze i ostrzeżenia.

## Skrypt dla maszyn

`tools/uruchom_proces.py` uruchamia jeden proces bez Centrum, przez ten sam
rdzeń Uruchomienia procesu. Nie jest wejściem taty. Służy weryfikacji
end-to-end, straży czasu w CI, benchmarkowi i osobie utrzymującej narzędzie.
Nie czyta Ustawień taty, nie otwiera okien wyboru i nie pyta o nic: każdą
Decyzję taty, np. o niepełnym okresie, odrzuca.

```sh
.venv/bin/python tools/uruchom_proces.py settlement --dry-run --source "Rozliczenie 08_14_09_2026 - zbiorcze.xlsx"
.venv/bin/python tools/uruchom_proces.py preparation --dry-run --register "ZLECENIA INTERMAX OD 08_11_2021.xlsx" --periods-directory INEA --period 08_14_09_2026
```

| Parametr | Proces | Domyślnie | Znaczenie |
|---|---|---|---|
| `--source` | `settlement` | wymagany | Plik zbiorczy. |
| `--worker-template` | `settlement` | `config\Wzorzec rozliczenia pracownika.xlsx` | Wzorzec rozliczenia pracownika. |
| `--register` | `preparation` | wymagany | Rejestr zleceń. |
| `--periods-directory` | `preparation` | wymagany | Folder okresów z Folderami okresu. |
| `--period` | `preparation` | wymagany | Token okresu. |
| `--internal-template` | `preparation` | `config\Wzorzec rozliczenia wewnętrznego.xlsx` | Wzorzec rozliczenia wewnętrznego. |
| `--collective-template` | `preparation` | `config\Wzorzec pliku zbiorczego.xlsx` | Wzorzec pliku zbiorczego. |
| `--config` | oba | `config\worker_mapping.yaml` | Konfiguracja wykonawców. |
| `--metrics` | oba | plik metryk procesu | Lokalna historia czasów. |
| `--dry-run` | oba | wyłączony | Podgląd bez zapisu. |

Na stdout trafia jeden obiekt JSON w kształcie kontraktu Centrum: wynik,
podsumowanie z karty Uruchomienia, ostrzeżenia i Zatrzymanie z kodem
Komunikatu, ostatni stan postępu, `Czas uruchomienia` i informacja o zapisie
metryk. Pełny opis pól jest w opisie skryptu (`--help`). Kody wyjścia: `0` OK,
`2` Wymaga sprawdzenia, `1` Zatrzymanie albo błędne argumenty. Przygotowanie z
zapisem kończy się kodem `2`, bo ma zawsze ostrzeżenia o ilościach do
uzupełnienia; podgląd bez zapisu z tymi samymi ostrzeżeniami kończy się kodem `0`.

## Testy

Testy tworzą syntetyczne pliki `.xlsx` w katalogu tymczasowym. Nie używają
plików z `praca-tata` i nie zawierają prawdziwych danych klientów.

```powershell
py -3 -m pytest
```

### Lokalne lintowanie i sprawdzanie typów

Kontrybutorzy mogą zainstalować zestaw developerski, a następnie uruchamiać
lintowanie i ścisły typecheck całego utrzymywanego kodu Pythona:

```powershell
py -3 -m pip install -e ".[dev]"
py -3 -m ruff check
py -3 -m mypy
```

Ruff i mypy obejmują aplikację, testy, narzędzia oraz skrypty weryfikacyjne.
Zakres plików jest ustawiony tylko w `pyproject.toml`; nowy plik `*.py` w
katalogu głównym albo w `scripts/` skilla w `.agents/skills/` jest sprawdzany
automatycznie.

Na macOS i Linuksie (bez `py -3`) zestaw developerski instaluje się przez
[`uv`](https://docs.astral.sh/uv/), a komendy uruchamia z `.venv`:

```sh
uv venv -p 3.12 .venv && uv pip install -p .venv -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m ruff check
.venv/bin/python -m mypy
```
Check formatowania nie jest wymagany. Sprawdzenia CI poza krokami E2E i Timing guard
(ruff, mypy, pytest, mutacje, frontend z odtwarzalnym buildem) odtwarza lokalnie
`.venv/bin/python tools/ci_lokalnie.py --tylko <zadania>` (Windows: `py -3 tools/ci_lokalnie.py --tylko <zadania>`).
Mutacje liczy CI na GitHubie (`mutations` w każdym runie, `change-mutations` nocą na `main`),
więc lokalnie biegną tylko z `--odtwarzam <id albo URL runu Actions>`, w którym padły na tej gałęzi
(run nocny odtwarza się na jego commicie).
Na macOS i Linuksie `tools/setup_worktree.py` włącza bramę `tools/hooks/pre-push`:
push agenta (zmienna `AI_AGENT` albo `CLAUDECODE`) przechodzi po ruff i mypy dla obu
systemów (`tools/ci_lokalnie.py --tylko ruff,mypy`), a push człowieka bez sprawdzania.
Pełne sprawdzenie robi CI na GitHubie.

W git worktree utwórz własne `.venv` przez `py -3 tools/setup_worktree.py`
(macOS i Linux: `python3 tools/setup_worktree.py`), bo `.venv` głównego
checkoutu importuje `src` głównego checkoutu.

`.venv/bin/python tools/sprzatanie.py` pokazuje lokalne worktree i gałęzie, których
praca jest już w `origin/main`, i niczego nie usuwa; usuwa je dopiero z `--usun`.
Zostawia każdy worktree z commitami spoza `origin/main`, zmianami, plikami nieśledzonymi,
niepustymi plikami ignorowanymi spoza `.venv`, `node_modules` i cache, żywym procesem
(także w podkatalogu), blokadą, rebase'em, merge'em albo bisect w toku albo aktywnym
wątkiem T3 i podaje powód.

Czas Przebiegu rozliczeń mierzy `tools/benchmark_przebiegu.py measure
--scenario typowy-tydzien` (albo `ciezki-tydzien`) na syntetycznym lustrze
folderów taty; `tools/benchmark_przebiegu.py comment` drukuje z dziennika
`.benchmark/przebieg.jsonl` komentarz Markdown do issue-dziennika wspinaczki.
Szczegóły i argumenty są w opisie narzędzia (`--help`).

Na Windows testy tworzą też skrót przez `install_centrum_shortcut.py` i
uruchamiają Centrum przez `pythonw.exe`.

## Centrum rozliczeń (rozwój)

Centrum rozliczeń to lokalny serwer (`src/rozliczenia/centrum/`) z
frontendem w przeglądarce (`frontend/`), opisany w
[ADR 0004](docs/adr/0004-centrum-rozliczen-adapter.md). Zbudowany frontend jest
commitowany w `src/rozliczenia/centrum/static/`, więc do uruchomienia
wystarczają zależności z `requirements.txt`, bez Node.

- Tata uruchamia Centrum skrótem „Centrum rozliczeń” z pulpitu. Skrót tworzy
  jednorazowo `py -3 install_centrum_shortcut.py`: wskazuje `pythonw.exe`
  tego samego Pythona co `py -3` i `run_centrum.py`, więc nie ma okna konsoli.
  Ponowne kliknięcie rozpoznaje działające Centrum po `/api/health` (tożsamość
  i commit narzędzia, z którego wystartowało) i tylko otwiera kartę. Błąd
  startu (port zajęty przez inny program, Centrum z innego commitu, brak
  biblioteki) bez konsoli pokazuje natywne okienko, z konsolą trzy linie
  komunikatu (`src/rozliczenia/centrum/start_problems.py`).
- `py -3 run_centrum.py` uruchamia Centrum z widoczną konsolą na `http://127.0.0.1:47811/` i otwiera kartę w
  przeglądarce. `--port` zmienia port, `--no-browser` nie otwiera karty.
- Serwer działa do kliknięcia „Zamknij Centrum rozliczeń” w karcie
  (`POST /api/shutdown`), Ctrl+C w konsoli albo wylogowania; zamknięcie karty
  go nie wyłącza.
- Dziennik Centrum `logs/centrum-rozliczen.log` (poza gitem) ma jedną linię na
  fakt: `start`, `juz-dziala`, `blad-startu`, `zamkniecie`, `stop`,
  `nieoczekiwany-wyjatek` (tylko typ i trasa, bez tekstu wyjątku) oraz
  `pomiar` po każdym gotowym widoku karty (zimny start strony, przejście w
  menu): strona z menu, czasy w ms i dla każdego zapytania API
  `operacja:przeglądarka/serwer`. Czas serwera każdej odpowiedzi API jest też
  w nagłówku `Server-Timing`; wpisy `pomiar` oddzielają wolny odczyt plików z
  OneDrive od wolnej przeglądarki.
- Ustawienia Centrum (Rejestr zleceń, folder okresów, motyw) są w
  `config/centrum-ustawienia.yaml`, poza gitem.
- Metryki czytają przy każdym odczycie oba pliki metryk
  (`.rozliczenia-metrics.jsonl`, `.przygotowanie-pliku-zbiorczego-metrics.jsonl`)
  bez zmiany schematu, więc widać w nich także Uruchomienia spoza Centrum.
  Mają odznakę `.cmd`: to stare Uruchomienia z dawnych launcherów i CLI oraz
  rekordy ze skryptu dla maszyn.

Zmiana frontendu wymaga Node 24 i kończy się commitem źródeł razem z
odbudowanym buildem; CI sprawdza, że build i kontrakt odpowiadają źródłom:

```sh
cd frontend
npm ci
npm run contract   # OpenAPI z modeli Pydantic → typy i schematy zod (Python z zależnościami: zmienna PYTHON)
npm run typecheck  # tsc strict
npm run lint       # Oxlint z wtyczkami anti-slop
npm run rules      # każde pole kontraktu użyte w UI, brak porównań nazwy procesu, sieć tylko w plikach NETWORK_FILES
npm run build      # build do src/rozliczenia/centrum/static/
```

- Zmiana kontraktu API to zmiana modeli Pydantic w `src/rozliczenia/centrum/contract.py`,
  potem `npm run regen` (kontrakt i build); `frontend/src/api/` i `static/` są generowane.
- Scalenie i rebase zostawiają w plikach generowanych wersję bieżącego HEAD bez konfliktu
  (`merge=wygenerowane` w `.gitattributes`, sterownik ustawia `tools/setup_worktree.py`),
  więc po nich `npm run regen` i commit; bez tego CI i `tools/ci_lokalnie.py` padają.
- Nowy proces w Uruchomieniach: opis procesu `process_run.Process` w module
  procesu (wzór: `settlement_process.PROCESS`), klucz w `contract.ProcessKey`,
  pole w `Processes` (`centrum/processes.py`), widok w `centrum/run_view.py`,
  wpis w katalogu procesów `centrum/catalog.py` (wzór: `SETTLEMENT`: Ustawienia
  taty, Wzorce i kroki Diagnozy procesu) i adapter startu (wzór:
  `SettlementEntry`, spełnia `runs.ProcessEntry`) na liście `entries` w
  `create_app`. Diagnoza, Logi Uruchomienia, karty z Logów, Metryki i Konfiguracja
  pytają wpis, więc `runs.py` i one się nie zmieniają; czego brakuje, mówi
  `tests/test_katalog_procesow.py`.

Podczas pracy nad UI `npm run dev` działa obok `run_centrum.py --no-browser`
i przekazuje `/api` do serwera. Zmiany w Centrum weryfikuje end-to-end skill
[`verify-centrum-rozliczen`](.agents/skills/verify-centrum-rozliczen/SKILL.md).
Zmianę, która może zmienić szybkość frontendu, mierzy przed i po funkcja
`--feature wydajnosc` tego skilla (profile CPU komputera taty, porównanie z
baseline'em; poza `all`, kilka minut na spokojnym CPU, opis w
[`features/wydajnosc.md`](.agents/skills/verify-centrum-rozliczen/features/wydajnosc.md)).

## Zakres poza pierwszą wersją

Synchronizacja OneDrive, współbieżna edycja przez innych użytkowników oraz
automatyczne wykrywanie gotowości po samym zapisie pliku są poza zakresem.

Poza zakresem Przygotowania pliku zbiorczego są też:

- połączenie Przygotowania pliku zbiorczego i Przebiegu rozliczeń w jeden
  proces działający w tle.

