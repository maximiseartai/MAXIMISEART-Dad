# Przegląd PR: korzeń i chwast

Każde Ważne z przeglądu i każdy czerwony `main` z prawdziwej zmiany (nie flaky test) kończy się wyrwaniem korzenia, a nie łatką pod `PASS` ([ADR 0031](../../../docs/adr/0031-korzen-po-fail-i-chwasty.md)).
Ta sama reguła obowiązuje przy poprawce operatora.

- **Korzeń** to to, co skłoniło agenta do błędu, a nie sam błąd: skopiowany najbliższy przykład, druga droga do tego samego, brak typu albo właściciela, instrukcja.
  Korzeń ma kod z zamkniętej listy [`korzenie.toml`](korzenie.toml), a każdy kod ma tam jedno zdanie i przykład PR.
  Kod korzenia to kategoria, więc jego powrót w innym PR niczego nie blokuje ([ADR 0036](../../../docs/adr/0036-chwast-to-regula.md)).
- **Chwast** to reguła detektora: reguła ast-grep, klucz `banned-api` ruff albo kontrakt import-linter, z komunikatem „użyj X” i próbkami.
  Prawdziwy powrót to odpalenie reguły na dodanej linii w Required CI, a ucieczka to wystąpienie idiomu po merge'u jego reguły, którego reguła nie złapała.
- **Szczebel** to poziom, na którym korzeń wyrwano, od najwyższego:
  - (a) usuń drugą drogę i stare przykłady, daj jednego właściciela;
  - (b) typ, z którym zła droga nie przechodzi mypy, albo reguła ruff (`banned-api` z `msg` „użyj X”);
  - (c) test zachowania, który łapie całą klasę, nie tylko ten przypadek;
  - (d) reguła deklaratywna gotowego narzędzia, czyli reguła ast-grep w `reguly-ast-grep/` na liniach dodanych albo na całym drzewie (warunki w [`CODING_STANDARDS.md`](../../../CODING_STANDARDS.md));
  - (e) nowy punkt z linkiem do PR, który go dopisuje, w sekcji „Co jest porażką” pliku [`SKILL.md`](SKILL.md), a punkt o ADR, specyfikacji albo issue `decyzja-maksa` w tej sekcji pliku [`porazka-adr.md`](porazka-adr.md).

  Reguła (d) stoi między (c) a (e), bo jest deterministyczna, a (e) to proza: (d) jest dozwolona tylko wtedy, gdy (a)–(c) nie działają, a (e) tylko wtedy, gdy (a)–(d) nie działają.
  Reguła struktury, której nie wyraża typ, zakaz ruff, kontrakt import-linter ani reguła ast-grep, dostaje test zachowania (c) albo punkt w „Co jest porażką” (e), a nie nowy matcher w Pythonie.
  To rozwinięcie decyzji Q7 i Q26 przez koordynatora (13.11.2026), do potwierdzenia przez Maksa.

  Zakaz ruff albo mypy z (b) nie zastępuje testu, który szuka nazwy w kodzie, dopóki dla tej reguły wolno `noqa` albo `type: ignore`, więc test usuń dopiero, gdy zamiennik łapie każdą formę, którą test łapał (#1371).

Reguły szczebla i dowodu:

- Autor wyrywa korzeń na najwyższym szczeblu, który działa, a przy każdym wyższym pisze jedno zdanie, czemu nie działa.
  Gdy recenzent pokaże działający wyższy szczebel, to Ważne.
  „Bez mechanizmu” nie jest szczeblem.
- Dowód wyrwania: mechanizm pada na pierwotnym błędzie, a liczy go bramka strażnika (niżej).
  Recenzent następnej rundy jedną sondą sprawdza siostrzaną formę błędu, której poprawka nie nazwała; forma, która przechodzi, to Ważne.
  Przy Ważnym z korzeniem R-PROZA-KOPIA regułę „Fix the class, not the instance” z `CODING_STANDARDS.md` autor stosuje do prozy: klasą jest każde zdanie diffu od merge-base na temat zdania z werdyktu, które przed kolejną rundą czyta z kodem (#2069: trzy `FAIL` za kolejne zdania o tym, skąd gospodarze biorą Ustawienia ze startu, `PASS` dopiero po przeczesaniu wszystkich).
- Autor może zakwestionować kod korzenia z powodem w odpowiedzi na werdykt, a rozstrzyga recenzent następnej rundy kodem w swoim werdykcie: punktem `Korzeń W<n> r<k>: R-KOD - zdanie` w `## Sprawdzone`, gdzie `r<k>` to `k`-ty werdykt PR.
  Rejestr korzeni i bramka korzenia biorą kod z ostatniego werdyktu, który dotyczy tego Ważnego, a kod w tym punkcie sprawdza się jak w polu `Korzeń:`.
- Autor opisuje wyrwanie każdego Ważnego w sekcji `## Korzeń` opisu PR według wzoru sekcji „Root section” skilla [`pr`](../pr/SKILL.md), a `tools/scal_pr.py` odmawia merge'a, dopóki sekcji czegoś brakuje.
  Większy korzeń (ponad `size:M`) idzie osobnym PR-em korzenia, który scala się najpierw (wzór w tej samej sekcji skilla `pr`).
  Rozmiaru wyrwania `tools/scal_pr.py` nie liczy, więc rozstrzyga go recenzent.
- Gdy żaden kod z listy nie pasuje, recenzent pisze `Korzeń: NOWY R-KOD - opis` z kodem, którego na liście nie ma, a nie najbliższy kod, bo zły kod zafałszowałby rejestr powtórzeń.
  Autor dopisuje ten kod do [`korzenie.toml`](korzenie.toml) w swoim PR, z jednym zdaniem i przykładem PR, a kolejne werdykty piszą go już bez `NOWY`.

Strażnik ([ADR 0042](../../../docs/adr/0042-straznik-przy-pierwszym-waznym.md)):

- Każde Ważne kończy strażnik: autor wpisuje w jego bloku sekcji `## Korzeń` linię `Strażnik: <selektor>` z listy w `ZASADY` [`tools/lib/straznik.py`](../../../tools/lib/straznik.py), a `tools/scal_pr.py` scala PR tylko z dowodem każdego strażnika (warunek 5).
  Autor sprawdza dowód przed kolejną rundą: `tools/na_scalonych_pr.py --straznik '<selektor>' --z-commita <HEAD PR> --wazne <PR>/W<n>/r<k>`.
  Próbka `ZNANE_LUKI` nigdy nie zastępuje strażnika; wolno ją dodać obok niego dla formy siostrzanej, której mechanizm nie wyrazi.
- Dowód bierze złą postać z drzewa SHA werdyktu i z funkcji wokół `Gdzie` (mypy i ruff liczą znalezisko w tej funkcji), więc recenzent pisze w `Gdzie` linie złego kodu, które poprawka ma zmienić, a nie miejsce objawu.
- Recenzent następnej rundy czyta z linii dowodu, które znalezisko padło, i daje Ważne, gdy strażnik łapie inną poprawkę tego PR niż to Ważne; przy `Strażnik: brak - napęd` uruchamia krok napędu skilla `verify-*` na drzewie SHA werdyktu, a to, co przechodzi, to Ważne.
- Test jako strażnik to `Strażnik: pytest tests/<plik>.py::<test>` (jeden test albo jego parametr), a złą postać pisze recenzent, nie autor: blok `### Mutacja W<n> r<k>` w werdykcie (szablon w sekcji „Postać werdyktu” pliku [`SKILL.md`](SKILL.md)) z mutacją, która na HEAD przywraca zachowanie z Dowodu Ważnego najmniejszą zmianą kodu, konfiguracji albo reguły, nie testu.
  Dowód przechodzi, gdy test na HEAD scalonym z bazą bez mutacji przechodzi, z każdą mutacją najnowszego bloku tego Ważnego w werdyktach PR biegnie i pada, a po nich bez mutacji przechodzi znowu (ADR 0042, aneks „Test jako strażnik z mutacją recenzenta”).
- Recenzent rundy, która sprawdza poprawkę Ważnego ze `Strażnik: pytest …`, czyta najnowszy blok tego Ważnego i pisze w swoim werdykcie, także w `PASS`, nowy blok `### Mutacja W<n> r<k>`, gdy bloku nie ma, gdy jego kotwicy nie ma na HEAD dokładnie raz albo gdy mutacja nie przywraca błędu z Ważnego (jest słabsza od niego albo psuje więcej), a gdy test łapie wierną mutację inną drogą niż błąd (np. na wejściu, którego błąd nie dotyczy), dopisuje do bloku formę siostrzaną błędu, której ta droga nie łapie.
  Blok sprawdza przed publikacją: `tools/mutacje.py --plik <blok.json> -- -m pytest -q -n 0 <węzeł>`, a `NIEWYKRYTA` to Ważne, bo strażnik nie łapie błędu; narzędzie i dowód liczą werdykt tą samą funkcją `silnik_mutacji.judged`, także gdy węzła z mutacją nie ma (`tools/mutacje.py --zasady`).
  Gdy test czyta stan modułu, który w sesji Required CI może ustawić inny plik testów (rejestr wypełniany przy imporcie) albo wcześniejszy test, sprawdza blok też z plikami testów, które ten moduł importują, w jednym poleceniu pytest, a `NIEWYKRYTA` tam to Ważne, bo dowód uruchamia węzeł sam (aneks ADR 0042, „Granica: sąsiedzi w sesji Required CI”).
  Blok stoi przed `## Sprawdzone` w `FAIL` albo w `PASS`, najwyżej jeden na Ważne w werdykcie, a pod nagłówkiem ma tylko blok kodu ``` albo ~~~ bez nazwy języka (```json GitHub renderuje inaczej, więc to odmowa) z JSON pliku `tools/mutacje.py --plik` z kluczami `nazwa` i `zmiany`, bez zmian w `tests/`.
  Recenzent `FAIL` daje blok od razu, gdy wie, jaki kod po poprawce przywróci błąd; wierność bloku ocenia recenzent następnej rundy, bo dowód gwarantuje tylko, że test pada przez tę mutację.
- `Strażnik: brak - test` przechodzi tylko w wątku z pierwszym werdyktem sprzed wdrożenia dowodu testu (`bramka_straznika.TEST_MARKER`), więc tam dowód testu jest osądem recenzenta jak przed ADR 0042.
  Recenzent następnej rundy uruchamia test, który nazywa `Szczebel:` bloku, na drzewie SHA werdyktu `FAIL` (przy próbce testu: mutację złej implementacji z Dowodu Ważnego) i daje Ważne, gdy test przechodzi, pada tylko z braku czegoś, co poprawka dodała obok kodu z `Gdzie` (moduł, metoda, nazwa, opcja), albo gdy Ważne zamknąłby wyższy szczebel z dowodem narzędzia (`mypy`, `ruff`, `ast-grep <id>`, `pytest <węzeł>`).
- Kod z `Gdzie` usunięty z PR (szczebel (a)) to `Strażnik: brak - usunięte`; recenzent następnej rundy sprawdza, że ten kod zniknął z HEAD i nie wrócił inną drogą, a gdy stoi albo wrócił, to Ważne.

## Mechanizm

Recenzent wpisuje w każdym Ważnym pole `Mechanizm:` z jednym szczeblem piramidy [ADR 0031](../../../docs/adr/0031-korzen-po-fail-i-chwasty.md), od najwyższego, i wybiera najwyższy, który działa, czyli odmówi nowej kopii tego błędu napisanej przez innego agenta w innym pliku albo funkcji repo, bez recenzenta ([ADR 0046](../../../docs/adr/0046-szczebel-straznika-wybiera-recenzent.md)).
Autor szczebla nie wybiera, a recenzent następnej rundy daje Ważne, gdy pokaże działający szczebel wyższy niż wpisany, jak przy `Szczebel:`.
Oceniasz klasę błędu, nie jedną linię: reguła, która pasuje tylko do tej linii z tą nazwą zmiennej, nie jest szczeblem `lint`.

- **architektura**: jeden właściciel, usunięta druga droga albo typ, z którym zły stan jest niewyrażalny, i strażnik obejścia, który odmawia kodu omijającego nową strukturę: typ, zakaz `TID251` właściciela albo reguła ast-grep.
  Przykład: #1553 dał tytułowi okna Ustawień jeden lokator `settings_title`, a nic nie odmówiło nowej kopii, która przyszła z #1533, więc dziś pilnuje go reguła `reguly-ast-grep/lokator-tytulu-okna.yml`; #2125 buduje wejście odczytu okna tylko w `report_inputs`, a drugi konstruktor zatrzymuje ruff.
- **refaktor**: zmiana postaci kodu w miejscu błędu bez nowego właściciela, którą trzyma typ, zakaz ruff albo reguła ast-grep: gotowy parser zamiast ręcznego, kształt, który kod przyjmuje, zamiast rosnącej listy wyjątków, `zip(strict=True)` pod `B905`.
  Przykład: #2161 zastąpił w `srodowisko_ci.mismatch` listy dozwolonych postaci równością z jedną postacią zadania.
- **lint**: zakaz nazwy (`banned-api` z `msg` „użyj X”) albo reguła ast-grep na kształcie złego kodu, bez zmiany samego kodu poza poprawką.
  Przykład: #1719 zakazał `time.sleep` w `drive/` poza `drive/waiting.py`.
- **test**: błąd logiki (warunek, liczba, kolejność kroków, stan po kroku), którego składnia nie zdradza, w jedynym właścicielu, którego jedyność już pilnuje typ, zakaz `TID251` albo reguła ast-grep z jego prawem właściciela; strażnikiem jest test zachowania na właścicielu.
  Przykład: zły dzień raportu w `worker_reports.EnteringMemory`, którego jedyność trzyma mypy (wiersz tabeli w „Design” `CODING_STANDARDS.md`).
  Jedyny właściciel bez takiej ochrony to szczebel `architektura`: PR dopisuje zakaz albo regułę, która kieruje do niego resztę kodu.
- **weryfikacja**: błąd jednorazowy w treści, którego nowa kopia nie ma rozpoznawalnej postaci ani właściciela (zdanie prozy, zła liczba w jednym teście, zachowanie widoczne tylko w napędzie frontendu); strażnikiem jest test, `brak - proza` albo `brak - napęd`.
  Przykład: #2069 dostał trzy `FAIL` za kolejne zdania o tym, skąd gospodarze biorą Ustawienia ze startu.

Szczebel nie działa, gdy jego reguła daje fałszywy alarm w ponad 10% PR-ów dowodu `tools/na_scalonych_pr.py --regula` albo wymaga listy nazw, która rośnie z każdym nowym kodem (#1904, #1919 i #1964 trzy razy poszerzały `regula-w-trasie` o nowe metody zapisu); wtedy recenzent schodzi szczebel niżej bez osobnej zgody.
Kod z `Gdzie` usunięty z PR to `architektura`, gdy zakaz usuniętej nazwy albo reguła na złej postaci z drzewa `FAIL` łapie jego powrót, a gdy się nie da, recenzent wpisuje niższy szczebel.
Którego selektora `Strażnik:` szczebel żąda, sprawdza dziś recenzent następnej rundy, a bramka strażnika liczy dowód selektora, który wpisał autor.
