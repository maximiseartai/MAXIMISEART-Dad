# ADR 0026: Wycena w efenix dokańcza zlecenie do Pliku zbiorczego tylko w górę

## Status

Zaakceptowana (decyzja Maksa 5.11.2026 po odpowiedziach taty na pytania po
runie z 4.11.2026, #960). Odwraca historie 21, 22, 24, 25 i 31 specyfikacji
#741; historie 19 i 20 zostają.

## Kontekst

Wycena w efenix według specyfikacji #741 nie nadpisywała żadnej ilości Wyceny
Emmetta, dopisywała ilości z pliku tylko w pozycjach pustych u Emmetta, a
zlecenie z inną ilością u Emmetta albo z wyceną, która już jest i różni się od
pliku, zostawiała tacie bez zmian. Ślad Wyceny Emmetta na komputerze taty
odróżniał przy tym wycenę zaczętą przez narzędzie od wyceny taty, żeby ponowne
uruchomienie dokończyło tylko tę pierwszą.

Run okresu 20_26_10 z 4.11.2026 zostawił tacie 49 zleceń: 46 z Ostrzeżeniem
Emmetta i 3 z „wycena już jest i się różni”. Tata odpowiedział, że prawdziwy
jest Plik zbiorczy, a nie Wycena Emmetta: Emmett liczy w „Dostarczenie CPE do
klienta” (S, pozycja 016) tylko dekodery, a plik każde urządzenie, także router
i dodatkowe CPE. Tata dotąd ręcznie podnosił S, a INEA rozliczała to bez
poprawek. W Logach tego runu we wszystkich 49 zleceniach efenix ma w każdej
pozycji tyle albo mniej niż plik, a w żadnym ze 108 załadowań Emmetta żadna
pozycja nie przekracza pliku.

## Decyzja

- **Wycena w efenix dokańcza każde zlecenie do Pliku zbiorczego tylko w górę.**
  W każdej pozycji, w której efenix ma mniej niż plik, wpisuje ilość z pliku,
  także w miejsce ilości Emmetta i w wycenie, która już jest (zaczętej przez
  narzędzie, przez tatę albo samej Wycenie Emmetta).
- **Ilości w efenix nigdy nie obniża ani nie czyści.** Pozycja, w której efenix
  ma więcej niż plik (także przy 0 w pliku), zostaje bez zmian i daje
  Ostrzeżenie Emmetta z pozycją, kolumną i obiema ilościami, a resztę zlecenia
  narzędzie i tak dokańcza. Takie zlecenie nie dostaje Znacznika efenix.
- **Wycenę Emmetta ładuje tylko do zlecenia bez żadnej ilości** (historie 19 i
  20), bo „Załaduj do zlecenia” czyści wycenę. Do zlecenia z ilościami jej nie
  ładuje.
- **Zlecenie bez nadmiaru z kwotą końcową równą `Kwota` (AU) jest gotowe.**
  Kwota różna od AU to błąd z obiema kwotami, jak dotąd.
- **Ręczna zmiana taty w efenix w dół nie jest chroniona.** Ilość, którą tata
  zmniejszył albo usunął w efenix poniżej pliku, następny run wpisze z pliku z
  powrotem: tata poprawia Plik zbiorczy, a nie efenix. Zmiana w górę zostaje i
  daje Ostrzeżenie Emmetta.
- **Śladu Wyceny Emmetta nie ma.** Decyzja zależy tylko od ilości pliku i strony
  zlecenia, więc ponowne uruchomienie dokańcza zlecenie przerwane Zatrzymaniem
  albo zgaśnięciem Centrum tak samo jak każde inne. Plik śladu z
  `config/slad-wyceny-emmetta/` u taty narzędzie już nie czyta.

## Odrzucone warianty

- **Dalej nie nadpisywać Emmetta, tylko ostrzegać.** Tak było i dało 49 zleceń
  do ręcznego dokończenia w jednym okresie, choć tata za każdym razem robi to
  samo: podnosi ilość do pliku.
- **Wpisywać ilość z pliku w każdej pozycji, także w dół.** Obniżenie ilości w
  efenix zmienia rozliczenie z firmą bez wiedzy taty, a w Logach z 4.11 nie ma
  ani jednego zlecenia, które by tego potrzebowało. Nadmiar zostaje tacie.
- **Zostawić Ślad Wyceny Emmetta i dokańczać tylko wyceny zaczęte przez
  narzędzie.** Tata chce dokończenia także wycen, które zaczął sam albo które
  mają samą Wycenę Emmetta, a reguła „tylko w górę” nie potrzebuje wiedzieć, kto
  wycenę zaczął.
