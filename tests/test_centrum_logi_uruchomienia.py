"""Logi Uruchomienia (ADR 0015, #317) przez HTTP API Centrum: plik JSON na komputerze taty po każdym Uruchomieniu.

Testy czytają pliki z katalogu Logów obok dziennika Centrum, tak jak Maks dostanie je z komputera taty.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, time as time_of_day, timedelta, timezone
from decimal import Decimal
import errno
import hashlib
from http import HTTPStatus
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import threading
import time
from typing import Any, Final, NoReturn, cast

from openpyxl import load_workbook
from openpyxl.worksheet.formula import ArrayFormula
from playwright.sync_api import Browser, sync_playwright
from pydantic import ValidationError
import pytest

from rozliczenia import settlement_messages, workbook_files
from rozliczenia.domain import RunMode
from rozliczenia.centrum import app
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.process_run import RunResult
from rozliczenia.centrum.dad_action_journal import DAD_ACTIONS_FILE, DadActionJournal
from rozliczenia.centrum.dad_actions import DadActions, ViewOpened
from rozliczenia.centrum.efenix_chrome import EFENIX_URL, EfenixWindow
from rozliczenia.centrum.comment_versions import ProgressVersion, post_of, progress_markdown
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import RETRY_S, Outbox, Post
from rozliczenia.centrum.logs_disk import LAST_STARTED_FILE, EndEntry, Journal, LogsOnDisk, name_of
from rozliczenia.centrum.run_comments import PROGRESS_S, RecordMaker
from rozliczenia.centrum.pricing_progress import OrderDone, PricingProgress
from rozliczenia.centrum.run_logs import Environment, LoggedInterruption, LoggedOrder, LoggedStep, ProcessLogs, RunLog, StartFacts, Tool
from rozliczenia.centrum.run_logs_guard import guard_text
from rozliczenia.centrum.report_box import Unreachable
from rozliczenia.centrum.tool_update import Release
from rozliczenia.efenix_pace import ACTION_PAUSE_S, KEEPALIVE_S, Pace
from rozliczenia.efenix_pricing import OrderKind
from rozliczenia.efenix_window import ForwardRefusal, WindowAction
from rozliczenia.client_data import empty_memory, guarded
from rozliczenia.dad_files import DadFiles
from rozliczenia.input_copy import InputCopy
from rozliczenia.workbook_files import ByteSource
from rozliczenia.preparation_register import period_sheets, read, register_problem
from rozliczenia.period_folder import PeriodFolder, PeriodFolderInaccessible, collective_file_name_with
from rozliczenia.register_file import OrderSheets
from rozliczenia.report_cells import ReportColumn
from rozliczenia.settlement_period import parse_period_token
from rozliczenia.telemetry import MetricsStore
from rozliczenia.worker_reports import AddBar, MoveBar, SubjectFault, VerdictFault

from atrapy.atrapa_efenix import (
    CATALOG,
    LIST_PAGE,
    TODAY,
    AtrapaEfenix,
    AtrapaOrder,
    Changed,
    Outage,
    amount_of,
    atrapa_efenix,
)
from tests.fixtures.centrum import (
    STOP_S,
    TOOL_COMMIT,
    FakeGitHub,
    FakeReportBox,
    ToolDirectory,
    finished_view,
    run_events,
    view_timing,
    views_until,
    without_times,
    write_report_key,
)
from tests.fixtures.centrum_processes import (
    PreparingCentrum,
    SettlingCentrum,
    Surroundings,
    preparing_centrum,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from tests.fixtures.bez_dostepu import without_creating
from tests.fixtures.centrum_w_procesie import centrum_process
from atrapy.dziennik_wyceny import begun_line, end_line, ended_line, left_journal
from atrapy.efenix import DAY, Order, write_collective_file
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, fake_cli
from tests.fixtures.fakt_domeny import known
from tests.fixtures.konce_linii_windows import windows_text_writes
from tests.fixtures.potomne import wait_for
from tests.fixtures.praca_centrum import centrum_work
from atrapy.pliki_taty import COLLECTIVE_HEADERS, REGISTER_NAME
from atrapy.preparation import (
    OLD_REGISTER_HEADERS,
    PERIOD,
    RAW_ORDER_FONT,
    default_register_rows,
    in_old_layout,
    incomplete_period_rows,
    paste_raw_orders,
    register_order,
    type_into_register,
    write_register,
)
from tests.fixtures.run_cards import first_view, restored, unlisted
from atrapy.settlement import MARKED, SOURCE_NAME, CellValue, write_quantity_source
from tests.fixtures.tool_clone import ToolRepository, git_failing_on, tool_repository
from tests.fixtures.wyciek import zawiera_wartosc
from atrapy.widok_skrzynki import shown
from atrapy.workbooks import active_worksheet, rewrite_parts

import odtworz_uruchomienie

AnyCentrum = PreparingCentrum | SettlingCentrum
KEYS = {
    "schema_version", "run_id", "process", "mode", "pricing", "period", "started_at", "ended_at", "duration_ms", "tool",
    "result", "ending", "stop_kind", "issue_count", "messages", "technical_notes", "summary", "phases", "templates",
    "inea_only_cleared", "intermax_entries", "efenix_orders", "efenix_stop", "report_entering", "environment", "trace",
    "diagnosis",
    "dad_actions", "interruption", "input_copy", "input_copy_notes", "quantity_rules",
}


def log_files(centrum: AnyCentrum) -> list[Path]:
    return sorted(centrum.tool.run_logs.glob("*"))


def records(centrum: AnyCentrum) -> list[dict[str, Any]]:
    """Logi po kolei od startu; nazwy plików mają start z dokładnością do sekundy."""

    loaded = [json.loads(path.read_text(encoding="utf-8")) for path in log_files(centrum)]
    return sorted(loaded, key=lambda record: datetime.fromisoformat(record["started_at"]))


def in_json(path: Path) -> str:
    """Ścieżka tak, jak stoi w tekście pliku JSON (w Windows z podwojonym ``\\``)."""

    return json.dumps(str(path))[1:-1]


def utc(moment: str | None) -> datetime:
    """Godzina kroku z Logów; każda jest w UTC."""

    assert moment is not None, "krok bez godziny"
    parsed = datetime.fromisoformat(moment)
    assert parsed.utcoffset() == timedelta(0), moment
    return parsed


def card_messages(view: dict[str, Any]) -> list[dict[str, str]]:
    return [*view["result"]["stops"], *view["result"]["warnings"]]


def three_parts(record: dict[str, Any]) -> list[dict[str, str]]:
    """Komunikaty z Logów tak, jak je pokazuje karta: trzy części i link do sekcji Ustawień, gdy go mają."""

    return [{part: message[part] for part in ("what", "where", "action", "setting") if part in message} for message in record["messages"]]


Ran = tuple[AnyCentrum, dict[str, Any]]


def _settlement(tmp_path: Path, *, dry_run: bool, include_unmapped: bool = False) -> Ran:
    centrum = settling_centrum(tmp_path, include_unmapped=include_unmapped)
    return centrum, run_to_end(centrum, dry_run=dry_run)


def _preparation(tmp_path: Path, *, dry_run: bool) -> Ran:
    centrum = preparing_centrum(tmp_path)
    return centrum, run_to_end(centrum, dry_run=dry_run)


def _existing_worker_settlements(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = settling_centrum(tmp_path)
    centrum.worker_settlements.mkdir()
    return centrum, run_to_end(centrum, dry_run=False)


def _missing_collective_file(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = settling_centrum(tmp_path)
    centrum.collective_file.unlink()
    return centrum, run_to_end(centrum, dry_run=True)


def _aborted_decision(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]
    centrum.client.post(f"/api/runs/{waiting['run']['id']}/decision", json={"answer": "abort"})
    return centrum, finished_view(centrum.client)


def _missing_collective_template(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.collective_template_path.unlink()
    return centrum, run_to_end(centrum, dry_run=False)


def _failing(
    centrum: Callable[[Path], AnyCentrum], *, dry_run: bool, engine: bool
) -> Callable[[Path, pytest.MonkeyPatch], Ran]:
    def run(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
        steered = centrum(tmp_path)
        if engine:
            steered.engines.fail_engine = True
        else:
            steered.engines.fail_summary = True
        return steered, run_to_end(steered, dry_run=dry_run)

    return run


def _adapter_net(
    centrum: Callable[[Path], AnyCentrum], *, dry_run: bool
) -> Callable[[Path, pytest.MonkeyPatch], Ran]:
    def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ran:
        steered = centrum(tmp_path)
        run_outcome = runs_contract.RunOutcome
        built: list[str] = []

        def broken_once(**fields: Any) -> runs_contract.RunOutcome:
            built.append(fields["ending"])
            if len(built) == 1:
                raise ValueError("synthetic contract failure SYN-001")
            return run_outcome(**fields)

        monkeypatch.setattr(runs_contract, "RunOutcome", broken_once)
        return steered, run_to_end(steered, dry_run=dry_run)

    return run


def _core_failed(
    centrum: Callable[[Path], AnyCentrum], *, dry_run: bool
) -> Callable[[Path, pytest.MonkeyPatch], Ran]:
    """Sam rdzeń Uruchomienia procesu rzuca wyjątkiem, więc nie oddaje wyniku: ostatnia siatka adaptera bez rdzenia."""

    def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ran:
        steered = centrum(tmp_path)
        steered.engines.fail_core = True
        return steered, run_to_end(steered, dry_run=dry_run)

    return run


QUANTITY_WARNINGS = [("warning", "NIEZNANE_URZADZENIA"), ("warning", "KOLUMNY_Z_OPISU")]
UNEXPECTED = [("stop", "BLAD_NIEOCZEKIWANY")]


@dataclass(frozen=True)
class Ending:
    run: Callable[[Path, pytest.MonkeyPatch], Ran]
    mode: str
    result: tuple[str, str, str | None]
    """Wynik, sposób zakończenia i Rodzaj Zatrzymania."""
    messages: list[tuple[str, str]]
    """Rodzaj i kod każdego Komunikatu, w kolejności karty."""
    trace: str | None = None
    """Typ wyjątku w śladzie wywołań."""
    files_unchanged: bool = field(kw_only=True)
    """Karta mówi, że pliki taty są bez zmian: podgląd albo koniec przed Zapisywaniem."""
    collective_file_prepared: bool = field(default=False, kw_only=True)
    """Wynik przygotował Plik zbiorczy okresu (Przygotowanie z zapisem bez Zatrzymania): karta pokazuje pod nim
    Uzupełnienie pliku zbiorczego."""


ENDINGS = {
    "sukces-podglad": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=True),
        "DRY-RUN",
        ("OK", "finished", None),
        [],
        files_unchanged=True,
    ),
    "sukces-zapis": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=False),
        "RUN",
        ("OK", "finished", None),
        [],
        files_unchanged=False,
    ),
    "sprawdzenie-podglad": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=True, include_unmapped=True),
        "DRY-RUN",
        ("WYMAGA_SPRAWDZENIA", "finished", None),
        [("warning", "BRAK_MAPOWANIA")],
        files_unchanged=True,
    ),
    "sprawdzenie-zapis": Ending(
        lambda tmp_path, _: _preparation(tmp_path, dry_run=False),
        "RUN",
        ("WYMAGA_SPRAWDZENIA", "finished", None),
        QUANTITY_WARNINGS,
        files_unchanged=False,
        collective_file_prepared=True,
    ),
    "dla-taty-zapis": Ending(
        _existing_worker_settlements,
        "RUN",
        ("BLAD_KRYTYCZNY", "stop", "for_tata"),
        [("stop", "FOLDER_ROZLICZEN_ISTNIEJE")],
        files_unchanged=True,
    ),
    "dla-taty-podglad": Ending(
        _missing_collective_file,
        "DRY-RUN",
        ("BLAD_KRYTYCZNY", "stop", "for_tata"),
        [("stop", "BRAK_PLIKU_ZBIORCZEGO")],
        # Zatrzymanie dla taty z przyczyną w wyjątku (``WorkbookError``) też ma ślad wywołań (#976).
        "rozliczenia.message.StopError",
        files_unchanged=True,
    ),
    "decyzja-przerwij": Ending(
        _aborted_decision,
        "RUN",
        ("BLAD_KRYTYCZNY", "declined", "declined"),
        [("stop", "PRZERWANO_NIEPELNY_OKRES")],
        files_unchanged=True,
    ),
    "do-maksa-zapis": Ending(
        _missing_collective_template,
        "RUN",
        ("BLAD_KRYTYCZNY", "stop", "for_maks"),
        [("stop", "BRAK_WZORCA")],
        files_unchanged=True,
    ),
    "wyjatek-zapis": Ending(
        _failing(settling_centrum, dry_run=False, engine=True),
        "RUN",
        ("BLAD_KRYTYCZNY", "unexpected", "for_maks"),
        UNEXPECTED,
        "RuntimeError",
        files_unchanged=True,
    ),
    "wyjatek-podglad": Ending(
        _failing(preparing_centrum, dry_run=True, engine=True),
        "DRY-RUN",
        ("BLAD_KRYTYCZNY", "unexpected", "for_maks"),
        UNEXPECTED,
        "RuntimeError",
        files_unchanged=True,
    ),
    "po-silniku-podglad": Ending(
        _failing(settling_centrum, dry_run=True, engine=False),
        "DRY-RUN",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_PLANU")],
        "ValueError",
        files_unchanged=True,
    ),
    "po-silniku-zapis": Ending(
        _failing(preparing_centrum, dry_run=False, engine=False),
        "RUN",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_PODSUMOWANIA")],
        "ValueError",
        files_unchanged=False,
    ),
    "po-silniku-adapter": Ending(
        _adapter_net(preparing_centrum, dry_run=True),
        "DRY-RUN",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_WYNIKU")],
        "ValueError",
        files_unchanged=True,
    ),
    "bez-rdzenia-zapis": Ending(
        _core_failed(settling_centrum, dry_run=False),
        "RUN",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_WYNIKU")],
        "ValueError",
        files_unchanged=False,
    ),
}


@pytest.mark.parametrize("ending", ENDINGS.values(), ids=ENDINGS.keys())
def test_kazda_droga_zakonczenia_w_obu_trybach_daje_jeden_plik_logow_a_po_ponownym_starcie_z_niego_karte_ostatniego_uruchomienia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: Ending
) -> None:
    """Logi każdej drogi końca mają wynik, sposób końca, Rodzaj Zatrzymania i Komunikaty karty, bez adresu i ścieżek, a
    Centrum po ponownym starcie pokazuje z nich kartę tego Uruchomienia taką, jaka była na żywo."""

    centrum, view = ending.run(tmp_path, monkeypatch)

    [path] = log_files(centrum)
    [record] = records(centrum)
    card = view["result"]
    assert (record["run_id"], record["process"], record["period"]) == (view["run"]["id"], view["run"]["process"], PERIOD)
    assert record["mode"] == ending.mode
    assert (record["result"], record["ending"], record["stop_kind"]) == ending.result
    assert (card["result"], card["ending"], card["stop_kind"]) == ending.result
    assert card["files_unchanged"] is ending.files_unchanged
    assert card["collective_file_prepared"] is ending.collective_file_prepared
    assert [(message["kind"], message["code"]) for message in record["messages"]] == ending.messages
    assert three_parts(record) == card_messages(view)
    assert (record["trace"] or {}).get("exception_type") == ending.trace
    text = path.read_text(encoding="utf-8")
    assert [marker for marker in ("syntetyczny adres SYN-", "OR-SYN-") if marker in text] == [], "ADRES i numer Orange"
    assert in_json(tmp_path) not in text and in_json(tmp_path.resolve()) not in text

    centrum.restart()

    current = centrum.client.get("/api/runs/current").json()
    assert current == {"state": "idle", "previous": restored(view, record["started_at"])}
    assert first_view(centrum.client) == current
    assert in_json(tmp_path) not in json.dumps(current), "same nazwy plików, bez ścieżek"


def test_logi_maja_etapy_i_przetworzenia_szablonow_pracownika_z_wynikiem_wierszami_czasem_i_godzina(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)

    view = run_to_end(centrum, dry_run=False)

    [path] = log_files(centrum)
    [record] = records(centrum)
    assert record.keys() == KEYS
    assert (record["schema_version"], record["diagnosis"], record["trace"]) == (3, None, None)
    assert record["intermax_entries"] is None, "Wpisy INTERMAX ma tylko Uporządkowanie INTERMAX"
    assert record["tool"] == {"wydanie": None, "commit": TOOL_COMMIT}
    assert [{key: phase[key] for key in ("phase", "state", "duration_ms")} for phase in record["phases"]] == view[
        "progress"
    ]["phases"]
    *before_saving, saving = record["phases"]
    steps = [record["started_at"]]
    for phase in before_saving:
        steps += [phase["started_at"], phase["ended_at"]]
    steps.append(saving["started_at"])
    for template in record["templates"]:
        steps += [template["started_at"], template["ended_at"]]
    steps += [saving["ended_at"], record["ended_at"]]
    moments = [utc(moment) for moment in steps]
    assert moments == sorted(moments), "godziny etapów, a w Zapisywaniu Szablonów pracownika, w kolejności kroków"
    assert [phase["state"] for phase in record["phases"]] == ["completed"] * 4
    assert [(template["wykonawca"], template["outcome"], template["rows"]) for template in record["templates"]] == [
        ("Adrian Testowy", "ZAPISANO", 2),
        ("Darek Fikcyjny", "ZAPISANO", 1),
        ("Kamil Syntetyczny", "PUSTY_SZABLON", 0),
    ]
    assert all(isinstance(template["duration_ms"], int) and template["duration_ms"] >= 0 for template in record["templates"])
    assert record["summary"] == view["result"]["summary"]
    assert (record["issue_count"], record["technical_notes"]) == (0, [])
    assert isinstance(record["duration_ms"], int)
    assert record["started_at"] <= record["ended_at"]
    assert re.fullmatch(rf"\d{{8}}T\d{{6}}Z-settlement-{view['run']['id']}\.json", path.name)


def test_logi_przebiegu_rozliczen_maja_liczbe_ilosci_tylko_dla_inea_w_kazdej_kolumnie_w_obu_trybach(
    tmp_path: Path,
) -> None:
    centrum = settling_centrum(tmp_path)
    rows: list[dict[str, CellValue]] = [
        {"D": "gniazdo", "AP": 1},
        {"D": "zyxel technicolor arion", "AK": 2},
        {"D": "Technicolor, globo lub cam", "AK": 1},
        {"D": "globo", "AK": 1, "AP": 1},
    ]
    write_quantity_source(centrum.collective_file, rows)

    views = [run_to_end(centrum, dry_run=dry_run) for dry_run in (True, False)]

    assert [view["result"]["result"] for view in views] == ["OK", "OK"]
    assert [record["inea_only_cleared"] for record in records(centrum)] == [{"AP": 1, "AK": 2}] * 2


def test_logi_przygotowania_nie_maja_dodatkow_innych_procesow(tmp_path: Path) -> None:
    """Przygotowanie nie ma własnych dodatków Logów, więc każde pole dodatku innego procesu to ``null``: puste
    ``efenix_orders`` karta z Logów liczyłaby jako zlecenia Uruchomienia (przegląd #1164 r1)."""

    centrum, _ = _preparation(tmp_path, dry_run=True)

    [record] = records(centrum)
    assert {field: record[field] for field in ProcessLogs.model_fields} == dict.fromkeys(ProcessLogs.model_fields)


def test_karta_wraca_z_logow_sprzed_liczby_ilosci_tylko_dla_inea(tmp_path: Path) -> None:
    centrum, live = _settlement(tmp_path, dry_run=False)
    [path] = log_files(centrum)
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["inea_only_cleared"]
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    centrum.restart()

    current = centrum.client.get("/api/runs/current").json()
    assert current == {"state": "idle", "previous": restored(live, record["started_at"])}


VERDICT_FAULT_WORDS: Final = {
    "missing": VerdictFault.MISSING,
    "letter_yes": VerdictFault.LETTER_YES,
    "letter_no": VerdictFault.LETTER_NO,
    "word_yes": VerdictFault.WORD_YES,
    "word_no": VerdictFault.WORD_NO,
}
SUBJECT_FAULT_WORDS: Final = {
    "no_date": SubjectFault.NO_DATE,
    "other_text": SubjectFault.OTHER_TEXT,
    "no_year": SubjectFault.NO_YEAR,
    "date_form": SubjectFault.DATE_FORM,
    "separator": SubjectFault.SEPARATOR,
    "year_digits": SubjectFault.YEAR_DIGITS,
    "not_a_day": SubjectFault.NOT_A_DAY,
}
ADD_BAR_WORDS: Final = {
    "in_intermax": AddBar.IN_INTERMAX,
    "before_window": AddBar.BEFORE_WINDOW,
    "form": AddBar.FORM,
    "mistaken_subject": AddBar.MISTAKEN_SUBJECT,
    "not_ordered": AddBar.NOT_ORDERED,
}
MOVE_BAR_WORDS: Final = {
    "not_ordered": MoveBar.NOT_ORDERED,
    "other_sheet": MoveBar.OTHER_SHEET,
    "closed_target": MoveBar.CLOSED_TARGET,
    "closed_source": MoveBar.CLOSED_SOURCE,
    "after_today": MoveBar.AFTER_TODAY,
}
COLUMN_WORDS: Final = {"SKUTECZNE": ReportColumn.SUCCESSFUL, "CZYNNOŚCI ZREALIZOWANE": ReportColumn.COMPLETED}


def _entering_words(entering: dict[str, Any]) -> list[object]:
    """Powody i kolumny Logów Wpisania raportów po kolei: Wpisy maila, maile z nieczytelnym tematem, problemy, zmiany."""

    [report, *unreadable] = entering["mails"]
    return [
        *(entry["fault"] for entry in report["entries"]),
        *(mail["fault"] for mail in unreadable),
        *(problem["bar"] for problem in entering["problems"]),
        *(change["column"] for change in entering["changes"]),
    ]


def test_logi_wpisania_raportow_z_kazdym_slowem_powodu_i_kolumny_z_wczesniejszych_wydan_czytaja_sie_dalej() -> None:
    """Plik Logów Wpisania raportów z każdym słowem powodu i kolumny, które zapisały wcześniejsze Wydania, czyta się do
    tego samego powodu i tej samej kolumny, a zapisuje z powrotem tymi samymi słowami: te pliki czytają karta z Logów,
    Historia i odtworzenie. ``not_ordered`` przy ``unknown_number`` to powód, dla którego Centrum nie dopisało
    zlecenia, a przy ``refused_move`` powód odmowy Przeniesienia. Słowo spoza powodów odmowy Przeniesienia przy
    ``refused_move`` (``form``) się nie czyta, bo żadne Wydanie go tam nie zapisało."""

    day, arrived, worker = "2026-11-09", "2026-11-09T18:00:00Z", "jan.testowy"
    entering = {
        "today": day,
        "rollout_before": None,
        "rollout": day,
        "skipped": 0,
        "mails": [
            {
                "kind": "report",
                "mail": "a" * 16,
                "arrived": arrived,
                "worker": worker,
                "day": day,
                "entries": [
                    {"number": "40000001", "verdict": None, "fault": word, "activities": ""} for word in VERDICT_FAULT_WORDS
                ],
            },
            *(
                {"kind": "unreadable", "mail": "b" * 16, "arrived": arrived, "worker": worker, "fault": word}
                for word in SUBJECT_FAULT_WORDS
            ),
        ],
        "problems": [
            {"kind": kind, "worker": worker, "day": day, "number": "40000001", "bar": word}
            for kind, words in (("unknown_number", ADD_BAR_WORDS), ("refused_move", MOVE_BAR_WORDS))
            for word in words
        ],
        "changes": [{"sheet": "Zlecenia", "row": 2, "column": word, "value": "tak"} for word in COLUMN_WORDS],
        "memory_before": [],
        "written": None,
    }
    logs = {
        "run_id": "c" * 32,
        "process": "report_entering",
        "mode": "RUN",
        "period": "10_16_11_2026",
        "started_at": arrived,
        "schema_version": 3,
        "ended_at": arrived,
        "duration_ms": 10,
        "tool": {"wydanie": None, "commit": TOOL_COMMIT},
        "result": "OK",
        "ending": "finished",
        "stop_kind": None,
        "issue_count": 0,
        "messages": [],
        "technical_notes": [],
        "summary": None,
        "phases": [],
        "templates": [],
        "report_entering": entering,
        "environment": {"system": "Windows-11", "python": "3.13.15", "files": None},
        "trace": None,
        "diagnosis": None,
    }

    record = RunLog.model_validate_json(json.dumps(logs, ensure_ascii=False))

    assert _entering_words(record.model_dump()["report_entering"]) == [
        *VERDICT_FAULT_WORDS.values(),
        *SUBJECT_FAULT_WORDS.values(),
        *ADD_BAR_WORDS.values(),
        *MOVE_BAR_WORDS.values(),
        *COLUMN_WORDS.values(),
    ]
    assert _entering_words(json.loads(record.text)["report_entering"]) == _entering_words(entering)
    refused_form = {"kind": "refused_move", "worker": worker, "day": day, "number": "40000001", "bar": "form"}
    with pytest.raises(ValidationError, match=r"refused_move\.bar"):
        RunLog.model_validate_json(
            json.dumps({**logs, "report_entering": {**entering, "problems": [refused_form]}}, ensure_ascii=False)
        )


def test_logi_po_bledzie_samego_adaptera_maja_czas_liczbe_problemow_i_przetworzenia_szablonow_z_rdzenia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, view = _adapter_net(settling_centrum, dry_run=False)(tmp_path, monkeypatch)

    [record] = records(centrum)
    assert (record["ending"], view["result"]["ending"]) == ("after_engine", "after_engine")
    assert isinstance(record["duration_ms"], int)
    assert record["issue_count"] == 0
    assert [(template["wykonawca"], template["outcome"], template["rows"]) for template in record["templates"]] == [
        ("Adrian Testowy", "ZAPISANO", 2),
        ("Darek Fikcyjny", "ZAPISANO", 1),
        ("Kamil Syntetyczny", "PUSTY_SZABLON", 0),
    ]
    assert record["summary"] is None


def test_powtorka_zatrzymania_dla_taty_ma_w_logach_rodzaj_powtorka(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.worker_settlements.mkdir()

    first = run_to_end(centrum, dry_run=False)
    second = run_to_end(centrum, dry_run=False)

    by_run = {record["run_id"]: record["stop_kind"] for record in records(centrum)}
    assert by_run == {first["run"]["id"]: "for_tata", second["run"]["id"]: "repeated"}


def test_srodowisko_ma_system_python_i_pliki_procesu_z_rozmiarem_i_onedrive(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    onedrive = centrum.surroundings.onedrive
    assert onedrive is not None
    onedrive.online_only.add(centrum.collective_file)

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    environment = record["environment"]
    assert environment["system"] and environment["python"]
    assert environment["files"] == [
        {
            "name": centrum.configuration.worker_template.name,
            "size": centrum.configuration.worker_template.stat().st_size,
            "online_only": False,
        },
        {"name": PeriodFolder.from_collective_file(centrum.collective_file).internal_settlement.name, "size": None, "online_only": None},
        {"name": SOURCE_NAME, "size": centrum.collective_file.stat().st_size, "online_only": True},
    ]


def test_zmiana_folderow_w_trakcie_uruchomienia_zostawia_w_wyniku_i_logach_pliki_z_jego_startu(tmp_path: Path) -> None:
    """Uruchomienie kończy na Ustawieniach Centrum ze swojego startu (ADR 0032): Rejestr zleceń i folder okresów
    zmienione w trakcie nie zmieniają ani jego wyniku, ani plików procesu w jego Logach."""

    centrum = preparing_centrum(tmp_path)
    register = centrum.fixture.register_path
    elsewhere = tmp_path / "Inny folder"
    centrum.engines.release = threading.Event()
    started = centrum.start(dry_run=True)
    assert centrum.engines.held.wait(STOP_S)
    changed = centrum.client.put(
        "/api/settings/folders",
        json={"order_register": str(elsewhere / "ZLECENIA INNE.xlsx"), "periods_directory": str(elsewhere)},
    )
    centrum.engines.release.set()
    view = finished_view(centrum.client)

    assert (started.status_code, changed.status_code, view["result"]["result"]) == (200, 200, "OK")
    [record] = records(centrum)
    assert register.name in [file["name"] for file in record["environment"]["files"]]


def test_pliki_procesu_ktorych_nie_da_sie_wyliczyc_daja_logi_bez_plikow_bez_nieoczekiwanego_wyjatku_w_dzienniku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = settling_centrum(tmp_path)

    def inaccessible(*_: object, **__: object) -> list[Path]:
        raise PeriodFolderInaccessible(centrum.period_directory)

    monkeypatch.setattr(app, "files_of_process", inaccessible)

    view = run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert record["environment"]["files"] is None
    assert (record["result"], view["result"]["result"]) == ("OK", "OK")
    assert "nieoczekiwany-wyjatek" not in centrum.log_path.read_text(encoding="utf-8")


def test_logi_przebiegu_rozliczen_nie_maja_adresu_numeru_orange_ani_pelnych_sciezek(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    unmapped = {**MARKED, "H": "ZNACZNIK-WYKONAWCA"}
    without_worker = {**MARKED, "H": None}
    write_quantity_source(centrum.collective_file, [MARKED, unmapped, without_worker])

    preview = run_to_end(centrum, dry_run=True)
    stopped = run_to_end(centrum, dry_run=False)
    write_quantity_source(centrum.collective_file, [MARKED])
    written = run_to_end(centrum, dry_run=False)

    assert [view["result"]["result"] for view in (preview, stopped, written)] == [
        "WYMAGA_SPRAWDZENIA",
        "BLAD_KRYTYCZNY",
        "OK",
    ]
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 3))
    sent = in_box(box)
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    assert len(texts) == 3
    texts += sent
    naming = settlement_messages.unmapped_worker(centrum.collective_file, ["ZNACZNIK-WYKONAWCA"]).what
    assert any(form in text for form in (naming, json.dumps(naming)[1:-1]) for text in texts), "Komunikat z Wykonawcą"
    forbidden = ("ZNACZNIK-ADRES", "ZNACZNIK-NUMER-UMOWY", in_json(tmp_path), in_json(tmp_path.resolve()))
    assert [marker for marker in forbidden if any(marker in text for text in texts)] == []
    assert sum("Adrian Testowy" in text for text in texts) == 4, "Wykonawca z Konfiguracji w obu wynikach z planem"


def test_diagnoza_w_logach_nie_ma_adresu_numeru_orange_ani_pelnych_sciezek(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    write_quantity_source(centrum.collective_file, [MARKED, {**MARKED, "H": "ZNACZNIK-WYKONAWCA"}])
    run_id = stopped_for_maks(centrum)
    centrum.collective_file.with_name(f"~${centrum.collective_file.name}").write_bytes(b"")

    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")

    assert response.status_code == 200, response.json()
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: len(fake.edited) == 1), "Diagnoza zmienia komentarz Logów"
    [record] = records(centrum)
    assert "failed" in [check["state"] for check in record["diagnosis"]["checks"]], "Diagnoza z przyczyną w pliku Logów"
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)] + in_box(box)
    forbidden = ("ZNACZNIK-ADRES", "ZNACZNIK-NUMER-UMOWY", in_json(tmp_path), in_json(tmp_path.resolve()))
    assert [marker for marker in forbidden if any(marker in text for text in texts)] == []


# Syntetyczne wartości kolumn, które nigdy nie wychodzą z komputera taty (ADR 0025), i wolny tekst z telefonem i ulicą.
ADDRESS_VALUE = "Syntetyczna Bursztynowa 14/2 Poznań"
ORANGE_VALUE = "4801234567"
PHONE = "600 123 456"
STREET = "ul. Kwiatowa 5"


def test_adres_i_numer_orange_cytowane_przez_komunikat_nie_wychodza_w_logach_ani_zgloszeniu_a_logi_maja_uwage(
    tmp_path: Path,
) -> None:
    rows = default_register_rows()
    rows[2] = {**(rows[2] or {}), "ADRES": ADDRESS_VALUE}
    rows[4] = {**(rows[4] or {}), "NUMER UMOWY": ORANGE_VALUE}
    rows[7] = {**(rows[7] or {}), "SKUTECZNE": f"{ADDRESS_VALUE.upper()}  {ORANGE_VALUE} tel. {PHONE}, {STREET}"}
    centrum = preparing_centrum(tmp_path, rows)
    write_report_key(ToolDirectory(tmp_path))

    first = run_to_end(centrum, dry_run=True)
    second = run_to_end(centrum, dry_run=True)
    diagnosis = centrum.client.post(f"/api/runs/{second['run']['id']}/diagnosis")
    sent = centrum.client.post(f"/api/runs/{second['run']['id']}/report")

    assert [view["result"]["stop_kind"] for view in (first, second)] == ["for_tata", "repeated"]
    assert (diagnosis.status_code, sent.json()) == (200, {"state": "sent"})
    box = centrum.surroundings.report_box
    # Logi obu Uruchomień, a tekst drugich to Logi po Diagnozie: Diagnoza zmienia ich komentarz (#849) albo, gdy przyszła
    # przed wysyłką, zastępuje je w kolejce, więc idą od razu z nią.
    assert box.wait_until(lambda fake: logs_arrived(fake, 2) and "- Diagnoza: " in logs_comments(fake)[1])
    assert ADDRESS_VALUE.upper() in json.dumps(card_messages(second), ensure_ascii=False), "karta taty cytuje komórkę"
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    texts += [part for issue in [*box.issues, *box.background_issues] for part in (issue.title, issue.body, *issue.comments)]
    leaked = (ADDRESS_VALUE, ADDRESS_VALUE.upper(), ORANGE_VALUE, PHONE, STREET)
    assert [value for value in leaked if any(value in text for text in texts)] == []
    quoted = "„[adres]  [numer Orange] tel. [telefon], [ulica]”"
    [report] = box.sent
    assert quoted in report.title + report.body
    assert "- Reguła danych: zamaskowano wartość kolumny ADRES w: treść Zgłoszenia." in report.body
    for record in records(centrum):
        [message] = record["messages"]
        assert quoted in message["where"]
        assert record["technical_notes"] == [
            "Reguła danych: zamaskowano wartość kolumny ADRES w: messages[0].where.",
            "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: messages[0].where.",
        ]
        # SKUTECZNE z adresem i numerem Orange to także komórka czwartego przeczytanego wiersza Rejestru w Kopii wejścia.
        assert record["input_copy_notes"] == [
            "Reguła danych: zamaskowano wartość kolumny ADRES w: input_copy[0].sheets[0].rows[3].cells.[…].",
            "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: input_copy[0].sheets[0].rows[3].cells.[…].",
        ]


# --- Położenia wklejonego wiersza w Rejestrze zleceń (#918) ----------------------------------------------------------
# Przygotowanie czyta Rejestr po nagłówkach, a wiersz wklejony z aplikacji firmowej może stać przesunięty o dwie
# kolumny w lewo (ADR 0019), w całości albo poza częścią, którą tata postawił z powrotem na miejsce. Wiersz próbny niesie
# syntetyczny adres i numer Orange w swoich kolumnach ``ADRES`` i ``NUMER UMOWY``, gdziekolwiek stoją w pliku, a tata
# cytuje je potem w Uwadze. Każdy wiersz ma jedno położenie (decyzja Maksa z 5.11.2026, ADR 0025): pierwszy wiersz bloku
# wklejenia przesunięty o dwie kolumny w lewo, każdy inny pod nagłówkiem. W obu jest pierwszy wiersz bloku, którego
# przesunięcia nie widać (bez daty z godziną dwie kolumny przed DATA albo z nią także pod DATA), bez uwagi, i inny wiersz
# z datą z godziną dwie kolumny przed DATA (ślad przesunięcia), z uwagą w Logach. ``NUMER ZL.`` uporządkowanych wierszy,
# który w przesuniętym wierszu stałby tam, gdzie numer Orange, wychodzi bez maski. Pierwszy wiersz bloku z widocznym
# przesunięciem, który nie jest przesunięty w całości, i wiersz na miejscu z datą z godziną w kolumnie A pod wpisem taty
# to ryzyko przyjęte przez Maksa (``KNOWN``).
PROBE_ADDRESS = "Przemiatana Wrzosowa 12 Kórnik"
PROBE_ORANGE = "4809876543"
ABOVE_ORDERED = 8
"""Pusty wiersz Rejestru między zleceniami z 9 i 12 września: wklejony tu wiersz stoi nad uporządkowanymi w okresie."""
ORDER_NUMBERS = {2: "ZL-SYN-001", 4: "ZL-SYN-002", 6: "ZL-SYN-003", 9: "ZL-SYN-004", 11: "ZL-SYN-005", 13: "ZL-SYN-006"}
"""``NUMER ZL.`` (kolumna I) uporządkowanych wierszy Rejestru, które Przygotowanie okresu czyta."""


def _register_probe(when: object = datetime(2026, 9, 10, 11), orange: object = PROBE_ORANGE) -> dict[str, object]:
    probe = {"DATA GODZ. POCZ.": when, "ADRES": PROBE_ADDRESS, "NUMER UMOWY": orange}
    return {**register_order(77, datetime(2026, 9, 10, 11)), **probe}


def _above_ordered(probe: dict[str, object] | None = None, in_place_from: str | None = None) -> Callable[[Path], object]:
    row = _register_probe() if probe is None else probe
    return lambda register: paste_raw_orders(register, [row], first=ABOVE_ORDERED, in_place_from=in_place_from)


def _worker_typed_by_tata(register: Path) -> None:
    """Przesunięty wiersz bez Wykonawcy z aplikacji, a tata wpisał Wykonawcę pod nagłówkiem ``WYKONAWCA`` czcionką
    Rejestru (Calibri 8): ta komórka nie czyni wiersza uporządkowanym, tak jak w Uporządkowaniu."""

    paste_raw_orders(register, [{**_register_probe(), "WYKONAWCA": None}], first=ABOVE_ORDERED)
    type_into_register(register, ABOVE_ORDERED, "WYKONAWCA", "adrian.testowy")


def _after_period(in_place_from: str | None = None) -> Callable[[Path], object]:
    """Wklejenie na dole Rejestru z dnia po okresie: Przygotowanie go nie zatrzymuje, ale czyta, bo leży w zakresie
    dat okresu z dniem zapasu."""

    later = [register_order(90 + hour, datetime(2026, 9, 15, 12 + hour)) for hour in range(2)]
    pasted = [_register_probe(datetime(2026, 9, 15, 10)), *later]
    return lambda register: paste_raw_orders(register, pasted, in_place_from=in_place_from)


def _second_paste(when: object = datetime(2026, 9, 10, 11)) -> Callable[[Path], object]:
    """Dwa wklejenia nad uporządkowanymi w okresie bez wiersza między nimi: pierwszy wiersz drugiego wklejenia (wiersz
    próbny) stoi przesunięty w środku bloku, a dwie kolumny przed ``DATA GODZ. POCZ.`` ma swoją datę ``when``."""

    def paste(register: Path) -> None:
        paste_raw_orders(register, [register_order(90, datetime(2026, 9, 10, 9))], first=ABOVE_ORDERED - 1)
        paste_raw_orders(register, [_register_probe(when)], first=ABOVE_ORDERED)

    return paste


def _date_in_column_a(register: Path, row: int, when: datetime | None) -> None:
    """Data z godziną ``when`` w kolumnie A (bez nagłówka, dwie kolumny przed ``DATA GODZ. POCZ.``) wiersza ``row``,
    np. wpisana ręcznie; ``None``: kolumna A bez zmian."""

    if when is None:
        return
    workbook = load_workbook(register)
    try:
        workbook["ZLECENIA"].cell(row, 1).value = when
        workbook.save(register)
    finally:
        workbook.close()


def _typed_into_first(when: object = datetime(2026, 9, 10, 11), column_a: datetime | None = None) -> Callable[[Path], object]:
    """Przesunięty pierwszy wiersz wklejenia nad uporządkowanymi z ``SKUTECZNE`` wpisanym przez tatę w Calibri 8, a pod
    nim wiersz próbny na miejscu z ``when`` pod ``DATA GODZ. POCZ.`` i ``column_a`` w kolumnie A (sondy R1 z przeglądu
    #984 r1, RN1 i RN2 z r2, RC1 i RC2 z r3)."""

    def paste(register: Path) -> None:
        rows = [register_order(90, datetime(2026, 9, 10, 9)), _register_probe(when)]
        paste_raw_orders(register, rows, first=ABOVE_ORDERED - 1)
        _date_in_column_a(register, ABOVE_ORDERED, column_a)
        type_into_register(register, ABOVE_ORDERED - 1, "SKUTECZNE", "tak")

    return paste


def _typed_into_middle(
    when: object = datetime(2026, 9, 15, 12), column_a: datetime | None = None, header: str = "MIASTO", typed: str = "POZNAŃ"
) -> Callable[[Path], object]:
    """Cztery wklejone wiersze na dole po okresie, tata wpisuje ``typed`` pod ``header`` drugiego w Calibri 8, a trzeci,
    wiersz próbny z ``when`` pod ``DATA GODZ. POCZ.`` i ``column_a`` w kolumnie A, cytuje w ``CZYNNOŚCI ZREALIZOWANE``
    swój adres i numer Orange (sonda R3 z przeglądu #984 r1, RN3 z r2, RC3 i RC4 z r3)."""

    def paste(register: Path) -> None:
        quoted = {"CZYNNOŚCI ZREALIZOWANE": f"montaż {PROBE_ADDRESS} umowa {PROBE_ORANGE}"}
        rows = [
            register_order(91, datetime(2026, 9, 15, 10)),
            register_order(92, datetime(2026, 9, 15, 11)),
            {**_register_probe(when), **quoted},
            register_order(93, datetime(2026, 9, 15, 13)),
        ]
        first = paste_raw_orders(register, rows)
        _date_in_column_a(register, first + 2, column_a)
        type_into_register(register, first + 1, header, typed)

    return paste


REGISTER_POSITIONS: dict[str, tuple[Callable[[Path], object], str | None]] = {
    "przesuniety_z_data_z_godzina_w_A": (_above_ordered(), "WIERSZ_BEZ_DATY"),
    "przesuniety_z_data_jako_tekst": (_above_ordered(_register_probe("10.09.2026 11:00")), "WIERSZ_BEZ_DATY"),
    "przesuniety_bez_daty": (_above_ordered(_register_probe(None)), "WIERSZ_BEZ_DATY"),
    "przesuniety_z_numerem_orange_jako_liczba": (_above_ordered(_register_probe(orange=4809876543)), "WIERSZ_BEZ_DATY"),
    "na_miejscu_od_adres": (_above_ordered(in_place_from="ADRES"), "WIERSZ_BEZ_DATY"),
    "na_miejscu_od_czynnosci": (_above_ordered(in_place_from="CZYNNOŚCI"), "WIERSZ_BEZ_DATY"),
    "na_miejscu_od_numer_zl": (_above_ordered(in_place_from="NUMER ZL."), "WIERSZ_BEZ_DATY"),
    "na_miejscu_od_skuteczne": (_above_ordered(in_place_from="SKUTECZNE"), "WIERSZ_BEZ_DATY"),
    "przesuniety_z_wykonawca_wpisanym_przez_tate": (_worker_typed_by_tata, "WIERSZ_BEZ_DATY"),
    "nieprzesuniety": (_above_ordered(in_place_from="DATA GODZ. POCZ."), None),
    "pierwszy_wiersz_wklejenia_po_okresie": (_after_period(), None),
    "pierwszy_wiersz_wklejenia_po_okresie_na_miejscu_od_czynnosci": (_after_period(in_place_from="CZYNNOŚCI"), None),
    "pierwszy_wiersz_wklejenia_po_okresie_na_miejscu_od_skuteczne": (_after_period(in_place_from="SKUTECZNE"), None),
    "przesuniety_pierwszy_wiersz_drugiego_wklejenia": (_second_paste(), "WIERSZ_BEZ_DATY"),
    "przesuniety_pierwszy_wiersz_drugiego_wklejenia_z_data_jako_tekst": (_second_paste("10.09.2026 11:00"), "WIERSZ_BEZ_DATY"),
    # wiersz z wyglądem z aplikacji na miejscu w wierszu 2: odczyt okresu zaczyna się tu od góry arkusza, więc wiersz
    # zaczyna blok, a z datą z godziną pod DATA jego przesunięcia nie widać, więc pamięć zna go w obu położeniach (bez
    # uwagi)
    "nieprzesuniety_na_gorze_odczytu": (
        lambda register: paste_raw_orders(
            register,
            [{**register_order(1, datetime(2026, 9, 7, 15)), "ADRES": PROBE_ADDRESS, "NUMER UMOWY": PROBE_ORANGE}],
            first=2,
            in_place_from="DATA GODZ. POCZ.",
        ),
        None,
    ),
    # wpis taty w Calibri 8 w wierszu wklejenia nad wierszem próbnym: pierwszy wiersz bloku z kroju (bez zmian) stoi na
    # miejscu bez daty z godziną w kolumnie A, z datą z godziną pod DATA, z datą tekstem albo bez daty, więc jego
    # przesunięcia nie widać, a pamięć zna go w obu położeniach
    "wpis_taty_w_przesunietym_pierwszym_wierszu": (_typed_into_first(), "WIERSZ_BEZ_DATY"),
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_z_data_jako_tekst": (
        _typed_into_first("10.09.2026 11:00"),
        "WIERSZ_BEZ_DATY",
    ),
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_bez_daty": (_typed_into_first(None), "WIERSZ_BEZ_DATY"),
    "wpis_taty_w_drugim_wierszu_wklejenia_po_okresie": (_typed_into_middle(), None),
    # wiersz próbny na miejscu z datą z godziną w kolumnie A, a bez niej pod DATA: przesunięcie widać (klasa C)
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_z_data_jako_tekst_i_w_kolumnie_a": (
        _typed_into_first("10.09.2026 11:00", datetime(2026, 9, 10, 11)),
        "WIERSZ_BEZ_DATY",
    ),
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_bez_daty_z_data_w_kolumnie_a": (
        _typed_into_first(None, datetime(2026, 9, 10, 11)),
        "WIERSZ_BEZ_DATY",
    ),
    "wpis_taty_w_drugim_wierszu_wklejenia_po_okresie_wiersz_probny_z_data_jako_tekst_i_w_kolumnie_a": (
        _typed_into_middle("15.09.2026 12:00", datetime(2026, 9, 15, 12)),
        None,
    ),
}
REGISTER_KNOWN = {
    name: "pierwszy_na_miejscu"
    for name in (
        "na_miejscu_od_adres",
        "na_miejscu_od_czynnosci",
        "na_miejscu_od_numer_zl",
        "pierwszy_wiersz_wklejenia_po_okresie_na_miejscu_od_czynnosci",
    )
} | {
    "przesuniety_pierwszy_wiersz_drugiego_wklejenia_z_data_jako_tekst": "przesuniety_inny_bez_sladu",
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_z_data_jako_tekst_i_w_kolumnie_a": "na_miejscu_z_data_w_a",
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_bez_daty_z_data_w_kolumnie_a": "na_miejscu_z_data_w_a",
    "wpis_taty_w_drugim_wierszu_wklejenia_po_okresie_wiersz_probny_z_data_jako_tekst_i_w_kolumnie_a": "na_miejscu_z_data_w_a",
}
"""Położenia poza faktem domeny bez śladu przesunięcia: pierwszy wiersz bloku z widocznym przesunięciem (data z godziną
dwie kolumny przed ``DATA GODZ. POCZ.``, pod nią nie) nie jest przesunięty w całości (od ``ADRES``, ``CZYNNOŚCI`` albo
``NUMER ZL.`` na miejscu) albo przesunięty jest inny wiersz, z datą tekstem; ryzyko przyjęte przez Maksa
(``tests/fixtures/fakt_domeny.py``). Do tego klasa C: fakt zachodzi, a wiersz próbny na miejscu pod wpisem taty ma datę z
godziną w kolumnie A i bez niej pod ``DATA GODZ. POCZ.``."""
REGISTER_TRACED = {
    "przesuniety_pierwszy_wiersz_drugiego_wklejenia",
    "wpis_taty_w_przesunietym_pierwszym_wierszu",
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_z_data_jako_tekst",
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_bez_daty",
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_z_data_jako_tekst_i_w_kolumnie_a",
    "wpis_taty_w_przesunietym_pierwszym_wierszu_wiersz_probny_bez_daty_z_data_w_kolumnie_a",
}
"""Położenia z wierszem ze śladem przesunięcia, który nie jest pierwszym wierszem bloku: Logi mają o nim uwagę. Przy wpisie
taty w Calibri 8 w przesuniętym pierwszym wierszu to fałszywa uwaga o nim (znana granica sygnału, ADR 0025)."""
REGISTER_IN_PLACE_FIRST = {"nieprzesuniety_na_gorze_odczytu": 2}
"""Położenia, w których wiersz próbny w miejscu wiersza uporządkowanego zaczyna blok, a stoi na miejscu: pamięć zna go w
obu położeniach, bez uwagi, więc jego ``NUMER ZL.`` jest możliwym numerem Orange."""


@pytest.mark.parametrize(
    ("name", "position"),
    [
        pytest.param(name, position, id=name, marks=known(REGISTER_KNOWN.get(name)))
        for name, position in REGISTER_POSITIONS.items()
    ],
)
def test_adres_i_numer_orange_wklejonego_wiersza_rejestru_nie_wychodza_z_przygotowania_w_zadnym_polozeniu(
    tmp_path: Path, name: str, position: tuple[Callable[[Path], object], str | None]
) -> None:
    """Podgląd Przygotowania na Rejestrze z wierszem próbnym w każdym położeniu: adres i numer Orange nie wychodzą do
    pliku Logów, do Skrzynki Zgłoszeń ani w Uwadze taty, a ``NUMER ZL.`` uporządkowanych wierszy jest w Kopii wejścia
    bez maski. Wiersz ze śladem przesunięcia poza pierwszym wierszem bloku ma uwagę w Logach, że fakt domeny jest
    złamany. Podgląd kończy się Zatrzymaniem na wierszu bez daty pod ``DATA GODZ. POCZ.`` albo bez Zatrzymania."""

    paste, stop = position
    centrum = preparing_centrum(tmp_path)
    paste(centrum.fixture.register_path)
    write_report_key(ToolDirectory(tmp_path))

    run_to_end(centrum, dry_run=True)
    note = {"title": "Pytanie", "body": f"Klient {PROBE_ADDRESS}, umowa {PROBE_ORANGE}"}
    draft = centrum.client.post("/api/dad-notes/draft", json=note)

    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    [record] = records(centrum)
    stops = [message["code"] for message in record["messages"] if message["kind"] == "stop"]
    assert stops == ([] if stop is None else [stop])
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)] + in_box(box) + [draft.json()["body"]]
    assert [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if any(value in text for text in texts)] == []
    [copied] = record["input_copy"]
    [sheet] = copied["sheets"]
    ordered = {row: number for row, number in ORDER_NUMBERS.items() if row != REGISTER_IN_PLACE_FIRST.get(name)}
    assert {row["row"]: row["cells"]["I"] for row in sheet["rows"] if row["row"] in ordered} == ordered
    broken = [note for note in record["input_copy_notes"] if note.startswith("Fakt domeny złamany: wiersz ")]
    assert len(broken) == (name in REGISTER_TRACED), record["input_copy_notes"]


REGISTER_COPY_POSITIONS: dict[str, tuple[Callable[[Path], object], int, bool]] = {
    # przesunięcie widać: pamięć zna wiersz tylko przesuniętego, więc C i I to jego ADRES i NUMER UMOWY
    "przesuniety_pierwszy_wiersz_nad_uporzadkowanymi": (_above_ordered(), ABOVE_ORDERED, False),
    # na miejscu na górze odczytu okresu z datą z godziną pod DATA: pierwszy wiersz bloku z siatki, w obu położeniach
    "pierwszy_wiersz_na_miejscu_na_gorze_odczytu": (
        lambda register: paste_raw_orders(register, [_register_probe(datetime(2026, 9, 8, 9))], first=2, in_place_from="DATA GODZ. POCZ."),
        2,
        True,
    ),
}
"""Pierwszy wiersz bloku w Odczycie danych Przygotowania: wklejenie, numer wiersza próbnego i czy jest z siatki."""


@pytest.mark.parametrize(("paste", "row", "uncertain"), REGISTER_COPY_POSITIONS.values(), ids=REGISTER_COPY_POSITIONS.keys())
def test_kopia_przygotowania_nie_ma_komorek_pierwszego_wiersza_bloku_ktore_w_jego_polozeniu_stoja_pod_zakazana_kolumna(
    tmp_path: Path, paste: Callable[[Path], object], row: int, uncertain: bool
) -> None:
    """Kopia wejścia Przygotowania ma wiersz Rejestru według reguły komórki z ADR 0025, tej samej co w Uporządkowaniu
    INTERMAX: komórka, która w którymś położeniu wiersza stoi pod ``ADRES`` albo ``NUMER UMOWY``, nie jest w Kopii, a
    wiersz z siatki jest w ``uncertain_rows`` z datą z godziną spod ``DATA GODZ. POCZ.``. Kolumny C i I stoją dwie
    kolumny przed ``ADRES`` (E) i ``NUMER UMOWY`` (K). ``SKUTECZNE`` (L) wiersza z siatki w położeniu przesuniętym
    stoi pod ``ZWROT`` (N), kolumną wklejenia, więc zostaje."""

    centrum = preparing_centrum(tmp_path)
    paste(centrum.fixture.register_path)

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    [copied] = record["input_copy"]
    [sheet] = copied["sheets"]
    [cells] = [found["cells"] for found in sheet["rows"] if found["row"] == row]
    assert sorted({"C", "I"} & cells.keys()) == (["C"] if uncertain else [])
    assert sheet["uncertain_rows"] == ([row] if uncertain else [])
    if uncertain:
        assert (cells["C"], cells["L"]) == (moment("2026-09-08T09:00:00"), "tak")


def test_wiersz_starszego_ukladu_rejestru_z_wykonawca_w_calibri_8_zaczyna_blok_pod_uporzadkowanymi(tmp_path: Path) -> None:
    """Starszy układ Rejestru (bez ``AKCJE`` i ``UWAGI``) bierze wygląd wiersza z kolumn ``COLUMNS`` bez ``WYKONAWCA``:
    wiersz okresu z krojem z aplikacji, w którym tata wpisał tylko Wykonawcę w Calibri 8, zaczyna blok pod
    uporządkowanymi, a stoi na miejscu z datą z godziną pod ``DATA GODZ. POCZ.``, więc jedynym wierszem Kopii w obu
    położeniach jest on."""

    register = write_register(tmp_path / "Rejestr.xlsx", in_old_layout(default_register_rows()), headers=OLD_REGISTER_HEADERS)
    app_row = 9
    workbook = load_workbook(register)
    try:
        for cell in workbook["ZLECENIA"][app_row]:
            if cell.value is not None and cell.column != OLD_REGISTER_HEADERS.index("WYKONAWCA") + 1:
                cell.font = RAW_ORDER_FONT
        workbook.save(register)
    finally:
        workbook.close()
    copy = InputCopy()

    period_sheets(read(register, DadFiles(copy=copy)), parse_period_token(PERIOD))

    [[sheet]] = [file.sheets for file in copy.files()]
    assert sheet.paste.uncertain_rows == (app_row,)


@pytest.mark.parametrize(
    ("damage", "stop"),
    [
        (lambda register: paste_raw_orders(register, [register_order(90, datetime(2026, 9, 14, 9))]), "SUROWE_ZLECENIA_W_OKRESIE"),
        (lambda register: write_register(register, default_register_rows(), headers=("", "DATA GODZ. POCZ.")), "BRAK_ARKUSZA_ZLECEN"),
    ],
    ids=["surowe-zlecenia-w-sprawdzaniu", "bez-arkusza-zlecen-w-odczycie-danych"],
)
def test_logi_przygotowania_zatrzymanego_na_rejestrze_maja_jego_odcisk(
    tmp_path: Path, damage: Callable[[Path], object], stop: str
) -> None:
    """Przygotowanie zatrzymane na Rejestrze zleceń, w Sprawdzaniu na Surowych zleceniach albo w Odczycie danych na
    nagłówkach: Kopia wejścia ma odcisk Rejestru, na którym się zatrzymało, bez arkuszy, więc zatrzymanie da się
    powiązać z wersją pliku."""

    centrum = preparing_centrum(tmp_path)
    register = centrum.fixture.register_path
    damage(register)

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert [message["code"] for message in record["messages"] if message["kind"] == "stop"] == [stop]
    [copied] = record["input_copy"]
    assert (copied["name"], copied["sheets"]) == (register.name, [])
    assert logged_fingerprint(copied) == fingerprint(register.read_bytes(), register)


def test_diagnoza_zna_adres_i_numer_orange_przesunietego_pierwszego_wiersza_na_gorze_rejestru_z_data_jako_tekstem(
    tmp_path: Path,
) -> None:
    """Diagnoza czyta cały Rejestr zleceń od wiersza 2 (``preparation_register.register_problem``, jak ``centrum/diagnosis.py``).
    Wklejenie stoi pod nagłówkami bez uporządkowanych wierszy, a jego pierwszy wiersz jest przesunięty z datą jako tekstem,
    więc bez śladu przesunięcia: na górze arkusza zaczyna blok, a pamięć reguły danych zna jego adres i numer Orange
    (przegląd #984 r1, D1)."""

    register = write_register(tmp_path / "Rejestr.xlsx", [])
    probe = {**register_order(77, datetime(2026, 9, 10, 11)), "DATA GODZ. POCZ.": "10.09.2026 11:00"}
    probe |= {"ADRES": PROBE_ADDRESS, "NUMER UMOWY": PROBE_ORANGE}
    paste_raw_orders(register, [probe, register_order(78, datetime(2026, 9, 10, 12))], first=2)
    memory = empty_memory()

    register_problem(register, DadFiles(forbidden=memory))

    assert [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if not guarded(memory, value, "Uwaga taty").notes] == []


def _typed_at_top(register: Path) -> None:
    """Wklejenie od wiersza 2, tata wpisał ``SKUTECZNE`` w Calibri 8 w jego przesunięty pierwszy wiersz, a pod nim stoi
    wiersz próbny na miejscu z datą jako tekstem (sonda D10 z przeglądu #984 r2)."""

    rows = [register_order(76, datetime(2026, 9, 10, 10)), _register_probe("10.09.2026 11:00")]
    paste_raw_orders(register, rows, first=2)
    type_into_register(register, 2, "SKUTECZNE", "tak")


TYPED_IN_DIAGNOSIS: dict[str, tuple[bool, Callable[[Path], object]]] = {
    "na_gorze_rejestru": (False, _typed_at_top),
    # sonda RN3 z przeglądu #984 r2: Przygotowanie okresu zatrzymuje się na takim wklejeniu przed Kopią wejścia
    "na_dole_rejestru": (True, _typed_into_middle("15.09.2026 12:00")),
    # sonda RC4 z r3: wiersz próbny z datą z godziną pod DATA i w kolumnie A
    "na_dole_rejestru_wiersz_probny_z_data_z_godzina_takze_w_kolumnie_a": (
        True,
        _typed_into_middle(column_a=datetime(2026, 9, 15, 12)),
    ),
}
"""Wpis taty w Calibri 8 nad wierszem próbnym na miejscu bez widocznego przesunięcia: czy Rejestr ma uporządkowane
wiersze (``default_register_rows``) i wklejenie."""


@pytest.mark.parametrize("case", TYPED_IN_DIAGNOSIS.values(), ids=TYPED_IN_DIAGNOSIS.keys())
def test_diagnoza_zna_adres_i_numer_orange_wiersza_na_miejscu_pod_wpisem_taty_w_calibri_8(
    tmp_path: Path, case: tuple[bool, Callable[[Path], object]]
) -> None:
    """Diagnoza czyta cały Rejestr zleceń (``preparation_register.register_problem``, jak ``centrum/diagnosis.py``). Tata wpisał
    coś w Calibri 8 w wiersz wklejenia, więc za pierwszy wiersz bloku uchodzi wiersz próbny pod nim, który stoi na
    miejscu z datą jako tekstem albo z datą z godziną pod ``DATA GODZ. POCZ.`` i w kolumnie A: jego przesunięcia nie
    widać, więc pamięć reguły danych zna jego adres i numer Orange pod nagłówkami (przegląd #984 r2, W1, i r3, D1)."""

    ordered, paste = case
    register = write_register(tmp_path / "Rejestr.xlsx", default_register_rows() if ordered else [])
    paste(register)
    memory = empty_memory()

    register_problem(register, DadFiles(forbidden=memory))

    assert [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if not guarded(memory, value, "Uwaga taty").notes] == []


TYPED_INTO_REMARKS: dict[str, tuple[str, datetime | None]] = {
    "wpis_bez_daty_w_kolumnie_a": ("POZNAŃ", None),
    "wpis_z_data_w_kolumnie_a": ("POZNAŃ", datetime(2026, 9, 15, 12)),
    # same spacje to komórka bez wartości także w Uporządkowaniu, więc wiersz pod nią nie zaczyna bloku
    "same_spacje_z_data_w_kolumnie_a": ("  ", datetime(2026, 9, 15, 12)),
}
"""Wpis taty w Calibri 8 w ``UWAGI`` drugiego wiersza wklejenia i data z godziną w kolumnie A wiersza próbnego pod nim."""


@pytest.mark.parametrize(("typed", "column_a"), TYPED_INTO_REMARKS.values(), ids=TYPED_INTO_REMARKS.keys())
def test_wpis_taty_w_calibri_8_tylko_w_uwagi_konczy_blok_w_przygotowaniu_tak_jak_w_uporzadkowaniu_tego_rejestru(
    tmp_path: Path, typed: str, column_a: datetime | None
) -> None:
    """Tata wpisał coś w Calibri 8 tylko w ``UWAGI`` drugiego wiersza wklejenia, a trzeci, wiersz próbny, stoi na miejscu
    z datą z godziną pod ``DATA GODZ. POCZ.`` (i w kolumnie A albo bez niej). Wiersz uporządkowany ma jedną definicję
    (``raw_orders.look`` na ``OrderColumns.look_columns``, od ``AKCJE`` do ``UWAGI`` bez ``WYKONAWCA``), więc Podgląd
    Przygotowania zna granice bloku tak jak Uporządkowanie INTERMAX tego samego pliku: wiersze z uwagą „Fakt domeny
    złamany” i wiersze w obu położeniach są w Logach Przygotowania te same co w Kopii Uporządkowania."""

    centrum = preparing_centrum(tmp_path)
    register = centrum.fixture.register_path
    _typed_into_middle(column_a=column_a, header="UWAGI", typed=typed)(register)
    ordering = InputCopy()
    [area] = cast(OrderSheets, read(register, DadFiles(copy=ordering)).order_sheets).paste_areas()
    area.copy_paste()
    [[ordered]] = [file.sheets for file in ordering.files()]

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    [copied] = record["input_copy"]
    [sheet] = copied["sheets"]
    broken = [int(found) for found in re.findall(r"Fakt domeny złamany: wiersz (\d+) ", " ".join(record["input_copy_notes"]))]
    assert (broken, sheet["uncertain_rows"]) == (list(ordered.paste.traced_rows), list(ordered.paste.uncertain_rows))
    assert ordered.paste.uncertain_rows, "wiersz próbny jest w obu położeniach w Uporządkowaniu"


def test_odczyt_okresu_ze_srodka_rejestru_zna_wiersz_z_aplikacji_na_gorze_odczytu_pod_naglowkiem(tmp_path: Path) -> None:
    """Odczyt okresu zaczyna się w środku arkusza (nad nim wiersze z sierpnia), a pierwszy jego wiersz to wiersz z
    wyglądem z aplikacji, który stoi na miejscu: zawężenie zaczyna się od daty z godziną pod ``DATA GODZ. POCZ.``, więc
    taki wiersz zaczyna blok z tą datą, a pamięć reguły danych zna go w obu położeniach, także jego adres i numer Orange
    pod nagłówkiem (ADR 0025)."""

    earlier = [register_order(80, datetime(2026, 8, 3, 9)), None, register_order(81, datetime(2026, 8, 4, 9)), None]
    register = write_register(tmp_path / "Rejestr.xlsx", [*earlier, *default_register_rows()])
    probe = {**register_order(1, datetime(2026, 9, 7, 15)), "ADRES": PROBE_ADDRESS, "NUMER UMOWY": PROBE_ORANGE}
    paste_raw_orders(register, [probe], first=len(earlier) + 2, in_place_from="DATA GODZ. POCZ.")
    memory = empty_memory()

    [sheet] = period_sheets(read(register, DadFiles(forbidden=memory)), parse_period_token(PERIOD))

    assert sheet.register_rows[0].number == len(earlier) + 2, "odczyt okresu zaczyna się od wiersza próbnego"
    assert [value for value in (PROBE_ADDRESS, PROBE_ORANGE) if not guarded(memory, value, "Uwaga taty").notes] == []


def test_adres_rowny_slowu_trybu_i_tokenowi_okresu_nie_gubi_logow_ani_ich_issue_okresu(tmp_path: Path) -> None:
    """Strażnik porównuje słowa, a nie pochodzenie wartości (#936): Rejestr zleceń z ``ADRES`` równym trybowi, który
    stoi w pliku Logów (``DRY-RUN``), i tokenowi okresu daje Logi w pliku i w Skrzynce z trybem i okresem, które dało
    narzędzie, w issue Logów tego okresu."""

    rows = default_register_rows()
    rows[2] = {**(rows[2] or {}), "ADRES": "DRY-RUN"}
    rows[4] = {**(rows[4] or {}), "ADRES": PERIOD}
    centrum = preparing_centrum(tmp_path, rows)
    write_report_key(ToolDirectory(tmp_path))

    view = run_to_end(centrum, dry_run=True)

    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    [record] = records(centrum)
    assert (record["run_id"], record["mode"], record["period"]) == (view["run"]["id"], "DRY-RUN", PERIOD)
    titles = [issue.title for issue in box.background_issues if issue.label == "logi-uruchomienia"]
    assert titles == [f"Logi Uruchomienia {PERIOD}"]


def test_katalog_logow_bez_prawa_zapisu_daje_ten_sam_wynik_bez_komunikatu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    blocked = centrum.tool.run_logs
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("", encoding="utf-8")

    view = run_to_end(centrum, dry_run=False)

    reference = settling_centrum(tmp_path / "bez-blokady")
    expected = run_to_end(reference, dry_run=False)
    assert without_times(view["result"]) == without_times(expected["result"])
    assert (view["result"]["stops"], view["result"]["warnings"], view["result"]["technical_notes"]) == ([], [], [])
    assert blocked.read_text(encoding="utf-8") == ""
    log = centrum.log_path.read_text(encoding="utf-8")
    assert 'nieoczekiwany-wyjatek typ=FileExistsError miejsce="po wyniku Uruchomienia procesu"' in log
    queue = ToolDirectory(tmp_path).queue.glob("*.json")
    labels = sorted(re.sub(r"^\w+-\d{4}-(.+)-\w{8}\.json$", r"\1", path.name) for path in queue)
    assert labels == ["kontrola-ilosci", "logi-uruchomienia"], "Kontrola ilości i Logi w kolejce"
    [record] = centrum.metric_records()
    [expected_record] = reference.metric_records()
    assert without_times(record) == without_times(expected_record)


def test_logi_przezywaja_zamkniecie_i_ponowny_start_centrum(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    before = run_to_end(centrum, dry_run=True)
    [first] = log_files(centrum)
    first_bytes = first.read_bytes()

    centrum.restart()
    after = run_to_end(centrum, dry_run=True)

    assert [record["run_id"] for record in records(centrum)] == [before["run"]["id"], after["run"]["id"]]
    assert first.read_bytes() == first_bytes


def installed_at(repository: ToolRepository, target: str) -> None:
    """Klon taty jak po instalacji z README: tagi z „origin” i ``main`` na ``target`` (tag Wydania albo commit)."""

    repository.in_clone("fetch", "--quiet", "--tags", "origin")
    repository.in_clone("reset", "--quiet", "--hard", target)


def _annotated_release(repository: ToolRepository) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"}, released=False)
    installed_at(repository, repository.release(annotated=True))


def _two_releases_on_one_commit(repository: ToolRepository) -> None:
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"}, released=False)
    repository.release(tag="v0.10.0")
    installed_at(repository, repository.release(tag="v0.9.0"))


def _commit_after_release(repository: ToolRepository) -> None:
    installed_at(repository, repository.publish({"src/narzedzie.py": "WERSJA = 2\n"}, released=False))


CLONES = {
    "wydanie-z-opisem": (_annotated_release, "0.1.1"),
    "dwa-wydania-na-commicie": (_two_releases_on_one_commit, "0.10.0"),
    "commit-po-wydaniu": (_commit_after_release, None),
}


@pytest.mark.parametrize(("install", "wydanie"), CLONES.values(), ids=CLONES.keys())
def test_logi_podaja_najwyzsze_wydanie_na_commicie_narzedzia_a_po_wydaniu_brak(
    tmp_path: Path, install: Callable[[ToolRepository], None], wydanie: str | None
) -> None:
    repository = tool_repository(tmp_path / "repozytoria")
    install(repository)
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository))

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert record["tool"] == {"wydanie": wydanie, "commit": repository.head()}


def _no_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path | None:
    return None


def _uninstalled_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path | None:
    return tmp_path / "odinstalowany" / "git"


def _git_failing_on_tags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path | None:
    return git_failing_on(tmp_path, "for-each-ref")


def _git_not_answering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path | None:
    """Git, który na każde polecenie milczy dłużej, niż Centrum czeka na Wydanie, a potem podaje tag Wydania."""

    wait_s = 0.5
    monkeypatch.setattr("rozliczenia.centrum.tool_update._TAGS_TIMEOUT_S", wait_s)
    # Odpowiedź przed dwoma limitami: Centrum, które czeka dwa razy dłużej, zapisze Wydanie z tej odpowiedzi.
    return fake_cli(tmp_path, "git", f"import time\ntime.sleep({wait_s * 1.2})\nprint('v9.9.9')\n")


GITS = {
    "bez-gita": _no_git,
    "git-odinstalowany": _uninstalled_git,
    "blad-gita": _git_failing_on_tags,
    "git-bez-odpowiedzi": _git_not_answering,
}


@pytest.mark.parametrize("found_git", GITS.values(), ids=GITS.keys())
def test_bez_dzialajacego_gita_logi_maja_commit_narzedzia_bez_wydania(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, found_git: Callable[[Path, pytest.MonkeyPatch], Path | None]
) -> None:
    repository = tool_repository(tmp_path / "repozytoria")
    git = found_git(tmp_path, monkeypatch)
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository, find_git=lambda: git))

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert record["tool"] == {"wydanie": None, "commit": repository.head()}


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_bez_gita_logi_niczego_nie_uruchamiaja_po_wydanie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    programs = tmp_path / "programy"
    started = tmp_path / "uruchomiony"
    fake_cli(programs, "None", f"import pathlib\npathlib.Path({str(started)!r}).touch()\nprint('v9.9.9')\n")
    monkeypatch.setenv("PATH", f"{programs}{os.pathsep}{os.environ['PATH']}")
    repository = tool_repository(tmp_path / "repozytoria")
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository, find_git=lambda: None))

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert record["tool"] == {"wydanie": None, "commit": repository.head()}
    assert not started.exists()


def test_narzedzie_poza_klonem_gita_ma_logi_bez_commitu_i_bez_wydania(tmp_path: Path) -> None:
    github = FakeGitHub(tool_commit=None, wydanie=Release.of_tag("v0.1.0"))
    centrum = settling_centrum(tmp_path, surroundings=Surroundings(github=github))

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert record["tool"] == {"wydanie": None, "commit": None}


# --- Wycena w efenix z Centrum (#750) -----------------------------------------------------------------------------------

LOGIN = "Zaloguj się w oknie efenix"
# Zlecenia sześciu Wykonawców (wiersze 18–23): jedno gotowe, dwa nieznane w efenix i trzy z Ostrzeżeniem Emmetta (Emmett
# ma O większe niż plik), więc każdy wynik ma inną liczbę zleceń.
PRICED = [
    Order("#ZLQX01", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}),
    Order("#ZLQX02", worker="beata.testowa", address="UL. PRYWATNA 7/1", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQX03", worker="celina.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 2}),
    Order("#ZLQX04", worker="dorota.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQX05", worker="ewa.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 3}),
    Order("#ZLQX06", worker="filip.testowy", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 2}),
]
# Zlecenia z ``PRICED``, które zna Atrapa efenix: gotowe i z Ostrzeżeniem Emmetta.
IN_EFENIX = [PRICED[0].in_efenix("611"), PRICED[2].in_efenix("613"), PRICED[4].in_efenix("615"), PRICED[5].in_efenix("616")]
# Najkrótszy początek ``PRICED``, który w Wycenie przez Centrum wykonuje te same linie src co całe ``PRICED`` (każdy
# rodzaj zlecenia i szukanie po zleceniu z zapisem): dla testów, których kontrakt nie liczy zleceń, bo każde zlecenie to
# czas Chromium.
FEW_PRICED = PRICED[:4]
FEW_IN_EFENIX = IN_EFENIX[:2]


def test_okno_efenix_taty_to_widoczny_chrome_w_tempie_ludzkim_z_prawdziwym_efenix() -> None:
    """Centrum taty daje Wycenie w efenix widoczne okno zainstalowanego Google Chrome, w którym tata się loguje, tempo
    ludzkie na prawdziwym zegarze i adres prawdziwego efenix. Testy i weryfikacja na Atrapie efenix mają okno bez tempa,
    a okna taty nie otwierają, bo prowadzi do prawdziwego efenix (ADR 0024)."""

    window = EfenixWindow.of_tata()

    assert (window.pace, window.url) == (Pace(sleep=time.sleep, clock=time.monotonic), EFENIX_URL)
    assert (window.channel, window.headless, window.arguments) == ("chrome", False, ())


def test_wycena_w_efenix_z_centrum_pracuje_w_tempie_ludzkim_okna_efenix(tmp_path: Path) -> None:
    """Centrum daje procesowi tempo swojego okna efenix: przerwę przed każdym zapisem w efenix. Na zegarze, który stoi,
    przerwa przed zapisem to ``ACTION_PAUSE_S``, a przed szukaniem zlecenia po zleceniu z zapisem próg podtrzymania sesji."""

    pauses: list[float] = []
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        pace = Pace(sleep=pauses.append, clock=lambda: 0.0)
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url, efenix_pace=pace))
        write_collective_file(centrum.period_parent, FEW_PRICED)
        assert _start_pricing(centrum).status_code == 200
        finished = finished_view(centrum.client)

    assert (finished["result"]["result"], pauses[0], set(pauses)) == ("WYMAGA_SPRAWDZENIA", ACTION_PAUSE_S, {ACTION_PAUSE_S, KEEPALIVE_S})


def _pricing_centrum(tmp_path: Path, atrapa: AtrapaEfenix, *arguments: str, orders: Sequence[Order] = PRICED) -> SettlingCentrum:
    """Centrum, którego okno efenix to Chromium na Atrapie z argumentami ``arguments``; Folder okresu ma Plik zbiorczy
    z ``orders``."""

    centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url, efenix_arguments=arguments))
    write_collective_file(centrum.period_parent, orders)
    return centrum


def _start_pricing(centrum: SettlingCentrum, *, dry_run: bool = False, pricing: str | None = None) -> Any:
    """Start Wyceny w efenix jak przycisk karty startu; bez ``pricing`` żądanie nie ma trybu (domyślny)."""

    request: dict[str, Any] = {"process": "efenix", "period": PERIOD, "mode": RunMode.of(dry_run=dry_run)}
    if pricing is not None:
        request["pricing"] = pricing
    return centrum.client.post("/api/runs", json=request)


def _view_where(centrum: SettlingCentrum, wanted: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    for event in run_events(centrum.client):
        view: dict[str, Any] = event["view"]
        if wanted(view):
            return view
    raise AssertionError("Strumień skończył się przed oczekiwanym widokiem.")


def _pricing_setup(centrum: SettlingCentrum) -> dict[str, Any]:
    [setup] = [process for process in centrum.client.get("/api/runs/setup").json()["processes"] if process["process"] == "efenix"]
    assert isinstance(setup, dict)
    return setup


def _with_collective_file(centrum: SettlingCentrum, token: str) -> str:
    name = collective_file_name_with(token)
    folder = centrum.periods_directory / token
    folder.mkdir()
    (folder / name).touch()
    return name


def test_karta_startu_wyceny_w_efenix_to_okresy_z_plikiem_zbiorczym_bez_podgladu_i_bez_potwierdzenia_gotowosci(
    tmp_path: Path,
) -> None:
    """Wycena w efenix wybiera okresy z Plikiem zbiorczym i proponuje ostatni pełny okres. Nie ma Podglądu bez zapisu,
    więc żaden okres nie ma udanego podglądu, a tata nie potwierdza gotowości plików; karta okresu nazywa jego Plik
    zbiorczy i przypomina, żeby go zapisać i zamknąć w Excelu."""

    centrum = settling_centrum(tmp_path)
    older = _with_collective_file(centrum, "01_07_09_2026")

    setup = _pricing_setup(centrum)

    assert (setup["title"], setup["creates"], setup["blocker"]) == ("Wycena w efenix", "Wyceny zleceń i Znaczniki efenix", None)
    assert (setup["confirms_readiness"], setup["preview_hint"], setup["preselected_period"]) == (False, None, PERIOD)
    assert setup["pricing_modes"] == ["bez Przekazania", "z Przekazaniem"], "dwa przyciski: bez zapisu i z zapisem"
    reminder = "Zapisz i zamknij Plik zbiorczy w Excelu"
    assert [
        (choice["token"], choice["last_complete"], choice["previewed"], choice["collective_file"], choice["reminder"])
        for choice in setup["periods"]
    ] == [(PERIOD, True, False, SOURCE_NAME, reminder), ("01_07_09_2026", False, False, older, reminder)]


def test_bez_pliku_zbiorczego_w_ostatnim_pelnym_okresie_wycena_w_efenix_proponuje_najnowszy_okres_z_plikiem_zbiorczym(
    tmp_path: Path,
) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.collective_file.unlink()
    _with_collective_file(centrum, "25_31_08_2026")
    _with_collective_file(centrum, "01_07_09_2026")

    setup = _pricing_setup(centrum)

    assert [choice["token"] for choice in setup["periods"]] == ["01_07_09_2026", "25_31_08_2026"]
    assert (setup["preselected_period"], setup["blocker"]) == ("01_07_09_2026", None)


def test_karta_startu_wyceny_w_efenix_mowi_czego_brakuje_bez_pliku_zbiorczego_i_bez_folderu_okresow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.collective_file.unlink()

    without_collective_file = _pricing_setup(centrum)
    shutil.rmtree(centrum.periods_directory)
    without_periods_directory = _pricing_setup(centrum)

    assert (without_collective_file["blocker"], without_collective_file["periods"]) == (
        "Żaden okres nie ma Pliku zbiorczego. Najpierw przygotuj plik zbiorczy.",
        [],
    )
    assert (without_periods_directory["blocker"], without_periods_directory["periods"]) == (
        f"Nie ma już folderu okresów {centrum.periods_directory.name}. Wskaż go ponownie.",
        [],
    )


def test_wycena_w_efenix_z_centrum_czeka_na_logowanie_taty_jako_jedyne_uruchomienie_a_karta_i_powiadomienie_maja_wynik(
    tmp_path: Path,
) -> None:
    """Okres z Plikiem zbiorczym ma przycisk Wyceny w efenix bez Podglądu bez zapisu. W trakcie czekania na logowanie
    inne Uruchomienie nie startuje, a karta po wyniku ma błędy i ostrzeżenia Emmetta z numerem zlecenia i Wykonawcą
    oraz liczby pominiętych. Nowe Powiadomienie (kropka na dzwonku) ma tytuł wyniku, okres i liczby zleceń, a prowadzi
    do karty tego Uruchomienia z jego Logów."""

    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        atrapa.expire_session()
        [setup] = [process for process in centrum.client.get("/api/runs/setup").json()["processes"] if process["process"] == "efenix"]
        preview = _start_pricing(centrum, dry_run=True)
        assert _start_pricing(centrum).status_code == 200
        waiting = _view_where(centrum, lambda view: (view.get("progress", {}).get("step") or {}).get("label") == LOGIN)
        busy = centrum.start(dry_run=True)
        atrapa.log_in()
        finished = finished_view(centrum.client)
        result = finished["result"]
    notifications = centrum.client.get("/api/notifications").json()
    [notification] = [item for item in notifications["items"] if item["kind"] == "wycena_w_efenix"]
    card = centrum.client.get(f"/api/runs/{notification['run_id']}/card").json()

    assert (notifications["unread"], notification["unread"]) == (1, True)
    assert (notification["headline"], notification["period"], _priced(notification), notification["stopped"]) == (
        "Wycena w efenix gotowa · wymaga sprawdzenia",
        PERIOD,
        [("Gotowe do przekazania", 1), ("Przekazane do akceptacji", 0), ("Rozliczone", 0), ("Błędy zleceń", 2), ("Ostrzeżenia Emmetta", 3)],
        None,
    )
    assert (notification["run_id"], card["state"], card["result"]["headline"]) == (
        finished["run"]["id"],
        "restored",
        "Wycena w efenix gotowa · wymaga sprawdzenia",
    )
    assert (setup["title"], setup["preview_hint"], [period["token"] for period in setup["periods"]]) == ("Wycena w efenix", None, [PERIOD])
    assert (preview.status_code, busy.status_code, waiting["state"]) == (409, 409, "running")
    assert preview.json()["message"] == (
        "Wycena w efenix nie ma podglądu bez zapisu. Uruchom ją przyciskiem „Uzupełnij bez zapisu” albo „Uzupełnij i zapisz”."
    )
    assert busy.json()["message"].startswith(f"Trwa już Uruchomienie procesu: Wycena w efenix, okres {PERIOD}.")
    assert (result["result"], result["headline"], result["next_action"], result["collective_file_prepared"]) == (
        "WYMAGA_SPRAWDZENIA",
        "Wycena w efenix gotowa · wymaga sprawdzenia",
        "open_collective_file",
        False,
    )
    assert {figure["label"]: figure["value"] for figure in result["summary"]["figures"]} == {
        "Zlecenia w zakresie": 6,
        "Gotowe do przekazania": 1,
        "Przekazane do akceptacji": 0,
        "Rozliczone": 0,
        "Błędy zleceń": 2,
        "Ostrzeżenia Emmetta": 3,
    }
    assert {count["label"]: count["count"] for count in result["summary"]["counts"]["counts"]} == {
        "Ze zdjęciami": 0,
        "Usterki": 0,
        "Nieznalezione w efenix": 2,
    }
    assert [(group["title"], group["done"]) for group in result["order_notes"]] == [
        ("Błędy zleceń", False),
        ("Ostrzeżenia Emmetta", False),
        ("Przekazane do akceptacji", True),
        ("Rozliczone", True),
    ]
    notes = _order_lists(result)
    assert [(note["row"], note["order"], note["worker"]) for note in notes["Błędy zleceń"]] == [
        (19, "ZLQX02", "beata.testowa"),
        (21, "ZLQX04", "dorota.testowa"),
    ]
    assert [(note["row"], note["order"], note["worker"]) for note in notes["Ostrzeżenia Emmetta"]] == [
        (20, "ZLQX03", "celina.testowa"),
        (22, "ZLQX05", "ewa.testowa"),
        (23, "ZLQX06", "filip.testowy"),
    ]
    assert notes["Błędy zleceń"][0]["what"].startswith("efenix nie zna zlecenia o numerze z NUMER ZL.")
    assert notes["Ostrzeżenia Emmetta"][0]["what"].startswith("efenix ma więcej niż Plik zbiorczy")
    assert notes["Rozliczone"] == []


def test_zlecenie_rozliczone_w_efenix_ma_na_karcie_w_logach_i_w_powiadomieniu_wlasny_wynik_a_nie_blad(tmp_path: Path) -> None:
    """Zlecenie o statusie „Rozliczone” (#821) to na karcie Uruchomienia osobna liczba i lista z numerem zlecenia i
    Wykonawcą, w Logach Uruchomienia wynik „rozliczone” bez kodu Komunikatu, a w Powiadomieniu osobna liczba; wynik to OK."""

    orders = [
        Order("#ZLQR01", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}),
        Order("#ZLQR02", worker="beata.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    ]
    in_efenix = [orders[0].in_efenix("621"), replace(orders[1].in_efenix("622"), status="Rozliczone", execution_date=DAY)]
    with atrapa_efenix(in_efenix) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, orders)
        assert _start_pricing(centrum).status_code == 200
        result = finished_view(centrum.client)["result"]
    [record] = records(centrum)
    [notification] = [item for item in centrum.client.get("/api/notifications").json()["items"] if item["kind"] == "wycena_w_efenix"]

    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    assert (result["result"], figures["Gotowe do przekazania"], figures["Rozliczone"], figures["Błędy zleceń"]) == ("OK", 1, 1, 0)
    notes = _order_lists(result)
    assert (notes["Błędy zleceń"], [(note["row"], note["order"], note["worker"], note["what"]) for note in notes["Rozliczone"]]) == (
        [],
        [(19, "ZLQR02", "beata.testowa", None)],
    )
    traced = [(order["row"], order["outcome"], order["code"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]]
    assert traced == [(18, "gotowe", None, ["szukanie", "otwarcie zlecenia"]), (19, "rozliczone", None, ["szukanie"])]
    assert _priced(notification) == [("Gotowe do przekazania", 1), ("Przekazane do akceptacji", 0), ("Rozliczone", 1), ("Błędy zleceń", 0), ("Ostrzeżenia Emmetta", 0)]



def test_zlecenie_do_akceptacji_w_efenix_ma_na_karcie_i_w_logach_wynik_przekazane_a_nie_blad(tmp_path: Path) -> None:
    """Start bez trybu to Wycena bez Przekazania (ADR 0027), z tym trybem na karcie i w faktach startu Logów, a zlecenie,
    które tata już przekazał do akceptacji, to na karcie liczba i lista „Przekazane do akceptacji”, a w Logach
    Uruchomienia wynik „przekazane” bez kodu Komunikatu i bez otwarcia strony zlecenia; wynik to OK, a efenix nie
    dostaje żadnej zmiany statusu."""

    orders = [
        Order("#ZLQP01", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}),
        Order("#ZLQP02", worker="beata.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    ]
    in_efenix = [orders[0].in_efenix("631"), replace(orders[1].in_efenix("632"), status="Do akceptacji", execution_date=DAY)]
    with atrapa_efenix(in_efenix) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, orders)
        assert _start_pricing(centrum).status_code == 200
        finished = finished_view(centrum.client)
        requests = atrapa.status_requests()
    [record] = records(centrum)
    result = finished["result"]

    assert (finished["run"]["pricing"], record["pricing"]) == ("bez Przekazania", "bez Przekazania")
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    assert (result["result"], figures["Gotowe do przekazania"], figures["Przekazane do akceptacji"], requests) == ("OK", 1, 1, [])
    forwarded = _order_lists(result)["Przekazane do akceptacji"]
    assert [(line["row"], line["order"], line["worker"]) for line in forwarded] == [(19, "ZLQP02", "beata.testowa")]
    traced = [(order["row"], order["outcome"], order["code"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]]
    assert traced == [(18, "gotowe", None, ["szukanie", "otwarcie zlecenia"]), (19, "przekazane", None, ["szukanie"])]

def _order_lists(result: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    return {group["title"]: group["notes"] for group in result["order_notes"]}


def _priced(notification: dict[str, Any]) -> list[tuple[str, int]]:
    return [(count["label"], count["count"]) for count in notification["orders"]]


# Zlecenie gotowe do przekazania i zlecenie, które tata już przekazał do akceptacji, każde z jedną pozycją jak w pliku.
FORWARDED: Final = [
    Order("#ZLQF01", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}),
    Order("#ZLQF02", worker="beata.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
]
FORWARDED_IN_EFENIX: Final = [
    FORWARDED[0].in_efenix("641"),
    replace(FORWARDED[1].in_efenix("642"), status="Do akceptacji", execution_date=DAY),
]


def test_wycena_w_efenix_z_zapisem_przekazuje_gotowe_zlecenie_a_karta_logi_i_powiadomienie_maja_tryb_i_przekazane(
    tmp_path: Path,
) -> None:
    """Przycisk „Uzupełnij i zapisz” startuje Wycenę z Przekazaniem (ADR 0027): gotowe zlecenie dostaje zielony „Zapisz”
    w efenix, jedno żądanie zmiany statusu na „Do akceptacji”, i razem ze zleceniem przekazanym wcześniej przez tatę
    jest na karcie liczbą i listą „Przekazane do akceptacji”, a nie gotowym. Tryb mają karta na żywo, fakty startu Logów
    Uruchomienia, karta z Logów i Powiadomienie, które liczy też przekazane."""

    with atrapa_efenix(FORWARDED_IN_EFENIX) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, FORWARDED)
        started = _start_pricing(centrum, pricing="z Przekazaniem")
        finished = finished_view(centrum.client)
        requests = atrapa.status_requests()
    [record] = records(centrum)
    [notification] = [item for item in centrum.client.get("/api/notifications").json()["items"] if item["kind"] == "wycena_w_efenix"]
    card = centrum.client.get(f"/api/runs/{finished['run']['id']}/card").json()
    result = finished["result"]

    assert (started.status_code, started.json()["run"]["pricing"], requests) == (200, "z Przekazaniem", [("POST", "Do akceptacji")])
    figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
    assert (result["result"], figures["Gotowe do przekazania"], figures["Przekazane do akceptacji"]) == ("OK", 0, 2)
    forwarded = _order_lists(result)["Przekazane do akceptacji"]
    assert [(line["row"], line["order"], line["worker"]) for line in forwarded] == [
        (18, "ZLQF01", "adrian.testowy"),
        (19, "ZLQF02", "beata.testowa"),
    ]
    assert [(order["row"], order["outcome"]) for order in record["efenix_orders"]] == [(18, "przekazane"), (19, "przekazane")]
    assert (record["pricing"], card["run"]["pricing"], notification["pricing"]) == ("z Przekazaniem",) * 3
    assert _priced(notification) == [("Gotowe do przekazania", 0), ("Przekazane do akceptacji", 2), ("Rozliczone", 0), ("Błędy zleceń", 0), ("Ostrzeżenia Emmetta", 0)]


def test_odmowa_przekazania_przez_efenix_jest_na_karcie_w_powiadomieniu_i_w_logach_bledem_zlecenia_z_przyczyna_bez_tekstu_efenix(
    tmp_path: Path,
) -> None:
    """Gotowe zlecenie, któremu efenix po zielonym „Zapisz” odmawia Przekazania (brak zdjęć), jest na karcie (lista błędów
    z Komunikatem), na karcie z Logów (liczba błędów) i w Powiadomieniu błędem zlecenia jak inne, z Komunikatem, czego efenix brakuje, a do efenix nie dochodzi żadna
    zmiana statusu. Logi Uruchomienia mają odmowę z zamkniętej listy, a nie tekst okna informacji efenix."""

    in_efenix = [replace(FORWARDED_IN_EFENIX[0], forward_refusal=ForwardRefusal.NO_PHOTOS.value), FORWARDED_IN_EFENIX[1]]
    with atrapa_efenix(in_efenix) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, FORWARDED)
        assert _start_pricing(centrum, pricing="z Przekazaniem").status_code == 200
        finished = finished_view(centrum.client)
        requests = atrapa.status_requests()
    [record] = records(centrum)
    [notification] = [item for item in centrum.client.get("/api/notifications").json()["items"] if item["kind"] == "wycena_w_efenix"]
    card = centrum.client.get(f"/api/runs/{finished['run']['id']}/card").json()
    result = finished["result"]

    for summary in (result["summary"], card["result"]["summary"]):
        figures = {figure["label"]: figure["value"] for figure in summary["figures"]}
        assert (figures["Błędy zleceń"], figures["Przekazane do akceptacji"], figures["Gotowe do przekazania"]) == (1, 1, 0)
    assert (result["result"], requests) == ("WYMAGA_SPRAWDZENIA", [])
    errors = _order_lists(result)["Błędy zleceń"]
    assert [(note["row"], note["order"], note["worker"]) for note in errors] == [(18, "ZLQF01", "adrian.testowy")]
    assert errors[0]["what"].startswith("efenix nie przyjął Przekazania do akceptacji: do wyceny nie są dołączone żadne zdjęcia")
    assert _priced(notification) == [("Gotowe do przekazania", 0), ("Przekazane do akceptacji", 1), ("Rozliczone", 0), ("Błędy zleceń", 1), ("Ostrzeżenia Emmetta", 0)]
    [refused, _forwarded] = record["efenix_orders"]
    assert (refused["outcome"], refused["code"], [(step["action"], step["refusal"]) for step in refused["steps"]][-1]) == (
        "błąd",
        "EFENIX_ODMOWA_PRZEKAZANIA",
        ("przekazanie do akceptacji", "NO_PHOTOS"),
    )
    assert "zdjęć" not in json.dumps(record, ensure_ascii=False)


def _previous_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kept: str, *, pricing: str | None, before_modes: bool = False
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Karta ostatniego Uruchomienia po ponownym starcie Centrum po Wycenie w trybie ``pricing``, której zostały tylko
    Logi Uruchomienia (``kept`` „logi”), wiersz Historii i plik ostatniego startu („historia”) albo dziennik i plik
    ostatniego startu („dziennik”); ``before_modes``: każdy z tych plików bez pola ``pricing``, jak zapisało go Centrum
    sprzed trybów. Daje kartę, identyfikator Uruchomienia i Logi po starcie."""

    with atrapa_efenix(FORWARDED_IN_EFENIX) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, FORWARDED)
        journaled = journals_at_result(monkeypatch, centrum.log_path.parent / "dzienniki-wyceny")
        assert _start_pricing(centrum, pricing=pricing).status_code == 200
        run_id = finished_view(centrum.client)["run"]["id"]
    centrum.client.stop()
    if kept != "logi":
        for logs in log_files(centrum):
            logs.unlink()
    if kept == "dziennik":
        centrum.engines.metrics.efenix.unlink()
        for path, text in journaled.items():
            path.write_text(text, encoding="utf-8")
    if before_modes:
        for path in [*log_files(centrum), centrum.tool.last_started]:
            path.write_text(json.dumps(_without_pricing(json.loads(path.read_text(encoding="utf-8")))), encoding="utf-8")
        for path in journaled if kept == "dziennik" else []:
            first, *rest = path.read_text(encoding="utf-8").splitlines(keepends=True)
            path.write_text(json.dumps(_without_pricing(json.loads(first))) + "\n" + "".join(rest), encoding="utf-8")

    centrum.restart()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    centrum.client.stop()
    return previous, run_id, records(centrum)


def _without_pricing(fields: dict[str, Any]) -> dict[str, Any]:
    assert "pricing" in fields, "plik ma tryb, więc test usuwa pole, którego nie było przed trybami"
    return {name: value for name, value in fields.items() if name != "pricing"}


@pytest.mark.parametrize("kept", ["logi", "historia", "dziennik"])
def test_karta_wyceny_z_zapisem_po_ponownym_starcie_centrum_ma_jej_tryb_z_logow_historii_albo_dziennika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kept: str
) -> None:
    """Karta ostatniego Uruchomienia po ponownym starcie Centrum mówi, że Wycena była z zapisem, skądkolwiek ją wzięła: z
    Logów Uruchomienia, z wiersza Historii i pliku ostatniego startu, gdy Logów nie ma, albo z dziennika Urwanego
    Uruchomienia, którego Logi mają ten tryb w faktach startu."""

    previous, run_id, logged = _previous_after_restart(tmp_path, monkeypatch, kept, pricing="z Przekazaniem")

    state = {"logi": "restored", "historia": "recorded", "dziennik": "interrupted"}[kept]
    assert (previous["state"], previous["run"]["id"], previous["run"]["pricing"]) == (state, run_id, "z Przekazaniem")
    if kept == "dziennik":
        assert [record["pricing"] for record in logged] == ["z Przekazaniem"]


@pytest.mark.parametrize("kept", ["logi", "historia", "dziennik"])
def test_karta_wyceny_z_plikow_sprzed_trybow_ma_tryb_bez_przekazania(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kept: str
) -> None:
    """Logi, plik ostatniego startu i pierwsza linia dziennika sprzed trybów nie mają pola ``pricing``, a Wycena biegła
    wtedy bez Przekazania (ADR 0027), więc karta ostatniego Uruchomienia mówi „bez Przekazania”, a nie „z Przekazaniem”."""

    previous, run_id, logged = _previous_after_restart(tmp_path, monkeypatch, kept, pricing=None, before_modes=True)

    state = {"logi": "restored", "historia": "recorded", "dziennik": "interrupted"}[kept]
    assert (previous["state"], previous["run"]["id"], previous["run"]["pricing"]) == (state, run_id, "bez Przekazania")
    if kept == "dziennik":
        assert [record.get("pricing") for record in logged] == [None]


def test_tryb_z_przekazaniem_ma_tylko_wycena_w_efenix_a_inny_proces_z_nim_dostaje_odmowe(tmp_path: Path) -> None:
    """Przebieg rozliczeń nie ma trybów, więc jego karta startu nie ma przycisków trybu, a start z Przekazaniem do
    akceptacji dostaje odmowę 409 i nic nie startuje."""

    centrum = settling_centrum(tmp_path)
    processes = centrum.client.get("/api/runs/setup").json()["processes"]
    refused = centrum.client.post(
        "/api/runs", json={"process": "settlement", "period": PERIOD, "mode": "DRY-RUN", "pricing": "z Przekazaniem"}
    )
    current = centrum.client.get("/api/runs/current").json()

    assert {process["process"]: process["pricing_modes"] for process in processes if process["process"] != "efenix"} == {
        "preparation": [],
        "settlement": [],
    }
    assert (refused.status_code, refused.json()["message"]) == (
        409,
        "Przebieg rozliczeń nie ma trybu z Przekazaniem do akceptacji.",
    )
    assert current["state"] == "idle"


def _close_window(profile: Path) -> None:
    """Tata zamyka krzyżykiem okno efenix, które Centrum otworzyło (przez port debugowania z profilu przeglądarki)."""

    with _devtools(profile) as browser:
        browser.contexts[0].pages[0].close()


def _kill_browser(profile: Path) -> None:
    """Przeglądarka okna efenix znika cała naraz, jak Chrome zamknięty z paska zadań albo zabity przez system."""

    with _devtools(profile) as browser:
        processes = browser.new_browser_cdp_session().send("SystemInfo.getProcessInfo")["processInfo"]
    [pid] = [process["id"] for process in processes if process["type"] == "browser"]
    if sys.platform == "win32":
        os.kill(pid, signal.SIGTERM)  # na Windows to TerminateProcess: proces znika bez sprzątania, jak po SIGKILL
    else:
        os.kill(pid, signal.SIGKILL)


@contextmanager
def _devtools(profile: Path) -> Iterator[Browser]:
    port = (profile / "DevToolsActivePort").read_text(encoding="utf-8").split()[0]
    with sync_playwright() as playwright:
        yield playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")


def _disabled_features(browser: Browser) -> list[set[str]]:
    """Funkcje każdego ``--disable-features`` z linii poleceń przeglądarki uruchomionej z ``--enable-automation``."""

    line = browser.new_browser_cdp_session().send("Browser.getBrowserCommandLine")["arguments"]
    return [set(argument.removeprefix("--disable-features=").split(",")) for argument in line if argument.startswith("--disable-features=")]


# Sprawdzenie skilla verify-wycena-efenix: przyczynę Zatrzymania okna efenix, którą dostają Logi, przy każdej awarii każdego
# żądania prawdziwej Wyceny w efenix sprawdza jego skrypt (explore_wycena_efenix.py) z tabelą oczekiwań z domeny. Cały
# zakres biegnie w CI jako podstawa skilla w częściach, a tu we własnym procesie z limitem (#651) zakres, który przechodzi
# przez każdą fazę sprawdzenia: przebieg bez awarii, awarie, stan, który zostawia zabity proces, i ponowne uruchomienia
# po nich ze zmianami taty w efenix.
EXPLORER = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-wycena-efenix" / "scripts" / "explore_wycena_efenix.py"
EXPLORER_SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "verify-wycena-efenix" / "SKILL.md"
# Poniżej limitu pytest testu, który je uruchamia, żeby sprawdzenie, które się nie kończy, padło z tym, co zdążyło
# wypisać. Zakres testu z ponownymi uruchomieniami trwał 26 s na Macu przy 4 przeglądarkach, a na Windows w CI całe
# zadania pytest z tym plikiem trwały 50 i 71 s (run 41985714991).
EXPLORER_LIMIT_S = 200


def _explorer_in_own_process(*arguments: str, environment: dict[str, str] | None = None) -> tuple[int | None, list[str]]:
    import subprocess

    try:
        done = subprocess.run(
            [sys.executable, "-X", "utf8", "-u", str(EXPLORER), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=EXPLORER_LIMIT_S,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired as hung:
        return None, (hung.stdout or b"").decode("utf-8", "replace").splitlines()
    return done.returncode, done.stdout.decode("utf-8", "replace").splitlines()


@pytest.mark.dlugi
@pytest.mark.timeout(EXPLORER_LIMIT_S + 40)
def test_odmowa_zaladuj_do_zlecenia_zabity_proces_przy_niej_i_wznowienie_po_nich_trzymaja_niezmienniki_bez_znanych_ustalen(
    tmp_path: Path,
) -> None:
    """Bez żadnego wybaczonego naruszenia: błąd serwera po wykonaniu „Załaduj do zlecenia” i zabity proces po nim
    zostawiają zlecenie z samą Wyceną Emmetta, a ponowne uruchomienie dokańcza je do pliku jak jeden przebieg (ADR 0026;
    dawniej przyjęte ryzyko #774)."""

    code, lines = _explorer_in_own_process(
        "--run-dir", str(tmp_path), "--variant", "odpowiedzi", "zabity-proces", "--rola", "zaladuj-do-zlecenia", "--rownolegle", "4"
    )

    # Werdykt z wybaczonym naruszeniem ma ich liczbę („WYCENA EFENIX OK, ZNANE USTALENIA: n”).
    assert (code, lines[-1:]) == (0, ["WYCENA EFENIX OK"]), "\n".join(lines)
    assert any(" ponownych uruchomień " in line for line in lines), "\n".join(lines)
    [evidence] = (tmp_path / "evidence").iterdir()
    assert (evidence / "raport.txt").read_text(encoding="utf-8").splitlines()[-1] == "WYCENA EFENIX OK"
    # Kontrprzykład ma tylko przypadek z naruszeniem, znanym ustaleniem albo przyjętym ryzykiem, a tu nie ma żadnego.
    assert not (evidence / "kontrprzyklady").exists()
    assert list((tmp_path / "runs").iterdir()) == []


def test_czesci_przegladu_z_ci_czesci_skladaja_sie_na_caly_zakres_kazdy_przypadek_raz() -> None:
    """Każda część ``ci-czesci`` z ``SKILL.md`` skilla ma swoje przypadki, a razem, w kolejności, cały zakres; mniejsze
    liczby części daje ten sam ``part`` (``tests/test_podstawa_w_czesciach.py``)."""

    [count] = [int(line.split(":")[1]) for line in EXPLORER_SKILL.read_text(encoding="utf-8").splitlines() if line.startswith("ci-czesci:")]
    code, whole = _explorer_in_own_process("--lista")
    parts = []
    for number in range(1, count + 1):
        part_code, lines = _explorer_in_own_process("--lista", environment={**os.environ, "MUTACJE_CZESC": f"{number}/{count}"})
        assert part_code == 0, "\n".join(lines)
        parts.append(lines)

    assert code == 0 and len(whole) > 400, "\n".join(whole)
    assert sum(parts, []) == whole
    assert all(parts)


def test_okno_efenix_z_centrum_nie_losuje_portu_polaczenia_i_ma_wylaczone_funkcje_playwrighta(tmp_path: Path) -> None:
    """Chromium 156 na Windows 11 22H2 i nowszym losuje port lokalny każdego połączenia (``TcpPortRandomizationWin``), a
    Windows odmawia wtedy czasem połączenia z efenix (``net::ERR_NO_BUFFER_SPACE``), choć porty są wolne (#767). Przeglądarka
    okna efenix, które otwiera Centrum, ma tę funkcję wyłączoną w jedynym ``--disable-features``, bo Chromium bierze tylko
    ostatni, razem z każdą funkcją, którą wyłącza Playwright w Chromium bez tych argumentów."""

    with atrapa_efenix([PRICED[0].in_efenix("611")]) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, "--remote-debugging-port=0", "--enable-automation")
        atrapa.expire_session()
        assert _start_pricing(centrum).status_code == 200
        _view_where(centrum, lambda view: (view.get("progress", {}).get("step") or {}).get("label") == LOGIN)
        with _devtools(tmp_path / "przegladarka-efenix") as window:
            disabled_in_window = _disabled_features(window)
        atrapa.log_in()
        finished_view(centrum.client)
    with sync_playwright() as playwright:
        plain = playwright.chromium.launch(args=["--enable-automation"])
        try:
            [disabled_by_playwright] = _disabled_features(plain)
        finally:
            plain.close()

    assert disabled_in_window == [disabled_by_playwright | {"TcpPortRandomizationWin"}]


@pytest.mark.parametrize("close", [_close_window, _kill_browser], ids=["zamkniete-okno", "zabita-przegladarka"])
def test_okno_efenix_zamkniete_w_trakcie_logowania_zatrzymuje_wycene_od_razu_a_centrum_przyjmuje_nastepne_uruchomienie(
    tmp_path: Path, close: Callable[[Path], None]
) -> None:
    """Tata zamyka okno efenix albo całą przeglądarkę, zanim się zalogował: Wycena zatrzymuje się po kilku sekundach, nie
    po 15 minutach limitu logowania, z Komunikatem o zamkniętym oknie, Powiadomienie to mówi, a Centrum od razu przyjmuje
    następne Uruchomienie. Logi tej Wyceny nazywają w śladzie wywołań drogę startu, która zawiodła (zamknięte okno), choć
    to Zatrzymanie dla taty (#976)."""

    with atrapa_efenix([PRICED[0].in_efenix("611")]) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, "--remote-debugging-port=0")
        atrapa.expire_session()
        assert _start_pricing(centrum).status_code == 200
        _view_where(centrum, lambda view: (view.get("progress", {}).get("step") or {}).get("label") == LOGIN)
        close(tmp_path / "przegladarka-efenix")
        # Bez wykrycia zamknięcia Wycena czekałaby do końca limitu logowania, 15 minut.
        assert wait_for(lambda: centrum.client.get("/api/runs/current").json()["state"] == "finished", 20)
        result = finished_view(centrum.client)["result"]
        following = centrum.start(dry_run=True)
        finished_view(centrum.client)
    [notification] = [
        item for item in centrum.client.get("/api/notifications").json()["items"] if item["kind"] == "wycena_w_efenix"
    ]

    assert ([stop["what"] for stop in result["stops"]], following.status_code) == (
        ["Okno efenix zostało zamknięte, więc Wycena w efenix się zatrzymała. W efenix nic się nie zmieniło."],
        200,
    )
    assert (notification["stopped"], notification["orders"], notification["unread"]) == (result["stops"][0]["what"], None, True)
    [logged] = [record for record in records(centrum) if record["process"] == "efenix"]
    trace = logged["trace"]
    assert ([trace["exception_type"], *(link["exception_type"] for link in trace["causes"])][:2], logged["stop_kind"]) == (
        ["rozliczenia.message.StopError", "rozliczenia.efenix_window.WindowClosed"],
        "for_tata",
    )


# Zatrzymanie okna efenix przy wierszu 19, gdy wiersz 18 jest już gotowy (Zgłoszenia #19 i #20 z
# MAXIMISEART-Dad-zgloszenia): zlecenie Atrapy w wierszu 19 i przyczyna, którą Logi mają podać. Hipotezy B, D i E z
# tabeli decyzji (``tests/test_tabela_zatrzyman_efenix.py``); hipoteza A od #819 nie jest Zatrzymaniem.
STOPPED_AT_SECOND = [PRICED[0], Order("#ZLQX07", worker="gosia.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})))]
HYPOTHESES = {
    "B-ilosc-niecalkowita": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), changed=Changed.QUANTITY_VALUE),
        {"what": "wartość pola Ilość, która nie jest liczbą całkowitą", "positions": ["012"]},
        ["szukanie"],
        "otwarcie zlecenia",
    ),
    "D-zerwane-otwarcie-strony": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), cut=True),
        {
            "what": "błąd przeglądarki w działaniu okna",
            "error_type": "playwright._impl._errors.Error",
            "operation": "otwarcie strony",
        },
        ["szukanie"],
        "otwarcie zlecenia",
    ),
    "D-strona-bledu-http": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), error_status=HTTPStatus.INTERNAL_SERVER_ERROR),
        {"what": "strona błędu HTTP serwera efenix zamiast strony albo odpowiedzi, na którą czekało okno", "status": 500},
        ["szukanie"],
        "otwarcie zlecenia",
    ),
    "D-strona-bledu-http-404": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), error_status=HTTPStatus.NOT_FOUND),
        {"what": "strona błędu HTTP serwera efenix zamiast strony albo odpowiedzi, na którą czekało okno", "status": 404},
        ["szukanie"],
        "otwarcie zlecenia",
    ),
    "D-strona-bledu-http-po-wycenie-emmetta": (
        replace(
            STOPPED_AT_SECOND[1].in_efenix("617"),
            execution_date=DAY,
            error_status=HTTPStatus.INTERNAL_SERVER_ERROR,
            after_emmett=True,
        ),
        {"what": "strona błędu HTTP serwera efenix zamiast strony albo odpowiedzi, na którą czekało okno", "status": 500},
        ["szukanie", "otwarcie zlecenia"],
        "Wycena Emmetta",
    ),
    "E-formularz-logowania-po-wycenie-emmetta": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), execution_date=DAY, login_form=True, after_emmett=True),
        {"what": "formularz logowania efenix pod adresem strony zlecenia, bez przekierowania"},
        ["szukanie", "otwarcie zlecenia"],
        "Wycena Emmetta",
    ),
    "E-formularz-logowania-pod-adresem-zlecenia": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), login_form=True),
        {"what": "formularz logowania efenix pod adresem strony zlecenia, bez przekierowania"},
        ["szukanie"],
        "otwarcie zlecenia",
    ),
}


@pytest.mark.parametrize(("second", "cause", "steps", "failed"), HYPOTHESES.values(), ids=HYPOTHESES.keys())
def test_logi_zatrzymania_okna_efenix_maja_przyczyne_wiersz_miejsce_w_przebiegu_i_slad_zlecen_sprzed_niego(
    tmp_path: Path, second: AtrapaOrder, cause: dict[str, Any], steps: list[str], failed: str
) -> None:
    """Okno efenix staje przy zleceniu w wierszu 19, a Logi Uruchomienia, które idą do Maksa same, bez Diagnozy, mówią
    dlaczego: przyczynę z zamkniętej listy (kody pozycji, budowę strony albo typ błędu Playwrighta z działaniem
    przeglądarki), wiersz, miejsce „2 z 2”, udane działania przy nim i działanie, które się nie udało, oraz ślad gotowego
    zlecenia z wiersza 18. Ślad wywołań ma łańcuch przyczyn do wyjątku okna. Komunikat taty jest ten sam co bez przyczyny,
    a ślad zleceń nie ma numeru zlecenia, a Logi adresu."""

    with atrapa_efenix([PRICED[0].in_efenix("611"), second]) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, STOPPED_AT_SECOND)
        assert _start_pricing(centrum).status_code == 200
        result = finished_view(centrum.client)["result"]
    [record] = records(centrum)
    stop, trace = record["efenix_stop"], record["trace"]

    assert ([message["where"] for message in result["stops"]], record["stop_kind"]) == (
        ["okno efenix, strona zlecenia z datą wykonania i wyceną"],
        "for_maks",
    )
    assert {key: value for key, value in stop["cause"].items() if value is not None} == {"part": "ORDER", **cause}
    assert (stop["row"], stop["order"], stop["orders"]) == (19, 2, 2)
    assert ([step["action"] for step in stop["steps"]], stop["failed"]["action"]) == (steps, failed)
    assert [(order["row"], order["outcome"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]] == [
        (18, "gotowe", ["szukanie", "otwarcie zlecenia"])
    ]
    assert [trace["exception_type"], *(cause["exception_type"] for cause in trace["causes"])][:2] == [
        "rozliczenia.message.StopError",
        "rozliczenia.efenix_window.UnexpectedPage",
    ]
    text = log_files(centrum)[0].read_text(encoding="utf-8")
    traced_text = json.dumps(record["efenix_orders"], ensure_ascii=False)
    assert [order.number for order in STOPPED_AT_SECOND if zawiera_wartosc(traced_text, order.number)] == []
    assert [marker for marker in ("TESTOWA", "Testowa", "Miasto-Dzielnica") if marker in text] == [], "ADRES"


def test_logi_zatrzymania_okna_efenix_na_elemencie_strony_nie_dokladnie_raz_maja_jego_selektor_i_liczbe(tmp_path: Path) -> None:
    """Strona zlecenia nie ma przycisku Emmetta, gdy okno ładuje Wycenę Emmetta zlecenia z wiersza 19: Logi
    Uruchomienia mówią Maksowi, który element strony okno znalazło ile razy (tu 0), a nie tylko, że budowa się zmieniła."""

    orders = [PRICED[0], Order("#ZLQX08", worker="gosia.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 1})]
    with atrapa_efenix([orders[0].in_efenix("611"), orders[1].in_efenix("618")], changed=Changed.EMMETT_BUTTON) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, orders)
        assert _start_pricing(centrum).status_code == 200
        finished_view(centrum.client)
    [record] = records(centrum)
    stop = record["efenix_stop"]

    assert {key: value for key, value in stop["cause"].items() if value is not None} == {
        "part": "EMMETT",
        "what": "element strony nie występuje dokładnie raz",
        "element": "#button_emmett",
        "count": 0,
    }
    assert (stop["row"], stop["failed"]["action"]) == (19, "Wycena Emmetta")


@dataclass(frozen=True)
class StartPath:
    """Droga startu okna efenix, która kończy Wycenę Zatrzymaniem (tabela w ``tests/test_tabela_zatrzyman_efenix.py``):
    jak test ją wywołuje i co mówią o niej Logi Uruchomienia.

    ``driver``: sterownik Playwrighta pod adresem, pod którym go nie ma; ``profile_file``: folder profilu przeglądarki
    okna jest plikiem, więc przeglądarka nie startuje; ``outage``, ``error_answer``: Atrapa przy pierwszym żądaniu.
    ``cause``: przyczyna techniczna ``efenix_stop.cause`` bez pól ``None`` (``error_type`` ``None``: dowolny błąd
    Playwrighta, którego typ zależy od systemu), ``chain``: wyjątek Zatrzymania, wyjątek okna (nazwa drogi startu) i
    jego źródło w śladzie wywołań, ``raised``: funkcja kodu narzędzia, w której wyjątek okna powstał.
    """

    stop_kind: str
    code: str
    cause: dict[str, Any]
    chain: list[str | None]
    raised: str
    driver: bool = False
    profile_file: bool = False
    outage: tuple[Outage, int] | None = None
    error_answer: tuple[str, int, HTTPStatus] | None = None


_BROWSER_FAILURE = "błąd przeglądarki w działaniu okna"
_PLAYWRIGHT_ERROR = "playwright._impl._errors.Error"
_STOP_ERROR = "rozliczenia.message.StopError"
START_PATHS = {
    "sterownik-playwrighta-nie-wystartowal": StartPath(
        "for_tata",
        "EFENIX_BRAK_PRZEGLADARKI",
        {"what": _BROWSER_FAILURE, "error_type": "FileNotFoundError", "operation": "start sterownika Playwrighta"},
        [_STOP_ERROR, "rozliczenia.efenix_window.BrowserNotStarted", "FileNotFoundError"],
        "_playwright",
        driver=True,
    ),
    "przegladarka-nie-wystartowala": StartPath(
        "for_tata",
        "EFENIX_BRAK_PRZEGLADARKI",
        {"what": _BROWSER_FAILURE, "error_type": None, "operation": "start przeglądarki"},
        [_STOP_ERROR, "rozliczenia.efenix_window.BrowserNotStarted", None],
        "chrome",
        profile_file=True,
    ),
    "efenix-nie-odpowiada": StartPath(
        "for_tata",
        "EFENIX_NIEDOSTEPNY",
        {"part": "LIST", "what": _BROWSER_FAILURE, "error_type": _PLAYWRIGHT_ERROR, "operation": "otwarcie strony"},
        [_STOP_ERROR, "rozliczenia.efenix_window.EfenixUnreachable", _PLAYWRIGHT_ERROR],
        "open_list",
        outage=(Outage.CUT, 0),
    ),
    "lista-to-strona-bledu-http": StartPath(
        "for_maks",
        "EFENIX_OKNO_ZATRZYMANE",
        {"part": "LIST", "what": "strona błędu HTTP serwera efenix zamiast strony albo odpowiedzi, na którą czekało okno", "status": 500},
        [_STOP_ERROR, "rozliczenia.efenix_window.UnexpectedPage", "rozliczenia.efenix_window.UnexpectedPage"],
        "open_list",
        error_answer=(LIST_PAGE, 1, HTTPStatus.INTERNAL_SERVER_ERROR),
    ),
}


@pytest.mark.parametrize("path", START_PATHS.values(), ids=START_PATHS.keys())
def test_logi_wyceny_zatrzymanej_przy_starcie_okna_efenix_nazywaja_droge_startu_typ_wyjatku_i_ramki_kodu_narzedzia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], path: StartPath
) -> None:
    """Okno efenix nie otwiera listy zleceń przy starcie (#976): Logi Uruchomienia, które idą do Maksa same, także przy
    Zatrzymaniu dla taty, mówią, która droga startu zawiodła: przyczynę techniczną bez zlecenia (``row`` ``None``) i
    ślad wywołań z nazwą wyjątku okna (``BrowserNotStarted``, ``EfenixUnreachable``, ``UnexpectedPage``), typem jego
    źródła i ramką kodu narzędzia, w której powstał, bez treści wyjątku. Narzędzie odtwarzania pokazuje tę przyczynę, a
    Logi nie mają adresu z Pliku zbiorczego."""

    if path.driver:
        monkeypatch.setenv("PLAYWRIGHT_NODEJS_PATH", str(tmp_path / "bez-sterownika" / "node"))
    if path.profile_file:
        (tmp_path / "przegladarka-efenix").write_text("", encoding="utf-8")
    with atrapa_efenix([PRICED[0].in_efenix("611")], outage_from=path.outage, error_answer=path.error_answer) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        assert _start_pricing(centrum).status_code == 200
        finished_view(centrum.client)
    monkeypatch.delenv("PLAYWRIGHT_NODEJS_PATH", raising=False)
    [record] = records(centrum)
    stop, trace = record["efenix_stop"], record["trace"]
    cause = {key: value for key, value in stop["cause"].items() if value is not None}
    chain = [trace["exception_type"], *(link["exception_type"] for link in trace["causes"])][:3]
    window_frames = trace["causes"][0]["frames"]

    assert ([message["code"] for message in record["messages"]], record["stop_kind"]) == ([path.code], path.stop_kind)
    if path.cause.get("error_type", "") is None:
        assert cause.pop("error_type").startswith("playwright._impl._errors."), cause
    assert cause == {key: value for key, value in path.cause.items() if value is not None}
    assert (stop["row"], stop["order"], stop["steps"], stop["failed"]) == (None, None, [], None)
    if path.chain[2] is None:
        assert chain[2].startswith("playwright._impl._errors."), chain
    assert chain == [path.chain[0], path.chain[1], path.chain[2] or chain[2]]
    assert (window_frames[-1]["file"], window_frames[-1]["function"]) == ("src/rozliczenia/efenix_browser.py", path.raised)
    text = log_files(centrum)[0].read_text(encoding="utf-8")
    assert [marker for marker in ("TESTOWA", "Testowa", "Miasto-Dzielnica") if marker in text] == [], "ADRES"

    replay_lines = _replay_report(capsys, log_files(centrum)[0])
    [shown] = [line for line in replay_lines if line.startswith("Przyczyna w Logach: ")]
    logged = stop["cause"]
    details = [str(logged[key]) for key in ("operation", "error_type") if logged[key] is not None]
    details += [] if logged["status"] is None else [f"HTTP {logged['status']}"]
    assert shown.split("; wyjątki ")[0] == f"Przyczyna w Logach: okno efenix przy starcie okna: {logged['what']} ({', '.join(details)})"
    assert f"; wyjątki {' ← '.join(chain)}" in shown and shown.endswith(f" w {path.raised}"), shown


def _replay_report(capsys: pytest.CaptureFixture[str], logs: Path) -> list[str]:
    """Linie raportu narzędzia odtwarzania (``tools/odtworz_uruchomienie.py``) z pliku Logów ``logs`` na tym drzewie."""

    capsys.readouterr()
    odtworz_uruchomienie.main([str(logs), "--na-tym-drzewie", "--efenix-dzis", TODAY.isoformat()])
    return capsys.readouterr().out.splitlines()


def test_logi_wyceny_w_efenix_maja_slad_kazdego_zlecenia_bez_numeru_zlecenia_i_bez_adresu(tmp_path: Path) -> None:
    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        write_report_key(ToolDirectory(tmp_path))
        assert _start_pricing(centrum).status_code == 200
        assert finished_view(centrum.client)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    [record] = records(centrum)
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    texts += in_box(box)

    traced = [(order["row"], order["outcome"], order["code"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]]
    emmett_steps = ["szukanie", "otwarcie zlecenia", "data wykonania", "otwarcie zlecenia", "Wycena Emmetta"]
    assert traced == [
        (18, "gotowe", None, ["szukanie", "otwarcie zlecenia"]),
        (19, "błąd", "EFENIX_NIEZNANY_NUMER", ["szukanie"]),
        (20, "ostrzeżenie Emmetta", "EFENIX_WIECEJ_NIZ_PLIK", emmett_steps),
        (21, "błąd", "EFENIX_NIEZNANY_NUMER", ["szukanie"]),
        (22, "ostrzeżenie Emmetta", "EFENIX_WIECEJ_NIZ_PLIK", emmett_steps),
        (23, "ostrzeżenie Emmetta", "EFENIX_WIECEJ_NIZ_PLIK", emmett_steps),
    ]
    emmett = record["efenix_orders"][2]
    assert (emmett["file"], emmett["steps"][-1]["quantities"]["012"], emmett["steps"][0]["found"]) == ({"012": 1}, 2, 1)
    moments = [utc(step["started_at"]) for order in record["efenix_orders"] for step in order["steps"]]
    assert utc(record["started_at"]) <= moments[0]
    assert moments == sorted(moments) and moments[-1] <= utc(record["ended_at"]), "godziny działań w kolejności zleceń"
    traced_text = json.dumps(record["efenix_orders"], ensure_ascii=False)
    assert [order.number for order in PRICED if zawiera_wartosc(traced_text, order.number)] == [], "ślad bez numeru"
    private = ["TESTOWA", "Testowa", "PRYWATNA", "Miasto-Dzielnica", in_json(tmp_path)]
    assert [marker for marker in private if any(marker in text for text in texts)] == []


# Każdy odczyt strony efenix w Logach (#843), wiersze 18–23 po Wykonawcach: zlecenie, które proces wycenia (data wykonania,
# Wycena Emmetta, ilość), zlecenie z innym statusem, z innym lokalem, z inną ulicą i numerem domu, numer, pod którym
# efenix pokazuje tylko inne zlecenie, i numer, którego efenix nie zna wcale. Adresy i numery są wymyślone.
_FILE_ADDRESS = "UL. ZAWILCOWA 12/3"
_EFENIX_ADDRESS = "Miastowo-Centrum ul.Zawilcowa 12 Lokal 3"


def _read_order(number: str, worker: str, *, efenix_address: str = _EFENIX_ADDRESS) -> Order:
    amount = float(amount_of({"012": 1}))
    return Order(number, worker=worker, address=_FILE_ADDRESS, efenix_address=efenix_address, cells={"O": 1}, amount=amount)


READ = [
    _read_order("#ZLQS01", "adrian.testowy"),
    _read_order("#ZLQS02", "beata.testowa"),
    _read_order("#ZLQS03", "celina.testowa", efenix_address="Miastowo-Centrum ul.Zawilcowa 12 Lokal 4"),
    _read_order("#ZLQS04", "dorota.testowa", efenix_address="Miastowo-Centrum ul.Rumiankowa 14 Lokal 3"),
    _read_order("#ZLQS05", "ewa.testowa"),
    _read_order("#ZLQS06", "filip.testowy"),
]
READ_IN_EFENIX = [
    READ[0].in_efenix("631"),
    replace(READ[1].in_efenix("632"), status="W realizacji"),
    READ[2].in_efenix("633"),
    READ[3].in_efenix("634"),
    replace(READ[4].in_efenix("635"), number="ZLQS050", realizator="gustaw.testowy", status="Rozliczone"),
]


def _listed(same_number: bool, status: str, realizator: str, address: list[str]) -> dict[str, Any]:
    return {"same_number": same_number, "status": status, "realizator": realizator, "address": address}


def test_logi_wyceny_w_efenix_maja_odczyt_kazdej_strony_efenix_ze_statusem_realizatorem_i_czesciami_adresu_bez_danych_adresowych(
    tmp_path: Path,
) -> None:
    """Logi Wyceny w efenix mówią, co narzędzie zobaczyło w efenix (#843): po szukaniu liczbę wyników i przy każdym
    status, login realizatora, czy to numer z pliku i które części adresu (ulica, numer domu, lokal) różnią się od ``ADRES``,
    po otwarciu zlecenia jego status i realizatora, a ze strony zlecenia datę wykonania, kwotę i ilość każdej pozycji, także
    po zapisie daty, Wyceny Emmetta i ilości. Zlecenie z innym statusem ma ten status, zlecenie z innym adresem tylko nazwy
    różniących się części, a nieznany numer to, co zwróciło szukanie. Dane adresowe pliku i Atrapy nie wychodzą ani do
    pliku Logów, ani do Skrzynki Zgłoszeń."""

    with atrapa_efenix(READ_IN_EFENIX) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, READ)
        write_report_key(ToolDirectory(tmp_path))
        assert _start_pricing(centrum).status_code == 200
        assert finished_view(centrum.client)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    [record] = records(centrum)
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    texts += [part for issue in box.background_issues for part in (issue.title, issue.body, *issue.comments)]
    page_codes = {position.code for position in CATALOG if position.kind == "ILOSC"}

    def read(step: dict[str, Any]) -> tuple[Any, ...]:
        match step["action"]:
            case "szukanie":
                return ("szukanie", step["found"], step["results"])
            case "otwarcie zlecenia":
                return ("otwarcie zlecenia", step["status"], step["realizator"], step["execution_date"], step["amount"], step["quantities"])
            case "data wykonania":
                return ("data wykonania", step["execution_date"], step["accepted"])
            case "Wycena Emmetta":
                return ("Wycena Emmetta", step["execution_date"], step["amount"], step["quantities"])
            case "ilość":
                return ("ilość", step["position"], step["quantity"], step["amount"])
            case _:
                raise AssertionError(step["action"])

    empty = dict.fromkeys(sorted(page_codes), 0)
    priced = str(amount_of({"012": 1}))
    assert [(order["row"], order["code"], [read(step) for step in order["steps"]]) for order in record["efenix_orders"]] == [
        (
            18,
            None,
            [
                ("szukanie", 1, [_listed(True, "Do wyceny", "adrian.testowy", [])]),
                ("otwarcie zlecenia", "Do wyceny", "adrian.testowy", None, "0.00", empty),
                ("data wykonania", DAY.isoformat(), True),
                ("otwarcie zlecenia", "Do wyceny", "adrian.testowy", DAY.isoformat(), "0.00", empty),
                ("Wycena Emmetta", DAY.isoformat(), "0.00", empty),
                ("ilość", "012", 1, priced),
            ],
        ),
        (19, "EFENIX_INNY_STATUS", [("szukanie", 1, [_listed(True, "W realizacji", "beata.testowa", [])])]),
        (20, "EFENIX_INNY_ADRES", [("szukanie", 1, [_listed(True, "Do wyceny", "celina.testowa", ["lokal"])])]),
        (21, "EFENIX_INNY_ADRES", [("szukanie", 1, [_listed(True, "Do wyceny", "dorota.testowa", ["ulica", "numer domu"])])]),
        (22, "EFENIX_NIEZNANY_NUMER", [("szukanie", 1, [_listed(False, "Rozliczone", "gustaw.testowy", [])])]),
        (23, "EFENIX_NIEZNANY_NUMER", [("szukanie", 0, [])]),
    ]
    # Numer zlecenia może wyjść (ADR 0025) i stoi w Kopii wejścia, ale nie w śladzie zleceń; adresu nie ma nigdzie.
    traced_text = json.dumps(record["efenix_orders"], ensure_ascii=False)
    numbers = [*(order.number for order in READ), "ZLQS050"]
    assert [number for number in numbers if zawiera_wartosc(traced_text, number)] == []
    private = [_FILE_ADDRESS, "ZAWILCOWA", "Zawilcowa", "Rumiankowa", "Miastowo"]
    assert [marker for marker in private if any(marker in text for text in texts + in_box(box))] == []
    assert record["technical_notes"] == []


def test_uwaga_taty_po_wycenie_w_efenix_nie_wynosi_adresu_z_pliku_zbiorczego_ani_danych_adresowych_efenix(
    tmp_path: Path,
) -> None:
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, orders=FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        assert _start_pricing(centrum).status_code == 200
        assert finished_view(centrum.client)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    efenix_address = PRICED[0].efenix_address

    sent = centrum.client.post("/api/dad-notes", json={"title": "Adresy", "body": f"{PRICED[1].address}\n{efenix_address}"})

    assert sent.json() == {"state": "sent"}
    [issue] = centrum.surroundings.report_box.issues_with("uwaga-taty")
    assert issue.body.splitlines()[:3] == [
        "[adres]",
        "[adres]",
        "Reguła danych: zamaskowano wartość kolumny ADRES w: treść Uwagi taty.",
    ]


# Dziennik działań taty (#839): co tata robił w Centrum od poprzedniego Uruchomienia, z godzinami, bez treści Uwagi taty.

NOTE_TITLE = "Tytuł Uwagi SYNTETYCZNY-TYTUŁ"
NOTE_BODY = "Treść Uwagi SYNTETYCZNA-TREŚĆ"


def logged_record(centrum: SettlingCentrum, run_id: str) -> tuple[str, dict[str, Any]]:
    [path] = centrum.tool.run_logs.glob(f"*-{run_id}.json")
    text = path.read_text(encoding="utf-8")
    return text, json.loads(text)


def dad_actions(record: dict[str, Any]) -> list[tuple[str, ...]]:
    def facts(action: dict[str, Any]) -> tuple[str, ...]:
        rest = [action[key] for key in ("page", "kind", "operation", "process", "mode") if action.get(key) is not None]
        return (action["action"], *rest)

    return [facts(action) for action in record["dad_actions"]["entries"]]


def action_moments(record: dict[str, Any]) -> list[datetime]:
    return [datetime.fromisoformat(action["at"]) for action in record["dad_actions"]["entries"]]


def logs_comments(fake: FakeReportBox) -> list[str]:
    return [comment for issue in fake.background_issues if issue.label == "logi-uruchomienia" for comment in issue.comments]


# Odnośnik komentarza Logów do pliku w Archiwum Logów okresu (#844): nazwa pliku i tag Archiwum z adresu pobrania.
ARCHIVE_LINK = re.compile(r"\[(?P<name>[^\]]+)\]\(https://github\.com/[^/]+/[^/]+/releases/download/(?P<tag>[^/]+)/(?P=name)\)")


def logs_arrived(fake: FakeReportBox, count: int) -> bool:
    """Skrzynka ma ``count`` komentarzy Logów i każdy prowadzi już do pełnych Logów w Archiwum Logów okresu.

    Komentarz Wyceny w efenix powstaje przy jej starcie jako komentarz postępu bez odnośnika (#846), a Logi zmieniają go
    dopiero później, więc sama liczba komentarzy przychodzi przed Logami (#923).
    """

    comments = logs_comments(fake)
    return len(comments) == count and all(ARCHIVE_LINK.search(comment) is not None for comment in comments)


def logs_file(fake: FakeReportBox, comment: str) -> bytes:
    """Pełne Logi z pliku w Archiwum Logów okresu, do którego prowadzi komentarz Logów, rozpakowane bajt w bajt."""

    found = ARCHIVE_LINK.search(comment)
    assert found is not None, comment
    return fake.archived(found["tag"])[found["name"]]


def logs_text(fake: FakeReportBox, comment: str) -> str:
    return logs_file(fake, comment).decode("utf-8")


def in_box(fake: FakeReportBox) -> list[str]:
    """Wszystko, co Maks dostaje w Skrzynce: tytuły, treści i komentarze issue oraz rozpakowane pliki w Archiwach."""

    issues = [part for issue in fake.background_issues for part in (issue.title, issue.body, *issue.comments)]
    return issues + [asset.text for archive in fake.archives for asset in archive.assets]


def test_dzialania_taty_miedzy_dwoma_uruchomieniami_sa_w_logach_drugiego_z_godzinami_bez_tresci_uwagi_taty(
    tmp_path: Path,
) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    first = run_to_end(centrum, dry_run=True)["run"]["id"]

    client = centrum.client
    assert client.post("/api/view-timings", json=view_timing(kind="navigation", page="okresy")).status_code == 204
    assert client.put("/api/settings/theme", json={"theme": "dark"}).status_code == 200
    assert client.post("/api/dad-notes/draft", json={"title": NOTE_TITLE, "body": NOTE_BODY}).status_code == 200
    assert client.post("/api/dad-notes", json={"title": NOTE_TITLE, "body": NOTE_BODY}).status_code == 200
    assert client.post("/api/shutdown").status_code == 202
    centrum.restart()
    assert centrum.client.post("/api/view-timings", json=view_timing(page="uruchomienia")).status_code == 204
    second = run_to_end(centrum, dry_run=False)["run"]["id"]

    _, earlier = logged_record(centrum, first)
    text, later = logged_record(centrum, second)
    assert dad_actions(earlier) == [
        ("start Centrum",),
        ("przycisk", "choosePeriodsDirectory"),
        ("przycisk", "startRun", "settlement", "DRY-RUN"),
    ]
    assert dad_actions(later) == [
        ("widok", "okresy", "navigation"),
        ("przycisk", "changeTheme"),
        ("przycisk", "sendDadNote"),
        ("przycisk", "closeCentrum"),
        ("start Centrum",),
        ("widok", "uruchomienia", "cold_start"),
        ("przycisk", "startRun", "settlement", "RUN"),
    ]
    assert later["dad_actions"]["omitted"] == 0
    times = action_moments(later)
    assert all(moment.utcoffset() == timedelta(0) for moment in times), "godziny w UTC"
    assert times == sorted(times)
    assert datetime.fromisoformat(earlier["ended_at"]) <= times[0]
    assert times[-1] <= datetime.fromisoformat(later["started_at"])
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 2)), "Logi obu Uruchomień w Skrzynce"
    sent = logs_text(box, logs_comments(box)[1])
    assert '"operation": "sendDadNote"' in sent, "dziennik działań taty dociera do Maksa"
    assert [marker for marker in ("SYNTETYCZNY-TYTUŁ", "SYNTETYCZNA-TREŚĆ") if marker in text or marker in sent] == []


def test_logi_maja_najnowsze_dzialania_taty_do_limitu_a_liczbe_starszych_obok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tata długo przegląda Centrum przed Uruchomieniem: Logi mają ``MAX_ENTRIES`` najnowszych działań, ze startem tego
    Uruchomienia na końcu, a start Centrum, wybór folderu okresów i najstarszy widok liczy ``omitted``."""

    limit = 5
    monkeypatch.setattr("rozliczenia.centrum.dad_action_journal.MAX_ENTRIES", limit)
    centrum = settling_centrum(tmp_path)
    for _ in range(limit):
        assert centrum.client.post("/api/view-timings", json=view_timing(kind="navigation", page="okresy")).status_code == 204
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]

    _, record = logged_record(centrum, run_id)
    assert dad_actions(record) == [
        *[("widok", "okresy", "navigation")] * (limit - 1),
        ("przycisk", "startRun", "settlement", "DRY-RUN"),
    ]
    assert record["dad_actions"]["omitted"] == 3


def test_logi_maja_najwyzej_1000_najnowszych_dzialan_taty(tmp_path: Path) -> None:
    oldest = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    moments = [oldest + timedelta(seconds=second) for second in range(1001)]
    tmp_path.joinpath(DAD_ACTIONS_FILE).write_text(
        "".join(ViewOpened(at=at, action="widok", page="okresy", kind="navigation").model_dump_json() + "\n" for at in moments),
        encoding="utf-8",
    )

    taken = DadActionJournal(centrum_work(tmp_path, CentrumLog(tmp_path / "centrum.log"))).take()

    assert ([entry.at for entry in taken.entries], taken.omitted) == (moments[1:], 1)


def test_dziennik_dzialan_taty_ktorego_nie_da_sie_oproznic_oddaje_te_same_wpisy_takze_nastepnym_logom(tmp_path: Path) -> None:
    """Katalog Logów przyjmuje dopisanie, ale nie założenie pliku, więc podmiana pliku pada: dziennik działań taty po
    pierwszym Uruchomieniu zostaje pełny, a Logi drugiego Uruchomienia mają też jego wpisy, bo lepiej dwa razy niż wcale."""

    centrum = settling_centrum(tmp_path)
    logs = centrum.log_path.parent
    centrum.tool.run_logs.mkdir(parents=True, exist_ok=True)
    assert centrum.client.put("/api/settings/theme", json={"theme": "dark"}).status_code == 200
    with without_creating(logs):
        first = run_to_end(centrum, dry_run=True)["run"]["id"]
    second = run_to_end(centrum, dry_run=True)["run"]["id"]

    _, earlier = logged_record(centrum, first)
    _, later = logged_record(centrum, second)
    assert ("przycisk", "changeTheme") in dad_actions(earlier)
    assert ("przycisk", "changeTheme") in dad_actions(later)
    assert "dzialania-taty-niedostepne typ=" in centrum.log_path.read_text(encoding="utf-8")


def test_dziennik_dzialan_taty_ktorego_nie_da_sie_zapisac_jest_linia_dziennika_centrum_a_nie_bledem_przycisku(
    tmp_path: Path,
) -> None:
    """Na miejscu pliku dziennika działań taty stoi katalog: przyciski i Uruchomienie działają jak zawsze, Logi mają
    pusty dziennik, a dziennik Centrum mówi, że dziennika działań taty nie da się zapisać."""

    centrum = settling_centrum(tmp_path)
    journal = centrum.log_path.parent / DAD_ACTIONS_FILE
    journal.unlink(missing_ok=True)
    journal.mkdir()

    assert centrum.client.put("/api/settings/theme", json={"theme": "dark"}).status_code == 200
    view = run_to_end(centrum, dry_run=True)

    assert view["result"]["result"] == "OK"
    _, record = logged_record(centrum, view["run"]["id"])
    assert record["dad_actions"] == {"entries": [], "omitted": 0}
    assert "dzialania-taty-niedostepne typ=" in centrum.log_path.read_text(encoding="utf-8")


# Dziennik Wyceny w efenix (#845): ślad Wyceny na dysku taty w trakcie i Logi Urwanego Uruchomienia po starcie Centrum.

# Wiersze 18–22: gotowe po zapisach w efenix (data wykonania, Wycena Emmetta, ilość), gotowe bez zapisu (wycena już jest),
# sprzeczne z Emmettem, zlecenie, przy którym efenix staje po zapisie daty wykonania, i zlecenie, do którego przebieg
# nie dochodzi.
CUT = [
    Order("#ZLQZ01", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQZ02", worker="beata.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}),
    Order("#ZLQZ03", worker="celina.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 2}),
    Order("#ZLQZ04", worker="dorota.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQZ05", worker="ewa.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
]
CUT_IN_EFENIX = [
    CUT[0].in_efenix("631"),
    CUT[1].in_efenix("632"),
    CUT[2].in_efenix("633"),
    replace(CUT[3].in_efenix("634"), hung=True, after_date=True),
    CUT[4].in_efenix("635"),
]
# Wpis dziennika, który prąd urwał w trakcie zapisu.
TORN = '{"at": "2026-09-16T10:'


def journals(centrum: SettlingCentrum) -> list[Path]:
    return sorted((centrum.log_path.parent / "dzienniki-wyceny").glob("*"))


def journal_entries(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line != TORN]


def journal_entries_of(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line != TORN]


def journals_at_result(monkeypatch: pytest.MonkeyPatch, directory: Path) -> dict[Path, str]:
    """Każdy dziennik z katalogu ``directory`` tak, jak jest na dysku w chwili wyniku Wyceny, zanim działanie po wyniku
    dopisze do niego wpis końca albo go usunie (``Journal.end``): test, który udaje zgaśnięcie Centrum przed wynikiem,
    odkłada go na dysk."""

    kept: dict[Path, str] = {}
    ended = Journal.end

    def keeping(journal: Journal, run_id: str, result: RunResult) -> None:
        kept.update({path: path.read_text(encoding="utf-8") for path in directory.glob("*.jsonl")})
        ended(journal, run_id, result)

    monkeypatch.setattr(Journal, "end", keeping)
    return kept


def logs_json(fake: FakeReportBox, comment: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(logs_text(fake, comment))
    return loaded


def test_centrum_zgaszone_w_trakcie_wyceny_w_efenix_po_starcie_wysyla_logi_urwanego_uruchomienia_ze_zleceniami_sprzed_zgasniecia(
    tmp_path: Path,
) -> None:
    """Centrum gaśnie nagle, cały proces razem z oknem efenix, przy czwartym zleceniu, po zapisie jego daty wykonania w
    efenix, a prąd urywa wpis dziennika w trakcie zapisu. Dziennik Wyceny w efenix ma wpis „zaczynam zlecenie” każdego
    zlecenia, które Atrapa ma zmienione. Następny start Centrum zamyka dziennik jako Logi Urwanego Uruchomienia: trzy
    zlecenia skończone z wynikiem, kodem Komunikatu zlecenia sprzecznego z Emmettem i śladem, zlecenie zaczęte bez
    wyniku, jeden wpis nie do odczytania i działania taty sprzed zgaśnięcia, bez wyniku Uruchomienia. Te Logi idą do
    Skrzynki Zgłoszeń jak zwykłe Logi, karta po starcie pokazuje zlecenia sprzed zgaśnięcia, a Urwane Uruchomienie nie
    ma karty wiersza Historii ani Powiadomienia o zakończonej Wycenie. Skrzynka Zgłoszeń dostaje klucz dopiero od
    następnego startu, więc komentarz postępu tej Wyceny (#846) czeka w Kolejce wysyłki, a Logi Urwanego Uruchomienia
    zastępują go w jednym komentarzu."""

    with atrapa_efenix(CUT_IN_EFENIX) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, CUT)
        before, _ = atrapa.state()
        with centrum_process(tmp_path, atrapa.url) as process:
            status, started = process.post("/api/runs", {"process": "efenix", "period": PERIOD, "mode": "RUN"})
            stalled = wait_for(lambda: atrapa.state()[0][3].execution_date is not None, 120)
            process.kill()
        after, _ = atrapa.state()
    write_report_key(ToolDirectory(tmp_path))
    [journal] = journals(centrum)
    with journal.open("a", encoding="utf-8") as torn:
        torn.write(TORN)
    entries, journal_text = journal_entries(journal), journal.read_text(encoding="utf-8")
    centrum.restart()
    centrum.client.start()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    box = centrum.surroundings.report_box
    sent = box.wait_until(lambda fake: logs_arrived(fake, 1))
    run_id = started["run"]["id"]
    card = centrum.client.get(f"/api/runs/{run_id}/card").json()
    notifications = centrum.client.get("/api/notifications").json()["items"]
    centrum.client.stop()
    [comment] = logs_comments(box)
    [record] = records(centrum)

    assert (status, stalled, sent) == (200, True, True)
    changed = [row for row, (was, now) in enumerate(zip(before, after, strict=True), start=18) if was != now]
    begun = [entry["row"] for entry in entries if entry["entry"] == "zaczynam zlecenie"]
    assert (changed, [row for row in changed if row not in begun]) == ([18, 20, 21], []), "zmiana w efenix bez wpisu w dzienniku"
    assert [(entry["entry"], entry.get("row", entry.get("order", {}).get("row"))) for entry in entries] == [
        ("start Uruchomienia", None),
        ("zaczynam zlecenie", 18),
        ("zlecenie skończone", 18),
        ("zaczynam zlecenie", 19),
        ("zlecenie skończone", 19),
        ("zaczynam zlecenie", 20),
        ("zlecenie skończone", 20),
        ("zaczynam zlecenie", 21),
    ]
    assert (record["run_id"], record["ending"], record["result"], record["duration_ms"]) == (run_id, "interrupted", None, None)
    traced = [(order["row"], order["outcome"], order["code"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]]
    assert traced == [
        (18, "gotowe", None, ["szukanie", "otwarcie zlecenia", "data wykonania", "otwarcie zlecenia", "Wycena Emmetta", "ilość"]),
        (19, "gotowe", None, ["szukanie", "otwarcie zlecenia"]),
        (20, "ostrzeżenie Emmetta", "EFENIX_WIECEJ_NIZ_PLIK", ["szukanie", "otwarcie zlecenia", "data wykonania", "otwarcie zlecenia", "Wycena Emmetta"]),
    ]
    assert record["interruption"] == {"row": 21, "place": 4, "total": 5, "omitted": 1}
    assert dad_actions(record) == [
        ("start Centrum",),
        ("przycisk", "choosePeriodsDirectory"),
        ("start Centrum",),
        ("przycisk", "startRun", "efenix", "RUN"),
    ], "działania taty sprzed zgaśnięcia, bez startu Centrum po nim"
    assert utc(record["started_at"]) <= utc(record["ended_at"]) == utc(entries[-1]["at"])
    assert (logs_json(box, comment), "- Wynik: brak, Centrum zamknęło się w trakcie (Urwane Uruchomienie)" in comment) == (record, True)
    assert (previous["state"], previous["run"]["id"], previous["orders"]["title"]) == ("interrupted", run_id, "Zlecenia przed zamknięciem Centrum")
    assert {count["label"]: count["count"] for count in previous["orders"]["counts"]} == {
        "Gotowe do przekazania": 2,
        "Przekazane do akceptacji": 0,
        "Rozliczone": 0,
        "Błędy zleceń": 0,
        "Ostrzeżenia Emmetta": 1,
    }
    assert (card, [item for item in notifications if item["kind"] == "wycena_w_efenix"]) == ({"state": "missing"}, [])
    assert journals(centrum) == [], "dziennik, którego Logi przyjęła Kolejka wysyłki, znika"
    numbers = [order.number for order in CUT]
    assert [number for number in numbers if zawiera_wartosc(journal_text, number) or zawiera_wartosc(comment, number)] == []
    private = ["TESTOWA", "Testowa", "Miasto-Dzielnica"]
    assert [marker for marker in private if marker in journal_text or marker in comment] == []


def test_wycena_w_efenix_ktora_doszla_do_konca_nie_zostawia_dziennika_ktory_start_uznalby_za_urwany(tmp_path: Path) -> None:
    """Wycena w efenix doszła do wyniku, a Kolejka wysyłki przyjęła jej Logi, więc dziennik znika. Następny start Centrum
    nie ma czego zamknąć jako Urwane Uruchomienie: Skrzynka nie dostaje drugich Logów, a karta po starcie ma wynik z
    Logów."""

    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, orders=FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        assert _start_pricing(centrum).status_code == 200
        run_id = finished_view(centrum.client)["run"]["id"]
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    centrum.client.stop()
    [logs] = log_files(centrum)

    centrum.restart()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    centrum.client.stop()

    assert ((previous["state"], previous["run"]["id"]), len(logs_comments(box))) == (("restored", run_id), 1)
    assert (log_files(centrum), journals(centrum)) == ([logs], [])


def _pricing_cut_before_result(tmp_path: Path) -> tuple[SettlingCentrum, str, Path]:
    """Wycena w efenix, którą Centrum zgasło w trakcie zlecenia: dysk Centrum ma jej start (plik ostatniego startu i
    dziennik) i „zaczynam zlecenie” bez wpisu końca, a nie ma Logów, wiersza Historii ani wysyłki w kolejce, czyli to
    Urwane Uruchomienie (ADR 0017). Skrzynka Zgłoszeń ma klucz dopiero od następnego startu, więc nic z tej Wyceny do
    niej nie poszło. Zwraca też folder kolejki wysyłki."""

    centrum = settling_centrum(tmp_path)
    disk = LogsOnDisk(CentrumLog(centrum.log_path), journaled="efenix")
    disk.started(PRICING_START)
    disk.journal.begun(row=18, place=1, total=2)
    write_report_key(ToolDirectory(tmp_path))
    return centrum, PRICING_START.run_id, ToolDirectory(tmp_path).queue


def test_logi_urwanego_uruchomienia_po_ponownym_zgasnieciu_centrum_przed_wysylka_ida_przy_nastepnym_starcie_raz(
    tmp_path: Path,
) -> None:
    """Start Centrum zamyka dziennik jako Logi Urwanego Uruchomienia, ale Centrum gaśnie znowu przed startem serwera,
    więc przed wysyłką: dziennik zostaje obok pliku Logów. Następny start wysyła te Logi do Skrzynki raz, karta ma Urwane
    Uruchomienie, a dziennik znika."""

    centrum, run_id, _ = _pricing_cut_before_result(tmp_path)
    box = centrum.surroundings.report_box
    centrum.restart()
    centrum.client.stop()
    closed = ([(record["run_id"], record["ending"]) for record in records(centrum)], len(journals(centrum)), len(logs_comments(box)))

    centrum.restart()
    centrum.client.start()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    sent = box.wait_until(lambda fake: logs_arrived(fake, 1))
    centrum.client.stop()

    assert closed == ([(run_id, "interrupted")], 1, 0)
    assert (sent, [(logs["run_id"], logs["ending"]) for logs in (logs_json(box, comment) for comment in logs_comments(box))]) == (True, [(run_id, "interrupted")])
    assert ((previous["state"], previous["run"]["id"]), journals(centrum)) == (("interrupted", run_id), [])


def test_start_serwera_wysyla_logi_urwanego_uruchomienia_raz_po_wznowieniu_kolejki_wysylki(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Budowa aplikacji zamyka dziennik Urwanej Wyceny i niczego nie wysyła. Start serwera wznawia Kolejkę wysyłki i
    dopiero po tym kładzie w niej Logi Urwanego Uruchomienia, przed pierwszym zapytaniem karty, więc kolejka nie dostaje
    wysyłki przed swoim startem; zapytania karty po starcie nie wysyłają ich drugi raz."""

    centrum, run_id, _ = _pricing_cut_before_result(tmp_path)
    box = centrum.surroundings.report_box
    steps: list[str] = []
    resume, post = Outbox.resume, Outbox.post

    def resuming(outbox: Outbox) -> None:
        steps.append("wznowienie kolejki")
        resume(outbox)

    def queueing(outbox: Outbox, sent: Post) -> bool:
        steps.append(f"wysyłka {sent.rank.name} {sent.run_id}")
        return post(outbox, sent)

    monkeypatch.setattr(Outbox, "resume", resuming)
    monkeypatch.setattr(Outbox, "post", queueing)
    centrum.restart()
    built = list(steps)
    centrum.client.start()
    started = list(steps)
    for _ in range(3):
        assert centrum.client.get("/api/runs/current").status_code == 200
    sent = box.wait_until(lambda fake: logs_arrived(fake, 1))
    centrum.client.stop()

    assert (built, started, steps) == ([], ["wznowienie kolejki", f"wysyłka STAND_IN {run_id}"], started)
    assert (sent, len(logs_comments(box)), journals(centrum)) == (True, 1, [])


def test_dziennik_urwanej_wyceny_ktorego_logow_kolejka_wysylki_nie_przyjela_zostaje_do_nastepnego_startu(
    tmp_path: Path,
) -> None:
    """Kolejka wysyłki nie przyjmuje Logów Urwanego Uruchomienia (na miejscu jej folderu stoi plik): dziennik zostaje, a
    start po naprawie folderu wysyła te Logi do Skrzynki i dopiero wtedy dziennik znika."""

    centrum, run_id, queue = _pricing_cut_before_result(tmp_path)
    box = centrum.surroundings.report_box
    queue.parent.mkdir(parents=True, exist_ok=True)
    queue.write_text("", encoding="utf-8")  # plik zamiast folderu: zapis się nie uda
    centrum.restart()
    centrum.client.start()
    assert centrum.client.get("/api/runs/current").status_code == 200
    centrum.client.stop()
    kept = (len(journals(centrum)), len(logs_comments(box)))

    queue.unlink()
    centrum.restart()
    centrum.client.start()
    assert centrum.client.get("/api/runs/current").status_code == 200
    sent = box.wait_until(lambda fake: logs_arrived(fake, 1))
    centrum.client.stop()

    assert (kept, sent, logs_json(box, logs_comments(box)[0])["run_id"], journals(centrum)) == ((1, 0), True, run_id, [])


def test_krotki_proces_nie_pisze_dziennika_wyceny_w_efenix(tmp_path: Path) -> None:
    """Przebieg rozliczeń zbiera Logi po wyniku, jak przed dziennikiem Wyceny w efenix: w trakcie nic nie trafia na dysk."""

    centrum = settling_centrum(tmp_path)
    run_to_end(centrum, dry_run=False)
    centrum.client.stop()

    assert (len(log_files(centrum)), (centrum.log_path.parent / "dzienniki-wyceny").exists()) == (1, False)


def test_dziennik_wyceny_w_efenix_ktorego_nie_da_sie_zapisac_nie_zatrzymuje_wyceny_i_ma_jedna_linie_na_wycene_w_dzienniku_centrum(
    tmp_path: Path,
) -> None:
    """Katalog dzienników zajęty przez plik, a tata uruchamia Wycenę w efenix dwa razy w jednej pracy Centrum: każda
    kończy się tym samym wynikiem co z dziennikiem, a dziennik Centrum ma jedną linię o dzienniku Wyceny, bez treści
    błędu, na każdą Wycenę, nie jedną na każdy wpis."""

    blocked = tmp_path / "logs" / "dzienniki-wyceny"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        results = []
        for _ in range(2):
            assert _start_pricing(centrum).status_code == 200
            results.append(finished_view(centrum.client)["result"]["result"])
    centrum.client.stop()
    lines = [line for line in centrum.log_path.read_text(encoding="utf-8").splitlines() if "dziennik-wyceny" in line]

    assert (results, [len(record["efenix_orders"]) for record in records(centrum)]) == (["WYMAGA_SPRAWDZENIA"] * 2, [6, 6])
    assert [line.split(" ", 1)[1] for line in lines] == ["dziennik-wyceny-niedostepny typ=FileExistsError miejsce=wpis"] * 2


@pytest.mark.parametrize("unsent", [False, True], ids=["z-dziennika", "z-niewyslanych-logow"])
def test_logi_urwanego_uruchomienia_w_pliku_i_w_skrzynce_przechodza_przez_straznika_reguly_danych(
    tmp_path: Path, unsent: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zlecenie skończone przed zgaśnięciem Centrum ma w śladzie pozycje odczytane ze strony efenix, a wśród nich ulicę i
    telefon (wolny tekst, ADR 0025). Start Centrum zamyka dziennik jako Logi Urwanego Uruchomienia, także gdy Logi zapisała
    już poprzednia praca Centrum sprzed strażnika, która zgasła przed ich wysyłką: plik Logów i plik w Archiwum Logów
    okresu, do którego prowadzi jedyny komentarz w Skrzynce, mają te same bajty, także z zapisem tekstowym Windows, z
    zamaskowaną ulicą i telefonem."""

    windows_text_writes(monkeypatch)
    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    started = StartFacts(
        run_id="b" * 32,
        process="efenix",
        mode=RunMode.RUN,
        period=PERIOD,
        started_at=utc("2026-09-16T10:15:00+00:00"),
    )
    step = LoggedStep(
        action=WindowAction.OPEN,
        duration_ms=120,
        found=None,
        execution_date=None,
        amount=None,
        quantities={STREET: 1, f"tel. {PHONE}": 2},
        position=None,
        quantity=None,
        accepted=None,
    )
    order = LoggedOrder(row=18, outcome=OrderKind.READY, code=None, file={}, file_amount=Decimal(0), steps=[step])
    ended_at = utc("2026-09-16T10:16:00+00:00")
    left_journal(centrum.log_path.parent, started, ended_line(ended_at, order))
    if unsent:
        logs = centrum.tool.run_logs / name_of(started)
        logs.parent.mkdir(parents=True)
        written = RunLog.interrupted(
            started,
            ended_at=ended_at,
            orders=[order],
            interruption=LoggedInterruption(row=None, place=None, total=None, omitted=0),
            tool=Tool(wydanie=None, commit=TOOL_COMMIT),
            environment=Environment(system="Windows-11", python="3.12.7", files=None),
            dad_actions=DadActions(entries=[], omitted=0),
        )
        logs.write_text(written.text, encoding="utf-8")

    centrum.restart()
    centrum.client.start()
    centrum.client.get("/api/runs/current")
    box = centrum.surroundings.report_box
    sent = box.wait_until(lambda fake: logs_arrived(fake, 1))
    centrum.client.stop()
    [comment] = logs_comments(box)
    [path] = log_files(centrum)
    data = path.read_bytes()
    archived = logs_file(box, comment)

    assert (sent, archived == data, journals(centrum)) == (True, True, [])
    text = data.decode("utf-8")
    [logged] = json.loads(text)["efenix_orders"]
    assert logged["steps"][0]["quantities"] == {"[ulica]": 1, "tel. [telefon]": 2}
    assert [value for value in (STREET, PHONE) if any(value in kept for kept in (text, comment))] == []


def test_dziennik_urwany_przy_pierwszym_wpisie_start_usuwa_bez_logow(tmp_path: Path) -> None:
    """Prąd zgasł w trakcie pierwszego zapisu dziennika, zanim Wycena cokolwiek zmieniła w efenix: dziennik bez linii
    startu nie mówi, czyje to Uruchomienie, więc start Centrum go usuwa i nie robi z niego Logów."""

    centrum = settling_centrum(tmp_path)
    directory = centrum.log_path.parent / "dzienniki-wyceny"
    directory.mkdir(parents=True)
    (directory / f"20260916T101500Z-efenix-{'a' * 32}.jsonl").write_text(TORN, encoding="utf-8")

    centrum.restart()
    centrum.client.get("/api/runs/current")
    centrum.client.stop()

    assert (journals(centrum), log_files(centrum)) == ([], [])


def test_plik_logow_ktorego_system_nie_daje_odczytac_zostawia_dziennik_do_nastepnego_startu(tmp_path: Path) -> None:
    """System odmawia odczytu pliku Logów Uruchomienia z dziennikiem Wyceny (tu w jego miejscu stoi katalog), więc start
    Centrum nie wie, czy Logi są i jakie: niczego za to Uruchomienie nie wysyła i zostawia dziennik następnemu startowi, z
    linią dziennika Centrum."""

    centrum = settling_centrum(tmp_path)
    started = StartFacts(
        run_id="d" * 32,
        process="efenix",
        mode=RunMode.RUN,
        period=PERIOD,
        started_at=utc("2026-09-16T10:15:00+00:00"),
    )
    journal = left_journal(centrum.log_path.parent, started)
    (centrum.tool.run_logs / name_of(started)).mkdir(parents=True)

    centrum.restart()
    centrum.client.get("/api/runs/current")
    centrum.client.stop()
    lines = [line for line in centrum.log_path.read_text(encoding="utf-8").splitlines() if "dziennik-wyceny" in line]

    assert journals(centrum) == [journal]
    assert [line.endswith("miejsce=start") for line in lines] == [True]


@pytest.mark.parametrize("ended", [False, True], ids=["bez-wpisu-konca", "z-wpisem-konca"])
def test_logi_z_pliku_w_katalogu_ktorego_nie_da_sie_wylistowac_ida_do_skrzynki_bez_wersji_zastepczej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ended: bool
) -> None:
    """Dziennik Wyceny w efenix ma obok czytelny plik Logów, których przyjęcia przez kolejkę nikt nie zapisał, a start
    Centrum nie może wylistować katalogu Logów. Start nie bierze tego za brak pliku: nie nadpisuje Logów Logami Urwanego
    Uruchomienia ani nie wysyła wyniku bez Logów, a Logi z pliku, bajt w bajt, trafiają do Skrzynki najpóźniej po
    następnym starcie, kiedy dziennik znika."""

    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    started = StartFacts(
        run_id="d" * 32,
        process="efenix",
        mode=RunMode.RUN,
        period=PERIOD,
        started_at=utc("2026-09-16T10:15:00+00:00"),
    )
    name = name_of(started)
    left_journal(centrum.log_path.parent, started, *([end_line(started.started_at + timedelta(minutes=9))] if ended else []))
    logs = RunLog.interrupted(
        started,
        ended_at=started.started_at + timedelta(minutes=5),
        orders=[],
        interruption=LoggedInterruption(row=None, place=None, total=None, omitted=0),
        tool=Tool(wydanie=None, commit=TOOL_COMMIT),
        environment=Environment(system="Windows-11", python="3.12.7", files=None),
        dad_actions=DadActions(entries=[], omitted=0),
    ).model_copy(update={"technical_notes": ["Logi z pliku"]})
    path = centrum.tool.run_logs / name
    path.parent.mkdir(parents=True)
    path.write_text(logs.text, encoding="utf-8", newline="")
    written = path.read_bytes()

    with unlisted(monkeypatch, path.parent):
        centrum.restart()
        centrum.client.start()
        centrum.client.get("/api/runs/current")
        centrum.client.stop()
    after_refusal = path.read_bytes()
    centrum.restart()
    centrum.client.start()
    centrum.client.get("/api/runs/current")
    box = centrum.surroundings.report_box
    sent = box.wait_until(lambda fake: logs_arrived(fake, 1))
    centrum.client.stop()

    assert (sent, after_refusal == written, journals(centrum)) == (True, True, [])
    assert [logs_file(box, comment) for comment in logs_comments(box)] == [written]


# --- Komentarz postępu Wyceny w efenix (#846) ----------------------------------------------------------------------------
# Wycena w efenix trwa u taty do półtorej godziny, a Maks chce widzieć jej postęp, zanim się skończy. Testy dają jej czas
# na udawanym zegarze Centrum: każde żądanie do Atrapy efenix trwa na nim minutę (``EfenixMinutes``), więc Wycena sześciu
# zleceń ``PRICED`` trwa kilkadziesiąt minut, a postęp odświeża się w jej trakcie. Maks czyta w Skrzynce jeden komentarz
# Uruchomienia: w trakcie postęp z dziennika Wyceny, na końcu podsumowanie z odnośnikiem do pełnych Logów w Archiwum.

PROGRESS_LABEL: Final = "logi-uruchomienia"
PROGRESS_ARCHIVE = f"logi-{PERIOD}"
# Ostatnia linia podsumowania: odnośnik do pliku w Archiwum Logów okresu (adres pobrania pliku GitHub Release).
SUMMARY_LINK = re.compile(r"- Pełne Logi: \[(?P<name>[^\]]+)\]\(https://github\.com/(?P<repo>[^/]+/[^/]+)/releases/download/(?P<tag>[^/]+)/(?P=name)\)")
MINUTES = re.compile(r"^- Czas: (?P<minutes>[0-9]+) min do tej pory$", re.MULTILINE)
DONE = re.compile(r"^- Zlecenia: (?P<done>[0-9]+) z 6 skończone", re.MULTILINE)
NO_ORDERS = "- Zlecenia: dziennik Wyceny nie ma jeszcze żadnego zlecenia"


@dataclass
class EfenixMinutes:
    """Zegar Atrapy efenix: każde żądanie okna efenix przesuwa zegar Centrum o minutę, a budziki Centrum, których
    chwila minęła, dzwonią w tym żądaniu (``ManualClock.advance``).

    Z działającą siecią żądanie czeka, aż Kolejka wysyłki odda Skrzynce wszystko, co budzik do niej włożył, więc
    Skrzynka dostaje każdy postęp. ``offline_until`` to minuta zegara Centrum, do której Skrzynka nie odpowiada (brak
    sieci); w pierwszym żądaniu po niej ``queued_at_return`` dostaje liczbę plików Logów w kolejce.
    """

    surroundings: Surroundings
    queue: Path
    offline_until: int | None = None
    queued_at_return: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.offline_until is not None:
            self.surroundings.report_box.search_failure = Unreachable()

    def __call__(self) -> float:
        clock, box = self.surroundings.clock, self.surroundings.report_box
        if self.offline_until is not None and clock() >= self.offline_until * 60:
            # Postęp ostatniego budzika mógł przyjść do kolejki tuż przed tym żądaniem: jego przejście jeszcze trwa.
            wait_for(lambda: len(queued_logs(self.queue)) == 1, 5)
            self.queued_at_return.append(len(queued_logs(self.queue)))
            self.offline_until, box.search_failure = None, None
        clock.advance(60)
        if self.offline_until is None:
            wait_for(lambda: queued_logs(self.queue) == [], 10)
        return clock()


def queued_logs(queue: Path) -> list[Path]:
    return sorted(queue.glob(f"*-{PROGRESS_LABEL}-*.json"))


@contextmanager
def pricing(
    tmp_path: Path, *, offline_until: int | None = None, logged_in: bool = True
) -> Iterator[tuple[SettlingCentrum, EfenixMinutes, AtrapaEfenix]]:
    """Centrum z Tokenem do Zgłoszeń, którego Skrzynka pokazuje Logi Uruchomienia w ``issues``, i Folder okresu z Plikiem
    zbiorczym ``PRICED``; okno efenix to Atrapa, na której każde żądanie trwa minutę (``EfenixMinutes``). Bez
    ``logged_in`` okno efenix czeka na logowanie taty (``AtrapaEfenix.log_in``)."""

    surroundings = Surroundings()
    surroundings.report_box.background = frozenset()
    minutes = EfenixMinutes(surroundings, ToolDirectory(tmp_path).queue, offline_until)
    with atrapa_efenix(IN_EFENIX, clock=minutes) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, PRICED)
        write_report_key(ToolDirectory(tmp_path))
        if not logged_in:
            atrapa.expire_session()
        yield centrum, minutes, atrapa


def summarized(fake: FakeReportBox) -> int:
    """Ile komentarzy issue Logów okresu ma podsumowanie: ich ostatnia linia to odnośnik do pełnych Logów."""

    return sum(
        SUMMARY_LINK.fullmatch(comment.splitlines()[-1]) is not None
        for issue in fake.issues_with(PROGRESS_LABEL)
        for comment in issue.comments
    )


def comment_histories(centrum: SettlingCentrum, count: int) -> list[tuple[int, list[str]]]:
    """Każdy z ``count`` komentarzy issue Logów okresu po kolei, gdy każdy ma już podsumowanie, a kolejka jest pusta: jego
    identyfikator i każdy jego tekst po kolei, jak go widział Maks (nowy komentarz, potem każda poprawka)."""

    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: summarized(fake) == count), box.issues
    assert wait_for(lambda: queued_logs(centrum.tool.queue) == [])
    [issue] = box.issues_with(PROGRESS_LABEL)
    assert len(issue.comment_ids) == count, issue.comments
    return [(comment_id, [shown(text) for written, text in box.written if written == comment_id]) for comment_id in issue.comment_ids]


def comment_history(centrum: SettlingCentrum) -> tuple[int, list[str]]:
    [history] = comment_histories(centrum, 1)
    return history


def minutes_of(texts: list[str]) -> list[int]:
    return [int(found["minutes"]) for text in texts if (found := MINUTES.search(text))]


def done_of(text: str) -> int | None:
    """Zlecenia skończone w postępie; ``None``: dziennik nie ma jeszcze żadnego zlecenia."""

    found = DONE.search(text)
    return None if found is None else int(found["done"])


def archived_logs(centrum: SettlingCentrum, comment: str) -> dict[str, Any]:
    link = SUMMARY_LINK.fullmatch(comment.splitlines()[-1])
    assert link is not None, comment
    assert link["tag"] == PROGRESS_ARCHIVE
    logs: dict[str, Any] = json.loads(centrum.surroundings.report_box.archived(PROGRESS_ARCHIVE)[link["name"]])
    return logs


def started_text(run_id: str, started_at: str, mode: str = "zapis") -> str:
    """Komentarz postępu przy starcie Wyceny w trybie ``mode``, zanim dziennik ma pierwsze zlecenie."""

    return (
        f"**Logi Uruchomienia**: Wycena w efenix, {mode}, okres {PERIOD}\n"
        "\n"
        "- Wynik: jeszcze nie ma, Uruchomienie trwa\n"
        f"{NO_ORDERS}\n"
        "- Czas: 0 min do tej pory\n"
        f"- Uruchomienie: {run_id}, start {datetime.fromisoformat(started_at):%Y-%m-%d %H:%M:%S} UTC\n"
        "- Pełne Logi: w tym komentarzu, gdy Uruchomienie się skończy\n"
    )


def test_wycena_w_efenix_ma_w_issue_okresu_jeden_komentarz_z_rosnacym_postepem_co_5_minut_a_na_koncu_z_podsumowaniem(
    tmp_path: Path,
) -> None:
    """Wycena zakłada komentarz Uruchomienia przy starcie, odświeża go co 5 minut na zegarze Centrum stanem dziennika
    (zlecenia skończone z sześciu, wyniki, ostatnie zlecenie), a na końcu ten sam komentarz staje się podsumowaniem z
    odnośnikiem do pliku w Archiwum Logów okresu. Po końcu żaden postęp już nie przychodzi, choć czas biegnie dalej."""

    with pricing(tmp_path) as (centrum, _, _):
        started = _start_pricing(centrum)
        assert started.status_code == 200, started.json()
        run_id = started.json()["run"]["id"]
        finished = finished_view(centrum.client)
    comment_id, texts = comment_history(centrum)
    centrum.surroundings.clock.advance(minutes=15)
    assert wait_for(lambda: queued_logs(centrum.tool.queue) == [])
    assert comment_history(centrum) == (comment_id, texts), "postęp po podsumowaniu"
    assert centrum.surroundings.clock.wakes == 0, "budzik postępu po końcu Wyceny"
    *progress, summary = texts
    logs = archived_logs(centrum, summary)
    done = [done_of(text) for text in progress]
    counted = [count for count in done if count is not None]

    assert (finished["run"]["id"], logs["run_id"], logs["ending"]) == (run_id, run_id, "finished")
    assert progress[0] == started_text(run_id, logs["started_at"])
    assert (minutes_of(progress), minutes_of([summary])) == (list(range(0, 5 * len(progress), 5)), [])
    assert len(progress) >= 4, progress
    assert done == [None] * (len(done) - len(counted)) + sorted(counted), "postęp nie cofa się"
    assert any(0 < count < 6 for count in counted), progress
    later = next(text for text in progress if (done_of(text) or 0) > 0)
    assert re.search(r"^- Ostatnie zlecenie: wiersz (18|19|20|21|22), ", later, re.MULTILINE), later
    assert "- Wynik: WYMAGA_SPRAWDZENIA" in summary.splitlines()
    assert centrum.surroundings.report_box.edited == [comment_id] * (len(texts) - 1)


def test_bez_sieci_w_kolejce_czeka_tylko_najnowszy_postep_a_po_powrocie_sieci_issue_ma_jeden_komentarz_uruchomienia(
    tmp_path: Path,
) -> None:
    """Przez pierwsze 12 minut Wyceny Skrzynka nie odpowiada: postęp z minut 0, 5 i 10 czeka w Kolejce wysyłki, a
    najnowszy zastępuje starszy, więc po powrocie sieci w kolejce jest jeden plik Logów, a Skrzynka dostaje od razu postęp
    z 10. minuty, potem następne i podsumowanie, wszystko w jednym komentarzu Uruchomienia."""

    with pricing(tmp_path, offline_until=12) as (centrum, minutes, _):
        assert _start_pricing(centrum).status_code == 200
        finished_view(centrum.client)
    _, texts = comment_history(centrum)
    *progress, summary = texts

    assert minutes.queued_at_return == [1]
    assert minutes_of(progress) == list(range(10, 10 + 5 * len(progress), 5))
    assert archived_logs(centrum, summary)["ending"] == "finished"


def test_wpis_dziennika_wyceny_ktorego_nie_da_sie_zapisac_nie_zmienia_postepu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Start dziennika Wyceny jest już na dysku, a zanim tata zaloguje się w efenix, plik dziennika przestaje przyjmować
    wpisy (tylko do odczytu). Wycena przechodzi wszystkie zlecenia, ale żaden ich wpis nie trafia na dysk, więc postęp
    nie wyprzedza dziennika: każdy mówi, że dziennik nie ma jeszcze żadnego zlecenia, a podsumowanie ma sześć zleceń."""

    with pricing(tmp_path, logged_in=False) as (centrum, _, atrapa):
        kept = journals_at_result(monkeypatch, centrum.log_path.parent / "dzienniki-wyceny")
        assert _start_pricing(centrum).status_code == 200
        [journal] = journals(centrum)
        journal.chmod(stat.S_IREAD)
        atrapa.log_in()
        finished_view(centrum.client)
    _, texts = comment_history(centrum)
    centrum.client.stop()
    with suppress(FileNotFoundError):  # Windows nie usuwa pliku tylko do odczytu: dziennik zostaje do następnego startu
        journal.chmod(stat.S_IREAD | stat.S_IWRITE)
    *progress, summary = texts

    assert [entry["entry"] for entry in journal_entries_of(kept[journal])] == ["start Uruchomienia"]
    assert len(progress) >= 4, progress
    assert [text for text in progress if NO_ORDERS not in text.splitlines()] == []
    assert len(archived_logs(centrum, summary)["efenix_orders"]) == 6


def test_start_dziennika_wyceny_ktorego_nie_dalo_sie_zapisac_idzie_z_pierwszym_wpisem_a_postep_rusza_z_nim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Katalog dzienników Wyceny zajęty przez plik, gdy tata uruchamia Wycenę w efenix, a okno efenix czeka na jego
    logowanie: start dziennika nie trafia na dysk, więc postępu nie ma. Zanim tata się zaloguje, katalog wraca (np.
    antywirus puścił plik): pierwszy wpis zapisuje przed sobą pierwszą linię, więc dziennik ma start i każde zlecenie, a
    komentarz Uruchomienia dostaje postęp ze zleceniami i na końcu podsumowanie. Kolejka przyjęła Logi z wynikiem, więc
    dziennik znika z końcem Wyceny."""

    blocked = tmp_path / "logs" / "dzienniki-wyceny"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    with pricing(tmp_path, logged_in=False) as (centrum, _, atrapa):
        kept = journals_at_result(monkeypatch, blocked)
        assert _start_pricing(centrum).status_code == 200
        blocked.unlink()
        atrapa.log_in()
        finished_view(centrum.client)
    _, texts = comment_history(centrum)
    centrum.client.stop()
    *progress, summary = texts
    [journal] = kept.values()
    entries = [entry["entry"] for entry in journal_entries_of(journal)]

    assert (entries[:2], entries.count("zlecenie skończone"), journals(centrum)) == (
        ["start Uruchomienia", "zaczynam zlecenie"],
        6,
        [],
    )
    assert progress != [], texts
    assert [text for text in progress if NO_ORDERS in text.splitlines()] == [], "postęp przed startem dziennika na dysku"
    assert len(archived_logs(centrum, summary)["efenix_orders"]) == 6


def test_komentarz_postepu_urwanej_wyceny_w_efenix_zamienia_w_podsumowanie_nastepny_start_centrum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Okno efenix czeka na logowanie taty, aż komentarz postępu ze startu Wyceny jest w Skrzynce, a potem sieć znika.
    Wycena przechodzi wszystkie zlecenia, ale Centrum gaśnie przed wynikiem (bez Logów, wiersza Historii i wysyłki w
    kolejce, jak po braku prądu). Następny start zamyka dziennik jako Logi Urwanego Uruchomienia, a komentarz, który Maks
    już widzi, zmienia się (poprawka, nie nowy komentarz) w ich podsumowanie z odnośnikiem do Archiwum."""

    surroundings = Surroundings()
    box = surroundings.report_box
    box.background = frozenset()
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        kept = journals_at_result(monkeypatch, centrum.log_path.parent / "dzienniki-wyceny")
        atrapa.expire_session()
        started = _start_pricing(centrum)
        assert started.status_code == 200, started.json()
        run_id = started.json()["run"]["id"]
        assert box.wait_until(lambda fake: [issue.comments for issue in fake.issues_with(PROGRESS_LABEL)] != [])
        box.search_failure = Unreachable()
        atrapa.log_in()
        finished_view(centrum.client)
    centrum.client.stop()
    [logs] = ToolDirectory(tmp_path).run_logs.glob("*.json")
    logs.unlink()
    centrum.engines.metrics.efenix.unlink()
    shutil.rmtree(ToolDirectory(tmp_path).queue)
    for path, text in kept.items():
        path.write_text(text, encoding="utf-8")
    box.search_failure = None

    centrum.restart()
    centrum.client.start()
    assert centrum.client.get("/api/runs/current").status_code == 200
    _, texts = comment_history(centrum)
    centrum.client.stop()
    progress, summary = texts

    assert (progress.splitlines()[3], archived_logs(centrum, summary)["ending"]) == (NO_ORDERS, "interrupted")
    assert "- Wynik: brak, Centrum zamknęło się w trakcie (Urwane Uruchomienie)" in summary.splitlines()
    assert f"- Uruchomienie: {run_id}, start " in summary


def test_centrum_zgaszone_w_trakcie_logowania_taty_w_efenix_zamienia_komentarz_postepu_w_logi_urwanego_uruchomienia(
    tmp_path: Path,
) -> None:
    """Okno efenix czeka na logowanie taty, a postęp ze startu Wyceny czeka w Kolejce wysyłki (Skrzynka Zgłoszeń dostaje
    klucz dopiero od następnego startu), gdy Centrum gaśnie nagle, cały proces razem z oknem efenix, przed pierwszym
    zleceniem. Dziennik Wyceny ma już na dysku jej start, więc następny start Centrum zamyka go jako Logi Urwanego
    Uruchomienia bez zleceń: jedyny komentarz Uruchomienia w issue okresu kończy się ich podsumowaniem, a nie postępem,
    który mówi, że Uruchomienie trwa, a karta po starcie pokazuje zero zleceń przed zamknięciem Centrum."""

    queue = ToolDirectory(tmp_path).queue
    surroundings = Surroundings()
    surroundings.report_box.background = frozenset()
    with atrapa_efenix(IN_EFENIX) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, PRICED)
        atrapa.expire_session()
        with centrum_process(tmp_path, atrapa.url) as process:
            status, started = process.post("/api/runs", {"process": "efenix", "period": PERIOD, "mode": "RUN"})
            queued = wait_for(lambda: len(queued_logs(queue)) == 1, 60)
            process.kill()
    on_disk = [entry["entry"] for journal in journals(centrum) for entry in journal_entries(journal)]
    write_report_key(ToolDirectory(tmp_path))
    centrum.restart()
    with centrum.client:  # start Centrum jak u taty: ``lifespan`` wznawia Kolejkę wysyłki z postępem
        previous = centrum.client.get("/api/runs/current").json()["previous"]
        _, texts = comment_history(centrum)
    centrum.client.stop()
    *_, summary = texts
    logs = archived_logs(centrum, summary)
    run_id = started["run"]["id"]

    assert (status, queued, on_disk) == (200, True, ["start Uruchomienia"]), "postęp przed startem dziennika na dysku"
    assert (logs["run_id"], logs["ending"], logs["efenix_orders"]) == (run_id, "interrupted", [])
    assert "- Wynik: brak, Centrum zamknęło się w trakcie (Urwane Uruchomienie)" in summary.splitlines()
    assert [text for text in texts[:-1] if text != started_text(run_id, logs["started_at"])] == []
    assert (previous["state"], previous["run"]["id"], previous["orders"]["title"]) == ("interrupted", run_id, "Zlecenia przed zamknięciem Centrum")
    assert {count["count"] for count in previous["orders"]["counts"]} == {0}


def test_druga_wycena_w_efenix_w_tej_samej_pracy_centrum_ma_swoj_komentarz_z_postepem_od_swojego_startu(tmp_path: Path) -> None:
    """Tata puszcza w jednej pracy Centrum Wycenę w efenix, a po jej wyniku drugą, na tym samym Pliku zbiorczym. Każda ma
    w issue okresu swój komentarz Uruchomienia: postęp drugiej zaczyna się od jej startu, bez zleceń i bez czasu
    pierwszej, a nie od sześciu zleceń pierwszej, i każdy komentarz kończy się podsumowaniem swojej Wyceny. Po obu końcach
    żaden postęp już nie przychodzi i Centrum go nie budzi, choć czas biegnie dalej."""

    with pricing(tmp_path) as (centrum, _, _):
        runs: list[str] = []
        for _ in range(2):
            started = _start_pricing(centrum)
            assert started.status_code == 200, started.json()
            runs.append(started.json()["run"]["id"])
            _view_where(centrum, lambda view: view["state"] == "finished" and view["run"]["id"] == runs[-1])
    histories = comment_histories(centrum, 2)
    clock = centrum.surroundings.clock
    clock.advance(minutes=15)
    assert wait_for(lambda: queued_logs(centrum.tool.queue) == [])
    assert (comment_histories(centrum, 2), clock.wakes) == (histories, 0), "postęp po podsumowaniu"
    summaries = [archived_logs(centrum, texts[-1]) for _, texts in histories]

    assert [(logs["run_id"], logs["ending"], len(logs["efenix_orders"])) for logs in summaries] == [
        (runs[0], "finished", 6),
        (runs[1], "finished", 6),
    ]
    assert [texts[0] for _, texts in histories] == [started_text(logs["run_id"], logs["started_at"]) for logs in summaries]


def test_postep_wyceny_w_efenix_ktorego_budzik_dzwoni_gdy_jej_logi_sa_juz_w_kolejce_nie_cofa_podsumowania(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Budzik postępu dzwoni dokładnie w chwili, gdy Kolejka wysyłki przyjęła Logi z wynikiem Wyceny (zegar Centrum
    przesuwa się o 5 minut przy pierwszej wysyłce po wierszu Historii). Postęp skończył się już z działaniami po wyniku,
    więc ten budzik nic nie wysyła i się nie powtarza: postęp nowszy od Logów zastąpiłby je w kolejce, a jedyny komentarz
    Uruchomienia zostałby na zawsze postępem, który mówi, że Uruchomienie trwa."""

    queued = CentrumLog.box_post_queued
    rung: list[str] = []
    with pricing(tmp_path) as (centrum, _, _):
        clock, metrics = centrum.surroundings.clock, centrum.engines.metrics.efenix

        def ringing(log: CentrumLog, *, label: str, period: str | None) -> None:
            queued(log, label=label, period=period)
            if metrics.exists() and not rung:  # wiersz Historii jest, więc to już działania po wyniku
                rung.append(label)
                clock.advance(PROGRESS_S)

        monkeypatch.setattr(CentrumLog, "box_post_queued", ringing)
        assert _start_pricing(centrum).status_code == 200
        finished_view(centrum.client)
    _, texts = comment_history(centrum)

    assert (rung, clock.wakes) == ([PROGRESS_LABEL], 0), "budzik postępu po Logach"
    assert archived_logs(centrum, texts[-1])["ending"] == "finished"


# --- Kopia wejścia (#841) ------------------------------------------------------------------------------------------------
# Przygotowanie, Przebieg i Wycena w efenix dają Logi z Wierszami danych, które przeczytały, bez kolumn ``ADRES`` i
# ``NUMER UMOWY/ZLECENIA ORANGE``, z odciskiem każdego pliku zgodnym z plikiem na dysku (reguła danych, ADR 0025).

FREE_TEXT = f"montaż {ADDRESS_VALUE} umowa {ORANGE_VALUE} tel. {PHONE}, {STREET}"
MASKED = "montaż [adres] umowa [numer Orange] tel. [telefon], [ulica]"

COLLECTIVE_COLUMNS = {
    letter: header
    for letter, header in zip("ABCDEFGHIJK", COLLECTIVE_HEADERS, strict=True)
    if header not in ("ADRES", "NUMER UMOWY/ZLECENIA ORANGE")
}
"""Nagłówki A17:K17 Pliku zbiorczego w Kopii wejścia: bez ``ADRES`` (B) i numeru Orange (I)."""


def fingerprint(content: bytes, path: Path) -> dict[str, object]:
    """Odcisk pliku taty tak, jak go liczy Maks na swojej kopii: rozmiar, chwila zmiany (UTC) i SHA-256 treści."""

    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return {"size": len(content), "modified_at": modified, "sha256": hashlib.sha256(content).hexdigest()}


def logged_fingerprint(copied: dict[str, Any]) -> dict[str, object]:
    found = dict(copied["fingerprint"])
    found["modified_at"] = None if found["modified_at"] is None else datetime.fromisoformat(found["modified_at"])
    return found


def moment(text: str) -> dict[str, str]:
    """Data z godziną w Kopii wejścia: rodzaj, bo JSON nie odróżnia jej od tekstu."""

    return {"type": "datetime", "text": text}


def test_logi_przygotowania_maja_wiersze_rejestru_z_okresu_bez_adresu_i_numeru_orange_oraz_odcisk_rejestru(
    tmp_path: Path,
) -> None:
    """Kopia wejścia Przygotowania to arkusz zleceń Rejestru: nagłówki Rejestru (wiersz 1) kolumn wklejenia od A do
    ``UWAGI`` w ich kolumnach arkusza, bez ``ADRES`` (E) i ``NUMER UMOWY`` (K), i każde zlecenie okresu z komórkami
    kolumn, które proces przenosi. Arkusz bez nagłówków zleceń („lista”) w Kopii nie stoi, a kolumny, których proces nie
    przenosi (AKCJE, ZWROT, UWAGI), mają w niej nagłówek bez komórek: z nich odtworzenie zna granicę wklejenia."""

    centrum = preparing_centrum(tmp_path)
    register = centrum.fixture.register_path
    content = register.read_bytes()

    view = run_to_end(centrum, dry_run=True)

    assert view["result"]["result"] == "OK"
    [record] = records(centrum)
    [copied] = record["input_copy"]
    assert (copied["name"], logged_fingerprint(copied)) == (register.name, fingerprint(content, register))
    [sheet] = copied["sheets"]
    assert (sheet["sheet"], sheet["header_row"]) == ("ZLECENIA", 1)
    assert sheet["columns"] == {
        "B": "AKCJE",
        "C": "DATA GODZ. POCZ.",
        "D": "MIASTO",
        "F": "UMOWA",
        "G": "URZĄDZENIA",
        "H": "CZYNNOŚCI",
        "I": "NUMER ZL.",
        "J": "WYKONAWCA",
        "L": "SKUTECZNE",
        "M": "CZYNNOŚCI ZREALIZOWANE",
        "N": "ZWROT",
        "O": "UWAGI",
    }
    rows = {row["row"]: row["cells"] for row in sheet["rows"]}
    in_period = {
        4: ("2026-09-08T00:00:00", 2, "adrian.testowy", "tak"),
        6: ("2026-09-09T10:30:00", 3, "dariusz.fikcyjny2", "NIE"),
        9: ("2026-09-12T12:00:00", 4, "kamil.syntetyczny", " Tak "),
        13: ("2026-09-14T18:30:00", 6, "dariusz.fikcyjny2", "TAK"),
    }
    for number, (started, order, worker, successful) in in_period.items():
        assert rows[number] == {
            "C": moment(started),
            "D": "POZNAŃ",
            "F": f"UM-SYN-{order:03d}",
            "G": "dekoder",
            "H": "instalacja",
            "I": f"ZL-SYN-{order:03d}",
            "J": worker,
            "L": successful,
            "M": "montaż",
        }, number
    assert {5, 7, 8, 10} <= set(sheet["empty_rows"]), "puste wiersze między zleceniami okresu"


def test_logi_przebiegu_rozliczen_maja_wiersze_pliku_zbiorczego_bez_adresu_i_numeru_orange_oraz_odcisk_pliku(
    tmp_path: Path,
) -> None:
    """Kopia wejścia Przebiegu to arkusz Pliku zbiorczego z nagłówkami z wiersza 17 i każdym Wierszem danych z jego
    komórkami A:AT, bez ``ADRES`` i numeru Orange. Godzina i czas trwania mają rodzaj, bo JSON nie odróżnia ich od
    tekstu, a formuła tablicowa to jej tekst, jak każda formuła."""

    centrum = settling_centrum(tmp_path)
    typed: dict[str, CellValue] = {"AQ": time_of_day(8, 30), "AR": timedelta(hours=1, minutes=30), "AS": True, "AT": ArrayFormula("AT19", "=SUM(N19:N19)")}
    write_quantity_source(centrum.collective_file, [MARKED, {"H": "kamil.syntetyczny", "N": 2, **typed}])
    content = centrum.collective_file.read_bytes()

    view = run_to_end(centrum, dry_run=True)

    assert view["result"]["result"] == "OK"
    [record] = records(centrum)
    [copied] = record["input_copy"]
    assert (copied["name"], logged_fingerprint(copied)) == (SOURCE_NAME, fingerprint(content, centrum.collective_file))
    [sheet] = copied["sheets"]
    assert (sheet["sheet"], sheet["header_row"], sheet["columns"], sheet["empty_rows"]) == ("Sheet1", 17, COLLECTIVE_COLUMNS, [])
    marked = {letter: value for letter, value in MARKED.items() if letter not in ("B", "I")}
    assert sheet["rows"] == [
        {"row": 18, "cells": {**marked, "G": moment("2026-09-09T13:45:00"), "H": "adrian.testowy"}},
        {
            "row": 19,
            "cells": {
                "A": "POZNAŃ",
                "F": "#19",
                "H": "kamil.syntetyczny",
                "J": "tak",
                "N": 2,
                "AQ": {"type": "time", "text": "08:30:00"},
                "AR": {"type": "timedelta", "text": "5400.0"},
                "AS": True,
                "AT": "=SUM(N19:N19)",
            },
        },
    ]
    assert sheet["rows"][1]["cells"]["AS"] is True, "prawda/fałsz, nie liczba"


def test_kolumna_pliku_zbiorczego_z_naglowkiem_z_samych_spacji_nie_jest_kolumna_kopii_wejscia(tmp_path: Path) -> None:
    """Spacje, które tata zostawił w nagłówku pustej kolumny Pliku zbiorczego, nie czynią z niej kolumny Kopii wejścia:
    Kopia nazywa tylko kolumny z nagłówkiem."""

    centrum = settling_centrum(tmp_path)
    write_quantity_source(centrum.collective_file, [MARKED])
    workbook = load_workbook(centrum.collective_file)
    try:
        active_worksheet(workbook)["L17"] = "  "
        workbook.save(centrum.collective_file)
    finally:
        workbook.close()

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    [copied] = record["input_copy"]
    [sheet] = copied["sheets"]
    assert sheet["columns"] == COLLECTIVE_COLUMNS


def test_logi_wyceny_w_efenix_maja_wiersze_pliku_zbiorczego_z_kwota_i_odcisk_przeczytanej_wersji_pliku(
    tmp_path: Path,
) -> None:
    """Kopia wejścia Wyceny w efenix to Wiersze danych Pliku zbiorczego z wartościami, które policzył Excel, także
    ``Kwota`` (AU). Wycena zapisuje Znaczniki efenix w tym samym pliku, więc odcisk to wersja, którą przeczytała, a nie
    plik po Uruchomieniu."""

    amount = float(amount_of({"012": 1}))
    ready = Order("#ZLKW01", cells={"O": 1}, amount=amount, quantities={"012": 1})
    unknown = Order("#ZLKW02", worker="beata.testowa", cells={"O": 1, "AQ": "uwaga taty"}, amount=amount)
    with atrapa_efenix([ready.in_efenix("701")]) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        source = write_collective_file(centrum.period_parent, [ready, unknown])
        content = source.read_bytes()
        read = fingerprint(content, source)
        started = centrum.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "mode": "RUN"})
        assert started.status_code == 200, started.json()
        result = finished_view(centrum.client)["result"]

    assert result["result"] == "WYMAGA_SPRAWDZENIA"
    assert source.read_bytes() != content, "Znacznik efenix gotowego zlecenia"
    [record] = records(centrum)
    [copied] = record["input_copy"]
    assert (copied["name"], logged_fingerprint(copied)) == (SOURCE_NAME, read)
    [sheet] = copied["sheets"]
    assert (sheet["header_row"], sheet["columns"]) == (17, COLLECTIVE_COLUMNS)
    started_at = moment("2026-09-09T10:30:00")
    assert sheet["rows"] == [
        {"row": 18, "cells": {"A": "MIASTO", "F": "#ZLKW01", "G": started_at, "H": "adrian.testowy", "J": "tak", "O": 1, "AU": amount}},
        {
            "row": 19,
            "cells": {
                "A": "MIASTO",
                "F": "#ZLKW02",
                "G": started_at,
                "H": "beata.testowa",
                "J": "tak",
                "O": 1,
                "AQ": "uwaga taty",
                "AU": amount,
            },
        },
    ]


def _copy_preparation(tmp_path: Path, _: ExitStack) -> PreparingCentrum | SettlingCentrum:
    rows = default_register_rows()
    rows[2] = {**(rows[2] or {}), "ADRES": ADDRESS_VALUE, "NUMER UMOWY": ORANGE_VALUE, "CZYNNOŚCI ZREALIZOWANE": FREE_TEXT}
    return preparing_centrum(tmp_path, rows)


def _copy_settlement(tmp_path: Path, _: ExitStack) -> PreparingCentrum | SettlingCentrum:
    centrum = settling_centrum(tmp_path)
    write_quantity_source(centrum.collective_file, [{"B": ADDRESS_VALUE, "I": ORANGE_VALUE, "K": FREE_TEXT}])
    return centrum


def _copy_pricing(
    tmp_path: Path, stack: ExitStack, source: ByteSource = workbook_files.file_bytes
) -> PreparingCentrum | SettlingCentrum:
    """Zlecenie, którego efenix nie zna: Wycena czyta cały wiersz i kończy się wynikiem bez zapisu w efenix."""

    atrapa = stack.enter_context(atrapa_efenix([]))
    centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url, source=source))
    order = Order("#ZLKW03", address=ADDRESS_VALUE, cells={"I": ORANGE_VALUE, "K": FREE_TEXT}, amount=0.0)
    write_collective_file(centrum.period_parent, [order])
    return centrum


COPY_PROCESSES: dict[str, Callable[[Path, ExitStack], PreparingCentrum | SettlingCentrum]] = {
    "preparation": _copy_preparation,
    "settlement": _copy_settlement,
    "efenix": _copy_pricing,
}


@pytest.mark.parametrize("process", COPY_PROCESSES.keys())
def test_adres_i_numer_orange_z_kopii_wejscia_nie_wychodza_do_logow_ani_skrzynki_takze_wpisane_w_wolny_tekst(
    tmp_path: Path, process: str
) -> None:
    """Komórki ``ADRES`` i numeru Orange nie stoją w Kopii wejścia, a ich wartości wpisane w wolny tekst innej komórki
    strażnik maskuje razem z telefonem i ulicą, z uwagą techniczną o miejscu w Kopii osobno od uwag technicznych karty,
    więc karta z Logów ma te same uwagi co karta na żywo (ADR 0017); nic z tego nie wychodzi do pliku Logów ani do
    Skrzynki Zgłoszeń."""

    with ExitStack() as stack:
        centrum = COPY_PROCESSES[process](tmp_path, stack)
        write_report_key(ToolDirectory(tmp_path))
        started = centrum.client.post("/api/runs", json={"process": process, "period": PERIOD, "mode": "DRY-RUN" if process != "efenix" else "RUN"})
        assert started.status_code == 200, started.json()
        result = finished_view(centrum.client)["result"]

    assert result["stop_kind"] is None, result["stops"]
    box: FakeReportBox = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    [record] = records(centrum)
    [copied] = record["input_copy"]
    headers = [header for sheet in copied["sheets"] for header in sheet["columns"].values()]
    assert [header for header in headers if header in ("ADRES", "NUMER UMOWY", "NUMER UMOWY/ZLECENIA ORANGE")] == []
    cells = [value for sheet in copied["sheets"] for row in sheet["rows"] for value in row["cells"].values()]
    masked = [value for value in cells if "[adres]" in str(value) or "[numer Orange]" in str(value)]
    assert masked == [MASKED], "zakazanych komórek nie ma w Kopii, a wolny tekst jest po strażniku"
    assert record["input_copy_notes"] == [
        f"Reguła danych: zamaskowano wartość kolumny {column} w: input_copy[0].sheets[0].rows[{cells_row(copied)}].cells.[…]."
        for column in ("ADRES", "NUMER UMOWY/ZLECENIA ORANGE")
    ]
    assert record["technical_notes"] == result["technical_notes"], "uwagi techniczne karty"
    texts = [path.read_text(encoding="utf-8") for path in sorted(centrum.tool.run_logs.glob("*"))]
    sent = in_box(box) + [part for issue in box.issues for part in (issue.title, issue.body, *issue.comments)]
    assert any(MASKED in part for part in sent), "Kopia wejścia w pliku Logów w Archiwum"
    texts += sent
    leaked = (ADDRESS_VALUE, ORANGE_VALUE, PHONE, STREET, json.dumps(ADDRESS_VALUE)[1:-1])
    assert [value for value in leaked if any(value in text for text in texts)] == []


def test_kolumny_adresu_i_numeru_orange_pliku_zbiorczego_nie_wychodza_takze_pod_innym_naglowkiem(tmp_path: Path) -> None:
    """Kolumny B i I Pliku zbiorczego to ``ADRES`` i numer Orange z układu Wzorca bez względu na nagłówek, który tata
    w nich zmienił: Kopia wejścia Przebiegu ich nie ma, a ich wartości wpisane w wolny tekst innej komórki strażnik
    maskuje, więc nie wychodzą do pliku Logów ani do Skrzynki Zgłoszeń."""

    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    write_quantity_source(centrum.collective_file, [{"B": ADDRESS_VALUE, "I": ORANGE_VALUE, "K": FREE_TEXT}])
    workbook = load_workbook(centrum.collective_file)
    sheet = active_worksheet(workbook)
    sheet["B17"], sheet["I17"] = "ADRES KLIENTA", "NR UMOWY ORANGE"
    workbook.save(centrum.collective_file)

    view = run_to_end(centrum, dry_run=True)

    assert view["result"]["stop_kind"] is None, view["result"]["stops"]
    box: FakeReportBox = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    [record] = records(centrum)
    [copied] = record["input_copy"]
    [sheet_copy] = copied["sheets"]
    assert [letter for letter in ("B", "I") if letter in sheet_copy["columns"]] == []
    [row] = sheet_copy["rows"]
    assert ([letter for letter in ("B", "I") if letter in row["cells"]], row["cells"]["K"]) == ([], MASKED)
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)] + in_box(box)
    assert [value for value in (ADDRESS_VALUE, ORANGE_VALUE) if any(value in text for text in texts)] == []


READ_AT = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
"""Chwila zmiany pliku taty przed Uruchomieniem, a ``SAVED_AGAIN_AT`` po zapisie zaraz po odczycie."""
SAVED_AGAIN_AT = datetime(2027, 1, 15, 8, 0, tzinfo=timezone.utc)


def _saved_at(path: Path, moment: datetime) -> None:
    os.utime(path, (moment.timestamp(), moment.timestamp()))


def _register_saved_again(path: Path) -> None:
    path.write_bytes(path.read_bytes() + b"\0")
    _saved_at(path, SAVED_AGAIN_AT)


def _register_gone(path: Path) -> None:
    path.rename(path.with_name("przeniesiony.xlsx"))


@pytest.mark.parametrize("after_reading", [_register_saved_again, _register_gone], ids=["zapisany-znowu", "zniknal"])
def test_odcisk_rejestru_jest_z_bajtow_ktore_przeczytalo_przygotowanie_takze_gdy_plik_zmienil_sie_zaraz_po_odczycie(
    tmp_path: Path, after_reading: Callable[[Path], None]
) -> None:
    """Rejestr zapisany znowu (Autozapis Excela, OneDrive) albo przeniesiony zaraz po odczycie: Przygotowanie czyta jego
    bajty raz, więc strażnik Surowych zleceń i Odczyt danych decydują na tej samej wersji, a odcisk w Kopii wejścia to
    rozmiar i skrót tych bajtów i chwila zmiany tej wersji, sprzed odczytu. Kopia nie czyta pliku drugi raz, więc nie
    zatrzymuje Przygotowania."""

    content: list[bytes] = []

    def read_then_changed(path: Path) -> bytes:
        read = workbook_files.file_bytes(path)
        if path.name == REGISTER_NAME:
            content.append(read)
            after_reading(path)
        return read

    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(source=read_then_changed))
    _saved_at(centrum.fixture.register_path, READ_AT)

    view = run_to_end(centrum, dry_run=True)

    assert (view["result"]["result"], view["result"]["stop_kind"]) == ("OK", None), view["result"]["stops"]
    [record] = records(centrum)
    [copied] = record["input_copy"]
    [read] = content
    assert logged_fingerprint(copied) == {"size": len(read), "modified_at": READ_AT, "sha256": hashlib.sha256(read).hexdigest()}


@pytest.mark.parametrize("process", ["settlement", "efenix"])
def test_chwila_zmiany_w_odcisku_pliku_zbiorczego_jest_sprzed_odczytu_takze_gdy_plik_zapisano_zaraz_po_nim(
    tmp_path: Path, process: str
) -> None:
    """Plik zbiorczy zapisany znowu (Autozapis Excela, OneDrive) zaraz po tym, jak Przebieg rozliczeń albo Wycena w
    efenix przeczytały jego bajty: odcisk w Kopii wejścia ma chwilę zmiany przeczytanej wersji, sprzed odczytu."""

    saved_again: list[Path] = []

    def read_then_saved(path: Path) -> bytes:
        content = workbook_files.file_bytes(path)
        if path.name == SOURCE_NAME:
            _saved_at(path, SAVED_AGAIN_AT)
            saved_again.append(path)
        return content

    with ExitStack() as stack:
        if process == "efenix":
            centrum = _copy_pricing(tmp_path, stack, read_then_saved)
        else:
            centrum = settling_centrum(tmp_path, surroundings=Surroundings(source=read_then_saved))
        assert isinstance(centrum, SettlingCentrum)
        _saved_at(centrum.collective_file, READ_AT)
        started = centrum.client.post("/api/runs", json={"process": process, "period": PERIOD, "mode": "DRY-RUN" if process != "efenix" else "RUN"})
        assert started.status_code == 200, started.json()
        result = finished_view(centrum.client)["result"]

    assert result["stop_kind"] is None, result["stops"]
    assert saved_again, "proces czyta Plik zbiorczy źródłem bajtów czytników, a plik zapisano znowu zaraz po odczycie"
    [record] = records(centrum)
    [copied] = record["input_copy"]
    assert (copied["name"], logged_fingerprint(copied)["modified_at"]) == (SOURCE_NAME, READ_AT)


MOVED_WORKER: Final = "KTO"
"""Nagłówek H17 Pliku zbiorczego, w którym tata nadpisał ``WYKONAWCA``."""


def _no_worker_settlement(tmp_path: Path, _: ExitStack) -> SettlingCentrum:
    centrum = settling_centrum(tmp_path)
    write_quantity_source(centrum.collective_file, [{}])
    workbook = load_workbook(centrum.collective_file)
    active_worksheet(workbook)["H17"] = MOVED_WORKER
    workbook.save(centrum.collective_file)
    return centrum


def _no_worker_pricing(tmp_path: Path, stack: ExitStack) -> SettlingCentrum:
    atrapa = stack.enter_context(atrapa_efenix([]))
    centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
    write_collective_file(centrum.period_parent, [Order("#ZLKW06", amount=0.0)], headers={"H": MOVED_WORKER})
    return centrum


NO_WORKER = {
    "settlement": (_no_worker_settlement, "ZLY_PLIK_ZBIORCZY"),
    "efenix": (_no_worker_pricing, "EFENIX_NIECZYTELNY_PLIK_ZBIORCZY"),
}


@pytest.mark.parametrize("process", NO_WORKER.keys())
def test_logi_uruchomienia_zatrzymanego_na_braku_wykonawcy_w_h17_maja_odcisk_i_naglowek_pliku_zbiorczego(
    tmp_path: Path, process: str
) -> None:
    """Przebieg rozliczeń i Wycena w efenix czytają Plik zbiorczy jednym potokiem: arkusz wchodzi do Kopii wejścia przed
    sprawdzeniem ``WYKONAWCA`` w H17, więc Logi Uruchomienia zatrzymanego na złym układzie mają odcisk pliku i jego
    nagłówek, z których da się to Zatrzymanie odtworzyć."""

    setup, code = NO_WORKER[process]
    with ExitStack() as stack:
        centrum = setup(tmp_path, stack)
        content = centrum.collective_file.read_bytes()
        started = centrum.client.post("/api/runs", json={"process": process, "period": PERIOD, "mode": "DRY-RUN" if process != "efenix" else "RUN"})
        assert started.status_code == 200, started.json()
        finished_view(centrum.client)

    [record] = records(centrum)
    assert [message["code"] for message in record["messages"] if message["kind"] == "stop"] == [code]
    [copied] = record["input_copy"]
    assert (copied["name"], logged_fingerprint(copied)) == (SOURCE_NAME, fingerprint(content, centrum.collective_file))
    [sheet] = copied["sheets"]
    columns = {**COLLECTIVE_COLUMNS, "H": MOVED_WORKER}
    assert (sheet["header_row"], sheet["columns"], sheet["rows"]) == (17, columns, [])


def cells_row(copied: dict[str, Any]) -> int:
    [sheet] = copied["sheets"]
    return next(index for index, row in enumerate(sheet["rows"]) if MASKED in row["cells"].values())


ORANGE_NUMBER = int(ORANGE_VALUE)
PHONE_NUMBER = int(PHONE.replace(" ", ""))
PHONE_WITH_PREFIX_NUMBER = int(f"48{PHONE_NUMBER}")
"""Numer Orange i telefon, które tata wpisał w komórkę bez innego tekstu, więc Excel trzyma je jako liczby; telefon
wpisany z ``+48`` albo ``0048`` format General trzyma bez ``+`` i zer (``PHONE_WITH_PREFIX_NUMBER``)."""


@dataclass(frozen=True)
class NumbersInCells:
    """Uruchomienie z liczbami w komórkach: Centrum gotowe do startu i komórki Kopii wejścia z numerem Orange albo
    telefonem po strażniku (wiersz arkusza → litera → maska), a ``elsewhere``: pola Logów poza Kopią z numerem Orange
    (ilości przy zleceniu Wyceny w efenix; ``steps[…]``: którekolwiek działanie okna)."""

    centrum: PreparingCentrum | SettlingCentrum
    masked: dict[int, dict[str, str]]
    elsewhere: frozenset[str] = frozenset()


def _numbers_preparation(tmp_path: Path, _: ExitStack) -> NumbersInCells:
    rows = default_register_rows()
    rows[2] = {**(rows[2] or {}), "NUMER UMOWY": ORANGE_NUMBER, "UMOWA": ORANGE_NUMBER, "CZYNNOŚCI ZREALIZOWANE": PHONE_NUMBER}
    return NumbersInCells(preparing_centrum(tmp_path, rows), {4: {"F": "[numer Orange]", "M": "[telefon]"}})


def _numbers_settlement(tmp_path: Path, _: ExitStack) -> NumbersInCells:
    """Excel zapisał numer Orange w I18 jako ułamek (``4.801234567E9``), a ten sam numer w AT18 jako liczbę całkowitą;
    telefon wpisany z ``+48`` w AQ18 to liczba ``48600123456``."""

    centrum = settling_centrum(tmp_path)
    cells: dict[str, CellValue] = {"I": ORANGE_NUMBER, "AT": ORANGE_NUMBER, "AS": PHONE_NUMBER, "AQ": PHONE_WITH_PREFIX_NUMBER}
    write_quantity_source(centrum.collective_file, [cells])
    as_fraction = re.compile(rb'(<c r="I18"[^>]*><v>)' + ORANGE_VALUE.encode() + rb"(</v>)")

    def fraction(name: str, data: bytes) -> bytes:
        if name != "xl/worksheets/sheet1.xml":
            return data
        changed, count = as_fraction.subn(rb"\g<1>4.801234567E9\g<2>", data)
        assert count == 1
        return changed

    rewrite_parts(centrum.collective_file, fraction)
    return NumbersInCells(centrum, {18: {"AT": "[numer Orange]", "AS": "[telefon]", "AQ": "[telefon]"}})


def _numbers_pricing(tmp_path: Path, stack: ExitStack) -> NumbersInCells:
    """Numer Orange także w kolumnie ilości (O) dwóch zleceń: wiersz 18 ma tę wycenę już w efenix (okno czyta ilości ze
    strony zlecenia), a wiersz 19 nie ma żadnej (okno wpisuje ilość)."""

    amount = float(amount_of({"012": ORANGE_NUMBER}))
    cells: dict[str, CellValue] = {"I": ORANGE_NUMBER, "O": ORANGE_NUMBER, "AQ": ORANGE_NUMBER, "AT": PHONE_NUMBER}
    priced = Order("#ZLKW04", cells=cells, amount=amount, quantities={"012": ORANGE_NUMBER})
    unpriced = Order("#ZLKW05", cells={"O": ORANGE_NUMBER}, amount=amount)
    atrapa = stack.enter_context(atrapa_efenix([priced.in_efenix("704"), unpriced.in_efenix("705")]))
    centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
    write_collective_file(centrum.period_parent, [priced, unpriced])
    masked = {18: {"O": "[numer Orange]", "AQ": "[numer Orange]", "AT": "[telefon]"}, 19: {"O": "[numer Orange]"}}
    elsewhere = {
        "efenix_orders[0].file.[…]",
        "efenix_orders[0].steps[…].quantities.[…]",
        "efenix_orders[1].file.[…]",
        "efenix_orders[1].steps[…].quantity",
    }
    return NumbersInCells(centrum, masked, frozenset(elsewhere))


NUMBER_PROCESSES = {"preparation": _numbers_preparation, "settlement": _numbers_settlement, "efenix": _numbers_pricing}


@pytest.mark.parametrize("process", NUMBER_PROCESSES.keys())
def test_numer_orange_i_telefon_zapisane_przez_excel_jako_liczba_nie_wychodza_do_logow_ani_skrzynki(
    tmp_path: Path, process: str
) -> None:
    """Numer Orange i telefon, które Excel trzyma jako liczbę, strażnik porównuje w tekście, który pokazuje Excel (numer
    zapisany jako ułamek to jego cyfry), więc liczba w innej komórce Kopii wejścia i w ilości przy zleceniu Wyceny w
    efenix (z pliku, ze strony zlecenia i wpisana w oknie) staje się w całości maską z uwagą techniczną o jej miejscu,
    a telefon, także z ``+48`` zgubionym przez format General, maską ``[telefon]``; nic z tego nie wychodzi do pliku
    Logów ani do Skrzynki Zgłoszeń."""

    with ExitStack() as stack:
        setup = NUMBER_PROCESSES[process](tmp_path, stack)
        centrum = setup.centrum
        write_report_key(ToolDirectory(tmp_path))
        started = centrum.client.post("/api/runs", json={"process": process, "period": PERIOD, "mode": "DRY-RUN" if process != "efenix" else "RUN"})
        assert started.status_code == 200, started.json()
        result = finished_view(centrum.client)["result"]

    assert result["stop_kind"] is None, result["stops"]
    box: FakeReportBox = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: logs_arrived(fake, 1))
    [record] = records(centrum)
    [copied] = record["input_copy"]
    [sheet] = copied["sheets"]
    rows = {row["row"]: (index, row["cells"]) for index, row in enumerate(sheet["rows"])}
    assert {number: {letter: rows[number][1].get(letter) for letter in cells} for number, cells in setup.masked.items()} == setup.masked
    orange = "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: {}."
    assert record["input_copy_notes"] == [
        orange.format(f"input_copy[0].sheets[0].rows[{rows[number][0]}].cells.[…]")
        for number, cells in sorted(setup.masked.items())
        if "[numer Orange]" in cells.values()
    ]
    card = len(result["technical_notes"])
    assert record["technical_notes"][:card] == result["technical_notes"], "uwagi techniczne karty"
    assert {re.sub(r"steps\[\d+\]", "steps[…]", note) for note in record["technical_notes"][card:]} == {
        orange.format(place) for place in setup.elsewhere
    }
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    sent = in_box(box) + [part for issue in box.issues for part in (issue.title, issue.body, *issue.comments)]
    assert any("[numer Orange]" in part for part in sent), "Kopia wejścia w pliku Logów w Archiwum"
    leaked = (ORANGE_VALUE, str(PHONE_NUMBER), str(PHONE_WITH_PREFIX_NUMBER))
    assert [value for value in leaked if any(value in text for text in texts + sent)] == []


@contextmanager
def _refused(monkeypatch: pytest.MonkeyPatch, method: str, refuses: Callable[[Path, str], bool]) -> Iterator[None]:
    """``Path.<method>`` rzuca PermissionError (plik trzyma antywirus albo inny program), gdy ``refuses`` mówi tak o
    ścieżce i trybie otwarcia."""

    original = getattr(Path, method)

    def refusing(self: Path, *arguments: Any, **keywords: Any) -> Any:
        mode = arguments[0] if arguments and isinstance(arguments[0], str) else keywords.get("mode", "r")
        if refuses(self, mode):
            raise PermissionError(13, "plik zajęty")
        return original(self, *arguments, **keywords)

    with monkeypatch.context() as patch:
        patch.setattr(Path, method, refusing)
        yield


def test_dziennik_urwanej_wyceny_nieodczytany_przy_starcie_dostaje_logi_urwanego_uruchomienia_takze_po_nastepnej_wycenie_z_wynikiem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#870: Wycena 1 urwana po „zaczynam zlecenie”, a start Centrum nie może przeczytać jej dziennika, więc zostawia go
    następnemu. W tej pracy Centrum Wycena 2 dochodzi do wyniku i ma wiersz Historii ze startem późniejszym niż Wycena 1.
    Następny start zamyka dziennik Wyceny 1 jako jej Logi Urwanego Uruchomienia ze zleceniem zaczętym bez wyniku i wysyła
    je do Skrzynki obok Logów Wyceny 2, a dopiero potem dziennik znika."""

    run_1 = "a" * 32
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, orders=FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        box = centrum.surroundings.report_box
        started_at = datetime.now(timezone.utc) - timedelta(hours=1)
        started = StartFacts(run_id=run_1, process="efenix", mode=RunMode.RUN, period=PERIOD, started_at=started_at)
        begun = begun_line(started_at + timedelta(seconds=30), row=18, place=1, total=6)
        journal_1 = left_journal(centrum.log_path.parent, started, begun)
        centrum.client.stop()
        with _refused(monkeypatch, "read_text", lambda path, _: path == journal_1):
            centrum.restart()
            centrum.client.start()
            assert centrum.client.get("/api/runs/current").status_code == 200
        skipped = (journal_1.exists(), log_files(centrum))
        assert _start_pricing(centrum).status_code == 200
        run_2 = finished_view(centrum.client)["run"]["id"]
        centrum.client.stop()
        centrum.restart()
        centrum.client.start()
        assert centrum.client.get("/api/runs/current").status_code == 200
        sent = box.wait_until(lambda fake: logs_arrived(fake, 2))
        centrum.client.stop()
    logged = {record["run_id"]: record for record in records(centrum)}

    assert (skipped, sent) == ((True, []), True)
    assert {run_id: record["ending"] for run_id, record in logged.items()} == {run_1: "interrupted", run_2: "finished"}
    assert logged[run_1]["interruption"] == {"row": 18, "place": 1, "total": 6, "omitted": 0}
    assert sorted(logs_json(box, comment)["run_id"] for comment in logs_comments(box)) == sorted([run_1, run_2])
    assert journals(centrum) == [], "dziennik, którego Logi przyjęła Kolejka wysyłki, znika"


def test_wycena_z_wynikiem_bez_pliku_logow_i_bez_rekordu_metryk_ma_logi_z_wynikiem_w_skrzynce_a_dziennik_znika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#871: Wycena doszła do wyniku, ale pliku jej Logów nie ma (katalog Logów zajęty przez plik), a rekord metryk się
    nie zapisał (pełny dysk). Logi z wynikiem idą do Skrzynki z kolejki, a dziennik znika za nimi, więc następny start
    nie ma czego zamknąć jako Urwane Uruchomienie."""

    blocked = ToolDirectory(tmp_path).run_logs
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")  # plik zamiast katalogu Logów: LogsOnDisk.write rzuca OSError

    def full_disk(_store: MetricsStore, _record: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(MetricsStore, "append", full_disk)
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, orders=FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        box = centrum.surroundings.report_box
        assert _start_pricing(centrum).status_code == 200
        run_id = finished_view(centrum.client)["run"]["id"]
        assert box.wait_until(lambda fake: logs_arrived(fake, 1))
        centrum.client.stop()

    assert (centrum.engines.metrics.efenix.exists(), journals(centrum)) == (False, [])
    assert [(logs["run_id"], logs["ending"]) for logs in (logs_json(box, comment) for comment in logs_comments(box))] == [
        (run_id, "finished")
    ]


def test_wpis_konca_ktory_sie_nie_zapisal_zostawia_dziennik_do_przyjecia_logow_z_wynikiem_a_start_nie_robi_z_wyceny_urwanego_uruchomienia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Każdy wpis Wyceny w efenix się zapisuje oprócz wpisu końca, bo po rekordzie metryk antywirus trzyma dziennik, a
    pliku Logów nie ma (katalog Logów zajęty przez plik). Kolejka wysyłki przyjmuje Logi z wynikiem, więc dziennik bez
    wpisu końca znika za nimi (``RunComments.run_ended``), z jedną linią dziennika Centrum, a następny start nie robi z Wyceny
    Urwanego Uruchomienia i w Skrzynce zostają Logi z wynikiem."""

    blocked = ToolDirectory(tmp_path).run_logs
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, orders=FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        box = centrum.surroundings.report_box
        metrics = centrum.engines.metrics.efenix

        def after_result(path: Path, mode: str) -> bool:
            return path.parent.name == "dzienniki-wyceny" and mode == "a" and metrics.exists()

        with _refused(monkeypatch, "open", after_result):
            assert _start_pricing(centrum).status_code == 200
            finished_view(centrum.client)
        assert box.wait_until(lambda fake: logs_arrived(fake, 1))
        centrum.client.stop()
    ended = journals(centrum)
    blocked.unlink()
    centrum.restart()
    assert centrum.client.get("/api/runs/current").status_code == 200
    centrum.client.stop()
    lines = [line.split(" ", 1)[1] for line in centrum.log_path.read_text(encoding="utf-8").splitlines() if "dziennik-wyceny" in line]

    assert (ended, lines) == ([], ["dziennik-wyceny-niedostepny typ=PermissionError miejsce=wpis"])
    assert (records(centrum), [logs_json(box, comment)["ending"] for comment in logs_comments(box)]) == ([], ["finished"])


class _Unconfirmed:
    """Plik dziennika, którego zapis dysk przyjął (``write`` i ``flush``), ale nie potwierdził: ``fsync`` na jego deskryptorze
    zgłasza błąd wejścia-wyjścia."""

    def __init__(self, file: Any) -> None:
        self._file = file

    def __enter__(self) -> _Unconfirmed:
        self._file.__enter__()
        return self

    def __exit__(self, *exception: object) -> None:
        self._file.__exit__(*exception)

    def write(self, text: str) -> int:
        return int(self._file.write(text))

    def flush(self) -> None:
        self._file.flush()

    def fileno(self) -> NoReturn:
        raise OSError(errno.EIO, "Input/output error")


def test_wycena_z_wynikiem_ktorej_jedyny_wpis_dziennika_zawiodl_po_zapisie_pierwszej_linii_nie_dostaje_logow_urwanego_uruchomienia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pierwsza linia dziennika Wyceny w efenix (przy jej starcie, #846) i jej pierwszy wpis, „zaczynam zlecenie”, razem z
    nią są już na dysku, gdy dysk przy każdym z tych zapisów zgłasza błąd wejścia-wyjścia, więc żaden zapis nie
    potwierdził pierwszej linii, a okno efenix staje przy tym samym zleceniu (strona błędu HTTP), więc Wycena dochodzi do
    wyniku z Zatrzymaniem bez następnego wpisu. Pliku Logów nie ma (katalog Logów zajęty przez plik), więc jej Logi z
    wynikiem idą do Skrzynki tylko z kolejki. Wycena usuwa dziennik sama, z jedną linią dziennika Centrum, więc następny
    start nie robi z niej Urwanego Uruchomienia, a w Skrzynce zostają Logi z wynikiem."""

    blocked = ToolDirectory(tmp_path).run_logs
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    opened = Path.open
    unconfirmed: list[Path] = []

    def opening(self: Path, *arguments: Any, **keywords: Any) -> Any:
        file = opened(self, *arguments, **keywords)
        mode = arguments[0] if arguments and isinstance(arguments[0], str) else keywords.get("mode", "r")
        if self.parent.name == "dzienniki-wyceny" and mode == "a":
            unconfirmed.append(self)
            return _Unconfirmed(file)
        return file

    with atrapa_efenix([HYPOTHESES["D-strona-bledu-http"][0]]) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, STOPPED_AT_SECOND[1:])
        write_report_key(ToolDirectory(tmp_path))
        box = centrum.surroundings.report_box
        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", opening)
            assert _start_pricing(centrum).status_code == 200
            stops = finished_view(centrum.client)["result"]["stops"]
        assert box.wait_until(lambda fake: logs_arrived(fake, 1))
        centrum.client.stop()
    left = journals(centrum)
    blocked.unlink()
    centrum.restart()
    assert centrum.client.get("/api/runs/current").status_code == 200
    centrum.client.stop()
    lines = [line.split(" ", 1)[1] for line in centrum.log_path.read_text(encoding="utf-8").splitlines() if "dziennik-wyceny" in line]

    assert (len(unconfirmed), len(stops), lines) == (2, 1, ["dziennik-wyceny-niedostepny typ=OSError miejsce=wpis"])
    assert (records(centrum), left, [logs_json(box, comment)["ending"] for comment in logs_comments(box)]) == ([], [], ["stop"])


PRICING_START = StartFacts(
    run_id="e" * 32, process="efenix", mode=RunMode.RUN, period=PERIOD, started_at=utc("2026-09-16T10:15:00+00:00")
)


def journal_log_lines(log: CentrumLog) -> list[str]:
    return [line.split(" ", 1)[1] for line in log.directory.joinpath("centrum.log").read_text(encoding="utf-8").splitlines()]


def test_dziennik_ktorego_pierwsza_linia_sie_nie_zapisala_dostaje_ja_z_pierwszym_zapisanym_wpisem_a_postep_tylko_z_dysku(
    tmp_path: Path,
) -> None:
    """Start Wyceny nie zapisał pierwszej linii dziennika (w miejscu katalogu dzienników stoi plik), a pierwszy wpis też
    nie, więc postępu nie ma. Następny wpis, który się zapisał, niesie pierwszą linię przed sobą: od niego postęp jest z
    tego, co dziennik ma na dysku, a start Centrum czyta z dziennika start Uruchomienia i zlecenie zaczęte bez wyniku.
    Nieudane zapisy jednego Uruchomienia to jedna linia dziennika Centrum."""

    log = CentrumLog(tmp_path / "centrum.log")
    disk = LogsOnDisk(log, journaled="efenix")
    blocked = tmp_path / "dzienniki-wyceny"
    blocked.write_text("", encoding="utf-8")

    disk.started(PRICING_START)
    disk.journal.begun(18, 1, 2)
    failed = disk.journal.progress(PRICING_START.run_id)
    blocked.unlink()
    disk.journal.begun(19, 2, 2)
    progress = disk.journal.progress(PRICING_START.run_id)
    [left] = disk.left_behind()

    assert (failed, progress) == (None, PricingProgress(PRICING_START, (), 2, 19))
    assert left.journal is not None
    assert (left.journal.started, left.journal.interruption.row, left.journal.end) == (PRICING_START, 19, None)
    assert journal_log_lines(log) == ["dziennik-wyceny-niedostepny typ=FileExistsError miejsce=wpis"]


def test_uruchomienie_innego_procesu_nie_ma_dziennika_ani_postepu(tmp_path: Path) -> None:
    log = CentrumLog(tmp_path / "centrum.log")
    disk = LogsOnDisk(log, journaled="efenix")
    settlement = StartFacts(
        run_id="f" * 32, process="settlement", mode=RunMode.RUN, period=PERIOD, started_at=PRICING_START.started_at
    )

    disk.started(settlement)
    disk.journal.begun(18, 1, 2)
    disk.journal.end(settlement.run_id, "OK")

    assert (disk.journal.progress(settlement.run_id), list(disk.left_behind())) == (None, [])


def test_koniec_innego_uruchomienia_nie_konczy_dziennika_wyceny(tmp_path: Path) -> None:
    """Wpis końca należy do Uruchomienia, którego wynik niesie: koniec innego Uruchomienia zostawia dziennik Wyceny bez
    wpisu końca, więc start Centrum dalej widzi w nim Wycenę, która nie doszła do wyniku."""

    log = CentrumLog(tmp_path / "centrum.log")
    disk = LogsOnDisk(log, journaled="efenix")

    disk.started(PRICING_START)
    disk.journal.begun(18, 1, 2)
    disk.journal.end("f" * 32, "OK")
    [left] = disk.left_behind()

    assert left.journal is not None
    assert (left.journal.started, left.journal.end) == (PRICING_START, None)


def test_plik_ostatniego_startu_ktorego_nie_da_sie_zapisac_nie_zabiera_wycenie_dziennika(tmp_path: Path) -> None:
    """Start Wyceny pisze pierwszą linię dziennika, zanim zapisze plik ostatniego startu, więc plik ostatniego startu,
    którego nie da się zapisać (w miejscu jego pliku tymczasowego stoi katalog), zatrzymuje start Uruchomienia dopiero wtedy, gdy dziennik
    ma już start na dysku, a postęp jest z niego."""

    log = CentrumLog(tmp_path / "centrum.log")
    disk = LogsOnDisk(log, journaled="efenix")
    (tmp_path / f"{LAST_STARTED_FILE}.tmp").mkdir()

    with pytest.raises(OSError, match=LAST_STARTED_FILE):
        disk.started(PRICING_START)
    [left] = disk.left_behind()

    assert left.journal is not None
    assert (left.journal.started, disk.journal.progress(PRICING_START.run_id)) == (
        PRICING_START,
        PricingProgress(PRICING_START, (), None, None),
    )


def test_kazdy_wpis_dziennika_wyceny_jest_w_pliku_zanim_dysk_potwierdzi_zapis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Każdy wpis dziennika jest na dysku (``fsync``), zanim silnik zrobi następny krok, więc brak prądu urywa najwyżej
    wpis w trakcie zapisu: w chwili potwierdzenia plik dziennika ma już cały wpis, a nie tylko wpisy przed nim."""

    log = CentrumLog(tmp_path / "centrum.log")
    disk = LogsOnDisk(log, journaled="efenix")
    synced: list[int] = []
    sync = os.fsync

    def syncing(descriptor: int) -> None:
        synced.append(os.fstat(descriptor).st_size)
        sync(descriptor)

    monkeypatch.setattr(os, "fsync", syncing)
    disk.started(PRICING_START)
    disk.journal.begun(18, 1, 2)
    [journal] = (tmp_path / "dzienniki-wyceny").iterdir()
    written = journal.read_bytes()

    assert synced == [written.index(b"\n") + 1, len(written)]


@pytest.mark.parametrize("refused", ["lista-dziennikow", "dziennik"])
def test_dziennik_ktorego_start_centrum_nie_moze_wylistowac_ani_odczytac_zostaje_z_linia_dziennika_centrum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str
) -> None:
    """Start Centrum nie może wylistować katalogu dzienników Wyceny albo odczytać dziennika (plik trzyma inny program):
    dziennik zostaje do następnego startu, a dziennik Centrum ma o tym linię z typem błędu, bo inaczej Maks nie wie,
    czemu komentarz Uruchomienia wciąż mówi, że trwa."""

    log = CentrumLog(tmp_path / "centrum.log")
    disk = LogsOnDisk(log, journaled="efenix")
    disk.started(PRICING_START)
    method = "glob" if refused == "lista-dziennikow" else "read_text"
    target = "dzienniki-wyceny" if refused == "lista-dziennikow" else name_of(PRICING_START).replace(".json", ".jsonl")

    with _refused(monkeypatch, method, lambda path, _: path.name == target):
        left = list(disk.left_behind())
    [after] = disk.left_behind()

    assert (left, after.journal is not None) == ([], True)
    assert journal_log_lines(log) == ["dziennik-wyceny-niedostepny typ=PermissionError miejsce=start"]


@pytest.mark.parametrize("confirmed", [True, False], ids=["z-pierwsza-linia", "bez-potwierdzonej-pierwszej-linii"])
def test_wpis_konca_dziennika_z_pierwsza_linia_niesie_wynik_a_dziennik_bez_niej_znika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, confirmed: bool
) -> None:
    """Dziennik z pierwszą linią na dysku dostaje wpis końca z wynikiem, który start Centrum z niego czyta. Gdy żaden zapis
    nie potwierdził pierwszej linii (dysk zgłasza błąd przy ``fsync`` po ``write``), cała linia może być na dysku, a
    postępu nie było, więc koniec Uruchomienia usuwa dziennik zamiast wpisu końca: start nie zrobi z niego Urwanego
    Uruchomienia."""

    log = CentrumLog(tmp_path / "centrum.log")
    disk = LogsOnDisk(log, journaled="efenix")
    opened = Path.open

    def opening(self: Path, *arguments: Any, **keywords: Any) -> Any:
        file = opened(self, *arguments, **keywords)
        return file if confirmed or self.parent.name != "dzienniki-wyceny" else _Unconfirmed(file)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", opening)
        disk.started(PRICING_START)
    on_disk = [left.journal is not None for left in disk.left_behind()]
    disk.journal.end(PRICING_START.run_id, "WYMAGA_SPRAWDZENIA")
    ends = [None if left.journal is None else left.journal.end for left in disk.left_behind()]

    assert on_disk == [True]
    assert ends == ([EndEntry("WYMAGA_SPRAWDZENIA")] if confirmed else [])


def held_before_removal(monkeypatch: pytest.MonkeyPatch) -> tuple[threading.Event, threading.Event]:
    """Usunięcie dziennika Wyceny za Logami z wynikiem (``Journal.remove``, ostatni krok ``RunComments.run_ended``) czeka,
    aż test je puści: ponowny start Centrum w tym czasie to Centrum zgaszone zaraz po wysyłce Logów z wynikiem do
    kolejki, przed usunięciem dziennika. Daje parę (doszło, puść)."""

    reached, released = threading.Event(), threading.Event()
    remove = Journal.remove

    def held(journal: Journal, run_id: str) -> None:
        reached.set()
        released.wait()
        remove(journal, run_id)

    monkeypatch.setattr(Journal, "remove", held)
    return reached, released


class SwitchedOffAfterRelease(Exception):
    """Wątek Uruchomienia w Centrum, które test uznał za zgaszone: po puszczeniu kończy się bez Logów z wynikiem."""


def test_centrum_zgaszone_zaraz_po_wyslaniu_logow_z_wynikiem_wyceny_w_efenix_nie_zastepuje_ich_logami_urwanego_uruchomienia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Centrum gaśnie zaraz po tym, jak Logi z wynikiem Wyceny w efenix poszły do Kolejki wysyłki, a pliku Logów nie ma
    (katalog Logów zajęty przez plik), zanim dziennik zniknął za nimi. Wycena dopisała wpis końca do dziennika przed
    swoimi Logami, więc następny start nie robi z niej Urwanego Uruchomienia, tylko wysyła wynik bez Logów, a ten ma
    niższy stopień wersji niż Logi z wynikiem: jedyny komentarz Uruchomienia w Skrzynce zostaje Logami z wynikiem z
    odnośnikiem do ich pliku w Archiwum, bez żadnej zmiany, a dziennik znika (#871, #910)."""

    blocked = ToolDirectory(tmp_path).run_logs
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    reached, released = held_before_removal(monkeypatch)
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa, orders=FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        box = centrum.surroundings.report_box
        assert _start_pricing(centrum).status_code == 200
        assert wait_for(reached.is_set, 120)
        sent = box.wait_until(lambda fake: logs_arrived(fake, 1))
        edited = list(box.edited)
        closed = centrum.client
        blocked.unlink()
        centrum.restart()
        centrum.client.start()
        assert centrum.client.get("/api/runs/current").status_code == 200
        queue = ToolDirectory(tmp_path).queue
        settled = wait_for(lambda: queued_logs(queue) == [], 10)
        after = (records(centrum), journals(centrum), box.edited == edited)
        released.set()
        finished_view(closed)
    centrum.client.stop()
    [comment] = logs_comments(box)

    assert (sent, settled, after) == (True, True, ([], [], True)), "Logi z wynikiem zmienione po starcie"
    assert logs_json(box, comment)["ending"] == "finished"


def test_bez_sieci_logi_z_wynikiem_zgaszonej_wyceny_w_efenix_czekaja_w_kolejce_po_starcie_i_dochodza_z_plikiem_do_archiwum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jak wyżej, ale bez sieci: Skrzynka nie odpowiada od startu Wyceny do chwili po następnym starcie Centrum, więc Logi
    z wynikiem czekają w Kolejce wysyłki, a pliku Logów na dysku taty nie ma. Start wysyła z dziennika z wpisem końca
    wynik bez Logów, który czeka w kolejce obok nich, a dziennik znika. Kolejka bierze wersję wyższego stopnia, więc po
    powrocie sieci wynik bez Logów znika bez wysłania, a jedyny komentarz Uruchomienia w issue okresu to Logi z wynikiem z
    odnośnikiem do ich pliku w Archiwum Logów okresu (#871, #910)."""

    blocked = ToolDirectory(tmp_path).run_logs
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    queue = ToolDirectory(tmp_path).queue
    reached, released = held_before_removal(monkeypatch)
    surroundings = Surroundings()
    box = surroundings.report_box
    box.background = frozenset()
    box.search_failure = Unreachable()
    with atrapa_efenix(FEW_IN_EFENIX) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, FEW_PRICED)
        write_report_key(ToolDirectory(tmp_path))
        started = _start_pricing(centrum)
        assert started.status_code == 200, started.json()
        assert wait_for(reached.is_set, 120)
        waiting = wait_for(lambda: len(queued_logs(queue)) == 1, 10)
        closed = centrum.client
        blocked.unlink()
        centrum.restart()
        with centrum.client:  # start Centrum jak u taty: ``lifespan`` wznawia Kolejkę wysyłki, która nie ma sieci
            assert centrum.client.get("/api/runs/current").status_code == 200
            after = (len(queued_logs(queue)), journals(centrum), log_files(centrum))
            box.search_failure = None
            surroundings.clock.advance(RETRY_S)
            _, texts = comment_history(centrum)
        released.set()
        finished_view(closed)
    centrum.client.stop()
    [summary] = texts
    logs = archived_logs(centrum, summary)

    assert (waiting, after) == (True, (2, [], [])), "Logi z wynikiem i wynik bez Logów w kolejce, dziennik i plik Logów"
    assert (logs["run_id"], logs["ending"]) == (started.json()["run"]["id"], "finished")


WITHOUT_LOGS = "- Pełne Logi: nie ma, Centrum nie zapisało ich po wyniku (np. zamknęło się tuż po nim)"


def test_centrum_zgaszone_po_wpisie_konca_a_przed_logami_z_wynikiem_konczy_komentarz_postepu_wynikiem_bez_logow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Centrum gaśnie po wpisie końca dziennika Wyceny w efenix, a przed jej Logami z wynikiem: działania po wyniku nie
    dochodzą do pliku Logów ani do Kolejki wysyłki, a komentarz Uruchomienia w issue okresu ma postęp, który mówi, że
    Uruchomienie trwa. Następny start ma dziennik z wpisem końca bez pliku Logów, więc ten sam komentarz zmienia się w
    wynik bez Logów: wynik Wyceny z wpisu końca, wszystkie zlecenia z dziennika i linię, że pełnych Logów nie ma, a
    dziennik znika (#910)."""

    reached, released = threading.Event(), threading.Event()

    def switched_off(records: RecordMaker, run: Any) -> NoReturn:  # Centrum gaśnie: Logi z wynikiem nie powstają
        reached.set()
        released.wait()
        raise SwitchedOffAfterRelease

    monkeypatch.setattr(RecordMaker, "of", switched_off)
    with pricing(tmp_path) as (centrum, _, _):
        assert _start_pricing(centrum).status_code == 200
        assert wait_for(reached.is_set, 120)
        box = centrum.surroundings.report_box
        closed = centrum.client
        centrum.restart()
        centrum.client.start()
        assert centrum.client.get("/api/runs/current").status_code == 200
        ended = box.wait_until(
            lambda fake: [text.splitlines()[-1] for issue in fake.issues_with(PROGRESS_LABEL) for text in issue.comments]
            == [WITHOUT_LOGS]
        )
        after = journals(centrum)
        released.set()
        result = finished_view(closed)["result"]["result"]
    centrum.client.stop()
    [issue] = box.issues_with(PROGRESS_LABEL)
    [comment_id] = issue.comment_ids
    *progress, final = [shown(text) for written, text in box.written if written == comment_id]
    lines = final.splitlines()

    assert (ended, after, lines[-1]) == (True, [], WITHOUT_LOGS)
    assert progress != [] and all("- Wynik: jeszcze nie ma, Uruchomienie trwa" in text.splitlines() for text in progress)
    [orders] = [line for line in lines if line.startswith("- Zlecenia: ")]
    assert (f"- Wynik: {result}" in lines, orders.startswith(f"- Zlecenia: {len(PRICED)} z {len(PRICED)} ")) == (True, True)


def test_cofniety_zegar_komputera_nie_daje_postepowi_w_kolejce_pierwszenstwa_przed_logami_urwanego_uruchomienia(
    tmp_path: Path,
) -> None:
    """Zegar komputera taty cofnął się, gdy Centrum było zamknięte (np. bateria CMOS po braku prądu, a bez sieci Windows
    go nie poprawi), więc postęp Urwanej Wyceny w efenix czeka w Kolejce wysyłki z chwilą w nazwie pliku późniejszą niż
    każda wysyłka następnej pracy Centrum. Start bez sieci zamyka dziennik Logami Urwanego Uruchomienia, które mają wyższy
    stopień wersji niż postęp, i usuwa dziennik. Po powrocie sieci postęp znika z kolejki bez wysłania, jedyny komentarz
    Uruchomienia to podsumowanie Logów Urwanego Uruchomienia, a ich plik jest w Archiwum Logów okresu (#910)."""

    centrum = settling_centrum(tmp_path)
    box = centrum.surroundings.report_box
    box.background = frozenset()
    write_report_key(ToolDirectory(tmp_path))
    started = StartFacts(
        run_id="c" * 32,
        process="efenix",
        mode=RunMode.RUN,
        period=PERIOD,
        started_at=utc("2026-09-16T10:15:00+00:00"),
    )
    order = LoggedOrder(row=18, outcome=OrderKind.READY, code=None, file={}, file_amount=Decimal(0), steps=[])
    begun = begun_line(utc("2026-09-16T10:16:00+00:00"), row=18, place=1, total=2)
    ended = ended_line(utc("2026-09-16T10:17:00+00:00"), order)
    left_journal(centrum.log_path.parent, started, begun, ended)
    progress = PricingProgress(started, (OrderDone(18, OrderKind.READY, None),), 2, None)
    text = guard_text(progress_markdown(progress, elapsed_s=600), "postęp Wyceny w efenix", empty_memory())
    queue = ToolDirectory(tmp_path).queue
    queue.mkdir(parents=True)
    # Poprzednia praca Centrum zapisała postęp, zanim zegar się cofnął: chwila w nazwie jest „w przyszłości”.
    (queue / f"20991231T235959000000Z-0007-{PROGRESS_LABEL}-{started.run_id[:8]}.json").write_text(
        post_of(ProgressVersion(progress, text)).to_json(), encoding="utf-8"
    )

    box.search_failure = Unreachable()
    centrum.restart()
    with centrum.client:  # start Centrum jak u taty: ``lifespan`` wznawia Kolejkę wysyłki, która nie ma sieci
        assert centrum.client.get("/api/runs/current").status_code == 200
        # Przejście kolejki ze startu (``lifespan``) mogło przeczytać kolejkę przed Logami z pierwszego zapytania, więc
        # widzi tylko postęp: sieć wraca dopiero, gdy każde przejście bez sieci stanęło i nastawiło ponowienie (noc 7.11).
        clock = centrum.surroundings.clock
        waiting = wait_for(lambda: len(queued_logs(queue)) == 2 and clock.wakes == 1, 10)
        after = journals(centrum)
        box.search_failure = None
        clock.advance(RETRY_S)
        _, texts = comment_history(centrum)
    centrum.client.stop()

    assert (waiting, after) == (True, []), "postęp i Logi Urwanego Uruchomienia w kolejce, ponowienie, dziennik po starcie"
    [summary] = texts
    logs = archived_logs(centrum, summary)
    assert (logs["run_id"], logs["ending"], [order["row"] for order in logs["efenix_orders"]]) == (
        started.run_id,
        "interrupted",
        [18],
    )
