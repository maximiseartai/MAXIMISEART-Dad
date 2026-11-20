"""Opis zlecenia ``tak`` w Legendzie czynności (ADR 0041): Błąd opisu we Wpisie raportu i Kody czynności zlecenia dnia.

Wpisanie raportów wpisuje Wpis z Błędem opisu jak każdy i daje przy nim problem ``FaultyDescription`` (``entered``);
Przypomnień o raporcie Błąd opisu nie dotyczy, bo raport z nim jest przysłany. Zwykły opis obok kodów nie jest błędem,
a zlecenie ``tak`` bez żadnego Kodu czynności ma w widoku Raporty informację „BRAK KODU” (``codes``), nie problem. Opis
Wpisu ``nie`` to powód nieskuteczności, więc legenda go nie czyta, a Wpis bez ``tak`` ani ``nie`` niczego nie wpisuje i
ma swój problem (``MissingVerdict``).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from ..activity_legend import ActivityLegend, DescriptionError
from ..quantity_engine import QuantityRules, evaluated, is_fault
from ..text import normalize_text
from ._matching import Addition
from ._model import FaultyDescription, Login, OrderNumber, RegisterOrder, ReportEntry, Verdict


def faulty(
    legend: ActivityLegend,
    worker: Login,
    day: date,
    number: OrderNumber,
    verdict: Verdict | None,
    activities: str,
    *,
    fault: bool,
) -> FaultyDescription | None:
    """Błąd opisu Wpisu ``tak`` zlecenia ``number`` od ``worker`` z dnia ``day`` z czynnościami ``activities`` w
    zleceniu, które jest usterką (``fault``) albo nie; ``None`` przy opisie bez Błędu opisu i przy Wpisie bez ``tak``."""

    if verdict is not Verdict.YES:
        return None
    read = legend.read(activities, fault=fault)
    return FaultyDescription(worker, day, number, read.problems) if isinstance(read, DescriptionError) else None


def entered(
    legend: ActivityLegend,
    rules: QuantityRules,
    targets: Iterable[tuple[RegisterOrder, Login, date, ReportEntry]],
    additions: Iterable[Addition],
) -> tuple[FaultyDescription, ...]:
    """Problemy wpisanych Wpisów ``tak`` z Błędem opisu: zwycięskich Wpisów zleceń z nadawcą i dniem, w którym tata
    widzi ich problem (``_matching.Matched.entered``), i Zleceń dopisanych z raportu po poprawionych mailach."""

    found = [
        *(
            faulty(
                legend,
                worker,
                day,
                entry.number,
                entry.verdict,
                entry.activities,
                fault=is_fault(evaluated(rules, order.content)),
            )
            for order, worker, day, entry in targets
        ),
        *(
            faulty(legend, added.worker, added.day, added.number, added.verdict, added.activities, fault=False)
            for added in additions
        ),
    ]
    return tuple(fault for fault in found if fault is not None)



def codes(legend: ActivityLegend, successful: str | None, activities: str | None) -> tuple[str, ...] | None:
    """Kody czynności zlecenia z ``SKUTECZNE`` ``successful`` i ``CZYNNOŚCI ZREALIZOWANE`` ``activities`` po kliknięciu, w
    zapisie legendy i kolejności z opisu (``spelled``), także kody z Błędem opisu; pusta krotka: „BRAK KODU”; ``None``:
    zlecenie bez ``tak``, bez względu na wielkość liter i spacje."""

    if normalize_text(successful) != Verdict.YES.value:
        return None
    return legend.read(activities or "", fault=False).spelled
