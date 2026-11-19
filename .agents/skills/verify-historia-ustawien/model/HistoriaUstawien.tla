------------------------------------------------ MODULE HistoriaUstawien ------------------------------------------------
(* Właściciel Ustawień Centrum (src/rozliczenia/centrum/settings/owner.py, CentrumSettings) przy jednym pliku Ustawień  *)
(* bez sekretu i bez pary: plik w config, jego pamięć w config/ustawienia-pamiec (Memory.read, Memory.write), Historia  *)
(* Ustawień config/historia-ustawien.jsonl (History.append, History.read), pamięć zmian z Wydań                        *)
(* config/ustawienia-pamiec/zmiany-z-wydan.json (Memory.applied, Memory.remember_applied) i jedna zmiana z Wydania,     *)
(* deklaratywna jak w release_changes.py („ustaw wartość r”), przy każdej kolejności kroków właściciela, ręcznej zmiany *)
(* pliku poza Centrum, zgaśnięcia Centrum i awarii każdego zapisu. Właściciel robi wszystko pod jedną blokadą           *)
(* (CentrumSettings._lock), więc jego kroki nie przeplatają się ze sobą: przeplatają się tylko z ręczną zmianą pliku i  *)
(* ze zgaśnięciem. Krok modelu to jedno wejście albo wyjście na dysk; krok bez dysku (wyliczenie) nie zmienia, co może  *)
(* się stać, bo ręczna zmiana i zgaśnięcie przed nim i po nim dają ten sam stan.                                       *)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Poczatek,                 \* treść pliku przed pierwszym startem z Wydaniem: "v0", "r" (tata ma już wartość zmiany)
                              \* albo "brak" (pliku nie ma, Centrum liczy wartością z Wydania)
    MaxZmian,                 \* ile zapisów taty w oknie Ustawień (formularz sekcji: CentrumSettings._by_dad, _change)
    MaxCofniec,               \* ile razy tata klika „Cofnij” (CentrumSettings.undo)
    MaxRecznych,              \* ile razy ktoś zmienia plik poza Centrum (Maks albo tata w Notatniku)
    MaxZgasniec,              \* ile razy Centrum gaśnie (w dowolnym kroku) i tata otwiera je znowu
    MaxAwariiZapisuPliku,     \* ile razy _ConfigFile.write (replace_atomically) rzuca OSError
    MaxAwariiWiersza,         \* ile razy History.append rzuca OSError po ponowieniach RETRY_PAUSES_S
    MaxAwariiPrzywrocenia,    \* ile razy _put_back nie przywraca pliku (place.write: OSError)
    MaxAwariiPamieci,         \* ile razy Memory.write rzuca OSError (_remember tylko loguje)
    MaxAwariiPamieciZmian,    \* ile razy Memory.remember_applied rzuca OSError (_apply_pending tylko loguje)
    MaxNieczytelnejPamieci,   \* ile razy Memory.read przy odczycie dla procesu daje Unreadable (np. antywirus trzyma plik)
    MaxNieczytelnejHistorii,  \* ile razy History.read daje Unreadable (przy starcie albo przy „Cofnij”)
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneLiczyZapisanym, WybaczoneWydanieNieNadpisuje, WybaczoneNieZapisanoZnaczyNie, WybaczoneCofnijPrzywracaBajty

ZLY == "zly"                  \* treść, której parse nie przyjmuje (FieldProblem): złe ustawienie
DOMYSLNA == "d"               \* file.default: wartość z Wydania, którą _value daje złej treści bez ostatniej dobrej
                              \* i brakowi pliku; jako treść: file.dump(file.default), treść z Wydania w pliku taty
BRAK == "brak"                \* brak pliku (settings_bytes: None); jego wartość to DOMYSLNA (parse(None))
CEL_WYDANIA == "r"            \* wartość, którą ustawia zmiana z Wydania (Edit, edycja deklaratywna)
Dobre == {"v0", "r", "t", "x", DOMYSLNA}
Tresci == {"v0", "r", "t", "x", ZLY, DOMYSLNA, BRAK}
\* Wartość treści: brak pliku to wartość z Wydania (file.parse(None)), a inna treść to ona sama.
Wartosc(tresc) == IF tresc = BRAK THEN DOMYSLNA ELSE tresc
WartosciTaty == {"t", "r"}    \* wartości, które tata wpisuje w formularz sekcji
Reczne == {"x", ZLY}          \* treści, które ktoś zapisuje poza Centrum
Zrodla == {"tata", "wydanie", "spoza"}  \* RowSource: ByDad, FromRelease, Outside
\* utworzono: HistoryRow.created, przed zmianą pliku nie było.
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
    \* Dysk taty: zostaje po zgaśnięciu Centrum.
    plik,           \* treść pliku Ustawień w config
    pamiec,         \* Remembered pliku: widziany (seen) i dobry (good)
    historia,       \* wiersze Historii Ustawień od najstarszego (linia urwana zgaśnięciem to wiersz, którego nie ma)
    zmianyZWydan,   \* czy pamięć zmian z Wydań ma zmianę z Wydania
    \* Praca Centrum: znika ze zgaśnięciem.
    faza,           \* "start" (apply_release_changes przed pierwszym zapytaniem), "historiaWydan", "wolny", "praca"
    op,             \* jedna operacja właściciela pod blokadą: odczyt dla procesu, zapis taty, zmiana z Wydania
    \* Liczniki.
    zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
    nieczPamieci, nieczHistorii,
    \* Historia zdarzeń, z której obietnice biorą przyczyny (nie zmienia kroków kodu).
    weszla,                       \* zmiana z Wydania weszła: ma wynik albo wiersz Historii pokazał jej wartość w pliku
    wydanieWPliku,                \* plik ma jeszcze wartość, którą zapisała zmiana z Wydania (nikt jej nie nadpisał)
    wartoscTaty,                  \* plik ma wartość, którą tata zapisał, gdy zmiana z Wydania już weszła
    bezZmianNiezapamietane,       \* wynik „bez-zmian” bez wiersza, a remember_applied się nie udał
    przywrocenieWydaniaNieudane,  \* zapis zmiany z Wydania bez wiersza, którego _put_back nie przywrócił
    zgasniecieWydania,            \* Centrum zgasło po zapisie zmiany z Wydania, a przed jej wierszem Historii
    pamiecZaWierszem,             \* Historia ma wiersz, którego pamięć pliku nie przyjęła: "-", "zgasniecie", "awaria"
    \* Zdarzenia, które łamią obietnice: zbiór przyczyn w chwili każdego zdarzenia.
    bezWiersza, nadpisane, klamstwo, zleBajty

dysk == <<plik, pamiec, historia, zmianyZWydan>>
liczniki == <<zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
              nieczPamieci, nieczHistorii>>
duchy == <<weszla, wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania,
           pamiecZaWierszem>>
zdarzenia == <<bezWiersza, nadpisane, klamstwo, zleBajty>>
vars == <<dysk, faza, op, liczniki, duchy, zdarzenia>>

\* Wartość, którą Historia tłumaczy: „po” najnowszego wiersza „zapisano”, a bez niego treść sprzed Wydania.
Zapisane == SelectSeq(historia, LAMBDA w : w.wynik = "zapisano")
Wyjasniona(u) == IF Len(Zapisane) = 0 THEN u = Wartosc(Poczatek) ELSE Zapisane[Len(Zapisane)].po = u

\* CentrumSettings._outside_row: zła treść „odrzucono” bez „Cofnij”, dobra różnica od ostatniej dobrej wartości;
\* created: pamięć widziała brak pliku.
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

(* ----------------------------- Start Centrum: apply_release_changes, _apply_pending ----------------------------- *)

(* Memory.applied: pamięć ma zmianę, więc nie ma czego stosować; inaczej _apply_pending czyta Historię.             *)
StartPamiecZmian ==
    /\ faza = "start"
    /\ faza' = IF zmianyZWydan THEN "wolny" ELSE "historiaWydan"
    /\ UNCHANGED <<dysk, op, liczniki, duchy, zdarzenia>>

(* _release_rows: Historia bez odczytu wstrzymuje zmianę do następnego startu („bez-historii”); wiersz zmiany z jej  *)
(* id daje wynik bez stosowania; bez niego _apply zaczyna od _observe pliku.                                        *)
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

(* --------------------------------------- Zapytania, gdy Centrum już działa --------------------------------------- *)

(* Odczyt dla procesu: CentrumSettings.snapshot na start Uruchomienia, _observe pliku.                              *)
Odczyt ==
    /\ faza = "wolny"
    /\ faza' = "praca" /\ op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "proces"]
    /\ UNCHANGED <<dysk, liczniki, duchy, zdarzenia>>

(* Zapis taty sekcji: CentrumSettings.change_* -> _by_dad -> _dad_change -> _change z edycją „ustaw v”.            *)
ZapisTaty ==
    /\ faza = "wolny" /\ zmiany < MaxZmian /\ zmiany' = zmiany + 1
    /\ \E v \in WartosciTaty :
        op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "tata", !.etap = "zmiana", !.cel = v]
    /\ faza' = "praca"
    /\ UNCHANGED <<dysk, cofniecia, reczne, zgasniecia, awZapisu, awWiersza, awPrzywrocenia, awPamieci, awPamieciZmian,
                   nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<duchy, zdarzenia>>

(* CentrumSettings.undo: History.read (bez odczytu: NotSaved), wiersz „zapisano” z undoable, potem _by_dad z         *)
(* file.restore(current, changes): wartość sprzed zmiany wiersza, a sam wiersz idzie do _change jako undoes.          *)
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

(* ------------------------- Porównanie z pamięcią: _observe / _bytes_for_change, _compared ------------------------- *)

(* Odczyt pliku (settings_bytes) i jego pamięci (Memory.read). Ten sam stan co pamięć: bez wiersza. Inny: zmiana     *)
(* spoza Centrum. Pamięć bez odczytu (tylko przy odczycie dla procesu): _read(parsed, None), bez porównania, a zła     *)
(* treść nie ma wtedy ostatniej dobrej, więc _value daje file.default.                                              *)
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

(* History.append wiersza spoza Centrum (_outside_row). Nieudany: pamięć bez zmiany, a _compared oddaje               *)
(* _read(parsed, good), czyli nową dobrą treść tak, jakby ją przyjął.                                                *)
WierszSpoza ==
    /\ op.pc = "wierszSpoza"
    /\ \/ /\ awWiersza < MaxAwariiWiersza /\ awWiersza' = awWiersza + 1
          /\ op' = [op EXCEPT !.pc = "porownane", !.sciezka = "wiersz-odczytu-nieudany"]
          /\ UNCHANGED <<historia, weszla>>
       \/ /\ historia' = Append(historia, WierszSpozaCentrum(op.dane, op.dobry, op.widzianyBrak))
          /\ op' = [op EXCEPT !.pc = "pamiecSpoza"]
          /\ UNCHANGED awWiersza
          \* wiersz spoza Centrum pokazuje tacie wartość, którą zapisała zmiana z Wydania (zapis bez swojego wiersza)
          /\ weszla' = (weszla \/ op.zWydania)
    /\ UNCHANGED <<plik, pamiec, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awPrzywrocenia,
                   awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania,
                   pamiecZaWierszem, zdarzenia>>

(* _remember po wierszu spoza Centrum: pamięć przyjmuje stan, także złą treść (dobry zostaje). Nieudany: tylko log.   *)
PamiecSpoza ==
    /\ op.pc = "pamiecSpoza"
    /\ \/ /\ awPamieci < MaxAwariiPamieci /\ awPamieci' = awPamieci + 1
          /\ UNCHANGED pamiec /\ pamiecZaWierszem' = "awaria"
       \/ /\ pamiec' = [widziany |-> op.dane, dobry |-> IF op.dane = ZLY THEN op.dobry ELSE op.dane]
          /\ UNCHANGED awPamieci
          \* zła treść zostawia w pamięci ostatnią dobrą, więc jej przyczyna zostaje
          /\ pamiecZaWierszem' = IF op.dane = ZLY THEN pamiecZaWierszem ELSE "-"
    /\ op' = [op EXCEPT !.pc = "porownane"]
    /\ UNCHANGED <<plik, historia, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awZapisu, awWiersza,
                   awPrzywrocenia, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, wydanieWPliku, wartoscTaty, bezZmianNiezapamietane, przywrocenieWydaniaNieudane,
                   zgasniecieWydania, zdarzenia>>

(* ------------------------------------------ Po porównaniu, bez dysku ------------------------------------------ *)

(* Proces liczy wartością _value(observed): migawka dla Uruchomienia.                                                *)
Uzyj ==
    /\ op.pc = "porownane" /\ op.kto = "proces"
    /\ bezWiersza' = bezWiersza \cup (IF Wyjasniona(op.obs) THEN {}
                                      ELSE {IF op.sciezka = "-" THEN {} ELSE {op.sciezka}})
    /\ Koniec
    /\ UNCHANGED <<dysk, liczniki, duchy, nadpisane, klamstwo, zleBajty>>

(* _apply: change.propose(ReleaseInputs(_observe(file))). Dobra wartość: Edit („ustaw r”), więc _change czyta plik    *)
(* znowu; zła treść: Later (jak periods_directory_from_layout_root), bez wyniku, zmiana wraca przy następnym starcie. *)
Propozycja ==
    /\ op.pc = "porownane" /\ op.kto = "wydanie" /\ op.etap = "obserwacja"
    /\ IF op.obsDobra
       THEN op' = [Bezczynne EXCEPT !.pc = "porownaj", !.kto = "wydanie", !.etap = "zmiana", !.cel = CEL_WYDANIA]
            /\ UNCHANGED faza
       ELSE Koniec
    /\ UNCHANGED <<dysk, liczniki, duchy, zdarzenia>>

(* _change: current = _value(observed), edit(current); bez różnicy przy dobrej treści Saved(change=None), a zmiana z  *)
(* Wydania ma wtedy wynik „bez-zmian”; inaczej wiersz tylko przy różnicy kluczy (zła treść bez różnicy: sam zapis).   *)
(* „Cofnij” wiersza z created zapisuje brak pliku (_restores_absence: plik to jedna wartość, więc późniejsze zmiany    *)
(* jej klucza nic po cofnięciu nie zostawiają), inny zapis file.dump.                                                *)
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

(* ------------------------------------------------- Zapis: _change ------------------------------------------------- *)

(* place.write(new): replace_atomically, więc stary albo nowy plik. Nieudany: NotSaved bez niczego.                  *)
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
          \* „Cofnij” zapisuje bajty sprzed cofanej zmiany: brak pliku, gdy go przed nią nie było
          /\ zleBajty' = zleBajty \cup (IF op.cofa /\ op.nowa # (IF op.usun THEN BRAK ELSE op.cel) THEN {{}} ELSE {})
          /\ UNCHANGED awZapisu
    /\ UNCHANGED <<pamiec, historia, zmianyZWydan, faza, zmiany, cofniecia, reczne, zgasniecia, awWiersza,
                   awPrzywrocenia, awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania, pamiecZaWierszem,
                   bezWiersza, klamstwo>>

(* History.append wiersza zmiany (_row ze źródłem taty albo Wydania). Nieudany: _put_back.                           *)
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

(* _put_back(place, data): poprzednia treść; nieudany zostawia nową treść bez wiersza (tylko log). Potem NotSaved.    *)
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

(* NotSaved: tata czyta „nie zapisano”; zmiana z Wydania nie ma wyniku i wraca przy następnym starcie.                *)
NieZapisano ==
    /\ op.pc = "niezapisane"
    /\ klamstwo' = klamstwo \cup
          (IF op.kto = "tata" /\ op.zapisane /\ Wartosc(plik) = op.cel
           THEN {IF op.przywrocenie = "nieudane" THEN {"przywrocenie-nieudane"} ELSE {}}
           ELSE {})
    /\ Koniec
    /\ UNCHANGED <<dysk, liczniki, duchy, bezWiersza, nadpisane, zleBajty>>

(* _remember(file, Remembered(new, new)) po wierszu; nieudany tylko loguje. Potem Saved; zmiana z Wydania ma wynik.  *)
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

(* _apply_pending: applied[change.id] = done i Memory.remember_applied; nieudany tylko loguje („bez-pamieci”).        *)
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

(* --------------------------------------------- Świat poza Centrum --------------------------------------------- *)

(* Ktoś zapisuje plik poza Centrum, także w trakcie operacji właściciela i przy wyłączonym Centrum.                  *)
Reczna ==
    /\ reczne < MaxRecznych /\ reczne' = reczne + 1
    /\ \E s \in Reczne : plik' = s
    /\ wartoscTaty' = FALSE /\ wydanieWPliku' = FALSE
    /\ UNCHANGED <<pamiec, historia, zmianyZWydan, faza, op, zmiany, cofniecia, zgasniecia, awZapisu, awWiersza,
                   awPrzywrocenia, awPamieci, awPamieciZmian, nieczPamieci, nieczHistorii>>
    /\ UNCHANGED <<weszla, bezZmianNiezapamietane, przywrocenieWydaniaNieudane, zgasniecieWydania, pamiecZaWierszem,
                   zdarzenia>>

(* Centrum gaśnie w dowolnym kroku, a tata otwiera je znowu: zapytanie bez odpowiedzi, start stosuje zmiany z Wydania *)
(* przed pierwszym zapytaniem. Linia Historii urwana w trakcie History.append to wiersz, którego nie ma.            *)
Zgasniecie ==
    /\ zgasniecia < MaxZgasniec /\ zgasniecia' = zgasniecia + 1
    /\ faza' = "start" /\ op' = Bezczynne
    \* wiersz już w Historii, a pamięć pliku jeszcze go nie przyjęła (_remember po History.append)
    /\ pamiecZaWierszem' = IF op.pc = "pamiecSpoza" \/ (op.pc = "pamiec" /\ op.wiersz) THEN "zgasniecie"
                           ELSE pamiecZaWierszem
    \* zapis zmiany z Wydania już w pliku, a jej wiersza jeszcze nie ma (History.append po place.write)
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

(* Obietnice. *)
\* Proces liczy wartością, którą tłumaczy Historia: „po” najnowszego wiersza „zapisano” albo treść sprzed Wydania
\* (owner.py: „Inny stan to zmiana spoza Centrum i dokładnie jeden wiersz Historii”; „zmiany bez wiersza nie daje żadne
\* miejsce”; zła treść ma ostatnią dobrą wartość z pamięci, „nigdy wyjątek ani błąd startu”).
LiczyZapisanym == bezWiersza = {}
\* Zmiana z Wydania nie nadpisuje wartości, którą tata zapisał, gdy ta zmiana już weszła (owner.py: „Każda zmiana z
\* wynikiem ... trafia do pamięci i już nie wraca”; „nie puszcza zmiany drugi raz, także po cofnięciu przez tatę”).
WydanieNieNadpisuje == nadpisane = {}
\* „Nie zapisano” (NotSaved) znaczy, że pliku nie zmieniono (owner.py, NotSaved: „więc nic się nie zmieniło”).
NieZapisanoZnaczyNie == klamstwo = {}
\* „Cofnij” przywraca bajty sprzed cofanej zmiany, także brak pliku (owner.py, _restores_absence): treść z Wydania
\* zapisana do pliku taty nie dostałaby nowych wartości domyślnych następnego Wydania (ADR 0032).
CofnijPrzywracaBajty == zleBajty = {}

Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
\* Wariant obietnicy, który pomija zdarzenie, gdy w jego chwili była przyczyna wybaczonego znaleziska.
LiczyZapisanymPozaZnanymi == Wybaczone(bezWiersza, WybaczoneLiczyZapisanym)
WydanieNieNadpisujePozaZnanymi == Wybaczone(nadpisane, WybaczoneWydanieNieNadpisuje)
NieZapisanoZnaczyNiePozaZnanymi == Wybaczone(klamstwo, WybaczoneNieZapisanoZnaczyNie)
CofnijPrzywracaBajtyPozaZnanymi == Wybaczone(zleBajty, WybaczoneCofnijPrzywracaBajty)
=========================================================================================================================
