"""Drive features/wykonawcy.md."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Locator, Page, ViewportSize, expect

from drive.common import DAD_VIEWPORT, Run, ensure_files_set, open_settings, read_bytes, read_text, settings_window

FEATURE = "wykonawcy"
NARROW: ViewportSize = {"width": 420, "height": 860}
# Synthetic Wykonawcy of the fixture (create_centrum_fixture.py): A–C have orders, D none; E is new and has none.
A, B, C, D = "Wykonawca Testowy A", "Wykonawca Testowy B", "Wykonawca Testowy C", "Wykonawca Testowy D"
NEW_LOGIN, NEW_NAME, NEW_ADDRESS = "wykonawca.e", "Wykonawca Testowy E", "wykonawca.e@przyklad.invalid"
RENAMED = "Wykonawca Testowy A2"
READY_PERIOD = "22_28_09_2026"
# The sentences the server gives, copied on purpose (skille.md: the oracle does not import what it checks).
ADDRESS_TAKEN = "Ten adres jest już na Liście Wykonawców. Jeden adres należy do jednego Wykonawcy."
KEPT_IN_REGISTER = "Wykonawca ma zlecenia w Rejestrze zleceń, więc zostaje na Liście Wykonawców."
OLD_NAME = f"Rozliczenie pracownika ze starą nazwą jest już w okresie {READY_PERIOD}."


def _row(window: Locator, name: str) -> Locator:
    return window.get_by_role("list", name="Wykonawcy").get_by_role("listitem", name=name, exact=True)


def _workers(run: Run, name: str) -> dict[str, dict[str, object]]:
    answer = run.api("/api/settings", name)["workers"]
    assert isinstance(answer, dict)
    return {str(worker["name"]): worker for worker in answer["workers"]}


def _save(window: Locator) -> None:
    window.get_by_role("button", name="Zapisz Wykonawcę").click()


def drive(run: Run, page: Page) -> None:
    page.goto(run.url + "#/okresy")
    ensure_files_set(run, page)
    worker_list = run.config / "wykonawcy.yaml"
    before = read_bytes(worker_list)
    ready_workers = Path(run.fixture["periods_directory"]) / READY_PERIOD / f"Rozliczenie pracowników {READY_PERIOD}"
    ready_files = sorted(path.name for path in ready_workers.iterdir())

    run.step(FEATURE, "wykonawcy-dodanie")
    window = open_settings(page, "Wykonawcy")
    window.get_by_role("button", name="Dodaj Wykonawcę", exact=True).click()
    form = window.get_by_role("form", name="Nowy Wykonawca")
    form.get_by_role("textbox", name="Login", exact=True).fill(NEW_LOGIN)
    form.get_by_label("Nazwa w Rozliczeniu pracownika").fill(NEW_NAME)
    form.get_by_role("button", name="Dodaj adres").click()
    form.get_by_role("textbox", name="Adres 1").fill(NEW_ADDRESS)
    run.capture(page, "380-wykonawcy-formularz", full_page=False)
    _save(form)
    expect(_row(window, NEW_NAME)).to_contain_text(NEW_ADDRESS)
    expect(form).to_have_count(0)
    added = _workers(run, "wykonawcy-dodany")[NEW_NAME]
    run.check(
        (added["logins"], added["addresses"], added["active"], added["reminders"]) == ([NEW_LOGIN], [NEW_ADDRESS], True, True),
        "the new Wykonawca is on the list, active and with Przypomnienia o raporcie",
    )
    run.check(NEW_LOGIN in read_text(worker_list), "the Lista Wykonawców file has the new login")

    run.step(FEATURE, "wykonawcy-odmowa-przy-polu")
    window.get_by_role("button", name="Dodaj Wykonawcę", exact=True).click()
    form = window.get_by_role("form", name="Nowy Wykonawca")
    form.get_by_role("textbox", name="Login", exact=True).fill("wykonawca.f")
    form.get_by_label("Nazwa w Rozliczeniu pracownika").fill("Wykonawca Testowy F")
    form.get_by_role("button", name="Dodaj adres").click()
    form.get_by_role("textbox", name="Adres 1").fill("wykonawca.a@przyklad.invalid")
    saved_bytes = read_bytes(worker_list)
    _save(form)
    expect(form.get_by_role("alert")).to_have_text(ADDRESS_TAKEN)
    expect(form.get_by_role("textbox", name="Adres 1")).to_have_attribute("aria-invalid", "true")
    run.check(read_bytes(worker_list) == saved_bytes, "an address of another Wykonawca is not saved")
    run.capture(page, "381-wykonawcy-odmowa-przy-polu", full_page=False)
    form.get_by_role("button", name="Anuluj").click()

    run.step(FEATURE, "wykonawcy-zamkniecie-bez-zapisu")
    _row(window, A).get_by_role("button", name=f"Edytuj: {A}").click()
    form = window.get_by_role("form", name=f"Wykonawca {A}")
    form.get_by_label("Nazwa w Rozliczeniu pracownika").fill(RENAMED)
    page.keyboard.press("Escape")
    question = page.get_by_role("alertdialog", name="Zamknąć bez zapisu?")
    expect(question).to_be_visible()
    run.capture(page, "382-wykonawcy-zamkniecie-bez-zapisu", full_page=False)
    question.get_by_role("button", name="Wróć").click()
    expect(settings_window(page)).to_be_visible()
    expect(form.get_by_label("Nazwa w Rozliczeniu pracownika")).to_have_value(RENAMED)
    run.check(True, "closing Ustawienia with an unsaved form asks first, and Wróć keeps what Dad typed")

    run.step(FEATURE, "wykonawcy-stara-nazwa")
    _save(form)
    asked = page.get_by_role("alertdialog", name="Zmienić nazwę?")
    expect(asked).to_contain_text(OLD_NAME)
    run.check(_workers(run, "wykonawcy-przed-potwierdzeniem")[A]["name"] == A, "nothing is saved before Dad confirms")
    run.capture(page, "383-wykonawcy-stara-nazwa", full_page=False)
    asked.get_by_role("button", name="Zmień nazwę").click()
    expect(_row(window, RENAMED)).to_be_visible()
    run.check(
        sorted(path.name for path in ready_workers.iterdir()) == ready_files,
        "the Rozliczenie pracownika with the old name stays as it was: Centrum renames none of Dad's files",
    )

    run.step(FEATURE, "wykonawcy-odmowa-usuniecia")
    _row(window, B).get_by_role("button", name=f"Edytuj: {B}").click()
    form = window.get_by_role("form", name=f"Wykonawca {B}")
    form.get_by_role("button", name="Usuń Wykonawcę").click()
    expect(form.get_by_role("alert")).to_contain_text(KEPT_IN_REGISTER)
    expect(form.get_by_role("button", name="Oznacz jako nieaktywnego")).to_be_visible()
    run.check(B in _workers(run, "wykonawcy-odmowa-usuniecia"), "a Wykonawca with orders in the Rejestr zleceń stays")
    run.capture(page, "384-wykonawcy-odmowa-usuniecia", full_page=False)
    form.get_by_role("button", name="Anuluj").click()

    run.step(FEATURE, "wykonawcy-przelaczniki")
    _row(window, D).get_by_role("button", name=f"Edytuj: {D}").click()
    form = window.get_by_role("form", name=f"Wykonawca {D}")
    form.get_by_role("button", name="Oznacz jako nieaktywnego").click()
    expect(_row(window, D).get_by_text("Nieaktywny", exact=True)).to_be_visible()
    form.get_by_role("button", name="Anuluj").click()
    _row(window, C).get_by_role("switch", name=f"Przypomnienia: {C}").click()
    expect(_row(window, C).get_by_role("switch", name=f"Przypomnienia: {C}")).not_to_be_checked()
    switched = _workers(run, "wykonawcy-przelaczniki")
    run.check(
        (switched[D]["active"], switched[C]["reminders"]) == (False, False),
        "Nieaktywny and Przypomnienia are saved at once, without Zapisz",
    )
    names = window.get_by_role("list", name="Wykonawcy").get_by_role("listitem").evaluate_all(
        "items => items.map((item) => item.getAttribute('aria-label'))"
    )
    run.check(names[-1] == D, f"the Nieaktywny Wykonawca stands below the active ones ({names})")
    run.capture(page, "385-wykonawcy-lista", full_page=False)

    run.step(FEATURE, "wykonawcy-waskie-okno")
    page.set_viewport_size(NARROW)
    try:
        expect(window.get_by_role("combobox", name="Sekcja Ustawień")).to_contain_text("Wykonawcy")
        _row(window, NEW_NAME).get_by_role("button", name=f"Edytuj: {NEW_NAME}").click()
        page.wait_for_function("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        run.check(True, "on a narrow window the form fits without a horizontal scroll")
        run.capture(page, "386-wykonawcy-formularz-waski", full_page=False)
        window.get_by_role("form", name=f"Wykonawca {NEW_NAME}").get_by_role("button", name="Anuluj").click()
        run.capture(page, "387-wykonawcy-lista-waska", full_page=False)
    finally:
        page.set_viewport_size(DAD_VIEWPORT)

    run.step(FEATURE, "wykonawcy-usuniecie-i-powrot")
    _row(window, NEW_NAME).get_by_role("button", name=f"Edytuj: {NEW_NAME}").click()
    window.get_by_role("form", name=f"Wykonawca {NEW_NAME}").get_by_role("button", name="Usuń Wykonawcę").click()
    expect(_row(window, NEW_NAME)).to_have_count(0)
    run.check(NEW_NAME not in _workers(run, "wykonawcy-usuniety"), "a Wykonawca whose login no period has is removed")
    # Back to the fixture's list for the features after this one: the same changes in the other direction.
    _row(window, RENAMED).get_by_role("button", name=f"Edytuj: {RENAMED}").click()
    form = window.get_by_role("form", name=f"Wykonawca {RENAMED}")
    form.get_by_label("Nazwa w Rozliczeniu pracownika").fill(A)
    _save(form)
    expect(_row(window, A)).to_be_visible()
    _row(window, D).get_by_role("button", name=f"Edytuj: {D}").click()
    window.get_by_role("form", name=f"Wykonawca {D}").get_by_role("button", name="Oznacz jako aktywnego").click()
    expect(_row(window, D).get_by_text("Nieaktywny", exact=True)).to_have_count(0)
    window.get_by_role("form", name=f"Wykonawca {D}").get_by_role("button", name="Anuluj").click()
    _row(window, C).get_by_role("switch", name=f"Przypomnienia: {C}").click()
    expect(_row(window, C).get_by_role("switch", name=f"Przypomnienia: {C}")).to_be_checked()
    run.wait_for(lambda: read_bytes(worker_list) == before, "the Lista Wykonawców is the fixture's again, byte for byte")
    # ✕ rather than Esc: the first Esc closes the notification „Zapisano · Cofnij” of the last switch.
    window.get_by_role("button", name="Zamknij Ustawienia").click()
    expect(settings_window(page)).to_have_count(0)
