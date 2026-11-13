# ADR 0032: Ustawienia Centrum zmienia tata, Maks tylko zachowanie narzędzia

## Status

Zaakceptowana (decyzja Maksa 13.11.2026, grill w tej gałęzi). Zmienia:

- [ADR 0006](0006-uklad-folderow-taty-i-wspolne-ustawienia.md): Ustawienia taty, czyli Rejestr zleceń i folder
  okresów, stają się częścią Ustawień Centrum. Folder okresów zapisuje się zawsze od folderu, od którego liczy się
  układ folderów taty (`Załączniki`), choćby tata wskazał folder tygodnia w środku;
- [ADR 0028](0028-wpisanie-raportow-z-gmaila-na-zadanie-przed-chmura.md): adresy Wykonawców przestaje prowadzić
  Maks, prowadzi je tata w Liście Wykonawców. Hasło aplikacji tata może wymienić sam;
- [ADR 0030](0030-przypomnienia-o-raporcie-z-centrum-w-autostarcie.md): pory 8:00–17:00 i 18:00–22:00, godzina
  pierwszego przypomnienia, stopka i treść maila to Ustawienia Centrum z dzisiejszymi wartościami jako domyślnymi.
  Przypomnienia idą tylko do aktywnych Wykonawców z włączonymi przypomnieniami. Temat zostaje stały;
- widok Konfiguracja, który był tylko do odczytu („Zmiany robi osoba utrzymująca narzędzie”), znika. Jego treść
  przechodzi do okna Ustawień.

Reguły ilości jako Ustawienia Centrum opisuje [ADR 0033](0033-reguly-ilosci-naleza-do-taty.md).

## Kontekst

Tata prosi Maksa o podstawowe zmiany: kolejnych pracowników do listy adresów, nazwę Wykonawcy, godziny
przypomnień. Każda taka zmiana to ręczna edycja pliku w `config/` na komputerze taty albo zmiana kodu i Wydanie.
W Centrum tata zmieniał dotąd tylko Rejestr zleceń, folder okresów i motyw. Ponad 30 innych wartości to pliki
w `config/` prowadzone przez Maksa, Wzorce w Excelu albo stałe w kodzie.

## Decyzja

- **Granica: dane o pracy taty kontra zachowanie narzędzia.** Ustawienia Centrum to to, co tata wie lepiej od
  Maksa: kto u niego pracuje i z jakich adresów pisze, foldery, pory przypomnień, Reguły ilości. Maks zostaje od
  działania narzędzia: token okresu, święta, Kolor operatora, reguły Uporządkowania INTERMAX, efenix, porty, kanał
  Aktualizacji, temat przypomnienia (po nim Wpisanie raportów poznaje odpowiedzi) i Token do Zgłoszeń.
- **Jedno miejsce zmiany: okno Ustawień.** Otwiera się z przycisku w stopce menu nad „Zamknij Centrum rozliczeń”,
  nad rozmytym Centrum, z sekcjami po lewej (wzorem okna ustawień T3 Code). Adres `#/ustawienia/<sekcja>` otwiera je
  nad bieżącym widokiem. Okresy, Uruchomienia i Raporty nie mają już własnych wyborów plików, tylko link do
  właściwej sekcji.
- **Zmiana działa od razu**, bez ponownego startu Centrum. Uruchomienie procesu, które już trwa, kończy na
  wartościach z chwili startu. Przełącznik albo pojedynczy wybór zapisuje się od razu, a formularz z kilkoma
  polami dopiero przyciskiem „Zapisz”, nigdy w połowie.
- **Zła wartość się nie zapisuje.** Centrum sprawdza ją przed zapisem i mówi jednym zdaniem, co poprawić.
- **Historia Ustawień.** Każda zmiana zapisuje, kiedy, co i wartość przed i po, przy sekrecie tylko to, że się
  zmienił. Z Historii tata cofa zmianę. Zgłoszenie podaje zmiany z ostatnich 30 dni.
- **Lista Wykonawców w jednym pliku** zastępuje osobne pliki identyfikatorów i adresów, które musiały się zgadzać.
  Pierwszy start po Aktualizacji łączy oba stare pliki i zostawia je jako kopię. Wykonawca może mieć świadomie
  dodany drugi login. Dwa różne wpisy z tą samą nazwą dalej są odrzucane. Wykonawcy z identyfikatorem w
  którymkolwiek okresie nie da się usunąć, tylko oznaczyć jako Nieaktywnego. Zmiana nazwy ostrzega, gdy w okresie
  leży już Rozliczenie pracownika ze starą nazwą; plików taty nic nie przemianowuje.
- **Zmiana pór nie daje drugiego maila tej samej pory** (decyzja Maksa przy przeglądzie #1568). „Najwyżej jedno w
  porze” z ADR 0030 liczy się według nazwanej pory, porannej albo wieczornej, przy porach z chwili wysyłki:
  poranne przypomnienie wysłane o 8:05 zamyka poranną porę tego dnia także po przesunięciu jej na 9:00–17:00.
  Nowe pory działają od następnego sprawdzenia dla pór, które tego dnia jeszcze nie poszły. Folder „Wysłane” zna
  tylko chwilę wysyłki, więc praca przypomnień zapisuje w `config/` pory, przy których sprawdzała, i od kiedy
  (`przypomnienia-pory.json`); to zmienia zdanie ADR 0030, że Centrum nie ma własnego pliku stanu przypomnień.
  Pamięcią wysłanych zostaje „Wysłane”. Przypomnienia sprzed pierwszego zapisu pór wysłała wersja sprzed Ustawień
  Centrum, więc liczą pory z ADR 0030, także w dniu Aktualizacji, gdy tata od razu zmieni pory.
- **Hasło skrzynki raportów wymienia tata** polem, które nigdy nie pokazuje starej wartości. Token do Zgłoszeń
  zostaje u Maksa; tata widzi jego stan.
- **Furtka Maksa.** Wydanie zmienia Ustawienia Centrum tylko jawną, nazwaną zmianą. Trafia ona do Historii z
  numerem Wydania i tata może ją cofnąć. Pliki w `config/` zostają czytelne; zmianę zrobioną w nich ręcznie Centrum
  zauważa i zapisuje w Historii jako zmianę spoza Centrum.
- **Lokalnie i nienadpisywane.** Ustawienia Centrum leżą w `config/` na komputerze taty, poza Gitem. Aktualizacja
  narzędzia ich nie nadpisuje; nowe ustawienie przychodzi z wartością domyślną. Jeden moduł jest ich właścicielem,
  więc da się je przenieść do chmury bez szukania czytelników po kodzie.
- **Stawki nie są Ustawieniem Centrum.** Leżą w wierszu 14 Wzorca pliku zbiorczego i Wzorca rozliczenia
  pracownika, wspólne dla wszystkich Wykonawców, i od 20.10 się nie zmieniły. Tata zmienia je w Excelu.

## Odrzucone warianty

- **Zapisz i uruchom Centrum ponownie.** Centrum i tak czyta pliki z `config/` przy każdym Uruchomieniu procesu i
  przy każdym sprawdzeniu przypomnień, więc restart niczego nie daje, a przerywa tacie pracę.
- **Ustawienia jako zwykły widok w menu.** Maks wybrał okno nad bieżącym widokiem, jak w T3 Code; zmiana
  ustawienia nie wyprowadza taty z miejsca, w którym pracuje.
- **Ekran Stawki z zapisem do Wzorców.** Zapis komórek wiersza 14 jest wykonalny wzorem zapisu INTERMAX, ale
  ryzykuje jedyny egzemplarz Wzorca u taty, nie obejmuje mnożników ukrytych w formułach, a stawki zmieniają się
  rzadko. Stawki INEA to ceny INEA, te same co w efenix.
- **Usuwanie Wykonawcy.** Okres sprzed jego odejścia, rozliczany ponownie, zatrzymałby się na nieznanym
  Wykonawcy.
- **Edytowalny temat przypomnienia.** Odpowiedzi na przypomnienie przestałyby być Raportem wykonawcy.
- **Czekać z tym na Centrum w chmurze.** Tata dalej prosiłby Maksa o każdą zmianę przez całą migrację.
