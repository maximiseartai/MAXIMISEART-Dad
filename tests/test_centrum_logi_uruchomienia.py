"""Logi Uruchomienia (ADR 0015, #317) przez HTTP API Centrum: plik JSON na komputerze taty po każdym Uruchomieniu.

Testy czytają pliki z katalogu Logów obok dziennika Centrum, tak jak Maks dostanie je z komputera taty.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import datetime, time as time_of_day, timedelta, timezone
from decimal import Decimal
import hashlib
from http import HTTPStatus
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import sys
import time
from typing import Any, Final, Literal, NoReturn, get_args

from openpyxl import load_workbook
from openpyxl.worksheet.formula import ArrayFormula
from playwright.sync_api import Browser, sync_playwright
import pytest

from rozliczenia import TOOL_ROOT, efenix_process, settlement_messages, workbook_files
from rozliczenia.centrum import app, contract, runs
from rozliczenia.centrum.dad_actions import DAD_ACTIONS_FILE, MAX_ENTRIES, DadActions
from rozliczenia.centrum.efenix_run import EfenixWindow
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.pricing_journal import JournalStarted, OrderBegun, OrderEnded, PricingJournal
from rozliczenia.centrum.pricing_progress import PROGRESS_S
from rozliczenia.centrum.run_logs import (
    Environment,
    LoggedInterruption,
    LoggedOrder,
    LoggedStep,
    PricingProgress,
    RunLog,
    Tool,
    logi_post,
    logs_file_name,
    progress_markdown,
    progress_post,
)
from rozliczenia.centrum.report_box import Unreachable
from rozliczenia.centrum.tool_update import Release
from rozliczenia.efenix_pace import ACTION_PAUSE_S, KEEPALIVE_S, Pace
from rozliczenia.input_checks import FILE_READERS
from rozliczenia.period_folder import PeriodFolderInaccessible
from rozliczenia.telemetry import MetricsStore, metric_record

from tests.fixtures.atrapa_efenix import CATALOG, AtrapaEfenix, AtrapaOrder, Changed, amount_of, atrapa_efenix
from tests.fixtures.centrum import (
    TOOL_COMMIT,
    FakeGitHub,
    FakeReportBox,
    finished_view,
    run_events,
    view_timing,
    views_until,
    without_times,
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
from tests.fixtures.centrum_w_procesie import centrum_process
from tests.fixtures.efenix import DAY, Order, write_collective_file
from tests.fixtures.konce_linii_windows import windows_text_writes
from tests.fixtures.potomne import wait_for
from tests.fixtures.preparation import PERIOD, default_register_rows, incomplete_period_rows
from tests.fixtures.run_cards import first_view, restored
from tests.fixtures.settlement import COLLECTIVE_HEADERS, MARKED, SOURCE_NAME, CellValue, write_quantity_source
from tests.fixtures.tool_clone import ToolRepository, git_command, git_failing_on, tool_repository
from tests.fixtures.widok_skrzynki import shown
from tests.fixtures.workbooks import active_worksheet, rewrite_parts

AnyCentrum = PreparingCentrum | SettlingCentrum
KEYS = {
    "schema_version", "run_id", "process", "mode", "period", "started_at", "ended_at", "duration_ms", "tool",
    "result", "ending", "stop_kind", "issue_count", "messages", "technical_notes", "summary", "phases", "templates",
    "inea_only_cleared", "intermax_entries", "efenix_orders", "efenix_stop", "environment", "trace", "diagnosis",
    "dad_actions", "interruption", "input_copy", "input_copy_notes",
}


def log_files(centrum: AnyCentrum) -> list[Path]:
    return sorted((centrum.log_path.parent / "uruchomienia").glob("*"))


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
    return [{part: message[part] for part in ("what", "where", "action")} for message in record["messages"]]


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


def _broken_worker_config(tmp_path: Path, _: pytest.MonkeyPatch) -> Ran:
    centrum = settling_centrum(tmp_path)
    centrum.configuration.worker_config.write_text(":: nie yaml", encoding="utf-8")
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
        run_outcome = contract.RunOutcome
        built: list[str] = []

        def broken_once(**fields: Any) -> contract.RunOutcome:
            built.append(fields["ending"])
            if len(built) == 1:
                raise ValueError("synthetic contract failure SYN-001")
            return run_outcome(**fields)

        monkeypatch.setattr(contract, "RunOutcome", broken_once)
        return steered, run_to_end(steered, dry_run=dry_run)

    return run


def _core_failed(
    centrum: Callable[[Path], AnyCentrum], *, dry_run: bool
) -> Callable[[Path, pytest.MonkeyPatch], Ran]:
    """Sam rdzeń Uruchomienia procesu rzuca wyjątkiem, więc nie oddaje wyniku: ostatnia siatka adaptera bez rdzenia."""

    def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Ran:
        steered = centrum(tmp_path)

        def broken(*args: object, **kwargs: object) -> NoReturn:
            raise ValueError("synthetic core failure SYN-002")

        monkeypatch.setattr(runs, "run_process", broken)
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


ENDINGS = {
    "sukces-podglad": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=True),
        "podgląd",
        ("OK", "finished", None),
        [],
        files_unchanged=True,
    ),
    "sukces-zapis": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=False),
        "zapis",
        ("OK", "finished", None),
        [],
        files_unchanged=False,
    ),
    "sprawdzenie-podglad": Ending(
        lambda tmp_path, _: _settlement(tmp_path, dry_run=True, include_unmapped=True),
        "podgląd",
        ("WYMAGA_SPRAWDZENIA", "finished", None),
        [("warning", "BRAK_MAPOWANIA")],
        files_unchanged=True,
    ),
    "sprawdzenie-zapis": Ending(
        lambda tmp_path, _: _preparation(tmp_path, dry_run=False),
        "zapis",
        ("WYMAGA_SPRAWDZENIA", "finished", None),
        QUANTITY_WARNINGS,
        files_unchanged=False,
    ),
    "dla-taty-zapis": Ending(
        _existing_worker_settlements,
        "zapis",
        ("BLAD_KRYTYCZNY", "stop", "for_tata"),
        [("stop", "FOLDER_ROZLICZEN_ISTNIEJE")],
        files_unchanged=True,
    ),
    "dla-taty-podglad": Ending(
        _missing_collective_file,
        "podgląd",
        ("BLAD_KRYTYCZNY", "stop", "for_tata"),
        [("stop", "BRAK_PLIKU_ZBIORCZEGO")],
        files_unchanged=True,
    ),
    "decyzja-przerwij": Ending(
        _aborted_decision,
        "zapis",
        ("BLAD_KRYTYCZNY", "declined", "declined"),
        [("stop", "PRZERWANO_NIEPELNY_OKRES")],
        files_unchanged=True,
    ),
    "do-maksa-zapis": Ending(
        _broken_worker_config,
        "zapis",
        ("BLAD_KRYTYCZNY", "stop", "for_maks"),
        [("stop", "ZLA_KONFIGURACJA_WYKONAWCOW")],
        "rozliczenia.message.StopError",
        files_unchanged=True,
    ),
    "wyjatek-zapis": Ending(
        _failing(settling_centrum, dry_run=False, engine=True),
        "zapis",
        ("BLAD_KRYTYCZNY", "unexpected", "for_maks"),
        UNEXPECTED,
        "RuntimeError",
        files_unchanged=True,
    ),
    "wyjatek-podglad": Ending(
        _failing(preparing_centrum, dry_run=True, engine=True),
        "podgląd",
        ("BLAD_KRYTYCZNY", "unexpected", "for_maks"),
        UNEXPECTED,
        "RuntimeError",
        files_unchanged=True,
    ),
    "po-silniku-podglad": Ending(
        _failing(settling_centrum, dry_run=True, engine=False),
        "podgląd",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_PLANU")],
        "ValueError",
        files_unchanged=True,
    ),
    "po-silniku-zapis": Ending(
        _failing(preparing_centrum, dry_run=False, engine=False),
        "zapis",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_PODSUMOWANIA")],
        "ValueError",
        files_unchanged=False,
    ),
    "po-silniku-adapter": Ending(
        _adapter_net(preparing_centrum, dry_run=True),
        "podgląd",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_WYNIKU")],
        "ValueError",
        files_unchanged=True,
    ),
    "bez-rdzenia-zapis": Ending(
        _core_failed(settling_centrum, dry_run=False),
        "zapis",
        ("BLAD_KRYTYCZNY", "after_engine", "for_maks"),
        [("stop", "BLAD_WYNIKU")],
        "ValueError",
        files_unchanged=False,
    ),
}


@pytest.mark.parametrize("ending", ENDINGS.values(), ids=ENDINGS.keys())
def test_kazda_droga_zakonczenia_w_obu_trybach_daje_jeden_plik_logow_z_wynikiem_i_komunikatami_karty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: Ending
) -> None:
    centrum, view = ending.run(tmp_path, monkeypatch)

    [path] = log_files(centrum)
    [record] = records(centrum)
    card = view["result"]
    assert (record["run_id"], record["process"], record["period"]) == (view["run"]["id"], view["run"]["process"], PERIOD)
    assert record["mode"] == ending.mode
    assert (record["result"], record["ending"], record["stop_kind"]) == ending.result
    assert (card["result"], card["ending"], card["stop_kind"]) == ending.result
    assert card["files_unchanged"] is ending.files_unchanged
    assert [(message["kind"], message["code"]) for message in record["messages"]] == ending.messages
    assert three_parts(record) == card_messages(view)
    assert (record["trace"] or {}).get("exception_type") == ending.trace
    text = path.read_text(encoding="utf-8")
    assert [marker for marker in ("syntetyczny adres SYN-", "OR-SYN-") if marker in text] == [], "ADRES i numer Orange"
    assert in_json(tmp_path) not in text and in_json(tmp_path.resolve()) not in text


@pytest.mark.parametrize("ending", ENDINGS.values(), ids=ENDINGS.keys())
def test_po_ponownym_starcie_karta_ostatniego_uruchomienia_wraca_z_logow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ending: Ending
) -> None:
    centrum, live = ending.run(tmp_path, monkeypatch)
    [record] = records(centrum)

    centrum.restart()

    current = centrum.client.get("/api/runs/current").json()
    assert current == {"state": "idle", "previous": restored(live, record["started_at"])}
    assert first_view(centrum.client) == current
    assert in_json(tmp_path) not in json.dumps(current), "same nazwy plików, bez ścieżek"


def test_logi_maja_etapy_i_przetworzenia_szablonow_pracownika_z_wynikiem_wierszami_czasem_i_godzina(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)

    view = run_to_end(centrum, dry_run=False)

    [path] = log_files(centrum)
    [record] = records(centrum)
    assert record.keys() == KEYS
    assert (record["schema_version"], record["diagnosis"], record["trace"]) == (2, None, None)
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


def test_logi_przygotowania_nie_maja_liczby_ilosci_tylko_dla_inea(tmp_path: Path) -> None:
    centrum, _ = _preparation(tmp_path, dry_run=True)

    [record] = records(centrum)
    assert record["inea_only_cleared"] is None


def test_karta_wraca_z_logow_sprzed_liczby_ilosci_tylko_dla_inea(tmp_path: Path) -> None:
    centrum, live = _settlement(tmp_path, dry_run=False)
    [path] = log_files(centrum)
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["inea_only_cleared"]
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    centrum.restart()

    current = centrum.client.get("/api/runs/current").json()
    assert current == {"state": "idle", "previous": restored(live, record["started_at"])}


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
            "name": "Wzorzec rozliczenia pracownika.xlsx",
            "size": centrum.configuration.worker_template.stat().st_size,
            "online_only": False,
        },
        {"name": f"Rozliczenie wew. {PERIOD}.xlsx", "size": None, "online_only": None},
        {"name": SOURCE_NAME, "size": centrum.collective_file.stat().st_size, "online_only": True},
    ]


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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
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
    assert box.wait_until(lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 3)
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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")

    first = run_to_end(centrum, dry_run=True)
    second = run_to_end(centrum, dry_run=True)
    diagnosis = centrum.client.post(f"/api/runs/{second['run']['id']}/diagnosis")
    sent = centrum.client.post(f"/api/runs/{second['run']['id']}/report")

    assert [view["result"]["stop_kind"] for view in (first, second)] == ["for_tata", "repeated"]
    assert (diagnosis.status_code, sent.json()) == (200, {"state": "sent"})
    box = centrum.surroundings.report_box
    # Logi obu Uruchomień, a Diagnoza drugiego zmienia jego komentarz (#849), więc jego tekst to Logi po Diagnozie.
    assert box.wait_until(
        lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 2 and len(fake.edited) == 1
    )
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


def test_katalog_logow_bez_prawa_zapisu_daje_ten_sam_wynik_bez_komunikatu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    blocked = centrum.log_path.parent / "uruchomienia"
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
    queue = (tmp_path / "config" / "zgloszenia" / "kolejka").glob("*.json")
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


def _no_git(tmp_path: Path) -> Path | None:
    return None


def _uninstalled_git(tmp_path: Path) -> Path | None:
    return tmp_path / "odinstalowany" / "git"


def _git_failing_on_tags(tmp_path: Path) -> Path | None:
    return git_failing_on(tmp_path, "for-each-ref")


def _git_not_answering(tmp_path: Path) -> Path | None:
    """Git, który na każde polecenie milczy dłużej, niż Centrum czeka na Wydanie, a potem podaje tag Wydania."""

    script = tmp_path / "git_bez_odpowiedzi.py"
    script.write_text("import time\ntime.sleep(30)\nprint('v9.9.9')\n", encoding="utf-8")
    return git_command(tmp_path, script)


GITS = {
    "bez-gita": _no_git,
    "git-odinstalowany": _uninstalled_git,
    "blad-gita": _git_failing_on_tags,
    "git-bez-odpowiedzi": _git_not_answering,
}


@pytest.mark.parametrize("found_git", GITS.values(), ids=GITS.keys())
def test_bez_dzialajacego_gita_logi_maja_commit_narzedzia_bez_wydania(
    tmp_path: Path, found_git: Callable[[Path], Path | None]
) -> None:
    repository = tool_repository(tmp_path / "repozytoria")
    git = found_git(tmp_path)
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository, find_git=lambda: git))

    run_to_end(centrum, dry_run=True)

    [record] = records(centrum)
    assert record["tool"] == {"wydanie": None, "commit": repository.head()}


@pytest.mark.skipif(sys.platform == "win32", reason="program bez rozszerzenia z PATH uruchamia tylko POSIX")
def test_bez_gita_logi_niczego_nie_uruchamiaja_po_wydanie(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    programs = tmp_path / "programy"
    programs.mkdir()
    started = tmp_path / "uruchomiony"
    impostor = programs / "None"
    impostor.write_text(f"#!/bin/sh\ntouch '{started}'\necho v9.9.9\n", encoding="utf-8")
    impostor.chmod(0o755)
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
# Zlecenia sześciu Wykonawców (wiersze 18–23): jedno gotowe, dwa nieznane w efenix i trzy sprzeczne z Emmettem, więc
# każdy wynik ma inną liczbę zleceń.
PRICED = [
    Order("#ZLQX01", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}),
    Order("#ZLQX02", worker="beata.testowa", address="UL. PRYWATNA 7/1", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQX03", worker="celina.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 2}),
    Order("#ZLQX04", worker="dorota.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQX05", worker="ewa.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 3}),
    Order("#ZLQX06", worker="filip.testowy", cells={"O": 1}, amount=float(amount_of({"012": 1})), emmett={"012": 2}),
]
# Zlecenia z ``PRICED``, które zna Atrapa efenix: gotowe i sprzeczne z Emmettem.
IN_EFENIX = [PRICED[0].in_efenix("611"), PRICED[2].in_efenix("613"), PRICED[4].in_efenix("615"), PRICED[5].in_efenix("616")]


def test_okno_efenix_taty_pracuje_w_tempie_ludzkim_a_slad_wyceny_emmetta_trzyma_w_config_narzedzia() -> None:
    """Centrum taty daje Wycenie w efenix tempo ludzkie na prawdziwym zegarze i Ślad Wyceny Emmetta w ``config/``
    narzędzia, poza OneDrive i poza Gitem (ADR 0015). Testy i weryfikacja na Atrapie efenix mają okno bez tempa i z własnym
    folderem śladu, a okna taty nie otwierają, bo prowadzi do prawdziwego efenix (ADR 0024)."""

    window = EfenixWindow.of_tata()

    assert (window.pace, window.trace_directory.parent) == (Pace(sleep=time.sleep, clock=time.monotonic), TOOL_ROOT / "config")


def test_wycena_w_efenix_z_centrum_pracuje_w_tempie_ludzkim_okna_efenix(tmp_path: Path) -> None:
    """Centrum daje procesowi tempo swojego okna efenix: przerwę przed każdym zapisem w efenix. Na zegarze, który stoi,
    przerwa przed zapisem to ``ACTION_PAUSE_S``, a przed szukaniem zlecenia po zleceniu z zapisem próg podtrzymania sesji."""

    pauses: list[float] = []
    with atrapa_efenix(IN_EFENIX) as atrapa:
        pace = Pace(sleep=pauses.append, clock=lambda: 0.0)
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url, efenix_pace=pace))
        write_collective_file(centrum.period_parent, PRICED)
        assert _start_pricing(centrum).status_code == 200
        finished = finished_view(centrum.client)

    assert (finished["result"]["result"], pauses[0], set(pauses)) == ("WYMAGA_SPRAWDZENIA", ACTION_PAUSE_S, {ACTION_PAUSE_S, KEEPALIVE_S})


def _pricing_centrum(tmp_path: Path, atrapa: AtrapaEfenix, *arguments: str) -> SettlingCentrum:
    """Centrum, którego okno efenix to Chromium na Atrapie z argumentami ``arguments``; Folder okresu ma Plik zbiorczy
    z ``PRICED``."""

    centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url, efenix_arguments=arguments))
    write_collective_file(centrum.period_parent, PRICED)
    return centrum


def _start_pricing(centrum: SettlingCentrum, *, dry_run: bool = False) -> Any:
    return centrum.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "dry_run": dry_run})


def _view_where(centrum: SettlingCentrum, wanted: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    for event in run_events(centrum.client):
        view: dict[str, Any] = event["view"]
        if wanted(view):
            return view
    raise AssertionError("Strumień skończył się przed oczekiwanym widokiem.")


def test_wycena_w_efenix_z_centrum_czeka_na_logowanie_taty_jako_jedyne_uruchomienie_a_karta_i_powiadomienie_maja_wynik(
    tmp_path: Path,
) -> None:
    """Okres z Plikiem zbiorczym ma przycisk Wyceny w efenix bez Podglądu bez zapisu. W trakcie czekania na logowanie
    inne Uruchomienie nie startuje, a karta po wyniku ma błędy i ostrzeżenia Emmetta z numerem zlecenia i Wykonawcą
    oraz liczby pominiętych. Nowe Powiadomienie (kropka na dzwonku) ma tytuł wyniku, okres i liczby zleceń, a prowadzi
    do karty tego Uruchomienia z jego Logów. Ślad Wyceny Emmetta okresu trafia do folderu śladów okna efenix Centrum."""

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
    assert (tmp_path / "slad-wyceny-emmetta" / f"{PERIOD}.json").is_file()
    assert (notification["headline"], notification["period"], notification["orders"], notification["stopped"]) == (
        "Wycena w efenix gotowa · wymaga sprawdzenia",
        PERIOD,
        {"ready": 1, "settled": 0, "errors": 2, "warnings": 3},
        None,
    )
    assert (notification["run_id"], card["state"], card["result"]["headline"]) == (
        finished["run"]["id"],
        "restored",
        "Wycena w efenix gotowa · wymaga sprawdzenia",
    )
    assert (setup["title"], setup["preview_hint"], [period["token"] for period in setup["periods"]]) == ("Wycena w efenix", None, [PERIOD])
    assert (preview.status_code, busy.status_code, waiting["state"]) == (409, 409, "running")
    assert busy.json()["message"].startswith(f"Trwa już Uruchomienie procesu: Wycena w efenix, okres {PERIOD}.")
    assert (result["result"], result["headline"], result["next_action"]) == (
        "WYMAGA_SPRAWDZENIA",
        "Wycena w efenix gotowa · wymaga sprawdzenia",
        "open_collective_file",
    )
    assert {figure["label"]: figure["value"] for figure in result["summary"]["figures"]} == {
        "Zlecenia w zakresie": 6,
        "Gotowe do przekazania": 1,
        "Rozliczone": 0,
        "Błędy zleceń": 2,
        "Ostrzeżenia Emmetta": 3,
    }
    assert {count["label"]: count["count"] for count in result["summary"]["counts"]["counts"]} == {
        "Ze zdjęciami": 0,
        "Usterki": 0,
        "Nieznalezione w efenix": 2,
    }
    notes = result["order_notes"]
    assert [(note["row"], note["order"], note["worker"]) for note in notes["errors"]] == [
        (19, "ZLQX02", "beata.testowa"),
        (21, "ZLQX04", "dorota.testowa"),
    ]
    assert [(note["row"], note["order"], note["worker"]) for note in notes["warnings"]] == [
        (20, "ZLQX03", "celina.testowa"),
        (22, "ZLQX05", "ewa.testowa"),
        (23, "ZLQX06", "filip.testowy"),
    ]
    assert notes["errors"][0]["what"].startswith("efenix nie zna zlecenia o numerze z NUMER ZL.")
    assert notes["warnings"][0]["what"].startswith("Wycena Emmetta ma inne ilości niż Plik zbiorczy")
    assert notes["settled"] == []


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
    notes = result["order_notes"]
    assert (notes["errors"], [(note["row"], note["order"], note["worker"]) for note in notes["settled"]]) == (
        [],
        [(19, "ZLQR02", "beata.testowa")],
    )
    traced = [(order["row"], order["outcome"], order["code"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]]
    assert traced == [(18, "gotowe", None, ["szukanie", "otwarcie zlecenia"]), (19, "rozliczone", None, ["szukanie"])]
    assert notification["orders"] == {"ready": 1, "settled": 1, "errors": 0, "warnings": 0}


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
    następne Uruchomienie."""

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


# Zatrzymanie okna efenix przy wierszu 19, gdy wiersz 18 jest już gotowy (Zgłoszenia #19 i #20 z
# MAXIMISEART-Dad-zgloszenia): zlecenie Atrapy w wierszu 19 i przyczyna, którą Logi mają podać. Hipotezy B–E z tabeli
# decyzji (``tests/test_tabela_zatrzyman_efenix.py``); hipoteza A od #819 nie jest Zatrzymaniem.
STOPPED_AT_SECOND = [PRICED[0], Order("#ZLQX07", worker="gosia.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})))]
HYPOTHESES = {
    "B-ilosc-niecalkowita": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), changed=Changed.QUANTITY_VALUE),
        {"what": "wartość pola Ilość, która nie jest liczbą całkowitą", "positions": ["012"]},
        ["szukanie"],
        "otwarcie zlecenia",
    ),
    "C-data-w-innej-postaci": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), changed=Changed.DATE_FORMAT, execution_date=DAY),
        {"what": "data wykonania w innej postaci niż RRRR-MM-DD"},
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


def test_logi_zatrzymania_po_nieudanym_zapisie_sladu_wyceny_emmetta_maja_pozycje_slad_zlecen_i_blad_zapisu_pliku(
    tmp_path: Path,
) -> None:
    """Pliku Śladu Wyceny Emmetta nie da się zastąpić (w jego miejscu jest folder), więc zapis ilości z wyprzedzeniem w
    zleceniu z wiersza 19 się nie udaje, a Wycena staje „do Maksa” (#881). Logi Uruchomienia mają to, co przy Zatrzymaniu
    okna: przyczynę z kodem pozycji, wiersz, miejsce „2 z 2”, udane działania okna przy tym zleceniu bez działania, które
    się nie udało (okno ilości nie wpisało), ślad gotowego zlecenia z wiersza 18, a w śladzie wywołań błąd zapisu pliku
    śladu w ``_replace``."""

    with atrapa_efenix([PRICED[0].in_efenix("611"), STOPPED_AT_SECOND[1].in_efenix("617")]) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        (tmp_path / "slad-wyceny-emmetta" / f"{PERIOD}.json").mkdir(parents=True)
        write_collective_file(centrum.period_parent, STOPPED_AT_SECOND)
        assert _start_pricing(centrum).status_code == 200
        assert finished_view(centrum.client)["result"]["result"] == "BLAD_KRYTYCZNY"
    [record] = records(centrum)
    stop, trace = record["efenix_stop"], record["trace"]

    assert ([(message["kind"], message["code"]) for message in record["messages"]], record["stop_kind"]) == (
        [("stop", "EFENIX_SLAD_NIEZAPISANY")],
        "for_maks",
    )
    assert {key: value for key, value in stop["cause"].items() if value is not None} == {
        "what": "Ślad Wyceny Emmetta nie zapisał ilości z wyprzedzeniem, więc okno jej nie wpisało",
        "positions": ["012"],
    }
    assert (stop["row"], stop["order"], stop["orders"], stop["failed"]) == (19, 2, 2, None)
    assert [step["action"] for step in stop["steps"]] == [
        "szukanie",
        "otwarcie zlecenia",
        "data wykonania",
        "otwarcie zlecenia",
        "Wycena Emmetta",
    ]
    assert [(order["row"], order["outcome"]) for order in record["efenix_orders"]] == [(18, "gotowe")]
    assert [trace["exception_type"], *(cause["exception_type"] for cause in trace["causes"])][:2] == [
        "rozliczenia.message.StopError",
        "rozliczenia.efenix_pricing._TraceNotSaved",
    ]
    assert [frame["function"] for frame in trace["causes"][-1]["frames"]][-1:] == ["_replace"]


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
        "rozliczenia.efenix_pricing.UnexpectedPage",
    ]
    text = log_files(centrum)[0].read_text(encoding="utf-8")
    traced_text = json.dumps(record["efenix_orders"], ensure_ascii=False)
    assert [order.number for order in STOPPED_AT_SECOND if order.number.removeprefix("#") in traced_text] == []
    assert [marker for marker in ("TESTOWA", "Testowa") if marker in text] == [], "ADRES"


def test_logi_wyceny_w_efenix_maja_slad_kazdego_zlecenia_bez_numeru_zlecenia_i_bez_adresu(tmp_path: Path) -> None:
    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        assert _start_pricing(centrum).status_code == 200
        assert finished_view(centrum.client)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 1)
    [record] = records(centrum)
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    texts += in_box(box)

    traced = [(order["row"], order["outcome"], order["code"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]]
    emmett_steps = ["szukanie", "otwarcie zlecenia", "data wykonania", "otwarcie zlecenia", "Wycena Emmetta"]
    assert traced == [
        (18, "gotowe", None, ["szukanie", "otwarcie zlecenia"]),
        (19, "błąd", "EFENIX_NIEZNANY_NUMER", ["szukanie"]),
        (20, "ostrzeżenie Emmetta", "EFENIX_SPRZECZNOSC_Z_EMMETTEM", emmett_steps),
        (21, "błąd", "EFENIX_NIEZNANY_NUMER", ["szukanie"]),
        (22, "ostrzeżenie Emmetta", "EFENIX_SPRZECZNOSC_Z_EMMETTEM", emmett_steps),
        (23, "ostrzeżenie Emmetta", "EFENIX_SPRZECZNOSC_Z_EMMETTEM", emmett_steps),
    ]
    emmett = record["efenix_orders"][2]
    assert (emmett["file"], emmett["steps"][-1]["quantities"]["012"], emmett["steps"][0]["found"]) == ({"012": 1}, 2, 1)
    moments = [utc(step["started_at"]) for order in record["efenix_orders"] for step in order["steps"]]
    assert utc(record["started_at"]) <= moments[0]
    assert moments == sorted(moments) and moments[-1] <= utc(record["ended_at"]), "godziny działań w kolejności zleceń"
    traced_text = json.dumps(record["efenix_orders"], ensure_ascii=False)
    assert [order.number for order in PRICED if order.number.removeprefix("#") in traced_text] == [], "ślad bez numeru"
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
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        assert _start_pricing(centrum).status_code == 200
        assert finished_view(centrum.client)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 1)
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
    numbers = [*(order.number.removeprefix("#") for order in READ), "ZLQS050"]
    assert [number for number in numbers if number in traced_text] == []
    private = [_FILE_ADDRESS, "ZAWILCOWA", "Zawilcowa", "Rumiankowa", "Miastowo"]
    assert [marker for marker in private if any(marker in text for text in texts + in_box(box))] == []
    assert record["technical_notes"] == []


def test_uwaga_taty_po_wycenie_w_efenix_nie_wynosi_adresu_z_pliku_zbiorczego_ani_danych_adresowych_efenix(
    tmp_path: Path,
) -> None:
    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
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
    [path] = (centrum.log_path.parent / "uruchomienia").glob(f"*-{run_id}.json")
    text = path.read_text(encoding="utf-8")
    return text, json.loads(text)


def dad_actions(record: dict[str, Any]) -> list[tuple[str, ...]]:
    """Działania bez godzin: rodzaj, a przy widoku strona i rodzaj widoku, przy przycisku operacja, proces i tryb."""

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


def logs_file(fake: FakeReportBox, comment: str) -> bytes:
    """Pełne Logi z pliku w Archiwum Logów okresu, do którego prowadzi komentarz Logów, rozpakowane bajt w bajt."""

    found = ARCHIVE_LINK.search(comment)
    assert found is not None, comment
    return fake.archived(found["tag"])[found["name"]]


def logs_text(fake: FakeReportBox, comment: str) -> str:
    """Pełne Logi z pliku w Archiwum Logów okresu, do którego prowadzi komentarz Logów (``logs_file``), jako tekst."""

    return logs_file(fake, comment).decode("utf-8")


def in_box(fake: FakeReportBox) -> list[str]:
    """Wszystko, co Maks dostaje w Skrzynce: tytuły, treści i komentarze issue oraz rozpakowane pliki w Archiwach."""

    issues = [part for issue in fake.background_issues for part in (issue.title, issue.body, *issue.comments)]
    return issues + [asset.text for archive in fake.archives for asset in archive.assets]


def test_dzialania_taty_miedzy_dwoma_uruchomieniami_sa_w_logach_drugiego_z_godzinami_bez_tresci_uwagi_taty(
    tmp_path: Path,
) -> None:
    centrum = settling_centrum(tmp_path)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
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
        ("przycisk", "startRun", "settlement", "podgląd"),
    ]
    assert dad_actions(later) == [
        ("widok", "okresy", "navigation"),
        ("przycisk", "changeTheme"),
        ("przycisk", "sendDadNote"),
        ("przycisk", "closeCentrum"),
        ("start Centrum",),
        ("widok", "uruchomienia", "cold_start"),
        ("przycisk", "startRun", "settlement", "zapis"),
    ]
    assert later["dad_actions"]["omitted"] == 0
    times = action_moments(later)
    assert all(moment.utcoffset() == timedelta(0) for moment in times), "godziny w UTC"
    assert times == sorted(times)
    assert datetime.fromisoformat(earlier["ended_at"]) <= times[0]
    assert times[-1] <= datetime.fromisoformat(later["started_at"])
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: len(logs_comments(fake)) == 2), "Logi obu Uruchomień w Skrzynce"
    sent = logs_text(box, logs_comments(box)[1])
    assert '"operation": "sendDadNote"' in sent, "dziennik działań taty dociera do Maksa"
    assert [marker for marker in ("SYNTETYCZNY-TYTUŁ", "SYNTETYCZNA-TREŚĆ") if marker in text or marker in sent] == []


def test_logi_maja_najnowsze_dzialania_taty_do_limitu_a_liczbe_starszych_obok(tmp_path: Path) -> None:
    """Tata długo przegląda Centrum przed Uruchomieniem: Logi mają ``MAX_ENTRIES`` najnowszych działań, ze startem tego
    Uruchomienia na końcu, a start Centrum, wybór folderu okresów i najstarszy widok liczy ``omitted``."""

    centrum = settling_centrum(tmp_path)
    for _ in range(MAX_ENTRIES):
        assert centrum.client.post("/api/view-timings", json=view_timing(kind="navigation", page="okresy")).status_code == 204
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]

    _, record = logged_record(centrum, run_id)
    assert dad_actions(record) == [
        *[("widok", "okresy", "navigation")] * (MAX_ENTRIES - 1),
        ("przycisk", "startRun", "settlement", "podgląd"),
    ]
    assert record["dad_actions"]["omitted"] == 3


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
    go usunie (``PricingJournal.run_ended``): test, który udaje zgaśnięcie Centrum przed wynikiem, odkłada go na dysk."""

    kept: dict[Path, str] = {}
    ended = PricingJournal.run_ended

    def keeping(journal: PricingJournal, run: runs.EndedRun) -> None:
        kept.update({path: path.read_text(encoding="utf-8") for path in directory.glob("*.jsonl")})
        ended(journal, run)

    monkeypatch.setattr(PricingJournal, "run_ended", keeping)
    return kept


def logs_json(fake: FakeReportBox, comment: str) -> dict[str, Any]:
    """Logi JSON z pliku w Archiwum Logów okresu, do którego prowadzi komentarz Logów."""

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
    ma karty wiersza Historii ani Powiadomienia o zakończonej Wycenie."""

    with atrapa_efenix(CUT_IN_EFENIX) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, CUT)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        before, _ = atrapa.state()
        with centrum_process(tmp_path, atrapa.url) as process:
            status, started = process.post("/api/runs", {"process": "efenix", "period": PERIOD, "dry_run": False})
            stalled = wait_for(lambda: atrapa.state()[0][3].execution_date is not None, 120)
            process.kill()
        after, _ = atrapa.state()
    [journal] = journals(centrum)
    with journal.open("a", encoding="utf-8") as torn:
        torn.write(TORN)
    entries, journal_text = journal_entries(journal), journal.read_text(encoding="utf-8")
    centrum.restart()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    box = centrum.surroundings.report_box
    sent = box.wait_until(lambda fake: len(logs_comments(fake)) == 1)
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
        (20, "ostrzeżenie Emmetta", "EFENIX_SPRZECZNOSC_Z_EMMETTEM", ["szukanie", "otwarcie zlecenia", "data wykonania", "otwarcie zlecenia", "Wycena Emmetta"]),
    ]
    assert record["interruption"] == {"row": 21, "place": 4, "total": 5, "omitted": 1}
    assert dad_actions(record) == [
        ("start Centrum",),
        ("przycisk", "choosePeriodsDirectory"),
        ("start Centrum",),
        ("przycisk", "startRun", "efenix", "zapis"),
    ], "działania taty sprzed zgaśnięcia, bez startu Centrum po nim"
    assert utc(record["started_at"]) <= utc(record["ended_at"]) == utc(entries[-1]["at"])
    assert (logs_json(box, comment), "- Wynik: brak, Centrum zamknęło się w trakcie (Urwane Uruchomienie)" in comment) == (record, True)
    assert (previous["state"], previous["run"]["id"], previous["orders"]["title"]) == ("interrupted", run_id, "Zlecenia przed zamknięciem Centrum")
    assert {count["label"]: count["count"] for count in previous["orders"]["counts"]} == {
        "Gotowe do przekazania": 2,
        "Rozliczone": 0,
        "Błędy zleceń": 0,
        "Ostrzeżenia Emmetta": 1,
    }
    assert (card, [item for item in notifications if item["kind"] == "wycena_w_efenix"]) == ({"state": "missing"}, [])
    assert journals(centrum) == [], "dziennik, którego Logi przyjęła Kolejka wysyłki, znika"
    private = [*(order.number.removeprefix("#") for order in CUT), "TESTOWA", "Testowa", "Miasto-Dzielnica"]
    assert [marker for marker in private if marker in journal_text or marker in comment] == []


@pytest.mark.parametrize(
    "lost",
    [None, "historia", "logi", "nieczytelne-logi"],
    ids=["logi-i-historia", "bez-historii", "bez-logow", "nieczytelne-logi"],
)
def test_wycena_w_efenix_ktora_doszla_do_konca_nie_zostawia_dziennika_ktory_start_uznalby_za_urwany(
    tmp_path: Path, lost: str | None
) -> None:
    """Wycena w efenix doszła do wyniku, a Kolejka wysyłki przyjęła jej Logi, więc jej dziennik znika już na jej końcu.
    Następny start Centrum nie ma czego zamykać, także gdy potem zniknęły jej Logi albo jej wiersz Historii, albo gdy jej
    Logi są, ale urwane w połowie: karta po starcie ma wynik, a Skrzynka nie dostaje drugich Logów."""

    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        assert _start_pricing(centrum).status_code == 200
        run_id = finished_view(centrum.client)["run"]["id"]
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: len(logs_comments(fake)) == 1)
    centrum.client.stop()
    assert journals(centrum) == [], "dziennik Wyceny, której Logi przyjęła kolejka, po jej końcu"
    [logs] = log_files(centrum)
    if lost == "historia":
        centrum.engines.metrics.efenix.unlink()
    elif lost == "logi":
        logs.unlink()
    elif lost == "nieczytelne-logi":
        logs.write_text(logs.read_text(encoding="utf-8")[:100], encoding="utf-8")

    centrum.restart()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    centrum.client.stop()

    # Karta nieczytelnych Logów: wynik był, tylko go nie znamy (``RunCards.last``).
    expected = {"logi": ("recorded", run_id), "nieczytelne-logi": None}.get(str(lost), ("restored", run_id))
    card = None if previous is None else (previous["state"], previous["run"]["id"])
    assert (card, len(logs_comments(box))) == (expected, 1)
    assert (log_files(centrum), journals(centrum)) == ([] if lost == "logi" else [logs], [])


def test_wycena_w_efenix_ktorej_logow_kolejka_wysylki_nie_przyjela_zostawia_dziennik_a_start_wysyla_te_logi(
    tmp_path: Path,
) -> None:
    """Na miejscu folderu Kolejki wysyłki stoi plik, więc kolejka nie przyjmuje ani postępu, ani Logów z wynikiem Wyceny w
    efenix. Dziennik zostaje po jej końcu obok pliku Logów, bo wersja końcowa jej komentarza Uruchomienia nie jest w drodze
    do Skrzynki. Start po naprawie folderu wysyła te Logi z pliku: Skrzynka ma jeden komentarz z ich podsumowaniem, a
    dziennik znika."""

    queue = tmp_path / "config" / "zgloszenia" / "kolejka"
    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        queue.parent.mkdir(parents=True, exist_ok=True)
        queue.write_text("", encoding="utf-8")  # plik zamiast folderu: zapis się nie uda
        assert _start_pricing(centrum).status_code == 200
        run_id = finished_view(centrum.client)["run"]["id"]
    centrum.client.stop()
    kept = (len(journals(centrum)), len(log_files(centrum)))
    queue.unlink()

    centrum.restart()
    assert centrum.client.get("/api/runs/current").status_code == 200
    box = centrum.surroundings.report_box
    sent = box.wait_until(lambda fake: len(logs_comments(fake)) == 1)
    centrum.client.stop()

    assert (kept, sent, journals(centrum)) == ((1, 1), True, [])
    [comment] = logs_comments(box)
    assert (logs_json(box, comment)["run_id"], logs_json(box, comment)["ending"]) == (run_id, "finished")


def _pricing_cut_before_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SettlingCentrum, str, Path]:
    """Wycena w efenix przeszła wszystkie zlecenia, ale Centrum zgasło przed jej wynikiem: dziennik ma każde zlecenie, a
    nie ma Logów, wiersza Historii ani wysyłki w kolejce, czyli to Urwane Uruchomienie (ADR 0017). Skrzynka Zgłoszeń ma
    klucz dopiero od następnego startu, więc nic z tej Wyceny do niej nie poszło. Zwraca też folder kolejki wysyłki."""

    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        kept = journals_at_result(monkeypatch, centrum.log_path.parent / "dzienniki-wyceny")
        assert _start_pricing(centrum).status_code == 200
        run_id = finished_view(centrum.client)["run"]["id"]
    centrum.client.stop()
    [logs] = log_files(centrum)
    logs.unlink()
    centrum.engines.metrics.efenix.unlink()
    queue = tmp_path / "config" / "zgloszenia" / "kolejka"
    shutil.rmtree(queue)
    for path, text in kept.items():
        path.write_text(text, encoding="utf-8")
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    return centrum, run_id, queue


def test_logi_urwanego_uruchomienia_po_ponownym_zgasnieciu_centrum_przed_wysylka_ida_przy_nastepnym_starcie_raz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Start Centrum zamyka dziennik jako Logi Urwanego Uruchomienia, ale Centrum gaśnie znowu przed pierwszym zapytaniem,
    więc przed wysyłką: dziennik zostaje obok pliku Logów. Następny start wysyła te Logi do Skrzynki raz, karta ma Urwane
    Uruchomienie, a dziennik znika."""

    centrum, run_id, _ = _pricing_cut_before_result(tmp_path, monkeypatch)
    box = centrum.surroundings.report_box
    centrum.restart()
    centrum.client.stop()
    closed = ([(record["run_id"], record["ending"]) for record in records(centrum)], len(journals(centrum)), len(logs_comments(box)))

    centrum.restart()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    sent = box.wait_until(lambda fake: len(logs_comments(fake)) == 1)
    centrum.client.stop()

    assert closed == ([(run_id, "interrupted")], 1, 0)
    assert (sent, [(logs["run_id"], logs["ending"]) for logs in (logs_json(box, comment) for comment in logs_comments(box))]) == (True, [(run_id, "interrupted")])
    assert ((previous["state"], previous["run"]["id"]), journals(centrum)) == (("interrupted", run_id), [])


def test_dziennik_urwanej_wyceny_ktorego_logow_kolejka_wysylki_nie_przyjela_zostaje_do_nastepnego_startu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kolejka wysyłki nie przyjmuje Logów Urwanego Uruchomienia (na miejscu jej folderu stoi plik): dziennik zostaje, a
    start po naprawie folderu wysyła te Logi do Skrzynki i dopiero wtedy dziennik znika."""

    centrum, run_id, queue = _pricing_cut_before_result(tmp_path, monkeypatch)
    box = centrum.surroundings.report_box
    queue.write_text("", encoding="utf-8")  # plik zamiast folderu: zapis się nie uda
    centrum.restart()
    assert centrum.client.get("/api/runs/current").status_code == 200
    centrum.client.stop()
    kept = (len(journals(centrum)), len(logs_comments(box)))

    queue.unlink()
    centrum.restart()
    assert centrum.client.get("/api/runs/current").status_code == 200
    sent = box.wait_until(lambda fake: len(logs_comments(fake)) == 1)
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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    started = JournalStarted(
        entry="start Uruchomienia",
        run_id="b" * 32,
        process="efenix",
        mode="zapis",
        period=PERIOD,
        started_at=utc("2026-09-16T10:15:00+00:00"),
    )
    step = LoggedStep(
        action="otwarcie zlecenia",
        duration_ms=120,
        found=None,
        execution_date=None,
        amount=None,
        quantities={STREET: 1, f"tel. {PHONE}": 2},
        position=None,
        quantity=None,
        accepted=None,
    )
    order = LoggedOrder(row=18, outcome="gotowe", code=None, file={}, file_amount=Decimal(0), steps=[step])
    ended = OrderEnded(at=utc("2026-09-16T10:16:00+00:00"), entry="zlecenie skończone", order=order)
    directory = centrum.log_path.parent / "dzienniki-wyceny"
    directory.mkdir(parents=True)
    journal = directory / Path(logs_file_name(started.started_at, "efenix", started.run_id)).with_suffix(".jsonl")
    journal.write_text(f"{started.model_dump_json()}\n{ended.model_dump_json()}\n", encoding="utf-8")
    if unsent:
        logs = centrum.log_path.parent / "uruchomienia" / logs_file_name(started.started_at, "efenix", started.run_id)
        logs.parent.mkdir(parents=True)
        written = RunLog.interrupted(
            started,
            ended_at=ended.at,
            orders=[order],
            interruption=LoggedInterruption(row=None, place=None, total=None, omitted=0),
            tool=Tool(wydanie=None, commit=TOOL_COMMIT),
            environment=Environment(system="Windows-11", python="3.12.7", files=None),
            dad_actions=DadActions(entries=[], omitted=0),
        )
        logs.write_text(written.text, encoding="utf-8")

    centrum.restart()
    centrum.client.get("/api/runs/current")
    box = centrum.surroundings.report_box
    sent = box.wait_until(lambda fake: len(logs_comments(fake)) == 1)
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
    minutes = EfenixMinutes(surroundings, tmp_path / "config" / "zgloszenia" / "kolejka", offline_until)
    with atrapa_efenix(IN_EFENIX, clock=minutes) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, PRICED)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
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
    assert wait_for(lambda: queued_logs(centrum.tmp_path / "config" / "zgloszenia" / "kolejka") == [])
    [issue] = box.issues_with(PROGRESS_LABEL)
    assert len(issue.comment_ids) == count, issue.comments
    return [(comment_id, [shown(text) for written, text in box.written if written == comment_id]) for comment_id in issue.comment_ids]


def comment_history(centrum: SettlingCentrum) -> tuple[int, list[str]]:
    """Jedyny komentarz issue Logów okresu (``comment_histories``)."""

    [history] = comment_histories(centrum, 1)
    return history


def minutes_of(texts: list[str]) -> list[int]:
    return [int(found["minutes"]) for text in texts if (found := MINUTES.search(text))]


def done_of(text: str) -> int | None:
    """Zlecenia skończone w postępie; ``None``: dziennik nie ma jeszcze żadnego zlecenia."""

    found = DONE.search(text)
    return None if found is None else int(found["done"])


def archived_logs(centrum: SettlingCentrum, comment: str) -> dict[str, Any]:
    """Pełne Logi z pliku w Archiwum Logów okresu, do którego prowadzi odnośnik podsumowania."""

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
    assert wait_for(lambda: queued_logs(centrum.tmp_path / "config" / "zgloszenia" / "kolejka") == [])
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


def test_wycena_ktorej_dziennika_nie_da_sie_zapisac_nie_ma_postepu_tylko_podsumowanie(tmp_path: Path) -> None:
    """Katalog dzienników Wyceny zajęty przez plik: Wycena biegnie do wyniku, ale ani jej start, ani żaden wpis nie trafia
    na dysk. Postęp nie wyprzedza dziennika, więc Skrzynka nie dostaje żadnego: komentarz, który powstałby bez dziennika,
    zostałby po zgaśnięciu Centrum na zawsze postępem, bo start Centrum nie miałby czego zamknąć jako Logi Urwanego
    Uruchomienia. Komentarz Uruchomienia powstaje od razu z podsumowaniem."""

    blocked = tmp_path / "logs" / "dzienniki-wyceny"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    with pricing(tmp_path) as (centrum, _, _):
        assert _start_pricing(centrum).status_code == 200
        finished_view(centrum.client)
    _, texts = comment_history(centrum)
    [summary] = texts

    assert len(archived_logs(centrum, summary)["efenix_orders"]) == 6


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
    komentarz Uruchomienia dostaje postęp ze zleceniami i na końcu podsumowanie."""

    blocked = tmp_path / "logs" / "dzienniki-wyceny"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    kept = journals_at_result(monkeypatch, blocked)
    with pricing(tmp_path, logged_in=False) as (centrum, _, atrapa):
        assert _start_pricing(centrum).status_code == 200
        blocked.unlink()
        atrapa.log_in()
        finished_view(centrum.client)
    _, texts = comment_history(centrum)
    centrum.client.stop()
    *progress, summary = texts
    [journal] = kept.values()
    entries = [entry["entry"] for entry in journal_entries_of(journal)]

    assert (entries[:2], entries.count("zlecenie skończone")) == (["start Uruchomienia", "zaczynam zlecenie"], 6)
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
    with atrapa_efenix(IN_EFENIX) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, PRICED)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
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
    [logs] = (tmp_path / "logs" / "uruchomienia").glob("*.json")
    logs.unlink()
    centrum.engines.metrics.efenix.unlink()
    shutil.rmtree(tmp_path / "config" / "zgloszenia" / "kolejka")
    for path, text in kept.items():
        path.write_text(text, encoding="utf-8")
    box.search_failure = None

    centrum.restart()
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

    queue = tmp_path / "config" / "zgloszenia" / "kolejka"
    surroundings = Surroundings()
    surroundings.report_box.background = frozenset()
    with atrapa_efenix(IN_EFENIX) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, PRICED)
        atrapa.expire_session()
        with centrum_process(tmp_path, atrapa.url) as process:
            status, started = process.post("/api/runs", {"process": "efenix", "period": PERIOD, "dry_run": False})
            queued = wait_for(lambda: len(queued_logs(queue)) == 1, 60)
            process.kill()
    on_disk = [entry["entry"] for journal in journals(centrum) for entry in journal_entries(journal)]
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
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
    assert wait_for(lambda: queued_logs(centrum.tmp_path / "config" / "zgloszenia" / "kolejka") == [])
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


# --- Wersja końcowa komentarza Uruchomienia po starcie Centrum (#846, tabela stanów startu) ------------------------------
# Komentarz postępu Wyceny w efenix powstaje dopiero, gdy jej dziennik ma na dysku pierwszą linię, a dziennik znika
# dopiero, gdy Kolejka wysyłki przyjęła wersję końcową tego komentarza. Start Centrum, który zastaje dziennik, bierze ją z
# tego, co jest na dysku taty: plik Logów, z wynikiem albo Urwanego Uruchomienia, idzie taki, jaki jest; bez pliku Logów,
# a z wierszem Historii, i przy pliku Logów, którego nie da się odczytać, idzie wynik bez Logów; bez pliku Logów i bez
# wiersza Historii Logi Urwanego Uruchomienia z dziennika. Dziennik bez zleceń albo ze zleceniami, Logi, które czekają w
# kolejce, i postęp, który Maks już widzi, zmieniają tylko treść wersji końcowej albo jej drogę przez kolejkę.

StartJournal = Literal["bez zleceń", "ze zleceniami"]
StartLogs = Literal["z wynikiem", "urwane", "brak", "nieczytelne"]
StartProgress = Literal["w Skrzynce", "w kolejce", "nigdzie"]
LOGS_WITH_RESULT: Final = "Logi z wynikiem"
INTERRUPTED_LOGS: Final = "Logi Urwanego Uruchomienia"
RESULT_FROM_HISTORY: Final = "- Wynik: WYMAGA_SPRAWDZENIA, z Historii"
UNKNOWN_RESULT: Final = "- Wynik: nieznany, Historia nie ma tego Uruchomienia"
LOGS_NOT_WRITTEN: Final = "- Pełne Logi: nie ma, Centrum nie zapisało ich po wyniku (np. zamknęło się tuż po nim)"
LOGS_UNREADABLE: Final = "- Pełne Logi: plik Logów na komputerze taty jest, ale nie da się go odczytać"
# Wersja końcowa po starcie z pliku Logów i wiersza Historii: Logi (ich ``ending`` w Archiwum) albo linie wyniku i Logów
# wyniku bez Logów.
FINAL_AFTER_START: Final[dict[tuple[StartLogs, bool], str | tuple[str, str]]] = {
    ("z wynikiem", True): LOGS_WITH_RESULT,
    ("z wynikiem", False): LOGS_WITH_RESULT,
    ("urwane", True): INTERRUPTED_LOGS,
    ("urwane", False): INTERRUPTED_LOGS,
    ("brak", True): (RESULT_FROM_HISTORY, LOGS_NOT_WRITTEN),
    ("brak", False): INTERRUPTED_LOGS,
    ("nieczytelne", True): (RESULT_FROM_HISTORY, LOGS_UNREADABLE),
    ("nieczytelne", False): (UNKNOWN_RESULT, LOGS_UNREADABLE),
}
SWEPT_RUN: Final = "c" * 32
SWEPT_START = utc("2026-09-16T10:15:00+00:00")
SWEPT_ORDERS = [
    LoggedOrder(row=18, outcome="gotowe", code=None, file={}, file_amount=Decimal(0), steps=[]),
    LoggedOrder(
        row=19, outcome="ostrzeżenie Emmetta", code="EFENIX_SPRZECZNOSC_Z_EMMETTEM", file={}, file_amount=Decimal(0), steps=[]
    ),
]
# Linie zleceń wyniku bez Logów: dwa zlecenia skończone z trzech i trzecie zaczęte bez wyniku, albo dziennik bez zleceń.
SWEPT_ORDER_LINES: Final[dict[StartJournal, list[str]]] = {
    "bez zleceń": ["- Zlecenia: dziennik Wyceny nie ma żadnego zlecenia"],
    "ze zleceniami": ["- Zlecenia: 2 z 3 skończone (gotowe 1, ostrzeżenie Emmetta 1)", "- Zlecenie bez wyniku: wiersz 20"],
}


def _swept_journal(directory: Path, started: JournalStarted, journal: StartJournal) -> None:
    """Dziennik Wyceny ``started`` w katalogu dzienników: sama pierwsza linia albo dwa zlecenia skończone i trzecie
    zaczęte bez wyniku."""

    lines: list[JournalStarted | OrderBegun | OrderEnded] = [started]
    if journal == "ze zleceniami":
        at = started.started_at
        for place, order in enumerate(SWEPT_ORDERS, start=1):
            lines.append(OrderBegun(at=at, entry="zaczynam zlecenie", row=order.row, place=place, total=3))
            lines.append(OrderEnded(at=at, entry="zlecenie skończone", order=order))
        lines.append(OrderBegun(at=at, entry="zaczynam zlecenie", row=20, place=3, total=3))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / Path(logs_file_name(started.started_at, "efenix", started.run_id)).with_suffix(".jsonl")
    path.write_text("".join(line.model_dump_json() + "\n" for line in lines), encoding="utf-8")


def _swept_logs(started: JournalStarted, journal: StartJournal, *, ending: Literal["finished", "interrupted"]) -> RunLog:
    """Logi Wyceny ``started``: z wynikiem, jak po ``_keep``, albo Urwanego Uruchomienia, jak po poprzednim starcie."""

    orders = SWEPT_ORDERS if journal == "ze zleceniami" else []
    interrupted = RunLog.interrupted(
        started,
        ended_at=started.started_at + timedelta(minutes=1),
        orders=orders,
        interruption=LoggedInterruption(row=20 if orders else None, place=3 if orders else None, total=3 if orders else None, omitted=0),
        tool=Tool(wydanie=None, commit=TOOL_COMMIT),
        environment=Environment(system="Windows-11", python="3.12.7", files=None),
        dad_actions=DadActions(entries=[], omitted=0),
    )
    if ending == "interrupted":
        return interrupted
    return interrupted.model_copy(
        update={"ending": "finished", "result": "WYMAGA_SPRAWDZENIA", "duration_ms": 60_000, "interruption": None}
    )


def _queued(queue: Path, moment: str, text: str) -> None:
    """Plik Kolejki wysyłki Logów Uruchomienia ``SWEPT_RUN`` z chwilą ``moment`` w nazwie (porządek wersji)."""

    queue.mkdir(parents=True, exist_ok=True)
    (queue / f"{moment}-0001-{PROGRESS_LABEL}-{SWEPT_RUN[:8]}.json").write_text(text, encoding="utf-8")


def _yes(value: bool) -> str:
    return "tak" if value else "nie"


START_STATES = [
    pytest.param(
        journal,
        logs,
        history,
        queued,
        progress,
        id=f"dziennik-{journal}-logi-{logs}-historia-{_yes(history)}-kolejka-{_yes(queued)}-postep-{progress}".replace(" ", "-"),
    )
    for journal, logs, history, queued, progress in itertools.product(
        get_args(StartJournal), get_args(StartLogs), [True, False], [True, False], get_args(StartProgress)
    )
]


@pytest.mark.parametrize(("journal", "logs", "history", "queued", "progress"), START_STATES)
def test_kazda_wycena_w_efenix_z_dziennikiem_ma_po_starcie_centrum_w_skrzynce_wersje_koncowa_komentarza_uruchomienia(
    tmp_path: Path, journal: StartJournal, logs: StartLogs, history: bool, queued: bool, progress: StartProgress
) -> None:
    """Start Centrum zastaje dziennik Wyceny w efenix (bez zleceń albo ze zleceniami), jej plik Logów (z wynikiem, Urwanego
    Uruchomienia, żaden albo nieczytelny), jej wiersz Historii albo nie, jej Logi w Kolejce wysyłki albo nie i jej postęp
    w Skrzynce, w kolejce albo nigdzie: każde połączenie, w którym Centrum mogło zgasnąć albo zapis mógł się nie udać.
    Po starcie issue okresu ma jeden komentarz tego Uruchomienia, a jego wersja końcowa to ta z tabeli
    ``FINAL_AFTER_START``, nigdy postęp, który mówi, że Uruchomienie trwa; dziennik znika."""

    centrum = settling_centrum(tmp_path)
    box = centrum.surroundings.report_box
    box.background = frozenset()
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    queue = tmp_path / "config" / "zgloszenia" / "kolejka"
    started = JournalStarted(
        entry="start Uruchomienia", run_id=SWEPT_RUN, process="efenix", mode="zapis", period=PERIOD, started_at=SWEPT_START
    )
    beginning = PricingProgress(started, (), None, None)
    if progress != "nigdzie":
        _queued(queue, "20260916T101500000000Z", progress_post(beginning, progress_markdown(beginning, elapsed_s=0)).to_json())
    if progress == "w Skrzynce":
        centrum.restart()
        with centrum.client:  # ``lifespan`` wznawia kolejkę, która oddaje postęp Skrzynce
            assert wait_for(lambda: queued_logs(queue) == [] and box.issues_with(PROGRESS_LABEL) != [])
        centrum.client.stop()
    _swept_journal(centrum.log_path.parent / "dzienniki-wyceny", started, journal)
    with_result = _swept_logs(started, journal, ending="finished")
    file = centrum.log_path.parent / "uruchomienia" / with_result.file_name
    file.parent.mkdir(parents=True, exist_ok=True)
    match logs:
        case "z wynikiem":
            file.write_text(with_result.text, encoding="utf-8")
        case "urwane":
            file.write_text(_swept_logs(started, journal, ending="interrupted").text, encoding="utf-8")
        case "nieczytelne":
            file.write_text(with_result.text[:100], encoding="utf-8")
        case "brak":
            pass
    if history:
        counters = efenix_process.PROCESS.counter_names
        MetricsStore(centrum.engines.metrics.efenix, counters).append(
            metric_record(
                mode="RUN",
                period=PERIOD,
                started_at=SWEPT_START.isoformat(),
                total_duration_ms=60_000,
                phase_durations_ms={},
                ending="WYMAGA_SPRAWDZENIA",
                counters=dict.fromkeys(counters, 0),
            )
        )
    if queued:  # Logi, które kolejka przyjęła, zanim Centrum zgasło, a dziennik nie zdążył zniknąć
        queued_record = _swept_logs(started, journal, ending="interrupted") if logs == "urwane" else with_result
        _queued(queue, "20260916T110000000000Z", logi_post(queued_record).to_json())

    centrum.restart()
    with centrum.client:
        assert centrum.client.get("/api/runs/current").status_code == 200
        assert wait_for(lambda: queued_logs(queue) == [])
        finals = [shown(text) for issue in box.issues_with(PROGRESS_LABEL) for text in issue.comments]
    centrum.client.stop()

    assert len(finals) == 1, finals
    [final] = finals
    expected = FINAL_AFTER_START[logs, history]
    if isinstance(expected, str):
        ending = archived_logs(centrum, final)["ending"]
        assert {"finished": LOGS_WITH_RESULT, "interrupted": INTERRUPTED_LOGS}[ending] == expected, final
    else:
        result_line, logs_line = expected
        assert final.splitlines() == [
            f"**Logi Uruchomienia**: Wycena w efenix, zapis, okres {PERIOD}",
            "",
            result_line,
            *SWEPT_ORDER_LINES[journal],
            f"- Uruchomienie: {SWEPT_RUN}, start 2026-09-16 10:15:00 UTC",
            logs_line,
        ]
    assert journals(centrum) == [], "dziennik, którego wersję końcową przyjęła Kolejka wysyłki, znika"


def test_centrum_zgaszone_po_wyniku_wyceny_w_efenix_przed_jej_logami_zamienia_komentarz_postepu_w_wynik_z_historii(
    tmp_path: Path,
) -> None:
    """Wycena w efenix doszła do wyniku, jej wiersz Historii jest na dysku, a Centrum gaśnie nagle, cały proces razem z
    oknem efenix, zanim jej Logi trafią do pliku i do Kolejki wysyłki; postęp czeka w kolejce (Skrzynka Zgłoszeń dostaje
    klucz dopiero od następnego startu). Następny start Centrum zastaje dziennik z wierszem Historii i bez Logów: jedyny
    komentarz Uruchomienia w issue okresu to wynik z Historii z dopiskiem, że pełnych Logów nie ma, a nie postęp, który
    mówi, że Uruchomienie trwa; karta po starcie pokazuje wynik z Historii (ADR 0017), a dziennik znika."""

    queue = tmp_path / "config" / "zgloszenia" / "kolejka"
    after_result = tmp_path / "po-wyniku"
    surroundings = Surroundings()
    box = surroundings.report_box
    box.background = frozenset()
    with atrapa_efenix(IN_EFENIX) as atrapa:
        surroundings.efenix_url = atrapa.url
        centrum = settling_centrum(tmp_path, surroundings=surroundings)
        write_collective_file(centrum.period_parent, PRICED)
        with centrum_process(tmp_path, atrapa.url, after_result=after_result) as process:
            status, started = process.post("/api/runs", {"process": "efenix", "period": PERIOD, "dry_run": False})
            stalled = wait_for(after_result.exists, 300)
            process.kill()
    run_id = started["run"]["id"]
    history = centrum.engines.metrics.efenix.read_text(encoding="utf-8").splitlines()
    on_disk = (len(history), log_files(centrum), len(journals(centrum)), len(queued_logs(queue)))
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    centrum.restart()
    with centrum.client:  # start Centrum jak u taty: ``lifespan`` wznawia Kolejkę wysyłki z postępem
        previous = centrum.client.get("/api/runs/current").json()["previous"]
        assert wait_for(lambda: queued_logs(queue) == [])
        texts = [shown(text) for issue in box.issues_with(PROGRESS_LABEL) for text in issue.comments]
    centrum.client.stop()

    assert (status, stalled, on_disk) == (200, True, (1, [], 1, 1)), "stan po zgaśnięciu inny niż okno po wyniku"
    [final] = texts
    lines = final.splitlines()
    assert lines[:3] == [f"**Logi Uruchomienia**: Wycena w efenix, zapis, okres {PERIOD}", "", RESULT_FROM_HISTORY]
    assert lines[3].startswith("- Zlecenia: 6 z 6 skończone (")
    assert (lines[-2].startswith(f"- Uruchomienie: {run_id}, start "), lines[-1]) == (True, LOGS_NOT_WRITTEN)
    assert (previous["state"], previous["run"]["id"]) == ("recorded", run_id)
    assert journals(centrum) == []


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
    """Kopia wejścia Przygotowania to arkusz zleceń Rejestru: kolumny, które proces przenosi, pod nagłówkiem Rejestru
    (wiersz 1) w ich kolumnach arkusza, bez ``ADRES`` (E) i ``NUMER UMOWY`` (K), i każde zlecenie okresu z jego
    komórkami. Arkusz bez nagłówków zleceń („lista”) i kolumny, których proces nie przenosi (AKCJE, ZWROT, UWAGI),
    w Kopii nie stoją."""

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
        "C": "DATA GODZ. POCZ.",
        "D": "MIASTO",
        "F": "UMOWA",
        "G": "URZĄDZENIA",
        "H": "CZYNNOŚCI",
        "I": "NUMER ZL.",
        "J": "WYKONAWCA",
        "L": "SKUTECZNE",
        "M": "CZYNNOŚCI ZREALIZOWANE",
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
        started = centrum.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "dry_run": False})
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


def _copy_pricing(tmp_path: Path, stack: ExitStack) -> PreparingCentrum | SettlingCentrum:
    """Zlecenie, którego efenix nie zna: Wycena czyta cały wiersz i kończy się wynikiem bez zapisu w efenix."""

    atrapa = stack.enter_context(atrapa_efenix([]))
    centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
    order = Order("#ZLKW03", address=ADDRESS_VALUE, cells={"I": ORANGE_VALUE, "K": FREE_TEXT}, amount=0.0)
    write_collective_file(centrum.period_parent, [order])
    return centrum


COPY_PROCESSES = {"preparation": _copy_preparation, "settlement": _copy_settlement, "efenix": _copy_pricing}


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
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        started = centrum.client.post("/api/runs", json={"process": process, "period": PERIOD, "dry_run": process != "efenix"})
        assert started.status_code == 200, started.json()
        result = finished_view(centrum.client)["result"]

    assert result["stop_kind"] is None, result["stops"]
    box: FakeReportBox = centrum.surroundings.report_box
    assert box.wait_until(
        lambda fake: any(issue.label == "logi-uruchomienia" and issue.comments for issue in fake.background_issues)
    )
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
    texts = [path.read_text(encoding="utf-8") for path in sorted((centrum.log_path.parent / "uruchomienia").glob("*"))]
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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    write_quantity_source(centrum.collective_file, [{"B": ADDRESS_VALUE, "I": ORANGE_VALUE, "K": FREE_TEXT}])
    workbook = load_workbook(centrum.collective_file)
    sheet = active_worksheet(workbook)
    sheet["B17"], sheet["I17"] = "ADRES KLIENTA", "NR UMOWY ORANGE"
    workbook.save(centrum.collective_file)

    view = run_to_end(centrum, dry_run=True)

    assert view["result"]["stop_kind"] is None, view["result"]["stops"]
    box: FakeReportBox = centrum.surroundings.report_box
    assert box.wait_until(
        lambda fake: any(issue.label == "logi-uruchomienia" and issue.comments for issue in fake.background_issues)
    )
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
    """Rejestr zapisany znowu (Autozapis Excela, OneDrive) albo przeniesiony zaraz po odczycie: odcisk w Kopii wejścia
    to rozmiar i skrót bajtów, z których Przygotowanie przeczytało zlecenia, i chwila zmiany tej wersji, sprzed odczytu,
    a Kopia nie czyta pliku drugi raz, więc nie zatrzymuje Przygotowania."""

    content: list[bytes] = []

    def read_then_changed(path: Path, period: Any) -> Any:
        content.append(path.read_bytes())
        read = FILE_READERS.register(path, period)
        after_reading(path)
        return read

    readers = replace(FILE_READERS, register=read_then_changed)
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(readers=readers))
    _saved_at(centrum.fixture.register_path, READ_AT)

    view = run_to_end(centrum, dry_run=True)

    assert (view["result"]["result"], view["result"]["stop_kind"]) == ("OK", None), view["result"]["stops"]
    [record] = records(centrum)
    [copied] = record["input_copy"]
    [read] = content
    assert logged_fingerprint(copied) == {"size": len(read), "modified_at": READ_AT, "sha256": hashlib.sha256(read).hexdigest()}


@pytest.mark.parametrize("process", ["settlement", "efenix"])
def test_chwila_zmiany_w_odcisku_pliku_zbiorczego_jest_sprzed_odczytu_takze_gdy_plik_zapisano_zaraz_po_nim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, process: str
) -> None:
    """Plik zbiorczy zapisany znowu (Autozapis Excela, OneDrive) zaraz po tym, jak Przebieg rozliczeń albo Wycena w
    efenix przeczytały jego bajty: odcisk w Kopii wejścia ma chwilę zmiany przeczytanej wersji, sprzed odczytu."""

    file_bytes = workbook_files._file_bytes

    def read_then_saved(path: Path) -> bytes:
        content = file_bytes(path)
        if path.name == SOURCE_NAME:
            _saved_at(path, SAVED_AGAIN_AT)
        return content

    # Jedyny odczyt bajtów skoroszytu w src/ (tests/test_jeden_odczyt_skoroszytu.py).
    monkeypatch.setattr(workbook_files, "_file_bytes", read_then_saved)
    with ExitStack() as stack:
        centrum = COPY_PROCESSES[process](tmp_path, stack)
        assert isinstance(centrum, SettlingCentrum)
        _saved_at(centrum.collective_file, READ_AT)
        started = centrum.client.post("/api/runs", json={"process": process, "period": PERIOD, "dry_run": process != "efenix"})
        assert started.status_code == 200, started.json()
        result = finished_view(centrum.client)["result"]

    assert result["stop_kind"] is None, result["stops"]
    [record] = records(centrum)
    [copied] = record["input_copy"]
    assert (copied["name"], logged_fingerprint(copied)["modified_at"]) == (SOURCE_NAME, READ_AT)


def cells_row(copied: dict[str, Any]) -> int:
    """Miejsce (od 0) przeczytanego wiersza z zamaskowanym wolnym tekstem w jedynym arkuszu Kopii."""

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
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        started = centrum.client.post("/api/runs", json={"process": process, "period": PERIOD, "dry_run": process != "efenix"})
        assert started.status_code == 200, started.json()
        result = finished_view(centrum.client)["result"]

    assert result["stop_kind"] is None, result["stops"]
    box: FakeReportBox = centrum.surroundings.report_box
    assert box.wait_until(
        lambda fake: any(issue.label == "logi-uruchomienia" and issue.comments for issue in fake.background_issues)
    )
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
