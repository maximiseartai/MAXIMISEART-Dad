"""Drive features/logi-uruchomienia.md."""

from __future__ import annotations

from datetime import datetime
import gzip
import json
import re
import subprocess
from typing import Any

from playwright.sync_api import Page, expect

from drive.common import (
    Run,
    box_issues,
    drop_report_key,
    finished_view,
    queued,
    read_bytes,
    read_json,
    read_text,
    run_logs,
    served_version,
)
from drive.waiting import Budget, until
from drive.teksty import ABOUT_LOGS
from drive.przebieg_rozliczen import TEMPLATE_PACING_MS
from atrapy.scenariusz_centrum import ROW_MARKER
from atrapy.pliki_taty import REPORT_KEY_FILE
from harness import archive_file, archive_listing

FEATURE = "logi-uruchomienia"
LABEL = "logi-uruchomienia"
# A synthetic key of its own; see ``common.REPORT_KEY``.
KEY = "github_pat_VERIFY_SYNTETYCZNY_KLUCZ_LOGOW"
# The last line of a comment: the link to the file of its full Logi in the Archiwum Logów okresu (a GitHub Release).
LINK = re.compile(r"- Pełne Logi: \[(?P<name>[^\]]+)\]\(https://github\.com/[^/]+/[^/]+/releases/download/(?P<tag>[^/]+)/(?P=name)\)")
# A Wydanie's tag (ADR 0014): vMAJOR.MINOR.PATCH without leading zeros or suffixes.
RELEASE_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

Json = dict[str, Any]
"""A file of Logi or a card, parsed from JSON."""


def _card(run: Run, name: str) -> Json:
    """The finished card as the browser got it: the one answer ``finished_view`` waited for, kept in ``api/``."""

    return finished_view(run, name)


def _one_new(run: Run, before: set[str], what: str) -> Json:
    new = {name: record for name, record in run_logs(run).items() if name not in before}
    run.check(len(new) == 1, f"{what}: exactly one new file in {run.run_logs_dir.relative_to(run.root).as_posix()} ({', '.join(sorted(new))})")
    [record] = new.values()
    return record


def _matches_card(run: Run, record: Json, view: Json, mode: str) -> None:
    info, result = view["run"], view["result"]
    run.check(
        (record["run_id"], record["process"], record["period"], record["mode"])
        == (info["id"], info["process"], info["period"], mode),
        f"the Logi name the card's Uruchomienie {info['id']} and say it was a {mode}",
    )
    run.check(
        (record["result"], record["ending"], record["stop_kind"])
        == (result["result"], result["ending"], result["stop_kind"]),
        f"result, ending and Rodzaj Zatrzymania equal the card: {result['result']}, {result['ending']}, "
        f"{result['stop_kind']}",
    )
    shown = [("stop", stop) for stop in result["stops"]] + [("warning", warning) for warning in result["warnings"]]
    run.check(
        [
            (message["kind"], {part: message[part] for part in ("what", "where", "action", "setting") if part in message})
            for message in record["messages"]
        ]
        == shown,
        f"the Logi hold the card's {len(shown)} Komunikaty in three parts with their link to Ustawienia, stops before warnings",
    )
    run.check(
        (record["summary"], record["technical_notes"]) == (result["summary"], result["technical_notes"]),
        "the summary and the technical notes equal the card",
    )


def _wydanie(run: Run, commit: str) -> str | None:
    """The highest Wydanie whose tag in the run's tool clone points at ``commit``, as Git lists the tags.

    Tags from the install (``refs/tags/``) and from Aktualizacja narzędzia (``refs/wydania/``) count.
    """

    clone = run.fixture["tool"]["clone"]
    tags = subprocess.run(
        ["git", "-C", clone, "for-each-ref", "--points-at", commit, "--format=%(refname:strip=2)", "refs/tags/", "refs/wydania/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    numbers = [tuple(map(int, found.groups())) for tag in tags if (found := RELEASE_TAG.fullmatch(tag))]
    return ".".join(map(str, max(numbers))) if numbers else None


def _names_running_tool(run: Run, record: Json) -> None:
    commit = served_version(run)[0]
    wydanie = _wydanie(run, commit)
    run.check(
        record["tool"] == {"wydanie": wydanie, "commit": commit},
        f"the Logi name the commit of the tool Centrum runs and its Wydanie from the clone's tags ({wydanie or 'none'})",
    )


def _codes(record: Json) -> list[tuple[str, str]]:
    return [(message["kind"], message["code"]) for message in record["messages"]]


def _nothing_about_logs(run: Run, page: Page, where: str) -> None:
    text = page.locator("body").inner_text()
    run.check(ABOUT_LOGS.search(text) is None, f"{where}: Dad reads nothing about the Logi, on the card or in a toast")


def _new_settlement(run: Run, page: Page, period: str) -> None:
    page.goto(run.url + "#/uruchomienia")
    page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)


def _archived(run: Run, tag: str, name: str) -> bytes:
    """The file ``name`` of the Archiwum ``tag`` in the run's skrzynka, unpacked byte for byte; empty when the Archiwum
    lacks it."""

    path = archive_file(run.root, tag, name)
    return gzip.decompress(read_bytes(path)) if path.is_file() else b""


def _ended_in_centrum_log(run: Run) -> list[tuple[str, str, str, str, str]]:
    return [
        (fact["proces"], fact["tryb"], fact["okres"], fact["wynik"], fact["koniec"])
        for fact in (entry.facts for entry in run.log_entries() if entry.event == "uruchomienie-koniec")
    ]


def drive(run: Run, page: Page) -> None:
    needs_check = run.fixture["settlement"]["needs_check"]
    settled = run.evidence / "api" / "przebieg-zapisane.json"

    run.step(FEATURE, "logi-podglad")
    before = set(run_logs(run))
    _new_settlement(run, page, needs_check)
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    view = _card(run, "logi-podglad")
    record = _one_new(run, before, "Podgląd bez zapisu")
    _matches_card(run, record, view, "DRY-RUN")
    _names_running_tool(run, record)
    run.check(
        _codes(record) == [("warning", "BRAK_MAPOWANIA")],
        "the warning keeps its code BRAK_MAPOWANIA, which the card does not show",
    )
    _nothing_about_logs(run, page, "after the preview")
    run.capture(page, "160-logi-podglad")

    run.step(FEATURE, "logi-zatrzymanie")
    before = set(run_logs(run))
    _new_settlement(run, page, needs_check)
    page.get_by_role("button", name="Uruchom", exact=True).click()
    page.get_by_role("alertdialog", name="Uruchomić z zapisem?").get_by_role("button", name="Uruchom", exact=True).click()
    expect(page.get_by_label("Zatrzymanie")).to_contain_text("W Pliku zbiorczym jest WYKONAWCA")
    view = _card(run, "logi-zatrzymanie")
    record = _one_new(run, before, "Zatrzymanie")
    _matches_card(run, record, view, "RUN")
    _names_running_tool(run, record)
    run.check(
        _codes(record) == [("stop", "NIEZNANY_WYKONAWCA")],
        "the Zatrzymanie is one message of kind stop with its code NIEZNANY_WYKONAWCA",
    )
    _nothing_about_logs(run, page, "after the Zatrzymanie")
    run.capture(page, "161-logi-zatrzymanie")

    run.step(FEATURE, "logi-szablony")
    view = read_json(settled)
    [record] = [record for record in run_logs(run).values() if record["run_id"] == view["run"]["id"]]
    _matches_card(run, record, view, "RUN")
    workers, rows = run.fixture["workers"], run.fixture["settlement"]["rows_per_worker"]
    templates = record["templates"]
    run.check(
        [(template["wykonawca"], template["outcome"], template["rows"]) for template in templates]
        == [
            (worker, "ZAPISANO" if count else "PUSTY_SZABLON", count) for worker, count in zip(workers, rows, strict=True)
        ],
        "the Logi of the written Przebieg rozliczeń list every Wykonawca in order with his outcome and rows",
    )
    durations = [template["duration_ms"] for template in templates] or [None]
    run.check(
        all(isinstance(duration, int) for duration in durations) and durations[0] >= TEMPLATE_PACING_MS,
        f"each Szablon pracownika has its time; the first, paced {TEMPLATE_PACING_MS} ms (harness), took {durations[0]} ms",
    )

    run.step(FEATURE, "logi-kazde-uruchomienie")
    ended = _ended_in_centrum_log(run)
    records = sorted(run_logs(run).values(), key=lambda record: datetime.fromisoformat(record["started_at"]))
    run.check(
        [(record["process"], record["mode"], record["period"], record["result"], record["ending"]) for record in records]
        == ended,
        f"each of the {len(ended)} Uruchomienia ended in the Centrum log has its own file of Logi, in the same order",
    )
    run.check(len({record["run_id"] for record in records}) == len(records), "no two files hold the same Uruchomienie")

    run.step(FEATURE, "logi-bez-sladu")
    page.reload()
    expect(page.get_by_label("Zatrzymanie")).to_be_visible()
    _nothing_about_logs(run, page, "Uruchomienia after a reload")
    texts = [read_text(path) for path in sorted(run.run_logs_dir.glob("*.json"))]
    run.check(
        not any(json.dumps(str(run.root))[1:-1] in text or ROW_MARKER in text for text in texts),
        "no file of Logi holds a path in the run root or workbook row content",
    )
    files = [logged["name"] for record in records for logged in record["environment"]["files"] or []]
    run.check(
        files != [] and not any("/" in name or "\\" in name for name in files),
        "the files of each process are listed by name only",
    )

    run.step(FEATURE, "logi-w-skrzynce")
    print("  harness: Maks writes the key; the next Uruchomienie wakes the queue", flush=True)
    key_file = run.config / REPORT_KEY_FILE
    key_file.write_text(KEY + "\n", encoding="utf-8")
    try:
        _new_settlement(run, page, needs_check)
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
        woke = _card(run, "logi-skrzynka-podglad")
        until(lambda: queued(run, LABEL, leaving=True) == [], "every Logi waiting in the queue reaches the skrzynka", Budget.BACKGROUND)
    finally:
        drop_report_key(key_file)
    # Bytes, not text: reading text turns the \r\n of a file written in text mode on Windows back into \n.
    files = sorted(read_bytes(path) for path in run.run_logs_dir.glob("*.json"))
    threads = box_issues(run, LABEL)
    (run.evidence / "api" / "logi-skrzynka.json").write_text(
        json.dumps(
            [
                {key: thread[key] for key in ("number", "title", "labels", "state")}
                | {"comments": len(thread.get("comments", []))}
                for thread in threads
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    periods = sorted({json.loads(text)["period"] for text in files})
    run.check(
        sorted((thread["title"], thread["body"].splitlines()[0]) for thread in threads)
        == [(f"Logi Uruchomienia {period}", f"- Logi Uruchomienia okresu: {period}") for period in periods],
        f"the skrzynka has one issue labelled {LABEL} per period with Uruchomienia: {', '.join(periods)}",
    )
    comments = [(thread["title"], comment) for thread in threads for comment in thread.get("comments", [])]
    links = [(title, LINK.fullmatch(comment.rstrip("\n").splitlines()[-1])) for title, comment in comments]
    run.check(
        all(link is not None for _, link in links),
        "each comment ends with the link to its full Logi in the Archiwum Logów okresu",
    )
    sent = [(title, link["tag"], _archived(run, link["tag"], link["name"])) for title, link in links if link is not None]
    by_run: dict[str, list[bytes]] = {}
    for _, _, text in sent:
        by_run.setdefault(json.loads(text)["run_id"] if text else "", []).append(text)
    local = {json.loads(text)["run_id"]: text for text in files}
    run.check(
        sorted(by_run) == sorted(local) and all(texts[-1] == local[run_id] for run_id, texts in by_run.items()),
        f"each of the {len(files)} files of Logi is, unpacked, the file in the Archiwum its comment links, byte for byte",
    )
    run.check(
        all(len(texts) == 1 for texts in by_run.values()),
        "each Uruchomienie is one comment, also after a Diagnoza, which changes that comment and its file",
    )
    run.check(
        all(
            (title, tag) == (f"Logi Uruchomienia {json.loads(text)['period']}", f"logi-{json.loads(text)['period']}")
            for title, tag, text in sent
            if text
        ),
        "each comment is in the issue of its own period and links the Archiwum of that period",
    )
    listed = read_json(archive_listing(run.root))
    run.check(
        sorted(archive["tag"] for archive in listed) == [f"logi-{period}" for period in periods]
        and sum(len(archive["assets"]) for archive in listed) == len(files),
        f"the skrzynka has one Archiwum Logów okresu per period with Uruchomienia and one file per Uruchomienie: {len(files)}",
    )
    run.check(
        all(comment.startswith("**Logi Uruchomienia**: ") for _, comment in comments),
        "each comment starts with the summary of its Uruchomienie",
    )
    [example] = [comment for _, comment in comments if f"- Uruchomienie: {woke['run']['id']}," in comment]
    (run.evidence / "api" / "logi-komentarz.md").write_text(example, encoding="utf-8")
    everything = json.dumps(threads, ensure_ascii=False)
    run.check(KEY not in everything and ROW_MARKER not in everything, "the skrzynka has neither the key nor workbook content")
    _nothing_about_logs(run, page, "after the Logi reached the skrzynka")
    run.capture(page, "162-logi-w-skrzynce")
