from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any

import pytest

from rozliczenia.centrum import notifications as notifications_module
from rozliczenia.centrum.notifications import NOTIFICATIONS_FILE

from tests.fixtures.centrum import finished_view, join_threads_since, write_report_key
from tests.fixtures.centrum_processes import PreparingCentrum, preparing_centrum, settling_centrum, stopped_for_maks
from tests.fixtures.linie_watkow import new_line

NOTE_TITLE = "Plik zbiorczy otwiera się długo"
CLOSED_AT = datetime(2026, 10, 20, 9, 15, tzinfo=timezone.utc)


def items(client: Any) -> list[dict[str, Any]]:
    response = client.get("/api/notifications")
    assert response.status_code == 200, response.json()
    found: list[dict[str, Any]] = response.json()["items"]
    return found


def polls(centrum: PreparingCentrum) -> int:
    return sum(include_closed for _, include_closed in centrum.surroundings.report_box.listed)


def test_powiadomienie_o_wycenie_w_efenix_zakonczonej_zatrzymaniem_ma_co_sie_stalo_zatrzymania(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    centrum.engines.fail_engine = True
    period = centrum.period_directory.name
    assert centrum.client.post("/api/runs", json={"process": "efenix", "period": period, "mode": "RUN"}).status_code == 200
    [stop] = finished_view(centrum.client)["result"]["stops"]

    [pricing] = [item for item in items(centrum.client) if item["kind"] == "wycena_w_efenix"]

    assert stop["what"]
    assert pricing["stopped"] == stop["what"]


@pytest.mark.parametrize(
    ("schema_version", "unread"),
    [
        pytest.param(notifications_module.SCHEMA_VERSION, False, id="znany-schemat-to-przeczytane"),
        pytest.param(notifications_module.SCHEMA_VERSION + 1, True, id="schemat-nowszego-wydania-to-brak-przeczytanych"),
    ],
)
def test_plik_przeczytanych_powiadomien_w_nieznanym_schemacie_to_brak_przeczytanych(
    tmp_path: Path, schema_version: int, unread: bool
) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    sent = centrum.client.post("/api/dad-notes", json={"title": NOTE_TITLE, "body": "Excel myśli minutę."})
    assert sent.status_code == 200, sent.json()
    box = centrum.surroundings.report_box
    box.close(next(issue.number for issue in box.issues if issue.title == NOTE_TITLE), "completed", CLOSED_AT)
    centrum.surroundings.clock.advance(minutes=10)
    [resolved] = items(centrum.client)
    assert resolved["unread"]
    (centrum.tool.config / NOTIFICATIONS_FILE).write_text(
        json.dumps({"schema_version": schema_version, "przeczytane": [resolved["id"]]}) + "\n", encoding="utf-8"
    )
    centrum.restart()

    assert [(item["id"], item["unread"]) for item in items(centrum.client)] == [(resolved["id"], unread)]


def test_odczyt_powiadomien_w_trakcie_pytania_skrzynki_nie_pyta_jej_drugi_raz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notifications_module, "CHECK_WAIT_S", 0.2)
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)
    assert centrum.client.post(f"/api/runs/{run_id}/diagnosis").status_code == 200
    assert centrum.client.post(f"/api/runs/{run_id}/report").json() == {"state": "sent"}
    box = centrum.surroundings.report_box
    box.search_hold = threading.Event()
    asked = polls(centrum)
    since = new_line()

    try:
        first, second = items(centrum.client), items(centrum.client)
    finally:
        box.search_hold.set()
    join_threads_since(since)

    assert [item["kind"] for item in first] == [item["kind"] for item in second] == ["zgloszenie"]
    assert polls(centrum) == asked + 1
