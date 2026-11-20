------------------------------ MODULE UrwaneUruchomienie ------------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Wyceny,
    LiczbaZlecen,
    MaxZgasniec,
    MaxZatrzyman,
    MaxAwariiWpisu,
    MaxAwariiOdczytu,
    MaxAwariiLogow,
    MaxAwariiKolejki,
    MaxAwariiUsuniecia,
    MaxCofniecZegara,
    TekstDoMaski,
    StareLogi,
    WybaczoneDziennikPoKolejce, WybaczoneBezUrwanychPoWyniku, WybaczoneTeSameZnaki, WybaczonePrzezStraznika,
    WybaczoneNicPrzedWznowieniem, WybaczoneZaczeteWLogach, WybaczoneWersjaKoncowa, WybaczoneLogiZostaja

Biegi == 1..Wyceny
Zlecenia == 1..LiczbaZlecen
Przyczyny == {"przed-wpisem-konca", "wpis-konca-nieudany", "zapis-logow-nieudany", "wpis-nieudany"}

Tresci == [skonczone : SUBSET Zlecenia, zaczete : 0..LiczbaZlecen, tekst : {"surowe", "strzezone"}]
Pusta == [skonczone |-> {}, zaczete |-> 0, tekst |-> "strzezone"]
PlikiLogow == [rodzaj : {"brak", "wynik", "urwane"}, tresc : Tresci]
BrakLogow == [rodzaj |-> "brak", tresc |-> Pusta]
Wpisy == [rodzaj : {"zaczete", "skonczone", "koniec"}, z : Zlecenia]
Rodzaje == {"wynik", "urwane", "bezLogow"}
RodzajeWersji == Rodzaje \cup {"brak", "postep"}
ZLogami == {"wynik", "urwane"}
StopienPostepu == 0
StopienZeStartu == 1
StopienWlasny == 2
Stopnie == 0..2
Wersje == [rodzaj : RodzajeWersji, stopien : Stopnie, tejPracy : BOOLEAN, cofniety : BOOLEAN]
BrakWersji == [rodzaj |-> "brak", stopien |-> 0, tejPracy |-> FALSE, cofniety |-> FALSE]
Rekordy == [rodzaj : ZLogami, tresc : Tresci]
Oczekujace == [bieg : Biegi, rodzaj : Rodzaje, tresc : Tresci, niezapisany : BOOLEAN]
PrzedKoncemPostepu == {"zaczete", "efenix", "skonczone", "wynik", "koniec", "logi"}

VARIABLES
    dziennik,
    wpisy,
    logi,
    efenix,
    kolejka,
    najnowsza,
    centrum,
    wznowiona,
    kursor,
    krokZamykania,
    rekord,
    oczekujace,
    doWyslania,
    krokWysylki,
    bieg,
    faza,
    zlecenie,
    naglowekCzeka,
    wKolejce,
    nastepny,
    zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia,
    zapisanyStart,
    postepMozliwy,
    wynik,
    przepadle,
    bezKonca,
    zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty

dysk == <<dziennik, wpisy, logi, efenix, kolejka, najnowsza>>
pamiec == <<centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg, faza,
            zlecenie, naglowekCzeka, wKolejce>>
liczniki == <<nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki,
              awarieUsuniecia, cofniecia>>
duchy == <<zapisanyStart, postepMozliwy, wynik, przepadle, bezKonca>>
zdarzenia == <<zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty>>
vars == <<dysk, pamiec, liczniki, duchy, zdarzenia>>

Zdarz(stare, warunek, przyczyny) == IF warunek THEN stare \cup {przyczyny} ELSE stare

TypeOK ==
    /\ dziennik \in [Biegi -> {"brak", "bezStartu", "jest"}]
    /\ \A r \in Biegi : wpisy[r] \in Seq(Wpisy) /\ Len(wpisy[r]) <= 2 * LiczbaZlecen + 1
    /\ logi \in [Biegi -> PlikiLogow]
    /\ efenix \in [Biegi -> SUBSET Zlecenia]
    /\ kolejka \subseteq [bieg : Biegi, rodzaj : Rodzaje, tresc : Tresci]
    /\ najnowsza \in [Biegi -> Wersje]
    /\ centrum \in {"stoi", "zamyka", "wysyla", "dziala"}
    /\ wznowiona \in BOOLEAN
    /\ kursor \in 1..(Wyceny + 1)
    /\ krokZamykania \in {"czytaj", "zapisz", "usun"}
    /\ rekord \in Rekordy
    /\ oczekujace \in Seq(Oczekujace) /\ doWyslania \in Seq(Oczekujace)
    /\ krokWysylki \in {"post", "usun"}
    /\ bieg \in 0..Wyceny
    /\ faza \in {"-", "start", "zaczete", "efenix", "skonczone", "wynik", "koniec", "logi", "post", "zaLogami", "po"}
    /\ zlecenie \in Zlecenia
    /\ naglowekCzeka \in BOOLEAN
    /\ wKolejce \in BOOLEAN
    /\ nastepny \in 1..(Wyceny + 1)
    /\ cofniecia \in 0..MaxCofniecZegara
    /\ zapisanyStart \in [Biegi -> BOOLEAN] /\ postepMozliwy \in [Biegi -> BOOLEAN] /\ wynik \in [Biegi -> BOOLEAN]
    /\ przepadle \in [Biegi -> SUBSET Zlecenia]
    /\ bezKonca \in [Biegi -> SUBSET Przyczyny]
    /\ \A e \in {zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty} :
           e \subseteq SUBSET Przyczyny

Init ==
    /\ dziennik = [r \in Biegi |-> IF StareLogi /\ r = 1 THEN "jest" ELSE "brak"]
    /\ wpisy = [r \in Biegi |-> IF StareLogi /\ r = 1
                                THEN <<[rodzaj |-> "zaczete", z |-> 1], [rodzaj |-> "skonczone", z |-> 1]>>
                                ELSE <<>>]
    /\ logi = [r \in Biegi |-> IF StareLogi /\ r = 1
                               THEN [rodzaj |-> "urwane", tresc |-> [skonczone |-> {1}, zaczete |-> 0, tekst |-> "surowe"]]
                               ELSE BrakLogow]
    /\ efenix = [r \in Biegi |-> IF StareLogi /\ r = 1 THEN {1} ELSE {}]
    /\ kolejka = {}
    /\ najnowsza = [r \in Biegi |-> BrakWersji]
    /\ centrum = "stoi" /\ wznowiona = FALSE /\ kursor = 1 /\ krokZamykania = "czytaj"
    /\ rekord = [rodzaj |-> "urwane", tresc |-> Pusta]
    /\ oczekujace = <<>> /\ doWyslania = <<>> /\ krokWysylki = "post"
    /\ bieg = 0 /\ faza = "-" /\ zlecenie = 1 /\ naglowekCzeka = FALSE /\ wKolejce = FALSE
    /\ nastepny = IF StareLogi THEN 2 ELSE 1
    /\ zgasniecia = 0 /\ zatrzymania = 0 /\ awarieWpisu = 0 /\ awarieOdczytu = 0 /\ awarieLogow = 0 /\ awarieKolejki = 0
    /\ awarieUsuniecia = 0 /\ cofniecia = 0
    /\ zapisanyStart = [r \in Biegi |-> StareLogi /\ r = 1]
    /\ postepMozliwy = [r \in Biegi |-> StareLogi /\ r = 1]
    /\ wynik = [r \in Biegi |-> FALSE]
    /\ przepadle = [r \in Biegi |-> {}]
    /\ bezKonca = [r \in Biegi |-> {}]
    /\ zgubiony = {} /\ poWyniku = {} /\ inneZnaki = {} /\ bezStrazy = {} /\ przedWznowieniem = {} /\ bezZlecenia = {}
    /\ bezWersji = {} /\ wyparty = {}

ZWynikiem(r) == wynik[r]
Przyjete(r) == najnowsza[r].rodzaj = "urwane"
WynikPrzyjety(r) == \E p \in kolejka : p.bieg = r /\ p.rodzaj = "wynik"
Koncowa(r) == najnowsza[r].rodzaj \in Rodzaje
Wyparcie(stary, nowy) == (stary \in ZLogami /\ nowy \notin ZLogami) \/ (stary = "wynik" /\ nowy = "urwane")

Przyjmij(r, rodzaj, s) ==
    LET u == najnowsza[r] IN
    \E pozniej \in IF u.cofniety /\ ~u.tejPracy THEN BOOLEAN ELSE {TRUE} :
        LET nowsza == u.rodzaj = "brak" \/ s > u.stopien \/ (s = u.stopien /\ pozniej) IN
        /\ najnowsza' = IF nowsza
                        THEN [najnowsza EXCEPT ![r] = [rodzaj |-> rodzaj, stopien |-> s, tejPracy |-> TRUE,
                                                       cofniety |-> FALSE]]
                        ELSE najnowsza
        /\ wyparty' = Zdarz(wyparty, nowsza /\ Wyparcie(u.rodzaj, rodzaj), {})
Zakonczony(r) == \E i \in 1..Len(wpisy[r]) : wpisy[r][i].rodzaj = "koniec"
Niepokryte(r, t) == {z \in efenix[r] : z \notin t.skonczone /\ z # t.zaczete}
Pokrywa(r, t) == Niepokryte(r, t) = {}
PoWpisach(r, brakujace) == IF brakujace \subseteq przepadle[r] THEN {"wpis-nieudany"} ELSE {}

ZDziennika(r) ==
    LET w == wpisy[r]
        skonczone == {w[i].z : i \in {i \in 1..Len(w) : w[i].rodzaj = "skonczone"}}
    IN [skonczone |-> skonczone,
        zaczete |-> IF Len(w) > 0 /\ w[Len(w)].rodzaj = "zaczete" THEN w[Len(w)].z ELSE 0,
        tekst |-> IF TekstDoMaski /\ skonczone # {} THEN "surowe" ELSE "strzezone"]
Straz(t) == [t EXCEPT !.tekst = "strzezone"]

PoPoscie(h) ==
    /\ inneZnaki' = Zdarz(inneZnaki, h.rodzaj = logi[h.bieg].rodzaj /\ logi[h.bieg].tresc # h.tresc,
                          IF h.niezapisany THEN {"zapis-logow-nieudany"} ELSE {})
    /\ bezStrazy' = Zdarz(bezStrazy, h.tresc.tekst = "surowe", {})
    /\ przedWznowieniem' = Zdarz(przedWznowieniem, ~wznowiona, {})
    /\ bezZlecenia' = Zdarz(bezZlecenia, h.rodzaj = "urwane" /\ ~Pokrywa(h.bieg, h.tresc),
                            PoWpisach(h.bieg, Niepokryte(h.bieg, h.tresc)))

UsunPlik(r, przyczyny) ==
    \/ /\ dziennik' = [dziennik EXCEPT ![r] = "brak"] /\ wpisy' = [wpisy EXCEPT ![r] = <<>>]
       /\ zgubiony' = Zdarz(zgubiony, zapisanyStart[r] /\ ~ZWynikiem(r) /\ ~Przyjete(r), przyczyny)
       /\ bezWersji' = Zdarz(bezWersji, postepMozliwy[r] /\ ~Koncowa(r), przyczyny)
       /\ UNCHANGED awarieUsuniecia
    \/ /\ awarieUsuniecia < MaxAwariiUsuniecia /\ awarieUsuniecia' = awarieUsuniecia + 1
       /\ UNCHANGED <<dziennik, wpisy, zgubiony, bezWersji>>

Start ==
    /\ centrum = "stoi"
    /\ centrum' = "zamyka" /\ wznowiona' = FALSE /\ kursor' = 1 /\ krokZamykania' = "czytaj"
    /\ rekord' = [rodzaj |-> "urwane", tresc |-> Pusta]
    /\ oczekujace' = <<>> /\ doWyslania' = <<>> /\ krokWysylki' = "post"
    /\ bieg' = 0 /\ faza' = "-" /\ zlecenie' = 1 /\ naglowekCzeka' = FALSE /\ wKolejce' = FALSE
    /\ \E cofa \in IF cofniecia < MaxCofniecZegara THEN BOOLEAN ELSE {FALSE} :
        /\ cofniecia' = IF cofa THEN cofniecia + 1 ELSE cofniecia
        /\ najnowsza' = [r \in Biegi |-> [najnowsza[r] EXCEPT !.tejPracy = FALSE,
                                                             !.cofniety = @ \/ (cofa /\ najnowsza[r].rodzaj # "brak")]]
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, kolejka, nastepny, zgasniecia, zatrzymania, awarieWpisu,
                   awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia, duchy, zdarzenia>>

Odczytane(odczytany) == krokZamykania' = "zapisz" /\ rekord' = [odczytany EXCEPT !.tresc = Straz(@)]

Zbuduj(r) ==
    /\ Odczytane([rodzaj |-> "urwane", tresc |-> ZDziennika(r)])
    /\ poWyniku' = Zdarz(poWyniku, ZWynikiem(r), bezKonca[r] \ (IF WynikPrzyjety(r) THEN {"przed-wpisem-konca"} ELSE {}))

Czytaj ==
    LET r == kursor
        koniecZapisany == Zakonczony(r)
    IN
    /\ centrum = "zamyka" /\ kursor <= Wyceny /\ krokZamykania = "czytaj"
    /\ \/ /\ dziennik[r] = "brak"
          /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, oczekujace, awarieOdczytu, poWyniku>>
       \/ /\ dziennik[r] # "brak" /\ awarieOdczytu < MaxAwariiOdczytu
          /\ awarieOdczytu' = awarieOdczytu + 1 /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, oczekujace, poWyniku>>
       \/ /\ dziennik[r] = "bezStartu"
          /\ krokZamykania' = "usun"
          /\ UNCHANGED <<kursor, rekord, oczekujace, awarieOdczytu, poWyniku>>
       \/ /\ dziennik[r] = "jest" /\ logi[r].rodzaj \in ZLogami
          /\ Odczytane(logi[r])
          /\ UNCHANGED <<kursor, oczekujace, awarieOdczytu, poWyniku>>
       \/ /\ dziennik[r] = "jest" /\ logi[r].rodzaj = "brak" /\ koniecZapisany
          /\ oczekujace' = Append(oczekujace, [bieg |-> r, rodzaj |-> "bezLogow", tresc |-> Pusta,
                                               niezapisany |-> FALSE])
          /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, awarieOdczytu, poWyniku>>
       \/ /\ dziennik[r] = "jest" /\ logi[r].rodzaj = "brak" /\ ~koniecZapisany
          /\ Zbuduj(r)
          /\ UNCHANGED <<kursor, oczekujace, awarieOdczytu>>
    /\ UNCHANGED <<dysk, centrum, wznowiona, doWyslania, krokWysylki, bieg, faza, zlecenie, naglowekCzeka, wKolejce,
                   nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieLogow, awarieKolejki, awarieUsuniecia,
                   cofniecia, duchy, zgubiony, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty>>

ZapiszLogi ==
    /\ centrum = "zamyka" /\ krokZamykania = "zapisz"
    /\ \E niezapisany \in BOOLEAN :
        /\ IF niezapisany
           THEN awarieLogow < MaxAwariiLogow /\ awarieLogow' = awarieLogow + 1 /\ UNCHANGED logi
           ELSE logi' = [logi EXCEPT ![kursor] = rekord] /\ UNCHANGED awarieLogow
        /\ oczekujace' = Append(oczekujace, [bieg |-> kursor, rodzaj |-> rekord.rodzaj, tresc |-> rekord.tresc,
                                             niezapisany |-> niezapisany])
    /\ kursor' = kursor + 1 /\ krokZamykania' = "czytaj"
    /\ UNCHANGED <<dziennik, wpisy, efenix, kolejka, najnowsza, centrum, wznowiona, rekord, doWyslania, krokWysylki,
                   bieg, faza, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu,
                   awarieOdczytu, awarieKolejki, awarieUsuniecia, cofniecia, duchy, zdarzenia>>

UsunDziennik ==
    /\ centrum = "zamyka" /\ krokZamykania = "usun"
    /\ UsunPlik(kursor, {})
    /\ kursor' = kursor + 1 /\ krokZamykania' = "czytaj"
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, rekord, oczekujace, doWyslania, krokWysylki,
                   bieg, faza, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu,
                   awarieOdczytu, awarieLogow, awarieKolejki, cofniecia, duchy, poWyniku, inneZnaki, bezStrazy,
                   przedWznowieniem, bezZlecenia, wyparty>>

Wznow ==
    /\ centrum = "zamyka" /\ kursor > Wyceny /\ ~wznowiona
    /\ wznowiona' = TRUE
    /\ UNCHANGED <<dysk, centrum, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, liczniki, duchy, zdarzenia>>

WysylkaStartu ==
    /\ centrum = "zamyka" /\ kursor > Wyceny
    /\ wznowiona
    /\ doWyslania' = oczekujace /\ oczekujace' = <<>> /\ krokWysylki' = "post"
    /\ centrum' = IF oczekujace = <<>> THEN "dziala" ELSE "wysyla"
    /\ UNCHANGED <<dysk, wznowiona, kursor, krokZamykania, rekord, bieg, faza, zlecenie, naglowekCzeka, wKolejce,
                   liczniki, duchy, zdarzenia>>

Dalej ==
    /\ doWyslania' = Tail(doWyslania) /\ krokWysylki' = "post"
    /\ centrum' = IF Tail(doWyslania) = <<>> THEN "dziala" ELSE "wysyla"

Wyslij ==
    LET h == Head(doWyslania) IN
    /\ centrum = "wysyla" /\ krokWysylki = "post"
    /\ \/ /\ kolejka' = kolejka \cup {[bieg |-> h.bieg, rodzaj |-> h.rodzaj, tresc |-> h.tresc]}
          /\ Przyjmij(h.bieg, h.rodzaj, StopienZeStartu)
          /\ PoPoscie(h)
          /\ krokWysylki' = "usun"
          /\ UNCHANGED <<centrum, doWyslania, awarieKolejki>>
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ Dalej
          /\ UNCHANGED <<kolejka, najnowsza, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, wyparty>>
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, wznowiona, kursor, krokZamykania, rekord, oczekujace, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu,
                   awarieLogow, awarieUsuniecia, cofniecia, duchy, zgubiony, poWyniku, bezWersji>>

UsunPoWysylce ==
    /\ centrum = "wysyla" /\ krokWysylki = "usun"
    /\ UsunPlik(Head(doWyslania).bieg, {})
    /\ Dalej
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, wznowiona, kursor, krokZamykania, rekord, oczekujace, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu,
                   awarieLogow, awarieKolejki, cofniecia, duchy, poWyniku, inneZnaki, bezStrazy, przedWznowieniem,
                   bezZlecenia, wyparty>>

StartWyceny ==
    /\ centrum = "dziala" /\ bieg = 0 /\ nastepny <= Wyceny
    /\ bieg' = nastepny /\ nastepny' = nastepny + 1 /\ faza' = "start" /\ zlecenie' = 1 /\ naglowekCzeka' = TRUE
    /\ wKolejce' = FALSE
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki,
                   zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia,
                   cofniecia, duchy, zdarzenia>>

ZapiszStart ==
    LET r == bieg IN
    /\ bieg # 0 /\ faza = "start"
    /\ \/ /\ dziennik' = [dziennik EXCEPT ![r] = "jest"]
          /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = TRUE]
          /\ postepMozliwy' = [postepMozliwy EXCEPT ![r] = TRUE]
          /\ naglowekCzeka' = FALSE
          /\ UNCHANGED awarieWpisu
       \/ /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
          /\ UNCHANGED <<dziennik, zapisanyStart, postepMozliwy, naglowekCzeka>>
       \/ /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
          /\ dziennik' = [dziennik EXCEPT ![r] = "jest"]
          /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = TRUE]
          /\ UNCHANGED <<postepMozliwy, naglowekCzeka>>
    /\ faza' = "zaczete"
    /\ UNCHANGED <<wpisy, logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, wKolejce, nastepny, zgasniecia, zatrzymania,
                   awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia, wynik, przepadle, bezKonca,
                   zdarzenia>>

Wpis(rodzaj) ==
    LET r == bieg IN
    \/ /\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> rodzaj, z |-> zlecenie])]
       /\ dziennik' = [dziennik EXCEPT ![r] = IF naglowekCzeka THEN "jest" ELSE IF @ = "brak" THEN "bezStartu" ELSE @]
       /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = @ \/ naglowekCzeka]
       /\ postepMozliwy' = [postepMozliwy EXCEPT ![r] = TRUE]
       /\ naglowekCzeka' = FALSE
       /\ UNCHANGED <<awarieWpisu, przepadle>>
    \/ /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
       /\ przepadle' = [przepadle EXCEPT ![r] = @ \cup {zlecenie}]
       /\ UNCHANGED <<wpisy, dziennik, zapisanyStart, postepMozliwy, naglowekCzeka>>
    \/ /\ naglowekCzeka /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
       /\ przepadle' = [przepadle EXCEPT ![r] = @ \cup {zlecenie}]
       /\ dziennik' = [dziennik EXCEPT ![r] = "jest"]
       /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = TRUE]
       /\ UNCHANGED <<wpisy, postepMozliwy, naglowekCzeka>>

WpisZaczete ==
    /\ bieg # 0 /\ faza = "zaczete"
    /\ Wpis("zaczete")
    /\ faza' = "efenix"
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, zlecenie, wKolejce, nastepny, zgasniecia, zatrzymania, awarieOdczytu,
                   awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia, wynik, bezKonca, zdarzenia>>

ZmianaWEfenix ==
    /\ bieg # 0 /\ faza = "efenix"
    /\ efenix' = [efenix EXCEPT ![bieg] = @ \cup {zlecenie}]
    /\ faza' = "skonczone"
    /\ UNCHANGED <<dziennik, wpisy, logi, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, wKolejce, liczniki, duchy,
                   zdarzenia>>

WpisSkonczone ==
    /\ bieg # 0 /\ faza = "skonczone"
    /\ Wpis("skonczone")
    /\ IF zlecenie < LiczbaZlecen
       THEN zlecenie' = zlecenie + 1 /\ faza' = "zaczete"
       ELSE faza' = "wynik" /\ UNCHANGED zlecenie
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, wKolejce, nastepny, zgasniecia, zatrzymania, awarieOdczytu,
                   awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia, wynik, bezKonca, zdarzenia>>

Zatrzymanie ==
    /\ bieg # 0 /\ faza \in {"zaczete", "efenix", "skonczone"} /\ zatrzymania < MaxZatrzyman
    /\ zatrzymania' = zatrzymania + 1
    /\ faza' = "wynik"
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg,
                   zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, awarieWpisu, awarieOdczytu, awarieLogow,
                   awarieKolejki, awarieUsuniecia, cofniecia, duchy, zdarzenia>>

Postep ==
    /\ bieg # 0 /\ ~naglowekCzeka /\ faza \in PrzedKoncemPostepu
    /\ Przyjmij(bieg, "postep", StopienPostepu)
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, kolejka, pamiec, liczniki, duchy, zgubiony, poWyniku, inneZnaki,
                   bezStrazy, przedWznowieniem, bezZlecenia, bezWersji>>

Wynik ==
    /\ bieg # 0 /\ faza = "wynik"
    /\ wynik' = [wynik EXCEPT ![bieg] = TRUE]
    /\ faza' = "koniec"
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg,
                   zlecenie, naglowekCzeka, wKolejce, liczniki, zapisanyStart, postepMozliwy, przepadle, bezKonca,
                   zdarzenia>>

WpisKonca ==
    LET r == bieg IN
    /\ bieg # 0 /\ faza = "koniec"
    /\ \/ /\ naglowekCzeka /\ dziennik[r] = "brak"
          /\ UNCHANGED <<dziennik, wpisy, awarieWpisu, awarieUsuniecia, zgubiony, bezKonca, bezWersji>>
       \/ /\ naglowekCzeka /\ dziennik[r] = "jest"
          /\ UsunPlik(r, {})
          /\ bezKonca' = IF dziennik'[r] = "brak" THEN bezKonca
                         ELSE [bezKonca EXCEPT ![r] = @ \cup {"wpis-konca-nieudany"}]
          /\ UNCHANGED awarieWpisu
       \/ /\ ~naglowekCzeka
          /\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> "koniec", z |-> zlecenie])]
          /\ UNCHANGED <<dziennik, awarieWpisu, awarieUsuniecia, zgubiony, bezKonca, bezWersji>>
       \/ /\ ~naglowekCzeka /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
          /\ bezKonca' = [bezKonca EXCEPT ![r] = @ \cup {"wpis-konca-nieudany"}]
          /\ UNCHANGED <<dziennik, wpisy, awarieUsuniecia, zgubiony, bezWersji>>
    /\ faza' = "logi" /\ UNCHANGED bieg
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania,
                   awarieOdczytu, awarieLogow, awarieKolejki, cofniecia, zapisanyStart, postepMozliwy, wynik,
                   przepadle, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, wyparty>>

LogiWyniku ==
    /\ bieg # 0 /\ faza = "logi"
    /\ \/ logi' = [logi EXCEPT ![bieg] = [rodzaj |-> "wynik", tresc |-> Pusta]] /\ UNCHANGED awarieLogow
       \/ awarieLogow < MaxAwariiLogow /\ awarieLogow' = awarieLogow + 1 /\ UNCHANGED logi
    /\ faza' = "post"
    /\ UNCHANGED <<dziennik, wpisy, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia,
                   zatrzymania, awarieWpisu, awarieOdczytu, awarieKolejki, awarieUsuniecia, cofniecia, duchy,
                   zdarzenia>>

WyslijWynik ==
    /\ bieg # 0 /\ faza = "post"
    /\ \/ /\ kolejka' = kolejka \cup {[bieg |-> bieg, rodzaj |-> "wynik", tresc |-> Pusta]}
          /\ Przyjmij(bieg, "wynik", StopienWlasny)
          /\ przedWznowieniem' = Zdarz(przedWznowieniem, ~wznowiona, {})
          /\ wKolejce' = TRUE
          /\ UNCHANGED awarieKolejki
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ UNCHANGED <<kolejka, najnowsza, przedWznowieniem, wKolejce, wyparty>>
    /\ faza' = "zaLogami"
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, nastepny, zgasniecia, zatrzymania,
                   awarieWpisu, awarieOdczytu, awarieLogow, awarieUsuniecia, cofniecia, duchy, zgubiony, poWyniku,
                   inneZnaki, bezStrazy, bezZlecenia, bezWersji>>

UsunPoLogach ==
    /\ bieg # 0 /\ faza = "zaLogami"
    /\ IF wKolejce /\ ~naglowekCzeka
       THEN UsunPlik(bieg, {})
       ELSE UNCHANGED <<dziennik, wpisy, zgubiony, bezWersji, awarieUsuniecia>>
    /\ faza' = "po"
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania,
                   awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki, cofniecia, duchy, poWyniku, inneZnaki,
                   bezStrazy, przedWznowieniem, bezZlecenia, wyparty>>

KoniecUruchomienia ==
    /\ bieg # 0 /\ faza = "po"
    /\ bieg' = 0 /\ faza' = "-"
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, zlecenie,
                   naglowekCzeka, wKolejce, liczniki, duchy, zdarzenia>>

Zgasniecie ==
    /\ centrum # "stoi" /\ zgasniecia < MaxZgasniec
    /\ zgasniecia' = zgasniecia + 1
    /\ \E urwany \in BOOLEAN :
        dziennik' = IF urwany /\ bieg # 0 /\ faza \in {"start", "zaczete", "skonczone"} /\ naglowekCzeka
                       /\ dziennik[bieg] = "brak"
                    THEN [dziennik EXCEPT ![bieg] = "bezStartu"]
                    ELSE dziennik
    /\ bezZlecenia' = IF bieg # 0 /\ ~ZWynikiem(bieg) /\ efenix[bieg] # {} /\ ~zapisanyStart[bieg]
                      THEN bezZlecenia \cup {PoWpisach(bieg, efenix[bieg])}
                      ELSE bezZlecenia
    /\ bezKonca' = IF bieg # 0 /\ faza = "koniec" /\ dziennik[bieg] = "jest"
                   THEN [bezKonca EXCEPT ![bieg] = @ \cup {"przed-wpisem-konca"}]
                   ELSE bezKonca
    /\ bezWersji' = Zdarz(bezWersji, bieg # 0 /\ postepMozliwy[bieg] /\ ~zapisanyStart[bieg], {})
    /\ centrum' = "stoi" /\ wznowiona' = FALSE /\ bieg' = 0 /\ faza' = "-" /\ oczekujace' = <<>> /\ doWyslania' = <<>>
    /\ wKolejce' = FALSE
    /\ UNCHANGED <<wpisy, logi, efenix, kolejka, najnowsza, kursor, krokZamykania, rekord, krokWysylki, zlecenie,
                   naglowekCzeka, nastepny, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki,
                   awarieUsuniecia, cofniecia, zapisanyStart, postepMozliwy, wynik, przepadle, zgubiony, poWyniku,
                   inneZnaki, bezStrazy, przedWznowieniem, wyparty>>

Zamkniecie ==
    /\ centrum = "dziala" /\ bieg = 0
    /\ centrum' = "stoi"
    /\ UNCHANGED <<dysk, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, liczniki, duchy, zdarzenia>>

Next ==
    \/ Start \/ Czytaj \/ ZapiszLogi \/ UsunDziennik \/ Wznow \/ WysylkaStartu \/ Wyslij \/ UsunPoWysylce
    \/ StartWyceny \/ ZapiszStart \/ WpisZaczete \/ ZmianaWEfenix \/ WpisSkonczone \/ Zatrzymanie \/ Postep \/ Wynik
    \/ WpisKonca \/ LogiWyniku \/ WyslijWynik \/ UsunPoLogach \/ KoniecUruchomienia \/ Zgasniecie \/ Zamkniecie

Sprawiedliwosc ==
    /\ WF_vars(Start) /\ WF_vars(Czytaj) /\ WF_vars(ZapiszLogi) /\ WF_vars(UsunDziennik) /\ WF_vars(Wznow)
    /\ WF_vars(WysylkaStartu) /\ WF_vars(Wyslij) /\ WF_vars(UsunPoWysylce) /\ WF_vars(ZapiszStart)
    /\ WF_vars(WpisZaczete) /\ WF_vars(ZmianaWEfenix) /\ WF_vars(WpisSkonczone) /\ WF_vars(Wynik) /\ WF_vars(WpisKonca)
    /\ WF_vars(LogiWyniku) /\ WF_vars(WyslijWynik) /\ WF_vars(UsunPoLogach) /\ WF_vars(KoniecUruchomienia)
    /\ WF_vars(Zamkniecie)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

DziennikPoKolejce == zgubiony = {}
BezUrwanychPoWyniku == poWyniku = {}
TeSameZnaki == inneZnaki = {}
PrzezStraznika == bezStrazy = {}
NicPrzedWznowieniem == przedWznowieniem = {}
ZaczeteWLogach == bezZlecenia = {}
WersjaKoncowa == bezWersji = {}
LogiZostaja == wyparty = {}
Zbieganie == <>[](\A r \in Biegi : dziennik[r] = "brak")

Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
DziennikPoKolejcePozaZnanymi == Wybaczone(zgubiony, WybaczoneDziennikPoKolejce)
BezUrwanychPoWynikuPozaZnanymi == Wybaczone(poWyniku, WybaczoneBezUrwanychPoWyniku)
TeSameZnakiPozaZnanymi == Wybaczone(inneZnaki, WybaczoneTeSameZnaki)
PrzezStraznikaPozaZnanymi == Wybaczone(bezStrazy, WybaczonePrzezStraznika)
NicPrzedWznowieniemPozaZnanymi == Wybaczone(przedWznowieniem, WybaczoneNicPrzedWznowieniem)
ZaczeteWLogachPozaZnanymi == Wybaczone(bezZlecenia, WybaczoneZaczeteWLogach)
WersjaKoncowaPozaZnanymi == Wybaczone(bezWersji, WybaczoneWersjaKoncowa)
LogiZostajaPozaZnanymi == Wybaczone(wyparty, WybaczoneLogiZostaja)
=========================================================================================================================
