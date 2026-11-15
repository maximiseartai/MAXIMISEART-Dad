---
name: boat
description: Gdzie biegnie ciężkie polecenie w tym repozytorium - na Macu albo na boxie boat przez `boatbox` - i kiedy rozbić je na kilka boxów. Użyj przed `szybko.py`, `mutacje.py --plik`, pełnym pytestem, budową frontendu i każdym innym poleceniem, które obciąży Maca dłużej niż minutę, oraz gdy test pada tylko na boxie.
---

# Boat

Mac Maksa ma 16 rdzeni i dzieli je między równoległe wątki agentów.
Box boat to kopia worktree: ten sam HEAD, ten sam `origin/main` i te same niezacommitowane pliki, więc narzędzia repo dają na nim ten sam wynik.
Edycja, git, `gh` i agenci zostają na Macu, a mechanikę (`run`, `auto`, `job`, `wait`, `log`, `fan`, `get`, `stop`) opisuje `boatbox help`.
Bez `boatbox` w `PATH` (inna maszyna niż Mac Maksa) uruchamiaj wszystko lokalnie.

## Gdzie biegnie polecenie

| Praca | Gdzie | Jak |
|---|---|---|
| Duży bieg, który dzieli się na niezależne części: `mutacje.py --plik` z kilkoma różnymi `polecenie` | kilka boxów naraz, bo razem są szybsze od Maca | `boatbox fan`, jedna część na linię (niżej) |
| Pełny pytest | jeden box, bo lokalnie zajmuje wszystkie rdzenie na kilka minut | `boatbox job pytest '.venv/bin/python -m pytest -n auto'`, potem `boatbox wait pytest` |
| `szybko.py`, `mutacje.py --plik` z jednym `polecenie`, budowa frontendu | Mac, gdy ma wolne rdzenie, a box, gdy Mac jest wąskim gardłem | `boatbox auto '<polecenie>'` |
| Odtworzenie błędu na Linuksie, powtórzenia testu pod obciążeniem, pomiar, model TLC | box | `boatbox run` albo `boatbox job` |
| Pojedynczy plik testów, `mutacje.py --zmiana`, ruff, mypy, git, `gh`, `tools/scal_pr.py` | Mac | bezpośrednio |
| Excel, napęd Centrum z oknem przeglądarki, prawdziwe pliki taty | Mac, jedno ciężkie polecenie naraz | bezpośrednio |
| Nocne mutacje (`mutacje_nocne.py`, `mutacje_zmiany.py`) | GitHub Actions | workflow `mutacje-nocne.yml` |

`boatbox auto` wybiera Maca, gdy obciążenie z ostatniej minuty jest niższe niż liczba rdzeni, gdy budżetu boat nie da się odczytać, gdy zostało mniej niż 30 startów albo gdy ostatnie 24 h zużyły co najmniej dzienne tempo godzin planu, a w przeciwnym razie box.
Linia `boatbox: auto -> ...` na stderr mówi, gdzie polecenie pobiegło i dlaczego.
`szybko.py` uruchamiaj tak: `boatbox auto '.venv/bin/python tools/szybko.py'`.
Liczbę workerów ustala `czasy_ci.workery_lokalne()`: na Macu 4, a na boxie wszystkie rdzenie, bo `boatbox` ustawia tam zmienną `BOATBOX`.

Zestaw mutacji dziel po `polecenie` i uruchamiaj części naraz:

```bash
jq -c 'group_by(.polecenie | tostring)[]' mutacje.json \
  | awk '{f = "mutacje-fan-" NR ".json"; print > f; print ".venv/bin/python tools/mutacje.py --rownolegle --plik " f}' \
  | boatbox fan
rm mutacje-fan-*.json
```

Mutacje bez klucza `polecenie` biorą polecenie po `--`, więc wtedy dopisz je na końcu linii w `awk`.
Pliki części leżą w korzeniu worktree, bo `boatbox` wysyła na box tylko pliki, które widzi git.

## Budżet

Plan za 20 USD ma dwa limity i oba się kończą: 200 startów boxa na dobę oraz godziny maszyn, z których na każdy dzień zostaje tylko część, a box `large` liczy się podwójnie.
Start to każde utworzenie i wznowienie boxa oraz każda część `fan` uruchomiona równolegle.
`boatbox status` pokazuje oba limity i tempo zużycia godzin, `boatbox auto` przy ich braku wybiera Maca, a `boatbox fan` przy braku startów uruchamia części po kolei na jednym boxie.
Przed pełnym pytestem i przed `fan` uruchom `boatbox status`.
Gdy pokazuje linię `over pace:`, pełny pytest uruchamiaj lokalnie, a `fan` tylko wtedy, gdy Mac jest wąskim gardłem (obciążenie z ostatniej minuty w `uptime` co najmniej równe liczbie rdzeni), bo `run`, `job` i `fan` przy przekroczonym tempie tylko ostrzegają i biegną dalej.
Zadanie kończ poleceniem `boatbox stop`.

## Dane

Na box trafiają tylko pliki, które widzi git, a repozytorium jest publiczne.
Pliki z `config/`, prawdziwe Wzorce, pliki taty, tokeny i treść skrzynki git ignoruje, więc zostają na Macu, a do testów na boxie służą atrapy i dane syntetyczne.

## Test pada tylko na boxie

Uruchom go lokalnie, zanim cokolwiek poprawisz.
Pada też lokalnie: to błąd zmiany.
Przechodzi lokalnie: sprawdź, czy box ma twój HEAD (`boatbox status` pokazuje `head` boxa), a potem szukaj różnicy środowiska (Linux zamiast macOS, 8 vCPU, sygnały) i zapisz ją w tym skillu.
