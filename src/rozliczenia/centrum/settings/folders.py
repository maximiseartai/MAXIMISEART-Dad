"""Foldery i motyw: Rejestr zleceń, folder okresów i motyw w pliku ``centrum-ustawienia.yaml`` (schemat 1).

Zapisana ścieżka jest pełna (Rejestr zleceń to plik ``.xlsx``), a motyw jest ciemny albo jasny. Klucz, którego w pliku
nie ma, ma wartość domyślną, a klucz spoza schematu to zła treść, tak jak inny schemat albo uszkodzony YAML.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import Final, Literal

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldProblem, KeyChange, SettingsFile
from rozliczenia.file_state import PathState, path_state

SETTINGS_FILE: Final = "centrum-ustawienia.yaml"
"""Plik Rejestru zleceń, folderu okresów i motywu w ``config``; czyta go i pisze tylko ``rozliczenia.centrum.settings``."""

Theme = Literal["dark", "light"]
THEMES: Final[tuple[Theme, ...]] = ("dark", "light")
DEFAULT_THEME: Final[Theme] = "dark"
_SCHEMA_VERSION: Final = 1

SettingState = Literal["not_set", "present", "missing", "inaccessible"]
"""Ścieżka z Ustawień Centrum: niewskazana, jest, nie ma jej albo jest niedostępna (np. folder bez dostępu)."""

REGISTER: Final = "rejestr_zlecen"
PERIODS_DIRECTORY: Final = "folder_okresow"
THEME: Final = "motyw"
_SECTIONS: Final[Mapping[str, str]] = {REGISTER: "foldery", PERIODS_DIRECTORY: "foldery", THEME: "wyglad"}
"""Sekcja okna Ustawień każdego klucza pliku; klucz Historii to ``sekcja.klucz``."""


@dataclass(frozen=True)
class FolderSettings:
    register: Path | None = None
    periods_directory: Path | None = None
    theme: Theme = DEFAULT_THEME

    @property
    def register_state(self) -> SettingState:
        return _setting_state(self.register, "file")

    @property
    def periods_directory_state(self) -> SettingState:
        return _setting_state(self.periods_directory, "folder")

    @property
    def register_to_read(self) -> Path | None:
        """Wskazany Rejestr zleceń, którego nie brakuje; niedostępny też, bo o niedostępności mówi dopiero jego odczyt."""

        return self.register if self.register_state in _TO_READ else None

    @property
    def periods_directory_to_read(self) -> Path | None:
        """Wskazany folder okresów, którego nie brakuje; niedostępny też, bo o niedostępności mówi dopiero jego odczyt."""

        return self.periods_directory if self.periods_directory_state in _TO_READ else None


_TO_READ: tuple[SettingState, ...] = ("present", "inaccessible")


def _setting_state(path: Path | None, kind: Literal["file", "folder"]) -> SettingState:
    if path is None:
        return "not_set"
    state: PathState = path_state(path)
    if state == "inaccessible":
        return "inaccessible"
    return "present" if state == kind else "missing"


def parse(data: bytes | None) -> FolderSettings | FieldProblem:
    """Foldery i motyw z bajtów pliku; ``None`` (brak pliku) to wartości domyślne, zła treść to pierwszy problem."""

    if data is None:
        return FolderSettings()
    try:
        document = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(SETTINGS_FILE))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(SETTINGS_FILE))
    if not isinstance(document, dict):
        return FieldProblem(None, messages.damaged(SETTINGS_FILE))
    if document.get("schema_version") != _SCHEMA_VERSION:
        return FieldProblem(None, messages.other_schema(SETTINGS_FILE))
    unknown = next((key for key in document if key != "schema_version" and key not in _SECTIONS), None)
    if unknown is not None:
        return FieldProblem(str(unknown), messages.unknown_key(SETTINGS_FILE, str(unknown)))
    register = _path(document.get(REGISTER), REGISTER, messages.register_path, suffix=".xlsx")
    if isinstance(register, FieldProblem):
        return register
    periods_directory = _path(document.get(PERIODS_DIRECTORY), PERIODS_DIRECTORY, messages.periods_directory_path)
    if isinstance(periods_directory, FieldProblem):
        return periods_directory
    theme = _theme(document.get(THEME, DEFAULT_THEME))
    if theme is None:
        return FieldProblem(THEME, messages.unknown_theme())
    return FolderSettings(register=register, periods_directory=periods_directory, theme=theme)


def _path(value: object, key: str, sentence: Callable[[], str], *, suffix: str | None = None) -> Path | None | FieldProblem:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not Path(value).is_absolute():
        return FieldProblem(key, sentence())
    if suffix is not None and Path(value).suffix.lower() != suffix:
        return FieldProblem(key, sentence())
    return Path(value)


def dump(settings: FolderSettings) -> str:
    document = {"schema_version": _SCHEMA_VERSION, **_values(settings)}
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=1_000_000)


def _values(settings: FolderSettings) -> dict[str, str | None]:
    return {
        REGISTER: None if settings.register is None else str(settings.register),
        PERIODS_DIRECTORY: None if settings.periods_directory is None else str(settings.periods_directory),
        THEME: settings.theme,
    }


def diff(before: FolderSettings, after: FolderSettings) -> tuple[KeyChange, ...]:
    old, new = _values(before), _values(after)
    return tuple(KeyChange(f"{_SECTIONS[key]}.{key}", old[key], new[key]) for key in _SECTIONS if old[key] != new[key])


def restore(settings: FolderSettings, changes: tuple[KeyChange, ...]) -> FolderSettings:
    """``settings`` z każdym kluczem ``changes`` ustawionym na wartość sprzed zmiany; nieznany klucz zostaje bez zmian."""

    values = _values(settings)
    for change in changes:
        section, _, key = change.key.partition(".")
        if _SECTIONS.get(key) == section:
            values[key] = change.before
    register, periods_directory = values[REGISTER], values[PERIODS_DIRECTORY]
    return replace(
        settings,
        register=None if register is None else Path(register),
        periods_directory=None if periods_directory is None else Path(periods_directory),
        theme=_theme(values[THEME]) or settings.theme,
    )


def _theme(value: object) -> Theme | None:
    return next((theme for theme in THEMES if theme == value), None)


def reported(change: KeyChange) -> str:
    """Zmiana klucza w Zgłoszeniu: ścieżka tylko nazwą pliku albo ostatniego folderu (jak w Komunikatach), bo pełna
    ścieżka ma nazwę konta taty; motyw wprost."""

    return f"{change.key}: {_shown(change.key, change.before)} → {_shown(change.key, change.after)}"


def _shown(key: str, value: str | None) -> str:
    if value is None:
        return "nie ustawiono"
    return value if key.endswith(f".{THEME}") else PureWindowsPath(value).name


FOLDERS: Final = SettingsFile(
    name=SETTINGS_FILE, parse=parse, dump=dump, diff=diff, restore=restore, reported=reported, default=FolderSettings()
)
