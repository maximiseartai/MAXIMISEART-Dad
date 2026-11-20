"""Drive features/stanowisko-andrzeja.md."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import Page, Response, expect

from drive.common import (
    Run,
    close_centrum,
    close_settings,
    move,
    open_settings,
    remove,
    remove_empty_folder,
    settings_window,
    start_centrum,
)
from drive.uporzadkowanie_intermax import CARD
from rozliczenia.centrum.scope import WORKSTATION_FILE, CentrumFunction

FEATURE = "stanowisko-andrzeja"
ANDRZEJ = "andrzej"
ANDRZEJ_FUNCTIONS = ["intermax", "intermax_copies"]
MENU = ["Uruchomienia"]
SETTINGS_GROUPS = ["Praca", "Pliki", "Połączenia", "Narzędzie", "Historia"]
SETTINGS_SECTIONS = ["Foldery", "Kopie INTERMAX", "Zgłoszenia", "Narzędzie", "Wygląd", "Historia"]
AUTOSTART = "Uruchamiaj Centrum razem z Windows"
LOAD_FAILURE = "Nie udało się odczytać"
WORKSTATION_WORDS = ("Stanowisk", "Andrzej")
TEMPLATES_ASIDE = "Wzorce poza config"


def _config(run: Run) -> Path:
    return Path(run.fixture["settings"]).parent


def _templates(run: Run) -> list[Path]:
    return [Path(path) for path in run.fixture["configuration"].values() if Path(path).suffix == ".xlsx"]


def _functions(run: Run, name: str) -> object:
    return run.api("/api/scope", name)["functions"]


def _menu(page: Page) -> list[str]:
    menu = page.get_by_role("list", name="Sekcje Centrum rozliczeń")
    return [link.strip() for link in menu.get_by_role("link").all_inner_texts()]


def _no_workstation(run: Run, page: Page, where: str) -> None:
    text = page.locator("body").inner_text()
    run.check(not any(word in text for word in WORKSTATION_WORDS), f"{where}: the page names no Stanowisko")


def drive(run: Run, page: Page) -> None:
    lost: list[str] = []

    def answered(response: Response) -> None:
        path = urlsplit(response.url).path
        if path.startswith("/api/") and response.status >= 400:
            lost.append(f"{response.request.method} {path} {response.status}")

    run.step(FEATURE, "start-bez-wzorcow")
    close_centrum(run, page)
    (_config(run) / WORKSTATION_FILE).write_text(f"{ANDRZEJ}\n", encoding="utf-8")
    aside = run.root / TEMPLATES_ASIDE
    aside.mkdir()
    for template in _templates(run):
        move(template, aside / template.name)
    start_centrum(run, "andrzej-start")
    run.check(not any(template.exists() for template in _templates(run)), "Andrzej's Centrum starts without the Wzorce")
    functions = _functions(run, "andrzej-zakres")
    run.check(functions == ANDRZEJ_FUNCTIONS, f"its Zakres has only Uporządkowanie and Kopie INTERMAX ({functions})")

    page.on("response", answered)
    try:
        run.step(FEATURE, "strona-startowa")
        page.goto(run.url)
        expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
        expect(page.get_by_role("region", name=CARD, exact=True)).to_be_visible()
        run.check(_menu(page) == MENU, f"the menu has only Uruchomienia ({_menu(page)})")
        run.check(page.get_by_role("radiogroup", name="Proces").count() == 0, "no card of a process with a period")
        run.check(page.get_by_role("tab").count() == 0, "Uruchomienia have no tab Historia of the Metryki")
        _no_workstation(run, page, "Uruchomienia")
        run.capture(page, "510-andrzej-uruchomienia")

        run.step(FEATURE, "adres-spoza-zakresu")
        for outside in ("#/okresy", "#/metryki", "#/raporty", "#/wysylka", "#/uzupelnienie/06_12_10_2026"):
            page.goto(run.url + outside)
            expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
        run.check(True, "each address outside the Zakres opens Uruchomienia")

        run.step(FEATURE, "ustawienia")
        window = open_settings(page, "Foldery")
        groups = [label.strip() for label in window.locator("[data-slot=sidebar-group-label]").all_inner_texts()]
        sections = [link.strip() for link in window.get_by_role("list").get_by_role("link").all_inner_texts()]
        run.check(groups == SETTINGS_GROUPS, f"the window has only the groups of Andrzej's sections ({groups})")
        run.check(sections == SETTINGS_SECTIONS, f"the window has only Andrzej's sections ({sections})")
        expect(window.get_by_text("Rejestr zleceń", exact=True)).to_be_visible()
        run.check(window.get_by_text("Folder okresów", exact=True).count() == 0, "Foldery has only the Rejestr zleceń")
        run.capture(page, "511-andrzej-ustawienia-foldery", full_page=False)
        open_settings(page, "Narzędzie")
        expect(window.get_by_text("Wersja narzędzia", exact=True)).to_be_visible()
        run.check(window.get_by_role("switch", name=AUTOSTART).count() == 0, "Narzędzie has no switch of the autostart")
        _no_workstation(run, page, "Ustawienia")
        run.capture(page, "512-andrzej-ustawienia-narzedzie", full_page=False)
        close_settings(page)
        expect(settings_window(page)).to_have_count(0)

        run.step(FEATURE, "bez-bledow-ladowania")
        run.check(page.get_by_text(LOAD_FAILURE).count() == 0, "no page shows a load failure")
        run.check(lost == [], f"Centrum answered every read of Andrzej's pages ({lost})")
    finally:
        page.remove_listener("response", answered)

    run.step(FEATURE, "powrot-taty")
    close_centrum(run, page)
    remove(_config(run) / WORKSTATION_FILE)
    for template in _templates(run):
        move(aside / template.name, template)
    remove_empty_folder(aside)
    start_centrum(run, "tata-start")
    functions = _functions(run, "tata-zakres")
    run.check(functions == [function.value for function in CentrumFunction], f"Dad's Centrum has every Function ({functions})")
    page.goto(run.url)
    expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
    run.check(_menu(page)[:2] == ["Okresy", "Uruchomienia"], f"Dad's menu starts with Okresy ({_menu(page)})")
