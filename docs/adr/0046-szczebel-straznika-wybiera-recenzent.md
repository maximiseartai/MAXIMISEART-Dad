# ADR 0046: Szczebel strażnika wybiera recenzent

## Status

Przyjęta na decyzje Maksa z 20.11.2026 w sesji pytań do specyfikacji [#2448](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/2448), cytowane niżej jego słowami; odwracalna przez revert.
Zmienia [ADR 0042](0042-straznik-przy-pierwszym-waznym.md) w decyzjach „Strażnik przy każdym Ważnym”, „Kod usunięty z PR” i „Pole `Idiom:`” oraz w aneksie „Lekka runda przeglądu PR samych narzędzi”, punkt „Lekka runda”, [ADR 0036](0036-chwast-to-regula.md) w decyzji „Pole werdyktu”, a [ADR 0031](0031-korzen-po-fail-i-chwasty.md) w decyzji o miejscu szczebla (d) w „Szczebel i dowód” (lista w sekcjach „Zmienia te zdania” niżej).
Wchodzi razem z polem `Mechanizm:` szablonu werdyktu, a ten plik wyznacza chwilę jego wdrożenia (`szablon_werdyktu.MECHANISM_ADR`).
Resztę decyzji wdrażają tickety specyfikacji z sekcji „Wdrożenie”, a do merge'a każdego obowiązuje dotychczasowe zdanie ADR 0042, skilla [`przeglad`](../../.agents/skills/przeglad/SKILL.md) i `tools/scal_pr.py`.

## Kontekst

Cel Maksa: żaden błąd znaleziony w przeglądzie nie wraca w kolejnej pracy agentów, bo każde Ważne kończy się mechanizmem, który odmawia nowej kopii błędu, albo zmianą architektury, po której błąd nie ma gdzie wrócić.
ADR 0042 daje wybór strażnika autorowi PR, a pomiar specyfikacji #2448 z 20.11.2026 (513 Ważnych werdyktów `FAIL` ze 192 PR-ów od 13.11.2026, materiałem był kod przy `Gdzie` i diff poprawki) pokazał:

- od wdrożenia warunku strażnika 64 z 64 Ważnych scalono ze strażnikiem `pytest` albo wyjątkiem `brak - …`, a żadne z `mypy`, `ruff` ani `ast-grep`, choć dwóch oceniających na ślepo (kappa 0,67) uznało 13% wszystkich Ważnych za zamykane typem, zakazem ruff albo regułą ast-grep;
- `Strażnik: brak - usunięte` nie ma mechanizmu, a zakaz usuniętej postaci zamyka 14 z 26 takich Ważnych od 19.11;
- pole `Idiom:` recenzent wpisał ostatni raz 19.11.2026 o 20:21, a w tym samym oknie historia gita ma trzy poszerzenia reguły `regula-w-trasie` (#1904, #1919, #1964), których raport tygodniowy nie pokazał.

## Decyzje Maksa (20.11.2026)

Pytania i odpowiedzi z sesji, odpowiedź Maksa w cudzysłowie:

- **Najwyższy szczebel, który działa** (Q1, „1.b”). Gdy błąd da się zamknąć strukturą, test go nie zastępuje; gdy nie da się wcale (proza, błąd jednorazowy w treści), zostaje strażnik jak dziś.
- **Szczebel wybiera recenzent, według piramidy** (Q2, „2. a i musi prioretyzowac najwyższe poziomy piramidy potato”). Recenzent, nie autor, wpisuje w Ważnym pole `Mechanizm:` ze szczeblem piramidy [ADR 0031](0031-korzen-po-fail-i-chwasty.md): `architektura`, `refaktor`, `lint`, `test`, `weryfikacja`, w tej kolejności pierwszeństwa. Recenzent następnej rundy daje Ważne, gdy pokaże działający wyższy szczebel.
- **Usterki z `main` od razu** (Q3, „tak”): tickety #2456, #2457 i #2458.
- **Lekka runda zostaje** (Q4, „tak”), a Ważne ze szczeblem `lint` dostaje lint także w PR samych narzędzi.
- **Pomiar bez pola `Idiom:`** (Q5, „tak” po trzech rundach wyjaśnień). Pole znika z szablonu, raport tygodniowy liczy odpalenia każdego strażnika z kodu w Required CI późniejszych PR-ów, poszerzenia reguł i ponowny dowód scalonych strażników, a powrót w nowej postaci liczy cotygodniowy audyt: pary od narzędzia ocenia dwóch agentów na ślepo, a zgodna para to ucieczka, której strażnik trzeba podnieść.
- **Bez selektora `import-linter`** (Q6, „6. tak”), dopóki któreś Ważne go nie potrzebuje; buduje go PR tego Ważnego.
- **Architektura ma strażnika obejścia** (Q7, „7. tak”): szczebel `architektura` (jeden właściciel, usunięta druga droga, typ, z którym zły stan jest niewyrażalny) przechodzi tylko z mechanizmem, który odmawia obejścia nowej struktury: typem, zakazem `TID251` właściciela albo regułą ast-grep.
- **Zaległe Ważne dostają strażników wstecz** (Q9, „9. tak”) tam, gdzie pomiar dał regułę bez rosnącej listy i z fałszywymi alarmami w najwyżej 10% PR-ów, i tam, gdzie zakaz usuniętego kodu łapie złą postać; zaległych Ważnych szczebla „właściciel” nie przerabiamy wstecz.
- **Usunięty kod** (Q10, „10. tak”): `brak - usunięte` wymaga zakazu usuniętej postaci (zakaz nazwy albo reguła na złej postaci z drzewa `FAIL`); gdy się nie da, recenzent wpisuje niższy szczebel.

## Decyzje autora specyfikacji

Reguły, które zaproponował autor specyfikacji, a Maks przyjął jednym „tak” do pytania (Q8 „8. tak”, Q11 „11. tak”):

- **Szczebel, który nie działa.** Reguła z fałszywym alarmem w ponad 10% PR-ów dowodu `tools/na_scalonych_pr.py --regula` albo z listą nazw, która rośnie z każdym nowym kodem, znaczy „szczebel nie działa”, a recenzent schodzi niżej bez osobnej zgody. Powód: próg 10% już stoi w dowodzie reguły, a 12 z 67 kandydatów z pomiaru potrzebowało rosnącej listy, jak `regula-w-trasie`.
- **Właściciel.** Błąd logiki w jedynym właścicielu, którego jedyność już pilnuje zakaz albo typ, zamyka test na właścicielu (szczebel `test`). Jedyny właściciel bez takiej ochrony to szczebel `architektura`: PR dopisuje zakaz albo regułę, która kieruje do niego resztę kodu. Powód: 76 ze 106 niezgód oceniających w pomiarze dotyczyło granicy „właściciel z testem” albo „żaden”.

Decyzje autora tego PR:

- **Numer 0046**, bo 0045 rezerwuje specyfikacja #2439.
- **Pole `Mechanizm:` stoi po `Szczebel:`**, który zostaje: `Szczebel:` mówi, jak autor wyrwał korzeń, a `Mechanizm:`, jakiego strażnika żąda Ważne.
- **Przejście.** Wątek, którego pierwszy werdykt powstał przed wejściem tego pliku do bazy PR, kończy po staremu, bez pola `Mechanizm:` i z opcjonalnym `Idiom:` (`werdykt_pr.rule_applies`, jak decyzja Q20 ADR 0031); stare werdykty z `Idiom:` czyta `szablon_werdyktu.findings` jak dotąd, więc raport tygodniowy liczy je do czasu ticketu #2463.

## Wdrożenie

| Decyzja | Ticket |
|---|---|
| pole `Mechanizm:` w szablonie, kryteria szczebli w skillu `przeglad`, ten ADR | #2459 |
| mapa szczebla na selektory strażnika, strażnik obejścia, `brak - usunięte` | #2460 |
| test jako strażnik tylko przy chronionym właścicielu | #2461 |
| lekka runda z lintem dla szczebla `lint` | #2462 |
| raport: odpalenia strażników i poszerzenia reguł zamiast `Idiom:` | #2463 |
| raport: ponowny dowód scalonych strażników | #2464 |
| raport: pary do audytu i audyt na ślepo | #2465 |
| zaległe reguły i zakazy usuniętego kodu | #2466, #2467, #2468, #2469 |

## Zmienia te zdania ADR 0042

- „Strażnik przy każdym Ważnym”: „Autor wybiera tylko selektor” zastępuje wybór szczebla przez recenzenta, a autor wybiera selektor spośród tych, których żąda szczebel z pola `Mechanizm:`.
- „Kod usunięty z PR”: `brak - usunięte` nie wystarcza przy szczeblach `architektura`, `refaktor` i `lint`, gdzie strażnikiem jest zakaz usuniętej postaci.
- „Pole `Idiom:`”: pole znika z szablonu dla nowych wątków, a raport przestaje liczyć z niego powroty.
- Aneks „Lekka runda przeglądu PR samych narzędzi”, punkt „Lekka runda”: Ważne ze szczeblem `lint` w takim PR potrzebuje bloku w `## Korzeń` i strażnika.

## Zmienia te zdania ADR 0031

- „Szczebel i dowód”, zdanie „Zapadka (d) stoi między (c) a (e) […]: (d) jest dozwolona tylko wtedy, gdy (a)–(c) nie działają”: pierwszeństwo szczebli daje piramida pola `Mechanizm:`, w której reguła ast-grep (szczebel `lint`) stoi przed testem, więc działająca reguła (d) idzie przed testem (c); (e) zostaje dozwolone tylko wtedy, gdy (a)–(d) nie działają. Litery (a)–(e) pola `Szczebel:` zostają, a „Wyżej nie, bo:” ma linię na każdy szczebel przed wpisanym w tym pierwszeństwie, w kolejności liter, więc blok (c) mówi też, czemu nie (d), a blok (d) nie mówi o (c) (bramka korzenia od #2460).

## Zmienia te zdania ADR 0036

- „Pole werdyktu”: pole recenzenta, od którego zależy strażnik, to `Mechanizm:` ze szczeblem piramidy, a nie `Idiom:` w trzech postaciach; powód „Autor nie wybiera postaci, więc nie może wybrać tańszej” zostaje i obejmuje teraz szczebel.

## Odrzucone warianty

- **Każde Ważne z lintem, typem albo kontraktem** (Q1 a): w pomiarze 55% Ważnych nie zamyka żaden mechanizm, więc około połowy PR-ów z `FAIL` nie miałoby wyjścia.
- **Szczebel bez recenzenta** (Q2 c): to osąd, a dwóch oceniających zgadzało się w 79%.
- **Obowiązkowe pole „Powrót:” w werdykcie** (Q5): stoi na tym, że recenzent rozpozna powtórkę, a ADR 0042 zmierzył, że pole `Idiom:` tego nie dawało.

## Konsekwencje

- Werdykt nowego wątku z Ważnym bez pola `Mechanizm:`, z wartością spoza listy albo z polem `Idiom:` nie przechodzi `tools/scal_pr.py --werdykt` ani zgody na merge, a odmowa podaje postać pola.
- Listę szczebli trzyma jeden moduł, `szablon_werdyktu.Mechanism`, a skill `przeglad` i bramka strażnika biorą ją z niego.
- Do merge'a #2460 strażnika szczebla sprawdza recenzent następnej rundy, a bramka liczy dowód selektora, który wpisał autor, jak w ADR 0042.
