"""Ustawienia taty w Centrum rozliczeń: Rejestr zleceń, folder okresów i motyw, w lokalnym pliku YAML poza gitem.

Centrum czyta je, wskazuje Rejestr zleceń i folder okresów oknem wyboru i zmienia motyw. Rejestr zleceń z Ustawień
taty otwiera się też z karty wyniku, gdy Zatrzymanie każe go poprawić. Brak albo uszkodzenie pliku znaczy „nie
ustawiono”, nigdy błąd startu. Zapis podmienia plik atomowo, więc przerwany zapis zostawia poprzednie ustawienia.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import os
from pathlib import Path
import stat
import tempfile
import threading
from typing import Literal

from fastapi import APIRouter
import yaml

from rozliczenia.centrum import contract
from rozliczenia.centrum.platform import Platform

Theme = Literal["dark", "light"]
_THEMES: tuple[Theme, ...] = ("dark", "light")
_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Settings:
    register: Path | None = None
    periods_directory: Path | None = None
    theme: Theme = "dark"

    @property
    def existing_register(self) -> Path | None:
        return self.register if self.register is not None and self.register.is_file() else None

    @property
    def existing_periods_directory(self) -> Path | None:
        return self.periods_directory if self.periods_directory is not None and self.periods_directory.is_dir() else None


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def load(self) -> Settings:
        try:
            document = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return Settings()
        if not isinstance(document, dict) or document.get("schema_version") != _SCHEMA_VERSION:
            return Settings()
        theme = document.get("motyw")
        return Settings(
            register=_path_or_none(document.get("rejestr_zlecen")),
            periods_directory=_path_or_none(document.get("folder_okresow")),
            theme=theme if theme in _THEMES else "dark",
        )

    def update(
        self,
        *,
        register: Path | None = None,
        periods_directory: Path | None = None,
        theme: Theme | None = None,
    ) -> Settings:
        with self._lock:
            current = self.load()
            updated = replace(
                current,
                register=register or current.register,
                periods_directory=periods_directory or current.periods_directory,
                theme=theme or current.theme,
            )
            self._write(updated)
            return updated

    def _write(self, settings: Settings) -> None:
        document = {
            "schema_version": _SCHEMA_VERSION,
            "rejestr_zlecen": None if settings.register is None else str(settings.register),
            "folder_okresow": None if settings.periods_directory is None else str(settings.periods_directory),
            "motyw": settings.theme,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{self._path.name}.", dir=self._path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                yaml.safe_dump(document, file, allow_unicode=True, sort_keys=False, width=1_000_000)
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def _path_or_none(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None


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
