"""Pliki tylko w chmurze: plik OneDrive „tylko online” nie ma kopii na komputerze taty.

OneDrive w Windows oznacza taki plik atrybutem, który widać w ``os.stat``
bez pobierania pliku. Odczyt atrybutów jest wstrzykiwany do aplikacji
Centrum; poza Windows go nie ma i Diagnoza pomija to sprawdzenie.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Final

_ONLINE_ONLY: Final = 0x1000 | 0x40000 | 0x400000
"""``FILE_ATTRIBUTE_OFFLINE``, ``FILE_ATTRIBUTE_RECALL_ON_OPEN`` i ``FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS``."""

FileAttributes = Callable[[Path], int]


@dataclass(frozen=True)
class CloudFiles:
    """Atrybuty plików Windows; ``read_attributes=None`` poza Windows, gdzie nie ma czego sprawdzać."""

    read_attributes: FileAttributes | None

    @classmethod
    def of_system(cls) -> CloudFiles:
        return cls(_windows_attributes if sys.platform == "win32" else None)

    @property
    def checked(self) -> bool:
        return self.read_attributes is not None

    def online_only(self, path: Path) -> bool:
        """Czy istniejący plik ``path`` jest tylko w chmurze; plik, którego atrybutów nie da się odczytać, nie jest."""

        if self.read_attributes is None:
            return False
        try:
            return bool(self.read_attributes(path) & _ONLINE_ONLY)
        except OSError:
            return False


def _windows_attributes(path: Path) -> int:
    """Atrybuty pliku z ``stat``, który czyta metadane i nie pobiera pliku z chmury; ``st_file_attributes`` istnieje
    tylko w Windows, więc poza nim to 0."""

    attributes: int = getattr(path.stat(), "st_file_attributes", 0)
    return attributes
