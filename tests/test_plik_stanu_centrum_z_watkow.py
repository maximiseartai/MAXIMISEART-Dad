from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
import threading

import pytest

from rozliczenia.centrum.atomic_file import StateFile
from rozliczenia.centrum.log import CentrumLog

NAME = "stan-sprawdzany.json"
NEWER_WRITE_WAIT_S = 0.5

Replace = Callable[[str | os.PathLike[str], str | os.PathLike[str]], None]


@dataclass
class HeldReplace:
    inner: Replace
    denied: bool = False
    hold_next: bool = False
    holding: threading.Event = field(default_factory=threading.Event)
    newer_written: threading.Event = field(default_factory=threading.Event)

    def __call__(self, source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if Path(target).name == NAME:
            if self.denied:
                raise PermissionError(13, "Odmowa dostępu", str(target))
            if self.hold_next:
                self.hold_next = False
                self.holding.set()
                self.newer_written.wait(NEWER_WRITE_WAIT_S)
        self.inner(source, target)


def _started(action: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=action, name="zapis-pliku-stanu", daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("older", ["write", "retry"], ids=["zapis", "ponowienie-czekajacej-tresci"])
def test_starsza_tresc_zapisywana_w_trakcie_zapisu_nowszej_nie_zastepuje_nowszej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, older: str
) -> None:
    path = tmp_path / NAME
    replace = HeldReplace(os.replace)
    monkeypatch.setattr(os, "replace", replace)
    state = StateFile(path, CentrumLog(tmp_path / "centrum-rozliczen.log"), where="stan w teście", pause=lambda _s: None)
    if older == "retry":
        replace.denied = True
        state.write("starsza")
        replace.denied = False
        assert state.unavailable
    replace.hold_next = True
    first = _started(state.retry if older == "retry" else lambda: state.write("starsza"))
    assert replace.holding.wait(30), "zapis starszej treści nie doszedł do zamiany pliku"

    def newer() -> None:
        state.write("nowsza")
        replace.newer_written.set()

    second = _started(newer)
    first.join(30)
    second.join(30)
    state.retry()

    assert (path.read_text(encoding="utf-8"), state.unavailable) == ("nowsza", False)
