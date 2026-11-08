"""Części zip skoroszytu .xlsx: nawigacja po relacjach i wierszach arkusza, wspólne części ręcznych zapisów XML oraz
skoroszyt zawężony do potrzebnych wierszy.

Moduł czyta skoroszyt po częściach zip, bez openpyxl: ``relationships`` i
``sheet_part`` znajdują część po relacjach, ``active_sheet`` arkusz, który
openpyxl daje jako ``workbook.active``, a ``SheetData`` dzieli XML arkusza na
wiersze bez parsera. Ręczne zapisy XML skoroszytu biorą stąd dopisanie wpisów do
list ``xl/styles.xml`` (``appended``), ustawienie atrybutu stylu komórki z flagą
``applyX`` (``with_style_attribute``) i jeden wyjątek kształtu, którego nie
przenoszą (``UnsupportedShape``).

``SheetData`` przyjmuje tylko kształt, który zapisują Excel i openpyxl: jeden
``<sheetData>``, każdy wiersz i każda komórka z ``r`` jako pierwszym atrybutem,
wiersze rosnąco po numerze i bez komentarzy ani CDATA w danych arkusza. Inny
kształt to ``IrregularSheetData``: zawężanie zostawia wtedy arkusz w całości, a
``template_copy`` oddaje zapis openpyxl.

Plik zbiorczy ma ~10 tys. sformatowanych wierszy, a dane tylko w kilkuset;
Rejestr zleceń dziesiątki tysięcy wierszy od 2021 r., a okres kilkaset. openpyxl
czytałby każdą komórkę każdego wiersza. ``rows_with_input`` i
``rows_dated_between`` składają więc z bajtów skoroszytu taki sam skoroszyt
(części przepisane bez kompresji), w którego arkuszach zostają tylko potrzebne
wiersze i wiersze z formułą główną wspólnej formuły, bo openpyxl rozwija z niej
formuły zależne w dalszych wierszach. Wartości komórek dalej odczytuje openpyxl,
więc są takie same jak przy odczycie całego arkusza (typy, daty, teksty wspólne
i wbudowane, formuły). Pominięte wiersze nie są czytane przez openpyxl, więc XML
zawężanego arkusza jest najpierw sprawdzany parserem expat, żeby zepsuty arkusz
dalej był nieczytelny (``xml.parsers.expat.ExpatError``).

``rows_with_input`` (Wiersze danych Pliku zbiorczego) zostawia wiersze, które
mogą mieć dane w kolumnach danych wejściowych, i nagłówek. Pominięty wiersz nie
ma tam wartości: każda jego komórka w tych kolumnach jest pustym elementem
``<c …/>``, a openpyxl czyta taki wiersz tak samo jak brakujący.

``rows_dated_between`` (zlecenia okresu z Rejestru zleceń) zostawia wiersz 1 z
nagłówkami, z którego czytający rozpoznaje arkusze zleceń, i wiersze od pierwszego
do ostatniego z liczbą z przedziału w kolumnie daty. Kolumnę daty do zawężenia
czytający bierze z wiersza 1 czytanego bez openpyxl (``first_rows``), a sprawdza ją
na wierszu 1 zawężonego skoroszytu w openpyxl. openpyxl daje datę tylko z liczby
w komórce bez typu albo z ``t="n"`` (ze stylem daty), więc wiersz, którego data
leży w przedziale, ma w kolumnie daty liczbę z przedziału. Zakres od pierwszej do
ostatniej takiej liczby zawiera więc każdy taki wiersz i wszystkie wiersze między
nimi. Liczba bez stylu daty albo wartość zapamiętana przy formule może zakres
tylko poszerzyć. Arkusz z komórką daty typu ``d`` (data tekstem ISO, której
Excel nie zapisuje) albo z wartością liczbową, której nie da się przeczytać bez
parsera XML, zostaje w całości.

Tabela tekstów wspólnych Rejestru ma dziesiątki tysięcy tekstów, które openpyxl
parsowałby wszystkie, a zawężone arkusze sięgają do kilku tysięcy. Zawężony
skoroszyt ``rows_dated_between`` ma więc w tabeli tylko te teksty, bajt w bajt
i w kolejności z tabeli, a komórki arkuszy mają ich nowe numery. W kształcie,
którego to przepisanie nie zna, tabela i arkusze zostają bez zmian.
"""

from __future__ import annotations

import math
import posixpath
import re
import zipfile
from bisect import bisect_right
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import cached_property, lru_cache
from io import BytesIO
from itertools import islice, pairwise
from types import MappingProxyType
from typing import Any, Final, NamedTuple, NoReturn, cast
from xml.etree import ElementTree
from xml.parsers import expat

from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_to_tuple
from openpyxl.workbook.properties import WorkbookProperties

SPREADSHEET_NS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
MAIN: Final = f"{{{SPREADSHEET_NS}}}"
OFFICE_REL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"

_WITHOUT_LEADING_R: Final = re.compile(rb'<(?:c|row)(?=[\s>/])(?! r=")')
_ROW_START_OR_IRREGULAR: Final = re.compile(rb'<(?:row r="(\d+)"|!|(?:c|row)(?=[\s>/])(?! r="))')
_IRREGULAR_IN_ROW: Final = re.compile(rb"-->|\]\]>|</?sheetData")
"""Koniec komentarza albo CDATA zaczętego wyżej albo granica innego ``<sheetData>`` w wierszu ``RowsFromBottom``."""
_WORKSHEET: Final = re.compile(rb"\s*(?:<\?xml[^>]*\?>\s*)?<worksheet[\s>]")
_SHARED_FORMULA_MASTER: Final = re.compile(rb'<f\b[^>]*\bt="shared"[^>]*(?<!/)>')
_TYPE: Final = re.compile(rb"""\st=["']([^"']*)["']""")
_VALUE: Final = re.compile(rb"<v\b[^>]*>([^<]*)</v>")
_NUMBER_TYPES: Final = (None, b"n")
WORKSHEET_ROOT: Final = re.compile(rb"<((?:[\w.-]+:)?)worksheet\b[^>]*>")
"""Znacznik otwierający ``<worksheet>`` z deklaracjami przestrzeni nazw; grupa 1 to prefiks z dwukropkiem albo pusty."""
STYLE_XF: Final = re.compile(rb"<xf\b[^>]*?(?:/>|>.*?</xf>)", re.S)
"""Wpis ``<xf>`` listy stylów w ``xl/styles.xml``."""


class UnsupportedShape(Exception):
    """Skoroszyt ma kształt, którego ręczny zapis XML nie przenosi; ``str`` mówi który, bez treści pliku."""


# --- części i relacje --------------------------------------------------------------------------


@contextmanager
def package_parts(content: bytes) -> Iterator[Mapping[str, bytes]]:
    """Części skoroszytu ``content`` (.xlsx) po nazwie w zip; zepsuty zip zgłasza ``zipfile`` (np. ``BadZipFile``)."""

    with zipfile.ZipFile(BytesIO(content)) as archive:
        yield _ZipParts(archive)


# Przygotowanie czyta ten sam Rejestr zleceń w Sprawdzaniu (Surowe zlecenia, ``intermax_file.Register``) i w Odczycie
# danych (zawężenie): jego arkusz to dziesiątki MB XML, więc drugie rozpakowanie zip kosztuje tyle co reszta zawężenia.
@lru_cache(maxsize=1)
def unpacked(content: bytes) -> tuple[tuple[zipfile.ZipInfo, ...], Mapping[str, bytes]]:
    """Wpisy zip skoroszytu ``content`` (.xlsx) w kolejności z pliku i ich rozpakowane części po nazwie, tylko do odczytu;
    zepsuty zip zgłasza ``zipfile`` (np. ``BadZipFile``) albo ``zlib``."""

    with zipfile.ZipFile(BytesIO(content)) as archive:
        infos = tuple(archive.infolist())
        return infos, MappingProxyType({info.filename: archive.read(info) for info in infos})


class _ZipParts(Mapping[str, bytes]):
    """Części zip po nazwie, rozpakowane dopiero przy odczycie: arkusz Rejestru zleceń ma dziesiątki MB."""

    def __init__(self, archive: zipfile.ZipFile) -> None:
        self._archive = archive

    def __getitem__(self, name: str) -> bytes:
        return self._archive.read(name)

    def __contains__(self, name: object) -> bool:
        try:
            self._archive.getinfo(str(name))
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(self._archive.namelist())

    def __len__(self) -> int:
        return len(self._archive.infolist())


@dataclass(frozen=True)
class Relationship:
    """Relacja części: typ (``Type``) i cel, czyli ścieżka części w zip albo adres zewnętrzny."""

    kind: str
    target: str
    external: bool


def relationships_part(part: str) -> str:
    """Nazwa części z relacjami części ``part``."""

    folder, name = posixpath.split(part)
    return posixpath.join(folder, "_rels", f"{name}.rels")


def relationships(parts: Mapping[str, bytes], part: str) -> dict[str, Relationship]:
    """Relacje części ``part`` po identyfikatorze; bez części relacji żadnych."""

    rels = relationships_part(part)
    if rels not in parts:
        return {}
    folder = posixpath.dirname(part)
    found: dict[str, Relationship] = {}
    for relationship in ElementTree.fromstring(parts[rels]).iter(PACKAGE_REL):
        target = relationship.get("Target", "")
        external = relationship.get("TargetMode") == "External"
        if not external:
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        found[relationship.get("Id", "")] = Relationship(relationship.get("Type", ""), target, external)
    return found


def office_document(parts: Mapping[str, bytes]) -> str | None:
    """Część skoroszytu (``xl/workbook.xml``) według relacji paczki; ``None``, gdy żadna relacja jej nie wskazuje."""

    for relationship in ElementTree.fromstring(parts["_rels/.rels"]).iter(PACKAGE_REL):
        if relationship.get("Type", "").endswith("/officeDocument"):
            return relationship.get("Target", "").lstrip("/")
    return None


def sheet_part(parts: Mapping[str, bytes], title: str) -> str:
    """Część arkusza o nazwie ``title`` według ``workbook.xml`` i jego relacji; brak którejś to ``KeyError``."""

    workbook = office_document(parts) or ""
    sheets = ElementTree.fromstring(parts[workbook]).iter(f"{MAIN}sheet")
    identifier = next((sheet.get(f"{{{OFFICE_REL}}}id", "") for sheet in sheets if sheet.get("name") == title), "")
    return relationships(parts, workbook)[identifier].target


@dataclass(frozen=True)
class ActiveSheet:
    """Arkusz, który openpyxl daje jako ``workbook.active``, więc ten, który czytają czytniki skoroszytów."""

    part: str
    title: str
    position: int
    """Miejsce wśród ``<sheet>`` w ``workbook.xml``, od 0: tak liczy ``localSheetId`` nazw."""
    visible: bool
    worksheet: bool
    """Arkusz komórek, a nie arkusz wykresu."""


def active_sheet(parts: Mapping[str, bytes], workbook: str) -> ActiveSheet:
    """Arkusz ``workbook.active`` openpyxl w skoroszycie o częściach ``parts`` i części skoroszytu ``workbook``.

    openpyxl liczy ``activeTab`` pierwszego widoku skoroszytu (bez niego 0) wśród arkuszy, które wczytuje: ``<sheet>`` z
    ``r:id``, którego część jest w zip. Arkusz bez relacji (openpyxl nie wczyta skoroszytu) albo ``activeTab`` poza nimi
    (``workbook.active`` to ``None``) to ``UnsupportedShape``.
    """

    root = ElementTree.fromstring(parts[workbook])
    rels = relationships(parts, workbook)
    loaded: list[ActiveSheet] = []
    for position, sheet in enumerate(root.iterfind(f"{MAIN}sheets/{MAIN}sheet")):
        identifier = sheet.get(f"{{{OFFICE_REL}}}id")
        if not identifier:
            continue
        relationship = rels.get(identifier)
        if relationship is None:
            raise UnsupportedShape("aktywna karta")
        if relationship.target in parts:
            visible = sheet.get("state", "visible") == "visible"
            worksheet = relationship.kind.endswith("/worksheet")
            loaded.append(ActiveSheet(relationship.target, sheet.get("name", ""), position, visible, worksheet))
    view = root.find(f"{MAIN}bookViews/{MAIN}workbookView")
    try:
        return loaded[int(view.get("activeTab", "0")) if view is not None else 0]
    except (ValueError, IndexError):
        raise UnsupportedShape("aktywna karta") from None


# --- wiersz 1 bez openpyxl --------------------------------------------------------------------

_HEAD_CHUNK: Final = 16 * 1024
"""Porcja części czytana strumieniowo, taka jak w ``iterparse``, którym openpyxl parsuje arkusz."""


class FirstRows(NamedTuple):
    """Wiersz 1 każdego arkusza skoroszytu jako teksty komórek od kolumny A i system dat skoroszytu."""

    date1904: bool
    sheets: dict[str, list[str | None]]
    """Nazwa arkusza z ``workbook.xml`` → teksty wiersza 1 w kolejności arkuszy; arkusz bez wiersza 1 ma pustą listę."""


def first_rows(content: bytes) -> FirstRows:
    """Wiersz 1 każdego arkusza skoroszytu ``content`` (.xlsx) i jego system dat, bez openpyxl.

    Tekst ma tylko komórka bez formuły z tekstem wbudowanym, typu ``str`` albo z tekstem wspólnym o numerze z tabeli,
    taki, jaki daje openpyxl; każda inna komórka to ``None``. Arkusz i teksty wspólne są rozpakowywane i parsowane
    tylko do wiersza 1 i do ostatniego tekstu, do którego on sięga, a arkusz, którego części nie ma w zip, jest
    pominięty. Uszkodzenie zgłaszają ``zipfile``, ``zlib``, brak części ``KeyError`` albo parser (``ParseError``).
    """

    with zipfile.ZipFile(BytesIO(content)) as archive:
        parts = _ZipParts(archive)
        workbook = office_document(parts) or ""
        root = ElementTree.fromstring(parts[workbook])
        properties = root.find(f"{MAIN}workbookPr")
        settings = None if properties is None else cast(WorkbookProperties, WorkbookProperties.from_tree(cast(Any, properties)))
        date1904 = settings is not None and bool(settings.date1904)
        rels = relationships(parts, workbook)
        strings = next((rel.target for rel in rels.values() if rel.kind.endswith("/sharedStrings")), None)
        rows: dict[str, list[ElementTree.Element]] = {}
        for sheet in root.iterfind(f"{MAIN}sheets/{MAIN}sheet"):
            relationship = rels.get(sheet.get(f"{{{OFFICE_REL}}}id", ""))
            if relationship is not None and relationship.target in parts:
                row = next(_streamed(archive, relationship.target, f"{MAIN}row"), None)
                header = [] if row is None or row.get("r", "1") != "1" else list(row.iterfind(f"{MAIN}c"))
                rows[sheet.get("name", "")] = header
        needed = [index for cells in rows.values() for cell in cells if (index := _shared_index(cell)) is not None]
        shared = (
            [_text(item).replace("x005F_", "") for item in islice(_streamed(archive, strings, f"{MAIN}si"), max(needed) + 1)]
            if needed and strings is not None
            else []
        )
    return FirstRows(date1904, {title: _row_texts(cells, shared) for title, cells in rows.items()})


def _streamed(archive: zipfile.ZipFile, part: str, tag: str) -> Iterator[ElementTree.Element]:
    """Elementy ``tag`` części ``part`` po kolei, z części rozpakowywanej porcjami dopiero, gdy czytający po nie sięga."""

    parser = ElementTree.XMLPullParser(("end",))
    with archive.open(part) as stream:
        while chunk := stream.read(_HEAD_CHUNK):
            parser.feed(chunk)
            ends = cast(Iterator[tuple[str, ElementTree.Element]], parser.read_events())  # tylko zdarzenia "end"
            for _, element in ends:
                if element.tag == tag:
                    yield element


def _value(cell: ElementTree.Element) -> str | None:
    return cell.findtext(f"{MAIN}v") or None


def _shared_index(cell: ElementTree.Element) -> int | None:
    value = _value(cell)
    return int(value) if cell.get("t") == "s" and value is not None and value.isdecimal() else None


def _text(item: ElementTree.Element) -> str:
    """Tekst ``<si>`` albo ``<is>`` bez formatowania i podpowiedzi wymowy, jak ``openpyxl.cell.text.Text.content``."""

    blocks = (item.find(f"{MAIN}t"), *item.iterfind(f"{MAIN}r/{MAIN}t"))
    return "".join(block.text or "" for block in blocks if block is not None)


def _row_texts(cells: Sequence[ElementTree.Element], shared: Sequence[str]) -> list[str | None]:
    texts: dict[int, str | None] = {}
    column = 0
    for cell in cells:
        reference = cell.get("r")
        column = coordinate_to_tuple(reference)[1] if reference else column + 1
        kind, value, inline, index = cell.get("t", "n"), _value(cell), cell.find(f"{MAIN}is"), _shared_index(cell)
        if cell.find(f"{MAIN}f") is not None:
            texts[column] = None
        elif kind == "inlineStr":
            texts[column] = None if inline is None else _text(inline)
        elif index is not None:
            texts[column] = shared[index] if index < len(shared) else None
        else:
            texts[column] = value if kind == "str" else None
    return [texts.get(number) for number in range(1, max(texts, default=0) + 1)]


# --- style -------------------------------------------------------------------------------------


def style_list(xml: bytes, tag: bytes) -> re.Match[bytes]:
    """Pierwsza lista ``tag`` w ``xl/styles.xml``: atrybuty (grupa 1) i wpisy (grupa 2); brak to ``UnsupportedShape``."""

    found = re.search(rb"<" + tag + rb"\b([^>]*)>(.*?)</" + tag + rb">", xml, re.S)
    if found is None:
        raise UnsupportedShape(f"style: {tag.decode('ascii')}")
    return found


def appended(xml: bytes, tag: bytes, entries: Sequence[bytes], existing: int) -> bytes:
    """``xl/styles.xml`` z ``entries`` na końcu listy ``tag`` (``existing`` wpisów) i licznikiem ``count`` jako pierwszym
    atrybutem; bez wpisów ``xml`` bez zmian."""

    if not entries:
        return xml
    block = style_list(xml, tag)
    attributes = re.sub(rb'\scount="\d+"', b"", block.group(1))
    opening = b"<" + tag + b' count="%d"' % (existing + len(entries)) + attributes + b">"
    return xml[: block.start()] + opening + block.group(2) + b"".join(entries) + b"</" + tag + b">" + xml[block.end() :]


def with_style_attribute(xf: bytes, name: bytes, value: int, apply: bytes) -> bytes:
    """Wpis ``<xf>`` z atrybutem ``name`` równym ``value`` zaraz za nazwą elementu i flagą ``apply`` równą 1 na końcu
    znacznika otwierającego; dotychczasowe ``name`` i ``apply`` znikają, reszta atrybutów i elementy wewnątrz zostają."""

    tag_end = xf.index(b">")
    tag = re.sub(rb"\s" + name + rb'="\d+"', b"", xf[:tag_end])
    tag = re.sub(rb"\s" + apply + rb'="\w+"', b"", tag).rstrip(b"/ ")
    closing = b"/>" if xf[tag_end - 1 : tag_end] == b"/" else xf[tag_end:]
    return tag[:3] + b" " + name + b'="%d"' % value + tag[3:] + b" " + apply + b'="1"' + closing


# --- wiersze arkusza ---------------------------------------------------------------------------


class IrregularSheetData(Exception):
    """``<sheetData>`` spoza kształtu, który zapisują Excel i openpyxl."""


@dataclass(frozen=True)
class SheetRow:
    """Wiersz arkusza: numer i granice jego elementu ``<row>`` w XML arkusza."""

    number: int
    start: int
    end: int


@dataclass(frozen=True)
class SheetData:
    """Jedyny ``<sheetData>`` arkusza: treść od ``start`` (za ``<sheetData>``) do ``end`` (``</sheetData>``) i jej wiersze."""

    start: int
    end: int
    rows: list[SheetRow]
    """Wiersze ``<row>`` w kolejności z pliku."""

    @classmethod
    def of(cls, xml: bytes) -> SheetData:
        """``<sheetData>`` XML arkusza; kształt spoza tego, który zapisują Excel i openpyxl, to ``IrregularSheetData``."""

        start, end = _sheet_data_bounds(xml)
        return cls(start, end, _sheet_rows(xml, start, end))

    @cached_property
    def _starts(self) -> list[int]:
        return [row.start for row in self.rows]

    def row_index(self, position: int) -> int:
        """Indeks w ``rows`` ostatniego wiersza, który zaczyna się przed miejscem ``position``; -1 przed pierwszym."""

        return bisect_right(self._starts, position) - 1


def _sheet_data_bounds(xml: bytes) -> tuple[int, int]:
    """Treść jedynego ``<sheetData>``: od miejsca za ``<sheetData>`` do ``</sheetData>``; inaczej ``IrregularSheetData``."""

    start = xml.find(b"<sheetData>")
    end = xml.find(b"</sheetData>")
    if start < 0 or end < start or xml.count(b"<sheetData") != 1:
        raise IrregularSheetData("sheetData")
    return start + len(b"<sheetData>"), end


class RowsFromBottom:
    """Wiersze jedynego ``<sheetData>`` arkusza od ostatniego w górę, dzielone dopiero, gdy czytający po nie sięga.

    Dla zmiany dołu arkusza, który ma dziesiątki tysięcy wierszy (Rejestr zleceń): dzielenie całego ``SheetData``
    kosztuje tyle co reszta Uporządkowania INTERMAX. Kształt jest ten sam co w ``SheetData``, ale sprawdzany tylko w
    wierszach, które czytający dostał: każdy z nich i jego kolejność za wierszem nad nim, a komentarz albo CDATA także
    wtedy, gdy w nich się kończy, choć zaczął się wyżej, i granica drugiego ``<sheetData>`` w nich. Wierszy nad nimi
    czytający nie zna i ich bajtów nie zmienia.
    """

    def __init__(self, xml: bytes) -> None:
        start, end = xml.find(b"<sheetData>"), xml.rfind(b"</sheetData>")
        if start < 0 or end < start:
            raise IrregularSheetData("sheetData")
        self.xml = xml
        self.start, self.end = start + len(b"<sheetData>"), end
        self._rows: list[SheetRow] = []
        self._divided_from = self.end

    def __iter__(self) -> Iterator[SheetRow]:
        index = 0
        while index < len(self._rows) or self._divide_more():
            yield self._rows[index]
            index += 1

    def above(self, number: int) -> list[SheetRow]:
        """Wiersze o numerze większym niż ``number``, w kolejności z pliku."""

        rows: list[SheetRow] = []
        for row in self:
            if row.number <= number:
                break
            rows.append(row)
        return rows[::-1]

    def row(self, number: int) -> SheetRow:
        """Wiersz o numerze ``number``; ``KeyError``, gdy arkusz go nie ma."""

        for row in self:
            if row.number == number:
                return row
            if row.number < number:
                break
        raise KeyError(number)

    def _divide_more(self) -> bool:
        """Dzieli wiersz nad podzieloną już częścią; ``False``, gdy nad nią nie ma już wierszy."""

        end = self._divided_from
        if end <= self.start:
            return False
        begin = max(self.start, self.xml.rfind(b"<row", self.start, end))
        if _IRREGULAR_IN_ROW.search(self.xml, begin, end):
            raise IrregularSheetData("komentarz, CDATA albo drugi sheetData")
        rows = _sheet_rows(self.xml, begin, end)
        if self._rows and rows and rows[-1].number >= self._rows[-1].number:
            raise IrregularSheetData("kolejność wierszy")
        self._rows.extend(reversed(rows))
        self._divided_from = begin
        return bool(rows)


def _sheet_rows(xml: bytes, start: int, end: int) -> list[SheetRow]:
    # Jedno przejście po arkuszu (dziesiątki MB w Rejestrze zleceń) zamiast osobnego dla każdego warunku kształtu.
    rows: list[SheetRow] = []
    for match in _ROW_START_OR_IRREGULAR.finditer(xml, start, end):
        if match.group(1) is None:
            _raise_irregular(xml, start, end)
        number = int(match.group(1))
        if rows and number <= rows[-1].number:
            _raise_irregular(xml, start, end, "kolejność wierszy")
        tag_end = xml.index(b">", match.end())
        row_end = tag_end + 1 if xml[tag_end - 1 : tag_end] == b"/" else xml.index(b"</row>", tag_end) + len(b"</row>")
        rows.append(SheetRow(number, match.start(), row_end))
    return rows


def _raise_irregular(xml: bytes, start: int, end: int, otherwise: str = "") -> NoReturn:
    """Pierwszy niespełniony warunek kształtu w kolejności: komentarz albo CDATA, ``r`` jako pierwszy atrybut, ``otherwise``."""

    if xml.find(b"<!", start, end) >= 0:
        raise IrregularSheetData("komentarz albo CDATA")
    if _WITHOUT_LEADING_R.search(xml, start, end):
        raise IrregularSheetData("r")
    raise IrregularSheetData(otherwise)


# --- zawężanie ---------------------------------------------------------------------------------

_Narrow = Callable[[bytes], bytes]
"""Zawężenie XML arkusza; arkusz spoza kształtu, który zawężenie sprawdza, to ``IrregularSheetData``."""
_Choose = Callable[[str, bytes], _Narrow | None]
"""Zawężenie części zip o tej nazwie i treści; ``None``: część zostaje bez zmian."""


def rows_with_input(content: bytes, input_columns: int) -> bytes:
    """Skoroszyt ``content`` (.xlsx) z arkuszami zawężonymi do wierszy, które mogą mieć dane w kolumnach 1..``input_columns``.

    Pozostałe części są przepisane bez zmian. Uszkodzenie skoroszytu zgłaszają
    ``zipfile`` (np. ``BadZipFile``), ``zlib`` albo ``expat`` (``ExpatError``).
    """

    letters = b"|".join(get_column_letter(column).encode("ascii") for column in range(1, input_columns + 1))
    with_input = re.compile(rb'<c r="(?:' + letters + rb')[0-9]+"[^>]*(?<!/)>')

    def narrow(xml: bytes) -> bytes:
        sheet = SheetData.of(xml)
        cells = with_input.finditer(xml, sheet.start, sheet.end)
        return _with_rows(xml, sheet, {sheet.row_index(cell.start()) for cell in cells})

    def every_worksheet(_: Mapping[str, bytes]) -> _Choose:
        return lambda _, xml: narrow if _WORKSHEET.match(xml) else None

    return _rewritten(content, every_worksheet)


def rows_dated_between(
    content: bytes, date_columns: Mapping[str, int], low: float, high: float
) -> tuple[bytes, dict[str, range]]:
    """Skoroszyt ``content`` (.xlsx) z arkuszami ``date_columns`` (tytuł → kolumna daty od 1) zawężonymi do zakresu dat.

    Zakres arkusza to wiersze od pierwszego do ostatniego z liczbą z [``low``,
    ``high``] w kolumnie daty; zwracany jest dla każdego zawężonego arkusza (pusty,
    gdy żadna komórka daty nie ma takiej liczby), a zawężony arkusz ma też wiersz 1 i wiersze z formułą główną
    wspólnej formuły. Granice zakresu biorą się z komórek daty jego pierwszego i ostatniego wiersza, bez dzielenia
    całego arkusza na wiersze: arkusz Rejestru zleceń ma dziesiątki tysięcy wierszy, a okres to kilkaset na dole.
    Arkusz bez zwróconego zakresu
    zostaje w całości, tabela tekstów wspólnych ma tylko teksty komórek arkuszy (``_used_strings_only``), a
    pozostałe części są przepisane bez zmian. Uszkodzenie
    skoroszytu zgłaszają ``zipfile`` (np. ``BadZipFile``), ``zlib``, brak części
    ``KeyError`` albo ``expat`` (``ExpatError``).
    """

    ranges: dict[str, range] = {}
    days = b"|".join(b"%d" % day for day in range(math.floor(low) - 1, math.floor(high) + 1))
    # Komórka bez typu innego niż ``n`` z liczbą zapisaną samymi cyframi, której część całkowita jest spoza ``days``, ma
    # liczbę spoza [low, high] (``float`` zaokrągla ją najwyżej do części całkowitej plus 1), więc parser wyrażeń jej nie
    # oddaje: kolumna daty Rejestru zleceń ma dziesiątki tysięcy komórek, a ``_is_number_between`` sprawdza resztę.
    outside = rb"""(?:(?!\st=["'](?!n["']))[^>])*><v>(?!0*(?:""" + days + rb""")(?:\.\d+)?</v>)\d+(?:\.\d+)?</v>"""

    def dated(title: str, column: int) -> _Narrow:
        letter = get_column_letter(column).encode("ascii")
        date_cell = re.compile(rb'<c r="' + letter + rb'(\d+)"(?!' + outside + rb")([^>]*)(?<!/)>(.*?)</c>", re.DOTALL)

        def narrow(xml: bytes) -> bytes:
            start, end = _sheet_data_bounds(xml)
            dated = [
                (int(found.group(1)), found.start())
                for found in date_cell.finditer(xml, start, end)
                if _is_number_between(found.group(2), found.group(3), low, high)
            ]
            rows = _first_row(xml, start, end)
            kept = range(0)
            if dated:
                begin, finish = _window(xml, start, end, dated)
                rows |= {(begin, finish)} | _master_rows(xml, start, begin) | _master_rows(xml, finish, end)
                kept = range(min(dated)[0], max(dated)[0] + 1)
            ranges[title] = kept
            return b"".join([xml[:start], *(xml[begin:finish] for begin, finish in sorted(rows)), xml[end:]])

        return narrow

    def by_title(parts: Mapping[str, bytes]) -> _Choose:
        narrowing = {sheet_part(parts, title): dated(title, column) for title, column in date_columns.items()}
        return lambda name, _: narrowing.get(name)

    return _rewritten(content, by_title, used_strings_only=True), ranges


def _rewritten(content: bytes, choose: Callable[[Mapping[str, bytes]], _Choose], *, used_strings_only: bool = False) -> bytes:
    """Skoroszyt ``content`` przepisany bez kompresji, z częściami zawężonymi tak, jak wybiera ``choose`` z jego części.

    Arkusz spoza kształtu (``IrregularSheetData``) zostaje w całości. Z ``used_strings_only`` tabela tekstów wspólnych
    ma tylko teksty, do których sięgają komórki arkuszy po zawężeniu (``_used_strings_only``).
    """

    reduced = BytesIO()
    infos, unpacked_parts = unpacked(content)
    with zipfile.ZipFile(reduced, "w", zipfile.ZIP_STORED) as target:
        narrowing = choose(unpacked_parts)
        parts: list[tuple[str, bytes]] = []
        for info in infos:
            data = unpacked_parts[info.filename]
            narrow = narrowing(info.filename, data)
            if narrow is not None:
                with suppress(IrregularSheetData):
                    data = narrow(data)
            parts.append((info.filename, data))
        replaced = _used_strings_only(dict(parts)) if used_strings_only else {}
        for name, data in parts:
            target.writestr(name, replaced.get(name, data))
    return reduced.getvalue()


def _window(xml: bytes, start: int, end: int, dated: Sequence[tuple[int, int]]) -> tuple[int, int]:
    """Granice w XML wierszy od pierwszego do ostatniego z wierszy ``dated`` (numer, miejsce komórki daty w nim).

    Komentarz albo CDATA, który zaczyna się nad nimi, a kończy w nich, i granica innego ``<sheetData>`` w nich to
    ``IrregularSheetData``: wiersze w komentarzu nie są wierszami arkusza. Resztę kształtu sprawdza openpyxl, który
    czyta zawężony arkusz.
    """

    begin = xml.rfind(b"<row", start, min(dated)[1])
    finish = xml.find(b"</row>", max(dated)[1], end)
    if begin < 0 or finish < 0 or _IRREGULAR_IN_ROW.search(xml, begin, finish):
        raise IrregularSheetData("komentarz, CDATA albo drugi sheetData")
    return begin, finish + len(b"</row>")


def _first_row(xml: bytes, start: int, end: int) -> set[tuple[int, int]]:
    """Granice w XML wiersza 1, gdy arkusz zaczyna się od niego (nagłówki Rejestru zleceń); inaczej pusty zbiór."""

    begin = xml.find(b"<row", start, end)
    if begin < 0 or not xml.startswith(b'<row r="1"', begin):
        return set()
    tag_end = xml.index(b">", begin)
    finish = tag_end + 1 if xml[tag_end - 1 : tag_end] == b"/" else xml.index(b"</row>", tag_end) + len(b"</row>")
    return {(begin, finish)}


def _master_rows(xml: bytes, start: int, end: int) -> set[tuple[int, int]]:
    """Granice w XML wierszy z formułą główną wspólnej formuły: openpyxl potrzebuje jej, by czytać formuły z niej
    przeniesione."""

    rows: set[tuple[int, int]] = set()
    for found in _SHARED_FORMULA_MASTER.finditer(xml, start, end):
        begin = xml.rfind(b"<row", start, found.start())
        if begin >= 0:
            rows.add((begin, xml.index(b"</row>", found.end(), end) + len(b"</row>")))
    return rows


def _with_rows(xml: bytes, sheet: SheetData, kept: Iterable[int]) -> bytes:
    """XML arkusza tylko z wierszami o indeksach ``kept`` i z wierszami formuł głównych wspólnych formuł.

    Najpierw sprawdza cały XML: openpyxl nie przeczyta pominiętych wierszy, a zepsuty arkusz ma być nieczytelny.
    """

    masters = (sheet.row_index(found.start()) for found in _SHARED_FORMULA_MASTER.finditer(xml, sheet.start, sheet.end))
    indices = sorted({*kept, *masters} - {-1})
    expat.ParserCreate().Parse(xml, True)
    rows = sheet.rows
    return b"".join([xml[: sheet.start], *(xml[rows[index].start : rows[index].end] for index in indices), xml[sheet.end :]])


def _is_number_between(attributes: bytes, content: bytes, low: float, high: float) -> bool:
    """Komórka z liczbą z [``low``, ``high``]: tylko taką openpyxl może odczytać jako datę z przedziału."""

    found_type = _TYPE.search(attributes)
    cell_type = found_type.group(1) if found_type else None
    if cell_type == b"d":
        raise IrregularSheetData("data tekstem ISO")
    if cell_type not in _NUMBER_TYPES:
        return False
    value = _VALUE.search(content)
    if value is None:
        return False
    try:
        number = float(value.group(1))
    except ValueError:
        raise IrregularSheetData("wartość liczbowa") from None
    return low <= number <= high


# --- teksty wspólne ----------------------------------------------------------------------------

_SHARED_STRINGS_TYPE: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
_CONTENT_TYPE_OVERRIDE: Final = "{http://schemas.openxmlformats.org/package/2006/content-types}Override"
_STRINGS_ROOT: Final = re.compile(
    rb"(?:<\?xml[^>]*\?>)?\s*<(?:[\w.-]+:)?[\w.-]+((?:\s+[\w.:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*)\s*(/?)>\s*"
)
"""Prolog bez komentarzy, DOCTYPE i instrukcji przetwarzania i znacznik otwierający korzeń z białymi znakami za nim;
grupa 1 to atrybuty korzenia, grupa 2 ``/`` korzenia bez treści."""
_MAIN_DEFAULT: Final = re.compile(rb"""\sxmlns\s*=\s*(["'])""" + re.escape(SPREADSHEET_NS.encode("ascii")) + rb"\1")
_STRING_ITEMS: Final = re.compile(
    rb"(?:<si(?:\s+(?!xmlns)[\w.:-]+\s*=\s*(?:\"[^\"]*\"|'[^']*'))*+\s*+"
    rb"(?:/>|>[^<]*+(?:<(?![!?]|/?(?:[\w.-]+:)?si)[^<]*+)*+</si\s*+>)\s*+)*+"
)
"""Ciąg ``<si>`` z białymi znakami między nimi, każdy bez prefiksu i bez ``xmlns``, a w jego treści bez komentarza,
CDATA, instrukcji przetwarzania i znacznika, którego nazwa bez prefiksu zaczyna się od ``si``; kwantyfikatory bez
cofania, bo odrzucenie tabeli z dziesiątkami tysięcy tekstów z cofaniem trwałoby długo."""
_STRING_START: Final = re.compile(rb"<si")
_CELL: Final = f"{SPREADSHEET_NS} c"
_CELL_VALUE: Final = f"{SPREADSHEET_NS} v"


def _used_strings_only(parts: Mapping[str, bytes]) -> dict[str, bytes]:
    """Części do podmiany: tabela tekstów wspólnych tylko z tekstami, do których sięgają komórki ``t="s"`` arkuszy, i
    arkusze z numerami tekstów w nowej tabeli.

    Teksty zostają bajt w bajt i w kolejności z tabeli, więc openpyxl czyta z każdej komórki ten sam tekst. Tabela to
    część, którą wskazuje ``[Content_Types].xml``, tak jak w openpyxl, a arkusze to cel relacji każdego ``<sheet>``
    skoroszytu. Kształt spoza tego, który znają ``shared_string_spans`` i ``_shared_cells``, zepsuty XML albo numer spoza
    tabeli, którego openpyxl może nie przeczytać: żadnej podmiany, więc openpyxl czyta skoroszyt jak bez niej.
    """

    strings = next(
        (
            override.get("PartName", "")[1:]
            for override in ElementTree.fromstring(parts["[Content_Types].xml"]).iter(_CONTENT_TYPE_OVERRIDE)
            if override.get("ContentType") == _SHARED_STRINGS_TYPE
        ),
        "",
    )
    if strings not in parts:
        return {}
    table = parts[strings]
    try:
        items = shared_string_spans(table)
        cells = {part: _shared_cells(parts[part]) for part in _sheet_parts(parts)}
    except (UnsupportedShape, expat.ExpatError):
        return {}
    used = sorted({index for found in cells.values() for _, _, index in found})
    if not items or (used and used[-1] >= len(items)):
        return {}
    renumbered = {index: number for number, index in enumerate(used)}
    kept = (table[slice(*items[index])] for index in used)
    replaced = {strings: b"".join([table[: items[0][0]], *kept, table[items[-1][1] :]])}
    for part, found in cells.items():
        xml = parts[part]
        pieces: list[bytes] = []
        last = 0
        for start, end, index in found:
            pieces += [xml[last:start], b"%d" % renumbered[index]]
            last = end
        replaced[part] = b"".join([*pieces, xml[last:]])
    return replaced


# Przygotowanie czyta tę samą tabelę w Sprawdzaniu (``intermax_file.Register``) i w Odczycie danych (zawężenie), z tych
# samych bajtów z ``unpacked``: tabela Rejestru zleceń ma dziesiątki tysięcy tekstów.
@lru_cache(maxsize=1)
def shared_string_spans(table: bytes) -> tuple[tuple[int, int], ...]:
    """Granice każdego ``<si>`` tabeli tekstów wspólnych ``table`` w kolejności z tabeli: od jego początku do początku
    następnego, a ostatniego do ostatniego znacznika końca, czyli korzenia, więc tekst ma też białe znaki za sobą.

    Tabelę sprawdza parser expat (zepsuty XML to ``ExpatError``), a granice dają wyrażenia regularne, które znają jeden
    kształt: prolog bez komentarzy, DOCTYPE i instrukcji przetwarzania, korzeń bez treści (żadnych tekstów) albo z
    domyślną przestrzenią nazw arkusza i treścią, która od początku do końca jest ciągiem ``<si>`` (``_STRING_ITEMS``).
    W poprawnym XML bez komentarzy, CDATA i instrukcji przetwarzania każdy ``<`` zaczyna znacznik, więc każdy ``<si>``
    jest wtedy dzieckiem korzenia z przestrzeni nazw arkusza, tak jak liczy go openpyxl, a każde ``<si`` w treści
    korzenia zaczyna tekst. Inny kształt to ``UnsupportedShape``.
    """

    expat.ParserCreate(namespace_separator=" ").Parse(table, True)
    root = _STRINGS_ROOT.match(table)
    if root is not None and root.group(2):
        return ()
    end = table.rfind(b"</")
    if root is None or not _MAIN_DEFAULT.search(root.group(1)) or not _STRING_ITEMS.fullmatch(table, root.end(), end):
        raise UnsupportedShape("teksty wspólne")
    starts = [found.start() for found in _STRING_START.finditer(table, root.end(), end)]
    return tuple(pairwise([*starts, end]))


def _sheet_parts(parts: Mapping[str, bytes]) -> set[str]:
    """Części arkuszy, z których openpyxl czyta komórki: cel relacji każdego ``<sheet>`` skoroszytu."""

    workbook = office_document(parts) or ""
    rels = relationships(parts, workbook)
    sheets = ElementTree.fromstring(parts[workbook]).iter(f"{MAIN}sheet")
    return {rel.target for sheet in sheets if (rel := rels.get(sheet.get(f"{{{OFFICE_REL}}}id", ""))) is not None}


def _shared_cells(xml: bytes) -> list[tuple[int, int, int]]:
    """Numer tekstu wspólnego w każdym ``<v>`` komórki ``t="s"`` arkusza z granicami w XML jego tekstu: (początek,
    koniec, numer), w kolejności z arkusza.

    openpyxl czyta numer z ``<v>`` dziecka komórki; ``<v>`` głębiej dostaje nowy numer tak samo, więc nie zmienia tego,
    co openpyxl czyta. Granice daje parser expat, a tekst ``<v>`` ma być samymi cyframi w bajtach XML, bez spacji,
    encji, CDATA ani znaczników; inaczej ``UnsupportedShape``, także pusty ``<v>``. Zepsuty XML to ``ExpatError``.
    """

    parser = expat.ParserCreate(namespace_separator=" ")
    cells: list[tuple[int, int, int]] = []
    depth = value_depth = value_start = 0
    shared = False

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal depth, shared, value_depth, value_start
        depth += 1
        if name == _CELL:
            shared = attributes.get("t") == "s"
        elif name == _CELL_VALUE and shared:
            # Pierwszy ``>`` za ``<v`` zamyka znacznik, a gdyby stał w atrybucie, tekst ma znaki spoza cyfr.
            value_depth, value_start = depth, xml.index(b">", parser.CurrentByteIndex) + 1

    def end(_: str) -> None:
        nonlocal depth, value_depth
        if value_depth == depth:
            digits = xml[value_start : parser.CurrentByteIndex]
            if not digits.isdigit():
                raise UnsupportedShape("komórka tekstu wspólnego")
            cells.append((value_start, parser.CurrentByteIndex, int(digits)))
            value_depth = 0
        depth -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(xml, True)
    return cells
