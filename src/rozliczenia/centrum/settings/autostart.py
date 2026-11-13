"""Start Centrum razem z Windows: przełącznik w sekcji Narzędzie, którego stan to obecność skrótu Centrum w folderze
Autostart (port ``platform.Autostart``), a nie plik w ``config``.

Dla właściciela Ustawień stan skrótu to treść ``wlaczony`` albo ``wylaczony``, odczytana z portu przy każdym odczycie,
więc pamięć, wiersz Historii, zmiana spoza Centrum (skrót usunięty albo założony ręcznie), „Cofnij” i Zgłoszenie idą tą
samą drogą co plik Folderów. Stan nigdy nie jest brakiem pliku, więc wiersz spoza Centrum nie mówi o usuniętym pliku.
Komputer bez Autostartu Windows (``unsupported``) nie ma tego ustawienia: bez pamięci, bez wiersza, a zmiana jest
odmową z jednym zdaniem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from rozliczenia.centrum.platform import Autostart
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldPath, FieldProblem, KeyChange, SettingsFile

AUTOSTART_SETTING: Final = "autostart"
"""Nazwa ustawienia w Historii (pole ``plik``) i w pamięci właściciela, a także pole odmowy zmiany."""
KEY: Final = "narzedzie.autostart"
ON: Final = "wlaczony"
OFF: Final = "wylaczony"


@dataclass(frozen=True)
class Unsupported:
    """Ten komputer nie ma Autostartu Windows, więc przełącznika nie ma czym zmienić."""


def parse(data: bytes | None) -> bool | FieldProblem:
    """Stan skrótu z treści ``wlaczony``; każda inna treść (``wylaczony``, ``None`` pamięci bez stanu) to wyłączony."""

    return data == ON.encode("ascii")


def dump(enabled: bool) -> str:
    return ON if enabled else OFF


def diff(before: bool, after: bool) -> tuple[KeyChange, ...]:
    return () if before == after else (KeyChange(KEY, dump(before), dump(after)),)


def restore(enabled: bool, changes: tuple[KeyChange, ...]) -> bool:
    """Stan sprzed zmiany klucza przełącznika; inny klucz zostawia stan bez zmiany."""

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
    """Miejsce stanu przełącznika dla właściciela Ustawień: skrót w folderze Autostart zamiast pliku w ``config``."""

    autostart: Autostart

    def unsupported(self) -> FieldProblem | None:
        """Odmowa każdej zmiany na komputerze bez Autostartu Windows; ``None``: przełącznik działa (także przy folderze
        Autostart, którego nie da się teraz sprawdzić: o tym mówi odczyt)."""

        try:
            state = self.autostart.state()
        except OSError:
            return None
        return FieldProblem(FieldPath(AUTOSTART_SETTING), messages.autostart_unsupported()) if state == "unsupported" else None

    def read(self) -> bytes | None | OSError:
        """Stan skrótu jako treść ustawienia; ``OSError``, gdy folderu Autostart nie da się teraz sprawdzić."""

        try:
            state = self.autostart.state()
        except OSError as failure:
            return failure
        return dump(state == "on").encode("ascii")

    def write(self, data: bytes | None) -> None:
        """Zakłada skrót dla treści ``wlaczony``, a dla każdej innej go usuwa; ``OSError``, gdy się nie udało."""

        if data == ON.encode("ascii"):
            self.autostart.enable()
        else:
            self.autostart.disable()
