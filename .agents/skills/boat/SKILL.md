---
name: boat
description: Ciężkie polecenie - na Macu albo na boxie boat (`boatbox`), także rozbite na kilka boxów. Użyj przed `szybko.py`, `mutacje.py --plik`, pełnym pytestem i innym poleceniem dłuższym niż minuta na Macu, oraz gdy test pada tylko na boxie.
---

# Boat

Box boat to kopia worktree w tym, co widzi git: ten sam HEAD, ten sam `origin/main` oraz te same niezacommitowane i nieśledzone pliki, więc narzędzia repo dają na nim ten sam wynik.
Pliki ignorowane przez git (`.venv`, `node_modules`, `config/`) na box nie trafiają, a pliki zapisane na boxie wracają do worktree tylko przez `boatbox get`.
Edycja, git i agenci zostają na Macu, a mechanikę (`run`, `auto`, `job`, `wait`, `log`, `fan`, `get`, `stop`, sloty równoległych agentów) opisuje `boatbox help`.
Bez `boatbox` w `PATH` (inna maszyna niż Mac Maksa) uruchamiaj wszystko lokalnie.

## Gdzie biegnie polecenie

| Praca | Gdzie | Jak |
|---|---|---|
| `mutacje.py --plik` z mutacjami o kilku różnych `polecenie` | kilka boxów naraz, bo razem są szybsze od Maca | `boatbox fan` (sekcja „Fan mutacji”) |
| Pełny pytest | jeden box, bo na Macu zajmuje wszystkie rdzenie na kilka minut | `boatbox job pytest '.venv/bin/python -m pytest -n auto'`, potem `boatbox wait pytest` |
| `szybko.py`, `mutacje.py --plik` z jednym `polecenie` | Mac w wolnym slocie, a bez wolnego slotu box (sekcja „Budżet”) | `boatbox auto '<polecenie>'`, a `szybko.py` jak niżej |
| Odtworzenie błędu na Linuksie, powtórzenia testu pod obciążeniem, pomiar, model TLC | box | `boatbox run` albo `boatbox job` |
| Pojedynczy plik testów, `mutacje.py --zmiana`, ruff, mypy, budowa frontendu, git, `gh`, `tools/scal_pr.py` | Mac, bo to lekkie polecenia (`npm ci` z `npm run build` trwają kilka sekund) | bezpośrednio |
| Excel, napęd Centrum z oknem przeglądarki, prawdziwe pliki taty, pomiar `benchmark_przebiegu.py measure` na Macu | Mac w slocie, a przy zajętych slotach kolejka na slot | `boatbox run --here '<polecenie>'` |
| Nocne mutacje (`mutacje_nocne.py`, `mutacje_zmiany.py`) | GitHub Actions | workflow `mutacje-nocne.yml` |

`szybko.py` uruchamiaj tak: `boatbox auto --box-env PYTEST_XDIST_AUTO_NUM_WORKERS=8 '.venv/bin/python tools/szybko.py'`.
Box `large` ma 8 vCPU, a Mac zostaje przy 4 workerach z `czasy_ci.WORKERY_LOKALNE`, więc liczbę workerów boxa podaje tylko `--box-env`.
W pomiarze A/B obie strony biegną po kolei na tym samym boxie.
Hook `tools/hooks/ciezkie.py` odmawia polecenia z tej tabeli, które biegłoby na Macu bez `boatbox`, i podaje gotowe polecenie `boatbox`; które polecenia łapie, a które przepuszcza, mówi jego docstring.

## Base

Box powstaje z base snapshotu repozytorium, który ma `.venv` z Pythonem 3.14 i Chromium dla Playwright.
Gdy `boatbox status` pokazuje `base: none`, zbuduj base tym poleceniem, bo bez `--setup` boatbox w tym repo nie instaluje niczego (w korzeniu nie ma pliku blokady):

```bash
boatbox base --setup 'python3 tools/setup_worktree.py --python 3.14 && .venv/bin/python -m playwright install --with-deps chromium'
```

Gdy sync pisze `a lockfile differs from the base`, a `pyproject.toml` zmienia twoja gałąź, poprzedź polecenie przez `python3 tools/setup_worktree.py --python 3.14 && `.
Gdy ta zmiana jest już na `origin/main`, uruchom `boatbox base` bez `--setup`, bo powtarza polecenie poprzedniego base.

## Fan mutacji

Zestaw mutacji dziel na najwyżej 12 części, bo plan boat daje 12 startów boxa na minutę, a mutacje o tym samym `polecenie` trzymaj w jednej części:

```bash
jq -c '[group_by(.polecenie | tostring) | to_entries[] | {k: (.key % 12), v: .value}] | group_by(.k)[] | map(.v[])' mutacje.json \
  | awk '{f = "mutacje-fan-" NR ".json"; print > f; print ".venv/bin/python tools/mutacje.py --rownolegle --plik " f}' \
  | boatbox fan
rm mutacje-fan-*.json
```

Mutacje bez klucza `polecenie` biorą polecenie po `--`, więc wtedy dopisz `-- <polecenie>` na końcu linii w `awk`.
Pliki części leżą w korzeniu worktree, bo `boatbox` wysyła na box tylko pliki, które widzi git.

## Budżet

Plan boat liczy starty boxa w oknach minuty, godziny i doby (`boat limits --json`) oraz godziny maszyn, z których na każdy dzień przypada tylko część, a box `large` zużywa je podwójnie.
Start to każde utworzenie i wznowienie boxa oraz każda część `fan` uruchomiona równolegle.
Mac ma sloty na ciężkie polecenia, wspólne dla wszystkich repozytoriów i wątków: `BOATBOX_MAC_SLOTS`, domyślnie liczba rdzeni / 4 − 1, bo ciężkie polecenie bierze około 4 rdzeni, a resztę potrzebują agenci, Chrome i T3.
`boatbox auto` i `boatbox run --here` zajmują slot na cały bieg polecenia blokadą pliku w jądrze, więc dwa równoczesne starty nie dostaną tego samego slotu, a slot zabitego polecenia zwalnia się sam.
Decyzja zapada przy starcie, nie po obciążeniu z `uptime`, które nie nadąża za kilkoma startami naraz.
Bez wolnego slotu `boatbox auto` od razu wysyła polecenie na box, także po przekroczeniu tempa godzin (linia `over pace:` w `boatbox status`), bo zatkany Mac kosztuje wątki agentów więcej niż godziny planu (decyzja Maksa 16.11.2026).
Bez wolnego slotu i bez startu boxa (budżet doby albo godziny, box nie wstaje) polecenie czeka w kolejce na slot i co 30 s pisze linię stanu, więc na Macu nigdy nie biegnie więcej ciężkich poleceń niż slotów.
Zajęte sloty, ich polecenia i czas pokazuje `boatbox status`, a zachowanie `fan` przy małej liczbie startów opisuje `boatbox help`.

## Dane

Prawdziwe pliki taty, pliki z `config/`, tokeny i treść skrzynki trzymaj poza worktree albo w ścieżkach ignorowanych przez git, bo na box trafia każdy nieignorowany plik, także nieśledzony.
Testom na boxie dawaj atrapy i dane syntetyczne.

## Test pada tylko na boxie

Uruchom go lokalnie, zanim cokolwiek poprawisz.
Pada też lokalnie: to błąd zmiany.
Przechodzi lokalnie: sprawdź, czy box ma twój HEAD (`boatbox status` pokazuje `head` boxa), a potem szukaj różnicy środowiska (Linux zamiast macOS, 8 vCPU, sygnały, base starszy niż `pyproject.toml`) i zapisz ją w tym skillu.
