"""Issue i komentarz Skrzynki Zgłoszeń tak, jak Maks je widzi na GitHubie.

GitHub nie pokazuje komentarzy HTML (``<!-- … -->``), więc niewidoczny znacznik wysyłki, który Kolejka wysyłki dopisuje
w osobnej linii każdego tekstu (``outbox._mark``), w widoku Maksa znika. Fałszywe skrzynki testów i weryfikacji trzymają
tekst tak, jak go zapisało Centrum, a testy i jazdy porównują widok Maksa.
"""

from __future__ import annotations

import re
from typing import Final

# Linia, którą GitHub przemilcza: sam komentarz HTML.
_HIDDEN_LINE: Final = re.compile(r"<!--.*-->")


def shown(text: str) -> str:
    """``text`` bez linii, które są samym komentarzem HTML."""

    return "\n".join(line for line in text.split("\n") if not _HIDDEN_LINE.fullmatch(line))
