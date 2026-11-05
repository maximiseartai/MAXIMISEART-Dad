# ADR 0007: Zgłoszenia do Maksa w prywatnym repo

## Status

Zaakceptowana. Zmienia trzy zdania
[ADR 0004](0004-centrum-rozliczen-adapter.md):

- regułę prywatności, dla jednej treści: Zgłoszenia;
- „Własne pliki Centrum to tylko ustawienia taty i dziennik pochodzenia
  Uruchomień”: dochodzą klucz do Zgłoszeń, stan wysłanych Zgłoszeń i kolejka
  Skrzynki Zgłoszeń (`config/zgloszenia/kolejka/`), wszystkie w `config/` poza
  Gitem;
- „Nie ma … zdalnego dostępu”: Centrum nadal nie przyjmuje połączeń spoza
  komputera taty, ale samo łączy się z API GitHuba w przypadkach wymienionych
  niżej.

Pozostałe zasady ADR 0004 (tylko `127.0.0.1`, kontrola `Host` i `Origin`,
pliki wyłącznie z wyliczonych ścieżek) zostają bez zmian.

Zdania tego ADR zmieniają później:
[ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md) (pobranie narzędzia z
`github.com` przez Git i Aktualność narzędzia w Konfiguracji),
[ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md) (Kontrola ilości
idzie do Skrzynki bez kliknięcia taty i z treścią wybranych kolumn) i
[ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md) (Logi
Uruchomienia, Uwagi taty i lista Wydań) i
[ADR 0025](0025-regula-danych-wysylki-do-skrzynki.md) (o treści wierszy w
każdej wysyłce rozstrzyga reguła danych ze strażnikiem przed wysyłką).

## Decyzja

Przy Zatrzymaniu, którego tata nie usunie sam, Centrum rozliczeń wysyła
Zgłoszenie jako issue z etykietą `zgloszenie` do prywatnego repozytorium
`MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia`, nie do publicznego repozytorium
narzędzia. Tata wysyła je jednym kliknięciem po Diagnozie i przed wysłaniem
widzi jego dokładną treść.

To pierwsze połączenie narzędzia z internetem z własnej inicjatywy taty i
pierwszy sekret na jego komputerze:

- Centrum łączy się wyłącznie z API GitHuba: przy wysyłce Zgłoszenia, przy
  sprawdzaniu stanu wysłanych Zgłoszeń (także przy pytaniu w Diagnozie, czy
  problem ma już otwarte Zgłoszenie) i przy sprawdzeniu aktualności
  narzędzia w Diagnozie. Brak sieci nie daje Komunikatu, dopóki tata niczego
  nie wysyła.
- Klucz to token fine-grained, który Maks tworzy ręcznie: tylko repozytorium
  Zgłoszeń, uprawnienie Issues (odczyt i zapis), ważność najwyżej rok. Maks
  wpisuje go do `config/zgloszenia-klucz.txt` poza Gitem; tata nie ma pola na
  klucz. Klucz nie trafia do odpowiedzi Centrum, dziennika, Zgłoszenia ani
  przeglądarki; Konfiguracja pokazuje tylko „gotowe”, „brak klucza” albo
  „klucz odrzucony” (#426).
- Co Skrzynka mówi o kluczu, wie jedno miejsce (`KeyedBox`): odmowa przy
  zakładaniu issue albo liście issue odrzuca klucz, każda inna odpowiedź go
  przyjmuje, a brak sieci niczego nie zmienia. Limit zapytań GitHuba (403 z
  „rate limit” w treści) to brak sieci, nie odmowa. Odmowy komentarza werdykt
  nie liczy, bo to 404 issue, które Maks usunął. Gdy żadna wysyłka nie
  odpowiedziała niedawno, Konfiguracja i Diagnoza zlecają jedno tanie pytanie
  (lista otwartych Zgłoszeń); Konfiguracja czeka na nie najwyżej sekundę.
  Odrzucony klucz przez kwadrans nie idzie do Skrzynki, a nowy klucz Maksa jest
  sprawdzany od razu. Diagnoza pokazuje stan klucza jako sprawdzenie, które
  nigdy nie jest wyjaśnieniem Zatrzymania.
- Skrzynka Zgłoszeń jest adapterem wstrzykiwanym do Centrum obok platformy.
  Testy i `verify-centrum-rozliczen` nigdy nie łączą się z prawdziwym GitHubem.
- „Wyślij do Maksa” kładzie dokładnie podgląd w kolejce Skrzynki Zgłoszeń
  (#426), tej samej co Kontrole ilości, Logi i Uwagi (ADR 0015), i czeka na
  Skrzynkę najwyżej 5 s. Bez sieci albo klucza Zgłoszenie czeka w kolejce, a
  kolejka sama ponawia wysyłkę co minutę. Karta mówi, czy czeka na internet,
  czy na klucz od Maksa, a Powiadomienia pokazują je jako czekające.
  Komunikat (`ZGLOSZENIE_NIEZAPISANE`) jest tylko wtedy, gdy nie da się zapisać
  pliku kolejki. Dawniej niewysłane Zgłoszenie zostawało plikiem Markdown w
  `config/zgloszenia/` z Komunikatem „prześlij mailem”. Centrum nigdy nie
  działało u taty w tej wersji, więc nie ma kodu, który przenosi takie pliki
  do kolejki: plik, który by został, Maks wyśle ręcznie albo usunie, a
  Kontrola ilości dalej oczekuje w `config/zgloszenia/` tylko kolejki.
- Sprawy Zgłoszeń (odcisk problemu, numer issue, commit narzędzia) Centrum
  pamięta jako Sprawy taty w `config/sprawy-taty.json` poza Gitem; sprawa w kolejce nie
  ma jeszcze numeru i dostaje go przy dostarczeniu. Jeden problem ma jedno
  otwarte Zgłoszenie: kolejka szuka w skrzynce otwartego Zgłoszenia z tym
  samym odciskiem (wiersz `Odcisk problemu` w treści) i dopisuje do niego
  komentarz „Zgłoszenie wróciło” z całą treścią nowego Zgłoszenia zamiast
  zakładać nowe (#820). Zgłoszenie z treścią równą wysyłanej założyła
  przerwana próba tej samej wysyłki (między założeniem issue a znacznikiem
  dostarczenia): kolejka przejmuje je bez komentarza. Problem, którego Zgłoszenie czeka w kolejce, nie trafia do niej
  drugi raz. Gdy
  Maks je zamknął, a problem wraca, nowe Zgłoszenie ma odnośnik do
  poprzedniego. Bez odpowiedzi skrzynki problem wysłany z tego komputera
  czeka na naprawę, także po restarcie Centrum.
- Powrót problemu, którego Zgłoszenie jest otwarte, idzie do Kolejki wysyłki
  sam, bez „Wyślij do Maksa” (#820): gdy po Diagnozie Zatrzymania odpowiedź
  skrzynki (a bez niej Sprawy taty) mówi, że Zgłoszenie tego odcisku czeka na
  naprawę, Centrum kładzie w kolejce dokładnie podgląd z tej Diagnozy, a kolejka
  dopisuje go komentarzem „Zgłoszenie wróciło”. Tata nic nie klika i widzi to,
  co dotąd: „Zgłoszenie tego problemu już jest wysłane i czeka na naprawę”, bez
  przycisku. Przycisk przy otwartym Zgłoszeniu kazałby tacie zgłaszać problem,
  o którym Maks już wie, a bez przycisku i bez wysyłki samej Maks nie widziałby,
  że problem wraca. Logi Uruchomienia z tą samą Diagnozą i tak wychodzą same
  (ADR 0015). Jedno Zatrzymanie daje najwyżej jeden komentarz powrotu:
  powtórzona Diagnoza na tej samej karcie go nie dubluje. Nieudana Aktualizacja
  narzędzia nie ma Diagnozy, więc jej powrót przy otwartym Zgłoszeniu nie idzie
  do kolejki.

Rewizja reguły prywatności: Zgłoszenie opuszcza komputer taty, ale niesie tylko
to, co reguła ADR 0004 już dopuszcza w Centrum (Komunikat w trzech częściach,
ze skróconymi ścieżkami, wynik sprawdzeń Diagnozy, bezpieczne wpisy dziennika
Centrum) oraz proces, okres, tryb, wersję i commit narzędzia. Przy
nieoczekiwanym błędzie, a także przy Zatrzymaniu, które ma przyczynę w wyjątku
(„do Maksa” i od #976 Powtórka Zatrzymania dla taty), dochodzi typ wyjątku z typami jego przyczyn i ślad wywołań w kodzie
narzędzia (plik względem katalogu narzędzia, linia, funkcja); Centrum trzyma go w pamięci
tylko przy tym Zatrzymaniu, poza dziennikiem, metrykami i innymi odpowiedziami.
Bez treści wierszy, adresów, numerów zleceń, stawek, treści wyjątków i pełnych
ścieżek. Jedyny wyjątek jest ten sam co w regule ADR 0004: Komunikat
Zatrzymania o brakach w `SKUTECZNE` (`ZLE_SKUTECZNE`, specyfikacja #206) niesie
dokładną zawartość komórek `SKUTECZNE` innych niż `tak` i `nie`, bo to kolumna
stanu zlecenia, nie dane klienta, a tata musi widzieć, co poprawić.

Diagnoza, z której powstaje Zgłoszenie, sprawdza pliki w OneDrive zaraz po
Ustawieniach taty, przed odczytem Rejestru zleceń, wzorców i plików okresu
(specyfikacja #153 wymienia OneDrive jako siódme sprawdzenie). Plik tylko w
chmurze może się nie otworzyć, a wtedy wyjaśnieniem ma być rada o OneDrive, nie
Komunikat o uszkodzonym pliku.

Naprawa odbywa się w publicznym repozytorium narzędzia. PR odwołuje się do
Zgłoszenia samym numerem, a przypadek testowy powstaje na danych syntetycznych;
treść Zgłoszenia nie trafia do publicznych PR-ów, commitów ani issue.

## Zagrożenia, przed którymi chroni prywatne repo

- Wyciek: nawet bezpieczna treść mówi o pracy taty (okresy, nazwy plików,
  Wykonawcy w Komunikatach), a publiczne issue czyta każdy.
- Wstrzykiwanie poleceń: publiczne issue może skomentować każdy. Zgłoszenia
  naprawia także agent, więc obcy tekst w wątku Zgłoszenia byłby poleceniem dla
  agenta z dostępem do repozytorium narzędzia. Do prywatnego repo piszą tylko
  Maks i klucz taty.

## Odrzucone warianty

- Prywatne repozytorium samego narzędzia: CI ma 6 z 7 zadań na
  `windows-latest` (podwójne minuty Actions, ok. 140 uruchomień CI tygodniowo),
  a `git pull` u taty wymagałby logowania.
- Publiczne issue z okrojoną treścią: bez ścieżek i Komunikatu Maks i tak
  dopytywałby tatę, a wstrzykiwanie poleceń przez komentarze obcych zostaje.
