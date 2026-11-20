from __future__ import annotations

import straznik
from straznik import Guard, Kind
from szablon_werdyktu import Mechanism
from stan_pr import Pull
import werdykt_pr

ZASADY = """Szczebel strażnika ([ADR 0046](../../docs/adr/0046-szczebel-straznika-wybiera-recenzent.md)): szczebel piramidy
z pola ``Mechanizm:`` Ważnego, które pisze recenzent (``szablon_werdyktu.Mechanism``), wybiera, jakie selektory
``Strażnik:`` przyjmuje warunek 5 ``tools/scal_pr.py``, a autor wybiera selektor tylko spośród nich (``ALLOWED``).
Szczebel Ważnego ``W<n> r<k>`` daje pole Ważnego werdyktu ``FAIL`` rundy ``k`` (``rejestr_korzeni.majors``), bo punkt
rozstrzygnięcia w „## Sprawdzone” zmienia kod korzenia, a nie szczebel.

| Szczebel | Przyjęty strażnik | Odmowa |
|---|---|---|
| ``architektura`` | ``mypy``, ``ruff`` albo ``ast-grep <id>``: strażnik obejścia nowej struktury (typ, zakaz ``TID251`` właściciela, reguła ast-grep) | każdy inny selektor; test zachowania właściciela stoi w PR obok, jako test Required CI, a nie w linii ``Strażnik:`` |
| ``refaktor``, ``lint`` | ``mypy``, ``ruff`` albo ``ast-grep <id>`` | każdy inny selektor |
| ``test``, ``weryfikacja`` | każdy selektor ``straznik.parse``, jak w ADR 0042 | żadna z tego warunku |

``brak - usunięte`` przy ``architektura``, ``refaktor`` i ``lint`` to odmowa z drogą: zakaz usuniętej nazwy
(``banned-api`` ruff, ``Strażnik: ruff``) albo reguła ast-grep na liniach z drzewa ``FAIL`` (``Strażnik: ast-grep
<id>``). Selektor odrzucony przez szczebel nie dostaje dowodu, a przyjęty dostaje go jak w ADR 0042 (``bramka_straznika``).
Ważne bez szczebla (werdykt ``FAIL`` wątku sprzed pola ``Mechanizm:`` albo opublikowany poza ``--werdykt`` bez niego)
przyjmuje każdy selektor.

Warunek obowiązuje od własnego wdrożenia (``MARKER``: ten moduł, jak ``bramka_straznika.MARKER`` i ``TEST_MARKER``;
``werdykt_pr.rule_applies``, decyzja Q20 ADR 0031), więc wątek z pierwszym werdyktem sprzed niego kończy po staremu,
z dowodem selektora, który wpisał autor. Moduł bierze tylko bibliotekę standardową, bo job ``status`` uruchamia
``tools/scal_pr.py`` Pythonem runnera bez zależności.
"""

MARKER = "tools/lib/szczebel_straznika.py"
BYPASS = frozenset({Kind.MYPY, Kind.RUFF, Kind.AST_GREP})
ALLOWED = {Mechanism.ARCHITEKTURA: BYPASS, Mechanism.REFAKTOR: BYPASS, Mechanism.LINT: BYPASS}
BYPASS_FORMS = f"{Kind.MYPY.value}, {Kind.RUFF.value} albo {Kind.AST_GREP.value} <id reguły>"


def applies(pull: Pull) -> bool:
    return werdykt_pr.rule_applies(pull, werdykt_pr.deployment(pull.base, MARKER))


def refusal(mechanism: Mechanism | None, guard: Guard) -> str | None:
    """Przyczyna, dla której szczebel ``mechanism`` nie przyjmuje strażnika ``guard``; ``None``, gdy go przyjmuje."""

    allowed = ALLOWED.get(mechanism) if mechanism is not None else None
    if allowed is None or guard.kind in allowed:
        return None
    wanted = f"{straznik.FIELD} {BYPASS_FORMS}"
    if mechanism is Mechanism.ARCHITEKTURA:
        wanted += " jako strażnik obejścia nowej struktury (typ, zakaz TID251 właściciela, reguła ast-grep), a test zachowania właściciela zostaje w PR obok"
    if guard.kind is Kind.REMOVED:
        wanted += "; usunięty kod zamyka zakaz jego powrotu: zakaz usuniętej nazwy w banned-api ruff (Strażnik: ruff) albo reguła ast-grep na liniach z drzewa FAIL (Strażnik: ast-grep <id>)"
    return f"Mechanizm: {mechanism} przyjmuje tylko {wanted}, a jest {straznik.FIELD} {guard}"
