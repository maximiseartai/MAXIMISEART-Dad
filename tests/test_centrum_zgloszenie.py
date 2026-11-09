"""Zgłoszenie do Maksa z Centrum rozliczeń przez HTTP API, z fałszywą skrzynką Zgłoszeń."""

from __future__ import annotations

import codecs
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
import json
import re
import shutil
import threading
from pathlib import Path
from typing import Any, NoReturn

import pytest

from rozliczenia.centrum.clock import ALARM_THREAD
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE
from rozliczenia.centrum.keyed_box import KEY_CHECK_THREAD
from rozliczenia.centrum.outbox import RETRY_S
from rozliczenia.centrum.report_box import Refused, Unreachable
from rozliczenia.centrum.reports import REPORT_THREAD, SEARCH_DEADLINE_S

from tests.fixtures.centrum import (
    REPORT_KEY,
    TOOL_COMMIT,
    CentrumClient,
    FakeGitHub,
    FakeReportBox,
    ToolDirectory,
    case_states,
    centrum as plain_centrum,
    centrum_app,
    dad_cases,
    join_threads_since,
    write_report_key,
)
from tests.fixtures.centrum_intermax import ordering_centrum
from tests.fixtures.linie_watkow import new_line
from tests.fixtures.locked_file import lock_file
from tests.fixtures.centrum_processes import (
    on_register_read,
    PreparingCentrum,
    SettlingCentrum,
    Surroundings,
    preparing_centrum,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from tests.fixtures.potomne import wait_for, wait_for_value
from atrapy.preparation import PERIOD
from atrapy.settlement import write_quantity_source


def diagnose(centrum: PreparingCentrum | SettlingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert response.status_code == 200, response.json()
    diagnosis: dict[str, Any] = response.json()
    return diagnosis


def send(centrum: PreparingCentrum | SettlingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/report")
    assert response.status_code == 200, response.json()
    state: dict[str, Any] = response.json()
    return state


def test_wyslane_zgloszenie_jest_dokladnie_podgladem_z_diagnozy(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)
    preview = diagnose(centrum, run_id)["report"]

    state = send(centrum, run_id)

    assert state == {"state": "sent"}
    [report] = centrum.surroundings.report_box.sent
    assert {"title": report.title, "body": report.body} == preview
    assert centrum.surroundings.report_box.keys == [REPORT_KEY]
    assert f"skrzynka-wyslano etykieta=zgloszenie okres={PERIOD} numer=1" in centrum.log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "content",
    [
        codecs.BOM_UTF8 + (REPORT_KEY + "\r\n").encode("utf-8"),  # Notatnik, PowerShell 5.1: Set-Content -Encoding UTF8
        codecs.BOM_UTF16_LE + (REPORT_KEY + "\r\n").encode("utf-16-le"),  # PowerShell 5.1: > albo Out-File
        codecs.BOM_UTF16_BE + (REPORT_KEY + "\r\n").encode("utf-16-be"),  # Notatnik: UTF-16 BE
    ],
    ids=["utf-8-bom", "utf-16-le", "utf-16-be"],
)
def test_klucz_zapisany_z_bom_wysyla_zgloszenie(tmp_path: Path, content: bytes) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool).write_bytes(content)
    run_id = stopped_for_maks(centrum)
    diagnose(centrum, run_id)

    assert send(centrum, run_id) == {"state": "sent"}
    assert centrum.surroundings.report_box.keys == [REPORT_KEY]


def test_zgloszenie_ma_komunikat_uruchomienie_narzedzie_diagnoze_i_dziennik(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    report = diagnosis["report"]
    assert report["title"] == "BRAK_WZORCA: Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku."
    body = report["body"]
    stop = stopped["result"]["stops"][0]
    for line in (
        "| Wzorzec rozliczenia wewnętrznego | przeszło | Wzorzec rozliczenia wewnętrznego.xlsx przechodzi Sprawdzanie. |",
        f"| Wzorzec pliku zbiorczego | nie przeszło | {stop['what']} |",
        "| Folder okresu | przeszło | Folderu 08_14_09_2026 jeszcze nie ma. |",
    ):
        assert line in body.splitlines()
    fingerprint = re.search(r"^- Odcisk problemu: ([0-9a-f]{16})$", body, re.MULTILINE)
    assert fingerprint is not None
    log_lines = centrum.log_path.read_text(encoding="utf-8").splitlines()
    diagnosed = next(index for index, line in enumerate(log_lines) if line.split(" ", 2)[1] == "diagnoza")
    results = {"passed": "przeszło", "failed": "nie przeszło", "not_checked": "nie sprawdzono"}
    assert body.splitlines() == [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        "- Kod: BRAK_WZORCA",
        f"- Co się stało: {stop['what']}",
        f"- Gdzie: {stop['where']}",
        f"- Co zrobić: {stop['action']}",
        "",
        "## Uruchomienie procesu",
        "",
        "- Proces: Przygotowanie pliku zbiorczego",
        f"- Okres: {PERIOD}",
        "- Tryb: DRY-RUN",
        f"- Logi: jeszcze niewysłane, Uruchomienie {stopped['run']['id']}",
        "",
        "## Narzędzie",
        "",
        f"- Commit: {TOOL_COMMIT}",
        f"- Odcisk problemu: {fingerprint[1]}",
        "",
        "## Diagnoza",
        "",
        f"Wyjaśnienie: BRAK_WZORCA · {stop['what']}",
        "",
        "| Sprawdzenie | Wynik | Szczegóły |",
        "| --- | --- | --- |",
        *(f"| {check['label']} | {results[check['state']]} | {check['detail']} |" for check in diagnosis["checks"]),
        "",
        "## Dziennik Centrum rozliczeń",
        "",
        "```text",
        *log_lines[:diagnosed],
        "```",
    ]
    assert body.endswith("```\n")


def test_zgloszenie_z_narzedzia_bez_commitu_gita_ma_commit_nieznany(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(github=FakeGitHub(tool_commit=None)))
    run_id = stopped_for_maks(centrum)

    body = diagnose(centrum, run_id)["report"]["body"].splitlines()

    assert body[body.index("## Narzędzie") + 2] == "- Commit: nieznany"


def test_zgloszenie_nie_ma_tresci_wierszy_wyjatku_pelnych_sciezek_ani_klucza(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    centrum.engines.fail_engine = True
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    diagnose(centrum, run_id)
    send(centrum, run_id)

    [report] = centrum.surroundings.report_box.sent
    text = report.title + report.body
    for forbidden in ("SYN-", "nieprzewidziany błąd", REPORT_KEY, str(tmp_path), tmp_path.as_posix(), "Traceback"):
        assert forbidden not in text
    assert REPORT_KEY not in centrum.log_path.read_text(encoding="utf-8")


def test_adres_wpisany_jako_wykonawca_wychodzi_w_tytule_zgloszenia_zamaskowany_z_uwaga(tmp_path: Path) -> None:
    # Komunikat nieznanego Wykonawcy cytuje WYKONAWCA w „Co się stało”, a z niego jest tytuł Zgłoszenia; tu tata
    # wpisał w WYKONAWCA adres, który stoi w ADRES innego Wiersza danych (reguła danych, ADR 0025).
    address = "Syntetyczna Kwarcowa 9/2"
    centrum = settling_centrum(tmp_path)
    write_quantity_source(centrum.collective_file, [{"B": address}, {"H": address}])
    write_report_key(centrum.tool)
    run_to_end(centrum, dry_run=False)
    run_id = run_to_end(centrum, dry_run=False)["run"]["id"]
    preview = diagnose(centrum, run_id)["report"]

    assert send(centrum, run_id) == {"state": "sent"}
    [report] = centrum.surroundings.report_box.sent
    assert {"title": report.title, "body": report.body} == preview
    assert "Kwarcowa" not in report.title + report.body
    assert "spoza konfiguracji wykonawców: [adres]." in report.title
    assert report.body.endswith(
        "## Uwagi techniczne\n\n"
        "- Reguła danych: zamaskowano wartość kolumny ADRES w: tytuł Zgłoszenia.\n"
        "- Reguła danych: zamaskowano wartość kolumny ADRES w: treść Zgłoszenia.\n"
    )


MARKER = "SYN-SLAD-158 treść wyjątku z Rejestru zleceń"


def raise_with_marker(path: Path) -> NoReturn:
    raise KeyError(MARKER)


def trace_section(body: str) -> list[str]:
    """Linie sekcji śladu wywołań w treści Zgłoszenia; pusta lista, gdy jej nie ma."""

    lines = body.splitlines()
    if "## Ślad wywołań" not in lines:
        return []
    section = lines[lines.index("## Ślad wywołań") + 1 :]
    return section[: next((i for i, line in enumerate(section) if line.startswith("## ")), len(section))]


def test_nieoczekiwany_wyjatek_daje_w_zgloszeniu_typ_i_ramki_kodu_narzedzia_bez_tresci_wyjatku(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(readers=on_register_read(raise_with_marker)))
    write_report_key(centrum.tool)
    stopped = run_to_end(centrum, dry_run=True)
    run_id = stopped["run"]["id"]

    preview = diagnose(centrum, run_id)["report"]
    send(centrum, run_id)

    assert stopped["result"]["ending"] == "unexpected"
    section = trace_section(preview["body"])
    assert "- Wyjątek: KeyError" in section
    frames = section[section.index("```text") + 1 : section.index("```")]
    assert all(re.fullmatch(r"(src|tests)/[\w/]+\.py:\d+ w \S+", frame) for frame in frames), frames
    assert re.fullmatch(r"src/rozliczenia/process_run\.py:\d+ w _run_engine", frames[0])
    assert any(re.fullmatch(r"src/rozliczenia/collective_preparation\.py:\d+ w check", frame) for frame in frames)
    raising_line = raise_with_marker.__code__.co_firstlineno + 1
    assert frames[-1] == f"tests/test_centrum_zgloszenie.py:{raising_line} w raise_with_marker"
    [report] = centrum.surroundings.report_box.sent
    assert report.body == preview["body"]
    for text in (
        preview["title"] + preview["body"],
        centrum.log_path.read_text(encoding="utf-8"),
        centrum.metrics_path.read_text(encoding="utf-8"),
        centrum.client.get("/api/runs/current").text,
    ):
        assert "SYN-SLAD" not in text
        assert str(Path.home()) not in text


def test_zatrzymanie_z_komunikatem_procesu_nie_ma_sladu_wywolan(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)

    report = diagnose(centrum, stopped["run"]["id"])["report"]

    assert trace_section(report["body"]) == []


def test_powtorka_zatrzymania_dla_taty_z_przyczyna_w_wyjatku_ma_w_zgloszeniu_slad_wywolan(tmp_path: Path) -> None:
    """Zatrzymanie dla taty, którego przyczyną jest wyjątek (Pliku zbiorczego nie ma: ``WorkbookError``), ma ślad
    wywołań, więc Zgłoszenie jego Powtórki niesie typ wyjątku i jego przyczynę z ramkami kodu narzędzia (#976)."""

    centrum = settling_centrum(tmp_path)
    centrum.collective_file.unlink()
    assert run_to_end(centrum, dry_run=True)["result"]["stop_kind"] == "for_tata"
    repeated = run_to_end(centrum, dry_run=True)
    assert repeated["result"]["stop_kind"] == "repeated"

    section = trace_section(diagnose(centrum, repeated["run"]["id"])["report"]["body"])

    assert section[1:3] == ["- Wyjątek: rozliczenia.message.StopError", "- Przyczyna: rozliczenia.workbook_files.WorkbookError"]
    assert section[section.index("```text") + 1].startswith("src/rozliczenia/"), section


def queued_reports(centrum: PreparingCentrum) -> list[dict[str, Any]]:
    """Pliki Zgłoszeń w kolejce Skrzynki (bez Logów Uruchomienia, które czekają obok)."""

    directory = centrum.tool.queue
    return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*-zgloszenie-*.json"))]


def cases(centrum: PreparingCentrum) -> list[dict[str, Any]]:
    return dad_cases(centrum.tmp_path / "config", "zgloszenie")


FOR_KEY = {"state": "queued", "waits_for": "key"}
FOR_INTERNET = {"state": "queued", "waits_for": "internet"}


def test_bez_klucza_zgloszenie_zatrzymania_czeka_w_kolejce_z_trescia_podgladu_bez_pliku_md(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    preview = diagnose(centrum, run_id)["report"]

    queued = send(centrum, run_id)

    assert queued == FOR_KEY
    [post] = queued_reports(centrum)
    assert (post["target"]["title"], "".join(post["parts"]), post["period"]) == (preview["title"], preview["body"], PERIOD)
    assert list(ToolDirectory(tmp_path).queue.parent.iterdir()) == [ToolDirectory(tmp_path).queue]
    assert centrum.surroundings.report_box.sent == []
    assert [case["number"] for case in cases(centrum)] == [None]
    assert f"skrzynka-w-kolejce etykieta=zgloszenie okres={PERIOD}" in centrum.log_path.read_text(encoding="utf-8")
    assert current_report(centrum) == queued


def test_zgloszenie_zatrzymania_bez_sieci_wysyla_sie_samo_po_powrocie_sieci(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    box.search_failure = Unreachable()
    run_id = stopped_for_maks(centrum)
    preview = diagnose(centrum, run_id)["report"]

    queued = send(centrum, run_id)
    box.search_failure = None
    centrum.surroundings.clock.advance(RETRY_S)

    assert queued == FOR_INTERNET
    assert box.wait_until(lambda box: len(box.sent) == 1)
    assert [{"title": report.title, "body": report.body} for report in box.sent] == [preview]
    assert report_becomes(centrum, {"state": "sent"}) == {"state": "sent"}
    assert [case["number"] for case in cases(centrum)] == [1]


def test_zgloszenie_z_kolejki_wychodzi_po_restarcie_centrum_z_numerem_w_stanie_wyslanych(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    diagnose(centrum, run_id)
    assert send(centrum, run_id) == FOR_KEY
    write_report_key(centrum.tool)

    centrum.restart()
    with centrum.client:
        assert centrum.surroundings.report_box.wait_until(lambda box: len(box.sent) == 1)
        assert wait_for(lambda: case_states(centrum.client, "zgloszenie") == ["wyslana"])
    centrum.client.stop()

    assert [case["number"] for case in cases(centrum)] == [1]
    assert queued_reports(centrum) == []


def test_numer_zgloszenia_z_kolejki_zostaje_po_restarcie_gdy_windows_na_chwile_blokuje_plik_spraw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    diagnose(centrum, run_id)
    assert send(centrum, run_id) == FOR_KEY
    write_report_key(centrum.tool)
    lock_file(monkeypatch, DAD_CASES_FILE, failures=2)

    centrum.restart()
    with centrum.client:
        assert centrum.surroundings.report_box.wait_until(lambda box: len(box.sent) == 1)
        assert wait_for(lambda: case_states(centrum.client, "zgloszenie") == ["wyslana"])
    centrum.client.stop()
    centrum.restart()

    assert case_states(centrum.client, "zgloszenie") == ["wyslana"]
    assert [case["number"] for case in cases(centrum)] == [1]
    assert queued_reports(centrum) == []


def test_zgloszenie_ktorego_nie_da_sie_zapisac_w_kolejce_daje_komunikat(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    diagnose(centrum, run_id)
    centrum.client.stop()
    queue = ToolDirectory(tmp_path).queue
    shutil.rmtree(queue)  # Logi Uruchomienia w kolejce
    queue.write_text("", encoding="utf-8")  # plik zamiast folderu: zapis się nie uda

    state = send(centrum, run_id)

    assert state == {
        "state": "not_queued",
        "message": {
            "what": "Nie udało się zapisać Zgłoszenia na tym komputerze, więc nie pójdzie do Maksa.",
            "where": "folder kolejka",
            "action": "Kliknij „Spróbuj ponownie”. Jeśli to nie pomoże, rozwiń „Co zostanie wysłane”, skopiuj treść i "
            "prześlij ją Maksowi mailem.",
        },
    }
    assert cases(centrum) == []


def test_niezapisane_zgloszenie_powracajacego_problemu_zostawia_jego_poprzednie_zgloszenie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    first = stopped_for_maks(centrum)
    diagnose(centrum, first)
    send(centrum, first)
    centrum.surroundings.report_box.close(1)
    assert [item["state"] for item in centrum.client.get("/api/notifications").json()["items"]] == ["rozwiazana"]
    centrum.restart()
    again = stopped_for_maks(centrum)
    diagnose(centrum, again)
    centrum.client.stop()
    queue = ToolDirectory(tmp_path).queue
    shutil.rmtree(queue)
    queue.write_text("", encoding="utf-8")  # plik zamiast folderu: zapis się nie uda

    state = send(centrum, again)

    assert state["state"] == "not_queued"
    assert "- Poprzednie Zgłoszenie: #1" in diagnose(centrum, again)["report"]["body"].splitlines()
    items = centrum.client.get("/api/notifications").json()["items"]
    assert [(item["kind"], item["state"]) for item in items] == [("zgloszenie", "rozwiazana")]
    assert [case["number"] for case in cases(centrum)] == [1]


@pytest.mark.parametrize("started", [preparing_centrum, settling_centrum], ids=["przygotowanie", "przebieg"])
def test_zatrzymanie_centrum_czeka_na_kazdy_jego_watek_takze_sprzed_ponownego_startu_a_drugie_nic_nie_robi(
    tmp_path: Path, started: Callable[[Path], PreparingCentrum | SettlingCentrum]
) -> None:
    centrum = started(tmp_path)
    write_report_key(centrum.tool)
    hold = centrum.surroundings.report_box.search_hold = threading.Event()
    run_id = stopped_for_maks(centrum)
    diagnose(centrum, run_id)  # Diagnoza pyta skrzynkę o Zgłoszenie w tle, a skrzynka nie odpowiada
    centrum.restart()

    with centrum.client:
        running = centrum.client.threads()
        with pytest.raises(AssertionError, match=f"żyją wątki .*{REPORT_THREAD}"):
            centrum.client.stop(timeout_s=0)
        hold.set()
        centrum.client.stop()
        centrum.client.stop()

    assert {REPORT_THREAD, KEY_CHECK_THREAD} <= {thread.name for thread in running}
    assert [thread.name for thread in running if thread.is_alive()] == []


@pytest.mark.parametrize("started", [preparing_centrum, settling_centrum], ids=["przygotowanie", "przebieg"])
def test_ponowny_start_centrum_zaczyna_sie_po_koncu_przejscia_kolejki_poprzedniego_jak_nowy_proces(
    tmp_path: Path, started: Callable[[Path], PreparingCentrum | SettlingCentrum], monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = started(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)
    diagnose(centrum, run_id)
    box = centrum.surroundings.report_box
    hold = box.open_hold = threading.Event()
    monkeypatch.setattr("rozliczenia.centrum.reports.DELIVERY_WAIT_S", 0.01)
    queued = send(centrum, run_id)
    release = threading.Timer(0.2, hold.set)
    release.start()

    centrum.restart()

    assert (queued, len(box.sent)) == (FOR_INTERNET, 1)


@pytest.mark.parametrize("started", [preparing_centrum, settling_centrum], ids=["przygotowanie", "przebieg"])
def test_po_ponownym_starcie_kolejke_ponawia_tylko_budzik_nowego_centrum_jak_w_nowym_procesie(
    tmp_path: Path, started: Callable[[Path], PreparingCentrum | SettlingCentrum]
) -> None:
    centrum = started(tmp_path)
    stopped_for_maks(centrum)  # bez klucza Logi Uruchomienia czekają, a kolejka nastawia ponowienie za ``RETRY_S``
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock
    centrum.restart()
    clock.advance(RETRY_S / 2)
    with centrum.client:  # nowe Centrum przy starcie przechodzi kolejkę i bez klucza ponowi ją za ``RETRY_S``
        pass
    centrum.client.stop()
    write_report_key(centrum.tool)

    clock.advance(RETRY_S / 2)  # chwila ponowienia poprzedniego Centrum
    centrum.client.stop()
    after_previous_alarm = len(box.background_issues)
    clock.advance(RETRY_S / 2)  # chwila ponowienia nowego Centrum
    centrum.client.stop()

    assert (after_previous_alarm, len(box.background_issues)) == (0, 1)


def test_po_ponownym_starcie_uporzadkowania_intermax_kolejke_ponawia_tylko_budzik_nowego_centrum(
    tmp_path: Path,
) -> None:
    centrum = ordering_centrum(tmp_path)
    centrum.run_to_end()  # bez klucza Logi Uruchomienia czekają, a kolejka nastawia ponowienie za ``RETRY_S``
    centrum.client.stop()
    box, clock = centrum.surroundings.report_box, centrum.surroundings.clock
    centrum.restart()
    clock.advance(RETRY_S / 2)
    with centrum.client:  # nowe Centrum przy starcie przechodzi kolejkę i bez klucza ponowi ją za ``RETRY_S``
        pass
    centrum.client.stop()
    write_report_key(centrum.tool)

    clock.advance(RETRY_S / 2)  # chwila ponowienia poprzedniego Centrum
    centrum.client.stop()
    after_previous_alarm = len(box.background_issues)
    clock.advance(RETRY_S / 2)  # chwila ponowienia nowego Centrum
    centrum.client.stop()

    assert (after_previous_alarm, len(box.background_issues)) == (0, 1)


def test_ponowny_start_uporzadkowania_intermax_zaczyna_sie_po_koncu_przejscia_kolejki_poprzedniego(
    tmp_path: Path,
) -> None:
    box = FakeReportBox()  # Logi Uruchomienia idą zakładaniem issue, które test wstrzymuje
    centrum = ordering_centrum(tmp_path, surroundings=Surroundings(report_box=box))
    write_report_key(centrum.tool)
    hold = box.open_hold = threading.Event()
    centrum.run_to_end()
    assert box.opening.wait(30)  # przejście kolejki czeka na skrzynkę z Logami Uruchomienia
    release = threading.Timer(0.2, hold.set)
    release.start()

    centrum.restart()

    assert [issue.label for issue in box.issues] == ["logi-uruchomienia"]


def test_zatrzymanie_centrum_nie_czeka_na_budzik_centrum_poprzedniego_testu_nastawiony_po_jego_starcie(
    tmp_path: Path,
) -> None:
    rings = threading.Event()
    next_rings = threading.Event()

    def ring() -> None:
        rings.wait()
        threading.Thread(target=next_rings.wait, name=ALARM_THREAD, daemon=True).start()

    # Budzik kolejki Centrum z poprzedniego testu (``SYSTEM_CLOCK``): dzwoni co ``RETRY_S`` i nastawia następny.
    earlier = threading.Thread(target=ring, name=ALARM_THREAD, daemon=True)
    earlier.start()
    started = plain_centrum(tmp_path)
    rings.set()
    earlier.join()

    try:
        assert started.client.threads() == []
        started.client.stop(timeout_s=0)
    finally:
        next_rings.set()


def current_report(centrum: PreparingCentrum) -> object:
    view = centrum.client.get("/api/runs/current").json()
    return view["result"]["report"]


def report_becomes(centrum: PreparingCentrum, expected: object) -> object:
    """Stan Zgłoszenia na karcie, gdy dojdzie do ``expected`` (odpowiedź skrzynki przychodzi w tle), albo po 10 s."""

    _, report = wait_for_value(lambda: current_report(centrum), lambda report: report == expected, 10, every=0.01)
    return report


def test_wyslanie_jest_raz_na_zatrzymanie_a_wynik_uruchomienia_pokazuje_potwierdzenie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)
    assert current_report(centrum) == {"state": "ready"}
    diagnose(centrum, run_id)

    first, second = send(centrum, run_id), send(centrum, run_id)

    assert first == second == {"state": "sent"}
    assert len(centrum.surroundings.report_box.keys) == 1
    assert current_report(centrum) == {"state": "sent"}


def test_ponowna_diagnoza_po_wyslaniu_pokazuje_wyslane_zgloszenie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)
    diagnose(centrum, run_id)
    send(centrum, run_id)

    diagnose(centrum, run_id)

    assert (current_report(centrum), send(centrum, run_id)) == ({"state": "sent"}, {"state": "sent"})
    assert len(centrum.surroundings.report_box.sent) == 1


def test_zatrzymanie_dla_taty_nie_proponuje_zgloszenia(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    (centrum.fixture.register_path.parent / f"~${centrum.fixture.register_path.name}").touch()

    view = run_to_end(centrum, dry_run=True)

    assert (view["result"]["stop_kind"], view["result"]["report"]) == ("for_tata", None)
    assert centrum.client.post(f"/api/runs/{view['run']['id']}/report").status_code == 409


def test_wyslanie_bez_diagnozy_jest_odrzucone(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)

    refused = centrum.client.post(f"/api/runs/{run_id}/report")

    assert (refused.status_code, refused.json()) == (
        409,
        {"message": "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”."},
    )
    assert centrum.surroundings.report_box.keys == []


def key_state(centrum: PreparingCentrum) -> str:
    response = centrum.client.get("/api/configuration")
    assert response.status_code == 200
    assert REPORT_KEY not in response.text
    state: str = response.json()["reports"]
    return state


def test_konfiguracja_pokazuje_stan_klucza_do_zgloszen_bez_jego_wartosci(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    missing = key_state(centrum)
    key_file = write_report_key(centrum.tool)
    ready = key_state(centrum)
    key_file.write_bytes(codecs.BOM_UTF8 + b"\r\n")  # Notatnik zapisał pusty plik

    assert (missing, ready, key_state(centrum)) == ("missing_key", "ready", "missing_key")
    assert centrum.surroundings.report_box.listed == [("zgloszenie", False)]


def test_start_centrum_sprawdza_klucz_w_skrzynce_w_tle_bez_zadnego_zapytania(tmp_path: Path) -> None:
    write_report_key(ToolDirectory(tmp_path))
    centrum = plain_centrum(tmp_path)

    with centrum.client:
        assert centrum.report_box.searching.wait(10), "Skrzynka nie dostała sprawdzenia klucza przy starcie"

    assert centrum.report_box.listed == [("zgloszenie", False)]


def test_skrzynka_github_odrzuca_klucz_ktorego_nie_da_sie_wyslac_bez_pytania_sieci(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    write_report_key(tool, "klucz z Notatnika")

    answer = CentrumClient(centrum_app(tool, report_box=None)).get("/api/configuration")

    assert answer.json()["reports"] == "refused_key"


def test_konfiguracja_pokazuje_klucz_odrzucony_gdy_skrzynka_odmawia_klucza(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    box = centrum.surroundings.report_box
    box.search_failure = Refused()
    key_file = write_report_key(centrum.tool)

    refused = key_state(centrum)
    box.search_failure = None
    key_file.write_text(REPORT_KEY + "_NOWY\n", encoding="utf-8")

    assert (refused, key_state(centrum)) == ("refused_key", "ready")


def test_konfiguracja_bez_sieci_albo_przed_odpowiedzia_skrzynki_pokazuje_gotowe(tmp_path: Path) -> None:
    hold = threading.Event()
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(report_box=FakeReportBox(search_hold=hold)))
    box = centrum.surroundings.report_box
    write_report_key(centrum.tool)

    silent = key_state(centrum)
    box.search_failure = Unreachable()
    hold.set()
    offline = key_state(centrum)
    assert len(box.listed) == 1
    centrum.surroundings.clock.advance(minutes=1)

    assert (silent, offline, key_state(centrum)) == ("ready", "ready", "ready")
    assert box.listed == [("zgloszenie", False), ("zgloszenie", False)]


def test_odmowa_przy_wysylce_uwagi_odrzuca_klucz_w_konfiguracji_bez_osobnego_pytania(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    box = centrum.surroundings.report_box
    box.outcomes.append(Refused())
    write_report_key(centrum.tool)

    sent = centrum.client.post("/api/dad-notes", json={"title": "Excel myśli minutę"})

    assert sent.json() == {"state": "waiting", "waits_for": "key"}
    assert key_state(centrum) == "refused_key"
    assert box.listed == [("uwaga-taty", True)]  # kolejka szuka issue tej Uwagi, a Konfiguracja nie pyta o klucz osobno


WAITING = {"state": "waiting"}


def diagnosed_to_end(centrum: PreparingCentrum, run_id: str) -> str:
    """Diagnoza Zatrzymania i jej dalszy ciąg w tle (odpowiedź skrzynki, powrót problemu w kolejce); treść podglądu."""

    since = new_line()
    body: str = diagnose(centrum, run_id)["report"]["body"]
    join_threads_since(since, named=REPORT_THREAD)
    return body


def test_powrot_problemu_z_otwartym_zgloszeniem_po_diagnozie_jest_komentarzem_w_nim_bez_klikniecia(
    tmp_path: Path
) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    first = stopped_for_maks(centrum)
    diagnose(centrum, first)
    send(centrum, first)

    again = stopped_for_maks(centrum)

    assert current_report(centrum) == WAITING
    again_body = diagnosed_to_end(centrum, again)
    [issue] = centrum.surroundings.report_box.sent
    assert issue.comments == [f"## Zgłoszenie wróciło\n\n{again_body}"]
    assert current_report(centrum) == WAITING
    assert [case["number"] for case in cases(centrum)] == [1]


def test_druga_diagnoza_tego_samego_zatrzymania_nie_dubluje_komentarza_powrotu(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    first = stopped_for_maks(centrum)
    diagnose(centrum, first)
    send(centrum, first)
    again = stopped_for_maks(centrum)
    diagnosed_to_end(centrum, again)

    diagnosed_to_end(centrum, again)

    [issue] = centrum.surroundings.report_box.sent
    assert (len(issue.comments), current_report(centrum)) == (1, WAITING)


def test_diagnoza_nie_czeka_na_skrzynke_a_jej_odpowiedz_o_otwartym_zgloszeniu_trafia_na_karte(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    first = stopped_for_maks(centrum)
    diagnose(centrum, first)
    send(centrum, first)
    (tmp_path / "config" / DAD_CASES_FILE).unlink()  # Zgłoszenie wysłane spoza tego komputera
    centrum.restart()
    again = stopped_for_maks(centrum)
    box.search_hold = threading.Event()
    box.searching.clear()
    release = threading.Timer(10, box.search_hold.set)  # gdyby Diagnoza czekała na skrzynkę
    release.start()

    try:
        diagnose(centrum, again)
        box_answered = box.search_hold.is_set()
        while_box_silent = current_report(centrum)
    finally:
        box.search_hold.set()
        release.cancel()

    assert (box_answered, while_box_silent) == (False, {"state": "ready"})
    assert report_becomes(centrum, WAITING) == WAITING
    # Odpowiedź skrzynki o otwartym Zgłoszeniu spoza tego komputera też kładzie powrót problemu w kolejce.
    assert box.wait_until(lambda box: len(box.sent[0].comments) == 1)
    assert len(box.sent) == 1


def test_zgloszenie_zamkniete_wedlug_powiadomien_nie_czeka_juz_po_restarcie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    first = stopped_for_maks(centrum)
    diagnose(centrum, first)
    send(centrum, first)
    box.close(1)
    assert [item["state"] for item in centrum.client.get("/api/notifications").json()["items"]] == ["rozwiazana"]
    centrum.restart()

    again = stopped_for_maks(centrum)

    assert current_report(centrum) == {"state": "ready"}
    preview_body = diagnosed_to_end(centrum, again)
    assert "- Poprzednie Zgłoszenie: #1" in preview_body.splitlines()
    # Bez otwartego Zgłoszenia nic nie wychodzi samo: tata ma przycisk i podgląd.
    assert ([issue.comments for issue in box.sent], current_report(centrum)) == ([[]], {"state": "ready"})
    assert send(centrum, again) == {"state": "sent"}
    sent = dad_cases(tmp_path / "config", "zgloszenie")
    assert [(entry["number"], entry["closure"] is None) for entry in sent] == [(1, False), (2, True)]


def test_podglad_zgloszenia_czeka_w_tle_na_skrzynke_zgloszen_najwyzej_3_s() -> None:
    assert SEARCH_DEADLINE_S == 3.0


def test_dwa_klikniecia_w_trakcie_wysylki_daja_jedno_zgloszenie_a_centrum_odpowiada_dalej(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    run_id = stopped_for_maks(centrum)
    # Podgląd z Diagnozy pyta skrzynkę w tle: bez czekania jego pytanie mogłoby stanąć na wstrzymaniu i ustawić
    # ``searching`` przed kliknięciem (#973).
    diagnosed_to_end(centrum, run_id)
    box.search_hold = threading.Event()
    box.searching.clear()

    with ThreadPoolExecutor(3) as pool:
        try:
            clicks = [pool.submit(send, centrum, run_id) for _ in range(2)]
            assert box.searching.wait(5)
            during_send = pool.submit(centrum.client.get, "/api/notifications").result(timeout=2)
        finally:
            box.search_hold.set()
        answers = [click.result(timeout=10) for click in clicks]

    notifications = during_send.json()
    assert (notifications["unread"], [item["state"] for item in notifications["items"]]) == (0, ["czeka_na_internet"])
    assert answers == [{"state": "sent"}, {"state": "sent"}]
    assert len(box.sent) == 1
