# ADR 0014: Tata dostaje tylko Wydania

## Status

Zaakceptowana (decyzja Maksa z 23.10, spec #313, ticket #315). Na niej
opiera się [ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md)
(Powiadomienie o nowej wersji z notką Wydania). Zmienia dwa zdania
[ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md):

- „Pobiera `main` z publicznego repozytorium bez logowania i przesuwa klon tylko
  do przodu”: Centrum pobiera `main` i tagi Wydań, a przesuwa klon tylko do
  przodu, na commit najnowszego Wydania. Lokalna gałąź klonu taty zostaje
  `main`.
- „Konfiguracja pamięta odpowiedź `main` przez 10 minut”: Aktualność narzędzia
  porównuje commit narzędzia z commitem najnowszego Wydania, z tą samą pamięcią.

Pozostałe zasady ADR 0009 (wszystko albo nic, dziennik „Aktualizacja w toku”,
opiekun ponownego startu, pliki taty, tylko po kliknięciu) zostają.

Tworzenie Wydania (#316) weszło w #326: `tools/wydanie.py` i skill `wydanie`.
Od #554 sprawdza też, że testy z kwarantanny przeszły na commicie Wydania
([ADR 0020](0020-ci-w-poziomach.md)).

## Kontekst

Centrum aktualizuje narzędzie z `main` po kliknięciu taty (ADR 0009). Na
`main` trafia 12-40 zmian dziennie, a ruleset `main` wymaga zielonego
`Required CI status` tylko na PR, bez aktualnej bazy. Z 40 runów CI na pushu
do `main` od 21.10 21:21 UTC do 23.10 rano 6 skończyło się porażką. Tata, który kliknie
`Zaktualizuj narzędzie` w takim oknie, dostaje commit, którego CI nie
przeszło. Okres rozliczeń taty jest tygodniowy, więc nie potrzebuje każdej
zmiany zaraz po merge'u.

## Decyzja

Tata dostaje tylko Wydanie: tag `vMAJOR.MINOR.PATCH` (pierwsze to `v0.1.0`) na
commicie `main` z zielonym CI. Wydanie powstaje tylko na prośbę Maksa. To
moment na `verify-*` na prawdziwych plikach taty i na jedną notkę „Co nowego”
zamiast każdej naprawy z osobna.

- **Najnowsze Wydanie** to tag z najwyższym numerem, którego commit był
  czubkiem `main`, czyli leży na linii pierwszych rodziców `main`
  (`tool_update.newest_on_main`, `_main_tips`). Commit z gałęzi wciągniętej do
  `main` zwykłym merge'em leży na `main`, ale nigdy nie był jego czubkiem, więc
  uśpiony tag na nim (założony na gałęzi agenta) nie staje się Wydaniem. Liczy się numer, nie porządek
  alfabetyczny (`v0.10.0` jest nowsze niż `v0.9.0`). Tag z dopiskiem
  (`v1.0.0-rc1`), tag innego kształtu i tag na obiekcie innym niż commit nie są
  Wydaniami. Wyższe Wydanie spoza `main` (tag założony z gałęzi agenta) jest
  pominięte i nie zatrzymuje niższego Wydania na `main`; same Wydania spoza
  `main` to tak, jakby Wydań nie było. Ten sam wybór robią Aktualizacja
  narzędzia, instalacja z README i Aktualność narzędzia.
- **Dowolny MAJOR.** #315 mówi o `v0.MINOR.PATCH`, ale kod przyjmuje każdy
  MAJOR. Gdyby kiedyś powstało `v1.0.0`, kod tylko z `v0` zostawiłby tatę na
  zawsze na ostatnim `v0`. Zabłąkany `v1.0.0` na `main` trafiłby do taty, tak
  jak każdy ręczny tag na `main`; przed nim chroni brama pre-push (niżej).
  Dowolny MAJOR to decyzja Maksa z 23.10.
- **Aktualizacja narzędzia.** `ToolClone.update` pobiera `main` (z `+`, więc
  force-push `main` na GitHubie nie psuje pobrania) i tagi `v*` do własnej
  przestrzeni refów klonu (`refs/wydania/`, z `--prune`, więc tag usunięty
  albo przesunięty na GitHubie nie zostaje u taty). Przesuwa lokalną `main`
  taty tylko do przodu, na commit najnowszego Wydania. Aktualizacja nigdy nie
  cofa wersji: klon, który już zawiera ten commit (także na nowszym commicie
  `main`), i GitHub bez Wydania na `main` to `AKTUALNA`, klon bez zmian.
  Pominięte Wydania spoza `main` dziennik Centrum zapisuje jako
  `aktualizacja-pominiete-wydania`, jeszcze przed ponownym startem. Błąd Gita przy sprawdzaniu, czy Wydanie
  leży na `main`, kończy aktualizację z nieoczekiwanego powodu, a nie
  pominięciem.
- **Aktualność narzędzia.** Diagnoza i Konfiguracja pytają API GitHuba o listę
  tagów (`tags?per_page=100`, wszystkie strony, najwyżej 10) i o to, czy commit
  najwyższego Wydania leży na linii pierwszych rodziców `main` (najwyżej 5
  Wydań po kolei). Pytanie to porównanie z `<czubek>~k` (`compare` ze stroną
  bez commitów i plików, kilkanaście kB) dla czubka `main` ustalonego raz na
  sprawdzenie (`git/ref/heads/main`) i k wybranego wyszukiwaniem binarnym:
  Wydanie leży na linii, gdy jest jednym z `<czubek>~k`. Wyszukiwanie zaczyna
  się dopiero wtedy, gdy commit Wydania, przodek czubka, nie jest commitem
  scalenia PR do `main` (`commits/<sha>/pulls`, `merge_commit_sha` PR z bazą
  `main`): taki commit był czubkiem `main`, więc leży na linii. Odpowiedź dla
  Wydania, które jest przodkiem `main`, Centrum pamięta do końca swojego
  działania, bo `main` rośnie tylko o nowe commity. Narzędzie jest
  `Aktualna`, gdy jego commit zawiera commit najnowszego Wydania: sprawdza to
  `git merge-base --is-ancestor` w klonie taty, bez pytania API. Narzędzie na
  nowszym commicie `main` niż Wydanie jest więc aktualne. Brak odpowiedzi to
  `Nie sprawdzono` z „brak połączenia z GitHubem”, a GitHub bez Wydania na
  `main` to `Nie sprawdzono` z „na GitHubie nie ma jeszcze żadnego Wydania”.
  Konfiguracja pamięta każdą odpowiedź, także „brak Wydania”, przez 10 minut,
  a brak odpowiedzi przez minutę: zwykle dwa pytania co 10 minut przy limicie
  60 na godzinę bez logowania. Ten limit dzieli cały adres IP taty: 8.11.2026
  coś w jego sieci go wyczerpało i tata nie widział v0.6.1. Od tego dnia
  Centrum pyta z Tokenem do Zgłoszeń, gdy jest (5000 na godzinę dla konta,
  ADR 0007), a odmowa z powodu limitu to w Diagnozie „GitHub chwilowo nie
  odpowiada na pytania o nową wersję” z godziną odnowienia limitu.

  Koszt: nowe Wydanie to raz na działanie Centrum cztery pytania (lista tagów,
  czubek, porównanie z nim, PR-y commitu), jak daleko by `main` od niego nie
  odszedł, potem tylko lista tagów. Wydanie bez scalenia PR kosztuje około log2
  z liczby commitów `main` od Wydania pytań więcej. Samo wyszukiwanie przy 239
  commitach `main` od `v0.1.1` (26.10) to 11 pytań w 5,38–5,55 s, ponad
  limit 3 s, więc tata po starcie Centrum widział `Nie sprawdzono`. Na
  prawdziwym repozytorium 26.10 każdy ze 139 commitów linii pierwszych rodziców
  `main` od `v0.1.0` był commitem scalenia PR, a żaden ze 173 sprawdzonych
  commitów spoza linii nim nie był. Do 25.10 Aktualność sprawdzała tylko
  osiągalność (jedno pytanie), więc przy uśpionym tagu wciągniętym do `main`
  merge'em pokazywała `Jest nowsza wersja`, a aktualizacja odpowiadała `Masz
  najnowszą wersję.`. Linię pierwszych rodziców przez `<czubek>~k` przyjął Maks
  w przeglądzie z 25.10 (Q21).
- **Tworzenie Wydania** (osobna zmiana, #316) sprawdza, że commit leży na
  `main` i ma zielone `Required CI status`, i dopiero wtedy zakłada tag i
  Wydanie na GitHubie z notką „Co nowego”. Notkę pokazuje Powiadomienie o
  nowej wersji (ADR 0015); numer i commit Wydania Centrum bierze z tagu.
  Centrum zielonego CI nie sprawdza.
- **Przycisk** `Zaktualizuj narzędzie` Konfiguracja, Diagnoza i Powiadomienie
  o nowej wersji pokazują tylko wtedy, gdy Aktualność to `Jest nowsza wersja`;
  przy `Aktualna` i przy `Nie sprawdzono` (brak sieci, brak Wydania, brak
  commitu) go nie ma. Regułę ma jedno miejsce, `tool_freshness.offers_update`,
  a Konfiguracja i Powiadomienia podają ją przeglądarce w polu `update_offered`
  (#319, #324). Powiadomienie o naprawie miało przycisk zawsze; #323 je
  usunęło. Powiadomienie o nowej wersji ocenia ostatnią odpowiedź GitHuba, więc
  bez sieci zostaje takie, jakie było. Odpowiedź `Masz najnowszą wersję.`
  zostaje na klon przesunięty po starcie Centrum i na każdego klienta HTTP. Dotyczy
  najnowszego Wydania, które Centrum znało w jej chwili: gdy pozna inne
  (pamięć Konfiguracji i Powiadomień, do której trafia też każda odpowiedź z
  Diagnozy), odpowiedź znika, więc przy przycisku nowszego Wydania jej nie ma
  (#373).

### Ochrona przed tagiem założonym ręcznie

Agenci pracują na tym samym koncie GitHuba co Maks (admin), więc żadne
uprawnienie GitHuba nie odróżni tagu z tworzenia Wydania od tagu założonego
ręcznie. Ochrona ma trzy warstwy:

- **Centrum pomija Wydanie spoza `main`** (wyżej). Tej warstwy nie omija ręczny
  tag z gałęzi agenta i pilnują jej testy w `tests/test_aktualizacja_narzedzia.py`.
- **Brama pre-push odrzuca push agenta z `refs/tags/v*`.** Tag Wydania i
  GitHub Release tworzy tylko narzędzie Wydań, które ustawia
  `MAXIMISEART_WYDANIE=1`. Brama widzi tylko `git push`; `git push
  --no-verify`, `git tag`, `gh release` i `gh api` w Bashu agenta odrzuca
  hook `PreToolUse` `tools/hooks/czekanie.py` z drogą przez skill `wydanie`,
  a stronę GitHuba, skrypt i formy spoza granicy w docstringu hooka łapie
  tylko przegląd.
- **Tagi Wydań się nie zmieniają.** Ruleset „Wydania v* bez przesuwania i
  usuwania” (id `25751654`, reguły `update` i `deletion`, bez wyjątków) blokuje
  przesunięcie i usunięcie tagów `v*`, także adminowi; założenie nowego tagu
  przechodzi. Sprawdzone na tymczasowym tagu próbnym: przesunięcie i usunięcie
  dostały `GH013`, utworzenie przeszło. Niezmienne Wydania GitHuba nie są
  włączone. Pomyłkowy tag naprawia się nowszym Wydaniem; usunięcie wymaga, żeby
  Maks na chwilę wyłączył ruleset.

Nie chroni: tag na commicie `main` bez zielonego CI, który ominie bramę
(`--no-verify`, push spoza agenta), i tag na commicie, który `main` potem
zrewertował, trafią do taty. Centrum nie pyta API o `Required CI status`
commitu: decyzja Maksa z 23.10.

## Przejście

- Wersja u taty sprzed tej zmiany pobiera `main`. Jej ostatnia aktualizacja
  bierze `main` z chwili kliknięcia. Dopiero wersja, którą przyniesie, pobiera
  Wydania. Tata staje więc na commicie merge'a albo nowszym, a od pierwszego
  Wydania na nim albo przed nim Aktualność mówi `Aktualna`.
- Pierwsze Wydanie `v0.1.0` powstaje na commicie merge'a po zielonym CI. Tag
  przed merge'em nie jest potrzebny: bez Wydania tata widzi prawdziwe `Nie
  sprawdzono`, a `Masz najnowszą wersję.` przy kliknięciu (od #319 przycisku
  wtedy nie ma). Od merge'a do potwierdzenia u taty nic nie wchodzi do
  `main`: stara wersja bierze `main` z chwili kliknięcia, więc nowy commit
  trafiłby do taty bez Wydania.
- Okno ryzyka: od merge'a do zielonego CI na jego commicie Diagnoza starej
  wersji dalej proponuje aktualizację, a stara wersja bierze `main` bez
  sprawdzenia CI. Gdy tata kliknie w tym oknie, a CI na tym commicie padnie,
  tata zostaje na nim do następnego Wydania, bo nowy kod nie cofa.
- Nowa instalacja u taty: `git clone`, potem `git reset --hard` na najnowsze
  Wydanie wybrane jak w Centrum (README).

## Konsekwencje

- Naprawa dociera do taty dopiero z następnym Wydaniem. Sprawę zamkniętą przed
  Wydaniem Powiadomienia z ADR 0015 nazywają rozwiązaną, z dopiskiem, że będzie
  w następnej wersji; przycisk aktualizacji przynosi dopiero Powiadomienie o
  nowej wersji, które wymienia ją z notki Wydania.
- Zielone, ale zepsute Wydanie naprawia się tylko do przodu: nowym Wydaniem z
  revertem. Usunięcie tagu nie cofa taty, bo aktualizacja nigdy nie cofa.
- Schemat `v*.*.*` i reguła „najwyższy numer na `main`” są umową z kodem u taty.

## Odrzucone warianty

- Gałąź `stabilna`, którą CI przesuwa na każdy zielony commit `main` (pierwsza
  wersja tego ADR): tata dostawałby 12-40 zmian dziennie bez notki i bez
  `verify-*` na prawdziwych plikach, a ręczny push na `stabilna` omijał CI tak
  samo jak ręczny tag.
- Centrum wybiera najnowszy commit `main` z zielonym CI przez API: więcej
  pytań do API bez logowania, logika wyboru wersji u taty, i dalej każda
  zmiana od razu u taty.
- Najnowszy tag według porządku alfabetycznego albo daty: `v0.10.0` przegrałby
  z `v0.9.0`, a data tagu mówi, kiedy go założono, nie co zawiera.
- Najwyższy tag w ogóle, z odmową, gdy nie leży na `main` (poprzednia wersja
  tego ADR): jeden zabłąkany tag zatrzymywał każde niższe Wydanie, a przy
  zakazie usuwania tagów nie dało się go zdjąć.
- Aktualność przez równość commitów: tata na nowszym commicie `main` niż
  Wydanie widział `Jest nowsza wersja`, a aktualizacja odpowiadała `Masz
  najnowszą wersję.`.
- Lokalna gałąź taty na tagu (odłączony `HEAD`): `INNA_GALAZ` zmieniłaby
  znaczenie, a commit narzędzia czyta się dziś z gałęzi.
