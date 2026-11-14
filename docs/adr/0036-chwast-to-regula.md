# ADR 0036: Chwast to reguła

## Status

Przyjęta na mandat Maksa z nocy 14/15.11.2026 (pełna samodzielność, uzgodnione z koordynatorem #1597); do przejrzenia przez Maksa; odwracalna przez revert.
Zmienia [ADR 0031](0031-korzen-po-fail-i-chwasty.md) w decyzjach Q1 (miara), Q11 (szczebel wyżej przy powrocie i `ZGODA KORZEŃ`), Q12, Q15, Q16 i Q22 (issues „Chwast”) oraz Q26 (powrót po (e) idzie do Maksa).
Zmienia [ADR 0034](0034-kod-jest-pamiecia.md) w decyzjach „Rejestr liczy zgody i obejścia”, „Autor wyrywa swój chwast”, „Kolejka” i „Ogrodnik”, bo ich przedmiotem jest issue „Chwast”, oraz w mierze odczytu 11.12.2026; „Cztery źródła” zostają źródłami wystąpień, ale żadne z nich nie zakłada już issue.
Zastępuje propozycję z PR #1678, zamkniętego bez merge'u, więc numer 0035 zostaje wolny.

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

- **Pole werdyktu.** Pole pisze recenzent, nie autor. Ma jedną z trzech postaci:
  - `Idiom: <id> jak #N Wn rk`, gdy to drugie wystąpienie idiomu, który nie ma jeszcze reguły, a `<id>` to id reguły, którą PR ma dodać;
  - `Idiom: <id>`, gdy to ucieczka istniejącej reguły `<id>`;
  - `Idiom: bez reguły <klasa> jak #N Wn rk`, gdy żaden mechanizm z sekcji „Jednostka chwastu” nie wyrazi idiomu, a `<klasa>` pochodzi z zamkniętej listy (`brak-testu`, `stan-kroku`).
  Powód: jawne oznaczenie daje deterministyczne źródło klastra, a grupowanie modelem zależałoby od zgodności oceniających, której nikt nie zmierzył. Autor nie wybiera postaci, więc nie może wybrać tańszej.
- **Warunek merge'a.** PR z Ważnym z polem `Idiom: <id>` albo `Idiom: <id> jak #N Wn rk` scala się tylko wtedy, gdy na HEAD PR istnieje reguła o id `<id>` (pole `id` reguły ast-grep, klucz `banned-api` albo nazwa kontraktu import-linter) i gdy jej dowód (niżej) przechodzi na przypadku z tego Ważnego.
  Próbka `ZNANE_LUKI` nigdy nie zastępuje reguły. Wolno ją dodać obok reguły, która łapie przypadek z `Gdzie`, dla formy siostrzanej, której mechanizm reguły nie wyrazi.
  Sprawdza to `tools/scal_pr.py` bez osądu i bez linii zgody.
  Powód: reguła pisana w PR drugiego wystąpienia ma autora z kontekstem, a gdyby próbka wystarczała, każdy idiom dałoby się zamknąć próbką, której reguła dziś nie łapie (R-ZAPADKA-OBEJSCIE).
- **Reguła chwastu niczego nie ukrywa poza właścicielem.** Odpalenia reguły chwastu nie da się ukryć tańszą drogą niż zmiana reguły z jej dowodem: ani tłumieniem, ani zwolnieniem poza prawem właściciela z `AGENTS.md`.
  Mechanizm, który to sprawdza w Required CI, i jego granicę wyznacza PR kroku ukryć ticketu #1676, a granicę pokazują próbki `ZNANE_LUKI` w jego teście, nie ten ADR. Formy, które musi rozstrzygnąć, zebrały przeglądy #1693 r1–r4 w [komentarzu #1676](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1676#issuecomment-6871386075).
  Powód: cztery rundy przeglądu tego ADR znalazły cztery formy ukrycia w prozie, w tym zwolnienie całego `TID251` dla 16 plików właścicieli, które istnieje już na `main`. Granicę mechanizmu da się sprawdzić tylko na kodzie z testem.
- **Dowód reguły.** Regułę przyjmuje się tylko z wynikiem `tools/na_scalonych_pr.py`, który `tools/scal_pr.py` uruchamia z kodu bazy PR: łapie `Gdzie` każdego przypadku tej reguły z historii jej pól `Idiom:` (nie tylko bieżącego) na dodanych liniach do SHA werdyktu `FAIL` i ma najwyżej 10% fałszywych alarmów na dodanych liniach 20 ostatnich scalonych PR-ów.
  Powód: 10% to próg Google Tricorder dla analiz w review, a reguła `write_text` dała 18 alarmów w 6 z 20 PR-ów bez żadnego znanego defektu, a reguła lokatora tytułu 0 alarmów i złapała jedyną porażkę wyrwania.
- **Idiom bez reguły.** Ważne z polem `Idiom: bez reguły <klasa>` nie zatrzymuje merge'a. Klasa `brak-testu` zostaje nocnym mutacjom ([ADR 0021](0021-mutacje-noca.md)), a każde takie Ważne trafia do poniedziałkowego raportu z linkiem.
  To jedyne miejsce osądu w pętli. Pisze je niezależny recenzent, a recenzent następnej rundy daje Ważne, gdy pokaże regułę, która ten idiom wyraża.
  Powód: z 11 prawdziwych powrotów regułą da się wyrazić 4, częściowo 2, a 5 to braki testu albo stan po wykonaniu. Mutacje linii zmienionych przed merge'em odpadły w próbie #1634: linię z Ważnego wskazały w 3 z 5 PR-ów, a żaden przebieg nie zmieścił się w 10 minutach.

### Issues „Chwast”

- **Bez listy.** Otwarte issues „Chwast” zamykamy z odsyłaczem do raportu tygodniowego i nie zakładamy nowych.
  Powód: zgłoszenia na liście poza przepływem pracy dały w Meta 0% naprawień wobec ponad 70% w diffie (Distefano i in., CACM 2019), a u nas jest 26 otwartych i 0 zamkniętych.

### Stary checkout

- **Status w Actions.** Status „Werdykt i bramka” w GitHub Actions liczy bramkę kodem bazy PR i na razie tylko raportuje.
  Włączenie go jako wymaganego w rulesecie należy do Maksa, bo 13.11.2026 wyłączył blokady po stronie serwera (ADR 0034, „Odrzucone warianty”), więc do tej decyzji stary checkout może ominąć bramkę.
  Powód: 12 merge'y, których bramka z kodu `main` by odmówiła, przeszło przez `tools/scal_pr.py` sprzed bramki, a ślad tego zostaje tylko w lokalnych transkryptach.

### Miara

| Miara | Baza 14.11.2026 | Cel |
|---|---|---|
| Prawdziwe powroty odmawiane przez Required CI | 0 z 11 | co najmniej 5 z 11: 4 wyrażalne i 2 częściowo, bez #1585 W1 r2 (`write_text`), którego linia była na `main` przed PR, więc nie jest dodaną linią |
| Powroty idiomu wśród wystąpień | 11 z 94 | poniżej 8% (próg z wyboru, nie z pomiaru) |
| Czekanie od `PASS` i zielonego CI do merge'a | mediana 4,9 h | poniżej 1 h |
| Fałszywe alarmy reguły na 20 ostatnich PR-ach | `write_text` 18 w 6 z 20 | najwyżej 10%, powyżej zawężamy albo usuwamy regułę |

Odczyt 11.12.2026 z ADR 0034 (#1636) zostaje i czyta te liczby (wiersz „Tickety o issues „Chwast”” w tabeli „Wdrożenie”).
Gdy odczyt pokaże zły wynik, wracamy do reguły pisanej w PR drugiego wystąpienia z blokadą w Required CI zamiast sprawdzenia w `tools/scal_pr.py`.

## Wdrożenie

| Decyzja | Wykonawca | Do jego merge'a obowiązuje |
|---|---|---|
| Chwast to reguła detektora | reguły ast-grep w Required CI: #1699 (scalony); kontrakty import-linter: #1612; `banned-api` ruff jest już w CI | reguła spoza tych narzędzi nie jest chwastem |
| Warunek merge'a z polem `Idiom:`, dowód reguły w `tools/scal_pr.py`, usunięcie Q11 i `ZGODA KORZEŃ` | PR bramki ticketu #1676 (zmienia `tools/lib/bramka_korzenia.py`, `tools/scal_pr.py` i skille `przeglad` i `pr`) | bramka z ADR 0031 |
| Reguła chwastu niczego nie ukrywa poza właścicielem | PR kroku ukryć ticketu #1676, krok Required CI z kryteriami z [komentarza #1676](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1676#issuecomment-6871386075) | tłumienie i zwolnienie w konfiguracji ukrywają odpalenie przed CI; reguła przejściowa pod tabelą |
| Bez nowych issues „Chwast” | ten sam PR bramki usuwa każdą drogę zakładania: `rejestr_korzeni.after_verdict` przy publikacji werdyktu i `tools/chwasty.py` (`settle`); spis zapachów #1627, którego zakres ten ADR zmienia, rosnący zapach podaje w raporcie, a nie w issue | publikacja werdyktu i `tools/chwasty.py` zakładają issues jak dziś |
| Zamknięcie otwartych issues „Chwast” z odsyłaczem do raportu | właściciel #1676, jednorazowo zaraz po merge'u PR bramki | issues zostają otwarte |
| Narzędzie dowodu reguły | #1697 (`tools/na_scalonych_pr.py --regula`), które samo żadnej reguły merge'a nie zmienia | dowód liczy się ręcznie |
| Status „Werdykt i bramka” w Actions, tylko raport | PR statusu ticketu #1676 | merge ze starego checkoutu nie zostawia śladu na GitHubie |
| Miara Q1: ucieczki, powroty idiomu, czekanie, fałszywe alarmy reguł, lista `Idiom: bez reguły` i pole „trigger” w poniedziałkowym raporcie | #1626, którego zakres ten ADR zmienia: zgody znikają, a zostają merge'e poza `tools/scal_pr.py` | raport liczy powtórzenia kodów jak w ADR 0031 |
| Tickety, których przedmiotem jest issue „Chwast” albo stara miara: #1619, #1621, #1626, #1627, #1636, #1640 (decyzje ADR 0034 „Autor wyrywa swój chwast”, „Kolejka”, „Ogrodnik”, „Rejestr liczy zgody i obejścia”, spis zapachów i odczyt 11.12) | właściciel #1676: komentarz zmiany zakresu w każdym z nich przed merge'em tego ADR, a #1619 i #1640 zamyka po merge'u PR bramki | tickety stoją; #1619 i #1621 nie mają `ready-for-agent` |

Reguła przejściowa: do merge'a PR kroku ukryć tłumienie albo zwolnienie reguły chwastu na dodanej linii to Ważne w przeglądzie (punkt „Co jest porażką” skilla [`przeglad`](../../.agents/skills/przeglad/SKILL.md)).
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

- Do merge'a wykonawców z tabeli „Wdrożenie” obowiązuje stara bramka z ADR 0031, a odpalenie reguły ast-grep da się ukryć komentarzem `# ast-grep-ignore` (sonda przeglądu #1693 r5); od merge'a PR bramki do merge'a PR kroku ukryć łapie to tylko przegląd (reguła przejściowa).
- Liczby z Kontekstu to jeden dzień pracy (94 wystąpienia), a podział 47 powrotów zrobił jeden oceniający; przy szerszym czytaniu porażek wyrwania jest 3–4 zamiast 1.
  Pierwszy krok pomiaru to drugi niezależny oceniający na tych samych 47 wierszach.
- Dowód reguły liczy `tools/na_scalonych_pr.py` z kodu bazy PR, więc wynik nie zależy od recenzenta; poza osądem zostaje tylko wybór postaci `bez reguły`, którą raport liczy co tydzień.
- Reguła łapie tylko to, co skan czyta: skan bez ukrytych katalogów pominąłby `.agents/`, gdzie leżała jedyna porażka wyrwania.
- Do decyzji Maksa o rulesecie stary checkout może scalić PR bez bramki, a status „Werdykt i bramka” pokazuje to po fakcie od merge'a jego wykonawcy z tabeli „Wdrożenie”.
- Pole nazywa się `Idiom:`, a nie `Wzorzec:`, bo Wzorzec to pojęcie domeny z [`GLOSSARY.md`](../../GLOSSARY.md).
