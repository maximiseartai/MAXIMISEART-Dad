# ADR 0012: Ilości usług wpisuje Przygotowanie pliku zbiorczego według Reguł ilości utrzymywanych przez Maksa

## Status

Zaakceptowana. Zmienia zakres z README: „automatyczne uzupełnianie ilości 0/1
w kolumnach `N:AP` Pliku zbiorczego” przestaje być poza zakresem narzędzia.
Dopełniają go
[ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md) (Kontrola ilości),
[ADR 0016](0016-uzupelnienie-pliku-zbiorczego-w-centrum.md) (Uzupełnienie
pliku zbiorczego w Centrum, które Pliku zbiorczego nie zmienia) i
[ADR 0018](0018-ilosci-tylko-dla-inea-nie-przechodza-do-rozliczenia-pracownika.md)
(Ilości tylko dla INEA nie przechodzą do Rozliczenia pracownika).

[ADR 0033](0033-reguly-ilosci-naleza-do-taty.md) zmienia punkt „Reguły ilości są w repozytorium narzędzia i utrzymuje je
Maks” i odrzucony wariant „Plik reguł edytowany przez tatę”: Reguły ilości tata
zmienia sam w Ustawieniach Centrum.

## Kontekst

Tata wpisuje Ilości usług do gotowego Pliku zbiorczego ręcznie, około dwóch
godzin tygodniowo, czytając w każdym wierszu `URZĄDZENIA` i `CZYNNOŚCI
ZREALIZOWANE`. Część ilości wynika z treści zlecenia według spisanej przez
niego instrukcji, a część tylko z opisu technika. Na dwóch prawdziwych
tygodniach (852 wiersze) instrukcja zgadza się z jego wpisami w kolumnach,
które opisuje. Rozbieżności dotyczą prawie wyłącznie kolumn wynikających z
opisu technika.

## Decyzja

- **Ilości usług powstają razem z Plikiem zbiorczym.** Wpisuje je
  Przygotowanie pliku zbiorczego. Nie ma osobnego kroku, który zmieniałby
  istniejący Plik zbiorczy. Okresy przygotowane wcześniej zostają bez zmian.
- **Narzędzie stosuje tylko Reguły ilości.** Ilości wynikające z opisu
  technika (Last drop MDU, spawania, sieć domowa, modyfikacja sieci) wpisuje
  tata, także w kolumnach, które Reguły ilości już częściowo wypełniły.
  Narzędzie nie zgaduje ich z tekstu.
- **Reguły ilości są w repozytorium narzędzia i utrzymuje je Maks.** Tata
  zgłasza zmiany, które zdarzają się raz albo dwa razy w roku. Do taty trafiają
  przez Aktualizację narzędzia, a test sprawdza je z każdą linią instrukcji
  taty.
- **`URZĄDZENIA` są czytane jako składniki** (np. `nokia zte`, `n*fut`,
  `n*wifi6extra`). Nowe kombinacje znanych składników nie wymagają nowej
  reguły.
- **Wiersz, którego Reguły ilości nie obejmują, nie zatrzymuje procesu.**
  Wiersz ze składnikiem, którego Reguły ilości nie znają, dostaje tylko ilości
  niezależne od `URZĄDZENIA`. Wiersze rozliczane z opisu (prewencja,
  niedostępność usług, puste `URZĄDZENIA`) zostają bez ilości. Uruchomienie
  kończy się wynikiem wymagającym sprawdzenia. Ostrzeżenia podają numery obu
  rodzajów wierszy i przypominają o kolumnach z opisu technika.
- **Sprawdzenia wymaga zapisany Plik zbiorczy, a nie podgląd.** Przypomnienie
  o kolumnach z opisu technika jest zawsze, więc każde Przygotowanie z zapisem
  wymaga sprawdzenia. Podgląd bez zapisu pokazuje te same ostrzeżenia, ale
  kończy się wynikiem OK: tacie zostaje `Uruchom`, a podgląd liczy się jako
  udany. Ostrzeżeń ilości nie da się usunąć przed zapisem, bo dotyczą pliku,
  który dopiero powstanie.
- **Plik wygląda tak, jakby wypełnił go tata.** Zera zostają tylko tam, gdzie
  ma je Wzorzec pliku zbiorczego. Komórki wypełnione przez narzędzie nie są
  oznaczane, bo Wyróżnienia przechodzą do Rozliczeń pracowników.
- **Wdrożenie bez trybu cienia.** Błędy reguł mają wychodzić na jaw z
  porównania Ilości usług z Plikiem zbiorczym po poprawkach taty, a nie z
  kilkutygodniowego okresu próbnego.

## Odrzucone warianty

- **Osobny krok w Centrum na gotowym Pliku zbiorczym.** Zmieniałby plik, który
  tata mógł już edytować, wbrew Nienadpisywaniu.
- **Plik reguł edytowany przez tatę.** Tata woli zgłaszać zmiany. Jego
  instrukcja miała literówki (`3*fut` → Z=2, `6*fut lub 2*globo`), które w
  edytowanym przez niego pliku przeszłyby bez testu.
- **Zgadywanie ilości z opisu technika.** Daje fałszywe trafienia, a ADR 0001
  wymaga deterministycznego silnika. Wracamy do tego dopiero po pomiarze.
- **Lista pełnych wpisów `URZĄDZENIA` 1:1 z instrukcji.** Każda nowa
  kombinacja wymagałaby nowej linii.
