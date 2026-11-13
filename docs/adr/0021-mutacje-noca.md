# ADR 0021: Mutacje nocą

## Status

Zaakceptowana (decyzja Maksa z 29.10: „nie możemy na każdy nowy PR odpalać mutacji”).
Zastępuje część [ADR 0020](0020-ci-w-poziomach.md) o Change mutations na PR: poziom bramki PR i `tools/scal_pr.py` przestają na nie czekać.
Zastępuje też część ADR 0020 o skryptach mutacji skilli na PR, a od 13.11 także w pełnym CI `main`: biegną nocą na `main`.
Opiera się na [ADR 0014](0014-tata-dostaje-tylko-wydania.md) i ADR 0020, według których granicą bezpieczeństwa taty jest Wydanie, a nie PR.
Zmieniona 31.10 (#701, zgoda Maksa w wątku T3: „okej zgadzam się na wdrożenie tego”): skrypt mutacji modelu TLA+ skilla biegnie też na PR, który zmienia jego model (sekcja Decyzja).
Zmieniona 3.11 (cel Maksa w triage 3.11: noc ma znów każdej nocy dawać wynik i zbiegać do zielonego po zaległości): noc ma limit mutacji, a zaległość przechodzi na kolejne noce; część mieści się w limicie czasu także z najdroższymi zmierzonymi mutacjami, a mutacja bez werdyktu po limicie części trafia do issue zamiast zatrzymać noc (sekcje Decyzja, Konsekwencje i Odrzucone warianty).
Zmieniona 6.11 (#935, Maks 5.11: „gotowe dla agenta”): ostrzeżenie `CZAS BLISKO LIMITU` skryptu mutacji skilla z nocy trafia do issue PR-u (sekcja Decyzja).
Zmieniona 6.11 (przegląd architektury 6.11, decyzja koordynatora w trybie auto Maksa): ręczny run z `od` spoza linii `main` liczy od wspólnego przodka HEAD i `od`, jak części (sekcja Decyzja).
Zmieniona 12.11 (#1339, bieg issues w trybie auto Maksa): mutacja, której ostatni przebieg testów skończył się `PRZEKROCZONY CZAS`, trafia do issue z dopiskiem, że noc nie dała jej werdyktu, a nie jako przeżyta; dalej nie jest wykryta (sekcje Decyzja i Odrzucone warianty).
Zmieniona 12.11 (hillclimb CI, budżet Maksa z 12.11: najwyżej 20 zadań nocy naraz): noc zajmuje najwyżej 17 zadań części i 3 zadania skryptów skilli naraz, a części startują od najdroższej według pracy testów na `main` (sekcje Decyzja i Odrzucone warianty).
Zmieniona 13.11 (Z4, zgoda Maksa): test, który w części pada bez mutacji, biegnie raz jeszcze jak w bramce PR, a gdy przejdzie, część mutuje dalej, a test dostaje issue `Flaky test:` (sekcje Decyzja i Konsekwencje).
Zmieniona 13.11 (Z1, zgoda Maksa): skrypty mutacji skilli nie biegną w pełnym CI `main`, tylko nocą, a noc uruchamia skrypt także przy zmianie modułu, który importuje sprawdzenie jego mutacji, i pliku, który psuje jego mutacja (sekcje Kontekst, Decyzja, Konsekwencje i Odrzucone warianty).

## Kontekst

Cel Maksa to czas CI na PR z p50 najwyżej 2 min i p90 najwyżej 5 min, jak w najlepszych repo (Matt Pocock course-video-manager p50 2,6 min, t3code p50 4,2 min).
Po ADR 0020 Change mutations startowały po zielonym `Required CI status` na każdym PR, który zmieniał `src/` albo `tools/`, i trwały 15–18 min.
Na przykład w runie 40612759981 Required skończył się po 5,6 min, a Change mutations po 21 min.
`tools/scal_pr.py` czekał na ich koniec i wymagał w `PASS` linii `MUTACJA` dla każdej przeżytej mutacji, więc to one były ogonem czasu do merge'a.
W części mutacji 6–10 min zajmuje pokrycie testów zmienionych plików, a każda mutacja ok. 10 s (runy z 27–28.10).
ADR 0020 podaje, że Change mutations nie złapały żadnego defektu produktu, którego nie złapał pytest w tym samym runie, a dały luki w testach.
To samo dotyczy skryptów mutacji skilli (`check_*_mutations.py`) w Mutation checks na PR: jedyny unikalny defekt z backtestu ADR 0020 (#438) złapała podstawa skilla (`ci:`, przebieg bez mutacji), a nie mutacja.
Skrypt mutacji mierzy jakość sprawdzenia skilla, tak jak Change mutations mierzą jakość testów, a w modelu 60 PR z 25–28.10 zajmował 36% runner-minut bramki (45,9 → 29,5 na PR bez nich).
Luka w teście nie jest defektem, który trafi do taty: ten zatrzymuje Wydanie z zielonym pełnym CI `main`.
Z1 (13.11): na pushu do `main` skrypty mutacji skilli kosztowały 105–114 runner-min na run, ok. 455 runner-h w 10 dniach 2–12.11, czyli 46% kosztu `main` (diagnoza hillclimbu CI 12.11, próbka 38 zielonych runów `main`).
W księdze czerwonych runów `main` 26.10–12.11 złapały 5 epizodów (#667, #897, #919 i #948, #1127, #1198), każdy to defekt samego sprawdzenia skilla (kotwica, czas sprawdzenia, czas mutacji, eksplorator, rozjazd modelu), a żaden defekt produktu.
Defekt produktu łapie podstawa `ci:`, którą skrypt mutacji uruchamia bez mutacji, a ta zostaje w pełnym CI `main` i na PR.

## Decyzja

- Change mutations nie biegną na PR.
  `ci.yml` nie ma ich zadania, plan CI ich nie liczy, a `tools/scal_pr.py` nie sprawdza ich ani linii `MUTACJA` w `PASS`.
- Workflow `mutacje-nocne.yml` biegnie raz na dobę na `main` i ręcznie z opcjonalnym `od`.
  Mutuje linie `src/` i `tools/` zmienione od bazy tym samym `tools/mutacje_zmiany.py`: jedna mutacja na linię, cofnięcie fragmentu, wyjątki `# mutacje-zmiany:`.
  Bazą jest commit, do którego doszedł ostatni udany przebieg (`do` z jego artefaktu `zakres-nocy`, a w runie bez niego jego commit), a bez udanego przebiegu commit sprzed 24 h.
  Ręczny run z `od` spoza linii `main` liczy od wspólnego przodka HEAD i `od` (`git merge-base`), od którego liczy też każda część, więc plan i części mutują te same zmiany, a cofnięcie zmian gałęzi `od` nie wchodzi do nocy; `od` bez wspólnego przodka z HEAD kończy plan błędem.
- Mutacje dzielą się na części, kolejne na liście posortowanej po plikach, żeby każda część liczyła pokrycie tylko dla kilku plików.
  Część ma 6 pełnych kolejek po 4 mutacje naraz, czyli 24 mutacje (`NA_CZESC` w `tools/mutacje_nocne.py`), a jej limit czasu to 175 min w zadaniu 180 min.
  Koszt mutacji zależy od pliku o dwa rzędy wielkości, a przed pokryciem plan go nie zna.
  W nocach 31.10–3.11 (runy 41179652907, 41285996039, 41408995300, 41601085650, 2892 mutacje) mediana mutacji pliku wynosiła 1–210 s, ale 34 mutacje trwały pełne 900 s, 16 z nich w `tools/mutacje.py`.
  Pokrycie części trwało tam najwyżej 1006 s, a brama typów najwyżej 58 s.
  Mutacje po 900 s kończyły się w testach linii, które biegną po 4 mutacje naraz.
  Testy kodu pliku, też po 4 naraz, trwały dla jednej mutacji najwyżej 836 s, a testy pliku, po jednej mutacji, najwyżej 441 s.
  Do testów kodu pliku doszło najwyżej 11 z 32 mutacji części, do testów pliku 37 z 93, a do obu naraz najwyżej po 12 z 49.
  Część mieści się w limicie, gdy ma najgorszy czas każdego przebiegu naraz, choć zmierzono je w różnych częściach, a do dalszych przebiegów dochodzi tyle jej mutacji, co w którejś zmierzonej części: 16 mutacji `tools/mutacje.py` po 900 s w testach linii, reszta po 210 s, testy kodu pliku po 836 s, testy pliku po 441 s, pokrycie i brama typów, najgorzej ok. 9700 s.
  Przy 28 mutacjach tak liczona część trwa ok. 10 800 s, ponad limit.
  Gdyby udziały dalszych przebiegów wziąć z różnych części (11 z 32 do testów kodu pliku i 37 z 93 do testów pliku w jednej części), w limicie zmieściłoby się 20 mutacji.
  Mutacja, która trwa pełny limit także w testach pliku, może limit części przekroczyć i zostaje wtedy bez werdyktu.
  Te same czasy w częściach pierwszej nocy po limicie mutacji nocy dają przy 25 mutacjach najdłuższą część ok. 3400–3600 s, więc w limicie 3300 s ona sama czerwieniłaby każdą noc z tym samym zakresem.
  Przy 24 mutacjach najdłuższa część tej nocy (24 mutacje `tools/lib/wplyw_zmiany.py`, z czego 6 w testach pliku po kolei przez ok. 2300 s) trwa tak liczona, ze wszystkimi przebiegami testów, ok. 4700 s, mniej niż połowę limitu części.
- Część, której limit czasu minął po pokryciu, przed werdyktem którejś mutacji, dała wynik: `tools/mutacje_zmiany.py` kończy się kodem 3, a zapis wymienia mutacje bez werdyktu.
  Każda trafia do issue `Przeżyte mutacje z #N` PR-u, który ostatni zmienił jej linie, z dopiskiem `bez werdyktu w limicie czasu części`, a agent sprawdza ją `tools/mutacje.py`.
  Zadanie części zostaje zielone, a przebieg przesuwa bazę, więc część z drogimi mutacjami nie zatrzymuje nocy, a następna noc nie dostaje tego samego zakresu.
- Noc ma najwyżej 40 części, czyli 960 mutacji, a naraz biegnie najwyżej 17 zadań części i 3 zadania skryptów skilli, bo 60 zadań organizacji dzielą też runy CI PR-ów, a noc dostaje z nich najwyżej 20.
  GitHub wpuszcza wpisy macierzy do okna `max-parallel` w kolejności listy: w nocach 9–12.11 (runy 42584604729, 42783639074, 42982940704, 43183893292) wpisy spoza pierwszej fali startowały po kolei (0 inwersji w 77 wpisach), zwykle 1–2 s po końcu innej części, a gdy sloty organizacji były zajęte, także pierwsza fala startowała z opóźnieniem i nie po kolei (12.11: 9 z pierwszych 20 wpisów po 190–216 s).
  Dlatego plan stawia na początku listy części, których najdroższy plik ma najwięcej pracy dotkniętych nim plików testów w zadaniach pytest `linux-3.14` na `main` (artefakt `czasy-ci`), a równa praca, także bez czasów, zostawia kolejność numerów.
  Kolejność nie zmienia mutacji części ani ich zgłoszenia, bo te wyznacza numer części.
  Symulacja na czasach zadań tych 4 nocy: szczyt 34–36 zadań naraz spada do 20, a ściana części i skilli 2,92–4,06 h zmienia się na 2,92–3,61 h (średnio 3,49 → 3,30 h); sam limit 17 + 3 bez kolejności dałby 3,35–4,49 h.
  Gdy od bazy jest więcej mutacji, noc mutuje tylko zmiany do najdalszego commitu linii pierwszych rodziców `main`, do którego ich mutacje mieszczą się w limicie, ale co najmniej do pierwszego commitu z mutacjami, także większego (`do`).
  Mutacja należy do zakresu, gdy którąś z jej linii ostatni zmienił (`git blame --first-parent`) commit, który `do` zawiera, a plan i części liczą listę mutacji od bazy, zakres do `do` i podział na części jedną klasą, `ZakresMutacji` w `tools/mutacje_zmiany.py`.
  Przebieg biegnie na HEAD `main`, więc mutuje dzisiejszy kod, a linie zmienione po `do` mutuje następna noc, której bazą jest `do`; linia zmieniona przed `do` i jeszcze raz po nim wchodzi do obu.
  Plan pisze, ile mutacji czeka na następne noce (`MUTACJE NOCNE | zaległość:`).
- Każda przeżyta mutacja trafia do issue `Przeżyte mutacje z #N` z etykietą `ready-for-agent` PR-u, który ostatni zmienił zmienione linie, które ona psuje (`git blame` na `main`, commit scalenia, a bez numeru w jego temacie API GitHuba).
  Jedno issue na PR, a ta sama mutacja nie trafia do niego drugi raz, także gdy jej linie się przesuną: porównuje się klucz z pliku i zmienionego kodu, bez numerów linii.
  Issue naprawia agent testem, który zabija mutację, albo linią `MUTACJA <id> | nie warto, bo <powód>`.
- Mutacja, której ostatni przebieg testów skończył się `PRZEKROCZONY CZAS` (`--limit-s`, 900 s), a której nie wykryła brama typów, trafia do issue PR-u z dopiskiem `przekroczony czas testów, bez werdyktu` i radą, by sprawdzić ją `tools/mutacje.py` (#1339).
  Limit dotyczy całego polecenia `pytest`, a zbiór testów pliku trwa bez mutacji blisko niego: w runie 42783639074 część 10/37 dała `NIEWYKRYTA` po 802.59 s i 800.20 s, a mutację `report_box.py:210`, którą `tests/test_skrzynka_zgloszen_github.py` łapie w 14 testach, `PRZEKROCZONY CZAS` w tym samym zbiorze.
  Taki wynik nie mówi więc ani, że test łapie mutację, ani, że jej nie łapie; przed #1339 siedem takich linii z nocy 9–11.11 trafiło do issues jako zwykłe przeżyte, choć test każdą łapał.
  W runach 42783639074 i 42982940704 tak kończyło się 21 z 64 i 20 ze 143 przeżytych mutacji (odtworzenie zapisów i logów części w #1339).
  Zapis części ma je w liście `przekroczony_czas`, a część kończy się kodem 1 jak z przeżytymi.
  `PRZEKROCZONY CZAS` w przebiegu przed ostatnim ma linię w logu części z nazwą przebiegu, a mutacja biegnie dalej z szerszymi testami.
- Przeżyta to mutacja, której nie wykrył ani test, ani brama typów (#703, zgoda Maksa w wątku T3 31.10).
  Mutację operatora (`True` → `False`, `<` → `<=`, `return x` → `return None`…), która przeżyła testy, sprawdzają jeszcze ruff i mypy obu systemów, te same kroki co brama pre-push (`tools/mutacje.py`, `type_gate`).
  Gdy któryś zgłasza, że kod jest błędny, mutacja jest `WYKRYTA PRZEZ BRAMĘ TYPÓW` i nie trafia do issue, bo takiego kodu nie wpuszczą brama pre-push ani zadanie CI „Ruff, mypy”.
  Za błąd kodu liczy się z ruff tylko niezdefiniowana nazwa (F821, F822, F823) i błąd składni, a z mypy każdy błąd typów poza pozostałościami (`unused-ignore`, `redundant-*`, `unreachable`, `no-any-return`), `mutacje.wrong`.
  Nieużyty import albo zmienna (F401, F841) się nie liczy, bo zostawia ją sama mutacja jednej linii.
  Cofnięcia fragmentu do bazy brama nie sprawdza: przywraca ono kod, który bramę przeszedł, więc jej błąd na nim powstaje tylko z niezgodności z niecofniętymi fragmentami tej samej zmiany (import, adnotacja, typ w innym miejscu).
  Pełne cofnięcie zmiany przeszłoby bramę, a testy by go nie złapały, więc brama nie mówi, czy test pilnuje zmiany, a każdą listę kodów da się tak obejść.
  Takie cofnięcie trafia do issue jak przed bramą, a gdy zmiana była tylko typów (#671, #674), agent odpowiada `nie warto`.
  Ręczne zamiany `check_all` skryptów mutacji skilli brama sprawdza tak samo jak mutacje operatorów.
  Brama biegnie tylko dla mutacji, które przeżyły testy, i raz bez mutacji, która daje im cache mypy; gdy bez mutacji coś zgłasza, przeżyte zostają przeżyte, a linia `BRAMA TYPÓW CZERWONA` idzie na stderr.
- Część, która nie dała wyniku (testy padają albo nie kończą się w limicie części bez mutacji, zły wyjątek, brak zapisu), jest czerwona, a przebieg z nią jest czerwony i nie przesuwa bazy, więc następna noc sprawdza te linie jeszcze raz, z tym samym limitem mutacji.
  Przeżyte mutacje i mutacje bez werdyktu po limicie części to wynik, więc zostawiają część zieloną.
- Test, który w części padł bez mutacji, nie czerwieni jej od razu: testy, które padły, biegną raz jeszcze, tym samym `niestabilne_testy.ponow` co w bramce PR (ADR 0020): najwyżej 5 testów, każdy z id, które da się zgłosić w issue, z zapisem pokrycia jak w pierwszym przebiegu.
  Gdy każdy przejdzie, część mutuje dalej (druga porażka to część bez wyniku z punktu wyżej), a testy trafiają do artefaktu `flaky-testy-mutacje-<część>`, z którego `zgloszenia.yml` po runie nocy zakłada albo komentuje issue `Flaky test: <test>`, tak jak po runie CI.
  W nocach 3–8.11 (runy 41601085650, 41793945765, 42185360488, 42351341369, 42459531620) 6 części padło w przebiegu bez mutacji, każda na jednym teście, który okazał się flaky testem albo testem losowo czerwonym (wyścig, termin, uuid4 z numerem, pomiar czasu na wolnym runnerze).
  Każdą z nich ponowienie by objęło, więc noce 4, 6, 7 i 8.11 byłyby zielone, o ile ten test za drugim razem przeszedł; 3.11 zostałaby czerwona przez 16 części na limicie czasu części.
- Skrypty mutacji skilli też nie biegną na PR: Mutation checks na PR to same podstawy `ci:` skilli, których `pilnuje:` albo folder trafia zmiana.
  Ta sama noc uruchamia skrypty skilli, których folder, runner mutacji, sprawdzenie, moduł, który sprawdzenie importuje, albo plik, który psuje mutacja (`Edit.file` z tabeli skryptu), zmienił się od jej bazy, w zadaniach planu `tools/plan_ci.py plan --zdarzenie noc`.
  Pełne CI `main` od 13.11 (Z1) nie uruchamia żadnego skryptu mutacji skilla, tylko każdą podstawę `ci:`, także tę, którą skrypt uruchamia bez mutacji.
  Moduły, które sprawdzenie importuje, noc liczy od Z1, bo sama zmiana kodu produktu może spowolnić sprawdzenie albo przesunąć jego mutację, a dotąd przy takiej zmianie skrypt uruchamiało tylko pełne CI `main`.
  Każdy z 5 epizodów wyżej noc wybrałaby i bez tego, bo jego PR zmieniał folder skilla; #667 zmieniał też `src/rozliczenia/centrum/outbox.py`, który importują sprawdzenia trzech innych skryptów.
  W 5 dobach `main` przed 13.11 noc wybierałaby 18–28 z 28 skryptów zamiast 11–28, a w 3 z nich już dziś wszystkie 28, więc ściana nocy nie przekracza dzisiejszej najdłuższej.
  Plik, który psuje mutacja, noc bierze z tej samej tabeli mutacji skryptu, bo 13 z 28 skryptów psuje plik, którego sprawdzenie nie importuje: 11 skryptów Centrum sięga go procesem Centrum, `check_quantity_rules_mutations.py` przez `pytest.main`, a `check_github_skrzynki_mutations.py` psuje plik testu (#1575, przegląd r1).
  W 5 dobach `main` przed 13.11 te pliki nie dokładają nocy żadnego skryptu, a `tests/test_zakres_runu.py` sprawdza na katalogu skilli, że zmiana każdego z nich wybiera nocą jego skrypt.
  Kotwicę mutacji, która przestała stać w swoim pliku, pilnuje już na PR pytest (`tests/test_mutacje_skilli.py`, #670).
  Skrypt, który padł, trafia linią `SKRYPT <skrypt>` do issue `Przeżyte mutacje skilli z #N` z etykietą `ready-for-agent` PR-u, który ostatni zmienił plik zmieniony od bazy, który uruchomił krok (`KrokSkilla.pliki` w `tools/lib/zakres_runu.py`): najpierw plik w folderze skilla, potem inny, a bez takiego pliku ostatni PR nocy; linia trafia tam bez powtórzeń, a zadanie bez zapisu czerwieni przebieg.
  Mutacja skryptu, której polecenie trwało ponad połowę limitu czasu mutacji (`CZAS BLISKO LIMITU`, `tools/mutacje.py`), trafia do tego samego issue linią `CZAS BLISKO LIMITU <skrypt> | <mutacja> | <czas> s z limitu --limit-s <limit> s`, także gdy skrypt przeszedł.
  Trafia tam raz, bo issue porównuje skrypt i mutację bez czasu, który zmienia się co noc, więc rosnący czas mutacji widać w issue, zanim `PRZEKROCZONY CZAS` zaczerwieni skrypt (#911, #935).
  `tools/skille_dla_zmiany.py` wymienia te skrypty w linii `LICZY NOC`, więc agent nie uruchamia ich przed pushem.
- Wyjątkiem jest skrypt mutacji modelu TLA+, którego każda mutacja psuje plik w folderze `model/` skilla (dziś `check_model_*_mutations.py` skilli `verify-kolejka-skrzynki`, `verify-urwane-uruchomienie` i `verify-wznowienie-wyceny-efenix`).
  Biegnie na PR, gdy PR zmienia plik w tym folderze (`*.tla`, `konfiguracje.json`), sam skrypt, sprawdzenie, które uruchamiają jego mutacje (`sprawdz_model_kolejki.py`), albo moduł, który to sprawdzenie importuje (`tools/lib/model_tlc.py` z parserem werdyktu i `.cfg`, od #1063), a wybiera go to samo `model_watched` dla planu PR i dla linii `LICZY CI` w `tools/skille_dla_zmiany.py`: oba czytają jeden wynik zakresu runu PR (`tools/lib/zakres_runu.py`, #720).
  Powód: zmiana modelu, po której mutacja kończy się `BŁĄD MODELU` zamiast naruszenia, nie zmienia werdyktu podstawy ani testów, więc przechodzi bramkę i przegląd, a czerwieni dopiero pełne CI `main`.
  Tak było przy #667 29.10: `Stop` dostał `UNCHANGED nieczytany`, a dwie mutacje, które zastępują `Stop`, nie ustawiały `nieczytany` i dawały `MODEL KOLEJKI: BŁĄD MODELU (1)`.
  Ten sam błąd przeszedł przegląd w powtórce zadania podczas hillclimbu przeglądu 30–31.10, bo recenzent skryptów z `LICZY NOC` nie uruchamia.
  Koszt: 10 z 212 merge'y 23–30.10 zmieniło model TLA+ jakiegoś skilla, a 6 merge'y w tym oknie zmieniło model kolejki, jej skrypt mutacji modelu albo sprawdzenie modelu, czyli dostałoby ten krok.
  Skrypt trwa 37–72 s na Macu, a w CI na Windows 156 s (mediana z runów `main`), które plan dzieli na części nie dłuższe od podstawy skilla, biegnącej przy tej samej zmianie, więc ok. 3% PR-ów zajmuje runnery o ok. 4 min dłużej, a ściana runu nie rośnie.
  Pozostałe skrypty mutacji skilli mutują kod produktu, który pilnuje też pytest bramki, i zostają w nocy.
- Podstawa z `ci-czesci:` biegnie na PR w częściach jednego n, które plan wybiera z celu ściany, więc ta sama noc, przy zmianie, która wybrałaby ją na PR, uruchamia każdą część każdego n od 1 do `ci-czesci`.
  Część, która pada tylko przy innym n (na przykład część zaczynająca się od funkcji, która potrzebuje stanu wcześniejszej), wychodzi tak w nocy, a nie dopiero na PR, którego cel ściany zmieni n.
  Pełne CI `main` uruchamia podstawę raz, w częściach z planu: wszystkie części każdego n przy każdym pushu `main` kosztowałyby ok. 55 min runnera Windows na merge.

## Konsekwencje

- Luka w testach PR wychodzi najpóźniej następnego dnia, w issue jego PR, a nie przed merge'em.
  PR, który by ją zamknął, jest osobną pracą z kolejki `ready-for-agent`.
- Recenzent nie omawia już mutacji w `PASS`, a przegląd PR kończy się razem z bramką.
- PR, który osłabia sprawdzenie skilla tak, że jego mutacja przeżywa, pokaże dopiero noc, która przypisze porażkę do issue jego PR (od Z1, 13.11, pełne CI `main` już tego nie pokazuje).
  Noc widzi go, gdy zmienia folder skilla, sprawdzenie, moduł, który sprawdzenie importuje, albo plik, który psuje mutacja; zmianę innego pliku, który sprawdzenie czyta bez importu, pokaże dopiero noc, którą uruchomi inna zmiana.
  Wydanie nie czeka na noc: commit z zielonym pełnym CI `main` jest do wydania, choć skrypt mutacji skilla na nim pada, bo taki skrypt mierzy jakość sprawdzenia, a nie produkt, który dostaje tata.
  Wyjątkiem jest zmiana modelu TLA+ skilla ze skryptem mutacji modelu: ta dostaje czerwone Mutation checks na PR.
- Noc mutuje zmiany wielu PR-ów naraz, więc pokrycie biegnie na testach wielu plików; części po plikach trzymają je w limicie czasu części.
- Część z drogimi mutacjami trzyma runner do 3 h zamiast 1 h, a zwykła część kończy się jak dotąd w kilka minut do godziny (31.10: 4–51 min).
- Mutacja bez werdyktu w issue to praca dla agenta PR-u, choć test może ją już wykrywać: zgłoszona raz, nie wraca do następnej nocy.
  Limit części jest ponad 2 razy dłuższy od najdłuższej części pierwszej nocy liczonej na zmierzonych czasach, więc taka linia wychodzi rzadko.
- Dzień z więcej niż 960 mutacjami, czerwona noc i noc, która nie wystartowała, zostawiają zaległość, którą przerabiają kolejne noce po 960, więc luka w testach PR-u z takiego dnia wychodzi później niż następnego dnia.
  Zaległość spada, gdy dzień ma mniej mutacji niż 960; ręczne uruchomienie workflow bez `od` przerabia następne 960 od razu.
  3.11 od bazy ostatniego udanego przebiegu czekało 2176 mutacji (`tools/mutacje_nocne.py plan`: 829 w pierwszej nocy i 1347 zaległości), a od 30.10 dochodziło ok. 570 mutacji na dobę, więc same noce wychodzą z zaległości po ok. 5 nocach, a noce po 1120 wyszłyby po ok. 4.
- Przed limitem nocy części rosły z zaległością: 1.11 po ok. 49 mutacji (10 z 20 części czerwonych na limicie czasu), 2.11 po ok. 93 (16 z 20), 3.11 po ok. 102 (16 z 20, run 41601085650), a czerwona noc nie przesuwała bazy, więc następna miała jeszcze więcej.
- Przebieg nocny, który nie skończył się sukcesem, nie zakłada issue o sobie; widać go w Actions, a następna noc powtarza jego zakres.
- Prawdziwa porażka, która przechodzi za drugim razem, nie czerwieni nocy, tylko daje issue `Flaky test:`; pilnuje jej dalej pełne CI `main`, które Wydanie wymaga zielonego.
  Flaky test zostaje w testach mutacji części, więc jego porażka po mutacji może policzyć mutację jako wykrytą i schować lukę w testach do następnej zmiany tej linii.

## Odrzucone warianty

- Liczba części z liczby mutacji (po 25) bez limitu nocy (3.11). Każda część mieści się w limicie czasu, ale czerwona noc zostawia całą zaległość następnej, więc części i runnery rosną z każdą czerwoną nocą, aż do limitu 256 zadań macierzy GitHuba.
- Przeniesienie mutacji bez werdyktu na następną noc po ich kluczu, z bazą przesuwaną po każdej nocy (3.11). Noc dalej dostaje więcej, niż przerobi, a odtworzenie przeniesionej mutacji wymaga mutacji od jej starszej bazy: klucz cofnięcia fragmentu zależy od fragmentu względem bazy, więc z nowszej bazy nie wraca, a przypisanie do PR-u liczy linie od najstarszej bazy.
- Zakres nocy przez checkout commitu `do` (3.11). Części biegłyby na starszym kodzie i starszych narzędziach, a zgłoszenie musiałoby przypisywać linie z `do`, nie z HEAD.
- Części po 25 mutacji w limicie 3300 s, bo „części po 31–32 mutacje trwały 6–50 min” (3.11). Run 41179652907 nie miał jeszcze mutacji `tools/mutacje.py` z #711 i #721: część pierwszej nocy z 25 takimi mutacjami trwałaby ok. 3400–3600 s (ich czasy z runu 41285996039), a czerwona noc wracałaby z tą samą częścią co noc.
- Części dzielone według szacowanego kosztu (3.11). Plan nie zna kosztu mutacji przed pokryciem: stosunek mediany mutacji pliku do czasu CI testów dotkniętych plikiem wynosił 0,00–0,48, a mutacja pliku z medianą 4 s potrafiła trwać 900 s. Koszt z poprzednich nocy wymaga stanu między nocami, a nowy drogi plik i tak czerwieniłby pierwszą noc.
  Kolejność startu części (12.11) to co innego: zła prognoza wydłuża tylko ścianę nocy, a nie zmienia części ani limitu.
- Kolejność części z kosztu mutacji pliku z poprzednich nocy (12.11). W nocach 10–12.11 korelacja rang z czasem części wynosiła 0,32–0,54, tylko 47–89% mutacji miało plik z kosztem z poprzedniej nocy, a 12.11 część 23 z 24 mutacjami `tools/lib/atrapy/atrapa_efenix.py` (176 min) trafiłaby na 28. miejsce, a ściana w symulacji byłaby o 0,3 h dłuższa niż w kolejności numerów. Praca testów z `czasy-ci` ma pomiar dla każdego pliku testów i korelację 0,58–0,66.
- Druga fala części w tym samym przebiegu dla mutacji bez werdyktu (3.11). Domyka je tej samej nocy, ale dokłada zadanie planu, drugą macierz i do 3 h przebiegu, a mutacja, której nie domknie druga fala, i tak potrzebuje reguły, która nie zatrzymuje nocy.
- PRZEKROCZONY CZAS jako mutacja wykryta, jak w Stryker i PIT (3.11). Mutacje nocy, które trwały 900 s (np. bez kopii cache mypy w bramie typów), spowalniały testy, a nie wieszały ich: żadnego testu nie przerwał pytest-timeout, więc CI by ich nie złapało. Reguła nie skraca też kolejki: mutacje, które czekały za nimi, dalej nie zaczynały się przed limitem części. Dlatego od #1339 taka mutacja nie jest wykryta, tylko trafia do issue z dopiskiem.
- Druga próba mutacji z `PRZEKROCZONY CZAS` w testach pliku, z dłuższym limitem albo z węższym zbiorem testów (12.11, #1339). Dłuższy limit dokłada do części kolejny przebieg testów pliku po jednej mutacji naraz, którego nie liczy rozmiar części (`NA_CZESC`), a węższy zbiór już przeszedł we wcześniejszych przebiegach, więc nie da werdyktu.
- Części po 28 mutacji, 1120 na noc (3.11, przegląd #815). Z najgorszymi czasami każdego przebiegu część po 28 trwa ok. 10 800 s, ponad limit części, więc mutacje z jej końca zostawałyby bez werdyktu.
- Mniejsze części, np. po 8 mutacji, które mieszczą się w 3300 s przy każdej mutacji po 900 s (3.11). Noc miałaby 320 mutacji przy 40 częściach, mniej niż daje dzień, więc zaległość by rosła, a większość części, z mutacjami po kilka sekund, biegłaby głównie pokrycie.
- Change mutations na PR, ale bez czekania na nie w `tools/scal_pr.py`. Każdy PR dalej zajmowałby trzy runnery po 15 min, a wynik po merge'u i tak musiałby trafić do issue.
- Mutacje tylko PR-ów z etykietą albo powyżej rozmiaru zmiany. Luki w testach są w małych zmianach tak samo, a wybór PR-ów to osąd, którego nic nie sprawdza.
- Każdy skrypt mutacji skilla na PR, który zmienia folder skilla (#701). Skrypty mutacji kodu produktu trwają do 13 min, a błąd z #667, który przeszedł bramkę i przegląd, był zmianą modelu TLA+, której nie widzą podstawa skilla ani pytest.
- Skrypty mutacji skilli w pełnym CI `main` (do 13.11). Każdy push do `main` uruchamiał każdy skrypt, ok. 46% runner-minut `main`, a od 26.10 do 12.11 złapały tylko defekty samych sprawdzeń, które noc łapie dzień później.
- Mutacje przy Wydaniu. Wydanie zbiera zmiany wielu dni, więc przebieg byłby długi, a luka wychodziłaby dopiero wtedy, gdy autor PR jest już przy innej pracy.
- Noc bez części podstawy z `ci-czesci`, gdy ta sama noc uruchamia skrypt mutacji jej skilla (Z10 hillclimbu CI, 13.11). Skrypt mutacji uruchamia bez mutacji tylko polecenia swoich mutacji (`_baseline` w `tools/lib/silnik_mutacji.py`), a nie polecenie `ci:`, i dla żadnej z czterech podstaw te polecenia nie sprawdzają wszystkiego, co podstawa.
  `verify-centrum-rozliczen` prowadzi `--feature all` przez 27 funkcji, a jego 11 skryptów przez 11 z nich; `verify-kolejka-skrzynki` ma 30 zakresów i konfiguracji, a skrypty 26, bez zakresów `zgloszenie` i `zgloszenie-lista` i konfiguracji `logi` i `postep`; `verify-urwane-uruchomienie` ma 8 konfiguracji, a skrypt 5, bez `wszystko` (ok. 85% podstawy), `odczyt` i `stare-logi` (komentarz `UNITS` jego `sprawdz_urwane_uruchomienie.py`); `verify-wycena-efenix` ma 468 przypadków, a skrypt 93 (`explore_wycena_efenix.py --lista`).
  Przebieg bez mutacji nie dzieli też podstawy na części żadnego n, a po to noc ją uruchamia.
  Podstawę, której polecenie `ci:` skrypt jej skilla uruchamia bez mutacji, wybór i tak pomija (`repeats` w `tools/lib/kroki_skilli.py`, dziś 6 skilli: karta-efenix, kopia-wzorca, publikacja-plikow-okresu, rozliczenia, status-okresu, zapis-intermax), ale żadna z czterech podstaw z `ci-czesci` nie ma takiego skryptu.
