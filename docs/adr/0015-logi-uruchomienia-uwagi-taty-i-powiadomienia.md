# ADR 0015: Logi Uruchomienia, Uwagi taty i Powiadomienia

## Status

Zaakceptowana. Zakłada Wydania z ADR 0014 (tata dostaje tylko Wydanie, nigdy
bieżący `main`). Zmienia trzy zdania
[ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md) w ten sam sposób co
[ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md):

- „Centrum łączy się wyłącznie z API GitHuba: przy wysyłce Zgłoszenia, przy
  sprawdzaniu stanu wysłanych Zgłoszeń…”: dochodzi wysyłka Logów Uruchomienia
  i Uwag taty, stan Uwag oraz lista Wydań publicznego repozytorium;
- „Bez treści wierszy”: Logi Uruchomienia nie niosą treści wierszy, ale ich
  Komunikaty i podsumowanie tak jak na karcie Uruchomienia (wyjątki niżej);
- własne pliki Centrum: dochodzą Logi Uruchomienia w `logs/uruchomienia/` oraz
  w `config/` stan wysłanych Uwag (`uwagi-taty.json`, od #431 razem ze
  Zgłoszeniami w pliku Spraw taty `sprawy-taty.json`), przeczytanych
  Powiadomień (`powiadomienia.json`) i adresy dostarczonych Logów
  (`skrzynka-adresy.jsonl`), wszystko poza Gitem.

Dopisek #839 (część #837): Logi mają `schema_version` 2 z godziną (UTC) każdego
kroku śladu i dziennikiem działań taty w Centrum; dochodzi własny plik Centrum
`logs/dzialania-taty.jsonl` z działaniami, które czekają na Logi następnego
Uruchomienia. Szczegóły w punkcie „Treść Logów”.

Dopisek #845 (część #837): Wycena w efenix, przerwana w trakcie, zostawia też
dziennik Wyceny w efenix w `logs/dzienniki-wyceny/`, z którego następny start
Centrum zamyka Logi Urwanego Uruchomienia; krótkie procesy zostawiają dalej
tylko `uruchomienie-start`. Szczegóły w dopisku #845 do
[ADR 0017](0017-karta-uruchomienia-z-logow.md).

[ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md) traci Powiadomienie o
naprawie na stronie Okresy: zastępuje je Powiadomienie o nowej wersji.

## Kontekst

Wszystko, co Maks wiedział o pracy narzędzia u taty, to rekord metryk (czasy,
liczniki, kod Zatrzymania) i linie dziennika Centrum. Pełny wynik Uruchomienia
procesu, czyli Komunikaty, podsumowanie i przebieg Szablonów pracownika, ginął
przy zamknięciu Centrum. Do Maksa trafiało tylko Zgłoszenie, a to wymaga
Zatrzymania „do Maksa” i kliknięcia taty; Skrzynka Zgłoszeń nie dostała
żadnego. Tata nie miał jak napisać do Maksa z narzędzia ani jak się dowiedzieć,
co stało się z tym, co wysłał.

## Decyzja

- **Logi Uruchomienia powstają na końcu każdego Uruchomienia z Centrum**, w
  każdym trybie i z każdym wynikiem, także przy Zatrzymaniu i nieoczekiwanym
  wyjątku. Mówią wprost, czy był to podgląd, czy zapis. Centrum przerwane w
  trakcie zostawia tylko `uruchomienie-start` w dzienniku; zapis przyrostowy
  dokładałby pracy każdemu Przebiegowi. Skrypt dla maszyn Logów nie tworzy.
- **Na komputerze taty jeden plik JSON na Uruchomienie** w `logs/uruchomienia/`
  na `C:`, z wersją schematu, zapisany atomowo i trzymany bez rotacji. Urwany
  zapis psuje jeden plik, nie historię, a ten sam plik jest treścią w Skrzynce.
- **Centrum wysyła Logi samo i po cichu.** Jeden okres to jedno issue z
  etykietą `logi-uruchomienia`, także po zamknięciu przez Maksa, a każde
  Uruchomienie to komentarz: podsumowanie w Markdown i pełny JSON w
  `<details>`, dzielony na kolejne komentarze ponad limitem GitHuba (65 536
  znaków treści, zmierzone w #332). Issue okresu Centrum znajduje po wierszu
  `- Logi Uruchomienia okresu: <okres>` w jego treści, tym samym mechanizmem
  co Kontrolę ilości; token okresu w tytule jest dla ludzi. Stałego issue dla
  Uruchomień bez okresu nie ma: oba wejścia do Uruchomienia z Centrum
  odrzucają zły token okresu, zanim Uruchomienie wystartuje, więc każde ma
  okres. Diagnoza z nowym wynikiem dopisuje go do pliku Logów ostatniego
  Uruchomienia tej pracy Centrum i wysyła całe Logi jako kolejny komentarz.
  Diagnoza z tym samym wynikiem co ostatnio dopisana (poza chwilą i opisem
  sprawdzeń, które przeszły) nie zmienia ani pliku, ani issue, bo automatyczna
  Diagnoza powtarza się przy każdym pokazaniu karty (#371). Zgłoszenie ma
  wiersz z odnośnikiem do Logów swojego Uruchomienia, gdy doszły przed
  Diagnozą, a inaczej „jeszcze niewysłane” z identyfikatorem Uruchomienia.
  Logi, które dojdą później, Zgłoszenia nie zmieniają.
- **Kolejka Skrzynki Zgłoszeń**, wspólna dla Kontroli ilości, Logów, Uwag i
  Zgłoszeń (od #426), rusza przy starcie Centrum, po każdej nowej wysyłce i
  sama minutę po przejściu, które stanęło na braku sieci, braku klucza albo
  odmowie klucza lub dostępu (401, 403, 404). Limit zapytań GitHuba to brak
  sieci. Odrzucony klucz nie kosztuje co minutę zapytania: Skrzynka z kluczem
  taty (ADR 0007) odpowiada odmową bez sieci przez kwadrans. Linia
  „skrzynka-czeka” trafia do dziennika tylko przy zmianie przyczyny, a każde
  dostarczenie ją zeruje, żeby ponowienia nie wypierały ostatnich wpisów,
  które niesie Diagnoza. Odmowa treści jednego pliku (400, 413, 422) zostawia go do
  następnego startu, a następne pliki idą dalej (#332). Wysyłka jest co
  najmniej raz: przerwanie między wysłaniem a znacznikiem dostarczenia
  powtarza komentarz, a porażka w środku Logów wieloczęściowych wysyła przy
  następnej próbie także części już przyjęte.
- **Treść Logów** (`schema_version` 1): proces, tryb, okres, Wydanie i commit,
  wynik, sposób zakończenia, Rodzaj Zatrzymania, czasy startu i końca, liczba
  problemów, Komunikaty (Zatrzymania i ostrzeżenia), uwagi techniczne,
  podsumowanie karty z planem plików, czasy etapów, Szablony pracownika z
  Wykonawcą, wynikiem, liczbą wierszy i czasem, środowisko (system, Python,
  nazwy i rozmiary plików procesu z flagą „tylko online” OneDrive), przy
  nieoczekiwanym wyjątku i przy własnym Zatrzymaniu „do Maksa”, które ma
  przyczynę w wyjątku, ślad wywołań jak w Zgłoszeniu (z typem i ramkami
  każdej przyczyny z łańcucha `__cause__`), przy Zatrzymaniu okna efenix
  przyczyna techniczna z zamkniętej listy, wiersz i miejsce zlecenia w
  przebiegu oraz ślad zleceń sprzed niego, i po Diagnozie jej wynik.
  Od `schema_version` 2 (#839) każdy etap i każde Przetworzenie Szablonu
  pracownika ma chwilę rozpoczęcia i końca w UTC, a każde działanie okna efenix
  chwilę rozpoczęcia, obok czasu trwania. Dochodzi dziennik działań taty w
  Centrum od Logów poprzedniego Uruchomienia do końca bieżącego: start
  Centrum, widoki, przyciski (każde zapytanie API, które coś zmienia, nazwane
  operacją API, start Uruchomienia z procesem i trybem), każde z godziną w UTC,
  bez treści zapytań, więc bez treści Uwagi taty. Karta Uruchomienia i Historia
  czytają pliki schematu 1 i 2.
  Wydanie to numer najwyższego Wydania, którego tag w klonie taty (z instalacji
  albo pobrany przez Aktualizację narzędzia) wskazuje dokładnie commit, z
  którego działa Centrum; Centrum ustala je lokalnie przy końcu każdego
  Uruchomienia (#426). Commit po Wydaniu, brak Gita i błąd Gita zostawiają pole
  puste. Logi nie niosą treści wierszy: nigdy adresu, numeru
  zlecenia, numeru umowy, Wykonawcy przy wierszu, daty dziennej z komórki,
  `CZYNNOŚCI ZREALIZOWANE` ani opisu technika. Komunikaty i przebieg Szablonów
  zachowują nazwę Wykonawcy, tak jak w Zgłoszeniu. Świadome wyjątki od tej
  reguły, te same co na karcie Uruchomienia i w Zgłoszeniu: Komunikat
  `ZLE_SKUTECZNE` cytuje dowolny tekst, który tata wpisał w komórce `SKUTECZNE`;
  `NIEZNANY_WYKONAWCA` z Przygotowania podaje identyfikator Wykonawcy przy
  numerze wiersza Rejestru; `BRAK_MAPOWANIA` i `NIEZNANY_WYKONAWCA` z Przebiegu
  rozliczeń podają identyfikator Wykonawcy spoza konfiguracji wykonawców, bez
  numeru wiersza; podsumowanie ma liczbę zleceń na każdy dzień okresu,
  a ostrzeżenie `NIEPELNY_OKRES` datę ostatniego zlecenia. Żaden z nich nie
  niesie adresu ani numeru zlecenia czy umowy, więc nie wskazuje klienta; tata
  widzi te same teksty na swojej karcie.
- **Uwaga taty** to tytuł i opcjonalna treść, pisane w oknie otwieranym ikoną
  obok dzwonka w każdym widoku, ogólne albo przypięte do jednego Uruchomienia
  procesu. Każda to osobne issue z etykietą `uwaga-taty`. Tata widzi w oknie
  dokładnie to, co wyśle, poza linią Logów opisaną niżej; bez sieci Uwaga czeka
  w kolejce z jednym zdaniem dla taty, bez Komunikatu. Uwaga przypięta niesie
  okres, proces, tryb, wynik i datę Uruchomienia, wersję narzędzia z chwili
  pisania Uwagi oraz odnośnik do Logów Uruchomienia. Gdy Logi jeszcze czekają w
  kolejce, szkic w oknie mówi „w drodze”, a kolejka tuż przed wysłaniem Uwagi
  wstawia w to miejsce odnośnik, jeśli Logi zdążyły dojść do Skrzynki, „nie
  dotarły”, jeśli Skrzynka odrzuciła ich treść, a inaczej „nie powstały albo nie
  da się ich wysłać”; obie te linie mają identyfikator Uruchomienia. Po „nie
  dotarły” kolejka dopisuje do issue Uwagi, także zamkniętego, komentarz z
  odnośnikiem, gdy Logi dotrą przy którymś następnym starcie Centrum, albo z
  tym, że nie dotrą, gdy znikną z kolejki (#374). Komentarz do issue Uwagi,
  którego Skrzynka już nie ma (Maks je usunął), kolejka usuwa z jedną linią
  dziennika, a bez sieci, klucza albo dostępu zostawia (#402). Wysyłka jest co najmniej raz:
  zerwane połączenie po utworzeniu issue może dać drugie issue.
- **Powiadomienia** to osobny widok otwierany dzwonkiem, z czterema rodzajami:
  nowa wersja, Uwaga, Zgłoszenie i zakończona Wycena w efenix (#750, z Logów
  Uruchomienia, także po Zatrzymaniu, z przyciskiem karty Uruchomienia). Wejście do widoku oznacza wszystkie jako
  przeczytane. Sprawę zamkniętą przez Maksa przed Wydaniem Powiadomienie nazywa
  rozwiązaną, z dopiskiem, że będzie w następnej wersji; zamkniętą bez zmiany w
  kodzie jako przeczytaną (`state_reason` zamkniętego issue: `completed` albo
  brak powodu to rozwiązana, `not_planned` albo `duplicate` to przeczytana).
  Zgłoszenie, które czeka w kolejce, ma stan „czeka na internet” jak Uwaga i
  przy dostarczeniu staje się wysłanym, bez kropki (#426). Powiadomienie o nowej wersji ma notkę Wydania (GitHub Release w
  formacie `release_notes`), rozwiązane sprawy taty wysłane z tego komputera i
  przycisk Aktualizacji narzędzia, ten sam co w Konfiguracji i Diagnozie
  (`offers_update`). Z Wydań kropkę zapala tylko najnowsze Wydanie na `main` i
  tylko wtedy, gdy jest nowsze od wersji taty; starsze stoją na liście jako
  historia, a Wydania wyższe od najnowszego na `main` nie dają karty. Kropkę
  zapalają też sprawy, które Maks rozwiązał albo przeczytał, i każda zakończona
  Wycena w efenix, dopóki tata jej nie zobaczy. Centrum sprawdza
  Wydania i stan spraw przy starcie i najwyżej raz na 10 minut jednym
  sprawdzaniem; bez sieci nie ma nowych Powiadomień ani Komunikatu. Pierwsza
  karta nowej wersji pojawi się z pierwszym Wydaniem opublikowanym przez
  narzędzie Wydań, bo goły tag bez GitHub Release nie ma notki.

## Odrzucone warianty

- **Logi wysyłane kliknięciem taty.** Maks dostawałby dane tylko wtedy, gdy
  tata sam zauważy problem, a to luka, którą Logi zamykają.
- **Jedno issue na Uruchomienie.** Kilkanaście issue miesięcznie, a sekwencja
  okresu (podgląd, Zatrzymanie, poprawka taty, Przebieg) rozbita na wątki.
- **Baza danych u taty.** Postgres to usługa systemowa z instalacją i
  aktualizacjami na Windowsie taty, a SQLite to plik binarny, którego nie da
  się wkleić do issue. Zapytania są potrzebne dopiero przy analizie, która
  odbywa się u Maksa na pobranych Logach.
- **Powiadomienie o każdej nowej wersji `main`.** Na `main` trafia kilkanaście
  zmian dziennie, więc kropka na dzwonku świeciłaby stale i tata przestałby
  ją zauważać.
- **Odpowiedź Maksa w Powiadomieniu.** Na razie tylko stan sprawy; komentarze
  z issue wejdą, gdy okaże się, że Maks dzwoni do taty z wyjaśnieniem.
