# ADR 0044: rt2 w usterce się nie liczy

## Status

Zaakceptowana (odpowiedź taty z 16.11.2026 przekazana przez Maksa; decyzje koordynatora tam, gdzie odpowiedź czegoś nie
rozstrzyga, nazwane niżej). Zmienia to zdanie [ADR 0039](0039-opis-zlecenia-to-same-kody-czynnosci.md), punkt „Dane
legendy z Wydania”:

- „Każde `rt2` daje `AM` (1, 2; decyzja koordynatora: „nie uwzględniamy usterek” czytamy jako „bez osobnej reguły dla
  usterek”, a gdy tata miał na myśli, że w usterce `rt2` się nie liczy, zmieni to Wydanie)”: tata miał to na myśli, więc
  `rt2` daje `AM` tylko poza usterką.

## Kontekst

ADR 0039 przeczytał odpowiedź taty „każde `rt2`, nie uwzględniamy usterek” jako brak osobnej reguły dla usterek i
zostawił drugie znaczenie do Wydania. Tata odpowiedział: „NIE, PRZY USTERKACH NIE LICZY SIĘ RT2”. Dziś każde `rt2` daje
1 w `AM`, czerwone `AM` i zielone `AF`, także w usterce.

Pozostałe odpowiedzi z tego samego maila niczego nie zmieniają, bo tak już jest: zwykły opis obok kodów nie jest błędem
([ADR 0041](0041-przypomnienie-tylko-bez-raportu.md)), zielone pole w Rozliczeniu pracownika dostaje 1, czerwone i
zielone w kolumnach tekstowych zostają bez zmian, pusty opis i samo `tak` nie są błędem, a wielkość liter nie ma
znaczenia (ADR 0039).

## Decyzja

- **Kod, który w usterce się nie liczy, to dana legendy.** Kod czynności ma w Legendzie czynności znacznik „w usterce się
  nie liczy” (w pliku `w_usterce: false`, w formularzu kodu „Nie liczy się w usterce”), bo legenda należy do taty
  ([ADR 0038](0038-legenda-czynnosci-wyznacza-ilosci-z-opisu-technika.md)), a nie stały identyfikator w kodzie.
- **W usterce taki kod jest kodem, ale niczego nie wyznacza** (decyzja koordynatora). Legenda rozpoznaje go w opisie,
  więc tata widzi go w widoku Raporty i nie ma „BRAK KODU”, ale w usterce nie daje Ilości usług, kwoty ani koloru i nie
  bierze udziału w Błędzie opisu (kolumna trafiona drugi raz, dwa kolory, liczba spoza przedziałów). Opis usterki z samym
  `rt2` to opis z kodami, więc wiersz nie czeka na tatę w kolumnach z opisu technika, a `rt2 bypas5m` w usterce daje
  `AM` z `bypas`, bez Błędu opisu.
- **Usterka to wiersz z Ilością usług w `AI` z Reguł ilości** (decyzja koordynatora). Tak nazywa ją
  [`GLOSSARY.md`](../../GLOSSARY.md) („Usterka (ilość w `AI`)”), a Przygotowanie pliku zbiorczego, Kontrola ilości,
  Ilości do uzupełnienia i podgląd zmiany legendy liczą ją z tego samego Wpisu narzędzia (`tool_entry`), więc wszystkie
  widzą tę samą usterkę. Wiersz bez wyniku Reguł ilości (`DATA` nie jest datą) nie jest usterką.
- **Widok Raporty czyta opis jak poza usterką** (decyzja koordynatora). Wpis raportu nie ma Ilości usług w `AI`, a
  zgadywanie usterki z innych kolumn byłoby drugą definicją. Kody czynności przy zleceniu są te same w usterce i poza
  nią; różnica jest tylko w Błędzie opisu z udziałem `rt2` (np. `rt2 bypas5m`), który tata zobaczy też przy usterce, choć
  Przygotowanie go tam nie liczy. Wolimy taki nadmiarowy błąd niż ukryty błąd poza usterką.
- **Zmiana z Wydania ustawia znacznik tylko przy `rt2` taty** (decyzja koordynatora). Wpis
  `2026-11-rt2-bez-usterek` w `RELEASE_CHANGES` zmienia w legendzie taty tylko znacznik kodu o id `rt2`, z wierszem
  Historii Ustawień i „Cofnij”. Kolumnę, kwotę i kolory, które tata ustawił sam, zostawia, a gdy tata `rt2` usunął,
  niczego nie dodaje. Tata bez własnego pliku legendy liczy legendą z Wydania, więc u niego zmiana zapisuje plik
  legendy z Wydania z tym znacznikiem. Plik legendy z Wydania (`legenda_czynnosci_domyslna.yaml`) się nie zmienia.

## Odrzucone warianty

- **Stały identyfikator `rt2` w kodzie.** Działałby od razu, ale tata nie mógłby go zmienić ani dodać innego kodu, który
  w usterce się nie liczy, bez Wydania.
- **W usterce `rt2` jak słowo spoza legendy.** Opis usterki z samym `rt2` miałby wtedy „BRAK KODU” i czekałby na tatę w
  Ilościach do uzupełnienia, choć Wykonawca napisał poprawny kod.
- **`set_codes` z kodem `rt2` z Wydania.** Nadpisałby kolumnę albo kolory, które tata ustawił przy `rt2` sam, i dodałby
  `rt2` z powrotem tacie, który go usunął.
