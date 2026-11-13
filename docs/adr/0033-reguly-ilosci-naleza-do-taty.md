# ADR 0033: Reguły ilości zmienia tata w Ustawieniach Centrum

## Status

Zaakceptowana (decyzja Maksa 13.11.2026, grill w tej gałęzi). Zmienia:

- [ADR 0012](0012-ilosci-uslug-w-przygotowaniu-pliku-zbiorczego.md): „Reguły ilości są w repozytorium narzędzia i
  utrzymuje je Maks” oraz odrzucony wariant „Plik reguł edytowany przez tatę”. Reguły ilości są Ustawieniem Centrum
  ([ADR 0032](0032-ustawienia-centrum-zmienia-tata.md)), które tata tworzy i zmienia sam;
- [ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md): „Zmiana reguły wymaga potwierdzenia taty”. Tata
  zmienia regułę sam, a różnice z Kontroli ilości widzi też w Centrum jako podpowiedzi. Kontrola ilości dalej
  trafia do Skrzynki Zgłoszeń;
- [ADR 0018](0018-ilosci-tylko-dla-inea-nie-przechodza-do-rozliczenia-pracownika.md): „Zasada należy do taty, a
  utrzymuje ją Maks”. Ilości tylko dla INEA to działanie reguły, które tata ustawia jak każde inne.

Zostaje [ADR 0001](0001-local-deterministic-settlement-engine.md): reguły z danych są tak samo deterministyczne jak
reguły z kodu.

## Kontekst

Reguły ilości to dziś kod. Każda różnica z Kontroli ilości (pierwsze trzy raporty: 109 różnic w 1349 wierszach)
czeka, aż Maks przejrzy ją z agentem, zapyta tatę, zmieni kod i wyda nową wersję. Do dziś nikt nie przeszedł tych
różnic z tatą.

22.10.2026, zapytany, jak chce zmieniać reguły, tata odpowiedział „WOLĘ DAĆ CI ZNAĆ”. ADR 0012 odrzucił plik reguł
edytowany przez tatę także dlatego, że jego instrukcja miała literówki (`3*fut` → Z=2), które przeszłyby bez testu.
Maks idzie inaczej. Edytor w Centrum to nie surowy plik, tylko formularz z podglądem skutków na prawdziwych
okresach taty, w którym literówkę widać przed zapisem. Pośrednictwo Maksa przy każdej regule jest wąskim gardłem.
Tata nie był jeszcze pytany o sam edytor; edytor powstaje bez czekania na jego odpowiedź.

## Decyzja

- **Reguły ilości to dane w `config/` u taty**, zmieniane w sekcji Reguły ilości okna Ustawień. Wydanie zmienia je
  tylko jawną zmianą z Historią Ustawień (furtka z ADR 0032).
- **Zamknięty słownik.** Reguła to „jeśli” (wszystkie warunki naraz, każdy może być zaprzeczony: „ale nie gdy”)
  i „to”. Warunki:
  1. `URZĄDZENIA` zawierają składnik, z liczbą z zapisu `n*`;
  2. `URZĄDZENIA` są puste albo są dokładnie tekstem;
  3. `CZYNNOŚCI` zawierają tekst;
  4. `UMOWA` zaczyna się od tekstu;
  5. `DATA` przypada w wybrane dni tygodnia od wybranej godziny;
  6. zlecenie ma albo nie ma urządzenia z grupy (router, TV, extender).

  Działania:
  1. wpisz w kolumnę `N:AP` wartość stałą, razy liczbę składnika, razy „N szt” z `CZYNNOŚCI` albo raz na
     zlecenie;
  2. nic nie wpisuj w tym zleceniu;
  3. zostaw kolumnę pustą w Rozliczeniu pracownika (Ilości tylko dla INEA).

  Nowy rodzaj warunku albo działania przychodzi Wydaniem.
- **Wbudowane, nie do edycji:** S jako suma, pierwszy TV do P a następne do Q, składnik spoza listy daje tylko
  ilości niezależne od `URZĄDZENIA` i ostrzeżenie (ADR 0012), a niedziele i święta nie dostają dodatku.
- **Lista Urządzeń.** Składniki z innymi zapisami tej samej rzeczy i grupą prowadzi tata osobno. Nowy zapis z
  INTERMAX tata dopisuje do składnika, bez nowej reguły.
- **Reguły się sumują.** Tata nie ustawia kolejności: pasujące reguły dodają się w kolumnie, jak dziś składniki.
  Pierwszeństwo mają tylko „`URZĄDZENIA` są dokładnie tekstem” i „nic nie wpisuj”.
- **Podgląd przed zapisem.** Centrum stosuje zmienione reguły do ostatnich Plików zbiorczych wypełnionych przez
  tatę, tym samym rachunkiem co Kontrola ilości, i pokazuje, ile wierszy się zmieni i w ilu będzie tak, jak wpisał
  tata. Zapis jest możliwy także przy różnicach, bo decyduje tata.
- **Różnice z Kontroli ilości jako podpowiedzi.** Sekcja pokazuje wiersze, w których tata wpisał inaczej niż
  reguła, z wyborem „Popraw regułę” albo „To był wyjątek”.
- **Start bez zmiany wyniku.** Pierwszy zestaw reguł to dzisiejszy kod przepisany na dane. Zanim trafi do taty,
  daje na wszystkich prawdziwych okresach na Macu Maksa te same Ilości usług i te same Ilości tylko dla INEA co
  kod, komórka w komórkę.
- **Kolumny z opisu technika** (`Y`, `AB`, `AD`, `AJ`, `AK`, `AL`, `AM`) i rodzaj budynku zostają poza słownikiem,
  dopóki tata nie poda dla nich zasad; nadal wpisuje je tata.

## Odrzucone warianty

- **Dalej przez Maksa.** Bezpieczne, ale różnice z Kontroli ilości czekają tygodniami.
- **Dowolne wyrażenia albo formuły w edytorze.** Pokrywają wszystko, ale tata ich nie przeczyta, a literówka
  przejdzie.
- **Kolejność reguł ustawiana przez tatę.** Dzisiejsze reguły się sumują; kolejność dodałaby tacie decyzję, której
  żadna znana reguła nie potrzebuje.
- **Czekać z edytorem na odpowiedź taty.** Maks woli zbudować wszystko, czego nie trzeba z tatą rozstrzygać, a
  konkretne różnice tata zamknie sam, gdy będzie miał czas.
