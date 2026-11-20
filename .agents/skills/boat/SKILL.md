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

Każde ciężkie polecenie i każdą jego część, którą da się rozdzielić, puszczaj przez `boatbox`, także wiele razy i równolegle.

| Praca | Gdzie | Jak |
|---|---|---|
| `mutacje.py --plik` z mutacjami o kilku różnych `polecenie` | kilka boxów naraz, bo razem są szybsze od Maca | `boatbox fan` (sekcja „Fan mutacji”) |
| Pełny pytest | jeden box, bo na Macu zajmuje wszystkie rdzenie na kilka minut | `boatbox job pytest '.venv/bin/python -m pytest -n auto'`, potem `boatbox wait pytest` |
| `szybko.py`, `mutacje.py --plik` z jednym `polecenie` | Mac w wolnym slocie, a bez wolnego slotu box (sekcja „Sloty Maca”) | `boatbox auto '<polecenie>'`, a `szybko.py` jak niżej |
| Odtworzenie błędu na Linuksie, powtórzenia testu pod obciążeniem, pomiar, model TLC | box | `boatbox run` albo `boatbox job` |
| Pojedynczy plik testów, `mutacje.py --zmiana`, ruff, mypy, budowa frontendu, git, `gh`, `tools/scal_pr.py` | Mac, bo to lekkie polecenia (`npm ci` z `npm run build` trwają kilka sekund) | bezpośrednio |
| Excel, napęd Centrum z oknem przeglądarki, prawdziwe pliki taty, pomiar `benchmark_przebiegu.py measure` na Macu | Mac w slocie, a przy zajętych slotach kolejka na slot | `boatbox run --here '<polecenie>'` |
| Nocne mutacje (`mutacje_nocne.py`, `mutacje_zmiany.py`) | GitHub Actions | workflow `mutacje-nocne.yml` |

`szybko.py` uruchamiaj tak: `boatbox auto --box-env PYTEST_XDIST_AUTO_NUM_WORKERS=8 '.venv/bin/python tools/szybko.py'`.
Box `large` ma 8 vCPU, a Mac zostaje przy 4 workerach z `czasy_ci.WORKERY_LOKALNE`, więc liczbę workerów boxa podaje tylko `--box-env`.
W pomiarze A/B obie strony biegną po kolei na tym samym boxie.

## Sloty Maca

Mac ma sloty na ciężkie polecenia, wspólne dla wszystkich repozytoriów i wątków: `BOATBOX_MAC_SLOTS`, domyślnie liczba rdzeni / 4 − 1, bo ciężkie polecenie bierze około 4 rdzeni, a resztę potrzebują agenci, Chrome i T3.
`boatbox auto` i `boatbox run --here` zajmują slot na cały bieg polecenia blokadą pliku w jądrze i dają mu jego numer w `BOATBOX_MAC_SLOT`, więc dwa równoczesne starty nie dostaną tego samego slotu, a slot zabitego polecenia zwalnia się sam.
Decyzja zapada przy starcie, nie po obciążeniu z `uptime`, które nie nadąża za kilkoma startami naraz.
Bez wolnego slotu `boatbox auto` od razu wysyła polecenie na box, a gdy box nie może wystartować, polecenie czeka w kolejce na slot i co 30 s pisze linię stanu, więc na Macu nigdy nie biegnie więcej ciężkich poleceń niż slotów.
`szybko.py`, `mutacje.py --plik`, `benchmark_przebiegu.py measure|freeze` i `ci_lokalnie.py` z zadaniem `pytest` albo `mutations` same biorą slot Maca przy starcie (`tools/lib/slot_maca.py`), gdy `boatbox` jest w `PATH`, a polecenie nie biegnie już w slocie `boatbox` (`BOATBOX_MAC_SLOT`) ani w sesji pytest (`PYTEST_VERSION`, więc narzędzie uruchomione przez test nie czeka); sam pytest bramki nie ma, więc pełny pytest uruchamiaj przez `boatbox job` jak w tabeli wyżej.
Bez wolnego slotu czekają w kolejce na slot jak `boatbox` i co 30 s piszą linię `CIĘŻKIE … Mac zajęty` z gotowym poleceniem `boatbox`, które pośle je na box bez czekania; kodu wyjścia bramka nie zmienia.
Zajęte sloty, ich polecenia i czas pokazuje `boatbox status`.

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

## Katalog repo przeniesiony w trakcie biegu

Box ze snapshotu albo po wznowieniu z dysku podaje `/home/user` z montowania FUSE ładowanego leniwie (lazyfs, `/var/lib/ascii-lazy/`).
Po załadowaniu (`HYDRATION-DONE` w `/var/lib/ascii-lazy/daemon.out`) lazyfs w pierwszej przerwie w odczytach podstawia prawdziwy dysk, a stare drzewo przenosi pod `/var/lib/ascii-lazy/retired/` (linia `retired /home/user ->` w tym samym pliku; 19.11.2026 w 16–29 s od startu boxa).
Polecenie, które już biegło w katalogu repo, ma wtedy katalog roboczy pod tą ścieżką, więc każdy worker pytest pada raz z komunikatem `BOX: boat przeniósł katalog repo w trakcie biegu; to nie test, powtórz bieg`.
To nie wygaśnięcie `BOATBOX_IDLE_MIN`: w każdym sprawdzonym takim biegu 19.11.2026 box był świeżo utworzony albo wznowiony, jego `hydratedAt` z `boat info <id> --json` wypadł w trakcie biegu, a następny bieg na tym samym boxie przeszedł.
Wznowienie nie zawsze ładuje dysk od nowa, a `hydrated` w `boat info` zostaje wtedy `true` z poprzedniego ładowania, więc o tym, czy box jeszcze ładuje dysk, mówi tylko sam box: `findmnt -n -o FSTYPE --mountpoint "$HOME"` daje wtedy typ `fuse…`.
Box wyjaśnia tylko katalog roboczy, który jest dokładnie oczekiwanym katalogiem po przeniesieniu (`box_boat.przeniesienie`): podkatalog, do którego test wszedł sam, inny stan zostawiony w tym samym teście (zmienna, plik, wątek) i błąd teardownu dalej są porażką testu.
Sesja pytest, której każda porażka to sam komunikat boxa, kończy się kodem 75 (`KOD_WYJSCIA` z `tools/lib/box_boat.py`, który rozstrzyga wszystkie trzy granice), a inna porażka obok, także porażka całej sesji jak `DRZEWO REPO`, daje kod 1.
`szybko.py` kończy linią `SZYBKO INFRA` i kodem 75 bieg, w którym każdy krok, który padł, to pytest z kodem 75: powtórz go bez zmian w kodzie.
Pełny pytest z kodem 75 (`boatbox job` kończy log `FAIL rc=75`) też powtórz.

## Test pada tylko na boxie

Uruchom go lokalnie, zanim cokolwiek poprawisz.
Pada też lokalnie: to błąd zmiany.
Przechodzi lokalnie: sprawdź, czy box ma twój HEAD (`boatbox status` pokazuje `head` boxa), a potem szukaj różnicy środowiska (Linux zamiast macOS, 8 vCPU, sygnały, base starszy niż `pyproject.toml`) i zapisz ją w tym skillu.
