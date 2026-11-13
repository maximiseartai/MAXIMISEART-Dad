"""Aktualizacja narzędzia w Centrum rozliczeń przez HTTP API, na prawdziwym klonie z lokalnym „origin”.

Reguły samej aktualizacji sprawdza ``test_aktualizacja_narzedzia.py`` na
interfejsie modułu; tutaj jest to, co widzi przeglądarka: akcja, krok,
wynik, Konfiguracja, odmowy „jedno naraz” i dziennik Centrum.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any

import pytest
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from rozliczenia.centrum import restart_guardian
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.outbox import RETRY_S
from rozliczenia.centrum.report_box import Unreachable
from rozliczenia.centrum.tool_updates import UPDATE_THREAD
from rozliczenia.centrum.tool_update import (
    LIBRARIES_FAILED,
    LOCAL_CHANGES,
    LOGIN,
    NEW_VERSION_FAILED,
    NO_CONNECTION,
    NO_GIT,
    OTHER_BRANCH,
    RESULT_FILE,
    ROLLBACK_FAILED,
    UNEXPECTED,
    UPDATED,
    ToolClone,
    UpdateResult,
    read_result,
    write_result,
)

from tests.fixtures.centrum import CENTRUM, NO_RELEASE, join_threads_since, views_until, write_report_key
from tests.fixtures.centrum_processes import (
    PreparingCentrum,
    Surroundings,
    preparing_centrum,
    run_to_end,
    settings_changed_at,
    stopped_for_maks,
)
from tests.fixtures.potomne import wait_for, wait_for_value
from atrapy.settlement import worker_list, write_worker_list
from atrapy.preparation import PERIOD, incomplete_period_rows
from tests.fixtures.tool_clone import (
    NEW_REQUIREMENTS,
    FakeInstaller,
    ToolRepository,
    git,
    tool_repository,
)


def updating_centrum(
    tmp_path: Path,
    *,
    hold: threading.Event | None = None,
    incomplete_period: bool = False,
    installer: FakeInstaller | None = None,
    guardian_failure: Callable[[ToolRepository], None] | None = None,
) -> tuple[PreparingCentrum, ToolRepository]:
    repository = tool_repository(tmp_path / "repozytoria")
    surroundings = Surroundings(
        guardian_failure=None if guardian_failure is None else lambda: guardian_failure(repository),
        tool=repository,
        update_hold=hold,
        installer=installer or FakeInstaller(),
    )
    rows = incomplete_period_rows() if incomplete_period else None
    return preparing_centrum(tmp_path, rows, surroundings=surroundings), repository


# Ile test czeka na każdy krok Aktualizacji narzędzia, także na pytanie do skrzynki po porażce: Git na przeciążonym
# runnerze Windows potrafi zająć ponad 10 s (#573).
UPDATE_WAIT_S = 30


def update_until_done(centrum: PreparingCentrum) -> dict[str, Any]:
    started = centrum.client.post("/api/tool-update")
    assert started.status_code == 202, started.json()
    assert started.json() == {"state": "running", "step": "fetching"}
    return tool_update_done(centrum)


def tool_update_done(centrum: PreparingCentrum) -> dict[str, Any]:
    """Czeka na wynik trwającej Aktualizacji narzędzia albo na zamknięcie Centrum do ponownego startu."""

    view = tool_update_until(centrum, lambda view: view["state"] != "running" or view["step"] == "restarting")
    if view["state"] == "running":
        # Karta widzi „restarting”, zanim opiekun wystartuje, a Centrum zamyka się dopiero po jego starcie (#661).
        join_threads_since(centrum.client.since, named=UPDATE_THREAD)
    return view


def update_until_result(centrum: PreparingCentrum) -> dict[str, Any]:
    """Klika „Zaktualizuj narzędzie” i czeka na wynik, także po nieudanej próbie ponownego startu."""

    assert centrum.client.post("/api/tool-update").status_code == 202
    return tool_update_until(centrum, lambda view: view["state"] != "running")


def tool_update_until(centrum: PreparingCentrum, reached: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    done, view = wait_for_value(lambda: dict(centrum.client.get("/api/tool-update").json()), reached, UPDATE_WAIT_S, every=0.02)
    assert done, f"Aktualizacja narzędzia utknęła w {view}."
    return view


def tool_on_configuration(centrum: PreparingCentrum) -> dict[str, Any]:
    configuration = centrum.client.get("/api/configuration").json()
    version = configuration["version"]
    return {
        "commit": None if version is None else version["commit"],
        "freshness": configuration["freshness"],
        "update_offered": configuration["update_offered"],
    }


def log_events(centrum: PreparingCentrum) -> list[str]:
    return [line.split(" ", 2)[1] for line in centrum.log_path.read_text(encoding="utf-8").splitlines()]


def log_entries(centrum: PreparingCentrum, event: str) -> list[str]:
    lines = centrum.log_path.read_text(encoding="utf-8").splitlines()
    return [line.split(" ", 2)[2] for line in lines if line.split(" ", 2)[1] == event]


def test_po_aktualizacji_centrum_zamyka_sie_i_prosi_opiekuna_o_start_nowej_wersji(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    outdated = tool_on_configuration(centrum)

    view = update_until_done(centrum)
    run = centrum.start(dry_run=True)

    assert outdated["commit"] == before[:7]
    assert (outdated["freshness"], outdated["update_offered"]) == ("newer", True)
    assert view == {"state": "running", "step": "restarting"}
    assert repository.head() == newest
    [restart] = centrum.surroundings.restarts
    assert (restart.port, restart.before, restart.after, restart.installed) == (47811, before, newest, False)
    assert (restart.root, restart.result) == (repository.clone, tmp_path / "config" / RESULT_FILE)
    assert log_entries(centrum, "aktualizacja-start") == [f"przed={before}"]
    assert log_entries(centrum, "zamkniecie") == ["z=aktualizacja"]
    assert "aktualizacja-koniec" not in log_events(centrum)
    assert (run.status_code, run.json()) == (
        409,
        {"message": "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem uruchom proces."},
    )


@pytest.mark.parametrize("server", [None, ("/tmp/centrum.sock", None)], ids=["bez-server", "gniazdo-bez-portu"])
def test_aktualizacja_bez_portu_centrum_odmawia_i_nie_zaczyna_sie(
    tmp_path: Path, server: tuple[str, None] | None
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    app = centrum.client.app

    async def without_port(scope: Scope, receive: Receive, send: Send) -> None:
        changed = {key: value for key, value in scope.items() if key != "server"}
        if server is not None:
            changed["server"] = server
        await app(changed, receive, send)

    answer = TestClient(without_port, base_url=CENTRUM, headers={"Origin": CENTRUM}).post("/api/tool-update")

    assert (answer.status_code, answer.json()) == (
        500,
        {
            "message": "Centrum rozliczeń nie zna swojego portu, więc nie zaktualizuje narzędzia. "
            "Zamknij Centrum rozliczeń i kliknij skrót „Centrum rozliczeń” na pulpicie."
        },
    )
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}
    assert (repository.head(), centrum.surroundings.restarts) == (before, [])


def test_nowe_centrum_po_aktualizacji_zapisuje_wynik_od_opiekuna_w_dzienniku_i_pokazuje_go_karcie(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    old_health = centrum.client.get("/api/health").json()
    update_until_done(centrum)
    [restart] = centrum.surroundings.restarts
    write_result(restart.result, UpdateResult(UPDATED, restart.before, restart.after, restart.installed))

    centrum.restart()
    new_health = centrum.client.get("/api/health").json()
    view = centrum.client.get("/api/tool-update").json()
    centrum.restart()

    assert (old_health["commit"], new_health["commit"]) == (before[:7], newest[:7])
    assert new_health["instance"] != old_health["instance"]
    assert view == {"state": "updated"}
    assert tool_on_configuration(centrum) == {"commit": newest[:7], "freshness": "current", "update_offered": False}
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={before} po={newest} biblioteki=nie"]
    assert not restart.result.exists()
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}


def run_logs_wydanie(centrum: PreparingCentrum) -> list[str | None]:
    paths = centrum.tool.run_logs.glob("*.json")
    logs = sorted((json.loads(path.read_text(encoding="utf-8")) for path in paths), key=lambda log: log["started_at"])
    return [log["tool"]["wydanie"] for log in logs]


def test_po_aktualizacji_logi_uruchomienia_podaja_wydanie_pobrane_przez_aktualizacje(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"}, released=False)
    repository.release(annotated=True)
    run_to_end(centrum, dry_run=True)
    update_until_done(centrum)

    centrum.restart()
    run_to_end(centrum, dry_run=True)

    assert run_logs_wydanie(centrum) == ["0.1.0", "0.1.1"]
    assert repository.in_clone("tag", "--points-at", "HEAD") == ""


def test_najnowsza_wersja_zostaje_bez_zmian(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    current = repository.head()

    view = update_until_done(centrum)

    assert view == {"state": "up_to_date"}
    assert repository.head() == current
    assert tool_on_configuration(centrum)["freshness"] == "current"
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=AKTUALNA przed={current} po={current} biblioteki=nie"
    ]


def release_in_clone_after_start(repository: ToolRepository) -> None:
    """Nowe Wydanie, na które klon przeszedł po starcie Centrum (ręcznie): Centrum działa dalej na commicie ze
    startu, więc proponuje Aktualizację, a próba kończy się ``AKTUALNA``, bo klon już zawiera to Wydanie."""

    repository.publish({"src/narzedzie.py": "WERSJA = 1.5\n"})
    repository.in_clone("fetch", "--quiet", str(repository.origin), "main")
    repository.in_clone("merge", "--quiet", "--ff-only", "FETCH_HEAD")


def up_to_date_while_offered(centrum: PreparingCentrum, repository: ToolRepository) -> dict[str, Any]:
    """Wynik ``AKTUALNA`` przy proponowanym przycisku (``release_in_clone_after_start``): wynik próby i to, co zaraz po niej
    widzi karta."""

    release_in_clone_after_start(repository)
    offered_before = tool_on_configuration(centrum)["update_offered"]
    result = update_until_done(centrum)
    return {
        "offered_before": offered_before,
        "result": result,
        "right_after": centrum.client.get("/api/tool-update").json(),
        "offered_after": tool_on_configuration(centrum)["update_offered"],
    }


UP_TO_DATE_WHILE_OFFERED = {
    "offered_before": True,
    "result": {"state": "up_to_date"},
    "right_after": {"state": "up_to_date"},
    "offered_after": True,
}


def test_po_wyniku_aktualna_nowsze_wydanie_konfiguracja_proponuje_aktualizacje_bez_starego_wyniku(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    attempt = up_to_date_while_offered(centrum, repository)
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    centrum.surroundings.clock.advance(minutes=10)

    newer_offered = tool_on_configuration(centrum)["update_offered"]

    assert attempt == UP_TO_DATE_WHILE_OFFERED
    assert (newer_offered, centrum.client.get("/api/tool-update").json()) == (True, {"state": "idle"})


def test_po_wyniku_aktualna_nowsze_wydanie_diagnoza_proponuje_aktualizacje_bez_starego_wyniku(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    attempt = up_to_date_while_offered(centrum, repository)
    run_id = stopped_for_maks(centrum)
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    # Diagnoza pyta GitHuba przy każdym sprawdzeniu, także w 10 minutach, przez które Konfiguracja pamięta odpowiedź.
    diagnosis = centrum.client.post(f"/api/runs/{run_id}/diagnosis").json()

    assert attempt == UP_TO_DATE_WHILE_OFFERED
    assert (diagnosis["next_action"], centrum.client.get("/api/tool-update").json()) == ("update", {"state": "idle"})


def test_po_wyniku_aktualna_bez_odpowiedzi_githuba_wynik_zostaje(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    attempt = up_to_date_while_offered(centrum, repository)
    centrum.surroundings.release_unanswered = True
    centrum.surroundings.clock.advance(minutes=10)

    # Centrum nie wie, czy najnowsze Wydanie się zmieniło, więc wynik dalej dotyczy tego, co zna.
    assert attempt == UP_TO_DATE_WHILE_OFFERED
    assert centrum.client.get("/api/tool-update").json() == {"state": "up_to_date"}


def test_wynik_aktualna_bez_odpowiedzi_githuba_w_jego_chwili_znika_przy_pierwszej_odpowiedzi(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    release_in_clone_after_start(repository)
    centrum.surroundings.release_unanswered = True
    result = update_until_done(centrum)
    unanswered = centrum.client.get("/api/tool-update").json()
    centrum.surroundings.release_unanswered = False
    centrum.surroundings.clock.advance(minutes=1)

    answered = centrum.client.get("/api/tool-update").json()

    assert (result, unanswered, answered) == ({"state": "up_to_date"}, {"state": "up_to_date"}, {"state": "idle"})


def test_pominiete_wydanie_spoza_main_zostawia_slad_w_dzienniku_centrum(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    current = repository.head()
    git(repository.publisher, "checkout", "--quiet", "-b", "agent")
    git(repository.publisher, "commit", "--quiet", "--allow-empty", "--message", "Zmiana spoza main")
    repository.release(tag="v0.3.0")

    view = update_until_done(centrum)

    assert view == {"state": "up_to_date"}
    assert repository.head() == current
    assert log_entries(centrum, "aktualizacja-pominiete-wydania") == ["tagi=v0.3.0"]
    assert tool_on_configuration(centrum)["freshness"] == "current"


def test_udana_aktualizacja_z_pominietym_wydaniem_spoza_main_zostawia_slad_takze_po_ponownym_starcie(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    git(repository.publisher, "checkout", "--quiet", "-b", "agent")
    git(repository.publisher, "commit", "--quiet", "--allow-empty", "--message", "Zmiana spoza main")
    repository.release(tag="v0.9.0")
    update_until_done(centrum)
    [restart] = centrum.surroundings.restarts
    write_result(restart.result, UpdateResult(UPDATED, restart.before, restart.after, restart.installed))

    centrum.restart()

    assert repository.head() == newest
    assert log_entries(centrum, "aktualizacja-pominiete-wydania") == ["tagi=v0.9.0"]
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={before} po={newest} biblioteki=nie"]


NEWER_MAIN = "f" * 40


def test_konfiguracja_pyta_githuba_o_main_najwyzej_raz_na_10_minut(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    github, clock = centrum.surroundings.github, centrum.surroundings.clock
    first = tool_on_configuration(centrum)["freshness"]
    github.release = NEWER_MAIN

    within_ten_minutes = [tool_on_configuration(centrum)["freshness"] for _ in range(3)]
    clock.advance(minutes=10)
    after_ten_minutes = tool_on_configuration(centrum)["freshness"]

    assert (first, within_ten_minutes, after_ten_minutes) == ("current", ["current"] * 3, "newer")
    assert github.asked == 2


def test_github_bez_wydania_konfiguracja_pamieta_jak_kazda_odpowiedz_przez_10_minut(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    github, clock = centrum.surroundings.github, centrum.surroundings.clock
    github.release = NO_RELEASE
    readings = []
    for _ in range(9):
        readings.append(tool_on_configuration(centrum)["freshness"])
        clock.advance(minutes=1)

    assert readings == ["not_checked"] * 9
    assert github.asked == 1


@pytest.mark.parametrize(
    "limited", [None, datetime(2026, 11, 8, 3, 49, tzinfo=timezone.utc)], ids=["brak-sieci", "limit-githuba"]
)
def test_bez_odpowiedzi_githuba_konfiguracja_pyta_znowu_po_minucie(tmp_path: Path, limited: datetime | None) -> None:
    centrum = preparing_centrum(tmp_path)
    github, clock = centrum.surroundings.github, centrum.surroundings.clock
    github.release, github.limited = None, limited
    offline = tool_on_configuration(centrum)["freshness"]
    github.release, github.limited = NEWER_MAIN, None

    still_offline = tool_on_configuration(centrum)["freshness"]
    clock.advance(minutes=1)
    back_online = tool_on_configuration(centrum)["freshness"]

    assert (offline, still_offline, back_online) == ("not_checked", "not_checked", "newer")
    assert github.asked == 2


def test_diagnoza_bez_odpowiedzi_githuba_nie_kasuje_odpowiedzi_pamietanej_przez_konfiguracje(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    github = centrum.surroundings.github
    github.release = NEWER_MAIN
    remembered = tool_on_configuration(centrum)["freshness"]
    github.release = None

    diagnosis = centrum.client.post(f"/api/runs/{stopped_for_maks(centrum)}/diagnosis")
    after_diagnosis = tool_on_configuration(centrum)["freshness"]

    assert diagnosis.status_code == 200
    assert (remembered, after_diagnosis) == ("newer", "newer")


def test_aktualizacja_w_trakcie_uruchomienia_procesu_jest_odrzucona(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path, incomplete_period=True)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]

    refused = centrum.client.post("/api/tool-update")
    centrum.client.post(f"/api/runs/{waiting['run']['id']}/decision", json={"answer": "abort"})

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "message": (
                f"Trwa Uruchomienie procesu: Przygotowanie pliku zbiorczego, okres {PERIOD}. "
                "Poczekaj na jego wynik w Uruchomieniach, potem zaktualizuj narzędzie."
            )
        },
    )
    assert repository.head() == before
    assert "aktualizacja-start" not in log_events(centrum)


def test_w_trakcie_aktualizacji_uruchomienie_druga_aktualizacja_i_zamkniecie_sa_odrzucone(tmp_path: Path) -> None:
    hold = threading.Event()
    centrum, repository = updating_centrum(tmp_path, hold=hold)
    current = repository.head()
    # Wpisanie raportów bez adresu na Liście Wykonawców odmawia startu, zanim zapyta o miejsce „jedno naraz”.
    write_worker_list(centrum.tool.worker_list, worker_list(addresses={"adrian.testowy": ["adrian@przyklad.invalid"]}))
    assert centrum.client.post("/api/tool-update").status_code == 202

    run = centrum.start(dry_run=True)
    entering = centrum.client.post("/api/report-entering/run")
    second = centrum.client.post("/api/tool-update")
    closing = centrum.client.post("/api/shutdown")
    hold.set()
    assert wait_for(lambda: centrum.client.get("/api/tool-update").json()["state"] != "running", 30, every=0.02)
    run_after = centrum.start(dry_run=True)

    assert (run.status_code, run.json()) == (
        409,
        {"message": "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem uruchom proces."},
    )
    assert (entering.status_code, entering.json()) == (run.status_code, run.json()), "Wpisanie raportów też czeka"
    assert (second.status_code, second.json()) == (
        409,
        {"message": "Trwa już aktualizacja narzędzia. Poczekaj na jej wynik."},
    )
    assert (closing.status_code, closing.json()) == (
        409,
        {"message": "Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem zamknij Centrum rozliczeń."},
    )
    assert repository.head() == current
    assert run_after.status_code == 200
    assert log_events(centrum).count("aktualizacja-start") == 1


def test_po_przyjetym_zamknieciu_aktualizacja_i_uruchomienie_sa_odrzucone(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    assert centrum.client.post("/api/shutdown").status_code == 202

    update = centrum.client.post("/api/tool-update")
    run = centrum.start(dry_run=True)

    closing = "Centrum rozliczeń się zamyka. Kliknij skrót „Centrum rozliczeń” na pulpicie, potem"
    assert (update.status_code, update.json()) == (409, {"message": f"{closing} zaktualizuj narzędzie."})
    assert (run.status_code, run.json()) == (409, {"message": f"{closing} uruchom proces."})
    assert repository.head() == before
    assert "aktualizacja-start" not in log_events(centrum)


def test_nieprzewidziana_porazka_daje_komunikat_a_klon_zostaje_bez_zmian(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    running = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    # Gałąź main bez commitu: Git nie poda commitu narzędzia, czego aktualizacja nie przewiduje.
    repository.in_clone("update-ref", "-d", "refs/heads/main")

    view = update_until_done(centrum)

    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
            "where": "narzędzie na tym komputerze",
            "action": (
                "Narzędzie działa dalej w poprzedniej wersji. Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
                "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."
            ),
        },
        "next_action": "retry",
        "report": {"state": "ready"},
        "after_restart": False,
    }
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    # Commit przed aktualizacją to ten, z którego działa Centrum, choć Git go już nie poda.
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NIEOCZEKIWANY_BLAD przed={running} po=- biblioteki=nie"
    ]
    assert centrum.client.post("/api/tool-update").status_code == 202


def test_karta_widzi_porazke_dopiero_gdy_ponowne_klikniecie_jest_przyjete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    repository.in_clone("update-ref", "-d", "refs/heads/main")
    remove_tree = shutil.rmtree

    def slow_cleanup(path: Any, *args: Any, **kwargs: Any) -> None:
        # Sprzątanie po aktualizacji bywa wolne (antywirus, OneDrive); tata może kliknąć w jego trakcie.
        time.sleep(0.3)
        remove_tree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", slow_cleanup)

    failed = update_until_done(centrum)
    again = centrum.client.post("/api/tool-update")
    tool_update_until(centrum, lambda view: view["state"] != "running")

    assert failed["state"] == "failed"
    assert again.status_code == 202, again.json()

STILL_WORKS = "Narzędzie działa dalej w poprzedniej wersji."
TO_MAKS = f"{STILL_WORKS} Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."


@contextmanager
def github_out_of_reach(repository: ToolRepository) -> Iterator[None]:
    """Lokalny „origin” poza zasięgiem, jak GitHub bez internetu, aż internet wróci."""

    away = repository.origin.with_name("origin-poza-zasiegiem.git")
    repository.origin.rename(away)
    try:
        yield
    finally:
        away.rename(repository.origin)


def test_porazka_aktualizacji_karta_dostaje_jako_komunikat_w_trzech_czesciach_a_po_powrocie_internetu_sie_udaje(
    tmp_path: Path,
) -> None:
    # Reguły porażek są w ``test_aktualizacja_narzedzia.py``; tu jedna zamiana kodu na Komunikat karty.
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})

    with github_out_of_reach(repository):
        view = update_until_done(centrum)
    offline_head = repository.head()
    retried = update_until_done(centrum)

    what = "Nie zaktualizowano narzędzia: brak połączenia z GitHubem."
    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": what,
            "where": "narzędzie na tym komputerze",
            "action": f"{STILL_WORKS} Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz.",
        },
        "next_action": "retry",
        "report": {"state": "ready"},
        "after_restart": False,
    }
    assert view["draft"]["title"] == f"BRAK_POLACZENIA: {what}"
    assert offline_head == before
    assert retried == {"state": "running", "step": "restarting"}
    assert ([restart.after for restart in centrum.surroundings.restarts], repository.head()) == ([newest], newest)
    # Koniec udanej aktualizacji zapisze nowe Centrum, z pliku wyniku od opiekuna.
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=BRAK_POLACZENIA przed={before} po=- biblioteki=nie"]


def send_report(centrum: PreparingCentrum) -> dict[str, Any]:
    response = centrum.client.post("/api/tool-update/report")
    assert response.status_code == 200, response.json()
    state: dict[str, Any] = response.json()
    return state


def test_zgloszenie_nieudanej_aktualizacji_ma_te_same_fakty_co_dziennik(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    write_report_key(centrum.tool)
    before = repository.head()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    repository.in_clone("checkout", "--quiet", "-b", "proba-maksa")
    preview = update_until_done(centrum)["draft"]

    state = send_report(centrum)

    assert state == {"state": "sent"}
    [report] = centrum.surroundings.report_box.sent
    assert {"title": report.title, "body": report.body} == preview
    assert report.title == "INNA_GALAZ: Nie zaktualizowano narzędzia: na tym komputerze jest inna gałąź narzędzia niż main."
    body = report.body
    fingerprint = re.search(r"^- Odcisk problemu: ([0-9a-f]{16})$", body, re.MULTILINE)
    assert fingerprint is not None
    head, log_block = body.split("## Dziennik Centrum rozliczeń\n")
    at = settings_changed_at(centrum)
    assert head.splitlines() == [
        "Zgłoszenie z Centrum rozliczeń.",
        "",
        "## Komunikat",
        "",
        "- Kod: INNA_GALAZ",
        "- Co się stało: Nie zaktualizowano narzędzia: na tym komputerze jest inna gałąź narzędzia niż main.",
        "- Gdzie: narzędzie na tym komputerze",
        f"- Co zrobić: {TO_MAKS}",
        "",
        "## Aktualizacja narzędzia",
        "",
        "- Wynik: INNA_GALAZ",
        f"- Commit przed: {before}",
        "- Commit po: brak",
        "- Biblioteki instalowane: nie",
        "",
        "## Narzędzie",
        "",
        f"- Odcisk problemu: {fingerprint[1]}",
        "",
        "## Zmiany Ustawień (30 dni)",
        "",
        f"{at[0]} · foldery.folder_okresow: nie ustawiono → {centrum.fixture.periods_directory.name}",
        f"{at[1]} · foldery.rejestr_zlecen: nie ustawiono → {centrum.fixture.register_path.name}",
        "",
    ]
    log = centrum.log_path.read_text(encoding="utf-8").splitlines()
    started = next(line for line in log if " aktualizacja-start " in line)
    finished = next(line for line in log if " aktualizacja-koniec " in line)
    assert log_block.startswith("\n```text\n") and log_block.endswith(f"\n{started}\n{finished}\n```\n")
    assert re.search(r"fatal|error:|hint:|proba-maksa|origin\.git", body) is None
    assert centrum.client.get("/api/tool-update").json()["report"] == {"state": "sent"}
    assert "skrzynka-wyslano etykieta=zgloszenie okres=bez-okresu numer=1" in centrum.log_path.read_text(encoding="utf-8")


def update_with_slow_box(centrum: PreparingCentrum) -> dict[str, Any]:
    """Klika „Zaktualizuj narzędzie” jak karta, gdy skrzynka Zgłoszeń odpowiada po 1 s, jak GitHub.

    Karta czyta wynik, dopóki aktualizacja trwa, a pierwszy wynik to jedyny, który pokaże bez przeładowania.
    """

    box = centrum.surroundings.report_box
    box.search_hold = threading.Event()
    box.searching.clear()
    answer = threading.Timer(1, box.search_hold.set)
    try:
        started = centrum.client.post("/api/tool-update")
        assert started.status_code == 202, started.json()
        assert box.searching.wait(UPDATE_WAIT_S)
        answer.start()
        return tool_update_until(centrum, lambda view: view["state"] != "running")
    finally:
        answer.cancel()
        box.search_hold.set()


def test_druga_nieudana_aktualizacja_po_zamknieciu_zgloszenia_karta_od_razu_pozwala_wyslac_wlasne(
    tmp_path: Path,
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    with github_out_of_reach(repository):
        update_until_done(centrum)
        assert send_report(centrum) == {"state": "sent"}
        box.close(1)

        again = update_with_slow_box(centrum)
        state = send_report(centrum)

    assert (again["state"], again["report"], state) == ("failed", {"state": "ready"}, {"state": "sent"})
    assert [report.title.split(":")[0] for report in box.sent] == ["BRAK_POLACZENIA"] * 2
    assert "- Poprzednie Zgłoszenie: #1" in box.sent[1].body.splitlines()


def test_nieudana_aktualizacja_ze_zgloszeniem_otwartym_w_skrzynce_karta_od_razu_mowi_ze_czeka(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    with github_out_of_reach(repository):
        update_until_done(centrum)
        assert send_report(centrum) == {"state": "sent"}
        (tmp_path / "config" / DAD_CASES_FILE).unlink()  # jak Zgłoszenie wysłane z innego komputera
        centrum.restart()

        again = update_with_slow_box(centrum)
        # Nieudana Aktualizacja nie ma Diagnozy: jej powrót nie idzie do kolejki sam jak powrót Zatrzymania.
        before_send = [len(issue.comments) for issue in box.sent]
        state = send_report(centrum)

    # Przycisku nie ma; wysyłka z API dopisuje komentarz do otwartego Zgłoszenia zamiast zakładać drugie.
    assert (again["state"], again["report"], state) == ("failed", {"state": "waiting"}, {"state": "sent"})
    assert (before_send, len(box.sent)) == ([0], 1)


def test_zgloszenie_nieudanej_aktualizacji_bez_sieci_czeka_w_kolejce_i_wychodzi_samo(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    box.search_failure = Unreachable()
    repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    with github_out_of_reach(repository):
        preview = update_until_done(centrum)["draft"]
        state = send_report(centrum)
    box.search_failure = None
    centrum.surroundings.clock.advance(RETRY_S)

    assert state == {"state": "queued", "waits_for": "internet"}
    assert box.wait_until(lambda box: len(box.sent) == 1)
    assert [{"title": report.title, "body": report.body} for report in box.sent] == [preview]
    assert wait_for(lambda: centrum.client.get("/api/tool-update").json()["report"] == {"state": "sent"})


def test_zgloszenie_bez_nieudanej_aktualizacji_jest_odrzucone(tmp_path: Path) -> None:
    centrum, _ = updating_centrum(tmp_path)
    write_report_key(centrum.tool)
    assert update_until_done(centrum)["state"] == "up_to_date"

    refused = centrum.client.post("/api/tool-update/report")

    assert refused.status_code == 409
    assert centrum.surroundings.report_box.sent == []


def test_nowe_biblioteki_karta_widzi_krok_instalowania_a_dziennik_zapisuje_instalacje(tmp_path: Path) -> None:
    hold = threading.Event()
    centrum, repository = updating_centrum(tmp_path, installer=FakeInstaller(hold=hold))
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS})
    assert centrum.client.post("/api/tool-update").status_code == 202

    installing = tool_update_until(centrum, lambda view: view.get("step") == "installing")
    hold.set()
    view = tool_update_done(centrum)

    assert installing == {"state": "running", "step": "installing"}
    assert view == {"state": "running", "step": "restarting"}
    [restart] = centrum.surroundings.restarts
    # Opiekun przekaże nowemu Centrum, że instalowano biblioteki; koniec aktualizacji zapisze ono.
    assert (restart.before, restart.after, restart.installed) == (before, newest, True)


def test_stara_wersja_po_cofnieciu_pokazuje_komunikat_bez_czekania_na_skrzynke_zgloszen(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    write_report_key(centrum.tool)
    box = centrum.surroundings.report_box
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    result = tmp_path / "config" / RESULT_FILE
    write_result(result, UpdateResult(NEW_VERSION_FAILED, before, newest))
    centrum.restart()
    first = tool_update_until(centrum, lambda view: view["report"] == {"state": "ready"})
    assert send_report(centrum) == {"state": "sent"}
    box.close(1)  # Maks naprawił, ale nowa wersja znowu nie wystartowała
    write_result(result, UpdateResult(NEW_VERSION_FAILED, before, newest))
    box.search_hold = threading.Event()
    release = threading.Timer(8, box.search_hold.set)  # bez osobnego wątku start czekałby na skrzynkę
    release.start()

    try:
        centrum.restart()
        box_answered = box.search_hold.is_set()
        while_box_silent = centrum.client.get("/api/tool-update").json()
    finally:
        box.search_hold.set()
        release.cancel()
    answered = tool_update_until(centrum, lambda view: view["report"] == {"state": "ready"})

    assert not box_answered
    assert {key: value for key, value in first.items() if key != "draft"} == {
        "state": "failed",
        "message": {"what": "Nowa wersja narzędzia nie wystartowała.", "where": "narzędzie na tym komputerze", "action": TO_MAKS},
        "next_action": "report",
        "report": {"state": "ready"},
        "after_restart": True,
    }
    assert first["draft"]["title"] == "NOWA_WERSJA_NIE_WYSTARTOWALA: Nowa wersja narzędzia nie wystartowała."
    assert (while_box_silent["state"], while_box_silent["report"]) == ("failed", {"state": "waiting"})
    assert answered["message"] == first["message"]
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie"
    ] * 2


def guardian_finishes(centrum: PreparingCentrum, code: str, *, rolled_back: bool = False) -> None:
    """Opiekun ponownego startu po ostatnim kliknięciu."""

    assert centrum.surroundings.restarts, (
        f"Aktualizacja skończyła się bez ponownego startu: {centrum.client.get('/api/tool-update').json()}, "
        f"dziennik: {centrum.log_path.read_text(encoding='utf-8')}"
    )
    restart = centrum.surroundings.restarts[-1]
    clone = ToolClone(restart.root)
    if rolled_back:
        clone.roll_back()
    else:
        clone.confirm_update()
    write_result(restart.result, UpdateResult(code, restart.before, restart.after, restart.installed))


def disk_refuses_removing(monkeypatch: pytest.MonkeyPatch, refused: Path) -> None:
    """Dysk (np. OneDrive albo antywirus) nie pozwala usunąć pliku ``refused``; inne pliki usuwa jak zwykle."""

    unlink = Path.unlink

    def refusing(self: Path, missing_ok: bool = False) -> None:
        if self == refused:
            raise PermissionError(13, "Odmowa dostępu")
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", refusing)


@pytest.mark.parametrize("from_running", [True, False], ids=["z dzialajacej", "z innej"])
def test_wynik_ok_przy_dzialajacej_poprzedniej_wersji_to_porazka_nieoczekiwana_z_rada_i_zgloszeniem(
    tmp_path: Path, from_running: bool
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    running = repository.head()
    second = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    # „ok” z innej wersji: Maks przestawił klon, zanim przeczytało je Centrum.
    before, newest = (running, second) if from_running else (second, repository.publish({"src/x.py": "WERSJA = 3\n"}))
    # Opiekun zapisał „ok”, komputer zgasł, skrót cofnął klon, a dysk odmówił mu zapisu porażki (#490).
    write_result(tmp_path / "config" / RESULT_FILE, UpdateResult(UPDATED, before, newest))

    centrum.restart()
    view = centrum.client.get("/api/tool-update").json()

    assert repository.head() == running
    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
            "where": "narzędzie na tym komputerze",
            "action": f"{STILL_WORKS} Kliknij „Zaktualizuj narzędzie” jeszcze raz. "
            "Jeśli komunikat wraca, kliknij „Wyślij do Maksa”.",
        },
        "next_action": "retry",
        "report": view.get("report"),
        "after_restart": True,
    }
    assert view["draft"]["title"] == "NIEOCZEKIWANY_BLAD: Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu."
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=nie"
    ]
    assert tool_on_configuration(centrum)["commit"] == running[:7]


def test_wynik_ok_bez_gita_zostaje_ok(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    write_result(tmp_path / "config" / RESULT_FILE, UpdateResult(UPDATED, before, newest))
    (repository.clone / ".git").rename(repository.clone / "git-poza-klonem")

    centrum.restart()

    assert tool_on_configuration(centrum)["commit"] is None
    assert centrum.client.get("/api/tool-update").json() == {"state": "updated"}
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={before} po={newest} biblioteki=nie"]


def test_dziennik_rozpoznaje_zapisany_wynik_aktualizacji_bez_commitow(tmp_path: Path) -> None:
    log = CentrumLog(tmp_path / "centrum.log")
    log.update_started(before=None)
    awaited = log.update_awaits(result=NEW_VERSION_FAILED, before=None, after=None)

    log.update_finished(result=NEW_VERSION_FAILED, before=None, after=None, installed=False)

    assert awaited
    assert not log.update_awaits(result=NEW_VERSION_FAILED, before=None, after=None)
    # Koniec z porażką już zgłosił wynik tych commitów, także gdy plik mówi co innego (#491).
    assert not log.update_awaits(result=UNEXPECTED, before=None, after=None)


@pytest.mark.parametrize(
    ("finished", "awaited"),
    # Porażka od opiekuna i każda, którą kończy się w Centrum kliknięcie z przesuniętym klonem (te same commity).
    [(UPDATED, True), (NEW_VERSION_FAILED, False), (UNEXPECTED, False), (ROLLBACK_FAILED, False), (LIBRARIES_FAILED, False)],
    ids=["po ok nowej wersji", "po porazce", "po innej porazce", "po nieudanym cofnieciu", "po nieudanej instalacji"],
)
def test_dziennik_po_koncu_z_tymi_samymi_commitami_czeka_tylko_na_porazke_po_ok_nowej_wersji(
    tmp_path: Path, finished: str, awaited: bool
) -> None:
    log = CentrumLog(tmp_path / "centrum.log")
    log.update_started(before="a" * 40)
    log.update_finished(result=finished, before="a" * 40, after="b" * 40, installed=False)

    assert log.update_awaits(result=NEW_VERSION_FAILED, before="a" * 40, after="b" * 40) is awaited
    # Wynik starszej Aktualizacji z tego samego commitu do innej wersji.
    assert not log.update_awaits(result=NEW_VERSION_FAILED, before="a" * 40, after="c" * 40)


def test_dziennik_pomija_wynik_starszej_aktualizacji_do_tej_samej_wersji_po_koncu_nowszej(tmp_path: Path) -> None:
    log = CentrumLog(tmp_path / "centrum.log")
    log.update_started(before="a" * 40)
    log.update_started(before="b" * 40)
    log.update_finished(result=UPDATED, before="b" * 40, after="c" * 40, installed=False)

    # Plik wyniku z pierwszej Aktualizacji (z „a” do tego samego „c”), który dysk nie dał usunąć.
    assert not log.update_awaits(result=NEW_VERSION_FAILED, before="a" * 40, after="c" * 40)


def test_wynik_aktualizacji_trafia_na_karte_gdy_dziennika_nie_da_sie_przeczytac(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    write_result(tmp_path / "config" / RESULT_FILE, UpdateResult(NEW_VERSION_FAILED, before, newest))
    # Na miejscu dziennika stoi folder: żaden system nie da go przeczytać jak pliku.
    centrum.log_path.unlink(missing_ok=True)
    centrum.log_path.mkdir(parents=True, exist_ok=True)

    centrum.restart()
    view = centrum.client.get("/api/tool-update").json()

    assert (view["state"], view["message"]["what"]) == ("failed", "Nowa wersja narzędzia nie wystartowała.")
    assert view["report"] == {"state": "ready"}
    assert view["draft"]["title"] == "NOWA_WERSJA_NIE_WYSTARTOWALA: Nowa wersja narzędzia nie wystartowała."


@pytest.mark.parametrize(
    ("code", "shown", "next_action"),
    [
        (NO_GIT, NO_GIT, "report"),
        (NO_CONNECTION, NO_CONNECTION, "retry"),
        (LOGIN, LOGIN, "report"),
        (OTHER_BRANCH, OTHER_BRANCH, "report"),
        (LOCAL_CHANGES, LOCAL_CHANGES, "report"),
        (UNEXPECTED, UNEXPECTED, "retry"),
        (LIBRARIES_FAILED, LIBRARIES_FAILED, "retry"),
        (NEW_VERSION_FAILED, NEW_VERSION_FAILED, "report"),
        (ROLLBACK_FAILED, ROLLBACK_FAILED, "retry"),
        ("KOD_Z_INNEJ_WERSJI", UNEXPECTED, "retry"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_karta_porazki_mowi_czy_tata_klika_jeszcze_raz_czy_przekazuje_sprawe_maksowi(
    tmp_path: Path, code: str, shown: str, next_action: str
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    write_result(tmp_path / "config" / RESULT_FILE, UpdateResult(code, repository.head(), None))

    centrum.restart()
    view = centrum.client.get("/api/tool-update").json()

    # Kod Komunikatu na karcie to początek tytułu Zgłoszenia; nieznany kod to porażka nieoczekiwana.
    assert (view["state"], view["draft"]["title"].split(":")[0], view["next_action"]) == ("failed", shown, next_action)


def test_zgloszony_wynik_nie_wraca_gdy_dysk_nie_pozwala_usunac_jego_pliku(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    guardian_finishes(centrum, UPDATED)
    result = tmp_path / "config" / RESULT_FILE
    disk_refuses_removing(monkeypatch, result)

    cards = []
    for _ in range(3):
        centrum.restart()
        cards.append(centrum.client.get("/api/tool-update").json())

    kept = result.exists()
    monkeypatch.undo()  # dysk znowu pozwala usuwać
    centrum.restart()

    assert cards == [{"state": "updated"}, {"state": "idle"}, {"state": "idle"}]
    assert kept
    assert not result.exists()
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={before} po={newest} biblioteki=nie"]
    assert log_entries(centrum, "aktualizacja-wynik-zostaje") == ["typ=PermissionError"]


def test_zgloszenie_po_kolejnych_startach_ma_jeden_koniec_aktualizacji_a_stary_wynik_nie_wraca_po_nowej_porazce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    guardian_finishes(centrum, NEW_VERSION_FAILED, rolled_back=True)
    disk_refuses_removing(monkeypatch, tmp_path / "config" / RESULT_FILE)
    cards = []
    for _ in range(3):
        centrum.restart()
        cards.append(centrum.client.get("/api/tool-update").json()["state"])

    with github_out_of_reach(repository):
        draft = update_until_done(centrum)["draft"]["body"]
    centrum.restart()  # plik wyniku dalej leży, a ostatni koniec ma ten sam commit przed

    finished = [
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie",
        f"wynik=BRAK_POLACZENIA przed={before} po=- biblioteki=nie",
    ]
    assert cards == ["failed", "idle", "idle"]
    assert re.findall(r" aktualizacja-koniec (.*)", draft) == finished
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}
    assert log_entries(centrum, "aktualizacja-koniec") == finished


def test_zgloszony_wynik_nie_wraca_po_porazce_kolejnego_klikniecia_z_tymi_samymi_commitami(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = FakeInstaller()
    centrum, repository = updating_centrum(tmp_path, installer=installer)
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS, "src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    guardian_finishes(centrum, NEW_VERSION_FAILED, rolled_back=True)
    disk_refuses_removing(monkeypatch, tmp_path / "config" / RESULT_FILE)
    centrum.restart()
    reported = centrum.client.get("/api/tool-update").json()["state"]
    installer.succeeds = False

    clicked = update_until_result(centrum)
    centrum.restart()  # plik wyniku dalej leży, a ostatni koniec ma te same commity i inny wynik
    view = centrum.client.get("/api/tool-update").json()

    assert reported == "failed"
    assert clicked["state"] == "failed"
    assert view == {"state": "idle"}
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=tak",
        f"wynik={LIBRARIES_FAILED} przed={before} po={newest} biblioteki=tak",
    ]


@pytest.mark.parametrize("new_version_logged", [True, False], ids=["po ok nowej wersji", "bez konca nowej wersji"])
def test_ok_przy_starej_wersji_gdy_dysk_nie_usuwa_wyniku_zglasza_porazke_raz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_version_logged: bool
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    restart = centrum.surroundings.restarts[-1]
    write_result(restart.result, UpdateResult(UPDATED, restart.before, restart.after))
    disk_refuses_removing(monkeypatch, restart.result)
    if new_version_logged:
        centrum.restart()  # nowa wersja zapisała „ok” w dzienniku, dysk nie dał usunąć pliku, a potem zgasła
    # Skrót albo opiekun cofnął klon, a dysk odmówił mu zapisu porażki: „ok” zostaje przy starej wersji (#490).
    ToolClone(restart.root).roll_back()

    cards = []
    for _ in range(3):
        centrum.restart()
        cards.append(centrum.client.get("/api/tool-update").json()["state"])

    assert repository.head() == before
    assert cards == ["failed", "idle", "idle"]
    assert log_entries(centrum, "aktualizacja-koniec") == [
        *([f"wynik=ok przed={before} po={newest} biblioteki=nie"] if new_version_logged else []),
        f"wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=nie",
    ]


class _AnsweringCentrum:
    """Proces nowego Centrum od opiekuna, który działa."""

    def poll(self) -> None:
        return None


def disk_refuses_replacing(monkeypatch: pytest.MonkeyPatch, refused: Path) -> None:
    """Dysk nie pozwala podmienić pliku ``refused`` (``os.replace`` w ``write_result``); inne pliki jak zwykle."""

    replace = os.replace

    def refusing(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target) == refused:
            raise PermissionError(13, "Odmowa dostępu")
        replace(source, target)

    monkeypatch.setattr(os, "replace", refusing)


def test_nowa_dzialajaca_wersja_po_dwoch_odmowach_dysku_nie_pokazuje_porazki_poprzedniej_proby(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    result = tmp_path / "config" / RESULT_FILE
    dialogs: list[str] = []
    # Pierwsza próba: stare Centrum nie oddaje portu, opiekun cofa klon i zapisuje „nowa wersja nie wystartowała”.
    update_until_done(centrum)
    restart = centrum.surroundings.restarts[-1]
    with monkeypatch.context() as patched:
        patched.setattr(restart_guardian, "_port_released", lambda port: False)
        patched.setattr(restart_guardian, "_runs", lambda port, commit: False)
        assert restart_guardian.main(restart.arguments(), show_problem=lambda title, text: dialogs.append(text)) == 1
    # Tata uruchamia skrót: stara wersja pokazuje porażkę, a dysk nie daje usunąć pliku wyniku.
    with monkeypatch.context() as patched:
        disk_refuses_removing(patched, result)
        centrum.restart()
        old_card = centrum.client.get("/api/tool-update").json()
    # Druga próba się udaje, ale dysk nie przyjmuje „ok” od opiekuna (#725).
    update_until_done(centrum)
    restart = centrum.surroundings.restarts[-1]
    with monkeypatch.context() as patched:
        patched.setattr(restart_guardian, "_port_released", lambda port: True)
        patched.setattr(restart_guardian, "_start_centrum", lambda restart: _AnsweringCentrum())
        patched.setattr(restart_guardian, "_answers", lambda new, port, commit: commit == newest)
        disk_refuses_replacing(patched, result)
        assert restart_guardian.main(restart.arguments(), show_problem=lambda title, text: dialogs.append(text)) == 0

    centrum.restart()
    card = centrum.client.get("/api/tool-update").json()

    assert old_card["state"] == "failed"
    assert old_card["message"]["what"] == "Nowa wersja narzędzia nie wystartowała."
    assert repository.head() == newest
    assert ToolClone(repository.clone).interrupted_update() is None
    assert card == {"state": "idle"}
    assert not result.exists()
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie"
    ]
    assert log_entries(centrum, "aktualizacja-wynik-stary") == [
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest}"
    ]


@pytest.mark.parametrize("code", [NEW_VERSION_FAILED, UNEXPECTED, ROLLBACK_FAILED])
def test_porazka_z_pliku_wyniku_przy_wersji_innej_niz_sprzed_aktualizacji_jest_stara_i_karta_jej_nie_pokazuje(
    tmp_path: Path, code: str
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    running = repository.head()
    other = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    # Wynik próby z innej wersji niż działająca (np. skrót cofnął klon po wyłączeniu komputera, a potem kolejna
    # Aktualizacja się udała, choć dysk nie przyjął jej „ok”).
    write_result(tmp_path / "config" / RESULT_FILE, UpdateResult(code, other, running))

    centrum.restart()

    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}
    assert not (tmp_path / "config" / RESULT_FILE).exists()
    assert log_entries(centrum, "aktualizacja-koniec") == []
    assert log_entries(centrum, "aktualizacja-wynik-stary") == [f"wynik={code} przed={other} po={running}"]


def test_urwany_wpis_na_koncu_dziennika_nie_zatrzymuje_startu_z_wynikiem_aktualizacji(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    CentrumLog(centrum.log_path).update_started(before=before)
    # Komputer zgasł w połowie zapisu: dziennik kończy się pierwszym bajtem dwubajtowej litery, bez końca linii.
    with centrum.log_path.open("ab") as log:
        log.write("2026-10-26T10:00:00+01:00 pomiar widok=Konfiguracja-Ł".encode()[:-1])
    write_result(tmp_path / "config" / RESULT_FILE, UpdateResult(NEW_VERSION_FAILED, before, newest))

    centrum.restart()
    view = centrum.client.get("/api/tool-update").json()

    assert (view["state"], view["message"]["what"]) == ("failed", "Nowa wersja narzędzia nie wystartowała.")
    assert re.findall(rb" aktualizacja-koniec ([^\r\n]*)", centrum.log_path.read_bytes()) == [
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie".encode()
    ]


def test_po_udanej_i_nieudanej_aktualizacji_karta_pokazuje_porazke_nowszej_nigdy_ok_starszej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    first = repository.head()
    second = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    guardian_finishes(centrum, UPDATED)
    disk_refuses_removing(monkeypatch, tmp_path / "config" / RESULT_FILE)
    centrum.restart()
    updated = centrum.client.get("/api/tool-update").json()
    third = repository.publish({"src/narzedzie.py": "WERSJA = 3\n"})

    update_until_done(centrum)
    guardian_finishes(centrum, NEW_VERSION_FAILED, rolled_back=True)
    centrum.restart()
    view = centrum.client.get("/api/tool-update").json()
    centrum.restart()

    assert updated == {"state": "updated"}
    assert (view["state"], view["message"]["what"]) == ("failed", "Nowa wersja narzędzia nie wystartowała.")
    assert repository.head() == second
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=ok przed={first} po={second} biblioteki=nie",
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={second} po={third} biblioteki=nie",
    ]
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}


def test_ok_starszej_aktualizacji_po_starcie_nowszej_nie_trafia_do_karty_ani_do_dziennika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum, repository = updating_centrum(tmp_path)
    first = repository.head()
    second = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    guardian_finishes(centrum, UPDATED)
    result = tmp_path / "config" / RESULT_FILE
    disk_refuses_removing(monkeypatch, result)
    centrum.restart()
    repository.publish({"src/narzedzie.py": "WERSJA = 3\n"})
    update_until_done(centrum)
    # Centrum zgasło przy ponownym starcie, zanim opiekun cokolwiek zapisał; skrót cofnął klon do drugiej wersji.
    ToolClone(repository.clone).confirm_update()
    repository.in_clone("reset", "--quiet", "--keep", second)

    centrum.restart()

    assert read_result(result) == UpdateResult(UPDATED, first, second)
    assert centrum.client.get("/api/tool-update").json() == {"state": "idle"}
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={first} po={second} biblioteki=nie"]
    assert log_entries(centrum, "aktualizacja-start")[-1] == f"przed={second}"


def test_porazka_od_opiekuna_po_ok_nowej_wersji_ktora_potem_nie_odpowiedziala_trafia_do_karty(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    restart = centrum.surroundings.restarts[-1]
    write_result(restart.result, UpdateResult(UPDATED, restart.before, restart.after))
    centrum.restart()  # nowa wersja zapisała „ok” w dzienniku, a potem nie odpowiedziała na /api/health
    guardian_finishes(centrum, NEW_VERSION_FAILED, rolled_back=True)

    centrum.restart()
    view = centrum.client.get("/api/tool-update").json()

    assert (view["state"], view["message"]["what"]) == ("failed", "Nowa wersja narzędzia nie wystartowała.")
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=ok przed={before} po={newest} biblioteki=nie",
        f"wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie",
    ]


@pytest.mark.parametrize("log", ["bez wpisu startu", "bez dziennika"])
def test_wynik_bez_startu_aktualizacji_w_dzienniku_trafia_do_dziennika_i_karty(tmp_path: Path, log: str) -> None:
    centrum, repository = updating_centrum(tmp_path)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    update_until_done(centrum)
    guardian_finishes(centrum, UPDATED)
    lines = centrum.log_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if log == "bez dziennika":
        centrum.log_path.unlink()
    else:
        centrum.log_path.write_text("".join(line for line in lines if " aktualizacja-start " not in line), "utf-8")

    centrum.restart()

    assert centrum.client.get("/api/tool-update").json() == {"state": "updated"}
    assert log_entries(centrum, "aktualizacja-koniec") == [f"wynik=ok przed={before} po={newest} biblioteki=nie"]


def nothing(repository: ToolRepository) -> None:
    pass


def test_gdy_opiekun_nie_wystartuje_klon_wraca_do_poprzedniej_wersji_a_karta_dostaje_komunikat(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path, guardian_failure=nothing)
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS, "src/narzedzie.py": "WERSJA = 2\n"})

    view = update_until_result(centrum)

    assert (view["state"], view["message"]["what"], view["next_action"], view["after_restart"]) == (
        "failed",
        "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
        "retry",
        False,
    )
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert centrum.surroundings.restarts == []
    assert "zamkniecie" not in log_events(centrum)
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=tak"
    ]
    assert centrum.start(dry_run=True).status_code == 200


def changes_new_version_file(repository: ToolRepository) -> None:
    repository.write("src/narzedzie.py", "WERSJA = 2  # zmienione, zanim opiekun miał wystartować\n")


def test_gdy_cofniecie_sie_nie_uda_karta_nie_mowi_ze_narzedzie_dziala_w_poprzedniej_wersji(tmp_path: Path) -> None:
    centrum, repository = updating_centrum(tmp_path, guardian_failure=changes_new_version_file)
    before = repository.head()
    newest = repository.publish({"requirements.txt": NEW_REQUIREMENTS, "src/narzedzie.py": "WERSJA = 2\n"})

    view = update_until_result(centrum)

    assert {key: value for key, value in view.items() if key != "draft"} == {
        "state": "failed",
        "message": {
            "what": "Aktualizacja narzędzia się nie udała i nie dało się przywrócić poprzedniej wersji.",
            "where": "narzędzie na tym komputerze",
            "action": "Kliknij „Zaktualizuj narzędzie” jeszcze raz. Jeśli komunikat wraca, kliknij „Wyślij do Maksa”.",
        },
        "next_action": "retry",
        "report": {"state": "ready"},
        "after_restart": False,
    }
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=COFNIECIE_NIEUDANE przed={before} po={newest} biblioteki=tak"
    ]
    interrupted = ToolClone(repository.clone).interrupted_update()
    assert interrupted is not None
    assert (interrupted.before, interrupted.after) == (before, newest)


def test_po_nieudanym_cofnieciu_kolejne_klikniecie_nie_mowi_ze_narzedzie_jest_aktualne_i_cofa_klon(
    tmp_path: Path,
) -> None:
    lock_once = threading.Event()

    def locks_index_once(repository: ToolRepository) -> None:
        if not lock_once.is_set():
            lock_once.set()
            (repository.clone / ".git" / "index.lock").touch()

    centrum, repository = updating_centrum(tmp_path, guardian_failure=locks_index_once)
    before = repository.head()
    newest = repository.publish({"src/narzedzie.py": "WERSJA = 2\n"})
    failed = update_until_result(centrum)
    (repository.clone / ".git" / "index.lock").unlink()

    view = update_until_result(centrum)

    assert failed["message"]["what"] == "Aktualizacja narzędzia się nie udała i nie dało się przywrócić poprzedniej wersji."
    assert (view["state"], view.get("message", {}).get("what")) == (
        "failed",
        "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
    )
    assert repository.head() == before
    assert repository.read("src/narzedzie.py") == "WERSJA = 1\n"
    assert ToolClone(repository.clone).interrupted_update() is None
    assert log_entries(centrum, "aktualizacja-koniec") == [
        f"wynik=COFNIECIE_NIEUDANE przed={before} po={newest} biblioteki=nie",
        f"wynik=NIEOCZEKIWANY_BLAD przed={before} po={newest} biblioteki=nie",
    ]
