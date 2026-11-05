"""Show that sprawdz_wznowienie_wyceny.py fails when the TLA+ model of resuming Wycena w efenix loses a guard the code has.

Each mutation removes from ``model/WznowienieWyceny.tla`` one guard or step whose counterpart in
``src/rozliczenia/efenix_pricing.py`` or ``src/rozliczenia/efenix_emmett_trace.py`` the mutation names, runs on its own
copy of the checkout (``tools/mutacje.py``) and must end the check with ``WZNOWIENIE WYCENY: NOWE NARUSZENIE``. A
mutation whose anchor text is no longer in the model is reported as NIEAKTUALNA: update it to the new model.

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
MODEL = Path(".agents/skills/verify-wznowienie-wyceny-efenix/model/WznowienieWyceny.tla")
CHECK = ".agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py"
NEW = "WZNOWIENIE WYCENY: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


MUTATIONS = (
    Mutation(
        "Wycena Emmetta także do zlecenia z wyceną (_outcome: bez gałęzi opened.amount != 0)",
        (Edit(MODEL, "    /\\ IF Kwota(q) # 0\n       THEN IF q = Plik", "    /\\ IF FALSE\n       THEN IF q = Plik"),),
        _check("zwykle"),
        "ponowne Uruchomienie ładuje Emmetta do zlecenia z wyceną i czyści ilości, także tacie",
        NEW,
    ),
    Mutation(
        "zlecenie nie przechodzi w stan „gotowe” śladu (_priced: bez trace.finished)",
        (Edit(MODEL, "    /\\ IF wPamieci[zlecenie] = \"zaladowany\"\n       THEN Zapisz(zlecenie, \"gotowe\")",
              "    /\\ IF FALSE\n       THEN Zapisz(zlecenie, \"gotowe\")"),),
        _check("zwykle"),
        "ilość, którą tata usunął ze zlecenia skończonego przez proces, ponowne Uruchomienie dopisuje z powrotem (#757)",
        NEW,
    ),
    Mutation(
        "dokańczanie wyceny bez śladu (_outcome: bez emmett is None)",
        (Edit(MODEL, "ELSE IF wPamieci[zlecenie] # \"zaladowany\" \\/ ~JakPoEmmetcie(q)", "ELSE IF ~JakPoEmmetcie(q)"),),
        _check("zwykle"),
        "każdą wycenę, która wygląda jak po Emmetcie, ponowne Uruchomienie dokańcza, także tę, z której tata usunął ilość",
        NEW,
    ),
    Mutation(
        "dokańczanie wyceny ze śladu bez porównania strony (_outcome: bez as_left_after_emmett)",
        (Edit(MODEL, "ELSE IF wPamieci[zlecenie] # \"zaladowany\" \\/ ~JakPoEmmetcie(q)", "ELSE IF wPamieci[zlecenie] # \"zaladowany\""),),
        _check("tata-po-przerwaniu"),
        "do wyceny, w której tata po Zatrzymaniu zmienił ilość Emmetta, ponowne Uruchomienie dopisuje ilości pliku",
        NEW,
    ),
    Mutation(
        "Znacznik przy każdym zleceniu z wynikiem (_mark: bez isinstance(result.outcome, Ready))",
        (Edit(MODEL, "znacznik[o] \\/ wynik[o] = \"gotowe\"]", "znacznik[o] \\/ wynik[o] # \"brak\"]"),),
        _check("przerwania"),
        "Znacznik efenix staje przy zleceniu z błędem „wycena już jest i się różni”",
        NEW,
    ),
    Mutation(
        "nieudany zapis śladu nie usuwa pliku (EmmettTrace._save: bez unlink)",
        (Edit(MODEL, "          /\\ naDysku' = [z \\in Zlecenia |-> \"brak\"]\n", "          /\\ naDysku' = naDysku /\\ naDysku # wPamieci'\n"),),
        _check("slad"),
        "ślad z „Emmett załadowany” zostaje przy zleceniu skończonym, gdy sam zapis się nie udał, i usunięta ilość wraca",
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
