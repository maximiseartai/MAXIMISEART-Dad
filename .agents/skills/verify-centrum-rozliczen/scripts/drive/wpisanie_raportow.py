"""Drive features/wpisanie-raportow.md."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, ViewportSize, expect

from atrapy.workbooks import excel_lock
from drive.common import (
    DAD_VIEWPORT,
    FOCUS,
    Run,
    current_run,
    ended_run_shown,
    figure,
    move,
    read_bytes,
    read_json,
    remove,
    remove_tree,
    result_of_start,
    run_logs,
    stop_banner,
)

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
KEPT = {
    "number": "40000103",
    "day": DAY,
    "worker": "wykonawca.b",
    "column": "CZYNNOŚCI ZREALIZOWANE",
    "reported": "montaż anteny",
}
NARROW: ViewportSize = {"width": 390, "height": 844}

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
    """Dad points INTERMAX on Raporty to ``path`` through the native picker (harness answers it)."""

    run.answer_picker(path)
    verb = "Wskaż" if run.remembered("rejestr_zlecen") is None else "Zmień"
    page.get_by_role("group", name="INTERMAX", exact=True).get_by_role("button", name=f"{verb} INTERMAX", exact=True).click()
    run.wait_for(lambda: run.remembered("rejestr_zlecen") == path, f"INTERMAX set to {Path(path).name}")


def _row(page: Page, worker: str) -> Locator:
    return page.get_by_role("list", name="Wykonawcy").get_by_role("listitem", name=worker, exact=True)


def _figures(row: Locator, shown: Json) -> None:
    for label, key in (("Zlecenia", "orders"), ("Wpisane", "entered"), ("Maile", "mails"), ("Problemy", "problems")):
        expect(row.get_by_label(f"{label} {shown[key]}", exact=True)).to_be_visible()


def _view(run: Run, name: str) -> Json:
    view = run.api("/api/report-entering/view", name)
    assert isinstance(view, dict)
    return view


def _workers(view: Json) -> dict[str, Json]:
    return {
        worker["worker"]: {
            "orders": worker["orders"],
            "entered": worker["entered"],
            "mails": worker["mails"],
            "problems": len(worker["problems"]),
            "without_report": worker["without_report"],
        }
        for worker in view["workers"]
    }


def _entering_logs(run: Run) -> list[Json]:
    return [log["report_entering"] for log in run_logs(run, "report_entering").values()]


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
        run.answer_picker(run.fixture["periods_directory"])
        page.get_by_role("button", name="Wskaż folder okresów", exact=True).click()
        expect(page.get_by_role("table", name="Tablica okresów")).to_be_visible()
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

    run.step(FEATURE, "widok-przed-kliknieciem")
    first_view = _view(run, "raporty-widok-przed")
    if first_view["clicked_at"] is None:
        expect(page.get_by_text("Jeszcze nie ma Raportów", exact=True)).to_be_visible()
        expect(page.get_by_text("Kliknij „Wpisz raporty z maili” powyżej.", exact=True)).to_be_visible()
    run.check(first_view["today"] == DAY and first_view["day"] == DAY, "the view opens on today, 19.10.2026")

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
    for worker, shown in SHOWN.items():
        _figures(_row(page, worker), shown)
    expect(_button(page)).to_be_enabled()
    run.check(True, "Raporty show the result of the click without a reload, and the button is on again")
    page.get_by_role("list", name="Sekcje Centrum rozliczeń").get_by_role("link", name="Uruchomienia", exact=True).click()
    live = page.get_by_role("region", name="Podgląd na żywo")
    live.get_by_role("button", name="Otwórz Raporty", exact=True).click()

    run.step(FEATURE, "widok")
    expect(page.get_by_role("heading", name="Raporty", exact=True)).to_be_visible()
    expect(page.get_by_role("group", name="Dzień")).to_contain_text("poniedziałek 19.10 · dziś")
    view = _view(run, "raporty-widok")
    run.check(_workers(view) == SHOWN, "the view has each Wykonawca of the day with the figures of the click")
    [unknown] = view["unknown_senders"]
    run.check(unknown["sender"] == fixture["stranger_address"], "the Raport from outside the list shows its address")
    for worker, shown in SHOWN.items():
        _figures(_row(page, worker), shown)
    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    run.check(
        menu.get_by_role("link").all_inner_texts()[:3] == ["Okresy", "Uruchomienia", "Raporty"],
        "Raporty is a menu section right after Uruchomienia",
    )
    expect(menu.get_by_role("link", name="Raporty", exact=True)).to_have_attribute("aria-current", "page")
    expect(page.get_by_role("link", name="Uruchomienia", exact=True)).to_have_count(1)
    _row(page, "wykonawca.a").get_by_role("button").first.click()
    expect(_row(page, "wykonawca.a").get_by_role("group", name="Bez raportu")).to_contain_text("40000102")
    _row(page, "wykonawca.b").get_by_role("button").first.click()
    keep = _row(page, "wykonawca.b").get_by_role("button", name="Zostaw moją", exact=True)
    expect(keep).to_be_visible()
    expect(_row(page, "wykonawca.b").get_by_role("list", name="Problemy")).to_contain_text("montaż ręcznie")
    expect(page.get_by_role("region", name="Spoza listy adresów")).to_contain_text(fixture["stranger_address"])
    logged = _entering_logs(run)[logs_before:]
    run.check(
        len(logged) == 1 and fixture["stranger_address"] not in str(logged),
        "the Logi of the click have no address of the stranger: only the view shows it",
    )
    run.capture(page, "281-raporty-dzien-z-problemami")

    run.step(FEATURE, "zostaw-moja")
    register_after_click = read_bytes(register)
    with page.expect_response(lambda response: response.url.endswith("/api/report-entering/keep")) as answered:
        keep.click()
    kept = answered.value.json()
    expect(_row(page, "wykonawca.b").get_by_role("button", name="Zostaw moją", exact=True)).to_have_count(0)
    _figures(_row(page, "wykonawca.b"), {**SHOWN["wykonawca.b"], "problems": 0})
    decisions = read_json(run.config / "wpisanie-raportow-decyzje.json")
    run.check(answered.value.status == 200 and _workers(kept)["wykonawca.b"]["problems"] == 0, "the difference is gone at once")
    run.check(decisions == {"schema_version": 1, "kept": [KEPT]}, "the decision is in the file of decisions")
    run.check(read_bytes(register) == register_after_click, "„Zostaw moją” leaves INTERMAX byte for byte")
    run.capture(page, "282-raporty-zostaw-moja")

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
            all(not worker["problems"] for worker in calm["workers"]) and calm["unknown_senders"] == [],
            "the day has no problems left",
        )
        # Still no reload since the stranger's region stood above: the view after the click came by itself.
        expect(page.get_by_role("region", name="Spoza listy adresów")).to_have_count(0)
        expect(page.get_by_role("button", name="Zostaw moją", exact=True)).to_have_count(0)
        run.capture(page, "283-raporty-dzien-bez-problemow")

        run.step(FEATURE, "waski-ekran")
        page.set_viewport_size(NARROW)
        try:
            _row(page, "wykonawca.a").get_by_role("button").first.click()
            expect(_row(page, "wykonawca.a").get_by_role("group", name="Bez raportu")).to_be_visible()
            width = page.evaluate("document.documentElement.scrollWidth")
            boxes = [
                box
                for worker in SHOWN
                for shown_part in (
                    _row(page, worker).get_by_text(worker, exact=True),
                    _row(page, worker).get_by_label("Problemy 0", exact=True),
                )
                if (box := shown_part.bounding_box()) is not None
            ]
            button = _button(page).bounding_box()
            run.check(
                width <= NARROW["width"]
                and len(boxes) == 2 * len(SHOWN)
                and button is not None
                and all(box["width"] > 0 and box["x"] + box["width"] <= NARROW["width"] for box in [*boxes, button]),
                "on a narrow screen each Wykonawca keeps his name and all four figures, and the header its button, "
                "without scrolling sideways",
            )
            run.capture(page, "284-raporty-waski-ekran")
        finally:
            page.set_viewport_size(DAD_VIEWPORT)
    finally:
        move(aside, stranger)

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
