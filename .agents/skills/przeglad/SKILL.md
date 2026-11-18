---
name: przeglad
description: Przegląd PR - co jest porażką, korzeń i szczebel, dowody, postać werdyktu PASS albo FAIL, kolejne rundy. Użyj jako recenzent przed werdyktem i jako autor przed zleceniem przeglądu.
---

# Przegląd PR

Oba tryby, autora i recenzenta, czytają wspólne reguły przeglądu, a różnią się tylko krokami końcowymi na dole.
`PASS` mówi też, że skille `verify-*` z linii `SKILLE VERIFY` przeszły na tym SHA (gotowość w `tools/scal_pr.py --help`).
Zlecenie przeglądu i brief koordynatora dodają tylko cel i punkty do sprawdzenia, a co jest Ważne, jakie dowody i jak opublikować werdykt, ustala ten skill.
Punkt do sprawdzenia może być tezą koordynatora („sprawdź, czy X nie daje wycieku”), bo Ważne z tezy stoi na tym samym powtarzalnym dowodzie co każde inne, więc werdykt nie oddziela znalezisk z tez od własnych (#950).

## Co jest porażką

Ważne znalezisko to defekt zachowania z dowodem, który da się powtórzyć: polecenie, jego wynik i plik:linia.
Tylko Ważne daje `FAIL`.
W tym repo Ważne były zwykle:

- mechanizm (reguła, narzędzie, krok skilla albo opcja issue `decyzja-maksa`), w którym krok powtarzany przy każdym wpisie, merge'u, wyjątku albo biegu czeka na zgodę albo czynność Maksa, choć nie należy do rodzajów decyzji Maksa z [`issue-tracker.md`](../../../docs/agents/issue-tracker.md), „Decisions for Maks”, i to samo sprawdzi reguła, recenzent albo narzędzie (#2008; `ZGODA KORZEŃ` zdjęta w [ADR 0036](../../../docs/adr/0036-chwast-to-regula.md), `ZGODA SZOPA` w #1622, opcja A #1888), oraz issue `decyzja-maksa` z decyzją spoza tych rodzajów;
- issue `decyzja-maksa`, którego pytanie stoi na pojęciu, próbie albo liczbie bez definicji w treści i bez linku do ADR, PR albo issue, bo jego źródłem są notatki biegu albo pamięć agenta (#1784, [`issue-tracker.md`](../../../docs/agents/issue-tracker.md), „Decisions for Maks”);
- test, który przestał sprawdzać to, co sprawdzał (pokrycie zgubione przy refaktorze, asercja na tekst zamiast na zachowanie);
- próbka testu, która nie może paść na złej implementacji nazwanej w docstringu testu, bo w świecie próbki nie ma przypadku z obietnicy (plik „bez odczytu”, którego świat próbki nie ma; separator, który w tekście JSON staje się ucieczką), a dowodem jest ta zła implementacja, z którą test przechodzi; nocne mutacje jej nie złapią, bo PR z samymi testami nie dostaje mutanta (#2031, [ADR 0036](../../../docs/adr/0036-chwast-to-regula.md), klasa `brak-testu`; #1853, #1869, #1909);
- zachowanie widoczne tylko na Windows albo na najstarszym Pythonie z `requires-python` (brak `tzdata`, krok zegara `time.monotonic()` pod dawnym minimum 3.11, import, który pada tylko pod najstarszym Pythonem);
- stan, który jedna część przebiegu zakłada po innej (część podstawy skilla startująca od środka porządku);
- przypisanie albo zakres liczony od złej linii lub złego commitu (np. `git blame` pierwszej linii wielowierszowej instrukcji).
- zmiana wspólnego elementu okna Centrum (sekcja okna Ustawień, menu, toast, okno dialogowe), która wywraca funkcję drive `verify-centrum-rozliczen` inną niż ta, którą autor uruchomił (#1517: nowa sekcja wywróciła `okno-ustawien`, które wymienia każdą sekcję).
- linia wyniku dla człowieka przepisana z listy wyników cudzego narzędzia (skilla pstack, kroku CI) bez gałęzi, którą to narzędzie zgłasza obok wyniku, więc człowiek czytający tylko linię jej nie widzi (#1875: błąd produktu znaleziony w przebiegu utrzymania skilli kończył się linią `clean`);
- fikstura albo przykład testu narzędzia, które czyta prywatne dane (transkrypty Claude Code, baza T3, pliki taty), z tekstem, nazwą sesji albo katalogu przepisanymi z prawdziwych danych zamiast wymyślonych, bo repozytorium jest publiczne, a CI tych danych nie ma, więc nic przed pushem cytatu nie odróżni (#1914: wiadomości operatora w teście `tools/poprawki_operatora.py`);
- nowy plik w `PARSERS` w `tests/test_zapadki.py` bez powodu w opisie PR albo z powodem nieprawdziwym, czyli taki, że reguła ruff, ast-grep albo test zachowania jednak wystarczają (#1888);
- tłumienie reguły chwastu na dodanej linii (`# noqa`, `# ruff: noqa`, `# ast-grep-ignore`, także z powodem i terminem) albo jej zwolnienie poza prawem właściciela z [`CODING_STANDARDS.md`](../../../CODING_STANDARDS.md) (nowy wpis `per-file-ignores` albo `ignores:`, zawężone `files:`, usunięta reguła), dopóki nie odmawia go krok Required CI PR kroku ukryć ticketu #1676 (#1720, [ADR 0036](../../../docs/adr/0036-chwast-to-regula.md), reguła przejściowa).
- ADR albo spec zapisany po odpowiedziach taty albo Maksa, w którym reguła różna od słów źródła (szersza albo węższa) stoi jako jego słowa, bez podziału na cytat i nazwaną decyzję koordynatora, w którym „źródło o tym nie mówi” nie zostało sprawdzone z pytaniem, na które źródło odpowiadało, albo którego lista „Zmienia te zdania” pomija zdanie zmienianego ADR, bo powstała z pamięci, a nie z przejścia po każdym punkcie jego Decyzji (#2011: r1 poszerzył odpowiedź taty bez nazwania decyzji, r2 zawęził ją, pisząc, że tata o własnych zapisach nie mówi).
- ADR albo spec, w którym zdanie w dowolnej sekcji (Status, Kontekst, Decyzja, Odrzucone warianty) mówi, czego chce albo co powiedział tata albo Maks, a nie stoi przy nim cytat tej osoby ani nazwana decyzja, albo w którym wybrany wariant pytania stoi węziej lub szerzej niż w całości; recenzent przechodzi każde zdanie z „tata” i „Maks” i każdy punkt Decyzji i szuka przy nim cytatu źródła albo nazwanej decyzji (#2042: „Zwykły opis obok kodów” mieścił dwie decyzje Maksa jako słowa taty, odrzucony wariant mówił „tata woli” o wyborze Maksa, a wariant „pokaż rozpoznane kody” stał bez połowy).

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

## Korzeń i chwast

Każde Ważne z przeglądu i każdy czerwony `main` z prawdziwej zmiany (nie flaky test) kończy się wyrwaniem korzenia, a nie łatką pod `PASS` ([ADR 0031](../../../docs/adr/0031-korzen-po-fail-i-chwasty.md)).
Ta sama reguła obowiązuje przy poprawce operatora.

- **Korzeń** to to, co skłoniło agenta do błędu, a nie sam błąd: skopiowany najbliższy przykład, druga droga do tego samego, brak typu albo właściciela, instrukcja.
  Korzeń ma kod z zamkniętej listy [`korzenie.toml`](korzenie.toml), a każdy kod ma tam jedno zdanie i przykład PR.
  Kod korzenia to kategoria, więc jego powrót w innym PR niczego nie blokuje ([ADR 0036](../../../docs/adr/0036-chwast-to-regula.md)).
- **Chwast** to reguła detektora: reguła ast-grep, klucz `banned-api` ruff albo kontrakt import-linter, z komunikatem „użyj X” i próbkami.
  Prawdziwy powrót to odpalenie reguły na dodanej linii w Required CI, a ucieczka to wystąpienie idiomu po merge'u jego reguły, którego reguła nie złapała.
- **Szczebel** to poziom, na którym korzeń wyrwano, od najwyższego:
  - (a) usuń drugą drogę i stare przykłady, daj jednego właściciela;
  - (b) typ, z którym zła droga nie przechodzi mypy, albo reguła ruff (`banned-api` z `msg` „użyj X”);
  - (c) test zachowania, który łapie całą klasę, nie tylko ten przypadek;
  - (d) reguła deklaratywna gotowego narzędzia, czyli reguła ast-grep w `reguly-ast-grep/` na liniach dodanych albo na całym drzewie (warunki w [`CODING_STANDARDS.md`](../../../CODING_STANDARDS.md));
  - (e) nowy punkt z linkiem do PR, który go dopisuje, w sekcji „Co jest porażką” tego skilla.

  Reguła (d) stoi między (c) a (e), bo jest deterministyczna, a (e) to proza: (d) jest dozwolona tylko wtedy, gdy (a)–(c) nie działają, a (e) tylko wtedy, gdy (a)–(d) nie działają.
  Reguła struktury, której nie wyraża typ, zakaz ruff, kontrakt import-linter ani reguła ast-grep, dostaje test zachowania (c) albo punkt w „Co jest porażką” (e), a nie nowy matcher w Pythonie.
  To rozwinięcie decyzji Q7 i Q26 przez koordynatora (13.11.2026), do potwierdzenia przez Maksa.

  Zakaz ruff albo mypy z (b) nie zastępuje testu, który szuka nazwy w kodzie, dopóki dla tej reguły wolno `noqa` albo `type: ignore`, więc test usuń dopiero, gdy zamiennik łapie każdą formę, którą test łapał (#1371).

Reguły szczebla i dowodu:

- Autor wyrywa korzeń na najwyższym szczeblu, który działa, a przy każdym wyższym pisze jedno zdanie, czemu nie działa.
  Gdy recenzent pokaże działający wyższy szczebel, to Ważne.
  „Bez mechanizmu” nie jest szczeblem.
- Dowód wyrwania: mechanizm pada na pierwotnym błędzie (mutacja z `tools/mutacje.py` albo cofnięcie poprawki).
  Recenzent następnej rundy powtarza ten dowód i jedną sondą sprawdza siostrzaną formę błędu, której poprawka nie nazwała; forma, która przechodzi, to Ważne.
  Przy Ważnym z korzeniem R-PROZA-KOPIA regułę „Fix the class, not the instance” z `CODING_STANDARDS.md` autor stosuje do prozy: klasą jest każde zdanie diffu od merge-base na temat zdania z werdyktu, które przed kolejną rundą czyta z kodem (#2069: trzy `FAIL` za kolejne zdania o tym, skąd gospodarze biorą Ustawienia ze startu, `PASS` dopiero po przeczesaniu wszystkich).
- Autor może zakwestionować kod korzenia z powodem w odpowiedzi na werdykt, a rozstrzyga recenzent następnej rundy kodem w swoim werdykcie: punktem `Korzeń W<n> r<k>: R-KOD - zdanie` w `## Sprawdzone`, gdzie `r<k>` to `k`-ty werdykt PR.
  Rejestr korzeni i bramka korzenia biorą kod z ostatniego werdyktu, który dotyczy tego Ważnego.
- Autor opisuje wyrwanie każdego Ważnego w sekcji `## Korzeń` opisu PR według wzoru sekcji „Root section” skilla [`pr`](../pr/SKILL.md), a `tools/scal_pr.py` odmawia merge'a, dopóki sekcji czegoś brakuje.
  Większy korzeń (ponad `size:M`) idzie osobnym PR-em korzenia, który scala się najpierw (wzór w tej samej sekcji skilla `pr`).
  Rozmiaru wyrwania `tools/scal_pr.py` nie liczy, więc rozstrzyga go recenzent.
- Gdy żaden kod z listy nie pasuje, recenzent pisze `Korzeń: NOWY R-KOD - opis` z kodem, którego na liście nie ma, a nie najbliższy kod, bo zły kod zafałszowałby rejestr powtórzeń.
  Autor dopisuje ten kod do [`korzenie.toml`](korzenie.toml) w swoim PR, z jednym zdaniem i przykładem PR, a kolejne werdykty piszą go już bez `NOWY`.

Drugie wystąpienie idiomu ([ADR 0036](../../../docs/adr/0036-chwast-to-regula.md)):

- Pole `Idiom:` pisze recenzent, nie autor, w Ważnym po polu `Szczebel:`, w jednej z trzech postaci:
  - `Idiom: <id> jak #N W<n> r<k>`, gdy to drugie wystąpienie idiomu, który nie ma jeszcze reguły, a `<id>` to id reguły, którą PR ma dodać;
  - `Idiom: <id>`, gdy to ucieczka istniejącej reguły `<id>`;
  - `Idiom: bez reguły <klasa> jak #N W<n> r<k>`, gdy idiom nie dostaje reguły, a `<klasa>` spełnia swój warunek z tabeli punktu „Idiom bez reguły” ADR 0036.
- PR z Ważnym z polem `Idiom: <id>` albo `Idiom: <id> jak #N W<n> r<k>` scala się tylko wtedy, gdy na HEAD PR istnieje reguła o id `<id>` i gdy jej dowód przechodzi.
  Próbka `ZNANE_LUKI` nigdy nie zastępuje reguły; wolno ją dodać obok reguły, która łapie przypadek z `Gdzie`, dla formy siostrzanej, której mechanizm reguły nie wyrazi.
  Dowód to `tools/na_scalonych_pr.py --regula-id <id> --z-commita <HEAD PR>` z każdym przypadkiem tej reguły z historii jej pól `Idiom:`, a `tools/scal_pr.py` uruchamia go z kodu bazy przy merge'u; dziś umie tylko reguły ast-grep.
- Ważne z polem `Idiom: bez reguły <klasa>` nie zatrzymuje merge'a; to, co sprawdza recenzent następnej rundy (regułę albo dowód mutacji), podaje dla każdej klasy ta sama tabela ADR 0036.

## Dowody

Każde znalezisko ma plik:linia i dowód: polecenie z wynikiem, repro albo mutację z `tools/mutacje.py` (`NIEWYKRYTA` albo `WYKRYTA`).
Mutacja `REGRES` (`NIEWYKRYTA` na HEAD, a `WYKRYTA` na merge-base, który narzędzie sprawdza samo) oraz `ZAWIESZENIE` (test po mutacji skończony przez pytest-timeout) i `PRZEKROCZONY CZAS` (polecenie bez wyniku w `--limit-s` narzędzia) to Ważne; noc i skrypty mutacji skilli liczą `ZAWIESZENIE` jak wykrytą, bo pytest-timeout czerwieni test w CI, więc widzi je tylko przegląd; `PRZEKROCZONY CZAS` skrypty mutacji skilli liczą jak przeżytą, a noc zgłasza z dopiskiem `przekroczony czas testów, bez werdyktu`.
Gdy wynik mutacji może zależeć od sąsiadów w procesie pytest (blokada, wątek, stan modułu), uruchom ją z `--jak-ci <id runu>`: biegnie z plikami każdego zadania pytest tego runu CI PR, w którym stoją zmienione testy, w jednym workerze, więc odtwarza skład zadania z tego runu, ale nie jego podział na workery.
Recenzent refaktoru, czyli zmiany, która nie ma zmieniać zachowania procesów, uruchamia `.venv/bin/python tools/rownowaznosc.py --baza <merge-base>` i wkleja do werdyktu jego ostatnią linię.
Recenzent PR-u, który dodaje albo zmienia sprawdzenie (test struktury, regułę lintu, zadanie CI, narzędzie sprawdzające), uruchamia samo to sprawdzenie przez `tools/na_scalonych_pr.py --commit <SHA>` na jednym z commitów, które opis PR podaje jako złapane, i wkleja ostatnią linię wyniku.
Mutacje recenzenta biegną po kolei, z `PYTEST_XDIST_AUTO_NUM_WORKERS=1`, najwyżej kilkanaście.
Pełnych mutacji i pełnego CI recenzent nie uruchamia lokalnie, bo liczy je CI i noc (ADR 0021).

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
Idiom: <id> jak #N W<n> r<k> (albo Idiom: <id>, albo Idiom: bez reguły <brak-testu|stan-kroku|typ|test-klasy> jak #N W<n> r<k>; tylko gdy idiom się powtarza)
### D1. <luka jednym zdaniem>
Gdzie: <plik:linia>
## Sprawdzone
- <co sprawdzone i z jakim wynikiem, 1–5 punktów>
```

`PASS` bez znalezisk ma tylko linie `WERDYKT: PASS <pełny SHA HEAD>`, `Znaleziska: 0 (Ważne 0, Drobne 0)` i `## Sprawdzone`.
Punkt `## Sprawdzone`, który zaczyna się od `Korzeń `, to rozstrzygnięcie kodu Ważnego z wcześniejszej rundy (`- Korzeń W1 r1: R-KOD - zdanie`, sekcja „Korzeń i chwast”), a kod sprawdza się jak w polu `Korzeń:`.
Treść czyta renderer GitHuba, więc pole albo nagłówek liczy się tylko poza blokiem kodu: wynik, który cytuje linię `Korzeń:`, `Gdzie:` albo `### W…`, ujmij w blok ``` albo ~~~.
Dowód dłuższy niż 5 linii albo z linią ponad 300 znaków zapisz w pliku obok werdyktu i podaj w Dowodzie jego ścieżkę.
Merge liczy `PASS` jako zgodę tylko w postaci, którą sprawdza `tools/scal_pr.py <PR> --werdykt <plik>`, także gdy ktoś opublikował go inaczej, więc werdykt publikuj tylko tym poleceniem.

## Kolejne rundy

Runda po `FAIL` sprawdza diff od przejrzanego SHA do nowego HEAD i to, czy każde znalezisko poprzedniej rundy jest zamknięte.
Zamkniętych znalezisk nie powtarza.
Ważne poprzedniej rundy jest zamknięte, gdy korzeń wyrwano według sekcji „Korzeń i chwast”, z dowodem wyrwania i sondą formy siostrzanej.
Nowe znalezisko w kodzie, którego ta runda nie zmieniła, jest Ważne tylko wtedy, gdy to defekt zachowania z dowodem.
Po drugiej rundzie z `FAIL` na tej samej przesłance (ta sama granica albo reguła pada na kolejnym przypadku) kolejna runda zaczyna się od zmiany podejścia: ataku na przesłankę, granicy z mechanizmu albo podziału PR.
Po trzeciej rundzie z `FAIL` bez zmiany podejścia czwartej rundy nie ma: `tools/scal_pr.py` odmawia jej w `--przeglad`, w `--werdykt` i przy merge'u (limit rund, `tools/lib/limit_rund.py`), dopóki HEAD PR ma kod z pola `Gdzie` Ważnych tych trzech rund; zmianę podejścia narzędzie widzi tylko w kodzie, a komentarz PR licznika nie zeruje (#2010: cztery komentarze, osiem rund z `FAIL`).
Podejście zmienia się w tym samym PR, a nie w nowym, bo bramka korzenia i bramka idiomu czytają tylko werdykty własnego PR, więc nowy PR gubi Ważne rund poprzednika (#1990); część, której przegląd nie przyjął, usuwasz z PR, a jej Ważne dostają w `## Korzeń` szczebel (a) z usuniętym kodem.
Recenzent rundy po zmianie podejścia sprawdza najpierw, czy nowy kod to naprawdę inne podejście, a nie ta sama przesłanka w innych liniach; gdy nie, to Ważne.
Każdą rundę robi nowy recenzent, który nie pisał kodu, z linkiem do poprzednich werdyktów.
Werdykt dla SHA, który ma już werdykt w tym PR (linia `RUNDA` z `--przeglad` kończy się `czyli dla tego HEAD`), ma w `## Sprawdzone` punkt `Ponowny przegląd: <czemu kolejny przegląd tego SHA i punkty „Do sprawdzenia” ze zlecenia>`, więc ślad na PR mówi, skąd zmiana zgody bez zmiany kodu (#875 r3: `FAIL` po `PASS` po tezie koordynatora); bez niego `--werdykt` i merge odmawiają (`tools/lib/ponowny_przeglad.py`).

## Tryb autora: przed zleceniem przeglądu

Autor nie przegląda własnego diffu przed pushem i nie zleca przeglądu przed pushem, bo pomiar takiego przeglądu dał czas większy o 27% i koszt dwa razy większy bez zysku w trafności (ADR 0023).

1. Wypchnij gałąź i utwórz PR według skilla [`pr`](../pr/SKILL.md).
   Krok kończy się, gdy masz numer PR i pełny SHA HEAD.
2. Zleć przegląd zaraz po pushu, równolegle z CI, nowemu agentowi, który nie pisał kodu i nie zna Twojej rozmowy.
   Zlecenie ma tylko te linie, bez własnej oceny diffu i bez reguł, które ma ten skill:

   ```text
   Przegląd PR #<N> według skilla .agents/skills/przeglad/SKILL.md w trybie recenzenta.
   Katalog werdyktu: ~/.t3/notes/<bieg>/recenzje/<N>/
   Cel Maksa: <jedno zdanie>
   Do sprawdzenia: <punkty albo „nic ponad skill”>
   ```

   Krok kończy się, gdy recenzent oddaje ścieżkę pliku werdyktu i linię `WERDYKT OK`.
3. Po `FAIL` wyrwij korzeń każdego Ważnego według sekcji „Korzeń i chwast” i opisz go w sekcji `## Korzeń` opisu PR (wzór w skillu [`pr`](../pr/SKILL.md)), dla Ważnego z polem `Idiom: <id>` dodaj albo popraw regułę ast-grep o tym id z jej dowodem, a Drobne popraw albo zapisz z powodem w opisie PR, i zleć kolejną rundę według sekcji „Kolejne rundy”.
   Krok kończy się, gdy na HEAD PR jest `PASS` albo po trzeciej rundzie z `FAIL`, po której zmieniasz podejście w tym samym PR tak, że HEAD nie ma już kodu z pola `Gdzie` ich Ważnych (sekcja „Kolejne rundy”).

## Tryb recenzenta: werdykt na PR

Plik werdyktu leży w katalogu ze zlecenia, a bez niego w `~/.t3/notes/recenzje/<PR>/`.
Recenzent nie pisał kodu i pracuje we własnym odłączonym checkoucie HEAD PR (`git fetch origin pull/<PR>/head`, potem `git worktree add --detach <katalog> FETCH_HEAD` i `tools/setup_worktree.py` w nim), nie zmienia gałęzi PR, nie pushuje, nie scala i nie uruchamia subagentów.

1. Uruchom `.venv/bin/python tools/scal_pr.py <PR> --przeglad`.
   Krok kończy się, gdy masz SHA HEAD i merge-base; poprzedni werdykt znaczy, że to kolejna runda (sekcja „Kolejne rundy”).
   Gdy kończy się linią `PRZEGLĄD ODMOWA`, nie przeglądasz i nie piszesz werdyktu, tylko oddajesz wywołującemu tę linię, bo `--werdykt` odmówi z tej samej przyczyny.
2. Przejrzyj diff według sekcji „Co jest porażką” i „Dowody”, a skille z linii `SKILLE VERIFY` wykonaj według sekcji `What CI runs and what stays local` każdego z nich.
   Linia `CI` z kroku 1 mówi, czy polecenia z linii `LICZY CI` przeszły: przy `success` logów zadań CI nie przeszukuj, a przy `failure` czytaj tylko logi padłych zadań, które podaje.
   Każde potwierdzone znalezisko od razu dopisz do pliku `runda-<k>.md` w katalogu werdyktu blokiem szablonu z sekcji „Postać werdyktu”, żeby przerwany przegląd zostawił znaleziska.
   Ważne ma kod korzenia z [`korzenie.toml`](korzenie.toml) i szczebel z sekcji „Korzeń i chwast”, a gdy idiom się powtarza albo ucieka regule, pole `Idiom:` z tej sekcji.
   Krok kończy się, gdy przejrzałeś cały diff, a każde znalezisko jest w pliku, Ważne z korzeniem i szczeblem.
3. Dopisz na górę pliku dwie linie z sekcji „Postać werdyktu”, a na koniec `## Sprawdzone` z 1–5 punktami.
   Krok kończy się, gdy liczby w drugiej linii zgadzają się ze znaleziskami w pliku.
4. Opublikuj werdykt: `.venv/bin/python tools/scal_pr.py <PR> --werdykt <plik>`.
   Gdy odmawia, popraw plik według jego komunikatu i uruchom je ponownie.
   Sądzi kodem `origin/<baza PR>`, jak merge, a nie kodem Twojego checkoutu HEAD PR (linia `SĘDZIA`).
   Gdy HEAD PR zmienił się w trakcie, przejrzyj diff od przejrzanego SHA do nowego HEAD, zanim zmienisz SHA w pliku.
   Krok kończy się linią `WERDYKT OK` z adresem komentarza: oddaj wywołującemu ścieżkę pliku i tę linię.
