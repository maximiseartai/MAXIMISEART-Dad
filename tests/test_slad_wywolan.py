from __future__ import annotations

from typing import NoReturn

import pytest

from rozliczenia.call_trace import CallTrace
from rozliczenia.tool_files import TOOL_ROOT

THIS_FILE = "tests/test_slad_wywolan.py"


def _source() -> NoReturn:
    raise KeyError("Kowalski, ul. Polna 1")


def _middle() -> NoReturn:
    try:
        _source()
    except KeyError as error:
        raise ValueError("adres") from error


def _top() -> NoReturn:
    try:
        _middle()
    except ValueError as error:
        raise RuntimeError("zlecenie") from error


def test_przyczyny_sladu_ida_od_bezposredniej_do_zrodlowej_kazda_z_ramkami_od_przejscia_do_rzucenia() -> None:
    with pytest.raises(RuntimeError) as raised:
        _top()

    trace = CallTrace.of(raised.value)

    assert (trace.exception_type, [(frame.file, frame.function) for frame in trace.frames][1:]) == (
        "RuntimeError",
        [(THIS_FILE, "_top")],
    )
    assert [(cause.exception_type, [frame.function for frame in cause.frames]) for cause in trace.causes] == [
        ("ValueError", ["_top", "_middle"]),
        ("KeyError", ["_middle", "_source"]),
    ]


def test_slad_pomija_ramki_biblioteki_w_srodowisku_pythona_w_katalogu_narzedzia() -> None:
    def library() -> NoReturn:
        raise LookupError("C:/Users/Jan Kowalski/OneDrive")

    library.__code__ = library.__code__.replace(co_filename=str(TOOL_ROOT / ".venv" / "lib" / "site-packages" / "biblioteka.py"))

    with pytest.raises(LookupError) as raised:
        library()

    assert [frame.file for frame in CallTrace.of(raised.value).frames] == [THIS_FILE]
