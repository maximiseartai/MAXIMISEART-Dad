"""SONDA TYMCZASOWA #1454, do usunięcia przed oddaniem PR: zawsze pada, żeby log CI pokazał notę porażki skrótu."""

from __future__ import annotations

from pathlib import Path
import time

import pytest

from rozliczenia.centrum import tool_update

import tests.test_przerwana_aktualizacja_narzedzia as skrot


def test_sonda_noty_skrotu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skrot, "STACKS_AFTER_S", 3.0)
    monkeypatch.setattr(tool_update, "GUARDIAN_LEASE_S", 0.0)
    repository = skrot.centrum_tool_repository(tmp_path / "repozytoria")
    repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    centrum = skrot.preparing_centrum(tmp_path, surroundings=skrot.Surroundings(tool=repository))
    skrot._update_until(centrum, lambda view: view.get("step") == "restarting")
    port = skrot.free_port()
    try:
        with skrot._shortcut(repository.clone, port) as shortcut:
            skrot.centrum_health(port, process=shortcut)
            time.sleep(6)
            raise AssertionError("wymuszona porażka sondy")
    except AssertionError as failure:
        pytest.fail("SONDA NOTY\n" + "\n".join(failure.__notes__))
