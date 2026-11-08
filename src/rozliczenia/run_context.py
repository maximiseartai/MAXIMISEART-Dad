"""Kontekst Uruchomienia: to, co gospodarz daje silnikowi każdego procesu obok jego wejścia."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .dad_files import DadFiles
from .decision import Conversation, Decision
from .domain import ProgressObserver
from .input_checks import FILE_READERS, Readers
from .run_clock import RunClock


class _Unasked:
    """Silnik bez rozmówcy (test silnika, skrypt weryfikacji): o nic nie pyta, więc idzie dalej jak po zgodzie."""

    continue_hint = ""

    def confirm(self, decision: Decision) -> bool:
        return True


UNASKED: Conversation = _Unasked()


@dataclass(frozen=True, kw_only=True)
class RunContext:
    """Kontekst Uruchomienia: jedyny argument silnika poza jego wejściem.

    Niesie tylko to, co gospodarz daje każdemu Uruchomieniu każdego procesu; zależność jednego procesu (okno efenix,
    folder Kopii INTERMAX) jest polem jego wejścia. ``files``: jedyna droga do wartości plików taty (pamięć reguły
    danych zawsze, Kopia wejścia tylko w Uruchomieniu z Logami). ``readers``: Sprawdzanie Wzorców i Rejestru zleceń; test
    podstawia czytnik, który się psuje. ``clock``: zegar Uruchomienia z jedyną pauzą. ``observer`` i ``conversation``
    dokłada rdzeń tuż przed silnikiem (``process_run.run_process``); test silnika podaje je sam albo zostawia domyślne.
    """

    files: DadFiles = field(default_factory=DadFiles, compare=False)
    readers: Readers = FILE_READERS
    clock: RunClock = field(default_factory=RunClock, compare=False)
    observer: ProgressObserver | None = None
    conversation: Conversation = UNASKED

    def engaged(self, observer: ProgressObserver, conversation: Conversation) -> RunContext:
        """Ten kontekst z obserwatorem postępu i rozmową rdzenia (``process_run.EngineContext``)."""

        return replace(self, observer=observer, conversation=conversation)


@dataclass(frozen=True)
class RunContexts:
    """Gospodarz Uruchomień z Logami: uchwyt plików taty i czytniki jego pracy.

    ``new()`` daje kontekst jednego Uruchomienia: ten sam uchwyt (ta sama pamięć reguły danych pracy) z nową Kopią
    wejścia i nowy zegar. Gospodarz bez Logów (Skrypt dla maszyn) bierze ``RunContext()`` bez Kopii.
    """

    files: DadFiles = field(default_factory=DadFiles)
    readers: Readers = FILE_READERS

    def new(self) -> RunContext:
        return RunContext(files=self.files.for_run(), readers=self.readers)
