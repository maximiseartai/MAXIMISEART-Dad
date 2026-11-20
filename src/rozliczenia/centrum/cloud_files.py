from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import stat
import sys
from typing import Final

_FILE_ATTRIBUTE_RECALL_ON_OPEN: Final = 0x40000
_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS: Final = 0x400000
# ZEWNĘTRZNE: OneDrive w Windows oznacza plik „tylko online” bez kopii na komputerze atrybutem OFFLINE, RECALL_ON_OPEN albo RECALL_ON_DATA_ACCESS (Microsoft Learn, File Attribute Constants)
_ONLINE_ONLY: Final = stat.FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_RECALL_ON_OPEN | _FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

FileAttributes = Callable[[Path], int]


@dataclass(frozen=True)
class CloudFiles:
    read_attributes: FileAttributes | None

    @classmethod
    def of_system(cls) -> CloudFiles:
        return cls(_windows_attributes if sys.platform == "win32" else None)

    @property
    def checked(self) -> bool:
        return self.read_attributes is not None

    def online_only(self, path: Path) -> bool:
        if self.read_attributes is None:
            return False
        try:
            return bool(self.read_attributes(path) & _ONLINE_ONLY)
        except OSError:
            return False


def _windows_attributes(path: Path) -> int:
    # ZEWNĘTRZNE: os.stat w Windows czyta atrybuty pliku z metadanych, bez pobierania pliku z chmury, a pole st_file_attributes ma tylko w Windows (dokumentacja Pythona, os.stat_result.st_file_attributes)
    attributes: int = getattr(path.stat(), "st_file_attributes", 0)
    return attributes
