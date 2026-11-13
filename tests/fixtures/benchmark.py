"""Benchmark Przebiegu rozliczeń w testach: syntetyczne Wzorce i CLI narzędzia jako osobny proces.

Narzędzie leży w ``tools/``, poza pakietem, więc testy uruchamiają je tak jak Maks:
osobnym procesem Pythona z tego checkoutu.
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from openpyxl import load_workbook

from rozliczenia import tool_files
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.collective_layout import DATA_ROW_COLUMNS, FIRST_DATA_ROW, QUANTITY_COLUMNS
from atrapy.preparation import write_collective_template, write_internal_template
from atrapy.settlement import write_template
from atrapy.workbooks import active_worksheet

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "tools" / "benchmark_przebiegu.py"
SYNTHETIC_TEMPLATES = ROOT / "tools" / "syntetyczne_wzorce.py"

# Nazwy, pod którymi Wzorce leżą w ``config``: te same, których szukają procesy.
WORKER_TEMPLATE = tool_files.WORKER_TEMPLATE.name
COLLECTIVE_TEMPLATE = tool_files.COLLECTIVE_TEMPLATE.name
INTERNAL_TEMPLATE = tool_files.INTERNAL_TEMPLATE.name
# Mała odmiana syntetycznych Wzorców: kilka grup wspólnych formuł (co 64 wiersze), szybka w pytest.
SMALL_DATA_ROWS = 150

# Pliki repozytorium, których benchmark nie może zmienić: Lista Wykonawców i historie metryk procesów. Ustawień
# Centrum benchmark nie dotyka, bo biegnie przez Skrypt dla maszyn, który ich nie pisze (rozliczenia.centrum.settings).
PROTECTED_REPOSITORY_FILES = (
    tool_files.CONFIG_DIR / WORKERS_FILE,
    tool_files.SETTLEMENT_METRICS,
    tool_files.PREPARATION_METRICS,
)

# Kolumny Pliku zbiorczego, które identyfikują klienta albo zlecenie: ADRES, UMOWA, NUMER ZL., NUMER UMOWY.
_IDENTIFYING_COLUMNS = (2, 3, 6, 9)


def write_templates(directory: Path) -> Path:
    directory.mkdir(parents=True)
    write_template(directory / WORKER_TEMPLATE)
    write_internal_template(directory / INTERNAL_TEMPLATE)
    write_collective_template(directory / COLLECTIVE_TEMPLATE)
    return directory


def write_synthetic_templates(directory: Path, data_rows: int | None = SMALL_DATA_ROWS) -> Path:
    """Folder z syntetycznymi Wzorcami kształtu Wzorców taty, z generatora w ``tools/``.

    ``data_rows=None`` to pełny rozmiar, jak u taty (domyślny w generatorze).
    """

    size = [] if data_rows is None else ["--data-rows", str(data_rows)]
    generated = _run_tool(SYNTHETIC_TEMPLATES, str(directory), *size)
    assert generated.returncode == 0, generated.stdout + generated.stderr
    return directory


def zip_part(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read(name).decode("utf-8")


def zip_part_names(path: Path) -> set[str]:
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def run_benchmark(*arguments: str) -> subprocess.CompletedProcess[str]:
    return _run_tool(BENCHMARK, *arguments)


def start_benchmark(*arguments: str) -> subprocess.Popen[str]:
    """CLI benchmarku uruchomione w tle; test czyta jego wyjście w trakcie pracy."""

    return subprocess.Popen(
        [sys.executable, str(BENCHMARK), *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


@contextmanager
def measurement_in_progress(lock: Path) -> Iterator[None]:
    """Inny pomiar trwa: trzyma wyłączną blokadę pliku ``lock`` tak jak benchmark (flock, na Windows msvcrt)."""

    with lock.open("a+b") as handle:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def _run_tool(tool: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tool), *arguments],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=100,
        check=False,
    )


def protected_repository_files() -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.is_file() else None for path in PROTECTED_REPOSITORY_FILES}


def identifying_values(collective_file: Path) -> set[str]:
    """Adresy, numery umów i numery zleceń z wierszy danych Pliku zbiorczego lustra."""

    workbook = load_workbook(collective_file)
    try:
        sheet = active_worksheet(workbook)
        return {
            str(row[column - 1])
            for row in sheet.iter_rows(min_row=FIRST_DATA_ROW, max_col=11, values_only=True)
            for column in _IDENTIFYING_COLUMNS
            if row[column - 1] is not None
        }
    finally:
        workbook.close()


def data_row_entries(collective_file: Path) -> list[tuple[object, ...]]:
    """Wpisy taty w każdym Wierszu danych Pliku zbiorczego lustra: ilości ``N:AP`` i obciążenia z uwagami ``AQ:AT``."""

    workbook = load_workbook(collective_file)
    try:
        sheet = active_worksheet(workbook)
        return [
            row[QUANTITY_COLUMNS[0] - 1 :]
            for row in sheet.iter_rows(min_row=FIRST_DATA_ROW, max_col=DATA_ROW_COLUMNS[-1], values_only=True)
            if any(value is not None for value in row[:11])
        ]
    finally:
        workbook.close()


def frozen_reference(reference_directory: Path) -> Path:
    """Jedyny zamrożony Folder rozliczeń pracowników pod ``reference_directory``."""

    (folder,) = (path for path in reference_directory.rglob("Rozliczenie pracowników *") if path.is_dir())
    return folder
