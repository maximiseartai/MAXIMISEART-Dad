"""Drive features/uporzadkowanie-intermax.md."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from playwright.sync_api import Locator, Page, expect
import yaml

from drive.common import (
    Run,
    current_run,
    dad_tab,
    ended_run_shown,
    point_in_settings,
    read_bytes,
    remove,
    result_of_start,
    run_again,
    run_logs,
    stop_banner,
)
from drive.waiting import Budget, until
from atrapy.workbooks import excel_lock
from harness import Log

FEATURE = "uporzadkowanie-intermax"
CARD = "Uporządkuj INTERMAX"
NOT_SET = "Najpierw wskaż INTERMAX."
OPEN = "INTERMAX jest otwarty w Excelu. Zapisz go i zamknij. Jeśli Excel jest zamknięty, usuń z tego samego folderu pozostawiony plik {lock}."
DONE = "INTERMAX uporządkowany"
NOTHING_TO_ORDER = "Na dole arkusza zleceń nie ma wklejonych zleceń do uporządkowania. INTERMAX nie został zmieniony."
# The fixture's "today" is Monday 19.10.2026, so every Uruchomienie of Uporządkowanie INTERMAX has this period.
PERIOD = "13_19_10_2026"
COPY = re.compile(r"INTERMAX przed uporządkowaniem 2026-10-19 \d{2}-\d{2}-\d{2}\.xlsx")
# Days of the fixture's INTERMAX on the card: today and the 6 days before it (13–19.10) and the later Dzień uporządkowany
# 20.10; 19.10 (two ordered rows) and 20.10 (no earlier day under it) are ordered. The day of the Surowe zlecenia 26.10
# is later than today and not ordered, so the card leaves it out until the Uporządkowanie.
DAYS = (
    ("wt 13.10", False),
    ("śr 14.10", False),
    ("czw 15.10", False),
    ("pt 16.10", False),
    ("sob 17.10", False),
    ("niedz 18.10", False),
    ("pon 19.10", True),
    ("wt 20.10", True),
)
# Dad's laptop runs JavaScript about 4× slower than the Mac this runs on (docs/agents/komputer-taty.md).
DAD_CPU = 4

Json = dict[str, Any]


def _card(page: Page) -> Locator:
    return page.get_by_role("region", name=CARD, exact=True)


def _button(page: Page) -> Locator:
    return _card(page).get_by_role("button", name=CARD, exact=True)


def _to_card(run: Run, page: Page) -> None:
    """Uruchomienia with the setup cards, the ended Uruchomienie set aside like Dad does with `+`."""

    page.goto(run.url + "#/uruchomienia")
    page.reload()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    if ended_run_shown(current_run(run, "intermax-przed-karta")):
        page.get_by_role("button", name="Nowe Uruchomienie procesu", exact=True).click()
    expect(_card(page)).to_be_visible()


def _choose(run: Run, page: Page, path: str) -> None:
    """Dad points INTERMAX (the Rejestr zleceń) to ``path`` in Ustawienia over the card (harness answers the picker)."""

    point_in_settings(run, page, "Rejestr zleceń", path)
    expect(_card(page).get_by_role("group", name="INTERMAX")).to_contain_text(Path(path).name)


def _day_name(label: str, ordered: bool) -> str:
    return f"{label}: {'uporządkowany' if ordered else 'nieuporządkowany'}"


def _days_shown(page: Page) -> Locator:
    return _card(page).get_by_role("list", name="Dni INTERMAX").get_by_role("listitem")


def _logs(run: Run) -> list[Json]:
    return list(run_logs(run, "intermax").values())


def drive(run: Run, page: Page) -> None:
    fixture = run.fixture["intermax"]
    register = Path(fixture["register"])
    before_feature = run.remembered("rejestr_zlecen")
    logs_before = len(_logs(run))

    run.step(FEATURE, "bez-intermax")
    settings = Path(run.fixture["settings"])
    saved = run.settings_text()
    without = {key: value for key, value in (yaml.safe_load(saved or "") or {}).items() if key != "rejestr_zlecen"}
    print("  harness: the settings file without the Rejestr zleceń, as before Dad points to it", flush=True)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(yaml.safe_dump(without, allow_unicode=True), encoding="utf-8")
    _to_card(run, page)
    setup = run.api("/api/intermax", "intermax-bez-intermax")
    expect(_card(page).get_by_text(NOT_SET, exact=True)).to_be_visible()
    expect(_card(page).get_by_text("INTERMAX: nie wskazano", exact=True)).to_be_visible()
    expect(_button(page)).to_be_disabled()
    run.check(setup["blocker"] == NOT_SET, "without INTERMAX the card says what to set and its button is disabled")
    run.capture(page, "230-intermax-bez-intermax")
    if saved is not None:
        settings.write_text(saved, encoding="utf-8")

    run.step(FEATURE, "wskazanie")
    page.reload()
    _to_card(run, page)
    _choose(run, page, str(register))
    page.reload()
    _to_card(run, page)
    expect(_card(page).get_by_text(NOT_SET, exact=True)).to_have_count(0)
    expect(_button(page)).to_be_enabled()
    expect(_card(page).get_by_text("Zapisz i zamknij INTERMAX w Excelu", exact=True)).to_be_visible()
    run.check(run.api("/api/intermax", "intermax-gotowa")["blocker"] is None, "the card is ready with Dad's INTERMAX")
    run.capture(page, "231-intermax-karta")

    run.step(FEATURE, "dni")
    days = run.api("/api/intermax/days", "intermax-dni")["days"]
    assert isinstance(days, list)
    expect(_days_shown(page)).to_have_count(len(DAYS))
    for label, ordered in DAYS:
        expect(_card(page).get_by_role("listitem", name=_day_name(label, ordered), exact=True)).to_be_visible()
    expect(_card(page).get_by_role("listitem", name=_day_name("pon 19.10", True), exact=True)).to_have_attribute(
        "aria-current", "date"
    )
    run.check(
        [(day["label"], day["ordered"]) for day in days] == list(DAYS),
        "the card lists today, the 6 days before it and the later Dzień uporządkowany, each with its state, without the pasted day",
    )

    run.step(FEATURE, "otwarty")
    lock = excel_lock(register)
    lock.write_bytes(b"\x00" * 165)
    try:
        page.reload()
        _to_card(run, page)
        expect(_card(page).get_by_text(OPEN.format(lock=lock.name), exact=True)).to_be_visible()
        expect(_button(page)).to_be_disabled()
        expect(_days_shown(page)).to_have_count(len(DAYS))
        run.check(True, "INTERMAX open in Excel disables the button with the sentence what to do")
        run.check(True, "the days of INTERMAX open in Excel come from its last saved version")
        run.capture(page, "232-intermax-otwarty")
    finally:
        remove(lock)
    page.reload()
    _to_card(run, page)
    expect(_button(page)).to_be_enabled()
    run.check(True, "once Excel closes INTERMAX the button is enabled again")

    run.step(FEATURE, "uporzadkowanie-dotykiem")
    original = read_bytes(register)
    _order_by_touch(run, page, register, original, fixture)

    run.step(FEATURE, "zatrzymanie-dla-taty")
    _to_card(run, page)
    last = _card(page).get_by_text(re.compile(r"^Ostatnio .* · INTERMAX uporządkowany · " + fixture["day"] + "$"))
    expect(last).to_be_visible()
    run.check(True, "the card shows the last Uporządkowanie from its Logi with its day")
    expect(_card(page).get_by_role("listitem", name=_day_name("pon 26.10", True), exact=True)).to_be_visible()
    run.check(True, "after the Uporządkowanie the card shows the pasted day as ordered")
    run.capture(page, "238-intermax-dni-po-uporzadkowaniu")
    result = result_of_start(run, "intermax-nic-do-uporzadkowania", _button(page).click)
    banner = stop_banner(page)
    expect(banner).to_contain_text(NOTHING_TO_ORDER)
    expect(banner).to_contain_text("Do poprawy")
    expect(banner.get_by_role("button", name="Otwórz INTERMAX", exact=True)).to_be_visible()
    expect(banner.get_by_role("button", name="Otwórz Rejestr zleceń", exact=True)).to_have_count(0)
    run.check(result["stop_kind"] == "for_tata", "the INTERMAX ordered before stops „dla taty”: nothing left to order")
    run.check(True, "the stop offers „Otwórz INTERMAX”, the card's one name of the file")
    repeated = run_again(run, banner, "intermax-powtorka")
    expect(stop_banner(page).get_by_role("button", name="Diagnoza", exact=True)).to_be_visible()
    run.check(repeated["stop_kind"] == "repeated", "the same stop again offers Diagnoza")
    run.capture(page, "234-intermax-zatrzymanie-dla-taty")

    run.step(FEATURE, "zatrzymanie-do-maksa")
    _to_card(run, page)
    _choose(run, page, fixture["with_formula"])
    page.reload()
    _to_card(run, page)
    stopped = result_of_start(run, "intermax-do-maksa", _button(page).click)
    expect(stop_banner(page)).to_contain_text("Błąd")
    run.check(stopped["stop_kind"] == "for_maks", "pasted rows with a formula stop „do Maksa”")
    with page.expect_response(lambda response: response.url.endswith("/diagnosis")) as answered:
        stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    diagnosis = answered.value.json()
    (run.evidence / "api" / "intermax-diagnoza.json").write_text(
        json.dumps(diagnosis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    region = page.get_by_role("region", name="Diagnoza")
    labels = [check["label"] for check in diagnosis["checks"]]
    region.get_by_role("button", name=f"Sprawdzono ({len(labels)})", exact=True).click()
    shown = region.get_by_role("list", name="Sprawdzono").get_by_role("listitem")
    expect(shown.filter(has_text=re.compile(r"^INTERMAX · "))).to_have_count(1)
    # Ustawienia Centrum name the file as the card does.
    expect(shown.filter(has_text="Ustawienia Centrum · INTERMAX jest na miejscu.")).to_have_count(1)
    expect(region.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_be_visible()
    run.check(
        labels[:3] == ["Ustawienia Centrum", "Pliki w OneDrive", "INTERMAX"]
        and "- Proces: Uporządkowanie INTERMAX" in diagnosis["report"]["body"],
        "the Diagnoza checks Dad's INTERMAX and offers the Zgłoszenie of Uporządkowanie INTERMAX",
    )
    run.capture(page, "235-intermax-do-maksa")

    run.step(FEATURE, "historia")
    logs = _logs(run)[logs_before:]
    run.check(
        [(log["mode"], log["period"]) for log in logs] == [("RUN", PERIOD)] * 4,
        "four new files of Logi of Uporządkowanie INTERMAX, each with the period of the fixture's today",
    )
    page.get_by_role("tab", name="Historia", exact=True).click()
    page.get_by_role("group", name="Proces w historii").get_by_role("button", name="INTERMAX", exact=True).click()
    rows = page.get_by_role("table", name="Historia Uruchomień procesu").get_by_role("row")
    expect(rows.filter(has_text="Uporządkowanie INTERMAX")).to_have_count(len(logs))
    metrics = run.api("/api/metrics", "intermax-metryki")["runs"]
    assert isinstance(metrics, list)
    ordering = [entry for entry in metrics if entry["process"] == "intermax"]
    run.check(
        len(ordering) == len(logs) and all(entry["origin"] == "centrum" for entry in ordering),
        "Historia lists every Uporządkowanie INTERMAX from Centrum",
    )
    run.capture(page, "236-intermax-historia")
    page.get_by_role("link", name="Metryki", exact=True).click()
    processes = page.get_by_role("group", name="Proces", exact=True)
    modes = page.get_by_role("group", name="Tryb", exact=True)
    # Dad looks at Przygotowanie DRY-RUN first: INTERMAX has no DRY-RUN, so its RUN has to be the mode shown.
    processes.get_by_role("button", name="Przygotowanie", exact=True).click()
    modes.get_by_role("button", name="DRY-RUN", exact=True).click()
    expect(modes.get_by_role("button", name="DRY-RUN", exact=True)).to_have_attribute("aria-pressed", "true")
    processes.get_by_role("button", name="INTERMAX", exact=True).click()
    expect(modes.get_by_role("button")).to_have_text(["RUN"])
    expect(modes.get_by_role("button", name="RUN", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_text("Ten proces nie był jeszcze uruchomiony w tym trybie", exact=True)).to_have_count(0)
    run.check(True, "Metryki of INTERMAX offer only the mode RUN: Uporządkowanie INTERMAX has no Podgląd bez zapisu")
    run.check(True, "from Przygotowanie DRY-RUN, INTERMAX shows its RUN pressed with the chart of its runs")
    run.capture(page, "237-intermax-metryki")

    print("  harness: the Rejestr zleceń from before this feature", flush=True)
    _to_card(run, page)
    if before_feature is None:
        settings.write_text(saved or "", encoding="utf-8")
    else:
        _choose(run, page, str(before_feature))


def _order_by_touch(run: Run, page: Page, register: Path, original: bytes, fixture: Json) -> None:
    """Dad taps the button with his finger on a laptop as slow as his (CPU 4×) and reads the result card."""

    with dad_tab(page, touch=True, cpu=DAD_CPU, timeout_ms=Budget.SLOWED.ms) as touch:
        _to_card(run, touch)
        result: Json = result_of_start(run, "intermax-wynik", _button(touch).tap)
        live = touch.get_by_role("region", name="Podgląd na żywo")
        expect(live.get_by_label("Wynik")).to_contain_text(DONE)
        copy = result["summary"]["intermax_copy"]
        expect(live.get_by_text(f"Kopia sprzed zapisu: {copy}", exact=True)).to_be_visible()
        expect(live.get_by_label(f"{fixture['day']}: {fixture['orders']}", exact=True)).to_be_visible()
        figures = {figure["label"]: figure["value"] for figure in result["summary"]["figures"]}
        run.check(
            figures == {"Zlecenia": fixture["orders"], "Wykonawcy": fixture["workers"]},
            "the result card counts the orders and the Wykonawcy of the pasted day in the period of today",
        )
        expect(live.get_by_text(f"Okres {PERIOD}", exact=True)).to_be_visible()
        copies = sorted(path.name for path in Path(fixture["copies"]).iterdir())
        run.check(
            bool(COPY.fullmatch(copy)) and copies == [copy] and read_bytes(Path(fixture["copies"]) / copy) == original,
            "the Kopia INTERMAX holds the bytes from before the write and is named after the clock",
        )
        run.check(read_bytes(register) != original, "Dad's INTERMAX is ordered on disk")
        run.capture(touch, "233-intermax-wynik")
        opened = len(run.lines(Log.OPENED))
        live.get_by_role("button", name="Otwórz INTERMAX", exact=True).tap()
        until(lambda: len(run.lines(Log.OPENED)) > opened, "INTERMAX opens in Excel")
        run.check(run.lines(Log.OPENED)[-1]["path"] == str(register), "the result opens Dad's INTERMAX")
