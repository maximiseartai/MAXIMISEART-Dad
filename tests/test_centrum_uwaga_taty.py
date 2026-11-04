"""Uwaga taty ogólna (ADR 0015, #318) przez HTTP API Centrum z fałszywą Skrzynką Zgłoszeń; bez prawdziwego GitHuba."""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import pytest

from rozliczenia.centrum.outbox import DELIVERY_WAIT_S, RETRY_S
from rozliczenia.centrum.report_box import Refused, SendOutcome, Unreachable

from tests.fixtures.centrum import TOOL_COMMIT, Centrum, FakeIssue, case_states, centrum, dad_cases
from tests.fixtures.centrum_intermax import ordering_centrum
from tests.fixtures.centrum_processes import preparing_centrum, run_to_end
from tests.fixtures.potomne import wait_for
from tests.fixtures.preparation import default_register_rows

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
TITLE = "Plik zbiorczy otwiera się długo"
BODY = "Od wczoraj Excel myśli przy nim minutę.\nInne pliki otwierają się od razu."
# Treść issue kończy się wersją narzędzia taty: pierwsze 7 znaków commitu, jak na Konfiguracji.
VERSION_LINE = "Uwaga ogólna · wersja narzędzia 3c1d0a9"


def with_key(tmp_path: Path) -> Centrum:
    started = centrum(tmp_path)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    return started


def notes(tmp_path: Path) -> list[dict[str, Any]]:
    return dad_cases(tmp_path / "config", "uwaga")


def queued(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "config" / "zgloszenia" / "kolejka").glob("*.json"))


def dad_note_issues(started: Centrum) -> list[FakeIssue]:
    return started.report_box.issues_with("uwaga-taty")


def test_uwaga_z_tytulem_i_trescia_to_jedno_issue_uwaga_taty_z_wersja_narzedzia(tmp_path: Path) -> None:
    started = with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})

    assert response.status_code == 200
    assert response.json() == {"state": "sent"}
    [issue] = started.report_box.issues
    assert (issue.label, issue.title, issue.body) == ("uwaga-taty", TITLE, f"{BODY}\n\n{VERSION_LINE}")
    [note] = notes(tmp_path)
    assert (note["title"], note["commit"], note["number"]) == (TITLE, TOOL_COMMIT, issue.number)
    assert BODY not in json.dumps(note, ensure_ascii=False)
    assert wait_for(lambda: queued(tmp_path) == [])


@pytest.mark.parametrize(
    ("text", "body"),
    [
        ({"title": f"  {TITLE}  ", "body": f"\n{BODY}\n\n"}, f"{BODY}\n\n{VERSION_LINE}"),
        ({"title": TITLE}, VERSION_LINE),
        ({"title": TITLE, "body": "  \n"}, VERSION_LINE),
    ],
    ids=["z-trescia", "bez-tresci", "tresc-z-samych-spacji"],
)
def test_podglad_maks_dostanie_to_dokladnie_wyslane_issue(tmp_path: Path, text: dict[str, str], body: str) -> None:
    started = with_key(tmp_path)

    draft = started.client.post("/api/dad-notes/draft", json=text)
    sent = started.client.post("/api/dad-notes", json=text)

    assert sent.json() == {"state": "sent"}
    [issue] = dad_note_issues(started)
    assert draft.status_code == 200
    assert draft.json() == {"title": issue.title, "body": issue.body} == {"title": TITLE, "body": body}


def test_uwaga_z_adresem_z_rejestru_telefonem_i_ulica_wychodzi_zamaskowana_z_uwaga_a_podglad_to_wyslane_issue(
    tmp_path: Path,
) -> None:
    address = "Syntetyczna Turkusowa 21/4 Kraków"
    rows = default_register_rows()
    rows[2] = {**(rows[2] or {}), "ADRES": address}
    started = preparing_centrum(tmp_path, rows)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    run_to_end(started, dry_run=True)
    text = {"title": f"Klient {address}", "body": "Dzwonił z +48 600 123 456, mieszka przy ul. Kwiatowa 5/3."}

    draft = started.client.post("/api/dad-notes/draft", json=text)
    sent = started.client.post("/api/dad-notes", json=text)

    assert sent.json() == {"state": "sent"}
    [issue] = started.surroundings.report_box.issues_with("uwaga-taty")
    assert draft.json() == {"title": issue.title, "body": issue.body} == {
        "title": "Klient [adres]",
        "body": "Dzwonił z [telefon], mieszka przy [ulica].\n"
        "Reguła danych: zamaskowano wartość kolumny ADRES w: tytuł Uwagi taty.\n\n"
        f"{VERSION_LINE}",
    }


def test_uwaga_po_uporzadkowaniu_intermax_nie_wynosi_adresu_ani_numeru_umowy_z_wklejonych_wierszy(tmp_path: Path) -> None:
    started = ordering_centrum(tmp_path)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    assert started.run_to_end()["result"]["result"] == "OK"

    sent = started.client.post("/api/dad-notes", json={"title": "Zlecenie Ulica 104, umowa UM-104"})

    assert sent.json() == {"state": "sent"}
    [issue] = started.surroundings.report_box.issues_with("uwaga-taty")
    assert (issue.title, issue.body.splitlines()[0]) == (
        "Zlecenie [adres], umowa [numer Orange]",
        "Reguła danych: zamaskowano wartość kolumny ADRES w: tytuł Uwagi taty.",
    )


def assert_nothing_sent(started: Centrum, tmp_path: Path) -> None:
    assert started.report_box.issues == []
    assert started.report_box.keys == []
    assert queued(tmp_path) == []
    assert notes(tmp_path) == []


@pytest.mark.parametrize("title", ["", "   \n"], ids=["pusty", "same-biale-znaki"])
def test_uwaga_bez_tytulu_jest_odrzucona(tmp_path: Path, title: str) -> None:
    started = with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": title, "body": BODY})

    assert response.status_code == 422
    assert_nothing_sent(started, tmp_path)


def test_tytul_uwagi_w_dwoch_liniach_jest_odrzucony(tmp_path: Path) -> None:
    started = with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": "Plik zbiorczy\notwiera się długo"})

    assert response.status_code == 422
    assert_nothing_sent(started, tmp_path)


@pytest.mark.parametrize(
    ("key", "outcome", "waits_for"),
    [(False, None, "key"), (True, Unreachable(), "internet"), (True, Refused(), "key")],
    ids=["brak-klucza", "brak-sieci", "odmowa"],
)
def test_uwaga_bez_skrzynki_czeka_w_kolejce_i_wychodzi_przy_nastepnym_starcie_centrum(
    tmp_path: Path, key: bool, outcome: SendOutcome | None, waits_for: str
) -> None:
    started = with_key(tmp_path) if key else centrum(tmp_path)
    if outcome is not None:
        started.report_box.outcomes.append(outcome)

    asked_at = time.monotonic()
    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})

    assert response.status_code == 200
    assert response.json() == {"state": "waiting", "waits_for": waits_for}
    # Odpowiedź przychodzi z końcem nieudanej próby wysyłki, a nie po całym czasie czekania na skrzynkę.
    assert time.monotonic() - asked_at < DELIVERY_WAIT_S
    assert started.report_box.issues == []
    started.client.stop()
    [waiting] = queued(tmp_path)
    [note] = notes(tmp_path)
    assert (note["title"], note["number"]) == (TITLE, None)

    restarted = with_key(tmp_path)
    with restarted.client:
        assert restarted.report_box.wait_until(lambda box: len(box.issues) == 1)
        assert wait_for(lambda: case_states(restarted.client, "uwaga") == ["wyslana"])
    restarted.client.stop()

    [issue] = dad_note_issues(restarted)
    assert (issue.title, issue.body) == (TITLE, f"{BODY}\n\n{VERSION_LINE}")
    assert notes(tmp_path) == [{**note, "number": issue.number}]
    assert waiting not in queued(tmp_path)


def test_uwaga_ktorej_kolejka_nie_zapisala_jest_odmowa_bez_sladu_w_stanie_uwag(tmp_path: Path) -> None:
    started = with_key(tmp_path)
    (tmp_path / "config" / "zgloszenia").mkdir()
    (tmp_path / "config" / "zgloszenia" / "kolejka").write_text("plik zamiast folderu", encoding="utf-8")

    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})

    assert response.status_code == 500
    assert response.json() == {
        "message": "Uwaga się nie zapisała i nie pójdzie do Maksa. Spróbuj wysłać ją jeszcze raz."
    }
    assert started.report_box.issues == []
    assert notes(tmp_path) == []


def test_uwaga_bez_sieci_wysyla_sie_sama_minute_po_powrocie_sieci_bez_restartu(tmp_path: Path) -> None:
    started = with_key(tmp_path)
    started.report_box.outcomes.append(Unreachable())
    assert started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY}).json() == {
        "state": "waiting",
        "waits_for": "internet",
    }

    started.clock.advance(RETRY_S)

    assert started.report_box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: case_states(started.client, "uwaga") == ["wyslana"])
    assert notes(tmp_path)[0]["number"] == dad_note_issues(started)[0].number
    assert wait_for(lambda: queued(tmp_path) == [])
