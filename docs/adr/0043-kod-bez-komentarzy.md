# ADR 0043: Kod bez komentarzy

## Status

Przyjęta 19.11.2026: cel i kolejność stoją w sekcji „Rozwiązanie” specyfikacji #2227, a decyzje Maksa w jej sekcji „Decyzje Maksa (19.11.2026)”; reguły ponad nie są decyzjami autora z ticketu #2232 i stoją w osobnej sekcji.
Zmienia [ADR 0034](0034-kod-jest-pamiecia.md) w decyzji „Komentarze w `src`”: zakaz obejmuje cały kod repo i docstringi, a historia zmiany idzie tylko do opisu PR, nie do issue.
Każda reguła wchodzi ticketem specyfikacji #2227, który stoi przy niej; do jego merge'a obowiązuje dotychczasowe zdanie w [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md), a dzisiejszy strażnik (`reguly-ast-grep/komentarz-w-src.yml`) łapie komentarz tylko w `src`.

## Kontekst

Agenci czytają komentarze jak instrukcje: komentarz, który usprawiedliwia obejście, uczy następnego agenta to obejście powielać, a niezmiennik w komentarzu chroni kod tylko, dopóki agent go przeczyta.
Żadna maszyna nie sprawdza, czy komentarz mówi prawdę.

Pomiar z 19.11.2026 na `98013d2565` (specyfikacja #2227): 14 046 własnych komentarzy i docstringów (src 3056, tests 5826, tools 2333, `.agents` 1862, frontend 774, konfiguracja 195).
Maszyna czyta z nich 978: skrót modelu skilli `verify-*` (505 docstringów), opisy OpenAPI (234), `--help` narzędzi i skryptów skilli (94), spis narzędzi w `AGENTS.md` (32), odczyt `X.__doc__` w kodzie (14) i dyrektywy ruff i mypy (127); resztę, 13 068, czyta tylko człowiek.
Próba warstwowa 330 wpisów dała klasy twierdzeń: powtarza kod albo to, co już wymusza test, typ lub reguła (37%); wiedza, której kod nie wyraża, czyli niezmiennik, kolejność, granica albo powód (47%); fałszywe dziś (1%, zaniżone, bo jeden docstring modułu miał 10 fałszywych twierdzeń na 96); historia zmiany (6%); ograniczenie zewnętrzne prawdziwe dziś, np. Windows, Excel, OneDrive, GitHub (9%).

Eksperyment: 9 świeżych agentów Opus, 3 zadania, każde w trzech warunkach, checkouty bez historii, ślepy recenzent.

| zadanie (niezmiennik) | z komentarzami | komentarze usunięte | usunięte, wiedza zakodowana |
|---|---|---|---|
| czytnik ekranu przy ponownym odczycie (`aria-busy` tylko na szkielecie) | zachowany | zachowany | zachowany |
| data `9.11.2026` w przypomnieniach (wpis Zmiany z Wydania, które wyszło, się nie zmienia) | zachowany | złamany: poprawiony wydany wpis | zachowany |
| z którego komputera przyszły Logi (nazwa komputera nie wychodzi) | zachowany | złamany: `platform.node()` | zachowany |

`tools/szybko.py` przeszedł w obu złamaniach, a agenci z zakodowaną wiedzą nazwali mechanizm, który ich zatrzymał (test, zakaz ruff).

## Decyzja

Kod repo, czyli pliki, które liczył pomiar (Python, TypeScript i JavaScript w `src/`, `tests/`, `tools/`, skryptach skilli i `frontend/` oraz pliki konfiguracji), nie ma komentarzy ani docstringów poza wyjątkami niżej.

### Cel i kolejność (specyfikacja #2227)

- **Zakoduj, potem usuń.** Wiedza, której nie ma nigdzie poza komentarzem, przechodzi do kodu najwyższym szczeblem drabiny ze skilla [`przeglad`](../../.agents/skills/przeglad/SKILL.md) (nazwa, typ, test zachowania, reguła) i dopiero potem komentarz znika, a komentarz, który nic nie dodaje (powtarza kod albo jest historią), znika od razu.
  Powód: w eksperymencie usunięcie komentarzy bez kodowania złamało dwa z trzech niezmienników przy zielonym `tools/szybko.py`, a ta sama wiedza zakodowana zatrzymała obu agentów.
  Wchodzi w #2236 (kodowanie wiedzy) i #2235 (usuwanie komentarzy, które powtarzają kod albo są historią).

### Decyzje Maksa (19.11.2026)

- **Docstringi też znikają, w drugiej kolejności.** Docstring znika jak komentarz, ale dopiero po wyniesieniu tekstu czytanego przez program (#2230) i po skrócie modelu skilli `verify-*` bez docstringów (#2231).
  Powód: docstring czytany tylko przez człowieka niesie te same niesprawdzane twierdzenia co komentarz, a 978 wpisów czyta maszyna, więc ich usunięcie przed tymi ticketami psuje `--help`, spis narzędzi i skrót modelu.
  Wchodzi w #2235 i #2236, po #2230 i #2231.
- **Tekst czytany przez program w nazwanej stałej.** Tekst, który czyta program (`--help`, spis narzędzi, zasady drukowane przez inne narzędzie), nie jest komentarzem i mieszka w nazwanej stałej modułu, a nie w `__doc__`.
  Powód: usunięty docstring psuje `--help` po cichu, a usunięta stała nie przechodzi mypy.
  Wchodzi w #2230.
- **Lista wyjątków.** Komentarzem zostają tylko dyrektywy narzędzi w obecnych postaciach (`# noqa: KOD - powód`, `# type: ignore[kod]`), `// SAFETY: powód`, `// @ts-expect-error powód`, `// oxlint-disable-next-line reguła -- powód`, shebang oraz ograniczenie zewnętrzne tylko w postaci `# ZEWNĘTRZNE: fakt (źródło)`, którą reguła liczy, a linków do issue w kodzie nie ma.
  Powód: dyrektywę czyta narzędzie, ograniczenie zewnętrzne jest prawdą o świecie poza repo, której kod nie wyrazi, a jedna postać ze źródłem pozwala regule je policzyć.
  Wchodzi w #2234 (reguła na liniach dodanych) i #2236 (ograniczenie zewnętrzne dostaje swoją postać albo przechodzi do nazwy i testu).
- **Miejsce na „dlaczego”.** „Dlaczego”, którego nie wyrazi kod, idzie tak: decyzja do ADR, motywacja domenowa do [`GLOSSARY.md`](../../GLOSSARY.md), historia zmiany do opisu PR, a nie do issue.
  Powód: issue się zamyka, więc „dlaczego” zapisane tylko w issue przestaje być widoczne tam, gdzie agent pracuje.
  Wchodzi tym ADR (#2232).
- **Kolumna `identyfikator`.** `GLOSSARY.md` ma kolumnę `identyfikator` (pojęcie po polsku → nazwa w kodzie, np. Wydanie → `release`) z testem, że nazwa istnieje w kodzie.
  Powód: nazwa to pierwszy szczebel kodowania wiedzy z komentarza, więc pojęcie i nazwa w kodzie muszą się zgadzać, a test pada, gdy nazwa z kolumny zniknie z kodu.
  Wchodzi tym ADR (#2232).

### Decyzje autora (#2232)

- **Kolumna dla każdego hasła.** Tabela `identyfikator` ma wiersz każdego hasła `GLOSSARY.md` w kolejności haseł, z `–` dla pojęcia bez nazwy w kodzie, a nazwa to definicja w Pythonie `src/` albo `tools/` (moduł, klasa, funkcja, parametr, przypisanie) albo `Klasa.składowa` dla składowej klasy (`tests/test_glossary.py`).
  Powód: nowe hasło bez wiersza pada w teście, więc jego nazwa w kodzie jest rozstrzygnięta przy dopisaniu hasła, a nazwa tylko importowana albo użyta nie jest domem pojęcia.
- **Model TLA+.** Komentarz w modelu TLA+ skilla `verify-*`, który nazywa kod, za który stoi akcja albo straż modelu, zostaje.
  Powód: pomiar specyfikacji nie liczył modeli TLA+, a w skillu, którego `SKILL.md` nie ma tabeli kroków, ten komentarz jest jedynym wiązaniem modelu z kodem (`tools/lib/rozjazd_modelu.py`), więc przeniesienie wiązania do tabeli to osobna decyzja.
- **Tabela przypadków to test.** Sprawdzenie, które obiecuje całą klasę, zapisuje swoją tabelę przypadków jako sparametryzowany test z `id` każdego przypadku, a nie w docstringu.
  Powód: tabela w docstringu zniknęłaby z docstringami i nie biegnie, a id przypadku stoi w wyniku pytest przy jego porażce.
- **Granica sprawdzenia.** Granica sprawdzenia stoi jako przypadek jego testu (próbka znanej luki albo `pytest.param` z `id`), a prozą tylko w jego wierszu `CODING_STANDARDS.md` po `boundary:`, gdy żaden test jej nie uruchomi: tak stoją granice reguł `npm run rules`, których zadania pytest nie uruchomią bez zależności frontendu, przeniesione z komentarza `frontend/scripts/rules.mjs` do tabeli sekcji Frontend.
  Granica, która dziś stoi w docstringu albo komentarzu, przechodzi do przypadku albo wiersza przy najbliższej zmianie tego sprawdzenia.
  Powód: granica w komentarzu znika razem z nim, a przypadek testu pada, gdy sprawdzenie zacznie ją łapać.
- **Powód `zip(strict=False)` w kodzie.** Dłuższą z założenia stronę `zip` kod przycina do długości krótszej i bierze `strict=True`, a `strict=False` zostaje tylko tam, gdzie ta sama funkcja zgłasza inną długość tuż za pętlą albo jedna strona jest nieskończona.
  Powód: dotąd regułą był komentarz albo docstring z nazwą sprawdzenia długości, a przycięcie i sprawdzenie obok `zip` mówią to samo kodem.

## Odrzucone warianty

- **Zakaz komentarzy od razu, bez kodowania wiedzy.** Eksperyment: usunięcie bez kodowania złamało dwa z trzech niezmienników, a `tools/szybko.py` tego nie zauważył.
- **„Dlaczego” w issue z linkiem w kodzie.** Issue się zamyka, a link do issue w kodzie jest tym samym komentarzem, którego nikt nie sprawdza.
- **Identyfikator jako zdanie w każdym haśle zamiast tabeli** (decyzja autora). Jedna tabela czyta się i sprawdza w jednej postaci, którą test przyjmuje albo odrzuca, a zdania w hasłach rozmyłyby się w prozie definicji.

## Konsekwencje

- Do merge'a #2234 nowy komentarz poza `src` łapie tylko przegląd, a recenzent zgłasza go jako Drobne, bo reguła jest punktem `CODING_STANDARDS.md` bez strażnika.
- Docstring, który czyta program, zostaje do #2230 i #2231; nowe narzędzie do tego czasu dalej dostaje docstring, z którego `--help` i spis narzędzi biorą swój tekst.
- Istniejące komentarze i docstringi czekają na fale #2235 i #2236, a zmiana, która dotyka modułu z komentarzem, może go zakodować i usunąć w tym samym PR.
