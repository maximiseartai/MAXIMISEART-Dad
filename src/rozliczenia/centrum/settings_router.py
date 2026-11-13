"""Interfejs HTTP Ustawień Centrum: odczyt wszystkich sekcji, zapis sekcji Foldery, wybór Rejestru zleceń i folderu
okresów oknem wyboru, otwarcie Rejestru zleceń, zmiana motywu, zmiana hasła skrzynki raportów z próbą logowania,
przełącznik startu razem z Windows, Historia Ustawień i cofnięcie jej wiersza. Hasła skrzynki nie ma w żadnej
odpowiedzi.

Pliki Ustawień, ich Historia i reguły zapisu należą do ``settings``; tu są tylko żądania przeglądarki i ich odmowy:
zła wartość to 422 z polem, plik albo Historia, których nie da się przeczytać albo zapisać, to 500, a wiersz Historii
bez „Cofnij” to 404.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import settings as settings_contract
from rozliczenia.centrum.contract.quantity_rules import SentencePart
from rozliczenia.centrum.contract import settings_workers as settings_workers_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.settings import inbox, messages
from rozliczenia.centrum.settings.autostart import AUTOSTART, Unsupported
from rozliczenia.centrum.settings.files import Bad, FieldProblem, Good, Read, Unreadable
from rozliczenia.centrum.settings.folders import (
    DEFAULT_THEME,
    FOLDERS,
    FolderSettings,
    SettingState,
    periods_directory_root,
)
from rozliczenia.centrum.settings.inbox import INBOX, InboxFile
from rozliczenia.centrum.settings.history import ByDad, FromRelease, HistoryRow, Outside
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, NotUndoable, Refused, Saved, SettingsView
from rozliczenia.file_state import file_state
from rozliczenia.worker_list import AddressesNotMoved, UnmatchedLogin, Unresolved, WorkerList
from rozliczenia.worker_report_inbox import LoginResult

_REGISTER_DIALOG = "Wybierz plik Rejestru zleceń"
_REGISTER_FILETYPES = (("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx"))
_PERIODS_DIALOG = "Wybierz folder okresów (np. Załączniki albo INEA)"
# Odmowy w OpenAPI: zła wartość (422) i wiersz Historii bez „Cofnij” (404), obie jako ``Problem``.
_REFUSED: dict[int | str, dict[str, object]] = {
    422: {"model": common_contract.Problem, "description": "Zła wartość Ustawień Centrum z polem i zdaniem"}
}
_NOT_UNDOABLE: dict[int | str, dict[str, object]] = {404: {"model": common_contract.Problem}, **_REFUSED}


def settings_router(
    settings: CentrumSettings,
    platform: Platform,
    inbox_login: Callable[[], LoginResult],
    rule_sentences: Callable[[], Callable[[str, str | None], list[SentencePart] | None]],
) -> APIRouter:
    """``inbox_login`` to jedna próba logowania do skrzynki raportów z bieżącym plikiem dostępu, a ``rule_sentences``
    daje na jeden odczyt Historii zdanie reguły ilości z wartości jej klucza (``quantity_rules_router.history_sentences``)."""

    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    def saved(edit: Callable[[FolderSettings], FolderSettings]) -> settings_contract.Choice:
        return _choice(settings, settings.change(FOLDERS, edit))

    @router.get("", operation_id="getSettings")
    def read() -> settings_contract.Settings:
        return describe(settings.view())

    @router.put("/folders", operation_id="changeFolders", responses=_REFUSED)
    def change_folders(change: settings_contract.FoldersChange) -> settings_contract.Choice:
        register, periods_directory = _path(change.order_register), _path(change.periods_directory)
        root = None if periods_directory is None else periods_directory_root(periods_directory)

        # Sekcja odsyła obie ścieżki, więc zapisany folder okresów zostaje, jaki jest (np. tydzień, do którego tata
        # cofnął zmianę z Wydania), a od korzenia układu zapisuje się tylko folder wskazany na nowo.
        def edit(current: FolderSettings) -> FolderSettings:
            kept = periods_directory == current.periods_directory
            return replace(current, register=register, periods_directory=periods_directory if kept else root)

        return saved(edit)

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
        root = periods_directory_root(chosen)
        return saved(lambda current: replace(current, periods_directory=root))

    @router.put("/theme", operation_id="changeTheme")
    def change_theme(change: settings_contract.ThemeChange) -> settings_contract.Choice:
        return saved(lambda current: replace(current, theme=change.theme))

    @router.put("/autostart", operation_id="changeAutostart", responses=_REFUSED)
    def change_autostart(change: settings_contract.AutostartChange) -> settings_contract.Choice:
        result = settings.change(AUTOSTART, lambda _: change.enabled)
        if isinstance(result, NotSaved):
            raise refusal.autostart_not_changed()
        return _choice(settings, result)

    @router.put("/inbox-password", operation_id="changeInboxPassword", responses=_REFUSED)
    def change_inbox_password(change: settings_contract.InboxPasswordChange) -> settings_contract.InboxPasswordSaved:
        """Nowe hasło zastępuje tylko linię hasła pliku; po każdym udanym zapisie jedna próba logowania mówi, czy
        skrzynka je przyjęła. Odrzucone hasło zostaje zapisane, a tata wpisuje je jeszcze raz."""

        password = inbox.new_password(settings.view().inbox, change.password)
        if isinstance(password, FieldProblem):
            raise refusal.setting_refused(password)
        saved = _choice(settings, settings.change(INBOX, lambda current: replace(current, password=password)))
        return settings_contract.InboxPasswordSaved(settings=saved.settings, change=saved.change, login=inbox_login())

    @router.get("/history", operation_id="getSettingsHistory")
    def history() -> settings_contract.SettingsHistory:
        read = settings.history()
        if isinstance(read, Unreadable):
            raise refusal.settings_history_unreadable()
        sentence = rule_sentences()
        return settings_contract.SettingsHistory(rows=[_row(row, sentence) for row in read.rows], skipped=read.skipped)

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

    workers = _workers(view.workers)
    inbox_setting, inbox_problem = _describe_inbox(view.inbox)
    autostart = _describe_autostart(view.autostart)
    match view.folders:
        case Unreadable():
            unreadable = settings_contract.UnreadablePath(state="unreadable")
            return settings_contract.Settings(
                order_register=unreadable,
                periods_directory=unreadable,
                periods_all_years=False,
                theme=DEFAULT_THEME,
                folders_problem=None,
                workers=workers,
                inbox=inbox_setting,
                inbox_problem=inbox_problem,
                autostart=autostart,
            )
        case Good(value=folders):
            problem = None
        case Bad(problem=bad, usable=usable):
            folders = FolderSettings() if usable is None else usable
            problem = settings_workers_contract.SettingProblem(field=bad.place, message=bad.sentence)
    return settings_contract.Settings(
        order_register=_describe_path(folders.register, folders.register_state),
        periods_directory=_describe_path(folders.periods_directory, folders.periods_directory_state),
        periods_all_years=folders.periods_directory_all_years,
        theme=folders.theme,
        folders_problem=problem,
        workers=workers,
        inbox=inbox_setting,
        inbox_problem=inbox_problem,
        autostart=autostart,
    )


def _describe_inbox(
    read: Read[InboxFile] | Unreadable,
) -> tuple[settings_contract.InboxSetting, settings_workers_contract.SettingProblem | None]:
    """Adres skrzynki i to, czy jest hasło, bez wartości hasła; zła treść ma zdanie o problemie i dobry adres z niej
    (przy złym starym haśle tata wpisuje nowe), a nieczytelna to skrzynka bez nich."""

    match read:
        case Good(value=found):
            return _inbox_setting(found), None
        case Bad(problem=bad, usable=found):
            problem = settings_workers_contract.SettingProblem(field=bad.place, message=bad.sentence)
            return _inbox_setting(found), problem
        case Unreadable():
            return _inbox_setting(None), None


def _inbox_setting(found: InboxFile | None) -> settings_contract.InboxSetting:
    address = None if found is None else found.address
    return settings_contract.InboxSetting(
        address=None if address is None else address.shown(), password=found is not None and bool(found.password)
    )


def _workers(read: Read[WorkerList] | Unreadable) -> settings_workers_contract.WorkerListSetting:
    """Lista Wykonawców w kolejności z pliku; przy złym pliku ostatnia dobra (bez niej pusta) i zdanie o problemie."""

    match read:
        case Good(value=workers):
            state: Literal["good", "bad", "unreadable"] = "good"
            problem = None
        case Bad(problem=bad, usable=usable):
            state, workers = "bad", usable or WorkerList(())
            problem = settings_workers_contract.SettingProblem(field=bad.place, message=bad.sentence)
        case Unreadable():
            state, workers, problem = "unreadable", WorkerList(()), None
    return settings_workers_contract.WorkerListSetting(
        state=state,
        workers=[
            settings_workers_contract.ListedWorker(
                logins=list(worker.logins),
                name=worker.name,
                addresses=[address.shown() for address in worker.addresses],
                active=worker.active,
                reminders=worker.reminders,
            )
            for worker in workers.workers
        ],
        unresolved=[_unresolved(item) for item in workers.unresolved],
        problem=problem,
    )


def _unresolved(item: Unresolved) -> settings_workers_contract.UnmatchedLogin | settings_workers_contract.AddressesNotMoved:
    match item:
        case UnmatchedLogin(login=login, addresses=addresses):
            return settings_workers_contract.UnmatchedLogin(
                reason="login_bez_wykonawcy", login=login, addresses=[address.shown() for address in addresses]
            )
        case AddressesNotMoved(sentence=sentence):
            return settings_workers_contract.AddressesNotMoved(reason="adresy_nieprzeniesione", message=sentence)
def _describe_autostart(autostart: Read[bool] | Unreadable | Unsupported) -> settings_contract.AutostartSetting:
    match autostart:
        case Unsupported():
            return settings_contract.AutostartSetting(state="unsupported", reason=messages.autostart_unsupported())
        case Unreadable():
            return settings_contract.AutostartSetting(state="unreadable", reason=messages.autostart_unreadable())
        case Good(value=enabled) | Bad(usable=enabled):
            return settings_contract.AutostartSetting(state="on" if enabled else "off", reason=None)


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


def _row(row: HistoryRow, sentence: Callable[[str, str | None], list[SentencePart] | None]) -> settings_contract.HistoryRow:
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
        rules=_rule_changes(row, sentence),
    )


def _rule_changes(
    row: HistoryRow, sentence: Callable[[str, str | None], list[SentencePart] | None]
) -> list[settings_contract.HistoryRuleChange]:
    """Zmienione reguły ilości wiersza jako zdania przed i po; klucz, którego wartości nie są regułą, się nie pokazuje."""

    found: list[settings_contract.HistoryRuleChange] = []
    for change in row.changes:
        before, after = sentence(change.key, change.before), sentence(change.key, change.after)
        if before is not None or after is not None:
            found.append(settings_contract.HistoryRuleChange(key=change.key, before=before, after=after))
    return found


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
