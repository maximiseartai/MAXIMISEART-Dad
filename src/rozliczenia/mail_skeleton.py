"""Szkielet maila z Raportem wykonawcy: mail MIME bez treści załączników, z którego ``mail_of`` czyta to samo co z
całego maila, oraz rozbiór odpowiedzi ``FETCH`` serwera IMAP, z której port Skrzynki raportów go składa. Bez I/O.

Pełny mail Wykonawcy ma zdjęcia: 121 maili z dni od 2.11.2026 w skrzynce raportów taty to 214 MB, a ich ``UID FETCH
BODY.PEEK[]`` trwał na Macu 17–34 s i raz przekroczył limit czasu portu (pomiar 12.11.2026). Port bierze więc z
serwera ``BODYSTRUCTURE`` i nagłówek maila, a potem tylko części, które opisuje ``sections``: nagłówek każdej części
``multipart/*`` i ``text/*`` (``n.MIME``), treść każdej części ``text/*`` i nagłówek każdego dziecka
``multipart/related``. ``skeleton`` składa z nich mail MIME, w którym każda inna część ma sam nagłówek
``Content-Type: application/octet-stream`` bez treści.

``mail_of`` daje na szkielecie ten sam ``ReportMail`` co na całym mailu, bo czyta tylko nagłówek maila i treść części,
którą wybiera ``EmailMessage.get_body``, a ta patrzy tylko na nagłówki części ``multipart`` i ``text``, a w
``multipart/related`` także na ``Content-ID`` dzieci. Część, którą serwer opisuje w ``BODYSTRUCTURE`` jako inną niż
``TEXT``, nie jest dla ``get_body`` kandydatem na treść, więc jej nagłówek w szkielecie nie zmienia wyboru. Wyjątkiem
byłby nagłówek tak zepsuty, że serwer i pakiet ``email`` przypisują części różne typy; nagłówki, które szkielet ma od
serwera, ``skeleton`` porównuje z ``BODYSTRUCTURE`` i przy różnicy zwraca ``None``, a port pobiera wtedy cały mail.

``fetch_responses`` czyta odpowiedź ``FETCH`` w postaci, w której oddaje ją ``imaplib`` (linie i pary z literałem), tylko
w formach z RFC 3501: nawias, napis w cudzysłowie, literał, ``NIL`` i atom. Każda inna forma to ``UnknownReply``, a
``Structure.of`` daje ``None`` dla ``BODYSTRUCTURE`` w innym kształcie niż część albo ``multipart``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import email
from email.message import EmailMessage
import email.policy
from enum import Enum
import itertools
import re
from typing import Final

__all__ = ["FetchValue", "Structure", "UnknownReply", "chosen", "fetch_responses", "sections", "skeleton"]

FetchValue = bytes | None | list["FetchValue"]
"""Wartość z odpowiedzi ``FETCH``: napis albo literał (``bytes``), ``NIL`` (``None``) albo lista w nawiasie."""

_TOKEN: Final = re.compile(
    rb'[ ]*(?:(?P<open>\()|(?P<close>\))|"(?P<quoted>(?:[^"\\\r\n]|\\["\\])*)"|(?P<literal>\{\d+\})$'
    rb"|(?P<atom>[^\s()\"{\[\]]+(?:\[[^\]\r\n]*\](?:<\d+>)?)?))"
)
_NIL: Final = b"NIL"
_SYNTHETIC_PART: Final = b"Content-Type: application/octet-stream\r\n\r\n"


class UnknownReply(Exception):
    """Odpowiedź ``FETCH`` w formie spoza RFC 3501, której rozbiór nie zna."""


def fetch_responses(data: Sequence[object]) -> list[dict[bytes, FetchValue]]:
    """Każda odpowiedź ``FETCH`` z ``data`` (wynik ``imaplib``) jako słownik nazwa elementu (wielkimi literami) →
    wartość, w kolejności serwera. ``UnknownReply`` przy formie spoza RFC 3501 i odpowiedzi bez pary nazwa–wartość."""

    stack: list[list[FetchValue]] = [[]]
    found: list[dict[bytes, FetchValue]] = []
    for token in _tokens(data):
        if token is _Bracket.OPEN:
            stack.append([])
        elif token is _Bracket.CLOSE:
            if len(stack) == 1:
                raise UnknownReply
            closed = stack.pop()
            stack[-1].append(closed)
            if len(stack) == 1:
                found.append(_items(stack[0]))
                stack[0] = []
        else:
            stack[-1].append(token)
    if len(stack) != 1 or stack[0]:
        raise UnknownReply
    return found


class _Bracket(Enum):
    OPEN = "("
    CLOSE = ")"


def _tokens(data: Sequence[object]) -> Iterator[_Bracket | FetchValue]:
    for part in data:
        if part is None:
            continue
        if isinstance(part, bytes):
            line, literal = part, None
        elif isinstance(part, tuple) and len(part) == 2 and all(isinstance(piece, bytes) for piece in part):
            line, literal = part
        else:
            raise UnknownReply
        position, ends_with_literal = 0, False
        while position < len(line):
            found = _TOKEN.match(line, position)
            if found is None or found.end() == position:
                if line[position:].strip(b" \r\n"):
                    raise UnknownReply
                break
            position = found.end()
            if found["open"]:
                yield _Bracket.OPEN
            elif found["close"]:
                yield _Bracket.CLOSE
            elif found["quoted"] is not None:
                yield re.sub(rb"\\(.)", rb"\1", found["quoted"])
            elif found["literal"]:
                ends_with_literal = True
            else:
                atom = found["atom"]
                yield None if atom.upper() == _NIL else atom
        if ends_with_literal != (literal is not None):
            raise UnknownReply
        if literal is not None:
            yield literal


def _items(response: list[FetchValue]) -> dict[bytes, FetchValue]:
    """``<numer> (<nazwa> <wartość> …)`` jako słownik nazwa → wartość."""

    if len(response) != 2 or not isinstance(response[0], bytes) or not isinstance(response[1], list):
        raise UnknownReply
    items = response[1]
    if len(items) % 2 or not all(isinstance(name, bytes) for name in items[::2]):
        raise UnknownReply
    return {name.upper(): value for name, value in zip(items[::2], items[1::2], strict=True) if isinstance(name, bytes)}


@dataclass(frozen=True)
class Structure:
    """Część maila z ``BODYSTRUCTURE``: ``parts`` to dzieci części ``multipart`` (puste dla części bez dzieci),
    ``text`` mówi, czy serwer opisuje część jako ``TEXT``, ``plain``, czy jako ``TEXT/PLAIN``, a ``related``, czy to
    ``multipart/related``."""

    parts: tuple[Structure, ...] = ()
    text: bool = False
    plain: bool = False
    related: bool = False

    @property
    def multipart(self) -> bool:
        return bool(self.parts)

    @staticmethod
    def of(value: FetchValue) -> Structure | None:
        """Część z wartości ``BODYSTRUCTURE``; ``None`` dla każdego innego kształtu."""

        if not isinstance(value, list) or len(value) < 2:
            return None
        if isinstance(value[0], list):
            children = list(itertools.takewhile(lambda child: isinstance(child, list), value))
            subtype = value[len(children)] if len(children) < len(value) else None
            parts = tuple(Structure.of(child) for child in children)
            if not isinstance(subtype, bytes) or any(part is None for part in parts):
                return None
            return Structure(tuple(part for part in parts if part is not None), related=subtype.upper() == b"RELATED")
        if isinstance(value[0], bytes) and isinstance(value[1], bytes):
            text = value[0].upper() == b"TEXT"
            return Structure(text=text, plain=text and value[1].upper() == b"PLAIN")
        return None


def _leaves(structure: Structure) -> Iterator[Structure]:
    if not structure.multipart:
        yield structure
    for part in structure.parts:
        yield from _leaves(part)


def sections(structure: Structure) -> tuple[str, ...]:
    """Sekcje ``BODY[…]``, które szkielet bierze od serwera oprócz nagłówka maila, w stałej kolejności: ``TEXT`` dla
    maila z jedną częścią tekstu, a w ``multipart`` ``n.MIME`` każdej części ``multipart`` i ``text`` oraz każdego
    dziecka ``multipart/related``, i ``n`` każdej części ``text/plain``, a gdy mail jej nie ma, każdej części ``text``.

    Treść części ``text/html`` obok ``text/plain`` jest zbędna, gdy ``get_body`` wybiera tekst przed HTML, a każda treść
    to jedno pobranie po stronie Gmaila. Którą część ``get_body`` wybrał naprawdę, mówi ``chosen`` na szkielecie."""

    if not structure.multipart:
        return ("TEXT",) if structure.text else ()
    with_plain = any(leaf.plain for leaf in _leaves(structure))
    return tuple(_sections(structure, "", with_plain))


def _sections(structure: Structure, prefix: str, with_plain: bool) -> Iterator[str]:
    for number, part in enumerate(structure.parts, start=1):
        name = f"{prefix}{number}"
        if part.multipart or part.text or structure.related:
            yield f"{name}.MIME"
        if part.text and not part.multipart and (part.plain or not with_plain):
            yield name
        if part.multipart:
            yield from _sections(part, f"{name}.", with_plain)


def skeleton(structure: Structure, header: bytes, parts: Mapping[str, bytes]) -> bytes | None:
    """Mail MIME z nagłówka maila ``header`` i sekcji ``parts`` (``sections``), bez treści części innych niż tekst i
    części tekstu, której treści ``parts`` nie ma; ``None``, gdy nagłówek od serwera nie zgadza się z ``BODYSTRUCTURE``
    (typ, brak ``boundary``) albo brak nagłówka części."""

    try:
        return _part(structure, header, parts, "")
    except (KeyError, UnicodeEncodeError):
        return None


def _part(structure: Structure, header: bytes, parts: Mapping[str, bytes], name: str) -> bytes | None:
    head = header if header.endswith(b"\r\n\r\n") else header.rstrip(b"\r\n") + b"\r\n\r\n"
    message = email.message_from_bytes(head, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    maintype = message.get_content_maintype()
    if structure.multipart:
        boundary = message.get_boundary()
        if maintype != "multipart" or boundary is None:
            return None
        delimiter = b"--" + boundary.encode("ascii", "surrogateescape")
        body = b""
        for number, part in enumerate(structure.parts, start=1):
            child = f"{name}.{number}" if name else str(number)
            known = part.multipart or part.text or structure.related
            built = _part(part, parts[f"{child}.MIME"] if known else _SYNTHETIC_PART, parts, child)
            if built is None:
                return None
            body += delimiter + b"\r\n" + built + b"\r\n"
        return head + body + delimiter + b"--\r\n"
    if maintype == "multipart" or (maintype == "text") != structure.text:
        return None
    if not structure.text:
        return head
    return head + parts.get(name or "TEXT", b"")


def chosen(structure: Structure, raw: bytes, preference: tuple[str, ...]) -> str | None:
    """Sekcja części, którą ``get_body(preferencelist=preference)`` wybiera ze szkieletu ``raw`` złożonego z
    ``structure`` (``TEXT`` dla maila z jedną częścią), albo ``None``, gdy nie wybiera żadnej. Wybór czyta tylko nagłówki
    części, a te szkielet ma od serwera, więc to ta sama część co w całym mailu."""

    message = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    body = message.get_body(preferencelist=preference)
    if body is None:
        return None
    return next((name for part, name in _named(message, structure, "") if part is body), None)


def _named(message: EmailMessage, structure: Structure, name: str) -> Iterator[tuple[object, str]]:
    yield message, name or "TEXT"
    payload = message.get_payload() if structure.multipart else []
    if not isinstance(payload, list) or len(payload) != len(structure.parts):
        return
    for number, (part, child) in enumerate(zip(payload, structure.parts, strict=True), start=1):
        if isinstance(part, EmailMessage):
            yield from _named(part, child, f"{name}.{number}" if name else str(number))
