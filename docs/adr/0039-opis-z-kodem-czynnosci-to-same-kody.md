# ADR 0039: Opis z Kodem czynności to same kody

## Status

Zaakceptowana (odpowiedzi taty z 16.11.2026 na pytania z [ADR 0038](0038-legenda-czynnosci-wyznacza-ilosci-z-opisu-technika.md),
przekazane przez Maksa; decyzje koordynatora tam, gdzie odpowiedź czegoś nie rozstrzyga, nazwane niżej). Zmienia te
zdania ADR 0038:

- „Pierwszy zestaw to mail taty z 15.11.2026 oraz zapis `instmdic` przy `instmdik`”: legenda z Wydania nie ma
  dodatkowych zapisów;
- „Kod czynności czyta się (…) bez względu na wielkość liter i spacje wewnątrz kodu, w jednym z jego zapisów”: spacja
  w środku kodu i kod sklejony z innym nie są kodem;
- „Liczba spoza przedziałów niczego nie wyznacza, a tata widzi, który kod został mu do wpisania”: to Błąd opisu;
- „Każde wystąpienie kodu się dodaje, także kwoty w `AS`, a różne kody w jednym zleceniu się sumują”: sumują się tylko
  kwoty w `AS`, a kolumna Ilości usług trafiona drugi raz to Błąd opisu;
- „Gdy obok kodu stoi inny tekst, legenda wpisuje swoje, a wiersz zostaje tacie do sprawdzenia. (…) Słowa obok kodu nie
  dają osobnego ostrzeżenia”: inny tekst obok kodu to Błąd opisu, a legenda nie wpisuje wtedy nic;
- „Dla każdego wiersza z różnicą i każdego wiersza bez kodu z wartością taty (…) wysyła treść `CZYNNOŚCI
  ZREALIZOWANE`”: wysyła ją też dla każdego wiersza z Błędem opisu;
- „W kodzie, nie w danych (…): kod sumuje się także w `Y` (…), a `AS` i kolory przechodzą do Rozliczenia pracownika”:
  czerwone i zielone pola zmieniają się w Rozliczeniu pracownika;
- „Później: (…) legenda w Przypomnieniu o raporcie”: niepotrzebna.

Dopełnia [ADR 0018](0018-ilosci-tylko-dla-inea-nie-przechodza-do-rozliczenia-pracownika.md): czerwone pole to kolejna
pozycja, za którą płaci INEA, a nie Wykonawca.

## Kontekst

ADR 0038 zbudował Legendę czynności z wartościami domyślnymi do odpowiedzi taty. Tata odpowiedział na 15 pytań.

Potwierdza to, co jest: `rt2` daje `AM` (1); „każde `rt2`, nie uwzględniamy usterek” (2); `instutp` do 10 m daje `AL`
(3); czerwone przy `spawpg` jest pole `AS` (4); liczba w `bypas` i `instwew` nie ma znaczenia (7); dwie kwoty w `AS`
„zawsze suma” (12); w zleceniu nieskutecznym „nic nie wprowadzamy” (13), a takie zlecenie już dziś nie trafia do Pliku
zbiorczego; inne dopłaty (listwy, „2x spawanie”) „pozostają do ręcznego rozliczenia” (14); legendy w Przypomnieniu nie
trzeba, bo tata powiadomił pracowników osobno (15).

Zmienia zasady:

- (5) „Wszystkie pola zakolorowane na czerwono mające jakąkolwiek liczbę po przeniesieniu do pracownika liczbę
  kasujemy, a kolor zmieniamy na biały, wszystkie pola zakolorowane na zielono po przeniesieniu do pracownika wstawiamy
  cyfrę 1, a kolor zmieniamy na biały.”
- (6) Kwota `pz` „nie zależy od liczby, jest zawsze taka sama”.
- (8) `instutp` i `instwewrg6` powyżej 30 m albo 0 m „nie powinno się pojawić; jeżeli się pojawi, to będzie błąd”.
- (9) Własne zapisy kodów: „Pracownicy mają pisać zgodnie z kodami; jeżeli napiszą inaczej, to traktujemy to jako błąd.
  Każdy błąd można potraktować jako niewysłany raport i wysłać powiadomienie do pracownika, że nie wysłał raportu.”
- (10) Kod obok zwykłego opisu: „Pracownicy mają pisać same kody, resztę traktujemy jako błąd.”
- (11) `instmdik` i `inst20m` w jednym zleceniu: „to jest błąd, nie będzie nigdy 2, 3 itd., zawsze tylko 1”.

Odpowiedzi nie mówią o opisie bez żadnego kodu („montaż ONT”, wymiana routera). Na Logach Wpisania raportów z
03.11–15.11.2026 takich Wpisów `tak` było 104 z 213, a dopłaty z odpowiedzi 14 Wykonawca może opisać tylko słowami.

## Decyzja

- **Opis z Kodem czynności to same kody.** Słowo opisu to ciąg liter, cyfr i `/`. W opisie, w którym stoi co najmniej
  jeden Kod czynności, każde słowo to cały zapis kodu z legendy albo `tak`/`nie` (odpowiedzi 9, 10). Wielkość liter nie
  ma znaczenia (decyzja koordynatora: telefon sam zaczyna wielką literą, a tata pisze o zapisie kodu).
- **Opis bez kodu zostaje tacie jak dotąd, bez błędu** (decyzja koordynatora: odpowiedzi o nim nie mówią, dopłaty z
  odpowiedzi 14 nie mają kodu, a błąd w połowie Wpisów `tak` zalałby Wykonawców przypomnieniami). Własny zapis bez
  żadnego kodu z legendy (`utp18m`) jest więc opisem bez kodu, a tata widzi go w Ilościach do uzupełnienia i Kontroli
  ilości jak dziś.
- **Błąd opisu** to opis z Kodem czynności i: słowem, które nie jest zapisem kodu (10), kodem z liczbą spoza przedziałów
  (8) albo kolumną Ilości usług trafioną drugi raz, także tym samym kodem (11; decyzja koordynatora: każda kolumna, nie
  tylko `Y`, bo tata pisze „zawsze tylko 1”). Kwoty w `AS` się sumują i nie są błędem (12).
- **Opis z Błędem opisu nie wyznacza niczego.** Legenda nie wpisuje w tym wierszu Ilości, kwoty ani koloru, a wiersz
  zostaje tacie w Ilościach do uzupełnienia. Przygotowanie pliku zbiorczego ostrzega o tych wierszach, a Kontrola
  ilości pokazuje je z opisem w maskowaniu [ADR 0025](0025-regula-danych-wysylki-do-skrzynki.md).
- **Błąd opisu w Raporcie wykonawcy: raport niewysłany, Wpis wpisany** (9). Raport dnia z Wpisem `tak` z Błędem opisu
  liczy się dla Przypomnień jako niewysłany, a Przypomnienie mówi, w którym zleceniu jest błąd i jaki (decyzja
  koordynatora: bez powodu Wykonawca odeśle ten sam raport). Kończy je następny raport tego dnia bez Błędu opisu.
  Wpisanie raportów wpisuje taki Wpis jak dotąd (decyzja koordynatora: bez `SKUTECZNE` Przygotowanie pliku zbiorczego
  się zatrzymuje, a legenda i tak nic z niego nie wyznaczy), a późniejszy poprawny Wpis go zastępuje. Opis we Wpisie
  `nie` to powód nieskuteczności, więc legenda go nie czyta (13). Wzór treści i przykład w Przypomnieniu pokazują kody.
- **Czerwone i zielone pole w Rozliczeniu pracownika** (5). Przebieg rozliczeń kasuje liczbę z pola z czerwonym
  wypełnieniem i wpisuje 1 w pole z zielonym, a oba robi białymi. Dotyczy to każdego takiego pola, także
  pokolorowanego przez tatę ręcznie, i czerwonego pola bez liczby (decyzja koordynatora: kolor znika i tak). Plik
  zbiorczy zostaje bez zmian, bo jest podstawą rozliczenia z INEA.
- **Dane legendy z Wydania**: `pz#m` daje 480 w `AS` przy każdej liczbie metrów (6). Legenda nie ma dodatkowych zapisów
  (`instmdic`, `dzielnika1/2`), bo dodaliśmy je sami (9). Każde `rt2` daje `AM` (1, 2; decyzja koordynatora: „nie
  uwzględniamy usterek” czytamy jako „bez osobnej reguły dla usterek”, a gdy tata miał na myśli, że w usterce `rt2` się
  nie liczy, zmieni to Wydanie).

## Odrzucone warianty

- **Każdy opis z innym słowem niż kod to Błąd opisu**, także bez kodu. Tak brzmi „pracownicy mają pisać same kody”
  wzięte dosłownie, ale dopłaty bez kodu (14) nie miałyby wtedy poprawnego zapisu, a 104 z 213 Wpisów `tak` z dwóch
  tygodni dałyby Przypomnienie. Zmiana to jedno zdanie silnika, gdy tata to potwierdzi.
- **Kod obok zwykłego opisu wpisuje swoje** (ADR 0038). Tata chce samych kodów, a częściowy wynik mieszałby się z
  poprawką taty albo z poprawionym raportem Wykonawcy.
- **Wpis z Błędem opisu niewpisany**, jak Wpis bez znaku `tak`/`nie`. Puste `SKUTECZNE` zatrzymuje Przygotowanie
  pliku zbiorczego, dopóki tata nie wpisze go ręcznie.
- **Wielka litera jako błąd.** Klawiatura telefonu zaczyna zdanie wielką literą sama.
