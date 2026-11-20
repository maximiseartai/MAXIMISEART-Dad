from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rozliczenia.centrum.box_prefix import BoxPrefix
from rozliczenia.centrum.clock import Clock
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.client_data import ForbiddenValues


@dataclass(frozen=True)
class CentrumWork:
    config: Path
    log: CentrumLog
    clock: Clock
    pause: Callable[[float], None]
    forbidden: ForbiddenValues
    box_prefix: BoxPrefix | None
