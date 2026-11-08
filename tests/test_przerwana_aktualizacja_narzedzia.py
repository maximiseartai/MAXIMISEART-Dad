"""Aktualizacja narzędzia przerwana wyłączeniem komputera, a potem skrót „Centrum rozliczeń”.

Klon narzędzia to prawdziwe Centrum rozliczeń w klonie Gita z lokalnym
„origin” zamiast GitHuba. Aktualizację prowadzi Centrum w procesie testu.
Wyłączenie komputera to Centrum, które w danym kroku przestaje cokolwiek robić:
na dysku zostaje dokładnie to, co zdążyło zapisać. Skrót to prawdziwy proces
``run_centrum.py`` z klonu.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
from typing import Any
import urllib.request

import pytest

from rozliczenia.centrum import tool_update

from tests.fixtures.centrum_processes import PreparingCentrum, Surroundings, preparing_centrum
from tests.fixtures.potomne import wait_for, wait_for_value
from tests.fixtures.tool_clone import REPOSITORY_ROOT, FakeInstaller, ToolRepository, centrum_tool_repository, free_port

DAD_MAPPING = "schema_version: 1\nworkers:\n  wykonawca.a: Wykonawca Syntetyczny A\n"
SAMPLE_MAPPING = "schema_version: 1\nworkers:\n  przyklad: Przykładowy Wykonawca\n"
GITIGNORE = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
MAPPING = "config/worker_mapping.yaml"


def _get(port: int, path: str, *, timeout_s: float = 30) -> dict[str, Any]:
    """Jeden odczyt API Centrum ze skrótu; karta też nie ma limitu 1 s, a przeciążony runner Windows stoi dłużej (#584)."""

    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout_s) as response:
        body = json.load(response)
        assert isinstance(body, dict)
        return body


@contextmanager
def _shortcut(clone: Path, port: int) -> Iterator[subprocess.Popen[str]]:
    """Tata klika skrót: ``run_centrum.py`` z klonu; po bloku Centrum zamyka się razem z każdym procesem potomnym."""

    process = subprocess.Popen(
        [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
        cwd=clone,
        env=os.environ | {"PYTHONUTF8": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=sys.platform != "win32",
    )
    try:
        yield process
    finally:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False)
        elif process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=30)


def _health(process: subprocess.Popen[str], port: int) -> dict[str, Any]:
    answers: list[dict[str, Any]] = []

    def answered() -> bool:
        try:
            answers.append(_get(port, "/api/health", timeout_s=1))
            return True
        except OSError:
            pass
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise AssertionError(f"Centrum ze skrótu zakończyło się kodem {process.returncode}:\n{output}")
        return False

    assert wait_for(answered, 60, every=0.1), "Centrum ze skrótu nie odpowiedziało na health."
    return answers[-1]


def _refusal(process: subprocess.Popen[str], port: int) -> tuple[int, str]:
    """Kod wyjścia i konsola skrótu, który miał odmówić startu; ``AssertionError``, gdy Centrum jednak odpowiada."""

    try:
        output, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"Skrót nie odmówił startu, Centrum odpowiada: {_get(port, '/api/health')}") from None
    return process.returncode, output


def _repository_with_dad_file(directory: Path) -> ToolRepository:
    """Prawdziwe Centrum, którego pierwsza wersja śledzi Konfigurację wykonawców, a tata ma w niej swoje nazwiska."""

    repository = centrum_tool_repository(
        directory, {".gitignore": f"{GITIGNORE}!{MAPPING}\n", MAPPING: SAMPLE_MAPPING}
    )
    repository.write(MAPPING, DAD_MAPPING)
    return repository


def _version_without_its_library(repository: ToolRepository) -> str:
    """Nowa wersja przestaje śledzić plik taty, dodaje bibliotekę do wymagań i bez niej nie wystartuje."""

    app = (repository.publisher / "src/rozliczenia/centrum/app.py").read_text(encoding="utf-8")
    return repository.publish(
        {
            ".gitignore": GITIGNORE,
            "requirements.txt": "biblioteka-ktorej-nie-ma>=1\n",
            "src/rozliczenia/centrum/app.py": app.replace(
                "from __future__ import annotations\n",
                "from __future__ import annotations\n\nimport biblioteka_ktorej_nie_ma  # noqa: F401\n",
                1,
            ),
        },
        untrack=(MAPPING,),
    )


def _update_until(centrum: PreparingCentrum, reached: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    assert centrum.client.post("/api/tool-update").status_code == 202
    done, view = wait_for_value(lambda: dict(centrum.client.get("/api/tool-update").json()), reached, 30, every=0.02)
    assert done, f"Aktualizacja narzędzia utknęła w {view}."
    return view


def test_po_wylaczeniu_komputera_w_trakcie_instalacji_bibliotek_skrot_wraca_do_poprzedniej_wersji_z_plikiem_taty(
    tmp_path: Path,
) -> None:
    repository = _repository_with_dad_file(tmp_path / "repozytoria")
    before = repository.head()
    newest = _version_without_its_library(repository)
    installing = threading.Event()
    pip_never_finishes = FakeInstaller(hold=installing)
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository, installer=pip_never_finishes))
    _update_until(centrum, lambda view: view.get("step") == "installing")
    switched_off = repository.head()
    port = free_port()

    with _shortcut(repository.clone, port) as shortcut:
        health = _health(shortcut, port)
        view = _get(port, "/api/tool-update")
    clone = (repository.head(), repository.read(MAPPING), repository.in_clone("status", "--porcelain", "--untracked-files=no"))
    # Wyłączony komputer nie kończy instalacji; Centrum testu, które ją zaczęło, kończy ją porażką dopiero po odczycie
    # klonu, żeby zatrzymało się przed końcem testu.
    pip_never_finishes.succeeds = False
    installing.set()

    assert switched_off == newest
    assert health["commit"] == before[:7]
    assert clone == (before, DAD_MAPPING, f"M {MAPPING}")
    assert (view["state"], view["message"]["what"], view["next_action"]) == (
        "failed",
        "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
        "retry",
    )


def test_skrot_w_trakcie_ponownego_startu_po_aktualizacji_nie_rusza_klonu_i_prosi_o_chwile_cierpliwosci(
    tmp_path: Path,
) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository))
    _update_until(centrum, lambda view: view.get("step") == "restarting")
    port = free_port()

    with _shortcut(repository.clone, port) as shortcut:
        code, console = _refusal(shortcut, port)

    assert code == 1
    assert console.splitlines()[0] == "Co się stało: Aktualizacja narzędzia jeszcze się kończy."
    assert repository.head() == newest


def test_gdy_opiekun_nie_skonczyl_aktualizacji_przed_wylaczeniem_skrot_po_jego_terminie_wraca_do_poprzedniej_wersji(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_update, "GUARDIAN_LEASE_S", 0.0)
    repository = _repository_with_dad_file(tmp_path / "repozytoria")
    before = repository.head()
    newest = repository.publish({".gitignore": GITIGNORE}, untrack=(MAPPING,))
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository))
    _update_until(centrum, lambda view: view.get("step") == "restarting")
    switched_off = repository.head()
    port = free_port()

    with _shortcut(repository.clone, port) as shortcut:
        health = _health(shortcut, port)

    assert switched_off == newest
    assert health["commit"] == before[:7]
    assert repository.head() == before
    assert repository.read(MAPPING) == DAD_MAPPING


def test_gdy_dysk_odmowi_skrotowi_zapisu_porazki_po_cofnieciu_nastepny_start_pokazuje_porazke_a_nie_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_update, "GUARDIAN_LEASE_S", 0.0)
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository))
    _update_until(centrum, lambda view: view.get("step") == "restarting")
    result = repository.clone / "config" / tool_update.RESULT_FILE
    # Opiekun zapisał „ok”, a komputer zgasł, zanim nowe Centrum je przeczytało.
    tool_update.write_result(result, tool_update.UpdateResult(tool_update.UPDATED, before, newest))
    # Dysk odmawia zapisu nowego wyniku: write_result w launcher._roll_back rzuca OSError po cofnięciu klonu.
    result.with_name(result.name + ".tmp").mkdir()
    port = free_port()

    with _shortcut(repository.clone, port) as shortcut:
        code, console = _refusal(shortcut, port)
    with _shortcut(repository.clone, port) as shortcut:
        health = _health(shortcut, port)
        view = _get(port, "/api/tool-update")

    assert code == 1
    assert console.splitlines()[0].startswith("Co się stało:")
    assert health["commit"] == before[:7]
    assert repository.head() == before
    assert (view["state"], view.get("message", {}).get("what"), view.get("next_action")) == (
        "failed",
        "Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
        "retry",
    )
