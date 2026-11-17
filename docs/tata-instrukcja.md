# Instrukcja dla taty

Co tydzień są dwa kroki, zawsze w tej kolejności:

1. **Przygotowanie pliku zbiorczego**: z Rejestru zleceń powstają Rozliczenie
   wewnętrzne i Plik zbiorczy okresu.
2. **Przebieg rozliczeń**: z Pliku zbiorczego powstają rozliczenia
   pracowników.

Do tego dochodzą dwa procesy, które też uruchamiasz w Centrum rozliczeń:
codziennie Uporządkowanie INTERMAX zleceń dnia wklejonych do INTERMAX, a
między krokiem 1 i 2, po Uzupełnieniu pliku zbiorczego, Wycena w efenix.

Wszystko robisz w Centrum rozliczeń, które otwierasz skrótem na pulpicie:

| Co chcesz zrobić | Gdzie w Centrum rozliczeń |
|---|---|
| Zobaczyć Status okresu każdego tygodnia | Strona `Okresy` |
| Otworzyć Plik zbiorczy, Rozliczenie wewnętrzne albo Folder okresu | Jedno kliknięcie w wierszu okresu |
| Uporządkować zlecenia dnia wklejone do INTERMAX | Strona `Uruchomienia`, karta `Uporządkowanie INTERMAX` (niżej, „Uporządkowanie INTERMAX”) |
| Przygotować plik zbiorczy | Strona `Uruchomienia`, proces `Przygotowanie pliku zbiorczego` |
| Wycenić zlecenia okresu w efenix | Strona `Uruchomienia`, proces `Wycena w efenix` (niżej, „Wycena w efenix”) |
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

   Przypomnienia o raporcie włączasz i wyłączasz w oknie `Ustawienia`, w
   sekcji `Przypomnienia`. Tam ustawiasz też pory, godzinę pierwszego
   przypomnienia, pierwsze zdanie i stopkę maila; podgląd pod spodem pokazuje
   mail tak, jak dostanie go Wykonawca. Zmiana działa od następnej minuty.

Osoba utrzymująca narzędzie umieszcza w folderze `config` narzędzia trzy
wzorce: `Wzorzec rozliczenia wewnętrznego.xlsx`, `Wzorzec pliku zbiorczego.xlsx`
i `Wzorzec rozliczenia pracownika.xlsx`. Ten ostatni to pusty plik rozliczenia
pracownika bez nazwy wykonawcy (u Ciebie `Rozliczenie {okres} -.xlsx`); z niego
powstają pliki pracowników.
Nie zmieniaj ich i nie podmieniaj plikami z poprzedniego tygodnia.

W tym samym folderze `config` leży też Lista Wykonawców `wykonawcy.yaml`,
czyli lista Twoich pracowników z ich adresami. Ten plik jest tylko na Twoim
komputerze, nie w internecie. Plik `wykonawcy.example.yaml` obok to przykład z
wymyślonymi nazwiskami; narzędzie z niego nie korzysta. Listę Wykonawców
prowadzisz sam w oknie `Ustawienia`, w sekcji `Wykonawcy`: `Dodaj Wykonawcę`
dodaje pracownika z loginem z kolumny `WYKONAWCA`, nazwą w jego Rozliczeniu
pracownika i adresami maili, a `Edytuj` zmienia nazwę, adresy albo dopisuje
drugi login; zmiana zapisuje się przyciskiem `Zapisz`. Przełącznik
`Przypomnienia` wyłącza przypomnienia jednemu pracownikowi, np. na urlop.
Pracownika, który ma zlecenia w Rejestrze zleceń albo w Pliku zbiorczym
któregoś tygodnia, nie da się usunąć: gdy odchodzi, kliknij
`Oznacz jako nieaktywnego`, a jego tygodnie dalej się rozliczą.
Pod listą sekcja podpowiada loginy z kolumny `WYKONAWCA` zleceń bieżącego
tygodnia i 4 poprzednich, których nie ma na liście: `Dodaj Wykonawcę` przy
loginie otwiera formularz z wpisanym loginem. Gdy raport przyjdzie z adresu
spoza listy, widok `Raporty` pokazuje ten adres z przyciskiem
`Przypisz do Wykonawcy…`: wybierz pracownika, a adres dopisze się od razu i
następne `Wpisz raporty z maili` wpisze ten raport.
Gdy pracownik w zleceniu z `tak` napisze coś poza Kodami czynności (Błąd opisu),
`Wpisz raporty z maili` wpisuje to zlecenie jak każde, a widok `Raporty`
pokazuje przy jego dniu problem z powodem. Taki raport jest przysłany, więc
pracownik nie dostaje za ten dzień Przypomnienia o raporcie: przypomnienie idzie
tylko za dzień, za który nie przysłał żadnego raportu.

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
| „Lista Wykonawców ma złe ustawienie” | Otwórz `Ustawienia`, sekcję `Wykonawcy`, popraw pole, które wskazuje komunikat, i uruchom ponownie. |
| „Uruchomienie użyło ostatniej dobrej Listy Wykonawców” | Ostrzeżenie: proces zadziałał na liście sprzed zepsucia pliku. Otwórz `Ustawienia`, sekcję `Wykonawcy`, i popraw pole, które wskazuje komunikat, zanim uruchomisz następny proces. |
| „Nie można teraz odczytać Listy Wykonawców” | Zamknij program, który może trzymać plik (np. antywirus), i uruchom ponownie. Gdy komunikat wraca, przekaż go osobie utrzymującej narzędzie. |

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

## Uporządkowanie INTERMAX

INTERMAX to Rejestr zleceń `ZLECENIA INTERMAX OD 08_11_2021.xlsx`.
Uporządkowanie INTERMAX robi za Ciebie to, co dotąd robiłeś ręcznie ze
zleceniami dnia wklejonymi z aplikacji firmowej: dzieli je na Wykonawców,
układa po godzinie i nadaje im wygląd reszty INTERMAX. Porządkuje jeden dzień,
nie okres.

### Kiedy uruchomić

- Ty albo pracownik wkleiliście z aplikacji firmowej zlecenia **jednego dnia**
  na dół arkusza zleceń INTERMAX, pod ostatni uporządkowany dzień.
- Ten dzień nie jest jeszcze uporządkowany: na karcie nie ma przy nim znaku.
- INTERMAX jest zapisany i **zamknięty** w Excelu. Jeśli zlecenia wkleił
  pracownik na swoim komputerze, poczekaj, aż OneDrive skończy synchronizację.

Narzędzie zmienia w INTERMAX tylko wklejone zlecenia i widok po otwarciu.
Wiersze nad nimi zostają bez zmian. Przed każdym zapisem narzędzie robi Kopię
INTERMAX, czyli stan INTERMAX sprzed zmiany, na Twoim komputerze poza OneDrive.

### Kroki

1. Na stronie `Uruchomienia` pod wyborem procesu jest karta
   `Uporządkowanie INTERMAX`. Pokazuje INTERMAX wskazany w oknie `Ustawienia`,
   w sekcji `Foldery`, i rząd dni: dziś, 6 dni przed nim i każdy późniejszy
   dzień uporządkowany. Dzień uporządkowany ma znak, nieuporządkowany pusty
   krąg, a dziś obwódkę.
2. Zapisz i zamknij INTERMAX w Excelu. Dopóki jest otwarty, przycisk jest
   nieaktywny, a karta pisze, że INTERMAX jest otwarty w Excelu.
3. Kliknij `Uporządkuj INTERMAX`. Nie ma podglądu bez zapisu ani okienka
   potwierdzenia: narzędzie od razu porządkuje wklejone zlecenia.
4. Wynik `INTERMAX uporządkowany` pokazuje liczby `Zlecenia` i `Wykonawcy`,
   `Uporządkowany dzień` z liczbą zleceń i `Kopia sprzed zapisu` z nazwą Kopii
   INTERMAX. Przycisk `Otwórz INTERMAX` otwiera plik.

Zatrzymanie pokazuje od razu trzy części komunikatu: co się stało (tytuł),
gdzie (pinezka) i co zrobić (klucz). Komunikaty są w tabeli niżej. Po
poprawce kliknij `Uruchom ponownie`.

### Co sprawdzić po zakończeniu

- INTERMAX otwiera się na dzisiejszym dniu, a gdy dziś nie ma zleceń, na
  ostatnim wcześniejszym dniu ze zleceniami.
- Zlecenia dnia są podzielone na Wykonawców w kolejności alfabetycznej,
  oddzielonych jednym pustym wierszem, a u każdego Wykonawcy ułożone od
  najwcześniejszej godziny do najpóźniejszej.
- Nowy dzień stoi jeden pusty wiersz pod żółtym wierszem, którym oddzielasz
  dni. Gdy żółtego wiersza nie ma, stoi 10 pustych wierszy pod ostatnim
  uporządkowanym zleceniem.
- Wiersze mają wygląd reszty INTERMAX, z cienką ramką i pogrubionym tylko
  `WYKONAWCA`. Kolumny z aplikacji za `UWAGI` zniknęły.
- Kolory operatora: `CZYNNOŚCI` i `NUMER UMOWY` są zielone przy T-Mobile,
  pomarańczowe przy Orange, jasnoniebieskie przy innych operatorach, a przy
  Netii `CZYNNOŚCI` jest ciemniejsza niebieska. INEA i zlecenie bez operatora
  zostają bez koloru. Usterka zamiast tego ma tylko różowe `URZĄDZENIA`, bez
  koloru w `CZYNNOŚCI` i `NUMER UMOWY`.
- Zlecenia `Instalacja Hurt` mają wpisane `URZĄDZENIA` i dopisaną czynność w
  `CZYNNOŚCI`, np. Orange `gniazdo` i ` - akt pętli LLU`. Zlecenie Orange,
  które okazało się BSA, poprawiasz ręcznie na `nokia` i ` - akt pętli BSA`.
- Na karcie dzień ma znak.

Potem Ty i pracownicy uzupełniacie dzień ręcznie, tak jak dotąd. Zlecenia
dopisane później do uporządkowanego dnia wpisujesz ręcznie: narzędzie nie
porządkuje tego samego dnia drugi raz.

Jeśli Uporządkowanie zrobiło coś nie tak, otwórz okno `Ustawienia`, sekcję
`Kopie INTERMAX`. Lista ma 10 najnowszych Kopii INTERMAX z datą i godziną.
Kliknij `Przywróć` przy kopii sprzed uporządkowania i potwierdź przyciskiem
`Przywróć tę kopię`. Wszystkie zmiany w INTERMAX późniejsze od tej kopii
znikną, także te, które wpisaliście ręcznie. Przed przywróceniem narzędzie
robi Kopię obecnego INTERMAX, więc przywrócenie też da się cofnąć tak samo.

### Uporządkowanie INTERMAX → co zrobić

Po każdym zatrzymaniu INTERMAX został bez zmian, więc po poprawce wystarczy
uruchomić ponownie. Wyjątki to komunikaty o starszych Kopiach INTERMAX i o
niepokazanym podsumowaniu: wtedy INTERMAX jest już uporządkowany.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znaleziono INTERMAX” | W oknie `Ustawienia`, w sekcji `Foldery`, wskaż właściwy plik INTERMAX i uruchom ponownie. |
| „INTERMAX jest otwarty w Excelu” | Zapisz i zamknij INTERMAX, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z folderu INTERMAX pozostawiony plik `~$ZLECENIA INTERMAX OD 08_11_2021.xlsx`. |
| „Nie można teraz odczytać INTERMAX” | Nie poprawiaj INTERMAX. Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy INTERMAX otwiera się w Excelu. Zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie można odczytać INTERMAX jako skoroszytu Excela” | Otwórz INTERMAX w Excelu. Jeśli się otwiera, zapisz go, zamknij i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „OneDrive jeszcze synchronizuje INTERMAX” | Poczekaj, aż OneDrive skończy synchronizację, potem uruchom ponownie. |
| „W INTERMAX nie ma arkusza zleceń” | Sprawdź, czy w `Ustawieniach` wskazano INTERMAX i czy wiersz 1 arkusza zleceń ma nagłówki od `AKCJE` do `UWAGI`. Uruchom ponownie. |
| „więcej niż raz, więc nie wiadomo, z której kolumny brać dane” | Zostaw wymieniony nagłówek tylko w jednej kolumnie: zmień nazwę drugiej kolumny albo ją usuń. Zapisz i zamknij INTERMAX, uruchom ponownie. |
| „nie ma wklejonych zleceń do uporządkowania” | Wklej zlecenia dnia z aplikacji firmowej na dół arkusza zleceń, zapisz i zamknij INTERMAX i uruchom ponownie. |
| „Wklejone zlecenia są w więcej niż jednym arkuszu zleceń” | Zostaw wklejone zlecenia tylko na dole jednego arkusza zleceń, a z pozostałych arkuszy wymienionych w `Gdzie` je usuń. Zapisz i zamknij INTERMAX, uruchom ponownie. |
| „wygląda jak wklejone zlecenie, ale stoi nad uporządkowanym wierszem” | Przenieś wklejone zlecenia na dół arkusza zleceń, pod ostatni uporządkowany wiersz. Jeśli wskazany wiersz jest już uporządkowany, nadaj mu taką czcionkę, jaką podaje komunikat. Zapisz i zamknij INTERMAX, uruchom ponownie. |
| „nie ma daty z godziną w kolumnie” | Wpisz datę z godziną w komórce wskazanej w `Gdzie`, zapisz i zamknij INTERMAX i uruchom ponownie. |
| „nie ma Wykonawcy w kolumnie” | Wpisz Wykonawcę w komórce wskazanej w `Gdzie`, zapisz i zamknij INTERMAX i uruchom ponownie. |
| „Wklejone zlecenia są z więcej niż jednego dnia” | Zostaw na dole arkusza zleceń zlecenia jednego dnia, a pozostałe usuń. Zapisz i zamknij INTERMAX, uruchom ponownie. Następny dzień wklej i uporządkuj osobno. |
| „jest już uporządkowany” | Ten dzień był już uporządkowany, więc narzędzie nie porządkuje go drugi raz. Wklejone wiersze wskazane w `Gdzie` usuń, a nowe zlecenia na ten dzień dopisz ręcznie. |
| „mają układ, którego narzędzie nie porządkuje” | Przekaż komunikat osobie utrzymującej narzędzie. Do czasu poprawki uporządkuj ten dzień ręcznie. |
| „Nie udało się zrobić Kopii INTERMAX” | Sprawdź, czy na dysku jest wolne miejsce, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się zapisać INTERMAX” | Sprawdź, czy na dysku jest wolne miejsce, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Sprawdzenie zapisu wykazało różnicę” | Narzędzie odrzuciło własny zapis, więc INTERMAX jest taki jak przedtem. Przekaż komunikat osobie utrzymującej narzędzie. |
| „nie udało się usunąć starszych Kopii INTERMAX” | Ostrzeżenie pod wynikiem: INTERMAX jest uporządkowany. Nie musisz nic robić teraz. Jeśli któraś Kopia INTERMAX jest otwarta w Excelu, zamknij ją. Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie. |
| „Wystąpił nieoczekiwany błąd” | Kliknij `Uruchom ponownie`. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „INTERMAX został uporządkowany, ale nie udało się pokazać podsumowania” | Nie uruchamiaj ponownie: INTERMAX jest już uporządkowany. Sprawdź INTERMAX i przekaż komunikat osobie utrzymującej narzędzie. |

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
  wymaga uwagi, zwykle kolumny z opisu technika. Każde ostrzeżenie jest
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
| „spoza Listy Wykonawców” | Literówkę w `WYKONAWCA` popraw we wskazanych wierszach Rejestru. Nowego Wykonawcę dodaj w `Ustawieniach`, w Liście Wykonawców (tej samej co w Przebiegu rozliczeń). |
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
Pliku zbiorczego, a nie Rejestru zleceń. Wynik zapisu to zawsze `Plik zbiorczy
przygotowany · wymaga sprawdzenia`: pliki powstały, a Ty uzupełniasz Plik
zbiorczy przed Przebiegiem rozliczeń. Wiersz, którego `CZYNNOŚCI ZREALIZOWANE`
to same Kody czynności (poza `tak`, `nie` i znakami interpunkcji), wypełniła
Legenda czynności, więc na Ciebie nie czeka. Każde inne słowo, kod z liczbą
spoza przedziałów albo dwa kody w jednej kolumnie to Błąd opisu: wtedy legenda
nic w wierszu nie wpisuje, a wiersz czeka na Ciebie.

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Rejestr zleceń może nie mieć jeszcze wszystkich zleceń tego okresu” | Sprawdź `Zlecenia na dzień`. Jeśli brakuje zleceń z końca tygodnia, kliknij `Przerwij bez zapisu`, uzupełnij eksport w Rejestrze, zapisz go, zamknij i uruchom ponownie. Jeśli w te dni naprawdę nie było zleceń, kliknij `Kontynuuj`. |
| „Narzędzie nie zna urządzenia z kolumny URZĄDZENIA” | W tych wierszach narzędzie wpisało tylko V, T i N. Uzupełnij pozostałe ilości ręcznie. Jeśli to nowe urządzenie, które będzie wracać, powiedz o nim osobie utrzymującej narzędzie. |
| „rozlicza się z opisu technika” | Prewencja, niedostępność usług albo puste `URZĄDZENIA`: Reguły ilości nie wpisały w tych wierszach żadnych ilości, a Legenda czynności najwyżej to, co wynika z kodów. Wpisz je według `CZYNNOŚCI ZREALIZOWANE`. |
| „nie jest w tych wierszach z samych Kodów czynności” | Pracownik napisał w `CZYNNOŚCI ZREALIZOWANE` coś poza Kodami czynności: zwykły opis, kod ze spacją w środku (`inst 20m`), kod z liczbą spoza przedziałów (np. `instutp40m`) albo dwa kody w jednej kolumnie (np. `instmdik` i `inst20m` w Y). Legenda nic w tych wierszach nie wpisała. Wpisz ilości według opisu technika. Kody czynności i ich zapisy zmienisz w Ustawieniach, w sekcji Legenda czynności. |
| „Ilości z opisu technika (CZYNNOŚCI ZREALIZOWANE)” | Mówi, w ilu wierszach legenda wpisała ilości i ile wierszy zostało Tobie. W tych wierszach uzupełnij ilości w kolumnach Y, AB, AD, AJ, AK, AL i AM według `CZYNNOŚCI ZREALIZOWANE`; to, co wynika z kodów, jest już wpisane. Gdy nic nie zostało, tego ostrzeżenia nie ma. |
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

## Reguły ilości

Reguły ilości zmieniasz sam w oknie `Ustawienia`, w sekcji `Reguły ilości`.
Działają od następnego Przygotowania pliku zbiorczego, a gotowe Pliki zbiorcze
zostają bez zmian.

1. Kliknij `Dodaj regułę` albo ołówek przy regule, którą chcesz zmienić.
2. Wybierz, dla których zleceń reguła działa, dodaj warunki (`Gdy` albo
   `Ale nie gdy`) i działanie, np. `Wpisz w kolumnę` z kolumną po nazwie z
   cennika.
3. Pod spodem `Podgląd na ostatnich okresach` pokazuje, ile wierszy ostatnich
   rozliczonych Plików zbiorczych się zmieni i w ilu będzie tak, jak wpisałeś,
   a niżej wiersze, w których reguła da inaczej niż Ty.
4. Kliknij `Zapisz`, także gdy są różnice. Złą regułę Centrum odrzuci jednym
   zdaniem przy polu, które trzeba poprawić.

Nad regułami stoi lista `Tu wpisałeś inaczej niż reguła`: wiersze ostatnich
rozliczonych Plików zbiorczych, w których wpisałeś w kolumnie co innego niż
reguła. To te same różnice, które Maks dostaje w Kontroli ilości.

- `Popraw regułę` otwiera nową regułę z warunkami z `URZĄDZENIA` tego wiersza.
  Nic się nie zapisuje, dopóki nie klikniesz `Zapisz`, więc najpierw sprawdź
  podgląd.
- `To był wyjątek` mówi, że w tym zleceniu wpisałeś dobrze. Ta różnica już nie
  wraca na listę; w sekcji `Historia` cofniesz to przyciskiem `Cofnij`.

Zmianę reguły widać w sekcji `Historia` jako zdanie reguły przed i po, a
`Cofnij` przywraca poprzednie reguły. Regułę usuwasz przyciskiem
`Usuń regułę` w tym samym oknie.

### Lista Urządzeń

Sekcja `Urządzenia` pokazuje składniki URZĄDZENIA, które znają Reguły ilości.
Gdy INTERMAX zapisze ten sam składnik inaczej, nie trzeba nowej reguły:

1. Kliknij ołówek przy składniku, potem `Dodaj zapis` i wpisz nowy zapis.
2. Kliknij `Zapisz`. Zapis działa od następnego Przygotowania pliku zbiorczego.

Nowy składnik dodajesz przyciskiem `Dodaj składnik`, z grupą router, TV albo
extender, gdy ją ma. Pod listą Centrum podpowiada zapisy z ostatnich okresów,
których lista nie zna; `Dodaj` przy podpowiedzi dodaje go jako nowy składnik
albo inny zapis składnika z listy. Jeden zapis należy do jednego składnika, a
składnika, którego potrzebuje reguła, Centrum nie usunie: poda zdanie tej reguły.

## Wycena w efenix

Wycena w efenix wpisuje za Ciebie w efenix wycenę zleceń z Pliku zbiorczego
okresu, w oknie efenix, w którym sam się logujesz. Narzędzie nie zna Twojego
hasła. Pomija Zlecenia ze zdjęciami i usterki: te wyceniasz sam, tak jak
dotąd. Zleceń, które w efenix są już „Rozliczone” albo „Do akceptacji”, nie
otwiera i niczego w nich nie zmienia.

W każdym zleceniu narzędzie:

1. ustawia datę wykonania z `DATA`, gdy zlecenie w efenix jej nie ma;
2. do zlecenia bez żadnej ilości ładuje Wycenę Emmetta;
3. w każdej pozycji, w której efenix ma mniej niż Plik zbiorczy, wpisuje
   ilość z pliku. Ilości w efenix nigdy nie obniża ani nie czyści.

Zlecenie jest gotowe, gdy kwota w efenix jest równa `Kwota` (AU) w Pliku
zbiorczym. Narzędzie nigdy nie anuluje zlecenia.

### Kiedy uruchomić

- Plik zbiorczy okresu jest uzupełniony, zapisany w Excelu i **zamknięty**.
  Zapis w Excelu liczy kwoty w kolumnie AU, z którymi narzędzie porównuje
  wycenę.
- Na komputerze jest Google Chrome i działa internet.
- Dzień z `DATA` nie jest starszy niż pierwszy dzień poprzedniego miesiąca:
  starszej daty wykonania efenix nie przyjmuje.
- Masz czas: narzędzie pracuje w tempie człowieka, ok. 20 sekund na każde
  zlecenie, w którym coś wpisuje w efenix. Zlecenia już gotowe sprawdza bez
  przerw.

Wycena w efenix nie zmienia Statusu okresu. Rozliczenia pracowników możesz
utworzyć także bez niej, na przykład gdy efenix nie działa.

### Kroki

1. Na stronie `Okresy` kliknij na karcie `Następny krok` przycisk
   `Wyceń w efenix`. Otworzy się strona `Uruchomienia` z Wyceną w efenix i tym
   okresem. Dla innego tygodnia wybierz na stronie `Uruchomienia` kafelek
   `Wycena w efenix` i okres z listy `Okres`. Lista ma okresy z Plikiem
   zbiorczym.
2. Wycena w efenix nie ma podglądu bez zapisu. Wybierz tryb jednym z dwóch
   przycisków. Centrum nie pamięta trybu, więc wybierasz go za każdym razem:
   - `Uzupełnij bez zapisu`: zielony „Zapisz” w efenix klikasz sam. Gotowe
     zlecenia dostają w Pliku zbiorczym Znacznik efenix.
   - `Uzupełnij i zapisz`: zielony „Zapisz” przy gotowych zleceniach klika
     Centrum, czyli przekazuje je do akceptacji. Takie zlecenia dostają
     Znacznik przekazania. Przekazania nie da się łatwo cofnąć.

   Oba tryby wpisują wycenę w efenix, więc `Uzupełnij bez zapisu` to nie
   podgląd. Błędów zleceń i Ostrzeżeń Emmetta narzędzie nie przekazuje w
   żadnym trybie.
3. Potwierdź w okienku `Uzupełnić bez zapisu?` albo `Uzupełnić i zapisać?`.
4. Centrum otworzy okno Google Chrome z efenix, a karta pokaże krok
   `Zaloguj się w oknie efenix`. Jeśli okno pokazuje stronę logowania,
   zaloguj się w nim. Okno czeka na zalogowanie 15 minut.
5. Narzędzie idzie przez zlecenia po kolei: Wykonawcy alfabetycznie, a u
   każdego od najstarszej `DATA`. Karta pokazuje bieżącego Wykonawcę i liczbę
   sprawdzonych zleceń ze wszystkich. Zostaw okno efenix otwarte do końca.
   Zamknięcie Centrum rozliczeń jest wtedy zablokowane.
6. Na końcu narzędzie raz zapisuje Plik zbiorczy: komórka `ADRES` gotowego
   zlecenia dostaje Znacznik efenix (jasny fiolet), a zlecenia przekazanego do
   akceptacji Znacznik przekazania (ciemniejszy fiolet). Dlatego Plik
   zbiorczy musi zostać zamknięty do końca Wyceny.
7. Wynik `Wycena w efenix gotowa` oznacza, że żadne zlecenie nie zostało dla
   Ciebie: każde jest gotowe, przekazane albo rozliczone. Wynik
   `Wycena w efenix gotowa · wymaga sprawdzenia` oznacza, że są błędy zleceń
   albo Ostrzeżenia Emmetta. Karta pokazuje liczby `Zlecenia w zakresie`,
   `Gotowe do przekazania`, `Przekazane do akceptacji`, `Rozliczone`,
   `Błędy zleceń` i `Ostrzeżenia Emmetta`, a w grupie `Pominięte`
   `Ze zdjęciami`, `Usterki` i `Nieznalezione w efenix`. Niżej są listy
   zleceń z numerem wiersza Pliku zbiorczego i Wykonawcą, najpierw te, które
   zostały dla Ciebie.

Po Wycenie z wynikiem OK karta `Następny krok` pokazuje
`Utwórz rozliczenia pracowników` (niżej, „Przebieg rozliczeń”).

### Co sprawdzić po zakończeniu

- Każde zlecenie z list `Błędy zleceń` i `Ostrzeżenia Emmetta`: wiersz Pliku
  zbiorczego i jego komunikat. Co zrobić, mówi tabela niżej. Takie zlecenia
  nie mają Znacznika efenix i nie są przekazane.
- Po trybie `Uzupełnij bez zapisu` przekaż gotowe zlecenia do akceptacji sam
  zielonym „Zapisz” w efenix albo uruchom Wycenę jeszcze raz przyciskiem
  `Uzupełnij i zapisz`: gotowe zlecenia narzędzie tylko sprawdzi i przekaże.
- W Pliku zbiorczym gotowe zlecenia mają jasnofioletowy `ADRES`, a przekazane
  ciemniejszy fiolet.
- Zlecenia ze zdjęciami i usterki wycenisz sam w efenix.
- Po wyniku możesz zamknąć okno efenix.

Ponowne uruchomienie jest bezpieczne: gotowe zlecenia narzędzie tylko
sprawdza, a resztę wycenia dalej.

### Wycena w efenix → co zrobić

Są dwa rodzaje komunikatów:

- **Zatrzymanie** kończy całą Wycenę. Pierwsza część mówi, czy przed
  zatrzymaniem narzędzie zmieniło coś w efenix: „W efenix nic się nie
  zmieniło.” albo „Wycena zleceń sprzed zatrzymania została w efenix.” Po
  poprawce kliknij `Uruchom ponownie`: gotowe zlecenia narzędzie tylko
  sprawdzi, a resztę wyceni dalej.
- **Błąd zlecenia** albo **Ostrzeżenie Emmetta** dotyczy jednego zlecenia,
  które zostało dla Ciebie. Wycena idzie dalej, a zlecenie jest na liście pod
  wynikiem. `Gdzie` podaje wiersz Pliku zbiorczego.

#### Zatrzymania

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Nie znaleziono Pliku zbiorczego” | Sprawdź, czy Plik zbiorczy okresu leży w Folderze okresu pod nazwą `Rozliczenie {okres} - zbiorcze.xlsx`, i uruchom ponownie. |
| „Plik zbiorczy jest otwarty w Excelu, a Wycena w efenix oznacza” | Zapisz i zamknij Plik zbiorczy w Excelu, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, usuń z Folderu okresu pozostawiony plik `~$` z nazwą Pliku zbiorczego. |
| „Nie można teraz odczytać Pliku zbiorczego” | Nie poprawiaj Pliku zbiorczego. Poczekaj, aż OneDrive skończy synchronizację, i sprawdź, czy plik otwiera się w Excelu. Zamknij go i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Plik zbiorczy jest uszkodzony albo nie ma układu Pliku zbiorczego” | Otwórz Plik zbiorczy w Excelu i sprawdź, czy otwiera się poprawnie. Jeśli tak, przekaż komunikat osobie utrzymującej narzędzie. |
| „W Pliku zbiorczym brakuje nagłówków” | Przywróć wymienione nagłówki w wierszu 17 Pliku zbiorczego tak jak we Wzorcu pliku zbiorczego, zapisz plik i uruchom ponownie. |
| „nie ma kwot w kolumnie AU policzonych przez Excel” | Otwórz Plik zbiorczy w Excelu, zapisz go, zamknij i uruchom ponownie. |
| „Nie udało się otworzyć przeglądarki Google Chrome” | Zamknij okno efenix, jeśli zostało otwarte z poprzedniej Wyceny w efenix, i uruchom ponownie. Jeśli na komputerze nie ma Google Chrome albo błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „Nie udało się otworzyć efenix” | Sprawdź połączenie z internetem i czy efenix otwiera się w przeglądarce, potem uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „efenix wylogował i pokazał stronę logowania” | efenix Cię wylogował albo nie zalogowałeś się w ciągu 15 minut. Uruchom ponownie i zaloguj się w oknie efenix. |
| „Okno efenix zostało zamknięte” | Uruchom ponownie i zostaw okno efenix otwarte do końca Wyceny. |
| „Wycena w efenix się zatrzymała, Maks już wie” | Okno efenix nie dokończyło kroku, np. po zerwanym połączeniu z internetem albo gdy efenix działa wolno lub inaczej niż zwykle. Wycena zatrzymuje się wtedy od razu. Uruchom ponownie. Jeśli zatrzyma się znowu, wyceń pozostałe zlecenia w efenix sam albo poczekaj na poprawkę narzędzia, i przekaż komunikat osobie utrzymującej narzędzie. |
| „nie dostały Znacznika efenix, bo Plik zbiorczy jest otwarty w Excelu” | Wycena gotowych zleceń jest już w efenix, brakuje tylko Znaczników w pliku. Zapisz i zamknij Plik zbiorczy w Excelu, potem uruchom ponownie: narzędzie oznaczy je bez zmian w efenix. |
| „bo Plik zbiorczy zmienił się w trakcie Wyceny w efenix” | Wycena gotowych zleceń jest już w efenix. Nie zmieniaj Pliku zbiorczego w trakcie Wyceny. Zamknij go w Excelu i uruchom ponownie: narzędzie oznaczy gotowe zlecenia bez zmian w efenix. |
| „bo nie udało się zapisać Pliku zbiorczego” | Wycena gotowych zleceń jest już w efenix. Zamknij Plik zbiorczy w Excelu, poczekaj, aż OneDrive skończy synchronizację, i uruchom ponownie. Jeśli błąd wraca, przekaż komunikat osobie utrzymującej narzędzie. |
| „zatrzymała się przez nieoczekiwany błąd” | Część zleceń mogła zostać już wyceniona w efenix. Przekaż komunikat osobie utrzymującej narzędzie. |
| „skończyła się, ale nie udało się pokazać wyniku” | Wycena się skończyła, tylko karta nie pokazała wyniku. Przekaż komunikat osobie utrzymującej narzędzie. |

#### Błędy zleceń i Ostrzeżenia Emmetta

| Co się stało (fragment) | Co zrobić |
|---|---|
| „Wiersz nie ma numeru zlecenia w NUMER ZL.” | Uzupełnij `NUMER ZL.` w tym wierszu Pliku zbiorczego i uruchom ponownie albo wyceń zlecenie w efenix sam. |
| „Wiersz nie ma daty w DATA” | Uzupełnij `DATA` w tym wierszu Pliku zbiorczego i uruchom ponownie albo wyceń zlecenie w efenix sam. |
| „efenix nie zna zlecenia o numerze” | Sprawdź `NUMER ZL.` w Pliku zbiorczym i zlecenie w efenix. Takie zlecenia liczy też `Nieznalezione w efenix`. |
| „efenix ma kilka zleceń o numerze” | Sprawdź zlecenie w efenix i wyceń je sam. |
| „Zlecenie w efenix nie ma statusu” | Zlecenie w efenix nie jest „Do wyceny”, „Rozliczone” ani „Do akceptacji”. Sprawdź jego status w efenix. |
| „Realizator zlecenia w efenix jest inny” | Sprawdź zlecenie w efenix i wyceń je sam. Jeśli w Pliku zbiorczym jest zły `WYKONAWCA`, popraw go. |
| „Dane adresowe zlecenia w efenix są inne” | Sprawdź zlecenie w efenix i wyceń je sam. |
| „Data wykonania zlecenia w efenix różni się” | Sprawdź zlecenie w efenix i wyceń je sam. |
| „Dzień z DATA jest poza zakresem dat wykonania” | Sprawdź `DATA` w Pliku zbiorczym. Jeśli jest błędna, popraw ją i uruchom ponownie. Jeśli jest dobra, okres jest za stary dla efenix: ustaw datę wykonania i wyceń zlecenie w efenix sam. |
| „efenix nie zapisał daty wykonania” | Ustaw datę wykonania w efenix sam i uruchom ponownie. |
| „ilość w kolumnach, które nie mają pozycji w efenix” | Sprawdź zlecenie w efenix i wyceń je sam. |
| „nie jest liczbą całkowitą większą od 0” | Popraw ilość we wskazanych kolumnach Pliku zbiorczego i uruchom ponownie albo wyceń zlecenie w efenix sam. |
| „Strona zlecenia w efenix nie ma pozycji” | Sprawdź ilości we wskazanych kolumnach Pliku zbiorczego i pozycje zlecenia w efenix, a potem wyceń zlecenie w efenix sam. |
| „kwota w efenix to” | Ilości z pliku są już wpisane w efenix, a kwoty się różnią. Sprawdź wycenę w efenix i Plik zbiorczy, popraw tę, która jest błędna, i uruchom ponownie. |
| „efenix ma więcej niż Plik zbiorczy” | Ostrzeżenie Emmetta: w podanych pozycjach efenix ma więcej niż plik, a pozostałe ilości narzędzie wpisało. Jeśli rację ma efenix, popraw Plik zbiorczy i uruchom ponownie. Jeśli rację ma plik, zmniejsz tę ilość w efenix sam. |
| „efenix nie przyjął Przekazania do akceptacji” | Tylko w trybie `Uzupełnij i zapisz`. Wycena jest już w efenix, a komunikat mówi, czego efenix brakuje: zdjęć, długości przyłącza, wyceny albo daty wykonania. Uzupełnij to w efenix, a potem przekaż zlecenie do akceptacji sam albo uruchom ponownie przyciskiem `Uzupełnij i zapisz`. Gdy efenix pokazał informację, której narzędzie nie zna, sprawdź w efenix, czego brakuje, i przekaż zlecenie sam. |
| „efenix nie pokazuje go potem ze statusem” | Tylko w trybie `Uzupełnij i zapisz`. Sprawdź zlecenie w efenix i, jeśli nie jest przekazane, przekaż je do akceptacji sam. |

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
| „Nie można użyć Wzorca rozliczenia pracownika” | Jeśli Wzorzec jest otwarty w Excelu, zamknij go bez zapisywania i uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat o otwartym Wzorcu wraca, usuń z folderu `config` pozostawiony plik `~$Wzorzec rozliczenia pracownika.xlsx`. Jeśli komunikat prosi o zmianę nazwy `placeholder.xlsx`, zrób to jak w części „Gdy pojawi się problem” niżej. W innym wypadku przekaż komunikat osobie utrzymującej narzędzie. |
| „spoza Listy Wykonawców” | Komunikat podaje każdy taki identyfikator WYKONAWCA. Popraw WYKONAWCĘ w kolumnie H albo dodaj Wykonawcę w `Ustawieniach`, w Liście Wykonawców. Zapisz, zamknij i uruchom ponownie. |
| „Nie wszystkie Wiersze danych Pliku zbiorczego mają WYKONAWCĘ” | Uruchom `Podgląd bez zapisu`: problemy pokażą numery wierszy. Wpisz w nich WYKONAWCĘ w kolumnie H, zapisz, zamknij i uruchom ponownie. |
| „Nieznany identyfikator WYKONAWCA” | Problem z podglądu (wynik wymaga sprawdzenia), osobny dla każdego identyfikatora, który podaje. Popraw ten identyfikator w kolumnie H albo dodaj Wykonawcę w `Ustawieniach`, w Liście Wykonawców. |
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

## Wysyłka rozliczeń

Po Przebiegu rozliczeń otwórz w menu `Wysyłka rozliczeń`. Tygodnie z Rozliczeniami pracowników stoją jeden pod drugim,
najnowszy na górze. Tydzień, w którym coś czeka, ma kartę z pracownikami, ich adresami i stanem pliku; zaznaczeni są ci,
którym rozliczenie jeszcze nie poszło. Kliknij `Wyślij N rozliczeń`, obejrzyj maile w okienku (strzałkami przechodzisz
do następnego) i potwierdź: każdy pracownik dostaje osobny mail ze swoim plikiem, ze skrzynki raportów, na wszystkie
swoje adresy z Listy Wykonawców. Przy każdym pracowniku pojawia się zielony znacznik, gdy jego mail poszedł, a pasek
na górze karty rośnie. Gdy poszło wszystko, karta zwija się w jeden wiersz tygodnia.

- Przełącznik w prawym górnym rogu: `Do wysłania` pokazuje tylko tygodnie, w których coś czeka, `Wszystkie okresy`
  także wysłane. W wierszu tygodnia `kto i kiedy` pokazuje, komu i kiedy poszło.
- Temat i treść maila zmieniasz w oknie `Ustawienia`, w sekcji `Wysyłka rozliczeń` (link `Temat i treść` u góry
  strony); `{okres}` to dni tygodnia, a `{wykonawca}` imię i nazwisko pracownika. Stopka jest ta sama co w Przypomnieniach o raporcie.
- Plik, który już poszedł, drugi raz nie pójdzie. Gdy po wysłaniu poprawisz plik, tydzień pyta „… ma poprawione
  rozliczenie”: kliknij `Wyślij poprawione`. Gdy w tygodniu czekają też inne pliki, przy pracowniku stoi `Zmienione po
  wysłaniu`: zaznacz go i wyślij razem z resztą.
- `Nie wyszło`: powód stoi przy pracowniku; kliknij `Ponów` przy nim albo `Ponów` na dole karty.
- `Brak adresu`: dopisz pracownikowi adres w sekcji `Wykonawcy`. `Bez zleceń`: pracownik nie miał w tym tygodniu
  zleceń, więc plik nie idzie.
- Plik otwarty w Excelu nie pójdzie: zapisz go, zamknij i wyślij jeszcze raz.
