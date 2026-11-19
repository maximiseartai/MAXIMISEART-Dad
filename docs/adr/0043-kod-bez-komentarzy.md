# ADR 0043: Kod bez komentarzy

## Status

Przyjęta 19.11.2026: cel i kolejność stoją w sekcji „Rozwiązanie” specyfikacji #2227, a decyzje Maksa w jej sekcji „Decyzje Maksa (19.11.2026)”; reguły ponad nie są decyzjami autora z ticketu #2232 i stoją w osobnej sekcji.
Zmienia [ADR 0034](0034-kod-jest-pamiecia.md) w decyzji „Komentarze w `src`”: zakaz obejmuje cały kod repo i docstringi, a historia zmiany idzie tylko do opisu PR, nie do issue.
Każda reguła wchodzi ticketem specyfikacji #2227, który stoi przy niej; do jego merge'a obowiązuje dotychczasowe zdanie w [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md), a strażnicy komentarzy od #2234 to `reguly-ast-grep/komentarz-w-src.yml` (każda linia `src`), `reguly-ast-grep/komentarz-poza-src.yml` i reguła oxlint `repo/no-comments` (linie dodane poza `src` i we frontendzie).

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

Kod repo nie ma komentarzy ani docstringów poza listą wyjątków Maksa niżej (cel specyfikacji #2227: „kod bez komentarzy”).
Czy komentarze modeli TLA+ skilli `verify-*` dostają wyjątek, rozstrzyga Maks w #2255; do jego odpowiedzi czekają jak inne istniejące komentarze.

### Cel i kolejność (specyfikacja #2227)

- **Zakoduj, potem usuń.** Wiedza, której nie ma nigdzie poza komentarzem, przechodzi do kodu najwyższym szczeblem drabiny ze skilla [`przeglad`](../../.agents/skills/przeglad/SKILL.md) (nazwa, typ, test zachowania, reguła) i dopiero potem komentarz znika, a komentarz, który nic nie dodaje (powtarza kod albo jest historią), znika od razu.
  Powód: w eksperymencie usunięcie komentarzy bez kodowania złamało dwa z trzech niezmienników przy zielonym `tools/szybko.py`, a ta sama wiedza zakodowana zatrzymała obu agentów.
  Wchodzi w #2236 (kodowanie wiedzy) i #2235 (usuwanie komentarzy, które powtarzają kod albo są historią).

### Decyzje Maksa (19.11.2026)

Każdy punkt to słowa Maksa z sekcji „Decyzje Maksa (19.11.2026)” specyfikacji #2227, z ticketami 3 i 4 jako #2230 i #2231; powód stoi przy punkcie tylko tam, gdzie Maks go podał, a powody i przykłady autora stoją niżej, w „Powodach autora”.

- **Docstringi też znikają, w drugiej kolejności:** po wyniesieniu tekstu czytanego przez program (#2230) i po skrócie modelu bez docstringów (#2231).
  Wchodzi w #2235 i #2236, po #2230 i #2231.
- **Tekst czytany przez program to nie komentarz, ale mieszka w nazwanej stałej, nie w `__doc__`.**
  Powód Maksa: usunięty docstring psuje `--help` po cichu, usunięta stała nie przechodzi mypy.
  Wchodzi w #2230.
- **Lista wyjątków:** dyrektywy narzędzi w obecnych postaciach (`# noqa: KOD - powód`, `# type: ignore[kod]`), `// SAFETY: powód`, `// @ts-expect-error powód`, `// oxlint-disable-next-line reguła -- powód`, shebang, oraz ograniczenie zewnętrzne tylko w postaci `# ZEWNĘTRZNE: fakt (źródło)`, którą reguła liczy. Linków do issue w kodzie nie ma.
  Wchodzi w #2234 (reguła na liniach dodanych) i #2236 (ograniczenie zewnętrzne dostaje swoją postać albo przechodzi do nazwy i testu).
- **„Dlaczego”, którego nie wyrazi kod:** decyzja do ADR, motywacja domenowa do [`GLOSSARY.md`](../../GLOSSARY.md), historia do opisu PR; nie do issue.
  Powód Maksa: issue się zamyka.
  Wchodzi tym ADR (#2232).
- **`GLOSSARY.md` dostaje kolumnę `identyfikator`** (pojęcie po polsku → nazwa w kodzie) z testem, że nazwa istnieje.
  Wchodzi tym ADR (#2232).

### Powody autora (#2232) przy decyzjach Maksa

Tych powodów i przykładów Maks nie podał; dopisał je autor ADR.

- **Docstringi:** docstring czytany tylko przez człowieka niesie te same niesprawdzane twierdzenia co komentarz, a 978 wpisów czyta maszyna, więc ich usunięcie przed #2230 i #2231 psuje `--help`, spis narzędzi i skrót modelu.
- **Tekst czytany przez program:** przykłady takiego tekstu to `--help`, spis narzędzi w `AGENTS.md` i zasady drukowane przez inne narzędzie.
- **Lista wyjątków:** dyrektywę czyta narzędzie, ograniczenie zewnętrzne jest prawdą o świecie poza repo, której kod nie wyrazi, a jedna postać ze źródłem pozwala regule je policzyć.
- **„Dlaczego” poza issue:** „dlaczego” zapisane tylko w issue przestaje być widoczne tam, gdzie agent pracuje.
- **Kolumna `identyfikator`** (np. Wydanie → `release`): nazwa to pierwszy szczebel kodowania wiedzy z komentarza, więc pojęcie i nazwa w kodzie muszą się zgadzać, a test pada, gdy nazwa z kolumny zniknie z kodu.

### Decyzje autora (#2232)

- **Kolumna dla każdego hasła.** Tabela `identyfikator` ma wiersz każdego hasła `GLOSSARY.md` w kolejności haseł, z `–` dla pojęcia bez nazwy w kodzie, a nazwa to definicja w Pythonie `src/` albo `tools/` (moduł, klasa, funkcja, parametr, przypisanie) albo `Klasa.składowa` dla składowej klasy (`tests/test_glossary.py`).
  Powód: nowe hasło bez wiersza pada w teście, więc jego nazwa w kodzie jest rozstrzygnięta przy dopisaniu hasła, a nazwa tylko importowana albo użyta nie jest domem pojęcia.
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

- Od #2234 komentarz na linii, którą zmiana dodaje poza `src` i we frontendzie, zatrzymuje Required CI (`komentarz-poza-src`, `repo/no-comments`), a w `src` każdy komentarz, jak dotąd (`komentarz-w-src`).
- Docstring, który czyta program, zostaje do #2230 i #2231; nowe narzędzie do tego czasu dalej dostaje docstring, z którego `--help` i spis narzędzi biorą swój tekst.
- Istniejące komentarze i docstringi czekają na fale #2235 i #2236, a zmiana, która dotyka modułu z komentarzem, może go zakodować i usunąć w tym samym PR.
- Komentarze modeli TLA+ skilli `verify-*` czekają na odpowiedź Maksa w #2255, a do niej kroki „Bring the model in line” ich `SKILL.md` zostają bez zmian.
