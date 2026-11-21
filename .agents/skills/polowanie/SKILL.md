---
name: polowanie
description: Cotygodniowe polowanie na powtarzane błędy poza bramką strażnika - klasy, mechanizm na klasę i zdrowie reguł chwastu (stałe zadanie T3 w poniedziałek).
disable-model-invocation: true
---

# Polowanie na powtarzane błędy

Bramka strażnika ([ADR 0042](../../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)) scala Ważne tylko ze strażnikiem, którego dowód policzyło narzędzie.
Polowanie raz w tygodniu czyta to, czego ta bramka nie widzi, składa z tego klasy i każdą klasę bez mechanizmu zamyka zwykłym PR, żeby recenzent, mutacje i tata łapali już tylko błędy nowe.
Uruchamia je stałe zadanie T3 w poniedziałek o 8:00 dla tygodnia, który właśnie minął, a jego wynik to PR-y i jedna linia w wątku zadania, bez issues „Chwast”.

- **Wystąpienie** to jeden błąd agenta z linkiem: poprawka Maksa w wątku, Ważne, przeżyty mutant, czerwony `main` albo runda `FAIL`.
- **Klasa** to co najmniej dwa wystąpienia tego samego mechanizmu błędu, czyli tego, co skłoniło agenta do błędu, z tego tygodnia albo z wcześniejszych polowań; wspólny kod korzenia klasy nie tworzy, bo kod to kategoria (ADR 0036).
- **Mechanizm** to szczebel (a)–(d) drabiny z [`korzen.md`](../przeglad/korzen.md) skilla `przeglad`: odmawia nowego wystąpienia bez osądu.
- **Zdrowie reguły** chwastu to jej odpalenia, fałszywe alarmy i obejścia w tygodniu.

Polowanie biegnie na Macu Maksa we własnym worktree z `origin/main` (`git worktree add --detach ~/.t3/worktrees/MAXIMISEART-Dad/polowanie-<poniedziałek> origin/main`, potem `python3 tools/setup_worktree.py` w nim), a pliki biegu trzyma w `~/.t3/notes/polowanie/<poniedziałek>/` (dalej `<bieg>`), gdzie `<poniedziałek>` i `<niedziela>` to pierwszy i ostatni dzień tygodnia polowania.
Treść wątków (wiadomości Maksa, nazwiska i adresy wykonawców, identyfikatory wątków, nazwy sesji i katalogów) zostaje w `<bieg>`: na box, do repozytorium, PR i issue idzie tylko klasa opisana własnymi słowami z linkiem do PR, werdyktu albo issue, a test i jego fikstura mają tekst wymyślony.

## Kroki

1. Zbierz wystąpienia ze źródeł, każde do swojego pliku w `<bieg>`.
   - Poprawki Maksa w wątkach agentów: wypisz wiadomości operatora z bazy T3 tego Maca, a z bazy T3 og-box tylko wtedy, gdy og-box odpowiada, każdą na maszynie, która ją trzyma, bo baza ma też sesje logowania T3.
     og-box jest nieużywany i offline od ok. 10.11.2026, więc brak odpowiedzi to stan zwykły: plik og-box dostaje linię `og-box: offline, pominięty`, a bieg idzie dalej bez pytania Maksa.
     Wystąpienie to wiadomość, w której Maks poprawia to, co agent zrobił albo pominął; pytanie, zgoda, nowe zadanie i prośba o stan nim nie są.

     ```bash
     .venv/bin/python tools/poprawki_operatora.py --tydzien <poniedziałek> > <bieg>/poprawki.txt
     if ssh -o ConnectTimeout=5 -o BatchMode=yes og-box true; then
       ssh og-box 'mkdir -p /tmp/polowanie/tools/lib' && scp tools/poprawki_operatora.py og-box:/tmp/polowanie/tools/ && scp tools/lib/tydzien_polski.py tools/lib/repo.py og-box:/tmp/polowanie/tools/lib/
       ssh og-box 'python3 /tmp/polowanie/tools/poprawki_operatora.py --tydzien <poniedziałek>' > <bieg>/poprawki-og-box.txt
     else
       echo 'og-box: offline, pominięty' > <bieg>/poprawki-og-box.txt
     fi
     ```

     `--tydzien` to skrót okna od poniedziałku do następnego poniedziałku; analiza wsteczna spoza polowania (np. po resecie limitów, w tygodniu, który jeszcze trwa) bierze okno `--od "RRRR-MM-DD GG:MM"` i, gdy nie kończy się teraz, `--do` w tym samym zapisie.
     Linia `POPRAWKI OPERATORA FAIL` znaczy „źródło poprawek operatora tej maszyny bez danych w tym tygodniu”: idź dalej z pozostałymi źródłami, a jej plik i linia wyniku z kroku 5 dostają zdanie „niedostępne: <powód z linii>”.
     Gdy ostatnia linia wymienia `inne projekty:`, oceń każdy z nich (stary katalog po przeniesieniu albo klon pod inną nazwą to repo) i dla repo uruchom narzędzie ponownie z `--projekt <identyfikator z nawiasu kwadratowego>` na tym samym pliku wyniku, a dla pozostałych dopisz do `<bieg>/wystapienia.md` decyzję „<projekt>: nie repo, <powód>”.

   - Werdykty tygodnia: PR-y z werdyktem `FAIL`, potem werdykty każdego z nich.
     Wystąpienia z werdyktów utworzonych w tygodniu to Ważne ze `Strażnik: brak - test` w bloku `## Korzeń` opisu PR (dowód został recenzentowi) i PR z co najmniej 3 werdyktami `FAIL`, których Ważne w kolejnych rundach stoją na tej samej przesłance.
     Pola `Idiom:` recenzent nie pisze od [ADR 0046](../../../docs/adr/0046-szczebel-straznika-wybiera-recenzent.md), więc ucieczkę reguły daje sekcja „Poszerzenia reguł” issue „Rejestr korzeni” z tego poniedziałku: PR, który zmienił zasięg reguły (`rule`, `files`, lista nazw `banned-api`), to wystąpienie ze stanem mechanizmu `ucieczka: <reguła>`.

     ```bash
     gh api -X GET search/issues -f q='repo:maximiseartai/MAXIMISEART-Dad is:pr updated:<poniedziałek>..<niedziela> "WERDYKT: FAIL"' -f per_page=100 --paginate --jq '.items[].number' > <bieg>/pr-fail.txt
     for n in $(cat <bieg>/pr-fail.txt); do gh pr view "$n" --json comments --jq '.comments[] | select(.body | startswith("WERDYKT:")) | "=== #'"$n"' \(.createdAt)\n\(.body)"'; done > <bieg>/werdykty.txt
     ```

   - Przeżyte mutanty nocy: wystąpienie to PR z tytułu issue i rodzaj linii, której zmiany żaden test nie widzi, a jeden PR to jedno wystąpienie, ile by miał mutantów.
     Linię nocy bez odpowiedzi `wykryta` albo `nie warto` daje `tools/mutacje_nocne.py wystapienia`: rozpoznaje linie nocy każdego rodzaju i odpowiedzi agentów tym samym rdzeniem, po którym noc nie zgłasza linii drugi raz, a liczy się ostatnia odpowiedź.
     Issue bez linii `WYSTĄPIENIE` w tym wyniku nie daje wystąpienia, a rodzaj linii wystąpienia bierzesz z jego linii `WYSTĄPIENIE`.
     W polowaniu 2026-11-09 to 38 z 88 issues bez wystąpienia, a 14 issues z liniami Atrapy efenix daje 4 wystąpienia (#784, #914, #1027, #1084).

     ```bash
     gh issue list --label przezyte-mutacje --state all --search 'created:<poniedziałek>..<niedziela>' --limit 200 --json number,title,body,state,comments > <bieg>/mutanty.json
     .venv/bin/python tools/mutacje_nocne.py wystapienia <bieg>/mutanty.json > <bieg>/mutanty-wystapienia.txt
     ```

   - Czerwony `main` z prawdziwej zmiany: wystąpienie to issue, którego PR naprawy (`cross-referenced` w osi czasu issue) ma blok `### Czerwony main #N` w `## Korzeń`; porażka niestabilna (issue `Flaky test:`, `zderzenie` zdjęte z komentarzem) nim nie jest.

     ```bash
     gh issue list --label czerwony-main --state all --search 'created:<poniedziałek>..<niedziela>' --json number,title,labels,body > <bieg>/czerwony-main.json
     gh api repos/maximiseartai/MAXIMISEART-Dad/issues/<N>/timeline --jq '.[] | select(.event=="cross-referenced") | .source.issue.number'
     ```

   Wyszukiwarkę GitHuba wołaj tylko w tych poleceniach, nie w pętli po issues, bo ma osobny limit 30 zapytań na minutę.
   Krok kończy się, gdy każde źródło ma plik w `<bieg>` z wynikiem polecenia, zdaniem „niedostępne: <przyczyna>” albo linią `og-box: offline, pominięty`, a `<bieg>/wystapienia.md` ma wiersz na każde wystąpienie: źródło, link (`#PR W<n> r<k>`, issue albo `<czas> <wątek>` z `poprawki.txt` i, gdy og-box odpowiedział, `poprawki-og-box.txt`) i jedno zdanie o mechanizmie błędu.
2. Złóż wystąpienia w klasy.
   Weź też sekcję `## Pojedyncze` z `~/.t3/notes/polowanie/*/klasy.md` wcześniejszych polowań, bo wystąpienie z innego tygodnia liczy się do klasy.
   Dla każdej klasy znajdź mechanizm, który ją już pilnuje: regułę w `reguly-ast-grep/`, klucz `banned-api` w konfiguracji ruff, kontrakt w `.importlinter`, wiersz tabel reguł (`| Rule | Guard |` w `CODING_STANDARDS.md`, „Reguły i co ich pilnuje” w `docs/agents/pr-i-ci.md` i `docs/agents/skille.md`) albo punkt skilla.
   Krok kończy się, gdy `<bieg>/klasy.md` ma każdą klasę z co najmniej dwoma wystąpieniami z linkami, zdaniem o wspólnym mechanizmie błędu i stanem mechanizmu (`brak`, `proza: <gdzie>` albo `ucieczka: <mechanizm>`), a każde wystąpienie spoza klas stoi w jego sekcji `## Pojedyncze`.
3. Zmierz zdrowie każdej reguły chwastu: reguły ast-grep z `reguly-ast-grep/`, klucza `banned-api` i kontraktu import-linter.
   - Odpalenie reguły ast-grep to wiersz `ast-grep <id>` sekcji „Odpalenia strażników” issue „Rejestr korzeni” z tego poniedziałku: porażka kroku reguł chwastów w runie CI PR-u tygodnia.
     Odpalenie klucza `banned-api` i kontraktu import-linter to porażka runu CI tygodnia na tej regule: `gh run list --workflow ci.yml --status failure --created <poniedziałek>..<niedziela> --limit 1000 --json databaseId --jq '.[].databaseId'`, potem dla każdego runu `gh run view <id> --log-failed`; ruff drukuje odpalenie zakazu jako `TID251`, import-linter nazwą kontraktu.
   - Fałszywy alarm to odpalenie, po którym PR zmienił regułę, dodał tłumienie albo zwolnienie albo przepisał poprawny kod tylko po to, żeby reguła zamilkła; rozstrzyga następny commit tego PR.
   - Obejście to tłumienie albo zwolnienie dodane do `main` w tygodniu: dla każdego merge'u `git diff <merge>^1 <merge> -U0 -- . ':!tests/' ':!docs/' ':!*.md'` z linią dodaną z `# ast-grep-ignore`, `# noqa: … TID251` albo `# ruff: noqa`, każdy wiersz sekcji „Poszerzenia reguł” issue „Rejestr korzeni” z polem `ignores`, `files` albo `per-file-ignores`, którego merge dodaje zwolnienie albo zawęża pliki (rozstrzyga `git diff <merge>^1 <merge>` pliku reguły), oraz każdy commit z `git log origin/main --first-parent --since=<poniedziałek> --until=<poniedziałek następnego tygodnia> -- sgconfig.yml .importlinter`, który zmienia katalog reguł albo kontrakt import-linter.

   Reguła, której fałszywe alarmy to ponad `FALSE_ALARMS` z `tools/na_scalonych_pr.py` jej odpaleń, dostaje w kroku 4 PR, który ją zawęża albo usuwa (próg Tricordera i miara AutoCommentera z [badania pętli](../../../docs/research/petla-blad-regula.md), „Co przejąć u nas”, punkt 1).
   Krok kończy się, gdy `<bieg>/zdrowie.md` ma wiersz na każdą regułę z liczbą odpaleń, fałszywych alarmów i obejść, a każda reguła ponad progiem stoi w kroku 4 jako klasa do zawężenia.
4. Daj mechanizm każdej klasie bez mechanizmu i każdej regule ponad progiem, od klasy z największą liczbą wystąpień, z najwyżej dwoma otwartymi PR-ami polowania naraz, licząc otwarte PR-y z `klasy.md` wcześniejszych polowań.
   Na każdą klasę zleć osobnego agenta z jej wierszem z `klasy.md` i tą metodą:
   - prototyp na najwyższym szczeblu drabiny (a)–(e), który działa, ze zdaniem przy każdym wyższym, czemu nie działa;
   - dowód na prawdziwym commicie z werdyktu, issue albo wątku: mechanizm pada dokładnie w miejscu z `Gdzie` (`tools/na_scalonych_pr.py --commit <SHA>` dla sprawdzenia, mypy albo test dla typu i testu), a przypadek z wątku wchodzi do testu przepisany na tekst wymyślony;
   - fałszywe alarmy na liniach dodanych ostatnich scalonych PR-ów z dowodu reguły (`tools/na_scalonych_pr.py --regula`, stałe `RULE_PRS` i `FALSE_ALARMS` tego narzędzia);
   - raport `<bieg>/klasa-<nazwa>.md` z sekcjami: Wynik w skrócie (mechanizm, szczebel, dowód, fałszywe alarmy, koszt migracji, gałąź), Prawdziwy kształt klasy, Szczebel i czemu nie inny, Dług i koszt migracji, Prototyp, Dowody (polecenie i ostatnia linia), Fałszywe alarmy, Złapane z historii, Kolizje, Ograniczenia;
   - PR zwykłą drogą (skill [`pr`](../pr/SKILL.md) z linią `Polowanie <poniedziałek>: klasa <nazwa>` w opisie, przegląd według [`przeglad`](../przeglad/SKILL.md), merge przez `tools/scal_pr.py`).

   Klasa, której mechanizm wymaga decyzji Maksa (rodzaj z listy „Decisions for Maks”; o każdej innej, także o miejscu reguły w repo, decyduje agent klasy), dostaje issue `decyzja-maksa` według [`issue-tracker.md`](../../../docs/agents/issue-tracker.md) zamiast PR, a PR bez merge'u przechodzi na następne polowanie i liczy się tam do limitu.
   Krok kończy się, gdy każda klasa bez mechanizmu i każda reguła ponad progiem ma w `klasy.md` link do PR z raportem klasy, issue `decyzja-maksa` albo zdanie „czeka: limit dwóch PR-ów”.
5. Zakończ odpowiedź w wątku zadania jedną linią: `POLOWANIE <poniedziałek> | klasy <k> (nowe <n>) | PR: <URL-e albo brak> | reguły ponad progiem: <id p%, albo brak> | decyzje: <URL-e albo brak> | niedostępne: <plik źródła: powód, albo brak>`, a przy og-box bez odpowiedzi w części `niedostępne` stoi `og-box: offline, pominięty`.
   Krok kończy się, gdy linia ma każdy PR i issue z kroku 4 i każdą regułę ponad progiem z kroku 3.
