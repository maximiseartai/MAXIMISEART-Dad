# ADR 0031: Korzeń po FAIL i chwasty

## Status

Zaakceptowana (decyzje Maksa Q1–Q26 z grilla 13.11.2026 w wątku T3).
Wdrożenie idzie w pięciu PR-ach (Q24); ten ADR wchodzi w pierwszym z nich.
Zmienia regułę korzenia z sekcji „Reguły i co ich pilnuje” w `AGENTS.md`: drabina szczebli ma teraz (e) i żyje w skillu [`przeglad`](../../.agents/skills/przeglad/SKILL.md), sekcja „Korzeń i chwast”.
Zmieniona przez [ADR 0034](0034-kod-jest-pamiecia.md) (specyfikacja #1597) w decyzjach o źródłach chwastu, szczeblu (d), PR korzenia, etykiecie `ready-for-agent` i pomiarze co poniedziałek; każda zmiana obowiązuje od merge'a ticketu, który ADR 0034 przy niej podaje.
Zmieniona przez [ADR 0036](0036-chwast-to-regula.md) (#1676) w decyzjach Q1, Q11, Q12, Q15, Q16, Q22 i Q26: chwast to reguła detektora, kod korzenia to kategoria, która nie blokuje merge'a, a `ZGODA KORZEŃ` i issues „Chwast” znikają; każda zmiana obowiązuje od merge'a jej wykonawcy z tabeli „Wdrożenie” w ADR 0036.

## Kontekst

Regułę „nazwij korzeń i napraw go na najwyższym szczeblu” pilnowały do dziś tylko dwa zdania prozy: w `AGENTS.md` i w kroku recenzenta skilla `przeglad`.
Nic nie sprawdzało, że Ważne ma korzeń, ani nie liczyło, czy ten sam korzeń wraca w innym PR.
Ręczny przegląd Ważnych z 28.10–12.11 przypisał im kody korzeni, a te same kody wracały w wielu PR-ach.
Wystąpienia każdego kodu z co najmniej 2 PR-ów spisał audyt historii (Wdrożenie, punkt 5) w issues z etykietą `chwast`, np. z tego okna `R-MATCH-KOD` w 12 PR-ach (#1541), `R-BEZ-TESTU` w 18 (#1520), `R-MATCH-TEKST` w 6 (#1542); późniejsze werdykty dopisują tam następne PR-y.
Poprawka pod `PASS` zamykała znalezisko, a korzeń zostawał i dawał następne Ważne gdzie indziej.

## Decyzja

### Miara i pojęcia

- Główna miara to udział Ważnych z powtórzonym korzeniem: korzeń, który pojawi się drugi raz w innym PR, to porażka (Q1).
- Pojęcia żyją w skillu `przeglad`, nie w `GLOSSARY.md`, bo ten jest słownikiem domeny taty (Q5):
  - **Korzeń**: to, co skłoniło agenta do błędu, a nie sam błąd; kod z zamkniętej listy obok skilla;
  - **Chwast**: korzeń, który dał Ważne w co najmniej 2 różnych PR-ach; [ADR 0034](0034-kod-jest-pamiecia.md) dokłada zapach, którego liczba na `main` rośnie dwa tygodnie z rzędu (#1627);
  - **Szczebel**: poziom wyrwania korzenia, (a) druga droga i jeden właściciel, (b) typ albo lint, (c) test zachowania łapiący klasę, (d) zapadka, (e) punkt w „Co jest porażką” skilla `przeglad`; [ADR 0034](0034-kod-jest-pamiecia.md) zmienia (d) na regułę deklaratywną w gotowym narzędziu i zakazuje nowej zapadki na regexie linii (#1615).
- Pytanie o korzeń uruchamia Ważne z przeglądu i czerwony `main` z prawdziwej zmiany (Q4); PR naprawy czerwonego `main` ma tę samą sekcję korzenia, a flaky test nie (Q10).
  [ADR 0034](0034-kod-jest-pamiecia.md) liczy do źródeł chwastu poprawkę Maksa w wątku, która jest nim już dziś w `AGENTS.md` i skillu `przeglad`, dokłada spis zapachów (#1627), a issue czerwonego `main` kieruje do wątku autora PR, którego merge go zaczerwienił (#1621).

### Szczebel i dowód

- Autor wyrywa korzeń według piramidy (architektura, refaktor, lint, testy, weryfikacja), a nie łata objaw pod `PASS`; recenzent następnej rundy to sprawdza (Q2).
- Najwyższy działający szczebel, przy każdym wyższym jedno zdanie, czemu nie; Ważne, gdy recenzent pokaże wyższy; bez „bez mechanizmu” (Q7).
- Szczebel (e) to punkt z przykładem w „Co jest porażką” skilla `przeglad`; powrót kodu po (e) idzie do Maksa (Q26).
  Zapadka (d) stoi między (c) a (e), bo jest deterministyczna, a (e) to proza: (d) jest dozwolona tylko wtedy, gdy (a)–(c) nie działają, a (e) tylko wtedy, gdy (a)–(d) nie działają.
  Przy (d) i przy (e) autor pisze jedno zdanie, czemu wyżej się nie da.
  To rozwinięcie decyzji Q7 i Q26 przez koordynatora (13.11.2026), do potwierdzenia przez Maksa.
  [ADR 0034](0034-kod-jest-pamiecia.md) zastępuje zapadkę (d) regułą deklaratywną w gotowym narzędziu, a nową regułę struktury dopuszcza tylko jako typ, regułę ruff, kontrakt import-linter albo regułę ast-grep (#1612, #1613, #1615).
- Dowód wyrwania: mechanizm pada na pierwotnym błędzie (mutacja albo cofnięcie), a recenzent jedną sondą sprawdza siostrzaną formę (Q6).
- Powrót korzenia wymusza szczebel wyżej niż poprzednio; brak wyższego idzie do Maksa (Q11).
- Mały korzeń (do rozmiaru M) wyrywa się w tym samym PR, większy w osobnym PR korzenia scalanym najpierw, a oba PR-y łączą linki (Q8).
  [ADR 0034](0034-kod-jest-pamiecia.md): PR, którego Ważne założyło albo uzupełniło issue „Chwast”, zamyka to issue sam, a większy korzeń idzie PR-em korzenia z tego samego wątku (#1619).

### Kody i werdykt

- Zamknięta lista kodów w repo, [`korzenie.toml`](../../.agents/skills/przeglad/korzenie.toml), z jednym zdaniem i przykładem PR przy każdym kodzie (Q3).
  Kody pochodzą z historii (Q13); te, które opisują jeden moduł albo pokrywają się z innym, scalono, a te z samymi drobiazgami pominięto.
- Nowy kod wchodzi przez `Korzeń: NOWY R-KOD - opis` w werdykcie, a autor dopisuje go do listy; porządek listy co tydzień jako propozycja dla Maksa (Q18).
- Szablon werdyktu: Ważne z polami `Gdzie`, `Dowód` (do 5 linii po 300 znaków), `Korzeń` i `Szczebel`, Drobne z jedną linią `Gdzie`, na końcu `## Sprawdzone` z najwyżej 5 punktami; sprawdza go `tools/scal_pr.py --werdykt` (Q3, Q9).
  Treść czyta renderer GitHuba (`gh api markdown`), jak opis PR przy „Naprawia”, więc pola i nagłówki liczą się tylko poza blokami kodu, a cytat wyniku z linią pola nie psuje szablonu.
- Autor może zakwestionować kod z powodem, rozstrzyga następny recenzent, a rejestr bierze kod z ostatniego werdyktu (Q25).
  Recenzent rozstrzyga punktem `Korzeń W<n> r<k>: R-KOD - zdanie` w `## Sprawdzone` swojego werdyktu, gdzie `r<k>` to `k`-ty werdykt PR.
- Szablon obowiązuje od pierwszego werdyktu po wdrożeniu; wątki, które już mają werdykt, kończą po staremu (Q20).
  Kryterium jest deterministyczne i jedno dla publikacji i zgody na merge: wątek kończy po staremu, gdy najstarszy werdykt PR (`createdAt` z GitHuba, od konta z prawem zapisu) powstał przed chwilą wdrożenia.
  Werdykt w komentarzu edytowanym (`includesCreatedEdit`) nadal jest werdyktem, ale wątku nie postarza, bo jego treść mogła powstać po wdrożeniu.
  Chwila wdrożenia to data commitu, który dodał ten ADR na bazie PR, liczona po `--first-parent`: na `main` to commit merge'a PR wdrożenia, a na gałęzi stosu commit z jej własnej historii (scalenie `main` do niej albo commit autora, którego datę zmienia rebase), a na bazie, do której ten ADR jeszcze nie wszedł, szablon nie obowiązuje.
  Komentarzem, także edytowanym, nie da się przesunąć chwili wdrożenia, a przed merge'em nikt jej nie zgaduje.
  Bramka korzenia (PR 2) obowiązuje od własnego wdrożenia, nie od wdrożenia szablonu, bo wątki, które pracowały przed nią, kończą po swojemu: wymaga sekcji `## Korzeń` tylko w wątku, którego najstarszy nieedytowany werdykt od konta z prawem zapisu nie powstał przed nią.
  Chwilę wdrożenia bramki wyznacza ta sama reguła co szablonu (`werdykt_pr.deployment` i `werdykt_pr.rule_applies`), ale dla pliku `tools/lib/bramka_korzenia.py`, który dodał PR wdrożenia bramki: na `main` to commit merge'a tego PR.

### Rejestr i chwasty

- Rejestrem są werdykty i issues na GitHubie; powrót korzenia wykrywa `tools/scal_pr.py --werdykt` przy publikacji (Q22).
  Wystąpienie kodu to Ważne werdyktu `FAIL` z kodem z ostatniego werdyktu, który go dotyczy (Q25), i blok `### Czerwony main #N: R-KOD` opisu scalonego PR, oba po wdrożeniu szablonu (Q13); czyta je jeden moduł, `tools/lib/rejestr_korzeni.py`.
  Werdykt z kodem, który ma wystąpienie w innym PR, zakłada issue „Chwast: R-KOD” albo dopisuje wiersz do tabeli otwartego, a linia `WERDYKT OK` podaje to po `| CHWAST`.
  Wcześniejsze wyrwanie (Q11) to blok ze szczeblem w innym PR scalonym przed powstaniem wystąpienia kodu w PR bramki: przed werdyktem `FAIL` z tym Ważnym, także gdy późniejszy werdykt rozstrzyga je innym kodem (Q25), albo przed założeniem issue czerwonego `main`.
  Gdy wcześniejsze wyrwanie było na (a), zgodę Maksa daje komentarz z linią `ZGODA KORZEŃ: R-KOD` od konta z prawem `admin`; to samo konto piszą agenci, więc bramka sprawdza konto, a nie człowieka.
- `## Korzeń` w opisie PR jest wymagany tylko po `FAIL` z Ważnym albo przy naprawie czerwonego `main`, z blokiem na każde Ważne: Szczebel, „Wyżej nie, bo”, Dowód (Q17).
  Wzór sekcji stoi w skillu [`pr`](../../.agents/skills/pr/SKILL.md), sekcja „Root section”, a `tools/scal_pr.py` czyta go jako wzór odmowy.
  PR naprawia czerwony `main`, gdy linia „Część #N” albo „Naprawia #N” jego opisu wskazuje issue z etykietą `czerwony-main`; flaky test ma własne issue z etykietą `flaky-test`, więc sekcji nie wymaga.
  Sekcję wymaga sama decyzja `FAIL`, bo `FAIL` daje tylko Ważne: `FAIL` bez linii `Znaleziska:` albo z `Ważne 0` (opublikowany poza `--werdykt`) wymaga bloku `W1 r<k>`.
  Każdy kod sekcji, w bloku Ważnego i w bloku czerwonego `main`, stoi na liście `korzenie.toml` na HEAD PR.
  Szczebel (e) wymaga, żeby PR dopisał do „Co jest porażką” skilla `przeglad` nowy punkt z linkiem do tego PR, a pozostałe punkty zostawił jak na bazie; czy punkt opisuje ten korzeń, ocenia recenzent.
- PR korzenia ma linię „Korzeń z #N: R-KOD”, PR z funkcją „Wyrwany w #M”; `scal_pr` sprawdza linie i kolejność merge'a (Q14): PR korzenia jest już scalony do domyślnej gałęzi repozytorium.
  Oba numery to linki GitHuba, więc GitHub pokazuje je na osi czasu obu PR-ów.
  Granica mechanizmu: rozmiaru ponad M (Q8) bramka nie liczy, bo w jednym PR nie oddzieli linii korzenia od linii funkcji, więc o tym, czy wyrwanie mieści się w PR, czy idzie do PR korzenia, rozstrzyga recenzent według skilla `przeglad`.
- Zgoda z góry na automatyczne issue „Chwast: R-KOD” z szablonem bez wolnej prozy (Korzeń, Wystąpienia, „Gotowe, gdy”), z etykietami `chwast` i `ready-for-agent`; zamyka je PR z „Korzeń z #issue” (Q12, Q15).
  [ADR 0034](0034-kod-jest-pamiecia.md): `ready-for-agent` ma tylko chwast z czoła kolejki (#1620), a sierotę bierze ogrodnik, gdy w toku są mniej niż dwa chwasty (#1621).
- Historyczne korzenie z powtórzeniami, których nic nie wyrwało, dostają issues do naprawy; jednorazowy audyt na `main` odtwarza przypadki kodów z co najmniej 2 PR-ów i zakłada issue tylko tam, gdzie nic dziś ich nie łapie (Q13, Q16).
- Pomiar co poniedziałek: GitHub Actions o 6:00 aktualizuje issue „Rejestr korzeni” liczbami z szablonu, a zadanie T3 o 8:00 dokłada osąd o kodach i kartę w wątku (Q19, Q23).
  Liczby liczy `tools/rejestr_korzeni_tydzien.py` z rejestru (`rejestr_korzeni.read`): wystąpienie to Ważne albo blok czerwonego `main`, powtórzenie to wystąpienie kodu, który wcześniej wystąpił w innym PR (Q1), a tydzień trwa od poniedziałku 0:00 czasu polskiego.
  Historię tygodni narzędzie liczy od nowa z rejestru przy każdym uruchomieniu, więc treść issue nie jest drugim rejestrem.
  [ADR 0034](0034-kod-jest-pamiecia.md) dokłada do pomiaru sześć liczb spisu zapachów (#1627) oraz liczbę zgód `ZGODA KORZEŃ` i `ZGODA SZOPA`, merge'y poza `tools/scal_pr.py` i zgód napisanych przez agentów (#1626).

## Wdrożenie

Pięć PR-ów w tej kolejności (Q24):

1. Ten ADR, pojęcia i drabina w skillu `przeglad`, lista kodów i szablon werdyktu sprawdzany przez `tools/scal_pr.py --werdykt` (Q3, Q5, Q9, Q18 część „NOWY”, Q21, Q25, Q26).
2. Zrobione: `## Korzeń` w opisie PR i linie PR korzenia („Korzeń z #N”, „Wyrwany w #M”) sprawdzane przez `tools/scal_pr.py` przy merge'u (`tools/lib/bramka_korzenia.py`), razem z tym, że każdy `NOWY` kod z werdyktów PR stoi na liście na HEAD, i punkt rozstrzygnięcia kodu w werdykcie (Q8, Q10, Q14, Q17, Q18, Q25, Q26).
3. Zrobione: wykrycie powrotu korzenia przy publikacji werdyktu i issue „Chwast: R-KOD” (`tools/lib/rejestr_korzeni.py`, `tools/chwasty.py`), szczebel wyżej przy powrocie w bramce korzenia z linią `ZGODA KORZEŃ: R-KOD` po (a) i zamknięcie issue przy merge'u PR z „Korzeń z #issue” (Q11, Q12, Q15, Q22).
4. Zrobione: workflow tygodniowy `.github/workflows/rejestr-korzeni.yml` w poniedziałek o 6:17 czasu polskiego (pełną godzinę GitHub opóźnia) i `tools/rejestr_korzeni_tydzien.py`, który zmienia treść issue „Rejestr korzeni” z etykietą `rejestr-korzeni` (Q19, Q23).
   Kartę XmR i propozycje porządku kodów (Q18) daje zadanie T3 o 8:00, bo wymagają osądu modelu; to zadanie zakłada koordynator po merge'u.
5. Zrobione bez zmiany kodu: audyt historii odtworzył na `main` przypadki kodów z co najmniej 2 PR-ów i przez `rejestr_korzeni.settle` założył albo uzupełnił issues „Chwast” tam, gdzie nic ich nie łapie (Q13, Q16).
   Przypadek liczy się jako złapany tylko wtedy, gdy mechanizm łapie też jego formę siostrzaną (Q6), więc test regresji samej poprawki nie wystarcza.

## Konsekwencje

- Recenzent pisze werdykt w szablonie, a odmowa `--werdykt` podaje przyczyny i wzór, więc poprawia plik bez czytania dokumentacji.
- W wątku z szablonem merge liczy `PASS` jako zgodę tylko wtedy, gdy przechodzi szablon, także gdy opublikowano go z pominięciem `--werdykt`; odmowa podaje przyczyny i wzór.
- `NOWY R-KOD` przechodzi przy publikacji z kodem spoza listy HEAD PR, a z kodem, który już na niej stoi, jest odmową; recenzent nie dobiera najbliższego kodu, bo zły kod zafałszowałby rejestr powtórzeń.
  NOWY kod musi być na liście przed merge'em PR; pilnuje tego bramka korzenia w `tools/scal_pr.py`.
