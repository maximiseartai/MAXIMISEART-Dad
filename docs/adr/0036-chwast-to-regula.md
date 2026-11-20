# ADR 0036: Chwast to reguła

## Status

Przyjęta na mandat Maksa z nocy 14/15.11.2026 (pełna samodzielność, uzgodnione z koordynatorem #1597); do przejrzenia przez Maksa; odwracalna przez revert.
Zmienia [ADR 0031](0031-korzen-po-fail-i-chwasty.md) w decyzjach Q1 (miara), Q11 (szczebel wyżej przy powrocie i `ZGODA KORZEŃ`), Q12, Q15, Q16 i Q22 (issues „Chwast”) oraz Q26 (powrót po (e) idzie do Maksa).
Zmienia [ADR 0034](0034-kod-jest-pamiecia.md) w decyzjach „Rejestr liczy zgody i obejścia”, „Autor wyrywa swój chwast”, „Kolejka” i „Ogrodnik”, bo ich przedmiotem jest issue „Chwast”, oraz w mierze odczytu 11.12.2026; „Cztery źródła” zostają źródłami wystąpień, ale żadne z nich nie zakłada już issue.
Zastępuje propozycję z PR #1678, zamkniętego bez merge'u, więc numer 0035 zostaje wolny.
[ADR 0042](0042-straznik-przy-pierwszym-waznym.md) na decyzję Maksa z 18.11.2026 zmienia decyzje „Pole werdyktu”, „Warunek merge'a”, „Dowód reguły”, „Idiom bez reguły” i „Status w Actions”.
[ADR 0046](0046-szczebel-straznika-wybiera-recenzent.md) na decyzje Maksa z 20.11.2026 zmienia decyzję „Pole werdyktu”.

Ten ADR wchodzi bez zmiany kodu, skilli i bramki. Każdą decyzję wdraża wykonawca z tabeli w sekcji „Wdrożenie”, a do jego merge'a obowiązuje dotychczasowe zdanie [`AGENTS.md`](../../AGENTS.md), skilli [`przeglad`](../../.agents/skills/przeglad/SKILL.md) i [`pr`](../../.agents/skills/pr/SKILL.md) oraz `tools/scal_pr.py`, z regułą przejściową pod tą tabelą.

## Kontekst

Rejestr korzeni od wdrożenia szablonu ADR 0031 (13.11.2026, ok. 22 h) ma 94 wystąpienia, z tego 47 „powrotów”, czyli kod, który inny scalony PR już wyrwał.
Przegląd każdego z 47 wobec wcześniejszego wyrwania pokazał (jeden oceniający, cała populacja):

- 36 łączy z wcześniejszym wyrwaniem tylko kod korzenia, a mechanizm jest inny;
- 10 to ten sam idiom w innym pliku, gdzie wcześniejsze wyrwanie świadomie zostało przy lokalnym szczeblu (np. #1568 odrzucił zakaz `write_text`);
- 1 to porażka wyrwania: #1553 usunął kopie lokatora tytułu okna, a nic nie odmówiło nowej kopii, która przyszła z #1533.

22 kody, które nazywają kategorię, dają 46 z 47 powrotów, a 11 kodów, które nazywają mechanizm, jeden.
Licznik powtórzeń mierzy więc szerokość etykiet, a nie to, czy wyrwanie trzyma.

Bramka zgody kosztowała 21 h czekania od `PASS` i zielonego CI do merge'a (5 PR-ów, mediana 4,9 h).
Wszystkie 5 linii `ZGODA KORZEŃ` z okna pomiaru napisało konto, z którego piszą też agenci.
13 scalonych PR-ów dzisiejsza bramka by zatrzymała. Bramka z kodu `main` tuż przed ich merge'em odmówiłaby 12 z nich (10 bez zgody, 2 bez szczebla wyżej), a #1492 przepuściła regułą wdrożenia (Q20). Te 12 scaliło `tools/scal_pr.py` ze starego checkoutu sprzed bramki, z wynikiem `SCAL OK` i bez śladu na GitHubie.
Z 26 issues „Chwast” żadne nie jest zamknięte.
Metoda i tabele tych liczb są w komentarzu PR #1693, który wprowadził ten ADR.

## Decyzja

### Jednostka chwastu

- **Chwast to reguła detektora.** Chwast to reguła gotowego narzędzia (ast-grep, `banned-api` ruff, kontrakt import-linter) albo typ razem z zakazem jego obejścia, z komunikatem „użyj X” i próbkami.
  Prawdziwy powrót to odpalenie reguły na dodanej linii w Required CI, a ucieczka to wystąpienie idiomu po merge'u jego reguły, którego reguła nie złapała.
  Powód: z 47 „powrotów” kodu 36 łączy tylko etykieta, a 11 prawdziwych (1 porażka i 10 idiomów) ma wspólną cechę: nic nie odmawiało nowego wystąpienia na dodanych liniach.
- **Miara Q1.** Główna miara to ucieczki i powroty idiomu zamiast udziału powtórzonego kodu korzenia.
  Powód: 22 kody-kategorie dają 46 z 47 powtórzeń, więc dawna miara rośnie z szerokością listy kodów.

### Kod korzenia

- **Kod korzenia to kategoria.** Kod z `korzenie.toml` zostaje typem w sensie ODC (IBM, Chillarege 1992) z wyliczonym polem „trigger” (gdzie błąd wyszedł: przegląd, CI, czerwony `main`, nocne mutacje), czyli daną w poniedziałkowym raporcie, i nie blokuje merge'a.
  Q11 (szczebel wyżej przy powrocie kodu) i linia `ZGODA KORZEŃ` znikają.
  Powód: bramka zgody dała 21 h czekania i 5 zgód z konta agentów, a 12 merge'y, których odmówiłaby, ominęło ją przez stary checkout.

### Drugie wystąpienie idiomu

Zapis decyzji z 14–17.11.2026; warunek merge'a z tej sekcji zastępuje [ADR 0042](0042-straznik-przy-pierwszym-waznym.md), a pole `Idiom:` zostaje adnotacją, którą czyta tylko raport tygodniowy.

- **Pole werdyktu.** Pole pisze recenzent, nie autor. Ma jedną z trzech postaci:
  - `Idiom: <id> jak #N Wn rk`, gdy to drugie wystąpienie idiomu, który nie ma jeszcze reguły, a `<id>` to id reguły, którą PR ma dodać;
  - `Idiom: <id>`, gdy to ucieczka istniejącej reguły `<id>`;
  - `Idiom: bez reguły <klasa> jak #N Wn rk`, gdy idiom nie dostaje reguły, a `<klasa>` pochodzi z zamkniętej listy w punkcie „Idiom bez reguły”, który podaje też warunek każdej klasy.
  Powód: jawne oznaczenie daje deterministyczne źródło klastra, a grupowanie modelem zależałoby od zgodności oceniających, której nikt nie zmierzył. Autor nie wybiera postaci, więc nie może wybrać tańszej.
- **Warunek merge'a.** PR z Ważnym z polem `Idiom: <id>` albo `Idiom: <id> jak #N Wn rk` scala się tylko wtedy, gdy na HEAD PR istnieje reguła o id `<id>` (pole `id` reguły ast-grep, klucz `banned-api` albo nazwa kontraktu import-linter) i gdy jej dowód (niżej) przechodzi na przypadku z tego Ważnego.
  Próbka `ZNANE_LUKI` nigdy nie zastępuje reguły. Wolno ją dodać obok reguły, która łapie przypadek z `Gdzie`, dla formy siostrzanej, której mechanizm reguły nie wyrazi.
  Sprawdza to `tools/scal_pr.py` bez osądu i bez linii zgody.
  Powód: reguła pisana w PR drugiego wystąpienia ma autora z kontekstem, a gdyby próbka wystarczała, każdy idiom dałoby się zamknąć próbką, której reguła dziś nie łapie (R-ZAPADKA-OBEJSCIE).
- **Reguła chwastu niczego nie ukrywa poza właścicielem.** Odpalenia reguły chwastu nie da się ukryć tańszą drogą niż zmiana reguły z jej dowodem: ani tłumieniem, ani zwolnieniem poza prawem właściciela z `CODING_STANDARDS.md`.
  Formy, które mechanizm musi rozstrzygnąć, zebrały przeglądy #1693 r1–r4 w [komentarzu #1676](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1676#issuecomment-6871386075).
  Prawo właściciela stoi tylko w konfiguracji reguły, którą widać w jej diffie (`per-file-ignores` i `OWNERS` dla `TID251`, `ignores:` reguły ast-grep), a nigdy w komentarzu: krok Required CI „Weed rules of the whole tree” odmawia każdej linii pliku Pythona z tekstem `ast-grep-ignore` (także w napisie, więc ast-grep nie ma czego uznać) i każdego `noqa`, które chowa zakazaną nazwę, a `tests/test_zakazy_ruff.py` trzyma zwolnienia z `TID251` równe `OWNERS`.
  Osłabienie reguły w PR, który ona sądzi (`ignores:`, `files:`, usunięta reguła, `sgconfig.yml`), łapie warunek 6 `tools/scal_pr.py`, także w statusie „Werdykt i bramka”: reguły ast-grep z bazy na liniach, które PR dodaje, linia z tekstem dyrektywy tłumienia też, a każdy przypadek reguł bazy (`metadata.przypadki`) wymienia i łapie po scaleniu któraś reguła, bez względu na jej id i plik, wszystko liczone kodem bazy, więc zmiana reguły obowiązuje od swojego merge'a, a kod, który z niej korzysta, wchodzi następnym PR-em.
  Powód kształtu: krok z #1766 wyznaczał prawo właściciela z treści linii różnicy i przepisywał YAML reguł, a każda z sześciu rund przeglądu #1720 znalazła w nim nową formę ukrycia; zakaz samego tekstu dyrektywy nie odtwarza gramatyki ast-grep, a dwie pierwsze rundy #2099 pokazały, że odtworzona gramatyka komentarza (`##`, samotne `\r`) się z nią rozjeżdża.
  Powód: cztery rundy przeglądu tego ADR znalazły cztery formy ukrycia w prozie, w tym zwolnienie całego `TID251` dla 16 plików właścicieli, które istnieje już na `main`. Granicę mechanizmu da się sprawdzić tylko na kodzie z testem.
- **Dowód reguły.** Regułę przyjmuje się tylko z wynikiem `tools/na_scalonych_pr.py`, który `tools/scal_pr.py` uruchamia z kodu bazy PR: łapie `Gdzie` każdego przypadku tej reguły z historii jej pól `Idiom:` (nie tylko bieżącego) na dodanych liniach do SHA werdyktu `FAIL` i ma najwyżej `FALSE_ALARMS` fałszywych alarmów na dodanych liniach `RULE_PRS` ostatnich scalonych PR-ów (stałe w `tools/na_scalonych_pr.py`).
  Powód: 10% to próg Google Tricorder dla analiz w review, a reguła `write_text` dała 18 alarmów w 6 z 20 PR-ów bez żadnego znanego defektu, a reguła lokatora tytułu 0 alarmów i złapała jedyną porażkę wyrwania.
- **Idiom bez reguły.** Ważne z polem `Idiom: bez reguły <klasa>` nie zatrzymuje merge'a, a bramka niczego w nim nie sprawdza; każde takie Ważne trafia do poniedziałkowego raportu z linkiem.
  To jedyne miejsce osądu w pętli: klasę wybiera niezależny recenzent według warunku z tabeli, a recenzent następnej rundy sprawdza ją według ostatniej kolumny.

  | Klasa | Recenzent pisze ją, gdy | Recenzent następnej rundy daje Ważne, gdy |
  |---|---|---|
  | `brak-testu` | brakuje testu, a idiomu nie wyrazi żaden mechanizm z sekcji „Jednostka chwastu” | pokaże regułę, która idiom wyraża; brak testu zostaje nocnym mutacjom ([ADR 0021](0021-mutacje-noca.md)), poza próbką testu, która nie może paść na złej implementacji z jego docstringu: tę łapie tylko przegląd |
  | `stan-kroku` | błąd to stan po wykonaniu kroku, a idiomu nie wyrazi żaden mechanizm z sekcji „Jednostka chwastu” | pokaże regułę, która idiom wyraża |
  | `typ` | idiom zamyka typ, z którym zła postać nie przechodzi mypy (szczebel (b)), także gdy regułą też da się go wyrazić | jego dowód mutacji nie daje `WYKRYTA`; reguły nie żąda |
  | `test-klasy` | idiom zamyka test zachowania, który łapie całą klasę (szczebel (c)), także gdy regułą też da się go wyrazić | jego dowód mutacji nie daje `WYKRYTA`; reguły nie żąda |

  Dowód mutacji to punkt „## Sprawdzone” recenzenta rundy po poprawce: polecenie `tools/mutacje.py`, które przywraca na HEAD złą postać z `Gdzie`, z linią `WYKRYTA` i ostatnią linią `MUTACJE OK`.
  Luka: gdy runda po poprawce kończy się `PASS` bez punktu dowodu, PR scala się bez dowodu, bo następnej rundy nie ma, a bramka tego nie sprawdza; ślad zostaje tylko w poniedziałkowym raporcie.
  Powód: z 11 prawdziwych powrotów regułą da się wyrazić 4, częściowo 2, a 5 to braki testu albo stan po wykonaniu. Mutacje linii zmienionych przed merge'em odpadły w próbie #1634: linię z Ważnego wskazały w 3 z 5 PR-ów, a żaden przebieg nie zmieścił się w 10 minutach.
  Powód klas `typ` i `test-klasy`: bramka, która przyjmowała tylko regułę ast-grep, popychała autora na szczebel (d), choć wyższy działał, a automatyczny dowód typu i testu po czterech rundach przeglądu dało się obejść przez tekst wyjścia narzędzi; Maks 15.11.2026 wybrał recenzenta jako bramkę ([#1912](https://github.com/maximiseartai/MAXIMISEART-Dad/pull/1912#issuecomment-6902436281)), jak w [#1888](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1888#issuecomment-6902408070), i przyjął tę lukę zamiast maszynerii dowodu.
  Granica nocy w klasie `brak-testu`: noc psuje tylko zmienione linie `src/` i części `tools/`, więc PR, który zmienia same testy, nie dostaje mutanta, a granicy obiecanej w docstringu testu (plik „bez odczytu”, którego świat próbki nie ma) obecne operatory nie wyrażą. Próbkę, która nie może paść na złej implementacji z docstringu testu, łapie więc tylko przegląd, według punktu w „Co jest porażką” skilla `przeglad` i zasady w „Test Surface” `CODING_STANDARDS.md`.
  Powód: 7 takich Ważnych w 3 PR-ach z 9–15.11.2026 (#1853, #1869, #1909) dostało 0 mutantów nocy, a odmowa w świecie próbki łapała 2 z 7 i odpalała na każdym z 20 ostatnich scalonych PR-ów; Maks 17.11.2026 wybrał zdanie zamiast mechanizmu ([#2006](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/2006)).

### Issues „Chwast”

- **Bez listy.** Otwarte issues „Chwast” zamykamy z odsyłaczem do raportu tygodniowego i nie zakładamy nowych.
  Powód: zgłoszenia na liście poza przepływem pracy dały w Meta 0% naprawień wobec ponad 70% w diffie (Distefano i in., CACM 2019), a u nas jest 26 otwartych i 0 zamkniętych.

### Stary checkout

- **Status w Actions.** Status „Werdykt i bramka” w GitHub Actions liczy bramkę kodem bazy PR, a ruleset `main` wymaga go od 14.11.2026 13:21 (`gh api repos/maximiseartai/MAXIMISEART-Dad/rules/branches/main`: `Required CI status` i `Werdykt i bramka`), więc stary checkout bramki nie omija.
  Powód: 12 merge'y, których bramka z kodu `main` by odmówiła, przeszło przez `tools/scal_pr.py` sprzed bramki, a ślad tego zostaje tylko w lokalnych transkryptach.

### Miara

| Miara | Baza 14.11.2026 | Cel |
|---|---|---|
| Prawdziwe powroty odmawiane przez Required CI | 0 z 11 | co najmniej 5 z 11: 4 wyrażalne i 2 częściowo, bez #1585 W1 r2 (`write_text`), którego linia była na `main` przed PR, więc nie jest dodaną linią |
| Powroty idiomu wśród wystąpień | 11 z 94 | poniżej 8% (próg z wyboru, nie z pomiaru) |
| Czekanie od `PASS` i zielonego CI do merge'a | mediana 4,9 h | poniżej 1 h |
| Fałszywe alarmy reguły na `RULE_PRS` ostatnich PR-ach | `write_text` 18 w 6 z 20 | najwyżej `FALSE_ALARMS` (stałe w `tools/na_scalonych_pr.py`), powyżej zawężamy albo usuwamy regułę |

Odczyt 11.12.2026 z ADR 0034 (#1636) zostaje i czyta te liczby (wiersz „Tickety o issues „Chwast”” w tabeli „Wdrożenie”).
Gdy odczyt pokaże zły wynik, wracamy do reguły pisanej w PR drugiego wystąpienia z blokadą w Required CI zamiast sprawdzenia w `tools/scal_pr.py`.

## Wdrożenie

| Decyzja | Wykonawca | Do jego merge'a obowiązuje |
|---|---|---|
| Chwast to reguła detektora | reguły ast-grep w Required CI: #1699 (scalony); kontrakty import-linter: #1612; `banned-api` ruff jest już w CI | reguła spoza tych narzędzi nie jest chwastem |
| Warunek merge'a z polem `Idiom:`, dowód reguły w `tools/scal_pr.py`, usunięcie Q11 i `ZGODA KORZEŃ` | PR bramki ticketu #1676 (zmienia `tools/lib/bramka_korzenia.py`, `tools/scal_pr.py` i skille `przeglad` i `pr`) | bramka z ADR 0031 |
| Reguła chwastu niczego nie ukrywa poza właścicielem | tłumienie w komentarzu: krok Required CI „Weed rules of the whole tree”; osłabienie reguły w PR, który ona sądzi: warunek 6 `tools/scal_pr.py` (reguły z bazy na liniach PR) obok zapadki Required CI (reguły z HEAD) | osłabienie reguły w jej konfiguracji ukrywa odpalenie przed CI; reguła przejściowa pod tabelą |
| Bez nowych issues „Chwast” | ten sam PR bramki usuwa każdą drogę zakładania: `rejestr_korzeni.after_verdict` przy publikacji werdyktu i `tools/chwasty.py` (`settle`); spis zapachów #1627, którego zakres ten ADR zmienia, rosnący zapach podaje w raporcie, a nie w issue | publikacja werdyktu i `tools/chwasty.py` zakładają issues jak dziś |
| Zamknięcie otwartych issues „Chwast” z odsyłaczem do raportu | właściciel #1676, jednorazowo zaraz po merge'u PR bramki | issues zostają otwarte |
| Narzędzie dowodu reguły | #1697 (`tools/na_scalonych_pr.py --regula`), które samo żadnej reguły merge'a nie zmienia | dowód liczy się ręcznie |
| Status „Werdykt i bramka” w Actions, tylko raport | PR statusu ticketu #1676 | merge ze starego checkoutu nie zostawia śladu na GitHubie |
| Miara Q1: ucieczki, powroty idiomu, czekanie, fałszywe alarmy reguł, lista `Idiom: bez reguły` i pole „trigger” w poniedziałkowym raporcie | #1626, którego zakres ten ADR zmienia: zgody znikają, a zostają merge'e poza `tools/scal_pr.py` | raport liczy powtórzenia kodów jak w ADR 0031 |
| Tickety, których przedmiotem jest issue „Chwast” albo stara miara: #1619, #1621, #1626, #1627, #1636, #1640 (decyzje ADR 0034 „Autor wyrywa swój chwast”, „Kolejka”, „Ogrodnik”, „Rejestr liczy zgody i obejścia”, spis zapachów i odczyt 11.12) | właściciel #1676: komentarz zmiany zakresu w każdym z nich przed merge'em tego ADR, a #1619 i #1640 zamyka po merge'u PR bramki | tickety stoją; #1619 i #1621 nie mają `ready-for-agent` |

Reguła przejściowa: do merge'a warunku 6 `tools/scal_pr.py` osłabienie reguły ast-grep w PR, który ona sądzi, było Ważnym w przeglądzie (punkt „Co jest porażką” skilla [`przeglad`](../../.agents/skills/przeglad/SKILL.md), usunięty razem z nim).
Sam warunek `Idiom:` nie otwiera nowej drogi ukrycia wobec stanu sprzed tego ADR, bo tłumienie i zwolnienie były możliwe także wtedy.
Pozostałe wiersze PR bramki wchodzą jednym merge'em, więc warunek `Idiom:` nie obowiązuje bez końca zakładania issues.

## Odrzucone warianty

- **Kod korzenia jako jednostka chwastu (ADR 0031).** 36 z 47 powrotów łączy tylko etykieta, więc bramka żąda szczebla wyżej od mechanizmu, którego wcześniejsze wyrwanie nie mogło objąć.
- **Powrót kodu w obszarze kodu (#1678).** Zostawia 29 z 47 powrotów, dalej z samej etykiety, i rozszerza zgodę z konta, które scala.
- **Zgoda koordynatora po `PASS` (#1678).** Linia z konta, które scala, niczego nie sprawdza ponad `PASS`.
- **Zgoda tylko Maksa przed merge'em (ADR 0031).** 21 h czekania w jednej nocy, a 12 merge'y, których bramka by odmówiła, i tak ją ominęło.
- **Osobny korpus próbek `tests/chwasty/<rodzaj>/<reguła>/`.** Druga postać obok natywnych próbek reguł i `ZNANE_LUKI`, czyli dwie drogi do jednej rzeczy.
- **Reguła bez pomiaru fałszywych alarmów.** Reguła `write_text` zatrzymałaby 6 z 20 poprawnych PR-ów, a agent uczy się obchodzić strażnika, który myli się często.
- **Issues „Chwast” z kolejką (#1620) i ogrodnikiem (#1621).** Lista poza diffem daje najmniej naprawień, a u nas żadne z 26 nie jest zamknięte.
- **Mechanizm SĘDZIA w `tools/scal_pr.py` jako jedyna ochrona.** Chroni tylko checkouty nowsze niż #1579, a scal_pr ze starego checkoutu nie zostawia śladu na GitHubie.
- **Udział powtórzonych kodów jako główna miara (Q1).** Mierzy szerokość listy kodów, a nie to, czy wyrwanie trzyma.

## Konsekwencje

- Do merge'a wykonawców z tabeli „Wdrożenie” obowiązuje stara bramka z ADR 0031, a odpalenie reguły ast-grep da się ukryć komentarzem `# ast-grep-ignore` (sonda przeglądu #1693 r5); od merge'a PR bramki do merge'a kroku „Weed rules of the whole tree” łapało to tylko przegląd (reguła przejściowa).
- Liczby z Kontekstu to jeden dzień pracy (94 wystąpienia), a podział 47 powrotów zrobił jeden oceniający; przy szerszym czytaniu porażek wyrwania jest 3–4 zamiast 1.
  Pierwszy krok pomiaru to drugi niezależny oceniający na tych samych 47 wierszach.
- Dowód reguły liczy `tools/na_scalonych_pr.py` z kodu bazy PR, więc wynik nie zależy od recenzenta; poza osądem zostaje tylko wybór postaci `bez reguły` i dowód mutacji klas `typ` i `test-klasy`, a raport liczy tę postać co tydzień.
- Reguła łapie tylko to, co skan czyta: skan bez ukrytych katalogów pominąłby `.agents/`, gdzie leżała jedyna porażka wyrwania.
- Pole nazywa się `Idiom:`, a nie `Wzorzec:`, bo Wzorzec to pojęcie domeny z [`GLOSSARY.md`](../../GLOSSARY.md).
