"""Drive features/metryki.md."""

from __future__ import annotations

from itertools import pairwise
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from playwright.sync_api import Locator, Page, ViewportSize, expect

from drive.common import (
    LAST_COMPLETE,
    REPO_ROOT,
    Run,
    choose_periods_directory,
    dad_tab,
    history_rows,
    local_time,
    move,
)

# The chart shows the newest Uruchomienia procesu of the chosen process and mode; older ones are in the history.
CHART_RUNS = 12
METRICS_ROUTE = "**/api/metrics"
# A bar is at most this wide, and narrower when its share of the chart is smaller (like recharts' `maxBarSize`).
MAX_BAR_PX = 28
# The smallest phone window: the seven bars of Przygotowanie RUN do not fit side by side at the widest size there.
NARROW_VIEWPORT: ViewportSize = {"width": 320, "height": 640}
# Left and right edge of every bar's segments, oldest bar first.
BAR_EDGES = """(figure) => [...figure.querySelectorAll("[role=button]")].map((bar) => {
  const boxes = [...bar.querySelectorAll("[data-phase]")].map((segment) => segment.getBoundingClientRect());
  return [Math.min(...boxes.map((box) => box.left)), Math.max(...boxes.map((box) => box.right))];
})"""


def _seconds(duration_ms: int) -> str:
    """The UI's duration text: tenths of a second rounded half up, Polish comma (``7250`` → ``7,3 s``)."""

    tenths = (duration_ms + 50) // 100
    return f"{tenths // 10},{tenths % 10} s"


def _other_results(results: dict[str, int]) -> str:
    """The note under the OK count: ``3 do sprawdzenia · 2 zatrzymane · 1 błąd``, with Polish plural of „błąd”."""

    failed = results["failed"]
    last, tens = failed % 10, failed % 100
    word = "błąd" if failed == 1 else "błędy" if 2 <= last <= 4 and not 12 <= tens <= 14 else "błędów"
    return f"{results['needs_review']} do sprawdzenia · {results['stopped']} zatrzymane · {failed} {word}"


def drive(run: Run, page: Page) -> None:
    feature = "metryki"
    fixture_metrics = run.fixture["metrics"]

    run.step(feature, "metryki-karty-okresow")
    page.goto(run.url + "#/okresy")
    if run.api("/api/settings", "metryki-ustawienia")["periods_directory"] == {"state": "not_set"}:
        choose_periods_directory(run, page)
    metrics = run.api("/api/metrics", "metryki")
    runs = metrics["runs"]
    recent = metrics["recent"]
    assert isinstance(runs, list) and isinstance(recent, dict)
    run.check(len(runs) == fixture_metrics["runs"], "the server reads every valid record of both metrics files")
    run.check(
        {entry["process"] for entry in runs} == {"preparation", "settlement"},
        "the history holds both processes, and the records the metrics reader skips are absent",
    )
    stats = page.get_by_role("group", name="Najważniejsze liczby")
    board = run.api("/api/periods", "metryki-tablica")["periods"]
    assert isinstance(board, list)
    prepared = next(period for period in board if period["collective_file_exists"])
    expect(stats.get_by_role("group", name="Ostatni przygotowany okres")).to_contain_text(prepared["token"])
    latest = runs[0]
    latest_card = stats.get_by_role("group", name="Ostatnie uruchomienie")
    expect(latest_card).to_contain_text(f"{latest['process_label']} · {local_time(latest['started_at'])}")
    expect(latest_card).to_contain_text("OK")
    results = recent["results"]
    recent_card = stats.get_by_role("group", name=f"Ostatnie {recent['weeks']} tygodni")
    expect(recent_card).to_contain_text(f"{results['ok']} OK")
    expect(recent_card).to_contain_text(_other_results(results))
    run.check(True, "Okresy shows the last prepared period, the last Uruchomienie procesu and the recent results")
    run.capture(page, "20-metryki-karty-okresow")

    run.step(feature, "metryki-karty-okresow-bez-odczytu")
    _drive_cards_unread(run, page, stats, recent["weeks"])

    run.step(feature, "metryki-p50-p95")
    page.get_by_role("link", name="Metryki", exact=True).click()
    expect(page.get_by_role("heading", name="Metryki", exact=True)).to_be_visible()
    entries = metrics["statistics"]
    assert isinstance(entries, list)
    statistics = {(entry["process"], entry["mode"]): entry for entry in entries}
    preparation_run = statistics[("preparation", "RUN")]
    percentiles = preparation_run["percentiles"]
    run.check(
        preparation_run["completed_runs"] >= 5 and percentiles is not None,
        "Przygotowanie RUN has five completed observations, so P50/P95 exist",
    )
    strip = page.get_by_role("group", name="Statystyki")
    expect(strip.get_by_role("group", name="P50")).to_contain_text(_seconds(percentiles["p50_ms"]))
    expect(strip.get_by_role("group", name="P95")).to_contain_text(_seconds(percentiles["p95_ms"]))
    counts = preparation_run["results"]
    expect(strip.get_by_role("group", name="Wyniki")).to_contain_text(f"{counts['ok']} OK")
    expect(strip.get_by_role("group", name="Wyniki")).to_contain_text(_other_results(counts))
    run.check(True, "the strip shows the server's P50/P95 and result counts for Przygotowanie RUN")

    run.step(feature, "metryki-wykres")
    chart = page.get_by_role("figure", name="Wykres czasów etapów")
    expect(chart).to_be_visible()
    phases = metrics["phases"]
    assert isinstance(phases, list)
    for process, process_name in (("settlement", "Przebieg"), ("preparation", "Przygotowanie")):
        page.get_by_role("group", name="Proces", exact=True).get_by_role("button", name=process_name, exact=True).click()
        for mode in ("DRY-RUN", "RUN"):
            page.get_by_role("group", name="Tryb", exact=True).get_by_role("button", name=mode, exact=True).click()
            _check_chart(run, chart, phases, _chart_runs(runs, process, mode), f"{process_name} {mode}")
    shown_runs = _chart_runs(runs, "preparation", "RUN")
    run.check(True, "the stage-times chart stacks the measured phases of each shown run for every Proces and Tryb")
    _check_bar_widths(run, chart, "1440 px", narrow=False)
    run.capture(page, "21-metryki-wykres")

    run.step(feature, "metryki-wykres-waski")
    _drive_narrow_chart(run, page)

    run.step(feature, "metryki-wykres-szczegoly")
    _drive_bar_details(run, page, chart, phases, shown_runs)

    run.step(feature, "metryki-tabela-etapow")
    page.get_by_role("tab", name="Tabela", exact=True).click()
    table = page.get_by_role("table", name="Czasy etapów")
    expect(table.get_by_role("row")).to_have_count(1 + len(shown_runs) + 2)
    p50_row = table.get_by_role("row").filter(has_text="P50")
    expect(p50_row).to_contain_text(_seconds(percentiles["p50_ms"]))
    for phase in percentiles["phases"]:
        if any(p["phase"] == phase["phase"] and p["duration_ms"] for e in shown_runs for p in e["phase_durations"]):
            expect(p50_row).to_contain_text(_seconds(phase["p50_ms"]))
    run.check(True, "the table view lists each run's phase times with per-phase P50/P95 from the server")
    run.capture(page, "22-metryki-tabela-etapow")
    page.get_by_role("tab", name="Wykres", exact=True).click()

    run.step(feature, "metryki-za-malo-obserwacji")
    page.get_by_role("group", name="Tryb", exact=True).get_by_role("button", name="DRY-RUN", exact=True).click()
    dry_run = statistics[("preparation", "DRY-RUN")]
    run.check(
        dry_run["percentiles"] is None and dry_run["completed_runs"] < 5,
        "Przygotowanie DRY-RUN has fewer than five completed observations",
    )
    expect(strip.get_by_role("group", name="P50")).to_contain_text(f"od 5 ukończonych (jest {dry_run['completed_runs']})")
    run.check(True, "below five completed observations P50/P95 show a dash and the count")
    run.capture(page, "23-metryki-za-malo-obserwacji")
    page.get_by_role("group", name="Tryb", exact=True).get_by_role("button", name="RUN", exact=True).click()

    run.step(feature, "metryki-przerwane")
    period, phase_times = fixture_metrics["interrupted"]
    interrupted = page.get_by_role("region", name="Przerwane")
    expect(interrupted).to_contain_text(period)
    expect(interrupted).to_contain_text(
        f"Sprawdzanie {_seconds(phase_times[0])} · Odczyt danych {_seconds(phase_times[1])}"
    )
    expect(interrupted).to_contain_text(f"do przerwania {_seconds(sum(phase_times))}")
    run.check(True, "an interrupted Uruchomienie procesu shows its phase times until the interruption")

    run.step(feature, "metryki-historia")
    rows = history_rows(page)
    expect(rows).to_have_count(1 + min(10, len(runs)))
    expect(rows.nth(1)).to_contain_text(local_time(runs[0]["started_at"]))
    dry_runs_on_page = sum(1 for entry in runs[:10] if entry["mode"] == "DRY-RUN")
    history = page.get_by_role("table", name="Historia Uruchomień procesu")
    expect(history.get_by_text("DRY-RUN", exact=True)).to_have_count(dry_runs_on_page)
    expect(history.get_by_text(".cmd", exact=True)).to_have_count(min(10, len(runs)))
    run.capture(page, "24-metryki-historia")
    history.get_by_role("button", name="Czas", exact=True).click()
    longest = max(runs, key=lambda entry: entry["total_duration_ms"])
    expect(rows.nth(1)).to_contain_text(_seconds(longest["total_duration_ms"]))
    expect(history.get_by_role("columnheader", name="Czas")).to_have_attribute("aria-sort", "descending")
    page.get_by_role("group", name="Proces w historii").get_by_role("button", name="Przebieg", exact=True).click()
    settlements = [entry for entry in runs if entry["process"] == "settlement"]
    expect(rows).to_have_count(1 + min(10, len(settlements)))
    for index in range(1, min(10, len(settlements)) + 1):
        expect(rows.nth(index)).to_contain_text("Przebieg rozliczeń")
    page.get_by_role("group", name="Proces w historii").get_by_role("button", name="Wszystkie", exact=True).click()
    page.get_by_role("button", name="Pokaż starsze", exact=True).click()
    expect(rows).to_have_count(1 + min(20, len(runs)))
    run.check(True, "the history sorts by time, filters by process and shows older runs on demand")
    run.capture(page, "25-metryki-historia-filtry")

    run.step(feature, "metryki-rodzaj-zatrzymania")
    _drive_stop_kinds(run, page, runs)

    run.step(feature, "metryki-nowy-rekord-spoza-centrum")
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "uruchom_proces.py"), "preparation",
         "--register", str(run.root / "brak-rejestru.xlsx"),
         "--periods-directory", run.fixture["periods_directory"],
         "--period", LAST_COMPLETE, "--dry-run",
         "--metrics", fixture_metrics["preparation"]],
        cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False,
    )
    result = json.loads(completed.stdout)
    run.check(
        completed.returncode == 1 and result["stop"]["message"]["code"] == "BRAK_REJESTRU" and result["metrics_saved"],
        "the machine script stopped (no Rejestr zleceń) and wrote its metrics record",
    )
    last_record = json.loads(Path(fixture_metrics["preparation"]).read_text(encoding="utf-8").splitlines()[-1])
    run.check(
        (last_record["schema_version"], last_record["result"], last_record["stop"])
        == (3, "BLAD_KRYTYCZNY", {"kind": "for_tata", "code": "BRAK_REJESTRU"}),
        f"the record carries the Rodzaj Zatrzymania and the Komunikat code only: {last_record['stop']}",
    )
    after = run.api("/api/metrics", "metryki-spoza-centrum")["runs"]
    assert isinstance(after, list)
    run.check(len(after) == len(runs) + 1, "the next read includes the record from outside Centrum without restarting it")
    page.reload()
    newest = history_rows(page).nth(1)
    expect(newest).to_contain_text(local_time(after[0]["started_at"]))
    expect(newest).to_contain_text(LAST_COMPLETE)
    expect(newest.locator("[data-slot=badge]", has_text="Zatrzymano")).to_have_attribute("data-variant", "outline")
    expect(newest).to_contain_text(".cmd")
    run.check(True, "the reloaded page shows the DRY-RUN from outside Centrum as the newest Uruchomienie procesu")
    run.capture(page, "26-metryki-nowy-rekord-spoza-centrum")

    run.step(feature, "metryki-pusty-stan")
    moved = [Path(fixture_metrics[name]) for name in ("preparation", "settlement")]
    for path in moved:
        move(path, path.with_name(path.name + ".odlozony"))
    try:
        run.check(run.api("/api/metrics", "metryki-brak-plikow")["runs"] == [], "no metrics files is an empty list")
        page.reload()
        expect(page.get_by_text("Jeszcze nie ma metryk", exact=True)).to_be_visible()
        run.capture(page, "27-metryki-pusty-stan")
    finally:
        for path in moved:
            move(path.with_name(path.name + ".odlozony"), path)


def _drive_cards_unread(run: Run, page: Page, stats: Locator, weeks: int) -> None:
    """Without the metrics the card names no number of weeks: only the server knows it (``recent.weeks``)."""

    page.route(METRICS_ROUTE, lambda route: route.abort())
    page.reload()
    recent_card = stats.get_by_role("group", name="Ostatnie tygodnie", exact=True)
    expect(recent_card).to_contain_text("nie udało się odczytać")
    expect(stats).not_to_contain_text(re.compile(r"\d+\s*tygodni"))
    run.check(True, "a failed read of the metrics leaves „Ostatnie tygodnie” without a number and „nie udało się odczytać”")
    run.capture(page, "2c-metryki-karty-okresow-bez-odczytu")
    page.unroute(METRICS_ROUTE)
    page.reload()
    expect(stats.get_by_role("group", name=f"Ostatnie {weeks} tygodni", exact=True)).to_be_visible()
    run.check(True, f"the next read of the metrics brings back „Ostatnie {weeks} tygodni”")


def _chart_runs(runs: list[dict[str, Any]], process: str, mode: str) -> list[dict[str, Any]]:
    """The runs on the chart, newest first as the API lists them; the chart shows them oldest on the left."""

    return [entry for entry in runs if (entry["process"], entry["mode"]) == (process, mode)][:CHART_RUNS]


def _phase_ms(entry: dict[str, Any], phase: str) -> int:
    return next((item["duration_ms"] for item in entry["phase_durations"] if item["phase"] == phase), 0)


def _measured(phases: list[str], shown: list[dict[str, Any]]) -> list[str]:
    """Phases that lasted in at least one shown run (a DRY-RUN has no Zapisywanie)."""

    return [phase for phase in phases if any(_phase_ms(entry, phase) > 0 for entry in shown)]


def _stop_word(entry: dict[str, Any]) -> str:
    """„błąd” for a stop „do Maksa”, „zatrzymano” for every other stop, also an old one without a kind."""

    return "błąd" if entry["stop_kind"] == "for_maks" else "zatrzymano"


def _bar_title(entry: dict[str, Any]) -> str:
    stopped = f" · {_stop_word(entry)}" if entry["result"] == "BLAD_KRYTYCZNY" else ""
    return f"{local_time(entry['started_at'])} · okres {entry['period']}{stopped}"


def _drive_stop_kinds(run: Run, page: Page, runs: list[dict[str, Any]]) -> None:
    """Historia: a stop „dla taty” and an old one without a kind are a calm outlined „Zatrzymano”, „do Maksa” a red „Błąd”."""

    stops = [entry for entry in runs if entry["result"] == "BLAD_KRYTYCZNY"]
    kinds = {entry["stop_kind"] for entry in stops}
    run.check(kinds == {"for_tata", "for_maks", None}, f"the fixture has every kind of stop: {sorted(map(str, kinds))}")
    rows = history_rows(page)
    expect(rows).to_have_count(1 + min(20, len(runs)))
    for entry in stops:
        row = rows.filter(has_text=local_time(entry["started_at"])).filter(has_text=entry["period"])
        word, variant = ("Błąd", "destructive") if entry["stop_kind"] == "for_maks" else ("Zatrzymano", "outline")
        expect(row.locator("[data-slot=badge]", has_text=word)).to_have_attribute("data-variant", variant)
    run.check(True, "Historia: „Zatrzymano” outlined for „dla taty” and the old record, „Błąd” red for „do Maksa”")
    run.capture(page, "2b-metryki-rodzaj-zatrzymania")


def _bar_name(entry: dict[str, Any], measured: list[str]) -> str:
    """The bar's accessible name: its details, as a screen reader reads them."""

    times = ", ".join(f"{phase} {_seconds(_phase_ms(entry, phase))}" for phase in measured)
    return f"{_bar_title(entry)}. {times}"


def _check_chart(run: Run, chart: Locator, phases: list[str], shown: list[dict[str, Any]], label: str) -> None:
    measured = _measured(phases, shown)
    bars = chart.get_by_role("button")
    expect(bars).to_have_count(len(shown))
    for index, entry in enumerate(reversed(shown)):
        expect(bars.nth(index)).to_have_accessible_name(_bar_name(entry, measured))
        segments = sum(1 for phase in measured if _phase_ms(entry, phase) > 0)
        expect(bars.nth(index).locator("[data-phase]")).to_have_count(segments)
    stopped = sum(1 for entry in shown if entry["result"] == "BLAD_KRYTYCZNY")
    expect(chart.get_by_text(re.compile(r"^\d\d\.\d\d ✕$"))).to_have_count(stopped)
    expect(chart.get_by_role("list", name="Etapy").get_by_role("listitem")).to_have_text(measured)
    run.check(
        True, f"{label}: {len(shown)} bars oldest first, a segment per lasting phase, {stopped} marked ✕, legend {measured}"
    )


def _check_bar_widths(run: Run, chart: Locator, label: str, *, narrow: bool) -> None:
    edges: list[list[float]] = chart.evaluate(BAR_EDGES)
    widths = [right - left for left, right in edges]
    gaps = [later[0] - earlier[1] for earlier, later in pairwise(edges)]
    run.check(
        len(edges) > 1
        and min(gaps) > 0
        and max(widths) <= MAX_BAR_PX + 0.5
        and (max(widths) < MAX_BAR_PX if narrow else min(widths) >= MAX_BAR_PX - 0.5),
        f"{label}: {len(edges)} bars {min(widths):.1f}–{max(widths):.1f} px wide (at most {MAX_BAR_PX}), "
        f"the smallest gap between them {min(gaps):.1f} px",
    )


def _drive_narrow_chart(run: Run, page: Page) -> None:
    """In a phone-sized window the bars of the busiest Proces and Tryb get narrower instead of overlapping."""

    with dad_tab(page, viewport=NARROW_VIEWPORT) as narrow:
        narrow.goto(run.url + "#/metryki")
        chart = narrow.get_by_role("figure", name="Wykres czasów etapów")
        expect(chart).to_be_visible()
        narrow.get_by_role("group", name="Proces", exact=True).get_by_role(
            "button", name="Przygotowanie", exact=True
        ).click()
        narrow.get_by_role("group", name="Tryb", exact=True).get_by_role("button", name="RUN", exact=True).click()
        _check_bar_widths(run, chart, f"{NARROW_VIEWPORT['width']} px, Przygotowanie RUN", narrow=True)
        chart.scroll_into_view_if_needed()
        run.capture(narrow, "2a-metryki-wykres-waski")


def _expect_details(details: Locator, entry: dict[str, Any], measured: list[str]) -> None:
    """The bar's details: date, period, „zatrzymano” for a stop, then every measured phase with its time."""

    parts = [_bar_title(entry)] + [text for phase in measured for text in (phase, _seconds(_phase_ms(entry, phase)))]
    expect(details).to_be_visible()
    expect(details).to_have_text(re.compile(r"^\s*" + r"\s*".join(re.escape(part) for part in parts) + r"\s*$"))


def _drive_bar_details(run: Run, page: Page, chart: Locator, phases: list[str], shown: list[dict[str, Any]]) -> None:
    measured = _measured(phases, shown)
    stopped = next(entry for entry in shown if entry["result"] == "BLAD_KRYTYCZNY")
    newest, previous = shown[0], shown[1]
    details = page.get_by_role("tooltip")
    expect(page.get_by_role("button", name="Włącz motyw jasny", exact=True)).to_be_visible()

    stopped_bar = chart.get_by_role("button", name=_bar_name(stopped, measured), exact=True)
    stopped_bar.hover()
    _expect_details(details, stopped, measured)
    page.mouse.move(4, 4)
    expect(details).to_have_count(0)
    stopped_bar.hover()
    expect(details).to_be_visible()
    page.keyboard.press("Escape")
    expect(details).to_have_count(0)
    page.mouse.move(4, 4)
    run.check(True, "hovering a bar opens its details with „zatrzymano”; leaving the chart and Escape close them")

    with dad_tab(page, touch=True) as touch:
        touch.goto(run.url + "#/metryki")
        touch_chart = touch.get_by_role("figure", name="Wykres czasów etapów")
        touch_details = touch.get_by_role("tooltip")
        touch_chart.get_by_role("button", name=_bar_name(newest, measured), exact=True).tap()
        _expect_details(touch_details, newest, measured)
        touch_chart.get_by_role("button", name=_bar_name(stopped, measured), exact=True).tap()
        _expect_details(touch_details, stopped, measured)
        run.capture(touch, "28-metryki-wykres-szczegoly-ciemny")
        touch.get_by_role("heading", name="Metryki", exact=True).tap()
        expect(touch_details).to_have_count(0)
        run.check(True, "tapping a bar with a finger opens its details, tapping another switches, tapping beside closes")

    page.get_by_role("tab", name="Wykres", exact=True).click()
    newest_bar = chart.get_by_role("button", name=_bar_name(newest, measured), exact=True)
    for _ in range(3):
        page.keyboard.press("Tab")
        if newest_bar.evaluate("(bar) => bar === document.activeElement"):
            break
    expect(newest_bar).to_be_focused()
    _expect_details(details, newest, measured)
    page.keyboard.press("ArrowLeft")
    previous_bar = chart.get_by_role("button", name=_bar_name(previous, measured), exact=True)
    expect(previous_bar).to_be_focused()
    _expect_details(details, previous, measured)
    page.keyboard.press("Escape")
    expect(details).to_have_count(0)
    expect(previous_bar).to_be_focused()
    run.check(True, "Tab reaches the newest bar with its details, arrows move between bars, Escape closes them")

    page.get_by_role("button", name="Włącz motyw jasny", exact=True).click()
    expect(page.get_by_role("button", name="Włącz motyw ciemny", exact=True)).to_be_visible()
    stopped_bar.hover()
    _expect_details(details, stopped, measured)
    run.capture(page, "29-metryki-wykres-szczegoly-jasny")
    page.mouse.move(4, 4)
    page.get_by_role("button", name="Włącz motyw ciemny", exact=True).click()
    expect(page.get_by_role("button", name="Włącz motyw jasny", exact=True)).to_be_visible()
    run.check(True, "the bar details read the same in the light theme")
