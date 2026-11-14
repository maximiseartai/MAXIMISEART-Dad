"""Drive features/pomiar-u-taty.md."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from playwright.sync_api import Page, Request, Response, Route, expect

from drive.common import PAGES, REPO_ROOT, Run, close_settings, ensure_files_set, read_json, settings_window
from drive.waiting import Budget, answer_late

FEATURE = "pomiar-u-taty"
SERVER_TIMING = re.compile(r"centrum;dur=\d+(\.\d+)?")
TIMED_REQUEST = re.compile(r"[a-zA-Z]+:\d+/\d+")
PERIOD_TOKEN = re.compile(r"\d{2}_\d{2}_\d{2}_\d{4}")
# The cold start before the menu clicks is Metryki, the last page of the menu, so its data is in the tab's cache
# when Dad comes back.
CACHED_IN_ROUTE = "metryki"
# Powiadomienia is a page without a sidebar entry: Dad reaches it with the header bell. Its cold start comes first,
# so Metryki stays the last one before the menu clicks.
NOTIFICATIONS = {"powiadomienia": "Powiadomienia"}
# A skeleton shows only once a read takes about 120 ms (index.css); a read held this long shows it for the rest.
SLOW_READ_S = 0.6
SKELETON_DELAY_MS = 120
CONTRACT = read_json(REPO_ROOT / "frontend" / "src" / "api" / "openapi.json")
# How many API requests one measurement of a view carries at most: the contract's `ViewTiming.requests`.
MAX_TIMED_REQUESTS = CONTRACT["components"]["schemas"]["ViewTiming"]["properties"]["requests"]["maxItems"]
# The contract's operation of every read (`GET`), by its address with `{…}` for any path segment.
READS = [
    (re.compile(re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(path))), operations["get"]["operationId"])
    for path, operations in CONTRACT["paths"].items()
    if "get" in operations
]


def _read_operation(url: str) -> str | None:
    path = urllib.parse.urlsplit(url).path
    return next((operation for address, operation in READS if address.fullmatch(path)), None)


def _timings(run: Run, since: int) -> list[dict[str, str]]:
    """Facts of every ``pomiar`` entry after the first ``since`` log entries."""

    return [entry.facts for entry in run.log_entries()[since:] if entry.event == "pomiar"]


def _wait_for_timings(run: Run, since: int, count: int, message: str) -> list[dict[str, str]]:
    run.wait_for(lambda: len(_timings(run, since)) >= count, message)
    return _timings(run, since)


def _okresy_measured(run: Run, page: Page) -> None:
    """Okresy opened cold and measured itself, so its entry stands before the entries of the next view."""

    page.goto("about:blank")
    since = len(run.log_entries())
    page.goto(f"{run.url}#/okresy")
    expect(page.get_by_role("heading", name="Okresy", level=1)).to_be_visible()
    _wait_for_timings(run, since, 1, "the cold start of Okresy is in the Centrum log")


def _check_requests(run: Run, timing: dict[str, str], where: str) -> None:
    requests = timing.get("zapytania", "").split(",")
    run.check(
        requests != [""] and all(TIMED_REQUEST.fullmatch(request) for request in requests),
        f"{where}: every API request has its operation, browser time and server time ({timing.get('zapytania')})",
    )


def drive(run: Run, page: Page) -> None:
    server_timings: list[dict[str, str]] = []

    def remember(response: Response) -> None:
        if "/api/" in response.url:
            server_timings.append({"url": response.url, "server-timing": response.headers.get("server-timing", "")})

    page.goto(run.url)
    ensure_files_set(run, page)

    run.step(FEATURE, "pomiar-zimny-start")
    page.on("response", remember)
    # The window Ustawienia on its address opens over the start page, which it hides: only the window is measured.
    since = len(run.log_entries())
    page.goto("about:blank")
    page.goto(f"{run.url}#/ustawienia/wzorce")
    expect(settings_window(page).get_by_role("list", name="Wzorce")).to_be_visible()
    [window] = _wait_for_timings(run, since, 1, "the cold start of Ustawienia is in the Centrum log")
    run.check(
        (window["widok"], window["strona"]) == ("zimny-start", "ustawienia"),
        "a cold start on #/ustawienia/wzorce logs the window, not the start page it hides",
    )
    _check_requests(run, window, "ustawienia")
    run.check("getConfiguration:" in window["zapytania"], "the window's entry holds its read of the configuration")
    for page_id, title in (NOTIFICATIONS | PAGES).items():
        since = len(run.log_entries())
        page.goto("about:blank")
        page.goto(f"{run.url}#/{page_id}")
        expect(page.get_by_role("heading", name=title, level=1)).to_be_visible()
        [timing] = _wait_for_timings(run, since, 1, f"the cold start of {title} is in the Centrum log")
        run.check(
            (timing["widok"], timing["strona"]) == ("zimny-start", page_id),
            f"the entry names the cold start of {page_id}",
        )
        run.check(
            all(timing.get(key, "").isdigit() for key in ("gotowe_ms", "fcp_ms", "szkielet_ms")),
            f"{page_id}: ready content, FCP and skeleton time in milliseconds",
        )
        _check_requests(run, timing, page_id)
    page.remove_listener("response", remember)

    run.step(FEATURE, "pomiar-server-timing")
    (run.evidence / "api" / "pomiar-server-timing.json").write_text(
        json.dumps(server_timings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    run.check(len(server_timings) > 0, "the browser read API answers during the cold starts")
    run.check(
        all(SERVER_TIMING.fullmatch(answer["server-timing"]) for answer in server_timings),
        "every API answer the browser got has Server-Timing with only the handling time",
    )

    run.step(FEATURE, "pomiar-przejscia-w-menu")
    since = len(run.log_entries())
    first, *rest = PAGES.items()
    route = [*rest, first]
    for clicked, (_, title) in enumerate(route, start=1):
        page.get_by_role("link", name=title, exact=True).click()
        expect(page.get_by_role("heading", name=title, level=1)).to_be_visible()
        # Dad reads the page until it is ready: a page left before its data came measures nothing.
        timings = _wait_for_timings(run, since, clicked, f"the menu click to {title} is in the Centrum log")
    run.check(
        [(timing["widok"], timing["strona"]) for timing in timings] == [("przejscie-w-menu", page_id) for page_id, _ in route],
        "one menu-click entry per page, in the order of the clicks",
    )
    run.check(all("fcp_ms" not in timing for timing in timings), "menu clicks carry no FCP")
    [(page_id, title)] = NOTIFICATIONS.items()
    bell_since = len(run.log_entries())
    page.locator("header").get_by_role("button", name=title, exact=False).click()
    expect(page.get_by_role("heading", name=title, level=1)).to_be_visible()
    [bell] = _wait_for_timings(run, bell_since, 1, "the click on the bell is in the Centrum log")
    run.check(
        (bell["widok"], bell["strona"]) == ("przejscie-w-menu", page_id) and "fcp_ms" not in bell,
        "the bell, outside the sidebar, logs a menu click to Powiadomienia without FCP",
    )
    for timing in timings:
        if timing["strona"] != CACHED_IN_ROUTE:
            _check_requests(run, timing, f"menu click to {timing['strona']}")
    [cached] = [timing for timing in timings if timing["strona"] == CACHED_IN_ROUTE]
    run.check(
        "zapytania" not in cached and cached["szkielet_ms"] == "0",
        f"back on {CACHED_IN_ROUTE}, the last data shows at once: no skeleton and no request before the content "
        f"(the read in the background ends later; gotowe_ms={cached['gotowe_ms']})",
    )

    run.step(FEATURE, "pomiar-szkielet-widoczny")
    _okresy_measured(run, page)

    def slow(route: Route) -> None:
        answer_late(route, SLOW_READ_S)

    page.route("**/api/configuration", slow)
    since = len(run.log_entries())
    try:
        page.evaluate("location.hash = '#/ustawienia/wzorce'")
        expect(settings_window(page).get_by_role("list", name="Wzorce")).to_be_visible()
        [timing] = _wait_for_timings(run, since, 1, "the opening of Ustawienia with a slow read is in the Centrum log")
    finally:
        page.unroute("**/api/configuration", slow)
    run.check(timing["strona"] == "ustawienia", f"the window measured itself ({timing['strona']})")
    close_settings(page)
    ready_ms, skeleton = int(timing["gotowe_ms"]), int(timing["szkielet_ms"])
    run.check(
        ready_ms >= SLOW_READ_S * 1000 and 0 < skeleton <= ready_ms - SKELETON_DELAY_MS + 20,
        f"a read held {SLOW_READ_S * 1000:.0f} ms (harness) shows the skeleton only after about {SKELETON_DELAY_MS} ms: "
        f"szkielet_ms={skeleton} of gotowe_ms={ready_ms}",
    )

    run.step(FEATURE, "pomiar-wiele-zapytan")
    _okresy_measured(run, page)
    held: list[str] = []

    def hold_first(route: Route) -> None:
        if held:
            route.continue_()
            return
        held.append(route.request.url)
        answer_late(route, SLOW_READ_S)

    # The read that made the view ready is the last one the page got before it sent the measurement, not always the
    # configuration: every return to the tab reads the settings again too.
    reads: list[str] = []
    measured: list[list[str]] = []

    def finished(request: Request) -> None:
        operation = _read_operation(request.url) if request.method == "GET" else None
        if operation is not None and not measured:
            reads.append(operation)

    def sent(request: Request) -> None:
        if request.method == "POST" and urllib.parse.urlsplit(request.url).path == "/api/view-timings":
            measured.append(list(reads))

    # The section Narzędzie reads Aktualizacja narzędzia with the configuration but shows nothing until it answers, so
    # the view is ready without it, and its answer could land after the page measured the view but before it sent
    # the measurement. Held until the measurement is logged, it cannot pass for the read that made the view ready.
    tool_updates: list[Route] = []

    def hold_tool_update(route: Route) -> None:
        tool_updates.append(route)

    page.route("**/api/tool-update", hold_tool_update)
    page.route("**/api/configuration", hold_first)
    page.on("requestfinished", finished)
    page.on("request", sent)
    since = len(run.log_entries())
    try:
        # Dad returns to the tab again and again while Ustawienia are still reading: every return reads the
        # settings and the configuration again, so the view ends with more requests than one measurement takes.
        page.evaluate(
            """([returns]) => {
              window.addEventListener("hashchange", () => setTimeout(() => {
                for (let i = 0; i < returns; i++) window.dispatchEvent(new Event("focus"));
              }, 50), { once: true });
              location.hash = "#/ustawienia/narzedzie";
            }""",
            [MAX_TIMED_REQUESTS + 5],
        )
        # Ready only after the reads of every return (harness).
        expect(settings_window(page).get_by_role("listitem", name="Wersja narzędzia")).to_be_visible(timeout=Budget.SLOWED.ms)
        [timing] = _wait_for_timings(run, since, 1, "the opening with more requests than one measurement is logged")
    finally:
        page.unroute("**/api/configuration", hold_first)
        for tool_update in tool_updates:
            tool_update.continue_()
        page.unroute("**/api/tool-update", hold_tool_update)
        page.remove_listener("requestfinished", finished)
        page.remove_listener("request", sent)
    run.check(
        bool(tool_updates),
        f"Ustawienia measured themselves while their read of Aktualizacja narzędzia was held ({len(tool_updates)} reads, "
        "harness)",
    )
    requests = timing.get("zapytania", "").split(",")
    last_read = measured[0][-1] if measured and measured[0] else None
    run.check(
        len(requests) == MAX_TIMED_REQUESTS and requests[-1].split(":")[0] == last_read,
        f"a view with more API requests than the contract's {MAX_TIMED_REQUESTS} is logged with its newest "
        f"{len(requests)}, ending with the read that made it ready ({requests[-1]}; the page's last read before "
        f"it sent the measurement: {last_read})",
    )

    run.step(FEATURE, "pomiar-bez-sladu")
    close_settings(page)
    expect(page.get_by_role("alert")).to_have_count(0)
    expect(page.get_by_role("dialog")).to_have_count(0)
    run.capture(page, "80-pomiar-bez-sladu")
    entries = [entry.text for entry in run.log_entries() if entry.event == "pomiar"]
    (run.evidence / "api" / "pomiar-dziennik.txt").write_text("\n".join(entries) + "\n", encoding="utf-8")
    run.check(
        not any(str(run.root) in entry or "/api/" in entry or PERIOD_TOKEN.search(entry) for entry in entries),
        "the measurement entries hold no path, address or period token",
    )

    run.step(FEATURE, "pomiar-obcy-origin")
    since = len(run.log_entries())
    body = json.dumps(
        {"kind": "navigation", "page": "okresy", "ready_ms": 1, "fcp_ms": None, "skeleton_ms": 0, "requests": []}
    ).encode()
    foreign = urllib.request.Request(
        run.url.rstrip("/") + "/api/view-timings",
        data=body,
        method="POST",
        headers={"Origin": "http://zly.example", "Content-Type": "application/json"},
    )
    run.check(run.refused(foreign, "pomiar-obcy-origin") == 403, "a measurement from a foreign Origin is refused")
    run.check(_timings(run, since) == [], "the refused measurement adds no entry")
