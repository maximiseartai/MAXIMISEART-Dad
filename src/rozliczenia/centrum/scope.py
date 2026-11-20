from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass
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


class Workstation(enum.StrEnum):
    DAD = "tata"


@dataclass(frozen=True)
class Scope:
    workstation: Workstation
    functions: frozenset[CentrumFunction]

    def covers(self, part: Part) -> bool:
        return part is ALWAYS or part in self.functions

    def listed(self) -> list[CentrumFunction]:
        return [function for function in CentrumFunction if function in self.functions]


SCOPES: Final[Mapping[Workstation, Scope]] = MappingProxyType(
    {Workstation.DAD: Scope(Workstation.DAD, frozenset(CentrumFunction))}
)
