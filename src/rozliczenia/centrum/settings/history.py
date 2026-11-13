"""Historia Ustawień w ``config/historia-ustawien.jsonl``: jeden wiersz JSON na jeden zapis, dopisywany linia po linii.

Wiersz mówi, kiedy, skąd (tata albo zmiana spoza Centrum), który plik i które klucze się zmieniły, z wartością przed
i po (sekret bez wartości), czy da się go cofnąć i czy zmiana weszła (``zapisano``) albo została odrzucona z powodem.
Linia, której nie da się przeczytać (np. urwana zgaśnięciem Centrum), jest pomijana i liczona; Historii się nie przycina.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S
from rozliczenia.centrum.settings.files import KeyChange
from rozliczenia.centrum.settings.memory import settings_bytes

HISTORY_FILE: Final = "historia-ustawien.jsonl"
_VERSION: Final = 1

SourceKind = Literal["tata", "spoza"]
"""Skąd zmiana: zapis taty w Centrum (także cofnięcie) albo plik w ``config`` zmieniony poza Centrum."""
RowResult = Literal["zapisano", "odrzucono"]


class _Model(BaseModel):
    """Model pliku Historii: pola po angielsku w kodzie, a w pliku pod polskimi nazwami (``validation_alias``)."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class RowSource(_Model):
    kind: SourceKind = Field(validation_alias="rodzaj", serialization_alias="rodzaj")


class RowChange(_Model):
    key: str = Field(validation_alias="klucz", serialization_alias="klucz")
    before: str | None = Field(validation_alias="przed", serialization_alias="przed")
    after: str | None = Field(validation_alias="po", serialization_alias="po")

    @classmethod
    def of(cls, change: KeyChange) -> RowChange:
        return cls(key=change.key, before=change.before, after=change.after)

    def change(self) -> KeyChange:
        return KeyChange(self.key, self.before, self.after)


class HistoryRow(_Model):
    """Wiersz Historii Ustawień. ``fingerprint``: odcisk złej treści spoza Centrum (wiersz ``odrzucono``), żeby ta sama
    zła treść dała jeden wiersz."""

    version: Literal[1] = Field(default=_VERSION, validation_alias="v", serialization_alias="v")
    id: str
    at: datetime = Field(validation_alias="kiedy", serialization_alias="kiedy")
    source: RowSource = Field(validation_alias="zrodlo", serialization_alias="zrodlo")
    undoes: str | None = Field(validation_alias="cofa", serialization_alias="cofa")
    file: str = Field(validation_alias="plik", serialization_alias="plik")
    section: str | None = Field(validation_alias="sekcja", serialization_alias="sekcja")
    changes: tuple[RowChange, ...] = Field(validation_alias="zmiany", serialization_alias="zmiany")
    secret: bool = Field(validation_alias="sekret", serialization_alias="sekret")
    undoable: bool = Field(validation_alias="cofalny", serialization_alias="cofalny")
    result: RowResult = Field(validation_alias="wynik", serialization_alias="wynik")
    reason: str | None = Field(validation_alias="powod", serialization_alias="powod")
    fingerprint: str | None = Field(default=None, validation_alias="odcisk", serialization_alias="odcisk")

    def key_changes(self) -> tuple[KeyChange, ...]:
        return tuple(change.change() for change in self.changes)


class HistoryRead(_Model):
    """Wiersze Historii od najnowszego i liczba linii, których nie dało się przeczytać."""

    rows: tuple[HistoryRow, ...]
    skipped: int


class History:
    def __init__(self, config: Path, pause: Callable[[float], None]) -> None:
        self._path = config / HISTORY_FILE
        self._pause = pause

    def append(self, row: HistoryRow) -> None:
        """Dopisuje wiersz, ponawiając po przerwach ``RETRY_PAUSES_S``; ``OSError``, gdy mimo to się nie udało.

        Linię urwaną zgaśnięciem Centrum wiersz zaczyna od nowej linii, więc nie skleja się z nią.
        """

        line = row.model_dump_json(by_alias=True).encode("utf-8") + b"\n"
        for seconds in (*RETRY_PAUSES_S, None):
            try:
                self._write(line)
                return
            except OSError:
                if seconds is None:
                    raise
                self._pause(seconds)

    def _write(self, line: bytes) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+b") as history:
            if history.tell() > 0:
                history.seek(-1, 2)
                if history.read(1) != b"\n":
                    line = b"\n" + line
            history.write(line)

    def read(self) -> HistoryRead:
        """Wiersze od najnowszego; brak pliku albo plik, którego nie da się czytać, to pusta Historia."""

        data = settings_bytes(self._path)
        if data is None or isinstance(data, OSError):
            return HistoryRead(rows=(), skipped=0)
        lines = data.splitlines()
        rows: list[HistoryRow] = []
        skipped = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                rows.append(HistoryRow.model_validate_json(line))
            except ValidationError:
                skipped += 1
        return HistoryRead(rows=tuple(reversed(rows)), skipped=skipped)
