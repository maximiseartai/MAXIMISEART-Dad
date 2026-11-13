# ADR 0018: Ilości tylko dla INEA nie przechodzą do Rozliczenia pracownika

## Status

Zaakceptowana. Dopełnia [ADR 0012](0012-ilosci-uslug-w-przygotowaniu-pliku-zbiorczego.md):
Ilości usług w Pliku zbiorczym to to, co INEA płaci tacie, a Rozliczenie
pracownika przestaje być wierną kopią Pliku zbiorczego w kolumnach `N:AP`.

[ADR 0033](0033-reguly-ilosci-naleza-do-taty.md) zmienia punkt „Zasada należy do taty, a utrzymuje ją Maks”: Ilości tylko
dla INEA to działanie Reguły ilości, które tata ustawia sam.

## Kontekst

Reguły ilości wpisują w Pliku zbiorczym `AP` (deinstalacja usługi z odbiorem
CPE) w zleceniu `gniazdo` i `AK` (dodatkowa sieć domowa do 10 m.b.) w
zleceniu z `technicolor`, bo INEA płaci za nie tacie przy każdym takim
zleceniu. Wykonawca tej pracy nie wykonuje, więc tata po podziale Pliku
zbiorczego kasował te komórki ręcznie w każdym Rozliczeniu pracownika. W 2026
roku to około 750 zleceń `gniazdo` i 300 z `technicolor`.

## Decyzja

- **Przebieg rozliczeń zostawia te komórki puste w Rozliczeniu pracownika.**
  `AP` w każdym Wierszu danych, którego `URZĄDZENIA` zawierają `gniazdo`, i
  `AK` w każdym, którego `URZĄDZENIA` zawierają `technicolor`, bez względu na
  wielkość liter, resztę `URZĄDZENIA` i liczbę w komórce.
- **Plik zbiorczy zostaje bez zmian.** Reguły ilości, Kontrola ilości i
  Uzupełnienie pliku zbiorczego dalej widzą te ilości, bo płaci za nie INEA.
- **Tata tego nie widzi.** Nie ma Komunikatu ani ostrzeżenia; liczba
  wyczyszczonych komórek trafia tylko do Logów Uruchomienia.
- **Zasada należy do taty, a utrzymuje ją Maks**, tak jak Reguły ilości. Obejmuje
  każdy Przebieg rozliczeń po Aktualizacji narzędzia, także okresu
  przygotowanego wcześniej.

## Odrzucone warianty

- **Koszt 0 we Wzorcu rozliczenia pracownika.** `AK` i `AP` są płatne
  Wykonawcy w innych zleceniach.
- **Czyszczenie w Pliku zbiorczym.** Za te pozycje płaci INEA, a Plik zbiorczy
  jest podstawą rozliczenia z nią.
- **Tylko trzy wpisy z instrukcji taty** (`technicolor`, `technicolor globo`,
  `technicolor 2*globo`). Tata potwierdził, że liczy się każde zlecenie z
  `technicolor` w nazwie, także `technicolor 3*globo` czy `technicolor arion`.

## Konsekwencje

Gdy technik przy zleceniu z `technicolor` naprawdę położy dodatkową sieć
domową, Wykonawca nie dostanie za nią `AK`. To świadome ograniczenie do czasu,
gdy zajmiemy się ilościami z opisu technika.
