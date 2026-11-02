"""Run skilla ``verify-skoroszyty-w-excelu`` nie zostawia w Excelu skoroszytów ani rosnącego procesu Excela (#390).

Prawdziwy Excel sprawdza sam skill (``.agents/skills/verify-skoroszyty-w-excelu/SKILL.md``). Tu ``excel.py``
ma podstawione wywołania AppleScriptu (podróbka ``FakeExcel``), a kroki runu, które potrzebują fixture i Excela,
zastępuje ``_drive``, który otwiera skoroszyty na biurku runu. Bez ``osascript`` test biegnie też na Windows,
gdzie zadanie CI ``mutations`` uruchamia ``check_excel_cleanup_mutations.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

SKILL_SCRIPTS = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-skoroszyty-w-excelu" / "scripts"

PID = 4242
DIALOG_WINDOW = "8 |  | 420x180"
RUN_WORKBOOKS = ("Rozliczenie 08_14_09_2026 - zbiorcze.xlsx", "Rozliczenie 08_14_09_2026 - Kamil Syntetyczny.xlsx")
MAKS_WORKBOOK = "/Users/maks/Documents/Rozliczenie Maksa.xlsx"


class FakeExcel:
    """Excel, jak widzi go ``excel.py``: działa albo nie, trzyma skoroszyty, ma okno dialogowe, zajmuje pamięć."""

    def __init__(self, excel: ModuleType) -> None:
        self.excel = excel
        self.running = False
        self.workbooks: list[str] = []
        self.dialog = False
        # Excel names its workbooks also behind a dialog that is not modal.
        self.names_workbooks_in_dialog = False
        self.rss_mb = 2400
        self.closed: list[str] = []
        self.end_error: Exception | None = None
        self.running_after_end_error = True

    def open_paths(self, timeout: int = 10) -> list[str]:
        if self.dialog and not self.names_workbooks_in_dialog:
            raise self.excel.ExcelDialog("Excel answers 'missing value' for its workbooks: a modal dialog is up")
        return list(self.workbooks) if self.running else []

    def close(self, path: Path, *, timeout: float = 30) -> None:
        if self.dialog:
            raise self.excel.ExcelDialog("Excel refuses AppleScript calls (-1708)")
        self.workbooks.remove(str(path))
        self.closed.append(str(path))

    def applescript(self, script: str, *arguments: str, timeout: int = 60) -> str:
        assert "to quit" in script, f"the fake Excel answers only quit, not {script!r}"
        if self.dialog:
            raise self.excel.ExcelDialog("Excel refuses AppleScript calls (-1708)")
        if self.end_error is not None:
            raise self.end_error
        self.running = False
        return ""

    def terminate(self, process_id: int) -> bool:
        if self.end_error is not None:
            self.running = self.running_after_end_error
            raise self.end_error
        self.running, self.dialog, self.workbooks = False, False, []
        return True


@pytest.fixture
def excel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeExcel]:
    monkeypatch.syspath_prepend(str(SKILL_SCRIPTS))
    for name in ("excel", "run_excel_verification"):
        sys.modules.pop(name, None)
    module = importlib.import_module("excel")
    fake = FakeExcel(module)
    desk = tmp_path / "Containers" / "com.microsoft.Excel" / "Data" / "maximiseart-weryfikacja"
    desk.mkdir(parents=True)
    replaced = {
        "DESK": desk,
        "claim": lambda *, owner: io.StringIO(),
        "installed_version": lambda: "16.114.1",
        "running": lambda: fake.running,
        "pid": lambda: PID if fake.running else None,
        "rss_mb": lambda: fake.rss_mb if fake.running else None,
        "open_paths": fake.open_paths,
        "close": fake.close,
        "dialogs": lambda: [DIALOG_WINDOW] if fake.dialog and fake.running else [],
        "terminate": fake.terminate,
        "_osascript": fake.applescript,
    }
    for name, value in replaced.items():
        monkeypatch.setattr(module, name, value)
    yield fake
    for name in ("excel", "run_excel_verification"):
        sys.modules.pop(name, None)


def _run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: FakeExcel, *, dialog: bool = False, opened_by_user: tuple[str, ...] = ()
) -> tuple[int, str]:
    """``run_excel_verification.main`` whose drive opens this run's workbooks on its desk, as the real steps do."""

    runner = importlib.import_module("run_excel_verification")

    def drive(run: object, args: object, real_templates: object) -> None:
        stranded = [path for path in fake.workbooks if Path(path).is_relative_to(fake.excel.DESK)]
        assert not stranded, f"the doctor would refuse workbooks named like this run's: {stranded}"
        desk: Path = run.desk  # type: ignore[attr-defined]
        desk.mkdir(parents=True)
        if not fake.running:
            fake.running = True
            run.started_excel = PID  # type: ignore[attr-defined]
        for name in RUN_WORKBOOKS:
            (desk / name).write_bytes(b"PK")
            fake.workbooks.append(str(desk / name))
        fake.workbooks += opened_by_user
        fake.rss_mb += 600
        if dialog:
            fake.dialog = True
            raise fake.excel.ExcelDialog(f"{RUN_WORKBOOKS[0]}: Excel did not answer within 180 s")

    monkeypatch.setattr(runner, "_drive", drive)
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", output)
    code = runner.main(["--wzorce", "syntetyczne", "--run-dir", str(tmp_path / "przebieg")])
    return code, output.getvalue()


def _evidence(tmp_path: Path) -> Path:
    (evidence,) = (tmp_path / "przebieg" / "evidence").iterdir()
    return evidence


def _verdict(output: str) -> str:
    return output.strip().splitlines()[-1]


def test_okno_dialogowe_przy_sprzataniu_zostawia_biurko_i_nie_udaje_sukcesu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel
) -> None:
    excel.running = True

    code, output = _run(tmp_path, monkeypatch, excel, dialog=True)

    (desk,) = (path for path in excel.excel.DESK.iterdir() if path.is_dir())
    cleanup = (_evidence(tmp_path) / "cleanup.txt").read_text(encoding="utf-8")
    assert code == 1 and _verdict(output).startswith("VERIFY FAIL"), output
    assert "close_failed=ExcelDialog" in cleanup and f"desk_kept={desk}" in cleanup, cleanup
    assert "scratch_removed=true" not in output, output
    assert sorted(path.name for path in desk.iterdir()) == sorted(RUN_WORKBOOKS)
    assert excel.running, "Excel with a dialog was quit"


def test_start_runu_zamyka_skoroszyty_martwych_runow_i_usuwa_ich_biurka_a_skoroszytu_maksa_nie_dotyka(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel
) -> None:
    dead_desk = excel.excel.DESK / "excel-martwy0000"
    dead_desk.mkdir()
    stranded = dead_desk / RUN_WORKBOOKS[0]
    stranded.write_bytes(b"PK")
    (excel.excel.DESK / "excel-martwy0001").mkdir()
    excel.running, excel.workbooks = True, [MAKS_WORKBOOK, str(stranded)]

    code, output = _run(tmp_path, monkeypatch, excel)

    observed = json.loads((_evidence(tmp_path) / "excel.json").read_text(encoding="utf-8"))
    assert code == 0 and _verdict(output).startswith("VERIFY OK"), output
    assert str(stranded) in excel.closed and MAKS_WORKBOOK not in excel.closed
    assert [path.name for path in excel.excel.DESK.iterdir()] == [], "a desk of a dead run or this run is left"
    assert (observed["stale_workbooks_closed"], observed["stale_desks_removed"]) == (1, 2), observed
    assert excel.running and excel.workbooks == [MAKS_WORKBOOK], "Excel with Maks's workbook was quit or changed"
    assert "excel_quit=false" in output, output


@pytest.mark.parametrize("excel_was_running", [False, True], ids=["excel-wylaczony", "excel-pusty-przed-runem"])
def test_koniec_runu_konczy_excela_bez_skoroszytow_takze_zastanego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel, excel_was_running: bool
) -> None:
    excel.running = excel_was_running

    code, output = _run(tmp_path, monkeypatch, excel)

    assert code == 0 and _verdict(output).startswith("VERIFY OK"), output
    assert "excel_quit=true" in output and "scratch_removed=true" in output, output
    assert not excel.running


def test_run_zapisuje_pamiec_excela_przed_i_po(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel
) -> None:
    excel.running, excel.workbooks = True, [MAKS_WORKBOOK]

    _run(tmp_path, monkeypatch, excel)

    observed = json.loads((_evidence(tmp_path) / "excel.json").read_text(encoding="utf-8"))
    assert (observed["excel_rss_mb_before"], observed["excel_rss_mb_after"]) == (2400, 3000), observed
    assert (observed["excel_workbooks_before"], observed["excel_workbooks_after"]) == (1, 1), observed


@pytest.mark.parametrize("error", ["ExcelDialog", "ExcelError"])
def test_nieudane_zamkniecie_excela_jest_notatka_sprzatania_a_nie_tracebackiem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel, error: str
) -> None:
    excel.running = True
    excel.end_error = getattr(excel.excel, error)("Excel did not answer within 60 s (-1712)")

    code, output = _run(tmp_path, monkeypatch, excel)

    cleanup = (_evidence(tmp_path) / "cleanup.txt").read_text(encoding="utf-8")
    observed = json.loads((_evidence(tmp_path) / "excel.json").read_text(encoding="utf-8"))
    assert code == 0 and _verdict(output).startswith("VERIFY OK"), output
    assert f"excel_quit_failed={error}" in cleanup and "scratch_removed=true" in cleanup, cleanup
    assert (observed["excel_rss_mb_after"], observed["excel_workbooks_after"]) == (3000, 0), observed


@pytest.mark.parametrize(
    ("error", "excel_ended"),
    [
        pytest.param(
            lambda excel: excel.ExcelDialog("Excel did not answer within 90 s of starting"), False, id="ExcelDialog"
        ),
        pytest.param(lambda excel: ProcessLookupError(3, "No such process"), True, id="ProcessLookupError"),
        pytest.param(lambda excel: subprocess.CalledProcessError(1, ["open", "-g"]), False, id="CalledProcessError"),
    ],
)
def test_nieudane_zatrzymanie_excela_z_oknem_dialogowym_konczy_run_linia_verify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    excel: FakeExcel,
    error: Callable[[ModuleType], Exception],
    excel_ended: bool,
) -> None:
    excel.end_error, excel.running_after_end_error = error(excel.excel), not excel_ended

    code, output = _run(tmp_path, monkeypatch, excel, dialog=True)

    cleanup = (_evidence(tmp_path) / "cleanup.txt").read_text(encoding="utf-8")
    assert code == 1 and _verdict(output).startswith("VERIFY FAIL"), output
    assert f"excel_quit_failed={type(excel.end_error).__name__}" in cleanup, cleanup
    assert ("desk_kept=" in cleanup) is not excel_ended, cleanup
    assert ("scratch_removed=true" in cleanup) is excel_ended, cleanup


# Nowy skoroszyt, którego Maks jeszcze nie zapisał, Excel nazywa bez ścieżki.
UNSAVED_WORKBOOK = "Zeszyt1"


@pytest.mark.parametrize(
    "opened",
    [(), (MAKS_WORKBOOK,), (UNSAVED_WORKBOOK,)],
    ids=["tylko-skoroszyty-runu", "skoroszyt-uzytkownika", "niezapisany-skoroszyt-uzytkownika"],
)
def test_excel_uruchomiony_przez_run_z_oknem_dialogowym_zostaje_otwarty_tylko_ze_skoroszytem_uzytkownika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel, opened: tuple[str, ...]
) -> None:
    excel.names_workbooks_in_dialog = True
    users = bool(opened)

    code, output = _run(tmp_path, monkeypatch, excel, dialog=True, opened_by_user=opened)

    cleanup = (_evidence(tmp_path) / "cleanup.txt").read_text(encoding="utf-8")
    assert code == 1 and _verdict(output).startswith("VERIFY FAIL"), output
    assert ("excel_dialog_left=true" in cleanup, "excel_stopped=true" in cleanup) == (users, not users), cleanup
    assert excel.running is users and all(workbook in excel.workbooks for workbook in opened)


def test_nieznany_numer_procesu_excela_po_nieudanym_starcie_konczy_run_linia_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel
) -> None:
    runner = importlib.import_module("run_excel_verification")

    def start_without_answer(run: object, args: object, real_templates: object) -> None:
        excel.running = True
        raise excel.excel.ExcelDialog("Excel did not answer within 90 s of starting; dialogs: []")

    def two_excels() -> int:
        raise excel.excel.ExcelError("pgrep -x 'Microsoft Excel' exited 0 with ['733', '734'], not one process id")

    monkeypatch.setattr(runner, "_drive", start_without_answer)
    monkeypatch.setattr(excel.excel, "pid", two_excels)
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(sys, "stderr", output)

    code = runner.main(["--wzorce", "syntetyczne", "--run-dir", str(tmp_path / "przebieg")])

    assert code == 1 and _verdict(output.getvalue()).startswith("VERIFY FAIL"), output.getvalue()
    assert "excel_quit=true" in output.getvalue(), output.getvalue()


def test_okno_dialogowe_na_starcie_konczy_run_przed_praca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, excel: FakeExcel
) -> None:
    excel.running, excel.dialog = True, True

    code, output = _run(tmp_path, monkeypatch, excel)

    assert code == 1 and "VERIFY FAIL | ExcelDialog" in output, output
    assert list(excel.excel.DESK.iterdir()) == [], "the run opened its workbooks into an Excel with a dialog"
    assert excel.running, "Excel with a dialog was quit"


if __name__ == "__main__":
    # Skrypt mutacji skilla (check_excel_cleanup_mutations.py) uruchamia ten moduł jako skrypt z repozytorium.
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:randomly", "-p", "no:cacheprovider"]))
