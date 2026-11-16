"""Legenda czynności (ADR 0038): plik ``legenda-czynnosci.yaml`` w ``config``.

Format pliku i niezmienniki należą do silnika i jego parsera (``activity_legend``, ``activity_legend_file``); tu jest ich
opis dla właściciela Ustawień. Brak pliku to Legenda czynności z Wydania (``DEFAULT_ACTIVITY_LEGEND``). Wartością pliku
są same kody, bo cofnięcie (``restore``) może złożyć wartość, której ``parse`` nie przyjmie, a właściciel sprawdza ją
dopiero przez ``dump`` i ``parse``; legendę, którą liczą procesy, daje z dobrej wartości ``activity_legend``. Klucz
Historii to ``kody.<id>``, a wartość to wpis pliku jako JSON, z którego cofnięcie odtwarza kod.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final

import yaml

from rozliczenia.activity_legend import ActivityCode, ActivityLegend, LegendProblem, LegendRefused
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND, dump_code, dump_codes, parse_activity_legend, parse_code
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import EntriesById, FieldProblem, KeyChange, SettingsFile, settings_yaml

LEGEND_FILE: Final = "legenda-czynnosci.yaml"
LEGEND_SECTION: Final = "kody"


@lru_cache(maxsize=4)
def _parse(data: bytes | None) -> tuple[ActivityCode, ...] | FieldProblem:
    """Kody z bajtów pliku; ``None`` (brak pliku) to legenda z Wydania. Te same bajty dają ten sam wynik, więc odczyt
    przy każdej migawce nie parsuje pliku od nowa."""

    if data is None:
        return DEFAULT_ACTIVITY_LEGEND.codes
    try:
        document: object = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(LEGEND_FILE))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(LEGEND_FILE))
    legend = parse_activity_legend(document)
    if isinstance(legend, LegendProblem):
        return FieldProblem(None, messages.activity_legend_problem(LEGEND_FILE, legend.message))
    return legend.codes


def _code(entry: object) -> ActivityCode | None:
    code = parse_code(entry)
    return None if isinstance(code, LegendProblem) else code


_ENTRIES: Final = EntriesById[ActivityCode](LEGEND_SECTION, dump_code, _code)


def _reported(change: KeyChange) -> str:
    """Zmiana w Zgłoszeniu: kod nie ma danych osobowych, więc wprost."""

    return f"{change.key}: {'nie ustawiono' if change.before is None else change.before} → {'nie ustawiono' if change.after is None else change.after}"


LEGEND: Final = SettingsFile[tuple[ActivityCode, ...]](
    name=LEGEND_FILE,
    parse=_parse,
    dump=lambda codes: settings_yaml(dump_codes(codes)),
    diff=_ENTRIES.diff,
    restore=_ENTRIES.restore,
    reported=_reported,
    default=DEFAULT_ACTIVITY_LEGEND.codes,
)


def activity_legend(codes: tuple[ActivityCode, ...]) -> ActivityLegend:
    """Legenda czynności, którą liczą procesy, z dobrej wartości pliku (dobrej albo ostatniej dobrej); wartość, której
    legenda nie przyjmuje (tylko spoza ``parse``), to legenda z Wydania."""

    try:
        return ActivityLegend(codes)
    except LegendRefused:
        return DEFAULT_ACTIVITY_LEGEND
