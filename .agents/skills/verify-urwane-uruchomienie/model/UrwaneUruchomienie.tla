------------------------------ MODULE UrwaneUruchomienie ------------------------------
(* Ślad Wyceny w efenix, którą przerwało zgaśnięcie Centrum, przez kolejne starty Centrum: dziennik Wyceny w efenix    *)
(* (src/rozliczenia/centrum/logs_disk.py: Journal, LogsOnDisk.left_behind; run_comments.py:                       *)
(* RunComments.close_left_behind i send_left_behind, comment_versions.close), Logi Urwanego                          *)
(* Uruchomienia (run_comments.py: RecordMaker.interrupted; run_logs_guard.py: guard_logs) i ich droga do Kolejki    *)
(* wysyłki (Outbox.post), obok Logów Wyceny, która doszła do wyniku, i wpisu końca w jej dzienniku, i komentarz       *)
(* postępu Wyceny (#846: RunComments._progress), który wersja końcowa zamienia w podsumowanie: Logi z wynikiem, a gdy *)
(* ich kolejka nie przyjęła w pracy Uruchomienia, wersja zastępcza z następnego startu (#910). Każda akcja to jeden    *)
(* niepodzielny krok kodu, który nazywa komentarz nad akcją i nad jej gałęziami. Kolejka kończy się tu na             *)
(* Outbox.post i najnowszej wersji, którą przyjęła (outbox.py: stopień, potem chwila): co dalej z plikiem kolejki,    *)
(* sprawdza model skilla verify-kolejka-skrzynki.                                                                     *)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Wyceny,              \* Uruchomień Wyceny w efenix, jedno po drugim (Centrum prowadzi jedno naraz)
    LiczbaZlecen,        \* zleceń w każdej Wycenie, po kolei
    MaxZgasniec,         \* zgaśnięć Centrum: brak prądu, zabity proces, zamknięte okno konsoli
    MaxZatrzyman,        \* Zatrzymań Wyceny przy zleceniu: dochodzi do wyniku bez „zlecenie skończone”
    MaxAwariiWpisu,      \* Journal._append_locked: OSError (wpis przepada, Wycena biegnie dalej), także pierwsza
                         \* linia przy starcie i wpis końca; po write może zostać cała pierwsza linia (flush albo fsync
                         \* rzuca)
    MaxAwariiOdczytu,    \* RunComments.close_left_behind: OSError odczytu dziennika, pliku albo katalogu Logów (dziennik zostaje)
    MaxAwariiLogow,      \* LogsOnDisk.write (replace_atomically): OSError, pliku Logów nie ma albo zostaje poprzedni
    MaxAwariiKolejki,    \* Outbox.post: False (pliku kolejki nie dało się zapisać)
    MaxAwariiUsuniecia,  \* _remove: OSError z unlink (dziennik zostaje), przy starcie, po wyniku i za Logami
    MaxCofniecZegara,    \* zegar komputera cofa się, gdy Centrum jest zamknięte (bateria CMOS po braku prądu, a bez sieci
                         \* Windows go nie poprawi): chwila w nazwie pliku kolejki może być wcześniejsza niż w poprzedniej
                         \* pracy Centrum
    TekstDoMaski,        \* ślad zleceń w dzienniku ma tekst, który strażnik reguły danych maskuje (telefon, ulica)
    StareLogi,           \* przed pierwszym startem: Wycena 1 urwana, a jej Logi Urwanego Uruchomienia zapisała, ale nie
                         \* wysłała praca Centrum sprzed strażnika (#851), więc bez maski
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneDziennikPoKolejce, WybaczoneBezUrwanychPoWyniku, WybaczoneTeSameZnaki, WybaczonePrzezStraznika,
    WybaczoneNicPrzedWznowieniem, WybaczoneZaczeteWLogach, WybaczoneWersjaKoncowa, WybaczoneLogiZostaja

Biegi == 1..Wyceny
Zlecenia == 1..LiczbaZlecen
Przyczyny == {"przed-wpisem-konca", "wpis-konca-nieudany", "zapis-logow-nieudany", "wpis-nieudany"}

\* Treść Logów Urwanego Uruchomienia: zlecenia skończone przed zgaśnięciem (efenix_orders), zlecenie zaczęte bez wyniku
\* (interruption.row, 0: zgasło między zleceniami) i to, czy tekst przeszedł przez strażnika reguły danych.
Tresci == [skonczone : SUBSET Zlecenia, zaczete : 0..LiczbaZlecen, tekst : {"surowe", "strzezone"}]
Pusta == [skonczone |-> {}, zaczete |-> 0, tekst |-> "strzezone"]
\* Plik Logów Uruchomienia (logs/uruchomienia/<plik>.json): brak, Logi z wynikiem (ending inny niż interrupted) albo
\* Logi Urwanego Uruchomienia z treścią.
PlikiLogow == [rodzaj : {"brak", "wynik", "urwane"}, tresc : Tresci]
BrakLogow == [rodzaj |-> "brak", tresc |-> Pusta]
\* Wpisy dziennika: „zaczynam zlecenie”, „zlecenie skończone” i „koniec Uruchomienia” (_RunEnded, z jest bez znaczenia).
Wpisy == [rodzaj : {"zaczete", "skonczone", "koniec"}, z : Zlecenia]
\* Wersje końcowe komentarza Uruchomienia, które przyjmuje kolejka: Logi z wynikiem, Logi Urwanego Uruchomienia i wynik
\* bez Logów (comment_versions.ResultWithoutLogs: start ma wpis końca, a pliku Logów nie). Postęp (RunComments._progress)
\* to wersja
\* tej samej wysyłki bez pliku Logów, której kolejka nie trzyma w zbiorze wersji końcowych, tylko w najnowszej wersji.
Rodzaje == {"wynik", "urwane", "bezLogow"}
\* Rodzaj najnowszej wersji komentarza Uruchomienia, którą przyjęła kolejka ("brak": żadnej), i te z pełnymi Logami.
RodzajeWersji == Rodzaje \cup {"brak", "postep"}
ZLogami == {"wynik", "urwane"}
\* Stopień wersji (outbox.py Rank, Post.rank): wybiera go ten, kto wysyła, a nie zegar. Kolejka porównuje najpierw
\* stopień, a chwilę z nazwy pliku tylko w tym samym stopniu (outbox.py Version).
StopienPostepu == 0   \* RunComments._progress -> post_of(ProgressVersion): rank_of daje Rank.DRAFT
StopienZeStartu == 1  \* RunComments.send_left_behind -> post_of(wersja zastępcza): Rank.STAND_IN
StopienWlasny == 2    \* RunComments._keep -> post_of(OwnLogs): rank_of daje Rank.OWN
Stopnie == 0..2
\* Najnowsza przyjęta wersja komentarza Uruchomienia: rodzaj, stopień, czy przyszła w tej pracy Centrum i czy od niej
\* zegar komputera cofnął się przy którymś starcie (wtedy jej chwila może być późniejsza od chwil nowej pracy).
Wersje == [rodzaj : RodzajeWersji, stopien : Stopnie, tejPracy : BOOLEAN, cofniety : BOOLEAN]
BrakWersji == [rodzaj |-> "brak", stopien |-> 0, tejPracy |-> FALSE, cofniety |-> FALSE]
\* Plik Logów, który start zapisze (LogsOnDisk.write), i wersja zastępcza, którą start wyśle: rodzaj i treść.
Rekordy == [rodzaj : ZLogami, tresc : Tresci]
\* RunComments._pending: wersja zastępcza, jej dziennik i czy jej pliku Logów nie udało się zapisać.
Oczekujace == [bieg : Biegi, rodzaj : Rodzaje, tresc : Tresci, niezapisany : BOOLEAN]
\* Fazy Wyceny, w których RunComments._progress jeszcze wysyła postęp: przed znacznikiem końca w RunComments.run_ended
\* (_Watched.ended, za wpisem końca).
PrzedKoncemPostepu == {"zaczete", "efenix", "skonczone", "wynik", "koniec", "logi"}

VARIABLES
    \* Dysk taty i Kolejka wysyłki: zostają po zgaśnięciu Centrum.
    dziennik,        \* dziennik Wyceny r: "brak" | "bezStartu" (urwana pierwsza linia) | "jest"
    wpisy,           \* wpisy dziennika r po pierwszej linii, po kolei (bez urwanych)
    logi,            \* plik Logów Uruchomienia r
    efenix,          \* zlecenia, które Wycena r zmieniła już w efenix
    kolejka,         \* wersje końcowe, które Outbox.post przyjął: [bieg, rodzaj, tresc]
    najnowsza,       \* najnowsza wersja komentarza Uruchomienia r, którą przyjęła kolejka (Wersje): ją ma w końcu
                     \* Skrzynka, bo kolejka zastępuje starszą (_superseded), a Skrzynka nie bierze starszej (_settle)
    \* Pamięć jednej pracy Centrum: znika ze zgaśnięciem i zamknięciem.
    centrum,         \* "stoi" | "zamyka" (create_app: close, potem lifespan) | "wysyla" (po starcie: send) |
                     \* "dziala"
    wznowiona,       \* lifespan tej pracy Centrum wywołał już Outbox.resume
    kursor,          \* który dziennik z sorted(glob) czyta close
    krokZamykania,   \* "czytaj" | "zapisz" (plik Logów) | "usun" (dziennik)
    rekord,          \* Logi (z pliku albo Urwanego Uruchomienia), które close zapisze w pliku
    oczekujace,      \* RunComments._pending: wersje zastępcze do wysłania i ich dzienniki
    doWyslania,      \* to, co send_left_behind wziął z _pending
    krokWysylki,     \* "post" | "usun" (dziennik po przyjęciu)
    bieg,            \* Wycena, która biegnie w tej pracy Centrum (0: żadna)
    faza,            \* gdzie jest Wycena: "-" | "start" | "zaczete" | "efenix" | "skonczone" | "wynik" | "koniec" |
                     \* "logi" | "post" | "zaLogami" (krok 4 run_ended) | "po" (reszta działań po wyniku)
    zlecenie,        \* bieżące zlecenie Wyceny
    naglowekCzeka,   \* Journal._header: pierwszej linii nie ma jeszcze na dysku (przy starcie albo z wpisem)
    wKolejce,        \* accepted w RunComments.run_ended: kolejka przyjęła Logi z wynikiem bieżącej Wyceny
    nastepny,        \* następna Wycena, którą tata może uruchomić
    zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia,
    \* Zmienne pomocnicze: nie mają odpowiednika w kodzie i służą tylko obietnicom.
    zapisanyStart,   \* dziennik r miał kiedyś pierwszą linię
    postepMozliwy,   \* Wycena r mogła wysłać postęp, więc jej komentarz w Skrzynce może mówić, że trwa: pierwsza linia
                     \* jej dziennika jest na dysku bez _header (Journal.progress daje postęp, a RunComments
                     \* wysyła go przy starcie Wyceny i potem co PROGRESS_S); model liczy go od tej chwili
    wynik,           \* Wycena r doszła do wyniku: run_process wrócił z wynikiem, z wierszem Historii albo bez niego
    przepadle,       \* zlecenia Wyceny r, których własny wpis dziennika się nie zapisał (OSError)
    bezKonca,        \* dlaczego dziennik Wyceny r z wynikiem został na dysku bez wpisu końca
    \* Zdarzenia, które łamią obietnice: zbiór przyczyn w chwili każdego zdarzenia.
    zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty

dysk == <<dziennik, wpisy, logi, efenix, kolejka, najnowsza>>
pamiec == <<centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg, faza,
            zlecenie, naglowekCzeka, wKolejce>>
liczniki == <<nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki,
              awarieUsuniecia, cofniecia>>
duchy == <<zapisanyStart, postepMozliwy, wynik, przepadle, bezKonca>>
zdarzenia == <<zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty>>
vars == <<dysk, pamiec, liczniki, duchy, zdarzenia>>

Zdarz(stare, warunek, przyczyny) == IF warunek THEN stare \cup {przyczyny} ELSE stare

TypeOK ==
    /\ dziennik \in [Biegi -> {"brak", "bezStartu", "jest"}]
    /\ \A r \in Biegi : wpisy[r] \in Seq(Wpisy) /\ Len(wpisy[r]) <= 2 * LiczbaZlecen + 1
    /\ logi \in [Biegi -> PlikiLogow]
    /\ efenix \in [Biegi -> SUBSET Zlecenia]
    /\ kolejka \subseteq [bieg : Biegi, rodzaj : Rodzaje, tresc : Tresci]
    /\ najnowsza \in [Biegi -> Wersje]
    /\ centrum \in {"stoi", "zamyka", "wysyla", "dziala"}
    /\ wznowiona \in BOOLEAN
    /\ kursor \in 1..(Wyceny + 1)
    /\ krokZamykania \in {"czytaj", "zapisz", "usun"}
    /\ rekord \in Rekordy
    /\ oczekujace \in Seq(Oczekujace) /\ doWyslania \in Seq(Oczekujace)
    /\ krokWysylki \in {"post", "usun"}
    /\ bieg \in 0..Wyceny
    /\ faza \in {"-", "start", "zaczete", "efenix", "skonczone", "wynik", "koniec", "logi", "post", "zaLogami", "po"}
    /\ zlecenie \in Zlecenia
    /\ naglowekCzeka \in BOOLEAN
    /\ wKolejce \in BOOLEAN
    /\ nastepny \in 1..(Wyceny + 1)
    /\ cofniecia \in 0..MaxCofniecZegara
    /\ zapisanyStart \in [Biegi -> BOOLEAN] /\ postepMozliwy \in [Biegi -> BOOLEAN] /\ wynik \in [Biegi -> BOOLEAN]
    /\ przepadle \in [Biegi -> SUBSET Zlecenia]
    /\ bezKonca \in [Biegi -> SUBSET Przyczyny]
    /\ \A e \in {zgubiony, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty} :
           e \subseteq SUBSET Przyczyny

\* Przed pierwszym startem nic nie ma; ze StareLogi Wycena 1 jest już urwana, jej dziennik ma zlecenie 1 skończone, a
\* plik jej Logów Urwanego Uruchomienia zapisała praca Centrum sprzed strażnika i zgasła przed ich wysłaniem. Jej postęp
\* liczy się jako możliwy, więc model sprawdza też wersję końcową jej komentarza.
Init ==
    /\ dziennik = [r \in Biegi |-> IF StareLogi /\ r = 1 THEN "jest" ELSE "brak"]
    /\ wpisy = [r \in Biegi |-> IF StareLogi /\ r = 1
                                THEN <<[rodzaj |-> "zaczete", z |-> 1], [rodzaj |-> "skonczone", z |-> 1]>>
                                ELSE <<>>]
    /\ logi = [r \in Biegi |-> IF StareLogi /\ r = 1
                               THEN [rodzaj |-> "urwane", tresc |-> [skonczone |-> {1}, zaczete |-> 0, tekst |-> "surowe"]]
                               ELSE BrakLogow]
    /\ efenix = [r \in Biegi |-> IF StareLogi /\ r = 1 THEN {1} ELSE {}]
    /\ kolejka = {}
    /\ najnowsza = [r \in Biegi |-> BrakWersji]
    /\ centrum = "stoi" /\ wznowiona = FALSE /\ kursor = 1 /\ krokZamykania = "czytaj"
    /\ rekord = [rodzaj |-> "urwane", tresc |-> Pusta]
    /\ oczekujace = <<>> /\ doWyslania = <<>> /\ krokWysylki = "post"
    /\ bieg = 0 /\ faza = "-" /\ zlecenie = 1 /\ naglowekCzeka = FALSE /\ wKolejce = FALSE
    /\ nastepny = IF StareLogi THEN 2 ELSE 1
    /\ zgasniecia = 0 /\ zatrzymania = 0 /\ awarieWpisu = 0 /\ awarieOdczytu = 0 /\ awarieLogow = 0 /\ awarieKolejki = 0
    /\ awarieUsuniecia = 0 /\ cofniecia = 0
    /\ zapisanyStart = [r \in Biegi |-> StareLogi /\ r = 1]
    /\ postepMozliwy = [r \in Biegi |-> StareLogi /\ r = 1]
    /\ wynik = [r \in Biegi |-> FALSE]
    /\ przepadle = [r \in Biegi |-> {}]
    /\ bezKonca = [r \in Biegi |-> {}]
    /\ zgubiony = {} /\ poWyniku = {} /\ inneZnaki = {} /\ bezStrazy = {} /\ przedWznowieniem = {} /\ bezZlecenia = {}
    /\ bezWersji = {} /\ wyparty = {}

\* Wycena r doszła do wyniku: run_process wrócił z wynikiem. Wiersz Historii (rekord metryk) mógł się nie zapisać.
ZWynikiem(r) == wynik[r]
\* Logi Urwanego Uruchomienia r są najnowszą wersją, którą przyjęła kolejka (Outbox.post zwrócił True), więc dojdą do
\* Skrzynki: Logi, za którymi kolejka ma nowszą wersję, oznacza i usuwa bez wysłania.
Przyjete(r) == najnowsza[r].rodzaj = "urwane"
\* Kolejka przyjęła Logi z wynikiem r w pracy ich Uruchomienia.
WynikPrzyjety(r) == \E p \in kolejka : p.bieg = r /\ p.rodzaj = "wynik"
\* Najnowsza wersja komentarza Uruchomienia r, którą przyjęła kolejka, jest końcowa, więc ten komentarz w Skrzynce nie
\* zostanie postępem.
Koncowa(r) == najnowsza[r].rodzaj \in Rodzaje
\* Zmiana najnowszej wersji z rodzaju stary na nowy, która gubi Logi: Logi (z wynikiem albo Urwanego Uruchomienia) na
\* postęp albo wynik bez Logów, a Logi z wynikiem także na Logi Urwanego Uruchomienia (#871).
Wyparcie(stary, nowy) == (stary \in ZLogami /\ nowy \notin ZLogami) \/ (stary = "wynik" /\ nowy = "urwane")

(* Outbox.post przyjął wersję rodzaj o stopniu s komentarza Uruchomienia r. Wersja w kolejce to stopień, potem chwila *)
(* i numer z nazwy pliku (outbox.py Version): nowsza jest wersja wyższego stopnia, a w tym samym stopniu późniejsza.   *)
(* W jednej pracy Centrum chwila rośnie z każdą wysyłką także po cofnięciu zegara (Outbox.post), a wersja z           *)
(* wcześniejszej pracy ma wcześniejszą chwilę, chyba że od niej zegar komputera cofnął się przy którymś starcie       *)
(* (cofniety): wtedy chwila nowej wysyłki może być wcześniejsza. Kolejka i Skrzynka zostawiają najnowszą wersję      *)
(* (_superseded, _settle, model verify-kolejka-skrzynki), więc model trzyma tylko ją. Wersja, która gubi Logi         *)
(* najnowszej, to zdarzenie obietnicy LogiZostaja.                                                                   *)
Przyjmij(r, rodzaj, s) ==
    LET u == najnowsza[r] IN
    \E pozniej \in IF u.cofniety /\ ~u.tejPracy THEN BOOLEAN ELSE {TRUE} :
        LET nowsza == u.rodzaj = "brak" \/ s > u.stopien \/ (s = u.stopien /\ pozniej) IN
        /\ najnowsza' = IF nowsza
                        THEN [najnowsza EXCEPT ![r] = [rodzaj |-> rodzaj, stopien |-> s, tejPracy |-> TRUE,
                                                       cofniety |-> FALSE]]
                        ELSE najnowsza
        /\ wyparty' = Zdarz(wyparty, nowsza /\ Wyparcie(u.rodzaj, rodzaj), {})
\* logs_disk._read_journal: dziennik r ma wpis „koniec Uruchomienia” (read.end).
Zakonczony(r) == \E i \in 1..Len(wpisy[r]) : wpisy[r][i].rodzaj = "koniec"
\* Zlecenia, które Wycena r zmieniła w efenix, a których Logi t nie mają ani jako skończonych, ani jako zaczętego bez
\* wyniku; Logi pokrywają Wycenę, gdy takich nie ma.
Niepokryte(r, t) == {z \in efenix[r] : z \notin t.skonczone /\ z # t.zaczete}
Pokrywa(r, t) == Niepokryte(r, t) = {}
\* Znalezisko „wpis-nieudany” dotyczy tylko zleceń, których własny wpis przepadł: brak w Logach zlecenia, którego
\* wpisy się zapisały, to nowe naruszenie.
PoWpisach(r, brakujace) == IF brakujace \subseteq przepadle[r] THEN {"wpis-nieudany"} ELSE {}

(* logs_disk._read_journal: zlecenia z wpisów „zlecenie skończone”, a zlecenie zaczęte bez wyniku z ostatniego wpisu, *)
(* gdy to „zaczynam zlecenie”; RecordMaker.interrupted -> RunLog.interrupted. Tekst ze śladu zleceń jest surowy, dopóki *)
(* nie przejdzie przez strażnika.                                                                                   *)
ZDziennika(r) ==
    LET w == wpisy[r]
        skonczone == {w[i].z : i \in {i \in 1..Len(w) : w[i].rodzaj = "skonczone"}}
    IN [skonczone |-> skonczone,
        zaczete |-> IF Len(w) > 0 /\ w[Len(w)].rodzaj = "zaczete" THEN w[Len(w)].z ELSE 0,
        tekst |-> IF TekstDoMaski /\ skonczone # {} THEN "surowe" ELSE "strzezone"]
\* guard_logs -> guarded w comment_versions.close: strażnik reguły danych pracy Centrum.
Straz(t) == [t EXCEPT !.tekst = "strzezone"]

(* Zdarzenia przy każdym Outbox.post wersji zastępczej h z dziennika: Logi z innymi znakami niż ich plik, tekst bez     *)
(* strażnika, wysyłka przed Outbox.resume i w Logach Urwanego Uruchomienia zlecenie zmienione w efenix bez śladu.     *)
PoPoscie(h) ==
    /\ inneZnaki' = Zdarz(inneZnaki, h.rodzaj = logi[h.bieg].rodzaj /\ logi[h.bieg].tresc # h.tresc,
                          IF h.niezapisany THEN {"zapis-logow-nieudany"} ELSE {})
    /\ bezStrazy' = Zdarz(bezStrazy, h.tresc.tekst = "surowe", {})
    /\ przedWznowieniem' = Zdarz(przedWznowieniem, ~wznowiona, {})
    /\ bezZlecenia' = Zdarz(bezZlecenia, h.rodzaj = "urwane" /\ ~Pokrywa(h.bieg, h.tresc),
                            PoWpisach(h.bieg, Niepokryte(h.bieg, h.tresc)))

(* logs_disk._remove: file_state.remove_file (unlink); brak pliku nic nie robi, OSError zostawia dziennik (linia     *)
(* dziennika Centrum). Dziennik Urwanego Uruchomienia (pierwsza linia, bez wyniku), którego Logi nie są najnowszą     *)
(* wersją w kolejce, znika: zdarzenie obietnicy DziennikPoKolejce z przyczyną decyzji. Dziennik Wyceny, która mogła   *)
(* wysłać postęp, a której najnowsza wersja w kolejce nie jest końcowa, znika: zdarzenie obietnicy WersjaKoncowa.     *)
UsunPlik(r, przyczyny) ==
    \/ /\ dziennik' = [dziennik EXCEPT ![r] = "brak"] /\ wpisy' = [wpisy EXCEPT ![r] = <<>>]
       /\ zgubiony' = Zdarz(zgubiony, zapisanyStart[r] /\ ~ZWynikiem(r) /\ ~Przyjete(r), przyczyny)
       /\ bezWersji' = Zdarz(bezWersji, postepMozliwy[r] /\ ~Koncowa(r), przyczyny)
       /\ UNCHANGED awarieUsuniecia
    \/ /\ awarieUsuniecia < MaxAwariiUsuniecia /\ awarieUsuniecia' = awarieUsuniecia + 1
       /\ UNCHANGED <<dziennik, wpisy, zgubiony, bezWersji>>

(* Start Centrum: launcher._start zajmuje port (_listen_when_released), potem create_app buduje aplikację, a w niej    *)
(* RunComments.close_left_behind() -> LogsOnDisk.left_behind przechodzi dzienniki z sorted(glob("*.jsonl")) po    *)
(* kolei. Pamięć jest nowa, a                                                                                       *)
(* wersje w kolejce są z wcześniejszej pracy. Gdy Centrum było zamknięte, zegar komputera mógł się cofnąć: chwile tej *)
(* pracy mogą być wtedy wcześniejsze od chwil każdej wersji, która już jest w kolejce (cofniety).                    *)
Start ==
    /\ centrum = "stoi"
    /\ centrum' = "zamyka" /\ wznowiona' = FALSE /\ kursor' = 1 /\ krokZamykania' = "czytaj"
    /\ rekord' = [rodzaj |-> "urwane", tresc |-> Pusta]
    /\ oczekujace' = <<>> /\ doWyslania' = <<>> /\ krokWysylki' = "post"
    /\ bieg' = 0 /\ faza' = "-" /\ zlecenie' = 1 /\ naglowekCzeka' = FALSE /\ wKolejce' = FALSE
    /\ \E cofa \in IF cofniecia < MaxCofniecZegara THEN BOOLEAN ELSE {FALSE} :
        /\ cofniecia' = IF cofa THEN cofniecia + 1 ELSE cofniecia
        /\ najnowsza' = [r \in Biegi |-> [najnowsza[r] EXCEPT !.tejPracy = FALSE,
                                                             !.cofniety = @ \/ (cofa /\ najnowsza[r].rodzaj # "brak")]]
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, kolejka, nastepny, zgasniecia, zatrzymania, awarieWpisu,
                   awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia, duchy, zdarzenia>>

\* close: StandInLogs(guard_logs(record, forbidden)) (GuardedLogs), potem plik Logów (ZapiszLogi).
Odczytane(odczytany) == krokZamykania' = "zapisz" /\ rekord' = [odczytany EXCEPT !.tresc = Straz(@)]

(* close z dziennika bez wpisu końca i bez pliku Logów: Logi Urwanego Uruchomienia Wyceny, która doszła do wyniku,  *)
(* to zdarzenie obietnicy BezUrwanychPoWyniku. Jego przyczyny to to, dlaczego dziennik nie ma wpisu końca (bezKonca), *)
(* a „przed-wpisem-konca” tylko, gdy kolejka nie przyjęła jej Logów z wynikiem: zgaśnięcie przed wpisem końca jest   *)
(* przed Logami. Plik Logów Urwanego Uruchomienia czyta potem gałąź „Logi z pliku”, która tego zdarzenia nie powtarza. *)
Zbuduj(r) ==
    /\ Odczytane([rodzaj |-> "urwane", tresc |-> ZDziennika(r)])
    /\ poWyniku' = Zdarz(poWyniku, ZWynikiem(r), bezKonca[r] \ (IF WynikPrzyjety(r) THEN {"przed-wpisem-konca"} ELSE {}))

(* RunComments.close_left_behind -> close(left) dla dziennika na pozycji kursor: LogsOnDisk.left_behind czyta go   *)
(* (_read_journal) i plik Logów (                                                                                   *)
(* LogsOnDisk.logs, _read_logs) w jednym kroku, bo w create_app nic innego tych plików nie pisze. Historii start nie   *)
(* czyta. OSError z odczytu dziennika albo Logów albo z listowania katalogu Logów, który jest (Refused, close rzuca  *)
(* go dalej): close_left_behind łapie go i zostawia dziennik następnemu startowi. Dziennik z pierwszą linią został, bo kolejka nie przyjęła Logów z       *)
(* wynikiem w pracy Uruchomienia (RunComments.run_ended) albo to Urwane Uruchomienie, więc start zamyka go wersją     *)
(* zastępczą (Rank.STAND_IN), a usuwa tylko dziennik bez niej.                                                         *)
Czytaj ==
    LET r == kursor
        koniecZapisany == Zakonczony(r)
    IN
    /\ centrum = "zamyka" /\ kursor <= Wyceny /\ krokZamykania = "czytaj"
    /\ \/ \* glob nie zwraca dziennika, którego nie ma
          /\ dziennik[r] = "brak"
          /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, oczekujace, awarieOdczytu, poWyniku>>
       \/ \* except OSError (left_behind albo close_left_behind): pricing_journal_unavailable(where="start"), continue
          /\ dziennik[r] # "brak" /\ awarieOdczytu < MaxAwariiOdczytu
          /\ awarieOdczytu' = awarieOdczytu + 1 /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, oczekujace, poWyniku>>
       \/ \* _read_journal: None (bez pierwszej linii) -> Drop -> remove_journal
          /\ dziennik[r] = "bezStartu"
          /\ krokZamykania' = "usun"
          /\ UNCHANGED <<kursor, rekord, oczekujace, awarieOdczytu, poWyniku>>
       \/ \* Found: Logi z pliku (z wynikiem, których przyjęcia przez kolejkę nikt nie zapisał, albo Urwanego
          \* Uruchomienia, które poprzedni start zapisał, a nie wysłał)
          /\ dziennik[r] = "jest" /\ logi[r].rodzaj \in ZLogami
          /\ Odczytane(logi[r])
          /\ UNCHANGED <<kursor, oczekujace, awarieOdczytu, poWyniku>>
       \/ \* read.end bez pliku Logów: WithoutLogsVersion (wynik z wpisu końca, zlecenia z dziennika), bez pliku
          /\ dziennik[r] = "jest" /\ logi[r].rodzaj = "brak" /\ koniecZapisany
          /\ oczekujace' = Append(oczekujace, [bieg |-> r, rodzaj |-> "bezLogow", tresc |-> Pusta,
                                               niezapisany |-> FALSE])
          /\ kursor' = kursor + 1
          /\ UNCHANGED <<krokZamykania, rekord, awarieOdczytu, poWyniku>>
       \/ \* bez pliku Logów i bez wpisu końca: StandInLogs(guard_logs(interrupted(read), forbidden))
          /\ dziennik[r] = "jest" /\ logi[r].rodzaj = "brak" /\ ~koniecZapisany
          /\ Zbuduj(r)
          /\ UNCHANGED <<kursor, oczekujace, awarieOdczytu>>
    /\ UNCHANGED <<dysk, centrum, wznowiona, doWyslania, krokWysylki, bieg, faza, zlecenie, naglowekCzeka, wKolejce,
                   nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieLogow, awarieKolejki, awarieUsuniecia,
                   cofniecia, duchy, zgubiony, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, bezWersji, wyparty>>

(* close_left_behind: self._disk.write(logs) -> replace_atomically (plik tymczasowy, os.replace);                   *)
(* OSError tylko do dziennika Centrum, a Logi i tak idą do _pending.                                               *)
ZapiszLogi ==
    /\ centrum = "zamyka" /\ krokZamykania = "zapisz"
    /\ \E niezapisany \in BOOLEAN :
        /\ IF niezapisany
           THEN awarieLogow < MaxAwariiLogow /\ awarieLogow' = awarieLogow + 1 /\ UNCHANGED logi
           ELSE logi' = [logi EXCEPT ![kursor] = rekord] /\ UNCHANGED awarieLogow
        /\ oczekujace' = Append(oczekujace, [bieg |-> kursor, rodzaj |-> rekord.rodzaj, tresc |-> rekord.tresc,
                                             niezapisany |-> niezapisany])
    /\ kursor' = kursor + 1 /\ krokZamykania' = "czytaj"
    /\ UNCHANGED <<dziennik, wpisy, efenix, kolejka, najnowsza, centrum, wznowiona, rekord, doWyslania, krokWysylki,
                   bieg, faza, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu,
                   awarieOdczytu, awarieKolejki, awarieUsuniecia, cofniecia, duchy, zdarzenia>>

(* close: if closed is None: _remove(path, ...), tylko dziennik bez pierwszej linii: postęp do niego nie poszedł.     *)
UsunDziennik ==
    /\ centrum = "zamyka" /\ krokZamykania = "usun"
    /\ UsunPlik(kursor, {})
    /\ kursor' = kursor + 1 /\ krokZamykania' = "czytaj"
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, rekord, oczekujace, doWyslania, krokWysylki,
                   bieg, faza, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu,
                   awarieOdczytu, awarieLogow, awarieKolejki, cofniecia, duchy, poWyniku, inneZnaki, bezStrazy,
                   przedWznowieniem, bezZlecenia, wyparty>>

(* app.py lifespan: outbox.resume() przed wersjami zastępczymi i przed pierwszym zapytaniem HTTP (uvicorn kończy    *)
(* start lifespan, zanim przyjmie zapytanie z kolejki gniazda).                                                     *)
Wznow ==
    /\ centrum = "zamyka" /\ kursor > Wyceny /\ ~wznowiona
    /\ wznowiona' = TRUE
    /\ UNCHANGED <<dysk, centrum, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, liczniki, duchy, zdarzenia>>

(* server.py serve po wpisie start (krok AFTER_START, który lifespan podał po outbox.resume()):                     *)
(* RunComments.send_left_behind bierze całe _pending pod blokadą (pending, self._pending = self._pending, []),     *)
(* przed pierwszym zapytaniem HTTP (_Server.startup woła go, zanim pętla zdarzeń przyjmie zapytanie).            *)
WysylkaStartu ==
    /\ centrum = "zamyka" /\ kursor > Wyceny
    /\ wznowiona
    /\ doWyslania' = oczekujace /\ oczekujace' = <<>> /\ krokWysylki' = "post"
    /\ centrum' = IF oczekujace = <<>> THEN "dziala" ELSE "wysyla"
    /\ UNCHANGED <<dysk, wznowiona, kursor, krokZamykania, rekord, bieg, faza, zlecenie, naglowekCzeka, wKolejce,
                   liczniki, duchy, zdarzenia>>

\* Następna wersja zastępcza z listy send_left_behind albo koniec send_left_behind.
Dalej ==
    /\ doWyslania' = Tail(doWyslania) /\ krokWysylki' = "post"
    /\ centrum' = IF Tail(doWyslania) = <<>> THEN "dziala" ELSE "wysyla"

(* send_left_behind: journal_after(version, accepted=self._queue.post(post_of(version))) -> Outbox.post wersji       *)
(* zastępczej                                                                                                         *)
(* (post_of, Rank.STAND_IN): Logi albo wynik bez Logów; journal_after daje usuń, gdy plik kolejki powstał,            *)
(* a zostaw, gdy post zwrócił False, i dziennik czeka na następny start.                                              *)
Wyslij ==
    LET h == Head(doWyslania) IN
    /\ centrum = "wysyla" /\ krokWysylki = "post"
    /\ \/ /\ kolejka' = kolejka \cup {[bieg |-> h.bieg, rodzaj |-> h.rodzaj, tresc |-> h.tresc]}
          /\ Przyjmij(h.bieg, h.rodzaj, StopienZeStartu)
          /\ PoPoscie(h)
          /\ krokWysylki' = "usun"
          /\ UNCHANGED <<centrum, doWyslania, awarieKolejki>>
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ Dalej
          /\ UNCHANGED <<kolejka, najnowsza, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, wyparty>>
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, wznowiona, kursor, krokZamykania, rekord, oczekujace, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu,
                   awarieLogow, awarieUsuniecia, cofniecia, duchy, zgubiony, poWyniku, bezWersji>>

\* send: _remove(path, ...) po przyjęciu przez kolejkę.
UsunPoWysylce ==
    /\ centrum = "wysyla" /\ krokWysylki = "usun"
    /\ UsunPlik(Head(doWyslania).bieg, {})
    /\ Dalej
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, wznowiona, kursor, krokZamykania, rekord, oczekujace, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu,
                   awarieLogow, awarieKolejki, cofniecia, duchy, poWyniku, inneZnaki, bezStrazy, przedWznowieniem,
                   bezZlecenia, wyparty>>

(* Tata uruchamia Wycenę w efenix: RunHost.start -> RunComments.run_started -> LogsOnDisk.started ->               *)
(* Journal._run_started (start w pamięci,                                                                           *)
(* _header), zanim ruszy wątek; pierwsza linia idzie na dysk w tym samym wywołaniu (ZapiszStart). Zapytanie startu   *)
(* przychodzi po starcie serwera, a więc po wysyłce wersji zastępczych.                                            *)
StartWyceny ==
    /\ centrum = "dziala" /\ bieg = 0 /\ nastepny <= Wyceny
    /\ bieg' = nastepny /\ nastepny' = nastepny + 1 /\ faza' = "start" /\ zlecenie' = 1 /\ naglowekCzeka' = TRUE
    /\ wKolejce' = FALSE
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki,
                   zgasniecia, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia,
                   cofniecia, duchy, zdarzenia>>


(* Journal._run_started -> _append_locked(start): pierwsza linia sama jednym write, flush i fsync (#846),             *)
(* zanim ruszy wątek Wyceny. OSError: _header zostaje, więc pierwsza linia idzie z następnym wpisem, a Wycena biegnie *)
(* dalej; OSError z flush albo fsync po write zostawia ją jednak na dysku. Zgaśnięcie w trakcie tego zapisu zostawia *)
(* urwaną pierwszą linię (Zgasniecie w fazie "start"). Postęp idzie dopiero bez _header (postepMozliwy).            *)
ZapiszStart ==
    LET r == bieg IN
    /\ bieg # 0 /\ faza = "start"
    /\ \/ /\ dziennik' = [dziennik EXCEPT ![r] = "jest"]
          /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = TRUE]
          /\ postepMozliwy' = [postepMozliwy EXCEPT ![r] = TRUE]
          /\ naglowekCzeka' = FALSE
          /\ UNCHANGED awarieWpisu
       \/ /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
          /\ UNCHANGED <<dziennik, zapisanyStart, postepMozliwy, naglowekCzeka>>
       \/ \* except OSError po write, który położył już całą pierwszą linię
          /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
          /\ dziennik' = [dziennik EXCEPT ![r] = "jest"]
          /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = TRUE]
          /\ UNCHANGED <<postepMozliwy, naglowekCzeka>>
    /\ faza' = "zaczete"
    /\ UNCHANGED <<wpisy, logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, wKolejce, nastepny, zgasniecia, zatrzymania,
                   awarieOdczytu, awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia, wynik, przepadle, bezKonca,
                   zdarzenia>>

(* Journal._write -> _append_locked: pierwsza linia (gdy jeszcze jej nie ma na dysku: _header) i wpis jednym          *)
(* write, flush i fsync, a bez niej sam wpis, więc wpis bez pierwszej linii na dysku daje dziennik bez startu.        *)
(* OSError: wpis przepada, _header zostaje, Wycena biegnie dalej, a następny wpis _write znów próbuje zapisać         *)
(* (_failed tylko ucisza linię dziennika Centrum). OSError z flush albo fsync po write może zostawić na dysku całą      *)
(* pierwszą linię: dziennik ma wtedy start, choć _header zostaje.                                                    *)
Wpis(rodzaj) ==
    LET r == bieg IN
    \/ /\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> rodzaj, z |-> zlecenie])]
       /\ dziennik' = [dziennik EXCEPT ![r] = IF naglowekCzeka THEN "jest" ELSE IF @ = "brak" THEN "bezStartu" ELSE @]
       /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = @ \/ naglowekCzeka]
       /\ postepMozliwy' = [postepMozliwy EXCEPT ![r] = TRUE]
       /\ naglowekCzeka' = FALSE
       /\ UNCHANGED <<awarieWpisu, przepadle>>
    \/ /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
       /\ przepadle' = [przepadle EXCEPT ![r] = @ \cup {zlecenie}]
       /\ UNCHANGED <<wpisy, dziennik, zapisanyStart, postepMozliwy, naglowekCzeka>>
    \/ \* except OSError po write, który położył już całą pierwszą linię (wpis przepada albo jest urwany)
       /\ naglowekCzeka /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
       /\ przepadle' = [przepadle EXCEPT ![r] = @ \cup {zlecenie}]
       /\ dziennik' = [dziennik EXCEPT ![r] = "jest"]
       /\ zapisanyStart' = [zapisanyStart EXCEPT ![r] = TRUE]
       /\ UNCHANGED <<wpisy, postepMozliwy, naglowekCzeka>>

\* efenix_pricing.save: journal.begun(order.row, ...) przed efenix_trace.traced i _outcome.
WpisZaczete ==
    /\ bieg # 0 /\ faza = "zaczete"
    /\ Wpis("zaczete")
    /\ faza' = "efenix"
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, zlecenie, wKolejce, nastepny, zgasniecia, zatrzymania, awarieOdczytu,
                   awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia, wynik, bezKonca, zdarzenia>>

\* _outcome: pierwsze działanie okna efenix, które zmienia zlecenie (data wykonania, Wycena Emmetta, ilość).
ZmianaWEfenix ==
    /\ bieg # 0 /\ faza = "efenix"
    /\ efenix' = [efenix EXCEPT ![bieg] = @ \cup {zlecenie}]
    /\ faza' = "skonczone"
    /\ UNCHANGED <<dziennik, wpisy, logi, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, wKolejce, liczniki, duchy,
                   zdarzenia>>

\* save: results.append(result), journal.ended(result), potem następne zlecenie albo koniec przebiegu.
WpisSkonczone ==
    /\ bieg # 0 /\ faza = "skonczone"
    /\ Wpis("skonczone")
    /\ IF zlecenie < LiczbaZlecen
       THEN zlecenie' = zlecenie + 1 /\ faza' = "zaczete"
       ELSE faza' = "wynik" /\ UNCHANGED zlecenie
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, wKolejce, nastepny, zgasniecia, zatrzymania, awarieOdczytu,
                   awarieLogow, awarieKolejki, awarieUsuniecia, cofniecia, wynik, bezKonca, zdarzenia>>

(* save: Zatrzymanie przy zleceniu po journal.begun, a przed journal.ended (okno efenix staje: strona błędu,         *)
(* wylogowanie, zamknięte okno); save oznacza                                                                       *)
(* gotowe i rzuca StopError dalej, a run_process wraca z wynikiem z Zatrzymaniem. Wpisu „zlecenie skończone” tego      *)
(* zlecenia nie ma, więc dziennik może dojść do wyniku z jednym wpisem. Okno efenix staje też przed pierwszym         *)
(* journal.begun (zamknięte w trakcie logowania taty, faza "zaczete"), więc dziennik dochodzi do wyniku z samą         *)
(* pierwszą linią albo bez niej.                                                                                    *)
Zatrzymanie ==
    /\ bieg # 0 /\ faza \in {"zaczete", "efenix", "skonczone"} /\ zatrzymania < MaxZatrzyman
    /\ zatrzymania' = zatrzymania + 1
    /\ faza' = "wynik"
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg,
                   zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, awarieWpisu, awarieOdczytu, awarieLogow,
                   awarieKolejki, awarieUsuniecia, cofniecia, duchy, zdarzenia>>

(* RunComments.run_started (start Wyceny) albo budzik _refresh co PROGRESS_S -> RunComments._progress: Outbox.post   *)
(* postępu z dziennika (post_of(ProgressVersion), Rank.DRAFT), gdy Journal.progress go daje (bez _header) i dopóki    *)
(* RunComments.run_ended nie oznaczył Wyceny jako skończonej (_Watched.ended, pod tą samą blokadą). Model liczy     *)
(* postęp jako możliwy od chwili, gdy pierwsza linia jest na dysku (postepMozliwy); postęp, którego kolejka nie      *)
(* przyjęła, niczego nie zmienia, więc akcja ma tylko przyjęty. Postęp, który zmienia najnowszą wersję z Logami, to *)
(* zdarzenie obietnicy LogiZostaja (Przyjmij).                                                                       *)
Postep ==
    /\ bieg # 0 /\ ~naglowekCzeka /\ faza \in PrzedKoncemPostepu
    /\ Przyjmij(bieg, "postep", StopienPostepu)
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, kolejka, pamiec, liczniki, duchy, zgubiony, poWyniku, inneZnaki,
                   bezStrazy, przedWznowieniem, bezZlecenia, bezWersji>>

(* runs.Run.work -> PreparedRun.conduct -> process_run.run_process: silnik doszedł do wyniku, MetricsStore(...)     *)
(* .append(record) zapisuje rekord metryk (wiersz Historii) albo nie (OSError, UnicodeError, ValueError:              *)
(* metrics_saved = False), a run_process wraca z wynikiem. Wiersza Historii start nie czyta, więc model go nie ma.   *)
(* process_kind.startable przed conduct i w nim nie zmienia stanu, a obiekt z Catalog.prepared zawsze je przechodzi. *)
Wynik ==
    /\ bieg # 0 /\ faza = "wynik"
    /\ wynik' = [wynik EXCEPT ![bieg] = TRUE]
    /\ faza' = "koniec"
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg,
                   zlecenie, naglowekCzeka, wKolejce, liczniki, zapisanyStart, postepMozliwy, przepadle, bezKonca,
                   zdarzenia>>

(* RunHost.after -> RunComments.run_ended, pierwsze działanie po wyniku (after_run w create_app), krok 1 w osłonie     *)
(* _step: Journal.end. Gdy pierwszej linii nie potwierdził żaden zapis (self._header): _remove usuwa to, co nieudany   *)
(* zapis zostawił na dysku (bez pliku unlink rzuca FileNotFoundError, a _remove go pomija); postępu wtedy nie było.   *)
(* Gdy zawiedzie unlink, dziennik zostaje bez wpisu końca. Gdy dziennik ma pierwszą linię na dysku: wpis „koniec      *)
(* Uruchomienia” z wynikiem przez _write (write, flush, fsync); OSError zostawia dziennik bez wpisu końca, a usuwa go *)
(* krok 4 run_ended, gdy kolejka przyjmie Logi z wynikiem, albo następny start po wersji zastępczej.                 *)
WpisKonca ==
    LET r == bieg IN
    /\ bieg # 0 /\ faza = "koniec"
    /\ \/ \* self._header bez pliku: inny proces albo każdy zapis nieudany bez śladu na dysku
          /\ naglowekCzeka /\ dziennik[r] = "brak"
          /\ UNCHANGED <<dziennik, wpisy, awarieWpisu, awarieUsuniecia, zgubiony, bezKonca, bezWersji>>
       \/ \* if header: _remove(path, ...)
          /\ naglowekCzeka /\ dziennik[r] = "jest"
          /\ UsunPlik(r, {})
          /\ bezKonca' = IF dziennik'[r] = "brak" THEN bezKonca
                         ELSE [bezKonca EXCEPT ![r] = @ \cup {"wpis-konca-nieudany"}]
          /\ UNCHANGED awarieWpisu
       \/ \* else: self._write(_RunEnded(...))
          /\ ~naglowekCzeka
          /\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> "koniec", z |-> zlecenie])]
          /\ UNCHANGED <<dziennik, awarieWpisu, awarieUsuniecia, zgubiony, bezKonca, bezWersji>>
       \/ \* _write: OSError, wpis końca przepada, dziennik zostaje
          /\ ~naglowekCzeka /\ awarieWpisu < MaxAwariiWpisu /\ awarieWpisu' = awarieWpisu + 1
          /\ bezKonca' = [bezKonca EXCEPT ![r] = @ \cup {"wpis-konca-nieudany"}]
          /\ UNCHANGED <<dziennik, wpisy, awarieUsuniecia, zgubiony, bezWersji>>
    /\ faza' = "logi" /\ UNCHANGED bieg
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania,
                   awarieOdczytu, awarieLogow, awarieKolejki, cofniecia, zapisanyStart, postepMozliwy, wynik,
                   przepadle, poWyniku, inneZnaki, bezStrazy, przedWznowieniem, bezZlecenia, wyparty>>

(* RunComments.run_ended, za krokiem 1: _Watched.ended pod blokadą (koniec postępu), potem w osłonie _step Logi z    *)
(* wynikiem (_own: RecordMaker.of, guard_logs) i _keep: LogsOnDisk.write (replace_atomically); błąd zapisu wychodzi  *)
(* z _keep dopiero po wysyłce (finally), a _step zapisuje jego typ w dzienniku Centrum.                              *)
LogiWyniku ==
    /\ bieg # 0 /\ faza = "logi"
    /\ \/ logi' = [logi EXCEPT ![bieg] = [rodzaj |-> "wynik", tresc |-> Pusta]] /\ UNCHANGED awarieLogow
       \/ awarieLogow < MaxAwariiLogow /\ awarieLogow' = awarieLogow + 1 /\ UNCHANGED logi
    /\ faza' = "post"
    /\ UNCHANGED <<dziennik, wpisy, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord,
                   oczekujace, doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia,
                   zatrzymania, awarieWpisu, awarieOdczytu, awarieKolejki, awarieUsuniecia, cofniecia, duchy,
                   zdarzenia>>

(* _keep, finally także po błędzie zapisu pliku: post_of(OwnLogs(logs)) do Outbox.post; accepted to jego wynik.       *)
(* Potem krok 4 run_ended (zaLogami).                                                                              *)
WyslijWynik ==
    /\ bieg # 0 /\ faza = "post"
    /\ \/ /\ kolejka' = kolejka \cup {[bieg |-> bieg, rodzaj |-> "wynik", tresc |-> Pusta]}
          /\ Przyjmij(bieg, "wynik", StopienWlasny)
          /\ przedWznowieniem' = Zdarz(przedWznowieniem, ~wznowiona, {})
          /\ wKolejce' = TRUE
          /\ UNCHANGED awarieKolejki
       \/ /\ awarieKolejki < MaxAwariiKolejki /\ awarieKolejki' = awarieKolejki + 1
          /\ UNCHANGED <<kolejka, najnowsza, przedWznowieniem, wKolejce, wyparty>>
    /\ faza' = "zaLogami"
    /\ UNCHANGED <<dziennik, wpisy, logi, efenix, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, nastepny, zgasniecia, zatrzymania,
                   awarieWpisu, awarieOdczytu, awarieLogow, awarieUsuniecia, cofniecia, duchy, zgubiony, poWyniku,
                   inneZnaki, bezStrazy, bezZlecenia, bezWersji>>

(* RunComments.run_ended, krok 4 w osłonie _step: Journal.remove, gdy journal_after(OwnLogs, accepted) daje „usuń”:  *)
(* dziennik z pierwszą linią na dysku znika, gdy kolejka przyjęła Logi z wynikiem w tej pracy Centrum               *)
(* (accepted); dziennik bez niej (_header) usunął już Journal.end. Inaczej zostaje do następnego startu.            *)
UsunPoLogach ==
    /\ bieg # 0 /\ faza = "zaLogami"
    /\ IF wKolejce /\ ~naglowekCzeka
       THEN UsunPlik(bieg, {})
       ELSE UNCHANGED <<dziennik, wpisy, zgubiony, bezWersji, awarieUsuniecia>>
    /\ faza' = "po"
    /\ UNCHANGED <<logi, efenix, kolejka, najnowsza, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace,
                   doWyslania, krokWysylki, bieg, zlecenie, naglowekCzeka, wKolejce, nastepny, zgasniecia, zatrzymania,
                   awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki, cofniecia, duchy, poWyniku, inneZnaki,
                   bezStrazy, przedWznowieniem, bezZlecenia, wyparty>>

(* Reszta after_run za RunComments (QuantityCheckAfterRun, filling), potem koniec Uruchomienia (end): następne         *)
(* może ruszyć.                                                                                                     *)
KoniecUruchomienia ==
    /\ bieg # 0 /\ faza = "po"
    /\ bieg' = 0 /\ faza' = "-"
    /\ UNCHANGED <<dysk, centrum, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, zlecenie,
                   naglowekCzeka, wKolejce, liczniki, duchy, zdarzenia>>

(* Zgaśnięcie Centrum w dowolnej chwili: pamięć znika, dysk i kolejka zostają. Wpis w trakcie zapisu może zostać     *)
(* urwany; urwana pierwsza linia to dziennik bez startu (_read_journal: None), a urwany wpis końca to dziennik bez niego. *)
(* Urwana Wycena, która zmieniła już coś w efenix, a nie ma dziennika z pierwszą linią, nie dostanie Logów: zdarzenie  *)
(* obietnicy ZaczeteWLogach, w którym brakuje każdego zlecenia zmienionego w efenix. Zgaśnięcie po wyniku, a przed    *)
(* wpisem końca, zostawia dziennik Wyceny z wynikiem bez wpisu końca (bezKonca). Postęp Wyceny, której dziennik nie    *)
(* miał nigdy pierwszej linii na dysku, nie dostałby wersji końcowej: zdarzenie obietnicy WersjaKoncowa.             *)
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
    /\ bezKonca' = IF bieg # 0 /\ faza = "koniec" /\ dziennik[bieg] = "jest"
                   THEN [bezKonca EXCEPT ![bieg] = @ \cup {"przed-wpisem-konca"}]
                   ELSE bezKonca
    /\ bezWersji' = Zdarz(bezWersji, bieg # 0 /\ postepMozliwy[bieg] /\ ~zapisanyStart[bieg], {})
    /\ centrum' = "stoi" /\ wznowiona' = FALSE /\ bieg' = 0 /\ faza' = "-" /\ oczekujace' = <<>> /\ doWyslania' = <<>>
    /\ wKolejce' = FALSE
    /\ UNCHANGED <<wpisy, logi, efenix, kolejka, najnowsza, kursor, krokZamykania, rekord, krokWysylki, zlecenie,
                   naglowekCzeka, nastepny, zatrzymania, awarieWpisu, awarieOdczytu, awarieLogow, awarieKolejki,
                   awarieUsuniecia, cofniecia, zapisanyStart, postepMozliwy, wynik, przepadle, zgubiony, poWyniku,
                   inneZnaki, bezStrazy, przedWznowieniem, wyparty>>

(* Tata zamyka Centrum („Zamknij Centrum rozliczeń”): Shutdown przyjmuje je tylko, gdy żadne Uruchomienie nie trwa  *)
(* (runs.shutdown_refusal), a samo zapytanie przyszło po starcie serwera.                                         *)
Zamkniecie ==
    /\ centrum = "dziala" /\ bieg = 0
    /\ centrum' = "stoi"
    /\ UNCHANGED <<dysk, wznowiona, kursor, krokZamykania, rekord, oczekujace, doWyslania, krokWysylki, bieg, faza,
                   zlecenie, naglowekCzeka, wKolejce, liczniki, duchy, zdarzenia>>

Next ==
    \/ Start \/ Czytaj \/ ZapiszLogi \/ UsunDziennik \/ Wznow \/ WysylkaStartu \/ Wyslij \/ UsunPoWysylce
    \/ StartWyceny \/ ZapiszStart \/ WpisZaczete \/ ZmianaWEfenix \/ WpisSkonczone \/ Zatrzymanie \/ Postep \/ Wynik
    \/ WpisKonca \/ LogiWyniku \/ WyslijWynik \/ UsunPoLogach \/ KoniecUruchomienia \/ Zgasniecie \/ Zamkniecie

(* Działający kod robi następny krok, tata otwiera Centrum, gdy żadne nie działa, i kiedyś je zamyka, gdy nic nie    *)
(* trwa (Centrum nie działa bez końca). Wyceny tata uruchamia, kiedy chce.                                         *)
(* Postęp zależy od budzika, a Wycena dochodzi do wyniku bez niego, więc Postep sprawiedliwości nie potrzebuje.      *)
Sprawiedliwosc ==
    /\ WF_vars(Start) /\ WF_vars(Czytaj) /\ WF_vars(ZapiszLogi) /\ WF_vars(UsunDziennik) /\ WF_vars(Wznow)
    /\ WF_vars(WysylkaStartu) /\ WF_vars(Wyslij) /\ WF_vars(UsunPoWysylce) /\ WF_vars(ZapiszStart)
    /\ WF_vars(WpisZaczete) /\ WF_vars(ZmianaWEfenix) /\ WF_vars(WpisSkonczone) /\ WF_vars(Wynik) /\ WF_vars(WpisKonca)
    /\ WF_vars(LogiWyniku) /\ WF_vars(WyslijWynik) /\ WF_vars(UsunPoLogach) /\ WF_vars(KoniecUruchomienia)
    /\ WF_vars(Zamkniecie)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

(* Obietnice (docstringi logs_disk.py i run_comments.py). *)
\* Dziennik Urwanego Uruchomienia (z pierwszą linią, bez wyniku) znika dopiero, gdy jego Logi są najnowszą wersją, którą
\* przyjęła kolejka: razem ze Zbieganiem to wysyłka co najmniej raz.
DziennikPoKolejce == zgubiony = {}
\* Logi Urwanego Uruchomienia powstają tylko dla Wyceny, która nie doszła do wyniku.
BezUrwanychPoWyniku == poWyniku = {}
\* Logi z dziennika idą do kolejki z tymi samymi znakami, co plik Logów na dysku taty.
TeSameZnaki == inneZnaki = {}
\* Logi z dziennika idą do kolejki dopiero po strażniku reguły danych pracy Centrum.
PrzezStraznika == bezStrazy = {}
\* Nic nie idzie do kolejki, zanim praca Centrum wywoła Outbox.resume (warunek modelu verify-kolejka-skrzynki).
NicPrzedWznowieniem == przedWznowieniem = {}
\* Każde zlecenie, które Urwana Wycena zmieniła w efenix, jest w jej Logach: skończone albo zaczęte bez wyniku.
ZaczeteWLogach == bezZlecenia = {}
\* Wycena, która mogła wysłać postęp, ma dziennik z pierwszą linią na dysku, a ten znika dopiero, gdy najnowsza wersja
\* komentarza jej Uruchomienia, którą przyjęła kolejka, jest końcowa (Logi z wynikiem, Logi Urwanego Uruchomienia albo
\* wynik bez Logów): razem ze Zbieganiem po następnym starcie każda Wycena, która wysłała postęp, ma w Skrzynce wersję
\* końcową, a nie postęp „Uruchomienie trwa”.
WersjaKoncowa == bezWersji = {}
\* Najnowsza wersja komentarza Uruchomienia z Logami (z wynikiem albo Urwanego Uruchomienia) nigdy nie ustępuje postępowi
\* ani wynikowi bez Logów, a Logi z wynikiem także Logom Urwanego Uruchomienia: Logi nie znikają ze Skrzynki ani z kolejki.
LogiZostaja == wyparty = {}
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
WersjaKoncowaPozaZnanymi == Wybaczone(bezWersji, WybaczoneWersjaKoncowa)
LogiZostajaPozaZnanymi == Wybaczone(wyparty, WybaczoneLogiZostaja)
=========================================================================================================================
