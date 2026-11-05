------------------------------ MODULE WznowienieWyceny ------------------------------
(* Wycena w efenix przez kolejne Uruchomienia jednego okresu: Zatrzymanie okna efenix, zgaśnięcie Centrum w każdym    *)
(* miejscu i ręczne zmiany taty w efenix między Uruchomieniami. Proces dokańcza każde zlecenie do Pliku zbiorczego     *)
(* tylko w górę (ADR 0026). Każda akcja to jeden niepodzielny krok kodu z tabeli w SKILL.md skilla                    *)
(* verify-wznowienie-wyceny-efenix: src/rozliczenia/efenix_pricing.py (price_orders.save, _outcome, _completed, _mark) *)
(* i src/rozliczenia/efenix_positions.py (completion).                                                               *)
EXTENDS Naturals, FiniteSets

CONSTANTS
    LiczbaZlecen,      \* zleceń w zakresie Pliku zbiorczego, przetwarzanych po kolei
    MaxUruchomien,     \* Uruchomień Wyceny w efenix tego okresu
    MaxZmianTaty,      \* ręcznych zmian ilości w efenix przez tatę
    MozeZgasnac,       \* Centrum może zgasnąć w każdej chwili Uruchomienia
    MozeSieZatrzymac,  \* działanie okna efenix może się nie dokończyć (Zatrzymanie)
    MozeBrakowacPozycji, \* strona po Wycenie Emmetta może nie mieć pozycji z ilością w pliku (missing_positions)
    TataWTrakcie,      \* tata zmienia efenix także w trakcie Uruchomienia (granica projektu, ADR 0024)
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneNieCzysciWycenyTaty, WybaczoneNieObnizaIlosci, WybaczoneZmianaTatyZostaje,
    WybaczoneZnacznikTylkoNaWycenionym, WybaczoneBladTylkoPoZmianieTaty

Zlecenia == 1..LiczbaZlecen
Pozycje == {"A", "B", "C"}
Ilosci == 0..2
(* Plik zbiorczy ma ilość w każdej pozycji, w B 2. Wycena Emmetta wpisuje A jak plik i B o 1 mniej niż plik (Emmett    *)
(* liczy w S tylko dekodery, #960), a C zostawia pustą: proces wpisuje B i C z pliku. Ilość większą niż plik w efenix   *)
(* daje tylko tata.                                                                                                  *)
Plik == [p \in Pozycje |-> IF p = "B" THEN 2 ELSE 1]
Emmett == [p \in Pozycje |-> IF p = "C" THEN 0 ELSE 1]
Pusta == [p \in Pozycje |-> 0]
\* Każda pozycja kosztuje 1, więc kwota to suma ilości, a kwota z pliku (AU) to suma Pliku.
Kwota(q) == q["A"] + q["B"] + q["C"]
\* efenix_positions.completion: to_enter (pozycje, w których strona ma mniej niż plik) i excess (więcej niż plik).
DoWpisania(q) == {p \in Pozycje : q[p] < Plik[p]}
Nadmiar(q) == {p \in Pozycje : q[p] > Plik[p]}
Pierwsza(S) == IF "A" \in S THEN "A" ELSE IF "B" \in S THEN "B" ELSE "C"
\* _completed po ostatniej ilości: Ostrzeżenie Emmetta przy nadmiarze, a bez niego gotowe przy kwocie równej AU.
WynikDokonczenia(q) == IF Nadmiar(q) # {} THEN "ostrzezenie" ELSE IF Kwota(q) = Kwota(Plik) THEN "gotowe" ELSE "blad"
\* Wynik, którego obietnice oczekują od zlecenia z ilościami q po dokończeniu do pliku tylko w górę.
Oczekiwany(q) == IF Nadmiar(q) # {} THEN "ostrzezenie" ELSE "gotowe"

ZnaneZnaleziska == {"brak-pozycji-po-emmetcie"}

VARIABLES
    efenix,          \* ilości każdego zlecenia na serwerze efenix
    proces,          \* "stoi" | "dziala"
    zlecenie,        \* które zlecenie z zakresu przetwarza Uruchomienie
    krok,            \* gdzie w zleceniu jest Uruchomienie
    doWpisania,      \* pozycje, które Uruchomienie jeszcze wpisze
    wynik,           \* wynik zlecenia w tym Uruchomieniu: "brak" | "gotowe" | "blad" | "ostrzezenie"
    znacznik,        \* Znacznik efenix w komórce ADRES Pliku zbiorczego
    tataZmienial,    \* tata ręcznie zmienił coś w zleceniu
    uruchomienia, zmian,
    slady,           \* przyczyny znanych znalezisk, które już się zdarzyły, osobno dla każdego zlecenia
    \* zdarzenia, które łamią obietnice (zmienne historii): {} albo {ślady zlecenia w chwili zdarzenia}
    czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu

vars == <<efenix, proces, zlecenie, krok, doWpisania, wynik, znacznik, tataZmienial, uruchomienia, zmian, slady,
          czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu>>
historia == <<czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu>>

Zdarzenie == {{}} \cup {{s} : s \in SUBSET ZnaneZnaleziska}
Zdarz(stare, warunek) == IF stare = {} /\ warunek THEN {slady[zlecenie]} ELSE stare

TypeOK ==
    /\ efenix \in [Zlecenia -> [Pozycje -> Ilosci]]
    /\ proces \in {"stoi", "dziala"}
    /\ zlecenie \in Zlecenia
    /\ krok \in {"-", "otworz", "emmett", "odczyt", "wpisz", "potwierdz", "koniec", "znaczniki"}
    /\ doWpisania \subseteq Pozycje
    /\ wynik \in [Zlecenia -> {"brak", "gotowe", "blad", "ostrzezenie"}]
    /\ znacznik \in [Zlecenia -> BOOLEAN]
    /\ tataZmienial \in [Zlecenia -> BOOLEAN]
    /\ slady \in [Zlecenia -> SUBSET ZnaneZnaleziska]
    /\ czysciTate \in Zdarzenie /\ obniza \in Zdarzenie /\ zlyWynikPoTacie \in Zdarzenie
    /\ zlyZnacznik \in Zdarzenie /\ bladBezPowodu \in Zdarzenie

Init ==
    /\ efenix = [o \in Zlecenia |-> Pusta]
    /\ proces = "stoi" /\ zlecenie = 1 /\ krok = "-" /\ doWpisania = {}
    /\ wynik = [o \in Zlecenia |-> "brak"]
    /\ znacznik = [o \in Zlecenia |-> FALSE]
    /\ tataZmienial = [o \in Zlecenia |-> FALSE]
    /\ uruchomienia = 0 /\ zmian = 0 /\ slady = [o \in Zlecenia |-> {}]
    /\ czysciTate = {} /\ obniza = {} /\ zlyWynikPoTacie = {} /\ zlyZnacznik = {} /\ bladBezPowodu = {}

\* price_orders.save: zlecenia z zakresu po kolei od pierwszego.
Start ==
    /\ proces = "stoi" /\ uruchomienia < MaxUruchomien
    /\ proces' = "dziala" /\ zlecenie' = 1 /\ krok' = "otworz"
    /\ wynik' = [o \in Zlecenia |-> "brak"]
    /\ UNCHANGED <<efenix, doWpisania, znacznik, tataZmienial, uruchomienia, zmian, slady, historia>>

(* Wynik w zlecenia w tym Uruchomieniu, przy ilościach q w efenix. Zlecenie, które tata zmieniał, kończy się          *)
(* Ostrzeżeniem Emmetta, gdy ma ilość większą niż plik, a w przeciwnym razie jest gotowe (ZmianaTatyZostaje); zlecenie, *)
(* którego tata nie zmieniał, jest gotowe (BladTylkoPoZmianieTaty).                                                   *)
Wynik(w, q) ==
    /\ wynik' = [wynik EXCEPT ![zlecenie] = w]
    /\ zlyWynikPoTacie' = Zdarz(zlyWynikPoTacie, tataZmienial[zlecenie] /\ w # Oczekiwany(q))
    /\ bladBezPowodu' = Zdarz(bladBezPowodu, ~tataZmienial[zlecenie] /\ w # "gotowe")

(* _completed na stronie z ilościami q: completion daje pozycje do wpisania; bez nich wynik od razu (kwota strony),   *)
(* a z nimi pierwsza ilość.                                                                                          *)
Dokoncz(q) ==
    /\ doWpisania' = DoWpisania(q)
    /\ IF DoWpisania(q) = {}
       THEN Wynik(WynikDokonczenia(q), q) /\ krok' = "koniec"
       ELSE krok' = "wpisz" /\ UNCHANGED <<wynik, zlyWynikPoTacie, bladBezPowodu>>

(* _outcome: search, listing, open_order, przy pustej dacie wykonania _dated na stronie z ilościami albo bez (data     *)
(* poza modelem: _dated nie zmienia ilości), i decyzja na otwartej stronie: strona bez żadnej ilości                   *)
(* (not any(opened.quantities.values())) idzie do Wyceny Emmetta, a strona z ilościami prosto do _completed, bez       *)
(* Emmetta.                                                                                                           *)
Otworz ==
    LET q == efenix[zlecenie] IN
    /\ proces = "dziala" /\ krok = "otworz"
    /\ IF q # Pusta
       THEN Dokoncz(q)
       ELSE krok' = "emmett" /\ UNCHANGED <<wynik, doWpisania, zlyWynikPoTacie, bladBezPowodu>>
    /\ UNCHANGED <<efenix, proces, zlecenie, znacznik, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyZnacznik>>

\* load_emmett: „Załaduj do zlecenia” zapisuje Wycenę Emmetta na serwerze i czyści każdą inną ilość zlecenia.
ZaladujEmmetta ==
    /\ proces = "dziala" /\ krok = "emmett"
    /\ czysciTate' = Zdarz(czysciTate, efenix[zlecenie] # Pusta)
    /\ obniza' = Zdarz(obniza, \E p \in Pozycje : Emmett[p] < efenix[zlecenie][p])
    /\ efenix' = [efenix EXCEPT ![zlecenie] = Emmett]
    /\ krok' = "odczyt"
    /\ UNCHANGED <<proces, zlecenie, doWpisania, wynik, znacznik, tataZmienial, uruchomienia, zmian, slady,
                   zlyWynikPoTacie, zlyZnacznik, bladBezPowodu>>

\* load_emmett czyta stronę po przeładowaniu, potem _completed na niej (completion od ilości Emmetta).
OdczytPoEmmetcie ==
    /\ proces = "dziala" /\ krok = "odczyt"
    /\ Dokoncz(efenix[zlecenie])
    /\ UNCHANGED <<efenix, proces, zlecenie, znacznik, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyZnacznik>>

\* _outcome: strona po Wycenie Emmetta bez pozycji z ilością w pliku (missing_positions, PageRead.AFTER_EMMETT) to błąd
\* zlecenia, a Wycena Emmetta zostaje w efenix.
BrakPozycji ==
    /\ MozeBrakowacPozycji /\ proces = "dziala" /\ krok = "odczyt"
    /\ slady' = [slady EXCEPT ![zlecenie] = @ \cup {"brak-pozycji-po-emmetcie"}]
    /\ wynik' = [wynik EXCEPT ![zlecenie] = "blad"]
    /\ bladBezPowodu' = IF bladBezPowodu = {} /\ ~tataZmienial[zlecenie] THEN {slady'[zlecenie]} ELSE bladBezPowodu
    /\ krok' = "koniec"
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, znacznik, tataZmienial, uruchomienia, zmian,
                   czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik>>

\* _completed: enter_quantity okna z ilością pliku; efenix zapisuje ją na serwerze po wyjściu z pola, zanim okno odczyta odpowiedź.
Wpisz ==
    LET p == Pierwsza(doWpisania) IN
    /\ proces = "dziala" /\ krok = "wpisz"
    /\ obniza' = Zdarz(obniza, Plik[p] < efenix[zlecenie][p])
    /\ efenix' = [efenix EXCEPT ![zlecenie][p] = Plik[p]]
    /\ doWpisania' = doWpisania \ {p}
    /\ krok' = "potwierdz"
    /\ UNCHANGED <<proces, zlecenie, wynik, znacznik, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu>>

\* enter_quantity: odpowiedź efenix z kwotą; po ostatniej pozycji _completed daje wynik (excess, same_amount).
Potwierdz ==
    /\ proces = "dziala" /\ krok = "potwierdz"
    /\ IF doWpisania = {}
       THEN Wynik(WynikDokonczenia(efenix[zlecenie]), efenix[zlecenie]) /\ krok' = "koniec"
       ELSE krok' = "wpisz" /\ UNCHANGED <<wynik, zlyWynikPoTacie, bladBezPowodu>>
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, znacznik, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyZnacznik>>

\* save: wynik zlecenia trafia do wyników i dziennika, potem następne zlecenie.
KoniecZlecenia ==
    /\ proces = "dziala" /\ krok = "koniec"
    /\ IF zlecenie < LiczbaZlecen
       THEN zlecenie' = zlecenie + 1 /\ krok' = "otworz"
       ELSE krok' = "znaczniki" /\ UNCHANGED zlecenie
    /\ UNCHANGED <<efenix, proces, doWpisania, wynik, znacznik, tataZmienial, uruchomienia, zmian, slady, historia>>

(* Niedokończone działanie okna (LoggedOut, UnexpectedPage, WindowClosed, EfenixUnreachable), także wylogowanie przy   *)
(* zapisie ilości, której efenix nie zapisał (krok "wpisz"), i odpowiedź, której okno nie odczytało po zapisie (krok    *)
(* "potwierdz"): wyjątek okna przechodzi przez _outcome, _efenix_stops w save() daje z niego StopError, a save()        *)
(* (except StopError) oznacza gotowe zlecenia sprzed niego.                                                           *)
Zatrzymanie ==
    /\ MozeSieZatrzymac /\ proces = "dziala" /\ krok \in {"otworz", "emmett", "odczyt", "wpisz", "potwierdz"}
    /\ krok' = "znaczniki"
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, wynik, znacznik, tataZmienial, uruchomienia, zmian, slady,
                   historia>>

\* _mark / efenix_marking.mark_ready: Znacznik efenix w ADRES każdego gotowego zlecenia, potem koniec Uruchomienia.
Zle(o) == znacznik'[o] /\ ~znacznik[o] /\ efenix[o] # Plik
Znaczniki ==
    /\ proces = "dziala" /\ krok = "znaczniki"
    /\ znacznik' = [o \in Zlecenia |-> znacznik[o] \/ wynik[o] = "gotowe"]
    /\ zlyZnacznik' = IF zlyZnacznik = {} /\ \E o \in Zlecenia : Zle(o)
                      THEN {slady[CHOOSE o \in Zlecenia : Zle(o)]} ELSE zlyZnacznik
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, zlecenie, doWpisania, wynik, tataZmienial, zmian, slady,
                   czysciTate, obniza, zlyWynikPoTacie, bladBezPowodu>>

\* Centrum gaśnie (brak prądu, zabity proces): pamięć znika, efenix zostaje, Znaczników nie ma.
Zgasniecie ==
    /\ MozeZgasnac /\ proces = "dziala"
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, zlecenie, doWpisania, wynik, znacznik, tataZmienial, zmian, slady, historia>>

\* Tata, gdy nic nie wycenia (albo także w trakcie, z TataWTrakcie), sam zmienia ilość pozycji zlecenia w efenix.
Tata(o, p, v) ==
    /\ (proces = "stoi" \/ TataWTrakcie) /\ zmian < MaxZmianTaty /\ v # efenix[o][p]
    /\ efenix' = [efenix EXCEPT ![o][p] = v]
    /\ tataZmienial' = [tataZmienial EXCEPT ![o] = TRUE]
    /\ zmian' = zmian + 1
    /\ UNCHANGED <<proces, zlecenie, krok, doWpisania, wynik, znacznik, uruchomienia, slady, historia>>

\* Ostatnie Uruchomienie się skończyło: nic więcej się nie dzieje.
Koniec ==
    /\ proces = "stoi" /\ uruchomienia = MaxUruchomien
    /\ UNCHANGED vars

Next ==
    \/ Start \/ Otworz \/ ZaladujEmmetta \/ OdczytPoEmmetcie \/ BrakPozycji \/ Wpisz \/ Potwierdz \/ KoniecZlecenia
    \/ Zatrzymanie \/ Znaczniki \/ Zgasniecie
    \/ \E o \in Zlecenia, p \in Pozycje, v \in Ilosci : Tata(o, p, v)
    \/ Koniec

Spec == Init /\ [][Next]_vars

(* Obietnice. *)
\* Załadowanie Wyceny Emmetta czyści wycenę zlecenia, więc narzędzie ładuje ją tylko do zlecenia bez żadnej ilości.
NieCzysciWycenyTaty == czysciTate = {}
\* Narzędzie nigdy nie obniża ani nie czyści ilości w efenix: każda ilość, którą wpisuje, jest co najmniej taka jak ta,
\* którą zastępuje, także ilość Emmetta i ilość taty.
NieObnizaIlosci == obniza = {}
\* Zlecenie, w którym tata coś zmienił ręcznie, kończy się Ostrzeżeniem Emmetta, gdy ma ilość większą niż plik (ta
\* ilość zostaje), a w przeciwnym razie jest gotowe: ilość taty mniejszą niż plik narzędzie zastępuje ilością z pliku.
ZmianaTatyZostaje == zlyWynikPoTacie = {}
\* Znacznik efenix stoi tylko przy zleceniu, którego wycena w efenix w chwili oznaczenia równa się plikowi.
ZnacznikTylkoNaWycenionym == zlyZnacznik = {}
\* Błąd albo Ostrzeżenie Emmetta tata dostaje tylko przy zleceniu, które sam zmieniał w efenix; każde inne zlecenie,
\* także przerwane Zatrzymaniem albo zgaśnięciem, kolejne Uruchomienie kończy jako gotowe.
BladTylkoPoZmianieTaty == bladBezPowodu = {}

\* Wariant obietnicy, który pomija jej zdarzenie, gdy w chwili zdarzenia była już przyczyna wybaczonego znaleziska.
Wybaczone(zdarzenie, wybaczone) == \E s \in zdarzenie : s \cap wybaczone # {}
NieCzysciWycenyTatyPozaZnanymi == NieCzysciWycenyTaty \/ Wybaczone(czysciTate, WybaczoneNieCzysciWycenyTaty)
NieObnizaIlosciPozaZnanymi == NieObnizaIlosci \/ Wybaczone(obniza, WybaczoneNieObnizaIlosci)
ZmianaTatyZostajePozaZnanymi == ZmianaTatyZostaje \/ Wybaczone(zlyWynikPoTacie, WybaczoneZmianaTatyZostaje)
ZnacznikTylkoNaWycenionymPozaZnanymi ==
    ZnacznikTylkoNaWycenionym \/ Wybaczone(zlyZnacznik, WybaczoneZnacznikTylkoNaWycenionym)
BladTylkoPoZmianieTatyPozaZnanymi == BladTylkoPoZmianieTaty \/ Wybaczone(bladBezPowodu, WybaczoneBladTylkoPoZmianieTaty)
==========================================================================================================
