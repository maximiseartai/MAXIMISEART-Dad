# ADR 0011: Bez CLI i adapterów terminala; skrypt dla maszyn przez rdzeń Uruchomienia procesu

## Status

Zaakceptowana. Zastępuje [ADR 0003](0003-cli-only-launcher.md): procesy nie
mają już CLI. Rezygnacja z adaptera VBA z ADR 0003 pozostaje w mocy. Zmienia:

- [ADR 0002](0002-progress-event-observation.md): adaptery plain i Rich
  znikają, a jedynym podglądem postępu zostaje Centrum rozliczeń. Zdarzenia
  przebiegu i jedna projekcja postępu zostają. Projekcja zwraca sam snapshot,
  bez zdarzenia, i traci fakty, które czytał tylko terminal.
- [ADR 0004](0004-centrum-rozliczen-adapter.md): Komunikat nie ma już linii
  terminala (`terminal_line`), a rdzeń Uruchomienia procesu nie ma wejścia CLI.
- [ADR 0006](0006-uklad-folderow-taty-i-wspolne-ustawienia.md): Ustawienia
  taty czyta tylko Centrum.
- [ADR 0010](0010-centrum-jedynym-wejsciem-taty.md): CLI nie zostaje jako
  narzędzie osoby utrzymującej.

[ADR 0032](0032-ustawienia-centrum-zmienia-tata.md) włącza Rejestr zleceń
i folder okresów do Ustawień Centrum.

## Kontekst

Od ADR 0010 tata pracuje tylko w Centrum rozliczeń. CLI obu procesów zostało
dla weryfikacji end-to-end, straży czasu i benchmarku Przebiegu rozliczeń.
Płaciliśmy za to drugą rozmową z tatą, której nikt nie prowadził: pulpitem
postępu Rich i adapterem tekstowym, pytaniami `t`/`n`, oknami wyboru, pytaniem
o okres, jednolinijkową wersją każdego Komunikatu i siedmioma fabrykami
Komunikatów osiągalnymi tylko z terminala. E2E i benchmark sprawdzały linie terminala,
których tata nie widzi.

## Decyzja

- **Jedna rozmowa z tatą.** CLI Przebiegu rozliczeń i Przygotowania pliku
  zbiorczego, rozmowa w terminalu, adaptery postępu i wzorcowe wyjście
  terminala znikają. Rdzeń Uruchomienia procesu przyjmuje zawsze gotowe wejście
  procesu.
- **Skrypt dla maszyn.** Jedynym wejściem spoza Centrum jest
  `tools/uruchom_proces.py`. Uruchamia jeden proces przez ten sam rdzeń co
  Centrum, odrzuca każdą Decyzję taty, nie pokazuje postępu i wypisuje wynik
  jako JSON w kształcie kontraktu Centrum. Nie czyta Ustawień taty i nie
  otwiera okien wyboru. Stoją na nim E2E, straż czasu, benchmark i test Metryk
  w weryfikacji Centrum.
- **Komunikat ma jeden kształt.** Trzy części: co się stało, gdzie, co zrobić.
  Katalogi tracą siedem fabryk Komunikatów, które wołał tylko terminal.
  Przygotowanie pliku zbiorczego traci trzy: niewybrany Rejestr zleceń
  (`NIE_WYBRANO_REJESTRU`), niewybrany folder okresów
  (`NIE_WYBRANO_FOLDERU_OKRESOW`) i niepodany okres (`NIE_PODANO_OKRESU`).
  Przebieg rozliczeń traci cztery: niewybrany Plik zbiorczy
  (`NIE_WYBRANO_PLIKU_ZBIORCZEGO`), niepodany okres (`NIE_PODANO_OKRESU`),
  Folder okresu, którego nie ma albo który jest w kilku folderach miesiąca
  (`BRAK_FOLDERU_OKRESU`, `POWTORZONY_FOLDER_OKRESU`), i zły token okresu
  (`ZLY_TOKEN_OKRESU`). Zły token okresu w Przygotowaniu zostaje, bo zgłasza go
  silnik.
- **Historia bez zmian.** Pochodzenie `.cmd` zostaje w kontrakcie i na
  odznace. Oznacza stare Uruchomienia z dawnych launcherów i z CLI.

## Uzasadnienie

Skrypt sprawdza te same liczby, etykiety i Komunikaty, które pokazuje karta
Uruchomienia, więc zielone E2E mówi coś o tym, co zobaczy tata. Każda zmiana
procesu przechodzi przez jedną rozmowę zamiast dwóch. Skrypt nie trafia do
pakietu `rozliczenia`, bo nie jest wejściem taty.

## Konsekwencje

- Instalacja u taty nie potrzebuje biblioteki `rich`. `tkinter` zostaje, bo
  Centrum otwiera nim własne okna wyboru.
- Wyniki referencyjne benchmarku zapisane przed skryptem trzeba zamrozić od
  nowa na każdej maszynie pomiarowej.
- Rekord metryk spoza Centrum, np. ze skryptu, nadal ma w Historii odznakę
  `.cmd`. U taty takie rekordy już nie powstają, więc odznaka zostaje przy
  jego starych Uruchomieniach.
