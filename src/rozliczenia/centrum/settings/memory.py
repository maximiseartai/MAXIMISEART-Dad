"""Pamięć właściciela Ustawień Centrum w ``config/ustawienia-pamiec``: dla każdego pliku ostatni stan, który właściciel
przyjął (``seen``), i ostatnia dobra treść (``good``), a obok kopie złej treści nadpisanej zapisem taty (``odrzucone``)
i zmiany z Wydań, których właściciel już nie stosuje (``zmiany-z-wydan.json``).

Stan pliku to brak pliku (``None``) albo jego bajty. ``seen`` to ostatni przyjęty stan, także brak pliku i zła treść,
którą Historia już ma; stan pliku różny od ``seen`` to zmiana spoza Centrum. ``good`` daje wartość przed tą zmianą
i ostatnią dobrą wartość przy złym pliku. Pamięci się nie kasuje: brak pamięci (``None`` z ``read``) znaczy tylko, że
właściciel nie przyjął jeszcze żadnego stanu, co odróżnia pierwszy start po Wydaniu od przyjętego braku pliku.
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
from rozliczenia.centrum.settings.files import Unreadable
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


class Remembered(BaseModel):
    """Pamięć jednego pliku: ``seen`` ostatni przyjęty stan, ``good`` ostatnia dobra treść; ``None``: brak pliku."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True, ser_json_bytes="base64", val_json_bytes="base64")

    version: Literal[1] = Field(default=1, validation_alias="v", serialization_alias="v")
    seen: bytes | None = Field(validation_alias="widziany", serialization_alias="widziany")
    good: bytes | None = Field(validation_alias="dobry", serialization_alias="dobry")


@dataclass(frozen=True)
class Memory:
    config: Path
    pause: Callable[[float], None]

    def read(self, name: str) -> Remembered | None | Unreadable:
        """Pamięć pliku ``name``; ``None``: brak pamięci (także treść, której nie da się przeczytać jako pamięci),
        ``Unreadable``: plik pamięci jest, ale system nie daje go teraz czytać."""

        data = settings_bytes(self._path(name))
        if isinstance(data, OSError):
            return Unreadable()
        if data is None:
            return None
        try:
            return Remembered.model_validate_json(data)
        except ValidationError:
            return None

    def write(self, name: str, remembered: Remembered) -> None:
        """Zapamiętuje stan pliku ``name``; ``OSError``, gdy się nie udało."""

        replace_atomically(self._path(name), remembered.model_dump_json(by_alias=True).encode("utf-8"), pause=self.pause)

    def applied(self) -> dict[str, Applied] | AppliedUnknown:
        """Zmiany z Wydań, które już nie wracają, po id; brak pamięci to żadna."""

        data = settings_bytes(self.config / MEMORY_DIRECTORY / APPLIED_FILE)
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
        replace_atomically(self.config / MEMORY_DIRECTORY / APPLIED_FILE, document.encode("utf-8"), pause=self.pause)

    def keep_rejected(self, name: str, data: bytes, at: datetime) -> None:
        """Kopia złej treści pliku ``name`` przed zapisem taty, który ją nadpisuje; nieudana kopia nie zatrzymuje zapisu."""

        with suppress(OSError):
            replace_atomically(self.config / MEMORY_DIRECTORY / _REJECTED / f"{name}.{at:%Y%m%d-%H%M%S}", data, pause=self.pause)

    def _path(self, name: str) -> Path:
        return self.config / MEMORY_DIRECTORY / f"{name}.json"


def settings_bytes(path: Path) -> bytes | None | OSError:
    """Bajty pliku Ustawień Centrum, ich Historii albo pamięci; ``None``: pliku nie ma, ``OSError``: plik jest, ale system
    nie daje go teraz czytać."""

    try:
        return path.read_bytes()
    except OSError as failure:
        return None if file_state(path) == "missing" else failure
