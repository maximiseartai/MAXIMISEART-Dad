"""Drive features/uwaga-taty.md."""

from __future__ import annotations

from datetime import datetime
import html
import json
from pathlib import Path
import re
import stat
from typing import Any
import urllib.parse
import urllib.request

from playwright.sync_api import FloatRect, Locator, Page, Request, ViewportSize, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from drive.common import (
    CENTRE_TAKES_CLICK,
    PAGES,
    REPORT_KEY,
    box_issues,
    close_centrum,
    current_run,
    drop_report_key,
    ended_run_shown,
    ensure_files_set,
    error_toasts,
    finished_result,
    finished_view,
    history_rows,
    local_time,
    queued,
    queued_posts,
    read_bytes,
    read_json,
    read_text,
    remove,
    Run,
    start_centrum,
    shown_theme,
    switch_theme,
    toggle_theme,
)
from drive.waiting import Budget, until
from harness import Pace, comment_address, issue_file, rejects
from drive.teksty import FOR_KEY, MODES, WRITE
from rozliczenia.centrum.contract.common import ProcessKey
from rozliczenia.centrum.run_origins import CentrumRuns
from rozliczenia.preparation_process import PROCESS as PREPARATION
from rozliczenia.process_run import Process
from rozliczenia.settlement_process import PROCESS as SETTLEMENT
from rozliczenia.telemetry import MetricsStore
from atrapy.pliki_taty import CENTRUM_RUNS_FILE, DAD_CASES_FILE, REPORT_KEY_FILE

FEATURE = "uwaga-taty"
LABEL = "uwaga-taty"
SENT = "Uwaga wysłana do Maksa."
REFUSED_CONTENT = "Tej Uwagi nie da się wysłać. Skontaktuj się z Maksem."
# Synthetic Uwagi: the first waits for the key, the second has no Treść.
FIRST = ("Brakuje kolumny z kilometrami", "W Pliku zbiorczym nie ma kilometrów.\nDopisuję je ręcznie.")
SECOND = ("Proszę o większą czcionkę", "")
# Unbroken text Dad might paste (a OneDrive link) on a 1366×768 screen: the dialog must not grow with it. A Tytuł of
# wide letters wraps to the most lines in „Maks dostanie”.
LONG = "W" * 120, ("https://onedrive.live.com/edit?id=" + "SYNTETYCZNY0123456789" * 20)[:400]
SMALL_SCREEN: ViewportSize = {"width": 1366, "height": 768}
# Windows Dad's screen may give the browser (#488): 1280×720 at 150% is 853×480 CSS pixels. A long Tytuł and a Treść of
# many short lines fill the form; a 10 000-character link is the longest Treść the contract allows.
LOW_WINDOW = ViewportSize(width=853, height=480)
LOW_WINDOWS: tuple[tuple[ViewportSize, str], ...] = (
    (LOW_WINDOW, "lines"),
    (ViewportSize(width=1280, height=520), "link"),
    (SMALL_SCREEN, "lines"),
    (ViewportSize(width=1093, height=614), "lines"),
)
LOW_NOTES = {
    "lines": (
        " ".join(f"Linia tytułu numer {line}." for line in range(5)),
        "\n".join(f"Linia treści uwagi taty numer {line}." for line in range(30)),
    ),
    "link": ("Link do pliku", ("https://onedrive.live.com/edit?id=" + "SYNTETYCZNY0123456789" * 500)[:10_000]),
}
# Centrum Uruchomienia the full-window list shows, as many as the dialog offers (`RECENT_RUNS`): more than four and a
# half rows, so the list gives up height (#498).
FULL_LIST_RUNS = 6
# Each issue waits this long in the skrzynka, so „Wyślij” is seen sending; two issues stay under the 5 s wait.
BOX_PACING_MS = 1500
ABOUT_RUN = "Napisz do Maksa o tym Uruchomieniu"
PINNED = ("Podgląd każe sprawdzić okres", "Nie wiem, którego Wykonawcę mam dopisać.")
# Uwagi pinned to previews whose Logi the skrzynka rejected or that never reached the queue. Each has its own title,
# because powiadomienia finds the newest Uwaga by it.
REJECTED = ("Podgląd po odrzuconych Logach", "Proszę spojrzeć na ten podgląd.")
NO_LOGS = ("Podgląd bez Logów", "")
# An Uwaga whose content the skrzynka rejects; it goes out at the next start of Centrum.
REFUSED = ("Uwaga, której Skrzynka nie przyjmie", "Treść odrzucona przez Skrzynkę.")
LOGS_LABEL = "logi-uruchomienia"
LOGS_LINK = re.compile(r"^\[Logi Uruchomienia\]\((.*)\)$", re.MULTILINE)
# A Markdown link as GitHub renders it, for the harness page that shows an issue the way Maks sees it.
MARKDOWN_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
NO_RUNS = "Nie ma jeszcze Uruchomień z Centrum."
NOT_IN_HISTORY = "Tego Uruchomienia nie ma w historii Centrum. Wybierz inne albo wyślij Uwagę ogólną."
LAPTOP = ViewportSize(width=1280, height=720)
# Measured as painted: in the frame after the next, whose ResizeObserver has already scrolled the list for the last
# change. A layout read between React's commit and that frame sees the list shrunk but not yet scrolled.
WHOLLY_SHOWN = """element => new Promise(measured => requestAnimationFrame(() => requestAnimationFrame(() => {
    const box = element.getBoundingClientRect()
    const inside = outer => box.top >= outer.top - 0.5 && box.bottom <= outer.bottom + 0.5
    let shown = inside({top: 0, bottom: innerHeight})
    for (let parent = element.parentElement; parent !== null; parent = parent.parentElement) {
        if (getComputedStyle(parent).overflowY !== "visible") {
            shown = shown && inside(parent.getBoundingClientRect())
        }
    }
    measured({shown, top: Math.round(box.top), bottom: Math.round(box.bottom)})
})))"""


# How much of its own height each part keeps: „Dotyczy” with the list and „Maks dostanie” with its Treść, each
# scrolling part at most at its max-height, without padding, as flexbox shares the missing height. Measured as painted,
# like WHOLLY_SHOWN.
KEPT = """figure => new Promise(measured => requestAnimationFrame(() => requestAnimationFrame(() => {
    const dialog = figure.closest("[role=dialog]")
    const list = dialog.querySelector("[role=radiogroup]")
    const label = [...dialog.querySelectorAll("[data-slot=field-label]")].find(element => element.textContent === "Dotyczy")
    const given = part => Math.min(part.scrollHeight + part.offsetHeight - part.clientHeight, parseFloat(getComputedStyle(part).maxHeight)) - part.offsetHeight
    const box = list.getBoundingClientRect()
    const dotyczy = box.bottom - label.getBoundingClientRect().top
    const style = getComputedStyle(figure)
    const preview = figure.getBoundingClientRect().height - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)
    measured({
        list: Math.round(box.height * 10) / 10,
        listNatural: Math.round((box.height + given(list)) * 10) / 10,
        dotyczy: Math.round(dotyczy / (dotyczy + given(list)) * 1000) / 1000,
        figure: Math.round(preview / (preview + given(figure.querySelectorAll("p")[1])) * 1000) / 1000,
    })
})))"""

# Whether the fields scroll, and how high „Maks dostanie” and „Dotyczy” with the list are against their least: the
# caption and the first line of the preview, the switch (with the sentence above the list) and one row of the list.
# `step` is one Tailwind spacing step, which the minimum of „Dotyczy” rounds up to. Measured as painted, like KEPT.
LEAST = """dialog => new Promise(measured => requestAnimationFrame(() => requestAnimationFrame(() => {
    const figure = dialog.querySelector("figure")
    const fields = figure.parentElement
    const height = element => element.getBoundingClientRect().height
    const round = value => Math.round(value * 10) / 10
    const style = getComputedStyle(figure)
    const line = parseFloat(getComputedStyle(figure.querySelector("p")).lineHeight)
    const list = dialog.querySelector("[role=radiogroup]")
    const field = list && list.closest("[data-slot=field]")
    const top = field && list.getBoundingClientRect().top - field.getBoundingClientRect().top
    measured({
        scrolls: fields.scrollHeight > fields.clientHeight + 1,
        preview: round(height(figure)),
        previewLeast: round(parseFloat(style.paddingTop) + height(figure.querySelector("figcaption")) + parseFloat(style.rowGap) + line + parseFloat(style.paddingBottom)),
        dotyczy: field && round(height(field)),
        dotyczyLeast: field && round(top + list.offsetHeight - list.clientHeight + height(list.querySelector("label"))),
        step: parseFloat(getComputedStyle(document.documentElement).fontSize) / 4,
    })
})))"""


def _server_time(started_at: str) -> str:
    """The date text the server writes (``06.10.2026, 08:21``): in the computer's time zone, Dad's own at his."""

    return datetime.fromisoformat(started_at).astimezone().strftime("%d.%m.%Y, %H:%M")


def _draft(run: Run, title: str, body: str, name: str, run_id: str | None = None) -> dict[str, str]:
    """The issue Maks would get, straight from the server, as the reference for the figure in the tab."""

    note = {"title": title, "body": body} | ({} if run_id is None else {"run_id": run_id})
    request = urllib.request.Request(
        run.url.rstrip("/") + "/api/dad-notes/draft",
        data=json.dumps(note).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Origin": run.url.rstrip("/")},
    )
    with urllib.request.urlopen(request, timeout=Budget.SCREEN.value) as response:
        draft = json.load(response)
    (run.evidence / "api" / f"{name}.json").write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert isinstance(draft, dict)
    return {"title": str(draft["title"]), "body": str(draft["body"]), "shown_body": str(draft["shown_body"])}


def _shown(figure: Locator) -> tuple[str, str]:
    """Title and body as „Maks dostanie” shows them."""

    lines = figure.locator("p")
    return lines.nth(0).inner_text(), lines.nth(1).inner_text()


def _shows(run: Run, figure: Locator, draft: dict[str, str], message: str) -> None:
    expected = (draft["title"], draft["shown_body"])
    until(lambda: _shown(figure) == expected, message)


def _notes(config: Path) -> list[dict[str, object]]:
    path = config / DAD_CASES_FILE
    cases = read_json(path)["sprawy"] if path.exists() else []
    return [case for case in cases if case["kind"] == "uwaga"]


def _open(page: Page) -> Locator:
    page.get_by_role("button", name=WRITE, exact=True).click()
    dialog = page.get_by_role("dialog", name=WRITE, exact=True)
    expect(dialog).to_be_visible()
    return dialog


def _close(dialog: Locator) -> None:
    """„Zamknij” under the answer; the dialog's corner button of the same name comes after it."""

    dialog.get_by_role("button", name="Zamknij", exact=True).first.click()
    expect(dialog).to_have_count(0)


def _write(dialog: Locator, title: str, body: str) -> None:
    dialog.get_by_role("textbox", name="Tytuł", exact=True).fill(title)
    dialog.get_by_role("textbox", name="Treść (niekonieczna)", exact=True).fill(body)


def _overflowing(page: Page, dialog: Locator) -> list[str]:
    """Parts of the form that stick out of the dialog sideways, the form or „Wyślij” off the screen (the fields between
    them scroll), and the dialog itself if it scrolls sideways."""

    frame = dialog.bounding_box()
    viewport = page.viewport_size
    assert frame is not None and viewport is not None
    parts = {
        "form": dialog.locator("form"),
        "Tytuł": dialog.get_by_role("textbox", name="Tytuł", exact=True),
        "Treść": dialog.get_by_role("textbox", name="Treść (niekonieczna)", exact=True),
        "Maks dostanie": dialog.get_by_role("figure", name="Co dostanie Maks", exact=True),
        "Wyślij": dialog.get_by_role("button", name="Wyślij", exact=True),
    }
    outside = [
        name
        for name, part in parts.items()
        if (box := part.bounding_box()) is None
        or box["x"] < frame["x"]
        or box["x"] + box["width"] > min(frame["x"] + frame["width"], viewport["width"]) + 0.5
        or (name in ("form", "Wyślij")
        and (box["y"] < 0 or box["y"] + box["height"] > viewport["height"] + 0.5))
    ]
    if (
        frame["x"] < 0
        or frame["y"] < 0
        or frame["x"] + frame["width"] > viewport["width"]
        or frame["y"] + frame["height"] > viewport["height"]
    ):
        outside.append(f"dialog {frame}")
    if dialog.evaluate("dialog => dialog.scrollWidth > dialog.clientWidth"):
        outside.append("dialog scrolls sideways")
    return outside


def _boxed(outer: FloatRect, inner: FloatRect) -> bool:
    return (
        inner["x"] >= outer["x"] - 0.5
        and inner["y"] >= outer["y"] - 0.5
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + 0.5
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + 0.5
    )


def _overlap(one: FloatRect, other: FloatRect) -> bool:
    return (
        one["x"] < other["x"] + other["width"]
        and other["x"] < one["x"] + one["width"]
        and one["y"] < other["y"] + other["height"]
        and other["y"] < one["y"] + one["height"]
    )


def _send_misplaced(page: Page, dialog: Locator) -> list[str]:
    """What keeps Dad from „Wyślij” or garbles the form in this window; empty when nothing does. The switch „Dotyczy” and
    the caption „Maks dostanie” only have to reach the screen once scrolled to: in a low window the fields scroll."""

    viewport = page.viewport_size
    frame = dialog.bounding_box()
    send = dialog.get_by_role("button", name="Wyślij", exact=True)
    button = send.bounding_box()
    switch = dialog.get_by_role("group", name="Dotyczy", exact=True)
    toggle = switch.bounding_box()
    caption = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True).get_by_text("Maks dostanie", exact=True)
    assert viewport is not None and frame is not None and button is not None and toggle is not None
    screen = FloatRect(x=0, y=0, width=viewport["width"], height=viewport["height"])
    wrong = []
    if not _boxed(screen, frame):
        wrong.append(f"the dialog {frame} sticks out of the window")
    if dialog.evaluate("dialog => dialog.scrollWidth > dialog.clientWidth"):
        wrong.append("the dialog scrolls sideways")
    shown = send.evaluate(WHOLLY_SHOWN)
    if not (_boxed(frame, button) and shown["shown"]):
        wrong.append(f"„Wyślij” {button} is not wholly inside the dialog {frame} or is clipped ({shown})")
    if not send.is_enabled() or not send.evaluate(CENTRE_TAKES_CLICK):
        wrong.append("„Wyślij” does not take a click at its centre")
    if (label := caption.bounding_box()) is None or _overlap(toggle, label):
        wrong.append(f"the switch „Dotyczy” {toggle} overlaps the caption „Maks dostanie” {label}")
    for name, part in (("the switch „Dotyczy”", switch), ("the caption „Maks dostanie”", caption)):
        part.scroll_into_view_if_needed()
        shown = part.evaluate(WHOLLY_SHOWN)
        if not (shown["shown"] and part.evaluate(CENTRE_TAKES_CLICK)):
            wrong.append(f"{name} scrolled into view is not wholly shown or does not take a click at its centre ({shown})")
    return wrong


def _scrolls_at_least(run: Run, dialog: Locator, where: str) -> bool:
    """Checks that the fields scroll only once „Maks dostanie” and „Dotyczy” with the list are at their least, and that
    they are not held above it then; returns whether the fields scroll."""

    least = dialog.evaluate(LEAST)
    preview_least = abs(least["preview"] - least["previewLeast"]) <= 1
    dotyczy_least = least["dotyczy"] is None or -1 <= least["dotyczy"] - least["dotyczyLeast"] <= least["step"] + 1
    run.check(
        not least["scrolls"] or (preview_least and dotyczy_least),
        f"at {where} the fields scroll only with „Maks dostanie” at its caption and first line and „Dotyczy” with the"
        f" list at its switch and one row ({least})",
    )
    return bool(least["scrolls"])


def _drive_low_windows(run: Run, page: Page) -> None:
    run.step(FEATURE, "uwaga-niskie-okno")
    screen = page.viewport_size
    assert screen is not None
    drafts = {kind: _draft(run, *note, f"uwaga-szkic-niskie-okno-{kind}") for kind, note in LOW_NOTES.items()}
    themes = []
    try:
        for second_theme in (False, True):
            if second_theme:
                toggle_theme(page)
            theme = shown_theme(page)
            themes.append(theme)
            for window, kind in ((screen, "lines"), *LOW_WINDOWS):
                page.set_viewport_size(window)
                dialog = _open(page)
                _write(dialog, *LOW_NOTES[kind])
                figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
                _shows(run, figure, drafts[kind], f"„Maks dostanie” shows the draft at {window['width']}×{window['height']}")
                expect(dialog.get_by_role("button", name="Wyślij", exact=True)).to_be_enabled()
                if window == screen and not second_theme:
                    run.capture(page, "178-uwaga-pelne-okno", full_page=False)
                if window == LOW_WINDOW:
                    shot = "177b-uwaga-niskie-okno-drugi-motyw" if second_theme else "177-uwaga-niskie-okno"
                    run.capture(page, shot, full_page=False)
                where = f"{window['width']}×{window['height']} ({kind}, motyw {theme})"
                scrolls = _scrolls_at_least(run, dialog, where)
                if window in (screen, LOW_WINDOW):
                    run.check(scrolls == (window == LOW_WINDOW), f"at {where} the fields scroll only in the low window")
                wrong = _send_misplaced(page, dialog)
                run.check(
                    wrong == [],
                    f"at {window['width']}×{window['height']} ({kind}, motyw {theme}) „Wyślij” is inside the dialog and"
                    f" takes a click, „Dotyczy” clears „Maks dostanie”, and the dialog fits the window ({wrong})",
                )
                page.keyboard.press("Escape")
                expect(dialog).to_have_count(0)
    finally:
        page.set_viewport_size(screen)
    toggle_theme(page)
    run.check(sorted(themes) == ["ciemny", "jasny"], "the low windows were checked in both themes")


def _low_with_list(run: Run, page: Page, dialog: Locator, choices: Locator, what: str) -> None:
    """In the low window the fields scroll with „Dotyczy” at its switch and one row of the list, and the checked row,
    scrolled into view, is wholly shown."""

    screen = page.viewport_size
    assert screen is not None
    try:
        page.set_viewport_size(LOW_WINDOW)
        where = f"{LOW_WINDOW['width']}×{LOW_WINDOW['height']} {what}"
        until(
            lambda: (box := dialog.bounding_box()) is not None and box["y"] >= 0
            and box["y"] + box["height"] <= LOW_WINDOW["height"],
            f"at {where} the open dialog fits the window",
        )
        run.check(_scrolls_at_least(run, dialog, where), f"at {where} the fields scroll")
        row = choices.locator('label:has([role="radio"][aria-checked="true"])')
        row.scroll_into_view_if_needed()
        shown = row.evaluate(WHOLLY_SHOWN)
        run.check(shown["shown"], f"at {where} the checked row scrolled into view is wholly shown ({shown})")
    finally:
        page.set_viewport_size(screen)


def _drive_full_window_list(run: Run, page: Page) -> None:
    run.step(FEATURE, "uwaga-pelne-okno-lista")
    # Centrum zapamiętuje Uruchomienia z Centrum we własnym pliku obok ustawień: napęd dopisuje je przez właściciela
    # pliku (run_origins), więc zmiana jego formatu nie zostawia Centrum pliku, którego ono nie przeczyta. Nazwę pliku
    # czyta następne Wydanie, więc napęd ma ją z kopii (docs/agents/skille.md, „Co wyrocznia bierze z src”).
    config = Path(run.fixture["settings"]).parent
    registry = config / CENTRUM_RUNS_FILE
    before = read_bytes(registry) if registry.exists() else None
    processes: tuple[tuple[ProcessKey, Process[Any, Any, Any]], ...] = (
        ("settlement", SETTLEMENT),
        ("preparation", PREPARATION),
    )
    metrics = {key: MetricsStore(Path(run.fixture["metrics"][key]), process.counter_names) for key, process in processes}
    started = [(record["started_at"], key) for key, store in metrics.items() for record in store.read()]
    newest = sorted(started, reverse=True)[:FULL_LIST_RUNS]
    run.check(len(newest) == FULL_LIST_RUNS, f"the fixture's metrics files hold at least {FULL_LIST_RUNS} runs ({len(newest)})")
    try:
        origins = CentrumRuns(config)
        for number, (at, key) in enumerate(newest):
            moment = datetime.fromisoformat(at)
            origins.remember(key, f"uwaga-lista-{number}", metrics[key], moment, moment)
        run.check(registry.exists(), f"Centrum keeps its Uruchomienia in config/{CENTRUM_RUNS_FILE}")
        dialog = _open(page)
        _scope(dialog, "Do Uruchomienia").click()
        choices = dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True)
        until(
            lambda: choices.get_by_role("radio").count() >= FULL_LIST_RUNS,
            f"the list shows at least {FULL_LIST_RUNS} Uruchomienia from Centrum",
        )
        choices.get_by_role("radio").first.click()
        _write(dialog, *LOW_NOTES["lines"])
        send = dialog.get_by_role("button", name="Wyślij", exact=True)
        expect(send).to_be_enabled()
        figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
        kept = figure.evaluate(KEPT)
        run.check(
            kept["list"] < kept["listNatural"] - 1 and abs(kept["dotyczy"] - kept["figure"]) <= 0.01,
            "at the full window the list gives up height and „Dotyczy” with it keeps the same share of its height"
            f" as „Maks dostanie”, as on main ({kept})",
        )
        run.check(
            not _scrolls_at_least(run, dialog, "the full window with the list"),
            "at the full window with the list the fields do not scroll",
        )
        parts = {
            "the checked row": choices.locator('label:has([role="radio"][aria-checked="true"])'),
            "the switch „Dotyczy”": dialog.get_by_role("group", name="Dotyczy", exact=True),
            "the caption „Maks dostanie”": figure.get_by_text("Maks dostanie", exact=True),
            "„Wyślij”": send,
        }
        hidden = {name: shown for name, part in parts.items() if not (shown := part.evaluate(WHOLLY_SHOWN))["shown"]}
        run.check(hidden == {}, f"at the full window the fields do not scroll: all of {list(parts)} are on screen ({hidden})")
        run.capture(page, "179-uwaga-pelne-okno-lista", full_page=False)
        _low_with_list(run, page, dialog, choices, "with the list")
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
    finally:
        if before is None:
            remove(registry, missing_ok=True)
        else:
            registry.write_bytes(before)


def drive(run: Run, page: Page) -> None:
    config = run.config
    key_file = config / REPORT_KEY_FILE
    box = run.box
    drop_report_key(key_file, missing_ok=True)
    notes_before = len(_notes(config))
    issues_before = len(box_issues(run, LABEL))
    run.check(queued_posts(run, LABEL, leaving=True) == [], "the skrzynka queue is empty before the first Uwaga")

    run.step(FEATURE, "uwaga-ikona")
    for page_id, heading in PAGES.items():
        page.goto(run.url + f"#/{page_id}")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        write = page.get_by_role("button", name=WRITE, exact=True)
        bell = page.locator("header").get_by_role("button", name="Powiadomienia", exact=False)
        expect(write).to_be_visible()
        write_box, bell_box = write.bounding_box(), bell.bounding_box()
        run.check(
            write_box is not None and bell_box is not None and write_box["x"] < bell_box["x"],
            f"{heading}: the header has „{WRITE}” left of the bell Powiadomienia",
        )
    page.get_by_role("button", name=WRITE, exact=True).hover()
    expect(page.get_by_text(WRITE, exact=True)).to_be_visible()
    run.capture(page, "170-uwaga-ikona-w-naglowku")
    header = page.locator("header").first.bounding_box()
    assert header is not None
    run.capture(
        page,
        "170b-uwaga-ikona-zblizenie",
        clip={"x": header["x"] + header["width"] - 360, "y": header["y"], "width": 360, "height": header["height"] + 40},
    )

    run.step(FEATURE, "uwaga-puste-okno")
    dialog = _open(page)
    figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
    title_box = dialog.get_by_role("textbox", name="Tytuł", exact=True)
    body_box = dialog.get_by_role("textbox", name="Treść (niekonieczna)", exact=True)
    send = dialog.get_by_role("button", name="Wyślij", exact=True)
    expect(title_box).to_be_focused()
    run.check(
        (title_box.get_attribute("maxlength"), body_box.get_attribute("maxlength")) == ("120", "10000"),
        "the fields take their limits from the contract (Tytuł 120, Treść 10000)",
    )
    run.check(
        title_box.get_attribute("placeholder") == "Np. Brakuje kolumny z kilometrami",
        "Tytuł shows the prototype's example as its placeholder",
    )
    expect(send).to_be_disabled()
    expect(_scope(dialog, "Ogólna")).to_have_attribute("aria-pressed", "true")
    expect(dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True)).to_have_count(0)
    empty = _draft(run, "", "", "uwaga-szkic-pusty")
    until(lambda: _shown(figure)[1] == empty["body"], "„Maks dostanie” shows the server's draft of an empty Uwaga")
    run.check(_shown(figure)[0] == "Tytuł" and empty["title"] == "", "with no Tytuł the figure shows the placeholder")
    _write(dialog, "   ", "")
    expect(send).to_be_disabled()
    title_box.fill("")
    run.capture(page, "171-uwaga-puste-okno")

    run.step(FEATURE, "uwaga-dlugi-tekst")
    screen = page.viewport_size
    assert screen is not None
    page.set_viewport_size(SMALL_SCREEN)
    try:
        _write(dialog, *LONG)
        _shows(run, figure, _draft(run, *LONG, "uwaga-szkic-dlugi"), "„Maks dostanie” shows the draft of the long text")
        outside = _overflowing(page, dialog)
        run.check(outside == [], f"the form, its preview and „Wyślij” stay inside the dialog and on screen ({outside})")
        run.capture(page, "172-uwaga-dlugi-tekst")
    finally:
        page.set_viewport_size(screen)
    _write(dialog, "", "")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _drive_low_windows(run, page)
    _drive_full_window_list(run, page)
    dialog = _open(page)

    run.step(FEATURE, "uwaga-szkic-po-bledzie")

    def failed_draft(request: Request) -> bool:
        return request.url.endswith("/api/dad-notes/draft") and request.post_data_json == {
            "title": FIRST[0],
            "body": FIRST[1],
            "run_id": None,
        }

    page.route("**/api/dad-notes/draft", lambda route: route.abort())
    try:
        _write(dialog, *FIRST)
        try:
            # The first failure may come before the wait starts; then the second wait catches the next retry.
            page.wait_for_event("requestfailed", predicate=failed_draft)
            page.wait_for_event("requestfailed", predicate=failed_draft)
            retried = True
        except PlaywrightTimeoutError:
            retried = False
        run.check(retried, "a failed draft request is asked again without Dad typing")
        expect(send).to_be_disabled()
        expect(page.get_by_role("alert")).to_have_count(0)
        expect(error_toasts(page)).to_have_count(0)
    finally:
        page.unroute("**/api/dad-notes/draft")
    expect(send).to_be_enabled()
    run.check(send.is_enabled(), "once Centrum answers the draft, „Wyślij” works without Dad typing again, and no Komunikat showed")

    run.step(FEATURE, "uwaga-bez-klucza")
    _write(dialog, *FIRST)
    first = _draft(run, *FIRST, "uwaga-szkic-pierwsza")
    _shows(run, figure, first, "„Maks dostanie” shows exactly the server's draft of the typed Uwaga")
    run.check(first["title"] == FIRST[0] and first["body"].startswith(FIRST[1] + "\n\n"), "the draft holds Dad's text")
    expect(send).to_be_enabled()
    run.capture(page, "173-uwaga-wypelniona")
    _scope(dialog, "Do Uruchomienia").click()
    if _note_runs(run, None, "uwaga-uruchomienia-z-naglowka"):
        expect(dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True).get_by_role("radio", checked=True)).to_have_count(0)
    else:
        expect(dialog.get_by_text(NO_RUNS, exact=True)).to_be_visible()
    expect(send).to_be_disabled()
    run.check(True, "„Do Uruchomienia” without a checked Uruchomienie keeps Wyślij disabled (no Uruchomienia: the calm sentence)")
    run.capture(page, "173b-uwaga-bez-wybranego-uruchomienia", full_page=False)
    _scope(dialog, "Ogólna").click()
    _shows(run, figure, first, "back to Ogólna the figure shows the general draft again")
    expect(send).to_be_enabled()
    answer = _send(page, send)
    run.check(answer == {"state": "queued", "waits_for": "key"}, f"without a key the server says the Uwaga waits for the token ({answer})")
    expect(dialog.get_by_role("status")).to_have_text(FOR_KEY)
    run.check(dialog.get_by_role("status").locator("svg").count() == 1, "the sentence has the error icon")
    expect(dialog.get_by_text("Wyślę do Maksa, gdy będzie internet.", exact=True)).to_have_count(0)
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(error_toasts(page)).to_have_count(0)
    run.capture(page, "174-uwaga-token-nie-dziala")
    [waiting] = queued_posts(run, LABEL)
    run.check(
        waiting["target"] == {"kind": "new_issue", "label": LABEL, "title": first["title"]}
        and waiting["parts"] == [first["body"]],
        "one queue file labelled uwaga-taty holds the issue the figure showed",
    )
    notes = _notes(config)
    run.check(
        len(notes) == notes_before + 1 and notes[-1]["title"] == first["title"] and notes[-1]["number"] is None,
        f"config/{DAD_CASES_FILE} keeps the Uwaga's title without an issue number",
    )
    run.check(
        f"skrzynka-czeka etykieta={LABEL} okres=bez-okresu przyczyna=brak-klucza" in run.log(),
        "without a key the Centrum log says the Uwaga waits",
    )
    run.check(len(box_issues(run, LABEL)) == issues_before, "nothing reached the skrzynka")
    _close(dialog)

    run.step(FEATURE, "uwaga-wyslana")
    print("  harness: Maks writes the key; the skrzynka answers each issue after a pause", flush=True)
    key_file.write_text(REPORT_KEY + "\n", encoding="utf-8")
    pacing = Pace.REPORT_BOX.set(run.root, BOX_PACING_MS)
    try:
        dialog = _open(page)
        figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
        title_box = dialog.get_by_role("textbox", name="Tytuł", exact=True)
        body_box = dialog.get_by_role("textbox", name="Treść (niekonieczna)", exact=True)
        send = dialog.get_by_role("button", name="Wyślij", exact=True)
        run.check(
            (title_box.input_value(), body_box.input_value()) == ("", ""), "a new opening starts an empty Uwaga"
        )
        _write(dialog, *SECOND)
        second = _draft(run, *SECOND, "uwaga-szkic-druga")
        _shows(run, figure, second, "„Maks dostanie” shows the server's draft of an Uwaga without Treść")
        send.click()
        expect(dialog.get_by_role("button", name="Trwa Wyślij", exact=True)).to_be_disabled()
        run.capture(page, "175-uwaga-wysylanie", live=True)
        expect(dialog.get_by_role("status")).to_have_text(SENT, timeout=Budget.SEND.ms)
    finally:
        remove(pacing, missing_ok=True)
    run.capture(page, "176-uwaga-wyslana")
    issues = box_issues(run, LABEL)
    (run.evidence / "api" / "uwaga-skrzynka.json").write_text(
        json.dumps(
            [{key: issue[key] for key in ("number", "title", "body", "labels")} for issue in issues[issues_before:]],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run.check(
        [(issue["title"], issue["body"]) for issue in issues[issues_before:]]
        == [(first["title"], first["body"]), (second["title"], second["body"])],
        "the skrzynka has both Uwagi as uwaga-taty issues, each exactly as its figure showed it",
    )
    until(lambda: queued_posts(run, LABEL, leaving=True) == [], "the waiting Uwaga left the queue in the same pass")
    notes = _notes(config)
    run.check(
        [note["number"] for note in notes[notes_before:]] == [issue["number"] for issue in issues[issues_before:]],
        f"config/{DAD_CASES_FILE} has both issue numbers",
    )
    log = run.log()
    run.check(
        all(text not in log for text in (REPORT_KEY, FIRST[0], FIRST[1].splitlines()[0], SECOND[0])),
        "the Centrum log has neither the key nor the text of an Uwaga",
    )
    run.check(REPORT_KEY not in page.content(), "the key never reaches the browser")
    _close(dialog)
    try:
        _drive_pinned(run, page, config, box)
    finally:
        drop_report_key(key_file)


def _send(page: Page, send: Locator) -> object:
    """Dad clicks „Wyślij”; the server's answer to it."""

    with page.expect_response(lambda response: response.url.endswith("/api/dad-notes") and response.request.method == "POST") as sent:
        send.click()
    return sent.value.json()


def _drive_refused(run: Run, page: Page, config: Path, box: Path) -> list[Path]:
    """The skrzynka rejects an Uwaga's content: Dad is told to contact Maks; the queue files that keep it."""

    run.step(FEATURE, "uwaga-odrzucona")
    rejecting = rejects(run.root, LABEL)
    print("  harness: the skrzynka rejects the content of every new Uwaga taty", flush=True)
    rejecting.touch()
    try:
        dialog = _open(page)
        _write(dialog, *REFUSED)
        _shows(run, dialog.get_by_role("figure", name="Co dostanie Maks", exact=True), _draft(run, *REFUSED, "uwaga-szkic-odrzucona"), "„Maks dostanie” shows the draft")
        issues_before = len(box_issues(run, LABEL))
        answer = _send(page, dialog.get_by_role("button", name="Wyślij", exact=True))
        run.check(answer == {"state": "rejected"}, f"the server says the skrzynka rejected the Uwaga ({answer})")
        status = dialog.get_by_role("status")
        expect(status).to_have_text(REFUSED_CONTENT)
        run.check(status.locator("svg").count() == 1, "the sentence has the error icon")
        expect(error_toasts(page)).to_have_count(0)
        run.capture(page, "174b-uwaga-odrzucona", full_page=False)
        waiting = [
            path for path in queued(run, LABEL) if read_json(path)["target"].get("title") == REFUSED[0]
        ]
        run.check(len(waiting) == 1, "the rejected Uwaga stays in the queue")
        run.check(len(box_issues(run, LABEL)) == issues_before, "the skrzynka got no new Uwaga")
        _close(dialog)
        page.locator("header").get_by_role("button", name="Powiadomienia", exact=False).click()
        row = page.get_by_role("list", name="Powiadomienia").get_by_role("listitem", name=f"Uwaga: {REFUSED[0]}")
        expect(row).to_contain_text(REFUSED_CONTENT)
        run.capture(page, "174c-uwaga-odrzucona-powiadomienia")
    finally:
        remove(rejecting, missing_ok=True)
    return waiting


def _note_runs(run: Run, selected: str | None, name: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({} if selected is None else {"selected": selected})
    with urllib.request.urlopen(run.url.rstrip("/") + f"/api/dad-notes/runs?{query}", timeout=Budget.SCREEN.value) as response:
        runs = json.load(response)
    (run.evidence / "api" / f"{name}.json").write_text(
        json.dumps(runs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    assert isinstance(runs, list)
    return runs


def _result_word(entry: dict[str, Any]) -> str:
    if entry["result"] == "BLAD_KRYTYCZNY":
        return "Błąd" if entry["stop_kind"] == "for_maks" else "Zatrzymano"
    return {"OK": "OK", "WYMAGA_SPRAWDZENIA": "Do sprawdzenia"}[entry["result"]]


def _offers(run: Run, choices: Locator, offered: list[dict[str, Any]], checked: str) -> None:
    rows = choices.locator("label")
    until(lambda: rows.count() == len(offered), f"the list shows the server's {len(offered)} Uruchomienia")
    texts = [row.inner_text() for row in rows.all()]
    run.check(
        all(
            entry["process_label"] in text
            and f"{entry['period']} · {MODES[entry['mode']]} · {local_time(entry['started_at'])}" in text
            and _result_word(entry) in text
            for entry, text in zip(offered, texts, strict=True)
        ),
        "each row shows process, period, podgląd or zapis, date and result, newest first",
    )
    states = [radio.get_attribute("aria-checked") for radio in choices.get_by_role("radio").all()]
    run.check(
        states == ["true" if entry["run_id"] == checked else "false" for entry in offered],
        f"exactly the Uruchomienie {checked} is checked"
        if checked in [entry["run_id"] for entry in offered]
        else f"no Uruchomienie is checked ({checked} is not in the list)",
    )


def _logs_comment(run: Run, run_id: str) -> str | None:
    for thread in box_issues(run, LOGS_LABEL):
        for index, comment in enumerate(thread.get("comments", []), start=1):
            if f"- Uruchomienie: {run_id}," in comment:
                return comment_address(thread["number"], index)
    return None


def _scope(dialog: Locator, option: str) -> Locator:
    return dialog.get_by_role("group", name="Dotyczy", exact=True).get_by_role("button", name=option, exact=True)


def _opened_about(run: Run, page: Page, run_id: str, name: str) -> tuple[Locator, list[dict[str, Any]]]:
    dialog = page.get_by_role("dialog", name=WRITE, exact=True)
    expect(dialog).to_be_visible()
    run.check(dialog.get_by_role("textbox", name="Tytuł", exact=True).input_value() == "", "a new, empty Uwaga")
    expect(_scope(dialog, "Do Uruchomienia")).to_have_attribute("aria-pressed", "true")
    offered = _note_runs(run, run_id, name)
    run.check(run_id in [entry["run_id"] for entry in offered], "the server offers the Uruchomienie it was opened from")
    _offers(run, dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True), offered, run_id)
    box, viewport = dialog.bounding_box(), page.viewport_size
    run.check(
        box is not None and viewport is not None and box["y"] >= 0 and box["y"] + box["height"] <= viewport["height"],
        "the whole dialog fits the window; a long list scrolls inside it",
    )
    return dialog, offered


def _drive_pinned(run: Run, page: Page, config: Path, box: Path) -> None:
    period = run.fixture["settlement"]["needs_check"]

    run.step(FEATURE, "uwaga-przycisk-na-karcie")
    page.goto(run.url)
    ensure_files_set(run, page)
    was_dark = switch_theme(page, "jasny")
    page.goto(run.url + "#/uruchomienia")
    if ended_run_shown(current_run(run, "uwaga-przed-podgladem")):
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    view = finished_view(run, "uwaga-podglad")
    run_id = str(view["run"]["id"])
    card = page.get_by_role("region", name="Podgląd na żywo")
    about = card.get_by_role("button", name=ABOUT_RUN, exact=True)
    expect(about).to_have_count(1)
    about_box = about.bounding_box()
    new_box = card.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).bounding_box()
    run.check(
        about_box is not None and new_box is not None and new_box["x"] < about_box["x"],
        f"the finished card has „{ABOUT_RUN}” right of „Nowe Uruchomienie procesu”",
    )
    about.hover()
    expect(page.get_by_text(ABOUT_RUN, exact=True)).to_be_visible()
    until(
        lambda: _logs_comment(run, run_id) is not None,
        "with the key the preview's Logi reached the skrzynka at the end of the Uruchomienie",
        Budget.BACKGROUND,
    )
    run.capture(page, "190-uwaga-przycisk-na-karcie")

    run.step(FEATURE, "uwaga-z-karty")
    about.click()
    dialog, offered = _opened_about(run, page, run_id, "uwaga-uruchomienia-z-karty")
    figure = dialog.get_by_role("figure", name="Co dostanie Maks", exact=True)
    send = dialog.get_by_role("button", name="Wyślij", exact=True)
    expect(send).to_be_disabled()
    run.capture(page, "191-uwaga-z-karty", full_page=False)

    run.step(FEATURE, "uwaga-przypieta")
    _write(dialog, *PINNED)
    pinned = _draft(run, *PINNED, "uwaga-szkic-przypieta", run_id=run_id)
    _shows(run, figure, pinned, "„Maks dostanie” shows exactly the server's draft of the Uwaga pinned to the preview")
    [entry] = [entry for entry in offered if entry["run_id"] == run_id]
    run.check(
        f"Uruchomienie: {entry['process_label']} · {period} · podgląd · do sprawdzenia · {_server_time(entry['started_at'])}"
        f" · wersja narzędzia " in pinned["body"],
        "the pinned Uwaga carries process, period, mode, result and date of the preview",
    )
    logs = _logs_comment(run, run_id)
    run.check(
        LOGS_LINK.findall(pinned["body"]) == [logs],
        "the pinned Uwaga links [Logi Uruchomienia] to the first comment of the preview's Logi in the skrzynka",
    )
    run.check(
        _shown(figure)[1].splitlines()[-1] == "Logi Uruchomienia" and str(logs) not in figure.inner_text(),
        "„Maks dostanie” shows the link as the words Logi Uruchomienia, without the address",
    )
    expect(send).to_be_enabled()
    run.capture(page, "192-uwaga-przypieta", full_page=False)

    run.step(FEATURE, "uwaga-ogolna-i-z-powrotem")
    _scope(dialog, "Ogólna").click()
    expect(dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True)).to_have_count(0)
    general = _draft(run, *PINNED, "uwaga-szkic-ogolna-z-karty")
    _shows(run, figure, general, "with Ogólna the figure shows the server's draft without the Uruchomienie")
    run.check(
        general["body"].splitlines()[-1].startswith("Uwaga ogólna · wersja narzędzia")
        and "Logi Uruchomienia" not in general["body"],
        "the general Uwaga ends with the general footer and has no Logi",
    )
    run.capture(page, "193-uwaga-ogolna-z-karty", full_page=False)
    _scope(dialog, "Do Uruchomienia").click()
    _offers(run, dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True), offered, run_id)
    _shows(run, figure, pinned, "back to Do Uruchomienia the same Uruchomienie is checked and the figure pinned again")

    run.step(FEATURE, "uwaga-przypieta-wyslana")
    issues_before = len(box_issues(run, LABEL))
    send.click()
    expect(dialog.get_by_role("status")).to_have_text(SENT, timeout=Budget.SEND.ms)
    expect(error_toasts(page)).to_have_count(0)
    new = box_issues(run, LABEL)[issues_before:]
    (run.evidence / "api" / "uwaga-przypieta-skrzynka.json").write_text(
        json.dumps(
            [{key: issue[key] for key in ("number", "title", "body", "labels")} for issue in new],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run.check(
        [(issue["title"], issue["body"]) for issue in new] == [(pinned["title"], pinned["body"])],
        "the skrzynka has the pinned Uwaga as one uwaga-taty issue, exactly as its figure's draft",
    )
    run.check(
        LOGS_LINK.findall(str(new[0]["body"])) == [logs],
        "its link Logi Uruchomienia leads to the first comment of the preview's Logi",
    )
    note = _notes(config)[-1]
    run.check(
        (note["title"], note["number"], note["run_id"]) == (pinned["title"], new[0]["number"], run_id),
        f"config/{DAD_CASES_FILE} keeps the issue number and the Uruchomienie of the pinned Uwaga",
    )
    _close(dialog)

    run.step(FEATURE, "uwaga-z-historii")
    page.get_by_role("tab", name="Historia", exact=True).click()
    history = page.get_by_role("table", name="Historia Uruchomień procesu")
    expect(history).to_be_visible()
    older = page.get_by_role("button", name="Pokaż starsze", exact=True)
    while older.count() > 0:
        older.click()
    metrics = run.api("/api/metrics", "uwaga-historia")["runs"]
    assert isinstance(metrics, list)
    shown = sorted(metrics, key=lambda entry: datetime.fromisoformat(entry["started_at"]), reverse=True)
    rows = history_rows(page)
    expect(rows).to_have_count(1 + len(shown))
    buttons = [rows.nth(index).get_by_role("button", name=ABOUT_RUN, exact=True).count() for index in range(1, len(shown) + 1)]
    run.check(
        buttons == [0 if entry["run_id"] is None else 1 for entry in shown] and 0 in buttons and 1 in buttons,
        f"only the {buttons.count(1)} rows of Uruchomienia from Centrum with a run id have „{ABOUT_RUN}”",
    )
    oldest = max(index for index, entry in enumerate(shown) if entry["run_id"] is not None)
    target = str(shown[oldest]["run_id"])
    about = rows.nth(oldest + 1).get_by_role("button", name=ABOUT_RUN, exact=True)
    about.hover()
    expect(page.get_by_text(ABOUT_RUN, exact=True)).to_be_visible()
    run.capture(page, "194-uwaga-historia")
    about.click()
    dialog, _ = _opened_about(run, page, target, "uwaga-uruchomienia-z-historii")
    run.capture(page, "195-uwaga-z-historii", full_page=False)
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    _laptop(run, page, about, target)
    _not_in_history(run, page, period)
    if was_dark:
        switch_theme(page, "ciemny")
    _drive_missing_logs(run, page, config, box, period)


def _laptop(run: Run, page: Page, about: Locator, target: str) -> None:
    viewport = page.viewport_size
    assert viewport is not None
    page.set_viewport_size(LAPTOP)
    try:
        about.click()
        dialog, _ = _opened_about(run, page, target, "uwaga-uruchomienia-laptop")
        choices = dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True)
        checked = choices.locator('label:has([role="radio"][aria-checked="true"])')
        send = dialog.get_by_role("button", name="Wyślij", exact=True)
        expect(checked).to_have_count(1)
        # The server's draft makes „Maks dostanie” taller, and the list gives up height for it.
        expect(dialog.get_by_role("figure", name="Co dostanie Maks", exact=True).locator("p")).to_have_count(2)
        scrolled = dialog.evaluate("element => element.scrollTop")
        row, button = checked.evaluate(WHOLLY_SHOWN), send.evaluate(WHOLLY_SHOWN)
        run.check(
            scrolled == 0 and row["shown"] and button["shown"],
            f"at {LAPTOP['width']}×{LAPTOP['height']} with the draft in „Maks dostanie” the checked oldest row and „Wyślij”"
            " are on screen without scrolling"
            f" (dialog scrollTop {scrolled}, row {row}, Wyślij {button})",
        )
        run.capture(page, "196-uwaga-z-historii-laptop", full_page=False)
        page.keyboard.press("Escape")
        expect(dialog).to_have_count(0)
    finally:
        page.set_viewport_size(viewport)


def _not_in_history(run: Run, page: Page, period: str) -> None:
    run.step(FEATURE, "uwaga-spoza-historii")
    metrics = Path(run.fixture["metrics"]["settlement"])
    records, mode = read_bytes(metrics), metrics.stat().st_mode
    page.goto(run.url + "#/uruchomienia")
    page.get_by_role("tab", name="Uruchomienie", exact=True).click()
    if ended_run_shown(current_run(run, "uwaga-przed-podgladem-bez-metryk")):
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)
    print("  harness: the metrics file of Przebieg rozliczeń is read-only, so the preview's record is not written", flush=True)
    metrics.chmod(stat.S_IREAD)
    try:
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
        finished_result(run, "uwaga-podglad-bez-metryk")
    finally:
        metrics.chmod(mode)
    run_id = str(read_json(run.evidence / "api" / "uwaga-podglad-bez-metryk.json")["run"]["id"])
    run.check(read_bytes(metrics) == records, "the preview added no record to the read-only metrics file")
    offered = _note_runs(run, run_id, "uwaga-uruchomienia-spoza-historii")
    run.check(
        offered != [] and run_id not in [entry["run_id"] for entry in offered],
        "the server offers other Uruchomienia, but not the preview without a metrics record",
    )
    page.get_by_role("region", name="Podgląd na żywo").get_by_role("button", name=ABOUT_RUN, exact=True).click()
    dialog = page.get_by_role("dialog", name=WRITE, exact=True)
    expect(_scope(dialog, "Do Uruchomienia")).to_have_attribute("aria-pressed", "true")
    sentence = dialog.get_by_text(NOT_IN_HISTORY, exact=True)
    choices = dialog.get_by_role("radiogroup", name="Uruchomienie", exact=True)
    expect(sentence).to_be_visible()
    _offers(run, choices, offered, run_id)
    send = dialog.get_by_role("button", name="Wyślij", exact=True)
    _write(dialog, *PINNED)
    expect(send).to_be_disabled()
    above, rows = sentence.bounding_box(), choices.bounding_box()
    run.check(
        above is not None and rows is not None and above["y"] + above["height"] <= rows["y"],
        f"the sentence „{NOT_IN_HISTORY}” stands above the list, nothing is checked and Wyślij stays disabled",
    )
    run.capture(page, "197-uwaga-spoza-historii", full_page=False)
    choices.get_by_role("radio").first.click()
    expect(choices.get_by_role("radio").first).to_have_attribute("aria-checked", "true")
    expect(sentence).to_be_visible()
    run.check(True, "checking another Uruchomienie keeps the sentence above the list, so the list does not jump")
    _shows(
        run,
        dialog.get_by_role("figure", name="Co dostanie Maks", exact=True),
        _draft(run, *PINNED, "uwaga-szkic-spoza-historii", run_id=str(offered[0]["run_id"])),
        "the figure shows the draft pinned to the newest Uruchomienie of the list",
    )
    expect(send).to_be_enabled()
    _low_with_list(run, page, dialog, choices, "with the sentence above the list")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)


def _waiting_logs(run_id: str) -> str:
    return f"Logi Uruchomienia: w drodze (Uruchomienie {run_id})"


def _preview(run: Run, page: Page, period: str, name: str) -> str:
    """A new `Podgląd bez zapisu` of Przebieg rozliczeń from tab Uruchomienie; its run id."""

    page.goto(run.url + "#/uruchomienia")
    page.get_by_role("tab", name="Uruchomienie", exact=True).click()
    if ended_run_shown(current_run(run, f"{name}-przed")):
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    page.get_by_role("radio", name="Przebieg rozliczeń").click()
    expect(page.get_by_role("combobox", name="Okres")).to_contain_text(period)
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(page.get_by_label("Wynik")).to_contain_text("Podgląd wymaga sprawdzenia · nic nie zapisano")
    return str(finished_view(run, name)["run"]["id"])


def _send_pinned(run: Run, page: Page, box: Path, run_id: str, note: tuple[str, str], name: str) -> tuple[str, dict[str, Any]]:
    """Dad sends ``note`` from the finished card; the body „Maks dostanie” showed and the new skrzynka issue."""

    page.get_by_role("region", name="Podgląd na żywo").get_by_role("button", name=ABOUT_RUN, exact=True).click()
    dialog, _ = _opened_about(run, page, run_id, f"uwaga-uruchomienia-{name}")
    _write(dialog, *note)
    draft = _draft(run, *note, f"uwaga-szkic-{name}", run_id=run_id)
    _shows(run, dialog.get_by_role("figure", name="Co dostanie Maks", exact=True), draft, "„Maks dostanie” shows the draft pinned to the preview")
    run.check(draft["body"].endswith("\n" + _waiting_logs(run_id)), "the draft says the preview's Logi are on their way")
    issues_before = len(box_issues(run, LABEL))
    dialog.get_by_role("button", name="Wyślij", exact=True).click()
    expect(dialog.get_by_role("status")).to_have_text(SENT, timeout=Budget.SEND.ms)
    expect(error_toasts(page)).to_have_count(0)
    new = box_issues(run, LABEL)[issues_before:]
    run.check(
        [issue["title"] for issue in new] == [draft["title"]], "the skrzynka has the pinned Uwaga as one new uwaga-taty issue"
    )
    _close(dialog)
    return draft["body"], new[0]


def _issue(run: Run, number: int) -> dict[str, Any]:
    issue = read_json(issue_file(run.root, number))
    assert isinstance(issue, dict)
    return issue


def _as_maks_sees(run: Run, page: Page, issue: dict[str, Any], name: str) -> None:
    """The skrzynka issue as GitHub shows it to Maks, each Markdown link as its text, for the screenshot."""

    print(f"  harness: the drive shows skrzynka issue #{issue['number']} the way GitHub shows it to Maks", flush=True)

    def shown(text: str) -> str:
        return MARKDOWN_LINK.sub(r'<a href="\2">\1</a>', html.escape(text, quote=False)).replace("\n", "<br>")

    comments = "".join(f'<div class="komentarz">{shown(comment)}</div>' for comment in issue.get("comments", []))
    maks = page.context.new_page()
    try:
        maks.set_content(
            '<html lang="pl"><body style="font: 15px/1.5 system-ui; max-width: 760px; margin: 32px auto">'
            "<style>.komentarz { border: 1px solid #d0d7de; border-radius: 6px; padding: 8px 12px; margin-top: 12px }</style>"
            f"<h1>{html.escape(issue['title'])} #{issue['number']}</h1><p>{' '.join(issue['labels'])}</p>"
            f'<div class="komentarz">{shown(issue["body"])}</div>{comments}</body></html>'
        )
        run.capture(maks, name)
    finally:
        maks.close()


def _drive_missing_logs(run: Run, page: Page, config: Path, box: Path, period: str) -> None:
    run.step(FEATURE, "uwaga-logi-odrzucone")
    rejecting = rejects(run.root, LOGS_LABEL)
    rejection = f"skrzynka-czeka etykieta={LOGS_LABEL} okres={period} przyczyna=odmowa-tresci"
    rejections = run.log().count(rejection)
    print("  harness: the skrzynka rejects the content of Logi Uruchomienia, as GitHub rejects a body too long", flush=True)
    rejecting.touch()
    try:
        run_id = _preview(run, page, period, "uwaga-podglad-logi-odrzucone")
        until(
            lambda: run.log().count(rejection) == rejections + 1, "the Centrum log says the skrzynka rejected the preview's Logi"
        )
        run.check(len(queued(run, LOGS_LABEL, run_id)) == 1, "the rejected Logi wait in the queue")
        body, issue = _send_pinned(run, page, box, run_id, REJECTED, "logi-odrzucone")
        rejected_line = (
            f"Logi Uruchomienia: nie dotarły, Skrzynka odrzuciła ich treść (Uruchomienie {run_id}). "
            "Odnośnik przyjdzie w komentarzu, gdy dotrą."
        )
        run.check(
            issue["body"] == body.removesuffix(_waiting_logs(run_id)) + rejected_line,
            "the sent Uwaga says its Logi did not arrive because the skrzynka rejected them, with the Uruchomienie's id",
        )
        until(
            lambda: [post["target"] for post in queued_posts(run, LABEL, run_id)]
            == [{"kind": "known_issue", "label": LABEL, "number": issue["number"]}],
            "a comment to the Uwaga's issue waits in the queue for the rejected Logi",
        )
        run.check(_issue(run, issue["number"]).get("comments", []) == [], "while the skrzynka rejects the Logi, the Uwaga has no comment")
        _as_maks_sees(run, page, _issue(run, issue["number"]), "198-uwaga-logi-odrzucone")
    finally:
        remove(rejecting, missing_ok=True)
    refused = _drive_refused(run, page, config, box)

    run.step(FEATURE, "uwaga-logi-dotarly")
    close_centrum(run, page)
    start_centrum(run, "uwaga-start-logi")
    until(
        lambda: queued(run, LOGS_LABEL, run_id, leaving=True) == queued(run, LABEL, run_id, leaving=True) == [],
        "at the start the skrzynka took the Logi and then the comment",
        Budget.WORK,
    )
    until(lambda: not any(path.exists() for path in refused), "at the start the queue tried the rejected Uwaga again", Budget.WORK)
    run.check(
        [(issue["title"], issue["body"]) for issue in box_issues(run, LABEL) if issue["title"] == REFUSED[0]]
        == [(REFUSED[0], read_json(run.evidence / "api" / "uwaga-szkic-odrzucona.json")["body"])],
        "once the skrzynka takes it, the rejected Uwaga is one issue, exactly as its figure showed it",
    )
    logs = _logs_comment(run, run_id)
    run.check(logs is not None, "the preview's Logi reached the skrzynka after the start")
    sent = _issue(run, issue["number"])
    run.check(
        sent.get("comments", []) == [f"[Logi Uruchomienia]({logs}) dotarły do Skrzynki po tej Uwadze (Uruchomienie {run_id})."],
        "the Uwaga's issue got exactly one comment, linking the first comment of the Logi",
    )
    _as_maks_sees(run, page, sent, "199-uwaga-logi-dotarly")

    run.step(FEATURE, "uwaga-logi-nie-powstaly")
    key_file = config / REPORT_KEY_FILE
    key = read_text(key_file)
    print("  harness: without the key the preview's Logi wait in the queue", flush=True)
    drop_report_key(key_file)
    try:
        page.reload()
        missing = _preview(run, page, period, "uwaga-podglad-bez-logow")
        until(lambda: len(queued(run, LOGS_LABEL, missing)) == 1, "the preview's Logi wait in the queue")
    finally:
        key_file.write_text(key, encoding="utf-8")
    print("  harness: Maks writes the key again; the Logi file leaves the queue, as when Centrum could not write it", flush=True)
    [logs_file] = queued(run, LOGS_LABEL, missing)
    logs_text = read_bytes(logs_file)
    remove(logs_file)
    try:
        body, issue = _send_pinned(run, page, box, missing, NO_LOGS, "bez-logow")
        run.check(
            issue["body"]
            == body.removesuffix(_waiting_logs(missing))
            + f"Logi Uruchomienia: nie powstały albo nie da się ich wysłać (Uruchomienie {missing})",
            "the sent Uwaga says its Logi were not made or cannot be sent, with the Uruchomienie's id",
        )
        until(lambda: queued(run, LABEL, missing, leaving=True) == [], "nothing of the Uwaga waits in the queue")
        run.check(_issue(run, issue["number"]).get("comments", []) == [], "an Uwaga whose Logi were never queued gets no comment")
        _as_maks_sees(run, page, issue, "200-uwaga-logi-nie-powstaly")
    finally:
        print("  harness: the Logi file goes back to the queue, so logi-uruchomienia finds every Uruchomienie's Logi in the skrzynka", flush=True)
        logs_file.write_bytes(logs_text)
