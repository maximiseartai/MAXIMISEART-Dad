"""Komunikaty Przypomnień o raporcie (ADR 0030): katalog jedynego Komunikatu pracy przypomnień, z którego Centrum samo
zakłada Zgłoszenie do Maksa."""

from __future__ import annotations

from typing import Final

from rozliczenia.message import Message

_REMINDERS: Final = "Przypomnienia o raporcie"


def password_rejected() -> Message:
    """Gmail odrzucił hasło aplikacji przy pracy przypomnień: nowe hasło może dać tylko Maks (spec #1344, US 47)."""

    return Message.to_maintainer(
        code="PRZYPOMNIENIA_HASLO_ODRZUCONE",
        what="Skrzynka raportów odrzuciła hasło, Maks musi je odnowić. Przypomnienia o raporcie nie poszły.",
        where=_REMINDERS,
    )
