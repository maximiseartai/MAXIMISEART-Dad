# ADR 0006: Układ folderów taty i Ustawienia taty wspólne z launcherami

## Status

Zaakceptowana. Zmienia jedno zdanie [ADR 0004](0004-centrum-rozliczen-adapter.md):
launchery `.cmd` i CLI nie zostają bez zmian, tylko czytają Ustawienia taty z
Centrum rozliczeń. Same launchery zostają jako ścieżka zapasowa.
[ADR 0010](0010-centrum-jedynym-wejsciem-taty.md) usuwa launchery; Ustawienia
taty czyta dalej CLI. [ADR 0011](0011-bez-cli-i-adapterow-terminala.md) usuwa
CLI: Ustawienia taty czyta tylko Centrum rozliczeń.
Zmieniona 2026-11-07: skoro czyta je tylko Centrum, plik Ustawień taty należy
do modułu `rozliczenia.centrum.settings`. Od #1467 (2026-11-13) jego nazwę zna
tylko ten pakiet (`SETTINGS_FILE`), razem z Historią Ustawień i pamięcią
właściciela, a `rozliczenia.tool_files` daje tylko folder `config`.

[ADR 0032](0032-ustawienia-centrum-zmienia-tata.md) włącza Ustawienia taty do Ustawień Centrum, a folder okresów zapisuje
zawsze od folderu, od którego liczy się układ folderów taty. Od #1472 (2026-11-13) wybór tygodnia, `INEA` albo
miesiąca zapisuje `Załączniki`, a zapis sprzed tej zmiany zamienia raz zmiana z Wydania
`2026-11-folder-okresow-od-zalacznikow`, którą tata może cofnąć w Historii Ustawień.

## Kontekst

Pierwsze uruchomienie na komputerze taty pokazało, że narzędzie zakładało inny
układ folderów niż ten, w którym tata pracuje. Narzędzie oczekiwało jednego
folderu okresów z Folderami okresu bezpośrednio w nim (`INEA\08_14_09_2026`).
U taty tygodnie leżą w OneDrive w
`Załączniki\Rozliczenia {rok}\{miesiąc}\INEA\{okres}`, a folder `INEA` jest
osobny w każdym miesiącu. Centrum widziało więc co najwyżej jeden miesiąc i nie
znalazło wypełnionego Pliku zbiorczego okresu `06_12_10_2026`.

Lista folderów z lat 2025–2026 pokazała jeszcze dwie rzeczy:

- Wszystkie tygodnie z przełomu miesięcy tata nazywa miesiącem i rokiem
  poniedziałku (`29_05_10_2026`, `27_02_11_2026`, `30_05_01_2026`). Narzędzie
  brało miesiąc wtorku, więc utworzyłoby `29_05_09_2026` obok folderu taty.
- Folder miesiąca to cykl rozliczeniowy, nie kalendarz:
  `04_Kwiecień_2026\INEA` ma `24_30_03_2026`, a `01_Styczeń_2026\INEA` ma
  `23_29_12_2025`. Z daty okresu nie da się wyliczyć jego miesiąca.

Launchery `.cmd` przy każdym uruchomieniu pytały oknem wyboru o Rejestr zleceń
i folder okresów, choć tata wskazał je już w Centrum rozliczeń.

## Decyzja

1. **Token okresu ma miesiąc i rok poniedziałku.** Zapis z miesiącem wtorku jest
   odrzucany jako zły token, więc każdy okres nadal ma jeden token.
2. **Folder okresów ma dwa układy.** W płaskim Foldery okresu leżą w nim
   bezpośrednio, a brakujący Folder okresu powstaje przy zapisie, jak dotąd. Gdy
   folder okresów ma foldery `Rozliczenia {rok}`, Folder okresu jest **szukany**
   w `Rozliczenia {rok}\{miesiąc}\INEA` każdego roku i miesiąca. Tata wskazuje
   wtedy `Załączniki`.
   Folder okresów wskazany wewnątrz `Rozliczenia {rok}` (np. `INEA` jednego
   miesiąca) to ten sam układ liczony od folderu nad `Rozliczenia {rok}`, więc
   brakujący Folder okresu nie powstaje w miesiącu, który akurat wskazano.
3. **Folder okresu zakłada tata.** W układzie folderów taty brak Folderu
   okresu zatrzymuje proces komunikatem „Załóż folder … w folderze INEA
   właściwego miesiąca”. Ten sam okres w dwóch miesiącach też zatrzymuje proces
   i pokazuje oba miejsca. Narzędzie nie zgaduje miesiąca. Tablica okresów
   pokazuje taki okres raz i nie zatrzymuje się; zatrzymuje dopiero akcja, która
   potrzebuje jednego Folderu okresu.
4. **Ustawienia taty są wspólne.** Plik `config/centrum-ustawienia.yaml` należy
   do modułu `rozliczenia.settings`, a nie do Centrum (zmienione 2026-11-07,
   patrz Status). Launchery biorą z niego
   Rejestr zleceń i folder okresów, jeśli nadal są na dysku. Okno wyboru
   pokazują tylko dla tego, czego brak. Argumenty CLI mają pierwszeństwo przed
   ustawieniami. Przebieg rozliczeń z ustawionym folderem okresów pyta o okres z
   propozycją, tak jak Przygotowanie pliku zbiorczego, zamiast pytać oknem o Plik
   zbiorczy.

## Uzasadnienie

Narzędzie ma pracować w folderach taty, a nie wymagać ich przebudowy. Zasady
miesiąca rozliczeniowego zna tylko tata i już dziś zakłada foldery tygodni z
wyprzedzeniem, więc szukanie zamiast wyliczania nie dokłada mu pracy. Zgadywanie
miesiąca zapisałoby pliki tam, gdzie tata ich nie szuka. Zatrzymanie z
komunikatem jest bezpieczne, bo nic nie powstaje.

Układ płaski zostaje, bo działa w testach, weryfikacjach i dotychczasowej
instrukcji, a nie koliduje z układem taty: decyduje sama obecność folderów
`Rozliczenia {rok}`.

Ustawienia wskazane w Centrum to ta sama wiedza, której potrzebują launchery.
Drugi plik konfiguracji albo ścieżki wpisane w kodzie rozjechałyby się z Centrum.
Ścieżki w kodzie trafiłyby też do publicznego repozytorium razem z nazwą konta
Windows.

## Konsekwencje

- W układzie folderów taty Folder okresu zawsze istnieje przed zapisem, więc
  pliki okresu trafiają do niego dwoma przeniesieniami. Ryzyko z
  [ADR 0005](0005-przerwana-publikacja-plikow-okresu.md) (samo Rozliczenie
  wewnętrzne po procesie zamkniętym między dwoma przeniesieniami albo po
  nieudanym drugim, zanim wycofanie usunęło pierwszy plik) dotyczy tam każdego
  zapisu. Nadal jest
  wykrywane przez Nienadpisywanie.
- Puste pliki okresu przygotowane z góry blokują Przygotowanie pliku zbiorczego
  (Nienadpisywanie). Tata zakłada z góry tylko foldery tygodni, a pliki tworzy
  narzędzie.
- Testy CLI nie czytają Ustawień taty z katalogu narzędzia; test, który ich
  potrzebuje, podaje je sam.
