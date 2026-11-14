"""Drive features/diagnoza.md."""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import Page, expect

from drive.common import (
    Run,
    current_run,
    diagnosis_answer,
    drop_report_key,
    ensure_files_set,
    finished_result,
    move,
    open_setup,
    period_choice,
    queued,
    queued_posts,
    read_bytes,
    read_json,
    remove,
    run_again,
    stop_banner,
    unreadable,
)
from drive.waiting import until
from harness import File, Log, Switch
from drive.teksty import FILES_UNCHANGED, FOR_KEY, NOT_FOUND, PROPOSAL, TEMPLATE_MISSING, UPDATE_BUTTON
from atrapy.scenariusz_centrum import PERIOD_WITHOUT_FILES, ROW_MARKER
from atrapy.pliki_taty import REPORT_KEY_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from atrapy.workbooks import excel_lock

FEATURE = "diagnoza"
# A period without a Folder okresu that no feature prepares; the Rejestr zleceń has no orders in it, so no
# Uruchomienie of this feature writes a file.
PERIOD = PERIOD_WITHOUT_FILES
REGISTER_OPEN = "Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku."
NO_ORDERS = "W Rejestrze zleceń nie ma żadnego zlecenia z tego okresu."
# The Diagnoza check of a bad Lista Wykonawców and the start refusal on one the system refuses to read.
WORKER_LIST_BAD = "Lista Wykonawców ma złe ustawienie."
WORKER_LIST_UNREADABLE = (
    "Nie można teraz odczytać Listy Wykonawców. Zamknij program, który może trzymać plik, i spróbuj ponownie."
)
CONFIRMS = "Diagnoza potwierdza ten komunikat."
NOT_DAD_FILES = "To nie wynika z Twoich plików."
NOT_CHECKED_UNEXPECTED = "Nie udało się sprawdzić: nieoczekiwany błąd."
# The Centrum log entry of a check that failed itself: the exception type and the check, never its text.
UNEXPECTED_IN_DIAGNOSIS = 'nieoczekiwany-wyjatek typ=RuntimeError miejsce="Diagnoza: Rejestr zleceń"'
UNEXPECTED_CODE = "BLAD_NIEOCZEKIWANY"
KEY_CHECK = "Token do Zgłoszeń"
NO_KEY = "Na tym komputerze nie ma Tokenu do Zgłoszeń. Zgłoszenie poczeka, aż Maks go wpisze."
KEY_REFUSED = "Skrzynka Zgłoszeń odrzuca Token do Zgłoszeń. Zgłoszenie poczeka, aż Maks go wymieni."
# A key of its own: the skrzynka refuses it here, and Centrum remembers that refusal per key for a quarter of an hour.
REFUSED_KEY = "github_pat_VERIFY_DIAGNOZA_ODRZUCONY"
OTHER_MAIN = "e" * 40
CHECKS = (
    "Ustawienia Centrum",
    "Pliki w OneDrive",
    "Rejestr zleceń",
    "Wzorzec rozliczenia wewnętrznego",
    "Wzorzec pliku zbiorczego",
    "Lista Wykonawców",
    "Folder okresu",
    "Pliki okresu w Excelu",
    "Aktualność narzędzia",
    KEY_CHECK,
    "Dziennik Centrum rozliczeń",
)


def _snapshot(paths: list[Path]) -> list[tuple[bytes, int]]:
    return [(read_bytes(path), path.stat().st_mtime_ns) for path in paths]


def drive(run: Run, page: Page) -> None:
    register = Path(run.fixture["order_register"])
    configuration = run.fixture["configuration"]
    assert isinstance(configuration, dict)
    internal_template = Path(configuration["internal_template"])
    untouched = [register, *(Path(configuration[key]) for key in ("internal_template", "collective_template"))]
    before = _snapshot(untouched)
    lock = excel_lock(register)
    diagnosis = page.get_by_role("region", name="Diagnoza")
    proposal = diagnosis.get_by_role("note", name="Propozycja aktualizacji")
    main_commit = File.MAIN_COMMIT.file(run.root)

    run.step(FEATURE, "diagnoza-dla-taty")
    page.goto(run.url)
    ensure_files_set(run, page)
    lock.touch()
    open_setup(run, page, "Przygotowanie pliku zbiorczego", "diagnoza", period=(PERIOD, "Brak plików okresu"))
    page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
    expect(stop_banner(page)).to_contain_text(REGISTER_OPEN)
    result = finished_result(run, "diagnoza-dla-taty")
    run.check(
        (result["stop_kind"], result["headline"], result["files_unchanged"], result["opens"])
        == ("for_tata", "Do poprawy", True, "order_register"),
        "a stop Dad fixes himself is „dla taty”, to fix in the Rejestr zleceń, with his files unchanged",
    )
    for_tata = page.get_by_role("region", name="Podgląd na żywo").get_by_label("Zatrzymanie do poprawy", exact=True)
    expect(for_tata).to_contain_text("Do poprawy")
    expect(for_tata).to_contain_text(FILES_UNCHANGED)
    expect(for_tata).not_to_contain_text(NOT_DAD_FILES)
    run.check(
        "text-destructive" not in (for_tata.get_attribute("class") or ""),
        "the stop Dad fixes himself is yellow, not a red error",
    )
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Diagnoza", exact=True)).to_have_count(0)
    run.check(True, "the stop offers Uruchom ponownie and no Diagnoza")
    run.capture(page, "50-diagnoza-dla-taty")
    opened_before = len(run.lines(Log.OPENED))
    for_tata.get_by_role("button", name="Otwórz Rejestr zleceń", exact=True).click()
    until(
        lambda: run.lines(Log.OPENED)[opened_before:] == [{"path": str(register)}],
        "Otwórz Rejestr zleceń opens the Rejestr zleceń from Dad's settings",
    )

    run.step(FEATURE, "diagnoza-powtorka")
    repeated = run_again(run, stop_banner(page), "diagnoza-powtorka")
    run.check(repeated["stop_kind"] == "repeated", "the same Komunikat after Uruchom ponownie is a repetition")
    current = run.api("/api/runs/current", "diagnoza-powtorka")
    run_info = current["run"]
    assert isinstance(run_info, dict)
    run.check((run_info["period"], run_info["mode"]) == (PERIOD, "DRY-RUN"), "Uruchom ponownie kept the period and mode")
    expect(stop_banner(page).get_by_role("button", name="Diagnoza", exact=True)).to_be_visible()
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_have_count(0)
    run.check(True, "the repeated stop offers Diagnoza instead of Uruchom ponownie")
    run.capture(page, "51-diagnoza-powtorka")

    run.step(FEATURE, "diagnoza-wyjasnienie")
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis).to_contain_text(CONFIRMS)
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_have_count(0)
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(proposal).to_have_count(0)
    run.check(True, "the Diagnoza confirms the stop without repeating it and puts Uruchom ponownie on the banner")
    answer = diagnosis_answer(run, str(run_info["id"]), "diagnoza-wyjasnienie")
    explanation = answer["explanation"]
    assert isinstance(explanation, dict)
    run.check(
        explanation["what"] == REGISTER_OPEN and answer["next_action"] == "rerun" and answer["update_proposal"] is False,
        "the Diagnoza explains the cause Dad removes himself and offers Uruchom ponownie first; the tool is up to date",
    )
    run.capture(page, "52-diagnoza-wyjasnienie")

    run.step(FEATURE, "diagnoza-sprawdzono")
    diagnosis.get_by_role("button", name=f"Sprawdzono ({len(CHECKS)})", exact=True).click()
    checks = diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem")
    expect(checks).to_have_count(len(CHECKS))
    for index, label in enumerate(CHECKS):
        expect(checks.nth(index)).to_contain_text(label)
    shown = answer["checks"]
    assert isinstance(shown, list)
    states = {check["label"]: check["state"] for check in shown}
    run.check(
        [check["label"] for check in shown] == list(CHECKS)
        and (states["Pliki w OneDrive"], states["Rejestr zleceń"], states["Aktualność narzędzia"])
        == ("passed", "failed", "passed"),
        "every check is listed in order; the Rejestr zleceń failed",
    )
    run.check(lock.exists() and _snapshot(untouched) == before, "the Diagnoza changed no file and kept the lock file")
    run.capture(page, "53-diagnoza-sprawdzono")

    run.step(FEATURE, "diagnoza-inny-komunikat")
    remove(lock)
    result = run_again(run, stop_banner(page), "diagnoza-inny-komunikat")
    expect(stop_banner(page)).to_contain_text(NO_ORDERS)
    run.check(result["stop_kind"] == "for_tata", "a different Komunikat after the fix is not a repetition")
    expect(stop_banner(page).get_by_role("button", name="Uruchom ponownie", exact=True)).to_be_visible()
    expect(diagnosis).to_have_count(0)
    run.capture(page, "54-diagnoza-inny-komunikat")

    run.step(FEATURE, "diagnoza-do-maksa")
    aside = internal_template.with_name(f"{internal_template.name}.odlozony")
    move(internal_template, aside)
    result = run_again(run, stop_banner(page), "diagnoza-do-maksa")
    expect(stop_banner(page)).to_contain_text(TEMPLATE_MISSING)
    run.check(
        (result["stop_kind"], result["headline"], result["opens"]) == ("for_maks", "Błąd", None),
        "a stop that tells Dad to pass it on is „do Maksa”, an error",
    )
    for_maks = page.get_by_role("region", name="Podgląd na żywo").get_by_label("Zatrzymanie", exact=True)
    expect(for_maks).to_contain_text(NOT_DAD_FILES)
    expect(for_maks).to_contain_text(FILES_UNCHANGED)
    run.check(
        "text-destructive" in (for_maks.get_attribute("class") or ""),
        "the stop „do Maksa” stays red and says it does not come from Dad's files",
    )
    expect(stop_banner(page).get_by_role("button", name="Diagnoza", exact=True)).to_be_visible()
    run.capture(page, "55-diagnoza-do-maksa")
    main_commit.parent.mkdir(exist_ok=True)
    main_commit.write_text(OTHER_MAIN, encoding="utf-8")  # `main` moved on, as it does several times a day
    try:
        stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
        expect(diagnosis).to_contain_text(CONFIRMS)
        expect(proposal).to_contain_text(PROPOSAL)
        expect(page.get_by_role("button", name="Uruchom ponownie", exact=True)).to_have_count(0)
        run.check(True, "a cause only Maks removes has no Uruchom ponownie; the newer version is only a quiet proposal")
        update = proposal.get_by_role("button", name=UPDATE_BUTTON, exact=True)
        expect(update).to_be_enabled()
        send = diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)
        run.check(
            "bg-primary" not in (update.get_attribute("class") or "")
            and "bg-primary" in (send.get_attribute("class") or ""),
            "the proposal holds `Zaktualizuj narzędzie` as a second action; `Wyślij do Maksa` stays the main one",
        )
        current = run.api("/api/runs/current", "diagnoza-do-maksa")
        run_info = current["run"]
        assert isinstance(run_info, dict)
        answer = diagnosis_answer(run, str(run_info["id"]), "diagnoza-do-maksa-wyjasnienie")
        explanation = answer["explanation"]
        assert isinstance(explanation, dict)
        run.check(
            explanation["what"].startswith(TEMPLATE_MISSING)
            and (answer["confirms_stop"], answer["next_action"], answer["update_proposal"]) == (True, "report", True),
            "a newer version does not cover the missing Wzorzec: the Diagnoza explains it and proposes the update",
        )
        run.capture(page, "56-diagnoza-do-maksa-wyjasnienie")
    finally:
        remove(main_commit)

    run.step(FEATURE, "diagnoza-bez-przyczyny")
    move(aside, internal_template)
    page.reload()
    stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
    expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text("Wyślij do Maksa.")
    current = run.api("/api/runs/current", "diagnoza-bez-przyczyny")
    run_info = current["run"]
    assert isinstance(run_info, dict)
    answer = diagnosis_answer(run, str(run_info["id"]), "diagnoza-bez-przyczyny")
    results = answer["checks"]
    assert isinstance(results, list)
    states = {check["label"]: check["state"] for check in results}
    run.check(
        answer["next_action"] == "report"
        and states.pop(KEY_CHECK) == "failed"
        and set(states.values()) == {"passed"},
        "with every check of the files passing the Diagnoza finds no cause; the missing key failed but is no cause",
    )
    key_item = diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem").filter(has_text=KEY_CHECK)
    diagnosis.get_by_role("button", name=f"Sprawdzono ({len(CHECKS)})", exact=True).click()
    expect(key_item).to_contain_text(f"{KEY_CHECK} · {NO_KEY}")
    run.check(_snapshot(untouched) == before, "the Rejestr zleceń and the Wzorce are unchanged")
    log = run.log()
    run.check(
        f"diagnoza proces=preparation okres={PERIOD} przyczyna=NIE_ZNALEZIONO_PRZYCZYNY" in log,
        "the Centrum log records each Diagnoza with its cause code only",
    )
    run.capture(page, "57-diagnoza-bez-przyczyny")

    run.step(FEATURE, "diagnoza-w-logach")
    run_id = str(run_info["id"])
    [logs] = run.run_logs_dir.glob(f"*-{run_id}.json")
    data = read_bytes(logs)  # bytes: reading text hides the \r\n of a text-mode write on Windows
    logged = json.loads(data)["diagnosis"]
    run.check(
        logged["explanation"]["code"] == "NIE_ZNALEZIONO_PRZYCZYNY"
        and [{part: check[part] for part in ("label", "state", "detail")} for check in logged["checks"]] == results,
        "the file of Logi of this Uruchomienie holds its last Diagnoza: the cause code and every check as Dad sees it",
    )
    logs_queued = queued(run, "logi-uruchomienia", run_id)
    first, newest = (read_json(path) for path in (logs_queued[0], logs_queued[-1]))
    [comment] = newest["parts"]
    run.check(
        len(logs_queued) >= 2
        and (newest["target"], newest["run_id"]) == (first["target"], first["run_id"])
        and "\n- Diagnoza: " in comment
        and (newest["archive"]["name"], newest["archive"]["text"].encode("utf-8")) == (logs.name, data),
        "without a key the Logi with this Diagnoza wait in the queue as a new version of the one comment of the "
        "Uruchomienie, and their file for the Archiwum Logów okresu, in UTF-8 as the queue packs it, is the file byte "
        "for byte",
    )

    run.step(FEATURE, "diagnoza-nieoczekiwany-wyjatek")
    fault = Switch.REGISTER_FAULT.on(run.root)
    try:
        page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
        page.get_by_role("radio", name="Przygotowanie pliku zbiorczego").click()
        page.get_by_role("combobox", name="Okres").click()
        page.get_by_role("option", name=period_choice(PERIOD, "Brak plików okresu"), exact=True).click()
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        # The automatic Diagnoza runs while the fault is still there, so reading the Rejestr zleceń fails in it too.
        expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
        result = finished_result(run, "diagnoza-nieoczekiwany-wyjatek")
        run.check(
            (result["ending"], result["diagnosis"]) == ("unexpected", "automatic"),
            "a nieoczekiwany wyjątek is „do Maksa” and its Diagnoza starts by itself",
        )
        expect(diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True)).to_be_visible()
        expect(diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True)).to_be_visible()
        expect(stop_banner(page).get_by_role("button", name="Diagnoza", exact=True)).to_have_count(0)
        run.check(True, "without a click Dad sees the Diagnoza, Wyślij do Maksa and the preview of the Zgłoszenie")
        diagnosis.get_by_role("button", name=f"Sprawdzono ({len(CHECKS)})", exact=True).click()
        checks = diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem")
        expect(checks).to_have_count(len(CHECKS))
        register_check = checks.nth(CHECKS.index("Rejestr zleceń"))
        expect(register_check).to_contain_text(f"Rejestr zleceń · {NOT_CHECKED_UNEXPECTED}")
        expect(register_check.get_by_label("nie sprawdzono")).to_be_visible()
        run.check(True, "the same failure in the Diagnoza leaves only the Rejestr zleceń unchecked; every check is listed")
        log = run.log()
        run.check(
            UNEXPECTED_IN_DIAGNOSIS in log and "synthetic unexpected failure" not in log,
            "the Centrum log names the exception type and the check, never the text of the exception",
        )
        diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
        shown = page.get_by_role("figure", name="Treść Zgłoszenia")
        title, body = shown.locator("figcaption").inner_text(), shown.locator("pre").inner_text()
        run.check(
            title.startswith(f"{UNEXPECTED_CODE}: ")
            and UNEXPECTED_IN_DIAGNOSIS in body
            and "synthetic unexpected failure" not in body
            and ROW_MARKER not in body,
            "the Zgłoszenie carries that log entry for Maks, without the exception text or a workbook row",
        )
        run.capture(page, "58-diagnoza-nieoczekiwany-wyjatek")

        run.step(FEATURE, "diagnoza-bez-powtorki")
        unexpected = current_run(run, "diagnoza-bez-powtorki")["run"]
        assert isinstance(unexpected, dict)
        its_logs = queued(run, "logi-uruchomienia", str(unexpected["id"]))
        diagnosed = f" diagnoza proces=preparation okres={PERIOD} "
        diagnoses = run.log().count(diagnosed)
        page.reload()
        expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
        page.get_by_role("link", name="Okresy", exact=True).click()
        expect(page.get_by_role("heading", name="Okresy", exact=True)).to_be_visible()
        page.get_by_role("link", name="Uruchomienia", exact=True).click()
        expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
        until(
            lambda: run.log().count(diagnosed) == diagnoses + 2,
            "a reload and Okresy → Uruchomienia each start the automatic Diagnoza again",
        )
        run.check(
            len(its_logs) == 2 and queued(run, "logi-uruchomienia", str(unexpected["id"])) == its_logs,
            "the same result queues no more Logi: one version for the Uruchomienie and one for its first Diagnoza",
        )
        diagnosis.get_by_role("button", name="Co zostanie wysłane", exact=True).click()
        title, body = shown.locator("figcaption").inner_text(), shown.locator("pre").inner_text()
    finally:
        remove(fault)

    run.step(FEATURE, "diagnoza-nieoczekiwany-wyjatek-zgloszenie")
    config = run.config
    key_file = config / REPORT_KEY_FILE
    drop_report_key(key_file, missing_ok=True)  # no key before features/zgloszenie.md
    diagnosis.get_by_role("button", name="Wyślij do Maksa", exact=True).click()
    expect(diagnosis.get_by_role("status").filter(has_text=FOR_KEY)).to_be_visible()
    [queued_report] = [post for post in queued_posts(run, "zgloszenie") if post["target"]["title"] == title]
    run.check(
        "".join(queued_report["parts"]) == body,
        "Wyślij do Maksa works after the nieoczekiwany wyjątek: without a key the preview waits in the queue",
    )
    report = finished_result(run, "diagnoza-nieoczekiwany-wyjatek-zgloszenie")["report"]
    run.check(
        report == {"state": "queued", "waits_for": "key"}, "the server keeps the queued Zgłoszenie in the result"
    )
    run.capture(page, "59-diagnoza-nieoczekiwany-wyjatek-zgloszenie")

    run.step(FEATURE, "diagnoza-klucz-odrzucony")
    print("  harness: Maks writes a key the skrzynka refuses (an expired token)", flush=True)
    refusing = Switch.KEY_REFUSED.on(run.root)
    key_file.write_text(REFUSED_KEY + "\n", encoding="utf-8")
    try:
        page.reload()
        expect(diagnosis.get_by_label("Wyjaśnienie Diagnozy")).to_contain_text(NOT_FOUND)
        diagnosis.get_by_role("button", name=f"Sprawdzono ({len(CHECKS)})", exact=True).click()
        key_item = diagnosis.get_by_role("list", name="Sprawdzono").get_by_role("listitem").filter(has_text=KEY_CHECK)
        expect(key_item).to_contain_text(f"{KEY_CHECK} · {KEY_REFUSED}")
        expect(key_item.get_by_label("nie przeszło")).to_be_visible()
        unexpected_run = current_run(run, "diagnoza-klucz-odrzucony")["run"]
        assert isinstance(unexpected_run, dict)
        answer = diagnosis_answer(run, str(unexpected_run["id"]), "diagnoza-klucz-odrzucony")
        explanation = answer["explanation"]
        assert isinstance(explanation, dict) and isinstance(answer["checks"], list)
        run.check(
            explanation["what"] == NOT_FOUND
            and {"label": KEY_CHECK, "state": "failed", "detail": KEY_REFUSED} in answer["checks"],
            "a refused key is a failed check of the Diagnoza, never its explanation",
        )
        run.capture(page, "59b-diagnoza-klucz-odrzucony")
    finally:
        remove(refusing)
        drop_report_key(key_file)

    run.step(FEATURE, "diagnoza-lista-wykonawcow")
    worker_list = internal_template.parent / WORKERS_FILE
    kept = worker_list.with_name(f"{worker_list.name}.odlozony")
    move(worker_list, kept)
    worker_list.write_bytes(b"\xff\xfe nie UTF-8")
    try:
        page.get_by_role("button", name="Nowe Uruchomienie procesu").click()
        page.get_by_role("radio", name="Przygotowanie pliku zbiorczego").click()
        page.get_by_role("combobox", name="Okres").click()
        page.get_by_role("option", name=period_choice(PERIOD, "Brak plików okresu"), exact=True).click()
        page.get_by_role("button", name="Podgląd bez zapisu", exact=True).click()
        expect(stop_banner(page)).to_contain_text(NO_ORDERS)
        result = finished_result(run, "diagnoza-lista-wykonawcow")
        run.check(
            all(WORKER_LIST_BAD not in stop["what"] for stop in result["stops"]),
            "a Lista Wykonawców Przygotowanie cannot use runs on the last good list: the stop is the period's, not the list's",
        )
        # A stop for tata offers `Diagnoza` only when Uruchom ponownie repeats the same Komunikat.
        run_again(run, stop_banner(page), "diagnoza-lista-wykonawcow")
        stop_banner(page).get_by_role("button", name="Diagnoza", exact=True).click()
        list_run = current_run(run, "diagnoza-lista-wykonawcow")["run"]
        assert isinstance(list_run, dict)
        answer = diagnosis_answer(run, str(list_run["id"]), "diagnoza-lista-wykonawcow")
        assert isinstance(answer["checks"], list)
        run.check(
            any(
                check["label"] == "Lista Wykonawców" and check["state"] == "failed" and WORKER_LIST_BAD in check["detail"]
                for check in answer["checks"]
            ),
            "the Diagnoza check of the Lista Wykonawców names the bad setting, so tata knows what to fix in Ustawienia",
        )
        run.capture(page, "59c-diagnoza-lista-wykonawcow")
    finally:
        remove(worker_list)
        move(kept, worker_list)

    run.step(FEATURE, "diagnoza-lista-wykonawcow-niedostepna")
    with unreadable(worker_list):
        refused = run.post(
            "/api/runs",
            "diagnoza-lista-wykonawcow-niedostepna",
            {"process": "preparation", "period": PERIOD, "mode": "DRY-RUN"},
        )
        run.check(
            refused.status == 409 and isinstance(refused.body, dict) and refused.body.get("message") == WORKER_LIST_UNREADABLE,
            "a Lista Wykonawców the system refuses to read refuses the start with a sentence, never „niepoprawna”",
        )
