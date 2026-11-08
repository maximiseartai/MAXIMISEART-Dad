# Research: Wycena w efenix spoza komputera taty

Data researchu: 2026-11-08. Ticket #1149, mapa #1145 „Centrum w chmurze”.

Pytanie: czy Wycena w efenix może biec z serwera, a nie z okna przeglądarki na komputerze taty?

Ten research nie wysłał żadnego żądania do prawdziwego efenix. Źródła to kod w `src/rozliczenia/efenix_*.py`,
`tools/zgodnosc_efenix.py`, ADR 0024, 0026 i 0027, `GLOSSARY.md`, prywatne notatki z rekonesansu i runów (poza repo,
tu tylko ogólne wnioski o logowaniu i sesji) oraz publiczna dokumentacja.

## Wniosek

Technicznie tak: okno efenix to Playwright z Chromium, które już dziś biegnie bez ekranu na Linuksie w CI na Atrapie
efenix, a logowanie efenix to zwykły formularz bez captchy i bez widocznego drugiego składnika. Ale trzy rzeczy, od
których zależy, czy sesja na serwerze w ogóle przeżyje, są niezmierzone: czy efenix wiąże sesję albo logowanie z
adresem IP lub urządzeniem, czy drugie logowanie tym samym kontem wylogowuje pierwsze i czy autor efenix zgadza się
na automatyzację z obcego adresu.

Rekomendacja na plan migracji: **mały agent na komputerze taty (wariant B)** jako docelowa droga Wyceny w efenix
w chmurze, a **przeglądarka na serwerze z sesją otwieraną przez tatę zdalnie (wariant A)** dopiero po sprawdzeniach z
sekcji „Do sprawdzenia w sesji taty” i po odpowiedzi autora efenix. Wariant C (Wycena zostaje w lokalnym Centrum) tylko
jako etap przejściowy. Uzasadnienie jest w tabeli porównania.

## Co wiadomo (fakty ze źródłem)

### Jak dziś narzędzie pracuje w efenix

- Narzędzie pracuje w efenix tylko w sesji, którą otworzył tata. Tata loguje się sam w oknie, które otwiera Centrum
  rozliczeń, a narzędzie hasła nie widzi i nie przechowuje (ADR 0024).
- Okno taty to widoczne okno zainstalowanego Google Chrome w trwałym profilu narzędzia na dysku lokalnym taty, poza
  OneDrive (`src/rozliczenia/centrum/efenix_chrome.py`, `efenix_browser.default_profile`, `PROFILE_DIRECTORY`).
  Testy i Skrypt dla maszyn używają Chromium Playwrighta bez okna (`headless=True`) na Atrapie efenix
  (`efenix_browser.chromium`, `efenix_chrome.atrapa_opening`). Sam kod okna nie zależy więc od ekranu ani od Windows.
- Okno czeka na logowanie taty do 15 minut (`LOGIN_TIMEOUT_MS`), pytając efenix co 2 s o listę zleceń w tej samej
  sesji przeglądarki, bez ruszania formularza, w którym tata pisze (`efenix_browser`, docstring modułu).
- Wylogowanie okno rozpoznaje po przekierowaniu na `page_login.php` albo po ostrzeżeniu „Twoja sesja wygasła” w
  odpowiedzi szukania (`efenix_page.SearchWarning.SESSION_EXPIRED`, `efenix_window.LoginSign`). Kończy się to
  Zatrzymaniem, a ponowne uruchomienie przechodzi przez gotowe zlecenia bez przerw (ADR 0024, punkt o tempie).
- Tempo jest ludzkie: ok. 20 s na zlecenie z zapisem, ok. 280 zleceń w okresie (ADR 0024). Pierwszy prawdziwy run taty
  (okres z października 2026) trwał 87 minut i skończył się bez wylogowania (prywatne Logi runu).
- Strażnik zmiany statusu stoi na całym kontekście przeglądarki okna i przerywa każde żądanie zmiany statusu poza
  własnym Przekazaniem do akceptacji (ADR 0027, `efenix_browser`). Działa tak samo bez ekranu, bo to `page.route`
  Playwrighta, a nie coś, co widzi tata.

### Logowanie efenix

Z kopii strony logowania i jej skryptu z rekonesansu (sam odczyt, 1.11.2026), potwierdzone przez
`tools/zgodnosc_efenix.py`, który sprawdza pola formularza na żywym efenix:

- Formularz to zwykły POST na `action_login.php` z polami: identyfikator użytkownika, hasło i ukryte pole
  `fingerprint`. Pod spodem jest link „Zapomniałem hasła”. Nie ma captchy, pola na kod drugiego składnika, przycisku
  SSO ani linku do regulaminu.
- Pole `fingerprint` wypełnia przed wysłaniem biblioteka Fingerprint2 (fingerprintjs w wersji 2): skrót `x64hash128`
  z cech przeglądarki (m.in. user agent, ekran, strefa czasowa, czcionki, canvas). Efenix dostaje więc przy każdym
  logowaniu odcisk przeglądarki. Co z nim robi po stronie serwera (zapis, porównanie, alert), nie wiadomo.
- Skrypt strony logowania czyści przy wejściu `sessionStorage` z filtrami listy. Nie ma w nim nic o pamiętaniu
  urządzenia.
- Efenix odrzuca tylko Internet Explorera (sprawdzenie user agenta w skrypcie). Headless Chromium ma w user agencie
  `HeadlessChrome`. Skrypt tego nie sprawdza, ale serwer może.

### Sesja efenix

- Efenix to aplikacja PHP (adresy `*.php`), a sesję trzyma ciasteczko `PHPSESSID`. W profilu Chrome z rekonesansu
  (metadane ciasteczka bez wartości) to ciasteczko sesji przeglądarki: bez daty wygaśnięcia, `Secure`, bez `HttpOnly`,
  `SameSite=Lax`. Jak długo serwer trzyma sesję, z ciasteczka nie widać.
- Domyślnie PHP uznaje dane sesji za śmieci po 1440 s (24 min) bez ruchu (`session.gc_maxlifetime`), ale serwer może to
  zmienić ([PHP: Session Runtime Configuration](https://www.php.net/manual/en/session.configuration.php)). Czy efenix
  zmienia tę wartość, nie wiadomo.
- Zaobserwowane: run taty z ruchem co kilkanaście sekund przeżył 87 minut. Sesja Maksa do sprawdzeń zgodności
  wygasła między dwoma podejściami tego samego dnia (4.11.2026), więc sesja bez ruchu ma skończony czas życia
  (prywatne notatki runów 4.11).
- Bez sesji lista i strona zlecenia odpowiadają 302 na `page_login.php`, a szukanie odpowiada 200 z samym ostrzeżeniem
  o wygasłej sesji (`tools/zgodnosc_efenix.py`, sprawdzone na żywym efenix 4.11.2026).
- `tools/zgodnosc_efenix.py` wysyła swoje odczyty klientem HTTP Playwrighta (`contexts[0].request`) z ciasteczkami
  sesji Chrome, bez kart i bez skryptów stron. Na żywym efenix 8.11.2026 przeszedł bez różnic. Sesja nie wymaga więc
  przy każdym żądaniu skryptów strony ani odcisku przeglądarki, tylko ciasteczka. Wszystkie te żądania szły jednak z
  tego samego komputera i adresu co logowanie, więc to nie mówi nic o wiązaniu z IP.
- Konto taty zalogowało się już na innym komputerze niż komputer taty: na Macu Maksa, w osobnym profilu Chrome, do
  sprawdzeń zgodności (4.11 i 8.11.2026). Logowanie przeszło bez dodatkowego kroku (prywatne notatki). Z notatek nie
  wynika, czy Mac był wtedy w innej sieci niż komputer taty ani czy tata był w tej chwili zalogowany u siebie.

### Warunki korzystania z efenix

- Efenix to mała aplikacja jednoosobowej firmy bez API do wycen. Prośba do autora o import albo API jest otwarta
  (ADR 0024).
- Strona logowania nie linkuje regulaminu. Wyszukiwanie publicznych stron nie znalazło regulaminu efenix ani jego
  dokumentacji, tylko niepowiązane firmy o nazwie Fenix. Warunków automatyzacji nie da się więc ustalić z publicznych
  źródeł. Wiążące jest to, co tata ma w umowie z firmą, z którą się rozlicza, i odpowiedź autora.

## Czego nie wiadomo (do sprawdzenia w sesji taty)

Każde sprawdzenie to odczyt albo pytanie. Żadne nie zapisuje niczego w efenix. Logowanie z obcego adresu (punkt 3) to
jednak nowe logowanie kontem taty, więc decyduje o nim Maks razem z tatą, a nie agent.

1. **Równoległe sesje.** Czy logowanie tym samym kontem na drugim urządzeniu wylogowuje pierwsze? Najtańsze sprawdzenie:
   zapytać tatę, czy 4.11 albo 8.11 wylogowało go w trakcie pracy, a potem jeden odczyt listy w obu oknach naraz.
   Od tego zależy, czy Wycena na serwerze może biec, gdy tata w tym czasie pracuje w efenix u siebie.
2. **Czas życia sesji bez ruchu.** Ile minut bez ruchu sesja jeszcze odpowiada na szukanie? Pomiar samymi odczytami
   (szukanie po numerze) w odstępach. Wariant A potrzebuje tego, żeby wiedzieć, ile czasu ma tata między logowaniem a
   startem Wyceny.
3. **Logowanie z adresu serwera w UE.** Czy efenix albo jego hosting blokuje albo flaguje logowanie z innego kraju albo
   ASN (np. centrum danych Hetznera w Niemczech albo Finlandii)? Źródła nic o tym nie mówią w żadną stronę. Sprawdzenie
   wymaga jednego logowania kontem taty przez przeglądarkę na serwerze testowym i jednego odczytu listy.
4. **Wiązanie sesji z IP.** Czy ciasteczko sesji działa z innego adresu niż logowanie? Ma to znaczenie tylko wtedy, gdy
   ktoś chciałby przenosić sesję między maszynami (patrz odrzucony wariant A2).
5. **Powiadomienia o nowym urządzeniu.** Czy tata dostał maila albo komunikat po logowaniach Maksa? Po co efenix zbiera
   odcisk przeglądarki? Na to odpowie tylko tata albo autor.
6. **Warunki automatyzacji.** Pytanie do autora (rozszerzenie otwartej prośby z ADR 0024): czy wolno pracować na koncie
   taty programem i z jakiego adresu, czy jest lista dozwolonych adresów, czy da się dostać import albo API.

## Warianty

### A. Przeglądarka na serwerze, sesję otwiera tata zdalnie

Centrum w chmurze uruchamia Chromium z oknem w wirtualnym ekranie (albo bez okna) i pokazuje tacie stronę logowania
efenix strumieniem w Centrum (np. obraz z `Page.startScreencast` Chrome DevTools Protocol i zdarzenia wejścia z
powrotem, albo gotowy serwer zdalnej przeglądarki). Tata wpisuje hasło w tym oknie, a Wycena biegnie dalej na serwerze.

- Za: Wycena nie zależy od komputera taty (kryteria 2 i 3). Wynik i postęp widzą wszyscy w Centrum (kryterium 1).
  Logi i alerty są tam, gdzie reszta systemu (kryteria 4 i 6). Tata może zacząć Wycenę z telefonu (kryterium 5).
- Przeciw: logowanie i każdy zapis idą z adresu centrum danych w innym kraju i z innym odciskiem przeglądarki. To
  wszystkie trzy niewiadome naraz (punkty 1, 3 i 5) i ryzyko, że autor efenix uzna to za współdzielenie konta. Hasło
  taty przechodzi przez pamięć serwera jako naciśnięcia klawiszy. Serwer go nie zapisuje, ale „narzędzie nie widzi
  hasła” z ADR 0024 trzeba by przeformułować. Strumień okna to nowy komponent do zbudowania, zabezpieczenia i
  testowania (Atrapa efenix tego nie obejmie). Gdy efenix wyloguje w trakcie, tata musi zalogować się ponownie przez
  strumień.

### A2. Tata loguje się u siebie, a ciasteczko sesji jedzie na serwer (odrzucony)

Ciasteczko `PHPSESSID` nie ma `HttpOnly`, więc dałoby się je przenieść. Odrzucone: to przeniesienie poświadczenia taty
poza jego komputer, którego ADR 0024 właśnie unika, a jeśli efenix wiąże sesję z IP (punkt 4), nie zadziała w ogóle.

### B. Mały agent na komputerze taty

Centrum w chmurze trzyma Plik zbiorczy (docelowo w bazie), a Wycenę w efenix robi agent na komputerze taty: dzisiejszy
kod okna (`efenix_browser`, `efenix_pricing`, strażnik zmiany statusu) z widocznym Chrome w profilu narzędzia. Agent
łączy się z serwerem tylko wychodząco (HTTPS albo WebSocket), bierze zadanie Wyceny z ilościami zleceń i oddaje wynik
każdego zlecenia i Logi Uruchomienia.

- Za: efenix widzi dokładnie to, co dziś: ten sam komputer, adres, przeglądarkę i tatę, który loguje się sam. Żadna z
  niewiadomych 1–5 nie blokuje. ADR 0024 i 0027 zostają bez zmian. Kod okna przechodzi bez przepisywania, a Atrapa
  efenix dalej testuje całość. Wynik i postęp widzą w Centrum wszyscy (kryterium 1), a dane i Logi są na serwerze
  (kryterium 4).
- Przeciw: sama Wycena dalej wymaga włączonego komputera z agentem przez ok. 40–90 minut raz na okres (kryteria 2 i 3
  tylko częściowo). Utrata laptopa nie traci danych, tylko zatrzymuje Wycenę do instalacji agenta na innym komputerze.
  Agent to drugi artefakt do wydawania (dziś Wydania z ADR 0014 i tak trafiają na Windows taty), z własnym
  uwierzytelnieniem urządzenia wobec serwera.

### C. Wycena zostaje w lokalnym Centrum

Wycena w efenix biegnie jak dziś w Centrum na `127.0.0.1` i czyta Plik zbiorczy z dysku taty.

- Za: zero pracy i zero nowego ryzyka teraz.
- Przeciw: gdy źródłem prawdy stanie się baza SQL, lokalna Wycena i tak musi pobrać ilości z serwera i oddać mu
  Znaczniki, czyli staje się wariantem B bez projektu. Wynik nie jest widoczny dla innych, dopóki nie wróci przez
  Excel (kryterium 1).

## Porównanie z kryteriami mapy

| Kryterium mapy (od najważniejszego) | A. Przeglądarka na serwerze | B. Agent u taty | C. Lokalnie jak dziś |
|---|---|---|---|
| 1. Wiele osób na tych samych danych | tak | tak | nie, wynik wraca przez Excel |
| 2. Działa 24/7 bez laptopa taty | tak, jeśli efenix przyjmie sesję z serwera | dane tak, sama Wycena tylko przy włączonym komputerze | nie |
| 3. Utrata laptopa nie zatrzymuje firmy | tak | dane bezpieczne, Wycena stoi do nowej instalacji agenta | Wycena i jej dane stoją |
| 4. Bezpieczeństwo, logi, alerty | logi w jednym miejscu, ale hasło przechodzi przez serwer | logi na serwerze, hasło tylko u taty | jak dziś |
| 5. Web i telefon | start z telefonu, logowanie przez strumień | start z telefonu, gdy komputer z agentem jest włączony | nie |
| 6. Długie utrzymanie | strumień okna i zmiany po stronie efenix (IP, odcisk) | drugi artefakt do wydawania | dwa systemy obok siebie |
| Ryzyko wobec efenix | trzy niewiadome i możliwe współdzielenie konta | brak nowego | brak nowego |

Wycena w efenix to proces uruchamiany raz na okres przez tatę, a nie praca w tle 24/7. Kryteria 2 i 3 ważą więc dla
niej mniej niż dla Rejestru zleceń. Za to błąd po stronie efenix (blokada konta taty, zarzut współdzielenia konta) uderza
w codzienną pracę taty, której narzędzie nie umie cofnąć. Dlatego B jest bezpieczną drogą docelową, a A zmianą, którą
warto rozważyć dopiero, gdy punkty 1, 3, 5 i 6 dadzą dobre odpowiedzi. Interfejs między serwerem a oknem efenix
(zadanie Wyceny z ilościami, wynik zlecenia, Logi) jest w A i B ten sam, więc późniejsze przejście z B na A nie zmienia
reszty Centrum.

## Źródła

- `docs/adr/0024-wycena-w-efenix-w-sesji-taty-testowana-na-atrapie.md`,
  `docs/adr/0026-wycena-w-efenix-dokancza-do-pliku-tylko-w-gore.md`,
  `docs/adr/0027-wycena-w-efenix-przekazuje-gotowe-zlecenia-do-akceptacji.md`
- `src/rozliczenia/efenix_browser.py` (docstring modułu, `chrome`, `chromium`, `LOGIN_TIMEOUT_MS`),
  `src/rozliczenia/centrum/efenix_chrome.py`, `src/rozliczenia/efenix_page.py` (`LOGIN_PAGE`, `LOGIN_FORM`,
  `SearchWarning`), `src/rozliczenia/efenix_window.py` (`LoginSign`)
- `tools/zgodnosc_efenix.py` (docstring: odczyty bez sesji, pola formularza logowania)
- `GLOSSARY.md`: efenix, Wycena w efenix, Przekazanie do akceptacji
- Prywatne notatki rekonesansu efenix (kopia strony logowania i jej skryptu, metadane ciasteczka profilu Chrome) i
  runów z 4.11 i 8.11.2026, poza repo
- [PHP: Session Runtime Configuration](https://www.php.net/manual/en/session.configuration.php) (`session.gc_maxlifetime`)
- [fingerprintjs](https://github.com/fingerprintjs/fingerprintjs) (biblioteka Fingerprint2 w wersji 2)
- [Chrome DevTools Protocol: Page.startScreencast](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-startScreencast)
