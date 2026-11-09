"""Stan pliku albo folderu na dysku (``file_state``): jest, nie ma go albo jest niedostępny.

Moduł jest szwem: biorą z niego odczyt skoroszytu, Konfiguracja wykonawców, otwarcie Rejestru zleceń z Ustawień,
listowanie Folderu okresu i Logi Uruchomienia, więc macierz błędów systemu plików jest tu raz, a wołający mają po
jednym teście tłumaczenia na swój Komunikat (``tests/test_workbook_files.py``, ``tests/test_worker_config.py``,
``tests/test_centrum_rozliczen.py``). Brak to ``FileNotFoundError`` albo ``NotADirectoryError``; każdy inny
``OSError`` (w Windows ``PermissionError`` pliku trzymanego przez OneDrive albo folderu bez dostępu) to niedostępność,
choć ``Path.is_file`` od Pythona 3.14 daje wtedy ``False``.
"""

from __future__ import annotations

from collections.abc import Callable
import errno
import os
from pathlib import Path
import sys

import pytest

from rozliczenia.file_state import file_state, folder_entries, remove_file

ABSENT = [
    pytest.param(FileNotFoundError(errno.ENOENT, "Nie można odnaleźć pliku"), id="brak"),
    pytest.param(NotADirectoryError(errno.ENOTDIR, "Nazwa katalogu jest nieprawidłowa"), id="plik-zamiast-folderu"),
]
INACCESSIBLE = [
    pytest.param(PermissionError(errno.EACCES, "Odmowa dostępu"), id="bez-dostepu"),
    pytest.param(OSError(errno.EIO, "Błąd wejścia/wyjścia"), id="blad-odczytu"),
]


def failing_for(path: Path, real: Callable[..., object], error: OSError) -> Callable[..., object]:
    """``real`` z błędem ``error`` dla ścieżki ``path``, a dla innych ścieżek prawdziwe."""

    def call(target: str | os.PathLike[str], *args: object, **kwargs: object) -> object:
        if Path(target) == path:
            raise error
        return real(target, *args, **kwargs)

    return call


def test_plik_jest_plikiem_a_folder_brak_pliku_i_plik_zamiast_folderu_to_brak(tmp_path: Path) -> None:
    (tmp_path / "Folder.xlsx").mkdir()
    (tmp_path / "plik").write_bytes(b"")

    assert file_state(tmp_path / "plik") == "file"
    assert file_state(tmp_path / "Folder.xlsx") == "missing"
    assert file_state(tmp_path / "brak.xlsx") == "missing"
    assert file_state(tmp_path / "plik" / "Skoroszyt.xlsx") == "missing"


@pytest.mark.parametrize("error", ABSENT)
def test_blad_braku_przy_stat_to_brak_pliku(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    path = tmp_path / "Skoroszyt.xlsx"
    path.write_bytes(b"")
    monkeypatch.setattr(Path, "stat", failing_for(path, Path.stat, error))

    assert file_state(path) == "missing"


@pytest.mark.parametrize("error", INACCESSIBLE)
def test_inny_blad_przy_stat_to_plik_niedostepny(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    path = tmp_path / "Skoroszyt.xlsx"
    path.write_bytes(b"")
    monkeypatch.setattr(Path, "stat", failing_for(path, Path.stat, error))

    assert file_state(path) == "inaccessible"


def test_listowanie_daje_wpisy_folderu_a_brak_folderu_albo_plik_na_jego_miejscu_to_brak(tmp_path: Path) -> None:
    (tmp_path / "Folder").mkdir()
    (tmp_path / "Folder" / "plik").write_bytes(b"")
    (tmp_path / "plik").write_bytes(b"")

    assert [entry.name for entry in folder_entries(tmp_path / "Folder") or []] == ["plik"]
    assert folder_entries(tmp_path / "brak") is None
    assert folder_entries(tmp_path / "plik") is None


@pytest.mark.parametrize("error", ABSENT)
def test_blad_braku_przy_listowaniu_to_brak_folderu(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    monkeypatch.setattr(os, "scandir", failing_for(tmp_path, os.scandir, error))

    assert folder_entries(tmp_path) is None


@pytest.mark.parametrize("error", INACCESSIBLE)
def test_inny_blad_przy_listowaniu_zglasza_folder_niedostepny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    monkeypatch.setattr(os, "scandir", failing_for(tmp_path, os.scandir, error))

    with pytest.raises(type(error)) as raised:
        folder_entries(tmp_path)

    assert raised.value is error


@pytest.mark.skipif(sys.platform == "win32", reason="chmod w Windows nie odbiera prawa odczytu")
def test_plik_i_folder_w_folderze_bez_dostepu_sa_niedostepne_a_nie_brakujace(tmp_path: Path) -> None:
    folder = tmp_path / "bez dostępu"
    (folder / "Folder okresu").mkdir(parents=True)
    (folder / "Skoroszyt.xlsx").write_bytes(b"")
    folder.chmod(0)
    try:
        state = file_state(folder / "Skoroszyt.xlsx")
        with pytest.raises(PermissionError, match="Permission denied"):
            folder_entries(folder / "Folder okresu")
    finally:
        folder.chmod(0o755)

    assert state == "inaccessible"


def test_usuniecie_pliku_ktorego_nie_ma_nie_jest_bledem(tmp_path: Path) -> None:
    (tmp_path / "plik").write_bytes(b"")
    (tmp_path / "dziennik").write_bytes(b"")

    remove_file(tmp_path / "dziennik")
    remove_file(tmp_path / "brak")
    remove_file(tmp_path / "plik" / "dziennik")

    assert sorted(path.name for path in tmp_path.iterdir()) == ["plik"]


@pytest.mark.parametrize("error", INACCESSIBLE)
def test_usuniecie_pliku_niedostepnego_zglasza_blad(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError) -> None:
    path = tmp_path / "dziennik"
    path.write_bytes(b"")
    monkeypatch.setattr(Path, "unlink", failing_for(path, Path.unlink, error))

    with pytest.raises(type(error)) as raised:
        remove_file(path)

    assert raised.value is error
    assert path.exists()
