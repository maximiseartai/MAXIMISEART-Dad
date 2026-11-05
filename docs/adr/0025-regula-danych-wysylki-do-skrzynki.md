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
  nagłówek, i każda inna kolumna A:K z takim nagłówkiem (#841). Każda inna
  kolumna wiersza może wyjść, w tym `NUMER ZL.`, `WYKONAWCA` i `MIASTO`.
- **Wolny tekst idzie w całości z maskowaniem**: numer telefonu (komórkowy
  3-3-3, stacjonarny 2-3-2-2, z `+48` albo bez) staje się `[telefon]`, a
  wzmianka ulicy („ul.”, „os.”, „al.”, „pl.” z nazwą i numerem domu, z
  lokalem albo bez) `[ulica]`. Cyfry zaraz po `#` to `NUMER ZL.`, nie telefon.
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
- **Liczba ma tekst, który pokazuje Excel** (#841): numer Orange albo
  telefon, który tata wpisał w komórkę bez innego tekstu, Excel trzyma jako
  liczbę, a liczba całkowita zapisana jako ułamek to jej cyfry. Tak liczbę
  zapamiętuje pamięć i tak sprawdza ją strażnik, który maskuje ją w całości
  (`[numer Orange]` z uwagą techniczną albo `[telefon]`). W Logach sprawdza
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
  to samo rozpoznanie bloku co Uporządkowanie. Pamięć jest jedna na pracę
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
- Telefon zapisany inaczej niż w powyższych kształtach (np. w nawiasach,
  z kropkami) i ulica bez „ul.”, „os.”, „al.” ani „pl.” wychodzą bez
  maskowania.

## Odrzucone warianty

- **Lista dozwolonych pól dla każdego rodzaju wysyłki osobno.** Tak było
  dotąd: cztery listy, których pilnował tylko przegląd, a każda nowa potrzeba
  Maksa dokładała wyjątek w kolejnym ADR.
- **Strażnik w Kolejce wysyłki.** Tata nie widziałby w podglądzie tego, co
  naprawdę wychodzi, a plik Logów na dysku i plik w Skrzynce różniłyby się.
- **Ponowny odczyt plików taty przy wysyłce, żeby poznać zakazane wartości.**
  Przebieg rozliczeń i Kontrola ilości czytają Plik zbiorczy raz (ADR 0013);
  drugi odczyt Rejestru zleceń trwa sekundy.
