---
name: przeglad
description: Przegląd PR w tym repozytorium, wspólny dla autora i recenzenta - co jest porażką (Ważne, Drobne), jakie dowody, postać werdyktu i kolejne rundy. Użyj jako niezależny recenzent PR, zanim napiszesz i opublikujesz werdykt PASS albo FAIL (tryb recenzenta), i jako autor, zanim zlecisz przegląd PR (tryb autora).
---

# Przegląd PR

Ten skill ma wspólne reguły przeglądu i dwa tryby, które różnią się tylko krokami końcowymi: tryb autora, który czyta reguły, zanim zleci przegląd PR, i tryb recenzenta, który publikuje werdykt na PR.
`PASS` mówi też, że skille `verify-*` z linii `SKILLE VERIFY` przeszły na tym SHA (gotowość w [`AGENTS.md`](../../../AGENTS.md)).
Zlecenie przeglądu i brief koordynatora dodają tylko cel i punkty do sprawdzenia, a co jest Ważne, jakie dowody i jak opublikować werdykt, ustala ten skill.

## Co jest porażką

Ważne znalezisko to defekt zachowania z dowodem, który da się powtórzyć: polecenie, jego wynik i plik:linia.
Tylko Ważne daje `FAIL`.
W tym repo Ważne były zwykle:

- test, który przestał sprawdzać to, co sprawdzał (pokrycie zgubione przy refaktorze, asercja na tekst zamiast na zachowanie);
- zachowanie widoczne tylko na Windows albo na Pythonie 3.11 (brak `tzdata`, krok zegara `time.monotonic()`, import, który pada tylko pod 3.11);
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

## Dowody

Każde znalezisko ma plik:linia i dowód: polecenie z wynikiem, repro albo mutację z `tools/mutacje.py` (`NIEWYKRYTA` albo `WYKRYTA`).
Mutacja `REGRES` (`NIEWYKRYTA` na HEAD, a `WYKRYTA` na merge-base, który narzędzie sprawdza samo) oraz `ZAWIESZENIE` (test po mutacji skończony przez pytest-timeout) i `PRZEKROCZONY CZAS` (polecenie bez wyniku w `--limit-s` narzędzia) to Ważne; noc i skrypty mutacji skilli liczą `ZAWIESZENIE` jak wykrytą, bo pytest-timeout czerwieni test w CI, więc widzi je tylko przegląd, a `PRZEKROCZONY CZAS` jak przeżytą.
Gdy wynik mutacji może zależeć od sąsiadów w procesie pytest (blokada, wątek, stan modułu), uruchom ją z `--jak-ci <id runu>`: biegnie z plikami każdego zadania pytest tego runu CI PR, w którym stoją zmienione testy, w jednym workerze, więc odtwarza skład zadania z tego runu, ale nie jego podział na workery.
Recenzent refaktoru, czyli zmiany, która nie ma zmieniać zachowania procesów, uruchamia `.venv/bin/python tools/rownowaznosc.py --baza <merge-base>` i wkleja do werdyktu jego ostatnią linię.
Recenzent PR-u, który dodaje albo zmienia sprawdzenie (test struktury, regułę lintu, zadanie CI, narzędzie sprawdzające), uruchamia samo to sprawdzenie przez `tools/na_scalonych_pr.py --commit <SHA>` na jednym z commitów, które opis PR podaje jako złapane, i wkleja ostatnią linię wyniku.
Mutacje recenzenta biegną po kolei, z `PYTEST_XDIST_AUTO_NUM_WORKERS=1`, najwyżej kilkanaście.
Pełnych mutacji i pełnego CI recenzent nie uruchamia lokalnie, bo liczy je CI i noc (ADR 0021).

## Postać werdyktu

Pierwsza linia to `WERDYKT: PASS <pełny SHA HEAD>` albo `WERDYKT: FAIL <pełny SHA HEAD>`.
Druga podaje liczbę znalezisk w postaci `Znaleziska: N (Ważne a, Drobne b)`.
Dalej znaleziska od najważniejszego, każde z oznaczeniem, plik:linia i dowodem, a na końcu krótko, co sprawdzone i z jakim wynikiem.
`tools/scal_pr.py <PR> --werdykt <plik>` sprawdza tę postać przed publikacją, a merge liczy `PASS` tylko w niej, także gdy ktoś opublikował go inaczej, więc werdykt publikuj tylko tym poleceniem.

## Kolejne rundy

Runda po `FAIL` sprawdza diff od przejrzanego SHA do nowego HEAD i to, czy każde znalezisko poprzedniej rundy jest zamknięte.
Zamkniętych znalezisk nie powtarza.
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
3. Po `FAIL` popraw każde Ważne, a Drobne popraw albo zapisz z powodem w opisie PR, i zleć kolejną rundę według sekcji „Kolejne rundy”.
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
   Każde potwierdzone znalezisko z oznaczeniem, plik:linia i dowodem od razu dopisz do pliku `runda-<k>.md` w katalogu werdyktu, żeby przerwany przegląd zostawił znaleziska.
   Krok kończy się, gdy przejrzałeś cały diff, a każde znalezisko jest w pliku.
3. Dopisz na górę pliku dwie linie z sekcji „Postać werdyktu”, a na koniec krótko, co sprawdzone i z jakim wynikiem.
   Krok kończy się, gdy liczby w drugiej linii zgadzają się ze znaleziskami w pliku.
4. Opublikuj werdykt: `.venv/bin/python tools/scal_pr.py <PR> --werdykt <plik>`.
   Narzędzie sprawdza obie linie i SHA HEAD, a gdy odmawia, popraw plik według jego komunikatu i uruchom je ponownie.
   Gdy HEAD PR zmienił się w trakcie, przejrzyj diff od przejrzanego SHA do nowego HEAD, zanim zmienisz SHA w pliku.
   Krok kończy się linią `WERDYKT OK` z adresem komentarza: oddaj wywołującemu ścieżkę pliku i tę linię.
