# ADR 0038: Legenda czynności wyznacza Ilości usług z opisu technika

## Status

Zaakceptowana (decyzja Maksa 16.11.2026 po mailu taty z legendą, grill w tej gałęzi). Zmienia te zdania wcześniejszych
ADR:

- [ADR 0033](0033-reguly-ilosci-naleza-do-taty.md), „Kolumny z opisu technika (…) zostają poza słownikiem, dopóki
  tata nie poda dla nich zasad”: tata podał zasady, a wyznacza je Legenda czynności, osobne Ustawienie Centrum, nie
  słownik Reguł ilości;
- [ADR 0018](0018-ilosci-tylko-dla-inea-nie-przechodza-do-rozliczenia-pracownika.md), „Konsekwencje”: ilości z opisu
  technika przestają czekać na osobną decyzję;
- [ADR 0013](0013-kontrola-ilosci-wysylana-automatycznie.md) i reguła prywatności Kontroli ilości: Kontrola ilości
  wysyła też `CZYNNOŚCI ZREALIZOWANE` z maskowaniem z [ADR 0025](0025-regula-danych-wysylki-do-skrzynki.md), ale tylko
  w wierszach opisanych niżej.

[ADR 0039](0039-opis-z-kodem-czynnosci-to-same-kody.md) zmienia po odpowiedziach taty zdania o pierwszym zestawie, spacjach i
zapisach kodu, liczbie spoza przedziałów, sumie wystąpień, tekście obok kodu, opisie w Kontroli ilości, `AS` i kolorach u
pracownika oraz legendzie w Przypomnieniu o raporcie.

## Kontekst

Kolumny Pliku zbiorczego z opisu technika (`Y`, `AB`, `AD`, `AJ`–`AM`) tata wypełnia ręcznie w każdym okresie: około
150 wierszy z `Y` tygodniowo. 15.11.2026 tata przysłał legendę kodów, które Wykonawcy piszą w Raportach wykonawcy, np.
`inst20m` daje 1 w `Y`, `spawpg` 1 w `AB`, 70 w `AS` i czerwone wypełnienie, a `instutp` wybiera kolumnę przedziałem
metrów. Wykonawcy już piszą tymi kodami (najczęściej `inst#m` i `instmdik`), choć z własnymi zapisami (`instmdic`,
`instrg610m`, `utp18m`).

Szkic legendy puszczony na pięciu Plikach zbiorczych wypełnionych przez tatę (08.09–09.11.2026, pliki na Macu Maksa i
Logi Wyceny w efenix) zgadzał się z tatą w 153 z 177 wierszy z kodem; Wykonawcy piszą kodami od października
(wrzesień: 9 wierszy z kodem). 16 z 24 różnic to wiersz, w którym obok kodu stał zwykły opis (`dzielnik 1/2` przy
„20 m patchcord”), a tata wpisał za ten opis `Y`. 6 to `rt2`: w mailu daje `AM`, a przy samym `rt2` w październiku i
listopadzie tata wpisał `AK`. Około dwóch trzecich wierszy z `Y` to nadal wolny tekst bez kodu.

## Decyzja

- **Legenda czynności to Ustawienie Centrum** ([ADR 0032](0032-ustawienia-centrum-zmienia-tata.md)), które tata
  zmienia sam w osobnej sekcji okna Ustawień. Wiersz legendy to Kod czynności z jego zapisami i z tym, co wyznacza.
  Pierwszy zestaw to mail taty z 15.11.2026 oraz zapis `instmdic` przy `instmdik`. Pytania do taty nie wstrzymują
  budowy: do jego odpowiedzi działają wartości domyślne z grilla, a odpowiedź zmienia dane legendy.
- **Kod czynności** czyta się w `CZYNNOŚCI ZREALIZOWANE` bez względu na wielkość liter i spacje wewnątrz kodu, w
  jednym z jego zapisów, i bez względu na to, kto go wpisał: Wpisanie raportów, tata czy pracownik. Liczba w kodzie
  albo nie ma znaczenia, albo przedziałem wybiera kolumnę. Liczba spoza przedziałów niczego nie wyznacza, a tata widzi,
  który kod został mu do wpisania. Nic bardziej rozmytego: „spawanie gniazda” to nie `spawgnd`.
- **Co wyznacza kod.** Ilość usług w jednej kolumnie, kwotę w `AS` (Uwagi - kwota), Wyróżnienie (kolor wypełnienia,
  także bez wartości w komórce) albo kilka z nich naraz. Każde wystąpienie kodu się dodaje, także kwoty w `AS`, a różne
  kody w jednym zleceniu się sumują. Kolor bez wartości nie robi ze zlecenia Zlecenia ze zdjęciami.
- **Gdzie działa.** Przygotowanie pliku zbiorczego wpisuje wynik legendy do Pliku zbiorczego obok Reguł ilości;
  Rejestr zleceń zostaje bez zmian. Wynik przechodzi do Rozliczeń pracowników jak każda Ilość usług i Wyróżnienie.
- **Wiersz skończony to wiersz z samych kodów.** Wiersz wypada z Ilości do uzupełnienia tylko wtedy, gdy jego
  `CZYNNOŚCI ZREALIZOWANE` to same Kody czynności (poza `tak`, `nie` i znakami interpunkcji). Gdy obok kodu stoi inny
  tekst, legenda wpisuje swoje, a wiersz zostaje tacie do sprawdzenia. Wiersz bez kodu zostaje tacie jak dotąd.
  Słowa obok kodu nie dają osobnego ostrzeżenia.
- **Kontrola ilości obejmuje legendę.** W wierszach z Kodem czynności porównuje kolumny legendy, `AS` i kolory
  legendy z tym, co wpisał tata. Dla każdego wiersza z różnicą i każdego wiersza bez kodu z wartością taty w kolumnie z
  opisu technika wysyła treść `CZYNNOŚCI ZREALIZOWANE`, czyli opis z Raportu wykonawcy, z maskowaniem z ADR 0025.
  Dzięki temu z różnic widać nowe kody i zapisy, tak jak różnice Reguł ilości.
- **Brama przed Wydaniem.** Zanim legenda trafi do taty, Maks widzi jej wynik na wszystkich Plikach zbiorczych
  wypełnionych przez tatę (pliki na Macu i Logi Wyceny w efenix): w ilu wierszach z kodem daje to samo co tata i każdą
  różnicę osobno.
- **W kodzie, nie w danych**, do odpowiedzi taty: kod sumuje się także w `Y` (np. `instmdik` i `inst20m` dają 2), a
  `AS` i kolory przechodzą do Rozliczenia pracownika. Zmiana któregoś z nich to Wydanie. Zlecenie nieskuteczne nie
  trafia do Pliku zbiorczego, więc legenda go nie widzi.
- **Później:** podpowiedzi różnic legendy w Centrum („Dodaj ten zapis do kodu” / „To był wyjątek”, jak przy Regułach
  ilości) i legenda w Przypomnieniu o raporcie.

## Odrzucone warianty

- **Rozszerzenie słownika Reguł ilości** o warunek „`CZYNNOŚCI ZREALIZOWANE` zawierają kod” i działania kwoty,
  koloru i przedziału. Słownik urósłby o trzy rodzaje działań, a mail taty to tabela legendy, nie „jeśli … to …”.
- **Legenda w kodzie, zmieniana Wydaniem.** ADR 0033 odrzucił tę drogę dla reguł: każda poprawka czekałaby na Maksa.
- **Wiersz z kodem zawsze skończony.** W danych taty `Y` za zwykły opis obok `dzielnik 1/2` zniknęłoby w 16 wierszach
  na pięć okresów.
- **Kontrola ilości tylko z rozpoznanymi kodami, bez tekstu.** Bezpieczniejsze, ale różnica w wierszu bez kodu (np.
  220 w `AS` za „listwy 11 metrów”) nie mówiłaby, jaki kod dopisać.
