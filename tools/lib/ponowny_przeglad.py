from __future__ import annotations

from collections.abc import Sequence

import szablon_werdyktu

ZASADY = """Ponowny przegląd tego samego HEAD (skill ``przeglad``, „Kolejne rundy”): werdykt dla SHA, który ma już werdykt
w tym PR, ma w „## Sprawdzone” punkt ``Ponowny przegląd: <zdanie>`` (``POINT``). Zdanie mówi, czemu ten SHA dostaje
kolejny przegląd, i podaje punkty „Do sprawdzenia” ze zlecenia tej rundy.

Drugi werdykt tego samego SHA zmienia zgodę bez zmiany kodu: ``FAIL`` po ``PASS`` po tezie koordynatora (#875,
runda 3, #950) albo ``PASS`` po ``FAIL``, gdy autor kwestionuje Ważne bez pushu. Punkt zostawia na PR ślad, skąd ten
werdykt się wziął.

Wcześniejszy werdykt to komentarz albo recenzja konta z prawem zapisu z linią ``WERDYKT: PASS|FAIL <SHA HEAD>``
(``werdykt_pr.read``); recenzja ``CHANGES_REQUESTED`` bez tej linii nim nie jest. Punkt sprawdzają ``--werdykt``
przed publikacją i zgoda na merge dla najnowszego werdyktu HEAD, także dla ``PASS`` opublikowanego z pominięciem
``--werdykt``. Obie drogi czytają ten sam HTML renderera GitHuba co szablon (``szablon_werdyktu``), więc punkt w bloku
kodu się nie liczy. Reguła obowiązuje w wątku z szablonem, którego najstarszy werdykt nie powstał przed wdrożeniem
tego modułu (``werdykt_pr.rule_applies`` z chwilą ``werdykt_pr.deployment`` dla pliku ``MARKER``, decyzja Q20).

Granica: narzędzie nie widzi zlecenia, więc nie sprawdza, czy zdanie punktu jest prawdziwe ani czy podaje każdy punkt
„Do sprawdzenia”; ocenia to recenzent następnej rundy.
"""

MARKER = "tools/lib/ponowny_przeglad.py"
POINT = "Ponowny przegląd: "


def problem(units: Sequence[szablon_werdyktu.Item]) -> str | None:
    """Przyczyna odmowy werdyktu ponownego przeglądu o jednostkach treści ``units`` (``szablon_werdyktu.items``),
    gdy nie ma punktu listy, który zaczyna się od ``POINT``; ``None``, gdy jest. Tekst jednostki jest bez odstępów na
    brzegach, więc punkt bez zdania (``Ponowny przegląd:``) się od niego nie zaczyna. Punkt listy stoi w szablonie
    tylko w „## Sprawdzone”, a werdykt z punktem gdzie indziej odrzuca szablon, więc miejsca punktu ta funkcja nie
    sprawdza."""

    if any(item.kind == "point" and item.text.startswith(POINT) for item in units):
        return None
    return (
        f"HEAD PR ma już werdykt, więc ten to ponowny przegląd tego samego SHA (skill przeglad, „Kolejne rundy”):"
        f" dopisz w „## {szablon_werdyktu.CHECKED}” punkt „- {POINT}<czemu kolejny przegląd tego SHA i punkty"
        f" „Do sprawdzenia” ze zlecenia>”"
    )
