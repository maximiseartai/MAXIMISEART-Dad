# Research: Microsoft Graph, zapis i odczyt INTERMAX w firmowym OneDrive

Data researchu: 2026-11-08.
Ticket #1147, mapa #1145 („Centrum w chmurze”).

Pytanie: czy serwer w chmurze może czytać i zapisywać Rejestr zleceń w firmowym
OneDrive (Microsoft 365 Business) bez konfliktów z tatą i Andrzejem, którzy
pracują w nim w Excelu?

Każde twierdzenie ma znacznik:

- **[docs]**: dokumentacja Microsoft mówi to wprost (źródło w nawiasie, lista na końcu);
- **[wniosek]**: wynika z kilku zdań dokumentacji, ale żadne nie mówi tego wprost;
- **[test]**: dokumentacja milczy albo jest niejednoznaczna; rozstrzygnie dopiero
  test na żywo w tenancie próbnym (lista testów niżej).

## Wniosek

1. **Zapis komórek przez Graph to tylko uprawnienia delegowane.**
   Excel workbook API (sesja, odczyt i zapis zakresu) ma w tabeli uprawnień
   „Application: Not supported”, a najwęższe delegowane to `Files.ReadWrite`
   [docs: S3, S4, S5].
   Serwer musi więc działać jako użytkownik (konto techniczne albo konto taty)
   z odświeżanym tokenem, a nie jako sama aplikacja.
   Domyślny refresh token żyje 90 dni i odnawia się przy każdym użyciu, a
   unieważnia go między innymi administrator albo zmiana hasła [docs: S20].
2. **Zapis przez Graph przy otwartym pliku jest możliwy tylko jako współedycja,
   a dokumentacja nie opisuje, co wtedy widzi Excel desktop.**
   Workbook API zwraca `accessConflict`, gdy „inny klient zablokował skoroszyt
   do edycji” [docs: S7], a współedycję w Excelu psuje każdy, kto otworzy plik
   wersją bez współedycji: wtedy „wszyscy inni” dostają błąd „plik zablokowany”
   [docs: S8].
   Czy zmiana z sesji Graph pojawi się u taty po kilku sekundach jak zmiana
   współautora: **[test]**.
3. **Graph nie mówi, które komórki zmienił człowiek.**
   Powiadomienia (webhooki) w OneDrive for Business da się założyć tylko na
   katalog główny dysku, a nie na plik, i mają średnie opóźnienie poniżej
   minuty, a maksymalne 6 godzin [docs: S10, S11, S12].
   Powiadomienie nie mówi, co się zmieniło; trzeba zapytać `delta` [docs: S13],
   a `delta` mówi tylko, że plik się zmienił [docs: S14].
   Zmienione komórki trzeba więc wyliczyć samemu: pobrać nową wersję pliku i
   porównać ją z poprzednią (wersje i ich autorów zwraca Graph [docs: S16]).
4. **Formatowanie tak, Hiperłącza nie.**
   Wypełnienie, czcionkę (z pogrubieniem i rozmiarem), ramki, wyrównanie,
   wysokość wiersza i szerokość kolumny da się zapisać [docs: S17, S18, S19].
   Zakres w Graph v1.0 nie ma żadnej właściwości ani metody Hiperłącza
   [docs: S6]; zostaje tylko formuła `=HYPERLINK()`, która nie jest tym samym
   co Hiperłącze w `NUMER ZL.` w INTERMAX.
5. **Limity nie są problemem dla rozmiaru INTERMAX, ale wymuszają dzielenie
   odczytu.**
   Excel w przeglądarce otwiera pliki do 100 MB [docs: S9], a INTERMAX ma
   ok. 6,5 MB.
   Jedno żądanie Excela w przeglądarce ma limit 5 MB, a odczyt zakresu
   5 mln komórek [docs: S15]; 42 tys. wierszy trzeba czytać kawałkami.
   Graph ogranicza Excel API do 1500 żądań na 10 s na aplikację w tenancie
   [docs: S2], a SharePoint do 1250 jednostek na minutę i 1,2 mln na dobę na
   aplikację w tenancie do 1000 licencji [docs: S21].

**Rekomendacja w skrócie** (szczegóły w ostatniej sekcji): nie budować
dwukierunkowej synchronizacji na żywym INTERMAX.
W pierwszym etapie serwer tylko czyta INTERMAX (pobiera cały plik po zmianie
`cTag`, czyta go obecnym czytnikiem i porównuje z poprzednią wersją).
Po przełączeniu źródłem prawdy jest baza, a Excel dostaje lustro generowane
przez serwer, w którym poprawki taty wracają jako propozycje do zatwierdzenia,
a nie jako automatyczne scalenie.

## 1. Zapis komórek przy otwartym pliku

### Co mówi dokumentacja

- Workbook API działa tylko na plikach w OneDrive for Business, SharePoint i
  dyskach grup, a nie w OneDrive prywatnym [docs: S1].
- Obsługuje tylko format Office Open XML; `.xls` nie działa [docs: S1].
- Są trzy tryby: sesja trwała (zmiany zapisują się w pliku), sesja nietrwała
  (zmiany giną po wygaśnięciu sesji) i żądanie bez sesji, które też zapisuje
  zmiany, ale jest wolniejsze [docs: S1].
- Sesja trwała wygasa po ok. 5 min bez aktywności, nietrwała po ok. 7 min;
  wygasła sesja daje `404` [docs: S1].
- Utworzenie sesji na dużym pliku może trwać dłużej niż limit żądania; jest wtedy
  wzorzec długiej operacji (`Prefer: respond-async`, `202 Accepted`, odpytywanie
  co ok. 30 s, najwyżej co 4 min) [docs: S3].
- Microsoft odradza równoległe zapisy do jednego skoroszytu: „często są przyczyną
  throttlingu, timeoutu (…), konfliktu scalenia (gdy biorą w nim udział równoległe
  sesje)”, i zaleca wysyłać następne żądanie dopiero po odpowiedzi na poprzednie
  [docs: S3].
- Kody błędów, które wprost mówią o innym kliencie [docs: S7]:
  - `accessConflict`: żądanie koliduje z innym klientem, „np. inny klient zablokował
    skoroszyt do edycji”; nie ponawiać, dopóki konflikt trwa;
  - `invalidSessionAccessConflict`: to samo, ale sesja jest już nieważna;
  - `invalidSessionUnsupportedWorkbook`: skoroszyt ma nieobsługiwane funkcje albo
    przekracza limit rozmiaru, „zwykle wprowadzone przez innego klienta”;
  - `insertDeleteConflict`, `filteredRangeConflict`: wstawianie albo usuwanie
    koliduje z innymi danymi albo z filtrem.
- Instrukcje błędów każą użytkownikowi „wykonać te same operacje w Excel Online”,
  żeby zobaczyć szczegóły [docs: S7].

**[wniosek]** API liczy skoroszyt tym samym silnikiem po stronie serwera co Excel
w przeglądarce (stąd odesłania do Excel Online i ten sam limit rozmiaru), więc dla
taty sesja Graph jest jeszcze jednym współautorem.
Dokumentacja nie mówi tego jednym zdaniem.

### Współedycja w Excelu: co mówi wsparcie Microsoft

Z artykułu o współedycji [docs: S8]:

- współedycja wymaga Microsoft 365 i najnowszej wersji Excela dla Microsoft 365
  (Windows, Mac, przeglądarka, telefon);
- działa na `.xlsx`, `.xlsm` i `.xlsb`, nie działa na „Strict Open XML”;
- plik musi leżeć w OneDrive, OneDrive for Business albo SharePoint Online, a
  Autozapis musi być włączony;
- najczęstsza przyczyna błędu „plik zablokowany”: ktoś otworzył plik wersją Excela
  bez współedycji, a „jeśli zrobi to choć jedna osoba, wszyscy pozostali dostaną
  błąd zablokowania”;
- zmiany innych widać „w ciągu kilku sekund”, czasem „minuty albo dwóch”;
- przy konflikcie „wygrywa ostatnia zapisana zmiana” (przyciskiem Zapisz albo
  Autozapisem);
- funkcja nie w pełni obsługiwana we współedycji daje „Zalecane odświeżenie” albo
  „Przekazywanie nie powiodło się” i może chwilowo zatrzymać współedycję.

### Odpowiedzi na pytania z ticketu

| Sytuacja u taty albo Andrzeja | Co wiemy | Znacznik |
|---|---|---|
| Excel desktop z Autozapisem | Współedycja działa między ludźmi; sesja Graph jest dla Excela kolejnym klientem. Czy tata zobaczy zapis z Graph po kilku sekundach i czy nie dostanie „Zalecane odświeżenie”, nie jest opisane. | [docs] + [test] |
| Excel w przeglądarce | Ten sam silnik co Graph; współedycja w przeglądarce jest obsługiwana. | [wniosek] + [test] |
| Excel dla Microsoft 365 bez Autozapisu | Dokumentacja mówi tylko, że wszyscy potrzebują Autozapisu, żeby widzieć zaznaczenia innych, i że wygrywa ostatni zapis. Co dzieje się z zapisem Graph, gdy tata potem ręcznie zapisze plik, nie jest opisane. | [test] |
| Starszy Excel (bez współedycji) | Plik zostaje zablokowany dla wszystkich pozostałych. Graph dostanie wtedy najpewniej `accessConflict`. | [docs] + [wniosek] |
| Plik `.xls` albo Strict Open XML | `.xls` nie działa w Graph; Strict nie działa we współedycji. INTERMAX to `.xlsx`; czy nie jest zapisany jako Strict, łatwo sprawdzić na kopii (przestrzeń nazw w `xl/workbook.xml`). | [docs] |
| Plik otwarty z folderu synchronizowanego OneDrive | Współedycja z pliku otwartego z dysku zależy od ustawienia klienta OneDrive „Użyj aplikacji pakietu Office do synchronizowania otwieranych plików”. Jedyne źródła to wątki Microsoft Q&A (źródło wtórne): bez tego ustawienia OneDrive przesyła cały plik i przy konflikcie tworzy kopię z nazwą komputera. | [test] |

### Zastąpienie całego pliku zamiast zapisu komórek

To jest obecny sposób z ADR 0019 (podmiana części XML, cały plik zapisany od nowa).
W chmurze odpowiada mu `PUT /drives/{id}/items/{id}/content` [docs: S22].

- Działa z uprawnieniem aplikacyjnym (`Files.ReadWrite.All`) [docs: S22], a
  dokumentacja Selected mówi, że `Files.SelectedOperations.Selected` daje dostęp
  do jednego pliku jak `Files.ReadWrite.All` [docs: S23].
  Tabela uprawnień samego `PUT …/content` nie wymienia jednak
  `Files.SelectedOperations.Selected`: **[test]**.
- Nagłówek `if-match` z `eTag` daje `412 Precondition Failed`, gdy plik zmienił się
  od odczytu [docs: S24, S25]; to odpowiednik obecnej „inna wersja, którą OneDrive
  wgrał w przerwie, daje Zatrzymanie”.
- Graph ma kod `423 Locked` dla zablokowanego zasobu [docs: S25].
- Co dzieje się u taty, gdy ktoś podmieni plik, który on właśnie edytuje we
  współedycji, nie jest opisane: **[test]**.
  Artykuł o współedycji sugeruje „Zalecane odświeżenie” albo utratę jednej ze
  stron („wygrywa ostatni zapis”) [docs: S8], więc to ryzyko traktujemy jako
  realne, dopóki test go nie wykluczy.

## 2. Wykrywanie zmian zrobionych przez człowieka

### Co mówi dokumentacja

- **Webhooki (subskrypcje):** w OneDrive for Business subskrypcję da się założyć
  „tylko na katalog główny”; nie na plik ani podfolder [docs: S11].
  Dla katalogu głównego dysku obsługiwany jest tylko `changeType` `updated`
  [docs: S10].
  Subskrypcja żyje najwyżej 42 300 minut (poniżej 30 dni) i trzeba ją odnawiać
  [docs: S10].
  Opóźnienie dla `driveItem`: średnio poniżej 1 minuty, najwyżej 6 godzin
  [docs: S10, S12].
  Uprawnienie: `Files.Read.All` (delegowane albo aplikacyjne) [docs: S11].
  Powiadomienie „nie zawiera żadnej informacji o zmianach”; aplikacja ma
  zapytać `delta` [docs: S13].
  Nieudane doręczenie jest ponawiane przez 15 minut, potem porzucane [docs: S13].
- **Delta:** zwraca listę zmienionych elementów (pliki i foldery), najnowszy stan
  każdego, a nie każdą zmianę [docs: S14].
  Działa na katalogu głównym dysku; najwęższe uprawnienie aplikacyjne to
  `Files.Read.All` [docs: S14].
  Zapytanie z tokenem kosztuje 1 jednostkę SharePoint [docs: S21].
  Stary token może dać `410 Gone` i wymusić pełne wyliczenie od nowa [docs: S14].
- **Pojedynczy plik:** `driveItem` ma `cTag`, który „nie zmienia się, gdy zmienią
  się tylko metadane”, oraz `lastModifiedBy` i `lastModifiedDateTime` [docs: S26].
  Odczyt jednego elementu kosztuje 1 jednostkę [docs: S21].
- **Wersje:** `GET …/versions` zwraca wersje od najnowszej, z autorem i czasem;
  co ile powstaje wersja, zależy od konfiguracji („przy każdej edycji, przy każdym
  zapisie, ręcznie albo nigdy”) [docs: S16].
- **Zmienione komórki:** żadne API Graph ich nie zwraca. **[wniosek]**: trzeba
  pobrać dwie wersje i porównać je samemu.

### Co z tego wynika dla INTERMAX

**[wniosek]** Dla jednego pliku najprostsze i najwęższe jest odpytywanie `cTag`
co kilka-kilkanaście sekund (koszt: 6 jednostek na minutę przy co 10 s, przy
limicie 1250 na minutę), a po zmianie pobranie pliku (1 jednostka [docs: S21])
i porównanie z poprzednim odczytem obecnym czytnikiem bajtów skoroszytu.
Webhook wymagałby subskrypcji na cały OneDrive taty z `Files.Read.All` i i tak
kończyłby się tym samym pobraniem pliku.

**[wniosek]** Jeśli INTERMAX trafi do biblioteki witryny SharePoint (zamiast
OneDrive taty), subskrypcja może dotyczyć tylko tej listy (`/sites/{id}/lists/{id}`,
to samo opóźnienie) [docs: S12], ale wymaga `Sites.Read.All` [docs: S11].

Opóźnienie wykrycia zmiany taty zależy też od tego, kiedy Excel taty wyśle zmianę
do OneDrive (Autozapis: kilka sekund według [docs: S8]; ADR 0016 zapisał, że na
laptopie taty nie udało się tego potwierdzić): **[test]**.

## 3. Rejestracja aplikacji i uprawnienia

### Co mówi dokumentacja

| Uprawnienie | Co daje | Zgoda administratora |
|---|---|---|
| `Files.ReadWrite` (delegowane) | pliki zalogowanego użytkownika | nie [docs: S27] |
| `Files.ReadWrite.All` (delegowane) | wszystkie pliki, do których użytkownik ma dostęp | nie [docs: S27] |
| `Files.ReadWrite.All` (aplikacyjne) | wszystkie pliki we wszystkich witrynach, bez użytkownika | tak [docs: S27] |
| `Files.SelectedOperations.Selected` (delegowane i aplikacyjne) | tylko pliki, którym nadano aplikacji uprawnienie | tak, w obu trybach [docs: S27] |
| `Sites.Selected` | jedna witryna (zbiór witryn) | tak [docs: S23] |

- Zakresy „Selected” działają w trzech krokach: zgoda w Entra ID, nadanie
  uprawnienia konkretnemu zasobowi (`POST …/items/{id}/permissions` z rolą
  `read`, `write`, `owner` albo `fullcontrol`) i token z tym zakresem; bez
  któregoś kroku aplikacja nie ma dostępu [docs: S23, S28].
- W trybie delegowanym dostęp to część wspólna uprawnień aplikacji i użytkownika
  [docs: S23].
- Nadanie uprawnienia plikowi wymaga `Sites.FullControl.All` albo `Sites.Selected`
  lub `Lists.SelectedOperations.Selected` z rolą `owner`/`fullcontrol` na
  nadrzędnym zasobie [docs: S23]; to jednorazowa czynność administratora.
- Nadanie uprawnienia aplikacji plikowi przerywa dziedziczenie uprawnień na tym
  pliku [docs: S23].
- Workbook API: najwęższe `Files.ReadWrite` (delegowane), aplikacyjne
  „Not supported”, także w beta [docs: S3, S4, S5].

### Co z tego wynika

- **[wniosek]** Odczyt i zastąpienie całego pliku mogą działać z najwęższym
  zakresem aplikacyjnym `Files.SelectedOperations.Selected` na jednym pliku,
  bez użytkownika i bez dostępu do reszty OneDrive taty.
  Że Graph przyjmie ten zakres dla pobrania, `PUT …/content`, `versions` i
  `GET` elementu: **[test]** (tabele tych metod go nie wymieniają).
- **[wniosek]** Zapis komórek przez Workbook API wymaga konta użytkownika w
  tenancie i tokenu delegowanego.
  `Files.ReadWrite` obejmuje tylko pliki tego użytkownika [docs: S27], więc dla
  konta technicznego, któremu INTERMAX jest udostępniony, potrzebne jest
  `Files.ReadWrite.All` (delegowane) albo `Files.SelectedOperations.Selected`
  (delegowane).
  Czy Workbook API przyjmie którykolwiek z nich, skoro jego tabela podaje tylko
  `Files.ReadWrite` i „wyższe: niedostępne”: **[test]**.
- Czy konto techniczne potrzebuje płatnej licencji Microsoft 365 i jak MFA oraz
  zasady dostępu warunkowego tenanta wpływają na token serwera: nie badaliśmy
  tego tutaj; do ustalenia przy rejestracji aplikacji.
- Zgodę administratora daje administrator tenanta firmy (rola Maksa jako admina
  z mapy #1145).

## 4. Limity i czas operacji

| Limit | Wartość | Źródło |
|---|---|---|
| Excel API, na aplikację w tenancie | 1500 żądań na 10 s | [docs: S2] |
| Excel API, throttling | bez stałych liczb; zależy od skoroszytu i żądania; zaleca sekwencyjne żądania i honorowanie `Retry-After` | [docs: S3] |
| Rozmiar żądania i odpowiedzi w Excelu w przeglądarce | 5 MB | [docs: S15] |
| Odczyt zakresu | 5 mln komórek | [docs: S15, S1] |
| Duży zakres | może dać błąd; czytać i zapisywać mniejszymi kawałkami | [docs: S1] |
| Zakres bez granic (`A:F`, `2:2`) | odczyt daje `null` dla wartości; zapis wartości i formatów liczb niedozwolony | [docs: S1] |
| Plik w Excelu w przeglądarce (SharePoint Online) | 0–100 MB | [docs: S9] |
| `PUT …/content` | do 250 MB | [docs: S22] |
| SharePoint, na aplikację w tenancie (0–1000 licencji) | 1250 jednostek na minutę, 1 200 000 na dobę | [docs: S21] |
| SharePoint, użytkownik | 3000 żądań na 5 min | [docs: S21] |
| Koszt w jednostkach | 1: odczyt elementu, delta z tokenem, pobranie pliku; 2: lista, utworzenie, zmiana, wysłanie pliku; 5: operacje na uprawnieniach | [docs: S21] |

**[wniosek]** dla INTERMAX (ok. 42 tys. wierszy, 4 arkusze, ok. 6,5 MB):

- rozmiar pliku mieści się w limicie Excela w przeglądarce z dużym zapasem;
- arkusz zleceń ma kilkaset tysięcy komórek do kolumny `UWAGI`, więc pełny
  odczyt przez Workbook API to kilka-kilkanaście żądań po kilka tysięcy wierszy;
  pobranie całego pliku (1 żądanie, 1 jednostka) i odczyt obecnym czytnikiem jest
  prostsze i tańsze;
- dokumentacja nie podaje czasu otwarcia sesji ani zapisu dla pliku tej
  wielkości; mówi tylko, że otwarcie dużego skoroszytu może trwać „nieokreślony
  czas” [docs: S3]: **[test]**;
- czy arkusz zleceń (ok. 43 MB XML po rozpakowaniu, ADR 0019) nie przekroczy
  wewnętrznych limitów Excela w przeglądarce (`unsupportedWorkbook`): **[test]**.

## 5. Formatowanie i Hiperłącza

| Co | Przez Graph | Źródło |
|---|---|---|
| Wartości, formuły, format liczb | tak (`PATCH …/range`) | [docs: S4] |
| Wypełnienie (kolor) | tak (`format/fill`) | [docs: S17] |
| Czcionka: nazwa, rozmiar, pogrubienie, kolor | tak (`format/font`) | [docs: S18] |
| Ramki: styl (`Continuous`…), grubość (`Thin`…), kolor, każda krawędź | tak (`format/borders`) | [docs: S19] |
| Wyrównanie, zawijanie, wysokość wiersza, szerokość kolumny | tak (`format`) | [docs: S17] |
| Wstawienie i usunięcie zakresu z przesunięciem, scalenie, sortowanie | tak | [docs: S6] |
| Hiperłącze komórki | **nie ma** w v1.0 (ani właściwości, ani metody) | [docs: S6] |
| Styl całego wiersza bez komórek (żółty wiersz taty) | brak osobnej metody; zapis formatu na zakresie `2:2` nie jest opisany | [test] |
| Przeniesienie komórek z Hiperłączem (sortowanie, wstawienie) | nie opisane | [test] |
| Aktywny arkusz i widok na dzień (ADR 0019) | nie znaleźliśmy w v1.0 metody aktywacji arkusza ani przewinięcia widoku | [wniosek] + [test] |

**[wniosek]** Uporządkowanie INTERMAX w obecnym kształcie (ADR 0019: Hiperłącza
w `NUMER ZL.` idą razem z komórką, wygląd dnia jak u taty, aktywny arkusz i widok
na dziś) nie da się w pełni zrobić Workbook API.
Da się je zrobić podmianą całego pliku, ale wtedy wraca problem pliku otwartego
(sekcja 1).

## 6. Testy na żywo w tenancie próbnym

Każdy test na syntetycznym pliku w kształcie INTERMAX (4 arkusze, ok. 42 tys.
wierszy, Hiperłącza w `NUMER ZL.`), w tenancie próbnym, nigdy na pliku taty ani
jego kopii (Reguła danych, ADR 0025).
Każdy wynik zapisać z wersją Excela i ustawieniami klienta OneDrive.

1. **Graph przy otwartym Excelu desktop z Autozapisem.** Dwa konta otwierają
   plik w Excelu desktop; serwer w sesji trwałej zapisuje 20 wierszy na dole
   arkusza (wartości, wypełnienie, ramki). Mierzyć: po ilu sekundach zmiana
   widać u obu osób, czy pojawia się „Zalecane odświeżenie”, czy ktoś traci
   swoje wpisy, kody błędów Graph.
2. **To samo w Excelu w przeglądarce** oraz z jedną osobą w desktopie, drugą w
   przeglądarce.
3. **Excel desktop bez Autozapisu.** Osoba edytuje bez zapisu, serwer zapisuje
   przez Graph, osoba zapisuje Ctrl+S. Sprawdzić, czyja zmiana zostaje i czy
   druga ginie bez ostrzeżenia.
4. **Plik otwarty z folderu synchronizowanego OneDrive** z włączonym i
   wyłączonym ustawieniem „Użyj aplikacji pakietu Office do synchronizowania
   otwieranych plików”: czy powstaje kopia z nazwą komputera.
5. **Starsza wersja Excela albo plik w trybie zgodności** (jeśli dostępna):
   potwierdzić blokadę i kod błędu Graph (`accessConflict`?).
6. **Podmiana całego pliku (`PUT …/content` z `if-match`) przy otwartym pliku**
   u jednej i dwóch osób: co widzą, czy ich niezapisane zmiany giną, czy Graph
   zwraca `423` albo `412`.
7. **Uprawnienia:** aplikacja z samym `Files.SelectedOperations.Selected`
   (aplikacyjnym) i rolą `write` na jednym pliku: pobranie, `PUT …/content`,
   `versions`, `GET` z `cTag`, oraz próba dostępu do innego pliku (ma się nie
   udać). To samo w trybie delegowanym dla Workbook API.
8. **Workbook API z kontem, któremu plik udostępniono:** `Files.ReadWrite`,
   `Files.ReadWrite.All` i `Files.SelectedOperations.Selected` (delegowane).
9. **Opóźnienia wykrycia:** tata wpisuje komórkę z Autozapisem; mierzyć czas do
   zmiany `cTag` i do webhooka na katalogu głównym; ile wersji powstaje na godzinę
   pracy.
10. **Czas i limity na pliku wielkości INTERMAX:** utworzenie sesji (czy daje
    `202`), odczyt arkusza kawałkami po 1000, 5000 i 10 000 wierszy, zapis bloku
    20–80 wierszy z formatem; czy pojawia się `unsupportedWorkbook`.
11. **Formatowanie i Hiperłącza:** sortowanie zakresu i wstawienie wierszy z
    przesunięciem nad komórkami z Hiperłączem: czy Hiperłącze idzie z komórką;
    format na całym wierszu (`2:2`).

## Rekomendacja: Excel jako zabezpieczenie w czasie migracji

Kryteria mapy stawiają na pierwszym miejscu współpracę wielu osób w tej samej
chwili, a docelowym źródłem prawdy ma być baza SQL.
Dokumentacja pokazuje, że zapis do żywego INTERMAX w czasie, gdy tata w nim
pracuje, opiera się na niezbadanej współedycji, wymaga konta użytkownika zamiast
samej aplikacji i nie umie zapisać Hiperłączy.
Dlatego Excel powinien być zabezpieczeniem, do którego serwer pisze ostrożnie
albo wcale, a nie drugim źródłem prawdy z dwukierunkowym scalaniem.

**Etap 1: Excel jest źródłem prawdy, serwer tylko czyta.**

- Aplikacja z `Files.SelectedOperations.Selected` (aplikacyjnym, rola `read`) na
  samym INTERMAX; bez konta użytkownika i bez dostępu do reszty OneDrive.
- Serwer co kilkanaście sekund sprawdza `cTag`; po zmianie pobiera plik, czyta go
  obecnym czytnikiem i wylicza różnicę z poprzednim odczytem (kto i kiedy: z wersji
  pliku).
- Baza jest kopią do odczytu: web i telefon pokazują zlecenia 24/7, a codzienne
  porównanie bazy z INTERMAX jest bramą zgodności przed przełączeniem.
- Uporządkowanie INTERMAX zostaje lokalnym procesem z ADR 0019 (plik zamknięty,
  Kopia INTERMAX) albo, jeśli ma przejść do chmury przed przełączeniem, robi
  podmianę całego pliku z `if-match` dopiero po testach 6 i 7 i dalej tylko przy
  zamkniętym pliku.

**Etap 2: baza jest źródłem prawdy, Excel jest lustrem.**

- Wklejanie i porządkowanie zleceń przechodzi do aplikacji; Uporządkowanie działa
  na bazie, a nie na pliku.
- Serwer generuje skoroszyt-lustro w tym samym układzie co INTERMAX (osobny plik,
  nie plik z historią od 2021) i wgrywa go całego z `if-match`, bo to on jest jego
  jedynym autorem; Hiperłącza i wygląd dnia zapisuje własny moduł zapisu, jak dziś.
- Tata może dalej pracować w lustrze. Serwer wykrywa jego zmiany tak jak w etapie 1
  i pokazuje je w aplikacji jako propozycje do zatwierdzenia (Uwagi), a nie scala
  ich sam; następne generowanie lustra zastępuje plik dopiero, gdy propozycje są
  rozstrzygnięte.
- Stary INTERMAX zostaje tylko do odczytu jako archiwum.

**Workbook API (zapis komórek przez Graph)** warto użyć tylko wtedy, gdy testy 1–3
i 8 pokażą, że zapis z sesji Graph pojawia się u taty jak zmiana współautora i
nikt nie traci danych.
Wtedy może dopisywać pojedyncze wiersze (np. statusy z aplikacji) do lustra w
czasie, gdy tata je ma otwarte, z kontem technicznym w trybie delegowanym; nie
nadaje się do Uporządkowania z Hiperłączami.

## Źródła

Wszystkie źródła odczytane 2026-11-08.

- S1: [Working with Excel in Microsoft Graph](https://learn.microsoft.com/en-us/graph/api/resources/excel?view=graph-rest-1.0)
- S2: [Microsoft Graph service-specific throttling limits: Excel service limits](https://learn.microsoft.com/en-us/graph/throttling-limits)
- S3: [Best practices for working with the Excel API](https://learn.microsoft.com/en-us/graph/workbook-best-practice) oraz [workbook: createSession](https://learn.microsoft.com/en-us/graph/api/workbook-createsession?view=graph-rest-1.0)
- S4: [Update range (v1.0)](https://learn.microsoft.com/en-us/graph/api/range-update?view=graph-rest-1.0)
- S5: [Update range (beta)](https://learn.microsoft.com/en-us/graph/api/range-update?view=graph-rest-beta)
- S6: [workbookRange resource type](https://learn.microsoft.com/en-us/graph/api/resources/workbookrange?view=graph-rest-1.0)
- S7: [Error handling for Excel APIs](https://learn.microsoft.com/en-us/graph/workbook-error-handling) oraz [Error codes for workbooks and charts APIs](https://learn.microsoft.com/en-us/graph/workbook-error-codes)
- S8: [Collaborate on Excel workbooks at the same time with co-authoring](https://support.microsoft.com/en-us/office/collaborate-on-excel-workbooks-at-the-same-time-with-co-authoring-7152aa8b-b791-414c-a3bb-3024e46fb104)
- S9: [File size limits for workbooks in SharePoint](https://support.microsoft.com/en-us/office/file-size-limits-for-workbooks-in-sharepoint-9e5bc6f8-018f-415a-b890-5452687b325e)
- S10: [subscription resource type](https://learn.microsoft.com/en-us/graph/api/resources/subscription?view=graph-rest-1.0)
- S11: [Create subscription](https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0)
- S12: [Set up notifications for changes in resource data](https://learn.microsoft.com/en-us/graph/change-notifications-overview)
- S13: [Webhook notifications, OneDrive API](https://learn.microsoft.com/en-us/onedrive/developer/rest-api/concepts/using-webhooks)
- S14: [driveItem: delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0)
- S15: [Resource limits and performance optimization for Office Add-ins: Excel add-ins](https://learn.microsoft.com/en-us/office/dev/add-ins/concepts/resource-limits-and-performance-optimization)
- S16: [List versions](https://learn.microsoft.com/en-us/graph/api/driveitem-list-versions?view=graph-rest-1.0)
- S17: [workbookRangeFormat resource type](https://learn.microsoft.com/en-us/graph/api/resources/workbookrangeformat?view=graph-rest-1.0)
- S18: [workbookRangeFont resource type](https://learn.microsoft.com/en-us/graph/api/resources/workbookrangefont?view=graph-rest-1.0)
- S19: [workbookRangeBorder resource type](https://learn.microsoft.com/en-us/graph/api/resources/workbookrangeborder?view=graph-rest-1.0)
- S20: [Refresh tokens in the Microsoft identity platform](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)
- S21: [Avoid getting throttled or blocked in SharePoint Online](https://learn.microsoft.com/en-us/sharepoint/dev/general-development/how-to-avoid-getting-throttled-or-blocked-in-sharepoint-online)
- S22: [Upload small files (driveItem: put content)](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0)
- S23: [Overview of Selected permissions in OneDrive and SharePoint](https://learn.microsoft.com/en-us/graph/permissions-selected-overview)
- S24: [driveItem: createUploadSession](https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0)
- S25: [Microsoft Graph error responses and resource types](https://learn.microsoft.com/en-us/graph/errors)
- S26: [driveItem resource type](https://learn.microsoft.com/en-us/graph/api/resources/driveitem?view=graph-rest-1.0)
- S27: [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)
- S28: [Create permission on a driveItem](https://learn.microsoft.com/en-us/graph/api/driveitem-post-permissions?view=graph-rest-1.0)
