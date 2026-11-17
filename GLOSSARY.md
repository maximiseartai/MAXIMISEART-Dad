# Model Domeny

Ten plik opisuje język procesu.
Nie opisuje implementacji.

## Okres rozliczeniowy

Tygodniowy przedział pracy od wtorku do poniedziałku.
Jest identyfikowany przez token zawierający dzień wtorku, dzień poniedziałku, miesiąc i rok, na przykład `08_14_09_2026`.
Miesiąc i rok są z poniedziałku, tak jak w folderach taty: na przełomie miesięcy i lat liczy się nowszy miesiąc, więc okres od 27 października do 2 listopada 2026 ma token `27_02_11_2026`, a od 29 grudnia 2026 do 4 stycznia 2027 token `29_04_01_2027`.
Każdy okres ma jeden token.

## Rejestr zleceń

Skoroszyt `ZLECENIA INTERMAX OD 08_11_2021.xlsx`, do którego tata wkleja zlecenia skopiowane z aplikacji firmowej.
Tata nazywa go też INTERMAX; obie nazwy znaczą to samo.
Jest jedynym źródłem prawdy o zleceniach wszystkich okresów.
Zawiera między zleceniami całkowicie puste wiersze.
Procesy go czytają.
Uporządkowanie INTERMAX zmienia w nim tylko Surowe zlecenia i widok po otwarciu, Wpisanie raportów tylko zlecenia uporządkowanych dni (`SKUTECZNE`, `CZYNNOŚCI ZREALIZOWANE`, Przeniesienie zlecenia i Zlecenie dopisane z raportu), a przywrócenie Kopii INTERMAX zastępuje go w całości tą kopią.
Edytują go tata na swoim komputerze i jeden jego pracownik na swoim.

## Aplikacja firmowa

System INEA, z którego tata i jego pracownicy kopiują zlecenia do Rejestru zleceń.
Numer w `NUMER ZL.` prowadzi do zlecenia w tym systemie.
Tata nie wpisuje w nim wyceny zleceń.
_Avoid_: efenix (to inny system)

## efenix

System firmy, z którą tata się rozlicza, na stronie efenix.pl.
Tata loguje się do niego własnym kontem i przy każdym zleceniu wpisuje wycenę, której kwota musi być równa `Kwota` (AU) tego zlecenia w Pliku zbiorczym.
Zlecenie znajduje po `Numer dokumentu`, równym `NUMER ZL.`, a nie po `Identyfikator Fenix`.
Ilości wpisane do wyceny efenix zapamiętuje od razu, bez „Zapisz”.
Daty wykonania późniejszej niż dziś ani wcześniejszej niż pierwszy dzień poprzedniego miesiąca efenix nie przyjmuje.
Realizator zlecenia w efenix to ten sam identyfikator co `WYKONAWCA` w Pliku zbiorczym.
Zdjęcia, które robią Wykonawcy, leżą w chomiku (chomik.efenix.pl) przy swoim zleceniu.
_Avoid_: aplikacja firmowa, Fenix

## Przekazanie do akceptacji

Zielony „Zapisz” przy zleceniu w efenix: zlecenie przechodzi ze statusu „Do wyceny” do „Do akceptacji” i jego wycenę sprawdza firma.
Robi je tata albo Wycena w efenix w trybie z Przekazaniem, tylko przy zleceniu gotowym (ADR 0027).
Gdy efenix odmawia Przekazania (brak zdjęć, długości przyłącza, wyceny albo daty wykonania), Wycena w efenix zostawia zlecenie tacie jako błąd bez Znacznika.
Czerwony „Zapisz” obok niego anuluje zlecenie, a tego narzędzie nie robi nigdy.
Tata mówi o nim „zapis”, więc w Centrum rozliczeń przyciski trybów Wyceny w efenix („Uzupełnij bez zapisu”, „Uzupełnij i zapisz”) i plakietka trybu na jej karcie („Bez zapisu”, „Z zapisem”) używają jego słowa, a plakietka karty Wyceny nie mówi o zapisie plików.
Kod i dokumenty mówią Przekazanie do akceptacji.
_Avoid_: zapis, zatwierdzenie

## Wycena w efenix

Proces, który tata uruchamia w Centrum rozliczeń dla okresu po Gotowości: w oknie efenix, w którym tata jest zalogowany, uzupełnia wycenę każdego zlecenia Pliku zbiorczego, które nie jest Zleceniem ze zdjęciami ani usterką, Wyceną Emmetta i Ilościami usług z Pliku zbiorczego.
Ma dwa tryby (ADR 0027), które tata wybiera przy każdym starcie jednym z dwóch przycisków, a Centrum żadnego nie pamięta: bez Przekazania gotowe zlecenie oznacza Znacznikiem efenix, a z Przekazaniem robi jego Przekazanie do akceptacji i oznacza je Znacznikiem przekazania.
W obu trybach uzupełnia wycenę w efenix, więc tryb bez Przekazania nie jest podglądem.
Wycenę dokańcza do Pliku zbiorczego tylko w górę (ADR 0026): w każdej pozycji, w której efenix ma mniej niż plik, wpisuje ilość z pliku, także w miejsce ilości Emmetta i w wycenie, która już jest, a ilości w efenix nigdy nie obniża ani nie czyści.
Zlecenie, którego nie da się uzupełnić tak, żeby kwota była równa `Kwota` (AU), zostawia tacie jako błąd, a pozycję, w której efenix ma więcej niż plik, jako Ostrzeżenie Emmetta.
Zlecenie rozliczone i Zlecenie przekazane nie są błędem, a zlecenie o statusie innym niż „Do wyceny”, „Rozliczone” i „Do akceptacji” jest.
Strona zlecenia w efenix bywa bez części pozycji wyceny: brak pozycji, w której Plik zbiorczy ma 0 albo pustą komórkę, nie przeszkadza, a brak pozycji, w której ma ilość, to błąd tego zlecenia.
_Avoid_: wpisywanie, import, synchronizacja

## Zlecenie rozliczone

Zlecenie Pliku zbiorczego, które w efenix ma status „Rozliczone”, a jego realizator i dane adresowe zgadzają się z `WYKONAWCA` i `ADRES`: firma już je rozliczyła z tatą.
Wycena w efenix go nie otwiera, niczego w nim nie zmienia i nie stawia mu Znacznika efenix.
Tata widzi je jako Rozliczone, osobno od gotowych, błędów i Ostrzeżeń Emmetta, a samo nie zmienia wyniku OK.
_Avoid_: zlecenie zamknięte, zlecenie zakończone

## Zlecenie przekazane

Zlecenie Pliku zbiorczego, które w efenix ma status „Do akceptacji”, a jego realizator i dane adresowe zgadzają się z `WYKONAWCA` i `ADRES`: przekazała je Wycena w efenix w trybie z Przekazaniem, wcześniejsze uruchomienie albo tata.
Wycena w efenix niczego w nim nie zmienia i stawia mu Znacznik przekazania.
Tata widzi je jako Przekazane, osobno od gotowych, Zleceń rozliczonych, błędów i Ostrzeżeń Emmetta, a samo nie zmienia wyniku OK.
_Avoid_: zlecenie zapisane, zlecenie zatwierdzone

## Wycena Emmetta

Ilości, które Emmett, skrypt w efenix, wpisuje do zlecenia po kliknięciu „Załaduj wycenę przygotowaną przez Emmetta”, zanim tata przeniesie do niego Ilości usług z Pliku zbiorczego.
Załadowanie Wyceny Emmetta czyści wycenę, którą zlecenie już ma, więc Wycena w efenix ładuje ją tylko do zlecenia bez żadnej ilości.
To kliknięcie otwiera najpierw okno z propozycją Emmetta, a do zlecenia wpisuje ją dopiero „Załaduj do zlecenia” w tym oknie.

## Ostrzeżenie Emmetta

Wynik zlecenia w Wycenie w efenix, w którym efenix ma w jakiejś pozycji więcej niż Plik zbiorczy, także gdy plik ma w niej 0 albo pozycja nie ma kolumny w pliku: od Emmetta, od taty albo z wcześniejszej wyceny.
Wycena w efenix tej ilości nie obniża ani nie czyści, a pozostałe ilości z pliku i tak wpisuje.
Ostrzeżenie podaje pozycję, jej kolumnę i obie ilości.
Zlecenie z Ostrzeżeniem Emmetta nie dostaje Znacznika efenix: tata poprawia Plik zbiorczy albo sam zmniejsza ilość w efenix.
Mniejsza ilość w efenix niż w pliku nie jest Ostrzeżeniem Emmetta, bo Wycena w efenix wpisuje w nią ilość z pliku.
_Avoid_: błąd Emmetta, konflikt z Emmettem, sprzeczność z Emmettem

## Znacznik efenix

Jasnofioletowe wypełnienie komórki `ADRES` zlecenia w Pliku zbiorczym: wycena tego zlecenia jest uzupełniona w efenix Ilościami usług z Pliku zbiorczego, jej kwota jest równa `Kwota` (AU), a Przekazanie do akceptacji należy do taty.
Nie jest Wyróżnieniem i nie przechodzi do Rozliczeń pracowników.
Nowy Plik zbiorczy ma `ADRES` bez wypełnienia, a żółte `ADRES` stawia tata, gdy zlecenie jest rozliczone z firmą.
Znacznika efenix Wycena w efenix nigdy nie stawia w miejsce Znacznika przekazania.
_Avoid_: kolor gotowości, zaznaczenie

## Znacznik przekazania

Ciemniejsze fioletowe wypełnienie komórki `ADRES` Zlecenia przekazanego w Pliku zbiorczym, które nie zaciemnia tekstu adresu.
Zastępuje Znacznik efenix tego zlecenia.
Tak jak Znacznik efenix nie jest Wyróżnieniem i nie przechodzi do Rozliczeń pracowników.
_Avoid_: ciemny Znacznik efenix, kolor przekazania

## Surowe zlecenia

Zlecenia, które tata albo jego pracownik wkleił z aplikacji firmowej na dół Rejestru zleceń, pod uporządkowane już dni, a których Uporządkowanie INTERMAX jeszcze nie uporządkowało.
Jedno wklejenie to zwykle zlecenia jednego dnia.
Mają wygląd z aplikacji.
Pierwszy wiersz wklejenia przychodzi przesunięty o dwie kolumny w lewo, ale zlecenia są Surowe także wtedy, gdy ktoś przesunął go już ręcznie.
W `CZYNNOŚCI` mają tylko nazwę operatora, a w `URZĄDZENIA` rodzaj zlecenia (instalacja, usterka); poza Wpisem urządzenia i czynności INTERMAX resztę dopisują ręcznie tata i pracownicy po Uporządkowaniu INTERMAX.
_Avoid_: eksport, nowe dane

## Uporządkowanie INTERMAX

Proces, który tata uruchamia w Centrum rozliczeń po wklejeniu Surowych zleceń dnia.
Przesuwa pierwszy wiersz na miejsce, gdy przyszedł przesunięty, dzieli zlecenia na segmenty Wykonawców w kolejności alfabetycznej, oddzielone jednym pustym wierszem, w segmencie układa je od najwcześniejszej godziny do najpóźniejszej i nadaje im od kolumny A do `UWAGI` wygląd reszty Rejestru zleceń z cienką ramką i pogrubionym tylko `WYKONAWCA`, Kolory operatora i Wpisy urządzenia i czynności INTERMAX, a kolumny z aplikacji za `UWAGI` usuwa.
Dzień stawia jeden pusty wiersz pod żółtym wierszem, którym tata oddziela dni, a bez niego 10 pustych wierszy pod ostatnim uporządkowanym zleceniem.
Po nim Rejestr otwiera się na dzisiejszym dniu z kalendarza, a gdy dziś nie ma zleceń, na ostatnim wcześniejszym dniu ze zleceniami.
Zmienia tylko Surowe zlecenia i widok po otwarciu.
Dnia, który już jest uporządkowany, nie porządkuje drugi raz; zlecenia dopisane później do takiego dnia wpisuje się ręcznie albo dopisuje je Wpisanie raportów (Zlecenie dopisane z raportu).
Porządkuje dzień, nie okres.
Po nim tata i pracownicy uzupełniają dzień ręcznie, a dopiero potem okres trafia do Przygotowania pliku zbiorczego.
_Avoid_: formatowanie, import

## Dzień uporządkowany

Dzień, którego zlecenia stoją w którymkolwiek arkuszu zleceń Rejestru zleceń z wyglądem uporządkowanego dnia: dwa kolejne uporządkowane wiersze z jego datą albo jeden, pod którym nie ma wiersza wcześniejszego dnia.
Zlecenie na jutro wpisane w środku dzisiejszego dnia nie czyni jutra uporządkowanym.
Dnia szuka się w każdym arkuszu od dołu w górę, aż 10 kolejnych uporządkowanych wierszy ma dzień wcześniejszy niż szósty dzień przed dzisiejszym (albo niż wklejony dzień, gdy jest wcześniejszy), więc znajduje się też dzień uporządkowany do przodu nad wcześniejszymi dniami.
Tą samą regułą Uporządkowanie INTERMAX odmawia drugiego wklejenia dnia, także do nowszego arkusza, a karta Uporządkowania INTERMAX w Centrum rozliczeń pokazuje przy dzisiejszym dniu i każdym z 6 dni przed nim, czy jest uporządkowany, a obok nich każdy późniejszy Dzień uporządkowany.
_Avoid_: dzień zrobiony, dzień sformatowany

## Kopia INTERMAX

Stan Rejestru zleceń zapisany przed Uporządkowaniem INTERMAX albo przed przywróceniem innej Kopii INTERMAX, nazwany datą i godziną, z której pochodzi.
Leży na komputerze taty poza OneDrive.
Tata przywraca ją z Centrum rozliczeń; zmiany późniejsze od niej wtedy znikają.
_Avoid_: backup, wersja

## Kolor operatora

Wypełnienie, które Uporządkowanie INTERMAX nadaje zleceniu po nazwie operatora w `CZYNNOŚCI`, a przy usterce po rodzaju zlecenia. `CZYNNOŚCI` i `NUMER UMOWY` dostają: T-Mobile zielony, Orange pomarańczowy, każdy inny operator jasny niebieski, a Netia ciemniejszy niebieski w `CZYNNOŚCI` i jasny niebieski w `NUMER UMOWY`.
INEA i zlecenie bez operatora zostają bez wypełnienia.
Nazwa operatora nie zależy od wielkości liter, spacji, myślników ani dopisku `S.A.`: `T-Mobile` to TMOBILE, a `Netia S.A.` to Netia.
Dopisek `S.A.` bez spacji przed nim, jak `NetiaSA` czy `NetiaS.A.`, też zostawia tego samego operatora (decyzja Maksa z 6.11.2026), a inne doklejone litery, jak `NetiaSAT`, dają innego operatora.
Usterka i usterka hurt mają zamiast tego różowe `URZĄDZENIA`.
W Rejestrze zleceń jest Wyróżnieniem jak każde inne; inne kolory w Rejestrze to ręczne zaznaczenia taty i jego pracowników.

## Wpis urządzenia i czynności INTERMAX

Wartości `URZĄDZENIA` i `CZYNNOŚCI`, które Uporządkowanie INTERMAX wpisuje Surowemu zleceniu z rodzajem `Instalacja Hurt` po nazwie operatora w `CZYNNOŚCI`, tej samej co przy Kolorze operatora: `URZĄDZENIA` zastępuje, a do nazwy operatora w `CZYNNOŚCI`, takiej jak z aplikacji, dopisuje czynność.
Netia, P4, Plus, VECTRA i SYSTEMIA dostają `nokia` i ` - akt pętli`, ORANGE `gniazdo` i ` - akt pętli LLU`, a TMOBILE `nokia getewayHomeBox` i ` - akt int`.
Usterki, instalacje ręczne, inne rodzaje zleceń i inni operatorzy, także INEA i OXYLION, zostają bez wpisu.
Zlecenie ORANGE, które okazało się BSA, tata i pracownicy poprawiają ręcznie na `nokia` i ` - akt pętli BSA`, tak jak dopisują `stb2`, `tv` czy `akt int` po wizycie.
_Avoid_: szablon, autouzupełnianie

## Zlecenie skuteczne

Zlecenie, którego wartość `SKUTECZNE` to `tak`, bez względu na wielkość liter i otaczające spacje.
Każde zlecenie skuteczne z Rozliczenia wewnętrznego trafia do Pliku zbiorczego.

## Zlecenie nieskuteczne

Zlecenie, którego wartość `SKUTECZNE` to `nie`, bez względu na wielkość liter i otaczające spacje.
Każde zlecenie okresu jest skuteczne albo nieskuteczne.
Puste `SKUTECZNE` albo inna wartość, na przykład `???` czy `tsk`, to brak w Rejestrze, który tata uzupełnia, a nie trzeci stan zlecenia.

## Raport wykonawcy

Mail, który Wykonawca wysyła ze swojego adresu na skrzynkę raportów taty, z tematem `Raport` i datą dnia zleceń, bez `Re:` ani `Fwd:` w temacie.
Temat wybacza wielkość liter, jedną literówkę w słowie `Raport` (`Rapotr`, `Rapor`), dowolną interpunkcję albo spację między dniem, miesiącem i rokiem oraz interpunkcję na końcu; inne słowa obok słowa i daty to błąd tematu.
Datę z rokiem pomylonym przez Wykonawcę (ponad 302 dni przed przyjściem maila albo ponad 62 dni po nim) Centrum czyta jako ten sam dzień i miesiąc w roku, w którym data leży w tych granicach.
Ma jeden albo więcej Wpisów raportu, niekoniecznie każdy w osobnej linii; mail bez żadnego Wpisu i mail ze zdjęciami do raportu (`Zdjęcia do raportu …`) nie jest Raportem wykonawcy.
Raport z błędem tematu (temat bez dnia albo z innymi słowami) jest przysłany za dzień z tematu, a bez niego za ostatni dzień Wykonawcy ze zleceniami bez raportu, nie późniejszy niż dzień przyjścia maila; tata widzi błąd przy tym dniu i wpisuje raport Wpisem na życzenie.
Raportem wykonawcy za dzień jest też odpowiedź Wykonawcy na Przypomnienie o raporcie za ten dzień i poprawka raportu: odpowiedź (`Re:`, `Odp:`) z tematem Raportu wykonawcy za ten dzień na początku i dowolnym dopiskiem po nim; jej Wpisami jest tylko tekst nad cytatem, bez numerów z przykładu w przypomnieniu.
Inne maile w tej skrzynce, także od Wykonawców z innym słowem w temacie (`Montaże 13.11.2026`), nie są Raportami wykonawcy.
_Avoid_: mail, raport (bez dopowiedzenia), sprawozdanie

## Wpis raportu

Część Raportu wykonawcy o jednym zleceniu: numer z `NUMER ZL.`, `tak` albo `nie` jak w `SKUTECZNE` i wykonane czynności albo powód nieskuteczności, słowa rozdzielone spacją, bez względu na wielkość liter.
Dotyczy zlecenia o tym numerze, a jego dzień i Wykonawca to dzień z tematu i nadawca raportu, także gdy Rejestr zleceń mówi inaczej.
Wyjątek: gdy w jednym raporcie co najmniej dwa Wpisy mają numery zleceń tego Wykonawcy z innego dnia niż dzień z tematu, temat jest pomyłką i te Wpisy dotyczą zleceń z ich dnia w Rejestrze.
Późniejszy Wpis raportu tego samego zlecenia, od tego samego albo innego Wykonawcy, wygrywa z wcześniejszym.
_Avoid_: linia raportu, Wpis urządzenia i czynności INTERMAX (to wpis Uporządkowania)

## Wpisanie raportów

Proces, który tata uruchamia na żądanie i który przenosi Wpisy raportu do uporządkowanych zleceń w Rejestrze zleceń: `tak` albo `nie` do `SKUTECZNE`, a czynności albo powód nieskuteczności do `CZYNNOŚCI ZREALIZOWANE`.
Raport wykonawcy jest ważniejszy od Rejestru w dniu i Wykonawcy zlecenia, więc Wpisanie raportów robi też Przeniesienie zlecenia i Zlecenie dopisane z raportu, a o każdej takiej zmianie i o temacie, który przegrał z Rejestrem, informuje tatę przy dniu Wykonawcy w widoku Raporty.
Zmienia tylko to, co jest puste albo co samo wcześniej zmieniło, a od tamtej pory nikt tego nie ruszył; ręczna wartość albo ręczna zmiana taty lub pracownika zawsze wygrywa.
Do `CZYNNOŚCI ZREALIZOWANE` wpisuje cały opis po `tak` albo `nie`, Kody czynności razem ze zwykłym opisem.
Wpis `tak` z Błędem opisu wpisuje jak każdy, a tata widzi przy nim problem w widoku Raporty.
Wpis z błędem, z którego Centrum wie, co wpisać, czeka na Wpis na życzenie.
Pisze tylko do zamkniętego Rejestru zleceń.
Za każdym razem czyta wszystkie Raporty wykonawców z dni od jego wdrożenia w okresach, które nie mają jeszcze Pliku zbiorczego; okres z Plikiem zbiorczym jest dla niego zamknięty.
Dzień zleceń jest uporządkowany, zanim Wykonawcy wyślą jego raporty, bo Uporządkowanie INTERMAX przygotowuje im dzień do pracy.
_Avoid_: import maili, synchronizacja

## Wpis na życzenie

Wpis raportu z błędem, który Wpisanie raportów samo pomija, a tata wpisuje do Rejestru zleceń jednym kliknięciem przy zleceniu w widoku Raporty, na swoją odpowiedzialność.
Jest tylko przy błędzie, przy którym wiadomo, co wpisać: błąd tematu (temat ze słowem raportu bez dnia albo z innymi słowami; wtedy dzień z tematu albo dzień, który Centrum wskazuje przy zleceniu, a numery zleceń dalej rozstrzygają jak przy pomylonym temacie i Przeniesieniu zlecenia) i `t`, `n`, `skuteczne` albo `nieskuteczne` zamiast `tak` albo `nie`.
W Rejestrze wygląda jak każdy Wpis, a późniejszy poprawny Wpis raportu wygrywa z nim.
_Avoid_: dopisanie ręczne, wymuszenie, Zlecenie dopisane z raportu (to zlecenie, którego nie było w Rejestrze)

## Przeniesienie zlecenia

Zmiana dnia albo Wykonawcy zlecenia w Rejestrze zleceń według Wpisu raportu: zlecenie dostaje dzień z tematu albo nadawcę raportu i trafia pod zlecenia tego Wykonawcy w tym dniu, w jego segmencie albo w nowym segmencie na jego miejscu w kolejności alfabetycznej.
Tak przechodzi zlecenie, które Wykonawca przejął od innego, albo wykonał innego dnia, niż mówi Rejestr.
Przenosi tylko do Dnia uporządkowanego, nie przenosi zlecenia do okresu ani z okresu, który ma Plik zbiorczy, ani z dnia po dziś, i nie przenosi zlecenia, którego numer Rejestr ma więcej niż raz w czytanych dniach, także w zleceniach na jutro; wtedy zostaje problem dla taty.
_Avoid_: korekta INTERMAX, poprawka daty

## Zlecenie dopisane z raportu

Zlecenie, które Wpisanie raportów dopisało do Rejestru zleceń, bo numeru z Wpisu raportu, w postaci numeru z aplikacji firmowej (8 cyfr), nie ma w żadnym wierszu, który Wpisanie raportów czyta w Rejestrze: ani w zleceniach na jutro, ani w Surowym zleceniu, ani w wierszu, z którego nie powstaje zlecenie (bez `WYKONAWCA`, z datą tekstem, wklejonym z aplikacji między uporządkowanymi), ani w wierszu z tygodnia przed pierwszym dniem otwartym, także sprzed dnia wdrożenia; numer z takiego wiersza to problem dla taty.
Stoi pod zleceniami nadawcy w dniu z tematu i ma tylko `NUMER ZL.`, dzień, `WYKONAWCA`, `SKUTECZNE` i `CZYNNOŚCI ZREALIZOWANE`; resztę uzupełnia tata, a widok Raporty przypomina mu o tym, dopóki zlecenie nie ma `ADRES`.
Nie powstaje, gdy temat raportu jest pomyłką, dzień z tematu nie jest Dniem uporządkowanym, Wykonawca poprawił raport późniejszym mailem bez tego numeru albo najpóźniejszy mail z tym numerem go nie dopisuje.
_Avoid_: nowe zlecenie, brakujące zlecenie

## Przypomnienie o raporcie

Mail ze skrzynki raportów taty do aktywnego Wykonawcy z Listy Wykonawców, który ma w Rejestrze zleceń zlecenia dnia, a nie przysłał jeszcze za ten dzień żadnego Raportu wykonawcy.
Raport, którego temat jest pomyłką, jest przysłany za dzień swoich zleceń z Rejestru.
Raport z błędem (w temacie albo we Wpisach) jest przysłany: Wykonawca nie dostaje za ten dzień przypomnienia, a błąd widzi tata przy zleceniu w widoku Raporty ([ADR 0041](docs/adr/0041-przypomnienie-tylko-bez-raportu.md)).
Prosi o raport za ten dzień, podaje wzór tematu i treści i kończy się stopką taty.
Idzie w porannej i wieczornej porze z Ustawień Centrum (domyślne pory i nadrabianie pominiętej: [ADR 0030](docs/adr/0030-przypomnienia-o-raporcie-z-centrum-w-autostarcie.md)), pierwsze od godziny pierwszego przypomnienia następnego dnia, najwyżej jedno w każdej porze, aż raport przyjdzie albo okres dnia dostanie Plik zbiorczy; nigdy poza porami i nigdy za dni sprzed wdrożenia przypomnień.
Każdy brakujący dzień ma własne przypomnienia.
_Avoid_: monit, ponaglenie

## Wysyłka rozliczeń

Wysłanie Rozliczeń pracowników okresu z Centrum rozliczeń, każdemu Wykonawcy jego własnego, jako Mail z rozliczeniem, na kliknięcie taty, dla wszystkich albo zaznaczonych plików ([ADR 0040](docs/adr/0040-wysylka-rozliczen-mailem-ze-skrzynki-raportow.md)).
Plik Wykonawcy idzie tylko na jego adresy z Listy Wykonawców, także Nieaktywnego, a pusty Szablon pracownika i plik bez Wykonawcy z Listy nie idą.
Co już poszło, wie folder „Wysłane” skrzynki raportów: plik wysłany i niezmieniony nie idzie drugi raz, a zmieniony po wysłaniu idzie tylko na ponowną prośbę taty.
_Avoid_: mailing, rozsyłka

## Mail z rozliczeniem

Mail ze skrzynki raportów taty do Wykonawcy z jego Rozliczeniem pracownika jako załącznikiem, z tematem i treścią z Ustawień Centrum i stopką taty.
Rozpoznaje się go w „Wysłanych” po nazwie pliku załącznika, a nie po temacie, więc także wtedy, gdy tata wysłał go ręcznie z tej skrzynki.
_Avoid_: mail z plikiem, wysyłka rozliczenia

## Rozliczenie wewnętrzne

Skoroszyt `Rozliczenie wew. {okres}.xlsx` zawierający wszystkie zlecenia jednego okresu rozliczeniowego z Rejestru zleceń, skuteczne i nieskuteczne, w kolejności z Rejestru, bez pustych wierszy.
Ma formatowanie Wzorca rozliczenia wewnętrznego, a zlecenia Wygląd Wiersza danych, do którego tata jest przyzwyczajony.

## Wzorzec

Każdy z trzech skoroszytów bazowych bez zleceń, z których powstają pliki nowego okresu: Wzorzec rozliczenia wewnętrznego, Wzorzec pliku zbiorczego i Wzorzec rozliczenia pracownika.
Jest jedynym źródłem szerokości kolumn plików, które z niego powstają, nie poprzedni okres.
Plik okresu otwiera się tak jak jego Wzorzec: w lewym górnym rogu arkusza, w powiększeniu 75%.
Wzorzec pozostaje niezmieniony.

## Wzorzec rozliczenia wewnętrznego

Wzorzec, z którego powstaje Rozliczenie wewnętrzne nowego okresu.

## Wzorzec pliku zbiorczego

Wzorzec, z którego powstaje Plik zbiorczy nowego okresu.
Zachowuje stawki, sumy, formuły i formatowanie; stawki ma własne, inne niż Wzorzec rozliczenia pracownika.

## Wzorzec rozliczenia pracownika

Wzorzec bez nazwy wykonawcy, z którego powstają Szablony pracowników.
Ma ten sam układ kolumn co Plik zbiorczy, ale własne stawki pracownika, i te same szerokości kolumn co Wzorzec pliku zbiorczego.
U taty to pusty plik `Rozliczenie {okres} -.xlsx` w Folderze rozliczeń pracowników.
Nie jest rozliczeniem konkretnej osoby.
_Avoid_: Placeholder

## Przygotowanie pliku zbiorczego

Proces poprzedzający Przebieg rozliczeń: z Rejestru zleceń tworzy Rozliczenie wewnętrzne okresu, a z jego zleceń skutecznych Plik zbiorczy z Ilościami usług wyznaczonymi przez Reguły ilości.
Nie zaczyna, gdy okres ma Surowe zlecenia.
Oba pliki powstają razem albo żaden.
Jedyny wyjątek: jeśli po nieudanym zapisie nie da się usunąć pliku, który już trafił do Folderu okresu, Zatrzymanie wskazuje ten plik.
Uruchamiany osobno od Przebiegu rozliczeń.

## Plik zbiorczy

Skoroszyt `Rozliczenie {okres} - zbiorcze.xlsx`: zlecenia skuteczne wszystkich wykonawców dla jednego okresu rozliczeniowego.
Jest wynikiem Przygotowania pliku zbiorczego i jedynym wejściem Przebiegu rozliczeń.

## Wykonawca

Osoba wskazana w kolumnie `WYKONAWCA` pliku zbiorczego.
Wartość w tej kolumnie jest identyfikatorem źródłowym, który nie musi być identyczny z nazwą człowieka w nazwie pliku docelowego.

## Lista Wykonawców

Część Ustawień Centrum: każdy Wykonawca z identyfikatorem z kolumny `WYKONAWCA` (H), nazwą w Rozliczeniu pracownika i adresami, z których wysyła Raporty wykonawcy.
Wspólna dla Przebiegu rozliczeń, Przygotowania pliku zbiorczego, Wpisania raportów, Przypomnień o raporcie i Wysyłki rozliczeń.
_Avoid_: Konfiguracja wykonawców, lista adresów Wykonawców, pracownicy

## Nieaktywny Wykonawca

Wykonawca z Listy Wykonawców, który już nie pracuje u taty: nie dostaje Przypomnień o raporcie, a okresy z jego zleceniami nadal się rozliczają i Wysyłka rozliczeń wysyła mu jego Rozliczenie pracownika.
Wykonawcy, którego identyfikator występuje w jakimkolwiek okresie, się nie usuwa, tylko oznacza jako nieaktywnego.
_Avoid_: usunięty Wykonawca, były pracownik

## Historia Ustawień

Każda zmiana Ustawień Centrum: kiedy, co i jaka była wartość przed i po, bez wartości sekretów.
Z niej tata cofa zmianę, a Zgłoszenie podaje zmiany z ostatnich 30 dni.
_Avoid_: log ustawień, dziennik konfiguracji

## Szablon pracownika

Skoroszyt przygotowany dla konkretnego wykonawcy na podstawie Wzorca rozliczenia pracownika.
Zachowuje jego strukturę, formuły, stawki i formatowanie; jedynie Wiersze danych mają Wygląd Wiersza danych oraz Wyróżnienia i Hiperłącza z Pliku zbiorczego.
Zawiera dane tylko z własnego okresu i może pozostać pusty, jeśli wykonawca nie ma wierszy w Pliku zbiorczym.

## Folder okresu

Folder o nazwie równej tokenowi okresu, wspólny dla wszystkich plików jednego okresu rozliczeniowego: Rozliczenia wewnętrznego, Pliku zbiorczego i Folderu rozliczeń pracowników.
Może istnieć wcześniej, zanim powstaną te pliki.
Folder, którego nazwa nie jest tokenem żadnego okresu (na przykład `09_15_09_2026`, bo 9 września 2026 to nie wtorek), nie jest Folderem okresu.

## Folder okresów

Folder, w którym narzędzie szuka Folderów okresu.
W układzie folderów taty to `Załączniki`, a Foldery okresu leżą w `Rozliczenia {rok}\{miesiąc}\INEA`.
Miesiąc to cykl rozliczeniowy taty, nie kalendarz, więc Folder okresu zakłada tata, a narzędzie go odszukuje.
Folder wskazany wewnątrz `Rozliczenia {rok}` (tydzień, `INEA` jednego miesiąca albo miesiąc) to ten sam układ liczony od `Załączniki`, więc Centrum rozliczeń zapisuje wtedy `Załączniki`.
Bez folderów `Rozliczenia {rok}` Foldery okresu leżą w folderze okresów bezpośrednio (np. `INEA`), a zapisuje się folder wskazany.

## Ustawienia Centrum

Wartości o pracy taty, które tata sam zmienia w Centrum rozliczeń, na przykład Rejestr zleceń i folder okresów.
Zmiana działa od razu, a Aktualizacja narzędzia jej nie nadpisuje.
Zachowanie narzędzia, które może zmienić tylko Maks, nie jest Ustawieniem Centrum.
_Avoid_: Ustawienia taty, Konfiguracja

## Folder rozliczeń pracowników

Folder danego okresu zawierający osobny skoroszyt dla każdego wykonawcy.

## Przygotowanie skoroszytów pracowników

Etap tworzenia plików nowego okresu przez skopiowanie Wzorca rozliczenia pracownika dla każdego wykonawcy.
Token okresu i nazwa wykonawcy trafiają do nazw folderu i plików; struktura, formuły, stawki i formatowanie Wzorca rozliczenia pracownika pozostają zachowane.

## Przetworzenie Szablonu pracownika

Obsłużenie jednego Szablonu pracownika w ramach przygotowania Rozliczeń pracowników.
Kończy się uzupełnieniem danych albo pozostawieniem pustego szablonu.
Gdy zapis nie jest bezpieczny, Przebieg rozliczeń się zatrzymuje i nie publikuje żadnego Rozliczenia pracownika.

## Rozliczenie pracownika

Szablon pracownika uzupełniony wierszami tego wykonawcy z danego okresu, bez Ilości tylko dla INEA, z pustym Czerwonym polem i 1 w Zielonym polu.
Plik jest identyfikowany nazwą `Rozliczenie {okres} - {nazwa wykonawcy}.xlsx`; `{okres}` to token okresu rozliczeniowego.

## Wiersz danych

Wiersz pod nagłówkiem z danymi wejściowymi pracy: w Pliku zbiorczym, Szablonach pracowników i ich Wzorcach od 18. w dół, w Rozliczeniu wewnętrznym od 2.; wiersz Rejestru zleceń ze zleceniem staje się Wierszem danych obu plików okresu.
Formuły i techniczne wartości szablonu nie są same w sobie wierszami danych.

## Wygląd Wiersza danych

Wygląd każdej komórki zapisanego Wiersza danych w kolumnach A:M Rozliczenia wewnętrznego i A:L Pliku zbiorczego oraz Rozliczenia pracownika, taki jak w plikach, które tata robił ręcznie: krój i rozmiar czcionki nagłówka tej kolumny we wzorcu, Wyróżnienia, wyrównanie do lewej i do środka wysokości, zawijanie tylko tekstu z końcem linii, cienkie obramowanie z czterech stron i format liczby komórki, z której pochodzi wartość.
Wiersz nie ma stałej wysokości.
Resztki formatowania wzorca w tych komórkach nie zostają; kolumny dalej mają wygląd wzorca.
_Avoid_: styl wiersza, formatowanie wiersza

## Ilości usług

Liczby w kolumnach `N:AP` Wiersza danych: ile razy przy zleceniu płatna jest dana pozycja cennika.
W Pliku zbiorczym płaci ją tacie INEA, a w Rozliczeniu pracownika tata Wykonawcy.
Wartość pozycji to jej ilość razy koszt z wiersza 14 tego pliku.
Dodatek 45 zł za usterkę po 17:00 albo w sobotę tata zapisuje jako ilość 45 w pozycji o koszcie 1 zł.
_Avoid_: cyfry, zera i jedynki, kolumny

## Ilości tylko dla INEA

Ilości usług z Pliku zbiorczego, które INEA płaci tacie, a Wykonawca ich nie wykonuje, więc nie przechodzą do Rozliczenia pracownika, np. `AP` w zleceniu z `gniazdo` w `URZĄDZENIA`, bez względu na liczbę.
Wyznacza je Reguła ilości, którą tata ustawia jak każdą inną; Zielone pole nie jest Ilością tylko dla INEA.
_Avoid_: kasowanie jedynek, usuwanie cyfr

## Czerwone pole

Komórka Ilości usług albo `AS` Wiersza danych Pliku zbiorczego z jednolitym czerwonym wypełnieniem (`FFFF0000`), które kładzie Legenda czynności albo tata: pozycja, za którą płaci INEA, a nie Wykonawca, np. `AS` z 70 przy `spawpg`.
W Rozliczeniu pracownika jest puste i bez wypełnienia, więc białe, bez względu na to, co w nim stoi; Plik zbiorczy zostaje bez zmian.
Czerwone wypełnienie w innych kolumnach, np. znacznik taty w `ADRES` albo `URZĄDZENIA`, nie jest Czerwonym polem i przechodzi jak każde Wyróżnienie.
_Avoid_: kolor INEA, czerwona komórka

## Zielone pole

Komórka Ilości usług albo `AS` Wiersza danych Pliku zbiorczego z jednolitym zielonym wypełnieniem (`FF92D050`), które kładzie Legenda czynności albo tata, zwykle bez liczby: pozycja, którą dostaje Wykonawca, a INEA za nią nie płaci, np. `AF` przy `rt2`.
W Rozliczeniu pracownika ma 1 zamiast tego, co w nim stoi, i jest bez wypełnienia, więc białe, także gdy Reguła ilości zostawia tę komórkę pustą; Hiperłącze zostaje przy wartości. Plik zbiorczy zostaje bez zmian.
Zielone wypełnienie w innych kolumnach, np. znacznik taty w `ADRES`, nie jest Zielonym polem i przechodzi jak każde Wyróżnienie.
_Avoid_: kolor pracownika, zielona komórka

## Reguły ilości

Zasady taty, które z treści zlecenia (`UMOWA`, `URZĄDZENIA`, `CZYNNOŚCI`, `DATA`) wyznaczają Ilości usług.
Są Ustawieniem Centrum: tata tworzy je i zmienia sam, każdą jako „jeśli … to …”.
Ilości wynikające z opisu technika (`CZYNNOŚCI ZREALIZOWANE`) nie są Regułami ilości: wyznacza je Legenda czynności albo wpisuje tata.
_Avoid_: scenariusze rozliczeń, instrukcja

## Legenda czynności

Kody czynności, które tata ustala dla Wykonawców, każdy z tym, co wyznacza w Pliku zbiorczym.
Jest Ustawieniem Centrum, które tata zmienia sam, i wyznacza Ilości usług z Kodów czynności w opisie technika (`CZYNNOŚCI ZREALIZOWANE`), gdy opis nie ma Błędu opisu; zwykły opis obok kodów niczego nie wyznacza.
_Avoid_: skróty, słownik czynności, legenda (bez dopowiedzenia)

## Kod czynności

Słowo z Legendy czynności, które Wykonawca pisze w Wpisie raportu obok zwykłego opisu albo bez niego, np. `inst20m` albo `spawpg`, w jednym z jego zapisów, bez względu na wielkość liter.
Wyznacza w Pliku zbiorczym Ilość usług w kolumnie, kwotę w `AS` (Uwagi - kwota), Wyróżnienie albo kilka z nich naraz; kwoty kilku kodów w zleceniu się sumują.
Liczba w kodzie albo nie ma znaczenia (`inst20m` i `inst35m` to ten sam kod), albo przedziałem wybiera kolumnę (`instutp12m` daje `AL`, `instutp20m` daje `AJ`).
_Avoid_: skrót, kod (bez dopowiedzenia)

## Błąd opisu

`CZYNNOŚCI ZREALIZOWANE` z Kodami czynności, których legenda nie może przyjąć: kod z liczbą spoza przedziałów, kolumna Ilości usług trafiona drugi raz albo kolumna wypełniona dwoma kolorami (jeden kod robi z niej Czerwone pole, a drugi Zielone pole).
Słowo, które nie jest zapisem kodu, to zwykły opis technika, a nie Błąd opisu: obok kodów zwykły opis jest dozwolony.
Opis z Błędem opisu nie wyznacza niczego, a Raport wykonawcy z takim Wpisem `tak` jest przysłany: błąd widzi tata przy zleceniu w widoku Raporty, a Wykonawca nie dostaje przypomnienia.
W szczegółach dnia tata widzi przy zleceniu `tak`, które słowa opisu są Kodami czynności, a przy zleceniu `tak` bez żadnego kodu informację „BRAK KODU”; brak kodu nie jest Błędem opisu.
_Avoid_: zły kod, literówka

## Lista Urządzeń

Składniki kolumny `URZĄDZENIA`, które znają Reguły ilości, każdy z innymi zapisami tej samej rzeczy (np. `zyxel` i `gateway`, albo `usterka`, `usterka hurt` i `usterka wew`) i grupą (router, TV, extender).
Część Ustawień Centrum.
Składnik spoza Listy Urządzeń to nieznane `URZĄDZENIA`: działają wtedy tylko reguły z zakresem „składnik spoza listy” albo „każde zlecenie”.
_Avoid_: słownik, aliasy

## Wpis narzędzia

To, co Przygotowanie pliku zbiorczego wpisuje w Wiersz danych Pliku zbiorczego z Reguł ilości i Legendy czynności: Ilości usług w `N:AP` (reguły i legenda razem), kwota w `AS`, Wyróżnienia legendy oraz kolumny, które narzędzie w tym wierszu wyznacza.
Kontrola ilości porównuje z nim wpis taty, a Ilości do uzupełnienia to miejsca poza nim.
_Avoid_: wynik wiersza, decyzja (Decyzja taty to co innego)

## Ilości do uzupełnienia

Ilości usług w Pliku zbiorczym, których Reguły ilości nie wyznaczają, więc wpisuje je tata: w wierszu bez reguły (nieznane `URZĄDZENIA`, reguły dały najwyżej V, T i N), w wierszu z opisu (prewencja, niedostępność usług albo puste `URZĄDZENIA`, reguły nie dały nic) i w kolumnach z opisu technika w każdym wierszu, którego `CZYNNOŚCI ZREALIZOWANE` nie mają żadnego Kodu czynności albo mają Błąd opisu.
To miejsca zostawione tacie, nie błędy taty.
_Avoid_: błędy, braki, cyfry do wpisania

## Zlecenie ze zdjęciami

Zlecenie Pliku zbiorczego z wartością inną niż 0 w którejkolwiek z kolumn AB, AC, AD, AE, AF, AJ–AP albo AS: płatna czynność, którą firma rozlicza tylko ze zdjęciem spełniającym jej kryteria (np. otwarte gniazdo spawne z widocznymi śrubkami).
Tata sprawdza zdjęcia, zanim wyceni takie zlecenie w efenix; gdy zdjęcie nie spełnia kryteriów, firma odsyła je z pytaniami.
Usterka (ilość w `AI`) nie jest Zleceniem ze zdjęciami: usterek nie wycenia się w efenix.
_Avoid_: zlecenie z cyfrą, zlecenie dodatkowo płatne

## Uzupełnienie pliku zbiorczego

Etap między Przygotowaniem pliku zbiorczego a Przebiegiem rozliczeń: tata wpisuje w Excelu Ilości do uzupełnienia.
Kończy go Gotowość.
_Avoid_: uzupełnienie Excela, poprawki

## Wyróżnienie

Wygląd komórki, którym tata, jego pracownik, Uporządkowanie INTERMAX (Kolor operatora) albo Legenda czynności zaznacza zlecenie: kolor wypełnienia, kolor czcionki, pogrubienie i kursywa.
Przechodzi razem z wartością z Rejestru zleceń do plików okresu, a z Pliku zbiorczego do Rozliczeń pracowników, poza wypełnieniem Czerwonego pola i Zielonego pola, które w Rozliczeniu pracownika staje się białe (ADR 0039).
Wyróżnienia zastępują wygląd komórki wzorca w całości: komórka bez Wyróżnień daje komórkę bez wypełnienia, z kolorem automatycznym, bez pogrubienia i bez kursywy.
Krój i rozmiar czcionki nie są Wyróżnieniem i pochodzą z wzorca (Wygląd Wiersza danych).
_Avoid_: formatowanie (szersze: obejmuje też krój, obramowania i formaty liczb)

## Hiperłącze

Adres poza skoroszytem, który komórka otwiera po kliknięciu, np. numer zlecenia w `NUMER ZL.` prowadzący do zlecenia w aplikacji firmowej.
Przechodzi razem z wartością komórki z Rejestru zleceń do plików okresu, a z Pliku zbiorczego do Rozliczeń pracowników, i zastępuje hiperłącze komórki wzorca: komórka bez Hiperłącza daje komórkę bez hiperłącza.
Komórka bez wartości nie niesie Hiperłącza.
Odnośnik do miejsca w tym samym skoroszycie (np. do innego arkusza) nie jest Hiperłączem i nie przechodzi.
Hiperłącze nie jest Wyróżnieniem i nie zmienia wyglądu komórki.
Adres jest treścią wiersza: nie trafia do Komunikatów, Zdarzeń przebiegu, metryk ani Zgłoszeń.
_Avoid_: link, odnośnik

## Gotowość

Świadoma decyzja taty, że plik zbiorczy jest zakończony i można przygotować rozliczenia pracowników.
Tata potwierdza ją uruchomieniem procesu; Centrum nie zgaduje jej z samego zapisu pliku.

## Status okresu

Etap okresu rozliczeniowego wynikający z plików w jego Folderze okresu: Brak plików okresu, gdy nie ma Pliku zbiorczego; Plik zbiorczy przygotowany, gdy jest Plik zbiorczy, ale nie ma Folderu rozliczeń pracowników; Rozliczenia pracowników gotowe, gdy jest Folder rozliczeń pracowników.
Nie zastępuje Gotowości: Plik zbiorczy przygotowany nie znaczy, że tata go zakończył.

## Droga okresu

Kroki okresu rozliczeniowego po kolei: Plik zbiorczy, Uzupełnienie w Excelu, Wycena w efenix i Rozliczenia pracowników.
Plik zbiorczy i Rozliczenia pracowników są zrobione według Statusu okresu, Uzupełnienie w Excelu, gdy Historia ma Wycenę w efenix tego okresu albo są Rozliczenia pracowników, a Wycena w efenix, gdy ostatnie jej Uruchomienie procesu tego okresu w Historii skończyło się wynikiem OK; Wymaga sprawdzenia i Zatrzymanie zostawiają ją w toku.
Historia ma tylko skończone Uruchomienia, więc Wycena, która jeszcze trwa, niczego w Drodze okresu nie zmienia.
Następny krok to pierwszy niezrobiony, ale Przebieg rozliczeń nie czeka na Wycenę w efenix, tylko stoi po niej.
Okres z Rozliczeniami pracowników jest zamknięty także bez zaliczonej Wyceny w efenix, która wtedy zostaje niezrobiona.
Droga okresu nie zmienia Statusu okresu.
_Avoid_: ścieżka okresu

## Przebieg rozliczeń

Jedno uruchomienie procesu od wskazania Pliku zbiorczego do wyniku końcowego albo bezpiecznego przerwania.
Obejmuje Przygotowanie skoroszytów pracowników, a następnie ich uzupełnienie danymi z Pliku zbiorczego.

## Uruchomienie procesu

Jedno uruchomienie Przebiegu rozliczeń, Przygotowania pliku zbiorczego, Uporządkowania INTERMAX, Wyceny w efenix albo Wpisania raportów z Centrum rozliczeń albo ze Skryptu dla maszyn, od gotowych plików (i okresu, gdy proces go ma) do wyniku końcowego.
Decyzja taty należy do Uruchomienia procesu bez względu na to, skąd wystartowało.
Kończy się sukcesem, wynikiem wymagającym sprawdzenia albo Zatrzymaniem z bezpiecznym Komunikatem zrozumiałym dla taty, nigdy z treścią błędu technicznego.
_Avoid_: Przebieg (zarezerwowany dla Przebiegu rozliczeń)

## Kontekst Uruchomienia

To, co gospodarz Uruchomienia procesu (Centrum rozliczeń, Skrypt dla maszyn, odtworzenie z Logów) daje silnikowi każdego procesu obok jego wejścia, w tym jedyną drogę do plików taty i zegar Uruchomienia.
Zegar Uruchomienia stoi, gdy proces czeka na tatę (Decyzja taty, logowanie w efenix), więc ten czas nie wlicza się ani do czasów etapów, ani do `Czas uruchomienia`.
Zależność jednego procesu (okno efenix, folder Kopii INTERMAX) nie należy do Kontekstu, tylko do wejścia procesu.
_Avoid_: ustawienia Uruchomienia, środowisko

## Ustawienia ze startu

Ustawienia Centrum, którymi liczy jedno Uruchomienie procesu, w chwili jego startu: Lista Wykonawców, Reguły ilości i Legenda czynności.
Proces mówi, którymi z nich liczy, w swoich potrzebach, a Uruchomienie procesu, który danym Ustawieniem nie liczy, nie ma go ani w wejściu, ani w Logach Uruchomienia.
Skąd bierze je każdy gospodarz Uruchomienia (Centrum rozliczeń, Skrypt dla maszyn, odtworzenie z Logów), mówi jeden opis: `process_kind.Start`.
Zmiana Ustawień w trakcie Uruchomienia ich nie zmienia (ADR 0032).
_Avoid_: fakty startu (to fakty o tym, jak wystartowało Uruchomienie), ustawienia Uruchomienia

## Decyzja taty

Pytanie, które proces zadaje tacie w trakcie Uruchomienia procesu; dziś tylko o niepełny okres w Przygotowaniu pliku zbiorczego.
Składa ją proces i sam zatrzymuje się po odmowie; rozmówca tylko pyta i mówi, jak wyrazić zgodę (`Kontynuuj` w Centrum rozliczeń).
Odmowa kończy Uruchomienie procesu Zatrzymaniem po odmowie w Decyzji taty.
Skrypt dla maszyn zawsze odmawia.
Czas czekania na Decyzję taty nie wlicza się do `Czas uruchomienia` ani do metryk.

## Centrum rozliczeń

Lokalna aplikacja w przeglądarce na komputerze taty, z której uruchamia Uporządkowanie INTERMAX, Przygotowanie pliku zbiorczego, Przebieg rozliczeń, Wycenę w efenix i Wpisanie raportów, przywraca Kopię INTERMAX oraz widzi Status okresu każdego okresu i historię Uruchomień procesu.
Jest jedynym wejściem taty do tych procesów, nie osobnym procesem.
_Avoid_: dashboard, panel, centrum dowodzenia

## Katalog procesów

Jeden wpis na każdy proces, który uruchamia Centrum rozliczeń: nazwa i widok Uruchomienia procesu, Ustawienia Centrum, bez których proces nie startuje, czytane Wzorce i sprawdzenia Diagnozy w kolejności wyjaśniania.
Diagnoza, Logi Uruchomienia, Metryki i okno Ustawień pytają wpis procesu, zamiast rozróżniać procesy same; pliki procesu wynikają z jego Ustawień Centrum i Wzorców.
_Avoid_: rejestr procesów, lista procesów

## Skrypt dla maszyn

Jedyne wejście do procesów spoza Centrum rozliczeń, dla testów, pomiarów czasu i osoby utrzymującej narzędzie.
Przyjmuje parametrami pliki i okres, gdy proces go ma, a Wycena w efenix także adres efenix (w testach Atrapy efenix), z nikim nie rozmawia i oddaje wynik w kształcie karty Uruchomienia.
Jego Uruchomienia procesu mają w historii Centrum odznakę `.cmd`, tę samą co stare Uruchomienia z dawnych launcherów.
_Avoid_: CLI, launcher

## Zdarzenie przebiegu

Bezpieczny fakt opisujący zmianę lub wynik jednego Uruchomienia procesu, na przykład rozpoczęcie etapu, zakończenie etapu albo przerwanie etapu.
Każdy proces przechodzi te same etapy: Sprawdzanie, Odczyt danych, Planowanie i Zapisywanie.
Tylko Przebieg rozliczeń zgłasza też rozpoczęcie i zakończenie przetwarzania Szablonu pracownika.
Zdarzenie nie zawiera adresów klientów, numerów zleceń ani treści wierszy.

## Komunikat

Bezpieczny tekst dla taty w trzech częściach: Co się stało, Gdzie, Co zrobić.
Trzy części nie zawierają pełnych ścieżek, treści wyjątków, adresów ani treści wierszy; wskazują tylko nazwę pliku, folder, arkusz, kolumnę, wiersz albo Wykonawcę.
Jedynym wyjątkiem jest Zatrzymanie o brakach w `SKUTECZNE`: pokazuje dokładną zawartość komórki innej niż `tak` i `nie`, żeby tata od razu widział, co poprawić.
Komunikat niesie Zatrzymanie, ostrzeżenie, problem z podsumowania albo problem startu Centrum rozliczeń.
Jego kod jest unikalny w obrębie procesu.
_Avoid_: błąd, wiadomość

## Zatrzymanie

Zakończenie Uruchomienia procesu bez wyniku, z jednym Komunikatem: własne zatrzymanie procesu (np. Nienadpisywanie) albo nieoczekiwany wyjątek, także po zakończeniu zapisu.
_Avoid_: przerwanie, awaria, błąd

## Nieoczekiwany wyjątek

Zatrzymanie, którego przyczyną jest wyjątek w kodzie narzędzia, a nie reguła procesu.
Tata dostaje ogólny Komunikat; typ wyjątku i ślad wywołań trafiają tylko do Zgłoszenia i Logów Uruchomienia.
_Avoid_: nieoczekiwany błąd, crash

## Rodzaj Zatrzymania

Kto usuwa przyczynę Zatrzymania: „dla taty”, gdy Komunikat mówi, co zrobić, albo „do Maksa”, gdy bezwarunkowo każe przekazać go osobie utrzymującej narzędzie.
Nieoczekiwany wyjątek jest zawsze „do Maksa”.
Powtórka zmienia Zatrzymanie „dla taty” w takie, przy którym Centrum proponuje Diagnozę.
Zatrzymanie po odmowie w Decyzji taty rekord metryk zapisuje jako „dla taty”, ale nigdy nie jest Powtórką ani nie ma Diagnozy.
Rekord metryk zapisuje rodzaj bez Powtórki, a Historia i karta wyniku pokazują jako błąd tylko Zatrzymanie „do Maksa”: Zatrzymanie „dla taty” jest do poprawy, a po odmowie w Decyzji taty neutralne.

## Powtórka

Następne Uruchomienie procesu tego samego procesu, które kończy się Zatrzymaniem o tym samym odcisku problemu co poprzednie.
Centrum pamięta poprzednie Zatrzymanie tylko do swojego zamknięcia.

## Odcisk problemu

Tożsamość problemu: proces, kod Komunikatu i jego trzy części.
Proces należy do odcisku, bo kody Komunikatów są unikalne tylko w obrębie procesu.

## Diagnoza

Sprawdzenie tylko do odczytu, które tata uruchamia w Centrum rozliczeń przy Zatrzymaniu „do Maksa” albo Powtórce; przy nieoczekiwanym wyjątku zaczyna się sama.
Ustala przyczynę na komputerze taty i wyjaśnia ją w trzech częściach, jak Komunikat.
Niczego nie zmienia ani nie naprawia.

## Zgłoszenie

Komunikat Zatrzymania razem z wynikiem Diagnozy, wysłany z Centrum rozliczeń do Maksa.
Jeden odcisk problemu ma najwyżej jedno otwarte Zgłoszenie: Zgłoszenie, którego odcisk ma już otwarte, trafia do niego jako komentarz „Zgłoszenie wróciło” z całą swoją treścią.
Takie Zgłoszenie powrotu problemu idzie do Kolejki wysyłki samo po Diagnozie Zatrzymania, raz na Uruchomienie procesu, a tata widzi tylko, że Zgłoszenie czeka na naprawę.
Gdy Maks je zamknie, a problem wraca, powstaje nowe z odnośnikiem do poprzedniego.

## Logi Uruchomienia

Pełny, bezpieczny obraz jednego Uruchomienia procesu z Centrum rozliczeń: wynik, Komunikaty, podsumowanie, przebieg etapów i Szablonów pracownika z godziną każdego kroku, wersja narzędzia, Kopia wejścia oraz dziennik działań taty w Centrum od poprzedniego Uruchomienia (widoki i przyciski z godzinami, bez treści Uwagi taty).
Logi Wyceny w efenix mają też odczyt strony efenix po każdym szukaniu, otwarciu zlecenia i zapisie, a z danych adresowych tylko nazwy części adresu, którymi wynik szukania różni się od `ADRES`, bez ich wartości; zrzutów ekranu nie mają.
Mówią wprost, czy był to podgląd, w którym nic nie zapisano, czy Uruchomienie z zapisem, a Logi Wyceny w efenix także jej tryb.
Zostają na komputerze taty także po zamknięciu Centrum i trafiają same do Skrzynki Zgłoszeń, gdzie wszystkie Uruchomienia jednego okresu są w jednym miejscu; Uruchomienie Uporządkowania INTERMAX jest tam przy okresie dnia, w którym tata je uruchomił.
Niosą tylko to, na co pozwala Reguła danych.
Tata ich nie wysyła ani nie ogląda, ale z nich wraca karta Uruchomienia po starcie Centrum i w Historii.
W trakcie Wyceny w efenix ten sam komentarz Uruchomienia w Skrzynce pokazuje co 5 minut jej postęp z dziennika Wyceny w efenix, a na końcu staje się podsumowaniem Logów, a gdy Centrum zamknęło się w jej trakcie, podsumowaniem Logów Urwanego Uruchomienia z następnego startu.
Wycena, której Logi z wynikiem nie doszły do kolejki, ma po następnym starcie wersję zastępczą, która Logów z wynikiem w Skrzynce nie zastępuje (ADR 0015, dopiski #846 i #910; ADR 0017, dopisek #910).
_Avoid_: Zgłoszenie (to Zatrzymanie z Diagnozą), dziennik Centrum, raport

## Kopia wejścia

Część Logów Uruchomienia: Wiersze danych, które Uruchomienie procesu przeczytało z plików taty, i odcisk każdego z tych plików, żeby Maks mógł odtworzyć Uruchomienie na tych samych danych.
Przygotowanie pliku zbiorczego ma w niej zlecenia Rejestru zleceń, które przeczytało dla okresu, a Przebieg rozliczeń i Wycena w efenix Wiersze danych Pliku zbiorczego (Wycena z wartościami, które policzył Excel, także `Kwota`), a Uporządkowanie INTERMAX wklejone wiersze z dołu każdego arkusza zleceń, które przetwarzało (nie cały Rejestr zleceń), w kolumnach od A do `UWAGI` i w położeniu, w którym czyta je Planowanie (ADR 0025, „Położenie wiersza”), a nad wklejeniem tylko numery ostatniego uporządkowanego i żółtego wiersza, od których Planowanie liczy wiersz dnia.
Wpisanie raportów ma w niej uporządkowane wiersze z dni od pierwszego dnia otwartego (od dnia wdrożenia, bez okresów z Plikiem zbiorczym przed nim), które przeczytało, w kolumnach od A do `UWAGI`, a Wpisy raportu, bez adresów, tematów i reszty treści maili, ma w swoim polu Logów, bo Kopia wejścia obejmuje tylko skoroszyty.
Według Reguły danych Kopia nie ma kolumn `ADRES` i `NUMER UMOWY/ZLECENIA ORANGE` (w Pliku zbiorczym kolumn B i I, także pod innym nagłówkiem), a wolny tekst i liczby ma po maskowaniu.
Odcisk to rozmiar i skrót bajtów, z których proces przeczytał plik, i chwila zmiany pliku tuż przed odczytem, więc Maks wie, czy jego kopia pliku jest tą samą wersją.
Plik ma w Kopii nazwę i nazwy dwóch folderów nad nim, bez pełnej ścieżki: Komunikaty Pliku zbiorczego pokazują oba, a Komunikaty INTERMAX tylko folder pliku.
Wyglądu komórek (Wyróżnień, formatu liczby, Hiperłączy) Kopia nie ma, bo proces tylko przenosi go do plików, które tworzy.
_Avoid_: zrzut pliku, kopia pliku taty (to cały plik, a Kopia wejścia ma tylko przeczytane wiersze)

## Urwane Uruchomienie

Uruchomienie procesu z Centrum rozliczeń, które nie doszło do wyniku, bo Centrum zamknęło się w jego trakcie.
Nie ma rekordu metryk; Centrum nazywa je po następnym starcie i radzi, co sprawdzić.
Urwana Wycena w efenix ma Logi Uruchomienia, które następny start Centrum zamyka z dziennika Wyceny w efenix, pisanego od jej startu zlecenie po zleceniu, i wysyła jak zwykłe Logi: zlecenia skończone przed zamknięciem Centrum i zlecenie zaczęte bez wyniku, a karta po starcie pokazuje te zlecenia.
Urwane Uruchomienie innego procesu Logów nie ma.
Uruchomienie, którego wynik jest już w Historii, a Logów nie ma (Centrum zamknęło się tuż po wyniku), nie jest urwane: karta po starcie pokazuje jego wynik z Historii, także gdy wiersz nie ma jeszcze identyfikatora Uruchomienia.
Wyjątek to Wycena w efenix, którą Centrum zamknęło przed wpisem końca jej dziennika: start zamyka ją jako Urwaną Wycenę z Logami Urwanego Uruchomienia.
_Avoid_: Zatrzymanie (kończy się Komunikatem procesu), przerwane (tak Metryki nazywają Zatrzymania)

## Uwaga taty

Własny tekst taty do Maksa z tytułem, który tata pisze z dowolnego widoku Centrum rozliczeń i przed wysłaniem do Skrzynki Zgłoszeń widzi w całości.
Powiadomienia nazywają ją tym tytułem, nie numerem.
Jest ogólna, o całym narzędziu, albo przypięta do jednego Uruchomienia procesu, i wtedy prowadzi do jego Logów Uruchomienia.
Każda Uwaga taty to osobna sprawa, którą Maks zamyka.
_Avoid_: Zgłoszenie (to Zatrzymanie z Diagnozą), feedback, komentarz

## Skrzynka Zgłoszeń

Miejsce, do którego trafiają Zgłoszenia, Kontrole ilości, Logi Uruchomienia i Uwagi taty i w którym Maks je zamyka: prywatne repozytorium Zgłoszeń.
_Avoid_: issue tracker, publiczne issue

## Reguła danych

To, co z treści plików taty może wyjść z jego komputera do Skrzynki Zgłoszeń, jedno dla Logów Uruchomienia, Zgłoszeń, Kontroli ilości i Uwag taty (ADR 0025): nigdy wartości `ADRES` ani `NUMER UMOWY/ZLECENIA ORANGE` ani dane adresowe z efenix, każda inna kolumna wiersza może.
W wolnym tekście telefony są `[telefon]`, a ulice `[ulica]`.
Przed zapisem Logów i każdą wysyłką strażnik maskuje każdą zakazaną wartość z przeczytanych plików i dopisuje uwagę techniczną z kolumną i miejscem, bez wartości.
Położenie, w którym strażnik zna każdy wiersz Rejestru zleceń, ustala sekcja „Położenie wiersza” tego ADR.
_Avoid_: reguła prywatności (dawne listy pól każdej wysyłki), anonimizacja

## Ślad przesunięcia

Data z godziną dwie kolumny na lewo od `DATA GODZ. POCZ.` (u taty w kolumnie A bez nagłówka) w wierszu Rejestru zleceń, który nie jest pierwszym wierszem bloku wklejenia.
Wiersz na miejscu u taty jej tam nie ma (kolumna A Rejestru jest pusta, a Uporządkowanie ją czyści), a przesunięty wiersz z aplikacji ma tam swoją datę.
Przesunięty przychodzi tylko pierwszy wklejony wiersz, więc ślad znaczy, że ten fakt nie zaszedł: reguła danych zna taki wiersz w obu położeniach, a Logi Uruchomienia mają o nim uwagę „Fakt domeny złamany”.
_Avoid_: niepewny wiersz, wiersz bez pewnego położenia

## Token do Zgłoszeń

Token, którym Centrum rozliczeń wysyła do Skrzynki Zgłoszeń.
Wpisuje go Maks na komputerze taty, a tata go nie widzi.
Może go brakować albo Skrzynka może go odrzucić; wtedy nic nie wychodzi, dopóki Maks go nie naprawi, a tata widzi, że Token do Zgłoszeń nie działa i ma skontaktować się z Maksem.
Tym samym tokenem Centrum pyta publiczne repozytorium narzędzia o Wydania (ADR 0014); gdy GitHub go tam nie przyjmie, Centrum pyta bez niego, a Token do Zgłoszeń dalej działa.
_Avoid_: klucz, hasło

## Kolejka wysyłki

Miejsce na komputerze taty, w którym Zgłoszenia, Uwagi taty, Logi Uruchomienia i Kontrole ilości czekają, aż przyjmie je Skrzynka Zgłoszeń.
Bez internetu wychodzą same, gdy sieć wróci, a bez działającego Tokenu do Zgłoszeń, gdy Maks go naprawi.
Każda wysyłka trafia do Skrzynki dokładnie raz, także gdy Centrum zgaśnie albo połączenie się zerwie, zanim kolejka zapisze, że ją dostarczyła (ADR 0015, dopisek #840).
Nowsza wersja tej samej wysyłki, jak Logi Uruchomienia po Diagnozie albo po postępie Wyceny w efenix, zmienia jej komentarz zamiast dokładać nowy, a gdy starsza jeszcze czeka, zastępuje ją w kolejce, więc bez internetu czeka tylko najnowsza.
Starsza, która dojdzie po nowszej, niczego w Skrzynce nie zmienia.
Która wersja jest nowsza, mówi najpierw jej stopień, który wybiera nadawca, a nie zegar komputera (ADR 0015, dopisek #910).
Treść, którą Skrzynka odrzuciła, zostaje w niej do następnego startu Centrum rozliczeń; tata ma wtedy skontaktować się z Maksem.
Plik w Archiwum Logów okresu też idzie dokładnie raz, a plik nowszej wersji podmienia plik starszej.
_Avoid_: outbox, bufor

## Archiwum Logów okresu

Pełne Logi Uruchomień jednego okresu w Skrzynce Zgłoszeń: GitHub Release z tagiem `logi-<okres>` w prywatnym repozytorium Zgłoszeń, który Centrum zakłada przy pierwszych Logach okresu.
Każde Uruchomienie ma w nim jeden plik o nazwie pliku Logów z `.gz`, który po rozpakowaniu jest bajt w bajt plikiem Logów z komputera taty, a w issue Logów okresu jeden komentarz z podsumowaniem i odnośnikiem do tego pliku.
Diagnoza podmienia plik swojego Uruchomienia.
Nie jest Wydaniem: leży w innym repozytorium i pod innym tagiem, a Centrum i narzędzie Wydań patrzą tylko na Wydania publicznego repozytorium.
Gdy Skrzynka odmawia Archiwum, plik czeka w Kolejce wysyłki, a komentarz idzie z dopiskiem, że pełne Logi czekają; pozostałe wysyłki kolejki idą dalej (ADR 0015, dopisek #844).
_Avoid_: Wydanie, release Logów, załącznik

## Kontrola ilości

Porównanie Ilości usług, które dają Reguły ilości i Legenda czynności (ta także kwotę w `AS` i kolory), z tym, co stoi w Pliku zbiorczym, z którego tata uruchomił Przebieg rozliczeń.
Pokazuje, co tata musiał poprawić albo dopisać ręcznie: tacie jako podpowiedzi przy Regułach ilości, a Maksowi w Skrzynce Zgłoszeń, gdzie jeden okres ma jedną Kontrolę ilości, której tata nie wysyła.
Różnica legendy i wpis taty w wierszu bez Kodu czynności idą tam z opisem technika, a wiersze z Błędem opisu jako liczby według powodu.
_Avoid_: Zgłoszenie (to Zatrzymanie z Diagnozą), raport różnic

## Wyjątek Kontroli ilości

Różnica Kontroli ilości w jednej komórce jednego Wiersza danych, przy której tata kliknął w podpowiedziach przy Regułach ilości „To był wyjątek”: jego wpis jest dobry dla tego zlecenia.
Ta różnica nie wraca w podpowiedziach, także po zmianie reguły, dopóki tata nie zmieni wpisu ani treści wiersza; cofa ją „Cofnij” w Historii Ustawień.
Nie zmienia Reguł ilości ani Kontroli ilości w Skrzynce Zgłoszeń.
_Avoid_: wyjątek od reguły (reguła zostaje bez zmian), pominięcie różnicy

## Powiadomienie

Fakt dla taty o jego Zgłoszeniach, Uwagach taty, wersjach narzędzia i zakończonych Wycenach w efenix, pokazany w widoku Powiadomienia w Centrum rozliczeń, do którego prowadzi dzwonek.
Nieprzeczytane Powiadomienie zapala kropkę na dzwonku; wejście do widoku oznacza wszystkie jako przeczytane.
Powiadomienie o zakończonej Wycenie w efenix, także zakończonej Zatrzymaniem, ma tytuł wyniku, okres, tryb Wyceny, liczby zleceń gotowych do przekazania, Zleceń przekazanych, Zleceń rozliczonych, błędów i Ostrzeżeń Emmetta, „Co się stało” Zatrzymania i przycisk karty Uruchomienia: tata w trakcie patrzy na okno efenix albo odchodzi od komputera.
Toast wyniku w karcie Centrum nie jest Powiadomieniem, a uwagi techniczne z karty Uruchomienia, np. o niezapisanych metrykach, też nie.
_Avoid_: notyfikacja, alert

## Powiadomienie o nowej wersji

Powiadomienie o Wydaniu nowszym od wersji taty: jego numer, notka „Co nowego” i Uwagi taty oraz Zgłoszenia, które rozwiązuje.
Ma przycisk Aktualizacji narzędzia, dopóki tata nie przejdzie na to Wydanie albo nowsze.
Sprawę, którą Maks rozwiązał przed Wydaniem, osobne Powiadomienie nazywa rozwiązaną, z dopiskiem, że będzie w następnej wersji.
_Avoid_: Powiadomienie o naprawie

## Wersja narzędzia

Commit klonu narzędzia, z którego wystartowało Centrum rozliczeń na komputerze taty.
Okno Ustawień pokazuje jego skrót i dzień, od którego narzędzie jest na tym commicie; Zgłoszenie podaje pełny commit.
_Avoid_: numer wersji z `pyproject.toml`

## Wydanie

Wersja narzędzia, którą Maks świadomie ogłasza tacie: numer, np. `0.2.0`, i krótka notka „Co nowego” dla taty.
Jedno Wydanie zbiera wszystkie zmiany od poprzedniego, a nie każdą naprawę z osobna.
Tylko Wydanie może trafić na komputer taty; zmiany, które nie weszły do żadnego Wydania, u taty nie działają.
_Avoid_: release, deploy, `main`

## Aktualizacja narzędzia

Przejście narzędzia na komputerze taty na najnowsze Wydanie, które tata zleca jednym przyciskiem w Centrum rozliczeń.
Przycisk jest tylko wtedy, gdy jest Wydanie nowsze od wersji taty.
Udaje się w całości albo zostawia poprzednią wersję; pliki taty pozostają nietknięte.
_Avoid_: upgrade, git pull, instalacja

## Aktualność narzędzia

Czy narzędzie na komputerze taty jest na najnowszym Wydaniu: `Aktualna`, `Jest nowsza wersja` albo `Nie sprawdzono` (bez internetu albo gdy GitHub chwilowo nie odpowiada na pytania o nową wersję).
Pokazuje ją okno Ustawień i sprawdza Diagnoza; nowsza wersja jest przyczyną Zatrzymania tylko wtedy, gdy Diagnoza nie znalazła innej.
_Avoid_: świeżość, freshness

## Ponowny start Centrum

Koniec udanej Aktualizacji narzędzia: Centrum rozliczeń samo się zamyka i startuje w nowej wersji na tym samym adresie, a otwarta karta przeglądarki sama się odświeża.
Gdy nowa wersja nie wystartuje, wraca poprzednia, a karta pokazuje Komunikat.
_Avoid_: restart, reboot

## Nienadpisywanie

Jeśli folder lub pliki docelowe nowego okresu już istnieją, proces zatrzymuje się bez ich nadpisywania.
Wzorców nie zmienia żaden proces, a Rejestr zleceń tylko te, które wymienia hasło Rejestr zleceń.
Istniejący Plik zbiorczy zmienia tylko Wycena w efenix i tylko Znacznikiem efenix w `ADRES` gotowych zleceń i Znacznikiem przekazania w `ADRES` Zleceń przekazanych.
