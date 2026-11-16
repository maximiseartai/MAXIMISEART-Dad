# ADR 0039: Opis zlecenia to same Kody czynności

## Status

Zaakceptowana (odpowiedzi taty z 16.11.2026 na pytania z [ADR 0038](0038-legenda-czynnosci-wyznacza-ilosci-z-opisu-technika.md),
przekazane przez Maksa). Zmienia te zdania ADR 0038:

- „Kod czynności czyta się (…) bez względu na wielkość liter i spacje wewnątrz kodu, w jednym z jego zapisów”: spacja w
  środku kodu i zapis spoza legendy to Błąd opisu;
- „Liczba spoza przedziałów niczego nie wyznacza, a tata widzi, który kod został mu do wpisania”: to Błąd opisu;
- „Gdy obok kodu stoi inny tekst, legenda wpisuje swoje, a wiersz zostaje tacie do sprawdzenia. (…) Słowa obok kodu nie
  dają osobnego ostrzeżenia”: inny tekst to Błąd opisu, a legenda nie wpisuje wtedy nic;
- „W kodzie, nie w danych (…): kod sumuje się także w `Y` (…), a `AS` i kolory przechodzą do Rozliczenia pracownika”:
  kolumna Ilości usług trafiona drugi raz to Błąd opisu, a czerwone i zielone pola zmieniają się w Rozliczeniu
  pracownika;
- „Później: (…) legenda w Przypomnieniu o raporcie”: niepotrzebna, tata powiadomił Wykonawców sam.

Dopełnia [ADR 0018](0018-ilosci-tylko-dla-inea-nie-przechodza-do-rozliczenia-pracownika.md): czerwone pole to kolejna
pozycja, za którą płaci INEA, a nie Wykonawca.

## Kontekst

ADR 0038 zbudował Legendę czynności z wartościami domyślnymi do odpowiedzi taty. Tata odpowiedział na 15 pytań. Osiem
odpowiedzi potwierdza to, co jest: `rt2` daje `AM` i liczy się zawsze, `instutp` do 10 m daje `AL`, czerwone przy
`spawpg` jest pole `AS`, liczba w `bypas` i `instwew` nie ma znaczenia, kwoty w `AS` się sumują, a inne dopłaty (listwy,
„2x spawanie”) zostają do ręcznego rozliczenia. Zlecenie nieskuteczne nie dostaje nic, a już dziś nie trafia do Pliku
zbiorczego.

Reszta zmienia zasady. Wykonawcy mają pisać same kody, w zapisach z legendy: własny zapis (`instmdic`, `utp18m`,
`inst25`), zwykły opis obok kodu, `instutp40m` i dwa kody w jednej kolumnie (`instmdik` i `inst20m` w `Y`) to błąd, a
„każdy błąd można potraktować jako niewysłany raport i wysłać powiadomienie do pracownika”. Kwota `pz` nie zależy od
metrów. W Rozliczeniu pracownika tata kasuje liczbę z każdego czerwonego pola, a w każde zielone wpisuje 1, i oba robi
białymi.

## Decyzja

- **Opis zlecenia to same Kody czynności.** `CZYNNOŚCI ZREALIZOWANE` czyta się słowami (ciąg liter, cyfr i `/`). Każde
  słowo to cały zapis kodu z legendy albo `tak`/`nie`. Wielkość liter nie ma znaczenia, bo telefon sam zaczyna wielką
  literą. Opis pusty albo z samym `tak`/`nie` nie ma kodów i nie ma błędu.
- **Błąd opisu** to słowo, które nie jest zapisem kodu (także kod ze spacją w środku albo sklejony z innym), kod z
  liczbą spoza przedziałów i kolumna Ilości usług trafiona drugi raz, także tym samym kodem. Kwoty w `AS` się sumują i
  nie są błędem.
- **Opis z Błędem opisu nie wyznacza niczego.** Legenda nie wpisuje w tym wierszu ani Ilości, ani kwoty, ani koloru, a
  wiersz zostaje tacie w Ilościach do uzupełnienia, tak jak wiersz bez kodu. Przygotowanie pliku zbiorczego ostrzega o
  wierszach z Błędem opisu, a Kontrola ilości pokazuje je z opisem w maskowaniu
  [ADR 0025](0025-regula-danych-wysylki-do-skrzynki.md).
- **Błąd opisu w Raporcie wykonawcy to raport niewysłany.** Wpisanie raportów nie wpisuje Wpisu `tak` z Błędem opisu,
  tata widzi go w Raportach, a raport tego dnia liczy się jako niewysłany, więc Wykonawca dostaje Przypomnienie o
  raporcie z powodem. Opis we Wpisie `nie` to powód nieskuteczności, a nie czynności, więc legenda go nie czyta.
- **Czerwone i zielone pole w Rozliczeniu pracownika.** Przebieg rozliczeń kasuje liczbę z pola z czerwonym
  wypełnieniem i wpisuje 1 w pole z zielonym, a oba robi białymi. Dotyczy to każdego takiego pola, także pokolorowanego
  przez tatę ręcznie. Plik zbiorczy zostaje bez zmian, bo jest podstawą rozliczenia z INEA.
- **Dane legendy z Wydania**: `pz#m` daje 480 w `AS` przy każdej liczbie metrów. Legenda nie ma już dodatkowych zapisów
  (`instmdic`, `dzielnika1/2`), bo dodaliśmy je sami, a nie tata. Tata może dopisać zapis sam w Ustawieniach.

## Odrzucone warianty

- **Kod obok zwykłego opisu wpisuje swoje** (ADR 0038). Tata chce samych kodów. Częściowy wynik z opisu z błędem
  mieszałby się z poprawką taty albo z poprawionym raportem Wykonawcy.
- **Wpis z Błędem opisu wpisany, tylko z ostrzeżeniem dla taty.** Tata chce traktować go jak niewysłany raport.
  Wykonawca bez powiadomienia nie poprawi opisu, a tata wypełniałby wiersz jak dawniej.
- **Wielka litera jako błąd.** Klawiatura telefonu zaczyna zdanie wielką literą sama, a tata pyta o zapis kodu, nie o
  wielkość liter.
