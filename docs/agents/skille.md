# Skille projektu

## Nowy albo zmieniony skill

- Skrypt mutacji skilla nazwij `scripts/check_<co>_mutations.py` i zostaw w nim tylko tabelę `Mutation` dla `check_all` z `tools/lib/silnik_mutacji.py`; CI uruchamia go sam przez `tools/ci/wykonaj_zadanie.py`.
  Człon `<co>` odróżnia go od skryptów innych skilli, bo mypy odrzuca dwa moduły o tej samej nazwie.
  Jego wywołanie w `SKILL.md` pilnuje, żeby nie wypadł z CI po zmianie nazwy albo usunięciu.
- Długą podstawę (`ci:`), której jednostki (funkcje, zakresy) biegną niezależnie albo po kolei od świeżego startu, podziel kluczem `ci-czesci: <n>` we frontmatterze.
  Plan CI uruchamia wtedy część k z `MUTACJE_CZESC=k/n`, a skrypt bierze swoje jednostki przez `part` z [`tools/lib/skrypt_skilla.py`](../../tools/lib/skrypt_skilla.py): kolejne kawałki w ich kolejności, każda jednostka raz.
  Każda część płaci swój start (serwer, przeglądarka), więc n dobierz symulatorem, a test skilla sprawdza, że części każdej liczby do n składają się na całość.
  Jednostka musi przejść zaraz po starcie części albo po każdej wcześniejszej jednostce, bo noc na `main` uruchamia każdą część każdej liczby do n (`LICZY NOC`), a pull request części jednej liczby, którą wybiera plan.

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
  Kopię, która wygląda na mechanikę, opatrz komentarzem z powodem i odsyłaczem do tej sekcji.

## Reguły i co ich pilnuje

| Reguła | Co jej pilnuje |
|---|---|
| Zdanie skilla `verify-*` o kodzie, środowisku albo modelu (uprawnienie, plik ignorowany przez Git, straż w modelu TLA+) stoi na przebiegu, który mógł je obalić (bez uprawnienia, na tym pliku, bez tej straży), straż modelu ma odpowiednik w kodzie, a zdanie, którego nie dało się obalić, skill nazywa niesprawdzonym. | nic: decyduje osąd (werdykty FAIL #370, #376 i #378 z 2026-10-24) |
| Każdy wpis krotek `ACCEPTED_RISKS` i `KNOWN_FINDINGS` eksploratora skilla `verify-*` to `Excuse` z [`tools/lib/eksplorator.py`](../../tools/lib/eksplorator.py) z jawnym kształtem, a w `BOUNDARIES` skryptu mutacji skilla ma mutację tuż za granicą każdej części kształtu, która coś zawęża. | `tests/test_mutacje_skilli.py::test_kazde_przyjete_ryzyko_i_znane_ustalenie_eksploratora_ma_mutacje_tuz_za_granica_kazdej_czesci_ksztaltu` i `::test_straznik_granic_czerwieni_wpis_bez_jawnego_ksztaltu_albo_czesc_bez_mutacji_tuz_za_granica` (granica: docstring pierwszego) |
| Wyrocznia skilla i narzędzie w `tools/` biorą z `src` tylko publiczne nazwy, a dane o świecie zewnętrznym kopiują celowo (sekcja wyżej). | `tests/test_granice_importow.py::test_wyrocznie_skilli_i_narzedzia_biora_z_src_tylko_publiczne_nazwy` (granica: docstring `_private_reaches`) |
