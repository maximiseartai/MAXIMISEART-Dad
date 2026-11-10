"""Wpisy raportu z treści Raportu wykonawcy tak, jak piszą Wykonawcy: wiele Wpisów w mailu, także w jednej linii,
``tak``/``nie`` w dowolnej wielkości liter i z interpunkcją, bez powitania, podpisu i cytatu w opisie."""

from __future__ import annotations

from collections.abc import Iterator, Sequence, Set
import itertools
import re
from typing import Final

from ._model import OrderNumber, ReportEntry, Verdict, VerdictFault

_EDGES: Final = re.compile(r"^(?:[^\w]|_)+|(?:[^\w]|_)+$")
_MARKS: Final[dict[str, Verdict | VerdictFault]] = {
    **{verdict.value: verdict for verdict in Verdict},
    "t": VerdictFault.LETTER,
    "n": VerdictFault.LETTER,
    "skuteczne": VerdictFault.WORD,
    "nieskuteczne": VerdictFault.WORD,
}
_CLOSINGS: Final = frozenset({"pozdrawiam", "pozdrowienia", "pozdr"})
_QUOTE_HEADER: Final = re.compile(
    r"(?:w dniu|on) .*(?:napisał\(a\)|napisał|napisała|wrote):"
    r"|-{2,} ?(?:original message|wiadomość oryginalna|forwarded message|wiadomość przekazana dalej) ?-{2,}"
    r"|(?:od|from): .*"
)
_SIGNATURE: Final = "-- "
"""Separator podpisu (RFC 3676): myślnik, myślnik, spacja."""
_DESCRIPTION_EDGES: Final = " ,;:-–—"


def entries(text: str, numbers: Set[OrderNumber]) -> tuple[ReportEntry, ...]:
    """Wpisy z treści; ``numbers`` to numery zleceń Wykonawcy z dnia z tematu.

    Treść czyta się linia po linii, bez linii cytatu ``>`` i bez wszystkiego od separatora podpisu ``-- `` albo
    nagłówka cytowanej wiadomości. Słowo z numerem (z ``#`` albo bez) zaczyna Wpis, gdy po nim stoi znak (``tak``,
    ``nie``, ``t``, ``n``, ``skuteczne``, ``nieskuteczne``, z interpunkcją, w dowolnej wielkości liter), a w linii nie
    zaczął się jeszcze żaden Wpis; dalej w linii tylko numer z ``numbers`` ze znakiem po nim. Numer z ``numbers`` na
    początku linii zaczyna Wpis także bez znaku. Opis to słowa do następnego Wpisu albo końca linii, ucięte na
    pożegnaniu, z pojedynczymi spacjami. W mailu liczy się pierwszy Wpis numeru, bo cytat stoi pod nową treścią.
    """

    found: dict[OrderNumber, ReportEntry] = {}
    for words in _lines(text):
        starts = _starts(words, numbers)
        bounds = [index for index, _ in starts] + [len(words)]
        for (start, number), end in zip(starts, bounds[1:], strict=True):
            found.setdefault(number, _entry(number, words[start + 1 : end]))
    return tuple(found.values())


def _lines(text: str) -> Iterator[list[str]]:
    for line in text.splitlines():
        stripped = line.strip()
        if line == _SIGNATURE or _QUOTE_HEADER.fullmatch(stripped.casefold()):
            return
        if not stripped.startswith(">"):
            yield stripped.split()


def _starts(words: Sequence[str], numbers: Set[OrderNumber]) -> list[tuple[int, OrderNumber]]:
    starts: list[tuple[int, OrderNumber]] = []
    for index, word in enumerate(words):
        number = _number(word)
        if number is None:
            continue
        marked = _mark(words[index + 1 :])[0] is not None
        if (index == 0 and number in numbers) or (marked and (not starts or number in numbers)):
            starts.append((index, number))
    return starts


def _entry(number: OrderNumber, words: Sequence[str]) -> ReportEntry:
    mark, rest = _mark(words)
    match mark:
        case Verdict():
            return ReportEntry(number, mark, None, _description(rest))
        case VerdictFault():
            return ReportEntry(number, None, mark, _description(rest))
        case None:
            return ReportEntry(number, None, VerdictFault.MISSING, _description(rest))


def _number(word: str) -> OrderNumber | None:
    core = _core(word)
    return OrderNumber(core) if core.isascii() and core.isdigit() else None


def _mark(words: Sequence[str]) -> tuple[Verdict | VerdictFault | None, Sequence[str]]:
    """Znak pierwszego słowa po numerze, które nie jest samą interpunkcją, i słowa po nim; bez znaku wszystkie słowa."""

    for index, word in enumerate(words):
        core = _core(word)
        if core:
            mark = _MARKS.get(core.casefold())
            return (mark, words[index + 1 :]) if mark is not None else (None, words)
    return None, words


def _description(words: Sequence[str]) -> str:
    kept = itertools.takewhile(lambda word: _core(word).casefold() not in _CLOSINGS, words)
    return " ".join(kept).strip(_DESCRIPTION_EDGES)


def _core(word: str) -> str:
    return _EDGES.sub("", word)
