# ADR 0021: Mutacje nocą

## Status

Zaakceptowana (decyzja Maksa z 29.10: „nie możemy na każdy nowy PR odpalać mutacji”).
Zastępuje część [ADR 0020](0020-ci-w-poziomach.md) o Change mutations na PR: poziom bramki PR i `tools/scal_pr.py` przestają na nie czekać.
Zastępuje też część ADR 0020 o skryptach mutacji skilli na PR: biegną nocą na `main` i w pełnym CI `main`.
Opiera się na [ADR 0014](0014-tata-dostaje-tylko-wydania.md) i ADR 0020, według których granicą bezpieczeństwa taty jest Wydanie, a nie PR.
Zmieniona 31.10 (#701, zgoda Maksa w wątku T3: „okej zgadzam się na wdrożenie tego”): skrypt mutacji modelu TLA+ skilla biegnie też na PR, który zmienia jego model (sekcja Decyzja).

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

## Decyzja

- Change mutations nie biegną na PR.
  `ci.yml` nie ma ich zadania, plan CI ich nie liczy, a `tools/scal_pr.py` nie sprawdza ich ani linii `MUTACJA` w `PASS`.
- Workflow `mutacje-nocne.yml` biegnie raz na dobę na `main` i ręcznie z opcjonalnym `od`.
  Mutuje linie `src/` i `tools/` zmienione od commitu ostatniego udanego przebiegu (bez niego od 24 h wstecz) tym samym `tools/mutacje_zmiany.py`: jedna mutacja na linię, cofnięcie fragmentu, wyjątki `# mutacje-zmiany:`.
- Mutacje dzielą się na części po najwyżej 25, kolejne na liście posortowanej po plikach, żeby każda część liczyła pokrycie tylko dla kilku plików i trwała 10–15 min.
- Każda przeżyta mutacja trafia do issue `Przeżyte mutacje z #N` z etykietą `ready-for-agent` PR-u, który ostatni zmienił zmienione linie, które ona psuje (`git blame` na `main`, commit scalenia, a bez numeru w jego temacie API GitHuba).
  Jedno issue na PR, a ta sama mutacja nie trafia do niego drugi raz, także gdy jej linie się przesuną: porównuje się klucz z pliku i zmienionego kodu, bez numerów linii.
  Issue naprawia agent testem, który zabija mutację, albo linią `MUTACJA <id> | nie warto, bo <powód>`.
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
- Część, która nie dała wyniku, jest czerwona, a przebieg z nią jest czerwony i nie przesuwa bazy, więc następna noc sprawdza te linie jeszcze raz.
  Przeżyte mutacje to wynik, więc zostawiają część zieloną.
- Skrypty mutacji skilli też nie biegną na PR: Mutation checks na PR to same podstawy `ci:` skilli, których `pilnuje:` albo folder trafia zmiana.
  Ta sama noc uruchamia skrypty skilli, których folder, runner mutacji albo sprawdzenie zmieniło się od jej bazy, w zadaniach planu `tools/plan_ci.py plan --zdarzenie noc`, a pełne CI `main` dalej uruchamia każdy skrypt.
  Skrypt, który padł, trafia linią `SKRYPT <skrypt>` do issue `Przeżyte mutacje skilli z #N` z etykietą `ready-for-agent` PR-u, który ostatni zmienił folder skilla, bez powtórzeń; zadanie bez zapisu czerwieni przebieg.
  `tools/skille_dla_zmiany.py` wymienia te skrypty w linii `LICZY NOC`, więc agent nie uruchamia ich przed pushem.
- Wyjątkiem jest skrypt mutacji modelu TLA+, którego każda mutacja psuje plik w folderze `model/` skilla (dziś `check_model_kolejki_mutations.py` skilla `verify-kolejka-skrzynki`).
  Biegnie na PR, gdy PR zmienia plik w tym folderze (`*.tla`, `*.cfg`, `oczekiwane.json`), sam skrypt albo sprawdzenie, które uruchamiają jego mutacje (`sprawdz_model_kolejki.py`), a wybiera go to samo `model_watched` dla planu PR i dla linii `LICZY CI` w `tools/skille_dla_zmiany.py`: oba czytają jeden wynik zakresu runu PR (`tools/lib/zakres_runu.py`, #720).
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
- PR, który osłabia sprawdzenie skilla tak, że jego mutacja przeżywa, pokaże dopiero pełne CI `main` po merge'u i noc, która przypisze porażkę do issue jego PR.
  Wyjątkiem jest zmiana modelu TLA+ skilla ze skryptem mutacji modelu: ta dostaje czerwone Mutation checks na PR.
- Noc mutuje zmiany wielu PR-ów naraz, więc pokrycie biegnie na testach wielu plików; części po plikach trzymają je w 10–15 min, a gdy zmian jest więcej niż na 20 części, części rosną.
- Przebieg nocny, który nie skończył się sukcesem, nie zakłada issue o sobie; widać go w Actions, a następna noc powtarza jego zakres.

## Odrzucone warianty

- Change mutations na PR, ale bez czekania na nie w `tools/scal_pr.py`. Każdy PR dalej zajmowałby trzy runnery po 15 min, a wynik po merge'u i tak musiałby trafić do issue.
- Mutacje tylko PR-ów z etykietą albo powyżej rozmiaru zmiany. Luki w testach są w małych zmianach tak samo, a wybór PR-ów to osąd, którego nic nie sprawdza.
- Każdy skrypt mutacji skilla na PR, który zmienia folder skilla (#701). Skrypty mutacji kodu produktu trwają do 13 min, a błąd z #667, który przeszedł bramkę i przegląd, był zmianą modelu TLA+, której nie widzą podstawa skilla ani pytest.
- Mutacje przy Wydaniu. Wydanie zbiera zmiany wielu dni, więc przebieg byłby długi, a luka wychodziłaby dopiero wtedy, gdy autor PR jest już przy innej pracy.
