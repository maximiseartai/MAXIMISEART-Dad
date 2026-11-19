# Przegląd PR: tryb autora

Autor nie przegląda własnego diffu przed pushem i nie zleca przeglądu przed pushem, bo pomiar takiego przeglądu dał czas większy o 27% i koszt dwa razy większy bez zysku w trafności (ADR 0023).

1. Wypchnij gałąź i utwórz PR według skilla [`pr`](../pr/SKILL.md).
   Krok kończy się, gdy masz numer PR i pełny SHA HEAD.
2. Zleć przegląd zaraz po pushu, równolegle z CI, nowemu agentowi, który nie pisał kodu i nie zna Twojej rozmowy.
   Agent dostaje własny worktree (podagent Agent z `isolation: "worktree"`, `delegate_task` z `isolation: "worktree"`), bo przełącza katalog roboczy swojej sesji na HEAD PR (sekcja „Checkout” w [`recenzent.md`](recenzent.md)).
   Zlecenie ma tylko te linie, bez własnej oceny diffu i bez reguł, które ma ten skill:

   ```text
   Przegląd PR #<N> według skilla .agents/skills/przeglad/SKILL.md w trybie recenzenta.
   Katalog werdyktu: ~/.t3/notes/<bieg>/recenzje/<N>/
   Cel Maksa: <jedno zdanie>
   Do sprawdzenia: <punkty albo „nic ponad skill”>
   ```

   Krok kończy się, gdy recenzent oddaje ścieżkę pliku werdyktu i linię `WERDYKT OK`.
3. Po `FAIL` wyrwij korzeń każdego Ważnego według [`korzen.md`](korzen.md) i opisz go w sekcji `## Korzeń` opisu PR (wzór w skillu [`pr`](../pr/SKILL.md)) z linią `Strażnik:`, której dowód przechodzi (przy `pytest <węzeł>` bez bloku recenzenta sprawdź test własną mutacją błędu w `tools/mutacje.py`, a blok do dowodu da recenzent kolejnej rundy), a Drobne popraw albo zapisz z powodem w opisie PR, i zleć kolejną rundę według [`rundy.md`](rundy.md).
   Krok kończy się, gdy na HEAD PR jest `PASS` albo po rundzie z `FAIL`, po której limit rund wymaga zmiany podejścia, a Ty zmieniasz je w tym samym PR i piszesz komentarz `ZMIANA PODEJŚCIA: <zdanie>` ([`rundy.md`](rundy.md)).
4. Po `PASS` z Drobnymi scal PR na tym `PASS` i nie pushuj do niego poprawek Drobnych: każde Drobne zapisz w opisie PR jako otwarte z PR-em, który je poprawi (Twój następny PR albo Twój zbiorczy PR poprawek Drobnych od świeżego `origin/main`), albo, jak po `FAIL` w kroku 3, z powodem, czemu go nie poprawiasz.
   Drobne z przeglądu PR, który sam poprawiał tylko Drobne, nie dostaje osobnego PR: zapisz je jako „bez poprawki” z powodem albo jako otwarte z najbliższym PR, który i tak zmienia jego plik, bo każdy taki PR przechodzi CI, przegląd i `scal_pr`, a jego przegląd daje nowe Drobne (#2238 → #2241 → #2247).
   Push po `PASS` zdejmuje zgodę i kosztuje rundę, a PR poprawki i tak przechodzi przegląd: w werdyktach z 12–17.11.2026 40 z 46 rund po `PASS` ze zmianą kodu przyszło po `PASS` z Drobnymi, 38 z nich skończyło się tym samym `PASS`, a w jednym poprawka Drobnych wniosła Ważne do PR, który miał już zgodę (#1853: jedno Drobne dało trzy rundy z `FAIL`).
   Krok kończy się, gdy PR jest scalony, a każde jego Drobne ma w opisie PR swój PR poprawki albo powód.
