"""Pamięć właściciela Ustawień Centrum w ``config/ustawienia-pamiec``: bajty ostatniej treści każdego pliku, którą
właściciel przyjął (własny zapis, przyjęta zmiana spoza Centrum, stan wyjściowy), i kopie złej treści nadpisanej
zapisem taty (``odrzucone``).

Porównanie bajtów pliku z pamięcią to odcisk: różne bajty to zmiana spoza Centrum, a pamięć daje wartość przed nią
i ostatnią dobrą wartość przy złym pliku. Brak pliku pamięci znaczy, że właściciel nie przyjął jeszcze żadnej treści
albo przyjął brak pliku.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Final

from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.file_state import file_state

MEMORY_DIRECTORY: Final = "ustawienia-pamiec"
_REJECTED: Final = "odrzucone"


class Memory:
    def __init__(self, config: Path, pause: Callable[[float], None]) -> None:
        self._directory = config / MEMORY_DIRECTORY
        self._pause = pause

    def remembered(self, name: str) -> bytes | None:
        """Ostatnia przyjęta treść pliku ``name``; ``None``: brak pamięci (także pamięć, której nie da się czytać)."""

        remembered = settings_bytes(self._directory / name)
        return None if isinstance(remembered, OSError) else remembered

    def remember(self, name: str, data: bytes | None) -> None:
        """Zapamiętuje treść ``data`` pliku ``name`` (``None``: przyjęty brak pliku); ``OSError``, gdy się nie udało."""

        path = self._directory / name
        if data is None:
            path.unlink(missing_ok=True)
            return
        replace_atomically(path, data, pause=self._pause)

    def keep_rejected(self, name: str, data: bytes, at: datetime) -> None:
        """Kopia złej treści pliku ``name`` przed zapisem taty, który ją nadpisuje; nieudana kopia nie zatrzymuje zapisu."""

        with suppress(OSError):
            replace_atomically(self._directory / _REJECTED / f"{name}.{at:%Y%m%d-%H%M%S}", data, pause=self._pause)


def settings_bytes(path: Path) -> bytes | None | OSError:
    """Bajty pliku Ustawień Centrum, ich Historii albo pamięci; ``None``: pliku nie ma, ``OSError``: plik jest, ale system
    nie daje go teraz czytać."""

    try:
        return path.read_bytes()
    except OSError as failure:
        return None if file_state(path) == "missing" else failure
