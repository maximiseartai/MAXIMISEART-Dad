from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final


class CentrumFunction(enum.StrEnum):
    PERIODS = "periods"
    FILLING = "filling"
    INTERMAX = "intermax"
    INTERMAX_COPIES = "intermax_copies"
    REPORT_ENTERING = "report_entering"
    REMINDERS = "reminders"
    SETTLEMENT_MAILING = "settlement_mailing"
    METRICS = "metrics"
    QUANTITIES = "quantities"
    WORKERS = "workers"
    TEMPLATES = "templates"
    REPORT_INBOX = "report_inbox"
    AUTOSTART = "autostart"


class Always(enum.Enum):
    PART = "stała część Centrum"


ALWAYS: Final = Always.PART

Part = CentrumFunction | Always


class BoxPrefix(enum.StrEnum):
    ANDRZEJ = "ANDRZEJ"


class Workstation(enum.StrEnum):
    DAD = "tata"
    ANDRZEJ = "andrzej"


@dataclass(frozen=True)
class Scope:
    workstation: Workstation
    functions: frozenset[CentrumFunction]
    box_prefix: BoxPrefix | None

    def covers(self, part: Part) -> bool:
        return part is ALWAYS or part in self.functions

    def listed(self) -> list[CentrumFunction]:
        return [function for function in CentrumFunction if function in self.functions]


SCOPES: Final[Mapping[Workstation, Scope]] = MappingProxyType(
    {
        Workstation.DAD: Scope(Workstation.DAD, frozenset(CentrumFunction), None),
        Workstation.ANDRZEJ: Scope(
            Workstation.ANDRZEJ, frozenset({CentrumFunction.INTERMAX, CentrumFunction.INTERMAX_COPIES}), BoxPrefix.ANDRZEJ
        ),
    }
)

WORKSTATION_FILE: Final = "stanowisko.txt"


@dataclass(frozen=True)
class UnknownWorkstation:
    file: Path


def workstation_scope(config: Path) -> Scope | UnknownWorkstation:
    file = config / WORKSTATION_FILE
    try:
        written = file.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return SCOPES[Workstation.DAD]
    except (OSError, UnicodeDecodeError):
        return UnknownWorkstation(file)
    try:
        return SCOPES[Workstation(written.strip())]
    except ValueError:
        return UnknownWorkstation(file)


def write_workstation(config: Path, workstation: Workstation) -> Path:
    file = config / WORKSTATION_FILE
    config.mkdir(parents=True, exist_ok=True)
    file.write_text(f"{workstation.value}\n", encoding="utf-8")
    return file
