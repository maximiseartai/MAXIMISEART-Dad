------------------------------------------------ MODULE SprawyTaty ------------------------------------------------
(* Sprawy taty (dad_cases.py), Zgłoszenie jednego problemu (reports.py: Reports, ReportHandle), Uwaga taty           *)
(* (dad_notes.send) i doręczenia Kolejki wysyłki (case_delivery._CaseDelivery) przy każdej kolejności kroków         *)
(* zapytania HTTP, wątku kolejki skrzynka-kolejka, wątku pytania skrzynki (zgloszenie-skrzynka), Powiadomień i       *)
(* zgaśnięcia Centrum. Kolejkę (Outbox) model ma tylko na granicy: Outbox.post to jeden krok z wynikiem True, False  *)
(* albo wyjątkiem, a przejście kolejki to doręczenie jednego pliku; resztę sprawdza verify-kolejka-skrzynki.        *)
(* Jeden problem (odcisk F) ma jeden uchwyt Zgłoszenia w każdej pracy Centrum: kartę Zatrzymania tego problemu.      *)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    MaxKlikniec,          \* ile razy tata klika „Wyślij do Maksa” (ReportHandle.send)
    MaxUwag,              \* ile Uwag taty tata wysyła („Wyślij”, dad_notes.send)
    MaxZgasniec,          \* ile razy Centrum gaśnie (w dowolnym kroku) i tata otwiera je znowu
    MaxAwariiSieci,       \* ile razy skrzynka nie odpowiada (brak sieci, brak albo odmowa Tokenu, spóźniona odpowiedź)
    MaxAwariiPlikuStanu,  \* ile zapisów config/sprawy-taty.json zawodzi (StateFile._save: OSError)
    MaxAwariiKolejki,     \* ile razy Outbox.post zwraca False (zapis pliku kolejki: OSError)
    MaxWyjatkowKolejki,   \* ile razy Outbox.post rzuca wyjątek inny niż OSError (Reports._queue: finally)
    MaxOdrzucen,          \* ile wysyłek ma treść, którą Skrzynka odrzuca (outbox: Rejected, odmowa-tresci)
    MaxZamkniec,          \* ile issue Maks zamyka
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneCzekaMaPlik, WybaczoneOdrzuconaNieCzeka

F == 0                       \* id sprawy Zgłoszenia: odcisk problemu (Case.id, ProblemFingerprint.digest)
Uwagi == 1..MaxUwag          \* id sprawy Uwagi taty: identyfikator jej wysyłki (uuid4().hex)
Idy == {F} \cup Uwagi
Rodzaje == {"zgl", "uwaga"}  \* CaseKind: REPORT (recurs) i NOTE
\* Każde _queue, które nie zastało czekającej sprawy, dopisuje jedną: kliknięcie albo powrót problemu (raz na uchwyt).
MaxSpraw == MaxKlikniec + MaxZgasniec + 1 + MaxUwag
Sidy == 1..MaxSpraw          \* tożsamość jednej sprawy (Case z chwilą sent_at; withdraw usuwa tylko ją)
Numery == 0..MaxSpraw        \* numer issue; 0: sprawa bez numeru, czeka w Kolejce wysyłki
Sprawy == [sid : Sidy, rodzaj : Rodzaje, id : Idy, numer : Numery, zamknieta : BOOLEAN]
Pliki == [nr : Sidy, rodzaj : Rodzaje, id : Idy, odrzucana : BOOLEAN]
Issue == [nr : Numery \ {0}, rodzaj : Rodzaje, id : Idy, zamkniete : BOOLEAN]
\* Stan uchwytu Zgłoszenia na karcie (diagnosis_contract.ReportState).
Karty == {"gotowe", "czekaNaNaprawe", "wKolejce", "wyslane", "odrzucone", "niezapisane"}
Przyczyny == {"zgasniecie-w-wysylce-zgloszenia", "zgasniecie-w-wysylce-uwagi", "plik-stanu-niedostepny",
              "pokaz-po-odrzuceniu"}

Wolny == [krok |-> "wolny", plik |-> 0, wiesc |-> "-"]
Bezczynne == [pc |-> "-", kto |-> "-", sid |-> 0, plik |-> 0, wynik |-> "-", znana |-> FALSE]
BezUwagi == [pc |-> "-", sid |-> 0, id |-> 0]
BezPytania == [krok |-> "-", numer |-> FALSE, wyslano |-> FALSE]
NowyUchwyt == [podglad |-> FALSE, wysyla |-> FALSE, powrot |-> FALSE]

VARIABLES
    \* Dysk taty i Skrzynka Zgłoszeń: zostają po zgaśnięciu Centrum.
    plikStanu,          \* config/sprawy-taty.json: sprawy, które ostatni udany zapis StateFile położył na dysku
    kolejka,            \* pliki config/zgloszenia/kolejka/*.json: wysyłki spraw (Post z run_id i celem)
    skrzynka,           \* issue Skrzynki Zgłoszeń z etykietą zgloszenie albo uwaga-taty
    znaczniki,          \* [plik, nr]: część wysyłki z jej znacznikiem już w issue nr (_settle znajdzie ją znowu)
    \* Pamięć jednej pracy Centrum: znika ze zgaśnięciem.
    sprawy,             \* DadCases._cases
    odrzuconeSprawy,    \* DadCases._rejected: id spraw, których treść Skrzynka odrzuciła w tej pracy Centrum
    odrzuconePliki,     \* Outbox._rejected: pliki, których kolejka nie próbuje do następnego startu
    dostarczoneWPracy,  \* Outbox._first_comments tej pracy: na nie czeka wait_delivered
    kolejkaPc,          \* gdzie jest wątek skrzynka-kolejka w doręczeniu jednego pliku (_send_all)
    req,                \* Reports._queue uchwytu: wywołane z ReportHandle.send (klik) albo z _ask (powrot)
    uwaga,              \* dad_notes.send jednej Uwagi
    uchwyt,             \* ReportHandle: _preview ustawiony, _sending, _returned
    pyt,                \* wątek zgloszenie-skrzynka z ReportHandle.prepare (_ask): krok, numer w trakcie, wysyłka w trakcie
    otwarte,            \* Reports._open[F]: "?" (brak odpowiedzi w tej pracy) | "tak" | "nie"
    karta,              \* ReportHandle._state: to, co widzi tata na karcie Zatrzymania
    \* Liczniki.
    nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, awarieSieci, awariePlikuStanu, awarieKolejki,
    wyjatkiKolejki, odrzucenia, zamkniecia,
    \* Zdarzenia, które łamią obietnice: zbiór przyczyn w chwili każdego zdarzenia.
    bezPliku, odrzuconaCzeka

dysk == <<plikStanu, kolejka, skrzynka, znaczniki>>
pamiec == <<sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req, uwaga, uchwyt, pyt, otwarte,
            karta>>
liczniki == <<nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, awarieSieci, awariePlikuStanu,
              awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
zdarzenia == <<bezPliku, odrzuconaCzeka>>
vars == <<dysk, pamiec, liczniki, zdarzenia>>

Najwieksza(S) == CHOOSE x \in S : \A y \in S : y <= x
Najmniejsza(S) == CHOOSE x \in S : \A y \in S : x <= y

\* Ostatnia sprawa Zgłoszenia problemu F w s (DadCases.find(REPORT, F)): jej indeks, 0 bez niej.
Ostatnia(s) == LET i == {k \in 1..Len(s) : s[k].rodzaj = "zgl"} IN IF i = {} THEN 0 ELSE Najwieksza(i)
\* Reports._pending: ostatnia sprawa problemu jest bez numeru issue.
CzekaZgl(s) == Ostatnia(s) > 0 /\ s[Ostatnia(s)].numer = 0
\* DadCases.queued(F): odrzucona treść nie czeka na nic, inaczej sprawa czeka w kolejce (na internet albo Token).
Czekajaca(odrz) == IF F \in odrz THEN "odrzucone" ELSE "wKolejce"
\* Reports._state_of: sprawa w kolejce, potem odpowiedź skrzynki z tej pracy Centrum, a bez niej ostatnia sprawa.
StanZgl(s, otw, odrz) ==
    IF CzekaZgl(s) THEN Czekajaca(odrz)
    ELSE IF otw # "?" THEN (IF otw = "tak" THEN "czekaNaNaprawe" ELSE "gotowe")
    ELSE IF Ostatnia(s) > 0 /\ ~s[Ostatnia(s)].zamknieta THEN "czekaNaNaprawe" ELSE "gotowe"

Usun(s, k) == SubSeq(s, 1, k - 1) \o SubSeq(s, k + 1, Len(s))
\* DadCases.withdraw(case): bez tej jednej sprawy.
Wycofana(s, sid) == LET inna(c) == c.sid # sid IN SelectSeq(s, inna)
\* DadCases.forget(NOTE, id): bez każdej Uwagi o tym id.
Zapomniana(s, id) == LET inna(c) == ~(c.rodzaj = "uwaga" /\ c.id = id) IN SelectSeq(s, inna)
\* DadCases.numbered: indeksy spraw, które dostają numer (Zgłoszenie: ostatnia czekająca, Uwaga: każda o tym id).
Nasze(s, rodzaj, id) == {k \in 1..Len(s) : s[k].rodzaj = rodzaj /\ s[k].id = id}
CzekajaceNasze(s, rodzaj, id) == {k \in Nasze(s, rodzaj, id) : s[k].numer = 0}
Znalezione(s, rodzaj, id) == IF rodzaj = "zgl" THEN CzekajaceNasze(s, rodzaj, id) # {} ELSE Nasze(s, rodzaj, id) # {}
Numerowane(s, rodzaj, id, n) ==
    IF rodzaj = "uwaga"
    THEN [k \in 1..Len(s) |-> IF k \in Nasze(s, rodzaj, id) THEN [s[k] EXCEPT !.numer = n] ELSE s[k]]
    ELSE IF CzekajaceNasze(s, rodzaj, id) = {} THEN s
    ELSE LET k == Najwieksza(CzekajaceNasze(s, rodzaj, id)) IN
         \* Inna sprawa ma już ten numer: wysyłka trafiła do otwartego Zgłoszenia, czekająca znika.
         IF \E j \in 1..Len(s) : s[j].numer = n THEN Usun(s, k) ELSE [s EXCEPT ![k].numer = n]

\* DadCases._change: sprawy w pamięci, a plik stanu dostaje je, chyba że zapis zawiedzie (StateFile: treść czeka w
\* pamięci, a następny _change, także bez zmiany, albo retry z odczytu Powiadomień zapisuje ją albo nowszą).
Zapisz(nowe) ==
    /\ sprawy' = nowe
    /\ IF nowe = plikStanu THEN UNCHANGED <<plikStanu, awariePlikuStanu>>
       ELSE \/ plikStanu' = nowe /\ UNCHANGED awariePlikuStanu
            \/ /\ awariePlikuStanu < MaxAwariiPlikuStanu /\ awariePlikuStanu' = awariePlikuStanu + 1
               /\ UNCHANGED plikStanu

\* Treść nowego pliku kolejki: czy Skrzynka ją odrzuci (ta sama treść za każdym razem, także po starcie).
Odrzucane == IF odrzucenia < MaxOdrzucen THEN BOOLEAN ELSE {FALSE}
NowyPlik(rodzaj, id, o) == [nr |-> nastepnyPlik, rodzaj |-> rodzaj, id |-> id, odrzucana |-> o]

OtwarteZgl == {i \in skrzynka : i.rodzaj = "zgl" /\ ~i.zamkniete}

(* Zdarzenia obietnic. *)
\* Zapytanie, które dopisało sprawę i jeszcze nie zapisało jej pliku kolejki ani jej nie wycofało: jego sprawa.
Wlasne(r, u) == (IF r.pc \in {"post", "wycofaj"} THEN {r.sid} ELSE {}) \cup
                (IF u.pc \in {"post", "zapomnij"} THEN {u.sid} ELSE {})
\* Sprawy bez numeru issue (Powiadomienie i karta: „czeka”), bez pliku w kolejce i bez zapytania, które go zapisze.
Osierocone(s, kol, wlasne) ==
    {s[k].sid : k \in {j \in 1..Len(s) : s[j].numer = 0 /\ s[j].sid \notin wlasne
                                        /\ ~\E p \in kol : p.rodzaj = s[j].rodzaj /\ p.id = s[j].id}}
\* Karta mówi „czeka w kolejce”, choć Sprawy taty wiedzą, że Skrzynka odrzuciła treść, a uchwyt już to usłyszał.
OdrzuconaWKolejce(s, k, odrz, kpc) ==
    k = "wKolejce" /\ CzekaZgl(s) /\ F \in odrz /\ ~(kpc.krok = "powiedz" /\ kpc.wiesc = "odrzucona")

Zdarz(stare, warunek, przyczyny) == IF warunek THEN stare \cup {przyczyny} ELSE stare
\* Ostatni koniunkt każdej akcji: zdarzenia obietnic w tym kroku z przyczynami, które akcja zna.
Historia(przyczynyBezPliku, przyczynyKarty) ==
    /\ bezPliku' = Zdarz(bezPliku, Osierocone(sprawy', kolejka', Wlasne(req', uwaga'))
                                   \ Osierocone(sprawy, kolejka, Wlasne(req, uwaga)) # {}, przyczynyBezPliku)
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
    /\ awarieSieci \in 0..MaxAwariiSieci /\ awariePlikuStanu \in 0..MaxAwariiPlikuStanu
    /\ awarieKolejki \in 0..MaxAwariiKolejki /\ wyjatkiKolejki \in 0..MaxWyjatkowKolejki
    /\ odrzucenia \in 0..MaxOdrzucen /\ zamkniecia \in 0..MaxZamkniec
    /\ \A e \in {bezPliku, odrzuconaCzeka} : e \subseteq SUBSET Przyczyny

\* Pierwszy start Centrum na komputerze bez spraw: karta Zatrzymania problemu F jest gotowa do wysłania.
Init ==
    /\ plikStanu = <<>> /\ kolejka = {} /\ skrzynka = {} /\ znaczniki = {}
    /\ sprawy = <<>> /\ odrzuconeSprawy = {} /\ odrzuconePliki = {} /\ dostarczoneWPracy = {}
    /\ kolejkaPc = Wolny /\ req = Bezczynne /\ uwaga = BezUwagi /\ uchwyt = NowyUchwyt /\ pyt = BezPytania
    /\ otwarte = "?" /\ karta = "gotowe"
    /\ nastepnaSprawa = 1 /\ nastepnyPlik = 1
    /\ klikniecia = 0 /\ uwagi = 0 /\ zgasniecia = 0 /\ awarieSieci = 0 /\ awariePlikuStanu = 0 /\ awarieKolejki = 0
    /\ wyjatkiKolejki = 0 /\ odrzucenia = 0 /\ zamkniecia = 0
    /\ bezPliku = {} /\ odrzuconaCzeka = {}

(* ---------------------------------------- uchwyt Zgłoszenia (reports.py) ---------------------------------------- *)

(* ReportHandle.prepare: zamraża podgląd i startuje wątek zgloszenie-skrzynka (_ask) z bieżącym _sends.            *)
Podglad ==
    /\ ~uchwyt.podglad /\ pyt.krok = "-"
    /\ uchwyt' = [uchwyt EXCEPT !.podglad = TRUE]
    /\ pyt' = [krok |-> "pyta", numer |-> FALSE, wyslano |-> FALSE]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req, uwaga, otwarte,
                   karta, liczniki>>
    /\ Historia({}, {})

(* Reports._ask_box: within(search_deadline_s, find_issue(... include_closed=False)); odpowiedź przepada, gdy jej nie *)
(* ma (Unreachable, NoKey, Refused, termin) albo gdy w trakcie pytania sprawa problemu dostała numer (_numbered).    *)
Pytanie ==
    /\ pyt.krok = "pyta"
    /\ \/ /\ awarieSieci < MaxAwariiSieci /\ awarieSieci' = awarieSieci + 1
          /\ UNCHANGED otwarte
       \/ /\ otwarte' = IF pyt.numer THEN otwarte ELSE IF OtwarteZgl # {} THEN "tak" ELSE "nie"
          /\ UNCHANGED awarieSieci
    /\ pyt' = [pyt EXCEPT !.krok = "decyzja"]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req, uwaga, uchwyt,
                   karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, awariePlikuStanu, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

(* ReportHandle._ask po odpowiedzi, pod blokadą uchwytu: odpowiedź na pytanie sprzed wysyłki przepada; inaczej       *)
(* _show(stan, gdy _done, albo Reports._state_of), a podgląd problemu, który czeka na naprawę, idzie sam do kolejki   *)
(* jako powrót, najwyżej raz (_returned, _sending), przez Reports._queue.                                         *)
Decyzja ==
    /\ pyt.krok = "decyzja"
    /\ pyt' = BezPytania
    /\ IF pyt.wyslano
       THEN UNCHANGED <<karta, uchwyt, req>>
       ELSE LET nowa == IF karta \in {"wyslane", "wKolejce"} THEN karta ELSE StanZgl(sprawy, otwarte, odrzuconeSprawy)
            IN /\ karta' = nowa
               /\ IF nowa = "czekaNaNaprawe" /\ ~uchwyt.powrot /\ req.pc = "-"
                  THEN /\ uchwyt' = [uchwyt EXCEPT !.powrot = TRUE, !.wysyla = TRUE]
                       /\ req' = [Bezczynne EXCEPT !.pc = "sprawdz", !.kto = "powrot"]
                  ELSE UNCHANGED <<uchwyt, req>>
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, otwarte,
                   liczniki>>
    /\ Historia({}, {})

(* Tata klika „Wyślij do Maksa”: ReportHandle.send czeka, dopóki _sending, a gdy karta już mówi „wysłane” albo      *)
(* „czeka w kolejce” (_done), oddaje ją bez wysyłki; inaczej _sending, _sends += 1 i Reports._queue(preview).      *)
Klik ==
    /\ uchwyt.podglad /\ ~uchwyt.wysyla /\ req.pc = "-"
    /\ karta \notin {"wyslane", "wKolejce"}
    /\ klikniecia < MaxKlikniec /\ klikniecia' = klikniecia + 1
    /\ uchwyt' = [uchwyt EXCEPT !.wysyla = TRUE]
    /\ pyt' = IF pyt.krok # "-" THEN [pyt EXCEPT !.wyslano = TRUE] ELSE pyt
    /\ req' = [Bezczynne EXCEPT !.pc = "sprawdz", !.kto = "klik"]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, otwarte, karta,
                   nastepnaSprawa, nastepnyPlik, uwagi, zgasniecia, awarieSieci, awariePlikuStanu, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

\* Koniec Reports._queue: send pokazuje wynik (pc "pokaz"), a powrót w _ask tylko zdejmuje _sending. ``znana``: czy
\* Sprawy taty wiedziały już w tej chwili, że Skrzynka odrzuciła treść.
KoniecQueue(wynik) ==
    IF req.kto = "klik"
    THEN req' = [req EXCEPT !.pc = "pokaz", !.wynik = wynik, !.znana = F \in odrzuconeSprawy] /\ UNCHANGED uchwyt
    ELSE req' = Bezczynne /\ uchwyt' = [uchwyt EXCEPT !.wysyla = FALSE]

(* Reports._queue: problem, którego sprawa czeka (_pending), nie trafia do kolejki drugi raz (DadCases.queued);     *)
(* inaczej self._cases.add(case) sprawy bez numeru, zanim plik kolejki istnieje.                                 *)
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
                   pyt, otwarte, karta, nastepnyPlik, klikniecia, uwagi, zgasniecia, awarieSieci, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

(* Reports._queue: queued = self._outbox.post(post), jeden krok: True (plik kolejki zapisany), False (OSError) albo *)
(* wyjątek; po False i wyjątku finally wycofuje sprawę (withdraw).                                                *)
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
                   karta, nastepnaSprawa, klikniecia, uwagi, zgasniecia, awarieSieci, awariePlikuStanu, zamkniecia>>
    /\ Historia({}, {})

(* Reports._queue, finally: if not queued: self._cases.withdraw(case); potem ReportNotQueued (Komunikat), a wyjątek  *)
(* idzie dalej: send zdejmuje _sending bez nowego stanu.                                                          *)
Wycofaj ==
    /\ req.pc = "wycofaj"
    /\ Zapisz(Wycofana(sprawy, req.sid))
    /\ IF req.wynik = "wyjatek" \/ req.kto = "powrot"
       THEN req' = Bezczynne /\ uchwyt' = [uchwyt EXCEPT !.wysyla = FALSE]
       ELSE req' = [req EXCEPT !.pc = "pokaz"] /\ UNCHANGED uchwyt
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga,
                   pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia, awarieSieci,
                   awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

(* Reports._queue po zapisie pliku: Outbox.wait_delivered (najwyżej DELIVERY_WAIT_S; kroki kolejki mogą przyjść     *)
(* wcześniej) daje „wysłane”, a bez dostarczenia return self._cases.queued(fingerprint, box).                       *)
Czekaj ==
    /\ req.pc = "czekaj"
    /\ KoniecQueue(IF req.plik \in dostarczoneWPracy THEN "wyslane" ELSE Czekajaca(odrzuconeSprawy))
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, pyt, otwarte,
                   karta, liczniki>>
    /\ Historia({}, {})

(* ReportHandle.send po _queue, pod blokadą uchwytu: _sending = False; „czeka w kolejce”, gdy sprawa już nie czeka  *)
(* (dostarczenie tuż po końcu czekania), to „wysłane”; _show(stan).                                               *)
Pokaz ==
    /\ req.pc = "pokaz"
    /\ karta' = IF req.wynik = "wKolejce" /\ ~CzekaZgl(sprawy) THEN "wyslane" ELSE req.wynik
    /\ req' = Bezczynne /\ uchwyt' = [uchwyt EXCEPT !.wysyla = FALSE]
    /\ UNCHANGED <<dysk, sprawy, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, uwaga, pyt, otwarte,
                   liczniki>>
    /\ Historia({}, IF req.znana THEN {} ELSE {"pokaz-po-odrzuceniu"})

(* ---------------------------------------- Uwaga taty (dad_notes.send) ---------------------------------------- *)

(* „Wyślij” Uwagi: cases.add(note) sprawy bez numeru, zanim powstał plik kolejki.                                 *)
UwagaWyslij ==
    /\ uwaga.pc = "-" /\ uwagi < MaxUwag
    /\ Zapisz(Append(sprawy, [sid |-> nastepnaSprawa, rodzaj |-> "uwaga", id |-> uwagi + 1, numer |-> 0,
                              zamknieta |-> FALSE]))
    /\ uwaga' = [pc |-> "post", sid |-> nastepnaSprawa, id |-> uwagi + 1]
    /\ uwagi' = uwagi + 1 /\ nastepnaSprawa' = nastepnaSprawa + 1
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req,
                   uchwyt, pyt, otwarte, karta, nastepnyPlik, klikniecia, zgasniecia, awarieSieci, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

(* dad_notes.send: queued = outbox.post(note_post(...)); po True czeka na skrzynkę i oddaje stan tylko tacie.       *)
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
                   kolejkaPc, req, uchwyt, pyt, otwarte, karta, nastepnaSprawa, klikniecia, uwagi, zgasniecia,
                   awarieSieci, awariePlikuStanu, wyjatkiKolejki, zamkniecia>>
    /\ Historia({}, {})

(* dad_notes.send po False: cases.forget(NOTE, note.id), potem odmowa note_not_queued.                           *)
UwagaZapomnij ==
    /\ uwaga.pc = "zapomnij"
    /\ Zapisz(Zapomniana(sprawy, uwaga.id))
    /\ uwaga' = BezUwagi
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req,
                   uchwyt, pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia,
                   awarieSieci, awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

(* ------------------------------------ wątek skrzynka-kolejka (outbox.py) ------------------------------------ *)

Kwalifikowane == {p \in kolejka : p.nr \notin odrzuconePliki}

(* Outbox._send_all dla najstarszego pliku, którego ta praca nie odrzuciła: _deliver, a w nim _settle, które         *)
(* znajduje część ze znacznikiem tej wysyłki już w Skrzynce. Brak sieci albo Tokenu zatrzymuje przejście (_stop,     *)
(* budzik RETRY_S). Odrzucona treść: _rejected, _rejected_posts, Listener.rejected -> DadCases.rejected (_rejected  *)
(* w pamięci, potem _tell). Przyjęta: OpenIssue Zgłoszenia idzie do otwartego Zgłoszenia problemu albo zakłada nowe, *)
(* NewIssue Uwagi zakłada nowe; Listener.delivered -> DadCases.numbered (_change, potem _tell).                     *)
Doreczenie ==
    /\ kolejkaPc = Wolny /\ Kwalifikowane # {}
    /\ LET p == CHOOSE q \in Kwalifikowane : \A r \in Kwalifikowane : q.nr <= r.nr
           znacznik == {m \in znaczniki : m.plik = p.nr}
       IN \/ /\ awarieSieci < MaxAwariiSieci /\ awarieSieci' = awarieSieci + 1
             /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, odrzuconeSprawy, odrzuconePliki, kolejkaPc,
                            awariePlikuStanu>>
          \/ /\ p.odrzucana /\ znacznik = {}
             /\ odrzuconePliki' = odrzuconePliki \cup {p.nr}
             /\ odrzuconeSprawy' = odrzuconeSprawy \cup {p.id}
             /\ kolejkaPc' = IF p.rodzaj = "zgl" THEN [krok |-> "powiedz", plik |-> p.nr, wiesc |-> "odrzucona"]
                             ELSE Wolny
             /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, awarieSieci, awariePlikuStanu>>
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
                   /\ kolejkaPc' = IF p.rodzaj = "zgl" /\ Znalezione(sprawy, p.rodzaj, p.id)
                                   THEN [krok |-> "powiedz", plik |-> p.nr, wiesc |-> "numer"]
                                   ELSE [krok |-> "oznacz", plik |-> p.nr, wiesc |-> "-"]
             /\ UNCHANGED <<odrzuconeSprawy, odrzuconePliki, awarieSieci>>
    /\ UNCHANGED <<kolejka, dostarczoneWPracy, req, uwaga, uchwyt, pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik,
                   klikniecia, uwagi, zgasniecia, awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

(* DadCases._tell w wątku kolejki, poza blokadą spraw: Reports._heard (numer: _open, _numbered) i każdy żywy uchwyt *)
(* problemu: ReportHandle._delivered („czeka w kolejce” -> „wysłane”) albo _rejected („odrzucone”).               *)
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
    /\ Historia({}, {})

(* _send_all po Listener.delivered: _first_comments (budzi wait_delivered), _mark_delivered i _remove pliku.        *)
Oznacz ==
    /\ kolejkaPc.krok = "oznacz"
    /\ dostarczoneWPracy' = dostarczoneWPracy \cup {kolejkaPc.plik}
    /\ kolejka' = {p \in kolejka : p.nr # kolejkaPc.plik}
    /\ kolejkaPc' = Wolny
    /\ UNCHANGED <<plikStanu, skrzynka, znaczniki, sprawy, odrzuconeSprawy, odrzuconePliki, req, uwaga, uchwyt, pyt,
                   otwarte, karta, liczniki>>
    /\ Historia({}, {})

(* ------------------------------------------- Powiadomienia i Maks ------------------------------------------- *)

(* Widok Powiadomień: StateFile.retry, a pytanie w tle DadCases.ask_box: zamknięcie każdej sprawy z numerem z         *)
(* labelled_issues(include_closed=True), _close przez _change; bez odpowiedzi skrzynki tylko retry.                *)
Powiadomienia ==
    /\ \/ Zapisz(sprawy)
       \/ Zapisz([k \in 1..Len(sprawy) |->
                     LET z == {i \in skrzynka : i.nr = sprawy[k].numer /\ i.rodzaj = sprawy[k].rodzaj} IN
                     IF z = {} THEN sprawy[k] ELSE [sprawy[k] EXCEPT !.zamknieta = (CHOOSE i \in z : TRUE).zamkniete]])
    /\ UNCHANGED <<kolejka, skrzynka, znaczniki, odrzuconeSprawy, odrzuconePliki, dostarczoneWPracy, kolejkaPc, req,
                   uwaga, uchwyt, pyt, otwarte, karta, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia,
                   awarieSieci, awarieKolejki, wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia({}, {})

(* Maks zamyka issue w Skrzynce Zgłoszeń.                                                                           *)
MaksZamyka ==
    /\ zamkniecia < MaxZamkniec /\ zamkniecia' = zamkniecia + 1
    /\ \E i \in skrzynka : ~i.zamkniete /\ skrzynka' = (skrzynka \ {i}) \cup {[i EXCEPT !.zamkniete = TRUE]}
    /\ UNCHANGED <<plikStanu, kolejka, znaczniki, pamiec, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, zgasniecia,
                   awarieSieci, awariePlikuStanu, awarieKolejki, wyjatkiKolejki, odrzucenia>>
    /\ Historia({}, {})

(* ----------------------------------------------- zgaśnięcie ----------------------------------------------- *)

(* Centrum gaśnie w dowolnym kroku (brak prądu, zamknięte okno konsoli, zabity proces), a tata otwiera je znowu:     *)
(* pamięć znika (także DadCases._rejected i Outbox._rejected), DadCases._load czyta plik stanu, Outbox.resume       *)
(* wysyła kolejkę od nowa, a karta Zatrzymania tego problemu ma nowy uchwyt ze stanem Reports._state_of.            *)
(* Nic nie godzi spraw z plikami kolejki po starcie.                                                             *)
Zgasniecie ==
    /\ zgasniecia < MaxZgasniec /\ zgasniecia' = zgasniecia + 1
    /\ sprawy' = plikStanu
    /\ odrzuconeSprawy' = {} /\ odrzuconePliki' = {} /\ dostarczoneWPracy' = {}
    /\ kolejkaPc' = Wolny /\ req' = Bezczynne /\ uwaga' = BezUwagi /\ uchwyt' = NowyUchwyt /\ pyt' = BezPytania
    /\ otwarte' = "?"
    /\ karta' = StanZgl(plikStanu, "?", {})
    /\ UNCHANGED <<dysk, nastepnaSprawa, nastepnyPlik, klikniecia, uwagi, awarieSieci, awariePlikuStanu, awarieKolejki,
                   wyjatkiKolejki, odrzucenia, zamkniecia>>
    /\ Historia((IF req.pc \in {"post", "wycofaj"} THEN {"zgasniecie-w-wysylce-zgloszenia"} ELSE {})
                \cup (IF uwaga.pc \in {"post", "zapomnij"} THEN {"zgasniecie-w-wysylce-uwagi"} ELSE {})
                \cup (IF plikStanu # sprawy THEN {"plik-stanu-niedostepny"} ELSE {}),
                {})

Next ==
    \/ Podglad \/ Pytanie \/ Decyzja \/ Klik \/ Sprawdz \/ Post \/ Wycofaj \/ Czekaj \/ Pokaz
    \/ UwagaWyslij \/ UwagaPost \/ UwagaZapomnij
    \/ Doreczenie \/ Uslyszane \/ Oznacz
    \/ Powiadomienia \/ MaksZamyka \/ Zgasniecie

(* Każdy krok kodu, który już się zaczął, kiedyś się dzieje; tata klika, pisze Uwagi, otwiera Powiadomienia i      *)
(* Diagnozę, kiedy chce, a Maks zamyka issue, kiedy chce.                                                        *)
Sprawiedliwosc ==
    /\ WF_vars(Pytanie) /\ WF_vars(Decyzja) /\ WF_vars(Sprawdz) /\ WF_vars(Post) /\ WF_vars(Wycofaj)
    /\ WF_vars(Czekaj) /\ WF_vars(Pokaz) /\ WF_vars(UwagaPost) /\ WF_vars(UwagaZapomnij)
    /\ WF_vars(Doreczenie) /\ WF_vars(Uslyszane) /\ WF_vars(Oznacz)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

(* Obietnice. *)
\* Każda sprawa, która czeka (bez numeru issue), ma swój plik w Kolejce wysyłki, poza chwilą jednego zapytania między
\* dopisaniem sprawy a zapisem jej pliku albo jej wycofaniem (reports.py, finally w Reports._queue: „sprawa bez pliku
\* kolejki czekałaby wiecznie, a tata nie mógłby kliknąć jeszcze raz”; dad_cases.py: Uwaga „bez numeru czeka w kolejce
\* Skrzynki, dopóki numbered nie dopisze numeru”).
CzekaMaPlik == bezPliku = {}
\* Karta nie mówi „czeka w kolejce” o sprawie, której treść Skrzynka odrzuciła w tej pracy Centrum, gdy uchwyt już to
\* usłyszał (reports.py: „Zgłoszenie, którego treść Skrzynka odrzuciła, nie czeka na nic”, ``Rejected``; GLOSSARY,
\* Kolejka wysyłki: treść odrzucona zostaje do następnego startu).
OdrzuconaNieCzeka == odrzuconaCzeka = {}

\* Karta mówi to, co wiedzą Sprawy taty i Skrzynka: ostatnia sprawa problemu czeka -> „czeka w kolejce” albo
\* „odrzucone”; bez czekającej karta nie mówi „czeka w kolejce”, a „odrzucone” tylko wtedy, gdy w kolejce leży
\* wysyłka Zgłoszenia, której treść Skrzynka odrzuciła w tej pracy Centrum (jej sprawę mogło zabrać DadCases.numbered,
\* gdy po zgaśnięciu kolejka doręczyła drugi raz starszy plik tego problemu do tego samego issue).
KartaZgodna ==
    IF CzekaZgl(sprawy) THEN karta = Czekajaca(odrzuconeSprawy)
    ELSE karta \in {"gotowe", "czekaNaNaprawe", "wyslane", "niezapisane"}
                   \cup (IF \E p \in kolejka : p.rodzaj = "zgl" /\ p.nr \in odrzuconePliki THEN {"odrzucone"} ELSE {})
\* W kolejce zostają tylko pliki, których treść Skrzynka odrzuciła w tej pracy Centrum.
KolejkaRozstrzygnieta == \A p \in kolejka : p.nr \in odrzuconePliki
Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
\* Karta, której jedyną niezgodnością jest wybaczone znane znalezisko OdrzuconaNieCzeka (skrypt podaje jego przyczynę).
KartaZnana ==
    /\ OdrzuconaWKolejce(sprawy, karta, odrzuconeSprawy, kolejkaPc)
    /\ odrzuconaCzeka # {} /\ Wybaczone(odrzuconaCzeka, WybaczoneOdrzuconaNieCzeka)
\* Gdy awarie i zgaśnięcia się skończą, a Centrum działa, karta mówi to, co wiedzą Sprawy taty i Skrzynka: każda
\* sprawa z plikiem w kolejce dostaje numer issue albo jej treść jest odrzucona.
Zbieganie == <>[]((KartaZgodna \/ KartaZnana) /\ KolejkaRozstrzygnieta)

\* Wariant obietnicy, który pomija zdarzenie, gdy w jego chwili była przyczyna wybaczonego znaleziska.
CzekaMaPlikPozaZnanymi == Wybaczone(bezPliku, WybaczoneCzekaMaPlik)
OdrzuconaNieCzekaPozaZnanymi == Wybaczone(odrzuconaCzeka, WybaczoneOdrzuconaNieCzeka)
=========================================================================================================================
