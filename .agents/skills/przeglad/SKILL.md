---
name: przeglad
description: Przegląd PR - co jest porażką i który plik skilla czyta autor, a który recenzent (kroki, dowody, postać werdyktu PASS albo FAIL, korzeń i szczebel, kolejne rundy). Użyj jako recenzent przed werdyktem i jako autor przed zleceniem przeglądu.
---

# Przegląd PR

`PASS` mówi też, że skille `verify-*` z linii `SKILLE VERIFY` przeszły na tym SHA (gotowość w `tools/scal_pr.py --help`).
Zlecenie przeglądu i brief koordynatora dodają tylko cel i punkty do sprawdzenia, a co jest Ważne, jakie dowody i jak opublikować werdykt, ustala ten skill.
Punkt do sprawdzenia może być tezą koordynatora („sprawdź, czy X nie daje wycieku”), bo Ważne z tezy stoi na tym samym powtarzalnym dowodzie co każde inne, więc werdykt nie oddziela znalezisk z tez od własnych (#950).

## Pliki trybów

Ten plik czyta każdy, a dalej każdy tryb czyta tylko swoje pliki, każdy w chwili z tej listy:

- Recenzent: [`recenzent.md`](recenzent.md) (checkout, kroki, dowody) od razu, [`porazka-adr.md`](porazka-adr.md), gdy diff zmienia ADR albo przegląd dotyczy specyfikacji lub issue `decyzja-maksa`, [`korzen.md`](korzen.md) i [`korzenie.toml`](korzenie.toml) przy pierwszym Ważnym, [`rundy.md`](rundy.md), gdy `--przeglad` pokazuje wcześniejszy werdykt PR, a [`korzen.md`](korzen.md), gdy któryś wcześniejszy werdykt ma Ważne.
- Autor: [`autor.md`](autor.md) przed zleceniem przeglądu, a [`korzen.md`](korzen.md) i [`rundy.md`](rundy.md) po `FAIL`.
- Poprawka operatora i czerwony `main` z prawdziwej zmiany: [`korzen.md`](korzen.md).

## Co jest porażką

Ważne znalezisko to defekt zachowania z dowodem, który da się powtórzyć: polecenie, jego wynik i plik:linia.
Tylko Ważne daje `FAIL`.
PR, któremu `--przeglad` drukuje `STAWKA | lekka`, ma Ważne tylko za zepsucie `main`, Wydania albo danych taty, a `tools/scal_pr.py` nie wymaga do niego bloku `## Korzeń` ani strażnika (aneks „Lekka runda” [ADR 0042](../../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)).
W tym repo Ważne były zwykle:

- mechanizm (reguła, narzędzie, krok skilla albo opcja issue `decyzja-maksa`), w którym krok powtarzany przy każdym wpisie, merge'u, wyjątku albo biegu czeka na zgodę albo czynność Maksa, choć nie należy do rodzajów decyzji Maksa z [`issue-tracker.md`](../../../docs/agents/issue-tracker.md), „Decisions for Maks”, i to samo sprawdzi reguła, recenzent albo narzędzie (#2008; `ZGODA KORZEŃ` zdjęta w [ADR 0036](../../../docs/adr/0036-chwast-to-regula.md), `ZGODA SZOPA` w #1622, opcja A #1888), oraz issue `decyzja-maksa` z decyzją spoza tych rodzajów;
- test, który przestał sprawdzać to, co sprawdzał (pokrycie zgubione przy refaktorze, asercja na tekst zamiast na zachowanie);
- próbka testu, która nie może paść na złej implementacji nazwanej przez test (w nazwie, id przypadku albo docstringu), bo w świecie próbki nie ma przypadku z obietnicy (plik „bez odczytu”, którego świat próbki nie ma; separator, który w tekście JSON staje się ucieczką), a dowodem jest ta zła implementacja, z którą test przechodzi; nocne mutacje jej nie złapią, bo PR z samymi testami nie dostaje mutanta (#2031, [ADR 0036](../../../docs/adr/0036-chwast-to-regula.md), klasa `brak-testu`; #1853, #1869, #1909);
- zachowanie widoczne tylko na Windows albo na najstarszym Pythonie z `requires-python` (brak `tzdata`, krok zegara `time.monotonic()` pod dawnym minimum 3.11, import, który pada tylko pod najstarszym Pythonem);
- stan, który jedna część przebiegu zakłada po innej (część podstawy skilla startująca od środka porządku);
- przypisanie albo zakres liczony od złej linii lub złego commitu (np. `git blame` pierwszej linii wielowierszowej instrukcji).
- zmiana wspólnego elementu okna Centrum (sekcja okna Ustawień, menu, toast, okno dialogowe), która wywraca funkcję drive `verify-centrum-rozliczen` inną niż ta, którą autor uruchomił (#1517: nowa sekcja wywróciła `okno-ustawien`, które wymienia każdą sekcję).
- linia wyniku dla człowieka przepisana z listy wyników cudzego narzędzia (skilla pstack, kroku CI) bez gałęzi, którą to narzędzie zgłasza obok wyniku, więc człowiek czytający tylko linię jej nie widzi (#1875: błąd produktu znaleziony w przebiegu utrzymania skilli kończył się linią `clean`);
- fikstura albo przykład testu narzędzia, które czyta prywatne dane (transkrypty Claude Code, baza T3, pliki taty), z tekstem, nazwą sesji albo katalogu przepisanymi z prawdziwych danych zamiast wymyślonych, bo repozytorium jest publiczne, a CI tych danych nie ma, więc nic przed pushem cytatu nie odróżni (#1914: wiadomości operatora w teście `tools/poprawki_operatora.py`);
- nowy plik w `PARSERS` w `tests/test_zapadki.py` bez powodu w opisie PR albo z powodem nieprawdziwym, czyli taki, że reguła ruff, ast-grep albo test zachowania jednak wystarczają (#1888);

Dziura w sprawdzeniu to też defekt zachowania.
W PR, który dodaje albo zmienia sprawdzenie (test struktury, checker, hook, skrypt mutacji, bramka CI, reguła lintu), Ważne jest odtworzony przypadek, który według wiersza reguły, docstringu albo opisu PR to sprawdzenie powinno wywrócić, a ono go przepuszcza, i wywrócenie się sprawdzenia na poprawnym wejściu.
To Ważne także wtedy, gdy produkt na tym SHA zachowuje się dobrze (ADR 0023).
Sprawdzenie, które PR zmienia, to także inne sprawdzenie, którego wynik PR zmienia nowym testem, wpisem albo konfiguracją: gdy przez tę zmianę przepuszcza ono przypadek, który według swojej reguły powinno zgłosić, to też Ważne (np. #670: nowy test struktury trafia do testów nocnych mutacji i zabija mutanta samą zmianą tekstu linii, więc noc nie zgłasza linii bez testu zachowania).

Drobne znalezisko to luka bez defektu: przeżyta mutacja w kodzie, który zachowuje się poprawnie, także w nowym kodzie, którego merge-base nie ma (wyjątek: mutacja `WYKRYTA` na merge-base, a `NIEWYKRYTA` na HEAD, to test, który przestał sprawdzać, czyli Ważne), nieaktualne zdanie w dokumencie, kosztowna, ale poprawna droga.
Przeżyta mutacja w kodzie sprawdzenia też jest Drobna, gdy nie odtworzyłeś przypadku, który sprawdzenie przepuszcza wbrew swojej regule.
Czysty PR z nowym sprawdzeniem, w którym nie odtworzyłeś dziury, dostaje więc `PASS`.
Drobnych podaj najwyżej 3, najważniejsze.
Defekt, który zmiana PR wywołuje albo ujawnia, liczy się do werdyktu także wtedy, gdy siedzi w pliku, którego PR nie zmienia (np. nowa konfiguracja uruchamia niezmieniony kod w nowym stanie).
Istniejące wcześniej to tylko defekt, który powtarzasz na merge-base bez tej zmiany, i do werdyktu się nie liczy.
Przypadek zbudowany tylko z pliku spoza dziedziny, którą wyznacza decyzja Maksa w ADR (dziś pliki łamiące pewniki wklejenia INTERMAX, [ADR 0025](../../../docs/adr/0025-regula-danych-wysylki-do-skrzynki.md), sekcja „Pewniki i granica dziedziny”), nie jest defektem.
Styl, nazwy i formatowanie zostawiasz ruffowi, mypy i lintom frontendu.

## Postać werdyktu

Werdykt jest zwięzły: każda linia ma miejsce w szablonie, bez prozy poza nim.

```markdown
WERDYKT: FAIL <pełny SHA HEAD>
Znaleziska: 2 (Ważne 1, Drobne 1)
### W1. <defekt zachowania jednym zdaniem>
Gdzie: <plik:linia>
Dowód: <polecenie i wynik, najwyżej 5 linii po 300 znaków; cytat z polem w bloku kodu>
Korzeń: <R-KOD z korzenie.toml> - <zdanie> (albo NOWY R-KOD - <opis> z kodem spoza listy)
Szczebel: <(a)–(e)> - <zdanie, czemu ten>
Idiom: <id> jak #N W<n> r<k> (albo Idiom: <id>; opcjonalne, tylko gdy Ważne powtarza wcześniejsze albo ucieka strażnikowi)
### D1. <luka jednym zdaniem>
Gdzie: <plik:linia>
### Mutacja W<n> r<k>
~~~
[{"nazwa": "<jaki błąd przywraca>", "zmiany": [["<plik>", "<kotwica: tekst HEAD, który stoi w pliku raz>", "<zamiana>"]]}]
~~~
## Sprawdzone
- <co sprawdzone i z jakim wynikiem, 1–5 punktów>
```

Postać bloku `### Mutacja W<n> r<k>` i punktu `## Sprawdzone` zaczętego od `Korzeń ` podaje [`korzen.md`](korzen.md).
`PASS` bez znalezisk ma tylko linie `WERDYKT: PASS <pełny SHA HEAD>`, `Znaleziska: 0 (Ważne 0, Drobne 0)`, bloki `### Mutacja` i `## Sprawdzone`.
Treść czyta renderer GitHuba, więc pole albo nagłówek liczy się tylko poza blokiem kodu: wynik, który cytuje linię `Korzeń:`, `Gdzie:` albo `### W…`, ujmij w blok ``` albo ~~~.
Dowód dłuższy niż 5 linii albo z linią ponad 300 znaków zapisz w pliku obok werdyktu i podaj w Dowodzie jego ścieżkę.
Merge liczy `PASS` jako zgodę tylko w postaci, którą sprawdza `tools/scal_pr.py <PR> --werdykt <plik>`, także gdy ktoś opublikował go inaczej, więc werdykt publikuj tylko tym poleceniem.
