from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import urllib.request

import pytest

from rozliczenia.centrum import tool_update
from rozliczenia.tool_files import config_dir, log_path

from tests.fixtures.centrum_processes import PreparingCentrum, Surroundings, preparing_centrum
from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.potomne import wait_for_value
from tests.fixtures.tool_clone import REPOSITORY_ROOT, FakeInstaller, ToolRepository, centrum_tool_repository, free_port, centrum_health

DAD_MAPPING = "schema_version: 1\nworkers:\n  wykonawca.a: Wykonawca Syntetyczny A\n"
SAMPLE_MAPPING = "schema_version: 1\nworkers:\n  przyklad: Przykładowy Wykonawca\n"
GITIGNORE = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")
MAPPING = "config/worker_mapping.yaml"
STACKS_BEFORE_HEALTH_GIVES_UP_S = 45.0
LATE_PROCESS_STACKS_AFTER_ITS_START_S = 1.0


def _get(port: int, path: str, *, timeout_s: float = 30) -> dict[str, Any]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout_s) as response:
        body = json.load(response)
        assert isinstance(body, dict)
        return body


@contextmanager
def _shortcut(clone: Path, port: int, *, browser: Path | None = None) -> Iterator[subprocess.Popen[str]]:
    this_shortcut_stacks = Path(tempfile.mkdtemp(prefix="stosy-skrotu-", dir=clone.parent))
    process = subprocess.Popen(
        [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
        cwd=clone,
        env=_environment(browser) | _stacks_later(this_shortcut_stacks, everyone_at=time.time() + STACKS_BEFORE_HEALTH_GIVES_UP_S),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=sys.platform != "win32",
    )
    try:
        yield process
    except BaseException as failure:
        alive, journal = process.poll() is None, (config_dir(clone) / tool_update.JOURNAL).exists()
        console = _stopped(process)
        failure.add_note(_shortcut_when_failed(clone, this_shortcut_stacks, alive=alive, journal=journal, console=console))
        raise
    _stopped(process)


def _stacks_later(directory: Path, *, everyone_at: float) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    # ZEWNĘTRZNE: proces, który pisze do pełnej rury, czeka, aż ktoś z niej przeczyta (man 7 pipe, Microsoft Learn: CreatePipe)
    (directory / "sitecustomize.py").write_text(
        "import faulthandler, os, time\n"
        f"_stacks = open(os.path.join({str(directory)!r}, f'stosy-{{os.getpid()}}.txt'), 'w', encoding='utf-8')\n"
        f"faulthandler.dump_traceback_later(max({everyone_at!r} - time.time(), {LATE_PROCESS_STACKS_AFTER_ITS_START_S}), file=_stacks)\n",
        encoding="utf-8",
    )
    return {"PYTHONPATH": os.pathsep.join([str(directory), *filter(None, [os.environ.get("PYTHONPATH")])])}


def _stopped(process: subprocess.Popen[str]) -> str:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False)
    elif process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
    console, _ = process.communicate(timeout=30)
    return console


def _shortcut_when_failed(clone: Path, stacks: Path, *, alive: bool, journal: bool, console: str) -> str:
    centrum_log = log_path(clone)
    log_tail = centrum_log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:] if centrum_log.exists() else []
    return "\n".join(
        [
            f"Skrót w chwili porażki: {'żył' if alive else 'już się skończył'}.",
            f"Dziennik „Aktualizacja w toku” klonu: {'jeszcze jest' if journal else 'nie ma go'}.",
            "Konsola skrótu:",
            console.rstrip() or "(pusta)",
            *(
                f"Stosy procesu {dump.stem.removeprefix('stosy-')}:\n{text.rstrip()}"
                for dump in sorted(stacks.glob("stosy-*.txt"))
                if (text := dump.read_text(encoding="utf-8", errors="replace"))
            ),
            "Koniec dziennika Centrum klonu:",
            *(log_tail or ["(brak dziennika)"]),
        ]
    )


def _environment(browser: Path | None) -> dict[str, str]:
    return os.environ | {"PYTHONUTF8": "1"} | ({} if browser is None else {"BROWSER": str(browser)})


def _browser_recorder(directory: Path) -> tuple[Path, Path]:
    record = directory / "otwarte-adresy.txt"
    script = f"import sys\nwith open({str(record)!r}, 'a', encoding='utf-8') as record:\n    record.write(sys.argv[1] + '\\n')\n"
    return fake_cli(directory, "przegladarka", script), record


def _refusal(process: subprocess.Popen[str], port: int) -> tuple[int, str]:
    try:
        output, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        raise AssertionError(f"Skrót nie odmówił startu, Centrum odpowiada: {_get(port, '/api/health')}") from None
    return process.returncode, output


def _repository_with_dad_file(directory: Path) -> ToolRepository:
    repository = centrum_tool_repository(
        directory, {".gitignore": f"{GITIGNORE}!{MAPPING}\n", MAPPING: SAMPLE_MAPPING}
    )
    repository.write(MAPPING, DAD_MAPPING)
    return repository


def _version_without_its_library(repository: ToolRepository) -> str:
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


def _update_stopping_at(centrum: PreparingCentrum, step: str) -> None:
    assert centrum.client.post("/api/tool-update").status_code == 202
    done, view = wait_for_value(
        lambda: dict(centrum.client.get("/api/tool-update").json()), lambda view: view.get("step") == step, 30, every=0.02
    )
    assert done, f"Aktualizacja narzędzia utknęła w {view}."


def _end_install_of_switched_off_computer_with_failure(installer: FakeInstaller, installing: threading.Event) -> None:
    installer.succeeds = False
    installing.set()


def _disk_refuses_replacing(path: Path) -> None:
    path.with_name(path.name + ".tmp").mkdir()


def test_po_wylaczeniu_komputera_w_trakcie_instalacji_bibliotek_skrot_wraca_do_poprzedniej_wersji_z_plikiem_taty(
    tmp_path: Path,
) -> None:
    repository = _repository_with_dad_file(tmp_path / "repozytoria")
    before = repository.head()
    newest = _version_without_its_library(repository)
    installing = threading.Event()
    pip_never_finishes = FakeInstaller(hold=installing)
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository, installer=pip_never_finishes))
    _update_stopping_at(centrum, "installing")
    switched_off = repository.head()
    port = free_port()

    with _shortcut(repository.clone, port) as shortcut:
        health = centrum_health(port, process=shortcut)
        view = _get(port, "/api/tool-update")
    clone = (repository.head(), repository.read(MAPPING), repository.in_clone("status", "--porcelain", "--untracked-files=no"))
    _end_install_of_switched_off_computer_with_failure(pip_never_finishes, installing)

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
    _update_stopping_at(centrum, "restarting")
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
    _update_stopping_at(centrum, "restarting")
    switched_off = repository.head()
    port = free_port()

    with _shortcut(repository.clone, port) as shortcut:
        health = centrum_health(port, process=shortcut)

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
    _update_stopping_at(centrum, "restarting")
    result = repository.clone / "config" / tool_update.RESULT_FILE
    ok_unread_by_new_centrum = tool_update.UpdateResult(tool_update.UPDATED, before, newest)
    tool_update.write_result(result, ok_unread_by_new_centrum)
    _disk_refuses_replacing(result)
    port = free_port()

    with _shortcut(repository.clone, port) as shortcut:
        code, console = _refusal(shortcut, port)
    with _shortcut(repository.clone, port) as shortcut:
        health = centrum_health(port, process=shortcut)
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


def test_skrot_z_autostartu_po_cofnieciu_przerwanej_aktualizacji_startuje_centrum_dalej_bez_karty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_update, "GUARDIAN_LEASE_S", 0.0)
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(tool=repository))
    _update_stopping_at(centrum, "restarting")
    browser, opened = _browser_recorder(tmp_path / "przegladarka")
    port = free_port()

    with _shortcut(repository.clone, port, browser=browser) as shortcut:
        health = centrum_health(port, process=shortcut)
        desktop = subprocess.run(
            [sys.executable, str(repository.clone / "run_centrum.py"), "--port", str(port)],
            cwd=repository.clone,
            env=_environment(browser),
            capture_output=True,
            timeout=60,
            check=False,
        )
        addresses = opened.read_text(encoding="utf-8").split() if opened.exists() else []

    assert health["commit"] == before[:7]
    assert repository.head() == before
    assert desktop.returncode == 0, desktop.stdout
    assert addresses == [f"http://127.0.0.1:{port}/"], "skrót z Autostartu po cofnięciu otworzył kartę"
