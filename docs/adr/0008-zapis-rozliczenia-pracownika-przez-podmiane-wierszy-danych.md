# ADR 0008: Zapis Rozliczenia pracownika przez podmianę Wierszy danych w kopii Wzorca

## Status

Zaakceptowana. Rozstrzyga eksperyment 1 (#147) wspinaczki „Przebieg rozliczeń
poniżej minuty” (#141); pomiar w dzienniku wspinaczki (#163).
Interfejsy z sekcji sprzed „Zmiany z 2026-10-24” (`WorkerSettlementTemplate`,
`CollectiveFileTemplate` i `Layout` w `workbook_files`) już nie istnieją: każdy
plik z Wzorca powstaje przez `template_file.TemplateFile` (konstruktory
`worker_settlement`, `collective_file`, `internal_settlement`).
Od #519 rekord metryk niesie drogę zapisu każdego pliku z Wzorca (`routes`,
[ADR 0002](0002-progress-event-observation.md)).
[ADR 0018](0018-ilosci-tylko-dla-inea-nie-przechodza-do-rozliczenia-pracownika.md)
zostawia puste w Rozliczeniu pracownika komórki `AP` i `AK` Ilości tylko dla
INEA, więc nie każda wartość Wiersza danych Pliku zbiorczego trafia do
Rozliczenia pracownika.
Od zmiany z 2026-11-08 także Rozliczenie wewnętrzne powstaje kopią Wzorca, a
flagi przeliczania są częścią układu pliku (sekcja na końcu); zdania
wcześniejszych sekcji, że Rozliczenie wewnętrzne powstaje tylko przez openpyxl
i bez flag przeliczania, opisują stan sprzed niej.

## Kontekst

Przebieg rozliczeń trwał u taty ~4 minuty (234–240 s), na Macu M4 Max 72,5 s
w benchmarku na lustrze folderów taty. 96% tego czasu to Zapisywanie:
Wzorzec rozliczenia pracownika ma ~10 tys. sformatowanych Wierszy danych,
~500 tys. komórek i ~50 tys. formuł (wspólnych), a openpyxl wczytywał go w
całości (~1,7 s) i zapisywał w całości (~1,5 s) dla każdego z 20 Szablonów
pracowników, po czym zip był przepisywany drugi raz, żeby przywrócić
`xl/externalLinks/*`. Samo wpisanie Wierszy danych trwało milisekundy.
Skutkiem ubocznym były pliki większe od Wzorca (2,8 MB zamiast 1,9 MB): bez
wspólnych formuł i bez `calcChain`.

Rozliczenie pracownika różni się od Wzorca tylko Wierszami danych od wiersza
18 w kolumnach A:AT (wartości i, od zmiany z 2026-10-21, Wyróżnienia) i
flagami przeliczania w `calcPr`.

## Decyzja

Rozliczenie pracownika powstaje z kopii bajtów Wzorca wczytanego raz na
Przebieg rozliczeń, za interfejsem `workbook_files.WorkerSettlementTemplate`
(implementacja: `template_copy.py`):

- Każda część zip poza XML aktywnego arkusza i `xl/workbook.xml` jest
  przepisywana bajt w bajt razem ze skompresowaną treścią, w tym
  `xl/externalLinks/*`, `xl/calcChain.xml` i `xl/sharedStrings.xml`.
  `xl/styles.xml` zmienia się tylko wtedy, gdy data trafia do komórki bez
  formatu daty (dopisany styl, jak w openpyxl) albo gdy Wyróżnienia wpisanej
  komórki różnią się od komórki Wzorca (zmiana z 2026-10-21).
- W XML arkusza zmieniają się tylko wiersze od 18 do ostatniego wpisanego.
  Komórki A:AT dostają wartości z tą samą semantyką co wpisanie przez openpyxl
  (tekst, `=formuła`, kody błędów, liczby, prawda/fałsz, daty jako liczba
  seryjna, pusta wartość czyści zera Wzorca, brakująca komórka powstaje ze
  stylem domyślnym). Pozostałe komórki, w tym formuły AU:AY, wspólne formuły
  i style, zostają bajt w bajt.
- `calcPr` dostaje `calcMode="auto"`, `fullCalcOnLoad="1"` i
  `forceFullCalc="1"`, tak jak przy zapisie przez openpyxl.
- Arkusz jest kompresowany raz przy wczytaniu Wzorca, w kawałkach od granic
  wierszy (pełne opróżnienie zlib co 64 wiersze). Dla każdego Rozliczenia
  pracownika kompresowany jest tylko początek arkusza z wpisanymi wierszami,
  a reszta to gotowe kawałki.
- Kontrole Szablonu pracownika (WYKONAWCA w H17, dane w Wierszach danych) są
  liczone raz na Wzorcu; wyniki, Komunikaty, liczniki i zdarzenia postępu są
  takie same jak wcześniej.
- Sprawdzanie Wzorca rozliczenia pracownika (#149) używa tego samego Wzorca
  wczytanego raz: `input_checks.check_settlement` zwraca Wzorzec, z którego etap
  Zapisywanie tworzy Rozliczenia pracowników. Kopia przyjmuje Wzorzec tylko
  wtedy, gdy każda część XML jest poprawnym XML-em; inaczej Sprawdzanie idzie
  przez openpyxl z dotychczasową klasyfikacją (brak, otwarty w Excelu,
  nieczytelny). Przy pierwszym Rozliczeniu pracownika bajty Wzorca są czytane
  ponownie: Wzorzec zmieniony albo otwarty w Excelu po Sprawdzaniu zatrzymuje
  Zapisywanie tak jak wcześniej. Zapis jest atomowy jak wcześniej (plik tymczasowy
  obok celu, `os.replace`).
- Wzorzec spoza kształtu, który zapisuje Excel (np. formuła albo scalenie w
  kolumnach A:AT Wierszy danych, XML z prefiksami przestrzeni nazw, komórki bez
  `r`), i wartości nieobsługiwanych typów (np. tekst sformatowany) idą dawną
  drogą: pełne wczytanie i zapis przez openpyxl. Wpisanie wartości w formułę
  Wierszy danych zmieniałoby `calcChain` i wspólne formuły, czego kopia nie
  robi.

Wynik: typowy tydzień 72,5 s → 2,8 s czasu ściany, Zapisywanie 70 s → 0,42 s
dla 20 Szablonów pracowników (jednorazowe wczytanie Wzorca ~0,35 s, potem
~3–8 ms na Rozliczenie pracownika); ciężki tydzień 73,6 s → 2,9 s. Bramka
poprawności `zgodny` w obu scenariuszach. Rozliczenie pracownika ma ~1,5 MB
(Wzorzec 1,9 MB).

Odrzucone kierunki:

- **Dalej openpyxl, tylko Wzorzec wczytany raz i kopiowany w pamięci.** Zostaje
  pełny zapis ~1,5 s na Szablon pracownika i utrata wspólnych formuł oraz
  `calcChain`; nie zbliża się do celu.
- **lxml pod openpyxl.** Zmierzone ~8% (72 → 67 s) za nową zależność binarną.
- **Równoległe Przetwarzanie Szablonów pracowników.** Nie usuwa pełnego
  wczytania i zapisu, tylko dzieli je na rdzenie, i komplikuje kolejność
  zdarzeń postępu oraz obsługę przerwanego zapisu (spec #141: poza zakresem).
- **Odchudzenie Wzorca** z 10 tys. sformatowanych wierszy. To zmiana w pliku
  taty, poza zakresem narzędzia, i nie usuwa kosztu pełnego wczytania i zapisu.

## Konsekwencje

- Repozytorium utrzymuje własny kod XML i zip (`template_copy.py`): indeks
  wierszy, scalanie komórek, escapowanie tekstu, znaki niedozwolone w XML,
  semantykę typów wartości openpyxl i zapis zip. Strażą jest test właściciel
  zapisu Rozliczenia pracownika w `tests/test_workbook_files.py`, który
  porównuje wynik z plikiem z Wzorca zapisanym przez openpyxl modułem bramki
  poprawności, oraz bramka benchmarku przy każdym eksperymencie.
- openpyxl zostaje do odczytu Pliku zbiorczego i Rejestru zleceń i do drogi
  zapasowej, także w Sprawdzaniu Wzorca, którego kształtu kopia nie przyjmuje.
  Wzorzec rozliczenia pracownika przechodzi Sprawdzanie bez openpyxl (#149):
  Wzorzec poprawny jako XML, ale semantycznie odrzucany przez openpyxl, nie
  jest już zatrzymywany w Sprawdzaniu. Do decyzji trzeba wrócić, jeśli taki
  Wzorzec się pojawi. Przygotowanie pliku zbiorczego
  zapisuje Plik zbiorczy od 2026-10-22, a Rozliczenie wewnętrzne od
  2026-11-08 tą samą kopią (sekcje niżej).
- Bramka poprawności traktuje nazwę arkusza w apostrofach i bez nich w nazwie
  zdefiniowanej jako to samo odwołanie: openpyxl dodaje apostrofy, kopia
  zostawia definicję z Wzorca.
- Usunięcie `forceFullCalc` to osobna zmiana (spec #141, Out of Scope); po niej
  zmienia się tylko łatka `calcPr`.
- Do decyzji trzeba wrócić, jeśli Wzorzec zacznie mieć formuły albo scalenia w
  A:AT Wierszy danych (cały zapis wraca wtedy do openpyxl i do minut) albo
  jeśli Excel zacznie zgłaszać naprawę plików z kopii.

## Zmiana z 2026-10-21

Przebieg rozliczeń czytał z Pliku zbiorczego same wartości, więc każda komórka
A:AT Wierszy danych dostawała wygląd komórki Wzorca. Wyróżnienia, które
Przygotowanie pliku zbiorczego przeniosło z Rejestru zleceń (wypełnienie, kolor
czcionki, pogrubienie, kursywa), znikały. Na kopii prawdziwego Pliku zbiorczego
różniło się tak 1981 z 7906 niepustych komórek.

Teraz `read_data_rows` czyta też Wyróżnienia każdej komórki A:AT, a obie drogi
zapisu nakładają je na komórkę Wzorca tą samą regułą co Przygotowanie z
Rejestru: Wyróżnienia zastępują wypełnienie, kolor, pogrubienie i kursywę
komórki Wzorca (komórka bez Wyróżnień daje komórkę bez wypełnienia, z kolorem
automatycznym); krój i rozmiar czcionki, format liczby, obramowanie,
wyrównanie i ochrona zostają z Wzorca. Kopia dopisuje brakujące czcionki,
wypełnienia i style komórek na końcu ich list w `xl/styles.xml`, każdy raz na
Rozliczenie pracownika; istniejące wpisy zostają bajt w bajt, a gdy żadna
komórka nie potrzebuje nowego stylu, `xl/styles.xml` jest przepisany bez zmian.
Test właściciel zapisu porównuje Wyróżnienia z drogi kopii i drogi przez
openpyxl.

Czcionki i wypełnienia są serializowane przez openpyxl (`to_tree`), więc zapis
jest deterministyczny i ma kształt, który openpyxl już zapisuje w drodze
zapasowej. Oba Wzorce taty mają ten sam motyw (`theme1.xml`), więc kolory
motywu z Pliku zbiorczego znaczą w Rozliczeniu pracownika to samo.

Odrzucone kierunki:

- **Przeniesienie całego stylu komórki Pliku zbiorczego** (jak „Wklej
  wszystko”). Zmieniłoby krój, rozmiar i obramowania, które pochodzą z Wzorca
  rozliczenia pracownika, i wymagałoby kopiowania obramowań oraz formatów
  liczb między dwoma plikami stylów.
- **Wspólny typ z `CellFormat` Przygotowania.** `CellFormat` niesie też format
  liczby z Rejestru i zawsze ustawia pogrubienie i kursywę; w Przebiegu każda
  zwykła komórka dostałaby wtedy nową czcionkę i nowy styl. Ujednolicenie
  zmieniłoby zapis Przygotowania, które jest poza zakresem tej zmiany.

Koszt: na lustrze `typowy-tydzien` (Mac M4 Max) mediana czasu ściany 681 → 709
ms; Odczyt danych tworzy komórki openpyxl zamiast samych wartości (+17 ms), a
Zapisywanie szuka stylu dla każdej wpisanej komórki (+12 ms).

## Zmiana z 2026-10-21: Hiperłącza

Numer zlecenia w `NUMER ZL.` Pliku zbiorczego jest u taty Hiperłączem do
zlecenia w aplikacji firmowej, a w Rozliczeniu pracownika nie dało się go
kliknąć: Przebieg rozliczeń hiperłączy nie czytał ani nie zapisywał.

Teraz `read_data_rows` czyta też Hiperłącza każdej komórki A:AT z wartością
(`hyperlinks.read_sheet_hyperlinks`: blok `<hyperlinks>` za `</sheetData>` i
relacje arkusza, bez parsowania wierszy), a obie drogi zapisu wpisują je w te
same komórki Rozliczenia pracownika. Hiperłącze zastępuje hiperłącze komórki
Wzorca w zapisywanym Wierszu danych, jak Wyróżnienia.

Kopia ma dwa nowe wyjątki od przepisania bajt w bajt, oba tylko wtedy, gdy
któraś wpisana komórka ma Hiperłącze:

- w ogonie XML arkusza pojawia się jeden blok `<hyperlinks>` w miejscu, które
  wyznacza mu schemat arkusza (za `mergeCells`, `conditionalFormatting` i
  `dataValidations`, przed `pageMargins`); pozostałe bajty ogona zostają;
- relacje arkusza (`xl/worksheets/_rels/sheetN.xml.rels`) dostają na końcu po
  jednej relacji `TargetMode="External"` na Hiperłącze, pod numerami `rId` za
  najwyższym numerem we Wzorcu; istniejące relacje (u taty `rId1` rysunek VML
  i `rId2` komentarze) zostają bajt w bajt. Wzorzec bez relacji arkusza dostaje
  nową część na końcu zip; `[Content_Types].xml` się nie zmienia, bo typ
  rozszerzenia `rels` już w nim jest. Wzorzec bez takiego typu idzie dawną
  drogą.

Bez Hiperłączy wszystkie części Rozliczenia pracownika mają po rozpakowaniu te
same bajty co przed zmianą. Skompresowany arkusz ma jedną granicę kawałka
więcej: ostatni kawałek zaczyna się w miejscu bloku `<hyperlinks>`, więc kopia z
Hiperłączami kompresuje od nowa tylko ogon arkusza (u taty 128 B).

Wzorzec, którego arkusz ma już własny blok `<hyperlinks>`, idzie dawną drogą
(`UnsupportedShape`). Wzorzec taty go nie ma, a zasada dla hiperłącza Wzorca w
Wierszach danych wymagałaby scalania dwóch bloków.

Wygląd komórki się nie zmienia: podkreślenie i styl komórki „Hiperłącze” nie
są Wyróżnieniem, więc nie przechodzą z Pliku zbiorczego.

Adres Hiperłącza to treść wiersza (np. numer sprawy klienta). `Hyperlink` nie
pokazuje go w `repr`, a żaden Komunikat, Zdarzenie przebiegu, rekord metryk ani
Zgłoszenie go nie zawiera.

## Zmiana z 2026-10-22: Plik zbiorczy z kopii Wzorca

Po wczytaniu Wzorca pliku zbiorczego w Sprawdzaniu i Planowaniu tylko w
zarysie (#263) największym kosztem Przygotowania pliku zbiorczego zostało
Zapisywanie: pełne wczytanie i zapis tego samego Wzorca przez openpyxl, 4,1 s
z 8,3 s całego Przygotowania na kopii danych taty (M4 Max). Wzorzec pliku zbiorczego ma ten sam
kształt co Wzorzec rozliczenia pracownika (~10 tys. sformatowanych wierszy, ~50
tys. wspólnych formuł), więc Plik zbiorczy powstaje teraz tą samą kopią
(`workbook_files.CollectiveFileTemplate`, układ `SheetLayout(collective_file=True)`).

Kopia wpisuje komórki A:K Wierszy danych tak jak dotąd zapis przez openpyxl
(`preparation_files._write_period_file`), z trzema dodatkami tylko dla Pliku
zbiorczego:

- format liczby każdej wpisanej komórki to format komórki Rejestru zleceń
  (`Row.number_formats`), dopisany do `xl/styles.xml` jak format daty;
  Rozliczenie pracownika nadal ma formaty liczb Wzorca;
- element `autoFilter` arkusza obejmuje kolumny niepustego nagłówka od wiersza
  17 do ostatniego wpisanego wiersza, bez warunków filtrów Wzorca, a nazwa
  `_xlnm._FilterDatabase` arkusza w `xl/workbook.xml` dostaje ten sam zakres;
- wpisana komórka bez własnego stylu w wierszu albo kolumnie ze stylem to
  `UnsupportedShape`: Excel i dawna droga dają jej styl wiersza albo kolumny,
  czego kopia nie odtwarza.

Wzorzec bez `autoFilter` albo bez nazwy `_xlnm._FilterDatabase`, z
nagłówkiem, którego kolumn nie da się dopasować do kolumn Rejestru, i każdy
kształt spoza kopii z decyzji wyżej idzie dawną drogą przez openpyxl. Brak
Wzorca, otwarcie w Excelu i nieczytelny plik zatrzymują Zapisywanie tymi
samymi Komunikatami co dotąd.

Wynik na kopiach danych taty (M4 Max, 8 par naprzemiennie na scenariusz):
Zapisywanie 4,1 s → 0,6 s, całe Przygotowanie 8,3 s → 4,7 s (nowy Rejestr) i
9,5 s → 5,9 s (stary), max RSS 383 → 192–208 MB. W 31 okresach z obu
Rejestrów Plik zbiorczy z kopii i z openpyxl nie różnią się w żadnej kategorii bramki
`tools/porownanie_rozliczen.py`, mają ten sam autofiltr, a Przebieg rozliczeń
na każdym z nich daje te same Rozliczenia pracowników. Plik zbiorczy z kopii
ma ~1,5 MB zamiast ~2,9 MB, zachowuje wspólne formuły i `calcChain` oraz
nieaktywne ustawienia ochrony arkusza Wzorca (`sheetProtection`,
`protectedRanges`), które openpyxl pomijał. Bajty części zip różnią się od
zapisu przez openpyxl, tak jak w Rozliczeniu pracownika.

Test właściciel: `tests/test_plik_zbiorczy_kopia_wzorca.py` porównuje Plik
zbiorczy z obu dróg na syntetycznych Wzorcach, także kształtu Wzorców taty.

## Zmiana z 2026-10-22: Wygląd Wiersza danych

Każda wpisana komórka brała dotąd krój i rozmiar czcionki, wyrównanie,
zawijanie, obramowanie i (w Rozliczeniu pracownika) format liczby z komórki
Wzorca w tym samym wierszu. Wzorce taty mają w Wierszach danych resztki
formatowania: w wierszach 18–31 zawijanie i wyrównanie do góry, od 32 inne
wyrównanie, a Wzorzec rozliczenia wewnętrznego zapisaną wysokość 14 pkt w ~170
wierszach. Na prawdziwych Wzorcach i Rejestrze (tydzień 29.09–05.10.2026)
wiersze 18–31 miały w Excelu podwójną wysokość, wiersze od 32 tekst na środku,
a DATA w Rozliczeniu pracownika pokazywała `#####` (format Wzorca
`yyyy-mm-dd h:mm:ss`).

Teraz komórki kolumn wyglądu (A:M Rozliczenia wewnętrznego, A:L Pliku
zbiorczego i Rozliczenia pracownika) dostają Wygląd Wiersza danych
(`row_look.RowLook`), jak w plikach, które tata robił ręcznie: krój i rozmiar
czcionki komórki nagłówka tej kolumny we Wzorcu, Wyróżnienia, wyrównanie do
lewej i do środka, zawijanie tylko tekstu z końcem linii, cienkie obramowanie z
czterech stron w kolorze automatycznym i format liczby komórki źródłowej
(Rejestru, a w Rozliczeniu pracownika Pliku zbiorczego). Komórka kolumny wyglądu
bez wartości źródłowej (`zwrot` i `UWAGI` Rozliczenia wewnętrznego, L Pliku
zbiorczego) dostaje sam wygląd z formatem ogólnym, a jej treść zostaje z
Wzorca. Wpisany wiersz nie ma zapisanej wysokości (`ht`, `customHeight`), więc
Excel dopasowuje ją do treści. ADRES Pliku zbiorczego bierze Wyróżnienia z
komórki ADRES tego zlecenia w Rejestrze, jak każda inna kolumna; Rozliczenie
pracownika dostaje je zwykłym przeniesieniem Wyróżnień. Pierwsza wersja tej
zmiany dawała mu zawsze żółte wypełnienie (w plikach taty 419 z 419 komórek),
także gdy w Rejestrze miał inny kolor albo żaden; tata poprawił to 2026-10-22.
Kolumny za kolumnami wyglądu (M:AT Rozliczenia pracownika) zostają jak w zmianie
z 2026-10-21. Ochrona i styl nazwany komórki Wzorca zostają.

Wszystkie drogi zapisu biorą wygląd z jednego `RowLook.cell`: openpyxl dla
Rozliczenia wewnętrznego, Pliku zbiorczego i Rozliczenia pracownika (droga
zapasowa) i kopia Wzorca. Kopia dopisuje brakujące obramowania do
`xl/styles.xml` tak jak czcionki i wypełnienia, a element `alignment` w stylu
komórki zastępuje; styl równy istniejącemu w Wzorcu albo już dopisanemu jest
używany ponownie. Wyjątek kopii Pliku zbiorczego dla komórki bez własnego stylu
w wierszu albo kolumnie ze stylem (sekcja wyżej) znika, bo każda komórka kolumn
wyglądu dostaje teraz pełny styl; Wzorzec ze stylem wiersza idzie kopią. Tak samo
znika nadawanie takiej komórce stylu wiersza albo kolumny w drodze przez openpyxl.

Odrzucony kierunek z 2026-10-21 („przeniesienie całego stylu komórki Pliku
zbiorczego”) zostaje odrzucony: krój, rozmiar i obramowanie nie przechodzą z
Pliku zbiorczego, tylko wynikają z reguły i z nagłówka Wzorca rozliczenia
pracownika. Z Pliku zbiorczego przechodzi teraz dodatkowo tylko format liczby.

Kontrola `verify-kopia-wzorca` ma piątą regułę `WYGLAD_WIERSZA`, wyprowadzoną z
reguły, a nie z kodu, bo błąd wspólny obu dróg zapisu nie byłby widoczny w
porównaniu kopii z openpyxl.

## Zmiana z 2026-10-22: jeden Wiersz danych i jeden zapis trzech plików z Wzorca

Po zmianach wyżej Wiersze danych trafiały do Wzorca trzema drogami z trzema
kształtami wiersza: `DataRow` Przebiegu rozliczeń, `CollectiveFileRow` kopii
Pliku zbiorczego i komórki Rejestru z `CellFormat` w zapisie przez openpyxl.
Wyróżnienia komórek Rejestru powstawały z pominięciem normalizacji pustego
wypełnienia z `Highlights.of`, więc ten sam wygląd mógł dać dwie różne wartości
`Highlights`. Przygotowanie samo liczyło kolumny pod nagłówkami, scalenia,
kolumny Wyglądu Wiersza danych, wysokość wiersza, autofiltr i kolejność
Hiperłącza przed wartością, a zapis Rozliczenia pracownika przez openpyxl
powtarzał część tych reguł osobno.

Teraz:

- Każdy plik z Wzorca powstaje przez `workbook_files.TemplateFile` w jednym z
  trzech układów (`Layout`): Rozliczenie pracownika, Plik zbiorczy, Rozliczenie
  wewnętrzne. `check()` to Sprawdzanie, `plan()` to Planowanie, a `create()`
  zapisuje plik. Układ wyznacza wiersz nagłówka i pierwszy Wiersz danych,
  nagłówek WYKONAWCA w H17, kolumny wyglądu, flagi przeliczania, autofiltr,
  kontrolę Szablonu pracownika i to, czy plik może powstać kopią. Rozliczenie
  wewnętrzne nadal powstaje tylko przez openpyxl. Wybór między kopią a openpyxl
  i reguły kopii z decyzji wyżej się nie zmieniają.
- Wiersz danych ma jeden kształt (`DataRow`): wartości komórek po kolei, ich
  Wyróżnienia, formaty liczb i Hiperłącza. Odczyt Pliku zbiorczego daje go z
  formatami liczb kolumn wyglądu A:L, odczyt Rejestru zleceń z formatem liczby
  każdej przenoszonej komórki.
- Wyróżnienia komórek Rejestru są czytane tą samą regułą co komórek Pliku
  zbiorczego (`Highlights.of`: wypełnienie bez wzoru to brak wypełnienia).
- Przygotowanie podaje tylko nagłówki docelowe kolumn Rejestru. Kolumny pod
  nagłówkami i scalenia w komórkach zapisu liczy `TemplateFile` z tego samego
  wczytania Wzorca, z którego powstaje plik, a zły układ zgłasza z miejscem
  (`MissingHeader`, `MergedCells`). Przygotowanie tłumaczy go na te same
  Komunikaty co dotąd.

Skutki dla plików:

- Rozliczenia pracowników: bez zmian, bajt w bajt.
- Plik zbiorczy z kopii: bez zmian, bajt w bajt, z jednym wyjątkiem: komórka
  Rejestru z wypełnieniem bez wzoru, ale z kolorem innym niż domyślny, dostaje
  puste wypełnienie, takie jak komórka bez Wyróżnień, zamiast kopii tego
  wypełnienia. W Excelu obie wyglądają tak samo.
- Rozliczenie wewnętrzne i Plik zbiorczy drogą openpyxl: to, co widać w Excelu,
  bez zmian, z tym samym wyjątkiem.
- Znak niedozwolony w XML zatrzymuje zapis każdego pliku z Wzorca tym samym
  błędem `WorkbookSaveError` na obu drogach. Dotąd kopia Pliku zbiorczego
  wracała wtedy do openpyxl, a droga openpyxl (zawsze w Rozliczeniu
  wewnętrznym) kończyła się nieoczekiwanym wyjątkiem. Przygotowanie zatrzymuje
  się teraz z `BLAD_ZAPISU`, Przebieg rozliczeń jak dotąd z
  `BLAD_SZABLONU_PRACOWNIKA`. Odczyt Rejestru i Pliku zbiorczego przez openpyxl
  takich wartości nie daje.

Na kopiach danych taty (31 okresów z obu Rejestrów, wszystkie, z których
Przygotowanie zapisuje pliki) Pliki zbiorcze i Rozliczenia pracowników po tej
zmianie mają te same bajty co przed nią (31 i 837 plików; wyjątek wyżej nie
wystąpił), a Rozliczenie wewnętrzne nie różni się w żadnej kategorii bramki
`tools/porownanie_rozliczen.py`.

Odrzucone kierunki:

- **Rozliczenie wewnętrzne kopią Wzorca.** To zmiana wydajności z własnym
  pomiarem, nie ujednolicenie. Tabela `Layout` pozwala ją zrobić osobno.
- **Wiersz jako krotka komórek** (wartość, Wyróżnienia, Hiperłącze i format
  liczby w jednym obiekcie). Kopia i oba odczyty pracują kolumnami; obiekt na
  komórkę to dziesiątki tysięcy obiektów więcej przy każdym odczycie Pliku
  zbiorczego.

Testy właściciele: `tests/test_workbook_files.py` (Rozliczenie pracownika) i
`tests/test_plik_zbiorczy_kopia_wzorca.py` (Plik zbiorczy) porównują plik z
kopii z plikiem z bliźniaka tego samego Wzorca z komentarzem XML w danych
arkusza, którego kopia nie przyjmuje, więc powstaje drogą openpyxl. Żaden test
nie podmienia wnętrza modułu, żeby wybrać drogę.

## Zmiana z 2026-10-24: plik z Wzorca w osobnym module

Decyzja się nie zmienia; zmienia się tylko miejsce kodu. `TemplateFile` jest
w `template_file.py`, a `workbook_files.py` tylko otwiera i czyta skoroszyty.
Atomowy zapis z przywróceniem `xl/externalLinks/*` jest w `workbook_save.py`.
Układ arkusza Wzorca opisuje jeden `template_copy.SheetLayout`, z którego czytają
obie drogi zapisu; plik wybiera konstruktor (`TemplateFile.worker_settlement`,
`collective_file`, `internal_settlement`) zamiast wyliczenia `Layout`.
`TemplateFile.create` podaje drogę, którą powstał plik (`Route.COPY` albo
`Route.OPENPYXL`), więc kontrola `verify-kopia-wzorca` nie podmienia wnętrza
modułu. Rozliczenie wewnętrzne nadal powstaje tylko przez openpyxl i bez flag
przeliczania: kopia zawsze je ustawia, więc droga przez openpyxl ustawia je
dokładnie dla plików, które mogą powstać kopią.

Komórka Wiersza danych niesie razem wartość, Wyróżnienia, format liczby i
Hiperłącze (`workbook_files.DataCell`). Wiersz danych Pliku zbiorczego
(`DataRow`) ma komórki A:AT po kolumnie i każda trafia do tej samej kolumny
Rozliczenia pracownika. Wiersz Rejestru zleceń (`RegisterRow`) ma komórki pod
nagłówkiem docelowym, a `TemplateFile` pliku okresu wpisuje każdą do kolumny
pod tym nagłówkiem we Wzorcu. Nagłówki docelowe są częścią układu pliku okresu,
więc konstruktor `TemplateFile` nie dostaje ich z wywołania. Kopia Pliku
zbiorczego szuka ich w A:K, więc w dowolnej kolejności zajmują wszystkie kolumny
od A; Rozliczenie wewnętrzne nadal zapisuje openpyxl.

## Zmiana z 2026-11-08: Rozliczenie wewnętrzne z kopii Wzorca

Po zmianach wspinaczki „Przygotowanie pliku zbiorczego poniżej sekundy”
Rozliczenie wewnętrzne zostało jedynym plikiem Przygotowania, który powstawał
pełnym wczytaniem i zapisem Wzorca przez openpyxl: na runnerze Windows, który
odpowiada laptopowi taty, 0,41 s w profilu, z czego zapis 0,26 s, a
Sprawdzanie wczytywało ten Wzorzec przez openpyxl osobno.

Teraz Rozliczenie wewnętrzne powstaje tą samą kopią co Plik zbiorczy, jako plik
okresu: autofiltr i nazwa `_xlnm._FilterDatabase` obejmują nagłówek i wpisane
wiersze, a Wygląd Wiersza danych mają kolumny A:M. Sprawdzanie i Planowanie
czytają jego zarys z tego samego odczytu. Droga przez openpyxl zostaje zapasowa
tak jak dla Pliku zbiorczego.

Flagi przeliczania są częścią układu pliku (`SheetLayout.recalculation`), a obie
drogi zapisu ustawiają w `calcPr` te same:

- Rozliczenie pracownika i Plik zbiorczy dostają jak dotąd `calcMode="auto"`,
  `fullCalcOnLoad="1"` i `forceFullCalc="1"` (`Recalculation.FORCED`).
- Rozliczenie wewnętrzne dostaje tylko `fullCalcOnLoad="1"`
  (`Recalculation.ON_LOAD`). Tyle miało dotąd: openpyxl zapisuje
  `fullCalcOnLoad="1"`, gdy Wzorzec go nie ma (wartość domyślna
  `CalcProperties`), a Wzorzec taty ma `<calcPr calcId="191029"/>`. „Bez flag
  przeliczania” ze zmiany z 2026-10-24 znaczyło więc bez `calcMode` i
  `forceFullCalc`. Jedyna różnica wobec dawnej drogi: Wzorzec z
  `fullCalcOnLoad="0"` dostaje teraz `1` na obu drogach. Żaden Wzorzec taty
  go nie ma.

Kopia czyta nagłówek pliku okresu tylko w kolumnach danych wejściowych A:K, a
droga przez openpyxl szuka nagłówków docelowych Rozliczenia wewnętrznego w
całym wierszu 1 i wpisuje pod ostatnim wystąpieniem każdego z nich. Kopia
przyjmuje więc Wzorzec tylko wtedy, gdy oba miejsca to ta sama kolumna; Wzorzec
z nagłówkiem docelowym dalej niż K albo powtórzonym za K idzie przez openpyxl.
U taty nagłówki docelowe zajmują A:K bez powtórzeń.

Poza tym, co widać w Excelu, kopia zachowuje części Wzorca, które openpyxl
pomijał albo zastępował: ustawienia drukarki
(`xl/printerSettings/printerSettings1.bin` i `r:id` w `pageSetup`) i tabelę
tekstów wspólnych Wzorca. Wzorzec bez motywu zostaje bez motywu, a openpyxl
dopisywał domyślny.

Wynik na dwóch kopiach Rejestru taty z Wzorcami taty i na syntetycznym
Rejestrze z jego Wzorcami (okres 15_21_09_2026): Rozliczenie wewnętrzne z kopii nie
różni się od zapisanego przez openpyxl w żadnej kategorii bramki
`tools/porownanie_rozliczen.py`, a także w szerokościach kolumn, widoku,
blokadzie wierszy, autofiltrze, ustawieniach wydruku, formatowaniu
warunkowym, walidacji danych, `calcPr` i nazwach zdefiniowanych. Plik zbiorczy
ma te same bajty co przed zmianą. Na Macu M4 Max `TemplateFile.create`
Rozliczenia wewnętrznego trwa 29 ms zamiast 62 ms (mediana 9 zimnych
przebiegów), a Zapisywanie 85 ms zamiast 119 ms.

Odrzucony 2026-10-22 kierunek „Rozliczenie wewnętrzne kopią Wzorca” jest tą
zmianą wydajności z własnym pomiarem.

Testy właściciele: `tests/test_plik_zbiorczy_kopia_wzorca.py` porównuje oba
pliki okresu z obu dróg zapisu, także dla Wzorca z nagłówkiem docelowym za K
albo powtórzonym za K, a
`tests/test_workbook_files.py` sprawdza flagi przeliczania Rozliczenia
wewnętrznego na obu drogach.
