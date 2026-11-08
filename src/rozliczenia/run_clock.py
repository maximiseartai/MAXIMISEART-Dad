"""Zegar jednego Uruchomienia procesu: jedyna pauza Uruchomienia."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class RunClock:
    """Zegar Uruchomienia w sekundach bez czasu czekania na tatę.

    W trakcie ``hold()`` ``now()`` stoi i po wyjściu rusza od tej samej wartości; zagnieżdżone ``hold()`` liczy się raz.
    Rdzeń (``Czas uruchomienia``), sekwencer etapów (czasy etapów, ``elapsed_ms`` Zdarzeń przebiegu) i ślad zleceń
    efenix czytają ten sam zegar, więc jedno ``hold()`` (Decyzja taty, czekanie na logowanie w efenix) wstrzymuje
    wszystkie naraz. ``raw``: zegar w sekundach, który biegnie także w czasie czekania.
    """

    def __init__(self, raw: Callable[[], float] = time.perf_counter) -> None:
        self._raw = raw
        self._held_s = 0.0
        self._held_at = 0.0
        self._holds = 0

    def now(self) -> float:
        """Czas surowy minus każde wstrzymanie; w trakcie ``hold()`` chwila jego początku."""

        return (self._held_at if self._holds else self._raw()) - self._held_s

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Zegar stoi do końca bloku."""

        if not self._holds:
            self._held_at = self._raw()
        self._holds += 1
        try:
            yield
        finally:
            self._holds -= 1
            if not self._holds:
                self._held_s += self._raw() - self._held_at
