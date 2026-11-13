---
name: przeglad
description: Przegląd PR w tym repozytorium, wspólny dla autora i recenzenta - co jest porażką (Ważne, Drobne), jakie dowody, postać werdyktu i kolejne rundy. Użyj jako niezależny recenzent PR, zanim napiszesz i opublikujesz werdykt PASS albo FAIL (tryb recenzenta), i jako autor, zanim zlecisz przegląd PR (tryb autora).
---

# Przegląd PR

Ten skill ma wspólne reguły przeglądu i dwa tryby, które różnią się tylko krokami końcowymi: tryb autora, który czyta reguły, zanim zleci przegląd PR, i tryb recenzenta, który publikuje werdykt na PR.
`PASS` mówi też, że skille `verify-*` z linii `SKILLE VERIFY` przeszły na tym SHA (gotowość w `tools/scal_pr.py --help`).
Zlecenie przeglądu i brief koordynatora dodają tylko cel i punkty do sprawdzenia, a co jest Ważne, jakie dowody i jak opublikować werdykt, ustala ten skill.

## Co jest porażką

Ważne znalezisko to defekt zachowania z dowodem, który da się powtórzyć: polecenie, jego wynik i plik:linia.
Tylko Ważne daje `FAIL`.
W tym repo Ważne były zwykle:

- test, który przestał sprawdzać to, co sprawdzał (pokrycie zgubione przy refaktorze, asercja na tekst zamiast na zachowanie);
- zachowanie widoczne tylko na Windows albo na najstarszym Pythonie z `requires-python` (brak `tzdata`, krok zegara `time.monotonic()` pod dawnym minimum 3.11, import, który pada tylko pod najstarszym Pythonem);
- stan, który jedna część przebiegu zakłada po innej (część podstawy skilla startująca od środka porządku);
- przypisanie albo zakres liczony od złej linii lub złego commitu (np. `git blame` pierwszej linii wielowierszowej instrukcji).

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

Korzeń wyrwany na szczeblu (e) dopisuje tu nowy punkt z linkiem do PR, który go dopisuje, jako przykładem, a punkt czyta autor i recenzent (sekcja niżej).

## Korzeń i chwast

Każde Ważne z przeglądu i każdy czerwony `main` z prawdziwej zmiany (nie flaky test) kończy się wyrwaniem korzenia, a nie łatką pod `PASS` ([ADR 0031](../../../docs/adr/0031-korzen-po-fail-i-chwasty.md)).
Ta sama reguła obowiązuje przy poprawce operatora.

- **Korzeń** to to, co skłoniło agenta do błędu, a nie sam błąd: skopiowany najbliższy przykład, druga droga do tego samego, brak typu albo właściciela, instrukcja.
  Korzeń ma kod z zamkniętej listy [`korzenie.toml`](korzenie.toml), a każdy kod ma tam jedno zdanie i przykład PR.
- **Chwast** to korzeń, który dał Ważne w co najmniej 2 różnych PR-ach.
  Powrót korzenia w innym PR to porażka i zadanie.
- **Szczebel** to poziom, na którym korzeń wyrwano, od najwyższego:
  - (a) usuń drugą drogę i stare przykłady, daj jednego właściciela;
  - (b) typ, z którym zła droga nie przechodzi mypy, albo reguła ruff (`banned-api` z `msg` „użyj X”);
  - (c) test zachowania, który łapie całą klasę, nie tylko ten przypadek;
  - (d) zapadka w `tests/test_zapadki.py`, która pada tylko na dodanych liniach (warunki w [`CODING_STANDARDS.md`](../../../CODING_STANDARDS.md));
  - (e) nowy punkt z linkiem do PR, który go dopisuje, w sekcji „Co jest porażką” tego skilla.

  Zapadka (d) stoi między (c) a (e), bo jest deterministyczna, a (e) to proza: (d) jest dozwolona tylko wtedy, gdy (a)–(c) nie działają, a (e) tylko wtedy, gdy (a)–(d) nie działają.
  Przy (d) i przy (e) autor pisze jedno zdanie, czemu wyżej się nie da.
  To rozwinięcie decyzji Q7 i Q26 przez koordynatora (13.11.2026), do potwierdzenia przez Maksa.

  Zakaz ruff albo mypy z (b) nie zastępuje testu, który szuka nazwy w kodzie, dopóki dla tej reguły wolno `noqa` albo `type: ignore`, więc test usuń dopiero, gdy zamiennik łapie każdą formę, którą test łapał (#1371).

Reguły szczebla i dowodu:

- Autor wyrywa korzeń na najwyższym szczeblu, który działa, a przy każdym wyższym pisze jedno zdanie, czemu nie działa.
  Gdy recenzent pokaże działający wyższy szczebel, to Ważne.
  „Bez mechanizmu” nie jest szczeblem.
- Dowód wyrwania: mechanizm pada na pierwotnym błędzie (mutacja z `tools/mutacje.py` albo cofnięcie poprawki).
  Recenzent następnej rundy powtarza ten dowód i jedną sondą sprawdza siostrzaną formę błędu, której poprawka nie nazwała; forma, która przechodzi, to Ważne.
- Korzeń, który wraca po wcześniejszym wyrwaniu, wyrywa się szczebel wyżej niż poprzednio.
  Gdy wyższego nie ma, także po szczeblu (e), decyduje Maks.
- Autor może zakwestionować kod korzenia z powodem w odpowiedzi na werdykt, a rozstrzyga recenzent następnej rundy kodem w swoim werdykcie: punktem `Korzeń W<n> r<k>: R-KOD - zdanie` w `## Sprawdzone`, gdzie `r<k>` to `k`-ty werdykt PR.
  Rejestr korzeni i bramka korzenia biorą kod z ostatniego werdyktu, który dotyczy tego Ważnego.
- Autor opisuje wyrwanie każdego Ważnego w sekcji `## Korzeń` opisu PR według wzoru sekcji „Root section” skilla [`pr`](../pr/SKILL.md), a `tools/scal_pr.py` odmawia merge'a, dopóki sekcji czegoś brakuje.
  Większy korzeń (ponad `size:M`) idzie osobnym PR-em korzenia z linią `Korzeń z #N: R-KOD`, który scala się najpierw.
  Rozmiaru wyrwania `tools/scal_pr.py` nie liczy, więc recenzent rozstrzyga, czy wyrwanie mieści się w PR (do `size:M`), czy należy do PR korzenia.
- Gdy żaden kod z listy nie pasuje, recenzent pisze `Korzeń: NOWY R-KOD - opis` z kodem, którego na liście nie ma, a nie najbliższy kod, bo zły kod zafałszowałby rejestr powtórzeń.
  `tools/scal_pr.py --werdykt` przyjmuje `NOWY` tylko z kodem w postaci kodów listy, którego nie ma na liście HEAD PR, i z niepustym opisem.
  Autor dopisuje ten kod do [`korzenie.toml`](korzenie.toml) w swoim PR, z jednym zdaniem i przykładem PR, a kolejne werdykty piszą go już bez `NOWY`.
  NOWY kod musi być na liście przed merge'em PR, a bez niego `tools/scal_pr.py` odmawia merge'a.

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
### D1. <luka jednym zdaniem>
Gdzie: <plik:linia>
## Sprawdzone
- <co sprawdzone i z jakim wynikiem, 1–5 punktów>
```

Pierwsza linia to `WERDYKT: PASS <pełny SHA HEAD>` albo `WERDYKT: FAIL <pełny SHA HEAD>`, a druga `Znaleziska: N (Ważne a, Drobne b)`.
Ważne (`### W1.`, `### W2.`) stoją przed Drobnymi (`### D1.`), każde z polami w kolejności szablonu.
`PASS` bez znalezisk ma tylko dwie pierwsze linie i `## Sprawdzone`.
Punkt `## Sprawdzone`, który zaczyna się od `Korzeń `, to rozstrzygnięcie kodu Ważnego z wcześniejszej rundy (`- Korzeń W1 r1: R-KOD - zdanie`, sekcja „Korzeń i chwast”), a kod sprawdza się jak w polu `Korzeń:`.
Treść czyta renderer GitHuba, więc pole albo nagłówek liczy się tylko poza blokiem kodu: wynik, który cytuje linię `Korzeń:`, `Gdzie:` albo `### W…`, ujmij w blok ``` albo ~~~.
Dowód dłuższy niż 5 linii albo z linią ponad 300 znaków zapisz w pliku obok werdyktu i podaj w Dowodzie jego ścieżkę.
`tools/scal_pr.py <PR> --werdykt <plik>` sprawdza tę postać przed publikacją i odmawia z przyczynami i wzorem, a merge liczy `PASS` jako zgodę tylko w tej samej postaci, także gdy ktoś opublikował go inaczej, więc werdykt publikuj tylko tym poleceniem.
W PR, którego najstarszy werdykt powstał przed wdrożeniem szablonu (merge ADR 0031 do bazy PR), publikacja i merge sprawdzają tylko dwie pierwsze linie (ADR 0031, decyzja Q20).

## Kolejne rundy

Runda po `FAIL` sprawdza diff od przejrzanego SHA do nowego HEAD i to, czy każde znalezisko poprzedniej rundy jest zamknięte.
Zamkniętych znalezisk nie powtarza.
Ważne poprzedniej rundy jest zamknięte, gdy korzeń wyrwano według sekcji „Korzeń i chwast”, z dowodem wyrwania i sondą formy siostrzanej.
Nowe znalezisko w kodzie, którego ta runda nie zmieniła, jest Ważne tylko wtedy, gdy to defekt zachowania z dowodem.
Po trzeciej rundzie z `FAIL` koordynator nie zleca czwartej, tylko zmienia podejście albo dzieli PR.
Każdą rundę robi nowy recenzent, który nie pisał kodu, z linkiem do poprzednich werdyktów.

## Tryb autora: przed zleceniem przeglądu

Autor czyta wspólne reguły wyżej, zanim zleci przegląd PR, żeby wiedzieć, co recenzent liczy jako porażkę i jakiego dowodu szuka.
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
3. Po `FAIL` wyrwij korzeń każdego Ważnego według sekcji „Korzeń i chwast” i opisz go w sekcji `## Korzeń` opisu PR (wzór w skillu [`pr`](../pr/SKILL.md)), a Drobne popraw albo zapisz z powodem w opisie PR, i zleć kolejną rundę według sekcji „Kolejne rundy”.
   Krok kończy się, gdy na HEAD PR jest `PASS` albo po trzeciej rundzie z `FAIL`, po której zmieniasz podejście albo dzielisz PR.

## Tryb recenzenta: werdykt na PR

Niezależny recenzent, który nie pisał kodu, przegląda HEAD PR i publikuje werdykt przez `tools/scal_pr.py`.
Kto zleca przegląd, podaje numer PR i katalog biegu, w którym leży plik werdyktu (`~/.t3/notes/<bieg>/recenzje/<PR>/`), a bez biegu plik leży w `~/.t3/notes/recenzje/<PR>/`.
Recenzent pracuje we własnym odłączonym checkoucie HEAD PR (`git fetch origin pull/<PR>/head`, potem `git worktree add --detach <katalog> FETCH_HEAD` i `tools/setup_worktree.py` w nim), nie zmienia gałęzi PR, nie pushuje, nie scala i nie uruchamia subagentów.

1. Uruchom `.venv/bin/python tools/scal_pr.py <PR> --przeglad`.
   Drukuje pełny SHA HEAD, merge-base z bazą, `git diff --stat`, zmienione pliki, wynik `tools/skille_dla_zmiany.py` dla HEAD PR, stan `Required CI status` na HEAD (linia `CI`) i poprzednie werdykty z ich SHA i dwiema pierwszymi liniami.
   Krok kończy się, gdy masz SHA HEAD i merge-base; poprzedni werdykt znaczy, że to kolejna runda (sekcja „Kolejne rundy”).
2. Przejrzyj diff według sekcji „Co jest porażką” i „Dowody”, a skille z linii `SKILLE VERIFY` wykonaj według sekcji `What CI runs and what stays local` każdego z nich.
   Linia `CI` z kroku 1 mówi, czy polecenia z linii `LICZY CI` przeszły: przy `success` logów zadań CI nie przeszukuj, a przy `failure` czytaj tylko logi padłych zadań, które podaje.
   Każde potwierdzone znalezisko od razu dopisz do pliku `runda-<k>.md` w katalogu werdyktu blokiem szablonu z sekcji „Postać werdyktu”, żeby przerwany przegląd zostawił znaleziska.
   Ważne ma kod korzenia z [`korzenie.toml`](korzenie.toml) i szczebel z sekcji „Korzeń i chwast”.
   Krok kończy się, gdy przejrzałeś cały diff, a każde znalezisko jest w pliku, Ważne z korzeniem i szczeblem.
3. Dopisz na górę pliku dwie linie z sekcji „Postać werdyktu”, a na koniec `## Sprawdzone` z 1–5 punktami.
   Krok kończy się, gdy liczby w drugiej linii zgadzają się ze znaleziskami w pliku.
4. Opublikuj werdykt: `.venv/bin/python tools/scal_pr.py <PR> --werdykt <plik>`.
   Narzędzie sprawdza obie linie, SHA HEAD i szablon, a gdy odmawia, popraw plik według jego komunikatu i wzoru i uruchom je ponownie.
   Gdy HEAD PR zmienił się w trakcie, przejrzyj diff od przejrzanego SHA do nowego HEAD, zanim zmienisz SHA w pliku.
   Gdy kod Ważnego ma wystąpienie w innym PR, narzędzie zakłada issue „Chwast: R-KOD” albo dopisuje wiersz do otwartego i podaje to w linii `WERDYKT OK` po `| CHWAST`.
   Krok kończy się linią `WERDYKT OK` z adresem komentarza: oddaj wywołującemu ścieżkę pliku i tę linię.
