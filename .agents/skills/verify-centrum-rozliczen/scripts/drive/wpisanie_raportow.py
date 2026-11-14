"""Drive features/wpisanie-raportow.md."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, Route, ViewportSize, expect

from atrapy.workbooks import excel_lock
from drive.common import (
    DAD_VIEWPORT,
    FOCUS,
    Run,
    active_run_signs,
    choose_periods_directory,
    current_run,
    ended_run_shown,
    figure,
    move,
    open_settings,
    point_in_settings,
    read_bytes,
    read_json,
    remove,
    remove_tree,
    result_of_start,
    run_logs,
    settings_title,
    settings_window,
    stop_banner,
    switch_theme,
)
from drive.waiting import until

FEATURE = "wpisanie-raportow"
BUTTON = "Wpisz raporty z maili"
# The broken INTERMAX of the step `zatrzymanie`: no workbook at all, so the Odczyt danych stops for Dad.
BROKEN = b"to nie jest skoroszyt INTERMAX"
DAY = "2026-10-19"
# The fixture's Raporty wykonawcy of today: what the view shows of each Wykonawca after the first click.
SHOWN = {
    "wykonawca.a": {"orders": 2, "entered": 1, "mails": 1, "problems": 0, "without_report": ["40000102"]},
    "wykonawca.b": {"orders": 1, "entered": 1, "mails": 1, "problems": 1, "without_report": []},
}
# The state of each Wykonawca's tile of today after the first click: wykonawca.a sent a mail without 40000102, so the
# day is `Bez raportu` even though it is today (`Czeka` needs no mail at all); wykonawca.b has Dad's own value.
TILES = {"wykonawca.a": "Bez raportu", "wykonawca.b": "Problem"}
# The orders of today at each Wykonawca after the first click, in the INTERMAX order: number, SKUTECZNE, CZYNNOŚCI
# ZREALIZOWANE and state. Dad's own `montaż ręcznie` stays, so 40000103 is a problem until `Zostaw moją`.
ORDERS = {
    "wykonawca.a": [
        ("40000101", "tak", "wymiana routera", "entered"),
        ("40000102", None, None, "without_report"),
    ],
    "wykonawca.b": [("40000103", "tak", "montaż ręcznie", "problem")],
}
KEPT = {
    "number": "40000103",
    "day": DAY,
    "worker": "wykonawca.b",
    "column": "CZYNNOŚCI ZREALIZOWANE",
    "reported": "montaż anteny",
}
NARROW: ViewportSize = {"width": 390, "height": 844}
# „Przypisz do Wykonawcy…” gives the stranger's address to Wykonawca D of the fixture: he has no orders and no Raport
# today, so his address changes no figure of the click.
ASSIGN = "Przypisz do Wykonawcy…"
ASSIGNED_TO, ASSIGNED_LOGIN = "Wykonawca Testowy D", "wykonawca.d"
WEEKDAYS = ("pn", "wt", "śr", "cz", "pt", "sb", "nd")
MAP = "Mapa Raportów"
# A Uporządkowanie INTERMAX that runs, as the Uruchomienia stream shows it (step `w-czasie-innego`).
OTHER_RUN = {
    "state": "running",
    "run": {
        "id": "weryfikacja-uporzadkowanie-trwa",
        "process": "intermax",
        "title": "Uporządkowanie INTERMAX",
        "period": "",
        "mode": "RUN",
        "pricing": None,
        "confirms_readiness": False,
        "register_name": "INTERMAX",
    },
    "progress": {"phases": [], "template_total": 0, "templates_completed": 0, "current_worker": None, "figures": []},
    "progress_stale": False,
}
# The window of a click on Wednesday 11.11.2026, Narodowe Święto Niepodległości (step `mapa-zakresu`): the fixture's
# clock stands on 19.10.2026, whose window is that day only, so the harness answers the view with this window.
WINDOW_TODAY = "2026-11-11"
WINDOW_FIRST = date(2026, 10, 26)
HOLIDAYS = {"2026-11-01": "Wszystkich Świętych", WINDOW_TODAY: "Narodowe Święto Niepodległości"}
# Days on which wykonawca.c sent a mail but has no orders and no problem: nothing to enter, so an empty cell.
MAIL_ONLY = ("2026-11-07", "2026-11-08")
# Przypomnienia o raporcie za 05.11 do wykonawca.b, 06.11 at 8:00 and 18:00 in Dad's time (UTC+1 in November).
REMINDERS = ("2026-11-06T07:00:00Z", "2026-11-06T17:00:00Z")
HANDED_REMINDER = ("2026-11-04T07:00:00Z",)
"""The Przypomnienie of `wykonawca.a` for 03.11, before his late Raport: one popover with a note and a Przypomnienie."""
WINDOW_WORKERS = ("wykonawca.a", "wykonawca.b", "wykonawca.c")

Json = dict[str, Any]


def _button(page: Page) -> Locator:
    """The main button of Raporty, in the page header next to the heading."""

    return page.get_by_role("main").get_by_role("button", name=BUTTON, exact=True)


def _to_reports(page: Page) -> None:
    """Dad opens Raporty from the menu, as a fresh read of the page."""

    page.get_by_role("list", name="Sekcje Centrum rozliczeń").get_by_role("link", name="Raporty", exact=True).click()
    page.reload()
    expect(page.get_by_role("heading", name="Raporty", exact=True)).to_be_visible()


def _to_setup(run: Run, page: Page, name: str) -> None:
    """Uruchomienia with the setup cards: `Nowe Uruchomienie procesu` first when an ended Uruchomienie is shown."""

    page.goto(run.url + "#/uruchomienia")
    page.reload()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    if ended_run_shown(current_run(run, name)):
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    expect(page.get_by_role("region", name="Uporządkuj INTERMAX", exact=True)).to_be_visible()


def _choose(run: Run, page: Page, path: str) -> None:
    """Dad points INTERMAX (the Rejestr zleceń) to ``path`` in Ustawienia over Raporty (harness answers the picker)."""

    point_in_settings(run, page, "Rejestr zleceń", path)


def _short(day: str) -> str:
    """`2026-11-03` → `wt. 03.11`, as the Mapa cieplna names a day."""

    weekday = WEEKDAYS[date.fromisoformat(day).weekday()]
    return f"{weekday}. {day[8:10]}.{day[5:7]}"


def _map(page: Page) -> Locator:
    return page.get_by_role("table", name=MAP, exact=True)


def _row(page: Page, worker: str) -> Locator:
    return _map(page).get_by_role("row", name=worker, exact=True)


def _tile(page: Page, worker: str, day: str) -> Locator:
    """The tile of ``worker`` on ``day``: a button whose name starts with the Wykonawca and the day."""

    return _row(page, worker).get_by_role("button", name=f"{worker}, {_short(day)}: ")


def _tile_is(page: Page, worker: str, day: str, state: str, entered: int, orders: int) -> None:
    expect(_tile(page, worker, day)).to_have_accessible_name(
        f"{worker}, {_short(day)}: {state}, wpisane {entered} z {orders}"
    )


def _popover(page: Page, worker: str, day: str) -> Locator:
    """Dad clicks the tile; its popover with the day's figures and orders."""

    _tile(page, worker, day).click()
    popover = page.get_by_role("dialog", name=f"{worker}, {_short(day)}", exact=True)
    expect(popover).to_be_visible()
    return popover


def _close(page: Page, popover: Locator) -> None:
    """Escape closes ``popover``; a toast of the Wpisanie is a dialog too, so only this one is waited for."""

    page.keyboard.press("Escape")
    expect(popover).to_have_count(0)


def _figures(popover: Locator, shown: Json) -> None:
    for label, key in (("Zlecenia", "orders"), ("Wpisane", "entered"), ("Maile", "mails")):
        expect(popover.get_by_label(f"{label} {shown[key]}", exact=True)).to_be_visible()


def _range(page: Page) -> Locator:
    return page.get_by_role("group", name="Zakres dni", exact=True)


def _day_columns(page: Page) -> int:
    """Columns of days on the Mapa cieplna: every column header but `Wykonawca` and `Wpisane`."""

    return _map(page).get_by_role("columnheader").count() - 2


def _assign_stranger(run: Run, page: Page, address: str) -> None:
    """„Przypisz do Wykonawcy…” at the stranger's Raport opens Ustawienia on Wykonawcy with a choice for that address; a
    Wykonawca chosen there gets the address at once, and Raporty say whom it went to without a reload. „Cofnij” in
    Historia takes it back, so the Lista Wykonawców is the fixture's again for the next steps."""

    run.step(FEATURE, "przypisanie-nadawcy")
    worker_list = run.config / "wykonawcy.yaml"
    before = read_bytes(worker_list)
    region = page.get_by_role("region", name="Spoza listy adresów")
    expect(region.get_by_role("button", name=ASSIGN, exact=True)).to_be_visible()
    run.capture(page, "414-raporty-przypisz")
    region.get_by_role("button", name=ASSIGN, exact=True).click()
    window = settings_window(page)
    expect(settings_title(page)).to_have_text("Ustawienia/Wykonawcy")
    chooser = window.get_by_role("group", name="Przypisz adres")
    expect(chooser).to_contain_text(address)
    run.check(read_bytes(worker_list) == before, "„Przypisz do Wykonawcy…” opens the choice and saves nothing")
    run.capture(page, "415-raporty-przypisz-wybor", full_page=False)
    page.set_viewport_size(NARROW)
    try:
        expect(chooser.get_by_role("combobox", name="Wykonawca")).to_be_visible()
        page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.check(True, "on a narrow window the choice fits without a horizontal scroll")
        run.capture(page, "417-raporty-przypisz-wybor-waski", full_page=False)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)
    chooser.get_by_role("combobox", name="Wykonawca").click()
    page.get_by_role("option", name=ASSIGNED_TO, exact=True).click()
    expect(chooser).to_have_count(0)
    workers = run.api("/api/settings", "raporty-przypisany-ustawienia")["workers"]
    assert isinstance(workers, dict)
    addresses = {worker["name"]: worker["addresses"] for worker in workers["workers"]}
    run.check(address in addresses[ASSIGNED_TO], "the choice saves the address at the Wykonawca at once")
    window.get_by_role("button", name="Zamknij Ustawienia").click()
    expect(window).to_have_count(0)
    expect(region).to_contain_text(f"Przypisany do {ASSIGNED_LOGIN}.")
    expect(region.get_by_role("button", name=ASSIGN, exact=True)).to_have_count(0)
    [sender] = _view(run, "raporty-przypisany")["unknown_senders"]
    run.check(
        (sender["sender"], sender["worker"]) == (address, ASSIGNED_LOGIN),
        "Raporty, without a reload, show the stranger as assigned to the Wykonawca; the next click enters the Raport",
    )
    run.capture(page, "416-raporty-przypisany")
    window = open_settings(page, "Historia")
    newest = window.get_by_role("list", name="Zmiany").get_by_role("listitem").first
    newest.get_by_role("button", name=f"Cofnij: wykonawcy[{ASSIGNED_LOGIN}]", exact=True).click()
    until(lambda: read_bytes(worker_list) == before, "„Cofnij” in Historia takes the address back")
    window.get_by_role("button", name="Zamknij Ustawienia").click()
    expect(window).to_have_count(0)
    expect(region.get_by_role("button", name=ASSIGN, exact=True)).to_be_visible()
    run.check(True, "after „Cofnij” the stranger is unknown again in Raporty")


def _view(run: Run, name: str) -> Json:
    view = run.api("/api/report-entering/view", name)
    assert isinstance(view, dict)
    return view


def _days_of(view: Json) -> dict[str, Json]:
    """Each Wykonawca's day ``DAY`` of the view, which has the whole window of the last click."""

    return {worker["worker"]: day for worker in view["workers"] for day in worker["days"] if day["day"] == DAY}


def _workers(view: Json) -> dict[str, Json]:
    return {
        worker: {
            "orders": day["orders"],
            "entered": day["entered"],
            "mails": day["mails"],
            "problems": len(day["problems"]),
            "without_report": day["without_report"],
        }
        for worker, day in _days_of(view).items()
    }


def _orders(view: Json) -> dict[str, list[tuple[str, str | None, str | None, str]]]:
    return {
        worker: [
            (order["number"], order["successful"], order["activities"], order["state"])
            for order in day["orders_detail"] or []
        ]
        for worker, day in _days_of(view).items()
    }


def _entering_logs(run: Run) -> list[Json]:
    return [log["report_entering"] for log in run_logs(run, "report_entering").values()]


def _tiles_match(page: Page, view: Json, tiles: dict[str, str]) -> None:
    """Each Wykonawca's tile of today and his ring say what the server's view says (``tiles``: the expected state)."""

    for worker, day in _workers(view).items():
        _tile_is(page, worker, DAY, tiles[worker], day["entered"], day["orders"])
        expect(_row(page, worker).get_by_label(f"Wpisane {day['entered']} z {day['orders']}", exact=True)).to_be_visible()


def _order(number: str, state: str) -> Json:
    entered = state == "entered"
    return {
        "number": number,
        "successful": "tak" if entered else None,
        "activities": "wymiana routera" if entered else None,
        "state": state,
    }


def _window_day(
    day: str,
    number: int,
    orders: int,
    *,
    without: int = 0,
    problem: bool = False,
    mails: int = 1,
    taken: bool = False,
    added: bool = False,
    reminders: tuple[str, ...] = (),
) -> Json:
    """A synthetic day of a Wykonawca: ``orders`` orders from ``number``, the last ``without`` without a report, with
    ``problem`` the first one a problem without `Zostaw moją`, with ``taken`` the last one taken over from
    `wykonawca.a` (`TAKEN_NOTE`, a Przeniesienie zlecenia, #1347), with ``added`` the last one a Zlecenie dopisane z
    raportu without `ADRES` (`ADDED_NOTE`, #1354), and the moments of its Przypomnienia o raporcie."""

    numbers = [str(number + offset) for offset in range(orders)]
    states = ["entered"] * (orders - without) + ["without_report"] * without
    if problem:
        states[0] = "problem"
    return {
        "day": day,
        "orders": orders,
        "entered": states.count("entered"),
        "mails": mails,
        "without_report": numbers[orders - without :],
        "problems": [
            {
                "reason": f"Raport wykonawcy z {day[8:10]}.{day[5:7]}.{day[:4]} ma dla zlecenia {numbers[0]} różne Wpisy.",
                "number": numbers[0],
                "keep": None,
            }
        ]
        if problem
        else [],
        "notes": [
            *([{"number": numbers[-1], "text": TAKEN_NOTE}] if taken else []),
            *([{"number": numbers[-1], "text": ADDED_NOTE}] if added else []),
        ],
        "orders_detail": [_order(found, state) for found, state in zip(numbers, states, strict=True)],
        "reminders": list(reminders),
    }


TAKEN_NOTE = "przejęte od wykonawca.a"
"""The calm note of a Przeniesienie zlecenia in the popover of `wykonawca.b` 03.11 (#1347)."""
HANDED_NOTE = "przekazane wykonawca.b"
"""The other side of it in the popover of `wykonawca.a` 03.11: a row of its own, because the order is no longer there."""
ADDED_NOTE = "dopisane z raportu, uzupełnij resztę"
"""The calm note of a Zlecenie dopisane z raportu without `ADRES` in the popover of `wykonawca.c` 09.11 (#1354)."""


def _window_view(clicked_at: str) -> Json:
    """The view of a click on 11.11.2026 with the window from 26.10 (harness): wykonawca.a waits for yesterday's
    Raport, wykonawca.b has a problem on 03.11 and an order without a report on 05.11, wykonawca.c is complete and
    sent a mail without orders on Saturday 07.11 and Sunday 08.11 (`MAIL_ONLY`)."""

    days = [(WINDOW_FIRST + timedelta(days=offset)).isoformat() for offset in range(17)]
    workdays = [day for day in days if date.fromisoformat(day).weekday() < 6 and day not in HOLIDAYS]
    special: dict[tuple[str, str], dict[str, Any]] = {
        ("wykonawca.a", "2026-11-03"): {"orders": 2, "reminders": HANDED_REMINDER},
        ("wykonawca.a", "2026-11-10"): {"orders": 3, "without": 3, "mails": 0},
        ("wykonawca.b", "2026-11-03"): {"orders": 3, "problem": True, "taken": True},
        ("wykonawca.b", "2026-11-05"): {"orders": 2, "without": 1, "reminders": REMINDERS},
        ("wykonawca.c", "2026-11-09"): {"orders": 4, "added": True},
        **{("wykonawca.c", day): {"orders": 0} for day in MAIL_ONLY},
    }
    workers = []
    tiles: dict[tuple[str, str], Json] = {}
    for index, worker in enumerate(WINDOW_WORKERS):
        worker_days = []
        for position, day in enumerate(day for day in days if day in workdays or (worker, day) in special):
            shape: dict[str, Any] = special.get((worker, day), {"orders": index + 2})
            tiles[worker, day] = _window_day(day, 40100000 + index * 1000 + position * 10, **shape)
            worker_days.append(tiles[worker, day])
        workers.append({"worker": worker, "days": worker_days})
    [taken] = tiles["wykonawca.b", "2026-11-03"]["notes"]
    tiles["wykonawca.a", "2026-11-03"]["notes"].append({"number": taken["number"], "text": HANDED_NOTE})
    return {
        "clicked_at": clicked_at,
        "today": WINDOW_TODAY,
        "days": [{"day": day, "holiday": HOLIDAYS.get(day)} for day in days],
        "workers": workers,
        "unknown_senders": [],
        "reminders_without_footer": True,
    }


def _other_process_running(run: Run, page: Page) -> None:
    """While another Uruchomienie procesu runs (the Uruchomienia stream, harness), the header button is off."""

    run.step(FEATURE, "w-czasie-innego")
    event = json.dumps({"sequence": 1, "view": OTHER_RUN}, ensure_ascii=False)

    def running(route: Route) -> None:
        route.fulfill(
            status=200,
            headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
            body=f"data: {event}\n\n",
        )

    print("  harness: the Uruchomienia stream shows a Uporządkowanie INTERMAX that runs", flush=True)
    page.route("**/api/runs/events", running)
    try:
        _reload_settled(page)
        expect(active_run_signs(page, "Trwa Uruchomienie")[1]).to_be_visible()
        expect(_button(page)).to_be_disabled()
        expect(page.get_by_role("alert")).to_have_count(0)
        run.check(True, "while another Uruchomienie procesu runs, `Wpisz raporty z maili` is off")
        run.capture(page, "287-raporty-w-czasie-innego", live=True)  # the menu sign of the run turns while it runs
    finally:
        page.unroute("**/api/runs/events")
    _reload_settled(page)
    expect(_button(page)).to_be_enabled()
    run.check(True, "with no Uruchomienie running the button is on again")


def _reload_settled(page: Page) -> None:
    """Reloads Raporty and waits until the page shows the setup of the button: before it is read the button is off
    anyway, so a check of „off” right after a reload would pass whatever the stream says."""

    with page.expect_response(
        lambda response: response.url.endswith("/api/report-entering") and response.request.method == "GET"
    ) as answered:
        page.reload()
    answered.value.body()
    expect(page.get_by_role("heading", name="Raporty", exact=True)).to_be_visible()
    # Two frames after the answer: React has shown it, so the button's state is the one the page settled on.
    page.evaluate("() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")


def _range_map(run: Run, page: Page) -> None:
    """Range, calendar and the Status filter on a window of 17 days with two holidays and two Sundays (harness)."""

    run.step(FEATURE, "mapa-zakresu")
    real = _view(run, "raporty-mapa-prawdziwy")
    window = _window_view(real["clicked_at"] or "2026-11-11T06:58:00Z")
    (run.evidence / "api" / "raporty-mapa-okno.json").write_text(
        json.dumps(window, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("  harness: the view answers a window of 26.10–11.11.2026 (api/raporty-mapa-okno.json)", flush=True)
    page.route(
        "**/api/report-entering/view",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(window)),
    )
    try:
        page.goto(run.url + "#/raporty")
        page.reload()
        expect(_range(page)).to_contain_text("2–11 lis")
        expect(page.get_by_role("button", name="Późniejsze dni", exact=True)).to_be_disabled()
        expect(_map(page).get_by_role("row")).to_have_count(1 + len(WINDOW_WORKERS))
        run.check(_day_columns(page) == 10, "by default the range is Monday of last week to today: 2–11.11")
        holiday = _map(page).get_by_role("columnheader", name="śr. 11.11, święto: Narodowe Święto Niepodległości")
        expect(holiday).to_have_text("11Św.")
        sundays = _map(page).locator('td[data-day="2026-11-08"].niedziela')
        expect(sundays).to_have_count(len(WINDOW_WORKERS))
        run.check(True, "11.11 has the holiday column with „Św.” and Sunday 08.11 is struck through in every row")
        for day in MAIL_ONLY:
            expect(_row(page, "wykonawca.c").locator(f'td[data-day="{day}"]')).to_be_empty()
        run.check(True, "a day with a mail but no orders and no problem is an empty cell, on Sunday struck through")
        run.capture(page, "293-raporty-mapa-bez-popovera", full_page=False)
        _tile_is(page, "wykonawca.a", "2026-11-10", "Czeka", 0, 3)
        _tile_is(page, "wykonawca.b", "2026-11-03", "Problem", 2, 3)
        _tile_is(page, "wykonawca.b", "2026-11-05", "Bez raportu", 1, 2)
        _tile_is(page, "wykonawca.c", "2026-11-09", "Komplet", 4, 4)
        expect(_row(page, "wykonawca.a").get_by_label("Wpisane 14 z 17", exact=True)).to_be_visible()
        expect(_row(page, "wykonawca.b")).to_contain_text("1 problem · 1 bez raportu")
        expect(_row(page, "wykonawca.a")).to_contain_text("Czeka na raport")
        run.check(True, "yesterday without a mail waits, an older order without a report is yellow, rings count the range")
        was_dark = switch_theme(page, "jasny")
        try:
            popover = _popover(page, "wykonawca.b", "2026-11-03")
            expect(popover).to_contain_text("różne Wpisy")
            expect(popover.get_by_role("button", name="Zostaw moją")).to_have_count(0)
            taken = popover.get_by_role("listitem").filter(has_text=TAKEN_NOTE)
            expect(taken).to_have_count(1)
            expect(taken).to_contain_text("Wpisane")
            expect(taken).not_to_contain_text("Problem")
            run.capture(page, "288-raporty-mapa-jasna", full_page=False)
            _close(page, popover)
            popover = _popover(page, "wykonawca.a", "2026-11-03")
            handed = popover.get_by_role("listitem").filter(has_text=HANDED_NOTE)
            expect(handed).to_have_count(1)
            expect(handed).not_to_contain_text("Wpisane")
            expect(handed).not_to_contain_text("Problem")
            _close(page, popover)
            switch_theme(page, "ciemny")
            popover = _popover(page, "wykonawca.b", "2026-11-03")
            run.capture(page, "289-raporty-mapa-ciemna", full_page=False)
            _close(page, popover)
        finally:
            switch_theme(page, "ciemny" if was_dark else "jasny")
        run.check(
            True,
            "the popover of a tile shows the problem's sentence and, under the taken order, the calm note "
            "„przejęte od wykonawca.a” without a Problem badge, in the light and the dark theme; the popover of "
            "wykonawca.a shows „przekazane wykonawca.b” as a row of its own, without a badge",
        )

        run.step(FEATURE, "przypomnienia")
        expect(page.get_by_text("Przypomnienia o raporcie idą bez Twojej stopki", exact=False)).to_be_visible()
        popover = _popover(page, "wykonawca.b", "2026-11-05")
        expect(popover).to_contain_text("Przypomnienia 06.11 08:00, 06.11 18:00")
        run.capture(page, "294-raporty-przypomnienia", full_page=False)
        _close(page, popover)
        popover = _popover(page, "wykonawca.b", "2026-11-03")
        expect(popover.get_by_text("Przypomnieni", exact=False)).to_have_count(0)
        _close(page, popover)
        popover = _popover(page, "wykonawca.a", "2026-11-03")
        expect(popover.get_by_role("listitem").filter(has_text=HANDED_NOTE)).to_have_count(1)
        expect(popover).to_contain_text("Przypomnienie 04.11 08:00")
        run.capture(page, "295-raporty-przypomnienie-i-przeniesienie", full_page=False)
        _close(page, popover)
        popover = _popover(page, "wykonawca.c", "2026-11-09")
        added = popover.get_by_role("listitem").filter(has_text=ADDED_NOTE)
        expect(added).to_have_count(1)
        expect(added).to_contain_text("Wpisane")
        expect(added).not_to_contain_text("Problem")
        run.capture(page, "296-raporty-dopisane", full_page=False)
        _close(page, popover)
        run.check(
            True,
            "the popover of 05.11 has the times of its Przypomnienia in Dad's time, 03.11 none; the page says the "
            "footer file is missing; the popover of wykonawca.a 03.11 has both „przekazane wykonawca.b” and its "
            "Przypomnienie; the popover of wykonawca.c 09.11 has „dopisane z raportu, uzupełnij resztę” under its last "
            "order, entered and without a Problem badge (#1354)",
        )

        page.get_by_role("button", name="Wcześniejsze dni", exact=True).click()
        expect(_range(page)).to_contain_text("26 paź – 4 lis")
        run.check(page.url.endswith("#/raporty/2026-10-26/2026-11-04"), "the arrow moves the range by its length")
        expect(page.get_by_role("button", name="Wcześniejsze dni", exact=True)).to_be_disabled()
        expect(_map(page).get_by_role("columnheader", name="nd. 01.11, święto: Wszystkich Świętych")).to_be_visible()
        page.reload()
        expect(_range(page)).to_contain_text("26 paź – 4 lis")
        run.check(_day_columns(page) == 10, "a reload keeps the range of the address")
        page.get_by_role("button", name="Późniejsze dni", exact=True).click()
        expect(_range(page)).to_contain_text("2–11 lis")
        page.go_back()
        expect(_range(page)).to_contain_text("26 paź – 4 lis")
        page.go_forward()
        expect(_range(page)).to_contain_text("2–11 lis")
        expect(page.get_by_role("button", name="Późniejsze dni", exact=True)).to_be_disabled()
        run.check(True, "the arrows change columns and address, Back returns, and each arrow is off at its window end")

        page.get_by_role("button", name="Wybierz dni w kalendarzu", exact=True).click()
        calendar = page.get_by_role("dialog", name="Kalendarz dni", exact=True)
        expect(calendar.locator('button[data-day="12.11.2026"]')).to_be_disabled()
        calendar.locator('button[data-day="3.11.2026"]').click()
        expect(calendar).to_contain_text("Kliknij ostatni dzień")
        calendar.locator('button[data-day="6.11.2026"]').hover()
        run.capture(page, "290-raporty-kalendarz", full_page=False)
        calendar.locator('button[data-day="6.11.2026"]').click()
        expect(calendar).to_have_count(0)
        expect(_range(page)).to_contain_text("3–6 lis")
        run.check(
            page.url.endswith("#/raporty/2026-11-03/2026-11-06") and _day_columns(page) == 4,
            "two clicks in the calendar choose 03–06.11; days outside the window are off",
        )

        page.get_by_role("button", name="Status", exact=False).click()
        menu = page.get_by_role("dialog", name="Pokaż w widoku", exact=True)
        expect(menu.get_by_role("button", name="Problem 1", exact=True)).to_be_visible()
        expect(menu.get_by_role("button", name="Bez raportu 1", exact=True)).to_be_visible()
        expect(menu.get_by_role("button", name="Czeka 0", exact=True)).to_be_visible()
        menu.get_by_role("button", name="Problem 1", exact=True).click()
        expect(menu.get_by_role("button", name="Problem 1", exact=True)).to_have_attribute("aria-pressed", "true")
        expect(_map(page).get_by_role("row")).to_have_count(2)
        expect(page.get_by_text("1 z 3 Wykonawców", exact=True)).to_be_visible()
        dimmed = _tile(page, "wykonawca.b", "2026-11-05").evaluate("tile => Number(getComputedStyle(tile).opacity)")
        kept = _tile(page, "wykonawca.b", "2026-11-03").evaluate("tile => Number(getComputedStyle(tile).opacity)")
        run.check(
            dimmed < 0.5 and kept == 1,
            f"Status Problem leaves wykonawca.b and dims his other tiles (opacity {dimmed} vs {kept})",
        )
        run.capture(page, "291-raporty-status", full_page=False)
        menu.get_by_role("button", name="Pokaż wszystko", exact=True).click()
        expect(_map(page).get_by_role("row")).to_have_count(1 + len(WINDOW_WORKERS))
        _close(page, menu)
        run.check(True, "„Pokaż wszystko” takes the filter off")

        page.get_by_role("button", name="Wybierz dni w kalendarzu", exact=True).click()
        page.get_by_role("button", name="Bieżące dwa tygodnie", exact=True).click()
        expect(calendar).to_have_count(0)
        expect(_range(page)).to_contain_text("2–11 lis")
        run.check(page.url.endswith("#/raporty/2026-11-02/2026-11-11"), "„Bieżące dwa tygodnie” returns to the default range")

        page.set_viewport_size(NARROW)
        try:
            _narrow_layout(run, page, "the Mapa cieplna of the window")
            run.capture(page, "292-raporty-mapa-waska", full_page=False)
        finally:
            page.set_viewport_size(DAD_VIEWPORT)
    finally:
        page.unroute("**/api/report-entering/view")
    page.goto(run.url + "#/raporty")
    page.reload()
    expect(_range(page)).to_contain_text("19 paź")


def _narrow_layout(run: Run, page: Page, what: str) -> None:
    """At 390 px the page does not scroll sideways, the header keeps its button and range bar and the toolbar its
    search and Status inside the screen, and the table scrolls sideways inside its card."""

    expect(_map(page)).to_be_visible()
    width = page.evaluate("document.documentElement.scrollWidth")
    # The page's own width: the viewport less the scrollbar gutter Centrum keeps.
    inside = page.evaluate("document.documentElement.clientWidth")
    container = _map(page).locator("xpath=..")
    scrolls = container.evaluate("box => box.scrollWidth > box.clientWidth")
    boxes = [
        part.bounding_box()
        for part in (
            _button(page),
            _range(page),
            page.get_by_role("button", name="Wybierz dni w kalendarzu", exact=True),
            page.get_by_label("Szukaj Wykonawcy", exact=True),
            page.get_by_role("button", name="Status", exact=False),
        )
    ]
    run.check(
        width <= inside
        and scrolls
        and all(box is not None and box["x"] >= 0 and box["x"] + box["width"] <= inside for box in boxes),
        f"on a narrow screen {what} scrolls sideways inside its card, while the page, the header and the toolbar stay "
        f"inside the screen (page {width} px, table scrolls {scrolls}, boxes {boxes})",
    )


def drive(run: Run, page: Page) -> None:
    fixture = run.fixture["report_entering"]
    register = Path(fixture["register"])
    stranger = Path(fixture["stranger"])
    aside = run.root / "maile-odlozone" / stranger.name
    before_feature = run.remembered("rejestr_zlecen")
    saved = run.settings_text()
    logs_before = len(_entering_logs(run))

    run.step(FEATURE, "bez-karty-w-uruchomieniach")
    settings = run.api("/api/settings", "raporty-ustawienia")
    if settings["periods_directory"] == {"state": "not_set"}:
        page.goto(run.url + "#/okresy")
        choose_periods_directory(run, page)
    _to_setup(run, page, "raporty-uruchomienia")
    expect(page.get_by_role("region", name=BUTTON, exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name=BUTTON, exact=True)).to_have_count(0)
    run.check(True, "Uruchomienia have the card of Uporządkowanie INTERMAX and no card or button Wpisz raporty z maili")

    run.step(FEATURE, "przycisk")
    _to_reports(page)
    _choose(run, page, str(register))
    _to_reports(page)
    expect(_button(page)).to_be_enabled()
    expect(page.get_by_role("group", name="INTERMAX", exact=True)).to_contain_text(register.name)
    expect(page.get_by_role("alert")).to_have_count(0)
    setup = run.api("/api/report-entering", "raporty-przycisk")
    run.check(
        setup["blocker"] is None and setup["open_in_excel"] == [],
        "the button in the header of Raporty is on with the INTERMAX of the fixture and the folder okresów",
    )
    run.capture(page, "280-raporty-przycisk")

    _other_process_running(run, page)

    run.step(FEATURE, "widok-przed-kliknieciem")
    first_view = _view(run, "raporty-widok-przed")
    if first_view["clicked_at"] is None:
        expect(page.get_by_text("Jeszcze nie ma Raportów", exact=True)).to_be_visible()
        expect(page.get_by_text("Kliknij „Wpisz raporty z maili” powyżej.", exact=True)).to_be_visible()
    run.check(
        first_view["today"] == DAY and {"day": DAY, "holiday": None} in first_view["days"],
        "the view has today, 19.10.2026, among the days of its window, without a holiday",
    )

    run.step(FEATURE, "blokada")
    lock = excel_lock(register)
    lock.touch()
    print(f"  harness: Excel opens {register.name}, so its lock file is next to it; Dad returns to Centrum", flush=True)
    try:
        page.evaluate(FOCUS)
        expect(page.get_by_role("alert").filter(has_text="jest otwarty w Excelu")).to_be_visible()
        expect(_button(page)).to_be_disabled()
        open_in_excel = run.api("/api/report-entering", "raporty-blokada")["open_in_excel"]
        run.check(
            isinstance(open_in_excel, list) and len(open_in_excel) == 1 and lock.name in open_in_excel[0],
            "INTERMAX open in Excel turns the button off and the sentence under the header names its lock file",
        )
        run.capture(page, "285-raporty-blokada")
    finally:
        remove(lock, missing_ok=True)
    page.evaluate(FOCUS)
    expect(_button(page)).to_be_enabled()
    expect(page.get_by_role("alert")).to_have_count(0)

    run.step(FEATURE, "klikniecie")
    register_before = read_bytes(register)
    result = result_of_start(run, "raporty-wynik", _button(page).click)
    summary = result["summary"]
    run.check(
        (figure(summary, "Wpisane"), figure(summary, "Problemy"), figure(summary, "Raporty")) == (2, 2, 2),
        "the click writes the Raporty of both Wykonawcy and has two problems: Dad's own value and a stranger",
    )
    run.check(read_bytes(register) != register_before, "INTERMAX is written on disk")
    # No reload: the end of the Wpisanie read the view again by itself.
    _tiles_match(page, _view(run, "raporty-po-kliknieciu"), TILES)
    expect(_button(page)).to_be_enabled()
    run.check(True, "Raporty show the result of the click without a reload, and the button is on again")
    page.get_by_role("list", name="Sekcje Centrum rozliczeń").get_by_role("link", name="Uruchomienia", exact=True).click()
    live = page.get_by_role("region", name="Podgląd na żywo")
    live.get_by_role("button", name="Otwórz Raporty", exact=True).click()

    run.step(FEATURE, "widok")
    expect(page.get_by_role("heading", name="Raporty", exact=True)).to_be_visible()
    expect(_range(page)).to_contain_text("19 paź")
    view = _view(run, "raporty-widok")
    run.check(_workers(view) == SHOWN, "the view has each Wykonawca of the day with the figures of the click")
    run.check(
        view["days"] == [{"day": DAY, "holiday": None}] and _orders(view) == ORDERS,
        "the view has the window of the click and at each Wykonawca the orders of the day as INTERMAX has them after "
        "the click, with Dad's own value and its state",
    )
    run.check(_day_columns(page) == 1, "the Mapa cieplna has the one day of the window")
    _tiles_match(page, view, TILES)
    run.check(True, "each tile and ring match the server's view: wpisane of zlecenia and the state of the day")
    [unknown] = view["unknown_senders"]
    run.check(unknown["sender"] == fixture["stranger_address"], "the Raport from outside the list shows its address")
    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    run.check(
        menu.get_by_role("link").all_inner_texts()[:3] == ["Okresy", "Uruchomienia", "Raporty"],
        "Raporty is a menu section right after Uruchomienia",
    )
    expect(menu.get_by_role("link", name="Raporty", exact=True)).to_have_attribute("aria-current", "page")
    expect(page.get_by_role("link", name="Uruchomienia", exact=True)).to_have_count(1)
    popover = _popover(page, "wykonawca.a", DAY)
    _figures(popover, SHOWN["wykonawca.a"])
    orders = popover.get_by_role("list", name="Zlecenia dnia")
    expect(orders.get_by_role("listitem")).to_have_count(2)
    expect(orders.get_by_role("listitem").nth(0)).to_contain_text("40000101")
    expect(orders.get_by_role("listitem").nth(0)).to_contain_text("tak")
    expect(orders.get_by_role("listitem").nth(0)).to_contain_text("wymiana routera")
    expect(orders.get_by_role("listitem").nth(1)).to_contain_text("40000102")
    expect(orders.get_by_role("listitem").nth(1)).to_contain_text("Brak Wpisu w raporcie")
    expect(orders.get_by_role("listitem").nth(1)).to_contain_text("Bez raportu")
    run.check(True, "the popover of wykonawca.a has his figures and the orders of the day in the INTERMAX order")
    _close(page, popover)
    popover = _popover(page, "wykonawca.b", DAY)
    _figures(popover, SHOWN["wykonawca.b"])
    expect(popover.get_by_role("list", name="Zlecenia dnia")).to_contain_text("montaż ręcznie")
    keep = popover.get_by_role("button", name="Zostaw moją", exact=True)
    expect(keep).to_be_visible()
    expect(page.get_by_role("region", name="Spoza listy adresów")).to_contain_text(fixture["stranger_address"])
    logged = _entering_logs(run)[logs_before:]
    run.check(
        len(logged) == 1 and fixture["stranger_address"] not in str(logged),
        "the Logi of the click have no address of the stranger: only the view shows it",
    )
    run.capture(page, "281-raporty-dzien-z-problemami", full_page=False)

    run.step(FEATURE, "zostaw-moja")
    register_after_click = read_bytes(register)
    with page.expect_response(lambda response: response.url.endswith("/api/report-entering/keep")) as answered:
        keep.click()
    kept = answered.value.json()
    expect(popover.get_by_role("button", name="Zostaw moją", exact=True)).to_have_count(0)
    expect(popover).to_be_visible()
    _tile_is(page, "wykonawca.b", DAY, "Komplet", 1, 1)
    expect(_row(page, "wykonawca.b")).to_contain_text("Komplet")
    decisions = read_json(run.config / "wpisanie-raportow-decyzje.json")
    run.check(answered.value.status == 200 and _workers(kept)["wykonawca.b"]["problems"] == 0, "the difference is gone at once")
    run.check(
        _orders(kept)["wykonawca.b"] == [("40000103", "tak", "montaż ręcznie", "entered")],
        "after „Zostaw moją” the order with Dad's own value is entered, and its tile turns Komplet without a reload",
    )
    run.check(decisions == {"schema_version": 1, "kept": [KEPT]}, "the decision is in the file of decisions")
    run.check(read_bytes(register) == register_after_click, "„Zostaw moją” leaves INTERMAX byte for byte")
    run.capture(page, "282-raporty-zostaw-moja", full_page=False)
    _close(page, popover)

    _assign_stranger(run, page, fixture["stranger_address"])

    run.step(FEATURE, "dzien-bez-problemow")
    print("  harness: the stranger's mail out of the Skrzynka raportów, as if Maks dealt with it", flush=True)
    aside.parent.mkdir(exist_ok=True)
    move(stranger, aside)
    try:
        notifications = run.api("/api/notifications", "raporty-powiadomienia-przed")
        expect(page.get_by_role("region", name="Spoza listy adresów")).to_be_visible()
        again = result_of_start(run, "raporty-drugie", _button(page).click)
        run.check(figure(again["summary"], "Problemy") == 0, "the next click does not bring the kept difference back")
        after = run.api("/api/notifications", "raporty-powiadomienia-po")
        run.check(
            (after["unread"], after["items"]) == (notifications["unread"], notifications["items"]),
            "a click without problems gives no Powiadomienie",
        )
        last = _entering_logs(run)[-1]
        run.check(
            [(entry["number"], entry["column"], entry["value"]) for entry in last["kept"]]
            == [(40000103, KEPT["column"], KEPT["reported"])],
            "the Logi of the next click have the decision of „Zostaw moją”",
        )
        calm = _view(run, "raporty-bez-problemow")
        run.check(
            all(not day["problems"] for day in _days_of(calm).values()) and calm["unknown_senders"] == [],
            "the day has no problems left",
        )
        # Still no reload since the stranger's region stood above: the view after the click came by itself.
        expect(page.get_by_role("region", name="Spoza listy adresów")).to_have_count(0)
        _tiles_match(page, calm, {"wykonawca.a": "Bez raportu", "wykonawca.b": "Komplet"})
        run.capture(page, "283-raporty-dzien-bez-problemow")

        run.step(FEATURE, "waski-ekran")
        page.set_viewport_size(NARROW)
        try:
            _narrow_layout(run, page, "the Mapa cieplna of the day")
            run.capture(page, "284-raporty-waski-ekran")
        finally:
            page.set_viewport_size(DAD_VIEWPORT)
    finally:
        move(aside, stranger)

    _range_map(run, page)

    run.step(FEATURE, "zatrzymanie")
    broken = run.root / "INTERMAX" / "zepsuty" / register.name
    broken.parent.mkdir(exist_ok=True)
    broken.write_bytes(BROKEN)
    print(f"  harness: INTERMAX is pointed to {broken.parent.name}/{broken.name}, which is no workbook", flush=True)
    _to_reports(page)
    _choose(run, page, str(broken))
    _to_reports(page)
    stopped = result_of_start(run, "raporty-zatrzymanie", _button(page).click)
    run.check(stopped["ending"] != "finished", "the Wpisanie with a broken INTERMAX stops")
    note = page.get_by_role("region", name="Zatrzymanie Wpisania raportów", exact=True)
    expect(note).to_have_text(f"{stopped['headline']}. Komunikat jest w Uruchomieniach.")
    expect(_button(page)).to_be_enabled()
    run.check(True, "Raporty say in one sentence that the Wpisanie stopped and link to Uruchomienia")
    run.capture(page, "286-raporty-zatrzymanie")
    note.get_by_role("link", name="Uruchomieniach", exact=True).click()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    expect(stop_banner(page).first).to_be_visible()
    run.check(True, "the link leads to Uruchomienia, where the stop stands with its Komunikat")

    print("  harness: the Rejestr zleceń from before this feature", flush=True)
    _to_reports(page)
    if before_feature is None:
        Path(run.fixture["settings"]).write_text(saved or "", encoding="utf-8")
    else:
        _choose(run, page, str(before_feature))
    remove_tree(broken.parent)
