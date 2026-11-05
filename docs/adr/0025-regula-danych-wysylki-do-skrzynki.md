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
  wiersza listy wyników. Wiersz Rejestru zleceń, który może stać
  przesunięty (ADR 0019), pamięć zna w obu położeniach, a wartość z drugiego
  położenia, z miejscem wiersza, strażnik maskuje węziej niż każdą inną
  (sekcja „Wiersz, który może stać przesunięty”).
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

## Wiersz, który może stać przesunięty (opcja 3, #913, #918)

Decyzja Maksa z 5.11.2026 (opcja 3 z komentarza wstrzymania PR #917): strażnik
niczego nie zgaduje, więc żadna reguła „pewnego położenia” nie decyduje o
prywatności. Zastępuje regułę z #905 (pewne położenie ma wiersz rozpoznany jako
Surowe zlecenie). Ta sama reguła obowiązuje w Uporządkowaniu INTERMAX, na jego
karcie, przy szukaniu Surowych zleceń i w odczycie Rejestru w Przygotowaniu i
Diagnozie (`raw_orders.Shifts`, `preparation_register`).

- **Dwa położenia** (pod nagłówkiem i dwie kolumny na lewo od niego) ma każdy
  wiersz z wyglądem z aplikacji (bez komórki z wartością w Calibri 8 poza
  `WYKONAWCA`): w INTERMAX każdy wiersz bloku wklejenia i wiersz nad
  uporządkowanymi, w Rejestrze każdy taki wiersz odczytu. Przesunięty może być
  każdy z nich, a dwa położenia są tanie, bo wartość z drugiego ma wąski zakres
  (niżej). Wiersz uporządkowany ma dwa położenia tylko z silnym śladem
  przesunięcia (`raw_orders.ShiftTrace`): datą z godziną dwie kolumny na lewo
  od `DATA GODZ. POCZ.` (u taty kolumna A bez nagłówka), Hiperłączem poza
  `NUMER ZL.` albo Hiperłączami arkusza, których nie da się przeczytać. Brak daty
  pod `DATA GODZ. POCZ.` i mieszany krój śladem nie są: u taty ma je 740
  wierszy na miejscu, a przesunięty wiersz wklejony w komórki Calibri 8 (klasa z
  #952) ma datę z aplikacji dwie kolumny w lewo.
- **Fakt domeny** (Maks, 5.11.2026; kopia INTERMAX taty z 25.10.2026: 84
  wklejone wiersze, 1 przesunięty, ten pierwszy): przesunięty przychodzi zawsze
  tylko pierwszy wklejony wiersz. Prywatność na nim nie stoi, daje tylko sygnał:
  wiersz z silnym śladem, który nie jest pierwszym wierszem bloku wklejenia, ma
  uwagę w `input_copy_notes` Logów („Fakt domeny złamany: …”, z rodzajem
  śladu, bez wartości).
- **Położenie podstawowe** wiersza z dwoma położeniami to przesunięte, gdy
  wiersz ma podpis przesunięcia w lewo (data z godziną dwie kolumny przed `DATA
  GODZ. POCZ.` albo Hiperłącze dwie kolumny przed `NUMER ZL.`), a inaczej na
  miejscu (`raw_orders.primary_offset`). Jego wartości strażnik maskuje
  wszędzie, jak każdą inną. Wybór decyduje o wycieku, nie tylko o koszcie:
  prawdziwa wartość w drugim położeniu ma wąski zakres (granica niżej).
- **Na miejscu od `NUMER ZL.`** (`raw_orders.in_place_from`): wiersz z dwoma
  położeniami, którego jedyne Hiperłącze stoi pod `NUMER ZL.`, ma datę z
  godziną pod `DATA GODZ. POCZ.` i pustą kolumnę dwie na lewo od niej, stoi na
  miejscu od `NUMER ZL.` w prawo: Hiperłącze z aplikacji idzie z komórką `NUMER
  ZL.`, a przesunięcie w lewo, także częściowe, przesuwa wiersz od lewej. Samo
  Hiperłącze tego nie dowodzi, bo może stać w złym miejscu (sondy #917 r3). W
  takim wierszu `NUMER UMOWY` ma jedno położenie, a `NUMER ZL.` nie jest
  możliwym numerem Orange. U taty tak wygląda 83 z 83 wklejonych wierszy na
  miejscu.
- **Drugie położenie, zakres opcji 3.** Wartość z niego strażnik maskuje w
  każdej komórce Kopii wejścia swojego wiersza w tej samej wersji pliku (skrót
  bajtów jak w odcisku Kopii; w wersji, którą zapisało Uporządkowanie, w
  wierszu dnia, do którego przeniosło wiersz), pod nagłówkiem `ADRES` i `NUMER
  UMOWY…` każdego wiersza, w każdym wolnym tekście (każde pole Logów poza
  komórkami Kopii, Zgłoszenie, Kontrola ilości, Uwaga taty, a w Kopii kolumny
  inne niż zwykłe: `CZYNNOŚCI ZREALIZOWANE`, `ZWROT`, `UWAGI`, `AKCJE`, kolumna
  bez nagłówka i każdy nieznany nagłówek) i w Kopii pliku o innej nazwie (Plik
  zbiorczy niesie wartości przepisane z Rejestru). Nie maskuje jej w zwykłej
  kolumnie innego wiersza pliku o tej samej nazwie: `DATA GODZ. POCZ.`,
  `MIASTO`, `UMOWA`, `URZĄDZENIA`, `CZYNNOŚCI`, `NUMER ZL.`, `WYKONAWCA`,
  `SKUTECZNE`. Cały swój wiersz, a nie tylko swoją komórkę, bo ta sama wartość
  w innej kolumnie tego wiersza (adres przepisany pod `MIASTO`) to też ta
  wartość: syntetyczny Rejestr weryfikacji Centrum ma w każdej komórce wiersza
  ten sam znacznik i z samą komórką wychodził on z `MIASTO`.
- **Kopia wejścia.** Wiersz INTERMAX z dwoma położeniami ma w Kopii tylko
  komórki dozwolone w obu (`uncertain_rows`), datę z godziną spod `DATA GODZ.
  POCZ.` położenia odczytu (data z godziną nie jest wartością zakazanej
  kolumny, a bez niej odtworzenie z Logów, #847, nie powtórzy Uruchomienia) i,
  w wierszu na miejscu od `NUMER ZL.`, każdą komórkę od `NUMER ZL.` w prawo poza
  `NUMER UMOWY`. Kopia nie ma więc tylko komórek, które mogą być `ADRES` albo
  `NUMER UMOWY` w drugim położeniu: w przesuniętym pierwszym wierszu
  `URZĄDZENIA` i `CZYNNOŚCI ZREALIZOWANE` (rodzaj zlecenia jest w `order_kinds`
  jako nazwa z zamkniętej listy), a w wierszu na miejscu bez dowodu od `NUMER
  ZL.` (z datą w A, z innym Hiperłączem albo bez niego) `NUMER ZL.`, `ZWROT` i
  `UWAGI`. Odtworzenie stawia pod `NUMER ZL.` wiersza z tą komórką w Kopii
  Hiperłącze syntetyczne, żeby odtworzony wiersz miał ten sam dowód. Wiersz Rejestru w Przygotowaniu ma w Kopii komórki pod
  nagłówkami bez zakazanych, a wartości z drugiego położenia w jego komórkach
  (`DATA`, `NUMER ZL.`) maskuje strażnik. Odtworzenie traktuje wiersz z dwoma
  położeniami jako zastrzeżenie, nie jako granicę blokującą.

Każdy przypadek sond przeglądów #917 (rundy 1–3: 6, 77 i 35), #952 (23) i #966
(K1–K7) jest w tabeli decyzji (`~/.t3/notes/logi-837/opcja3/TABELA.md` na Macu
Maksa, opis PR); przemiatanie jej grup przez HTTP API Centrum to tabele położeń
w `tests/test_centrum_uporzadkowanie_intermax.py` (`POSITIONS`) i
`tests/test_centrum_logi_uruchomienia.py` (`REGISTER_POSITIONS`), z Uwagą
taty. Sondy przeglądów na tym kodzie: 3 wycieki ze 148 sond #917, #952 i K1–K7
z #966 (na `main` 050bd8911: 18 ze 141), każdy z pierwszej granicy niżej, i 11 z
13 sond P1–P9 z #966 r2 (na `main` 0), każdy z drugiej granicy.

Znane granice, w których adres albo numer Orange wychodzi:
- przesunięcie w prawo: tata wstawił dwie komórki w J:K albo K:L wiersza na
  miejscu, więc `NUMER UMOWY` stoi w M, poza oboma położeniami. Wycieka tak samo
  jak na `main` (3 przypadki sond). Zamknięcie wymagałoby trzeciego położenia
  w każdym wierszu, a wtedy `URZĄDZENIA` każdego wiersza (G = `ADRES`+2) byłoby
  w nim wartością `ADRES`;
- prawdziwa wartość w drugim położeniu, gdy podpis przesunięcia nie mówi
  prawdy o zakazanej kolumnie, i ta sama wartość w zwykłej kolumnie innego
  wiersza (przegląd #966 r2, W1, do decyzji Maksa): adres albo numer Orange
  wychodzi wtedy z tej zwykłej komórki do Logów i Skrzynki (Uwaga taty jest
  zamaskowana jako wolny tekst), a na `main` nie wychodzi. Podpis nie mówi
  prawdy w trzech klasach: kłamie na wierszu na miejscu (data z godziną w A albo
  Hiperłącze pod `URZĄDZENIA`), brak go w wierszu przesuniętym (data tekstem
  albo pusta, bez Hiperłącza) i jest prawdziwy, ale zakazana kolumna stoi na
  miejscu w częściowym przesunięciu (W4 z #917 r3: tata postawił z powrotem
  komórki od `WYKONAWCA` albo od `ADRES`). Sonda recenzenta: 11 z 11 takich
  przypadków wycieka, na `main` 0. Na kopii INTERMAX taty podpis zgadza się z
  położeniem odczytu w 84 z 84 wklejonych wierszy (pierwszy: data w A i
  Hiperłącze w G, 83: pusta A, data w C i Hiperłącze w I), 31 772 uporządkowane
  wiersze nie mają daty w A ani Hiperłącza w G, a kolizji prawdziwej wartości z
  całą zwykłą komórką innego wiersza jest 0;
- `ADRES`, który Excel trzyma jako datę z godziną, w wierszu przesuniętym
  czytanym bez przesunięcia: Kopia niesie go pod `DATA GODZ. POCZ.` (u taty
  `ADRES` jako data: 0 wierszy, #917);
- przesunięty wiersz z pustą datą z aplikacji, `ADRES` jako datą z godziną i
  Hiperłączem przeniesionym pod `NUMER ZL.` wygląda na wiersz na miejscu od
  `NUMER ZL.`, więc pamięć nie zna jego `NUMER UMOWY` spod `NUMER ZL.` (trzy
  fakty kłamią naraz);
- wiersz na miejscu, z którego tata usunął `NUMER ZL.` z Hiperłączem i sąsiednią
  komórkę, tak że `NUMER UMOWY` stoi pod `NUMER ZL.`, i który jest
  uporządkowany: jedno położenie;
- wiersz z dwoma położeniami, który Uporządkowanie przeniosło z drugim
  położeniem w złym miejscu, a tata potem zmienił INTERMAX, zanim go przeczytało
  następne Uruchomienie w tej samej pracy Centrum: nowa wersja pliku nie ma już
  przeniesionej komórki.

Koszt na kopiach plików taty (tylko odczyt, Mac Maksa, pomiar w PR, src `main`
050bd8911 → ta zmiana): Kopia wejścia Uporządkowania na kopii INTERMAX z
wklejeniem (84 wiersze) bez Diagnozy 0 → 0 masek, po Diagnozie Przygotowania
165 (`NUMER ZL.` 83, `URZĄDZENIA` 82) → 0, po repro 1 w następnym Uporządkowaniu
82 → 0; komórek Kopii 518 → 517 (`URZĄDZENIA` przesuniętego pierwszego wiersza,
rodzaj zlecenia w `order_kinds`).
Uwagi o złamanym fakcie domeny w Kopii Przygotowania 41 okresów tygodniowych
2026 na kopii Rejestru z 20.10.2026: 0 → 0, w repro 1 jedna. Dwa położenia w
całym Rejestrze (Diagnoza): 11 → 11 wierszy, z wklejeniem 95 → 95. Wolny tekst
całego Rejestru (`CZYNNOŚCI ZREALIZOWANE`, `ZWROT`, `UWAGI`, 26 495 komórek) z
pamięcią po Diagnozie: 2 → 2 komórki z maską (wartości z miejscem w pamięci 2). Kopie Rejestru taty mają puste
`ADRES`, `NUMER UMOWY` i `NUMER ZL.`, więc o masce w Przygotowaniu mówi tylko
kopia INTERMAX z wklejeniem.

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
