"""Show that sprawdz_urwane_uruchomienie.py fails when the TLA+ model of the Dziennik Wyceny loses a guard the code has.

Each mutation removes from ``model/UrwaneUruchomienie.tla`` one guard or step whose counterpart in
``src/rozliczenia/centrum/pricing_journal.py``, ``run_logs.py``, ``app.py``, ``src/rozliczenia/efenix_pricing.py`` or
``process_run.py``
the mutation names, runs on its own copy of the checkout (``tools/mutacje.py``) and must end the check with
``URWANE URUCHOMIENIE: NOWE NARUSZENIE``. A mutation whose anchor text is no longer in the model is reported as
NIEAKTUALNA: update it to the new model.

The copy of the checkout has no ignored TLC cache, so this script hands Java and ``tla2tools.jar`` of this checkout
to every command through ``TLC_JAVA`` and ``TLC_JAR``.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

ROOT = Path(__file__).resolve().parents[4]
MODEL = Path(".agents/skills/verify-urwane-uruchomienie/model/UrwaneUruchomienie.tla")
CHECK = ".agents/skills/verify-urwane-uruchomienie/scripts/sprawdz_urwane_uruchomienie.py"
NEW = "URWANE URUCHOMIENIE: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


MUTATIONS = (
    Mutation(
        "dziennik usunięty, choć Outbox.post zwrócił False (send: bez if self._run_logs.send(record))",
        (
            Edit(
                MODEL,
                "          /\\ Dalej\n          /\\ UNCHANGED <<kolejka, inneZnaki,",
                "          /\\ krokWysylki' = \"usun\" /\\ UNCHANGED <<centrum, doWyslania>>\n"
                "          /\\ UNCHANGED <<kolejka, inneZnaki,",
            ),
        ),
        _check("logi-i-kolejka"),
        "Logi Urwanego Uruchomienia, których kolejka nie przyjęła, znikają razem z dziennikiem i nie dochodzą nigdy",
        NEW,
    ),
    Mutation(
        "start nie czyta wpisu końca (_closed: bez read.ended)",
        (Edit(MODEL, "        koniecZapisany == Zakonczony(r)\n", "        koniecZapisany == FALSE\n"),),
        _check("zwykle"),
        "Wycena, która dopisała „koniec Uruchomienia” i zgasła przed Logami, dostaje Logi Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "Wycena bez wpisu końca (create_app: after_run bez journal, PricingJournal.run_ended nie biegnie)",
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
        "Logi z wynikiem przed wpisem końca (create_app: after_run z run_logs przed journal)",
        (
            Edit(MODEL, "    /\\ faza' = \"koniec\"\n", "    /\\ faza' = \"logi\"\n"),
            Edit(MODEL, "\n    /\\ bieg' = 0 /\\ faza' = \"-\"\n", "\n    /\\ faza' = \"koniec\" /\\ UNCHANGED bieg\n"),
            Edit(MODEL, "    /\\ faza' = \"logi\" /\\ UNCHANGED bieg\n", "    /\\ faza' = \"-\" /\\ bieg' = 0\n"),
        ),
        _check("koniec"),
        "Logi z wynikiem poszły do kolejki bez pliku, Centrum gaśnie przed wpisem końca: Logi Urwanego Uruchomienia "
        "zastępują je w Skrzynce",
        NEW,
    ),
    Mutation(
        "dziennik zostaje po nieudanym wpisie końca (PricingJournal.run_ended: bez _remove)",
        (
            Edit(
                MODEL,
                "          /\\ UsunPlik(r, {})\n"
                "          /\\ bezKonca' = IF dziennik'[r] = \"brak\" THEN bezKonca\n"
                "                         ELSE [bezKonca EXCEPT ![r] = @ \\cup {\"wpis-konca-nieudany\"}]\n",
                "          /\\ UNCHANGED <<dziennik, wpisy, zgubiony, awarieUsuniecia, bezKonca>>\n",
            ),
        ),
        _check("koniec"),
        "Wycena, której wpis końca się nie zapisał, dostaje przy starcie Logi Urwanego Uruchomienia",
        NEW,
    ),
    Mutation(
        "plik Logów z wynikiem nie rozstrzyga (_closed: bez return None przy logged.ending != \"interrupted\")",
        (
            Edit(MODEL, "          /\\ dziennik[r] = \"jest\" /\\ ~koniecZapisany /\\ logi[r].rodzaj = \"wynik\"\n",
                 "          /\\ FALSE\n"),
            Edit(MODEL, "          /\\ dziennik[r] = \"jest\" /\\ ~koniecZapisany /\\ logi[r].rodzaj = \"brak\"\n",
                 "          /\\ dziennik[r] = \"jest\" /\\ ~koniecZapisany /\\ logi[r].rodzaj \\in {\"brak\", \"wynik\"}\n"),
        ),
        _check("koniec"),
        "Wycena z Logami z wynikiem, której wpis końca i usunięcie dziennika się nie udały, dostaje Logi Urwanego "
        "Uruchomienia",
        NEW,
    ),
    Mutation(
        "plik Logów zapisany przed strażnikiem (_closed: guard dopiero po self._run_logs.close(record))",
        (
            Edit(MODEL, "Odczytane(tresc) == krokZamykania' = \"zapisz\" /\\ rekord' = Straz(tresc)",
                 "Odczytane(tresc) == krokZamykania' = \"zapisz\" /\\ rekord' = tresc"),
            Edit(MODEL, "[bieg |-> kursor, tresc |-> rekord, niezapisany |-> niezapisany]",
                 "[bieg |-> kursor, tresc |-> Straz(rekord), niezapisany |-> niezapisany]"),
        ),
        _check("zwykle"),
        "plik Logów na dysku ma telefon i ulicę, a plik w Archiwum Logów okresu maskę: różne znaki",
        NEW,
    ),
    Mutation(
        "Logi Urwanego Uruchomienia bez strażnika (_closed: bez record = self._run_logs.guard(record))",
        (Edit(MODEL, "Straz(t) == [t EXCEPT !.tekst = \"strzezone\"]", "Straz(t) == t"),),
        _check("zwykle"),
        "telefon i ulica ze strony efenix idą do Skrzynki Zgłoszeń bez maski (ADR 0025)",
        NEW,
    ),
    Mutation(
        "Logi Urwanego Uruchomienia do kolejki przed Outbox.resume (create_app: send zaraz po close, nie w zależności)",
        (Edit(MODEL, "    /\\ centrum = \"zamyka\" /\\ kursor > Wyceny\n    /\\ wznowiona\n",
              "    /\\ centrum = \"zamyka\" /\\ kursor > Wyceny\n"),),
        _check("zwykle"),
        "kolejka dostaje wysyłkę przed swoim startem, czego model verify-kolejka-skrzynki nie sprawdza",
        NEW,
    ),
    Mutation(
        "bez zlecenia zaczętego bez wyniku (_read: begun zawsze None)",
        (Edit(MODEL, "        zaczete |-> IF Len(w) > 0 /\\ w[Len(w)].rodzaj = \"zaczete\" THEN w[Len(w)].z ELSE 0,",
              "        zaczete |-> 0,"),),
        _check("zwykle"),
        "Logi nie mówią, przy którym zleceniu Centrum zgasło, choć jego zmiany w efenix mogą być niepełne",
        NEW,
    ),
    Mutation(
        "„zaczynam zlecenie” po pierwszym działaniu okna efenix (save: journal.begun po _priced)",
        (
            Edit(MODEL, "faza' = \"zaczete\" /\\ zlecenie' = 1 /\\ naglowekCzeka' = TRUE",
                 "faza' = \"efenix\" /\\ zlecenie' = 1 /\\ naglowekCzeka' = TRUE"),
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
        "dziennik milknie po pierwszym nieudanym wpisie (PricingJournal._write: if self._failed: return na początku)",
        (
            Edit(
                MODEL,
                "    \\/ /\\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> rodzaj, z |-> zlecenie])]\n",
                "    \\/ /\\ przepadle[r] # {} /\\ UNCHANGED <<wpisy, dziennik, zapisanyStart, naglowekCzeka, awarieWpisu,\n"
                "                                      przepadle>>\n"
                "    \\/ /\\ przepadle[r] = {} /\\ wpisy' = [wpisy EXCEPT ![r] = Append(@, [rodzaj |-> rodzaj, z |-> zlecenie])]\n",
            ),
            Edit(MODEL, "    \\/ /\\ awarieWpisu < MaxAwariiWpisu /\\ awarieWpisu' = awarieWpisu + 1\n",
                 "    \\/ /\\ przepadle[r] = {} /\\ awarieWpisu < MaxAwariiWpisu /\\ awarieWpisu' = awarieWpisu + 1\n"),
        ),
        _check("wpisy"),
        "zlecenie, którego żaden wpis nie zawiódł, znika z Logów Urwanego Uruchomienia po nieudanym wpisie innego zlecenia",
        NEW,
    ),
    Mutation(
        "dziennik zostaje po przyjęciu Logów przez kolejkę (send: bez _remove(path, ...))",
        (Edit(MODEL, "    /\\ UsunPlik(Head(doWyslania).bieg, {})\n",
              "    /\\ UNCHANGED <<dziennik, wpisy, zgubiony, awarieUsuniecia>>\n"),),
        _check("zwykle"),
        "każdy start wysyła te same Logi Urwanego Uruchomienia znowu, a dziennik nie znika nigdy",
        NEW,
    ),
    Mutation(
        "start nie usuwa dziennika Wyceny z wynikiem (close: bez if closed is None: _remove(path, ...))",
        (Edit(MODEL, "    /\\ UsunPlik(kursor, {})\n", "    /\\ UNCHANGED <<dziennik, wpisy, zgubiony, awarieUsuniecia>>\n"),),
        _check("zwykle"),
        "dzienniki Wycen, które doszły do wyniku, zostają w logs/dzienniki-wyceny na zawsze",
        NEW,
    ),
    Mutation(
        "Logi Urwanego Uruchomienia z pliku wzięte za Logi z wynikiem (_closed: bez logged.ending != \"interrupted\")",
        (
            Edit(MODEL, "          /\\ dziennik[r] = \"jest\" /\\ ~koniecZapisany /\\ logi[r].rodzaj = \"wynik\"\n",
                 "          /\\ dziennik[r] = \"jest\" /\\ ~koniecZapisany /\\ logi[r].rodzaj \\in {\"wynik\", \"urwane\"}\n"),
            Edit(MODEL, "          /\\ dziennik[r] = \"jest\" /\\ ~koniecZapisany /\\ logi[r].rodzaj = \"urwane\"\n",
                 "          /\\ FALSE\n"),
        ),
        _check("zwykle"),
        "Logi Urwanego Uruchomienia zapisane, a niewysłane przed zgaśnięciem, nie dochodzą nigdy, a dziennik znika",
        NEW,
    ),
)


def _tlc_from_checkout() -> None:
    """Java i ``tla2tools.jar`` tego checkoutu (narzędzia ``sprawdz_aktualizacje.py``) dla poleceń w kopiach."""

    tools = ROOT / ".agents" / "skills" / "verify-aktualizacja-narzedzia" / "scripts" / "sprawdz_aktualizacje.py"
    spec = importlib.util.spec_from_file_location("sprawdz_aktualizacje", tools)
    if spec is None or spec.loader is None:
        sys.exit(f"BŁĄD: nie da się wczytać {tools}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    os.environ.setdefault("TLC_JAVA", module._java())
    os.environ.setdefault("TLC_JAR", str(module._tla_tools()))


if __name__ == "__main__":
    _tlc_from_checkout()
    raise SystemExit(check_all(MUTATIONS))
