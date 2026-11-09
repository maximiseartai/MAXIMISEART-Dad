"""Publikacja przez folder tymczasowy (``staged_publication``): pliki trafiają do taty wszystkie albo żaden.

Moduł jest szwem Przebiegu rozliczeń i Przygotowania pliku zbiorczego, więc macierz jego zachowania jest tu raz, na
jego interfejsie: założenie folderu tymczasowego, błąd dysku w publikacji, zatrzymanie z folderem tymczasowym, którego
nie dało się usunąć (np. trzyma go OneDrive), i sprzątanie po publikacji. Tłumaczenie na Komunikat każdego procesu
sprawdzają ``tests/test_settlement_engine.py`` i ``tests/test_collective_preparation_stops.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from rozliczenia import settlement_messages
from rozliczenia.message import Message, StopError
from rozliczenia.staged_publication import LOCAL_DISK, Disk, publish_staged
from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, PATH_CHECKS

NAME = "Rozliczenia pracowników"
# Celowa kopia początku nazwy folderu tymczasowego: tata czyta go w Komunikacie i szuka folderu po nim.
PREFIX = f".{NAME}.staging-"


def failed(tmp_path: Path) -> Message:
    return settlement_messages.write_failed(tmp_path / NAME)


def published(tmp_path: Path, publish: Callable[[Path], object], disk: Disk = LOCAL_DISK) -> object:
    return publish_staged(
        tmp_path,
        NAME,
        publish,
        failed=failed(tmp_path),
        left=settlement_messages.staging_left,
        disk=disk,
    )


def left_behind(tmp_path: Path) -> list[str]:
    return sorted(path.name for path in tmp_path.iterdir() if path.name.startswith(PREFIX))


# Folder tymczasowy, którego nie da się usunąć: prawdziwe ``remove_staging`` też nie zgłasza wtedy błędu.
HELD_BY_ONEDRIVE = Disk(remove_staging=lambda staging: None)


def test_publikacja_daje_wynik_i_nie_zostawia_folderu_tymczasowego(tmp_path: Path) -> None:
    def publish(staging: Path) -> str:
        (staging / "plik.xlsx").write_bytes(b"")
        (staging / "plik.xlsx").rename(tmp_path / "plik.xlsx")
        return "wynik"

    assert published(tmp_path, publish) == "wynik"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["plik.xlsx"]


def test_folder_tymczasowy_powstaje_obok_miejsca_publikacji_z_poczatkiem_nazwy_z_komunikatu(tmp_path: Path) -> None:
    seen: list[Path] = []

    published(tmp_path, seen.append)

    assert [path.parent for path in seen] == [tmp_path]
    assert seen[0].name.startswith(PREFIX)


def test_folder_tymczasowy_ktorego_nie_da_sie_usunac_po_publikacji_nie_zatrzymuje(tmp_path: Path) -> None:
    assert published(tmp_path, lambda staging: "wynik", HELD_BY_ONEDRIVE) == "wynik"
    assert len(left_behind(tmp_path)) == 1


def test_blad_zalozenia_folderu_tymczasowego_zatrzymuje_bez_publikacji(tmp_path: Path) -> None:
    calls: list[Path] = []

    def make_staging(prefix: str, directory: Path) -> Path:
        raise PermissionError("wymuszony: folder bez prawa zapisu")

    with pytest.raises(StopError) as raised:
        published(tmp_path, calls.append, Disk(make_staging=make_staging))

    assert raised.value.message == failed(tmp_path)
    assert calls == []


def test_blad_dysku_w_publikacji_zatrzymuje_i_sprzata_folder_tymczasowy(tmp_path: Path) -> None:
    def publish(staging: Path) -> None:
        (staging / "plik.xlsx").write_bytes(b"")
        raise OSError("wymuszony błąd zapisu")

    with pytest.raises(StopError) as raised:
        published(tmp_path, publish)

    assert raised.value.message == failed(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_zatrzymanie_procesu_po_usunieciu_folderu_tymczasowego_zostaje_bez_zmian(tmp_path: Path) -> None:
    stop = settlement_messages.publish_failed(tmp_path / NAME)

    def publish(staging: Path) -> None:
        raise StopError(stop)

    with pytest.raises(StopError) as raised:
        published(tmp_path, publish)

    assert raised.value.message == stop
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "error",
    [StopError(settlement_messages.publish_failed(Path("Rozliczenia pracowników"))), OSError("wymuszony błąd zapisu")],
    ids=["zatrzymanie-procesu", "blad-dysku"],
)
def test_zatrzymanie_z_folderem_tymczasowym_ktorego_nie_da_sie_usunac_podaje_poczatek_jego_nazwy(
    tmp_path: Path, error: Exception
) -> None:
    def publish(staging: Path) -> None:
        raise error

    with pytest.raises(StopError) as raised:
        published(tmp_path, publish, HELD_BY_ONEDRIVE)

    original = error.message if isinstance(error, StopError) else failed(tmp_path)
    assert raised.value.message == settlement_messages.staging_left(original, PREFIX)
    assert len(left_behind(tmp_path)) == 1


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_zatrzymanie_z_folderem_tymczasowym_w_folderze_bez_dostepu_podaje_poczatek_jego_nazwy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    """OneDrive odbiera dostęp do folderu, zanim folder tymczasowy zniknie: tata dalej dostaje jego początek nazwy."""

    directory = tmp_path / "Folder okresu"
    directory.mkdir()
    stop = settlement_messages.publish_failed(directory / NAME)

    def publish(staging: Path) -> None:
        raise StopError(stop)

    path_checks(monkeypatch)
    try:
        with pytest.raises(StopError) as raised:
            published(directory, publish, Disk(remove_staging=lambda staging: directory.chmod(0)))
    finally:
        directory.chmod(0o755)

    assert raised.value.message == settlement_messages.staging_left(stop, PREFIX)
    assert len(left_behind(directory)) == 1


def test_inny_wyjatek_przechodzi_bez_zmian_a_folder_tymczasowy_jest_sprzatany(tmp_path: Path) -> None:
    error = KeyboardInterrupt()

    def publish(staging: Path) -> None:
        raise error

    with pytest.raises(KeyboardInterrupt) as raised:
        published(tmp_path, publish)

    assert raised.value is error
    assert list(tmp_path.iterdir()) == []
