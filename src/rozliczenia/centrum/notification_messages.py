from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rozliczenia.message import Message


def unavailable(files: Sequence[Path]) -> Message:
    names = " i ".join(file.name for file in files)
    one = len(files) == 1
    return Message(
        code="POWIADOMIENIA_NIEZAPISANE",
        what="Centrum nie może teraz zapisać Powiadomień na tym komputerze, bo "
        + ("plik jest niedostępny." if one else "pliki są niedostępne."),
        where=f"{'plik' if one else 'pliki'} {names} w folderze {files[0].parent.name}",
        action="Nie zamykaj Centrum: pamięta zmiany i zapisze je samo. Zamknij program, który może trzymać "
        + ("ten plik" if one else "te pliki")
        + ", i otwórz Powiadomienia ponownie. Jeśli Komunikat zostaje, wyślij Uwagę do Maksa.",
    )
