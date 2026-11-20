------------------------------ MODULE WpisanieRaportow ------------------------------
EXTENDS Naturals, FiniteSets

CONSTANTS
    Karty,
    MaxZgasniec,
    MaxAwariiIntermax,
    MaxAwariiPamieci,
    MaxAwariiWyniku,
    MaxAwariiDecyzji,
    MozeOtworzyc,
    MozeKopia,
    WybaczoneNieNadpisuje, WybaczoneZostawUcisza, WybaczoneBezFalszywejRoznicy, WybaczoneKopiaZatrzymuje

Brak == "brak"
Pusta == "pusta"
Wpisy == {"A", "B"}
Reczne == Wpisy
Komorki == {Pusta} \cup Reczne
Pamieci == {Brak} \cup Wpisy
KartyZ == 1..Karty
Fazy == {"wolne", "sprawdzone", "zapisane", "pamiec"}
Etapy == {"nic", "sprawdzona", "czyta"}
Ponowienia(czeka) == IF czeka THEN {"udany", "nieudany"} ELSE {"bez"}
Zapisy == {"udany", "nieudany"}
MozeZawiesc(z, czeka, awarie, max) == z = "nieudany" => (czeka \/ awarie < max)
Nieudane(z, czeka) == IF z = "nieudany" /\ ~czeka THEN 1 ELSE 0
Przyczyny == {"przywrocona-wartosc", "przywrocona-ze-starej-pamieci", "przed-pamiecia", "pamiec-odlozona",
              "okres-otwarty-ponownie", "decyzja-odlozona", "przy-sprawdzaniu", "po-zapisie"}

VARIABLES
    komorka,
    autor,
    wpis,
    okresOtwarty,
    kopia,
    pamiec, pamiecCzeka, pamiecOdlozona,
    wynik, wynikCzeka, wynikOdlozony,
    decyzje, decyzjeCzeka, decyzjeOdlozone,
    faza, migPamiec, migDecyzje, kopiaPrzySprawdzaniu,
    planPamiec, planRoznica, planZapisal, planFalszywa, planPrzyczyny, planZapomina,
    etap, tresc, odczyt, blokada,
    ostatniWlasny,
    zapomniala,
    zapomnialaCzeka,
    utrataPamieci,
    bezPamieci,
    upuszczona,
    zostawione,
    zgasniecia, awarieIntermax, awariePamieci, awarieWyniku, awarieDecyzji,
    nadpisane, falszywe, bezDecyzji, przeoczonaKopia

swiat == <<komorka, autor, wpis, okresOtwarty, kopia>>
plikPamieci == <<pamiec, pamiecCzeka, pamiecOdlozona>>
plikWyniku == <<wynik, wynikCzeka, wynikOdlozony>>
plikDecyzji == <<decyzje, decyzjeCzeka, decyzjeOdlozone>>
klik == <<faza, migPamiec, migDecyzje, kopiaPrzySprawdzaniu, planPamiec, planRoznica, planZapisal, planFalszywa,
          planPrzyczyny, planZapomina>>
karty == <<etap, tresc, odczyt, blokada>>
duchy == <<ostatniWlasny, zapomniala, zapomnialaCzeka, utrataPamieci, bezPamieci, upuszczona, zostawione>>
liczniki == <<zgasniecia, awarieIntermax, awariePamieci, awarieWyniku, awarieDecyzji>>
zdarzenia == <<nadpisane, falszywe, bezDecyzji, przeoczonaKopia>>
vars == <<swiat, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy, liczniki, zdarzenia>>

PamiecEfektywna == IF pamiecCzeka THEN pamiecOdlozona ELSE pamiec
PokazanaRoznica == IF wynikCzeka THEN wynikOdlozony ELSE wynik
DecyzjeWidoku == IF decyzjeCzeka THEN decyzjeOdlozone ELSE decyzje
PamiecWlasciwa == IF faza = "zapisane" THEN planPamiec ELSE PamiecEfektywna

TypeOK ==
    /\ komorka \in Komorki /\ autor \in {"nikt", "narzedzie", "tata"} /\ wpis \in Pamieci
    /\ okresOtwarty \in BOOLEAN /\ kopia \in BOOLEAN
    /\ pamiec \in Pamieci /\ pamiecCzeka \in BOOLEAN /\ pamiecOdlozona \in Pamieci
    /\ wynik \in Pamieci /\ wynikCzeka \in BOOLEAN /\ wynikOdlozony \in Pamieci
    /\ decyzje \subseteq Wpisy /\ decyzjeCzeka \in BOOLEAN /\ decyzjeOdlozone \subseteq Wpisy
    /\ faza \in Fazy /\ migPamiec \in Pamieci /\ migDecyzje \subseteq Wpisy /\ kopiaPrzySprawdzaniu \in BOOLEAN
    /\ planPamiec \in Pamieci /\ planRoznica \in Pamieci /\ planZapisal \in BOOLEAN /\ planFalszywa \in BOOLEAN
    /\ planPrzyczyny \subseteq Przyczyny /\ planZapomina \in BOOLEAN
    /\ etap \in [KartyZ -> Etapy] /\ tresc \in [KartyZ -> Pamieci] /\ odczyt \in [KartyZ -> SUBSET Wpisy]
    /\ blokada \in 0..Karty
    /\ ostatniWlasny \in Pamieci /\ zapomniala \in BOOLEAN /\ zapomnialaCzeka \in BOOLEAN
    /\ utrataPamieci \in BOOLEAN /\ bezPamieci \subseteq Przyczyny /\ upuszczona \in BOOLEAN /\ zostawione \subseteq Wpisy
    /\ zgasniecia \in 0..MaxZgasniec /\ awarieIntermax \in 0..MaxAwariiIntermax /\ awariePamieci \in 0..MaxAwariiPamieci
    /\ awarieWyniku \in 0..MaxAwariiWyniku /\ awarieDecyzji \in 0..MaxAwariiDecyzji
    /\ nadpisane \subseteq SUBSET Przyczyny /\ falszywe \subseteq SUBSET Przyczyny
    /\ bezDecyzji \subseteq Przyczyny /\ przeoczonaKopia \subseteq SUBSET Przyczyny

KlikWolny ==
    /\ faza' = "wolne" /\ migPamiec' = Brak /\ migDecyzje' = {} /\ kopiaPrzySprawdzaniu' = FALSE
    /\ planPamiec' = Brak /\ planRoznica' = Brak /\ planZapisal' = FALSE /\ planFalszywa' = FALSE
    /\ planPrzyczyny' = {} /\ planZapomina' = FALSE

Init ==
    /\ komorka = Pusta /\ autor = "nikt" /\ wpis = Brak /\ okresOtwarty = TRUE /\ kopia = FALSE
    /\ pamiec = Brak /\ pamiecCzeka = FALSE /\ pamiecOdlozona = Brak
    /\ wynik = Brak /\ wynikCzeka = FALSE /\ wynikOdlozony = Brak
    /\ decyzje = {} /\ decyzjeCzeka = FALSE /\ decyzjeOdlozone = {}
    /\ faza = "wolne" /\ migPamiec = Brak /\ migDecyzje = {} /\ kopiaPrzySprawdzaniu = FALSE
    /\ planPamiec = Brak /\ planRoznica = Brak /\ planZapisal = FALSE /\ planFalszywa = FALSE
    /\ planPrzyczyny = {} /\ planZapomina = FALSE
    /\ etap = [k \in KartyZ |-> "nic"] /\ tresc = [k \in KartyZ |-> Brak] /\ odczyt = [k \in KartyZ |-> {}]
    /\ blokada = 0
    /\ ostatniWlasny = Brak /\ zapomniala = FALSE /\ zapomnialaCzeka = FALSE /\ utrataPamieci = FALSE
    /\ bezPamieci = {} /\ upuszczona = FALSE /\ zostawione = {}
    /\ zgasniecia = 0 /\ awarieIntermax = 0 /\ awariePamieci = 0 /\ awarieWyniku = 0 /\ awarieDecyzji = 0
    /\ nadpisane = {} /\ falszywe = {} /\ bezDecyzji = {} /\ przeoczonaKopia = {}

BezZmian == ~okresOtwarty \/ wpis = Brak \/ (komorka # Pusta /\ komorka = wpis)
Zmiana == IF ~BezZmian /\ (komorka = Pusta \/ komorka = migPamiec) THEN wpis ELSE Brak
Roznica == IF ~BezZmian /\ Zmiana = Brak /\ wpis \notin migDecyzje THEN wpis ELSE Brak
NowaPamiec ==
    IF Zmiana # Brak THEN Zmiana
    ELSE IF okresOtwarty /\ migPamiec # Brak /\ migPamiec = komorka THEN migPamiec
    ELSE Brak

TataZmienia(v) ==
    /\ v \in Komorki /\ v # komorka
    /\ komorka' = v
    /\ autor' = IF v = Pusta THEN "nikt" ELSE "tata"
    /\ upuszczona' = FALSE
    /\ UNCHANGED <<wpis, okresOtwarty, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, ostatniWlasny,
                   zapomniala, zapomnialaCzeka, utrataPamieci, bezPamieci, zostawione, liczniki, zdarzenia>>

NowyMail(w) ==
    /\ w \in Wpisy /\ w # wpis
    /\ wpis' = w
    /\ UNCHANGED <<komorka, autor, okresOtwarty, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy,
                   liczniki, zdarzenia>>

ZamkniecieOkresu ==
    /\ okresOtwarty /\ okresOtwarty' = FALSE
    /\ UNCHANGED <<komorka, autor, wpis, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy, liczniki,
                   zdarzenia>>

OtwarcieOkresu ==
    /\ MozeOtworzyc /\ ~okresOtwarty /\ okresOtwarty' = TRUE
    /\ UNCHANGED <<komorka, autor, wpis, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy, liczniki,
                   zdarzenia>>

PojawiaSieKopia ==
    /\ MozeKopia /\ ~kopia /\ kopia' = TRUE
    /\ UNCHANGED <<komorka, autor, wpis, okresOtwarty, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy,
                   liczniki, zdarzenia>>

TataUsuwaKopie ==
    /\ kopia /\ kopia' = FALSE
    /\ UNCHANGED <<komorka, autor, wpis, okresOtwarty, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy,
                   liczniki, zdarzenia>>

Sprawdzanie ==
    /\ faza = "wolne"
    /\ \E p \in Ponowienia(pamiecCzeka), d \in Ponowienia(decyzjeCzeka) :
        /\ pamiec' = IF p = "udany" THEN pamiecOdlozona ELSE pamiec
        /\ pamiecCzeka' = (p = "nieudany")
        /\ pamiecOdlozona' = IF p = "nieudany" THEN pamiecOdlozona ELSE Brak
        /\ zapomniala' = IF p = "udany" THEN zapomniala \/ zapomnialaCzeka ELSE zapomniala
        /\ zapomnialaCzeka' = (p = "nieudany" /\ zapomnialaCzeka)
        /\ decyzje' = IF d = "udany" THEN decyzjeOdlozone ELSE decyzje
        /\ decyzjeCzeka' = (d = "nieudany")
        /\ decyzjeOdlozone' = IF d = "nieudany" THEN decyzjeOdlozone ELSE {}
        /\ LET zatrzymanie == kopia IN
           IF zatrzymanie
           THEN KlikWolny
           ELSE /\ faza' = "sprawdzone"
                /\ migPamiec' = PamiecEfektywna
                /\ migDecyzje' = DecyzjeWidoku
                /\ kopiaPrzySprawdzaniu' = kopia
                /\ UNCHANGED <<planPamiec, planRoznica, planZapisal, planFalszywa, planPrzyczyny, planZapomina>>
    /\ UNCHANGED <<swiat, plikWyniku, karty, ostatniWlasny, utrataPamieci, bezPamieci, upuszczona, zostawione,
                   liczniki, zdarzenia>>

PrzyczynaNadpisania ==
    IF komorka = ostatniWlasny /\ ~zapomniala /\ ~zapomnialaCzeka /\ ~utrataPamieci THEN {"przywrocona-wartosc"}
    ELSE IF utrataPamieci THEN {"przywrocona-ze-starej-pamieci"}
    ELSE {}

Zapis ==
    /\ faza = "sprawdzone"
    /\ LET zmiana == Zmiana
           roznica == Roznica
       IN \/ /\ zmiana # Brak /\ awarieIntermax < MaxAwariiIntermax
             /\ awarieIntermax' = awarieIntermax + 1
             /\ KlikWolny
             /\ UNCHANGED <<swiat, duchy, zgasniecia, awariePamieci, awarieWyniku, awarieDecyzji, zdarzenia>>
          \/ /\ faza' = "zapisane"
             /\ komorka' = IF zmiana = Brak THEN komorka ELSE zmiana
             /\ autor' = IF zmiana = Brak THEN autor ELSE "narzedzie"
             /\ ostatniWlasny' = IF zmiana = Brak THEN ostatniWlasny ELSE zmiana
             /\ planPamiec' = NowaPamiec
             /\ planRoznica' = roznica
             /\ planZapisal' = (zmiana # Brak)
             /\ planZapomina' = (zmiana = Brak /\ okresOtwarty /\ ostatniWlasny # Brak /\ komorka # ostatniWlasny)
             /\ planFalszywa' = (roznica # Brak /\ autor = "narzedzie")
             /\ planPrzyczyny' = bezPamieci \cup (IF upuszczona THEN {"okres-otwarty-ponownie"} ELSE {})
             /\ zapomniala' = IF zmiana = Brak THEN zapomniala ELSE FALSE
             /\ zapomnialaCzeka' = IF zmiana = Brak THEN zapomnialaCzeka ELSE FALSE
             /\ bezPamieci' = IF zmiana = Brak THEN bezPamieci ELSE {}
             /\ utrataPamieci' = IF zmiana = Brak THEN utrataPamieci ELSE FALSE
             /\ upuszczona' =
                    IF zmiana # Brak THEN FALSE
                    ELSE upuszczona \/ (~okresOtwarty /\ autor = "narzedzie" /\ migPamiec = komorka)
             /\ nadpisane' = nadpisane \cup (IF zmiana # Brak /\ autor = "tata" THEN {PrzyczynaNadpisania} ELSE {})
             /\ przeoczonaKopia' = przeoczonaKopia \cup (IF kopiaPrzySprawdzaniu THEN {{"przy-sprawdzaniu"}} ELSE {})
             /\ migPamiec' = Brak /\ migDecyzje' = {} /\ kopiaPrzySprawdzaniu' = FALSE
             /\ UNCHANGED <<wpis, okresOtwarty, kopia, zostawione, liczniki, falszywe, bezDecyzji>>
    /\ UNCHANGED <<plikPamieci, plikWyniku, plikDecyzji, karty>>

ZapiszPamiec ==
    /\ faza = "zapisane"
    /\ faza' = "pamiec"
    /\ \E z \in Zapisy :
        /\ MozeZawiesc(z, pamiecCzeka, awariePamieci, MaxAwariiPamieci)
        /\ awariePamieci' = awariePamieci + Nieudane(z, pamiecCzeka)
        /\ IF z = "udany"
           THEN /\ pamiec' = planPamiec /\ pamiecCzeka' = FALSE /\ pamiecOdlozona' = Brak
                /\ zapomniala' = (zapomniala \/ zapomnialaCzeka \/ planZapomina) /\ zapomnialaCzeka' = FALSE
           ELSE /\ pamiecCzeka' = TRUE /\ pamiecOdlozona' = planPamiec /\ UNCHANGED pamiec
                /\ zapomnialaCzeka' = (zapomnialaCzeka \/ planZapomina) /\ UNCHANGED zapomniala
    /\ UNCHANGED <<swiat, plikWyniku, plikDecyzji, migPamiec, migDecyzje, kopiaPrzySprawdzaniu, planPamiec, planRoznica,
                   planZapisal, planFalszywa, planPrzyczyny, planZapomina, karty, ostatniWlasny, utrataPamieci,
                   bezPamieci, upuszczona, zostawione, zgasniecia, awarieIntermax, awarieWyniku, awarieDecyzji,
                   zdarzenia>>

ZapiszWynik ==
    /\ faza = "pamiec"
    /\ \E z \in Zapisy :
        /\ MozeZawiesc(z, wynikCzeka, awarieWyniku, MaxAwariiWyniku)
        /\ awarieWyniku' = awarieWyniku + Nieudane(z, wynikCzeka)
        /\ IF z = "udany"
           THEN wynik' = planRoznica /\ wynikCzeka' = FALSE /\ wynikOdlozony' = Brak
           ELSE wynikCzeka' = TRUE /\ wynikOdlozony' = planRoznica /\ UNCHANGED wynik
    /\ falszywe' = falszywe \cup (IF planFalszywa THEN {planPrzyczyny} ELSE {})
    /\ LET zatrzymanie == kopia IN
       przeoczonaKopia' = przeoczonaKopia \cup (IF ~zatrzymanie /\ kopia THEN {{"po-zapisie"}} ELSE {})
    /\ KlikWolny
    /\ UNCHANGED <<swiat, plikPamieci, plikDecyzji, karty, duchy, zgasniecia, awarieIntermax, awariePamieci,
                   awarieDecyzji, nadpisane, bezDecyzji>>

Odswiez ==
    /\ wynikCzeka \/ decyzjeCzeka
    /\ \E w \in Ponowienia(wynikCzeka), d \in Ponowienia(decyzjeCzeka) :
        /\ wynik' = IF w = "udany" THEN wynikOdlozony ELSE wynik
        /\ wynikCzeka' = (w = "nieudany")
        /\ wynikOdlozony' = IF w = "nieudany" THEN wynikOdlozony ELSE Brak
        /\ decyzje' = IF d = "udany" THEN decyzjeOdlozone ELSE decyzje
        /\ decyzjeCzeka' = (d = "nieudany")
        /\ decyzjeOdlozone' = IF d = "nieudany" THEN decyzjeOdlozone ELSE {}
    /\ UNCHANGED <<swiat, plikPamieci, klik, karty, duchy, liczniki, zdarzenia>>

ZostawSprawdz(k) ==
    /\ etap[k] = "nic" /\ PokazanaRoznica # Brak
    /\ etap' = [etap EXCEPT ![k] = "sprawdzona"]
    /\ tresc' = [tresc EXCEPT ![k] = PokazanaRoznica]
    /\ UNCHANGED <<swiat, plikPamieci, plikWyniku, plikDecyzji, klik, odczyt, blokada, duchy, liczniki, zdarzenia>>

ZostawCzytaj(k) ==
    /\ etap[k] = "sprawdzona"
    /\ blokada = 0
    /\ blokada' = k
    /\ etap' = [etap EXCEPT ![k] = "czyta"]
    /\ odczyt' = [odczyt EXCEPT ![k] = DecyzjeWidoku]
    /\ UNCHANGED <<swiat, plikPamieci, plikWyniku, plikDecyzji, klik, tresc, duchy, liczniki, zdarzenia>>

ZostawZapisz(k) ==
    /\ etap[k] = "czyta"
    /\ blokada' = 0
    /\ etap' = [etap EXCEPT ![k] = "nic"]
    /\ LET nowe == odczyt[k] \cup {tresc[k]} IN
       /\ \E z \in Zapisy :
           /\ MozeZawiesc(z, decyzjeCzeka, awarieDecyzji, MaxAwariiDecyzji)
           /\ awarieDecyzji' = awarieDecyzji + Nieudane(z, decyzjeCzeka)
           /\ IF z = "udany"
              THEN decyzje' = nowe /\ decyzjeCzeka' = FALSE /\ decyzjeOdlozone' = {}
              ELSE decyzjeCzeka' = TRUE /\ decyzjeOdlozone' = nowe /\ UNCHANGED decyzje
       /\ zostawione' = zostawione \cup {tresc[k]}
       /\ bezDecyzji' = IF zostawione \cup {tresc[k]} \subseteq nowe THEN {} ELSE bezDecyzji
    /\ UNCHANGED <<swiat, plikPamieci, plikWyniku, klik, tresc, odczyt, ostatniWlasny, zapomniala,
                   zapomnialaCzeka, utrataPamieci, bezPamieci, upuszczona, zgasniecia, awarieIntermax, awariePamieci,
                   awarieWyniku, nadpisane, falszywe, przeoczonaKopia>>

Zgasniecie ==
    /\ zgasniecia < MaxZgasniec
    /\ zgasniecia' = zgasniecia + 1
    /\ KlikWolny
    /\ pamiec' = pamiec /\ pamiecCzeka' = FALSE /\ pamiecOdlozona' = Brak
    /\ wynikCzeka' = FALSE /\ wynikOdlozony' = Brak
    /\ decyzjeCzeka' = FALSE /\ decyzjeOdlozone' = {}
    /\ etap' = [k \in KartyZ |-> "nic"] /\ tresc' = [k \in KartyZ |-> Brak] /\ odczyt' = [k \in KartyZ |-> {}]
    /\ blokada' = 0
    /\ zapomnialaCzeka' = FALSE
    /\ utrataPamieci' = (utrataPamieci \/ PamiecWlasciwa # pamiec')
    /\ bezPamieci' = bezPamieci
                     \cup (IF faza = "zapisane" /\ planZapisal THEN {"przed-pamiecia"} ELSE {})
                     \cup (IF pamiecCzeka /\ pamiecOdlozona = ostatniWlasny /\ pamiec # ostatniWlasny
                           THEN {"pamiec-odlozona"} ELSE {})
    /\ bezDecyzji' = bezDecyzji
                     \cup (IF decyzjeCzeka /\ (zostawione \cap decyzjeOdlozone) \ decyzje # {}
                           THEN {"decyzja-odlozona"} ELSE {})
    /\ UNCHANGED <<swiat, wynik, decyzje, ostatniWlasny, zapomniala, upuszczona, zostawione,
                   awarieIntermax, awariePamieci, awarieWyniku, awarieDecyzji, nadpisane, falszywe, przeoczonaKopia>>

Next ==
    \/ \E v \in Komorki : TataZmienia(v)
    \/ \E w \in Wpisy : NowyMail(w)
    \/ ZamkniecieOkresu \/ OtwarcieOkresu \/ PojawiaSieKopia \/ TataUsuwaKopie
    \/ Sprawdzanie \/ Zapis \/ ZapiszPamiec \/ ZapiszWynik \/ Odswiez
    \/ \E k \in KartyZ : ZostawSprawdz(k)
    \/ \E k \in KartyZ : ZostawCzytaj(k)
    \/ \E k \in KartyZ : ZostawZapisz(k)
    \/ Zgasniecie

Spec == Init /\ [][Next]_vars

NieNadpisuje == nadpisane = {}
Widoczna == PokazanaRoznica # Brak /\ PokazanaRoznica \notin DecyzjeWidoku
ZostawUcisza == ~(Widoczna /\ PokazanaRoznica \in zostawione)
BezFalszywejRoznicy == falszywe = {}
KopiaZatrzymuje == przeoczonaKopia = {}

Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
NieNadpisujePozaZnanymi == Wybaczone(nadpisane, WybaczoneNieNadpisuje)
ZostawUciszaPozaZnanymi == ZostawUcisza \/ bezDecyzji \cap WybaczoneZostawUcisza # {}
BezFalszywejRoznicyPozaZnanymi == Wybaczone(falszywe, WybaczoneBezFalszywejRoznicy)
KopiaZatrzymujePozaZnanymi == Wybaczone(przeoczonaKopia, WybaczoneKopiaZatrzymuje)
=========================================================================================================================
