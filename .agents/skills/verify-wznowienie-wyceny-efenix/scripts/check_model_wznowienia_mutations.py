"""Show that sprawdz_wznowienie_wyceny.py fails when the TLA+ model of resuming Wycena w efenix loses a guard the code has.

Each mutation removes from ``model/WznowienieWyceny.tla`` one guard or step whose counterpart in
``src/rozliczenia/efenix_pricing.py``, ``src/rozliczenia/efenix_checks.py`` or ``src/rozliczenia/efenix_positions.py``
the mutation names, runs on its own
copy of the checkout (``tools/mutacje.py``) and must end the check with ``WZNOWIENIE WYCENY: NOWE NARUSZENIE``. A mutation whose anchor text is no longer in the model is reported as
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
MODEL = Path(".agents/skills/verify-wznowienie-wyceny-efenix/model/WznowienieWyceny.tla")
CHECK = ".agents/skills/verify-wznowienie-wyceny-efenix/scripts/sprawdz_wznowienie_wyceny.py"
NEW = "WZNOWIENIE WYCENY: NOWE NARUSZENIE"


def _check(config: str) -> tuple[str, ...]:
    return (CHECK, "--config", config)


MUTATIONS = (
    Mutation(
        "Wycena Emmetta także do zlecenia z ilościami (_outcome: bez not _priced(opened))",
        (Edit(MODEL, "       ELSE IF q # Pusta\n       THEN Dokoncz(q)", "       ELSE IF FALSE\n       THEN Dokoncz(q)"),),
        _check("zwykle"),
        "ponowne Uruchomienie ładuje Emmetta do zlecenia z wyceną i czyści ilości, także tacie",
        NEW,
    ),
    Mutation(
        "dokończenie także w dół (completion: to_enter z każdą pozycją, w której strona ma inną ilość niż plik)",
        (Edit(MODEL, "DoWpisania(q) == {p \\in Pozycje : q[p] < Plik[p]}", "DoWpisania(q) == {p \\in Pozycje : q[p] # Plik[p]}"),),
        _check("zwykle"),
        "ilość, którą tata wpisał w efenix ponad plik, ponowne Uruchomienie obniża do pliku (NieObnizaIlosci)",
        NEW,
    ),
    Mutation(
        "ilość z pliku tylko w pozycjach pustych (completion: to_enter jak przed #960, bez pozycji z mniejszą ilością)",
        (
            Edit(
                MODEL,
                "DoWpisania(q) == {p \\in Pozycje : q[p] < Plik[p]}",
                "DoWpisania(q) == {p \\in Pozycje : q[p] = 0 /\\ Plik[p] # 0}",
            ),
        ),
        _check("zwykle"),
        "ilość Emmetta mniejsza niż plik (S, #960) zostaje, więc tata dostaje błąd kwoty w zleceniu, którego nie zmieniał",
        NEW,
    ),
    Mutation(
        "bez Ostrzeżenia Emmetta (_completed: bez if plan.excess)",
        (
            Edit(
                MODEL,
                'WynikDokonczenia(q) == IF Nadmiar(q) # {} THEN "ostrzezenie" ELSE',
                'WynikDokonczenia(q) == IF FALSE THEN "ostrzezenie" ELSE',
            ),
        ),
        _check("zwykle"),
        "zlecenie z ilością taty ponad plik kończy się błędem kwoty zamiast Ostrzeżenia Emmetta z pozycją",
        NEW,
    ),
    Mutation(
        "Znacznik przy każdym zleceniu z wynikiem (_mark: bez isinstance(result.outcome, Ready))",
        (Edit(MODEL, '[] wynik[o] = "gotowe" /\\ znacznik[o]', '[] wynik[o] # "brak" /\\ znacznik[o]'),),
        _check("zwykle"),
        "Znacznik efenix staje przy zleceniu z Ostrzeżeniem Emmetta",
        NEW,
    ),
    Mutation(
        "Przekazanie także zlecenia z Ostrzeżeniem albo błędem (_outcome: bez isinstance(outcome, Ready))",
        (Edit(MODEL, '    IF w = "gotowe" /\\ tryb = "z"\n', '    IF tryb = "z"\n'),),
        _check("zwykle"),
        "firma dostaje do akceptacji zlecenie, w którym efenix ma więcej niż Plik zbiorczy (PrzekazujeTylkoGotowe)",
        NEW,
    ),
    Mutation(
        "Przekazanie także w trybie bez Przekazania (_outcome: bez mode is PricingMode.FORWARD)",
        (Edit(MODEL, '    IF w = "gotowe" /\\ tryb = "z"\n', '    IF w = "gotowe"\n'),),
        _check("zwykle"),
        "tata uruchamia Wycenę bez Przekazania, a narzędzie i tak przekazuje gotowe zlecenia (PrzekazujeTylkoGotowe)",
        NEW,
    ),
    Mutation(
        "odmowa Przekazania jak Zlecenie przekazane (_forwarded: Forwarded zamiast OrderError(refusal))",
        (
            Edit(
                MODEL,
                "    /\\ slady' = [slady EXCEPT ![zlecenie] = slad]\n    /\\ wynik' = [wynik EXCEPT ![zlecenie] = \"blad\"]",
                "    /\\ slady' = [slady EXCEPT ![zlecenie] = slad]\n    /\\ wynik' = [wynik EXCEPT ![zlecenie] = \"przekazane\"]",
            ),
        ),
        _check("wszystko"),
        "zlecenie, któremu efenix odmówił Przekazania, ma Znacznik przekazania, choć jest „Do wyceny” (ZnacznikTylkoNaWycenionym)",
        NEW,
    ),
    Mutation(
        "zlecenie „Do akceptacji” otwierane jak „Do wyceny” (listing: bez Forwarded)",
        (Edit(MODEL, '    /\\ IF status[zlecenie] = "do akceptacji"\n', "    /\\ IF FALSE\n"),),
        _check("zwykle"),
        "ponowne Uruchomienie z Przekazaniem przekazuje zlecenie „Do akceptacji” drugi raz (NieZmieniaPrzekazanego)",
        NEW,
    ),
)


if __name__ == "__main__":
    narzedzia_dla_kopii(ROOT)
    raise SystemExit(check_all(MUTATIONS))
