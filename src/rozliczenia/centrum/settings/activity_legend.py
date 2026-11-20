from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from functools import lru_cache
from typing import Final

import yaml

from rozliczenia.activity_legend import ActivityCode, ActivityLegend, LegendProblem, LegendRefused
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND, dump_code, dump_codes, parse_activity_legend, parse_code
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import EntriesById, FieldProblem, Good, KeyChange, SettingsFile, settings_yaml
from rozliczenia.centrum.settings.proposal import Edit, Later, Proposal, ReleaseInputs

LEGEND_FILE: Final = "legenda-czynnosci.yaml"
LEGEND_SECTION: Final = "kody"


@lru_cache(maxsize=4)
def _parse(data: bytes | None) -> tuple[ActivityCode, ...] | FieldProblem:
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
    try:
        return ActivityLegend(codes)
    except LegendRefused:
        return DEFAULT_ACTIVITY_LEGEND


Codes = tuple[ActivityCode, ...]


def code_ids(keys: frozenset[str]) -> frozenset[str]:
    return _ENTRIES.ids(keys)


def legend_refusal(codes: Codes | FieldProblem) -> Codes | FieldProblem:
    if isinstance(codes, FieldProblem):
        return codes
    try:
        ActivityLegend(codes)
    except LegendRefused as refused:
        return FieldProblem(None, refused.problem.message)
    return codes


def set_codes(*codes: ActivityCode) -> Callable[[ReleaseInputs[Codes]], Proposal[Codes]]:
    def propose(inputs: ReleaseInputs[Codes]) -> Proposal[Codes]:
        if not isinstance(inputs.current, Good):
            return Later("plik Legendy czynności ma złą treść albo nie da się go teraz przeczytać")
        return Edit(lambda current: _with_codes(current, codes))

    return propose


def not_counted_in_fault(code_id: str) -> Callable[[ReleaseInputs[Codes]], Proposal[Codes]]:
    def propose(inputs: ReleaseInputs[Codes]) -> Proposal[Codes]:
        if not isinstance(inputs.current, Good):
            return Later("plik Legendy czynności ma złą treść albo nie da się go teraz przeczytać")
        return Edit(lambda current: tuple(replace(code, counts_in_fault=False) if code.id == code_id else code for code in current))

    return propose


def _with_codes(current: Codes, codes: Codes) -> Codes:
    by_id = {code.id: code for code in codes}
    kept = tuple(by_id.pop(code.id, code) for code in current)
    return (*kept, *by_id.values())
