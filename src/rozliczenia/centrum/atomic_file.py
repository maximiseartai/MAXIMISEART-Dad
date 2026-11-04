"""Atomowa zamiana pliku tekstowego Centrum: pliki stanu, Zgłoszenia, ich plik w kolejce i pliki kolejki Skrzynki.

Na Windows zamiana pliku, który ktoś na chwilę trzyma otwarty (antywirus, indeksowanie), kończy się
``PermissionError``, więc zamiana czeka i próbuje jeszcze raz (``RETRY_PAUSES_S``). Plik stanu (``StateFile``),
którego mimo to nie da się zapisać, pamięta treść i zapisuje ją przy następnej próbie.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Final

from rozliczenia.centrum.log import CentrumLog

# Przerwy przed kolejnymi próbami zamiany zablokowanego pliku: pięć prób w 0,75 s.
RETRY_PAUSES_S: Final = (0.05, 0.1, 0.2, 0.4)


def replace_atomically(
    path: Path,
    text: str,
    *,
    pause: Callable[[float], None] = time.sleep,
    pauses: Sequence[float] = RETRY_PAUSES_S,
    newline: str | None = None,
) -> None:
    """Zapisuje ``text`` w UTF-8 jako ``path`` przez plik tymczasowy w tym samym folderze.

    ``newline`` jak w ``Path.write_text``: ``None`` zapisuje każde ``\n`` jako koniec linii systemu (na Windows
    ``\r\n``), a ``""`` zapisuje znaki ``text`` bez zmiany, więc plik ma na każdym systemie te same bajty.

    Zamiana, której Windows odmawia (``PermissionError``), czeka ``pause`` kolejnej przerwy z ``pauses`` i próbuje
    ponownie; bez przerw jest jedna próba. Nieudany zapis (``OSError``) nie zostawia pustego ani urwanego pliku i nie
    niszczy poprzedniej treści.
    """

    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temporary.write_text(text, encoding="utf-8", newline=newline)
        for seconds in pauses:
            try:
                temporary.replace(path)
                return
            except PermissionError:
                pause(seconds)
        temporary.replace(path)
    except OSError:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise


class StateFile:
    """Plik stanu Centrum, którego nieudany zapis nie udaje zapisanego.

    Treść, której nie udało się zapisać, czeka w pamięci (``unavailable``), a ``retry`` albo następny ``write``
    zapisuje ją albo nowszą. Obie idą pod jedną blokadą, więc starsza treść nigdy nie zastąpi nowszej. Pierwsza
    porażka po udanym zapisie trafia do dziennika Centrum jako ``where``. Tylko ona ponawia zamianę z przerwami:
    każdy odczyt Powiadomień próbuje zapisu, więc przerwy przy dłuższej blokadzie spowalniałyby każdą stronę.
    """

    def __init__(self, path: Path, log: CentrumLog, *, where: str, pause: Callable[[float], None]) -> None:
        self.path = path
        self._log = log
        self._where = where
        self._pause = pause
        self._lock = threading.Lock()
        self._waiting: str | None = None

    @property
    def unavailable(self) -> bool:
        """Treść czeka na zapis, bo plik był niedostępny."""

        with self._lock:
            return self._waiting is not None

    def write(self, text: str) -> None:
        with self._lock:
            self._save(text)

    def retry(self) -> None:
        """Zapisuje treść, która czeka; bez niej nic nie robi."""

        with self._lock:
            if self._waiting is not None:
                self._save(self._waiting)

    def _save(self, text: str) -> None:
        try:
            pauses = RETRY_PAUSES_S if self._waiting is None else ()
            replace_atomically(self.path, text, pause=self._pause, pauses=pauses)
        except OSError as failure:
            if self._waiting is None:
                self._log.unexpected_failure(failure, where=self._where)
            self._waiting = text
        else:
            self._waiting = None
