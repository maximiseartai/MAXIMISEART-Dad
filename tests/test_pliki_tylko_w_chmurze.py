from __future__ import annotations

from pathlib import Path
import stat

import pytest

from rozliczenia.centrum.cloud_files import CloudFiles

RECALL_ON_DATA_ACCESS = 0x400000
RECALL_ON_OPEN = 0x40000
PINNED = 0x80000
UNPINNED = 0x100000
WORKBOOK = Path("Plik zbiorczy.xlsx")


@pytest.mark.parametrize(
    ("attributes", "online_only"),
    [
        pytest.param(RECALL_ON_DATA_ACCESS | stat.FILE_ATTRIBUTE_ARCHIVE, True, id="onedrive-tylko-online"),
        pytest.param(RECALL_ON_OPEN, True, id="pobierany-przy-otwarciu"),
        pytest.param(stat.FILE_ATTRIBUTE_OFFLINE, True, id="offline"),
        pytest.param(PINNED | stat.FILE_ATTRIBUTE_ARCHIVE, False, id="onedrive-zawsze-na-komputerze"),
        pytest.param(UNPINNED | stat.FILE_ATTRIBUTE_ARCHIVE, False, id="onedrive-pobrany-na-komputer"),
        pytest.param(stat.FILE_ATTRIBUTE_ARCHIVE | stat.FILE_ATTRIBUTE_READONLY, False, id="zwykly-plik"),
    ],
)
def test_plik_tylko_w_chmurze_ma_atrybut_onedrive_bez_kopii_na_komputerze(attributes: int, online_only: bool) -> None:
    assert CloudFiles(read_attributes=lambda _path: attributes).online_only(WORKBOOK) is online_only


def test_plik_bez_odczytu_atrybutow_nie_jest_tylko_w_chmurze() -> None:
    def denied(path: Path) -> int:
        raise PermissionError(13, "Odmowa dostępu", str(path))

    assert CloudFiles(read_attributes=denied).online_only(WORKBOOK) is False
