"""Wzorce taty w Archiwum Logów okresu (ADR 0025, „Wzorce w Archiwum Logów okresu”): Wzorzec, którym liczy Uruchomienie,
idzie tam obok pliku Logów tylko przez sprawdzenie reguły danych (``TemplateChecks.checked``), pod nazwą z SHA-256 swoich
bajtów (``asset_name``). Ta sama nazwa to więc te same bajty, a nowa wersja Wzorca to nowy plik, który Kolejka wysyłki
wysyła do Archiwum okresu raz (``outbox``).

Wzorzec to cały skoroszyt, którego nie da się zamaskować jak tekstu, więc sprawdzenie odmawia (``TemplateRefused``)
zamiast maskować, a Logi dostają uwagę z nazwą Wzorca i powodem, bez wartości. Każdy tekst i każda wartość atrybutu
każdej części XML pakietu przechodzi przez strażnika reguły danych (``client_data.guarded``, liczba komórki przez
``guarded_number``), a każda maska albo uwaga to odmowa; bez strażnika idzie tylko to, co Maks przepuścił (ADR 0025).
Tabela postaci:

| Postać | Przykład | Wynik |
|---|---|---|
| wartość (nie formuła) pod nagłówkiem zakazanej kolumny reguły danych (``client_data.forbidden_columns``) w każdym arkuszu | ``Kwiatowa 5`` w B18 pod ``ADRES`` w B17 | odmowa ``ADDRESS`` albo ``ORANGE`` |
| liczba pod takim nagłówkiem | ``123456789`` w I18 pod ``NUMER UMOWY/ZLECENIA ORANGE`` | odmowa ``ORANGE`` |
| wartość w kolumnie B albo I pod wierszem nagłówka Wzorca o układzie Pliku zbiorczego, także pod innym nagłówkiem (``workbook_files.FORBIDDEN_POSITIONS``) | ``Kwiatowa 5`` w B18 pod ``MIEJSCE`` | odmowa ``ADDRESS`` |
| formuła pod takim nagłówkiem, z wynikiem albo bez (jej tekst idzie przez strażnika jak każdy) | ``=A18`` w B18 | przechodzi |
| tekst z zakazaną wartością pamięci pracy Centrum w dowolnym miejscu XML: komórka, formuła, tekst wspólny (także na granicy przebiegów formatowania), komentarz, nagłówek i stopka wydruku (tak, jak je pokazuje Excel, ``_shown_header``), podpowiedź hiperłącza, cel relacji (``mailto:``), lista walidacji danych, nazwa arkusza, właściwości dokumentu, pamięć łącza zewnętrznego, każdy atrybut | ``=IF(A1="Kwiatowa 5",1,0)``, gdy praca przeczytała ten ``ADRES`` | odmowa ``FORBIDDEN`` |
| taki tekst z telefonem albo ulicą (strażnik ``client_data.guarded`` by go zmienił) | ``&Ctel. 600 123 456`` w stopce | odmowa ``FREE_TEXT`` |
| liczba komórki (także wynik formuły) albo pamięci łącza zewnętrznego z zakazaną wartością albo telefonem (``guarded_number``) | ``600123456`` w C3 | odmowa ``FORBIDDEN`` albo ``FREE_TEXT`` |
| nieznany kod nagłówka albo stopki wydruku | ``&Q`` | odmowa ``UNREADABLE`` |
| tekst za końcem elementu (ogon), także za granicą porcji pliku, którą czyta parser | ``</div>tel. 600 123 456`` w rysunku komentarza | odmowa jak tekst |
| komentarz XML albo instrukcja przetwarzania w części | ``<!-- tel. 600 123 456 -->`` | odmowa ``XML_EXTRA`` |
| część pakietu spoza ``_KNOWN_PARTS`` | obraz ``xl/media/image1.png``, tabela przestawna | odmowa ``UNKNOWN_PART`` |
| plik, który nie jest pakietem zip, albo część z uszkodzonym XML | ``b"nie zip"`` | odmowa ``UNREADABLE`` |
| wyjątek (decyzja Maksa): cel łącza zewnętrznego, ``Target`` relacji ``externalLinkPath`` w ``xl/externalLinks/_rels`` (``_allowed``) | ``file:///C:/Users/…/cennik.xlsx`` | przechodzi bez strażnika |
| wyjątek (decyzja Maksa): stawki z wiersza 14 wychodzą razem z Wzorcem | ``45,5`` w N14 | przechodzą przez strażnika liczby jak każda liczba |
| granica: ustawienia drukarki (część binarna ``_BINARY``) | ``xl/printerSettings/printerSettings1.bin`` | przechodzą nieczytane |
| granica: wartość nad nagłówkiem zakazanej kolumny | ``Kwiatowa 5`` w B3 nad ``ADRES`` w B17 | tylko strażnik tekstu |

Skan pakietu (setki tysięcy komórek i atrybutów Wzorca pliku zbiorczego) nie zależy od pamięci reguły danych, więc
``TemplateChecks`` robi go raz na wersję Wzorca (SHA-256) w pracy Centrum i zapamiętuje jego teksty i liczby, a
strażnik przechodzi je znowu tylko wtedy, gdy pamięć poznała nową wartość od poprzedniego sprawdzenia tej wersji.

Wzorzec, który przeszedł, to ``ArchivedTemplate``: dają go tylko ``TemplateChecks.checked`` i, z pliku Kolejki wysyłki,
``from_queue`` (prawo właściciela ma ``outbox``), a plik kolejki bierze tylko jego dokładny typ (``outbox._queue_text``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    remembered,
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
    XML_EXTRA = "komentarz XML albo instrukcja przetwarzania, których Excel nie zapisuje"
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
        """``_verdicts``: wynik strażnika dla wersji Wzorca i liczby wartości pamięci (``client_data.remembered``), przy
        której go policzył; pamięć tylko rośnie, więc ta sama liczba to ta sama pamięć, a strażnik nie przechodzi
        drugi raz setek tysięcy tekstów Wzorca pliku zbiorczego, gdy praca nie poznała nowej wartości."""

        self._forbidden = forbidden
        self._scans: dict[str, _Scan] = {}
        self._verdicts: dict[tuple[str, int], Refusal | None] = {}
        self._lock = threading.Lock()

    def checked(self, file: str, content: bytes) -> ArchivedTemplate | TemplateRefused:
        """Wzorzec ``file`` (nazwa w ``config``, z niej układ) o bajtach ``content`` po tabeli postaci modułu."""

        if file not in _TEMPLATE_FILES:
            raise ValueError(f"{file} nie jest Wzorcem z config")
        sha256 = hashlib.sha256(content).hexdigest()
        key = (sha256, remembered(self._forbidden))
        with self._lock:
            scan = self._scans.get(sha256)
            if scan is None:
                scan = self._scans[sha256] = _scanned(content, collective=file in _COLLECTIVE_LAYOUT)
            if key not in self._verdicts:
                self._verdicts[key] = scan.refusal or self._guarded(scan)
            refusal = self._verdicts[key]
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
_BINARY: Final = re.compile(r"xl/printerSettings/printerSettings\d+\.bin")
"""Jedyna część pakietu, której sprawdzenie nie czyta: ustawienia drukarki (struktura ``DEVMODE`` sterownika), bez
tekstu taty."""
_KNOWN_PARTS: Final = (
    re.compile(r"\[Content_Types\]\.xml"),
    re.compile(r"(?:.+/)?_rels/[^/]*\.rels"),
    re.compile(r"xl/workbook\.xml"),
    _SHEET,
    re.compile(r"xl/sharedStrings\.xml"),
    re.compile(r"xl/styles\.xml"),
    re.compile(r"xl/theme/theme\d+\.xml"),
    re.compile(r"xl/calcChain\.xml"),
    re.compile(r"xl/comments\d+\.xml|xl/comments/comment\d+\.xml"),
    re.compile(r"xl/drawings/(?:vmlDrawing|commentsDrawing)\d+\.vml"),
    re.compile(r"xl/externalLinks/externalLink\d+\.xml"),
    re.compile(r"docProps/(?:core|app|custom)\.xml"),
    _BINARY,
)
"""Części pakietu, które sprawdzenie zna; każda poza ``_BINARY`` to XML, którego każdy tekst i każda wartość atrybutu
przechodzi przez strażnika. Komentarze i ich rysunek mają nazwy, które daje Excel (``xl/comments1.xml``), i nazwy, które
daje openpyxl (``xl/comments/comment1.xml``)."""
_EXTERNAL_LINK_RELS: Final = re.compile(r"xl/externalLinks/_rels/externalLink\d+\.xml\.rels")
_EXTERNAL_LINK_PATH: Final = ("/externalLinkPath", "/xlPathMissing")
"""Typy relacji z celem łącza zewnętrznego (ścieżką skoroszytu, do którego prowadzi): jedyny tekst Wzorca, który idzie bez
strażnika (decyzja Maksa, ADR 0025)."""
_CELLS: Final = frozenset({"c", "cell"})
"""Komórka arkusza i komórka pamięci łącza zewnętrznego: liczba w jej ``<v>`` przechodzi przez strażnika liczby."""
_JOINED: Final = frozenset({"si", "is", "comment"})
"""Tekst złożony z kilku przebiegów formatowania (tekst wspólny, tekst w komórce, komentarz): strażnik dostaje go też
w całości, bo telefon albo wartość mogą stać na granicy dwóch przebiegów."""


@dataclass
class _Found:
    """Teksty i liczby pakietu do strażnika, każdy raz."""

    texts: set[str] = field(default_factory=set)
    numbers: set[float] = field(default_factory=set)

    def add(self, text: str | None) -> None:
        if text and text.strip():
            self.texts.add(text)


def _scanned(content: bytes, *, collective: bool) -> _Scan:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            names = package.namelist()
            if any(not _known(name) for name in names):
                return _Scan(Refusal.UNKNOWN_PART)
            shared = _shared_strings(package) if "xl/sharedStrings.xml" in names else ()
            found = _Found()
            for name in names:
                if name.endswith("/") or _BINARY.fullmatch(name):
                    continue
                columns = _Columns.of(collective=collective) if _SHEET.fullmatch(name) else None
                refusal = _part(package, name, shared, found, columns)
                if refusal is not None:
                    return _Scan(refusal)
    except _UNREADABLE:
        return _Scan(Refusal.UNREADABLE)
    return _Scan(None, tuple(sorted(found.texts)), tuple(sorted(found.numbers)))


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
    return name.endswith("/") or any(part.fullmatch(name) for part in _KNOWN_PARTS)


def _part(
    package: zipfile.ZipFile, name: str, shared: tuple[str, ...], found: _Found, columns: _Columns | None
) -> Refusal | None:
    """Część XML ``name``: każdy tekst (także ogon elementu) i każda wartość atrybutu do ``found``, liczba komórki do
    liczb, a w arkuszu (``columns``) odmowa za wartość w zakazanej kolumnie. Poza celem łącza zewnętrznego
    (``_allowed``) nic nie idzie bez strażnika. Komentarz XML i instrukcja przetwarzania to odmowa, bo Excel ich nie
    zapisuje, a ich tekstu drzewo elementów nie ma.

    Ogon dziecka (tekst za jego znacznikiem końca) parser przypisuje dopiero przy następnym znaczniku, czasem w następnej
    porcji pliku, więc ogony czyta koniec rodzica, gdy każdy jest już przypisany, a czyszczenie elementu ogon zostawia
    (``_cleared``). Element komórki i tekstu złożonego (``_CELLS``, ``_JOINED``) czyści się dopiero z nim, bo jego dzieci
    są potrzebne w całości."""

    held = 0
    cells: list[str] = []
    with package.open(name) as part:
        for event, element in iterparse(part, events=("start", "end", "comment", "pi")):
            if event in ("comment", "pi"):
                return Refusal.XML_EXTRA
            local = element.tag.rpartition("}")[2]
            if event == "start":
                cells += [element.get("t", "n")] if local in _CELLS else []
                held += local in _CELLS or local in _JOINED
                continue
            if local == "v" and cells and cells[-1] == "n" and element.text:
                found.numbers.add(float(element.text))
            else:
                found.add(element.text)
            for child in element:
                found.add(child.tail)
            for key, value in element.attrib.items():
                if not _allowed(name, element, key):
                    found.add(value)
            if local in _JOINED:
                found.add("".join(element.itertext()))
            if local in _HEADER_FOOTER and element.text:
                found.add(_shown_header(element.text))
            if local in _CELLS:
                cells.pop()
                refusal = None if columns is None or local != "c" else columns.refusal(element, shared)
                if refusal is not None:
                    return refusal
            held -= local in _CELLS or local in _JOINED
            if not held:
                _cleared(element)
    return None


def _cleared(element: Element) -> None:
    """``element`` bez dzieci, atrybutów i tekstu, z ogonem, który czyta koniec jego rodzica (``_part``)."""

    tail = element.tail
    element.clear()
    element.tail = tail


_HEADER_FOOTER: Final = frozenset({"oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter"})
_HEADER_CODE: Final = re.compile(
    r"&(?:(?P<amp>&)|(?P<part>[LCR])|(?P<field>[PN](?:[+-]\d+)?|[DTFAZG])|(?P<format>[BIUESXYOH]|K(?:[0-9A-Fa-f]{6}|\d{2}[+-]\d{3})|\"[^\"]*\"|\d+))"
)
"""Kod nagłówka i stopki wydruku Excela: ``&&`` to ``&``, część (``&L``, ``&C``, ``&R``) i pole (strona, data, plik,
arkusz, obraz) to osobny tekst, a formatowanie (pogrubienie, kolor, czcionka, rozmiar) niczego nie pokazuje."""


def _shown_header(text: str) -> str:
    """Nagłówek albo stopka wydruku tak, jak je pokazuje Excel: kod formatowania usunięty, część i pole jako koniec linii,
    bo kod sklejony ze słowem (``&LSyntetyczna``) ukryłby słowo przed strażnikiem; nieznany kod to ``ValueError``
    (pakiet nieczytelny), a nie tekst bez sprawdzenia."""

    shown: list[str] = []
    position = 0
    for code in _HEADER_CODE.finditer(text):
        shown.append(text[position : code.start()])
        shown.append("&" if code["amp"] else "" if code["format"] else "\n")
        position = code.end()
    rest = text[position:]
    if "&" in rest or any("&" in piece for piece in shown[::2]):
        raise ValueError("nieznany kod nagłówka wydruku")
    return "".join(shown) + rest


def _allowed(name: str, element: Element, key: str) -> bool:
    """Cel łącza zewnętrznego w relacjach pamięci łącza (``_EXTERNAL_LINK_PATH``): idzie bez strażnika."""

    return (
        key == "Target"
        and _EXTERNAL_LINK_RELS.fullmatch(name) is not None
        and element.get("Type", "").endswith(_EXTERNAL_LINK_PATH)
    )


def _shared_strings(package: zipfile.ZipFile) -> tuple[str, ...]:
    found: list[str] = []
    with package.open("xl/sharedStrings.xml") as part:
        for _, element in iterparse(part):
            if element.tag == f"{_MAIN}si":
                found.append(_text_of(element))
                element.clear()
    return tuple(found)


def _text_of(element: Element) -> str:
    return "".join(text.text or "" for text in element.iter(f"{_MAIN}t"))


_CELL_REFERENCE: Final = re.compile(r"([A-Z]{1,3})([0-9]+)")


@dataclass
class _Columns:
    """Zakazane kolumny jednego arkusza: numer kolumny → kolumna reguły danych i wiersz jej nagłówka. Komórki stoją w pliku
    wierszami od góry, więc nagłówek jest przed wierszami pod nim."""

    forbidden: dict[int, tuple[ForbiddenColumn, int]]

    @classmethod
    def of(cls, *, collective: bool) -> _Columns:
        positions = {column: (kind, collective_layout.HEADER_ROW) for kind, column in FORBIDDEN_POSITIONS}
        return cls(positions if collective else {})

    def refusal(self, cell: Element, shared: tuple[str, ...]) -> Refusal | None:
        """Odmowa za wartość komórki ``cell`` pod nagłówkiem zakazanej kolumny; nagłówek takiej kolumny zapamiętuje."""

        reference = _CELL_REFERENCE.fullmatch(cell.get("r", ""))
        if reference is None:
            raise ValueError("komórka bez adresu")
        column, row = column_index_from_string(reference.group(1)), int(reference.group(2))
        value = _value(cell, shared)
        if value is None:
            return None
        under = self.forbidden.get(column)
        if under is not None and row > under[1]:
            return _IN_COLUMN[under[0]]
        if isinstance(value, str):
            for kind, _ in forbidden_columns({normalize_text(value): column}):
                self.forbidden.setdefault(column, (kind, row))
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
