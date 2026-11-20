------------------------------ MODULE KolejkaSkrzynki ------------------------------
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Cel,
    Czesci,
    CzesciNowszej,
    Naglowek,
    Wysylek,
    MaxBrakSieci,
    MaxZgubionych,
    MaxOdmowTresci,
    MaxBledowPliku,
    AwariaOdczytu,
    MaxWylaczen,
    Kolejki,
    DwaProcesy,
    Diagnoza,
    Archiwum,
    Wzorzec,
    MaxOdmowArchiwum,
    PusteRepo,
    Postep,
    StarszaPozniej,
    OpoznienieListy,
    WybaczoneJednoIssue, WybaczoneDokladnieRaz, WybaczoneCzesciWKolejnosci, WybaczoneZbieganie

ASSUME Cel = "zgloszenie" => Czesci = 1
ASSUME Diagnoza => Cel = "okres" /\ Naglowek /\ Wysylek = 2
ASSUME CzesciNowszej >= 1 /\ (~Diagnoza => CzesciNowszej = Czesci)
ASSUME Archiwum => Cel = "okres" /\ Naglowek /\ Czesci = 1 /\ CzesciNowszej = 1
ASSUME PusteRepo => Archiwum
ASSUME Postep => Diagnoza /\ Archiwum
ASSUME StarszaPozniej => Diagnoza /\ Archiwum /\ ~Postep
ASSUME Wzorzec => Archiwum /\ ~Postep /\ ~StarszaPozniej

W == 1..Wysylek
Id(w) == IF Diagnoza THEN 1 ELSE w
Liczba(w) == IF Diagnoza /\ w = 2 THEN CzesciNowszej ELSE Czesci
Najwiecej == IF CzesciNowszej > Czesci THEN CzesciNowszej ELSE Czesci
MaPlik(w) == Archiwum /\ ~(Postep /\ w = 1)
Nr(w) == IF StarszaPozniej /\ w \in {1, 2} THEN 3 - w ELSE w
Q == 1..Kolejki
Proc(q) == IF DwaProcesy THEN q ELSE 1
Procesy == {Proc(q) : q \in Q}

VARIABLES
    plik,
    tmp,
    zakladanie,
    pamiec,
    pamiecWydania,
    issues,
    archiwum,
    wydania,
    niewidoczne,
    wydanieNiewidoczne,
    falszywe,
    zyje,
    pc,
    draining, again, armed, stopped,
    nieczytany,
    bezBlokady,
    undeleted, rejected,
    lista,
    czytane,
    biez,
    nr,
    kom,
    arch,
    po,
    odmowaArch,
    bezZnacznika,
    passes,
    blokada,
    zamkniecia,
    odczyt,
    nadawca,
    przez,
    zakolejkowane,
    odrzucone,
    wzorce,
    wzCzeka,
    podwojny,
    sieci, zgubione, odmowy, odmowyArchiwum, bledyPliku, wylaczenia,
    krok,
    slady

dysk == <<plik, tmp>>
watek == <<pc, draining, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, czytane, biez, nr, kom,
           bezZnacznika, arch, po, odmowaArch, wzCzeka>>
archiwa == <<archiwum, wydania, podwojny, wzorce>>
nadawanie == <<nadawca, przez, zakolejkowane, odrzucone>>
awarie == <<sieci, zgubione, odmowy, odmowyArchiwum, bledyPliku, wylaczenia>>
opoznienie == <<niewidoczne, zakladanie, pamiec, odczyt, wydanieNiewidoczne, pamiecWydania, falszywe>>
vars == <<dysk, issues, archiwa, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, krok, slady, opoznienie>>

ZnaneZnaleziska == {}

Rodzaje == {"issue", "archiwum"}

Kroki == {"spi", "petla", "plik", "szukaj", "czytaj", "zaloz", "komentuj", "dostarczona", "zamiana", "usun", "zwolnij",
          "decyzja", "archiwum", "wydanie", "wzorzec", "usunplik", "wyslij"}
Para == (0..Wysylek) \X (0..Najwiecej)
Zapisy == {"dopisz", "popraw", "wycofaj"}

TypeOK ==
    /\ plik \in [W -> {"nadejdzie", "przepadl", "czeka", "skomentowany", "oznaczony", "usuniety"}]
    /\ tmp \subseteq W
    /\ issues \in Seq([klucz : {"L", "N", "Z"}, tresc : Seq(Para)])
    /\ archiwum \in Seq(W) /\ wydania \in Nat /\ podwojny \in BOOLEAN /\ wzorce \in Nat
    /\ wzCzeka \in [Q -> BOOLEAN]
    /\ arch \in [Q -> {"brak", "jest", "czeka"}] /\ po \in [Q -> {"zaloz", "komentuj", "dostarczona"}]
    /\ odmowaArch \in [Q -> BOOLEAN]
    /\ zyje \in [Q -> {"nie", "tak", "zamkniety"}]
    /\ pc \in [Q -> Kroki]
    /\ draining \in [Q -> BOOLEAN] /\ again \in [Q -> BOOLEAN]
    /\ armed \in [Q -> BOOLEAN] /\ stopped \in [Q -> BOOLEAN] /\ nieczytany \in [Q -> BOOLEAN]
    /\ bezBlokady \in [Q -> BOOLEAN]
    /\ undeleted \in [Q -> SUBSET W] /\ rejected \in [Q -> SUBSET W]
    /\ lista \in [Q -> Seq(W)] /\ czytane \in [Q -> SUBSET W] /\ biez \in [Q -> W] /\ nr \in [Q -> Nat]
    /\ kom \in [Q -> Seq((1..Najwiecej) \X Zapisy)] /\ bezZnacznika \in [Q -> BOOLEAN]
    /\ passes \in [Procesy -> {"wolny", "zajety", "prosba"}]
    /\ blokada \in Q \cup {0}
    /\ nadawca \in [W -> {"czeka", "zamiana", "budzi", "koniec"}]
    /\ przez \in [W -> Q] /\ zakolejkowane \subseteq W /\ odrzucone \subseteq W
    /\ slady \subseteq ZnaneZnaleziska
    /\ niewidoczne \subseteq 1..Len(issues) /\ zakladanie \in [Rodzaje -> {"brak", "swieze"}]
    /\ pamiec \subseteq 1..Len(issues)
    /\ odczyt \in [Q -> [Rodzaje -> BOOLEAN]] /\ wydanieNiewidoczne \in BOOLEAN /\ pamiecWydania \in BOOLEAN
    /\ falszywe \in BOOLEAN

Swiezo == IF Cel = "znane" /\ OpoznienieListy THEN {1} ELSE {}

Init ==
    /\ plik = [w \in W |-> "nadejdzie"]
    /\ tmp = {}
    /\ issues = IF Cel = "znane" THEN <<[klucz |-> "Z", tresc |-> <<<<0, 0>>>>]>> ELSE <<>>
    /\ archiwum = <<>> /\ wydania = 0 /\ podwojny = FALSE /\ wzorce = 0 /\ wzCzeka = [q \in Q |-> FALSE]
    /\ arch = [q \in Q |-> "brak"] /\ po = [q \in Q |-> "dostarczona"] /\ odmowaArch = [q \in Q |-> FALSE]
    /\ zyje = [q \in Q |-> "nie"]
    /\ pc = [q \in Q |-> "spi"]
    /\ draining = [q \in Q |-> FALSE] /\ again = [q \in Q |-> FALSE]
    /\ armed = [q \in Q |-> FALSE] /\ stopped = [q \in Q |-> FALSE] /\ nieczytany = [q \in Q |-> FALSE]
    /\ bezBlokady = [q \in Q |-> FALSE]
    /\ undeleted = [q \in Q |-> {}] /\ rejected = [q \in Q |-> {}]
    /\ lista = [q \in Q |-> <<>>] /\ czytane = [q \in Q |-> {}] /\ biez = [q \in Q |-> 1] /\ nr = [q \in Q |-> 0]
    /\ kom = [q \in Q |-> <<>>] /\ bezZnacznika = [q \in Q |-> FALSE]
    /\ passes = [p \in Procesy |-> "wolny"]
    /\ blokada = 0
    /\ zamkniecia = 0
    /\ nadawca = [w \in W |-> "czeka"] /\ przez = [w \in W |-> 1] /\ zakolejkowane = {} /\ odrzucone = {}
    /\ sieci = 0 /\ zgubione = 0 /\ odmowy = 0 /\ odmowyArchiwum = 0 /\ bledyPliku = 0 /\ wylaczenia = 0
    /\ krok = "start"
    /\ slady = {}
    /\ niewidoczne = Swiezo
    /\ \/ /\ pamiec = Swiezo /\ zakladanie = [r \in Rodzaje |-> "brak"]
       \/ /\ Swiezo /= {} /\ pamiec = {} /\ zakladanie = [r \in Rodzaje |-> IF r = "issue" THEN "swieze" ELSE "brak"]
    /\ odczyt = [q \in Q |-> [r \in Rodzaje |-> FALSE]]
    /\ wydanieNiewidoczne = FALSE /\ pamiecWydania = FALSE /\ falszywe = FALSE

Zakres(s) == {s[i] : i \in 1..Len(s)}
Klucz == IF Cel = "nowe" THEN "N" ELSE IF Cel = "znane" THEN "Z" ELSE "L"
Cialo(w) == IF Naglowek THEN <<w, 0>> ELSE <<w, 1>>
Od(w, a) == [i \in 1..(Liczba(w) - a + 1) |-> a + i - 1]
Reszta(w) == IF Naglowek THEN Od(w, 1) ELSE Od(w, 2)
Najwyzszy(z) == IF z = {} THEN 0 ELSE CHOOSE i \in z : \A j \in z : j <= i
Najnizszy(z) == CHOOSE i \in z : \A j \in z : i <= j
Widoczne(q, zna) == {i \in 1..Len(issues) : i \notin niewidoczne \/ (zna /\ i \in pamiec)}
Najnowsze(q, zna) == Najwyzszy({i \in Widoczne(q, zna) : issues[i].klucz = "L"})
Moj(e, w) == e[1] \in W /\ Id(e[1]) = Id(w)
Swoje(w, q, zna) == Najwyzszy({i \in Widoczne(q, zna) : Moj(issues[i].tresc[1], w)})
OdczytyZapisow == IF OpoznienieListy /\ bledyPliku < MaxBledowPliku THEN {TRUE, FALSE} ELSE {TRUE}
Ma(i, w, k) == \E j \in 1..Len(issues[i].tresc) :
                 Moj(issues[i].tresc[j], w) /\ issues[i].tresc[j][2] = k /\ Nr(issues[i].tresc[j][1]) >= Nr(w)
WIssue(w) == \E i \in 1..Len(issues) : \A k \in 1..Liczba(w) : Ma(i, w, k)
Pliki(w) == {i \in 1..Len(archiwum) : Id(archiwum[i]) = Id(w)}
WArchiwum(w) == ~MaPlik(w) \/ ((\E i \in Pliki(w) : Nr(archiwum[i]) >= Nr(w)) /\ (Wzorzec => wzorce > 0))
Dostarczona(w) == WIssue(w) /\ WArchiwum(w)
Zastapiona(w) == \E v \in zakolejkowane : Nr(v) > Nr(w) /\ Id(v) = Id(w)
BezStarszych(w) ==
    /\ \A i \in 1..Len(issues) : \A j \in 1..Len(issues[i].tresc) :
         LET e == issues[i].tresc[j] IN Moj(e, w) /\ e[2] > 0 => Nr(e[1]) >= Nr(w)
    /\ \A i \in Pliki(w) : Nr(archiwum[i]) >= Nr(w)
Miejsca(w, k) == UNION {{<<i, j>> : j \in {m \in 1..Len(issues[i].tresc) :
                                             Moj(issues[i].tresc[m], w) /\ issues[i].tresc[m][2] = k}} :
                        i \in 1..Len(issues)}

JednoIssue ==
  /\ wydania <= 1
  /\ CASE Cel \in {"okres", "zgloszenie"} ->
            Cardinality({i \in 1..Len(issues) : issues[i].klucz = "L"}) <= 1
      [] Cel = "znane" -> Len(issues) = 1
      [] Cel = "nowe" -> \A w \in W : Cardinality({i \in 1..Len(issues) : issues[i].tresc[1] = Cialo(w)}) <= 1

DokladnieRaz ==
    /\ \A w \in zakolejkowane : plik[w] \in {"oznaczony", "usuniety", "przepadl"} /\ ~Zastapiona(w) => Dostarczona(w)
    /\ \A w \in zakolejkowane : plik[w] = "skomentowany" /\ ~Zastapiona(w) => WIssue(w)
    /\ \A w \in W : \A k \in 1..Najwiecej : Cardinality(Miejsca(w, k)) <= 1
    /\ \A w \in W : Cardinality(Pliki(w)) <= 1
    /\ ~podwojny
    /\ \A w \in zakolejkowane : plik[w] \in {"oznaczony", "usuniety"} => BezStarszych(w)
    /\ ~falszywe

CzesciWKolejnosci ==
    \A i \in 1..Len(issues) : \A j \in 1..Len(issues[i].tresc) :
        LET p == issues[i].tresc[j] IN
        p[2] > 1 => \E m \in 1..(j - 1) : Moj(issues[i].tresc[m], p[1]) /\ issues[i].tresc[m][2] = p[2] - 1

Odrzucona(w) == w \in odrzucone /\ \E q \in Q : zyje[q] /= "nie" /\ w \in rejected[q]
Pamieta(w) == \E q \in Q : zyje[q] /= "nie" /\ w \in undeleted[q]

Zbieganie ==
    <>[](\A w \in zakolejkowane : plik[w] = "czeka" \/ (plik[w] = "skomentowany" /\ ~PusteRepo)
                                  => Odrzucona(w) \/ (Pamieta(w) /\ Dostarczona(w)))

Po(wybaczone) == wybaczone \cap slady /= {}
JednoIssuePozaZnanymi == JednoIssue \/ Po(WybaczoneJednoIssue)
DokladnieRazPozaZnanymi == DokladnieRaz \/ Po(WybaczoneDokladnieRaz)
CzesciWKolejnosciPozaZnanymi == CzesciWKolejnosci \/ Po(WybaczoneCzesciWKolejnosci)
ZbieganiePozaZnanymi == Zbieganie \/ <>Po(WybaczoneZbieganie)

Ustaw(f, q, v) == [f EXCEPT ![q] = v]
Budz(q) ==
    IF draining[q]
    THEN /\ again' = Ustaw(again, q, TRUE) /\ UNCHANGED <<draining, pc>>
    ELSE /\ draining' = Ustaw(draining, q, TRUE) /\ pc' = Ustaw(pc, q, "petla") /\ UNCHANGED again
Idz(q, krokKodu, opis) == pc' = Ustaw(pc, q, krokKodu) /\ krok' = opis
Stop(q, opis) ==
    /\ stopped' = Ustaw(stopped, q, TRUE)
    /\ UNCHANGED nieczytany
    /\ Idz(q, "zwolnij", opis)
Odrzuc(q, w, opis) ==
    /\ rejected' = Ustaw(rejected, q, rejected[q] \cup {w})
    /\ Idz(q, "plik", opis)
Dopisz(ks) == [n \in 1..Len(ks) |-> <<ks[n], "dopisz">>]
PoArchiwum(q, dalej, opis) ==
    IF MaPlik(biez[q])
    THEN /\ po' = Ustaw(po, q, dalej) /\ Idz(q, "archiwum", opis)
    ELSE /\ UNCHANGED po /\ Idz(q, dalej, opis)
Czeka(q, opis) ==
    /\ arch' = Ustaw(arch, q, "czeka")
    /\ Idz(q, po[q], opis)

Swieze(q, r) == zakladanie[r] = "swieze"
Wstrzymane(q, r) == odczyt[q][r]
Zapis(q, r, zna) ==
    IF OpoznienieListy
    THEN IF zna
         THEN /\ zakladanie' = [zakladanie EXCEPT ![r] = "brak"]
              /\ odczyt' = [x \in Q |-> [odczyt[x] EXCEPT ![r] = FALSE]]
         ELSE /\ zakladanie' = [zakladanie EXCEPT ![r] = "swieze"]
              /\ odczyt' = [x \in Q |-> IF x = q THEN odczyt[x] ELSE [odczyt[x] EXCEPT ![r] = TRUE]]
    ELSE UNCHANGED <<zakladanie, odczyt>>

PlikiPrzejscia == SelectSeq([i \in 1..Wysylek |-> i], LAMBDA w : plik[w] \in {"czeka", "skomentowany", "oznaczony"})

Petla(q) ==
    /\ pc[q] = "petla"
    /\ IF passes[Proc(q)] = "wolny"
       THEN /\ passes' = Ustaw(passes, Proc(q), "zajety")
            /\ bezBlokady' = Ustaw(bezBlokady, q, blokada /= 0)
            /\ IF blokada = 0
               THEN /\ blokada' = q
                    /\ nieczytany' = Ustaw(nieczytany, q, FALSE)
                    /\ odmowaArch' = Ustaw(odmowaArch, q, FALSE)
                    /\ lista' = Ustaw(lista, q, PlikiPrzejscia)
                    /\ czytane' = Ustaw(czytane, q, {w \in Zakres(PlikiPrzejscia) : w \notin rejected[q] \cup undeleted[q]})
                    /\ Idz(q, "plik", "_drain: _claimed, _folder_lock, _send_all bierze pliki kolejki po nazwie")
               ELSE /\ UNCHANGED <<blokada, lista, czytane, nieczytany, odmowaArch>>
                    /\ Idz(q, "zwolnij", "_drain: _claimed, blokade folderu trzyma kolejka innego procesu, _locked_out")
       ELSE /\ passes' = Ustaw(passes, Proc(q), "prosba")
            /\ UNCHANGED <<blokada, lista, czytane, nieczytany, bezBlokady, odmowaArch>>
            /\ Idz(q, "decyzja", "_drain: _claimed zastaje przejscie innej kolejki, prosi o nastepne")
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, draining, again, armed, stopped, undeleted, rejected, biez, nr, kom,
                   bezZnacznika, arch, po, wzCzeka, zamkniecia, nadawanie, awarie, slady>>

Nowszy(q, w) == \E v \in czytane[q] : Id(v) = Id(w) /\ Nr(v) > Nr(w)
NowszyDalej(q, w) == \E v \in Zakres(Tail(lista[q])) \cap czytane[q] : Id(v) = Id(w) /\ Nr(v) > Nr(w)

Plik(q) ==
    /\ pc[q] = "plik"
    /\ IF lista[q] = <<>>
       THEN /\ stopped' = Ustaw(stopped, q, FALSE)
            /\ UNCHANGED <<lista, czytane, biez, nieczytany, bledyPliku, slady, arch, po>>
            /\ Idz(q, "zwolnij", "_send_all: koniec plikow, _stopped_on = None")
       ELSE LET w == Head(lista[q])
                dalej == Ustaw(lista, q, Tail(lista[q]))
            IN
            /\ biez' = Ustaw(biez, q, w)
            /\ arch' = Ustaw(arch, q, "brak")
            /\ UNCHANGED stopped
            /\ CASE w \in undeleted[q] ->
                      /\ lista' = dalej
                      /\ UNCHANGED <<czytane, nieczytany, bledyPliku, slady, po>>
                      /\ Idz(q, "usun", "_send_all: plik w _undeleted, _remove")
                 [] w \in rejected[q] ->
                      /\ lista' = dalej
                      /\ UNCHANGED <<czytane, nieczytany, bledyPliku, slady, po>>
                      /\ Idz(q, "plik", "_send_all: plik w _rejected, czeka do nastepnego startu")
                 [] OTHER ->
                      \/ /\ AwariaOdczytu /\ bledyPliku < MaxBledowPliku /\ plik[w] /= "usuniety"
                         /\ lista' = dalej
                         /\ bledyPliku' = bledyPliku + 1
                         /\ nieczytany' = Ustaw(nieczytany, q, TRUE)
                         /\ czytane' = Ustaw(czytane, q, czytane[q] \ {w})
                         /\ UNCHANGED <<slady, po>>
                         /\ Idz(q, "plik", "_queued: read_text rzuca OSError, _read_failed, _skip_unreadable pomija plik")
                      \/ /\ plik[w] = "usuniety"
                         /\ lista' = dalej
                         /\ nieczytany' = Ustaw(nieczytany, q, TRUE)
                         /\ czytane' = Ustaw(czytane, q, czytane[q] \ {w})
                         /\ UNCHANGED <<bledyPliku, slady, po>>
                         /\ Idz(q, "plik", "_queued: pliku juz nie ma (usunal go inny proces), _read_failed, _skip_unreadable")
                      \/ /\ plik[w] = "oznaczony"
                         /\ lista' = dalej
                         /\ UNCHANGED <<czytane, nieczytany, bledyPliku, slady, po>>
                         /\ Idz(q, "usun", "_queued: plik ze znacznikiem dostarczenia, _remove")
                      \/ /\ plik[w] \in {"czeka", "skomentowany"} /\ Nowszy(q, w)
                         /\ lista' = dalej
                         /\ UNCHANGED <<czytane, nieczytany, bledyPliku, slady, po>>
                         /\ Idz(q, "dostarczona", "_superseded: przejscie odczytalo nowsza wersje tej wysylki, znacznik bez wysylania")
                      \/ /\ plik[w] \in {"czeka", "skomentowany"} /\ NowszyDalej(q, w)
                         /\ AwariaOdczytu /\ bledyPliku < MaxBledowPliku
                         /\ lista' = Ustaw(lista, q, SelectSeq(Tail(lista[q]), LAMBDA v : Id(v) /= Id(w)))
                         /\ bledyPliku' = bledyPliku + 1
                         /\ nieczytany' = Ustaw(nieczytany, q, TRUE)
                         /\ czytane' = Ustaw(czytane, q, {v \in czytane[q] : v \notin Zakres(Tail(lista[q])) \/ Id(v) /= Id(w)})
                         /\ po' = IF plik[w] = "skomentowany" THEN Ustaw(po, q, "dostarczona") ELSE po
                         /\ UNCHANGED slady
                         /\ Idz(q, IF plik[w] = "skomentowany" THEN "archiwum" ELSE "szukaj",
                                "_read: pliku nowszej wersji nie da sie odczytac (OSError), _read_failed; ten idzie jak zwykle, nowsza czeka na budzik")
                      \/ /\ plik[w] = "skomentowany" /\ ~Nowszy(q, w)
                         /\ lista' = dalej
                         /\ UNCHANGED <<czytane, nieczytany, bledyPliku, slady>>
                         /\ po' = Ustaw(po, q, "dostarczona")
                         /\ Idz(q, "archiwum", "_queued: czesci sa w Skrzynce (commented), sam _deliver_archive")
                      \/ /\ plik[w] = "czeka" /\ ~Nowszy(q, w)
                         /\ lista' = dalej
                         /\ UNCHANGED <<czytane, nieczytany, bledyPliku, slady, po>>
                         /\ Idz(q, "szukaj", "_deliver: wysylka z pliku")
    /\ UNCHANGED <<wzCzeka>>
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, nr, kom, bezZnacznika,
                   odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia>>

Szukaj(q) == \E zna \in OdczytyZapisow :
    /\ pc[q] = "szukaj"
    /\ bledyPliku' = IF zna THEN bledyPliku ELSE bledyPliku + 1
    /\ odczyt' = [odczyt EXCEPT ![q]["issue"] = ~zna \/ Swieze(q, "issue")]
    /\ \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, "labelled_issues: Unreachable (brak sieci), przejscie staje")
          /\ UNCHANGED <<nr, kom, slady, po>>
       \/ /\ Cel = "okres"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          /\ IF Najnowsze(q, zna) = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ PoArchiwum(q, "zaloz", "find_issue: brak issue okresu")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze(q, zna)) /\ kom' = Ustaw(kom, q, Dopisz(Od(biez[q], 1)))
                  /\ UNCHANGED po
                  /\ Idz(q, "czytaj", "labelled_issues: jest issue okresu, _settle z kazda czescia")
       \/ /\ Cel = "zgloszenie"
          /\ UNCHANGED <<sieci, stopped, nieczytany, po>>
          /\ UNCHANGED slady
          /\ IF Najnowsze(q, zna) = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "labelled_issues: brak otwartego Zgloszenia z odciskiem")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze(q, zna)) /\ kom' = Ustaw(kom, q, Dopisz(Od(biez[q], 1)))
                  /\ Idz(q, "czytaj", "_deliver_open_issue: jest Zgloszenie z odciskiem, _settle z komentarzem z naglowkiem again")
       \/ /\ Cel = "znane"
          /\ UNCHANGED <<sieci, nieczytany, slady, po>>
          /\ IF 1 \in Widoczne(q, zna)
             THEN /\ nr' = Ustaw(nr, q, 1) /\ kom' = Ustaw(kom, q, Dopisz(Od(biez[q], 1)))
                  /\ UNCHANGED stopped
                  /\ Idz(q, "czytaj", "_deliver_to_known: issue jest na liscie, _settle z kazda czescia")
             ELSE IF ~zna \/ Swieze(q, "issue")
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Stop(q, "known_issue: lista bez issue, a zapis z etykieta bylby wstrzymany, Unreachable")
             ELSE /\ UNCHANGED <<nr, kom, stopped>>
                  /\ Idz(q, "usun", "_deliver_to_known: lista bez issue, Gone, _remove bez wysylki")
       \/ /\ Cel = "nowe"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady, po>>
          /\ IF Swoje(biez[q], q, zna) = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "labelled_issues: brak issue ze znacznikiem tej Uwagi")
             ELSE /\ nr' = Ustaw(nr, q, Swoje(biez[q], q, zna)) /\ kom' = Ustaw(kom, q, Dopisz(Reszta(biez[q])))
                  /\ Idz(q, "czytaj", "labelled_issues: jest issue ze znacznikiem tej Uwagi, _settle z reszta czesci")
    /\ UNCHANGED <<niewidoczne, zakladanie, pamiec, wydanieNiewidoczne, pamiecWydania, falszywe>>
    /\ UNCHANGED <<dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, bezZnacznika,
                   arch, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia>>

WTresci(i, w, k) == Moj(issues[i].tresc[1], w) /\ issues[i].tresc[1][2] = k
Komentarze(i, w, k) == {j \in 2..Len(issues[i].tresc) : Moj(issues[i].tresc[j], w) /\ issues[i].tresc[j][2] = k}
Wersja(i, w, k) == issues[i].tresc[Najnizszy(Komentarze(i, w, k))][1]
Krok(i, w, k) ==
    IF WTresci(i, w, k) THEN "jest"
    ELSE IF Komentarze(i, w, k) = {} THEN "dopisz"
    ELSE IF Nr(Wersja(i, w, k)) < Nr(w) THEN "popraw"
    ELSE "jest"
Wycofaj(i, w) == SelectSeq([k \in 1..Najwiecej |-> <<k, "wycofaj">>],
                           LAMBDA x : x[1] > Liczba(w) /\ ~WTresci(i, w, x[1]) /\ Komentarze(i, w, x[1]) /= {}
                                      /\ Nr(Wersja(i, w, x[1])) < Nr(w))
Plan(i, w, ks) == SelectSeq([n \in 1..Len(ks) |-> <<ks[n][1], Krok(i, w, ks[n][1])>>], LAMBDA x : x[2] /= "jest")
                  \o Wycofaj(i, w)
Nowsza(i, w) == \E j \in 1..Len(issues[i].tresc) : Moj(issues[i].tresc[j], w) /\ Nr(issues[i].tresc[j][1]) > Nr(w)

Czytaj(q) ==
    LET nowsza == Nowsza(nr[q], biez[q])
        plan == IF nowsza THEN <<>> ELSE Plan(nr[q], biez[q], kom[q])
    IN
    /\ pc[q] = "czytaj"
    /\ \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, "comments: Unreachable (brak sieci), przejscie staje")
          /\ UNCHANGED <<kom, po>>
       \/ /\ kom' = Ustaw(kom, q, plan)
          /\ UNCHANGED <<sieci, stopped, nieczytany>>
          /\ IF nowsza
             THEN /\ UNCHANGED po
                  /\ Idz(q, "dostarczona", "comments: issue ma nowsza wersje tej wysylki, Delivered bez zapisu")
             ELSE IF plan = <<>>
             THEN PoArchiwum(q, "dostarczona", "comments: kazda czesc juz jest w Skrzynce, Delivered")
             ELSE PoArchiwum(q, "komentuj", "comments: brakujace czesci komentarzami, starsza wersja poprawka, _RETIRED")
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, bezZnacznika,
                   arch, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy,
                   odmowyArchiwum, bledyPliku, wylaczenia, slady>>

Zaloz(q) ==
    LET w == biez[q]
        nowe == Append(issues, [klucz |-> Klucz, tresc |-> <<Cialo(w)>>])
        zaLista == IF OpoznienieListy THEN niewidoczne \cup {Len(nowe)} ELSE niewidoczne
    IN
    /\ pc[q] = "zaloz"
    /\ \/ /\ Wstrzymane(q, "issue")
          /\ Stop(q, "open_issue: _held, lista sprzed LIST_LAG_S po zakladaniu bez odpowiedzi, Unreachable bez zapytania")
          /\ UNCHANGED <<issues, nr, kom, rejected, sieci, zgubione, odmowy, slady, odrzucone, bledyPliku, opoznienie>>
       \/ /\ OpoznienieListy /\ ~Wstrzymane(q, "issue") /\ bledyPliku < MaxBledowPliku
          /\ bledyPliku' = bledyPliku + 1
          /\ Stop(q, "open_issue: _noted, zapis chwili zakladania rzuca OSError, Unreachable bez zapytania")
          /\ UNCHANGED <<issues, nr, kom, rejected, sieci, zgubione, odmowy, slady, odrzucone, opoznienie>>
       \/ /\ ~Wstrzymane(q, "issue")
          /\ issues' = nowe /\ niewidoczne' = zaLista /\ Zapis(q, "issue", TRUE)
          /\ pamiec' = IF OpoznienieListy THEN pamiec \cup {Len(nowe)} ELSE pamiec
          /\ nr' = Ustaw(nr, q, Len(nowe)) /\ kom' = Ustaw(kom, q, Dopisz(Reszta(w)))
          /\ UNCHANGED <<stopped, nieczytany, rejected, sieci, zgubione, odmowy, slady, odrzucone, bledyPliku,
                         wydanieNiewidoczne, pamiecWydania, falszywe>>
          /\ IF Reszta(w) = <<>>
             THEN Idz(q, "dostarczona", "open_issue: Sent, cala wysylka w tresci issue")
             ELSE Idz(q, "komentuj", "open_issue: Sent, reszta czesci komentarzami (_comment_all)")
       \/ /\ OpoznienieListy /\ ~Wstrzymane(q, "issue") /\ bledyPliku < MaxBledowPliku
          /\ bledyPliku' = bledyPliku + 1
          /\ issues' = nowe /\ niewidoczne' = zaLista /\ Zapis(q, "issue", FALSE)
          /\ nr' = Ustaw(nr, q, Len(nowe)) /\ kom' = Ustaw(kom, q, Dopisz(Reszta(w)))
          /\ UNCHANGED <<stopped, nieczytany, rejected, sieci, zgubione, odmowy, slady, odrzucone, pamiec,
                         wydanieNiewidoczne, pamiecWydania, falszywe>>
          /\ IF Reszta(w) = <<>>
             THEN Idz(q, "dostarczona", "open_issue: Sent, _settled: zapis skutku rzuca OSError, cala wysylka w tresci")
             ELSE Idz(q, "komentuj", "open_issue: Sent, _settled: zapis skutku rzuca OSError, reszta komentarzami")
       \/ /\ ~Wstrzymane(q, "issue") /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Zapis(q, "issue", FALSE)
          /\ Stop(q, "open_issue: Unreachable przed skutkiem, przejscie staje")
          /\ UNCHANGED <<issues, nr, kom, rejected, zgubione, odmowy, slady, odrzucone, bledyPliku, niewidoczne, pamiec,
                         wydanieNiewidoczne, pamiecWydania, falszywe>>
       \/ /\ ~Wstrzymane(q, "issue") /\ zgubione < MaxZgubionych
          /\ zgubione' = zgubione + 1 /\ issues' = nowe /\ niewidoczne' = zaLista
          /\ Zapis(q, "issue", FALSE)
          /\ Stop(q, "open_issue: Skrzynka zaklada issue, odpowiedz ginie (Unreachable), przejscie staje")
          /\ UNCHANGED <<nr, kom, rejected, sieci, odmowy, odrzucone, slady, bledyPliku, pamiec, wydanieNiewidoczne,
                         pamiecWydania, falszywe>>
       \/ /\ ~Wstrzymane(q, "issue") /\ odmowy < MaxOdmowTresci
          /\ odmowy' = odmowy + 1 /\ odrzucone' = odrzucone \cup {w}
          /\ Odrzuc(q, w, "open_issue: Rejected, plik zakladania jak przed zapisem, plik czeka do nastepnego startu")
          /\ UNCHANGED <<issues, nr, kom, stopped, nieczytany, sieci, zgubione, slady, bledyPliku, opoznienie>>
    /\ UNCHANGED <<dysk, archiwa, zyje, draining, again, armed, undeleted, lista, czytane, biez, bezZnacznika, arch, po, odmowaArch, wzCzeka,
                   passes, blokada, bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, odmowyArchiwum, wylaczenia>>

Komentuj(q) ==
    LET w == biez[q]
        k == Head(kom[q])[1]
        popraw == Head(kom[q])[2] \in {"popraw", "wycofaj"}
        zapis == IF popraw
                 THEN [issues EXCEPT ![nr[q]].tresc[Najnizszy(Komentarze(nr[q], w, k))] = <<w, k>>]
                 ELSE [issues EXCEPT ![nr[q]].tresc = Append(@, <<w, k>>)]
        zapytanie == CASE Head(kom[q])[2] = "popraw" -> "edit_comment"
                       [] Head(kom[q])[2] = "wycofaj" -> "edit_comment (_RETIRED)"
                       [] OTHER -> "comment"
    IN
    /\ pc[q] = "komentuj"
    /\ \/ /\ issues' = zapis
          /\ kom' = Ustaw(kom, q, Tail(kom[q]))
          /\ UNCHANGED <<stopped, nieczytany, rejected, sieci, zgubione, odmowy, odrzucone>>
          /\ IF Tail(kom[q]) = <<>>
             THEN Idz(q, "dostarczona", zapytanie \o ": Commented, ostatnia czesc, Delivered")
             ELSE Idz(q, "komentuj", zapytanie \o ": Commented")
       \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, zapytanie \o ": Unreachable przed skutkiem, przejscie staje")
          /\ UNCHANGED <<issues, kom, rejected, zgubione, odmowy, odrzucone>>
       \/ /\ zgubione < MaxZgubionych
          /\ zgubione' = zgubione + 1 /\ issues' = zapis
          /\ Stop(q, zapytanie \o ": Skrzynka przyjmuje, odpowiedz ginie, przejscie staje")
          /\ UNCHANGED <<kom, rejected, sieci, odmowy, odrzucone>>
       \/ /\ odmowy < MaxOdmowTresci
          /\ odmowy' = odmowy + 1 /\ odrzucone' = odrzucone \cup {w}
          /\ Odrzuc(q, w, zapytanie \o ": Rejected, plik czeka do nastepnego startu")
          /\ UNCHANGED <<issues, kom, stopped, nieczytany, sieci, zgubione>>
    /\ UNCHANGED <<wzCzeka>>
    /\ UNCHANGED <<opoznienie, dysk, archiwa, zyje, draining, again, armed, undeleted, lista, czytane, biez, nr, bezZnacznika, arch, po,
                   odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, odmowyArchiwum,
                   bledyPliku, wylaczenia, slady>>

PlikLogow(q, czeka) ==
    LET w == biez[q]
        moje == Pliki(w)
    IN
    IF \E i \in moje : Nr(archiwum[i]) >= Nr(w)
    THEN /\ arch' = Ustaw(arch, q, IF czeka THEN "czeka" ELSE "jest")
         /\ Idz(q, po[q], IF czeka THEN "archive: plik jest, Wzorzec czeka, ArchiveWaits(logs=False)"
                                   ELSE "archive: plik jest w tej wersji albo nowszej, InArchive")
    ELSE IF moje /= {}
    THEN /\ UNCHANGED arch
         /\ Idz(q, "usunplik", "archive: plik starszej wersji ustepuje, remove")
    ELSE /\ UNCHANGED arch
         /\ Idz(q, "wyslij", "archive: pliku nie ma, upload")

CzytajArchiwum(q) ==
    /\ pc[q] = "archiwum"
    /\ wzCzeka' = Ustaw(wzCzeka, q, FALSE)
    /\ IF odmowaArch[q]
       THEN /\ UNCHANGED <<sieci, odmowyArchiwum, stopped, nieczytany, bledyPliku>>
            /\ UNCHANGED odczyt
            /\ Czeka(q, "_deliver_archive: archive_open = False, Archiwum odmowilo w tym przejsciu")
       ELSE \/ /\ sieci < MaxBrakSieci
               /\ sieci' = sieci + 1
               /\ UNCHANGED <<odmowyArchiwum, arch, odczyt, bledyPliku>>
               /\ Stop(q, "archive: Unreachable (brak sieci), przejscie staje")
            \/ /\ odmowyArchiwum < MaxOdmowArchiwum
               /\ odmowyArchiwum' = odmowyArchiwum + 1
               /\ UNCHANGED <<sieci, stopped, nieczytany, odczyt, bledyPliku>>
               /\ Czeka(q, "archive: Refused (Token bez uprawnienia do tresci repozytorium), ArchiveWaits")
            \/ \E zna \in OdczytyZapisow :
               /\ UNCHANGED <<sieci, odmowyArchiwum, stopped, nieczytany>>
               /\ bledyPliku' = IF zna THEN bledyPliku ELSE bledyPliku + 1
               /\ odczyt' = [odczyt EXCEPT ![q]["archiwum"] = ~zna \/ Swieze(q, "archiwum")]
               /\ IF wydania = 0 \/ (wydanieNiewidoczne /\ ~(zna /\ pamiecWydania))
                  THEN /\ UNCHANGED arch
                       /\ Idz(q, "wydanie", "archive: brak Archiwum okresu na liscie, open_archive")
                  ELSE IF Wzorzec /\ wzorce = 0
                  THEN /\ UNCHANGED arch
                       /\ Idz(q, "wzorzec", "archive: Wzorca nie ma w Archiwum, upload Wzorca przed plikiem Logow")
                  ELSE PlikLogow(q, FALSE)
    /\ UNCHANGED <<niewidoczne, zakladanie, pamiec, wydanieNiewidoczne, pamiecWydania, falszywe, dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy,
                   wylaczenia, slady>>

WyslijWzorzec(q) ==
    /\ pc[q] = "wzorzec"
    /\ \/ /\ wzorce = 0
          /\ wzorce' = 1
          /\ UNCHANGED <<sieci, zgubione, odmowyArchiwum, stopped, nieczytany, wzCzeka>>
          /\ PlikLogow(q, FALSE)
       \/ /\ wzorce > 0
          /\ wzCzeka' = Ustaw(wzCzeka, q, TRUE)
          /\ UNCHANGED <<wzorce, sieci, zgubione, odmowyArchiwum, stopped, nieczytany>>
          /\ PlikLogow(q, TRUE)
       \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ UNCHANGED <<wzorce, zgubione, odmowyArchiwum, arch, wzCzeka>>
          /\ Stop(q, "upload Wzorca: Unreachable przed skutkiem, przejscie staje")
       \/ /\ zgubione < MaxZgubionych /\ wzorce = 0
          /\ zgubione' = zgubione + 1 /\ wzorce' = 1
          /\ UNCHANGED <<sieci, odmowyArchiwum, arch, wzCzeka>>
          /\ Stop(q, "upload Wzorca: Skrzynka przyjmuje Wzorzec, odpowiedz ginie, przejscie staje")
       \/ /\ odmowyArchiwum < MaxOdmowArchiwum
          /\ odmowyArchiwum' = odmowyArchiwum + 1
          /\ wzCzeka' = Ustaw(wzCzeka, q, TRUE)
          /\ UNCHANGED <<wzorce, sieci, zgubione, stopped, nieczytany>>
          /\ PlikLogow(q, TRUE)
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwum, wydania, podwojny, zyje, draining, again, armed, undeleted, rejected,
                   lista, czytane, biez, nr, kom, bezZnacznika, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia,
                   nadawanie, odmowy, bledyPliku, wylaczenia, slady>>

OdmowaPustegoRepo(q) ==
    /\ UNCHANGED <<stopped, nieczytany>>
    /\ Czeka(q, "open_archive: 409 Git Repository is empty, Rejected, ArchiveWaits")

ZalozArchiwum(q) ==
    LET zaListe == OpoznienieListy
    IN
    /\ pc[q] = "wydanie"
    /\ \/ /\ Wstrzymane(q, "archiwum")
          /\ UNCHANGED <<wydania, sieci, zgubione, odmowyArchiwum, arch, opoznienie>>
          /\ Stop(q, "open_archive: _held, lista sprzed LIST_LAG_S po zakladaniu bez odpowiedzi, Unreachable bez zapytania")
       \/ /\ ~Wstrzymane(q, "archiwum") /\ ~PusteRepo /\ wydania = 0
          /\ wydania' = wydania + 1 /\ wydanieNiewidoczne' = zaListe /\ pamiecWydania' = IF zaListe THEN TRUE ELSE pamiecWydania
          /\ Zapis(q, "archiwum", TRUE)
          /\ UNCHANGED <<sieci, zgubione, odmowyArchiwum, stopped, nieczytany, arch, niewidoczne, pamiec, falszywe>>
          /\ Idz(q, IF Wzorzec THEN "wzorzec" ELSE "wyslij", "open_archive: Archive bez plikow, upload Wzorca, potem pliku Logow")
       \/ /\ ~Wstrzymane(q, "archiwum") /\ ~PusteRepo /\ wydania > 0
          /\ falszywe' = TRUE
          /\ UNCHANGED <<wydania, sieci, zgubione, odmowyArchiwum, niewidoczne, zakladanie, pamiec, odczyt,
                         wydanieNiewidoczne, pamiecWydania>>
          /\ UNCHANGED <<stopped, nieczytany>>
          /\ Czeka(q, "open_archive: 422, Release tego tagu juz jest, Rejected, ArchiveWaits")
       \/ /\ ~Wstrzymane(q, "archiwum") /\ PusteRepo
          /\ UNCHANGED <<wydania, sieci, zgubione, odmowyArchiwum, opoznienie>>
          /\ OdmowaPustegoRepo(q)
       \/ /\ ~Wstrzymane(q, "archiwum") /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Zapis(q, "archiwum", FALSE)
          /\ UNCHANGED <<wydania, zgubione, odmowyArchiwum, arch, niewidoczne, pamiec, wydanieNiewidoczne, pamiecWydania,
                         falszywe>>
          /\ Stop(q, "open_archive: Unreachable przed skutkiem, przejscie staje")
       \/ /\ ~Wstrzymane(q, "archiwum") /\ ~PusteRepo /\ wydania = 0 /\ zgubione < MaxZgubionych
          /\ zgubione' = zgubione + 1 /\ wydania' = wydania + 1 /\ wydanieNiewidoczne' = zaListe
          /\ Zapis(q, "archiwum", FALSE)
          /\ UNCHANGED <<sieci, odmowyArchiwum, arch, niewidoczne, pamiec, pamiecWydania, falszywe>>
          /\ Stop(q, "open_archive: Skrzynka zaklada Archiwum, odpowiedz ginie, przejscie staje")
       \/ /\ ~Wstrzymane(q, "archiwum") /\ odmowyArchiwum < MaxOdmowArchiwum
          /\ odmowyArchiwum' = odmowyArchiwum + 1
          /\ UNCHANGED <<wydania, sieci, zgubione, stopped, nieczytany, opoznienie>>
          /\ Czeka(q, "open_archive: Refused albo Rejected, ArchiveWaits")
    /\ UNCHANGED <<dysk, issues, archiwum, podwojny, wzorce, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, odmowy, bledyPliku,
                   wylaczenia, slady>>

UsunPlik(q) ==
    LET w == biez[q]
        zostaje == SelectSeq(archiwum, LAMBDA e : Id(e) /= Id(w))
        zbedny == \E i \in Pliki(w) : Nr(archiwum[i]) >= Nr(w)
    IN
    /\ pc[q] = "usunplik"
    /\ \/ /\ archiwum' = zostaje /\ podwojny' = (podwojny \/ zbedny)
          /\ UNCHANGED <<sieci, zgubione, odmowyArchiwum, stopped, nieczytany, arch>>
          /\ Idz(q, "wyslij", "remove: Removed, upload tej wersji")
       \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ UNCHANGED <<archiwum, podwojny, zgubione, odmowyArchiwum, arch>>
          /\ Stop(q, "remove: Unreachable przed skutkiem, przejscie staje")
       \/ /\ zgubione < MaxZgubionych
          /\ zgubione' = zgubione + 1 /\ archiwum' = zostaje /\ podwojny' = (podwojny \/ zbedny)
          /\ UNCHANGED <<sieci, odmowyArchiwum, arch>>
          /\ Stop(q, "remove: Skrzynka usuwa plik, odpowiedz ginie, przejscie staje")
       \/ /\ odmowyArchiwum < MaxOdmowArchiwum
          /\ odmowyArchiwum' = odmowyArchiwum + 1
          /\ UNCHANGED <<archiwum, podwojny, sieci, zgubione, stopped, nieczytany>>
          /\ Czeka(q, "remove: Refused, ArchiveWaits")
    /\ UNCHANGED <<wzorce>>
    /\ UNCHANGED <<opoznienie, dysk, issues, wydania, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, odmowy, bledyPliku,
                   wylaczenia, slady>>

WyslijPlik(q) ==
    LET w == biez[q]
        zajety == Pliki(w) /= {}
        wyslany == IF zajety THEN archiwum ELSE Append(archiwum, w)
    IN
    /\ pc[q] = "wyslij"
    /\ \/ /\ ~zajety
          /\ archiwum' = wyslany
          /\ arch' = Ustaw(arch, q, IF wzCzeka[q] THEN "czeka" ELSE "jest")
          /\ UNCHANGED <<sieci, zgubione, odmowyArchiwum, stopped, nieczytany>>
          /\ Idz(q, po[q], IF wzCzeka[q] THEN "upload: Asset, Wzorzec czeka, ArchiveWaits(logs=False)" ELSE "upload: Asset, InArchive")
       \/ /\ zajety
          /\ UNCHANGED <<archiwum, sieci, zgubione, odmowyArchiwum, stopped, nieczytany>>
          /\ Czeka(q, "upload: Rejected (plik tej nazwy juz jest), ArchiveWaits")
       \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ UNCHANGED <<archiwum, zgubione, odmowyArchiwum, arch>>
          /\ Stop(q, "upload: Unreachable przed skutkiem, przejscie staje")
       \/ /\ zgubione < MaxZgubionych
          /\ zgubione' = zgubione + 1 /\ archiwum' = wyslany
          /\ UNCHANGED <<sieci, odmowyArchiwum, arch>>
          /\ Stop(q, "upload: Skrzynka przyjmuje plik, odpowiedz ginie, przejscie staje")
       \/ /\ odmowyArchiwum < MaxOdmowArchiwum
          /\ odmowyArchiwum' = odmowyArchiwum + 1
          /\ UNCHANGED <<archiwum, sieci, zgubione, stopped, nieczytany>>
          /\ Czeka(q, "upload: Refused, ArchiveWaits")
    /\ UNCHANGED <<wzorce>>
    /\ UNCHANGED <<opoznienie, dysk, issues, wydania, podwojny, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, odmowy, bledyPliku,
                   wylaczenia, slady>>

Znacznik(q) ==
    LET w == biez[q]
        czeka == arch[q] = "czeka"
    IN
    /\ pc[q] = "dostarczona"
    /\ stopped' = Ustaw(stopped, q, FALSE)
    /\ odmowaArch' = IF czeka THEN Ustaw(odmowaArch, q, TRUE) ELSE odmowaArch
    /\ UNCHANGED nieczytany
    /\ IF czeka /\ plik[w] = "skomentowany"
       THEN /\ UNCHANGED <<tmp, bezZnacznika, bledyPliku>>
            /\ Idz(q, "plik", "_archive_waits: plik czeka dalej na Archiwum")
       ELSE \/ /\ tmp' = tmp \cup {w}
               /\ UNCHANGED <<bezZnacznika, bledyPliku>>
               /\ Idz(q, "zamiana", IF czeka THEN "_archive_waits, znacznik czesci: replace_atomically zapisuje plik .json.tmp"
                                    ELSE "znacznik: replace_atomically zapisuje plik .json.tmp")
            \/ /\ bledyPliku < MaxBledowPliku
               /\ bledyPliku' = bledyPliku + 1
               /\ bezZnacznika' = Ustaw(bezZnacznika, q, TRUE)
               /\ UNCHANGED tmp
               /\ IF czeka THEN Idz(q, "plik", "znacznik czesci: write_text pliku .json.tmp rzuca OSError (suppress)")
                  ELSE Idz(q, "usun", "znacznik: write_text pliku .json.tmp rzuca OSError (suppress), _remove")
    /\ UNCHANGED <<wzCzeka>>
    /\ UNCHANGED <<opoznienie, plik, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom, arch, po,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, odmowyArchiwum,
                   wylaczenia, slady>>

Zamiana(q) ==
    LET w == biez[q]
        czeka == arch[q] = "czeka"
        dalej == IF czeka THEN "plik" ELSE "usun"
    IN
    /\ pc[q] = "zamiana"
    /\ tmp' = tmp \ {w}
    /\ \/ /\ w \in tmp
          /\ plik' = [plik EXCEPT ![w] = IF czeka THEN "skomentowany" ELSE "oznaczony"]
          /\ UNCHANGED <<bezZnacznika, bledyPliku>>
          /\ Idz(q, dalej, IF czeka THEN "znacznik czesci: os.replace, plik czeka tylko na Archiwum"
                          ELSE "znacznik: os.replace, plik ma delivered_parts = len(parts); _remove")
       \/ /\ w \in tmp /\ bledyPliku < MaxBledowPliku
          /\ bledyPliku' = bledyPliku + 1
          /\ bezZnacznika' = Ustaw(bezZnacznika, q, TRUE)
          /\ UNCHANGED plik
          /\ Idz(q, dalej, "znacznik: os.replace rzuca OSError (suppress), plik bez znacznika")
       \/ /\ w \notin tmp
          /\ bezZnacznika' = Ustaw(bezZnacznika, q, TRUE)
          /\ UNCHANGED <<plik, bledyPliku>>
          /\ Idz(q, dalej, "znacznik: pliku .json.tmp juz nie ma, os.replace rzuca OSError (suppress)")
    /\ UNCHANGED <<opoznienie, issues, archiwa, zyje, draining, again, armed, stopped, nieczytany, undeleted, rejected, lista, czytane, biez, nr,
                   kom, arch, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione,
                   odmowy, odmowyArchiwum, wylaczenia, slady>>

Usun(q) ==
    LET w == biez[q] IN
    /\ pc[q] = "usun"
    /\ bezZnacznika' = Ustaw(bezZnacznika, q, FALSE)
    /\ \/ /\ plik' = [plik EXCEPT ![w] = "usuniety"]
          /\ undeleted' = Ustaw(undeleted, q, undeleted[q] \ {w})
          /\ UNCHANGED bledyPliku
          /\ Idz(q, "plik", "_remove: unlink")
       \/ /\ bledyPliku < MaxBledowPliku /\ plik[w] /= "usuniety"
          /\ bledyPliku' = bledyPliku + 1
          /\ undeleted' = Ustaw(undeleted, q, undeleted[q] \cup {w})
          /\ UNCHANGED plik
          /\ Idz(q, "plik", "_remove: unlink rzuca OSError, plik zostaje, nazwa w _undeleted")
    /\ UNCHANGED <<opoznienie, tmp, issues, archiwa, zyje, draining, again, armed, stopped, nieczytany, rejected, lista, czytane, biez, nr, kom,
                   arch, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia, slady>>

Zwolnij(q) ==
    /\ pc[q] = "zwolnij"
    /\ blokada' = IF blokada = q THEN 0 ELSE blokada
    /\ again' = IF passes[Proc(q)] = "prosba" THEN Ustaw(again, q, TRUE) ELSE again
    /\ passes' = Ustaw(passes, Proc(q), "wolny")
    /\ Idz(q, "decyzja", "_drain: koniec _folder_lock, _released")
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, draining, armed, stopped, nieczytany, bezBlokady, undeleted, rejected,
                   lista, czytane, biez, nr, kom, bezZnacznika, arch, po, odmowaArch, wzCzeka, zamkniecia, nadawanie, awarie, slady>>

Decyzja(q) ==
    /\ pc[q] = "decyzja"
    /\ IF again[q]
       THEN /\ again' = Ustaw(again, q, FALSE)
            /\ UNCHANGED <<draining, armed>>
            /\ Idz(q, "petla", "_drain: _again, nastepne przejscie")
       ELSE /\ draining' = Ustaw(draining, q, FALSE)
            /\ armed' = Ustaw(armed, q, armed[q] \/ stopped[q] \/ nieczytany[q] \/ odmowaArch[q] \/ bezBlokady[q])
            /\ UNCHANGED again
            /\ Idz(q, "spi", IF stopped[q] \/ nieczytany[q] \/ odmowaArch[q] \/ bezBlokady[q]
                             THEN "_drain: koniec watku, budzenie za RETRY_S" ELSE "_drain: koniec watku")
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, stopped, nieczytany, undeleted, rejected, lista, czytane, biez, nr, kom, bezZnacznika,
                   arch, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, awarie, slady>>

Watek(q) ==
    /\ zyje[q] /= "nie"
    /\ \/ Petla(q) \/ Plik(q) \/ Szukaj(q) \/ Czytaj(q) \/ Zaloz(q) \/ Komentuj(q)
       \/ CzytajArchiwum(q) \/ ZalozArchiwum(q) \/ WyslijWzorzec(q) \/ UsunPlik(q) \/ WyslijPlik(q)
       \/ Znacznik(q) \/ Zamiana(q) \/ Usun(q) \/ Zwolnij(q) \/ Decyzja(q)

Budzenie(q) ==
    /\ zyje[q] /= "nie"
    /\ armed[q]
    /\ armed' = Ustaw(armed, q, FALSE)
    /\ Budz(q)
    /\ krok' = "_woken po RETRY_S: send_in_background"
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, stopped, nieczytany, undeleted, rejected, lista, czytane, biez, nr, kom, bezZnacznika,
                   arch, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, nadawanie, awarie, slady>>

MaPort == {q \in Q : zyje[q] = "tak"}
Port == CHOOSE q \in MaPort : \A r \in MaPort : q <= r

Nadaj(w) ==
    /\ \/ /\ nadawca[w] = "czeka"
          /\ MaPort /= {}
          /\ IF w = 1 THEN TRUE ELSE nadawca[w - 1] /= "czeka"
          /\ przez' = [przez EXCEPT ![w] = Port]
          /\ \/ /\ tmp' = tmp \cup {w}
                /\ nadawca' = [nadawca EXCEPT ![w] = "zamiana"]
                /\ UNCHANGED <<plik, bledyPliku>>
                /\ krok' = "post: replace_atomically zapisuje plik .json.tmp"
             \/ /\ bledyPliku < MaxBledowPliku
                /\ bledyPliku' = bledyPliku + 1
                /\ plik' = [plik EXCEPT ![w] = "przepadl"]
                /\ nadawca' = [nadawca EXCEPT ![w] = "koniec"]
                /\ UNCHANGED tmp
                /\ krok' = "post: write_text rzuca OSError, post zwraca False"
          /\ UNCHANGED <<zakolejkowane, draining, again, pc>>
       \/ /\ nadawca[w] = "zamiana"
          /\ tmp' = tmp \ {w}
          /\ \/ /\ w \in tmp
                /\ plik' = [plik EXCEPT ![w] = "czeka"]
                /\ zakolejkowane' = zakolejkowane \cup {w}
                /\ nadawca' = [nadawca EXCEPT ![w] = "budzi"]
                /\ UNCHANGED bledyPliku
                /\ krok' = "post: os.replace, plik kolejki bez znacznika"
             \/ /\ w \notin tmp
                /\ plik' = [plik EXCEPT ![w] = "przepadl"]
                /\ nadawca' = [nadawca EXCEPT ![w] = "koniec"]
                /\ UNCHANGED <<zakolejkowane, bledyPliku>>
                /\ krok' = "post: pliku .json.tmp juz nie ma, os.replace rzuca FileNotFoundError, post zwraca False"
             \/ /\ w \in tmp /\ bledyPliku < MaxBledowPliku
                /\ bledyPliku' = bledyPliku + 1
                /\ plik' = [plik EXCEPT ![w] = "przepadl"]
                /\ nadawca' = [nadawca EXCEPT ![w] = "koniec"]
                /\ UNCHANGED zakolejkowane
                /\ krok' = "post: os.replace rzuca OSError, post zwraca False"
          /\ UNCHANGED <<przez, draining, again, pc>>
       \/ /\ nadawca[w] = "budzi"
          /\ nadawca' = [nadawca EXCEPT ![w] = "koniec"]
          /\ Budz(przez[w])
          /\ krok' = "post: send_in_background"
          /\ UNCHANGED <<plik, tmp, przez, zakolejkowane, bledyPliku>>
    /\ nadawca[w] /= "czeka" => zyje[przez[w]] /= "nie"
    /\ UNCHANGED <<opoznienie, issues, archiwa, zyje, armed, stopped, nieczytany, undeleted, rejected, lista, czytane, biez, nr, kom, bezZnacznika,
                   arch, po, odmowaArch, wzCzeka, passes, blokada, bezBlokady, zamkniecia, odrzucone, sieci, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia, slady>>

Zabij(S) ==
    /\ zyje' = [q \in Q |-> IF q \in S THEN "nie" ELSE zyje[q]]
    /\ pc' = [q \in Q |-> IF q \in S THEN "spi" ELSE pc[q]]
    /\ draining' = [q \in Q |-> IF q \in S THEN FALSE ELSE draining[q]]
    /\ again' = [q \in Q |-> IF q \in S THEN FALSE ELSE again[q]]
    /\ armed' = [q \in Q |-> IF q \in S THEN FALSE ELSE armed[q]]
    /\ stopped' = [q \in Q |-> IF q \in S THEN FALSE ELSE stopped[q]]
    /\ nieczytany' = [q \in Q |-> IF q \in S THEN FALSE ELSE nieczytany[q]]
    /\ bezBlokady' = [q \in Q |-> IF q \in S THEN FALSE ELSE bezBlokady[q]]
    /\ undeleted' = [q \in Q |-> IF q \in S THEN {} ELSE undeleted[q]]
    /\ rejected' = [q \in Q |-> IF q \in S THEN {} ELSE rejected[q]]
    /\ lista' = [q \in Q |-> IF q \in S THEN <<>> ELSE lista[q]]
    /\ czytane' = [q \in Q |-> IF q \in S THEN {} ELSE czytane[q]]
    /\ kom' = [q \in Q |-> IF q \in S THEN <<>> ELSE kom[q]]
    /\ bezZnacznika' = [q \in Q |-> IF q \in S THEN FALSE ELSE bezZnacznika[q]]
    /\ arch' = [q \in Q |-> IF q \in S THEN "brak" ELSE arch[q]]
    /\ po' = [q \in Q |-> IF q \in S THEN "dostarczona" ELSE po[q]]
    /\ odmowaArch' = [q \in Q |-> IF q \in S THEN FALSE ELSE odmowaArch[q]]
    /\ wzCzeka' = [q \in Q |-> IF q \in S THEN FALSE ELSE wzCzeka[q]]
    /\ passes' = [p \in Procesy |-> IF \E q \in S : Proc(q) = p THEN "wolny" ELSE passes[p]]
    /\ blokada' = IF blokada \in S THEN 0 ELSE blokada
    /\ UNCHANGED <<pamiec, pamiecWydania>>
    /\ odczyt' = [q \in Q |-> IF q \in S THEN [r \in Rodzaje |-> FALSE] ELSE odczyt[q]]
    /\ plik' = [w \in W |-> IF nadawca[w] = "zamiana" /\ przez[w] \in S THEN "przepadl" ELSE plik[w]]
    /\ nadawca' = [w \in W |-> IF nadawca[w] \in {"zamiana", "budzi"} /\ przez[w] \in S THEN "koniec" ELSE nadawca[w]]
    /\ UNCHANGED slady

Wylacz ==
    /\ wylaczenia < MaxWylaczen
    /\ \E q \in Q : zyje[q] /= "nie"
    /\ wylaczenia' = wylaczenia + 1
    /\ Zabij(Q)
    /\ krok' = "komputer gasnie w tym kroku"
    /\ UNCHANGED <<niewidoczne, zakladanie, wydanieNiewidoczne, falszywe, tmp, issues, archiwa, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, sieci, zgubione, odmowy,
                   odmowyArchiwum, bledyPliku>>

Start(q) ==
    /\ zyje[q] = "nie"
    /\ IF DwaProcesy \/ q = 1 THEN MaPort = {} ELSE zyje[1] = "tak"
    /\ zyje' = Ustaw(zyje, q, "tak")
    /\ tmp' = {}
    /\ odczyt' = Ustaw(odczyt, q, [r \in Rodzaje |-> FALSE])
    /\ draining' = Ustaw(draining, q, TRUE)
    /\ pc' = Ustaw(pc, q, "petla")
    /\ krok' = "Centrum startuje: Outbox.resume usuwa *.tmp, send_in_background"
    /\ UNCHANGED <<niewidoczne, zakladanie, pamiec, pamiecWydania, wydanieNiewidoczne, falszywe, plik, issues, archiwa, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, czytane, biez,
                   nr, kom, bezZnacznika, arch, po, odmowaArch, wzCzeka, passes, blokada, zamkniecia, nadawanie, awarie, slady>>

Zamknij(q) ==
    /\ DwaProcesy
    /\ zyje[q] = "tak"
    /\ zamkniecia < 1
    /\ zamkniecia' = zamkniecia + 1
    /\ zyje' = Ustaw(zyje, q, "zamkniety")
    /\ krok' = "server.py serve: uvicorn zamyka gniazdo, proces jeszcze konczy prace"
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, watek, passes, blokada, nadawanie, awarie, slady>>

KoniecProcesu(q) ==
    /\ zyje[q] = "zamkniety"
    /\ Zabij({q})
    /\ krok' = "stary proces Centrum konczy sie, watek kolejki ginie z nim"
    /\ UNCHANGED <<niewidoczne, zakladanie, wydanieNiewidoczne, falszywe, tmp, issues, archiwa, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, awarie>>

Nadaza ==
    /\ \E i \in niewidoczne : niewidoczne' = niewidoczne \ {i}
    /\ krok' = "lista issue GitHuba pokazuje nowe issue"
    /\ UNCHANGED <<dysk, issues, archiwa, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, slady, zakladanie,
                   pamiec, odczyt, wydanieNiewidoczne, pamiecWydania, falszywe>>

NadazaWydanie ==
    /\ wydanieNiewidoczne
    /\ wydanieNiewidoczne' = FALSE
    /\ krok' = "lista Release'ow GitHuba pokazuje nowe Archiwum"
    /\ UNCHANGED <<dysk, issues, archiwa, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, slady, niewidoczne,
                   zakladanie, pamiec, odczyt, pamiecWydania, falszywe>>

Przedawnienie(r) ==
    /\ zakladanie[r] = "swieze"
    /\ IF r = "issue" THEN niewidoczne = {} ELSE ~wydanieNiewidoczne
    /\ zakladanie' = [zakladanie EXCEPT ![r] = "brak"]
    /\ krok' = "mija LIST_LAG_S od zapisu w pliku zakladania"
    /\ UNCHANGED <<dysk, issues, archiwa, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, slady, niewidoczne,
                   pamiec, odczyt, wydanieNiewidoczne, pamiecWydania, falszywe>>

Next ==
    \/ \E q \in Q : Watek(q) \/ Budzenie(q) \/ Start(q) \/ Zamknij(q) \/ KoniecProcesu(q)
    \/ Nadaza \/ NadazaWydanie \/ \E r \in Rodzaje : Przedawnienie(r)
    \/ \E w \in W : Nadaj(w)
    \/ Wylacz

Sprawiedliwosc ==
    /\ \A q \in Q : WF_vars(Watek(q)) /\ WF_vars(Budzenie(q)) /\ WF_vars(KoniecProcesu(q)) /\ WF_vars(Start(q))
    /\ \A w \in W : WF_vars(Nadaj(w))
    /\ WF_vars(Nadaza) /\ WF_vars(NadazaWydanie) /\ \A r \in Rodzaje : WF_vars(Przedawnienie(r))

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

=============================================================================
