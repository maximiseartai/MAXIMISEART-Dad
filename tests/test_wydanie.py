"""``tools/wydanie.py``: plan Wydania z zielonego `main` i publikacja tylko po potwierdzeniu Maksa.

Testy biegną na prawdziwym Gicie: repozytorium bare jako ``origin`` i checkout Maksa, w którym PR-y wchodzą do
`main` merge'em jak na GitHubie. Atrapa ``gh`` odpowiada jak API GitHuba: ``Required CI status`` commitów, sprawy
w Skrzynce Zgłoszeń i Releases, i zapisuje utworzone Releases.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from rozliczenia.centrum import release_notes, tool_update
from rozliczenia.centrum.release_notes import DadCase, ReleaseNotes
from tests.fixtures.fake_cli import ONLY_FOUND_BY_NAME_ON_POSIX, fake_cli
from tests.fixtures.git_repo import AUTHOR, commit, git

pytestmark = ONLY_FOUND_BY_NAME_ON_POSIX

TOOL = Path(__file__).resolve().parents[1] / "tools" / "wydanie.py"
SUMMARY = "Przygotowanie pliku zbiorczego samo wpisuje ilości usług. Centrum pokazuje, co nowego."
SECRET = "TREŚĆ-SPRAWY-TATY"
# Chwila każdego commitu w testach; sprawy taty zamyka się przed nią albo po niej.
COMMITTED = "2026-10-10T10:00:00+00:00"
QUARANTINE_FILE = "tests/fixtures/kwarantanna.py"
EMPTY = "KWARANTANNA: dict[str, Kwarantanna] = {}\n"
QUARANTINED = 'KWARANTANNA: dict[str, Kwarantanna] = {"tests/test_x.py::test_niestabilny": Kwarantanna(1, date(2026, 10, 30))}\n'
FAKE_GH = """\
import io, json, pathlib, sys, urllib.parse, zipfile

state_file = pathlib.Path(sys.argv[0]).with_name("github.json")
state = json.loads(state_file.read_text(encoding="utf-8"))
arguments = sys.argv[1:]
method, path = arguments[2], arguments[3]
address = urllib.parse.urlsplit(path)
query = dict(urllib.parse.parse_qsl(address.query))
repository, parts = "/".join(address.path.split("/")[1:3]), address.path.split("/")[3:]


def answer(value):
    print(json.dumps(value))
    sys.exit(0)


if arguments[:2] != ["api", "--method"]:
    sys.exit(f"atrapa gh nie zna: {arguments}")
if method == "GET" and parts[0] == "commits" and parts[2] == "check-runs" and query["check_name"] == "Required CI status":
    runs = state["checks"].get(parts[1], [])
    answer({"total_count": len(runs), "check_runs": runs})
if method == "GET" and parts[:2] == ["actions", "runs"] and parts[3:] == ["artifacts"]:
    listed = state["artifacts"].get(parts[2], [])
    answer({"total_count": len(listed), "artifacts": [{key: value for key, value in found.items() if key != "record"} for found in listed]})
if method == "GET" and parts[:2] == ["actions", "artifacts"] and parts[3:] == ["zip"]:
    [found] = [found for listed in state["artifacts"].values() for found in listed if str(found["id"]) == parts[2]]
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w") as archive:
        archive.writestr("kwarantanna.json", json.dumps(found["record"]))
    sys.stdout.buffer.write(packed.getvalue())
    sys.exit(0)
if method == "GET" and parts[:2] == ["releases", "tags"]:
    found = state["releases"].get(parts[2])
    if found is None:
        print('{"message":"Not Found","status":"404"}')
        sys.exit("gh: Not Found (HTTP 404)")
    answer(found)
if method == "POST" and parts == ["releases"]:
    if state.pop("fail_next_post", False):
        state_file.write_text(json.dumps(state), encoding="utf-8")
        sys.exit("gh: Server Error (HTTP 502)")
    body = json.load(sys.stdin)
    created = {**body, "html_url": f"https://github.com/{repository}/releases/tag/{body['tag_name']}", "published_at": state["now"]}
    state["releases"][body["tag_name"]] = created
    state["posted"].append(created)
    state_file.write_text(json.dumps(state), encoding="utf-8")
    answer(created)
if method == "GET" and repository == "MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia" and parts == ["issues"]:
    if state.get("no_report_box"):
        print('{"message":"Not Found","status":"404"}')
        sys.exit("gh: Not Found (HTTP 404)")
    since = query.get("since", "")
    listed = [
        issue
        for issue in state["issues"]
        if issue["state"] == query["state"]
        and query["labels"] in [label["name"] for label in issue["labels"]]
        and issue["updated_at"] >= since
    ]
    size, page = int(query["per_page"]), int(query["page"])
    answer(listed[(page - 1) * size : page * size])
sys.exit(f"atrapa gh nie zna: {arguments}")
"""


class Releasing:
    """Checkout Maksa z ``origin``, atrapa GitHuba i narzędzie Wydań uruchamiane jak przez agenta."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.origin = tmp_path / "origin.git"
        git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(self.origin))
        self.checkout = tmp_path / "checkout"
        self.checkout.mkdir()
        git(self.checkout, "init", "--quiet", "--initial-branch=main")
        git(self.checkout, "remote", "add", "origin", str(self.origin))
        (self.checkout / "README.md").write_text("narzędzie\n", encoding="utf-8")
        self.start = commit(self.checkout, "początek")
        self.bin = tmp_path / "bin"
        fake_cli(self.bin, "gh", FAKE_GH)
        self.state: dict[str, Any] = {"checks": {}, "artifacts": {}, "releases": {}, "issues": [], "posted": [], "now": "2026-10-23T12:00:00Z"}
        self._save()
        self.plan_file = tmp_path / "notatki" / "plan.json"
        self.summary_file = tmp_path / "co-nowego.txt"
        self.summary_file.write_text(SUMMARY + "\n", encoding="utf-8")
        self._branches = 0

    def merge(self, number: int, title: str, files: dict[str, str], *, ci: str = "success") -> str:
        """PR ``number`` scalony do `main` merge'em; ``ci`` to wynik ``Required CI status`` commitu merge'a na `main`."""

        self._branches += 1
        branch = f"zmiana-{self._branches}"
        git(self.checkout, "switch", "--quiet", "--create", branch)
        for name, text in files.items():
            (self.checkout / name).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / name).write_text(text, encoding="utf-8")
        head = commit(self.checkout, title)
        self.ci(head, "success")
        git(self.checkout, "switch", "--quiet", "main")
        git(self.checkout, "merge", "--no-ff", "--quiet", "-m", f"Merge pull request #{number} from MAXIMISEART-AI/{branch}", "-m", title, branch)
        merged = git(self.checkout, "rev-parse", "HEAD")
        self.ci(merged, ci)
        git(self.checkout, "push", "--quiet", "origin", "main")
        return merged

    def squash(self, number: int, title: str, files: dict[str, str]) -> str:
        """PR ``number`` scalony do `main` squashem, z zielonym CI."""

        for name, text in files.items():
            (self.checkout / name).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / name).write_text(text, encoding="utf-8")
        squashed = commit(self.checkout, f"{title} (#{number})")
        self.ci(squashed, "success")
        git(self.checkout, "push", "--quiet", "origin", "main")
        return squashed

    def github(self, flag: str) -> None:
        """Atrapa GitHuba: ``fail_next_post`` (następne utworzenie Release pada) albo ``no_report_box`` (brak dostępu)."""

        self._edit(lambda state: state.__setitem__(flag, True))

    def ci(self, commit: str, conclusion: str, quarantine: str = "przeszedł") -> None:
        """``conclusion``: wynik zakończonego ``Required CI status``, ``in_progress`` albo ``brak`` (CI się nie zaczęło).

        Run commitu ma zapis kwarantanny z jednym testem w kwarantannie i jego wynikiem ``quarantine`` (``przeszedł``
        albo ``padł``) w jednym zadaniu i pusty zapis drugiego zadania; ``brak`` to run bez artefaktów kwarantanny.
        """

        run = str(int(commit[:8], 16))
        url = f"https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad/actions/runs/{run}/job/1"
        runs = {
            "brak": [],
            "in_progress": [{"name": "Required CI status", "status": "in_progress", "conclusion": None, "details_url": url}],
        }.get(conclusion, [{"name": "Required CI status", "status": "completed", "conclusion": conclusion, "details_url": url}])
        test = "tests/test_x.py::test_niestabilny"
        records = [
            {"zadanie": job, "proba": 1, "sha": commit, "wyniki": results}
            for job, results in (("windows-3.14-1", {test: quarantine}), ("linux-3.14-1", {}))
        ]
        artifacts = [] if quarantine == "brak" else [
            {"id": int(run) * 10 + index, "name": f"kwarantanna-{record['zadanie']}-1", "expired": False, "record": record}
            for index, record in enumerate(records)
        ]
        # Wygasły zapis kwarantanny z porażką: GitHub już go nie oddaje, więc się nie liczy.
        expired = {"zadanie": "linux-3.14-2", "proba": 1, "sha": commit, "wyniki": {test: "padł"}}
        artifacts += [
            {"id": int(run) * 10 + 8, "name": "kwarantanna-linux-3.14-2-1", "expired": True, "record": expired},
            {"id": int(run) * 10 + 9, "name": "czasy-ci", "expired": False, "record": {}},
        ]

        def change(state: dict[str, Any]) -> None:
            state["checks"][commit] = runs
            state["artifacts"][run] = artifacts

        self._edit(change)

    def released(self, tag: str, commit: str, cases: tuple[DadCase, ...] = (), *, release: bool = True) -> None:
        """Wcześniejsze Wydanie: tag z opisem w ``origin`` i, gdy ``release``, jego Release z notką wymieniającą ``cases``."""

        git(self.checkout, "tag", "--annotate", "--message", tag, tag, commit)
        git(self.checkout, "push", "--quiet", "origin", f"refs/tags/{tag}")
        if not release:
            return
        body = release_notes.render(ReleaseNotes("Wcześniej.", cases))
        self._edit(lambda state: state["releases"].__setitem__(tag, {"tag_name": tag, "body": body, "html_url": ""}))

    def case(self, number: int, label: str, closed_at: str, *, reason: str = "completed", updated_at: str = "") -> None:
        """Sprawa taty w Skrzynce Zgłoszeń zamknięta ``closed_at`` z powodem ``reason``; jej treść to ``SECRET``."""

        issue = {
            "number": number,
            "title": f"Sprawa {number}",
            "body": f"{SECRET} {number}",
            "labels": [{"name": label}],
            "state": "closed",
            "state_reason": reason,
            "closed_at": closed_at,
            "updated_at": updated_at or closed_at,
        }
        self._edit(lambda state: state["issues"].append(issue))

    def plan(self) -> subprocess.CompletedProcess[str]:
        return self._tool("plan", "--plik", str(self.plan_file))

    def publish(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return self._tool("wydaj", "--plan", str(self.plan_file), "--co-nowego", str(self.summary_file), *extra)

    def publish_without_summary(self) -> subprocess.CompletedProcess[str]:
        """``wydaj`` z planem i potwierdzeniem Maksa, ale bez pliku „Co nowego”."""

        return self._tool("wydaj", "--plan", str(self.plan_file), "--potwierdzone-przez-maksa")

    def planned(self) -> dict[str, Any]:
        result = self.plan()
        assert result.returncode == 0, result.stdout + result.stderr
        planned: dict[str, Any] = json.loads(self.plan_file.read_text(encoding="utf-8"))
        return planned

    def remote_tags(self) -> dict[str, str]:
        listed = git(self.checkout, "ls-remote", "--tags", "--refs", "origin")
        return {ref.removeprefix("refs/tags/"): sha for sha, ref in (line.split() for line in listed.splitlines())}

    def posted(self) -> list[dict[str, str]]:
        posted: list[dict[str, str]] = self._load()["posted"]
        return posted

    def _tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, **AUTHOR, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        environment.pop("MAXIMISEART_WYDANIE", None)
        return subprocess.run(
            [sys.executable, str(TOOL), "--repozytorium", str(self.checkout), *arguments],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )

    def _load(self) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads((self.bin / "github.json").read_text(encoding="utf-8"))
        return loaded

    def _edit(self, change: Callable[[dict[str, Any]], object]) -> None:
        self.state = self._load()
        change(self.state)
        self._save()

    def _save(self) -> None:
        (self.bin / "github.json").write_text(json.dumps(self.state), encoding="utf-8")


@pytest.fixture
def releasing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Releasing:
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_DATE", COMMITTED)
    return Releasing(tmp_path)


def test_plan_bierze_najnowszy_commit_main_z_zielonym_ci_i_pomija_czerwone_i_niezakonczone(releasing: Releasing) -> None:
    green = releasing.merge(1, "fix: pierwsza naprawa", {"src/a.py": "a = 1\n"})
    red = releasing.merge(2, "fix: druga", {"src/b.py": "b = 1\n"}, ci="failure")
    running = releasing.merge(3, "fix: trzecia", {"src/c.py": "c = 1\n"}, ci="in_progress")
    without = releasing.merge(4, "fix: czwarta", {"src/d.py": "d = 1\n"}, ci="brak")

    planned = releasing.planned()

    assert planned["commit"] == green
    assert planned["skipped"] == [
        {"commit": without, "ci": "brak"},
        {"commit": running, "ci": "w toku"},
        {"commit": red, "ci": "czerwone"},
    ]


@pytest.mark.parametrize(("quarantine", "state"), [("padł", "kwarantanna czerwona"), ("brak", "bez zapisu kwarantanny")])
def test_plan_pomija_zielony_commit_na_ktorym_test_z_kwarantanny_padl_albo_nie_ma_zapisu(releasing: Releasing, quarantine: str, state: str) -> None:
    passed = releasing.merge(1, "fix: pierwsza naprawa", {"src/a.py": "a = 1\n"})
    skipped = releasing.merge(2, "fix: druga", {"src/b.py": "b = 1\n", QUARANTINE_FILE: QUARANTINED})
    releasing.ci(skipped, "success", quarantine)

    planned = releasing.planned()

    assert planned["commit"] == passed
    assert planned["skipped"] == [{"commit": skipped, "ci": state}]


@pytest.mark.parametrize(
    "files",
    [{}, {QUARANTINE_FILE: EMPTY}],
    ids=["sprzed kwarantanny", "pusta kwarantanna"],
)
def test_commit_bez_wpisow_kwarantanny_jest_do_wydania_bez_jej_zapisu(releasing: Releasing, files: dict[str, str]) -> None:
    merged = releasing.merge(1, "fix: naprawa", {"src/a.py": "a = 1\n", **files})
    releasing.ci(merged, "success", "brak")

    assert releasing.planned()["commit"] == merged


@pytest.mark.parametrize(
    "source",
    [
        "KWARANTANNA: dict[str, Kwarantanna] = dict(WPISY)\n",
        "KWARANTANNA = {\n",
        "WPISY = {}\n",
        EMPTY + 'KWARANTANNA["tests/test_x.py::test_niestabilny"] = Kwarantanna(1, date(2026, 10, 30))\n',
        EMPTY + "KWARANTANNA.update(WPISY)\n",
        EMPTY + "KWARANTANNA |= WPISY\n",
        EMPTY + 'KWARANTANNA = {"tests/test_x.py::test_niestabilny": Kwarantanna(1, date(2026, 10, 30))}\n',
        EMPTY + "KWARANTANNA: dict[str, Kwarantanna] = dict(WPISY)\n",
        EMPTY + 'globals()["KWARANTANNA"].update(WPISY)\n',
    ],
    ids=[
        "nie dosłowny słownik",
        "błąd składni",
        "bez słownika",
        "dopisany klucz",
        "update",
        "|=",
        "drugie przypisanie",
        "drugie przypisanie z adnotacją",
        "przez globals()",
    ],
)
def test_kwarantanna_inna_niz_jedno_puste_przypisanie_wymaga_zapisu(releasing: Releasing, source: str) -> None:
    passed = releasing.merge(1, "fix: pierwsza naprawa", {"src/a.py": "a = 1\n"})
    skipped = releasing.merge(2, "fix: druga", {QUARANTINE_FILE: source})
    releasing.ci(skipped, "success", "brak")

    planned = releasing.planned()

    assert planned["commit"] == passed
    assert planned["skipped"] == [{"commit": skipped, "ci": "bez zapisu kwarantanny"}]


def test_wydanie_odmawia_gdy_test_z_kwarantanny_padl_w_ponowionym_runie_commitu(releasing: Releasing) -> None:
    merged = releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n", QUARANTINE_FILE: QUARANTINED})
    releasing.planned()
    releasing.ci(merged, "success", "padł")

    result = releasing.publish("--potwierdzone-przez-maksa")

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1] == f"WYDANIE ODMOWA | CI commitu {merged} nie jest już zielone (kwarantanna czerwona)."
    assert releasing.remote_tags() == {}


def test_bez_potwierdzenia_maksa_nie_powstaje_tag_ani_release(releasing: Releasing) -> None:
    releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.planned()

    result = releasing.publish()

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1].startswith("WYDANIE PODGLĄD | v0.1.0 | nic nie utworzono")
    assert SUMMARY in result.stdout
    assert releasing.remote_tags() == {}
    assert git(releasing.checkout, "tag", "--list") == ""
    assert releasing.posted() == []


def test_wydanie_bez_pliku_co_nowego_konczy_sie_bledem_uzycia_z_nazwa_opcji_i_nic_nie_tworzy(releasing: Releasing) -> None:
    releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.planned()

    result = releasing.publish_without_summary()

    assert result.returncode == 2, result.stdout + result.stderr
    assert result.stderr.splitlines()[-1].endswith("the following arguments are required: --co-nowego")
    assert releasing.remote_tags() == {}
    assert releasing.posted() == []


def test_wydanie_po_potwierdzeniu_to_tag_na_main_i_release_z_notka_ktora_odczyta_centrum(releasing: Releasing) -> None:
    merged = releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.case(5, "uwaga-taty", "2026-10-22T10:00:00Z")
    releasing.case(3, "zgloszenie", "2026-10-21T10:00:00Z")
    releasing.planned()

    result = releasing.publish("--potwierdzone-przez-maksa")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines()[-1].startswith(f"WYDANIE OK | v0.1.0 | {merged} | https://github.com/")
    assert git(releasing.checkout, "cat-file", "-t", "refs/tags/v0.1.0") == "tag"
    assert git(releasing.checkout, "rev-parse", "refs/tags/v0.1.0^{commit}") == merged
    [posted] = releasing.posted()
    assert posted["tag_name"] == "v0.1.0"
    assert release_notes.parse(posted["body"]) == ReleaseNotes(
        SUMMARY, (DadCase(3, "Sprawa 3", "zgloszenie"), DadCase(5, "Sprawa 5", "uwaga-taty"))
    )
    dad = releasing.tmp_path / "tata"
    git(releasing.tmp_path, "clone", "--quiet", str(releasing.origin), str(dad))
    assert tool_update.fetch_main_line(dad, str(releasing.origin)).newest().commit == merged


def test_ponowione_wydanie_konczy_to_samo_bez_drugiego_release(releasing: Releasing) -> None:
    releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.planned()
    assert releasing.publish("--potwierdzone-przez-maksa").returncode == 0

    again = releasing.publish("--potwierdzone-przez-maksa")

    assert again.returncode == 0, again.stdout + again.stderr
    assert again.stdout.splitlines()[-1].startswith("WYDANIE OK | v0.1.0 | ")
    assert len(releasing.posted()) == 1


def test_wydanie_odmawia_gdy_ci_commitu_przestalo_byc_zielone(releasing: Releasing) -> None:
    merged = releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.planned()
    releasing.ci(merged, "failure")

    result = releasing.publish("--potwierdzone-przez-maksa")

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith("WYDANIE ODMOWA | ")
    assert releasing.remote_tags() == {}
    assert releasing.posted() == []


@pytest.mark.parametrize(
    ("previous", "title", "files", "proposed"),
    [
        ("v0.1.0", "fix(przebieg): naprawa", {"src/a.py": "a = 2\n"}, "v0.1.1"),
        ("v0.1.0", "feat(centrum): nowa rzecz dla taty", {"src/a.py": "a = 2\n"}, "v0.2.0"),
        ("v0.1.0", "feat(narzedzia): nowe narzędzie Maksa", {"tools/x.py": "x = 1\n"}, "v0.1.1"),
        ("v0.9.4", "feat: nowa rzecz", {"src/a.py": "a = 2\n"}, "v0.10.0"),
        ("v0.10.0", "Naprawa bez typu", {"src/a.py": "a = 2\n"}, "v0.10.1"),
    ],
)
def test_numer_wydania_podbija_minor_za_nowa_rzecz_u_taty_a_patch_za_reszte(
    releasing: Releasing, previous: str, title: str, files: dict[str, str], proposed: str
) -> None:
    released = releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.released("v0.9.9-rc1", released)
    releasing.released(previous, released)
    releasing.merge(2, title, files)

    planned = releasing.planned()

    assert planned["proposed"]["tag"] == proposed
    assert [change["number"] for change in planned["changes"]] == [2]


def test_pr_scalony_squashem_jest_zmiana_wydania(releasing: Releasing) -> None:
    released = releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.released("v0.1.0", released)
    releasing.squash(7, "feat(centrum): nowa rzecz", {"src/a.py": "a = 2\n"})

    planned = releasing.planned()

    assert planned["changes"] == [{"number": 7, "title": "feat(centrum): nowa rzecz", "for_dad": True}]
    assert planned["proposed"]["tag"] == "v0.2.0"


def test_numer_jest_wyzszy_od_wydania_spoza_main_ktore_centrum_pomija(releasing: Releasing) -> None:
    releasing.merge(1, "fix: naprawa", {"src/a.py": "a = 1\n"})
    git(releasing.checkout, "switch", "--quiet", "--create", "agent")
    (releasing.checkout / "README.md").write_text("gałąź agenta\n", encoding="utf-8")
    side = commit(releasing.checkout, "commit agenta")
    releasing.released("v0.7.0", side)
    git(releasing.checkout, "switch", "--quiet", "main")

    planned = releasing.planned()

    assert planned["previous"] is None
    assert planned["off_main"] == ["v0.7.0"]
    assert planned["proposed"]["tag"] == "v0.8.0"


def test_poprzednie_wydanie_bez_release_to_tag_i_sprawy_od_jego_commitu(releasing: Releasing) -> None:
    released = releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.released("v0.1.0", released, release=False)
    releasing.merge(2, "fix: naprawa", {"src/a.py": "a = 2\n"})
    releasing.case(1, "zgloszenie", "2026-10-09T10:00:00Z")
    releasing.case(2, "uwaga-taty", "2026-10-11T10:00:00Z")

    planned = releasing.planned()

    assert planned["previous"]["release"]["tag"] == "v0.1.0"
    assert planned["proposed"]["tag"] == "v0.1.1"
    assert planned["dad_cases"] == [{"number": 2, "title": "Sprawa 2", "label": "uwaga-taty"}]


def test_plan_odmawia_gdy_od_poprzedniego_wydania_nic_nie_ma_zielonego_ci(releasing: Releasing) -> None:
    released = releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.released("v0.1.0", released)
    releasing.merge(2, "fix: naprawa", {"src/a.py": "a = 2\n"}, ci="failure")

    result = releasing.plan()

    assert result.returncode == 1
    assert result.stdout.splitlines()[-1].startswith("WYDANIE ODMOWA | Nic do wydania")
    assert not releasing.plan_file.exists()


def test_plan_odmawia_bez_dostepu_do_skrzynki_zgloszen(releasing: Releasing) -> None:
    releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.github("no_report_box")

    result = releasing.plan()

    assert result.returncode == 1
    assert "404" in result.stdout.splitlines()[-1]


@pytest.mark.parametrize(
    ("number", "refusal"),
    [
        ("0.2.0", "nie jest wyższy"),
        ("v0.1.9", "nie jest wyższy"),
        ("1.0.0", "nie ma kształtu"),
        ("0.3", "nie ma kształtu"),
    ],
)
def test_numer_podany_przez_maksa_musi_byc_wyzszy_i_miec_ksztalt_0_minor_patch(
    releasing: Releasing, number: str, refusal: str
) -> None:
    released = releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.released("v0.2.0", released)
    releasing.merge(2, "fix: naprawa", {"src/a.py": "a = 2\n"})
    releasing.planned()

    result = releasing.publish("--numer", number, "--potwierdzone-przez-maksa")

    assert result.returncode == 1
    assert refusal in result.stdout.splitlines()[-1]
    assert set(releasing.remote_tags()) == {"v0.2.0"}


def test_numer_podany_przez_maksa_wyzszy_od_poprzedniego_jest_wydany(releasing: Releasing) -> None:
    released = releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.released("v0.2.0", released)
    merged = releasing.merge(2, "fix: naprawa", {"src/a.py": "a = 2\n"})
    releasing.planned()

    result = releasing.publish("--numer", "0.5.0", "--potwierdzone-przez-maksa")

    assert result.returncode == 0, result.stdout + result.stderr
    assert releasing.remote_tags().keys() == {"v0.2.0", "v0.5.0"}
    assert git(releasing.checkout, "rev-parse", "refs/tags/v0.5.0^{commit}") == merged


def test_wydanie_odmawia_commitu_spoza_linii_main(releasing: Releasing) -> None:
    merged = releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    planned = releasing.planned()
    branch_head = git(releasing.checkout, "rev-parse", f"{merged}^2")
    releasing.plan_file.write_text(json.dumps({**planned, "commit": branch_head}), encoding="utf-8")

    result = releasing.publish("--potwierdzone-przez-maksa")

    assert result.returncode == 1
    assert "nie leży na linii pierwszych rodziców main" in result.stdout.splitlines()[-1]
    assert releasing.remote_tags() == {}
    assert releasing.posted() == []


def test_wydanie_odmawia_gdy_tag_jest_juz_na_innym_commicie(releasing: Releasing) -> None:
    releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.planned()
    git(releasing.checkout, "switch", "--quiet", "--create", "agent")
    (releasing.checkout / "README.md").write_text("gałąź agenta\n", encoding="utf-8")
    side = commit(releasing.checkout, "commit agenta")
    git(releasing.checkout, "push", "--quiet", "origin", f"{side}:refs/tags/v0.1.0")
    git(releasing.checkout, "switch", "--quiet", "main")

    result = releasing.publish("--potwierdzone-przez-maksa")

    assert result.returncode == 1
    assert "na innym commicie" in result.stdout.splitlines()[-1]
    assert releasing.posted() == []


def test_wydanie_odmawia_commitu_starszego_niz_najnowsze_wydanie(releasing: Releasing) -> None:
    releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.planned()
    newer = releasing.merge(2, "fix: naprawa", {"src/a.py": "a = 2\n"})
    releasing.released("v0.5.0", newer)

    result = releasing.publish("--numer", "0.6.0", "--potwierdzone-przez-maksa")

    assert result.returncode == 1
    assert "nie jest nowszy od commitu Wydania v0.5.0" in result.stdout.splitlines()[-1]
    assert set(releasing.remote_tags()) == {"v0.5.0"}


def test_wydanie_odmawia_gdy_lokalny_tag_wskazuje_inny_commit(releasing: Releasing) -> None:
    releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.planned()
    git(releasing.checkout, "tag", "v0.1.0", releasing.start)

    result = releasing.publish("--potwierdzone-przez-maksa")

    assert result.returncode == 1
    assert "Lokalny tag v0.1.0 wskazuje inny commit" in result.stdout.splitlines()[-1]
    assert releasing.remote_tags() == {}


def test_ponowione_wydanie_po_nieudanym_release_konczy_je_na_tym_samym_tagu(releasing: Releasing) -> None:
    merged = releasing.merge(1, "feat: ilości usług", {"src/a.py": "a = 1\n"})
    releasing.planned()
    releasing.github("fail_next_post")
    failed = releasing.publish("--potwierdzone-przez-maksa")
    tags = releasing.remote_tags()
    releasing.ci(merged, "failure")

    again = releasing.publish("--potwierdzone-przez-maksa")

    assert failed.returncode == 1
    assert tags.keys() == {"v0.1.0"}
    assert again.returncode == 0, again.stdout + again.stderr
    assert releasing.remote_tags() == tags
    assert git(releasing.checkout, "rev-parse", "refs/tags/v0.1.0^{commit}") == merged
    assert [posted["tag_name"] for posted in releasing.posted()] == ["v0.1.0"]


def test_sprawy_taty_to_uwagi_i_zgloszenia_rozwiazane_od_poprzedniego_wydania_bez_tresci(releasing: Releasing) -> None:
    released = releasing.merge(1, "feat: pierwsze", {"src/a.py": "a = 1\n"})
    releasing.released("v0.1.0", released, (DadCase(2, "Sprawa 2", "zgloszenie"),))
    releasing.merge(2, "fix: naprawa", {"src/a.py": "a = 2\n"})
    releasing.case(1, "zgloszenie", "2026-10-09T10:00:00Z")
    releasing.case(5, "uwaga-taty", "2026-10-09T10:00:00Z", updated_at="2026-10-11T10:00:00Z")
    releasing.case(2, "zgloszenie", "2026-10-11T10:00:00Z")
    releasing.case(3, "uwaga-taty", "2026-10-12T10:00:00Z")
    releasing.case(4, "uwaga-taty", "2026-10-12T10:00:00Z", reason="not_planned")
    releasing.case(6, "logi-uruchomienia", "2026-10-12T10:00:00Z")
    releasing.case(7, "zgloszenie", "2026-10-10T11:00:00Z")

    planned = releasing.planned()
    published = releasing.publish("--potwierdzone-przez-maksa")

    assert planned["dad_cases"] == [
        {"number": 3, "title": "Sprawa 3", "label": "uwaga-taty"},
        {"number": 7, "title": "Sprawa 7", "label": "zgloszenie"},
    ]
    assert published.returncode == 0, published.stdout + published.stderr
    assert SECRET not in releasing.plan_file.read_text(encoding="utf-8")
    assert SECRET not in releasing.posted()[0]["body"]
