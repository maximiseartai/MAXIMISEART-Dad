# Skille projektu

## Nowy albo zmieniony skill

- Skrypt mutacji skilla nazwij `scripts/check_<co>_mutations.py` i zostaw w nim tylko tabelę `Mutation` dla `check_all` z `tools/lib/silnik_mutacji.py`; CI uruchamia go sam przez `tools/ci/wykonaj_zadanie.py`.
  Człon `<co>` odróżnia go od skryptów innych skilli, bo mypy odrzuca dwa moduły o tej samej nazwie.
  Jego wywołanie w `SKILL.md` pilnuje, żeby nie wypadł z CI po zmianie nazwy albo usunięciu.
- Długą podstawę (`ci:`), której jednostki (funkcje, zakresy) biegną niezależnie albo po kolei od świeżego startu, podziel kluczem `ci-czesci: <n>` we frontmatterze.
  Plan CI uruchamia wtedy część k z `MUTACJE_CZESC=k/n`, a skrypt bierze swoje jednostki przez `part` z [`tools/lib/skrypt_skilla.py`](../../tools/lib/skrypt_skilla.py): kolejne kawałki w ich kolejności, każda jednostka raz.
  Każda część płaci swój start (serwer, przeglądarka), więc n dobierz symulatorem, a test skilla sprawdza, że części każdej liczby do n składają się na całość.
  Jednostka musi przejść zaraz po starcie części albo po każdej wcześniejszej jednostce, bo noc na `main` uruchamia każdą część każdej liczby do n (`LICZY NOC`), a pull request części jednej liczby, którą wybiera plan.
- Znane ustalenie skilla `verify-*` (`KNOWN_FINDINGS` eksploratora albo znane naruszenie modelu TLA+) wybacza jedną wąską przyczynę, a skrypt mutacji ma na nie dwie mutacje: usunięcie tylko tej przyczyny daje `ZNALEZISKO ZNIKNĘŁO` tylko dla niego, a ta sama szkoda z innej przyczyny `NOWE NARUSZENIE` (#1341, #1343, #1345).

## Redakcja prozy skilla `verify-*`

Skill `verify-*` to skill weryfikacji pstack (`/pstack:create-verification-skill`), a jego treść zmienia tylko przebieg utrzymania z dowodem ze źródła i biegu na żywo (`/pstack:maintain-verification-skill`).
Redakcja pod agenta (skill `writing-for-agents`) zmienia więc samą formę: każde zdanie o kodzie, środowisku albo biegu zostaje ze swoją treścią.

- Opis (`description`) mówi, co skill sprawdza, i daje jeden wyzwalacz na gałąź, bez listy ścieżek, bo kiedy skill obowiązuje, mówi jego `pilnuje:` przez `tools/skille_dla_zmiany.py`.
- Usuń zdanie, które powtarza inne zdanie skilla albo jego mapy, kod skryptu albo `--help`, i zdanie, które nie zmienia zachowania agenta.
  Zdanie z `Gotchas` zostaje, bo to wiedza, której agent nie znajdzie w kodzie.
- Nietknięte zostają: klucze frontmatteru poza `description`, nagłówki H2 szablonu mapy, sekcja `## Sub-features` (drukuje ją `scripts/sub_features.py`, a bieg porównuje ją z plikiem), polecenia, nazwy funkcji i nazwy testów.
- Skill, którego PR utrzymania jest otwarty (`tools/praca_w_toku.py`), czeka na jego merge.

## Cotygodniowe utrzymanie skilli weryfikacji

Zadanie T3 uruchamia raz w tygodniu `/pstack:maintain-verification-skill` dla dwóch skilli, które samo nazywa: skillu procesów (skrypt maszynowy `tools/uruchom_proces.py`) i skillu Centrum (napęd przeglądarki).
Ta sekcja mówi, czego skill pstack nie wie o tym repo.

- Pracuj we własnym worktree z `origin/main` (`git worktree add ~/.t3/worktrees/MAXIMISEART-Dad/utrzymanie-<data> origin/main`), a notatki przebiegu trzymaj w `~/.t3/notes/utrzymanie-skilli/<data>/`.
  Główny checkout i inne worktree należą do innych wątków.
- Skill procesów idzie pierwszy.
  Centrum uruchamia te same procesy (ADR 0010), więc dryf procesu znaleziony w nim tłumaczy porażkę Centrum, zanim weźmiesz ją za dryf ekranu.
- Przebieg na żywo skillu procesów: `run_verification.py --variant all` na boxie (skill [`boat`](../../.agents/skills/boat/SKILL.md)).
  Warianty z prawdziwymi Wzorcami biegną tylko na Macu, bo Wzorce z `config/` nie opuszczają Maca.
  Ich `VERIFY SKIP` to `verified-unreachable` z warunkiem „Wzorce w `config/`”.
- Przebieg na żywo skillu Centrum: na Macu, jeden bieg napędu naraz, bo procesor Maca dzielą wszystkie wątki; bieg innego wątku pokazuje `tools/quiet_machine.py --status` (`drive_centrum.py`), a wtedy czekasz na jego koniec.
  Sekcja `Real mailbox` w `wpisanie-raportow` wymaga zgody Maksa na każdy bieg, więc nie wchodzi do przebiegu.
  `wydajnosc` zostaje poza przebiegiem jako `verified-unreachable` z warunkiem „cichy procesor”.
- Dryf mapy w tym repo to także zdanie o tym, czego bieg nie sprawdza, bez nazwy testu, który to trzyma.
  Takie zdanie dostaje jedno zdanie z nazwą testu, które mówi dokładnie to, co test sprawdza, a gdy takiego testu nie ma, zostaje i opis PR wymienia je jako brak.
- Wynik `changed` to jeden PR dla obu skilli (commit na skill), a jego opis nie wskazuje issue, bo przebieg nie ma ticketu.
  Właścicielem tego PR jest agent zadania: linię wyniku pisze dopiero po merge'u.
  PR, który do merge'a nie doszedł, blokuje każdy skill, którego commit w nim stoi, a powodem tego skillu jest PR bez merge'a.
- Błąd produktu znaleziony w przebiegu opisz w końcowej odpowiedzi nad linią wyniku: co, gdzie w kodzie i jak go odtworzyć.
  Ticket z niego zakłada Maks.
- Ostatnia linia odpowiedzi to `<mapy> | produkt: <stan>`.
  `<mapy>` to `clean`, `changed <URL PR>`, `blocked <skill>: <powód>` (przy obu skillach `blocked <skill procesów>: <powód>; <skill Centrum>: <powód>`) albo `blocked <skill>: <powód>, changed <URL PR>`, gdy jeden skill zablokował, a PR drugiego wszedł.
  `<stan>` to `brak` albo jedno zdanie o błędzie produktu opisanym wyżej.

## Co wyrocznia bierze z `src`

- Wyrocznia skilla (skrypt `verify-*`, eksplorator, narzędzie w `tools/`) bierze z `src` mechanikę wewnętrzną tylko przez publiczny punkt obserwacji: publiczną nazwę modułu, metodę stanu (`Outbox.state`, `KeyedBox.state`) albo szew konstruktora (`QueueDisk`, `start`, `CentrumLog(append=…)`, `intermax_replace.Disk`).
  Mechanika to stan w pamięci, przerwy ponowień, ścieżki modułów, miejsca w dzienniku Centrum i kroki, w których wyrocznia wstrzykuje awarię.
  Prywatna nazwa (`moduł._x`), `vars(moduł)` i podmiana globali modułu wiążą wyrocznię z wnętrzem, które autor zmienia bez patrzenia na skille, a wyrocznia, która je podmienia, po takiej zmianie po cichu przestaje wstrzykiwać awarię.
- Dane o świecie zewnętrznym i oczekiwane wyniki wyrocznia kopiuje celowo: tekst Komunikatu, który tata czyta, dopisek w Skrzynce Zgłoszeń, który czyta Maks, nazwę pliku w folderze taty (Kopia INTERMAX, Wzorce), nagłówki plików taty i format, który czyta następne Wydanie (nazwa pliku kolejki, znacznik wysyłki).
  Tak samo kopiuje to, co tworzy świat zewnętrzny (blokada `~$` Excela), także gdy skrypt sam to tworzy, grając Excela albo tatę: generator świata bierze z `src` tylko to, czego tata nie widzi, czego nie czyta inna wersja narzędzia z plików taty i czego nie tworzy świat.
  Nazwy plików i folderów narzędzia u taty (`config/`, Ustawienia, dziennik, Logi, kolejka, pliki stanu, wynik Aktualizacji) mają jedną kopię, w `tools/lib/atrapy/pliki_taty.py`.
  Taką nazwę skrypt bierze z `src` tylko w trzech przypadkach.
  (a) Sprawdzenie, że pliku nie ma, na przykład czekanie, aż plik zniknie z kolejki: na kopii przeszłoby po cichu, gdy `src` zmieni nazwę, bo pod starą nazwą pliku nie ma od początku.
  (b) Ścieżka, którą harness sam wybiera i podaje produktowi jako parametr (Ustawienia, dziennik i konfiguracja serwera w `fixture.json`, folder Wzorców, adres przekierowany na repozytorium próbne).
  (c) Współrzędne i nazwy w sprawdzeniu, które czyta plik zbudowany przez atrapę z kopią: zła stała w `src` nie trafia w ten plik, więc odczyt pada.
  Wyrocznia, która importuje sprawdzany kod, nie wykryje jego błędu: zmieniony w `src` tekst albo format przeszedłby z nim razem.
  Kopię, która wygląda na mechanikę, trzymaj w stałej nazwanej tym, co kopiuje ze świata zewnętrznego, jak nazwy plików taty w `tools/lib/atrapy/pliki_taty.py`, a nie w komentarzu z powodem ([ADR 0043](../adr/0043-kod-bez-komentarzy.md)).

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Zdanie skilla `verify-*` o kodzie, środowisku albo modelu (uprawnienie, plik ignorowany przez Git, straż w modelu TLA+) stoi na przebiegu, który mógł je obalić (bez uprawnienia, na tym pliku, bez tej straży), straż modelu ma odpowiednik w kodzie, a zdanie, którego nie dało się obalić, skill nazywa niesprawdzonym. | nic: decyduje osąd (werdykty FAIL #370, #376 i #378 z 2026-10-24) |
| Każdy wpis krotek `ACCEPTED_RISKS` i `KNOWN_FINDINGS` eksploratora skilla `verify-*` to `Excuse` z [`tools/lib/eksplorator.py`](../../tools/lib/eksplorator.py) z jawnym kształtem, a w `BOUNDARIES` skryptu mutacji skilla ma mutację tuż za granicą każdej części kształtu, która coś zawęża. | `tests/test_mutacje_skilli.py::test_kazde_przyjete_ryzyko_i_znane_ustalenie_eksploratora_ma_mutacje_tuz_za_granica_kazdej_czesci_ksztaltu` i `::test_straznik_granic_czerwieni_wpis_bez_jawnego_ksztaltu_albo_czesc_bez_mutacji_tuz_za_granica` (granica: docstring pierwszego) |
| Wyrocznia skilla i narzędzie w `tools/` biorą z `src` tylko publiczne nazwy, a dane o świecie zewnętrznym kopiują celowo (sekcja wyżej). | `tests/test_granice_importow.py::test_wyrocznie_skilli_i_narzedzia_biora_z_src_tylko_publiczne_nazwy` (granica: docstring `_private_reaches`) |
