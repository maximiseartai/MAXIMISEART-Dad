# ADR 0020: CI w poziomach

## Status

Zaakceptowana (decyzje Maksa z 26.10).
Część o Change mutations na PR (poziom 2) zastępuje [ADR 0021](0021-mutacje-noca.md): mutacje biegną nocą na `main`, a przeżyte trafiają do issue PR-u.
ADR 0021 zastępuje też zdanie poziomu 2, że skrypty mutacji skilla biegną na PR, gdy zmienił się folder skilla: na PR biegną same podstawy `ci:` (#566), a skrypty pełne CI `main` i noc.
Od 13.11 (Z1, zgoda Maksa) ADR 0021 zabiera skrypty mutacji skilli także z pełnego CI `main` (poziom 3): biegną tylko nocą.
Zdanie poziomu 3, że Change mutations na `main` nie biegną, też przestało obowiązywać: biegną nocą na `main` (#564).
Opisuje stan docelowy, który wchodził krokami, jeden PR na krok; wszystkie kroki weszły 26.10 (#541, #542, #551, #552, #553, #554), więc Kontekst opisuje CI sprzed tego ADR.
Od #540 (26.10) repozytorium jest w organizacji GitHuba `maximiseartai`, więc odpada powód „wymagają organizacji GitHuba zamiast konta osobistego” przy odrzuconych runnerach Blacksmith; pozostałe powody zostają.
Od 13.11 (decyzja Maksa) tor Windows 3.13 zastępuje Windows 3.11 na PR i na `main`: tata ma na laptopie Pythona 3.13.15 ([komputer taty](../agents/komputer-taty.md)), a dolnej granicy 3.11 nie ma komputer, na którym narzędzie działa, więc `requires-python` rośnie do 3.13. Windows 3.14 zostaje na `main` jako ostrzeżenie przed aktualizacją Pythona, a liczba torów i zadań się nie zmienia.
Opiera się na [ADR 0014](0014-tata-dostaje-tylko-wydania.md), według którego tata dostaje tylko Wydanie z commitu `main` z zielonym `Required CI status`.
Zmieniona 13.11 (Z2, zgoda Maksa): pełne CI `main` nie uruchamia już toru Windows 3.14, więc zdanie wyżej, że Windows 3.14 zostaje na `main`, przestało obowiązywać.
E2E i straż czasu, które biegły na nim, biegną na Windows 3.13, Pythonie taty, a Pythona 3.14 dalej testuje tor Linux; tor Mutation checks na Windows 3.14 się nie zmienia.
Bramka PR też się nie zmienia, bo Windows 3.14 nigdy na niej nie biegł (poziom 2).
W runach pushu do `main` od 2.11 do 12.11 (379 runów, pomiar bazy hillclimbu CI) tor Windows 3.14 miał 654 zadania i 149 runner-godzin, a 23 jego zadania padły; 16 runów było czerwonych tylko przez niego, każdy przez jedno zadanie, a tor wracał do zieleni najpóźniej w drugim kolejnym runie `main`.
Defekt tylko z Windows i Pythonem 3.14 CI pokaże dopiero wtedy, gdy tata przejdzie na 3.14, a z nim tor Windows i `requires-python`.

## Kontekst

Przed tym ADR każdy PR uruchamia prawie pełne CI, czyli wszystkie pliki testów na trzech torach (Windows 3.11, Windows 3.14, Linux 3.14), E2E, podstawy i skrypty mutacji skilli `verify-*` oraz Change mutations bez limitu.
Każda poprawka jakości dokładała pracę do każdego PR (#406 Change mutations, #449 podstawy skilli), a nic nie liczyło jej kosztu.
Mediana czasu do werdyktu PR wzrosła z 4,3 min przed 21.10 do 26,6 min 26.10 (p90 39,7 min).
Od 25.10 15:00 do 26.10 42% tego czasu to była kolejka, bo konto ma limit 20 zadań naraz, a jeden run PR zajmował 14–19 zadań.

Wartość ciężkich zadań do 26.10 wyglądała tak:

- Change mutations w 2,5 dnia od wprowadzenia zużyło 113 runner-godzin i nie złapało żadnego defektu produktu, którego nie złapał pytest w tym samym runie; dało 35 luk w testach.
- Mutation checks jako osobne zadanie w 5 dni zużyło 222 runner-godziny, złapało 1 unikalny defekt (#438), a 88% jego porażek to flaky testy, infrastruktura albo błąd samego sprawdzenia.
- Tor Windows 3.11 w 28 dniach sam złapał 2 defekty importu na Pythonie 3.11 (#282, #285).

## Decyzja

Zakres sprawdzeń na PR zależy od zmiany i od tego, co ta zmiana może zepsuć.
Pełny zestaw biegnie po merge'u na `main`.
CI ma cztery poziomy:

1. **Lokalnie.** `tools/szybko.py` przed pushem.
2. **Bramka PR.** `Required CI status` na PR, warunek gotowości z `tools/scal_pr.py --help`.
   Ruff, mypy i Frontend biegną zawsze, a E2E przy zmianie `src/`.
   pytest biegnie tylko na testach wybranych dla zmiany, na Windows 3.13 (Python taty i najstarszy z `requires-python`) i Linux 3.14.
   Zmiana `.github/workflows/**` wybiera wszystko.
   Podstawa skilla `verify-*` biegnie, gdy zmiana trafia w jego `pilnuje:`, a jego skrypty mutacji, gdy zmienił się folder skilla.
   Change mutations nie blokuje werdyktu CI. Biegnie po zadaniach bramki, jedna mutacja na zmienioną linię, a każdą przeżytą recenzent omawia w werdykcie.
   `tools/scal_pr.py` nie scala PR, którego `PASS` nie omawia przeżytych mutacji.
3. **Pełne CI `main`.** Zestaw, który przed tym ADR biegł na pushu do `main`: wszystkie testy na dwóch torach (od 13.11, Z2: Windows 3.13 i Linux 3.14), E2E i straż czasu na Windows 3.13 oraz podstawy `ci:` wszystkich skilli; skrypty mutacji skilli od 13.11 tylko nocą (ADR 0021).
   Change mutations mutuje zmienione linie PR, więc na `main` nie biegnie.
   Trwający run `main` się kończy, a nowy merge podmienia tylko run, który czeka.
   Czerwony `main` nie blokuje merge'ów.
   Zakłada automatyczne issue, naprawia go osobny PR, a winnego wśród kilku merge'ów wskazuje bisect.
4. **Wydanie.** Tylko commit `main` z zielonym pełnym CI (ADR 0014) i z zielonymi testami z kwarantanny (niżej).
   To jest granica bezpieczeństwa taty, więc `main` może być czerwony nawet cały dzień.

Jakość bramki to odsetek prawdziwych defektów, które łapie w PR, a nie ilość wykonanej pracy.
Mierzy ją backtest na czerwonych runach z prawdziwym defektem.
W backteście na 28 dniach do 26.10 bramka z torem Windows 3.11 złapałaby w PR 11 z 11 defektów produktu.

### Gdy defekt przejdzie przez bramkę

Najpierw poprawka w codebase albo środowisku agenta, tak żeby ta klasa błędu nie wróciła (architektura, typy, lint, test, a proza na końcu).
Do bramki trafia tylko to, co złapałoby ten defekt, z dowodem z backtestu, czyli test, krawędź wyboru testów albo glob `pilnuje:`.
Pełnego zestawu ani całego zadania CI do bramki się nie dokłada.
Test kształtu planu bramki dla dwóch wzorcowych PR-ów, małego tylko z testami i zmiany Centrum, ma limit liczby zadań i prognozy czasu; przekroczenie to decyzja Maksa.

### Niestabilne testy

Bramka ponawia raz tylko test, który padł.
Przejście po ponowieniu przechodzi, ale trafia do zapisu, z którego powstaje issue dla tego testu; dwa padnięcia to prawdziwa porażka.
Kwarantanna to wpis z numerem issue i datą wygaśnięcia najwyżej 7 dni od wpisania.
Test w kwarantannie dalej biegnie na `main`, ale nie czerwieni `Required CI status`.
Dlatego narzędzie Wydań sprawdza osobno, że na commicie Wydania testy z kwarantanny przeszły.
Maks zgodził się 26.10 na takie wpisy z góry, więc nie wymagają osobnej zgody z `AGENTS.md`; wpis bez issue, z dłuższym terminem albo wygasły czerwieni strażnika.

## Konsekwencje

- Defekt, który przejdzie przez bramkę, pokazuje dopiero `main`, po kilkudziesięciu minutach.
  Do taty nie trafi, bo Wydanie wymaga zielonego pełnego CI i zielonych testów z kwarantanny.
- Dwa PR-y zielone osobno mogą się zepsuć dopiero razem na `main` (2 razy w 28 dniach do 26.10).
  Issue czerwonego `main` rozpoznaje takie zderzenie; gdy zderzenia się powtarzają, wraca decyzja o merge queue.
  Od #959 (6.11) zderzeniem jest tylko czerwony `main`, którego każda nowa porażka to test, którego wejścia zmieniły oba PR-y (graf `tools/lib/wplyw_zmiany.py`), a zielony `main`, który przyszedł bez zmiany wejść tych testów, zdejmuje etykietę `zderzenie`.
  Na 6 issues `zderzenie` z 5–6.11 żadne nie było zderzeniem: pierwszy warunek odrzuca 4 z nich (flaky test jednej strony, padnięte Mutation checks), a drugi jeszcze 1, więc decyzję o merge queue wywołuje mniej fałszywych alarmów.
- Od 6.11 (#959) `tools/scal_pr.py` przed merge'em uruchamia na scalonym drzewie test scalenia: pliki testów w odległości najwyżej 1 w grafie wpływu zmiany i od zmiany PR, i od zmiany `main` od merge-base, gdy ich czas CI mieści się w limicie 180 s.
  Zamiast merge queue łapie tylko tanią część zderzeń: na 19 merge'ach z 6.11 biegł 4 razy po 4–8 s, a 8 razy go pominął z powodem w linii `SCAL OK`: 5 przecięć ponad limit (#994, #995, #998, #1002, #1007, od 437 s w CI, 93 s na Macu agenta) i 3 zmiany `tests/conftest.py` (#984, #1001, #1004); liczenie przecięcia dodało do merge'a najwyżej 1,6 s.
  Czerwony `main` nadal nie blokuje merge'ów: gdy test scalenia pada, te same pliki testów biegną jeszcze raz na samym `main`, a odmowę daje tylko test, który pada na scaleniu, a na samym `main` nie.
  Test, który pada już na samym `main`, linia `SCAL OK` wymienia, a merge przechodzi; drugi bieg kosztuje tylko po porażce.
  Decyzja o merge queue zostaje Maksa.
- Przy 100 PR dziennie limit 20 zadań jest zajęty przez 16–17 godzin na dobę i wydłuża bramkę.
  W symulacji tego kształtu (nieblokujące Change mutations, trwający run `main` się kończy) p50 to 19,3 min i p90 46,3 min przy 20 zadaniach naraz, a 6,3 i 11,0 min przy 40.
- Dalsze skracanie bramki to przyspieszanie samych testów, nie zdejmowanie ich z bramki.

## Odrzucone warianty

- Pełne CI na każdym PR, szybsze przez więcej równoległych zadań. Praca rośnie ze zmianą, a każde zadanie więcej to mniej slotów dla innych PR-ów.
- Anulowanie każdego starszego runu `main`. Przy częstych merge'ach pełny werdykt dostaje mało commitów, a Wydanie nie ma z czego wybierać.
- Merge queue od razu. Werdykt `PASS <SHA HEAD>` w `tools/scal_pr.py` dotyczy commitu PR, a kolejka testuje inny commit; zderzeń było za mało, żeby to uzasadnić.
- Runnery Blacksmith. Wymagają organizacji GitHuba zamiast konta osobistego, Windows mają w becie, a przy naszym ruchu kosztowałyby około 840–1 650 dolarów miesięcznie, wobec darmowych minut repo publicznego na runnerach GitHuba.
