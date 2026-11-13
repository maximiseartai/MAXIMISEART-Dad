# ADR 0009: Aktualizacja narzędzia z Centrum rozliczeń

## Status

Zaakceptowana. Zmienia trzy zdania
[ADR 0004](0004-centrum-rozliczen-adapter.md) i trzy
[ADR 0007](0007-zgloszenia-do-maksa-w-prywatnym-repo.md):

- ADR 0004 „Pliki i foldery otwiera tylko wtedy, gdy sam wyliczył je z folderu
  okresów”: dochodzi jeden wyjątek, katalog samego narzędzia, który Centrum
  zmienia wyłącznie przez Aktualizację narzędzia.
- ADR 0004 „Centrum … nie [jest] osobnym procesem”: Centrum dalej nie ma
  własnych reguł rozliczeń. Aktualizacja narzędzia nie jest procesem z
  [GLOSSARY](../../GLOSSARY.md), tylko czynnością utrzymaniową, jak
  `Zamknij Centrum rozliczeń`.
- ADR 0004 „Nie ma … zdalnego dostępu”: Centrum nadal nie przyjmuje połączeń
  spoza komputera taty.
- ADR 0007 „Centrum łączy się wyłącznie z API GitHuba”: dochodzi pobranie
  `main` publicznego repozytorium narzędzia z `github.com` przez Git, tylko po
  kliknięciu taty.
- ADR 0007 „Centrum łączy się wyłącznie z API GitHuba: … przy sprawdzeniu
  aktualności narzędzia w Diagnozie”: dochodzi sprawdzenie Aktualności narzędzia
  na stronie Konfiguracja. Konfiguracja pamięta odpowiedź `main` przez 10
  minut, a brak odpowiedzi przez minutę (limit API bez logowania, czekanie bez
  sieci); Diagnoza dalej pyta przy każdym sprawdzeniu.
- ADR 0007, kolejność wyjaśnień Diagnozy: Aktualność narzędzia przestaje
  wygrywać z przyczyną znalezioną przez inne sprawdzenie (niżej).

Pozostałe zasady (tylko `127.0.0.1`, kontrola `Host` i `Origin`, reguła
prywatności, launchery `.cmd` bez zmian) zostają. Launchery `.cmd` usunął
potem [ADR 0010](0010-centrum-jedynym-wejsciem-taty.md).
Wersję, na którą Centrum przesuwa klon i z którą porównuje Aktualność
narzędzia, zmienia [ADR 0014](0014-tata-dostaje-tylko-wydania.md): najnowsze
Wydanie zamiast `main`.
[ADR 0015](0015-logi-uruchomienia-uwagi-taty-i-powiadomienia.md) zastępuje
Powiadomienie o naprawie z Kontekstu Powiadomieniem o nowej wersji.
[ADR 0032](0032-ustawienia-centrum-zmienia-tata.md) włącza Rejestr zleceń
i folder okresów do Ustawień Centrum, a stary plik Wykonawców
(`worker_mapping.yaml`) zastępuje Lista Wykonawców (`wykonawcy.yaml`).

## Kontekst

Diagnoza i Powiadomienie o naprawie każą tacie „Zaktualizuj narzędzie”, ale
nigdzie nie ma, jak to zrobić. U taty jest Git for Windows, niekoniecznie w
`PATH`; narzędzie to klon publicznego repozytorium, a Centrum odczytuje commit
narzędzia z plików `.git` (`version.tool_commit`). Pierwszy zwykły `git pull`
po #161 usuwa `config/worker_mapping.yaml`, bo repozytorium przestało go
śledzić. Ręczną procedurę zna tylko Maks (README).

## Decyzja

Tata aktualizuje narzędzie przyciskiem `Zaktualizuj narzędzie` w Centrum
rozliczeń. Centrum robi to samo, co Maks zrobiłby ręcznie, i niczego więcej:

- **Git for Windows.** Centrum szuka `git.exe` w `PATH` i w znanych miejscach
  instalacji Git for Windows. Pobiera `main` z publicznego repozytorium bez
  logowania i przesuwa klon tylko do przodu (fast-forward). Lokalne commity,
  inna gałąź albo zmienione śledzone pliki zatrzymują Aktualizację narzędzia z
  Komunikatem „przekaż Maksowi” i niczego nie zmieniają.
- **Pliki taty zostają.** Plik w `config/`, który nowa wersja przestaje śledzić
  albo usuwa, a który tata ma u siebie (dziś `worker_mapping.yaml`), Centrum
  zachowuje i przywraca po przesunięciu klonu. Wzorce, Ustawienia taty, klucz
  do Zgłoszeń, dziennik, metryki i pliki okresów nie są dotykane.
- **Biblioteki.** Gdy nowa wersja zmienia `requirements.txt`, Centrum instaluje
  je tym samym Pythonem, w którym działa.
- **Wszystko albo nic.** Porażka po przesunięciu klonu (instalacja bibliotek,
  przywracanie plików taty) cofa klon do commitu sprzed Aktualizacji
  narzędzia. Tata zostaje z wersją, która działała.

  Zanim Aktualizacja narzędzia zmieni klon, zapisuje dziennik „Aktualizacja w
  toku” w `config/centrum-aktualizacja-w-toku/`: commit przed i po oraz kopię
  plików taty. Ta nazwa jest zarezerwowana i ignorowana przez Gita. Dziennik
  znika dopiero przy wyniku ostatecznym. Gdy komputer zgaśnie w trakcie, skrót
  przy następnym starcie, zanim wczyta biblioteki, cofa z dziennika klon i
  pliki taty, a potem startuje poprzednią wersję. Nie cofa, dopóki opiekun
  ponownego startu może jeszcze działać (10 minut od jego startu). Gdy
  cofnięcie w działającym Centrum się nie uda, następne kliknięcie
  `Zaktualizuj narzędzie` najpierw cofa klon z dziennika, a potem aktualizuje
  jak zwykle.
- **Ponowne uruchomienie.** Po udanej Aktualizacji narzędzia Centrum zamyka się
  i startuje od nowa w nowej wersji, a karta przeglądarki sama łączy się z nim
  ponownie. Opiekun ponownego startu działa z kopii sprzed Aktualizacji
  narzędzia, tylko na bibliotece standardowej: gdy nowa wersja nie wystartuje,
  cofa klon i uruchamia starą.
- **Nie w trakcie pracy.** Aktualizacja narzędzia jest odrzucona, gdy trwa
  Uruchomienie procesu, tak jak `Zamknij Centrum rozliczeń`.
- **Ślad.** Dziennik Centrum zapisuje start, wynik i oba commity, bez ścieżek.
- **Diagnoza nie przykrywa przyczyny.** Nowsza wersja narzędzia jest
  wyjaśnieniem Diagnozy tylko wtedy, gdy żadne inne sprawdzenie nie znalazło
  przyczyny; inaczej Diagnoza wyjaśnia przyczynę i proponuje Aktualizację
  narzędzia obok. `main` zmienia się kilka razy dziennie, więc „jest nowsza
  wersja” jest prawie zawsze prawdą i prawie nigdy przyczyną.

## Odrzucone warianty

- Pobranie archiwum `main` bez Gita: Centrum traci commit narzędzia, od
  którego zależą Diagnoza, Zgłoszenia i Powiadomienie o naprawie, a
  nadpisanie plików w miejscu nie ma kroku „wszystko albo nic”.
- Launcher `Zaktualizuj narzędzie.cmd`: tata i tak dostaje polecenie
  aktualizacji w Centrum, więc przycisk jest tam, gdzie pada prośba. Launcher
  nie cofa się po nieudanym starcie nowej wersji.
- Aktualizacja automatyczna przy starcie: `main` zmienia się kilka razy
  dziennie; tata nie powinien dostawać nowej wersji w środku tygodnia
  rozliczeń bez kliknięcia.
- Aktualizacja zdalnie przez Maksa: wymaga dostępu do komputera taty i
  opóźnia każdą naprawę.
