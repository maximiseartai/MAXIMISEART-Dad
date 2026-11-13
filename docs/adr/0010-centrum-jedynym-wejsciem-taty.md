# ADR 0010: Centrum rozliczeń jedynym wejściem taty, bez launcherów `.cmd`

## Status

Zaakceptowana. To decyzja, którą [ADR 0004](0004-centrum-rozliczen-adapter.md)
odłożył „do czasu, aż Centrum przejmie całą pracę taty”. Zmienia:

- [ADR 0003](0003-cli-only-launcher.md): procesy nie mają już launcherów `.cmd`.
- ADR 0004: Centrum nie jest drugim wejściem obok launcherów, tylko jedynym
  wejściem taty; launchery nie są ścieżką zapasową.
- [ADR 0006](0006-uklad-folderow-taty-i-wspolne-ustawienia.md): Ustawienia taty
  czyta CLI, nie launchery.
- [ADR 0009](0009-aktualizacja-narzedzia-z-centrum.md): zdanie „launchery
  `.cmd` bez zmian” przestaje obowiązywać.

[ADR 0011](0011-bez-cli-i-adapterow-terminala.md) zmienia punkt „CLI zostaje
jako narzędzie osoby utrzymującej”: CLI znika, a E2E, straż czasu i benchmark
uruchamiają procesy skryptem dla maszyn przez rdzeń Uruchomienia procesu.
[ADR 0032](0032-ustawienia-centrum-zmienia-tata.md) włącza Rejestr zleceń
i folder okresów do Ustawień Centrum.

## Kontekst

Centrum rozliczeń robi wszystko, co tata robił launcherami: uruchamia oba
procesy z podglądem bez zapisu, proponuje okres i daje wybrać inny, pyta o
niepełny okres przyciskiem, pamięta Rejestr zleceń i folder okresów, a przy
Zatrzymaniu ma Diagnozę i Zgłoszenie do Maksa. CLI umie poza tym przyjąć Plik
zbiorczy spoza Folderu okresu i nadpisać ścieżki wzorców, konfiguracji i metryk
parametrami. Tata z tego nie korzysta: od ADR 0006 jego pliki zawsze leżą w
Folderach okresu.

Dwa wejścia kosztują tatę i Maksa. Instrukcja taty opisuje każdy proces dwa
razy, a jej tabele komunikatów mieszają przyciski Centrum z `Status końcowy`,
`t`/`n` i oknami wyboru z terminala. Każda zmiana procesu wymaga sprawdzenia
obu rozmów.

## Decyzja

- **Tata pracuje tylko w Centrum rozliczeń.** Znikają `Utwórz rozliczenia.cmd`,
  `Przygotuj plik zbiorczy.cmd`, `Centrum rozliczeń (konsola).cmd` i
  `Zainstaluj skrót Centrum rozliczeń.cmd`. Instrukcja taty opisuje wyłącznie
  Centrum.
- **Skrót instaluje osoba utrzymująca narzędzie.** Pierwsza instalacja ma już
  polecenie `py -3 -m pip install -r requirements.txt` w terminalu; obok niego
  staje `py -3 install_centrum_shortcut.py`. Centrum z konsolą to
  `py -3 run_centrum.py`.
- **CLI zostaje jako narzędzie osoby utrzymującej.** `run.py` i
  `run_preparation.py` z rdzeniem rozmowy terminala obsługują E2E w CI, pomiar
  czasu i benchmarki. Nie są wejściem taty, więc Komunikaty widoczne tylko w
  terminalu (okna wyboru, wpisany okres) nie mają wierszy w instrukcji taty.
  Usunięcie CLI i adapterów terminala to osobna decyzja.
- **Bez ścieżki zapasowej.** Komunikat startu Centrum nie odsyła już do
  launcherów. Gdy Centrum nie wystartuje, tata przekazuje Komunikat osobie
  utrzymującej narzędzie.
- **Historia bez zmian.** Dziennik pochodzenia Uruchomień i odznaka `.cmd`
  zostają: oznaczają Uruchomienia z dawnych launcherów i z CLI.

## Uzasadnienie

Jedno wejście to jedna instrukcja i jedna rozmowa do utrzymania po stronie taty.
Ścieżka zapasowa miała sens, póki Centrum było nowe. Dziś Centrum ma własne
Komunikaty startu, Diagnozę i Zgłoszenia, a Aktualizacja narzędzia z ADR 0009
ma cofać wersję, która nie startuje. Launcher, który tata uruchomiłby raz na
kilka miesięcy, nie jest wart drugiego opisu każdego procesu.

CLI zostaje, bo opierają się na nim weryfikacja end-to-end, bramka czasu w CI
i benchmarki na prawdziwych plikach. Przeniesienie ich na rdzeń Uruchomienia
procesu bez terminala to osobna praca. Nie musi blokować uproszczenia pracy
taty.

## Konsekwencje

- Testy uruchamiające launchery przez `cmd.exe` znikają. Start Centrum z
  konsolą i instalację skrótu testy uruchamiają przez Pythona.
- Gdy Centrum nie wystartuje, tata nie ma czym uruchomić procesu do czasu
  pomocy Maksa. Ryzyko ograniczy Aktualizacja narzędzia z ADR 0009: nowa
  wersja, która nie startuje, sama się cofa.
- Komunikat startu `Brakuje biblioteki` nadal każe uruchomić
  `py -3 -m pip install -r requirements.txt`. Po wejściu Aktualizacji narzędzia,
  która instaluje biblioteki sama, ten Komunikat dotyczy tylko zepsutej
  instalacji.
- Zmiany CLI nie wymagają zmian instrukcji taty. Zmiana Komunikatu, który widać
  w Centrum, nadal wymaga.
