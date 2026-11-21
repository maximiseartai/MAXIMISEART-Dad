from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

DadFile = Literal["order_register", "collective_file"]

SettingsSection = Literal["wykonawcy"]

_MAINTAINER: Final = "osobie utrzymującej narzędzie"
KEEP_ON_DEVICE: Final = (
    "W Eksploratorze plików kliknij ten plik prawym przyciskiem myszy, wybierz „Zawsze zachowuj na tym urządzeniu”, "
    "poczekaj, aż się pobierze,"
)


def explorer_check(folder: str, then: str, *, read_only: bool = False) -> str:
    writable = ", nie jest tylko do odczytu" if read_only else ""
    return f"Sprawdź, czy {folder} otwiera się w Eksploratorze plików{writable} i czy OneDrive działa, potem {then}."


@dataclass(frozen=True)
class Message:
    code: str
    what: str
    where: str
    action: str
    dad_file: DadFile | None = None
    setting: SettingsSection | None = None
    reports_to_maintainer: bool = field(default=False, kw_only=True)

    @classmethod
    def to_maintainer(cls, code: str, what: str, where: str, *, before: str = "", check: str = "") -> Message:
        refer = f"Sprawdź {check} i przekaż" if check else "Przekaż"
        action = f"{refer} ten komunikat {_MAINTAINER}."
        return cls(code, what, where, f"{before} {action}" if before else action, reports_to_maintainer=True)

    @property
    def text(self) -> str:
        return f"Co się stało: {self.what}\nGdzie: {self.where}\nCo zrobić: {self.action}"


def refer_if(condition: str, *, request: str = "przekaż ten komunikat", then: str = "") -> str:
    return f"{condition}, {request} {_MAINTAINER}{then}."


IF_ERROR_RETURNS: Final = refer_if("Jeśli błąd wraca")
OTHERWISE_REFER: Final = f"W innym wypadku przekaż ten komunikat {_MAINTAINER}."


class StopError(Exception):
    def __init__(self, message: Message, *, facts: object = None) -> None:
        super().__init__(message.code)
        self.message = message
        self.facts = facts


def file_label(path: Path) -> str:
    return f"plik {path.name}, folder {path.parent.name}" if path.parent.name else f"plik {path.name}"


def folder_label(directory: Path) -> str:
    return f"folder {directory.parent.name}\\{directory.name}" if directory.parent.name else f"folder {directory.name}"
