"""Błąd opisu we Wpisie raportu (ADR 0039): Wpis ``tak``, którego czynności Legenda czynności czyta jako Błąd opisu.

Regułę ma jedna funkcja, ``faulty``, dla obu operacji rdzenia: Wpisanie raportów wpisuje taki Wpis jak każdy i daje przy
nim problem ``FaultyDescription`` (``entered``), a Przypomnienia o raporcie liczą dzień Wykonawcy z takim wygrywającym
Wpisem jako niewysłany (``standing``). Opis Wpisu ``nie`` to powód nieskuteczności, więc legenda go nie czyta, a Wpis
bez ``tak`` ani ``nie`` niczego nie wpisuje i ma swój problem (``MissingVerdict``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date

from ..activity_legend import ActivityLegend, DescriptionError
from ._matching import Addition
from ._model import FaultyDescription, Login, OrderNumber, ReadReport, ReportEntry, Verdict


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


def standing(
    legend: ActivityLegend, reports: Sequence[ReadReport], numbers: frozenset[OrderNumber]
) -> Mapping[tuple[Login, date], tuple[FaultyDescription, ...]]:
    """Wygrywające Wpisy ``tak`` z Błędem opisu po Wykonawcy i dniu z tematu, a przy każdym po numerze.

    ``reports`` idą w kolejności przyjścia, a numer wygrywa Wpis najpóźniejszego Raportu wykonawcy z tym numerem, także
    od innego Wykonawcy, jak we Wpisaniu raportów; raport z Wpisami numeru o przeciwnym zamiarze niczego nie wpisuje, więc
    nie daje Błędu opisu. Liczą się tylko numery zleceń INTERMAX (``numbers``): Wpis innego numeru to zlecenie, którego
    Wpisanie raportów jeszcze nie dopisało, albo literówka, którą poprawiony mail przed kliknięciem odrzuca
    (``_corrections.uncorrected``). Literówkę dopisaną kliknięciem przed poprawką INTERMAX ma jako zlecenie, więc
    przypomina jak każde zlecenie z takim Wpisem, np. dopóki tata nie usunie jej wiersza albo okres nie dostanie Pliku
    zbiorczego."""

    winners: dict[OrderNumber, tuple[ReadReport, list[ReportEntry]]] = {}
    for report in reports:
        said: dict[OrderNumber, list[ReportEntry]] = defaultdict(list)
        for entry in report.entries:
            said[entry.number].append(entry)
        winners.update((number, (report, written)) for number, written in said.items())
    found: dict[tuple[Login, date], list[FaultyDescription]] = defaultdict(list)
    for number, (report, written) in sorted(winners.items(), key=lambda won: (len(won[0]), won[0])):
        if number not in numbers or len(written) != 1:
            continue
        fault = faulty(legend, report.worker, report.day, number, written[0].verdict, written[0].activities)
        if fault is not None:
            found[report.worker, report.day].append(fault)
    return {place: tuple(faults) for place, faults in found.items()}
