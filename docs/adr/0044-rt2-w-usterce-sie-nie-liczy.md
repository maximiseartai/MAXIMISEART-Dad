# ADR 0044: rt2 w usterce się nie liczy

## Status

Zaakceptowana (odpowiedź taty z 16.11.2026 przekazana przez Maksa; decyzje koordynatora tam, gdzie odpowiedź czegoś nie
rozstrzyga, nazwane niżej). Zmienia to zdanie [ADR 0039](0039-opis-zlecenia-to-same-kody-czynnosci.md), punkt „Dane
legendy z Wydania”:

- „Każde `rt2` daje `AM` (1, 2; decyzja koordynatora: „nie uwzględniamy usterek” czytamy jako „bez osobnej reguły dla
  usterek”, a gdy tata miał na myśli, że w usterce `rt2` się nie liczy, zmieni to Wydanie)”: tata miał to na myśli, więc
  `rt2` daje `AM` tylko poza usterką.

Zmieniona 20.11.2026 (decyzja Maksa: „trzeba zrobić tak, żeby Widok Raporty wiedział, że zlecenie to usterka”): widok
Raporty czyta opis Wpisu `tak` w usterce tak jak Przygotowanie pliku zbiorczego, z tą samą definicją usterki (sekcje
Decyzja i Odrzucone warianty). Jak to zrobić, rozstrzyga autor zmiany, nazwany przy każdym punkcie.

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
- **Widok Raporty wie, że zlecenie to usterka** (decyzja Maksa 20.11.2026, cytat w Statusie). Opis Wpisu `tak` z
  `rt2 bypas5m` w usterce nie ma w widoku Raporty Błędu opisu, tak jak w Przygotowaniu pliku zbiorczego.
- **Jedna definicja usterki dla Pliku zbiorczego i widoku Raporty** (decyzja autora zmiany 20.11.2026). Wynik Reguł
  ilości dla treści zlecenia (`quantity_engine.evaluated`) i usterkę z niego (`quantity_engine.is_fault`: Ilość usług w
  `AI`) liczą Wpis narzędzia i rdzeń raportów tą samą funkcją, a rdzeń raportów dostaje treść zlecenia (`UMOWA`,
  `URZĄDZENIA`, `CZYNNOŚCI`, `DATA`) z wiersza INTERMAX i Reguły ilości ze startu Uruchomienia, jak Legendę czynności.
  Powód: druga definicja (np. słowo `usterka` w `URZĄDZENIA`) rozjechałaby się z Regułami ilości taty, np. przy
  `usterka` obok składnika spoza Listy Urządzeń, który Reguły ilości liczą bez `AI`.
- **Zlecenie dopisane z raportu nie jest usterką** (decyzja autora zmiany 20.11.2026). INTERMAX nie ma jego wiersza, więc
  nie ma treści, z której Reguły ilości wyznaczą `AI`, tak jak wiersz bez wyniku Reguł ilości w Pliku zbiorczym.
- **Wpisanie raportów i Przypomnienia o raporcie liczą Regułami ilości ze startu** (decyzja autora zmiany 20.11.2026).
  Wpisanie raportów potrzebuje Reguł ilości jak Legendy czynności: start przy pliku Reguł ilości albo Listy Urządzeń bez
  odczytu odmawia, a praca przypomnień go pomija z powodem w dzienniku Centrum, bo obie operacje czytają okno z jednego
  wejścia rdzenia.
  Logi Wpisania raportów mają odtąd Reguły ilości, a odtworzenie Logów sprzed tej zmiany liczy Regułami ilości z Wydania
  z zastrzeżeniem.
- **Zmiana z Wydania ustawia znacznik tylko przy `rt2` taty** (decyzja koordynatora). Wpis
  `2026-11-rt2-bez-usterek` w `RELEASE_CHANGES` zmienia w legendzie taty tylko znacznik kodu o id `rt2`, z wierszem
  Historii Ustawień i „Cofnij”. Kolumnę, kwotę i kolory, które tata ustawił sam, zostawia, a gdy tata `rt2` usunął,
  niczego nie dodaje. Tata bez własnego pliku legendy liczy legendą z Wydania, więc u niego zmiana zapisuje plik
  legendy z Wydania z tym znacznikiem. Plik legendy z Wydania (`legenda_czynnosci_domyslna.yaml`) się nie zmienia.

## Odrzucone warianty

- **Widok Raporty czyta opis jak poza usterką** (decyzja koordynatora z 16.11.2026, zmieniona decyzją Maksa
  20.11.2026). Tata widziałby przy usterce Błąd opisu z udziałem `rt2`, którego Przygotowanie tam nie liczy.
- **Stały identyfikator `rt2` w kodzie.** Działałby od razu, ale tata nie mógłby go zmienić ani dodać innego kodu, który
  w usterce się nie liczy, bez Wydania.
- **W usterce `rt2` jak słowo spoza legendy.** Opis usterki z samym `rt2` miałby wtedy „BRAK KODU” i czekałby na tatę w
  Ilościach do uzupełnienia, choć Wykonawca napisał poprawny kod.
- **`set_codes` z kodem `rt2` z Wydania.** Nadpisałby kolumnę albo kolory, które tata ustawił przy `rt2` sam, i dodałby
  `rt2` z powrotem tacie, który go usunął.
