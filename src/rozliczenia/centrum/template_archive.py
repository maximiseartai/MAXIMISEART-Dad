"""Wzorce taty w Archiwum Logów okresu (ADR 0025, „Wzorce w Archiwum Logów okresu”): Wzorzec, którym liczy Uruchomienie,
idzie tam obok pliku Logów tylko przez sprawdzenie reguły danych (``TemplateChecks.checked``), pod nazwą z SHA-256 swoich
bajtów (``asset_name``). Ta sama nazwa to więc te same bajty, a nowa wersja Wzorca to nowy plik, który Kolejka wysyłki
wysyła do Archiwum okresu raz (``outbox``).

Wzorzec to cały skoroszyt, którego nie da się zamaskować jak tekstu, więc sprawdzenie odmawia (``TemplateRefused``)
zamiast maskować, a Logi dostają uwagę z nazwą Wzorca i powodem, bez wartości. Tabela postaci:

| Postać | Przykład | Wynik |
|---|---|---|
| wartość (nie formuła) pod nagłówkiem zakazanej kolumny reguły danych (``client_data.forbidden_columns``) w każdym arkuszu | ``Kwiatowa 5`` w B18 pod ``ADRES`` w B17 | odmowa ``ADDRESS`` albo ``ORANGE`` |
| liczba pod takim nagłówkiem | ``123456789`` w I18 pod ``NUMER UMOWY/ZLECENIA ORANGE`` | odmowa ``ORANGE`` |
| wartość w kolumnie B albo I pod wierszem nagłówka Wzorca o układzie Pliku zbiorczego, także pod innym nagłówkiem (``workbook_files.FORBIDDEN_POSITIONS``) | ``Kwiatowa 5`` w B18 pod ``MIEJSCE`` | odmowa ``ADDRESS`` |
| formuła pod takim nagłówkiem, z wynikiem albo bez | ``=A18`` w B18 | przechodzi |
| tekst komórki, komentarza, pamięci łącza zewnętrznego, nazwy arkusza albo właściwości dokumentu z zakazaną wartością pamięci pracy Centrum | ``Kwiatowa 5`` w C3, gdy praca przeczytała ten ``ADRES`` | odmowa ``FORBIDDEN`` |
| taki tekst z telefonem albo ulicą (strażnik ``client_data.guarded`` by go zmienił) | ``tel. 600 123 456`` w C3 | odmowa ``FREE_TEXT`` |
| liczba komórki (nie formuły) albo pamięci łącza zewnętrznego z zakazaną wartością albo telefonem (``guarded_number``) | ``600123456`` w C3 | odmowa ``FORBIDDEN`` albo ``FREE_TEXT`` |
| część pakietu spoza ``_READ_PARTS`` i ``_STRUCTURE_PARTS`` | obraz ``xl/media/image1.png``, tabela przestawna | odmowa ``UNKNOWN_PART`` |
| plik, który nie jest pakietem zip, albo część z uszkodzonym XML | ``b"nie zip"`` | odmowa ``UNREADABLE`` |
| granica: wynik formuły, liczba i tekst | ``SUMA`` w AU18 | przechodzi bez sprawdzenia |
| granica: cel łącza zewnętrznego (ścieżka pliku), stawki z wiersza 14, ustawienia drukarki | | przechodzą (decyzja Maksa) |
| granica: wartość nad nagłówkiem zakazanej kolumny | ``Kwiatowa 5`` w B3 nad ``ADRES`` w B17 | tylko strażnik tekstu |

Skan arkuszy pakietu (setki tysięcy komórek Wzorca pliku zbiorczego) nie zależy od pamięci reguły danych, więc
``TemplateChecks`` robi go raz na wersję Wzorca (SHA-256) w pracy Centrum i zapamiętuje jego wynik z tekstami i liczbami,
które przy każdym następnym sprawdzeniu przechodzą przez strażnika z bieżącą pamięcią.

Wzorzec, który przeszedł, to ``ArchivedTemplate``: dają go tylko ``TemplateChecks.checked`` i, z pliku Kolejki wysyłki,
``from_queue`` (prawo właściciela ma ``outbox``), a plik kolejki bierze tylko jego dokładny typ (``outbox._queue_text``).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
import hashlib
import io
import re
import threading
from typing import Final, final
import zipfile
from xml.etree.ElementTree import Element, ParseError, iterparse
import zlib

from openpyxl.utils import column_index_from_string

from rozliczenia import collective_layout
from rozliczenia.client_data import (
    ForbiddenColumn,
    ForbiddenValues,
    Outgoing,
    WithoutSubclasses,
    forbidden_columns,
    guarded,
    guarded_number,
    tool,
)
from rozliczenia.text import normalize_text
from rozliczenia.tool_files import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, WORKER_TEMPLATE
from rozliczenia.workbook_files import FORBIDDEN_POSITIONS

ASSET_PREFIX: Final = "wzorzec-"
ASSET_SUFFIX: Final = ".xlsx"
_ASSET_NAME: Final = re.compile(rf"{ASSET_PREFIX}(?P<sha256>[0-9a-f]{{64}}){re.escape(ASSET_SUFFIX)}", re.ASCII)


def asset_name(sha256: str) -> str:
    """Nazwa pliku Wzorca o skrócie ``sha256`` w Archiwum Logów okresu."""

    return f"{ASSET_PREFIX}{sha256}{ASSET_SUFFIX}"


class Refusal(Enum):
    """Powód, dla którego Wzorzec nie idzie do Archiwum; ``value`` to jego opis w uwadze, bez wartości."""

    ADDRESS = f"wartość w kolumnie {ForbiddenColumn.ADDRESS.value}"
    ORANGE = f"wartość w kolumnie {ForbiddenColumn.ORANGE.value}"
    FORBIDDEN = "tekst albo liczba z zakazaną wartością z plików, które przeczytała ta praca Centrum"
    FREE_TEXT = "tekst albo liczba z numerem telefonu albo ulicą"
    UNKNOWN_PART = "część skoroszytu, której sprawdzenie nie zna (np. obraz albo tabela przestawna)"
    UNREADABLE = "skoroszytu nie da się odczytać"


_IN_COLUMN: Final = {ForbiddenColumn.ADDRESS: Refusal.ADDRESS, ForbiddenColumn.ORANGE: Refusal.ORANGE}


@dataclass(frozen=True)
class TemplateRefused:
    """Wzorzec ``file`` (nazwa w ``config``), którego sprawdzenie nie przepuściło do Archiwum, z powodem."""

    file: str
    reason: Refusal

    @property
    def note(self) -> str:
        """Uwaga techniczna w Logach (``RunLog.input_copy_notes``): nazwa Wzorca i powód, bez wartości."""

        return f"Reguła danych: {self.file} nie idzie do Archiwum Logów okresu: {self.reason.value}."


_CHECKED: Final = object()
"""Dowód, że Wzorzec przeszedł sprawdzenie (``TemplateChecks.checked``) albo wrócił z pliku kolejki (``from_queue``); poza
tym modułem ruff (``TID251``) odrzuca jego import i atrybut modułu."""

_NO_SUBCLASSES: Final = "Wzorzec do Archiwum nie ma podklas: daje go tylko TemplateChecks.checked."


@final
class ArchivedTemplate(metaclass=WithoutSubclasses, refusal=_NO_SUBCLASSES):
    """Wzorzec do Archiwum Logów okresu: nazwa w Archiwum (``asset_name``), nazwa Wzorca w ``config`` i bajty pliku.

    Konstruktor bez ``_CHECKED`` rzuca ``TypeError``, a wartość jest niezmienna i bez podklas, jak Logi po strażniku
    (``run_logs_guard.GuardedLogs``)."""

    __slots__ = ("__content", "__file", "__name")
    __name: Outgoing
    __file: Outgoing
    __content: bytes

    def __init__(self, name: Outgoing, file: Outgoing, content: bytes, proof: object) -> None:
        if proof is not _CHECKED:
            raise TypeError("Wzorzec do Archiwum daje tylko TemplateChecks.checked.")
        object.__setattr__(self, "_ArchivedTemplate__name", name)
        object.__setattr__(self, "_ArchivedTemplate__file", file)
        object.__setattr__(self, "_ArchivedTemplate__content", content)

    def __init_subclass__(cls, **kwargs: object) -> None:
        raise TypeError(_NO_SUBCLASSES)

    @property
    def name(self) -> Outgoing:
        return self.__name

    @property
    def file(self) -> Outgoing:
        return self.__file

    @property
    def content(self) -> bytes:
        return self.__content

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ArchivedTemplate) and self.__name == other.__name

    def __hash__(self) -> int:
        return hash(self.__name)

    def __repr__(self) -> str:
        return f"ArchivedTemplate({self.__name!r})"

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Wzorzec do Archiwum jest niezmienny.")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Wzorzec do Archiwum jest niezmienny.")


def from_queue(name: str, file: str, content: bytes) -> ArchivedTemplate:
    """Wzorzec z pliku Kolejki wysyłki, który zapisał tam Wzorzec po sprawdzeniu: ``ValueError``, gdy nazwa nie jest
    ``asset_name`` skrótu bajtów albo nazwa Wzorca nie jest nazwą z ``config`` (plik kolejki nieczytelny)."""

    if name != asset_name(hashlib.sha256(content).hexdigest()) or file not in _TEMPLATE_FILES:
        raise ValueError("Wzorzec w pliku kolejki nie ma nazwy ze skrótu swoich bajtów.")
    return ArchivedTemplate(tool(name), tool(file), content, _CHECKED)


_TEMPLATE_FILES: Final = frozenset(template.name for template in (INTERNAL_TEMPLATE, COLLECTIVE_TEMPLATE, WORKER_TEMPLATE))
"""Nazwy Wzorców w ``config`` (``tool_files``), jedyne nazwy Wzorca w uwadze i w etykiecie pliku w Archiwum."""

_COLLECTIVE_LAYOUT: Final = frozenset({COLLECTIVE_TEMPLATE.name, WORKER_TEMPLATE.name})
"""Wzorce z układem Pliku zbiorczego: kolumny reguły danych stoją w nich na stałym miejscu (``FORBIDDEN_POSITIONS``)."""


@dataclass(frozen=True)
class _Scan:
    """Wynik skanu pakietu Wzorca, który nie zależy od pamięci reguły danych: odmowa albo teksty i liczby, które
    sprawdza strażnik."""

    refusal: Refusal | None
    texts: tuple[str, ...] = ()
    numbers: tuple[float, ...] = ()


class TemplateChecks:
    """Sprawdzenie Wzorców jednej pracy Centrum z jej pamięcią reguły danych (``CentrumWork.forbidden``); skan pakietu
    raz na wersję Wzorca (docstring modułu), pod zamkiem, bo Logi powstają w wątkach Uruchomień."""

    def __init__(self, forbidden: ForbiddenValues) -> None:
        self._forbidden = forbidden
        self._scans: dict[str, _Scan] = {}
        self._lock = threading.Lock()

    def checked(self, file: str, content: bytes) -> ArchivedTemplate | TemplateRefused:
        """Wzorzec ``file`` (nazwa w ``config``, z niej układ) o bajtach ``content`` po tabeli postaci modułu."""

        if file not in _TEMPLATE_FILES:
            raise ValueError(f"{file} nie jest Wzorcem z config")
        sha256 = hashlib.sha256(content).hexdigest()
        with self._lock:
            scan = self._scans.get(sha256)
            if scan is None:
                scan = self._scans[sha256] = _scanned(content, collective=file in _COLLECTIVE_LAYOUT)
        refusal = scan.refusal or self._guarded(scan)
        if refusal is not None:
            return TemplateRefused(file, refusal)
        return ArchivedTemplate(tool(asset_name(sha256)), tool(file), content, _CHECKED)

    def _guarded(self, scan: _Scan) -> Refusal | None:
        for text in scan.texts:
            found = guarded(self._forbidden, text, "Wzorzec")
            if found.notes:
                return Refusal.FORBIDDEN
            if found.text != text:
                return Refusal.FREE_TEXT
        for number in scan.numbers:
            hit = guarded_number(self._forbidden, number, "Wzorzec")
            if hit is not None:
                return Refusal.FORBIDDEN if hit.notes else Refusal.FREE_TEXT
        return None


_MAIN: Final = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SHEET: Final = re.compile(r"xl/worksheets/sheet\d+\.xml")
_READ_PARTS: Final = (
    re.compile(r"xl/sharedStrings\.xml"),
    _SHEET,
    re.compile(r"xl/comments\d+\.xml|xl/comments/comment\d+\.xml"),
    re.compile(r"xl/externalLinks/externalLink\d+\.xml"),
    re.compile(r"xl/drawings/(?:vmlDrawing|commentsDrawing)\d+\.vml"),
    re.compile(r"xl/workbook\.xml"),
    re.compile(r"docProps/(?:core|app|custom)\.xml"),
)
"""Części pakietu z tekstem albo liczbami, które sprawdzenie czyta; każdy ich tekst przechodzi przez strażnika. Komentarze
i ich rysunek mają nazwy, które daje Excel (``xl/comments1.xml``), i nazwy, które daje openpyxl
(``xl/comments/comment1.xml``)."""
_STRUCTURE_PARTS: Final = (
    re.compile(r"\[Content_Types\]\.xml"),
    re.compile(r"(?:.+/)?_rels/[^/]*\.rels"),
    re.compile(r"xl/theme/theme\d+\.xml"),
    re.compile(r"xl/styles\.xml"),
    re.compile(r"xl/calcChain\.xml"),
    re.compile(r"xl/printerSettings/printerSettings\d+\.bin"),
)
"""Części pakietu bez treści taty (układ, style, kolejność przeliczania, ustawienia drukarki, relacje); relacje niosą cel
łącza zewnętrznego, który idzie razem z Wzorcem (decyzja Maksa)."""


def _scanned(content: bytes, *, collective: bool) -> _Scan:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            names = package.namelist()
            if any(not _known(name) for name in names):
                return _Scan(Refusal.UNKNOWN_PART)
            shared = _shared_strings(package) if "xl/sharedStrings.xml" in names else ()
            texts: list[str] = list(shared)
            numbers: list[float] = []
            for name in names:
                if _SHEET.fullmatch(name):
                    refusal = _sheet(package, name, shared, texts, numbers, collective=collective)
                    if refusal is not None:
                        return _Scan(refusal)
                elif name.startswith("xl/externalLinks/"):
                    _external(package, name, texts, numbers)
                elif name != "xl/sharedStrings.xml" and any(part.fullmatch(name) for part in _READ_PARTS):
                    texts += _all_text(package, name)
    except _UNREADABLE:
        return _Scan(Refusal.UNREADABLE)
    return _Scan(None, tuple(dict.fromkeys(text for text in texts if text)), tuple(dict.fromkeys(numbers)))


_UNREADABLE: Final = (
    zipfile.BadZipFile,
    zlib.error,
    ParseError,
    KeyError,
    IndexError,
    ValueError,
    EOFError,
    NotImplementedError,
    RuntimeError,
)
"""Błędy odczytu pakietu, który nie jest całym skoroszytem: nie zip, uszkodzona kompresja albo XML, odwołanie do
nieistniejącego tekstu wspólnego, kompresja albo szyfrowanie, którego ``zipfile`` nie zna."""


def _known(name: str) -> bool:
    return name.endswith("/") or any(part.fullmatch(name) for part in (*_READ_PARTS, *_STRUCTURE_PARTS))


def _elements(package: zipfile.ZipFile, name: str) -> Iterator[Element]:
    with package.open(name) as part:
        for _, element in iterparse(part):
            yield element


def _shared_strings(package: zipfile.ZipFile) -> tuple[str, ...]:
    found: list[str] = []
    for element in _elements(package, "xl/sharedStrings.xml"):
        if element.tag == f"{_MAIN}si":
            found.append(_text_of(element))
            element.clear()
    return tuple(found)


def _text_of(element: Element) -> str:
    return "".join(text.text or "" for text in element.iter(f"{_MAIN}t"))


def _all_text(package: zipfile.ZipFile, name: str) -> list[str]:
    """Każdy tekst i każda wartość atrybutu części ``name`` (komentarze, nazwy arkuszy, właściwości dokumentu)."""

    found: list[str] = []
    for element in _elements(package, name):
        found += [element.text or "", element.tail or "", *element.attrib.values()]
    return [text for text in found if text.strip()]


_CELL_REFERENCE: Final = re.compile(r"([A-Z]{1,3})([0-9]+)")


def _sheet(
    package: zipfile.ZipFile,
    name: str,
    shared: tuple[str, ...],
    texts: list[str],
    numbers: list[float],
    *,
    collective: bool,
) -> Refusal | None:
    """Arkusz ``name``: odmowa za wartość pod nagłówkiem zakazanej kolumny albo ``None``, a teksty i liczby komórek bez
    formuły do ``texts`` i ``numbers``. Komórki stoją w pliku wierszami od góry, więc nagłówek jest przed wierszami pod
    nim."""

    forbidden: dict[int, tuple[ForbiddenColumn, int]] = {}
    if collective:
        forbidden |= {column: (kind, collective_layout.HEADER_ROW) for kind, column in FORBIDDEN_POSITIONS}
    for element in _elements(package, name):
        if element.tag != f"{_MAIN}c":
            if element.tag == f"{_MAIN}row":
                element.clear()
            continue
        reference = _CELL_REFERENCE.fullmatch(element.get("r", ""))
        if reference is None:
            raise ValueError("komórka bez adresu")
        column, row = column_index_from_string(reference.group(1)), int(reference.group(2))
        value = _value(element, shared)
        element.clear()
        if value is None:
            continue
        under = forbidden.get(column)
        if under is not None and row > under[1]:
            return _IN_COLUMN[under[0]]
        if isinstance(value, str):
            texts.append(value)
            for kind, _ in forbidden_columns({normalize_text(value): column}):
                forbidden.setdefault(column, (kind, row))
        else:
            numbers.append(value)
    return None


def _value(cell: Element, shared: tuple[str, ...]) -> str | float | None:
    """Wartość komórki bez formuły (tekst albo liczba); ``None``: komórka pusta albo z formułą."""

    if cell.find(f"{_MAIN}f") is not None:
        return None
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        inline = cell.find(f"{_MAIN}is")
        return None if inline is None else _text_of(inline) or None
    stored = cell.find(f"{_MAIN}v")
    if stored is None or stored.text is None:
        return None
    match kind:
        case "s":
            return shared[int(stored.text)] or None
        case "n":
            return float(stored.text)
        case "b" | "e" | "str" | "d":
            return stored.text
        case _:
            raise ValueError("komórka nieznanego typu")


def _external(package: zipfile.ZipFile, name: str, texts: list[str], numbers: list[float]) -> None:
    """Pamięć łącza zewnętrznego: nazwy arkuszy i wartości komórek skoroszytu, do którego prowadzi łącze."""

    for element in _elements(package, name):
        if element.tag == f"{_MAIN}sheetName":
            texts.append(element.get("val", ""))
        elif element.tag == f"{_MAIN}cell":
            stored = element.find(f"{_MAIN}v")
            if stored is not None and stored.text:
                if element.get("t", "n") == "n":
                    numbers.append(float(stored.text))
                else:
                    texts.append(stored.text)
            element.clear()
