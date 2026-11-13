# ADR 0013: Kontrola ilości wysyłana automatycznie do Skrzynki Zgłoszeń

## Status

Zaakceptowana. Dopełnia [ADR 0012](0012-ilosci-uslug-w-przygotowaniu-pliku-zbiorczego.md),
który wdraża Reguły ilości bez trybu cienia. Zmienia dwa zdania
[ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md):

- „Tata wysyła je jednym kliknięciem po Diagnozie i przed wysłaniem widzi jego
  dokładną treść”: dotyczy Zgłoszeń, a Kontrolę ilości Centrum wysyła samo;
- „Bez treści wierszy”: Kontrola ilości zawiera treść wybranych kolumn
  Wiersza danych.

Kontrolę ilości wysyła dziś wspólna kolejka Skrzynki Zgłoszeń
([ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md)).

[ADR 0033](0033-reguly-ilosci-naleza-do-taty.md) zmienia zdanie „Zmiana reguły wymaga potwierdzenia taty”: tata zmienia
regułę sam i widzi różnice z Kontroli ilości w Centrum.

## Kontekst

Plik zbiorczy ma dwa stany: Ilości usług wpisane przez Przygotowanie pliku
zbiorczego i Ilości po poprawkach taty, z których powstają Rozliczenia
pracowników. Różnica między nimi pokazuje, co tata nadal robi ręcznie i
którą Regułę ilości trzeba poprawić. Bez trybu cienia to jedyny sposób, żeby
Maks dowiedział się o błędnej regule, zanim tata sam ją zgłosi.

## Decyzja

- **Kontrola ilości przelicza, niczego nie przechowuje.** Po Przebiegu
  rozliczeń narzędzie stosuje Reguły ilości do tych samych Wierszy danych,
  które Przebieg już wczytał, i porównuje wynik z `N:AP` taty. Nie ma kopii
  stanu z Przygotowania. Dzięki temu Kontrola działa też dla okresów
  przygotowanych przed ADR 0012.
- **Nie spowalnia Przebiegu.** Plik nie jest czytany drugi raz, a wysyłka
  rusza dopiero po wyniku i nie wstrzymuje taty. Benchmark Przebiegu
  rozliczeń potwierdza, że czas nie zmienia się ponad szum pomiaru.
- **Wysyła ją Centrum, samo i po cichu.** Kontrola powstaje po każdym
  Przebiegu z Centrum zakończonym sukcesem albo wynikiem wymagającym
  sprawdzenia. Nie powstaje ze Skryptu dla maszyn. Tata niczego nie klika i
  nic nie widzi. Gdy brakuje sieci albo klucza, Kontrola zostaje w
  `config/zgloszenia/` i Centrum ponawia ją przy następnym starcie, bez
  Komunikatu. Od #438 kolejka Skrzynki Zgłoszeń ponawia ją też sama minutę
  po nieudanej próbie (ADR 0015).
- **Jeden okres to jedno issue** z etykietą `kontrola-ilosci`, także przy zera
  różnic. Powtórzony Przebieg okresu dopisuje komentarz do otwartego issue.
- **Treść:**
  - dla kolumn wyznaczanych przez Reguły ilości: grupy różnic według
    dokładnego tekstu `URZĄDZENIA`, z `CZYNNOŚCI`, `UMOWA`, dniem tygodnia i
    godziną z `DATA`, wartością reguły, wartością taty i liczbą wierszy;
  - dla kolumn z opisu technika: liczba wypełnionych wierszy w każdej kolumnie;
  - nigdy: adres, numer zlecenia, numer umowy, Wykonawca, data dzienna i
    `CZYNNOŚCI ZREALIZOWANE`. Opis technika to wolny tekst, w którym może być
    nazwisko albo telefon klienta. Wejdzie osobną decyzją, gdy powstaną reguły
    z opisu.
- **Poluzowanie prywatności dotyczy tylko Kontroli ilości.** Komunikaty,
  Zdarzenia przebiegu, dziennik, metryki i Zgłoszenia nadal nie zawierają
  treści wierszy według ADR 0004 i ADR 0007. Kontrola ilości trafia wyłącznie
  do prywatnej Skrzynki Zgłoszeń.
- **Przegląd na żądanie.** Maks przegląda Kontrolę ilości w sesji z agentem.
  Zmiana reguły wymaga potwierdzenia taty. PR w publicznym repozytorium
  odwołuje się tylko do numeru issue, a przypadek testowy jest na danych
  syntetycznych.

## Odrzucone warianty

- **Kopia Ilości z Przygotowania w Folderze okresu.** Pokazałaby też poprawki
  taty w `URZĄDZENIA`, ale to nowy plik z danymi okresu do przechowania, a
  poprawki reguł i tak wynikają z przeliczenia.
- **Wysyłka po kliknięciu taty, jak Zgłoszenie.** Kontrola służy Maksowi, a nie
  tacie. Co tydzień tata dostawałby pytanie o coś, czego nie musi rozumieć.
- **Ogólne poluzowanie reguły prywatności.** Treść wierszy trafiłaby do
  dziennika i metryk na komputerze taty bez żadnej potrzeby.
