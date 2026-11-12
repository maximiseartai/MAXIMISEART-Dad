"""Wpisy raportu z treści Raportu wykonawcy tak, jak piszą Wykonawcy: wiele Wpisów w mailu, w jednej linii albo przez
kilka linii, ``tak``/``nie`` w dowolnej wielkości liter i z interpunkcją, bez powitania, podpisu i cytatu w opisie.

Treść kończy pierwsza linia z ``_END`` (separator podpisu albo pierwsza linia cytatu), a numery z przykładu w
Przypomnieniu o raporcie nigdy nie są Wpisami. Opis Wpisu kończy jeden z wyliczonych znaczników: następny Wpis, pusta
linia, stopka (``Wysłane z …``, ``Sent from …``) w osobnej linii albo w środku ostatniej linii treści, pożegnanie z
``_CLOSINGS`` albo koniec treści. Tekst bez żadnego z nich tuż pod opisem (samo imię w następnej linii) należy do
opisu."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
import re
from typing import Final
import unicodedata

from ._model import OrderNumber, ReportEntry, Verdict, VerdictFault
from ._reminders import EXAMPLE_NUMBERS

_EDGES: Final = re.compile(r"^(?:[^\w]|_)+|(?:[^\w]|_)+$")
_MARKS: Final[dict[str, Verdict | VerdictFault]] = {
    **{verdict.value: verdict for verdict in Verdict},
    "t": VerdictFault.LETTER_YES,
    "n": VerdictFault.LETTER_NO,
    "skuteczne": VerdictFault.WORD_YES,
    "nieskuteczne": VerdictFault.WORD_NO,
}


def _fold(word: str) -> str:
    """Słowo małymi literami bez polskich znaków (``Dziękuję`` → ``dziekuje``), jak z telefonu bez polskiej klawiatury."""

    decomposed = unicodedata.normalize("NFKD", word.casefold().replace("ł", "l"))
    return "".join(letter for letter in decomposed if not unicodedata.combining(letter))


_CLOSINGS: Final = tuple(
    (tuple(_fold(word) for word in closing.split()), anywhere)
    for closing, anywhere in (
        ("pozdrawiam", True),
        ("pozdrowienia", True),
        ("pozdr", True),
        ("pzdr", True),
        ("pozdro", True),
        ("serdecznie pozdrawiam", True),
        ("dziękuję", True),
        ("dzięki", False),
        ("z poważaniem", True),
        ("miłego dnia", True),
        ("miłego wieczoru", True),
    )
)
"""Pożegnania, które kończą opis, bez względu na wielkość liter, polskie znaki i interpunkcję po nich (``Dziekuje!``,
``Pzdr.``). Pożegnanie na początku linii kończy opis zawsze. W środku linii bywa słowem opisu (``klient dziękuje za
szybką obsługę``), więc kończy go tylko wtedy, gdy do końca linii stoi po nim najwyżej ``_SIGNATURE`` słów podpisu
(``…, pozdrawiam Jan``); pożegnanie z ``False`` w środku linii nie kończy go nigdy (``wymiana dzięki drabinie``)."""
_SIGNATURE: Final = 2
"""Najwięcej słów podpisu (imię i nazwisko) po pożegnaniu w środku linii."""
_PREFIXES: Final = frozenset({"zlecenie", "zlec", "zl", "nr"})
"""Słowa przed numerem następnego Wpisu (``Zlecenie``, ``Zlec.``, ``Zl.``, ``Nr``), które nie należą do opisu."""
_END: Final = re.compile(
    r"^[ \t]*(?:--"
    r"|>.*"
    r"|(?:w dniu|on) .*(?:\n.*){0,2}?(?:napisał\(a\)|napisał|napisała|wrote):"
    r"|-{2,} ?(?:original message|wiadomość oryginalna|forwarded message|wiadomość przekazana dalej) ?-{2,}"
    r"|_{10,}"
    r"|(?:od|from): .*"
    r")[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
"""Linia, od której treść się nie liczy, bez względu na wielkość liter i białe znaki na brzegach linii, jedna z:

- separator podpisu ``--`` z albo bez spacji (RFC 3676);
- linia cytatu: zaczyna się od ``>``;
- nagłówek cytatu Gmaila ``W dniu … napisał(a):`` (także ``napisał:``, ``napisała:``) i ``On … wrote:``, rozbity
  najwyżej na trzy linie, jak Gmail zawija go przy długiej nazwie albo adresie;
- nagłówek przekazanej albo oryginalnej wiadomości między myślnikami (``---------- Forwarded message ---------``,
  ``-----Wiadomość oryginalna-----``);
- linia samych podkreślników, co najmniej 10, którą Outlook stawia nad nagłówkami cytatu;
- pierwsza linia nagłówków cytatu Outlooka ``Od: …`` albo ``From: …`` (po dwukropku spacja).

Inne postacie cytatu (``Wiadomość napisana przez … w dniu …:`` z Apple Mail po polsku, ``Od:`` bez spacji, cytat bez
żadnego znacznika) to granica: tekst cytatu czyta się jak treść, a fałszywego Wpisu z cytowanego przypomnienia nie
daje i tak, bo jedyne numery w nim to numery z przykładu."""
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
"""Słowa treści w kolejności; ``None`` to przerwa: pusta linia albo stopka (``Wysłane z iPhone'a``)."""


def entries(text: str, digits: int) -> tuple[ReportEntry, ...]:
    """Wpisy z treści; ``digits`` to liczba cyfr najkrótszego numeru zlecenia.

    Treść kończy pierwsza linia z ``_END`` (separator podpisu albo pierwsza linia cytatu), a koniec linii nie kończy ani
    Wpisu, ani opisu; pusta linia kończy jedno i drugie. Numer w kształcie numeru zlecenia (same cyfry ASCII, z ``#`` albo bez, co najmniej ``digits`` cyfr) zaczyna
    Wpis, gdy po nim, także w następnej linii, stoi znak (``tak``, ``nie``, ``t``, ``n``, ``skuteczne``,
    ``nieskuteczne``, z interpunkcją, w dowolnej wielkości liter) albo gdy zaczyna linię. Krótsza liczba to słowo opisu.
    Opis to słowa do następnego Wpisu, przerwy, pożegnania albo końca treści, z pojedynczymi spacjami, bez słowa
    z ``_PREFIXES`` tuż przed numerem następnego Wpisu i bez znacznika listy (``1.``, ``-``) na początku jego linii. Słowa przed pierwszym Wpisem i po przerwie albo pożegnaniu
    się nie liczą. Opis ostatniego Wpisu kończy też stopka w środku ostatniej linii treści (``_last_end``).

    Numer z przykładu w Przypomnieniu o raporcie (``EXAMPLE_NUMBERS``) zaczyna Wpis jak każdy inny, więc kończy opis
    Wpisu nad nim, ale jego Wpis wypada z wyniku: Wykonawca przepisał albo zacytował przykład bez znaku cytatu.

    Cytatu w treści już nie ma, więc kilka Wpisów jednego numeru Wykonawca napisał w nowej treści. Liczy się pierwszy
    Wpis z ``tak`` albo ``nie``, a Wpis bez nich tylko wtedy, gdy żaden Wpis numeru ich nie ma (pierwszy). Litera
    ``t``/``n`` i słowo ``skuteczne``/``nieskuteczne`` niosą zamiar (Decyzja Maksa D13, ``ReportEntry.leaning``): gdy
    Wpisy numeru mają przeciwny zamiar (``tak`` albo ``t`` albo ``skuteczne`` i ``nie`` albo ``n`` albo
    ``nieskuteczne``), wynik ma pierwszy Wpis każdego zamiaru, w kolejności maila, a dopasowanie nie wpisuje żadnego
    (``ConflictingVerdicts``).
    """

    stream = tuple(_stream(text))
    starts = [index for index in range(len(stream)) if _starts(stream, index, digits)]
    found: dict[OrderNumber, list[ReportEntry]] = {}
    for position, start in enumerate(starts):
        end = _cut(stream, starts[position + 1]) if position + 1 < len(starts) else _last_end(stream, start)
        number = OrderNumber(_word(stream, start).core)
        if number not in EXAMPLE_NUMBERS:
            found.setdefault(number, []).append(_entry(number, stream[start + 1 : end]))
    return tuple(entry for said in found.values() for entry in _counted(said))


def _counted(said: Sequence[ReportEntry]) -> tuple[ReportEntry, ...]:
    """Wpisy numeru, które się liczą: przy przeciwnym zamiarze pierwszy Wpis każdego zamiaru, inaczej pierwszy Wpis z
    ``tak``/``nie``, a bez nich pierwszy Wpis."""

    first: dict[Verdict, ReportEntry] = {}
    for entry in said:
        if entry.leaning is not None:
            first.setdefault(entry.leaning, entry)
    if len(first) > 1:
        return tuple(first.values())
    return next(((entry,) for entry in said if entry.verdict is not None), (said[0],))


def _last_end(stream: _Stream, start: int) -> int:
    """Koniec opisu ostatniego Wpisu ``start``: koniec treści, a gdy w środku ostatniej linii treści stoi stopka, która
    biegnie do końca tej linii (słowo, od którego reszta linii pasuje do ``_FOOTER``), pierwsze słowo stopki.

    Taką stopkę stawiają aplikacje pocztowe na końcu raportu pisanego w jednej linii. Słowa stopki, po których stoi
    kolejny Wpis albo tekst w tej linii lub pod nią, to opis, bo pod nimi nie ma już samych przerw."""

    last = start + 1
    while last < len(stream) and stream[last] is not None:
        last += 1
    if any(word is not None for word in stream[last:]):
        return len(stream)
    words = [_word(stream, index) for index in range(start + 1, last)]
    for index in range(len(words)):
        line = words[index:]
        if not any(word.first for word in line) and _FOOTER.fullmatch(" ".join(word.text for word in line)):
            return start + 1 + index
    return len(stream)


def _stream(text: str) -> Iterator[_Word | None]:
    lines = "\n".join(text.splitlines())
    end = _END.search(lines)
    for line in lines[: None if end is None else end.start()].split("\n"):
        stripped = line.strip()
        if not stripped or _FOOTER.fullmatch(stripped):
            yield None
        else:
            yield from (_Word(word, _EDGES.sub("", word), index == 0) for index, word in enumerate(stripped.split()))


def _starts(stream: _Stream, index: int, digits: int) -> bool:
    word = stream[index]
    if word is None or not (word.core.isascii() and word.core.isdigit() and len(word.core) >= digits):
        return False
    return word.first or _mark(stream, index + 1)[0] is not None


def _cut(stream: _Stream, start: int) -> int:
    """Koniec opisu przed Wpisem ``start``: bez słów z ``_PREFIXES`` tuż przed numerem i bez znacznika listy (sama
    interpunkcja albo liczba) na początku linii."""

    end = start
    while (prefix := stream[end - 1]) is not None and _fold(prefix.core) in _PREFIXES:
        end -= 1
    before = stream[end - 1]
    return end - 1 if before is not None and before.first and (not before.core or before.core.isdigit()) else end


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
        if word is None or _closing(words[index:]):
            break
        kept.append(word.text)
    return " ".join(kept).strip(_DESCRIPTION_EDGES)


def _closing(words: _Stream) -> bool:
    """Czy pożegnanie z ``_CLOSINGS`` na początku ``words`` kończy opis."""

    first = words[0] is not None and words[0].first
    for closing, anywhere in _CLOSINGS:
        folded = tuple("" if word is None else _fold(word.core) for word in words[: len(closing)])
        if folded == closing and (first or (anywhere and _line_rest(words[len(closing) :]) <= _SIGNATURE)):
            return True
    return False


def _line_rest(words: _Stream) -> int:
    """Liczba słów ``words`` do końca linii."""

    count = 0
    for word in words:
        if word is None or word.first:
            break
        count += 1
    return count
