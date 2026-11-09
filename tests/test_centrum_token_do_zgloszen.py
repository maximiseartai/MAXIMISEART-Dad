"""Wysyłka, która nie wyjdzie bez Maksa (Q5, Q17): Token do Zgłoszeń i treść odrzucona przez Skrzynkę Zgłoszeń.

Uwaga taty i Zgłoszenie mówią przez HTTP API, na co czekają w Kolejce wysyłki, a Powiadomienia mówią to samo. Bez
Tokenu do Zgłoszeń albo z odrzuconym czekają na token, nie na internet. Treść, którą Skrzynka odrzuciła, nie czeka na
nic, co naprawi tata albo internet: kolejka ponawia ją dopiero przy następnym starcie Centrum.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rozliczenia.centrum.outbox import RETRY_S
from rozliczenia.centrum.report_box import Rejected, Unreachable

from tests.fixtures.centrum import (
    QUEUED_FOR_INTERNET,
    QUEUED_FOR_KEY,
    REJECTED,
    SENT,
    Centrum,
    ToolDirectory,
    case_states,
    centrum,
    write_report_key,
)
from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, stopped_for_maks
from tests.fixtures.potomne import wait_for

KEY = "github_pat_SYNTETYCZNY_TOKEN_DO_ZGLOSZEN"


def queued(tmp_path: Path, label: str) -> list[Path]:
    return sorted(ToolDirectory(tmp_path).queue.glob(f"*-{label}-*.json"))


def note_states(started: Centrum) -> dict[str, dict[str, str]]:
    """Stan każdej Uwagi taty w Powiadomieniach, po jej tytule."""

    items = started.client.get("/api/notifications").json()["items"]
    return {item["title"]: item["state"] for item in items if item["kind"] == "uwaga"}


def send_note(started: Centrum, title: str) -> dict[str, Any]:
    response = started.client.post("/api/dad-notes", json={"title": title})
    assert response.status_code == 200, response.json()
    state: dict[str, Any] = response.json()
    return state


def test_uwaga_odrzucona_przez_skrzynke_nie_czeka_na_internet_a_nastepna_wychodzi_w_tym_samym_przejsciu(
    tmp_path: Path,
) -> None:
    started = centrum(tmp_path)
    assert send_note(started, "Pierwsza") == QUEUED_FOR_KEY
    assert send_note(started, "Druga") == QUEUED_FOR_KEY
    assert note_states(started) == {"Pierwsza": QUEUED_FOR_KEY, "Druga": QUEUED_FOR_KEY}

    write_report_key(ToolDirectory(tmp_path), KEY)
    started.report_box.outcomes.append(Rejected())
    started.clock.advance(RETRY_S)

    assert started.report_box.wait_until(lambda box: len(box.issues_with("uwaga-taty")) == 1)
    [sent] = started.report_box.issues_with("uwaga-taty")
    assert sent.title == "Druga"
    assert wait_for(lambda: note_states(started) == {"Pierwsza": REJECTED, "Druga": SENT})
    # Kolejka usuwa plik dostarczonej Uwagi po zapisaniu jej stanu, a na Windows chwilę później.
    assert wait_for(lambda: len(queued(tmp_path, "uwaga-taty")) == 1)
    assert "przyczyna=odmowa-tresci" in started.log_path.read_text(encoding="utf-8")


def test_uwaga_odrzucona_przy_wyslij_mowi_o_tym_od_razu_a_po_starcie_centrum_kolejka_probuje_jeszcze_raz(
    tmp_path: Path,
) -> None:
    write_report_key(ToolDirectory(tmp_path), KEY)
    started = centrum(tmp_path)
    started.report_box.outcomes.append(Rejected())

    assert send_note(started, "Odrzucona") == REJECTED
    assert note_states(started) == {"Odrzucona": REJECTED}
    assert started.report_box.issues == []

    restarted = centrum(tmp_path)
    with restarted.client:
        assert restarted.report_box.wait_until(lambda box: len(box.issues_with("uwaga-taty")) == 1)
        assert wait_for(lambda: note_states(restarted) == {"Odrzucona": SENT})


def test_uwaga_z_tokenem_bez_sieci_czeka_na_internet_takze_w_powiadomieniach(tmp_path: Path) -> None:
    write_report_key(ToolDirectory(tmp_path), KEY)
    started = centrum(tmp_path)
    # Bez sieci Skrzynka nie sprawdziła jeszcze tokenu, więc Centrum nie wie, czy działa, i czeka na internet.
    started.report_box.search_failure = Unreachable()
    started.report_box.outcomes.append(Unreachable())

    assert send_note(started, "Bez sieci") == QUEUED_FOR_INTERNET
    assert note_states(started) == {"Bez sieci": QUEUED_FOR_INTERNET}


def report(centrum: PreparingCentrum, run_id: str) -> dict[str, Any]:
    """„Wyślij do Maksa” po Diagnozie Zatrzymania ``run_id``."""

    assert centrum.client.post(f"/api/runs/{run_id}/diagnosis").status_code == 200
    response = centrum.client.post(f"/api/runs/{run_id}/report")
    assert response.status_code == 200, response.json()
    state: dict[str, Any] = response.json()
    return state


def current_report(centrum: PreparingCentrum) -> object:
    return centrum.client.get("/api/runs/current").json()["result"]["report"]


def test_zgloszenie_odrzucone_przez_skrzynke_kaze_skontaktowac_sie_z_maksem_zamiast_czekac_na_internet(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path), KEY)
    box = centrum.surroundings.report_box
    run_id = stopped_for_maks(centrum)
    box.outcomes.append(Rejected())

    assert report(centrum, run_id) == REJECTED
    assert centrum.client.post(f"/api/runs/{run_id}/report").json() == REJECTED
    assert current_report(centrum) == REJECTED
    assert case_states(centrum.client, "zgloszenie") == [REJECTED]
    assert box.sent == []
    assert len(queued(tmp_path, "zgloszenie")) == 1

    again = stopped_for_maks(centrum)
    assert again != run_id
    assert current_report(centrum) == REJECTED


def test_zgloszenie_czekajace_na_token_staje_sie_odrzucone_gdy_skrzynka_odrzuci_tresc_po_wpisaniu_tokenu(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path)
    box = centrum.surroundings.report_box
    run_id = stopped_for_maks(centrum)
    assert report(centrum, run_id) == QUEUED_FOR_KEY
    assert case_states(centrum.client, "zgloszenie") == [QUEUED_FOR_KEY]

    write_report_key(ToolDirectory(tmp_path), KEY)
    box.outcomes.append(Rejected())
    centrum.surroundings.clock.advance(RETRY_S)

    assert wait_for(lambda: current_report(centrum) == REJECTED)
    assert case_states(centrum.client, "zgloszenie") == [REJECTED]
    assert box.sent == []


def test_odrzucona_tresc_zostaje_odrzucona_takze_gdy_potem_token_przestaje_dzialac(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    box = centrum.surroundings.report_box
    run_id = stopped_for_maks(centrum)
    write_report_key(ToolDirectory(tmp_path), KEY)
    box.outcomes.append(Rejected())
    assert report(centrum, run_id) == REJECTED

    # Token przestaje działać, ale odrzuconej treści i tak nie wyśle żaden token, więc tata dalej słyszy, że tego
    # Zgłoszenia nie da się wysłać.
    ToolDirectory(tmp_path).report_key.unlink()

    assert current_report(centrum) == REJECTED
    assert case_states(centrum.client, "zgloszenie") == [REJECTED]
