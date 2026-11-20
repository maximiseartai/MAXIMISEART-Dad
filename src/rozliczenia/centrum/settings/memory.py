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
AppliedResult = Literal["zastosowano", "bez-zmian", "odrzucono"]

class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class Applied(_Model):
    at: datetime = Field(validation_alias="kiedy", serialization_alias="kiedy")
    release: str | None = Field(validation_alias="wydanie", serialization_alias="wydanie")
    commit: str | None
    result: AppliedResult = Field(validation_alias="wynik", serialization_alias="wynik")


class _AppliedFile(_Model):
    schema_version: Literal[1] = 1
    changes: dict[str, Applied] = Field(validation_alias="zmiany", serialization_alias="zmiany")


@dataclass(frozen=True)
class AppliedUnknown:
    ...


class Remembered(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True, ser_json_bytes="base64", val_json_bytes="base64")

    version: Literal[1] = Field(default=1, validation_alias="v", serialization_alias="v")
    seen: bytes | None = Field(validation_alias="widziany", serialization_alias="widziany")
    good: bytes | None = Field(validation_alias="dobry", serialization_alias="dobry")


@dataclass(frozen=True)
class Memory:
    config: Path
    pause: Callable[[float], None]

    def read(self, name: str) -> Remembered | None | Unreadable:
        data = settings_bytes(self._path(name))
        if isinstance(data, OSError):
            return Unreadable(self._path(name).name)
        if data is None:
            return None
        try:
            return Remembered.model_validate_json(data)
        except ValidationError:
            return None

    def write(self, name: str, remembered: Remembered) -> None:
        replace_atomically(self._path(name), remembered.model_dump_json(by_alias=True).encode("utf-8"), pause=self.pause)

    def applied(self) -> dict[str, Applied] | AppliedUnknown:
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
        document = _AppliedFile(changes=dict(changes)).model_dump_json(by_alias=True, indent=2)
        replace_atomically(self.config / MEMORY_DIRECTORY / APPLIED_FILE, document.encode("utf-8"), pause=self.pause)

    def keep_rejected(self, name: str, data: bytes, at: datetime) -> None:
        with suppress(OSError):
            replace_atomically(self.config / MEMORY_DIRECTORY / _REJECTED / f"{name}.{at:%Y%m%d-%H%M%S}", data, pause=self.pause)

    def _path(self, name: str) -> Path:
        return self.config / MEMORY_DIRECTORY / f"{name}.json"


def settings_bytes(path: Path) -> bytes | None | OSError:
    try:
        return path.read_bytes()
    except OSError as failure:
        return None if file_state(path) == "missing" else failure
