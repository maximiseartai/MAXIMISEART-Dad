from __future__ import annotations

import re

QUOTED = r"\\([\s\S])|'([^']*)'|\"([^\"\\]*(?:\\[\s\S][^\"\\]*)*)\""
_PART = re.compile(QUOTED)
_ESCAPED_IN_DOUBLE_QUOTES = re.compile(r"\\([\\\"\n$`])")


def unquoted(word: str) -> str:
    return _PART.sub(_part, word)


def _part(part: re.Match[str]) -> str:
    escaped, single, double = part.groups()
    if escaped is not None:
        return "" if escaped == "\n" else escaped
    if single is not None:
        return single
    return _ESCAPED_IN_DOUBLE_QUOTES.sub(_escaped, double)


def _escaped(escape: re.Match[str]) -> str:
    return "" if escape[1] == "\n" else escape[1]
