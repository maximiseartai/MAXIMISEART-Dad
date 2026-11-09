"""Czasy CI: zadanie zapisuje czas każdej jednostki swojej pracy, a Required na main scala zapisy runu w ``czasy-ci``.

Zapis zadania bierze testy z junit pytest, jednostki zmierzone przez ``tools/ci/wykonaj_zadanie.py`` i kroki CI z API zadań
runu. Wejście, którego brakuje albo którego nie da się odczytać, jest zgłoszone linią ``CZASY CI FAIL``, a reszta
pomiaru zostaje.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time
import tomllib
from typing import NoReturn
import zipfile

import pytest

from tests.fixtures.ci_workflow import jobs
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, fake_cli

import czasy_ci
from github import GhApi
import niestabilne_testy
import plan_runu
import wykonaj_zadanie
import wyniki_testow
import zapis_czasow
from zakres_runu import MUTACJE, TORY
from zapis_czasow import KROKI, main

ROOT = Path(__file__).resolve().parents[1]

RUNNER = "GitHub Actions 1000012606"
ENV = {
    "GITHUB_JOB": "pytest",
    "RUNNER_NAME": RUNNER,
    "GITHUB_RUN_ID": "40259456807",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_EVENT_NAME": "push",
    "GITHUB_SHA": "31bb76513d0bce91cdba28d09f61d07431ee4028",
    "GITHUB_REPOSITORY": "MAXIMISEART-AI/MAXIMISEART-Dad",
    "GH_TOKEN": "token-testu",
}
# junit pytest -n 4 z junit_family = xunit1: na Windows ścieżka z ukośnikami wstecznymi, test w klasie, porażka
# testu, błąd fixture, pominięty test i plik, którego nie dało się zaimportować.
JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="7">
<testcase classname="tests.test_b" name="test_ok" file="tests\\test_b.py" line="3" time="0.100" />
<testcase classname="tests.test_b.TestK" name="test_w_klasie" file="tests\\test_b.py" line="9" time="0.200" />
<testcase classname="tests.test_a" name="test_zly" file="tests/test_a.py" line="7" time="1.500"><failure message="assert False">E</failure></testcase>
<testcase classname="tests.test_c" name="test_fixture" file="tests/test_c.py" line="26" time="0.25371"><error message="failed on setup">E</error></testcase>
<testcase classname="tests.test_d" name="test_pominiety" file="tests/test_d.py" line="11" time="0.000"><skipped message="skip">s</skipped></testcase>
<testcase classname="tests.test_d" name="test_ok" file="tests/test_d.py" line="15" time="2.000" />
<testcase classname="" name="tests.test_e" file="tests/test_e.py" time="0.000"><error message="collection failure">E</error></testcase>
</testsuite></testsuites>
"""
def _step(name: str, conclusion: str, started: str, completed: str) -> dict[str, str | None]:
    times = {"started_at": f"2026-10-26T{started}Z", "completed_at": f"2026-10-26T{completed}Z"}
    return {"name": name, "conclusion": conclusion, **times}


def _running(step: dict[str, str | None]) -> dict[str, str | None]:
    """Krok, który już się skończył, tak jak API pokazuje go przez chwilę po końcu."""

    return {**step, "conclusion": None, "completed_at": None}


def _api(steps: list[dict[str, str | None]]) -> dict[str, object]:
    """Odpowiedź API zadań runu: to zadanie i zadanie na innym runnerze z tymi samymi krokami."""

    job = {"name": "pytest (Python 3.14, 1/2)", "runner_name": RUNNER, "started_at": "2026-10-26T02:30:51Z", "steps": steps}
    return {"total_count": 2, "jobs": [{**job, "name": "inne", "runner_name": "GitHub Actions 7", "started_at": "2026-10-26T01:00:00Z"}, job]}


PYTEST_STEPS: list[dict[str, str | None]] = [
    _step("Set up job", "success", "02:30:51", "02:30:54"),
    _step("Run the planned units", "failure", "02:31:08", "02:39:07"),
    _step("Upload E2E and timing guard evidence on failure", "success", "02:39:07", "02:39:09"),
]
# Krok zapisu sam trwa, gdy czyta API.
RECORDING = _running(_step("Record the time of each unit of work", "success", "02:39:09", "02:39:10"))
PYTEST_STEPS.append(RECORDING)
API_UNITS = [{"klucz": "krok:praca", "s": 479.0, "status": "fail"}]
JUNIT_UNITS = [
    {"klucz": "pytest:tests/test_a.py", "s": 1.5, "status": "fail"},
    {"klucz": "pytest:tests/test_b.py", "s": 0.3, "status": "ok"},
    {"klucz": "pytest:tests/test_c.py", "s": 0.254, "status": "fail"},
    {"klucz": "pytest:tests/test_d.py", "s": 2.0, "status": "ok"},
    {"klucz": "pytest:tests/test_e.py", "s": 0.0, "status": "fail"},
]
# Jednostki, które mierzy ``tools/ci/wykonaj_zadanie.py``, i plan, z którego biegły.
PLANNED = {"plan": "digest-planu", "zadanie": "windows-3.14-1"}
PLANNED_UNITS = [
    {"klucz": "krok:pytest", "s": 383.0, "status": "fail"},
    {"klucz": "krok:e2e", "s": 61.0, "status": "ok"},
    {"klucz": "krok:timing", "s": 35.0, "status": "ok"},
]
PYTEST_UNITS = [*API_UNITS, *JUNIT_UNITS, *PLANNED_UNITS]


class _Api:
    """API zadań runu: odpowiada na każde GET tym, co test ustawi, i zapamiętuje ścieżkę i nagłówek autoryzacji."""

    def __init__(self) -> None:
        self.status = 200
        self.delay_s = 0.0
        self.earlier: list[str] = []
        self.body = json.dumps(_api(PYTEST_STEPS))
        self.requests: list[tuple[str, str | None]] = []

    def steps(self, *readings: list[dict[str, str | None]]) -> None:
        """Kolejne odczyty dostają kolejne listy kroków, a ostatnia zostaje na dalsze odczyty."""

        *self.earlier, self.body = (json.dumps(_api(steps)) for steps in readings)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Api]:
    state = _Api()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.requests.append((self.path, self.headers.get("Authorization")))
            threading.Event().wait(state.delay_s)
            body = (state.earlier.pop(0) if state.earlier else state.body).encode("utf-8")
            self.send_response(state.status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    for name, value in {**ENV, "GITHUB_API_URL": f"http://127.0.0.1:{server.server_port}", "NO_PROXY": "127.0.0.1"}.items():
        monkeypatch.setenv(name, value)
    yield state
    server.shutdown()
    server.server_close()
    thread.join()


def _inputs(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = {"junit": folder / "junit.xml", "wykonanie": folder / "wykonanie.json"}
    paths["junit"].write_text(JUNIT, encoding="utf-8")
    paths["wykonanie"].write_text(json.dumps({**PLANNED, "jednostki": PLANNED_UNITS}), encoding="utf-8")
    return paths


def _record(tmp_path: Path, paths: dict[str, Path], *sources: str, tor: str = "Windows-3.14.0") -> tuple[int, dict[str, object]]:
    record = tmp_path / "czasy" / "zapis" / "pytest-0-2.json"
    arguments = [part for source in sources for part in (f"--{source}", str(paths[source]))]
    code = main(["zadanie", "--tor", tor, *arguments, "--wyjscie", str(record)])
    return code, json.loads(record.read_text(encoding="utf-8"))


def test_zadanie_pytest_zapisuje_czas_kazdego_pliku_testow_i_kazdej_jednostki_planu_z_narzutem_i_planem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], api: _Api
) -> None:
    code, record = _record(tmp_path, _inputs(tmp_path / "wejscie"), "junit", "wykonanie")

    assert code == 0
    assert api.requests == [("/repos/MAXIMISEART-AI/MAXIMISEART-Dad/actions/runs/40259456807/attempts/2/jobs?per_page=100", "Bearer token-testu")]
    assert record == {
        "wersja": 1,
        "run": 40259456807,
        "proba": 2,
        "szablon": "pytest",
        "zadanie": "pytest (Python 3.14, 1/2)",
        "tor": "windows-3.14",
        "zdarzenie": "push",
        "sha": ENV["GITHUB_SHA"],
        "narzut_s": 17.0,
        "jednostki": PYTEST_UNITS,
        "bledy": [],
        "plan": "digest-planu",
        "zadanie_planu": "windows-3.14-1",
    }
    assert capsys.readouterr().out.splitlines() == ["CZASY CI | pytest (Python 3.14, 1/2) | windows-3.14 | 9 jednostek | narzut 17 s | pytest-0-2.json"]


def test_zadanie_bez_kroku_jednostki_skonczonego_sukcesem_albo_porazka_nie_ma_narzutu(tmp_path: Path, capsys: pytest.CaptureFixture[str], api: _Api) -> None:
    api.steps(
        [
            _step("Set up job", "success", "02:30:51", "02:30:54"),
            _step("Run the planned units", "cancelled", "02:31:00", "02:31:30"),
        ]
    )
    code, record = _record(tmp_path, {}, tor="Linux-3.14.0")

    assert code == 0
    assert (record["tor"], record["narzut_s"], record["jednostki"]) == ("linux-3.14", None, [])
    assert "| 0 jednostek | narzut ? s |" in capsys.readouterr().out


def test_krok_bez_wyniku_w_api_zadanie_czyta_ponownie_az_api_pokaze_wynik(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: _Api
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    lagging = [PYTEST_STEPS[0], _running(PYTEST_STEPS[1]), *PYTEST_STEPS[2:]]
    api.steps(lagging, lagging, PYTEST_STEPS)

    code, record = _record(tmp_path, {}, tor="Linux-3.14.0")

    assert (code, record["bledy"], record["jednostki"], record["narzut_s"]) == (0, [], API_UNITS, 17.0)
    assert (waits, len(api.requests)) == ([1.0, 1.0], 3)


def test_krok_bez_wyniku_po_piatym_odczycie_jest_zgloszony(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], api: _Api
) -> None:
    waits: list[float] = []
    monkeypatch.setattr(time, "sleep", waits.append)
    api.steps([PYTEST_STEPS[0], _running(PYTEST_STEPS[1])])

    code, record = _record(tmp_path, {})

    assert (code, record["jednostki"], waits, len(api.requests)) == (1, [], [1.0] * 4, 5)
    assert record["bledy"] == ["API zadań runu: ValueError(\"kroki ['Run the planned units'] bez wyniku w API po 5 odczytach\")"]
    assert capsys.readouterr().out.startswith(f"CZASY CI FAIL | {record['bledy'][0]}\n")


def test_api_ktore_nie_odpowiada_w_limicie_czasu_jest_zgloszone_zamiast_zatrzymac_zadanie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api: _Api
) -> None:
    monkeypatch.setattr(zapis_czasow, "LIMIT_API_S", 0.1)
    api.delay_s = 1.0

    code, record = _record(tmp_path, {})

    assert (code, record["jednostki"]) == (1, [])
    assert record["bledy"] == ["API zadań runu: TimeoutError('timed out')"]


def _replace(path: Path, content: str | None) -> None:
    if content is None:
        path.unlink()
    else:
        path.write_text(content, encoding="utf-8")


@pytest.mark.parametrize(
    ("source", "content", "error"),
    [
        ("junit", None, "junit.xml: FileNotFoundError("),
        ("junit", "<testsuites><testsuite>", "junit.xml: ValueError('to nie jest XML ("),
        ("junit", '<testsuite><testcase name="test_x" time="1.0" /></testsuite>', "junit.xml: ValueError('test test_x bez atrybutu file"),
        ("junit", '<testsuite><testcase name="test_x" file="tests/test_x.py" /></testsuite>', "junit.xml: ValueError('test test_x bez atrybutu file albo time"),
        ("junit", '<testsuite name="pytest" tests="0"></testsuite>', "junit.xml: ValueError('brak testów')"),
        ("wykonanie", None, "wykonanie.json: FileNotFoundError("),
        ("wykonanie", "{", "wykonanie.json: JSONDecodeError("),
        ("wykonanie", '{"plan": "digest-planu", "jednostki": []}', "wykonanie.json: KeyError('zadanie')"),
        ("wykonanie", '{"plan": "p", "zadanie": "z", "jednostki": [{"klucz": "krok:e2e"}]}', "wykonanie.json: TypeError("),
        ("api", None, "API zadań runu: URLError(ConnectionRefusedError("),
        ("api", (401, '{"message": "Bad credentials"}'), "API zadań runu: <HTTPError 401: "),
        ("api", (200, ""), "API zadań runu: JSONDecodeError("),
        ("api", (200, '{"message": "Bad credentials"}'), "API zadań runu: KeyError('jobs')"),
        ("api", (200, '{"jobs": null}'), "API zadań runu: TypeError("),
        ("api", (200, json.dumps({"jobs": []})), "API zadań runu: ValueError(\"0 zadań na runnerze 'GitHub Actions 1000012606' zamiast jednego\")"),
        (
            "api",
            (200, json.dumps({"jobs": [{"name": "pytest", "runner_name": RUNNER, "steps": []}] * 2})),
            "API zadań runu: ValueError(\"2 zadań na runnerze 'GitHub Actions 1000012606' zamiast jednego\")",
        ),
    ],
)
def test_brakujace_albo_zepsute_wejscie_jest_zgloszone_a_reszta_pomiaru_zostaje(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    api: _Api,
    source: str,
    content: str | tuple[int, str] | None,
    error: str,
) -> None:
    paths = _inputs(tmp_path / "wejscie")
    if source != "api":
        _replace(paths[source], content if isinstance(content, str) else None)
    elif isinstance(content, tuple):
        api.status, api.body = content
    else:
        monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:1")

    code, record = _record(tmp_path, paths, "junit", "wykonanie")
    errors = record["bledy"]
    out = capsys.readouterr().out.splitlines()

    assert code == 1
    assert isinstance(errors, list) and len(errors) == 1 and errors[0].startswith(error), errors
    assert out[0] == f"CZASY CI FAIL | {errors[0]}"
    kept = {"api": API_UNITS, "junit": JUNIT_UNITS, "wykonanie": PLANNED_UNITS}
    assert record["jednostki"] == [unit for other in ("api", "junit", "wykonanie") if other != source for unit in kept[other]]
    assert record["zadanie"] == ("pytest" if source == "api" else "pytest (Python 3.14, 1/2)")
    assert (record["plan"], record["zadanie_planu"]) == ((None, None) if source == "wykonanie" else ("digest-planu", "windows-3.14-1"))


def _merge(folder: Path, output: Path) -> int:
    return main(["scal", "--katalog", str(folder), "--wyjscie", str(output)])


def _saved(folder: Path, name: str, *, run: int, attempt: int, job: str, tor: str = "windows-3.14", seconds: float = 1.0) -> None:
    record = {
        "wersja": 1,
        "run": run,
        "proba": attempt,
        "szablon": "pytest",
        "zadanie": job,
        "tor": tor,
        "zdarzenie": "push",
        "sha": f"sha{run}",
        "narzut_s": None,
        "jednostki": [{"klucz": "krok:pytest", "s": seconds, "status": "ok"}],
        "bledy": [],
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(record), encoding="utf-8")


def test_scalenie_zapisow_runu_daje_obserwacje_kazdego_klucza_na_torze(tmp_path: Path, capsys: pytest.CaptureFixture[str], api: _Api) -> None:
    for lane, (python, planned) in {"windows": ("Windows-3.14.0", "wykonanie"), "linux": ("Linux-3.14.0", None)}.items():
        paths = _inputs(tmp_path / lane)
        sources = ["--junit", str(paths["junit"]), *(["--wykonanie", str(paths["wykonanie"])] if planned else [])]
        main(["zadanie", "--tor", python, *sources, "--wyjscie", str(tmp_path / "zapisy" / f"{lane}.json")])
    capsys.readouterr()

    code = _merge(tmp_path / "zapisy", tmp_path / "czasy-ci.json")
    merged = json.loads((tmp_path / "czasy-ci.json").read_text(encoding="utf-8"))

    def observed(unit: dict[str, object]) -> list[dict[str, object]]:
        return [{"run": 40259456807, "proba": 2, "zadanie": "pytest (Python 3.14, 1/2)", "s": unit["s"], "status": unit["status"]}]

    assert code == 0
    assert merged["wersja"] == 1
    assert merged["runy"] == [{"run": 40259456807, "proba": 2, "sha": ENV["GITHUB_SHA"], "zdarzenie": "push"}]
    assert merged["tory"] == {
        "linux-3.14": {
            **{str(unit["klucz"]): observed(unit) for unit in [*API_UNITS, *JUNIT_UNITS]},
            "narzut:pytest": observed({"s": 17.0, "status": "ok"}),
        },
        "windows-3.14": {
            **{str(unit["klucz"]): observed(unit) for unit in PYTEST_UNITS},
            "narzut:pytest": observed({"s": 17.0, "status": "ok"}),
        },
    }
    assert list(merged["tory"]["windows-3.14"]) == sorted(merged["tory"]["windows-3.14"])
    assert capsys.readouterr().out.splitlines() == [
        "CZASY CI | linux-3.14 | 7 kluczy, w tym 5 plików testów",
        "CZASY CI | windows-3.14 | 10 kluczy, w tym 5 plików testów",
        "CZASY CI SCALONE | 2 zapisów zadań | czasy-ci.json",
    ]


def test_scalenie_tych_samych_zapisow_daje_ten_sam_plik_niezaleznie_od_nazw_plikow_i_katalogow(tmp_path: Path) -> None:
    records = [(2, 1, "A"), (1, 2, "A"), (1, 1, "B"), (1, 1, "A")]
    for index, (run, attempt, job) in enumerate(records):
        _saved(tmp_path / "po-kolei", f"{index}.json", run=run, attempt=attempt, job=job, seconds=index)
        _saved(tmp_path / "odwrotnie" / f"czasy-zadanie-{index}", f"{len(records) - index}.json", run=run, attempt=attempt, job=job, seconds=index)

    assert _merge(tmp_path / "po-kolei", tmp_path / "1.json") == 0
    assert _merge(tmp_path / "odwrotnie", tmp_path / "2.json") == 0
    merged = (tmp_path / "1.json").read_bytes()

    assert merged == (tmp_path / "2.json").read_bytes()
    observations = json.loads(merged)["tory"]["windows-3.14"]["krok:pytest"]
    assert [(o["run"], o["proba"], o["zadanie"], o["s"]) for o in observations] == [(1, 1, "A", 3), (1, 1, "B", 2), (1, 2, "A", 1), (2, 1, "A", 0)]
    assert [(run["run"], run["proba"]) for run in json.loads(merged)["runy"]] == [(1, 1), (1, 2), (2, 1)]


@pytest.mark.parametrize(
    ("broken", "error"),
    [
        ("katalog", "0-zly.json: IsADirectoryError(" if sys.platform != "win32" else "0-zly.json: PermissionError("),
        ("{", "0-zly.json: JSONDecodeError("),
        ('{"wersja": 2}', "0-zly.json: ValueError('wersja zapisu inna niż 1')"),
        ("{}", "0-zly.json: KeyError('wersja')"),
        ('{"wersja": 1, "jednostki": [], "nieznane": 1}', "0-zly.json: TypeError("),
    ],
)
def test_zepsuty_zapis_zadania_jest_zgloszony_a_scalenie_bierze_pozostale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], broken: str, error: str
) -> None:
    _saved(tmp_path / "zapisy", "1-dobry.json", run=1, attempt=1, job="A")
    if broken == "katalog":
        (tmp_path / "zapisy" / "0-zly.json").mkdir()
    else:
        (tmp_path / "zapisy" / "0-zly.json").write_text(broken, encoding="utf-8")

    code = _merge(tmp_path / "zapisy", tmp_path / "czasy-ci.json")
    out = capsys.readouterr().out.splitlines()

    assert code == 1
    assert out[0].startswith(f"CZASY CI FAIL | {error}"), out
    assert out[-1] == "CZASY CI SCALONE | 1 zapisów zadań | czasy-ci.json"
    assert list(json.loads((tmp_path / "czasy-ci.json").read_text(encoding="utf-8"))["tory"]["windows-3.14"]) == ["krok:pytest"]


@pytest.mark.parametrize("records", [(), ("{",)])
def test_bez_zadnego_dobrego_zapisu_scalenie_nie_tworzy_czasow_ci(tmp_path: Path, capsys: pytest.CaptureFixture[str], records: tuple[str, ...]) -> None:
    (tmp_path / "zapisy").mkdir()
    for index, content in enumerate(records):
        (tmp_path / "zapisy" / f"{index}.json").write_text(content, encoding="utf-8")

    code = _merge(tmp_path / "zapisy", tmp_path / "czasy-ci.json")
    out = capsys.readouterr().out.splitlines()

    assert code == 1
    assert not (tmp_path / "czasy-ci.json").exists()
    assert len(out) == 1 and out[0].startswith("CZASY CI FAIL | "), out
    assert (f"brak zapisów zadań w {tmp_path / 'zapisy'}" in out[0]) == (not records)


def _artifact(run: int, **jobs: dict[str, float]) -> dict[str, object]:
    """Artefakt ``czasy-ci`` runu main: zadanie (``nazwa`` albo ``nazwa@próba``) -> klucz -> sekundy na windows-3.14."""

    keys: dict[str, list[dict[str, object]]] = {}
    for job, units in jobs.items():
        name, _, attempt = job.partition("@")
        for key, seconds in units.items():
            keys.setdefault(key, []).append({"run": run, "proba": int(attempt or 1), "zadanie": name, "s": seconds, "status": "ok"})
    return {"wersja": 1, "runy": [{"run": run, "proba": 1, "sha": f"sha{run}", "zdarzenie": "push"}], "tory": {"windows-3.14": keys}}


class _GitHub:
    """GitHub z zielonymi runami main i ich artefaktami ``czasy-ci`` (id artefaktu to numer runu + 1000), z których
    ``expired`` wygasły; zapamiętuje listy, o które pytano, i runy, których artefakt pobrano."""

    def __init__(self, green: list[int], artifacts: dict[int, dict[str, object]], expired: frozenset[int] = frozenset()) -> None:
        self.green, self.artifacts, self.expired = green, artifacts, expired
        self.listed: list[str] = []
        self.downloaded: list[int] = []

    def json(self, sciezka: str) -> dict[str, object]:
        self.listed.append(sciezka)
        if sciezka.startswith("repos/{owner}/{repo}/actions/workflows/ci.yml/runs?"):
            return {"workflow_runs": [{"id": run} for run in self.green]}
        assert sciezka.startswith("repos/{owner}/{repo}/actions/artifacts?name=czasy-ci&"), sciezka
        return {"artifacts": [{"id": run + 1000, "expired": run in self.expired, "workflow_run": {"id": run}} for run in self.artifacts]}

    def bajty(self, sciezka: str) -> bytes:
        artifact = sciezka.removeprefix("repos/{owner}/{repo}/actions/artifacts/").removesuffix("/zip")
        run = int(artifact) - 1000
        self.downloaded.append(run)
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w") as archive:
            if self.artifacts[run]:
                archive.writestr("czasy-ci.json", json.dumps(self.artifacts[run]))
        return packed.getvalue()

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> NoReturn:
        raise AssertionError(f"odczyt czasów nie pisze do GitHuba: {metoda} {sciezka}")


class _Offline:
    """GitHub bez sieci: każde zapytanie pada tak, jak ``GhApi``, gdy ``gh`` nie łączy się z API."""

    def json(self, sciezka: str) -> NoReturn:
        raise RuntimeError("error connecting to api.github.com")

    def bajty(self, sciezka: str) -> NoReturn:
        raise RuntimeError("error connecting to api.github.com")

    def wyslij(self, metoda: str, sciezka: str, tresc: Mapping[str, object]) -> NoReturn:
        raise RuntimeError("error connecting to api.github.com")


def _seconds(run: int) -> dict[str, dict[str, float]]:
    """Plik testów podzielony między dwa zadania i narzut każdego zadania; zadanie B powtórzone, liczy się próba 2."""

    return {
        "A": {"pytest:tests/test_x.py": run, "narzut:pytest": 10},
        "B": {"pytest:tests/test_x.py": 1000, "narzut:pytest": 1000},
        "B@2": {"pytest:tests/test_x.py": 2 * run, "narzut:pytest": 20},
    }


def test_czasy_z_main_to_mediana_trzech_najnowszych_zielonych_runow_z_artefaktem_i_ostatniej_proby_zadania(tmp_path: Path) -> None:
    # Runy 11 i 6 anulowano: Required wysłał częściowy artefakt, ale lista zielonych runów main ich nie ma.
    github = _GitHub([10, 9, 8, 7, 5], {run: _artifact(run, **_seconds(run)) for run in (11, 10, 9, 8, 7, 6)})
    (tmp_path / "5.json").write_text(json.dumps(_artifact(5, A={"pytest:tests/test_x.py": 9000})), encoding="utf-8")

    czasy = czasy_ci.z_mainu(tmp_path, github=github)

    assert (czasy.runy, czasy.blad) == ((8, 9, 10), None)
    assert sorted(github.downloaded) == [8, 9, 10]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["10.json", "8.json", "9.json", "pobrane"]
    assert czasy.praca("windows-3.14", "pytest:tests/test_x.py") == 27
    assert czasy.pliki("windows-3.14") == {"tests/test_x.py": 27}
    assert (czasy.praca("linux-3.14", "pytest:tests/test_x.py"), czasy.pliki("linux-3.14")) == (None, {})
    assert czasy.zadania("windows-3.14")[:2] == [{"pytest:tests/test_x.py": 8, "narzut:pytest": 10}, {"pytest:tests/test_x.py": 16, "narzut:pytest": 20}]


def test_wygasly_artefakt_zielonego_runu_nie_liczy_sie_do_trzech_najnowszych(tmp_path: Path) -> None:
    github = _GitHub([10, 9, 8, 7], {run: _artifact(run, A={"pytest:tests/test_x.py": run}) for run in (10, 9, 8, 7)}, expired=frozenset({9}))

    czasy = czasy_ci.z_mainu(tmp_path, github=github)

    assert (czasy.runy, sorted(github.downloaded)) == ((7, 8, 10), [7, 8, 10])


def test_artefakt_bez_pliku_czasow_to_przyczyna_a_czasy_biora_kopie(tmp_path: Path) -> None:
    (tmp_path / "2.json").write_text(json.dumps(_artifact(2, A={"pytest:tests/test_x.py": 2})), encoding="utf-8")

    czasy = czasy_ci.z_mainu(tmp_path, github=_GitHub([3, 2], {3: {}, 2: _artifact(2)}))

    assert (czasy.runy, czasy.pliki("windows-3.14")) == ((2,), {"tests/test_x.py": 2})
    assert czasy.blad == "pobranie czasy-ci z GitHuba: \"There is no item named 'czasy-ci.json' in the archive\""


def test_swieze_czasy_nie_pytaja_githuba_a_starsze_niz_doba_odswiezaja(tmp_path: Path) -> None:
    github = _GitHub([3], {3: _artifact(3, A={"pytest:tests/test_x.py": 4})})
    (tmp_path / "2.json").write_text(json.dumps(_artifact(2, A={"pytest:tests/test_x.py": 2})), encoding="utf-8")
    (tmp_path / "pobrane").touch()

    fresh = czasy_ci.z_mainu(tmp_path, odswiez_po_s=czasy_ci.ODSWIEZ_S, github=github)
    os.utime(tmp_path / "pobrane", (time.time() - czasy_ci.ODSWIEZ_S - 1,) * 2)
    refreshed = czasy_ci.z_mainu(tmp_path, odswiez_po_s=czasy_ci.ODSWIEZ_S, github=github)

    assert (fresh.runy, refreshed.runy) == ((2,), (3,))
    assert len(github.listed) == 2


def test_bez_githuba_czasy_biora_kopie_a_bez_kopii_sa_puste_i_mowia_dlaczego(tmp_path: Path) -> None:
    empty = czasy_ci.z_mainu(tmp_path / "pusty", github=_Offline())
    (tmp_path / "kopia").mkdir()
    (tmp_path / "kopia" / "2.json").write_text(json.dumps(_artifact(2, A={"pytest:tests/test_x.py": 2})), encoding="utf-8")
    cached = czasy_ci.z_mainu(tmp_path / "kopia", github=_Offline())

    assert (empty.runy, empty.tory, empty.blad) == ((), {}, "pobranie czasy-ci z GitHuba: error connecting to api.github.com")
    assert (cached.runy, cached.pliki("windows-3.14"), cached.blad) == ((2,), {"tests/test_x.py": 2}, empty.blad)


@ONLY_FOUND_BY_NAME_ON_POSIX
@pytest.mark.parametrize(
    ("gh", "reason"),
    [
        ("import sys\nsys.exit('HTTP 404: Not Found')\n", "pobranie czasy-ci z GitHuba: HTTP 404: Not Found"),
        ("import time\ntime.sleep(60)\n", "timed out after 0.5 seconds"),
    ],
    ids=["gh pada", "gh nie odpowiada"],
)
def test_gh_ktory_pada_albo_nie_odpowiada_w_limicie_daje_przyczyne_z_jego_bledu_a_czasy_biora_kopie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gh: str, reason: str
) -> None:
    """Prawdziwy ``GhApi`` na atrapie ``gh``: przyczyna to sam błąd ``gh`` bez polecenia (linie ``CZASY CI |`` i ``SZYBKO |
    bez czasów CI``), a ``gh``, który wisi, przerywa limit jednego zapytania, więc plan nie czeka na sieć."""

    fake_cli(tmp_path / "bin", "gh", gh)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    (tmp_path / "kopia").mkdir()
    (tmp_path / "kopia" / "2.json").write_text(json.dumps(_artifact(2, A={"pytest:tests/test_x.py": 2})), encoding="utf-8")

    czasy = czasy_ci.z_mainu(tmp_path / "kopia", github=GhApi(limit_s=0.5))

    assert (czasy.runy, czasy.pliki("windows-3.14")) == ((2,), {"tests/test_x.py": 2})
    assert czasy.blad is not None and czasy.blad.startswith("pobranie czasy-ci z GitHuba: ") and czasy.blad.endswith(reason), czasy.blad


def test_po_nieudanym_pobraniu_nastepny_odczyt_pobiera_znowu_a_po_udanym_czeka_dobe(tmp_path: Path) -> None:
    failed = czasy_ci.z_mainu(tmp_path, odswiez_po_s=czasy_ci.ODSWIEZ_S, github=_Offline())
    retried = czasy_ci.z_mainu(tmp_path, odswiez_po_s=czasy_ci.ODSWIEZ_S, github=_GitHub([3], {3: _artifact(3, A={"pytest:tests/test_x.py": 4})}))
    cached = czasy_ci.z_mainu(tmp_path, odswiez_po_s=czasy_ci.ODSWIEZ_S, github=_Offline())

    assert (failed.runy, failed.blad) == ((), "pobranie czasy-ci z GitHuba: error connecting to api.github.com")
    assert (retried.runy, retried.blad) == ((3,), None)
    assert (cached.runy, cached.blad) == ((3,), None)


@pytest.mark.parametrize(
    ("content", "error"),
    [
        (None, "brak artefaktu czasy-ci z zielonego runu main"),
        ("{", "2.json: Expecting property name"),
        ('{"wersja": 1, "runy": [], "tory": {"windows-3.14": {"k": [{"run": 2}]}}}', "czasy-ci w innym kształcie: KeyError('zadanie')"),
    ],
)
def test_brak_albo_zepsuty_artefakt_daje_puste_czasy_z_przyczyna(tmp_path: Path, content: str | None, error: str) -> None:
    if content is not None:
        (tmp_path / "2.json").write_text(content, encoding="utf-8")
    (tmp_path / "pobrane").touch()

    czasy = czasy_ci.z_mainu(tmp_path, odswiez_po_s=czasy_ci.ODSWIEZ_S, github=_GitHub([], {}))

    assert (czasy.runy, czasy.tory) == ((), {})
    assert czasy.blad is not None and czasy.blad.startswith(error), czasy.blad


def _recorded(job: str, option: str) -> str:
    recorded = [step["run"] for step in jobs()[job]["steps"] if "tools/ci/zapis_czasow.py zadanie" in step.get("run", "")]
    assert len(recorded) == 1, job
    arguments = shlex.split(recorded[0])
    return arguments[arguments.index(option) + 1]


def test_kazdy_krok_jednostki_jest_krokiem_ci_a_zapis_czyta_junit_i_wynik_tam_gdzie_pisze_je_wykonanie_zadania() -> None:
    workflow = jobs()
    names = {step.get("name") for job in ("pytest", "mutations") for step in workflow[job]["steps"]}

    assert set(KROKI) - names == set()
    assert tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]["junit_family"] == "xunit1"
    assert Path(_recorded("pytest", "--junit")) == wykonaj_zadanie.JUNIT
    assert Path(_recorded("pytest", "--wykonanie")) == Path(_recorded("mutations", "--wykonanie")) == plan_runu.WYKONANIE


def test_pomiar_czasow_nie_zmienia_werdyktu_ci_i_biegnie_takze_po_porazce_z_dostepem_do_api_zadan() -> None:
    workflow = jobs()
    measuring = {
        name: [step for step in job["steps"] if "tools/ci/zapis_czasow.py" in step.get("run", "") or "czasy" in json.dumps(step.get("with", {}))]
        for name, job in workflow.items()
    }
    required = workflow["required"]["steps"]
    verdict = next(index for index, step in enumerate(required) if "tools/ci/werdykt_required.py" in step.get("run", ""))
    # Zapisy zadań Required pobiera przed werdyktem, bo z nich sprawdza, że każda jednostka planu biegła.
    records, *merging = measuring["required"]

    assert {name: len(steps) for name, steps in measuring.items() if steps} == {"pytest": 2, "mutations": 2, "required": 3}
    assert [
        step.get("name", step.get("uses"))
        for steps in (measuring["pytest"], measuring["mutations"], merging)
        for step in steps
        if step.get("continue-on-error") is not True or not step.get("if", "").startswith("${{ !cancelled()")
    ] == []
    assert (required.index(records) < verdict, records.get("continue-on-error")) == (True, True)
    assert all(required.index(step) > verdict for step in merging)
    for job in ("pytest", "mutations"):
        assert workflow[job]["permissions"]["actions"] == "read", job
        assert [step["env"]["GH_TOKEN"] for step in measuring[job] if "run" in step] == ["${{ github.token }}"], job



def test_pomoc_pokazuje_polecenia_z_docstringu_z_ich_wcieciami(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])

    assert stopped.value.code == 0
    assert "\n    python3 tools/ci/zapis_czasow.py scal --katalog zapisy --wyjscie czasy-ci.json\n" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("arguments", "missing"),
    [
        ([], "polecenie"),
        (["zadanie", "--wyjscie", "z.json"], "--tor"),
        (["zadanie", "--tor", "Linux-3.14"], "--wyjscie"),
        (["scal", "--wyjscie", "c.json"], "--katalog"),
        (["scal", "--katalog", "zapisy"], "--wyjscie"),
    ],
)
def test_wywolanie_bez_wymaganego_argumentu_konczy_sie_kodem_2_z_jego_nazwa(
    capsys: pytest.CaptureFixture[str], arguments: list[str], missing: str
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(arguments)

    assert stopped.value.code == 2
    assert capsys.readouterr().err.splitlines()[-1].endswith(f"the following arguments are required: {missing}")


def test_zapis_ci_podaje_czasy_pod_torem_pomiarow_planu_a_tor_lokalny_jest_torem_pytest() -> None:
    """``ci.yml`` podaje zapisowi tor runnera (``Windows-3.14.0``), a zapis skraca go do toru czasów; plan czyta czasy pod
    ``Tor.pomiary``, a ``tools/szybko.py`` i ``tools/scal_pr.py`` pod ``TOR_LOKALNY``. Tor, którego zapis nie trafia pod
    ich nazwę, po cichu waży każdą jednostkę zerem."""

    runner = {"windows-latest": "Windows", "ubuntu-latest": "Linux"}
    tory = (*TORY, MUTACJE)

    assert {_recorded(job, "--tor") for job in ("pytest", "mutations")} == {"${{ runner.os }}-${{ steps.python.outputs.python-version }}"}
    assert [zapis_czasow._tor(f"{runner[tor.os]}-{tor.python}.0") for tor in tory] == [tor.pomiary for tor in tory]
    assert czasy_ci.TOR_LOKALNY in {tor.pomiary for tor in TORY}


# Każdy kształt wyniku pytest, który junit niesie inaczej: test w klasie, parametr ze spacją i ``::``, porażka, błąd
# fixture, pominięcie, xfail, xpass, własność junit i plik, którego nie da się zaimportować (błąd kolekcji).
WSZYSTKIE_WYNIKI = """import pytest


def test_ok() -> None:
    pass


def test_zly() -> None:
    assert False


@pytest.fixture
def zepsuta() -> None:
    raise RuntimeError("fixture")


def test_fixture(zepsuta: None) -> None:
    pass


@pytest.mark.skip
def test_pominiety() -> None:
    pass


@pytest.mark.xfail
def test_xfail() -> None:
    assert False


@pytest.mark.xfail
def test_xpass() -> None:
    pass


@pytest.mark.parametrize("opis", ["dwa i dwa", "a::b"])
def test_opis(opis: str) -> None:
    assert opis != "dwa i dwa"


def test_z_wlasnoscia(record_property):
    record_property("kwarantanna", "powód")


class TestKlasa:
    def test_metoda(self) -> None:
        pass
"""


def test_junit_daje_id_pytest_wynik_i_wlasnosci_kazdego_testu_takze_bez_konfiguracji_junit_projektu(tmp_path: Path) -> None:
    """Narzędzia czytają junit jednym czytnikiem (``tools/lib/wyniki_testow.py``), a narzędzie, które uruchamia pytest w
    drzewie bez ``junit_family = "xunit1"``, wymusza tę postać argumentami ``zapis``."""

    (tmp_path / "tests" / "pod").mkdir(parents=True)
    (tmp_path / "tests" / "pod" / "test_wyniki.py").write_text(WSZYSTKIE_WYNIKI, encoding="utf-8")
    (tmp_path / "tests" / "pod" / "test_nie_importuje.py").write_text("import nie_ma_takiego_modulu\n", encoding="utf-8")
    junit = tmp_path / "junit.xml"
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--continue-on-collection-errors", *wyniki_testow.zapis(junit), "tests"],
        cwd=tmp_path,
        capture_output=True,
        check=False,
    )

    plik, modul = "tests/pod/test_wyniki.py", "tests/pod/test_nie_importuje.py"
    assert sorted((test.plik, test.id, test.wynik, test.wlasnosci) for test in wyniki_testow.testy(junit)) == sorted(
        [
            (modul, None, "padł", frozenset()),
            *(
                (plik, f"{plik}::{nazwa}", wynik, wlasnosci)
                for nazwa, wynik, wlasnosci in [
                    ("test_ok", "przeszedł", frozenset()),
                    ("test_zly", "padł", frozenset()),
                    ("test_fixture", "padł", frozenset()),
                    ("test_pominiety", "pominięty", frozenset()),
                    ("test_xfail", "xfail", frozenset()),
                    ("test_xpass", "przeszedł", frozenset()),
                    ("test_opis[dwa i dwa]", "padł", frozenset()),
                    ("test_opis[a::b]", "przeszedł", frozenset()),
                    ("test_z_wlasnoscia", "przeszedł", frozenset({"kwarantanna"})),
                    ("TestKlasa::test_metoda", "przeszedł", frozenset()),
                ]
            ),
        ]
    )
    # Błąd kolekcji nie ma id testu, więc ponowienie nie ma czego ponowić; porażkę i błąd fixture zdejmuje po id.
    assert niestabilne_testy.padniete(junit) is None
    wyniki_testow.bez_porazek(junit, [f"{plik}::{nazwa}" for nazwa in ("test_zly", "test_fixture", "test_opis[dwa i dwa]")])
    assert [(test.plik, test.id) for test in wyniki_testow.testy(junit) if test.wynik == "padł"] == [(modul, None)]
