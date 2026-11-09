"""Postęp Wyceny w efenix w trakcie Uruchomienia (#846): to, co ma jej dziennik na dysku (``logs_disk``), a pokazuje
komentarz Uruchomienia (``comment_versions.ProgressVersion``)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from rozliczenia.centrum.run_logs import LoggedOrder, StartFacts
from rozliczenia.efenix_pricing import OrderKind


@dataclass(frozen=True)
class OrderDone:
    """Zlecenie skończone w trakcie Wyceny w efenix, jak we wpisie dziennika „zlecenie skończone”: wiersz Pliku
    zbiorczego, wynik i kod Komunikatu zlecenia (``None`` przy gotowym, rozliczonym i przekazanym)."""

    row: int
    outcome: OrderKind
    code: str | None

    @classmethod
    def of(cls, order: LoggedOrder) -> OrderDone:
        return cls(order.row, order.outcome, order.code)


@dataclass(frozen=True)
class PricingProgress:
    """Postęp Wyceny w efenix w trakcie Uruchomienia (#846): to, co ma jej dziennik na dysku.

    ``done``: zlecenia skończone po kolei; ``total``: ile zleceń ma przebieg, z ostatniego wpisu „zaczynam zlecenie”
    (``None`` przed pierwszym, np. gdy okno efenix czeka na logowanie taty, albo gdy dziennika nie da się zapisać);
    ``current``: wiersz zlecenia zaczętego bez wyniku (``None`` między zleceniami).
    """

    started: StartFacts
    done: tuple[OrderDone, ...]
    total: int | None
    current: int | None

    def outcomes(self) -> tuple[tuple[OrderKind, int], ...]:
        counted = Counter(order.outcome for order in self.done)
        return tuple((kind, counted[kind]) for kind in OrderKind if counted[kind])
