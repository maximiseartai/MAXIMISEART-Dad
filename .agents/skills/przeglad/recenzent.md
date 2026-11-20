# Przegląd PR: tryb recenzenta

Ten plik czytasz po [`SKILL.md`](SKILL.md) (co jest porażką, postać werdyktu, pozostałe pliki).
Recenzent nie pisał kodu, nie zmienia gałęzi PR, nie pushuje, nie scala i nie uruchamia subagentów.

## Checkout

Recenzent pracuje w katalogu roboczym swojej sesji, bo zlecenie daje mu własny worktree (krok 2 [trybu autora](autor.md)), więc żadne polecenie nie zaczyna się od `cd`.
Przełącz go na HEAD PR: `git fetch origin pull/<PR>/head`, `git checkout --detach FETCH_HEAD`, potem `python3 tools/setup_worktree.py`.
Katalog roboczy to cudzy checkout, gdy jest głównym checkoutem (`git rev-parse --git-dir` równe `git rev-parse --git-common-dir`), stoi na gałęzi PR (`git branch --show-current`) albo `git status --porcelain` nie jest pusty: wtedy go nie przełączaj, tylko utwórz odłączony checkout `git worktree add --detach <katalog> FETCH_HEAD` i `tools/setup_worktree.py` w nim.
Plik werdyktu leży w katalogu ze zlecenia, a bez niego w `~/.t3/notes/recenzje/<PR>/`; ten katalog trzyma tylko pliki werdyktu i jego dowodów, nigdy checkout.

## Kroki

1. Uruchom `.venv/bin/python tools/scal_pr.py <PR> --przeglad`.
   Krok kończy się, gdy masz SHA HEAD i merge-base; poprzedni werdykt znaczy, że to kolejna runda, więc przeczytaj [`rundy.md`](rundy.md), a gdy któryś poprzedni werdykt ma Ważne, także [`korzen.md`](korzen.md).
   Gdy kończy się linią `PRZEGLĄD ODMOWA`, nie przeglądasz i nie piszesz werdyktu, tylko oddajesz wywołującemu tę linię, bo `--werdykt` odmówi z tej samej przyczyny.
2. Przejrzyj diff według sekcji „Co jest porażką” w [`SKILL.md`](SKILL.md) i sekcji „Dowody” niżej, a skille z linii `SKILLE VERIFY` wykonaj według sekcji `What CI runs and what stays local` każdego z nich.
   Linia `CI` z kroku 1 mówi, czy polecenia z linii `LICZY CI` przeszły: przy `success` logów zadań CI nie przeszukuj, a przy `failure` czytaj tylko logi padłych zadań, które podaje.
   Każde potwierdzone znalezisko od razu dopisz do pliku `runda-<k>.md` w katalogu werdyktu blokiem szablonu z sekcji „Postać werdyktu” w [`SKILL.md`](SKILL.md), żeby przerwany przegląd zostawił znaleziska.
   Ważne ma kod korzenia z [`korzenie.toml`](korzenie.toml), szczebel i mechanizm z [`korzen.md`](korzen.md) i `Gdzie` z liniami złego kodu, więc oba pliki czytasz przy pierwszym Ważnym.
   Krok kończy się, gdy przejrzałeś cały diff, a każde znalezisko jest w pliku, Ważne z korzeniem i szczeblem.
3. Dopisz na górę pliku dwie linie z sekcji „Postać werdyktu” w [`SKILL.md`](SKILL.md), a na koniec `## Sprawdzone` z 1–5 punktami.
   Krok kończy się, gdy liczby w drugiej linii zgadzają się ze znaleziskami w pliku.
4. Opublikuj werdykt: `.venv/bin/python tools/scal_pr.py <PR> --werdykt <plik>`.
   Gdy odmawia, popraw plik według jego komunikatu i uruchom je ponownie.
   Sądzi kodem `origin/<baza PR>`, jak merge, a nie kodem Twojego checkoutu HEAD PR (linia `SĘDZIA`).
   Gdy HEAD PR zmienił się w trakcie, przejrzyj diff od przejrzanego SHA do nowego HEAD, zanim zmienisz SHA w pliku.
   Krok kończy się linią `WERDYKT OK` z adresem komentarza: oddaj wywołującemu ścieżkę pliku i tę linię.

## Dowody

Każde znalezisko ma plik:linia i dowód: polecenie z wynikiem, repro albo mutację z `tools/mutacje.py` (`NIEWYKRYTA` albo `WYKRYTA`).
Mutacja `REGRES` (`NIEWYKRYTA` na HEAD, a `WYKRYTA` na merge-base, który narzędzie sprawdza samo) oraz `ZAWIESZENIE` (test po mutacji skończony przez pytest-timeout) i `PRZEKROCZONY CZAS` (polecenie bez wyniku w `--limit-s` narzędzia) to Ważne; noc i skrypty mutacji skilli liczą `ZAWIESZENIE` jak wykrytą, bo pytest-timeout czerwieni test w CI, więc widzi je tylko przegląd; `PRZEKROCZONY CZAS` skrypty mutacji skilli liczą jak przeżytą, a noc tylko loguje (`MUTACJE NOCNE BEZ ISSUE`).
Gdy wynik mutacji może zależeć od sąsiadów w procesie pytest (blokada, wątek, stan modułu), uruchom ją z `--jak-ci <id runu>`: biegnie z plikami każdego zadania pytest tego runu CI PR, w którym stoją zmienione testy, w jednym workerze, więc odtwarza skład zadania z tego runu, ale nie jego podział na workery.
Recenzent refaktoru, czyli zmiany, która nie ma zmieniać zachowania procesów, uruchamia `.venv/bin/python tools/rownowaznosc.py --baza <merge-base>` i wkleja do werdyktu jego ostatnią linię.
Recenzent PR-u, który dodaje albo zmienia sprawdzenie (test struktury, regułę lintu, zadanie CI, narzędzie sprawdzające), uruchamia samo to sprawdzenie przez `tools/na_scalonych_pr.py --commit <SHA>` na jednym z commitów, które opis PR podaje jako złapane, i wkleja ostatnią linię wyniku.
Mutacje recenzenta biegną po kolei, z `PYTEST_XDIST_AUTO_NUM_WORKERS=1`, najwyżej kilkanaście.
Pełnych mutacji i pełnego CI recenzent nie uruchamia lokalnie, bo liczy je CI i noc (ADR 0021).
