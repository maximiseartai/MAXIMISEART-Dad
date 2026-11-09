"""Zapis pliku stanu Centrum, gdy Windows na chwilę albo na dłużej blokuje plik (#459)."""

from __future__ import annotations

import os
from pathlib import Path
import sys

import pytest

from rozliczenia.centrum.atomic_file import StateFile, replace_atomically
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE
from rozliczenia.centrum.log import CentrumLog

from tests.fixtures.clock import ManualClock
from tests.fixtures.locked_file import lock_file

NAME = DAD_CASES_FILE
PAUSES = (0.05, 0.1, 0.2, 0.4)
WHERE = "stan Spraw taty"


def state(tmp_path: Path, text: str = "stara treść") -> Path:
    path = tmp_path / "config" / NAME
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    return path


def leftovers(path: Path) -> list[str]:
    return sorted(other.name for other in path.parent.iterdir() if other != path)


@pytest.mark.parametrize("failures", [1, 2, 4])
def test_chwilowa_blokada_konczy_sie_zapisem_po_przerwach_od_najkrotszej(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int
) -> None:
    path = state(tmp_path)
    locked = lock_file(monkeypatch, NAME, failures)
    clock = ManualClock()

    replace_atomically(path, "nowa treść", pause=clock.pause)

    assert path.read_text(encoding="utf-8") == "nowa treść"
    assert (locked.attempts, clock.seconds) == (failures + 1, sum(PAUSES[:failures]))
    assert leftovers(path) == []


def test_trwala_blokada_zostawia_stara_tresc_bez_pliku_tymczasowego_i_rzuca(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = state(tmp_path)
    locked = lock_file(monkeypatch, NAME)
    clock = ManualClock()

    with pytest.raises(PermissionError):
        replace_atomically(path, "nowa treść", pause=clock.pause)

    assert path.read_text(encoding="utf-8") == "stara treść"
    assert (locked.attempts, clock.seconds) == (5, sum(PAUSES))
    assert leftovers(path) == []


def test_inny_blad_systemu_niz_odmowa_dostepu_nie_czeka_na_ponowienie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = state(tmp_path)
    attempts: list[object] = []

    def full_disk(source: object, target: object) -> None:
        attempts.append(target)
        raise OSError(28, "Brak miejsca na dysku")

    monkeypatch.setattr(os, "replace", full_disk)
    clock = ManualClock()

    with pytest.raises(OSError, match="Brak miejsca"):
        replace_atomically(path, "nowa treść", pause=clock.pause)

    assert (len(attempts), clock.seconds) == (1, 0.0)
    assert path.read_text(encoding="utf-8") == "stara treść"
    assert leftovers(path) == []


@pytest.mark.skipif(sys.platform != "win32", reason="uchwyt bez FILE_SHARE_DELETE blokuje zamianę tylko na Windows")
def test_na_windows_plik_otwarty_innym_uchwytem_zapisuje_sie_po_jego_zamknieciu(tmp_path: Path) -> None:
    path = state(tmp_path)
    clock = ManualClock()
    handle = path.open(encoding="utf-8")

    def pause(seconds: float) -> None:
        clock.pause(seconds)
        handle.close()

    try:
        replace_atomically(path, "nowa treść", pause=pause)
    finally:
        handle.close()

    assert path.read_text(encoding="utf-8") == "nowa treść"
    assert clock.seconds == PAUSES[0]


def state_file(tmp_path: Path) -> tuple[StateFile, Path]:
    log_path = tmp_path / "logs" / "centrum-rozliczen.log"
    path = tmp_path / "config" / NAME
    return StateFile(path, CentrumLog(log_path), where=WHERE, pause=ManualClock().pause), log_path


def failures_in_log(log_path: Path) -> int:
    return log_path.read_text(encoding="utf-8").count(WHERE) if log_path.exists() else 0


def test_tresc_niedostepnego_pliku_czeka_a_ponowienie_zapisuje_najnowsza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file, log_path = state_file(tmp_path)
    locked = lock_file(monkeypatch, NAME)

    file.write("pierwsza")
    file.write("druga")
    file.retry()
    waiting = file.unavailable
    locked.release()
    file.retry()

    assert waiting
    assert not file.unavailable
    assert file.path.read_text(encoding="utf-8") == "druga"
    assert failures_in_log(log_path) == 1


def test_dziennik_dostaje_pierwsza_porazke_kazdego_okresu_niedostepnosci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file, log_path = state_file(tmp_path)
    locked = lock_file(monkeypatch, NAME)

    file.write("pierwsza")
    locked.release()
    file.write("druga")
    locked.failures = None
    file.write("trzecia")
    file.write("czwarta")

    assert failures_in_log(log_path) == 2
    assert file.unavailable
    assert file.path.read_text(encoding="utf-8") == "druga"


def test_ponowienie_bez_czekajacej_tresci_niczego_nie_zapisuje(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file, log_path = state_file(tmp_path)
    locked = lock_file(monkeypatch, NAME)

    file.retry()

    assert (locked.attempts, file.unavailable, file.path.exists()) == (0, False, False)
    assert failures_in_log(log_path) == 0


def test_przy_trwajacej_niedostepnosci_kolejne_proby_zapisu_nie_czekaja(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = ManualClock()
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log")
    file = StateFile(tmp_path / "config" / NAME, log, where=WHERE, pause=clock.pause)
    locked = lock_file(monkeypatch, NAME)

    file.write("pierwsza")
    file.retry()
    file.write("druga")

    assert (locked.attempts, clock.seconds) == (len(PAUSES) + 3, sum(PAUSES))
    assert file.unavailable
