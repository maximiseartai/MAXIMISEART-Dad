------------------------------------------------ MODULE SprawyTaty ------------------------------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    MaxKlikniec,
    MaxUwag,
    MaxZgasniec,
    MaxAwariiSieci,
    MaxAwariiPlikuStanu,
    MaxAwariiKolejki,
    MaxWyjatkowKolejki,
    MaxOdrzucen,
    MaxZamkniec,
    MaxUchwytowPrzypomnien,
    WybaczoneCzekaMaPlik, WybaczoneOdrzuconaNieCzeka

F == 0
Uwagi == 1..MaxUwag
Idy == {F} \cup Uwagi
Rodzaje == {"zgl", "uwaga"}
MaxSpraw == MaxKlikniec + MaxZgasniec + 1 + MaxUwag
Sidy == 1..MaxSpraw
Numery == 0..MaxSpraw
Sprawy == [sid : Sidy, rodzaj : Rodzaje, id : Idy, numer : Numery, zamknieta : BOOLEAN]
Pliki == [nr : Sidy, rodzaj : Rodzaje, id : Idy, odrzucana : BOOLEAN]
Issue == [nr : Numery \ {0}, rodzaj : Rodzaje, id : Idy, zamkniete : BOOLEAN]
Karty == {"gotowe", "czekaNaNaprawe", "wKolejce", "wyslane", "odrzucone", "niezapisane"}
Przyczyny == {"zgasniecie-w-wysylce-zgloszenia", "zgasniecie-w-wysylce-uwagi", "plik-stanu-niedostepny",
              "wycofanie-bez-zapisu", "zapomnienie-bez-zapisu", "pokaz-po-odrzuceniu"}

Wolny == [krok |-> "wolny", plik |-> 0, wiesc |-> "-"]
Bezczynne == [pc |-> "-", kto |-> "-", sid |-> 0, plik |-> 0, wynik |-> "-", znana |-> FALSE]
BezUwagi == [pc |-> "-", sid |-> 0, id |-> 0]
BezPytania == [krok |-> "-", numer |-> FALSE, wyslano |-> FALSE]
NowyUchwyt == [podglad |-> FALSE, wysyla |-> FALSE, powrot |-> FALSE]
UchwytPrzypomnien == [podglad |-> FALSE, wysyla |-> FALSE, powrot |-> TRUE]
PierwszyUchwyt == IF MaxUchwytowPrzypomnien > 0 THEN UchwytPrzypomnien ELSE NowyUchwyt

VARIABLES
    plikStanu,
    kolejka,
    skrzynka,
    znaczniki,
    sprawy,
    odrzuconeSprawy,
    odrzuconePliki,
    dostarczoneWPracy,
    kolejkaPc,
    req,
    uwaga,
    uchwyt,
    pyt,
    otwarte,
    karta,
    nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien, awarieSieci, awariePlikuStanu, awarieKolejki,
    wyjatkiKolejki, odrzucenia, zamkniecia,
    bezPliku, odrzuconaCzeka,
    wycofane,
    numerowane

dysk == <<plikStanu, kolejka, skrzynka, znaczniki>>
pamiec == <<sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req, uwaga, uchwyt, pyt, otwarte,
            karta>>
liczniki == <<nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien, awarieSieci, awariePlikuStanu,
              awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
zdarzenia == <<bezPliku, odrzuconaCzeka>>
duchy == <<wycofane, numerowane>>
vars == <<dysk, pamiec, liczniki, zdarzenia, duchy>>

Najwieksza(S) == CHOOSE x \in S : \A y \in S : y <= x
Najmniejsza(S) == CHOOSE x \in S : \A y \in S : x <= y

Ostatnia(s) == LET i == {k \in 1..Len(s) : s[k].rodzaj = "zgl"} IN IF i = {} THEN 0 ELSE Najwieksza(i)
CzekaZgl(s) == Ostatnia(s) > 0 /\ s[Ostatnia(s)].numer = 0
Czekajaca(odrz) == IF F \in odrz THEN "odrzucone" ELSE "wKolejce"
StanZgl(s, otw, odrz) ==
    IF CzekaZgl(s) THEN Czekajaca(odrz)
    ELSE IF otw # "?" THEN (IF otw = "tak" THEN "czekaNaNaprawe" ELSE "gotowe")
    ELSE IF Ostatnia(s) > 0 /\ ~s[Ostatnia(s)].zamknieta THEN "czekaNaNaprawe" ELSE "gotowe"

Usun(s, k) == SubSeq(s, 1, k - 1) \o SubSeq(s, k + 1, Len(s))
Wycofana(s, sid) == LET inna(c) == c.sid # sid IN SelectSeq(s, inna)
Zapomniana(s, id) == LET inna(c) == ~(c.rodzaj = "uwaga" /\ c.id = id) IN SelectSeq(s, inna)
Nasze(s, rodzaj, id) == {k \in 1..Len(s) : s[k].rodzaj = rodzaj /\ s[k].id = id}
CzekajaceNasze(s, rodzaj, id) == {k \in Nasze(s, rodzaj, id) : s[k].numer = 0}
Znalezione(s, rodzaj, id) == IF rodzaj = "zgl" THEN CzekajaceNasze(s, rodzaj, id) # {} ELSE Nasze(s, rodzaj, id) # {}
Numerowane(s, rodzaj, id, n) ==
    IF rodzaj = "uwaga"
    THEN [k \in 1..Len(s) |-> IF k \in Nasze(s, rodzaj, id) THEN [s[k] EXCEPT !.numer = n] ELSE s[k]]
    ELSE IF CzekajaceNasze(s, rodzaj, id) = {} THEN s
    ELSE LET k == Najwieksza(CzekajaceNasze(s, rodzaj, id)) IN
         IF \E j \in 1..Len(s) : s[j].numer = n THEN Usun(s, k) ELSE [s EXCEPT ![k].numer = n]
NumerowaneSidy(s, rodzaj, id) ==
    IF rodzaj = "uwaga" THEN {s[k].sid : k \in Nasze(s, rodzaj, id)}
    ELSE IF CzekajaceNasze(s, rodzaj, id) = {} THEN {}
    ELSE {s[Najwieksza(CzekajaceNasze(s, rodzaj, id))].sid}

Zapisz(nowe) ==
    /\ sprawy' = nowe
    /\ IF nowe = plikStanu THEN UNCHANGED <<plikStanu, awariePlikuStanu>>
       ELSE \/ plikStanu' = nowe /\ UNCHANGED awariePlikuStanu
            \/ /\ awariePlikuStanu < MaxAwariiPlikuStanu /\ awariePlikuStanu' = awariePlikuStanu + 1
               /\ UNCHANGED plikStanu

Odrzucane == IF odrzucenia < MaxOdrzucen THEN BOOLEAN ELSE {FALSE}
NowyPlik(rodzaj, id, o) == [nr |-> nastepnyPlik, rodzaj |-> rodzaj, id |-> id, odrzucana |-> o]

OtwarteZgl == {i \in skrzynka : i.rodzaj = "zgl" /\ ~i.zamkniete}

Wlasne(r, u) == (IF r.pc \in {"post", "wycofaj"} THEN {r.sid} ELSE {}) \cup
                (IF u.pc \in {"post", "zapomnij"} THEN {u.sid} ELSE {})
Osierocone(s, kol, wlasne) ==
    {s[k].sid : k \in {j \in 1..Len(s) : s[j].numer = 0 /\ s[j].sid \notin wlasne
                                        /\ ~\E p \in kol : p.rodzaj = s[j].rodzaj /\ p.id = s[j].id}}
OdrzuconaWKolejce(s, k, odrz, kpc) ==
    k = "wKolejce" /\ CzekaZgl(s) /\ F \in odrz /\ ~(kpc.krok = "powiedz" /\ kpc.wiesc = "odrzucona")

Zdarz(stare, warunek, przyczyny) == IF warunek THEN stare \cup {przyczyny} ELSE stare
RodzajWPliku(sid) == (CHOOSE c \in {plikStanu[k] : k \in 1..Len(plikStanu)} : c.sid = sid).rodzaj
PrzyczynaZgasniecia(sid) ==
    (IF req.pc \in {"post", "wycofaj"} /\ req.sid = sid THEN {"zgasniecie-w-wysylce-zgloszenia"} ELSE {})
    \cup (IF uwaga.pc \in {"post", "zapomnij"} /\ uwaga.sid = sid THEN {"zgasniecie-w-wysylce-uwagi"} ELSE {})
    \cup (IF sid \in numerowane THEN {"plik-stanu-niedostepny"} ELSE {})
    \cup (IF sid \in wycofane /\ RodzajWPliku(sid) = "zgl" THEN {"wycofanie-bez-zapisu"} ELSE {})
    \cup (IF sid \in wycofane /\ RodzajWPliku(sid) = "uwaga" THEN {"zapomnienie-bez-zapisu"} ELSE {})
Historia(zgasniecie, przyczynyKarty) ==
    /\ bezPliku' = bezPliku \cup {IF zgasniecie THEN PrzyczynaZgasniecia(sid) ELSE {} :
                                  sid \in Osierocone(sprawy', kolejka', Wlasne(req', uwaga'))
                                         \ Osierocone(sprawy, kolejka, Wlasne(req, uwaga))}
    /\ odrzuconaCzeka' = Zdarz(odrzuconaCzeka, ~OdrzuconaWKolejce(sprawy, karta, odrzuconeSprawy, kolejkaPc)
                                               /\ OdrzuconaWKolejce(sprawy', karta', odrzuconeSprawy', kolejkaPc'),
                               przyczynyKarty)

TypeOK ==
    /\ plikStanu \in Seq(Sprawy) /\ sprawy \in Seq(Sprawy)
    /\ kolejka \subseteq Pliki
    /\ skrzynka \subseteq Issue
    /\ znaczniki \subseteq [plik : Sidy, nr : Numery \ {0}]
    /\ odrzuconeSprawy \subseteq Idy /\ odrzuconePliki \subseteq Sidy /\ dostarczoneWPracy \subseteq Sidy
    /\ kolejkaPc \in [krok : {"wolny", "powiedz", "oznacz"}, plik : 0..MaxSpraw, wiesc : {"-", "numer", "odrzucona"}]
    /\ req \in [pc : {"-", "sprawdz", "post", "wycofaj", "czekaj", "pokaz"}, kto : {"-", "klik", "powrot"},
                sid : 0..MaxSpraw, plik : 0..MaxSpraw, wynik : Karty \cup {"-", "wyjatek"}, znana : BOOLEAN]
    /\ uwaga \in [pc : {"-", "post", "zapomnij"}, sid : 0..MaxSpraw, id : {0} \cup Uwagi]
    /\ uchwyt \in [podglad : BOOLEAN, wysyla : BOOLEAN, powrot : BOOLEAN]
    /\ pyt \in [krok : {"-", "pyta", "decyzja"}, numer : BOOLEAN, wyslano : BOOLEAN]
    /\ otwarte \in {"?", "tak", "nie"}
    /\ karta \in Karty
    /\ nastepnaSprawa \in 1..(MaxSpraw + 1) /\ nastepnyPlik \in 1..(MaxSpraw + 1)
    /\ klikniecia \in 0..MaxKlikniec /\ uwagi \in 0..MaxUwag /\ zgasniecia \in 0..MaxZgasniec
    /\ uchwytyPrzypomnien \in 0..MaxUchwytowPrzypomnien
    /\ awarieSieci \in 0..MaxAwariiSieci /\ awariePlikuStanu \in 0..MaxAwariiPlikuStanu
    /\ awarieKolejki \in 0..MaxAwariiKolejki /\ wyjatkiKolejki \in 0..MaxWyjatkowKolejki
    /\ odrzucenia \in 0..MaxOdrzucen /\ zamkniecia \in 0..MaxZamkniec
    /\ \A e \in {bezPliku, odrzuconaCzeka} : e \subseteq SUBSET Przyczyny
    /\ wycofane \subseteq Sidy /\ numerowane \subseteq Sidy

Init ==
    /\ plikStanu = <<>> /\ kolejka = {} /\ skrzynka = {} /\ znaczniki = {}
    /\ sprawy = <<>> /\ odrzuconeSprawy = {} /\ odrzuconePliki = {} /\ dostarczoneWPracy = {}
    /\ kolejkaPc = Wolny /\ req = Bezczynne /\ uwaga = BezUwagi /\ uchwyt = PierwszyUchwyt /\ pyt = BezPytania
    /\ otwarte = "?" /\ karta = "gotowe"
    /\ nastepnaSprawa = 1 /\ nastepnyPlik = 1
    /\ klikniecia = 0 /\ uwagi = 0 /\ zgasniecia = 0 /\ uchwytyPrzypomnien = 0 /\ awarieSieci = 0 /\ awariePlikuStanu = 0 /\ awarieKolejki = 0
    /\ wyjatkiKolejki = 0 /\ odrzucenia = 0 /\ zamkniecia = 0
    /\ bezPliku = {} /\ odrzuconaCzeka = {}
    /\ wycofane = {} /\ numerowane = {}

Podglad ==
    /\ ~uchwyt.podglad /\ pyt.krok = "-"
    /\ uchwyt' = [uchwyt EXCEPT !.podglad = TRUE]
    /\ pyt' = [krok |-> "pyta", numer |-> FALSE, wyslano |-> FALSE]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req, uwaga, otwarte,
                   karta, liczniki>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Pytanie ==
    /\ pyt.krok = "pyta"
    /\ \/ /\ awarieSieci < MaxAwariiSieci /\ awarieSieci' = awarieSieci + 1
          /\ UNCHANGED otwarte
       \/ /\ otwarte' = IF pyt.numer THEN otwarte ELSE IF OtwarteZgl # {} THEN "tak" ELSE "nie"
          /\ UNCHANGED awarieSieci
    /\ pyt' = [pyt EXCEPT !.krok = "decyzja"]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req, uwaga, uchwyt,
                   karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien, awariePlikuStanu, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Decyzja ==
    /\ pyt.krok = "decyzja"
    /\ pyt' = BezPytania
    /\ IF pyt.wyslano
       THEN UNCHANGED <<karta, uchwyt, req>>
       ELSE LET nowa == IF karta \in {"wyslane", "wKolejce"} THEN karta ELSE StanZgl(sprawy, otwarte, odrzuconeSprawy)
            IN /\ karta' = nowa
               /\ IF nowa = "czekaNaNaprawe" /\ ~uchwyt.powrot
                  THEN /\ uchwyt' = [uchwyt EXCEPT !.powrot = TRUE, !.wysyla = TRUE]
                       /\ req' = [Bezczynne EXCEPT !.pc = "sprawdz", !.kto = "powrot"]
                  ELSE UNCHANGED <<uchwyt, req>>
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, otwarte,
                   liczniki>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Klik ==
    /\ uchwyt.podglad /\ ~uchwyt.wysyla /\ req.pc = "-"
    /\ karta \notin {"wyslane", "wKolejce"}
    /\ klikniecia < MaxKlikniec /\ klikniecia' = klikniecia + 1
    /\ uchwyt' = [uchwyt EXCEPT !.wysyla = TRUE]
    /\ pyt' = IF pyt.krok # "-" THEN [pyt EXCEPT !.wyslano = TRUE] ELSE pyt
    /\ req' = [Bezczynne EXCEPT !.pc = "sprawdz", !.kto = "klik"]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, otwarte, karta,
                   nastepnaSprawa, nastepnyPlik, uwagi, zgasniecia, uchwytyPrzypomnien, awarieSieci, awariePlikuStanu, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

KoniecQueue(wynik) ==
    IF req.kto = "klik"
    THEN req' = [req EXCEPT !.pc = "pokaz", !.wynik = wynik, !.znana = F \in odrzuconeSprawy] /\ UNCHANGED uchwyt
    ELSE req' = Bezczynne /\ uchwyt' = [uchwyt EXCEPT !.wysyla = FALSE]

Sprawdz ==
    /\ req.pc = "sprawdz"
    /\ IF CzekaZgl(sprawy)
       THEN /\ KoniecQueue(Czekajaca(odrzuconeSprawy))
            /\ UNCHANGED <<sprawy, plikStanu, awariePlikuStanu, nastepnaSprawa>>
       ELSE /\ Zapisz(Append(sprawy, [sid |-> nastepnaSprawa, rodzaj |-> "zgl", id |-> F, numer |-> 0,
                                      zamknieta |-> FALSE]))
            /\ req' = [req EXCEPT !.pc = "post", !.sid = nastepnaSprawa]
            /\ nastepnaSprawa' = nastepnaSprawa + 1
            /\ UNCHANGED uchwyt
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga,
                   pyt, otwarte, karta, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien, awarieSieci, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Post ==
    /\ req.pc = "post"
    /\ \/ \E o \in Odrzucane :
             /\ kolejka' = kolejka \cup {NowyPlik("zgl", F, o)}
             /\ nastepnyPlik' = nastepnyPlik + 1
             /\ odrzucenia' = IF o THEN odrzucenia + 1 ELSE odrzucenia
             /\ req' = [req EXCEPT !.pc = "czekaj", !.plik = nastepnyPlik]
             /\ UNCHANGED <<awarieKolejki, wyjatkiKolejki>>
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ req' = [req EXCEPT !.pc = "wycofaj", !.wynik = "niezapisane"]
          /\ UNCHANGED <<kolejka, nastepnyPlik, odrzucenia, wyjatkiKolejki>>
       \/ /\ wyjatkiKolejki < MaxWyjatkowKolejki /\ wyjatkiKolejki' = wyjatkiKolejki + 1
          /\ req' = [req EXCEPT !.pc = "wycofaj", !.wynik = "wyjatek"]
          /\ UNCHANGED <<kolejka, nastepnyPlik, odrzucenia, awarieKolejki>>
    /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, uchwyt, pyt, otwarte,
                   karta, nastepnaSprawa, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien, awarieSieci, awariePlikuStanu, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Wycofaj ==
    /\ req.pc = "wycofaj"
    /\ Zapisz(Wycofana(sprawy, req.sid))
    /\ wycofane' = wycofane \cup {req.sid}
    /\ IF req.wynik = "wyjatek" \/ req.kto = "powrot"
       THEN req' = Bezczynne /\ uchwyt' = [uchwyt EXCEPT !.wysyla = FALSE]
       ELSE req' = [req EXCEPT !.pc = "pokaz"] /\ UNCHANGED uchwyt
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga,
                   pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien, awarieSieci,
                   awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia, numerowane>>
    /\ Historia(FALSE, {})

Czekaj ==
    /\ req.pc = "czekaj"
    /\ KoniecQueue(IF req.plik \in dostarczoneWPracy THEN "wyslane" ELSE Czekajaca(odrzuconeSprawy))
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, pyt, otwarte,
                   karta, liczniki>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Pokaz ==
    /\ req.pc = "pokaz"
    /\ karta' = IF req.wynik = "wKolejce" /\ ~CzekaZgl(sprawy) THEN "wyslane" ELSE req.wynik
    /\ req' = Bezczynne /\ uchwyt' = [uchwyt EXCEPT !.wysyla = FALSE]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, pyt, otwarte,
                   liczniki>>
    /\ UNCHANGED duchy /\ Historia(FALSE, IF req.znana THEN {} ELSE {"pokaz-po-odrzuceniu"})

UwagaWyslij ==
    /\ uwaga.pc = "-" /\ uwagi < MaxUwag
    /\ Zapisz(Append(sprawy, [sid |-> nastepnaSprawa, rodzaj |-> "uwaga", id |-> uwagi + 1, numer |-> 0,
                              zamknieta |-> FALSE]))
    /\ uwaga' = [pc |-> "post", sid |-> nastepnaSprawa, id |-> uwagi + 1]
    /\ uwagi' = uwagi + 1 /\ nastepnaSprawa' = nastepnaSprawa + 1
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req,
                   uchwyt, pyt, otwarte, karta, nastepnyPlik, klikniecia, zgasniecia, uchwytyPrzypomnien, awarieSieci, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

UwagaPost ==
    /\ uwaga.pc = "post"
    /\ \/ \E o \in Odrzucane :
             /\ kolejka' = kolejka \cup {NowyPlik("uwaga", uwaga.id, o)}
             /\ nastepnyPlik' = nastepnyPlik + 1
             /\ odrzucenia' = IF o THEN odrzucenia + 1 ELSE odrzucenia
             /\ uwaga' = BezUwagi
             /\ UNCHANGED awarieKolejki
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ uwaga' = [uwaga EXCEPT !.pc = "zapomnij"]
          /\ UNCHANGED <<kolejka, nastepnyPlik, odrzucenia>>
    /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy,
                   kolejkaPc, req, uchwyt, pyt, otwarte, karta, nastepnaSprawa, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien,
                   awarieSieci, awariePlikuStanu, wyjatkiKolejki, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

UwagaZapomnij ==
    /\ uwaga.pc = "zapomnij"
    /\ Zapisz(Zapomniana(sprawy, uwaga.id))
    /\ wycofane' = wycofane \cup {uwaga.sid}
    /\ uwaga' = BezUwagi
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req,
                   uchwyt, pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien,
                   awarieSieci, awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia, numerowane>>
    /\ Historia(FALSE, {})

Kwalifikowane == {p \in kolejka : p.nr \notin odrzuconePliki}

Doreczenie ==
    /\ kolejkaPc = Wolny /\ Kwalifikowane # {}
    /\ LET p == CHOOSE q \in Kwalifikowane : \A r \in Kwalifikowane : q.nr <= r.nr
           znacznik == {m \in znaczniki : m.plik = p.nr}
       IN \/ /\ awarieSieci < MaxAwariiSieci /\ awarieSieci' = awarieSieci + 1
             /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, odrzuconeSprawy, odrzuconePliki, kolejkaPc,
                            awariePlikuStanu, numerowane>>
          \/ /\ p.odrzucana /\ znacznik = {}
             /\ odrzuconePliki' = odrzuconePliki \cup {p.nr}
             /\ odrzuconeSprawy' = odrzuconeSprawy \cup {p.id}
             /\ kolejkaPc' = IF p.rodzaj = "zgl" THEN [krok |-> "powiedz", plik |-> p.nr, wiesc |-> "odrzucona"]
                             ELSE Wolny
             /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, awarieSieci, awariePlikuStanu, numerowane>>
          \/ /\ ~(p.odrzucana /\ znacznik = {})
             /\ LET nowe == znacznik = {} /\ ~(p.rodzaj = "zgl" /\ OtwarteZgl # {})
                    nr == IF znacznik # {} THEN (CHOOSE m \in znacznik : TRUE).nr
                          ELSE IF ~nowe THEN Najmniejsza({i.nr : i \in OtwarteZgl})
                          ELSE Cardinality(skrzynka) + 1
                IN /\ skrzynka' = IF nowe
                                  THEN skrzynka \cup {[nr |-> nr, rodzaj |-> p.rodzaj, id |-> p.id, zamkniete |-> FALSE]}
                                  ELSE skrzynka
                   /\ znaczniki' = znaczniki \cup {[plik |-> p.nr, nr |-> nr]}
                   /\ Zapisz(Numerowane(sprawy, p.rodzaj, p.id, nr))
                   /\ numerowane' = numerowane \cup NumerowaneSidy(sprawy, p.rodzaj, p.id)
                   /\ kolejkaPc' = IF p.rodzaj = "zgl" /\ Znalezione(sprawy, p.rodzaj, p.id)
                                   THEN [krok |-> "powiedz", plik |-> p.nr, wiesc |-> "numer"]
                                   ELSE [krok |-> "oznacz", plik |-> p.nr, wiesc |-> "-"]
             /\ UNCHANGED <<odrzuconeSprawy, odrzuconePliki, awarieSieci>>
    /\ UNCHANGED <<kolejka, dostarczoneWPracy, req, uwaga, uchwyt, pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik,
                   klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien, awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia, wycofane>>
    /\ Historia(FALSE, {})

Uslyszane ==
    /\ kolejkaPc.krok = "powiedz"
    /\ IF kolejkaPc.wiesc = "numer"
       THEN /\ otwarte' = "tak"
            /\ pyt' = IF pyt.krok = "pyta" THEN [pyt EXCEPT !.numer = TRUE] ELSE pyt
            /\ karta' = IF karta = "wKolejce" THEN "wyslane" ELSE karta
            /\ kolejkaPc' = [kolejkaPc EXCEPT !.krok = "oznacz"]
       ELSE /\ karta' = "odrzucone"
            /\ kolejkaPc' = Wolny
            /\ UNCHANGED <<otwarte, pyt>>
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, req, uwaga, uchwyt, liczniki>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Oznacz ==
    /\ kolejkaPc.krok = "oznacz"
    /\ dostarczoneWPracy' = dostarczoneWPracy \cup {kolejkaPc.plik}
    /\ kolejka' = {p \in kolejka : p.nr # kolejkaPc.plik}
    /\ kolejkaPc' = Wolny
    /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, odrzuconeSprawy, odrzuconePliki, req, uwaga, uchwyt, pyt,
                   otwarte, karta, liczniki>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Powiadomienia ==
    /\ \/ Zapisz(sprawy)
       \/ Zapisz([k \in 1..Len(sprawy) |->
                     LET z == {i \in skrzynka : i.nr = sprawy[k].numer /\ i.rodzaj = sprawy[k].rodzaj} IN
                     IF z = {} THEN sprawy[k] ELSE [sprawy[k] EXCEPT !.zamknieta = (CHOOSE i \in z : TRUE).zamkniete]])
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req,
                   uwaga, uchwyt, pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien,
                   awarieSieci, awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

MaksZamyka ==
    /\ zamkniecia < MaxZamkniec /\ zamkniecia' = zamkniecia + 1
    /\ \E i \in skrzynka : ~i.zamkniete /\ skrzynka' = (skrzynka \ {i}) \cup {[i EXCEPT !.zamkniete = TRUE]}
    /\ UNCHANGED <<plikStanu, kolejka, znaczniki, pamiec, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, uchwytyPrzypomnien,
                   awarieSieci, awariePlikuStanu, awarieKolejki, wyjatkiKolejki, odrzucenia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Zgasniecie ==
    /\ zgasniecia < MaxZgasniec /\ zgasniecia' = zgasniecia + 1
    /\ sprawy' = plikStanu
    /\ odrzuconeSprawy' = {} /\ odrzuconePliki' = {} /\ dostarczoneWPracy' = {}
    /\ kolejkaPc' = Wolny /\ req' = Bezczynne /\ uwaga' = BezUwagi /\ uchwyt' = PierwszyUchwyt /\ pyt' = BezPytania
    /\ otwarte' = "?"
    /\ karta' = StanZgl(plikStanu, "?", {})
    /\ UNCHANGED <<dysk, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, uchwytyPrzypomnien, awarieSieci,
                   awariePlikuStanu, awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(TRUE, {})

NowyUchwytPrzypomnien ==
    /\ uchwytyPrzypomnien < MaxUchwytowPrzypomnien /\ uchwytyPrzypomnien' = uchwytyPrzypomnien + 1
    /\ req.pc = "-" /\ pyt.krok = "-"
    /\ uchwyt' = UchwytPrzypomnien
    /\ karta' = StanZgl(sprawy, otwarte, odrzuconeSprawy)
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req, uwaga, pyt, otwarte,
                   nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, awarieSieci, awariePlikuStanu,
                   awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ UNCHANGED duchy /\ Historia(FALSE, {})

Next ==
    \/ Podglad \/ Pytanie \/ Decyzja \/ Klik \/ Sprawdz \/ Post \/ Wycofaj \/ Czekaj \/ Pokaz
    \/ UwagaWyslij \/ UwagaPost \/ UwagaZapomnij
    \/ Doreczenie \/ Uslyszane \/ Oznacz
    \/ Powiadomienia \/ MaksZamyka \/ Zgasniecie \/ NowyUchwytPrzypomnien

Sprawiedliwosc ==
    /\ WF_vars(Pytanie) /\ WF_vars(Decyzja) /\ WF_vars(Sprawdz) /\ WF_vars(Post) /\ WF_vars(Wycofaj)
    /\ WF_vars(Czekaj) /\ WF_vars(Pokaz) /\ WF_vars(UwagaPost) /\ WF_vars(UwagaZapomnij)
    /\ WF_vars(Doreczenie) /\ WF_vars(Uslyszane) /\ WF_vars(Oznacz)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

CzekaMaPlik == bezPliku = {}
OdrzuconaNieCzeka == odrzuconaCzeka = {}

KartaZgodna ==
    IF CzekaZgl(sprawy) THEN karta = Czekajaca(odrzuconeSprawy)
    ELSE karta \in {"gotowe", "czekaNaNaprawe", "wyslane", "niezapisane"}
                   \cup (IF \E p \in kolejka : p.rodzaj = "zgl" /\ p.nr \in odrzuconePliki THEN {"odrzucone"} ELSE {})
KolejkaRozstrzygnieta == \A p \in kolejka : p.nr \in odrzuconePliki
Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
KartaZnana ==
    /\ OdrzuconaWKolejce(sprawy, karta, odrzuconeSprawy, kolejkaPc)
    /\ odrzuconaCzeka # {} /\ Wybaczone(odrzuconaCzeka, WybaczoneOdrzuconaNieCzeka)
Zbieganie == <>[]((KartaZgodna \/ KartaZnana) /\ KolejkaRozstrzygnieta)

CzekaMaPlikPozaZnanymi == Wybaczone(bezPliku, WybaczoneCzekaMaPlik)
OdrzuconaNieCzekaPozaZnanymi == Wybaczone(odrzuconaCzeka, WybaczoneOdrzuconaNieCzeka)
=========================================================================================================================
