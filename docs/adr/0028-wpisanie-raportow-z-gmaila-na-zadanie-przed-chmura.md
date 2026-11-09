# ADR 0028: Wpisanie raportów z Gmaila na żądanie taty, przed chmurą

## Status

Zaakceptowana (decyzja Maksa 9.11.2026 po rozmowie z tatą, grill w tej gałęzi). Wyprzedza mapę
[Centrum w chmurze](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1145), która zakładała raporty dopiero
w chmurze ([#1161](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1161)). Zmienia te zdania wcześniejszych
ADR:

- [ADR 0004](0004-centrum-rozliczen-adapter.md) i [ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md): Centrum
  łączy się już nie tylko z GitHubem, ale także ze skrzynką raportów taty w Gmailu, przez IMAP i tylko do odczytu;
- [ADR 0004](0004-centrum-rozliczen-adapter.md), regułę prywatności („Adresy klientów, numery zleceń, treści Wierszy
  danych i tekst wyjątków nie trafiają do przeglądarki”), dla jednego widoku: widok Raporty dostaje wybrane pola
  (niżej), tak jak ADR 0016 zmienił ją dla stron Uzupełnienia;
- [ADR 0004](0004-centrum-rozliczen-adapter.md), zdanie „Własne pliki Centrum to tylko ustawienia taty i dziennik
  pochodzenia Uruchomień; żaden z nich nie jest źródłem Statusu okresu, wyniku ani metryk”: dochodzą pliki Wpisania
  raportów w `config/` (niżej), a pamięć własnych wpisów rozstrzyga o wyniku procesu;
- [ADR 0019](0019-uporzadkowanie-intermax-zmienia-rejestr-zlecen.md): Rejestr zleceń zmienia trzeci proces, Wpisanie
  raportów, i robi to bez Kopii INTERMAX;
- [ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md): dochodzi drugi sekret na komputerze taty, hasło aplikacji
  Google do skrzynki raportów.

## Kontekst

Wykonawcy wysyłają tacie Raporty wykonawcy mailem: w temacie `Raport` i data dnia zleceń, w treści numer zlecenia,
`tak`/`nie` i czynności albo powód nieskuteczności. Tata przepisuje je ręcznie do `SKUTECZNE` i `CZYNNOŚCI
ZREALIZOWANE` w INTERMAX. Mapa chmurowa przeniosła tę funkcję za migrację, ale migracja potrwa, a tata chce mieć ją
wcześniej. INTERMAX edytuje też pracownik taty, na swoim komputerze, przez OneDrive. Centrum na laptopie taty nie
widzi, że pracownik ma plik otwarty, a kopii konfliktu OneDrive nic dziś nie wykrywa.

## Decyzja

- **Na żądanie, nie w tle.** Wpisanie raportów to zwykły proces Centrum, który uruchamia tata kliknięciem, wtedy gdy
  wie, że jego pracownik nie pracuje w INTERMAX. Centrum nie sprawdza skrzynki cyklicznie i nie startuje samo z Windows.
- **Gmail przez IMAP, tylko odczyt.** Hasło aplikacji generuje Maks i wpisuje je do `config/` u taty, poza Gitem i
  OneDrive, jak Token do Zgłoszeń. Narzędzie niczego w skrzynce nie zmienia: nie oznacza maili jako przeczytanych, nie
  przenosi ich i nie usuwa. Odrzucone hasło daje Zgłoszenie do Maksa, a brak sieci tylko Komunikat.
- **Każde kliknięcie liczy od nowa.** Czyta wszystkie Raporty wykonawców z dni od wdrożenia, które należą do okresów bez
  Pliku zbiorczego, przeczytane czy nie. Pamięta tylko to, co samo wpisało, bo bez tego nie odróżni własnego wpisu od
  ręcznego.
- **Bez Kopii INTERMAX.** Wpisanie raportów pisze tylko do pustej komórki albo do własnego wcześniejszego wpisu, którego
  nikt potem nie zmienił, więc z własnej pamięci zawsze wie, co było przed nim. Kopia na każdy zapis zajmowałaby miejsce
  bez potrzeby. Do odtworzenia Uruchomienia wystarcza Kopia wejścia w Logach.
- **Zapis tylko do zamkniętego INTERMAX**, tą samą drogą co Uporządkowanie (ADR 0019). Gdy plik jest otwarty, tata
  dostaje Komunikat i skrzynka nie jest czytana. Gdy po zapisie obok INTERMAX pojawi się kopia konfliktu OneDrive,
  następuje Zatrzymanie dla taty.
- **Co widzi przeglądarka.** Tylko widok Raporty, dla dni okresów bez Pliku zbiorczego: `NUMER ZL.`, `WYKONAWCA`,
  dzień, `SKUTECZNE` i `CZYNNOŚCI ZREALIZOWANE` z INTERMAX i z Wpisów (przy różnicy z ręczną wartością i przy
  „Zostaw moją”), powód problemu i adres nadawcy Raportu wykonawcy spoza listy adresów, żeby tata mógł powiedzieć
  Maksowi, czyj to adres. `ADRES`, `NUMER UMOWY`, tematy i pozostała treść maili nie trafiają do przeglądarki.
- **Własne pliki w `config/`, poza Gitem:** hasło aplikacji (czyta je tylko odczyt skrzynki), adresy Wykonawców
  (prowadzi je Maks), pamięć własnych wpisów i decyzji „Zostaw moją”, dzień wdrożenia i wynik ostatniego kliknięcia
  dla widoku Raporty.
- **Plik zbiorczy się nie zmienia.** Powstaje z INTERMAX dopiero po raportach, a okres z Plikiem zbiorczym jest dla
  Wpisania raportów zamknięty.
- **Rdzeń jest gotowy na chmurę.** Rozpoznawanie Raportów i Wpisów oraz reguły dopasowania do zleceń nie znają ani
  Excela, ani IMAP i przejdą do #1161 bez zmian razem z testami. Tymczasowe są tylko odczyt skrzynki i zapis do
  INTERMAX.

## Odrzucone warianty

- **Czekać na chmurę.** Tata dalej przepisywałby raporty ręcznie przez całą migrację.
- **Sprawdzanie co 5 minut z autostartem z Windows.** Centrum pisałoby do INTERMAX także wtedy, gdy pracownik taty ma go
  otwartego u siebie, a tego nie umie wykryć. Kliknięcie taty przenosi tę wiedzę na człowieka, który ją ma.
- **Gmail API z OAuth.** Zakres `gmail.readonly` jest dla Google ograniczony: aplikacja testowa traci token co 7 dni,
  a publikacja wymaga weryfikacji Google. Dla jednej skrzynki to za dużo zachodu.
- **Zapis przez działającego Excela, gdy plik jest otwarty.** Kasuje tacie historię Cofnij i nie przechodzi, gdy tata
  akurat edytuje komórkę.
- **Kopia INTERMAX przed każdym zapisem.** Patrz decyzja wyżej.
- **Zmiana istniejącego Pliku zbiorczego po późnej poprawce.** Usuwałaby albo dodawała wiersze z Ilościami taty, a
  sytuacja zdarza się tylko po Przygotowaniu, gdy raporty dnia już dawno przyszły.
- **Tryb podglądu przed pierwszym zapisem.** Wykonawcy z listy taty już piszą raporty według wzoru.
