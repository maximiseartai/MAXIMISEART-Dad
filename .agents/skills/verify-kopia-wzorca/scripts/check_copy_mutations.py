"""Show that check_template_copy.py fails on broken variants of the template copy.

Each mutation runs on its own copy of the checkout (``tools/mutacje.py``) with the
checker, without shrinking, and must end with ``KOPIA WZORCA: NOWE NARUSZENIE``. A
mutation whose anchor text is no longer in its file exactly once is reported as
NIEAKTUALNA: update it to the new code.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))

from mutacje import Edit, Mutation, check_all

VERIFIED = Path("src/rozliczenia/template_copy.py")
ROW_LOOK = Path("src/rozliczenia/row_look.py")
LAYOUT = Path("src/rozliczenia/collective_layout.py")
CHECKER = (".agents/skills/verify-kopia-wzorca/scripts/check_template_copy.py", "--no-shrink")
EXPECTED = "KOPIA WZORCA: NOWE NARUSZENIE"

MUTATIONS = (
    Mutation(
        "CRC arkusza tylko z początku",
        (Edit(VERIFIED, "crc = zlib.crc32(piece, crc)", "crc = crc"),),
        CHECKER,
        "Excel i openpyxl odrzucają Rozliczenie pracownika jako uszkodzony plik",
        EXPECTED,
    ),
    Mutation(
        "kawałki kompresji z jednego kompresora bez pełnego opróżnienia",
        (
            Edit(VERIFIED, "    view = memoryview(xml)\n", "    view = memoryview(xml)\n    compressor = zlib.compressobj(_COMPRESSION_LEVEL, zlib.DEFLATED, -15)\n"),
            Edit(VERIFIED, "        compressor = zlib.compressobj(_COMPRESSION_LEVEL, zlib.DEFLATED, -15)\n        last", "        last"),
            Edit(VERIFIED, "zlib.Z_FINISH if last else zlib.Z_FULL_FLUSH", "zlib.Z_FINISH if last else zlib.Z_SYNC_FLUSH"),
            Edit(VERIFIED, "list(pool.map(compressed,", "list(map(compressed,"),
        ),
        CHECKER,
        "kawałek sięga wstecz do bajtów Wzorca, których po podmianie już nie ma: arkusz jest uszkodzony",
        EXPECTED,
    ),
    Mutation(
        "zgubiony kawałek za podmienionymi wierszami",
        (Edit(VERIFIED, "*self._chunks[chunk:-1]", "*self._chunks[chunk + 1 : -1]"),),
        CHECKER,
        "z Rozliczenia pracownika znika 64 wierszy Wzorca z formułami",
        EXPECTED,
    ),
    Mutation(
        "dimension bez wpisanych wierszy",
        (Edit(VERIFIED, "max(max_row or 1, last_row),", "max_row or 1,"),),
        CHECKER,
        "zakres arkusza nie obejmuje Wierszy danych za sformatowanymi wierszami Wzorca",
        EXPECTED,
    ),
    Mutation(
        "data bez formatu daty",
        (Edit(VERIFIED, "date_format = None if is_date_format(styles.number_format(template_style)) else _date_format(value)", "date_format = None"),),
        CHECKER,
        "data zlecenia pokazuje się jako liczba seryjna",
        EXPECTED,
    ),
    Mutation(
        "pusta wartość nie czyści zer Wzorca",
        (Edit(VERIFIED, 'if empty_style == template_style and existing is not None and existing.endswith(b"/>"):', "if existing is not None:"),),
        CHECKER,
        "pusta ilość z Pliku zbiorczego zostaje w Rozliczeniu pracownika zerem z Wzorca",
        EXPECTED,
    ),
    Mutation(
        "Wyróżnienia bez wypełnienia",
        (Edit(VERIFIED, 'xf = with_style_attribute(xf, b"fillId", fill_id, b"applyFill")', "pass"),),
        CHECKER,
        "wypełnienie komórki z Pliku zbiorczego nie przechodzi do Rozliczenia pracownika",
        EXPECTED,
    ),
    Mutation(
        "obramowanie Wzorca w kolumnach wyglądu",
        (Edit(VERIFIED, 'xf = with_style_attribute(xf, b"borderId", border_id, b"applyBorder")', "pass"),),
        CHECKER,
        "Wiersze danych bez obramowania komórek, jak w resztkach formatowania Wzorca",
        EXPECTED,
    ),
    Mutation(
        "format liczby Wzorca w kolumnach wyglądu",
        (Edit(VERIFIED, "if self.number_format(style) != look.number_format:", "if False:"),),
        CHECKER,
        "DATA w Rozliczeniu pracownika ma format Wzorca i pokazuje #####",
        EXPECTED,
    ),
    Mutation(
        "wysokość wiersza Wzorca zostaje",
        (Edit(VERIFIED, 'start_tag = _HEIGHT.sub(b"", start_tag)', "start_tag = start_tag"),),
        CHECKER,
        "wpisany wiersz ma wysokość z Wzorca i Excel nie dopasowuje jej do treści",
        EXPECTED,
    ),
    Mutation(
        "zawijanie każdego tekstu",
        (Edit(ROW_LOOK, 'return isinstance(value, str) and ("\\n" in value or "\\r" in value)', "return isinstance(value, str)"),),
        CHECKER,
        "obie drogi zawijają każdy tekst, więc wiersze bez końca linii są w Excelu wyższe",
        EXPECTED,
    ),
    Mutation(
        "\\r nie zawija tekstu",
        (Edit(ROW_LOOK, 'return isinstance(value, str) and ("\\n" in value or "\\r" in value)', 'return isinstance(value, str) and "\\n" in value'),),
        CHECKER,
        "tekst z końcem linii Windows z Rejestru zostaje w Excelu bez zawijania",
        EXPECTED,
    ),
    Mutation(
        "rozmiar czcionki nie z nagłówka",
        (Edit(ROW_LOOK, "sz=font.sz,", "sz=(font.sz or 11) + 1,"),),
        CHECKER,
        "obie drogi piszą Wiersze danych inną czcionką niż nagłówek Wzorca",
        EXPECTED,
    ),
    Mutation(
        "15 cyfr znaczących zamiast 16",
        (Edit(VERIFIED, '"%.16g"', '"%.15g"'),),
        CHECKER,
        "ilości i kwoty są zaokrąglone inaczej niż przy zapisie przez openpyxl",
        EXPECTED,
    ),
    Mutation(
        "xml:space tylko przy spacji na początku",
        (Edit(VERIFIED, "if text != text.strip() else", "if text != text.lstrip() else"),),
        CHECKER,
        "Excel ucina spacje na końcu tekstu",
        EXPECTED,
    ),
    Mutation(
        "& bez escapowania",
        (Edit(VERIFIED, 'text.replace("&", "&amp;")', "text"),),
        CHECKER,
        "tekst z & daje niepoprawny XML i plik, którego Excel nie otworzy",
        EXPECTED,
    ),
    Mutation(
        "<hyperlinks> za pageMargins",
        (Edit(VERIFIED, '        "dataValidations",\n    }', '        "dataValidations",\n        "pageMargins",\n    }'),),
        CHECKER,
        "blok Hiperłączy poza kolejnością schematu arkusza: Excel proponuje naprawę pliku i usuwa Hiperłącza",
        EXPECTED,
    ),
    Mutation(
        "rId Wzorca użyty ponownie",
        (Edit(VERIFIED, "self._first = max(numbers) + 1", "self._first = 1"),),
        CHECKER,
        "numer zlecenia otwiera rysunek komentarza Wzorca zamiast zlecenia, a Excel proponuje naprawę pliku",
        EXPECTED,
    ),
    Mutation(
        "Hiperłącze o wiersz dalej",
        (Edit(VERIFIED, 'b"%d" % (first_row + index), link)', 'b"%d" % (first_row + index + 1), link)'),),
        CHECKER,
        "numer zlecenia otwiera zlecenie z wiersza wyżej",
        EXPECTED,
    ),
    Mutation(
        "& w adresie Hiperłącza bez escapowania",
        (Edit(VERIFIED, "html.escape(text, quote=True)", "text"),),
        CHECKER,
        "relacje arkusza są niepoprawnym XML i plik się nie otwiera",
        EXPECTED,
    ),
    # The checker and the synthetic Wzorce take Dad's layout from tools/lib/atrapy/pliki_taty.py, so a wrong constant in
    # src misses the Wzorzec; with the layout from src both moved with it and the check passed.
    Mutation(
        "pierwszy Wiersz danych o wiersz niżej w układzie src",
        (Edit(LAYOUT, "FIRST_DATA_ROW: Final = 18", "FIRST_DATA_ROW: Final = 19"),),
        CHECKER,
        "Rozliczenie pracownika zaczyna Wiersze danych pod pierwszym sformatowanym wierszem Wzorca taty",
        EXPECTED,
    ),
    Mutation(
        "Wygląd Wiersza danych bez kolumny L w układzie src",
        (Edit(LAYOUT, 'LOOK_COLUMNS: Final = _span("A", "L")', 'LOOK_COLUMNS: Final = _span("A", "K")'),),
        CHECKER,
        "kolumna L Wierszy danych zostaje z formatowaniem Wzorca zamiast Wyglądu Wiersza danych",
        EXPECTED,
    ),
)


if __name__ == "__main__":
    raise SystemExit(check_all(MUTATIONS))
