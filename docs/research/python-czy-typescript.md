# Research: Python czy TypeScript — koszt przeniesienia domeny i ekosystem

Data researchu: 2026-11-08.
Ticket: #1151 (mapa #1145 „Centrum w chmurze”).
Commit pomiaru: `604d12116` (`origin/main`).

Notatka zbiera fakty do decyzji, ale jej nie podejmuje.
Wybór należy do ticketu grillującego „Język i stack: Python czy TypeScript”.

## Wniosek w skrócie

- `src/` ma 36 242 linie (22 510 linii kodu bez docstringów, komentarzy i pustych linii).
  Logika domeny bez Excela to 6,3 tys. linii, a warstwa plików Excela 5,9 tys.
  Centrum (FastAPI) to 17,9 tys. linii, w tym 3,2 tys. linii, które istnieją tylko dlatego, że Centrum działa na komputerze taty.
- Testy to 85,4 tys. linii i 2649 funkcji `test_`.
  Prawie wszystkie biegną w procesie Pythona na jego modułach: 94 pliki importują `rozliczenia`, testy Centrum używają `TestClient` FastAPI i wstrzykiwania przez `create_app`, a skoroszyty testowe powstają przez openpyxl.
  W wariancie TypeScript żadnego z nich nie da się uruchomić na nowym kodzie, więc każdy trzeba przepisać.
  Wyrocznią na czas przepisywania mogą być narzędzia, które porównują wyniki, a nie kod: `tools/rownowaznosc.py`, `tools/porownanie_rozliczen.py` i `tools/odtworz_uruchomienie.py`.
- Zapis „podmień wiersze, resztę pliku zostaw bajt w bajt” (ADR 0008, ADR 0019) nie pochodzi z żadnej biblioteki Excela.
  To własna warstwa repozytorium na stdlib Pythona (`zipfile`, `zlib`, `struct`, `xml.parsers.expat`), a openpyxl służy tylko do odczytu i jako zapas.
  Ani ExcelJS, ani SheetJS CE tego nie robią: oba wczytują i zapisują cały skoroszyt, a SheetJS CE nie zapisuje stylów komórek.
  W TypeScript tę warstwę trzeba przepisać ręcznie na `node:zlib` i `Buffer`; ma ona wszystkie potrzebne prymitywy.
- Nocne mutacje (ADR 0021) to własny potok w Pythonie: operatory na `ast`, plugin pokrycia pytest i brama typów ruff/mypy.
  Stryker 10.1.1 daje mutację zakresów linii, pokrycie per test, tryb przyrostowy i checker TypeScript.
  Inaczej niż ADR 0021 liczy jednak przekroczony czas (jako wykrytą mutację) i nie ma kilku operatorów, które repo dodało, bo mutacje nimi przeżywały testy.
- Kontrakt Centrum jest już współdzielony przez generację: Pydantic → OpenAPI → `@hey-api/openapi-ts` → typy i schematy zod.
  Jeden język usuwa ten krok generacji, ale nie usuwa żadnej luki w typach.
- Objętość przepisania w wariancie TypeScript (ok. 33 tys. linii `src/`, ok. 60 tys. linii testów i ok. 36 tys. linii skryptów skilli `verify-*`) to mniej więcej miesiąc obecnej przepustowości repo.
  W ostatnich 30 dniach scalono 588 PR-ów: `src/` +61 tys./−27 tys. linii, `tests/` +108 tys./−21 tys.
  Przy porcie trzeba jednak dowieść równoważności, a nie tylko napisać kod.

## 1. Rozmiar i podział kodu `src/`

Metoda: każdy plik `src/rozliczenia/**/*.py` trafia do jednej grupy.
„Kod” to linie z tokenami Pythona bez docstringów modułów, klas i funkcji, komentarzy i pustych linii (`ast` + `tokenize`).
Kod ma tu bardzo długie docstringi: 38% linii `src/` to nie kod.

Reguły grup:

- **Warstwa plików Excela**: plik importuje `openpyxl` (poza samym `openpyxl.utils` do liter kolumn), `zipfile` albo `xml`.
- **Logika domeny bez Excela**: pozostałe moduły procesów i reguł.
  Należy tu też pięć modułów, które z openpyxl biorą tylko `get_column_letter`/`column_index_from_string`: `intermax_ordering.py`, `order_facts.py`, `inea_only_quantities.py`, `efenix_orders.py` i `preparation_register.py` (853 linie).
- **Komunikaty**: `*_messages.py` i `message.py`, czyli polski tekst dla taty.
- **Rdzeń uruchomienia i telemetria**: `process_run.py`, `phase_runner.py`, `progress.py`, `domain.py`, `decision.py`, `dad_files.py`, `telemetry.py` i inne.
- **efenix, okno przeglądarki**: `efenix_browser.py`, `efenix_page.py` (Playwright), `efenix_window.py`, `efenix_pace.py` i `efenix_trace.py`.
- **Centrum** w czterech podgrupach według docstringu modułu.

| Grupa | Pliki | Linie | Kod |
|---|---:|---:|---:|
| Logika domeny bez Excela | 34 | 6 300 | 3 853 |
| Warstwa plików Excela | 14 | 5 854 | 3 805 |
| Centrum: HTTP i kontrakt (`app.py`, `contract.py`, routery FastAPI, `runs.py` z SSE) | 17 | 5 125 | 3 189 |
| Centrum: Skrzynka Zgłoszeń, GitHub, Sprawy taty (`outbox.py`, `keyed_box.py`, `reports.py`…) | 13 | 5 004 | 2 928 |
| Centrum: tylko dla komputera taty (`tool_update.py`, `restart_guardian.py`, `launcher.py`, `shortcut.py`, `platform.py`, `cloud_files.py`, `settings.py`…) | 15 | 3 166 | 1 908 |
| Centrum: Logi Uruchomienia (`run_logs.py`, `run_logs_guard.py`, `logs_disk.py`…) | 7 | 2 313 | 1 413 |
| Centrum: procesy i Uruchomienia (`catalog.py`, `processes/*`, `diagnosis.py`, `stops.py`…) | 17 | 2 254 | 1 457 |
| efenix: okno przeglądarki | 5 | 2 220 | 1 323 |
| Komunikaty (tekst) | 7 | 2 134 | 1 467 |
| Rdzeń uruchomienia i telemetria | 12 | 1 872 | 1 167 |
| **Razem** | **141** | **36 242** | **22 510** |

W obu wariantach zmieni się część Centrum, niezależnie od języka.
Grupa „tylko dla komputera taty” (Aktualizacja narzędzia, opiekun ponownego startu, skrót na pulpicie, okna wyboru plików, pliki OneDrive „tylko online”, lokalny plik Ustawień) w chmurze traci sens.
Stan w plikach (`dad_cases.py`, `logs_disk.py`, `outbox.py`) przechodzi do bazy.
Przenoszona domena to głównie logika domeny, warstwa Excela na okres przejściowy, komunikaty, rdzeń uruchomienia i ewentualnie okno efenix (ADR 0024 zakłada sesję taty).
Razem to ok. 18,4 tys. linii, w tym ok. 11,6 tys. linii kodu.

Poza `src/`:

| Obszar | Linie | Uwagi |
|---|---:|---|
| `frontend/src` (TS/TSX) | 17 441 | w tym wygenerowane `types.gen.ts` (3 761) i `zod.gen.ts` (2 089) |
| `tools/**/*.py` | 19 563 | narzędzia procesu (CI, merge, mutacje, benchmarki) |
| `.agents/skills/**/*.py` | 36 504 | skrypty skilli `verify-*`; 23 pliki w 11 skillach importują `rozliczenia` |

## 2. Jak testy są związane z Pythonem

Pliki `tests/**/*.py` podzielone według tego, co importują:

| Grupa | Pliki | Linie | Funkcje `test_` |
|---|---:|---:|---:|
| Centrum (import `rozliczenia.centrum`) | 43 | 29 926 | 1 057 |
| Narzędzia procesu, skille, CI (import `tools`/`lib` albo ścieżki skilli) | 50 | 23 244 | 813 |
| Silnik (import `rozliczenia` bez Centrum) | 32 | 18 800 | 639 |
| `tests/fixtures/*.py` | 53 | 8 827 | — |
| Inne (przez fixtures albo `ast` na źródłach) | 27 | 4 294 | 140 |
| `conftest.py`, `__init__.py` | 2 | 310 | — |
| **Razem** | **207** | **85 401** | **2 649** |

Co wiąże testy z Pythonem:

- **Wywołania w procesie.** 94 pliki testów i fixtures importują moduły `rozliczenia`.
  Testy Centrum budują aplikację przez `create_app` z podstawionymi zależnościami i wołają ją `fastapi.testclient.TestClient` (`tests/fixtures/centrum.py`).
  `tests/conftest.py` łata `TestClient` i pilnuje, żeby test nie sięgał do GitHuba ani do katalogu narzędzia.
  Testy nie są czarną skrzynką po HTTP, więc nie przetestują serwera w innym języku.
- **Skoroszyty testowe z openpyxl.** `tests/fixtures/workbooks.py` i `tools/syntetyczne_wzorce.py` budują pliki xlsx w czasie testu (repo nie ma żadnego `.xlsx`).
  Wzorce syntetyczne mają kształt Wzorców taty: ~10 tys. sformatowanych wierszy, ~50 tys. wspólnych formuł, `calcChain`.
- **Strażnicy architektury na `ast`.** 17 plików testów (5 326 linii) czyta źródła Pythona przez `ast`.
  Należą do nich `test_jeden_odczyt_skoroszytu.py`, `test_jeden_zapis_skoroszytu.py`, `test_granice_wyjatkow.py`, `test_tabela_zatrzyman_efenix.py` i `test_struktura_testow.py`.
  W TypeScript to inne narzędzie, np. reguły oxlint, których repo już używa we `frontend/` (`@oxlint/plugins`).
- **Biblioteki pytest:** fixtures (63 `@pytest.fixture`), `parametrize` (116 plików), `monkeypatch` (75), hypothesis (9 plików), pytest-xdist z `--dist worksteal` i pytest-timeout.
  Odpowiedniki w TS istnieją (vitest 5.1.0, fast-check 4.10.2), ale to przepisanie, a nie tłumaczenie składni.
- **Wyrocznie niezależne od języka kodu**, które porównują wyniki, a nie wywołują modułów:
  - `tools/rownowaznosc.py` uruchamia te same scenariusze syntetyczne trzech procesów na dwóch commitach przez skrypt dla maszyn `tools/uruchom_proces.py` (wynik JSON) i porównuje wyniki;
  - `tools/porownanie_rozliczen.py` porównuje znaczeniowo dwa Foldery rozliczeń pracowników (wartości, formuły, style, hiperłącza);
  - `tools/odtworz_uruchomienie.py` odtwarza Uruchomienie taty z Logów;
  - `tests/expected/` ma 59 plików oczekiwanych wyników.

  Gdyby implementacja TS miała skrypt dla maszyn z tymi samymi argumentami i wynikiem JSON co `uruchom_proces.py`, te narzędzia porównałyby Pythona z TS na tych samych wejściach.
  To najtańsza znana droga, żeby port nie stracił zachowania, którego nie opisuje żaden test.

## 3. Warstwa Excela: co robi dziś i co dają biblioteki TS

### Co robi narzędzie dziś

- **Kopia Wzorca z podmienionymi wierszami** (`template_copy.py`, ADR 0008).
  Każda część zip poza arkuszem, `xl/workbook.xml` i `xl/styles.xml` jest przepisana bajt w bajt razem ze skompresowaną treścią, w tym `xl/externalLinks/*`, `xl/calcChain.xml` i `xl/sharedStrings.xml`.
  W XML arkusza zmieniają się tylko wpisane wiersze, a nowe style są dopisywane na końcu list w `styles.xml`.
  Arkusz jest skompresowany raz, w kawałkach od granic wierszy (`zlib.Z_FULL_FLUSH`), więc kolejna kopia kompresuje tylko swój początek.
  Nagłówki zip powstają ręcznie przez `struct.pack`.
- **Zapis dnia w INTERMAX** (`intermax_file.py`, ADR 0019): ten sam wzór na Rejestrze zleceń z ~42 tys. wierszy (dziesiątki MB XML).
  Zmieniają się wiersze dnia, `ref` hiperłączy, `<dimension>` i widok arkusza.
- **Znaczniki efenix** (`efenix_marking.py`): zmienia się tylko atrybut `s` komórek `ADRES` i końce list `fills`/`cellXfs`.
- **Hiperłącza** (`hyperlinks.py`) czyta z relacji arkusza, bo openpyxl w trybie tylko do odczytu ich nie daje.
- **openpyxl 3.1.5** (ostatnie wydanie 2024-06-28 na PyPI) służy do odczytu `read_only` w `workbook_files.py` i do zapisu zapasowego, gdy kopia odmawia kształtu.
  Po zapisie przez openpyxl `workbook_save.py` przywraca bajtowo `xl/externalLinks/*`, bo openpyxl „nie zapisuje ich wiernie”.

Wniosek: to, co ticket nazywa „podmianą wierszy bez ruszania reszty pliku”, w Pythonie też nie pochodzi z biblioteki xlsx.
To 5,9 tys. linii własnej warstwy na stdlib.

### ExcelJS

- Wersja 4.4.0 na npm z 2023-10-19.
  Ostatni commit na `master` to 2024-01-12, a repo ma 825 otwartych issues (GitHub API, 2026-11-08).
- Model dokumentowy: wczytuje cały skoroszyt do obiektów i zapisuje go od nowa.
  Ma osobny strumieniowy zapis i odczyt; zapis strumieniowy ma opcje `useStyles` i `useSharedStrings` (README).
- README nie opisuje odwołań zewnętrznych (`externalLinks`).
  Otwarte są issues o utracie zawartości przy wczytaniu i zapisie: #261 „Losing formatting/pivot table from loaded file” (2017) i #1184 „Template data validation lost” (2020).
- Podmiany wierszy z zachowaniem reszty bajtów nie oferuje.

### SheetJS (pakiet `xlsx`)

- Bieżąca wersja Community Edition to 0.20.3, dystrybuowana z CDN SheetJS.
  Dokumentacja mówi, że pakiet `xlsx` w rejestrze npm jest nieaktualny (0.18.5, 2022-03-24) i zaleca vendoring tarballa.
- Według dokumentacji zapisu „SheetJS CE writers focus on data preservation”, a „SheetJS Pro offers support for additional features, including styling…”.
  `cellStyles` w CE eksportuje tylko metadane wierszy i kolumn.
  Dokumentacja dodaje: „Features not described in the documentation may not be serialized.”
- Opiekun potwierdza w issues #2952 i #3214, że zachowanie stylów przy wczytaniu i zapisie oraz edycja istniejących plików to oferta Pro.
- Dla plików taty (Wyróżnienia, Wygląd Wiersza danych, Znaczniki efenix to style komórek) CE się nie nadaje.

### Prymitywy Node dla własnej warstwy

- `node:zlib` ma surowy deflate (`deflateRaw`, `deflateRawSync`, `createDeflateRaw`) i stałe `Z_SYNC_FLUSH`, `Z_FULL_FLUSH` i `Z_FINISH`.
  Strumień ma `flush([kind])`, domyślnie `Z_FULL_FLUSH` dla strumieni zlib.
- `zlib.crc32(data[, value])` jest w Node od v22.2.0 i v20.15.0.
- Asynchroniczne API zlib biegną w puli wątków libuv.
  Synchroniczne skanowanie XML w JS blokuje pętlę zdarzeń, więc na serwerze proces musiałby biec w `worker_threads`.
  W Pythonie Uruchomienie biegnie dziś w wątku roboczym (`centrum/runs.py`), a kompresja kawałków w `ThreadPoolExecutor`, bo zlib zwalnia GIL.
- Node nie ma w stdlib parsera XML, a Python ma expat.
  `workbook_parts.SheetData` dzieli arkusz na wiersze bez parsera, ale sprawdzenie poprawności części XML (expat) w TS wymaga zależności albo własnego kodu.
- Bez biblioteki xlsx trzeba też zastąpić odczyt `read_only` openpyxl (Plik zbiorczy, wartości policzone przez Excel) i zapis zapasowy.
  Kandydatem do odczytu jest strumieniowy czytnik ExcelJS, ale z ryzykiem utrzymania opisanym wyżej.
- Optymalizacje z hillclimbów wydajności (Przygotowanie, INTERMAX, Przebieg) są zmierzone w Pythonie na sprzęcie taty.
  Port musiałby je odtworzyć i zmierzyć jeszcze raz; czas w Node nie jest tu zmierzony.

## 4. Postgres, walidacja, serwer HTTP

Wersje z rejestrów npm i PyPI z 2026-11-08.

| Rola | Python | TypeScript |
|---|---|---|
| Dostęp do Postgresa | SQLAlchemy 2.1.8, psycopg 3.3.8 | Drizzle ORM 0.45.4 (1.0 od 2025-11 w beta, od 2026-10 w RC 1.0.0-rc.5); Kysely 0.29.8 (query builder, Node ≥ 22); Prisma ORM 7.10.1 stabilne, Prisma 8 jako RC (tag `latest` pakietu `prisma` wskazuje 8.0.0-rc.33) |
| Migracje | Alembic 1.20.1 | Drizzle: `drizzle-kit generate/migrate/push/pull`, schemat w TS źródłem prawdy; Kysely: wbudowany `Migrator` z ręcznymi `up`/`down` i blokadą w bazie, typy z bazy osobnym `kysely-codegen` 0.20.0; Prisma: Prisma Migrate |
| Walidacja i modele | Pydantic 2.14.3 (repo przypina 2.14.1) | Zod 4.6.7 (frontend już go używa); `z.toJSONSchema` z celami draft-2020-12, draft-07, draft-04 i openapi-3.0; `z.date()` i `z.transform()` są tam nieprzedstawialne i domyślnie rzucają błąd |
| Serwer HTTP | FastAPI 0.162.2 (repo przypina 0.146.0), uvicorn | Fastify 5.12.8 z `@fastify/type-provider-zod` 1.0.3 i `@fastify/swagger` 9.9.3; Hono 4.13.17 na `@hono/node-server` 2.1.6 (Node ≥ 20) ze `streamSSE` i `@hono/zod-openapi` 1.6.3 |
| Przeglądarka (efenix) | Playwright for Python 1.64 | Playwright 1.65.0; TS to jego pierwotny język |
| Testy | pytest 8.3.3, hypothesis, xdist | vitest 5.1.0 (Node ^22.12 / ^24 / ≥ 26), fast-check 4.10.2 |

Uwagi:

- Prisma 7 wymaga adaptera sterownika w `new PrismaClient({ adapter })` (dla Postgresa `@prisma/adapter-pg`), ESM i `"type": "module"`, a minimalny Node to 20.19.0.
  Pule połączeń mają wtedy domyślne ustawienia sterownika; `pg` nie ma domyślnego limitu czasu połączenia (przewodnik aktualizacji do v7).
- Drizzle i Kysely są jeszcze przed 1.0.
  Drizzle zapowiada zmiany v0 → v1 z przewodnikiem aktualizacji, więc wybór dziś to wybór między stabilnym 0.45 a RC 1.0.
- Centrum strumieniuje dziś postęp Uruchomienia przez SSE (`centrum/runs.py`, `StreamingResponse`); oba serwery TS to mają.

## 5. Mutacje: proces nocny wobec Strykera

### Dziś (ADR 0021)

- Własny potok: `tools/mutacje.py` (972 linie), `tools/mutacje_nocne.py` (567) i `tools/mutacje_zmiany.py` (1 073), plus plugin pokrycia `tools/lib/pytest_pokrycie.py` z `tools/lib/pokrycie_procesu.py`.
- Mutowane są linie `src/` i `tools/` zmienione od bazy nocy, najwyżej jedna mutacja operatora na linię (najgłębszy węzeł `ast.walk`) plus cofnięcie każdego fragmentu zmiany do bazy.
- Operatory: usunięcie członu `and`/`or`, jedna gałąź `a if w else b`, `True`↔`False`, `if` zawsze prawdziwy i fałszywy, granica `<`/`<=`, `return x` → `return None` (i kody wyjścia), `in`/`startswith`/`endswith`, argument nazwany → `None`, usunięcie wywołania w osobnej linii i usunięcie elementu krotki.
- Mutacja, która przeżyła testy, przechodzi jeszcze bramę typów (ruff, mypy obu systemów); błąd daje `WYKRYTA PRZEZ BRAMĘ TYPÓW`.
- `PRZEKROCZONY CZAS` noc liczy jak przeżytą.
  ADR 0021 wprost odrzucił wariant „jak w Stryker i PIT”, bo mutacje po 900 s spowalniały testy, a nie je wieszały.
- Przeżyte trafiają do issue `Przeżyte mutacje z #N` PR-u z `git blame --first-parent`.
  Noc ma części po 24 mutacje i limit 960 mutacji, a zaległość przechodzi na kolejne noce.
- Skrypty mutacji skilli (`check_*_mutations.py`) używają `tools/mutacje.py` z kotwicami tekstowymi i poleceniem po `--`, które dziś jest Pythonem.

### StrykerJS 10.1.1 (2026-10-23, Node ≥ 22)

- `mutate` przyjmuje zakresy `plik:startLinia-koniecLinia` (bez łączenia zakresu z globem w jednej pozycji).
  Listę zmienionych linii od bazy da się więc podać z zewnątrz; samej opcji „od commitu” konfiguracja nie ma.
- `coverageAnalysis: perTest` uruchamia dla mutacji tylko testy, które ją pokrywają.
  Runner vitest zawsze wymusza `perTest`, `maxWorkers: 1` i `bail` na pierwszej porażce i nie wspiera trybu przeglądarki.
- `incremental` porównuje kod i testy z własnym plikiem raportu (`reports/stryker-incremental.json`), a nie z gitem.
  Nie wykrywa zmian w innych plikach ani w zależnościach.
  W CI plik raportu trzeba przenosić między nocami.
- `checkers: ["typescript"]` sprawdza każdą mutację kompilatorem przed testami.
  Mutacja z błędem kompilacji to `CompileError`, poza wynikiem, czyli funkcjonalnie to samo co brama typów.
- Stany: `Timeout` jest liczony jako wykryty („counted as detected”), a wynik to `(killed + timeout) / (killed + timeout + survived + no coverage)`.
  To odwrotność decyzji ADR 0021 o `PRZEKROCZONY CZAS`.
- Mutatory: ArithmeticOperator, ArrayDeclaration, BlockStatement, BooleanLiteral, ConditionalExpression, EqualityOperator (granice i negacje `<`, `<=`, `>`, `>=`, `==`, `===`…), LogicalOperator, MethodExpression (`startsWith`↔`endsWith`, `some`↔`every` i inne), ObjectLiteral, OptionalChaining, Regex, StringLiteral, UnaryOperator, UpdateOperator.
  Na liście nie ma: zamiany wartości `return` na `undefined`, usunięcia pojedynczego wywołania (jest tylko opróżnienie całego bloku), argumentu → `undefined`, usunięcia elementu krotki ani cofnięcia fragmentu zmiany do bazy.
  Te operatory repo dodało, bo mutacje nimi przeżywały testy (docstring `tools/mutacje_zmiany.py`).
- Przypisanie przeżytych do issue PR-u, części, limity nocy i zaległość to orkiestracja na `git` i `gh`.
  W wariancie TS zostają własnym kodem nad raportem JSON Strykera.

## 6. Jeden język: kontrakt Centrum

- Dziś źródłem prawdy jest `src/rozliczenia/centrum/contract.py` (1 357 linii Pydantic).
  `frontend/scripts/contract.mjs` uruchamia `tools/ci/export_openapi.py` (OpenAPI, `frontend/src/api/openapi.json`, 6 188 linii), a potem `@hey-api/openapi-ts` 0.99.0 z wtyczkami `@hey-api/typescript` i `zod`.
  Wynik to `types.gen.ts` i `zod.gen.ts`, razem 5 850 linii.
- CI regeneruje kontrakt i build i pada, gdy zacommitowane pliki różnią się od źródeł (`.github/workflows/ci.yml`, `tools/ci_lokalnie.py`).
- Frontend już ma typy i schematy zod z serwera, więc jeden język nie dodaje bezpieczeństwa typów na granicy.
  Usuwa krok generacji, wymaganie Pythona w `npm run contract` i drugi zestaw narzędzi (ruff/mypy obok tsc/oxlint).
- CI dziś używa Pythona 3.14 i Node 24 (`.github/workflows/*.yml`).
  W chmurze odpada ograniczenie „u taty nie ma Node” (komentarz w `tools/ci_lokalnie.py`).

## 7. Koszt i ryzyko obu wariantów

### Praca wspólna dla obu wariantów

- Centrum na serwer: baza zamiast plików stanu, uwierzytelnianie i role, wielu użytkowników naraz zamiast jednego Uruchomienia na komputer.
- Usunięcie albo przebudowa ok. 3,2 tys. linii Centrum „tylko dla komputera taty”.
- Zachowanie warstwy Excela na okres przejściowy, w którym tata dalej pracuje w Excelu (mapa #1145).

### Wariant A: zostać przy Pythonie

- Koszt języka bliski zeru: domena, warstwa Excela, 2 649 testów, nocne mutacje i skrypty `verify-*` zostają.
- Nowe zależności: SQLAlchemy/psycopg i Alembic (albo sam psycopg).
  Kontrakt OpenAPI → zod działa jak dziś.
- Zostają dwa języki (TS na froncie, Python na serwerze) i dwa zestawy narzędzi jakości.
- Ryzyko: openpyxl rozwija się wolno (3.1.5 z 2024-06), ale repo zależy od niego tylko przy odczycie i zapisie zapasowym.

### Wariant B: całość w TypeScript

Objętość do przepisania, licząc tylko to, co przeżywa przejście do chmury:

| Co | Linie Pythona | Uwagi |
|---|---:|---|
| `src/` bez Centrum „tylko dla komputera taty” | ~33 000 | ~20 600 linii kodu; warstwa Excela 5,9 tys. bez biblioteki-odpowiednika |
| Testy silnika, Centrum i fixtures | ~57 500 | 18,8 + 29,9 + 8,8 tys.; skoroszyty testowe dziś z openpyxl |
| Strażnicy architektury na `ast` | 5 326 | do zaprojektowania jako reguły lintera TS |
| Potok mutacji | ~2 600 + plugin pokrycia | Stryker plus własna orkiestracja nocy; brak części operatorów; inna semantyka `Timeout` |
| Skrypty `verify-*` | 36 504 | 23 pliki w 11 skillach importują `rozliczenia`; modele TLA+ są niezależne od języka, ale eksploratory biegną na kodzie Pythona (np. greenlety w `verify-jedno-uruchomienie-naraz`) |
| `tools/` | 19 563 | narzędzia procesu mogą zostać w Pythonie; wtedy repo dalej ma dwa języki |

Ryzyko utraty pokrycia:

- Żaden z 2 649 testów nie przechodzi na nowy kod automatycznie.
  Pokrycie i zabite mutacje trzeba odbudować, a dopóki Stryker nie przeliczy nowego kodu, nie wiadomo, które testy cokolwiek pilnują.
- Zachowanie, którego nie opisuje żaden test, wychodzi tylko przez porównanie wyników.
  Repo ma do tego wyrocznie (`rownowaznosc.py`, `porownanie_rozliczen.py`, `odtworz_uruchomienie.py`, `tests/expected/`).
  Warunkiem jest skrypt dla maszyn w TS o tym samym interfejsie co `tools/uruchom_proces.py`, a porównanie bajtów plików wymaga identycznej kompresji, której nikt nie zmierzył (Node ma własną kopię zlib, a Python linkuje swoją, więc wersje mogą się różnić); porównanie znaczeniowe `porownanie_rozliczen.py` tego nie wymaga.
- Warstwa Excela ma najwyższe ryzyko: plik, który otwiera się w Excelu, ale traci odwołania zewnętrzne albo `calcChain`, wychodzi dopiero u taty.
  Dziś pilnują tego skill `verify-skoroszyty-w-excelu` (prawdziwy Excel na Macu) i `verify-kopia-wzorca`.
- Przepustowość: w 30 dniach do 2026-11-08 scalono 588 PR-ów; `src/` +61 206/−27 501 linii, `tests/` +108 443/−21 313 (`git log --first-parent --numstat` na `origin/main`).
  Objętość portu to rząd wielkości jednego miesiąca tej przepustowości, bez kosztu dowodu równoważności i bez pracy nad chmurą, która jest wspólna dla obu wariantów.

### Pytania otwarte dla grilla

- Czy okno efenix (ADR 0024, sesja taty) w ogóle przechodzi na serwer, czy zostaje lokalnym agentem — to zmienia, ile kodu efenix się przenosi.
- Czy warstwa Excela ma żyć długo (Wzorce i Szablony jako skoroszyty, „Not yet specified” w #1145), czy tylko w okresie przejściowym.
- Czy wariant pośredni (domena i warstwa Excela w Pythonie jako proces roboczy, serwer w TS) jest w ogóle rozważany; ta notatka go nie mierzy.

## Źródła

Kod repozytorium (commit `604d12116`):

- `src/rozliczenia/template_copy.py`, `intermax_file.py`, `workbook_parts.py`, `workbook_files.py`, `workbook_save.py`, `hyperlinks.py`, `efenix_marking.py`, `register_file.py`
- `src/rozliczenia/centrum/contract.py`, `app.py`, `runs.py`
- `docs/adr/0008-zapis-rozliczenia-pracownika-przez-podmiane-wierszy-danych.md`, `docs/adr/0019-uporzadkowanie-intermax-zmienia-rejestr-zlecen.md`, `docs/adr/0021-mutacje-noca.md`
- `tools/mutacje.py`, `tools/mutacje_zmiany.py`, `tools/mutacje_nocne.py`, `tools/lib/pytest_pokrycie.py`, `tools/rownowaznosc.py`, `tools/porownanie_rozliczen.py`, `tools/odtworz_uruchomienie.py`, `tools/uruchom_proces.py`, `tools/syntetyczne_wzorce.py`
- `tests/conftest.py`, `tests/fixtures/centrum.py`, `tests/fixtures/workbooks.py`
- `frontend/package.json`, `frontend/scripts/contract.mjs`, `frontend/openapi-ts.config.ts`, `pyproject.toml`, `.github/workflows/ci.yml`

Biblioteki i narzędzia:

- Rejestr npm (`https://registry.npmjs.org/<pakiet>`) i PyPI (`https://pypi.org/pypi/<pakiet>/json`): wersje, daty wydań i `engines` z 2026-11-08
- [ExcelJS README](https://github.com/exceljs/exceljs/blob/master/README.md), [issue #261](https://github.com/exceljs/exceljs/issues/261), [issue #1184](https://github.com/exceljs/exceljs/issues/1184); aktywność repo z GitHub API
- [SheetJS: instalacja w Node.js](https://docs.sheetjs.com/docs/getting-started/installation/nodejs), [SheetJS: Writing Files](https://docs.sheetjs.com/docs/api/write-options/), [SheetJS: Reading Files](https://docs.sheetjs.com/docs/api/parse-options/), [issue #2952](https://git.sheetjs.com/sheetjs/sheetjs/issues/2952), [issue #3214](https://git.sheetjs.com/sheetjs/sheetjs/issues/3214)
- [Node.js: zlib](https://nodejs.org/api/zlib.html)
- [StrykerJS: konfiguracja](https://stryker-mutator.io/docs/stryker-js/configuration/), [tryb przyrostowy](https://stryker-mutator.io/docs/stryker-js/incremental/), [runner vitest](https://stryker-mutator.io/docs/stryker-js/vitest-runner/), [stany mutacji i metryki](https://stryker-mutator.io/docs/mutation-testing-elements/mutant-states-and-metrics/), [obsługiwane mutatory](https://stryker-mutator.io/docs/mutation-testing-elements/supported-mutators/)
- [Drizzle: migracje](https://orm.drizzle.team/docs/migrations), [Kysely: migracje](https://kysely.dev/docs/migrations), [Prisma: aktualizacja do v7](https://www.prisma.io/docs/guides/upgrade-prisma-orm/v7), [Prisma ORM 7.0.0 changelog](https://www.prisma.io/changelog/2025-11-19)
- [Fastify: Type Providers](https://fastify.dev/docs/latest/Reference/Type-Providers/), [Hono na Node.js](https://hono.dev/docs/getting-started/nodejs), [Hono: streaming](https://hono.dev/docs/helpers/streaming), [Zod: JSON Schema](https://zod.dev/json-schema)
