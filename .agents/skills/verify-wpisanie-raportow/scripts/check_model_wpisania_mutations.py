"""Show that sprawdz_wpisanie_raportow.py fails when the TLA+ model of a report cell loses a guard the code has.

Each mutation removes from ``model/WpisanieRaportow.tla`` one guard or step whose counterpart in
``src/rozliczenia/worker_reports/_cells.py``, ``src/rozliczenia/report_entering.py``,
``src/rozliczenia/centrum/report_entering_state.py`` or ``report_entering_run.py`` the mutation names, runs on its own
copy of the checkout (``tools/lib/silnik_mutacji.py``) and must end the check with
``WPISANIE RAPORTÓW: NOWE NARUSZENIE``. A mutation whose anchor text is no longer in the model is reported as
NIEAKTUALNA: update it to the new model.

The copy of the checkout has no ignored TLC cache, so this script hands Java and ``tla2tools.jar`` of this checkout
to every command through ``TLC_JAVA`` and ``TLC_JAR`` (``model_tlc.narzedzia_dla_kopii``).
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from model_tlc import narzedzia_dla_kopii
from silnik_mutacji import Edit, Mutation, check_all

ROOT = Path(__file__).resolve().parents[4]
MODEL = Path(".agents/skills/verify-wpisanie-raportow/model/WpisanieRaportow.tla")
CHECK = ".agents/skills/verify-wpisanie-raportow/scripts/sprawdz_wpisanie_raportow.py"
NEW = "WPISANIE RAPORTÓW: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


MUTATIONS = (
    Mutation(
        "Wpis także do komórki z ręczną wartością (_cells.reconcile bez `cell is None or cell == remembered`)",
        (
            Edit(
                MODEL,
                "Zmiana == IF ~BezZmian /\\ (komorka = Pusta \\/ komorka = migPamiec) THEN wpis ELSE Brak",
                "Zmiana == IF ~BezZmian THEN wpis ELSE Brak",
            ),
        ),
        _check("zwykle"),
        "nowy Wpis zastępuje w INTERMAX wartość, którą tata wpisał ręcznie",
        NEW,
    ),
    Mutation(
        "pamięć trzyma dawny własny wpis, którego komórki już nie ma (_cells.reconcile: own bez `if value in current[cell]`)",
        (
            Edit(
                MODEL,
                "    ELSE IF okresOtwarty /\\ migPamiec # Brak /\\ migPamiec = komorka THEN migPamiec\n",
                "    ELSE IF migPamiec # Brak THEN migPamiec\n",
            ),
        ),
        _check("zwykle"),
        "tata zmienia wpis narzędzia, kliknięcie to widzi, a gdy tata potem wpisze dawną wartość narzędzia, nowy Wpis ją "
        "nadpisuje",
        NEW,
    ),
    Mutation(
        "pamięć bez wpisu, który kliknięcie właśnie wpisało (_cells.reconcile bez `own[order.key, column] = value`)",
        (Edit(MODEL, "    IF Zmiana # Brak THEN Zmiana\n", "    IF FALSE THEN Zmiana\n"),),
        _check("okres"),
        "następny Wpis Wykonawcy pokazuje własny wpis narzędzia jako ręczną różnicę",
        NEW,
    ),
    Mutation(
        "Sprawdzanie czyta pamięć z dysku mimo treści odłożonej (_TextFile.text bez `if self.file.unavailable`)",
        (
            Edit(
                MODEL,
                "                /\\ migPamiec' = PamiecEfektywna\n",
                "                /\\ migPamiec' = IF p = \"udany\" THEN pamiecOdlozona ELSE pamiec\n",
            ),
        ),
        _check("pamiec"),
        "po nieudanym zapisie pamięci następne kliknięcie tej samej pracy Centrum bierze własne wpisy za ręczne",
        NEW,
    ),
    Mutation(
        "„Zostaw moją” bez blokady (FileReportState.keep bez `with self._deciding`)",
        (Edit(MODEL, "    /\\ blokada = 0\n    /\\ blokada' = k\n", "    /\\ blokada' = k\n"),),
        _check("dwie-karty"),
        "dwie karty klikają „Zostaw moją” naraz, a jedna decyzja ginie i jej różnica wraca",
        NEW,
    ),
    Mutation(
        "„Zostaw moją” zapisuje samą nową decyzję (FileReportState.keep bez `self.kept() |`)",
        (Edit(MODEL, "    /\\ LET nowe == odczyt[k] \\cup {tresc[k]} IN\n", "    /\\ LET nowe == {tresc[k]} IN\n"),),
        _check("dwie-karty"),
        "druga decyzja „Zostaw moją” usuwa pierwszą, więc jej różnica wraca",
        NEW,
    ),
    Mutation(
        "„Zostaw moją” czyta dawne decyzje z dysku mimo treści odłożonej (_TextFile.text bez `if self.file.unavailable`)",
        (
            Edit(
                MODEL,
                "    /\\ odczyt' = [odczyt EXCEPT ![k] = DecyzjeWidoku]\n",
                "    /\\ odczyt' = [odczyt EXCEPT ![k] = decyzje]\n",
            ),
        ),
        _check("decyzje"),
        "po nieudanym zapisie decyzji następne „Zostaw moją” zapisuje decyzje bez niej, choć Centrum nie zgasło",
        NEW,
    ),
    Mutation(
        "widok Raporty bez decyzji (_view bez `if problem.difference not in kept`)",
        (
            Edit(
                MODEL,
                "Widoczna == PokazanaRoznica # Brak /\\ PokazanaRoznica \\notin DecyzjeWidoku",
                "Widoczna == PokazanaRoznica # Brak",
            ),
        ),
        _check("dwie-karty"),
        "różnica, przy której tata kliknął „Zostaw moją”, zostaje w widoku do następnego kliknięcia",
        NEW,
    ),
    Mutation(
        "Sprawdzanie bez kopii konfliktu (report_entering.py: check bez `onedrive_conflicts.beside`)",
        (
            Edit(
                MODEL,
                "        /\\ LET zatrzymanie == kopia IN\n           IF zatrzymanie",
                "        /\\ LET zatrzymanie == FALSE IN\n           IF zatrzymanie",
            ),
        ),
        _check("kopia"),
        "kliknięcie czyta skrzynkę i pisze INTERMAX, choć zmiana pracownika leży w kopii konfliktu",
        NEW,
    ),
    Mutation(
        "koniec bez kopii konfliktu (enter_from_mail bez `onedrive_conflicts.beside` po zapisie)",
        (
            Edit(
                MODEL,
                "    /\\ LET zatrzymanie == kopia IN\n       przeoczonaKopia'",
                "    /\\ LET zatrzymanie == FALSE IN\n       przeoczonaKopia'",
            ),
        ),
        _check("kopia"),
        "tata dostaje podsumowanie, choć zmiana pracownika leży w kopii konfliktu obok INTERMAX",
        NEW,
    ),
)


if __name__ == "__main__":
    narzedzia_dla_kopii(ROOT)
    raise SystemExit(check_all(MUTATIONS))
