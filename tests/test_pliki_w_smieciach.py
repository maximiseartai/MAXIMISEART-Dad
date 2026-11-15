"""Straż pliku, który test zostawił otwarty w śmieciach (``tests/fixtures/pliki_w_smieciach.py``, #1923)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import contextlib
import gc
import os
from pathlib import Path
import sqlite3
import sys
import threading
from typing import IO, Final
import warnings
import zipfile

from openpyxl import Workbook, load_workbook
import pytest

from tests.fixtures.pliki_w_smieciach import left_to_gc, open_files
from tests.fixtures.znane_luki import assert_znane_luki

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="straż listuje deskryptory tylko na Linuksie i macOS")


@contextlib.contextmanager
def _bez_samoczynnego_gc() -> Iterator[None]:
    # Samoczynny gc w trakcie testu zamknąłby plik w śmieciach przed sprawdzeniem.
    gc.disable()
    try:
        yield
    finally:
        gc.enable()


def _skoroszyt(tmp_path: Path) -> Path:
    path = tmp_path / "skoroszyt.xlsx"
    Workbook().save(path)
    return path


def test_skoroszyt_read_only_bez_close_zamyka_dopiero_gc_a_straz_podaje_jego_sciezke(tmp_path: Path) -> None:
    path = _skoroszyt(tmp_path)

    with _bez_samoczynnego_gc():
        before = open_files()
        load_workbook(path, read_only=True)
        left = left_to_gc(before)

    assert left == [str(path.resolve())]


def test_zamkniety_skoroszyt_read_only_nie_wywraca_testu(tmp_path: Path) -> None:
    path = _skoroszyt(tmp_path)

    with _bez_samoczynnego_gc():
        before = open_files()
        workbook = load_workbook(path, read_only=True)
        workbook.close()
        left = left_to_gc(before)

    assert left == []


def test_zipfile_w_cyklu_zamyka_plik_bez_resourcewarning_a_straz_i_tak_podaje_jego_sciezke(tmp_path: Path) -> None:
    path = _skoroszyt(tmp_path)

    with _bez_samoczynnego_gc():
        before = open_files()
        cykl: list[object] = [zipfile.ZipFile(path)]
        cykl.append(cykl)
        del cykl
        left = left_to_gc(before)

    assert left == [str(path.resolve())]


def test_plik_ktory_zywy_watek_zamyka_w_trakcie_gc_nie_wywraca_testu(tmp_path: Path) -> None:
    # Wątek kolejki Zgłoszeń kończy blok with na pliku blokady przejścia już po teście, czasem w trakcie gc.collect()
    # straży: callback gc puszcza wątek dokładnie w tym oknie i czeka na jego koniec.
    path = _skoroszyt(tmp_path)
    otwarty, puszczony = threading.Event(), threading.Event()

    def trzyma_plik() -> None:
        with path.open("rb"):
            otwarty.set()
            puszczony.wait(10)

    watek = threading.Thread(target=trzyma_plik, daemon=True)

    def konczy_watek_w_trakcie_gc(phase: str, info: dict[str, int]) -> None:
        if phase == "start":
            puszczony.set()
            watek.join(10)

    with _bez_samoczynnego_gc():
        before = open_files()
        watek.start()
        otwarty.wait(10)
        gc.callbacks.append(konczy_watek_w_trakcie_gc)
        try:
            left = left_to_gc(before)
        finally:
            gc.callbacks.remove(konczy_watek_w_trakcie_gc)

    assert (left, watek.is_alive()) == ([], False)


class _PuszczaWatekWPrzegladzie:
    """Obiekt, o którego ``__class__`` pyta ``isinstance`` w przeglądzie ``gc.get_objects()`` straży: puszcza wtedy wątek
    i czeka na jego koniec, więc wątek zamyka i puszcza swój plik, gdy lista przeglądu jeszcze go trzyma."""

    def __init__(self, puszcza: Callable[[], None]) -> None:
        self._puszcza = puszcza

    @property  # type: ignore[misc]  # isinstance pyta o __class__ tylko do odczytu
    def __class__(self) -> type:
        self._puszcza()
        return _PuszczaWatekWPrzegladzie


def test_plik_ktory_zywy_watek_puszcza_w_trakcie_przegladu_obiektow_nie_wywraca_testu(tmp_path: Path) -> None:
    # Lista gc.get_objects() trzyma każdy obiekt, więc obiekt pliku, który wątek kolejki puścił w trakcie przeglądu,
    # zwalnia dopiero koniec listy w wątku straży, przed gc.collect().
    path = _skoroszyt(tmp_path)
    otwarty, puszczony = threading.Event(), threading.Event()

    def trzyma_plik() -> None:
        with path.open("rb"):
            otwarty.set()
            puszczony.wait(10)

    watek = threading.Thread(target=trzyma_plik, daemon=True)

    def puszcza() -> None:
        puszczony.set()
        watek.join(10)

    with _bez_samoczynnego_gc():
        before = open_files()
        watek.start()
        otwarty.wait(10)
        straznik = _PuszczaWatekWPrzegladzie(puszcza)
        left = left_to_gc(before)
        del straznik

    assert (left, watek.is_alive()) == ([], False)


def _zywy_obiekt(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    trzymane.append(path.open("rb"))


def _windows(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    load_workbook(path, read_only=True)


def _plik_biblioteki_c(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    cykl: list[object] = [sqlite3.connect(path.with_suffix(".sqlite"))]
    cykl.append(cykl)


def _potok(path: Path, trzymane: list[IO[bytes]], monkeypatch: pytest.MonkeyPatch) -> None:
    odczyt, zapis = os.pipe()
    os.close(zapis)
    cykl: list[object] = [os.fdopen(odczyt, "rb")]
    cykl.append(cykl)


ZNANE_LUKI: Final[dict[str, Callable[[Path, list[IO[bytes]], pytest.MonkeyPatch], None]]] = {
    "widzi tylko plik zwolniony przez gc: plik trzymany po teście przez żywy obiekt": _zywy_obiekt,
    "listuje deskryptory tylko na Linuksie i macOS: na Windows nie widzi pliku w śmieciach": _windows,
    "zna tylko obiekt io.FileIO: plik otwarty przez bibliotekę C (połączenie sqlite3) w cyklu": _plik_biblioteki_c,
    "zna tylko zwykłe pliki: potok (jak wyjście procesu potomnego) w cyklu": _potok,
}


def test_znane_luki_strazy_plikow_w_smieciach_przechodza_przez_nia(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _skoroszyt(tmp_path)
    zgloszenia: dict[str, list[str]] = {}

    for opis, probka in ZNANE_LUKI.items():
        trzymane: list[IO[bytes]] = []
        with monkeypatch.context() as patch, _bez_samoczynnego_gc():
            before = open_files()
            probka(path, trzymane, patch)
            zgloszenia[opis] = left_to_gc(before)
        for obiekt in trzymane:
            obiekt.close()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()  # plik próbki w śmieciach nie zostaje dla straży po teście

    assert_znane_luki(zgloszenia, "tests/test_pliki_w_smieciach.py")
