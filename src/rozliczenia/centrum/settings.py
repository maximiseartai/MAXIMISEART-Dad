"""Ustawienia taty w Centrum rozliczeń: Rejestr zleceń, folder okresów i motyw, w lokalnym pliku YAML poza gitem.

Centrum czyta je, wskazuje Rejestr zleceń i folder okresów oknem wyboru i zmienia motyw. Rejestr zleceń z Ustawień
taty otwiera się też z karty wyniku, gdy Zatrzymanie każe go poprawić. Brak albo uszkodzenie pliku znaczy „nie
ustawiono”, nigdy błąd startu. Zapis podmienia plik atomowo, więc przerwany zapis zostawia poprzednie ustawienia.

Zmiana nie zapisuje się na Ustawieniach, których nie dało się przeczytać: plik niedostępny (na Windows trzyma go np.
antywirus) zostaje, a zmiana jest odmową. Uszkodzoną treść i plik innego schematu zmiana nadpisuje. Taki plik
przeglądarka dostaje jako nieczytelny (``read``), a procesy jako nieustawiony (``load``).

Moduł nie wczytuje FastAPI: Ustawienia taty czytają też katalog procesów i gospodarze Uruchomień bez serwera, a ich
interfejs HTTP jest w ``settings_router``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
import threading
from typing import Final, Literal

import yaml

from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S, replace_atomically
from rozliczenia.centrum.log import CentrumLog, SettingsUnreadableCause
from rozliczenia.file_state import PathState, file_state, path_state

Theme = Literal["dark", "light"]
_THEMES: tuple[Theme, ...] = ("dark", "light")
DEFAULT_THEME: Final[Theme] = "dark"
_SCHEMA_VERSION = 1

SettingState = Literal["not_set", "present", "missing", "inaccessible"]
"""Ścieżka z Ustawień taty: niewskazana, jest, nie ma jej albo jest niedostępna (np. folder bez dostępu)."""


@dataclass(frozen=True)
class Settings:
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


class SettingsUnreadable(Exception):
    """Pliku Ustawień taty nie dało się przeczytać przed zmianą, więc zmiany nie zapisano."""


class SettingsStore:
    def __init__(self, path: Path, *, log: CentrumLog, pause: Callable[[float], None]) -> None:
        """Ustawienia w pliku ``path``; ``pause`` czeka przed kolejną próbą odczytu albo zamiany pliku niedostępnego."""

        self._path = path
        self._log = log
        self._pause = pause
        self._lock = threading.Lock()

    def load(self) -> Settings:
        """Ustawienia z pliku; plik, którego nie da się teraz przeczytać, to ``Settings()``."""

        read = self.read()
        return Settings() if read is None else read

    def read(self) -> Settings | None:
        """Ustawienia z pliku; ``None``, gdy plik jest, ale nie da się go teraz przeczytać."""

        read = self._read()
        return read if isinstance(read, Settings) else None

    def update(
        self,
        *,
        register: Path | None = None,
        periods_directory: Path | None = None,
        theme: Theme | None = None,
    ) -> Settings:
        """Ustawienia po zmianie zapisane w pliku; ``SettingsUnreadable``, gdy pliku nie dało się przeczytać, a
        ``OSError``, gdy nie dało się go zapisać."""

        with self._lock:
            current = self._current()
            updated = replace(
                current,
                register=register or current.register,
                periods_directory=periods_directory or current.periods_directory,
                theme=theme or current.theme,
            )
            self._write(updated)
            return updated

    def _current(self) -> Settings:
        """Ustawienia przed zmianą; plik niedostępny czyta ponownie po kolejnych przerwach, jak zamiana pliku."""

        read = self._read()
        for seconds in RETRY_PAUSES_S:
            if read != "dostep":
                break
            self._pause(seconds)
            read = self._read()
        if isinstance(read, Settings):
            return read
        self._log.settings_unreadable(cause=read)
        raise SettingsUnreadable(read)

    def _read(self) -> Settings | SettingsUnreadableCause:
        """Ustawienia z pliku; brak pliku, treść uszkodzona i inny schemat to ``Settings()``, a plik, który jest, ale nie
        da się go przeczytać, to ``"dostep"``."""

        try:
            text = self._path.read_text(encoding="utf-8")
        except UnicodeError:
            return Settings()
        except OSError:
            return Settings() if file_state(self._path) == "missing" else "dostep"
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError:
            return Settings()
        if not isinstance(document, dict):
            return Settings()
        if document.get("schema_version") != _SCHEMA_VERSION:
            return Settings()
        theme = document.get("motyw")
        return Settings(
            register=_path_or_none(document.get("rejestr_zlecen")),
            periods_directory=_path_or_none(document.get("folder_okresow")),
            theme=theme if theme in _THEMES else DEFAULT_THEME,
        )

    def _write(self, settings: Settings) -> None:
        document = {
            "schema_version": _SCHEMA_VERSION,
            "rejestr_zlecen": None if settings.register is None else str(settings.register),
            "folder_okresow": None if settings.periods_directory is None else str(settings.periods_directory),
            "motyw": settings.theme,
        }
        text = yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=1_000_000)
        replace_atomically(self._path, text, pause=self._pause)


def _path_or_none(value: object) -> Path | None:
    return Path(value) if isinstance(value, str) and value else None
