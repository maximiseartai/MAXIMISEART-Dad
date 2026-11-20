---
name: boat
description: Ciężkie polecenie biegnie na boxie boat (`boatbox`), także rozbite na kilka boxów. Użyj przed `szybko.py`, pełnym pytestem, `mutacje.py --plik` i każdym poleceniem, które na Macu trwałoby ponad minutę, oraz gdy test pada tylko na boxie albo z komunikatem `BOX:`.
---

# Boat

Box boat to kopia worktree w tym, co widzi git: ten sam HEAD, ten sam `origin/main` oraz te same niezacommitowane i nieśledzone pliki, więc narzędzia repo dają na nim ten sam wynik.
Pliki ignorowane przez git (`.venv`, `node_modules`, `config/`) na box nie trafiają, a pliki zapisane na boxie wracają do worktree tylko przez `boatbox get`.
Edycja, git i agenci zostają na Macu, a obliczenia idą na box; mechanikę (`run`, `job`, `wait`, `log`, `fan`, `get`, `stop`, sloty równoległych agentów) opisuje `boatbox help`.
Bez `boatbox` w `PATH` (inna maszyna niż Mac Maksa) uruchamiaj wszystko lokalnie.

## Gdzie biegnie polecenie

Polecenie jest **ciężkie**, gdy na Macu trwałoby ponad minutę albo zajmuje kilka rdzeni naraz, oraz gdy uruchamia kod z zewnątrz.
Ciężkie polecenie biegnie zawsze na boxie, także wiele naraz i równolegle, każda część, którą da się rozdzielić, na własnym boxie; Mac zostaje dla edycji, gita i agentów.

| Praca | Jak |
|---|---|
| `szybko.py` | `boatbox run 'PYTEST_XDIST_AUTO_NUM_WORKERS=8 .venv/bin/python tools/szybko.py'` (box `large` ma 8 vCPU) |
| Pełny pytest | `boatbox job pytest '.venv/bin/python -m pytest -n auto'`, potem `boatbox wait pytest` |
| `mutacje.py --plik` z mutacjami o kilku różnych `polecenie` | `boatbox fan` (sekcja „Fan mutacji”) |
| `mutacje.py --plik` z jednym `polecenie`, odtworzenie błędu na Linuksie, powtórzenia testu pod obciążeniem, pomiar, model TLC, kod z zewnątrz (nowa zależność, cudzy PR) | `boatbox run '<polecenie>'`, a przy biegu ponad 5 minut `boatbox job` i `boatbox wait` |
| Lekkie: pojedynczy plik testów, `mutacje.py --zmiana`, ruff, mypy, budowa frontendu, git, `gh`, `tools/scal_pr.py` | na Macu, bezpośrednio |
| Excel, napęd Centrum z oknem przeglądarki, prawdziwe pliki taty, test, który działa tylko na macOS | na Macu: `boatbox run --here '<polecenie>'` |
| Nocne mutacje (`mutacje_nocne.py`, `mutacje_zmiany.py`) | GitHub Actions, workflow `mutacje-nocne.yml` |

W pomiarze A/B obie strony biegną po kolei na tym samym boxie.

## Gdy box nie wstaje

- `missing command: boat`: zgłoś to Maksowi, bo instalacja i logowanie boat to jego krok.
- `no_ready_machine` albo inny brak maszyn: ponów raz po minucie, potem z `BOATBOX_TYPE=default`; gdy i to nie wstaje, zgłoś polecenie i błąd, a polecenie zostaw na boxie.
- Wynik wygląda na stary kod: porównaj `head` boxa z `boatbox status` z `git rev-parse HEAD`.

## Base

Box powstaje z base snapshotu repozytorium, który ma `.venv` z Pythonem 3.14 i Chromium dla Playwright.
Gdy `boatbox status` pokazuje `base: none`, zbuduj base tym poleceniem, bo bez `--setup` boatbox w tym repo nie instaluje niczego (w korzeniu nie ma pliku blokady):

```bash
boatbox base --setup 'python3 tools/setup_worktree.py --python 3.14 && .venv/bin/python -m playwright install --with-deps chromium'
```

Gdy sync pisze `a lockfile differs from the base`, a `pyproject.toml` zmienia twoja gałąź, poprzedź polecenie przez `python3 tools/setup_worktree.py --python 3.14 && `.
Gdy ta zmiana jest już na `origin/main`, uruchom `boatbox base` bez `--setup`, bo powtarza polecenie poprzedniego base.

## Fan mutacji

Zestaw mutacji dziel na części (w przykładzie 12), a mutacje o tym samym `polecenie` trzymaj w jednej części:

```bash
jq -c '[group_by(.polecenie | tostring) | to_entries[] | {k: (.key % 12), v: .value}] | group_by(.k)[] | map(.v[])' mutacje.json \
  | awk '{f = "mutacje-fan-" NR ".json"; print > f; print ".venv/bin/python tools/mutacje.py --rownolegle --plik " f}' \
  | boatbox fan
rm mutacje-fan-*.json
```

Mutacje bez klucza `polecenie` biorą polecenie po `--`, więc wtedy dopisz `-- <polecenie>` na końcu linii w `awk`.
Pliki części leżą w korzeniu worktree, bo `boatbox` wysyła na box tylko pliki, które widzi git.

## Dane

Prawdziwe pliki taty, pliki z `config/`, tokeny i treść skrzynki trzymaj poza worktree albo w ścieżkach ignorowanych przez git, bo na box trafia każdy nieignorowany plik, także nieśledzony.
Testom na boxie dawaj atrapy i dane syntetyczne.

## Komunikat `BOX:` i `SZYBKO INFRA`

Komunikat `BOX: boat przeniósł katalog repo w trakcie biegu; to nie test, powtórz bieg`, linia `SZYBKO INFRA` z kodem 75 i log `boatbox job` zakończony `FAIL rc=75` znaczą, że box podmienił dysk pod biegnącym poleceniem: powtórz ten sam bieg bez zmian w kodzie.
Przyczynę i granice tego rozpoznania opisuje [`przeniesienie.md`](przeniesienie.md).

## Test pada tylko na boxie

Uruchom go lokalnie, zanim cokolwiek poprawisz.
Pada też lokalnie: to błąd zmiany.
Przechodzi lokalnie: sprawdź, czy box ma twój HEAD (`boatbox status` pokazuje `head` boxa), a potem szukaj różnicy środowiska (Linux zamiast macOS, 8 vCPU, sygnały, base starszy niż `pyproject.toml`) i zapisz ją w tym skillu.
Zmiana we `frontend/` daje na boxie `ScanFailed: brak oxlint z zależności frontendu` w `tests/test_komentarze_frontendu.py`, bo `node_modules` na box nie trafia: poprzedź polecenie przez `(cd frontend && npm ci --no-audit --no-fund) && `.
