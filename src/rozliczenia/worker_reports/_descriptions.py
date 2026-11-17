"""Błąd opisu we Wpisie raportu (ADR 0039): Wpis ``tak``, którego czynności Legenda czynności czyta jako Błąd opisu.

Wpisanie raportów wpisuje taki Wpis jak każdy i daje przy nim problem ``FaultyDescription`` (``entered``); Przypomnień o
raporcie Błąd opisu nie dotyczy, bo raport z nim jest przysłany (ADR 0041). Opis Wpisu ``nie`` to powód
nieskuteczności, więc legenda go nie czyta, a Wpis bez ``tak`` ani ``nie`` niczego nie wpisuje i ma swój problem
(``MissingVerdict``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ..activity_legend import ActivityLegend, DescriptionError
from ._matching import Addition
from ._model import FaultyDescription, Login, OrderNumber, ReportEntry, Verdict


def faulty(
    legend: ActivityLegend, worker: Login, day: date, number: OrderNumber, verdict: Verdict | None, activities: str
) -> FaultyDescription | None:
    """Błąd opisu Wpisu ``tak`` zlecenia ``number`` od ``worker`` z dnia ``day`` z czynnościami ``activities``; ``None``
    przy opisie bez Błędu opisu i przy Wpisie bez ``tak``."""

    if verdict is not Verdict.YES:
        return None
    read = legend.read(activities)
    return FaultyDescription(worker, day, number, read.problems) if isinstance(read, DescriptionError) else None


def entered(
    legend: ActivityLegend, targets: Iterable[tuple[Login, date, ReportEntry]], additions: Iterable[Addition]
) -> tuple[FaultyDescription, ...]:
    """Problemy wpisanych Wpisów ``tak`` z Błędem opisu: zwycięskich Wpisów zleceń z nadawcą i dniem, w którym tata
    widzi ich problem (``_matching.Matched.entered``), i Zleceń dopisanych z raportu po poprawionych mailach."""

    found = [
        *(faulty(legend, worker, day, entry.number, entry.verdict, entry.activities) for worker, day, entry in targets),
        *(faulty(legend, added.worker, added.day, added.number, added.verdict, added.activities) for added in additions),
    ]
    return tuple(fault for fault in found if fault is not None)

