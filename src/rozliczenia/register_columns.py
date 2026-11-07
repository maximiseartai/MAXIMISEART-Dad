"""Kolumny Rejestru zleceń (i INTERMAX) z ich nagłówkami w plikach okresu oraz wygląd, który tata nadaje Rejestrowi.

Wspólne dla Przygotowania pliku zbiorczego, Uporządkowania INTERMAX, Przebiegu rozliczeń, Wyceny w efenix i reguły
danych: każdy z nich pyta tu o nagłówek kolumny, a nie czyta go z czytnika Przygotowania.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class Column:
    """Kolumna przenoszona z Rejestru zleceń; nagłówek docelowy jest szukany we wzorcach.

    Pary różniące się zapisem są jawne; nagłówek Rejestru nigdy nie zastępuje
    nagłówka docelowego. ``register_header`` to zapis z nowego Rejestru taty;
    kolumna może mieć w Rejestrze drugi przyjmowany zapis ze starszej kopii.
    Nagłówki są porównywane bez względu na wielkość liter, więc zapis różniący
    się tylko nią (``adres``) nie jest osobną alternatywą.
    """

    register_header: str
    target_header: str
    alternative_register_headers: tuple[str, ...] = ()

    @property
    def register_headers(self) -> tuple[str, ...]:
        return (self.register_header, *self.alternative_register_headers)

    @property
    def label(self) -> str:
        """Nagłówek w komunikacie: wszystkie przyjmowane zapisy."""

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
"""Nagłówki docelowe obu plików okresu, pod którymi stają komórki wiersza Rejestru."""

ORDERED_FONT: Final = "Calibri"
ORDERED_SIZE: Final = 8
"""Krój i rozmiar czcionki uporządkowanego wiersza: Uporządkowanie INTERMAX nadaje go kolumnom zlecenia, a rozpoznanie
Surowych zleceń po nim poznaje wiersz uporządkowany."""
WORKER_SIZE: Final = 9
"""Rozmiar pogrubionej czcionki ``WYKONAWCA`` uporządkowanego wiersza (tata pisze tę kolumnę Calibri 9)."""
DAY_FILL: Final = "FFFF00"
"""Żółte wypełnienie wiersza, którym tata oddziela dni w arkuszu zleceń (RGB)."""
