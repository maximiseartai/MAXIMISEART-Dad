from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TypeAlias


class Route(Enum):
    COPY = "kopia"
    OPENPYXL = "openpyxl"


class TemplateKind(Enum):
    WORKER_SETTLEMENT = "worker_settlement"
    COLLECTIVE_FILE = "collective_file"
    INTERNAL_SETTLEMENT = "internal_settlement"


RouteCounts: TypeAlias = "Mapping[tuple[TemplateKind, Route], int]"
