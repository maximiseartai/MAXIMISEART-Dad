# ADR 0042: Strażnik przy pierwszym Ważnym

## Status

Przyjęta na decyzję Maksa z 18.11.2026 w wątku koordynatora programu chwastów, jego słowami: „tak bramka ma przejmowac” (bramka przyjmuje strażnika każdego rodzaju z dowodem, który liczy narzędzie, a nie recenzent).
Zmienia jego wybór z 15.11.2026 („recenzent jako bramka”, [#1912](https://github.com/maximiseartai/MAXIMISEART-Dad/pull/1912#issuecomment-6902436281)) w punkcie „Idiom bez reguły” [ADR 0036](0036-chwast-to-regula.md) i decyzje tego ADR z listy „Zmienia te zdania”; odwracalna przez revert.
Wchodzi razem z kodem, który ją wdraża, a ten plik wyznacza chwilę wdrożenia (`bramka_straznika.MARKER`).
Wdraża ją dla typu, zakazu ruff i reguły ast-grep; test czeka na dowód narzędzia w następnej jednostce programu (G3) i do niej pisze `brak - test` (decyzja „Test jako strażnik”).

## Kontekst

Od 14.11.2026 PR-y z werdyktem `FAIL` miały 13 pól `Idiom:` w 9 PR-ach i żadnego z id reguły, więc warunek merge'a z polem `Idiom:` nie zażądał reguły ani razu (audyt 17.11.2026, liczony z komentarzy PR-ów).
Model TLA+ tego procesu łamie regułę „druga kopia idiomu ma regułę” tylko wtedy, gdy recenzent przeoczy powtórkę, a dominujące klasy Ważnych (nieczytelny plik liczony jak brak, druga droga obok właściciela) zamyka typ, test zachowania albo kontrakt, których dowodu bramka nie umiała.
Dowód typu i testu z #1912 odpadł po czterech rundach, bo autor pisał tekst mutacji (r1: wcięcie, r2: zasięg) albo bramka czytała tekst wyjścia narzędzi, którego format ustawia `pyproject.toml` PR (r3, r4).

## Decyzja

- **Strażnik przy każdym Ważnym.** Blok każdego Ważnego w sekcji `## Korzeń` opisu PR kończy linia `Strażnik: <selektor>` z zamkniętej listy, także po `Wyrwany w #M`, zamiast autorskiego `Dowód:`, który zostaje tylko w bloku czerwonego `main`.
  Autor wybiera tylko selektor; złą postać daje drzewo SHA werdyktu `FAIL` i miejsca jego pola `Gdzie` (przy mypy i ruff przywrócone pliki z `Gdzie`, przy `ast-grep <id>` linie dodane do `FAIL`), a wynik liczy narzędzie poleceniami i w środowisku Required CI (niżej „Środowisko dowodu”), więc dowód na Macu, w jobie na ubuntu i u autora daje to samo.
  Listę, przywrócenie błędu przy każdym rodzaju i granice podaje jeden właściciel: docstring `tools/lib/straznik.py`, a bramkę `tools/lib/bramka_straznika.py` (warunek 5 `tools/scal_pr.py`).
  Powód: strażnik powstaje przy pierwszym Ważnym, więc rozpoznanie powtórki przez recenzenta przestaje być warunkiem.
- **Dowód bez tekstu autora.** Bramka czyta tylko znaleziska mypy i ruff w formacie JSON z wiersza poleceń dowodu i wynik dowodu reguły ast-grep, więc ani tekst mutacji, ani format wyjścia z konfiguracji PR wyniku nie zmienia.
  Powód: prototyp na Ważnych z przeszłości (tabela w komentarzu PR, który dodał ten ADR) dał dowód `WYKRYTA` dla 2 z 2 Ważnych z typem i 0 z 5 fałszywych `WYKRYTA` strażnika statycznego niezwiązanego z błędem, a mutacja z pliku PR z warunkiem „zamiana to tekst z SHA `FAIL`” przepuściła 7 z 9 sond obejścia.
- **Test jako strażnik.** Test nie jest selektorem z dowodem narzędzia: Ważne, którego strażnikiem jest test, pisze `Strażnik: brak - test`, a czy test pada na błędzie z `Gdzie`, sprawdza recenzent następnej rundy, jak przed tym ADR.
  Powód: trzy rundy przeglądu PR, który dodał ten ADR, obaliły trzy kształty dowodu pytest na tej samej przesłance, że narzędzie rozstrzyga dla dowolnego testu, czy padł przez kod z `Gdzie`: kod 1 na drzewie `FAIL` przyjmował test, który pada tylko z braku nazwy dodanej po `FAIL` (r1), lista wyjątków braku nazwy przepuszczała kolejne formy (r2), a drugie przywrócenie samego kodu z `Gdzie` brało z `FAIL` linie obok funkcji, próbki z `tests/` i odrzucało poprawkę, która kod z `Gdzie` usuwa (r3).
  Dla testów to nie pogorszenie: przed tym ADR dowód testu też oceniał recenzent. Dowód testu liczony przez narzędzie to następna jednostka programu chwastów (G3), a do niej poniedziałkowe polowanie liczy Ważne z `brak - test`.
- **Kod usunięty z PR.** Ważne, którego kod z `Gdzie` PR usunął (szczebel (a): część, której przegląd nie przyjął, albo druga droga, której wołający biorą właściciela), pisze `Strażnik: brak - usunięte`, a czy kod zniknął i nie wraca inną drogą, sprawdza recenzent następnej rundy.
  Powód: usuniętego kodu żaden mechanizm nie dowodzi, bo przywrócony z `FAIL` przechodzi typ, ruff i reguły, a to częsta droga: w czterech ostatnich scalonych PR-ach z `## Korzeń` przed tym ADR (#2125, #2120, #2119, #2112) 8 z 13 bloków Ważnych to szczebel (a) z usuniętym kodem.
- **Wyjątki.** `brak - proza` sprawdza narzędzie (każde miejsce `Gdzie`, które zmienił PR, to `.md`, docstring albo komentarz), a `brak - napęd` (miejsca tylko w `frontend/`, a strażnik to krok napędu skilla `verify-*`) narzędzie co do miejsca, a dowód recenzent następnej rundy: krok napędu na drzewie `FAIL`, jak dotąd; `brak - test` (wyżej) nie ma warunku narzędzia.
  Powód: frontend nie ma testów jednostkowych, a krok napędu potrzebuje przeglądarki i zbudowanego frontendu, których job dowodu nie ma (#2104 W1 r1).
- **Środowisko dowodu.** Dowód `mypy`, `ruff` i `ast-grep <id>` biegnie w środowisku, które `tools/lib/srodowisko_ci.py` buduje z drzewa HEAD PR scalonego z bazą (jak `refs/pull/N/merge`), a nie w środowisku wołającego: Python, zależności z `pyproject.toml` drzewa i projekt jak instalacja zadania „Ruff, mypy” z `ci.yml`, polecenia `kroki_lokalne.static_steps` (każda platforma `MYPY_PLATFORMS`), zmienne bez tych, które sterują Pythonem, mypy, ruff i uv, a ast-grep w wersji z drzewa.
  Zadanie „Ruff, mypy”, które buduje środowisko inaczej (`srodowisko_ci.mismatch`: kroki od pierwszego do ostatniego sprawdzenia różne od `srodowisko_ci.job_steps`, porównane na równość poza nazwą kroku i wersją akcji, klucz zadania spoza listy, runner, `env` i `defaults` workflow, konfiguracja uv), to odmowa dowodu, a zmianę środowiska Required CI scala się osobnym PR przed tym, który jej potrzebuje, jak zmianę reguły bazy (#2113).
  Powód: #2116 dostał trzy `FAIL` na tej samej przesłance, że dowód liczy narzędzie w środowisku Required CI (r4 system maszyny, r5 lista platform, r6 zależności `main` zamiast HEAD PR); środowisko buduje teraz jedna funkcja z drzewa, które sprawdza Required CI, a z `ci.yml` wiąże ją ta sama `mismatch` na `main` w teście i na drzewie PR przy każdym dowodzie.
  Przed ruff i mypy zadanie nie uruchamia żadnego kodu PR poza instalacją (krok pytest reguł całego drzewa stoi za mypy), więc dowód nie musi odtwarzać plików, które taki kod by zapisał; dowód na PR scalonym przed tym krokiem liczy jego drzewo z dawnym `ci.yml`, więc odmawia.
  Kroki ruff i mypy biegną po kolei na jednej kopii po instalacji, w kolejności zadania (wiąże ją `mismatch`), a krok, który zmienia pliki kopii (np. ruff z `fix` w konfiguracji drzewa), to odmowa, bo Required CI liczy dalsze kroki na zmienionych plikach (#2161 r1 W2).
  Kopia to osobne repozytorium bez konfiguracji gita i `info/exclude` wołającego, a narzędzia biegną z pustym `HOME`, jak checkout na runnerze, więc ani wykluczenia gita, które czyta ruff, ani konfiguracja użytkownika mypy i ruff dowodu nie zmieniają; na macOS dowód odmawia drzewa ze ścieżkami, które jego system plików scala (wielkość liter, normalizacja Unicode).
  Powód zmiany podejścia w #2161 r3: dwie rundy z `FAIL` znalazły w `mismatch` kolejne wyjątki (tekst zamiast parsera TOML, prefiks polecenia), więc porównanie z listami dozwolonych postaci zastąpiła równość z jedną postacią zadania.
  Granica: wydanie poprawkowe Pythona, wersja uv i obraz runnera mogą się różnić od runu Required CI, a pakiety rozwiązują się w chwili dowodu, jak w runie CI w tej chwili (repo nie ma pliku blokady).
- **Gdzie liczy dowód.** Budowa środowiska i mypy wykonują kod PR (backend budowy i pakiety z `pyproject.toml` PR, wtyczki mypy z jego konfiguracji), więc status „Werdykt i bramka” liczy warunek 5 w jobie `dowod` bez prawa zapisu, a job `status` liczy warunki 1–4 kodem `main` i bierze z `dowod` tylko przyczyny warunku 5 dla tego samego SHA HEAD.
  Powód: kod PR nie dostaje tokenu, który ustawia statusy (#1912 r1, `R-KOD-PR-Z-TOKENEM`). Granica: kod PR, który celowo pisze plik wyników joba `dowod`, daje w statusie przechodzący warunek 5 własnego PR (#2116 r1 D1), ale nie zgodę, CI ani opis, a merge przez `tools/scal_pr.py` liczy dowód sam.
- **Pole `Idiom:`.** Nie zatrzymuje już merge'a; postacie `<id> jak #N W<n> r<k>` i `<id>` zostają adnotacją recenzenta dla raportu tygodniowego, a postać `bez reguły <klasa>` z tabelą klas czyta raport tylko w werdyktach sprzed tego ADR.

## Odrzucone warianty

- **Mutacja z pliku JSON w PR, której zamiana musi być tekstem z SHA `FAIL`.** Autor wybiera miejsce zamiany, więc ten sam tekst w złym miejscu (w funkcji przed definicją nazwy, na poziomie modułu) daje fałszywe `WYKRYTA` (#1912 r1–r2; prototyp: 7 z 9 sond).
- **Cofnięcie samych hunków przy `Gdzie` dla pytest.** Mieszanka kodu z `FAIL` i HEAD wywraca test, który na całym drzewie `FAIL` przechodzi (prototyp, #2059 W1 r1).
- **Rodzaj wyjątku testu jako dowód (wtyczka pytest, #2116 r1).** Kod testu wybiera, jakim wyjątkiem pada (`AttributeError` instancji, `monkeypatch`, `SystemExit` opcji), więc lista wyjątków braku nazwy przepuszczała kolejne formy (#2116 r2 W1).
- **Dowód pytest przez drugie przywrócenie samego kodu z `Gdzie` (#2116 r2).** Różnica linii HEAD i `FAIL` nie zna granicy funkcji, więc przywrócenie brało też linie dodane obok niej i próbki z `tests/`, a przy poprawce, która kod z `Gdzie` usuwa, dawało HEAD, na którym test przechodzi (#2116 r3 W1–W3).
- **Dowód w środowisku wołającego z kolejnymi poprawkami (#2116 r4–r6).** Każda runda zamykała jeden wymiar (system maszyny, lista platform), a następny (zależności z `main`) zostawał, bo dowód nie budował środowiska, tylko je zastawał.
- **Odmowa każdego PR, który zmienia zależności.** Środowisko z drzewa PR zamyka ten wymiar bez drugiego PR, a odmowa zostaje tylko dla zmiany samego zadania „Ruff, mypy”.
- **Dowód na samym HEAD PR.** Konfiguracja, którą baza zmieniła po rozwidleniu, nie wchodzi do dowodu, choć po merge'u obowiązuje: wyłączony w bazie kod błędu dawał `WYKRYTA` strażnikowi, który po merge'u nic nie łapie.
- **Recenzent jako bramka typu i testu (#1912).** Zostawia warunek, którego dotrzymanie zależy od tego, czy recenzent rozpozna powtórkę i napisze dowód.

## Konsekwencje

- Wątek z werdyktem sprzed wdrożenia tego ADR kończy po staremu, z `Dowód:` w bloku Ważnego (`bramka_straznika.applies`, decyzja Q20 ADR 0031).
- Strażnik statyczny innej poprawki tego samego PR w tej samej funkcji przechodzi dowód Ważnego tej rundy; jego trafność ocenia recenzent następnej rundy z linii dowodu, która nazywa znalezisko.
- `Strażnik: brak - test` i `Strażnik: brak - usunięte` przechodzą przy każdym Ważnym, więc test, który błędu nie łapie, kod z `Gdzie`, który stoi na HEAD, i Ważne, które zamknąłby typ, łapie tylko recenzent następnej rundy, jak przed tym ADR.
- Dowód mypy biegnie krokami mypy z `kroki_lokalne.static_steps` (każda platforma `MYPY_PLATFORMS`, jak Required CI) w środowisku z `srodowisko_ci.built` i na prawdziwych Ważnych trwa 33–45 s na Macu (#1956 W2 r1, #1499 W1 r2), z czego budowa środowiska z pamięci uv około sekundy, więc status przy PR z `FAIL` przychodzi później niż dziś; PR bez czego dowodzić czeka tylko na start joba `dowod`.
- Dowód potrzebuje uv i sieci do PyPI (jak Required CI); bez uv, na Windows i przy porażce budowy odmawia z przyczyną.

## Zmienia te zdania ADR 0036

- „Pole werdyktu”: pole `Idiom:` w trzech postaciach przestaje być polem, od którego zależy merge.
- „Warunek merge'a”: zastępuje go „Strażnik przy każdym Ważnym”.
- „Dowód reguły”: przypadki reguły to jej pole `metadata.przypadki` (#2098), a Ważne ze `Strażnik: ast-grep <id>` przechodzi tylko z wpisem na tej liście na HEAD i z dowodem reguły na nim, a nie z historii pól `Idiom:`.
- „Idiom bez reguły”: klasę `typ` zastępuje strażnik `mypy` z dowodem narzędzia, a klasy `brak-testu`, `stan-kroku` i `test-klasy` strażnik `brak - test`, którego dowód zostaje recenzentowi, więc luka „PASS bez punktu dowodu” zostaje tylko przy nim.
- „Status w Actions”: liczy warunek 5 w osobnym jobie (wyżej) i jest wymagany od 14.11.2026.
- „Konsekwencje”: poza osądem nie zostaje wybór postaci `bez reguły` ani dowód mutacji klasy `typ`, a dowód testu zostaje osądem przy `brak - test`; zdanie o stanie sprzed decyzji o rulesecie zdejmuje ten ADR z ADR 0036.
