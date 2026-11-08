"""Show that sprawdz_urwane_uruchomienie.py fails when the TLA+ model of the Dziennik Wyceny loses a guard the code has.

Each mutation removes from ``model/UrwaneUruchomienie.tla`` one guard or step whose counterpart in
``src/rozliczenia/centrum/run_comments.py``, ``comment_versions.py``, ``logs_disk.py``, ``run_logs_guard.py``, ``app.py``,
``src/rozliczenia/efenix_pricing.py`` or ``process_run.py``
the mutation names, runs on its own copy of the checkout (``tools/mutacje.py``) and must end the check with
``URWANE URUCHOMIENIE: NOWE NARUSZENIE``. A mutation whose anchor text is no longer in the model is reported as
NIEAKTUALNA: update it to the new model.

The copy of the checkout has no ignored TLC cache, so this script hands Java and ``tla2tools.jar`` of this checkout
to every command through ``TLC_JAVA`` and ``TLC_JAR`` (``model_tlc.narzedzia_dla_kopii``).
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import narzedzia_dla_kopii
from mutacje import Edit, Mutation, check_all

ROOT = Path(__file__).resolve().parents[4]
MODEL = Path(".agents/skills/verify-urwane-uruchomienie/model/UrwaneUruchomienie.tla")
CHECK = ".agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py"
NEW = "URWANE URUCHOMIENIE: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


_NO_RANK = (
    Edit(MODEL, "StopienZeStartu == 1  ", "StopienZeStartu == 0  "),
    Edit(MODEL, "StopienWlasny == 2    ", "StopienWlasny == 0    "),
)

MUTATIONS = (
    Mutation(
        "dziennik usunięty, choć Outbox.post zwrócił False (send_left_behind: bez if journal_after(...) == \"usuń\")",
        (
            Edit(
                MODEL,
                "          /\\ Dalej\n          /\\ UNCHANGED <<kolejka, najnowsza, inneZnaki,",
                "          /\\ krokWysylki' = \"usun\" /\\ UNCHANGED <<centrum, doWyslania>>\n"
                "          /\\ UNCHANGED <<kolejka, najnowsza, inneZnaki,",
            ),
        ),
        _check("logi-i-kolejka"),
        "Logi Urwanego Uruchomienia, których kolejka nie przyjęła, znikają razem z dziennikiem i nie dochodzą nigdy",
        NEW,
    ),
    Mutation(
        "start nie czyta wpisu końca (close: bez read.end)",
        (Edit(MODEL, "        koniecZapisany == Zakonczony(r)\n", "        koniecZapisany == FALSE\n"),),
        _check("zwykle"),
        "Wycena, która dopisała „koniec Uruchomienia” i zgasła przed Logami, dostaje Logi Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "Wycena bez wpisu końca (kolejność w RunComments.run_ended: bez kroku 1, Journal.end nie biegnie)",
        (
            Edit(
                MODEL,
                "          /\\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> \"koniec\", z |-> zlecenie])]\n",
                "          /\\ UNCHANGED wpisy\n",
            ),
        ),
        _check("zwykle"),
        "Wycena, która doszła do wyniku i zgasła przed Logami, dostaje Logi Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "wpis końca przed rekordem metryk (wpis końca w save albo w run_process przed MetricsStore.append)",
        (
            Edit(MODEL, "       ELSE faza' = \"wynik\" /\\ UNCHANGED zlecenie", "       ELSE faza' = \"koniec\" /\\ UNCHANGED zlecenie"),
            Edit(MODEL, "    /\\ faza' = \"logi\" /\\ UNCHANGED bieg\n", "    /\\ faza' = \"wynik\" /\\ UNCHANGED bieg\n"),
            Edit(MODEL, "    /\\ faza' = \"koniec\"\n", "    /\\ faza' = \"logi\"\n"),
        ),
        _check("zwykle"),
        "Centrum gaśnie po wpisie końca, a przed wynikiem: dziennik Urwanej Wyceny znika bez Logów Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "Logi z wynikiem przed wpisem końca (kolejność w RunComments.run_ended: _keep przed Journal.end)",
        (
            Edit(MODEL, "    /\\ faza' = \"koniec\"\n", "    /\\ faza' = \"logi\"\n"),
            Edit(MODEL, "    /\\ faza' = \"zaLogami\"\n", "    /\\ faza' = \"koniec\"\n"),
            Edit(MODEL, "    /\\ faza' = \"logi\" /\\ UNCHANGED bieg\n", "    /\\ faza' = \"zaLogami\" /\\ UNCHANGED bieg\n"),
        ),
        _check("koniec"),
        "Logi z wynikiem poszły do kolejki bez pliku, Centrum gaśnie przed wpisem końca: start daje Wycenie z wynikiem "
        "Logi Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "nieudany wpis końca usuwa dziennik przed Logami (Journal.end jak w #888: if header or not "
        "self._write(...): _remove)",
        (
            Edit(
                MODEL,
                "          /\\ bezKonca' = [bezKonca EXCEPT ![r] = @ \\cup {\"wpis-konca-nieudany\"}]\n"
                "          /\\ UNCHANGED <<dziennik, wpisy, awarieUsuniecia, zgubiony, bezWersji>>\n",
                "          /\\ UsunPlik(r, {})\n"
                "          /\\ bezKonca' = IF dziennik'[r] = \"brak\" THEN bezKonca\n"
                "                         ELSE [bezKonca EXCEPT ![r] = @ \\cup {\"wpis-konca-nieudany\"}]\n",
            ),
        ),
        _check("wpisy"),
        "wpis końca rzuca OSError, run_ended usuwa dziennik, a Centrum gaśnie przed Logami z wynikiem: komentarz zostaje "
        "na zawsze postępem „Uruchomienie trwa” (okno #910)",
        NEW,
    ),
    Mutation(
        "dziennik z pierwszą linią z nieudanego zapisu zostaje po wyniku (Journal.end: return przy "
        "self._header, bez _remove)",
        (
            Edit(MODEL, "          /\\ naglowekCzeka /\\ dziennik[r] = \"brak\"\n", "          /\\ naglowekCzeka\n"),
            Edit(MODEL, "          /\\ naglowekCzeka /\\ dziennik[r] = \"jest\"\n          /\\ UsunPlik(r, {})\n",
                 "          /\\ FALSE /\\ UsunPlik(r, {})\n"),
        ),
        _check("koniec"),
        "pierwszy wpis rzuca OSError po zapisie pierwszej linii, okno efenix staje, a Wycena z wynikiem dostaje przy "
        "starcie Logi Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "start usuwa dziennik z plikiem Logów bez wysyłki (close: Drop przy pliku Logów, jak start na main przed #910)",
        (
            Edit(
                MODEL,
                "          /\\ dziennik[r] = \"jest\" /\\ logi[r].rodzaj \\in ZLogami\n          /\\ Odczytane(logi[r])\n"
                "          /\\ UNCHANGED <<kursor, oczekujace, awarieOdczytu, poWyniku>>\n",
                "          /\\ dziennik[r] = \"jest\" /\\ logi[r].rodzaj \\in ZLogami\n          /\\ krokZamykania' = \"usun\"\n"
                "          /\\ UNCHANGED <<kursor, rekord, oczekujace, awarieOdczytu, poWyniku>>\n",
            ),
        ),
        _check("zwykle"),
        "Centrum gaśnie po pliku Logów z wynikiem, a przed ich wysyłką: start usuwa dziennik, a komentarz zostaje "
        "postępem",
        NEW,
    ),
    Mutation(
        "plik Logów zapisany przed strażnikiem (close_left_behind: write przed guard_logs, co odrzuca też mypy)",
        (
            Edit(MODEL, "Odczytane(odczytany) == krokZamykania' = \"zapisz\" /\\ rekord' = [odczytany EXCEPT !.tresc = Straz(@)]",
                 "Odczytane(odczytany) == krokZamykania' = \"zapisz\" /\\ rekord' = odczytany"),
            Edit(MODEL, "rodzaj |-> rekord.rodzaj, tresc |-> rekord.tresc,", "rodzaj |-> rekord.rodzaj, tresc |-> Straz(rekord.tresc),"),
        ),
        _check("zwykle"),
        "plik Logów na dysku ma telefon i ulicę, a plik w Archiwum Logów okresu maskę: różne znaki",
        NEW,
    ),
    Mutation(
        "Logi z dziennika bez strażnika (close: StandInLogs(record) bez guard_logs, co odrzuca też mypy)",
        (Edit(MODEL, "Straz(t) == [t EXCEPT !.tekst = \"strzezone\"]", "Straz(t) == t"),),
        _check("zwykle"),
        "telefon i ulica ze strony efenix idą do Skrzynki Zgłoszeń bez maski (ADR 0025)",
        NEW,
    ),
    Mutation(
        "wersja zastępcza do kolejki przed Outbox.resume (create_app: send_left_behind zaraz po close_left_behind, nie w lifespan)",
        (Edit(MODEL, "    /\\ centrum = \"zamyka\" /\\ kursor > Wyceny\n    /\\ wznowiona\n",
              "    /\\ centrum = \"zamyka\" /\\ kursor > Wyceny\n"),),
        _check("zwykle"),
        "kolejka dostaje wysyłkę przed swoim startem, czego model verify-kolejka-skrzynki nie sprawdza",
        NEW,
    ),
    Mutation(
        "bez zlecenia zaczętego bez wyniku (_read_journal: begun zawsze None)",
        (Edit(MODEL, "        zaczete |-> IF Len(w) > 0 /\\ w[Len(w)].rodzaj = \"zaczete\" THEN w[Len(w)].z ELSE 0,",
              "        zaczete |-> 0,"),),
        _check("zwykle"),
        "Logi nie mówią, przy którym zleceniu Centrum zgasło, choć jego zmiany w efenix mogą być niepełne",
        NEW,
    ),
    Mutation(
        "„zaczynam zlecenie” po pierwszym działaniu okna efenix (save: journal.begun po _outcome)",
        (
            Edit(MODEL, "    /\\ faza' = \"zaczete\"\n    /\\ UNCHANGED <<wpisy, logi,",
                 "    /\\ faza' = \"efenix\"\n    /\\ UNCHANGED <<wpisy, logi,"),
            Edit(MODEL, "    /\\ efenix' = [efenix EXCEPT ![bieg] = @ \\cup {zlecenie}]\n    /\\ faza' = \"skonczone\"",
                 "    /\\ efenix' = [efenix EXCEPT ![bieg] = @ \\cup {zlecenie}]\n    /\\ faza' = \"zaczete\""),
            Edit(MODEL, "    /\\ Wpis(\"zaczete\")\n    /\\ faza' = \"efenix\"", "    /\\ Wpis(\"zaczete\")\n    /\\ faza' = \"skonczone\""),
            Edit(MODEL, "       THEN zlecenie' = zlecenie + 1 /\\ faza' = \"zaczete\"",
                 "       THEN zlecenie' = zlecenie + 1 /\\ faza' = \"efenix\""),
        ),
        _check("zwykle"),
        "Centrum gaśnie po zmianie w efenix, a przed wpisem: zlecenia nie ma w Logach Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "dziennik milknie po pierwszym nieudanym wpisie (Journal._write: if self._failed: return na początku)",
        (
            Edit(
                MODEL,
                "    \\/ /\\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> rodzaj, z |-> zlecenie])]\n",
                "    \\/ /\\ przepadle[r] # {} /\\ UNCHANGED <<wpisy, dziennik, zapisanyStart, postepMozliwy, naglowekCzeka,\n"
                "                                      awarieWpisu, przepadle>>\n"
                "    \\/ /\\ przepadle[r] = {} /\\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> rodzaj, z |-> zlecenie])]\n",
            ),
            Edit(MODEL, "<<awarieWpisu, przepadle>>\n    \\/ /\\ awarieWpisu < MaxAwariiWpisu /\\ awarieWpisu' = awarieWpisu + 1\n",
                 "<<awarieWpisu, przepadle>>\n"
                 "    \\/ /\\ przepadle[r] = {} /\\ awarieWpisu < MaxAwariiWpisu /\\ awarieWpisu' = awarieWpisu + 1\n"),
        ),
        _check("wpisy"),
        "zlecenie, którego żaden wpis nie zawiódł, znika z Logów Urwanego Uruchomienia po nieudanym wpisie innego zlecenia",
        NEW,
    ),
    Mutation(
        "dziennik zostaje po przyjęciu wersji zastępczej przez kolejkę (send: bez _remove(path, ...))",
        (Edit(MODEL, "    /\\ UsunPlik(Head(doWyslania).bieg, {})\n",
              "    /\\ UNCHANGED <<dziennik, wpisy, zgubiony, bezWersji, awarieUsuniecia>>\n"),),
        _check("zwykle"),
        "każdy start wysyła tę samą wersję zastępczą znowu, a dziennik nie znika nigdy",
        NEW,
    ),
    Mutation(
        "start nie usuwa dziennika bez pierwszej linii (close: bez if closed is None: _remove(path, ...))",
        (Edit(MODEL, "    /\\ UsunPlik(kursor, {})\n", "    /\\ UNCHANGED <<dziennik, wpisy, zgubiony, bezWersji, awarieUsuniecia>>\n"),),
        _check("zwykle"),
        "dziennik z urwaną pierwszą linią zostaje w logs/dzienniki-wyceny na zawsze",
        NEW,
    ),
    Mutation(
        "pierwsza linia, której zapis przy starcie Wyceny się nie udał, nie idzie z następnym wpisem "
        "(Journal._append_locked: self._header = False także po OSError)",
        (Edit(MODEL, "          /\\ UNCHANGED <<dziennik, zapisanyStart, postepMozliwy, naglowekCzeka>>\n",
              "          /\\ naglowekCzeka' = FALSE /\\ UNCHANGED <<dziennik, zapisanyStart, postepMozliwy>>\n"),),
        _check("wpisy"),
        "dziennik bez pierwszej linii: start Centrum go usuwa, a zlecenia zmienione w efenix nie trafiają do żadnych Logów",
        NEW,
    ),
    Mutation(
        "postęp przed pierwszą linią dziennika na dysku (Journal.progress bez self._header, W1 rundy 1 #846)",
        (
            Edit(
                MODEL,
                "          /\\ UNCHANGED <<dziennik, zapisanyStart, postepMozliwy, naglowekCzeka>>\n",
                "          /\\ postepMozliwy' = [postepMozliwy EXCEPT ![r] = TRUE]\n"
                "          /\\ UNCHANGED <<dziennik, zapisanyStart, naglowekCzeka>>\n",
            ),
        ),
        _check("wpisy"),
        "zapis pierwszej linii przy starcie Wyceny rzuca OSError, postęp idzie, a Centrum gaśnie przed następnym wpisem: "
        "dziennika nie ma, więc komentarz zostaje na zawsze postępem „Uruchomienie trwa”",
        NEW,
    ),
    Mutation(
        "dziennik znika za Logami, choć kolejka ich nie przyjęła (RunComments.run_ended: Journal.remove bez journal_after)",
        (Edit(MODEL, "    /\\ IF wKolejce /\\ ~naglowekCzeka\n", "    /\\ IF ~naglowekCzeka\n"),),
        _check("logi-i-kolejka"),
        "Outbox.post Logów z wynikiem zwraca False, a dziennik znika: komentarz zostaje na zawsze postępem",
        NEW,
    ),
    Mutation(
        "wersja tylko z chwili, bez stopnia (outbox.py: wersja z nazwy pliku jak przed #910; kod rundy 3 #846, W1)",
        _NO_RANK,
        _check("logi-i-kolejka"),
        "plik Logów z wynikiem się nie zapisał, kolejka przyjęła Logi z wynikiem, Centrum gaśnie przed krokiem 4, a "
        "wynik bez Logów ze startu jest nowszy i zastępuje je w kolejce i w Skrzynce",
        NEW,
    ),
    Mutation(
        "wersja tylko z chwili, bez stopnia, przy cofniętym zegarze (outbox.py: wersja z nazwy pliku jak przed #910, D2)",
        _NO_RANK,
        _check("zegar"),
        "postęp czeka w kolejce, Centrum gaśnie, zegar cofa się, a Logi Urwanego Uruchomienia ze startu są starsze od "
        "postępu: kolejka je zdejmuje, a komentarz zostaje postępem",
        NEW,
    ),
    Mutation(
        "wersja zastępcza ze stopniem Logów z wynikiem (rank_of: Rank.OWN zamiast Rank.STAND_IN dla StandInLogs)",
        (Edit(MODEL, "StopienZeStartu == 1  ", "StopienZeStartu == 2  "),),
        _check("logi-i-kolejka"),
        "wynik bez Logów ze startu zastępuje Logi z wynikiem, które kolejka przyjęła bez ich pliku",
        NEW,
    ),
    Mutation(
        "postęp ze stopniem wersji zastępczej (rank_of: Rank.STAND_IN zamiast Rank.DRAFT dla ProgressVersion)",
        (Edit(MODEL, "StopienPostepu == 0 ", "StopienPostepu == 1 "),),
        _check("zegar"),
        "po cofnięciu zegara postęp w kolejce jest nowszy od Logów Urwanego Uruchomienia ze startu",
        NEW,
    ),
    Mutation(
        "kod main przed #910: start usuwa dziennik z wpisem końca albo z Logami z wynikiem bez wysyłki, nieudany wpis "
        "końca usuwa dziennik, bez usunięcia dziennika za Logami i bez stopnia wersji (W2)",
        (
            *_NO_RANK,
            Edit(
                MODEL,
                "          /\\ dziennik[r] = \"jest\" /\\ logi[r].rodzaj = \"brak\" /\\ koniecZapisany\n"
                "          /\\ oczekujace' = Append(oczekujace, [bieg |-> r, rodzaj |-> \"bezLogow\", tresc |-> Pusta,\n"
                "                                               niezapisany |-> FALSE])\n"
                "          /\\ kursor' = kursor + 1\n"
                "          /\\ UNCHANGED <<krokZamykania, rekord, awarieOdczytu, poWyniku>>\n",
                "          /\\ dziennik[r] = \"jest\" /\\ logi[r].rodzaj = \"brak\" /\\ koniecZapisany\n"
                "          /\\ krokZamykania' = \"usun\"\n"
                "          /\\ UNCHANGED <<kursor, rekord, oczekujace, awarieOdczytu, poWyniku>>\n",
            ),
            Edit(
                MODEL,
                "          /\\ dziennik[r] = \"jest\" /\\ logi[r].rodzaj \\in ZLogami\n",
                "          /\\ dziennik[r] = \"jest\" /\\ logi[r].rodzaj = \"urwane\"\n",
            ),
            Edit(
                MODEL,
                "       \\/ \\* bez pliku Logów i bez wpisu końca: StandInLogs(guard_logs(interrupted(read), forbidden))\n",
                "       \\/ /\\ dziennik[r] = \"jest\" /\\ logi[r].rodzaj = \"wynik\"\n"
                "          /\\ krokZamykania' = \"usun\"\n"
                "          /\\ UNCHANGED <<kursor, rekord, oczekujace, awarieOdczytu, poWyniku>>\n"
                "       \\/ \\* bez pliku Logów i bez wpisu końca: StandInLogs(guard_logs(interrupted(read), forbidden))\n",
            ),
            Edit(MODEL, "    /\\ IF wKolejce /\\ ~naglowekCzeka\n", "    /\\ IF FALSE\n"),
            Edit(
                MODEL,
                "          /\\ bezKonca' = [bezKonca EXCEPT ![r] = @ \\cup {\"wpis-konca-nieudany\"}]\n"
                "          /\\ UNCHANGED <<dziennik, wpisy, awarieUsuniecia, zgubiony, bezWersji>>\n",
                "          /\\ UsunPlik(r, {})\n"
                "          /\\ bezKonca' = IF dziennik'[r] = \"brak\" THEN bezKonca\n"
                "                         ELSE [bezKonca EXCEPT ![r] = @ \\cup {\"wpis-konca-nieudany\"}]\n",
            ),
        ),
        _check("zwykle"),
        "Centrum gaśnie po wpisie końca, a przed przyjęciem Logów z wynikiem: start usuwa dziennik bez wysyłki, a "
        "komentarz zostaje na zawsze postępem „Uruchomienie trwa”",
        NEW,
    ),
)


if __name__ == "__main__":
    narzedzia_dla_kopii(ROOT)
    raise SystemExit(check_all(MUTATIONS))
