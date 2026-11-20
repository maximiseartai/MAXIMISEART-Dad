from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Any, Final, Literal, TypedDict, assert_never, get_args

from rozliczenia.activity_legend import ActivityLegend
from rozliczenia.centrum import diagnosis_messages, refusal
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.centrum.run_logs import LoggedActivityLegend, LoggedQuantityRules, LoggedWorker
from rozliczenia.centrum.settings.files import Unreadable
from rozliczenia.centrum.settings.owner import SettingsSnapshot
from rozliczenia.message import Message
from rozliczenia.quantity_engine import QuantityRules
from rozliczenia.worker_list import WorkerList

SettingNeed = Literal["workers", "quantity_rules", "activity_legend"]
_SETTING_NEEDS: Final[tuple[SettingNeed, ...]] = get_args(SettingNeed)


class LoggedSettings(TypedDict):
    quantity_rules: LoggedQuantityRules | None
    activity_legend: LoggedActivityLegend | None
    workers: list[LoggedWorker] | None


@dataclass(frozen=True, kw_only=True)
class SettingsAtStart:
    snapshot: SettingsSnapshot | None
    workers: WorkerList | None
    quantity_rules: QuantityRules | None
    activity_legend: ActivityLegend | None
    warnings: tuple[Message, ...]

    @classmethod
    def of_snapshot(cls, snapshot: SettingsSnapshot, needs: Collection[str]) -> SettingsAtStart:
        rules, legend = snapshot.quantity_rules_or_unreadable, snapshot.activity_legend_or_unreadable
        return cls(
            snapshot=snapshot,
            workers=snapshot.workers.counted() if "workers" in needs else None,
            quantity_rules=None if isinstance(rules, Unreadable) else rules,
            activity_legend=None if isinstance(legend, Unreadable) else legend,
            warnings=_start_warnings(snapshot, needs),
        )

    def missing(self, needs: Collection[str]) -> str | None:
        for need in _SETTING_NEEDS:
            if need in needs and getattr(self, need) is None:
                return _missing(need)
        return None

    def for_process(self, needs: Collection[str]) -> SettingsAtStart:
        unused: dict[str, Any] = {need: None for need in _SETTING_NEEDS if need not in needs}
        return replace(self, **unused)

    def logged(self) -> LoggedSettings:
        rules, legend, workers = self.quantity_rules, self.activity_legend, self.workers
        return LoggedSettings(
            quantity_rules=None if rules is None else LoggedQuantityRules.of(rules),
            activity_legend=None if legend is None else LoggedActivityLegend.of(legend),
            workers=None if workers is None else LoggedWorker.all_of(workers),
        )

    def counted_rules(self) -> QuantityRules:
        assert self.quantity_rules is not None, "Catalog.prepared sprawdza Reguły ilości procesu, który nimi liczy"
        return self.quantity_rules

    def counted_legend(self) -> ActivityLegend:
        assert self.activity_legend is not None, "Catalog.prepared sprawdza Legendę czynności procesu, który nią liczy"
        return self.activity_legend

    def worker_list(self) -> WorkerList:
        assert self.workers is not None, "Catalog.prepared sprawdza potrzebę workers"
        return self.workers


def unreadable(snapshot: SettingsSnapshot, needs: Collection[str]) -> Refusal | None:
    for need in _SETTING_NEEDS:
        if need in needs and (file := _unreadable_at_start(snapshot, need)) is not None:
            return refusal.settings_file_unreadable(file.name)
    return None


def _unreadable_at_start(snapshot: SettingsSnapshot, need: SettingNeed) -> Unreadable | None:
    match need:
        case "workers":
            return None
        case "quantity_rules":
            rules = snapshot.quantity_rules_or_unreadable
            return rules if isinstance(rules, Unreadable) else None
        case "activity_legend":
            legend = snapshot.activity_legend_or_unreadable
            return legend if isinstance(legend, Unreadable) else None
        case _:
            assert_never(need)


def _missing(need: SettingNeed) -> str:
    match need:
        case "workers":
            return "potrzebuje Listy Wykonawców, a start jej nie ma"
        case "quantity_rules":
            return "liczy Regułami ilości, a start ich nie ma"
        case "activity_legend":
            return "liczy Legendą czynności, a start jej nie ma"
        case _:
            assert_never(need)


def _start_warnings(snapshot: SettingsSnapshot, needs: Collection[str]) -> tuple[Message, ...]:
    problem = snapshot.workers.last_good()
    if "workers" in needs and problem is not None:
        return (diagnosis_messages.worker_list_last_good(problem.sentence),)
    return ()
