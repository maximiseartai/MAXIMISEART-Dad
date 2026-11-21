from __future__ import annotations

import re

QUOTED = r"\\([\s\S])|'([^']*)'|\"([^\"\\]*(?:\\[\s\S][^\"\\]*)*)\""
_PART = re.compile(QUOTED)
_ESCAPED_IN_DOUBLE_QUOTES = re.compile(r"\\([\\\"])")


def unquoted(word: str) -> str:
    return _PART.sub(_part, word)


def _part(part: re.Match[str]) -> str:
    escaped, single, double = part.groups()
    if escaped is not None:
        return escaped
    if single is not None:
        return single
    return _ESCAPED_IN_DOUBLE_QUOTES.sub(r"\1", double)
