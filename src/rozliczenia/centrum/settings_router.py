"""Interfejs HTTP Ustawień taty: odczyt, wybór Rejestru zleceń i folderu okresów oknem wyboru, otwarcie Rejestru
zleceń i zmiana motywu.

Plik Ustawień taty i jego zapis należą do ``settings``; tu są tylko żądania przeglądarki i ich odmowy.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import stat

from fastapi import APIRouter

from rozliczenia.centrum import contract
from rozliczenia.centrum.platform import Platform
from rozliczenia.centrum.settings import Settings, SettingsStore, Theme

_REGISTER_DIALOG = "Wybierz plik Rejestru zleceń"
_REGISTER_FILETYPES = (("Rejestr zleceń Excel", "ZLECENIA*.xlsx"), ("Excel", "*.xlsx"))
_PERIODS_DIALOG = "Wybierz folder okresów (np. Załączniki albo INEA)"
_NOT_SAVED = (
    "Nie udało się zapisać Ustawień taty w folderze config. Sprawdź, czy folder otwiera się w Eksploratorze "
    "plików, nie jest tylko do odczytu i czy OneDrive działa, potem spróbuj ponownie."
)


def settings_router(store: SettingsStore, platform: Platform) -> APIRouter:
    router = APIRouter(prefix="/api/settings", tags=["ustawienia"])

    @router.get("", operation_id="getSettings")
    def read() -> contract.Settings:
        return describe(store.load())

    @router.post("/register/choose", operation_id="chooseRegister")
    def choose_register() -> contract.Choice:
        chosen = platform.choose_file(_REGISTER_DIALOG, _REGISTER_FILETYPES)
        if chosen is None:
            return contract.Choice(settings=describe(store.load()))
        return contract.Choice(settings=_saved(store, register=chosen))

    @router.post("/register/open", operation_id="openRegister", responses=contract.NOT_FOUND_OR_CONFLICT)
    def open_register() -> contract.Opened:
        register = store.load().register
        if register is None:
            raise contract.Refusal(409, "Najpierw wybierz Rejestr zleceń w Ustawieniach.")
        try:
            found = stat.S_ISREG(register.stat().st_mode)
        except (FileNotFoundError, NotADirectoryError):
            found = False
        except OSError:
            raise contract.Refusal(
                409,
                f"Rejestr zleceń {register.name} jest teraz niedostępny. Sprawdź, czy jego folder otwiera się "
                "w Eksploratorze plików i czy OneDrive działa, potem spróbuj ponownie.",
            ) from None
        if not found:
            raise contract.Refusal(
                404, f"Nie ma Rejestru zleceń {register.name}. Wybierz właściwy plik w Ustawieniach."
            )
        platform.open_path(register)
        return contract.Opened(name=register.name)

    @router.post("/periods-directory/choose", operation_id="choosePeriodsDirectory")
    def choose_periods_directory() -> contract.Choice:
        chosen = platform.choose_folder(_PERIODS_DIALOG)
        if chosen is None:
            return contract.Choice(settings=describe(store.load()))
        return contract.Choice(settings=_saved(store, periods_directory=chosen))

    @router.put("/theme", operation_id="changeTheme")
    def change_theme(change: contract.ThemeChange) -> contract.Settings:
        return _saved(store, theme=change.theme)

    return router


def _saved(
    store: SettingsStore, *, register: Path | None = None, periods_directory: Path | None = None, theme: Theme | None = None
) -> contract.Settings:
    """Ustawienia po zapisie zmiany; folder config, do którego nie da się pisać, to odmowa z własnym tekstem."""

    try:
        return describe(store.update(register=register, periods_directory=periods_directory, theme=theme))
    except OSError:
        raise contract.Refusal(500, _NOT_SAVED) from None


def describe(settings: Settings) -> contract.Settings:
    return contract.Settings(
        order_register=_describe_path(settings.register, exists=Path.is_file),
        periods_directory=_describe_path(settings.periods_directory, exists=Path.is_dir),
        theme=settings.theme,
    )


def _describe_path(path: Path | None, *, exists: Callable[[Path], bool]) -> contract.PathSetting:
    if path is None:
        return contract.NotSetPath(state="not_set")
    if exists(path):
        return contract.ReadyPath(state="ready", path=str(path), name=path.name)
    return contract.MissingPath(state="missing", path=str(path), name=path.name)
