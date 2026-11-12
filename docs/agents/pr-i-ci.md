# CI na PR

Kiedy PR jest gotowy i jak go scalić, mówi `tools/scal_pr.py --help`.
Dlaczego PR dostaje mniej sprawdzeń niż `main`, mówi [ADR 0020](../adr/0020-ci-w-poziomach.md).

## Co biegnie na PR

- Co biegnie na swojej gałęzi, drukuje `.venv/bin/python tools/plan_ci.py plan --baza origin/main` (Windows: `py -3 tools/plan_ci.py plan --baza origin/main`).
  Linia `PLAN CI` podaje źródło plików (`wybór <n> plików` albo `FULL (<pliki>)`), a linie `WYBRANY` i `POMINIĘTY` kroki skilli z powodem.
- Do bramki PR dokładasz tylko to, co złapałoby defekt, który przez nią przeszedł, z dowodem z backtestu.

## Zadanie CI padło

- Gdy run padł przez starą wersję `main` w scaleniu PR, CI na świeżym scaleniu bez zmiany HEAD uruchamiasz przez `gh pr close N && gh pr reopen N`, więc werdykt dla HEAD zostaje ważny, a ponowienie zadania (`gh run rerun`) biegnie na starym scaleniu.
  Gotowość w `tools/scal_pr.py` i linia `CI` jego `--przeglad` liczą wtedy tylko najnowszy run workflow `CI` na HEAD, czyli ten o największym identyfikatorze runu z `detailsUrl` jego checków (`stan_pr.latest_ci_run` w `tools/lib/stan_pr.py`), więc checki starszych runów nie blokują merge'u ani go nie dają.
  Merge blokuje najnowszy run bez checku `Required CI status` (GitHub tworzy go dopiero po zadaniach z jego `needs:`, więc taki run jeszcze trwa), z Required w toku albo czerwonym i z zadaniem w toku obok zielonego Required (ponowienie zadań w tym samym runie).
- Porażkę zadania odtwarzasz przez `.venv/bin/python tools/ci_lokalnie.py --tylko <zadanie>` (Windows: `py -3 tools/ci_lokalnie.py --tylko <zadanie>`).
- Linia `LIMIT | krok:pytest` znaczy, że krok pytest przekroczył swój limit z planu (`limit_pytest_s` w `tools/lib/plan_runu.py`), czyli coś się zawiesiło: test, który wisiał, zostawił wyżej w logu stosy swoich wątków pod `Timeout (0:02:30)!` (`faulthandler_timeout` w `pyproject.toml`), a zawieszenie przy imporcie albo zbieraniu testów stosów nie zostawia.
- Ciężkie zadania liczy GitHub w częściach: `mutations` po pushu (stan pokazuje `tools/praca_w_toku.py` albo `gh pr checks`), a `change-mutations` i skrypty mutacji skilli nocą na `main`.
  Część skryptu mutacji albo podstawy z planu (`#k/n` w nazwie jednostki) odtwarzasz przez `MUTACJE_CZESC=k/n` w środowisku polecenia tego skryptu albo polecenia `ci:`.

## Status `scalenie z main`

- Status (`tools/ci/status_scalenia.py`) mówi w opisie, co zrobić, a ruleset go nie wymaga, więc gotowość PR od niego nie zależy, choć `gh pr checks` kończy się kodem 1, gdy jest czerwony.
- Brak statusu znaczy, że `main` nie zmienił się od pushu PR albo przebieg jeszcze trwa.

## Czerwony `main`

- Czerwony `main` nie blokuje merge'ów, a naprawia go od razu osobny PR.
  PR, nad którym pracujesz, zostaje przy swojej zmianie.
- Etykieta `zderzenie` w issue czerwonego `main` znaczy, że PR-y zielone osobno padły razem: każda nowa porażka jest w teście, którego wejścia zmieniły oba PR-y.
  Zielony `main`, który przyszedł bez zmiany wejść tych testów, zdejmuje ją z komentarzem, że porażka była niestabilna.

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Trwający run `main` kończy się, a nowy push do PR anuluje run jego starszego commitu. | `tests/test_zadania_ci.py::test_push_do_main_nie_anuluje_trwajacego_runu_a_nowy_push_pr_anuluje_stary` |
| Gotowość CI w `tools/scal_pr.py` liczy tylko najnowszy run workflow `CI` na HEAD PR (największy identyfikator runu z `detailsUrl`): gotowy jest, gdy ten run się skończył, a jego `Required CI status` przeszedł, więc po zamknięciu i otwarciu PR stare czerwone checki nie blokują merge'u, a trwający nowy run go blokuje. | `tests/test_scal_pr.py::test_gotowosc_ci_liczy_tylko_najnowszy_run_ci_na_head` |
| `Required CI status` biegnie także w anulowanym runie, bo pominięty wymagany check przepuszcza merge. | `tests/test_zadania_ci.py::test_required_biegnie_takze_w_anulowanym_runie_bo_pominiety_wymagany_check_przepuszcza_merge` |
| Change mutations i skrypty mutacji skilli nie biegną na PR (poza skryptem mutacji modelu przy zmianie modelu) i gotowość PR na nie nie czeka, a biegną nocą na `main` od miejsca, do którego doszedł ostatni udany przebieg, i każdą przeżytą mutację, także mutację bez werdyktu po limicie czasu części albo z przekroczonym czasem testów, dopisują raz do issue `Przeżyte mutacje z #N` PR-u, który ostatni zmienił jej linię, a skrypt, który padł, i raz na mutację ostrzeżenie `CZAS BLISKO LIMITU` skryptu do issue `Przeżyte mutacje skilli z #N` PR-u, który ostatni zmienił plik zmieniony od bazy, który uruchomił krok (`KrokSkilla.pliki`), najpierw w folderze skilla; część mieści się w limicie czasu także z najdroższymi zmierzonymi mutacjami każdego przebiegu testów. | `tests/test_zadania_ci.py::test_required_czeka_na_kazde_zadanie_runu_a_pull_request_nie_mutuje_zmienionych_linii`, `tests/test_scal_pr.py::test_gotowy_pr_nie_czeka_na_mutacje_zmiany_ani_linie_mutacja_bo_mutacje_biegna_noca_na_main`, `tests/test_plan_ci.py::test_plan_pull_requestu_i_nocy_startuje_mutation_checks_tylko_z_praca_od_zmiany`, `tests/test_zakres_runu.py::test_na_pull_request_biegna_same_podstawy_a_noca_same_skrypty_mutacji` i `::test_na_pull_request_skrypt_mutacji_modelu_biegnie_przy_zmianie_modelu_skryptu_albo_sprawdzenia`, `tests/test_mutacje_nocne.py` (w nim `::test_czesc_z_mutacjami_drozszymi_niz_jej_limit_czasu_nie_zatrzymuje_nocy_a_nastepna_zaczyna_za_nia` i `::test_czesc_konczy_sie_w_limicie_czasu_z_najdrozszymi_zmierzonymi_mutacjami_kazdego_przebiegu`) |
