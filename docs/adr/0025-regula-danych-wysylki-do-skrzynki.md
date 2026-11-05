# ADR 0025: Reguła danych wysyłki do Skrzynki Zgłoszeń

## Status

Zaakceptowana (grilling Maksa 4.11.2026, specyfikacja #837, ticket #838).
Zmienia:

- [ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md), punkt
  „Treść Logów”: zdanie „Logi nie niosą treści wierszy: nigdy adresu, numeru
  zlecenia, numeru umowy, Wykonawcy przy wierszu, daty dziennej z komórki,
  `CZYNNOŚCI ZREALIZOWANE` ani opisu technika” zastępuje reguła danych niżej.
  Od #841 Logi niosą Wiersze danych w Kopii wejścia, bez zakazanych kolumn,
  a wszystko, co niosą, przechodzi przez strażnika;
- [ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md), zdanie „Bez treści
  wierszy, adresów, numerów zleceń, stawek, treści wyjątków i pełnych
  ścieżek” w rewizji reguły prywatności: o treści wierszy w Zgłoszeniu,
  Kontroli ilości ([ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md)),
  Logach i Uwadze taty rozstrzyga odtąd reguła danych. Treści wyjątków, stawek,
  pełnych ścieżek i klucza dalej nic nie wysyła.

Publiczne repozytorium bez zmian: PR-y, commity, issue i testy nie niosą
treści wierszy, numerów zleceń ani Wykonawców taty, a testy mają tylko dane
syntetyczne.

## Kontekst

Maks utrzymuje narzędzie zdalnie i chce odtwarzać Uruchomienie tak, jakby
siedział przy komputerze taty (#837). Do tego potrzebuje treści wierszy,
których dotąd nic nie wysyłało, z wyjątkami (`ZLE_SKUTECZNE`, Kontrola
ilości) dopisywanymi w kolejnych ADR. Każdy rodzaj wysyłki (Logi
Uruchomienia, Zgłoszenie, Kontrola ilości, Uwaga taty) miał własną listę
tego, czego nie niesie, a pilnował jej tylko przegląd. Klienta wskazują
adres i numer umowy Orange, nie numer zlecenia, Wykonawca, miasto czy opis
technika. Skan kopii plików taty (Maks, 4.11.2026): w INTERMAX 17 telefonów i
16 ulic na 25 839 opisów `CZYNNOŚCI ZREALIZOWANE`, w Plikach zbiorczych 0–2
telefony na okres.

## Decyzja

- **Jedna reguła danych dla wszystkiego, co Centrum wysyła do Skrzynki
  Zgłoszeń**: Logów Uruchomienia, Zgłoszeń, Kontroli ilości i Uwag taty.
  Nigdy nie wychodzą z komputera taty wartości kolumn `ADRES` i
  `NUMER UMOWY/ZLECENIA ORANGE` (w Rejestrze zleceń i INTERMAX także `adres`
  i `NUMER UMOWY`) ani dane adresowe ze strony zlecenia efenix. W Pliku
  zbiorczym to kolumny B i I z układu Wzorca, także gdy tata zmienił ich
  nagłówek, i każda inna kolumna A:K z takim nagłówkiem (#841). INTERMAX nie
  ma stałego układu kolumn, więc w jego arkuszu zleceń to kolumny z takim
  nagłówkiem w wierszu 1, po którym Uporządkowanie znajduje też kolumny
  zlecenia (#842).
  Każda inna kolumna wiersza może wyjść, w tym `NUMER ZL.`, `WYKONAWCA` i
  `MIASTO`. Kolumny z aplikacji za `UWAGI` w wklejeniu INTERMAX nie mają
  nagłówka i nie wychodzą: jedna z nich niesie części adresu ze słowami
  sklejonymi `_`, których strażnik nie rozpozna jako wartości `ADRES` (skan
  kopii INTERMAX taty z 25.10.2026 na Macu Maksa: słowo z `ADRES` spoza
  miasta w 48 z 83 wklejonych wierszy, zamaskowany 1, #842).
- **Wolny tekst idzie w całości z maskowaniem**: numer telefonu (komórkowy
  3-3-3, stacjonarny 2-3-2-2, z numerem kierunkowym `+48`, `0048` albo `48`
  albo bez) staje się `[telefon]`, a wzmianka ulicy („ul.”, „os.”, „al.”,
  „pl.” z nazwą i numerem domu, z lokalem albo bez) `[ulica]`. Cyfry zaraz po
  `#` to `NUMER ZL.`, nie telefon. Które formy telefonu strażnik maskuje, a
  które nie, mówi tabela w sekcji „Telefon: formy i znane granice”.
- **Strażnik u producenta, nie w kolejce.** Tam, gdzie powstaje tekst pliku
  Logów i każdej wysyłki (Logi, podgląd Zgłoszenia, Kontrola ilości, podgląd
  Uwagi taty), Centrum szuka w nim każdej zakazanej wartości z plików, które
  przeczytało, i każdą znalezioną zastępuje `[adres]` albo
  `[numer Orange]`. Wartość to ciąg jej słów: tekst ją zawiera, gdy ma te
  słowa po kolei, całe i bez wielkości liter, z dowolnymi znakami spoza słów
  między nimi. Producent może więc zapisać komórkę po swojemu przed strażnikiem
  (koniec linii jako `⏎` i `|` jako `\|` w tabeli Kontroli ilości, cudzysłów
  Komunikatu), a z kilku wartości od tego samego słowa wygrywa najdłuższa.
  Dopisuje uwagę techniczną z nazwą kolumny i miejscem (w Logach pole
  pliku, np. `messages[0].where`), bez wartości: w Logach do
  `technical_notes` (o polu Kopii wejścia do `input_copy_notes`, #841, bo
  `technical_notes` pokazuje karta Uruchomienia z Logów, a Kopii nie), w
  Zgłoszeniu i Kontroli ilości sekcją „Uwagi techniczne”, w Uwadze taty linią
  pod jej tekstem. Tata widzi w podglądzie
  Zgłoszenia i Uwagi dokładnie to, co wyjdzie. Tekst bez zakazanej wartości,
  telefonu i ulicy wychodzi bez zmian i bez uwagi.
- **W Logach słowa i chwile narzędzia zostają** (#936). Strażnik porównuje
  słowa, a nie pochodzenie wartości, więc wartość z pliku taty równa słowu
  narzędzia (`zapis`, token okresu, część chwili startu) trafiała też w pole,
  które niesie tylko to, co dało narzędzie, i gubiła całe Logi albo ich okres,
  Uruchomienie i commit, z których odtworzenie (#847) buduje Uruchomienie.
  Strażnik zostawia więc wartość z rekordu w tych polach Logów, a lista jest
  jedna (`_TOOL_FIELDS` w `run_logs.py`):
  - `run_id`: identyfikator `uuid4`;
  - `period`: token okresu z żądania przeglądarki po `parse_period_token`
    albo z zegara (Uporządkowanie INTERMAX);
  - `process`, `mode`, `result`, `ending`, `stop_kind`: wartości zamkniętych
    list schematu;
  - `started_at`, `ended_at`: chwile zegara Centrum (w Logach Urwanego
    Uruchomienia z dziennika Wyceny, który pisze Centrum);
  - `tool`: Wydanie i commit z Gita narzędzia;
  - `phases`: etapy z zamkniętej listy ze stanem, czasem i chwilami projekcji
    postępu;
  - `trace`: typy wyjątków i ramki kodu narzędzia, bez treści wyjątku;
  - `dad_actions`: chwile, wartości zamkniętych list i operacje API z
    kontraktu, bez treści zapytań;
  - `system` i `python` Środowiska: moduł `platform`.

  Nazw pól schematu (kluczy modeli Logów) strażnik też nie maskuje, a klucze
  słowników (operator, kod pozycji, litera kolumny) to dane i maskuje je jak
  tekst. Każde inne pole może nieść treść pliku taty (tekst Komunikatu,
  Wykonawca, nazwa pliku, odczyt strony efenix, Kopia wejścia) i dalej ma
  maskę. Pole typowane spoza listy (kwota, data, wartość z zamkniętej listy w
  elemencie listy), które maski nie przyjmuje, zostaje puste albo odpada jego
  element listy z uwagą techniczną (#929), więc maska nie gubi całych Logów.
- **Liczba ma tekst, który pokazuje Excel** (#841): numer Orange albo
  telefon, który tata wpisał w komórkę bez innego tekstu, Excel trzyma jako
  liczbę, a liczba całkowita zapisana jako ułamek to jej cyfry. Format General
  gubi `+` i zera z przodu, więc telefon `+48600123456` albo `0048600123456`
  to liczba `48600123456`. Tak liczbę zapamiętuje pamięć i tak sprawdza ją
  strażnik, który maskuje ją w całości: `[numer Orange]` z uwagą techniczną
  albo `[telefon]`, gdy to liczba całkowita z 9 cyframi albo z `48` i 9
  cyframi. Liczba z częścią ułamkową nie jest telefonem. W Logach sprawdza
  liczby w polach z wartościami z komórek pliku taty i ze strony efenix
  (komórki Kopii wejścia i ilości przy zleceniu Wyceny w efenix), bo każdą
  inną liczbę Logów (wiersz, rozmiar, czas, liczbę zleceń) policzyło
  narzędzie.
- **Skąd Centrum zna zakazane wartości.** Każdy czytnik Wierszy danych,
  który czyta dla Centrum (Pliku zbiorczego w Przebiegu rozliczeń, Kontroli
  ilości, Wycenie w efenix i Uzupełnieniu, Rejestru zleceń w Przygotowaniu i
  Diagnozie, INTERMAX w Uporządkowaniu, na jego karcie i przy szukaniu
  Surowych zleceń w Przygotowaniu), oddaje przy odczycie komórki zakazanych
  kolumn pamięci reguły danych, a Wycena w efenix dane adresowe każdego
  wiersza listy wyników. W przesuniętym pierwszym wierszu wklejenia INTERMAX
  (ADR 0019) te komórki stoją dwie kolumny na lewo od nagłówka; rozpoznaje go
  to samo rozpoznanie bloku co Uporządkowanie. Pewne położenie ma jednak tylko
  wiersz uporządkowany i wiersz, który rozpoznanie przeczytało jako Surowe
  zlecenie: pierwszy wiersz drugiego wklejenia też przychodzi przesunięty, a
  pierwszy wiersz z datą jako tekstem nie musi być przesunięty. W każdym innym
  wierszu pamięć poznaje komórki w obu miejscach, a Kopia wejścia niesie tylko
  komórki dozwolone w obu położeniach (#842, tabela położeń w PR #905).
  Pamięć jest jedna na pracę
  Centrum: Centrum tworzy ją przy starcie i podaje czytnikom i producentom, a
  nie jest stanem modułu, więc dwie prace Centrum w jednym procesie (testy)
  jej nie dzielą. Tylko rośnie i nie trafia na dysk, więc chroni także Uwagę
  taty, która nie ma Uruchomienia, i Zgłoszenie z Diagnozy. Proces bez Centrum
  (Skrypt dla maszyn) pamięci nie ma, bo nic nie wysyła. Wartość krótsza niż
  5 znaków jest pomijana: nie wskazuje klienta, a pasowałaby do zwykłych słów
  i liczb.
- **Zgoda taty.** Tata wie, że wysyłki do prywatnej Skrzynki Zgłoszeń będą
  niosły numery zleceń, Wykonawców, miasta i opisy techników, i zgodził się
  na to z Maksem (grilling 4.11.2026).

## Konsekwencje

- Reguła ma jedno miejsce w kodzie (`client_data`), a każdy producent woła
  jego strażnika; nowy rodzaj wysyłki dostaje go tak samo.
- Wartości przeczytane przed startem tej pracy Centrum strażnik zna dopiero
  po ponownym odczycie pliku. Uwaga taty napisana zaraz po starcie Centrum
  ma tylko maskowanie telefonów i ulic, tak jak Logi Urwanego Uruchomienia
  (#845): start Centrum przepuszcza je przez strażnika przed plikiem i
  wysyłką, także Logi zapisane, a niewysłane przez poprzednią pracę Centrum,
  ale zamyka je i wysyła, zanim ta praca Centrum przeczyta plik taty.
- Strażnik maskuje ciąg słów wartości także z innymi znakami między nimi
  (`Kwiatowa 5-3` przy wartości `Kwiatowa 5/3`): to więcej niż sama wartość,
  nigdy mniej. Część wartości (sama ulica z numerem z danych adresowych efenix
  bez miejscowości przed nią) nie jest wartością i ma tylko maskowanie ulicy.
- Czas strażnika zależy od długości tekstu, nie od liczby zapamiętanych
  wartości, więc pamięć po Diagnozie całego Rejestru (~31,7 tys. wierszy) nie
  spowalnia wysyłek (pomiar w PR #851).
- Telefon w formie spoza tabeli niżej i ulica bez „ul.”, „os.”, „al.” ani
  „pl.” wychodzą bez maskowania.

## Telefon: formy i znane granice

Dopisek #841 (PR #863). Tabela mówi, co strażnik robi z każdą formą telefonu
w komórce z tekstem albo w wolnym tekście (tekst) i w komórce, którą Excel
trzyma jako liczbę (liczba). Te same formy są danymi testu
`tests/fixtures/formy_telefonu.py`, który przechodzi przez całą tabelę.

| Forma | Przykład | Wynik |
|---|---|---|
| tekst: komórkowy 3-3-3 bez separatorów, ze spacjami albo kreskami | `600 123 456` | `[telefon]` |
| tekst: z `+48`, `0048` albo `48`, z separatorami albo bez | `48600123456` | `[telefon]` |
| tekst: stacjonarny 2-3-2-2, ze spacjami albo kreskami, z numerem kierunkowym albo bez | `12 345 67 89` | `[telefon]` |
| tekst: `+48` w nawiasie | `(+48) 600 123 456` | `(+48) [telefon]` |
| liczba całkowita z 9 cyframi, także zapisana jako ułamek albo w notacji E | `600123456` | `[telefon]` |
| liczba całkowita z `48` i 9 cyframi (`+48` albo `0048` zgubione przez format General) | `48600123456` | `[telefon]` |

Znane granice, w których telefon wychodzi bez maski: telefon z kropkami
(`600.123.456`), numer w nawiasie (`(600) 123 456`, `(12) 345 67 89`),
komórkowy w grupach 3-2-2-2 (`600 12 34 56`) i telefon sklejony z literami w
jedno słowo (`tel600123456`). Kropki między grupami cyfr mają też daty z
godziną i adresy IP, a słowo z cyframi to też numer urządzenia w opisie
technika, więc maska tych form zabierałaby wartości, które nie są telefonem.

Znane granice w drugą stronę, w których strażnik maskuje wartość, która nie
jest telefonem: liczba z 9 cyframi bez `#` (`NUMER ZL.` ma dziś 8 cyfr) i
ciąg `48` z 9 cyframi w tekście (np. numer seryjny).

Bez maski wychodzą ilość, kwota, `NUMER ZL.` z `#` (8 albo 9 cyfr), data, data
z godziną, liczba z częścią ułamkową i liczba całkowita, która nie ma 9 cyfr
ani `48` i 9 cyfr. Liczb policzonych przez narzędzie (numer wiersza, rozmiar
pliku) strażnik liczby nie sprawdza.

Skan kopii plików taty (PR #863: 2 kopie Rejestru zleceń, 3 Pliki zbiorcze,
2 Rozliczenia wewnętrzne i surowe zlecenia z aplikacji firmowej, ok. 613 tys.
komórek z wartością): form ze znanych granic jest 0. Numer kierunkowy `48`
bez `+` i zer (PR #863) maskuje tam 5 wartości więcej: 4 liczby z `48` i 9
cyframi w `CZYNNOŚCI ZREALIZOWANE` i `ZWROT` Rejestru i 1 taki ciąg w tekście,
wszystkie z prefiksem sieci komórkowej, i żadnej wartości, która nie jest
telefonem.
Poza telefonami maska łapie tam, jak przed tą zmianą, 8 numerów umowy z
przedrostkiem i 9 cyframi (kolumna `NUMER UMOWY` surowych zleceń i
Rozliczenia wewnętrznego, której wartości reguła danych i tak nie wypuszcza)
i 1 liczbę z 9 cyframi w arkuszu „komentarze” Rejestru, którego żaden proces
nie czyta.

## Odrzucone warianty

- **Lista dozwolonych pól dla każdego rodzaju wysyłki osobno.** Tak było
  dotąd: cztery listy, których pilnował tylko przegląd, a każda nowa potrzeba
  Maksa dokładała wyjątek w kolejnym ADR.
- **Strażnik w Kolejce wysyłki.** Tata nie widziałby w podglądzie tego, co
  naprawdę wychodzi, a plik Logów na dysku i plik w Skrzynce różniłyby się.
- **Ponowny odczyt plików taty przy wysyłce, żeby poznać zakazane wartości.**
  Przebieg rozliczeń i Kontrola ilości czytają Plik zbiorczy raz (ADR 0013);
  drugi odczyt Rejestru zleceń trwa sekundy.
