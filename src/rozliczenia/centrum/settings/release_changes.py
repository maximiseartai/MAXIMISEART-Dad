from __future__ import annotations

from dataclasses import replace
from typing import Any, Final

from rozliczenia.centrum.settings.activity_legend import LEGEND, not_counted_in_fault
from rozliczenia.centrum.settings.files import Good
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings
from rozliczenia.centrum.settings.migrations import reminders as reminders_migration
from rozliczenia.centrum.settings.migrations import workers as workers_migration
from rozliczenia.centrum.settings.proposal import Edit, Later, Nothing, Proposal, ReleaseChange, ReleaseInputs
from rozliczenia.period_folder import PeriodFolderInaccessible, layout_root


def periods_directory_from_layout_root(inputs: ReleaseInputs[FolderSettings]) -> Proposal[FolderSettings]:
    if not isinstance(inputs.current, Good):
        return Later("plik Ustawień ma złą treść albo nie da się go teraz przeczytać")
    settings = inputs.current.value
    saved = settings.periods_directory
    if saved is None:
        return Nothing()
    try:
        root = layout_root(saved).directory
    except PeriodFolderInaccessible:
        return Later("folderu okresów nie da się teraz odczytać")
    if root != saved:
        return Edit(lambda current: replace(current, periods_directory=root))
    if settings.periods_directory_state == "missing":
        return Later("folderu okresów nie ma")
    return Nothing()


RELEASE_CHANGES: Final[tuple[ReleaseChange[Any], ...]] = (
    workers_migration.CHANGE,
    ReleaseChange("2026-11-folder-okresow-od-zalacznikow", FOLDERS, periods_directory_from_layout_root),
    reminders_migration.CHANGE,
    ReleaseChange("2026-11-rt2-bez-usterek", LEGEND, not_counted_in_fault("rt2")),
)
