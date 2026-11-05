------------------------------ MODULE UrwaneUruchomienie ------------------------------
(* Ślad Wyceny w efenix, którą przerwało zgaśnięcie Centrum, przez kolejne starty Centrum: dziennik Wyceny w efenix    *)
(* (src/rozliczenia/centrum/pricing_journal.py: PricingJournal, InterruptedPricings.close i send), Logi Urwanego       *)
(* Uruchomienia (src/rozliczenia/centrum/run_logs.py: RunLogs.interrupted, guard, close, send) i ich droga do Kolejki  *)
(* wysyłki (Outbox.post), obok Logów i wiersza Historii Wyceny, która doszła do wyniku, i wersja końcowa komentarza     *)
(* Uruchomienia każdej Wyceny z dziennikiem (#846: Logi, Logi Urwanego Uruchomienia albo wynik bez Logów). Każda    *)
(* akcja to jeden niepodzielny krok kodu z tabeli w SKILL.md skilla verify-urwane-uruchomienie. Kolejka kończy się tu  *)
(* na Outbox.post: co dalej z plikiem kolejki, sprawdza model skilla verify-kolejka-skrzynki.                         *)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Wyceny,              \* Uruchomień Wyceny w efenix, jedno po drugim (Centrum prowadzi jedno naraz)
    LiczbaZlecen,        \* zleceń w każdej Wycenie, po kolei
    MaxZgasniec,         \* zgaśnięć Centrum: brak prądu, zabity proces, zamknięte okno konsoli
    MaxAwariiWpisu,      \* PricingJournal._write: OSError (wpis przepada, Wycena biegnie dalej)
    MaxAwariiOdczytu,    \* InterruptedPricings.close: OSError odczytu dziennika albo pliku Logów (dziennik zostaje)
    MaxAwariiHistorii,   \* RunCards._row: OSError odczytu Historii (wiersza „nie ma”)
    MaxAwariiMetryk,     \* run_process: MetricsStore.append rzuca OSError, UnicodeError albo ValueError; run_process go
                         \* łapie (metrics_saved = False) i wraca z wynikiem bez wiersza Historii
    MaxAwariiLogow,     \* RunLogs._write (replace_atomically): OSError, pliku Logów nie ma albo zostaje poprzedni
    MaxAwariiKolejki,    \* Outbox.post: False (pliku kolejki nie dało się zapisać)
    MaxAwariiUsuniecia,  \* InterruptedPricings._remove: OSError z unlink (dziennik zostaje)
    TekstDoMaski,        \* ślad zleceń w dzienniku ma tekst, który strażnik reguły danych maskuje (telefon, ulica)
    StareLogi,           \* przed pierwszym startem: Wycena 1 urwana, a jej Logi Urwanego Uruchomienia zapisała, ale nie
                         \* wysłała praca Centrum sprzed strażnika (#851), więc bez maski
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneDziennikPoKolejce, WybaczoneBezUrwanychPoWyniku, WybaczoneTeSameZnaki, WybaczonePrzezStraznika,
    WybaczoneNicPrzedWznowieniem, WybaczoneZaczeteWLogach, WybaczoneWersjaKoncowa

Biegi == 1..Wyceny
Zlecenia == 1..LiczbaZlecen
Przyczyny == {"wiersz-pozniejszej-wyceny", "historia-nieczytelna", "historia-niezapisana", "zapis-logow-nieudany",
              "wpis-nieudany"}

\* Treść Logów Urwanego Uruchomienia: zlecenia skończone przed zgaśnięciem (efenix_orders), zlecenie zaczęte bez wyniku
\* (interruption.row, 0: zgasło między zleceniami) i to, czy tekst przeszedł przez strażnika reguły danych.
Tresci == [skonczone : SUBSET Zlecenia, zaczete : 0..LiczbaZlecen, tekst : {"surowe", "strzezone"}]
Pusta == [skonczone |-> {}, zaczete |-> 0, tekst |-> "strzezone"]
\* Plik Logów Uruchomienia (logs/uruchomienia/<plik>.json): brak, Logi z wynikiem (ending inny niż interrupted) albo
\* Logi Urwanego Uruchomienia z treścią.
PlikiLogow == [rodzaj : {"brak", "wynik", "urwane"}, tresc : Tresci]
BrakLogow == [rodzaj |-> "brak", tresc |-> Pusta]
Wpisy == [rodzaj : {"zaczete", "skonczone"}, z : Zlecenia]
\* Wersja końcowa komentarza Uruchomienia w kolejce: Logi z wynikiem, Logi Urwanego Uruchomienia albo wynik bez Logów
\* (run_logs.ResultWithoutLogs: wynik z wiersza Historii, bez pliku Logów i bez pliku w Archiwum).
Rodzaje == {"wynik", "urwane", "bezLogow"}
\* Co close weźmie z dziennika: Logi (z pliku albo Urwanego Uruchomienia z dziennika) z treścią po strażniku.
Rekordy == [rodzaj : {"wynik", "urwane"}, tresc : Tresci]
BrakRekordu == [rodzaj |-> "urwane", tresc |-> Pusta]
\* InterruptedPricings._pending: wersja końcowa, jej dziennik, czy jej pliku Logów nie udało się zapisać, i przyczyna
\* decyzji (wiersz późniejszej Wyceny), którą niesie usunięcie dziennika po przyjęciu.
Oczekujace == [bieg : Biegi, rodzaj : Rodzaje, tresc : Tresci, niezapisany : BOOLEAN, powod : SUBSET Przyczyny]

VARIABLES
    \* Dysk taty i Kolejka wysyłki: zostają po zgaśnięciu Centrum.
    dziennik,        \* dziennik Wyceny r: "brak" | "bezStartu" (urwana pierwsza linia) | "jest"
    wpisy,           \* wpisy dziennika r po pierwszej linii, po kolei (bez urwanych)
    logi,            \* plik Logów Uruchomienia r
    historia,        \* wiersz Historii (rekord metryk) Wyceny r
    efenix,          \* zlecenia, które Wycena r zmieniła już w efenix
    kolejka,         \* wersje końcowe, które Outbox.post przyjął: [bieg, rodzaj, tresc]
    \* Pamięć jednej pracy Centrum: znika ze zgaśnięciem i zamknięciem.
    centrum,         \* "stoi" | "zamyka" (create_app: close, potem lifespan) | "wysyla" (pierwsze zapytanie: send) |
                     \* "dziala"
    wznowiona,       \* lifespan tej pracy Centrum wywołał już Outbox.resume
    kursor,          \* który dziennik z sorted(glob) czyta close
    krokZamykania,   \* "czytaj" | "zapisz" (plik Logów) | "usun" (dziennik)
    rekord,          \* Logi, które close zapisze w pliku: z pliku albo Urwanego Uruchomienia z dziennika
    powod,           \* przyczyna, dla której close usuwa dziennik (wiersz późniejszej Wyceny)
    oczekujace,      \* InterruptedPricings._pending: Logi do wysłania i ich dzienniki
    doWyslania,      \* to, co send wziął z _pending
    krokWysylki,     \* "post" | "usun" (dziennik po przyjęciu)
    bieg,            \* Wycena, która biegnie w tej pracy Centrum (0: żadna)
    faza,            \* gdzie jest Wycena: "-" | "start" | "zaczete" | "efenix" | "skonczone" | "historia" | "logi" |
                     \* "post" | "usun" (dziennik po Logach przyjętych przez kolejkę)
    zlecenie,        \* bieżące zlecenie Wyceny
    naglowekCzeka,   \* PricingJournal._header: pierwszej linii nie ma jeszcze na dysku (idzie z następnym zapisem)
    nastepny,        \* następna Wycena, którą tata może uruchomić
    zgasniecia, awarieWpisu, awarieOdczytu, awarieHistorii, awarieMetryk, awarieLogow, awarieKolejki, awarieUsuniecia,
    \* Zmienne pomocnicze: nie mają odpowiednika w kodzie i służą tylko obietnicom.
    zapisanyStart,   \* dziennik r miał kiedyś pierwszą linię
    wynik,           \* Wycena r doszła do wyniku: run_process wrócił z wynikiem, z wierszem Historii albo bez niego
    przepadle,       \* zlecenia Wyceny r, których własny wpis dziennika się nie zapisał (OSError)
    \* Zdarzenia, które łamią obietnice: zbiór przyczyn w chwili każdego zdarzenia.
    zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezKonca

dysk == <<dziennik, wpisy, logi, historia, efenix, kolejka>>
pamiec == <<centrum, wznowiona, kursor, krokZamykania, rekord, powod, oczekujace, doWyslania, krokWysylki, bieg, faza,
            zlecenie, naglowekCzeka>>
liczniki == <<nastepny, zgasniecia, awarieWpisu, awarieOdczytu, awarieHistorii, awarieMetryk, awarieLogow,
              awarieKolejki, awarieUsuniecia>>
duchy == <<zapisanyStart, wynik, przepadle>>
zdarzenia == <<zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezKonca>>
vars == <<dysk, pamiec, liczniki, duchy, zdarzenia>>

Zdarz(stare, warunek, przyczyny) == IF warunek THEN stare \cup {przyczyny} ELSE stare

TypeOK ==
    /\ dziennik \in [Biegi -> {"brak", "bezStartu", "jest"}]
    /\ \A r \in Biegi : wpisy[r] \in Seq(Wpisy) /\ Len(wpisy[r]) <= 2 * LiczbaZlecen
    /\ logi \in [Biegi -> PlikiLogow]
    /\ historia \in [Biegi -> BOOLEAN]
    /\ efenix \in [Biegi -> SUBSET Zlecenia]
    /\ kolejka \subseteq [bieg : Biegi, rodzaj : Rodzaje, tresc : Tresci]
    /\ centrum \in {"stoi", "zamyka", "wysyla", "dziala"}
    /\ wznowiona \in BOOLEAN
    /\ kursor \in 1..(Wyceny + 1)
    /\ krokZamykania \in {"czytaj", "zapisz", "usun"}
    /\ rekord \in Rekordy
    /\ powod \subseteq Przyczyny
    /\ oczekujace \in Seq(Oczekujace) /\ doWyslania \in Seq(Oczekujace)
    /\ krokWysylki \in {"post", "usun"}
    /\ bieg \in 0..Wyceny
    /\ faza \in {"-", "start", "zaczete", "efenix", "skonczone", "historia", "logi", "post", "usun"}
    /\ zlecenie \in Zlecenia
    /\ naglowekCzeka \in BOOLEAN
    /\ nastepny \in 1..(Wyceny + 1)
    /\ zapisanyStart \in [Biegi -> BOOLEAN] /\ wynik \in [Biegi -> BOOLEAN] /\ przepadle \in [Biegi -> SUBSET Zlecenia]
    /\ \A e \in {zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezKonca} :
           e \subseteq SUBSET Przyczyny

\* Przed pierwszym startem nic nie ma; ze StareLogi Wycena 1 jest już urwana, jej dziennik ma zlecenie 1 skończone, a
\* plik jej Logów Urwanego Uruchomienia zapisała praca Centrum sprzed strażnika i zgasła przed ich wysłaniem.
Init ==
    /\ dziennik = [r \in Biegi |-> IF StareLogi /\ r = 1 THEN "jest" ELSE "brak"]
    /\ wpisy = [r \in Biegi |-> IF StareLogi /\ r = 1
                                THEN <<[rodzaj |-> "zaczete", z |-> 1], [rodzaj |-> "skonczone", z |-> 1]>>
                                ELSE <<>>]
    /\ logi = [r \in Biegi |-> IF StareLogi /\ r = 1
                               THEN [rodzaj |-> "urwane", tresc |-> [skonczone |-> {1}, zaczete |-> 0, tekst |-> "surowe"]]
                               ELSE BrakLogow]
    /\ historia = [r \in Biegi |-> FALSE]
    /\ efenix = [r \in Biegi |-> IF StareLogi /\ r = 1 THEN {1} ELSE {}]
    /\ kolejka = {}
    /\ centrum = "stoi" /\ wznowiona = FALSE /\ kursor = 1 /\ krokZamykania = "czytaj" /\ rekord = BrakRekordu
    /\ powod = {}
    /\ oczekujace = <<>> /\ doWyslania = <<>> /\ krokWysylki = "post"
    /\ bieg = 0 /\ faza = "-" /\ zlecenie = 1 /\ naglowekCzeka = FALSE
    /\ nastepny = IF StareLogi THEN 2 ELSE 1
    /\ zgasniecia = 0 /\ awarieWpisu = 0 /\ awarieOdczytu = 0 /\ awarieHistorii = 0 /\ awarieMetryk = 0
    /\ awarieLogow = 0 /\ awarieKolejki = 0 /\ awarieUsuniecia = 0
    /\ zapisanyStart = [r \in Biegi |-> StareLogi /\ r = 1]
    /\ wynik = [r \in Biegi |-> FALSE]
    /\ przepadle = [r \in Biegi |-> {}]
    /\ zgubiony = {} /\ poWyniku = {} /\ inneZnaki = {} /\ bezStrazy = {} /\ przedWznowieniem = {} /\ bezZlecenia = {}
    /\ bezKonca = {}

\* Wycena r doszła do wyniku: run_process wrócił z wynikiem. Wiersz Historii (rekord metryk) mógł się nie zapisać.
ZWynikiem(r) == wynik[r]
\* Kolejka przyjęła Logi Urwanego Uruchomienia r (Outbox.post zwrócił True).
Przyjete(r) == \E p \in kolejka : p.bieg = r /\ p.rodzaj = "urwane"
\* Kolejka przyjęła wersję końcową komentarza Uruchomienia r, więc ten komentarz w Skrzynce nie zostanie postępem.
Koncowa(r) == \E p \in kolejka : p.bieg = r
\* RunCards.recorded -> _row: najwcześniejszy wiersz Historii procesu ze startem od startu r, a Wyceny startują po kolei.
Zapisana(r) == \E r2 \in Biegi : r2 >= r /\ historia[r2]
\* Zlecenia, które Wycena r zmieniła w efenix, a których Logi t nie mają ani jako skończonych, ani jako zaczętego bez
\* wyniku; Logi pokrywają Wycenę, gdy takich nie ma.
Niepokryte(r, t) == {z \in efenix[r] : z \notin t.skonczone /\ z # t.zaczete}
Pokrywa(r, t) == Niepokryte(r, t) = {}
\* Znalezisko „wpis-nieudany” dotyczy tylko zleceń, których własny wpis przepadł: brak w Logach zlecenia, którego
\* wpisy się zapisały, to nowe naruszenie.
PoWpisach(r, brakujace) == IF brakujace \subseteq przepadle[r] THEN {"wpis-nieudany"} ELSE {}

(* pricing_journal._read: zlecenia z wpisów „zlecenie skończone”, a zlecenie zaczęte bez wyniku z ostatniego wpisu,  *)
(* gdy to „zaczynam zlecenie”; RunLogs.interrupted -> RunLog.interrupted. Tekst ze śladu zleceń jest surowy, dopóki   *)
(* nie przejdzie przez strażnika.                                                                                   *)
ZDziennika(r) ==
    LET w == wpisy[r]
        skonczone == {w[i].z : i \in {i \in 1..Len(w) : w[i].rodzaj = "skonczone"}}
    IN [skonczone |-> skonczone,
        zaczete |-> IF Len(w) > 0 /\ w[Len(w)].rodzaj = "zaczete" THEN w[Len(w)].z ELSE 0,
        tekst |-> IF TekstDoMaski /\ skonczone # {} THEN "surowe" ELSE "strzezone"]
\* RunLogs.guard -> guarded: strażnik reguły danych pracy Centrum.
Straz(t) == [t EXCEPT !.tekst = "strzezone"]

\* Zdarzenia przy każdym Outbox.post wersji końcowej h z dziennika: plik Logów tego samego rodzaju z innymi znakami,
\* tekst bez strażnika, wysyłka przed Outbox.resume, a w Logach Urwanego Uruchomienia zlecenie zmienione w efenix bez
\* śladu.
PoPoscie(h) ==
    /\ inneZnaki' = Zdarz(inneZnaki, h.rodzaj # "bezLogow" /\ logi[h.bieg].rodzaj = h.rodzaj /\ logi[h.bieg].tresc # h.tresc,
                          IF h.niezapisany THEN {"zapis-logow-nieudany"} ELSE {})
    /\ bezStrazy' = Zdarz(bezStrazy, h.tresc.tekst = "surowe", {})
    /\ przedWznowieniem' = Zdarz(przedWznowieniem, ~wznowiona, {})
    /\ bezZlecenia' = Zdarz(bezZlecenia, h.rodzaj = "urwane" /\ ~Pokrywa(h.bieg, h.tresc),
                            PoWpisach(h.bieg, Niepokryte(h.bieg, h.tresc)))

(* pricing_journal._remove: path.unlink(); FileNotFoundError nic nie robi, OSError zostawia dziennik (linia dziennika *)
(* Centrum). Dziennik Urwanego Uruchomienia (pierwsza linia, bez wiersza Historii), którego Logów kolejka nie        *)
(* przyjęła, znika: zdarzenie obietnicy DziennikPoKolejce z przyczyną decyzji. Dziennik, który miał pierwszą linię   *)
(* (więc postęp mógł pójść do Skrzynki), a którego wersji końcowej kolejka nie przyjęła, znika: zdarzenie obietnicy  *)
(* WersjaKoncowa.                                                                                                   *)
UsunPlik(r, przyczyny) ==
    \/ /\ dziennik' = [dziennik EXCEPT ![r] = "brak"] /\ wpisy' = [wpisy EXCEPT ![r] = <<>>]
       /\ zgubiony' = Zdarz(zgubiony, zapisanyStart[r] /\ ~ZWynikiem(r) /\ ~Przyjete(r), przyczyny)
       /\ bezKonca' = Zdarz(bezKonca, zapisanyStart[r] /\ ~Koncowa(r), przyczyny)
       /\ UNCHANGED awarieUsuniecia
    \/ /\ awarieUsuniecia < MaxAwariiUsuniecia /\ awarieUsuniecia' = awarieUsuniecia + 1
       /\ UNCHANGED <<dziennik, wpisy, zgubiony, bezKonca>>

(* Start Centrum: launcher._start zajmuje port (_listen_when_released), potem create_app buduje aplikację, a w niej    *)
(* InterruptedPricings(...).close() przechodzi dzienniki z sorted(glob("*.jsonl")) po kolei. Pamięć jest nowa.       *)
Start ==
    /\ centrum = "stoi"
    /\ centrum' = "zamyka" /\ wznowiona' = FALSE /\ kursor' = 1 /\ krokZamykania' = "czytaj" /\ rekord' = BrakRekordu
    /\ powod' = {}
    /\ oczekujace' = <<>> /\ doWyslania' = <<>> /\ krokWysylki' = "post"
    /\ bieg' = 0 /\ faza' = "-" /\ zlecenie' = 1 /\ naglowekCzeka' = FALSE
    /\ UNCHANGED <<dysk, liczniki, duchy, zdarzenia>>

\* _closed: record = self._run_logs.guard(record), potem plik Logów (ZapiszLogi).
Odczytane(rodzaj, tresc) == krokZamykania' = "zapisz" /\ rekord' = [rodzaj |-> rodzaj, tresc |-> Straz(tresc)]

(* _closed z dziennika: Logi Urwanego Uruchomienia Wyceny, która doszła do wyniku, to zdarzenie obietnicy           *)
(* BezUrwanychPoWyniku. Jego przyczyny to przyczyna decyzji („historia-nieczytelna”) i brak własnego wiersza        *)
(* Historii („historia-niezapisana”), ale tylko dla Wyceny bez pliku Logów z wynikiem: oba znaleziska to Wycena,     *)
(* której wyniku start nie widzi ani w Historii, ani w pliku Logów. Plik Logów Urwanego Uruchomienia czyta potem      *)
(* gałąź „record = logged”, która tego zdarzenia już nie powtarza.                                                   *)
Zbuduj(r, przyczyny) ==
    /\ Odczytane("urwane", ZDziennika(r))
    /\ poWyniku' = Zdarz(poWyniku, ZWynikiem(r),
                         IF logi[r].rodzaj = "wynik" THEN {}
                         ELSE przyczyny \cup (IF historia[r] THEN {} ELSE {"historia-niezapisana"}))

(* InterruptedPricings.close -> _closed(path) dla dziennika na pozycji kursor: _read(path), plik Logów (file_of,      *)
(* RunLog.model_validate_json) i Historia (recorded) w jednym kroku, bo w create_app nic innego tych plików nie      *)
(* pisze. OSError z odczytu dziennika albo Logów: close łapie go i zostawia dziennik następnemu startowi. Wynik bez   *)
(* Logów (ResultWithoutLogs) nie ma pliku, więc close od razu dopisuje go do _pending.                               *)
Czytaj ==
    LET r == kursor IN
    /\ centrum = "zamyka" /\ kursor <= Wyceny /\ krokZamykania = "czytaj"
    /\ \/ \* glob nie zwraca dziennika, którego nie ma
          /\ dziennik[r] = "brak"
          /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, powod, oczekujace, awarieOdczytu, awarieHistorii, poWyniku>>
       \/ \* except OSError: pricing_journal_unavailable(where="start"), continue
          /\ dziennik[r] # "brak" /\ awarieOdczytu < MaxAwariiOdczytu
          /\ awarieOdczytu' = awarieOdczytu + 1 /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, powod, oczekujace, awarieHistorii, poWyniku>>
       \/ \* _read: None (bez pierwszej linii) -> _remove
          /\ dziennik[r] = "bezStartu"
          /\ krokZamykania' = "usun" /\ powod' = {}
          /\ UNCHANGED <<kursor, rekord, oczekujace, awarieOdczytu, awarieHistorii, poWyniku>>
       \/ \* record = RunLog.model_validate_json(...): Logi z pliku, z wynikiem albo Urwanego Uruchomienia, które
          \* poprzednia praca Centrum zapisała, a których przyjęcia przez kolejkę nikt nie zapisał
          /\ dziennik[r] = "jest" /\ logi[r].rodzaj # "brak"
          /\ Odczytane(logi[r].rodzaj, logi[r].tresc)
          /\ UNCHANGED <<kursor, powod, oczekujace, awarieOdczytu, awarieHistorii, poWyniku>>
       \/ \* bez pliku Logów rozstrzyga Historia
          /\ dziennik[r] = "jest" /\ logi[r].rodzaj = "brak"
          /\ \/ \* elif (result := self._recorded(...)) is not None: ResultWithoutLogs; wiersz może być wierszem
                \* późniejszej Wyceny (_row: >=)
                /\ Zapisana(r)
                /\ oczekujace' = Append(oczekujace, [bieg |-> r, rodzaj |-> "bezLogow", tresc |-> Pusta,
                                                     niezapisany |-> FALSE,
                                                     powod |-> IF ZWynikiem(r) THEN {} ELSE {"wiersz-pozniejszej-wyceny"}])
                /\ kursor' = kursor + 1
                /\ UNCHANGED <<krokZamykania, rekord, powod, awarieOdczytu, awarieHistorii, poWyniku>>
             \/ \* else: record = self._run_logs.interrupted(...)
                /\ ~Zapisana(r)
                /\ Zbuduj(r, {})
                /\ UNCHANGED <<kursor, powod, oczekujace, awarieOdczytu, awarieHistorii>>
             \/ \* _row: OSError z Historii -> None, czyli „nie doszło do wyniku”
                /\ Zapisana(r) /\ awarieHistorii < MaxAwariiHistorii
                /\ awarieHistorii' = awarieHistorii + 1
                /\ Zbuduj(r, {"historia-nieczytelna"})
                /\ UNCHANGED <<kursor, powod, oczekujace, awarieOdczytu>>
    /\ UNCHANGED <<dysk, centrum, wznowiona, doWyslania, krokWysylki, bieg, faza, zlecenie, naglowekCzeka,
                   nastepny, zgasniecia, awarieWpisu, awarieMetryk, awarieLogow, awarieKolejki, awarieUsuniecia, duchy,
                   zgubiony, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezKonca>>

(* _closed: self._run_logs.close(record) -> RunLogs._write -> replace_atomically (plik tymczasowy, os.replace);       *)
(* OSError tylko do dziennika Centrum, a Logi i tak idą do _pending. Logi z pliku wracają do pliku po strażniku.      *)
ZapiszLogi ==
    /\ centrum = "zamyka" /\ krokZamykania = "zapisz"
    /\ \E niezapisany \in BOOLEAN :
        /\ IF niezapisany
           THEN awarieLogow < MaxAwariiLogow /\ awarieLogow' = awarieLogow + 1 /\ UNCHANGED logi
           ELSE logi' = [logi EXCEPT ![kursor] = rekord] /\ UNCHANGED awarieLogow
        /\ oczekujace' = Append(oczekujace, [bieg |-> kursor, rodzaj |-> rekord.rodzaj, tresc |-> rekord.tresc,
                                             niezapisany |-> niezapisany, powod |-> {}])
    /\ kursor' = kursor + 1 /\ krokZamykania' = "czytaj"
    /\ UNCHANGED <<dziennik, wpisy, historia, efenix, kolejka, centrum, wznowiona, rekord, powod, doWyslania,
                   krokWysylki, bieg, faza, zlecenie, naglowekCzeka, nastepny, zgasniecia, awarieWpisu, awarieOdczytu,
                   awarieHistorii, awarieMetryk, awarieKolejki, awarieUsuniecia, duchy, zdarzenia>>

\* close: if closed is None: self._remove(path)
UsunDziennik ==
    /\ centrum = "zamyka" /\ krokZamykania = "usun"
    /\ UsunPlik(kursor, powod)
    /\ kursor' = kursor + 1 /\ krokZamykania' = "czytaj"
    /\ UNCHANGED <<logi, historia, efenix, kolejka, centrum, wznowiona, rekord, powod, oczekujace, doWyslania,
                   krokWysylki, bieg, faza, zlecenie, naglowekCzeka, nastepny, zgasniecia, awarieWpisu, awarieOdczytu,
                   awarieHistorii, awarieMetryk, awarieLogow, awarieKolejki, duchy, poWyniku, inneZnaki, bezStrazy,
                   przedWznowieniem, bezZlecenia>>

(* app.py lifespan: outbox.resume() przed pierwszym zapytaniem HTTP (uvicorn kończy start lifespan, zanim przyjmie   *)
(* zapytanie z kolejki gniazda).                                                                                    *)
Wznow ==
    /\ centrum = "zamyka" /\ kursor > Wyceny /\ ~wznowiona
    /\ wznowiona' = TRUE
    /\ UNCHANGED <<dysk, centrum, kursor, krokZamykania, rekord, powod, oczekujace, doWyslania, krokWysylki, bieg,
                   faza, zlecenie, naglowekCzeka, liczniki, duchy, zdarzenia>>

(* Pierwsze zapytanie API: zależność send_interrupted -> InterruptedPricings.send bierze całe _pending pod blokadą   *)
(* (pending, self._pending = self._pending, []); następne zapytania dostają pustą listę.                             *)
PierwszeZapytanie ==
    /\ centrum = "zamyka" /\ kursor > Wyceny
    /\ wznowiona
    /\ doWyslania' = oczekujace /\ oczekujace' = <<>> /\ krokWysylki' = "post"
    /\ centrum' = IF oczekujace = <<>> THEN "dziala" ELSE "wysyla"
    /\ UNCHANGED <<dysk, wznowiona, kursor, krokZamykania, rekord, powod, bieg, faza, zlecenie, naglowekCzeka,
                   liczniki, duchy, zdarzenia>>

\* Następne Logi z listy send albo koniec send.
Dalej ==
    /\ doWyslania' = Tail(doWyslania) /\ krokWysylki' = "post"
    /\ centrum' = IF Tail(doWyslania) = <<>> THEN "dziala" ELSE "wysyla"

(* send: if self._run_logs.send(final) -> RunLogs.send -> Outbox.post(logi_post(final)) albo, dla wyniku bez Logów,  *)
(* Outbox.post(_logs_post(...)) po strażniku: True, gdy plik kolejki powstał; False zostawia dziennik i wersję       *)
(* końcową następnemu startowi.                                                                                    *)
Wyslij ==
    LET h == Head(doWyslania) IN
    /\ centrum = "wysyla" /\ krokWysylki = "post"
    /\ \/ /\ kolejka' = kolejka \cup {[bieg |-> h.bieg, rodzaj |-> h.rodzaj, tresc |-> h.tresc]}
          /\ PoPoscie(h)
          /\ krokWysylki' = "usun"
          /\ UNCHANGED <<centrum, doWyslania, awarieKolejki>>
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ Dalej
          /\ UNCHANGED <<kolejka, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia>>
    /\ UNCHANGED <<dziennik, wpisy, logi, historia, efenix, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, bieg, faza, zlecenie, naglowekCzeka, nastepny, zgasniecia, awarieWpisu, awarieOdczytu,
                   awarieHistorii, awarieMetryk, awarieLogow, awarieUsuniecia, duchy, zgubiony, poWyniku, bezKonca>>

\* send: _remove(path) po przyjęciu przez kolejkę, z przyczyną decyzji o wersji końcowej.
UsunPoWysylce ==
    /\ centrum = "wysyla" /\ krokWysylki = "usun"
    /\ UsunPlik(Head(doWyslania).bieg, Head(doWyslania).powod)
    /\ Dalej
    /\ UNCHANGED <<logi, historia, efenix, kolejka, wznowiona, kursor, krokZamykania, rekord, powod, oczekujace, bieg,
                   faza, zlecenie, naglowekCzeka, nastepny, zgasniecia, awarieWpisu, awarieOdczytu, awarieHistorii,
                   awarieMetryk, awarieLogow, awarieKolejki, duchy, poWyniku, inneZnaki, bezStrazy, przedWznowieniem,
                   bezZlecenia>>

(* Tata uruchamia Wycenę w efenix: RunHost.start -> run_started -> PricingJournal.run_started (start w pamięci,      *)
(* _header), zanim ruszy wątek; pierwsza linia idzie na dysk w tym samym wywołaniu (ZapiszStart). Każde zapytanie   *)
(* przechodzi najpierw send_interrupted.                                                                           *)
StartWyceny ==
    /\ centrum = "dziala" /\ bieg = 0 /\ nastepny <= Wyceny
    /\ bieg' = nastepny /\ nastepny' = nastepny + 1 /\ faza' = "start" /\ zlecenie' = 1 /\ naglowekCzeka' = TRUE
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, powod, oczekujace, doWyslania,
                   krokWysylki, zgasniecia, awarieWpisu, awarieOdczytu, awarieHistorii, awarieMetryk, awarieLogow,
                   awarieKolejki, awarieUsuniecia, duchy, zdarzenia>>

(* PricingJournal.run_started -> _append_locked(started): pierwsza linia sama jednym write, flush i fsync (#846);     *)
(* OSError: dziennika nie ma, _header zostaje, więc pierwsza linia idzie z następnym wpisem (Wpis), a Wycena biegnie *)
(* dalej. Zgaśnięcie w trakcie tego zapisu zostawia urwaną pierwszą linię (Zgasniecie w fazie "start").            *)
ZapiszStart ==
    /\ bieg # 0 /\ faza = "start"
    /\ \/ /\ dziennik' = [dziennik EXCEPT ![bieg] = "jest"]
          /\ zapisanyStart' = [zapisanyStart EXCEPT ![bieg] = TRUE]
          /\ naglowekCzeka' = FALSE
          /\ UNCHANGED awarieWpisu
       \/ /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
          /\ UNCHANGED <<dziennik, zapisanyStart, naglowekCzeka>>
    /\ faza' = "zaczete"
    /\ UNCHANGED <<wpisy, logi, historia, efenix, kolejka, centrum, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, nastepny, zgasniecia, awarieOdczytu,
                   awarieHistorii, awarieMetryk, awarieLogow, awarieKolejki, awarieUsuniecia, wynik, przepadle,
                   zdarzenia>>

(* PricingJournal._write -> _append_locked: pierwsza linia (gdy jej jeszcze nie ma na dysku) i wpis jednym write,    *)
(* flush i fsync, a bez niej sam wpis, więc wpis bez pierwszej linii na dysku daje dziennik bez startu. OSError:     *)
(* wpis przepada, _header zostaje, Wycena biegnie dalej, a następny wpis _write znów próbuje zapisać (_failed tylko  *)
(* ucisza linię dziennika Centrum).                                                                                 *)
Wpis(rodzaj) ==
    LET r == bieg IN
    \/ /\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> rodzaj, z |-> zlecenie])]
       /\ dziennik' = [dziennik EXCEPT ![r] = IF naglowekCzeka THEN "jest" ELSE IF @ = "brak" THEN "bezStartu" ELSE @]
       /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = @ \/ naglowekCzeka]
       /\ naglowekCzeka' = FALSE
       /\ UNCHANGED <<awarieWpisu, przepadle>>
    \/ /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
       /\ przepadle' = [przepadle EXCEPT ![r] = @ \cup {zlecenie}]
       /\ UNCHANGED <<wpisy, dziennik, zapisanyStart, naglowekCzeka>>

\* efenix_pricing.save: journal.begun(order.row, ...) przed efenix_trace.traced i _priced.
WpisZaczete ==
    /\ bieg # 0 /\ faza = "zaczete"
    /\ Wpis("zaczete")
    /\ faza' = "efenix"
    /\ UNCHANGED <<logi, historia, efenix, kolejka, centrum, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, nastepny, zgasniecia, awarieOdczytu,
                   awarieHistorii, awarieMetryk, awarieLogow, awarieKolejki, awarieUsuniecia, wynik, zdarzenia>>

\* _priced -> _outcome: pierwsze działanie okna efenix, które zmienia zlecenie (data wykonania, Wycena Emmetta, ilość).
ZmianaWEfenix ==
    /\ bieg # 0 /\ faza = "efenix"
    /\ efenix' = [efenix EXCEPT ![bieg] = @ \cup {zlecenie}]
    /\ faza' = "skonczone"
    /\ UNCHANGED <<dziennik, wpisy, logi, historia, kolejka, centrum, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, liczniki, duchy, zdarzenia>>

\* save: results.append(result), journal.ended(result, ...), potem następne zlecenie albo koniec przebiegu.
WpisSkonczone ==
    /\ bieg # 0 /\ faza = "skonczone"
    /\ Wpis("skonczone")
    /\ IF zlecenie < LiczbaZlecen
       THEN zlecenie' = zlecenie + 1 /\ faza' = "zaczete"
       ELSE faza' = "historia" /\ UNCHANGED zlecenie
    /\ UNCHANGED <<logi, historia, efenix, kolejka, centrum, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, doWyslania, krokWysylki, bieg, nastepny, zgasniecia, awarieOdczytu, awarieHistorii,
                   awarieMetryk, awarieLogow, awarieKolejki, awarieUsuniecia, wynik, zdarzenia>>

(* runs._Run.work -> process_run.run_process: silnik doszedł do wyniku, a MetricsStore(...).append(record) zapisuje *)
(* rekord metryk, czyli wiersz Historii, zanim run_process wróci. OSError, UnicodeError albo ValueError z append    *)
(* run_process łapie (metrics_saved = False) i wraca z wynikiem bez wiersza Historii, a Uruchomienie biegnie dalej  *)
(* do Logów z wynikiem.                                                                                            *)
Historia ==
    /\ bieg # 0 /\ faza = "historia"
    /\ wynik' = [wynik EXCEPT ![bieg] = TRUE]
    /\ \/ historia' = [historia EXCEPT ![bieg] = TRUE] /\ UNCHANGED awarieMetryk
       \/ awarieMetryk < MaxAwariiMetryk /\ awarieMetryk' = awarieMetryk + 1 /\ UNCHANGED historia
    /\ faza' = "logi"
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, kolejka, centrum, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, nastepny, zgasniecia,
                   awarieWpisu, awarieOdczytu, awarieHistorii, awarieLogow, awarieKolejki, awarieUsuniecia,
                   zapisanyStart, przepadle, zdarzenia>>

\* RunHost.after -> RunLogs.run_ended -> _keep: _write (replace_atomically) Logów z wynikiem; OSError leci dalej.
LogiWyniku ==
    /\ bieg # 0 /\ faza = "logi"
    /\ \/ logi' = [logi EXCEPT ![bieg] = [rodzaj |-> "wynik", tresc |-> Pusta]] /\ UNCHANGED awarieLogow
       \/ awarieLogow < MaxAwariiLogow /\ awarieLogow' = awarieLogow + 1 /\ UNCHANGED logi
    /\ faza' = "post"
    /\ UNCHANGED <<dziennik, wpisy, historia, efenix, kolejka, centrum, wznowiona, kursor, krokZamykania, rekord,
                   powod, oczekujace, doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, nastepny, zgasniecia,
                   awarieWpisu, awarieOdczytu, awarieHistorii, awarieMetryk, awarieKolejki, awarieUsuniecia, duchy,
                   zdarzenia>>

(* _keep: finally if self._outbox.post(logi_post(kept)): self._queued.add(...). Logi, które kolejka przyjęła, idą do  *)
(* działania po wyniku dziennika (UsunPoLogach); inaczej koniec Uruchomienia, a dziennik zostaje do następnego       *)
(* startu.                                                                                                          *)
WyslijWynik ==
    /\ bieg # 0 /\ faza = "post"
    /\ \/ /\ kolejka' = kolejka \cup {[bieg |-> bieg, rodzaj |-> "wynik", tresc |-> Pusta]}
          /\ przedWznowieniem' = Zdarz(przedWznowieniem, ~wznowiona, {})
          /\ faza' = "usun"
          /\ UNCHANGED <<bieg, awarieKolejki>>
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ bieg' = 0 /\ faza' = "-"
          /\ UNCHANGED <<kolejka, przedWznowieniem>>
    /\ UNCHANGED <<dziennik, wpisy, logi, historia, efenix, centrum, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, doWyslania, krokWysylki, zlecenie, naglowekCzeka, nastepny, zgasniecia, awarieWpisu,
                   awarieOdczytu, awarieHistorii, awarieMetryk, awarieLogow, awarieUsuniecia, duchy, zgubiony,
                   poWyniku, inneZnaki, bezStrazy, bezZlecenia, bezKonca>>

(* RunHost.after -> PricingJournal.run_ended, za RunLogs.run_ended: if self._run_logs.queued(run.info.id): _remove,   *)
(* gdy pierwsza linia jest na dysku (bez _header); potem koniec Uruchomienia (end).                                  *)
UsunPoLogach ==
    /\ bieg # 0 /\ faza = "usun"
    /\ IF naglowekCzeka
       THEN UNCHANGED <<dziennik, wpisy, zgubiony, bezKonca, awarieUsuniecia>>
       ELSE UsunPlik(bieg, {})
    /\ bieg' = 0 /\ faza' = "-"
    /\ UNCHANGED <<logi, historia, efenix, kolejka, centrum, wznowiona, kursor, krokZamykania, rekord, powod,
                   oczekujace, doWyslania, krokWysylki, zlecenie, naglowekCzeka, nastepny, zgasniecia, awarieWpisu,
                   awarieOdczytu, awarieHistorii, awarieMetryk, awarieLogow, awarieKolejki, duchy, poWyniku, inneZnaki,
                   bezStrazy, przedWznowieniem, bezZlecenia>>

(* Zgaśnięcie Centrum w dowolnej chwili: pamięć znika, dysk i kolejka zostają. Wpis w trakcie zapisu może zostać     *)
(* urwany; urwana pierwsza linia to dziennik bez startu (_read: None). Urwana Wycena, która zmieniła już coś w efenix, *)
(* a nie ma dziennika z pierwszą linią, nie dostanie Logów: zdarzenie obietnicy ZaczeteWLogach, w którym brakuje     *)
(* każdego zlecenia zmienionego w efenix.                                                                          *)
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
    /\ centrum' = "stoi" /\ wznowiona' = FALSE /\ bieg' = 0 /\ faza' = "-" /\ oczekujace' = <<>> /\ doWyslania' = <<>>
    /\ UNCHANGED <<wpisy, logi, historia, efenix, kolejka, kursor, krokZamykania, rekord, powod, krokWysylki,
                   zlecenie, naglowekCzeka, nastepny, awarieWpisu, awarieOdczytu, awarieHistorii, awarieMetryk,
                   awarieLogow, awarieKolejki, awarieUsuniecia, duchy, zgubiony, poWyniku, inneZnaki, bezStrazy,
                   przedWznowieniem, bezKonca>>

(* Tata zamyka Centrum („Zamknij Centrum rozliczeń”): Shutdown przyjmuje je tylko, gdy żadne Uruchomienie nie trwa  *)
(* (runs.shutdown_refusal), a samo zapytanie przeszło już send_interrupted.                                       *)
Zamkniecie ==
    /\ centrum = "dziala" /\ bieg = 0
    /\ centrum' = "stoi"
    /\ UNCHANGED <<dysk, wznowiona, kursor, krokZamykania, rekord, powod, oczekujace, doWyslania, krokWysylki, bieg,
                   faza, zlecenie, naglowekCzeka, liczniki, duchy, zdarzenia>>

Next ==
    \/ Start \/ Czytaj \/ ZapiszLogi \/ UsunDziennik \/ Wznow \/ PierwszeZapytanie \/ Wyslij \/ UsunPoWysylce
    \/ StartWyceny \/ ZapiszStart \/ WpisZaczete \/ ZmianaWEfenix \/ WpisSkonczone \/ Historia \/ LogiWyniku \/ WyslijWynik
    \/ UsunPoLogach \/ Zgasniecie \/ Zamkniecie

(* Działający kod robi następny krok, tata otwiera Centrum, gdy żadne nie działa, i kiedyś je zamyka, gdy nic nie    *)
(* trwa (Centrum nie działa bez końca), a przeglądarka wysyła pierwsze zapytanie. Wyceny tata uruchamia, kiedy chce. *)
Sprawiedliwosc ==
    /\ WF_vars(Start) /\ WF_vars(Czytaj) /\ WF_vars(ZapiszLogi) /\ WF_vars(UsunDziennik) /\ WF_vars(Wznow)
    /\ WF_vars(PierwszeZapytanie) /\ WF_vars(Wyslij) /\ WF_vars(UsunPoWysylce) /\ WF_vars(ZapiszStart)
    /\ WF_vars(WpisZaczete)
    /\ WF_vars(ZmianaWEfenix) /\ WF_vars(WpisSkonczone) /\ WF_vars(Historia) /\ WF_vars(LogiWyniku)
    /\ WF_vars(WyslijWynik) /\ WF_vars(UsunPoLogach) /\ WF_vars(Zamkniecie)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

(* Obietnice (docstring pricing_journal.py). *)
\* Dziennik Urwanego Uruchomienia (z pierwszą linią, bez wiersza Historii) znika dopiero, gdy kolejka przyjęła jego Logi:
\* razem ze Zbieganiem to wysyłka co najmniej raz.
DziennikPoKolejce == zgubiony = {}
\* Logi Urwanego Uruchomienia powstają tylko dla Wyceny, która nie doszła do wyniku: dziennik Wyceny z wynikiem start
\* usuwa, a nie zamyka.
BezUrwanychPoWyniku == poWyniku = {}
\* Logi Urwanego Uruchomienia idą do kolejki z tymi samymi znakami, co plik Logów na dysku taty.
TeSameZnaki == inneZnaki = {}
\* Logi Urwanego Uruchomienia idą do kolejki dopiero po strażniku reguły danych pracy Centrum.
PrzezStraznika == bezStrazy = {}
\* Nic nie idzie do kolejki, zanim praca Centrum wywoła Outbox.resume (warunek modelu verify-kolejka-skrzynki).
NicPrzedWznowieniem == przedWznowieniem = {}
\* Każde zlecenie, które Urwana Wycena zmieniła w efenix, jest w jej Logach: skończone albo zaczęte bez wyniku.
ZaczeteWLogach == bezZlecenia = {}
\* Dziennik, który miał pierwszą linię (więc komentarz postępu mógł już być w Skrzynce), znika dopiero, gdy kolejka
\* przyjęła wersję końcową komentarza jego Uruchomienia: razem ze Zbieganiem każda Wycena, która wysłała postęp, kończy
\* się w Skrzynce Logami, Logami Urwanego Uruchomienia albo wynikiem bez Logów, a nie postępem „Uruchomienie trwa”.
WersjaKoncowa == bezKonca = {}
\* Gdy awarie się skończą, a tata otwiera i zamyka Centrum, każdy dziennik znika.
Zbieganie == <>[](\A r \in Biegi : dziennik[r] = "brak")

\* Wariant obietnicy, który pomija zdarzenie, gdy w jego chwili była przyczyna wybaczonego znaleziska.
Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
DziennikPoKolejcePozaZnanymi == Wybaczone(zgubiony, WybaczoneDziennikPoKolejce)
BezUrwanychPoWynikuPozaZnanymi == Wybaczone(poWyniku, WybaczoneBezUrwanychPoWyniku)
TeSameZnakiPozaZnanymi == Wybaczone(inneZnaki, WybaczoneTeSameZnaki)
PrzezStraznikaPozaZnanymi == Wybaczone(bezStrazy, WybaczonePrzezStraznika)
NicPrzedWznowieniemPozaZnanymi == Wybaczone(przedWznowieniem, WybaczoneNicPrzedWznowieniem)
ZaczeteWLogachPozaZnanymi == Wybaczone(bezZlecenia, WybaczoneZaczeteWLogach)
WersjaKoncowaPozaZnanymi == Wybaczone(bezKonca, WybaczoneWersjaKoncowa)
=========================================================================================================================
