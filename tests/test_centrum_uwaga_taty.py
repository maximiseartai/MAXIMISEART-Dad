"""Uwaga taty ogólna (ADR 0015, #318) przez HTTP API Centrum z fałszywą Skrzynką Zgłoszeń; bez prawdziwego GitHuba."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from rozliczenia.centrum.keyed_box import LIST_LAG_S, OPENING_FILE
from rozliczenia.centrum.outbox import DELIVERY_WAIT_S, RETRY_S
from rozliczenia.centrum.report_box import Refused, SendOutcome, Unreachable

from atrapy.skrzynka import BoxIssue
from tests.fixtures.centrum import (
    QUEUED_FOR_INTERNET,
    SENT,
    TOOL_COMMIT,
    Centrum,
    ToolDirectory,
    case_states,
    centrum,
    dad_cases,
    write_report_key,
)
from tests.fixtures.centrum_intermax import ordering_centrum
from tests.fixtures.centrum_processes import preparing_centrum, run_to_end, settling_centrum, stopped_for_maks
from tests.fixtures.potomne import wait_for
from atrapy.preparation import PERIOD, default_register_rows, paste_raw_orders, register_order
from atrapy.settlement import write_quantity_source

TITLE = "Plik zbiorczy otwiera się długo"
BODY = "Od wczoraj Excel myśli przy nim minutę.\nInne pliki otwierają się od razu."
# Treść issue kończy się wersją narzędzia taty: pierwsze 7 znaków commitu, jak na Konfiguracji.
VERSION_LINE = "Uwaga ogólna · wersja narzędzia 3c1d0a9"


def centrum_with_key(tmp_path: Path) -> Centrum:
    started = centrum(tmp_path)
    write_report_key(started.tool)
    return started


def notes(tmp_path: Path) -> list[dict[str, Any]]:
    return dad_cases(tmp_path / "config", "uwaga")


def queued(tmp_path: Path) -> list[Path]:
    return sorted(ToolDirectory(tmp_path).queue.glob("*.json"))


def dad_note_issues(started: Centrum) -> list[BoxIssue]:
    return started.report_box.issues_with("uwaga-taty")


def test_uwaga_z_tytulem_i_trescia_to_jedno_issue_uwaga_taty_z_wersja_narzedzia(tmp_path: Path) -> None:
    started = centrum_with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})

    assert response.status_code == 200
    assert response.json() == {"state": "sent"}
    [issue] = started.report_box.issues
    assert (issue.label, issue.title, issue.body) == ("uwaga-taty", TITLE, f"{BODY}\n\n{VERSION_LINE}")
    [note] = notes(tmp_path)
    assert (note["title"], note["commit"], note["number"]) == (TITLE, TOOL_COMMIT, issue.number)
    assert BODY not in json.dumps(note, ensure_ascii=False)
    assert wait_for(lambda: queued(tmp_path) == [])


def test_uwaga_przy_chwilowo_zablokowanym_pliku_zapisow_skrzynki_wychodzi_od_razu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antywirus na chwilę trzyma plik zapisów Skrzynki: jego zamiana czeka jak przy innych plikach Centrum, więc Uwaga
    nie czeka na budzenie kolejki i nie wygląda jak brak sieci (#879)."""

    opening = tmp_path / "config" / OPENING_FILE
    replace = Path.replace
    refused: list[Path] = []

    def held_once(path: Path, target: Any) -> Path:
        if Path(target) == opening and not refused:
            refused.append(path)
            raise PermissionError(13, "Odmowa dostępu", str(target))
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", held_once)
    started = centrum_with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})

    assert (response.json(), len(refused), len(started.report_box.issues)) == ({"state": "sent"}, 1, 1)


def test_uwaga_przy_pliku_zapisow_skrzynki_nieczytelnym_na_stale_czeka_a_dziennik_mowi_raz_ktory_plik(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pliku zapisów Skrzynki nie da się odczytać ani zapisać (#909): Uwaga czeka w kolejce jak bez internetu, a dziennik
    Centrum dostaje jedną linię z typem błędu, po której Maks wie, że to nie sieć."""

    opening = tmp_path / "config" / OPENING_FILE
    read_text = Path.read_text

    def locked(path: Path, *args: Any, **kwargs: Any) -> str:
        if path == opening:
            raise PermissionError(13, "Odmowa dostępu", str(path))
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", locked)
    started = centrum_with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})
    started.client.post("/api/dad-notes", json={"title": "Druga uwaga", "body": BODY})

    assert response.json() == QUEUED_FOR_INTERNET
    assert started.report_box.issues == []
    log = started.log_path.read_text(encoding="utf-8")
    assert log.count("skrzynka-zapisy-niedostepne typ=PermissionError") == 1


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
    started = centrum_with_key(tmp_path)

    draft = started.client.post("/api/dad-notes/draft", json=text)
    sent = started.client.post("/api/dad-notes", json=text)

    assert sent.json() == {"state": "sent"}
    [issue] = dad_note_issues(started)
    assert draft.status_code == 200
    # Uwaga ogólna nie ma odnośnika, więc „Maks dostanie” pokazuje tacie treść issue bez zmian.
    assert draft.json() == {"title": issue.title, "body": issue.body, "shown_body": issue.body}
    assert (issue.title, issue.body) == (TITLE, body)


def test_uwaga_z_adresem_z_rejestru_telefonem_i_ulica_wychodzi_zamaskowana_z_uwaga_a_podglad_to_wyslane_issue(
    tmp_path: Path,
) -> None:
    address = "Syntetyczna Turkusowa 21/4 Kraków"
    rows = default_register_rows()
    rows[2] = {**(rows[2] or {}), "ADRES": address}
    started = preparing_centrum(tmp_path, rows)
    write_report_key(ToolDirectory(tmp_path))
    run_to_end(started, dry_run=True)
    text = {"title": f"Klient {address}", "body": "Dzwonił z +48 600 123 456, mieszka przy ul. Kwiatowa 5/3."}

    draft = started.client.post("/api/dad-notes/draft", json=text)
    sent = started.client.post("/api/dad-notes", json=text)

    assert sent.json() == {"state": "sent"}
    [issue] = started.surroundings.report_box.issues_with("uwaga-taty")
    assert draft.json() == {"title": issue.title, "body": issue.body, "shown_body": issue.body}
    assert (issue.title, issue.body) == (
        "Klient [adres]",
        "Dzwonił z [telefon], mieszka przy [ulica].\n"
        "Reguła danych: zamaskowano wartość kolumny ADRES w: tytuł Uwagi taty.\n\n"
        f"{VERSION_LINE}",
    )


def test_uwaga_po_uporzadkowaniu_intermax_nie_wynosi_adresu_ani_numeru_umowy_z_wklejonych_wierszy(tmp_path: Path) -> None:
    started = ordering_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    assert started.run_to_end()["result"]["result"] == "OK"

    sent = started.client.post("/api/dad-notes", json={"title": "Zlecenie Ulica 104, umowa UM-104"})

    assert sent.json() == {"state": "sent"}
    [issue] = started.surroundings.report_box.issues_with("uwaga-taty")
    assert (issue.title, issue.body.splitlines()[0]) == (
        "Zlecenie [adres], umowa [numer Orange]",
        "Reguła danych: zamaskowano wartość kolumny ADRES w: tytuł Uwagi taty.",
    )


def test_po_uporzadkowaniu_intermax_uwaga_zna_adres_przesunietego_wiersza_a_slowo_z_urzadzen_wychodzi_bez_zmian(
    tmp_path: Path,
) -> None:
    # Pierwszy wiersz wklejenia (zlecenie 101) jest przesunięty o dwie kolumny w lewo (ADR 0019): pod nagłówkiem
    # ADRES stoi w nim URZĄDZENIA („Instalacja”), a jego ADRES i NUMER UMOWY stoją dwie kolumny wcześniej.
    started = ordering_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))
    assert started.run_to_end()["result"]["result"] == "OK"
    plain = {"title": "Pytanie", "body": "Instalacja internetu u klienta trwała długo"}
    shifted = {"title": "Pytanie", "body": "Zlecenie Ulica 101, umowa UM-101"}

    plain_draft = started.client.post("/api/dad-notes/draft", json=plain)
    shifted_draft = started.client.post("/api/dad-notes/draft", json=shifted)

    assert plain_draft.json()["body"] == f"Instalacja internetu u klienta trwała długo\n\n{VERSION_LINE}"
    assert shifted_draft.json()["body"].splitlines()[:3] == [
        "Zlecenie [adres], umowa [numer Orange]",
        "Reguła danych: zamaskowano wartość kolumny ADRES w: treść Uwagi taty.",
        "Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: treść Uwagi taty.",
    ]


# Każdy odczyt pliku taty w tej pracy Centrum uczy strażnika jego zakazanych wartości (ADR 0025), także odczyt bez
# Uruchomienia: Diagnoza czyta cały Rejestr zleceń, strony Uzupełnienia i okno startu Przebiegu Plik zbiorczy, karta
# Uporządkowania dół INTERMAX, a Przygotowanie przed odczytem okresu szuka Surowych zleceń.
READ_ADDRESS = "Syntetyczna Opalowa 3/8"


def first_line_of_draft(client: TestClient, body: str) -> str:
    draft = client.post("/api/dad-notes/draft", json={"title": "Pytanie", "body": body})
    assert draft.status_code == 200, draft.json()
    line: str = draft.json()["body"].splitlines()[0]
    return line


def diagnosed_register(tmp_path: Path) -> tuple[TestClient, Callable[[], object], str]:
    # Zlecenie z sierpnia: Przygotowanie okresu go nie czyta, czyta je tylko Diagnoza całego Rejestru.
    started = preparing_centrum(tmp_path, [{**register_order(9, datetime(2026, 8, 3, 9)), "ADRES": READ_ADDRESS}, *default_register_rows()])

    def read() -> object:
        run_id = stopped_for_maks(started)
        return started.client.post(f"/api/runs/{run_id}/diagnosis").status_code

    return started.client, read, READ_ADDRESS


def collective_file_page(page: str) -> Callable[[Path], tuple[TestClient, Callable[[], object], str]]:
    def setup(tmp_path: Path) -> tuple[TestClient, Callable[[], object], str]:
        started = settling_centrum(tmp_path)
        write_quantity_source(started.collective_file, [{"B": READ_ADDRESS}])
        return started.client, lambda: started.client.get(f"/api/periods/{PERIOD}/{page}").status_code, READ_ADDRESS

    return setup


def intermax_card(tmp_path: Path) -> tuple[TestClient, Callable[[], object], str]:
    started = ordering_centrum(tmp_path)
    return started.client, lambda: started.client.get("/api/intermax/days").status_code, "Ulica 104"


def raw_orders_in_register(tmp_path: Path) -> tuple[TestClient, Callable[[], object], str]:
    started = preparing_centrum(tmp_path)
    pasted = [register_order(11, datetime(2026, 9, 13, 10)), {**register_order(12, datetime(2026, 9, 13, 12)), "ADRES": READ_ADDRESS}]
    paste_raw_orders(started.fixture.register_path, pasted)
    return started.client, lambda: run_to_end(started, dry_run=True)["result"]["stop_kind"], READ_ADDRESS


@pytest.mark.parametrize(
    "reading",
    [
        diagnosed_register,
        collective_file_page("quantities-to-fill"),
        collective_file_page("without-quantity"),
        intermax_card,
        raw_orders_in_register,
    ],
    ids=["diagnoza-rejestru", "strona-uzupelnienia", "okno-startu-przebiegu", "karta-uporzadkowania", "surowe-zlecenia"],
)
def test_adres_z_pliku_przeczytanego_bez_uruchomienia_tez_wychodzi_w_uwadze_zamaskowany(
    tmp_path: Path, reading: Callable[[Path], tuple[TestClient, Callable[[], object], str]]
) -> None:
    client, read, address = reading(tmp_path)
    body = f"Klient {address} dzwonił"

    before = first_line_of_draft(client, body)
    read()
    after = first_line_of_draft(client, body)

    assert (before, after) == (body, "Klient [adres] dzwonił")


def assert_nothing_sent(started: Centrum, tmp_path: Path) -> None:
    assert started.report_box.issues == []
    assert started.report_box.keys == []
    assert queued(tmp_path) == []
    assert notes(tmp_path) == []


@pytest.mark.parametrize("title", ["", "   \n"], ids=["pusty", "same-biale-znaki"])
def test_uwaga_bez_tytulu_jest_odrzucona(tmp_path: Path, title: str) -> None:
    started = centrum_with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": title, "body": BODY})

    assert response.status_code == 422
    assert_nothing_sent(started, tmp_path)


@pytest.mark.parametrize("line_break", ["\n", "\r", "\r\n"], ids=["lf", "cr", "crlf"])
def test_tytul_uwagi_w_dwoch_liniach_jest_odrzucony(tmp_path: Path, line_break: str) -> None:
    started = centrum_with_key(tmp_path)

    response = started.client.post("/api/dad-notes", json={"title": f"Plik zbiorczy{line_break}otwiera się długo"})

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
    started = centrum_with_key(tmp_path) if key else centrum(tmp_path)
    if outcome is not None:
        started.report_box.outcomes.append(outcome)

    asked_at = time.monotonic()
    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})

    assert response.status_code == 200
    assert response.json() == {"state": "queued", "waits_for": waits_for}
    # Odpowiedź przychodzi z końcem nieudanej próby wysyłki, a nie po całym czasie czekania na skrzynkę.
    assert time.monotonic() - asked_at < DELIVERY_WAIT_S
    assert started.report_box.issues == []
    started.client.stop()
    [waiting] = queued(tmp_path)
    [note] = notes(tmp_path)
    assert (note["title"], note["number"]) == (TITLE, None)

    restarted = centrum_with_key(tmp_path)
    # Zakładanie bez odpowiedzi wstrzymuje następne Centrum na LIST_LAG_S (#879); nowe Centrum ma nowy zegar od zera.
    restarted.clock.pause(LIST_LAG_S)
    with restarted.client:
        assert restarted.report_box.wait_until(lambda box: len(box.issues) == 1)
        assert wait_for(lambda: case_states(restarted.client, "uwaga") == [SENT])
    restarted.client.stop()

    [issue] = dad_note_issues(restarted)
    assert (issue.title, issue.body) == (TITLE, f"{BODY}\n\n{VERSION_LINE}")
    assert notes(tmp_path) == [{**note, "number": issue.number}]
    assert waiting not in queued(tmp_path)


def test_uwaga_ktorej_kolejka_nie_zapisala_jest_odmowa_bez_sladu_w_stanie_uwag(tmp_path: Path) -> None:
    started = centrum_with_key(tmp_path)
    ToolDirectory(tmp_path).queue.parent.mkdir()
    ToolDirectory(tmp_path).queue.write_text("plik zamiast folderu", encoding="utf-8")

    response = started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY})

    assert response.status_code == 500
    assert response.json() == {
        "message": "Uwaga się nie zapisała i nie pójdzie do Maksa. Spróbuj wysłać ją jeszcze raz."
    }
    assert started.report_box.issues == []
    assert notes(tmp_path) == []


def test_uwaga_bez_sieci_wysyla_sie_sama_minute_po_powrocie_sieci_bez_restartu(tmp_path: Path) -> None:
    started = centrum_with_key(tmp_path)
    started.report_box.outcomes.append(Unreachable())
    assert started.client.post("/api/dad-notes", json={"title": TITLE, "body": BODY}).json() == QUEUED_FOR_INTERNET

    started.clock.advance(RETRY_S)

    assert started.report_box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: case_states(started.client, "uwaga") == [SENT])
    assert notes(tmp_path)[0]["number"] == dad_note_issues(started)[0].number
    assert wait_for(lambda: queued(tmp_path) == [])
