"""Drive features/aktualnosc-i-onedrive.md."""

from __future__ import annotations

from pathlib import Path
import subprocess

from playwright.sync_api import Locator, Page, expect

from drive.common import (
    Run,
    diagnosis_answer,
    ensure_files_set,
    finished_view,
    move,
    open_setup,
    read_bytes,
    release_only,
    remove,
    sent_requests,
    settle,
    stop_banner,
)
from harness import File, Pace, Switch
from drive.teksty import FETCHING, NOT_FOUND, PROPOSAL, TEMPLATE_MISSING, UPDATE_BUTTON, UP_TO_DATE
from atrapy.scenariusz_centrum import PERIOD_WITHOUT_FILES

FEATURE = "aktualnosc-i-onedrive"
# The period of features/diagnoza.md: no Folder okresu and no orders, so no Uruchomienie here writes a file.
PERIOD = PERIOD_WITHOUT_FILES
NEWER = "Jest nowsza wersja narzędzia."
ONLY_IN_CLOUD = "Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze."
KEEP_ON_DEVICE = "„Zawsze zachowuj na tym urządzeniu”"
OTHER_MAIN = "f" * 40
FRESHNESS = "Aktualność narzędzia"
ONEDRIVE = "Pliki w OneDrive"
# Long enough to see the update running and click its button again; the local "origin" answers in milliseconds.
UPDATE_PACING_MS = 4000


def _stop_without_cause_on_computer(run: Run, page: Page) -> str:
    """A stop „do Maksa” whose cause is gone again: the Wzorzec rozliczenia wewnętrznego was missing during the run."""

    configuration = run.fixture["configuration"]
    assert isinstance(configuration, dict)
    template = Path(configuration["internal_template"])
    aside = template.with_name(f"{template.name}.odlozony")
    page.goto(run.url)
    ensure_files_set(run, page)
    open_setup(run, page, "Przygotowanie pliku zbiorczego", "aktualnosc", period=(PERIOD, "Brak plików okresu"))
    move(template, aside)
    try:
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(stop_banner(page)).to_contain_text(TEMPLATE_MISSING)
        view = finished_view(run, "aktualnosc-zatrzymanie")
    finally:
        move(aside, template)
    run.check(view["result"]["stop_kind"] == "for_maks", "the stop without its Wzorzec is „do Maksa”")
    return str(view["run"]["id"])


def _diagnose(page: Page) -> Locator:
    """A fresh Diagnoza of the stop shown on Uruchomienia; a reload drops the previous result."""

    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    explanation = page.get_by_role("region", name="Diagnoza").get_by_label("Wyjaśnienie Diagnozy")
    expect(explanation).to_be_visible()
    return explanation


def _proposal(page: Page) -> Locator:
    return page.get_by_role("region", name="Diagnoza").get_by_role("note", name="Propozycja aktualizacji")


def _no_update_offered(page: Page) -> None:
    expect(page.get_by_role("region", name="Diagnoza").get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_have_count(0)


def _state(answer: dict[str, object], label: str) -> tuple[str, str]:
    checks = answer["checks"]
    assert isinstance(checks, list)
    [found] = [check for check in checks if check["label"] == label]
    return found["state"], found["detail"]


def _shown_checks(page: Page) -> Locator:
    """Opens the collapsed list `Sprawdzono` of the Diagnoza and returns its items."""

    diagnosis = page.get_by_role("region", name="Diagnoza")
    diagnosis.get_by_role("button", name="Sprawdzono (11)", exact=True).click()
    return diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem")


def drive(run: Run, page: Page) -> None:
    register = Path(run.fixture["order_register"])
    main_commit = File.MAIN_COMMIT.file(run.root)

    run.step(FEATURE, "aktualnosc-nowsza-wersja")
    run_id = _stop_without_cause_on_computer(run, page)
    File.MAIN_COMMIT.write(run.root, OTHER_MAIN)
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(NEWER)
    expect(explanation).to_contain_text("Kliknij „Zaktualizuj narzędzie”.")
    update = explanation.get_by_role("button", name=UPDATE_BUTTON, exact=True)
    expect(update).to_be_enabled()
    expect(explanation.get_by_role("button", name="Uruchom ponownie", exact=True)).to_have_count(0)
    expect(_proposal(page)).to_have_count(0)
    run.check("bg-primary" in (update.get_attribute("class") or ""), "updating the tool is the explanation's main action")
    answer = diagnosis_answer(run, run_id, "aktualnosc-nowsza-wersja")
    run.check(
        _state(answer, FRESHNESS) == ("failed", NEWER)
        and answer["next_action"] == "update"
        and answer["update_proposal"] is False,
        "with no other cause a newer Wydanie on `main` explains the stop, and Dad updates the tool with the button",
    )
    run.capture(page, "76-aktualnosc-nowsza-wersja")

    run.step(FEATURE, "aktualnosc-brak-sieci")
    remove(main_commit)
    offline = Switch.GITHUB_OFFLINE.on(run.root)
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(NOT_FOUND)
    shown = _shown_checks(page).filter(has_text=FRESHNESS)
    expect(shown).to_contain_text("Nie sprawdzono: brak połączenia z GitHubem.")
    expect(shown.get_by_label("nie sprawdzono")).to_be_visible()
    _no_update_offered(page)
    answer = diagnosis_answer(run, run_id, "aktualnosc-brak-sieci")
    run.check(
        _state(answer, FRESHNESS)[0] == "not_checked"
        and answer["next_action"] == "report"
        and answer["update_proposal"] is False,
        "without network the freshness is not checked, is no cause, and the Diagnoza offers no update",
    )
    run.capture(page, "77-aktualnosc-brak-sieci")

    run.step(FEATURE, "onedrive-tylko-w-chmurze")
    remove(offline)
    before = (read_bytes(register), register.stat().st_mtime_ns)
    only_in_cloud = File.CLOUD_ONLY.write(run.root, str(register) + "\n")
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(ONLY_IN_CLOUD)
    expect(explanation).to_contain_text(f"plik {register.name}")
    expect(explanation).to_contain_text(KEEP_ON_DEVICE)
    expect(explanation.get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    answer = diagnosis_answer(run, run_id, "onedrive-tylko-w-chmurze")
    run.check(
        _state(answer, ONEDRIVE)[0] == "failed" and answer["next_action"] == "rerun",
        "a Rejestr zleceń only in the cloud explains the stop with „Zawsze zachowuj na tym urządzeniu”",
    )
    run.check((read_bytes(register), register.stat().st_mtime_ns) == before, "the Diagnoza left the Rejestr zleceń as it was")
    run.capture(page, "78-onedrive-tylko-w-chmurze")

    run.step(FEATURE, "aktualnosc-propozycja")
    File.MAIN_COMMIT.write(run.root, OTHER_MAIN)
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(ONLY_IN_CLOUD)
    expect(explanation.get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(_proposal(page)).to_contain_text(PROPOSAL)
    update = _proposal(page).get_by_role("button", name=UPDATE_BUTTON, exact=True)
    expect(update).to_be_enabled()
    run.check(
        "bg-primary" not in (update.get_attribute("class") or ""),
        "`Zaktualizuj narzędzie` in the proposal comes second, after the explanation's `Uruchom ponownie`",
    )
    answer = diagnosis_answer(run, run_id, "aktualnosc-propozycja")
    shown_explanation = answer["explanation"]
    assert isinstance(shown_explanation, dict)
    run.check(
        shown_explanation["what"] == ONLY_IN_CLOUD
        and _state(answer, FRESHNESS) == ("failed", NEWER)
        and (answer["next_action"], answer["update_proposal"]) == ("rerun", True),
        "a newer Wydanie does not cover the Rejestr zleceń only in the cloud: it is only proposed under the explanation",
    )
    run.capture(page, "81-aktualnosc-propozycja")
    _drive_update_in_progress(run, page, update)

    run.step(FEATURE, "aktualnosc-i-onedrive-przeszly")
    remove(main_commit)
    remove(only_in_cloud)
    explanation = _diagnose(page)
    expect(explanation).to_contain_text(NOT_FOUND)
    checks = _shown_checks(page)
    expect(checks.filter(has_text=FRESHNESS)).to_contain_text("Najnowsza wersja z GitHuba, commit ")
    expect(checks.filter(has_text=ONEDRIVE).get_by_label("przeszło")).to_be_visible()
    _no_update_offered(page)
    answer = diagnosis_answer(run, run_id, "aktualnosc-i-onedrive-przeszly")
    run.check(
        _state(answer, FRESHNESS)[0] == "passed"
        and _state(answer, ONEDRIVE)[0] == "passed"
        and answer["next_action"] != "update"
        and answer["update_proposal"] is False,
        "an up-to-date tool and files kept on the computer pass both checks, and the Diagnoza offers no update",
    )
    log = run.log()
    run.check(
        all(f"przyczyna={code}" in log for code in ("NOWSZA_WERSJA_NARZEDZIA", "PLIK_TYLKO_W_CHMURZE")),
        "the Centrum log records both causes by code only",
    )
    run.capture(page, "79-aktualnosc-i-onedrive-przeszly")



def _update_entries(run: Run) -> list[str]:
    return [entry.text for entry in run.log_entries() if entry.event == "aktualizacja-start"]


def _drive_update_in_progress(run: Run, page: Page, update: Locator) -> None:
    """Dad clicks `Zaktualizuj narzędzie` under the Diagnoza: while it runs the button cannot be clicked again."""

    run.step(FEATURE, "aktualnosc-aktualizacja-w-trakcie")
    tool = run.fixture["tool"]
    origin, clone = Path(tool["origin"]), Path(tool["clone"])
    head = subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    print("  harness: the local origin's only Wydanie is the clone's own commit, so the update changes nothing", flush=True)
    release_only(origin, head.stdout.strip())
    print(f"  harness: the Aktualizacja narzędzia waits {UPDATE_PACING_MS} ms before it looks for Git", flush=True)
    pacing = Pace.UPDATE.set(run.root, UPDATE_PACING_MS)
    started = len(_update_entries(run))
    diagnosis = page.get_by_role("region", name="Diagnoza")
    try:
        with sent_requests(page, "POST", "/api/tool-update") as sent:
            update.click()
            expect(diagnosis.get_by_role("status").filter(has_text=FETCHING)).to_be_visible()
            expect(update).to_be_disabled()
            update.click(force=True)
            run.check(settle(page, sent) == 1, "the click on the disabled button during the update sends nothing")
        run.check(
            run.api("/api/tool-update", "aktualnosc-aktualizacja-w-trakcie") == {"state": "running", "step": "fetching"},
            "the server reports the update running",
        )
        diagnosis.get_by_role("status").filter(has_text=FETCHING).evaluate(
            "element => Promise.all(element.getAnimations().map((animation) => animation.finished))"
        )
        run.capture(page, "140-aktualnosc-aktualizacja-w-trakcie", live=True)
    finally:
        remove(pacing, missing_ok=True)
    try:
        expect(diagnosis.get_by_role("status").filter(has_text=UP_TO_DATE)).to_be_visible(timeout=20_000)
        expect(update).to_be_enabled()
        run.check(
            len(_update_entries(run)) == started + 1,
            "the click on the disabled button during the update started no second Aktualizacja narzędzia",
        )
    finally:
        release_only(origin, tool["newest"])
