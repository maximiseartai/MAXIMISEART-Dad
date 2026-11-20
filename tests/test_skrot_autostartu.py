from __future__ import annotations

from pathlib import Path

from rozliczenia.centrum.shortcut import StartupShortcut


def test_wylaczenie_autostartu_gdy_skrotu_juz_nie_ma_w_folderze_nie_jest_bledem(tmp_path: Path) -> None:
    autostart = StartupShortcut(folder=tmp_path)

    autostart.disable()

    assert (autostart.state(), list(tmp_path.iterdir())) == ("off", [])
