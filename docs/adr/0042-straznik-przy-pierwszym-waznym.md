# ADR 0042: Strażnik przy pierwszym Ważnym

## Status

Przyjęta na decyzję Maksa z 18.11.2026 w wątku koordynatora programu chwastów, jego słowami: „tak bramka ma przejmowac” (bramka przyjmuje strażnika każdego rodzaju z dowodem, który liczy narzędzie, a nie recenzent).
Zmienia jego wybór z 15.11.2026 („recenzent jako bramka”, [#1912](https://github.com/maximiseartai/MAXIMISEART-Dad/pull/1912#issuecomment-6902436281)) w punkcie „Idiom bez reguły” [ADR 0036](0036-chwast-to-regula.md) i decyzje tego ADR z listy „Zmienia te zdania”; odwracalna przez revert.
Wchodzi razem z kodem, który ją wdraża, a ten plik wyznacza chwilę wdrożenia (`bramka_straznika.MARKER`).

## Kontekst

Od 14.11.2026 PR-y z werdyktem `FAIL` miały 13 pól `Idiom:` w 9 PR-ach i żadnego z id reguły, więc warunek merge'a z polem `Idiom:` nie zażądał reguły ani razu (audyt 17.11.2026, liczony z komentarzy PR-ów).
Model TLA+ tego procesu łamie regułę „druga kopia idiomu ma regułę” tylko wtedy, gdy recenzent przeoczy powtórkę, a dominujące klasy Ważnych (nieczytelny plik liczony jak brak, druga droga obok właściciela) zamyka typ, test zachowania albo kontrakt, których dowodu bramka nie umiała.
Dowód typu i testu z #1912 odpadł po czterech rundach, bo autor pisał tekst mutacji (r1: wcięcie, r2: zasięg) albo bramka czytała tekst wyjścia narzędzi, którego format ustawia `pyproject.toml` PR (r3, r4).

## Decyzja

- **Strażnik przy każdym Ważnym.** Blok każdego Ważnego w sekcji `## Korzeń` opisu PR kończy linia `Strażnik: <selektor>` z zamkniętej listy, także po `Wyrwany w #M`, zamiast autorskiego `Dowód:`, który zostaje tylko w bloku czerwonego `main`.
  Autor wybiera tylko selektor; złą postać wyznacza drzewo SHA werdyktu `FAIL` w miejscach jego pola `Gdzie`, a wynik liczy narzędzie.
  Listę, przywrócenie błędu przy każdym rodzaju i granice podaje jeden właściciel: docstring `tools/lib/straznik.py`, a bramkę `tools/lib/bramka_straznika.py` (warunek 5 `tools/scal_pr.py`).
  Powód: strażnik powstaje przy pierwszym Ważnym, więc rozpoznanie powtórki przez recenzenta przestaje być warunkiem.
- **Dowód bez tekstu autora.** Bramka czyta tylko kod wyjścia pytest i znaleziska mypy i ruff w formacie JSON z wiersza poleceń dowodu, więc ani tekst mutacji, ani format wyjścia z konfiguracji PR wyniku nie zmienia.
  Powód: prototyp na dziesięciu Ważnych z przeszłości (tabela w komentarzu PR, który dodał ten ADR) dał dowód `WYKRYTA` dla 6 z 6 Ważnych z mechanizmem i 0 z 8 fałszywych `WYKRYTA` strażnika niezwiązanego z błędem, a mutacja z pliku PR z warunkiem „zamiana to tekst z SHA `FAIL`” przepuściła 7 z 9 sond obejścia.
- **Wyjątki.** `brak - proza` sprawdza narzędzie (każde miejsce `Gdzie`, które zmienił PR, to `.md`, docstring albo komentarz), a `brak - test` (miejsca tylko w `tests/`, czyli próbka testu bez przypadku z obietnicy) i `brak - napęd` (miejsca tylko w `frontend/`, a strażnik to krok napędu skilla `verify-*`) narzędzie co do miejsca, a dowód recenzent następnej rundy: mutację złej implementacji albo krok napędu na drzewie `FAIL`, jak dotąd.
  Powód: dowód testu, który nie łapie złej implementacji, potrzebuje tej implementacji, a drzewo SHA `FAIL` jej nie ma; frontend nie ma testów jednostkowych, a krok napędu potrzebuje przeglądarki i zbudowanego frontendu, których job dowodu nie ma (#2104 W1 r1).
- **Gdzie liczy dowód.** Pytest i mypy wykonują kod PR, więc status „Werdykt i bramka” liczy warunek 5 w jobie `dowod` bez prawa zapisu, a job `status` liczy warunki 1–4 kodem `main` i bierze z `dowod` tylko przyczyny warunku 5 dla tego samego SHA HEAD.
  Powód: kod PR nie dostaje tokenu, który ustawia statusy (#1912 r1, `R-KOD-PR-Z-TOKENEM`), a może zmienić najwyżej własny warunek 5, jak test, który niczego nie sprawdza.
- **Pole `Idiom:`.** Nie zatrzymuje już merge'a; postacie `<id> jak #N W<n> r<k>` i `<id>` zostają adnotacją recenzenta dla raportu tygodniowego, a postać `bez reguły <klasa>` z tabelą klas czyta raport tylko w werdyktach sprzed tego ADR.

## Odrzucone warianty

- **Mutacja z pliku JSON w PR, której zamiana musi być tekstem z SHA `FAIL`.** Autor wybiera miejsce zamiany, więc ten sam tekst w złym miejscu (w funkcji przed definicją nazwy, na poziomie modułu) daje fałszywe `WYKRYTA` (#1912 r1–r2; prototyp: 7 z 9 sond).
- **Cofnięcie samych hunków przy `Gdzie` dla pytest.** Mieszanka kodu z `FAIL` i HEAD wywraca test, który na całym drzewie `FAIL` przechodzi (prototyp, #2059 W1 r1).
- **Recenzent jako bramka typu i testu (#1912).** Zostawia warunek, którego dotrzymanie zależy od tego, czy recenzent rozpozna powtórkę i napisze dowód.

## Konsekwencje

- Wątek z werdyktem sprzed wdrożenia tego ADR kończy po staremu, z `Dowód:` w bloku Ważnego (`bramka_straznika.applies`, decyzja Q20 ADR 0031).
- Strażnik innej poprawki tego samego PR przechodzi dowód pytest każdego Ważnego tej rundy; jego trafność ocenia recenzent następnej rundy z linii dowodu, która nazywa padły test albo znalezisko.
- Dowód pytest trwa tyle, co test dwa razy, a mypy około 10 s na Macu, więc status przy PR z `FAIL` przychodzi później niż dziś.

## Zmienia te zdania ADR 0036

- „Pole werdyktu”: pole `Idiom:` w trzech postaciach przestaje być polem, od którego zależy merge.
- „Warunek merge'a”: zastępuje go „Strażnik przy każdym Ważnym”.
- „Dowód reguły”: przypadki reguły to jej pole `metadata.przypadki` (#2098), a Ważne ze `Strażnik: ast-grep <id>` przechodzi tylko z wpisem na tej liście na HEAD i z dowodem reguły na nim, a nie z historii pól `Idiom:`.
- „Idiom bez reguły”: klasy `brak-testu`, `stan-kroku`, `typ` i `test-klasy` zastępuje strażnik z dowodem narzędzia, a luka „PASS bez punktu dowodu” zostaje tylko przy `brak - test`.
- „Status w Actions”: liczy warunek 5 w osobnym jobie (wyżej) i jest wymagany od 14.11.2026.
- „Konsekwencje”: poza osądem nie zostaje wybór postaci `bez reguły` ani dowód mutacji klas `typ` i `test-klasy`, a zdanie o stanie sprzed decyzji o rulesecie zdejmuje ten ADR z ADR 0036.
