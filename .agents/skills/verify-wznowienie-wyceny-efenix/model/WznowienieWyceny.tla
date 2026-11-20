------------------------------ MODULE WznowienieWyceny ------------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS
    LiczbaZlecen,
    MaxUruchomien,
    MaxZmianTaty,
    MozeZgasnac,
    MozeSieZatrzymac,
    MozeBrakowacPozycji,
    TataWTrakcie,
    MozePrzekazac,
    MozeOdmowicPrzekazania,
    WybaczoneNieCzysciWycenyTaty, WybaczoneNieObnizaIlosci, WybaczoneZmianaTatyZostaje,
    WybaczoneZnacznikTylkoNaWycenionym, WybaczoneBladTylkoPoZmianieTaty, WybaczonePrzekazujeTylkoGotowe,
    WybaczoneNieZmieniaPrzekazanego

Zlecenia == 1..LiczbaZlecen
Pozycje == {"A", "B", "C"}
Ilosci == 0..2
Plik == [p \in Pozycje |-> IF p = "B" THEN 2 ELSE 1]
Emmett == [p \in Pozycje |-> IF p = "C" THEN 0 ELSE 1]
Pusta == [p \in Pozycje |-> 0]
Tryby == IF MozePrzekazac THEN {"bez", "z"} ELSE {"bez"}
Kwota(q) == q["A"] + q["B"] + q["C"]
DoWpisania(q) == {p \in Pozycje : q[p] < Plik[p]}
Nadmiar(q) == {p \in Pozycje : q[p] > Plik[p]}
Pierwsza(S) == IF "A" \in S THEN "A" ELSE IF "B" \in S THEN "B" ELSE "C"
WynikDokonczenia(q) == IF Nadmiar(q) # {} THEN "ostrzezenie" ELSE IF Kwota(q) = Kwota(Plik) THEN "gotowe" ELSE "blad"
Oczekiwane(q) == IF Nadmiar(q) # {} THEN {"ostrzezenie"} ELSE {"gotowe", "przekazane"}

ZnaneZnaleziska == {"brak-pozycji-po-emmetcie", "odmowa-przekazania"}

VARIABLES
    efenix,
    proces,
    zlecenie,
    krok,
    doWpisania,
    wynik,
    znacznik,
    status,
    tryb,
    tataZmienial,
    uruchomienia, zmian,
    slady,
    czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu, zlePrzekazanie, zmianaPrzekazanego

vars == <<efenix, proces, zlecenie, krok, doWpisania, wynik, znacznik, status, tryb, tataZmienial, uruchomienia, zmian,
          slady, czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu, zlePrzekazanie, zmianaPrzekazanego>>
historia == <<czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu, zlePrzekazanie, zmianaPrzekazanego>>

Zdarzenie == {{}} \cup {{s} : s \in SUBSET ZnaneZnaleziska}
Zdarz(stare, warunek) == IF stare = {} /\ warunek THEN {slady[zlecenie]} ELSE stare

TypeOK ==
    /\ efenix \in [Zlecenia -> [Pozycje -> Ilosci]]
    /\ proces \in {"stoi", "dziala"}
    /\ zlecenie \in Zlecenia
    /\ krok \in {"-", "otworz", "emmett", "odczyt", "wpisz", "potwierdz", "przekaz", "szukaj", "koniec", "znaczniki"}
    /\ doWpisania \subseteq Pozycje
    /\ wynik \in [Zlecenia -> {"brak", "gotowe", "przekazane", "blad", "ostrzezenie"}]
    /\ znacznik \in [Zlecenia -> {"brak", "efenix", "przekazania"}]
    /\ status \in [Zlecenia -> {"do wyceny", "do akceptacji"}]
    /\ tryb \in {"bez", "z"}
    /\ tataZmienial \in [Zlecenia -> BOOLEAN]
    /\ slady \in [Zlecenia -> SUBSET ZnaneZnaleziska]
    /\ czysciTate \in Zdarzenie /\ obniza \in Zdarzenie /\ zlyWynikPoTacie \in Zdarzenie
    /\ zlyZnacznik \in Zdarzenie /\ bladBezPowodu \in Zdarzenie
    /\ zlePrzekazanie \in Zdarzenie /\ zmianaPrzekazanego \in Zdarzenie

Init ==
    /\ efenix = [o \in Zlecenia |-> Pusta]
    /\ proces = "stoi" /\ zlecenie = 1 /\ krok = "-" /\ doWpisania = {}
    /\ wynik = [o \in Zlecenia |-> "brak"]
    /\ znacznik = [o \in Zlecenia |-> "brak"]
    /\ status = [o \in Zlecenia |-> "do wyceny"]
    /\ tryb = "bez"
    /\ tataZmienial = [o \in Zlecenia |-> FALSE]
    /\ uruchomienia = 0 /\ zmian = 0 /\ slady = [o \in Zlecenia |-> {}]
    /\ czysciTate = {} /\ obniza = {} /\ zlyWynikPoTacie = {} /\ zlyZnacznik = {} /\ bladBezPowodu = {}
    /\ zlePrzekazanie = {} /\ zmianaPrzekazanego = {}

Start ==
    /\ proces = "stoi" /\ uruchomienia < MaxUruchomien
    /\ proces' = "dziala" /\ zlecenie' = 1 /\ krok' = "otworz" /\ tryb' \in Tryby
    /\ wynik' = [o \in Zlecenia |-> "brak"]
    /\ UNCHANGED <<efenix, doWpisania, znacznik, status, tataZmienial, uruchomienia, zmian, slady, historia>>

Wynik(w, q) ==
    /\ wynik' = [wynik EXCEPT ![zlecenie] = w]
    /\ zlyWynikPoTacie' = Zdarz(zlyWynikPoTacie, tataZmienial[zlecenie] /\ w \notin Oczekiwane(q))
    /\ bladBezPowodu' = Zdarz(bladBezPowodu, ~tataZmienial[zlecenie] /\ w \notin {"gotowe", "przekazane"})

Skonczone(q) ==
    LET w == WynikDokonczenia(q) IN
    IF w = "gotowe" /\ tryb = "z"
    THEN wynik' = [wynik EXCEPT ![zlecenie] = "gotowe"] /\ krok' = "przekaz" /\ UNCHANGED <<zlyWynikPoTacie, bladBezPowodu>>
    ELSE Wynik(w, q) /\ krok' = "koniec"

Dokoncz(q) ==
    /\ doWpisania' = DoWpisania(q)
    /\ IF DoWpisania(q) = {}
       THEN Skonczone(q)
       ELSE krok' = "wpisz" /\ UNCHANGED <<wynik, zlyWynikPoTacie, bladBezPowodu>>

Otworz ==
    LET q == efenix[zlecenie] IN
    /\ proces = "dziala" /\ krok = "otworz"
    /\ IF status[zlecenie] = "do akceptacji"
       THEN Wynik("przekazane", q) /\ krok' = "koniec" /\ UNCHANGED doWpisania
       ELSE IF q # Pusta
       THEN Dokoncz(q)
       ELSE krok' = "emmett" /\ UNCHANGED <<wynik, doWpisania, zlyWynikPoTacie, bladBezPowodu>>
    /\ UNCHANGED <<efenix, proces, zlecenie, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyZnacznik, zlePrzekazanie, zmianaPrzekazanego>>

ZaladujEmmetta ==
    /\ proces = "dziala" /\ krok = "emmett"
    /\ czysciTate' = Zdarz(czysciTate, efenix[zlecenie] # Pusta)
    /\ obniza' = Zdarz(obniza, \E p \in Pozycje : Emmett[p] < efenix[zlecenie][p])
    /\ zmianaPrzekazanego' = Zdarz(zmianaPrzekazanego, status[zlecenie] = "do akceptacji")
    /\ efenix' = [efenix EXCEPT ![zlecenie] = Emmett]
    /\ krok' = "odczyt"
    /\ UNCHANGED <<proces, zlecenie, doWpisania, wynik, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   zlyWynikPoTacie, zlyZnacznik, bladBezPowodu, zlePrzekazanie>>

OdczytPoEmmetcie ==
    /\ proces = "dziala" /\ krok = "odczyt"
    /\ Dokoncz(efenix[zlecenie])
    /\ UNCHANGED <<efenix, proces, zlecenie, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyZnacznik, zlePrzekazanie, zmianaPrzekazanego>>

BrakPozycji ==
    /\ MozeBrakowacPozycji /\ proces = "dziala" /\ krok = "odczyt"
    /\ slady' = [slady EXCEPT ![zlecenie] = @ \cup {"brak-pozycji-po-emmetcie"}]
    /\ wynik' = [wynik EXCEPT ![zlecenie] = "blad"]
    /\ bladBezPowodu' = IF bladBezPowodu = {} /\ ~tataZmienial[zlecenie] THEN {slady'[zlecenie]} ELSE bladBezPowodu
    /\ krok' = "koniec"
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, znacznik, status, tryb, tataZmienial, uruchomienia, zmian,
                   czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, zlePrzekazanie, zmianaPrzekazanego>>

Wpisz ==
    LET p == Pierwsza(doWpisania) IN
    /\ proces = "dziala" /\ krok = "wpisz"
    /\ obniza' = Zdarz(obniza, Plik[p] < efenix[zlecenie][p])
    /\ zmianaPrzekazanego' = Zdarz(zmianaPrzekazanego, status[zlecenie] = "do akceptacji")
    /\ efenix' = [efenix EXCEPT ![zlecenie][p] = Plik[p]]
    /\ doWpisania' = doWpisania \ {p}
    /\ krok' = "potwierdz"
    /\ UNCHANGED <<proces, zlecenie, wynik, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu, zlePrzekazanie>>

Potwierdz ==
    /\ proces = "dziala" /\ krok = "potwierdz"
    /\ IF doWpisania = {}
       THEN Skonczone(efenix[zlecenie])
       ELSE krok' = "wpisz" /\ UNCHANGED <<wynik, zlyWynikPoTacie, bladBezPowodu>>
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyZnacznik, zlePrzekazanie, zmianaPrzekazanego>>

Przekaz ==
    /\ proces = "dziala" /\ krok = "przekaz"
    /\ zlePrzekazanie' = Zdarz(zlePrzekazanie, efenix[zlecenie] # Plik \/ tryb # "z")
    /\ zmianaPrzekazanego' = Zdarz(zmianaPrzekazanego, status[zlecenie] = "do akceptacji")
    /\ status' = [status EXCEPT ![zlecenie] = "do akceptacji"]
    /\ krok' = "szukaj"
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, wynik, znacznik, tryb, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyWynikPoTacie, zlyZnacznik, bladBezPowodu>>

OdmowaPrzekazania ==
    LET slad == slady[zlecenie] \cup {"odmowa-przekazania"} IN
    /\ MozeOdmowicPrzekazania /\ proces = "dziala" /\ krok = "przekaz"
    /\ slady' = [slady EXCEPT ![zlecenie] = slad]
    /\ wynik' = [wynik EXCEPT ![zlecenie] = "blad"]
    /\ zlyWynikPoTacie' = IF zlyWynikPoTacie = {} /\ tataZmienial[zlecenie] THEN {slad} ELSE zlyWynikPoTacie
    /\ bladBezPowodu' = IF bladBezPowodu = {} /\ ~tataZmienial[zlecenie] THEN {slad} ELSE bladBezPowodu
    /\ krok' = "koniec"
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, znacznik, status, tryb, tataZmienial, uruchomienia, zmian,
                   czysciTate, obniza, zlyZnacznik, zlePrzekazanie, zmianaPrzekazanego>>

Szukaj ==
    /\ proces = "dziala" /\ krok = "szukaj"
    /\ Wynik(IF status[zlecenie] = "do akceptacji" THEN "przekazane" ELSE "blad", efenix[zlecenie])
    /\ krok' = "koniec"
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   czysciTate, obniza, zlyZnacznik, zlePrzekazanie, zmianaPrzekazanego>>

KoniecZlecenia ==
    /\ proces = "dziala" /\ krok = "koniec"
    /\ IF zlecenie < LiczbaZlecen
       THEN zlecenie' = zlecenie + 1 /\ krok' = "otworz"
       ELSE krok' = "znaczniki" /\ UNCHANGED zlecenie
    /\ UNCHANGED <<efenix, proces, doWpisania, wynik, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   historia>>

Zatrzymanie ==
    /\ MozeSieZatrzymac /\ proces = "dziala"
    /\ krok \in {"otworz", "emmett", "odczyt", "wpisz", "potwierdz", "przekaz", "szukaj"}
    /\ krok' = "znaczniki"
    /\ wynik' = [wynik EXCEPT ![zlecenie] = "brak"]
    /\ UNCHANGED <<efenix, proces, zlecenie, doWpisania, znacznik, status, tryb, tataZmienial, uruchomienia, zmian, slady,
                   historia>>

Nowy(o) ==
    CASE wynik[o] = "przekazane" -> "przekazania"
      [] wynik[o] = "gotowe" /\ znacznik[o] # "przekazania" -> "efenix"
      [] OTHER -> znacznik[o]
Zle(o) ==
    /\ znacznik'[o] # znacznik[o]
    /\ \/ znacznik'[o] = "efenix" /\ (efenix[o] # Plik \/ znacznik[o] = "przekazania")
       \/ znacznik'[o] = "przekazania" /\ (efenix[o] # Plik \/ status[o] # "do akceptacji")
       \/ znacznik'[o] = "brak"
Znaczniki ==
    /\ proces = "dziala" /\ krok = "znaczniki"
    /\ znacznik' = [o \in Zlecenia |-> Nowy(o)]
    /\ zlyZnacznik' = IF zlyZnacznik = {} /\ \E o \in Zlecenia : Zle(o)
                      THEN {slady[CHOOSE o \in Zlecenia : Zle(o)]} ELSE zlyZnacznik
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, zlecenie, doWpisania, wynik, status, tryb, tataZmienial, zmian, slady,
                   czysciTate, obniza, zlyWynikPoTacie, bladBezPowodu, zlePrzekazanie, zmianaPrzekazanego>>

Zgasniecie ==
    /\ MozeZgasnac /\ proces = "dziala"
    /\ proces' = "stoi" /\ krok' = "-" /\ uruchomienia' = uruchomienia + 1
    /\ UNCHANGED <<efenix, zlecenie, doWpisania, wynik, znacznik, status, tryb, tataZmienial, zmian, slady, historia>>

Tata(o, p, v) ==
    /\ (proces = "stoi" \/ TataWTrakcie) /\ zmian < MaxZmianTaty /\ v # efenix[o][p] /\ status[o] = "do wyceny"
    /\ efenix' = [efenix EXCEPT ![o][p] = v]
    /\ tataZmienial' = [tataZmienial EXCEPT ![o] = TRUE]
    /\ zmian' = zmian + 1
    /\ UNCHANGED <<proces, zlecenie, krok, doWpisania, wynik, znacznik, status, tryb, uruchomienia, slady, historia>>

Koniec ==
    /\ proces = "stoi" /\ uruchomienia = MaxUruchomien
    /\ UNCHANGED vars

Next ==
    \/ Start \/ Otworz \/ ZaladujEmmetta \/ OdczytPoEmmetcie \/ BrakPozycji \/ Wpisz \/ Potwierdz \/ Przekaz
    \/ OdmowaPrzekazania \/ Szukaj
    \/ KoniecZlecenia
    \/ Zatrzymanie \/ Znaczniki \/ Zgasniecie
    \/ \E o \in Zlecenia, p \in Pozycje, v \in Ilosci : Tata(o, p, v)
    \/ Koniec

Spec == Init /\ [][Next]_vars

NieCzysciWycenyTaty == czysciTate = {}
NieObnizaIlosci == obniza = {}
ZmianaTatyZostaje == zlyWynikPoTacie = {}
ZnacznikTylkoNaWycenionym == zlyZnacznik = {}
BladTylkoPoZmianieTaty == bladBezPowodu = {}
PrzekazujeTylkoGotowe == zlePrzekazanie = {}
NieZmieniaPrzekazanego == zmianaPrzekazanego = {}

Wybaczone(zdarzenie, wybaczone) == \E s \in zdarzenie : s \cap wybaczone # {}
NieCzysciWycenyTatyPozaZnanymi == NieCzysciWycenyTaty \/ Wybaczone(czysciTate, WybaczoneNieCzysciWycenyTaty)
NieObnizaIlosciPozaZnanymi == NieObnizaIlosci \/ Wybaczone(obniza, WybaczoneNieObnizaIlosci)
ZmianaTatyZostajePozaZnanymi == ZmianaTatyZostaje \/ Wybaczone(zlyWynikPoTacie, WybaczoneZmianaTatyZostaje)
ZnacznikTylkoNaWycenionymPozaZnanymi ==
    ZnacznikTylkoNaWycenionym \/ Wybaczone(zlyZnacznik, WybaczoneZnacznikTylkoNaWycenionym)
BladTylkoPoZmianieTatyPozaZnanymi == BladTylkoPoZmianieTaty \/ Wybaczone(bladBezPowodu, WybaczoneBladTylkoPoZmianieTaty)
PrzekazujeTylkoGotowePozaZnanymi == PrzekazujeTylkoGotowe \/ Wybaczone(zlePrzekazanie, WybaczonePrzekazujeTylkoGotowe)
NieZmieniaPrzekazanegoPozaZnanymi == NieZmieniaPrzekazanego \/ Wybaczone(zmianaPrzekazanego, WybaczoneNieZmieniaPrzekazanego)
==========================================================================================================
