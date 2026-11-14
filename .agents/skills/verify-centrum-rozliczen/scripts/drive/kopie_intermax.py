"""Drive features/kopie-intermax.md."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
import shutil
from typing import Any

from playwright.sync_api import Locator, Page, expect
from drive.common import DAD_TIME_ZONE, Run, dad_tab, read_bytes, remove, settings_title, settings_window
from drive.waiting import Budget
from atrapy.workbooks import excel_lock

FEATURE = "kopie-intermax"
CARD = "Kopie INTERMAX"
OPEN = "INTERMAX jest otwarty w Excelu. INTERMAX nie został zmieniony."
NAME = re.compile(r"INTERMAX przed (uporządkowaniem|przywróceniem) (\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2})\.xlsx")
NEW_COPY = re.compile(r"INTERMAX przed przywróceniem 2026-10-19 \d{2}-\d{2}-\d{2}\.xlsx")
# Dad's laptop runs JavaScript about 4× slower than the Mac this runs on (docs/agents/komputer-taty.md).
DAD_CPU = 4

Json = dict[str, Any]


def _moment(name: str) -> datetime:
    """The moment in a Kopia's name: the computer's local time, as Centrum's clock names it."""

    found = NAME.fullmatch(name)
    assert found is not None, name
    return datetime.strptime(found[2], "%Y-%m-%d %H-%M-%S").astimezone()


def _label(name: str) -> str:
    """How the card shows the Kopia's moment: Dad's date and time, as `dateTime` in the browser."""

    return f"{_moment(name).astimezone(DAD_TIME_ZONE):%d.%m.%Y, %H:%M}"


def _card(page: Page) -> Locator:
    return settings_window(page).get_by_role("region", name=CARD, exact=True)


def _row(page: Page, name: str) -> Locator:
    return _card(page).get_by_role("group", name=f"Kopia z {_label(name)}", exact=True)


def _to_card(run: Run, page: Page) -> None:
    page.goto(run.url + "#/ustawienia/kopie-intermax")
    page.reload()
    expect(settings_title(page)).to_have_text(f"Ustawienia/{CARD}")
    expect(_card(page)).to_be_visible()


def _kopie(folder: Path) -> dict[str, bytes]:
    return {path.name: read_bytes(path) for path in sorted(folder.iterdir())} if folder.is_dir() else {}


def _point_register(run: Run, page: Page, register: Path) -> None:
    """Harness: the native picker answers ``register`` to „Zmień Rejestr zleceń” in Ustawienia, as when Dad points to it."""

    run.answer_picker(str(register))
    answer = page.request.post(run.url.rstrip("/") + "/api/settings/register/choose", headers={"Origin": run.url.rstrip("/")})
    run.check(answer.ok and run.remembered("rejestr_zlecen") == str(register), "INTERMAX of this feature is in the settings")


def drive(run: Run, page: Page) -> None:
    fixture = run.fixture["intermax"]["restore"]
    register = Path(fixture["register"])
    folder = Path(run.fixture["intermax"]["copies"])
    sources = [Path(source) for source in fixture["copies"]]
    oldest, middle, newest = (source.name for source in sources)
    settings = Path(run.fixture["settings"])
    saved = run.settings_text()
    kopie_before = _kopie(folder)
    original = read_bytes(register)
    print("  harness: INTERMAX of this feature in the settings and three Kopie of both names in the folder", flush=True)
    _point_register(run, page, register)
    folder.mkdir(exist_ok=True)
    for source in sources:
        shutil.copyfile(source, folder / source.name)
    try:
        _drive(run, page, register, folder, original, oldest, middle, newest)
    finally:
        print("  harness: the Kopie and the settings from before this feature", flush=True)
        for name in set(_kopie(folder)) - set(kopie_before):
            remove(folder / name)
        register.write_bytes(original)
        lock = excel_lock(register)
        remove(lock, missing_ok=True)
        if saved is None:
            remove(settings, missing_ok=True)
        else:
            settings.write_text(saved, encoding="utf-8")


def _drive(
    run: Run, page: Page, register: Path, folder: Path, original: bytes, oldest: str, middle: str, newest: str
) -> None:
    run.step(FEATURE, "lista")
    _to_card(run, page)
    listed = run.api("/api/intermax/copies", "kopie-lista")
    copies = listed["copies"]
    assert isinstance(copies, list)
    names = [copy["name"] for copy in copies]
    run.check(listed["problem"] is None, "the folder of Kopie reads without a Komunikat")
    run.check(
        {oldest, middle, newest} <= set(names) and names == sorted(names, key=_moment, reverse=True),
        "the list has the Kopie of both names, the newest first, by the moment in their name",
    )
    run.check(
        [copy["before"] for copy in copies if copy["name"] in (oldest, middle, newest)]
        == ["ordering", "restore", "ordering"],
        "each Kopia says before what it was made",
    )
    rows = _card(page).get_by_role("group")
    expect(rows).to_have_count(len(names))
    titles = [rows.nth(index).get_attribute("aria-label") for index in range(len(names))]
    run.check(
        titles == [f"Kopia z {_label(name)}" for name in names],
        "the card lists the Kopie in the same order with Dad's date and time from the name",
    )
    expect(_row(page, middle)).to_contain_text("przed przywróceniem")
    expect(_row(page, oldest)).to_contain_text("przed uporządkowaniem")
    run.capture(page, "240-kopie-intermax-lista")

    run.step(FEATURE, "ostrzezenie")
    _row(page, oldest).get_by_role("button", name="Przywróć", exact=True).click()
    dialog = page.get_by_role("alertdialog")
    expect(dialog.get_by_role("heading", name=f"Przywrócić kopię z {_label(oldest)}?", exact=True)).to_be_visible()
    warning = f"Zmiany w INTERMAX wprowadzone po {_label(oldest)[-5:]} znikną."
    expect(dialog.get_by_text(warning, exact=True)).to_be_visible()
    run.check(True, "one sentence warns that the changes after the Kopia's time disappear")
    run.capture(page, "241-kopie-intermax-ostrzezenie")
    dialog.get_by_role("button", name="Anuluj", exact=True).click()
    expect(dialog).to_have_count(0)
    run.check(
        read_bytes(register) == original and set(_kopie(folder)) == set(names),
        "„Anuluj” leaves INTERMAX and the Kopie as they were",
    )

    run.step(FEATURE, "otwarty")
    lock = excel_lock(register)
    lock.write_bytes(b"\x00" * 165)
    try:
        kopie = _kopie(folder)
        _row(page, oldest).get_by_role("button", name="Przywróć", exact=True).click()
        page.get_by_role("alertdialog").get_by_role("button", name="Przywróć tę kopię", exact=True).click()
        expect(_card(page).get_by_text(OPEN, exact=True)).to_be_visible()
        expect(_card(page)).to_contain_text("Zapisz i zamknij INTERMAX w Excelu, potem przywróć kopię jeszcze raz.")
        run.check(
            read_bytes(register) == original and _kopie(folder) == kopie,
            "with INTERMAX open in Excel the restore refuses and changes neither INTERMAX nor the Kopie",
        )
        run.capture(page, "242-kopie-intermax-otwarty")
    finally:
        remove(lock)

    run.step(FEATURE, "przywrocenie-dotykiem")
    _restore_by_touch(run, page, register, folder, original, oldest)


def _restore_by_touch(run: Run, page: Page, register: Path, folder: Path, original: bytes, oldest: str) -> None:
    """Dad taps „Przywróć” and „Przywróć tę kopię” with his finger on a laptop as slow as his (CPU 4×)."""

    with dad_tab(page, touch=True, cpu=DAD_CPU, timeout_ms=Budget.SLOWED.ms) as touch:
        _to_card(run, touch)
        chosen = read_bytes(folder / oldest)
        before = set(_kopie(folder))
        _row(touch, oldest).get_by_role("button", name="Przywróć", exact=True).tap()
        touch.get_by_role("alertdialog").get_by_role("button", name="Przywróć tę kopię", exact=True).tap()
        expect(_card(touch).get_by_text(f"Przywrócono kopię z {_label(oldest)}", exact=True)).to_be_visible()
        run.check(read_bytes(register) == chosen, "INTERMAX is the chosen Kopia byte for byte")
        made = sorted(set(_kopie(folder)) - before)
        run.check(
            len(made) == 1 and bool(NEW_COPY.fullmatch(made[0])) and read_bytes(folder / made[0]) == original,
            "the state before the restore lies as a new Kopia „przed przywróceniem” named after Centrum's clock",
        )
        listed = run.api("/api/intermax/copies", "kopie-po-przywroceniu")["copies"]
        assert isinstance(listed, list)
        run.check(listed[0]["name"] == made[0], "the new Kopia is the newest on the list")
        first = _card(touch).get_by_role("group").first
        expect(first).to_have_attribute("aria-label", f"Kopia z {_label(made[0])}")
        expect(first).to_contain_text("przed przywróceniem")
        run.check(True, "the card reads the list again and shows the new Kopia first")
        run.capture(touch, "243-kopie-intermax-przywrocona")
