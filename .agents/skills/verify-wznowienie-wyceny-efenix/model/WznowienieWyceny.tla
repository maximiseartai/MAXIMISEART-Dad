------------------------------ MODULE WznowienieWyceny ------------------------------
(* Wycena w efenix przez kolejne Uruchomienia jednego okresu: Ślad Wyceny Emmetta na dysku taty, Zatrzymanie okna      *)
(* efenix, zgaśnięcie Centrum w każdym miejscu, nieudany zapis śladu i ręczne zmiany taty w efenix między            *)
(* Uruchomieniami. Każda akcja to jeden niepodzielny krok kodu z tabeli w SKILL.md skilla                            *)
(* verify-wznowienie-wyceny-efenix: src/rozliczenia/efenix_pricing.py (price_orders.save, _priced, _outcome,         *)
(* _after_emmett, _entered, _WrittenAhead, _mark) i src/rozliczenia/efenix_emmett_trace.py (EmmettTrace).           *)
EXTENDS Naturals, FiniteSets

CONSTANTS
    LiczbaZlecen,      \* zleceń w zakresie Pliku zbiorczego, przetwarzanych po kolei
    MaxUruchomien,     \* Uruchomień Wyceny w efenix tego okresu
    MaxZmianTaty,      \* ręcznych zmian ilości w efenix przez tatę
    MaxAwariiSladu,    \* nieudanych zapisów pliku śladu (_replace zwraca False)
    MozeZgasnac,       \* Centrum może zgasnąć w każdej chwili Uruchomienia
    MozeSieZatrzymac,  \* działanie okna efenix może się nie dokończyć (Zatrzymanie)
    MozeBrakowacPozycji, \* strona po Wycenie Emmetta może nie mieć pozycji z ilością w pliku (missing_positions)
    TataWTrakcie,      \* tata zmienia efenix także w trakcie Uruchomienia (granica projektu, ADR 0024)
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneNieCzysciWycenyTaty, WybaczoneZmianaTatyZostaje, WybaczoneZnacznikTylkoNaWycenionym,
    WybaczoneBladTylkoPoZmianieTaty

Zlecenia == 1..LiczbaZlecen
Pozycje == {"A", "B", "C"}
Ilosci == 0..2
\* Wycena Emmetta wpisuje A, a B i C zostawia puste; Plik zbiorczy ma ilość w każdej i nie przeczy Emmettowi.
Emmett == [p \in Pozycje |-> IF p = "A" THEN 1 ELSE 0]
Plik == [p \in Pozycje |-> 1]
Pusta == [p \in Pozycje |-> 0]
\* Każda pozycja kosztuje 1, więc kwota to suma ilości, a kwota z pliku (AU) to suma Pliku.
Kwota(q) == q["A"] + q["B"] + q["C"]
(* efenix_positions.as_left_after_emmett: pozycja z ilością Emmetta ma tę ilość, pozycja, w której narzędzie zaczęło   *)
(* wpisywać ilość (E, zapis z wyprzedzeniem), ma ilość, którą narzędzie wpisało (tu ilość pliku), a każda inna jest     *)
(* pusta: ilość w niej wpisał ktoś inny niż narzędzie.                                                                *)
JakPoEmmetcie(q, E) ==
    \A p \in Pozycje : IF Emmett[p] # 0 THEN q[p] = Emmett[p] ELSE IF p \in E THEN q[p] = Plik[p] ELSE q[p] = 0
\* efenix_positions.to_enter: pozycje z ilością w pliku, puste na stronie, po kolei
DoWpisania(q) == {p \in Pozycje : Plik[p] # 0 /\ q[p] = 0}
Pierwsza(S) == IF "A" \in S THEN "A" ELSE IF "B" \in S THEN "B" ELSE "C"

ZnaneZnaleziska ==
    {"przerwanie-po-zaladuj", "slad-nie-zapisany", "przerwanie-przed-zapisem-ilosci", "brak-pozycji-po-emmetcie",
     "tata-wpisal-ilosc-ze-sladu"}

(* Wpis jednego zlecenia w śladzie: „brak”, „zaladowany” (Emmett załadowany) z pozycjami, w których narzędzie zaczęło *)
(* wpisywać ilość (``entering``), albo „gotowe”.                                                                     *)
StanySladu == {"brak", "zaladowany", "gotowe"}
Wpisy == [stan : StanySladu, wpisuje : SUBSET Pozycje]
Brak == [stan |-> "brak", wpisuje |-> {}]
Gotowe == [stan |-> "gotowe", wpisuje |-> {}]
Zaladowany(E) == [stan |-> "zaladowany", wpisuje |-> E]

VARIABLES
    efenix,          \* ilości każdego zlecenia na serwerze efenix
    naDysku,         \* plik śladu: wpis każdego zlecenia
    wPamieci,        \* ślad w pamięci Uruchomienia (EmmettTrace._orders), czytany raz przy starcie
    proces,          \* "stoi" | "dziala"
    zlecenie,        \* które zlecenie z zakresu przetwarza Uruchomienie
    krok,            \* gdzie w zleceniu jest Uruchomienie
    zWycena,         \* strona przy otwarciu miała kwotę różną od 0 (gałąź „wycena już jest”)
    doWpisania,      \* pozycje, które Uruchomienie jeszcze wpisze
    wynik,           \* wynik zlecenia w tym Uruchomieniu: "brak" | "gotowe" | "blad"
    znacznik,        \* Znacznik efenix w komórce ADRES Pliku zbiorczego
    odTaty,          \* pozycje, których obecna ilość w efenix pochodzi od taty (od jego zmiany do zapisu narzędzia)
    tataZmienial,    \* tata ręcznie zmienił coś w zleceniu
    uruchomienia, zmian, awarieSladu,
    slady,           \* przyczyny znanych znalezisk, które już się zdarzyły, osobno dla każdego zlecenia
    \* zdarzenia, które łamią obietnice (zmienne historii): {} albo {ślady zlecenia w chwili zdarzenia}
    czysciTate, nadpisujeTate, zlyZnacznik, bladBezPowodu

vars == <<efenix, naDysku, wPamieci, proces, zlecenie, krok, zWycena, doWpisania, wynik, znacznik,
          odTaty, tataZmienial, uruchomienia, zmian, awarieSladu, slady,
          czysciTate, nadpisujeTate, zlyZnacznik, bladBezPowodu>>
historia == <<czysciTate, nadpisujeTate, zlyZnacznik, bladBezPowodu>>

Zdarzenie == {{}} \cup {{s} : s \in SUBSET ZnaneZnaleziska}
Zdarz(stare, warunek) == IF stare = {} /\ warunek THEN {slady[zlecenie]} ELSE stare

TypeOK ==
    /\ efenix \in [Zlecenia -> [Pozycje -> Ilosci]]
    /\ naDysku \in [Zlecenia -> Wpisy]
    /\ wPamieci \in [Zlecenia -> Wpisy]
    /\ proces \in {"stoi", "dziala"}
    /\ zlecenie \in Zlecenia
    /\ krok \in {"-", "otworz", "emmett", "odczyt", "zapowiedz", "wpisz", "potwierdz", "koniec", "znaczniki"}
    /\ zWycena \in BOOLEAN
    /\ doWpisania \subseteq Pozycje
    /\ wynik \in [Zlecenia -> {"brak", "gotowe", "blad"}]
    /\ znacznik \in [Zlecenia -> BOOLEAN]
    /\ odTaty \in [Zlecenia -> SUBSET Pozycje]
    /\ slady \in [Zlecenia -> SUBSET ZnaneZnaleziska]
    /\ czysciTate \in Zdarzenie /\ nadpisujeTate \in Zdarzenie /\ zlyZnacznik \in Zdarzenie /\ bladBezPowodu \in Zdarzenie

Init ==
    /\ efenix = [o \in Zlecenia |-> Pusta]
    /\ naDysku = [o \in Zlecenia |-> Brak]
    /\ wPamieci = [o \in Zlecenia |-> Brak]
    /\ proces = "stoi" /\ zlecenie = 1 /\ krok = "-"
    /\ zWycena = FALSE /\ doWpisania = {}
    /\ wynik = [o \in Zlecenia |-> "brak"]
    /\ znacznik = [o \in Zlecenia |-> FALSE]
    /\ odTaty = [o \in Zlecenia |-> {}]
    /\ tataZmienial = [o \in Zlecenia |-> FALSE]
    /\ uruchomienia = 0 /\ zmian = 0 /\ awarieSladu = 0 /\ slady = [o \in Zlecenia |-> {}]
    /\ czysciTate = {} /\ nadpisujeTate = {} /\ zlyZnacznik = {} /\ bladBezPowodu = {}

(* EmmettTrace._save: zapis całego śladu z pamięci przez _replace (plik tymczasowy i os.replace); zwraca, czy się     *)
(* udał. Nieudany zapis usuwa plik (unlink w suppress(OSError)), a gdy i to się nie uda, na dysku zostaje poprzedni    *)
(* ślad. Zlecenie, którego ostatni stan „Emmett załadowany” nie trafił przez to na dysk, dostaje przyczynę             *)
(* „slad-nie-zapisany”.                                                                                               *)
Udany(o, wpis) ==
    /\ wPamieci' = [wPamieci EXCEPT ![o] = wpis]
    /\ naDysku' = wPamieci'
    /\ UNCHANGED <<awarieSladu, slady>>
Nieudany(o, wpis) ==
    /\ awarieSladu < MaxAwariiSladu /\ awarieSladu' = awarieSladu + 1
    /\ wPamieci' = [wPamieci EXCEPT ![o] = wpis]
    /\ \/ naDysku' = [z \in Zlecenia |-> Brak]
       \/ naDysku' = naDysku /\ naDysku # wPamieci'
    /\ slady' = [z \in Zlecenia |->
                    slady[z] \cup (IF wPamieci'[z].stan = "zaladowany" /\ naDysku'[z] # wPamieci'[z]
                                   THEN {"slad-nie-zapisany"} ELSE {})]
Zapisz(o, wpis) == Udany(o, wpis) \/ Nieudany(o, wpis)

\* price_orders.save: EmmettTrace(trace_file) czyta plik raz, potem zlecenia z zakresu po kolei od pierwszego.
Start ==
    /\ proces = "stoi" /\ uruchomienia < MaxUruchomien
    /\ proces' = "dziala" /\ wPamieci' = naDysku /\ zlecenie' = 1 /\ krok' = "otworz"
    /\ wynik' = [o \in Zlecenia |-> "brak"]
    /\ UNCHANGED <<efenix, naDysku, zWycena, doWpisania, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, awarieSladu, slady, historia>>

Wynik(w) == wynik' = [wynik EXCEPT ![zlecenie] = w]

\* _outcome: search, open_order i decyzja na otwartej stronie (data wykonania poza modelem).
Otworz ==
    LET q == efenix[zlecenie]
        w == wPamieci[zlecenie] IN
    /\ proces = "dziala" /\ krok = "otworz"
    /\ IF Kwota(q) # 0
       THEN IF q = Plik
            \* priced_differently(...) is None: Ready
            THEN Wynik("gotowe") /\ krok' = "koniec" /\ UNCHANGED <<zWycena, doWpisania, bladBezPowodu>>
            \* emmett is None or not as_left_after_emmett(file, emmett, trace.entered(number), ...): OrderError(differs)
            ELSE IF w.stan # "zaladowany" \/ ~JakPoEmmetcie(q, w.wpisuje)
                 THEN /\ Wynik("blad") /\ krok' = "koniec"
                      /\ bladBezPowodu' = Zdarz(bladBezPowodu, ~tataZmienial[zlecenie])
                      /\ UNCHANGED <<zWycena, doWpisania>>
                 \* _after_emmett(order, hit, efenix, file, emmett, opened, ...)
                 ELSE /\ zWycena' = TRUE /\ doWpisania' = DoWpisania(q) /\ krok' = "zapowiedz"
                      /\ UNCHANGED <<wynik, bladBezPowodu>>
       \* kwota 0: Wycena Emmetta (emmett is None or any(emmett.values()))
       ELSE krok' = "emmett" /\ zWycena' = FALSE /\ UNCHANGED <<wynik, doWpisania, bladBezPowodu>>
    /\ UNCHANGED <<efenix, naDysku, wPamieci, proces, zlecenie, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, awarieSladu, slady, czysciTate, nadpisujeTate, zlyZnacznik>>

\* load_emmett: „Załaduj do zlecenia” zapisuje Wycenę Emmetta na serwerze i czyści każdą inną ilość zlecenia.
ZaladujEmmetta ==
    /\ proces = "dziala" /\ krok = "emmett"
    /\ czysciTate' = Zdarz(czysciTate, Kwota(efenix[zlecenie]) # 0)
    /\ efenix' = [efenix EXCEPT ![zlecenie] = Emmett]
    /\ odTaty' = [odTaty EXCEPT ![zlecenie] = {}]
    /\ krok' = "odczyt"
    /\ UNCHANGED <<naDysku, wPamieci, proces, zlecenie, zWycena, doWpisania, wynik, znacznik,
                   tataZmienial, uruchomienia, zmian, awarieSladu, slady, nadpisujeTate, zlyZnacznik, bladBezPowodu>>

\* load_emmett czyta stronę po przeładowaniu, potem trace.loaded(number, emmett); nieudany zapis nie zatrzymuje.
OdczytPoEmmetcie ==
    /\ proces = "dziala" /\ krok = "odczyt"
    /\ Zapisz(zlecenie, Zaladowany({}))
    /\ doWpisania' = DoWpisania(Emmett) /\ krok' = "zapowiedz"
    /\ UNCHANGED <<efenix, proces, zlecenie, zWycena, wynik, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, historia>>

\* _outcome: strona po Wycenie Emmetta bez pozycji z ilością w pliku (missing_positions, PageRead.AFTER_EMMETT) to błąd
\* zlecenia przed trace.loaded, więc Wycena Emmetta zostaje w efenix bez śladu.
BrakPozycji ==
    /\ MozeBrakowacPozycji /\ proces = "dziala" /\ krok = "odczyt"
    /\ Wynik("blad") /\ krok' = "koniec"
    /\ slady' = [slady EXCEPT ![zlecenie] = @ \cup {"brak-pozycji-po-emmetcie"}]
    /\ UNCHANGED <<efenix, naDysku, wPamieci, proces, zlecenie, zWycena, doWpisania, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, awarieSladu, historia>>

(* _WrittenAhead.enter_quantity: po przerwie tempa ludzkiego trace.entering(number, position, quantity), zapis z     *)
(* wyprzedzeniem pozycji, którą okno zaraz wpisze. Gdy się nie uda, okno nie wpisuje ilości (_TraceNotSaved), a        *)
(* _efenix_stops zatrzymuje Wycenę (StopError, emmett_trace_not_saved), a save() oznacza gotowe zlecenia sprzed niego. *)
Zapowiedz ==
    LET p == Pierwsza(doWpisania)
        wpis == Zaladowany(wPamieci[zlecenie].wpisuje \cup {p}) IN
    /\ proces = "dziala" /\ krok = "zapowiedz" /\ doWpisania # {}
    /\ \/ Udany(zlecenie, wpis) /\ krok' = "wpisz"
       \/ Nieudany(zlecenie, wpis) /\ krok' = "znaczniki"
    /\ UNCHANGED <<efenix, proces, zlecenie, zWycena, doWpisania, wynik, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, historia>>

\* _WrittenAhead.enter_quantity: enter_quantity okna; efenix zapisuje ilość na serwerze po wyjściu z pola, zanim okno odczyta odpowiedź.
Wpisz ==
    LET p == Pierwsza(doWpisania) IN
    /\ proces = "dziala" /\ krok = "wpisz"
    /\ nadpisujeTate' = Zdarz(nadpisujeTate, zWycena /\ odTaty[zlecenie] # {})
    /\ efenix' = [efenix EXCEPT ![zlecenie][p] = Plik[p]]
    /\ odTaty' = [odTaty EXCEPT ![zlecenie] = @ \ {p}]
    /\ doWpisania' = doWpisania \ {p}
    /\ krok' = "potwierdz"
    /\ UNCHANGED <<naDysku, wPamieci, proces, zlecenie, zWycena, wynik, znacznik, tataZmienial,
                   uruchomienia, zmian, awarieSladu, slady, czysciTate, zlyZnacznik, bladBezPowodu>>

(* _WrittenAhead.enter_quantity: okno zgłasza LoggedOut (odpowiedź zapisu z wynikiem nok albo przekierowana na       *)
(* logowanie), więc efenix ilości nie zapisał; trace.not_entered(number, position) wycofuje pozycję ze śladu, a       *)
(* LoggedOut przechodzi przez _priced bez trace.finished, a _efenix_stops w save() daje z niego StopError.           *)
Odmowa ==
    /\ MozeSieZatrzymac /\ proces = "dziala" /\ krok = "wpisz"
    /\ Zapisz(zlecenie, Zaladowany(wPamieci[zlecenie].wpisuje \ {Pierwsza(doWpisania)}))
    /\ krok' = "znaczniki"
    /\ UNCHANGED <<efenix, proces, zlecenie, zWycena, doWpisania, wynik, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, historia>>

\* enter_quantity: odpowiedź efenix z kwotą; po ostatniej pozycji _entered porównuje kwotę z AU (same_amount).
Potwierdz ==
    /\ proces = "dziala" /\ krok = "potwierdz"
    /\ IF doWpisania = {}
       THEN Wynik(IF efenix[zlecenie] = Plik THEN "gotowe" ELSE "blad") /\ krok' = "koniec"
       ELSE krok' = "zapowiedz" /\ UNCHANGED wynik
    /\ UNCHANGED <<efenix, naDysku, wPamieci, proces, zlecenie, zWycena, doWpisania, znacznik,
                   odTaty, tataZmienial, uruchomienia, zmian, awarieSladu, slady, historia>>

\* _priced: trace.finished(number) po wyniku; zapisuje „gotowe” tylko zlecenia w stanie „Emmett załadowany”.
KoniecZlecenia ==
    /\ proces = "dziala" /\ krok = "koniec"
    /\ IF wPamieci[zlecenie].stan = "zaladowany"
       THEN Zapisz(zlecenie, Gotowe)
       ELSE UNCHANGED <<wPamieci, naDysku, awarieSladu, slady>>
    /\ IF zlecenie < LiczbaZlecen
       THEN zlecenie' = zlecenie + 1 /\ krok' = "otworz"
       ELSE krok' = "znaczniki" /\ UNCHANGED zlecenie
    /\ UNCHANGED <<efenix, proces, zWycena, doWpisania, wynik, znacznik, odTaty, tataZmienial,
                   uruchomienia, zmian, historia>>

\* Przerwanie Uruchomienia w kroku krok: która przyczyna znanego znaleziska się zdarzyła w bieżącym zleceniu.
Przerwanie ==
    slady' = [slady EXCEPT ![zlecenie] = @ \cup (IF krok = "odczyt" THEN {"przerwanie-po-zaladuj"} ELSE {})
                                         \cup (IF krok = "wpisz" THEN {"przerwanie-przed-zapisem-ilosci"} ELSE {})]

\* Niedokończone działanie okna (LoggedOut, UnexpectedPage, WindowClosed, EfenixUnreachable): wyjątek okna przechodzi
\* przez _priced bez trace.finished, _efenix_stops w save() daje z niego StopError, a save() (except StopError)
\* oznacza gotowe zlecenia sprzed niego.
Zatrzymanie ==
    /\ MozeSieZatrzymac /\ proces = "dziala" /\ krok \in {"otworz", "emmett", "odczyt", "wpisz", "potwierdz"}
    /\ Przerwanie
    /\ krok' = "znaczniki"
    /\ UNCHANGED <<efenix, naDysku, wPamieci, proces, zlecenie, zWycena, doWpisania, wynik, znacznik,
                   odTaty, tataZmienial, uruchomienia, zmian, awarieSladu, historia>>

\* _mark / efenix_marking.mark_ready: Znacznik efenix w ADRES każdego gotowego zlecenia, potem koniec Uruchomienia.
Zle(o) == znacznik'[o] /\ ~znacznik[o] /\ efenix[o] # Plik
Znaczniki ==
    /\ proces = "dziala" /\ krok = "znaczniki"
    /\ znacznik' = [o \in Zlecenia |-> znacznik[o] \/ wynik[o] = "gotowe"]
    /\ zlyZnacznik' = IF zlyZnacznik = {} /\ \E o \in Zlecenia : Zle(o)
                      THEN {slady[CHOOSE o \in Zlecenia : Zle(o)]} ELSE zlyZnacznik
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, naDysku, wPamieci, zlecenie, zWycena, doWpisania, wynik, odTaty,
                   tataZmienial, zmian, awarieSladu, slady, czysciTate, nadpisujeTate, bladBezPowodu>>

\* Centrum gaśnie (brak prądu, zabity proces): pamięć znika, plik śladu i efenix zostają, Znaczników nie ma.
Zgasniecie ==
    /\ MozeZgasnac /\ proces = "dziala"
    /\ Przerwanie
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, naDysku, wPamieci, zlecenie, zWycena, doWpisania, wynik, znacznik,
                   odTaty, tataZmienial, zmian, awarieSladu, historia>>

(* Tata, gdy nic nie wycenia (albo także w trakcie, z TataWTrakcie), sam zmienia ilość pozycji zlecenia w efenix.     *)
(* Ilość, którą narzędzie zaczęło wpisywać w tej pozycji (zapis z wyprzedzeniem na dysku), wpisana przez tatę daje     *)
(* stronę taką jak po zapisie narzędzia: przyczyna „tata-wpisal-ilosc-ze-sladu”.                                      *)
Tata(o, p, v) ==
    /\ (proces = "stoi" \/ TataWTrakcie) /\ zmian < MaxZmianTaty /\ v # efenix[o][p]
    /\ efenix' = [efenix EXCEPT ![o][p] = v]
    /\ odTaty' = [odTaty EXCEPT ![o] = @ \cup {p}]
    /\ tataZmienial' = [tataZmienial EXCEPT ![o] = TRUE]
    /\ zmian' = zmian + 1
    /\ slady' = [slady EXCEPT ![o] = @ \cup (IF p \in naDysku[o].wpisuje /\ v = Plik[p] THEN {"tata-wpisal-ilosc-ze-sladu"} ELSE {})]
    /\ UNCHANGED <<naDysku, wPamieci, proces, zlecenie, krok, zWycena, doWpisania, wynik, znacznik,
                   uruchomienia, awarieSladu, historia>>

\* Ostatnie Uruchomienie się skończyło: nic więcej się nie dzieje.
Koniec ==
    /\ proces = "stoi" /\ uruchomienia = MaxUruchomien
    /\ UNCHANGED vars

Next ==
    \/ Start \/ Otworz \/ ZaladujEmmetta \/ OdczytPoEmmetcie \/ BrakPozycji \/ Zapowiedz \/ Wpisz \/ Odmowa
    \/ Potwierdz \/ KoniecZlecenia \/ Zatrzymanie \/ Znaczniki \/ Zgasniecie
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
