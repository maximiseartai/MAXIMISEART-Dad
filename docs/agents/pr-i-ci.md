# CI na PR

Kiedy PR jest gotowy i jak go scalić, mówi sekcja `PR: od pushu do merge'a` w [`AGENTS.md`](../../AGENTS.md).
Dlaczego PR dostaje mniej sprawdzeń niż `main`, mówi [ADR 0020](../adr/0020-ci-w-poziomach.md).

## Co biegnie na PR

- `Required CI status` przechodzi, gdy przeszły `Frontend`, `Ruff, mypy`, `Plan CI` i każde zadanie pytest i Mutation checks z planu runu.
- `Frontend` oraz `Ruff, mypy` biegną na każdym PR, obok siebie i obok planu.
- pytest biegnie na torach Windows 3.11 i Linux 3.14.
  Każdy tor bierze pliki, które `tools/szybko.py` wybiera dla zmiany od bazy (bez jego budżetu czasu), i testy `STRUCTURE` z `tools/lib/wplyw_zmiany.py`.
  Lokalne `tools/szybko.py` uruchamia z tego wyboru zawsze pliki w odległości najwyżej 1 od zmiany, a dalsze tylko w swoim budżecie czasu, i resztę wypisuje jako „zostawione CI”.
  Pomija przy tym plik testu, który już przeszedł, jeśli od tamtej pory nie zmienił się ani on, ani nic, od czego zależy.
- Zmiana ścieżki, która w tabeli reguł `tools/lib/wplyw_zmiany.py` uruchamia wszystko w bramce PR (`Context.PR_GATE`: pliki, od których zależy każdy test, i `.github/workflows/`), wybiera wszystkie pliki testów, E2E i straż czasu.
- Co biegnie dla zdarzenia (push, PR, noc) i zmiany, rozstrzyga jeden moduł, zakres runu `tools/lib/zakres_runu.py`: plan CI go wycenia i pakuje, a `tools/skille_dla_zmiany.py` drukuje z niego linie `LICZY CI` i `LICZY NOC`.
- E2E biegnie na Windows 3.11 przy zmianie pod `src/`, a straż czasu przy zmianie w domknięciu jej skryptów (`STRAZ` w `tools/lib/zakres_runu.py`).
- Mutation checks biegną tylko wtedy, gdy zakres runu wybrał dla zmiany krok skilla (podstawę `ci:` albo skrypt mutacji modelu).
  Kiedy ją wybiera, mówi [`docs/agents/skille.md`](skille.md).
- Skrypty mutacji skilli (`check_*_mutations.py`) na PR nie biegną, tylko w pełnym CI `main` i nocą na `main` (sekcja `Change mutations` niżej).
  Wyjątkiem jest skrypt mutacji modelu TLA+ skilla (dziś `check_model_kolejki_mutations.py`), który biegnie na PR zmieniającym plik w `model/` skilla, sam skrypt albo sprawdzenie, które uruchamiają jego mutacje (ADR 0021, [`docs/agents/skille.md`](skille.md)).
- Mutacje zmienionych linii na PR nie biegną, tylko nocą na `main` (sekcja `Change mutations` niżej).
- Nowy push do PR anuluje run jego starszego commitu.
- Co biegnie na swojej gałęzi, drukuje `.venv/bin/python tools/plan_ci.py plan --baza origin/main` (Windows: `py -3 tools/plan_ci.py plan --baza origin/main`).
  Linia `PLAN CI` podaje źródło plików (`wybór <n> plików` albo `FULL (<pliki>)`), a linie `WYBRANY` i `POMINIĘTY` kroki skilli z powodem.

## Pełne CI na `main`

- Push do `main` uruchamia każdy plik testów na Windows 3.11, Windows 3.14 i Linux 3.14, E2E na obu torach Windows, straż czasu na Windows 3.14 i wszystkie kroki skilli.
- Trwający run `main` kończy się, a nowy merge podmienia tylko run, który czeka.

## Change mutations

- Biegną raz na dobę (workflow `mutacje-nocne.yml`, ADR 0021) na `main`, na liniach plików `src/**/*.py` i `tools/**/*.py` zmienionych od commitu ostatniego udanego przebiegu, a bez niego od 24 h wstecz.
  W tym samym przebiegu biegną skrypty mutacji skilli, których folder, runner mutacji albo sprawdzenie zmieniło się od tej bazy, w zadaniach z planu `tools/plan_ci.py plan --zdarzenie noc`.
  Biegnie w nim też każda część każdego n od 1 do `ci-czesci` podstawy z `ci-czesci:`, którą zmiana od bazy wybrałaby na pull request, bo pull request uruchamia jej części tylko jednego n.
  Ręczne uruchomienie workflow przyjmuje `od`, czyli commit, od którego liczyć zmiany.
- `tools/mutacje_nocne.py` dzieli mutacje na części po najwyżej 25, więc każda trwa ok. 10–15 min.
  Część, której testy sięgają Atrapy efenix, plan oznacza `przegladarka`, a jej zadanie instaluje Chromium tymi samymi krokami co zadanie pytest.
  Bazę i liczbę części drukuje bez testów `.venv/bin/python tools/mutacje_nocne.py plan`.
- Każdą przeżytą mutację ostatnie zadanie przypisuje PR-owi, który ostatni zmienił zmienione linie, które ona psuje, i dopisuje linią `MUTACJA <plik>:<linia> <opis> | klucz <klucz>` do issue `Przeżyte mutacje z #N` z etykietą `ready-for-agent`.
  Klucz nie ma numerów linii, więc mutacja nie trafia do issue drugi raz, także gdy następny PR przesunie jej linie.
- Skrypt mutacji skilla, który padł, ostatnie zadanie dopisuje linią `SKRYPT <skrypt>` do issue `Przeżyte mutacje skilli z #N` PR-u, który ostatni zmienił folder skilla od bazy, tak samo bez powtórzeń.
  Część podstawy, która padła, trafia tam linią `SKRYPT <skrypt z ci:>`, a bez zmiany folderu skilla do PR-u, który ostatni zmienił jego `pilnuje:`.
- Issue naprawiasz testem, który zabija mutację (dowód z `tools/mutacje.py`), albo linią `MUTACJA <plik>:<linia> <opis> | nie warto, bo <powód>`, a potem je zamykasz.
  Issue skryptu skilla naprawiasz poprawką sprawdzenia skilla albo tabeli mutacji, albo linią `SKRYPT <skrypt> | nie warto, bo <powód>`.
- Ani `Required CI status`, ani `tools/scal_pr.py` na mutacje nie czekają.
- Część bez wyniku (testy padają bez mutacji, zły wyjątek `# mutacje-zmiany:`, limit czasu części minął przed werdyktem którejś mutacji) jest czerwona i czerwieni przebieg, więc następna noc liczy od tej samej bazy, a przeżyte mutacje zostawiają część zieloną.
  Limit czasu części (`PART_LIMIT_S` w `tools/mutacje_zmiany.py`, 55 min) kończy ją przed 60 min jej zadania, więc zapis z przeżytymi mutacjami zostaje, a mutacje bez wyniku mają w logu linię `BEZ WERDYKTU`.
  Zadanie skryptów skilli bez zapisu też czerwieni przebieg.
  Czerwoną część odtwarzasz na commicie runu: `git checkout --detach <headSha runu>` i `.venv/bin/python tools/mutacje_zmiany.py --baza <baza z planu> --czesc K/N --odtwarzam <run>`.

## Zadanie CI padło

- Porażkę zadania odtwarzasz przez `.venv/bin/python tools/ci_lokalnie.py --tylko <zadanie>` (Windows: `py -3 tools/ci_lokalnie.py --tylko <zadanie>`).
- Linia `LIMIT | krok:pytest` znaczy, że krok pytest przekroczył swój limit z planu (`limit_pytest_s` w `tools/plan_ci.py`), czyli coś się zawiesiło: test, który wisiał, zostawił wyżej w logu stosy swoich wątków pod `Timeout (0:02:30)!` (`faulthandler_timeout` w `pyproject.toml`), a zawieszenie przy imporcie albo zbieraniu testów stosów nie zostawia.
- Ciężkie zadania liczy GitHub w częściach: `mutations` po pushu (stan pokazuje `tools/praca_w_toku.py` albo `gh pr checks`), a `change-mutations` i skrypty mutacji skilli nocą na `main`.
  Część skryptu mutacji albo podstawy z planu (`#k/n` w nazwie jednostki) odtwarzasz przez `MUTACJE_CZESC=k/n` w środowisku polecenia tego skryptu albo polecenia `ci:`.

## Plan runu, zadania pytest i Mutation checks

- Ile zadań pytest startuje na każdym torze i które pliki testów (albo udziały długiego pliku) bierze każde, ustala zadanie `Plan CI` (`tools/plan_ci.py`) z czasów ostatnich zielonych runów `main`, a E2E i straż czasu dokłada do zadań Windows.
- Plan dzieli kroki skilli (na PR podstawy `ci:` i skrypt mutacji modelu przy zmianie modelu, na `main` także każdy skrypt `check_*_mutations.py`) między zadania Mutation checks w tym samym limicie zadań runu i z tym samym celem ściany co pytest, a skrypt mutacji dłuższy niż zadanie dzieli na części, najwyżej po jednej na mutację.
- Podstawę `ci:` plan dzieli tak samo, na najwyżej tyle części, ile mówi klucz `ci-czesci:` w `SKILL.md`, a podstawę bez niego nie dzieli wcale.
  Linia każdego toru w planie nazywa najdłuższą jednostkę po podziale, poniżej której ściana zadania nie zejdzie.
- `Required CI status` czerwienieje też wtedy, gdy części podzielonej jednostki jednego toru nie są w planie dokładnie raz każdą z `1/n`…`n/n`.
- Chromium instaluje tylko zadanie Mutation checks z krokiem skilla, którego skrypty importują Playwright, i zadanie pytest z plikiem testów, który sięga Atrapy efenix (`PRZEGLADARKA` w `tools/lib/zakres_runu.py`), a nocą część Change mutations, której mutacje sprawdzają takie pliki testów.
- `Required CI status` czerwienieje także wtedy, gdy planu nie ma albo zadanie planu (pytest albo Mutation checks) nie zgłosiło w zapisie czasów ostatniej próby którejś swojej jednostki albo zgłosiło ją z porażką, a linia `REQUIRED FAIL` nazywa zadanie i jednostkę.
- Skrypt mutacji, którego wybór skilli by nie uruchomił (nazwa spoza wzorca, wskazany w `SKILL.md`, a usunięty), i zły klucz `ci:` plan zgłasza w `Required CI status` linią `REQUIRED FAIL | mutacje skilli: …`.
- Porażkę jednego zadania pytest odtwarzasz przez `tools/ci_lokalnie.py --tylko pytest` albo przez pytest na plikach tego zadania.
- Linia zadania w planie podaje liczbę jego plików i nazywa tylko udziały i kroki, a listę plików ma pole `jednostki` zadania w artefakcie `plan` runu (`gh run download <id runu> --name plan`).

## Status `scalenie z main`

- Status `scalenie z main` na HEAD PR mówi, czy scalenie PR z obecnym `main` przechodzi bez konfliktu, ruff i mypy dla obu systemów (`tools/ci/status_scalenia.py` w workflow `scalenia.yml`, po każdym pushu do `main`).
- Ruleset go nie wymaga, więc gotowość PR od niego nie zależy, choć `gh pr checks` kończy się kodem 1, gdy jest czerwony.
- `failure` znaczy, że PR trzeba zaktualizować z `origin/main` i poprawić, a opis statusu nazywa pliki z konfliktem albo kroki, które padły.
- `error` z „sam nie przechodzi” znaczy, że czerwony jest `main`, nie PR.
- Brak statusu znaczy, że `main` nie zmienił się od pushu PR albo przebieg jeszcze trwa.

## Czerwony `main`

- Czerwony `main` nie blokuje merge'ów, a naprawia go od razu osobny PR.
  PR, nad którym pracujesz, zostaje przy swojej zmianie.

## Każdy commit gałęzi

- Każdy commit gałęzi sprawdzasz, gdy tego potrzebujesz (nic tego nie wymaga), przez `tools/ci_lokalnie.py --kazdy-commit`.

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Rebase albo merge `main` do gałęzi robisz tylko przy konflikcie albo gdy `main` zmienił te same pliki co PR. | werdykt `AKTUALIZACJA` z `tools/praca_w_toku.py --aktualizacja`, drukowany też przez bramę `tools/hooks/pre-push`; `tests/test_praca_w_toku.py`, `tests/test_brama_pre_push.py` |
| Ciężkie zadania CI (`change-mutations`, `mutations`) liczy GitHub, a lokalnie biegną tylko do odtworzenia porażki z runu Actions tej gałęzi albo, na jego commicie, z runu `mutacje-nocne.yml`. | `tools/lib/ciezkie_ci.py`, `tests/test_ciezkie_ci.py`, `tests/test_na_scalonych_pr.py` |
| Lista dłuższa niż `TARGETED` mutacji w `tools/mutacje.py` to ręczne `change-mutations`, więc poza CI biegnie tylko z tymi samymi wyjątkami, a skrypty mutacji skilli `verify-*` (`check_all`) nie mają tego limitu. | `tools/lib/ciezkie_ci.py` (`TARGETED`), `tests/test_ciezkie_ci.py` |
| Bramka PR uruchamia pytest na Windows 3.11 i Linux 3.14 na wyborze `tools/szybko.py` dla zmiany, a zmiana ścieżki z `Context.PR_GATE` (`tools/lib/wplyw_zmiany.py`) wybiera wszystkie pliki, E2E i straż czasu. | `tests/test_zakres_runu.py::test_bramka_pr_biegnie_na_windows_311_i_linuksie_z_wyborem_szybko_a_e2e_i_straz_czasu_tylko_przy_ich_zmianie` |
| Do bramki PR dokładasz tylko to, co złapałoby defekt, który przez nią przeszedł, z dowodem z backtestu, a plan wzorcowych PR-ów L i C ponad limit testów, zadań albo prognozy ściany to decyzja Maksa. | limitu testów, zadań i prognozy ściany (+20%) pilnuje `tests/test_ksztalt_bramki.py`, a dowodu z backtestu tylko przegląd |
| Trwający run `main` kończy się, a nowy push do PR anuluje run jego starszego commitu. | `tests/test_zadania_ci.py::test_push_do_main_nie_anuluje_trwajacego_runu_a_nowy_push_pr_anuluje_stary` |
| `Required CI status` biegnie także w anulowanym runie, bo pominięty wymagany check przepuszcza merge. | `tests/test_zadania_ci.py::test_required_biegnie_takze_w_anulowanym_runie_bo_pominiety_wymagany_check_przepuszcza_merge` |
| Change mutations i skrypty mutacji skilli nie biegną na PR (poza skryptem mutacji modelu przy zmianie modelu) i gotowość PR na nie nie czeka, a biegną nocą na `main` od ostatniego udanego przebiegu i każdą przeżytą mutację dopisują raz do issue `Przeżyte mutacje z #N` PR-u, który ostatni zmienił jej linię, a skrypt, który padł, do issue `Przeżyte mutacje skilli z #N` PR-u, który ostatni zmienił folder skilla. | `tests/test_zadania_ci.py::test_required_czeka_na_kazde_zadanie_runu_a_pull_request_nie_mutuje_zmienionych_linii`, `tests/test_scal_pr.py::test_gotowy_pr_nie_czeka_na_mutacje_zmiany_ani_linie_mutacja_bo_mutacje_biegna_noca_na_main`, `tests/test_plan_ci.py::test_plan_pull_requestu_i_nocy_startuje_mutation_checks_tylko_z_praca_od_zmiany`, `tests/test_zakres_runu.py::test_na_pull_request_biegna_same_podstawy_a_noca_same_skrypty_mutacji` i `::test_na_pull_request_skrypt_mutacji_modelu_biegnie_przy_zmianie_modelu_skryptu_albo_sprawdzenia`, `tests/test_mutacje_nocne.py` |
