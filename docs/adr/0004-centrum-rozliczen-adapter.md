# ADR 0004: Centrum rozliczeń jako adapter Uruchomienia procesu

## Status

Zaakceptowana. Zastępuje część [ADR 0003](0003-cli-only-launcher.md), według
której procesy są uruchamiane wyłącznie przez CLI i launchery `.cmd`.
Rezygnacja z adaptera VBA z ADR 0003 pozostaje w mocy.
[ADR 0006](0006-uklad-folderow-taty-i-wspolne-ustawienia.md) zmienia zdanie o
launcherach: czytają one Ustawienia taty z Centrum rozliczeń.
[ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md) rewiduje regułę
prywatności dla treści Zgłoszenia wysyłanego do Maksa, dodaje własne pliki
Centrum dla Zgłoszeń i pozwala Centrum łączyć się z API GitHuba przy
Zgłoszeniach i Diagnozie.
[ADR 0010](0010-centrum-jedynym-wejsciem-taty.md) podejmuje odłożoną tu decyzję:
launchery `.cmd` znikają, Centrum jest jedynym wejściem taty, a CLI zostaje
narzędziem osoby utrzymującej.
[ADR 0011](0011-bez-cli-i-adapterow-terminala.md) usuwa CLI i adaptery
terminala: procesy mają jedną rozmowę z tatą, w Centrum, a Komunikat nie ma
linii terminala (`terminal_line`).
[ADR 0016](0016-uzupelnienie-pliku-zbiorczego-w-centrum.md) zmienia dla stron
Uzupełnienia pliku zbiorczego regułę prywatności (przeglądarka dostaje wybrane
pola wierszy Ilości do uzupełnienia) i pozwala czytać Plik zbiorczy otwarty w
Excelu.
[ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md) dodaje wyjątek do zdania
„Pliki i foldery otwiera tylko wtedy, gdy sam wyliczył je z folderu okresów”:
katalog samego narzędzia, który Centrum zmienia wyłącznie przez Aktualizację
narzędzia.
Zdanie „Własne pliki Centrum to tylko ustawienia taty i dziennik pochodzenia
Uruchomień” zmieniają też
[ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md) (Logi
Uruchomienia i stan Powiadomień),
[ADR 0017](0017-karta-uruchomienia-z-logow.md) (plik ostatniego startu) i
[ADR 0019](0019-uporzadkowanie-intermax-zmienia-rejestr-zlecen.md) (Kopie
INTERMAX). ADR 0019 dodaje też trzeci proces, Uporządkowanie INTERMAX, z tym
samym rdzeniem Uruchomienia procesu.
[ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md) dopuszcza treść
wybranych kolumn Wiersza danych tylko w Kontroli ilości, wysyłanej do Skrzynki
Zgłoszeń; przeglądarka jej nie dostaje.
[ADR 0028](0028-wpisanie-raportow-z-gmaila-na-zadanie-przed-chmura.md) pozwala
Centrum czytać skrzynkę raportów taty w Gmailu przez IMAP, zmienia regułę
prywatności dla widoku Raporty (wybrane pola zleceń i Wpisów raportu) i dodaje
własne pliki Wpisania raportów, z których pamięć własnych wpisów rozstrzyga o
wyniku procesu.
[ADR 0029](0029-raport-wykonawcy-wazniejszy-od-intermax.md) poszerza pamięć
własnych wpisów o Przeniesienia zleceń i Zlecenia dopisane z raportu.
[ADR 0030](0030-przypomnienia-o-raporcie-z-centrum-w-autostarcie.md) pozwala
Centrum wysyłać Przypomnienia o raporcie przez SMTP Gmaila, dodaje plik stopki
taty w `config/` i pokazuje w widoku Raporty pory wysłanych przypomnień.

## Decyzja

Przebieg rozliczeń i Przygotowanie pliku zbiorczego mają dwa wejścia do tych
samych procesów: CLI z launcherami `.cmd` jako ścieżkę zapasową oraz Centrum
rozliczeń, lokalną aplikację w przeglądarce. Oba wejścia są rozmówcami tego
samego rdzenia Uruchomienia procesu: ten sam pomiar czasu, te same metryki, te
same linie komunikatów i ta sama projekcja postępu z ADR 0002, dla której
Centrum jest trzecim adapterem obok plain i Rich. Reguły procesów pozostają
wyłącznie w silniku Python (ADR 0001). Przeglądarka niczego nie wylicza ani nie
interpretuje Zdarzeń przebiegu.

Centrum działa jako lokalny serwer w tle na komputerze taty, w tym samym
procesie co silnik, bez okna konsoli. Nasłuchuje wyłącznie na `127.0.0.1`.
Odrzuca każde żądanie z nagłówkiem `Host` spoza localhost, a akcje zmieniające
stan przyjmuje tylko z `Origin` Centrum. Nie ma logowania, zdalnego dostępu ani
własnej bazy danych: stan wylicza przy każdym odczycie z folderu okresów,
plików metryk i konfiguracji. Przeglądarka może pokazać ostatnią odczytaną
kopię z pamięci karty, dopóki nie przyjdzie nowy odczyt; kopię czyści zmiana
folderu okresów albo Rejestru zleceń i odświeżenie karty, a źródłem stanu
zostaje serwer. Własne pliki Centrum to tylko ustawienia taty i
dziennik pochodzenia Uruchomień (niżej); żaden z nich nie jest źródłem Statusu
okresu, wyniku ani metryk. Pliki i foldery otwiera tylko wtedy, gdy sam
wyliczył je z folderu okresów, nigdy dla ścieżki podanej w żądaniu.

Reguła prywatności: do Centrum trafia tylko to, co przechodzi przez seam
obserwacji z ADR 0002 (snapshoty projekcji i neutralne powiadomienia), oraz
bezpieczne komunikaty procesu wspólne z terminalem. Adresy klientów, numery
zleceń, treści Wierszy danych i tekst wyjątków nie trafiają do przeglądarki,
dziennika Centrum ani metryk. Jedynym wyjątkiem jest Zatrzymanie o brakach w
`SKUTECZNE` (`ZLE_SKUTECZNE`, specyfikacja #206): pokazuje dokładną zawartość
komórek `SKUTECZNE` innych niż `tak` i `nie`, więc ta zawartość trafia do
przeglądarki, Zgłoszenia i historii Uruchomień. `SKUTECZNE` to kolumna stanu
zlecenia, nie dane klienta, a tata musi widzieć, co poprawić. Typowane błędy silnika niosą jawny bezpieczny
komunikat dla taty (`message`), napisany jak komunikat, nie jak opis błędu;
terminal i Centrum biorą go stamtąd, nigdy z `str()` wyjątku.

Komunikaty w Centrum mają tę samą treść co w terminalu, ale inną postać:
Centrum dostaje każde zatrzymanie, ostrzeżenie i decyzję taty jako strukturę w
trzech częściach (co się stało, gdzie, co zrobić) z tego samego katalogu
komunikatów, a nie linie terminala do parsowania. Linie wyłącznie terminalowe
(`Status końcowy`, `Czas uruchomienia`, statystyki P50/P95, plan z pełną ścieżką
Folderu rozliczeń pracowników) nie trafiają do przeglądarki; zastępuje je tytuł
wyniku i podsumowanie z samymi nazwami plików. Treść różni się tylko tam, gdzie
różni się rozmowa:

- zgodę na niepełny okres wyraża się w terminalu wpisaniem `t`, a w Centrum
  przyciskiem `Kontynuuj`; mówi o tym rozmówca, nie proces;
- terminal Przebiegu rozliczeń pokazuje zatrzymanie dawną jedną linią, a
  Centrum ten sam komunikat w trzech częściach.

Dziennik pochodzenia Uruchomień, `config/centrum-uruchomienia.jsonl`, to
lokalny plik Centrum obok ustawień, poza gitem. Schemat metryk się nie zmienia,
a historia ma odróżniać Uruchomienia z Centrum od tych z `.cmd`, więc po każdym
Uruchomieniu z Centrum dopisuje on parę (proces, `started_at`) rekordu metryk,
który to Uruchomienie dodało. Zawiera tylko te dwa bezpieczne fakty. Brak,
uszkodzenie albo nieudany zapis pliku oznacza jedynie, że Uruchomienie pokaże
się w historii jako `.cmd`; nigdy nie zmienia wyniku, zapisu ani metryk.
Rekord rozpoznaje okno czasu Uruchomienia, więc Uruchomienie z `.cmd` tego
samego procesu, które wystartuje w tym oknie, też zostanie oznaczone jako z
Centrum. To rzadkie (tata nie prowadzi dwóch Uruchomień naraz) i tylko
kosmetyczne, więc nie uzasadnia zmiany schematu metryk.

Launchery `.cmd` i CLI zostają bez zmian. Ich porzucenie to osobna, przyszła
decyzja z własnym ADR, podejmowana dopiero wtedy, gdy Centrum przejmie całą
pracę taty.

## Uzasadnienie

Terminal nie jest miejscem pracy taty: każde Uruchomienie procesu to okno
konsoli, ponowne wskazywanie tych samych plików, pytanie `t`/`n` wpisywane z
klawiatury i szukanie komunikatu w instrukcji. Stanu okresów i historii
Uruchomień procesu nie widać nigdzie.

ADR 0003 odrzucił drugie wejście, bo adapter VBA wymagał ręcznej bramy
walidacji w Excelu, zależał od polityki makr i dokładał ukryte przełączniki do
CLI. Centrum nie powtarza tych kosztów: działa w tym samym procesie co silnik i
przez ten sam rdzeń Uruchomienia procesu, więc nie powstaje druga kopia reguł,
drugi pomiar ani drugi zestaw komunikatów. Cel z ADR 0003, jeden proces taty
działający w tle, jest bliżej z Centrum niż z terminala.

Serwer HTTP na localhost jest osiągalny z każdej strony otwartej w przeglądarce
taty, a dane klientów są poufne. Stąd nasłuch tylko na `127.0.0.1`, kontrola
`Host` przeciw DNS rebinding, kontrola `Origin` przed akcjami zapisu i otwieranie
wyłącznie plików wyliczonych przez serwer.

Launchery `.cmd` zostają, bo działają dziś i mają testy. Do czasu, aż Centrum
przejmie całą pracę, są ścieżką zapasową, gdy Centrum nie wystartuje.

## Konsekwencje

- Zmiana reguł procesu odbywa się w silniku i działa w obu wejściach. Centrum
  nie dostaje własnych reguł.
- Moduł Uruchomienia procesu wydziela rdzeń, z którym rozmawiają terminal i
  Centrum. Decyzja taty o niepełnym okresie jest częścią tej rozmowy: w Centrum
  to stan czekający na odpowiedź taty, nie pytanie w terminalu. Czas czekania
  nie wlicza się do czasu Uruchomienia procesu ani do metryk.
- Wejście CLI zachowuje dzisiejsze zachowanie, a jego testy pilnują regresji
  wydzielenia rdzenia.
- Uruchomienia z obu wejść trafiają do tych samych plików metryk, bez zmiany
  schematu. Pochodzenie Uruchomienia (Centrum albo `.cmd`) i udany podgląd bez
  zapisu okresu Centrum wylicza z tych plików i z dziennika pochodzenia, nie z
  pamięci karty przeglądarki.
- Serwer prowadzi jedno Uruchomienie procesu naraz. Między CLI a Centrum nie ma
  blokady: przed zderzeniem chronią Nienadpisywanie i atomowa publikacja plików
  okresu.
- Awaria adaptera Centrum odłącza go bez wpływu na wynik, zapis i metryki, tak
  jak awaria adaptera terminala (ADR 0002). Dotyczy to obserwatora postępu;
  przygotowanie widoku wyniku jest częścią rdzenia, jak podsumowanie w
  terminalu, więc jego awaria to błąd po silniku z Komunikatem z katalogu
  procesu i `BLAD_KRYTYCZNY` w metrykach.
- Zmiany w Centrum weryfikuje end-to-end skill `verify-centrum-rozliczen`.
- Edycja danych w Centrum wymaga osobnego ADR i rewizji reguły prywatności.
