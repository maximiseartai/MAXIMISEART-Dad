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
(* Uwagę taty), DokladnieRaz (plik znika albo dostaje znacznik dopiero,    *)
(* gdy każda jego część jest w Skrzynce, a żadna część żadnej wysyłki nie  *)
(* jest w Skrzynce dwa razy), CzesciWKolejnosci (część k issue ma przed    *)
(* sobą część k-1) i Zbieganie (gdy awarie się skończą, każda wysyłka z    *)
(* kolejki jest w Skrzynce, a kolejka pusta).                              *)
(*                                                                         *)
(* Każdy tekst kolejki w Skrzynce niesie znacznik wysyłki (outbox.py       *)
(* _mark): element <<w, k>> issue to część k wysyłki w, a w to też jej     *)
(* wersja (kolejność plików kolejki). Diagnoza to druga wersja tej samej   *)
(* wysyłki (Id), która poprawia komentarze pierwszej (edit_comment).       *)
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
    Diagnoza,       \* wysyłka 2 to nowsza wersja wysyłki 1 (ten sam run_id i etykieta: Logi po Diagnozie,
                    \* run_logs.py RunLogs.diagnosed), a nie osobna wysyłka
    \* Znane znaleziska (oczekiwane.json), każde przy jednej obietnicy: ślady przyczyn, po których wariant
    \* ...PozaZnanymi tej obietnicy ją pomija. Pozostałe obietnice tego przebiegu sprawdza dalej w całości.
    WybaczoneJednoIssue, WybaczoneDokladnieRaz, WybaczoneCzesciWKolejnosci, WybaczoneZbieganie

\* outbox.py Post.__post_init__: Zgłoszenie (ReportIssue) w więcej niż jednej części to ValueError (#724).
ASSUME Cel = "zgloszenie" => Czesci = 1
\* Nowszą wersję wysyłki daje tylko Diagnoza Logów Uruchomienia: issue okresu z nagłówkiem.
ASSUME Diagnoza => Cel = "okres" /\ Naglowek /\ Wysylek = 2

W == 1..Wysylek
\* Identyfikator wysyłki w (etykieta i run_id w znaczniku): przy Diagnozie wysyłka 2 to wersja wysyłki 1.
Id(w) == IF Diagnoza THEN 1 ELSE w
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
    \* Skrzynka Zgłoszeń (GitHub): przeżywa wszystko.
    issues,        \* issue po numerze: [klucz, tresc]; klucz "L" (wiersz rozpoznawczy okresu albo odcisk
                   \* Zgłoszenia), "N" (Uwaga taty, bez wiersza) albo "Z" (issue o znanym numerze);
                   \* tresc: treść issue, potem komentarze, każdy jako znacznik <<wysyłka, część>> (0: nagłówek)
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
    kom,           \* części do zapisania po kolei, każda <<część, "dopisz">> (comment, _comment_all) albo
                   \* <<część, "popraw">> (edit_comment w _settle)
    bezZnacznika,  \* zapis znacznika się nie udał (suppress(OSError) w _send_all)
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
    slady          \* przyczyny znanych znalezisk, które już się zdarzyły

dysk == <<plik, tmp>>
watek == <<pc, draining, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, biez, nr, kom, bezZnacznika>>
nadawanie == <<nadawca, przez, zakolejkowane, odrzucone>>
awarie == <<sieci, zgubione, odmowy, bledyPliku, wylaczenia>>
vars == <<dysk, issues, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, krok, slady>>

\* Znane znaleziska (SKILL.md, oczekiwane.json): ślad przyczyny, po której obietnica pada.
ZnaneZnaleziska == {}

Kroki == {"spi", "petla", "plik", "szukaj", "czytaj", "zaloz", "komentuj", "dostarczona", "zamiana", "usun", "zwolnij",
          "decyzja"}
Para == (0..Wysylek) \X (0..Czesci)
Zapisy == {"dopisz", "popraw"}

TypeOK ==
    /\ plik \in [W -> {"nadejdzie", "przepadl", "czeka", "oznaczony", "usuniety"}]
    /\ tmp \subseteq W
    /\ issues \in Seq([klucz : {"L", "N", "Z"}, tresc : Seq(Para)])
    /\ zyje \in [Q -> {"nie", "tak", "zamkniety"}]
    /\ pc \in [Q -> Kroki]
    /\ draining \in [Q -> BOOLEAN] /\ again \in [Q -> BOOLEAN]
    /\ armed \in [Q -> BOOLEAN] /\ stopped \in [Q -> BOOLEAN] /\ nieczytany \in [Q -> BOOLEAN]
    /\ bezBlokady \in [Q -> BOOLEAN]
    /\ undeleted \in [Q -> SUBSET W] /\ rejected \in [Q -> SUBSET W]
    /\ lista \in [Q -> Seq(W)] /\ biez \in [Q -> W] /\ nr \in [Q -> Nat]
    /\ kom \in [Q -> Seq((1..Czesci) \X Zapisy)] /\ bezZnacznika \in [Q -> BOOLEAN]
    /\ passes \in [Procesy -> {"wolny", "zajety", "prosba"}]
    /\ blokada \in Q \cup {0}
    /\ nadawca \in [W -> {"czeka", "zamiana", "budzi", "koniec"}]
    /\ przez \in [W -> Q] /\ zakolejkowane \subseteq W /\ odrzucone \subseteq W
    /\ slady \subseteq ZnaneZnaleziska

Init ==
    /\ plik = [w \in W |-> "nadejdzie"]
    /\ tmp = {}
    \* KnownIssue: issue Uwagi taty, do którego idzie odnośnik do Logów, już jest (numer 1).
    /\ issues = IF Cel = "znane" THEN <<[klucz |-> "Z", tresc |-> <<<<0, 0>>>>]>> ELSE <<>>
    /\ zyje = [q \in Q |-> "nie"]
    /\ pc = [q \in Q |-> "spi"]
    /\ draining = [q \in Q |-> FALSE] /\ again = [q \in Q |-> FALSE]
    /\ armed = [q \in Q |-> FALSE] /\ stopped = [q \in Q |-> FALSE] /\ nieczytany = [q \in Q |-> FALSE]
    /\ bezBlokady = [q \in Q |-> FALSE]
    /\ undeleted = [q \in Q |-> {}] /\ rejected = [q \in Q |-> {}]
    /\ lista = [q \in Q |-> <<>>] /\ biez = [q \in Q |-> 1] /\ nr = [q \in Q |-> 0]
    /\ kom = [q \in Q |-> <<>>] /\ bezZnacznika = [q \in Q |-> FALSE]
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
Najwyzszy(z) == IF z = {} THEN 0 ELSE CHOOSE i \in z : \A j \in z : j <= i
Najnizszy(z) == CHOOSE i \in z : \A j \in z : i <= j
\* report_box.py newest_with_line na liście labelled_issues: najnowsze issue z wierszem; 0 to None.
Najnowsze == Najwyzszy({i \in 1..Len(issues) : issues[i].klucz = "L"})
\* Znacznik e należy do wysyłki w (outbox.py _marks: ta sama etykieta i run_id, każda wersja).
Moj(e, w) == e[1] \in W /\ Id(e[1]) = Id(w)
\* outbox.py _deliver_new_issue: najnowsze issue, którego treść ma znacznik wysyłki w; 0 to brak.
Swoje(w) == Najwyzszy({i \in 1..Len(issues) : Moj(issues[i].tresc[1], w)})
\* Część k wysyłki w jest w issue i w tej wersji albo nowszej (Diagnoza ją poprawiła).
Ma(i, w, k) == \E j \in 1..Len(issues[i].tresc) :
                 Moj(issues[i].tresc[j], w) /\ issues[i].tresc[j][2] = k /\ issues[i].tresc[j][1] >= w
\* Każda część wysyłki w jest w jednym issue (w treści albo w komentarzu), w tej wersji albo nowszej.
Dostarczona(w) == \E i \in 1..Len(issues) : \A k \in 1..Czesci : Ma(i, w, k)
\* Miejsca w Skrzynce, w których jest część k wysyłki w, w każdej wersji.
Miejsca(w, k) == UNION {{<<i, j>> : j \in {m \in 1..Len(issues[i].tresc) :
                                             Moj(issues[i].tresc[m], w) /\ issues[i].tresc[m][2] = k}} :
                        i \in 1..Len(issues)}

\* --- Obietnice -----------------------------------------------------------------

\* Uwaga taty (NewIssue) ma jedno issue: następna próba znajduje issue przerwanej po znaczniku w treści.
JednoIssue ==
    CASE Cel \in {"okres", "zgloszenie"} ->
            Cardinality({i \in 1..Len(issues) : issues[i].klucz = "L"}) <= 1
      [] Cel = "znane" -> Len(issues) = 1
      [] Cel = "nowe" -> \A w \in W : Cardinality({i \in 1..Len(issues) : issues[i].tresc[1] = Cialo(w)}) <= 1

\* Plik znika z kolejki, przepada albo dostaje znacznik dopiero, gdy Skrzynka ma każdą jego część w jego wersji albo
\* nowszej, a żadna część żadnej wysyłki nie jest w Skrzynce dwa razy (ani w dwóch wersjach).
DokladnieRaz ==
    /\ \A w \in zakolejkowane : plik[w] \in {"oznaczony", "usuniety", "przepadl"} => Dostarczona(w)
    /\ \A w \in W : \A k \in 1..Czesci : Cardinality(Miejsca(w, k)) <= 1

\* Część k > 1 w issue ma przed sobą część k-1 tej samej wysyłki: issue czyta się po kolei.
CzesciWKolejnosci ==
    \A i \in 1..Len(issues) : \A j \in 1..Len(issues[i].tresc) :
        LET p == issues[i].tresc[j] IN
        p[2] > 1 => \E m \in 1..(j - 1) : Moj(issues[i].tresc[m], p[1]) /\ issues[i].tresc[m][2] = p[2] - 1

\* Plik czeka do następnego startu Centrum, gdy Skrzynka odrzuciła jego treść (Rejected, _rejected), albo
\* jest wysłany, tylko nie dało się go usunąć (_undeleted).
Odrzucona(w) == w \in odrzucone /\ \E q \in Q : zyje[q] /= "nie" /\ w \in rejected[q]
Pamieta(w) == \E q \in Q : zyje[q] /= "nie" /\ w \in undeleted[q]

\* Gdy awarie się skończą, pliku bez znacznika nie ma, chyba że Skrzynka odrzuciła jego treść albo jest wysłany i
\* tylko nie dało się go usunąć. Plik, który zniknął albo ma znacznik, a Skrzynka nie ma jego części, łamie już
\* DokladnieRaz, więc Zbieganie patrzy tylko na pliki bez znacznika i każde znalezisko łamie jedną obietnicę.
Zbieganie ==
    <>[](\A w \in zakolejkowane : plik[w] = "czeka" => Odrzucona(w) \/ (Pamieta(w) /\ Dostarczona(w)))

\* Przyczyna jednego ze znanych znalezisk obietnicy już się zdarzyła.
Po(wybaczone) == wybaczone \cap slady /= {}
JednoIssuePozaZnanymi == JednoIssue \/ Po(WybaczoneJednoIssue)
DokladnieRazPozaZnanymi == DokladnieRaz \/ Po(WybaczoneDokladnieRaz)
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
\* Każda część z listy jako nowy komentarz: kom nowego issue, przed odczytem komentarzy także issue znalezionego.
Dopisz(ks) == [n \in 1..Len(ks) |-> <<ks[n], "dopisz">>]

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
                   bezZnacznika, zamkniecia, nadawanie, awarie, slady>>

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
                         \* _deliver: każdy cel najpierw pyta Skrzynkę o issue z etykietą.
                         /\ Idz(q, "szukaj", "_deliver: wysylka z pliku")
    /\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, undeleted, rejected, nr, kom, bezZnacznika,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia>>

\* keyed_box.py KeyedBox.labelled_issues (z report_box.py newest_with_line), wołane przez outbox.py
\* _deliver_to_period, _deliver_report, _deliver_to_known i _deliver_new_issue. Odczyt nie zmienia Skrzynki.
\* Znalezione issue dostaje części przez _settle (Czytaj), nowe issue przez open_issue (Zaloz).
Szukaj(q) ==
    /\ pc[q] = "szukaj"
    /\ \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, "labelled_issues: Unreachable (brak sieci), przejscie staje")
          /\ UNCHANGED <<nr, kom, slady>>
       \/ /\ Cel = "okres"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          \* _deliver_to_period: bez issue okresu nowe issue, a w znalezionym _settle z każdą częścią.
          /\ IF Najnowsze = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "find_issue: brak issue okresu")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze) /\ kom' = Ustaw(kom, q, Dopisz(Od(1)))
                  /\ Idz(q, "czytaj", "labelled_issues: jest issue okresu, _settle z kazda czescia")
       \/ /\ Cel = "zgloszenie"
          /\ UNCHANGED <<sieci, stopped, nieczytany>>
          \* _deliver_report: bez otwartego Zgłoszenia z odciskiem nowe issue z jedyną częścią (ASSUME wyżej), a w
          \* znalezionym _settle z tą częścią jako komentarzem returned_report. Zgłoszenie, którego treść ma znacznik tej
          \* części, założyła przerwana próba tej wysyłki, więc _settle przejmuje je bez komentarza.
          /\ UNCHANGED slady
          /\ IF Najnowsze = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "labelled_issues: brak otwartego Zgloszenia z odciskiem")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze) /\ kom' = Ustaw(kom, q, Dopisz(Od(1)))
                  /\ Idz(q, "czytaj", "_deliver_report: jest Zgloszenie z odciskiem, _settle z komentarzem returned_report")
       \/ /\ Cel = "znane"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          \* _deliver_to_known: issue jest na liście (Gone model pomija), _settle z każdą częścią.
          /\ nr' = Ustaw(nr, q, 1) /\ kom' = Ustaw(kom, q, Dopisz(Od(1)))
          /\ Idz(q, "czytaj", "_deliver_to_known: issue jest na liscie, _settle z kazda czescia")
       \/ /\ Cel = "nowe"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          \* _deliver_new_issue: issue z treścią ze znacznikiem tej Uwagi (najnowsze, także zamknięte) dostaje resztę
          \* części przez _settle, a bez niego nowe issue.
          /\ IF Swoje(biez[q]) = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "labelled_issues: brak issue ze znacznikiem tej Uwagi")
             ELSE /\ nr' = Ustaw(nr, q, Swoje(biez[q])) /\ kom' = Ustaw(kom, q, Dopisz(Reszta))
                  /\ Idz(q, "czytaj", "labelled_issues: jest issue ze znacznikiem tej Uwagi, _settle z reszta czesci")
    /\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, undeleted, rejected, lista, biez, bezZnacznika,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy, bledyPliku, wylaczenia>>

\* Co _settle robi z częścią k wysyłki w w issue i: "jest", gdy znacznik tej części stoi w treści issue albo w
\* pierwszym komentarzu z nim w tej wersji lub nowszej, "popraw", gdy ten komentarz ma starszą wersję, a inaczej
\* "dopisz" (outbox.py _settle i _put).
WTresci(i, w, k) == Moj(issues[i].tresc[1], w) /\ issues[i].tresc[1][2] = k
Komentarze(i, w, k) == {j \in 2..Len(issues[i].tresc) : Moj(issues[i].tresc[j], w) /\ issues[i].tresc[j][2] = k}
Krok(i, w, k) ==
    IF WTresci(i, w, k) THEN "jest"
    ELSE IF Komentarze(i, w, k) = {} THEN "dopisz"
    ELSE IF issues[i].tresc[Najnizszy(Komentarze(i, w, k))][1] < w THEN "popraw"
    ELSE "jest"
Plan(i, w, ks) == SelectSeq([n \in 1..Len(ks) |-> <<ks[n][1], Krok(i, w, ks[n][1])>>], LAMBDA x : x[2] /= "jest")

\* keyed_box.py KeyedBox.comments w outbox.py _settle: komentarze znalezionego issue przed wysłaniem, a z nich (i z
\* treści issue) plan części, których w Skrzynce jeszcze nie ma albo są w starszej wersji. Odczyt nie zmienia Skrzynki.
\* Część nowszej wersji ponad liczbę części tej wersji (_RETIRED) model pomija: każda wersja ma Czesci części.
Czytaj(q) ==
    LET plan == Plan(nr[q], biez[q], kom[q]) IN
    /\ pc[q] = "czytaj"
    /\ \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, "comments: Unreachable (brak sieci), przejscie staje")
          /\ UNCHANGED kom
       \/ /\ kom' = Ustaw(kom, q, plan)
          /\ UNCHANGED <<sieci, stopped, nieczytany>>
          /\ IF plan = <<>>
             THEN Idz(q, "dostarczona", "comments: kazda czesc juz jest w Skrzynce, Delivered")
             ELSE Idz(q, "komentuj", "comments: brakujace czesci komentarzami, starsza wersja poprawka")
    /\ UNCHANGED <<dysk, issues, zyje, draining, again, armed, undeleted, rejected, lista, biez, nr, bezZnacznika,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy, bledyPliku, wylaczenia, slady>>

\* keyed_box.py KeyedBox.open_issue, wołane przez outbox.py _deliver_new_issue, _deliver_report i
\* _deliver_to_period z Post.opening (treść: nagłówek albo część 1 i wiersz rozpoznawczy).
Zaloz(q) ==
    LET w == biez[q]
        nowe == Append(issues, [klucz |-> Klucz, tresc |-> <<Cialo(w)>>])
    IN
    /\ pc[q] = "zaloz"
    /\ \/ /\ issues' = nowe
          /\ nr' = Ustaw(nr, q, Len(nowe)) /\ kom' = Ustaw(kom, q, Dopisz(Reszta))
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
          /\ Stop(q, "open_issue: Skrzynka zaklada issue, odpowiedz ginie (Unreachable), przejscie staje")
          /\ UNCHANGED <<nr, kom, rejected, sieci, odmowy, odrzucone, slady>>
       \/ /\ odmowy < MaxOdmowTresci
          /\ odmowy' = odmowy + 1 /\ odrzucone' = odrzucone \cup {w}
          /\ Odrzuc(q, w, "open_issue: Rejected, plik czeka do nastepnego startu")
          /\ UNCHANGED <<issues, nr, kom, stopped, nieczytany, sieci, zgubione, slady>>
    /\ UNCHANGED <<dysk, zyje, draining, again, armed, undeleted, lista, biez, bezZnacznika, passes, blokada,
                   bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, bledyPliku, wylaczenia>>

\* keyed_box.py KeyedBox.comment (_comment_all, _settle przez _put) albo KeyedBox.edit_comment (_put: komentarz
\* części w starszej wersji dostaje tekst tej wersji w tym samym miejscu issue), po kolei; pierwsza porażka kończy
\* wysyłkę.
Komentuj(q) ==
    LET w == biez[q]
        k == Head(kom[q])[1]
        popraw == Head(kom[q])[2] = "popraw"
        zapis == IF popraw
                 THEN [issues EXCEPT ![nr[q]].tresc[Najnizszy(Komentarze(nr[q], w, k))] = <<w, k>>]
                 ELSE [issues EXCEPT ![nr[q]].tresc = Append(@, <<w, k>>)]
        zapytanie == IF popraw THEN "edit_comment" ELSE "comment"
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
    /\ UNCHANGED <<dysk, zyje, draining, again, armed, undeleted, lista, biez, nr, bezZnacznika, passes,
                   blokada, bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, bledyPliku, wylaczenia, slady>>

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
    /\ UNCHANGED <<plik, issues, zyje, draining, again, armed, undeleted, rejected, lista, biez, nr, kom,
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
    /\ UNCHANGED <<issues, zyje, draining, again, armed, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia, slady>>

\* outbox.py Outbox._remove: path.unlink(missing_ok=True); OSError (Windows, antywirus, OneDrive trzyma
\* plik) dopisuje nazwę do _undeleted, a następne przejście tej pracy Centrum usuwa plik bez wysyłania.
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
    /\ UNCHANGED <<tmp, issues, zyje, draining, again, armed, stopped, nieczytany, rejected, lista, biez, nr, kom,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, wylaczenia, slady>>

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
                   nr, kom, bezZnacznika, zamkniecia, nadawanie, awarie, slady>>

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
    /\ UNCHANGED <<dysk, issues, zyje, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom, bezZnacznika, passes,
                   blokada, bezBlokady, zamkniecia, nadawanie, awarie, slady>>

Watek(q) ==
    /\ zyje[q] /= "nie"
    /\ \/ Petla(q) \/ Plik(q) \/ Szukaj(q) \/ Czytaj(q) \/ Zaloz(q) \/ Komentuj(q)
       \/ Znacznik(q) \/ Zamiana(q) \/ Usun(q) \/ Zwolnij(q) \/ Decyzja(q)

\* outbox.py Outbox._woken: budzenie z clock.after (wątek zegara, także w procesie, który zamknął port).
Budzenie(q) ==
    /\ zyje[q] /= "nie"
    /\ armed[q]
    /\ armed' = Ustaw(armed, q, FALSE)
    /\ Budz(q)
    /\ krok' = "_woken po RETRY_S: send_in_background"
    /\ UNCHANGED <<dysk, issues, zyje, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom, bezZnacznika, passes,
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
    /\ UNCHANGED <<issues, zyje, armed, stopped, nieczytany, undeleted, rejected, lista, biez, nr, kom, bezZnacznika,
                   passes, blokada, bezBlokady, zamkniecia, odrzucone, sieci, zgubione, odmowy, wylaczenia, slady>>

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
    /\ passes' = [p \in Procesy |-> IF \E q \in S : Proc(q) = p THEN "wolny" ELSE passes[p]]
    \* Koniec procesu zamyka jego pliki, a z nimi system zwalnia blokadę folderu.
    /\ blokada' = IF blokada \in S THEN 0 ELSE blokada
    /\ plik' = [w \in W |-> IF nadawca[w] = "zamiana" /\ przez[w] \in S THEN "przepadl" ELSE plik[w]]
    /\ nadawca' = [w \in W |-> IF nadawca[w] \in {"zamiana", "budzi"} /\ przez[w] \in S THEN "koniec" ELSE nadawca[w]]
    \* Przerwanie między przyjęciem części przez Skrzynkę a znacznikiem dostarczenia zostawia plik bez znacznika, a
    \* następna próba znajduje tę część po znaczniku wysyłki (_settle), więc żadna przyczyna nie trafia do slady.
    /\ UNCHANGED slady

\* Komputer gaśnie albo proces Centrum ginie: dysk i Skrzynka zostają.
Wylacz ==
    /\ wylaczenia < MaxWylaczen
    /\ \E q \in Q : zyje[q] /= "nie"
    /\ wylaczenia' = wylaczenia + 1
    /\ Zabij(Q)
    /\ krok' = "komputer gasnie w tym kroku"
    /\ UNCHANGED <<tmp, issues, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, sieci, zgubione, odmowy,
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
    /\ UNCHANGED <<plik, issues, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, biez,
                   nr, kom, bezZnacznika, passes, blokada, zamkniecia, nadawanie, awarie, slady>>

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
    /\ UNCHANGED <<tmp, issues, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, awarie>>

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
