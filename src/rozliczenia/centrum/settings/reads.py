from __future__ import annotations

from typing import Protocol

from rozliczenia.activity_legend import ActivityLegend
from rozliczenia.centrum.settings.folders import FolderSettings
from rozliczenia.centrum.settings.owner import (
    QuantityRulesView as QuantityRulesView,
    SettingsSnapshot as SettingsSnapshot,
    WorkerListRead as WorkerListRead,
)


class SettingsReads(Protocol):
    def snapshot(self) -> SettingsSnapshot: ...

    def folders(self) -> FolderSettings: ...

    def quantity_rules(self) -> QuantityRulesView: ...

    def counted_activity_legend(self) -> ActivityLegend: ...
