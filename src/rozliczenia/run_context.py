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


def check_on_disk(template: TemplateFile) -> None:
    template.check()


class _Unasked:
    continue_hint = ""

    def confirm(self, decision: Decision) -> bool:
        return True


UNASKED: Conversation = _Unasked()


@dataclass(frozen=True, kw_only=True)
class RunContext:
    files: DadFiles = field(default_factory=DadFiles, compare=False)
    template_check: TemplateCheck = check_on_disk
    clock: RunClock = field(default_factory=RunClock, compare=False)
    observer: ProgressObserver | None = None
    conversation: Conversation = UNASKED

    def engaged(self, observer: ProgressObserver, conversation: Conversation) -> RunContext:
        return replace(self, observer=observer, conversation=conversation)


@dataclass(frozen=True)
class RunContexts:
    files: DadFiles = field(default_factory=DadFiles)
    template_check: TemplateCheck = check_on_disk

    def new(self) -> RunContext:
        return RunContext(files=self.files.for_run(), template_check=self.template_check)
