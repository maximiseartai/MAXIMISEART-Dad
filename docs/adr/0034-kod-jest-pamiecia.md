# ADR 0034: Kod jest pamięcią

## Status

Zaakceptowana (decyzje Maksa ze specyfikacji #1597, 13.11.2026).
Zmieniona 14.11.2026 decyzją Maksa w #1622: „Maszyneria maleje” pokazuje etykieta zamiast zgody `ZGODA SZOPA`.
Zmieniona 14.11.2026 w #1611 (po trzech werdyktach FAIL PR #1680: dwóch za brakujące warianty i jednym za klasę spoza ręcznej tabeli klas): próbka znanej luki nosi nazwę klasy mechanizmu strażnika, a próbki to luki znane, nie pełna lista postaci ani klas (sekcja Decyzja, „Granica strażnika”).
Zmienia [ADR 0031](0031-korzen-po-fail-i-chwasty.md) w decyzjach o źródłach chwastu, szczeblu (d), PR korzenia, etykiecie `ready-for-agent` i pomiarze co poniedziałek.
Zmienia sekcję „Reguły i co ich pilnuje” w [`AGENTS.md`](../../AGENTS.md): granicę strażnika, wyjątek na linii i źródła korzenia, a dokłada zakaz pamięci agentów poza repo.
Zmienia zakres nocnych mutacji z [ADR 0021](0021-mutacje-noca.md).
Zmieniona przez [ADR 0036](0036-chwast-to-regula.md) (#1676) w decyzjach „Rejestr liczy zgody i obejścia”, „Autor wyrywa swój chwast”, „Kolejka” i „Ogrodnik” oraz w mierze odczytu 11.12.2026: chwast to reguła detektora zamiast issue „Chwast”; każda zmiana obowiązuje od merge'a jej wykonawcy z tabeli „Wdrożenie” w ADR 0036.

Każda reguła wchodzi ticketem specyfikacji #1597, który stoi przy niej w sekcji Decyzja.
Do merge'a tego ticketu obowiązuje dotychczasowe zdanie w `AGENTS.md`, [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md) i skillu [`przeglad`](../../.agents/skills/przeglad/SKILL.md), a ticket zmienia te pliki tak, żeby zdanie tego ADR stało się prawdziwe.

## Kontekst

Maks nie przegląda już PR-ów w tempie agentów, więc jakość ma wynikać ze środowiska, w którym agent pracuje.
Agent kopiuje najbliższy przykład i idzie najkrótszą drogą, która przechodzi sprawdzenia.
Ocena repo z 13.11.2026 w #1597 pokazała:

- 25 otwartych issues „Chwast” i żadnego zamkniętego, a 52% wystąpień korzeni to powtórzenia;
- 177 tłumień (106 `noqa`, 71 `type: ignore`), z czego 24 `noqa` bez powodu, i 34 wyjątki w linii od zakazów jednej drogi (`TID251`);
- 71 sprawdzeń struktury w 18 plikach testów, a najczęstszy korzeń to `R-MATCH-KOD` (22 Ważne w 12 PR-ach);
- 107 wpisów pamięci agentów na jednej maszynie, których inne maszyny nie widzą i których nic nie pilnuje;
- 70 928 linii narzędzi i skryptów skilli przy 49 417 w `src`, z 50 issues `czerwony-main` (2–13.11) tylko 4 z naprawą w `src`, a z 685 linii przeżytych mutacji 450 w `tools/`.

## Decyzja

Repo jest jedynym źródłem prawdy dla reguł i wiedzy, a GitHub tego repo dla stanu pracy (issues, PR-y, werdykty).
Każda decyzja niżej ma jedno zdanie decyzji, jedno zdanie powodu i ticket, który ją wprowadza.

### Strażnicy i wyjątki

- **Granica strażnika.** Znana postać, której strażnik nie łapie, jest próbką w teście strażnika oznaczoną jako znana luka i nazwaną klasą mechanizmu, który ją przepuszcza (np. „zna tylko nazwę z importu”), a nie zdaniem w docstringu, próbki są lukami znanymi, a nie pełną listą postaci ani klas, więc nowo znaleziona luka staje się nową próbką albo zamyka ją konstrukcja (typ, zakaz ruff, odmowa w biegu), a test pada, gdy strażnik zaczyna próbkę łapać.
  Powód: lista obejść w docstringu jest najbliższym przykładem do skopiowania i nic nie mówi, kiedy przestaje być prawdziwa, a ani lista wariantów, ani ręczna tabela klas z kodu strażnika się nie zamyka: PR #1680 dostał trzy werdykty FAIL, dwa za brakujące warianty i jeden za klasę spoza tabeli klas.
  Wchodzi w #1610 i #1611.
- **Szczebel (d).** Szczebel (d) drabiny z ADR 0031 to reguła deklaratywna w gotowym narzędziu (ast-grep) na dodanych liniach, a nowa zapadka na regexie linii jest zakazana.
  Powód: wzorzec na drzewie składni myli się rzadziej niż wzorzec na tekście linii, a ręczne matchery dały najczęstszy korzeń `R-MATCH-KOD`.
  Wchodzi w #1614 i #1615.
- **Nowa reguła struktury.** Nowa reguła struktury wchodzi tylko jako typ, reguła ruff, kontrakt import-linter albo reguła ast-grep, a bez takiej postaci dostaje test zachowania albo punkt w „Co jest porażką” skilla `przeglad`, nie matcher w Pythonie.
  Powód: granicę strażnika wyznacza wtedy mechanizm gotowego narzędzia, więc runda przeglądu nie szuka kolejnej postaci obejścia.
  Wchodzi w #1612, #1613 i #1615.
- **Prawo właściciela i wyjątek.** Stałe prawo modułu-właściciela do zakazanego API stoi jako zakres reguły w `per-file-ignores` konfiguracji ruff, a na linii stoi tylko wyjątek tymczasowy z powodem, datą wygaśnięcia i zgodą Maksa.
  Powód: prawo właściciela zapisane tłumieniem w linii wygląda jak wyjątek do skopiowania.
  Wchodzi w #1608.
- **Licznik tłumień.** Liczba `noqa` i `type: ignore` w każdym katalogu stoi w repo, a PR, który zmienia liczbę tłumień, zmienia też zapisaną liczbę, także w dół.
  Powód: każde nowe tłumienie ma być widać w diffie, a zapas po usuniętych nie może pozwolić dodać nowych po cichu.
  Wchodzi w #1609.

### Chwasty

- **Cztery źródła.** Chwast ma cztery źródła: werdykt przeglądu, czerwony `main` z prawdziwej zmiany, poprawkę Maksa w wątku i spis zapachów, w którym liczba zapachu na `main` rośnie dwa tygodnie z rzędu.
  Powód: wzorzec, który rośnie bez defektu zachowania, niczego dziś nie uruchamia, więc dostaje issue dopiero, gdy padnie na nim przegląd.
  Poprawka Maksa jest źródłem już dziś w `AGENTS.md` i skillu `przeglad`, a spis zapachów wchodzi w #1627.
- **Rejestr liczy zgody i obejścia.** Poniedziałkowy rejestr korzeni dokłada sześć liczb spisu zapachów oraz liczy komentarze `ZGODA KORZEŃ` i `ZGODA SZOPA`, merge'e poza `tools/scal_pr.py` i zgody napisane przez agentów.
  Powód: agenci i Maks piszą z jednego konta, więc te reguły są konwencją, której przestrzeganie pokazuje tylko liczba.
  Wchodzi w #1626 i #1627.
- **Autor wyrywa swój chwast.** PR, którego Ważne założyło albo uzupełniło issue „Chwast”, zamyka to issue linią „Korzeń z #N”, chyba że wyrwanie przekracza rozmiar M i idzie osobnym PR-em korzenia z tego samego wątku.
  Powód: chwast bez właściciela czeka, a autor ma kontekst, którego nie ma nikt inny.
  Wchodzi w #1619; bramkę z #1644 wycofuje #1683 do rozstrzygnięcia, co zamyka issue „Chwast”.
- **Czerwony `main` w wątku autora.** Issue `czerwony-main` trafia do wątku T3, którego merge zaczerwienił `main`.
  Powód: autor naprawia korzeń, póki ma kontekst, a czerwony `main` blokuje wszystkie wątki.
  Wchodzi w #1621.
- **Kolejka.** Etykietę `ready-for-agent` ma tylko chwast z czoła kolejki: najpierw `R-WYCIEK`, potem sprawdzenia napędu Centrum zależne od czasu i kopie tekstów okna w napędzie, potem reszta według godzin rund FAIL.
  Powód: `R-WYCIEK` dotyczy danych klientów taty, awaria napędu czerwieni `main` wszystkim wątkom, a chwast wzięty poza kolejnością zderza się z innymi PR-ami strażników w tych samych plikach.
  Wchodzi w #1620.
- **Ogrodnik.** Sierotę, czyli chwast bez żyjącego wątku autora, bierze ogrodnik (stałe zadanie T3) zaraz po zdarzeniu issue na GitHubie, gdy w toku są mniej niż dwa chwasty.
  Powód: chwasty nie czekają tydzień na pomiar, a dwa naraz to tyle, ile PR-y strażników zniosą bez zderzeń w tych samych plikach.
  Wchodzi w #1621.

### Kod jest pamięcią

- **Zakaz pamięci poza repo.** Agenci nie zapisują niczego do pamięci poza repo, a zakaz stoi w ustawieniach projektu w repo i wchodzi po rozbiórce dzisiejszych wpisów.
  Powód: pamięć jednej maszyny starzeje się, inne maszyny jej nie widzą, nic jej nie pilnuje i służy do usprawiedliwiania obejść.
  Wchodzi w #1603 i #1606.
- **Los wiedzy.** Lekcja o kodzie albo procesie idzie przez drabinę (a)–(e) tylko wtedy, gdy wróciła co najmniej dwa razy, fakt domeny idzie do [`GLOSSARY.md`](../../GLOSSARY.md) albo ADR, preferencja pracy w repo do strażnika albo linii `AGENTS.md`, a fakt prywatny albo o maszynie do pliku reguł użytkownika na tej maszynie, który pisze tylko Maks, albo do narzędzia, które ten stan wykrywa.
  Powód: każda wiedza ma wtedy miejsce, które ją sprawdza albo czyta, a lekcja jednorazowa i historia biegów tylko rozdymają prozę dla agentów.
  Wchodzi w #1603 i #1605.
- **Decyzje Maksa.** Otwarta decyzja dla Maksa jest issue z etykietą `decyzja-maksa` i szablonem bez wolnej prozy, a agenci mają stałą zgodę na zakładanie tylko takich issues, gdy sprawdzili, że decyzja nie jest już rozstrzygnięta.
  Powód: decyzja zapisana w pamięci agenta czeka na Maksa niewidoczna dla niego i dla innych maszyn.
  Wchodzi w #1604.
- **Notatki biegów.** Repo nie powołuje się na notatki biegów: dowód i decyzja, na których coś stoi, są w ADR, PR albo issue, a pliki werdyktów przeglądu mogą powstawać w notatkach, bo publikacja werdyktu przenosi je na GitHuba.
  Powód: notatki leżą na jednej maszynie i znikają, więc odsyłacz do nich nie jest dowodem dla nikogo innego.
  Wchodzi w #1607.
- **Stałe zadania T3.** Polecenie stałego zadania T3 to jedno zdanie wskazujące narzędzie albo skill w repo.
  Powód: zmiana procedury w repo zmienia wtedy to, co zadanie robi, bez drugiej kopii w poleceniu.
  Wchodzi w #1607.

### Komentarze i proza

- **Komentarze w `src`.** W `src` nie ma komentarzy `#` poza tłumieniami, a docstring nie niesie numerów PR, skrótów commitów ani list obejść.
  Powód: agent czytający kod bierze cudze uzasadnienie i historię za wzorzec.
  Wchodzi w #1614, #1616, #1617 i #1618.
- **Proza skilli.** Krok, który wykonuje skrypt, nie jest opisany prozą skilla, a `SKILL.md` mówi, kiedy skilla użyć, jakim poleceniem i jak czytać wynik.
  Powód: proza, która powtarza skrypt, rozjeżdża się z nim, a agent wierzy prozie.
  Wchodzi w #1628, #1629, #1630 i #1631.
- **ADR.** Nowy i zmieniany ADR zapisuje decyzję i jej powód, a działanie mechanizmu zostawia narzędziu i jego `--help`; starych ADR-ów nie przepisujemy.
  Powód: opis działania w ADR starzeje się przy każdej zmianie narzędzia, a `--help` zmienia się razem z kodem.
  Wchodzi tym ADR (#1602).

### Szopa

Szopa to warstwa procesu repo: narzędzia, skrypty skilli, strażnicy struktury, proza dla agentów i testy tych rzeczy.
Weryfikacja produktu to jej część, która wydaje wyrok o zachowaniu produktu, a maszyneria procesu to reszta.

- **Dwie szopy.** Jedna lista w repo przypisuje każdą jednostkę szopy do weryfikacji produktu albo do maszynerii procesu, a każda z nich ma osobny cel.
  Powód: wspólny cel karałby weryfikację, która łapie błędy produktu, tak samo jak kolejną bramkę.
  Wchodzi w #1622.
- **Maszyneria maleje.** PR, który dodaje więcej linii maszynerii procesu z jej testami, niż usuwa, dostaje etykietę informacyjną „powiększa maszynerię procesu”, która niczego nie blokuje.
  Powód: szopa ma więcej linii niż `src` i sama tworzy sobie pracę, skoro tylko 4 z 50 issues `czerwony-main` miały naprawę w `src`, więc recenzent i Maks mają widzieć każdy PR, który ją powiększa.
  Wchodzi w #1622.
- **Audyt szopy.** Każda jednostka szopy dostaje wyrok usunąć, scalić z bliźniakiem, zastąpić zmianą API albo typem, albo zostawić, „zostawić” wymaga bilansu złapań błędów produktu do własnych awarii, a Maks zatwierdza listę raz, zanim cokolwiek zniknie.
  Powód: jednostka, która częściej czerwieni `main` albo pada w przeglądzie, niż zatrzymuje błąd produktu, kosztuje więcej, niż daje.
  Wchodzi w #1623 i #1624.
- **Nocne mutacje.** Noc mutuje `src` oraz jednostki szopy, których fałszywe „OK” przepuszcza zły kod produktu, a pomiary, raporty, plan CI, sprzątanie, obsługa flaky testów i rejestr korzeni wychodzą z nocnych mutacji.
  Powód: przeżyta mutacja pomiaru albo raportu nie przepuszcza złego kodu do taty, a to tam leży większość zgłoszonych linii przeżytych mutacji.
  Wchodzi w #1625.

## Odrzucone warianty

- **Osobne konto dla agentów i blokady po stronie serwera.** Maks wyłączył je z zakresu 13.11.2026, więc zgody od konta z prawem `admin` zostają konwencją, którą liczy rejestr.
- **Zgoda `ZGODA SZOPA` na powiększenie maszynerii.** Maks odrzucił ją 14.11.2026 (#1622): pełny mechanizm zgody to kilkaset linii nowej maszynerii, która niczego nie blokuje, a trzy rundy przeglądu PR #1646 znalazły trzy drogi jego obejścia.
  Przeniesienie pliku między grupami recenzent ocenia z liczb obu grup, które licznik już drukuje.
- **Przeniesienie wszystkich sprawdzeń struktury do gotowych narzędzi.** Z 71 sprawdzeń gotowe narzędzie wyrazi 33, a bez utraty postaci tylko 17, więc reszta czeka na audyt szopy, zamiast tracić postacie, które dziś łapie.
- **Macierz „mutant × test” dla całego `src` przed cięciem testów produktu.** Szacunek to 405–1120 godzin runnera, więc cięcie zaczyna pilot na jednym pliku testów (#1635).

## Konsekwencje

- Recenzent sprawdza regułę według zdania w `AGENTS.md`, `CODING_STANDARDS.md` i skillu `przeglad`, a nie według tego ADR, dopóki ticket tej reguły nie jest scalony.
- Wyłącznik pamięci, budzenie ogrodnika i stałe zadania T3 nie mają szwu testowego w repo, więc sprawdza się je raz na żywo przy ich tickecie.
- Odczyt 11.12.2026 (#1636): udział powtórzonych korzeni poniżej 35% (próg z wyboru, nie z pomiaru) oraz mniej otwartych chwastów, tłumień i linii maszynerii procesu niż 13.11.
  Gdy odczyt nie pokaże poprawy, cofamy to, co dodał program #1597, zamiast dokładać kolejny mechanizm.
