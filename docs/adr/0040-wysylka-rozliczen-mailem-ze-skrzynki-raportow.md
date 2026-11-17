# ADR 0040: Wysyłka rozliczeń mailem ze skrzynki raportów

## Status

Zaakceptowana (decyzja Maksa 16.11.2026: prośba w wątku tej gałęzi, w trybie bez Maksa przy komputerze; decyzje
szczegółowe agenta wdrożenia nazwane niżej). To decyzja Maksa o nowej drodze danych taty: Rozliczenie pracownika, w
którym są wartości `ADRES` klientów, wychodzi z komputera taty mailem do Wykonawcy, tak jak tata wysyłał je dotąd
ręcznie. Zmienia:

- [ADR 0030](0030-przypomnienia-o-raporcie-z-centrum-w-autostarcie.md): SMTP skrzynki raportów nie służy już tylko
  Przypomnieniom o raporcie. Centrum wysyła nim też Maile z rozliczeniem, tylko na kliknięcie taty. Folder „Wysłane”
  jest pamięcią wysłanych także dla nich;
- [ADR 0032](0032-ustawienia-centrum-zmienia-tata.md): temat i treść Maila z rozliczeniem to nowe Ustawienie Centrum
  (`config/wysylka-rozliczen.yaml`), które zmienia tata. Temat przypomnienia zostaje stały, a temat Maila z
  rozliczeniem zmienia tata, bo po nim Centrum niczego nie rozpoznaje.

## Kontekst

Po Przebiegu rozliczeń tata wysyła każdemu Wykonawcy jego Rozliczenie pracownika: otwiera Gmaila, dołącza plik, wpisuje
adres i temat, osobno dla każdego. Przy kilku Wykonawcach co tydzień to kilkanaście minut powtarzalnej pracy, w której
łatwo dołączyć plik innego pracownika albo kogoś pominąć. Centrum zna już pliki okresu, Listę Wykonawców z adresami i
skrzynkę raportów z hasłem aplikacji.

## Decyzja

- **Strona „Wysyłka rozliczeń” (`#/wysylka`): oś okresów z paskiem postępu** (wariant „Mix”, wybrany przez Maksa
  17.11.2026 z drugiej rundy prototypów). Ostatnie 12 Folderów okresu, które mają Rozliczenia pracowników, stoi na
  pionowej osi od najnowszego. Okres z plikiem do wysłania to karta z paskiem „X z Y wysłane” i Wykonawcami z adresami
  i stanem; gdy wszystko poszło, karta zamienia się w jeden wiersz osi. Okres, w którym czekają tylko pliki zmienione po
  wysłaniu, pyta o każdy z nich („Wyślij poprawione”), a reszta to jeden wiersz z małym paskiem i Wykonawcami. Widok
  „Do wysłania” pokazuje tylko okresy, które czekają na tatę (i wysłane w tej wizycie), „Wszystkie okresy” także resztę.
  „X z Y” liczy pliki, które mają mail: bez braku adresu, bez zleceń i spoza Listy, a zmieniony po wysłaniu czeka na
  ponowną wysyłkę, więc okres z nim nie jest pełny. Strona liczy to ze stanów wierszy, bo zmienia je po każdym mailu.
- **Stany Rozliczenia pracownika w Wysyłce** to jedna unia, liczona w tej kolejności: nie ma w Liście Wykonawców (nazwa
  pliku nie odpowiada żadnej nazwie z Listy), brak adresu, wysłane (przez Centrum) albo wysłane ręcznie (mail z tym
  plikiem bez znaku Centrum), zmienione po wysłaniu (plik zmieniony ponad 2 minuty po ostatnim mailu z nim), nie wyszło
  (ostatnia próba w tej pracy Centrum), bez zleceń (pusty Szablon pracownika), do wysłania. Zaznaczone na start są pliki
  do wysłania i te, które nie wyszły; zmieniony po wysłaniu można wysłać jeszcze raz, ale tata zaznacza go sam.
- **Pamięcią wysłanych jest folder „Wysłane”**, jak dla Przypomnień o raporcie, bez własnego pliku stanu. Mail z
  rozliczeniem rozpoznaje się po nazwie pliku załącznika `Rozliczenie {token} - {nazwa}.xlsx` (bez względu na wielkość
  liter i postać Unicode), a nie po temacie, który zmienia tata, i tylko wtedy, gdy poszedł na któryś adres tego
  Wykonawcy z Listy: plik przesłany komuś innemu nie jest wysłany Wykonawcy. Dzięki temu widać też rozliczenia, które tata
  wysłał sam z tej skrzynki. Port czyta „Wysłane” od wtorku najstarszego okresu strony tylko z `BODYSTRUCTURE` i
  nagłówków maila i części z plikiem, bez treści maili i bajtów załączników.
- **Znak Centrum.** Mail Centrum ma nagłówek `X-Centrum-Rozliczen: wysylka-rozliczen`; po nim „Wysłane” odróżniają
  „wysłane” od „wysłane ręcznie”.
- **Jedno zapytanie na mail, po kolei.** „Wyślij N rozliczeń” otwiera okno z podglądem każdego maila (1 z N), a po
  potwierdzeniu przeglądarka wysyła maile po jednym zapytaniu; odznaka wiersza zmienia się, gdy jego mail wychodzi, a
  na końcu powiadomienie mówi, ile poszło. Porażka jednego maila nie zatrzymuje reszty.
- **Wysyłka bez powtórek.** Serwer wysyła po jednym mailu pod blokadą i przed każdym znowu czyta „Wysłane”: plik już
  wysłany i niezmieniony wraca ze swoim stanem bez maila (podwójne kliknięcie, druga karta, ponowienie), a zmieniony idzie
  tylko z `resend`. Gmail kładzie mail w „Wysłanych” z opóźnieniem, więc maile wysłane w tej pracy Centrum serwer pamięta
  też w pamięci procesu. „Wysłanych”, których nie da się przeczytać, serwer nie zgaduje: plik nie idzie, a wiersz mówi
  dlaczego.
- **Tylko swój plik na swoje adresy.** Plik Wykonawcy X idzie tylko na wszystkie adresy Wykonawcy X z Listy Wykonawców,
  jeden mail na Wykonawcę, z adresu skrzynki raportów. Nieaktywny Wykonawca też dostaje swoje rozliczenie: rozliczenie
  należy mu się także po odejściu.
- **Mail.** Tekst w UTF-8, temat i treść z Ustawień z polami `{okres}` (dni okresu słowami, np. „3–9 listopada 2026”)
  i `{wykonawca}`, na końcu stopka Przypomnień o raporcie (jeden podpis taty), plik xlsx pod dokładną nazwą z dysku
  (polskie litery po RFC 2231). Plik otwarty w Excelu nie idzie: tata zapisuje go i zamyka.
- **Temat i treść to Ustawienie Centrum** w `config/wysylka-rozliczen.yaml` (schemat 1: `temat`, `tresc`), w sekcji
  „Wysyłka rozliczeń” grupy Praca, z podglądem i Historią Ustawień. Domyślnie temat „Rozliczenie za {okres}” i treść
  „Dzień dobry, w załączniku rozliczenie za {okres}.”. Temat jest wymagany, w jednej linii i taki, że port Skrzynki
  raportów nie wybierze odpowiedzi Wykonawcy `Re: <temat>` jako Raportu wykonawcy (gramatyka tematu z ADR 0041,
  `reads_as_report`: odmową jest np. `Raport 16.11.2026 …`, poprawka raportu w odpowiedzi); inny nawias klamrowy niż
  pole to odmowa.
- **Bez zleceń.** Pusty Szablon pracownika nie idzie. Centrum poznaje go po braku Wykonawcy w `WYKONAWCA` od pierwszego
  Wiersza danych (odczyt kolumny z XML, bez openpyxl), tylko dla pliku, który jeszcze nie poszedł, z pamięcią po chwili
  zmiany pliku. Plik, którego nie da się przeczytać, liczy się jako plik ze zleceniami: lepiej go pokazać niż ukryć.
- **Dane.** Dziennik Centrum, Logi, Zgłoszenia i pomiary dostają tylko token okresu, przyczynę i nazwę typu wyjątku, bez
  nazw, adresów, nazw plików, tematu i treści (ADR 0028, ADR 0030); Zgłoszenie podaje zmianę tematu i treści samym
  znacznikiem. Przeglądarka pokazuje adresy i nazwy, bo to lokalne Centrum taty, a Lista Wykonawców już je pokazuje.
- **Skrzynka bez odczytu.** Gdy „Wysłanych” nie da się przeczytać (brak hasła, odrzucone hasło, brak sieci), strona
  mówi to jednym zdaniem, a wysyłka jest wyłączona.

Decyzje agenta wdrożenia poza prośbą Maksa: stan „nie wyszło” trwa tylko w pamięci pracy Centrum (bez pliku stanu, po
ponownym starcie plik jest znów do wysłania albo, gdy mail jednak doszedł, wysłany); mail na adres spoza Wykonawcy nie
liczy się jako wysłany; margines zegara 2 minuty jak w Przypomnieniach; odrzucone hasło przy wysyłce nie zakłada
Zgłoszenia do Maksa, bo tata jest przy komputerze i hasło wymienia sam (ADR 0032); stan „nieznany” dla pliku przy
skrzynce bez odczytu; strona nie pokazuje okresów bez Rozliczeń pracowników.

## Odrzucone warianty

- **Własny plik stanu wysłanych.** Folder „Wysłane” już to wie i widzi też maile wysłane przez tatę ręcznie, a plik
  rozjechałby się ze skrzynką (ADR 0030).
- **Okres po okresie (lista okresów po lewej, Wykonawcy wybranego po prawej).** Pierwsza wersja tej strony; na osi
  tata widzi naraz, co czeka w każdym okresie, a skończony okres zwija się w jeden wiersz zamiast stać na liście.
- **Mapa okresów (Wykonawcy × okresy).** Widać wszystko naraz, ale tata wysyła okres po okresie, a mapa przy kilkunastu
  okresach nie mieści się na laptopie taty i ukrywa adresy, które tata sprawdza przed wysyłką.
- **Lista „Do wysłania” ze wszystkich okresów.** Szybsza przy zaległościach, ale miesza okresy w jednym oknie
  potwierdzenia, a tata myśli tygodniami.
- **Jedno zadanie serwera dla całej partii z odpytywaniem stanu.** Dałoby postęp bez otwartej karty, ale to drugi
  mechanizm obok Uruchomień, z własnym stanem i sprzątaniem; zapytanie na mail daje ten sam postęp, a częściowa porażka
  zostaje przy swoim wierszu.
- **Osobna stopka Wysyłki rozliczeń.** Tata miałby dwa podpisy do pilnowania; jedna stopka z Przypomnień o raporcie
  wystarcza.
- **Rozpoznawanie po temacie.** Tata zmienia temat w Ustawieniach, więc temat nie wskazuje maila; nazwa pliku robi to
  zawsze.
