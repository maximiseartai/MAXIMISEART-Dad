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

Zmieniona 5.11.2026 (decyzja Maksa, #913, #918, zastępuje PR #966): położenie
wiersza Rejestru zleceń i INTERMAX w pamięci reguły danych (sekcja „Położenie
wiersza”). Uzupełniona 6.11.2026 (decyzja Maksa po przeglądzie #984 r2): pierwszy
wiersz bloku ma jedno położenie tylko wtedy, gdy jego przesunięcie widać.

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
  jedna (`TOOL_FIELDS` w `run_logs.py`):
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
  wiersza listy wyników. Każdy wiersz Rejestru zleceń i INTERMAX pamięć zna w
  jednym położeniu (sekcja „Położenie wiersza” niżej): pierwszy wiersz bloku
  wklejenia dwie kolumny na lewo od nagłówków, każdy inny pod nimi, a wiersz z
  siatki w obu.
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

## Położenie wiersza (decyzja Maksa z 5.11.2026, #913, #918)

Fakt domeny (Maks): z aplikacji firmowej przychodzi przesunięty o dwie kolumny
w lewo zawsze pierwszy wiersz wklejenia i tylko on (ADR 0019; kopia INTERMAX taty
z 25.10.2026: 84 wklejone wiersze, przesunięty pierwszy). Maks wybrał regułę
deterministyczną opartą na tym fakcie i bierze na siebie ryzyko, że fakt nie
zajdzie:

- **Pierwszy wiersz bloku wklejenia** to wiersz z wyglądem z aplikacji (żadna
  komórka z wartością poza `WYKONAWCA` nie ma Calibri 8), nad którym najbliższy
  wiersz z wartościami w odczycie jest uporządkowany albo nie ma żadnego, także
  nad uporządkowanymi (`raw_orders.first_in_block`; odczyt INTERMAX od dołu
  sięga o jeden wiersz z wartościami dalej). Gdy jego przesunięcie widać, czyli
  dwie kolumny przed `DATA GODZ. POCZ.` ma datę z godziną, a pod nią nie
  (`raw_orders.shift_visible`; tak stoi u taty każdy przesunięty pierwszy wiersz
  z aplikacji), pamięć zna jego `ADRES` i `NUMER UMOWY` tylko dwie kolumny na lewo
  od nagłówków i maskuje je wszędzie.
- **Każdy inny wiersz** pamięć zna tylko pod nagłówkiem i maskuje wszędzie.
  Drugich położeń z wąską maską, faktów przesunięcia i podpisów nie ma.
- **Siatka** (`raw_orders.both_positions`): dwa rodzaje wierszy pamięć zna w obu
  położeniach. To dodatkowe położenie, a nie reguła, która z treści wiersza
  wybiera jedno; u taty kosztuje 0:
  - inny wiersz z datą z godziną dwie kolumny przed `DATA GODZ. POCZ.` (ślad
    przesunięcia, `raw_orders.shift_traced`). Logi mają o nim uwagę w
    `input_copy_notes` („Fakt domeny złamany: wiersz N …”; w INTERMAX o wierszach
    wklejenia w Kopii, w Rejestrze o każdym przeczytanym). Wariant a, sama uwaga,
    dał w repro 1 (drugi wklejony wiersz przesunięty) te same maski i wypuścił do
    Kopii prawdziwą wartość, a b nie;
  - pierwszy wiersz bloku, którego przesunięcia nie widać: z datą z godziną pod
    `DATA GODZ. POCZ.`, z datą tekstem albo bez daty, bez uwagi. Fakt Maksa dalej
    wybiera, który wiersz jest kandydatem, ale sam kształt treści nigdy nie
    zdejmuje z pierwszego wiersza drugiego położenia. Tak stoi wiersz, który
    uchodzi za pierwszy, bo tata wpisał coś w Calibri 8 w wiersz wklejenia nad nim
    (przegląd #984 r1 i r2), i wiersz na górze odczytu okresu ze środka arkusza
    (zawężenie zaczyna się od daty z godziną pod `DATA GODZ. POCZ.`). Granica
    bloku z kroju zostaje: reguła z większości komórek przestawia u taty granice
    dziesiątek bloków (odrzucone warianty).
- **Kopia wejścia** niesie wiersz w położeniu, w którym czyta go Planowanie, bez
  kolumn `ADRES` i `NUMER UMOWY`, więc przesunięty pierwszy wiersz ma
  `URZĄDZENIA` i `NUMER ZL.`. Wiersz z siatki ma tylko komórki dozwolone w obu
  położeniach i datę z godziną spod `DATA GODZ. POCZ.`; odtworzenie (#847)
  traktuje go jako zastrzeżenie, nie granicę blokującą.

Sondy przeglądów #917, #952 i #966 (179 przypadków przez HTTP API Centrum, te
same bajty na `main` b3f1c625a i na tej regule; tabela na Macu Maksa:
`~/.t3/notes/logi-837/deterministyczna/TABELA.md`):

| klasa | sond | wyciek na `main` | wyciek na tej regule |
|---|---|---|---|
| fakt domeny zachodzi | 91 | 11 | 0 |
| ślad przesunięcia (siatka) | 40 | 0 | 0 |
| przesunięty inny wiersz niż pierwszy, bez śladu | 19 | 4 | 19 |
| pierwszy wiersz bloku z widocznym przesunięciem nie przesunięty w całości | 25 | 6 | 16 |
| przesunięcie w prawo | 3 | 3 | 3 |
| `ADRES` jako data z godziną (adresu nie ma w pliku) | 1 | 1 | 1 |

Ryzyko przyjęte przez Maksa to dwie klasy z faktem domeny złamanym bez śladu: 19
i 16 sond. W drugiej pierwszy wiersz ma widoczne przesunięcie (data z godziną dwie
kolumny przed `DATA GODZ. POCZ.`, pod nią nie), a jest przesunięty tylko w części
albo stoi na miejscu. W każdej adres albo numer Orange wiersza wychodzi, gdy stoi
też w wolnym tekście, w Uwadze taty albo w zwykłej kolumnie innego wiersza. Testy
`KNOWN` (xfail strict, termin 5.02.2027, `tests/fixtures/fakt_domeny.py`) mają
po przypadku z każdej klasy w tabelach położeń INTERMAX i Rejestru. Wpis taty w
Calibri 8 we wklejonym wierszu nie wypuszcza wartości, z datą z godziną, z datą
tekstem i bez daty w wierszu pod nim (sondy przeglądu #984 r1 i r2: I1, I1b, I2,
R1, R3, N1–N6t, RN1–RN3, D9, D10).

Znana granica sygnału: gdy tata wpisze coś w Calibri 8 w przesunięty pierwszy
wiersz wklejenia, ten wiersz ma wygląd uporządkowany, więc jego data z godziną w
kolumnie przed `DATA GODZ. POCZ.` daje fałszywą uwagę „Fakt domeny złamany”, a
granica bloku przesuwa się o wiersz. Wartości nie wychodzą (pierwszy wiersz za
nim stoi na miejscu, więc jego przesunięcia nie widać i ma oba położenia). Na
kopii Rejestru taty z 20.10.2026 w 41 okresach 2026 uwag o złamanym fakcie
domeny jest 0.

Koszt na kopiach plików taty (tylko odczyt, Mac Maksa, pomiar w PR, `main`
b3f1c625a → ta reguła): Kopia wejścia Uporządkowania na kopii INTERMAX z
wklejeniem bez Diagnozy 0 → 0 masek, po Diagnozie Przygotowania 165 (`NUMER ZL.`
83, `URZĄDZENIA` 82) → 0, komórek 518 → 518; prawdziwych wartości wklejonych
wierszy (168) w Kopii po strażniku 0 i nieznanych strażnikowi 0. W repro 1, które
łamie fakt domeny, 81 → 81 masek `URZĄDZENIA`, a w następnym Uporządkowaniu po
poprawce taty 82 → 82, bez wycieku. Kopia Przygotowania 41 okresów 2026: 0 masek,
0 uwag o złamanym fakcie domeny. Granice bloków z kroju bez zmian: pierwszych
wierszy bloków w Diagnozie całego Rejestru 10, w Uporządkowaniu INTERMAX 7
(`first_in_block`), w 41 okresach razem 4. Przesunięcie widać tylko w pierwszym
wierszu ostatniego wklejenia INTERMAX, więc oba położenia ma 10 z 10, 6 z 7 i 4 z
4. Pamięć nie poznaje przez to żadnej nowej wartości (ich `ADRES` i `NUMER UMOWY`
są puste albo znane), a masek w Kopii jest tyle samo.

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
- **Dwa położenia każdego wiersza z wyglądem z aplikacji, wartość z drugiego
  maskowana wąsko (opcja 3, PR #966).** Po trzech rundach przeglądu wciąż
  wyciekała w kolejnych układach podpisu przesunięcia, a reguła rosła o fakty i
  wyjątki; Maks odrzucił dwa położenia i maskę w wielu kolumnach.
- **Oba położenia każdego wiersza bez wyglądu uporządkowanego wszędzie (`main`
  przed tą decyzją, #952).** Maskowało `URZĄDZENIA` i `NUMER ZL.` w 165
  komórkach Kopii Uporządkowania po Diagnozie.
- **Siatka bez drugiego położenia (wariant a).** Te same maski co wariant b, a w
  repro 1 prawdziwa wartość w Kopii.
- **Wygląd uporządkowany z większości komórek w Calibri 8 bez kolumn, w które tata
  pisze ręcznie (przegląd #984 r1).** Na kopiach taty robi pierwszymi wierszami
  bloków stare wiersze wpisane innym krojem albo częściowo przeformatowane: w
  INTERMAX 94 zamiast 7 (92 na miejscu), w Rejestrze 93 zamiast 6. Większość
  wśród wszystkich komórek daje 69, większość w kroju aplikacji (Roboto) 60, a
  pomijanie samych kolumn ręcznych 23 (20 na miejscu).
- **Pierwszy wiersz z datą z godziną pod `DATA GODZ. POCZ.` tylko pod nagłówkiem
  (przegląd #984 r1).** Przesunięty pierwszy wiersz z `ADRES` jako datą z godziną
  wygląda wtedy na wiersz na miejscu: 3 sondy, w których fakt domeny zachodzi,
  wypuszczają wartości (na `main` 0).
- **Pierwszy wiersz w obu położeniach tylko z datą z godziną pod `DATA GODZ.
  POCZ.` (przegląd #984 r2).** Wpis taty w Calibri 8 nad wierszem na miejscu z
  datą tekstem albo bez daty robił z tego wiersza pierwszy wiersz bloku znany
  tylko przesunięty: 10 sond przeglądu (N1–N6t, RN1–RN3, D9, D10) wypuszczało adres
  i numer Orange albo zostawiało je strażnikowi nieznane (na `main` 0).
- **Ponowny odczyt plików taty przy wysyłce, żeby poznać zakazane wartości.**
  Przebieg rozliczeń i Kontrola ilości czytają Plik zbiorczy raz (ADR 0013);
  drugi odczyt Rejestru zleceń trwa sekundy.
