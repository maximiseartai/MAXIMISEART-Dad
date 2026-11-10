"""Pamięć własnych wpisów Wpisania raportów w ``config`` (ADR 0028): jedyny moduł, który zna format jej pliku.

Plik ``wpisanie-raportow-stan.json`` ma postać ``{schema_version: 1, rollout, own: [{number, day, worker, column,
value}]}``: dzień wdrożenia i komórki, które Wpisanie raportów samo wpisało. Pisze go tylko proces po udanym zapisie
INTERMAX, atomowo (``atomic_file.StateFile``); treść, której nie dało się zapisać, czeka w pamięci tej pracy Centrum i
wygrywa przy następnym odczycie. Plik, którego nie da się odczytać (zły JSON, nieznana wersja, zły wpis), to ``StateUnreadable``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.work import CentrumWork
from rozliczenia.intermax_cells import CellsWritten
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import SavedState, StateUnreadable
from rozliczenia.tool_files import REPORT_ENTERING_STATE
from rozliczenia.worker_reports import Login, OrderKey, OrderNumber, OwnEntries, OwnEntry

_SCHEMA_VERSION: Final = 1


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Own(_Record):
    number: str
    day: date
    worker: str
    column: Literal["SKUTECZNE", "CZYNNOŚCI ZREALIZOWANE"]
    value: str


class _State(_Record):
    schema_version: Literal[1]
    rollout: date
    own: list[_Own]


@dataclass
class FileReportState:
    """Pamięć własnych wpisów w pliku ``config`` pracy Centrum; ``_written`` to ostatnia treść, którą zapisała ta praca."""

    file: StateFile
    _written: str | None = field(default=None, repr=False)

    @classmethod
    def of_work(cls, work: CentrumWork) -> FileReportState:
        path = work.config / REPORT_ENTERING_STATE
        return cls(StateFile(path, work.log, where="pamięć Wpisania raportów", pause=work.pause))

    def load(self) -> SavedState:
        self.file.retry()
        waiting = self._written if self.file.unavailable else None
        try:
            text = waiting if waiting is not None else self.file.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return SavedState(None, OwnEntries.EMPTY)
        except (OSError, UnicodeDecodeError) as error:
            raise StateUnreadable from error
        try:
            state = _State.model_validate_json(text)
            entries = frozenset(
                OwnEntry(
                    OrderKey(OrderNumber(own.number), own.day, Login(own.worker)), ReportColumn(own.column), own.value
                )
                for own in state.own
            )
            return SavedState(state.rollout, OwnEntries(entries))
        except (ValidationError, ValueError) as error:
            raise StateUnreadable from error

    def save_memory(self, written: CellsWritten, rollout: date, memory: OwnEntries) -> bool:
        own = [
            _Own(
                number=entry.key.number,
                day=entry.key.day,
                worker=entry.key.worker,
                column=entry.column.value,
                value=entry.value,
            )
            for entry in sorted(memory.entries, key=lambda entry: (entry.key, entry.column.value, entry.value))
        ]
        state = _State(schema_version=_SCHEMA_VERSION, rollout=rollout, own=own)
        self._written = json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
        self.file.write(self._written)
        return not self.file.unavailable
