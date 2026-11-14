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
(* wysyłki (Id), która poprawia komentarze pierwszej (edit_comment), a     *)
(* komentarz części, której sama nie ma, opróżnia (_RETIRED). Starsza      *)
(* wersja, która dochodzi po nowszej, niczego w issue nie zmienia.         *)
(*                                                                         *)
(* Wysyłka do issue okresu może nieść plik do Archiwum okresu (GitHub      *)
(* Release, #844): plik idzie przed częściami, odmowa Archiwum zostawia    *)
(* plik kolejki „skomentowany” (części są, plik czeka), a Archiwum ma      *)
(* najwyżej jeden plik wysyłki, w wersji nie starszej niż wysłana. Odmowa  *)
(* Archiwum, która trwa (repozytorium bez commitu: 409), zatrzymuje tylko  *)
(* plik: części każdej wysyłki dochodzą (Zbieganie przy PusteRepo).        *)
(*                                                                         *)
(* Plik, gdy przejście odczytało plik nowszej wersji tej samej wysyłki,  *)
(* kolejka oznacza i usuwa bez wysyłania (_superseded, #846). Postęp       *)
(* Wyceny w efenix to starsza wersja Logów bez pliku do Archiwum. Wersja   *)
(* to stopień, potem chwila (#910, outbox.py Version), więc wersja         *)
(* zastępcza ze startu Centrum, wysłana po Logach z wynikiem, może być     *)
(* od nich starsza (StarszaPozniej): porządek wersji to Nr, nie kolejność  *)
(* wysyłek.                                                                *)
(*                                                                         *)
(* Listy GitHuba (issue, Release'y) pokazują nowe issue i Archiwum z      *)
(* opóźnieniem (#879, #887): KeyedBox dopisuje do list to, co założył on  *)
(* albo inny KeyedBox z odpowiedzią (plik obok klucza, keyed_box.py        *)
(* OPENING_FILE), a nie zakłada, gdy w pliku jest zakładanie bez odpowiedzi *)
(* i ostatnia lista przyszła mniej niż LIST_LAG_S po nim.                  *)
(*                                                                         *)
(* Jedna akcja to jeden krok kodu: jedno zapytanie do Skrzynki, jeden      *)
(* zapis pliku tymczasowego, jedna zamiana pliku, jedno usunięcie, jedna   *)
(* decyzja pod blokadą. Komentarz przy akcji i przy każdej straży wskazuje *)
(* plik:funkcję w src/rozliczenia/centrum/. Napisy TLA+ są w ASCII.        *)
(***************************************************************************)
EXTENDS Naturals, Sequences, FiniteSets

CONSTANTS
    Cel,            \* cel wysyłki (outbox.py Target): "okres" (PeriodThread), "nowe" (NewIssue),
                    \* "zgloszenie" (OpenIssue), "znane" (KnownIssue: issue o znanym numerze już jest; z
                    \* OpoznienieListy kolejka właśnie je założyła, a lista GitHuba może go jeszcze nie pokazywać)
    Czesci,         \* części jednej wysyłki (Post.parts, Post.of dzieli treść ponad COMMENT_LIMIT)
    CzesciNowszej,  \* części nowszej wersji (wysyłka 2 przy Diagnozie): Diagnoza zmienia długość Logów
    Naglowek,       \* Post.header: treść nowego issue to nagłówek, a każda część idzie komentarzem (Logi)
    Wysylek,        \* wysyłki do tego samego celu, po kolei (ten sam wiersz rozpoznawczy)
    MaxBrakSieci,   \* Unreachable, Refused albo NoKey przed skutkiem: _waiting daje "stop"
    MaxZgubionych,  \* Unreachable po skutku: Skrzynka przyjęła zapis, a odpowiedź zginęła (POST po _TIMEOUT_S)
    MaxOdmowTresci, \* Rejected (400, 413, 422 w report_box._REJECTIONS): _waiting daje "next"
    MaxBledowPliku, \* OSError z dysku: zapis pliku tymczasowego, zamiana, usunięcie (atomic_file, _remove); z
                    \* OpoznienieListy także zapis i odczyt pliku zapisów KeyedBox (_noted, _settled, _notes)
    AwariaOdczytu,  \* OSError także z odczytu pliku kolejki (outbox.py _queued)
    MaxWylaczen,    \* komputer gaśnie albo proces ginie w dowolnym kroku
    Kolejki,        \* 1 albo 2: dwie kolejki jednego folderu (_claimed, _released)
    DwaProcesy,     \* druga kolejka w nowym procesie, gdy stary zamknął port, a jego wątek jeszcze wysyła
    Diagnoza,       \* wysyłka 2 to nowsza wersja wysyłki 1 (ten sam run_id i etykieta: Logi po Diagnozie,
                    \* run_comments.py RunComments.diagnosed), a nie osobna wysyłka
    Archiwum,       \* wysyłka niesie plik do Archiwum okresu (outbox.py Post.archive, ArchiveFile: Logi Uruchomienia)
    MaxOdmowArchiwum, \* Refused albo Rejected z kroku Archiwum (Token bez uprawnienia do treści repozytorium): ArchiveWaits
    PusteRepo,      \* repozytorium Skrzynki bez commitu przez cały przebieg: GitHub odpowiada 409 „Git Repository is
                    \* empty.” na każde założenie Archiwum (report_box.py GitHubReportBox.open_archive: Rejected)
    Postep,         \* wysyłka 1 to postęp Wyceny w efenix, starsza wersja Logów wysyłki 2 bez pliku do Archiwum
                    \* (comment_versions.py ProgressVersion, run_comments.py RunComments._progress)
    StarszaPozniej, \* wysyłka 2 to wersja zastępcza ze startu Centrum (Rank.STAND_IN: Logi z pliku), starsza od Logów
                    \* z wynikiem wysyłki 1 (Rank.OWN), choć jej plik kolejki powstał później (#910)
    OpoznienieListy, \* listy GitHuba (labelled_issues, archive) pokazują nowe issue i Archiwum po kilku sekundach
    \* Znane znaleziska (konfiguracje.json), każde przy jednej obietnicy: ślady przyczyn, po których wariant
    \* ...PozaZnanymi tej obietnicy ją pomija. Pozostałe obietnice tego przebiegu sprawdza dalej w całości.
    WybaczoneJednoIssue, WybaczoneDokladnieRaz, WybaczoneCzesciWKolejnosci, WybaczoneZbieganie

\* outbox.py Post.__post_init__: Zgłoszenie (OpenIssue) w więcej niż jednej części to ValueError (#724).
ASSUME Cel = "zgloszenie" => Czesci = 1
\* Nowszą wersję wysyłki daje tylko Diagnoza Logów Uruchomienia: issue okresu z nagłówkiem.
ASSUME Diagnoza => Cel = "okres" /\ Naglowek /\ Wysylek = 2
\* Bez Diagnozy każda wysyłka ma Czesci części.
ASSUME CzesciNowszej >= 1 /\ (~Diagnoza => CzesciNowszej = Czesci)
\* outbox.py Post.__post_init__: plik do Archiwum idzie tylko z jedną częścią do issue okresu (Logi z nagłówkiem).
ASSUME Archiwum => Cel = "okres" /\ Naglowek /\ Czesci = 1 /\ CzesciNowszej = 1
\* Repozytorium bez commitu odmawia tylko założenia Archiwum, więc ma znaczenie tylko z plikiem do Archiwum.
ASSUME PusteRepo => Archiwum
\* Postęp to starsza wersja Logów (ten sam run_id i etykieta), a pełne Logi na końcu niosą plik do Archiwum.
ASSUME Postep => Diagnoza /\ Archiwum
\* Wersja zastępcza to wersja Logów z plikiem do Archiwum (run_comments.py RunComments.send_left_behind) po Logach z
\* wynikiem.
ASSUME StarszaPozniej => Diagnoza /\ Archiwum /\ ~Postep

W == 1..Wysylek
\* Identyfikator wysyłki w (etykieta i run_id w znaczniku): przy Diagnozie wysyłka 2 to wersja wysyłki 1.
Id(w) == IF Diagnoza THEN 1 ELSE w
\* Części wysyłki w (Post.parts): nowsza wersja może mieć ich więcej albo mniej niż starsza.
Liczba(w) == IF Diagnoza /\ w = 2 THEN CzesciNowszej ELSE Czesci
Najwiecej == IF CzesciNowszej > Czesci THEN CzesciNowszej ELSE Czesci
\* Wysyłka w niesie plik do Archiwum (Post.archive); postęp Wyceny w efenix (wysyłka 1 przy Postep) go nie ma.
MaPlik(w) == Archiwum /\ ~(Postep /\ w = 1)
\* Miejsce wersji wysyłki w w porządku wersji (outbox.py Version: stopień, potem chwila i numer z nazwy pliku): kolejność
\* wysyłek, a przy StarszaPozniej wysyłka 2 jest starsza od wysyłki 1. Znacznik części i etykieta pliku w Archiwum niosą
\* wysyłkę w, a kolejka porównuje ich Nr (_settle, _put, _deliver_archive, _superseded).
Nr(w) == IF StarszaPozniej /\ w \in {1, 2} THEN 3 - w ELSE w
Q == 1..Kolejki
\* Proces kolejki q: każda w swoim, gdy DwaProcesy, inaczej obie w jednym (wspólne _PASSES).
Proc(q) == IF DwaProcesy THEN q ELSE 1
Procesy == {Proc(q) : q \in Q}

VARIABLES
    \* Dysk taty: przeżywa wyłączenie komputera.
    plik,          \* plik kolejki <czas>-<n>-<etykieta>-<run>.json wysyłki w: "nadejdzie" (post go jeszcze nie
                   \* zapisał), "przepadl" (post zwrócił False albo zginął przed zamianą), "czeka" (bez znacznika),
                   \* "skomentowany" (delivered_parts = len(parts), archived false: czeka tylko na Archiwum),
                   \* "oznaczony" (wszystkie części i plik w Archiwum) albo "usuniety"
    tmp,           \* wysyłki, których plik <nazwa>.json.tmp leży w folderze (replace_atomically przerwane)
    zakladanie,    \* plik keyed_box.py OPENING_FILE po rodzaju ("issue" albo "archiwum"): "swieze", gdy ma zapis bez
                   \* odpowiedzi sprzed mniej niż LIST_LAG_S, inaczej "brak" (zapis dawny, z odpowiedzią albo go nie ma)
    pamiec,        \* skutki z pliku OPENING_FILE (_Notes.opened): issue, które KeyedBox założył z odpowiedzią; każdy
                   \* KeyedBox (także nowego procesu) dopisuje je do listy, która ich nie pokazuje
    pamiecWydania, \* _Notes.archives: Archiwum, które KeyedBox założył z odpowiedzią; każdy dopisuje je do archive
    \* Skrzynka Zgłoszeń (GitHub): przeżywa wszystko.
    issues,        \* issue po numerze: [klucz, tresc]; klucz "L" (wiersz rozpoznawczy okresu albo odcisk
                   \* Zgłoszenia), "N" (Uwaga taty, bez wiersza) albo "Z" (issue o znanym numerze);
                   \* tresc: treść issue, potem komentarze, każdy jako znacznik <<wysyłka, część>> (0: nagłówek)
    archiwum,      \* pliki Archiwum okresu (assets Release), każdy jako wersja w wysyłki, której jest; GitHub nie
                   \* trzyma dwóch plików jednej nazwy, więc upload, gdy plik wysyłki już jest, to Rejected
    wydania,       \* ile Release'ów z tagiem okresu (Archiwów okresu) założyła kolejka
    niewidoczne,   \* issue, których lista issue GitHuba (labelled_issues) jeszcze nie pokazuje
    wydanieNiewidoczne, \* lista Release'ów (archive) jeszcze nie pokazuje Archiwum okresu
    falszywe,      \* duch: GitHub odrzucił drugie Archiwum tagu (422), a części poszły z dopiskiem, że plik czeka
    \* Pamięć procesu: znika z procesem.
    zyje,          \* proces kolejki q: "nie", "tak" (ma port, przyjmuje zapytania HTTP) albo "zamkniety"
                   \* (uvicorn zamknął gniazdo, a proces jeszcze kończy pracę: _GRACEFUL_SHUTDOWN_S)
    pc,            \* krok wątku skrzynka-kolejka kolejki q; "spi", gdy wątek nie biegnie
    draining, again, armed, stopped, \* Outbox._draining, _again, _retry_armed, _stopped_on is not None
    nieczytany,    \* Outbox._read_failed: przejście pominęło plik, którego nie dało się odczytać
    bezBlokady,    \* Outbox._locked_out: przejście zastało blokadę folderu u kolejki innego procesu
    undeleted, rejected,             \* Outbox._undeleted, _rejected (nazwy plików)
    lista,         \* pliki tego przejścia jeszcze nie obsłużone (sorted(glob("*.json")) w _send_all)
    czytane,       \* pliki, które przejście odczytało na początku (read w _send_all, bez _undeleted i _rejected), z
                   \* których _superseded bierze najnowszą wersję każdej wysyłki
    biez,          \* plik, który przejście właśnie wysyła
    nr,            \* numer issue tej wysyłki (otwarte albo znalezione)
    kom,           \* części do zapisania po kolei, każda <<część, "dopisz">> (comment, _comment_all),
                   \* <<część, "popraw">> (edit_comment w _put) albo <<część, "wycofaj">> (edit_comment z _RETIRED)
    arch,          \* wynik kroku Archiwum tej wysyłki (_deliver_archive): "brak" (jeszcze nie albo bez pliku), "jest"
                   \* (InArchive) albo "czeka" (ArchiveWaits: części idą z dopiskiem, plik kolejki "skomentowany")
    po,            \* krok po kroku Archiwum: "zaloz" (_deliver_to_period bez issue), "komentuj" (_put_all) albo
                   \* "dostarczona" (nic do zapisania w issue albo sam plik do Archiwum)
    odmowaArch,    \* Outbox._archive_refused: Archiwum odmówiło w tym przejściu, więc dalej archive_open = False
    bezZnacznika,  \* zapis znacznika się nie udał (suppress(OSError) w _send_all)
    passes,        \* _PASSES[folder] procesu: "wolny", "zajety" (False) albo "prosba" (True)
    blokada,       \* kolejka, która trzyma blokadę systemową pliku przejscie.lock folderu (_folder_lock); 0: żadna.
                   \* Każda kolejka otwiera plik osobno; blokadę zwalnia zamknięcie pliku i koniec procesu
    zamkniecia,    \* ile razy stary proces zamknął port
    odczyt,        \* KeyedBox._listed_at wątku kolejki q po rodzaju: ostatnia lista przyszła mniej niż LIST_LAG_S po
                   \* zapisie z pliku bez odpowiedzi (albo przed nim), więc _held wstrzymuje zakładanie
    \* Zapytania HTTP, które tworzą wysyłki (Outbox.post).
    nadawca,       \* krok post wysyłki w: "czeka", "zamiana", "budzi", "koniec"
    przez,         \* kolejka, której post zapisuje wysyłkę w
    zakolejkowane, \* wysyłki, dla których post zwrócił True (plik "czeka" na dysku)
    odrzucone,     \* duch: wysyłki, których treść Skrzynka kiedyś odrzuciła (Rejected)
    podwojny,      \* duch: kolejka usunęła z Archiwum plik wysyłki w wersji, którą wysyła, albo nowszej, czyli wyśle
                   \* plik drugi raz (_deliver_archive usuwa tylko plik starszej wersji)
    \* Awarie, które już się zdarzyły.
    sieci, zgubione, odmowy, odmowyArchiwum, bledyPliku, wylaczenia,
    krok,          \* ostatni krok słowami kodu: z nich składa się kontrprzykład
    slady          \* przyczyny znanych znalezisk, które już się zdarzyły

dysk == <<plik, tmp>>
watek == <<pc, draining, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, czytane, biez, nr, kom,
           bezZnacznika, arch, po, odmowaArch>>
archiwa == <<archiwum, wydania, podwojny>>
nadawanie == <<nadawca, przez, zakolejkowane, odrzucone>>
awarie == <<sieci, zgubione, odmowy, odmowyArchiwum, bledyPliku, wylaczenia>>
opoznienie == <<niewidoczne, zakladanie, pamiec, odczyt, wydanieNiewidoczne, pamiecWydania, falszywe>>
vars == <<dysk, issues, archiwa, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, krok, slady, opoznienie>>

\* Znane znaleziska (SKILL.md, konfiguracje.json): ślad przyczyny, po której obietnica pada.
ZnaneZnaleziska == {}

\* Rodzaje zapisów, których skutek widać tylko na liście (keyed_box.py: etykieta issue, _archive_kind). Wysłania i
\* usunięcia pliku Archiwum (_file_kind) model nie wstrzymuje: lista plików nie ma tu opóźnienia (SKILL.md).
Rodzaje == {"issue", "archiwum"}

Kroki == {"spi", "petla", "plik", "szukaj", "czytaj", "zaloz", "komentuj", "dostarczona", "zamiana", "usun", "zwolnij",
          "decyzja", "archiwum", "wydanie", "usunplik", "wyslij"}
Para == (0..Wysylek) \X (0..Najwiecej)
Zapisy == {"dopisz", "popraw", "wycofaj"}

TypeOK ==
    /\ plik \in [W -> {"nadejdzie", "przepadl", "czeka", "skomentowany", "oznaczony", "usuniety"}]
    /\ tmp \subseteq W
    /\ issues \in Seq([klucz : {"L", "N", "Z"}, tresc : Seq(Para)])
    /\ archiwum \in Seq(W) /\ wydania \in Nat /\ podwojny \in BOOLEAN
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

\* Świeże issue o znanym numerze, którego lista GitHuba jeszcze nie pokazuje (Init).
Swiezo == IF Cel = "znane" /\ OpoznienieListy THEN {1} ELSE {}

Init ==
    /\ plik = [w \in W |-> "nadejdzie"]
    /\ tmp = {}
    \* KnownIssue: issue Uwagi taty, do którego idzie odnośnik do Logów, już jest (numer 1).
    /\ issues = IF Cel = "znane" THEN <<[klucz |-> "Z", tresc |-> <<<<0, 0>>>>]>> ELSE <<>>
    /\ archiwum = <<>> /\ wydania = 0 /\ podwojny = FALSE
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
    \* KnownIssue z OpoznienieListy (#915): Uwagę, do której idzie komentarz, kolejka właśnie założyła z odpowiedzią
    \* (case_delivery.py _CaseDelivery.delivered), więc lista GitHuba może jej jeszcze nie pokazywać, a plik zapisów ma
    \* jej skutek albo, gdy zapis odpowiedzi rzucił OSError (keyed_box.py _settled), zapis bez odpowiedzi.
    /\ niewidoczne = Swiezo
    /\ \/ /\ pamiec = Swiezo /\ zakladanie = [r \in Rodzaje |-> "brak"]
       \/ /\ Swiezo /= {} /\ pamiec = {} /\ zakladanie = [r \in Rodzaje |-> IF r = "issue" THEN "swieze" ELSE "brak"]
    /\ odczyt = [q \in Q |-> [r \in Rodzaje |-> FALSE]]
    /\ wydanieNiewidoczne = FALSE /\ pamiecWydania = FALSE /\ falszywe = FALSE

\* --- Skrzynka -----------------------------------------------------------------

Zakres(s) == {s[i] : i \in 1..Len(s)}
Klucz == IF Cel = "nowe" THEN "N" ELSE IF Cel = "znane" THEN "Z" ELSE "L"
\* Post.opening: treść nowego issue to nagłówek albo część 1, a reszta części to komentarze.
Cialo(w) == IF Naglowek THEN <<w, 0>> ELSE <<w, 1>>
Od(w, a) == [i \in 1..(Liczba(w) - a + 1) |-> a + i - 1]
Reszta(w) == IF Naglowek THEN Od(w, 1) ELSE Od(w, 2)
Najwyzszy(z) == IF z = {} THEN 0 ELSE CHOOSE i \in z : \A j \in z : j <= i
Najnizszy(z) == CHOOSE i \in z : \A j \in z : i <= j
\* keyed_box.py KeyedBox.labelled_issues kolejki q: issue z listy GitHuba i skutki z pliku zapisów (pamiec,
\* _Notes.opened), wspólnego dla każdego KeyedBox, także nowego procesu; bez odczytu pliku (zna FALSE) sama lista.
Widoczne(q, zna) == {i \in 1..Len(issues) : i \notin niewidoczne \/ (zna /\ i \in pamiec)}
\* report_box.py newest_with_line na liście labelled_issues: najnowsze issue z wierszem; 0 to None.
Najnowsze(q, zna) == Najwyzszy({i \in Widoczne(q, zna) : issues[i].klucz = "L"})
\* Znacznik e należy do wysyłki w (outbox.py _marks: ta sama etykieta i run_id, każda wersja).
Moj(e, w) == e[1] \in W /\ Id(e[1]) = Id(w)
\* outbox.py _deliver_new_issue: najnowsze issue na liście kolejki q, którego treść ma znacznik wysyłki w; 0 to brak.
Swoje(w, q, zna) == Najwyzszy({i \in Widoczne(q, zna) : Moj(issues[i].tresc[1], w)})
\* keyed_box.py _notes przy liście (labelled_issues, archive): odczyt pliku zapisów się udaje (TRUE) albo rzuca OSError
\* (FALSE, jeden z bledyPliku). Bez OpoznienieListy listy pokazują każdy zapis od razu, więc plik nic nie zmienia.
OdczytyZapisow == IF OpoznienieListy /\ bledyPliku < MaxBledowPliku THEN {TRUE, FALSE} ELSE {TRUE}
\* Część k wysyłki w jest w issue i w tej wersji albo nowszej (Diagnoza ją poprawiła).
Ma(i, w, k) == \E j \in 1..Len(issues[i].tresc) :
                 Moj(issues[i].tresc[j], w) /\ issues[i].tresc[j][2] = k /\ Nr(issues[i].tresc[j][1]) >= Nr(w)
\* Każda część wysyłki w jest w jednym issue (w treści albo w komentarzu), w tej wersji albo nowszej.
WIssue(w) == \E i \in 1..Len(issues) : \A k \in 1..Liczba(w) : Ma(i, w, k)
\* Pliki wysyłki w w Archiwum (każda wersja) i czy jest wśród nich plik w tej wersji albo nowszej.
Pliki(w) == {i \in 1..Len(archiwum) : Id(archiwum[i]) = Id(w)}
WArchiwum(w) == ~MaPlik(w) \/ \E i \in Pliki(w) : Nr(archiwum[i]) >= Nr(w)
\* Wysyłka w jest w Skrzynce cała: każda część w issue i plik w Archiwum.
Dostarczona(w) == WIssue(w) /\ WArchiwum(w)
\* Wysyłka w ma w kolejce nowszą wersję (Diagnoza): jej plik może zniknąć bez swoich części, bo Skrzynce należy się
\* nowsza.
Zastapiona(w) == \E v \in zakolejkowane : Nr(v) > Nr(w) /\ Id(v) = Id(w)
\* Żaden komentarz wysyłki w (część k > 0; nagłówka w treści issue kolejka nie zmienia) nie jest w wersji starszej
\* niż w.
BezStarszych(w) ==
    /\ \A i \in 1..Len(issues) : \A j \in 1..Len(issues[i].tresc) :
         LET e == issues[i].tresc[j] IN Moj(e, w) /\ e[2] > 0 => Nr(e[1]) >= Nr(w)
    /\ \A i \in Pliki(w) : Nr(archiwum[i]) >= Nr(w)
\* Miejsca w Skrzynce, w których jest część k wysyłki w, w każdej wersji.
Miejsca(w, k) == UNION {{<<i, j>> : j \in {m \in 1..Len(issues[i].tresc) :
                                             Moj(issues[i].tresc[m], w) /\ issues[i].tresc[m][2] = k}} :
                        i \in 1..Len(issues)}

\* --- Obietnice -----------------------------------------------------------------

\* Uwaga taty (NewIssue) ma jedno issue: następna próba znajduje issue przerwanej po znaczniku w treści.
JednoIssue ==
  /\ wydania <= 1
  /\ CASE Cel \in {"okres", "zgloszenie"} ->
            Cardinality({i \in 1..Len(issues) : issues[i].klucz = "L"}) <= 1
      [] Cel = "znane" -> Len(issues) = 1
      [] Cel = "nowe" -> \A w \in W : Cardinality({i \in 1..Len(issues) : issues[i].tresc[1] = Cialo(w)}) <= 1

\* Plik znika z kolejki, przepada albo dostaje znacznik dopiero, gdy Skrzynka ma każdą jego część i jego plik w
\* Archiwum w jego wersji albo nowszej (plik wersji, którą zastąpiła nowsza w kolejce, może zniknąć bez nich), a znacznik
\* części ("skomentowany"), gdy ma każdą część; żadna część żadnej wysyłki nie jest w Skrzynce dwa razy (ani w dwóch
\* wersjach), Archiwum ma najwyżej jeden plik wysyłki, kolejka nie wysyła pliku do Archiwum drugi raz, a po wysłaniu
\* wersji w Skrzynka nie ma już tekstu ani pliku starszej.
DokladnieRaz ==
    /\ \A w \in zakolejkowane : plik[w] \in {"oznaczony", "usuniety", "przepadl"} /\ ~Zastapiona(w) => Dostarczona(w)
    /\ \A w \in zakolejkowane : plik[w] = "skomentowany" /\ ~Zastapiona(w) => WIssue(w)
    /\ \A w \in W : \A k \in 1..Najwiecej : Cardinality(Miejsca(w, k)) <= 1
    /\ \A w \in W : Cardinality(Pliki(w)) <= 1
    /\ ~podwojny
    /\ \A w \in zakolejkowane : plik[w] \in {"oznaczony", "usuniety"} => BezStarszych(w)
    /\ ~falszywe

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
\* DokladnieRaz, więc Zbieganie patrzy tylko na pliki bez znacznika i każde znalezisko łamie jedną obietnicę. W
\* repozytorium bez commitu (PusteRepo) plik do Archiwum nie dojdzie nigdy, więc zostaje plik ze znacznikiem części
\* ("skomentowany": każda część jest w Skrzynce, DokladnieRaz), ale żaden bez niego: odmowa Archiwum zatrzymuje tylko
\* plik, a nie części tej ani następnych wysyłek.
Zbieganie ==
    <>[](\A w \in zakolejkowane : plik[w] = "czeka" \/ (plik[w] = "skomentowany" /\ ~PusteRepo)
                                  => Odrzucona(w) \/ (Pamieta(w) /\ Dostarczona(w)))

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
\* outbox.py _deliver_to_period: z plikiem do Archiwum najpierw krok Archiwum (_deliver_archive), potem krok dalej.
PoArchiwum(q, dalej, opis) ==
    IF MaPlik(biez[q])
    THEN /\ po' = Ustaw(po, q, dalej) /\ Idz(q, "archiwum", opis)
    ELSE /\ UNCHANGED po /\ Idz(q, dalej, opis)
\* _deliver_archive daje ArchiveWaits (odmowa uprawnienia albo treści): części idą z dopiskiem (_note), a plik
\* kolejki dostaje znacznik części (Znacznik).
Czeka(q, opis) ==
    /\ arch' = Ustaw(arch, q, "czeka")
    /\ Idz(q, po[q], opis)

\* Zapis rodzaju r w pliku jest świeży i bez odpowiedzi (kolejka q bez znaczenia: plik jest wspólny).
Swieze(q, r) == zakladanie[r] = "swieze"
\* keyed_box.py _held: decyduje chwila ostatniej listy (odczyt), a zapis bez odpowiedzi po niej zawsze wstrzymuje.
Wstrzymane(q, r) == odczyt[q][r]
\* _noted przed zapytaniem i _settled po nim: bez odpowiedzi (zna FALSE) zapis rodzaju r zostaje w pliku, a inne
\* kolejki mają listę sprzed niego (odczyt); odpowiedź ze skutkiem (zna) zamienia go w pliku na skutek (pamiec,
\* pamiecWydania), więc nikogo nie wstrzymuje. Zapis i odpowiedź to jeden krok, bo idą w jednym przejściu pod blokadą
\* folderu (_folder_lock), a bez niej druga kolejka zakłada po swojej liście sprzed zapisu (JednoIssue).
\* Bez OpoznienieListy listy pokazują każdy zapis od razu, więc wstrzymanie tylko opóźnia: model go wtedy pomija.
Zapis(q, r, zna) ==
    IF OpoznienieListy
    THEN IF zna
         THEN /\ zakladanie' = [zakladanie EXCEPT ![r] = "brak"]
              /\ odczyt' = [x \in Q |-> [odczyt[x] EXCEPT ![r] = FALSE]]
         ELSE /\ zakladanie' = [zakladanie EXCEPT ![r] = "swieze"]
              /\ odczyt' = [x \in Q |-> IF x = q THEN odczyt[x] ELSE [odczyt[x] EXCEPT ![r] = TRUE]]
    ELSE UNCHANGED <<zakladanie, odczyt>>

\* --- Wątek skrzynka-kolejka ----------------------------------------------------

\* sorted(glob("*.json")) w _send_all: pliki kolejki po nazwie (bez *.json.tmp i przejscie.lock).
PlikiPrzejscia == SelectSeq([i \in 1..Wysylek |-> i], LAMBDA w : plik[w] \in {"czeka", "skomentowany", "oznaczony"})

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
                   bezZnacznika, arch, po, zamkniecia, nadawanie, awarie, slady>>

\* outbox.py _superseded: przejście odczytało na początku (_read) plik nowszej wersji tej samej wysyłki (ten sam cel i
\* run_id: Id), poza _rejected i _undeleted, także plik przed w na liście (wersja zastępcza po Logach z wynikiem).
Nowszy(q, w) == \E v \in czytane[q] : Id(v) = Id(w) /\ Nr(v) > Nr(w)
\* Plik nowszej wersji jest dalej na liście, więc przejście jeszcze go nie obsłużyło: model rozstrzyga jego odczyt teraz.
NowszyDalej(q, w) == \E v \in Zakres(Tail(lista[q])) \cap czytane[q] : Id(v) = Id(w) /\ Nr(v) > Nr(w)

\* outbox.py Outbox._send_all, jeden plik: _undeleted (_remove), _rejected (pomija), _queued (odczyt:
\* nieczytelny albo usunięty przez inny proces plik pomija, a OSError ustawia _read_failed), delivered
\* (_remove), plik, gdy przejście odczytało nowszą wersję tej wysyłki, przed nim albo za nim (_superseded:
\* _mark_delivered bez wysyłania; gdy nowszej za nim nie da się odczytać, ten idzie jak zwykle, a nowsza czeka na
\* budzik), commented (_deliver_archive, sam plik do
\* Archiwum), potem _deliver. Koniec listy: self._stopped_on = None.
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
                         \* _read na początku przejścia dał None, więc ten plik nie wypiera starszej wersji (_superseded).
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
                         \* _send_all czyta pliki na początku przejścia (_read), więc nowsza wersja, której odczyt padł,
                         \* nie wypiera tej, a gdy przejście do niej dojdzie, _skip_unreadable ją pomija do budzika
                         \* RETRY_S (_read_failed): przejście bierze ją z listy już teraz. Nowsza wersja przed tym plikiem
                         \* na liście ma już swój odczyt za sobą (czytane).
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
                         \* _deliver: każdy cel najpierw pyta Skrzynkę o issue z etykietą.
                         /\ Idz(q, "szukaj", "_deliver: wysylka z pliku")
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, nr, kom, bezZnacznika,
                   odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia>>

\* keyed_box.py KeyedBox.labelled_issues (z report_box.py newest_with_line), wołane przez outbox.py
\* _deliver_to_period, _deliver_open_issue, _deliver_to_known i _deliver_new_issue. Odczyt nie zmienia Skrzynki.
\* Znalezione issue dostaje części przez _settle (Czytaj), nowe issue przez open_issue (Zaloz).
Szukaj(q) == \E zna \in OdczytyZapisow :
    /\ pc[q] = "szukaj"
    /\ bledyPliku' = IF zna THEN bledyPliku ELSE bledyPliku + 1
    \* keyed_box.py labelled_issues: _listed_at, chwila tej listy wobec zapisu z pliku (_held przy zakładaniu); bez
    \* odczytu pliku None, więc _held wstrzymuje zakładanie do listy, przy której plik się odczyta (#909).
    /\ odczyt' = [odczyt EXCEPT ![q]["issue"] = ~zna \/ Swieze(q, "issue")]
    /\ \/ /\ sieci < MaxBrakSieci
          /\ sieci' = sieci + 1
          /\ Stop(q, "labelled_issues: Unreachable (brak sieci), przejscie staje")
          /\ UNCHANGED <<nr, kom, slady, po>>
       \/ /\ Cel = "okres"
          /\ UNCHANGED <<sieci, stopped, nieczytany, slady>>
          \* _deliver_to_period: bez issue okresu krok Archiwum, potem nowe issue, a w znalezionym _settle z każdą
          \* częścią (krok Archiwum po odczycie komentarzy, w Czytaj).
          /\ IF Najnowsze(q, zna) = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ PoArchiwum(q, "zaloz", "find_issue: brak issue okresu")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze(q, zna)) /\ kom' = Ustaw(kom, q, Dopisz(Od(biez[q], 1)))
                  /\ UNCHANGED po
                  /\ Idz(q, "czytaj", "labelled_issues: jest issue okresu, _settle z kazda czescia")
       \/ /\ Cel = "zgloszenie"
          /\ UNCHANGED <<sieci, stopped, nieczytany, po>>
          \* _deliver_open_issue: bez otwartego Zgłoszenia z odciskiem nowe issue z jedyną częścią (ASSUME wyżej), a w
          \* znalezionym _settle z tą częścią jako komentarzem z nagłówkiem again. Zgłoszenie, którego treść ma znacznik tej
          \* części, założyła przerwana próba tej wysyłki, więc _settle przejmuje je bez komentarza.
          /\ UNCHANGED slady
          /\ IF Najnowsze(q, zna) = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "labelled_issues: brak otwartego Zgloszenia z odciskiem")
             ELSE /\ nr' = Ustaw(nr, q, Najnowsze(q, zna)) /\ kom' = Ustaw(kom, q, Dopisz(Od(biez[q], 1)))
                  /\ Idz(q, "czytaj", "_deliver_open_issue: jest Zgloszenie z odciskiem, _settle z komentarzem z naglowkiem again")
       \/ /\ Cel = "znane"
          /\ UNCHANGED <<sieci, nieczytany, slady, po>>
          \* _deliver_to_known (keyed_box.py KeyedBox.known_issue): issue jest na liście (także z pliku zapisów), więc
          \* _settle z każdą częścią. Bez niego lista, przy której zapis z etykietą byłby wstrzymany (_held: pliku nie
          \* dało się odczytać albo czeka w nim zapis bez odpowiedzi, #915), to Unreachable bez decyzji, a inna to Gone:
          \* box_post_dropped i _remove bez wysyłki. Issue Uwagi w modelu nikt nie usuwa, więc Gone łamie DokladnieRaz.
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
          \* _deliver_new_issue: issue z treścią ze znacznikiem tej Uwagi (najnowsze, także zamknięte) dostaje resztę
          \* części przez _settle, a bez niego nowe issue.
          /\ IF Swoje(biez[q], q, zna) = 0
             THEN /\ UNCHANGED <<nr, kom>>
                  /\ Idz(q, "zaloz", "labelled_issues: brak issue ze znacznikiem tej Uwagi")
             ELSE /\ nr' = Ustaw(nr, q, Swoje(biez[q], q, zna)) /\ kom' = Ustaw(kom, q, Dopisz(Reszta(biez[q])))
                  /\ Idz(q, "czytaj", "labelled_issues: jest issue ze znacznikiem tej Uwagi, _settle z reszta czesci")
    /\ UNCHANGED <<niewidoczne, zakladanie, pamiec, wydanieNiewidoczne, pamiecWydania, falszywe>>
    /\ UNCHANGED <<dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, bezZnacznika,
                   arch, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia>>

\* Co _settle robi z częścią k wysyłki w w issue i: "jest", gdy znacznik tej części stoi w treści issue albo w
\* pierwszym komentarzu z nim w tej wersji lub nowszej, "popraw", gdy ten komentarz ma starszą wersję, a inaczej
\* "dopisz" (outbox.py _settle i _put).
WTresci(i, w, k) == Moj(issues[i].tresc[1], w) /\ issues[i].tresc[1][2] = k
Komentarze(i, w, k) == {j \in 2..Len(issues[i].tresc) : Moj(issues[i].tresc[j], w) /\ issues[i].tresc[j][2] = k}
Wersja(i, w, k) == issues[i].tresc[Najnizszy(Komentarze(i, w, k))][1]
Krok(i, w, k) ==
    IF WTresci(i, w, k) THEN "jest"
    ELSE IF Komentarze(i, w, k) = {} THEN "dopisz"
    ELSE IF Nr(Wersja(i, w, k)) < Nr(w) THEN "popraw"
    ELSE "jest"
\* outbox.py _settle: komentarz części, której wersja w nie ma (ani w treści issue), w starszej wersji dostaje _RETIRED
\* (part not in wanted and seen < version), po częściach tej wersji.
Wycofaj(i, w) == SelectSeq([k \in 1..Najwiecej |-> <<k, "wycofaj">>],
                           LAMBDA x : x[1] > Liczba(w) /\ ~WTresci(i, w, x[1]) /\ Komentarze(i, w, x[1]) /= {}
                                      /\ Nr(Wersja(i, w, x[1])) < Nr(w))
Plan(i, w, ks) == SelectSeq([n \in 1..Len(ks) |-> <<ks[n][1], Krok(i, w, ks[n][1])>>], LAMBDA x : x[2] /= "jest")
                  \o Wycofaj(i, w)
\* outbox.py _settle: znacznik wysyłki w w nowszej wersji w treści albo komentarzu issue i (newest > version).
Nowsza(i, w) == \E j \in 1..Len(issues[i].tresc) : Moj(issues[i].tresc[j], w) /\ Nr(issues[i].tresc[j][1]) > Nr(w)

\* keyed_box.py KeyedBox.comments w outbox.py _settle: komentarze znalezionego issue przed wysłaniem, a z nich (i z
\* treści issue) plan: nic, gdy issue ma już nowszą wersję tej wysyłki, a inaczej części, których w Skrzynce jeszcze
\* nie ma albo są w starszej wersji, potem _RETIRED w komentarzach części, których ta wersja nie ma. Odczyt nie
\* zmienia Skrzynki.
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
          \* outbox.py _deliver_to_period: issue z nowszą wersją nie dostaje nic, także w Archiwum (_newer); inaczej
          \* krok Archiwum (_deliver_archive), potem części (_put_all).
          /\ IF nowsza
             THEN /\ UNCHANGED po
                  /\ Idz(q, "dostarczona", "comments: issue ma nowsza wersje tej wysylki, Delivered bez zapisu")
             ELSE IF plan = <<>>
             THEN PoArchiwum(q, "dostarczona", "comments: kazda czesc juz jest w Skrzynce, Delivered")
             ELSE PoArchiwum(q, "komentuj", "comments: brakujace czesci komentarzami, starsza wersja poprawka, _RETIRED")
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, bezZnacznika,
                   arch, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy,
                   odmowyArchiwum, bledyPliku, wylaczenia, slady>>

\* keyed_box.py KeyedBox.open_issue, wołane przez outbox.py _deliver_new_issue, _deliver_open_issue i
\* _deliver_to_period z Post.opening (treść: nagłówek albo część 1 i wiersz rozpoznawczy). Najpierw _held: chwila
\* zakładania w pliku sprzed mniej niż LIST_LAG_S, bez odpowiedzi, po której lista nie przyszła, daje
\* Unreachable bez zapytania; potem _noted zapisuje chwilę tego zakładania (OSError: Unreachable bez zapytania), a
\* odmowa (Rejected) przywraca plik sprzed zapisu.
Zaloz(q) ==
    LET w == biez[q]
        nowe == Append(issues, [klucz |-> Klucz, tresc |-> <<Cialo(w)>>])
        \* Nowe issue, którego lista GitHuba jeszcze nie pokazuje.
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
       \* _settled: odpowiedź Sent przyszła, a zapis skutku w pliku rzuca OSError: zapis bez odpowiedzi zostaje.
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
    /\ UNCHANGED <<dysk, archiwa, zyje, draining, again, armed, undeleted, lista, czytane, biez, bezZnacznika, arch, po, odmowaArch,
                   passes, blokada, bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, odmowyArchiwum, wylaczenia>>

\* keyed_box.py KeyedBox.comment (_comment_all, _settle przez _put) albo KeyedBox.edit_comment (_put: komentarz
\* części w starszej wersji dostaje tekst tej wersji w tym samym miejscu issue; _settle: komentarz części, której ta
\* wersja nie ma, dostaje _RETIRED ze znacznikiem tej wersji), po kolei; pierwsza porażka kończy wysyłkę.
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
    /\ UNCHANGED <<opoznienie, dysk, archiwa, zyje, draining, again, armed, undeleted, lista, czytane, biez, nr, bezZnacznika, arch, po,
                   odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawca, przez, zakolejkowane, odmowyArchiwum,
                   bledyPliku, wylaczenia, slady>>

\* --- Archiwum okresu: outbox.py _deliver_archive ------------------------------

\* Kroki Archiwum kończą się „jest” albo „czeka” i przechodzą do po[q]; brak sieci zatrzymuje przejście (Stop). Odmowa
\* (Refused: brak uprawnienia do treści repozytorium; Rejected: treść) każdego kroku to ArchiveWaits (Czeka).
\* keyed_box.py KeyedBox.archive (report_box.py GitHubReportBox.archive: Release z tagiem i jego pliki) w
\* _deliver_archive; przy archive_open = False (_archive_refused) ArchiveWaits bez pytania. Plik tej wysyłki w tej wersji
\* albo nowszej zostaje (_asset_version z etykiety), plik starszej wersji ustępuje (remove), a bez pliku upload.
CzytajArchiwum(q) ==
    LET w == biez[q]
        moje == Pliki(w)
    IN
    /\ pc[q] = "archiwum"
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
               \* keyed_box.py archive: _listed_at Archiwum i plików wobec zapisu z pliku zakładania (_held); bez odczytu
               \* pliku None, więc _held wstrzymuje zapisy Archiwum do odczytu przy następnej liście (#909).
               /\ odczyt' = [odczyt EXCEPT ![q]["archiwum"] = ~zna \/ Swieze(q, "archiwum")]
               \* Archiwum z listy Release'ów albo skutek z pliku zapisów (pamiecWydania, _Notes.archives), wspólnego dla
               \* każdego KeyedBox; bez odczytu pliku sama lista.
               /\ IF wydania = 0 \/ (wydanieNiewidoczne /\ ~(zna /\ pamiecWydania))
                  THEN /\ UNCHANGED arch
                       /\ Idz(q, "wydanie", "archive: brak Archiwum okresu na liscie, open_archive")
                  ELSE IF \E i \in moje : Nr(archiwum[i]) >= Nr(w)
                  THEN /\ arch' = Ustaw(arch, q, "jest")
                       /\ Idz(q, po[q], "archive: plik jest w tej wersji albo nowszej, InArchive")
                  ELSE IF moje /= {}
                  THEN /\ UNCHANGED arch
                       /\ Idz(q, "usunplik", "archive: plik starszej wersji ustepuje, remove")
                  ELSE /\ UNCHANGED arch
                       /\ Idz(q, "wyslij", "archive: pliku nie ma, upload")
    /\ UNCHANGED <<niewidoczne, zakladanie, pamiec, wydanieNiewidoczne, pamiecWydania, falszywe, dysk, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, zgubione, odmowy,
                   wylaczenia, slady>>

\* report_box.py GitHubReportBox.open_archive: 409 „Git Repository is empty.” to Rejected, a _deliver_archive daje z niego
\* ArchiveWaits: części idą z dopiskiem, a przejście idzie dalej do następnych plików.
OdmowaPustegoRepo(q) ==
    /\ UNCHANGED <<stopped, nieczytany>>
    /\ Czeka(q, "open_archive: 409 Git Repository is empty, Rejected, ArchiveWaits")

\* keyed_box.py KeyedBox.open_archive (Release z tagiem okresu, bez plików) w _deliver_archive, wstrzymany jak
\* zakładanie issue (_held, _noted, Zapis). W repozytorium bez commitu (PusteRepo) GitHub nie zakłada Release, tylko
\* odpowiada 409 (OdmowaPustegoRepo), a gdy Release tego tagu już jest, 422 (Rejected, report_box.py open_archive):
\* ArchiveWaits, choć Archiwum przyjęłoby plik (duch falszywe).
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
          /\ Idz(q, "wyslij", "open_archive: Archive bez plikow, upload")
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
    /\ UNCHANGED <<dysk, issues, archiwum, podwojny, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, odmowy, bledyPliku,
                   wylaczenia, slady>>

\* keyed_box.py KeyedBox.remove pliku starszej wersji w _deliver_archive, przed upload tej wersji. Duch podwojny: usunięty
\* plik był w tej wersji albo nowszej, czyli kolejka wyśle plik drugi raz.
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
    /\ UNCHANGED <<opoznienie, dysk, issues, wydania, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, odmowy, bledyPliku,
                   wylaczenia, slady>>

\* keyed_box.py KeyedBox.upload pliku tej wersji (etykieta z wersją, _asset_label) w _deliver_archive. GitHub nie
\* trzyma dwóch plików jednej nazwy: upload, gdy plik tej wysyłki już jest, to Rejected bez skutku (ArchiveWaits).
WyslijPlik(q) ==
    LET w == biez[q]
        zajety == Pliki(w) /= {}
        wyslany == IF zajety THEN archiwum ELSE Append(archiwum, w)
    IN
    /\ pc[q] = "wyslij"
    /\ \/ /\ ~zajety
          /\ archiwum' = wyslany
          /\ arch' = Ustaw(arch, q, "jest")
          /\ UNCHANGED <<sieci, zgubione, odmowyArchiwum, stopped, nieczytany>>
          /\ Idz(q, po[q], "upload: Asset, InArchive")
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
    /\ UNCHANGED <<opoznienie, dysk, issues, wydania, podwojny, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom,
                   bezZnacznika, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, odmowy, bledyPliku,
                   wylaczenia, slady>>

\* outbox.py _send_all po Delivered: _stopped_on = None, listener.delivered (i post jego wysyłek), _first_comments,
\* _remember_address (jego OSError trafia tylko do dziennika), potem znacznik dostarczenia:
\* replace_atomically(path, _queue_text(...)) w suppress(OSError). Ten krok to atomic_file.py
\* replace_atomically: temporary.write_text; jego OSError usuwa plik tymczasowy i wychodzi z suppress. Plik, którego
\* Archiwum nie przyjęło (archive_waits), _archive_waits: _archive_refused, a potem znacznik części (archived false) i
\* następny plik bez _remove; plik, który już miał znacznik części, czeka dalej bez zapisu.
\* Rozbieżność z kodem: Znacznik zeruje stopped na każdej drodze, a _send_all nie rusza _stopped_on po pliku wypartym
\* przez nowszą wersję (_superseded: sam _mark_delivered) ani po pliku commented, na który Archiwum czeka
\* (ArchiveWaits: sam _archive_waits). Nieszkodliwe: stopped czyta tylko Decyzja po końcu przejścia, a przejście albo
\* staje dalej na innym pliku (_stop ustawia _stopped_on znowu), albo kończy listę z self._stopped_on = None.
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
    /\ UNCHANGED <<opoznienie, plik, issues, archiwa, zyje, draining, again, armed, undeleted, rejected, lista, czytane, biez, nr, kom, arch, po,
                   passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy, odmowyArchiwum,
                   wylaczenia, slady>>

\* atomic_file.py replace_atomically: temporary.replace(path) (ponawiane po PermissionError, ostatnie
\* OSError usuwa plik tymczasowy). Bez pliku tymczasowego (usunął go resume innego procesu) replace
\* rzuca FileNotFoundError, czyli też OSError w suppress.
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
                   kom, arch, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione,
                   odmowy, odmowyArchiwum, wylaczenia, slady>>

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
    /\ UNCHANGED <<opoznienie, tmp, issues, archiwa, zyje, draining, again, armed, stopped, nieczytany, rejected, lista, czytane, biez, nr, kom,
                   arch, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, sieci, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia, slady>>

\* outbox.py Outbox._drain po _send_all: koniec bloku _folder_lock (zamknięcie pliku zwalnia blokadę, gdy jest
\* tej kolejki), potem finally z _released; prośba innej kolejki o przejście to _again. Dwa kroki kodu w jednej
\* akcji, jak w Petla.
Zwolnij(q) ==
    /\ pc[q] = "zwolnij"
    /\ blokada' = IF blokada = q THEN 0 ELSE blokada
    /\ again' = IF passes[Proc(q)] = "prosba" THEN Ustaw(again, q, TRUE) ELSE again
    /\ passes' = Ustaw(passes, Proc(q), "wolny")
    /\ Idz(q, "decyzja", "_drain: koniec _folder_lock, _released")
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, draining, armed, stopped, nieczytany, bezBlokady, undeleted, rejected,
                   lista, czytane, biez, nr, kom, bezZnacznika, arch, po, odmowaArch, zamkniecia, nadawanie, awarie, slady>>

\* outbox.py Outbox._drain pod self._changed: z _again następne przejście; bez niego _draining = False
\* i, gdy przejście stanęło (_stopped_on), pominęło nieczytelny plik (_read_failed), zastało odmowę Archiwum
\* (_archive_refused) albo blokadę folderu u innego procesu (_locked_out), a budzenie nie jest nastawione,
\* clock.after(RETRY_S, _woken).
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
                   arch, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, awarie, slady>>

Watek(q) ==
    /\ zyje[q] /= "nie"
    /\ \/ Petla(q) \/ Plik(q) \/ Szukaj(q) \/ Czytaj(q) \/ Zaloz(q) \/ Komentuj(q)
       \/ CzytajArchiwum(q) \/ ZalozArchiwum(q) \/ UsunPlik(q) \/ WyslijPlik(q)
       \/ Znacznik(q) \/ Zamiana(q) \/ Usun(q) \/ Zwolnij(q) \/ Decyzja(q)

\* outbox.py Outbox._woken: budzenie z clock.after (wątek zegara, także w procesie, który zamknął port).
Budzenie(q) ==
    /\ zyje[q] /= "nie"
    /\ armed[q]
    /\ armed' = Ustaw(armed, q, FALSE)
    /\ Budz(q)
    /\ krok' = "_woken po RETRY_S: send_in_background"
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, zyje, stopped, nieczytany, undeleted, rejected, lista, czytane, biez, nr, kom, bezZnacznika,
                   arch, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, nadawanie, awarie, slady>>

\* --- Zapytania HTTP: Outbox.post ------------------------------------------------

\* Kolejka procesu z portem: tylko jej create_app przyjmuje zapytania. Straż bez odpowiednika w kodzie: w jednym
\* procesie z dwiema kolejkami każde post idzie do pierwszej (SKILL.md, What the model leaves out).
MaPort == {q \in Q : zyje[q] = "tak"}
Port == CHOOSE q \in MaPort : \A r \in MaPort : q <= r

\* outbox.py Outbox.post: tekst pliku z _queue_text (bez dysku; wysyłka albo tekst innego typu to TypeError,
\* którego wysyłki Centrum nie dają), nazwa z chwili i next(self._sequence), potem replace_atomically
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
    /\ UNCHANGED <<opoznienie, issues, archiwa, zyje, armed, stopped, nieczytany, undeleted, rejected, lista, czytane, biez, nr, kom, bezZnacznika,
                   arch, po, odmowaArch, passes, blokada, bezBlokady, zamkniecia, odrzucone, sieci, zgubione, odmowy,
                   odmowyArchiwum, wylaczenia, slady>>

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
    /\ czytane' = [q \in Q |-> IF q \in S THEN {} ELSE czytane[q]]
    /\ kom' = [q \in Q |-> IF q \in S THEN <<>> ELSE kom[q]]
    /\ bezZnacznika' = [q \in Q |-> IF q \in S THEN FALSE ELSE bezZnacznika[q]]
    /\ arch' = [q \in Q |-> IF q \in S THEN "brak" ELSE arch[q]]
    /\ po' = [q \in Q |-> IF q \in S THEN "dostarczona" ELSE po[q]]
    /\ odmowaArch' = [q \in Q |-> IF q \in S THEN FALSE ELSE odmowaArch[q]]
    /\ passes' = [p \in Procesy |-> IF \E q \in S : Proc(q) = p THEN "wolny" ELSE passes[p]]
    \* Koniec procesu zamyka jego pliki, a z nimi system zwalnia blokadę folderu.
    /\ blokada' = IF blokada \in S THEN 0 ELSE blokada
    \* Skutki zapisów są w pliku OPENING_FILE, więc zostają; ginie tylko chwila listy wątku.
    /\ UNCHANGED <<pamiec, pamiecWydania>>
    /\ odczyt' = [q \in Q |-> IF q \in S THEN [r \in Rodzaje |-> FALSE] ELSE odczyt[q]]
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
    /\ UNCHANGED <<niewidoczne, zakladanie, wydanieNiewidoczne, falszywe, tmp, issues, archiwa, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, sieci, zgubione, odmowy,
                   odmowyArchiwum, bledyPliku>>

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
    \* Nowy KeyedBox: bez chwili listy; plik zapisów (zakladanie, pamiec, pamiecWydania) zostaje na dysku.
    /\ odczyt' = Ustaw(odczyt, q, [r \in Rodzaje |-> FALSE])
    /\ draining' = Ustaw(draining, q, TRUE)
    /\ pc' = Ustaw(pc, q, "petla")
    /\ krok' = "Centrum startuje: Outbox.resume usuwa *.tmp, send_in_background"
    /\ UNCHANGED <<niewidoczne, zakladanie, pamiec, pamiecWydania, wydanieNiewidoczne, falszywe, plik, issues, archiwa, again, armed, stopped, nieczytany, bezBlokady, undeleted, rejected, lista, czytane, biez,
                   nr, kom, bezZnacznika, arch, po, odmowaArch, passes, blokada, zamkniecia, nadawanie, awarie, slady>>

\* Tata zamyka Centrum albo opiekun ponownego startu je restartuje: uvicorn zamyka gniazdo (port wolny
\* dla nowego Centrum), a proces jeszcze kończy pracę.
Zamknij(q) ==
    /\ DwaProcesy
    /\ zyje[q] = "tak"
    /\ zamkniecia < 1
    /\ zamkniecia' = zamkniecia + 1
    /\ zyje' = Ustaw(zyje, q, "zamkniety")
    /\ krok' = "server.py serve: uvicorn zamyka gniazdo, proces jeszcze konczy prace"
    /\ UNCHANGED <<opoznienie, dysk, issues, archiwa, watek, passes, blokada, nadawanie, awarie, slady>>

\* Proces po zamknięciu portu kończy się, a jego wątki daemon giną z nim.
KoniecProcesu(q) ==
    /\ zyje[q] = "zamkniety"
    /\ Zabij({q})
    /\ krok' = "stary proces Centrum konczy sie, watek kolejki ginie z nim"
    /\ UNCHANGED <<niewidoczne, zakladanie, wydanieNiewidoczne, falszywe, tmp, issues, archiwa, biez, nr, zamkniecia, przez, zakolejkowane, odrzucone, awarie>>

\* GitHub: lista issue (labelled_issues) zaczyna pokazywać nowe issue (verify-github-skrzynki: po 3,0-6,8 s).
Nadaza ==
    /\ \E i \in niewidoczne : niewidoczne' = niewidoczne \ {i}
    /\ krok' = "lista issue GitHuba pokazuje nowe issue"
    /\ UNCHANGED <<dysk, issues, archiwa, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, slady, zakladanie,
                   pamiec, odczyt, wydanieNiewidoczne, pamiecWydania, falszywe>>

\* GitHub: lista Release'ów (archive) zaczyna pokazywać nowe Archiwum (verify-github-skrzynki, #887: po 2,8 s).
NadazaWydanie ==
    /\ wydanieNiewidoczne
    /\ wydanieNiewidoczne' = FALSE
    /\ krok' = "lista Release'ow GitHuba pokazuje nowe Archiwum"
    /\ UNCHANGED <<dysk, issues, archiwa, zyje, watek, passes, blokada, zamkniecia, nadawanie, awarie, slady, niewidoczne,
                   zakladanie, pamiec, odczyt, pamiecWydania, falszywe>>

\* keyed_box.py _held: zapis w pliku dawnieje LIST_LAG_S po swojej chwili (0 <= now - moment), a lista z pytania
\* zadanego później już go pokazuje. Założenie (SKILL.md): zapytanie do report_box._TIMEOUT_S i opóźnienie listy
\* mieszczą się w LIST_LAG_S, a każdy zapis najpierw zapisuje swoją chwilę, więc dawnieje dopiero, gdy jego lista pokazuje
\* każdy zapis tego rodzaju. Lista, która przyszła wcześniej (odczyt), wstrzymuje dalej.
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

\* Działający kod robi następny krok, budzenie przychodzi, zapytanie HTTP kończy post, stary proces
\* kiedyś się kończy, a tata uruchamia Centrum, gdy nic nie działa. Komputer gaśnie i Skrzynka zawodzi
\* skończenie wiele razy (Max...), więc po ostatniej awarii zostają kroki, które się udają.
Sprawiedliwosc ==
    /\ \A q \in Q : WF_vars(Watek(q)) /\ WF_vars(Budzenie(q)) /\ WF_vars(KoniecProcesu(q)) /\ WF_vars(Start(q))
    /\ \A w \in W : WF_vars(Nadaj(w))
    /\ WF_vars(Nadaza) /\ WF_vars(NadazaWydanie) /\ \A r \in Rodzaje : WF_vars(Przedawnienie(r))

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

=============================================================================
