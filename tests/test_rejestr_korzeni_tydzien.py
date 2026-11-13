"""``tools/rejestr_korzeni_tydzien.py``: tygodniowy pomiar korzeni w treści issue „Rejestr korzeni” (ADR 0031, Q1,
Q19, Q23) i workflow ``rejestr-korzeni.yml``, który go uruchamia w poniedziałek o 6:00 czasu polskiego.

Wymagania bierzemy z ADR 0031 i decyzji Maksa: powtórzenie to wystąpienie kodu, który wystąpił wcześniej w innym PR
(Q1), tydzień to poniedziałek–niedziela czasu taty i Maksa (``Europe/Warsaw``), a issue zmienia się treścią, bez
komentarzy. Testy przepływu biegną na prawdziwym Gicie z ``origin`` i atrapie ``gh``, która podaje PR-y z zapytania
rejestru i HTML treści nagrany z renderera GitHuba (``tests/fixtures/werdykty_szablonu.json``, ``chwasty.json``,
``korzenie_pr.json``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from tests.fixtures import chwasty, korzenie_pr, opisy_pr, werdykty_szablonu
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub

from rejestr_korzeni import Occurrence
import rejestr_korzeni_tydzien as tydzien
import szablon_werdyktu

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rejestr-korzeni.yml"
DEPLOYED = datetime(2026, 10, 1, tzinfo=UTC)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _occurrence(pull: int, code: str, when: str, major: str = "W1 r1") -> Occurrence:
    return Occurrence(code, pull, major, 1, "-", "-", _at(when))


def _rows(text: str, section: str) -> list[str]:
    """Wiersze danych tabeli sekcji ``## section`` treści issue (bez nagłówka i linii ``---``)."""

    lines = text.splitlines()
    start = lines.index(f"## {section}")
    end = next((index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")), len(lines))
    return [line for line in lines[start + 1 : end] if line.startswith("| ")][2:]


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
    text = tydzien.body([_occurrence(1, "R-BEZ-TESTU", when)], [], date(2026, 10, 26), DEPLOYED)

    history = {row.split(" | ")[0].removeprefix("| "): row for row in _rows(text, "Historia")}
    assert [name for name, row in history.items() if " | 1 | " in row] == [week], text


@pytest.mark.parametrize(
    ("found", "repeats"),
    [
        ([_occurrence(1, "R-BEZ-TESTU", "2026-10-13T10:00:00+00:00"), _occurrence(2, "R-BEZ-TESTU", "2026-10-14T10:00:00+00:00")], 1),
        ([_occurrence(2, "R-BEZ-TESTU", "2026-10-14T10:00:00+00:00"), _occurrence(1, "R-BEZ-TESTU", "2026-10-13T10:00:00+00:00")], 1),
        ([_occurrence(1, "R-BEZ-TESTU", "2026-10-13T10:00:00+00:00"), _occurrence(1, "R-BEZ-TESTU", "2026-10-14T10:00:00+00:00", "W1 r2")], 0),
        ([_occurrence(1, "R-BEZ-TESTU", "2026-10-13T10:00:00+00:00"), _occurrence(2, "R-DRUGA-DROGA", "2026-10-14T10:00:00+00:00")], 0),
        ([_occurrence(1, "R-BEZ-TESTU", "2026-10-13T10:00:00+00:00"), _occurrence(2, "R-BEZ-TESTU", "2026-10-13T10:00:00+00:00")], 0),
    ],
    ids=["ten-sam-kod-pozniej-w-innym-pr", "kolejnosc-z-rejestru-nie-zmienia-powtorzen", "ten-sam-kod-drugi-raz-w-tym-samym-pr", "inny-kod-w-innym-pr", "ten-sam-kod-w-tej-samej-chwili-w-innym-pr"],
)
def test_powtorzenie_to_wystapienie_kodu_ktory_wystapil_wczesniej_w_innym_pr(found: list[Occurrence], repeats: int) -> None:
    text = tydzien.body(found, [], date(2026, 10, 12), DEPLOYED)

    share = {0: "0%", 1: "50%"}[repeats]
    assert _rows(text, "Pomiar")[0] == f"| Tydzień 2026-10-12 | 2 | {repeats} | {share} |", text


def test_tydzien_bez_wystapien_ma_zero_i_udzial_bez_wartosci() -> None:
    text = tydzien.body([_occurrence(1, "R-BEZ-TESTU", "2026-10-06T10:00:00+00:00")], [], date(2026, 10, 12), DEPLOYED)

    assert _rows(text, "Pomiar") == ["| Tydzień 2026-10-12 | 0 | 0 | - |", "| Od wdrożenia 2026-10-01 | 1 | 0 | 0% |"], text
    assert _rows(text, "Kody") == ["| R-BEZ-TESTU | 0 | 1 |"], text
    assert _rows(text, "Historia")[-1] == "| 2026-10-12 | 0 | 0 | - |", text


def test_historia_ma_najwyzej_26_ostatnich_tygodni_od_tygodnia_wdrozenia() -> None:
    text = tydzien.body([], [], date(2027, 6, 7), DEPLOYED)

    weeks = [row.split(" | ")[0].removeprefix("| ") for row in _rows(text, "Historia")]
    assert (len(weeks), weeks[0], weeks[-1]) == (26, "2026-12-14", "2027-06-07"), weeks
    assert [row.split(" | ")[0].removeprefix("| ") for row in _rows(tydzien.body([], [], date(2026, 10, 5), DEPLOYED), "Historia")] == ["2026-09-28", "2026-10-05"]


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
    assert tydzien.last_full_week(_at(now)).isoformat() == week


@pytest.mark.parametrize(
    ("now", "cron"),
    [("2026-11-16T05:20:00+00:00", "0 5 * * 1"), ("2027-04-05T04:20:00+00:00", "0 4 * * 1"), ("2026-10-19T04:20:00+00:00", "0 4 * * 1")],
    ids=["poniedzialek-czasu-zimowego", "poniedzialek-czasu-letniego", "poniedzialek-przed-zmiana-czasu-na-zimowy"],
)
def test_z_cronow_workflowu_pomiar_biegnie_tylko_ten_ktory_jest_6_00_czasu_polskiego(now: str, cron: str) -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    crons = [entry["cron"] for entry in workflow[True]["schedule"]]

    assert [planned for planned in crons if tydzien.on_time(planned, _at(now))] == [cron], crons


# Przepływ narzędzia na atrapie GitHuba. Wdrożenie szablonu 1.10.2026 (tydzień od 28.09), pomiar tygodnia 19.10.
FAIL_W1 = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["wazne"]  # R-BEZ-TESTU
FAIL_OTHER = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + chwasty.WERDYKTY["inny-kod"]  # R-DRUGA-DROGA
OLD = "0" * 40
FAKE_GH = """\
import json, pathlib, sys

here = pathlib.Path(sys.argv[0]).parent
arguments = sys.argv[1:]
state = json.loads((here / "state.json").read_text(encoding="utf-8"))
if arguments[:2] == ["repo", "view"]:
    print(json.dumps({"nameWithOwner": state["repo"]}))
elif arguments[:2] == ["api", "graphql"]:
    print(json.dumps({"data": {"search": {"nodes": state["pulls"]}}}))
elif arguments == ["api", "markdown", "--input", "-"]:
    request = json.loads(sys.stdin.read())
    if request["text"] not in state["markdown"]:
        sys.exit(f"atrapa gh nie zna treści: {request['text']!r}")
    print(state["markdown"][request["text"]], end="")
elif arguments[:2] == ["api", "repos/{owner}/{repo}/issues?labels=chwast&state=open&per_page=100&page=1"]:
    print(json.dumps(state["issues"]))
elif arguments[:2] == ["api", "--method"]:
    with (here / "writes.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps([arguments[2], arguments[3], json.loads(sys.stdin.read())]) + "\\n")
    print(json.dumps({"number": 9100}))
else:
    sys.exit(f"atrapa gh nie zna: {arguments}")
"""


def _pull(number: int, verdicts: list[tuple[str, str]], *, body: str = "", merged: str | None = None) -> dict[str, object]:
    """PR ``number`` z zapytania GraphQL rejestru: komentarze werdyktów (treść i chwila utworzenia), opis i merge."""

    comments = [
        {"body": text.format(commit=OLD), "authorAssociation": "OWNER", "createdAt": when, "includesCreatedEdit": False, "author": {"login": "recenzent"}}
        for text, when in verdicts
    ]
    return {
        "number": number,
        "title": f"PR {number}",
        "state": "MERGED" if merged else "OPEN",
        "isDraft": False,
        "isCrossRepository": False,
        "baseRefName": "main",
        "headRefOid": OLD,
        "url": f"https://github.com/{opisy_pr.REPO}/pull/{number}",
        "body": body,
        "createdAt": "2026-10-02T00:00:00Z",
        "updatedAt": "2026-10-27T00:00:00Z",
        "mergedAt": merged,
        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": comments},
        "reviews": {"pageInfo": {"hasNextPage": False}, "nodes": []},
    }


PULLS = [
    _pull(1436, [(FAIL_W1, "2026-10-07T10:00:00Z")]),
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

| Okres | Wystąpienia | Powtórzenia | Udział powtórzeń |
| --- | --- | --- | --- |
| Tydzień 2026-10-12 | 0 | 0 | - |
| Od wdrożenia 2026-10-01 | 1 | 0 | 0% |

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

| Tydzień | Wystąpienia | Powtórzenia | Udział powtórzeń |
| --- | --- | --- | --- |
| 2026-09-28 | 0 | 0 | - |
| 2026-10-05 | 1 | 0 | 0% |
| 2026-10-12 | 0 | 0 | - |
"""
WEEK_19 = """\
## Pomiar

| Okres | Wystąpienia | Powtórzenia | Udział powtórzeń |
| --- | --- | --- | --- |
| Tydzień 2026-10-19 | 3 | 2 | 67% |
| Od wdrożenia 2026-10-01 | 4 | 2 | 50% |

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

| Tydzień | Wystąpienia | Powtórzenia | Udział powtórzeń |
| --- | --- | --- | --- |
| 2026-09-28 | 0 | 0 | - |
| 2026-10-05 | 1 | 0 | 0% |
| 2026-10-12 | 0 | 0 | - |
| 2026-10-19 | 3 | 2 | 67% |
"""


class RegistryGitHub(FakeGitHub):
    """Checkout z narzędziem pomiaru, ``origin`` z ADR 0031 wdrożonym 1.10.2026 i atrapa ``gh`` z PR-ami ``PULLS``."""

    def __init__(self, tmp_path: Path, issues: list[dict[str, object]]) -> None:
        tmp_path.mkdir()
        super().__init__(tmp_path, {"docs/adr/README.md": "# ADR\n"}, tool="tools/rejestr_korzeni_tydzien.py", gh=FAKE_GH)
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("GIT_COMMITTER_DATE", DEPLOYED.isoformat())
            self.push_main({szablon_werdyktu.ADR: "# ADR 0031: Korzeń po FAIL i chwasty\n"})
        markdown = {**werdykty_szablonu.rendered(), **chwasty.rendered(), **korzenie_pr.rendered()}
        state = {"repo": opisy_pr.REPO, "pulls": PULLS, "markdown": markdown, "issues": issues}
        (self.bin / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def writes(self) -> list[list[object]]:
        log = self.bin / "writes.jsonl"
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def _measure(github: RegistryGitHub, *arguments: str) -> list[str]:
    answered: subprocess.CompletedProcess[str] = github.run(*arguments)
    assert answered.returncode == 0, answered.stdout + answered.stderr
    return answered.stdout.splitlines()


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pierwszy_pomiar_bez_issue_zaklada_rejestr_korzeni_z_etykieta_chwast_a_kolejny_zmienia_jego_tresc_z_historia(tmp_path: Path) -> None:
    first = RegistryGitHub(tmp_path / "pierwszy", WEEDS)

    created = _measure(first, "--tydzien", "2026-10-14")

    assert first.writes() == [["POST", "repos/{owner}/{repo}/issues", {"title": "Rejestr korzeni", "body": WEEK_12, "labels": ["chwast"]}]]
    assert created == ["REJESTR KORZENI | założone #9100 „Rejestr korzeni”", "REJESTR KORZENI OK | tydzień 2026-10-12: 0 wystąpień, 0 powtórzeń, udział -"]

    issue = {"number": 1600, "title": "Rejestr korzeni", "body": WEEK_12}
    later = RegistryGitHub(tmp_path / "kolejny", [*WEEDS, issue])

    edited = _measure(later, "--tydzien", "2026-10-25")

    assert later.writes() == [["PATCH", "repos/{owner}/{repo}/issues/1600", {"body": WEEK_19}]]
    assert edited == ["REJESTR KORZENI | zmieniona treść #1600", "REJESTR KORZENI OK | tydzień 2026-10-19: 3 wystąpień, 2 powtórzeń, udział 67%"]


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pomiar_z_ta_sama_trescia_niczego_nie_zapisuje_a_bez_zapisu_drukuje_tresc(tmp_path: Path) -> None:
    same = RegistryGitHub(tmp_path / "ta-sama", [*WEEDS, {"number": 1600, "title": "Rejestr korzeni", "body": WEEK_19.replace("\n", "\r\n")}])
    dry = RegistryGitHub(tmp_path / "bez-zapisu", WEEDS)

    unchanged = _measure(same, "--tydzien", "2026-10-19")
    printed = _measure(dry, "--tydzien", "2026-10-19", "--bez-zapisu")

    assert same.writes() == [] and unchanged[0] == "REJESTR KORZENI | #1600 ma już tę treść", unchanged
    assert dry.writes() == []
    assert printed[0] == "REJESTR KORZENI | bez zapisu: załóż issue „Rejestr korzeni” z etykietami chwast", printed
    assert "\n".join(printed[1:-1]) == WEEK_19, printed
