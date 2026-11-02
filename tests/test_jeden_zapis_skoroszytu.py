"""Skoroszyt zapisują tylko moduły zapisu, więc obie drogi zapisu dają ten sam plik (#282).

``template_file`` zapisuje openpyxl, ``template_copy`` kopiuje Wzorzec, ``row_look`` daje obu ten sam
Wygląd Wiersza danych, ``workbook_save`` zapisuje plik atomowo, ``efenix_marking`` stawia Znaczniki efenix w Pliku zbiorczym
podmianą stylu komórek XML, ``intermax_file`` daje bajty dnia Uporządkowania INTERMAX z podmianą wierszy XML, a
``intermax_replace`` zastępuje nimi albo bajtami Kopii INTERMAX Rejestr zleceń. Reszta
``src`` przekazuje im Wiersze danych, ale sama nie pisze do komórek ani plików.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path
import re

SRC = Path(__file__).resolve().parents[1] / "src"
WRITERS = frozenset(
    {
        "rozliczenia/efenix_marking.py",
        "rozliczenia/template_file.py",
        "rozliczenia/template_copy.py",
        "rozliczenia/row_look.py",
        "rozliczenia/workbook_save.py",
        "rozliczenia/intermax_file.py",
        "rozliczenia/intermax_replace.py",
    }
)
CELL_WRITES = frozenset(
    {"value", "font", "fill", "border", "alignment", "number_format", "protection", "hyperlink", "auto_filter"}
    | {"comment", "freeze_panes"}
)
SHEET_CHANGES = frozenset(
    {"insert_rows", "delete_rows", "insert_cols", "delete_cols", "move_range", "merge_cells", "unmerge_cells"}
    | {"add_data_validation", "add_image", "add_chart", "add_table"}
)
SHEET_PARTS = frozenset({"row_dimensions", "column_dimensions"})
CELL_PARAMETERS = frozenset({"row", "column", "value"})  # Worksheet.cell z openpyxl, w odróżnieniu od RowLook.cell
COLUMN = r"\$?[A-Z]{1,3}\$?"
CELL_ADDRESS = re.compile(rf"{COLUMN}[0-9]+(?::{COLUMN}[0-9]+)?")
NOT_WORKBOOK_SAVES = {
    "phases.save": "PhaseRunner.save to etap Zapisywanie procesu; skoroszyt zapisuje w nim template_file",
}


def _cell_address(index: ast.expr) -> bool:
    """``"A1"``, ``"A1:C3"`` albo ``f"A{row}"``: adres komórki, pod który ``sheet[...] =`` wpisuje wartość."""

    if isinstance(index, ast.JoinedStr):
        head = index.values[0]
        return len(index.values) > 1 and isinstance(head, ast.Constant) and re.fullmatch(COLUMN, str(head.value)) is not None
    return isinstance(index, ast.Constant) and isinstance(index.value, str) and CELL_ADDRESS.fullmatch(index.value) is not None


def _writes(tree: ast.Module) -> Iterator[ast.expr]:
    """Przypisanie wartości, wyglądu albo wymiaru komórki, zmiana układu arkusza i ``.cell(..., value=...)``.

    Przypisanie do ``self`` się nie liczy.
    """

    for node in ast.walk(tree):
        if isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store):
            if (
                (isinstance(node, ast.Attribute) and node.attr in CELL_WRITES and ast.unparse(node.value) != "self")
                or (isinstance(node, ast.Subscript) and _cell_address(node.slice))
                or any(isinstance(part, ast.Attribute) and part.attr in SHEET_PARTS for part in ast.walk(node))
            ):
                yield node
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in SHEET_CHANGES:
            yield node
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "cell":
            keywords = {keyword.arg for keyword in node.keywords}
            if keywords <= CELL_PARAMETERS and (len(node.args) == 3 or "value" in keywords):
                yield node


def test_zapis_skoroszytu_ma_jedno_miejsce() -> None:
    """Poza modułami zapisu nikt nie przypisuje wartości, wyglądu ani wymiaru komórki, nie zmienia układu arkusza
    (``insert_rows``, ``merge_cells``) i nie woła ``.save``.

    Znana granica: ``sheet[adres] = …`` z adresem w zmiennej i ``sheet.append(…)`` wyglądają w składni jak zapis do
    słownika i listy, a odróżnia je dopiero typ obiektu, którego test nie zna.
    """

    found, saves = [], set()
    for path in sorted(SRC.rglob("*.py")):
        name = path.relative_to(SRC).as_posix()
        if name in WRITERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += [f"src/{name}:{write.lineno}: {ast.unparse(write)} pisze do skoroszytu" for write in _writes(tree)]
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "save":
                if (called := ast.unparse(node.func)) in NOT_WORKBOOK_SAVES:
                    saves.add(called)
                else:
                    found.append(f"src/{name}:{node.lineno}: {called}(...) zapisuje skoroszyt")
    found += [f"NOT_WORKBOOK_SAVES: nikt nie woła {called}, usuń wpis" for called in sorted(NOT_WORKBOOK_SAVES.keys() - saves)]

    assert not found, "\n".join(
        [
            *found,
            "Wiersze danych zapisuj przez TemplateFile.create z template_file.py, a wygląd komórki przez RowLook z "
            "row_look.py; wywołanie .save, które nie zapisuje skoroszytu, wpisz do NOT_WORKBOOK_SAVES z powodem.",
        ]
    )
