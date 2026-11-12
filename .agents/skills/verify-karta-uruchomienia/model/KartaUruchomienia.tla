------------------------------ MODULE KartaUruchomienia ------------------------------
(* Jedna karta przeglądarki z Centrum rozliczeń: jak śledzi Uruchomienie procesu ze strumienia Uruchomień          *)
(* (RunsProvider w frontend/src/lib/runs.tsx, panel RunOrSetup w frontend/src/pages/runs/runs-page.tsx) i         *)
(* Aktualizację narzędzia (ToolUpdateProvider w frontend/src/lib/tool-update.tsx). Serwer jest tu tylko źródłem   *)
(* zdarzeń i odpowiedzi (RunHost w src/rozliczenia/centrum/runs.py, ToolUpdates w tool_updates.py); jego slot     *)
(* „jedno naraz” sprawdza verify-jedno-uruchomienie-naraz. Każda akcja to jeden niepodzielny krok z tabeli w      *)
(* SKILL.md skilla verify-karta-uruchomienia: jedno zadanie pętli zdarzeń przeglądarki (zdarzenie strumienia,      *)
(* kontynuacja po odpowiedzi HTTP, kliknięcie taty) albo jedna obsługa żądania na serwerze pod jego blokadą.      *)
EXTENDS Integers, Sequences, FiniteSets

CONSTANTS
    Czesc,             \* "uruchomienia" albo "aktualizacja": która część karty działa w tej konfiguracji
    MaxStartow,        \* prób startu Uruchomienia w sumie, z tej karty i z drugiej
    DrugaKarta,        \* druga karta (albo drugie okno) może uruchamiać i odpowiadać na Decyzję
    MozeDecyzja,       \* Uruchomienie może raz zapytać o Decyzję taty (Przygotowanie pliku zbiorczego, RUN)
    MozeZatrzymac,     \* Uruchomienie może skończyć się Zatrzymaniem (ending inny niż "finished")
    MaxRestartow,      \* ponownych startów Centrum (proces zabity i uruchomiony skrótem)
    MaxNieczytelnych,  \* widoków, których karta nie odczyta (zRunEvent.safeParse nie przechodzi)
    MaxZerwan,         \* zerwań strumienia (zdarzenie "error" EventSource) albo ukryć karty
    MaxWejsc,          \* wejść na stronę z przyciskiem aktualizacji, każde czyta stan (ToolUpdateStatus: read)
    MaxZaladowan,      \* przeładowań strony po aktualizacji (window.location.reload)
    MaxAktualizacji,   \* kliknięć „Zaktualizuj narzędzie”, które serwer przyjmie
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczonePrzyciskWraca, WybaczoneWynikNaKarcie, WybaczoneAktualizacjaNieWraca

Uruchomienia == 1..MaxStartow
Brak == 0
(* Widok Uruchomienia (unia RunView): idle z previous (ostatnie Uruchomienie sprzed startu Centrum), running,     *)
(* awaiting_decision, finished z result.ending. "null" to stan karty przed pierwszym odczytanym widokiem.        *)
Widok(s, r, p, k) == [stan |-> s, run |-> r, prev |-> p, konc |-> k]
Pusty == Widok("null", Brak, Brak, "-")
Bezczynny(p) == Widok("idle", Brak, p, "-")
StanyWidoku == {"null", "idle", "trwa", "decyzja", "wynik"}
Widoki == [stan : StanyWidoku, run : 0..MaxStartow, prev : 0..MaxStartow, konc : {"-", "wynik", "zatrzymane"}]

\* runs.tsx shownRun: id Uruchomienia z widoku, null dla braku widoku i idle.
ShownRun(v) == IF v.stan \in {"null", "idle"} THEN Brak ELSE v.run
\* runs.tsx awaitsDecision.
AwaitsDecision(v, r) == v.stan = "decyzja" /\ v.run = r
\* runs.tsx isActive.
IsActive(v) == v.stan \in {"trwa", "decyzja"}
Ended(v) == v.stan \in {"idle", "wynik"}

StanyAktualizacji == {"idle", "running", "updated", "failed"}

ZnaneZnaleziska == {"cudze-uruchomienie-przed-odpowiedzia", "restart-przed-odpowiedzia", "druga-karta",
                    "wybor-przed-wynikiem", "stary-odczyt", "stary-odczyt-petli"}

VARIABLES
    \* --- serwer: RunHost ---
    inst,            \* który start Centrum (health.instance); restart zaczyna nowy
    dziala,          \* Centrum odpowiada (FALSE tylko między zamknięciem a ponownym startem po aktualizacji)
    srvRun,          \* RunHost._run: id bieżącego Uruchomienia albo Brak po starcie Centrum
    srvStan,         \* "trwa" | "decyzja" | "wynik"
    srvKonc,         \* zakończenie wyniku: "wynik" | "zatrzymane" | "-"
    srvPytal,        \* Uruchomienie już zapytało o Decyzję
    prev,            \* previous widoku idle po starcie Centrum
    log,             \* RunHost._events: widoki z flagą, czy karta je odczyta (czyt)
    baza,            \* numer (sequence) pierwszego widoku w log; start przycina log do ostatniego
    proby, nieczyt, zerwan, restartow,
    \* --- karta: RunsProvider ---
    widok,           \* view i latest.current: ostatni odczytany widok
    nieczytelny,     \* unreadable
    rozlaczony,      \* disconnected
    draft,           \* draft !== null
    odlozony,        \* dismissed
    polaczenie,      \* "otwarte" | "brak": EventSource tej karty
    widziane,        \* seen w _event_stream tego połączenia: numer ostatniego wysłanego widoku
    startuje,        \* useAction starting: [faza, przed, id (Run.info.id, gdy serwer przyjmie), wynik (przyjęte Uruchomienie,
                     \* Brak przy odmowie i błędzie), inst (start Centrum, który obsłużył żądanie)]
    decyduje,        \* useAction deciding: [faza, run, wynik]
    \* --- karta: ToolUpdateProvider i serwer ToolUpdates ---
    aSrv,            \* stan Aktualizacji narzędzia na serwerze
    aNr,             \* która aktualizacja na serwerze (do rozpoznania starej odpowiedzi)
    upd,             \* update.state karty ("null" przed pierwszym odczytem)
    instRef,         \* instance.current: -1 to null
    startA,          \* useAction starting aktualizacji: [faza, odp]
    odczyty,         \* odczyty getToolUpdate z read() i z wejścia: [faza, odp, nr]
    petla,           \* odpytywanie co POLL_MS: [faza, odp, nr]
    wejsc, zaladowan,
    \* --- zmienne pomocnicze obietnic ---
    kto,             \* kto uruchomił Uruchomienie: "ta" | "inna" | "-"
    przedWynikiem,   \* Uruchomienia, przed których wynikiem w tej karcie tata wybrał nowe Uruchomienie (draft)
    odczytane,       \* Uruchomienia, których wynik (finished) ta karta odczytała
    wybralPo,        \* Uruchomienia, po których wyniku tata w tej karcie wybrał nowe Uruchomienie
    widzialTrwa,     \* karta pokazała trwającą aktualizację, która na serwerze jeszcze trwa
    slady,           \* przyczyny znanych znalezisk, które już się zdarzyły
    \* zdarzenia, które łamią obietnice (zmienne historii): {} albo {ślady w chwili zdarzenia}
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

(* ------------------------------------------------------------------------------------------------------------ *)
(* Widok panelu Uruchomień (runs-page.tsx RunsContent i RunOrSetup), czyli co tata widzi w tej karcie.           *)
Run(v) == IF v.stan = "idle" THEN v.prev ELSE v.run
SetupInstead(v) == Run(v) = Brak \/ (Ended(v) /\ (Run(v) = odlozony \/ draft))
Panel ==
    IF widok.stan = "null" THEN "szkielet"
    ELSE IF SetupInstead(widok) THEN "start"
    ELSE IF widok.stan = "idle" THEN "ostatnie"
    ELSE widok.stan

(* Serwer: bieżący widok RunHost i jego log. *)
SrvWidok == IF srvRun = Brak THEN Bezczynny(prev) ELSE Widok(srvStan, srvRun, Brak, srvKonc)
OstatniNr == baza + Len(log) - 1
Czytelnosci == IF nieczyt < MaxNieczytelnych THEN BOOLEAN ELSE {TRUE}
\* RunHost._publish_locked: nowy widok na końcu log; czy karta go odczyta, wybiera świat (stara wersja strony).
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

(* Zmienne historii obietnic: każda akcja kończy się krokiem Historia. *)
\* busy w ToolUpdateProvider: start wysłany albo update.state === "running".
Busy == startA.faza # "nie" \/ upd = "running"
AktTrwa == aSrv = "running" \/ ~dziala
Odp(s) == IF dziala THEN s ELSE "blad"

\* Karta pokazuje kartę startu zamiast wyniku Uruchomienia, po którego wyniku tata w tej karcie nie wybrał nowego
\* Uruchomienia. Chwilę między startem z tej karty a odpowiedzią (setDraft(null) jeszcze nie przyszło) pomijamy.
Zasloniety == /\ widok.stan = "wynik" /\ Panel = "start" /\ widok.run \notin wybralPo
              /\ startuje.faza \notin {"wyslany", "odpowiedz"}
PrzyczynyZasloniecia(r) == (IF kto[r] = "inna" THEN {"druga-karta"} ELSE {})
                           \cup (IF r \in przedWynikiem THEN {"wybor-przed-wynikiem"} ELSE {})
\* Przycisk „Zaktualizuj narzędzie” wraca (busy = false), choć aktualizacja, którą ta strona pokazała jako
\* trwającą, na serwerze jeszcze trwa.
Wrocil == AktTrwa /\ widzialTrwa /\ ~Busy

Historia ==
    /\ zaslonietyWynik' = IF zaslonietyWynik = {} /\ Zasloniety'
                          THEN {slady' \cup PrzyczynyZasloniecia(widok'.run)} ELSE zaslonietyWynik
    /\ wrocilPrzycisk' = IF wrocilPrzycisk = {} /\ Wrocil' THEN {slady'} ELSE wrocilPrzycisk


(* ============================ Uruchomienie: kliknięcia taty w tej karcie ============================ *)

\* useAction.run starting: przycisk startu (karta startu, IntermaxCard, „Uruchom ponownie”, podgląd z Tablicy
\* okresów, „Wpisz raporty z maili”) jest w tej karcie do kliknięcia, gdy widok nie pokazuje trwającego
\* Uruchomienia i start nie trwa (inFlight); `before = shownRun(latest.current)`, potem fetch startRun.
KlikStart ==
    /\ Uruchom /\ ~IsActive(widok) /\ startuje.faza = "nie" /\ proby < MaxStartow
    /\ proby' = proby + 1
    /\ startuje' = [faza |-> "wyslany", przed |-> ShownRun(widok), id |-> proby + 1, wynik |-> Brak, inst |-> inst]
    /\ UNCHANGED <<inst, dziala, srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, nieczyt, zerwan, restartow>>
    /\ UNCHANGED <<widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, decyduje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

\* DecisionDialog: przyciski Decyzji są w panelu z widokiem awaiting_decision, wyłączone, gdy deciding jest tym
\* Uruchomieniem; useAction.run deciding, potem fetch decideRun.
KlikDecyzja ==
    /\ Uruchom /\ Panel = "decyzja" /\ decyduje.faza = "nie"
    /\ decyduje' = [faza |-> "wyslany", run |-> widok.run, wynik |-> "-"]
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, startuje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

\* NewRunButton na karcie wyniku (RunCard przy finished, PastRunCard przy idle z previous): newRun = setDismissed.
NoweUruchomienie ==
    /\ Uruchom /\ Panel \in {"wynik", "ostatnie"}
    /\ odlozony' = Run(widok)
    /\ wybralPo' = wybralPo \cup {Run(widok)}
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, draft, polaczenie, widziane, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, kto, odczytane, przedWynikiem, widzialTrwa, slady>>
    /\ Historia

\* Wybór nowego Uruchomienia ustawia draft: kafelek procesu albo okres na karcie startu (RunSetupCard
\* onValueChange), krok w Tablicy okresów (DraftButton), „Gotowe, rozlicz pracowników” (ReadyForSettlement) i
\* „Uruchom ponownie” Wyceny w efenix (rerun z pricing). Poza kartą startu tata może to zrobić w każdej chwili.
\* Zmienne pomocnicze: wybór po wyniku Uruchomienia, który ta karta pokazuje, i wybór przed wynikiem Uruchomienia, które
\* serwer już uruchomił, a którego wyniku ta karta jeszcze nie odczytała.
WybierzNowe ==
    /\ draft' = TRUE
    /\ wybralPo' = IF widok.stan = "wynik" THEN wybralPo \cup {widok.run} ELSE wybralPo
    /\ przedWynikiem' = przedWynikiem \cup {r \in Uruchomienia : kto[r] # "-" /\ r \notin odczytane}
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, odlozony, polaczenie, widziane, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, kto, odczytane, widzialTrwa, slady>>
    /\ Historia
WyborNaKarcieStartu == Uruchom /\ Panel = "start" /\ WybierzNowe
WyborSpozaKarty == Uruchom /\ WybierzNowe

(* ============================ Uruchomienie: kontynuacje po odpowiedzi HTTP ============================ *)

\* starting po `await startRun(...)`: odmowa albo błąd sieci kończy akcję (powiadomienie, draft zostaje); przyjęty
\* start: setDraft(null), a gdy latest.current nie pokazuje przyjętego Uruchomienia, streamShows czeka na widok
\* z innym Uruchomieniem niż `before` albo idle. Ślady: odpowiedź po tym, jak strumień pokazał już inne Uruchomienie
\* niż `before` i przyjęte, albo po ponownym starcie Centrum.
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

\* deciding po `await decideRun(...)`: błąd kończy akcję; przyjęta Decyzja czeka, aż strumień przestanie
\* pokazywać, że to Uruchomienie czeka na Decyzję, chyba że latest.current już tego nie pokazuje.
OdpowiedzDecyzji ==
    /\ Uruchom /\ decyduje.faza = "odpowiedz"
    /\ decyduje' = IF decyduje.wynik = "blad" \/ ~AwaitsDecision(widok, decyduje.run)
                   THEN NieDecyduje ELSE [decyduje EXCEPT !.faza = "czeka"]
    /\ UNCHANGED <<serwer, widok, nieczytelny, rozlaczony, draft, odlozony, polaczenie, widziane, startuje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

(* ============================ Uruchomienie: strumień tej karty ============================ *)

\* watchRunEvents "message": następny widok po `seen` (events_after; po przycięciu pierwszy, który został).
\* Odczytany: announce, latest.current i view, unreadable = false i rozwiązanie każdego awaited, którego shows
\* przechodzi. Nieczytelny: onUnreadable ustawia tylko unreadable.
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

\* EventSource "error" (Centrum nie odpowiada, sieć) albo ukrycie karty (followVisibility zamyka strumień).
Zerwij ==
    /\ Uruchom /\ polaczenie = "otwarte" /\ zerwan < MaxZerwan
    /\ zerwan' = zerwan + 1 /\ polaczenie' = "brak" /\ rozlaczony' = TRUE
    /\ UNCHANGED <<inst, dziala, srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, proby, nieczyt, restartow>>
    /\ UNCHANGED <<widok, nieczytelny, draft, odlozony, widziane, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

\* EventSource łączy się ponownie sam (retry) albo karta wraca na wierzch: "open", a _event_stream wysyła najpierw
\* bieżący widok (current), potem każdy nowszy.
Polacz ==
    /\ Uruchom /\ dziala /\ polaczenie = "brak"
    /\ polaczenie' = "otwarte" /\ rozlaczony' = FALSE /\ widziane' = OstatniNr - 1
    /\ UNCHANGED <<serwer, widok, nieczytelny, draft, odlozony, startuje, decyduje>>
    /\ UNCHANGED <<aktualizacja, pomocnicze>>
    /\ Historia

(* ============================ Uruchomienie: serwer ============================ *)

\* POST /api/runs: RunHost.start pod blokadą. Odmowa, gdy Uruchomienie trwa; inaczej nowy Run, przycięcie
\* _events do ostatniego widoku i widok startu opublikowany przed odpowiedzią.
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

\* POST /api/runs/{id}/decision: RunHost.decide pod blokadą; Run.answer i widok running przed odpowiedzią.
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

\* Druga karta uruchamia (RunHost.start z innego żądania); jej start przy trwającym Uruchomieniu to odmowa bez zmian.
InnaKartaStart ==
    /\ Uruchom /\ DrugaKarta /\ dziala /\ ~Zajety /\ proby < MaxStartow
    /\ proby' = proby + 1 /\ Przyjmij(proby + 1, "inna")
    /\ UNCHANGED <<inst, dziala, prev, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, odczytane, przedWynikiem, wybralPo, widzialTrwa, slady>>
    /\ Historia

\* Druga karta odpowiada na Decyzję (RunHost.decide).
InnaKartaDecyzja ==
    /\ Uruchom /\ DrugaKarta /\ dziala /\ srvRun # Brak /\ srvStan = "decyzja"
    /\ Odpowiedz(srvRun)
    /\ UNCHANGED <<inst, dziala, srvRun, srvKonc, srvPytal, prev, baza, proby, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

\* Run.confirm: Uruchomienie pyta o Decyzję taty raz (collective_preparation, niepełny okres) i czeka.
PytanieODecyzje ==
    /\ Uruchom /\ MozeDecyzja /\ dziala /\ srvRun # Brak /\ srvStan = "trwa" /\ ~srvPytal
    /\ srvStan' = "decyzja" /\ srvPytal' = TRUE
    /\ \E c \in Czytelnosci : Publikuj(Widok("decyzja", srvRun, Brak, "-"), c)
    /\ UNCHANGED <<inst, dziala, srvRun, srvKonc, prev, baza, proby, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

\* RunHost.end: wynik (finished) i koniec Uruchomienia pod jedną blokadą.
KoniecUruchomienia ==
    /\ Uruchom /\ dziala /\ srvRun # Brak /\ srvStan = "trwa"
    /\ \E k \in (IF MozeZatrzymac THEN {"wynik", "zatrzymane"} ELSE {"wynik"}), c \in Czytelnosci :
           /\ srvStan' = "wynik" /\ srvKonc' = k
           /\ Publikuj(Widok("wynik", srvRun, Brak, k), c)
    /\ UNCHANGED <<inst, dziala, srvRun, srvPytal, prev, baza, proby, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

\* Centrum zabite i uruchomione ponownie: nowy RunHost z idle (previous: ostatnie Uruchomienie z Logów), strumień
\* tej karty dostaje "error", a żądanie, którego serwer nie obsłużył, kończy się błędem sieci.
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

(* ============================ Aktualizacja narzędzia ============================ *)

\* show(result): stan od serwera zastępuje to, co karta pokazywała.
Pokaz(s) ==
    /\ upd' = s
    /\ widzialTrwa' = (widzialTrwa \/ s = "running")
\* Ślad przyczyny: odpowiedź s zapytania, które serwer obsłużył przed startem trwającej aktualizacji (nr < aNr),
\* zastępuje jej stan. Odczyt przy wejściu (read) i pętla odpytywania mają osobne przyczyny, bo każde naprawia się
\* osobno.
Slad(s, nr, przyczyna) ==
    slady' = IF nr < aNr /\ AktTrwa /\ s # "running" THEN slady \cup {przyczyna} ELSE slady

\* ToolUpdateButton: useAction starting, setClicked(true), potem getHealth: instance.current = health.instance.
\* Przycisk ma tylko disabled={busy}, więc działa też przed pierwszym odczytem (update === null).
KlikAktualizuj ==
    /\ Aktualizuj /\ ~Busy /\ aNr < MaxAktualizacji
    /\ startA' = [faza |-> "zdrowie", odp |-> "-"]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, odczyty, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

\* .then(health => { instance.current = health.instance; return startToolUpdate() }); getHealth bez odpowiedzi
\* kończy akcję powiadomieniem „Nie zaktualizowano narzędzia”.
ZdrowieStartu ==
    /\ Aktualizuj /\ startA.faza = "zdrowie"
    /\ IF dziala THEN /\ instRef' = inst /\ startA' = [faza |-> "wyslany", odp |-> "-"]
                 ELSE /\ startA' = [faza |-> "nie", odp |-> "-"] /\ UNCHANGED instRef
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, odczyty, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

\* POST /api/tool-update: ToolUpdates.start zajmuje begin_update i odpowiada pierwszym krokiem (running); trwająca
\* aktualizacja to odmowa.
ObslugaStartuAkt ==
    /\ Aktualizuj /\ dziala /\ startA.faza = "wyslany"
    /\ IF aSrv = "running"
       THEN /\ startA' = [faza |-> "odpowiedz", odp |-> "odmowa"] /\ UNCHANGED <<aSrv, aNr>>
       ELSE /\ aSrv' = "running" /\ aNr' = aNr + 1 /\ startA' = [faza |-> "odpowiedz", odp |-> "running"]
    /\ UNCHANGED <<serwer, karta, upd, instRef, odczyty, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

\* .then(show) po starcie; odmowa albo błąd sieci to powiadomienie, a stan karty zostaje.
KoniecStartuAkt ==
    /\ Aktualizuj /\ startA.faza = "odpowiedz"
    /\ startA' = [faza |-> "nie", odp |-> "-"]
    /\ IF startA.odp = "running" THEN Pokaz("running") ELSE UNCHANGED <<upd, widzialTrwa>>
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, instRef, odczyty, petla, wejsc, zaladowan, kto, odczytane, przedWynikiem, wybralPo, slady>>
    /\ Historia

\* Wejście na stronę z przyciskiem: efekt ToolUpdateProvider przy załadowaniu strony i ToolUpdateStatus
\* (React.useEffect(read)) wysyłają getToolUpdate bez numeru zapytania.
Wejscie ==
    /\ Aktualizuj /\ wejsc < MaxWejsc
    /\ wejsc' = wejsc + 1
    /\ odczyty' = [odczyty EXCEPT ![wejsc + 1] = [faza |-> "wyslany", odp |-> "-", nr |-> 0]]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, startA, petla, zaladowan, pomocnicze>>
    /\ Historia

\* GET /api/tool-update: serwer podaje bieżący stan (ToolUpdates.state); Centrum zamknięte nie odpowiada.
ObslugaOdczytu(i) ==
    /\ Aktualizuj /\ odczyty[i].faza = "wyslany"
    /\ odczyty' = [odczyty EXCEPT ![i] = [faza |-> "odpowiedz", odp |-> Odp(aSrv), nr |-> aNr]]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, startA, petla, wejsc, zaladowan, pomocnicze>>
    /\ Historia

\* read(): getToolUpdate().then(show, failRead); odpowiedzi przychodzą w dowolnej kolejności.
OdbierzOdczyt(i) ==
    /\ Aktualizuj /\ odczyty[i].faza = "odpowiedz"
    /\ odczyty' = [odczyty EXCEPT ![i].faza = "zrobiony"]
    /\ IF odczyty[i].odp = "blad" THEN UNCHANGED <<upd, widzialTrwa, slady>>
       ELSE Pokaz(odczyty[i].odp) /\ Slad(odczyty[i].odp, odczyty[i].nr, "stary-odczyt")
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, instRef, startA, petla, wejsc, zaladowan, kto, odczytane, przedWynikiem, wybralPo>>
    /\ Historia

\* Efekt przy update.state === "running": po POLL_MS getHealth (instance.current ??= health.instance). Timer
\* czyści cleanup efektu, ale wysłanego łańcucha nikt nie przerywa.
Tik ==
    /\ Aktualizuj /\ upd = "running" /\ petla.faza = "nie"
    /\ petla' = [faza |-> "zdrowie", odp |-> "-", nr |-> 0]
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, upd, instRef, startA, odczyty, wejsc, zaladowan, pomocnicze>>
    /\ Historia

\* Strona po przeładowaniu: ToolUpdateProvider od nowa, bez odpowiedzi poprzedniej strony; odczyt przy wejściu.
Zaladuj ==
    /\ zaladowan' = zaladowan + 1
    /\ upd' = "null" /\ instRef' = -1 /\ startA' = [faza |-> "nie", odp |-> "-"] /\ petla' = Nic
    /\ odczyty' = [i \in 1..MaxWejsc |-> IF i = 1 THEN [faza |-> "wyslany", odp |-> "-", nr |-> 0] ELSE Nic]
    /\ wejsc' = 1 /\ widzialTrwa' = FALSE

\* getHealth().then: inny instance to przeładowanie strony (sessionStorage), ten sam to getToolUpdate; brak
\* odpowiedzi (.catch) to show({state: "running", step: "restarting"}).
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

\* getToolUpdate().then(show) w pętli, bez numeru zapytania jak read(); błąd przechodzi do .catch: show(running,
\* restarting). Łańcuch wysłany w trakcie poprzedniej aktualizacji odpowiada też po starcie następnej: wynik
\* poprzedniej zastępuje wtedy running.
OdbierzPetli ==
    /\ Aktualizuj /\ petla.faza = "odpowiedz"
    /\ petla' = Nic
    /\ LET s == IF petla.odp = "blad" THEN "running" ELSE petla.odp
       IN Pokaz(s) /\ Slad(s, petla.nr, "stary-odczyt-petli")
    /\ UNCHANGED <<serwer, karta, aSrv, aNr, instRef, startA, odczyty, wejsc, zaladowan, kto, odczytane, przedWynikiem, wybralPo>>
    /\ Historia

\* ToolUpdates._update: porażka kroku przed ponownym startem (fetch, pip) kończy aktualizację w tym samym Centrum.
AktPorazka ==
    /\ Aktualizuj /\ dziala /\ aSrv = "running"
    /\ aSrv' = "failed" /\ widzialTrwa' = FALSE
    /\ UNCHANGED <<serwer, karta, aNr, upd, instRef, startA, odczyty, petla, wejsc, zaladowan>>
    /\ UNCHANGED <<kto, odczytane, przedWynikiem, wybralPo, slady>>
    /\ Historia

\* ToolUpdates._restart: Centrum zamyka się po udanej aktualizacji, opiekun ponownego startu uruchamia nowe.
AktZamkniecie ==
    /\ Aktualizuj /\ dziala /\ aSrv = "running"
    /\ dziala' = FALSE
    /\ UNCHANGED <<inst, srvRun, srvStan, srvKonc, srvPytal, prev, log, baza, proby, nieczyt, zerwan, restartow>>
    /\ UNCHANGED <<karta, aktualizacja, pomocnicze>>
    /\ Historia

\* Nowe Centrum (inny instance) czyta wynik aktualizacji raz przy starcie (_after_restart): updated albo failed.
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

(* ------------------------------------------------------------------------------------------------------------ *)
(* Obietnice nad stanem po każdym kroku: zmienne historii zapisują pierwsze zdarzenie, które łamie obietnicę,     *)
(* ze śladami znanych znalezisk z tej chwili.                                                                    *)


\* Strumień czyta i odpowiada sam, serwer obsługuje żądania i kończy Uruchomienie, karta łączy się ponownie.
Sprawiedliwosc ==
    /\ WF_vars(Odbierz) /\ WF_vars(Polacz) /\ WF_vars(OdpowiedzStartu) /\ WF_vars(OdpowiedzDecyzji)
    /\ WF_vars(ObslugaStartu) /\ WF_vars(ObslugaDecyzji) /\ WF_vars(KoniecUruchomienia)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

(* Obietnice. *)
\* Start i Decyzja wysłane z tej karty kończą się (przyciski wracają), gdy ostatni widok serwera da się odczytać:
\* strumień wrócił do czytelnego albo Centrum wystartowało ponownie z czytelnym idle.
CzytelnyWidok == log[Len(log)].czyt
PrzyciskWraca ==
    <>[]CzytelnyWidok => /\ (startuje.faza # "nie" ~> startuje.faza = "nie")
                         /\ (decyduje.faza # "nie" ~> decyduje.faza = "nie")
\* Wynik zakończonego Uruchomienia (finished) zostaje na karcie, dopóki tata w tej karcie po nim nie wybierze
\* nowego Uruchomienia.
WynikNaKarcie == zaslonietyWynik = {}
\* Karta Aktualizacji narzędzia nie wraca do „Zaktualizuj narzędzie” w trakcie aktualizacji, którą pokazała.
AktualizacjaNieWraca == wrocilPrzycisk = {}

\* Wariant obietnicy, który pomija jej zdarzenie, gdy w chwili zdarzenia była już przyczyna wybaczonego znaleziska.
Wybaczone(zdarzenie, wybaczone) == \E s \in zdarzenie : s \cap wybaczone # {}
PrzyciskWracaPozaZnanymi == PrzyciskWraca \/ <>(slady \cap WybaczonePrzyciskWraca # {})
WynikNaKarciePozaZnanymi == WynikNaKarcie \/ Wybaczone(zaslonietyWynik, WybaczoneWynikNaKarcie)
AktualizacjaNieWracaPozaZnanymi == AktualizacjaNieWraca \/ Wybaczone(wrocilPrzycisk, WybaczoneAktualizacjaNieWraca)
==========================================================================================================
