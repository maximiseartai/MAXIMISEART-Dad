"""Karta Uruchomienia z Logów Uruchomienia (#427) widziana z przeglądarki: czego test oczekuje po starcie Centrum, i katalog
Logów, którego system nie daje wylistować."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import copy
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

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


@contextmanager
def unlisted(monkeypatch: pytest.MonkeyPatch, directory: Path) -> Iterator[None]:
    """System odmawia wylistowania katalogu ``directory`` (``os.listdir``, ``os.scandir``), choć plik w nim da się
    odczytać po nazwie: prawa bez odczytu katalogu, antywirus albo brak uchwytów; tak samo na Windows i na Macu."""

    def refusing(listing: Callable[..., Any]) -> Callable[..., Any]:
        def listed(path: Any = ".") -> Any:
            if isinstance(path, str | os.PathLike) and Path(path) == directory:
                raise PermissionError(13, "odmowa dostępu", str(path))
            return listing(path)

        return listed

    with monkeypatch.context() as patch:
        patch.setattr(os, "listdir", refusing(os.listdir))
        patch.setattr(os, "scandir", refusing(os.scandir))
        yield
