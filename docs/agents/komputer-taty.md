# Komputer taty

Środowisko, w którym naprawdę działa narzędzie i Centrum rozliczeń. Pomiar
wydajności albo decyzja zależna od sprzętu czy OneDrive odnosi się do tego
komputera, a nie do komputera dewelopera.

## Sprzęt i system

- Laptop z Windows, 64-bitowy, x64.
- Procesor Intel Core i7-10875H (2,3 GHz, 8 rdzeni / 16 wątków, generacja z 2020 r.).
- 32 GB RAM.
- Grafika NVIDIA GeForce RTX 2060 Max-Q (6 GB) oraz zintegrowana Intel UHD.
- Dysk 954 GB, zajęte 811 GB (około 85%).
- Ekran dotykowy (10 punktów). Tata może klikać Centrum palcem.
- Monitor 27 cali (stan z 26.10.2026); rozdzielczości i skalowania Windows nikt nie sprawdził.
- Python 3.13.15 (stan z 13.11.2026). To najstarszy Python z `requires-python`, więc bramka PR testuje
  Windows z Pythonem 3.13 ([ADR 0020](../adr/0020-ci-w-poziomach.md)).

## Gdzie leżą pliki

- Narzędzie, w tym Centrum, `config/` i pliki metryk, leży lokalnie na dysku `C:`.
- Folder okresów, Rejestr zleceń, Pliki zbiorcze i rozliczenia pracowników leżą
  w OneDrive. Odczyt może trafić na plik „tylko online”, który OneDrive najpierw
  pobiera. Czas odpowiedzi API, które czyta folder okresów (Tablica okresów,
  Uruchomienia), zależy więc od OneDrive, a nie tylko od dysku.
- OneDrive taty jest poza zasięgiem Maksa i serwera, także przez Microsoft Graph
  ([#1154](https://github.com/maximiseartai/MAXIMISEART-Dad/issues/1154)), więc
  pracę taty na prawdziwych plikach pokazują tylko Logi Uruchomienia w Archiwum
  Logów okresu.

## Profil do pomiarów wydajności

- Frontend wykonuje JS w jednym wątku, więc liczy się wydajność jednego rdzenia.
  i7-10875H jest w niej około 3× wolniejszy od Apple M4 Max. To szacunek
  z publicznych benchmarków, nie pomiar.
- Na Macu z M4 Max odwzoruj komputer taty przez spowolnienie CPU w Chromium
  (`Emulation.setCPUThrottlingRate`): 4× to profil odniesienia, 6× to profil
  pesymistyczny (laptop na baterii, oszczędzanie energii w Windows). Na innym
  komputerze deweloperskim przelicz mnożnik według wydajności jednego rdzenia.
- Pomiar lokalny nie pokazuje opóźnień OneDrive. Czasy serwera u taty trzeba
  zmierzyć na jego komputerze.
- Szybkość procesu w Pythonie u taty szacuj z A/B na `windows-latest`: gałąź
  próbna z workflow uruchamianym pushem mierzy `main` i zmianę na przemian w
  jednym runie, a czas u taty to czas z jego Logów razy stosunek zmiana/`main`
  (#1055, #1111).
