# ADR 0023: Przegląd PR jako skill z narzędziem recenzenta

## Status

Zaakceptowana na próbę (decyzja Maksa z 31.10 w wątku T3 po hillclimbie przeglądu 30–31.10).
Przez tydzień od merge'a obserwujemy ją na żywo, a potem Maks decyduje, czy zostaje.
Zastępuje `docs/agents/przeglad.md`: jego reguły są teraz w skillu `przeglad`.

## Kontekst

47% PR-ów dostawało `FAIL` w pierwszej rundzie przeglądu, a PR-y z `FAIL` zajmowały 68% godzin otwartych PR-ów (23–30.10).
Recenzent czytał reguły z `docs/agents/przeglad.md`, sam zbierał kontekst (SHA HEAD, merge-base, skille `verify-*`, poprzednie werdykty) i sam pisał komentarz z werdyktem, więc postać werdyktu sprawdzał dopiero `tools/scal_pr.py` przy merge'u.
Hillclimb zmierzył warianty przeglądu na poligonie (`maximiseartai/rozliczenia`) na 72 przypadkach z historii repo: 52 z defektem znanym z późniejszej poprawki i 20 czystych.
Stan wyjściowy (`main` 99703a21, dwa powtórzenia) trafiał defekt jako Ważne w 0,50 przypadków, a w 0,19 widział go, ale oceniał jako Drobne.
Rozrzut dwóch powtórzeń tego samego wariantu to ok. ±0,12 trafności, więc mniejsza różnica nie jest mierzalna.

## Decyzja

- Reguły przeglądu są w skillu [`przeglad`](../../.agents/skills/przeglad/SKILL.md): co jest porażką, dowody, postać werdyktu i kolejne rundy, wspólne dla autora i recenzenta.
- Tryb recenzenta ma kroki: `tools/scal_pr.py N --przeglad` drukuje kontekst, recenzent dopisuje każde potwierdzone znalezisko od razu do pliku rundy, a `tools/scal_pr.py N --werdykt <plik>` sprawdza obie pierwsze linie, SHA HEAD i zgodność `PASS`/`FAIL` z liczbą Ważnych, zanim opublikuje werdykt jako komentarz PR.
- Tryb autora to tylko to, co autor czyta, zanim zleci przegląd po pushu: autor nie przegląda własnego diffu przed pushem.

## Co jest porażką: dziura w sprawdzeniu

Decyzja Maksa z 31.10: dziura w sprawdzeniu daje `FAIL`, wąsko.
W PR, który dodaje albo zmienia sprawdzenie (test struktury, checker, hook, skrypt mutacji, bramka CI, reguła lintu), Ważne jest odtworzony przypadek, który według wiersza reguły, docstringu albo opisu PR to sprawdzenie powinno wywrócić, a ono go przepuszcza, i fałszywy alarm sprawdzenia na poprawnym wejściu.
To Ważne także wtedy, gdy produkt na tym SHA zachowuje się dobrze, bo sprawdzenie jest produktem tego PR: dziura w nim to defekt jego zachowania.
Sprawdzenie, które PR zmienia, to także inne sprawdzenie, którego wynik PR zmienia nowym testem, wpisem albo konfiguracją, jak w #670 niżej.
Poza tym Drobne zostają luką bez defektu: przeżyta mutacja w kodzie, który zachowuje się poprawnie, jest Drobne także w kodzie sprawdzenia, gdy recenzent nie odtworzył przypadku, który ono przepuszcza wbrew swojej regule.
Czysty PR z nowym sprawdzeniem bez dziury dalej dostaje `PASS`.

Przypadki, które po tej decyzji są Ważne:

- #496: hook miał oddawać agentowi odmowę, zanim Claude Code zapyta człowieka o zgodę na `rm`, a przepuszczał `cd <katalog> && \rm -f logi/*` i `cd <katalog> && env rm -f logi/*`, na których Claude Code dalej pytał, bo słowo polecenia musiało być dosłownie `rm`.
  Repo zachowywało się dobrze, a dziura była w samym hooku.
- #670: PR dodał test struktury kotwic mutacji skilli, który trafia też do testów nocnych mutacji zmienionych linii i zabija mutanta tylko dlatego, że zmienił się tekst linii.
  Sam test kotwic działa zgodnie ze swoją regułą, ale PR zmienia nim wynik nocnych mutacji: noc nie zakłada wtedy issue `Przeżyte mutacje z #N`, choć zmiany nie pilnuje żaden test zachowania.
  Na tym SHA produkt zachowywał się dobrze, więc pomiar liczył #670 jako czysty, a znalezisko recenzenta wariantu L5 jako fałszywe Ważne.
  Ta decyzja rozstrzyga ten spór: takie znalezisko jest Ważne, a pomiar liczy je odtąd jako przypadek z błędem.
- #408 to inny przypadek z tego samego sporu: zmieniony test przestał łapać brak zabicia drzewa Gita (mutacja `WYKRYTA` na merge-base, `NIEWYKRYTA` na HEAD).
  To „test, który przestał sprawdzać to, co sprawdzał”, czyli Ważne już według dotychczasowej reguły, a nie dziura w sprawdzeniu w rozumieniu tej decyzji; definicja Drobnych mówi teraz wprost, że mutacja `WYKRYTA` na merge-base, a `NIEWYKRYTA` na HEAD nie jest Drobna, a przeżyta mutacja w nowym kodzie, którego merge-base nie ma, zostaje Drobna.

## Dowód

Wariant L1 (ta decyzja) względem stanu wyjściowego:

- „widziane, ale ocenione jako Drobne” 0,19 → 0,04, czyli spadek poza szumem pomiaru;
- trafność 0,52 → 0,58, czyli w szumie: wariant jej nie pogarsza, ale też nie dowodzi poprawy;
- 0 fałszywych Ważnych na czystych przypadkach poza spornym #408 (wariant L1; sporny #670 dotyczy wariantu L5).

## Odrzucone warianty

- Przegląd autora przed pushem (L2): autor zleca świeżemu agentowi przegląd swojego diffu przed pushem i poprawia Ważne, zanim przegląd zrobi niezależny recenzent.
  W pomiarze czas do werdyktu urósł o 27%, a koszt dwa razy, bez zysku w trafności, więc skill nie każe autorowi przeglądać diffu przed pushem.

## Konsekwencje

- Werdykt w złej postaci (brak linii `Znaleziska:`, `PASS` z Ważnym, SHA innego commitu) odrzuca `--werdykt` przed publikacją, a `PASS` w złej postaci opublikowany z pominięciem `--werdykt` odrzuca też `tools/scal_pr.py` przy merge'u (od 7.11.2026, po #994, #1001 i #1004).
- Przez tydzień od merge'a koordynator liczy na żywo: odsetek PR-ów z `PASS` w pierwszej rundzie, błędy przepuszczone przez przegląd (znalezione po merge'u) i czerwony `main`.
  Po tygodniu Maks decyduje na tych liczbach, czy skill zostaje, a do tego czasu `docs/agents/przeglad.md` nie wraca.
