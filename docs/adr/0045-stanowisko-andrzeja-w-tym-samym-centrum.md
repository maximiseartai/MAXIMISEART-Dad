# ADR 0045: Stanowisko Andrzeja w tym samym Centrum rozliczeń

## Status

Przyjęta (decyzje Maksa z 20.11.2026, grill specyfikacji
[#2439](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/2439)). Zmienia:

- [ADR 0010](0010-centrum-jedynym-wejsciem-taty.md): Centrum rozliczeń jest wejściem taty i także Andrzeja,
  pracownika biura taty, na jego laptopie, w Zakresie jego Stanowiska;
- [ADR 0019](0019-uporzadkowanie-intermax-zmienia-rejestr-zlecen.md): Kopie INTERMAX leżą osobno na każdym komputerze,
  który porządkuje INTERMAX, a przed Kopią i zapisem Uporządkowanie sprawdza, czy obok INTERMAX nie leży kopia
  konfliktu OneDrive;
- [ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md): Skrzynka Zgłoszeń jest jedna dla obu Stanowisk, a to, co
  przychodzi ze Stanowiska Andrzeja, ma w tytule prefiks `ANDRZEJ`, a w tagu Archiwum Logów okresu
  `andrzej-logi-<okres>` (wdraża [#2454](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/2454)); pliki
  repozytorium nazywają Andrzeja z imienia, bo to nazwa jego Stanowiska, zamiast „pracownik taty”.

## Kontekst

Andrzej też porządkuje zlecenia w INTERMAX: wkleja Surowe zlecenia z Aplikacji firmowej i uzupełnia dzień.
Uporządkowanie INTERMAX działało tylko w Centrum na komputerze taty, więc Andrzej czekał na tatę przy każdym dniu.
Centrum taty pokazuje okresy, Pliki zbiorcze, kwoty, Rozliczenia pracowników, skrzynkę raportów i efenix, których
Andrzej ma nie widzieć ([#1153](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1153)).

## Decyzja

- **Stanowisko to zachowanie narzędzia, nie Ustawienie Centrum** ([ADR 0032](0032-ustawienia-centrum-zmienia-tata.md)).
  Leży w jednym pliku `config/stanowisko.txt`, który zapisuje instalator skrótu z `--stanowisko andrzej`. Centrum
  czyta je raz przy starcie: brak pliku to Stanowisko taty, więc komputer taty nie potrzebuje migracji, a nieznana
  wartość to Komunikat startu `NIEZNANE_STANOWISKO`, nigdy Stanowisko taty.
- **Jedna tabela Zakresu** (`scope.SCOPES`). Stanowisko taty ma każdą Funkcję, a Stanowisko Andrzeja Uporządkowanie
  INTERMAX i Kopie INTERMAX. Stałe części ma każde Stanowisko: Uruchomienia z Diagnozą, Zgłoszenia, Uwagi,
  Powiadomienia, Aktualizację narzędzia, Foldery z Rejestrem zleceń, Wygląd, Historię Ustawień i zamknięcie Centrum.
- **Funkcji spoza Zakresu w Centrum nie ma.** Jej trasy nie istnieją (404 dla każdej metody pod `/api/`), jej praca w
  tle nie rusza, `GET /api/settings` ma w jej polach `null`, a właściciel Ustawień nie czyta, nie pamięta i nie zmienia
  jej plików w `config/`, także Zmianami z Wydania. Stanowisko bez autostartu nie dostaje od instalatora skrótu w
  Autostarcie.
- **Start bez Wzorców.** Stanowisko bez Funkcji Wzorców nie sięga po Wzorce: Konfiguracja ich nie sprawdza, a zdania
  reguł w Historii Ustawień, które czytają cennik Wzorca pliku zbiorczego, są tylko z Funkcją Ilości. Uporządkowanie i
  jego Diagnoza Wzorców nie czytają, więc Maks nie kopiuje Wzorców taty na laptop Andrzeja.
- **Frontend zna Funkcje, nie Stanowiska.** Strona startowa to pierwsza strona menu w Zakresie, u Andrzeja
  Uruchomienia, a adres strony spoza Zakresu otwiera stronę startową. Stanowiska nie widać nigdzie.
- **Uporządkowanie bez zmian.** Ten sam proces, te same Komunikaty, Zatrzymania i Kopia INTERMAX przed zapisem, na
  komputerze, na którym biegnie. Dwa komputery na jednym INTERMAX w OneDrive chronią istniejące Zatrzymania: kopia
  konfliktu OneDrive obok INTERMAX ([#2451](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/2451)) i drugie
  wklejenie Dnia uporządkowanego.
- **Jeden kanał Wydań.** Andrzej aktualizuje narzędzie tym samym przyciskiem i z tych samych Wydań co tata.

## Odrzucone warianty

- **Osobne repozytorium Zgłoszeń Andrzeja.** Andrzej nie dotyka tokenu, a dwa repozytoria podwajają narzędzia Maksa do
  Skrzynki.
- **Osobna aplikacja dla Andrzeja.** Dwie kopie składania Uruchomień, Zatrzymań, Kolejki wysyłki i Aktualizacji.
- **Blokada INTERMAX między komputerami.** OneDrive nie daje wspólnej blokady, a kopię konfliktu i drugie wklejenie
  dnia łapią istniejące Zatrzymania.
- **Widok aktywności Andrzeja w Centrum taty.** Zostaje dla Centrum w chmurze
  ([#1157](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1157)).
- **Stanowisko w oknie Ustawień.** Tata albo Andrzej zmieniłby nim Zakres, który należy do Maksa.
- **Nieznana wartość jako Stanowisko taty.** Literówka w pliku na laptopie Andrzeja dałaby mu całe Centrum taty.

## Konsekwencje

- Stanowisko to rola jednego komputera, nie zabezpieczenie: kto zmieni plik w `config/`, zmieni Zakres. Logowanie i
  role należą do Centrum w chmurze (#1157, [#1168](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1168)).
- Token do Zgłoszeń Andrzeja czyta też Zgłoszenia i Archiwum Logów okresu taty, z adresami zamaskowanymi Regułą
  danych; to ryzyko Maks przyjął w specyfikacji #2439.
- Nowa trasa API bez Funkcji psuje strażnika tras w `tests/test_centrum_rozliczen.py`, więc nie trafia do Centrum
  Andrzeja przez pomyłkę.
