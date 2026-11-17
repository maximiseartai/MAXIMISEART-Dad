"""Show that sprawdz_karte_uruchomienia.py fails when the TLA+ model of the browser card loses a guard the code has.

Each mutation removes from ``model/KartaUruchomienia.tla`` one guard or step whose counterpart in
``frontend/src/lib/runs.tsx``, ``frontend/src/pages/runs/runs-page.tsx`` or ``frontend/src/lib/tool-update.tsx`` the
mutation names, runs on its own copy of the checkout (``tools/lib/silnik_mutacji.py``) and must end the check with
``KARTA URUCHOMIENIA: NOWE NARUSZENIE``. A mutation that instead fixes the cause of one known finding the way the code
would must end it with ``KARTA URUCHOMIENIA: ZNALEZISKO ZNIKNĘŁO``: the fix of one finding is not hidden by another
one. A mutation whose anchor text is no longer in the model is reported as
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
MODEL = Path(".agents/skills/verify-karta-uruchomienia/model/KartaUruchomienia.tla")
CHECK = ".agents/skills/verify-karta-uruchomienia/scripts/sprawdz_karte_uruchomienia.py"
NEW = "KARTA URUCHOMIENIA: NOWE NARUSZENIE"
GONE = "KARTA URUCHOMIENIA: ZNALEZISKO ZNIKNĘŁO"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


MUTATIONS = (
    Mutation(
        "start czeka na strumień także wtedy, gdy latest pokazuje przyjęte Uruchomienie (runs.tsx: bez return po"
        " shownRun(latest.current) === accepted)",
        (
            Edit(
                MODEL,
                "            /\\ IF ShownRun(widok) = startuje.wynik\n",
                "            /\\ IF FALSE\n",
            ),
        ),
        _check("jedna-karta"),
        "strumień pokazał start i wynik przed odpowiedzią, a karta czeka na kolejny widok i przyciski startu zostają"
        " wyłączone (PrzyciskWraca)",
        NEW,
    ),
    Mutation(
        'start nie kończy się na idle (runs.tsx streamShows: bez || next.state === "idle")',
        (
            Edit(
                MODEL,
                '(ShownRun(e.w) # startuje.przed \\/ e.w.stan = "idle")',
                "(ShownRun(e.w) # startuje.przed)",
            ),
        ),
        _check("restart"),
        "Centrum startuje ponownie w trakcie startu z karty pokazującej idle, a start czeka bez końca (PrzyciskWraca)",
        NEW,
    ),
    Mutation(
        "Decyzja czeka na strumień, choć latest już nie pokazuje Decyzji (runs.tsx: bez if awaitsDecision(latest))",
        (
            Edit(
                MODEL,
                '    /\\ decyduje\' = IF decyduje.wynik = "blad" \\/ ~AwaitsDecision(widok, decyduje.run)\n',
                '    /\\ decyduje\' = IF decyduje.wynik = "blad"\n',
            ),
        ),
        _check("jedna-karta"),
        "strumień pokazał odpowiedź na Decyzję i wynik przed odpowiedzią HTTP, a przyciski Decyzji czekają bez końca"
        " (PrzyciskWraca)",
        NEW,
    ),
    Mutation(
        "Decyzja nie kończy się na widoku bez niej (runs.tsx streamShows: !awaitsDecision(next, runId) zawsze fałsz)",
        (
            Edit(
                MODEL,
                '/\\ decyduje\' = IF decyduje.faza = "czeka" /\\ ~AwaitsDecision(e.w, decyduje.run)',
                '/\\ decyduje\' = IF decyduje.faza = "czeka" /\\ FALSE',
            ),
        ),
        _check("jedna-karta"),
        "po Decyzji przyciski zostają wyłączone, choć strumień pokazuje, że Uruchomienie trwa dalej (PrzyciskWraca)",
        NEW,
    ),
    Mutation(
        "przyjęty start nie czyści wyboru (runs.tsx: bez setDraft(null))",
        (
            Edit(
                MODEL,
                "       ELSE /\\ draft' = FALSE\n",
                "       ELSE /\\ draft' = draft\n",
            ),
        ),
        _check("jedna-karta"),
        "tata wybiera proces na karcie startu i uruchamia, a po końcu widzi kartę startu zamiast wyniku (WynikNaKarcie)",
        NEW,
    ),
    Mutation(
        "odłożony wynik to każdy wynik (runs-page.tsx RunOrSetup: run.id === dismissed zamiast dismissed !== null)",
        (
            Edit(
                MODEL,
                "SetupInstead(v) == Run(v) = Brak \\/ (Ended(v) /\\ (Run(v) = odlozony \\/ draft))",
                "SetupInstead(v) == Run(v) = Brak \\/ (Ended(v) /\\ (odlozony # Brak \\/ draft))",
            ),
        ),
        _check("jedna-karta"),
        "po „Nowe Uruchomienie procesu” wynik następnego Uruchomienia zasłania karta startu (WynikNaKarcie)",
        NEW,
    ),
    Mutation(
        'przycisk aktualizacji wyłączony tylko na czas startu (tool-update.tsx shownOf: busy bez matches("polling"))',
        (
            Edit(
                MODEL,
                'Busy == ms \\in {"starting", "czeka", "pyta"}',
                'Busy == ms = "starting"',
            ),
        ),
        _check("aktualizacja"),
        "po odpowiedzi startu przycisk „Zaktualizuj narzędzie” wraca, choć aktualizacja trwa (AktualizacjaNieWraca)",
        NEW,
    ),
    Mutation(
        "Centrum bez odpowiedzi w pętli to porażka, nie ponowny start (tool-update-machine.ts: onError poll do idle"
        " z failed zamiast waiting z running/restarting)",
        (
            Edit(
                MODEL,
                '       THEN /\\ zad\' = Nic /\\ ms\' = "czeka" /\\ Pokaz("running")\n',
                '       THEN /\\ zad\' = Nic /\\ ms\' = "idle" /\\ Pokaz("failed")\n',
            ),
        ),
        _check("aktualizacja"),
        "w czasie ponownego startu karta pokazuje porażkę i przycisk, choć aktualizacja trwa (AktualizacjaNieWraca)",
        NEW,
    ),
    Mutation(
        "read przyjęty w każdym stanie (tool-update-machine.ts: read na poziomie maszyny zamiast tylko w idle)",
        (
            Edit(
                MODEL,
                '    /\\ IF ms = "idle" THEN ms\' = "reading"',
                '    /\\ IF ms \\in {"idle", "czeka", "pyta"} THEN ms\' = "reading"',
            ),
        ),
        _check("aktualizacja"),
        "wejście na stronę w trakcie aktualizacji przerywa odpytywanie: przycisk wraca, a karta się nie przeładuje"
        " (AktualizacjaNieWraca)",
        NEW,
    ),
    Mutation(
        "settled nie odpytuje po odczycie running (tool-update-machine.ts choice: zawsze idle)",
        (
            Edit(
                MODEL,
                'PoStanie(s) == IF s = "running" THEN "czeka" ELSE "idle"',
                'PoStanie(s) == "idle"',
            ),
        ),
        _check("aktualizacja"),
        "karta odczytuje trwającą aktualizację i pokazuje przycisk zamiast kroku (AktualizacjaNieWraca)",
        NEW,
    ),
)


if __name__ == "__main__":
    narzedzia_dla_kopii(ROOT)
    raise SystemExit(check_all(MUTATIONS))
