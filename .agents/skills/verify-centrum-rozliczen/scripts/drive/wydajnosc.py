"""Drive features/wydajnosc.md: measure Centrum on Dad's year of work in his computer's CPU profiles."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import re
from pathlib import Path
import statistics
from typing import Any
from urllib.parse import urlsplit

from openpyxl import Workbook, load_workbook
from openpyxl.utils import column_index_from_string
from openpyxl.worksheet.worksheet import Worksheet
from playwright.sync_api import Browser, BrowserContext, CDPSession, Page, Request, expect

from drive import DEFAULT_REPEATS
from drive.common import (
    PAGES,
    DriveFailure,
    Run,
    close_settings,
    dad_context,
    ensure_files_set,
    open_settings,
    read_json,
    read_text,
    replace_file,
)
from drive.uzupelnienie import LIVE_TIMEOUT_MS
from drive.waiting import Budget
from atrapy.scenariusz_centrum import COLLECTIVE_HEADERS, LAST_COMPLETE

SKILL_ROOT = Path(__file__).resolve().parents[2]
BASELINE = SKILL_ROOT / "wydajnosc-baseline.json"
# docs/agents/komputer-taty.md: 4× is the reference profile of Dad's laptop, 6× the pessimistic one.
PROFILES = (4, 6)
# The menu pages the baseline holds; Raporty has no budget yet, so it is neither measured nor captured.
MEASURED_PAGES = ("okresy", "uruchomienia", "metryki")
LAP = ("uruchomienia", "metryki", "okresy")
REOPENED = ("okresy", "metryki")
TRACED = ("okresy", "metryki")
REOPEN_WARMUP = 2  # V8 caches the bundle's code only after a few visits
SETTLE_MS = 400  # transitions of 150–200 ms finish and late requests arrive
# From this lap on, every page shows its last data at once: a visible skeleton there fails without a second chance.
SKELETON_FREE_LAP = 2
# Used when the baseline file is missing, so the first measurement can produce one.
DEFAULT_MARGIN = {"wzgledny": 0.15, "minimalny_ms": 20, "bundle_wzgledny": 0.02}
# Uzupełnienie na żywo (#419) on a Plik zbiorczy of Dad's size: about 430 Zlecenia skuteczne a week (September
# 2026: 852 rows in two weeks). Every 40th row has devices the Reguły ilości do not know (a row without rule).
LIVE_PAGE = f"uzupelnienie/{LAST_COMPLETE}"
LIVE_TITLE = "Uzupełnienie pliku zbiorczego"
LIVE_ROWS = 430
LIVE_CHECKS = 3
VERSION_PATH = f"/api/periods/{LAST_COMPLETE}/collective-file-version"
VIEW_PATH = f"/api/periods/{LAST_COMPLETE}/quantities-to-fill"
LIVE_DEVICES = ("nokia zte", "zte", "nokia", "nokia zte stb")
# Every fetch of the page with its path, start and answer (headers) in page time.
FETCHES = r"""
(() => {
  const original = window.fetch;
  const fetches = (window.__fetches = []);
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    const entry = { path: url.pathname, start: performance.now(), end: null };
    fetches.push(entry);
    const response = await original(input, init);
    entry.end = performance.now();
    return response;
  };
})();
"""
TRACE_CATEGORIES = [
    "devtools.timeline",
    "disabled-by-default-devtools.timeline",
    "v8",
    "v8.execute",
    "blink.user_timing",
    "loading",
]
TRACE_EVENTS = (
    "EvaluateScript", "v8.compile", "v8.compileModule", "v8.evaluateModule", "FunctionCall", "RunMicrotasks",
    "ParseHTML", "ParseAuthorStyleSheet", "UpdateLayoutTree", "Layout", "PrePaint", "Paint", "Layerize",
    "MinorGC", "MajorGC",
)

# Recorded in the page from the first byte: when the view of a page becomes ready (its h1 without any
# skeleton or aria-busy in the DOM), when a skeleton becomes visible and stops being visible, the last DOM
# change, FCP, long tasks, and Event Timing of input (the browser's own input-to-next-paint). A skeleton is in
# the DOM from the first render but shows only once its animation starts (index.css delays it by about 120 ms),
# so it is visible from the first `animationstart` of a loading element until no such element is left.
INIT = r"""
(() => {
  const P = (window.__wydajnosc = { views: [], skeleton: [], lastMutation: 0, fcp: null, longtasks: [], events: [] });
  const LOADING = '[data-slot="skeleton"],[aria-busy="true"]';
  const shown = new Set();
  let view = null;
  let visible = false;
  const track = (now) => {
    for (const element of shown) { if (!element.isConnected || !element.matches(LOADING)) shown.delete(element); }
    if ((shown.size > 0) !== visible) { visible = shown.size > 0; P.skeleton.push([now, visible]); }
  };
  document.addEventListener("animationstart", (e) => {
    if (e.target instanceof Element && e.target.matches(LOADING)) { shown.add(e.target); track(performance.now()); }
  }, true);
  const check = () => {
    const now = performance.now();
    P.lastMutation = now;
    track(now);
    const busy = !!document.querySelector(LOADING);
    const heading = document.querySelector('[data-slot="sidebar-inset"] h1');
    const ready = !busy && heading ? heading.textContent.trim() : null;
    if (ready !== view) { P.views.push([now, ready]); view = ready; }
  };
  new MutationObserver(check).observe(document, {
    subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ["aria-busy", "data-slot"],
  });
  const observe = (type, take, options = {}) => {
    try { new PerformanceObserver((list) => list.getEntries().forEach(take)).observe({ type, buffered: true, ...options }); } catch {}
  };
  observe("paint", (e) => { if (e.name === "first-contentful-paint") P.fcp = e.startTime; });
  observe("longtask", (e) => P.longtasks.push(e.duration));
  observe("event", (e) => P.events.push([e.startTime, e.duration]), { durationThreshold: 16 });
})();
"""


@dataclass
class Measured:
    """Samples of every scenario; ``values`` in ms."""

    values: dict[str, dict[int, list[float]]] = field(default_factory=dict)
    requests: dict[str, list[dict[str, int]]] = field(default_factory=dict)
    details: dict[str, dict[int, dict[str, list[float]]]] = field(default_factory=dict)
    bundle: dict[str, int] = field(default_factory=dict)
    traces: list[dict[str, Any]] = field(default_factory=list)

    def add(self, scenario: str, cpu: int, value: float, requests: list[str] | None = None, **details: float) -> None:
        self.values.setdefault(scenario, {}).setdefault(cpu, []).append(value)
        if requests is not None:
            self.requests.setdefault(scenario, []).append(dict(sorted(Counter(requests).items())))
        for name, detail in details.items():
            self.details.setdefault(scenario, {}).setdefault(cpu, {}).setdefault(name, []).append(detail)


class Browsing:
    """Fresh contexts at one CPU profile, with the API requests of each one recorded in order."""

    def __init__(self, browser: Browser, url: str, cpu: int) -> None:
        self.browser = browser
        self.url = url
        self.cpu = cpu

    @contextmanager
    def context(self) -> Iterator[tuple[BrowserContext, list[str]]]:
        context = dad_context(self.browser)
        context.add_init_script(INIT)
        requests: list[str] = []

        def record(request: Request) -> None:
            path = urlsplit(request.url).path
            if path.startswith("/api/"):
                requests.append(f"{request.method} {path}")

        context.on("request", record)
        try:
            yield context, requests
        finally:
            context.close()

    def page(self, context: BrowserContext) -> tuple[Page, CDPSession]:
        page = context.new_page()
        page.set_default_timeout(Budget.SLOWED.ms)
        cdp = context.new_cdp_session(page)
        cdp.send("Performance.enable")
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": self.cpu})
        return page, cdp

    def open(self, page: Page, page_id: str) -> float:
        page.goto(f"{self.url}#/{page_id}", wait_until="commit")
        return ready(page, PAGES[page_id])


def now(page: Page) -> float:
    value = page.evaluate("() => performance.now()")
    assert isinstance(value, (int, float))
    return float(value)


def ready(page: Page, title: str) -> float:
    """When the view of ``title`` became ready: its h1 shown with no skeleton and no aria-busy."""

    page.wait_for_function(
        "([title]) => { const v = window.__wydajnosc.views; return v.length > 0 && v[v.length - 1][1] === title }",
        arg=[title],
        polling="raf",
    )
    value = page.evaluate("() => { const v = window.__wydajnosc.views; return v[v.length - 1][0] }")
    assert isinstance(value, (int, float))
    return float(value)


def skeleton_ms(page: Page, start: float, end: float) -> float:
    changes: list[list[Any]] = page.evaluate("() => window.__wydajnosc.skeleton")
    total, since = 0.0, None
    for at, visible in changes:
        if visible:
            since = at
        elif since is not None:
            total += max(0.0, min(at, end) - max(since, start))
            since = None
    if since is not None:
        total += max(0.0, end - max(since, start))
    return total


def script_ms(cdp: CDPSession) -> float:
    metrics = {entry["name"]: entry["value"] for entry in cdp.send("Performance.getMetrics")["metrics"]}
    return float(metrics.get("ScriptDuration", 0)) * 1000


def _cold_starts(browsing: Browsing, measured: Measured, pages: tuple[str, ...] = MEASURED_PAGES) -> None:
    for page_id in pages:
        with browsing.context() as (context, requests):
            page, cdp = browsing.page(context)
            shown = browsing.open(page, page_id)
            page.wait_for_timeout(SETTLE_MS)
            perf = page.evaluate("() => window.__wydajnosc")
            if not measured.bundle:
                measured.bundle = page.evaluate(
                    """() => {
                      const size = (suffix) => performance.getEntriesByType("resource")
                        .filter((r) => new URL(r.name).pathname.endsWith(suffix))
                        .reduce((sum, r) => sum + r.decodedBodySize, 0);
                      return { js: size(".js"), css: size(".css") };
                    }"""
                )
            measured.add(
                f"{page_id}/zimny-start", browsing.cpu, shown, requests,
                fcp_ms=float(perf["fcp"] or 0), skrypt_ms=script_ms(cdp), dlugie_zadania_ms=sum(perf["longtasks"]),
            )


def _reopened_tabs(browsing: Browsing, measured: Measured, repeats: int, pages: tuple[str, ...] = REOPENED) -> None:
    for page_id in pages:
        with browsing.context() as (context, requests):
            for visit in range(REOPEN_WARMUP + repeats):
                mark = len(requests)
                page, cdp = browsing.page(context)
                shown = browsing.open(page, page_id)
                page.wait_for_timeout(SETTLE_MS)
                fcp = page.evaluate("() => window.__wydajnosc.fcp")
                if visit >= REOPEN_WARMUP:
                    measured.add(
                        f"{page_id}/ponowne-otwarcie", browsing.cpu, shown, requests[mark:],
                        fcp_ms=float(fcp or 0), skrypt_ms=script_ms(cdp),
                    )
                page.close()


def _menu_laps(browsing: Browsing, measured: Measured) -> None:
    with browsing.context() as (context, requests):
        page, cdp = browsing.page(context)
        browsing.open(page, "okresy")
        page.wait_for_timeout(SETTLE_MS)
        for lap in (1, 2):
            for page_id in LAP:
                mark, before = len(requests), script_ms(cdp)
                start = now(page)
                page.get_by_role("link", name=PAGES[page_id], exact=True).click()
                shown = ready(page, PAGES[page_id])
                page.wait_for_timeout(SETTLE_MS)
                scenario = f"menu/{lap}/{page_id}"
                measured.add(scenario, browsing.cpu, shown - start, requests[mark:], skrypt_ms=script_ms(cdp) - before)
                measured.add(f"{scenario}/szkielet", browsing.cpu, skeleton_ms(page, start, shown))


def _interactions(browsing: Browsing, measured: Measured) -> None:
    """Input measured as the browser's Event Timing (≤ 16 ms shows as 16); a return to the tab, which
    has no input, until its last API answer or DOM change."""

    with browsing.context() as (context, requests):
        page, _ = browsing.page(context)

        def interaction(scenario: str, act: Callable[[], None]) -> None:
            mark, start = len(requests), now(page)
            act()
            page.wait_for_timeout(SETTLE_MS)
            events: list[list[float]] = page.evaluate("() => window.__wydajnosc.events")
            durations = [duration for at, duration in events if at >= start]
            if not durations:
                durations = [16.0]  # below Event Timing's threshold
            measured.add(scenario, browsing.cpu, max(durations), requests[mark:])

        def return_to_tab(scenario: str) -> None:
            mark, start = len(requests), now(page)
            page.evaluate("() => window.dispatchEvent(new Event('focus'))")
            page.wait_for_timeout(SETTLE_MS)
            settled = page.evaluate(
                """([start]) => Math.max(window.__wydajnosc.lastMutation, ...performance.getEntriesByType("resource")
                  .filter((r) => r.startTime >= start && new URL(r.name).pathname.startsWith("/api/"))
                  .map((r) => r.responseEnd))""",
                [start],
            )
            measured.add(scenario, browsing.cpu, max(0.0, float(settled) - start), requests[mark:])

        def go(page_id: str) -> None:
            page.get_by_role("link", name=PAGES[page_id], exact=True).click()
            ready(page, PAGES[page_id])
            page.wait_for_timeout(SETTLE_MS)

        browsing.open(page, "okresy")
        page.wait_for_timeout(SETTLE_MS)
        # The theme is switched in the section Wygląd of Ustawienia over Okresy; the opening itself is not measured.
        themes = open_settings(page, "Wygląd").get_by_role("group", name="Motyw", exact=True)
        page.wait_for_timeout(SETTLE_MS)
        interaction("okresy/motyw-jasny", themes.get_by_role("button", name="Jasny", exact=True).click)
        interaction("okresy/motyw-ciemny", themes.get_by_role("button", name="Ciemny", exact=True).click)
        close_settings(page)
        return_to_tab("okresy/powrot-do-karty")
        go("metryki")
        for group, option, slug in (
            ("Proces", "Przebieg", "proces-przebieg"),
            ("Proces", "Przygotowanie", "proces-przygotowanie"),
            ("Tryb", "DRY-RUN", "tryb-dry-run"),
            ("Tryb", "RUN", "tryb-run"),
        ):
            button = page.get_by_role("group", name=group, exact=True).get_by_role("button", name=option, exact=True)
            interaction(f"metryki/{slug}", button.click)
        interaction("metryki/zakladka-tabela", page.get_by_role("tab", name="Tabela", exact=True).click)
        interaction("metryki/zakladka-wykres", page.get_by_role("tab", name="Wykres", exact=True).click)
        return_to_tab("metryki/powrot-do-karty")
        go("uruchomienia")
        interaction("uruchomienia/zakladka-historia", page.get_by_role("tab", name="Historia", exact=True).click)
        interaction("uruchomienia/zakladka-uruchomienie", page.get_by_role("tab", name="Uruchomienie", exact=True).click)
        toggle = page.get_by_role("button", name="Pokaż lub ukryj menu", exact=True)
        interaction("menu-boczne/zwin", toggle.click)
        interaction("menu-boczne/rozwin", toggle.click)


def _write_live_file(path: Path) -> None:
    """A synthetic Plik zbiorczy of Dad's size in his layout (header in row 17, data from row 18)."""

    workbook = Workbook()
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    for column, header in enumerate(COLLECTIVE_HEADERS, start=1):
        sheet.cell(17, column).value = header
    tuesday = datetime(2026, 10, 6, 8, 0)
    for index in range(LIVE_ROWS):
        devices = "router x9" if index % 40 == 0 else "prewencja" if index % 45 == 7 else LIVE_DEVICES[index % 4]
        values: tuple[str | datetime, ...] = (
            "Miasto", f"ul. Syntetyczna {index}", f"u UM-SYN-{index:04d}", devices, "instalacja usługi",
            f"ZL-{index:05d}", tuesday + timedelta(minutes=23 * index), f"Wykonawca Testowy {chr(65 + index % 14)}",
            f"OR-{index:05d}", "TAK", "zainstalowano router i dekoder, sprawdzono sygnał, klient poinformowany",
        )
        for column, value in enumerate(values, start=1):
            sheet.cell(18 + index, column).value = value
        sheet.cell(18 + index, column_index_from_string("N")).value = 45
        sheet.cell(18 + index, column_index_from_string("V")).value = 1
    _save_whole(workbook, path)


def _toggle_live_value(path: Path) -> None:
    """Dad types a quantity into the first row without rule, or clears it, and Excel saves the whole file."""

    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    cell = sheet["O18"]
    cell.value = None if cell.value else 1
    _save_whole(workbook, path)


def _save_whole(workbook: Workbook, path: Path) -> None:
    # Like Excel: a whole new file replaces the old one, so a check never sees half of it.
    partial = path.with_name(f"zapis-{path.name}")
    workbook.save(partial)
    workbook.close()
    replace_file(partial, path)


def _live_filling(browsing: Browsing, measured: Measured, collective_file: Path) -> None:
    """The summary of Uzupełnienie open while Dad works in Excel: checks of an unchanged file, then one change.

    ``pytanie-o-zapis``: one check of the saved version (request start to answer); ``zmiana-pliku``: from the
    answer of the check that saw Dad's save to the new counter on screen, which is the full read and the render.
    """

    with browsing.context() as (context, requests):
        context.add_init_script(FETCHES)
        page, cdp = browsing.page(context)
        page.goto(f"{browsing.url}#/{LIVE_PAGE}", wait_until="commit")
        ready(page, LIVE_TITLE)
        page.wait_for_timeout(SETTLE_MS)
        mark, seen, before = len(requests), _fetch_count(page), script_ms(cdp)
        for _ in range(LIVE_CHECKS):
            with page.expect_response(lambda response: urlsplit(response.url).path == VERSION_PATH, timeout=LIVE_TIMEOUT_MS):
                pass
        page.wait_for_timeout(SETTLE_MS)
        checks = [end - start for path, start, end in _fetches(page, seen) if path == VERSION_PATH]
        measured.add(
            "uzupelnienie/pytanie-o-zapis", browsing.cpu, statistics.median(checks), requests[mark:],
            skrypt_ms=(script_ms(cdp) - before) / LIVE_CHECKS,
        )

        counter = '[aria-label="Wiersze bez reguły"]'
        shown = page.eval_on_selector(counter, "(region) => region.textContent")
        mark, seen = len(requests), _fetch_count(page)
        _toggle_live_value(collective_file)
        page.wait_for_function(
            "([counter, shown]) => document.querySelector(counter).textContent !== shown",
            arg=[counter, shown], polling="raf", timeout=LIVE_TIMEOUT_MS,
        )
        on_screen = float(page.evaluate("() => window.__wydajnosc.lastMutation"))
        page.wait_for_timeout(SETTLE_MS)
        fetches = _fetches(page, seen)
        reads = [(start, end) for path, start, end in fetches if path == VIEW_PATH]
        saw = [end for path, _, end in fetches if path == VERSION_PATH and reads and end <= reads[0][0]]
        if not reads or not saw:
            raise DriveFailure(f"uzupelnienie/zmiana-pliku: no check of the saved version before the read: {fetches}")
        measured.add(
            "uzupelnienie/zmiana-pliku", browsing.cpu, on_screen - saw[-1], requests[mark:],
            odczyt_ms=reads[0][1] - reads[0][0],
        )


def _fetch_count(page: Page) -> int:
    count = page.evaluate("() => window.__fetches.length")
    assert isinstance(count, int)
    return count


def _fetches(page: Page, since: int) -> list[tuple[str, float, float]]:
    """The page's fetches from number ``since`` on that have an answer, in order: path, start and answer."""

    found: list[dict[str, Any]] = page.evaluate("() => window.__fetches")
    return [
        (entry["path"], float(entry["start"]), float(entry["end"])) for entry in found[since:] if entry["end"] is not None
    ]


def _trace(browsing: Browsing, page_id: str, path: Path) -> dict[str, Any]:
    """A DevTools trace of one cold start; the main thread's time per event kind."""

    with browsing.context() as (context, _):
        page, _ = browsing.page(context)
        browsing.browser.start_tracing(page=page, path=path, categories=TRACE_CATEGORIES)
        browsing.open(page, page_id)
        page.wait_for_timeout(SETTLE_MS)
        browsing.browser.stop_tracing()
    events = read_json(path)["traceEvents"]
    renderers = {
        (event["pid"], event["tid"])
        for event in events
        if event.get("name") == "thread_name" and event.get("args", {}).get("name") == "CrRendererMain"
    }
    tasks = Counter(
        (event.get("pid"), event.get("tid"))
        for event in events
        if event.get("name") == "RunTask" and (event.get("pid"), event.get("tid")) in renderers
    )
    main = tasks.most_common(1)[0][0]
    spent: Counter[str] = Counter()
    for event in events:
        if (event.get("pid"), event.get("tid")) == main and event.get("ph") == "X" and event["name"] in TRACE_EVENTS:
            spent[event["name"]] += event.get("dur", 0) / 1000
    return {
        "strona": page_id,
        "profil": f"{browsing.cpu}x",
        "plik": path.name,
        "glowny_watek_ms": {name: round(ms, 1) for name, ms in spent.most_common()},
    }


def measure(browser: Browser, url: str, repeats: int, evidence: Path, collective_file: Path) -> Measured:
    measured = Measured()
    for cpu in PROFILES:
        browsing = Browsing(browser, url, cpu)
        for _ in range(repeats):
            _cold_starts(browsing, measured)
            _menu_laps(browsing, measured)
            _interactions(browsing, measured)
            _live_filling(browsing, measured, collective_file)
        _reopened_tabs(browsing, measured, repeats)
        for page_id in TRACED:
            path = evidence / f"slad-{page_id}-{cpu}x.json"
            measured.traces.append(_trace(browsing, page_id, path))
        print(f"  measured: CPU {cpu}× ({repeats} repetitions)", flush=True)
    return measured


def remeasure(
    browser: Browser, url: str, repeats: int, over: list[tuple[str, int]], collective_file: Path
) -> Measured:
    """Measures again the routines that produced the scenarios over budget, in their profile only."""

    again = Measured()
    routines = sorted({(cpu, _routine(scenario)) for scenario, cpu in over})
    for cpu, routine in routines:
        browsing = Browsing(browser, url, cpu)
        kind, _, page_id = routine.partition(":")
        if kind == "ponowne-otwarcie":
            _reopened_tabs(browsing, again, repeats, (page_id,))
            continue
        for _ in range(repeats):
            if kind == "zimny-start":
                _cold_starts(browsing, again, (page_id,))
            elif kind == "menu":
                _menu_laps(browsing, again)
            elif kind == "na-zywo":
                _live_filling(browsing, again, collective_file)
            else:
                _interactions(browsing, again)
    print(f"  measured again: {', '.join(f'{routine} {cpu}×' for cpu, routine in routines)}", flush=True)
    return again


def _routine(scenario: str) -> str:
    first, _, rest = scenario.partition("/")
    if rest in ("zimny-start", "ponowne-otwarcie"):
        return f"{rest}:{first}"
    return {"menu": "menu", "uzupelnienie": "na-zywo"}.get(first, "interakcje")


def budget(baseline_ms: float, margin: dict[str, float]) -> float:
    return max(baseline_ms * (1 + margin["wzgledny"]), baseline_ms + margin["minimalny_ms"])


def over_budget(measured: Measured, baseline: dict[str, Any]) -> list[tuple[str, int]]:
    """The scenarios and profiles whose median exceeds the budget of a known baseline."""

    margin: dict[str, float] = baseline.get("margines", DEFAULT_MARGIN)
    expected: dict[str, Any] = baseline.get("scenariusze", {})
    over = []
    for scenario, profiles in measured.values.items():
        for cpu, values in profiles.items():
            base = expected.get(scenario, {}).get("mediana_ms", {}).get(f"{cpu}x")
            if base is not None and statistics.median(values) > budget(base, margin):
                over.append((scenario, cpu))
    return over


def compare(measured: Measured, baseline: dict[str, Any], again: Measured | None = None) -> dict[str, Any]:
    """Each scenario's median against its baseline and budget, and its API requests against the expected ones.

    A median over budget fails only if the median of ``again`` (the same scenario measured again right
    after) is over budget too: one noisy series on a busy machine is not a regression. API requests and
    the bundle have no second chance.
    """

    margin: dict[str, float] = baseline.get("margines", DEFAULT_MARGIN)
    expected: dict[str, Any] = baseline.get("scenariusze", {})
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for scenario, profiles in measured.values.items():
        known = expected.get(scenario, {})
        for cpu, values in profiles.items():
            profile = f"{cpu}x"
            median = statistics.median(values)
            base = known.get("mediana_ms", {}).get(profile)
            limit = None if base is None else budget(base, margin)
            repeated = (again.values if again else {}).get(scenario, {}).get(cpu)
            median_again = None if repeated is None else statistics.median(repeated)
            if limit is None:
                verdict = "brak w baseline"
            elif median <= limit:
                verdict = "ok"
            elif median_again is not None and median_again <= limit:
                verdict = "ok w ponownym pomiarze"
            else:
                verdict = "ponad budżet"
            if verdict not in ("ok", "ok w ponownym pomiarze"):
                shown = "brak" if limit is None else f"{limit:.0f} ms"
                again_text = "" if median_again is None else f", ponownie {median_again:.0f} ms"
                failures.append(f"{scenario} {profile}: {verdict} (mediana {median:.0f} ms{again_text}, budżet {shown})")
            details = {
                name: round(statistics.median(samples), 1)
                for name, samples in measured.details.get(scenario, {}).get(cpu, {}).items()
            }
            rows.append({
                "scenariusz": scenario, "profil": profile, "mediana_ms": round(median, 1),
                "probki_ms": [round(value, 1) for value in values], "baseline_ms": base,
                "budzet_ms": None if limit is None else round(limit, 1), "wynik": verdict, "szczegoly": details,
                "ponownie_ms": None if median_again is None else round(median_again, 1),
            })
    for scenario, profiles in measured.values.items():
        if scenario.startswith(f"menu/{SKELETON_FREE_LAP}/") and scenario.endswith("/szkielet"):
            for cpu, values in profiles.items():
                if any(value > 0 for value in values):
                    shown = ", ".join(f"{value:.0f}" for value in values)
                    failures.append(f"{scenario} {cpu}x: szkielet widoczny przy powrocie na stronę ({shown} ms)")
    requests: list[dict[str, Any]] = []
    for scenario, counts in measured.requests.items():
        wanted = expected.get(scenario, {}).get("zapytania_api")
        differing = [count for count in counts if count != wanted]
        verdict = "ok" if not differing else ("brak w baseline" if wanted is None else "inna liczba")
        if verdict != "ok":
            failures.append(f"{scenario}: zapytania API {verdict} (oczekiwano {wanted}, zmierzono {differing[0]})")
        requests.append({
            "scenariusz": scenario, "oczekiwane": wanted, "zmierzone": differing[0] if differing else counts[0],
            "powtorzenia_z_roznica": len(differing), "powtorzenia": len(counts), "wynik": verdict,
            "rozne_zestawy": len({json.dumps(count, sort_keys=True) for count in counts}),
        })
    for scenario in sorted(set(expected) - set(measured.values)):
        failures.append(f"{scenario}: scenariusz z baseline'u nie został zmierzony")
    bundle: list[dict[str, Any]] = []
    for kind, size in measured.bundle.items():
        base = baseline.get("bundle_bajty", {}).get(kind)
        limit = None if base is None else round(base * (1 + margin["bundle_wzgledny"]))
        verdict = "brak w baseline" if limit is None else ("ok" if size <= limit else "ponad budżet")
        if verdict != "ok":
            failures.append(f"bundle {kind}: {verdict} ({size} B, budżet {limit} B)")
        bundle.append({"rodzaj": kind, "bajty": size, "baseline_bajty": base, "budzet_bajty": limit, "wynik": verdict})
    if not expected:
        failures = ["baseline nie ma scenariuszy; zaakceptuj wydajnosc/baseline-kandydat.json (features/wydajnosc.md)"]
    return {
        "margines": margin, "scenariusze": rows, "zapytania_api": requests, "bundle": bundle,
        "slady_cpu": measured.traces, "porazki": failures,
    }


def candidate(measured: Measured, margin: dict[str, float], repeats: int) -> dict[str, Any]:
    """This measurement in the baseline's format: copy it over the baseline to accept it."""

    return {
        "zmierzono": {"data": datetime.now().astimezone().date().isoformat(), "powtorzenia": repeats, "profile": [f"{cpu}x" for cpu in PROFILES]},
        "margines": margin,
        "bundle_bajty": measured.bundle,
        "scenariusze": {
            scenario: {
                "mediana_ms": {f"{cpu}x": round(statistics.median(values)) for cpu, values in profiles.items()},
                **({"zapytania_api": measured.requests[scenario][0]} if scenario in measured.requests else {}),
            }
            for scenario, profiles in measured.values.items()
        },
    }


def text_report(report: dict[str, Any], baseline_path: Path, repeats: int) -> str:
    def ms(value: float | None) -> str:
        return "–" if value is None else f"{value:.0f} ms"

    lines = [
        f"WYDAJNOSC | powtórzenia={repeats} | profile={','.join(f'{cpu}×' for cpu in PROFILES)} | baseline={baseline_path}",
        f"margines: +{report['margines']['wzgledny']:.0%}, co najmniej +{report['margines']['minimalny_ms']} ms; "
        f"bundle +{report['margines']['bundle_wzgledny']:.0%}",
        "",
        "mediana ponad budżet mierzy się ponownie; porażka tylko, gdy ponowna mediana też jest ponad budżetem",
        "",
        f"{'scenariusz':44} {'profil':6} {'mediana':>9} {'baseline':>9} {'budżet':>9}  wynik",
    ]
    for row in report["scenariusze"]:
        again = "" if row["ponownie_ms"] is None else f" (ponownie {ms(row['ponownie_ms'])})"
        lines.append(
            f"{row['scenariusz']:44} {row['profil']:6} {ms(row['mediana_ms']):>9} {ms(row['baseline_ms']):>9} "
            f"{ms(row['budzet_ms']):>9}  {row['wynik']}{again}"
            + ("" if not row["szczegoly"] else "  (" + ", ".join(f"{k} {v:.0f}" for k, v in row["szczegoly"].items()) + ")")
        )
    lines += ["", "zapytania API (każde powtórzenie w obu profilach)"]
    for entry in report["zapytania_api"]:
        shown = ", ".join(f"{request} ×{count}" for request, count in entry["zmierzone"].items()) or "brak"
        lines.append(f"{entry['scenariusz']:44} {entry['wynik']:16} {shown}")
        if entry["wynik"] != "ok":
            lines.append(f"{'':44} {'oczekiwano':16} {entry['oczekiwane']}")
    lines += ["", "bundle (rozmiar po rozpakowaniu)"]
    for entry in report["bundle"]:
        lines.append(
            f"{entry['rodzaj']:44} {entry['bajty']:>9} B  baseline {entry['baseline_bajty']} B  "
            f"budżet {entry['budzet_bajty']} B  {entry['wynik']}"
        )
    lines += ["", "ślady CPU zimnego startu (główny wątek, ms)"]
    for trace in report["slady_cpu"]:
        top = ", ".join(f"{name} {value:.0f}" for name, value in list(trace["glowny_watek_ms"].items())[:8])
        lines.append(f"{trace['strona']} {trace['profil']}: {top}  [{trace['plik']}]")
    lines += ["", f"porażki: {len(report['porazki'])}", *(f"  {failure}" for failure in report["porazki"])]
    return "\n".join(lines) + "\n"


def _prepare_year_of_work(run: Run, page: Page) -> None:
    """Points Centrum to Dad's year of work and the Rejestr zleceń through the UI, as Dad does."""

    year = run.fixture["year_of_work"]
    page.goto(run.url + "#/okresy")
    ensure_files_set(run, page, year["periods_directory"])
    periods = run.api("/api/periods", "wydajnosc-tablica")["periods"]
    assert isinstance(periods, list)
    tokens = {period["token"] for period in periods}
    ready_count = sum(period["status"] == "worker_settlements_ready" for period in periods)
    run.check(
        len(tokens) >= year["periods"] and ready_count == year["worker_settlements_ready"],
        f"the Tablica okresów holds the year: {len(tokens)} periods, {ready_count} with Rozliczenia pracowników",
    )
    runs = run.api("/api/metrics", "wydajnosc-metryki")["runs"]
    assert isinstance(runs, list)
    run.check(len(runs) == run.fixture["metrics"]["runs"], f"Metryki read {len(runs)} records of the year")
    expect(page.locator("html")).to_have_class(re.compile(r"\bdark\b"))
    for number, page_id in enumerate(MEASURED_PAGES, start=84):
        page.get_by_role("link", name=PAGES[page_id], exact=True).click()
        expect(page.get_by_role("heading", name=PAGES[page_id], exact=True)).to_be_visible()
        expect(page.locator('[data-slot="skeleton"],[aria-busy="true"]')).to_have_count(0)
        run.capture(page, f"{number}-wydajnosc-{page_id}")
    # The drive's own tab would keep its event stream open while measuring.
    page.goto("about:blank")


def drive(run: Run, page: Page, *, baseline_path: Path = BASELINE, repeats: int = DEFAULT_REPEATS) -> None:
    feature = "wydajnosc"
    out = run.evidence / "wydajnosc"
    out.mkdir(exist_ok=True)

    run.step(feature, "wydajnosc-rok-pracy")
    _prepare_year_of_work(run, page)

    run.step(feature, "wydajnosc-na-zywo")
    [collective_file] = Path(run.fixture["year_of_work"]["periods_directory"]).rglob(
        f"Rozliczenie {LAST_COMPLETE} - zbiorcze.xlsx"
    )
    _write_live_file(collective_file)
    answer = run.api(VIEW_PATH, "wydajnosc-uzupelnienie")
    run.check(answer["state"] == "ready", f"the year's {LAST_COMPLETE} has a Plik zbiorczy of {LIVE_ROWS} rows")

    run.step(feature, "wydajnosc-pomiar")
    browser = page.context.browser
    assert browser is not None
    measured = measure(browser, run.url, repeats, out, collective_file)

    run.step(feature, "wydajnosc-porownanie")
    baseline: dict[str, Any] = (
        read_json(baseline_path) if baseline_path.exists() else {}
    )
    over = over_budget(measured, baseline)
    again = remeasure(browser, run.url, repeats, over, collective_file) if over else None
    report = compare(measured, baseline, again)
    report["baseline"] = str(baseline_path)
    report["powtorzenia"] = repeats
    (out / "raport.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "raport.txt").write_text(text_report(report, baseline_path, repeats), encoding="utf-8")
    (out / "baseline-kandydat.json").write_text(
        json.dumps(candidate(measured, report["margines"], repeats), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(read_text(out / "raport.txt"), flush=True)
    if report["porazki"]:
        raise DriveFailure(f"wydajnosc: {len(report['porazki'])} porażek, see wydajnosc/raport.txt")
    run.check(True, "every scenario is within its budget and sends the expected API requests")
