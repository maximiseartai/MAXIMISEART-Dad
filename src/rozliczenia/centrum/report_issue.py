from __future__ import annotations

from typing import Final

from rozliczenia.centrum.report_box import Label

LABEL: Final[Label] = "zgloszenie"
_FINGERPRINT_PREFIX: Final = "- Odcisk problemu: "
RETURNED_HEADING: Final = "## Zgłoszenie wróciło\n\n"


def fingerprint_line(fingerprint: str) -> str:
    return f"{_FINGERPRINT_PREFIX}{fingerprint}"


def fingerprint_of(line: str) -> str | None:
    fingerprint = line.removeprefix(_FINGERPRINT_PREFIX)
    return fingerprint if fingerprint != line else None
