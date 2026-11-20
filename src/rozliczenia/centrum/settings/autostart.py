from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rozliczenia.centrum.platform import Autostart
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldPath, FieldProblem, KeyChange, SettingsFile

AUTOSTART_SETTING: Final = "autostart"
KEY: Final = "narzedzie.autostart"
ON: Final = "wlaczony"
OFF: Final = "wylaczony"


@dataclass(frozen=True)
class Unsupported:
    ...


def parse(data: bytes | None) -> bool | FieldProblem:
    return data == ON.encode("ascii")


def dump(enabled: bool) -> bytes:
    return _state(enabled).encode("ascii")


def _state(enabled: bool) -> str:
    return ON if enabled else OFF


def diff(before: bool, after: bool) -> tuple[KeyChange, ...]:
    return () if before == after else (KeyChange(KEY, _state(before), _state(after)),)


def restore(enabled: bool, changes: tuple[KeyChange, ...]) -> bool:
    before = next((change.before for change in changes if change.key == KEY), None)
    return enabled if before is None else before == ON


def reported(change: KeyChange) -> str:
    return f"{change.key}: {_shown(change.before)} → {_shown(change.after)}"


def _shown(value: str | None) -> str:
    return "nie ustawiono" if value is None else value


AUTOSTART: Final = SettingsFile(
    name=AUTOSTART_SETTING, parse=parse, dump=dump, diff=diff, restore=restore, reported=reported, default=False
)


@dataclass(frozen=True)
class AutostartPlace:
    autostart: Autostart

    def unsupported(self) -> FieldProblem | None:
        try:
            state = self.autostart.state()
        except OSError:
            return None
        return FieldProblem(FieldPath(AUTOSTART_SETTING), messages.autostart_unsupported()) if state == "unsupported" else None

    def read(self) -> bytes | None | OSError:
        try:
            state = self.autostart.state()
        except OSError as failure:
            return failure
        return dump(state == "on")

    def write(self, data: bytes | None) -> None:
        if data == ON.encode("ascii"):
            self.autostart.enable()
        else:
            self.autostart.disable()
