"""``tools/rejestr_korzeni_tydzien.py``: tygodniowy pomiar w treści issue „Rejestr korzeni” (miary ADR 0036, tydzień
i szablon treści z ADR 0031, Q19, Q23) i workflow ``rejestr-korzeni.yml``, który go uruchamia w poniedziałek o 6:00
czasu polskiego.

Wymagania bierzemy z ADR 0036 („Miara”) i decyzji Maksa: powrót idiomu to Ważne z polem ``Idiom:``, ucieczka to pole
``Idiom: <id>`` bez ``jak``, czekanie liczy się od ``PASS`` na HEAD do merge'a, a Ważne ``bez reguły`` trafia do
raportu z odsyłaczem; tydzień to poniedziałek–niedziela czasu taty i Maksa (``Europe/Warsaw``), a issue zmienia się
treścią, bez komentarzy. Testy przepływu biegną na prawdziwym Gicie z ``origin`` i atrapie ``gh``, która podaje PR-y
z zapytania rejestru z HTML treści (``bodyHTML``) złożonym z nagranego HTML renderera GitHuba
(``tests/fixtures/body_html.py``), a renderowania treści nie zna, bo przebieg ma czytać HTML z tej samej strony
GraphQL (W1 r1 #1525: limit ``GITHUB_TOKEN`` workflowu).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from tests.fixtures import chwasty, korzenie_pr, opisy_pr, werdykty_szablonu
from tests.fixtures.body_html import SAMPLES, body_html
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, FakeGitHub
from tests.fixtures.git_repo import git

import rejestr_korzeni
from rejestr_korzeni import IdiomCase, Occurrence, Reviewed
import rejestr_korzeni_tydzien as tydzien
import szablon_werdyktu
import tydzien_polski
import werdykt_pr

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "rejestr-korzeni.yml"
DEPLOYED = datetime(2026, 10, 1, tzinfo=UTC)
NO_ALARMS = tydzien.Alarms(0, {}, 0)


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def _occurrence(pull: int, code: str, when: str, major: str = "W1 r1") -> Occurrence:
    return Occurrence(code, pull, major, _at(when))


def _pull_of(
    number: int,
    occurrences: Sequence[Occurrence] = (),
    idioms: Sequence[IdiomCase] = (),
    merged: str | None = None,
    passed: str | None = None,
    *,
    created: str | None = None,
    files: Sequence[str] = (),
    limited: str | None = None,
) -> Reviewed:
    return Reviewed(
        number,
        _at(merged) if merged else None,
        _at(passed) if passed else None,
        tuple(occurrences),
        tuple(idioms),
        _at(created) if created else None,
        frozenset(files),
        _at(limited) if limited else None,
    )


def _idiom(pull: int, when: str, rule: str | None, klass: str | None, like: tuple[int, str, int] | None, label: str = "W1", round_: int = 2) -> IdiomCase:
    return IdiomCase(pull, round_, szablon_werdyktu.Idiom(label, rule, klass, like), _at(when))


def _body(pulls: Sequence[Reviewed], week: date, alarms: tydzien.Alarms = NO_ALARMS) -> str:
    return tydzien.body(pulls, [], week, DEPLOYED, alarms)


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
    text = _body([_pull_of(1, [_occurrence(1, "R-BEZ-TESTU", when)])], date(2026, 10, 26))

    history = {row.split(" | ")[0].removeprefix("| "): row for row in _rows(text, "Historia")}
    assert [name for name, row in history.items() if row.split(" | ")[1] == "1"] == [week], text


def test_pole_idiom_to_powrot_bez_jak_ucieczka_a_jak_innego_pr_polaczenie_i_bez_reguly_trafia_na_liste() -> None:
    """Pole z ``jak`` tego samego PR to powrót między rundami, nie połączenie między PR-ami; pole z tygodnia przed
    pomiarem liczy się tylko od wdrożenia."""

    pulls = [
        _pull_of(10, [_occurrence(10, "R-BEZ-TESTU", "2026-10-13T10:00:00+00:00")], [_idiom(10, "2026-10-13T10:00:00+00:00", None, "brak-testu", (10, "W1", 1))]),
        _pull_of(11, [_occurrence(11, "R-BEZ-TESTU", "2026-10-14T10:00:00+00:00")], [_idiom(11, "2026-10-14T10:00:00+00:00", "x-regula", None, (10, "W1", 1), "W2", 1)]),
        _pull_of(12, [_occurrence(12, "R-DRUGA-DROGA", "2026-10-15T10:00:00+00:00")], [_idiom(12, "2026-10-15T10:00:00+00:00", "x-regula", None, None)]),
        _pull_of(13, [_occurrence(13, "R-DRUGA-DROGA", "2026-10-15T10:00:00+00:00")]),
        _pull_of(9, [_occurrence(9, "R-BEZ-TESTU", "2026-10-06T10:00:00+00:00")], [_idiom(9, "2026-10-06T10:00:00+00:00", None, "typ", (8, "W1", 3))]),
    ]

    text = _body(pulls, date(2026, 10, 12))

    assert _rows(text, "Pomiar") == ["| Tydzień 2026-10-12 | 4 | 3 | 75% | 1 | 1 |", "| Od wdrożenia 2026-10-01 | 5 | 4 | 80% | 1 | 2 |"], text
    assert _rows(text, "Bez reguły") == ["| #10 W1 r2 | brak-testu | #10 W1 r1 |"], text
    assert _rows(text, "Historia")[-2:] == ["| 2026-10-05 | 1 | 1 | 100% | 0 | 1 |", "| 2026-10-12 | 4 | 3 | 75% | 1 | 1 |"], text


def test_tydzien_bez_wystapien_ma_zero_i_udzial_bez_wartosci() -> None:
    text = _body([_pull_of(1, [_occurrence(1, "R-BEZ-TESTU", "2026-10-06T10:00:00+00:00")])], date(2026, 10, 12))

    assert _rows(text, "Pomiar") == ["| Tydzień 2026-10-12 | 0 | 0 | - | 0 | 0 |", "| Od wdrożenia 2026-10-01 | 1 | 0 | 0% | 0 | 0 |"], text
    assert _rows(text, "Kody") == ["| R-BEZ-TESTU | 0 | 1 |"], text
    assert _rows(text, "Historia")[-1] == "| 2026-10-12 | 0 | 0 | - | 0 | 0 |", text


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


def test_historia_ma_najwyzej_26_ostatnich_tygodni_od_tygodnia_wdrozenia() -> None:
    text = _body([], date(2027, 6, 7))

    weeks = [row.split(" | ")[0].removeprefix("| ") for row in _rows(text, "Historia")]
    assert (len(weeks), weeks[0], weeks[-1]) == (26, "2026-12-14", "2027-06-07"), weeks
    assert [row.split(" | ")[0].removeprefix("| ") for row in _rows(_body([], date(2026, 10, 5)), "Historia")] == ["2026-09-28", "2026-10-05"]


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

| Okres | Wystąpienia | Powroty idiomu | Udział powrotów | Ucieczki | Połączenia między PR-ami |
| --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-12 | 0 | 0 | - | 0 | 0 |
| Od wdrożenia 2026-10-01 | 1 | 0 | 0% | 0 | 0 |

## Czekanie

| Okres | Merge'e | Bez PASS na HEAD | Mediana PASS → merge | Najdłużej | Ponad 1 h |
| --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-12 | 0 | 0 | - | - | 0 |
| Od wdrożenia 2026-10-01 | 0 | 0 | - | - | 0 |

## Reguły

| Reguła | PR-y z odpaleniem z 0 ostatnich |
| --- | --- |
| Każda reguła | 0 |

## Bez reguły

| Ważne | Klasa | Jak |
| --- | --- | --- |

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

| Tydzień | Wystąpienia | Powroty idiomu | Udział powrotów | Ucieczki | Połączenia między PR-ami |
| --- | --- | --- | --- | --- | --- |
| 2026-09-28 | 0 | 0 | - | 0 | 0 |
| 2026-10-05 | 1 | 0 | 0% | 0 | 0 |
| 2026-10-12 | 0 | 0 | - | 0 | 0 |
"""
WEEK_19 = """\
## Pomiar

| Okres | Wystąpienia | Powroty idiomu | Udział powrotów | Ucieczki | Połączenia między PR-ami |
| --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-19 | 3 | 0 | 0% | 0 | 0 |
| Od wdrożenia 2026-10-01 | 4 | 0 | 0% | 0 | 0 |

## Czekanie

| Okres | Merge'e | Bez PASS na HEAD | Mediana PASS → merge | Najdłużej | Ponad 1 h |
| --- | --- | --- | --- | --- | --- |
| Tydzień 2026-10-19 | 2 | 2 | - | - | 0 |
| Od wdrożenia 2026-10-01 | 2 | 2 | - | - | 0 |

## Reguły

| Reguła | PR-y z odpaleniem z 0 ostatnich |
| --- | --- |
| Każda reguła | 0 |

## Bez reguły

| Ważne | Klasa | Jak |
| --- | --- | --- |

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

| Tydzień | Wystąpienia | Powroty idiomu | Udział powrotów | Ucieczki | Połączenia między PR-ami |
| --- | --- | --- | --- | --- | --- |
| 2026-09-28 | 0 | 0 | - | 0 | 0 |
| 2026-10-05 | 1 | 0 | 0% | 0 | 0 |
| 2026-10-12 | 0 | 0 | - | 0 | 0 |
| 2026-10-19 | 3 | 0 | 0% | 0 | 0 |
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
    ) -> None:
        tmp_path.mkdir()
        super().__init__(tmp_path, {"docs/adr/README.md": "# ADR\n", **(files or {})}, tool="tools/rejestr_korzeni_tydzien.py", gh=FAKE_GH, started=started)
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("GIT_COMMITTER_DATE", DEPLOYED.isoformat())
            self.push_main({szablon_werdyktu.ADR: "# ADR 0031: Korzeń po FAIL i chwasty\n"})
        state = {"repo": opisy_pr.REPO, "pulls": pulls, "weeds": WEEDS, "own": own, "labels": list(labels)}
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
        "REJESTR KORZENI OK | tydzień 2026-10-12: 0 wystąpień, 0 powrotów idiomu (udział -), 0 ucieczek, 0 połączeń między PR-ami",
    ]

    labelled = RegistryGitHub(tmp_path / "z-etykieta", [], labels=("chwast", "rejestr-korzeni"))
    _measure(labelled, "--tydzien", "2026-10-14")
    assert [write[1] for write in labelled.writes()] == ["repos/{owner}/{repo}/issues"]

    later = RegistryGitHub(tmp_path / "kolejny", [{"number": 1600, "title": "Rejestr korzeni", "body": WEEK_12}])

    edited = _measure(later, "--tydzien", "2026-10-25")

    assert later.writes() == [["PATCH", "repos/{owner}/{repo}/issues/1600", {"body": WEEK_19}]]
    assert edited == ["REJESTR KORZENI | zmieniona treść #1600", "REJESTR KORZENI OK | tydzień 2026-10-19: 3 wystąpień, 0 powrotów idiomu (udział 0%), 0 ucieczek, 0 połączeń między PR-ami"]


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

    assert lines[-1].startswith(f"REJESTR KORZENI OK | tydzień 2026-10-19: {count} wystąpień, 0 powrotów idiomu"), lines
    issues = "repos/{owner}/{repo}/issues?labels={label}&state=open&per_page=100&page=1"
    rest = [issues.format(owner="{owner}", repo="{repo}", label=label) for label in ("chwast", "rejestr-korzeni")]
    assert github.calls() == ["repo view", *["graphql"] * pages, *rest, "repos/{owner}/{repo}/labels?per_page=100&page=1"]


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
FAIL_IDIOM = "WERDYKT: FAIL {commit}\nZnaleziska: 1 (Ważne 1, Drobne 0)\n" + werdykty_szablonu.WERDYKTY["wazne-idiom-bez-reguly"]


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pole_idiom_i_pass_na_head_z_werdyktow_skanu_daja_powrot_polaczenie_liste_bez_reguly_i_czekanie(tmp_path: Path) -> None:
    """``PASS`` na innym commicie niż HEAD PR nie jest jego zgodą na merge, więc merge liczy się jako bez ``PASS``."""

    other = "1" * 40
    pulls = [
        _pull(1450, [(FAIL_IDIOM, "2026-10-20T10:00:00Z"), (PASS, "2026-10-20T11:00:00Z")], merged="2026-10-20T11:30:00Z"),
        _pull(1451, [(PASS.replace("{commit}", other), "2026-10-20T11:00:00Z")], merged="2026-10-20T11:30:00Z"),
    ]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls)

    text = "\n".join(_measure(github, "--tydzien", "2026-10-19", "--bez-zapisu")[2:-1])

    assert _rows(text, "Pomiar")[0] == "| Tydzień 2026-10-19 | 1 | 1 | 100% | 0 | 1 |", text
    assert _rows(text, "Czekanie")[0] == "| Tydzień 2026-10-19 | 2 | 1 | 30 min | 30 min | 0 |", text
    assert _rows(text, "Bez reguły") == ["| #1450 W1 r1 | brak-testu | #1553 W1 r2 |"], text


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pr_scalony_przed_wdrozeniem_i_zmieniony_po_nim_nie_liczy_sie_od_wdrozenia(tmp_path: Path) -> None:
    """Skan bierze każdy PR zmieniony po wdrożeniu, więc stary scalony PR z późniejszym komentarzem w nim jest, a jego
    merge i blok czerwonego `main` są sprzed wdrożenia."""

    pulls = [_pull(1460, [], body=korzenie_pr.OPISY["czerwony-main"], merged="2026-09-20T10:00:00Z", created="2026-09-19T00:00:00Z")]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls)

    text = "\n".join(_measure(github, "--tydzien", "2026-10-12", "--bez-zapisu")[2:-1])

    assert _rows(text, "Pomiar")[1] == "| Od wdrożenia 2026-10-01 | 0 | 0 | - | 0 | 0 |", text
    assert _rows(text, "Czekanie")[1] == "| Od wdrożenia 2026-10-01 | 0 | 0 | - | - | 0 |", text


@ONLY_FOUND_BY_NAME_ON_POSIX
def test_pr_zamkniety_bez_merge_po_trzech_rundach_z_fail_daje_nowy_pr_na_jego_plikach_w_raporcie(tmp_path: Path) -> None:
    """Skan rozpoznaje PR zamknięty po limicie rund z jego werdyktów: trzy rundy z FAIL i zamknięcie bez merge'a; PR
    zamknięty po dwóch rundach i PR otwarty po trzech nie są zamknięte po limicie."""

    fails = [(FAIL_W1.replace("{commit}", sha * 40), f"2026-10-13T1{index}:00:00Z") for index, sha in enumerate("123")]
    pulls = [
        _pull(1470, fails, closed=True, created="2026-10-05T00:00:00Z", files=["kod/limit.py", "kod/test_limitu.py"]),
        _pull(1471, fails[:2], closed=True, created="2026-10-05T00:01:00Z", files=["kod/dwie.py"]),
        _pull(1472, fails, created="2026-10-05T00:02:00Z", files=["kod/otwarty.py"]),
        _pull(1473, [], created="2026-10-14T00:00:00Z", files=["kod/limit.py", "kod/dwie.py", "kod/otwarty.py"]),
    ]
    github = RegistryGitHub(tmp_path / "gh", [], pulls=pulls, started=DEPLOYED.isoformat())

    text = "\n".join(_measure(github, "--tydzien", "2026-10-12", "--bez-zapisu")[2:-1])

    assert _rows(text, "Po limicie rund") == ["| #1473 | #1470 | 1 |"], text


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
