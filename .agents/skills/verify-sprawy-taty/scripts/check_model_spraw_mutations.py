"""Show that sprawdz_sprawy_taty.py fails when the TLA+ model of the Sprawy taty loses a guard the code has.

Each mutation removes from ``model/SprawyTaty.tla`` one guard or step whose counterpart in
``src/rozliczenia/centrum/reports.py``, ``dad_cases.py``, ``dad_notes.py`` or ``case_delivery.py`` the mutation names,
runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must end the check with
``SPRAWY TATY: NOWE NARUSZENIE``. A mutation whose anchor text is no longer in the model is reported as NIEAKTUALNA:
update it to the new model.

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
MODEL = Path(".agents/skills/verify-sprawy-taty/model/SprawyTaty.tla")
CHECK = ".agents/skills/verify-sprawy-taty/scripts/sprawdz_sprawy_taty.py"
NEW = "SPRAWY TATY: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


MUTATIONS = (
    Mutation(
        "Reports._queue bez finally: sprawa zostaje, gdy Outbox.post zwrócił False",
        (Edit(MODEL, "    /\\ Zapisz(Wycofana(sprawy, req.sid))\n", "    /\\ Zapisz(sprawy)\n"),),
        _check("kolejka"),
        "Zgłoszenie, którego pliku kolejka nie zapisała, czeka bez pliku, a _pending zatrzymuje każde następne kliknięcie",
        NEW,
    ),
    Mutation(
        "dad_notes.send bez cases.forget po False",
        (Edit(MODEL, "    /\\ Zapisz(Zapomniana(sprawy, uwaga.id))\n", "    /\\ Zapisz(sprawy)\n"),),
        _check("kolejka"),
        "Uwaga taty, której kolejka nie zapisała, czeka w Powiadomieniach na zawsze",
        NEW,
    ),
    Mutation(
        "_CaseDelivery.delivered bez DadCases.numbered",
        (
            Edit(
                MODEL,
                "                   /\\ Zapisz(Numerowane(sprawy, p.rodzaj, p.id, nr))\n",
                "                   /\\ Zapisz(sprawy)\n",
            ),
        ),
        _check("zwykle"),
        "kolejka usuwa plik doręczonej wysyłki, a sprawa nie dostaje numeru issue i czeka bez pliku",
        NEW,
    ),
    Mutation(
        "DadCases.queued bez _rejected: odrzucona treść czeka w kolejce",
        (Edit(MODEL, 'Czekajaca(odrz) == IF F \\in odrz THEN "odrzucone" ELSE "wKolejce"', 'Czekajaca(odrz) == "wKolejce"'),),
        _check("odrzucona"),
        "po odrzuceniu treści karta i „Wyślij do Maksa” mówią „czeka w kolejce”",
        NEW,
    ),
    Mutation(
        "ReportHandle._rejected bez _show: uchwyt nie pokazuje odrzucenia",
        (Edit(MODEL, "       ELSE /\\ karta' = \"odrzucone\"\n", "       ELSE /\\ UNCHANGED karta\n"),),
        _check("odrzucona"),
        "karta dalej mówi „czeka w kolejce”, choć Skrzynka odrzuciła treść",
        NEW,
    ),
    Mutation(
        "ReportHandle._delivered bez _show: uchwyt nie słyszy numeru issue",
        (
            Edit(
                MODEL,
                "            /\\ karta' = IF karta = \"wKolejce\" THEN \"wyslane\" ELSE karta\n",
                "            /\\ UNCHANGED karta\n",
            ),
        ),
        _check("zwykle"),
        "Zgłoszenie doręczone z kolejki po końcu czekania: karta mówi „czeka w kolejce” do końca pracy Centrum",
        NEW,
    ),
    Mutation(
        "ReportHandle.send bez sprawdzenia _pending po czekaniu (dostarczenie tuż po końcu czekania)",
        (
            Edit(
                MODEL,
                "    /\\ karta' = IF req.wynik = \"wKolejce\" /\\ ~CzekaZgl(sprawy) THEN \"wyslane\" ELSE req.wynik\n",
                "    /\\ karta' = req.wynik\n",
            ),
        ),
        _check("zwykle"),
        "numer issue przychodzi między DadCases.queued a końcem send: karta mówi „czeka w kolejce” do końca pracy Centrum",
        NEW,
    ),
)


if __name__ == "__main__":
    narzedzia_dla_kopii(ROOT)
    raise SystemExit(check_all(MUTATIONS))
