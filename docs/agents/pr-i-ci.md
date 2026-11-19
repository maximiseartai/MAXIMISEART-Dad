# CI na PR

Kiedy PR jest gotowy i jak go scalić, mówi `tools/scal_pr.py --help`.
Dlaczego PR dostaje mniej sprawdzeń niż `main`, mówi [ADR 0020](../adr/0020-ci-w-poziomach.md).

## Co biegnie na PR

- Co biegnie na swojej gałęzi, drukuje `tools/plan_ci.py plan --baza origin/main`.
  Linia `PLAN CI` podaje źródło plików (`wybór <n> plików` albo `FULL (<pliki>)`), a linie `WYBRANY` i `POMINIĘTY` kroki skilli z powodem.
- Podstawa `ci:` skilla biegnie na PR tylko wtedy, gdy PR zmienia folder skilla (ADR 0020, D1): przy zmianie tylko w `pilnuje:` linia `POMINIĘTY` mówi `biegnie na main: PR nie zmienia folderu skilla`, a `tools/skille_dla_zmiany.py` wymienia ją w `LICZY MAIN`; lokalnie jej nie uruchamiasz.
  Linia `CIEŃ PODSTAW` podaje ścianę i zadania wariantów V0, NF i N0, a rozstrzygnięcie D1 (#2169) liczy po 14 dniach `tools/cien_podstaw.py`.
- Do bramki PR dokładasz tylko to, co złapałoby defekt, który przez nią przeszedł, z dowodem z backtestu.
- Bramka ma budżet p90 ≤ 5 min od pushu do `Required CI status` (ADR 0020, D2): przekroczenie otwiera issue z etykietą `budzet-ci`, które nazywa wąskie gardło, a stan budżetu na dziś bez zapisu na GitHubie drukuje `tools/budzet_ci.py --katalog <folder> --bez-zapisu`.
- Linię `SZOPA` i etykietę `powiększa maszynerię procesu` z workflow `Rozmiar PR` opisuje `OPIS` `tools/ci/rozmiar_pr.py` (jego `--help`): etykieta tylko informuje recenzenta i nie wstrzymuje merge'u, a przeniesienie pliku między grupami (licznik liczy ścieżki) recenzent ocenia z liczb obu grup w linii `SZOPA`.
- pytest na Windows biegnie w CI, na PR i na `main`, tylko na Pythonie taty (3.13) i na tym torze biegną E2E i straż czasu; pytest na Pythonie 3.14 biegnie tylko na Linuksie (ADR 0020, Z2).

## Zadanie CI padło

- Run CI ponawiasz tylko przez `tools/ponow_ci.py N`, a run `main` przez `--run ID`; co ponawia, a co odrzuca z poleceniem odtworzenia, mówi jego `--help`.
  Po limicie ponowień, gdy awaria minie, nowy run na tym samym HEAD dają `gh pr close N` i `gh pr reopen N`, a nie push, który unieważnia werdykt.
- Porażkę zadania odtwarzasz przez `tools/ci_lokalnie.py --tylko <zadanie>`.
- Linia `LIMIT | krok:pytest` znaczy, że krok pytest przekroczył swój limit z planu (`limit_pytest_s` w `tools/lib/plan_runu.py`), czyli coś się zawiesiło: test, który wisiał, zostawił wyżej w logu stosy swoich wątków pod `Timeout (0:02:30)!` (`faulthandler_timeout` w `pyproject.toml`), a zawieszenie przy imporcie albo zbieraniu testów stosów nie zostawia.
- `worker 'gwN' crashed while running '<test>'` z linią `LIMIT TESTU | <s> s pytest-timeout: <test>` wyżej w logu znaczy, że test przekroczył swój limit pytest-timeout (`timeout` w `pyproject.toml` albo `@pytest.mark.timeout`), a pod tą linią stoją stosy wątków workera z chwili limitu (`tests/fixtures/limit_testu_w_workerze.py`); bez tej linii worker zginął z innej przyczyny.
- Ciężkie zadania liczy GitHub w częściach: `mutations` po pushu, z samymi podstawami `ci:` skilli (stan pokazuje `gh pr checks`), a `change-mutations` i skrypty mutacji skilli tylko nocą na `main`, poza skryptem mutacji modelu TLA+, który biegnie też na PR zmieniającym model, jego skrypt albo sprawdzenie (ADR 0021).
  Część skryptu mutacji albo podstawy z planu (`#k/n` w nazwie jednostki) odtwarzasz przez `MUTACJE_CZESC=k/n` w środowisku polecenia tego skryptu albo polecenia `ci:`.
  Nocne `change-mutations` mutują zmienione linie `src/` i tylko tych jednostek `tools/`, które `tools/lib/szopa.toml` stawia w podtabeli `przepuszcza`, bo ich fałszywe „OK” przepuszcza zły kod produktu (audyty #1623 i #1624).

## Status `Werdykt i bramka`

- Run workflow `Werdykt i bramka` w stanie `cancelled` to nie porażka: `cancel-in-progress` w `werdykt-i-bramka.yml` anuluje starszy run PR, gdy przychodzi nowsze zdarzenie (komentarz, edycja opisu, koniec runu CI), a `gh pr checks` i powiadomienie „Checks failed” pokazują taki run jako `fail`.
  O gotowości mówi status commita `Werdykt i bramka` na HEAD: `pending` czeka na CI albo werdykt, a opis `failure` zaczyna się od przyczyny, która wymaga działania autora (pełne przyczyny podaje linia `STATUS` w logu runu z `target_url` statusu).
- Status w kolejce po zielonym CI i `PASS` to linia `SCAL CZEKA` z `tools/scal_pr.py N`: obserwuj PR, a nie ponawiaj merge'a w pętli.

## Status `scalenie z main`

- Status (`tools/ci/status_scalenia.py`) mówi w opisie, co zrobić, a ruleset go nie wymaga, więc gotowość PR od niego nie zależy, choć `gh pr checks` kończy się kodem 1, gdy jest czerwony.
- Brak statusu znaczy, że `main` nie zmienił się od pushu PR, przebieg jeszcze trwa albo padł job „Statusy scalenia z main” w `werdykt-i-bramka.yml`, który ustawia werdykty z artefaktu `scalenia.yml`.

## Czerwony `main`

- Czerwony `main` nie blokuje merge'ów, a naprawia go od razu osobny PR.
  PR, nad którym pracujesz, zostaje przy swojej zmianie.
  PR naprawy wskazuje issue czerwonego `main` linią `Część #N` (zamyka je następny zielony `main`) i ma sekcję `## Korzeń` według skilla [`pr`](../../.agents/skills/pr/SKILL.md), a PR flaky testu wskazuje issue `Flaky test:` i sekcji nie ma.
- O merge'u rozstrzyga pierwszy nieanulowany run CI pushu na `main`, którego commit zawiera merge: nowszy push anuluje run, który czeka za trwającym (ADR 0020).
  Kiedy kończysz obserwację scalonego PR, mówi linia `CI MAIN` z `tools/scal_pr.py` i jego `--help`.

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Trwający run `main` kończy się, a nowy push do PR anuluje run jego starszego commitu. | `tests/test_zadania_ci.py::test_push_do_main_nie_anuluje_trwajacego_runu_a_nowy_push_pr_anuluje_stary` |
| `Required CI status` biegnie także w anulowanym runie, bo pominięty wymagany check przepuszcza merge. | `tests/test_zadania_ci.py::test_required_biegnie_takze_w_anulowanym_runie_bo_pominiety_wymagany_check_przepuszcza_merge` |
