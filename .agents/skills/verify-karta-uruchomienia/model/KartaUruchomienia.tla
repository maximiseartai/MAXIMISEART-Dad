------------------------------ MODULE KartaUruchomienia ------------------------------
EXTENDS Integers, Sequences, FiniteSets

CONSTANTS
    Czesc,
    MaxStartow,
    DrugaKarta,
    MozeDecyzja,
    MozeZatrzymac,
    MaxRestartow,
    MaxNieczytelnych,
    MaxZerwan,
    MaxWejsc,
    MaxZaladowan,
    MaxAktualizacji,
    WybaczonePrzyciskWraca, WybaczoneWynikNaKarcie, WybaczoneAktualizacjaNieWraca

Uruchomienia == 1..MaxStartow
Brak == 0
Widok(s, r, p, k) == [stan |-> s, run |-> r, prev |-> p, konc |-> k]
Pusty == Widok("null", Brak, Brak, "-")
Bezczynny(p) == Widok("idle", Brak, p, "-")
StanyWidoku == {"null", "idle", "trwa", "decyzja", "wynik"}
Widoki == [stan : StanyWidoku, run : 0..MaxStartow, prev : 0..MaxStartow, konc : {"-", "wynik", "zatrzymane"}]

ShownRun(v) == IF v.stan \in {"null", "idle"} THEN Brak ELSE v.run
AwaitsDecision(v, r) == v.stan = "decyzja" /\ v.run = r
IsActive(v) == v.stan \in {"trwa", "decyzja"}
Ended(v) == v.stan \in {"idle", "wynik"}

StanyAktualizacji == {"idle", "running", "updated", "failed"}

ZnaneZnaleziska == {"cudze-uruchomienie-przed-odpowiedzia", "restart-przed-odpowiedzia", "druga-karta",
                    "wybor-przed-wynikiem", "stary-odczyt", "stary-odczyt-petli"}

VARIABLES
    inst,
    dziala,
    srvRun,
    srvStan,
    srvKonc,
    srvPytal,
    prev,
    log,
    baza,
    proby, nieczyt, zerwan, restartow,
    widok,
    nieczytelny,
    rozlaczony,
    draft,
    odlozony,
    polaczenie,
    widziane,
    startuje,
    decyduje,
    aSrv,
    aNr,
    upd,
    instRef,
    startA,
    odczyty,
    petla,
    wejsc, zaladowan,
    kto,
    przedWynikiem,
    odczytane,
    wybralPo,
    widzialTrwa,
    slady,
    zaslonietyWynik, wrocilPrzycisk

serwer == <<inst, dziala, srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, proby, nieczyt, zerwan, restartow>>
karta == <<widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, startuje, decyduje>>
aktualizacja == <<aSrv, aNr, upd, instRef, startA, odczyty, petla, wejsc, zaladowan>>
pomocnicze == <<kto, przedWynikiem, odczytane, wybralPo, widzialTrwa, slady>>
vars == <<serwer, karta, aktualizacja, pomocnicze, zaslonietyWynik, wrocilPrzycisk>>

Zdarzenie == {{}} \cup {{s} : s \in SUBSET ZnaneZnaleziska}

NieStartuje == [faza |-> "nie", przed |-> Brak, id |-> Brak, wynik |-> Brak, inst |-> 0]
NieDecyduje == [faza |-> "nie", run |-> Brak, wynik |-> "-"]
Nic == [faza |-> "nie", odp |-> "-", nr |-> 0]

TypeOK ==
    /\ inst \in 0..(MaxRestartow + MaxAktualizacji) /\ dziala \in BOOLEAN
    /\ srvRun \in 0..MaxStartow /\ srvStan \in {"trwa", "decyzja", "wynik"} /\ srvKonc \in {"-", "wynik", "zatrzymane"}
    /\ prev \in 0..MaxStartow /\ \A i \in 1..Len(log) : log[i].w \in Widoki /\ log[i].czyt \in BOOLEAN
    /\ widok \in Widoki /\ nieczytelny \in BOOLEAN /\ rozlaczony \in BOOLEAN /\ draft \in BOOLEAN
    /\ odlozony \in 0..MaxStartow /\ polaczenie \in {"otwarte", "brak"}
    /\ startuje.faza \in {"nie", "wyslany", "odpowiedz", "czeka"}
    /\ decyduje.faza \in {"nie", "wyslany", "odpowiedz", "czeka"}
    /\ aSrv \in StanyAktualizacji /\ upd \in StanyAktualizacji \cup {"null"}
    /\ startA.faza \in {"nie", "zdrowie", "wyslany", "odpowiedz"}
    /\ \A i \in 1..MaxWejsc : odczyty[i].faza \in {"nie", "wyslany", "odpowiedz", "zrobiony"}
    /\ petla.faza \in {"nie", "zdrowie", "wyslany", "odpowiedz"}
    /\ zaslonietyWynik \in Zdarzenie /\ wrocilPrzycisk \in Zdarzenie

Run(v) == IF v.stan = "idle" THEN v.prev ELSE v.run
SetupInstead(v) == Run(v) = Brak \/ (Ended(v) /\ (Run(v) = odlozony \/ draft))
Panel ==
    IF widok.stan = "null" THEN "szkielet"
    ELSE IF SetupInstead(widok) THEN "start"
    ELSE IF widok.stan = "idle" THEN "ostatnie"
    ELSE widok.stan

SrvWidok == IF srvRun = Brak THEN Bezczynny(prev) ELSE Widok(srvStan, srvRun, Brak, srvKonc)
OstatniNr == baza + Len(log) - 1
Czytelnosci == IF nieczyt < MaxNieczytelnych THEN BOOLEAN ELSE {TRUE}
Publikuj(v, c) == /\ log' = Append(log, [w |-> v, czyt |-> c])
                  /\ nieczyt' = IF c THEN nieczyt ELSE nieczyt + 1

Uruchom == Czesc = "uruchomienia"
Aktualizuj == Czesc = "aktualizacja"

Init ==
    /\ inst = 0 /\ dziala = TRUE
    /\ srvRun = Brak /\ srvStan = "wynik" /\ srvKonc = "-" /\ srvPytal = FALSE /\ prev = Brak
    /\ log = <<[w |-> Bezczynny(Brak), czyt |-> TRUE]>> /\ baza = 0
    /\ proby = 0 /\ nieczyt = 0 /\ zerwan = 0 /\ restartow = 0
    /\ widok = Pusty /\ nieczytelny = FALSE /\ rozlaczony = FALSE /\ draft = FALSE /\ odlozony = Brak
    /\ polaczenie = "otwarte" /\ widziane = -1
    /\ startuje = NieStartuje /\ decyduje = NieDecyduje
    /\ aSrv = "idle" /\ aNr = 0 /\ upd = "null" /\ instRef = -1 /\ startA = [faza |-> "nie", odp |-> "-"]
    /\ odczyty = [i \in 1..MaxWejsc |-> Nic] /\ petla = Nic /\ wejsc = 0 /\ zaladowan = 0
    /\ kto = [r \in Uruchomienia |-> "-"] /\ przedWynikiem = {} /\ odczytane = {} /\ wybralPo = {} /\ widzialTrwa = FALSE /\ slady = {}
    /\ zaslonietyWynik = {} /\ wrocilPrzycisk = {}

Busy == startA.faza # "nie" \/ upd = "running"
AktTrwa == aSrv = "running" \/ ~dziala
Odp(s) == IF dziala THEN s ELSE "blad"

Zasloniety == /\ widok.stan = "wynik" /\ Panel = "start" /\ widok.run \notin wybralPo
              /\ startuje.faza \notin {"wyslany", "odpowiedz"}
PrzyczynyZasloniecia(r) == (IF kto[r] = "inna" THEN {"druga-karta"} ELSE {})
                           \cup (IF r \in przedWynikiem THEN {"wybor-przed-wynikiem"} ELSE {})
Wrocil == AktTrwa /\ widzialTrwa /\ ~Busy

Historia ==
    /\ zaslonietyWynik' = IF zaslonietyWynik = {} /\ Zasloniety'
                          THEN {slady' \cup PrzyczynyZasloniecia(widok'.run)} ELSE zaslonietyWynik
    /\ wrocilPrzycisk' = IF wrocilPrzycisk = {} /\ Wrocil' THEN {slady'} ELSE wrocilPrzycisk

KlikStart ==
    /\ Uruchom /\ ~IsActive(widok) /\ startuje.faza = "nie" /\ proby < MaxStartow
    /\ proby' = proby + 1
    /\ startuje' = [faza |-> "wyslany", przed |-> ShownRun(widok), id |-> proby + 1, wynik |-> Brak, inst |-> inst]
    /\ UNCHANGED <<inst, dziala, srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, nieczyt, zerwan, restartow>>
    /\ UNCHANGED <<widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, decyduje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

KlikDecyzja ==
    /\ Uruchom /\ Panel = "decyzja" /\ decyduje.faza = "nie"
    /\ decyduje' = [faza |-> "wyslany", run |-> widok.run, wynik |-> "-"]
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, startuje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

NoweUruchomienie ==
    /\ Uruchom /\ Panel \in {"wynik", "ostatnie"}
    /\ odlozony' = Run(widok)
    /\ wybralPo' = wybralPo \cup {Run(widok)}
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, draft, polaczenie, widziane, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, kto, odczytane, przedWynikiem, widzialTrwa, slady>>
    /\ Historia

WybierzNowe ==
    /\ draft' = TRUE
    /\ wybralPo' = IF widok.stan = "wynik" THEN wybralPo \cup {widok.run} ELSE wybralPo
    /\ przedWynikiem' = przedWynikiem \cup {r \in Uruchomienia : kto[r] # "-" /\ r \notin odczytane}
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, odlozony, polaczenie, widziane, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, kto, odczytane, widzialTrwa, slady>>
    /\ Historia
WyborNaKarcieStartu == Uruchom /\ Panel = "start" /\ WybierzNowe
WyborSpozaKarty == Uruchom /\ WybierzNowe

OdpowiedzStartu ==
    /\ Uruchom /\ startuje.faza = "odpowiedz"
    /\ IF startuje.wynik = Brak
       THEN /\ startuje' = NieStartuje /\ UNCHANGED <<draft, slady>>
       ELSE /\ draft' = FALSE
            /\ IF ShownRun(widok) = startuje.wynik
               THEN startuje' = NieStartuje /\ UNCHANGED slady
               ELSE /\ startuje' = [startuje EXCEPT !.faza = "czeka"]
                    /\ slady' = slady
                         \cup (IF ShownRun(widok) \notin {startuje.przed, startuje.wynik}
                               THEN {"cudze-uruchomienie-przed-odpowiedzia"} ELSE {})
                         \cup (IF inst # startuje.inst THEN {"restart-przed-odpowiedzia"} ELSE {})
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, odlozony, polaczenie, widziane, decyduje>>
    /\ UNCHANGED <<aktualizacja, kto, odczytane, przedWynikiem, wybralPo, widzialTrwa>>
    /\ Historia

OdpowiedzDecyzji ==
    /\ Uruchom /\ decyduje.faza = "odpowiedz"
    /\ decyduje' = IF decyduje.wynik = "blad" \/ ~AwaitsDecision(widok, decyduje.run)
                   THEN NieDecyduje ELSE [decyduje EXCEPT !.faza = "czeka"]
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, startuje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

Odbierz ==
    /\ Uruchom /\ dziala /\ polaczenie = "otwarte" /\ widziane < OstatniNr
    /\ LET nr == IF widziane + 1 < baza THEN baza ELSE widziane + 1
           e == log[nr - baza + 1]
       IN /\ widziane' = nr
          /\ IF e.czyt
             THEN /\ widok' = e.w /\ nieczytelny' = FALSE
                  /\ odczytane' = IF e.w.stan = "wynik" THEN odczytane \cup {e.w.run} ELSE odczytane
                  /\ startuje' = IF startuje.faza = "czeka" /\ (ShownRun(e.w) # startuje.przed \/ e.w.stan = "idle")
                                 THEN NieStartuje ELSE startuje
                  /\ decyduje' = IF decyduje.faza = "czeka" /\ ~AwaitsDecision(e.w, decyduje.run)
                                 THEN NieDecyduje ELSE decyduje
             ELSE /\ nieczytelny' = TRUE /\ UNCHANGED <<widok, startuje, decyduje, odczytane>>
    /\ UNCHANGED <<serwer, rozlaczony, draft, odlozony, polaczenie>>
    /\ UNCHANGED <<aktualizacja, kto, przedWynikiem, wybralPo, widzialTrwa, slady>>
    /\ Historia

Zerwij ==
    /\ Uruchom /\ polaczenie = "otwarte" /\ zerwan < MaxZerwan
    /\ zerwan' = zerwan + 1 /\ polaczenie' = "brak" /\ rozlaczony' = TRUE
    /\ UNCHANGED <<inst, dziala, srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, proby, nieczyt, restartow>>
    /\ UNCHANGED <<widok, nieczytelny, draft, odlozony, widziane, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

Polacz ==
    /\ Uruchom /\ dziala /\ polaczenie = "brak"
    /\ polaczenie' = "otwarte" /\ rozlaczony' = FALSE /\ widziane' = OstatniNr - 1
    /\ UNCHANGED <<serwer, widok, nieczytelny, draft, odlozony, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

Zajety == srvRun # Brak /\ srvStan # "wynik"
Przyjmij(r, kto2) ==
    /\ srvRun' = r /\ srvStan' = "trwa" /\ srvKonc' = "-" /\ srvPytal' = FALSE
    /\ baza' = OstatniNr
    /\ \E c \in Czytelnosci :
           /\ log' = <<log[Len(log)], [w |-> Widok("trwa", r, Brak, "-"), czyt |-> c]>>
           /\ nieczyt' = IF c THEN nieczyt ELSE nieczyt + 1
    /\ kto' = [kto EXCEPT ![r] = kto2]

ObslugaStartu ==
    /\ Uruchom /\ dziala /\ startuje.faza = "wyslany"
    /\ IF Zajety
       THEN /\ startuje' = [startuje EXCEPT !.faza = "odpowiedz", !.wynik = Brak]
            /\ UNCHANGED <<srvRun, srvStan, srvKonc, srvPytal, log, baza, nieczyt, kto>>
       ELSE /\ Przyjmij(startuje.id, "ta")
            /\ startuje' = [startuje EXCEPT !.faza = "odpowiedz", !.wynik = startuje.id, !.inst = inst]
    /\ UNCHANGED <<inst, dziala, prev, proby, zerwan, restartow>>
    /\ UNCHANGED <<widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, decyduje>>
    /\ UNCHANGED <<aktualizacja, odczytane, przedWynikiem, wybralPo, widzialTrwa, slady>>
    /\ Historia

Odpowiedz(r) ==
    /\ srvStan' = "trwa"
    /\ \E c \in Czytelnosci : Publikuj(Widok("trwa", r, Brak, "-"), c)

ObslugaDecyzji ==
    /\ Uruchom /\ dziala /\ decyduje.faza = "wyslany"
    /\ IF srvRun = decyduje.run /\ srvStan = "decyzja"
       THEN /\ Odpowiedz(srvRun) /\ decyduje' = [decyduje EXCEPT !.faza = "odpowiedz", !.wynik = "ok"]
       ELSE /\ decyduje' = [decyduje EXCEPT !.faza = "odpowiedz", !.wynik = "blad"]
            /\ UNCHANGED <<srvStan, log, nieczyt>>
    /\ UNCHANGED <<inst, dziala, srvRun, srvKonc, srvPytal, prev, baza, proby, zerwan, restartow>>
    /\ UNCHANGED <<widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, startuje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

InnaKartaStart ==
    /\ Uruchom /\ DrugaKarta /\ dziala /\ ~Zajety /\ proby < MaxStartow
    /\ proby' = proby + 1 /\ Przyjmij(proby + 1, "inna")
    /\ UNCHANGED <<inst, dziala, prev, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, odczytane, przedWynikiem, wybralPo, widzialTrwa, slady>>
    /\ Historia

InnaKartaDecyzja ==
    /\ Uruchom /\ DrugaKarta /\ dziala /\ srvRun # Brak /\ srvStan = "decyzja"
    /\ Odpowiedz(srvRun)
    /\ UNCHANGED <<inst, dziala, srvRun, srvKonc, srvPytal, prev, baza, proby, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

PytanieODecyzje ==
    /\ Uruchom /\ MozeDecyzja /\ dziala /\ srvRun # Brak /\ srvStan = "trwa" /\ ~srvPytal
    /\ srvStan' = "decyzja" /\ srvPytal' = TRUE
    /\ \E c \in Czytelnosci : Publikuj(Widok("decyzja", srvRun, Brak, "-"), c)
    /\ UNCHANGED <<inst, dziala, srvRun, srvKonc, prev, baza, proby, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

KoniecUruchomienia ==
    /\ Uruchom /\ dziala /\ srvRun # Brak /\ srvStan = "trwa"
    /\ \E k \in (IF MozeZatrzymac THEN {"wynik", "zatrzymane"} ELSE {"wynik"}), c \in Czytelnosci :
           /\ srvStan' = "wynik" /\ srvKonc' = k
           /\ Publikuj(Widok("wynik", srvRun, Brak, k), c)
    /\ UNCHANGED <<inst, dziala, srvRun, srvPytal, prev, baza, proby, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

Restart ==
    /\ Uruchom /\ restartow < MaxRestartow
    /\ restartow' = restartow + 1 /\ inst' = inst + 1
    /\ prev' = IF srvRun # Brak THEN srvRun ELSE prev
    /\ srvRun' = Brak /\ srvStan' = "wynik" /\ srvKonc' = "-" /\ srvPytal' = FALSE
    /\ \E c \in Czytelnosci :
           /\ log' = <<[w |-> Bezczynny(IF srvRun # Brak THEN srvRun ELSE prev), czyt |-> c]>>
           /\ nieczyt' = IF c THEN nieczyt ELSE nieczyt + 1
    /\ baza' = 0
    /\ polaczenie' = "brak" /\ rozlaczony' = TRUE
    /\ startuje' = IF startuje.faza = "wyslany" THEN [startuje EXCEPT !.faza = "odpowiedz", !.wynik = Brak]
                   ELSE startuje
    /\ decyduje' = IF decyduje.faza = "wyslany" THEN [decyduje EXCEPT !.faza = "odpowiedz", !.wynik = "blad"]
                   ELSE decyduje
    /\ UNCHANGED <<dziala, proby, zerwan, widok, nieczytelny, draft, odlozony, widziane>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

Pokaz(s) ==
    /\ upd' = s
    /\ widzialTrwa' = (widzialTrwa \/ s = "running")
Slad(s, nr, przyczyna) ==
    slady' = IF nr < aNr /\ AktTrwa /\ s # "running" THEN slady \cup {przyczyna} ELSE slady

KlikAktualizuj ==
    /\ Aktualizuj /\ ~Busy /\ aNr < MaxAktualizacji
    /\ startA' = [faza |-> "zdrowie", odp |-> "-"]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, odczyty, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

ZdrowieStartu ==
    /\ Aktualizuj /\ startA.faza = "zdrowie"
    /\ IF dziala THEN /\ instRef' = inst /\ startA' = [faza |-> "wyslany", odp |-> "-"]
                 ELSE /\ startA' = [faza |-> "nie", odp |-> "-"] /\ UNCHANGED instRef
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, odczyty, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

ObslugaStartuAkt ==
    /\ Aktualizuj /\ dziala /\ startA.faza = "wyslany"
    /\ IF aSrv = "running"
       THEN /\ startA' = [faza |-> "odpowiedz", odp |-> "odmowa"] /\ UNCHANGED <<aSrv, aNr>>
       ELSE /\ aSrv' = "running" /\ aNr' = aNr + 1 /\ startA' = [faza |-> "odpowiedz", odp |-> "running"]
    /\ UNCHANGED <<serwer, karta, upd, instRef, odczyty, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

KoniecStartuAkt ==
    /\ Aktualizuj /\ startA.faza = "odpowiedz"
    /\ startA' = [faza |-> "nie", odp |-> "-"]
    /\ IF startA.odp = "running" THEN Pokaz("running") ELSE UNCHANGED <<upd, widzialTrwa>>
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, instRef, odczyty, petla, wejsc, zaladowan, kto, odczytane, przedWynikiem, wybralPo, slady>>
    /\ Historia

Wejscie ==
    /\ Aktualizuj /\ wejsc < MaxWejsc
    /\ wejsc' = wejsc + 1
    /\ odczyty' = [odczyty EXCEPT ![wejsc + 1] = [faza |-> "wyslany", odp |-> "-", nr |-> 0]]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, startA, petla, zaladowan, pomocnicze>>
    /\ Historia

ObslugaOdczytu(i) ==
    /\ Aktualizuj /\ odczyty[i].faza = "wyslany"
    /\ odczyty' = [odczyty EXCEPT ![i] = [faza |-> "odpowiedz", odp |-> Odp(aSrv), nr |-> aNr]]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, startA, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

OdbierzOdczyt(i) ==
    /\ Aktualizuj /\ odczyty[i].faza = "odpowiedz"
    /\ odczyty' = [odczyty EXCEPT ![i].faza = "zrobiony"]
    /\ IF odczyty[i].odp = "blad" THEN UNCHANGED <<upd, widzialTrwa, slady>>
       ELSE Pokaz(odczyty[i].odp) /\ Slad(odczyty[i].odp, odczyty[i].nr, "stary-odczyt")
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, instRef, startA, petla, wejsc, zaladowan, kto, odczytane, przedWynikiem, wybralPo>>
    /\ Historia

Tik ==
    /\ Aktualizuj /\ upd = "running" /\ petla.faza = "nie"
    /\ petla' = [faza |-> "zdrowie", odp |-> "-", nr |-> 0]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, startA, odczyty, wejsc, zaladowan, pomocnicze>>
    /\ Historia

Zaladuj ==
    /\ zaladowan' = zaladowan + 1
    /\ upd' = "null" /\ instRef' = -1 /\ startA' = [faza |-> "nie", odp |-> "-"] /\ petla' = Nic
    /\ odczyty' = [i \in 1..MaxWejsc |-> IF i = 1 THEN [faza |-> "wyslany", odp |-> "-", nr |-> 0] ELSE Nic]
    /\ wejsc' = 1 /\ widzialTrwa' = FALSE

ZdrowiePetli ==
    /\ Aktualizuj /\ petla.faza = "zdrowie"
    /\ (dziala /\ instRef # -1 /\ inst # instRef) => zaladowan < MaxZaladowan
    /\ IF ~dziala
       THEN /\ petla' = Nic /\ Pokaz("running")
            /\ UNCHANGED <<instRef, startA, odczyty, wejsc, zaladowan, slady>>
       ELSE IF instRef # -1 /\ inst # instRef
       THEN /\ Zaladuj /\ UNCHANGED slady
       ELSE /\ petla' = [faza |-> "wyslany", odp |-> "-", nr |-> 0]
            /\ instRef' = IF instRef = -1 THEN inst ELSE instRef
            /\ UNCHANGED <<upd, startA, odczyty, wejsc, zaladowan, widzialTrwa, slady>>
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, kto, odczytane, przedWynikiem, wybralPo>>
    /\ Historia

ObslugaPetli ==
    /\ Aktualizuj /\ petla.faza = "wyslany"
    /\ petla' = [faza |-> "odpowiedz", odp |-> Odp(aSrv), nr |-> aNr]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, startA, odczyty, wejsc, zaladowan, pomocnicze>>
    /\ Historia

OdbierzPetli ==
    /\ Aktualizuj /\ petla.faza = "odpowiedz"
    /\ petla' = Nic
    /\ LET s == IF petla.odp = "blad" THEN "running" ELSE petla.odp
       IN Pokaz(s) /\ Slad(s, petla.nr, "stary-odczyt-petli")
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, instRef, startA, odczyty, wejsc, zaladowan, kto, odczytane, przedWynikiem, wybralPo>>
    /\ Historia

AktPorazka ==
    /\ Aktualizuj /\ dziala /\ aSrv = "running"
    /\ aSrv' = "failed" /\ widzialTrwa' = FALSE
    /\ UNCHANGED <<serwer, karta, aNr, upd, instRef, startA, odczyty, petla, wejsc, zaladowan>>
    /\ UNCHANGED <<kto, odczytane, przedWynikiem, wybralPo, slady>>
    /\ Historia

AktZamkniecie ==
    /\ Aktualizuj /\ dziala /\ aSrv = "running"
    /\ dziala' = FALSE
    /\ UNCHANGED <<inst, srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, proby, nieczyt, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

AktPonownyStart ==
    /\ Aktualizuj /\ ~dziala
    /\ dziala' = TRUE /\ inst' = inst + 1
    /\ \E s \in {"updated", "failed"} : aSrv' = s
    /\ widzialTrwa' = FALSE
    /\ UNCHANGED <<srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, proby, nieczyt, zerwan, restartow>>
    /\ UNCHANGED <<karta, aNr, upd, instRef, startA, odczyty, petla, wejsc, zaladowan>>
    /\ UNCHANGED <<kto, odczytane, przedWynikiem, wybralPo, slady>>
    /\ Historia

Next ==
    \/ KlikStart \/ KlikDecyzja \/ NoweUruchomienie \/ WyborNaKarcieStartu \/ WyborSpozaKarty
    \/ OdpowiedzStartu \/ OdpowiedzDecyzji \/ Odbierz \/ Zerwij \/ Polacz
    \/ ObslugaStartu \/ ObslugaDecyzji \/ InnaKartaStart \/ InnaKartaDecyzja \/ PytanieODecyzje
    \/ KoniecUruchomienia \/ Restart
    \/ KlikAktualizuj \/ ZdrowieStartu \/ ObslugaStartuAkt \/ KoniecStartuAkt \/ Wejscie
    \/ \E i \in 1..MaxWejsc : ObslugaOdczytu(i)
    \/ \E i \in 1..MaxWejsc : OdbierzOdczyt(i)
    \/ Tik \/ ZdrowiePetli \/ ObslugaPetli \/ OdbierzPetli \/ AktPorazka \/ AktZamkniecie \/ AktPonownyStart

Sprawiedliwosc ==
    /\ WF_vars(Odbierz) /\ WF_vars(Polacz) /\ WF_vars(OdpowiedzStartu) /\ WF_vars(OdpowiedzDecyzji)
    /\ WF_vars(ObslugaStartu) /\ WF_vars(ObslugaDecyzji) /\ WF_vars(KoniecUruchomienia)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

CzytelnyWidok == log[Len(log)].czyt
PrzyciskWraca ==
    <>[]CzytelnyWidok => /\ (startuje.faza # "nie" ~> startuje.faza = "nie")
                         /\ (decyduje.faza # "nie" ~> decyduje.faza = "nie")
WynikNaKarcie == zaslonietyWynik = {}
AktualizacjaNieWraca == wrocilPrzycisk = {}

Wybaczone(zdarzenie, wybaczone) == \E s \in zdarzenie : s \cap wybaczone # {}
PrzyciskWracaPozaZnanymi == PrzyciskWraca \/ <>(slady \cap WybaczonePrzyciskWraca # {})
WynikNaKarciePozaZnanymi == WynikNaKarcie \/ Wybaczone(zaslonietyWynik, WybaczoneWynikNaKarcie)
AktualizacjaNieWracaPozaZnanymi == AktualizacjaNieWraca \/ Wybaczone(wrocilPrzycisk, WybaczoneAktualizacjaNieWraca)
==========================================================================================================
