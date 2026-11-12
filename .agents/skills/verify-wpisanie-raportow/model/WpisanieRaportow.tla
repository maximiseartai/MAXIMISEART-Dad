------------------------------ MODULE WpisanieRaportow ------------------------------
(* Jedna komórka raportu (SKUTECZNE albo CZYNNOŚCI ZREALIZOWANE jednego zlecenia) we Wpisaniu raportów z maili     *)
(* (ADR 0028): wartość w INTERMAX, pamięć własnych wpisów (wpisanie-raportow-stan.json, OwnEntries), wynik          *)
(* ostatniego kliknięcia dla widoku Raporty (wpisanie-raportow-wynik.json) i decyzje „Zostaw moją”                   *)
(* (wpisanie-raportow-decyzje.json, Kept), każdy plik z treścią odłożoną w pamięci pracy Centrum po nieudanym        *)
(* zapisie (centrum/atomic_file.py StateFile, centrum/report_entering_state.py _TextFile). Reguły komórki to czysta   *)
(* funkcja worker_reports/_cells.py reconcile; kroki kliknięcia to report_entering.py enter_from_mail, a „Zostaw    *)
(* moją” to centrum/report_entering_run.py ReportEnteringEntry.keep i FileReportState.keep. Zapis INTERMAX           *)
(* (intermax_cells.write_cells) jest tu jednym krokiem z odmową: jego bajty sprawdza skill verify-zapis-intermax.   *)
(* Każda akcja to jeden niepodzielny krok kodu z tabeli w SKILL.md skilla verify-wpisanie-raportow.                  *)
EXTENDS Naturals, FiniteSets

CONSTANTS
    Karty,              \* kart widoku Raporty, z których tata klika „Zostaw moją” naraz (1 albo 2)
    MaxZgasniec,        \* zgaśnięć Centrum: brak prądu, zabity proces; treść odłożona w pamięci ginie
    MaxAwariiIntermax,  \* write_cells: Refusal albo Rejected (Excel, OneDrive, nieudany zapis), INTERMAX nietknięty
    MaxAwariiPamieci,   \* StateFile.write pamięci, wyniku i decyzji: OSError z replace_atomically pliku w config;
    MaxAwariiWyniku,    \* plik, którego zapis zawiódł, może zawodzić przy każdym ponowieniu (StateFile.retry) i
    MaxAwariiDecyzji,   \* zapisie (StateFile.write), dopóki treść czeka, bez dalszych awarii z tej puli
    MozeOtworzyc,       \* tata usuwa Plik zbiorczy okresu, który już był zamknięty, więc okres znów jest otwarty
    MozeKopia,          \* OneDrive kładzie obok INTERMAX kopię konfliktu (onedrive_conflicts.beside)
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneNieNadpisuje, WybaczoneZostawUcisza, WybaczoneBezFalszywejRoznicy, WybaczoneKopiaZatrzymuje

Brak == "brak"
Pusta == "pusta"
Wpisy == {"A", "B"}             \* treść Wpisu raportu dla komórki z najnowszego maila Wykonawcy
Reczne == Wpisy                 \* wartości, które tata albo jego pracownik wpisuje w Excelu: każda równa jakiemuś Wpisowi
Komorki == {Pusta} \cup Reczne
Pamieci == {Brak} \cup Wpisy    \* pamięć jednej komórki: bez wpisu albo wartość, którą narzędzie samo wpisało
KartyZ == 1..Karty
Fazy == {"wolne", "sprawdzone", "zapisane", "pamiec"}
Etapy == {"nic", "sprawdzona", "czyta"}
Ponowienia(czeka) == IF czeka THEN {"udany", "nieudany"} ELSE {"bez"}
Zapisy == {"udany", "nieudany"}
\* StateFile._save: zapis pliku, którego treść już czeka, idzie bez przerw i może znów zawieść (OSError); taka porażka
\* nie bierze nowej awarii z puli, jak nieudane ponowienie (Ponowienia).
MozeZawiesc(z, czeka, awarie, max) == z = "nieudany" => (czeka \/ awarie < max)
Nieudane(z, czeka) == IF z = "nieudany" /\ ~czeka THEN 1 ELSE 0
Przyczyny == {"przywrocona-wartosc", "przywrocona-ze-starej-pamieci", "przed-pamiecia", "pamiec-odlozona",
              "okres-otwarty-ponownie", "decyzja-odlozona", "przy-sprawdzaniu", "po-zapisie"}

VARIABLES
    \* świat taty
    komorka,            \* wartość komórki w INTERMAX
    autor,              \* duch: kto wpisał obecną wartość ("nikt": pusta, "narzedzie", "tata": tata albo pracownik)
    wpis,               \* treść najnowszego Wpisu raportu dla komórki ze Skrzynki raportów (Brak: bez Wpisu)
    okresOtwarty,       \* okres dnia zlecenia nie ma Pliku zbiorczego (Window.opens)
    kopia,              \* obok INTERMAX leży kopia konfliktu OneDrive
    \* pliki w config: treść na dysku, czy treść czeka w pamięci pracy Centrum (StateFile.unavailable) i jaka
    pamiec, pamiecCzeka, pamiecOdlozona,
    wynik, wynikCzeka, wynikOdlozony,       \* różnica z ręczną wartością w wyniku: Brak albo treść Wpisu
    decyzje, decyzjeCzeka, decyzjeOdlozone, \* treści Wpisu, przy których tata kliknął „Zostaw moją”
    \* kliknięcie „Wpisz raporty z maili” (jedno naraz: RunHost.start)
    faza, migPamiec, migDecyzje, kopiaPrzySprawdzaniu,
    planPamiec, planRoznica, planZapisal, planFalszywa, planPrzyczyny, planZapomina,
    \* „Zostaw moją” z kart: etap żądania, treść różnicy, decyzje przeczytane pod blokadą, blokada _deciding
    etap, tresc, odczyt, blokada,
    \* duchy: historia, z której obietnice biorą przyczyny znanych znalezisk
    ostatniWlasny,      \* wartość, którą narzędzie ostatnio wpisało do komórki
    zapomniala,         \* pamięć na dysku nie ma już ostatniWlasny, bo kliknięcie widziało komórkę bez niej
    zapomnialaCzeka,    \* to samo, ale tylko w treści odłożonej
    utrataPamieci,      \* zgaśnięcie zostawiło na dysku pamięć inną niż PamiecWlasciwa, a narzędzie od tej pory nie pisało
    bezPamieci,         \* dlaczego pamięć nie ma wartości, którą narzędzie wpisało i która dalej stoi w komórce
    upuszczona,         \* pamięć upuściła własny wpis, który stoi w komórce, bo okres był zamknięty
    zostawione,         \* treści, przy których „Zostaw moją” wróciło do taty z widokiem bez różnicy
    \* liczniki
    zgasniecia, awarieIntermax, awariePamieci, awarieWyniku, awarieDecyzji,
    \* zdarzenia: zbiór przyczyn w chwili każdego zdarzenia, które łamie obietnicę
    nadpisane, falszywe, bezDecyzji, przeoczonaKopia

swiat == <<komorka, autor, wpis, okresOtwarty, kopia>>
plikPamieci == <<pamiec, pamiecCzeka, pamiecOdlozona>>
plikWyniku == <<wynik, wynikCzeka, wynikOdlozony>>
plikDecyzji == <<decyzje, decyzjeCzeka, decyzjeOdlozone>>
klik == <<faza, migPamiec, migDecyzje, kopiaPrzySprawdzaniu, planPamiec, planRoznica, planZapisal, planFalszywa,
          planPrzyczyny, planZapomina>>
karty == <<etap, tresc, odczyt, blokada>>
duchy == <<ostatniWlasny, zapomniala, zapomnialaCzeka, utrataPamieci, bezPamieci, upuszczona, zostawione>>
liczniki == <<zgasniecia, awarieIntermax, awariePamieci, awarieWyniku, awarieDecyzji>>
zdarzenia == <<nadpisane, falszywe, bezDecyzji, przeoczonaKopia>>
vars == <<swiat, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy, liczniki, zdarzenia>>

\* _TextFile.text: treść odłożona wygrywa, dopóki plik jest niedostępny, inaczej treść z dysku.
PamiecEfektywna == IF pamiecCzeka THEN pamiecOdlozona ELSE pamiec
PokazanaRoznica == IF wynikCzeka THEN wynikOdlozony ELSE wynik
DecyzjeWidoku == IF decyzjeCzeka THEN decyzjeOdlozone ELSE decyzje
\* Pamięć, którą ta praca Centrum ma za właściwą: policzona przez kliknięcie po zapisie INTERMAX, a przed save_memory,
\* inaczej treść odłożona albo plik.
PamiecWlasciwa == IF faza = "zapisane" THEN planPamiec ELSE PamiecEfektywna

TypeOK ==
    /\ komorka \in Komorki /\ autor \in {"nikt", "narzedzie", "tata"} /\ wpis \in Pamieci
    /\ okresOtwarty \in BOOLEAN /\ kopia \in BOOLEAN
    /\ pamiec \in Pamieci /\ pamiecCzeka \in BOOLEAN /\ pamiecOdlozona \in Pamieci
    /\ wynik \in Pamieci /\ wynikCzeka \in BOOLEAN /\ wynikOdlozony \in Pamieci
    /\ decyzje \subseteq Wpisy /\ decyzjeCzeka \in BOOLEAN /\ decyzjeOdlozone \subseteq Wpisy
    /\ faza \in Fazy /\ migPamiec \in Pamieci /\ migDecyzje \subseteq Wpisy /\ kopiaPrzySprawdzaniu \in BOOLEAN
    /\ planPamiec \in Pamieci /\ planRoznica \in Pamieci /\ planZapisal \in BOOLEAN /\ planFalszywa \in BOOLEAN
    /\ planPrzyczyny \subseteq Przyczyny /\ planZapomina \in BOOLEAN
    /\ etap \in [KartyZ -> Etapy] /\ tresc \in [KartyZ -> Pamieci] /\ odczyt \in [KartyZ -> SUBSET Wpisy]
    /\ blokada \in 0..Karty
    /\ ostatniWlasny \in Pamieci /\ zapomniala \in BOOLEAN /\ zapomnialaCzeka \in BOOLEAN
    /\ utrataPamieci \in BOOLEAN /\ bezPamieci \subseteq Przyczyny /\ upuszczona \in BOOLEAN /\ zostawione \subseteq Wpisy
    /\ zgasniecia \in 0..MaxZgasniec /\ awarieIntermax \in 0..MaxAwariiIntermax /\ awariePamieci \in 0..MaxAwariiPamieci
    /\ awarieWyniku \in 0..MaxAwariiWyniku /\ awarieDecyzji \in 0..MaxAwariiDecyzji
    /\ nadpisane \subseteq SUBSET Przyczyny /\ falszywe \subseteq SUBSET Przyczyny
    /\ bezDecyzji \subseteq Przyczyny /\ przeoczonaKopia \subseteq SUBSET Przyczyny

\* Kliknięcie bez planu: Uruchomienie się skończyło albo jeszcze nie przeczytało plików.
KlikWolny ==
    /\ faza' = "wolne" /\ migPamiec' = Brak /\ migDecyzje' = {} /\ kopiaPrzySprawdzaniu' = FALSE
    /\ planPamiec' = Brak /\ planRoznica' = Brak /\ planZapisal' = FALSE /\ planFalszywa' = FALSE
    /\ planPrzyczyny' = {} /\ planZapomina' = FALSE

Init ==
    /\ komorka = Pusta /\ autor = "nikt" /\ wpis = Brak /\ okresOtwarty = TRUE /\ kopia = FALSE
    /\ pamiec = Brak /\ pamiecCzeka = FALSE /\ pamiecOdlozona = Brak
    /\ wynik = Brak /\ wynikCzeka = FALSE /\ wynikOdlozony = Brak
    /\ decyzje = {} /\ decyzjeCzeka = FALSE /\ decyzjeOdlozone = {}
    /\ faza = "wolne" /\ migPamiec = Brak /\ migDecyzje = {} /\ kopiaPrzySprawdzaniu = FALSE
    /\ planPamiec = Brak /\ planRoznica = Brak /\ planZapisal = FALSE /\ planFalszywa = FALSE
    /\ planPrzyczyny = {} /\ planZapomina = FALSE
    /\ etap = [k \in KartyZ |-> "nic"] /\ tresc = [k \in KartyZ |-> Brak] /\ odczyt = [k \in KartyZ |-> {}]
    /\ blokada = 0
    /\ ostatniWlasny = Brak /\ zapomniala = FALSE /\ zapomnialaCzeka = FALSE /\ utrataPamieci = FALSE
    /\ bezPamieci = {} /\ upuszczona = FALSE /\ zostawione = {}
    /\ zgasniecia = 0 /\ awarieIntermax = 0 /\ awariePamieci = 0 /\ awarieWyniku = 0 /\ awarieDecyzji = 0
    /\ nadpisane = {} /\ falszywe = {} /\ bezDecyzji = {} /\ przeoczonaKopia = {}

(* Reguły jednej komórki z worker_reports/_cells.py reconcile na migawce kliknięcia (pamięć migPamiec, decyzje    *)
(* migDecyzje) i INTERMAX z odczytu. Zlecenie z dnia zamkniętego okresu nie wchodzi do orders (enter_reports:        *)
(* window.opens), więc nie dostaje Wpisu ani różnicy, a pamięć je upuszcza (own: wartość musi być w current).       *)
\* `if value is None or (cell is not None and normalize_text(cell) == normalize_text(value)): continue`
BezZmian == ~okresOtwarty \/ wpis = Brak \/ (komorka # Pusta /\ komorka = wpis)
\* `if cell is None or cell == remembered.get((order.key, column))`: Wpis do pustej komórki albo własnego wpisu
Zmiana == IF ~BezZmian /\ (komorka = Pusta \/ komorka = migPamiec) THEN wpis ELSE Brak
\* `elif Kept(order.key, column, value) not in kept`: ManualDifference
Roznica == IF ~BezZmian /\ Zmiana = Brak /\ wpis \notin migDecyzje THEN wpis ELSE Brak
\* `own = {cell: value for cell, value in remembered.items() if value in current[cell]}`, potem `own[...] = value`
NowaPamiec ==
    IF Zmiana # Brak THEN Zmiana
    ELSE IF okresOtwarty /\ migPamiec # Brak /\ migPamiec = komorka THEN migPamiec
    ELSE Brak

(* Tata albo jego pracownik (przez OneDrive) zmienia komórkę w Excelu i zapisuje INTERMAX, także na pustą.        *)
TataZmienia(v) ==
    /\ v \in Komorki /\ v # komorka
    /\ komorka' = v
    /\ autor' = IF v = Pusta THEN "nikt" ELSE "tata"
    /\ upuszczona' = FALSE
    /\ UNCHANGED <<wpis, okresOtwarty, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, ostatniWlasny,
                   zapomniala, zapomnialaCzeka, utrataPamieci, bezPamieci, zostawione, liczniki, zdarzenia>>

(* Wykonawca przysyła Raport wykonawcy z nową treścią Wpisu dla tego zlecenia (najpóźniejszy mail wygrywa).         *)
NowyMail(w) ==
    /\ w \in Wpisy /\ w # wpis
    /\ wpis' = w
    /\ UNCHANGED <<komorka, autor, okresOtwarty, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy,
                   liczniki, zdarzenia>>

(* Przygotowanie tworzy Plik zbiorczy okresu: okres jest dla Wpisania raportów zamknięty (_closed).              *)
ZamkniecieOkresu ==
    /\ okresOtwarty /\ okresOtwarty' = FALSE
    /\ UNCHANGED <<komorka, autor, wpis, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy, liczniki,
                   zdarzenia>>

(* Tata usuwa Plik zbiorczy (na przykład przed Przygotowaniem od nowa): okres znów jest otwarty.                   *)
OtwarcieOkresu ==
    /\ MozeOtworzyc /\ ~okresOtwarty /\ okresOtwarty' = TRUE
    /\ UNCHANGED <<komorka, autor, wpis, kopia, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy, liczniki,
                   zdarzenia>>

(* OneDrive kładzie obok INTERMAX kopię konfliktu (zmiana pracownika i podmiana narzędzia naraz).                  *)
PojawiaSieKopia ==
    /\ MozeKopia /\ ~kopia /\ kopia' = TRUE
    /\ UNCHANGED <<komorka, autor, wpis, okresOtwarty, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy,
                   liczniki, zdarzenia>>

(* Tata scala kopię konfliktu z INTERMAX i ją usuwa; to, co przepisze, to jego zmiany komórki (TataZmienia).         *)
TataUsuwaKopie ==
    /\ kopia /\ kopia' = FALSE
    /\ UNCHANGED <<komorka, autor, wpis, okresOtwarty, plikPamieci, plikWyniku, plikDecyzji, klik, karty, duchy,
                   liczniki, zdarzenia>>

(* Tata klika „Wpisz raporty z maili”; enter_from_mail, faza Sprawdzanie (check): ReportState.load, czyli            *)
(* FileReportState.load: _TextFile.text pamięci (StateFile.retry odłożonej treści, potem ona albo plik), potem kept() *)
(* tak samo dla decyzji, a dalej onedrive_conflicts.beside (report_entering.py :265): kopia konfliktu to Zatrzymanie, *)
(* zanim proces przeczyta skrzynkę.                                                                                 *)
Sprawdzanie ==
    /\ faza = "wolne"
    /\ \E p \in Ponowienia(pamiecCzeka), d \in Ponowienia(decyzjeCzeka) :
        /\ pamiec' = IF p = "udany" THEN pamiecOdlozona ELSE pamiec
        /\ pamiecCzeka' = (p = "nieudany")
        /\ pamiecOdlozona' = IF p = "nieudany" THEN pamiecOdlozona ELSE Brak
        /\ zapomniala' = IF p = "udany" THEN zapomniala \/ zapomnialaCzeka ELSE zapomniala
        /\ zapomnialaCzeka' = (p = "nieudany" /\ zapomnialaCzeka)
        /\ decyzje' = IF d = "udany" THEN decyzjeOdlozone ELSE decyzje
        /\ decyzjeCzeka' = (d = "nieudany")
        /\ decyzjeOdlozone' = IF d = "nieudany" THEN decyzjeOdlozone ELSE {}
        /\ LET zatrzymanie == kopia IN
           IF zatrzymanie
           THEN KlikWolny
           ELSE /\ faza' = "sprawdzone"
                /\ migPamiec' = PamiecEfektywna
                /\ migDecyzje' = DecyzjeWidoku
                /\ kopiaPrzySprawdzaniu' = kopia
                /\ UNCHANGED <<planPamiec, planRoznica, planZapisal, planFalszywa, planPrzyczyny, planZapomina>>
    /\ UNCHANGED <<swiat, plikWyniku, karty, ostatniWlasny, utrataPamieci, bezPamieci, upuszczona, zostawione,
                   liczniki, zdarzenia>>

\* Nadpisana ręczna wartość: przyczyny z historii, nie z kodu. Tata przywrócił wartość, którą narzędzie samo wpisało
\* ostatnio, a żadne kliknięcie, którego pamięć przetrwała, nie widziało komórki bez niej (pamięć porównuje wartości,
\* nie autora), albo wpisał wartość po zgaśnięciu, które zgubiło nowszą pamięć (wartości komórki to w modelu tylko
\* treści Wpisów, więc każda jest albo może być dawną wartością narzędzia).
PrzyczynaNadpisania ==
    IF komorka = ostatniWlasny /\ ~zapomniala /\ ~zapomnialaCzeka /\ ~utrataPamieci THEN {"przywrocona-wartosc"}
    ELSE IF utrataPamieci THEN {"przywrocona-ze-starej-pamieci"}
    ELSE {}

(* Odczyt danych (skrzynka, INTERMAX), Planowanie (enter_reports: _cells.reconcile) i Zapisywanie (write_cells,     *)
(* report_entering.py :340) jako jeden krok: okno między odczytem INTERMAX a podmianą to znane znalezisko 1 skilla    *)
(* verify-zapis-intermax. Bez zmian write_cells zwraca CellsWritten(0) bez podmiany; odmowa (Refusal, Rejected) to   *)
(* Zatrzymanie z INTERMAX nietkniętym i bez zapisu pamięci ani wyniku.                                              *)
Zapis ==
    /\ faza = "sprawdzone"
    /\ LET zmiana == Zmiana
           roznica == Roznica
       IN \/ /\ zmiana # Brak /\ awarieIntermax < MaxAwariiIntermax
             /\ awarieIntermax' = awarieIntermax + 1
             /\ KlikWolny
             /\ UNCHANGED <<swiat, duchy, zgasniecia, awariePamieci, awarieWyniku, awarieDecyzji, zdarzenia>>
          \/ /\ faza' = "zapisane"
             /\ komorka' = IF zmiana = Brak THEN komorka ELSE zmiana
             /\ autor' = IF zmiana = Brak THEN autor ELSE "narzedzie"
             /\ ostatniWlasny' = IF zmiana = Brak THEN ostatniWlasny ELSE zmiana
             /\ planPamiec' = NowaPamiec
             /\ planRoznica' = roznica
             /\ planZapisal' = (zmiana # Brak)
             /\ planZapomina' = (zmiana = Brak /\ okresOtwarty /\ ostatniWlasny # Brak /\ komorka # ostatniWlasny)
             /\ planFalszywa' = (roznica # Brak /\ autor = "narzedzie")
             /\ planPrzyczyny' = bezPamieci \cup (IF upuszczona THEN {"okres-otwarty-ponownie"} ELSE {})
             /\ zapomniala' = IF zmiana = Brak THEN zapomniala ELSE FALSE
             /\ zapomnialaCzeka' = IF zmiana = Brak THEN zapomnialaCzeka ELSE FALSE
             /\ bezPamieci' = IF zmiana = Brak THEN bezPamieci ELSE {}
             /\ utrataPamieci' = IF zmiana = Brak THEN utrataPamieci ELSE FALSE
             /\ upuszczona' =
                    IF zmiana # Brak THEN FALSE
                    ELSE upuszczona \/ (~okresOtwarty /\ autor = "narzedzie" /\ migPamiec = komorka)
             /\ nadpisane' = nadpisane \cup (IF zmiana # Brak /\ autor = "tata" THEN {PrzyczynaNadpisania} ELSE {})
             /\ przeoczonaKopia' = przeoczonaKopia \cup (IF kopiaPrzySprawdzaniu THEN {{"przy-sprawdzaniu"}} ELSE {})
             \* migawka kliknięcia jest potrzebna tylko w planie, więc dalej jej nie ma
             /\ migPamiec' = Brak /\ migDecyzje' = {} /\ kopiaPrzySprawdzaniu' = FALSE
             /\ UNCHANGED <<wpis, okresOtwarty, kopia, zostawione, liczniki, falszywe, bezDecyzji>>
    /\ UNCHANGED <<plikPamieci, plikWyniku, plikDecyzji, karty>>

(* report_entering.py :353: parts.state.save_memory po udanym zapisie INTERMAX, także przy zerze wpisanych komórek: *)
(* FileReportState.save_memory → _TextFile.write → StateFile.write; OSError zostawia treść odłożoną w pamięci, a     *)
(* proces daje tylko ostrzeżenie (memory_not_saved) i idzie dalej.                                                 *)
ZapiszPamiec ==
    /\ faza = "zapisane"
    /\ faza' = "pamiec"
    /\ \E z \in Zapisy :
        /\ MozeZawiesc(z, pamiecCzeka, awariePamieci, MaxAwariiPamieci)
        /\ awariePamieci' = awariePamieci + Nieudane(z, pamiecCzeka)
        /\ IF z = "udany"
           THEN /\ pamiec' = planPamiec /\ pamiecCzeka' = FALSE /\ pamiecOdlozona' = Brak
                /\ zapomniala' = (zapomniala \/ zapomnialaCzeka \/ planZapomina) /\ zapomnialaCzeka' = FALSE
           ELSE /\ pamiecCzeka' = TRUE /\ pamiecOdlozona' = planPamiec /\ UNCHANGED pamiec
                /\ zapomnialaCzeka' = (zapomnialaCzeka \/ planZapomina) /\ UNCHANGED zapomniala
    /\ UNCHANGED <<swiat, plikWyniku, plikDecyzji, migPamiec, migDecyzje, kopiaPrzySprawdzaniu, planPamiec, planRoznica,
                   planZapisal, planFalszywa, planPrzyczyny, planZapomina, karty, ostatniWlasny, utrataPamieci,
                   bezPamieci, upuszczona, zostawione, zgasniecia, awarieIntermax, awarieWyniku, awarieDecyzji,
                   zdarzenia>>

(* report_entering.py :354: parts.state.save_result (ClickResult z problemami, w nich ManualDifference) →          *)
(* _TextFile.write; OSError zostawia treść odłożoną, a widok pokazuje ją z pamięci. Zaraz potem, w tym samym kroku,  *)
(* :356 onedrive_conflicts.beside: kopia konfliktu to Zatrzymanie dla taty (conflict_after_save) z podsumowaniem,   *)
(* bez niej podsumowanie, i Uruchomienie się kończy. Jeden krok, bo między nimi nic nie pisze plików ani INTERMAX:    *)
(* zgaśnięcie tam gubi tylko to, co gubi zgaśnięcie po końcu, a kopia, która pojawi się tam, pojawia się przed nim.   *)
ZapiszWynik ==
    /\ faza = "pamiec"
    /\ \E z \in Zapisy :
        /\ MozeZawiesc(z, wynikCzeka, awarieWyniku, MaxAwariiWyniku)
        /\ awarieWyniku' = awarieWyniku + Nieudane(z, wynikCzeka)
        /\ IF z = "udany"
           THEN wynik' = planRoznica /\ wynikCzeka' = FALSE /\ wynikOdlozony' = Brak
           ELSE wynikCzeka' = TRUE /\ wynikOdlozony' = planRoznica /\ UNCHANGED wynik
    /\ falszywe' = falszywe \cup (IF planFalszywa THEN {planPrzyczyny} ELSE {})
    /\ LET zatrzymanie == kopia IN
       przeoczonaKopia' = przeoczonaKopia \cup (IF ~zatrzymanie /\ kopia THEN {{"po-zapisie"}} ELSE {})
    /\ KlikWolny
    /\ UNCHANGED <<swiat, plikPamieci, plikDecyzji, karty, duchy, zgasniecia, awarieIntermax, awariePamieci,
                   awarieDecyzji, nadpisane, bezDecyzji>>

(* Karta odświeża widok Raporty (ReportEnteringEntry.view → FileReportState.shown i kept): _TextFile.text każdego    *)
(* z dwóch plików najpierw ponawia odłożony zapis (StateFile.retry).                                               *)
Odswiez ==
    /\ wynikCzeka \/ decyzjeCzeka
    /\ \E w \in Ponowienia(wynikCzeka), d \in Ponowienia(decyzjeCzeka) :
        /\ wynik' = IF w = "udany" THEN wynikOdlozony ELSE wynik
        /\ wynikCzeka' = (w = "nieudany")
        /\ wynikOdlozony' = IF w = "nieudany" THEN wynikOdlozony ELSE Brak
        /\ decyzje' = IF d = "udany" THEN decyzjeOdlozone ELSE decyzje
        /\ decyzjeCzeka' = (d = "nieudany")
        /\ decyzjeOdlozone' = IF d = "nieudany" THEN decyzjeOdlozone ELSE {}
    /\ UNCHANGED <<swiat, plikPamieci, klik, karty, duchy, liczniki, zdarzenia>>

(* Tata klika „Zostaw moją” na karcie k: ReportEnteringEntry.keep sprawdza files.shown() poza blokadą               *)
(* (report_entering_run.py :125-129): różnica z tą treścią jest w wyniku ostatniego kliknięcia, inaczej             *)
(* difference_gone.                                                                                                *)
ZostawSprawdz(k) ==
    /\ etap[k] = "nic" /\ PokazanaRoznica # Brak
    /\ etap' = [etap EXCEPT ![k] = "sprawdzona"]
    /\ tresc' = [tresc EXCEPT ![k] = PokazanaRoznica]
    /\ UNCHANGED <<swiat, plikPamieci, plikWyniku, plikDecyzji, klik, odczyt, blokada, duchy, liczniki, zdarzenia>>

(* FileReportState.keep pod blokadą _deciding (report_entering_state.py :362-363): kept(), czyli dawne decyzje.      *)
ZostawCzytaj(k) ==
    /\ etap[k] = "sprawdzona"
    /\ blokada = 0
    /\ blokada' = k
    /\ etap' = [etap EXCEPT ![k] = "czyta"]
    /\ odczyt' = [odczyt EXCEPT ![k] = DecyzjeWidoku]
    /\ UNCHANGED <<swiat, plikPamieci, plikWyniku, plikDecyzji, klik, tresc, duchy, liczniki, zdarzenia>>

(* Dalej pod tą samą blokadą (:364-366): decisions.write dawnych decyzji z nową; keep nie patrzy na wynik zapisu, więc *)
(* tata dostaje widok bez różnicy także wtedy, gdy decyzja tylko czeka w pamięci.                                   *)
ZostawZapisz(k) ==
    /\ etap[k] = "czyta"
    /\ blokada' = 0
    /\ etap' = [etap EXCEPT ![k] = "nic"]
    /\ LET nowe == odczyt[k] \cup {tresc[k]} IN
       /\ \E z \in Zapisy :
           /\ MozeZawiesc(z, decyzjeCzeka, awarieDecyzji, MaxAwariiDecyzji)
           /\ awarieDecyzji' = awarieDecyzji + Nieudane(z, decyzjeCzeka)
           /\ IF z = "udany"
              THEN decyzje' = nowe /\ decyzjeCzeka' = FALSE /\ decyzjeOdlozone' = {}
              ELSE decyzjeCzeka' = TRUE /\ decyzjeOdlozone' = nowe /\ UNCHANGED decyzje
       /\ zostawione' = zostawione \cup {tresc[k]}
       /\ bezDecyzji' = IF zostawione \cup {tresc[k]} \subseteq nowe THEN {} ELSE bezDecyzji
    /\ UNCHANGED <<swiat, plikPamieci, plikWyniku, klik, tresc, odczyt, ostatniWlasny, zapomniala,
                   zapomnialaCzeka, utrataPamieci, bezPamieci, upuszczona, zgasniecia, awarieIntermax, awariePamieci,
                   awarieWyniku, nadpisane, falszywe, przeoczonaKopia>>

(* Centrum gaśnie w dowolnym kroku i tata otwiera je od nowa: Uruchomienie i żądania „Zostaw moją” giną, treści        *)
(* odłożone w pamięci (StateFile._waiting, _TextFile._written) też, a pliki na dysku i INTERMAX zostają (zapis        *)
(* replace_atomically jest atomowy).                                                                                *)
Zgasniecie ==
    /\ zgasniecia < MaxZgasniec
    /\ zgasniecia' = zgasniecia + 1
    /\ KlikWolny
    \* na dysku zostaje plik, nie pamięć, którą ta praca policzyła albo odłożyła
    /\ pamiec' = pamiec /\ pamiecCzeka' = FALSE /\ pamiecOdlozona' = Brak
    /\ wynikCzeka' = FALSE /\ wynikOdlozony' = Brak
    /\ decyzjeCzeka' = FALSE /\ decyzjeOdlozone' = {}
    /\ etap' = [k \in KartyZ |-> "nic"] /\ tresc' = [k \in KartyZ |-> Brak] /\ odczyt' = [k \in KartyZ |-> {}]
    /\ blokada' = 0
    /\ zapomnialaCzeka' = FALSE
    /\ utrataPamieci' = (utrataPamieci \/ PamiecWlasciwa # pamiec')
    /\ bezPamieci' = bezPamieci
                     \cup (IF faza = "zapisane" /\ planZapisal THEN {"przed-pamiecia"} ELSE {})
                     \cup (IF pamiecCzeka /\ pamiecOdlozona = ostatniWlasny /\ pamiec # ostatniWlasny
                           THEN {"pamiec-odlozona"} ELSE {})
    /\ bezDecyzji' = bezDecyzji
                     \cup (IF decyzjeCzeka /\ (zostawione \cap decyzjeOdlozone) \ decyzje # {}
                           THEN {"decyzja-odlozona"} ELSE {})
    /\ UNCHANGED <<swiat, wynik, decyzje, ostatniWlasny, zapomniala, upuszczona, zostawione,
                   awarieIntermax, awariePamieci, awarieWyniku, awarieDecyzji, nadpisane, falszywe, przeoczonaKopia>>

Next ==
    \/ \E v \in Komorki : TataZmienia(v)
    \/ \E w \in Wpisy : NowyMail(w)
    \/ ZamkniecieOkresu \/ OtwarcieOkresu \/ PojawiaSieKopia \/ TataUsuwaKopie
    \/ Sprawdzanie \/ Zapis \/ ZapiszPamiec \/ ZapiszWynik \/ Odswiez
    \/ \E k \in KartyZ : ZostawSprawdz(k)
    \/ \E k \in KartyZ : ZostawCzytaj(k)
    \/ \E k \in KartyZ : ZostawZapisz(k)
    \/ Zgasniecie

Spec == Init /\ [][Next]_vars

(* Obietnice (ADR 0028, docstringi _cells.reconcile, report_entering.py i report_entering_run.py). *)
\* Wpis zmienia tylko pustą komórkę albo własny wpis narzędzia, którego nikt potem nie zmienił: nigdy wartości, którą
\* wpisał tata albo jego pracownik (ADR 0028: „pisze tylko do pustej komórki albo do własnego wcześniejszego wpisu,
\* którego nikt potem nie zmienił”).
NieNadpisuje == nadpisane = {}
\* „Zostaw moją” trwale ucisza różnicę z tą treścią Wpisu: widok Raporty (_view: problemy bez decyzji z kept) nie
\* pokazuje jej znowu, gdy tata dostał widok bez niej.
Widoczna == PokazanaRoznica # Brak /\ PokazanaRoznica \notin DecyzjeWidoku
ZostawUcisza == ~(Widoczna /\ PokazanaRoznica \in zostawione)
\* Różnica z ręczną wartością (ManualDifference) jest tylko przy wartości, którą wpisał tata albo jego pracownik, nigdy
\* przy własnym wpisie narzędzia.
BezFalszywejRoznicy == falszywe = {}
\* Kliknięcie nie czyta skrzynki, gdy obok INTERMAX leży kopia konfliktu OneDrive, a kopia, która pojawiła się do
\* końca zapisu, kończy je Zatrzymaniem dla taty, nie podsumowaniem.
KopiaZatrzymuje == przeoczonaKopia = {}

\* Wariant obietnicy, który pomija zdarzenie, gdy w jego chwili była przyczyna wybaczonego znaleziska.
Wybaczone(zdarzenie, wybaczone) == \A s \in zdarzenie : s \cap wybaczone # {}
NieNadpisujePozaZnanymi == Wybaczone(nadpisane, WybaczoneNieNadpisuje)
ZostawUciszaPozaZnanymi == ZostawUcisza \/ bezDecyzji \cap WybaczoneZostawUcisza # {}
BezFalszywejRoznicyPozaZnanymi == Wybaczone(falszywe, WybaczoneBezFalszywejRoznicy)
KopiaZatrzymujePozaZnanymi == Wybaczone(przeoczonaKopia, WybaczoneKopiaZatrzymuje)
=========================================================================================================================
