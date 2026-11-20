from __future__ import annotations

from pathlib import Path
import sys

import pytest

from rozliczenia.centrum.shortcut import SHORTCUT_FILE, StartupShortcut


def test_wylaczenie_autostartu_gdy_skrotu_juz_nie_ma_w_folderze_nie_jest_bledem(tmp_path: Path) -> None:
    autostart = StartupShortcut(folder=tmp_path)

    autostart.disable()

    assert (autostart.state(), list(tmp_path.iterdir())) == ("off", [])


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Dowiązanie symboliczne w Windows wymaga uprawnienia SeCreateSymbolicLinkPrivilege (Microsoft Learn: CreateSymbolicLinkW).",
)
def test_stan_autostartu_przy_skrocie_ktorego_nie_da_sie_sprawdzic_to_oserror_a_nie_wylaczony(tmp_path: Path) -> None:
    looped = tmp_path / SHORTCUT_FILE
    looped.symlink_to(looped)

    with pytest.raises(OSError, match="Nie da się teraz sprawdzić folderu Autostart"):
        StartupShortcut(folder=tmp_path).state()
