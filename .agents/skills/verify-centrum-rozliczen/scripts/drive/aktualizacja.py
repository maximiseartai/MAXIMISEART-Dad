"""Drive features/aktualizacja.md."""

from __future__ import annotations

import json
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import subprocess

from playwright.sync_api import Locator, Page

from drive.common import (
    Run,
    advance_clock,
    close_settings,
    answers,
    move,
    open_settings,
    read_bytes,
    read_json,
    read_text,
    release_only,
    remove,
    served_version,
    settings_section,
    settings_title,
    version_line,
)
from drive.waiting import Budget, expect, until
from harness import File, Pace, Switch
from drive.teksty import FETCHING, UPDATE_BUTTON, UP_TO_DATE
from atrapy.pliki_taty import UPDATE_RESULT_FILE, WORKER_MAPPING_FILE as WORKER_MAPPING
from rozliczenia.centrum.tool_update import RESULT_FILE

# The section Narzędzie of Ustawienia: version, Aktualność and „Zaktualizuj narzędzie”.
TOOL_SECTION = "#/ustawienia/narzedzie"
FEATURE = "aktualizacja"
UPDATED = "Zaktualizowano"
RESTARTING = "Ponowne uruchamianie Centrum…"
NO_CONNECTION = "Nie zaktualizowano narzędzia: brak połączenia z GitHubem."
RETRY = "Narzędzie działa dalej w poprzedniej wersji. Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz."
REPORT_BUTTON = "Wyślij do Maksa"
READ_FAILED = "Nie udało się odczytać stanu aktualizacji."
INSTALLING = "Instalowanie bibliotek…"
LIBRARIES_FAILED = "Nie udało się zainstalować bibliotek nowej wersji narzędzia."
NEW_VERSION_FAILED = "Nowa wersja narzędzia nie wystartowała."
UNEXPECTED = "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu."
TO_MAKS = "Narzędzie działa dalej w poprzedniej wersji. Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."
# Long enough to see the installation start; installing from no index fails in about a second.
PACING_MS = 4000
# Long enough to see the progress, send the refused requests and capture it during the same update; fetching from
# the local "origin" takes milliseconds.
UPDATE_PACING_MS = 8000
# Long enough to see the tab wait for the new Centrum; the restarted scripted Centrum starts in about a second.
RESTART_PACING_MS = 3000
# Long enough for the harness to put „ok” back after the guardian's failure and before the old version reads it.
OK_ON_OLD_VERSION_PACING_MS = 5000
# The read of the configuration (`/api/configuration`) keeps GitHub's answer about the newest Wydanie for 10 minutes of Centrum's clock.
MAIN_KEPT_MIN = 10
# A Wydanie GitHub names but the update does not take: the clone and the local origin never had this commit.
DORMANT_RELEASE = "e" * 40


def _git(clone: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _github_main(run: Run, commit: str) -> None:
    """The newest Wydanie on the scripted GitHub is ``commit``; Centrum's clock moves past the time Centrum keeps the old answer."""

    File.MAIN_COMMIT.write(run.root, commit)
    _forget_github_answer(run)


def _forget_github_answer(run: Run) -> None:
    advance_clock(run, MAIN_KEPT_MIN, "Centrum asks GitHub again")


def _github_dormant_release(run: Run) -> None:
    print(
        "  harness: the scripted GitHub names a Wydanie the update does not take, a tag that never was the tip of"
        " `main` (ADR 0014): Aktualność says newer by reachability, the update picks by the first-parent line",
        flush=True,
    )
    _github_main(run, DORMANT_RELEASE)


def _head(clone: Path) -> str:
    return _git(clone, "rev-parse", "HEAD")


def _contents(directory: Path) -> dict[str, bytes]:
    return {str(path.relative_to(directory)): read_bytes(path) for path in directory.rglob("*") if path.is_file()}


def _dad_files_kept(run: Run, clone: Path, dad_files: dict[str, str], run_configuration: dict[str, bytes]) -> None:
    run.check(
        {name: read_text(clone / name) for name in dad_files} == dad_files,
        "Dad's files in the tool's config/ keep exactly their content, the changed old Wykonawcy file too",
    )
    run.check(
        _git(clone, "ls-files", "--", WORKER_MAPPING) == "",
        "the new version no longer tracks the old Wykonawcy file that Dad still has",
    )
    run.check(_contents(run.config) == run_configuration, "the run's configuration directory is untouched")


@contextmanager
def _without_internet(run: Run) -> Iterator[None]:
    """No internet on Dad's computer: the local "origin", the scripted GitHub and the skrzynka are out of reach."""

    origin = Path(run.fixture["tool"]["origin"])
    away = origin.with_name("origin-poza-zasiegiem.git")
    switches = (Switch.GITHUB_OFFLINE, Switch.BOX_OFFLINE)
    print("  harness: no internet (the local origin moved out of reach, GitHub and the skrzynka unreachable)", flush=True)
    move(origin, away)
    markers = [switch.on(run.root) for switch in switches]
    try:
        yield
    finally:
        move(away, origin)
        for marker in markers:
            remove(marker, missing_ok=True)
        print("  harness: the internet is back", flush=True)


def _drive_no_connection(run: Run, page: Page, card: Locator, clone: Path, first: str) -> None:
    run.step(FEATURE, "aktualizacja-brak-sieci")
    with _without_internet(run):
        # Harness: Centrum was busy for a moment as Dad opened the section Narzędzie, so the read of the update's state failed.
        page.route("**/api/tool-update", lambda route: route.abort() if route.request.method == "GET" else route.fallback())
        try:
            page.reload()
            expect(_status(page, READ_FAILED)).to_be_visible()
        finally:
            page.unroute("**/api/tool-update")
        card.get_by_role("button", name=UPDATE_BUTTON, exact=True).click()
        message = card.get_by_role("alert", name="Ostrzeżenie")
        expect(message).to_contain_text(NO_CONNECTION, timeout=Budget.SLOWED.ms)
        expect(_status(page, READ_FAILED)).to_have_count(0)
        expect(message).to_contain_text("narzędzie na tym komputerze")
        expect(message).to_contain_text(RETRY)
        update = card.get_by_role("button", name=UPDATE_BUTTON, exact=True)
        expect(update).to_be_enabled()
        report = card.get_by_role("button", name=REPORT_BUTTON, exact=True)
        expect(report).to_be_visible()
        run.check("bg-primary" in (update.get_attribute("class") or ""), "trying again is the main action")
        run.check("bg-primary" not in (report.get_attribute("class") or ""), "`Wyślij do Maksa` is the second action")
        view = run.api("/api/tool-update", "aktualizacja-brak-sieci")
        run.check(
            (view["state"], view["message"], view["next_action"], view["report"])
            == (
                "failed",
                {"what": NO_CONNECTION, "where": "narzędzie na tym komputerze", "action": RETRY},
                "retry",
                {"state": "ready"},
            ),
            "the server reports the Komunikat in three parts, a retry, and a Zgłoszenie ready to send",
        )
        run.check(_head(clone) == first, "the clone stays on the commit Dad had")
        run.check(
            _git(clone, "status", "--porcelain", "--", WORKER_MAPPING) == f"M {WORKER_MAPPING}",
            "Dad's changed old Wykonawcy file is still there, still tracked",
        )
        run.check(
            _update_entries(run)
            == [f"aktualizacja-start przed={first}", f"aktualizacja-koniec wynik=BRAK_POLACZENIA przed={first} po=- biblioteki=nie"],
            "the Centrum log has the failed update with its code and commit, and no path",
        )
        run.capture(page, "115-aktualizacja-brak-sieci")
        card.get_by_role("button", name="Co zostanie wysłane").click()
        preview = card.get_by_role("figure", name="Treść Zgłoszenia")
        expect(preview).to_contain_text(f"BRAK_POLACZENIA: {NO_CONNECTION}")
        expect(preview).to_contain_text(f"- Commit przed: {first}")
        expect(preview).to_contain_text("- Biblioteki instalowane: nie")
        expect(preview).to_contain_text("aktualizacja-koniec wynik=BRAK_POLACZENIA")
        draft = view["draft"]
        run.check(
            isinstance(draft, dict) and "origin" not in str(draft["body"]) and str(run.root) not in str(draft["body"]),
            "the Zgłoszenie has the log's facts, no path and no Git output",
        )
        run.capture(page, "116-aktualizacja-brak-sieci-zgloszenie")

        _forget_github_answer(run)
        page.reload()
        expect(card).to_contain_text("Nie sprawdzono")
        expect(card.get_by_role("alert", name="Ostrzeżenie")).to_contain_text(NO_CONNECTION)
        expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_have_count(0)
        configuration = run.api("/api/configuration", "aktualizacja-brak-sieci-konfiguracja")
        run.check(
            (configuration["freshness"], configuration["update_offered"]) == ("not_checked", False),
            "without GitHub's answer Ustawienia offer no update; the failed update's Komunikat stays in the card",
        )
        run.capture(page, "117-aktualizacja-brak-sieci-bez-przycisku")


def _status(page: Page, text: str) -> Locator:
    return page.get_by_role("status").filter(has_text=text)


def _entered(status: Locator) -> None:
    """Waits for the status's own entrance; its spinner turns on, so a live capture cannot wait for every animation."""

    status.evaluate("element => Promise.all(element.getAnimations().map((animation) => animation.finished))")


def _update_entries(run: Run) -> list[str]:
    """The start and end entries of every Aktualizacja narzędzia in the Centrum log, without their moment."""

    return [entry.text for entry in run.log_entries() if entry.event in ("aktualizacja-start", "aktualizacja-koniec")]


def _log_events(run: Run) -> list[str]:
    return [entry.event for entry in run.log_entries() if entry.event != "pomiar"]


def _since_update(run: Run) -> list[str]:
    events = _log_events(run)
    return events[len(events) - events[::-1].index("aktualizacja-start") :]


def drive(run: Run, page: Page) -> None:
    tool = run.fixture["tool"]
    clone, first, newest, dad_files = Path(tool["clone"]), tool["first"], tool["newest"], tool["dad_files"]
    origin, libraries = Path(tool["origin"]), tool["libraries"]
    run_configuration = _contents(run.config)
    main_commit = File.MAIN_COMMIT.file(run.root)
    pacing = Pace.UPDATE.file(run.root)
    restart_pacing = Pace.RESTART.file(run.root)

    run.step(FEATURE, "aktualizacja-jest-nowsza")
    print("  harness: the newest Wydanie on the scripted GitHub is the local origin's newest commit", flush=True)
    _github_main(run, newest)
    try:
        run.check(_head(clone) == first, "the run's tool clone stands on the first commit")
        run.check(
            _git(clone, "status", "--porcelain", "--", WORKER_MAPPING) == f"M {WORKER_MAPPING}",
            "Dad changed the tracked old Wykonawcy file in the clone",
        )
        page.goto(run.url + TOOL_SECTION)
        page.reload()
        card = settings_section(page)
        first_commit, first_since = served_version(run)
        expect(card.get_by_text(version_line(first_commit, first_since), exact=True)).to_be_visible()
        expect(card).to_contain_text("Jest nowsza wersja")
        configuration = run.api("/api/configuration", "aktualizacja-jest-nowsza")
        run.check(
            (first_commit, configuration["version"], configuration["freshness"], configuration["update_offered"])
            == (first, {"commit": first[:7], "since": first_since}, "newer", True),
            "the server reports the clone's commit, the day the clone moved there, a newer version, and offers the update",
        )
        expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_enabled()
        run.check(
            run.api("/api/tool-update", "aktualizacja-przed")["state"] == "idle",
            "no Aktualizacja narzędzia since Centrum started",
        )
        run.capture(page, "93-aktualizacja-jest-nowsza")
        _drive_no_connection(run, page, card, clone, first)
        _github_main(run, newest)

        run.step(FEATURE, "aktualizacja-postep")
        page.reload()
        expect(card).to_contain_text("Jest nowsza wersja")
        expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_enabled()
        print(f"  harness: each Aktualizacja narzędzia waits {UPDATE_PACING_MS} ms before it looks for Git", flush=True)
        Pace.UPDATE.set(run.root, UPDATE_PACING_MS)
        print(f"  harness: the restarted Centrum waits {RESTART_PACING_MS} ms before it starts", flush=True)
        Pace.RESTART.set(run.root, RESTART_PACING_MS)
        before_health = run.api("/api/health", "aktualizacja-health-przed")
        page.evaluate("window.przedPonownymStartem = true")
        card.get_by_role("button", name=UPDATE_BUTTON, exact=True).dblclick()
        expect(card.get_by_role("status").filter(has_text=FETCHING)).to_be_visible()
        expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_disabled()
        view = run.api("/api/tool-update", "aktualizacja-postep")
        run.check(view == {"state": "running", "step": "fetching"}, "the server reports the step `fetching`")
        run.check(
            run.post("/api/tool-update", "aktualizacja-druga-odmowa").status == 409,
            "a second Aktualizacja narzędzia is refused while one runs",
        )
        run.check(
            run.post("/api/shutdown", "aktualizacja-zamkniecie-odmowa").status == 409,
            "closing Centrum is refused while the update runs",
        )
        _entered(_status(page, FETCHING))
        run.capture(page, "94-aktualizacja-postep", live=True)
        run.check(
            [entry.split(" ")[0] for entry in _update_entries(run)[2:]] == ["aktualizacja-start"],
            "with the internet back, the double click started exactly one more Aktualizacja narzędzia",
        )
    finally:
        remove(pacing, missing_ok=True)

    try:
        run.step(FEATURE, "aktualizacja-ponowny-start")
        expect(_status(page, RESTARTING)).to_be_visible(timeout=Budget.SLOWED.ms)
        expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_disabled()
        # The card shows the restart once the server says it restarts, before the old Centrum closes its port;
        # on Windows the old one still answers then.
        until(lambda: not answers(run.url), "the old Centrum has closed and the new one is not up yet")
        run.check(_log_events(run)[-3:] == ["aktualizacja-start", "zamkniecie", "stop"], "the old Centrum closed itself and logged its stop")
        run.check(
            "zamkniecie z=aktualizacja" in run.log(),
            "the closing names the update, not the card",
        )
        run.capture(page, "100-aktualizacja-ponowny-start", live=True)
    finally:
        remove(restart_pacing, missing_ok=True)

    try:
        run.step(FEATURE, "aktualizacja-zaktualizowano")
        toast = page.get_by_role("region", name="Notifications").get_by_role("dialog", name=UPDATED)
        expect(toast).to_be_visible(timeout=Budget.BACKGROUND.ms)
        expect(toast).to_contain_text(f"Centrum działa w wersji {newest[:7]}.")
        run.check(page.evaluate("window.przedPonownymStartem === undefined"), "the tab reloaded by itself")
        expect(settings_title(page)).to_have_text("Ustawienia/Narzędzie")
        run.check(True, "the reloaded tab is back on Ustawienia, section Narzędzie, in the new version")
        card = settings_section(page)
        updated_commit, since = served_version(run)
        expect(card.get_by_text(version_line(updated_commit, since), exact=True)).to_be_visible()
        expect(card).to_contain_text("Aktualna")
        expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_have_count(0)
        health = run.api("/api/health", "aktualizacja-health-po")
        run.check(
            health["commit"] == newest[:7] and health["instance"] != before_health["instance"],
            "a new Centrum answers on the same address, in the new commit",
        )
        view = run.api("/api/tool-update", "aktualizacja-zaktualizowano")
        run.check(view == {"state": "updated"}, "the new Centrum reports the update's result")
        run.check(_head(clone) == newest, "the clone moved forward to the origin's newest commit")
        _dad_files_kept(run, clone, dad_files, run_configuration)
        configuration = run.api("/api/configuration", "aktualizacja-konfiguracja-po")
        run.check(
            (updated_commit, configuration["version"], configuration["freshness"], configuration["update_offered"])
            == (newest, {"commit": newest[:7], "since": since}, "current", False),
            "Ustawienia report the new commit as current, since the day of the update, and offers no update",
        )
        run.check(
            not (run.config / RESULT_FILE).exists(),
            "the new Centrum read the guardian's result once and removed it",
        )
        entries = _update_entries(run)
        run.check(
            entries[2:] == [f"aktualizacja-start przed={first}", f"aktualizacja-koniec wynik=ok przed={first} po={newest} biblioteki=nie"],
            "the Centrum log has the retry's start and end with both commits, and no path",
        )
        run.check(
            _since_update(run) == ["zamkniecie", "stop", "aktualizacja-koniec", "start"],
            "the old Centrum logged its stop, then the new Centrum the end of the update and its start",
        )
        run.capture(page, "101-aktualizacja-zaktualizowano")

        run.step(FEATURE, "aktualizacja-najnowsza")
        _github_dormant_release(run)
        page.reload()
        expect(card).to_contain_text("Jest nowsza wersja")
        card.get_by_role("button", name=UPDATE_BUTTON, exact=True).click()
        expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_be_visible()
        view = run.api("/api/tool-update", "aktualizacja-najnowsza")
        run.check(view == {"state": "up_to_date"}, "the server reports the newest version")
        run.check(_head(clone) == newest, "the clone stays on the newest commit")
        run.check(
            _update_entries(run)[-1] == f"aktualizacja-koniec wynik=AKTUALNA przed={newest} po={newest} biblioteki=nie",
            "the Centrum log has the update that changed nothing",
        )
        run.capture(page, "96-aktualizacja-najnowsza")

        _drive_failed_installation(run, page, clone, origin, newest, libraries, dad_files, run_configuration)
        try:
            _drive_new_version_not_starting(run, page, origin, tool["not_starting"], run_configuration)
            _drive_start_from_shortcut(run, page)
            _drive_ok_on_old_version(run, page, tool["not_starting"])
        finally:
            remove(restart_pacing, missing_ok=True)
        # Later features (pomiar-u-taty) expect Ustawienia without an alert: one more click on the restored
        # Wydanie replaces the failed installation with `Masz najnowszą wersję.`, which the last reload drops.
        print("  harness: the newest Wydanie in the local origin is the newest commit again", flush=True)
        release_only(origin, newest)
        _github_dormant_release(run)
        page.reload()
        card = settings_section(page)
        expect(card).to_contain_text("Jest nowsza wersja")
        card.get_by_role("button", name=UPDATE_BUTTON, exact=True).click()
        expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_be_visible(timeout=Budget.SLOWED.ms)
        expect(card.get_by_role("alert")).to_have_count(0)
        run.check(_head(clone) == newest, "after the failed installation the tool is up to date on the newest commit")
        _github_main(run, newest)
        with page.expect_response(lambda response: response.url.endswith("/api/tool-update")):
            page.reload()
        expect(card).to_contain_text("Aktualna")
        expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_have_count(0)
        expect(page.get_by_role("alert")).to_have_count(0)
        run.check(True, "with GitHub's newest Wydanie on the tool's commit, Ustawienia show it current, with no button and no alert")
        expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_have_count(0)
        run.check(True, f"the card no longer says „{UP_TO_DATE}”")
        run.check(
            run.api("/api/tool-update", "aktualizacja-znowu-aktualna") == {"state": "idle"},
            "with GitHub's newest Wydanie on the tool's commit, the server forgets the result about the other Wydanie",
        )
    finally:
        remove(main_commit, missing_ok=True)
        remove(Pace.INSTALL.file(run.root), missing_ok=True)
        release_only(origin, newest)


def _drive_failed_installation(
    run: Run,
    page: Page,
    clone: Path,
    origin: Path,
    newest: str,
    libraries: str,
    dad_files: dict[str, str],
    run_configuration: dict[str, bytes],
) -> None:
    run.step(FEATURE, "aktualizacja-instalowanie")
    print("  harness: the newest Wydanie in the local origin and on the scripted GitHub needs a library pip cannot install offline", flush=True)
    release_only(origin, libraries)
    _github_main(run, libraries)
    print(f"  harness: each installation of libraries waits {PACING_MS} ms before pip starts", flush=True)
    installation_pacing = Pace.INSTALL.set(run.root, PACING_MS)
    page.reload()
    card = settings_section(page)
    expect(card).to_contain_text("Jest nowsza wersja")
    run.check(
        run.api("/api/tool-update", "aktualizacja-instalowanie-przed") == {"state": "idle"},
        "with a newer Wydanie than the one the last update was up to date with, the server forgets that result",
    )
    expect(card.get_by_role("status").filter(has_text=UP_TO_DATE)).to_have_count(0)
    card.get_by_role("button", name=UPDATE_BUTTON, exact=True).click()
    expect(card.get_by_role("status").filter(has_text=INSTALLING)).to_be_visible()
    expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_disabled()
    view = run.api("/api/tool-update", "aktualizacja-instalowanie")
    run.check(view == {"state": "running", "step": "installing"}, "the server reports the step `installing`")
    run.capture(page, "130-aktualizacja-instalowanie", live=True)
    remove(installation_pacing)

    run.step(FEATURE, "aktualizacja-instalacja-nieudana")
    message = card.get_by_role("alert").filter(has_text=LIBRARIES_FAILED)
    expect(message).to_be_visible(timeout=Budget.SLOWED.ms)
    expect(message).to_contain_text("Narzędzie działa dalej w poprzedniej wersji.")
    expect(card).to_contain_text(newest[:7])
    expect(card).to_contain_text("Jest nowsza wersja")
    expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_enabled()
    view = run.api("/api/tool-update", "aktualizacja-instalacja-nieudana")
    run.check(
        (view["state"], view["message"], view["next_action"])
        == (
            "failed",
            {
                "what": LIBRARIES_FAILED,
                "where": "narzędzie na tym komputerze",
                "action": (
                    "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                    "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
                ),
            },
            "retry",
        ),
        "the server reports the three-part Komunikat of the failed installation, to be tried again",
    )
    run.check(_head(clone) == newest, "the clone is back on the commit before the click")
    run.check(not (clone / "requirements.txt").exists(), "the new version's requirements left with it")
    run.check(_git(clone, "status", "--porcelain", "--untracked-files=no") == "", "the clone has no changes left")
    _dad_files_kept(run, clone, dad_files, run_configuration)
    run.check(
        _update_entries(run)[-1]
        == f"aktualizacja-koniec wynik=INSTALACJA_BIBLIOTEK przed={newest} po={libraries} biblioteki=tak",
        "the Centrum log has the failed installation with both commits, and no path or pip output",
    )
    run.capture(page, "131-aktualizacja-instalacja-nieudana")


def _drive_new_version_not_starting(
    run: Run, page: Page, origin: Path, not_starting: str, run_configuration: dict[str, bytes]
) -> None:
    tool = run.fixture["tool"]
    clone, newest, dad_files = Path(tool["clone"]), tool["newest"], tool["dad_files"]
    run.step(FEATURE, "aktualizacja-nie-wystartowala-ponowny-start")
    print("  harness: the newest Wydanie in the local origin and on the scripted GitHub is a version whose Centrum does not start", flush=True)
    release_only(origin, not_starting)
    _github_main(run, not_starting)
    print(f"  harness: the old version, started again, waits {RESTART_PACING_MS} ms before it starts", flush=True)
    restart_pacing = Pace.RESTART.set(run.root, RESTART_PACING_MS)
    page.reload()
    card = settings_section(page)
    expect(card).to_contain_text("Jest nowsza wersja")
    before_health = run.api("/api/health", "aktualizacja-nie-wystartowala-health-przed")
    page.evaluate("window.przedPonownymStartem = true")
    card.get_by_role("button", name=UPDATE_BUTTON, exact=True).click()
    expect(_status(page, RESTARTING)).to_be_visible(timeout=Budget.SLOWED.ms)
    expect(card.get_by_role("button", name=UPDATE_BUTTON, exact=True)).to_be_disabled()
    until(lambda: not answers(run.url), "the old Centrum has closed, and no Centrum answers yet")
    _entered(_status(page, RESTARTING))
    run.capture(page, "135-aktualizacja-nie-wystartowala-ponowny-start", live=True)
    print("  Dad closes Ustawienia and goes to Uruchomienia while Centrum restarts", flush=True)
    close_settings(page)
    page.get_by_role("link", name="Uruchomienia", exact=True).click()
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    remove(restart_pacing)

    run.step(FEATURE, "aktualizacja-nie-wystartowala")
    message = page.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)
    expect(message).to_be_visible(timeout=Budget.BACKGROUND.ms)
    run.check(page.evaluate("window.przedPonownymStartem === undefined"), "the tab reloaded by itself")
    expect(page.get_by_role("heading", name="Uruchomienia", exact=True)).to_be_visible()
    run.check(True, "the tab reloaded on Uruchomienia, a page with no button of its own, and shows the Komunikat there")
    message = page.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)
    expect(message).to_contain_text("narzędzie na tym komputerze")
    expect(message).to_contain_text(TO_MAKS)
    report = page.get_by_role("button", name=REPORT_BUTTON, exact=True)
    expect(report).to_be_visible()
    run.check("bg-primary" in (report.get_attribute("class") or ""), "`Wyślij do Maksa` is the main action")
    expect(page.get_by_role("region", name="Notifications").get_by_role("dialog", name=UPDATED)).to_have_count(0)
    health = run.api("/api/health", "aktualizacja-nie-wystartowala-health-po")
    run.check(
        health["commit"] == newest[:7] and health["instance"] != before_health["instance"],
        "a new Centrum answers on the same address, in the old version",
    )
    view = run.api("/api/tool-update", "aktualizacja-nie-wystartowala")
    run.check(
        (view["state"], view["message"], view["next_action"])
        == ("failed", {"what": NEW_VERSION_FAILED, "where": "narzędzie na tym komputerze", "action": TO_MAKS}, "report"),
        "the old version reports the Komunikat in three parts and a Zgłoszenie to Maks",
    )
    run.check(_head(clone) == newest, "the guardian moved the clone back to the commit before the click")
    run.check(_git(clone, "status", "--porcelain", "--untracked-files=no") == "", "the clone has no changes left")
    _dad_files_kept(run, clone, dad_files, run_configuration)
    run.check(not (run.config / RESULT_FILE).exists(), "the old version read the result once")
    run.check(
        _update_entries(run)[-2:]
        == [
            f"aktualizacja-start przed={newest}",
            f"aktualizacja-koniec wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={newest} po={not_starting} biblioteki=nie",
        ],
        "the Centrum log has the update and its end in the old version, with both commits and no path",
    )
    run.check(
        _since_update(run) == ["zamkniecie", "stop", "aktualizacja-koniec", "start"],
        "the Centrum before the click logged its stop; only the old version started again, the new one never logged a start",
    )
    run.capture(page, "136-aktualizacja-nie-wystartowala")

    open_settings(page, "Narzędzie")
    card = settings_section(page)
    expect(card).to_contain_text(newest[:7])
    expect(card).to_contain_text("Jest nowsza wersja")
    expect(card.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)).to_have_count(1)
    run.check(True, "in Ustawienia the same Komunikat stands once, in the section Narzędzie, with the old version")
    run.capture(page, "137-aktualizacja-nie-wystartowala-konfiguracja")


def _drive_start_from_shortcut(run: Run, page: Page) -> None:
    run.step(FEATURE, "aktualizacja-start-ze-skrotu")
    print("  Dad closed the browser while Centrum restarted and starts it from the shortcut: a new tab", flush=True)
    tab = page.context.new_page()
    try:
        tab.goto(run.url)
        expect(tab.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
        message = tab.get_by_role("alert").filter(has_text=NEW_VERSION_FAILED)
        expect(message).to_have_count(1)
        expect(message).to_contain_text(TO_MAKS)
        report = tab.get_by_role("button", name=REPORT_BUTTON, exact=True)
        expect(report).to_be_visible()
        run.check("bg-primary" in (report.get_attribute("class") or ""), "`Wyślij do Maksa` is the main action")
        run.check(True, "a tab the restart did not reload shows the Komunikat under the title of Okresy, where Dad lands")
        run.capture(tab, "132-aktualizacja-start-ze-skrotu")
    finally:
        tab.close()


def _drive_ok_on_old_version(run: Run, page: Page, not_starting: str) -> None:
    tool = run.fixture["tool"]
    clone, newest = Path(tool["clone"]), tool["newest"]
    result = run.config / UPDATE_RESULT_FILE
    run.step(FEATURE, "aktualizacja-ok-przy-starej-wersji")
    print(f"  harness: the old version, started again, waits {OK_ON_OLD_VERSION_PACING_MS} ms before it starts", flush=True)
    restart_pacing = Pace.RESTART.set(run.root, OK_ON_OLD_VERSION_PACING_MS)
    page.reload()
    card = settings_section(page)
    expect(card).to_contain_text("Jest nowsza wersja")
    page.evaluate("window.przedPonownymStartem = true")
    card.get_by_role("button", name=UPDATE_BUTTON, exact=True).click()
    expect(_status(page, RESTARTING)).to_be_visible(timeout=Budget.SLOWED.ms)
    until(
        lambda: result.exists() and read_json(result)["wynik"] == "NOWA_WERSJA_NIE_WYSTARTOWALA",
        "the guardian moved the clone back and wrote the failure",
        Budget.SLOWED,
    )
    print(
        "  harness: the disk refused the guardian both the removal of „ok” and the write of the failure, so „ok” stays",
        flush=True,
    )
    result.write_text(
        json.dumps({"wynik": "ok", "przed": newest, "po": not_starting, "biblioteki": False}) + "\n", encoding="utf-8"
    )
    run.check(not answers(run.url), "the harness put „ok” back before the old version started")
    remove(restart_pacing)

    message = settings_section(page).get_by_role("alert").filter(has_text=UNEXPECTED)
    expect(message).to_be_visible(timeout=Budget.BACKGROUND.ms)
    run.check(page.evaluate("window.przedPonownymStartem === undefined"), "the tab reloaded by itself")
    expect(settings_title(page)).to_have_text("Ustawienia/Narzędzie")
    expect(message).to_contain_text("narzędzie na tym komputerze")
    expect(message).to_contain_text(
        "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
        "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
    )
    expect(settings_section(page).get_by_role("button", name=REPORT_BUTTON, exact=True)).to_be_visible()
    expect(page.get_by_role("region", name="Notifications").get_by_role("dialog", name=UPDATED)).to_have_count(0)
    card = settings_section(page)
    expect(card).to_contain_text(newest[:7])
    expect(card).to_contain_text("Jest nowsza wersja")
    run.check(True, "the section Narzędzie shows the failure, no `Zaktualizowano`, and the old version")
    view = run.api("/api/tool-update", "aktualizacja-ok-przy-starej-wersji")
    run.check(
        (view["state"], view["message"], view["next_action"])
        == (
            "failed",
            {
                "what": UNEXPECTED,
                "where": "narzędzie na tym komputerze",
                "action": (
                    "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                    "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
                ),
            },
            "retry",
        ),
        "„ok” read by the old version is the unexpected failure, to be tried again",
    )
    run.check(run.api("/api/health", "aktualizacja-ok-przy-starej-wersji-health")["commit"] == newest[:7], "the old version runs")
    run.check(_head(clone) == newest, "the clone stands on the commit before the click")
    run.check(not result.exists(), "the old version read the result once")
    run.check(
        _update_entries(run)[-2:]
        == [
            f"aktualizacja-start przed={newest}",
            f"aktualizacja-koniec wynik=NIEOCZEKIWANY_BLAD przed={newest} po={not_starting} biblioteki=nie",
        ],
        "the Centrum log has the update's end as the unexpected failure, with both commits",
    )
    run.capture(page, "138-aktualizacja-ok-przy-starej-wersji")
