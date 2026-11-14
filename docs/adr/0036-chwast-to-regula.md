# ADR 0036: Chwast to reguła

## Status

Przyjęta na mandat Maksa z nocy 14/15.11.2026 (pełna samodzielność, uzgodnione z koordynatorem #1597); do przejrzenia przez Maksa; odwracalna przez revert.
Zmienia [ADR 0031](0031-korzen-po-fail-i-chwasty.md) w decyzjach Q1 (miara), Q11 (szczebel wyżej przy powrocie i `ZGODA KORZEŃ`), Q12, Q15 i Q22 (issues „Chwast”).
Zmienia [ADR 0034](0034-kod-jest-pamiecia.md) w decyzjach „Rejestr liczy zgody i obejścia”, „Autor wyrywa swój chwast”, „Kolejka” i „Ogrodnik”, bo ich przedmiotem jest issue „Chwast”, oraz w mierze odczytu 11.12.2026.
Zastępuje propozycję z PR #1678, zamkniętego bez merge'u, więc numer 0035 zostaje wolny.

Ten ADR wchodzi bez zmiany kodu, skilli i bramki.
Zmienia je następny PR ticketu #1676, a do jego merge'a obowiązuje dotychczasowe zdanie [`AGENTS.md`](../../AGENTS.md), skilli [`przeglad`](../../.agents/skills/przeglad/SKILL.md) i [`pr`](../../.agents/skills/pr/SKILL.md) oraz `tools/scal_pr.py`.

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
Z 13 PR-ów scalonych bez zgody, której bramka wymagała, 12 scaliło `tools/scal_pr.py` ze starego checkoutu sprzed bramki, z wynikiem `SCAL OK` i bez śladu na GitHubie; 13. przepuściła reguła wdrożenia (Q20).
Z 26 issues „Chwast” żadne nie jest zamknięte.

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
  Powód: bramka zgody dała 21 h czekania i 5 zgód z konta agentów, a 12 z 13 merge'y bez zgody ominęło ją przez stary checkout.

### Drugie wystąpienie idiomu

- **Pole werdyktu.** Recenzent oznacza drugie wystąpienie idiomu polem Ważnego `Wzorzec: jak #N Wn rk` (pierwsze wystąpienie bez reguły) albo `Wzorzec: <id reguły>` (ucieczka istniejącej reguły).
  Powód: jawne oznaczenie daje deterministyczne źródło klastra, a grupowanie modelem zależałoby od zgodności oceniających, której nikt nie zmierzył.
- **Warunek merge'a.** PR z takim Ważnym scala się dopiero wtedy, gdy jego diff dodaje albo rozszerza regułę tego wzorca, albo dodaje próbkę `ZNANE_LUKI` dla reguły, której mechanizm tej postaci nie wyrazi, i sprawdza to deterministycznie `tools/scal_pr.py`, bez linii zgody.
  Powód: reguła pisana w PR drugiego wystąpienia ma autora z kontekstem, a próbka znanej luki zapisuje granicę w kodzie, który pada, gdy przestaje być prawdą (ADR 0034).
- **Dowód reguły.** Regułę przyjmuje się z wynikiem `tools/na_scalonych_pr.py` w Evidence PR: łapie `Gdzie` każdego przypadku na dodanych liniach do SHA werdyktu `FAIL` i ma najwyżej 10% fałszywych alarmów na dodanych liniach 20 ostatnich scalonych PR-ów.
  Powód: 10% to próg Google Tricorder dla analiz w review, a reguła `write_text` dała 18 alarmów w 6 z 20 PR-ów bez żadnego znanego defektu, a reguła lokatora tytułu 0 alarmów i złapała jedyną porażkę wyrwania.
- **Idiom bez formy.** Idiom, którego żaden z tych mechanizmów nie wyrazi (brak testu, stan po kroku), idzie do mutacji zmienionych linii (#1634) albo do raportu jako klaster i nie zatrzymuje merge'a.
  Powód: z 11 prawdziwych powrotów regułą da się wyrazić 4, częściowo 2, a 5 to braki testu albo stan po wykonaniu.

### Issues „Chwast”

- **Bez listy.** Otwarte issues „Chwast” zamykamy z odsyłaczem do raportu tygodniowego i nie zakładamy nowych.
  Powód: zgłoszenia na liście poza przepływem pracy dały w Meta 0% naprawień wobec ponad 70% w diffie (Distefano i in., CACM 2019), a u nas jest 26 otwartych i 0 zamkniętych.

### Stary checkout

- **Status w Actions.** Status „Werdykt i bramka” w GitHub Actions liczy bramkę kodem bazy PR i na razie tylko raportuje.
  Włączenie go jako wymaganego w rulesecie należy do Maksa, bo 13.11.2026 wyłączył blokady po stronie serwera (ADR 0034, „Odrzucone warianty”), więc do tej decyzji stary checkout może ominąć bramkę.
  Powód: 12 z 13 merge'y bez zgody przeszło przez `tools/scal_pr.py` sprzed bramki, a ślad tego zostaje tylko w lokalnych transkryptach.

### Miara

| Miara | Baza 14.11.2026 | Cel |
|---|---|---|
| Prawdziwe powroty odmawiane przez Required CI | 0 z 11 | co najmniej 6 z 11 (4 wyrażalne i 2 częściowo) |
| Powroty idiomu wśród wystąpień | 11 z 94 | poniżej 8% (próg z wyboru, nie z pomiaru) |
| Czekanie od `PASS` i zielonego CI do merge'a | mediana 4,9 h | poniżej 1 h |
| Fałszywe alarmy reguły na 20 ostatnich PR-ach | `write_text` 18 w 6 z 20 | najwyżej 10%, powyżej zawężamy albo usuwamy regułę |

Odczyt 11.12.2026 z ADR 0034 (#1636) zostaje i czyta te liczby.
Gdy odczyt pokaże zły wynik, wracamy do reguły pisanej w PR drugiego wystąpienia z blokadą w Required CI zamiast sprawdzenia w `tools/scal_pr.py`.

## Odrzucone warianty

- **Kod korzenia jako jednostka chwastu (ADR 0031).** 36 z 47 powrotów łączy tylko etykieta, więc bramka żąda szczebla wyżej od mechanizmu, którego wcześniejsze wyrwanie nie mogło objąć.
- **Powrót kodu w obszarze kodu (#1678).** Zostawia 29 z 47 powrotów, dalej z samej etykiety, i rozszerza zgodę z konta, które scala.
- **Zgoda koordynatora po `PASS` (#1678).** Linia z konta, które scala, niczego nie sprawdza ponad `PASS`.
- **Zgoda tylko Maksa przed merge'em (ADR 0031).** 21 h czekania w jednej nocy, a 12 z 13 merge'y bez zgody i tak ją ominęło.
- **Osobny korpus próbek `tests/chwasty/<rodzaj>/<reguła>/`.** Druga postać obok natywnych próbek reguł i `ZNANE_LUKI`, czyli dwie drogi do jednej rzeczy.
- **Reguła bez pomiaru fałszywych alarmów.** Reguła `write_text` zatrzymałaby 6 z 20 poprawnych PR-ów, a agent uczy się obchodzić strażnika, który myli się często.
- **Issues „Chwast” z kolejką (#1620) i ogrodnikiem (#1621).** Lista poza diffem daje najmniej naprawień, a u nas żadne z 26 nie jest zamknięte.
- **Mechanizm SĘDZIA w `tools/scal_pr.py` jako jedyna ochrona.** Chroni tylko checkouty nowsze niż #1579, a scal_pr ze starego checkoutu nie zostawia śladu na GitHubie.
- **Udział powtórzonych kodów jako główna miara (Q1).** Mierzy szerokość listy kodów, a nie to, czy wyrwanie trzyma.

## Konsekwencje

- Liczby z Kontekstu to jeden dzień pracy (94 wystąpienia), a podział 47 powrotów zrobił jeden oceniający; przy szerszym czytaniu porażek wyrwania jest 3–4 zamiast 1.
  Pierwszy krok pomiaru to drugi niezależny oceniający na tych samych 47 wierszach.
- `tools/scal_pr.py` sprawdza, że diff dodaje albo rozszerza regułę, ale nie odtwarza jej dowodu; wynik `tools/na_scalonych_pr.py` ocenia recenzent jak każde Evidence.
- Reguła łapie tylko to, co skan czyta: skan bez ukrytych katalogów pominąłby `.agents/`, gdzie leżała jedyna porażka wyrwania.
- Do decyzji Maksa o rulesecie stary checkout może scalić PR bez bramki, a status „Werdykt i bramka” pokazuje to po fakcie.
- Pole `Wzorzec:` w werdykcie nazywa idiom kodu, a nie Wzorzec rozliczenia z [`GLOSSARY.md`](../../GLOSSARY.md).
