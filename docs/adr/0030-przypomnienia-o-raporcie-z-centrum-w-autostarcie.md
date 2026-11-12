# ADR 0030: Przypomnienia o raporcie z Centrum w Autostarcie laptopa taty

## Status

Zaakceptowana (decyzja Maksa 12.11.2026 po rozmowie z tatą, grill w tej gałęzi). Wyprzedza mapę
[Centrum w chmurze](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1145) tak jak
[ADR 0028](0028-wpisanie-raportow-z-gmaila-na-zadanie-przed-chmura.md). Zmienia te zdania ADR 0028:

- „Na żądanie, nie w tle”: Centrum startuje samo po zalogowaniu taty i w tle wysyła Przypomnienia o raporcie.
  Wpisanie raportów dalej rusza tylko na kliknięcie taty;
- „Gmail przez IMAP, tylko odczyt”: Centrum wysyła maile ze skrzynki raportów przez SMTP Gmaila tym samym hasłem
  aplikacji. Dalej niczego w skrzynce nie oznacza, nie przenosi i nie usuwa;
- „Centrum nie sprawdza skrzynki cyklicznie i nie startuje samo z Windows”: sprawdza ją o 8:00 i 18:00 i startuje
  samo, ale tylko po to, żeby wysłać przypomnienia.

## Kontekst

Wykonawcy nie zawsze wysyłają raport za dzień. Tata przypomina im o tym sam. Chce, żeby Centrum wysyłało
przypomnienie, gdy raportu za dzień nie ma rano następnego dnia, i ponawiało je co 10 godzin, aż raport przyjdzie.
Laptop taty na pewno działa o 8:00. Nie wiadomo, czy działa w nocy albo wieczorem.

## Decyzja

- **Centrum w Autostarcie, bez karty.** Wpis w Autostarcie Windows uruchamia przy logowaniu taty serwer Centrum bez
  otwierania przeglądarki. Skrót z pulpitu działa jak dziś: widzi działające Centrum i otwiera kartę.
- **8:00 i 18:00, nigdy w nocy.** Pierwsze przypomnienie za dzień idzie o 8:00 następnego dnia, kolejne o 18:00 i 8:00
  (10 godzin, z nocą przesuniętą na rano). Pora pominięta przez uśpiony albo wyłączony laptop nadrabia się po jego
  włączeniu do 22:00, później czeka do 8:00.
- **Folder „Wysłane” jest pamięcią.** Przed wysłaniem Centrum sprawdza w skrzynce, czy przypomnienie za ten dzień do
  tego Wykonawcy poszło w ciągu 10 godzin. Restart Centrum ani dwa sprawdzenia naraz nie wysyłają go drugi raz, a
  Centrum nie ma własnego pliku stanu przypomnień.
- **Kto i do kiedy.** Tylko Wykonawcy z listy adresów Wykonawców, którzy mają zlecenia dnia w INTERMAX, czytanym tylko
  do odczytu. Przypomnienia kończy czytelny Raport wykonawcy za ten dzień, nawet niepełny; mail z nieczytelnym
  tematem ich nie kończy. Kończy je też Plik zbiorczy okresu dnia. Liczą się dni od wdrożenia przypomnień, nie od
  wdrożenia Wpisania raportów, a każdy brakujący dzień ma osobny mail.
- **Treść ze wzorem i stopką taty.** Przypomnienie podaje wzór tematu i treści Raportu wykonawcy. Gmail nie dokleja
  stopki do maili z SMTP, więc stopka taty leży jako tekst w `config/` obok adresów Wykonawców; bez niej przypomnienie
  idzie bez stopki, a widok Raporty o tym mówi.
- **Odpowiedź na przypomnienie jest raportem.** Pracownik najczęściej kliknie „Odpowiedz”, a dotąd każdy temat z
  `Re:` był pomijany. Odpowiedź na Przypomnienie o raporcie jest Raportem wykonawcy za dzień z jego tematu; liczy się
  tylko tekst nad cytatem, a numery z przykładu w przypomnieniu nigdy nie dają Wpisu, żeby cytat nie dopisał
  fałszywego zlecenia (ADR 0029).
- **Tata widzi przypomnienia** w okienku dnia Wykonawcy na mapie cieplnej widoku Raporty: kiedy poszły.
- **Próba przed Wydaniem.** Maks uruchamia na prawdziwej skrzynce taty próbę, która liczy, komu i za które dni poszłyby
  przypomnienia, a wysyła jeden mail tylko na adres Maksa. Po Wydaniu nie ma trybu próbnego.

## Odrzucone warianty

- **Czekać na chmurę.** Tata dalej przypominałby ręcznie przez całą migrację.
- **Osobne narzędzie z Harmonogramu zadań Windows.** Działałoby także przy zamkniętym Centrum, ale to drugi program
  z własnymi Logami i drugim źródłem dla widoku Raporty. Centrum zamknięte przez tatę to rzadki wyjątek, który nadrabia
  następne uruchomienie.
- **6:00 rano i dosłownie co 10 godzin przez całą dobę.** O 6:00 laptop taty może jeszcze nie działać, a przypomnienia
  o 2:00 czy 4:00 budziłyby pracowników.
- **Własny plik z wysłanymi przypomnieniami.** Folder „Wysłane” już to wie, a plik mógłby rozjechać się ze skrzynką.
