"""Sprzątanie runu ``verify-github-skrzynki``: usuwa z repozytoriów próbnych tylko to, co założył ten run.

Run rozpoznaje znacznik ``<!-- verify-github-skrzynki run=<id> -->`` w treści issue i opisie Release (Archiwum) i
``verify-github-skrzynki run=<id>`` w opisie etykiety, a identyfikator runu w nazwie tagu i pliku Archiwum, nie nazwa:
issue z numerem z rejestru runu (``zalozone.jsonl``), które znacznika nie ma, zostaje i trafia do wyniku. Etykietę,
którą GitHub założył sam przy issue runu (bez opisu), usuwa tylko wtedy, gdy rejestr ją zapisał, a stan sprzed runu jej
nie miał. Issue usuwa GraphQL ``deleteIssue`` kluczem ``gh`` Maksa, bo zamknięte issue zostałoby w liście z
``include_closed`` następnego runu. Release ze znacznikiem usuwa razem z jego plikami tylko wtedy, gdy każdy plik ma w
nazwie identyfikator runu, a potem tag runu. Na koniec porównuje stan obu repozytoriów próbnych (etykiety, issue,
Release, tagi) ze stanem sprzed runu, zapisuje wynik w dowodach i usuwa katalog runu (``.katalog-runu``). Dowody
zostają.

    .venv/bin/python .agents/skills/verify-github-skrzynki/scripts/github_sprzatanie.py --root <katalog runu>
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from skrypt_skilla import Parser, RunRootError, remove_run_root, require_run_root

from github_wymiana import RUN_MARKER, TRIAL, TRIAL_ARCHIVE, TRIALS, Admin, Pace, gh_token

RUN_FILE: Final = "run.json"
# Lista issue GitHuba nadąża za założeniem i usunięciem po kilku sekundach (pomiar 5.11.2026: 98 ze 101 świeżych issue).
SETTLE_ROUNDS: Final = 12
SETTLE_S: Final = 5.0
LEDGER: Final = "zalozone.jsonl"


# Tag i plik Archiwum runu mają w nazwie ``verify-<run>`` albo ``<run>-`` (``github_przypadki_archiwum``).
RUN_TAG: Final = "logi-verify-"


def state(admin: Admin) -> dict[str, object]:
    """Stan każdego repozytorium próbnego, który run może zmienić: etykiety z opisem, numery issue, tagi Release i tagi."""

    return {trial: _state(admin, trial) for trial in TRIALS}


def _state(admin: Admin, trial: str) -> dict[str, object]:
    status, labels = admin.request("GET", f"/repos/{trial}/labels?per_page=100")
    issues = admin.pages(f"/repos/{trial}/issues?state=all")
    return {
        "etykiety": sorted(
            f"{entry['name']}: {entry.get('description') or ''}" for entry in labels if isinstance(entry, dict)
        )
        if status == 200 and isinstance(labels, list)
        else f"lista etykiet → {status}",
        "issue": sorted(entry["number"] for entry in issues if isinstance(entry, dict)),
        "release": sorted(_names(admin.pages(f"/repos/{trial}/releases?"), "tag_name")),
        "tagi": sorted(_names(admin.pages(f"/repos/{trial}/tags?"), "name")),
    }


def _names(entries: list[object], field: str) -> list[str]:
    return [str(entry.get(field)) for entry in entries if isinstance(entry, dict)]


def leftovers(admin: Admin, run: str | None = None) -> list[str]:
    """Issue, etykiety, Release'y i tagi ze znacznikiem runu ``run`` (``None``: każdego runu) w repozytoriach próbnych."""

    marker = RUN_MARKER + (run or "")
    found = []
    for trial in TRIALS:
        name = trial.rsplit("/", 1)[1]
        issues = admin.pages(f"/repos/{trial}/issues?state=all")
        found += [
            f"{name}: issue {entry['number']}"
            for entry in issues
            if isinstance(entry, dict) and marker in str(entry.get("body") or "")
        ]
        _, labels = admin.request("GET", f"/repos/{trial}/labels?per_page=100")
        for entry in labels if isinstance(labels, list) else []:
            if isinstance(entry, dict) and marker in str(entry.get("description") or ""):
                found.append(f"{name}: etykieta {entry['name']}")
        for entry in admin.pages(f"/repos/{trial}/releases?"):
            if isinstance(entry, dict) and marker in str(entry.get("body") or ""):
                found.append(f"{name}: Release {entry.get('tag_name')}")
        for entry in admin.pages(f"/repos/{trial}/tags?"):
            if isinstance(entry, dict) and str(entry.get("name")).startswith(RUN_TAG + (run or "")):
                found.append(f"{name}: tag {entry.get('name')}")
    return found


def _clean_releases(admin: Admin, trial: str, run: str, noted: set[int]) -> list[str]:
    """Release'y (Archiwa) ze znacznikiem runu w opisie, z listy i z rejestru ``noted`` (każdy pytany wprost, bo lista
    może nie nadążać), razem z plikami, gdy każdy ma w nazwie identyfikator runu, a potem tagi z identyfikatorem runu."""

    lines = []
    found = {entry["id"]: entry for entry in admin.pages(f"/repos/{trial}/releases?") if isinstance(entry, dict)}
    for release in sorted(noted - set(found)):
        status, entry = admin.request("GET", f"/repos/{trial}/releases/{release}")
        if status == 200 and isinstance(entry, dict):
            found[release] = entry
    for release, entry in sorted(found.items()):
        if f"{RUN_MARKER}{run}" not in str(entry.get("body") or ""):
            continue
        foreign = [
            str(asset.get("name"))
            for asset in admin.pages(f"/repos/{trial}/releases/{release}/assets?")
            if isinstance(asset, dict) and not str(asset.get("name")).startswith(f"{run}-")
        ]
        if foreign:
            lines.append(f"BŁĄD: Release {entry.get('tag_name')} zostaje, bo ma pliki bez identyfikatora runu: {foreign[:3]}")
            continue
        status, _ = admin.request("DELETE", f"/repos/{trial}/releases/{release}")
        lines.append(
            f"usunięty Release {entry.get('tag_name')} z plikami" if status == 204 else f"BŁĄD usunięcia Release: {status}"
        )
    for entry in admin.pages(f"/repos/{trial}/tags?"):
        tag = str(entry.get("name")) if isinstance(entry, dict) else ""
        if tag.startswith(f"{RUN_TAG}{run}"):
            status, _ = admin.request("DELETE", f"/repos/{trial}/git/refs/tags/{tag}")
            lines.append(f"usunięty tag {tag}" if status == 204 else f"BŁĄD usunięcia tagu {tag}: {status}")
    return lines


def _clean_issues(admin: Admin, marker: str, noted: set[int], lines: list[str]) -> tuple[int, list[int]]:
    """Usuwa issue ze znacznikiem ``marker``: z listy repozytorium i z rejestru ``noted`` (każde pytane wprost, bo
    lista issue GitHuba nadąża za zmianami dopiero po kilku sekundach), aż żadne nie zostanie. Zwraca liczbę usuniętych
    i numery z rejestru, które zostają, bo nie mają znacznika."""

    deleted, kept, gone = 0, [], set[int]()
    for _ in range(SETTLE_ROUNDS):
        found: dict[int, dict[str, object]] = {
            entry["number"]: entry
            for entry in admin.pages(f"/repos/{TRIAL}/issues?state=all")
            if isinstance(entry, dict)
        }
        for number in sorted(noted - set(found) - gone):
            status, entry = admin.request("GET", f"/repos/{TRIAL}/issues/{number}")
            if status == 200 and isinstance(entry, dict):
                found[number] = entry
            else:
                gone.add(number)
        marked = {number: entry for number, entry in found.items() if marker in str(entry.get("body") or "")}
        kept = sorted(number for number in noted & set(found) if number not in marked)
        if not marked:
            break
        for number, entry in sorted(marked.items()):
            status, answer = admin.delete_issue(str(entry["node_id"]))
            failed = status != 200 or (isinstance(answer, dict) and answer.get("errors"))
            lines.append(
                f"usunięte issue {number}" if not failed else f"BŁĄD usunięcia issue {number}: {status} {answer}"
            )
            deleted += not failed
            gone.add(number)
        time.sleep(SETTLE_S)
    lines += [f"zostaje issue {number}: w rejestrze, ale bez znacznika runu" for number in kept]
    return deleted, kept


def clean(root: Path) -> tuple[bool, list[str]]:
    """Sprząta run z ``root``: (czy repozytorium wróciło do stanu sprzed runu, linie wyniku)."""

    if not (require_run_root(root) / RUN_FILE).is_file():
        remove_run_root(root)
        return True, [
            f"SPRZĄTANIE OK | run bez {RUN_FILE}: nic nie założył w repozytorium próbnym | usuniety_katalog={root}"
        ]
    facts = json.loads((root / RUN_FILE).read_text(encoding="utf-8"))
    run, before = str(facts["run"]), facts["stan_przed"]
    ledger = (
        [json.loads(line) for line in (root / LEDGER).read_text(encoding="utf-8").splitlines()]
        if (root / LEDGER).is_file()
        else []
    )
    admin = Admin(gh_token(), Pace())
    lines: list[str] = []
    marker = f"<!-- {RUN_MARKER}{run} -->"
    noted = {entry["issue"] for entry in ledger if "issue" in entry}
    deleted, kept = _clean_issues(admin, marker, noted, lines)
    _, labels = admin.request("GET", f"/repos/{TRIAL}/labels?per_page=100")
    before_labels = before[TRIAL]["etykiety"]
    before_names = {line.split(":", 1)[0] for line in before_labels} if isinstance(before_labels, list) else set()
    by_github = {entry["etykieta"] for entry in ledger if entry.get("zrodlo") == "github"}
    for label in labels if isinstance(labels, list) else []:
        name, description = str(label.get("name")), str(label.get("description") or "")
        if f"{RUN_MARKER}{run}" in description or (name in by_github and name not in before_names):
            status, _ = admin.request("DELETE", f"/repos/{TRIAL}/labels/{name}")
            lines.append(f"usunięta etykieta {name}" if status == 204 else f"BŁĄD usunięcia etykiety {name}: {status}")
    releases = {entry["release"] for entry in ledger if "release" in entry}
    for trial in TRIALS:
        lines += _clean_releases(admin, trial, run, releases if trial == TRIAL_ARCHIVE else set())
    after = state(admin)
    for _ in range(SETTLE_ROUNDS):  # lista issue GitHuba nadąża za usunięciem po kilku sekundach
        if after == before:
            break
        time.sleep(SETTLE_S)
        after = state(admin)
    restored = after == before and not kept
    lines.append(f"stan przed: {json.dumps(before, ensure_ascii=False)}")
    lines.append(f"stan po: {json.dumps(after, ensure_ascii=False)}")
    lines += admin.log
    evidence = Path(facts["dowody"])
    summary = f"SPRZĄTANIE {'OK' if restored else 'FAIL'} | usuniete_issue={deleted} | repo_wrocilo={str(restored).lower()} | evidence={evidence}"
    lines.append(summary)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "sprzatanie.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    remove_run_root(root)
    return restored, lines


def main() -> int:
    parser = Parser(description=__doc__.splitlines()[0])
    parser.add_root("katalog runu, który założył github_skrzynki.py na-zywo")
    arguments = parser.parse_args()
    try:
        restored, lines = clean(arguments.root)
    except RunRootError as error:
        print(f"SPRZĄTANIE ODMOWA | {error}")
        return 1
    print(lines[-1])
    return 0 if restored else 1


if __name__ == "__main__":
    raise SystemExit(main())
