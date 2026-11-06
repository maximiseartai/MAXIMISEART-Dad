"""Logi Uruchomienia w Skrzynce Zgłoszeń (ADR 0015, #320, #844) przez HTTP API Centrum z fałszywą Skrzynką.

Maks czyta w Skrzynce jedno issue na okres, a w nim jeden komentarz na każde Uruchomienie: podsumowanie i odnośnik do
pełnych Logów w Archiwum Logów okresu (GitHub Release ``logi-<okres>``), gdzie leży plik o nazwie pliku Logów, który
rozpakowany jest plikiem Logów z komputera taty. Diagnoza (#321) dopisuje się do pliku, podmienia go w Archiwum i
zmienia komentarz swojego Uruchomienia (#840), a Zgłoszenie prowadzi do komentarza Logów swojego Uruchomienia. Plik z
Archiwum każdego procesu odtwarza się narzędziem odtwarzania (``tools/odtworz_uruchomienie.py``, #847) z tym samym wynikiem
i śladem. Żaden test nie łączy się z GitHubem.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
import gzip
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import ModuleType
from typing import Any, Final

import pytest

from rozliczenia import intermax_copies
from rozliczenia.centrum import app
from rozliczenia.centrum.outbox import RETRY_S
from rozliczenia.centrum.report_box import REPOSITORY, Refused, Unreachable
from rozliczenia.centrum.run_logs import RunLog, guarded
from rozliczenia.client_data import ForbiddenColumn, ForbiddenValues

from tests.fixtures.atrapa_efenix import PRICES, TODAY, AtrapaOrder, Changed, amount_of, atrapa_efenix
from tests.fixtures.centrum import TOOL_COMMIT, FakeIssue, FakeReportBox, finished_view, views_until
from tests.fixtures.centrum_intermax import Clock, ordering_centrum
from tests.fixtures.efenix import Order as EfenixOrder
from tests.fixtures.efenix import write_collective_file
from tests.fixtures.intermax import ADDRESS, CONTRACT_NUMBER, Intermax, Order
from tests.fixtures.konce_linii_windows import windows_text_writes
from tests.fixtures.centrum_processes import (
    SettlingCentrum,
    Surroundings,
    preparing_centrum,
    run_logs_handled,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from tests.fixtures.potomne import wait_for
from tests.fixtures.preparation import INTERNAL_SETTLEMENT_NAME, incomplete_period_rows, paste_raw_orders, register_order
from tests.fixtures.settlement import PERIOD

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
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
        write_key(centrum)
    return centrum


def write_key(centrum: SettlingCentrum) -> None:
    (centrum.tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")


def box(centrum: SettlingCentrum) -> FakeReportBox:
    return centrum.surroundings.report_box


def threads(fake: FakeReportBox) -> list[FakeIssue]:
    return [issue for issue in fake.issues_with(LABEL) if issue.title == f"Logi Uruchomienia {PERIOD}"]


def thread_with(centrum: SettlingCentrum, comments: int) -> FakeIssue:
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
    """Jedyny komentarz issue Logów okresu, gdy Skrzynka zmieniła już ``edits`` komentarzy, a kolejka Logów jest pusta."""

    assert box(centrum).wait_until(lambda fake: len(fake.edited) == edits), f"Skrzynka nie ma {edits} poprawek"
    [comment] = thread_with(centrum, comments=1).comments
    return comment


def diagnosed_logs(centrum: SettlingCentrum, edits: int) -> dict[str, Any]:
    """Logi z pliku w Archiwum, do którego prowadzi komentarz po ``edits`` poprawkach (``diagnosed_comment``)."""

    logs: dict[str, Any] = json.loads(archived(centrum, diagnosed_comment(centrum, edits)))
    return logs


def local_path(centrum: SettlingCentrum, run_id: str) -> Path:
    [path] = (centrum.log_path.parent / "uruchomienia").glob(f"*-{run_id}.json")
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

    return sorted((centrum.tmp_path / "config" / "zgloszenia" / "kolejka").glob(f"*-{LABEL}-*.json"))


def test_pierwsze_uruchomienie_okresu_zaklada_issue_i_archiwum_logow_a_kolejne_dopisuja_komentarze_i_pliki_takze_po_zamknieciu(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    foreign = [
        FakeIssue(1, LABEL, "Logi Uruchomienia 01_07_09_2026", "- Logi Uruchomienia okresu: 01_07_09_2026\n"),
        FakeIssue(2, LABEL, f"Logi Uruchomienia {PERIOD}0", f"- Logi Uruchomienia okresu: {PERIOD}0\n"),
        FakeIssue(3, "zgloszenie", "BRAK_WZORCA: Nie znaleziono wzorca.", f"## Komunikat\n\n{LINE}\n"),
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


def _broken_worker_config(centrum: SettlingCentrum) -> None:
    centrum.configuration.worker_config.write_text(":: nie yaml", encoding="utf-8")


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
        _broken_worker_config,
        False,
        False,
        ["- Wynik: BLAD_KRYTYCZNY, Zatrzymanie do Maksa", "- Komunikaty: `ZLA_KONFIGURACJA_WYKONAWCOW` (Zatrzymanie)"],
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
    assert [path.name for path in (tmp_path / "config" / "zgloszenia").iterdir()] == ["kolejka"]
    assert (box(centrum).issues, box(centrum).archives) == ([], [])

    box(centrum).search_failure = None
    write_key(centrum)
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
    workers = centrum.configuration.worker_config
    workers.write_bytes("wykonawcy: [".encode())
    not_yaml = diagnose(centrum, run_id)
    sent = [diagnosed_logs(centrum, edits=1)]

    workers.write_bytes("wykonawcy: ż".encode("cp1250"))
    not_utf8 = diagnose(centrum, run_id)

    sent.append(diagnosed_logs(centrum, edits=2))
    label = "Konfiguracja wykonawców"
    assert [diagnosis["explanation"] for diagnosis in (not_yaml, not_utf8)] == [not_yaml["explanation"]] * 2
    assert check_detail(not_yaml, label) != check_detail(not_utf8, label)
    logged = [logs["diagnosis"] for logs in sent]
    checks = [next(check for check in diagnosis["checks"] if check["label"] == label) for diagnosis in logged]
    assert [(check["code"], check["detail"]) for check in checks] == [
        ("ZLA_KONFIGURACJA_WYKONAWCOW", check_detail(diagnosis, label)) for diagnosis in (not_yaml, not_utf8)
    ]


def test_plik_logow_ktory_nie_powstal_przy_diagnozie_powstaje_przy_nastepnej_z_tym_samym_wynikiem(
    tmp_path: Path,
) -> None:
    centrum = watched_centrum(tmp_path)
    run_id = unexpected_exception(centrum)
    thread_with(centrum, comments=1)
    [path] = (centrum.log_path.parent / "uruchomienia").glob(f"*-{run_id}.json")
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
    assert archived(centrum, thread.comments[1]).startswith(('{\n  "schema_version": 2,\n  "run_id": "' + run_id).encode())


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
    blocked = centrum.log_path.parent / "uruchomienia"
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


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("odtworz_uruchomienie", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _replayed(capsys: pytest.CaptureFixture[str], *arguments: str | Path) -> tuple[int, list[str]]:
    """Kod wyjścia narzędzia i linie jego raportu."""

    code = _tool().main([str(argument) for argument in arguments])
    return code, capsys.readouterr().out.splitlines()


def _archive_file(fake: FakeReportBox, folder: Path) -> Path:
    """Plik Logów z Archiwum Logów okresu fałszywej Skrzynki, spakowany gzipem, jak go pobiera Maks."""

    assert fake.wait_until(lambda box: any(archive.assets for archive in box.archives)), "plik Logów nie doszedł do Archiwum"
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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    assert run_to_end(centrum, dry_run=True)["result"]["result"] == "OK"
    return Produced(_archive_file(centrum.surroundings.report_box, tmp_path), ("--konfiguracja", str(tmp_path / "config")))


def _preparation(tmp_path: Path) -> Produced:
    tmp_path.mkdir()
    centrum = preparing_centrum(tmp_path)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    configuration = {centrum.fixture.config_path.parent, centrum.fixture.internal_template_path.parent}
    assert configuration == {tmp_path / "config"}
    return Produced(_archive_file(centrum.surroundings.report_box, tmp_path), ("--konfiguracja", str(tmp_path / "config")))


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
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    centrum.run_to_end()
    return Produced(_archive_file(centrum.surroundings.report_box, tmp_path), ())


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


def _efenix(tmp_path: Path, in_efenix: list[AtrapaOrder] | None = None, result: str = "WYMAGA_SPRAWDZENIA") -> Produced:
    with atrapa_efenix(in_efenix or IN_EFENIX, prices=_TATA_PRICES) as atrapa:
        centrum = settling_centrum(tmp_path, surroundings=Surroundings(efenix_url=atrapa.url))
        write_collective_file(centrum.period_parent, PRICED)
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
        started = centrum.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "dry_run": False})
        assert started.status_code == 200, started.json()
        assert finished_view(centrum.client)["result"]["result"] == result
    return Produced(_archive_file(centrum.surroundings.report_box, tmp_path), ("--efenix-dzis", TODAY.isoformat()))


PROCESSES = {"settlement": _settlement, "preparation": _preparation, "intermax": _intermax, "efenix": _efenix}


@pytest.mark.parametrize("process", PROCESSES)
def test_logi_z_archiwum_kazdego_procesu_odtwarzaja_sie_z_tym_samym_wynikiem_i_sladem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], process: str
) -> None:
    """Plik z Archiwum Logów okresu, który wyprodukowało Uruchomienie procesu z Centrum, odtwarza się na tym kodzie z
    tymi samymi wynikiem, Komunikatami, podsumowaniem, etapami i śladem (Szablony pracownika, Wpisy INTERMAX z
    wierszami dnia, ślad zleceń efenix z odczytem każdej strony), a pliki, które odtworzenie zapisuje, zostają w jego
    katalogu roboczym."""

    produced = PROCESSES[process](tmp_path / "taty")
    record = produced.record
    kept = tmp_path / "odtworzenie"

    code, lines = _replayed(capsys, produced.archived, "--na-tym-drzewie", "--zachowaj", kept, *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    assert lines[1] == f"Uruchomienie: {_title(record)}, {record['mode']}, okres {record['period']}, {produced.archived.stem}"
    replayed = json.loads((kept / "odtworzone-logi.json").read_text(encoding="utf-8"))
    assert (replayed["process"], replayed["mode"], replayed["result"]) == (process, record["mode"], record["result"])
    trace = {"settlement": "templates", "preparation": "summary", "intermax": "intermax_entries", "efenix": "efenix_orders"}
    assert record[trace[process]], "ślad, który odtworzenie porównało, nie jest pusty"
    if process == "intermax":
        assert record["intermax_entries"]["rows"], "wiersze dnia w śladzie"
        assert (kept / "Kopie INTERMAX" / INTERMAX_COPY).is_file()
        assert not (intermax_copies.default_directory() / INTERMAX_COPY).exists(), "Kopia INTERMAX poza katalogiem odtworzenia"
    if process == "efenix":
        actions = {step["action"] for order in record["efenix_orders"] for step in order["steps"]}
        assert actions == {"szukanie", "otwarcie zlecenia", "data wykonania", "Wycena Emmetta", "ilość"}


def _title(record: dict[str, Any]) -> str:
    return {
        "settlement": "Przebieg rozliczeń",
        "preparation": "Przygotowanie pliku zbiorczego",
        "intermax": "Uporządkowanie INTERMAX",
        "efenix": "Wycena w efenix",
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
    (folder / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]
    centrum.client.post(f"/api/runs/{waiting['run']['id']}/decision", json={"answer": answer})
    finished_view(centrum.client)
    produced = Produced(_archive_file(centrum.surroundings.report_box, folder), ("--konfiguracja", str(folder / "config")))
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
    record["environment"]["files"] = [{"name": "worker_mapping.yaml", "size": 1, "online_only": None}]


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
    "bez_folderu_konfiguracji": (lambda record: None, "nie-ma", 3, "NIE DA SIĘ ODTWORZYĆ: nie ma folderu z Konfiguracją"),
    "maska_strazinka_w_kopii": (
        _cell_with_phone,
        None,
        0,
        "- Kopia wejścia ma maski strażnika reguły danych ([telefon] ×1): odtworzenie czyta maskę w miejscu wartości taty",
    ),
    "inny_rozmiar_konfiguracji": (_other_config_size, None, 0, "- Konfiguracja wykonawców i Wzorce nie są w Logach"),
}


@pytest.mark.parametrize("case", LIMITS)
def test_granica_logow_jest_w_raporcie_a_blokujaca_konczy_odtworzenie_bez_zgodnosci(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Czego Logi nie niosą, raport mówi: Urwane Uruchomienie, pusta Kopia wejścia, komórka typu spoza Kopii i brak
    folderu Konfiguracji kończą odtworzenie bez uruchomienia procesu (kod 3), a maska strażnika w Kopii i Konfiguracja
    innego rozmiaru niż u taty stoją pod „Granice:” przy zgodnym odtworzeniu."""

    change, folder, expected_code, expected = LIMITS[case]
    produced = _settlement(tmp_path / "taty")
    changed = _changed(produced, tmp_path, change)
    configuration = tmp_path / "taty" / "config" if folder is None else tmp_path / folder

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", "--konfiguracja", configuration)

    assert code == expected_code, lines
    if expected_code == 3:
        assert lines[0].startswith(expected) and not any(line.startswith("Pierwsza różnica") for line in lines), lines
    else:
        assert lines[0] == "ODTWORZENIE ZGODNE"
        granice = lines[lines.index("Granice:") + 1 :]
        assert [line for line in granice if line.startswith(expected)], granice
    if case == "inny_rozmiar_konfiguracji":
        size = (configuration / "worker_mapping.yaml").stat().st_size
        assert any(line.endswith(f"inny rozmiar niż u taty: worker_mapping.yaml: u taty 1 B, tu {size} B") for line in lines)


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
        "wyjątki rozliczenia.message.StopError ← rozliczenia.efenix_pricing.UnexpectedPage"
    ), cause


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


def _changed(produced: Produced, folder: Path, change: Any) -> Path:
    """Plik Logów z Archiwum po zmianie ``change`` (słownik Logów → nic), zapisany jako plik z dysku taty."""

    record = produced.record
    change(record)
    path = folder / produced.archived.stem
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_celowo_zmieniona_kopia_wejscia_daje_wydruk_pierwszej_roznicy_a_nie_zgodnosc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Wiersz Kopii wejścia z innym Wykonawcą niż ten, z którego Przebieg rozliczeń policzył Logi: odtworzenie liczy z
    Kopii, więc pierwsza różnica to liczba zleceń Rozliczenia pracownika w podsumowaniu, z wartością w Logach i w
    odtworzeniu, a raport mówi, co porównał."""

    produced = _settlement(tmp_path / "taty")

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


def test_strona_efenix_inna_niz_w_odczycie_z_logow_daje_roznice_w_sladzie_zlecen(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Atrapa efenix ma stronę z odczytów stron w Logach: odczyt wiersza listy zmieniony w Logach (status „Do wyceny”
    zamiast innego) zmienia, co okno widzi w odtworzeniu, więc Komunikat tego zlecenia różni się od Komunikatu w Logach."""

    produced = _efenix(tmp_path / "taty")

    def ready_status(record: dict[str, Any]) -> None:
        [result] = record["efenix_orders"][2]["steps"][0]["results"]
        assert result["status"] == "W realizacji"
        result["status"] = "Do wyceny"

    changed = _changed(produced, tmp_path, ready_status)

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert lines[3] == "Pierwsza różnica: Komunikaty (messages)[1: kod EFENIX_INNY_STATUS].code"


def test_kopia_wejscia_bez_folderow_nad_plikiem_daje_roznice_w_kopii_a_nie_zgodnosc(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kopia wejścia bez nazw folderów nad plikiem (Logi sprzed #847): odbudowa kładzie Plik zbiorczy w folderze okresu,
    więc Kopia odtworzenia ma foldery, których Kopia w Logach nie ma, a pierwszą różnicą jest Kopia wejścia."""

    produced = _settlement(tmp_path / "taty")
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
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dzień, który okno wpisało w datę wykonania, Atrapa z Logów bierze z Pliku zbiorczego, nie z kroku śladu: inny
    dzień w śladzie zleceń efenix w Logach nie zmienia Komunikatów, a odtworzenie zgłasza różnicę w tym kroku śladu."""

    produced = _efenix(tmp_path / "taty")

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
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Etapy w Logach z jednym więcej albo jednym mniej na końcu niż w odtworzeniu: wspólny początek się zgadza, więc
    pierwszą różnicą jest element bez pary, z wartością tam, gdzie jest, i „(brak)” tam, gdzie go nie ma."""

    change, place, present, absent = LENGTHS[case]
    produced = _settlement(tmp_path / "taty")
    changed = _changed(produced, tmp_path, lambda record: change(record["phases"]))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (1, "ODTWORZENIE RÓŻNE"), lines
    assert lines[3] == f"Pierwsza różnica: etapy (phases)[{place}]", lines
    shown = dict(line.strip().split(":", 1) for line in lines[4:6])
    assert (shown[absent].strip(), '"phase": "Zapisywanie"' in shown[present]) == ("(brak)", True), lines



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
    (root / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    centrum.run_to_end()
    note = centrum.client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": QUOTED}).json()["body"]
    archived = _archive_file(centrum.surroundings.report_box, root)
    record = json.loads(gzip.decompress(archived.read_bytes()))
    [sheet] = record["input_copy"][0]["sheets"]

    code, lines = _replayed(capsys, archived, "--na-tym-drzewie")

    files = [path.read_text(encoding="utf-8") for path in (root / "logs" / "uruchomienia").glob("*")]
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
    (root / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    run_to_end(centrum, dry_run=False)
    note = centrum.client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": QUOTED}).json()["body"]
    archived = _archive_file(centrum.surroundings.report_box, root)
    record = json.loads(gzip.decompress(archived.read_bytes()))
    [sheet] = record["input_copy"][0]["sheets"]
    devices = next(letter for letter, name in sheet["columns"].items() if name == "URZĄDZENIA")

    code, lines = _replayed(capsys, archived, "--na-tym-drzewie", "--konfiguracja", root / "config")

    files = [path.read_text(encoding="utf-8") for path in (root / "logs" / "uruchomienia").glob("*")]
    assert _leaked([*files, gzip.decompress(archived.read_bytes()).decode("utf-8"), note]) == []
    assert [row["cells"][devices] for row in sheet["rows"] if devices in row["cells"]][-1] == "dekoder"
    assert not any("[" in str(row["cells"].get(devices, "")) for row in sheet["rows"])
    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines


def _guarded_with(produced: Produced, folder: Path, word: str) -> Path:
    """Plik Logów z Archiwum po strażniku, który zapamiętał ``word`` jako ADRES z pliku taty, jak ``guarded`` w Centrum."""

    forbidden = ForbiddenValues()
    forbidden.remember_value(ForbiddenColumn.ADDRESS, word)
    kept = guarded(RunLog.model_validate(produced.record), forbidden)
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
    tmp_path: Path, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    """Maska strażnika w polu z zamkniętą listą zabiera z Logów Wyceny w efenix cały element z uwagą techniczną.
    Zlecenie śladu albo wiersz Kopii to wejście odtworzenia, więc odtworzenie kończy się granicą z tym miejscem, a nie
    różnicą z fałszywą przyczyną (nieznany numer w efenix); pominięty Komunikat stoi pod „Granice:” przy różnicy."""

    word, expected_code, expected = CUTS[case]
    produced = _efenix(tmp_path / "taty")
    cut = _guarded_with(produced, tmp_path, word)

    code, lines = _replayed(capsys, cut, "--na-tym-drzewie", *produced.arguments)

    assert code == expected_code, lines
    if expected_code == 3:
        assert lines[0] == expected, lines
        assert not any(line.startswith("Pierwsza różnica") for line in lines), lines
    else:
        assert (lines[0], lines[3].startswith("Pierwsza różnica: Komunikaty (messages)")) == ("ODTWORZENIE RÓŻNE", True)
        assert expected in lines[lines.index("Granice:") + 1 :], lines


def test_logi_bez_kopii_wejscia_daja_granice_a_nie_zgodnosc(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    produced = _settlement(tmp_path / "taty")
    changed = _changed(produced, tmp_path, lambda record: record.update(input_copy=None))

    code, lines = _replayed(capsys, changed, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (
        3,
        "NIE DA SIĘ ODTWORZYĆ: Logi nie mają Kopii wejścia (Logi sprzed #841 albo Uporządkowanie sprzed #842)",
    )


def _head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_odtworzenie_biegnie_na_kopii_commitu_z_logow_jej_wlasnym_narzedziem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bez ``--na-tym-drzewie`` narzędzie robi kopię commitu z Logów i odtwarza w niej; commitu, którego nie ma w
    repozytorium, nie odtwarza."""

    produced = _settlement(tmp_path / "taty")
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
def _fake_gh(folder: Path, archived: Path) -> Iterator[Path]:
    """``gh`` na początku ``PATH``, który zapisuje swoje argumenty i kładzie plik ``archived`` w folderze ``--dir``."""

    folder.mkdir()
    script = folder / "gh.py"
    calls = folder / "wywolania.json"
    script.write_text(
        "import json, shutil, sys\n"
        "from pathlib import Path\n"
        f"Path({str(calls)!r}).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
        "directory = Path(sys.argv[sys.argv.index('--dir') + 1])\n"
        f"shutil.copy({str(archived)!r}, directory / sys.argv[sys.argv.index('--pattern') + 1])\n",
        encoding="utf-8",
    )
    if sys.platform == "win32":
        (folder / "gh.cmd").write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = folder / "gh"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    path = os.environ["PATH"]
    os.environ["PATH"] = f"{folder}{os.pathsep}{path}"
    try:
        yield calls
    finally:
        os.environ["PATH"] = path


def test_odnosnik_z_komentarza_logow_pobiera_plik_z_archiwum_przez_gh_i_odtwarza_go(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Odnośnik do pliku w Archiwum Logów okresu z komentarza Logów to ``gh release download`` z tagiem okresu i nazwą
    pliku w repozytorium Zgłoszeń; pobrany plik odtwarza się tak jak plik z dysku. Odnośnika spoza GitHuba narzędzie nie
    pobiera."""

    produced = _settlement(tmp_path / "taty")
    name = produced.archived.name
    tag = f"logi-{PERIOD}"
    link = f"https://github.com/{REPOSITORY}/releases/download/{tag}/{name}"

    with _fake_gh(tmp_path / "gh", produced.archived) as calls:
        elsewhere = _replayed(capsys, link.replace("https://github.com/", "https://example.invalid/"), "--na-tym-drzewie")
        assert (elsewhere[0], calls.exists()) == (2, False), elsewhere
        code, lines = _replayed(capsys, link, "--na-tym-drzewie", *produced.arguments)

    assert (code, lines[0]) == (0, "ODTWORZENIE ZGODNE"), lines
    arguments = json.loads(calls.read_text(encoding="utf-8"))
    assert arguments[:7] == ["release", "download", tag, "--repo", REPOSITORY, "--pattern", name]
