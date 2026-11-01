# Model Domeny

Ten plik opisuje język procesu. Nie opisuje implementacji.

## Okres rozliczeniowy

Tygodniowy przedział pracy od wtorku do poniedziałku. Jest identyfikowany przez
token zawierający dzień wtorku, dzień poniedziałku, miesiąc i rok, na przykład
`08_14_09_2026`. Miesiąc i rok są z poniedziałku, tak jak w folderach taty: na
przełomie miesięcy i lat liczy się nowszy miesiąc, więc okres od 27 października
do 2 listopada 2026 ma token
`27_02_11_2026`, a od 29 grudnia 2026 do 4 stycznia 2027 token `29_04_01_2027`.
Każdy okres ma jeden token.

## Rejestr zleceń

Skoroszyt `ZLECENIA INTERMAX OD 08_11_2021.xlsx`, do którego tata wkleja
zlecenia skopiowane z aplikacji firmowej. Tata nazywa go też INTERMAX; obie
nazwy znaczą to samo. Jest jedynym źródłem prawdy o zleceniach wszystkich
okresów. Zawiera między zleceniami całkowicie puste wiersze. Procesy go
czytają. Uporządkowanie INTERMAX zmienia w nim tylko Surowe zlecenia i widok
po otwarciu, a przywrócenie Kopii INTERMAX zastępuje go w całości tą kopią.

## Aplikacja firmowa

System INEA, z którego tata i jego pracownicy kopiują zlecenia do Rejestru
zleceń. Numer w `NUMER ZL.` prowadzi do zlecenia w tym systemie. Tata nie
wpisuje w nim wyceny zleceń.
_Avoid_: efenix (to inny system)

## efenix

System firmy, z którą tata się rozlicza, na stronie efenix.pl. Tata loguje się
do niego własnym kontem i przy każdym zleceniu wpisuje wycenę, której kwota
musi być równa `Kwota` (AU) tego zlecenia w Pliku zbiorczym. Zlecenie znajduje
po `Numer dokumentu`, równym `NUMER ZL.`, a nie po `Identyfikator Fenix`.
Ilości wpisane do wyceny efenix zapamiętuje od razu, bez „Zapisz”. Daty
wykonania późniejszej niż dziś ani wcześniejszej niż pierwszy dzień poprzedniego
miesiąca efenix nie przyjmuje. Realizator
zlecenia w efenix to ten sam identyfikator co `WYKONAWCA` w Pliku zbiorczym.
Zdjęcia, które robią Wykonawcy, leżą w chomiku (chomik.efenix.pl) przy swoim
zleceniu.
_Avoid_: aplikacja firmowa, Fenix

## Przekazanie do akceptacji

Zielony „Zapisz” przy zleceniu w efenix: zlecenie przechodzi ze statusu „Do
wyceny” do „Do akceptacji” i jego wycenę sprawdza firma. Robi je tylko tata.
Czerwony „Zapisz” obok niego anuluje zlecenie.
_Avoid_: zapis, zatwierdzenie

## Wycena w efenix

Proces, który tata uruchamia w Centrum rozliczeń dla okresu po Gotowości:
w oknie efenix, w którym tata jest zalogowany, uzupełnia wycenę każdego
zlecenia Pliku zbiorczego, które nie jest Zleceniem ze zdjęciami ani usterką,
Wyceną Emmetta i Ilościami usług z Pliku zbiorczego, a gotowe oznacza
Znacznikiem efenix. Nigdy nie robi Przekazania do akceptacji. Zlecenie, którego
nie da się uzupełnić tak, żeby kwota była równa `Kwota` (AU), zostawia tacie
jako błąd, a sprzeczność z Wyceną Emmetta jako ostrzeżenie.
_Avoid_: wpisywanie, import, synchronizacja

## Wycena Emmetta

Ilości, które Emmett, skrypt w efenix, wpisuje do zlecenia po kliknięciu
„Załaduj wycenę przygotowaną przez Emmetta”, zanim tata przeniesie do niego
Ilości usług z Pliku zbiorczego. Nikt ich nie nadpisuje: gdy różnią się od
Pliku zbiorczego, sprzeczność rozstrzyga tata. Załadowanie Wyceny Emmetta
czyści wycenę, którą zlecenie już ma.

## Znacznik efenix

Jasnofioletowe wypełnienie komórki `ADRES` zlecenia w Pliku zbiorczym: wycena
tego zlecenia jest uzupełniona w efenix Ilościami usług z Pliku zbiorczego, jej
kwota jest równa `Kwota` (AU), a Przekazanie do akceptacji należy do taty. Nie jest
Wyróżnieniem i nie przechodzi do Rozliczeń pracowników.
_Avoid_: kolor gotowości, zaznaczenie

## Surowe zlecenia

Zlecenia, które tata albo jego pracownik wkleił z aplikacji firmowej na dół
Rejestru zleceń, pod uporządkowane już dni, a których Uporządkowanie INTERMAX
jeszcze nie uporządkowało. Jedno wklejenie to zwykle zlecenia jednego dnia. Mają
wygląd z aplikacji. Pierwszy wiersz wklejenia przychodzi przesunięty o dwie
kolumny w lewo, ale zlecenia są Surowe także wtedy, gdy ktoś przesunął go już
ręcznie. W `CZYNNOŚCI` mają tylko nazwę operatora, a w `URZĄDZENIA` rodzaj
zlecenia (instalacja, usterka); poza Wpisem urządzenia i czynności INTERMAX
resztę dopisują ręcznie tata i pracownicy po Uporządkowaniu INTERMAX.
_Avoid_: eksport, nowe dane

## Uporządkowanie INTERMAX

Proces, który tata uruchamia w Centrum rozliczeń po wklejeniu Surowych
zleceń dnia. Przesuwa pierwszy wiersz na miejsce, gdy przyszedł przesunięty,
dzieli zlecenia na segmenty Wykonawców w kolejności alfabetycznej, oddzielone
jednym pustym wierszem, w segmencie układa je od najwcześniejszej godziny do
najpóźniejszej i nadaje im od kolumny A do `UWAGI` wygląd reszty Rejestru
zleceń z cienką ramką i pogrubionym tylko `WYKONAWCA`, Kolory operatora i Wpisy
urządzenia i czynności INTERMAX, a kolumny z aplikacji za `UWAGI` usuwa. Dzień stawia jeden pusty wiersz pod żółtym wierszem, którym
tata oddziela dni, a bez niego 10 pustych wierszy pod ostatnim uporządkowanym
zleceniem. Po nim Rejestr otwiera się na dzisiejszym dniu z kalendarza, a gdy
dziś nie ma zleceń, na ostatnim wcześniejszym dniu ze zleceniami. Zmienia tylko
Surowe zlecenia i widok po otwarciu. Dnia, który już jest uporządkowany, nie
porządkuje drugi raz; zlecenia dopisane później do takiego dnia wpisuje się
ręcznie. Porządkuje dzień, nie okres. Po nim tata i pracownicy uzupełniają
dzień ręcznie, a dopiero potem okres trafia do Przygotowania pliku zbiorczego.
_Avoid_: formatowanie, import

## Kopia INTERMAX

Stan Rejestru zleceń zapisany przed Uporządkowaniem INTERMAX albo przed
przywróceniem innej Kopii INTERMAX, nazwany datą i godziną, z której pochodzi.
Leży na komputerze taty poza OneDrive. Tata przywraca ją z Centrum rozliczeń;
zmiany późniejsze od niej wtedy znikają.
_Avoid_: backup, wersja

## Kolor operatora

Wypełnienie, które Uporządkowanie INTERMAX nadaje zleceniu po nazwie operatora
w `CZYNNOŚCI`, a przy usterce po rodzaju zlecenia. `CZYNNOŚCI` i `NUMER UMOWY`
dostają: T-Mobile zielony, Orange pomarańczowy, każdy inny operator jasny
niebieski, a Netia ciemniejszy niebieski w `CZYNNOŚCI` i jasny niebieski w
`NUMER UMOWY`. INEA i zlecenie bez operatora zostają bez wypełnienia. Nazwa
operatora nie zależy od wielkości liter, spacji, myślników ani dopisku `S.A.`:
`T-Mobile` to TMOBILE, a `Netia S.A.` to Netia. Usterka
i usterka hurt mają zamiast tego różowe `URZĄDZENIA`. W Rejestrze zleceń jest
Wyróżnieniem jak każde inne; inne kolory w Rejestrze to ręczne zaznaczenia
taty i jego pracowników.

## Wpis urządzenia i czynności INTERMAX

Wartości `URZĄDZENIA` i `CZYNNOŚCI`, które Uporządkowanie INTERMAX wpisuje
Surowemu zleceniu z rodzajem `Instalacja Hurt` po nazwie operatora w
`CZYNNOŚCI`, tej samej co przy Kolorze operatora: `URZĄDZENIA` zastępuje, a
do nazwy operatora w `CZYNNOŚCI`, takiej jak z aplikacji, dopisuje czynność. Netia, P4, Plus, VECTRA i SYSTEMIA dostają `nokia` i
` - akt pętli`, ORANGE `gniazdo` i ` - akt pętli LLU`, a TMOBILE `nokia
getewayHomeBox` i ` - akt int`. Usterki, instalacje ręczne, inne rodzaje
zleceń i inni operatorzy, także INEA i OXYLION, zostają bez wpisu. Zlecenie
ORANGE, które okazało się BSA, tata i pracownicy poprawiają ręcznie na `nokia`
i ` - akt pętli BSA`, tak jak dopisują `stb2`, `tv` czy `akt int` po wizycie.
_Avoid_: szablon, autouzupełnianie

## Zlecenie skuteczne

Zlecenie, którego wartość `SKUTECZNE` to `tak`, bez względu na wielkość liter i
otaczające spacje. Każde zlecenie skuteczne z Rozliczenia wewnętrznego trafia
do Pliku zbiorczego.

## Zlecenie nieskuteczne

Zlecenie, którego wartość `SKUTECZNE` to `nie`, bez względu na wielkość liter i
otaczające spacje. Każde zlecenie okresu jest skuteczne albo nieskuteczne.
Puste `SKUTECZNE` albo inna wartość, na przykład `???` czy `tsk`, to brak w
Rejestrze, który tata uzupełnia, a nie trzeci stan zlecenia.

## Rozliczenie wewnętrzne

Skoroszyt `Rozliczenie wew. {okres}.xlsx` zawierający wszystkie zlecenia
jednego okresu rozliczeniowego z Rejestru zleceń, skuteczne i nieskuteczne, w
kolejności z Rejestru, bez pustych wierszy. Ma formatowanie Wzorca rozliczenia
wewnętrznego, a zlecenia Wygląd Wiersza danych, do którego tata jest
przyzwyczajony.

## Wzorzec rozliczenia wewnętrznego

Wspólny skoroszyt bazowy, z którego powstaje Rozliczenie wewnętrzne nowego
okresu. Jest jedynym źródłem szerokości kolumn Rozliczenia wewnętrznego, nie
poprzedni okres. Plik okresu otwiera się tak jak jego Wzorzec: w lewym górnym
rogu arkusza, w powiększeniu 75%. Nie zawiera zleceń i pozostaje niezmieniony.

## Wzorzec pliku zbiorczego

Wspólny skoroszyt bazowy, z którego powstaje Plik zbiorczy nowego okresu.
Zachowuje stawki, sumy, formuły i formatowanie. Jest jedynym źródłem szerokości
kolumn Pliku zbiorczego, nie poprzedni okres; stawki ma własne, inne niż
Wzorzec rozliczenia pracownika. Plik okresu otwiera się tak jak jego Wzorzec:
w lewym górnym rogu arkusza, w powiększeniu 75%. Nie zawiera zleceń i
pozostaje niezmieniony.

## Wzorzec rozliczenia pracownika

Wspólny skoroszyt bazowy bez nazwy wykonawcy, z którego powstają Szablony
pracowników. Ma ten sam układ kolumn co Plik zbiorczy, ale własne stawki
pracownika. Jest jedynym źródłem szerokości kolumn Rozliczeń pracowników, nie
poprzedni okres; ma te same szerokości co Wzorzec pliku zbiorczego. Plik okresu
otwiera się tak jak jego Wzorzec: w lewym górnym rogu arkusza, w powiększeniu
75%. U taty to pusty plik `Rozliczenie {okres} -.xlsx` w Folderze rozliczeń
pracowników. Nie jest rozliczeniem konkretnej osoby i pozostaje niezmieniony.
_Avoid_: Placeholder

## Przygotowanie pliku zbiorczego

Proces poprzedzający Przebieg rozliczeń: z Rejestru zleceń tworzy Rozliczenie
wewnętrzne okresu, a z jego zleceń skutecznych Plik zbiorczy z Ilościami usług
wyznaczonymi przez Reguły ilości. Nie zaczyna, gdy okres ma Surowe zlecenia.
Oba pliki powstają razem albo żaden. Jedyny wyjątek: jeśli po nieudanym
zapisie nie da się usunąć pliku, który już trafił do Folderu okresu,
Zatrzymanie wskazuje ten plik. Uruchamiany osobno od Przebiegu rozliczeń.

## Plik zbiorczy

Skoroszyt `Rozliczenie {okres} - zbiorcze.xlsx`: zlecenia skuteczne wszystkich
wykonawców dla jednego okresu rozliczeniowego. Jest wynikiem Przygotowania
pliku zbiorczego i jedynym wejściem Przebiegu rozliczeń.

## Wykonawca

Osoba wskazana w kolumnie `WYKONAWCA` pliku zbiorczego. Wartość w tej kolumnie
jest identyfikatorem źródłowym, który nie musi być identyczny z nazwą człowieka
w nazwie pliku docelowego.

## Konfiguracja wykonawców

Plik konfiguracji w folderze `config`, który łączy identyfikator Wykonawcy z
kolumny `WYKONAWCA` (H) z nazwą Wykonawcy w Rozliczeniu pracownika. Wspólny
dla Przebiegu rozliczeń i Przygotowania pliku zbiorczego.

## Szablon pracownika

Skoroszyt przygotowany dla konkretnego wykonawcy na podstawie Wzorca
rozliczenia pracownika. Zachowuje jego strukturę, formuły, stawki i
formatowanie; jedynie Wiersze danych mają Wygląd Wiersza danych oraz
Wyróżnienia i Hiperłącza z Pliku zbiorczego.
Zawiera dane tylko z własnego okresu i może pozostać pusty, jeśli wykonawca nie
ma wierszy w Pliku zbiorczym.

## Folder okresu

Folder o nazwie równej tokenowi okresu, wspólny dla wszystkich plików jednego
okresu rozliczeniowego: Rozliczenia wewnętrznego, Pliku zbiorczego i Folderu
rozliczeń pracowników. Może istnieć wcześniej, zanim powstaną te pliki.
Folder, którego nazwa nie jest tokenem żadnego okresu (na przykład
`09_15_09_2026`, bo 9 września 2026 to nie wtorek), nie jest Folderem okresu.

## Folder okresów

Folder, w którym narzędzie szuka Folderów okresu. W układzie folderów taty to
`Załączniki`, a Foldery okresu leżą w `Rozliczenia {rok}\{miesiąc}\INEA`.
Miesiąc to cykl rozliczeniowy taty, nie kalendarz, więc Folder okresu zakłada
tata, a narzędzie go odszukuje. Folder wskazany wewnątrz `Rozliczenia {rok}`
(np. `INEA` jednego miesiąca) to ten sam układ liczony od `Załączniki`. Bez
folderów `Rozliczenia {rok}` Foldery okresu leżą w folderze okresów
bezpośrednio (np. `INEA`).

## Ustawienia taty

Rejestr zleceń i folder okresów wskazane raz w Centrum rozliczeń. Czyta je
tylko Centrum rozliczeń.

## Folder rozliczeń pracowników

Folder danego okresu zawierający osobny skoroszyt dla każdego wykonawcy.

## Przygotowanie skoroszytów pracowników

Etap tworzenia plików nowego okresu przez skopiowanie Wzorca rozliczenia
pracownika dla każdego wykonawcy. Token okresu i nazwa wykonawcy trafiają do
nazw folderu i plików; struktura, formuły, stawki i formatowanie Wzorca
rozliczenia pracownika pozostają zachowane, a sam Wzorzec pozostaje
niezmieniony.

## Przetworzenie Szablonu pracownika

Obsłużenie jednego Szablonu pracownika w ramach przygotowania Rozliczeń
pracowników. Kończy się uzupełnieniem danych albo pozostawieniem pustego
szablonu. Gdy zapis nie jest bezpieczny, Przebieg rozliczeń się zatrzymuje i
nie publikuje żadnego Rozliczenia pracownika.

## Rozliczenie pracownika

Szablon pracownika uzupełniony wierszami tego wykonawcy z danego okresu, bez
Ilości tylko dla INEA.
Plik jest identyfikowany nazwą `Rozliczenie {okres} - {nazwa wykonawcy}.xlsx`;
`{okres}` to token okresu rozliczeniowego.

## Wiersz danych

Wiersz pod nagłówkiem z danymi wejściowymi pracy: w Pliku zbiorczym, Szablonach
pracowników i ich Wzorcach od 18. w dół, w Rozliczeniu wewnętrznym od 2.; wiersz
Rejestru zleceń ze zleceniem staje się Wierszem danych obu plików okresu.
Formuły i techniczne wartości szablonu nie są same w sobie wierszami danych.

## Wygląd Wiersza danych

Wygląd każdej komórki zapisanego Wiersza danych w kolumnach A:M Rozliczenia
wewnętrznego i A:L Pliku zbiorczego oraz Rozliczenia pracownika, taki jak w
plikach, które tata robił ręcznie: krój i rozmiar czcionki nagłówka tej kolumny
we wzorcu, Wyróżnienia, wyrównanie do lewej i do środka wysokości, zawijanie
tylko tekstu z końcem linii, cienkie obramowanie z czterech stron i format
liczby komórki, z której pochodzi wartość. Wiersz nie ma stałej wysokości.
Resztki formatowania wzorca w tych komórkach nie zostają; kolumny dalej mają
wygląd wzorca.
_Avoid_: styl wiersza, formatowanie wiersza

## Ilości usług

Liczby w kolumnach `N:AP` Wiersza danych: ile razy przy zleceniu płatna jest
dana pozycja cennika. W Pliku zbiorczym płaci ją tacie INEA, a w Rozliczeniu
pracownika tata Wykonawcy. Wartość pozycji to jej ilość razy koszt z wiersza 14
tego pliku. Dodatek 45 zł za usterkę po 17:00 albo w sobotę tata zapisuje jako
ilość 45 w pozycji o koszcie 1 zł.
_Avoid_: cyfry, zera i jedynki, kolumny

## Ilości tylko dla INEA

Ilości usług z Pliku zbiorczego, które INEA płaci tacie, a Wykonawca ich nie
wykonuje, więc nie przechodzą do Rozliczenia pracownika: `AP` w zleceniu z
`gniazdo` w `URZĄDZENIA` i `AK` w zleceniu z `technicolor` w `URZĄDZENIA`, bez
względu na liczbę. Należą do taty, tak jak Reguły ilości.
_Avoid_: kasowanie jedynek, usuwanie cyfr

## Reguły ilości

Zasady taty, które z treści zlecenia (`UMOWA`, `URZĄDZENIA`, `CZYNNOŚCI`,
`DATA`) wyznaczają Ilości usług. Należą do taty: zmiany zgłasza Maksowi. Ilości
wynikające z opisu technika (`CZYNNOŚCI ZREALIZOWANE`) nie są Regułami ilości,
bo wpisuje je tata.
_Avoid_: scenariusze rozliczeń, instrukcja

## Ilości do uzupełnienia

Ilości usług w Pliku zbiorczym, których Reguły ilości nie wyznaczają, więc
wpisuje je tata: w wierszu bez reguły (nieznane `URZĄDZENIA`, reguły dały najwyżej
V, T i N), w wierszu z opisu (prewencja, niedostępność usług albo puste
`URZĄDZENIA`, reguły nie dały nic) i w kolumnach z opisu technika w każdym
wierszu. To miejsca zostawione tacie, nie błędy.
_Avoid_: błędy, braki, cyfry do wpisania

## Zlecenie ze zdjęciami

Zlecenie Pliku zbiorczego z wartością inną niż 0 w którejkolwiek z kolumn AB,
AC, AD, AE, AF, AJ–AP albo AS: płatna czynność, którą firma rozlicza tylko ze
zdjęciem spełniającym jej kryteria (np. otwarte gniazdo spawne z widocznymi
śrubkami). Tata sprawdza zdjęcia, zanim wyceni takie zlecenie w efenix; gdy
zdjęcie nie spełnia kryteriów, firma odsyła je z pytaniami. Usterka (ilość w
`AI`) nie jest Zleceniem ze zdjęciami: usterek nie wycenia się w efenix.
_Avoid_: zlecenie z cyfrą, zlecenie dodatkowo płatne

## Uzupełnienie pliku zbiorczego

Etap między Przygotowaniem pliku zbiorczego a Przebiegiem rozliczeń: tata
wpisuje w Excelu Ilości do uzupełnienia. Kończy go Gotowość.
_Avoid_: uzupełnienie Excela, poprawki

## Wyróżnienie

Wygląd komórki, którym tata, jego pracownik albo Uporządkowanie INTERMAX
(Kolor operatora) zaznacza zlecenie: kolor wypełnienia, kolor
czcionki, pogrubienie i kursywa. Przechodzi razem z wartością z Rejestru zleceń
do plików okresu, a z Pliku zbiorczego do Rozliczeń pracowników. Wyróżnienia
zastępują wygląd komórki wzorca w całości: komórka bez Wyróżnień daje komórkę
bez wypełnienia, z kolorem automatycznym, bez pogrubienia i bez kursywy. Krój i
rozmiar czcionki nie są Wyróżnieniem i pochodzą z wzorca (Wygląd Wiersza
danych).
_Avoid_: formatowanie (szersze: obejmuje też krój, obramowania i formaty liczb)

## Hiperłącze

Adres poza skoroszytem, który komórka otwiera po kliknięciu, np. numer zlecenia
w `NUMER ZL.` prowadzący do zlecenia w aplikacji firmowej. Przechodzi razem z
wartością komórki z Rejestru zleceń do plików okresu, a z Pliku zbiorczego do
Rozliczeń pracowników, i zastępuje hiperłącze komórki wzorca: komórka bez
Hiperłącza daje komórkę bez hiperłącza.
Komórka bez wartości nie niesie Hiperłącza. Odnośnik do miejsca w tym samym
skoroszycie (np. do innego arkusza) nie jest Hiperłączem i nie przechodzi.
Hiperłącze nie jest Wyróżnieniem i nie zmienia wyglądu komórki. Adres jest
treścią wiersza: nie trafia do Komunikatów, Zdarzeń przebiegu, metryk ani
Zgłoszeń.
_Avoid_: link, odnośnik

## Gotowość

Świadoma decyzja taty, że plik zbiorczy jest zakończony i można przygotować
rozliczenia pracowników. W pierwszej wersji gotowość jest potwierdzana przez
uruchomienie procesu, a nie zgadywana na podstawie samego zapisu pliku.

## Status okresu

Etap okresu rozliczeniowego wynikający z plików w jego Folderze okresu: Brak
plików okresu, gdy nie ma Pliku zbiorczego; Plik zbiorczy przygotowany, gdy
jest Plik zbiorczy, ale nie ma Folderu rozliczeń pracowników; Rozliczenia
pracowników gotowe, gdy jest Folder rozliczeń pracowników. Nie zastępuje
Gotowości: Plik zbiorczy przygotowany nie znaczy, że tata go zakończył.

## Przebieg rozliczeń

Jedno uruchomienie procesu od wskazania Pliku zbiorczego do wyniku końcowego
albo bezpiecznego przerwania. Obejmuje Przygotowanie skoroszytów pracowników,
a następnie ich uzupełnienie danymi z Pliku zbiorczego.

## Uruchomienie procesu

Jedno uruchomienie Przebiegu rozliczeń, Przygotowania pliku zbiorczego,
Uporządkowania INTERMAX albo Wyceny w efenix z Centrum rozliczeń albo ze
Skryptu dla maszyn, od
gotowych plików (i okresu, gdy proces go ma) do wyniku końcowego. Decyzja
taty należy do Uruchomienia procesu bez względu na to, skąd wystartowało.
Kończy się sukcesem, wynikiem wymagającym sprawdzenia albo Zatrzymaniem z
bezpiecznym Komunikatem zrozumiałym dla taty, nigdy z treścią błędu
technicznego.
_Avoid_: Przebieg (zarezerwowany dla Przebiegu rozliczeń)

## Decyzja taty

Pytanie, które proces zadaje tacie w trakcie Uruchomienia procesu; dziś tylko
o niepełny okres w Przygotowaniu pliku zbiorczego. Składa ją proces i sam
zatrzymuje się po odmowie; rozmówca tylko pyta i mówi, jak wyrazić zgodę
(`Kontynuuj` w Centrum rozliczeń). Odmowa kończy Uruchomienie procesu
Zatrzymaniem po odmowie w Decyzji taty. Skrypt dla maszyn zawsze odmawia. Czas
czekania na Decyzję taty nie wlicza się do `Czas uruchomienia` ani do metryk.

## Centrum rozliczeń

Lokalna aplikacja w przeglądarce na komputerze taty, z której uruchamia
Uporządkowanie INTERMAX, Przygotowanie pliku zbiorczego, Przebieg rozliczeń i
Wycenę w efenix, przywraca Kopię INTERMAX oraz widzi Status okresu każdego okresu i historię
Uruchomień procesu. Jest jedynym wejściem taty do
tych procesów, nie osobnym procesem.
_Avoid_: dashboard, panel, centrum dowodzenia

## Katalog procesów

Jeden wpis na każdy proces, który uruchamia Centrum rozliczeń: nazwa i widok
Uruchomienia procesu, Ustawienia taty, bez których proces nie startuje,
czytane Wzorce i sprawdzenia Diagnozy w kolejności wyjaśniania. Diagnoza, Logi
Uruchomienia, Metryki i Konfiguracja pytają wpis procesu, zamiast rozróżniać
procesy same; pliki procesu wynikają z jego Ustawień taty i Wzorców.
_Avoid_: rejestr procesów, lista procesów

## Skrypt dla maszyn

Jedyne wejście do procesów spoza Centrum rozliczeń, dla testów, pomiarów czasu
i osoby utrzymującej narzędzie. Przyjmuje parametrami pliki i okres, gdy
proces go ma, a Wycena w efenix także adres efenix (w testach Atrapy efenix), z nikim nie rozmawia i oddaje wynik w kształcie karty Uruchomienia. Jego Uruchomienia
procesu mają w historii Centrum odznakę `.cmd`, tę samą co stare Uruchomienia
z dawnych launcherów.
_Avoid_: CLI, launcher

## Zdarzenie przebiegu

Bezpieczny fakt opisujący zmianę lub wynik jednego Uruchomienia procesu, na
przykład rozpoczęcie etapu, zakończenie etapu albo przerwanie etapu. Wszystkie
trzy procesy przechodzą te same etapy:
Sprawdzanie, Odczyt danych, Planowanie i Zapisywanie. Tylko Przebieg rozliczeń
zgłasza też rozpoczęcie i zakończenie przetwarzania Szablonu pracownika.
Zdarzenie nie zawiera adresów klientów, numerów zleceń ani treści wierszy.

## Komunikat

Bezpieczny tekst dla taty w trzech częściach: Co się stało, Gdzie, Co zrobić.
Trzy części nie zawierają pełnych ścieżek, treści wyjątków, adresów ani treści
wierszy; wskazują tylko nazwę pliku, folder, arkusz, kolumnę, wiersz albo
Wykonawcę. Jedynym wyjątkiem jest Zatrzymanie o brakach w `SKUTECZNE`:
pokazuje dokładną zawartość komórki innej niż `tak` i `nie`, żeby tata od razu
widział, co poprawić. Komunikat niesie Zatrzymanie, ostrzeżenie, problem z
podsumowania albo problem startu Centrum rozliczeń. Jego kod jest unikalny w
obrębie procesu.
_Avoid_: błąd, wiadomość

## Zatrzymanie

Zakończenie Uruchomienia procesu bez wyniku, z jednym Komunikatem: własne
zatrzymanie procesu (np. Nienadpisywanie) albo nieoczekiwany wyjątek, także po
zakończeniu zapisu.
_Avoid_: przerwanie, awaria, błąd

## Nieoczekiwany wyjątek

Zatrzymanie, którego przyczyną jest wyjątek w kodzie narzędzia, a nie reguła
procesu. Tata dostaje ogólny Komunikat; typ wyjątku i ślad wywołań trafiają
tylko do Zgłoszenia.
_Avoid_: nieoczekiwany błąd, crash

## Rodzaj Zatrzymania

Kto usuwa przyczynę Zatrzymania: „dla taty”, gdy Komunikat mówi, co zrobić,
albo „do Maksa”, gdy bezwarunkowo każe przekazać go osobie utrzymującej
narzędzie. Nieoczekiwany wyjątek jest zawsze „do Maksa”. Powtórka zmienia
Zatrzymanie „dla taty” w takie, przy którym Centrum proponuje Diagnozę.
Zatrzymanie po odmowie w Decyzji taty rekord metryk zapisuje jako „dla taty”,
ale nigdy nie jest Powtórką ani nie ma Diagnozy. Rekord metryk zapisuje rodzaj
bez Powtórki, a Historia i karta wyniku pokazują jako błąd tylko Zatrzymanie
„do Maksa”: Zatrzymanie „dla taty” jest do poprawy, a po odmowie w Decyzji
taty neutralne.

## Powtórka

Następne Uruchomienie procesu tego samego procesu, które kończy się
Zatrzymaniem o tym samym odcisku problemu co poprzednie. Centrum pamięta
poprzednie Zatrzymanie tylko do swojego zamknięcia.

## Odcisk problemu

Tożsamość problemu: proces, kod Komunikatu i jego trzy części. Proces należy
do odcisku, bo kody Komunikatów są unikalne tylko w obrębie procesu.

## Diagnoza

Sprawdzenie tylko do odczytu, które tata uruchamia w Centrum rozliczeń przy
Zatrzymaniu „do Maksa” albo Powtórce; przy nieoczekiwanym wyjątku zaczyna się
sama. Ustala przyczynę na komputerze taty i wyjaśnia ją w trzech częściach, jak
Komunikat. Niczego nie zmienia ani nie naprawia.

## Zgłoszenie

Komunikat Zatrzymania razem z wynikiem Diagnozy, wysłany z Centrum rozliczeń
do Maksa. Jeden odcisk problemu ma najwyżej jedno otwarte Zgłoszenie; gdy Maks
je zamknie, a problem wraca, powstaje nowe z odnośnikiem do poprzedniego.
Zgłoszenie, które nie może od razu wyjść (brak internetu albo Tokenu do
Zgłoszeń), czeka w Kolejce wysyłki i wychodzi samo.

## Logi Uruchomienia

Pełny, bezpieczny obraz jednego Uruchomienia procesu z Centrum rozliczeń:
wynik, Komunikaty, podsumowanie, przebieg etapów i Szablonów pracownika oraz
wersja narzędzia. Mówią wprost, czy był to podgląd, w którym nic nie
zapisano, czy Uruchomienie z zapisem. Zostają na komputerze taty także po
zamknięciu Centrum i trafiają same do Skrzynki Zgłoszeń, gdzie wszystkie
Uruchomienia jednego okresu są w jednym miejscu; Uruchomienie Uporządkowania
INTERMAX jest tam przy okresie dnia, w którym tata je uruchomił. Nie zawierają
adresów,
numerów zleceń ani numerów umów. Tata ich nie wysyła ani nie ogląda, ale z
nich wraca karta Uruchomienia po starcie Centrum i w Historii.
_Avoid_: Zgłoszenie (to Zatrzymanie z Diagnozą), dziennik Centrum, raport

## Urwane Uruchomienie

Uruchomienie procesu z Centrum rozliczeń, które nie doszło do wyniku, bo
Centrum zamknęło się w jego trakcie. Nie ma Logów Uruchomienia ani rekordu
metryk; Centrum nazywa je po następnym starcie i radzi, co sprawdzić.
_Avoid_: Zatrzymanie (kończy się Komunikatem procesu), przerwane (tak Metryki
nazywają Zatrzymania)

## Uwaga taty

Własny tekst taty do Maksa z tytułem, który tata pisze z dowolnego widoku
Centrum rozliczeń i przed wysłaniem do Skrzynki Zgłoszeń widzi w całości.
Powiadomienia nazywają ją tym tytułem, nie numerem. Jest ogólna, o całym
narzędziu, albo przypięta do jednego Uruchomienia procesu, i wtedy prowadzi do
jego Logów Uruchomienia. Każda Uwaga taty to osobna sprawa, którą Maks
zamyka.
_Avoid_: Zgłoszenie (to Zatrzymanie z Diagnozą), feedback, komentarz

## Skrzynka Zgłoszeń

Miejsce, do którego trafiają Zgłoszenia, Kontrole ilości, Logi Uruchomienia i
Uwagi taty i w którym Maks je zamyka: prywatne repozytorium Zgłoszeń. Centrum
pyta ją o otwarte Zgłoszenie odcisku problemu, o otwarte issue Kontroli ilości
okresu, o issue Logów Uruchomienia okresu (także zamknięte) i o stan wysłanych
Zgłoszeń. Z jej odpowiedzi Centrum wie, czy przyjmuje Token do Zgłoszeń.
_Avoid_: issue tracker, publiczne issue

## Token do Zgłoszeń

Token, którym Centrum rozliczeń wysyła do Skrzynki Zgłoszeń. Wpisuje go Maks na
komputerze taty, a tata go nie widzi. Może go brakować albo Skrzynka może go
odrzucić; wtedy nic nie wychodzi, dopóki Maks go nie naprawi, a tata widzi, że
Token do Zgłoszeń nie działa i ma skontaktować się z Maksem.
_Avoid_: klucz, hasło

## Kolejka wysyłki

Miejsce na komputerze taty, w którym Zgłoszenia, Uwagi taty, Logi Uruchomienia
i Kontrole ilości czekają, aż przyjmie je Skrzynka Zgłoszeń. Bez internetu
wychodzą same, gdy sieć wróci, a bez działającego Tokenu do Zgłoszeń, gdy Maks
go naprawi. Treść, którą Skrzynka odrzuciła, zostaje w niej do następnego
startu Centrum rozliczeń; tata ma wtedy skontaktować się z Maksem.
_Avoid_: outbox, bufor

## Kontrola ilości

Porównanie Ilości usług, które dają Reguły ilości, z Ilościami usług w Pliku
zbiorczym, z którego tata uruchomił Przebieg rozliczeń. Pokazuje Maksowi, co
tata musiał poprawić albo dopisać ręcznie. Jeden okres ma jedną Kontrolę
ilości w Skrzynce Zgłoszeń, a tata jej nie wysyła ani nie ogląda.
_Avoid_: Zgłoszenie (to Zatrzymanie z Diagnozą), raport różnic

## Powiadomienie

Fakt dla taty o jego Zgłoszeniach, Uwagach taty i wersjach narzędzia, pokazany
w widoku Powiadomienia w Centrum rozliczeń, do którego prowadzi dzwonek.
Nieprzeczytane Powiadomienie zapala kropkę na dzwonku; wejście do widoku
oznacza wszystkie jako przeczytane. Uwagi techniczne z karty Uruchomienia, np.
o niezapisanych metrykach, nie są Powiadomieniami.
_Avoid_: notyfikacja, alert

## Powiadomienie o nowej wersji

Powiadomienie o Wydaniu nowszym od wersji taty: jego numer, notka „Co nowego”
i Uwagi taty oraz Zgłoszenia, które rozwiązuje. Ma przycisk Aktualizacji
narzędzia, dopóki tata nie przejdzie na to Wydanie albo nowsze. Sprawę, którą
Maks rozwiązał przed Wydaniem, osobne Powiadomienie nazywa rozwiązaną, z
dopiskiem, że będzie w następnej wersji.
_Avoid_: Powiadomienie o naprawie

## Wersja narzędzia

Commit klonu narzędzia, z którego wystartowało Centrum rozliczeń na komputerze
taty. Karta `Narzędzie` w Konfiguracji pokazuje jego skrót i dzień, od którego
narzędzie jest na tym commicie; Zgłoszenie podaje pełny commit.
_Avoid_: numer wersji z `pyproject.toml`

## Wydanie

Wersja narzędzia, którą Maks świadomie ogłasza tacie: numer, np. `0.2.0`, i
krótka notka „Co nowego” dla taty. Jedno Wydanie zbiera wszystkie zmiany od
poprzedniego, a nie każdą naprawę z osobna. Tylko Wydanie może trafić na
komputer taty; zmiany, które nie weszły do żadnego Wydania, u taty nie działają.
_Avoid_: release, deploy, `main`

## Aktualizacja narzędzia

Przejście narzędzia na komputerze taty na najnowsze Wydanie, które tata zleca
jednym przyciskiem w Centrum rozliczeń. Przycisk jest tylko wtedy, gdy jest
Wydanie nowsze od wersji taty. Udaje się w całości albo zostawia poprzednią
wersję; pliki taty pozostają nietknięte.
_Avoid_: upgrade, git pull, instalacja

## Aktualność narzędzia

Czy narzędzie na komputerze taty jest na najnowszym Wydaniu: `Aktualna`,
`Jest nowsza wersja` albo `Nie sprawdzono` (bez internetu). Pokazuje ją
Konfiguracja i sprawdza Diagnoza; nowsza wersja jest przyczyną Zatrzymania
tylko wtedy, gdy Diagnoza nie znalazła innej.
_Avoid_: świeżość, freshness

## Ponowny start Centrum

Koniec udanej Aktualizacji narzędzia: Centrum rozliczeń samo się zamyka i
startuje w nowej wersji na tym samym adresie, a otwarta karta przeglądarki
sama się odświeża. Gdy nowa wersja nie wystartuje, wraca poprzednia, a karta
pokazuje Komunikat.
_Avoid_: restart, reboot

## Nienadpisywanie

Jeśli folder lub pliki docelowe nowego okresu już istnieją, proces zatrzymuje
się bez ich nadpisywania. Wzorce również pozostają niezmienione, a Rejestr
zleceń zmieniają tylko Uporządkowanie INTERMAX i przywrócenie Kopii INTERMAX.
