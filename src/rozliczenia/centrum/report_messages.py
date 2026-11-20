from __future__ import annotations

from pathlib import Path

from rozliczenia.message import Message


def not_queued(queue: Path) -> Message:
    return Message(
        code="ZGLOSZENIE_NIEZAPISANE",
        what="Nie udało się zapisać Zgłoszenia na tym komputerze, więc nie pójdzie do Maksa.",
        where=f"folder {queue.name}",
        action="Kliknij „Spróbuj ponownie”. Jeśli to nie pomoże, rozwiń „Co zostanie wysłane”, skopiuj treść i "
        "prześlij ją Maksowi mailem.",
    )
