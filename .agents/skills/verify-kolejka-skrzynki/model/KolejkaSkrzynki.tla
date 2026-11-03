------------------------------ MODULE KolejkaSkrzynki ------------------------------
(***************************************************************************)
(* Kolejka Skrzynki Zgłoszeń (src/rozliczenia/centrum/outbox.py) przy     *)
(* każdej kolejności awarii i przeplotów wątków.                          *)
(*                                                                         *)
(* Wysyłka (Post) trafia do pliku w config/zgloszenia/kolejka/ (post),     *)
(* a jeden wątek w tle (Outbox._drain, _send_all) wysyła pliki po kolei,  *)
(* oznacza wysłany plik znacznikiem dostarczenia i go usuwa.               *)
(*                                                                         *)
(* Obietnice: JednoIssue (jedno issue na okres, na problem Zgłoszenia i na *)
(* Uwagę taty, poza ryzykiem z ADR 0015), WszystkieCzesci (plik znika albo *)
(* dostaje znacznik dopiero, gdy każda jego część jest w Skrzynce),        *)
(* CzesciWKolejnosci (część k issue ma przed sobą część k-1) i Zbieganie   *)
(* (gdy awarie się skończą, każda wysyłka z kolejki jest w Skrzynce, a     *)
(* kolejka pusta).                                                         *)
(*                                                                         *)
(* Jedna akcja to jeden krok kodu: jedno zapytanie do Skrzynki, jeden      *)
(* zapis pliku tymczasowego, jedna zamiana pliku, jedno usunięcie, jedna   *)
(* decyzja pod blokadą. Komentarz przy akcji i przy każdej straży wskazuje *)
(* plik:funkcję w src/rozliczenia/centrum/. Napisy TLA+ są w ASCII.        *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Cel,            \* cel wysyłki (outbox.py Target): "okres" (PeriodThread), "nowe" (NewIssue),
                    \* "zgloszenie" (ReportIssue), "znane" (KnownIssue: issue o znanym numerze już jest)
    Czesci,         \* części jednej wysyłki (Post.parts, Post.of dzieli treść ponad COMMENT_LIMIT)
    Naglowek,       \* Post.header: treść nowego issue to nagłówek, a każda część idzie komentarzem (Logi)
    Wysylek,        \* wysyłki do tego samego celu, po kolei (ten sam wiersz rozpoznawczy)
    MaxBrakSieci,   \* Unreachable, Refused albo NoKey przed skutkiem: _waiting daje "stop"
    MaxZgubionych,  \* Unreachable po skutku: Skrzynka przyjęła zapis, a odpowiedź zginęła (POST po _TIMEOUT_S)
    MaxOdmowTresci, \* Rejected (400, 413, 422 w report_box._REJECTIONS): _waiting daje "next"
    MaxBledowPliku, \* OSError z dysku: zapis pliku tymczasowego, zamiana, usunięcie (atomic_file, _remove)
    AwariaOdczytu,  \* OSError także z odczytu pliku kolejki (outbox.py _queued)
    MaxWylaczen,    \* komputer gaśnie albo proces ginie w dowolnym kroku
    Kolejki,        \* 1 albo 2: dwie kolejki jednego folderu (_claimed, _released)
    DwaProcesy,     \* druga kolejka w nowym procesie, gdy stary zamknął port, a jego wątek jeszcze wysyła
    \* Znane znaleziska (oczekiwane.json), każde przy jednej obietnicy: ślady przyczyn, po których wariant
    \* ...PozaZnanymi tej obietnicy ją pomija. Pozostałe obietnice tego przebiegu sprawdza dalej w całości.
    WybaczoneJednoIssue, WybaczoneWszystkieCzesci, WybaczoneCzesciWKolejnosci, WybaczoneZbieganie

\* outbox.py Post.__post_init__: Zgłoszenie (ReportIssue) w więcej niż jednej części to ValueError (#724).
ASSUME Cel = "zgloszenie" => Czesci = 1

W == 1..Wysylek
Q == 1..Kolejki
\* Proces kolejki q: każda w swoim, gdy DwaProcesy, inaczej obie w jednym (wspólne _PASSES).
Proc(q) == IF DwaProcesy THEN q ELSE 1
Procesy == {Proc(q) : q \in Q}

VARIABLES
    \* Dysk taty: przeżywa wyłączenie komputera.
    plik,          \* plik kolejki <czas>-<n>-<etykieta>-<run>.json wysyłki w: "nadejdzie" (post go jeszcze nie
                   \* zapisał), "przepadl" (post zwrócił False albo zginął przed zamianą), "czeka" (bez znacznika),
                   \* "oznaczony" (delivered_parts = len(parts)) albo "usuniety"
    tmp,           \* wysyłki, których plik <nazwa>.json.tmp leży w folderze (replace_atomically przerwane)
    numer,         \* numer issue w pliku kolejki wysyłki w ("issue" w _queue_text, po Opened); 0: brak
    \* Skrzynka Zgłoszeń (GitHub): przeżywa wszystko.
    issues,        \* issue po numerze: [klucz, tresc]; klucz "L" (wiersz rozpoznawczy okresu albo odcisk
                   \* Zgłoszenia), "N" (Uwaga taty, bez wiersza) albo "Z" (issue o znanym numerze);
                   \* tresc: treść issue, potem komentarze, każdy jako <<wysyłka, część>> (0: nagłówek)
    \* Pamięć procesu: znika z procesem.
    zyje,          \* proces kolejki q: "nie", "tak" (ma port, przyjmuje zapytania HTTP) albo "zamkniety"
                   \* (uvicorn zamknął gniazdo, a proces jeszcze kończy pracę: _GRACEFUL_SHUTDOWN_S)
    pc,            \* krok wątku skrzynka-kolejka kolejki q; "spi", gdy wątek nie biegnie
    draining, again, armed, stopped, \* Outbox._draining, _again, _retry_armed, _stopped_on is not None
    nieczytany,    \* Outbox._read_failed: przejście pominęło plik, którego nie dało się odczytać
    bezBlokady,    \* Outbox._locked_out: przejście zastało blokadę folderu u kolejki innego procesu
    undeleted, rejected,             \* Outbox._undeleted, _rejected (nazwy plików)
    lista,         \* pliki tego przejścia jeszcze nie obsłużone (sorted(glob("*.json")) w _send_all)
    biez,          \* plik, który przejście właśnie wysyła
    nr,            \* numer issue tej wysyłki (otwarte albo znalezione)
    kom,           \* części, które zostały do skomentowania (_comment_all)
    bezZnacznika,  \* zapis znacznika się nie udał (suppress(OSError) w _send_all)
    bezOchrony,    \* duch, bez odpowiednika w kodzie: pliki, przed których ponowną wysyłką chroni już tylko pamięć
                   \* tej pracy Centrum: wysłane bez znacznika, których usunięcie też się nie udało (_undeleted), i
                   \* Uwagi z odrzuconym komentarzem, których numeru issue nie dało się zapisać (_rejected)
    passes,        \* _PASSES[folder] procesu: "wolny", "zajety" (False) albo "prosba" (True)
    blokada,       \* kolejka, która trzyma blokadę systemową pliku przejscie.lock folderu (_folder_lock); 0: żadna.
                   \* Każda kolejka otwiera plik osobno; blokadę zwalnia zamknięcie pliku i koniec procesu
    zamkniecia,    \* ile razy stary proces zamknął port
    \* Zapytania HTTP, które tworzą wysyłki (Outbox.post).
    nadawca,       \* krok post wysyłki w: "czeka", "zamiana", "budzi", "koniec"
    przez,         \* kolejka, której post zapisuje wysyłkę w
    zakolejkowane, \* wysyłki, dla których post zwrócił True (plik "czeka" na dysku)
    odrzucone,     \* duch: wysyłki, których treść Skrzynka kiedyś odrzuciła (Rejected)
    \* Awarie, które już się zdarzyły.
    sieci, zgubione, odmowy, bledyPliku, wylaczenia,
    krok,          \* ostatni krok słowami kodu: z nich składa się kontrprzykład
    slady          \* przyczyny ryzyk i znanych znalezisk, które już się zdarzyły

dysk == <<plik, tmp, numer>>
watek == <<pc, draining, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, biez, nr, kom, bezZnacznika,
           bezOchrony>>
nadawanie == <<nadawca, przez, zakolejkowane, odrzucone>>
awarie == <<sieci, zgubione, odmowy, bledyPliku, wylaczenia>>
vars == <<dysk, issues, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, krok, slady>>

\* Znane znaleziska (SKILL.md, oczekiwane.json): ślad przyczyny, po której obietnica pada.
ZnaneZnaleziska == {}
\* Ryzyka, które obietnica JednoIssue przyjmuje sama (ADR 0015, docstring outbox.py, komentarze w _send_all).
Ryzyka == {"zerwane_po_zalozeniu", "bez_znacznika", "bez_numeru"}

Kroki == {"spi", "petla", "plik", "szukaj", "zaloz", "komentuj", "zapisz_numer", "zamien_numer", "dostarczona",
          "zamiana", "usun", "zwolnij", "decyzja"}
Para == (0..Wysylek) \X (0..Czesci)

TypeOK ==
    /\ plik \in [W -> {"nadejdzie", "przepadl", "czeka", "oznaczony", "usuniety"}]
    /\ tmp \subseteq W
    /\ numer \in [W -> Nat]
    /\ issues \in Seq([klucz : {"L", "N", "Z"}, tresc : Seq(Para)])
    /\ zyje \in [Q -> {"nie", "tak", "zamkniety"}]
    /\ pc \in [Q -> Kroki]
    /\ draining \in [Q -> BOOLEAN] /\ again \in [Q -> BOOLEAN]
    /\ armed \in [Q -> BOOLEAN] /\ stopped \in [Q -> BOOLEAN] /\ nieczytany \in [Q -> BOOLEAN]
    /\ bezBlokady \in [Q -> BOOLEAN]
    /\ undeleted \in [Q -> SUBSET W] /\ rejected \in [Q -> SUBSET W]
    /\ lista \in [Q -> Seq(W)] /\ biez \in [Q -> W] /\ nr \in [Q -> Nat]
    /\ kom \in [Q -> Seq(1..Czesci)] /\ bezZnacznika \in [Q -> BOOLEAN] /\ bezOchrony \in [Q -> SUBSET W]
    /\ passes \in [Procesy -> {"wolny", "zajety", "prosba"}]
    /\ blokada \in Q \cup {0}
    /\ nadawca \in [W -> {"czeka", "zamiana", "budzi", "koniec"}]
    /\ przez \in [W -> Q] /\ zakolejkowane \subseteq W /\ odrzucone \subseteq W
    /\ slady \subseteq ZnaneZnaleziska \cup Ryzyka

Init ==
    /\ plik = [w \in W |-> "nadejdzie"]
    /\ tmp = {}
    /\ numer = [w \in W |-> 0]
    \* KnownIssue: issue Uwagi taty, do którego idzie odnośnik do Logów, już jest (numer 1).
    /\ issues = IF Cel = "znane" THEN <<[klucz |-> "Z", tresc |-> <<<<0, 0>>>>]>> ELSE <<>>
    /\ zyje = [q \in Q |-> "nie"]
    /\ pc = [q \in Q |-> "spi"]
    /\ draining = [q \in Q |-> FALSE] /\ again = [q \in Q |-> FALSE]
    /\ armed = [q \in Q |-> FALSE] /\ stopped = [q \in Q |-> FALSE] /\ nieczytany = [q \in Q |-> FALSE]
    /\ bezBlokady = [q \in Q |-> FALSE]
    /\ undeleted = [q \in Q |-> {}] /\ rejected = [q \in Q |-> {}]
    /\ lista = [q \in Q |-> <<>>] /\ biez = [q \in Q |-> 1] /\ nr = [q \in Q |-> 0]
    /\ kom = [q \in Q |-> <<>>] /\ bezZnacznika = [q \in Q |-> FALSE] /\ bezOchrony = [q \in Q |-> {}]
    /\ passes = [p \in Procesy |-> "wolny"]
    /\ blokada = 0
    /\ zamkniecia = 0
    /\ nadawca = [w \in W |-> "czeka"] /\ przez = [w \in W |-> 1] /\ zakolejkowane = {} /\ odrzucone = {}
    /\ sieci = 0 /\ zgubione = 0 /\ odmowy = 0 /\ bledyPliku = 0 /\ wylaczenia = 0
    /\ krok = "start"
    /\ slady = {}

\* --- Skrzynka -----------------------------------------------------------------

Zakres(s) == {s[i] : i \in 1..Len(s)}
Klucz == IF Cel = "nowe" THEN "N" ELSE IF Cel = "znane" THEN "Z" ELSE "L"
\* Post.opening: treść nowego issue to nagłówek albo część 1, a reszta części to komentarze.
Cialo(w) == IF Naglowek THEN <<w, 0>> ELSE <<w, 1>>
Od(a) == [i \in 1..(Czesci - a + 1) |-> a + i - 1]
Reszta == IF Naglowek THEN Od(1) ELSE Od(2)
\* report_box.py newest_with_line przez keyed_box.py KeyedBox.find_issue: najnowsze issue z wierszem; 0 to None.
Najnowsze == LET z == {i \in 1..Len(issues) : issues[i].klucz = "L"} IN
             IF z = {} THEN 0 ELSE CHOOSE i \in z : \A j \in z : j <= i
\* Każda część wysyłki w jest w jednym issue (w treści albo w komentarzu).
Dostarczona(w) == \E i \in 1..Len(issues) : \A k \in 1..Czesci : <<w, k>> \in Zakres(issues[i].tresc)

\* --- Obietnice -----------------------------------------------------------------

\* Ryzyko z ADR 0015 i docstringu outbox.py: zerwane połączenie po założeniu issue albo przerwanie
\* między wysłaniem a znacznikiem może dać Uwadze taty drugie issue (NewIssue nie ma wiersza, po którym
\* by je znalazła). Komentarz w _send_all przyjmuje to samo po nieudanym znaczniku: chroni wtedy już
\* tylko _undeleted, do końca tej pracy Centrum.
JednoIssue ==
    CASE Cel \in {"okres", "zgloszenie"} ->
            Cardinality({i \in 1..Len(issues) : issues[i].klucz = "L"}) <= 1
      [] Cel = "znane" -> Len(issues) = 1
      [] Cel = "nowe" ->
            \/ \A w \in W : Cardinality({i \in 1..Len(issues) : issues[i].tresc[1] = Cialo(w)}) <= 1
            \/ slady \cap Ryzyka /= {}

\* Plik znika z kolejki, przepada albo dostaje znacznik dopiero, gdy Skrzynka ma każdą jego część.
WszystkieCzesci == \A w \in zakolejkowane : plik[w] \in {"oznaczony", "usuniety", "przepadl"} => Dostarczona(w)

\* Część k > 1 w issue ma przed sobą część k-1 tej samej wysyłki: issue czyta się po kolei.
CzesciWKolejnosci ==
    \A i \in 1..Len(issues) : \A j \in 1..Len(issues[i].tresc) :
        LET p == issues[i].tresc[j] IN
        p[2] > 1 => \E m \in 1..(j - 1) : issues[i].tresc[m] = <<p[1], p[2] - 1>>

\* Plik czeka do następnego startu Centrum, gdy Skrzynka odrzuciła jego treść (Rejected, _rejected), albo
\* jest wysłany, tylko nie dało się go usunąć (_undeleted).
Odrzucona(w) == w \in odrzucone /\ \E q \in Q : zyje[q] /= "nie" /\ w \in rejected[q]
Pamieta(w) == \E q \in Q : zyje[q] /= "nie" /\ w \in undeleted[q]

\* Gdy awarie się skończą, pliku bez znacznika nie ma, chyba że Skrzynka odrzuciła jego treść albo jest wysłany i
\* tylko nie dało się go usunąć. Plik, który zniknął albo ma znacznik, a Skrzynka nie ma jego części, łamie już
\* WszystkieCzesci, więc Zbieganie patrzy tylko na pliki bez znacznika i każde znalezisko łamie jedną obietnicę.
Zbieganie ==
    <>[](\A w \in zakolejkowane : plik[w] = "czeka" => Odrzucona(w) \/ (Pamieta(w) /\ Dostarczona(w)))

\* Przyczyna jednego ze znanych znalezisk obietnicy już się zdarzyła.
Po(wybaczone) == wybaczone \cap slady /= {}
JednoIssuePozaZnanymi == JednoIssue \/ Po(WybaczoneJednoIssue)
WszystkieCzesciPozaZnanymi == WszystkieCzesci \/ Po(WybaczoneWszystkieCzesci)
CzesciWKolejnosciPozaZnanymi == CzesciWKolejnosci \/ Po(WybaczoneCzesciWKolejnosci)
\* slady tylko rosną, więc <>Po(...) to przebieg, w którym przyczyna znanego znaleziska kiedyś się zdarzyła.
ZbieganiePozaZnanymi == Zbieganie \/ <>Po(WybaczoneZbieganie)

\* --- Pomocnicze ----------------------------------------------------------------

Ustaw(f, q, v) == [f EXCEPT ![q] = v]
\* Outbox.send_in_background: wątek już biegnie, więc _again; inaczej _draining i nowy wątek.
Budz(q) ==
    IF draining[q]
    THEN /\ again' = Ustaw(again, q, TRUE) /\ UNCHANGED <<draining, pc>>
    ELSE /\ draining' = Ustaw(draining, q, TRUE) /\ pc' = Ustaw(pc, q, "petla") /\ UNCHANGED again
Idz(q, krokKodu, opis) == pc' = Ustaw(pc, q, krokKodu) /\ krok' = opis
\* _waiting daje "stop" (brak sieci, odmowa klucza, brak klucza): _stopped_on i return z _send_all.
Stop(q, opis) ==
    /\ stopped' = Ustaw(stopped, q, TRUE)
    /\ UNCHANGED nieczytany
    /\ Idz(q, "zwolnij", opis)
\* _waiting daje "next" (odmowa treści): plik w _rejected do następnego startu, przejście idzie dalej.
Odrzuc(q, w, opis) ==
    /\ rejected' = Ustaw(rejected, q, rejected[q] \cup {w})
    /\ Idz(q, "plik", opis)
Slad(s) == slady' = slady \cup {s}

\* --- Wątek skrzynka-kolejka ----------------------------------------------------

\* outbox.py Outbox._drain: początek pętli while, _claimed, potem _folder_lock. Kolejka, która zastanie
\* przejście innej kolejki tego folderu w swoim procesie, tylko prosi o następne (_PASSES = True) i nie wysyła.
\* Zajęta kolejka bierze blokadę folderu bez czekania (_locked); gdy trzyma ją kolejka innego procesu,
\* _locked_out i przejście bez _send_all. Z blokadą zeruje _read_failed i bierze pliki po nazwie:
\* sorted(glob("*.json")) w _send_all (bez *.json.tmp i przejscie.lock). _claimed i _locked to dwa kroki
\* kodu w jednej akcji: _PASSES widzi tylko ten proces, a blokadę między nimi może wziąć tylko kolejka innego
\* procesu, co daje ten sam stan co jej blokada wzięta przed _claimed.
Petla(q) ==
    /\ pc[q] = "petla"
    /\ IF passes[Proc(q)] = "wolny"
       THEN /\ passes' = Ustaw(passes, Proc(q), "zajety")
            /\ bezBlokady' = Ustaw(bezBlokady, q, blokada /= 0)
            /\ IF blokada = 0
               THEN /\ blokada' = q
                    /\ nieczytany' = Ustaw(nieczytany, q, FALSE)
                    /\ lista' = Ustaw(lista, q, SelectSeq([i \in 1..Wysylek |-> i],
                                                          LAMBDA w : plik[w] \in {"czeka", "oznaczony"}))
                    /\ Idz(q, "plik", "_drain: _claimed, _folder_lock, _send_all bierze pliki kolejki po nazwie")
               ELSE /\ UNCHANGED <<blokada, lista, nieczytany>>
                    /\ Idz(q, "zwolnij", "_drain: _claimed, blokade folderu trzyma kolejka innego procesu, _locked_out")
       ELSE /\ passes' = Ustaw(passes, Proc(q), "prosba")
            /\ UNCHANGED <<blokada, lista, nieczytany, bezBlokady>>
            /\ Idz(q, "decyzja", "_drain: _claimed zastaje przejscie innej kolejki, prosi o nastepne")
    /\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, stopped, undeleted, rejected, biez, nr, kom,
                   bezZnacznika, bezOchrony, zamkniecia, nadawanie, awarie, slady>>

\* outbox.py Outbox._send_all, jeden plik: _undeleted (_remove), _rejected (pomija), _queued (odczyt:
\* nieczytelny albo usunięty przez inny proces plik pomija, a OSError ustawia _read_failed), delivered
\* (_remove), potem _deliver.
\* Koniec listy: self._stopped_on = None.
Plik(q) ==
    /\ pc[q] = "plik"
    /\ IF lista[q] = <<>>
       THEN /\ stopped' = Ustaw(stopped, q, FALSE)
            /\ UNCHANGED <<lista, biez, nieczytany, bledyPliku, slady>>
            /\ Idz(q, "zwolnij", "_send_all: koniec plikow, _stopped_on = None")
       ELSE LET w == Head(lista[q]) IN
            /\ lista' = Ustaw(lista, q, Tail(lista[q]))
            /\ biez' = Ustaw(biez, q, w)
            /\ UNCHANGED stopped
            /\ CASE w \in undeleted[q] ->
                      /\ UNCHANGED <<nieczytany, bledyPliku, slady>>
                      /\ Idz(q, "usun", "_send_all: plik w _undeleted, _remove")
                 [] w \in rejected[q] ->
                      /\ UNCHANGED <<nieczytany, bledyPliku, slady>>
                      /\ Idz(q, "plik", "_send_all: plik w _rejected, czeka do nastepnego startu")
                 [] OTHER ->
                      \/ /\ AwariaOdczytu /\ bledyPliku < MaxBledowPliku /\ plik[w] /= "usuniety"
                         /\ bledyPliku' = bledyPliku + 1
                         /\ nieczytany' = Ustaw(nieczytany, q, TRUE)
                         /\ UNCHANGED slady
                         /\ Idz(q, "plik", "_queued: read_text rzuca OSError, _read_failed, _skip_unreadable pomija plik")
                      \/ /\ plik[w] = "usuniety"
                         /\ nieczytany' = Ustaw(nieczytany, q, TRUE)
                         /\ UNCHANGED <<bledyPliku, slady>>
                         /\ Idz(q, "plik", "_queued: pliku juz nie ma (usunal go inny proces), _read_failed, _skip_unreadable")
                      \/ /\ plik[w] = "oznaczony"
                         /\ UNCHANGED <<nieczytany, bledyPliku, slady>>
                         /\ Idz(q, "usun", "_queued: plik ze znacznikiem dostarczenia, _remove")
                      \/ /\ plik[w] = "czeka"
                         /\ UNCHANGED <<nieczytany, bledyPliku, slady>>
                         \* _deliver: NewIssue zakłada issue od razu, reszta celów i plik z numerem issue
                         \* (Opened) najpierw pytają Skrzynkę.
                         /\ IF Cel = "nowe" /\ numer[w] = 0
                            THEN Idz(q, "zaloz", "_deliver_new_issue: wysylka z pliku")
                            ELSE Idz(q, "szukaj", "_deliver: wysylka z pliku")
    /\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, undeleted, rejected, nr, kom, bezZnacznika, bezOchrony,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia>>

\* keyed_box.py KeyedBox.labelled_issues (find_issue: newest_with_line), wołane przez outbox.py
\* _deliver_to_period, _deliver_report i _deliver_to_known. Odczyt nie zmienia Skrzynki.
Szukaj(q) ==
    /\ pc[q] = "szukaj"
    /\ \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, "labelled_issues: Unreachable (brak sieci), przejscie staje")
          /\ UNCHANGED <<nr, kom, slady>>
       \/ /\ Cel = "okres"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          \* _deliver_to_period: bez issue okresu nowe issue, a do znalezionego każda część komentarzem.
          /\ IF Najnowsze = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "find_issue: brak issue okresu")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze) /\ kom' = Ustaw(kom, q, Od(1))
                  /\ Idz(q, "komentuj", "find_issue: jest issue okresu, kazda czesc komentarzem")
       \/ /\ Cel = "zgloszenie"
          /\ UNCHANGED <<sieci, stopped, nieczytany>>
          \* _deliver_report: otwarte Zgłoszenie z tym odciskiem to Delivered(found, ()), bez komentarzy; jedyna
          \* część Zgłoszenia (ASSUME wyżej) jest już w treści tego issue.
          /\ IF Najnowsze = 0
             THEN /\ UNCHANGED <<nr, kom, slady>>
                  /\ Idz(q, "zaloz", "find_issue: brak otwartego Zgloszenia z odciskiem")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze) /\ kom' = Ustaw(kom, q, <<>>)
                  /\ UNCHANGED slady
                  /\ Idz(q, "dostarczona", "_deliver_report: jest Zgloszenie z odciskiem, Delivered(found, ()) bez komentarzy")
       \/ /\ Cel = "znane"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          \* _deliver_to_known: issue jest na liście (Gone model pomija), każda część komentarzem.
          /\ nr' = Ustaw(nr, q, 1) /\ kom' = Ustaw(kom, q, Od(1))
          /\ Idz(q, "komentuj", "_deliver_to_known: issue jest na liscie, kazda czesc komentarzem")
       \/ /\ Cel = "nowe"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          \* _deliver z issue z pliku: _deliver_to_known, issue jest na liście, komentarze z Post.opening.
          /\ nr' = Ustaw(nr, q, numer[biez[q]]) /\ kom' = Ustaw(kom, q, Reszta)
          /\ Idz(q, "komentuj", "_deliver_to_known: issue z pliku kolejki jest na liscie, reszta czesci komentarzami")
    /\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, undeleted, rejected, lista, biez, bezZnacznika, bezOchrony,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy, bledyPliku, wylaczenia>>

\* keyed_box.py KeyedBox.open_issue, wołane przez outbox.py _deliver_new_issue, _deliver_report i
\* _deliver_to_period z Post.opening (treść: nagłówek albo część 1 i wiersz rozpoznawczy).
Zaloz(q) ==
    LET w == biez[q]
        nowe == Append(issues, [klucz |-> Klucz, tresc |-> <<Cialo(w)>>])
    IN
    /\ pc[q] = "zaloz"
    /\ \/ /\ issues' = nowe
          /\ nr' = Ustaw(nr, q, Len(nowe)) /\ kom' = Ustaw(kom, q, Reszta)
          /\ UNCHANGED <<stopped, nieczytany, rejected, sieci, zgubione, odmowy, slady, odrzucone>>
          /\ IF Reszta = <<>>
             THEN Idz(q, "dostarczona", "open_issue: Sent, cala wysylka w tresci issue")
             ELSE Idz(q, "komentuj", "open_issue: Sent, reszta czesci komentarzami (_comment_all)")
       \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, "open_issue: Unreachable przed skutkiem, przejscie staje")
          /\ UNCHANGED <<issues, nr, kom, rejected, zgubione, odmowy, slady, odrzucone>>
       \/ /\ zgubione < MaxZgubionych
          /\ zgubione' = zgubione + 1 /\ issues' = nowe
          /\ Slad("zerwane_po_zalozeniu")
          /\ Stop(q, "open_issue: Skrzynka zaklada issue, odpowiedz ginie (Unreachable), przejscie staje")
          /\ UNCHANGED <<nr, kom, rejected, sieci, odmowy, odrzucone>>
       \/ /\ odmowy < MaxOdmowTresci
          /\ odmowy' = odmowy + 1 /\ odrzucone' = odrzucone \cup {w}
          /\ Odrzuc(q, w, "open_issue: Rejected, plik czeka do nastepnego startu")
          /\ UNCHANGED <<issues, nr, kom, stopped, nieczytany, sieci, zgubione, slady>>
    /\ UNCHANGED <<dysk, zyje, draining, again, armed, undeleted, lista, biez, bezZnacznika, bezOchrony, passes, blokada,
                   bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, bledyPliku, wylaczenia>>

\* keyed_box.py KeyedBox.comment, w outbox.py _comment_all po kolei; pierwsza porażka kończy wysyłkę.
Komentuj(q) ==
    LET w == biez[q]
        k == Head(kom[q])
        dopisane == [issues EXCEPT ![nr[q]].tresc = Append(@, <<w, k>>)]
    IN
    /\ pc[q] = "komentuj"
    /\ \/ /\ issues' = dopisane
          /\ kom' = Ustaw(kom, q, Tail(kom[q]))
          /\ UNCHANGED <<stopped, nieczytany, rejected, sieci, zgubione, odmowy, slady, odrzucone>>
          /\ IF Tail(kom[q]) = <<>>
             THEN Idz(q, "dostarczona", "comment: Commented, ostatnia czesc, Delivered")
             ELSE Idz(q, "komentuj", "comment: Commented")
       \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Slad("zerwane_po_zalozeniu")
          /\ Stop(q, "comment: Unreachable przed skutkiem, przejscie staje")
          /\ UNCHANGED <<issues, kom, rejected, zgubione, odmowy, odrzucone>>
       \/ /\ zgubione < MaxZgubionych
          /\ zgubione' = zgubione + 1 /\ issues' = dopisane
          /\ Slad("zerwane_po_zalozeniu")
          /\ Stop(q, "comment: Skrzynka dopisuje komentarz, odpowiedz ginie, przejscie staje")
          /\ UNCHANGED <<kom, rejected, sieci, odmowy, odrzucone>>
       \/ /\ odmowy < MaxOdmowTresci
          /\ odmowy' = odmowy + 1 /\ odrzucone' = odrzucone \cup {w}
          \* _deliver_new_issue: Rejected po założeniu issue to Opened, a _send_all zapisuje numer w pliku.
          /\ IF Cel = "nowe" /\ numer[w] = 0
             THEN /\ UNCHANGED rejected
                  /\ Idz(q, "zapisz_numer", "comment: Rejected po open_issue, Opened: plik zapamieta numer issue")
             ELSE Odrzuc(q, w, "comment: Rejected, plik czeka do nastepnego startu")
          /\ UNCHANGED <<issues, kom, stopped, nieczytany, sieci, zgubione, slady>>
    /\ UNCHANGED <<dysk, zyje, draining, again, armed, undeleted, lista, biez, nr, bezZnacznika, bezOchrony, passes,
                   blokada, bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, bledyPliku, wylaczenia>>

\* outbox.py _send_all po Opened: replace_atomically(path, _queue_text(..., issue=outcome.number)) w
\* suppress(OSError), potem plik w _rejected jak po każdym Rejected. Ten krok to atomic_file.py
\* replace_atomically: temporary.write_text; jego OSError usuwa plik tymczasowy i wychodzi z suppress.
ZapiszNumer(q) ==
    LET w == biez[q] IN
    /\ pc[q] = "zapisz_numer"
    /\ \/ /\ tmp' = tmp \cup {w}
          /\ UNCHANGED <<rejected, bledyPliku, bezOchrony>>
          /\ Idz(q, "zamien_numer", "numer issue: replace_atomically zapisuje plik .json.tmp")
       \/ /\ bledyPliku < MaxBledowPliku
          /\ bledyPliku' = bledyPliku + 1
          /\ bezOchrony' = Ustaw(bezOchrony, q, bezOchrony[q] \cup {w})
          /\ UNCHANGED tmp
          /\ Odrzuc(q, w, "numer issue: write_text pliku .json.tmp rzuca OSError (suppress), plik bez numeru w _rejected")
    /\ UNCHANGED <<plik, numer, issues, zyje, draining, again, armed, stopped, nieczytany, undeleted, lista, biez, nr, kom,
                   bezZnacznika, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia, slady>>

\* atomic_file.py replace_atomically: temporary.replace(path); OSError (także FileNotFoundError, gdy plik
\* tymczasowy usunął resume innego procesu) w suppress, plik zostaje bez numeru. Potem _rejected.
ZamienNumer(q) ==
    LET w == biez[q] IN
    /\ pc[q] = "zamien_numer"
    /\ tmp' = tmp \ {w}
    /\ \/ /\ w \in tmp
          /\ numer' = [numer EXCEPT ![w] = nr[q]]
          /\ UNCHANGED <<bledyPliku, bezOchrony>>
          /\ Odrzuc(q, w, "numer issue: os.replace, plik ma numer issue; plik w _rejected")
       \/ /\ w \in tmp /\ bledyPliku < MaxBledowPliku
          /\ bledyPliku' = bledyPliku + 1
          /\ bezOchrony' = Ustaw(bezOchrony, q, bezOchrony[q] \cup {w})
          /\ UNCHANGED numer
          /\ Odrzuc(q, w, "numer issue: os.replace rzuca OSError (suppress), plik bez numeru w _rejected")
       \/ /\ w \notin tmp
          /\ bezOchrony' = Ustaw(bezOchrony, q, bezOchrony[q] \cup {w})
          /\ UNCHANGED <<numer, bledyPliku>>
          /\ Odrzuc(q, w, "numer issue: pliku .json.tmp juz nie ma, os.replace rzuca OSError (suppress); _rejected")
    /\ UNCHANGED <<plik, issues, zyje, draining, again, armed, stopped, nieczytany, undeleted, lista, biez, nr, kom,
                   bezZnacznika, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia, slady>>

\* outbox.py _send_all po Delivered: _stopped_on = None, listener.delivered (i post jego wysyłek), _first_comments,
\* _remember_address (jego OSError trafia tylko do dziennika), potem znacznik dostarczenia:
\* replace_atomically(path, _queue_text(...)) w suppress(OSError). Ten krok to atomic_file.py
\* replace_atomically: temporary.write_text; jego OSError usuwa plik tymczasowy i wychodzi z suppress.
Znacznik(q) ==
    LET w == biez[q] IN
    /\ pc[q] = "dostarczona"
    /\ stopped' = Ustaw(stopped, q, FALSE)
    /\ UNCHANGED nieczytany
    /\ \/ /\ tmp' = tmp \cup {w}
          /\ UNCHANGED <<bezZnacznika, bledyPliku>>
          /\ Idz(q, "zamiana", "znacznik: replace_atomically zapisuje plik .json.tmp")
       \/ /\ bledyPliku < MaxBledowPliku
          /\ bledyPliku' = bledyPliku + 1
          /\ bezZnacznika' = Ustaw(bezZnacznika, q, TRUE)
          /\ UNCHANGED tmp
          /\ Idz(q, "usun", "znacznik: write_text pliku .json.tmp rzuca OSError (suppress), _remove")
    /\ UNCHANGED <<plik, numer, issues, zyje, draining, again, armed, undeleted, rejected, lista, biez, nr, kom, bezOchrony,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia, slady>>

\* atomic_file.py replace_atomically: temporary.replace(path) (ponawiane po PermissionError, ostatnie
\* OSError usuwa plik tymczasowy). Bez pliku tymczasowego (usunął go resume innego procesu) replace
\* rzuca FileNotFoundError, czyli też OSError w suppress.
Zamiana(q) ==
    LET w == biez[q] IN
    /\ pc[q] = "zamiana"
    /\ tmp' = tmp \ {w}
    /\ \/ /\ w \in tmp
          /\ plik' = [plik EXCEPT ![w] = "oznaczony"]
          /\ UNCHANGED <<bezZnacznika, bledyPliku>>
          /\ Idz(q, "usun", "znacznik: os.replace, plik ma delivered_parts = len(parts); _remove")
       \/ /\ w \in tmp /\ bledyPliku < MaxBledowPliku
          /\ bledyPliku' = bledyPliku + 1
          /\ bezZnacznika' = Ustaw(bezZnacznika, q, TRUE)
          /\ UNCHANGED plik
          /\ Idz(q, "usun", "znacznik: os.replace rzuca OSError (suppress), plik bez znacznika; _remove")
       \/ /\ w \notin tmp
          /\ bezZnacznika' = Ustaw(bezZnacznika, q, TRUE)
          /\ UNCHANGED <<plik, bledyPliku>>
          /\ Idz(q, "usun", "znacznik: pliku .json.tmp juz nie ma, os.replace rzuca OSError (suppress); _remove")
    /\ UNCHANGED <<numer, issues, zyje, draining, again, armed, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom,
                   bezOchrony, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia, slady>>

\* outbox.py Outbox._remove: path.unlink(missing_ok=True); OSError (Windows, antywirus, OneDrive trzyma
\* plik) dopisuje nazwę do _undeleted, a następne przejście tej pracy Centrum usuwa plik bez wysyłania.
Usun(q) ==
    LET w == biez[q] IN
    /\ pc[q] = "usun"
    /\ bezZnacznika' = Ustaw(bezZnacznika, q, FALSE)
    /\ \/ /\ plik' = [plik EXCEPT ![w] = "usuniety"]
          /\ undeleted' = Ustaw(undeleted, q, undeleted[q] \ {w})
          /\ bezOchrony' = Ustaw(bezOchrony, q, bezOchrony[q] \ {w})
          /\ UNCHANGED <<bledyPliku, slady>>
          /\ Idz(q, "plik", "_remove: unlink")
       \/ /\ bledyPliku < MaxBledowPliku /\ plik[w] /= "usuniety"
          /\ bledyPliku' = bledyPliku + 1
          /\ undeleted' = Ustaw(undeleted, q, undeleted[q] \cup {w})
          /\ bezOchrony' = IF bezZnacznika[q] THEN Ustaw(bezOchrony, q, bezOchrony[q] \cup {w}) ELSE bezOchrony
          /\ UNCHANGED <<plik, slady>>
          /\ Idz(q, "plik", "_remove: unlink rzuca OSError, plik zostaje, nazwa w _undeleted")
    /\ UNCHANGED <<tmp, numer, issues, zyje, draining, again, armed, stopped, nieczytany, rejected, lista, biez, nr, kom,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia>>

\* outbox.py Outbox._drain po _send_all: koniec bloku _folder_lock (zamknięcie pliku zwalnia blokadę, gdy jest
\* tej kolejki), potem finally z _released; prośba innej kolejki o przejście to _again. Dwa kroki kodu w jednej
\* akcji, jak w Petla.
Zwolnij(q) ==
    /\ pc[q] = "zwolnij"
    /\ blokada' = IF blokada = q THEN 0 ELSE blokada
    /\ again' = IF passes[Proc(q)] = "prosba" THEN Ustaw(again, q, TRUE) ELSE again
    /\ passes' = Ustaw(passes, Proc(q), "wolny")
    /\ Idz(q, "decyzja", "_drain: koniec _folder_lock, _released")
    /\ UNCHANGED <<dysk, issues, zyje, draining, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, biez,
                   nr, kom, bezZnacznika, bezOchrony, zamkniecia, nadawanie, awarie, slady>>

\* outbox.py Outbox._drain pod self._changed: z _again następne przejście; bez niego _draining = False
\* i, gdy przejście stanęło (_stopped_on), pominęło nieczytelny plik (_read_failed) albo zastało blokadę
\* folderu u innego procesu (_locked_out), a budzenie nie jest nastawione, clock.after(RETRY_S, _woken).
Decyzja(q) ==
    /\ pc[q] = "decyzja"
    /\ IF again[q]
       THEN /\ again' = Ustaw(again, q, FALSE)
            /\ UNCHANGED <<draining, armed>>
            /\ Idz(q, "petla", "_drain: _again, nastepne przejscie")
       ELSE /\ draining' = Ustaw(draining, q, FALSE)
            /\ armed' = Ustaw(armed, q, armed[q] \/ stopped[q] \/ nieczytany[q] \/ bezBlokady[q])
            /\ UNCHANGED again
            /\ Idz(q, "spi", IF stopped[q] \/ nieczytany[q] \/ bezBlokady[q] THEN "_drain: koniec watku, budzenie za RETRY_S"
                             ELSE "_drain: koniec watku")
    /\ UNCHANGED <<dysk, issues, zyje, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom, bezZnacznika, bezOchrony, passes,
                   blokada, bezBlokady, zamkniecia, nadawanie, awarie, slady>>

Watek(q) ==
    /\ zyje[q] /= "nie"
    /\ \/ Petla(q) \/ Plik(q) \/ Szukaj(q) \/ Zaloz(q) \/ Komentuj(q) \/ ZapiszNumer(q) \/ ZamienNumer(q)
       \/ Znacznik(q) \/ Zamiana(q) \/ Usun(q) \/ Zwolnij(q) \/ Decyzja(q)

\* outbox.py Outbox._woken: budzenie z clock.after (wątek zegara, także w procesie, który zamknął port).
Budzenie(q) ==
    /\ zyje[q] /= "nie"
    /\ armed[q]
    /\ armed' = Ustaw(armed, q, FALSE)
    /\ Budz(q)
    /\ krok' = "_woken po RETRY_S: send_in_background"
    /\ UNCHANGED <<dysk, issues, zyje, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom, bezZnacznika, bezOchrony, passes,
                   blokada, bezBlokady, zamkniecia, nadawanie, awarie, slady>>

\* --- Zapytania HTTP: Outbox.post ------------------------------------------------

\* Kolejka procesu z portem: tylko jej create_app przyjmuje zapytania. Straż bez odpowiednika w kodzie: w jednym
\* procesie z dwiema kolejkami każde post idzie do pierwszej (SKILL.md, What the model leaves out).
MaPort == {q \in Q : zyje[q] = "tak"}
Port == CHOOSE q \in MaPort : \A r \in MaPort : q <= r

\* outbox.py Outbox.post: nazwa z chwili i next(self._sequence) na początku, potem replace_atomically
\* nowego pliku (write_text pliku .json.tmp, potem zamiana), OSError to False (wysyłka przepadła, typ
\* wyjątku w dzienniku), potem send_in_background. Numer wysyłki to kolejność nazw: wysyłka w zaczyna
\* się po wysyłce w-1, a ich zapisy mogą się przeplatać.
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
             \* Pliku .json.tmp już nie ma (usunął go resume nowego procesu): temporary.replace rzuca
             \* FileNotFoundError, czyli OSError, i post zwraca False.
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
    /\ UNCHANGED <<numer, issues, zyje, armed, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom, bezZnacznika,
                   bezOchrony, passes, blokada, bezBlokady, zamkniecia, odrzucone, sieci, zgubione, odmowy, wylaczenia, slady>>

\* --- Procesy Centrum ------------------------------------------------------------

\* Pamięć kolejek z S po końcu ich procesu; zapytanie HTTP w trakcie post ginie z nim: plik .json.tmp
\* zostaje, a wysyłka przepada (post nie zwrócił True), plik już zamieniony czeka na resume.
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
    /\ kom' = [q \in Q |-> IF q \in S THEN <<>> ELSE kom[q]]
    /\ bezZnacznika' = [q \in Q |-> IF q \in S THEN FALSE ELSE bezZnacznika[q]]
    /\ bezOchrony' = [q \in Q |-> IF q \in S THEN {} ELSE bezOchrony[q]]
    /\ passes' = [p \in Procesy |-> IF \E q \in S : Proc(q) = p THEN "wolny" ELSE passes[p]]
    \* Koniec procesu zamyka jego pliki, a z nimi system zwalnia blokadę folderu.
    /\ blokada' = IF blokada \in S THEN 0 ELSE blokada
    /\ plik' = [w \in W |-> IF nadawca[w] = "zamiana" /\ przez[w] \in S THEN "przepadl" ELSE plik[w]]
    /\ nadawca' = [w \in W |-> IF nadawca[w] \in {"zamiana", "budzi"} /\ przez[w] \in S THEN "koniec" ELSE nadawca[w]]
    \* Przerwanie między wysłaniem a znacznikiem (docstring outbox.py): issue już jest, a plik bez znacznika.
    \* Koniec pracy Centrum z wysłanym plikiem bez znacznika, którego nie dało się usunąć (komentarz w
    \* _send_all: „bez znacznika chroni już tylko _undeleted, do końca tej pracy Centrum”).
    \* Koniec pracy Centrum z plikiem Uwagi, której komentarz Skrzynka odrzuciła po założeniu issue, a numeru
    \* issue nie dało się zapisać (komentarz w _send_all: „chroni wtedy już tylko _rejected, do końca tej pracy
    \* Centrum”).
    /\ slady' = slady
               \cup (IF \E q \in S : \/ pc[q] \in {"komentuj", "zapisz_numer", "zamien_numer", "dostarczona", "zamiana"}
                                     \/ pc[q] = "usun" /\ bezZnacznika[q]
                     THEN {"zerwane_po_zalozeniu"} ELSE {})
               \cup (IF \E q \in S : \E w \in bezOchrony[q] \ rejected[q] : plik[w] = "czeka" THEN {"bez_znacznika"} ELSE {})
               \cup (IF \E q \in S : \E w \in bezOchrony[q] \cap rejected[q] : plik[w] = "czeka" THEN {"bez_numeru"} ELSE {})

\* Komputer gaśnie albo proces Centrum ginie: dysk i Skrzynka zostają.
Wylacz ==
    /\ wylaczenia < MaxWylaczen
    /\ \E q \in Q : zyje[q] /= "nie"
    /\ wylaczenia' = wylaczenia + 1
    /\ Zabij(Q)
    /\ krok' = "komputer gasnie w tym kroku"
    /\ UNCHANGED <<tmp, numer, issues, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, sieci, zgubione, odmowy,
                   bledyPliku>>

\* app.py lifespan: Outbox.resume przed pierwszym zapytaniem HTTP usuwa pliki *.tmp (każdy w
\* suppress(OSError)) i wywołuje send_in_background. Port ma tylko jeden proces (launcher.py
\* listen_locally); druga kolejka tego samego procesu powstaje, gdy pierwsza działa. Nowy proces
\* startuje także wtedy, gdy stary po zamknięciu gniazda jeszcze kończy pracę (server.py serve:
\* _GRACEFUL_SHUTDOWN_S, a wątek kolejki dalej biegnie), a jego resume może usunąć plik .json.tmp,
\* który post albo przejście starego procesu jeszcze zamienia (Nadaj, Zamiana, ZamienNumer).
Start(q) ==
    /\ zyje[q] = "nie"
    /\ IF DwaProcesy \/ q = 1 THEN MaPort = {} ELSE zyje[1] = "tak"
    /\ zyje' = Ustaw(zyje, q, "tak")
    /\ tmp' = {}
    /\ draining' = Ustaw(draining, q, TRUE)
    /\ pc' = Ustaw(pc, q, "petla")
    /\ krok' = "Centrum startuje: Outbox.resume usuwa *.tmp, send_in_background"
    /\ UNCHANGED <<plik, numer, issues, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, biez,
                   nr, kom, bezZnacznika, bezOchrony, passes, blokada, zamkniecia, nadawanie, awarie, slady>>

\* Tata zamyka Centrum albo opiekun ponownego startu je restartuje: uvicorn zamyka gniazdo (port wolny
\* dla nowego Centrum), a proces jeszcze kończy pracę.
Zamknij(q) ==
    /\ DwaProcesy
    /\ zyje[q] = "tak"
    /\ zamkniecia < 1
    /\ zamkniecia' = zamkniecia + 1
    /\ zyje' = Ustaw(zyje, q, "zamkniety")
    /\ krok' = "server.py serve: uvicorn zamyka gniazdo, proces jeszcze konczy prace"
    /\ UNCHANGED <<dysk, issues, watek, passes, blokada, nadawanie, awarie, slady>>

\* Proces po zamknięciu portu kończy się, a jego wątki daemon giną z nim.
KoniecProcesu(q) ==
    /\ zyje[q] = "zamkniety"
    /\ Zabij({q})
    /\ krok' = "stary proces Centrum konczy sie, watek kolejki ginie z nim"
    /\ UNCHANGED <<tmp, numer, issues, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, awarie>>

Next ==
    \/ \E q \in Q : Watek(q) \/ Budzenie(q) \/ Start(q) \/ Zamknij(q) \/ KoniecProcesu(q)
    \/ \E w \in W : Nadaj(w)
    \/ Wylacz

\* Działający kod robi następny krok, budzenie przychodzi, zapytanie HTTP kończy post, stary proces
\* kiedyś się kończy, a tata uruchamia Centrum, gdy nic nie działa. Komputer gaśnie i Skrzynka zawodzi
\* skończenie wiele razy (Max...), więc po ostatniej awarii zostają kroki, które się udają.
Sprawiedliwosc ==
    /\ \A q \in Q : WF_vars(Watek(q)) /\ WF_vars(Budzenie(q)) /\ WF_vars(KoniecProcesu(q)) /\ WF_vars(Start(q))
    /\ \A w \in W : WF_vars(Nadaj(w))

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

=============================================================================
