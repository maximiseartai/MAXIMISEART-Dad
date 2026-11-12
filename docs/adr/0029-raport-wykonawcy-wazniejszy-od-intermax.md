# ADR 0029: Raport wykonawcy jest ważniejszy od INTERMAX w dniu i Wykonawcy zlecenia

## Status

Zaakceptowana (decyzja Maksa 12.11.2026 po rozmowie z tatą, grill w tej gałęzi). Zmienia te zdania wcześniejszych
ADR:

- [ADR 0028](0028-wpisanie-raportow-z-gmaila-na-zadanie-przed-chmura.md) i
  [ADR 0019](0019-uporzadkowanie-intermax-zmienia-rejestr-zlecen.md): Wpisanie raportów zmienia w Rejestrze zleceń nie
  tylko `SKUTECZNE` i `CZYNNOŚCI ZREALIZOWANE`, ale też dzień i `WYKONAWCA` zlecenia, przenosi jego wiersz i dopisuje
  nowe wiersze;
- [ADR 0028](0028-wpisanie-raportow-z-gmaila-na-zadanie-przed-chmura.md), „Bez Kopii INTERMAX”: pamięć własnych wpisów
  obejmuje też Przeniesienia zleceń i Zlecenia dopisane z raportu, bo bez niej Wpisanie raportów nie odróżni własnej
  zmiany od ręcznej;
- [ADR 0028](0028-wpisanie-raportow-z-gmaila-na-zadanie-przed-chmura.md), „Co widzi przeglądarka”: informacje o
  Przeniesieniach i Zleceniach dopisanych z raportu używają tylko pól z tej listy (`NUMER ZL.`, `WYKONAWCA`, dzień),
  a o brakującym `ADRES` mówią bez jego treści.

## Kontekst

Wersja 0.7.0 pokazywała tacie trzy rozbieżności Raportu wykonawcy z INTERMAX jako problem i niczego przy nich nie
wpisywała: numer bez zlecenia, zlecenie z innego dnia i zlecenie innego Wykonawcy. W prawdziwym runie z Logów
Wykonawca wysłał raport z numerem zlecenia przypisanego innemu Wykonawcy. Tata mówi, że to zwykła sytuacja:
pracownicy przekazują sobie zlecenia, zlecenie wykonuje się innego dnia, a część zleceń nie trafia do INTERMAX
wklejeniem. Tata poprawia wtedy INTERMAX ręcznie według maila, bo mail mówi, co się naprawdę stało.

## Decyzja

- **Mail wygrywa w Wykonawcy.** Wpis raportu ze zleceniem innego Wykonawcy to Przeniesienie zlecenia do nadawcy, nie
  błąd. Późniejszy Wpis tego samego zlecenia wygrywa także wtedy, gdy przysłał go inny Wykonawca.
- **Mail wygrywa w dniu, chyba że pomylił się temat.** Jeden niezgodny Wpis w raporcie, czyli numer zlecenia tego
  Wykonawcy z innego dnia, to Przeniesienie na dzień z tematu, bo w pracy coś wyszło. Co najmniej dwa niezgodne Wpisy
  w jednym raporcie oznaczają pomylony temat: te Wpisy idą do zleceń z ich dnia w INTERMAX, bez Przeniesienia. Tata
  dostaje informację w obu przypadkach.
- **Numer bez zlecenia to Zlecenie dopisane z raportu**, pod zleceniami nadawcy w dniu z tematu, z pięcioma kolumnami
  z raportu. Tylko numer w postaci numeru z aplikacji firmowej (8 cyfr, jak w INTERMAX), którego nie ma w żadnym
  czytanym dniu, także w zleceniach na jutro, żeby literówka w numerze ani zlecenie wklejone dzień wcześniej nie
  dopisały zlecenia, które już jest. Nie przy pomylonym temacie i nie do dnia, który nie jest Dniem uporządkowanym.
- **Wiersz idzie za zleceniem.** Przeniesienie zmienia dzień w `DATA GODZ. POCZ.` (godzina zostaje) albo `WYKONAWCA` i
  przenosi wiersz pod zlecenia nadawcy w tym dniu, w razie potrzeby do nowego segmentu na miejscu alfabetycznym, żeby
  dzień zachował układ z Uporządkowania INTERMAX. Przeniesienie idzie tylko do Dnia uporządkowanego, bo wiersz w dniu z
  samymi Surowymi zleceniami albo bez zleceń sprawiłby, że Uporządkowanie INTERMAX uznałoby ten dzień za uporządkowany
  i odmówiło jego wklejenia. Okres z Plikiem zbiorczym pozostaje zamknięty w obie strony. W tych przypadkach zostaje
  problem dla taty.
- **Ręczna zmiana dalej wygrywa.** Wpisanie raportów zmienia tylko to, co jest puste albo co samo zmieniło, a od tamtej
  pory nikt tego nie ruszył. Gdy tata przeniesie zlecenie z powrotem, Centrum go nie przenosi drugi raz.
- **Numer w kilku zleceniach się nie przenosi.** Gdy Rejestr zleceń ma numer z Wpisu więcej niż raz w dniach, które
  Wpisanie raportów czyta (także w okresie z Plikiem zbiorczym i w zleceniach na jutro), Wpisanie raportów nie przenosi
  żadnego z tych zleceń: Wpis trafia tylko do jedynego zlecenia nadawcy w dniu z tematu, a inaczej zostaje problem z
  dniem i Wykonawcą każdego z nich. Excel nie mówi, które z tych zleceń tata przeniósł, scalił albo usunął, więc Centrum
  pamięta swoje wpisy w komórkach tylko przy numerze z jednym zleceniem, a wartość w zleceniu numeru, który ma ich
  kilka, liczy jak wartość taty. Bez tej granicy stary mail cofał ręczną zmianę taty i nadpisywał jego wartość
  (przeglądy #1367).
- **Okno mówi, gdzie wolno pisać, a nie, które numery są w Rejestrze.** Wpisanie raportów nie zmienia zleceń z dni po
  dziś: Wpis do numeru, który Rejestr ma tylko jutro, to problem z dniem zlecenia, a nie numer bez zlecenia, który
  dubluje zlecenie na jutro.
- **Informacja, nie Zgłoszenie.** Każde Przeniesienie, Zlecenie dopisane z raportu i temat, który przegrał z INTERMAX,
  widać w okienku dnia Wykonawcy na mapie cieplnej widoku Raporty; Przeniesienie po obu stronach (skąd i dokąd).

## Odrzucone warianty

- **Problem dla taty bez zmiany INTERMAX (wersja 0.7.0).** Tata i tak robi tę poprawkę ręcznie, zawsze tak samo.
- **INTERMAX wygrywa w dniu.** Tata: data z maila jest ważniejsza, bo Wykonawca wie, kiedy był u klienta. Wyjątkiem
  jest tylko pomylony temat.
- **Pomylony temat tylko wtedy, gdy wszystkie Wpisy się nie zgadzają.** Raport z jednym Wpisem byłby wtedy zawsze
  „pomylonym tematem”, a tata chce, żeby jedno przeniesione zlecenie wygrywało z INTERMAX.
- **Wcześniejszy raport ważniejszy.** Notatka z rozmowy z tatą tak mówiła, ale chodziło o poprawkę: drugi mail
  Wykonawcy z `tak` po pierwszym z `nie` musi wygrać.
- **Dopisanie każdego nieznanego numeru.** Literówka w numerze tworzyłaby fałszywe zlecenie, a prawdziwe zostawało puste.
