------------------------------------------------ MODULE HistoriaUstawien ------------------------------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Poczatek,
    MaxZmian,
    MaxCofniec,
    MaxRecznych,
    MaxZgasniec,
    MaxAwariiZapisuPliku,
    MaxAwariiWiersza,
    MaxAwariiPrzywrocenia,
    MaxAwariiPamieci,
    MaxAwariiPamieciZmian,
    MaxNieczytelnejPamieci,
    MaxNieczytelnejHistorii,
    WybaczoneLiczyZapisanym, WybaczoneWydanieNieNadpisuje, WybaczoneNieZapisanoZnaczyNie, WybaczoneCofnijPrzywracaBajty

ZLY == "zly"
DOMYSLNA == "d"
BRAK == "brak"
CEL_WYDANIA == "r"
Dobre == {"v0", "r", "t", "x", DOMYSLNA}
Tresci == {"v0", "r", "t", "x", ZLY, DOMYSLNA, BRAK}
Wartosc(tresc) == IF tresc = BRAK THEN DOMYSLNA ELSE tresc
WartosciTaty == {"t", "r"}
Reczne == {"x", ZLY}
Zrodla == {"tata", "wydanie", "spoza"}
Wiersze == [zrodlo : Zrodla, wynik : {"zapisano", "odrzucono"}, przed : Dobre, po : Dobre \cup {ZLY}, cofalny : BOOLEAN,
            utworzono : BOOLEAN]
Przyczyny == {"wiersz-odczytu-nieudany", "pamiec-bez-odczytu", "zly-plik-bez-pamieci", "zgasniecie-przed-pamiecia",
              "pamiec-niezapisana",
              "bez-zmian-bez-pamieci", "wiersz-i-przywrocenie-nieudane", "zgasniecie-przed-wierszem-wydania",
              "przywrocenie-nieudane"}
Kroki == {"-", "porownaj", "wierszSpoza", "pamiecSpoza", "porownane", "zapis", "wiersz", "przywroc", "niezapisane",
          "pamiec", "pamiecZmian"}
Kto == {"-", "proces", "tata", "wydanie"}
Wyniki == {"-", "zastosowano", "bez-zmian", "z-historii"}
Bezczynne == [pc |-> "-", kto |-> "-", etap |-> "-", cel |-> "v0", dane |-> "v0", dobry |-> "v0", obs |-> "v0",
              obsDobra |-> TRUE, sciezka |-> "-", nowa |-> "v0", wiersz |-> FALSE, zapisane |-> FALSE,
              przywrocenie |-> "-", tataPrzed |-> FALSE, zWydania |-> FALSE, wynik |-> "-", cofa |-> FALSE,
              usun |-> FALSE, widzianyBrak |-> FALSE]

VARIABLES
    plik,
    pamiec,
    historia,
    zmianyZWydan,
    faza,
    op,
    zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
    nieczPamieci, nieczHistorii,
    weszla,
    wydanieWPliku,
    wartoscTaty,
    bezZmianNiezapamietane,
    przywrocenieWydaniaNieudane,
    zgasniecieWydania,
    pamiecZaWierszem,
    bezWiersza, nadpisane, klamstwo, zleBajty

dysk == <<plik, pamiec, historia, zmianyZWydan>>
liczniki == <<zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
              nieczPamieci, nieczHistorii>>
duchy == <<weszla, wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania,
           pamiecZaWierszem>>
zdarzenia == <<bezWiersza, nadpisane, klamstwo, zleBajty>>
vars == <<dysk, faza, op, liczniki, duchy, zdarzenia>>

Zapisane == SelectSeq(historia, LAMBDA w : w.wynik = "zapisano")
Wyjasniona(u) == IF Len(Zapisane) = 0 THEN u = Wartosc(Poczatek) ELSE Zapisane[Len(Zapisane)].po = u

WierszSpozaCentrum(dane, dobry, utworzono) ==
    IF dane = ZLY THEN [zrodlo |-> "spoza", wynik |-> "odrzucono", przed |-> Wartosc(dobry), po |-> ZLY, cofalny |-> FALSE,
                        utworzono |-> utworzono]
    ELSE [zrodlo |-> "spoza", wynik |-> "zapisano", przed |-> Wartosc(dobry), po |-> Wartosc(dane),
          cofalny |-> Wartosc(dobry) # Wartosc(dane), utworzono |-> utworzono]

Koniec == faza' = "wolny" /\ op' = Bezczynne

TypeOK ==
    /\ plik \in Tresci
    /\ pamiec \in [widziany : Tresci, dobry : Tresci \ {ZLY}]
    /\ historia \in Seq(Wiersze)
    /\ zmianyZWydan \in BOOLEAN
    /\ faza \in {"start", "historiaWydan", "wolny", "praca"}
    /\ op.pc \in Kroki /\ op.kto \in Kto /\ op.etap \in {"-", "obserwacja", "zmiana"}
    /\ op.cel \in Dobre /\ op.dane \in Tresci /\ op.dobry \in Tresci \ {ZLY} /\ op.obs \in Dobre /\ op.nowa \in Tresci
    /\ op.sciezka \in {"-"} \cup Przyczyny /\ op.przywrocenie \in {"-", "ok", "nieudane"} /\ op.wynik \in Wyniki
    /\ \A b \in {op.obsDobra, op.wiersz, op.zapisane, op.tataPrzed, op.zWydania, op.cofa, op.usun,
                  op.widzianyBrak} : b \in BOOLEAN
    /\ (faza = "praca") = (op.pc # "-")
    /\ \A b \in {weszla, wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane,
                  zgasniecieWydania} : b \in BOOLEAN
    /\ pamiecZaWierszem \in {"-", "zgasniecie", "awaria"}
    /\ \A e \in {bezWiersza, nadpisane, klamstwo, zleBajty} : e \subseteq SUBSET Przyczyny

Init ==
    /\ plik = Poczatek /\ pamiec = [widziany |-> Poczatek, dobry |-> Poczatek] /\ historia = <<>>
    /\ zmianyZWydan = FALSE
    /\ faza = "start" /\ op = Bezczynne
    /\ zmiany = 0 /\ cofniecia = 0 /\ reczne = 0 /\ zgasniecia = 0 /\ awZapisu = 0 /\ awWiersza = 0
    /\ awPrzywrocenia = 0 /\ awPamieci = 0 /\ awPamieciZmian = 0 /\ nieczPamieci = 0 /\ nieczHistorii = 0
    /\ weszla = FALSE /\ wydanieWPliku = FALSE /\ wartoscTaty = FALSE /\ bezZmianNiezapamietane = FALSE
    /\ przywrocenieWydaniaNieudane = FALSE
    /\ zgasniecieWydania = FALSE /\ pamiecZaWierszem = "-"
    /\ bezWiersza = {} /\ nadpisane = {} /\ klamstwo = {} /\ zleBajty = {}

StartPamiecZmian ==
    /\ faza = "start"
    /\ faza' = IF zmianyZWydan THEN "wolny" ELSE "historiaWydan"
    /\ UNCHANGED <<dysk, op, liczniki, duchy, zdarzenia>>

StartHistoria ==
    /\ faza = "historiaWydan"
    /\ \/ /\ nieczHistorii < MaxNieczytelnejHistorii /\ nieczHistorii' = nieczHistorii + 1
          /\ faza' = "wolny" /\ UNCHANGED op
       \/ /\ \E i \in DOMAIN historia : historia[i].zrodlo = "wydanie"
          /\ faza' = "praca" /\ op' = [Bezczynne EXCEPT !.pc = "pamiecZmian", !.kto = "wydanie", !.wynik = "z-historii"]
          /\ UNCHANGED nieczHistorii
       \/ /\ ~\E i \in DOMAIN historia : historia[i].zrodlo = "wydanie"
          /\ faza' = "praca" /\ op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "wydanie", !.etap = "obserwacja"]
          /\ UNCHANGED nieczHistorii
    /\ UNCHANGED <<dysk, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci,
                   awPamieciZmian, nieczPamieci>>
    /\ UNCHANGED <<duchy, zdarzenia>>

Odczyt ==
    /\ faza = "wolny"
    /\ faza' = "praca" /\ op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "proces"]
    /\ UNCHANGED <<dysk, liczniki, duchy, zdarzenia>>

ZapisTaty ==
    /\ faza = "wolny" /\ zmiany < MaxZmian /\ zmiany' = zmiany + 1
    /\ \E v \in WartosciTaty :
        op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "tata", !.etap = "zmiana", !.cel = v]
    /\ faza' = "praca"
    /\ UNCHANGED <<dysk, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
                   nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<duchy, zdarzenia>>

CofnijTaty ==
    /\ faza = "wolny" /\ cofniecia < MaxCofniec /\ cofniecia' = cofniecia + 1
    /\ \/ /\ nieczHistorii < MaxNieczytelnejHistorii /\ nieczHistorii' = nieczHistorii + 1
          /\ UNCHANGED <<faza, op>>
       \/ /\ \E i \in DOMAIN historia :
                /\ historia[i].wynik = "zapisano" /\ historia[i].cofalny
                /\ op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "tata", !.etap = "zmiana", !.cel = historia[i].przed,
                                          !.cofa = TRUE, !.usun = historia[i].utworzono]
          /\ faza' = "praca"
          /\ UNCHANGED nieczHistorii
    /\ UNCHANGED <<dysk, zmiany, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
                   nieczPamieci>>
    /\ UNCHANGED <<duchy, zdarzenia>>

Porownaj ==
    /\ op.pc = "porownaj"
    /\ LET dane == plik
           zmieniony == ~(dane = pamiec.widziany /\ (dane = ZLY \/ pamiec.dobry = dane))
       IN \/ /\ op.kto = "proces" /\ nieczPamieci < MaxNieczytelnejPamieci /\ nieczPamieci' = nieczPamieci + 1
             /\ op' = [op EXCEPT !.pc = "porownane", !.dane = dane, !.obs = IF dane = ZLY THEN DOMYSLNA ELSE Wartosc(dane),
                                 !.obsDobra = dane # ZLY,
                                 !.sciezka = IF dane = ZLY THEN "zly-plik-bez-pamieci" ELSE "pamiec-bez-odczytu"]
          \/ /\ UNCHANGED nieczPamieci
             /\ op' = [op EXCEPT !.pc = IF zmieniony THEN "wierszSpoza" ELSE "porownane", !.dane = dane,
                                 !.zWydania = wydanieWPliku /\ dane = CEL_WYDANIA, !.dobry = pamiec.dobry,
                                 !.widzianyBrak = (pamiec.widziany = BRAK),
                                 !.obs = Wartosc(IF dane = ZLY THEN pamiec.dobry ELSE dane),
                                 !.obsDobra = dane # ZLY,
                                 !.sciezka = IF pamiecZaWierszem # "-"
                                             THEN IF pamiecZaWierszem = "zgasniecie" THEN "zgasniecie-przed-pamiecia"
                                                  ELSE "pamiec-niezapisana"
                                             ELSE "-"]
    /\ UNCHANGED <<dysk, faza, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci,
                   awPamieciZmian, nieczHistorii>>
    /\ UNCHANGED <<duchy, zdarzenia>>

WierszSpoza ==
    /\ op.pc = "wierszSpoza"
    /\ \/ /\ awWiersza < MaxAwariiWiersza /\ awWiersza' = awWiersza + 1
          /\ op' = [op EXCEPT !.pc = "porownane", !.sciezka = "wiersz-odczytu-nieudany"]
          /\ UNCHANGED <<historia, weszla>>
       \/ /\ historia' = Append(historia, WierszSpozaCentrum(op.dane, op.dobry, op.widzianyBrak))
          /\ op' = [op EXCEPT !.pc = "pamiecSpoza"]
          /\ UNCHANGED awWiersza
          /\ weszla' = (weszla \/ op.zWydania)
    /\ UNCHANGED <<plik, pamiec, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awPrzywrocenia,
                   awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania,
                   pamiecZaWierszem, zdarzenia>>

PamiecSpoza ==
    /\ op.pc = "pamiecSpoza"
    /\ \/ /\ awPamieci < MaxAwariiPamieci /\ awPamieci' = awPamieci + 1
          /\ UNCHANGED pamiec /\ pamiecZaWierszem' = "awaria"
       \/ /\ pamiec' = [widziany |-> op.dane, dobry |-> IF op.dane = ZLY THEN op.dobry ELSE op.dane]
          /\ UNCHANGED awPamieci
          /\ pamiecZaWierszem' = IF op.dane = ZLY THEN pamiecZaWierszem ELSE "-"
    /\ op' = [op EXCEPT !.pc = "porownane"]
    /\ UNCHANGED <<plik, historia, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza,
                   awPrzywrocenia, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane,
                   zgasniecieWydania, zdarzenia>>

Uzyj ==
    /\ op.pc = "porownane" /\ op.kto = "proces"
    /\ bezWiersza' = bezWiersza \cup (IF Wyjasniona(op.obs) THEN {}
                                      ELSE {IF op.sciezka = "-" THEN {} ELSE {op.sciezka}})
    /\ Koniec
    /\ UNCHANGED <<dysk, liczniki, duchy, nadpisane, klamstwo, zleBajty>>

Propozycja ==
    /\ op.pc = "porownane" /\ op.kto = "wydanie" /\ op.etap = "obserwacja"
    /\ IF op.obsDobra
       THEN op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "wydanie", !.etap = "zmiana", !.cel = CEL_WYDANIA]
            /\ UNCHANGED faza
       ELSE Koniec
    /\ UNCHANGED <<dysk, liczniki, duchy, zdarzenia>>

Wylicz ==
    /\ op.pc = "porownane" /\ op.etap = "zmiana"
    /\ IF op.cel = op.obs /\ op.obsDobra
       THEN IF op.kto = "tata" THEN Koniec
            ELSE op' = [Bezczynne EXCEPT !.pc = "pamiecZmian", !.kto = "wydanie", !.wynik = "bez-zmian"]
                 /\ UNCHANGED faza
       ELSE op' = [op EXCEPT !.pc = "zapis", !.nowa = IF op.usun THEN BRAK ELSE op.cel,
                             !.wiersz = op.cel # op.obs, !.tataPrzed = wartoscTaty]
            /\ UNCHANGED faza
    /\ UNCHANGED <<dysk, liczniki, duchy, zdarzenia>>

Zapis ==
    /\ op.pc = "zapis"
    /\ \/ /\ awZapisu < MaxAwariiZapisuPliku /\ awZapisu' = awZapisu + 1
          /\ op' = [op EXCEPT !.pc = "niezapisane"]
          /\ UNCHANGED <<plik, wydanieWPliku, wartoscTaty, nadpisane, zleBajty>>
       \/ /\ plik' = op.nowa
          /\ op' = [op EXCEPT !.pc = IF op.wiersz THEN "wiersz" ELSE "pamiec", !.zapisane = TRUE]
          /\ nadpisane' = nadpisane \cup
                (IF op.kto = "wydanie" /\ op.wiersz /\ wartoscTaty
                 THEN {{c \in Przyczyny : \/ c = "bez-zmian-bez-pamieci" /\ bezZmianNiezapamietane
                                          \/ c = "wiersz-i-przywrocenie-nieudane" /\ przywrocenieWydaniaNieudane
                                          \/ c = "zgasniecie-przed-wierszem-wydania" /\ zgasniecieWydania}}
                 ELSE {})
          /\ wydanieWPliku' = (op.kto = "wydanie")
          /\ wartoscTaty' = (op.kto = "tata" /\ weszla)
          /\ zleBajty' = zleBajty \cup (IF op.cofa /\ op.nowa # (IF op.usun THEN BRAK ELSE op.cel) THEN {{}} ELSE {})
          /\ UNCHANGED awZapisu
    /\ UNCHANGED <<pamiec, historia, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awWiersza,
                   awPrzywrocenia, awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania, pamiecZaWierszem,
                   bezWiersza, klamstwo>>

Wiersz ==
    /\ op.pc = "wiersz"
    /\ \/ /\ awWiersza < MaxAwariiWiersza /\ awWiersza' = awWiersza + 1
          /\ op' = [op EXCEPT !.pc = "przywroc"]
          /\ UNCHANGED historia
       \/ /\ historia' = Append(historia, [zrodlo |-> op.kto, wynik |-> "zapisano", przed |-> op.obs, po |-> op.cel,
                                          cofalny |-> TRUE, utworzono |-> op.dane = BRAK])
          /\ op' = [op EXCEPT !.pc = "pamiec"]
          /\ UNCHANGED awWiersza
    /\ UNCHANGED <<plik, pamiec, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awPrzywrocenia,
                   awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<duchy, zdarzenia>>

Przywroc ==
    /\ op.pc = "przywroc"
    /\ \/ /\ awPrzywrocenia < MaxAwariiPrzywrocenia /\ awPrzywrocenia' = awPrzywrocenia + 1
          /\ op' = [op EXCEPT !.pc = "niezapisane", !.przywrocenie = "nieudane"]
          /\ przywrocenieWydaniaNieudane' = (przywrocenieWydaniaNieudane \/ op.kto = "wydanie")
          /\ UNCHANGED <<plik, wydanieWPliku, wartoscTaty>>
       \/ /\ plik' = op.dane
          /\ op' = [op EXCEPT !.pc = "niezapisane", !.przywrocenie = "ok", !.zapisane = FALSE]
          /\ wydanieWPliku' = FALSE /\ wartoscTaty' = op.tataPrzed
          /\ UNCHANGED <<awPrzywrocenia, przywrocenieWydaniaNieudane>>
    /\ UNCHANGED <<pamiec, historia, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza,
                   awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, bezZmianNiezapamietane, zgasniecieWydania, pamiecZaWierszem, zdarzenia>>

NieZapisano ==
    /\ op.pc = "niezapisane"
    /\ klamstwo' = klamstwo \cup
          (IF op.kto = "tata" /\ op.zapisane /\ Wartosc(plik) = op.cel
           THEN {IF op.przywrocenie = "nieudane" THEN {"przywrocenie-nieudane"} ELSE {}}
           ELSE {})
    /\ Koniec
    /\ UNCHANGED <<dysk, liczniki, duchy, bezWiersza, nadpisane, zleBajty>>

Pamiec ==
    /\ op.pc = "pamiec"
    /\ \/ /\ awPamieci < MaxAwariiPamieci /\ awPamieci' = awPamieci + 1
          /\ UNCHANGED pamiec /\ pamiecZaWierszem' = IF op.wiersz THEN "awaria" ELSE pamiecZaWierszem
       \/ /\ pamiec' = [widziany |-> op.nowa, dobry |-> op.nowa]
          /\ UNCHANGED awPamieci /\ pamiecZaWierszem' = IF op.wiersz THEN "-" ELSE pamiecZaWierszem
    /\ IF op.kto = "tata" THEN Koniec
       ELSE op' = [Bezczynne EXCEPT !.pc = "pamiecZmian", !.kto = "wydanie",
                                    !.wynik = IF op.wiersz THEN "zastosowano" ELSE "bez-zmian"]
            /\ UNCHANGED faza
    /\ UNCHANGED <<plik, historia, zmianyZWydan, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza,
                   awPrzywrocenia, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane,
                   zgasniecieWydania, zdarzenia>>

PamiecZmian ==
    /\ op.pc = "pamiecZmian"
    /\ \/ /\ awPamieciZmian < MaxAwariiPamieciZmian /\ awPamieciZmian' = awPamieciZmian + 1
          /\ bezZmianNiezapamietane' = (bezZmianNiezapamietane \/ op.wynik = "bez-zmian")
          /\ UNCHANGED zmianyZWydan
       \/ /\ zmianyZWydan' = TRUE
          /\ UNCHANGED <<awPamieciZmian, bezZmianNiezapamietane>>
    /\ weszla' = TRUE
    /\ Koniec
    /\ UNCHANGED <<plik, pamiec, historia, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia,
                   awPamieci, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<wydanieWPliku, wartoscTaty, przywrocenieWydaniaNieudane, zgasniecieWydania, pamiecZaWierszem,
                   zdarzenia>>

Reczna ==
    /\ reczne < MaxRecznych /\ reczne' = reczne + 1
    /\ \E s \in Reczne : plik' = s
    /\ wartoscTaty' = FALSE /\ wydanieWPliku' = FALSE
    /\ UNCHANGED <<pamiec, historia, zmianyZWydan, faza, op, zmiany, cofniecia, zgasniecia, awZapisu, awWiersza,
                   awPrzywrocenia, awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania, pamiecZaWierszem,
                   zdarzenia>>

Zgasniecie ==
    /\ zgasniecia < MaxZgasniec /\ zgasniecia' = zgasniecia + 1
    /\ faza' = "start" /\ op' = Bezczynne
    /\ pamiecZaWierszem' = IF op.pc = "pamiecSpoza" \/ (op.pc = "pamiec" /\ op.wiersz) THEN "zgasniecie"
                           ELSE pamiecZaWierszem
    /\ zgasniecieWydania' = (zgasniecieWydania \/ (op.kto = "wydanie" /\ op.pc \in {"wiersz", "przywroc"}))
    /\ UNCHANGED <<dysk, zmiany, cofniecia, reczne, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
                   nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zdarzenia>>

Next ==
    \/ StartPamiecZmian \/ StartHistoria
    \/ Odczyt \/ ZapisTaty \/ CofnijTaty
    \/ Porownaj \/ WierszSpoza \/ PamiecSpoza
    \/ Uzyj \/ Propozycja \/ Wylicz
    \/ Zapis \/ Wiersz \/ Przywroc \/ NieZapisano \/ Pamiec \/ PamiecZmian
    \/ Reczna \/ Zgasniecie

Spec == Init /\ [][Next]_vars

LiczyZapisanym == bezWiersza = {}
WydanieNieNadpisuje == nadpisane = {}
NieZapisanoZnaczyNie == klamstwo = {}
CofnijPrzywracaBajty == zleBajty = {}

Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
LiczyZapisanymPozaZnanymi == Wybaczone(bezWiersza, WybaczoneLiczyZapisanym)
WydanieNieNadpisujePozaZnanymi == Wybaczone(nadpisane, WybaczoneWydanieNieNadpisuje)
NieZapisanoZnaczyNiePozaZnanymi == Wybaczone(klamstwo, WybaczoneNieZapisanoZnaczyNie)
CofnijPrzywracaBajtyPozaZnanymi == Wybaczone(zleBajty, WybaczoneCofnijPrzywracaBajty)
=========================================================================================================================
