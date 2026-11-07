"""Drogi zapisu plików z Wzorca (ADR 0008): rodzaj pliku i droga, którą powstał, do metryk i podsumowań procesów."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TypeAlias


class Route(Enum):
    """Droga, którą powstał plik z Wzorca (ADR 0008); oba dają ten sam plik, a kopia jest szybsza."""

    COPY = "kopia"
    OPENPYXL = "openpyxl"


class TemplateKind(Enum):
    """Plik, który powstaje z Wzorca, nazwany jak konstruktor ``TemplateFile``."""

    WORKER_SETTLEMENT = "worker_settlement"
    COLLECTIVE_FILE = "collective_file"
    INTERNAL_SETTLEMENT = "internal_settlement"


RouteCounts: TypeAlias = "Mapping[tuple[TemplateKind, Route], int]"
"""Drogi zapisu: ile plików każdego rodzaju powstało każdą drogą; para bez plików może nie mieć wpisu."""
