"""Interfejs HTTP Ustawień taty: odczyt, wybór Rejestru zleceń i folderu okresów oknem wyboru, otwarcie Rejestru
zleceń i zmiana motywu.

Plik Ustawień taty i jego zapis należą do ``settings``; tu są tylko żądania przeglądarki i ich odmowy.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import stat

from fastapi import APIRouter

from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import settings as settings_contract
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import NOT_FOUND_OR_CONFLICT
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.settings import Settings, SettingsStore, Theme

_REGISTER_DIALOG = "Wybierz plik Rejestru zleceń"
_REGISTER_FILETYPES = (("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx"))
_PERIODS_DIALOG = "Wybierz folder okresów (np. Załączniki albo INEA)"


def settings_router(store: SettingsStore, platform: Platform) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    @router.get("", operation_id="getSettings")
    def read() -> settings_contract.Settings:
        return describe(store.load())

    @router.post("/register/choose", operation_id="chooseRegister")
    def choose_register() -> settings_contract.Choice:
        chosen = platform.choose_file(_REGISTER_DIALOG, _REGISTER_FILETYPES)
        if chosen is None:
            return settings_contract.Choice(settings=describe(store.load()))
        return settings_contract.Choice(settings=_saved(store, register=chosen))

    @router.post("/register/open", operation_id="openRegister", responses=NOT_FOUND_OR_CONFLICT)
    def open_register() -> common_contract.Opened:
        register = store.load().register
        if register is None:
            raise refusal.register_not_chosen()
        try:
            found = stat.S_ISREG(register.stat().st_mode)
        except (FileNotFoundError, NotADirectoryError):
            found = False
        except OSError:
            raise refusal.register_unavailable(register.name) from None
        if not found:
            raise refusal.register_missing(register.name)
        platform.open_path(register)
        return common_contract.Opened(name=register.name)

    @router.post("/periods-directory/choose", operation_id="choosePeriodsDirectory")
    def choose_periods_directory() -> settings_contract.Choice:
        chosen = platform.choose_folder(_PERIODS_DIALOG)
        if chosen is None:
            return settings_contract.Choice(settings=describe(store.load()))
        return settings_contract.Choice(settings=_saved(store, periods_directory=chosen))

    @router.put("/theme", operation_id="changeTheme")
    def change_theme(change: settings_contract.ThemeChange) -> settings_contract.Settings:
        return _saved(store, theme=change.theme)

    return router


def _saved(
    store: SettingsStore, *, register: Path | None = None, periods_directory: Path | None = None, theme: Theme | None = None
) -> settings_contract.Settings:
    """Ustawienia po zapisie zmiany; folder config, do którego nie da się pisać, to odmowa z własnym tekstem."""

    try:
        return describe(store.update(register=register, periods_directory=periods_directory, theme=theme))
    except OSError:
        raise refusal.settings_not_saved() from None


def describe(settings: Settings) -> settings_contract.Settings:
    return settings_contract.Settings(
        order_register=_describe_path(settings.register, exists=Path.is_file),
        periods_directory=_describe_path(settings.periods_directory, exists=Path.is_dir),
        theme=settings.theme,
    )


def _describe_path(path: Path | None, *, exists: Callable[[Path], bool]) -> settings_contract.PathSetting:
    if path is None:
        return settings_contract.NotSetPath(state="not_set")
    if exists(path):
        return settings_contract.ReadyPath(state="ready", path=str(path), name=path.name)
    return settings_contract.MissingPath(state="missing", path=str(path), name=path.name)
