# Jev (TypeSafe) w CI: gdzie typowany osąd może pomóc i jak to tanio sprawdzić

Badanie z 19.11.2026. Badanie źródeł nie wywoływało API TypeSafe; eksperyment E1 wywołał je tego samego dnia na publicznych logach CI, za zgodą Maksa (sekcja „Wynik E1”).
Każde twierdzenie ma numer źródła [Sn] z listy na końcu. „Niepotwierdzone” znaczy, że nie znalazłem źródła pierwotnego.
Liczby o naszym CI pochodzą z pomiarów 11–18.11 [S30, S31, S32] i z tekstu zlecenia. Tam, gdzie liczba jest tylko w zleceniu, piszę to wprost.

## Werdykt

1. **Czym jest Jev.** Jev to model, który nie generuje tekstu. Dostaje stan i pytania typu Choice (najwyżej 255 opcji), Score (najwyżej 10 poziomów), Noul (tak/nie) albo Box, a dla każdego pytania zwraca typowaną odpowiedź z rozkładem prawdopodobieństwa [S1, S5, S13]. Kosztuje 0,042 USD za milion tokenów wejścia, a tokeny wyjścia są darmowe [S3]. Limit kontekstu to 64k tokenów na żądanie i 32k na pytanie [S3]. Typowe wywołanie trwa ok. 100 ms [S6]. Limity zapytań ustala się per organizacja w konsoli, a ich wartości są niepotwierdzone [S3]. Odpowiedzi nie są deterministyczne: między powtórzeniami prawdopodobieństwa przesuwają się do 0,015 [S11], a API nie ma parametru temperatury ani ziarna [S5]. Alias `jev-latest` przesuwa się z każdym wydaniem, więc wersję trzeba przypiąć (`jev-1.14.0`) [S3].
2. **Koszt i opóźnienie nie są ograniczeniem.** Najdroższy kandydat, zawężanie wyboru testów, kosztowałby przy ok. 1000 runach PR na tydzień najwyżej ok. 2,7 USD tygodniowo według cennika. Każdy eksperyment offline poniżej kosztuje mniej niż 1,5 USD. Opóźnienie ~100 ms też nie ma znaczenia przy bramce, która trwa minuty. Dwie główne zalety Jev, szybkość i cena wobec LLM, prawie nic tu nie dają. Zostaje skalibrowane prawdopodobieństwo dla osądu semantycznego o logu albo diffie.
3. **Jedyny kandydat wart testu, doradcza klasyfikacja porażki, odpadł w E1 (NO-GO, pkt 8).** Chodziło o porażki zadania, które `tools/ponow_ci.py` dziś uznaje za „nieznaną porażkę, więc defekt” [S27], i o issue czerwonego `main`. Jev nigdy nie uruchamiałby ponowienia, tylko dopisywałby linię do odmowy i do issue. Zysk byłby w czasie pierwszej diagnozy agenta, a nie w ścianie CI. Eksperyment E1 z progiem go/no-go opisuje sekcja E1, a jego wynik sekcja „Wynik E1”.
4. **Nie robić: zawężania wyboru testów ani pomijania podstaw skilli przez Jev.** Oba pomysły kłócą się z ADR 0020 („Dalsze skracanie bramki to przyspieszanie samych testów, nie zdejmowanie ich z bramki”) [S24] i z zasadą, że nieznana forma kończy się bezpiecznie (fail closed) [S26]. Do tego za mało pozytywów, żeby dowieść recall: prawdziwych defektów `src/` złapanych przez podstawy było ok. 3 na tydzień [S30]. Większy zysk dają zmiany deterministyczne, które już zmierzono: planer zaniża realną ścianę o 112 s przy p50 i 436 s przy p90, a zawężenie FULL i warianty NF/N0 obniżają p50 z 4,7 do 3,9–4,3 min [S30].
5. **Nie robić: Jev dla etykiety `zderzenie`.** W danych nie ma ani jednego prawdziwego zderzenia (0 z 5 w tygodniu 12–18.11, 0 z 6 w ADR 0020) [S31, S24], więc nie da się zmierzyć ani precyzji, ani recall. Prostsza jest poprawka deterministyczna (sekcja K5).
6. **Dane.** Do Jev mogą trafić tylko artefakty CI publicznego repo: diff, nazwy testów i ogon logu kroku, który padł. Dane taty nie mogą tam trafić nigdy, także dlatego, że zgoda na podprocesora dla jego umowy jest otwarta (#1157). TypeSafe nie trenuje na danych wejściowych [S3, S18, S20]. Retencja to jednak „as long as reasonably necessary” [S18, S19], telemetrię z danych klienta TypeSafe może trzymać bezterminowo [S20], a zero data retention ma tylko plan enterprise [S17]. Listy podprocesorów nie udało się odczytać (niepotwierdzone).
7. **Wniosek ogólny.** Dla ścieżki merge'a odpowiedź brzmi „nie opłaca się”. Mały zysk był możliwy tylko w roli doradczej, przy pierwszym wystąpieniu flaky testu i nowej awarii infrastruktury.
8. **Wynik E1: NO-GO.** Na 189 przypadkach (567 wywołań `jev-1.14.0`, 0,12 USD) żaden próg nie dał precyzji ≥ 0,9 bez defektu nad progiem. Jev odróżnia flaky i awarie od defektów słabo (AUC 0,61), a na 29 ręcznie oznaczonych przypadkach czerwonego `main` gorzej niż losowo (AUC 0,42). Doradczego klasyfikatora z Jev nie budujemy (sekcja „Wynik E1”).

## Czym jest Jev: kontrakt, koszt, opóźnienie, limity

### Kontrakt API

- **Wywołanie.** Jedno wywołanie to `POST https://api.typesafe.ai/v1/systemone` z polami `model`, `state` i `questions`, opcjonalnie `assets` dla obrazów [S5]. `state` może być napisem, obiektem JSON albo tablicą [S5]. `questions` to słownik nazwanych pytań (co najmniej jedno), a odpowiedzi wracają pod tymi samymi nazwami [S5].
- **Odpowiedź** zawiera `model` (wersję, która faktycznie odpowiedziała), `answers` i `usage` z polami `input_tokens` i `output_tokens` [S5].
- **Typy pytań** [S1, S5, S13]:
  - Choice: `choice`, `probabilities` po opcjach i `confidence`; `criteria` ma od 1 do 255 opcji (OpenAPI `maxProperties: 255`).
  - Score: `score` (średnia ważona po poziomach), `probabilities`, `confidence` i `legend`; od 1 do 10 poziomów, a strona Score zaleca co najmniej dwa.
  - Noul: `noul` od 0 do 1, bez `confidence`.
  - Box: tylko dla obrazów, od Jev 1.14 z 14.10.2026 [S3, S23].
- **Pytania są od siebie niezależne.** Każde pytanie jest oceniane osobno i równolegle wobec tego samego stanu, więc odpowiedzi nie widzą się nawzajem [S1]. Liczba pytań nie ma osobnego limitu, ogranicza ją tylko kontekst [S3, S13].
- **`confidence`** to statystyka liczona z kształtu rozkładu (1 to cała masa na jednej opcji, 0 to rozkład równy), a nie prawdopodobieństwo, że odpowiedź jest poprawna [S9].
- **Kalibracja** dotyczy grup przewidywań, a nie gwarantuje poprawności pojedynczej odpowiedzi [S2, S10]. Dokumentacja każe ustalać progi na własnych danych [S9].
- **SDK** [S14, S15, S16]:
  - Python: `typesafe-sdk` 0.7.5, `requires-python >=3.10`, klient synchroniczny i asynchroniczny. Domyślnie ma timeout 10 s na operację HTTP, model `jev-latest` i ponowienia (`max_retries=2`, 429/5xx).
  - JavaScript/TypeScript: `@typesafe-ai/sdk` dla Node.js 22 lub nowszego.
  - SDK nie jest potrzebne: plan CI biegnie systemowym `python3` z samą biblioteką standardową [S29], a do HTTP API wystarczy `urllib`.
- **Czego Jev nie robi.** Nie generuje tekstu ani wyjaśnień [S2, S21]. Agent dalej musi więc sam przeczytać log, a Jev daje tylko sygnał do skierowania sprawy.

### Koszt

- **Cena** to 0,042 USD za milion tokenów wejścia (Jev 1.14 i 1.13), a tokeny wyjścia są darmowe [S3]. Pole `usage.input_tokens` w API opisano jako „billable input tokens” [S5].
- **Stan płaci się raz na żądanie.** Pytania zebrane w jednym żądaniu płacą za stan raz. W przykładzie 13 pytań do jednego dokumentu jedno żądanie było 12,2 raza tańsze niż 13 osobnych [S11].
- **Kredyty.** MCA mówi, że kredyty schodzą za każde wejście, a kurs „may vary based on account settings” [S20]. Kursu kredytu wobec dolara nie znalazłem (niepotwierdzone), więc koszty niżej podaję w USD według cennika.
- **Ważność kredytów.** Kredyty kupione wygasają po 12 miesiącach albo z końcem umowy [S20]. Kredyty promocyjne mają warunki podane przy wydaniu i schodzą przed kupionymi [S20]. Termin kredytów Maksa jest niepotwierdzony.

### Opóźnienie

- **Typowe wywołanie.** „Most calls complete in about 100 ms” [S6]. Strona przypadków użycia podaje „about 150ms” [S7]. W teście spójności średni czas obiegu wyniósł 103 ms przy małym stanie [S12].
- **Duży stan.** Czasu dla stanu bliskiego 64k tokenów (cały diff, długi log) nie znalazłem (niepotwierdzone). Długi kontekst (262k z nagłówkiem `TypeSafe-Danger-Zone-Long-Context`) jest „slower and less accurate” [S3].

### Limity i błędy

- **Rozmiar żądania.** Kontekst to 64k tokenów na całe żądanie (stan i wszystkie pytania) i 32k na stan z jednym pytaniem [S3]. Przekroczenie daje `400 max_tokens_exceeded` [S4]. Ciało żądania może mieć najwyżej 32 MiB, a stan, instrukcje i kryteria najwyżej 64 poziomy zagnieżdżenia [S4].
- **Limity zapytań.** Liczą się w tokenach na sekundę i żądaniach na sekundę, per organizacja, a przekroczenie daje `429`. Wartości są tylko w konsoli (niepotwierdzone) [S3]. Przeciążenie usługi daje `529` [S4].

### Determinizm i stabilność

- **Szum między powtórzeniami.** W 5 powtórzeniach 13 pytań 7 odpowiedzi było identycznych, a reszta przesunęła się najwyżej o 0,015 [S11].
- **Decyzje na granicy.** Na 40 granicznych postach najmniej stabilna decyzja zmieniała się średnio w 4,0% przypadków, a najczęściej w 6,7%. Wynik uśrednia wszystkie progi od 0 do 1 [S12].
- **Brak parametru determinizmu.** API nie ma temperatury ani ziarna [S5].
- **Kolejność opcji.** Jev woli pierwszą opcję Choice, więc dokumentacja radzi zamienić kolejność i sprawdzić, czy odpowiedź się nie zmienia [S8].
- **Słabe punkty według dokumentacji** [S8]: liczenie i arytmetyka, porównywanie dat, wiele kroków pośrednich, duży stan z nieistotnymi szczegółami, treść napisana przeciwko modelowi i dosłowne czytanie pytania.

## Kandydaci w CI

Każdy kandydat dostaje: wejście, pytanie typowane, to, co dziś robi kod deterministyczny, oczekiwany zysk, tryb porażki i miejsce (ścieżka merge'a albo tylko porada).

### Zasada repo wobec osądu probabilistycznego

- **Drabina naprawy.** Szczeble (a)–(e) to typ, zakaz ruff, kontrakt importów, reguła ast-grep i proza. „A new check that matches lines with a regular expression is not a rung” [S26]. Osąd modelu też nie jest szczeblem.
- **ADR 0036.** Chwastem jest reguła detektora z próbkami, która odmawia nowego wystąpienia [S25].
- **Fail closed.** Tekst, którego program nie napisał, czyta się parserem i przyjmuje tylko wymienione formy, a nieznana forma kończy się bezpiecznie [S26].
- **Gdzie Jev może stać.** Jev nie może stać tam, gdzie decyzja przepuszcza zmianę (ścieżka merge'a, ponowienie, pominięcie testów). Może stać tam, gdzie decyzja tylko kieruje uwagę agenta, a deterministyczny wynik zostaje bez zmian.
- **Powtarzalność.** CI musi dać się powtórzyć: werdykt `PASS <SHA>` i plan zapisany w `plan.json` [S24, S28]. Osąd z szumem między powtórzeniami [S11, S12] łamie tę własność na ścieżce merge'a, nawet z przypiętą wersją.

### K1. Klasyfikacja porażki zadania (ponow_ci, flaky, czerwony `main`)

- **Wejście.** Ogon logu kroku, który padł (`log_porazki` w `ponow_ci` [S27]), przycięty do ok. 6k tokenów, oraz id testu z linii `FAILED`/`ERROR` i nazwa zadania i toru (Windows 3.13 albo Linux 3.14). Do tego cechy policzone kodem: czy plik testu zmienił PR (Z7) i odległość testu od zmiany w grafie `wplyw_zmiany` [S29]. Logi zadań mają od 61 KB do 643 KB (4 logi w `ci-kun-2026-11-19/logi`), czyli za dużo na 32k tokenów, więc przycięcie jest konieczne [S3].
- **Pytania**, wszystkie w jednym żądaniu:
  - Choice `przyczyna`: `awaria_runnera` (sieć, pobieranie, runner, artefakt), `niestabilny_test` (czas, kolejność, port, blokada pliku, wyścig, bez związku z zachowaniem zmienionym w diffie), `defekt_zmiany` (asercja o wartości zwracanej przez kod, który zmienił PR) i `defekt_sprawdzenia` (skrypt skilla albo narzędzie CI).
  - Noul towarzyszący „czy któraś z opcji pasuje” [S8].
  - Noul `asercja_o_wartosci`: „Czy test padł na porównaniu wartości zwróconej przez kod, a nie na przekroczeniu czasu, błędzie systemu plików, sieci albo procesu?”.
- **Co robi dziś kod.** `ponow_ci` ponawia tylko awarię z `SYGNATURY` bez linii `FAILED`/`ERROR` i znany flaky test z otwartym issue `Flaky test:`. „Każda inna porażka, także nieznana, to defekt” [S27]. Issue czerwonego `main` nie klasyfikuje przyczyny i wprost mówi, że porażka „może być w innym PR z listy, ze zderzenia albo niestabilna” [S28].
- **Zysk.**
  - W tygodniu 12–18.11 było 31 issues czerwonego `main`: 18 flaky, 3 infrastruktury, 4 defekty w 5 issues i 5 defektów utajonych [S31].
  - Według numerów issue (wniosek) co najmniej 7 z 18 flaky dostało issue `Flaky test:` dopiero po czerwonym `main`: #1454, #1485, #1460, #1797, #1982, #2060, #2106. Kolejne 4 były „samo zeszło” bez issue. W tych przypadkach kod deterministyczny nie miał czego dopasować.
  - Na PR padło 56 z 691 runów w 14–18.11 [S31], czyli ok. 80 na tydzień przy 1000 runach.
  - Zysk to agent, który szybciej trafia z pierwszą hipotezą (flaky albo infrastruktura zamiast własnego defektu). Ile minut agenta to oszczędza, jest niepotwierdzone, bo nie mamy pomiaru czasu diagnozy. Ściana CI ani p50/p90 PR się nie zmieniają.
- **Tryb porażki.**
  - Jev nazwie defekt „niestabilnym testem” i agent go zbagatelizuje. Taki był #1075: ponowienie ukryło prawdziwy defekt [S24].
  - Treść logu może sterować odpowiedzią [S8].
  - Usługa może nie odpowiedzieć (`429`/`529`) [S4]. Wtedy linia nie powstaje, a reszta działa jak dziś.
- **Miejsce.** Tylko porada: linia `JEV | niestabilny_test 0.91 (jev-1.14.0)` w odmowie `ponow_ci` i w komentarzu issue. Bez wpływu na ponowienie, kwarantannę i Required. W `ponow_ci` klucz musiałby być w środowisku agenta, a w `zgloszenia.yml` jako sekret workflow.

### K2. P(zmiana tego PR może zepsuć plik testów X) jako drugi sygnał obok grafu

- **Wejście.** Diff PR (przycięty do ok. 30k tokenów, żeby zmieścić się w 32k na pytanie [S3]) i lista plików testów, które wybrał graf. Dla każdego pliku nazwa i jedno zdanie opisu, na przykład z docstringu.
- **Pytania.** Jeden Noul na plik: „Czy zmiana w `diff` może zmienić wynik testów w `tests/test_x.py`, opisanych jako …?”. Przy 129–171 plikach (liczba ze zlecenia) to 129–171 pytań w jednym żądaniu. Mieści się, bo liczba pytań nie ma limitu [S13], ale stan z pytaniami musi zmieścić się w 64k.
- **Co robi dziś kod.** Graf importów, napisów ze ścieżkami i globów, przechodni dla importów, wybiera każdy test, do którego zmiana dochodzi [S29]. Zmiana pliku z tabeli „uruchamia wszystko” wybiera wszystko [S29].
- **Zysk.**
  - Teoretycznie mniej plików na PR. Ściana bramki zależy jednak od najdłuższej jednostki i od narzutu zadań [S29], a nie tylko od ich liczby.
  - Backtest kształtów pokazuje, że p90 trzymają podstawy skilli i plan, a nie tylko pytest: kształt N0 (bez podstaw) obniża p90 z 10,8 do 9,1 min [S30].
  - Zysku zawężenia pytest przez Jev nie da się oszacować bez eksperymentu (niepotwierdzone).
- **Tryb porażki.** Pominięty test, który by padł, przepuszcza defekt na `main`. Nie trafi on do taty, bo Wydanie wymaga zielonego pełnego CI [S24], ale czerwieni `main`. Zawodzą tu dokładnie słabe punkty Jev: pośredniość (import przechodni, fixture w `conftest.py`) i dosłowne czytanie [S8]. Szum między powtórzeniami sprawia, że ten sam PR może dostać inny zbiór testów [S11].
- **Miejsce.** Ścieżka merge'a, więc wbrew ADR 0020 („nie zdejmowanie ich z bramki”, a do bramki i z bramki tylko z dowodem z backtestu) [S24] i wbrew fail closed [S26]. Bez decyzji Maksa: nie. Jako porada (kolejność plików w zadaniu, żeby test, który najpewniej padnie, biegł pierwszy) nie skraca zielonego runu, więc zysk jest pomijalny.

### K3. Czy PR potrzebuje podstaw skilli (Mutation checks)

- **Wejście.** Diff PR i dla każdego z 19 skilli `verify-*` jego opis i glob `pilnuje:`.
- **Pytania.** Jeden Noul na skill: „Czy zmiana w `diff` zmienia zachowanie, które sprawdza skill `verify-x`, opisany jako …?”.
- **Co robi dziś kod.** Podstawa `ci:` biegnie, gdy zmiana trafia w `pilnuje:` skilla [S24]. Mutation checks to 25,3% runner-minut runu PR [S31].
- **Zysk.**
  - W 11–18.11 Mutation checks były jedynym czerwonym zadaniem w 18 z 1011 runów PR. Około 3 na tydzień to prawdziwe defekty `src/`, a reszta to defekt sprawdzenia, flaky albo infrastruktura [S30].
  - Kształt NF (podstawa tylko przy zmianie folderu skilla) daje p50 4,1 min, a N0 (podstawy tylko na `main`) 3,9 min, wobec 4,7 dziś [S30]. Oba są deterministyczne.
  - Jev mógłby leżeć między nimi, ale nie ma jak dowieść, że nie gubi tych ~3 defektów na tydzień.
- **Tryb porażki.** Pominięta podstawa przepuszcza prawdziwy defekt `src/` na `main`, a dwie ucieczki z 12–18.11 (#1508, #1901) były czasowe na Windows [S31], czyli takie, których diff nie zdradza.
- **Miejsce.** Ścieżka merge'a, więc nie. Decyzja o NF/N0 i tak należy do Maksa, bo zmienia ADR 0020 [S30].

### K4. Kierowanie naprawy czerwonego `main`

- **Wejście.** Wynik K1 i lista PR-ów scalonych od ostatniego zielonego commitu, z diffami przyciętymi do budżetu.
- **Pytania.** Choice: który PR z listy zmienił zachowanie, które sprawdza padnięty test, albo `żaden`.
- **Co robi dziś kod.** Issue podaje PR-y w zakresie i polecenie `git bisect` [S28].
- **Zysk.** W 31 issues ok. 8 miało więcej niż jeden PR w zakresie, a prawdziwym defektem (D albo L) były z nich tylko #1783, #1871 i może #1834 [S31]. #1906 miał winnego (#1901) spoza zakresu, czego Choice nad listą zakresu nie wskaże.
- **Tryb porażki.** Wskazanie złego PR-u kosztuje jedną zmarnowaną rundę agenta.
- **Miejsce.** Tylko porada, jako dodatek do K1. Za mało przypadków na osobny eksperyment: mierzyć przy okazji E1.

### K5. Etykieta `zderzenie`

- **Wejście.** Diffy PR-ów A i B, nowa porażka i jej log.
- **Pytania.** Noul: „Czy porażka wynika z połączenia obu zmian, a nie z jednej z nich?”.
- **Co robi dziś kod.** Etykieta trafia na issue tylko wtedy, gdy każda nowa porażka to test, którego wejścia zmieniły oba PR-y, a zielony `main` bez zmiany wejść ją zdejmuje [S28].
- **Zysk.** Brak mierzalnego: 5 etykiet i 0 prawdziwych zderzeń w 12–18.11, a wcześniej 0 z 6 [S31, S24]. Bez żadnego pozytywu nie da się ustalić progu ani recall.
- **Tańsza droga deterministyczna.** Według numerów issue (wniosek) co najmniej 3 z 5 fałszywych etykiet (#1555 z #1505, #1669 i #1671 z #1580) miały issue `Flaky test:` otwarte przed czerwonym `main`. Warunek „żadna nowa porażka nie ma otwartego issue `Flaky test:`” w `zgloszenia_ci.py` odrzuciłby je bez modelu. To osobna zmiana z backtestem, poza zakresem tego badania.
- **Miejsce.** Nie dotyczy, Jev nie testować.

## Ograniczenia danych

- **Co może trafić do Jev.** Tylko to, co i tak jest publiczne w publicznym repo: diff, nazwy plików i testów, ogony logów zadań CI. Logi workflow publicznego repo może przeczytać każdy zalogowany użytkownik GitHuba [S22], więc wysłanie ich do TypeSafe nie odsłania nowej treści, tylko dodaje jej kopię u jeszcze jednego dostawcy.
- **Czego nie wysyłać nigdy:**
  - plików z Folderów okresu, Rejestru zleceń i Wzorców taty;
  - Logów uruchomień z komputera taty (`tools/odtworz_uruchomienie.py`);
  - treści Zgłoszeń z prywatnego repo;
  - konfiguracji (`config/`) i adresów wykonawców.
  Ich wysłanie zrobiłoby z TypeSafe podprocesora danych klienta taty, a zgoda z art. 28(2) RODO jest otwarta w #1157.
- **Logi CI z zasady nie niosą danych taty.** Klient Jev powinien jednak wysyłać tylko ogon kroku, który padł, po filtrze, który odrzuca log z oznaką danych spoza repo (na przykład ścieżka folderu z danymi taty albo adres e-mail). Wtedy nie wysyła nic.
- **Warunki TypeSafe:**
  - Brak treningu na danych wejściowych: „Jev is not trained on customer requests or responses” [S3], „We will not train or fine tune … on Input” [S18], a MCA nie pozwala bez zgody klienta włączać Customer Data do zbioru treningowego [S20].
  - Retencja: dane osobowe „as long as reasonably necessary” [S18], w DPA „as long as necessary taking into account the purpose” [S19]. Konkretnej liczby dni nie znalazłem (niepotwierdzone).
  - Telemetria: MCA daje TypeSafe bezterminowe prawo do tworzenia z Customer Data telemetrii („technical logs, hashes, summary statistics and classifications”), do wykrywania nadużyć i zgodności z prawem [S20].
  - Zero data retention jest tylko dla klientów enterprise [S17].
  - Lista podprocesorów jest na `trust.typesafe.ai/subprocessors` [S19], ale strona renderuje się skryptem i jej treści nie odczytałem (niepotwierdzone).
  - Prawo DPA: Irlandia, SCC moduł 2 i 3 [S19].
- **Sekret w CI.** Klucz `TYPESAFE_API_KEY` byłby sekretem repo. Workflow `zgloszenia.yml` ma już `GH_TOKEN` [S28], a sekret dla Jev dochodzi obok niego. W `ponow_ci` klucz byłby w środowisku agenta.

## Eksperymenty offline według oczekiwanej wartości

Wspólne zasady:
- przypięty `jev-1.14.0`;
- każdy przypadek 3 razy i w dwóch kolejnościach opcji, bo kolejność może zmieniać odpowiedź [S8];
- próg ustalany na połowie przypadków (dev), a mierzony na drugiej połowie;
- wynik z liczbą przypadków i przedziałem.

Koszt liczę według cennika 0,042 USD za milion tokenów wejścia [S3].
Wolumen to ok. 1000 runów PR i ok. 500 merge'ów na tydzień, z czego 500 scalonych PR-ów i 499 runów pushu na `main` w 12–18.11 [S31].
Zapytania do GitHub API: E1 potrzebuje ok. 100–150 pobrań logów, a reszta danych jest w cache.

### E1. Doradcza klasyfikacja porażki (K1, z K4 przy okazji): najwyższa wartość

- **Dane z etykietami, które już mamy:**
  - 31 issues czerwonego `main` z 12–18.11 sklasyfikowanych ręcznie jako F, I, D albo L, z PR-ami naprawy (`ci-kun-2026-11-19/zuzycie/klasyfikacja-czerwonego-main.md`, `cache/issues/*.json`, `fix-*.json`) [S31].
  - 32 issues `Flaky test:` z datami (`cache/issues/flaky.json`).
  - 18 runów PR, w których czerwone było tylko zadanie Mutation checks, z wynikiem następnego runu i zmienionymi plikami (`m_unikalne_1118.txt`, `klasy_1118.txt`) [S30].
  - Zadania runów PR i `main` w cache API (`agent-friction-2026-11-18/rekord/pomiar-11-18/api`, 1625 plików) [S32] i `zuzycie/cache/jobs`.
  - Etykiety awarii runnera z `SYGNATURY` w `ponow_ci` (142 padnięte próby z 2–12.11) [S27].
  - Do pobrania zostają same logi padniętych zadań, ok. 100–150 zapytań.
- **Populacja.** Do pomiaru wchodzą tylko przypadki, które deterministyczny `ponow_ci` uznałby za „nieznaną porażkę, więc defekt”. Pozostałe ponawia albo odrzuca już kod, więc Jev nic tam nie dodaje.
- **Etykieta.**
  - Czerwony `main`: klasa z tabeli.
  - PR: słabsza etykieta. Następny run na tym samym SHA zielony oznacza awarię albo flaky test. Nowy commit, który zmienia `src/` albo test, a potem zielony run, oznacza defekt.
- **Metryki:**
  - precyzja i recall `niestabilny_test ∪ awaria_runnera` wobec etykiety, przy progu z dev;
  - liczba przypadków D albo L z prawdopodobieństwem nad progiem, czyli niebezpiecznych;
  - zgodność między 3 powtórzeniami i dwiema kolejnościami opcji;
  - p50/p90 czasu wywołania;
  - `usage.input_tokens`;
  - przy okazji (K4) trafność top-1 PR-u wobec PR-u naprawy dla issues z więcej niż jednym PR w zakresie.
- **Go:**
  - na połowie testowej co najmniej 40 przypadków;
  - precyzja co najmniej 0,9 przy recall co najmniej 0,5;
  - zero przypadków D albo L nad progiem;
  - zmiana decyzji między powtórzeniami najwyżej w 5% przypadków;
  - populacja „nieznana porażka” co najmniej 5 na tydzień, bo mniej nie warte jest sekretu i kodu.
- **No-go.** Którykolwiek warunek niespełniony. Wtedy wynik „sprawdziliśmy, nie opłaca się” trafia do issue z liczbami.
- **Koszt eksperymentu.** Ok. 150 przypadków × 2 kolejności × 3 powtórzenia = 900 wywołań po ok. 7k tokenów = 6,3 mln tokenów ≈ 0,27 USD.
- **Koszt na tydzień przy wdrożeniu.** Ok. 80 padniętych runów PR i ok. 36 czerwonych runów `main` [S31]. Gdy pytamy tylko o populację „nieznana porażka”, to najwyżej ok. 120 wywołań po 7k tokenów ≈ 0,04 USD.

### E2. Zawężanie wyboru testów (K2): niska wartość, wysokie ryzyko

- **Dane.**
  - `pomiar.jsonl` ma 1526 runów z klasą zmiany [S32].
  - W 11–18.11 było 64 runów PR z czerwonym pytest [S30]. Ich id testów trzeba wziąć z logów (ok. 64 zapytania), a prawdziwość defektu ustalić jak w E1.
  - Wybór grafu dla każdego SHA da `tools/plan_ci.py plan` lokalnie, bez API.
  - Czasy plików są w `czasy-ci`.
- **Metryki:**
  - recall plików, które padły na prawdziwym defekcie, przy progu, który zdejmuje co najmniej 30% czasu wybranych plików;
  - symulowana zmiana p50/p90 ściany, liczona jak w backteście kształtów, czyli od zmierzonej ściany odjęta różnica planu [S30];
  - stabilność zbioru między powtórzeniami.
- **Go:**
  - recall 100% na co najmniej 30 runach z prawdziwym defektem;
  - p90 niższe o co najmniej 60 s;
  - żaden plik, który padł, nie przekracza progu w żadnym z 3 powtórzeń;
  - a potem i tak decyzja Maksa o zmianie ADR 0020 [S24].
- **Dlaczego wynik najpewniej wyjdzie no-go.** Nawet 30 z 30 trafień daje dolną granicę recall ok. 0,90 (reguła trzech: 1 − 3/30). Nie wykluczamy więc ucieczki raz na dziesięć defektów.
- **Koszt.** Eksperyment na 500 runach × ok. 50k tokenów = 25 mln ≈ 1,05 USD. Wdrożenie najwyżej ok. 2,7 USD na tydzień (pełne 64k × 1000 runów).
- **Co zrobić przed E2.** Najpierw poprawić deterministyczne zaniżenie planera (112/436 s) [S30]. Daje więcej, a nie zmienia ADR.

### E3. Pomijanie podstaw skilli (K3): nie uruchamiać teraz

- **Dane.** W 11–18.11 było 565 runów z Mutation checks, z czego 26 czerwonych, a 18 z nich miało czerwone tylko to zadanie. W 2–12.11 runów z czerwonym tylko tym zadaniem było 27 [S30]. Prawdziwych defektów `src/` było ok. 3 na tydzień [S30], czyli ok. 6–9 pozytywów w obu oknach.
- **Metryka i próg.** Te same co w E2: recall 100% i udział zdjętych runner-minut podstaw.
- **Decyzja.** Przy 6–9 pozytywach reguła trzech nie wyklucza gubienia jednej trzeciej do połowy defektów. Eksperyment nie może dać „go”, dopóki nie uzbiera się co najmniej 30 pozytywów, czyli ok. 10 tygodni. Koszt w kredytach byłby pomijalny (ok. 36k tokenów na run, ≈ 1,5 USD na tydzień), ale wynik nic by nie rozstrzygnął.

### E4. `zderzenie` (K5): nie uruchamiać

Zero pozytywów, więc nie ma metryki. Zamiast tego deterministyczny warunek z sekcji K5, sprawdzony backtestem na 5 etykietach z 12–18.11 i 6 z 5–6.11.

### Podsumowanie

| | Kandydat | Miejsce | Dane z etykietą | Koszt eksp. | Koszt/tydz. | Rozstrzygalne teraz | Rekomendacja |
|---|---|---|---|---|---|---|---|
| E1 | Klasyfikacja porażki (+K4) | porada | 31 issues czerwonego `main`, 32 flaky, 18 runów tylko z Mutation checks, `SYGNATURY` | ≈ 0,27 USD | ≈ 0,04 USD | tak (≥ 40 przypadków testowych) | uruchomiony 19.11: NO-GO (sekcja „Wynik E1”) |
| E2 | Zawężanie testów | merge | 64 runy z czerwonym pytest | ≈ 1,05 USD | ≤ 2,7 USD | słabo (recall ≤ 0,90 przy n=30) | najpierw planer; potem tylko za zgodą Maksa |
| E3 | Pomijanie podstaw | merge | ok. 6–9 pozytywów | pomijalny | ≈ 1,5 USD | nie | nie teraz |
| E4 | `zderzenie` | porada | 0 pozytywów | — | — | nie | reguła deterministyczna |

## Wynik E1 (19.11.2026)

Eksperyment według sekcji E1, z narzędziami w notatce lokalnej poza repo (`~/.t3/notes/ci-kun-2026-11-19/E1/`: `dane.jsonl`, `filtr.py`, `baza.py`, `jev.py`, `ocena.py`, `wyniki.jsonl`, `ocena.txt`).

- **Dane.** 189 przypadków: 29 z czerwonego `main` (etykiety ręczne: flaky 16, defekt 6, latent 5, awaria 2), 22 z runów PR, w których czerwone było tylko Mutation checks, 138 innych porażek PR (etykieta słaba: następny zielony run po zmianie kodu). Tylko populacja, którą `ponow_ci` uznaje za nieznaną porażkę.
- **Wysyłka.** Ogon kroku, który padł, po filtrze danych taty. Filtr w trybie „dane” odrzucił 0 przypadków; 41 trafień filtra dosłownego koordynator sprawdził ręcznie i wszystkie były słownictwem repo z testów syntetycznych (np. „Skrzynka raportów”, nazwa kolumny w nazwie testu).
- **Wywołania.** 567 (189 × 3 powtórzenia), w każdym pytanie Choice o 4 klasy w dwóch kolejnościach opcji i dwa pytania Noul. 2 883 684 tokeny wejścia = 0,1211 USD, 0 błędów, czas p50 0,22 s, p90 0,25 s.
- **Ocena** (`python3 ocena.py`, wydruk w `ocena.txt`, z którego pochodzą wszystkie liczby tabeli i mediany niżej; podział dev/test 50/50, próg z dev):

| Miara | Wynik | Poprzeczka |
|---|---|---|
| precyzja flaky∪awaria przy recall ≥ 0,5 | żaden próg na dev nie daje ≥ 0,9 bez defektu nad progiem | ≥ 0,9 |
| AUC flaky∪awaria wobec defekt∪latent, wszystkie przypadki | Choice 0,615, Noul 0,612 | — |
| AUC na etykietach ręcznych (czerwony `main`, 18 poz., 11 neg.) | 0,417 | > 0,5 |
| zmiana decyzji między 3 powtórzeniami tej samej kolejności opcji, bez progu (argmax 4 klas; P(flaky∪awaria) ≥ 0,5), test | 2/94 = 2,1%; 2/94 = 2,1% (wszystkie: 8/189 = 4,2%; 5/189 = 2,6%) | ≤ 5% zmian (przy progu z dev, którego nie ma) |
| zgodność argmax dwóch kolejności opcji, odczyty testu | 0,989 (279/282; wszystkie odczyty 0,972) | — |
| trafność argmax 4 klas (test) | 0,543 | — |
| baza deterministyczna z chwili porażki | precyzja 0, recall 0 | Jev musi ją pobić |

- **Werdykt: NO-GO.** Wynik nie jest artefaktem słabych etykiet PR: na samych etykietach ręcznych Jev daje prawdziwym defektom wyższe „bezpieczne” prawdopodobieństwo (Choice, mediana 0,51) niż flaky testom (0,25). Baza deterministyczna też nic nie wnosi, więc obie drogi zostają przy dzisiejszym `ponow_ci` i diagnozie agenta.
- **Granica wyniku.** Pozytywów jest mało (24, z tego 18 z czerwonego `main`), a jedna wersja modelu (`jev-1.14.0`) i jedno sformułowanie pytań. Inne sformułowanie albo nowsza wersja Jev wymaga nowego pomiaru tymi samymi skryptami (koszt ≈ 0,12 USD).

## Źródła

- [S1] TypeSafe, „Introduction”. https://docs.typesafe.ai/introduction
- [S2] TypeSafe, „System One”. https://docs.typesafe.ai/concepts/system-one
- [S3] TypeSafe, „Models” (cena, kontekst, długi kontekst, limity zapytań, aliasy, obsługa danych). https://docs.typesafe.ai/models
- [S4] TypeSafe, „Request rules and errors”. https://docs.typesafe.ai/api/errors
- [S5] TypeSafe, API „System One” i specyfikacja OpenAPI 0.2.0 (`SystemOneRequest`, `ChoiceQuestion.criteria maxProperties 255`, `ScoreQuestion.criteria maxItems 10`, `Usage`). https://docs.typesafe.ai/api/system-one, https://api.typesafe.ai/openapi.json
- [S6] TypeSafe, „How to build with TypeSafe”. https://docs.typesafe.ai/concepts/how-to-build-with-system-one
- [S7] TypeSafe, „Use cases”. https://docs.typesafe.ai/concepts/use-case-map
- [S8] TypeSafe, „Model jaggedness”. https://docs.typesafe.ai/model-jaggedness
- [S9] TypeSafe, „Confidence”. https://docs.typesafe.ai/confidence
- [S10] TypeSafe, „AI primer” (RLCD, kalibracja). https://docs.typesafe.ai/introduction/machine-learning-primer
- [S11] TypeSafe, cookbook „Parallel questions”. https://docs.typesafe.ai/cookbooks/parallel_questions
- [S12] TypeSafe, cookbook „Self-consistency: choices”. https://docs.typesafe.ai/cookbooks/consistency_choice_cookbook
- [S13] TypeSafe, „Primitives (Questions)” i „Score”. https://docs.typesafe.ai/primitives, https://docs.typesafe.ai/primitives/score
- [S14] TypeSafe, Python SDK: strona główna, „Constants” (`DEFAULT_TIMEOUT = 10.0`, `DEFAULT_MODEL = 'jev-latest'`), „Retries” (`max_retries = 2`), changelog v0.7.5 (14.10.2026). https://docs.typesafe.ai/sdk/python, https://docs.typesafe.ai/sdk/python/api/constants, https://docs.typesafe.ai/sdk/python/api/retries, https://docs.typesafe.ai/sdk/python/changelog
- [S15] PyPI, `typesafe-sdk` 0.7.5, `requires_python >=3.10`. https://pypi.org/pypi/typesafe-sdk/json
- [S16] TypeSafe, JavaScript SDK (Node.js 22 lub nowszy). https://docs.typesafe.ai/sdk/javascript
- [S17] TypeSafe, „Legal” (ZDR dla enterprise). https://docs.typesafe.ai/legal
- [S18] TypeSafe, „Privacy policy”, aktualizacja 19.11.2025. https://typesafe.ai/legal/privacy-policy
- [S19] TypeSafe, „Data processing addendum”, aktualizacja 24.04.2026. https://typesafe.ai/legal/data-processing
- [S20] TypeSafe, „Master customer agreement”, aktualizacja 23.09.2026 (4.1 licencja i trening, 4.3 telemetria, 8.2 kredyty). https://typesafe.ai/legal/mca
- [S21] TypeSafe, „Jev with coding agents”. https://docs.typesafe.ai/introduction/coding-agents
- [S22] GitHub Docs, „Using workflow run logs”. https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs
- [S23] TypeSafe, „Model changelog” (Jev 1.14, 14.10.2026). https://docs.typesafe.ai/changelog
- [S24] Repo, [ADR 0020: CI w poziomach](../adr/0020-ci-w-poziomach.md).
- [S25] Repo, [ADR 0036: Chwast to reguła](../adr/0036-chwast-to-regula.md).
- [S26] Repo, [`CODING_STANDARDS.md`](../../CODING_STANDARDS.md), wstęp, „Fixing a Mistake Class”, „Design”.
- [S27] Repo, `tools/ponow_ci.py --help` (stan `origin/main` 0765928975).
- [S28] Repo, `tools/scal_pr.py --help` i docstring `tools/ci/zgloszenia_ci.py` (ten sam commit); [`docs/agents/pr-i-ci.md`](../agents/pr-i-ci.md).
- [S29] Repo, docstringi `tools/plan_ci.py` i `tools/lib/wplyw_zmiany.py` (ten sam commit); [ADR 0021](../adr/0021-mutacje-noca.md).
- [S30] Notatka lokalna poza repo, `~/.t3/notes/ci-kun-2026-11-19/WYNIKI.md`, `m_unikalne_1118.txt`, `klasy_1118.txt` (pomiar 11–18.11, 1011 runów PR z zadaniami, backtest 113 scalonych PR).
- [S31] Notatka lokalna poza repo, `~/.t3/notes/ci-kun-2026-11-19/zuzycie/RAPORT.md` i `klasyfikacja-czerwonego-main.md` (okno 12–18.11).
- [S32] Notatka lokalna poza repo, `~/.t3/notes/agent-friction-2026-11-18/rekord/pomiar-11-18/` (`pomiar.jsonl`, cache API zadań).
