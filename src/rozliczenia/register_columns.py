from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Column:
    register_header: str
    target_header: str
    older_register_headers: tuple[str, ...] = ()

    @property
    def register_headers(self) -> tuple[str, ...]:
        return (self.register_header, *self.older_register_headers)

    @property
    def label(self) -> str:
        return " albo ".join(self.register_headers)


DATE: Final = Column("DATA GODZ. POCZ.", "DATA")
CITY: Final = Column("MIASTO", "MIASTO")
ADDRESS: Final = Column("ADRES", "ADRES")
CONTRACT: Final = Column("UMOWA", "UMOWA")
DEVICES: Final = Column("URZĄDZENIA", "URZĄDZENIA")
ACTIVITIES: Final = Column("CZYNNOŚCI", "CZYNNOŚCI")
ORDER_NUMBER: Final = Column("NUMER ZL.", "NUMER ZL.", ("nr zlecenia",))
WORKER: Final = Column("WYKONAWCA", "WYKONAWCA")
CONTRACT_NUMBER: Final = Column("NUMER UMOWY", "NUMER UMOWY/ZLECENIA ORANGE", ("NUMER UMOWY/ZLECENIA ORANGE",))
SUCCESSFUL: Final = Column("SKUTECZNE", "SKUTECZNE")
COMPLETED: Final = Column("CZYNNOŚCI ZREALIZOWANE", "CZYNNOŚCI ZREALIZOWANE")
COLUMNS: Final[tuple[Column, ...]] = (
    DATE,
    CITY,
    ADDRESS,
    CONTRACT,
    DEVICES,
    ACTIVITIES,
    ORDER_NUMBER,
    WORKER,
    CONTRACT_NUMBER,
    SUCCESSFUL,
    COMPLETED,
)
TARGET_HEADERS: Final[tuple[str, ...]] = tuple(column.target_header for column in COLUMNS)

ORDERED_FONT: Final = "Calibri"
ORDERED_SIZE: Final = 8
WORKER_SIZE: Final = 9
DAY_FILL: Final = "FFFF00"
