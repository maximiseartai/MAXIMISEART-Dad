"""Sprawdzenie Wzorca przed Archiwum Logów okresu (ADR 0025, „Wzorce w Archiwum Logów okresu”): każdy wiersz tabeli
postaci z docstringu ``rozliczenia.centrum.template_archive`` na syntetycznym Wzorcu.

Wzorzec, którego sprawdzenie nie przepuściło, nie idzie do Archiwum, a Wzorzec, który przeszedł, ma nazwę ze skrótu
swoich bajtów. Skan pakietu jest raz na wersję Wzorca, a strażnik z pamięcią reguły danych pracy Centrum przechodzi go
znowu, gdy pamięć poznała nową wartość, więc wartość, którą praca poznała po pierwszym sprawdzeniu, też zatrzymuje
Wzorzec. Drogę Wzorca przez Centrum i Kolejkę
wysyłki do Archiwum pokazują testy w ``tests/test_centrum_logi_w_skrzynce.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import io
from typing import Final
import zipfile

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet
import pytest

from rozliczenia.centrum.template_archive import ArchivedTemplate, Refusal, TemplateChecks, TemplateRefused, asset_name, from_queue
from rozliczenia.client_data import ForbiddenColumn, ForbiddenValues, empty_memory
from rozliczenia.tool_files import COLLECTIVE_TEMPLATE, INTERNAL_TEMPLATE, WORKER_TEMPLATE

_COLLECTIVE: Final = COLLECTIVE_TEMPLATE.name
_INTERNAL: Final = INTERNAL_TEMPLATE.name
_WORKER: Final = WORKER_TEMPLATE.name
_ADDRESS: Final = "Syntetyczna Lipowa 5"
"""Wartość ``ADRES``, którą praca Centrum przeczytała w pliku taty, w próbkach z pamięcią."""


def _workbook(change: Callable[[Workbook, Worksheet], object] = lambda workbook, sheet: None) -> Workbook:
    """Wzorzec w kształcie Wzorca taty w tym, co czyta sprawdzenie: stawki nad nagłówkiem, nagłówki w wierszu 17 z
    ``ADRES`` w B i numerem Orange w I, a pod nimi formuły i ilości."""

    workbook = Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet.title = "Rozliczenie"
    sheet["C3"] = "Stawki"
    sheet["N14"] = 45.5
    for letter, header in {"A": "LP", "B": "ADRES", "H": "WYKONAWCA", "I": "NUMER UMOWY/ZLECENIA ORANGE", "N": "ILOŚĆ"}.items():
        sheet[f"{letter}17"] = header
    sheet["N18"] = 0
    sheet["AU18"] = "=SUM(N18:R18)"
    change(workbook, sheet)
    return workbook


def _bytes(workbook: Workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _cell(reference: str, value: str | float) -> Callable[[Workbook, Worksheet], object]:
    def change(workbook: Workbook, sheet: Worksheet) -> None:
        sheet[reference] = value

    return change


def _with_part(content: bytes, name: str, part: bytes) -> bytes:
    """Pakiet ``content`` z częścią ``name`` o bajtach ``part``, nowej albo w miejscu tej o tej nazwie."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(buffer, "w") as target:
        for item in source.infolist():
            if item.filename != name:
                target.writestr(item, source.read(item.filename))
        target.writestr(name, part)
    return buffer.getvalue()


def _cached_formula_result(content: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        sheet = package.read("xl/worksheets/sheet1.xml").decode("utf-8")
    cached = sheet.replace("<f>SUM(N18:R18)</f><v />", "<f>SUM(N18:R18)</f><v>600123456</v>")
    assert cached != sheet, "Wzorzec bez formuły AU18 w postaci, którą zna próbka"
    return _with_part(content, "xl/worksheets/sheet1.xml", cached.encode("utf-8"))


_PARSER_CHUNK: Final = 16 * 1024
"""Porcja pliku, którą ``xml.etree.ElementTree.iterparse`` czyta naraz: ogon za znacznikiem końca na jej granicy parser
przypisuje dopiero w następnej porcji."""


def _tail_vml(*, at_chunk_end: bool) -> bytes:
    """Rysunek komentarza z telefonem w ogonie ``</div>``; ``at_chunk_end``: znacznik ``</div>`` kończy się dokładnie na
    końcu pierwszej porcji parsera, a ogon jest w następnej."""

    head = b'<xml xmlns:v="urn:schemas-microsoft-com:vml"><v:shape><v:textbox><div>Notatka</div>'
    if at_chunk_end:
        head = head.replace(b"<v:textbox>", b"<v:textbox>" + b" " * (_PARSER_CHUNK - len(head)), 1)
        assert len(head) == _PARSER_CHUNK and head.endswith(b"</div>")
    return head + b"tel. 600 123 456</v:textbox></v:shape></xml>"


def _drawing(part: bytes) -> Callable[[], bytes]:
    return lambda: _with_part(_bytes(_workbook()), "xl/drawings/vmlDrawing1.vml", part)


_EXTERNAL_RELS: Final = (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{kind}" Target="{target}" '
    'TargetMode="External"/></Relationships>'
)
"""Relacje pamięci łącza zewnętrznego: cel łącza (``externalLinkPath``) albo relacja innego rodzaju z tym samym celem."""
_PATH_WITH_PHONE: Final = "file:///C:/Users/tel 600 123 456/cennik.xlsx"


def _external_link_rels(kind: str) -> Callable[[], bytes]:
    return lambda: _with_part(
        _bytes(_workbook()), "xl/externalLinks/_rels/externalLink1.xml.rels", _EXTERNAL_RELS.format(kind=kind, target=_PATH_WITH_PHONE).encode()
    )


_EXTERNAL: Final = (
    '<externalLink xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><externalBook>'
    '<sheetNames><sheetName val="Cennik"/></sheetNames><sheetDataSet><sheetData sheetId="0"><row r="1">'
    '<cell r="A1" t="str"><v>{text}</v></cell><cell r="B1"><v>12.5</v></cell></row></sheetData></sheetDataSet>'
    "</externalBook></externalLink>"
)
"""Pamięć łącza zewnętrznego Wzorca: nazwa arkusza i wartości komórek skoroszytu, do którego prowadzi łącze."""


def _remembered(memory: ForbiddenValues) -> ForbiddenValues:
    memory.remember_value(ForbiddenColumn.ADDRESS, _ADDRESS)
    return memory


@dataclass(frozen=True)
class Case:
    file: str
    content: Callable[[], bytes]
    expected: Refusal | None
    remembered: bool = False


def _plain(change: Callable[[Workbook, Worksheet], object] = lambda workbook, sheet: None) -> Callable[[], bytes]:
    return lambda: _bytes(_workbook(change))


def _comment(workbook: Workbook, sheet: Worksheet) -> None:
    sheet["D5"].comment = Comment("Dzwonić: 600 123 456", "tata")


def _creator(workbook: Workbook, sheet: Worksheet) -> None:
    workbook.properties.creator = "tel. 600 123 456"


def _header(text: str) -> Callable[[Workbook, Worksheet], object]:
    def change(workbook: Workbook, sheet: Worksheet) -> None:
        header = sheet.oddHeader
        assert header is not None
        header.left.text = text

    return change


def _footer(workbook: Workbook, sheet: Worksheet) -> None:
    footer = sheet.oddFooter
    assert footer is not None
    footer.center.text = "tel. 600 123 456"


def _tooltip(workbook: Workbook, sheet: Worksheet) -> None:
    sheet["C4"] = "Cennik"
    sheet["C4"].hyperlink = "https://example.com/"
    assert sheet["C4"].hyperlink is not None
    sheet["C4"].hyperlink.tooltip = "tel. 600 123 456"


def _mailto(workbook: Workbook, sheet: Worksheet) -> None:
    sheet["C4"] = "Cennik"
    sheet["C4"].hyperlink = "mailto:biuro@example.com?subject=tel. 600 123 456"


def _validation(workbook: Workbook, sheet: Worksheet) -> None:
    validation = DataValidation(type="list", formula1='"tel. 600 123 456,inne"')
    sheet.add_data_validation(validation)
    validation.add("C5")


def _rich_phone(workbook: Workbook, sheet: Worksheet) -> None:
    sheet["C5"] = CellRichText("tel. 600 ", TextBlock(InlineFont(b=True), "123 456"))


def _renamed(header: str) -> Callable[[Workbook, Worksheet], object]:
    def change(workbook: Workbook, sheet: Worksheet) -> None:
        sheet["B17"] = header
        sheet["B18"] = "Kwiatowa 7"

    return change


CASES: Final[dict[str, Case]] = {
    "Wzorzec bez treści taty przechodzi": Case(_COLLECTIVE, _plain(), None),
    "wartość pod nagłówkiem ADRES": Case(_INTERNAL, _plain(_cell("B18", "Kwiatowa 7")), Refusal.ADDRESS),
    "liczba pod nagłówkiem numeru Orange": Case(_INTERNAL, _plain(_cell("I18", 123456789)), Refusal.ORANGE),
    "wartość w B pod innym nagłówkiem w układzie Pliku zbiorczego": Case(_COLLECTIVE, _plain(_renamed("MIEJSCE")), Refusal.ADDRESS),
    "wartość w B pod innym nagłówkiem Wzorca bez układu Pliku zbiorczego": Case(_INTERNAL, _plain(_renamed("MIEJSCE")), None),
    "formuła pod nagłówkiem ADRES": Case(_INTERNAL, _plain(_cell("B18", "=A18")), None),
    "tekst z zakazaną wartością z pamięci pracy": Case(_COLLECTIVE, _plain(_cell("C5", f"Zostało: {_ADDRESS}")), Refusal.FORBIDDEN, remembered=True),
    "ten sam tekst, gdy praca nie zna wartości": Case(_COLLECTIVE, _plain(_cell("C5", f"Zostało: {_ADDRESS}")), None),
    "tekst z telefonem": Case(_COLLECTIVE, _plain(_cell("C5", "tel. 600 123 456")), Refusal.FREE_TEXT),
    "tekst z ulicą": Case(_COLLECTIVE, _plain(_cell("C5", "biuro ul. Kwiatowa 7")), Refusal.FREE_TEXT),
    "liczba w kształcie telefonu": Case(_COLLECTIVE, _plain(_cell("C5", 600123456)), Refusal.FREE_TEXT),
    "komentarz z telefonem": Case(_WORKER, _plain(_comment), Refusal.FREE_TEXT),
    "nazwa arkusza z zakazaną wartością": Case(
        _COLLECTIVE, _plain(lambda workbook, sheet: setattr(sheet, "title", _ADDRESS)), Refusal.FORBIDDEN, remembered=True
    ),
    "właściwości dokumentu z telefonem": Case(_COLLECTIVE, _plain(_creator), Refusal.FREE_TEXT),
    "pamięć łącza zewnętrznego z telefonem": Case(
        _COLLECTIVE,
        lambda: _with_part(_bytes(_workbook()), "xl/externalLinks/externalLink1.xml", _EXTERNAL.format(text="600 123 456").encode()),
        Refusal.FREE_TEXT,
    ),
    "pamięć łącza zewnętrznego z cennikiem": Case(
        _COLLECTIVE,
        lambda: _with_part(_bytes(_workbook()), "xl/externalLinks/externalLink1.xml", _EXTERNAL.format(text="Montaż").encode()),
        None,
    ),
    "obraz w pakiecie": Case(_COLLECTIVE, lambda: _with_part(_bytes(_workbook()), "xl/media/image1.png", b"\x89PNG"), Refusal.UNKNOWN_PART),
    "plik, który nie jest pakietem": Case(_COLLECTIVE, lambda: b"nie zip", Refusal.UNREADABLE),
    "arkusz z uszkodzonym XML": Case(
        _COLLECTIVE, lambda: _with_part(_bytes(_workbook()), "xl/worksheets/sheet1.xml", b"<worksheet"), Refusal.UNREADABLE
    ),
    "wynik formuły w kształcie telefonu": Case(_COLLECTIVE, lambda: _cached_formula_result(_bytes(_workbook())), Refusal.FREE_TEXT),
    "stała z zakazaną wartością w formule": Case(
        _INTERNAL, _plain(_cell("C4", f'=IF(A1="{_ADDRESS}",1,0)')), Refusal.FORBIDDEN, remembered=True
    ),
    "nagłówek wydruku z zakazaną wartością sklejoną z kodem części": Case(
        _INTERNAL, _plain(_header(_ADDRESS)), Refusal.FORBIDDEN, remembered=True
    ),
    "stopka wydruku z telefonem": Case(_INTERNAL, _plain(_footer), Refusal.FREE_TEXT),
    "nieznany kod nagłówka wydruku": Case(_INTERNAL, _plain(_header("&QStawki")), Refusal.UNREADABLE),
    "podpowiedź hiperłącza z telefonem": Case(_INTERNAL, _plain(_tooltip), Refusal.FREE_TEXT),
    "cel hiperłącza mailto z telefonem": Case(_INTERNAL, _plain(_mailto), Refusal.FREE_TEXT),
    "lista walidacji danych z telefonem": Case(_INTERNAL, _plain(_validation), Refusal.FREE_TEXT),
    "telefon na granicy przebiegów formatowania tekstu": Case(_COLLECTIVE, _plain(_rich_phone), Refusal.FREE_TEXT),
    "relacja pamięci łącza innego rodzaju niż cel łącza, z telefonem": Case(_COLLECTIVE, _external_link_rels("hyperlink"), Refusal.FREE_TEXT),
    "tekst za elementem (ogon) w rysunku komentarza": Case(_WORKER, _drawing(_tail_vml(at_chunk_end=False)), Refusal.FREE_TEXT),
    "ogon za granicą porcji pliku, którą czyta parser": Case(_WORKER, _drawing(_tail_vml(at_chunk_end=True)), Refusal.FREE_TEXT),
    "komentarz XML w części": Case(
        _WORKER, _drawing(b'<xml xmlns:v="urn:schemas-microsoft-com:vml"><!-- tel. 600 123 456 --><v:shape/></xml>'), Refusal.XML_EXTRA
    ),
    "instrukcja przetwarzania w części": Case(
        _WORKER, _drawing(b'<xml xmlns:v="urn:schemas-microsoft-com:vml"><?notatka tel. 600 123 456?><v:shape/></xml>'), Refusal.XML_EXTRA
    ),
    "wyjątek: cel łącza zewnętrznego idzie bez strażnika": Case(_COLLECTIVE, _external_link_rels("externalLinkPath"), None),
    "wyjątek: stawka w wierszu 14": Case(_COLLECTIVE, _plain(_cell("N14", 57.25)), None),
    "granica: wartość nad nagłówkiem ADRES": Case(_INTERNAL, _plain(_cell("B3", "Kwiatowa 7")), None),
}




@pytest.mark.parametrize("case", CASES)
def test_sprawdzenie_wzorca_do_archiwum_daje_wynik_z_tabeli_postaci(case: str) -> None:
    row = CASES[case]
    memory = _remembered(empty_memory()) if row.remembered else empty_memory()
    content = row.content()
    file = row.file

    found = TemplateChecks(memory).checked(file, content)

    if row.expected is None:
        assert isinstance(found, ArchivedTemplate), found
        assert (found.name, found.file, found.content) == (asset_name(hashlib.sha256(content).hexdigest()), file, content)
    else:
        assert isinstance(found, TemplateRefused) and found == TemplateRefused(file, row.expected)
        assert found.note == f"Reguła danych: {file} nie idzie do Archiwum Logów okresu: {row.expected.value}."
        assert _ADDRESS not in found.note and "600" not in found.note


def test_wartosc_poznana_po_pierwszym_sprawdzeniu_zatrzymuje_ten_sam_wzorzec_przy_nastepnym() -> None:
    """Skan pakietu jest raz na wersję Wzorca, ale jego teksty przechodzą przez pamięć pracy Centrum przy każdym
    sprawdzeniu: Wzorzec, który przeszedł, zanim praca przeczytała ten ``ADRES``, przy następnych Logach już nie idzie."""

    memory = empty_memory()
    checks = TemplateChecks(memory)
    content = _bytes(_workbook(_cell("C5", f"Zostało: {_ADDRESS}")))

    before = checks.checked(_COLLECTIVE, content)
    _remembered(memory)
    after = checks.checked(_COLLECTIVE, content)

    assert (isinstance(before, ArchivedTemplate), after) == (True, TemplateRefused(COLLECTIVE_TEMPLATE.name, Refusal.FORBIDDEN))


def test_wzorzec_z_pliku_kolejki_ma_nazwe_ze_skrotu_swoich_bajtow_a_wzorca_bez_sprawdzenia_nie_ma() -> None:
    content = _bytes(_workbook())
    name = asset_name(hashlib.sha256(content).hexdigest())
    other = asset_name(hashlib.sha256(content + b"x").hexdigest())

    assert from_queue(name, COLLECTIVE_TEMPLATE.name, content).content == content
    with pytest.raises(ValueError, match="skrótu"):
        from_queue(other, COLLECTIVE_TEMPLATE.name, content)
    with pytest.raises(ValueError, match="skrótu"):
        from_queue(name, "Rejestr zleceń.xlsx", content)
    with pytest.raises(TypeError, match="TemplateChecks.checked"):
        ArchivedTemplate(*(from_queue(name, COLLECTIVE_TEMPLATE.name, content).name,) * 2, content, object())
