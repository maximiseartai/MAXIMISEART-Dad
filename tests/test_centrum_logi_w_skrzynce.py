"""Logi Uruchomienia w Skrzynce Zgłoszeń (ADR 0015, #320, #844) przez HTTP API Centrum z fałszywą Skrzynką.

Maks czyta w Skrzynce jedno issue na okres, a w nim jeden komentarz na każde Uruchomienie: podsumowanie i odnośnik do
pełnych Logów w Archiwum Logów okresu (GitHub Release ``logi-<okres>``), gdzie leży plik o nazwie pliku Logów, który
rozpakowany jest plikiem Logów z komputera taty. Diagnoza (#321) dopisuje się do pliku, podmienia go w Archiwum i
zmienia komentarz swojego Uruchomienia (#840), a Zgłoszenie prowadzi do komentarza Logów swojego Uruchomienia. Plik z
Archiwum każdego procesu odtwarza się narzędziem odtwarzania (``tools/odtworz_uruchomienie.py``, #847) z tym samym wynikiem
i śladem. Żaden test nie łączy się z GitHubem.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
import copy
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Final, Protocol

from hypothesis import given, settings
from hypothesis import strategies as st
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import pytest

from odtworzenie import (
    COMPARED,
    NOT_COMPARED,
    SYNTHETIC_ADDRESS,
    SYNTHETIC_ORANGE,
    Difference,
    Report,
    Verdict,
    first_difference,
    replay,
    stop_cause,
)
from rozliczenia.tool_files import REPORT_ENTERING_STATE
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia import intermax_copies, settlement_messages
from rozliczenia.centrum import app
from rozliczenia.centrum.catalog import CATALOG, KINDS
from rozliczenia.centrum.outbox import RETRY_S
from rozliczenia.centrum.report_box import REPOSITORY, Refused, Unreachable
from rozliczenia.centrum.report_entering_logs import EnteringReplay, LoggedReports, ReplayedOrderless, Unreplayable
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import guard_logs
from rozliczenia.client_data import ForbiddenColumn, empty_memory
from rozliczenia.domain import RunMode
from rozliczenia.report_cells import ReportColumn
from rozliczenia.report_entering import EnteringFacts, Orderless, SavedState
from rozliczenia.worker_reports import (
    Kept,
    Login,
    MailId,
    OrderKey,
    OrderNumber,
    OwnEntries,
    OwnEntry,
    OwnMove,
    ReadReport,
    ReadStranger,
    ReadUnreadable,
    ReportEntry,
    SenderAddress,
    SubjectFault,
    UnknownSender,
)
from rozliczenia.worker_reports import Verdict as Intent

from atrapy.skrzynka import BoxIssue
from atrapy.workbooks import excel_lock
from tests.fixtures.centrum import (
    TOOL_COMMIT,
    CentrumClient,
    FakeReportBox,
    ToolDirectory,
    finished_view,
    views_until,
    write_report_key,
)
from atrapy.atrapa_efenix import PRICES, TODAY, AtrapaOrder, Changed, amount_of, atrapa_efenix
from tests.fixtures.centrum_intermax import ENTERING_NOW, SENDERS, Clock, entering_centrum, ordering_centrum, report
from atrapy.efenix import Order as EfenixOrder
from atrapy.efenix import write_collective_file
from tests.fixtures.fake_cli import fake_cli
from atrapy.intermax import (
    ADDRESS,
    APP_LAST,
    CONTRACT_NUMBER,
    DATE,
    FIRST,
    HEADERS,
    LAST,
    NUMBER,
    ORDER_SHEET,
    WORKER,
    Intermax,
    Order,
)
from tests.fixtures.konce_linii_windows import windows_text_writes
from tests.fixtures.centrum_processes import (
    PERIOD_MONDAY,
    SettlingCentrum,
    Surroundings,
    preparing_centrum,
    run_logs_handled,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from tests.fixtures.potomne import wait_for
from atrapy.preparation import INTERNAL_SETTLEMENT_NAME, incomplete_period_rows, paste_raw_orders, register_order
from atrapy.settlement import PERIOD, write_quantity_source
import sys

import odtworz_uruchomienie
import openpyxl
from atrapa_z_logow import ScopedOrder, fed
from rozliczenia.centrum.run_logs import LoggedOrder
from rozliczenia.efenix_address import AddressPart, address_differences

LABEL: Final = "logi-uruchomienia"
LINE = f"- Logi Uruchomienia okresu: {PERIOD}"
ARCHIVE = f"logi-{PERIOD}"
# Ostatnia linia komentarza: odnośnik do pliku w Archiwum Logów okresu (adres pobrania pliku GitHub Release).
LINK = re.compile(r"- Pełne Logi: \[(?P<name>[^\]]+)\]\(https://github\.com/(?P<repo>[^/]+/[^/]+)/releases/download/(?P<tag>[^/]+)/(?P<file>[^)]+)\)")


def watched_centrum(tmp_path: Path, *, key: bool = True, include_unmapped: bool = False) -> SettlingCentrum:
    """Centrum, którego fałszywa Skrzynka pokazuje Logi Uruchomienia w ``issues``, a nie w ruchu w tle."""

    centrum = settling_centrum(tmp_path, include_unmapped=include_unmapped)
    box(centrum).background = frozenset()
    if key:
        write_report_key(centrum.tool)
    return centrum


def box(centrum: SettlingCentrum) -> FakeReportBox:
    return centrum.surroundings.report_box


def threads(fake: FakeReportBox) -> list[BoxIssue]:
    return [issue for issue in fake.issues_with(LABEL) if issue.title == f"Logi Uruchomienia {PERIOD}"]


def thread_with(centrum: SettlingCentrum, comments: int) -> BoxIssue:
    """Jedyne issue Logów okresu, gdy ma już ``comments`` komentarzy, a kolejka Logów jest pusta.

    Skrzynka dostaje komentarz, zanim Outbox zapamięta jego adres dla Zgłoszenia i usunie plik kolejki.
    """

    def arrived(fake: FakeReportBox) -> bool:
        found = threads(fake)
        return len(found) == 1 and len(found[0].comments) == comments

    assert box(centrum).wait_until(arrived), f"issue Logów okresu nie ma {comments} komentarzy: {box(centrum).issues}"
    assert wait_for(lambda: queued_logs(centrum) == [])
    [thread] = threads(box(centrum))
    return thread


def diagnosed_comment(centrum: SettlingCentrum, edits: int) -> str:
    assert box(centrum).wait_until(lambda fake: len(fake.edited) == edits), f"Skrzynka nie ma {edits} poprawek"
    [comment] = thread_with(centrum, comments=1).comments
    return comment


def diagnosed_logs(centrum: SettlingCentrum, edits: int) -> dict[str, Any]:
    logs: dict[str, Any] = json.loads(archived(centrum, diagnosed_comment(centrum, edits)))
    return logs


def local_path(centrum: SettlingCentrum, run_id: str) -> Path:
    [path] = centrum.tool.run_logs.glob(f"*-{run_id}.json")
    return path


def local_logs(centrum: SettlingCentrum, run_id: str) -> bytes:
    """Plik Logów Uruchomienia ``run_id`` na dysku taty bajt w bajt: odczyt tekstowy ukryłby końce linii Windows."""

    return local_path(centrum, run_id).read_bytes()


def archived(centrum: SettlingCentrum, comment: str, *, tag: str = ARCHIVE) -> bytes:
    """Plik Logów z Archiwum, do którego prowadzi odnośnik komentarza, rozpakowany bajt w bajt; jedyny o tej nazwie w
    Archiwum."""

    link = LINK.fullmatch(comment.rstrip("\n").splitlines()[-1])
    assert link is not None, comment
    assert (link["repo"], link["tag"], link["file"]) == (REPOSITORY, tag, link["name"])
    files = box(centrum).archived(tag)
    assert link["name"] in files, (link["name"], sorted(files))
    return files[link["name"]]


def queued_logs(centrum: SettlingCentrum) -> list[Path]:
    """Pliki kolejki z Logami Uruchomienia, bez ``.json.tmp``, który kolejka zostawia na chwilę przepisania pliku
    (``replace_atomically``, na Windows z ponowieniami zamiany; #885)."""

    return sorted(centrum.tool.queue.glob(f"*-{LABEL}-*.json"))


def test_pierwsze_uruchomienie_okresu_zaklada_issue_i_archiwum_logow_a_kolejne_dopisuja_komentarze_i_pliki_takze_po_zamknieciu(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    foreign = [
        BoxIssue(1, LABEL, "Logi Uruchomienia 01_07_09_2026", "- Logi Uruchomienia okresu: 01_07_09_2026\n"),
        BoxIssue(2, LABEL, f"Logi Uruchomienia {PERIOD}0", f"- Logi Uruchomienia okresu: {PERIOD}0\n"),
        BoxIssue(3, "zgloszenie", "BRAK_WZORCA: Nie znaleziono wzorca.", f"## Komunikat\n\n{LINE}\n"),
    ]
    box(centrum).issues.extend(foreign)

    first = run_to_end(centrum, dry_run=True)
    thread = thread_with(centrum, comments=1)
    second = run_to_end(centrum, dry_run=True)
    thread_with(centrum, comments=2)
    box(centrum).close(thread.number)
    third = run_to_end(centrum, dry_run=False)
    thread_with(centrum, comments=3)

    assert (thread.title, thread.body.splitlines()[0]) == (f"Logi Uruchomienia {PERIOD}", LINE)
    runs = [view["run"]["id"] for view in (first, second, third)]
    assert [archived(centrum, comment) for comment in thread.comments] == [local_logs(centrum, run) for run in runs]
    [archive] = box(centrum).archives
    assert (archive.tag, archive.title) == (ARCHIVE, f"Logi Uruchomień {PERIOD}")
    assert [asset.name for asset in archive.assets] == [f"{local_path(centrum, run).name}.gz" for run in runs]
    assert [issue.comments for issue in foreign] == [[], [], []]
    assert wait_for(lambda: queued_logs(centrum) == [])


def test_pierwsze_uruchomienie_nowego_okresu_zaklada_nowe_archiwum_logow(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_to_end(centrum, dry_run=True)
    thread_with(centrum, comments=1)
    later = "15_21_09_2026"
    (centrum.period_parent / later).mkdir()

    started = centrum.start(dry_run=True, period=later)
    assert started.status_code == 200, started.json()
    view = finished_view(centrum.client)

    def arrived(fake: FakeReportBox) -> bool:
        return any(issue.title == f"Logi Uruchomienia {later}" and issue.comments for issue in fake.issues_with(LABEL))

    assert box(centrum).wait_until(arrived)
    assert wait_for(lambda: queued_logs(centrum) == [])
    [comment] = next(issue for issue in box(centrum).issues_with(LABEL) if issue.title.endswith(later)).comments
    assert archived(centrum, comment, tag=f"logi-{later}") == local_logs(centrum, view["run"]["id"])
    assert [(archive.tag, len(archive.assets)) for archive in box(centrum).archives] == [(ARCHIVE, 1), (f"logi-{later}", 1)]


def test_komentarz_ma_podsumowanie_uruchomienia_i_odnosnik_do_pliku_w_archiwum_ktory_rozpakowany_jest_plikiem_logow_bajt_w_bajt_takze_na_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Maks porównuje plik z Archiwum z plikiem Logów z komputera taty (``cmp``, skrót SHA-256): po rozpakowaniu mają te
    same bajty, także gdy zapis tekstowy na Windows zamienia ``\\n`` na ``\\r\\n`` (spec #837, #844)."""

    windows_text_writes(monkeypatch)
    centrum = watched_centrum(tmp_path)
    centrum.worker_settlements.mkdir()

    view = run_to_end(centrum, dry_run=False)

    [comment] = thread_with(centrum, comments=1).comments
    run_id = view["run"]["id"]
    local = local_logs(centrum, run_id)
    started = datetime.fromisoformat(json.loads(local)["started_at"])
    name = f"{local_path(centrum, run_id).name}.gz"
    assert re.sub(r"\n- Czas: [^\n]+\n", "\n- Czas: …\n", comment) == (
        f"**Logi Uruchomienia**: Przebieg rozliczeń, zapis, okres {PERIOD}\n"
        "\n"
        "- Wynik: BLAD_KRYTYCZNY, Zatrzymanie dla taty\n"
        "- Czas: …\n"
        "- Komunikaty: `FOLDER_ROZLICZEN_ISTNIEJE` (Zatrzymanie)\n"
        f"- Wydanie: brak, commit {TOOL_COMMIT[:7]}\n"
        f"- Uruchomienie: {run_id}, start {started:%Y-%m-%d %H:%M:%S} UTC\n"
        f"- Pełne Logi: [{name}](https://github.com/{REPOSITORY}/releases/download/{ARCHIVE}/{name})\n"
    )
    assert box(centrum).archived(ARCHIVE) == {name: local}


def _stop_for_maks(centrum: SettlingCentrum) -> None:
    centrum.engines.stop = settlement_messages.summary_not_shown()


def _failing_engine(centrum: SettlingCentrum) -> None:
    centrum.engines.fail_engine = True


def _failing_summary(centrum: SettlingCentrum) -> None:
    centrum.engines.fail_summary = True


def _as_is(centrum: SettlingCentrum) -> None:
    return None


SUMMARIES: Final[dict[str, tuple[Callable[[SettlingCentrum], None], bool, bool, list[str]]]] = {
    "ok": (_as_is, False, True, ["- Wynik: OK", "- Komunikaty: brak"]),
    "wymaga-sprawdzenia": (
        _as_is,
        True,
        True,
        ["- Wynik: WYMAGA_SPRAWDZENIA", "- Komunikaty: `BRAK_MAPOWANIA` (ostrzeżenie)"],
    ),
    "do-maksa": (
        _stop_for_maks,
        False,
        False,
        ["- Wynik: BLAD_KRYTYCZNY, Zatrzymanie do Maksa", "- Komunikaty: `BLAD_PODSUMOWANIA` (Zatrzymanie)"],
    ),
    "nieoczekiwany-wyjatek": (
        _failing_engine,
        False,
        False,
        ["- Wynik: BLAD_KRYTYCZNY, nieoczekiwany wyjątek", "- Komunikaty: `BLAD_NIEOCZEKIWANY` (Zatrzymanie)"],
    ),
    "po-silniku": (
        _failing_summary,
        False,
        True,
        ["- Wynik: BLAD_KRYTYCZNY, błąd po zakończeniu silnika", "- Komunikaty: `BLAD_PLANU` (Zatrzymanie)"],
    ),
}


@pytest.mark.parametrize(("steer", "unmapped", "dry_run", "lines"), SUMMARIES.values(), ids=SUMMARIES.keys())
def test_podsumowanie_komentarza_nazywa_wynik_sposob_zakonczenia_i_kody_komunikatow(
    tmp_path: Path, steer: Callable[[SettlingCentrum], None], unmapped: bool, dry_run: bool, lines: list[str]
) -> None:
    centrum = watched_centrum(tmp_path, include_unmapped=unmapped)
    steer(centrum)

    view = run_to_end(centrum, dry_run=dry_run)

    [comment] = thread_with(centrum, comments=1).comments
    assert [line for line in lines if line not in comment.splitlines()] == []
    assert archived(centrum, comment) == local_logs(centrum, view["run"]["id"])


@pytest.mark.parametrize(
    ("cause", "failure", "key"),
    [("brak-sieci", Unreachable(), True), ("odmowa", Refused(), True), ("brak-klucza", None, False)],
    ids=["brak-sieci", "odmowa", "brak-klucza"],
)
def test_logi_bez_skrzynki_czekaja_w_kolejce_bez_komunikatu_a_nastepny_start_je_wysyla(
    tmp_path: Path, cause: str, failure: Refused | Unreachable | None, key: bool
) -> None:
    centrum = watched_centrum(tmp_path, key=key)
    box(centrum).search_failure = failure

    view = run_to_end(centrum, dry_run=True)

    waiting = f"skrzynka-czeka etykieta={LABEL} okres={PERIOD} przyczyna={cause}"
    assert wait_for(lambda: waiting in centrum.log_path.read_text(encoding="utf-8"))
    assert (view["result"]["result"], view["result"]["stops"], view["result"]["warnings"]) == ("OK", [], [])
    assert view["result"]["technical_notes"] == []
    [queued] = queued_logs(centrum)
    assert list(ToolDirectory(tmp_path).queue.parent.iterdir()) == [ToolDirectory(tmp_path).queue]
    assert (box(centrum).issues, box(centrum).archives) == ([], [])

    box(centrum).search_failure = None
    write_report_key(centrum.tool)
    centrum.restart()
    with centrum.client:
        [comment] = thread_with(centrum, comments=1).comments

    assert archived(centrum, comment) == local_logs(centrum, view["run"]["id"])
    assert wait_for(lambda: queued_logs(centrum) == [])
    assert not queued.exists()


def diagnose(centrum: SettlingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert response.status_code == 200, response.json()
    diagnosis: dict[str, Any] = response.json()
    return diagnosis


def test_diagnoza_po_zatrzymaniu_do_maksa_dopisuje_sie_do_pliku_logow_i_zmienia_komentarz_uruchomienia_w_issue_okresu(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    before = local_logs(centrum, run_id)
    [first] = thread_with(centrum, comments=1).comment_ids

    shown = diagnose(centrum, run_id)

    comment = diagnosed_comment(centrum, edits=1)
    local = local_logs(centrum, run_id)
    diagnosis = json.loads(local)["diagnosis"]
    assert {**json.loads(local), "diagnosis": None} == json.loads(before)
    assert [{part: check[part] for part in ("label", "state", "detail")} for check in diagnosis["checks"]] == shown["checks"]
    assert {part: diagnosis["explanation"][part] for part in ("what", "where", "action")} == shown["explanation"]
    assert diagnosis["next_action"] == shown["next_action"]
    assert archived(centrum, comment) == local
    assert list(box(centrum).archived(ARCHIVE)) == [f"{local_path(centrum, run_id).name}.gz"]
    assert f"- Diagnoza: `{diagnosis['explanation']['code']}`" in [line.split(";")[0] for line in comment.splitlines()]
    assert box(centrum).edited == [first]
    assert len(box(centrum).issues_with(LABEL)) == 1


def unexpected_exception(centrum: SettlingCentrum) -> str:
    """Nieoczekiwany wyjątek, po którym karta zaczyna Diagnozę sama przy każdym pokazaniu; zwraca id Uruchomienia."""

    centrum.engines.fail_engine = True
    try:
        view = run_to_end(centrum, dry_run=True)
    finally:
        centrum.engines.fail_engine = False
    assert (view["result"]["ending"], view["result"]["diagnosis"]) == ("unexpected", "automatic")
    run_logs_handled(centrum)
    return str(view["run"]["id"])


def test_diagnoza_z_tym_samym_wynikiem_przy_kazdym_pokazaniu_karty_zmienia_komentarz_logow_raz(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = unexpected_exception(centrum)
    thread_with(centrum, comments=1)
    diagnose(centrum, run_id)
    diagnosed = diagnosed_comment(centrum, edits=1)

    shown = [diagnose(centrum, run_id) for _ in range(3)]
    response = centrum.client.post(f"/api/runs/{run_id}/report")

    assert diagnosed_comment(centrum, edits=1) == diagnosed
    assert archived(centrum, diagnosed) == local_logs(centrum, run_id)
    assert response.json() == {"state": "sent"}
    [report] = box(centrum).sent
    assert report.body == shown[-1]["report"]["body"]
    [thread] = threads(box(centrum))
    link = f"- Logi: https://github.com/{REPOSITORY}/issues/{thread.number}#issuecomment-1"
    assert link in report.body.splitlines()
    assert len(box(centrum).edited) == 1


def test_diagnoza_z_innym_wynikiem_niz_ostatnio_wyslana_zmienia_komentarz_logow(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = unexpected_exception(centrum)
    template = centrum.configuration.worker_template
    good = template.read_bytes()
    thread_with(centrum, comments=1)

    passing = diagnose(centrum, run_id)
    sent = [diagnosed_logs(centrum, edits=1)]
    template.write_bytes(b"to nie jest skoroszyt")
    broken = diagnose(centrum, run_id)
    sent.append(diagnosed_logs(centrum, edits=2))
    template.write_bytes(good)
    fixed = diagnose(centrum, run_id)
    sent.append(diagnosed_logs(centrum, edits=3))
    centrum.surroundings.github.release = None
    offline = diagnose(centrum, run_id)
    sent.append(diagnosed_logs(centrum, edits=4))
    centrum.surroundings.github.tool_commit = None
    without_git = diagnose(centrum, run_id)

    sent.append(diagnosed_logs(centrum, edits=5))
    labels = ("Wzorzec rozliczenia pracownika", "Aktualność narzędzia")
    shown = (passing, broken, fixed, offline, without_git)
    states = [tuple(check_state(diagnosis, label) for label in labels) for diagnosis in shown]
    assert states == [
        ("passed", "passed"),
        ("failed", "passed"),
        ("passed", "passed"),
        ("passed", "not_checked"),
        ("passed", "not_checked"),
    ]
    assert check_detail(offline, labels[1]) != check_detail(without_git, labels[1])
    logged = [logs["diagnosis"] for logs in sent]
    assert [tuple(check_state(diagnosis, label) for label in labels) for diagnosis in logged] == states
    assert [check_detail(diagnosis, labels[1]) for diagnosis in logged[-2:]] == [
        check_detail(diagnosis, labels[1]) for diagnosis in shown[-2:]
    ]
    assert sent[-1] == json.loads(local_logs(centrum, run_id))
    assert len(box(centrum).archived(ARCHIVE)) == 1


def test_to_samo_wyjasnienie_o_innym_pliku_okresu_zmienia_komentarz_logow(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = unexpected_exception(centrum)
    thread_with(centrum, comments=1)
    collective = centrum.collective_file.with_name(f"~${centrum.collective_file.name}")
    collective.write_bytes(b"")
    first = diagnose(centrum, run_id)
    sent = [diagnosed_logs(centrum, edits=1)]

    collective.unlink()
    (centrum.period_directory / f"~${INTERNAL_SETTLEMENT_NAME}").write_bytes(b"")
    second = diagnose(centrum, run_id)

    sent.append(diagnosed_logs(centrum, edits=2))
    shown = [diagnosis["explanation"]["where"] for diagnosis in (first, second)]
    assert shown[0] != shown[1]
    logged = [logs["diagnosis"]["explanation"] for logs in sent]
    assert [(explanation["code"], explanation["where"]) for explanation in logged] == [
        ("PLIK_OKRESU_OTWARTY", where) for where in shown
    ]


def test_inny_plik_tylko_w_chmurze_za_tym_samym_co_zrobic_zmienia_komentarz_logow(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = unexpected_exception(centrum)
    onedrive = centrum.surroundings.onedrive
    assert onedrive is not None
    thread_with(centrum, comments=1)
    onedrive.online_only.add(centrum.collective_file)
    first = diagnose(centrum, run_id)
    sent = [diagnosed_logs(centrum, edits=1)]

    onedrive.online_only = {centrum.configuration.worker_template}
    second = diagnose(centrum, run_id)

    sent.append(diagnosed_logs(centrum, edits=2))
    explanations = [diagnosis["explanation"] for diagnosis in (first, second)]
    assert explanations[0]["action"] == explanations[1]["action"]
    assert explanations[0]["where"] != explanations[1]["where"]
    logged = [logs["diagnosis"]["explanation"] for logs in sent]
    assert [(explanation["code"], explanation["where"]) for explanation in logged] == [
        ("PLIK_TYLKO_W_CHMURZE", explanation["where"]) for explanation in explanations
    ]


def test_inna_wada_sprawdzenia_za_tym_samym_wyjasnieniem_zmienia_komentarz_logow(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = unexpected_exception(centrum)
    thread_with(centrum, comments=1)
    centrum.configuration.worker_template.write_bytes(b"to nie jest skoroszyt")
    # Pliki okresu Diagnoza czyta na dysku przy każdym pytaniu (Listę Wykonawców bierze z migawki startu, D9).
    collective = centrum.collective_file.read_bytes()
    centrum.collective_file.unlink()
    without_collective_file = diagnose(centrum, run_id)
    sent = [diagnosed_logs(centrum, edits=1)]

    centrum.collective_file.write_bytes(collective)
    excel_lock(centrum.collective_file).write_bytes(b"")
    open_in_excel = diagnose(centrum, run_id)

    sent.append(diagnosed_logs(centrum, edits=2))
    diagnoses = (without_collective_file, open_in_excel)
    assert [diagnosis["explanation"] for diagnosis in diagnoses] == [without_collective_file["explanation"]] * 2
    logged = [logs["diagnosis"] for logs in sent]
    failed = [[(check["label"], check["code"]) for check in diagnosis["checks"] if check["state"] == "failed"] for diagnosis in logged]
    assert [rows[1:] for rows in failed] == [
        [("Folder okresu", "BRAK_PLIKU_ZBIORCZEGO")],
        [("Pliki okresu w Excelu", "PLIK_OKRESU_OTWARTY")],
    ]


def test_plik_logow_ktory_nie_powstal_przy_diagnozie_powstaje_przy_nastepnej_z_tym_samym_wynikiem(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = unexpected_exception(centrum)
    thread_with(centrum, comments=1)
    [path] = centrum.tool.run_logs.glob(f"*-{run_id}.json")
    blocked = path.with_name(path.name + ".tmp")
    blocked.mkdir()
    diagnose(centrum, run_id)
    diagnosed_comment(centrum, edits=1)
    assert json.loads(local_logs(centrum, run_id))["diagnosis"] is None

    blocked.rmdir()
    diagnose(centrum, run_id)

    comment = diagnosed_comment(centrum, edits=2)
    assert json.loads(local_logs(centrum, run_id))["diagnosis"] is not None
    assert archived(centrum, comment) == local_logs(centrum, run_id)


def check_state(diagnosis: dict[str, Any], label: str) -> str:
    [state] = [check["state"] for check in diagnosis["checks"] if check["label"] == label]
    return str(state)


def check_detail(diagnosis: dict[str, Any], label: str) -> str:
    [detail] = [check["detail"] for check in diagnosis["checks"] if check["label"] == label]
    return str(detail)


def test_wyslane_zgloszenie_prowadzi_do_komentarza_logow_swojego_uruchomienia(tmp_path: Path) -> None:
    centrum = watched_centrum(tmp_path)
    run_to_end(centrum, dry_run=True)
    thread_with(centrum, comments=1)
    run_id = stopped_for_maks(centrum)
    thread = thread_with(centrum, comments=2)

    preview = diagnose(centrum, run_id)["report"]
    response = centrum.client.post(f"/api/runs/{run_id}/report")

    assert response.json() == {"state": "sent"}
    [report] = box(centrum).sent
    assert report.body == preview["body"]
    link = f"- Logi: https://github.com/{REPOSITORY}/issues/{thread.number}#issuecomment-2"
    assert link in report.body.splitlines()
    assert archived(centrum, thread.comments[1]).startswith(('{\n  "run_id": "' + run_id).encode())


def test_diagnoza_bez_sieci_jest_w_pliku_logow_a_w_kolejce_zastepuje_logi_bez_niej_a_zgloszenie_dziala_jak_dotad(
    tmp_path: Path,
) -> None:
    """Bez sieci Logi z Diagnozą, nowsza wersja wysyłki Logów tego Uruchomienia, zastępują w Kolejce wysyłki Logi bez
    niej (#846): po powrocie sieci komentarz Uruchomienia powstaje od razu z Diagnozą, bez poprawki."""

    centrum = watched_centrum(tmp_path)
    box(centrum).search_failure = Unreachable()
    run_id = stopped_for_maks(centrum)

    shown = diagnose(centrum, run_id)
    state = centrum.client.post(f"/api/runs/{run_id}/report").json()

    local = local_logs(centrum, run_id)
    assert json.loads(local)["diagnosis"]["checks"][0]["label"] == shown["checks"][0]["label"]
    assert f"- Logi: jeszcze niewysłane, Uruchomienie {run_id}" in shown["report"]["body"].splitlines()
    assert state == {"state": "queued", "waits_for": "internet"}
    assert wait_for(lambda: len(queued_logs(centrum)) == 1)
    assert box(centrum).issues == []

    box(centrum).search_failure = None
    centrum.restart()
    with centrum.client:
        comment = diagnosed_comment(centrum, edits=0)
        assert box(centrum).wait_until(lambda box: len(box.sent) == 1)

    assert (archived(centrum, comment), box(centrum).edited) == (local, [])
    assert box(centrum).sent[0].body == shown["report"]["body"]
    assert wait_for(lambda: queued_logs(centrum) == [])


def test_katalog_logow_bez_prawa_zapisu_nie_zmienia_diagnozy_ani_zgloszenia_a_diagnoza_idzie_do_skrzynki(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    blocked = centrum.tool.run_logs
    blocked.parent.mkdir(parents=True, exist_ok=True)
    blocked.write_text("", encoding="utf-8")
    run_id = stopped_for_maks(centrum)
    thread_with(centrum, comments=1)

    shown = diagnose(centrum, run_id)

    comment = diagnosed_comment(centrum, edits=1)
    assert json.loads(archived(centrum, comment))["diagnosis"]["next_action"] == shown["next_action"]
    assert "- Logi: https://github.com/" in shown["report"]["body"]
    assert blocked.read_text(encoding="utf-8") == ""
    log = centrum.log_path.read_text(encoding="utf-8")
    assert 'nieoczekiwany-wyjatek typ=FileExistsError miejsce="Diagnoza w Logach Uruchomienia"' in log


def test_diagnoza_uruchomienia_bez_logow_nie_trafia_do_logow_poprzedniego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = watched_centrum(tmp_path)
    earlier = run_to_end(centrum, dry_run=True)["run"]["id"]
    thread_with(centrum, comments=1)
    before = local_logs(centrum, earlier)

    def broken(*_: object, **__: object) -> list[Path]:
        raise RuntimeError("syntetyczny błąd budowy Logów")

    monkeypatch.setattr(app, "files_of_process", broken)
    run_id = stopped_for_maks(centrum)

    shown = diagnose(centrum, run_id)

    assert f"- Logi: jeszcze niewysłane, Uruchomienie {run_id}" in shown["report"]["body"].splitlines()
    assert local_logs(centrum, earlier) == before
    assert wait_for(lambda: queued_logs(centrum) == [])
    assert len(threads(box(centrum))[0].comments) == 1


def test_kolejne_uruchomienie_okresu_bez_uprawnienia_do_archiwum_ma_komentarz_z_dopiskiem_a_plik_dochodzi_po_przywroceniu(
    tmp_path: Path,
) -> None:
    """Issue okresu już jest, jak u taty przy każdym Uruchomieniu poza pierwszym w okresie: bez uprawnienia Tokenu do
    Archiwum komentarz Uruchomienia idzie z dopiskiem, że pełne Logi czekają w kolejce, a plik dochodzi do Archiwum, gdy
    uprawnienie wróci, bez drugiego komentarza ani poprawki (#844)."""

    centrum = watched_centrum(tmp_path)
    first = run_to_end(centrum, dry_run=True)["run"]["id"]
    thread_with(centrum, comments=1)
    box(centrum).archive_failure = Refused()

    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]

    assert box(centrum).wait_until(lambda fake: len(threads(fake)) == 1 and len(threads(fake)[0].comments) == 2)
    name = f"{local_path(centrum, run_id).name}.gz"
    waiting = f"skrzynka-czeka etykieta={LABEL} okres={PERIOD} przyczyna=odmowa-archiwum"
    assert wait_for(lambda: waiting in centrum.log_path.read_text(encoding="utf-8"))
    summary, note = threads(box(centrum))[0].comments[1].split("\n\n")[1:]
    assert summary.splitlines()[-1] == (
        f"- Pełne Logi: [{name}](https://github.com/{REPOSITORY}/releases/download/{ARCHIVE}/{name})"
    )
    assert note.startswith(f"Plik `{name}` czeka w Kolejce wysyłki na komputerze taty")
    assert list(box(centrum).archived(ARCHIVE)) == [f"{local_path(centrum, first).name}.gz"]

    # Przejście nastawia ponowienie dopiero po przepisaniu pliku kolejki, które idzie po linii dziennika (#885).
    assert wait_for(lambda: centrum.surroundings.clock.wakes == 1)
    box(centrum).archive_failure = None
    centrum.surroundings.clock.advance(RETRY_S)

    assert wait_for(lambda: queued_logs(centrum) == [])
    assert box(centrum).archived(ARCHIVE)[name] == local_logs(centrum, run_id)
    assert ([len(issue.comments) for issue in threads(box(centrum))], box(centrum).edited) == ([2], [])


def test_bez_uprawnienia_do_archiwum_komentarz_idzie_z_dopiskiem_a_plik_czeka_bez_komunikatu_i_dochodzi_po_przywroceniu(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    box(centrum).archive_failure = Refused()

    view = run_to_end(centrum, dry_run=True)

    def commented(fake: FakeReportBox) -> bool:
        return len(threads(fake)) == 1 and len(threads(fake)[0].comments) == 1

    assert box(centrum).wait_until(commented)
    run_id = view["run"]["id"]
    name = f"{local_path(centrum, run_id).name}.gz"
    [queued] = queued_logs(centrum)
    waiting = f"skrzynka-czeka etykieta={LABEL} okres={PERIOD} przyczyna=odmowa-archiwum plik={queued.name}"
    assert wait_for(lambda: waiting in centrum.log_path.read_text(encoding="utf-8"))
    [comment] = threads(box(centrum))[0].comments
    summary, note = comment.split("\n\n")[1:]
    assert summary.splitlines()[-1] == (
        f"- Pełne Logi: [{name}](https://github.com/{REPOSITORY}/releases/download/{ARCHIVE}/{name})"
    )
    assert note.startswith(f"Plik `{name}` czeka w Kolejce wysyłki na komputerze taty")
    assert (view["result"]["stops"], view["result"]["warnings"], view["result"]["technical_notes"]) == ([], [], [])
    assert centrum.client.get("/api/configuration").json()["reports"] == "ready"
    assert (box(centrum).archive_requests, box(centrum).archives) == (1, [])

    # Przejście nastawia ponowienie dopiero po przepisaniu pliku kolejki, które idzie po linii dziennika (#885).
    assert wait_for(lambda: centrum.surroundings.clock.wakes == 1)
    box(centrum).archive_failure = None
    centrum.surroundings.clock.advance(RETRY_S)

    assert wait_for(lambda: queued_logs(centrum) == [])
    assert box(centrum).archived(ARCHIVE) == {name: local_logs(centrum, run_id)}
    assert ([len(issue.comments) for issue in threads(box(centrum))], box(centrum).edited) == ([1], [])
    log = centrum.log_path.read_text(encoding="utf-8")
    assert (log.count("przyczyna=odmowa-archiwum"), log.count("nieoczekiwany-wyjatek")) == (1, 0)


# Odtworzenie Uruchomienia z pliku w Archiwum Logów okresu (``tools/odtworz_uruchomienie.py``, #847): Logi powstają
# tak jak u taty, przez HTTP API Centrum z fałszywą Skrzynką (Wycena w efenix na Atrapie efenix), a narzędzie dostaje plik
# z Archiwum spakowany gzipem, jak go pobiera Maks, i odtwarza Uruchomienie w katalogu roboczym testu.

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "odtworz_uruchomienie.py"
# Chwila zegara Uporządkowania INTERMAX tylko tych testów, więc nazwa ich Kopii INTERMAX jest tylko ich.
ORDERED_AT = datetime(2026, 10, 26, 15, 16, 17)
INTERMAX_COPY = "INTERMAX przed uporządkowaniem 2026-10-26 15-16-17.xlsx"


def test_odtworzenie_porownuje_kazde_pole_logow_poza_faktami_startu_i_okolicznosciami() -> None:
    """Nowe pole Logów trafia do porównania odtworzenia albo do pól, które odtworzenie bierze z Logów albo które zależą od
    chwili i komputera (``NOT_COMPARED``), a nie wychodzi dopiero w biegu odtworzenia."""

    compared = [part.key for part in COMPARED]

    assert len(compared) == len(set(compared))
    assert set(compared).isdisjoint(NOT_COMPARED)
    assert set(compared) | NOT_COMPARED == set(RunLog.model_fields)


def test_pomoc_narzedzia_wymienia_kazdy_proces_katalogu(capsys: pytest.CaptureFixture[str]) -> None:
    """``--help`` narzędzia odtwarzania wymienia każdy proces, który odtwarza, nazwą z karty Centrum, a parametrów,
    którymi narzędzie woła swoją kopię commitu (``--opis-kodu``, ``--granica``), nie pokazuje."""

    with pytest.raises(SystemExit) as exited:
        odtworz_uruchomienie.main(["--help"])

    shown = " ".join(capsys.readouterr().out.split())
    assert exited.value.code == 0
    assert [kind.title for kind in CATALOG.kinds if kind.title not in shown] == []
    assert [option for option in ("--opis-kodu", "--granica") if option in shown] == []


def test_zly_parametr_narzedzia_daje_skladnie_i_blad_na_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    """Parametr, którego narzędzie nie przyjmuje (dzień Atrapy, który nie jest datą), kończy je kodem 2 ze składnią
    wywołania i błędem na stderr."""

    with pytest.raises(SystemExit) as exited:
        odtworz_uruchomienie.main(["logi.json", "--efenix-dzis", "jutro"])

    shown = capsys.readouterr()
    assert (exited.value.code, shown.out, shown.err.startswith("usage: "), "błąd: argument --efenix-dzis" in shown.err) == (2, "", True, True), shown.err


def _replayed(capsys: pytest.CaptureFixture[str], *arguments: str | Path) -> tuple[int, list[str]]:
    code = odtworz_uruchomienie.main([str(argument) for argument in arguments])
    return code, capsys.readouterr().out.splitlines()


class _Sending(Protocol):
    """Centrum procesu z fałszywą Skrzynką Zgłoszeń, do której Kolejka wysyłki wysyła plik Logów."""

    @property
    def client(self) -> CentrumClient: ...

    @property
    def surroundings(self) -> Surroundings: ...


def _archive_file(centrum: _Sending, folder: Path) -> Path:
    """Plik Logów z Archiwum Logów okresu fałszywej Skrzynki, spakowany gzipem, jak go pobiera Maks.

    Zatrzymuje Centrum, gdy plik doszedł: wątek kolejki po wysyłce dalej zapisuje plik zapisów skrzynki i znacznik
    części w ``config`` przez pliki ``.tmp``, a kopia albo odczyt folderu Konfiguracji w trakcie tych zapisów pada na
    wolnym runnerze Windows (``shutil.Error``, #1329).
    """

    fake = centrum.surroundings.report_box
    assert fake.wait_until(lambda box: any(archive.assets for archive in box.archives)), "plik Logów nie doszedł do Archiwum"
    centrum.client.stop()
    [asset] = [asset for archive in fake.archives for asset in archive.assets]
    path = folder / asset.name
    path.write_bytes(asset.data)
    return path


@dataclass(frozen=True)
class Produced:
    """Logi z Archiwum Logów okresu jednego Uruchomienia i parametry narzędzia, których potrzebuje jego odtworzenie."""

    archived: Path
    arguments: tuple[str, ...]

    @property
    def record(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(gzip.decompress(self.archived.read_bytes()))
        return loaded


def _settlement(tmp_path: Path) -> Produced:
    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    assert run_to_end(centrum, dry_run=True)["result"]["result"] == "OK"
    return Produced(_archive_file(centrum, tmp_path), ("--konfiguracja", str(tmp_path / "config")))


def _preparation(tmp_path: Path, paste: Callable[[Path], object] | None = None) -> Produced:
    tmp_path.mkdir()
    centrum = preparing_centrum(tmp_path)
    if paste is not None:
        paste(centrum.fixture.register_path)
    write_report_key(ToolDirectory(tmp_path))
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    configuration = {centrum.fixture.config_path.parent, centrum.fixture.internal_template_path.parent}
    assert configuration == {tmp_path / "config"}
    return Produced(_archive_file(centrum, tmp_path), ("--konfiguracja", str(tmp_path / "config")))


# Instalacje hurt z Wpisem urządzenia i czynności INTERMAX i bez niego, dwóch Wykonawców: wiersze dnia w śladzie
# (``intermax_entries``) zależą od ostatniego uporządkowanego i żółtego wiersza nad wklejeniem.
PASTED = (
    Order(datetime(2026, 10, 26, 8), "jan.nowak", 201, "P4", "Instalacja Hurt"),
    Order(datetime(2026, 10, 26, 9), "anna.kowalska", 202, "T-Mobile", "Instalacja Hurt"),
    Order(datetime(2026, 10, 26, 10), "jan.nowak", 203, "P4", "Instalacja Hurt"),
    Order(datetime(2026, 10, 26, 11), "jan.nowak", 204, "INEA S.A.", "Instalacja Hurt"),
    Order(datetime(2026, 10, 26, 13), "anna.kowalska", 205, "P4", "Usterka"),
)


def _intermax(tmp_path: Path, intermax: Intermax | None = None) -> Produced:
    centrum = ordering_centrum(tmp_path, intermax or Intermax(raw=PASTED), clock=Clock([ORDERED_AT]))
    write_report_key(ToolDirectory(tmp_path))
    centrum.run_to_end()
    return Produced(_archive_file(centrum, tmp_path), ())


# Wycena w efenix na Atrapie: każde działanie okna (szukanie, otwarcie zlecenia, data wykonania, Wycena Emmetta, ilość)
# i każdy odczyt strony z Logów (#843), po Wykonawcach: zlecenie wycenione, sprzeczne z Emmettem, z innym statusem, z
# innym lokalem, numer, pod którym efenix pokazuje tylko inne, rozliczone zlecenie, i numer, którego efenix nie zna.
_FILE_ADDRESS = "UL. ZAWILCOWA 12/3"
_EFENIX_ADDRESS = "Miastowo-Centrum ul.Zawilcowa 12 Lokal 3"
# Ceny pozycji efenix taty inne niż ceny Atrapy: odtworzenie bierze je z kwot w Logach.
_TATA_PRICES = {**PRICES, "012": Decimal("99.00")}
_PRICED = float(amount_of({"012": 1}, _TATA_PRICES))


def _efenix_order(number: str, worker: str, **changes: Any) -> EfenixOrder:
    order = EfenixOrder(number, worker=worker, address=_FILE_ADDRESS, efenix_address=_EFENIX_ADDRESS, cells={"O": 1}, amount=_PRICED)
    return replace(order, **changes)


PRICED = [
    _efenix_order("#ZLQR01", "adrian.testowy"),
    _efenix_order("#ZLQR02", "beata.testowa", emmett={"012": 2}),
    _efenix_order("#ZLQR03", "celina.testowa"),
    _efenix_order("#ZLQR04", "dorota.testowa", efenix_address="Miastowo-Centrum ul.Zawilcowa 12 Lokal 4"),
    _efenix_order("#ZLQR05", "ewa.testowa"),
    _efenix_order("#ZLQR06", "filip.testowy"),
]
IN_EFENIX = [
    PRICED[0].in_efenix("641"),
    PRICED[1].in_efenix("642"),
    replace(PRICED[2].in_efenix("643"), status="W realizacji"),
    PRICED[3].in_efenix("644"),
    replace(PRICED[4].in_efenix("645"), number="ZLQR050", realizator="gustaw.testowy", status="Rozliczone"),
]


def _efenix(
    tmp_path: Path,
    in_efenix: list[AtrapaOrder] | None = None,
    result: str = "WYMAGA_SPRAWDZENIA",
    pricing: str = "bez Przekazania",
    priced: list[EfenixOrder] = PRICED,
) -> Produced:
    with atrapa_efenix(in_efenix or IN_EFENIX, prices=_TATA_PRICES) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, priced)
        write_report_key(ToolDirectory(tmp_path))
        request = {"process": "efenix", "period": PERIOD, "mode": "RUN", "pricing": pricing}
        started = centrum.client.post("/api/runs", json=request)
        assert started.status_code == 200, started.json()
        assert finished_view(centrum.client)["result"]["result"] == result
    return Produced(_archive_file(centrum, tmp_path), ("--efenix-dzis", TODAY.isoformat()))


# Strona zlecenia Wykonawcy z drugiego wiersza bez przycisku Emmetta: okno efenix staje na elemencie, którego szukało.
_EMMETT_GONE = [IN_EFENIX[0], replace(PRICED[1].in_efenix("642"), changed=Changed.EMMETT_BUTTON)]

# Logi, które wiele testów odtwarza albo zmienia w kopii w swoim ``tmp_path``, wyprodukowane raz na moduł i worker:
# produkcja Wyceny to okno w Chromium na Atrapie efenix (~2,3 s). Logi z innymi parametrami są osobnym wpisem.
SHARED: Final[dict[str, Callable[[Path], Produced]]] = {
    "settlement": _settlement,
    "efenix": _efenix,
    "efenix_bez_emmetta": lambda folder: _efenix(folder, _EMMETT_GONE, "BLAD_KRYTYCZNY"),
}


def _fingerprint(folder: Path) -> dict[str, str]:
    return {
        path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "folder"
        for path in folder.rglob("*")
    }


@pytest.fixture(scope="module")
def _shared_store() -> dict[str, tuple[Produced, dict[str, str]]]:
    return {}


@pytest.fixture
def shared_logs(
    _shared_store: dict[str, tuple[Produced, dict[str, str]]], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Callable[[str], Produced]]:
    """Logi z ``SHARED`` po nazwie, wyprodukowane w pierwszym teście modułu, który o nie prosi, więc pod strażami z
    conftest (reguła prywatności Centrum, bez GitHuba). Test, po którym folder wspólnych Logów różni się od folderu zaraz
    po produkcji, pada: zmiany idą do kopii w ``tmp_path`` testu, bo inaczej następny test odtwarzałby cudze Logi."""

    handed: set[str] = set()

    def logs(name: str) -> Produced:
        if name not in _shared_store:
            produced = SHARED[name](tmp_path_factory.mktemp(name))
            _shared_store[name] = (produced, _fingerprint(produced.archived.parent))
        handed.add(name)
        return _shared_store[name][0]

    yield logs
    changed = [name for name in sorted(handed) if _fingerprint(_shared_store[name][0].archived.parent) != _shared_store[name][1]]
    assert changed == [], f"test zmienił folder wspólnych Logów {changed}; zmieniaj kopię w tmp_path testu"


def _archived_run(fake: FakeReportBox, folder: Path, run_id: str) -> Path:
    """Plik Logów Uruchomienia ``run_id`` z Archiwum Logów okresu fałszywej Skrzynki, spakowany gzipem."""

    def arrived(box: FakeReportBox) -> bool:
        return any(run_id in asset.name for archive in box.archives for asset in archive.assets)

    assert fake.wait_until(arrived), f"plik Logów {run_id} nie doszedł do Archiwum"
    [asset] = [asset for archive in fake.archives for asset in archive.assets if run_id in asset.name]
    path = folder / asset.name
    path.write_bytes(asset.data)
    return path


# Wpisanie raportów, drugie kliknięcie: tata kliknął w poniedziałek 9.11 (Raporty Jana: telefon w czynnościach, numer
# zlecenia z zerem na początku), a we wtorek rano Anna przysyła Raporty za 9.11 do pustych komórek i do zlecenia z
# ręcznym „nie” w SKUTECZNE, Jan numer spoza swoich zleceń, a obce adresy Raporty za 9.11: dwa różne adresy z jednym
# Message-ID (dwa problemy) i jeden adres dwa razy z innym (jeden problem), a Jan poprawia opis swojego wpisu z
# poniedziałku (#1230). Dwóch maili skrzynka nie umiała przeczytać.
_SUCCESSFUL = FIRST + HEADERS.index("SKUTECZNE")
_REPORTED_DAY = "Raport 09.11.2026"
REPORTED = Intermax(
    ordered=(
        Order(datetime(2026, 11, 9, 9), "jan.testowy", 40000001, cells=((NUMBER, 40000001),)),
        Order(datetime(2026, 11, 9, 10), "jan.testowy", 4000005, cells=((NUMBER, "04000005"),)),
        Order(datetime(2026, 11, 9, 11), "anna.kowalska", 40000002, cells=((NUMBER, 40000002),)),
        Order(datetime(2026, 11, 9, 12), "anna.kowalska", 40000006, cells=((NUMBER, 40000006), (_SUCCESSFUL, "nie"))),
    ),
    raw=(),
)
JAN_REPORTS = [
    report(SENDERS["jan.testowy"], _REPORTED_DAY, "40000001 tak wymiana, tel. 600 100 200"),
    report(SENDERS["jan.testowy"], _REPORTED_DAY, "04000005 nie brak klienta", at=datetime(2026, 11, 9, 17)),
]
NEXT_MORNING = [
    *JAN_REPORTS,
    report(SENDERS["anna.kowalska"], _REPORTED_DAY, "40000002 tak montaż", at=datetime(2026, 11, 10, 7, 50)),
    report(SENDERS["anna.kowalska"], _REPORTED_DAY, "40000006 tak montaż anteny", at=datetime(2026, 11, 10, 7, 51)),
    report(SENDERS["jan.testowy"], _REPORTED_DAY, "40000099 tak wymiana", at=datetime(2026, 11, 10, 7, 52)),
    report("obcy@przyklad.invalid", _REPORTED_DAY, "40000002 nie brak", at=datetime(2026, 11, 10, 7, 53), message_id="<a@x>"),
    report("inny@przyklad.invalid", _REPORTED_DAY, "40000002 nie brak", at=datetime(2026, 11, 10, 7, 53), message_id="<a@x>"),
    report("trzeci@przyklad.invalid", _REPORTED_DAY, "40000001 nie", at=datetime(2026, 11, 10, 7, 54), message_id="<b@x>"),
    report("trzeci@przyklad.invalid", _REPORTED_DAY, "40000001 nie", at=datetime(2026, 11, 10, 7, 54), message_id="<b@x>"),
    report(SENDERS["jan.testowy"], _REPORTED_DAY, "04000005 nie klient nieobecny", at=datetime(2026, 11, 10, 7, 55)),
]


def _report_entering(tmp_path: Path, *, memory_saved: bool = True) -> Produced:
    """Logi drugiego kliknięcia Wpisania raportów (``memory_saved``: pamięć wpisów zapisała się po kliknięciu)."""

    surroundings = Surroundings()
    centrum = entering_centrum(tmp_path, REPORTED, JAN_REPORTS, surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path))
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    centrum.moment.append(datetime(2026, 11, 10, 8))
    centrum.fake_inbox.outcome = NEXT_MORNING
    centrum.fake_inbox.skipped = 2
    if not memory_saved:
        state = centrum.tool.config / REPORT_ENTERING_STATE

        def unwritable() -> None:
            state.unlink()
            state.mkdir()

        centrum.fake_inbox.during = unwritable
    second = centrum.run_to_end()
    assert second["result"]["ending"] == "finished"
    produced = Produced(_archived_run(surroundings.report_box, tmp_path, second["run"]["id"]), ())
    problems = [problem["kind"] for problem in produced.record["report_entering"]["problems"]]
    assert problems == ["unknown_sender"] * 3 + ["manual_difference"], problems
    added = [(found["number"], found["worker"]) for found in produced.record["report_entering"]["added"]]
    assert added == [(40000099, "jan.testowy")], "nowy numer Jana z 8 cyframi to Zlecenie dopisane z raportu (#1354)"
    assert "klient nieobecny" in [change["value"] for change in produced.record["report_entering"]["changes"]]
    assert produced.record["report_entering"]["skipped"] == 2
    return produced


PROCESSES = {
    "settlement": _settlement,
    "preparation": _preparation,
    "intermax": _intermax,
    "efenix": _efenix,
    "report_entering": _report_entering,
}
_CONFIGURATION = "- Lista Wykonawców i Wzorce nie są w Logach"
# Granice zgodnego odtworzenia Logów każdego procesu, po kolei (początek linii pod „Granice:”): to, czego Logi tego
# procesu nie niosą, bez braków w folderze Konfiguracji i arkusza, w którym odtworzenie nie wie, gdzie stały ADRES i
# NUMER UMOWY. Maski strażnika są tylko przy Wpisaniu raportów: Raport Jana i jego wiersz INTERMAX mają telefon.
ALWAYS = {
    "settlement": (_CONFIGURATION,),
    "preparation": ("- Surowe zlecenia na dole arkuszy Rejestru zleceń", "- folderu okresów taty Logi nie mają", _CONFIGURATION),
    "intermax": ("- dni uporządkowane nad wklejeniem nie są w Kopii wejścia", "- kolumn z aplikacji za UWAGI nie ma w Kopii"),
    "efenix": ("- efenix to Atrapa efenix z odczytów stron w Logach, a nie efenix taty",),
    "report_entering": (
        "- Kopia wejścia ma maski strażnika reguły danych ([telefon] ×1)",
        "- maili taty Logi nie mają",
        "- Wpisy raportu w Logach mają maski strażnika reguły danych ([telefon] ×1)",
    ),
}


@pytest.mark.parametrize("process", PROCESSES)
def test_logi_z_archiwum_kazdego_procesu_odtwarzaja_sie_z_tym_samym_wynikiem_i_sladem(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str], process: str
) -> None:
    """Plik z Archiwum Logów okresu, który wyprodukowało Uruchomienie procesu z Centrum, odtwarza się na tym kodzie z
    tymi samymi wynikiem, Komunikatami, podsumowaniem, etapami i śladem (Szablony pracownika, Wpisy INTERMAX z
    wierszami dnia, ślad zleceń efenix z odczytem każdej strony), a pliki, które odtworzenie zapisuje, zostają w jego
    katalogu roboczym, także rekord metryk: historii metryk narzędzia odtworzenie nie dopisuje. Pod „Granice:” stoi
    tylko to, czego Logi procesu nie niosą, a Konfiguracja z folderu taty nie ma braków ani innego rozmiaru."""

    produced = shared_logs(process) if process in SHARED else PROCESSES[process](tmp_path / "taty")
    record = produced.record
    kept = tmp_path / "odtworzenie"
    tool_metrics = CATALOG.metrics(record["process"]).path
    history = tool_metrics.read_bytes() if tool_metrics.exists() else None

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", "--zachowaj", kept, *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert lines[1] == f"Uruchomienie: {_title(record)}, {RunMode(record['mode']).word}, okres {record['period']}, {produced.archived.stem}"
    granice = lines[lines.index("Granice:") + 1 :]
    assert len(granice) == len(ALWAYS[process]) and all(map(str.startswith, granice, ALWAYS[process])), granice
    configuration = [line for line in granice if line.startswith(_CONFIGURATION)]
    assert [line for line in configuration if not line.endswith("a Logi mają tylko nazwę i rozmiar plików taty")] == []
    replayed = json.loads((kept / "odtworzone-logi.json").read_text(encoding="utf-8"))
    assert (replayed["process"], replayed["mode"], replayed["result"]) == (process, record["mode"], record["result"])
    trace = {
        "settlement": "templates",
        "preparation": "summary",
        "intermax": "intermax_entries",
        "efenix": "efenix_orders",
        "report_entering": "report_entering",
    }
    assert record[trace[process]], "ślad, który odtworzenie porównało, nie jest pusty"
    assert len((kept / "metryki.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert (tool_metrics.read_bytes() if tool_metrics.exists() else None) == history, "rekord w historii metryk narzędzia"
    if process == "intermax":
        assert record["intermax_entries"]["rows"], "wiersze dnia w śladzie"
        assert (kept / "Kopie INTERMAX" / INTERMAX_COPY).is_file()
        assert not (intermax_copies.default_directory() / INTERMAX_COPY).exists(), "Kopia INTERMAX poza katalogiem odtworzenia"
    if process == "efenix":
        actions = {step["action"] for order in record["efenix_orders"] for step in order["steps"]}
        assert actions == {"szukanie", "otwarcie zlecenia", "data wykonania", "Wycena Emmetta", "ilość"}


def test_uruchomienie_na_ostatniej_dobrej_liscie_wykonawcow_odtwarza_sie_z_ostrzezeniem_startu_z_logow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Przebieg rozliczeń, który biegł na ostatniej dobrej Liście Wykonawców, bo plik dostał złą treść po odczycie
    Ustawień, ma ostrzeżenie startu w Logach jako fakt startu, a odtworzenie bierze je z Logów, bo Ustawień Centrum
    Logi nie mają: odtworzenie na folderze Konfiguracji z dobrą listą jest zgodne, a nie różne na samym ostrzeżeniu."""

    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    assert centrum.client.get("/api/settings").json()["workers"]["state"] == "good"
    good = centrum.tool.worker_list.read_bytes()
    centrum.tool.worker_list.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8")
    assert run_to_end(centrum, dry_run=True)["result"]["result"] == "OK"
    produced = Produced(_archive_file(centrum, tmp_path), ("--konfiguracja", str(tmp_path / "config")))
    centrum.tool.worker_list.write_bytes(good)
    logged = [(message["code"], message.get("at_start")) for message in produced.record["messages"]]
    assert logged == [("LISTA_WYKONAWCOW_OSTATNIA_DOBRA", True)], logged

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


@pytest.mark.parametrize(
    ("pricing", "change", "replayed_pricing"),
    [
        ("z Przekazaniem", lambda record: None, "z Przekazaniem"),
        ("bez Przekazania", lambda record: record.pop("pricing"), "bez Przekazania"),
    ],
    ids=["z_przekazaniem", "logi_sprzed_trybow"],
)
def test_logi_wyceny_w_efenix_odtwarzaja_sie_w_trybie_z_logow_a_sprzed_trybow_bez_przekazania(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str], pricing: str, change: Callable[[dict[str, Any]], None], replayed_pricing: str
) -> None:
    """Wycena w efenix z Przekazaniem do akceptacji odtwarza się w tym trybie, z tym samym śladem zleceń, a Logi sprzed
    trybów (bez pola trybu) w trybie bez Przekazania, w którym wtedy biegła każda Wycena (ADR 0027)."""

    produced = shared_logs("efenix") if pricing == "bez Przekazania" else _efenix(tmp_path / "taty", pricing=pricing)
    logs = _changed(produced, tmp_path, change)
    kept = tmp_path / "odtworzenie"

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie", "--zachowaj", kept, *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    replayed = json.loads((kept / "odtworzone-logi.json").read_text(encoding="utf-8"))
    assert replayed["pricing"] == replayed_pricing


def _title(record: dict[str, Any]) -> str:
    return {
        "settlement": "Przebieg rozliczeń",
        "preparation": "Przygotowanie pliku zbiorczego",
        "intermax": "Uporządkowanie INTERMAX",
        "efenix": "Wycena w efenix",
        "report_entering": "Wpisanie raportów",
    }[record["process"]]


@pytest.mark.parametrize(("answer", "ending"), [("abort", "declined"), ("continue", "finished")])
def test_odtworzenie_odpowiada_w_decyzji_taty_tak_jak_tata_w_logach(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], answer: str, ending: str
) -> None:
    """Przygotowanie okresu bez zleceń z ostatnich dni pyta tatę, czy przygotować plik; odtworzenie odpowiada tak, jak
    tata odpowiedział w Logach: po odmowie to samo Zatrzymanie po odmowie z tym samym Komunikatem, po zgodzie ten sam
    Plik zbiorczy."""

    folder = tmp_path / "taty"
    folder.mkdir()
    centrum = preparing_centrum(folder, incomplete_period_rows())
    write_report_key(ToolDirectory(folder))
    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]
    centrum.client.post(f"/api/runs/{waiting['run']['id']}/decision", json={"answer": answer})
    finished_view(centrum.client)
    produced = Produced(_archive_file(centrum, folder), ("--konfiguracja", str(folder / "config")))
    assert produced.record["ending"] == ending

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def _cell_with_phone(record: dict[str, Any]) -> None:
    [sheet] = record["input_copy"][0]["sheets"]
    sheet["rows"][0]["cells"]["A"] += " [telefon]"


def _other_cell(record: dict[str, Any]) -> None:
    [sheet] = record["input_copy"][0]["sheets"]
    sheet["rows"][0]["cells"]["A"] = {"type": "other", "text": "CellRichText"}


def _other_config_size(record: dict[str, Any]) -> None:
    record["environment"]["files"] = [{"name": WORKERS_FILE, "size": 1, "online_only": None}]


# Granica Logów: zmiana pliku Logów Przebiegu, folder Konfiguracji (``None``: folder Centrum taty), kod wyjścia i linia
# raportu (pierwsza przy granicy blokującej, a przy zastrzeżeniu linia pod „Granice:”, która się nią zaczyna).
LIMITS = {
    "urwane_uruchomienie": (
        lambda record: record.update(ending="interrupted"),
        None,
        3,
        "NIE DA SIĘ ODTWORZYĆ: to Logi Urwanego Uruchomienia: Centrum zgasło w trakcie, a Logi z dziennika Wyceny nie mają "
        "Kopii wejścia ani wyniku do porównania",
    ),
    "pusta_kopia_wejscia": (
        lambda record: record.update(input_copy=[]),
        None,
        3,
        "NIE DA SIĘ ODTWORZYĆ: Kopia wejścia jest pusta: Uruchomienie skończyło się przed odczytem plików taty, więc nie "
        "wiadomo, jakie pliki zastało",
    ),
    "komorka_spoza_kopii": (
        _other_cell,
        None,
        3,
        "NIE DA SIĘ ODTWORZYĆ: Kopia wejścia nie zapisała wartości 1 komórek (typ spoza Kopii, np. Sheet1 A18), więc "
        "odtworzone pliki ich nie mają",
    ),
    "naglowki_poza_wierszem_17": (
        lambda record: record["input_copy"][0]["sheets"][0].update(header_row=1),
        None,
        3,
        "NIE DA SIĘ ODTWORZYĆ: Kopia Pliku zbiorczego nie ma jednego arkusza z nagłówkami w wierszu 17",
    ),
    "bez_folderu_konfiguracji": (lambda record: None, "nie-ma", 3, "NIE DA SIĘ ODTWORZYĆ: nie ma folderu z Listą Wykonawców"),
    "maska_strazinka_w_kopii": (
        _cell_with_phone,
        None,
        0,
        "- Kopia wejścia ma maski strażnika reguły danych ([telefon] ×1): odtworzenie czyta maskę w miejscu wartości taty",
    ),
    "inny_rozmiar_konfiguracji": (_other_config_size, None, 0, _CONFIGURATION),
    "logi_bez_regul_ilosci": (
        lambda record: record.update(quantity_rules=None),
        None,
        0,
        "- Logi nie mają Reguł ilości Uruchomienia (Logi sprzed ich zapisu), więc odtworzenie liczy Regułami ilości z "
        "Wydania tego drzewa",
    ),
    "maska_strazinka_w_regulach_ilosci": (
        lambda record: record["quantity_rules"].update(rules=record["quantity_rules"]["rules"].replace("z-opisu", "[telefon]", 1)),
        None,
        3,
        "NIE DA SIĘ ODTWORZYĆ: Reguły ilości w Logach mają maski strażnika reguły danych ([telefon])",
    ),
    "reguly_ilosci_innego_zapisu": (
        lambda record: record["quantity_rules"].update(rules=record["quantity_rules"]["rules"].replace('"schema_version":1', '"schema_version":2')),
        None,
        3,
        "NIE DA SIĘ ODTWORZYĆ: Reguł ilości z Logów nie da się odczytać (schema_version: Plik ma inną wersję zapisu niż 1.)",
    ),
}


@pytest.mark.parametrize("case", LIMITS)
def test_granica_logow_jest_w_raporcie_a_blokujaca_konczy_odtworzenie_bez_zgodnosci(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Czego Logi nie niosą, raport mówi: Urwane Uruchomienie, pusta Kopia wejścia, komórka typu spoza Kopii, Kopia
    Pliku zbiorczego z nagłówkami poza wierszem 17 i brak folderu Konfiguracji kończą odtworzenie bez uruchomienia
    procesu (kod 3), a maska strażnika w Kopii i Konfiguracja innego rozmiaru niż u taty stoją pod „Granice:” przy
    zgodnym odtworzeniu."""

    change, folder, expected_code, expected = LIMITS[case]
    produced = shared_logs("settlement")
    changed = _changed(produced, tmp_path, change)
    configuration = produced.archived.parent / "config" if folder is None else tmp_path / folder

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", "--konfiguracja", configuration)

    assert code == expected_code, lines
    if expected_code == 3:
        assert lines[0].startswith(expected) and not any(line.startswith("Pierwsza różnica") for line in lines), lines
    else:
        assert lines[0] == "ODTWORZENIE ZGODNE"
        granice = lines[lines.index("Granice:") + 1 :]
        assert [line for line in granice if line.startswith(expected)], granice
    if case == "inny_rozmiar_konfiguracji":
        size = (configuration / WORKERS_FILE).stat().st_size
        assert any(line.endswith(f"inny rozmiar niż u taty: {WORKERS_FILE}: u taty 1 B, tu {size} B") for line in lines)


@dataclass(frozen=True)
class _EditedRulesRun:
    """Uruchomienie procesu, który liczy Regułami ilości, po regule zapisanej przez tatę w edytorze, i skutek tej reguły
    w wyniku odtworzenia (``kept``: katalog roboczy odtworzenia), którego Reguły ilości z Wydania nie dają."""

    produced: Produced
    effect: Callable[[Path], object]
    expected: object


_LEAVE_V_EMPTY_AT_NOKIA = {
    "scope": "every",
    "conditions": [{"kind": "devices", "mode": "contains", "text": "nokia", "negated": False}],
    "action": {"kind": "leave_empty", "columns": ["V"]},
}
_AA_3_AT_ROUTER = {
    "scope": "known",
    "conditions": [{"kind": "group", "group": "router", "negated": False}],
    "action": {"kind": "fill", "writes": [{"column": "AA", "value": 3, "multiplier": "once", "component": None}]},
}


def _settlement_with_edited_rule(folder: Path) -> _EditedRulesRun:
    """Przebieg rozliczeń po regule „zostaw V pustą w Rozliczeniu pracownika” przy „nokia”: V czyści się tylko dla
    INEA, czego Reguły ilości z Wydania nie robią."""

    centrum = settling_centrum(folder)
    write_quantity_source(centrum.collective_file, [{"C": "pr", "D": "nokia", "G": datetime(2026, 9, 9, 12), "V": 1, "Z": 1}])
    write_report_key(ToolDirectory(folder))
    assert centrum.client.post("/api/settings/quantity-rules", json=_LEAVE_V_EMPTY_AT_NOKIA).status_code == 200
    run_to_end(centrum, dry_run=True)
    produced = Produced(_archive_file(centrum, folder), ("--konfiguracja", str(folder / "config")))
    assert produced.record["inea_only_cleared"] == {"AK": 0, "AP": 0, "V": 1}

    def cleared(kept: Path) -> object:
        return json.loads((kept / "odtworzone-logi.json").read_text(encoding="utf-8"))["inea_only_cleared"]

    return _EditedRulesRun(produced, cleared, {"AK": 0, "AP": 0, "V": 1})


def _preparation_with_edited_rule(folder: Path) -> _EditedRulesRun:
    """Przygotowanie pliku zbiorczego po regule „przy routerze wpisz 3 w AA”: kolumny AA Reguły ilości z Wydania nie
    wypełniają."""

    centrum = preparing_centrum(folder, [{**register_order(1, PERIOD_MONDAY), "URZĄDZENIA": "nokia zte"}])
    write_report_key(ToolDirectory(folder))
    assert centrum.client.post("/api/settings/quantity-rules", json=_AA_3_AT_ROUTER).status_code == 200
    run_to_end(centrum, dry_run=False)
    collective = centrum.fixture.collective_file_path
    produced = Produced(_archive_file(centrum, folder), ("--konfiguracja", str(folder / "config")))

    assert _quantity(collective, "AA18") == 3, "Przygotowanie u taty wpisało regułę z edytora"
    return _EditedRulesRun(produced, lambda kept: _quantity(kept / "okresy" / collective.parent.name / collective.name, "AA18"), 3)


def _quantity(collective: Path, cell: str) -> object:
    workbook = load_workbook(collective, read_only=True)
    try:
        return workbook.worksheets[0][cell].value
    finally:
        workbook.close()


# Każdy proces, który liczy Regułami ilości ze startu (``ProcessKind.quantity_rules``), z regułą taty z edytora.
EDITED_RULES_RUNS: dict[str, Callable[[Path], _EditedRulesRun]] = {
    "settlement": _settlement_with_edited_rule,
    "preparation": _preparation_with_edited_rule,
}


def test_kazdy_proces_liczacy_regulami_ilosci_ze_startu_ma_tu_uruchomienie_z_regula_z_edytora() -> None:
    assert set(EDITED_RULES_RUNS) == {kind.key for kind in KINDS if kind.quantity_rules}


@pytest.mark.parametrize("process", EDITED_RULES_RUNS)
def test_odtworzenie_procesu_liczy_regulami_ilosci_taty_z_logow_i_jest_zgodne(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], process: str
) -> None:
    """Tata zapisał regułę w edytorze, a proces liczył nią w Uruchomieniu; odtworzenie z Logów liczy Regułami ilości z
    chwili Uruchomienia, nie regułami z Wydania, więc ma skutek reguły taty, jest zgodne i nie ma granicy o Logach
    bez Reguł ilości."""

    folder = tmp_path / "taty"
    folder.mkdir()
    run = EDITED_RULES_RUNS[process](folder)
    kept = tmp_path / "odtworzenie"

    code, lines = _replayed(capsys, run.produced.archived, "--na-tym-drzewie", "--zachowaj", kept, *run.produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert [line for line in lines if "Reguł ilości" in line] == []
    assert run.effect(kept) == run.expected


def test_odtworzenie_przygotowania_liczy_lista_urzadzen_taty_z_logow_i_jest_zgodne(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tata dopisał zapis „ont nokia” do składnika „nokia” w sekcji Urządzenia, a Przygotowanie wpisało nim Z; odtworzenie
    z Logów liczy Listą Urządzeń z chwili Uruchomienia, nie listą z Wydania, więc wpisuje to samo i jest zgodne."""

    folder = tmp_path / "taty"
    folder.mkdir()
    centrum = preparing_centrum(folder, [{**register_order(1, PERIOD_MONDAY), "URZĄDZENIA": "ont nokia"}])
    write_report_key(ToolDirectory(folder))
    nokia = next(device for device in centrum.client.get("/api/settings/quantity-rules").json()["devices"] if device["id"] == "nokia")
    form = {**nokia, "other_spellings": [*nokia["other_spellings"], "ont nokia"]}
    del form["id"]
    assert centrum.client.put("/api/settings/devices/nokia", json=form).status_code == 200
    run_to_end(centrum, dry_run=False)
    collective = centrum.fixture.collective_file_path
    produced = Produced(_archive_file(centrum, folder), ("--konfiguracja", str(folder / "config")))
    kept = tmp_path / "odtworzenie"

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", "--zachowaj", kept, *produced.arguments)

    assert _quantity(collective, "Z18") == 1, "Przygotowanie u taty liczyło zapisem z sekcji Urządzenia"
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert _quantity(kept / "okresy" / collective.parent.name / collective.name, "Z18") == 1


# Proces i jego nazwa w granicy Kopii wejścia z innej liczby plików niż jeden plik taty, który czyta.
ONE_FILE = {
    "settlement": "proces",
    "preparation": "Przygotowanie pliku zbiorczego",
    "intermax": "Uporządkowanie INTERMAX",
    "efenix": "proces",
    "report_entering": "Wpisanie raportów",
}


@pytest.mark.parametrize("process", PROCESSES)
def test_kopia_wejscia_z_dwoma_plikami_konczy_odtworzenie_granica_procesu_jednego_pliku(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str], process: str
) -> None:
    """Każdy proces czyta jeden plik taty, więc Logi z Kopią wejścia z dwoma plikami (ten sam plik drugi raz) nie
    odtwarzają się: kod 3 z granicą, która nazywa liczbę plików i proces, bez uruchomienia procesu."""

    produced = shared_logs(process) if process in SHARED else PROCESSES[process](tmp_path / "taty")
    changed = _changed(produced, tmp_path, lambda record: record["input_copy"].append(record["input_copy"][0]))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (3, f"NIE DA SIĘ ODTWORZYĆ: Kopia wejścia ma 2 pliki, a {ONE_FILE[process]} czyta jeden"), lines


def test_folder_konfiguracji_bez_listy_wykonawcow_raport_nazywa_brakujacy_plik(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Folder Konfiguracji z Wzorcami, a bez Listy Wykonawców: raport mówi pod „Granice:”, którego pliku w nim
    nie ma, bo bez niego Przebieg rozliczeń kończy się inaczej niż u taty."""

    produced = shared_logs("settlement")
    folder = tmp_path / "bez-konfiguracji-wykonawcow"
    shutil.copytree(produced.archived.parent / "config", folder)
    (folder / WORKERS_FILE).unlink()

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", "--konfiguracja", folder)

    [configuration] = [line for line in lines if line.startswith(_CONFIGURATION)]
    assert (code, configuration.endswith(f"; w folderze nie ma: {WORKERS_FILE}")) == (1, True), lines


def test_odtworzenie_bez_folderu_konfiguracji_mowi_ze_folderu_nie_podano(tmp_path: Path, shared_logs: Callable[[str], Produced]) -> None:
    """Bez folderu Konfiguracji (narzędzie nie ma domyślnego, gdy główny checkout nie ma ``config/``) odtworzenie
    Przebiegu rozliczeń nie biegnie, a granica mówi, że folderu nie podano."""

    record = RunLog.model_validate(shared_logs("settlement").record)

    report = replay(record, work=tmp_path / "odtworzenie", configuration=None)

    assert report.lines(record, "kod")[0] == (
        "NIE DA SIĘ ODTWORZYĆ: nie ma folderu z Listą Wykonawców i Wzorcami (brak, --konfiguracja): Logi ich nie "
        "niosą, a proces bez nich nie biegnie"
    )


def test_arkusz_kopii_bez_naglowkow_daje_granice_o_kolumnach_adres_i_numer_umowy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Arkusz Kopii wejścia INTERMAX bez nagłówków: odtworzenie nie wie, w których kolumnach stały ``ADRES`` i
    ``NUMER UMOWY``, więc raport mówi to pod „Granice:” przy różnicy w Kopii wejścia (Uporządkowanie nie czyta arkusza
    bez nagłówków), a nie kończy się wyjątkiem."""

    produced = _intermax(tmp_path / "taty")

    def without_headers(record: dict[str, Any]) -> None:
        record["input_copy"][0]["sheets"].append({"sheet": "Bez nagłówków", "header_row": 1, "columns": {}, "rows": [], "empty_rows": []})

    changed = _changed(produced, tmp_path, without_headers)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie")

    assert (code, lines[3].startswith("Pierwsza różnica: Kopia wejścia (input_copy)")) == (1, True), lines
    assert "- arkusz Bez nagłówków: nie wiem, gdzie stały kolumny ADRES i NUMER UMOWY" in lines[lines.index("Granice:") + 1 :]


def test_odtworzony_rejestr_ma_w_adresie_i_numerze_umowy_wartosci_syntetyczne_swojego_wiersza(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kopia wejścia nie ma ``ADRES`` ani ``NUMER UMOWY`` Rejestru zleceń, więc odtworzony Rejestr w katalogu
    odtworzenia ma w nich w każdym wierszu Kopii wartość syntetyczną z numerem tego wiersza, której żaden plik taty nie
    ma."""

    produced = _preparation(tmp_path / "taty")
    kept = tmp_path / "odtworzenie"

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", "--zachowaj", kept, *produced.arguments)

    [register] = (kept / "rejestr").rglob("*.xlsx")
    workbook = load_workbook(register)
    found, expected = [], []
    for sheet in produced.record["input_copy"][0]["sheets"]:
        created = workbook[sheet["sheet"]]
        headers = {cell.value: cell.column for cell in created[sheet["header_row"]] if cell.value in ("ADRES", "NUMER UMOWY")}
        for row in sheet["rows"]:
            found.append((created.cell(row["row"], headers["ADRES"]).value, created.cell(row["row"], headers["NUMER UMOWY"]).value))
            expected.append((SYNTHETIC_ADDRESS.format(row=row["row"]), SYNTHETIC_ORANGE.format(row=row["row"])))
    workbook.close()
    assert (code, len(found) > 1, found) == (0, True, expected), lines


def test_powtorka_zatrzymania_porownuje_sie_jak_zatrzymanie_dla_taty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Powtórka zależy od poprzedniego Zatrzymania w tej samej pracy Centrum, której odtworzenie nie ma: Zatrzymanie
    dla taty odtworzenia (wklejenie INTERMAX z dwóch dni) zgadza się z Powtórką w Logach, a raport to mówi."""

    produced = _intermax(tmp_path / "taty", Intermax(raw=(PASTED[0], replace(PASTED[1], when=datetime(2026, 10, 27, 9)))))
    assert produced.record["stop_kind"] == "for_tata"
    repeated = _changed(produced, tmp_path, lambda record: record.update(stop_kind="repeated"))

    code, lines = _replayed(capsys, repeated, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert "- Powtórka zależy od poprzedniego Zatrzymania w tej samej pracy Centrum: odtworzenie porównuje ją jak " "Zatrzymanie dla taty" in lines


def test_zatrzymanie_okna_efenix_jest_granica_przy_roznicy_odtworzenia_na_atrapie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Okno efenix staje na stronie zlecenia, której budowa jest inna niż ta, którą zna (pole Ilość z ułamkiem); Atrapa
    z odczytów stron w Logach jej nie ma, więc odtworzenie różni się od Logów, a raport nazywa tę granicę i przyczynę z
    Logów: zlecenie z miejscem w przebiegu i wyjątek okna (#976)."""

    stopped = [IN_EFENIX[0], replace(PRICED[1].in_efenix("642"), changed=Changed.QUANTITY_VALUE)]
    produced = _efenix(tmp_path / "taty", stopped, "BLAD_KRYTYCZNY")
    assert produced.record["efenix_stop"] is not None

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert (
        "- Zatrzymanie okna efenix (wartość pola Ilość, która nie jest liczbą całkowitą) zależy od strony efenix taty: na "
        "Atrapie się nie powtórzy"
    ) in lines
    [cause] = [line for line in lines if line.startswith("Przyczyna w Logach: ")]
    assert cause.startswith(
        "Przyczyna w Logach: okno efenix przy wierszu 19 (2 z 6): wartość pola Ilość, która nie jest liczbą całkowitą; "
        "wyjątki rozliczenia.message.StopError ← rozliczenia.efenix_window.UnexpectedPage"
    ), cause


_WINDOW_CHAIN = "rozliczenia.message.StopError ← rozliczenia.efenix_window.UnexpectedPage"


def test_przyczyna_zatrzymania_okna_ma_element_strony_a_wyjatek_bez_ramek_nie_ma_miejsca_powstania(
    shared_logs: Callable[[str], Produced],
) -> None:
    """Przyczyna w Logach nazywa element strony, którego okno efenix nie znalazło dokładnie raz, i miejsce w kodzie
    okna, w którym powstał jego wyjątek; Logi, w których wyjątek okna nie ma ramek śladu wywołań, mają przyczynę bez
    tego miejsca (#976). Linię przyczyny w raporcie narzędzia sprawdza test Zatrzymania okna przy różnicy odtworzenia."""

    record = shared_logs("efenix_bez_emmetta").record
    cause = record["efenix_stop"]["cause"]
    without = copy.deepcopy(record)
    without["trace"]["causes"][0]["frames"] = []

    shown = [stop_cause(RunLog.model_validate(logs)) or "" for logs in (record, without)]

    stopped = f"okno efenix przy wierszu 19 (2 z 6): {cause['what']} ({cause['element']}); wyjątki {_WINDOW_CHAIN}"
    assert (cause["element"], shown[0].startswith(f"{stopped}, powstał w src/rozliczenia/efenix_browser.py:")) == ("#button_emmett", True), shown
    assert shown[1] == stopped


def test_porownanie_zatrzymania_okna_efenix_pomija_czasy_krokow_a_nie_przyczyne(shared_logs: Callable[[str], Produced]) -> None:
    """Zatrzymanie okna efenix w Logach i w odtworzeniu różni się przyczyną (innym elementem strony), a nie czasami
    kroków przy zleceniu; tak samo Zatrzymanie przy starcie okna, które nie ma zlecenia ani działania, które zawiodło."""

    record = shared_logs("efenix_bez_emmetta").record
    element = record["efenix_stop"]["cause"]["element"]

    def stopped(*, other_element: bool = False, later: bool = False, at_start: bool = False) -> RunLog:
        changed = copy.deepcopy(record)
        stop = changed["efenix_stop"]
        if other_element:
            stop["cause"]["element"] = "#inny_element"
        if later:
            for step in [*stop["steps"], stop["failed"]]:
                step.update(started_at="2026-11-11T23:59:00Z", duration_ms=step["duration_ms"] + 1000)
        if at_start:
            stop.update(row=None, order=None, orders=None, steps=[], failed=None)
        return RunLog.model_validate(changed)

    other = Difference("Zatrzymanie okna efenix (efenix_stop).cause.element", element, "#inny_element")
    assert first_difference(stopped(), stopped(later=True)) is None
    assert first_difference(stopped(), stopped(other_element=True)) == other
    assert first_difference(stopped(at_start=True), stopped(at_start=True, other_element=True)) == other


def test_plik_ktory_nie_jest_plikiem_logow_konczy_sie_bledem_albo_granica(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pliku, którego nie ma, i pliku ``.gz``, który nie jest gzipem, narzędzie nie czyta (kod 2); JSON, który nie jest
    Logami Uruchomienia tego kodu, nie odtwarza się, a Logi bez commitu nie mają kopii commitu (kod 3)."""

    not_logs = tmp_path / "nie-logi.json"
    not_logs.write_text('{"schema_version": 2, "tool": {"wydanie": null, "commit": null}}', encoding="utf-8")
    not_gzip = tmp_path / "nie-gzip.json.gz"
    not_gzip.write_text("{}", encoding="utf-8")

    assert _replayed(capsys, tmp_path / "nie-ma.json", "--na-tym-drzewie")[0] == 2
    assert _replayed(capsys, not_gzip, "--na-tym-drzewie")[0] == 2
    code, lines = _replayed(capsys, not_logs, "--na-tym-drzewie")
    assert (code, lines[0].split(" (")[0]) == (3, "NIE DA SIĘ ODTWORZYĆ: plik nie jest Logami Uruchomienia w schemacie tego kodu")
    assert _replayed(capsys, not_logs) == (
        3,
        ["NIE DA SIĘ ODTWORZYĆ: Logi nie mają commitu narzędzia; odtwórz na kodzie tego checkoutu (--na-tym-drzewie)"],
    )


def test_plik_logow_ktorego_nie_ma_albo_nie_w_utf8_daje_blad_na_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Pliku Logów, którego nie ma, i pliku nie w UTF-8 narzędzie nie czyta: kod 2, a na stderr błąd, który mówi,
    czego brakuje albo czego nie dało się odczytać; stdout, na którym stoi raport, zostaje pusty."""

    missing = tmp_path / "nie-ma.json"
    other_encoding = tmp_path / "cp1250.json"
    other_encoding.write_bytes('{"tool": "łódź"}'.encode("cp1250"))

    shown = []
    for logs in (missing, other_encoding):
        code = odtworz_uruchomienie.main([str(logs), "--na-tym-drzewie"])
        captured = capsys.readouterr()
        shown.append((code, captured.out, captured.err))

    assert shown == [
        (2, "", f"BŁĄD: nie ma pliku Logów {missing}\n"),
        (2, "", "BŁĄD: nie da się odczytać pliku Logów cp1250.json: UnicodeDecodeError\n"),
    ]


@pytest.mark.parametrize("text", ["[]", '{"tool": {"commit": ""}}'], ids=["json_nie_obiekt", "pusty_commit"])
def test_logi_bez_commitu_w_innej_postaci_nie_maja_kopii_commitu(tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str) -> None:
    """JSON, który nie jest obiektem, i pusty commit narzędzia to też Logi bez commitu: kod 3 z podpowiedzią
    ``--na-tym-drzewie``, a nie wyjątek ani szukanie pustego commitu."""

    logs = tmp_path / "logi.json"
    logs.write_text(text, encoding="utf-8")

    assert _replayed(capsys, logs) == (
        3,
        ["NIE DA SIĘ ODTWORZYĆ: Logi nie mają commitu narzędzia; odtwórz na kodzie tego checkoutu (--na-tym-drzewie)"],
    )


def test_odtworzenie_na_tym_drzewie_zachowuje_pliki_w_pustym_folderze_a_niepustego_nie_rusza(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """``--zachowaj`` przyjmuje folder, który już jest, gdy jest pusty, i zostawia w nim Logi odtworzenia, a folder
    z plikami odrzuca kodem 2 z błędem na stderr. Logi bez commitu narzędzia raport nazywa Logami z commitu
    nieznanego."""

    produced = shared_logs("settlement")
    logs = _changed(produced, tmp_path, lambda record: record["tool"].update(commit=None))
    kept = tmp_path / "odtworzenie"
    kept.mkdir()

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie", "--zachowaj", kept, *produced.arguments)
    again = odtworz_uruchomienie.main([str(logs), "--na-tym-drzewie", "--zachowaj", str(kept), *produced.arguments])
    shown = capsys.readouterr()

    assert (code, lines[0], lines[2].endswith("; Logi są z commitu nieznanego")) == (0, "ODTWORZENIE ZGODNE", True), lines
    assert (kept / "odtworzone-logi.json").is_file()
    assert (again, shown.out, shown.err) == (2, "", f"BŁĄD: folder {kept} nie jest pusty\n")


def _changed(produced: Produced, folder: Path, change: Any) -> Path:
    """Plik Logów z Archiwum po zmianie ``change`` (słownik Logów → nic), zapisany jako plik z dysku taty."""

    record = produced.record
    change(record)
    path = folder / produced.archived.stem
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_celowo_zmieniona_kopia_wejscia_daje_wydruk_pierwszej_roznicy_a_nie_zgodnosc(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Wiersz Kopii wejścia z innym Wykonawcą niż ten, z którego Przebieg rozliczeń policzył Logi: odtworzenie liczy z
    Kopii, więc pierwsza różnica to liczba zleceń Rozliczenia pracownika w podsumowaniu, z wartością w Logach i w
    odtworzeniu, a raport mówi, co porównał."""

    produced = shared_logs("settlement")

    def other_worker(record: dict[str, Any]) -> None:
        [sheet] = record["input_copy"][0]["sheets"]
        row = next(row for row in sheet["rows"] if row["cells"]["H"] == "adrian.testowy")
        row["cells"]["H"] = "dariusz.fikcyjny2"

    changed = _changed(produced, tmp_path, other_worker)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert code == 1
    assert lines[0] == "ODTWORZENIE RÓŻNE"
    assert lines[3:6] == [
        "Pierwsza różnica: podsumowanie (summary).worker_settlements[0: Wykonawca Adrian Testowy].orders",
        "  Logi:        2",
        "  Odtworzenie: 1",
    ]
    assert lines[6].startswith("Porównano: Kopia wejścia, wynik, zakończenie, Rodzaj Zatrzymania, Komunikaty")
    assert lines[7].startswith("Poza porównaniem: czasy i chwile kroków, odciski plików, środowisko")


def test_klikniecie_bez_raportow_wykonawcow_i_z_pamiecia_niezapisana_u_taty_odtwarza_sie_zgodnie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kliknięcie bez żadnego maila w skrzynce i drugie kliknięcie, po którym pamięci wpisów nie dało się zapisać na
    dysku taty: odtworzenie daje ten sam wynik, także ostrzeżenie o pamięci, choć Wpisów, z których wziąć Konfigurację
    wykonawców, i dysku taty nie ma."""

    surroundings = Surroundings()
    centrum = entering_centrum(tmp_path / "taty", REPORTED, (), surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    empty = centrum.run_to_end()
    unsaved = _report_entering(tmp_path / "taty-pamiec", memory_saved=False)
    assert [message["code"] for message in unsaved.record["messages"]] == ["RAPORTY_PAMIEC_NIEZAPISANA"]

    replayed = [
        _replayed(capsys, logs, "--na-tym-drzewie")
        for logs in (_archived_run(surroundings.report_box, tmp_path, empty["run"]["id"]), unsaved.archived)
    ]

    assert [(code, lines[0]) for code, lines in replayed] == [(0, "ODTWORZENIE ZGODNE")] * 2, replayed


def test_klikniecie_z_wpisami_numerow_z_wierszy_bez_zlecenia_odtwarza_sie_zgodnie_z_numerami_z_logow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#1354: Jan przysłał Wpisy numerów, które INTERMAX ma w wierszach bez zlecenia: Surowe zlecenie na dole arkusza,
    uporządkowany wiersz z ``DATA GODZ. POCZ.`` tekstem, uporządkowany wiersz bez ``WYKONAWCA`` i zlecenie z 8.11 sprzed
    dnia wdrożenia 9.11 (bez numeru w ``NUMER UMOWY`` i kolumnach z aplikacji, które strażnik reguły danych zna, więc
    numer Wpisu wychodzi do Logów), numeru zlecenia Anny, które INTERMAX ma też jako Surowe zlecenie, i nowego numeru.
    Logi mają numery z wierszy bez zlecenia (``orderless``, przy zleceniu sprzed okna z jego dniem) i dopisanie, a
    odtworzenie, którego Kopia wejścia ma tylko uporządkowane wiersze zleceń od 9.11, stawia numery z Logów na dole
    arkusza, więc nie dopisuje żadnego z nich, nie przenosi zlecenia Anny i daje ten sam wynik z tymi samymi powodami
    (#1374 r4)."""

    other = ((CONTRACT_NUMBER, "UM-surowe"), *((column, f"APP{column}") for column in range(LAST + 1, APP_LAST + 1)))
    raw = tuple(
        Order(datetime(2026, 11, 10, 9), "jan.testowy", number, cells=((NUMBER, number), *other))
        for number in (40000030, 40000031, 40000002)
    )
    earlier = Order(datetime(2026, 11, 8, 9), "jan.testowy", 40000000, cells=((NUMBER, 40000000), *other))
    text_date = Order(datetime(2026, 11, 9, 13), "jan.testowy", 40000033, cells=((NUMBER, 40000033), (DATE, "09.11.2026 13:00"), *other))
    no_worker = Order(datetime(2026, 11, 9, 14), "", 40000034, cells=((NUMBER, 40000034), *other))
    intermax = replace(REPORTED, ordered=(earlier, *REPORTED.ordered, text_date, no_worker), raw=raw)
    surroundings = Surroundings()
    text = "40000031 tak montaż\n40000032 nie brak klienta\n40000033 tak wymiana\n40000034 nie brak\n40000000 tak\n40000002 tak"
    mails = [report(SENDERS["jan.testowy"], _REPORTED_DAY, text)]
    centrum = entering_centrum(tmp_path / "taty", intermax, mails, surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    view = centrum.run_to_end()
    logs = _archived_run(surroundings.report_box, tmp_path, view["run"]["id"])
    entering = json.loads(gzip.decompress(logs.read_bytes()))["report_entering"]

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie")

    assert entering["orderless"] == [
        {"sheet": ORDER_SHEET, "number": 40000000, "day": "2026-11-08"},
        *({"sheet": ORDER_SHEET, "number": number, "day": None} for number in (40000002, 40000031, 40000033, 40000034)),
    ]
    assert [found["number"] for found in entering["added"]] == [40000032]
    assert entering["moves"] == []
    assert [(problem["kind"], problem["bar"]) for problem in entering["problems"]] == [
        ("unknown_number", "before_window"),
        ("repeated_number", None),
        *[("unknown_number", "in_intermax")] * 3,
    ]
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def test_klikniecie_po_zostaw_moja_odtwarza_sie_zgodnie_z_decyzja_z_logow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Po drugim kliknięciu tata klika „Zostaw moją” przy ręcznym ``nie`` Anny, więc trzecie kliknięcie nie ma różnicy:
    Logi mają decyzję z migawki kliknięcia, a odtworzenie bierze ją z nich i daje ten sam wynik bez różnicy (#1231)."""

    surroundings = Surroundings()
    centrum = entering_centrum(tmp_path / "taty", REPORTED, JAN_REPORTS, surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    centrum.moment.append(datetime(2026, 11, 10, 8))
    centrum.fake_inbox.outcome = NEXT_MORNING
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    view = centrum.client.get("/api/report-entering/view").json()
    [cell] = [
        problem["keep"]
        for worker in view["workers"]
        for day in worker["days"]
        for problem in day["problems"]
        if problem["keep"]
    ]
    assert centrum.client.post("/api/report-entering/keep", json=cell).status_code == 200
    third = centrum.run_to_end()
    logs = _archived_run(surroundings.report_box, tmp_path, third["run"]["id"])
    entering = json.loads(gzip.decompress(logs.read_bytes()))["report_entering"]

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie")

    assert [problem["kind"] for problem in entering["problems"]] == ["unknown_sender"] * 3
    assert entering["added"] == [], "40000099 dopisało drugie kliknięcie, a trzecie go nie dubluje (#1354)"
    assert [move["number"] for move in entering["moves_before"] if move["added"]] == [40000099]
    assert [(kept["number"], kept["column"], kept["value"]) for kept in entering["kept"]] == [(40000006, "SKUTECZNE", "tak")]
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


# Wpisanie raportów z dniami zamkniętymi i pomyłkami Wykonawców (#1229): tata kliknął w poniedziałek 9.11, potem
# przygotował Plik zbiorczy okresu 03_09_11_2026, a w środę 11.11 rano skrzynka ma Raport z 9.11 (okres zamknięty), Raport
# Jana z 11.11 z numerem jego zlecenia z 10.11, Raport Anny z numerem zlecenia Jana i Raport Jana z numerem, który stoi
# dwa razy w jego dniu.
MATCHED = Intermax(
    ordered=(
        Order(datetime(2026, 11, 9, 9), "jan.testowy", 40000001, cells=((NUMBER, 40000001),)),
        Order(datetime(2026, 11, 10, 9), "jan.testowy", 40000011, cells=((NUMBER, 40000011),)),
        Order(datetime(2026, 11, 10, 10), "anna.kowalska", 40000012, cells=((NUMBER, 40000012),)),
        Order(datetime(2026, 11, 10, 11), "jan.testowy", 40000013, cells=((NUMBER, 40000013),)),
        Order(datetime(2026, 11, 10, 12), "jan.testowy", 40000013, cells=((NUMBER, 40000013),)),
    ),
    raw=(),
)


def test_klikniecie_z_okresem_zamknietym_i_pomylkami_wykonawcow_odtwarza_sie_zgodnie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Logi mają tokeny okresów z Plikiem zbiorczym, a odtworzenie kładzie Plik zbiorczy każdego z nich w swoim folderze
    okresów: dni zamknięte, Przeniesienia zleceń między Janem i Anną (ADR 0029), zlecenie z innego dnia, którego nie
    wolno przenieść na dzień bez uporządkowanych zleceń (#1350), i numer dwa razy w dniu wychodzą tak samo jak u taty."""

    surroundings = Surroundings()
    centrum = entering_centrum(tmp_path / "taty", MATCHED, (), surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    folder = centrum.periods_directory / "03_09_11_2026"
    folder.mkdir()
    (folder / "Rozliczenie 03_09_11_2026 - zbiorcze.xlsx").write_bytes(b"syntetyczny Plik zbiorczy")
    jan, anna = SENDERS["jan.testowy"], SENDERS["anna.kowalska"]
    centrum.moment.append(datetime(2026, 11, 11, 8))
    centrum.fake_inbox.outcome = [
        report(jan, "Raport 09.11.2026", "40000001 tak wymiana", at=datetime(2026, 11, 10, 7)),
        report(jan, "Raport 11.11.2026", "40000011 tak wymiana", at=datetime(2026, 11, 11, 7)),
        report(anna, "Raport 10.11.2026", "40000011 tak montaż", at=datetime(2026, 11, 11, 7, 1)),
        report(jan, "Raport 10.11.2026", "40000013 tak montaż", at=datetime(2026, 11, 11, 7, 2)),
        report(jan, "Raport 10.11.2026", "40000012 nie brak klienta", at=datetime(2026, 11, 11, 7, 3)),
    ]
    second = centrum.run_to_end()
    archived = _archived_run(surroundings.report_box, tmp_path, second["run"]["id"])
    entering = json.loads(gzip.decompress(archived.read_bytes()))["report_entering"]
    assert entering["closed"] == ["03_09_11_2026"]
    assert [problem["kind"] for problem in entering["problems"]] == ["repeated_order", "refused_move"], entering["problems"]
    assert entering["problems"][1]["bar"] == "not_ordered"
    assert [(move["row"], move["worker"]) for move in entering["moves"]] == [(3, "anna.kowalska"), (5, "jan.testowy")]

    code, lines = _replayed(capsys, archived, "--na-tym-drzewie")

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def test_przeniesienie_po_recznej_zmianie_wykonawcy_odtwarza_sie_z_wpisami_centrum_pod_wykonawca_od_taty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Centrum wpisało Wpis Jana, tata dał zlecenie Annie, a kliknięcie bez nowych maili przeniosło własne wpisy
    Centrum pod klucz Anny (komórki idą z wierszem). Świeższy mail Jana przenosi zlecenie z powrotem i nadpisuje te
    komórki: Logi mają własne wpisy zlecenia także pod Anną, która nie przysłała Raportu, więc odtworzenie daje te same
    komórki, bez różnicy z ręczną wartością."""

    surroundings = Surroundings()
    jan = SENDERS["jan.testowy"]
    first = report(jan, "Raport 09.11.2026", "40000001 tak wymiana", at=datetime(2026, 11, 9, 17))
    centrum = entering_centrum(tmp_path / "taty", MATCHED, [first], surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    book = load_workbook(centrum.register)
    [row] = [cell.row for cell in book[ORDER_SHEET][get_column_letter(NUMBER)] if cell.value == 40000001]
    book[ORDER_SHEET].cell(row, WORKER).value = "anna.kowalska"
    book.save(centrum.register)
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    centrum.fake_inbox.outcome = [first, report(jan, "Raport 09.11.2026", "40000001 nie brak klienta", at=datetime(2026, 11, 9, 18))]
    third = centrum.run_to_end()
    logs = _archived_run(surroundings.report_box, tmp_path, third["run"]["id"])
    entering = json.loads(gzip.decompress(logs.read_bytes()))["report_entering"]

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie")

    assert [(move["row"], move["worker"]) for move in entering["moves"]] == [(row, "jan.testowy")]
    assert [(entry["worker"], entry["value"]) for entry in entering["memory_before"]] == [("anna.kowalska", "wymiana"), ("anna.kowalska", "tak")]
    assert [change["value"] for change in entering["changes"]] == ["nie", "brak klienta"]
    assert entering["problems"] == []
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def test_zmiana_taty_po_przeniesieniu_trzyma_przez_plik_pamieci_i_odtwarza_sie_zgodnie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Tabela przejść R3 przez plik pamięci i Logi: Centrum przeniosło zlecenie Jana do Anny, tata oddał je Janowi, a
    potem znów Annie, tam, gdzie postawiło je Centrum. Tata zmienił Wykonawcę po Przeniesieniu, co pamięć niesie przez
    plik, więc nowszy mail Jana zlecenia nie przenosi, a odtworzenie tego kliknięcia z Logów daje to samo."""

    surroundings = Surroundings()
    jan, anna = SENDERS["jan.testowy"], SENDERS["anna.kowalska"]
    taken = report(anna, "Raport 09.11.2026", "40000001 nie brak klienta", at=datetime(2026, 11, 9, 17))
    centrum = entering_centrum(tmp_path / "taty", MATCHED, [taken], surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    first = centrum.run_to_end()
    assert first["result"]["ending"] == "finished"

    def given_to(worker: str) -> None:
        book = load_workbook(centrum.register)
        [row] = [cell.row for cell in book[ORDER_SHEET][get_column_letter(NUMBER)] if cell.value == 40000001]
        book[ORDER_SHEET].cell(row, WORKER).value = worker
        book.save(centrum.register)

    given_to("jan.testowy")
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    given_to("anna.kowalska")
    centrum.fake_inbox.outcome = [taken, report(jan, "Raport 09.11.2026", "40000001 tak wymiana", at=datetime(2026, 11, 9, 18))]
    third = centrum.run_to_end()
    logs = _archived_run(surroundings.report_box, tmp_path, third["run"]["id"])
    entering = json.loads(gzip.decompress(logs.read_bytes()))["report_entering"]

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie")

    assert [move["overridden"] for move in entering["moves_before"]] == [True]
    assert (entering["moves"], entering["changes"], entering["problems"]) == ([], [], [])
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def test_reczne_przeniesienie_na_inny_dzien_po_przeniesieniu_centrum_odtwarza_sie_z_pamiecia_spod_dnia_centrum(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """#1350 z tabelą przejść R3: Raport Jana za 10.11 przeniósł jego zlecenie z 9.11 na 10.11, a tata przestawił dzień
    z powrotem na 9.11. Raport Anny za 9.11 z tym numerem nie przenosi zlecenia, bo pamięć spod 10.11 mówi o zmianie
    taty, choć temat Anny ma 9.11: Logi mają pamięć zleceń i własne wpisy numeru z każdego dnia, więc odtworzenie daje
    to samo, a nie Przeniesienie do Anny."""

    surroundings = Surroundings()
    jan, anna = SENDERS["jan.testowy"], SENDERS["anna.kowalska"]
    centrum = entering_centrum(tmp_path / "taty", MATCHED, (), surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    centrum.moment.append(datetime(2026, 11, 11, 8))
    centrum.fake_inbox.outcome = [report(jan, "Raport 10.11.2026", "40000001 tak wymiana", at=datetime(2026, 11, 10, 18))]
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    book = load_workbook(centrum.register)
    [row] = [cell.row for cell in book[ORDER_SHEET][get_column_letter(NUMBER)] if cell.value == 40000001]
    assert book[ORDER_SHEET].cell(row, DATE).value == datetime(2026, 11, 10, 9)
    book[ORDER_SHEET].cell(row, DATE).value = datetime(2026, 11, 9, 9)
    book.save(centrum.register)
    before = centrum.register.read_bytes()
    centrum.moment.append(datetime(2026, 11, 11, 8, 30))
    centrum.fake_inbox.outcome = [report(anna, "Raport 09.11.2026", "40000001 tak montaż", at=datetime(2026, 11, 11, 8, 20))]
    third = centrum.run_to_end()
    logs = _archived_run(surroundings.report_box, tmp_path, third["run"]["id"])
    entering = json.loads(gzip.decompress(logs.read_bytes()))["report_entering"]

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie")

    assert centrum.register.read_bytes() == before
    assert [(move["day"], move["overridden"]) for move in entering["moves_before"]] == [("2026-11-10", False)]
    assert {(entry["day"], entry["worker"]) for entry in entering["memory_before"]} == {("2026-11-10", "jan.testowy")}
    assert (entering["moves"], entering["changes"], entering["problems"]) == ([], [], [])
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def test_klikniecie_z_tak_i_nie_jednego_zlecenia_w_mailu_odtwarza_sie_zgodnie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Raport Jana ma dla zlecenia 40000001 Wpis z ``tak`` i Wpis z ``nie``: Logi mają oba Wpisy maila i ostrzeżenie z
    nimi, a odtworzenie, które czyta mail w postaci kanonicznej, daje to samo ostrzeżenie i te same komórki."""

    surroundings = Surroundings()
    mail = report(SENDERS["jan.testowy"], "Raport 09.11.2026", "40000001 tak wymiana\n40000001 nie brak klienta")
    centrum = entering_centrum(tmp_path / "taty", MATCHED, [mail], surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    view = centrum.run_to_end()
    assert view["result"]["ending"] == "finished"
    logs = _archived_run(surroundings.report_box, tmp_path, view["run"]["id"])
    entering = json.loads(gzip.decompress(logs.read_bytes()))["report_entering"]

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie")

    [problem] = entering["problems"]
    assert (problem["kind"], problem["number"], [entry["verdict"] for entry in problem["entries"]]) == (
        "conflicting_verdicts",
        "40000001",
        ["tak", "nie"],
    )
    assert [entry["verdict"] for logged in entering["mails"] for entry in logged["entries"]] == ["tak", "nie"]
    assert (entering["changes"], code, lines[0]) == ([], 0, "ODTWORZENIE ZGODNE"), lines


def _corrected_unreadable(tmp_path: Path, text: str = "40000001 tak wymiana") -> Produced:
    """Logi kliknięcia, w którym Jan przysłał Raport z tematem bez dnia i treścią ``text``, a potem Raport z dniem."""

    surroundings = Surroundings()
    jan = SENDERS["jan.testowy"]
    mails = [
        report(jan, "Raport", text, at=ENTERING_NOW - timedelta(minutes=5)),
        report(jan, "Raport 09.11.2026", "40000001 tak wymiana"),
    ]
    centrum = entering_centrum(tmp_path / "taty", MATCHED, mails, surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    view = centrum.run_to_end()
    assert view["result"]["ending"] == "finished"
    logs = _archived_run(surroundings.report_box, tmp_path, view["run"]["id"])
    return Produced(logs, ("--na-tym-drzewie",))


OLD_LOGS_LIMIT: Final = "- Logi sprzed numerów Wpisów maila z nieczytelnym tematem (v0.7.0)"


@pytest.mark.parametrize(
    ("text", "numbers", "problems"),
    [
        pytest.param("40000001 tak wymiana", ["40000001"], [], id="poprawiony"),
        pytest.param("kurier jutro", [], ["unreadable_subject"], id="bez-wpisow"),
    ],
)
def test_klikniecie_z_nieczytelnym_tematem_i_poprawionym_mailem_odtwarza_sie_zgodnie(
    text: str, numbers: list[str], problems: list[str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Poprawiony mail zdejmuje ostrzeżenie o nieczytelnym temacie, a Logi mają numery Wpisów nieczytelnego maila, więc
    odtworzenie też widzi poprawkę i nie pokazuje ostrzeżenia, którego kliknięcie u taty nie pokazało (kliknięcie
    taty z 11.11 odtwarzało się z jednym problemem więcej). Mail bez Wpisów ma w nowych Logach pustą listę numerów,
    więc ostrzeżenie zostaje, a granicy starych Logów nie ma."""

    produced = _corrected_unreadable(tmp_path, text)
    entering = produced.record["report_entering"]

    code, lines = _replayed(capsys, produced.archived, *produced.arguments)

    assert [(mail["kind"], mail.get("numbers")) for mail in entering["mails"]] == [
        ("unreadable", numbers),
        ("report", None),
    ]
    assert [problem["kind"] for problem in entering["problems"]] == problems
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert not any(line.startswith(OLD_LOGS_LIMIT) for line in lines), lines


def test_logi_sprzed_numerow_nieczytelnego_maila_daja_roznice_z_granica_w_raporcie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Logi z v0.7.0 nie mają numerów Wpisów maila z nieczytelnym tematem: odtworzenie nie widzi poprawki, a raport
    mówi dlaczego."""

    produced = _corrected_unreadable(tmp_path)
    changed = _changed(produced, tmp_path, lambda record: record["report_entering"]["mails"][0].pop("numbers"))

    code, lines = _replayed(capsys, changed, *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert any(line.startswith(OLD_LOGS_LIMIT) for line in lines), lines


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("40000001 nie sprzęt wysłano z magazynu\nkurier jutro", id="slowa-stopki-przed-tekstem-w-nastepnej-linii"),
        pytest.param("40000001 nie sprzęt wysłano z magazynu 40000001 nie drugi", id="slowa-stopki-przed-powtorzonym-numerem"),
        pytest.param(
            "40000001 tak montaż\n40000002 nie sprzęt wysłano z magazynu 40000001 tak drugi",
            id="slowa-stopki-przed-powtorzonym-numerem-innego-wpisu",
        ),
        pytest.param("40000001 t wymiana\n40000001 nie brak klienta", id="litera-t-przeciw-nie"),
    ],
)
def test_klikniecie_ze_slowami_stopki_w_opisie_albo_litera_przeciw_nie_odtwarza_sie_zgodnie(
    text: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Opis ze słowami stopki w środku, który w mailu stoi przed dalszym tekstem albo przed Wpisem, który się nie liczy,
    a w postaci kanonicznej byłby na końcu treści, i Wpis z literą przeciw Wpisowi z ``nie`` (Decyzja Maksa D13):
    odtworzenie z Logów czyta mail w postaci kanonicznej tak jak kliknięcie."""

    surroundings = Surroundings()
    mail = report(SENDERS["jan.testowy"], "Raport 09.11.2026", text)
    centrum = entering_centrum(tmp_path / "taty", MATCHED, [mail], surroundings=surroundings)
    write_report_key(ToolDirectory(tmp_path / "taty"))
    view = centrum.run_to_end()
    assert view["result"]["ending"] == "finished"
    logs = _archived_run(surroundings.report_box, tmp_path, view["run"]["id"])

    code, lines = _replayed(capsys, logs, "--na-tym-drzewie")

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def _logged_entry(record: dict[str, Any], number: str) -> dict[str, Any]:
    """Jedyny Wpis raportu z numerem ``number`` w Logach Wpisania raportów, do zmiany w miejscu."""

    entries: list[dict[str, Any]] = [entry for mail in record["report_entering"]["mails"] for entry in mail.get("entries", [])]
    [entry] = [entry for entry in entries if entry["number"] == number]
    return entry


def _other_activities(record: dict[str, Any]) -> None:
    _logged_entry(record, "40000002")["activities"] = "montaż gniazda"


def test_zmieniony_wpis_raportu_w_logach_daje_pierwsza_roznice_w_komorkach_wpisanych_przez_odtworzenie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Wpis raportu Anny w Logach z innymi czynnościami niż te, z których Wpisanie raportów wpisało komórkę: odtworzenie
    wpisuje czynności z Logów, więc pierwszą różnicą jest wartość tej komórki w zmianach, a Wpisy z Logów wracają z
    postaci kanonicznej bez różnicy."""

    produced = _report_entering(tmp_path / "taty")
    changed = _changed(produced, tmp_path, _other_activities)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie")

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    [sheet] = produced.record["input_copy"][0]["sheets"]
    assert lines[3:6] == [
        f"Pierwsza różnica: Wpisanie raportów (report_entering).changes[2: arkusz {sheet['sheet']}].value",
        '  Logi:        "montaż"',
        '  Odtworzenie: "montaż gniazda"',
    ]


def test_problem_rdzenia_zdjety_z_logow_daje_pierwsza_roznice_w_problemach_wpisania_raportow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Odtworzenie porównuje problemy rdzenia raportów z Logów, nie tylko komórki: Logi bez pierwszego problemu
    (nieznany nadawca), który rdzeń liczy z tych samych Wpisów, dają różnicę w problemach."""

    produced = _report_entering(tmp_path / "taty")
    changed = _changed(produced, tmp_path, lambda record: record["report_entering"]["problems"].pop(0))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie")

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert lines[3] == "Pierwsza różnica: Wpisanie raportów (report_entering).problems[0].mail", lines


def test_logi_wpisania_raportow_sprzed_dni_zamknietych_bez_pola_closed_odtwarzaja_sie_zgodnie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Logi Wpisania raportów sprzed #1229 nie mają tokenów okresów z Plikiem zbiorczym (``closed``), bo kliknięcie ich
    wtedy nie sprawdzało: odtwarzają się jak kliknięcie bez okresu zamkniętego."""

    produced = _report_entering(tmp_path / "taty")
    assert produced.record["report_entering"]["closed"] == []
    changed = _changed(produced, tmp_path, lambda record: record["report_entering"].pop("closed"))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie")

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def _guard_cut(place: str) -> Callable[[dict[str, Any]], None]:
    return lambda record: record["technical_notes"].append(
        f"Reguła danych: pominięto {place}: strażnik zamaskował w nim wartość, której pole nie przyjmuje."
    )


def _emptied_by_guard(record: dict[str, Any]) -> None:
    record["report_entering"] = None
    record["technical_notes"].append(
        "Reguła danych: pole report_entering jest puste: strażnik zamaskował w nim wartość, której pole nie przyjmuje."
    )


def _stopped_at_saving(record: dict[str, Any]) -> None:
    record.update(ending="stop", stop_kind="for_tata", result=None)
    record["report_entering"]["written"] = None


# Granica Logów Wpisania raportów: zmiana pliku Logów drugiego kliknięcia, kod wyjścia i linia raportu (pierwsza przy
# granicy blokującej, a przy zastrzeżeniu linie pod „Granice:”, które się nimi zaczynają).
ENTERING_LIMITS: dict[str, tuple[Callable[[dict[str, Any]], None], int, tuple[str, ...]]] = {
    "kazde_odtworzenie": (
        lambda record: None,
        0,
        (
            "- maili taty Logi nie mają: odtworzenie czyta Wpisy raportu z Logów z maili w postaci kanonicznej",
            "- Wpisy raportu w Logach mają maski strażnika reguły danych ([telefon] ×1): odtworzenie wpisuje do INTERMAX",
        ),
    ),
    "numer_wpisu_jako_telefon": (
        lambda record: _logged_entry(record, "40000099").update(number="[telefon]"),
        3,
        ("NIE DA SIĘ ODTWORZYĆ: Wpis raportu w Logach ma numer zlecenia zamaskowany przez strażnika reguły danych ([telefon]: 9 cyfr",),
    ),
    "pamiec_bez_wpisu_z_numerem": (
        lambda record: record["report_entering"]["memory_before"][0].update(number=4000007),
        3,
        ("NIE DA SIĘ ODTWORZYĆ: pamięć wpisów w Logach ma zlecenie 4000007 Wykonawcy jan.testowy z 09.11.2026 tylko jako liczbę",),
    ),
    "ciecie_straznika_we_wpisach": (
        _guard_cut("report_entering.mails[5]"),
        3,
        ("NIE DA SIĘ ODTWORZYĆ: strażnik reguły danych pominął w Logach report_entering.mails[5]",),
    ),
    "ciecie_straznika_w_przeniesieniach_przed": (
        _guard_cut("report_entering.moves_before[0]"),
        3,
        ("NIE DA SIĘ ODTWORZYĆ: strażnik reguły danych pominął w Logach report_entering.moves_before[0]",),
    ),
    "ciecie_straznika_calego_pola": (
        _emptied_by_guard,
        3,
        ("NIE DA SIĘ ODTWORZYĆ: strażnik reguły danych zostawił puste w Logach report_entering ",),
    ),
    "bez_wpisow_przed_rdzeniem": (
        lambda record: record.update(report_entering=None),
        1,
        ("- Logi nie mają Wpisów raportu, bo Uruchomienie skończyło się przed rdzeniem raportów",),
    ),
    "zatrzymanie_przy_zapisie": (
        _stopped_at_saving,
        1,
        ("- zapis INTERMAX u taty skończył się Zatrzymaniem, które zależy od jego dysku",),
    ),
}


@pytest.mark.parametrize("case", ENTERING_LIMITS)
def test_granica_logow_wpisania_raportow_jest_w_raporcie_a_blokujaca_konczy_odtworzenie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Czego Logi Wpisania raportów nie niosą, raport mówi: maile taty i czynności pod maską są zastrzeżeniem przy każdym
    odtworzeniu, a Logi bez Wpisów i Zatrzymanie przy zapisie u taty zastrzeżeniem przy
    różnicy. Numer Wpisu zamaskowany jak telefon, numer pamięci bez Wpisu z nim i cięcie strażnika w dowolnym polu Logów
    Wpisania raportów kończą odtworzenie bez uruchomienia procesu (kod 3)."""

    change, expected_code, expected = ENTERING_LIMITS[case]
    produced = _report_entering(tmp_path / "taty")
    changed = _changed(produced, tmp_path, change)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie")

    assert code == expected_code, lines
    if expected_code == 3:
        [first] = expected
        assert lines[0].startswith(first) and not any(line.startswith("Pierwsza różnica") for line in lines), lines
    else:
        granice = lines[lines.index("Granice:") + 1 :]
        assert all(any(line.startswith(text) for line in granice) for text in expected), granice


CLICK_DAY: Final = date(2026, 11, 9)
JAN, ANNA = Login("jan.testowy"), Login("anna.testowa")


def _entering_facts() -> EnteringFacts:
    """Fakty kliknięcia z numerem z zerem na początku we Wpisie (pamięć wpisów, pamięć zlecenia z innego dnia i od
    innego Wykonawcy, numer bez zlecenia), decyzją „Zostaw moją”, mailem z nieczytelnym tematem i trzema mailami spoza
    listy adresów, z których dwa mają ten sam Message-ID i różne adresy."""

    arrived = datetime(2026, 11, 9, 18, 0).astimezone()
    zero, plain = OrderNumber("040000001"), OrderNumber("40000002")
    twice, once = MailId("c" * 16), MailId("d" * 16)
    entries = (ReportEntry(zero, Intent.YES, None, "montaż"), ReportEntry(plain, Intent.NO, None, "brak klienta"))
    return EnteringFacts(
        today=CLICK_DAY,
        rollout_before=date(2026, 11, 2),
        rollout=date(2026, 11, 2),
        closed=("2_8_11_2026",),
        memory_before=(OwnEntry(OrderKey(zero, CLICK_DAY, JAN), ReportColumn.SUCCESSFUL, "tak"),),
        kept=(Kept(OrderKey(plain, CLICK_DAY, JAN), ReportColumn.COMPLETED, "brak klienta"),),
        skipped=2,
        mails=(
            ReadReport(MailId("a" * 16), arrived, JAN, CLICK_DAY, entries),
            ReadUnreadable(MailId("b" * 16), arrived, ANNA, SubjectFault.NO_DATE, frozenset({plain})),
            ReadStranger(twice, arrived, CLICK_DAY),
            ReadStranger(twice, arrived, CLICK_DAY),
            ReadStranger(once, arrived, CLICK_DAY),
        ),
        problems=(
            UnknownSender(twice, SenderAddress("pierwszy@obcy.invalid"), CLICK_DAY),
            UnknownSender(twice, SenderAddress("drugi@obcy.invalid"), CLICK_DAY),
            UnknownSender(once, SenderAddress("trzeci@obcy.invalid"), CLICK_DAY),
        ),
        changes=(),
        moves_before=(OwnMove(zero, date(2026, 11, 10), ANNA, CLICK_DAY, JAN, "Jan Testowy", arrived, True, False),),
        orderless=(Orderless("Zlecenia", zero, None),),
    )


def _logged_reports(facts: EnteringFacts) -> dict[str, Any]:
    logged = LoggedReports.of_run(None, facts)
    assert logged is not None
    loaded: dict[str, Any] = json.loads(logged.model_dump_json())
    return loaded


def test_wpisanie_raportow_z_logow_wraca_jako_te_same_fakty_klikniecia_z_numerem_z_zerem_z_wpisu() -> None:
    """Logi mają numer pamięci wpisów, pamięci zleceń i numeru bez zlecenia tylko jako liczbę, a odczyt wejścia
    kliknięcia z pliku Logów daje te same pamięć, decyzje „Zostaw moją”, maile i numery bez zlecenia co kliknięcie, z
    zerem na początku z Wpisu. Mail spoza listy adresów dostaje po kolei jeden z różnych adresów jego Message-ID."""

    facts = _entering_facts()

    replayed = LoggedReports.model_validate(_logged_reports(facts)).replay()

    assert isinstance(replayed, EnteringReplay), replayed
    assert replayed.saved == SavedState(
        facts.rollout_before, OwnEntries(frozenset(facts.memory_before), frozenset(facts.moves_before)), frozenset(facts.kept)
    )
    assert replayed.mails == facts.mails
    assert replayed.strangers == (0, 1, 0)
    assert replayed.orderless == (ReplayedOrderless("Zlecenia", "040000001", None),)
    assert (replayed.today, replayed.closed, replayed.skipped, replayed.reservations) == (
        facts.today,
        facts.closed,
        facts.skipped,
        (),
    )


def _second_form(entering: dict[str, Any]) -> None:
    entering["mails"][0]["entries"].append({"number": "0040000002", "verdict": "nie", "fault": None, "activities": ""})


# Zmiana Logów Wpisania raportów z ``_entering_facts`` i początek powodu, dla którego odtworzenie nie ma wejścia.
UNREPLAYABLE: Final[dict[str, tuple[Callable[[dict[str, Any]], None], str]]] = {
    "numer_wpisu_z_maska": (
        lambda entering: entering["mails"][0]["entries"][1].update(number="[telefon]"),
        "Wpis raportu w Logach ma numer zlecenia zamaskowany przez strażnika reguły danych ([telefon]: 9 cyfr",
    ),
    "pamiec_bez_wpisu": (
        lambda entering: entering["memory_before"][0].update(number=40000009),
        "pamięć wpisów w Logach ma zlecenie 40000009 Wykonawcy jan.testowy z 09.11.2026 tylko jako liczbę, a jego numeru "
        "nie ma w dokładnie jednym Wpisie",
    ),
    "zostaw_moja_z_dwiema_postaciami_numeru": (
        _second_form,
        "decyzje „Zostaw moją” w Logach ma zlecenie 40000002 Wykonawcy jan.testowy z 09.11.2026 tylko jako liczbę",
    ),
    "dwa_przeniesienia_jednej_postaci_numeru_z_jednego_dnia": (
        lambda entering: entering["moves_before"].append({**entering["moves_before"][0], "worker": "ola.testowa"}),
        "pamięć wpisów i zleceń w Logach z numerami w postaci z Wpisów raportu łamie regułę pamięci (Pamięć własnych "
        "wpisów ma dwa Przeniesienia jednego zlecenia w jednym dniu)",
    ),
}


@pytest.mark.parametrize("case", UNREPLAYABLE)
def test_logi_wpisania_raportow_bez_numeru_zlecenia_nie_daja_wejscia_klikniecia(case: str) -> None:
    """Numer Wpisu z maską strażnika, numer pamięci albo decyzji „Zostaw moją”, którego postaci nie wyznacza dokładnie
    jeden Wpis, i pamięć zleceń, w której postacie numerów z Wpisów dają dwa Przeniesienia jednego zlecenia w jednym
    dniu, nie dają wejścia kliknięcia, tylko powód."""

    change, reason = UNREPLAYABLE[case]
    entering = _logged_reports(_entering_facts())
    change(entering)

    replayed = LoggedReports.model_validate(entering).replay()

    assert isinstance(replayed, Unreplayable) and replayed.reason.startswith(reason), replayed


def test_postac_numeru_spod_wpisu_odchodzi_z_pierwszym_przeniesieniem_u_tego_wykonawcy_i_dnia() -> None:
    """0040000001 i 40000001 to dwa zlecenia, a Logi niosą numer Przeniesienia tylko jako liczbę: jedyna postać spod
    Wpisu Wykonawcy i dnia odchodzi z pierwszym Przeniesieniem, więc drugie tej liczby u tego Wykonawcy i dnia to
    zlecenie bez zer na początku, a nie drugie Przeniesienie tego samego zlecenia."""

    entering = _logged_reports(_entering_facts())
    [move] = entering["moves_before"]
    here = {"day": "2026-11-09", "worker": "jan.testowy"}
    entering["moves_before"] = [move | here, move | here | {"origin_name": "Jan Testowy Drugi"}]

    replayed = LoggedReports.model_validate(entering).replay()

    assert isinstance(replayed, EnteringReplay), replayed
    memory = replayed.saved.memory
    assert isinstance(memory, OwnEntries)
    assert sorted(str(moved.number) for moved in memory.moves) == ["040000001", "40000001"]


OLA: Final = Login("ola.testowa")
FORM_DAYS: Final = (date(2026, 11, 5), date(2026, 11, 8), CLICK_DAY)
FORM_WORKERS: Final = (JAN, ANNA, OLA)
# Numer z zerami na początku i bez nich to w INTERMAX różne zlecenia jednej liczby.
FORMS: Final = (OrderNumber("0040000001"), OrderNumber("040000001"), OrderNumber("40000001"))
PROPERTY: Final = settings(derandomize=True, database=None, deadline=None, max_examples=150)


def _click_with_forms(
    reported: dict[tuple[date, Login], frozenset[OrderNumber]],
    moved: Sequence[OrderKey],
    entries: Sequence[OwnEntry] = (),
    kept: Sequence[Kept] = (),
    orderless: Sequence[Orderless] = (),
) -> EnteringFacts:
    """Fakty kliknięcia z Wpisami ``reported`` po dniu i Wykonawcy i z pamięcią sprzed kliknięcia, pamięć zleceń w
    kolejności, w której zapisuje ją kliknięcie (po dniu i numerze)."""

    arrived = datetime(2026, 11, 9, 18, 0).astimezone()
    mails = tuple(
        ReadReport(
            MailId(f"{index:016x}"),
            arrived,
            worker,
            day,
            tuple(ReportEntry(form, Intent.YES, None, "montaż") for form in sorted(forms)),
        )
        for index, ((day, worker), forms) in enumerate(sorted(reported.items()))
    )
    moves = (OwnMove(key.number, key.day, key.worker, key.day, key.worker, "Jan Testowy", arrived) for key in moved)
    return EnteringFacts(
        today=CLICK_DAY,
        rollout_before=date(2026, 11, 2),
        rollout=date(2026, 11, 2),
        closed=(),
        memory_before=tuple(sorted(entries, key=lambda entry: (entry.key, entry.column.value))),
        kept=tuple(kept),
        skipped=0,
        mails=mails,
        problems=(),
        changes=(),
        moves_before=tuple(sorted(moves, key=lambda move: (move.day, move.number))),
        orderless=tuple(orderless),
    )


@st.composite
def _clicks_with_forms(draw: st.DrawFn) -> EnteringFacts:
    """Fakty kliknięcia z kilkoma postaciami jednej liczby we Wpisach od jednego albo kilku Wykonawców z jednego albo
    kilku dni: pamięć wpisów, decyzja „Zostaw moją” i pamięć zleceń pod Wpisem albo pod dowolnym dniem i Wykonawcą, z
    najwyżej jednym Przeniesieniem zlecenia (tak pamięć zapisuje Wpisanie raportów od #1367 r4, ``memories_of``), i
    numer bez zlecenia."""

    places = st.tuples(st.sampled_from(FORM_DAYS), st.sampled_from(FORM_WORKERS))
    single = st.sampled_from(FORMS).map(lambda form: frozenset({form}))
    forms = st.one_of(single, single, st.frozensets(st.sampled_from(FORMS), min_size=2, max_size=2))
    reported = draw(st.dictionaries(places, forms, min_size=2, max_size=4))
    keys = sorted(OrderKey(form, day, worker) for (day, worker), found in reported.items() for form in found)
    numbers = st.sampled_from(sorted({key.number for key in keys}))
    elsewhere = st.builds(OrderKey, numbers, st.sampled_from(FORM_DAYS), st.sampled_from(FORM_WORKERS))
    placed = st.one_of(st.sampled_from(keys), st.sampled_from(keys), elsewhere)
    columns = st.sampled_from(ReportColumn)
    return _click_with_forms(
        reported,
        draw(st.lists(placed, min_size=1, max_size=3, unique_by=lambda key: key.number)),
        draw(st.lists(st.builds(OwnEntry, placed, columns, st.just("tak")), max_size=1)),
        draw(st.lists(st.builds(Kept, st.sampled_from(keys), columns, st.just("brak klienta")), max_size=1)),
        draw(st.lists(st.builds(Orderless, st.just("Zlecenia"), numbers, st.sampled_from((None, *FORM_DAYS))), max_size=1)),
    )


@PROPERTY
@given(_clicks_with_forms())
def test_odczyt_wejscia_klikniecia_z_logow_z_kilkoma_postaciami_jednej_liczby_nie_rzuca_wyjatku(
    facts: EnteringFacts,
) -> None:
    """Numer z zerami na początku i bez nich to różne zlecenia, a Logi mają numer pamięci tylko jako liczbę. Odczyt
    wejścia kliknięcia z pliku Logów daje wejście albo powód, dla którego Logi go nie wyznaczają, nigdy wyjątek, bo
    wyjątek kończy odtworzenie bez raportu."""

    replayed = LoggedReports.model_validate(_logged_reports(facts)).replay()

    assert isinstance(replayed, EnteringReplay | Unreplayable), replayed


# Wpisy po dniu i Wykonawcy i miejsca dwóch Przeniesień jednej liczby z jednego dnia: pierwsze w Logach (po dniu i
# numerze) pod Wpisem swojego Wykonawcy i dnia, drugie pod Wykonawcą bez Wpisu z tego dnia.
TWO_MOVES_ONE_DAY: Final[dict[str, tuple[dict[tuple[date, Login], frozenset[OrderNumber]], tuple[OrderKey, OrderKey]]]] = {
    "postac_drugiego_z_innego_dnia": (
        {(CLICK_DAY, JAN): frozenset({FORMS[1]}), (FORM_DAYS[0], ANNA): frozenset({FORMS[2]})},
        (OrderKey(FORMS[1], CLICK_DAY, JAN), OrderKey(FORMS[2], CLICK_DAY, ANNA)),
    ),
    "postac_drugiego_od_innego_wykonawcy_z_tego_dnia": (
        {(CLICK_DAY, JAN): frozenset({FORMS[0]}), (CLICK_DAY, OLA): frozenset({FORMS[1]})},
        (OrderKey(FORMS[0], CLICK_DAY, JAN), OrderKey(FORMS[1], CLICK_DAY, ANNA)),
    ),
}


@pytest.mark.parametrize("case", TWO_MOVES_ONE_DAY)
def test_dwa_przeniesienia_jednej_liczby_z_jednego_dnia_wracaja_z_logow_jako_dwa_zlecenia(case: str) -> None:
    """Zlecenie ma najwyżej jedno Przeniesienie na dzień, więc z dwóch Przeniesień jednej liczby z jednego dnia to pod
    Wpisem swojego Wykonawcy i dnia ma postać z tego Wpisu, a drugie, które idzie w Logach po nim, drugą postać tej
    liczby z Wpisów: odczyt wejścia kliknięcia z pliku Logów daje tę samą pamięć zleceń co kliknięcie."""

    facts = _click_with_forms(*TWO_MOVES_ONE_DAY[case])

    replayed = LoggedReports.model_validate(_logged_reports(facts)).replay()

    assert isinstance(replayed, EnteringReplay), replayed
    assert replayed.saved.memory == OwnEntries(frozenset(), frozenset(facts.moves_before))


def test_pamiec_wpisow_pod_wykonawca_bez_raportu_wraca_z_logow_z_postacia_numeru_z_wpisu_innego_wykonawcy_z_tego_dnia() -> None:
    """Wpis pamięci idzie za wierszem, więc może stać pod Wykonawcą, który nie przysłał Raportu. Jego numer ma wtedy
    postać z Wpisu innego Wykonawcy z tego samego dnia, a nie z Wpisów innych numerów tego dnia ani z Wpisu tej liczby z
    innego dnia, bo numer z zerami na początku i bez nich to różne zlecenia: odczyt wejścia kliknięcia z pliku Logów daje
    tę samą pamięć wpisów co kliknięcie."""

    entry = OwnEntry(OrderKey(FORMS[1], CLICK_DAY, ANNA), ReportColumn.SUCCESSFUL, "tak")
    reported = {(CLICK_DAY, JAN): frozenset({FORMS[1], OrderNumber("40000002")}), (FORM_DAYS[0], OLA): frozenset({FORMS[2]})}
    facts = _click_with_forms(reported, (), (entry,))

    replayed = LoggedReports.model_validate(_logged_reports(facts)).replay()

    assert isinstance(replayed, EnteringReplay), replayed
    assert replayed.saved.memory == OwnEntries(frozenset({entry}), frozenset())


def test_numer_bez_zlecenia_bez_zera_we_wpisach_wraca_z_logow_jako_liczba() -> None:
    """Odtworzenie stawia numer bez zlecenia w ``NUMER ZL.`` jak wklejenie z aplikacji: w postaci z zerem na początku z
    Wpisu, gdy Wpis ją ma, a inaczej liczbą, więc numer, którego Wpisy nie mają zera, wraca z Logów jako liczba."""

    facts = _click_with_forms({(CLICK_DAY, JAN): frozenset({FORMS[2]})}, (), orderless=(Orderless("Zlecenia", FORMS[2], None),))

    replayed = LoggedReports.model_validate(_logged_reports(facts)).replay()

    assert isinstance(replayed, EnteringReplay), replayed
    assert replayed.orderless == (ReplayedOrderless("Zlecenia", 40000001, None),)


def test_strona_efenix_inna_niz_w_odczycie_z_logow_daje_roznice_w_sladzie_zlecen(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Atrapa efenix ma stronę z odczytów stron w Logach: odczyt wiersza listy zmieniony w Logach (status „Do wyceny”
    zamiast innego) zmienia, co okno widzi w odtworzeniu, więc Komunikat tego zlecenia różni się od Komunikatu w Logach."""

    produced = shared_logs("efenix")

    def ready_status(record: dict[str, Any]) -> None:
        [result] = record["efenix_orders"][2]["steps"][0]["results"]
        assert result["status"] == "W realizacji"
        result["status"] = "Do wyceny"

    changed = _changed(produced, tmp_path, ready_status)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert lines[3] == "Pierwsza różnica: Komunikaty (messages)[1: kod EFENIX_INNY_STATUS].code"


# Wiersze 18–20 po Wykonawcach: ``ADRES``, którego reguła adresu nie rozbiera (bez rodzaju ulicy), ``Dane adresowe``
# bez rodzaju ulicy i ``Dane adresowe`` z inną ulicą i numerem domu. Adresy są wymyślone.
ADDRESSED = [
    _efenix_order("#ZLQR11", "adrian.testowy", address="ZAWILCOWA 12/3"),
    _efenix_order("#ZLQR12", "beata.testowa", efenix_address="Miastowo-Centrum Zawilcowa 12 Lokal 3"),
    _efenix_order("#ZLQR13", "celina.testowa", efenix_address="Miastowo-Centrum ul.Rumiankowa 14 Lokal 3"),
]


def test_logi_wyceny_z_adresem_bez_rozbioru_i_innym_adresem_w_efenix_odtwarzaja_sie_zgodnie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Atrapa z Logów pokazuje ``Dane adresowe``, które różnią się od ``ADRES`` odtworzonego Pliku zbiorczego tymi
    samymi częściami co u taty: ``ADRES`` bez rozbioru (w odtworzonym pliku też bez rodzaju ulicy, z numerem swojego
    wiersza), ``Dane adresowe`` bez rozbioru oraz inna ulica i numer domu. Wycena daje więc te same Komunikaty i ślad, a
    raport nie ma granicy o adresie."""

    in_efenix = [order.in_efenix(str(651 + index)) for index, order in enumerate(ADDRESSED)]
    produced = _efenix(tmp_path / "taty", in_efenix, priced=ADDRESSED)
    kept = tmp_path / "odtworzenie"

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", "--zachowaj", kept, *produced.arguments)

    logged = [result["address"] for order in produced.record["efenix_orders"] for result in order["steps"][0]["results"]]
    assert logged == [[AddressPart.FILE_UNREAD.value], [AddressPart.EFENIX_UNREAD.value], ["ulica", "numer domu"]]
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert [line[:40] for line in lines[lines.index("Granice:") + 1 :]] == ["- efenix to Atrapa efenix z odczytów str"], lines
    [collective] = (kept / "okresy").rglob("*.xlsx")
    workbook = openpyxl.load_workbook(collective)
    sheet = workbook.active
    assert sheet is not None
    column = next(cell.column for cell in sheet[17] if cell.value == "ADRES")
    addresses = {row: str(sheet.cell(row, column).value) for row in (18, 19, 20)}
    workbook.close()
    unread = (AddressPart.FILE_UNREAD, AddressPart.EFENIX_UNREAD)
    assert [(address_differences(address, address), address.endswith(f" {row}")) for row, address in addresses.items()] == [
        (unread, True),
        ((), True),
        ((), True),
    ], addresses


def test_logi_wyceny_sprzed_odczytu_wierszy_listy_koncza_odtworzenie_granica(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Logi sprzed #843 mają szukanie z trafieniami bez odczytu wierszy listy, więc Atrapa nie wie, co pokazać:
    odtworzenie kończy się granicą (kod 3), a nie różnicą."""

    produced = shared_logs("efenix")

    def without_results(record: dict[str, Any]) -> None:
        for order in record["efenix_orders"]:
            for step in order["steps"]:
                if step["action"] == "szukanie":
                    step["results"] = None

    changed = _changed(produced, tmp_path, without_results)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (
        3,
        "NIE DA SIĘ ODTWORZYĆ: Logi Wyceny w efenix nie mają odczytu wierszy listy po szukaniu (Logi sprzed #843), więc "
        "Atrapa nie wie, co pokazać",
    ), lines


def _page(amount: str, quantities: dict[str, int | str]) -> dict[str, Any]:
    """Odczyt strony zlecenia po otwarciu w śladzie: kwota końcowa i ilości (każda pozycja Atrapy bez podanej ma 0)."""

    shown = {**dict.fromkeys(PRICES, 0), **quantities}
    return {"action": "otwarcie zlecenia", "duration_ms": 1, "found": None, "execution_date": None, "amount": amount,
            "quantities": shown, "position": None, "quantity": None, "accepted": None}


def _typed(position: str, quantity: int, amount: str | None) -> dict[str, Any]:
    """Wpisanie ilości pozycji w śladzie z kwotą końcową po zapisie (``None``: zapis bez kwoty)."""

    return {"action": "ilość", "duration_ms": 1, "found": None, "execution_date": None, "amount": amount,
            "quantities": None, "position": position, "quantity": quantity, "accepted": True}


def _searched(*results: dict[str, Any]) -> dict[str, Any]:
    return {"action": "szukanie", "duration_ms": 1, "found": len(results), "execution_date": None, "amount": None,
            "quantities": None, "position": None, "quantity": None, "accepted": None, "results": list(results)}


def _traced(row: int, *steps: dict[str, Any]) -> LoggedOrder:
    return LoggedOrder.model_validate({"row": row, "outcome": "gotowe", "code": None, "file": {}, "file_amount": "0", "steps": list(steps)})


_UNKNOWN_012 = ("ceny pozycji 012 nie wynikają z kwot w Logach: Atrapa liczy je swoimi cenami", False)
# Kroki śladu każdego zlecenia w Logach, ceny, które z nich wynikają, i granice Atrapy (tekst, czy blokuje).
PRICES_FROM_LOGS: dict[str, tuple[list[list[dict[str, Any]]], dict[str, Decimal], tuple[tuple[str, bool], ...]]] = {
    "zmiana_kwoty_po_wpisaniu_ilosci": ([[_page("0.00", {}), _typed("012", 1, "99.00")]], {"012": Decimal(99)}, ()),
    "zmiana_jednej_z_dwoch_pozycji_strony": (
        [[_page("30.00", {"012": 1, "013": 1}), _typed("012", 2, "40.00")]],
        {"012": Decimal(10), "013": Decimal(20)},
        (),
    ),
    "cena_ze_strony_innego_zlecenia": (
        [[_page("30.00", {"012": 1, "013": 1})], [_page("10.00", {"012": 1})]],
        {"012": Decimal(10), "013": Decimal(20)},
        (),
    ),
    "zapis_ilosci_bez_kwoty": ([[_page("0.00", {}), _typed("012", 1, None)]], {"012": PRICES["012"]}, ()),
    "dwie_nieznane_na_stronie_jedna_spoza_atrapy": (
        [[_page("50.00", {"012": 1, "999": 1})]],
        {"012": PRICES["012"]},
        (_UNKNOWN_012, ("pozycji 999 nie ma na stronach Atrapy efenix", False)),
    ),
}


@pytest.mark.parametrize("case", PRICES_FROM_LOGS)
def test_ceny_atrapy_z_logow_wynikaja_z_kwot_po_wpisaniu_ilosci_i_ze_stron_z_jedna_nieznana_cena(case: str) -> None:
    """Cena pozycji to zmiana kwoty końcowej po wpisaniu ilości przez zmianę jej ilości, a kwota strony, na której
    tylko jedna pozycja z ilością ma nieznaną cenę, daje tę cenę, także ze strony innego zlecenia i po cenie wyznaczonej
    później. Cena, której Logi nie wyznaczają, zostaje ceną Atrapy z granicą, gdy pozycja ma ilość, a pozycja spoza
    stron Atrapy ma swoją granicę (``atrapa_z_logow``)."""

    steps, prices, limits = PRICES_FROM_LOGS[case]

    found = fed([_traced(18 + index, *order) for index, order in enumerate(steps)], [])

    assert ({code: found.prices[code] for code in prices}, found.limits) == (prices, limits)


def test_atrapa_z_logow_nazywa_wiersz_bez_numeru_zl_i_roznice_adresu_ktorej_nie_umie_pokazac() -> None:
    """Zlecenie z wynikami szukania w Logach, którego wiersz odtworzonego Pliku zbiorczego nie ma ``NUMER ZL.``, i
    wynik z częścią adresu, której Atrapa nie umie pokazać (np. z innej wersji Logów), dają granice, które nie blokują;
    zlecenie bez wyników szukania granicy nie daje."""

    listed = {"same_number": True, "status": "Do wyceny", "realizator": "adrian.testowy"}
    orders = [
        _traced(18, _searched({**listed, "address": []})),
        _traced(19, _searched()),
        _traced(20, _searched({**listed, "address": ["województwo"]})),
    ]
    scoped = [ScopedOrder(18, None, "ul. Odtworzeniowa 18"), ScopedOrder(19, None, "ul. Odtworzeniowa 19"), ScopedOrder(20, "ZL20", "ul. Odtworzeniowa 20")]

    found = fed(orders, scoped)

    assert ([order.number for order in found.orders], found.limits) == (
        ["ZL20"],
        (
            ("wiersz 18 Pliku zbiorczego nie ma w odtworzeniu zlecenia z NUMER ZL.", False),
            ("wiersz 20: Atrapa nie umie pokazać różnicy adresu ['województwo']", False),
        ),
    )


def test_kopia_wejscia_bez_folderow_nad_plikiem_daje_roznice_w_kopii_a_nie_zgodnosc(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Kopia wejścia bez nazw folderów nad plikiem (Logi sprzed #847): odbudowa kładzie Plik zbiorczy w folderze okresu,
    więc Kopia odtworzenia ma foldery, których Kopia w Logach nie ma, a pierwszą różnicą jest Kopia wejścia."""

    produced = shared_logs("settlement")
    changed = _changed(produced, tmp_path, lambda record: record["input_copy"][0].pop("folders"))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    name = produced.record["input_copy"][0]["name"]
    assert lines[3:6] == [
        f"Pierwsza różnica: Kopia wejścia (input_copy)[0: plik {name}].folders[0]",
        "  Logi:        (brak)",
        '  Odtworzenie: "okresy"',
    ]


def test_inna_data_wykonania_w_sladzie_zlecen_efenix_daje_roznice_w_sladzie_przy_tych_samych_komunikatach(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Dzień, który okno wpisało w datę wykonania, Atrapa z Logów bierze z Pliku zbiorczego, nie z kroku śladu: inny
    dzień w śladzie zleceń efenix w Logach nie zmienia Komunikatów, a odtworzenie zgłasza różnicę w tym kroku śladu."""

    produced = shared_logs("efenix")

    def other_day(record: dict[str, Any]) -> None:
        [typed] = [step for step in record["efenix_orders"][0]["steps"] if step["action"] == "data wykonania"]
        typed["execution_date"] = "2026-09-10"

    changed = _changed(produced, tmp_path, other_day)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    row = produced.record["efenix_orders"][0]["row"]
    assert lines[3].startswith(f"Pierwsza różnica: ślad zleceń efenix (efenix_orders)[0: wiersz {row}].steps["), lines
    assert (lines[3].endswith("].execution_date"), lines[4]) == (True, '  Logi:        "2026-09-10"'), lines


def _twice_saving(phases: list[dict[str, Any]]) -> None:
    phases.append(phases[-1])


def _without_saving(phases: list[dict[str, Any]]) -> None:
    phases.pop()


# Lista w Logach dłuższa i krótsza niż w odtworzeniu przy równym początku: etap Zapisywania dopisany drugi raz i usunięty.
LENGTHS: dict[str, tuple[Callable[[list[dict[str, Any]]], None], str, str, str]] = {
    "dluzsza_w_logach": (_twice_saving, "4: etap Zapisywanie", "Logi", "Odtworzenie"),
    "krotsza_w_logach": (_without_saving, "3: etap Zapisywanie", "Odtworzenie", "Logi"),
}


@pytest.mark.parametrize("case", LENGTHS)
def test_lista_innej_dlugosci_w_logach_daje_roznice_w_pierwszym_elemencie_bez_pary(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Etapy w Logach z jednym więcej albo jednym mniej na końcu niż w odtworzeniu: wspólny początek się zgadza, więc
    pierwszą różnicą jest element bez pary, z wartością tam, gdzie jest, i „(brak)” tam, gdzie go nie ma."""

    change, place, present, absent = LENGTHS[case]
    produced = shared_logs("settlement")
    changed = _changed(produced, tmp_path, lambda record: change(record["phases"]))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert lines[3] == f"Pierwsza różnica: etapy (phases)[{place}]", lines
    shown = dict(line.strip().split(":", 1) for line in lines[4:6])
    assert (shown[absent].strip(), '"phase": "Zapisywanie"' in shown[present]) == ("(brak)", True), lines


# Komórka Kopii wejścia w Logach i w odtworzeniu (``None``: tej komórki po tej stronie nie ma) i czy porównanie
# odtworzenia ma w niej pierwszą różnicę (``_same`` w ``odtworzenie``).
CELLS: dict[str, tuple[object, object, bool]] = {
    "komorka_tylko_w_logach": ("wymiana", None, True),
    "komorka_tylko_w_odtworzeniu": (None, "wymiana", True),
    "liczba_przeciw_prawdzie": (1, True, True),
    "prawda_przeciw_falszowi": (True, False, True),
    "calkowita_przeciw_ulamkowi_tej_samej_wartosci": (5, 5.0, False),
}


@pytest.mark.parametrize("case", CELLS)
def test_porownanie_odtworzenia_rozni_brak_pola_i_prawde_od_liczby_a_nie_ulamek_od_calkowitej(shared_logs: Callable[[str], Produced], case: str) -> None:
    """Pierwszą różnicą jest pole, które ma tylko jedna strona (po drugiej „(brak)”), i prawda albo fałsz inne niż po
    drugiej stronie, także liczba 1 przeciw prawdzie; liczba całkowita i ułamek tej samej wartości różnicą nie są, bo
    zapis pliku zmienia 5.0 w 5."""

    logged, replayed, differs = CELLS[case]
    record = shared_logs("settlement").record

    def with_cell(value: object) -> RunLog:
        changed = copy.deepcopy(record)
        if value is not None:
            changed["input_copy"][0]["sheets"][0]["rows"][0]["cells"]["Z"] = value
        return RunLog.model_validate(changed)

    found = first_difference(with_cell(logged), with_cell(replayed))

    shown = ["(brak)" if value is None else value for value in (logged, replayed)]
    if differs:
        assert found is not None and (found.field.endswith(".cells.Z"), [found.logged, found.replayed]) == (True, shown), found
        assert [type(value) for value in (found.logged, found.replayed)] == [type(value) for value in shown]
    else:
        assert found is None


def test_wartosc_roznicy_do_300_znakow_raport_pokazuje_cala_a_dluzsza_ucina(shared_logs: Callable[[str], Produced]) -> None:
    """Wartość w pierwszej różnicy raport pokazuje w JSON najwyżej na 300 znakach: tyle mieści się cała, a dłuższa
    kończy się na 297 znakach i „...”."""

    record = RunLog.model_validate(shared_logs("settlement").record)
    whole, cut = "a" * 298, "b" * 299  # z cudzysłowami JSON 300 i 301 znaków

    lines = Report(Verdict.DIFFERS, Difference("pole", whole, cut), ()).lines(record, "kod")

    start = lines.index("Pierwsza różnica: pole")
    assert lines[start + 1 : start + 3] == [f'  Logi:        "{whole}"', f'  Odtworzenie: "{cut[:296]}...']


def test_kopia_intermax_bez_wiersza_nad_wklejeniem_stawia_dzien_gdzie_indziej_niz_u_taty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bez żółtego wiersza nad wklejeniem w Kopii wejścia odtworzenie stawia dzień pod ostatnim uporządkowanym wierszem,
    a nie pod żółtym, więc wiersze Wpisów urządzenia i czynności INTERMAX różnią się od Logów."""

    produced = _intermax(tmp_path / "taty")

    def without_yellow(record: dict[str, Any]) -> None:
        for sheet in record["input_copy"][0]["sheets"]:
            sheet["yellow_row"] = None

    changed = _changed(produced, tmp_path, without_yellow)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie")

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert lines[3].startswith("Pierwsza różnica: Wpisy INTERMAX (intermax_entries).rows")


def test_logi_z_wierszem_intermax_bez_wykonawcy_maja_go_w_kopii_w_jednym_polozeniu_i_odtwarzaja_sie_zgodnie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Wklejony wiersz bez Wykonawcy, który nie jest pierwszym wierszem bloku, pamięć reguły danych zna w jednym
    położeniu, pod nagłówkiem (ADR 0025), więc Kopia wejścia ma jego datę i numer zlecenia, a narzędzie odtwarza
    Uruchomienie zgodnie."""

    raw = (PASTED[0], replace(PASTED[1], worker=""), PASTED[2])
    produced = _intermax(tmp_path / "taty", Intermax(raw=raw))
    [sheet] = produced.record["input_copy"][0]["sheets"]
    [row] = [row for row in sheet["rows"] if row["row"] == sheet["rows"][1]["row"]]

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie")

    assert (sheet["uncertain_rows"], {"C", "I"} <= set(row["cells"])) == ([], True)
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def test_logi_z_przesunietym_wierszem_w_srodku_wklejenia_maja_uwage_o_fakcie_domeny_i_odtwarzaja_sie_z_zastrzezeniem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Przesunięty wiersz w środku wklejenia (pierwszy wiersz drugiego wklejenia) ma datę z godziną dwie kolumny przed
    ``DATA GODZ. POCZ.``: łamie fakt domeny, więc pamięć zna go w obu położeniach, a Logi mają o nim uwagę. Kopia nie
    ma jego komórek dozwolonych tylko w jednym położeniu, więc narzędzie odtwarza Uruchomienie z zastrzeżeniem o nich."""

    raw = (PASTED[0], PASTED[1], replace(PASTED[2], shifted=True), *PASTED[3:])
    produced = _intermax(tmp_path / "taty", Intermax(raw=raw))
    record = produced.record
    [sheet] = record["input_copy"][0]["sheets"]
    shifted = sheet["rows"][2]["row"]

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie")

    assert sheet["uncertain_rows"] == [shifted]
    assert [note for note in record["input_copy_notes"] if note.startswith("Fakt domeny złamany")] == [
        f"Fakt domeny złamany: wiersz {shifted} arkusza {sheet['sheet']} w {record['input_copy'][0]['name']} ma datę z "
        "godziną dwie kolumny na lewo od DATA GODZ. POCZ., a nie jest pierwszym wierszem bloku wklejenia; pamięć reguły "
        "danych zna go w obu położeniach (ADR 0025)."
    ]
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert (
        f"- Kopia wejścia ma wiersze INTERMAX w obu położeniach (arkusz {sheet['sheet']}, wiersze {shifted}): to wiersze "
        "z siatki reguły położenia (ślad przesunięcia albo pierwszy wiersz bloku, którego przesunięcia nie widać), a nie "
        "ma w nich komórek, które w którymś położeniu stałyby pod ADRES, NUMER UMOWY albo za UWAGI (NUMER "
        "ZL., ZWROT, UWAGI i DATA GODZ. POCZ., gdy nie jest datą z godziną), więc odtworzony wiersz ich nie ma, a reguła, "
        "która je czyta, może zdecydować inaczej (ADR 0025)"
    ) in lines


def test_logi_przygotowania_z_wierszem_rejestru_z_siatki_odtwarzaja_sie_z_zastrzezeniem_o_nim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Wiersz z wyglądem z aplikacji na miejscu na górze odczytu okresu zaczyna blok, a jego przesunięcia nie widać:
    pamięć zna go w obu położeniach, a Kopia wejścia Przygotowania ma go w ``uncertain_rows`` bez komórek dozwolonych
    tylko w jednym. Odtworzony Rejestr ma go znowu jako pierwszy wiersz bloku z nagłówkami wklejenia, więc Logi
    odtwarzają się zgodnie, a raport ma o nim zastrzeżenie."""

    def in_place_on_top(register: Path) -> None:
        paste_raw_orders(register, [register_order(1, datetime(2026, 9, 8, 9))], first=2, in_place_from="DATA GODZ. POCZ.")

    produced = _preparation(tmp_path / "taty", in_place_on_top)
    [sheet] = produced.record["input_copy"][0]["sheets"]

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", *produced.arguments)

    assert sheet["uncertain_rows"] == [2]
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    granice = lines[lines.index("Granice:") + 1 :]
    assert [line for line in granice if line.startswith(
        f"- Kopia wejścia ma wiersze Rejestru zleceń w obu położeniach (arkusz {sheet['sheet']}, wiersze 2): "
    )], granice


# Pierwszy wiersz bloku wklejenia przychodzi z aplikacji przesunięty o dwie kolumny w lewo (fakt domeny, ADR 0025): jego
# adres i numer Orange pamięć reguły danych zna tylko w położeniu przesuniętym, więc nie wychodzą, także zacytowane w
# wolnym tekście innego wiersza i w Uwadze taty, a URZĄDZENIA żadnego wiersza (w położeniu na miejscu stałoby tam, gdzie
# ADRES przesuniętego) nie są w Kopii zamaskowane.
FIRST_ADDRESS = "Przemiatana Wrzosowa 12 Kórnik"
FIRST_ORANGE = "4809876543"
QUOTED = f"montaż {FIRST_ADDRESS} umowa {FIRST_ORANGE}"
DONE = 13
"""``CZYNNOŚCI ZREALIZOWANE`` (M) INTERMAX, wolny tekst technika."""


def _leaked(texts: list[str]) -> list[str]:
    return [value for value in (FIRST_ADDRESS, FIRST_ORANGE) if any(value in text for text in texts)]


def test_przesuniety_pierwszy_wiersz_wklejenia_intermax_nie_wypuszcza_adresu_ani_numeru_orange_a_kopia_ma_urzadzenia_i_odtwarza_sie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Uporządkowanie INTERMAX z przesuniętym pierwszym wierszem wklejenia: jego adres i numer Orange nie wychodzą do
    pliku Logów, do Skrzynki ani w Uwadze taty, Kopia wejścia ma ``URZĄDZENIA`` każdego wiersza bez maski, a Logi
    odtwarzają się zgodnie."""

    first = replace(PASTED[0], cells=((ADDRESS, FIRST_ADDRESS), (CONTRACT_NUMBER, FIRST_ORANGE)))
    raw = (first, *PASTED[1:4], replace(PASTED[4], cells=((DONE, QUOTED),)))
    root = tmp_path / "taty"
    centrum = ordering_centrum(root, Intermax(raw=raw), clock=Clock([ORDERED_AT]))
    write_report_key(ToolDirectory(root))
    centrum.run_to_end()
    note = centrum.client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": QUOTED}).json()["body"]
    archived = _archive_file(centrum, root)
    record = json.loads(gzip.decompress(archived.read_bytes()))
    [sheet] = record["input_copy"][0]["sheets"]

    code, lines = _replayed(capsys, archived, "--na-tym-drzewie")

    files = [path.read_text(encoding="utf-8") for path in ToolDirectory(root).run_logs.glob("*")]
    assert _leaked([*files, gzip.decompress(archived.read_bytes()).decode("utf-8"), note]) == []
    assert [row["cells"]["G"] for row in sheet["rows"]] == [order.kind for order in raw]
    assert (sheet["shifted_row"], sheet["uncertain_rows"]) == (sheet["rows"][0]["row"], [])
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def test_przesuniety_pierwszy_wiersz_wklejenia_rejestru_nie_wypuszcza_adresu_ani_numeru_orange_z_przygotowania_i_odtwarza_sie(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Przygotowanie z przesuniętym pierwszym wierszem wklejenia na dole Rejestru zleceń (z dnia po okresie, więc go
    czyta, a nie zatrzymuje się): jego adres i numer Orange nie wychodzą do pliku Logów, do Skrzynki ani w Uwadze taty,
    Kopia wejścia ma ``URZĄDZENIA`` każdego wiersza bez maski, a Logi odtwarzają się zgodnie."""

    root = tmp_path / "taty"
    root.mkdir()
    centrum = preparing_centrum(root)
    probe = {**register_order(90, datetime(2026, 9, 15, 10)), "ADRES": FIRST_ADDRESS, "NUMER UMOWY": FIRST_ORANGE}
    later = {**register_order(91, datetime(2026, 9, 15, 12)), "CZYNNOŚCI ZREALIZOWANE": QUOTED}
    paste_raw_orders(centrum.fixture.register_path, [probe, later])
    write_report_key(ToolDirectory(root))
    run_to_end(centrum, dry_run=False)
    note = centrum.client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": QUOTED}).json()["body"]
    archived = _archive_file(centrum, root)
    record = json.loads(gzip.decompress(archived.read_bytes()))
    [sheet] = record["input_copy"][0]["sheets"]
    devices = next(letter for letter, name in sheet["columns"].items() if name == "URZĄDZENIA")

    code, lines = _replayed(capsys, archived, "--na-tym-drzewie", "--konfiguracja", root / "config")

    files = [path.read_text(encoding="utf-8") for path in ToolDirectory(root).run_logs.glob("*")]
    assert _leaked([*files, gzip.decompress(archived.read_bytes()).decode("utf-8"), note]) == []
    assert [row["cells"][devices] for row in sheet["rows"] if devices in row["cells"]][-1] == "dekoder"
    assert not any("[" in str(row["cells"].get(devices, "")) for row in sheet["rows"])
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def _guarded_with(produced: Produced, folder: Path, word: str) -> Path:
    """Plik Logów z Archiwum po strażniku, który zapamiętał ``word`` jako ADRES z pliku taty, jak ``guard_logs`` w Centrum."""

    forbidden = empty_memory()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, word)
    kept = guard_logs(RunLog.model_validate(produced.record), forbidden).record
    path = folder / produced.archived.stem
    path.write_text(kept.text, encoding="utf-8")
    return path


# Słowo z pliku taty, które strażnik maskuje w polu z zamkniętą listą, kod wyjścia odtworzenia i linia raportu: zlecenie
# śladu efenix („gotowe” w ``outcome``) i wiersz Kopii wejścia („datetime” w typie komórki z datą) to wejście
# odtworzenia, więc granica blokuje, a Komunikat („warning” w rodzaju) jest poza wejściem, więc zostaje zastrzeżeniem.
CUTS = {
    "zlecenie_sladu_efenix": (
        "gotowe",
        3,
        "NIE DA SIĘ ODTWORZYĆ: strażnik reguły danych pominął w Logach efenix_orders[0] (maska w polu, które jej nie "
        "przyjmuje), a odtworzenie buduje z niego wejście",
    ),
    "wiersz_kopii_wejscia": (
        "datetime",
        3,
        "NIE DA SIĘ ODTWORZYĆ: strażnik reguły danych pominął w Logach input_copy[0].sheets[0].rows[0] (maska w polu, "
        "które jej nie przyjmuje), a odtworzenie buduje z niego wejście",
    ),
    "komunikat": (
        "warning",
        1,
        "- Strażnik reguły danych pominął w Logach messages[0] (maska w polu, które jej nie przyjmuje): różnica w tym "
        "miejscu jest skutkiem maski",
    ),
}


@pytest.mark.parametrize("case", CUTS)
def test_element_ktory_straznik_pominal_w_logach_jest_granica_a_nie_falszywa_przyczyna_roznicy(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Maska strażnika w polu z zamkniętą listą zabiera z Logów Wyceny w efenix cały element z uwagą techniczną.
    Zlecenie śladu albo wiersz Kopii to wejście odtworzenia, więc odtworzenie kończy się granicą z tym miejscem, a nie
    różnicą z fałszywą przyczyną (nieznany numer w efenix); pominięty Komunikat stoi pod „Granice:” przy różnicy."""

    word, expected_code, expected = CUTS[case]
    produced = shared_logs("efenix")
    cut = _guarded_with(produced, tmp_path, word)

    code, lines = _replayed(capsys, cut, "--na-tym-drzewie", *produced.arguments)

    assert code == expected_code, lines
    if expected_code == 3:
        assert lines[0] == expected, lines
        assert not any(line.startswith("Pierwsza różnica") for line in lines), lines
    else:
        assert (lines[0], lines[3].startswith("Pierwsza różnica: Komunikaty (messages)")) == ("ODTWORZENIE RÓŻNE", True)
        assert expected in lines[lines.index("Granice:") + 1 :], lines


def test_logi_bez_kopii_wejscia_daja_granice_a_nie_zgodnosc(tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]) -> None:
    produced = shared_logs("settlement")
    changed = _changed(produced, tmp_path, lambda record: record.update(input_copy=None))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (
        3,
        "NIE DA SIĘ ODTWORZYĆ: Logi nie mają Kopii wejścia (Logi sprzed #841 albo Uporządkowanie sprzed #842)",
    )


def _commit_like_head(folder: Path, *, without: str | None = None, changed: tuple[str, bytes] | None = None) -> str:
    """Commit bez gałęzi z drzewem HEAD bez pliku ``without`` albo z inną treścią ``changed`` (ścieżka, bajty) jednego
    pliku: commit sprzed narzędzia odtwarzania albo z innym ``requirements.txt``, których płytki klon CI nie ma."""

    environment = os.environ | {"GIT_INDEX_FILE": str(folder / "indeks-commitu")}

    def git(*arguments: str, given: bytes | None = None) -> str:
        done = subprocess.run(["git", *arguments], cwd=ROOT, env=environment, input=given, capture_output=True, check=True)
        return done.stdout.decode("utf-8").strip()

    git("read-tree", "HEAD")
    if without is not None:
        git("update-index", "--force-remove", without)
    if changed is not None:
        path, content = changed
        blob = git("hash-object", "-w", "--stdin", given=content)
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
    return git("commit-tree", git("write-tree"), "-p", "HEAD", "-m", "commit z Logów w teście odtworzenia")


def test_commit_z_logow_sprzed_narzedzia_odtwarzania_konczy_sie_granica(tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]) -> None:
    """Commit z Logów, w którym nie ma narzędzia odtwarzania (sprzed #847), nie odtwarza się na swojej kopii: kod 3 z
    podpowiedzią ``--na-tym-drzewie``."""

    produced = shared_logs("settlement")
    commit = _commit_like_head(tmp_path, without="tools/odtworz_uruchomienie.py")
    logs = _changed(produced, tmp_path, lambda record: record["tool"].update(commit=commit))

    assert _replayed(capsys, logs, *produced.arguments) == (
        3,
        [
            f"NIE DA SIĘ ODTWORZYĆ: commit {commit} jest sprzed narzędzia odtwarzania (#847); odtwórz na kodzie tego "
            "checkoutu (--na-tym-drzewie)"
        ],
    )


def test_kopia_commitu_z_logow_dostaje_parametry_narzedzia_i_granice_innych_bibliotek(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Kopia commitu z Logów Wyceny w efenix odtwarza z dniem Atrapy i folderem do zachowania z parametrów narzędzia
    (bez dnia Atrapy Wycena różni się od Logów), a ``requirements.txt`` commitu inny niż tego checkoutu raport podaje
    jako granicę. Błąd w kopii (folder do zachowania nie jest pusty) narzędzie oddaje na swój stderr z jej kodem."""

    produced = shared_logs("efenix")
    requirements = (ROOT / "requirements.txt").read_bytes() + b"# inne biblioteki commitu z Logow\n"
    commit = _commit_like_head(tmp_path, changed=("requirements.txt", requirements))
    logs = _changed(produced, tmp_path, lambda record: record["tool"].update(commit=commit))
    kept = tmp_path / "odtworzenie"

    code, lines = _replayed(capsys, logs, "--zachowaj", kept, *produced.arguments)
    again = odtworz_uruchomienie.main([str(logs), "--zachowaj", str(kept), *produced.arguments])
    shown = capsys.readouterr()

    assert (code, lines[0], lines[2]) == (0, "ODTWORZENIE ZGODNE", f"Kod: commit {commit} z Logów, w osobnym drzewie"), lines
    assert "- requirements.txt commitu różni się od tego checkoutu: odtworzenie biegło bibliotekami .venv tego checkoutu" in lines
    assert (kept / "odtworzone-logi.json").is_file()
    assert (again, shown.out, shown.err) == (2, "", f"BŁĄD: folder {kept.resolve()} nie jest pusty\n")


def _tool_process(logs: Path, *arguments: str | Path, tool: Path = TOOL, path: Path) -> subprocess.CompletedProcess[str]:
    """Narzędzie odtwarzania ``tool`` jako osobny proces z ``path`` w ``PYTHONPATH`` przed instalacją pakietu."""

    return subprocess.run(
        [sys.executable, str(tool), str(logs), "--na-tym-drzewie", *map(str, arguments)],
        cwd=path,
        env=os.environ | {"PYTHONPATH": str(path), "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


def test_narzedzie_jako_proces_odtwarza_kodem_swojego_drzewa_a_nie_innym_pakietem_rozliczenia(tmp_path: Path, shared_logs: Callable[[str], Produced]) -> None:
    """Narzędzie uruchomione jako proces bierze pakiet ``rozliczenia`` ze swojego drzewa, choć inny pakiet o tej
    nazwie stoi wcześniej na ścieżce (``PYTHONPATH``, instalacja innego checkoutu), więc odtwarza kodem tego drzewa."""

    produced = shared_logs("settlement")
    other = tmp_path / "inny-pakiet"
    (other / "rozliczenia").mkdir(parents=True)
    (other / "rozliczenia" / "__init__.py").write_text("", encoding="utf-8")

    done = _tool_process(produced.archived, *produced.arguments, path=other)

    assert (done.returncode, done.stdout.splitlines()[:1]) == (0, ["ODTWORZENIE ZGODNE"]), done.stderr


def test_narzedzie_w_drzewie_bez_kodu_procesu_nie_odtwarza_kodem_innego_checkoutu(tmp_path: Path, shared_logs: Callable[[str], Produced]) -> None:
    """Narzędzie z drzewa bez ``src`` (kopia samych narzędzi) dostałoby pakiet ``rozliczenia`` innego checkoutu, więc
    nie odtwarza: kod 2 z błędem na stderr, który nazywa oba miejsca."""

    produced = shared_logs("settlement")
    tree = tmp_path / "same-narzedzia"
    for source in (TOOL, ROOT / "tools" / "lib" / "potomne.py", ROOT / "tools" / "lib" / "repo.py"):
        copied = tree / source.relative_to(ROOT)
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(source.read_bytes())

    done = _tool_process(produced.archived, *produced.arguments, tool=tree / "tools" / "odtworz_uruchomienie.py", path=ROOT / "src")

    assert (done.returncode, done.stdout) == (2, ""), done.stderr
    assert done.stderr == f"BŁĄD: rozliczenia z {ROOT / 'src' / 'rozliczenia' / '__init__.py'}, a nie z {tree.resolve() / 'src'}\n"


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_odtworzenie_biegnie_na_kopii_commitu_z_logow_jej_wlasnym_narzedziem(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Bez ``--na-tym-drzewie`` narzędzie robi kopię commitu z Logów i odtwarza w niej; commitu, którego nie ma w
    repozytorium, nie odtwarza."""

    produced = shared_logs("settlement")
    head = _head()
    at_head = _changed(produced, tmp_path, lambda record: record["tool"].update(commit=head))

    code, lines = _replayed(capsys, at_head, *produced.arguments)

    assert (code, lines[0], lines[2]) == (0, "ODTWORZENIE ZGODNE", f"Kod: commit {head} z Logów, w osobnym drzewie"), lines

    unknown = "0" * 40
    (tmp_path / "nieznany").mkdir()
    elsewhere = _changed(produced, tmp_path / "nieznany", lambda record: record["tool"].update(commit=unknown))

    code, lines = _replayed(capsys, elsewhere, *produced.arguments)

    assert (code, lines) == (
        3,
        [
            f"NIE DA SIĘ ODTWORZYĆ: commitu {unknown} nie ma w tym repozytorium; pobierz go (git fetch origin) albo "
            "odtwórz na kodzie tego checkoutu (--na-tym-drzewie)"
        ],
    )


@contextmanager
def _fake_gh(folder: Path, archived: Path | None) -> Iterator[Path]:
    """``gh`` na początku ``PATH``, który zapisuje swoje argumenty i kładzie plik ``archived`` w folderze ``--dir``
    (``None``: kończy się kodem 0 bez pliku)."""

    calls = folder / "wywolania.json"
    lays = "" if archived is None else f"shutil.copy({str(archived)!r}, directory / sys.argv[sys.argv.index('--pattern') + 1])\n"
    fake_cli(
        folder,
        "gh",
        "import json, shutil, sys\n"
        "from pathlib import Path\n"
        f"Path({str(calls)!r}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "directory = Path(sys.argv[sys.argv.index('--dir') + 1])\n" + lays,
    )
    path = os.environ["PATH"]
    os.environ["PATH"] = f"{folder}{os.pathsep}{path}"
    try:
        yield calls
    finally:
        os.environ["PATH"] = path


def test_odnosnik_z_komentarza_logow_pobiera_plik_z_archiwum_przez_gh_i_odtwarza_go(
    tmp_path: Path, shared_logs: Callable[[str], Produced], capsys: pytest.CaptureFixture[str]
) -> None:
    """Odnośnik do pliku w Archiwum Logów okresu z komentarza Logów to ``gh release download`` z tagiem okresu i nazwą
    pliku w repozytorium Zgłoszeń; pobrany plik odtwarza się tak jak plik z dysku. Odnośnika spoza GitHuba ani spoza
    plików GitHub Release narzędzie nie pobiera."""

    produced = shared_logs("settlement")
    name = produced.archived.name
    tag = f"logi-{PERIOD}"
    link = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"

    with _fake_gh(tmp_path / "gh", produced.archived) as calls:
        elsewhere = _replayed(capsys, link.replace("https://github.com/", "https://example.invalid/"), "--na-tym-drzewie")
        not_release = _replayed(capsys, link.replace("/releases/download/", "/archive/download/"), "--na-tym-drzewie")
        assert (elsewhere[0], not_release[0], calls.exists()) == (2, 2, False), (elsewhere, not_release)
        code, lines = _replayed(capsys, link, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    arguments = json.loads(calls.read_text(encoding="utf-8"))
    assert arguments[:7] == ["release", "download", tag, "--repo", REPOSITORY, "--pattern", name]


def test_gh_bez_pobranego_pliku_daje_blad_a_nie_odtworzenie(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``gh release download``, które kończy się kodem 0, a pliku nie kładzie, to błąd pobrania z Archiwum (kod 2)."""

    name = "20261111T000000Z-settlement-0.json.gz"
    tag = f"logi-{PERIOD}"

    with _fake_gh(tmp_path / "gh", None):
        code = odtworz_uruchomienie.main([f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}", "--na-tym-drzewie"])

    shown = capsys.readouterr()
    assert (code, shown.out, shown.err) == (2, "", f"BŁĄD: gh release download nie pobrał {name} z {REPOSITORY} {tag}: \n")
