"""Drive features/konfiguracja.md."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import re

from playwright.sync_api import Locator, Page, expect

from playwright.sync_api import ViewportSize

from drive.common import (
    Run,
    dad_tab,
    move,
    open_settings,
    read_bytes,
    remove,
    served_version,
    settings_window,
    unreadable,
    version_line,
)
from drive.teksty import UPDATE_BUTTON
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from atrapy.workbooks import EXCEL_LOCK_PREFIX, excel_lock

TEMPLATE_LABELS = ("Wzorzec rozliczenia wewnętrznego", "Wzorzec pliku zbiorczego", "Wzorzec rozliczenia pracownika")
INACCESSIBLE_TEMPLATE = "Nie można teraz odczytać wzorca. Plik może być zajęty przez inny program."
# The sentences Dad reads in the section Wykonawcy, copied on purpose (docs/agents/skille.md, „Co wyrocznia bierze z src”).
BROKEN_WORKER_LIST = f"Plik {WORKERS_FILE} w folderze config ma uszkodzoną treść. Poprawia go Maks."
LAST_GOOD_CAPTION = "Ostatnia dobra lista, której używają procesy"
INACCESSIBLE_WORKER_LIST = (
    "Nie można teraz odczytać Listy Wykonawców. Plik może być zajęty przez inny program. Spróbuj za chwilę."
)
NARROW_VIEWPORT: ViewportSize = {"width": 390, "height": 844}
# Synthetic matters left by moving the old Wykonawcy files, as the migration writes them (ADR 0032, DESIGN §4.2).
UNRESOLVED_LOGIN, UNRESOLVED_ADDRESS = "obcy.login", "obcy.login@przyklad.invalid"
UNRESOLVED_SENTENCE = "Adresów Wykonawców nie przeniesiono ze starego pliku adresy-wykonawcow.yaml w folderze config."


def _configuration_snapshot(files: dict[str, Path]) -> dict[str, tuple[bytes, int]]:
    """Bytes and modification time of every configuration file of the fixture and the Lista Wykonawców, plus every lock
    file."""

    config = next(iter(files.values())).parent
    paths = [*files.values(), config / WORKERS_FILE, *config.glob(f"{EXCEL_LOCK_PREFIX}*")]
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
    """The row of the Wzorzec ``label`` in the section Wzorce of Ustawienia."""

    return settings_window(page).get_by_role("listitem", name=label, exact=True)


def _shown_as_ready(page: Page, label: str) -> None:
    expect(_template_group(page, label).get_by_role("img", name="Na miejscu i czytelny")).to_be_visible()


def _expect_badge_icon(page: Page, label: str, color: str) -> None:
    """The badge icon of a Wzorzec with a problem: ``text-warning`` for one Dad clears himself (open in Excel),
    ``text-destructive`` for a stop."""

    icon = _template_group(page, label).locator("[data-slot=badge] svg")
    expect(icon).to_have_class(re.compile(rf"(^|\s){color}(\s|$)"))


def _workers_answer(run: Run, name: str) -> dict[str, object]:
    workers = run.api("/api/settings", name)["workers"]
    assert isinstance(workers, dict)
    return workers


def _parts(workers: dict[str, object]) -> tuple[object, list[object], list[object]]:
    """State, Wykonawcy and matters to settle of the server's Lista Wykonawców."""

    listed, unresolved = workers["workers"], workers["unresolved"]
    assert isinstance(listed, list) and isinstance(unresolved, list)
    return workers["state"], listed, unresolved


def _names(workers: dict[str, object]) -> list[object]:
    return [worker["name"] for worker in _parts(workers)[1] if isinstance(worker, dict)]


def _listed(window: Locator) -> list[str | None]:
    """The names of the Wykonawcy in the section Wykonawcy, top to bottom (each list item is named by its Wykonawca)."""

    return [item.get_attribute("aria-label") for item in window.get_by_role("list", name="Wykonawcy").get_by_role("listitem").all()]


def _narrow_capture(run: Run, page: Page, name: str) -> None:
    """The section Wykonawcy in a phone-sized window of Dad's browser, for the screenshot ``name``."""

    with dad_tab(page, viewport=NARROW_VIEWPORT) as narrow:
        # On a phone the menu with the gear is folded away, so Dad comes by the address of the section.
        narrow.goto(run.url + "#/ustawienia/wykonawcy")
        expect(settings_window(narrow).get_by_role("heading")).to_have_text("Ustawienia/Wykonawcy")
        width = narrow.evaluate("document.documentElement.scrollWidth")
        run.check(width <= NARROW_VIEWPORT["width"], f"the section Wykonawcy fits {NARROW_VIEWPORT['width']} px without scrolling sideways")
        run.capture(narrow, name)


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
    window = open_settings(page, "Wzorce")
    alerts = window.get_by_role("alert")
    configuration = run.api("/api/configuration", "konfiguracja-gotowa")
    templates = configuration["templates"]
    assert isinstance(templates, list)
    run.check(
        [(template["label"], template["state"]) for template in templates]
        == [(label, "ready") for label in TEMPLATE_LABELS],
        "the server reports all three Wzorce present and readable",
    )
    workers = _workers_answer(run, "konfiguracja-gotowa-wykonawcy")
    run.check(
        (workers["state"], _names(workers), _parts(workers)[2]) == ("good", run.fixture["workers"], []),
        "the server lists the Wykonawcy in the order of the Lista Wykonawców, with nothing left to settle",
    )
    run.check("workers" not in configuration, "the configuration no longer carries the Wykonawcy: one source, the Ustawienia")
    commit, since = served_version(run)
    run.check(
        configuration["version"] == {"commit": commit[:7], "since": since},
        "the server reports the tool's commit and the day the tool moved there",
    )
    for label in TEMPLATE_LABELS:
        _shown_as_ready(page, label)
    expect(alerts).to_have_count(0)
    run.capture(page, "10-konfiguracja-gotowa")
    open_settings(page, "Wykonawcy")
    expect(window.get_by_role("list", name="Wykonawcy").get_by_role("listitem")).to_have_count(len(run.fixture["workers"]))
    run.check(_listed(window) == run.fixture["workers"], "the section Wykonawcy lists the active Wykonawcy in file order")
    first = window.get_by_role("listitem", name=run.fixture["workers"][0], exact=True)
    expect(first).to_contain_text("@przyklad.invalid")
    run.capture(page, "10b-konfiguracja-wykonawcy")
    _narrow_capture(run, page, "10a-konfiguracja-wykonawcy-waski")
    open_settings(page, "Narzędzie")
    expect(window.get_by_role("listitem", name="Wersja narzędzia").get_by_text(version_line(commit, since), exact=True)).to_be_visible()
    run.check(True, "the window shows the same Wzorce, Wykonawcy, and version, with no problem")

    run.step(feature, "konfiguracja-tylko-do-odczytu")
    run.check(
        window.get_by_role("button", name=UPDATE_BUTTON).count() == 0,
        "the section Narzędzie has no `Zaktualizuj narzędzie` for the current tool",
    )
    offer = run.api("/api/configuration", "konfiguracja-tylko-do-odczytu")
    run.check(
        (offer["freshness"], offer["update_offered"]) == ("current", False),
        "the server offers no Aktualizacja narzędzia for the current tool",
    )
    run.capture(page, "11-konfiguracja-tylko-do-odczytu", full_page=False)
    open_settings(page, "Wzorce")
    expect(window.locator("[data-slot=settings-section]").get_by_role("button")).to_have_count(0)
    run.check(True, "the section Wzorce offers no action on the Wzorce: Dad changes them in Excel (Wykonawcy: wykonawcy.md)")

    run.step(feature, "konfiguracja-wzorzec-otwarty")
    collective = files["collective_template"]
    lock = excel_lock(collective)
    lock.write_bytes(b"")
    try:
        page.reload()
        expect(_template_group(page, "Wzorzec pliku zbiorczego")).to_contain_text("Otwarty w Excelu")
        _expect_badge_icon(page, "Wzorzec pliku zbiorczego", "text-warning")
        message = window.get_by_role("alert", name="Ostrzeżenie", exact=True).filter(
            has_text="Wzorzec jest otwarty w Excelu."
        )
        expect(message).to_contain_text(f"plik {collective.name}, folder config")
        expect(message).to_contain_text(f"usuń z tego samego folderu pozostawiony plik ~${collective.name}")
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
            message = alerts.filter(has_text=INACCESSIBLE_TEMPLATE)
            expect(message).to_contain_text(f"plik {internal.name}, folder config")
            run.check("uszkodzon" not in message.inner_text(), "a Wzorzec without access is niedostępny, never uszkodzony")
            answer = _template_answer(run, "konfiguracja-wzorzec-niedostepny", "Wzorzec rozliczenia wewnętrznego")
            run.check(answer["problem"] == "unreadable", "the server reports the Wzorzec as not passing the Sprawdzanie")
            run.capture(page, "12a-konfiguracja-wzorzec-niedostepny")
        print("  harness: access to the Wzorzec is back", flush=True)
        page.evaluate("window.dispatchEvent(new FocusEvent('focus'))")
        _shown_as_ready(page, "Wzorzec rozliczenia wewnętrznego")
        expect(alerts).to_have_count(0)
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
        message = window.get_by_role("alert", name="Zatrzymanie", exact=True).filter(
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

    run.step(feature, "konfiguracja-zla-lista-wykonawcow")
    worker_list = files["worker_template"].parent / WORKERS_FILE
    moved = worker_list.with_name(worker_list.name + ".przeniesiony")
    move(worker_list, moved)
    try:
        worker_list.write_text("schema_version: 1\nwykonawcy: [niedomknięta lista\n", encoding="utf-8")
        page.reload()
        open_settings(page, "Wykonawcy")
        sentence = BROKEN_WORKER_LIST
        expect(alerts.filter(has_text=sentence)).to_have_count(1)
        expect(window.get_by_text("Na liście nie ma jeszcze Wykonawców.")).to_have_count(0)
        expect(window.get_by_text(LAST_GOOD_CAPTION, exact=True)).to_be_visible()
        run.check(
            "Zapisz Ustawienia" not in window.locator("[data-slot=settings-section]").inner_text(),
            "the section Wykonawcy never asks to save Ustawienia as a whole: only a change of a Wykonawca rewrites the list",
        )
        run.check(
            _listed(window) == run.fixture["workers"],
            "a broken Lista Wykonawców keeps showing the last good list under the sentence, never an empty good list",
        )
        workers = _workers_answer(run, "konfiguracja-zla-lista-wykonawcow")
        run.check(
            (workers["state"], workers["problem"]) == ("bad", {"field": None, "message": sentence}),
            "the server reports the Lista Wykonawców as bad, with the sentence and the last good list",
        )
        run.capture(page, "14-konfiguracja-zla-lista-wykonawcow")
        _narrow_capture(run, page, "14b-konfiguracja-zla-lista-wykonawcow-waski")
    finally:
        remove(worker_list, missing_ok=True)
        move(moved, worker_list)

    run.step(feature, "konfiguracja-niedostepna-lista-wykonawcow")
    with unreadable(worker_list):
        page.reload()
        message = alerts.filter(has_text=INACCESSIBLE_WORKER_LIST)
        expect(message).to_have_count(1)
        run.check(
            all(word not in message.inner_text() for word in ("uszkodzon", "niepoprawn")),
            "a Lista Wykonawców without access is niedostępna, never uszkodzona or niepoprawna",
        )
        expect(window.get_by_role("list", name="Wykonawcy")).to_have_count(0)
        expect(window.get_by_role("button", name="Spróbuj ponownie")).to_be_visible()
        workers = _workers_answer(run, "konfiguracja-niedostepna-lista-wykonawcow")
        run.check(
            (workers["state"], workers["problem"])
            == ("unreadable", {"field": None, "message": INACCESSIBLE_WORKER_LIST}),
            "the server reports the Lista Wykonawców as unreadable, with the sentence the section shows",
        )
        run.capture(page, "14a-konfiguracja-niedostepna-lista-wykonawcow")

    run.step(feature, "konfiguracja-do-rozstrzygniecia")
    move(worker_list, moved)
    try:
        print("  harness: the Lista Wykonawców gets the matters a migration of the old files leaves for Dad", flush=True)
        worker_list.write_bytes(
            read_bytes(moved)
            + (
                "do_rozstrzygniecia:\n"
                f"  - {{login: {UNRESOLVED_LOGIN}, adresy: [{UNRESOLVED_ADDRESS}], powod: login_bez_wykonawcy}}\n"
                f"  - {{powod: adresy_nieprzeniesione, zdanie: '{UNRESOLVED_SENTENCE}'}}\n"
            ).encode("utf-8")
        )
        page.reload()
        open_settings(page, "Wykonawcy")
        matters = window.get_by_role("list", name="Do rozstrzygnięcia").get_by_role("listitem")
        expect(matters).to_have_count(2)
        expect(matters.nth(0)).to_contain_text(UNRESOLVED_LOGIN)
        expect(matters.nth(0)).to_contain_text(UNRESOLVED_ADDRESS)
        expect(matters.nth(1)).to_have_text(UNRESOLVED_SENTENCE)
        run.check(_listed(window) == run.fixture["workers"], "the matters stand above the unchanged list, one sentence each")
        workers = _workers_answer(run, "konfiguracja-do-rozstrzygniecia")
        run.check(
            (workers["state"], len(_parts(workers)[2])) == ("good", 2),
            "the server gives the two matters with a good list",
        )
        run.capture(page, "14c-konfiguracja-do-rozstrzygniecia")
        _narrow_capture(run, page, "14d-konfiguracja-do-rozstrzygniecia-waski")
    finally:
        remove(worker_list, missing_ok=True)
        move(moved, worker_list)

    run.step(feature, "konfiguracja-bez-zmian")
    page.reload()
    open_settings(page, "Wzorce")
    for label in TEMPLATE_LABELS:
        _shown_as_ready(page, label)
    run.check(
        _configuration_snapshot(files) == before,
        "the Lista Wykonawców and every Wzorzec keep their bytes and modification times; no lock file is left",
    )
