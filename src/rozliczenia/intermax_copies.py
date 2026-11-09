"""Kopie INTERMAX: stan Rejestru zleceń sprzed Uporządkowania INTERMAX albo sprzed przywrócenia Kopii, poza OneDrive.

Kopia ma nazwę z chwili zegara procesu, ``INTERMAX przed uporządkowaniem RRRR-MM-DD GG-MM-SS.xlsx`` albo
``INTERMAX przed przywróceniem RRRR-MM-DD GG-MM-SS.xlsx``, i bajty INTERMAX sprzed zapisu. Po udanym zapisie zostaje
``KEPT`` najnowszych Kopii obu nazw według chwili z nazwy; inne pliki w folderze zostają. Folder leży na dysku
narzędzia, więc OneDrive nie synchronizuje codziennie dużego pliku.

Ten moduł tylko nazywa i wymienia Kopie. Kopie zapisuje i usuwa wyłącznie podmiana INTERMAX (``intermax_replace``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from .tool_files import TOOL_ROOT

KEPT: Final = 10
Before = Literal["ordering", "restore"]
# Słowa z nazwy Kopii, które karta Kopii pokazuje tacie; nazwy Kopii u taty z nich powstały, więc się nie zmieniają.
_BEFORE: Final[Mapping[Before, str]] = {
    "ordering": "przed uporządkowaniem",
    "restore": "przed przywróceniem",
}
_BEFORE_OF_WORDS: Final = {words: before for before, words in _BEFORE.items()}
_NAME: Final = re.compile(
    rf"INTERMAX ({'|'.join(map(re.escape, _BEFORE.values()))}) (\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}-\d{{2}}-\d{{2}})\.xlsx"
)
_MOMENT: Final = "%Y-%m-%d %H-%M-%S"


@dataclass(frozen=True)
class Copy:
    """Kopia INTERMAX w folderze Kopii: plik, chwila z nazwy w czasie komputera i to, przed czym powstała."""

    path: Path
    moment: datetime
    before: Before

    @property
    def before_label(self) -> str:
        """To, przed czym powstała, słowami z nazwy Kopii."""

        return _BEFORE[self.before]


def default_directory() -> Path:
    return TOOL_ROOT / "Kopie INTERMAX"


def _copy(path: Path) -> Copy | None:
    found = _NAME.fullmatch(path.name)
    if found is None:
        return None
    try:
        moment = datetime.strptime(found[2], _MOMENT).astimezone()
    except ValueError:  # nazwa z nieistniejącą datą albo godziną nie pochodzi od narzędzia
        return None
    return Copy(path, moment, _BEFORE_OF_WORDS[found[1]])


def listed(directory: Path) -> list[Copy]:
    """Kopie INTERMAX w ``directory`` od najnowszej; brak folderu to brak Kopii, inny błąd odczytu to ``OSError``."""

    try:
        paths = list(directory.iterdir())
    except FileNotFoundError:
        return []
    copies = [copy for copy in map(_copy, paths) if copy is not None]
    return sorted(copies, key=lambda copy: (copy.moment, copy.path.name), reverse=True)


def named(directory: Path, before: Before, moment: datetime) -> Copy:
    """Kopia INTERMAX w ``directory``, którą podmiana zrobi przed ``before`` w chwili ``moment``, tak jak ją wymieni
    ``listed``."""

    copy = _copy(directory / f"INTERMAX {_BEFORE[before]} {moment:{_MOMENT}}.xlsx")
    assert copy is not None, "nazwa z _BEFORE i _MOMENT pasuje do _NAME"
    return copy


def outdated(directory: Path) -> list[Copy]:
    """Kopie INTERMAX obu nazw starsze niż ``KEPT`` najnowszych według chwili z nazwy; ``OSError`` jak ``listed``."""

    return listed(directory)[KEPT:]
