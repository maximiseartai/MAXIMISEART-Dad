"""Ustawienia taty w Centrum rozliczeń: Rejestr zleceń, folder okresów i motyw, w lokalnym pliku YAML poza gitem.

Centrum czyta je, wskazuje Rejestr zleceń i folder okresów oknem wyboru i zmienia motyw. Rejestr zleceń z Ustawień
taty otwiera się też z karty wyniku, gdy Zatrzymanie każe go poprawić. Brak albo uszkodzenie pliku znaczy „nie
ustawiono”, nigdy błąd startu. Zapis podmienia plik atomowo, więc przerwany zapis zostawia poprzednie ustawienia.

Moduł nie wczytuje FastAPI: Ustawienia taty czytają też katalog procesów i gospodarze Uruchomień bez serwera, a ich
interfejs HTTP jest w ``settings_router``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile
import threading
from typing import Literal

import yaml

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
