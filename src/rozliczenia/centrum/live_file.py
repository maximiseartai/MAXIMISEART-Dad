"""Plik zbiorczy na żywo dla stron Uzupełnienia (#419, ADR 0016): znacznik zapisu i ostatni dobry odczyt.

Przeglądarka co kilka sekund pyta o znacznik zapisu (``saved_version``), który daje ``stat`` bez otwierania
skoroszytu, a pełny widok pobiera dopiero po jego zmianie. Gdy odczyt się nie uda (synchronizacja OneDrive, zapis
Excela), ``LastGoodReads`` oddaje przez ``SHOWN_FAILING_AFTER_S`` ostatni dobry odczyt pliku z jego godziną, a dopiero
potem porażkę, którą strona pokazuje jako Komunikat. Ostatni dobry odczyt jest tylko w pamięci procesu Centrum i
zmienia tylko to, co strona pokazuje podczas porażki: źródłem stanu dalej jest zapisany Plik zbiorczy. Po podmianie
pliku (``forget_all``) odczyt starego pliku nie zastępuje porażki nowego.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import threading
from typing import Final, Generic, TypeVar

from rozliczenia.wall_clock import utc_now

SHOWN_FAILING_AFTER_S: Final = 60.0
RETRY_GAP_S: Final = 15.0
"""Strona ponawia nieudany odczyt co 3 s; dłuższa cisza znaczy, że nikt nie patrzył (ukryta karta, inna strona)."""

T = TypeVar("T")


def saved_version(path: Path) -> str | None:
    """Znacznik zapisu pliku: czas zmiany i rozmiar z ``stat``; ``None``, gdy pliku nie widać."""

    try:
        status = path.stat()
    except OSError:
        return None
    return f"{status.st_mtime_ns}-{status.st_size}"


@dataclass(frozen=True)
class GoodRead(Generic[T]):
    """Odczyt pliku w wersji ``version`` z ``read_at``; ``retrying``: późniejsze próby się nie udały."""

    value: T
    version: str | None
    read_at: datetime
    retrying: bool = False


@dataclass(frozen=True)
class Attempt:
    """Próba odczytu pliku: jego znacznik zapisu i chwila zegara Centrum (sekundy), obie sprzed odczytu."""

    version: str | None
    started: float


@dataclass(frozen=True)
class Failing(Generic[T]):
    """Nieudany odczyt: ``kept`` to ostatni dobry do pokazania zamiast porażki, ``None``: pora na Komunikat.

    ``new_cause``: przyczyny tej porażki nie ma w dzienniku od ostatniego dobrego odczytu, więc ma tam trafić.
    """

    kept: GoodRead[T] | None
    new_cause: bool


@dataclass(frozen=True)
class _Series:
    """Seria nieudanych prób odczytu pliku, w sekundach zegara Centrum.

    ``since``: początek pierwszej próby serii; ``ended``: koniec ostatniej; ``version``: znacznik zapisu sprzed ostatniej;
    ``message``: seria oddała już Komunikat; ``causes``: przyczyny w dzienniku od ostatniego dobrego odczytu.
    """

    since: float
    ended: float
    version: str | None
    message: bool
    causes: frozenset[str]

    def continues(self, attempt: Attempt) -> bool:
        return self.message or attempt.started - self.ended <= RETRY_GAP_S or attempt.version == self.version


@dataclass
class _File(Generic[T]):
    last: GoodRead[T] | None = None
    failing: _Series | None = None


class LastGoodReads(Generic[T]):
    """Ostatni dobry odczyt każdego pliku i seria nieudanych prób po nim, na zegarze ``clock`` w sekundach.

    Przejścia (porażka bez serii zaczyna nową):

    ======================  ==================================================  ==================================
    zdarzenie               warunek                                             seria po nim
    ======================  ==================================================  ==================================
    dobry odczyt            zawsze                                              brak; to jest ostatni dobry odczyt
    porażka                 seria oddała już Komunikat                          ta sama: po Komunikacie strona
                                                                                czyta tylko po zmianie znacznika
    porażka                 od końca ostatniej porażki do początku tej próby    ta sama: strona ponawia co 3 s
                            najwyżej ``RETRY_GAP_S``
    porażka                 znacznik zapisu taki sam jak przy ostatniej         ta sama: plik się nie zmienił
    porażka                 inaczej (cisza i zapis pliku, którego nikt nie      nowa, z przyczynami z dziennika
                            czytał: ukryta karta)                               poprzedniej
    ======================  ==================================================  ==================================

    Strona dostaje ostatni dobry odczyt, dopóki seria nie oddała Komunikatu i od jej początku minęło mniej niż
    ``SHOWN_FAILING_AFTER_S``; potem Komunikat. Do dziennika trafia przyczyna, której tam nie ma od ostatniego dobrego
    odczytu, więc trwała porażka oglądana zrywami to jeden wpis.
    """

    def __init__(self, *, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._files: dict[Path, _File[T]] = {}

    def attempt(self, path: Path) -> Attempt:
        return Attempt(saved_version(path), self._clock())

    def succeeded(self, path: Path, value: T, attempt: Attempt) -> GoodRead[T]:
        with self._lock:
            file = self._files.setdefault(path, _File())
            file.last = GoodRead(value, attempt.version, utc_now())
            file.failing = None
            return file.last

    def forget_all(self) -> None:
        """Pliki mogły zostać podmienione: bez ostatnich dobrych odczytów i serii, więc porażka to od razu Komunikat,
        a jej przyczyna trafia do dziennika od nowa."""

        with self._lock:
            self._files.clear()

    def failed(self, path: Path, attempt: Attempt, cause: str) -> Failing[T]:
        """Nieudana próba ``attempt`` odczytu ``path`` z przyczyną ``cause`` (kod Komunikatu) według przejść klasy."""

        with self._lock:
            file = self._files.setdefault(path, _File())
            now = self._clock()
            before = file.failing
            if before is not None and before.continues(attempt):
                since, causes = before.since, before.causes
            else:
                since, causes = attempt.started, before.causes if before is not None else frozenset()
            kept = None
            if file.last is not None and now - since < SHOWN_FAILING_AFTER_S:
                kept = replace(file.last, retrying=True)
            file.failing = _Series(since, now, attempt.version, message=kept is None, causes=causes | {cause})
            return Failing(kept, cause not in causes)
