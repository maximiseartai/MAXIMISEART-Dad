"""Interfejs HTTP Ustawień Centrum: odczyt wszystkich sekcji, zapis sekcji Foldery, wybór Rejestru zleceń i folderu
okresów oknem wyboru, otwarcie Rejestru zleceń, zmiana motywu, Historia Ustawień i cofnięcie jej wiersza.

Pliki Ustawień, ich Historia i reguły zapisu należą do ``settings``; tu są tylko żądania przeglądarki i ich odmowy:
zła wartość to 422 z polem, plik albo Historia, których nie da się przeczytać albo zapisać, to 500, a wiersz Historii
bez „Cofnij” to 404.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timezone
from pathlib import Path

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import settings as settings_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.settings.files import Bad, Good, Unreadable
from rozliczenia.centrum.settings.folders import DEFAULT_THEME, FOLDERS, FolderSettings, SettingState
from rozliczenia.centrum.settings.history import ByDad, FromRelease, HistoryRow, Outside
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, NotUndoable, Refused, Saved, SettingsView
from rozliczenia.file_state import file_state

_REGISTER_DIALOG = "Wybierz plik Rejestru zleceń"
_REGISTER_FILETYPES = (("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx"))
_PERIODS_DIALOG = "Wybierz folder okresów (np. Załączniki albo INEA)"
# Odmowy w OpenAPI: zła wartość (422) i wiersz Historii bez „Cofnij” (404), obie jako ``Problem``.
_REFUSED: dict[int | str, dict[str, object]] = {
    422: {"model": common_contract.Problem, "description": "Zła wartość Ustawień Centrum z polem i zdaniem"}
}
_NOT_UNDOABLE: dict[int | str, dict[str, object]] = {404: {"model": common_contract.Problem}, **_REFUSED}


def settings_router(settings: CentrumSettings, platform: Platform) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    def saved(edit: Callable[[FolderSettings], FolderSettings]) -> settings_contract.Choice:
        return _choice(settings, settings.change(FOLDERS, edit))

    @router.get("", operation_id="getSettings")
    def read() -> settings_contract.Settings:
        return describe(settings.view())

    @router.put("/folders", operation_id="changeFolders", responses=_REFUSED)
    def change_folders(change: settings_contract.FoldersChange) -> settings_contract.Choice:
        register, periods_directory = _path(change.order_register), _path(change.periods_directory)
        return saved(lambda current: replace(current, register=register, periods_directory=periods_directory))

    @router.post("/register/choose", operation_id="chooseRegister")
    def choose_register() -> settings_contract.Choice:
        chosen = platform.choose_file(_REGISTER_DIALOG, _REGISTER_FILETYPES)
        if chosen is None:
            return settings_contract.Choice(settings=describe(settings.view()))
        return saved(lambda current: replace(current, register=chosen))

    @router.post("/register/open", operation_id="openRegister", responses=NOT_FOUND_OR_CONFLICT)
    def open_register() -> common_contract.Opened:
        register = settings.snapshot().folders.register
        if register is None:
            raise refusal.register_not_chosen()
        match file_state(register):
            case "inaccessible":
                raise refusal.register_unavailable(register.name)
            case "missing":
                raise refusal.register_missing(register.name)
            case "file":
                pass
        platform.open_path(register)
        return common_contract.Opened(name=register.name)

    @router.post("/periods-directory/choose", operation_id="choosePeriodsDirectory")
    def choose_periods_directory() -> settings_contract.Choice:
        chosen = platform.choose_folder(_PERIODS_DIALOG)
        if chosen is None:
            return settings_contract.Choice(settings=describe(settings.view()))
        return saved(lambda current: replace(current, periods_directory=chosen))

    @router.put("/theme", operation_id="changeTheme")
    def change_theme(change: settings_contract.ThemeChange) -> settings_contract.Choice:
        return saved(lambda current: replace(current, theme=change.theme))

    @router.get("/history", operation_id="getSettingsHistory")
    def history() -> settings_contract.SettingsHistory:
        read = settings.history()
        if isinstance(read, Unreadable):
            raise refusal.settings_history_unreadable()
        return settings_contract.SettingsHistory(rows=[_row(row) for row in read.rows], skipped=read.skipped)

    @router.post("/history/{change_id}/undo", operation_id="undoSettingsChange", responses=_NOT_UNDOABLE)
    def undo(change_id: str) -> settings_contract.Choice:
        undone = settings.undo(change_id)
        if isinstance(undone, NotUndoable):
            raise refusal.settings_change_not_undoable() if undone.known else refusal.settings_change_unknown()
        return _choice(settings, undone)

    return router


def _choice(settings: CentrumSettings, result: Saved | Refused | NotSaved) -> settings_contract.Choice:
    """Ustawienia po zapisie z id wiersza Historii; zła wartość to odmowa z polem, a plik, którego nie da się
    przeczytać albo zapisać, to odmowa z własnym tekstem."""

    match result:
        case Saved(change=change):
            return settings_contract.Choice(settings=describe(settings.view()), change=change)
        case Refused(problem=problem):
            raise refusal.setting_refused(problem)
        case NotSaved():
            raise refusal.settings_not_saved()


def _path(value: str | None) -> Path | None:
    return Path(value) if value else None


def describe(view: SettingsView) -> settings_contract.Settings:
    """Ustawienia Centrum dla przeglądarki: przy złym pliku ostatnie dobre wartości i zdanie o problemie."""

    match view.folders:
        case Unreadable():
            unreadable = settings_contract.UnreadablePath(state="unreadable")
            return settings_contract.Settings(
                order_register=unreadable, periods_directory=unreadable, theme=DEFAULT_THEME, folders_problem=None
            )
        case Good(value=folders):
            problem = None
        case Bad(problem=bad, usable=usable):
            folders = FolderSettings() if usable is None else usable
            problem = settings_contract.SettingProblem(field=bad.field, message=bad.sentence)
    return settings_contract.Settings(
        order_register=_describe_path(folders.register, folders.register_state),
        periods_directory=_describe_path(folders.periods_directory, folders.periods_directory_state),
        theme=folders.theme,
        folders_problem=problem,
    )


def _describe_path(path: Path | None, state: SettingState) -> settings_contract.PathSetting:
    if path is None:
        return settings_contract.NotSetPath(state="not_set")
    match state:
        case "present":
            return settings_contract.ReadyPath(state="ready", path=str(path), name=path.name)
        case "missing":
            return settings_contract.MissingPath(state="missing", path=str(path), name=path.name)
        case "inaccessible":
            return settings_contract.InaccessiblePath(state="inaccessible", path=str(path), name=path.name)
        case "not_set":
            return settings_contract.NotSetPath(state="not_set")


def _row(row: HistoryRow) -> settings_contract.HistoryRow:
    return settings_contract.HistoryRow(
        id=row.id,
        # Chwila taty w UTC, jak każda chwila kontraktu: przeglądarka przyjmuje tylko zapis z „Z”.
        at=row.at.astimezone(timezone.utc),
        source=_source(row),
        release=_release(row),
        undoes=row.undoes,
        file=row.file,
        section=row.section,
        changes=[
            settings_contract.HistoryChange(key=change.key, before=change.before, after=change.after) for change in row.changes
        ],
        secret=row.secret,
        undoable=row.undoable and row.result == "zapisano",
        refused=row.result == "odrzucono",
        removed=row.removed,
        reason=row.reason,
    )


def _source(row: HistoryRow) -> settings_contract.HistorySource:
    match row.source:
        case ByDad():
            return "tata"
        case Outside():
            return "outside"
        case FromRelease():
            return "release"


def _release(row: HistoryRow) -> settings_contract.HistoryRelease | None:
    if not isinstance(row.source, FromRelease):
        return None
    return settings_contract.HistoryRelease(version=row.source.release, commit=row.source.commit, change=row.source.change)
