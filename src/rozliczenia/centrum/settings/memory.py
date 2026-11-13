"""Pamięć właściciela Ustawień Centrum w ``config/ustawienia-pamiec``: bajty ostatniej treści każdego pliku, którą
właściciel przyjął (własny zapis, przyjęta zmiana spoza Centrum, stan wyjściowy), i kopie złej treści nadpisanej
zapisem taty (``odrzucone``) i zmiany z Wydań, które właściciel już zastosował (``zmiany-z-wydan.json``).

Porównanie bajtów pliku z pamięcią to odcisk: różne bajty to zmiana spoza Centrum, a pamięć daje wartość przed nią
i ostatnią dobrą wartość przy złym pliku. Brak pliku pamięci znaczy, że właściciel nie przyjął jeszcze żadnej treści
albo przyjął brak pliku.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.file_state import file_state

MEMORY_DIRECTORY: Final = "ustawienia-pamiec"
_REJECTED: Final = "odrzucone"
APPLIED_FILE: Final = "zmiany-z-wydan.json"
"""Pamięć zmian z Wydań, które już nie wracają (``release_changes``), w folderze pamięci."""

AppliedResult = Literal["zastosowano", "bez-zmian", "odrzucono"]
"""Wynik zmiany z Wydania, po którym już nie wraca: weszła, nie było nic do zmiany albo została odrzucona."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class Applied(_Model):
    """Zastosowana zmiana z Wydania: kiedy, z którego Wydania (numer, skrót commitu) i z jakim wynikiem."""

    at: datetime = Field(validation_alias="kiedy", serialization_alias="kiedy")
    release: str | None = Field(validation_alias="wydanie", serialization_alias="wydanie")
    commit: str | None
    result: AppliedResult = Field(validation_alias="wynik", serialization_alias="wynik")


class _AppliedFile(_Model):
    schema_version: Literal[1] = 1
    changes: dict[str, Applied] = Field(validation_alias="zmiany", serialization_alias="zmiany")


@dataclass(frozen=True)
class AppliedUnknown:
    """Pamięci zmian z Wydań nie da się przeczytać (system jej nie daje albo jest uszkodzona)."""


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

    def applied(self) -> dict[str, Applied] | AppliedUnknown:
        """Zmiany z Wydań, które już nie wracają, po id; brak pamięci to żadna."""

        data = settings_bytes(self._directory / APPLIED_FILE)
        if data is None:
            return {}
        if isinstance(data, OSError):
            return AppliedUnknown()
        try:
            return dict(_AppliedFile.model_validate_json(data).changes)
        except ValidationError:
            return AppliedUnknown()

    def remember_applied(self, changes: Mapping[str, Applied]) -> None:
        """Zapamiętuje zmiany z Wydań ``changes`` (wszystkie, nie tylko nową); ``OSError``, gdy się nie udało."""

        document = _AppliedFile(changes=dict(changes)).model_dump_json(by_alias=True, indent=2)
        replace_atomically(self._directory / APPLIED_FILE, document.encode("utf-8"), pause=self._pause)

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
