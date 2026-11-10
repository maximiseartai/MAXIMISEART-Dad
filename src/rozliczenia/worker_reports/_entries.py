"""Wpisy raportu z treści Raportu wykonawcy tak, jak piszą Wykonawcy: wiele Wpisów w mailu, w jednej linii albo przez
kilka linii, ``tak``/``nie`` w dowolnej wielkości liter i z interpunkcją, bez powitania, podpisu i cytatu w opisie."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
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
_CLOSINGS: Final = (("pozdrawiam",), ("pozdrowienia",), ("pozdr",), ("dziękuję",), ("z", "poważaniem"))
_END: Final = re.compile(
    r"^[ \t]*(?:--"
    r"|(?:w dniu|on) .*(?:\n.*){0,2}?(?:napisał\(a\)|napisał|napisała|wrote):"
    r"|-{2,} ?(?:original message|wiadomość oryginalna|forwarded message|wiadomość przekazana dalej) ?-{2,}"
    r"|(?:od|from): .*"
    r")[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
"""Separator podpisu (``--`` z albo bez spacji, RFC 3676) albo nagłówek cytowanej wiadomości, także zawinięty."""
_FOOTER: Final = re.compile(r"(?:wysłane|wysłano) ze? .*|sent from .*|get outlook for .*", re.IGNORECASE)
_DESCRIPTION_EDGES: Final = " ,;:-–—"


@dataclass(frozen=True)
class _Word:
    text: str
    core: str
    """Słowo bez znaków niealfanumerycznych na brzegach."""
    first: bool
    """Pierwsze słowo swojej linii."""


_Stream = Sequence[_Word | None]
"""Słowa treści w kolejności; ``None`` to przerwa: linia cytatu ``>`` albo stopka (``Wysłane z iPhone'a``)."""


def entries(text: str, digits: int) -> tuple[ReportEntry, ...]:
    """Wpisy z treści; ``digits`` to liczba cyfr najkrótszego numeru zlecenia.

    Treść kończy separator podpisu ``--`` albo nagłówek cytowanej wiadomości, a koniec linii nie kończy ani Wpisu, ani
    opisu. Numer w kształcie numeru zlecenia (same cyfry ASCII, z ``#`` albo bez, co najmniej ``digits`` cyfr) zaczyna
    Wpis, gdy po nim, także w następnej linii, stoi znak (``tak``, ``nie``, ``t``, ``n``, ``skuteczne``,
    ``nieskuteczne``, z interpunkcją, w dowolnej wielkości liter) albo gdy zaczyna linię. Krótsza liczba to słowo opisu.
    Opis to słowa do następnego Wpisu, przerwy, pożegnania albo końca treści, z pojedynczymi spacjami, bez znacznika
    listy (``1.``, ``-``) na początku linii następnego Wpisu. Słowa przed pierwszym Wpisem i po przerwie albo pożegnaniu
    się nie liczą. W mailu liczy się pierwszy Wpis numeru, bo cytat stoi pod nową treścią.
    """

    stream = tuple(_stream(text))
    starts = [index for index in range(len(stream)) if _starts(stream, index, digits)]
    found: dict[OrderNumber, ReportEntry] = {}
    for position, start in enumerate(starts):
        end = _cut(stream, starts[position + 1]) if position + 1 < len(starts) else len(stream)
        number = OrderNumber(_word(stream, start).core)
        found.setdefault(number, _entry(number, stream[start + 1 : end]))
    return tuple(found.values())


def _stream(text: str) -> Iterator[_Word | None]:
    lines = "\n".join(text.splitlines())
    end = _END.search(lines)
    for line in lines[: None if end is None else end.start()].split("\n"):
        stripped = line.strip()
        if stripped.startswith(">") or _FOOTER.fullmatch(stripped):
            yield None
        else:
            yield from (_Word(word, _EDGES.sub("", word), index == 0) for index, word in enumerate(stripped.split()))


def _starts(stream: _Stream, index: int, digits: int) -> bool:
    word = stream[index]
    if word is None or not (word.core.isascii() and word.core.isdigit() and len(word.core) >= digits):
        return False
    return word.first or _mark(stream, index + 1)[0] is not None


def _cut(stream: _Stream, start: int) -> int:
    """Koniec opisu przed Wpisem ``start``: bez znacznika listy (sama interpunkcja albo liczba) na początku linii."""

    before = stream[start - 1]
    return start - 1 if before is not None and before.first and (not before.core or before.core.isdigit()) else start


def _word(stream: _Stream, index: int) -> _Word:
    word = stream[index]
    assert word is not None
    return word


def _entry(number: OrderNumber, words: _Stream) -> ReportEntry:
    mark, after = _mark(words, 0)
    match mark:
        case Verdict():
            return ReportEntry(number, mark, None, _description(words[after:]))
        case VerdictFault():
            return ReportEntry(number, None, mark, _description(words[after:]))
        case None:
            return ReportEntry(number, None, VerdictFault.MISSING, _description(words))


def _mark(words: _Stream, begin: int) -> tuple[Verdict | VerdictFault | None, int]:
    """Znak pierwszego słowa od ``begin``, które nie jest samą interpunkcją, przed przerwą, i miejsce po nim."""

    for index in range(begin, len(words)):
        word = words[index]
        if word is None:
            break
        if word.core:
            mark = _MARKS.get(word.core.casefold())
            return (mark, index + 1) if mark is not None else (None, begin)
    return None, begin


def _description(words: _Stream) -> str:
    kept: list[str] = []
    for index, word in enumerate(words):
        if word is None or _closing(words[index : index + 2]):
            break
        kept.append(word.text)
    return " ".join(kept).strip(_DESCRIPTION_EDGES)


def _closing(words: _Stream) -> bool:
    cores = tuple("" if word is None else word.core.casefold() for word in words)
    return any(cores[: len(closing)] == closing for closing in _CLOSINGS)
