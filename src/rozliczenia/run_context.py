"""Kontekst Uruchomienia: to, co gospodarz daje silnikowi każdego procesu obok jego wejścia."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from .dad_files import DadFiles
from .decision import Conversation, Decision
from .domain import ProgressObserver
from .run_clock import RunClock

if TYPE_CHECKING:
    from .template_file import TemplateFile

TemplateCheck = Callable[["TemplateFile"], None]
"""Sprawdzanie Wzorca: ``WorkbookError``, gdy Wzorzec nie może posłużyć jako wzór. Ten sam dostają Uruchomienie procesu,
Diagnoza i Konfiguracja, więc usterka, którą podstawia test albo weryfikacja, trafia do wszystkich trzech."""


def check_on_disk(template: TemplateFile) -> None:
    """Sprawdzanie Wzorca na dysku taty (``TemplateFile.check``)."""

    template.check()


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
    folder Kopii INTERMAX) jest polem jego wejścia. ``files``: jedyna droga do bajtów i wartości plików taty (pamięć
    reguły danych zawsze, Kopia wejścia tylko w Uruchomieniu z Logami). ``template_check``: Sprawdzanie Wzorców.
    ``observer`` i ``conversation`` dokłada rdzeń tuż przed silnikiem (``process_run.run_process``); test silnika podaje
    je sam albo zostawia domyślne.
    """

    files: DadFiles = field(default_factory=DadFiles, compare=False)
    template_check: TemplateCheck = check_on_disk
    clock: RunClock = field(default_factory=RunClock, compare=False)
    observer: ProgressObserver | None = None
    conversation: Conversation = UNASKED

    def engaged(self, observer: ProgressObserver, conversation: Conversation) -> RunContext:
        return replace(self, observer=observer, conversation=conversation)


@dataclass(frozen=True)
class RunContexts:
    """Gospodarz Uruchomień z Logami: uchwyt plików taty i Sprawdzanie Wzorców jego pracy.

    ``new()`` daje kontekst jednego Uruchomienia z uchwytem ``DadFiles.for_run`` i nowym zegarem. Gospodarz bez Logów
    (Skrypt dla maszyn) bierze ``RunContext()`` bez Kopii.
    """

    files: DadFiles = field(default_factory=DadFiles)
    template_check: TemplateCheck = check_on_disk

    def new(self) -> RunContext:
        return RunContext(files=self.files.for_run(), template_check=self.template_check)
