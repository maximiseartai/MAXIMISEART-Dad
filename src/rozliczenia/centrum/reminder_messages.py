from __future__ import annotations

from typing import Final

from rozliczenia.message import Message

_REMINDERS: Final = "Przypomnienia o raporcie"


def password_rejected() -> Message:
    return Message.to_maintainer(
        code="PRZYPOMNIENIA_HASLO_ODRZUCONE",
        what="Skrzynka raportów odrzuciła hasło, Maks musi je odnowić. Przypomnienia o raporcie nie poszły.",
        where=_REMINDERS,
    )
