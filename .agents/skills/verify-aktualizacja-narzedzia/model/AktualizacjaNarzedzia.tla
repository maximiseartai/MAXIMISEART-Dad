------------------------- MODULE AktualizacjaNarzedzia -------------------------
(***************************************************************************)
(* Aktualizacja narzędzia z Centrum rozliczeń (ADR 0009) przy każdej       *)
(* kolejności awarii.                                                      *)
(*                                                                         *)
(* Obietnica: gdy aktualizacja się skończy, przerwie albo komputer zgaśnie, *)
(* klon narzędzia stoi na wersji, która wystartuje ze skrótu taty, a plik  *)
(* taty w config/ (dziś worker_mapping.yaml) ma treść taty. Albo zostaje   *)
(* dziennik „Aktualizacja w toku” z treścią taty, a skrót przy następnym   *)
(* starcie albo następne kliknięcie cofa z niego klon (Postep).            *)
(*                                                                         *)
(* Jedna akcja to jeden krok kodu, który kończy się, zanim zacznie się     *)
(* następny: jedno polecenie Gita, jedno shutil.copy2, jedno uruchomienie  *)
(* pip, jeden proces opiekuna. Komentarz przy akcji wskazuje ten kod w     *)
(* src/rozliczenia/centrum/: tool_update.py, tool_updates.py,              *)
(* restart_guardian.py (z cofaniem nowej wersji, która nie wystartuje),   *)
(* launcher.py (cofanie przerwanej aktualizacji przy starcie skrótu).      *)
(*                                                                         *)
(* Druga obietnica (OpiekunCofaTylkoNieudana): opiekun cofa nową wersję    *)
(* tylko wtedy, gdy ona naprawdę nie startuje, także gdy tata w trakcie    *)
(* ponownego startu kliknie skrót na pulpicie.                             *)
(*                                                                         *)
(* Trzecia obietnica (OkienkoTylkoGdyNicNieDziala): opiekun pokazuje       *)
(* okienko „nie wystartowało” tylko wtedy, gdy żadne Centrum nie działa.  *)
(*                                                                         *)
(* Czwarta (TataNieZostajeBezOdpowiedzi): gdy nic już nie działa, tata     *)
(* widzi okienko albo zgaszony komputer, nigdy samą martwą kartę. Piąta    *)
(* (KartaNieKlamie): karta mówi „zaktualizowano” tylko w nowej wersji.     *)
(* Szósta (KartaNieStraszy): karta nowej wersji nie mówi o porażce.        *)
(* Trzy ostatnie opisują plik wyniku (write_result, read_result) i kartę   *)
(* po starcie Centrum (ToolUpdates._after_restart).                        *)
(***************************************************************************)
EXTENDS Naturals, Sequences

CONSTANTS
    MaxKlikniec,        \* ile razy tata klika „Zaktualizuj narzędzie”
    OdmowaScalenia,     \* merge --ff-only odmawia przed zmianą czegokolwiek -> ZMIANY_NA_KOMPUTERZE
    AwariaPobrania,     \* _Git.fetch: brak sieci albo logowanie -> BRAK_POLACZENIA, LOGOWANIE
    AwariaBibliotek,    \* pip_install zwraca False (błąd pip, limit czasu) -> INSTALACJA_BIBLIOTEK
    AwariaOpiekuna,     \* restart_guardian.launch rzuca; stare Centrum nie zwalnia portu w PORT_TIMEOUT_S
    AwariaGita,         \* git checkout HEAD -- (set_aside) z kodem różnym od 0: _NotSetAside; git diff (changed),
                        \* rev-parse HEAD i git reset --keep (_roll_back): GitFailed;
                        \* każde polecenie Gita także po limicie czasu albo z OSError z _run_tree (_Git.run:
                        \* TimeoutExpired; OSError, gdy zadanie Windows nie powstanie albo drzewo przeżyje
                        \* _KILL_TIMEOUT_S): git checkout HEAD --, git merge --ff-only, git diff (changed), rev-parse
                        \* HEAD i git reset --keep w _roll_back
    AwariaKopiowania,   \* OSError z dysku (dysk, antywirus, OneDrive): shutil.copy2 pliku taty, zapis stan.json (także
                        \* terminu opiekuna), zapis pliku wyniku (write_result) albo jego usunięcie, usunięcie pliku
                        \* taty z klonu w _roll_back
    NieudanyStart,      \* nowa wersja nie odpowiada w START_TIMEOUT_S, choć ma swoje biblioteki
    Wylaczenie,         \* komputer gaśnie albo proces ginie w dowolnym kroku
    MaxSkrotowWTrakcie, \* ile razy tata klika skrót na pulpicie, gdy opiekun ponownego startu działa
    \* Przyczyny znanych znalezisk, które wariant ...PozaZnanymi danej obietnicy pomija (skrypt skilla je ustawia).
    WybaczoneTataMaDzialajacaWersje, WybaczoneOpiekunCofaTylkoNieudana, WybaczoneOkienkoTylkoGdyNicNieDziala,
    WybaczoneTataNieZostajeBezOdpowiedzi, WybaczoneKartaNieKlamie, WybaczoneKartaNieStraszy, WybaczonePostep

VARIABLES
    \* Dysk taty: przeżywa zamknięcie Centrum i wyłączenie komputera.
    head,          \* commit klonu: "stara" (sprzed kliknięcia) albo "nowa" (najnowsze Wydanie)
    plikTaty,      \* config/worker_mapping.yaml w klonie: "taty", "wzor" (treść z HEAD repozytorium) albo "brak"
    kopia,         \* kopia pliku taty w dzienniku (centrum-aktualizacja-w-toku/pliki-taty): "brak" albo "taty"
    biblioteki,    \* biblioteki Pythona taty: "stare", "czesciowe" (pip przerwany albo nieudany), "nowe"
    dziennik,      \* dziennik „Aktualizacja w toku” (stan.json): "brak" albo "w_toku"
    dzierzawa,     \* opiekun_do w stan.json: "wazna", dopóki opiekun ponownego startu może działać, albo "brak"
    \* Nowa wersja: wybrana raz na początku, potem stała.
    nowaUsuwaPlikTaty,     \* nowa wersja usuwa albo przestaje śledzić plik taty (_DadFiles.leaving go znajduje)
    nowaZmieniaWymagania,  \* nowa wersja zmienia requirements.txt (_Git.changed)
    nowaStartuje,          \* nowa wersja odpowiada na /api/health, gdy ma swoje biblioteki
    \* Procesy.
    centrum,       \* wersja działającego Centrum: "stara", "nowa" albo "brak"
    pc,            \* krok aktualizacji; "spoczynek", gdy żadna nie trwa
    klikniecia,
    krok,          \* ostatni krok, słowami kodu: z nich składa się kontrprzykład
    slady,         \* awarie znanych znalezisk, które już się zdarzyły (ZnaneZnaleziska)
    skrot,         \* skrót kliknięty w trakcie pracy opiekuna: "ma_port" od listen_locally do listener.close(), inaczej "brak"
    skrotyWTrakcie,\* ile razy tata kliknął skrót, gdy opiekun działał
    cofa,          \* kto woła _roll_back: "centrum" (ToolClone.update, ToolUpdates._moved_back), "klik"
                   \* (ToolClone.update przed pobraniem, gdy zastaje dziennik bez terminu opiekuna), "opiekun"
                   \* (restart_guardian._rolled_back po nowej wersji, która nie odpowiada) albo "opiekun_bez_portu"
                   \* (restart_guardian._rolled_back, gdy port nie został zwolniony; potem jak po "opiekun")
                   \* albo "skrot" (launcher._roll_back przy starcie); po odmowie scalenia "centrum"
    \* Plik wyniku i to, co tata widzi.
    wynik,         \* config/centrum-aktualizacja.json (write_result): "brak", "ok" (UPDATED) albo "porazka" (każdy inny kod)
    karta,         \* co karta działającego Centrum mówi z pliku wyniku (ToolUpdates._after_restart): "nic",
                   \* "zaktualizowano" albo "porazka"; wyniki, które Centrum ma samo, model pomija
    widzi          \* co tata ma przed sobą: "centrum", "nic" (Centrum zamknięte, nic nie wystartowało), "okienko"
                   \* (natywne okienko z Komunikatem startu) albo "wylaczony" (komputer zgasł)

dysk == <<head, plikTaty, kopia, biblioteki, dziennik, dzierzawa>>
nowa == <<nowaUsuwaPlikTaty, nowaZmieniaWymagania, nowaStartuje>>
ekran == <<wynik, karta, widzi>>
vars == <<dysk, nowa, centrum, pc, klikniecia, krok, slady, cofa, skrot, skrotyWTrakcie, ekran>>

\* Znane znaleziska (SKILL.md, model/konfiguracje.json): krok awarii, po którym obietnica pada. Dziś żadnego:
\* ok_po_dwoch_odmowach i skrot_gasnie_przed_wynikiem zamknęło porównanie „po” z działającą wersją (#490).
ZnaneZnaleziska == {}

Kroki == {"spoczynek", "pobieranie", "kopia_plikow", "checkout_head", "scalanie",
          "przywrocenie_po_odmowie", "przywrocenie_po_scaleniu", "instalacja",
          "przywrocenie_po_wyjatku", "instalacja_trwa", "cofanie_usun", "cofanie_reset",
          "cofanie_przywroc", "cofanie_przywroc_po_bledzie", "koniec_dziennika", "skrot_wynik", "restart", "opiekun_port",
          "opiekun_start", "opiekun_koniec", "opiekun_wycofanie", "opiekun_wynik",
          "opiekun_port_stara", "opiekun_start_stara", "okienko"}

TypeOK ==
    /\ head \in {"stara", "nowa"}
    /\ plikTaty \in {"taty", "wzor", "brak"}
    /\ kopia \in {"brak", "taty"}
    /\ biblioteki \in {"stare", "czesciowe", "nowe"}
    /\ dziennik \in {"brak", "w_toku"}
    /\ dzierzawa \in {"brak", "wazna"}
    /\ nowa \in BOOLEAN \X BOOLEAN \X BOOLEAN
    /\ centrum \in {"stara", "nowa", "brak"}
    /\ pc \in Kroki
    /\ klikniecia \in 0..MaxKlikniec
    /\ slady \subseteq ZnaneZnaleziska
    /\ cofa \in {"centrum", "klik", "opiekun", "opiekun_bez_portu", "skrot"}
    /\ skrot \in {"brak", "ma_port"}
    /\ skrotyWTrakcie \in 0..MaxSkrotowWTrakcie
    /\ wynik \in {"brak", "ok", "porazka"}
    /\ karta \in {"nic", "zaktualizowano", "porazka"}
    /\ widzi \in {"centrum", "nic", "okienko", "wylaczony"}

\* Czy wersja wystartuje ze skrótu taty (run_centrum.py z klonu). Założenie: stara
\* wersja startuje z każdymi bibliotekami, bo requirements.txt ma dolne granice
\* wersji, a jedynej górnej (Playwright <1.65, #1242) Centrum przy starcie nie
\* sprawdza (docstring tool_update.py), więc pip nowej wersji jej nie psuje.
Startuje(wersja) ==
    \/ wersja = "stara"
    \/ /\ nowaStartuje
       /\ (~nowaZmieniaWymagania \/ biblioteki = "nowe")

\* --- Obietnica --------------------------------------------------------------

\* Treść taty jest na dysku: w klonie albo w kopii w dzienniku. Bez kopii (nowa wersja
\* nie usuwa pliku taty) cofanie go nie dotyka, więc wystarcza ten w klonie.
TrescTatyNaDysku == plikTaty = "taty" \/ kopia = "taty"

TataMaDzialajacaWersje ==
    pc = "spoczynek" =>
        \/ Startuje(head) /\ plikTaty = "taty"
        \/ dziennik = "w_toku" /\ TrescTatyNaDysku

\* Znane znalezisko obietnicy: przebieg, w którym zdarzyła się awaria z jej stałej Wybaczone... Każde
\* inne złamanie obietnicy zostaje naruszeniem, więc znane znalezisko nie zasłania nowego.
Po(wybaczone) == wybaczone \cap slady /= {}

TataMaDzialajacaWersjePozaZnanymi == TataMaDzialajacaWersje \/ Po(WybaczoneTataMaDzialajacaWersje)

\* Opiekun cofa klon (cofa = "opiekun") tylko wtedy, gdy wersja, na której klon stoi,
\* naprawdę nie wystartuje. Sprawdzane w chwili wejścia w _roll_back, zanim klon się ruszy.
OpiekunCofaTylkoNieudana ==
    pc = "cofanie_usun" /\ cofa = "opiekun" => ~Startuje(head)

OpiekunCofaTylkoNieudanaPozaZnanymi == OpiekunCofaTylkoNieudana \/ Po(WybaczoneOpiekunCofaTylkoNieudana)

\* Opiekun pokazuje okienko not_started_after_update (pc = "okienko") tylko wtedy, gdy żadne
\* Centrum nie działa: okienko przy starej wersji ze skrótu to fałszywy alarm (#368), także po
\* cofnięciu bez zwolnionego portu (#726).
OkienkoTylkoGdyNicNieDziala ==
    pc = "okienko" => centrum = "brak"

OkienkoTylkoGdyNicNieDzialaPozaZnanymi == OkienkoTylkoGdyNicNieDziala \/ Po(WybaczoneOkienkoTylkoGdyNicNieDziala)

\* Gdy nic już nie działa (żadna aktualizacja ani opiekun, żadne Centrum), tata widzi okienko z
\* Komunikatem albo zgaszony komputer, nigdy samą martwą kartę. Docstring restart_guardian.py
\* i komentarz w main: „Karta nie ma już z kim rozmawiać: jedno okienko zamiast ciszy”.
TataNieZostajeBezOdpowiedzi ==
    pc = "spoczynek" /\ centrum = "brak" => widzi \in {"okienko", "wylaczony"}

TataNieZostajeBezOdpowiedziPozaZnanymi == TataNieZostajeBezOdpowiedzi \/ Po(WybaczoneTataNieZostajeBezOdpowiedzi)

\* Karta mówi „Narzędzie zaktualizowane” tylko wtedy, gdy Centrum działa w nowej wersji; inaczej
\* Maks nie dostaje Zgłoszenia o wersji, która u taty nie startuje. Docstring launcher._roll_back:
\* plik wyniku mógł już mówić „ok”, a karta cofniętej wersji ma pokazać porażkę.
KartaNieKlamie ==
    karta = "zaktualizowano" => centrum = "nowa"

KartaNieKlamiePozaZnanymi == KartaNieKlamie \/ Po(WybaczoneKartaNieKlamie)

\* Karta nowej, działającej wersji nie mówi o porażce aktualizacji: porażka z pliku wyniku dotyczy
\* wersji sprzed aktualizacji, do której klon cofnięto, a w nowej jest stara (#725). Inaczej tata
\* wysyła Maksowi Zgłoszenie o wersji, która startuje.
KartaNieStraszy ==
    karta = "porazka" => centrum /= "nowa"

KartaNieStraszyPozaZnanymi == KartaNieStraszy \/ Po(WybaczoneKartaNieStraszy)


\* --- Start ------------------------------------------------------------------

Init ==
    /\ head = "stara"
    /\ plikTaty = "taty"
    /\ kopia = "brak"
    /\ biblioteki = "stare"
    /\ dziennik = "brak"
    /\ dzierzawa = "brak"
    /\ nowaUsuwaPlikTaty \in BOOLEAN
    /\ nowaZmieniaWymagania \in BOOLEAN
    /\ nowaStartuje \in (IF NieudanyStart THEN BOOLEAN ELSE {TRUE})
    /\ centrum = "stara"
    /\ pc = "spoczynek"
    /\ klikniecia = 0
    /\ krok = "Centrum dziala w starej wersji"
    /\ slady = {}
    /\ cofa = "centrum"
    /\ skrot = "brak"
    /\ skrotyWTrakcie = 0
    /\ wynik = "brak"
    /\ karta = "nic"
    /\ widzi = "centrum"

\* Kroki kodu aktualizacji i opiekuna nie ruszają skrótu klikniętego w trakcie (skrot).
Idz(nastepny, opis) == pc' = nastepny /\ krok' = opis /\ slady' = slady /\ cofa' = cofa /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* Krok awarii znanego znaleziska: zostawia jej ślad dla Po.
Slad(nastepny, opis, slad) == pc' = nastepny /\ krok' = opis /\ slady' = slady \cup {slad} /\ cofa' = cofa /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* Wejście w _roll_back; ``kto`` decyduje, co dzieje się po nim.
Cofaj(kto, opis) == pc' = "cofanie_usun" /\ krok' = opis /\ slady' = slady /\ cofa' = kto /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

CofajSlad(kto, opis, slad) == pc' = "cofanie_usun" /\ krok' = opis /\ slady' = slady \cup {slad} /\ cofa' = kto /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* Klon się nie przesunął, a pliki taty są z powrotem: ToolClone.update usuwa dziennik.
PoOdmowie(opis) == pc' = "koniec_dziennika" /\ krok' = opis /\ slady' = slady /\ cofa' = "centrum" /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

\* Karta Centrum, które startuje w wersji head przy pliku wyniku w: ToolUpdates._after_restart (read_result,
\* _view_of). „ok”, gdy działa inny commit niż jego „po” (running != result.after), to NIEOCZEKIWANY_BLAD (#490):
\* w modelu każde „ok” ma po = "nowa", więc „ok” przy head = "stara" to porażka. Porażka, gdy działa inny commit
\* niż jej „przed” (result.before != running), jest stara (update_result_stale, #725): każda Aktualizacja w modelu
\* zaczyna się od head = "stara" (Pobranie przy "nowa" to AKTUALNA), więc porażka przy head = "nowa" nic nie mówi.
KartaZ(w) == CASE w = "ok" /\ head = "nowa" -> "zaktualizowano"
               [] w = "ok" -> "porazka"
               [] w = "porazka" /\ head = "stara" -> "porazka"
               [] OTHER -> "nic"

KartaSlowami(w) == CASE w = "ok" /\ head = "nowa" -> "karta mowi 'Narzedzie zaktualizowane'"
                     [] w = "ok" -> "karta pokazuje porazke: 'ok' przy starej wersji to NIEOCZEKIWANY_BLAD"
                     [] w = "porazka" /\ head = "stara" -> "karta pokazuje porazke aktualizacji"
                     [] w = "porazka" -> "karta nic nie mowi: porazka z pliku jest sprzed nowej wersji (aktualizacja-wynik-stary)"
                     [] OTHER -> "karta nic nie mowi o aktualizacji"

\* Centrum startuje w wersji head przy pliku wyniku w: ToolUpdates._after_restart czyta plik, usuwa go
\* (przy odmowie dysku plik zostaje do następnego startu) i ustawia kartę. Wynik już zgłoszony (ostatni wpis
\* Aktualizacji w dzienniku Centrum to jej koniec, chyba że „ok” nowej wersji, a plik mówi co innego) albo wynik
\* starszej Aktualizacji (CentrumLog.update_awaits, #491) Centrum pomija: karta nic nie mówi.
\* Dziennika Centrum model nie opisuje, więc każdy start może wynik pominąć; pominięcie nigdy nie daje
\* „zaktualizowano”.
StartCentrumZ(w) ==
    /\ centrum' = head
    /\ karta' \in {KartaZ(w), "nic"}
    /\ wynik' \in IF AwariaKopiowania /\ w /= "brak" THEN {"brak", w} ELSE {"brak"}
    /\ widzi' = "centrum"

StartCentrum == StartCentrumZ(wynik)

\* --- ToolUpdates.start, ToolUpdates._result ----------------------------------

\* RunHost.begin_update zajmuje miejsce „jedno naraz”; restart_guardian.prepare
\* kopiuje opiekuna do nowego katalogu tymczasowego (work), zanim klon się zmieni.
\* Kliknięcie przy dzienniku w toku nie liczy się do MaxKlikniec: po COFNIECIE_NIEUDANE
\* Komunikat każe tacie kliknąć jeszcze raz.
Klik ==
    /\ pc = "spoczynek"
    /\ centrum /= "brak"
    /\ klikniecia < MaxKlikniec \/ dziennik = "w_toku"
    /\ klikniecia' = IF dziennik = "w_toku" THEN klikniecia ELSE klikniecia + 1
    /\ karta' = "nic"
    /\ Idz("pobieranie", "ToolUpdates.start: tata klika 'Zaktualizuj narzedzie'")
    /\ UNCHANGED <<dysk, nowa, centrum, wynik, widzi>>

\* --- ToolClone.update ---------------------------------------------------------

\* Dziennik w toku bez terminu opiekuna (_Journal.read, guardian_may_run): _moved_back cofa
\* klon, zanim cokolwiek się pobierze. Inaczej run.fetch(self.origin) (`main` i tagi Wydań),
\* _main_tips i newest_on_main (Wydania spoza linii czubków main pominięte), is_ancestor(after, before), potem
\* _has_local_commits i _changed_tracked_files (te odmowy nie zmieniają klonu, tak jak porażka
\* fetch, więc model ich nie rozróżnia; tak samo OSError z _run_tree w każdym z tych poleceń Gita,
\* który idzie do ToolUpdates._result jako NIEOCZEKIWANY_BLAD, zanim powstanie dziennik). GitHub bez Wydania, Wydanie na starszym commicie i klon na
\* nowszym commicie `main` niż Wydanie kończą się jak head = "nowa": AKTUALNA, klon bez zmian.
Pobranie ==
    /\ pc = "pobieranie"
    /\ \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "brak"
          /\ Cofaj("klik", "ToolClone.update: dziennik 'Aktualizacja w toku' bez terminu opiekuna, _roll_back przed pobraniem")
       \/ /\ dziennik = "brak" \/ dzierzawa = "wazna"
          /\ \/ /\ AwariaPobrania
                /\ Idz("spoczynek", "ToolClone.update: fetch nie przeszedl (BRAK_POLACZENIA), klon bez zmian")
             \/ /\ head = "nowa"
                /\ Idz("spoczynek", "ToolClone.update: klon zawiera najnowsze Wydanie (AKTUALNA), klon bez zmian")
             \/ /\ head = "stara"
                /\ Idz("kopia_plikow",
                       IF nowaUsuwaPlikTaty
                       THEN "ToolClone.update: najnowsze Wydanie usuwa plik taty z config/"
                       ELSE "ToolClone.update: fetch pobral nowe Wydanie")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, ekran>>

\* _Journal.begin: copy2 pliku taty do pliki-taty i fsync, potem stan.json (plik tymczasowy, fsync,
\* os.replace). Trwający dziennik to JournalKept, zanim cokolwiek się zmieni (NIEOCZEKIWANY_BLAD).
KopiaPlikow ==
    /\ pc = "kopia_plikow"
    /\ \/ /\ dziennik = "brak"
          /\ kopia' = IF nowaUsuwaPlikTaty THEN "taty" ELSE "brak"
          /\ dziennik' = "w_toku"
          /\ dzierzawa' = "brak"
          /\ Idz(IF nowaUsuwaPlikTaty THEN "checkout_head" ELSE "scalanie",
                 "_Journal.begin: kopia plikow taty, potem stan.json dziennika 'Aktualizacja w toku'")
       \/ /\ dziennik = "w_toku"
          /\ UNCHANGED <<kopia, dziennik, dzierzawa>>
          /\ Idz("spoczynek", "_Journal.begin: poprzednia aktualizacja w toku, JournalKept (NIEOCZEKIWANY_BLAD), klon bez zmian")
       \/ /\ AwariaKopiowania
          /\ dziennik = "brak"
          /\ UNCHANGED <<kopia, dziennik, dzierzawa>>
          /\ Idz("spoczynek", "_Journal.begin: copy2 albo zapis stan.json rzuca OSError (NIEOCZEKIWANY_BLAD), klon bez zmian")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum, klikniecia, ekran>>

\* _DadFiles.set_aside: git checkout HEAD -- <plik taty>, w try. Kod wyjścia różny od 0 to _NotSetAside,
\* po którym ToolClone.update usuwa dziennik. Limit czasu rzuca TimeoutExpired, a _run_tree w Windows także
\* OSError (zadanie nie powstało, _join, drzewo przeżyło zabicie): finally wgrywa kopię, a wyjątek mija oba
\* except w ToolClone.update, więc dziennik zostaje. Ubity checkout mógł już nadpisać plik taty albo jeszcze nie.
CheckoutHead ==
    /\ pc = "checkout_head"
    /\ \/ /\ plikTaty' = "wzor"
          /\ Idz("scalanie", "_DadFiles.set_aside: git checkout HEAD -- przywraca plikowi tresc z repozytorium")
       \/ /\ AwariaGita
          /\ plikTaty' = plikTaty
          /\ Idz("przywrocenie_po_odmowie", "_DadFiles.set_aside: git checkout HEAD -- sie nie udaje, _NotSetAside")
       \/ /\ AwariaGita
          /\ plikTaty' \in {"taty", "wzor"}
          /\ Idz("przywrocenie_po_wyjatku", "_DadFiles.set_aside: git checkout HEAD -- rzuca TimeoutExpired albo OSError (_run_tree)")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

\* ToolClone.update: git merge --ff-only, w bloku set_aside. Wyjątek z _Git.run (TimeoutExpired albo OSError
\* z _run_tree, także zanim Git ruszy) zostawia moved = False: finally set_aside wgrywa kopię, gdy jest
\* (PrzywroceniePoWyjatku), a wyjątek mija oba except w ToolClone.update, więc dziennik zostaje
\* (NIEOCZEKIWANY_BLAD). Git ubity po przesunięciu klonu (np. w gc --auto po scaleniu) zostawia klon na
\* nowym Wydaniu; scalenie przerwane w połowie model pomija (Scope).
Scalanie ==
    /\ pc = "scalanie"
    /\ \/ /\ head' = "nowa"
          /\ plikTaty' = IF nowaUsuwaPlikTaty THEN "brak" ELSE plikTaty
          /\ Idz(IF nowaUsuwaPlikTaty THEN "przywrocenie_po_scaleniu" ELSE "instalacja",
                 "ToolClone.update: git merge --ff-only przesuwa klon na nowe Wydanie")
       \/ /\ OdmowaScalenia
          /\ UNCHANGED <<head, plikTaty>>
          /\ IF nowaUsuwaPlikTaty
             THEN Idz("przywrocenie_po_odmowie", "ToolClone.update: git merge --ff-only odmawia (ZMIANY_NA_KOMPUTERZE)")
             ELSE PoOdmowie("ToolClone.update: git merge --ff-only odmawia (ZMIANY_NA_KOMPUTERZE)")
       \/ /\ AwariaGita
          /\ head' \in {"stara", "nowa"}
          /\ plikTaty' = IF head' = "nowa" /\ nowaUsuwaPlikTaty THEN "brak" ELSE plikTaty
          /\ IF nowaUsuwaPlikTaty
             THEN Idz("przywrocenie_po_wyjatku", "ToolClone.update: git merge --ff-only rzuca TimeoutExpired albo OSError (_run_tree)")
             ELSE Idz("spoczynek", "ToolClone.update: git merge --ff-only rzuca TimeoutExpired albo OSError (_run_tree); dziennik zostaje (NIEOCZEKIWANY_BLAD)")
    /\ UNCHANGED <<kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

\* _DadFiles.set_aside, finally, gdy klon się nie przesunął: _put_back, czyli copy2(backup / name, target).
\* Potem ToolClone.update usuwa dziennik (po odmowie i po _NotSetAside z checkout). OSError staje się
\* _NotPutBack; ToolClone.update zwraca COFNIECIE_NIEUDANE, a dziennik z kopią zostaje.
PrzywroceniePoOdmowie ==
    /\ pc = "przywrocenie_po_odmowie"
    /\ \/ /\ plikTaty' = "taty"
          /\ PoOdmowie("_DadFiles.set_aside (finally): plik taty wraca z kopii, klon bez zmian")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE, tresc taty tylko w dzienniku)")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

\* _DadFiles.set_aside, finally, po wyjątku z git checkout HEAD -- albo git merge --ff-only (TimeoutExpired,
\* OSError z _run_tree): _put_back wgrywa kopię, a wyjątek idzie do ToolUpdates._result (NIEOCZEKIWANY_BLAD).
\* OSError z _put_back staje się _NotPutBack, a ToolClone.update (moved = False) zwraca COFNIECIE_NIEUDANE.
\* W obu razach dziennik zostaje, a klon stoi tam, gdzie zostawił go Git.
PrzywroceniePoWyjatku ==
    /\ pc = "przywrocenie_po_wyjatku"
    /\ \/ /\ plikTaty' = "taty"
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): plik taty wraca z kopii; wyjatek Gita, dziennik zostaje (NIEOCZEKIWANY_BLAD)")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE), dziennik zostaje")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

\* _DadFiles.set_aside, finally, po przesunięciu klonu. OSError z _put_back staje się
\* _NotPutBack, a ToolClone.update (except _NotPutBack, moved) woła _moved_back -> _roll_back.
PrzywroceniePoScaleniu ==
    /\ pc = "przywrocenie_po_scaleniu"
    /\ \/ /\ plikTaty' = "taty"
          /\ Idz("instalacja", "_DadFiles.set_aside (finally): plik taty wraca z kopii")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Cofaj("centrum", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError; update() wola _roll_back")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

\* ToolClone._install_libraries, w try: run.changed(...requirements.txt), potem self.install.
Instalacja ==
    /\ pc = "instalacja"
    /\ \/ /\ ~nowaZmieniaWymagania
          /\ UNCHANGED biblioteki
          /\ Idz("restart", "ToolClone.update: requirements.txt bez zmian, wynik ok")
       \/ /\ nowaZmieniaWymagania
          /\ biblioteki' = "czesciowe"
          /\ Idz("instalacja_trwa", "pip_install: pip instaluje biblioteki nowej wersji (do 15 minut)")
       \/ /\ AwariaGita
          /\ UNCHANGED biblioteki
          /\ Cofaj("centrum", "_Git.changed: git diff rzuca GitFailed, TimeoutExpired albo OSError, update() wola _roll_back")
    /\ UNCHANGED <<head, plikTaty, kopia, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

InstalacjaKoniec ==
    /\ pc = "instalacja_trwa"
    /\ \/ /\ biblioteki' = "nowe"
          /\ Idz("restart", "pip_install: pip skonczyl, wynik ok")
       \/ /\ AwariaBibliotek
          /\ UNCHANGED biblioteki
          /\ Cofaj("centrum", "pip_install zwraca False, update() wola _roll_back (INSTALACJA_BIBLIOTEK)")
    /\ UNCHANGED <<head, plikTaty, kopia, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

\* --- _roll_back ---------------------------------------------------------------

\* _roll_back, który rzucił: dziennik zostaje. W Centrum _moved_back zwraca False i wynikiem jest
\* COFNIECIE_NIEUDANE; opiekun (_rolled_back zwraca False) zapisuje COFNIECIE_NIEUDANE (OpiekunWynik),
\* pokazuje okienko i kończy się; skrót kończy się okienkiem NIEOCZEKIWANY_BLAD_STARTU (wyjątek z
\* launcher._roll_back do launcher.main, _refuse) i niczego nie startuje.
NieudaneCofniecie(opis) ==
    /\ Idz(IF cofa \in {"opiekun", "opiekun_bez_portu"} THEN "opiekun_wynik" ELSE "spoczynek", opis)
    /\ widzi' = IF cofa = "skrot" THEN "okienko" ELSE widzi

KtoPokazujeNieudane == CASE cofa \in {"centrum", "klik"} -> "Centrum pokazuje COFNIECIE_NIEUDANE"
                         [] cofa = "skrot" -> "skrot konczy sie Komunikatem startu"
                         [] OTHER -> "opiekun zapisuje COFNIECIE_NIEUDANE"

\* _Journal.read i rev-parse HEAD (klon na przed albo po), potem (git.root / name).unlink()
\* dla każdego pliku z kopii w dzienniku. rev-parse HEAD, który rzuca (GitFailed, TimeoutExpired,
\* OSError z _run_tree), kończy _roll_back przed try, więc nic się nie zmienia. Tak samo unlink pliku taty,
\* który rzuca OSError (Windows trzyma plik): plik zostaje, a _put_back nie rusza, bo jest dopiero w finally.
CofanieUsun ==
    /\ pc = "cofanie_usun"
    /\ \/ /\ plikTaty' = IF kopia = "taty" THEN "brak" ELSE plikTaty
          /\ Idz("cofanie_reset", "_roll_back: plik taty znika z klonu przed reset")
          /\ widzi' = widzi
       \/ /\ AwariaGita
          /\ plikTaty' = plikTaty
          /\ NieudaneCofniecie("_roll_back: rev-parse HEAD rzuca, nic sie nie zmienia; " \o KtoPokazujeNieudane)
       \/ /\ AwariaKopiowania
          /\ kopia = "taty"
          /\ plikTaty /= "brak"  \* unlink(missing_ok=True) brakującego pliku nie rzuca
          /\ plikTaty' = plikTaty
          /\ NieudaneCofniecie("_roll_back: (git.root / name).unlink rzuca OSError przed try, plik taty zostaje; " \o KtoPokazujeNieudane)
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, wynik, karta>>

CofanieUsunUdane == CofanieUsun /\ pc' = "cofanie_reset"

\* git reset --keep --quiet before, w try. Stara wersja śledzi plik taty, więc reset
\* zapisuje jej treść z repozytorium. Porażka (GitFailed, TimeoutExpired, OSError z _run_tree) zostawia
\* klon, gdzie stał: na nowym commicie albo na starym, gdy dziennik został, a klon się jeszcze nie przesunął
\* (wyjątek albo nieudane _put_back w checkout HEAD -- lub w scalaniu, wyłączenie komputera przed scaleniem
\* albo po jego odmowie, zanim ToolClone.update usunie dziennik)
\* albo już wrócił (wcześniejsze cofanie z udanym resetem, po którym _put_back rzucił albo komputer zgasł).
CofanieReset ==
    /\ pc = "cofanie_reset"
    /\ \/ /\ head' = "stara"
          /\ plikTaty' = IF kopia = "taty" THEN "wzor" ELSE plikTaty
          /\ Idz("cofanie_przywroc", "_roll_back: git reset --keep cofa klon do starego commitu")
       \/ /\ AwariaGita
          /\ UNCHANGED <<head, plikTaty>>
          /\ Idz("cofanie_przywroc_po_bledzie", "_roll_back: git reset --keep rzuca, klon zostaje, gdzie stal")
    /\ UNCHANGED <<kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

CofanieResetUdane == CofanieReset /\ pc' = "cofanie_przywroc"

\* finally: _put_back, czyli shutil.copy2(backup / name, target). Biblioteki zostają (docstring tool_update.py).
\* Po udanym resecie i kopiowaniu _roll_back usuwa dziennik (KoniecDziennika). Gdy reset się nie
\* udał, po finally wychodzi jego wyjątek (NieudaneCofniecie), także gdy klon już stał na starym commicie.
CofaniePrzywroc ==
    /\ pc \in {"cofanie_przywroc", "cofanie_przywroc_po_bledzie"}
    /\ \/ /\ plikTaty' = IF kopia = "taty" THEN "taty" ELSE plikTaty
          /\ IF pc = "cofanie_przywroc"
             THEN /\ Idz("koniec_dziennika", "_roll_back (finally): plik taty wraca z kopii")
                  /\ widzi' = widzi
             ELSE NieudaneCofniecie("_roll_back (finally): plik taty wraca z kopii; reset rzucil, " \o KtoPokazujeNieudane)
       \/ /\ AwariaKopiowania
          /\ kopia = "taty"
          /\ plikTaty' = plikTaty
          /\ NieudaneCofniecie("_roll_back (finally): copy2 z kopii rzuca OSError (tresc taty tylko w dzienniku); " \o KtoPokazujeNieudane)
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, wynik, karta>>

CofaniePrzywrocUdane == CofaniePrzywroc /\ pc' = "koniec_dziennika"

\* _Journal.end: najpierw stan.json, potem katalog z kopią. Po nim każdy, kto cofał, idzie dalej: opiekun
\* zapisuje wynik (OpiekunWynik), skrót zapisuje wynik i startuje Centrum od nowa (SkrotWynik), klik pobiera.
KoniecDziennika ==
    /\ pc = "koniec_dziennika"
    /\ dziennik' = "brak"
    /\ kopia' = "brak"
    /\ dzierzawa' = "brak"
    /\ Idz(CASE cofa = "skrot" -> "skrot_wynik"
             [] cofa \in {"opiekun", "opiekun_bez_portu"} -> "opiekun_wynik"
             [] cofa = "klik" -> "pobieranie"
             [] OTHER -> "spoczynek",
           CASE cofa = "skrot" -> "_Journal.end: dziennik znika; skrot cofnal klon"
             [] cofa = "opiekun" -> "_Journal.end: dziennik znika; opiekun cofnal klon"
             [] cofa = "klik" -> "_Journal.end: dziennik znika; ToolClone.update pobiera Wydania jak zwykle"
             [] cofa = "opiekun_bez_portu" -> "_Journal.end: dziennik znika; opiekun cofnal klon bez portu"
             [] OTHER -> "_Journal.end: dziennik znika; Centrum pokazuje Komunikat porazki")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum, klikniecia, ekran>>

\* launcher._roll_back po ToolClone.roll_back: write_result(NIEOCZEKIWANY_BLAD), potem w launcher._start
\* subprocess.call(restart_from_disk): Centrum z cofniętego klonu czyta ten wynik. OSError z zapisu
\* idzie do launcher.main: okienko NIEOCZEKIWANY_BLAD_STARTU, nic nie startuje, stary plik wyniku zostaje.
SkrotWynik ==
    /\ pc = "skrot_wynik"
    /\ \/ /\ StartCentrumZ("porazka")
          /\ Idz("spoczynek", "launcher._roll_back: write_result(NIEOCZEKIWANY_BLAD); Centrum startuje od nowa z cofnietego klonu, karta pokazuje porazke aktualizacji")
       \/ /\ AwariaKopiowania
          /\ widzi' = "okienko"
          /\ UNCHANGED <<wynik, karta, centrum>>
          /\ Idz("spoczynek", "launcher._roll_back: write_result rzuca OSError; okienko NIEOCZEKIWANY_BLAD_STARTU, nic nie startuje")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* --- ToolUpdates._restart, restart_guardian.main ------------------------------

\* ToolUpdates._restart; gdy blok rzuca, ToolUpdates._moved_back woła ToolClone.roll_back (-> _roll_back),
\* a Centrum działa dalej w starej wersji. ToolClone.leased_to_guardian zapisuje w dzienniku opiekun_do
\* przed restart_guardian.launch (_Journal.lease: plik tymczasowy, potem os.replace, więc OSError zostawia
\* stan.json bez terminu), a gdy launch rzuci, usuwa go; to usunięcie też może rzucić OSError.
Restart ==
    /\ pc = "restart"
    /\ \/ /\ AwariaKopiowania
          /\ UNCHANGED <<dzierzawa, centrum, karta, widzi>>
          /\ Cofaj("centrum", "ToolClone.leased_to_guardian: zapis terminu opiekuna rzuca OSError; _moved_back cofa klon, Centrum dziala dalej")
       \/ /\ AwariaOpiekuna
          /\ dzierzawa' \in IF AwariaKopiowania THEN {"brak", "wazna"} ELSE {"brak"}
          /\ UNCHANGED <<centrum, karta, widzi>>
          /\ Cofaj("centrum", "ToolUpdates._restart: restart_guardian.launch rzuca; _moved_back cofa klon, Centrum dziala dalej")
       \/ /\ dzierzawa' = "wazna"
          /\ centrum' = "brak"
          /\ karta' = "nic"
          /\ widzi' = "nic"
          /\ Idz("opiekun_port", "ToolUpdates._restart: opiekun startuje, Shutdown.close_for_update zamyka Centrum")
    /\ UNCHANGED <<head, plikTaty, kopia, biblioteki, dziennik, nowa, klikniecia, wynik>>

\* _port_released, potem _record(UPDATED): write_result(ok) w suppress(OSError), więc odmowa dysku
\* zostawia plik wyniku, jaki był, a opiekun idzie dalej. Oba w jednym kroku: plik wyniku czyta tylko
\* startujące Centrum, a skrót kliknięty między nimi oddaje port przy dzienniku z terminem opiekuna.
\* Bez portu main od razu woła _rolled_back (ToolClone.roll_back -> _roll_back), nie zapisując „ok”.
\* _port_released próbuje co _POLL_S przez PORT_TIMEOUT_S, a skrót trzyma port przez chwilę,
\* więc opiekun czeka, aż skrót go odda (skrot = "brak").
OpiekunPort ==
    /\ pc = "opiekun_port"
    /\ \/ /\ AwariaOpiekuna
          /\ UNCHANGED wynik
          /\ Cofaj("opiekun_bez_portu", "restart_guardian.main: port nie zwolniony w PORT_TIMEOUT_S; _rolled_back bez startu nowej wersji")
       \/ /\ skrot = "brak"
          /\ wynik' = "ok"
          /\ Idz("opiekun_start", "restart_guardian.main: port zwolniony; _record zapisuje wynik ok")
       \/ /\ skrot = "brak"
          /\ AwariaKopiowania
          /\ UNCHANGED wynik
          /\ Idz("opiekun_start", "restart_guardian.main: port zwolniony; _record: write_result(ok) rzuca OSError, opiekun idzie dalej")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, karta, widzi>>

\* _start_centrum (run_centrum.py --bez-okienek: skrót bez cofania), potem _answers. Nowe Centrum przy
\* starcie czyta plik wyniku (StartCentrum). Gdy nowa wersja nie odpowie: _stop, potem usunięcie „ok”
\* (OpiekunWycofanie) i _rolled_back, czyli ToolClone.roll_back -> _roll_back.
\* Akcja to chwila, w której nowe Centrum zajmuje port w launcher._listen_when_released. Gdy
\* port trzyma skrót, Centrum z --bez-okienek ponawia listen_locally przez _SHORTCUT_HOLDS_PORT_S,
\* a skrót oddaje port po odczycie dziennika z terminem opiekuna (SkrotOddajePort), więc akcja
\* czeka na skrot = "brak" (#246).
OpiekunStart ==
    /\ pc = "opiekun_start"
    /\ skrot = "brak"
    /\ \/ /\ Startuje(head)
          /\ StartCentrum
          /\ Idz("opiekun_koniec", "restart_guardian.main: nowa wersja odpowiada na /api/health; " \o KartaSlowami(wynik))
       \/ /\ ~Startuje(head)
          /\ UNCHANGED <<centrum, ekran>>
          /\ Idz("opiekun_wycofanie", "restart_guardian.main: nowa wersja nie odpowiada w START_TIMEOUT_S; _stop")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* ToolClone.confirm_update: aktualizacja skończona, dziennik znika (_Journal.end).
OpiekunKoniec ==
    /\ pc = "opiekun_koniec"
    /\ dziennik' = "brak"
    /\ kopia' = "brak"
    /\ dzierzawa' = "brak"
    /\ Idz("spoczynek", "restart_guardian.main: ToolClone.confirm_update usuwa dziennik")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum, klikniecia, ekran>>

\* Po _stop restart_guardian.main usuwa plik wyniku (unlink(missing_ok=True) w suppress(OSError)):
\* „ok” przestało być prawdą. Odmowa dysku zostawia „ok”, a opiekun i tak cofa klon. Gdy potem dysk
\* odmówi też zapisu porażki (OpiekunWynik, SkrotWynik), stara wersja czyta „ok” i pokazuje porażkę (KartaZ).
OpiekunWycofanie ==
    /\ pc = "opiekun_wycofanie"
    /\ \/ /\ wynik' = "brak"
          /\ Cofaj("opiekun", "restart_guardian.main: usuwa plik wyniku 'ok', potem _rolled_back")
       \/ /\ AwariaKopiowania
          /\ wynik /= "brak"
          /\ UNCHANGED wynik
          /\ Cofaj("opiekun", "restart_guardian.main: usuniecie pliku wyniku rzuca OSError, 'ok' zostaje; potem _rolled_back")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, karta, widzi>>

\* Po _rolled_back: _record z NOWA_WERSJA_NIE_WYSTARTOWALA (cofnięcie udane, dziennika nie ma) albo
\* COFNIECIE_NIEUDANE, write_result w suppress(OSError): odmowa dysku zostawia plik wyniku, a opiekun idzie
\* dalej. Potem po udanym cofnięciu stara wersja, także po cofnięciu bez zwolnionego portu (#726), a po
\* nieudanym okienko.
OpiekunWynik ==
    /\ pc = "opiekun_wynik"
    /\ LET dalej == IF dziennik = "brak" THEN "opiekun_port_stara" ELSE "okienko"
       IN \/ /\ wynik' = "porazka"
             /\ Idz(dalej, "restart_guardian.main: _record zapisuje wynik porazki po cofnieciu")
          \/ /\ AwariaKopiowania
             /\ UNCHANGED wynik
             /\ Idz(dalej, "restart_guardian.main: _record po cofnieciu, write_result rzuca OSError, opiekun idzie dalej")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, karta, widzi>>

\* Po udanym cofnięciu: _port_released, potem _start_centrum i _answers(before), także po cofnięciu bez
\* zwolnionego portu (#726). Port po cofnięciu może trzymać Centrum, które skrót uruchomił, gdy dziennika
\* już nie było: _port_released czeka na nie PORT_TIMEOUT_S, a potem opiekun pyta je _runs(before) i kończy
\* bez okienka. Port bez Centrum i bez skrótu trzyma inny program (albo stare Centrum, które się nie
\* zamknęło): wtedy okienko not_started_after_update.
OpiekunPortStara ==
    /\ pc = "opiekun_port_stara"
    /\ \/ /\ AwariaOpiekuna
          /\ centrum = "brak"
          /\ skrot = "brak"
          /\ Idz("okienko", "restart_guardian.main: port po cofnieciu trzyma inny program, _runs(before) nie odpowiada")
       \/ /\ centrum /= "brak"
          /\ Idz("spoczynek", "restart_guardian.main: port po cofnieciu trzyma Centrum ze skrotu, opiekun konczy bez okienka (_runs)")
       \/ /\ centrum = "brak"
          /\ skrot = "brak"
          /\ Idz("opiekun_start_stara", "restart_guardian.main: port zwolniony po cofnieciu")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, ekran>>

\* Stara wersja też startuje z --bez-okienek, więc jak nowa w OpiekunStart czeka, aż skrót odda
\* port. Gdy skrót bez dziennika został na porcie z Centrum w tej samej wersji, stara po
\* _SHORTCUT_HOLDS_PORT_S kończy się (już działa), a _answers(before) dostaje odpowiedź od tamtego
\* Centrum.
OpiekunStartStara ==
    /\ pc = "opiekun_start_stara"
    /\ skrot = "brak"
    /\ IF centrum = "brak" /\ Startuje(head)
       THEN StartCentrum
       ELSE UNCHANGED <<centrum, ekran>>
    /\ Idz(IF centrum = "brak" /\ ~Startuje(head) THEN "okienko" ELSE "spoczynek",
           CASE centrum /= "brak" -> "restart_guardian.main: stara wersja juz dziala (Centrum ze skrotu odpowiada)"
             [] Startuje(head) -> "restart_guardian.main: stara wersja odpowiada; " \o KartaSlowami(wynik)
             [] OTHER -> "restart_guardian.main: stara wersja nie odpowiada, opiekun pokazuje okienko")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

\* show_problem: natywne okienko not_started_after_update, potem return 1.
OpiekunOkienko ==
    /\ pc = "okienko"
    /\ widzi' = "okienko"
    /\ Idz("spoczynek", "restart_guardian.main: show_problem pokazuje okienko not_started_after_update (return 1)")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, wynik, karta>>

\* --- Poza kodem aktualizacji ----------------------------------------------------

\* Komputer gaśnie albo proces ginie (Centrum, opiekun albo skrót w trakcie cofania). Na
\* dysku zostaje stan z ostatniego kroku, razem z dziennikiem i jego kopią.
Wylacz ==
    /\ Wylaczenie
    /\ pc /= "spoczynek"
    /\ centrum' = "brak"
    /\ skrot' = "brak"
    /\ pc' = "spoczynek"
    /\ karta' = "nic"
    /\ widzi' = "wylaczony"
    /\ krok' = "komputer gasnie w tym kroku"
    /\ UNCHANGED <<dysk, nowa, klikniecia, slady, cofa, skrotyWTrakcie, wynik>>

\* Mija GUARDIAN_LEASE_S od zapisu opiekun_do. Założenie (Scope): opiekun kończy się przed tym
\* terminem, więc termin mija dopiero wtedy, gdy nic już nie działa.
\* Skrót trzyma port przez ułamek sekundy, a termin to 10 minut, więc nie mija w tej chwili.
DzierzawaMija ==
    /\ pc = "spoczynek"
    /\ skrot = "brak"
    /\ dzierzawa = "wazna"
    /\ dzierzawa' = "brak"
    /\ krok' = "mija termin opiekuna (GUARDIAN_LEASE_S)"
    /\ UNCHANGED <<head, plikTaty, kopia, biblioteki, dziennik, nowa, centrum, pc, klikniecia, slady, cofa, skrot, skrotyWTrakcie, ekran>>

\* Tata uruchamia Centrum skrótem z pulpitu (launcher._start z klonu). Skrót zajmuje port
\* (listen_locally) i czyta dziennik (ToolClone.interrupted_update), zanim wczyta biblioteki.
\* Gdy nic nie działa, nikt inny nie walczy o port, więc cały start skrótu to jeden krok.
Skrot ==
    /\ pc = "spoczynek"
    /\ centrum = "brak"
    /\ skrot = "brak"
    /\ \/ /\ dziennik = "brak"
          /\ Startuje(head)
          /\ StartCentrum
          /\ krok' = "tata uruchamia Centrum skrotem z pulpitu; " \o KartaSlowami(wynik)
          /\ UNCHANGED <<dysk, nowa, pc, klikniecia, slady, cofa, skrot, skrotyWTrakcie>>
       \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "wazna"
          /\ widzi' = "okienko"
          /\ krok' = "skrot: dziennik z terminem opiekuna, okienko AKTUALIZACJA_SIE_KONCZY"
          /\ UNCHANGED <<dysk, nowa, centrum, pc, klikniecia, slady, cofa, skrot, skrotyWTrakcie, wynik, karta>>
       \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "brak"
          /\ Cofaj("skrot", "skrot: dziennik 'Aktualizacja w toku', launcher._roll_back przed startem")
          /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, ekran>>

\* Opiekun ponownego startu działa (od Restart do jego ostatniego kroku), a port jest wolny:
\* stare Centrum już się zamknęło, a nowe jeszcze go nie zajęło.
DzialaOpiekun ==
    \/ pc \in {"opiekun_port", "opiekun_start", "opiekun_koniec", "opiekun_wycofanie", "opiekun_wynik",
              "opiekun_port_stara", "opiekun_start_stara"}
    \/ /\ pc \in {"cofanie_usun", "cofanie_reset", "cofanie_przywroc", "cofanie_przywroc_po_bledzie",
              "koniec_dziennika"}
       /\ cofa \in {"opiekun", "opiekun_bez_portu"}

\* Tata klika skrót, gdy opiekun działa (karta pokazuje ponowny start): launcher._start
\* z klonu (bez --bez-okienek) zajmuje wolny port w listen_locally. Gdy port trzyma
\* Centrum, bind rzuca, a skrót tylko pyta health: nic na dysku się nie zmienia, więc tego
\* przypadku model nie opisuje.
SkrotWTrakcie ==
    /\ DzialaOpiekun
    /\ centrum = "brak"
    /\ skrot = "brak"
    /\ skrotyWTrakcie < MaxSkrotowWTrakcie
    /\ skrot' = "ma_port"
    /\ skrotyWTrakcie' = skrotyWTrakcie + 1
    /\ krok' = "tata klika skrot w trakcie ponownego startu: launcher._start zajmuje port (listen_locally)"
    /\ UNCHANGED <<dysk, nowa, centrum, pc, klikniecia, slady, cofa, ekran>>

\* launcher._start po listen_locally: ToolClone.interrupted_update i guardian_may_run. Z terminem
\* opiekuna listener.close() i Komunikat update_finishing. Bez dziennika (opiekun już go usunął
\* po cofnięciu) skrót startuje Centrum i zostaje na porcie. Dziennik bez terminu nie zdarza się,
\* póki opiekun działa (DzierzawaMija). Okienko AKTUALIZACJA_SIE_KONCZY model pomija: opiekun działa
\* dalej i to on decyduje, co tata zobaczy na końcu.
SkrotOddajePort ==
    /\ skrot = "ma_port"
    /\ skrot' = "brak"
    /\ \/ /\ dziennik = "w_toku"
          /\ dzierzawa = "wazna"
          /\ UNCHANGED <<centrum, ekran>>
          /\ krok' = "skrot: dziennik z terminem opiekuna, listener.close(), Komunikat AKTUALIZACJA_SIE_KONCZY"
       \/ /\ dziennik = "brak"
          /\ IF Startuje(head) THEN StartCentrum ELSE UNCHANGED <<centrum, ekran>>
          /\ krok' = "skrot: dziennika juz nie ma, Centrum ze skrotu startuje i zostaje na porcie; " \o KartaSlowami(wynik)
    /\ UNCHANGED <<dysk, nowa, pc, klikniecia, slady, cofa, skrotyWTrakcie>>

\* Kroki kodu: Centrum, opiekun i skrót, który cofa albo oddaje port.
Program ==
    \/ Pobranie \/ KopiaPlikow \/ CheckoutHead \/ Scalanie
    \/ PrzywroceniePoOdmowie \/ PrzywroceniePoScaleniu \/ PrzywroceniePoWyjatku \/ Instalacja \/ InstalacjaKoniec
    \/ CofanieUsun \/ CofanieReset \/ CofaniePrzywroc \/ KoniecDziennika \/ SkrotWynik
    \/ Restart \/ OpiekunPort \/ OpiekunStart \/ OpiekunKoniec \/ OpiekunWycofanie \/ OpiekunWynik
    \/ OpiekunPortStara \/ OpiekunStartStara
    \/ OpiekunOkienko
    \/ SkrotOddajePort

Next == Program \/ Klik \/ Wylacz \/ DzierzawaMija \/ Skrot \/ SkrotWTrakcie

\* Działający kod robi następny krok, tata klika, póki Centrum działa i ma kliknięcia albo dziennik
\* jest w toku, uruchamia skrót, póki Centrum nie działa, a termin opiekuna kiedyś mija, także gdy
\* tata w międzyczasie klika. Awarie Gita i kopiowania są przejściowe: cofanie ponawiane bez końca
\* kiedyś się udaje (silna sprawiedliwość), także jego rev-parse HEAD.
Sprawiedliwosc ==
    /\ WF_vars(Program)
    /\ WF_vars(Klik)
    /\ WF_vars(Skrot)
    /\ SF_vars(DzierzawaMija)
    /\ SF_vars(CofanieUsunUdane)
    /\ SF_vars(CofanieResetUdane)
    /\ SF_vars(CofaniePrzywrocUdane)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc


\* --- Postęp ------------------------------------------------------------------

\* Dziennik w toku w końcu znika: skrót, opiekun, Centrum albo następne kliknięcie kończy albo cofa
\* aktualizację.
\* Gdy znika w spoczynku, TataMaDzialajacaWersje wymaga wersji, która startuje, i pliku taty.
\* Założenie: komputer gaśnie skończenie wiele razy.
Postep == <>[][~Wylacz]_vars => (dziennik = "w_toku" ~> dziennik = "brak")

\* slady tylko rosną, więc <>Po(...) to przebieg, w którym awaria znanego znaleziska kiedyś się zdarzyła.
PostepPozaZnanymi == Postep \/ <>Po(WybaczonePostep)

=============================================================================
