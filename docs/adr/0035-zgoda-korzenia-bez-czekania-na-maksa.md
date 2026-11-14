# ADR 0035: Zgoda korzenia bez czekania na Maksa

## Status

Zaakceptowana (decyzja Maksa z 14.11.2026 w wątku koordynatora programu #1597, ticket #1676).
Zmienia [ADR 0031](0031-korzen-po-fail-i-chwasty.md) w decyzji Q11 (powrót korzenia i zgoda Maksa).
Wchodzi PR-em bramki korzenia z #1676; do jego merge'a obowiązuje dotychczasowe zdanie skilli [`przeglad`](../../.agents/skills/przeglad/SKILL.md) i [`pr`](../../.agents/skills/pr/SKILL.md), a ten PR zmienia je tak, żeby zdanie tego ADR stało się prawdziwe.

## Kontekst

Bramka korzenia (`tools/lib/bramka_korzenia.py`) w nocy 13/14.11.2026 zatrzymała pięć PR-ów z werdyktem `PASS` i zielonym CI (#1644, #1645, #1646, #1655, #1664), bo każdy czekał na linię `ZGODA KORZEŃ` od Maksa, a Maksa nie było.
Maks nie przegląda PR-ów w tempie agentów i chce listy zgód do przejrzenia po fakcie, a nie pytania przed każdym merge'em.
Trzy luki Q11:

- powrót kodu liczy się w całym repo, więc wyrwanie na (a) w jednym narzędziu czeka na Maksa przy każdym następnym wystąpieniu kodu w każdym wątku;
- po szczeblu niższym niż (a) narzędzie nie ma drogi zgody, choć ADR 0031 mówi „brak wyższego idzie do Maksa”, więc #1664 (`R-MATCH-KOD` po (c) w #1583) nie miał drogi do merge'a;
- zgodę daje tylko Maks przed merge'em.

Rejestr korzeni od wdrożenia szablonu (93 wystąpienia, 14.11.2026) ma 47 wystąpień z wcześniejszym wyrwaniem kodu w innym scalonym PR; 31 z nich czekało na zgodę Maksa po (a), w 20 PR-ach.

## Decyzja

- **Powrót w obszarze kodu.** Wcześniejsze wyrwanie kodu jest powrotem tylko wtedy, gdy wystąpienie leży w tym samym obszarze kodu co Ważne, które to wyrwanie wyrwało.
  Obszar wyznaczają ścieżki pola `Gdzie` Ważnego: plik w pakiecie `src/rozliczenia/<pakiet>/` ma obszar tego pakietu, plik wprost w `src/rozliczenia/` obszar `src/rozliczenia/`, a inny plik grupę (`produkt`, `weryfikacja`, `maszyneria`) z listy dwóch szop `tools/lib/szopa.toml` i jej reguły katalogu, tej samej, z której liczy workflow rozmiaru PR; plik bez grupy ma obszar swojego katalogu najwyższego poziomu, a plik w korzeniu repo obszar korzenia.
  Wystąpienie z kilkoma ścieżkami ma kilka obszarów i wraca, gdy jeden z nich jest wspólny; wystąpienie bez ścieżki (blok czerwonego `main`, `Gdzie` bez ścieżki repo) leży w każdym obszarze.
  Powód: wyrwanie w jednym obszarze (druga droga w narzędziu chwastów) nie zapobiega temu korzeniowi w innym (Centrum), a obszar z istniejącej listy i z pakietów nie wymaga nowej listy do utrzymania.
  Na rejestrze z 14.11.2026 zostaje 29 z 47 powrotów, 18 z 31 po (a) i 14 z 20 PR-ów ze zgodą.
- **Zgoda po niższym szczeblu.** Gdy kod wraca po wyrwaniu na szczeblu od (b) do (e), a blok nie wyrywa go wyżej, merge przechodzi z linią zgody tak samo jak po (a).
  Blok ma wtedy „Wyżej nie, bo:” z jedną linią na każdy wyższy szczebel, czego bramka już wymaga od każdego szczebla niższego niż (a), a recenzent następnej rundy potwierdza szczebel werdyktem `PASS`, bo działający wyższy szczebel to Ważne (Q2, Q7).
  Powód: ADR 0031 kieruje brak wyższego szczebla do decyzji, a bez drogi zgody taki PR mógł skończyć tylko zmianą reguły.
- **Zgoda koordynatora.** Zgodę na powrót zapisuje koordynator biegu po werdykcie `PASS` na HEAD PR komentarzem z linią `ZGODA KORZEŃ: R-KOD po PASS <pełny SHA HEAD>`, a zgoda Maksa to dalej linia `ZGODA KORZEŃ: R-KOD` bez dopisku.
  Zgoda koordynatora działa tylko dla HEAD, który podaje, więc nowy commit wymaga nowego `PASS` i nowej zgody; obie piszą konto z prawem `admin`, więc treść linii jest jedynym, co je odróżnia.
  Każda zgoda koordynatora trafia do poniedziałkowego rejestru korzeni jako pozycja do przejrzenia przez Maksa, z liczbą i listą linków (#1626).
  Powód: werdykt `PASS` niezależnego recenzenta już potwierdza szczebel, więc czekanie na Maksa zatrzymuje przyjętą pracę, a lista po fakcie zostawia mu przegląd w jego tempie.

## Odrzucone warianty

- **Obszar jako najbliższy katalog pliku.** Dzieli Centrum na `settings/`, `settings/migrations/`, `processes/`, a jedno wyrwanie zwykle obejmuje całe Centrum; różnica na rejestrze to tylko 2 powroty (27 zamiast 29).
- **Obszar jako jednostka listy dwóch szop.** Lista trzyma tylko wyjątki od reguły katalogu, więc większość plików nie ma jednostki.
- **Obszar z plików zmienionych przez PR.** PR wyrwania zmienia też testy i prozę w innych obszarach, więc obszar rósłby z każdym wyrwaniem.
- **Nowa ręczna lista obszarów.** Druga lista obok `tools/lib/szopa.toml`, której nic nie pilnuje.
- **Zgoda koordynatora bez SHA.** Przeżyłaby commit po `PASS`, którego żaden recenzent nie widział.
- **Bramka bez zgody, gdy jest `PASS`.** Rejestr nie miałby czego pokazać Maksowi, a powrót przeszedłby bez śladu.
- **Zgoda tylko od Maksa przed merge'em (stan sprzed tego ADR).** Zatrzymuje w nocy PR-y, które recenzent już przyjął.

## Konsekwencje

- Bramka dalej zatrzymuje powrót w tym samym obszarze bez szczebla wyżej, a odmowa podaje obie postacie linii zgody; zatrzymanie trwa do zgody koordynatora, nie do powrotu Maksa.
- Odmowy z innych powodów (brak sekcji, brak bloku, szczebel niższy niż (a) bez „Wyżej nie, bo:”, otwarty PR korzenia) zostają bez zmian.
- Chwast i miara powtórzeń (Q1) dalej liczą kod w całym repo: obszar zawęża tylko powrót, który bramka wymaga wyrwać wyżej.
- Ważne, którego `Gdzie` nie podaje ścieżki repo, wraca w każdym obszarze, więc recenzent podaje w `Gdzie` ścieżkę pliku.
- Zgodę Maksa od zgody koordynatora odróżnia tylko treść linii z jednego konta, więc to konwencja, której przestrzeganie pokazuje rejestr (ADR 0034).
