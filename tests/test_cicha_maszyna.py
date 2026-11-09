"""Kto na kogo czeka na maszynie pomiarów i jak długo (``tools/quiet_machine.py``), na zegarze testu."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

import pytest

from tests.fixtures.cicha_maszyna import ZegarTestu
import quiet_machine
from quiet_machine import MachineBusy, QuietMachine
from tests.fixtures.potomne import wait_for

# Pomiar wydajnosc trwa około 5 minut (features/wydajnosc.md skilla verify-centrum-rozliczen); agent ma 10 minut
# na jedno polecenie.
POMIAR_S = 5 * 60
LIMIT_POLECENIA_S = 10 * 60


@pytest.fixture
def zegar(monkeypatch: pytest.MonkeyPatch) -> ZegarTestu:
    clock = ZegarTestu()
    monkeypatch.setattr(quiet_machine, "time", clock)
    return clock


def maszyna(directory: Path, busy: list[str] | None = None) -> QuietMachine:
    return QuietMachine(directory, busy_processes=lambda: busy or [], report_every_s=None)


def trwajacy_pomiar(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "pomiar.lock"
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def test_przebieg_czeka_na_caly_trwajacy_pomiar_z_zapasem(tmp_path: Path, zegar: ZegarTestu) -> None:
    lock = trwajacy_pomiar(tmp_path)
    zegar.at(2 * POMIAR_S, lambda: lock.unlink())

    with maszyna(tmp_path).run() as waited:
        assert waited >= 2 * POMIAR_S


def test_przebieg_w_koncu_przestaje_czekac_i_nazywa_pomiar_ktory_trzyma_maszyne(
    tmp_path: Path, zegar: ZegarTestu
) -> None:
    trwajacy_pomiar(tmp_path)

    with pytest.raises(MachineBusy, match=rf"pomiar \(pid {os.getpid()}\)"):
        with maszyna(tmp_path).run():
            pass
    assert zegar.now >= 2 * POMIAR_S


def test_pomiar_czeka_na_cichy_procesor_krotko_nic_nie_trzymajac(tmp_path: Path, zegar: ZegarTestu) -> None:
    runs_waited: list[float] = []

    def run_during_wait() -> None:
        with maszyna(tmp_path).run() as waited:
            runs_waited.append(waited)

    zegar.at(60, run_during_wait)

    with pytest.raises(MachineBusy, match="pytest"):
        with maszyna(tmp_path, ["pytest"]).measurement():
            pass
    assert zegar.now + POMIAR_S <= LIMIT_POLECENIA_S
    assert runs_waited == [0]


def test_pomiar_ustepuje_przebiegowi_ktory_zarejestrowal_sie_gdy_pomiar_bral_blokade(
    tmp_path: Path, zegar: ZegarTestu
) -> None:
    late_run = tmp_path / "run-spozniony.pid"

    def run_registers_after_first_look() -> list[str]:
        late_run.write_text(str(os.getpid()), encoding="utf-8")
        return []

    racing = QuietMachine(tmp_path, busy_processes=run_registers_after_first_look, report_every_s=None)

    with pytest.raises(MachineBusy, match=rf"przebieg \(pid {os.getpid()}\)"):
        with racing.measurement():
            pass
    assert not (tmp_path / "pomiar.lock").exists()


@contextmanager
def proces(argv: list[str], fragment: str, executable: str | None = None) -> Iterator[None]:
    """Działa, dopóki trwa blok; ``ps`` widzi już jego własną linię poleceń z ``fragment``, a nie rodzica sprzed exec."""

    process = subprocess.Popen(argv, executable=executable)
    try:
        command = ["ps", "-ww", "-o", "command=", "-p", str(process.pid)]
        shown = wait_for(lambda: fragment in subprocess.run(command, capture_output=True, text=True, check=False).stdout, 10)
        assert shown, f"ps nie pokazał procesu {argv}"
        yield
    finally:
        process.kill()
        process.wait()


@pytest.fixture
def praca(monkeypatch: pytest.MonkeyPatch) -> str:
    """Fragment pracy, którego nie ma w żadnym innym procesie na maszynie, więc inne wątki nie mieszają się do testu."""

    fragment = f"praca-{uuid.uuid4().hex}"
    monkeypatch.setattr(quiet_machine, "BUSY_COMMANDS", (fragment,))
    return fragment


@pytest.mark.skipif(sys.platform == "win32", reason="na Windows maszyna nie czyta procesów z ps")
def test_powloka_czekajaca_na_swoja_kolej_nie_zajmuje_maszyny(praca: str) -> None:
    with proces(["sh", "-c", f"sleep 60; echo {praca}"], praca):
        assert quiet_machine.busy_commands() == []


@pytest.mark.skipif(sys.platform == "win32", reason="na Windows maszyna nie czyta procesów z ps")
def test_python_wykonujacy_prace_zajmuje_maszyne(praca: str) -> None:
    with proces([sys.executable, "-c", "import time; time.sleep(60)", praca], praca):
        assert quiet_machine.busy_commands() == [praca]


@pytest.mark.skipif(sys.platform == "win32", reason="na Windows maszyna nie czyta procesów z ps")
def test_przegladarka_zajmuje_maszyne(praca: str) -> None:
    browser = f"/{praca}/chrome-headless-shell"

    with proces([browser, "60"], praca, executable=shutil.which("sleep")):
        assert quiet_machine.busy_commands() == [praca]


def test_kazdy_skrypt_z_listy_pracy_maszyny_istnieje_w_repozytorium() -> None:
    """Fragment ``.py`` z ``BUSY_COMMANDS`` to nazwa skryptu (albo koniec nazw skryptów mutacji): po zmianie nazwy pliku
    maszyna przestałaby widzieć jego pracę i pomiar biegłby obok niego."""

    root = Path(__file__).resolve().parents[1]
    scripts = [path.name for folder in (".agents/skills", "tools") for path in (root / folder).rglob("*.py")]

    assert [fragment for fragment in quiet_machine.BUSY_COMMANDS if fragment.endswith(".py") and not any(name.endswith(fragment) for name in scripts)] == []
