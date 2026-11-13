# ADR 0033: Reguły ilości zmienia tata w Ustawieniach Centrum

## Status

Zaakceptowana (decyzja Maksa 13.11.2026, grill w tej gałęzi). Poprawiona 13.11.2026 przy przepisaniu reguł z kodu na
dane (#1471): zakres reguły, tryb „zawierają tekst”, S jako liczba urządzeń z grup, doprecyzowania słownika i zdanie o
świętach. To decyzje domyślne z wdrożenia, które Maks może zmienić. Zmienia:

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
- **Zamknięty słownik.** Reguła to „jeśli” (wszystkie warunki naraz, każdy może być zaprzeczony: „ale nie gdy”),
  „to” i zakres. Warunki:
  1. `URZĄDZENIA` zawierają składnik, z liczbą z zapisu `n*`; warunek widzi składniki z listy także obok składnika
     spoza niej;
  2. `URZĄDZENIA` są puste, są dokładnie tekstem (słowa po tej samej normalizacji co zapisy składników: małe litery,
     przecinki jak spacje, bez `xg`) albo zawierają tekst (fragment tekstu bez względu na wielkość liter, nie
     składnik: tak czyta Ilości tylko dla INEA, więc `gniazdo2` też zawiera `gniazdo`);
  3. `CZYNNOŚCI` zawierają tekst (fragment po małych literach i zwinięciu spacji);
  4. pierwsze słowo `UMOWA` jest tym słowem (`u` nie pasuje do `U/123` ani `usługa`);
  5. `DATA` przypada w wybrane dni tygodnia od wybranej godziny; zlecenie bez `DATA` tego warunku nie spełnia, także
     zaprzeczonego;
  6. zlecenie ma albo nie ma urządzenia z grupy (router, TV, extender).

  Działania:
  1. wpisz w kolumnę `N:AP` (bez P, Q i S) wartość raz na zlecenie, razy liczbę składnika (suma krotności `n*`)
     albo razy „N szt” z `CZYNNOŚCI` (bez liczby 1) razy wystąpienia składnika, bez jego krotności `n*`;
  2. nic nie wpisuj w tym zleceniu;
  3. zostaw kolumnę pustą w Rozliczeniu pracownika (Ilości tylko dla INEA).

  Zakres mówi, dla których zleceń reguła działa: gdy Lista Urządzeń zna każdy składnik `URZĄDZENIA` (domyślny),
  gdy jest składnik spoza listy, albo dla każdego zlecenia. Dzisiejsze V to dwie reguły: V=1 przy znanych bez
  instalacji ręcznej i V=1 przy składniku spoza listy; dodatek za usterkę i T działają w każdym zleceniu.

  Nowy rodzaj warunku albo działania przychodzi Wydaniem.
- **Wbudowane, nie do edycji:** P i Q (przy routerze pierwszy TV do P, a następne do Q; bez routera wszystkie do
  Q), S jako liczba urządzeń z grup router, TV i extender, oba tylko przy znanych składnikach, i ostrzeżenie o
  składniku spoza listy (ADR 0012). Dodatek za usterkę po godzinach to zwykła reguła z dniami i godziną: w niedzielę
  nie działa, bo niedzieli nie ma na liście jej dni. Świąt Reguły ilości nie znają (dostają dzień tygodnia, nie datę
  dzienną) i przepisanie reguł na dane tego nie zmienia; dzień świąteczny bez dodatku to osobna zmiana z własną
  bramą.
- **Lista Urządzeń.** Składniki z innymi zapisami tej samej rzeczy i grupą prowadzi tata osobno. Nowy zapis z
  INTERMAX tata dopisuje do składnika, bez nowej reguły.
- **Reguły się sumują.** Tata nie ustawia kolejności: pasujące reguły dodają się w kolumnie, jak dziś składniki.
  Pierwszeństwo mają tylko „nic nie wpisuj” (wtedy zlecenie nie ma żadnych ilości) i potem „`URZĄDZENIA` są
  dokładnie tekstem” (wtedy liczą się tylko reguły z tym warunkiem, bez P, Q i S). „Zostaw pustą” działa obok każdej
  z nich.
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
