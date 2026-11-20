------------------------- MODULE AktualizacjaNarzedzia -------------------------
EXTENDS Naturals, Sequences

CONSTANTS
    MaxKlikniec,
    OdmowaScalenia,
    AwariaPobrania,
    AwariaBibliotek,
    AwariaOpiekuna,
    AwariaGita,
    AwariaKopiowania,
    NieudanyStart,
    Wylaczenie,
    MaxSkrotowWTrakcie,
    WybaczoneTataMaDzialajacaWersje, WybaczoneOpiekunCofaTylkoNieudana, WybaczoneOkienkoTylkoGdyNicNieDziala,
    WybaczoneTataNieZostajeBezOdpowiedzi, WybaczoneKartaNieKlamie, WybaczoneKartaNieStraszy, WybaczonePostep

VARIABLES
    head,
    plikTaty,
    kopia,
    biblioteki,
    dziennik,
    dzierzawa,
    nowaUsuwaPlikTaty,
    nowaZmieniaWymagania,
    nowaStartuje,
    centrum,
    pc,
    klikniecia,
    krok,
    slady,
    skrot,
    skrotyWTrakcie,
    cofa,
    wynik,
    karta,
    widzi

dysk == <<head, plikTaty, kopia, biblioteki, dziennik, dzierzawa>>
nowa == <<nowaUsuwaPlikTaty, nowaZmieniaWymagania, nowaStartuje>>
ekran == <<wynik, karta, widzi>>
vars == <<dysk, nowa, centrum, pc, klikniecia, krok, slady, cofa, skrot, skrotyWTrakcie, ekran>>

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

Startuje(wersja) ==
    \/ wersja = "stara"
    \/ /\ nowaStartuje
       /\ (~nowaZmieniaWymagania \/ biblioteki = "nowe")

TrescTatyNaDysku == plikTaty = "taty" \/ kopia = "taty"

TataMaDzialajacaWersje ==
    pc = "spoczynek" =>
        \/ Startuje(head) /\ plikTaty = "taty"
        \/ dziennik = "w_toku" /\ TrescTatyNaDysku

Po(wybaczone) == wybaczone \cap slady /= {}

TataMaDzialajacaWersjePozaZnanymi == TataMaDzialajacaWersje \/ Po(WybaczoneTataMaDzialajacaWersje)

OpiekunCofaTylkoNieudana ==
    pc = "cofanie_usun" /\ cofa = "opiekun" => ~Startuje(head)

OpiekunCofaTylkoNieudanaPozaZnanymi == OpiekunCofaTylkoNieudana \/ Po(WybaczoneOpiekunCofaTylkoNieudana)

OkienkoTylkoGdyNicNieDziala ==
    pc = "okienko" => centrum = "brak"

OkienkoTylkoGdyNicNieDzialaPozaZnanymi == OkienkoTylkoGdyNicNieDziala \/ Po(WybaczoneOkienkoTylkoGdyNicNieDziala)

TataNieZostajeBezOdpowiedzi ==
    pc = "spoczynek" /\ centrum = "brak" => widzi \in {"okienko", "wylaczony"}

TataNieZostajeBezOdpowiedziPozaZnanymi == TataNieZostajeBezOdpowiedzi \/ Po(WybaczoneTataNieZostajeBezOdpowiedzi)

KartaNieKlamie ==
    karta = "zaktualizowano" => centrum = "nowa"

KartaNieKlamiePozaZnanymi == KartaNieKlamie \/ Po(WybaczoneKartaNieKlamie)

KartaNieStraszy ==
    karta = "porazka" => centrum /= "nowa"

KartaNieStraszyPozaZnanymi == KartaNieStraszy \/ Po(WybaczoneKartaNieStraszy)

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

Idz(nastepny, opis) == pc' = nastepny /\ krok' = opis /\ slady' = slady /\ cofa' = cofa /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

Slad(nastepny, opis, slad) == pc' = nastepny /\ krok' = opis /\ slady' = slady \cup {slad} /\ cofa' = cofa /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

Cofaj(kto, opis) == pc' = "cofanie_usun" /\ krok' = opis /\ slady' = slady /\ cofa' = kto /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

CofajSlad(kto, opis, slad) == pc' = "cofanie_usun" /\ krok' = opis /\ slady' = slady \cup {slad} /\ cofa' = kto /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

PoOdmowie(opis) == pc' = "koniec_dziennika" /\ krok' = opis /\ slady' = slady /\ cofa' = "centrum" /\ skrot' = skrot /\ skrotyWTrakcie' = skrotyWTrakcie

KartaZ(w) == CASE w = "ok" /\ head = "nowa" -> "zaktualizowano"
               [] w = "ok" -> "porazka"
               [] w = "porazka" /\ head = "stara" -> "porazka"
               [] OTHER -> "nic"

KartaSlowami(w) == CASE w = "ok" /\ head = "nowa" -> "karta mowi 'Narzedzie zaktualizowane'"
                     [] w = "ok" -> "karta pokazuje porazke: 'ok' przy starej wersji to NIEOCZEKIWANY_BLAD"
                     [] w = "porazka" /\ head = "stara" -> "karta pokazuje porazke aktualizacji"
                     [] w = "porazka" -> "karta nic nie mowi: porazka z pliku jest sprzed nowej wersji (aktualizacja-wynik-stary)"
                     [] OTHER -> "karta nic nie mowi o aktualizacji"

StartCentrumZ(w) ==
    /\ centrum' = head
    /\ karta' \in {KartaZ(w), "nic"}
    /\ wynik' \in IF AwariaKopiowania /\ w /= "brak" THEN {"brak", w} ELSE {"brak"}
    /\ widzi' = "centrum"

StartCentrum == StartCentrumZ(wynik)

Klik ==
    /\ pc = "spoczynek"
    /\ centrum /= "brak"
    /\ klikniecia < MaxKlikniec \/ dziennik = "w_toku"
    /\ klikniecia' = IF dziennik = "w_toku" THEN klikniecia ELSE klikniecia + 1
    /\ karta' = "nic"
    /\ Idz("pobieranie", "ToolUpdates.start: tata klika 'Zaktualizuj narzedzie'")
    /\ UNCHANGED <<dysk, nowa, centrum, wynik, widzi>>

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

PrzywroceniePoOdmowie ==
    /\ pc = "przywrocenie_po_odmowie"
    /\ \/ /\ plikTaty' = "taty"
          /\ PoOdmowie("_DadFiles.set_aside (finally): plik taty wraca z kopii, klon bez zmian")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE, tresc taty tylko w dzienniku)")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

PrzywroceniePoWyjatku ==
    /\ pc = "przywrocenie_po_wyjatku"
    /\ \/ /\ plikTaty' = "taty"
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): plik taty wraca z kopii; wyjatek Gita, dziennik zostaje (NIEOCZEKIWANY_BLAD)")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Idz("spoczynek", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError (COFNIECIE_NIEUDANE), dziennik zostaje")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

PrzywroceniePoScaleniu ==
    /\ pc = "przywrocenie_po_scaleniu"
    /\ \/ /\ plikTaty' = "taty"
          /\ Idz("instalacja", "_DadFiles.set_aside (finally): plik taty wraca z kopii")
       \/ /\ AwariaKopiowania
          /\ plikTaty' = plikTaty
          /\ Cofaj("centrum", "_DadFiles.set_aside (finally): copy2 z kopii rzuca OSError; update() wola _roll_back")
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, ekran>>

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

NieudaneCofniecie(opis) ==
    /\ Idz(IF cofa \in {"opiekun", "opiekun_bez_portu"} THEN "opiekun_wynik" ELSE "spoczynek", opis)
    /\ widzi' = IF cofa = "skrot" THEN "okienko" ELSE widzi

KtoPokazujeNieudane == CASE cofa \in {"centrum", "klik"} -> "Centrum pokazuje COFNIECIE_NIEUDANE"
                         [] cofa = "skrot" -> "skrot konczy sie Komunikatem startu"
                         [] OTHER -> "opiekun zapisuje COFNIECIE_NIEUDANE"

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
          /\ plikTaty /= "brak"
          /\ plikTaty' = plikTaty
          /\ NieudaneCofniecie("_roll_back: (git.root / name).unlink rzuca OSError przed try, plik taty zostaje; " \o KtoPokazujeNieudane)
    /\ UNCHANGED <<head, kopia, biblioteki, dziennik, dzierzawa, nowa, centrum, klikniecia, wynik, karta>>

CofanieUsunUdane == CofanieUsun /\ pc' = "cofanie_reset"

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

SkrotWynik ==
    /\ pc = "skrot_wynik"
    /\ \/ /\ StartCentrumZ("porazka")
          /\ Idz("spoczynek", "launcher._roll_back: write_result(NIEOCZEKIWANY_BLAD); Centrum startuje od nowa z cofnietego klonu, karta pokazuje porazke aktualizacji")
       \/ /\ AwariaKopiowania
          /\ widzi' = "okienko"
          /\ UNCHANGED <<wynik, karta, centrum>>
          /\ Idz("spoczynek", "launcher._roll_back: write_result rzuca OSError; okienko NIEOCZEKIWANY_BLAD_STARTU, nic nie startuje")
    /\ UNCHANGED <<dysk, nowa, klikniecia>>

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

OpiekunKoniec ==
    /\ pc = "opiekun_koniec"
    /\ dziennik' = "brak"
    /\ kopia' = "brak"
    /\ dzierzawa' = "brak"
    /\ Idz("spoczynek", "restart_guardian.main: ToolClone.confirm_update usuwa dziennik")
    /\ UNCHANGED <<head, plikTaty, biblioteki, nowa, centrum, klikniecia, ekran>>

OpiekunWycofanie ==
    /\ pc = "opiekun_wycofanie"
    /\ \/ /\ wynik' = "brak"
          /\ Cofaj("opiekun", "restart_guardian.main: usuwa plik wyniku 'ok', potem _rolled_back")
       \/ /\ AwariaKopiowania
          /\ wynik /= "brak"
          /\ UNCHANGED wynik
          /\ Cofaj("opiekun", "restart_guardian.main: usuniecie pliku wyniku rzuca OSError, 'ok' zostaje; potem _rolled_back")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, karta, widzi>>

OpiekunWynik ==
    /\ pc = "opiekun_wynik"
    /\ LET dalej == IF dziennik = "brak" THEN "opiekun_port_stara" ELSE "okienko"
       IN \/ /\ wynik' = "porazka"
             /\ Idz(dalej, "restart_guardian.main: _record zapisuje wynik porazki po cofnieciu")
          \/ /\ AwariaKopiowania
             /\ UNCHANGED wynik
             /\ Idz(dalej, "restart_guardian.main: _record po cofnieciu, write_result rzuca OSError, opiekun idzie dalej")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, karta, widzi>>

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

OpiekunOkienko ==
    /\ pc = "okienko"
    /\ widzi' = "okienko"
    /\ Idz("spoczynek", "restart_guardian.main: show_problem pokazuje okienko not_started_after_update (return 1)")
    /\ UNCHANGED <<dysk, nowa, centrum, klikniecia, wynik, karta>>

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

DzierzawaMija ==
    /\ pc = "spoczynek"
    /\ skrot = "brak"
    /\ dzierzawa = "wazna"
    /\ dzierzawa' = "brak"
    /\ krok' = "mija termin opiekuna (GUARDIAN_LEASE_S)"
    /\ UNCHANGED <<head, plikTaty, kopia, biblioteki, dziennik, nowa, centrum, pc, klikniecia, slady, cofa, skrot, skrotyWTrakcie, ekran>>

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

DzialaOpiekun ==
    \/ pc \in {"opiekun_port", "opiekun_start", "opiekun_koniec", "opiekun_wycofanie", "opiekun_wynik",
              "opiekun_port_stara", "opiekun_start_stara"}
    \/ /\ pc \in {"cofanie_usun", "cofanie_reset", "cofanie_przywroc", "cofanie_przywroc_po_bledzie",
              "koniec_dziennika"}
       /\ cofa \in {"opiekun", "opiekun_bez_portu"}

SkrotWTrakcie ==
    /\ DzialaOpiekun
    /\ centrum = "brak"
    /\ skrot = "brak"
    /\ skrotyWTrakcie < MaxSkrotowWTrakcie
    /\ skrot' = "ma_port"
    /\ skrotyWTrakcie' = skrotyWTrakcie + 1
    /\ krok' = "tata klika skrot w trakcie ponownego startu: launcher._start zajmuje port (listen_locally)"
    /\ UNCHANGED <<dysk, nowa, centrum, pc, klikniecia, slady, cofa, ekran>>

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

Program ==
    \/ Pobranie \/ KopiaPlikow \/ CheckoutHead \/ Scalanie
    \/ PrzywroceniePoOdmowie \/ PrzywroceniePoScaleniu \/ PrzywroceniePoWyjatku \/ Instalacja \/ InstalacjaKoniec
    \/ CofanieUsun \/ CofanieReset \/ CofaniePrzywroc \/ KoniecDziennika \/ SkrotWynik
    \/ Restart \/ OpiekunPort \/ OpiekunStart \/ OpiekunKoniec \/ OpiekunWycofanie \/ OpiekunWynik
    \/ OpiekunPortStara \/ OpiekunStartStara
    \/ OpiekunOkienko
    \/ SkrotOddajePort

Next == Program \/ Klik \/ Wylacz \/ DzierzawaMija \/ Skrot \/ SkrotWTrakcie

Sprawiedliwosc ==
    /\ WF_vars(Program)
    /\ WF_vars(Klik)
    /\ WF_vars(Skrot)
    /\ SF_vars(DzierzawaMija)
    /\ SF_vars(CofanieUsunUdane)
    /\ SF_vars(CofanieResetUdane)
    /\ SF_vars(CofaniePrzywrocUdane)

Spec == Init /\ [][Next]_vars /\ Sprawiedliwosc

Postep == <>[][~Wylacz]_vars => (dziennik = "w_toku" ~> dziennik = "brak")

PostepPozaZnanymi == Postep \/ <>Po(WybaczonePostep)

=============================================================================
