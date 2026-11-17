# ADR 0041: Przypomnienie tylko bez raportu, błąd raportu widzi tata

## Status

Zaakceptowana (słowa taty przekazane przez Maksa 17.11.2026 i decyzje Maksa z grilla w gałęzi
`docs/powiadomienia-brak-raportow`). Od taty są trzy reguły, cytowane w Kontekście: przypomnienie tylko bez raportu,
błąd raportu tylko dla taty i zwykły opis obok kodów to nie błąd. Cytaty Maksa z grilla mają poprawioną pisownię. Pozostałe punkty Decyzji to decyzje Maksa, nazwane przy
każdym. Spis zdań niżej powstał z przejścia po każdym punkcie Decyzji ADR 0039 i ADR 0030.

Zmienia te zdania [ADR 0039](0039-opis-zlecenia-to-same-kody-czynnosci.md):

- „Opis zlecenia to same kody. (…) Każde słowo to cały zapis kodu z legendy albo `tak`/`nie`”: obok Kodów czynności
  stoi zwykły opis technika, a słowo, które nie jest zapisem kodu, jest opisem, nie błędem;
- „Błąd opisu to opis ze słowem, które nie jest zapisem kodu (9, 10; także kod ze spacją w środku, sklejony z innym i
  zwykły opis bez kodu)”: Błąd opisu to już tylko kod z liczbą spoza przedziałów, kolumna Ilości usług trafiona drugi
  raz i kolumna wypełniona dwoma kolorami. Odpada też oparcie tego zdania na pierwszym zdaniu odpowiedzi 9 („Pracownicy
  mają pisać zgodnie z kodami; jeżeli napiszą inaczej, to traktujemy to jako błąd”): własny zapis kodu nie jest już
  Błędem opisu, tylko zwykłym opisem (decyzja Maksa, niżej);
- „Opis z Błędem opisu nie wyznacza niczego” zostaje, ale opis z kodami i zwykłym tekstem wyznacza Ilości z samych
  kodów: wraca wariant „Kod obok zwykłego opisu wpisuje swoje”, który ADR 0039 odrzucił;
- „Błąd opisu w Raporcie wykonawcy: raport niewysłany, Wpis wpisany”: raport jest przysłany, Wpis wpisany, a błąd
  widzi tata przy zleceniu w szczegółach dnia Wykonawcy w widoku Raporty; Przypomnienie nie wymienia już zleceń z
  błędem (zdania „Przypomnienie mówi, w którym zleceniu jest błąd i jaki” i „Dzień liczy się jako wysłany, gdy żaden
  wygrywający Wpis `tak` tego dnia nie ma Błędu opisu” odpadają);
- „Opis z Błędem opisu nie wyznacza niczego. (…) wiersz zostaje tacie w Ilościach do uzupełnienia”: tak zostaje, ale
  w Ilościach do uzupełnienia czeka też tylko wiersz bez żadnego kodu, a nie wiersz z kodem i zwykłym opisem;
- odrzucony wariant „Opis bez żadnego kodu bez błędu”: przyjęty, z informacją „BRAK KODU” dla taty zamiast Błędu
  opisu.

Zmienia te zdania [ADR 0030](0030-przypomnienia-o-raporcie-z-centrum-w-autostarcie.md):

- „Przypomnienia kończy czytelny Raport wykonawcy za ten dzień, nawet niepełny; mail z nieczytelnym tematem ich nie
  kończy”: kończy je każdy Raport wykonawcy za ten dzień, także z błędem tematu, z Błędem opisu i z pomylonym tematem
  ([ADR 0029](0029-raport-wykonawcy-wazniejszy-od-intermax.md)), który liczy się za dzień swoich zleceń;
- „Odpowiedź na przypomnienie jest raportem. (…) dotąd każdy temat z `Re:` był pomijany”: raportem jest też odpowiedź
  z tematem Raportu wykonawcy na początku (poprawka raportu), z tą samą regułą tekstu nad cytatem.

## Kontekst

Pierwszego ranka po wdrożeniu ADR 0039 Centrum wysłało o 8:00 25 przypomnień do 18 Wykonawców. 19 z nich poszło
za dni, za które Wykonawca przysłał czytelny raport, a Błąd opisu miał każdy z 88 wskazanych Wpisów z jednego powodu:
słowa, które nie jest zapisem kodu (dopisany opis albo kod ze spacją). Część dni była sprzed ogłoszenia kodów
Wykonawcom. Trzy poszły po raporcie z błędem w temacie (literówka w słowie `Raport`, spacja w dacie, zła cyfra
dnia), a tylko trzy za dni, za które raportu naprawdę nie było. Tata tego samego ranka sam pisał do Wykonawców o
błędach, a potem do wszystkich, że dodatkowy opis nie jest błędem.

Słowa taty przekazane przez Maksa: przypomnienia „mają wychodzić tylko wtedy, kiedy pracownik w ogóle nie przesłał
raportu”, a „kiedy przysłał go źle (zły format, kod, tekst itd.) ma tata zostać tylko powiadomiony”; „w opisie oprócz
tych kodów (…) będzie też zwykły opis”. Mail taty do Wykonawców: „dodatkowy opis nie jest błędem”. Tata nie mówi o
własnym zapisie kodu (`instmdic`, `dzielnik 1/2`), więc to, że i on jest zwykłym opisem, to decyzja Maksa.

Drugie zdanie odpowiedzi 9 z ADR 0039 („każdy błąd można potraktować jako niewysłany raport”) było możliwością, którą
tata teraz odrzuca, a odpowiedź 10 („resztę traktujemy jako błąd”) zmienia jego mail. Maks dodaje, że dodatkowy opis
„często będzie, bo musi być”.

## Decyzja

- **Przypomnienie tylko bez raportu.** Przypomnienie za dzień idzie, dopóki Wykonawca nie przysłał za ten dzień żadnego
  Raportu wykonawcy. Raport z błędem w temacie albo we Wpisach jest przysłany.
- **Zwykły opis obok kodów** (słowa taty). Zwykły opis obok Kodów czynności nie jest błędem.
- **Cały opis do INTERMAX, Ilości z samych kodów** (decyzja Maksa). Wpisanie raportów wpisuje do
  `CZYNNOŚCI ZREALIZOWANE` cały opis po `tak`/`nie`, a Przygotowanie pliku zbiorczego wyznacza Ilości legendą z samych
  Kodów czynności, także gdy obok stoi zwykły opis.
- **Własny zapis kodu to zwykły opis, tata widzi rozpoznane kody i „BRAK KODU”** (decyzja Maksa: „tata musi być
  powiadomiony, najlepiej (…) w szczegółach danego dnia, jeżeli nie ma rozpoznanego kodu w danym zleceniu, to jest
  informacja, że BRAK KODU”, przy wybranym wariancie, w którym szczegóły zlecenia pokazują, które słowa legenda wzięła
  za kody). Słowo, które nie jest zapisem kodu z legendy, także własny zapis kodu (`instmdic`, `dzielnik 1/2`), jest
  zwykłym opisem i niczego nie wyznacza. W szczegółach dnia przy każdym zleceniu `tak` widać, które słowa opisu
  legenda wzięła za kody, więc przy `inst30m instmdic` tata widzi, że kodem jest tylko `inst30m`. Zlecenie `tak` bez
  żadnego rozpoznanego kodu ma informację „BRAK KODU”, bez zgadywania, do którego kodu słowo jest podobne (ADR 0038
  odrzucił rozmyte dopasowanie). Zlecenie bez kodu zostaje tacie w Ilościach do uzupełnienia;
  Przygotowanie pliku zbiorczego liczy je w ostrzeżeniu o kolumnach z opisu technika jako wiersz zostawiony tacie, a
  Kontrola ilości jako wiersz bez kodu, jak przed ADR 0039 (decyzja koordynatora: ostrzeżenie i blok Kontroli według
  powodu zostają tylko dla Błędu opisu).
- **Błędy raportu widzi tata w kafelku dnia** (decyzja Maksa: „najlepiej na heat mapie po kliknięciu na kafelek, tam gdzie są
  szczegóły poszczególnych zleceń”). Błąd opisu, błąd tematu i każdy inny problem Wpisania raportów stoi przy
  zleceniu w szczegółach dnia Wykonawcy na mapie cieplnej widoku Raporty, po kliknięciu „Wpisz raporty z maili”. Praca
  przypomnień w tle niczego nie pokazuje w kafelkach.
- **Wpis na życzenie** (decyzja Maksa: „dopisanie danych z raportu do INTERMAX na życzenie, a nie jako
  automatyczny run”). Przy błędzie, przy którym wiadomo, co wpisać (błąd tematu, czyli temat ze słowem raportu
  bez dnia albo z innymi słowami; `t`, `n`, `skuteczne`, `nieskuteczne` zamiast `tak`/`nie`), tata jednym kliknięciem przy
  zleceniu wpisuje Wpis do INTERMAX na swoją odpowiedzialność, zamiast prosić Wykonawcę o nowy mail. W INTERMAX wygląda
  jak każdy Wpis, Centrum pamięta decyzję taty jak „Zostaw moją”, a późniejszy poprawny Wpis raportu wygrywa. Przy
  przeciwnych Wpisach i numerze, którego INTERMAX nie ma albo ma w kilku miejscach, przycisku nie ma.
- **Tolerancja tematu** (decyzja Maksa: „błędy, jeżeli chodzi o ortografię i interpunkcję w temacie (…) powinieneś go
  traktować jako poprawne”; granicę wyznaczają tematy ze skrzynki).
  Temat wybacza wielkość liter, jedną literówkę w słowie `Raport`, dowolną interpunkcję albo
  spację w dacie i interpunkcję na końcu. Na tematach od Wykonawców z 16–17.11.2026 (pierwsze dni nowego wzoru) to
  łapie wszystkie trzy błędne. Inne słowa obok słowa i daty to błąd tematu z Wpisem na życzenie. Dzień raportu bez
  dnia w temacie to ostatni dzień Wykonawcy ze zleceniami bez raportu, nie późniejszy niż dzień przyjścia maila, a
  numery zleceń dalej wygrywają z datą (ADR 0029).
- **Co nie jest raportem** (decyzja Maksa). Mail bez żadnego Wpisu i mail ze zdjęciami do raportu (`Zdjęcia do raportu …`, codziennie
  od jednego Wykonawcy) Centrum pomija po cichu. Mail bez słowa `Raport` w temacie (także `Montaże …`, `Zlecenia …`)
  nie jest raportem nawet z Wpisami: Centrum nie czyta treści wszystkich maili Wykonawców (Maks: „żeby niepotrzebnie
  nie czytać wszystkich maili”), a przypomnienie wtedy pójdzie; Maks: „tata na pewno zobaczy, że jest montaże zamiast
  raport, i poprawi pracownika”.
- **Poprawka raportu w odpowiedzi** (decyzja Maksa). Odpowiedź (`Re:`, `Odp:`) z tematem Raportu wykonawcy za dzień na początku i
  dowolnym dopiskiem po nim (tata odpisuje „Re: Raport 16.11.2026 - BŁĘDY PROSZĘ POPRAW…”) jest Raportem wykonawcy
  za ten dzień, a jej Wpisami jest tylko tekst nad cytatem, jak w odpowiedzi na Przypomnienie. Temat bez roku
  („Re: Raport 16.11 - popraw”) daje ten dzień i miesiąc w roku, w którym leżą w tych samych granicach od dnia
  przyjścia maila co data z rokiem pomylonym (31.12 w mailu z 2.01 to poprzedni rok), bez błędu tematu (decyzja Maksa 17.11.2026:
  „odpowiedź na poprawkę bez roku nie może być pomijana, bo domyślnie rok zawsze będzie ten obecny; odpowiedź na
  poprawkę i tak dziedziczy temat, który wpisał tata, a tata będzie się trzymał swojej konwencji”).
  Rozwinięcie tej decyzji przez koordynatora (17.11.2026, bez Maksa): gdy liczby po dniu i miesiącu nie dają dnia z
  rokiem, odpowiedź liczy się za ten dzień i miesiąc tak samo jak bez roku, więc rok złej długości
  („Re: Raport 16.11.202”) i liczba w dopisku („Re: Raport 16.11 2 montaże”) też dają 16.11; odpowiedź dziedziczy
  temat taty, a jej dopisek nie zmienia dnia. Temat bez `Re:` z takim rokiem zostaje błędem tematu.

## Odrzucone warianty

- **Błąd opisu dalej jako raport niewysłany, tylko z łagodniejszą legendą.** Przypomnienie dalej szłoby do Wykonawcy,
  który raport przysłał, a tata przy raporcie przysłanym źle chce być „tylko powiadomiony”.
- **Powiadomienie taty mailem.** Maks wybrał widok Raporty („w Raportach w odpowiednim dniu i zleceniu na heat
  mapie”), gdzie są szczegóły zlecenia; mail do skrzynki raportów taty byłby szumem między raportami.
- **Czytać wszystkie maile Wykonawców i brać każdy z Wpisami.** Złapałby `Montaże 13.11.26`, ale czyta całą
  korespondencję Wykonawców z tatą; Maks woli, żeby Centrum czytało tylko maile ze słowem `Raport` (decyzja Maksa
  wyżej, „Co nie jest raportem”).
- **Wpisywać zawsze, gdy numery pasują do innego dnia, i nigdy nie pytać taty.** Zostaje tylko dla pomylonego tematu z
  ADR 0029, gdzie co najmniej dwa numery dowodzą dnia (Maks: „numery zleceń są ważniejsze niż daty w takich
  przypadkach”); przy błędzie tematu tata wpisuje raport Wpisem na życzenie (decyzja Maksa wyżej).
