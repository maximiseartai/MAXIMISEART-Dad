# ADR 0017: Karta Uruchomienia wraca z Logów Uruchomienia

## Status

Zaakceptowana. Rozstrzyga główną część issue #427. Issue #722 (decyzja Maksa
z 2.11.2026) dodało kartę z wynikiem z Historii, gdy Logów nie ma. Zmienia
dwa miejsca
[ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md):

- „Centrum przerwane w trakcie zostawia tylko `uruchomienie-start` w
  dzienniku”: zostawia też plik ostatniego startu, po którym następny start
  Centrum nazywa je Urwanym Uruchomieniem;
- własne pliki Centrum: dochodzi `logs/ostatnie-uruchomienie.json`, poza
  Gitem i OneDrive.

Dopisek #845 (część #837): Urwana Wycena w efenix ma Logi Urwanego
Uruchomienia. Wycena w efenix pisze w trakcie dziennik Wyceny w efenix,
osobny plik Uruchomienia w `logs/dzienniki-wyceny/` (własny plik Centrum, poza
Gitem i OneDrive), wpis po wpisie: „zaczynam zlecenie” przed pierwszym
działaniem okna efenix przy zleceniu, więc przed każdym zapisem w efenix, i
„zlecenie skończone” z wynikiem i śladem zlecenia zaraz po nim. Start Centrum,
który zastanie dziennik Uruchomienia bez Logów i bez wpisu końca (dopisek
#870/#871 niżej), zamyka go jako Logi z nowym sposobem zakończenia
`interrupted` (bez wyniku, ze
zleceniami sprzed zgaśnięcia i zleceniem zaczętym bez wyniku), zanim przeczyta
kartę ostatniego Uruchomienia, i wysyła je jak zwykłe Logi przy pierwszym
zapytaniu tej pracy Centrum, już po starcie Kolejki wysyłki. Karta po starcie
to dalej karta Urwanego Uruchomienia, z liczbą zleceń skończonych przed
zamknięciem Centrum z każdym wynikiem. Plik Logów powstaje dalej tylko pełny:
dziennik nie jest niepełnym plikiem Logów, tylko osobnym plikiem, który czyta
wyłącznie start Centrum. Krótkie procesy dziennika nie piszą.

Dopisek #870/#871: o tym, czy Uruchomienie z dziennikiem doszło do wyniku,
mówi sam dziennik, nie Historia. Pierwsze działanie po wyniku dopisuje do
niego „koniec Uruchomienia” z wynikiem (z `fsync`), zanim powstaną Logi z
wynikiem i zanim pójdą do Skrzynki, a dziennik, w którym nie zapisała się
nawet pierwsza linia, Centrum od razu usuwa (nieudany zapis mógł zostawić ją
na dysku, a Zatrzymanie przy zleceniu zakończyć Wycenę przed następnym
wpisem). Start nie czyta Historii, bo reguła „pierwszy wiersz od startu” jest
prawdziwa tylko dla ostatniego startu (wiersz późniejszej Wyceny zabierał
dziennik urwanej bez Logów), a Historia nieczytelna albo bez rekordu metryk
dawała Wycenie z wynikiem Logi Urwanego Uruchomienia, które w Skrzynce
zastępowały Logi z wynikiem. Zgaśnięcie między rekordem metryk a wpisem końca
(milisekundy) zostawia dziennik bez wpisu końca: start zamyka go jako Logi
Urwanego Uruchomienia, a karta po starcie pokazuje Urwane Uruchomienie, choć
Historia ma wiersz. Logi z wynikiem jeszcze wtedy nie istnieją, więc w
Skrzynce niczego nie zastępują. Wpis końca przed rekordem metryk odrzucony: w
tym samym oknie dziennik Urwanej Wyceny znikałby bez żadnych Logów.

Dopisek #846 (część #837): pierwsza linia dziennika, start Uruchomienia, trafia
na dysk już przy starcie Wyceny w efenix, zanim ruszy jej wątek, a nie z
pierwszym zleceniem. Wycena zamknięta przed pierwszym zleceniem, np. gdy okno
efenix czeka na logowanie taty, też ma więc Logi Urwanego Uruchomienia, bez
zleceń, a karta po starcie pokazuje zero zleceń przed zamknięciem Centrum.
Komentarz postępu Wyceny w issue okresu (dopisek #846 w ADR 0015) powstaje
dopiero, gdy ta linia jest na dysku, a dziennik znika dopiero, gdy Kolejka
wysyłki przyjęła wersję końcową tego komentarza: na końcu Wyceny jej Logi z
wynikiem (działanie po wyniku za Logami usuwa dziennik, gdy kolejka je
przyjęła, także gdy wpis końca się nie zapisał). Start Centrum, który zastanie
dziennik, wysyła ją z niego, a karta po starcie zostaje taka, jak wyżej:
czytelny plik Logów idzie do Skrzynki taki, jaki jest; bez pliku Logów i bez
wpisu końca idą Logi Urwanego Uruchomienia; bez pliku Logów, a z wpisem końca
(Centrum zamknęło się tuż po wyniku), i przy pliku Logów, którego nie da się
odczytać, idzie wynik bez Logów: wynik z wpisu końca, zlecenia z dziennika i
dopisek, dlaczego pełnych Logów nie ma. Pliku Logów ten wynik nie tworzy, więc
karta po starcie dalej pokazuje wynik z Historii.

## Kontekst

Centrum trzymało tylko bieżące Uruchomienie procesu w pamięci, więc karta
wyniku ginęła z zamknięciem Centrum, choć Logi Uruchomienia mają prawie całą
jej treść. Uruchomienie zabite razem z Centrum (zamknięte okno konsoli, brak
prądu) nie zostawiało nic trwałego: rekord metryk i Logi powstają dopiero na
końcu. Issue zakładało, że Telemetria zapisuje start i że Metryki pokazują
takie Uruchomienie jako „Przerwane”. To nieprawda: „Przerwane” w Metrykach to
Zatrzymania z rekordem metryk, a jedynym śladem startu była linia dziennika
Centrum bez identyfikatora Uruchomienia.

## Decyzja

- **Plik ostatniego startu.** Przy każdym starcie Uruchomienia z Centrum,
  zanim ruszy jego wątek, Centrum nadpisuje atomowo
  `logs/ostatnie-uruchomienie.json`: identyfikator, proces, tryb, okres i
  chwilę startu, te same bezpieczne fakty co linia `uruchomienie-start` i
  nagłówek Logów. Pliku nikt nie usuwa. Nieudany zapis to jedna linia
  dziennika, a Uruchomienie biegnie dalej.
- **Urwane Uruchomienie wynika z plików, nie jest zapisywane.** Po starcie
  Centrum ostatnie Uruchomienie to ostatni start. Gdy ma plik Logów, jego
  karta wraca z Logów. Gdy go nie ma, a Historia ma jego wiersz, Centrum
  zamknęło się po zapisie rekordu metryk, a przed zapisem Logów: karta pokazuje
  wynik z Historii z tytułem i akcją z tej samej reguły co na żywo i z
  dopiskiem, że Centrum zamknęło się tuż po wyniku, więc szczegółów nie ma
  (#722). Jego wiersz to pierwszy wiersz tego procesu ze startem od startu z
  pliku, ta sama reguła, po której `CentrumRuns.remember` daje wierszowi
  identyfikator Uruchomienia, więc karta znajduje go także przed nią.
  Wcześniejsze Uruchomienia z Centrum startowały przed nim, bo Centrum
  prowadzi jedno naraz. Gdy nie ma ani Logów, ani wiersza Historii,
  Centrum zamknęło się w trakcie i to Urwane Uruchomienie, bo Logi powstają
  przed końcem każdego Uruchomienia, także przy Zatrzymaniu. Nic nie jest
  zapisywane na końcu, więc nie ma kolejności względem działań po wyniku, a
  zabicie Centrum w dowolnej chwili daje kartę zgodną z Historią.
- **Karta z Logów niesie tylko to, co w nich jest**: Komunikaty w trzech
  częściach, podsumowanie, etapy, sposób zakończenia i Rodzaj Zatrzymania.
  Tytuł wyniku i akcję po nim wylicza ta sama reguła co na żywo. Diagnozy i
  „Wyślij do Maksa” nie ma: żyją tylko przy Zatrzymaniu bieżącego Uruchomienia
  tej pracy Centrum, a „Uruchom ponownie” odtwarza Zatrzymanie z Diagnozą.
  Reguła prywatności Logów obowiązuje bez zmian.
- **Ostatnie Uruchomienie nie jest stanem żadnego Uruchomienia tej pracy
  Centrum.** Przychodzi w pierwszym widoku jako dopisek do stanu „bez
  Uruchomienia”, a pierwszy start w tej pracy Centrum go zastępuje.
- **Wiersz Historii otwiera kartę swojego Uruchomienia** z jego Logów, po
  identyfikatorze Uruchomienia. Uruchomienie bez Logów (ze Skryptu dla maszyn,
  sprzed Logów albo z plikiem, którego nie da się odczytać) dostaje zwykłą
  odpowiedź „karty nie ma”, nie błąd, więc przeglądarka nie proponuje
  ponowienia.
- Urwane Uruchomienie zostaje w Centrum tylko do następnego startu
  Uruchomienia: nie ma Logów, rekordu metryk ani wiersza Historii. Wyjątek od
  #845: Urwana Wycena w efenix ma Logi Urwanego Uruchomienia z dziennika (dopisek
  wyżej), ale też nie ma rekordu metryk ani wiersza Historii, więc nie ma
  karty wiersza Historii ani Powiadomienia o zakończonej Wycenie w efenix.

## Odrzucone warianty

- **Niepełny plik Logów zapisany przy starcie.** Każdy czytelnik Logów
  (kolejka Skrzynki, podsumowanie, weryfikacja) musiałby pomijać niepełny
  plik, a Logi przestałyby być pełnym obrazem Uruchomienia.
- **Usuwanie pliku startu na końcu Uruchomienia.** Wymaga kolejności po
  zapisie Logów, a zabicie Centrum między tymi krokami źle nazywa
  Uruchomienie.
- **Szukanie startu bez końca w dzienniku Centrum.** To tekst dla pomocy
  technicznej, bez identyfikatora Uruchomienia.
- **Karta z Logów jako zakończone Uruchomienie na żywo.** Wymagałaby
  zmyślonego postępu i Diagnozy, której po zamknięciu Centrum nie ma kto
  obsłużyć.

## Konsekwencje

- Nieudany zapis Logów na końcu Uruchomienia (np. brak uprawnień do katalogu
  Logów, który leży obok pliku startu) daje po ponownym starcie Centrum kartę
  z wynikiem z Historii, jak zamknięcie Centrum przed zapisem Logów.
- Wiersz Historii dostaje identyfikator Uruchomienia dopiero chwilę po zapisie
  rekordu metryk (`CentrumRuns.remember` czyta plik metryk i dopisuje jedną
  linię). Centrum zamknięte w tej chwili zostawia wiersz Historii bez
  identyfikatora (pochodzenie `.cmd`), a karta po starcie i tak pokazuje jego
  wynik, bo szuka wiersza po procesie i chwili startu.
- Uruchomienie spoza Centrum (Skrypt dla maszyn) tego procesu po starcie
  Urwanego Uruchomienia dałoby mu na karcie swój wynik, jak w
  `CentrumRuns.remember` dostałoby jego identyfikator. To rzadkie: na
  komputerze taty Uruchomienia biegną z Centrum.
- Wiersz Historii nie mówi, czy Zatrzymanie przyszło po silniku. Po błędzie
  podsumowania przy zapisie karta na żywo proponuje otwarcie pliku, a karta z
  Historii „Uruchom ponownie”; ponowne Uruchomienie zostawia pliki, które
  powstały, i mówi, co z nimi zrobić.
- Plik Logów bez pola Diagnozy (sprzed tego pola, tylko u Maksa) daje „karty
  nie ma”.
