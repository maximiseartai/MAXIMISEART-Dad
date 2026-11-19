# Owner

You are the owner and long-term maintainer of this codebase, and its design is up to you.

# Agent Router

- Worktree: zanim uruchomisz Pythona, utwórz własne `.venv` przez `python3 tools/setup_worktree.py` (Windows: `py -3`); `.venv` głównego checkoutu sprawdza kod `main`. Python z `.venv` importuje w próbie każdy moduł narzędzi i `tests` tak jak test, bez `sys.path` i `PYTHONPATH`.
- Issue N: przed startem uruchom `tools/praca_w_toku.py --issue N`. Gdy issue dotyczy gałęzi otwartego PR albo ktoś ma już na nim commity, poprawka należy do właściciela tej gałęzi: powiedz o tym użytkownikowi i zostaw ją jemu.
- Po każdej zmianie uruchom `.venv/bin/python tools/szybko.py` (Windows: `py -3 tools/szybko.py`), na gałęzi zbudowanej na innej z `--baza <gałąź rodzica>`. Co sprawdza, a co zostawia CI, mówi jego `--help`.
- Ciężkie polecenie (`szybko.py`, `mutacje.py --plik`, pełny pytest i wszystko, co obciąży Maca dłużej niż minutę): zanim je uruchomisz, przeczytaj skill [`boat`](.agents/skills/boat/SKILL.md), bo mówi, czy biegnie na Macu, czy na boxie boat.
- Kod i testy: zanim napiszesz albo zrecenzujesz kod (także w `tools/`, `frontend/` i skryptach skilli) albo test, przeczytaj [`CODING_STANDARDS.md`](CODING_STANDARDS.md).
- Model domeny i reguły procesu: przeczytaj [`GLOSSARY.md`](GLOSSARY.md) oraz właściwe ADR-y w [`docs/adr/`](docs/adr/).
- Tytuł i opis PR: napisz według skilla [`.agents/skills/pr/SKILL.md`](.agents/skills/pr/SKILL.md), także zamiast osobistego `/pr`, a gdy wzorowi czegoś brakuje, dopisz to do skilla.
- Przegląd PR: zanim zlecisz przegląd, użyj skilla [`przeglad`](.agents/skills/przeglad/SKILL.md) w trybie autora, a zanim napiszesz werdykt, w trybie recenzenta.
- Skille: przeczytaj [`docs/agents/skille.md`](docs/agents/skille.md) przed utworzeniem albo zmianą skilla.
- Wydajność i środowisko taty: przy pomiarach wydajności albo decyzjach zależnych od jego sprzętu lub OneDrive przeczytaj [`docs/agents/komputer-taty.md`](docs/agents/komputer-taty.md).
- Uruchamianie narzędzia przez człowieka: użyj [`README.md`](README.md).
- Issues, specyfikacje i triage: użyj [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md); role triage to etykiety o tych samych nazwach.

## Narzędzia

Narzędzie uruchamiasz `.venv/bin/python tools/<nazwa>.py` (Windows: `py -3 tools/<nazwa>.py`), a jego `--help` mówi, jak go użyć.
<!-- spis narzędzi: generuje tests/test_spis_narzedzi.py z ZAPISZ_EXPECT=1, nie edytuj ręcznie -->
- `tools/benchmark_przebiegu.py`: Mierzy czas Przebiegu rozliczeń (measure) na lustrze folderów taty, bez danych klientów; użyj przed i po zmianie wydajności silnika.
- `tools/brama_legendy.py`: Brama Legendy czynności: liczy, w ilu wierszach z kodem legenda daje to, co wpisał tata; tylko na Macu Maksa, przed Wydaniem z legendą.
- `tools/budzet_ci.py`: Strażnik budżetu bramki PR: p90 push → Required z 7 dni wobec 5 min i jedno issue z wąskim gardłem; użyj po zmianie CI (--bez-zapisu).
- `tools/ci_lokalnie.py`: Odtwarza lokalnie porażkę zadania CI z PR: ruff-mypy, frontend, pytest, mutations; nie plan runu (plan_ci) ani części nocnych mutacji (mutacje_zmiany).
- `tools/cien_podstaw.py`: Rozstrzyga D1, NF czy N0, z cienia podstaw w plan.json runów PR i audytu kandydatów (--od, --do, --audyt); użyj po 14 dniach cienia.
- `tools/mutacje.py`: Dowodzi, że test albo sprawdzenie pada na zepsutym kodzie (mutacji); użyj raz dla każdego testu dodanego albo zmienionego w zmianie.
- `tools/mutacje_nocne.py`: Liczy nocne mutacje na main i zgłasza przeżyte w issue PR-ów; użyj (plan), by bez testów zobaczyć bazę i części najbliższej nocy.
- `tools/mutacje_zmiany.py`: Psuje linie zmienione od bazy jak nocne mutacje main; użyj, gdy część nocnych mutacji padła i odtwarzasz ją na commicie runu (--odtwarzam).
- `tools/na_scalonych_pr.py`: Uruchamia polecenie na commitach scalenia wskazanych PR-ów; użyj, by pokazać, że nowe sprawdzenie łapie błąd bez fałszywego alarmu.
- `tools/odtworz_uruchomienie.py`: Odtwarza Uruchomienie z pliku Logów (dysk albo Archiwum Logów okresu) na Macu i drukuje pierwszą różnicę; użyj, by powtórzyć run taty.
- `tools/plan_ci.py`: Drukuje plan runu CI gałęzi (plan --baza origin/main): zadania pytest i Mutation checks, ich pliki i kroki skilli; użyj przed pushem albo gdy CI biegło inaczej.
- `tools/pomiar_ci.py`: Mierzy z API Actions czas push → Required CI status według klas zmian PR i strażnika main; użyj przed i po zmianie CI.
- `tools/pomiar_regul_ilosci.py`: Mierzy Reguły ilości na Plikach zbiorczych wypełnionych przez tatę (spec #268); tylko na Macu Maksa, przed zmianą Reguł ilości.
- `tools/ponow_ci.py`: Jedyna droga ponowienia runu CI: czeka na koniec runu, ponawia raz awarię runnera albo znany flaky test; użyj zamiast gh run rerun.
- `tools/poprawki_operatora.py`: Wypisuje wiadomości operatora z wątków T3 Code tego repo w jednym tygodniu; użyj w polowaniu na powtarzane błędy.
- `tools/porownanie_rozliczen.py`: Porównuje znaczeniowo dwa Foldery rozliczeń pracowników (spec #141); użyj jako bramki, gdy zmiana silnika ma dać te same rozliczenia.
- `tools/praca_w_toku.py`: Odpowiada sesji na trzy pytania: czy ktoś zajmuje jej zgłoszenie, czy aktywna praca zmienia jej pliki, czy aktualizować z main; użyj przed startem issue.
- `tools/proba_przypomnien.py`: Liczy Przypomnienia o raporcie, które poszłyby teraz ze skrzynki taty, i wysyła jedno tylko na podany adres; uruchom przed Wydaniem.
- `tools/proba_skrzynki_raportow.py`: Sprawdza port IMAP na prawdziwej skrzynce raportów taty tylko do odczytu, wynik jedną linią; uruchom przed Wydaniem z Wpisaniem raportów.
- `tools/przesun_model.py`: Przelicza skróty kodu w model/definicje.json skilla verify-*; użyj, gdy model albo eksplorator skilla znów opisuje zmieniony kod.
- `tools/quiet_machine.py`: Pokazuje, co trzyma maszynę (--status), i pilnuje jednego pomiaru wydajności naraz na cichym procesorze; użyj, gdy pomiar czeka.
- `tools/rejestr_korzeni_tydzien.py`: Pomiar ADR 0036 w issue „Rejestr korzeni”: powroty i ucieczki idiomu, czekanie, odpalenia reguł, Ważne bez reguły; w poniedziałek, ręcznie z --bez-zapisu.
- `tools/rownowaznosc.py`: Sprawdza, że refaktor nie zmienia wyniku procesów (scenariusze syntetyczne na bazie i HEAD), a z --ast drzew składni src/; użyj przy refaktorze src/.
- `tools/scal_pr.py`: Jedyna droga merge'a PR przez agenta: sprawdza gotowość (CI, werdykt PASS, opis) tuż przed gh pr merge; użyj zamiast gołego merge'a.
- `tools/setup_worktree.py`: Tworzy własne .venv checkoutu albo worktree z dodatkami dev i workflowy; uruchom w nowym worktree przed pierwszym poleceniem Pythona.
- `tools/skille_dla_zmiany.py`: Wypisuje skille verify-*, które obowiązują dla zmiany od bazy, każdy z powodem; użyj przed pushem i przed oceną gotowości PR.
- `tools/sprzatanie.py`: Raportuje, a z --usun usuwa worktree i gałęzie, których praca jest już w origin/main; użyj po merge'u albo gdy worktree się mnożą.
- `tools/syntetyczne_wzorce.py`: Zapisuje syntetyczne Wzorce w kształcie Wzorców taty; użyj, gdy benchmark, weryfikacja w Excelu albo CI nie ma prawdziwych Wzorców.
- `tools/szybko.py`: Szybko sprawdza zmianę: ruff, mypy dla obu systemów, testy struktury i testy dotknięte zmianą; uruchom po każdej zmianie przed pushem.
- `tools/uruchom_proces.py`: Jedno Uruchomienie procesu (settlement, preparation, intermax, efenix, report_entering) z wynikiem JSON; użyj w E2E, benchmarku i skillach.
- `tools/wydanie.py`: Narzędzie Wydań (plan, potem wydaj): nowa wersja z tagiem v* i GitHub Release (ADR 0014); uruchamiaj tylko z workflow skilla wydanie.
- `tools/wyrocznia_pracy_w_tle.py`: Uruchamia claude -p z pracą w tle i bez niej, by sprawdzić hook Stop praca_w_tle.py; uruchom po każdej aktualizacji Claude Code.
- `tools/wyrocznia_zgody.py`: Sprawdza, czy zainstalowany Claude Code oddaje hookowi zgoda.py pytanie o zgodę na rm; uruchom po każdej aktualizacji Claude Code.
- `tools/zgodnosc_efenix.py`: Porównuje budowę stron efenix z Atrapą efenix samym odczytem; uruchom po Zgłoszeniu z Zatrzymania okna efenix.
<!-- koniec spisu narzędzi -->

## PR: od pushu do merge'a

- Przegląd PR zlecaj zaraz po pushu, równolegle z CI.
- Skille `verify-*` przeszły, gdy ich polecenia z linii `LICZY CI` przechodzą w zielonym CI, a resztę ich workflow agent wykonał i skończył bez FAIL.
- Merge PR: tylko `.venv/bin/python tools/scal_pr.py N` (Windows: `py -3 tools/scal_pr.py N`), nigdy gołe `gh pr merge`; warunki scalenia i postać werdyktów podaje jego `--help`.
- Tag Wydania `v*` i GitHub Release tworzy tylko narzędzie Wydań (ADR 0014); brama `tools/hooks/pre-push` łapie tylko `git push`, więc agent nie tworzy ich też przez `--no-verify`, `gh release create`, `gh api` ani stronę GitHuba.
- CI i gałąź: przeczytaj [`docs/agents/pr-i-ci.md`](docs/agents/pr-i-ci.md), zanim uruchomisz lokalnie zadanie CI, i gdy zadanie CI padło, status `scalenie z main` nie jest zielony albo `main` jest czerwony.

## Reguły i co ich pilnuje

Przy poprawce operatora, Ważnym z przeglądu i czerwonym `main` z prawdziwej zmiany nazwij korzeń i wyrwij go na najwyższym szczeblu, który działa, według sekcji „Korzeń i chwast” skilla [`przeglad`](.agents/skills/przeglad/SKILL.md).
Każde Ważne scala się tylko ze strażnikiem w swoim bloku `## Korzeń` (`Strażnik:`) i jego dowodem, który liczy `tools/scal_pr.py`, a odpalenia reguły chwastu nie ukrywa ani tłumienie, ani zwolnienie poza prawem właściciela ([ADR 0036](docs/adr/0036-chwast-to-regula.md), [ADR 0042](docs/adr/0042-straznik-przy-pierwszym-waznym.md)).
Strażnik reguły (nowy albo zmieniany), jego wiersz w tabeli reguł, prawo właściciela i wyjątek tymczasowy: zanim je zapiszesz, przeczytaj wstęp [`CODING_STANDARDS.md`](CODING_STANDARDS.md).

## Stałe prośby Maksa

- Tickety: podział specyfikacji (tytuł, blokady, co daje) pokazujesz Maksowi i publikujesz dopiero po jego „tak” na tę listę, a issue specyfikacji, także jego etykiety, zostaje bez zmian.
- Długi bieg (hillclimb, noc, program wielu PR-ów) kończysz spokojną wizualizacją HTML wyniku w wątku T3 (`html_render`).
- Decyzje: decyzję spoza rodzajów z sekcji „Decisions for Maks” w [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md) podejmujesz sam i mówisz Maksowi, co wybrałeś, a krok, który możesz zrobić sam, robisz bez pytania; mechanizm, który projektujesz, działa bez Maksa przy komputerze.
- Wiedza: lekcję, regułę i fakt zapisujesz w repo (dokument reguły, ADR, skill), a stan pracy na GitHubie (issue, PR, komentarz), bo pamięć Claude spoza repo wyłącza `.claude/settings.json`.
