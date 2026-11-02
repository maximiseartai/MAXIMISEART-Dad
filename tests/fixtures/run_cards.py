"""Karta Uruchomienia z Logów Uruchomienia (#427) widziana z przeglądarki: czego test oczekuje po starcie Centrum."""

from __future__ import annotations

import copy
from typing import Any

from fastapi.testclient import TestClient

from tests.fixtures.centrum import views_until

LIVE_ONLY = ("diagnosis", "report", "files_unchanged", "opens", "order_notes")


def restored(live: dict[str, Any], started_at: str) -> dict[str, Any]:
    """Karta z Logów zakończonego Uruchomienia: karta na żywo bez pól, których Logi nie niosą, i bez liczb postępu."""

    result = {key: value for key, value in live["result"].items() if key not in LIVE_ONLY}
    return copy.deepcopy(
        {"state": "restored", "run": live["run"], "started_at": started_at, "phases": live["progress"]["phases"], "result": result}
    )


def first_view(client: TestClient) -> dict[str, Any]:
    """Pierwszy widok strumienia SSE, z którym przeglądarka zaczyna po starcie Centrum."""

    return views_until(client, "idle", "running", "awaiting_decision", "finished")[0]
