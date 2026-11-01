# Agent Router

- Worktree: zanim uruchomisz Pythona, utwórz własne `.venv` przez `python3 tools/setup_worktree.py` (Windows: `py -3`); `.venv` głównego checkoutu sprawdza kod `main`.
- Issue N: przed startem uruchom `tools/praca_w_toku.py --issue N`. Gdy issue dotyczy gałęzi otwartego PR albo ktoś ma już na nim commity, poprawka należy do właściciela tej gałęzi: powiedz o tym użytkownikowi i zostaw ją jemu.
- Po każdej zmianie uruchom `.venv/bin/python tools/szybko.py` (Windows: `py -3 tools/szybko.py`), na gałęzi zbudowanej na innej z `--baza <gałąź rodzica>`. Co sprawdza, a co zostawia CI, mówi jego `--help`.
- Kod i testy: zanim napiszesz albo zrecenzujesz kod (także w `tools/`, `frontend/` i skryptach skilli) albo test, przeczytaj [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Model domeny i reguły procesu: przeczytaj [`GLOSSARY.md`](GLOSSARY.md) oraz właściwe ADR-y w [`docs/adr/`](docs/adr/).
- Tytuł i opis PR: napisz według skilla [`.agents/skills/pr/SKILL.md`](.agents/skills/pr/SKILL.md), także zamiast osobistego `/pr`, a gdy wzorowi czegoś brakuje, dopisz to do skilla.
- Przegląd PR: zanim zlecisz przegląd, użyj skilla [`przeglad`](.agents/skills/przeglad/SKILL.md) w trybie autora, a zanim napiszesz werdykt, w trybie recenzenta.
- Skille: przeczytaj [`docs/agents/skille.md`](docs/agents/skille.md) przed pushem i przed utworzeniem albo zmianą skilla.
- Wydajność i środowisko taty: przy pomiarach wydajności albo decyzjach zależnych od jego sprzętu lub OneDrive przeczytaj [`docs/agents/komputer-taty.md`](docs/agents/komputer-taty.md).
- Uruchamianie narzędzia przez człowieka: użyj [`README.md`](README.md).
- Issues i specyfikacje: użyj [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).
- Triage: użyj [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

## Narzędzia

Narzędzie uruchamiasz `.venv/bin/python tools/<nazwa>.py` (Windows: `py -3 tools/<nazwa>.py`), a jego `--help` mówi, jak go użyć.
<!-- spis narzędzi: generuje tests/test_spis_narzedzi.py z ZAPISZ_EXPECT=1, nie edytuj ręcznie -->
- `tools/benchmark_przebiegu.py`: Mierzy czas Przebiegu rozliczeń (measure) na lustrze folderów taty, bez danych klientów; użyj przed i po zmianie wydajności silnika.
- `tools/ci_lokalnie.py`: Odtwarza lokalnie porażkę zadania CI z PR: ruff-mypy, frontend, pytest, mutations; nie plan runu (plan_ci) ani części nocnych mutacji (mutacje_zmiany).
- `tools/mutacje.py`: Dowodzi, że test albo sprawdzenie pada na zepsutym kodzie (mutacji); użyj raz dla każdego testu dodanego albo zmienionego w zmianie.
- `tools/mutacje_nocne.py`: Liczy nocne mutacje na main i zgłasza przeżyte w issue PR-ów; użyj (plan), by bez testów zobaczyć bazę i części najbliższej nocy.
- `tools/mutacje_zmiany.py`: Psuje linie zmienione od bazy jak nocne mutacje main; użyj, gdy część nocnych mutacji padła i odtwarzasz ją na commicie runu (--odtwarzam).
- `tools/na_scalonych_pr.py`: Uruchamia polecenie na commitach scalenia wskazanych PR-ów; użyj, by pokazać, że nowe sprawdzenie łapie błąd bez fałszywego alarmu.
- `tools/plan_ci.py`: Drukuje plan runu CI gałęzi (plan --baza origin/main): zadania pytest i Mutation checks, ich pliki i kroki skilli; użyj przed pushem albo gdy CI biegło inaczej.
- `tools/pomiar_regul_ilosci.py`: Mierzy Reguły ilości na Plikach zbiorczych wypełnionych przez tatę (spec #268); tylko na Macu Maksa, przed zmianą Reguł ilości.
- `tools/porownanie_rozliczen.py`: Porównuje znaczeniowo dwa Foldery rozliczeń pracowników (spec #141); użyj jako bramki, gdy zmiana silnika ma dać te same rozliczenia.
- `tools/praca_w_toku.py`: Pokazuje pracę innych checkoutów i otwartych PR-ów oraz pliki wspólne z bieżącym; użyj przed startem issue i przed aktualizacją z main.
- `tools/quiet_machine.py`: Pokazuje, co trzyma maszynę (--status), i pilnuje jednego pomiaru wydajności naraz na cichym procesorze; użyj, gdy pomiar czeka.
- `tools/rownowaznosc.py`: Sprawdza, że refaktor nie zmienia wyniku procesów: te same scenariusze syntetyczne na bazie i na HEAD; użyj przy refaktorze src/.
- `tools/scal_pr.py`: Jedyna droga merge'a PR przez agenta: sprawdza gotowość (CI, werdykt PASS, opis) tuż przed gh pr merge; użyj zamiast gołego merge'a.
- `tools/setup_worktree.py`: Tworzy własne .venv checkoutu albo worktree z dodatkiem dev; uruchom w nowym worktree przed pierwszym poleceniem Pythona.
- `tools/skille_dla_zmiany.py`: Wypisuje skille verify-*, które obowiązują dla zmiany od bazy, każdy z powodem; użyj przed pushem i przed oceną gotowości PR.
- `tools/sprzatanie.py`: Raportuje, a z --usun usuwa worktree i gałęzie, których praca jest już w origin/main; użyj po merge'u albo gdy worktree się mnożą.
- `tools/syntetyczne_wzorce.py`: Zapisuje syntetyczne Wzorce w kształcie Wzorców taty; użyj, gdy benchmark, weryfikacja w Excelu albo CI nie ma prawdziwych Wzorców.
- `tools/szybko.py`: Szybko sprawdza zmianę: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą; uruchom po każdej zmianie przed pushem.
- `tools/uruchom_proces.py`: Jedno Uruchomienie procesu (settlement, preparation, intermax, efenix) z wynikiem JSON; użyj w E2E, benchmarku i skillach zamiast Centrum rozliczeń.
- `tools/wydanie.py`: Narzędzie Wydań (plan, potem wydaj): nowa wersja z tagiem v* i GitHub Release (ADR 0014); uruchamiaj tylko z workflow skilla wydanie.
- `tools/wyrocznia_zgody.py`: Sprawdza, czy zainstalowany Claude Code oddaje hookowi zgoda.py pytanie o zgodę na rm; uruchom po każdej aktualizacji Claude Code.
<!-- koniec spisu narzędzi -->

## PR: od pushu do merge'a

- Dziecko `delegate_task` kończy zadanie na pushu i utworzeniu PR, a zwraca URL PR i pełny SHA HEAD. Rodzic wywołuje `watch_pull_request` i kończy turę, a T3 budzi go po końcu CI.
- Przegląd PR zlecaj zaraz po pushu, równolegle z CI.
- PR jest gotowy do merge'a, gdy na HEAD PR zielony jest `Required CI status` (i każdy inny workflow niż `CI`, który biegnie na PR), przeszły skille `verify-*` z linii `SKILLE VERIFY` narzędzia `tools/skille_dla_zmiany.py` i jest `PASS` niezależnego recenzenta.
  Skille `verify-*` przeszły, gdy ich polecenia z linii `LICZY CI` przechodzą w zielonym CI, a resztę ich workflow agent wykonał i skończył bez FAIL.
  Skryptów z linii `LICZY NOC` agent nie uruchamia: liczy je noc na `main` po merge'u, a ich porażka trafia do issue PR-u (ADR 0021).
  `SZYBKO OK` i `CI LOKALNIE OK` gotowości nie dają.
- Mutacje zmienionych linii biegną nocą na `main` (ADR 0021), a każda przeżyta trafia do issue `Przeżyte mutacje z #N` (`ready-for-agent`) PR-u, który ostatni zmienił jej linię.
- Merge PR: tylko `.venv/bin/python tools/scal_pr.py N` (Windows: `py -3 tools/scal_pr.py N`), nigdy gołe `gh pr merge`; warunki scalenia i postać werdyktów podaje jego `--help`. Zgoda to komentarz albo recenzja niezależnego recenzenta, której pierwsza linia to `WERDYKT: PASS <pełny SHA HEAD>`.
- CI i gałąź: przeczytaj [`docs/agents/pr-i-ci.md`](docs/agents/pr-i-ci.md), zanim uruchomisz lokalnie zadanie CI albo zrobisz rebase lub merge `main` do gałęzi, i gdy zadanie CI padło, status `scalenie z main` nie jest zielony, `main` jest czerwony albo chcesz sprawdzić każdy commit gałęzi.

## Reguły i co ich pilnuje

Gdy operator Cię poprawi, dopisz regułę z jej strażnikiem do tabeli, do której należy: regułę o tym, jak pisać kod i testy, do tabeli jej sekcji w [`CODING_STANDARDS.md`](CODING_STANDARDS.md) (po angielsku), regułę procesu gałęzi z [`docs/agents/pr-i-ci.md`](docs/agents/pr-i-ci.md) albo [`docs/agents/skille.md`](docs/agents/skille.md) do tabeli tego pliku, a pozostałą regułę procesu do tabeli niżej.
Jeśli reguła już tam była, a nic jej nie pilnowało, to błąd się powtórzył: w tej samej zmianie dodaj sprawdzenie, które go łapie.
Wyjątek zapisz na linii, której dotyczy, z powodem, terminem i zgodą Maksa (wzór: `KNOWN` w `tests/test_uszkodzone_wejscia.py`).
Szczegóły strażnika, jego wyjątki i granicę (co łapie tylko przegląd) opisuje jego docstring.

| Reguła | Co jej pilnuje |
|---|---|
| Push agenta, który wysyła HEAD, przechodzi tylko wtedy, gdy ruff i mypy dla obu systemów nie zgłaszają błędów w drzewie roboczym. | brama `tools/hooks/pre-push`, `tests/test_brama_pre_push.py` |
| Tag Wydania `v*` i GitHub Release tworzy tylko narzędzie Wydań (#316), które ustawia `MAXIMISEART_WYDANIE=1` (ADR 0014), a agent nie robi tego ani `git push`, także z `--no-verify`, ani `gh release create`, `gh api` czy stroną GitHuba. | brama `tools/hooks/pre-push`, `tests/test_brama_pre_push.py` |
| Opis PR ma każdy nagłówek `##` wzoru ze skilla `pr`, w jego kolejności. | `tools/scal_pr.py`, `tests/test_scal_pr.py` |
| Na własny proces agent czeka na powiadomienie `run_in_background`, a na CI rodzic przez `watch_pull_request`. | hook `PreToolUse` `tools/hooks/czekanie.py` (`.claude/settings.json`), `tests/test_czekanie.py` |
| Agent w trybie bypass nie czeka na zgodę człowieka na polecenie Basha: gdy Claude Code by o nią zapytał (kontrola `rm`, której nie zdejmuje `permissions.allow`, albo reguła `permissions.ask`), od razu oddaje mu odmowę z poprawką, którą podaje komunikat hooka; po aktualizacji Claude Code uruchom `tools/wyrocznia_zgody.py`. | hook `PermissionRequest` `tools/hooks/zgoda.py` (`.claude/settings.json`), `tests/test_zgoda.py` |
| Issue tego repozytorium, które opis PR wskazuje jako naprawione, zamyka się przy merge'u PR do domyślnej gałęzi, nie ręcznie: `Closes #N` zamyka GitHub, a słowa „Naprawia” GitHub nie zna, więc `tools/scal_pr.py` renderuje opis rendererem GitHuba i zamyka z komentarzem o PR i commicie merge'a issues z linków na liście numerów po „Naprawia”, które zaczyna linię akapitu albo punktu listy stojącego tylko w akapitach i listach, poza kodem i przekreśleniem, a odwołania do innego repozytorium (Zgłoszenia) zostawia. | `tools/scal_pr.py`, `tests/test_scal_pr.py` |
| Niestabilny test trafia do kwarantanny tylko wpisem w `KWARANTANNA` (`tests/fixtures/kwarantanna.py`) z numerem issue `Flaky test: <test>` i terminem najwyżej 7 dni od dziś, a wpis wygasły czerwieni CI; Maks zgodził się na takie wpisy z góry (ADR 0020), więc nie potrzebują osobnej zgody. | `tests/test_kwarantanna.py` |
| Repozytorium mówi po angielsku „flaky test” („flaky testy” w polskim zdaniu), także w nazwach zadań CI oraz tytule i etykiecie issue, które zakłada CI, i nigdy nie używa spolszczonej formy tego słowa; wyjątek mają tylko dane historyczne. | `tests/test_slowo_flaky_test.py` |
| W `AGENTS.md`, `CODING_STANDARDS.md`, `docs/agents/pr-i-ci.md` i `docs/agents/skille.md` łam linię prozy tylko na końcu zdania, żeby zmiana słowa zmieniała jedną linię, a nie cały akapit. | `tests/test_dokumenty_regul.py` |
