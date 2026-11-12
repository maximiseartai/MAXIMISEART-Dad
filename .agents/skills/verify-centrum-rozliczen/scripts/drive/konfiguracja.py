"""Drive features/konfiguracja.md."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import re

from playwright.sync_api import Locator, Page, expect

from drive.common import Run, move, read_bytes, remove, served_version, unreadable, version_line
from drive.teksty import UPDATE_BUTTON, WRITE
from atrapy.workbooks import EXCEL_LOCK_PREFIX, excel_lock

TEMPLATE_LABELS = ("Wzorzec rozliczenia wewnętrznego", "Wzorzec pliku zbiorczego", "Wzorzec rozliczenia pracownika")
REPORT_TO_MAINTAINER = "Przekaż ten komunikat osobie utrzymującej narzędzie."
INACCESSIBLE_TEMPLATE = "Nie można teraz odczytać wzorca. Plik może być zajęty przez inny program."
INACCESSIBLE_WORKER_CONFIG = (
    "Nie można teraz odczytać konfiguracji wykonawców. Plik może być zajęty przez inny program."
)


def _configuration_snapshot(files: dict[str, Path]) -> dict[str, tuple[bytes, int]]:
    """Bytes and modification time of every configuration file of the fixture, plus every lock file."""

    config = next(iter(files.values())).parent
    paths = [*files.values(), *config.glob(f"{EXCEL_LOCK_PREFIX}*")]
    return {path.name: (read_bytes(path), path.stat().st_mtime_ns) for path in sorted(paths)}


@contextmanager
def _changed(path: Path) -> Iterator[None]:
    """Harness: ``path`` gets a newer modification time, as when OneDrive brings it again; the old one comes back after."""

    stat = path.stat()
    print("  harness: the Wzorzec gets a newer modification time, so Centrum checks it again", flush=True)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
    try:
        yield
    finally:
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def _template_group(page: Page, label: str) -> Locator:
    return page.get_by_role("group", name=label, exact=True)


def _shown_as_ready(page: Page, label: str) -> None:
    expect(_template_group(page, label).get_by_role("img", name="Na miejscu i czytelny")).to_be_visible()


def _expect_badge_icon(page: Page, label: str, color: str) -> None:
    """The badge icon of a Wzorzec with a problem: ``text-warning`` for one Dad clears himself (open in Excel),
    ``text-destructive`` for a stop."""

    icon = _template_group(page, label).locator("[data-slot=badge] svg")
    expect(icon).to_have_class(re.compile(rf"(^|\s){color}(\s|$)"))


def _template_answer(run: Run, name: str, label: str) -> dict[str, object]:
    templates = run.api("/api/configuration", name)["templates"]
    assert isinstance(templates, list)
    return next(template for template in templates if template["label"] == label)


def drive(run: Run, page: Page) -> None:
    """Every broken state is made by renaming or adding files and undone by renaming back, so a
    Centrum that wrote nothing leaves bytes and modification times exactly as the fixture made them."""

    feature = "konfiguracja"
    files = {name: Path(path) for name, path in run.fixture["configuration"].items()}
    before = _configuration_snapshot(files)

    run.step(feature, "konfiguracja-gotowa")
    page.goto(run.url)
    page.get_by_role("link", name="Konfiguracja", exact=True).click()
    expect(page.get_by_role("heading", name="Konfiguracja", level=1)).to_be_visible()
    configuration = run.api("/api/configuration", "konfiguracja-gotowa")
    templates = configuration["templates"]
    assert isinstance(templates, list)
    run.check(
        [(template["label"], template["state"]) for template in templates]
        == [(label, "ready") for label in TEMPLATE_LABELS],
        "the server reports all three Wzorce present and readable",
    )
    run.check(
        configuration["workers"] == {"state": "ready", "names": run.fixture["workers"]},
        "the server lists the Wykonawcy in the order of the konfiguracja wykonawców",
    )
    commit, since = served_version(run)
    run.check(
        configuration["version"] == {"commit": commit[:7], "since": since},
        "the server reports the tool's commit and the day the tool moved there",
    )
    for label in TEMPLATE_LABELS:
        _shown_as_ready(page, label)
    expect(page.get_by_text("3 z 3", exact=True)).to_be_visible()
    expect(page.get_by_role("list", name="Wykonawcy").get_by_role("listitem")).to_have_text(run.fixture["workers"])
    expect(page.get_by_role("region", name="Narzędzie").get_by_text(version_line(commit, since), exact=True)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    run.check(True, "the screen shows the same Wzorce, Wykonawcy, and version, with no problem")
    run.capture(page, "10-konfiguracja-gotowa")

    run.step(feature, "konfiguracja-tylko-do-odczytu")
    page.get_by_text("Tylko do odczytu", exact=True).hover()
    expect(page.get_by_text("Zmiany robi osoba utrzymująca narzędzie.", exact=True)).to_be_visible()
    buttons = page.locator("main").get_by_role("button")
    run.check(
        page.url.endswith("#/konfiguracja")
        and buttons.count() == 4
        and buttons.filter(has_text=UPDATE_BUTTON).count() == 0
        and page.locator("main").get_by_role("button", name=WRITE, exact=True).count() == 1
        and page.locator("main").get_by_role("button", name="Powiadomienia", exact=False).count() == 1,
        "the page offers no action besides the header's menu, `Napisz do Maksa`, Powiadomienia and theme buttons; the current tool"
        " has no `Zaktualizuj narzędzie`",
    )
    offer = run.api("/api/configuration", "konfiguracja-tylko-do-odczytu")
    run.check(
        (offer["freshness"], offer["update_offered"]) == ("current", False),
        "the server offers no Aktualizacja narzędzia for the current tool",
    )
    run.capture(page, "11-konfiguracja-tylko-do-odczytu", full_page=False)
    page.mouse.move(0, 0)

    run.step(feature, "konfiguracja-wzorzec-otwarty")
    collective = files["collective_template"]
    lock = excel_lock(collective)
    lock.write_bytes(b"")
    try:
        page.reload()
        expect(_template_group(page, "Wzorzec pliku zbiorczego")).to_contain_text("Otwarty w Excelu")
        _expect_badge_icon(page, "Wzorzec pliku zbiorczego", "text-warning")
        message = page.get_by_role("alert", name="Ostrzeżenie", exact=True).filter(has_text="Wzorzec jest otwarty w Excelu.")
        expect(message).to_contain_text(f"plik {collective.name}, folder config")
        expect(message).to_contain_text(f"usuń z tego samego folderu pozostawiony plik ~${collective.name}")
        expect(page.get_by_text("2 z 3", exact=True)).to_be_visible()
        answer = _template_answer(run, "konfiguracja-wzorzec-otwarty", "Wzorzec pliku zbiorczego")
        run.check(answer["problem"] == "open_in_excel", "the server reports the Wzorzec as open in Excel")
        run.capture(page, "12-konfiguracja-wzorzec-otwarty")
        run.check(lock.exists(), "Centrum leaves Excel's lock file alone")
    finally:
        remove(lock)
    # Headless Chromium keeps every tab visible, so returning to the tab is simulated with `focus`.
    page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
    _shown_as_ready(page, "Wzorzec pliku zbiorczego")
    run.check(True, "a (simulated) return to the tab shows the Wzorzec ready once Excel has closed it")

    run.step(feature, "konfiguracja-wzorzec-niedostepny")
    internal = files["internal_template"]
    with _changed(internal):
        with unreadable(internal):
            page.reload()
            group = _template_group(page, "Wzorzec rozliczenia wewnętrznego")
            expect(group).to_contain_text("Nie przechodzi sprawdzenia")
            message = page.get_by_role("alert").filter(has_text=INACCESSIBLE_TEMPLATE)
            expect(message).to_contain_text(f"plik {internal.name}, folder config")
            run.check("uszkodzon" not in message.inner_text(), "a Wzorzec without access is niedostępny, never uszkodzony")
            answer = _template_answer(run, "konfiguracja-wzorzec-niedostepny", "Wzorzec rozliczenia wewnętrznego")
            run.check(answer["problem"] == "unreadable", "the server reports the Wzorzec as not passing the Sprawdzanie")
            run.capture(page, "12a-konfiguracja-wzorzec-niedostepny")
        print("  harness: access to the Wzorzec is back", flush=True)
        page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
        _shown_as_ready(page, "Wzorzec rozliczenia wewnętrznego")
        expect(page.get_by_role("alert")).to_have_count(0)
        answer = _template_answer(run, "konfiguracja-wzorzec-dostepny", "Wzorzec rozliczenia wewnętrznego")
        run.check(
            answer["state"] == "ready",
            "once access is back, a (simulated) return to the tab shows the Wzorzec ready without restarting Centrum",
        )
        run.capture(page, "12b-konfiguracja-wzorzec-dostepny")

    run.step(feature, "konfiguracja-brak-wzorca")
    worker_template = files["worker_template"]
    moved = worker_template.with_name(worker_template.name + ".przeniesiony")
    move(worker_template, moved)
    try:
        page.reload()
        expect(_template_group(page, "Wzorzec rozliczenia pracownika")).to_contain_text("Brak pliku")
        _expect_badge_icon(page, "Wzorzec rozliczenia pracownika", "text-destructive")
        message = page.get_by_role("alert", name="Zatrzymanie", exact=True).filter(
            has_text=f"Nie znaleziono Wzorca rozliczenia pracownika: {worker_template.name}."
        )
        # The same message as the Przebieg rozliczeń stop for this Wzorzec.
        expect(message).to_contain_text("Nie można użyć Wzorca rozliczenia pracownika.")
        expect(message).to_contain_text("W innym wypadku przekaż ten komunikat osobie utrzymującej narzędzie.")
        answer = _template_answer(run, "konfiguracja-brak-wzorca", "Wzorzec rozliczenia pracownika")
        run.check(answer["problem"] == "missing", "the server reports the Wzorzec rozliczenia pracownika as missing")
        run.capture(page, "13-konfiguracja-brak-wzorca")
    finally:
        move(moved, worker_template)

    run.step(feature, "konfiguracja-nieczytelna-konfiguracja-wykonawcow")
    worker_config = files["worker_config"]
    moved = worker_config.with_name(worker_config.name + ".przeniesiony")
    move(worker_config, moved)
    try:
        worker_config.write_text("workers: [niedomknięta lista\n", encoding="utf-8")
        page.reload()
        # The same message as the stop of each process on this konfiguracja wykonawców.
        message = page.get_by_role("alert").filter(has_text="Nie można odczytać konfiguracji wykonawców.")
        expect(message).to_contain_text("Plik nie jest poprawnym YAML.")
        expect(message).to_contain_text(f"plik {worker_config.name}")
        expect(message).to_contain_text(REPORT_TO_MAINTAINER)
        expect(page.get_by_role("list", name="Wykonawcy")).to_have_count(0)
        workers = run.api("/api/configuration", "konfiguracja-nieczytelna-konfiguracja-wykonawcow")["workers"]
        assert isinstance(workers, dict)
        run.check(workers["state"] == "unreadable", "the server reports the konfiguracja wykonawców as unreadable")
        run.capture(page, "14-konfiguracja-nieczytelna-konfiguracja-wykonawcow")
    finally:
        remove(worker_config, missing_ok=True)
        move(moved, worker_config)

    run.step(feature, "konfiguracja-niedostepna-konfiguracja-wykonawcow")
    with unreadable(worker_config):
        page.reload()
        # The same message as Przebieg rozliczeń's stop on this konfiguracja wykonawców.
        message = page.get_by_role("alert").filter(has_text=INACCESSIBLE_WORKER_CONFIG)
        expect(message).to_contain_text(f"plik {worker_config.name}, folder config")
        expect(message).to_contain_text(REPORT_TO_MAINTAINER)
        run.check(
            all(word not in message.inner_text() for word in ("uszkodzon", "niepoprawn")),
            "a konfiguracja wykonawców without access is niedostępna, never uszkodzona or niepoprawna",
        )
        expect(page.get_by_role("list", name="Wykonawcy")).to_have_count(0)
        workers = run.api("/api/configuration", "konfiguracja-niedostepna-konfiguracja-wykonawcow")["workers"]
        assert isinstance(workers, dict)
        run.check(workers["state"] == "unreadable", "the server reports the konfiguracja wykonawców as unreadable")
        run.capture(page, "14a-konfiguracja-niedostepna-konfiguracja-wykonawcow")

    run.step(feature, "konfiguracja-bez-zmian")
    page.reload()
    for label in TEMPLATE_LABELS:
        _shown_as_ready(page, label)
    run.check(
        _configuration_snapshot(files) == before,
        "the konfiguracja wykonawców and every Wzorzec keep their bytes and modification times; no lock file is left",
    )
