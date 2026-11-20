"""``tools/rejestr_korzeni_tydzien.py``: tygodniowy pomiar w treści issue „Rejestr korzeni” (miary ADR 0036, tydzień
i szablon treści z ADR 0031, Q19, Q23) i workflow ``rejestr-korzeni.yml``, który go uruchamia w poniedziałek o 6:00
czasu polskiego.

Wymagania bierzemy z ADR 0036 („Miara”), ADR 0046 („Pomiar bez pola ``Idiom:``”) i decyzji Maksa: odpalenie strażnika
to porażka jego kroku albo testu w runie Required CI PR-u tygodnia, poszerzenie reguły to zmiana zasięgu reguły, którą
baza merge'a już miała, czekanie liczy się od ``PASS`` na HEAD do merge'a; tydzień to poniedziałek–niedziela czasu taty
i Maksa (``Europe/Warsaw``), a issue zmienia się treścią, bez komentarzy. Testy przepływu biegną na prawdziwym Gicie z ``origin`` i atrapie ``gh``, która podaje PR-y
z zapytania rejestru z HTML treści (``bodyHTML``) złożonym z nagranego HTML renderera GitHuba
(``tests/fixtures/body_html.py``), a renderowania treści nie zna, bo przebieg ma czytać HTML z tej samej strony
GraphQL (W1 r1 #1525: limit ``GITHUB_TOKEN`` workflowu).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import subprocess
from typing import Any

import pytest
import yaml

from tests.fixtures import chwasty, korzenie_pr, opisy_pr, werdykty_szablonu
from tests.fixtures.body_html import SAMPLES, body_html
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub
from tests.fixtures.git_repo import git

import bramka_straznika
import rejestr_korzeni
from rejestr_korzeni import GuardCase, Occurrence, Reviewed
import rejestr_korzeni_tydzien as tydzien
import straznik
import szablon_werdyktu
import tydzien_polski
import werdykt_pr

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rejestr-korzeni.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEPLOYED = datetime(2026, 10, 1, tzinfo=UTC)
GUARDED = datetime(2026, 10, 15, tzinfo=UTC)
NO_ALARMS = tydzien.Alarms(0, {}, 0)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _occurrence(pull: int, code: str, when: str, major: str = "W1 r1") -> Occurrence:
    return Occurrence(code, pull, major, _at(when))


def _pull_of(
    number: int,
    occurrences: Sequence[Occurrence] = (),
    merged: str | None = None,
    passed: str | None = None,
    *,
    created: str | None = None,
    files: Sequence[str] = (),
    limited: str | None = None,
    guards: Sequence[GuardCase] = (),
    branch: str | None = None,
) -> Reviewed:
    return Reviewed(
        number,
        _at(merged) if merged else None,
        _at(passed) if passed else None,
        tuple(occurrences),
        _at(created) if created else None,
        frozenset(files),
        _at(limited) if limited else None,
        tuple(guards),
        branch,
    )


def _body(pulls: Sequence[Reviewed], week: date, alarms: tydzien.Alarms = NO_ALARMS, widened: Sequence[tydzien.Widening] = ()) -> str:
    return tydzien.body(pulls, [], week, DEPLOYED, GUARDED, alarms, [], widened)


def _rows(text: str, section: str) -> list[str]:
    """Wiersze danych tabeli sekcji ``## section`` treści issue (bez nagłówka i linii ``---``)."""

    lines = text.splitlines()
    start = lines.index(f"## {section}")
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    return [line for line in lines[start + 1 : end] if line.startswith("| ")][2:]


class _Actions:
    def __init__(self, runs: list[dict[str, object]], jobs: dict[int, list[dict[str, object]]], logs: dict[int, str]) -> None:
        self.runs, self.jobs, self.logs = runs, jobs, logs

    def json(self, path: str) -> Any:
        if path.startswith(tydzien.CI_RUNS):
            query = dict(part.split("=", 1) for part in path.split("?", 1)[1].split("&"))
            low, high = query["created"].split("..")
            return {"workflow_runs": [run for run in self.runs if low <= str(run["created_at"]) <= high]}
        return {"jobs": self.jobs[int(path.split("/")[5])]}

    def bajty(self, path: str) -> bytes:
        return self.logs[int(path.split("/")[5])].encode("utf-8")

    def wyslij(self, method: str, path: str, content: Mapping[str, object]) -> Any:
        raise AssertionError(f"odpalenia strażników tylko czytają GitHuba, a jest {method} {path}")


def _job(job: int, name: str, steps: Sequence[tuple[str, str, str]]) -> tuple[dict[str, object], str]:
    api_steps, lines = [], []
    for number, (step, conclusion, text) in enumerate(steps, start=1):
        second = f"2026-10-20T10:00:{number:02d}"
        api_steps.append({"name": step, "conclusion": conclusion, "number": number, "started_at": f"{second}Z", "completed_at": f"{second}Z"})
        lines += [f"{second}.1000000Z ##[group]Run {step}", *(f"{second}.5000000Z {line}" for line in text.splitlines())]
    failed = any(conclusion == "failure" for _, conclusion, _ in steps)
    return {"id": job, "name": name, "conclusion": "failure" if failed else "success", "steps": api_steps}, "\n".join(lines) + "\n"


def _actions(runs: Sequence[tuple[int, str, str, Sequence[tuple[dict[str, object], str]]]]) -> _Actions:
    required = {"id": 0, "name": "Required CI status", "conclusion": "failure", "steps": []}
    return _Actions(
        [{"id": run, "head_branch": branch, "created_at": created} for run, branch, created, _ in runs],
        {run: [*(job for job, _ in jobs), required] for run, _, _, jobs in runs},
        {int(str(job["id"])): log for _, _, _, jobs in runs for job, log in jobs},
    )


def _pytest_job(job: int, *failed: str) -> tuple[dict[str, object], str]:
    return _job(job, "pytest (Python 3.14, Linux, 1/12)", [("Run the planned units", "failure", "\n".join(f"FAILED {test} - AssertionError" for test in failed))])


def _ruff_mypy_job(job: int, failed: Mapping[str, str]) -> tuple[dict[str, object], str]:
    return _job(job, tydzien.RUFF_MYPY, [(step, "failure" if step in failed else "success", failed.get(step, "")) for step in tydzien.STEP_GUARDS])


def _rows_of(firings: Sequence[tydzien.Firing]) -> list[str]:
    return [firing.row() for firing in firings]


# Granice tygodnia: poniedziałek 0:00 czasu polskiego, w czasie letnim (UTC+2) do 25.10.2026 i zimowym (UTC+1) po nim.
@pytest.mark.parametrize(
    ("when", "week"),
    [
        ("2026-10-18T21:59:59+00:00", "2026-10-12"),
        ("2026-10-18T22:00:00+00:00", "2026-10-19"),
        ("2026-10-25T22:59:59+00:00", "2026-10-19"),
        ("2026-10-25T23:00:00+00:00", "2026-10-26"),
    ],
    ids=["niedziela-23-59-czasu-letniego", "poniedzialek-0-00-czasu-letniego", "niedziela-23-59-czasu-zimowego", "poniedzialek-0-00-czasu-zimowego"],
)
def test_wystapienie_nalezy_do_tygodnia_od_poniedzialku_0_00_czasu_polskiego(when: str, week: str) -> None:
    text = _body([_pull_of(1, [_occurrence(1, "R-BEZ-TESTU", when)])], date(2026, 10, 26))

    history = {row.split(" | ")[0].removeprefix("| "): row for row in _rows(text, "Historia")}
    assert [name for name, row in history.items() if row.split(" | ")[1] == "1"] == [week], text


def test_tydzien_bez_wystapien_ma_zero_a_od_wdrozenia_liczy_wczesniejsze() -> None:
    text = _body([_pull_of(1, [_occurrence(1, "R-BEZ-TESTU", "2026-10-06T10:00:00+00:00")])], date(2026, 10, 12))

    assert _rows(text, "Pomiar") == ["| Tydzień 2026-10-12 | 0 | 0 |", "| Od wdrożenia 2026-10-01 | 1 | 0 |"], text
    assert _rows(text, "Kody") == ["| R-BEZ-TESTU | 0 | 1 |"], text
    assert _rows(text, "Historia")[-1] == "| 2026-10-12 | 0 | 0 |", text


def test_poszerzenie_liczy_sie_w_tygodniu_merge_a_jego_lista_ma_tylko_tydzien() -> None:
    widened = [
        tydzien.Widening(30, _at("2026-10-06T10:00:00+00:00"), "a-regula", ("rule",)),
        tydzien.Widening(31, _at("2026-10-14T10:00:00+00:00"), "b-regula", ("files", "ignores")),
        tydzien.Widening(32, _at("2026-10-19T10:00:00+00:00"), "c-regula", ("rule",)),
    ]

    text = _body([], date(2026, 10, 12), widened=widened)

    assert _rows(text, "Pomiar") == ["| Tydzień 2026-10-12 | 0 | 1 |", "| Od wdrożenia 2026-10-01 | 0 | 2 |"], text
    assert _rows(text, "Poszerzenia reguł") == ["| #31 | b-regula | files, ignores |"], text
    assert _rows(text, "Historia")[-2:] == ["| 2026-10-05 | 0 | 1 |", "| 2026-10-12 | 0 | 1 |"], text


def test_czekanie_od_pass_na_head_do_merge_w_tygodniu_merge_a_merge_bez_pass_osobno() -> None:
    merged = "2026-10-14T12:00:00+00:00"
    pulls = [
        _pull_of(1, merged=merged, passed="2026-10-14T11:50:00+00:00"),
        _pull_of(2, merged=merged, passed="2026-10-14T11:30:00+00:00"),
        _pull_of(3, merged=merged, passed="2026-10-14T09:00:00+00:00"),
        _pull_of(4, merged=merged),
        _pull_of(5, merged="2026-10-07T12:00:00+00:00", passed="2026-10-06T12:00:00+00:00"),
        _pull_of(6, passed="2026-10-14T09:00:00+00:00"),
    ]

    text = _body(pulls, date(2026, 10, 12))

    assert _rows(text, "Czekanie") == ["| Tydzień 2026-10-12 | 4 | 1 | 30 min | 3,0 h | 1 |", "| Od wdrożenia 2026-10-01 | 5 | 1 | 1,8 h | 24,0 h | 2 |"], text


def test_odpalenia_regul_od_najczestszej_z_udzialem_pr_z_jakimkolwiek_odpaleniem() -> None:
    text = _body([], date(2026, 10, 12), tydzien.Alarms(20, {"b-regula": 1, "a-regula": 2}, 3))

    assert _rows(text, "Reguły") == ["| a-regula | 2 |", "| b-regula | 1 |", "| Każda reguła | 3 (15%) |"], text
    assert _rows(_body([], date(2026, 10, 12)), "Reguły") == ["| Każda reguła | 0 |"]


def test_po_limicie_rund_pokazuje_pr_tygodnia_na_plikach_pr_zamknietego_po_limicie_zalozony_po_jego_ostatnim_fail() -> None:
    """Limit kończy PR po szóstej rundzie z FAIL i zostawia nowy PR od main, którego nic nie blokuje (L2 #2100), więc
    raport pokazuje każdy taki PR z liczbą wspólnych plików; PR równoległy, założony przed ostatnim FAIL, nim nie jest."""

    closed = _pull_of(20, created="2026-10-05T10:00:00+00:00", files=["a.py", "b.py", "c.py"], limited="2026-10-13T10:00:00+00:00")
    pulls = [
        closed,
        _pull_of(21, created="2026-10-12T10:00:00+00:00", files=["a.py"]),
        _pull_of(22, created="2026-10-14T10:00:00+00:00", files=["b.py", "c.py", "d.py"]),
        _pull_of(23, created="2026-10-14T11:00:00+00:00", files=["d.py"]),
        _pull_of(24, created="2026-10-20T10:00:00+00:00", files=["a.py"]),
        _pull_of(25, created="2026-10-14T12:00:00+00:00", files=["a.py"], merged="2026-10-15T10:00:00+00:00"),
    ]

    text = _body(pulls, date(2026, 10, 12))

    assert _rows(text, "Po limicie rund") == ["| #22 | #20 | 2 |", "| #25 | #20 | 1 |"], text


def _guard(pull: int, merged: str, text: str | None, major: str = "W1 r1") -> GuardCase:
    """Ważne PR ``pull`` scalonego w chwili ``merged`` z linią ``Strażnik: text`` (``None``: bez linii), czytaną jak
    w bramce strażnika."""

    return GuardCase(pull, major, _at(merged), straznik.parse(text) if text is not None else None)


# Każdy selektor z listy ADR 0042 i Ważne bez strażnika, z różną liczbą Ważnych, żeby kolumna nie mogła wziąć liczby
# innej; wyjątki to postacie „brak - …”.
SELECTORS = [
    ("mypy", 3),
    ("ruff", 1),
    ("ast-grep zakazane-wywolanie", 1),
    ("pytest tests/test_x.py::test_y", 2),
    ("brak - proza", 1),
    ("brak - napęd", 1),
    ("brak - usunięte", 2),
    ("brak - test", 1),
    (None, 1),
]


def test_strazniki_licza_wazne_scalone_z_kazdym_selektorem_a_wyjatki_i_brak_straznika_trafiaja_na_liste_tygodnia() -> None:
    """Ważne liczy się w tygodniu merge'a PR; udział wyjątków to Ważne z „brak - …” przez wszystkie Ważne, a lista
    tygodnia pokazuje każde Ważne z wyjątkiem albo bez strażnika, bez tych z dowodem narzędzia."""

    week = [_guard(2000 + index * 10 + copy, "2026-10-20T10:00:00+00:00", text) for index, (text, count) in enumerate(SELECTORS) for copy in range(count)]
    before = _guard(1990, "2026-10-16T10:00:00+00:00", "mypy")
    text = _body([_pull_of(case.pull, merged=case.when.isoformat(), guards=[case]) for case in [before, *week]], date(2026, 10, 19))

    lines = text.splitlines()
    header = lines[lines.index("## Strażniki") + 2].strip("| ").split(" | ")
    rows = [dict(zip(header, row.strip("| ").split(" | "), strict=True)) for row in _rows(text, "Strażniki")]
    weekly = {"Okres": "Tydzień 2026-10-19", "Ważne": "13", "mypy": "3", "ruff": "1", "ast-grep": "1", "pytest": "2", "brak - proza": "1", "brak - napęd": "1"}
    weekly |= {"brak - usunięte": "2", "brak - test": "1", "Bez strażnika": "1", "Udział wyjątków": "38%"}
    assert rows == [weekly, weekly | {"Okres": "Od wdrożenia 2026-10-15", "Ważne": "14", "mypy": "4", "Udział wyjątków": "36%"}], text
    assert _rows(text, "Wyjątki strażnika") == [
        "| #2040 W1 r1 | brak - proza |",
        "| #2050 W1 r1 | brak - napęd |",
        "| #2060 W1 r1 | brak - usunięte |",
        "| #2061 W1 r1 | brak - usunięte |",
        "| #2070 W1 r1 | brak - test |",
        "| #2080 W1 r1 | - |",
    ], text


def test_historia_ma_najwyzej_26_ostatnich_tygodni_od_tygodnia_wdrozenia() -> None:
    text = _body([], date(2027, 6, 7))

    weeks = [row.split(" | ")[0].removeprefix("| ") for row in _rows(text, "Historia")]
    assert (len(weeks), weeks[0], weeks[-1]) == (26, "2026-12-14", "2027-06-07"), weeks
    assert [row.split(" | ")[0].removeprefix("| ") for row in _rows(_body([], date(2026, 10, 5)), "Historia")] == ["2026-09-28", "2026-10-05"]


WEEK_START, WEEK_END = tydzien_polski.midnight(date(2026, 10, 19)), tydzien_polski.midnight(date(2026, 10, 26))
WEED_STEP = "ast-grep rules on the added lines of the repository"
FIRING_PULLS = [
    _pull_of(30, merged="2026-10-16T10:00:00+00:00", guards=[_guard(30, "2026-10-16T10:00:00+00:00", "pytest tests/test_x.py::test_y")]),
    _pull_of(31, merged="2026-10-16T10:00:00+00:00", guards=[_guard(31, "2026-10-16T10:00:00+00:00", "ast-grep zakazane-wywolanie")]),
    _pull_of(32, merged="2026-10-22T12:00:00+00:00", guards=[_guard(32, "2026-10-22T12:00:00+00:00", "pytest tests/test_z.py::test_z")]),
    _pull_of(33, merged="2026-10-16T10:00:00+00:00", guards=[_guard(33, "2026-10-16T10:00:00+00:00", "ruff")]),
    _pull_of(39, created="2026-10-05T10:00:00+00:00", branch="a"),
    _pull_of(40, created="2026-10-19T10:00:00+00:00", branch="a"),
    _pull_of(41, created="2026-10-19T10:00:00+00:00", branch="b"),
    _pull_of(42, created="2026-10-19T10:00:00+00:00", branch="c"),
]


@pytest.mark.parametrize(
    ("runs", "expected"),
    [
        pytest.param([(1, "a", "2026-10-20T10:00:00Z", [_pytest_job(11, "tests/test_x.py::test_y[parametr]")])], ["| #40 | pytest tests/test_x.py::test_y | #30 W1 r1 |"], id="test-strażnika-z-parametrem-odpalił-w-pr-u-najnowszym-na-gałęzi"),
        pytest.param([(1, "a", "2026-10-20T10:00:00Z", [_pytest_job(11, "tests/test_x.py::test_inny")])], [], id="inny-test-nie-jest-strażnikiem"),
        pytest.param([(1, "b", "2026-10-20T10:00:00Z", [_pytest_job(11, "tests/test_z.py::test_z")])], [], id="test-strażnika-scalonego-po-runie-nie-odpalił"),
        pytest.param([(1, "b", "2026-10-23T10:00:00Z", [_pytest_job(11, "tests/test_z.py::test_z")])], ["| #41 | pytest tests/test_z.py::test_z | #32 W1 r1 |"], id="test-strażnika-scalonego-przed-runem-odpalił"),
        pytest.param([(1, "a", "2026-10-26T10:00:00Z", [_pytest_job(11, "tests/test_x.py::test_y")])], [], id="run-spoza-tygodnia"),
        pytest.param(
            [(1, "a", "2026-10-20T10:00:00Z", [_pytest_job(11, "tests/test_x.py::test_y")]), (2, "a", "2026-10-21T10:00:00Z", [_pytest_job(21, "tests/test_x.py::test_y")])],
            ["| #40 | pytest tests/test_x.py::test_y | #30 W1 r1 |"],
            id="dwa-runy-tego-samego-pr-u-to-jedno-odpalenie",
        ),
        pytest.param(
            [(1, "b", "2026-10-20T10:00:00Z", [_ruff_mypy_job(11, {WEED_STEP: "E   + 'kod/a.py:3: zakazane-wywolanie: bez zakazane()',\nE   + 'kod/b.py:4: inna-regula: bez innej',"})])],
            ["| #41 | ast-grep inna-regula | - |", "| #41 | ast-grep zakazane-wywolanie | #31 W1 r1 |"],
            id="reguła-chwastu-z-logu-kroku-z-ważnym-jej-strażnika",
        ),
        pytest.param(
            [(1, "c", "2026-10-20T10:00:00Z", [_ruff_mypy_job(11, {"Lint Python code": "", "Typecheck Python code (Windows)": "", "Weed rules of the whole tree": "kod/a.py:3"})])],
            ["| #42 | ast-grep | - |", "| #42 | mypy | - |", "| #42 | ruff | - |"],
            id="kroki-ruff-mypy-i-reguł-bez-id-reguły",
        ),
        pytest.param([(1, "nowa", "2026-10-20T10:00:00Z", [_ruff_mypy_job(11, {"Lint Python code": ""})])], ["| gałąź nowa | ruff | - |"], id="run-gałęzi-bez-pr-u-w-skanie"),
    ],
)
def test_odpalenia_straznikow_to_porazki_ich_krokow_i_testow_w_runach_ci_pr_ow_tygodnia(runs: list[tuple[int, str, str, list[tuple[dict[str, object], str]]]], expected: list[str]) -> None:
    assert _rows_of(tydzien.firings(_actions(runs), FIRING_PULLS, WEEK_START, WEEK_END)) == expected


def test_kroki_straznikow_odpalen_to_kroki_ruff_mypy_i_regul_chwastow_zadania_ruff_mypy_w_ci() -> None:
    job = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["ruff-mypy"]
    markers = {straznik.Kind.RUFF: "-m ruff check", straznik.Kind.MYPY: "-m mypy", straznik.Kind.AST_GREP: "tests/test_zapadki.py"}
    found = {step["name"]: kind for step in job["steps"] for kind, marker in markers.items() if marker in str(step.get("run", ""))}

    assert (job["name"], found) == (tydzien.RUFF_MYPY, tydzien.STEP_GUARDS)


@pytest.mark.parametrize(
    ("now", "week"),
    [
        ("2026-11-16T05:00:00+00:00", "2026-11-09"),
        ("2026-11-15T23:30:00+00:00", "2026-11-09"),
        ("2026-11-15T22:30:00+00:00", "2026-11-02"),
        ("2027-04-04T22:30:00+00:00", "2027-03-29"),
    ],
    ids=["poniedzialek-6-00-czasu-zimowego", "poniedzialek-0-30-czasu-polskiego-a-niedziela-w-utc", "niedziela-23-30-czasu-polskiego", "poniedzialek-0-30-czasu-letniego"],
)
def test_bez_tygodnia_pomiar_bierze_ostatni_pelny_tydzien_czasu_polskiego(now: str, week: str) -> None:
    assert tydzien_polski.last_full_week(_at(now)).isoformat() == week


@pytest.mark.parametrize(
    ("now", "cron"),
    [("2026-11-16T05:40:00+00:00", "17 5 * * 1"), ("2027-04-05T04:40:00+00:00", "17 4 * * 1"), ("2026-10-19T04:40:00+00:00", "17 4 * * 1")],
    ids=["poniedzialek-czasu-zimowego", "poniedzialek-czasu-letniego", "poniedzialek-przed-zmiana-czasu-na-zimowy"],
)
def test_z_cronow_workflowu_pomiar_biegnie_tylko_ten_ktory_jest_6_czasu_polskiego_poza_pelna_godzina(now: str, cron: str) -> None:
    """GitHub opóźnia i przy dużym obciążeniu porzuca biegi z cronu na początku godziny, więc żaden cron nie stoi
    na pełnej godzinie ani na jej kwadransie."""

    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    crons = [entry["cron"] for entry in workflow[True]["schedule"]]

    assert [planned for planned in crons if tydzien.on_time(planned, _at(now))] == [cron], crons
    assert [planned for planned in crons if int(planned.split()[0]) % 15 == 0] == [], crons


# Przepływ narzędzia na atrapie GitHuba. Wdrożenie szablonu 1.10.2026 (tydzień od 28.09), pomiar tygodnia 19.10.
FAIL_W1 = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["wazne"]  # R-BEZ-TESTU
FAIL_OTHER = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + chwasty.WERDYKTY["inny-kod"]  # R-DRUGA-DROGA
FAIL_ELSEWHERE = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["wazne-gdzie-indziej"]
OLD = "0" * 40
# Atrapa gh: wyszukiwanie PR-ów jak GitHub (created:>=, sort:created-asc, first) i zapis każdego wywołania (bez
# zapytania GraphQL) do calls.jsonl; renderowania treści (api markdown) nie zna.
FAKE_GH = """\
import json, pathlib, sys

here = pathlib.Path(sys.argv[0]).parent
arguments = sys.argv[1:]
state = json.loads((here / "state.json").read_text(encoding="utf-8"))
with (here / "calls.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps([argument for argument in arguments if not argument.startswith("query=")]) + "\\n")
if arguments[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": state["repo"]}))
elif arguments[:2] == ["api", "graphql"]:
    variables = dict(arguments[index + 1].split("=", 1) for index, value in enumerate(arguments) if value in {"-f", "-F"})
    since = [term.removeprefix("created:>=") for term in variables["q"].split() if term.startswith("created:>=")]
    nodes = sorted((node for node in state["pulls"] if all(node["createdAt"] >= moment for moment in since)), key=lambda node: (node["createdAt"], node["number"]))
    print(json.dumps({"data": {"search": {"nodes": nodes[: int(variables["first"])]}}}))
elif arguments[:2] == ["api", "repos/{owner}/{repo}/issues?labels=chwast&state=open&per_page=100&page=1"]:
    print(json.dumps(state["weeds"]))
elif arguments[:2] == ["api", "repos/{owner}/{repo}/issues?labels=rejestr-korzeni&state=open&per_page=100&page=1"]:
    print(json.dumps(state["own"]))
elif arguments[:2] == ["api", "repos/{owner}/{repo}/labels?per_page=100&page=1"]:
    print(json.dumps([{"name": name} for name in state["labels"]]))
elif arguments[0] == "api" and arguments[1].startswith("repos/{owner}/{repo}/actions/workflows/ci.yml/runs?"):
    query = dict(part.split("=", 1) for part in arguments[1].split("?", 1)[1].split("&"))
    low, high = query["created"].split("..")
    print(json.dumps({"workflow_runs": [run for run in state["runs"] if low <= run["created_at"] <= high]}))
elif arguments[0] == "api" and arguments[1].startswith("repos/{owner}/{repo}/actions/runs/"):
    print(json.dumps({"jobs": state["jobs"][arguments[1].split("/")[5]]}))
elif arguments[0] == "api" and arguments[1].startswith("repos/{owner}/{repo}/actions/jobs/"):
    sys.stdout.write(state["logs"][arguments[1].split("/")[5]])
elif arguments[:2] == ["api", "--method"]:
    with (here / "writes.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps([arguments[2], arguments[3], json.loads(sys.stdin.read())]) + "\\n")
    print(json.dumps({"number": 9100}))
else:
    sys.exit(f"atrapa gh nie zna: {arguments}")
"""


RENDERED = {**werdykty_szablonu.rendered(), **chwasty.rendered(), **korzenie_pr.rendered()}


def _pull(
    number: int,
    verdicts: list[tuple[str, str]],
    *,
    body: str = "",
    merged: str | None = None,
    created: str = "2026-10-02T00:00:00Z",
    closed: bool = False,
    files: Sequence[str] = (),
    branch: str = "galaz",
) -> dict[str, object]:
    """PR ``number`` z zapytania GraphQL rejestru: komentarze werdyktów (treść i chwila utworzenia), opis, merge,
    chwila założenia, zamknięcie bez merge'a i pliki diffu, z HTML każdej treści w ``bodyHTML``."""

    comments = [
        {
            "body": text.format(commit=OLD),
            "bodyHTML": body_html(text.format(commit=OLD), RENDERED),
            "authorAssociation": "OWNER",
            "createdAt": when,
            "includesCreatedEdit": False,
            "author": {"login": "recenzent"},
        }
        for text, when in verdicts
    ]
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "MERGED" if merged else "CLOSED" if closed else "OPEN",
        "isDraft": False,
        "isCrossRepository": False,
        "baseRefName": "main",
        "headRefName": branch,
        "headRefOid": OLD,
        "url": f"https://github.com/{opisy_pr.REPO}/pull/{number}",
        "body": body,
        "bodyHTML": body_html(body, RENDERED),
        "createdAt": created,
        "updatedAt": "2026-10-27T00:00:00Z",
        "mergedAt": merged,
        "files": {"nodes": [{"path": name} for name in files]},
        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": comments},
        "reviews": {"pageInfo": {"hasNextPage": False}, "nodes": []},
    }


PULLS = [
    # Ważne w tygodniu 5.10, a PR scalony w tygodniu 19.10: Ważne liczy się w chwili werdyktu
    _pull(1436, [(FAIL_W1, "2026-10-07T10:00:00Z")], merged="2026-10-20T08:00:00Z"),
    _pull(1437, [(FAIL_W1, "2026-10-20T10:00:00Z")]),
    _pull(1438, [(FAIL_OTHER, "2026-10-21T10:00:00Z")]),
    # scalony w poniedziałek 19.10 o 0:30 czasu letniego, a w UTC jeszcze w niedzielę 18.10
    _pull(1439, [], body=korzenie_pr.OPISY["czerwony-main"], merged="2026-10-18T22:30:00Z"),
    # Ważne w poniedziałek 26.10 o 0:30 czasu zimowego, po tygodniu pomiaru
    _pull(1440, [(FAIL_W1, "2026-10-25T23:30:00Z")]),
]
WEEDS = [{"number": 1520, "title": "Chwast: R-DRUGA-DROGA", "body": ""}, {"number": 1519, "title": "Chwast: R-BEZ-TESTU", "body": ""}]
WEEK_12 = """\
## Pomiar

| Okres | Wystąpienia | Poszerzenia reguł |
| --- | --- | --- |
| Tydzień 2026-10-12 | 0 | 0 |
| Od wdrożenia 2026-10-01 | 1 | 0 |

## Czekanie

| Okres | Merge'e | Bez PASS na HEAD | Mediana PASS → merge | Najdłużej | Ponad 1 h |
| --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-12 | 0 | 0 | - | - | 0 |
| Od wdrożenia 2026-10-01 | 0 | 0 | - | - | 0 |

## Reguły

| Reguła | PR-y z odpaleniem z 0 ostatnich |
| --- | --- |
| Każda reguła | 0 |

## Odpalenia strażników

Licznik nie widzi prób złapanych lokalnie przed pushem ani błędów bez strażnika.

| PR | Strażnik | Ważne strażnika |
| --- | --- | --- |

## Poszerzenia reguł

| PR | Reguła | Pola |
| --- | --- | --- |

## Strażniki

| Okres | Ważne | mypy | ruff | ast-grep | pytest | brak - proza | brak - test | brak - napęd | brak - usunięte | Bez strażnika | Udział wyjątków |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| Od wdrożenia 2026-10-15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |

## Wyjątki strażnika

| Ważne | Strażnik |
| --- | --- |

## Po limicie rund

| Nowy PR | PR zamknięty po limicie | Wspólne pliki |
| --- | --- | --- |

## Kody

| Kod | Tydzień | Od wdrożenia |
| --- | --- | --- |
| R-BEZ-TESTU | 0 | 1 |

## Chwasty

| Issue | Kod |
| --- | --- |
| #1519 | R-BEZ-TESTU |
| #1520 | R-DRUGA-DROGA |

## Historia

| Tydzień | Wystąpienia | Poszerzenia reguł |
| --- | --- | --- |
| 2026-09-28 | 0 | 0 |
| 2026-10-05 | 1 | 0 |
| 2026-10-12 | 0 | 0 |
"""
WEEK_19 = """\
## Pomiar

| Okres | Wystąpienia | Poszerzenia reguł |
| --- | --- | --- |
| Tydzień 2026-10-19 | 3 | 0 |
| Od wdrożenia 2026-10-01 | 4 | 0 |

## Czekanie

| Okres | Merge'e | Bez PASS na HEAD | Mediana PASS → merge | Najdłużej | Ponad 1 h |
| --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-19 | 2 | 2 | - | - | 0 |
| Od wdrożenia 2026-10-01 | 2 | 2 | - | - | 0 |

## Reguły

| Reguła | PR-y z odpaleniem z 0 ostatnich |
| --- | --- |
| Każda reguła | 0 |

## Odpalenia strażników

Licznik nie widzi prób złapanych lokalnie przed pushem ani błędów bez strażnika.

| PR | Strażnik | Ważne strażnika |
| --- | --- | --- |

## Poszerzenia reguł

| PR | Reguła | Pola |
| --- | --- | --- |

## Strażniki

| Okres | Ważne | mypy | ruff | ast-grep | pytest | brak - proza | brak - test | brak - napęd | brak - usunięte | Bez strażnika | Udział wyjątków |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-19 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |
| Od wdrożenia 2026-10-15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | - |

## Wyjątki strażnika

| Ważne | Strażnik |
| --- | --- |

## Po limicie rund

| Nowy PR | PR zamknięty po limicie | Wspólne pliki |
| --- | --- | --- |

## Kody

| Kod | Tydzień | Od wdrożenia |
| --- | --- | --- |
| R-BEZ-TESTU | 2 | 3 |
| R-DRUGA-DROGA | 1 | 1 |

## Chwasty

| Issue | Kod |
| --- | --- |
| #1519 | R-BEZ-TESTU |
| #1520 | R-DRUGA-DROGA |

## Historia

| Tydzień | Wystąpienia | Poszerzenia reguł |
| --- | --- | --- |
| 2026-09-28 | 0 | 0 |
| 2026-10-05 | 1 | 0 |
| 2026-10-12 | 0 | 0 |
| 2026-10-19 | 3 | 0 |
"""


OLD_BODY = """\
## Pomiar

| Okres | Wystąpienia | Powroty idiomu | Udział powrotów | Ucieczki | Połączenia między PR-ami | Powroty mimo strażnika |
| --- | --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-12 | 9 | 9 | 100% | 9 | 9 | 9 |

## Historia

| Tydzień | Wystąpienia | Powroty idiomu | Udział powrotów | Ucieczki | Połączenia między PR-ami | Powroty mimo strażnika |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-10-05 | 9 | 9 | 100% | 9 | 9 | 9 |
"""


class RegistryGitHub(FakeGitHub):
    """Checkout z narzędziem pomiaru, ``origin`` z ADR 0031 wdrożonym 1.10.2026 i atrapa ``gh`` z PR-ami ``pulls``,
    otwartymi issues chwastów ``WEEDS``, otwartymi issues z etykietą ``rejestr-korzeni`` ``own`` i etykietami
    repozytorium ``labels``."""

    def __init__(
        self,
        tmp_path: Path,
        own: list[dict[str, object]],
        *,
        pulls: list[dict[str, object]] = PULLS,
        labels: tuple[str, ...] = ("chwast",),
        files: dict[str, str] | None = None,
        started: str | None = None,
        actions: _Actions | None = None,
    ) -> None:
        tmp_path.mkdir()
        super().__init__(tmp_path, {"docs/adr/README.md": "# ADR\n", **(files or {})}, tool="tools/rejestr_korzeni_tydzien.py", gh=FAKE_GH, started=started)
        for moment, marker in [(DEPLOYED, szablon_werdyktu.ADR), (GUARDED, bramka_straznika.MARKER)]:
            with pytest.MonkeyPatch.context() as patch:
                patch.setenv("GIT_COMMITTER_DATE", moment.isoformat())
                self.push_main({marker: "# ADR\n"})
        actions = actions or _Actions([], {}, {})
        runs = {"runs": actions.runs, "jobs": {str(run): jobs for run, jobs in actions.jobs.items()}, "logs": {str(job): log for job, log in actions.logs.items()}}
        state = {"repo": opisy_pr.REPO, "pulls": pulls, "weeds": WEEDS, "own": own, "labels": list(labels), **runs}
        (self.bin / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def writes(self) -> list[list[object]]:
        return self._lines("writes.jsonl")

    def calls(self) -> list[str]:
        """Każde wywołanie ``gh`` po kolei: ``repo view``, ``graphql``, ``markdown`` albo ścieżka REST."""

        return [" ".join(map(str, call[:2])) if call[0] != "api" else "graphql" if call[1] == "graphql" else str(call[1]) for call in self._lines("calls.jsonl")]

    def _lines(self, name: str) -> list[list[object]]:
        log = self.bin / name
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _measure(github: RegistryGitHub, *arguments: str) -> list[str]:
    answered: subprocess.CompletedProcess[str] = github.run(*arguments)
    assert answered.returncode == 0, answered.stdout + answered.stderr
    return answered.stdout.splitlines()


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pierwszy_pomiar_bez_issue_zaklada_etykiete_i_rejestr_korzeni_z_nia_a_kolejny_zmienia_jego_tresc_z_historia(tmp_path: Path) -> None:
    """Issue „Rejestr korzeni” ma własną etykietę, żeby lista z etykietą ``chwast`` miała same chwasty."""

    first = RegistryGitHub(tmp_path / "pierwszy", [])

    created = _measure(first, "--tydzien", "2026-10-14")

    label = {"name": "rejestr-korzeni", "color": "5319e7", "description": "Tygodniowy pomiar powtórzeń korzeni (ADR 0031)"}
    assert first.writes() == [["POST", "repos/{owner}/{repo}/labels", label], ["POST", "repos/{owner}/{repo}/issues", {"title": "Rejestr korzeni", "body": WEEK_12, "labels": ["rejestr-korzeni"]}]]
    assert created == [
        "REJESTR KORZENI | założona etykieta rejestr-korzeni",
        "REJESTR KORZENI | założone #9100 „Rejestr korzeni”",
        "REJESTR KORZENI OK | tydzień 2026-10-12: 0 wystąpień, 0 odpaleń strażników, 0 poszerzeń reguł, 0 Ważnych w wątkach strażnika",
    ]

    labelled = RegistryGitHub(tmp_path / "z-etykieta", [], labels=("chwast", "rejestr-korzeni"))
    _measure(labelled, "--tydzien", "2026-10-14")
    assert [write[1] for write in labelled.writes()] == ["repos/{owner}/{repo}/issues"]

    later = RegistryGitHub(tmp_path / "kolejny", [{"number": 1600, "title": "Rejestr korzeni", "body": OLD_BODY}])

    edited = _measure(later, "--tydzien", "2026-10-25")

    assert later.writes() == [["PATCH", "repos/{owner}/{repo}/issues/1600", {"body": WEEK_19}]]
    assert edited == ["REJESTR KORZENI | zmieniona treść #1600", "REJESTR KORZENI OK | tydzień 2026-10-19: 3 wystąpień, 0 odpaleń strażników, 0 poszerzeń reguł, 0 Ważnych w wątkach strażnika"]


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pomiar_z_ta_sama_trescia_niczego_nie_zapisuje_a_bez_zapisu_drukuje_tresc(tmp_path: Path) -> None:
    same = RegistryGitHub(tmp_path / "ta-sama", [{"number": 1600, "title": "Rejestr korzeni", "body": WEEK_19.replace("\n", "\r\n")}])
    dry = RegistryGitHub(tmp_path / "bez-zapisu", [])

    unchanged = _measure(same, "--tydzien", "2026-10-19")
    printed = _measure(dry, "--tydzien", "2026-10-19", "--bez-zapisu")

    assert same.writes() == [] and unchanged[0] == "REJESTR KORZENI | #1600 ma już tę treść", unchanged
    assert dry.writes() == []
    assert printed[:2] == ["REJESTR KORZENI | bez zapisu: załóż etykietę rejestr-korzeni", "REJESTR KORZENI | bez zapisu: załóż issue „Rejestr korzeni” z etykietami rejestr-korzeni"], printed
    assert "\n".join(printed[2:-1]) == WEEK_19, printed


# Budżet GITHUB_TOKEN workflowu (W1 r1 #1525): 1000 punktów GraphQL i 1000 żądań REST na godzinę na repozytorium.
@ONLY_FOUND_BY_NAME_ON_POSIX
@pytest.mark.parametrize(("count", "pages"), [(5, 1), (45, 3)], ids=["jedna-strona", "trzy-strony"])
def test_przebieg_czyta_werdykty_z_tej_samej_strony_graphql_bez_renderowania_kazdego(tmp_path: Path, count: int, pages: int) -> None:
    """Każdy PR ma werdykt ``FAIL`` z kodem, a przebieg zużywa stronę GraphQL na każde 19 PR-ów (strona to 20 PR-ów
    od chwili założenia ostatniego z poprzedniej) i stałą liczbę żądań REST, bez wywołania renderera na werdykt."""

    pulls = [_pull(1000 + index, [(FAIL_W1, f"2026-10-20T10:{index:02d}:00Z")], created=f"2026-10-02T00:{index:02d}:00Z") for index in range(count)]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls)

    lines = _measure(github, "--tydzien", "2026-10-19", "--bez-zapisu")

    assert lines[-1].startswith(f"REJESTR KORZENI OK | tydzień 2026-10-19: {count} wystąpień, 0 odpaleń strażników"), lines
    issues = "repos/{owner}/{repo}/issues?labels={label}&state=open&per_page=100&page=1"
    rest = [issues.format(owner="{owner}", repo="{repo}", label=label) for label in ("chwast", "rejestr-korzeni")]
    runs = f"{tydzien.CI_RUNS}&created=2026-10-18T22:00:00Z..2026-10-25T23:00:00Z&per_page=100&page=1"
    assert github.calls() == ["repo view", *["graphql"] * pages, runs, *rest, "repos/{owner}/{repo}/labels?per_page=100&page=1"]


@pytest.mark.parametrize("sample", ["fail", "pass"])
def test_werdykt_z_bodyhtml_graphql_daje_te_same_jednostki_co_renderer_tresci_pod_dwiema_pierwszymi_liniami(sample: str) -> None:
    """Prawdziwe werdykty z GitHuba (``tests/fixtures/body_html.json``): ``bodyHTML`` to HTML całej treści z blokami
    kodu w osłonie ``snippet-clipboard-content``, a renderer dostaje treść pod dwiema pierwszymi liniami."""

    recorded = SAMPLES[sample]
    verdict = werdykt_pr.read({"body": recorded["body"], "bodyHTML": recorded["bodyHTML"], "authorAssociation": "OWNER"}, OLD)
    assert verdict is not None

    rendered = szablon_werdyktu.items(recorded["rendered"])
    assert werdykt_pr.from_graphql(verdict) == rendered
    assert szablon_werdyktu.findings(rendered) == szablon_werdyktu.findings(werdykt_pr.from_graphql(verdict)) != szablon_werdyktu.Findings((), ())


@pytest.mark.parametrize("sample", ["opis", "issue"])
def test_opis_pr_i_issue_chwastu_z_bodyhtml_graphql_daja_te_same_jednostki_co_renderer(sample: str) -> None:
    recorded = SAMPLES[sample]

    units = szablon_werdyktu.items(recorded["bodyHTML"])

    assert units == szablon_werdyktu.items(recorded["rendered"])
    assert rejestr_korzeni.section(units) == rejestr_korzeni.section(szablon_werdyktu.items(recorded["rendered"]))


PASS = "WERDYKT: PASS {commit}\nZnaleziska: 0 (Ważne 0, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["sprawdzone"]


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pass_na_head_z_werdyktow_skanu_daje_czekanie_a_pass_na_innym_commicie_to_merge_bez_pass(tmp_path: Path) -> None:
    other = "1" * 40
    pulls = [
        _pull(1450, [(FAIL_W1, "2026-10-20T10:00:00Z"), (PASS, "2026-10-20T11:00:00Z")], merged="2026-10-20T11:30:00Z"),
        _pull(1451, [(PASS.replace("{commit}", other), "2026-10-20T11:00:00Z")], merged="2026-10-20T11:30:00Z"),
    ]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls)

    text = "\n".join(_measure(github, "--tydzien", "2026-10-19", "--bez-zapisu")[2:-1])

    assert _rows(text, "Pomiar")[0] == "| Tydzień 2026-10-19 | 1 | 0 |", text
    assert _rows(text, "Czekanie")[0] == "| Tydzień 2026-10-19 | 2 | 1 | 30 min | 30 min | 0 |", text


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pr_scalony_przed_wdrozeniem_i_zmieniony_po_nim_nie_liczy_sie_od_wdrozenia(tmp_path: Path) -> None:
    """Skan bierze każdy PR zmieniony po wdrożeniu, więc stary scalony PR z późniejszym komentarzem w nim jest, a jego
    merge i blok czerwonego `main` są sprzed wdrożenia."""

    pulls = [_pull(1460, [], body=korzenie_pr.OPISY["czerwony-main"], merged="2026-09-20T10:00:00Z", created="2026-09-19T00:00:00Z")]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls)

    text = "\n".join(_measure(github, "--tydzien", "2026-10-12", "--bez-zapisu")[2:-1])

    assert _rows(text, "Pomiar")[1] == "| Od wdrożenia 2026-10-01 | 0 | 0 |", text
    assert _rows(text, "Czekanie")[1] == "| Od wdrożenia 2026-10-01 | 0 | 0 | - | - | 0 |", text


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pr_zamkniety_bez_merge_po_trzech_rundach_z_fail_daje_nowy_pr_na_jego_plikach_w_raporcie(tmp_path: Path) -> None:
    """Skan rozpoznaje PR zamknięty po limicie rund z jego werdyktów: trzy rundy z FAIL i zamknięcie bez merge'a; PR
    zamknięty po dwóch rundach z Ważnymi w różnych miejscach i PR otwarty po trzech nie są zamknięte po limicie, a PR
    założony między pierwszym a ostatnim FAIL zamkniętego to praca równoległa, nie nowy PR po limicie."""

    fails = [(FAIL_W1.replace("{commit}", sha * 40), f"2026-10-13T1{index}:00:00Z") for index, sha in enumerate("123")]
    elsewhere = (FAIL_ELSEWHERE.replace("{commit}", "2" * 40), fails[1][1])
    pulls = [
        _pull(1470, fails, closed=True, created="2026-10-05T00:00:00Z", files=["kod/limit.py", "kod/test_limitu.py"]),
        _pull(1471, [fails[0], elsewhere], closed=True, created="2026-10-05T00:01:00Z", files=["kod/dwie.py"]),
        _pull(1472, fails, created="2026-10-05T00:02:00Z", files=["kod/otwarty.py"]),
        _pull(1473, [], created="2026-10-14T00:00:00Z", files=["kod/limit.py", "kod/dwie.py", "kod/otwarty.py"]),
        _pull(1474, [], created="2026-10-13T10:30:00Z", files=["kod/limit.py"]),
    ]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls, started=DEPLOYED.isoformat())

    text = "\n".join(_measure(github, "--tydzien", "2026-10-12", "--bez-zapisu")[2:-1])

    assert _rows(text, "Po limicie rund") == ["| #1473 | #1470 | 1 |"], text


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_straznik_waznego_czyta_selektor_z_opisu_scalonego_pr_tylko_w_watku_po_wdrozeniu_warunku_straznika(tmp_path: Path) -> None:
    """Granica to chwila, w której ``bramka_straznika.MARKER`` wszedł do ``main`` (tu 15.10): PR z pierwszym werdyktem
    przed nią kończy z ``Dowód:`` i nie liczy się, a PR otwarty jeszcze się nie scalił; selektor spoza listy to Ważne bez
    strażnika."""

    after = "2026-10-16T10:00:00Z"
    pulls = [
        _pull(1480, [(FAIL_W1, after)], body=korzenie_pr.OPISY["straznik-c"], merged="2026-10-20T10:00:00Z"),
        _pull(1481, [(FAIL_W1, after)], body=korzenie_pr.OPISY["straznik-brak-testu"], merged="2026-10-20T10:00:00Z"),
        _pull(1482, [(FAIL_W1, after)], body=korzenie_pr.OPISY["straznik-spoza-listy"], merged="2026-10-20T10:00:00Z"),
        _pull(1483, [(FAIL_W1, "2026-10-14T10:00:00Z")], body=korzenie_pr.OPISY["straznik-c"], merged="2026-10-20T10:00:00Z"),
        _pull(1484, [(FAIL_W1, after)], body=korzenie_pr.OPISY["straznik-c"]),
    ]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls)

    lines = _measure(github, "--tydzien", "2026-10-19", "--bez-zapisu")
    text = "\n".join(lines[2:-1])

    assert _rows(text, "Strażniki")[0] == "| Tydzień 2026-10-19 | 3 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 33% |", text
    assert _rows(text, "Wyjątki strażnika") == ["| #1481 W1 r1 | brak - test |", "| #1482 W1 r1 | - |"], text
    assert lines[-1].endswith(", 3 Ważnych w wątkach strażnika"), lines


RULE = 'id: zakazane-wywolanie\nlanguage: python\nseverity: error\nmessage: bez zakazane()\nfiles:\n  - "**/*.py"\nrule:\n  pattern: $O.zakazane()\n'
needs_ast_grep = pytest.mark.skipif(tydzien.AST_GREP is None, reason="ast-grep z dodatku dev, a zadania pytest na Windows instalują tylko requirements.txt")


@ONLY_FOUND_BY_NAME_ON_POSIX
@needs_ast_grep
def test_odpalenia_regul_z_checkoutu_licza_pr_y_ktorych_merge_dodaje_linie_z_odpaleniem(tmp_path: Path) -> None:
    """Merge sprzed końca tygodnia z odpaleniem na dodanej linii, merge bez odpalenia i merge po tygodniu, którego
    pomiar tygodnia nie widzi; dawne odpalenie w pliku startowym nie jest linią dodaną."""

    files = {"sgconfig.yml": "ruleDirs:\n  - reguly-ast-grep\n", "reguly-ast-grep/zakazane.yml": RULE, "stare.py": "obiekt.zakazane()\n"}
    github = RegistryGitHub(tmp_path / "gh", [], pulls=[], files=files)
    for number, (name, text), when in [
        (7, ("kod/a.py", "def a(obiekt):\n    obiekt.zakazane()\n"), "2026-10-20T10:00:00+00:00"),
        (8, ("kod/b.py", "def b(obiekt):\n    obiekt.dozwolone()\n"), "2026-10-21T10:00:00+00:00"),
        (9, ("kod/c.py", "def c(obiekt):\n    obiekt.zakazane()\n"), "2026-10-27T10:00:00+00:00"),
    ]:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("GIT_COMMITTER_DATE", when)
            branch = github.commit_on("main", {name: text}, f"PR {number}")
            git(github.checkout, "merge", "--quiet", "--no-ff", "--message", f"Merge pull request #{number} from organizacja/galaz-{number}", branch)
    git(github.checkout, "push", "--quiet", "origin", "main")

    text = "\n".join(_measure(github, "--tydzien", "2026-10-19", "--bez-zapisu")[2:-1])

    assert text.splitlines()[text.splitlines().index("## Reguły") + 2] == "| Reguła | PR-y z odpaleniem z 2 ostatnich |", text
    assert _rows(text, "Reguły") == ["| zakazane-wywolanie | 1 |", "| Każda reguła | 1 (50%) |"], text


BANS = '[lint.flake8-tidy-imports.banned-api]\n"a.b".msg = "nie a.b"\n"a.c".msg = "nie a.b"\n"x.y".msg = "nie x.y"\n\n[lint.per-file-ignores]\n"kod/wlasciciel.py" = ["TID251"]\n'


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_poszerzenie_reguly_to_zmiana_zasiegu_reguly_z_bazy_merge_a_bez_zmiany_komunikatu_i_nowej_reguly(tmp_path: Path) -> None:
    rule = "reguly-ast-grep/zakazane.yml"
    files = {"sgconfig.yml": "ruleDirs:\n  - reguly-ast-grep\n", rule: RULE, "ruff.toml": BANS}
    github = RegistryGitHub(tmp_path / "gh", [], pulls=[], files=files)
    scoped = RULE.replace('  - "**/*.py"', '  - "kod/**/*.py"')
    worded = scoped.replace("message: bez zakazane()", "message: bez zakazane(), weź dozwolone()")
    widened = worded.replace("$O.zakazane()", "$O.zakazane($$$)")
    owned = f"# komentarz reguły\n{widened}ignores:\n  - kod/wlasciciel.py\n"
    named = BANS.replace('"x.y"', '"a.d".msg = "nie a.b"\n"x.y"')
    reworded = named.replace("nie a.b", "nigdy a.b")
    for number, changed, when in [
        (6, {rule: scoped}, "2026-10-13T10:00:00+00:00"),
        (7, {rule: worded}, "2026-10-20T10:00:00+00:00"),
        (8, {rule: widened}, "2026-10-20T11:00:00+00:00"),
        (9, {"reguly-ast-grep/nowa.yml": RULE.replace("zakazane-wywolanie", "nowa-regula")}, "2026-10-20T12:00:00+00:00"),
        (10, {rule: owned}, "2026-10-20T13:00:00+00:00"),
        (11, {"ruff.toml": named}, "2026-10-21T10:00:00+00:00"),
        (12, {"ruff.toml": reworded}, "2026-10-21T11:00:00+00:00"),
        (13, {"ruff.toml": f'{reworded}"kod/drugi.py" = ["TID251"]\n'}, "2026-10-21T12:00:00+00:00"),
        (14, {rule: RULE}, "2026-10-27T10:00:00+00:00"),
    ]:
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("GIT_COMMITTER_DATE", when)
            branch = github.commit_on("main", changed, f"PR {number}")
            git(github.checkout, "merge", "--quiet", "--no-ff", "--message", f"Merge pull request #{number} from organizacja/galaz-{number}", branch)
        if number == 10:
            with pytest.MonkeyPatch.context() as patch:
                patch.setenv("GIT_COMMITTER_DATE", "2026-10-20T14:00:00+00:00")
                github.push_main({rule: owned.replace("$O.zakazane($$$)", "$O.zakazane(1)")})
    git(github.checkout, "push", "--quiet", "origin", "main")

    lines = _measure(github, "--tydzien", "2026-10-19", "--bez-zapisu")
    text = "\n".join(lines[2:-1])

    assert _rows(text, "Poszerzenia reguł") == [
        "| #8 | zakazane-wywolanie | rule |",
        "| #10 | zakazane-wywolanie | ignores |",
        "| #11 | banned-api a.b | nazwy |",
        "| #13 | banned-api ruff.toml | per-file-ignores |",
    ], text
    assert _rows(text, "Pomiar") == ["| Tydzień 2026-10-19 | 0 | 4 |", "| Od wdrożenia 2026-10-01 | 0 | 5 |"], text
    assert _rows(text, "Historia")[-2:] == ["| 2026-10-12 | 0 | 1 |", "| 2026-10-19 | 0 | 4 |"], text
    assert lines[-1].endswith(": 0 wystąpień, 0 odpaleń strażników, 4 poszerzeń reguł, 0 Ważnych w wątkach strażnika"), lines


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_odpalenia_strażnikow_z_runow_ci_tygodnia_trafiaja_do_tresci_issue_z_linia_granic(tmp_path: Path) -> None:
    pulls = [
        _pull(1480, [(FAIL_W1, "2026-10-16T10:00:00Z")], body=korzenie_pr.OPISY["straznik-c"], merged="2026-10-19T10:00:00Z"),
        _pull(1490, [], created="2026-10-20T08:00:00Z", branch="feat/praca"),
    ]
    actions = _actions([
        (1, "feat/praca", "2026-10-21T10:00:00Z", [_ruff_mypy_job(11, {"Typecheck Python code (Linux)": "kod/a.py:3: error"})]),
        (2, "feat/praca", "2026-10-26T10:00:00Z", [_ruff_mypy_job(21, {"Lint Python code": "kod/a.py:3:1: F401"})]),
    ])
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls, actions=actions)

    text = "\n".join(_measure(github, "--tydzien", "2026-10-19", "--bez-zapisu")[2:-1])

    section = text.split("## Odpalenia strażników\n", 1)[1].split("\n## ", 1)[0]
    assert section.splitlines()[1] == tydzien.GRANICE, text
    assert _rows(text, "Odpalenia strażników") == ["| #1490 | mypy | - |"], text
