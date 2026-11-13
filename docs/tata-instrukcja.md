# Instrukcja dla taty

Co tydzień są dwa kroki, zawsze w tej kolejności:

1. **Przygotowanie pliku zbiorczego**: z Rejestru zleceń powstają Rozliczenie
   wewnętrzne i Plik zbiorczy okresu.
2. **Przebieg rozliczeń**: z Pliku zbiorczego powstają rozliczenia
   pracowników.

Oba kroki robisz w Centrum rozliczeń, które otwierasz skrótem na pulpicie:

| Co chcesz zrobić | Gdzie w Centrum rozliczeń |
|---|---|
| Zobaczyć Status okresu każdego tygodnia | Strona `Okresy` |
| Otworzyć Plik zbiorczy, Rozliczenie wewnętrzne albo Folder okresu | Jedno kliknięcie w wierszu okresu |
| Przygotować plik zbiorczy | Strona `Uruchomienia`, proces `Przygotowanie pliku zbiorczego` |
| Utworzyć rozliczenia pracowników | Strona `Uruchomienia`, proces `Przebieg rozliczeń` |
| Zaktualizować narzędzie | Przycisk `Zaktualizuj narzędzie`, gdy jest nowsza wersja: w oknie `Ustawienia` (sekcja `Narzędzie`), w Powiadomieniach i w Diagnozie |
| Napisać do Maksa, ogólnie albo o jednym Uruchomieniu | Ikona „Napisz do Maksa” w prawym górnym rogu albo na karcie Uruchomienia |

## Pierwsza instalacja

Pierwszą instalację robi osoba utrzymująca narzędzie:

1. Zainstaluj Python 3.13 lub nowszy.
2. W folderze narzędzia uruchom:

   ```powershell
   py -3 -m pip install -r requirements.txt
   py -3 install_centrum_shortcut.py
   ```

   Na pulpicie pojawi się skrót „Centrum rozliczeń” z ikoną. Ten sam skrót
   trafia do Autostartu Windows, więc Centrum startuje samo po zalogowaniu, bez
   otwierania karty; kartę otwierasz skrótem z pulpitu. Drugie polecenie
   powtórz tylko po przeniesieniu folderu narzędzia albo po instalacji nowego
   Pythona. Start razem z Windows wyłączasz i włączasz przełącznikiem
   `Uruchamiaj Centrum razem z Windows` w oknie `Ustawienia`, w sekcji
   `Narzędzie`.

Osoba utrzymująca narzędzie umieszcza w folderze `config` narzędzia trzy
wzorce: `Wzorzec rozliczenia wewnętrznego.xlsx`, `Wzorzec pliku zbiorczego.xlsx`
i `Wzorzec rozliczenia pracownika.xlsx`. Ten ostatni to pusty plik rozliczenia
pracownika bez nazwy wykonawcy (u Ciebie `Rozliczenie {okres} -.xlsx`); z niego
powstają pliki pracowników.
Nie zmieniaj ich i nie podmieniaj plikami z poprzedniego tygodnia.

W tym samym folderze `config` osoba utrzymująca narzędzie umieszcza też
konfigurację wykonawców `worker_mapping.yaml`, czyli listę Twoich pracowników.
Ten plik jest tylko na Twoim komputerze, nie w internecie. Plik
`worker_mapping.example.yaml` obok to przykład z wymyślonymi nazwiskami;
narzędzie z niego nie korzysta.

### Foldery tygodni

Tygodnie leżą w OneDrive w `Załączniki\Rozliczenia {rok}\{miesiąc}\INEA`, np.
`Rozliczenia 2026\10_Październik_2026\INEA\13_19_10_2026`. Narzędzie szuka
folderu tygodnia we wszystkich miesiącach, bo tylko Ty wiesz, w którym miesiącu
rozliczasz dany tydzień.

- Zakładaj z góry **tylko pusty folder tygodnia**, tak jak dotąd. Nie kopiuj do
  niego pustych plików rozliczeń: narzędzie nie nadpisuje istniejących plików,
  więc pusty plik zablokuje Przygotowanie pliku zbiorczego.
- Nazwa folderu to okres: dzień wtorku, dzień poniedziałku, miesiąc i rok
  poniedziałku, np. `29_05_10_2026` dla 29 września – 5 października 2026.
- Jeden tydzień ma jeden folder. Ten sam tydzień w dwóch miesiącach zatrzyma
  narzędzie z komunikatem, który pokaże oba miejsca.

## Centrum rozliczeń

Centrum rozliczeń to strona w przeglądarce, która działa tylko na Twoim
komputerze. Nie otwiera czarnego okna konsoli.

### Uruchomienie

1. Dwukrotnie kliknij skrót „Centrum rozliczeń” na pulpicie.
2. Po chwili przeglądarka sama otworzy kartę Centrum rozliczeń
   (`http://127.0.0.1:47811/`).
3. Za pierwszym razem kliknij `Ustawienia` (zębatka w lewym dolnym rogu, nad
   `Zamknij Centrum rozliczeń`) i w sekcji `Foldery` wskaż folder okresów, czyli
   `Załączniki` w OneDrive (ten z folderami `Rozliczenia 2025`,
   `Rozliczenia 2026`), i Rejestr zleceń. Centrum je zapamięta. Gdy wskażesz
   folder tygodnia, `INEA` albo miesiąca, Centrum i tak zapamięta `Załączniki`
   i dopisze przy nim „wszystkie lata”.

Zamknięcie karty przeglądarki nie wyłącza Centrum. Żeby wrócić, kliknij skrót
jeszcze raz: otworzy się karta działającego Centrum, a nie druga kopia.

### Zamknięcie

1. W menu po lewej kliknij `Zamknij Centrum rozliczeń`.
2. Potwierdź przyciskiem `Zamknij Centrum`.
3. Karta pokaże `Centrum rozliczeń jest zamknięte`. Możesz ją zamknąć.

Centrum kończy pracę także po wylogowaniu albo wyłączeniu komputera.

Gdy trwa Uruchomienie procesu (także gdy czeka na Twoją decyzję), Centrum się
nie zamknie: pokaże, że trwa Uruchomienie procesu. Poczekaj na wynik na stronie
`Uruchomienia` i zamknij Centrum potem.

### Zatrzymanie i Diagnoza

Gdy Uruchomienie procesu się zatrzyma, Centrum pokaże komunikat w trzech
częściach i podpowie, co dalej:

- `Uruchom ponownie`: przyczynę usuniesz sam według części `Co zrobić`. Po
  poprawce kliknij przycisk; ten sam proces ruszy dla tego samego okresu i w tym
  samym trybie.
- `Diagnoza`: komunikat każe przekazać go osobie utrzymującej narzędzie albo po
  ponownym uruchomieniu wrócił ten sam komunikat. Kliknij `Diagnoza`. Centrum
  sprawdzi Twój komputer tylko do odczytu i wyjaśni przyczynę w trzech
  częściach. Niczego nie zmienia w Twoich plikach. Przy nieoczekiwanym błędzie
  narzędzia Diagnoza zaczyna się sama, bez klikania.

Gdy przyczyną jest sam komunikat zatrzymania, Centrum pisze tylko `Diagnoza
potwierdza ten komunikat.` Gdy wyjaśnienie mówi, co zrobić, popraw to i kliknij
`Uruchom ponownie`. Lista `Sprawdzono` pokazuje każde sprawdzenie Diagnozy.

Nowsza wersja narzędzia jest wyjaśnieniem tylko wtedy, gdy Diagnoza nie
znalazła innej przyczyny. Wtedy przy wyjaśnieniu jest przycisk `Zaktualizuj
narzędzie`. Gdy Diagnoza znalazła inną przyczynę, pod wyjaśnieniem jest tylko
krótkie zdanie `Jest też nowsza wersja narzędzia.` z tym samym przyciskiem,
drugim po `Uruchom ponownie`. Najpierw usuń przyczynę według wyjaśnienia;
aktualizacja może poczekać.

### Wyjaśnienie Diagnozy → co zrobić

Diagnoza wyjaśnia przyczynę komunikatem z tabel procesów (np. Rejestr zleceń
otwarty w Excelu) albo jednym z tych:

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znalazłem przyczyny na tym komputerze” | Przyczyna nie leży na Twoim komputerze. Kliknij `Wyślij do Maksa`. |
| „Jest nowsza wersja narzędzia” | Kliknij `Zaktualizuj narzędzie` przy wyjaśnieniu (niżej, „Aktualizacja narzędzia”). Gdy karta Centrum sama się odświeży, uruchom proces ponownie. Bez internetu Diagnoza tego nie sprawdza. |
| „Plik okresu jest otwarty w Excelu” | Zapisz i zamknij wskazany plik w Excelu i uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z tego samego folderu pozostawiony plik zaczynający się od `~$`. |
| „Plik jest tylko w OneDrive w chmurze” | W Eksploratorze plików kliknij wskazany plik prawym przyciskiem myszy i wybierz „Zawsze zachowuj na tym urządzeniu”. Gdy ikona chmurki zmieni się w zielony znacznik, uruchom ponownie. |

### Zgłoszenie do Maksa

Pod wyjaśnieniem Diagnozy jest przycisk `Wyślij do Maksa`. Gdy wyjaśnienie
mówi, co poprawić, pierwszy jest `Uruchom ponownie`, a `Wyślij do Maksa` drugi.

1. Rozwiń `Co zostanie wysłane`, jeśli chcesz zobaczyć dokładną treść
   Zgłoszenia: komunikat, proces, okres, wersję narzędzia, wynik każdego
   sprawdzenia Diagnozy i ostatnie wpisy dziennika Centrum. Nie ma w niej
   adresów, numerów zleceń ani treści wierszy.
2. Kliknij `Wyślij do Maksa`. Nie ma dodatkowego pytania „Na pewno?”.
3. W miejscu przycisku pojawi się `Zgłoszenie wysłane do Maksa. Poczekaj na
   naprawę.` Potwierdzenie zostaje po odświeżeniu karty.

Gdy ten sam problem wróci przy kolejnym Uruchomieniu, a Maks jeszcze go nie
naprawił, zamiast przycisku zobaczysz `Zgłoszenie tego problemu już jest
wysłane i czeka na naprawę.` Drugie Zgłoszenie nie powstaje. Gdy Maks zamknie
Zgłoszenie, a problem wróci, po Diagnozie znowu będzie `Wyślij do Maksa`.

Zgłoszenie trafia do prywatnego repozytorium Zgłoszeń Maksa na GitHubie.
Brak internetu niczego nie psuje, dopóki niczego nie wysyłasz.

### Zgłoszenie → co zrobić

Gdy Zgłoszenie nie może od razu wyjść, Centrum trzyma je na tym komputerze i
wyśle je samo, bez klikania. W miejscu przycisku zobaczysz, dlaczego czeka.
W Powiadomieniach przy Zgłoszeniu zobaczysz to samo: na co czeka albo że
trzeba skontaktować się z Maksem.

- `Wyślę do Maksa, gdy będzie internet.` Niczego nie musisz robić.
  Zgłoszenie wyjdzie najpóźniej minutę po powrocie internetu.
- `Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.` (z czerwoną ikoną)
  Na komputerze nie ma Tokenu do Zgłoszeń albo przestał działać. Powiedz
  Maksowi. Gdy go naprawi, Zgłoszenie wyjdzie samo.
- `Tego Zgłoszenia nie da się wysłać. Skontaktuj się z Maksem.` Skrzynka
  Zgłoszeń nie przyjęła tego Zgłoszenia. Internet tego nie naprawi. Powiedz
  Maksowi.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie udało się zapisać Zgłoszenia na tym komputerze” | Kliknij `Spróbuj ponownie`. Jeśli komunikat wraca, rozwiń `Co zostanie wysłane`, skopiuj treść i wklej ją do maila do Maksa. Po odświeżeniu karty najpierw kliknij `Diagnoza`. |

W oknie `Ustawienia`, w sekcji `Zgłoszenia`, widać `Gotowe`, gdy Token do Zgłoszeń
jest na komputerze, `Brak tokenu`, gdy go nie ma, albo
`Token odrzucony`, gdy GitHub go nie przyjmuje. Wtedy powiedz
Maksowi. Token wpisuje Maks; Ty niczego tam nie wpisujesz.

### Napisz do Maksa

Ikona „Napisz do Maksa” w prawym górnym rogu otwiera okno, w którym piszesz
Uwagę do Maksa. Wpisz `Tytuł` i, jeśli chcesz, `Treść`. W `Dotyczy` wybierz
`Ogólna`, gdy piszesz o całym narzędziu, albo `Do Uruchomienia`, gdy piszesz o
jednym Uruchomieniu, i zaznacz je na liście ostatnich Uruchomień. Ramka
`Maks dostanie` pokazuje dokładnie to, co dostanie Maks. Kliknij `Wyślij`.

Na karcie zakończonego Uruchomienia i przy Uruchomieniach w zakładce
`Historia` jest ta sama ikona: `Napisz do Maksa o tym Uruchomieniu`. Okno
otwiera się wtedy z tym Uruchomieniem już zaznaczonym. Maks dostanie jego
proces, okres, tryb i wynik, więc nie musisz ich przepisywać.

Bez internetu zobaczysz `Wyślę do Maksa, gdy będzie internet.` i nic więcej
nie musisz robić: Uwaga wyjdzie sama. Gdy zobaczysz `Token do Zgłoszeń nie
działa. Skontaktuj się z Maksem.`, Uwaga czeka na tym komputerze i wyjdzie
sama, gdy Maks naprawi Token do Zgłoszeń. `Tej Uwagi nie da się wysłać.
Skontaktuj się z Maksem.` znaczy, że Skrzynka Zgłoszeń jej nie przyjęła.

### Powiadomienia

Dzwonek w prawym górnym rogu, obok ikony „Napisz do Maksa”, otwiera
Powiadomienia. Widać tam Twoje Uwagi i Zgłoszenia, od najnowszych, i co się z
nimi stało: `Uwaga wysłana do Maksa.` (przy Zgłoszeniu `Zgłoszenie wysłane do Maksa.
Poczekaj na naprawę.`), `Wyślę do Maksa, gdy będzie internet.`,
`Token do Zgłoszeń nie działa. Skontaktuj się z Maksem.`, `Tej Uwagi nie da
się wysłać. Skontaktuj się z Maksem.` (przy Zgłoszeniu `Tego Zgłoszenia`),
`Rozwiązana. Będzie w następnej wersji.` albo `Maks przeczytał.`.

Gdy Maks wyda nową wersję narzędzia, nad listą pojawia się karta `Nowa wersja`
z numerem, np. `Nowa wersja 0.2.0`: co nowego, które Twoje Uwagi i Zgłoszenia
rozwiązuje, i przycisk `Zaktualizuj narzędzie`. Po aktualizacji przycisk znika,
a karta zostaje na liście jako historia.

Czerwona kropka na dzwonku znaczy, że Maks coś zrobił z Twoją sprawą albo wydał
nową wersję. Gdy wejdziesz w Powiadomienia, kropka gaśnie; nowe sprawy mają małą kropkę, dopóki
nie wyjdziesz. Niczego nie oznaczasz ręcznie. Centrum sprawdza to przy
otwarciu i najwyżej raz na 10 minut. Bez internetu nic się nie pokazuje i nic
się nie psuje; Centrum sprawdzi ponownie później.

Centrum zapisuje Twoje Uwagi, Zgłoszenia i przeczytane Powiadomienia w folderze
`config`. Gdy na chwilę nie może, bo inny program trzyma plik, nad listą
pojawia się komunikat. Centrum pamięta zmiany i zapisze je samo; komunikat
zniknie, gdy się uda.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Centrum nie może teraz zapisać Powiadomień na tym komputerze” | Nie zamykaj Centrum. Zamknij program, który może trzymać plik nazwany w komunikacie, i otwórz Powiadomienia ponownie. Jeśli komunikat zostaje, wyślij Uwagę do Maksa. |

### Aktualizacja narzędzia

W oknie `Ustawienia`, w sekcji `Narzędzie`, widać wersję narzędzia, np.
`1a2b3c4 od 20.10.2026`, i czy jest najnowsza: `Aktualna`, `Jest nowsza
wersja` albo `Nie sprawdzono` (bez internetu). Gdy Maks zapyta, którą wersję
masz, przeczytaj mu ją. Przycisk `Zaktualizuj narzędzie` jest w tej sekcji i w
Diagnozie tylko wtedy, gdy jest nowsza wersja.

1. Kliknij `Zaktualizuj narzędzie`: w oknie `Ustawienia` albo w
   Diagnozie. Oba przyciski robią to samo.
2. Poczekaj. Pod przyciskiem widać `Pobieranie nowej wersji…`, a gdy nowa
   wersja potrzebuje nowych bibliotek, potem `Instalowanie bibliotek…` (to może
   potrwać kilka minut). Na końcu widać `Ponowne uruchamianie Centrum…`. Każdy
   przycisk aktualizacji jest wtedy wyłączony. Nie zamykaj karty i nie klikaj
   skrótu: Centrum samo uruchamia się w nowej wersji.
3. Na końcu zobaczysz jedno z dwóch:
   - Karta sama się odświeży i na chwilę pokaże `Zaktualizowano`. Działa już
     nowa wersja; niczego nie zamykasz.
   - `Masz najnowszą wersję.` Niczego więcej nie robisz.

Gdy trwa Uruchomienie procesu, Centrum nie zaktualizuje narzędzia: poczekaj
na wynik na stronie `Uruchomienia`. W trakcie aktualizacji nie uruchomisz
procesu ani nie zamkniesz Centrum.

### Aktualizacja narzędzia → co zrobić

Gdy aktualizacja się nie uda, narzędzie działa dalej w wersji sprzed
kliknięcia (chyba że komunikat mówi, że nie dało się jej przywrócić), a pod
przyciskiem pojawi się komunikat w trzech częściach i przycisk `Wyślij do
Maksa`. Rozwiń `Co zostanie wysłane`, żeby zobaczyć Zgłoszenie
przed wysłaniem.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „brak połączenia z GitHubem” | Sprawdź internet i kliknij `Zaktualizuj narzędzie` jeszcze raz. Bez internetu przycisku może nie być; wraca najpóźniej minutę po powrocie internetu, gdy wrócisz do karty Centrum. |
| „nie ma Gita” | Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „GitHub prosi o logowanie” | Nie loguj się nigdzie. Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „inna gałąź narzędzia” | Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „zmiany zrobione na tym komputerze” | Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „Nie udało się zainstalować bibliotek” | Kliknij `Zaktualizuj narzędzie` jeszcze raz. Jeśli komunikat wraca, kliknij `Wyślij do Maksa`. |
| „z nieoczekiwanego powodu” | Kliknij `Zaktualizuj narzędzie` jeszcze raz. Jeśli komunikat wraca, kliknij `Wyślij do Maksa`. |
| „Nowa wersja narzędzia nie wystartowała” | Niczego nie zamykasz: Centrum samo wróciło do poprzedniej wersji, a karta odświeżyła się na niej z tym komunikatem pod tytułem strony. Przekaż sprawę Maksowi: kliknij `Wyślij do Maksa`. |
| „nie dało się przywrócić poprzedniej wersji” | Kliknij `Zaktualizuj narzędzie` jeszcze raz. Jeśli komunikat wraca, kliknij `Wyślij do Maksa`. |

Bez internetu `Wyślij do Maksa` zostawi Zgłoszenie na tym komputerze i wyśle
je samo, gdy wróci internet (więcej w „Zgłoszenie → co zrobić”).

### Komunikaty startu Centrum rozliczeń

Gdy Centrum nie może wystartować, zamiast karty pojawi się okienko z trzema
częściami: `Co się stało`, `Gdzie` i `Co zrobić`. Znajdź w tabeli wiersz z
fragmentem pierwszej części.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „zajmuje inny program” | Uruchom ponownie komputer i kliknij skrót. Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie. |
| „Działa już Centrum rozliczeń w innej wersji” | Zdarza się po aktualizacji narzędzia bez przycisku w Centrum. W otwartej karcie Centrum kliknij `Zamknij Centrum rozliczeń`, potem kliknij skrót ponownie. |
| „Brakuje biblioteki potrzebnej Centrum rozliczeń” | W folderze narzędzia uruchom `py -3 -m pip install -r requirements.txt` i kliknij skrót ponownie. |
| „nie wystartowało z nieoczekiwanego powodu” | Kliknij skrót ponownie. Jeśli komunikat wraca, przekaż osobie utrzymującej narzędzie plik `logs\centrum-rozliczen.log` z folderu narzędzia. |
| „nie wystartowało po aktualizacji narzędzia” | Nie wystartowała ani nowa, ani poprzednia wersja. Przekaż komunikat Maksowi. |
| „Aktualizacja narzędzia jeszcze się kończy” | Centrum właśnie startuje w nowej wersji albo wraca do poprzedniej. Poczekaj 10 minut i kliknij skrót ponownie. |

Plik `logs\centrum-rozliczen.log` to dziennik Centrum: zapisuje tylko start,
zamknięcie, port, rodzaj błędu, aktualizacje narzędzia i czas otwierania
stron, bez danych z Twoich plików. Możesz go bezpiecznie przekazać do diagnozy.

## Przygotowanie pliku zbiorczego

### Kiedy uruchomić

- Eksport zleceń całego okresu (od wtorku do poniedziałku) jest już w Rejestrze
  zleceń `ZLECENIA INTERMAX OD 08_11_2021.xlsx`.
- Rejestr zleceń jest zapisany i **zamknięty** w Excelu.
- Folder tygodnia jest założony w folderze `INEA` właściwego miesiąca
  (zob. [Foldery tygodni](#foldery-tygodni)) i nie ma jeszcze plików
  `Rozliczenie wew. {okres}.xlsx` ani `Rozliczenie {okres} - zbiorcze.xlsx`.

Narzędzie tylko czyta Rejestr zleceń i wzorce. Nigdy ich nie zmienia.

### Kroki

Rejestr zleceń i folder okresów wskazujesz raz w oknie `Ustawienia`, w sekcji
`Foldery`; potem Centrum je pamięta.

1. Na stronie `Okresy` karta `Następny krok` pokazuje ostatni pełny okres.
   Kliknij `Podgląd bez zapisu`. Żeby przygotować inny tydzień, kliknij
   `Przygotuj plik zbiorczy` w jego wierszu Tablicy okresów albo wybierz okres
   z listy `Okres` na stronie `Uruchomienia`.
2. Podgląd bez zapisu niczego nie tworzy. Pokazuje plan: liczby zleceń,
   ostrzeżenia, `Zlecenia na dzień` (dzień z liczbą `0` ma żółty znak) i nazwy
   obu plików. Na górze widać etapy `Sprawdzanie`, `Odczyt danych`,
   `Planowanie` i `Zapisywanie`.
3. Zapisz i zamknij Rejestr zleceń w Excelu. Kliknij `Uruchom` i potwierdź w
   okienku `Uruchomić z zapisem?`. Jeśli dla tego okresu nie było jeszcze
   udanego podglądu, okienko pokazuje żółtą uwagę `Nie było podglądu bez
   zapisu`; Centrum pamięta podgląd także po odświeżeniu karty.
4. Jeśli okres jest niepełny, pojawi się okienko `Kontynuować mimo niepełnego
   okresu?` z liczbami `Zlecenia na dzień`. Kliknij `Kontynuuj` albo `Przerwij
   bez zapisu`. Okienko czeka na Ciebie także po odświeżeniu albo ponownym
   otwarciu karty.
5. Wynik `Plik zbiorczy przygotowany · wymaga sprawdzenia` oznacza, że oba
   pliki powstały razem. Pod nim jest to, co zostało do uzupełnienia w Excelu,
   z przyciskiem `Uzupełnij`, a niżej ostrzeżenia.
   Przycisk `Folder okresu` otwiera folder z nimi, a na stronie `Okresy` okres
   ma Status `Plik zbiorczy przygotowany`.

Zatrzymanie pokazuje od razu trzy części komunikatu: co się stało (tytuł),
gdzie (pinezka) i co zrobić (klucz). Tabela niżej objaśnia każdy komunikat.
Po poprawce kliknij `Uruchom ponownie`. Ostrzeżenia są osobno, pod wynikiem:
pliki powstały, ale coś wymaga uwagi.

Zamknięcie karty przeglądarki nie przerywa pracy. Gdy coś już trwa, drugie
uruchomienie dostaje komunikat, że trwa już Uruchomienie procesu. Zakładka
`Historia` pokazuje wszystkie uruchomienia, także dawne z launcherów `.cmd`
(z odznaką `.cmd`).

### Co sprawdzić po zakończeniu

- Wynik `Plik zbiorczy przygotowany · wymaga sprawdzenia` oznacza, że oba
  pliki powstały razem. Zatrzymanie oznacza, że nie powstał żaden plik. Wtedy
  znajdź komunikat w tabeli poniżej. Jedyny wyjątek to komunikat, że pliki
  okresu powstały, ale nie udało się pokazać podsumowania.
- Sprawdź podsumowanie: `Zlecenia okresu`, `Zlecenia skuteczne`,
  `Pominięte puste wiersze` i `Zlecenia na dzień`. Dzień z liczbą `0` może
  oznaczać brakujący eksport.
- `Pominięte puste wiersze` to wszystkie całkowicie puste wiersze Rejestru od
  pierwszego do ostatniego zlecenia okresu, także te między zleceniami innych
  tygodni. Nie trafiają do żadnego pliku.
- Liczba `Ostrzeżenia` to ostrzeżenia pod wynikiem: pliki powstały, ale coś
  wymaga uwagi, co najmniej kolumny z opisu technika. Każde ostrzeżenie jest
  opisane w tabeli poniżej.
- W Folderze okresu (np. `INEA\08_14_09_2026`) są dwa nowe pliki:
  `Rozliczenie wew. {okres}.xlsx` i `Rozliczenie {okres} - zbiorcze.xlsx`.
- Rozliczenie wewnętrzne ma wszystkie zlecenia okresu, skuteczne i
  nieskuteczne, w kolejności z Rejestru, bez pustych wierszy i z wyróżnieniami
  kolorem i pogrubieniem jak w Rejestrze.
- Plik zbiorczy ma wszystkie Zlecenia skuteczne od wiersza 18, bez przerw.
  W kolumnach `N:AP` są już Ilości usług według Reguł ilości. Stawki, sumy,
  formuły i link do Słownika są jak we wzorcu.

### Co dalej ręcznie

1. Uzupełnij `UWAGI` i `zwrot` w Rozliczeniu wewnętrznym.
2. Przejrzyj Ilości usług w Pliku zbiorczym. Uzupełnij kolumny z opisu
   technika i wiersze wskazane w ostrzeżeniach (niżej, „Uzupełnienie pliku
   zbiorczego”). Jeśli chcesz pominąć jakieś Zlecenie skuteczne, usuń je ręcznie.
3. Zapisz i zamknij oba pliki.
4. Uruchom Przebieg rozliczeń w Centrum rozliczeń.

### Komunikat → co zrobić

Każdy komunikat ma trzy części: co się stało, gdzie i co zrobić. Znajdź w
tabeli wiersz z fragmentem pierwszej części. `Gdzie` wskazuje plik, arkusz albo
numery wierszy Rejestru zleceń. Po każdym zatrzymaniu nie powstał żaden plik,
więc po poprawce wystarczy uruchomić proces ponownie. Wyjątki: po komunikacie
o niepokazanym podsumowaniu pliki okresu już są, a po komunikacie o pliku,
którego nie udało się usunąć, w Folderze okresu został wskazany plik.
Jeśli komunikat mówi, że obok Folderu okresu został folder tymczasowy, najpierw
usuń każdy folder, którego nazwa zaczyna się tak, jak podaje komunikat (kropką,
z `.staging-` na końcu). To nie są Foldery okresu.

#### Zatrzymania

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Rejestr zleceń jest otwarty w Excelu” | Zapisz i zamknij Rejestr zleceń, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu Rejestru pozostawiony plik `~$ZLECENIA INTERMAX OD 08_11_2021.xlsx`. |
| „Nie znaleziono Rejestru zleceń” | W oknie `Ustawienia`, w sekcji `Foldery`, wskaż właściwy plik Rejestru zleceń i uruchom ponownie. |
| „Nie można teraz odczytać Rejestru zleceń” | Nie poprawiaj Rejestru. Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy Rejestr otwiera się w Excelu. Zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać Rejestru zleceń” | Sprawdź, czy Rejestr otwiera się w Excelu i jest zapisany jako `.xlsx`. Zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „nie znaleziono arkusza ze zleceniami” | Sprawdź, czy w `Ustawieniach` wskazano plik Rejestru zleceń. Pierwszy wiersz arkusza ze zleceniami musi mieć wszystkie nagłówki wymienione w komunikacie. |
| „W Rejestrze zleceń brakuje” | Dopisz albo popraw wymieniony nagłówek w pierwszym wierszu arkusza ze zleceniami. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „więcej niż raz, więc nie wiadomo, z której kolumny brać dane” | Zostaw wymieniony nagłówek tylko w jednej kolumnie: zmień nazwę drugiej kolumny albo ją usuń. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „Zlecenia tego okresu są w więcej niż jednym arkuszu” | Przenieś zlecenia tego okresu do jednego z wymienionych arkuszy. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „Wklejone zlecenia na dole Rejestru zleceń nie są jeszcze uporządkowane, a mogą należeć do tego okresu” | W Centrum rozliczeń kliknij `Uporządkuj INTERMAX`, potem uruchom Przygotowanie ponownie. Jeśli Uporządkowanie się zatrzyma, jego komunikat mówi, który wiersz poprawić. |
| „bez poprawnej daty w kolumnie DATA GODZ. POCZ.” | We wskazanych wierszach wpisz datę zlecenia albo wyczyść cały wiersz, jeśli jest zbędny. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „tak ani nie w SKUTECZNE” | `Gdzie` pokazuje komórki Rejestru zleceń, np. `L42081`: osobno puste i osobno z inną wartością, z jej treścią w cudzysłowie. We wszystkich wskazanych komórkach wpisz `tak` albo `nie`. Braki w `SKUTECZNE` poprawiaj w Rejestrze zleceń przed uruchomieniem, a nie w Rozliczeniu wewnętrznym, bo Rozliczenie wewnętrzne powstaje z Rejestru. Zapisz i zamknij Rejestr, uruchom ponownie. |
| „spoza konfiguracji wykonawców” | Literówkę w `WYKONAWCA` popraw we wskazanych wierszach Rejestru. Nowego wykonawcę trzeba dopisać do konfiguracji wykonawców (`config\worker_mapping.yaml`, tej samej co w Przebiegu rozliczeń); poproś o to osobę utrzymującą narzędzie. |
| „nie ma żadnego zlecenia z tego okresu” | Sprawdź, czy wybrano właściwy okres i czy eksport zleceń jest zapisany w Rejestrze. Uruchom ponownie. |
| „Plik tego okresu już istnieje” | Narzędzie nie nadpisuje plików okresu, żeby nie stracić ręcznych poprawek. Sprawdź okres. Jeśli plik ma powstać od nowa, przenieś albo usuń wskazany plik i uruchom ponownie. Jeśli w Folderze okresu jest samo Rozliczenie wewnętrzne, bez Pliku zbiorczego, a poprzednie uruchomienie nie doszło do wyniku (np. zabrakło prądu), to jest niedokończony zapis: usuń to Rozliczenie wewnętrzne i uruchom ponownie. |
| „Nie znaleziono folderu okresów” | W oknie `Ustawienia`, w sekcji `Foldery`, wskaż istniejący folder okresów, np. `Załączniki`, i uruchom ponownie. |
| „Nie można teraz odczytać folderu” | Otwórz folder wskazany w `Gdzie` w Eksploratorze plików. Jeśli się nie otwiera albo OneDrive pokazuje błąd, uruchom OneDrive i poczekaj, aż skończy synchronizację, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „w żadnym folderze miesiąca” | W `Rozliczenia {rok}` nie ma folderu tego tygodnia. W folderze `INEA` miesiąca, do którego należy tydzień, załóż pusty folder o nazwie okresu, np. `13_19_10_2026`, i uruchom ponownie. Pliki w nim zrobi narzędzie. |
| „jest w więcej niż jednym folderze miesiąca” | `Gdzie` pokazuje oba miesiące z folderem tego tygodnia. Zostaw folder tylko w tym miesiącu, w którym ma być rozliczony: drugi usuń albo zmień mu nazwę, np. dopisz na końcu ` stary`. Uruchom ponownie. |
| „Przerwano z powodu niepełnego okresu” | Uzupełnij eksport zleceń w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli okres jest pełny, w okienku kliknij `Kontynuuj`. |
| „Nie znaleziono wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. Nie twórz wzorca z pliku poprzedniego tygodnia. |
| „Wzorzec jest otwarty w Excelu” | Zamknij wzorzec w Excelu bez zapisywania zmian i uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu `config` pozostawiony plik `~$` wskazany w komunikacie. |
| „Nie można teraz odczytać wzorca” | Nie poprawiaj wzorca. Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać wzorca” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu brakuje nagłówka” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Wzorzec pliku zbiorczego ma nagłówek WYKONAWCA w kolumnie” | Przebieg rozliczeń czyta wykonawcę tylko z kolumny H. Otwórz `config\Wzorzec pliku zbiorczego.xlsx` i w wierszu 17 przenieś WYKONAWCA do kolumny H, a nagłówek z kolumny H do kolumny wskazanej w komunikacie. Zapisz i zamknij wzorzec, uruchom ponownie. Jeśli nie wiesz, jak to zrobić, przekaż komunikat osobie utrzymującej narzędzie. |
| „We wzorcu są scalone komórki” | Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można teraz odczytać konfiguracji wykonawców” | Nie poprawiaj konfiguracji wykonawców. Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać konfiguracji wykonawców” | Przekaż komunikat osobie utrzymującej narzędzie. Ta sama konfiguracja jest potrzebna w Przebiegu rozliczeń. |
| „Zapisano tylko jeden z dwóch plików okresu” | Usuń z Folderu okresu plik wskazany w `Gdzie` i uruchom ponownie. Jeśli Windows nie pozwala go usunąć, odczekaj chwilę, bo plik może sprawdzać antywirus albo OneDrive. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się zapisać plików okresu” | Sprawdź, czy folder okresów jest dostępny i czy pliki okresu nie są otwarte w Excelu, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Wystąpił nieoczekiwany błąd” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Pliki okresu powstały, ale nie udało się pokazać podsumowania” | Pojawia się po zapisie plików. Oba pliki są już w Folderze okresu, więc nie uruchamiaj procesu ponownie. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się pokazać planu” | Pojawia się tylko w podglądzie bez zapisu. Nic nie zapisano. Przekaż komunikat osobie utrzymującej narzędzie. |

#### Ostrzeżenia

Ostrzeżenie nie zatrzymuje procesu. Ostrzeżenie o niepełnym okresie pojawia
się przed zapisem w okienku `Kontynuować mimo niepełnego okresu?`. Pozostałe
ostrzeżenia są pod wynikiem, a podgląd bez zapisu pokazuje je zawsze takie same
jak zapis. Ostrzeżenia o ilościach do uzupełnienia wskazują numery wierszy
Pliku zbiorczego, a nie Rejestru zleceń. Przypomnienie o kolumnach z opisu
technika jest zawsze, więc wynik zapisu to `Plik zbiorczy przygotowany ·
wymaga sprawdzenia`: pliki powstały, a Ty uzupełniasz Plik zbiorczy przed
Przebiegiem rozliczeń.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu” | Sprawdź `Zlecenia na dzień`. Jeśli brakuje zleceń z końca tygodnia, kliknij `Przerwij bez zapisu`, uzupełnij eksport w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli w te dni naprawdę nie było zleceń, kliknij `Kontynuuj`. |
| „Narzędzie nie zna urządzenia z kolumny URZĄDZENIA” | W tych wierszach narzędzie wpisało tylko V, T i N. Uzupełnij pozostałe ilości ręcznie. Jeśli to nowe urządzenie, które będzie wracać, powiedz o nim osobie utrzymującej narzędzie. |
| „rozlicza się z opisu technika” | Prewencja, niedostępność usług albo puste `URZĄDZENIA`: narzędzie nie wpisało w tych wierszach żadnych ilości. Wpisz je według `CZYNNOŚCI ZREALIZOWANE`. |
| „Ilości, które wynikają z opisu technika” | Przypomnienie przy każdym Przygotowaniu. W kolumnach Y, AB, AD, AJ, AK, AL i AM uzupełnij ilości według `CZYNNOŚCI ZREALIZOWANE` w każdym wierszu. |
| „Dolne wiersze Pliku zbiorczego nie mają zer w kolumnach ilości” | Pliki powstały. Narzędzie wpisało ilości w tych wierszach tak samo jak w pozostałych, a puste komórki liczą się jak 0. Sprawdź je jak pozostałe wiersze. Jeśli zdarza się to często, poproś osobę utrzymującą narzędzie o dodanie wierszy z zerami we Wzorcu pliku zbiorczego. |

## Uzupełnienie pliku zbiorczego

Gdy okres ma Plik zbiorczy przygotowany, przycisk `Uzupełnij` jest na karcie
`Następny krok`, w wierszu okresu w Tablicy okresów i pod wynikiem
Przygotowania. Prowadzi na stronę, która pokazuje, co zostało do wpisania w
Excelu:

- `Wiersze bez reguły`: narzędzie nie zna `URZĄDZEŃ`, więc wpisało najwyżej
  V, T i N. Wiersz jest zrobiony, gdy wpiszesz w nim ilość w innej kolumnie.
- `Wiersze z opisu`: prewencja, niedostępność usług albo puste `URZĄDZENIA`.
  Wiersz jest zrobiony, gdy wpiszesz w nim jakąkolwiek ilość.
- Kolumny Y, AB, AD, AJ, AK, AL i AM: w każdym wierszu według `CZYNNOŚCI
  ZREALIZOWANE`. Strona podaje tylko, w ilu wierszach coś w nich wpisałeś.

Dotknij `Wiersze bez reguły` albo `Wiersze z opisu`, a zobaczysz tabelę jak w
Excelu, tylko z wierszami tego rodzaju. Z lewej stoją numer wiersza, `WYKONAWCA`,
`URZĄDZENIA`, `CZYNNOŚCI` i `CZYNNOŚCI ZREALIZOWANE`, z prawej kolumny od N do
AP, które przesuwasz w bok. Dotknij tekstu albo litery kolumny, a zobaczysz
cały tekst albo pełną nazwę pozycji cennika. Szare są kolumny, które wypełnia narzędzie.
Wiersz do uzupełnienia jest żółty. Komórka z Twoją ilością jest zielona, a
wiersz z choćby jedną Twoją ilością robi się zielony. W tabeli niczego nie
wpisujesz: ilości wpisujesz w Excelu.

`0` i pusta komórka to to samo. Strona czyta zapisany Plik zbiorczy, także gdy
masz go otwartego w Excelu, i nigdy go nie zmienia. Czyta go na nowo, gdy
wracasz do niej z Excela. Jeśli nie widzisz swoich wpisów, zapisz plik w Excelu
(Ctrl+S). `Otwórz Plik zbiorczy` otwiera plik w Excelu.

Gdy skończysz, zapisz i zamknij Plik zbiorczy i kliknij `Gotowe, rozlicz
pracowników`. Otwiera się strona `Uruchomienia` z Przebiegiem rozliczeń i tym
okresem (dalej „Przebieg rozliczeń” niżej).
Jeśli tego okresu nie ma do wyboru w Przebiegu rozliczeń (na przykład nie ma
jeszcze Pliku zbiorczego), strona mówi „Okresu … nie ma do wyboru, więc wybrany
jest …”. Sprawdź okres, zanim klikniesz `Podgląd bez zapisu`.

Po Przebiegu rozliczeń strony zostają jako podgląd: nad listą stoi `Przebieg
rozliczeń się odbył · tylko podgląd`, a `Gotowe, rozlicz pracowników` znika.
Wiersz, w którym nic nie wpisałeś, jest szary z napisem `bez ilości`: został na
zerach. Zielone zostają wiersze, które uzupełniłeś.

### Uzupełnienie → co zrobić

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie ma Pliku zbiorczego tego okresu” | Jeśli okresu nie przygotowano, najpierw przygotuj plik zbiorczy. Jeśli plik ma inną nazwę albo leży w innym folderze, przywróć go do Folderu okresu pod nazwą `Rozliczenie {okres} - zbiorcze.xlsx` i odśwież stronę. |
| „Nie można teraz odczytać Pliku zbiorczego” | Poczekaj, aż OneDrive skończy synchronizację, i odśwież stronę. Jeśli komunikat wraca, zapisz i zamknij Plik zbiorczy w Excelu i odśwież stronę. |
| „Plik zbiorczy jest uszkodzony” | Sprawdź, czy plik otwiera się w Excelu. Jeśli tak, zapisz go w Excelu i odśwież stronę. W innym wypadku przekaż komunikat osobie utrzymującej narzędzie. |
| „Brakuje nagłówka w Pliku zbiorczym” | Przywróć wskazany nagłówek tak jak w Wzorcu pliku zbiorczego, zapisz plik i odśwież stronę. |
| „Plik zbiorczy jest tylko w OneDrive w chmurze” | W Eksploratorze plików kliknij plik prawym przyciskiem myszy i wybierz „Zawsze zachowuj na tym urządzeniu”. Gdy się pobierze, odśwież stronę. |

## Przebieg rozliczeń

### Przed uruchomieniem

1. Zakończ pracę w pliku `Rozliczenie {okres} - zbiorcze.xlsx`.
2. Zamknij ten plik w Excelu.
3. Upewnij się, że folder `Rozliczenie pracowników {okres}` jest dostępny.

### Kroki

Plik zbiorczy wynika z okresu, więc go nie szukasz: Centrum bierze
`Rozliczenie {okres} - zbiorcze.xlsx` z Folderu okresu w folderze okresów.

1. Uzupełnij Plik zbiorczy w Excelu, zapisz go i zamknij (Gotowość). Centrum
   nie sprawdza, czy skończyłeś: to Ty decydujesz, kiedy plik jest gotowy.
2. Na stronie `Okresy` okres ma Status `Plik zbiorczy przygotowany`. Droga
   okresu na karcie `Następny krok` ma cztery kroki: Plik zbiorczy,
   Uzupełnienie w Excelu, Wycena w efenix i Rozliczenia pracowników. Przed
   Wyceną w efenix tego okresu karta pokazuje `Uzupełnij plik zbiorczy`, a
   dopóki ostatnia Wycena nie skończyła się wynikiem OK, `Wyceń w efenix`.
   `Utwórz rozliczenia pracowników` jest obok w
   wierszu okresu w Tablicy okresów: rozliczenia możesz utworzyć także bez
   Wyceny, na przykład gdy efenix nie działa. Po Wycenie z wynikiem OK karta
   pokazuje `Utwórz rozliczenia pracowników`; kliknij `Podgląd bez zapisu`.
   Dla innego tygodnia kliknij `Utwórz rozliczenia
   pracowników` w jego wierszu Tablicy okresów albo na stronie `Uruchomienia`
   wybierz kafelek `Przebieg rozliczeń` i okres z listy `Okres`. Lista ma tylko
   okresy ze Statusem `Plik zbiorczy przygotowany`.
3. Podgląd bez zapisu niczego nie tworzy. Pokazuje liczby `Wiersze danych`,
   `Planowane szablony` i `Puste szablony` oraz zwijany `Plan plików`: nazwę
   pliku każdego Wykonawcy z liczbą wierszy (`Pusty skoroszyt`, gdy Wykonawca
   nie ma wierszy).
4. Kliknij `Uruchom` i potwierdź w okienku `Uruchomić z zapisem?`. To kliknięcie
   jest potwierdzeniem Gotowości, więc zrób je dopiero po zamknięciu Pliku
   zbiorczego w Excelu. Okienko wymienia wiersze, w których nadal nie ma żadnej
   ilości, np. `3 wiersze bez ilości: 118, 203, 244`. Możesz mimo to uruchomić,
   jeśli te wiersze naprawdę zostają na zero.
5. W trakcie widać etapy, liczniki (`Wiersze danych`, `Zapisane szablony`,
   `Puste szablony`, `Problemy`) i pasek `Szablony
   pracowników` z bieżącym Wykonawcą i liczbą, np. `2 z 7`. Zamknięcie Centrum
   rozliczeń jest wtedy zablokowane.
6. Wynik `Rozliczenia pracowników gotowe` oznacza, że cały folder
   `Rozliczenie pracowników {okres}` powstał naraz. Pokazuje liczby `Zapisane
   szablony` i `Puste szablony`. Przycisk `Folder okresu`
   otwiera folder, a na stronie `Okresy` okres ma Status `Rozliczenia
   pracowników gotowe`. Otwórz pliki pracowników i sprawdź ich zawartość.
7. Wiersze w pliku pracownika wyglądają jak w Pliku zbiorczym: mają te same
   kolory wypełnienia, kolory czcionki, pogrubienia i kursywy. Krój i rozmiar
   czcionki, format liczb i obramowania są jak we Wzorcu rozliczenia
   pracownika.

Wynik z żółtym znakiem `Podgląd wymaga sprawdzenia · nic nie zapisano` to nie
sukces: pod nim są problemy w Pliku zbiorczym, każdy w trzech częściach. Popraw
je, zapisz i zamknij Plik zbiorczy i kliknij `Uruchom ponownie`. Zapis
(`Uruchom`) z takimi problemami zatrzyma się bez tworzenia plików.

Zatrzymanie pokazuje od razu trzy części komunikatu: co się stało (tytuł),
gdzie (pinezka) i co zrobić (klucz). Komunikaty są w tabeli niżej.

### Komunikat w Centrum rozliczeń → co zrobić

Po każdym zatrzymaniu nie powstał Folder rozliczeń pracowników. Wyjątkiem jest
komunikat o niepokazanym podsumowaniu: wtedy rozliczenia pracowników już są.
Jeśli komunikat mówi, że został folder tymczasowy, najpierw usuń z Folderu
okresu każdy folder, którego nazwa zaczyna się tak, jak podaje komunikat
(kropką, z `.staging-` na końcu). To nie są Foldery rozliczeń pracowników.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znaleziono Pliku zbiorczego tego okresu” | Sprawdź, czy Plik zbiorczy leży w Folderze okresu pod nazwą `Rozliczenie {okres} - zbiorcze.xlsx`. Jeśli okresu nie przygotowano, najpierw przygotuj plik zbiorczy. |
| „Plik zbiorczy jest otwarty w Excelu” | Zapisz i zamknij Plik zbiorczy, potem kliknij `Uruchom ponownie`. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z Folderu okresu pozostawiony plik `~$` z nazwą Pliku zbiorczego. |
| „Nie można teraz odczytać Pliku zbiorczego” | Nie poprawiaj Pliku zbiorczego. Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy plik otwiera się w Excelu. Zamknij go i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Plik zbiorczy nie nadaje się do Przebiegu rozliczeń” | Dalsza część komunikatu mówi, co jest nie tak (np. plik nie otwiera się w Excelu albo nie ma nagłówka WYKONAWCA). Popraw Plik zbiorczy, zapisz go, zamknij i uruchom ponownie. |
| „Folder rozliczeń pracowników tego okresu już istnieje” | Rozliczenia pracowników tego okresu już są; narzędzie ich nie nadpisze. Sprawdź, czy wybrano właściwy okres. Żeby utworzyć je od nowa, najpierw przenieś Folder rozliczeń pracowników poza Folder okresu. |
| „Nie można teraz odczytać konfiguracji wykonawców” | Nie poprawiaj konfiguracji wykonawców. Przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać konfiguracji wykonawców” | Przekaż komunikat osobie utrzymującej narzędzie. Ta sama konfiguracja jest potrzebna w Przygotowaniu pliku zbiorczego. |
| „Nie można użyć Wzorca rozliczenia pracownika” | Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania i uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat o otwartym Wzorcu wraca, usuń z folderu `config` pozostawiony plik `~$Wzorzec rozliczenia pracownika.xlsx`. Jeśli komunikat prosi o zmianę nazwy `placeholder.xlsx`, zrób to jak w części „Gdy pojawi się problem” niżej. W innym wypadku przekaż komunikat osobie utrzymującej narzędzie. |
| „spoza konfiguracji wykonawców” | Komunikat podaje każdy taki identyfikator WYKONAWCA. Popraw WYKONAWCĘ w kolumnie H albo poproś osobę utrzymującą narzędzie o dopisanie Wykonawcy. Zapisz, zamknij i uruchom ponownie. |
| „Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ” | Uruchom `Podgląd bez zapisu`: problemy pokażą numery wierszy. Wpisz w nich WYKONAWCĘ w kolumnie H, zapisz, zamknij i uruchom ponownie. |
| „Nieznany identyfikator WYKONAWCA” | Problem z podglądu (wynik wymaga sprawdzenia), osobny dla każdego identyfikatora, który podaje. Popraw ten identyfikator w kolumnie H albo poproś o dopisanie Wykonawcy do konfiguracji wykonawców. |
| „ma dane, ale nie ma wykonawcy w kolumnie H” | Problem z podglądu (wynik wymaga sprawdzenia). Wpisz WYKONAWCĘ we wskazanym wierszu albo wyczyść wiersz, jeśli jest zbędny. |
| „Nie udało się przygotować skoroszytu pracownika” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można utworzyć skoroszytów z Wzorca rozliczenia pracownika” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można opublikować gotowego Folderu rozliczeń pracowników” | Jeśli komunikat prosi o usunięcie folderów tymczasowych, usuń je z Folderu okresu; gdy się nie dają, odczekaj chwilę. Sprawdź, czy Folder okresu jest dostępny, i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można przygotować Folderu rozliczeń pracowników” | Sprawdź, czy Folder okresu jest dostępny, i kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Wystąpił nieoczekiwany błąd” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Rozliczenia pracowników powstały, ale nie udało się pokazać podsumowania” | Nie uruchamiaj ponownie: folder rozliczeń pracowników już jest. Sprawdź Folder okresu i przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się pokazać planu” | Nic nie zapisano. Przekaż komunikat osobie utrzymującej narzędzie. |

### Gdy pojawi się problem

- Jeśli plik jest otwarty, zamknij go i uruchom proces ponownie.
- Jeśli narzędzie napisze, że folder tygodnia jest w więcej niż jednym folderze miesiąca, zostaw go tylko w jednym miesiącu: drugi usuń albo zmień mu nazwę. Uruchom proces ponownie.
- Jeśli pojawi się komunikat „Nie znaleziono Wzorca rozliczenia pracownika” z prośbą o zmianę nazwy pliku `placeholder.xlsx`, zmień w folderze `config` narzędzia nazwę tego pliku na `Wzorzec rozliczenia pracownika.xlsx` i uruchom proces ponownie. Bez tej prośby przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się komunikat „Nie można odczytać Pliku zbiorczego”, sprawdź, czy ten plik otwiera się w Excelu i jest zapisany jako `.xlsx`. Zamknij go i uruchom proces ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie.
- Jeśli pojawi się informacja o braku szablonu, nie twórz pliku ręcznie z innego pracownika. Przekaż tę informację osobie utrzymującej narzędzie.
- Jeśli plik pracownika ma już dane, narzędzie go nie nadpisze.
