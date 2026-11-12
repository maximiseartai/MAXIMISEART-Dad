# ADR 0022: Układ `tools/` i spis narzędzi w `AGENTS.md`

## Status

Zaakceptowana na próbę (decyzja Maksa z 31.10 po hillclimbie przeglądu 30–31.10, dźwignia L4+L4b).
Od merge'a biegnie tydzień obserwacji na żywo, po którym Maks decyduje, czy układ zostaje (niżej, „Obserwacja”).

## Kontekst

W `tools/` leżały obok siebie 34 pliki Pythona: narzędzia, które agent albo człowiek uruchamia, skrypty, które uruchamia tylko workflow CI, i moduły bez własnego wywołania.
Agent dowiadywał się o narzędziu z `AGENTS.md`, dokumentu w `docs/agents/` albo z listingu katalogu, więc przy zadaniu bez podpowiedzi zgadywał po nazwie pliku, czytał kilka `--help` albo pisał polecenie sam.
Pomiar na poligonie (publiczna kopia repozytorium, `claude -p` na Opusie, 19 sytuacji z 8 prawdziwych zadań, n=3–5 na wariant) dał na `main` 99703a21 trafny pierwszy wybór narzędzia bez podpowiedzi w 49/57 próbach (86%), średnio 2,33 tury do trafnego.

## Decyzja

- `tools/` trzyma tylko narzędzia, które agent albo człowiek uruchamia.
  Skrypt, który uruchamia tylko workflow, leży w `tools/ci/`, a moduł bez własnego wywołania w `tools/lib/`.
  Skrypt, który agent uruchamia sam według `docs/agents/`, `README.md` albo docstringu narzędzia (plan runu `plan_ci`, odtworzenie części nocnych mutacji `mutacje_zmiany`), zostaje w `tools/`.
- `AGENTS.md` ma sekcję `## Narzędzia`: jedna linia na narzędzie z `tools/`, a w niej pierwsze zdanie docstringu, które mówi, co narzędzie robi i kiedy go użyć.
  Blok generuje `tests/test_spis_narzedzi.py` z `ZAPISZ_EXPECT=1` i ten sam test pada, gdy blok rozjedzie się z docstringami, więc spis nie ma ręcznych opisów.
- Pierwsze zdanie ma jedną linię 80–160 znaków, a jego pierwsze trzy słowa odróżniają narzędzie od innych.
  Narzędzie z obowiązkową podkomendą wymienia ją w tym zdaniu w nawiasie, np. `(plan --baza origin/main)`.
- `AGENTS.md` i skille nie wskazują `tools/ci/`, a dokument agenta ani docstring narzędzia nie każe uruchamiać skryptu z `tools/ci/`.
- Tych reguł pilnuje `tests/test_spis_narzedzi.py`, a jego komunikaty je mówią.

## Dowód

- Ten sam pomiar ze spisem: trafny wybór narzędzia bez podpowiedzi 56/57 (98%), średnio −0,7 tury na zadanie (powtórka po poprawce L4b: pierwszy wybór 30/30 wobec 29/30 na `main`, −0,73 tury na sytuację, bootstrap 95% 0,27–1,23).
  Pozostałe miary bez pogorszenia: czas próby (mediana 13,8 s wobec 17,8 s), tokeny wejścia, koszt i cel nazwany w pozostałych 13 sytuacjach (13/13 wobec 12/13).
- Pierwsza wersja (L4) przeniosła do `tools/ci/` także `plan_ci` i `mutacje_zmiany`, które dokumenty każą agentowi uruchamiać, i agent ich nie znajdował; stąd reguła, że skrypt agenta zostaje w `tools/`, i strażnik dokumentów.
- Agent, który zna narzędzie tylko ze spisu, rzadziej czyta `--help`: przy zdaniu `plan_ci` bez podkomendy pisał `tools/plan_ci.py` bez `plan` (1/5 dobrych poleceń, `main` 5/5), a po dopisaniu `plan --baza origin/main` 5/5; stąd reguła o podkomendzie.
- Dane: `~/.t3/notes/hillclimb-przeglad-2026-10-30/` na Macu Maksa (`decision.tsv`, `L4b/RAPORT.md`, `L4eval/`).

## Obserwacja

- Tydzień od merge'a agenci pracują z tym układem na prawdziwych zadaniach.
- Miara: czy agent trafia w narzędzie bez podpowiedzi (polecenie z `tools/` zamiast własnego skryptu albo czytania kilku `--help`) i liczba tur do pierwszego trafnego wywołania, z transkryptów wątków T3.
- Po tygodniu Maks decyduje, czy układ zostaje; jeśli nie, następny ADR zastępuje ten, a ścieżki wracają jednym PR.

## Konsekwencje

- Każde nowe narzędzie w `tools/` to linia w kontekście każdej sesji agenta, więc spis rośnie tylko z narzędziami, których agent naprawdę używa; skrypt dla workflow idzie do `tools/ci/`.
- Przeniesienie zmieniło ścieżki w workflow CI, hookach, skryptach skilli i dokumentach, więc gałąź sprzed merge'a, która woła starą ścieżkę, trzeba zaktualizować z `main`.
- Spis nie mówi, kiedy narzędzie jest właściwe w sytuacji agenta (czerwone CI, przed merge'em); to łapie tylko przegląd.

## Odrzucone warianty

- Ręcznie pisany spis w `AGENTS.md`. Rozjeżdża się z narzędziami, a test, który go porównuje z docstringami, i tak potrzebuje jednego źródła.
- Spis z całym pierwszym akapitem docstringu albo z `--help`. Dłuższy kontekst każdej sesji bez zysku w pomiarze; jedno zdanie wystarczyło do 98%.
- Wszystkie skrypty CI w `tools/ci/`, także te, które agent uruchamia. Pomiar L4 pokazał, że agent ich wtedy nie znajduje.
