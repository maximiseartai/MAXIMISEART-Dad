"""SONDA TYMCZASOWA #1454, do usunięcia przed oddaniem PR: zawsze pada, żeby log CI pokazał notę porażki skrótu."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from rozliczenia.centrum import tool_update

from tests.fixtures.centrum_processes import Surroundings, preparing_centrum
from tests.fixtures.tool_clone import centrum_health, centrum_tool_repository, free_port
import tests.test_przerwana_aktualizacja_narzedzia as skrot


def test_sonda_noty_skrotu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skrot, "STACKS_AFTER_S", 3.0)
    monkeypatch.setattr(tool_update, "GUARDIAN_LEASE_S", 0.0)
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository))
    skrot._update_until(centrum, lambda view: view.get("step") == "restarting")
    port = free_port()
    try:
        with skrot._shortcut(repository.clone, port) as shortcut:
            centrum_health(port, process=shortcut)
            time.sleep(6)
            raise AssertionError("wymuszona porażka sondy")
    except AssertionError as failure:
        pytest.fail("SONDA NOTY\n" + "\n".join(failure.__notes__))
