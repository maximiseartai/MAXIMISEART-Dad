"""Zgłoszenie w Skrzynce Zgłoszeń (ADR 0007): etykieta, wiersz odcisku problemu i nagłówek „Zgłoszenie wróciło”.

Jeden problem ma jedno otwarte Zgłoszenie: Centrum znajduje je po wierszu odcisku w treści issue, a Zgłoszenie tego
samego odcisku, które przyjdzie, gdy tamto jest otwarte, idzie do niego komentarzem z nagłówkiem ``RETURNED_HEADING``.
Moduł leży pod ``keyed_box`` i ``dad_cases``, bo oba potrzebują etykiety, a ``dad_cases`` importuje ``keyed_box``.
"""

from __future__ import annotations

from typing import Final

from rozliczenia.centrum.report_box import Label

LABEL: Final[Label] = "zgloszenie"
_FINGERPRINT_PREFIX: Final = "- Odcisk problemu: "
RETURNED_HEADING: Final = "## Zgłoszenie wróciło\n\n"


def fingerprint_line(fingerprint: str) -> str:
    """Wiersz treści Zgłoszenia z odciskiem problemu, po którym Centrum znajduje otwarte Zgłoszenie w skrzynce."""

    return f"{_FINGERPRINT_PREFIX}{fingerprint}"


def fingerprint_of(line: str) -> str | None:
    """Odcisk problemu z wiersza ``fingerprint_line``; inny wiersz to ``None``."""

    fingerprint = line.removeprefix(_FINGERPRINT_PREFIX)
    return fingerprint if fingerprint != line else None
