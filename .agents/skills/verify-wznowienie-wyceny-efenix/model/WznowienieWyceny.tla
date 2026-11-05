------------------------------ MODULE WznowienieWyceny ------------------------------
(* Wycena w efenix przez kolejne Uruchomienia jednego okresu: Ślad Wyceny Emmetta na dysku taty, Zatrzymanie okna      *)
(* efenix, zgaśnięcie Centrum w każdym miejscu, nieudany zapis śladu i ręczne zmiany taty w efenix między            *)
(* Uruchomieniami. Każda akcja to jeden niepodzielny krok kodu z tabeli w SKILL.md skilla                            *)
(* verify-wznowienie-wyceny-efenix: src/rozliczenia/efenix_pricing.py (price_orders.save, _priced, _outcome,         *)
(* _after_emmett, _entered, _mark) i src/rozliczenia/efenix_emmett_trace.py (EmmettTrace).                          *)
EXTENDS Naturals, FiniteSets

CONSTANTS
    LiczbaZlecen,      \* zleceń w zakresie Pliku zbiorczego, przetwarzanych po kolei
    MaxUruchomien,     \* Uruchomień Wyceny w efenix tego okresu
    MaxZmianTaty,      \* ręcznych zmian ilości w efenix przez tatę
    MaxAwariiSladu,    \* nieudanych zapisów pliku śladu (_replace zwraca False)
    MozeZgasnac,       \* Centrum może zgasnąć w każdej chwili Uruchomienia
    MozeSieZatrzymac,  \* działanie okna efenix może się nie dokończyć (Zatrzymanie)
    TataWTrakcie,      \* tata zmienia efenix także w trakcie Uruchomienia (granica projektu, ADR 0024)
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneNieCzysciWycenyTaty, WybaczoneZmianaTatyZostaje, WybaczoneZnacznikTylkoNaWycenionym,
    WybaczoneBladTylkoPoZmianieTaty

Zlecenia == 1..LiczbaZlecen
Pozycje == {"A", "B"}
Ilosci == 0..2
\* Wycena Emmetta wpisuje A, a B zostawia pustą; Plik zbiorczy ma ilość w obu i nie przeczy Emmettowi.
Emmett == [p \in Pozycje |-> IF p = "A" THEN 1 ELSE 0]
Plik == [p \in Pozycje |-> 1]
Pusta == [p \in Pozycje |-> 0]
\* Każda pozycja kosztuje 1, więc kwota to suma ilości, a kwota z pliku (AU) to suma Pliku.
Kwota(q) == q["A"] + q["B"]
\* efenix_positions.as_left_after_emmett
JakPoEmmetcie(q) == \A p \in Pozycje : IF Emmett[p] # 0 THEN q[p] = Emmett[p] ELSE q[p] \in {0, Plik[p]}
\* efenix_positions.to_enter: pozycje z ilością w pliku, puste na stronie, po kolei
DoWpisania(q) == {p \in Pozycje : Plik[p] # 0 /\ q[p] = 0}
Pierwsza(S) == IF "A" \in S THEN "A" ELSE "B"

ZnaneZnaleziska == {"przerwanie-po-zaladuj", "slad-nie-zapisany-po-zaladuj", "przerwanie-po-ilosci", "slad-zostal-po-gotowe"}

VARIABLES
    efenix,          \* ilości każdego zlecenia na serwerze efenix
    naDysku,         \* plik śladu: "brak" | "zaladowany" | "gotowe" każdego zlecenia
    wPamieci,        \* ślad w pamięci Uruchomienia (EmmettTrace._orders), czytany raz przy starcie
    proces,          \* "stoi" | "dziala"
    zlecenie,        \* które zlecenie z zakresu przetwarza Uruchomienie
    krok,            \* gdzie w zleceniu jest Uruchomienie
    zWycena,         \* strona przy otwarciu miała kwotę różną od 0 (gałąź „wycena już jest”)
    doWpisania,      \* pozycje, które Uruchomienie jeszcze wpisze
    wpisal,          \* Uruchomienie wpisało już ilość w bieżącym zleceniu
    wynik,           \* wynik zlecenia w tym Uruchomieniu: "brak" | "gotowe" | "blad"
    znacznik,        \* Znacznik efenix w komórce ADRES Pliku zbiorczego
    odTaty,          \* pozycje, których obecna ilość w efenix pochodzi od taty (od jego zmiany do zapisu narzędzia)
    tataZmienial,    \* tata ręcznie zmienił coś w zleceniu
    uruchomienia, zmian, awarieSladu,
    slady,           \* przyczyny znanych znalezisk, które już się zdarzyły
    \* zdarzenia, które łamią obietnice (zmienne historii): {} albo {ślady w chwili zdarzenia}
    czysciTate, nadpisujeTate, zlyZnacznik, bladBezPowodu

vars == <<efenix, naDysku, wPamieci, proces, zlecenie, krok, zWycena, doWpisania, wpisal, wynik, znacznik,
          odTaty, tataZmienial, uruchomienia, zmian, awarieSladu, slady,
          czysciTate, nadpisujeTate, zlyZnacznik, bladBezPowodu>>
historia == <<czysciTate, nadpisujeTate, zlyZnacznik, bladBezPowodu>>

StanySladu == {"brak", "zaladowany", "gotowe"}
Zdarzenie == {{}} \cup {{s} : s \in SUBSET ZnaneZnaleziska}
Zdarz(stare, warunek) == IF stare = {} /\ warunek THEN {slady} ELSE stare

TypeOK ==
    /\ efenix \in [Zlecenia -> [Pozycje -> Ilosci]]
    /\ naDysku \in [Zlecenia -> StanySladu]
    /\ wPamieci \in [Zlecenia -> StanySladu]
    /\ proces \in {"stoi", "dziala"}
    /\ zlecenie \in Zlecenia
    /\ krok \in {"-", "otworz", "emmett", "odczyt", "wpisz", "potwierdz", "koniec", "znaczniki"}
    /\ zWycena \in BOOLEAN /\ wpisal \in BOOLEAN
    /\ doWpisania \subseteq Pozycje
    /\ wynik \in [Zlecenia -> {"brak", "gotowe", "blad"}]
    /\ znacznik \in [Zlecenia -> BOOLEAN]
    /\ odTaty \in [Zlecenia -> SUBSET Pozycje]
    /\ slady \subseteq ZnaneZnaleziska
    /\ czysciTate \in Zdarzenie /\ nadpisujeTate \in Zdarzenie /\ zlyZnacznik \in Zdarzenie /\ bladBezPowodu \in Zdarzenie

Init ==
    /\ efenix = [o \in Zlecenia |-> Pusta]
    /\ naDysku = [o \in Zlecenia |-> "brak"]
    /\ wPamieci = [o \in Zlecenia |-> "brak"]
    /\ proces = "stoi" /\ zlecenie = 1 /\ krok = "-"
    /\ zWycena = FALSE /\ doWpisania = {} /\ wpisal = FALSE
    /\ wynik = [o \in Zlecenia |-> "brak"]
    /\ znacznik = [o \in Zlecenia |-> FALSE]
    /\ odTaty = [o \in Zlecenia |-> {}]
    /\ tataZmienial = [o \in Zlecenia |-> FALSE]
    /\ uruchomienia = 0 /\ zmian = 0 /\ awarieSladu = 0 /\ slady = {}
    /\ czysciTate = {} /\ nadpisujeTate = {} /\ zlyZnacznik = {} /\ bladBezPowodu = {}

\* Nieudany zapis „Emmett załadowany”: plik śladu nie wie, że narzędzie załadowało Emmetta.
NieZapisany(stan) == IF stan = "zaladowany" THEN {"slad-nie-zapisany-po-zaladuj"} ELSE {}

(* EmmettTrace._save: zapis całego śladu z pamięci przez _replace (plik tymczasowy i os.replace). Nieudany zapis    *)
(* usuwa plik (unlink w suppress(OSError)), a gdy i to się nie uda, na dysku zostaje poprzedni ślad.               *)
Zapisz(o, stan) ==
    /\ wPamieci' = [wPamieci EXCEPT ![o] = stan]
    /\ \/ naDysku' = wPamieci' /\ UNCHANGED <<awarieSladu, slady>>
       \/ /\ awarieSladu < MaxAwariiSladu /\ awarieSladu' = awarieSladu + 1
          /\ naDysku' = [z \in Zlecenia |-> "brak"]
          /\ slady' = slady \cup NieZapisany(stan)
       \/ /\ awarieSladu < MaxAwariiSladu /\ awarieSladu' = awarieSladu + 1
          /\ naDysku' = naDysku /\ naDysku # wPamieci'
          /\ slady' = slady \cup NieZapisany(stan)
                   \cup (IF stan = "gotowe" /\ naDysku[o] = "zaladowany" THEN {"slad-zostal-po-gotowe"} ELSE {})

\* price_orders.save: EmmettTrace(trace_file) czyta plik raz, potem zlecenia z zakresu po kolei od pierwszego.
Start ==
    /\ proces = "stoi" /\ uruchomienia < MaxUruchomien
    /\ proces' = "dziala" /\ wPamieci' = naDysku /\ zlecenie' = 1 /\ krok' = "otworz" /\ wpisal' = FALSE
    /\ wynik' = [o \in Zlecenia |-> "brak"]
    /\ UNCHANGED <<efenix, naDysku, zWycena, doWpisania, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, awarieSladu, slady, historia>>

Wynik(w) == wynik' = [wynik EXCEPT ![zlecenie] = w]

\* _outcome: search, open_order i decyzja na otwartej stronie (data wykonania poza modelem).
Otworz ==
    LET q == efenix[zlecenie] IN
    /\ proces = "dziala" /\ krok = "otworz"
    /\ IF Kwota(q) # 0
       THEN IF q = Plik
            \* priced_differently(...) is None: Ready
            THEN Wynik("gotowe") /\ krok' = "koniec" /\ UNCHANGED <<zWycena, doWpisania, bladBezPowodu>>
            \* emmett is None or not as_left_after_emmett(...): OrderError(differs)
            ELSE IF wPamieci[zlecenie] # "zaladowany" \/ ~JakPoEmmetcie(q)
                 THEN /\ Wynik("blad") /\ krok' = "koniec"
                      /\ bladBezPowodu' = Zdarz(bladBezPowodu, ~tataZmienial[zlecenie])
                      /\ UNCHANGED <<zWycena, doWpisania>>
                 \* _after_emmett(order, hit, efenix, file, emmett, opened)
                 ELSE /\ zWycena' = TRUE /\ doWpisania' = DoWpisania(q) /\ krok' = "wpisz"
                      /\ UNCHANGED <<wynik, bladBezPowodu>>
       \* kwota 0: Wycena Emmetta (emmett is None or any(emmett.values()))
       ELSE krok' = "emmett" /\ zWycena' = FALSE /\ UNCHANGED <<wynik, doWpisania, bladBezPowodu>>
    /\ UNCHANGED <<efenix, naDysku, wPamieci, proces, zlecenie, wpisal, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, awarieSladu, slady, czysciTate, nadpisujeTate, zlyZnacznik>>

\* load_emmett: „Załaduj do zlecenia” zapisuje Wycenę Emmetta na serwerze i czyści każdą inną ilość zlecenia.
ZaladujEmmetta ==
    /\ proces = "dziala" /\ krok = "emmett"
    /\ czysciTate' = Zdarz(czysciTate, Kwota(efenix[zlecenie]) # 0)
    /\ efenix' = [efenix EXCEPT ![zlecenie] = Emmett]
    /\ odTaty' = [odTaty EXCEPT ![zlecenie] = {}]
    /\ krok' = "odczyt"
    /\ UNCHANGED <<naDysku, wPamieci, proces, zlecenie, zWycena, doWpisania, wpisal, wynik, znacznik,
                   tataZmienial, uruchomienia, zmian, awarieSladu, slady, nadpisujeTate, zlyZnacznik, bladBezPowodu>>

\* load_emmett czyta stronę po przeładowaniu, potem trace.loaded(number, emmett).
OdczytPoEmmetcie ==
    /\ proces = "dziala" /\ krok = "odczyt"
    /\ Zapisz(zlecenie, "zaladowany")
    /\ doWpisania' = DoWpisania(Emmett) /\ krok' = "wpisz"
    /\ UNCHANGED <<efenix, proces, zlecenie, zWycena, wpisal, wynik, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, historia>>

\* _entered: enter_quantity; efenix zapisuje ilość na serwerze po wyjściu z pola, zanim okno odczyta odpowiedź.
Wpisz ==
    LET p == Pierwsza(doWpisania) IN
    /\ proces = "dziala" /\ krok = "wpisz" /\ doWpisania # {}
    /\ nadpisujeTate' = Zdarz(nadpisujeTate, zWycena /\ odTaty[zlecenie] # {})
    /\ efenix' = [efenix EXCEPT ![zlecenie][p] = Plik[p]]
    /\ odTaty' = [odTaty EXCEPT ![zlecenie] = @ \ {p}]
    /\ doWpisania' = doWpisania \ {p}
    /\ wpisal' = TRUE /\ krok' = "potwierdz"
    /\ UNCHANGED <<naDysku, wPamieci, proces, zlecenie, zWycena, wynik, znacznik, tataZmienial,
                   uruchomienia, zmian, awarieSladu, slady, czysciTate, zlyZnacznik, bladBezPowodu>>

\* enter_quantity: odpowiedź efenix z kwotą; po ostatniej pozycji _entered porównuje kwotę z AU (same_amount).
Potwierdz ==
    /\ proces = "dziala" /\ krok = "potwierdz"
    /\ IF doWpisania = {}
       THEN Wynik(IF efenix[zlecenie] = Plik THEN "gotowe" ELSE "blad") /\ krok' = "koniec"
       ELSE krok' = "wpisz" /\ UNCHANGED wynik
    /\ UNCHANGED <<efenix, naDysku, wPamieci, proces, zlecenie, zWycena, doWpisania, wpisal, znacznik,
                   odTaty, tataZmienial, uruchomienia, zmian, awarieSladu, slady, historia>>

\* _priced: trace.finished(number) po wyniku; zapisuje „gotowe” tylko zlecenia w stanie „Emmett załadowany”.
KoniecZlecenia ==
    /\ proces = "dziala" /\ krok = "koniec"
    /\ IF wPamieci[zlecenie] = "zaladowany"
       THEN Zapisz(zlecenie, "gotowe")
       ELSE UNCHANGED <<wPamieci, naDysku, awarieSladu, slady>>
    /\ IF zlecenie < LiczbaZlecen
       THEN zlecenie' = zlecenie + 1 /\ krok' = "otworz"
       ELSE krok' = "znaczniki" /\ UNCHANGED zlecenie
    /\ wpisal' = FALSE
    /\ UNCHANGED <<efenix, proces, zWycena, doWpisania, wynik, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, historia>>

\* Przerwanie Uruchomienia w kroku krok: która przyczyna znanego znaleziska się zdarzyła.
Przerwanie ==
    slady' = slady \cup (IF krok = "odczyt" THEN {"przerwanie-po-zaladuj"} ELSE {})
                   \cup (IF wpisal THEN {"przerwanie-po-ilosci"} ELSE {})

\* Niedokończone działanie okna (LoggedOut, UnexpectedPage, WindowClosed, EfenixUnreachable): StopError przechodzi
\* przez _priced bez trace.finished, a save() (except StopError) oznacza gotowe zlecenia sprzed niego.
Zatrzymanie ==
    /\ MozeSieZatrzymac /\ proces = "dziala" /\ krok \in {"otworz", "emmett", "odczyt", "wpisz", "potwierdz"}
    /\ Przerwanie
    /\ krok' = "znaczniki"
    /\ UNCHANGED <<efenix, naDysku, wPamieci, proces, zlecenie, zWycena, doWpisania, wpisal, wynik, znacznik,
                   odTaty, tataZmienial, uruchomienia, zmian, awarieSladu, historia>>

\* _mark / efenix_marking.mark_ready: Znacznik efenix w ADRES każdego gotowego zlecenia, potem koniec Uruchomienia.
Znaczniki ==
    /\ proces = "dziala" /\ krok = "znaczniki"
    /\ znacznik' = [o \in Zlecenia |-> znacznik[o] \/ wynik[o] = "gotowe"]
    /\ zlyZnacznik' = Zdarz(zlyZnacznik, \E o \in Zlecenia : znacznik'[o] /\ ~znacznik[o] /\ efenix[o] # Plik)
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, naDysku, wPamieci, zlecenie, zWycena, doWpisania, wpisal, wynik, odTaty,
                   tataZmienial, zmian, awarieSladu, slady, czysciTate, nadpisujeTate, bladBezPowodu>>

\* Centrum gaśnie (brak prądu, zabity proces): pamięć znika, plik śladu i efenix zostają, Znaczników nie ma.
Zgasniecie ==
    /\ MozeZgasnac /\ proces = "dziala"
    /\ Przerwanie
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, naDysku, wPamieci, zlecenie, zWycena, doWpisania, wpisal, wynik, znacznik,
                   odTaty, tataZmienial, zmian, awarieSladu, historia>>

\* Tata, gdy nic nie wycenia (albo także w trakcie, z TataWTrakcie), sam zmienia ilość pozycji zlecenia w efenix.
Tata(o, p, v) ==
    /\ (proces = "stoi" \/ TataWTrakcie) /\ zmian < MaxZmianTaty /\ v # efenix[o][p]
    /\ efenix' = [efenix EXCEPT ![o][p] = v]
    /\ odTaty' = [odTaty EXCEPT ![o] = @ \cup {p}]
    /\ tataZmienial' = [tataZmienial EXCEPT ![o] = TRUE]
    /\ zmian' = zmian + 1
    /\ UNCHANGED <<naDysku, wPamieci, proces, zlecenie, krok, zWycena, doWpisania, wpisal, wynik, znacznik,
                   uruchomienia, awarieSladu, slady, historia>>

\* Ostatnie Uruchomienie się skończyło: nic więcej się nie dzieje.
Koniec ==
    /\ proces = "stoi" /\ uruchomienia = MaxUruchomien
    /\ UNCHANGED vars

Next ==
    \/ Start \/ Otworz \/ ZaladujEmmetta \/ OdczytPoEmmetcie \/ Wpisz \/ Potwierdz \/ KoniecZlecenia
    \/ Zatrzymanie \/ Znaczniki \/ Zgasniecie
    \/ \E o \in Zlecenia, p \in Pozycje, v \in Ilosci : Tata(o, p, v)
    \/ Koniec

Spec == Init /\ [][Next]_vars

(* Obietnice. *)
\* Załadowanie Wyceny Emmetta czyści wycenę zlecenia, więc narzędzie ładuje ją tylko do zlecenia bez żadnej ilości.
NieCzysciWycenyTaty == czysciTate = {}
\* W zleceniu z wyceną, w którym tata sam coś zmienił albo usunął, narzędzie niczego nie wpisuje (także nie dopisuje
\* z powrotem ilości, którą tata usunął): taka strona to błąd „wycena już jest i się różni” bez zmian.
ZmianaTatyZostaje == nadpisujeTate = {}
\* Znacznik efenix stoi tylko przy zleceniu, którego wycena w efenix w chwili oznaczenia równa się plikowi.
ZnacznikTylkoNaWycenionym == zlyZnacznik = {}
\* Błąd „wycena już jest i się różni” tata dostaje tylko przy zleceniu, które sam zmieniał w efenix.
BladTylkoPoZmianieTaty == bladBezPowodu = {}

\* Wariant obietnicy, który pomija jej zdarzenie, gdy w chwili zdarzenia była już przyczyna wybaczonego znaleziska.
Wybaczone(zdarzenie, wybaczone) == \E s \in zdarzenie : s \cap wybaczone # {}
NieCzysciWycenyTatyPozaZnanymi == NieCzysciWycenyTaty \/ Wybaczone(czysciTate, WybaczoneNieCzysciWycenyTaty)
ZmianaTatyZostajePozaZnanymi == ZmianaTatyZostaje \/ Wybaczone(nadpisujeTate, WybaczoneZmianaTatyZostaje)
ZnacznikTylkoNaWycenionymPozaZnanymi ==
    ZnacznikTylkoNaWycenionym \/ Wybaczone(zlyZnacznik, WybaczoneZnacznikTylkoNaWycenionym)
BladTylkoPoZmianieTatyPozaZnanymi == BladTylkoPoZmianieTaty \/ Wybaczone(bladBezPowodu, WybaczoneBladTylkoPoZmianieTaty)
==========================================================================================================
