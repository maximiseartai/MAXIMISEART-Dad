"""Logi Uruchomienia (ADR 0015, #317) przez HTTP API Centrum: plik JSON na komputerze taty po każdym Uruchomieniu.

Testy czytają pliki z katalogu Logów obok dziennika Centrum, tak jak Maks dostanie je z komputera taty.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from http import HTTPStatus
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
from typing import Any, NoReturn

from playwright.sync_api import Browser, sync_playwright
import pytest

from rozliczenia import TOOL_ROOT, settlement_messages
from rozliczenia.centrum import app, contract, runs
from rozliczenia.centrum.efenix_run import EfenixWindow
from rozliczenia.centrum.tool_update import Release
from rozliczenia.efenix_pace import ACTION_PAUSE_S, KEEPALIVE_S, Pace
from rozliczenia.period_folder import PeriodFolderInaccessible

from tests.fixtures.atrapa_efenix import AtrapaEfenix, AtrapaOrder, Changed, amount_of, atrapa_efenix
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
from tests.fixtures.potomne import wait_for
from tests.fixtures.preparation import PERIOD, incomplete_period_rows
from tests.fixtures.run_cards import first_view, restored
from tests.fixtures.settlement import MARKED, SOURCE_NAME, CellValue, write_quantity_source
from tests.fixtures.tool_clone import ToolRepository, git_command, git_failing_on, tool_repository

AnyCentrum = PreparingCentrum | SettlingCentrum
KEYS = {
    "schema_version", "run_id", "process", "mode", "period", "started_at", "ended_at", "duration_ms", "tool",
    "result", "ending", "stop_kind", "issue_count", "messages", "technical_notes", "summary", "phases", "templates",
    "inea_only_cleared", "intermax_entries", "efenix_orders", "efenix_stop", "environment", "trace", "diagnosis",
    "dad_actions", "interruption",
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
    assert "SYN-" not in text
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


def test_logi_nie_maja_tresci_komorek_wykonawcy_przy_wierszu_daty_dziennej_ani_pelnych_sciezek(tmp_path: Path) -> None:
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
    sent = [part for issue in box.background_issues for part in (issue.title, issue.body, *issue.comments)]
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    assert len(texts) == 3
    texts += sent
    naming = [
        settlement_messages.unmapped_worker_warning(centrum.collective_file, "ZNACZNIK-WYKONAWCA").what,
        settlement_messages.unmapped_worker(centrum.collective_file, ["ZNACZNIK-WYKONAWCA"]).what,
    ]
    for what in naming:
        forms = (what, json.dumps(what)[1:-1])
        assert any(form in text for form in forms for text in texts), what
        texts = [text.replace(forms[0], "").replace(forms[1], "") for text in texts]
    forbidden = ("ZNACZNIK", "adrian.testowy", "2026-09-09", "09.09.2026", in_json(tmp_path), in_json(tmp_path.resolve()))
    assert [marker for marker in forbidden if any(marker in text for text in texts)] == []
    assert sum("Adrian Testowy" in text for text in texts) == 4, "Wykonawca z Konfiguracji w obu wynikach z planem"


def test_diagnoza_w_logach_nie_ma_tresci_komorek_ani_pelnych_sciezek(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
    write_quantity_source(centrum.collective_file, [MARKED, {**MARKED, "H": "ZNACZNIK-WYKONAWCA"}])
    run_id = stopped_for_maks(centrum)
    centrum.collective_file.with_name(f"~${centrum.collective_file.name}").write_bytes(b"")

    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")

    assert response.status_code == 200, response.json()
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 2)
    [record] = records(centrum)
    assert "failed" in [check["state"] for check in record["diagnosis"]["checks"]], "Diagnoza z przyczyną w pliku Logów"
    sent = [part for issue in box.background_issues for part in (issue.title, issue.body, *issue.comments)]
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)] + sent
    forbidden = ("ZNACZNIK", "adrian.testowy", "2026-09-09", "09.09.2026", in_json(tmp_path), in_json(tmp_path.resolve()))
    assert [marker for marker in forbidden if any(marker in text for text in texts)] == []


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
        {"what": "strona błędu HTTP serwera efenix zamiast strony zlecenia", "status": 500},
        ["szukanie"],
        "otwarcie zlecenia",
    ),
    "D-strona-bledu-http-404": (
        replace(STOPPED_AT_SECOND[1].in_efenix("617"), error_status=HTTPStatus.NOT_FOUND),
        {"what": "strona błędu HTTP serwera efenix zamiast strony zlecenia", "status": 404},
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
        {"what": "strona błędu HTTP serwera efenix zamiast strony zlecenia", "status": 500},
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
    a Logi nie mają numeru zlecenia, adresu ani loginu Wykonawcy."""

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
    private = [*(order.number.removeprefix("#") for order in STOPPED_AT_SECOND), *(order.worker for order in STOPPED_AT_SECOND), "TESTOWA"]
    assert [marker for marker in private if marker in text] == []


def test_logi_wyceny_w_efenix_maja_slad_kazdego_zlecenia_bez_numeru_zlecenia_adresu_i_loginu_wykonawcy(tmp_path: Path) -> None:
    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        assert _start_pricing(centrum).status_code == 200
        assert finished_view(centrum.client)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: sum(len(issue.comments) for issue in fake.background_issues) == 1)
    [record] = records(centrum)
    texts = [path.read_text(encoding="utf-8") for path in log_files(centrum)]
    texts += [part for issue in box.background_issues for part in (issue.title, issue.body, *issue.comments)]

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
    private = [
        *(order.number.removeprefix("#") for order in PRICED),
        *(order.worker for order in PRICED),
        "TESTOWA",
        "PRYWATNA",
        "Miasto-Dzielnica",
        in_json(tmp_path),
    ]
    assert [marker for marker in private if any(marker in text for text in texts)] == []


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
    [_, sent] = logs_comments(box)
    assert '"operation": "sendDadNote"' in sent, "dziennik działań taty dociera do Maksa"
    assert [marker for marker in ("SYNTETYCZNY-TYTUŁ", "SYNTETYCZNA-TREŚĆ") if marker in text or marker in sent] == []


# Dziennik Wyceny w efenix (#845): ślad Wyceny na dysku taty w trakcie i Logi Urwanego Uruchomienia po starcie Centrum.

# Wiersze 18–21: gotowe po zapisach w efenix (data wykonania, Wycena Emmetta, ilość), gotowe bez zapisu (wycena już jest),
# zlecenie, przy którym efenix staje po zapisie daty wykonania, i zlecenie, do którego przebieg nie dochodzi.
CUT = [
    Order("#ZLQZ01", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQZ02", worker="beata.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1})), quantities={"012": 1}),
    Order("#ZLQZ03", worker="celina.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
    Order("#ZLQZ04", worker="dorota.testowa", cells={"O": 1}, amount=float(amount_of({"012": 1}))),
]
CUT_IN_EFENIX = [
    CUT[0].in_efenix("631"),
    CUT[1].in_efenix("632"),
    replace(CUT[2].in_efenix("633"), hung=True, after_date=True),
    CUT[3].in_efenix("634"),
]
# Wpis dziennika, który prąd urwał w trakcie zapisu.
TORN = '{"at": "2026-09-16T10:'


def journals(centrum: SettlingCentrum) -> list[Path]:
    return sorted((centrum.log_path.parent / "dzienniki-wyceny").glob("*"))


def journal_entries(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line != TORN]


def logs_json(comment: str) -> dict[str, Any]:
    """Logi JSON z komentarza Logów w jednej części."""

    loaded: dict[str, Any] = json.loads(comment.split("````json\n", 1)[1].split("\n````", 1)[0])
    return loaded


def test_centrum_zgaszone_w_trakcie_wyceny_w_efenix_po_starcie_wysyla_logi_urwanego_uruchomienia_ze_zleceniami_sprzed_zgasniecia(
    tmp_path: Path,
) -> None:
    """Centrum gaśnie nagle, cały proces razem z oknem efenix, przy trzecim zleceniu, po zapisie jego daty wykonania w
    efenix, a prąd urywa wpis dziennika w trakcie zapisu. Dziennik Wyceny w efenix ma wpis „zaczynam zlecenie” każdego
    zlecenia, które Atrapa ma zmienione. Następny start Centrum zamyka dziennik jako Logi Urwanego Uruchomienia: dwa
    zlecenia skończone z wynikiem i śladem, zlecenie zaczęte bez wyniku i jeden wpis nie do odczytania, bez wyniku
    Uruchomienia. Te Logi idą do Skrzynki Zgłoszeń jak zwykłe Logi, karta po starcie pokazuje zlecenia sprzed zgaśnięcia,
    a Urwane Uruchomienie nie ma karty wiersza Historii ani Powiadomienia o zakończonej Wycenie."""

    with atrapa_efenix(CUT_IN_EFENIX) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, CUT)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        before, _ = atrapa.state()
        with centrum_process(tmp_path, atrapa.url) as process:
            status, started = process.post("/api/runs", {"process": "efenix", "period": PERIOD, "dry_run": False})
            stalled = wait_for(lambda: atrapa.state()[0][2].execution_date is not None, 120)
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
    assert (changed, [row for row in changed if row not in begun]) == ([18, 20], []), "zmiana w efenix bez wpisu w dzienniku"
    assert [(entry["entry"], entry.get("row", entry.get("order", {}).get("row"))) for entry in entries] == [
        ("start Uruchomienia", None),
        ("zaczynam zlecenie", 18),
        ("zlecenie skończone", 18),
        ("zaczynam zlecenie", 19),
        ("zlecenie skończone", 19),
        ("zaczynam zlecenie", 20),
    ]
    assert (record["run_id"], record["ending"], record["result"], record["duration_ms"]) == (run_id, "interrupted", None, None)
    assert [(order["row"], order["outcome"], [step["action"] for step in order["steps"]]) for order in record["efenix_orders"]] == [
        (18, "gotowe", ["szukanie", "otwarcie zlecenia", "data wykonania", "otwarcie zlecenia", "Wycena Emmetta", "ilość"]),
        (19, "gotowe", ["szukanie", "otwarcie zlecenia"]),
    ]
    assert record["interruption"] == {"row": 20, "place": 3, "total": 4, "omitted": 1}
    assert utc(record["started_at"]) <= utc(record["ended_at"]) == utc(entries[-1]["at"])
    assert (logs_json(comment), "- Wynik: brak, Centrum zamknęło się w trakcie (Urwane Uruchomienie)" in comment) == (record, True)
    assert (previous["state"], previous["run"]["id"], previous["orders"]["title"]) == ("interrupted", run_id, "Zlecenia przed zamknięciem Centrum")
    assert {count["label"]: count["count"] for count in previous["orders"]["counts"]} == {
        "Gotowe do przekazania": 2,
        "Rozliczone": 0,
        "Błędy zleceń": 0,
        "Ostrzeżenia Emmetta": 0,
    }
    assert (card, [item for item in notifications if item["kind"] == "wycena_w_efenix"]) == ({"state": "missing"}, [])
    assert journals(centrum) == [], "dziennik, którego Logi przyjęła Kolejka wysyłki, znika"
    private = [*(order.number.removeprefix("#") for order in CUT), *(order.worker for order in CUT), "TESTOWA", "Miasto-Dzielnica"]
    assert [marker for marker in private if marker in journal_text or marker in comment] == []


@pytest.mark.parametrize("lost", [None, "historia", "logi"], ids=["logi-i-historia", "bez-historii", "bez-logow"])
def test_wycena_w_efenix_ktora_doszla_do_konca_nie_zostawia_dziennika_ktory_start_uznalby_za_urwany(
    tmp_path: Path, lost: str | None
) -> None:
    """Wycena w efenix doszła do wyniku. Następny start Centrum nie zamyka jej dziennika jako Urwanego Uruchomienia, także
    gdy zostały tylko jej Logi albo tylko jej wiersz Historii (Centrum zgasło po rekordzie metryk, a przed Logami, #722):
    karta po starcie ma wynik, Skrzynka nie dostaje drugich Logów, a dziennik znika."""

    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")
        assert _start_pricing(centrum).status_code == 200
        run_id = finished_view(centrum.client)["run"]["id"]
    box = centrum.surroundings.report_box
    assert box.wait_until(lambda fake: len(logs_comments(fake)) == 1)
    centrum.client.stop()
    [logs] = log_files(centrum)
    if lost == "historia":
        centrum.engines.metrics.efenix.unlink()
    elif lost == "logi":
        logs.unlink()

    centrum.restart()
    previous = centrum.client.get("/api/runs/current").json()["previous"]
    centrum.client.stop()

    expected = "recorded" if lost == "logi" else "restored"
    assert (previous["state"], previous["run"]["id"], len(logs_comments(box))) == (expected, run_id, 1)
    assert (log_files(centrum), journals(centrum)) == ([] if lost == "logi" else [logs], [])


def test_krotki_proces_nie_pisze_dziennika_wyceny_w_efenix(tmp_path: Path) -> None:
    """Przebieg rozliczeń zbiera Logi po wyniku, jak przed dziennikiem Wyceny w efenix: w trakcie nic nie trafia na dysk."""

    centrum = settling_centrum(tmp_path)
    run_to_end(centrum, dry_run=False)
    centrum.client.stop()

    assert (len(log_files(centrum)), (centrum.log_path.parent / "dzienniki-wyceny").exists()) == (1, False)


def test_dziennik_wyceny_w_efenix_ktorego_nie_da_sie_zapisac_nie_zatrzymuje_wyceny_i_ma_jedna_linie_w_dzienniku_centrum(
    tmp_path: Path,
) -> None:
    """Katalog dzienników zajęty przez plik: Wycena w efenix kończy się tym samym wynikiem co z dziennikiem, a dziennik
    Centrum ma jedną linię o dzienniku Wyceny, bez treści błędu, nie jedną na każdy wpis."""

    blocked = tmp_path / "logs" / "dzienniki-wyceny"
    blocked.parent.mkdir(parents=True)
    blocked.write_text("", encoding="utf-8")
    with atrapa_efenix(IN_EFENIX) as atrapa:
        centrum = _pricing_centrum(tmp_path, atrapa)
        assert _start_pricing(centrum).status_code == 200
        result = finished_view(centrum.client)["result"]
    centrum.client.stop()
    lines = [line for line in centrum.log_path.read_text(encoding="utf-8").splitlines() if "dziennik-wyceny" in line]

    assert (result["result"], len(records(centrum)[0]["efenix_orders"])) == ("WYMAGA_SPRAWDZENIA", 6)
    assert [line.split(" ", 1)[1] for line in lines] == ["dziennik-wyceny-niedostepny typ=FileExistsError miejsce=wpis"]


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
