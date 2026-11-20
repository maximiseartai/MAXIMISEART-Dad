from __future__ import annotations

import contextlib
import gc
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import warnings

import pytest

from rozliczenia.centrum import launcher, restart_guardian
from rozliczenia.centrum.restart_guardian import Restart, main, prepare
from rozliczenia.centrum.restart_guardian import launch as launch_unguarded_by_conftest
from rozliczenia.centrum.tool_update import (
    NEW_VERSION_FAILED,
    RESULT_FILE,
    ROLLBACK_FAILED,
    UPDATED,
    ToolClone,
    UpdateResult,
    read_result,
)
from rozliczenia import tool_files
from rozliczenia.centrum.settings.migrations.reminders import OLD_FOOTER_FILE, OLD_ROLLOUT_FILE
from rozliczenia.centrum.settings.migrations.workers import OLD_ADDRESSES_FILE, OLD_MAPPING_FILE
from rozliczenia.centrum.settings.reminders import REMINDERS_FILE
from rozliczenia.centrum.settings.settlement_mail import SETTLEMENT_MAIL_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.history import HISTORY_FILE
from rozliczenia.centrum.settings.memory import APPLIED_FILE, MEMORY_DIRECTORY
from rozliczenia.tool_files import start_command

from tests.fixtures.centrum import FIRST_START_RELEASE_ENTRIES, CentrumClient, ToolDirectory, centrum_app
from tests.fixtures.potomne import wait_for
from tests.fixtures.tool_clone import (
    FIRST_VERSION,
    REPOSITORY_ROOT,
    ToolRepository,
    centrum_tool_repository,
    free_port,
    git,
    centrum_health,
    tool_repository,
)


def _get(port: int, path: str) -> dict[str, object]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=1) as response:
        body = json.load(response)
        assert isinstance(body, dict)
        return body


def _close(port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(f"{origin}/api/shutdown", method="POST", headers={"Origin": origin})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 202


def _close_if_running(port: int) -> None:
    with contextlib.suppress(OSError):
        _close(port)
    # ZEWNĘTRZNE: na przeciążonym runnerze Windows GitHub Actions /api/health Centrum przestaje odpowiadać w limicie czasu, zanim Centrum zapisze stop w dzienniku i zwolni port (czasy zadań pytest na windows-latest)
    wait_for(lambda: tool_files.port_free(port), 30, every=0.1)


def _log_lines(clone: Path) -> list[str]:
    return ToolDirectory(clone).log_path.read_text(encoding="utf-8").splitlines()


def test_polecenie_opiekuna_przyjmuje_launcher_kazdej_wersji_jako_start_bez_karty_i_bez_okienek(tmp_path: Path) -> None:
    command = start_command(tmp_path, 47811)
    arguments = launcher.parse_arguments(command[2:])

    assert command == [sys.executable, str(tmp_path / "run_centrum.py"), "--port", "47811", "--no-browser", "--bez-okienek"]
    assert (arguments.port, arguments.no_browser, arguments.bez_okienek) == (47811, True, True)


def test_opiekun_z_kopii_nie_wczytuje_modulu_z_katalogu_roboczego_ani_nie_zapisuje_w_kopii_pycache(
    tmp_path: Path,
) -> None:
    root = tmp_path / "narzedzie"
    root.mkdir()
    loaded = tmp_path / "modul-z-katalogu-roboczego"
    (root / "argparse.py").write_text(
        f"import pathlib\npathlib.Path({str(loaded)!r}).touch()\nraise SystemExit(3)\n", encoding="utf-8"
    )
    work = tmp_path / "praca"
    work.mkdir()
    copy = prepare(work)
    restart = Restart(
        port=free_port(),
        before="1" * 40,
        after="2" * 40,
        root=root,
        result=tmp_path / RESULT_FILE,
        installed=False,
        work=work,
    )

    guardian = launch_unguarded_by_conftest(copy, restart)
    try:
        wait_for(lambda: restart.result.exists() or guardian.poll() is not None, 30)
    finally:
        guardian.kill()
        guardian.wait()

    assert not loaded.exists()
    assert read_result(restart.result) == UpdateResult(UPDATED, restart.before, restart.after, installed=False)
    assert sorted(path.relative_to(copy).as_posix() for path in copy.rglob("__pycache__")) == []


def test_opiekun_dostaje_kopie_swojego_kodu_z_klonu_sprzed_aktualizacji_ktora_ten_kod_zmienia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    guardian_file = "src/rozliczenia/centrum/restart_guardian.py"
    old_guardian = repository.read(guardian_file)
    newest = repository.publish({guardian_file: old_guardian + "\nOPIEKUN_NOWEJ_WERSJI = True\n"})
    monkeypatch.setattr(restart_guardian, "_SOURCE", repository.clone / "src")
    copied: list[str] = []

    def guardian(copy: Path, restart: Restart) -> None:
        copied.append((copy / "rozliczenia" / "centrum" / "restart_guardian.py").read_text(encoding="utf-8"))
        shutil.rmtree(restart.work)

    tool_update = ToolClone(repository.clone, origin=str(repository.origin))
    with CentrumClient(centrum_app(ToolDirectory(tmp_path), tool_update=tool_update, guardian=guardian)) as client:
        assert client.post("/api/tool-update").status_code == 202
        assert wait_for(lambda: copied != [], 60), client.get("/api/tool-update").json()

    assert copied == [old_guardian]
    assert repository.head() == newest


def test_nowe_centrum_zastaje_wynik_ok_w_pliku_juz_w_chwili_swojego_startu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "START_TIMEOUT_S", 0.0)
    root, work = tmp_path / "narzedzie", tmp_path / "praca"
    root.mkdir()
    work.mkdir()
    restart = Restart(free_port(), "1" * 40, "2" * 40, root, tmp_path / RESULT_FILE, False, work)
    at_start: list[UpdateResult | None] = []

    def start(started: Restart) -> subprocess.Popen[bytes]:
        at_start.append(read_result(started.result))
        return subprocess.Popen([sys.executable, "-c", ""])

    main(restart.arguments(), show_problem=lambda title, text: None, start=start)

    assert at_start[:1] == [UpdateResult(UPDATED, restart.before, restart.after, False)]


def test_pliki_narzedzia_na_dysku_taty_maja_w_kazdej_wersji_te_same_nazwy() -> None:
    files = {
        "WORKER_LIST": tool_files.CONFIG_DIR / WORKERS_FILE,
        "OLD_WORKER_MAPPING": tool_files.CONFIG_DIR / OLD_MAPPING_FILE,
        "OLD_WORKER_ADDRESSES": tool_files.CONFIG_DIR / OLD_ADDRESSES_FILE,
        "REMINDERS": tool_files.CONFIG_DIR / REMINDERS_FILE,
        "SETTLEMENT_MAIL": tool_files.CONFIG_DIR / SETTLEMENT_MAIL_FILE,
        "OLD_REMINDERS_ROLLOUT": tool_files.CONFIG_DIR / OLD_ROLLOUT_FILE,
        "OLD_REMINDERS_FOOTER": tool_files.CONFIG_DIR / OLD_FOOTER_FILE,
        "WORKER_TEMPLATE": tool_files.WORKER_TEMPLATE,
        "COLLECTIVE_TEMPLATE": tool_files.COLLECTIVE_TEMPLATE,
        "INTERNAL_TEMPLATE": tool_files.INTERNAL_TEMPLATE,
        "SETTINGS": tool_files.CONFIG_DIR / SETTINGS_FILE,
        "SETTINGS_HISTORY": tool_files.CONFIG_DIR / HISTORY_FILE,
        "SETTINGS_MEMORY": tool_files.CONFIG_DIR / MEMORY_DIRECTORY,
        "SETTINGS_RELEASE_CHANGES": tool_files.CONFIG_DIR / MEMORY_DIRECTORY / APPLIED_FILE,
        "SETTLEMENT_METRICS": tool_files.SETTLEMENT_METRICS,
        "PREPARATION_METRICS": tool_files.PREPARATION_METRICS,
        "INTERMAX_METRICS": tool_files.INTERMAX_METRICS,
        "EFENIX_METRICS": tool_files.EFENIX_METRICS,
        "REPORT_ENTERING_METRICS": tool_files.REPORT_ENTERING_METRICS,
        "LOG_PATH": tool_files.LOG_PATH,
    }

    assert {name: path.relative_to(tool_files.TOOL_ROOT).as_posix() for name, path in files.items()} == {
        "WORKER_LIST": "config/wykonawcy.yaml",
        "OLD_WORKER_MAPPING": "config/worker_mapping.yaml",
        "OLD_WORKER_ADDRESSES": "config/adresy-wykonawcow.yaml",
        "REMINDERS": "config/przypomnienia.yaml",
        "SETTLEMENT_MAIL": "config/wysylka-rozliczen.yaml",
        "OLD_REMINDERS_ROLLOUT": "config/przypomnienia-od.txt",
        "OLD_REMINDERS_FOOTER": "config/stopka-przypomnien.txt",
        "WORKER_TEMPLATE": "config/Wzorzec rozliczenia pracownika.xlsx",
        "COLLECTIVE_TEMPLATE": "config/Wzorzec pliku zbiorczego.xlsx",
        "INTERNAL_TEMPLATE": "config/Wzorzec rozliczenia wewnętrznego.xlsx",
        "SETTINGS": "config/centrum-ustawienia.yaml",
        "SETTINGS_HISTORY": "config/historia-ustawien.jsonl",
        "SETTINGS_MEMORY": "config/ustawienia-pamiec",
        "SETTINGS_RELEASE_CHANGES": "config/ustawienia-pamiec/zmiany-z-wydan.json",
        "SETTLEMENT_METRICS": ".rozliczenia-metrics.jsonl",
        "PREPARATION_METRICS": ".przygotowanie-pliku-zbiorczego-metrics.jsonl",
        "INTERMAX_METRICS": ".uporzadkowanie-intermax-metrics.jsonl",
        "EFENIX_METRICS": ".wycena-efenix-metrics.jsonl",
        "REPORT_ENTERING_METRICS": ".wpisanie-raportow-metrics.jsonl",
        "LOG_PATH": "logs/centrum-rozliczen.log",
    }


def test_skrot_klikniety_w_trakcie_startu_centrum_laczy_sie_z_jego_portem_zanim_serwer_zacznie_obslugiwac() -> None:
    with tool_files.listen_locally(0) as listener:
        with socket.create_connection(listener.getsockname(), timeout=5):
            pass


def _collect_garbage_of_earlier_tests_in_this_worker() -> None:
    gc.collect()


def _port_free_with_unclosed_sockets(port: int) -> tuple[bool, list[str]]:
    _collect_garbage_of_earlier_tests_in_this_worker()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        free = tool_files.port_free(port)
        gc.collect()
    return free, [str(warning.message) for warning in caught if isinstance(warning.source, socket.socket)]


def test_port_zajety_przez_centrum_nie_jest_wolny_a_sprawdzenie_zajetego_i_wolnego_zamyka_gniazdo() -> None:
    with tool_files.listen_locally(0) as listener:
        port = listener.getsockname()[1]
        taken = _port_free_with_unclosed_sockets(port)
    released = _port_free_with_unclosed_sockets(port)

    assert (taken, released) == ((False, []), (True, []))


def test_opiekun_czeka_na_zwolnienie_portu_i_startuje_nowa_wersje_z_nowym_identyfikatorem_startu(
    tmp_path: Path,
) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    port = free_port()
    old = subprocess.Popen(
        [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
        cwd=clone,
        env=os.environ | {"PYTHONUTF8": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        old_health = centrum_health(port)
        newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
        assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
        work = tmp_path / "praca"
        work.mkdir()
        guardian = launch_unguarded_by_conftest(
            prepare(work),
            Restart(
                port=port,
                before=before,
                after=newest,
                root=clone,
                result=clone / "config" / RESULT_FILE,
                installed=False,
                work=work,
            ),
        )
        _close(port)
        old_exit = old.wait(timeout=30)
        new_health = centrum_health(port, commit=newest)
        guardian_exit = guardian.wait(timeout=30)
        view = _get(port, "/api/tool-update")
    finally:
        _close_if_running(port)
        old.kill()
        old.wait()

    assert old_exit == 0
    assert (old_health["commit"], new_health["commit"]) == (before[:7], newest[:7])
    assert new_health["instance"] != old_health["instance"]
    assert guardian_exit == 0
    assert view == {"state": "updated"}
    assert not (clone / "config" / RESULT_FILE).exists()
    assert not work.exists()
    assert ToolClone(clone).interrupted_update() is None
    events = [line.split(" ", 2)[1] for line in _log_lines(clone)]
    assert events == [
        "start",
        *FIRST_START_RELEASE_ENTRIES,
        "zamkniecie",
        "stop",
        "aktualizacja-koniec",
        "start",
        "zamkniecie",
        "stop",
    ]
    assert f"aktualizacja-koniec wynik=ok przed={before} po={newest} biblioteki=nie" in [
        line.split(" ", 1)[1] for line in _log_lines(clone)
    ]
    starts = [line.split(" ", 1)[1] for line in _log_lines(clone) if line.split(" ", 2)[1] == "start"]
    assert starts[1] == f"start port={port} wersja={newest[:7]} konsola=nie"


def _guardian_in_background(restart: Restart, dialogs: list[tuple[str, str]]) -> tuple[threading.Thread, list[int]]:
    exits: list[int] = []

    def record(title: str, text: str) -> None:
        dialogs.append((title, text))

    def guard() -> None:
        exits.append(main(restart.arguments(), show_problem=record))

    thread = threading.Thread(target=guard, name="opiekun-w-tescie", daemon=True)
    thread.start()
    return thread, exits


def test_skrot_klikniety_w_trakcie_ponownego_startu_nie_cofa_nowej_wersji_ktora_dziala(tmp_path: Path) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    started = tmp_path / "nowa-wersja-startuje"
    run_centrum = (repository.publisher / "run_centrum.py").read_text(encoding="utf-8")
    takes_port_after_shortcut = f"from pathlib import Path; Path({str(started)!r}).touch()\nimport time; time.sleep(1.5)\n"
    newest = repository.publish({"run_centrum.py": takes_port_after_shortcut + run_centrum})
    assert ToolClone(repository.clone, origin=str(repository.origin)).update().code == UPDATED
    work = tmp_path / "praca"
    work.mkdir()
    port = free_port()
    dialogs: list[tuple[str, str]] = []
    restart = Restart(port, before, newest, repository.clone, repository.clone / "config" / RESULT_FILE, False, work)
    try:
        guardian, exits = _guardian_in_background(restart, dialogs)
        assert wait_for(started.exists, 60), "Opiekun nie uruchomił nowej wersji."
        with socket.socket() as shortcut_reading_log:
            shortcut_reading_log.bind(("127.0.0.1", port))
            shortcut_reading_log.listen()
            time.sleep(3)
        guardian.join(timeout=90)
        health = centrum_health(port, timeout_s=5)
    finally:
        _close_if_running(port)

    assert exits == [0]
    assert dialogs == []
    assert repository.head() == newest
    assert health["commit"] == newest[:7]
    assert ToolClone(repository.clone).interrupted_update() is None


def _version_missing_a_library(repository: ToolRepository, start_problems_shown: Path) -> dict[str, str]:
    app = (repository.publisher / "src/rozliczenia/centrum/app.py").read_text(encoding="utf-8")
    platform = (repository.publisher / "src/rozliczenia/centrum/platform.py").read_text(encoding="utf-8")
    windowless = (
        "\n\ndef show_start_problem(title: str, text: str) -> None:\n"
        f"    with open({str(start_problems_shown)!r}, 'a', encoding='utf-8') as shown:\n"
        "        shown.write(text + '\\n')\n"
    )
    return {
        "src/rozliczenia/centrum/app.py": app.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\nimport biblioteka_ktorej_nie_ma  # noqa: F401\n",
            1,
        ),
        "src/rozliczenia/centrum/platform.py": platform + windowless,
    }


def test_nowa_wersja_ktora_nie_wystartuje_wraca_do_starego_commitu_a_stara_startuje_z_komunikatem(
    tmp_path: Path,
) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    port = free_port()
    new_version_dialogs = tmp_path / "okienka-nowej-wersji.txt"
    dialogs: list[tuple[str, str]] = []
    old = subprocess.Popen(
        [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
        cwd=clone,
        env=os.environ | {"PYTHONUTF8": "1"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        old_health = centrum_health(port)
        newest = repository.publish(_version_missing_a_library(repository, new_version_dialogs))
        work = tmp_path / "praca"
        work.mkdir()
        assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
        restart = Restart(port, before, newest, clone, clone / "config" / RESULT_FILE, False, work)
        guardian, exits = _guardian_in_background(restart, dialogs)
        _close(port)
        old.wait(timeout=30)
        guardian.join(timeout=90)
        back_health = centrum_health(port, commit=before)
        view = _get(port, "/api/tool-update")
    finally:
        _close_if_running(port)
        old.kill()
        old.wait()

    assert exits == [0]
    assert repository.head() == before
    assert repository.in_clone("status", "--porcelain", "--untracked-files=no") == ""
    assert back_health["instance"] != old_health["instance"]
    assert dialogs == []
    assert not new_version_dialogs.exists()
    assert (view["state"], view["message"], view["next_action"]) == (
        "failed",
        {
            "what": "Nowa wersja narzędzia nie wystartowała.",
            "where": "narzędzie na tym komputerze",
            "action": "Narzędzie działa dalej w poprzedniej wersji. Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”.",
        },
        "report",
    )
    assert not (clone / "config" / RESULT_FILE).exists()
    assert not work.exists()
    entries = [line.split(" ", 1)[1] for line in _log_lines(clone)]
    assert any(entry.startswith("blad-startu kod=BRAK_BIBLIOTEKI ") for entry in entries)
    assert [entry for entry in entries if entry.startswith("aktualizacja-koniec")] == [
        f"aktualizacja-koniec wynik=NOWA_WERSJA_NIE_WYSTARTOWALA przed={before} po={newest} biblioteki=nie"
    ]


def test_gdy_po_cofnieciu_stara_wersja_ze_skrotu_juz_trzyma_port_opiekun_konczy_bez_okienka(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "PORT_TIMEOUT_S", 0.2)
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    old_copy = tmp_path / "stara-wersja"
    git(tmp_path, "clone", "--quiet", str(repository.origin), str(old_copy))
    started = tmp_path / "nowa-wersja-startuje"
    waits_for_shortcut = (
        "import sys, time, urllib.request\n"
        "direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
        f"from pathlib import Path; Path({str(started)!r}).touch()\n"
        "port = int(sys.argv[sys.argv.index('--port') + 1])\n"
        "while True:\n"
        "    try:\n"
        "        direct.open(f'http://127.0.0.1:{port}/api/health', timeout=1).close()\n"
        "    except OSError:\n"
        "        time.sleep(0.1)\n"
        "    else:\n"
        "        raise SystemExit(1)\n"
    )
    newest = repository.publish({"run_centrum.py": waits_for_shortcut})
    work = tmp_path / "praca"
    work.mkdir()
    assert ToolClone(repository.clone, origin=str(repository.origin)).update().code == UPDATED
    port = free_port()
    result = repository.clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []
    restart = Restart(port, before, newest, repository.clone, result, False, work)
    shortcut: subprocess.Popen[bytes] | None = None
    try:
        guardian, exits = _guardian_in_background(restart, dialogs)
        assert wait_for(started.exists, 60), "Opiekun nie uruchomił nowej wersji."
        shortcut = subprocess.Popen(
            [sys.executable, str(old_copy / "run_centrum.py"), "--port", str(port), "--no-browser"],
            cwd=old_copy,
            env=os.environ | {"PYTHONUTF8": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        centrum_health(port, commit=before)
        guardian.join(timeout=90)
        health = centrum_health(port, timeout_s=5)
    finally:
        _close_if_running(port)
        if shortcut is not None:
            shortcut.kill()
            shortcut.wait()

    assert exits == [0]
    assert dialogs == []
    assert repository.head() == before
    assert health["commit"] == before[:7]
    assert read_result(result) == UpdateResult(NEW_VERSION_FAILED, before, newest, False)


OLD_VERSION_FROM_GUARDIAN_ENDS_WITHIN_S = 30


def test_gdy_skrot_zajmie_port_tuz_po_cofnieciu_opiekun_konczy_bez_okienka(tmp_path: Path) -> None:
    started = tmp_path / "stara-wersja-startuje"
    run_centrum = (REPOSITORY_ROOT / "run_centrum.py").read_text(encoding="utf-8")
    old_version_from_guardian_waits_for_shortcut = (
        "import sys\n"
        "if '--bez-okienek' in sys.argv:\n"
        "    import time, urllib.request\n"
        "    from pathlib import Path\n"
        f"    Path({str(started)!r}).touch()\n"
        "    port = int(sys.argv[sys.argv.index('--port') + 1])\n"
        "    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))\n"
        "    deadline = time.monotonic() + 60\n"
        "    while time.monotonic() < deadline:\n"
        "        try:\n"
        "            direct.open(f'http://127.0.0.1:{port}/api/health', timeout=1).close()\n"
        "        except OSError:\n"
        "            time.sleep(0.1)\n"
        "        else:\n"
        "            break\n"
        "    sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))\n"
        "    from rozliczenia.centrum import launcher\n"
        f"    assert launcher._SHORTCUT_HOLDS_PORT_S <= {OLD_VERSION_FROM_GUARDIAN_ENDS_WITHIN_S}, launcher._SHORTCUT_HOLDS_PORT_S\n"
        "    launcher._SHORTCUT_HOLDS_PORT_S = 0.5\n"
    )
    repository = centrum_tool_repository(
        tmp_path / "repozytoria", {"run_centrum.py": old_version_from_guardian_waits_for_shortcut + run_centrum}
    )
    clone = repository.clone
    before = repository.head()
    newest = repository.publish(
        {**_version_missing_a_library(repository, tmp_path / "okienka-nowej-wersji.txt"), "run_centrum.py": run_centrum}
    )
    work = tmp_path / "praca"
    work.mkdir()
    assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
    port = free_port()
    dialogs: list[tuple[str, str]] = []
    restart = Restart(port, before, newest, clone, clone / "config" / RESULT_FILE, False, work)
    shortcut: subprocess.Popen[bytes] | None = None
    try:
        guardian, exits = _guardian_in_background(restart, dialogs)
        assert wait_for(started.exists, 90), "Opiekun nie uruchomił starej wersji po cofnięciu."
        shortcut = subprocess.Popen(
            [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
            cwd=clone,
            env=os.environ | {"PYTHONUTF8": "1"},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        guardian.join(timeout=90)
        health = centrum_health(port, timeout_s=5)
        view = _get(port, "/api/tool-update")
        assert wait_for(
            lambda: "juz-dziala" in [line.split(" ", 2)[1] for line in _log_lines(clone)],
            OLD_VERSION_FROM_GUARDIAN_ENDS_WITHIN_S,
            every=0.1,
        ), "Stara wersja od opiekuna nie zakończyła się."
    finally:
        _close_if_running(port)
        if shortcut is not None:
            shortcut.kill()
            shortcut.wait()

    assert exits == [0]
    assert dialogs == []
    assert repository.head() == before
    assert health["commit"] == before[:7]
    assert (view["state"], view["next_action"]) == ("failed", "report")


def test_gdy_nie_startuje_zadna_wersja_opiekun_pokazuje_jedno_okienko_a_klon_stoi_na_starym_commicie(
    tmp_path: Path,
) -> None:
    not_starting = "raise SystemExit(1)\n"
    repository = tool_repository(tmp_path / "repozytoria", {**FIRST_VERSION, "run_centrum.py": not_starting})
    before = repository.head()
    dad_mapping = "schema_version: 1\nworkers:\n  wykonawca.a: Wykonawca Syntetyczny A\n"
    repository.write("config/worker_mapping.yaml", dad_mapping)
    newest = repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",)
    )
    work = tmp_path / "praca"
    work.mkdir()
    assert ToolClone(repository.clone, origin=str(repository.origin)).update().code == UPDATED
    result = repository.clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []

    guardian, exits = _guardian_in_background(
        Restart(free_port(), before, newest, repository.clone, result, False, work), dialogs
    )
    guardian.join(timeout=90)

    assert exits == [1]
    assert dialogs == [
        (
            "Centrum rozliczeń",
            "Co się stało: Centrum rozliczeń nie wystartowało po aktualizacji narzędzia.\n"
            "Gdzie: narzędzie na tym komputerze\n"
            "Co zrobić: Przekaż ten komunikat Maksowi.",
        )
    ]
    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == dad_mapping
    assert repository.in_clone("status", "--porcelain", "--untracked-files=no") == "M config/worker_mapping.yaml"
    assert read_result(result) == UpdateResult(NEW_VERSION_FAILED, before, newest, False)


NOT_STARTED_AFTER_UPDATE = (
    "Centrum rozliczeń",
    "Co się stało: Centrum rozliczeń nie wystartowało po aktualizacji narzędzia.\n"
    "Gdzie: narzędzie na tym komputerze\n"
    "Co zrobić: Przekaż ten komunikat Maksowi.",
)


def test_gdy_port_nie_zostanie_zwolniony_opiekun_cofa_klon_zapisuje_prawdziwy_wynik_i_pokazuje_okienko(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "PORT_TIMEOUT_S", 0.2)
    repository = tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    dad_mapping = "schema_version: 1\nworkers:\n  wykonawca.a: Wykonawca Syntetyczny A\n"
    repository.write("config/worker_mapping.yaml", dad_mapping)
    newest = repository.publish(
        {".gitignore": "config/worker_mapping.yaml\n"}, untrack=("config/worker_mapping.yaml",)
    )
    work = tmp_path / "praca"
    work.mkdir()
    assert ToolClone(repository.clone, origin=str(repository.origin)).update().code == UPDATED
    result = repository.clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []

    with socket.socket() as port_never_released:
        port_never_released.bind(("127.0.0.1", 0))
        port_never_released.listen()
        restart = Restart(port_never_released.getsockname()[1], before, newest, repository.clone, result, False, work)
        guardian, exits = _guardian_in_background(restart, dialogs)
        guardian.join(timeout=60)

    assert exits == [1]
    assert dialogs == [NOT_STARTED_AFTER_UPDATE]
    assert repository.head() == before
    assert repository.read("config/worker_mapping.yaml") == dad_mapping
    assert read_result(result) == UpdateResult(NEW_VERSION_FAILED, before, newest, False)


def test_gdy_po_cofnieciu_bez_portu_centrum_ze_skrotu_juz_dziala_opiekun_konczy_bez_okienka(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "PORT_TIMEOUT_S", 0.2)
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
    work = tmp_path / "praca"
    work.mkdir()
    result = clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []
    old_centrum_closing_past_port_timeout = socket.socket()
    old_centrum_closing_past_port_timeout.bind(("127.0.0.1", 0))
    old_centrum_closing_past_port_timeout.listen()
    port = old_centrum_closing_past_port_timeout.getsockname()[1]
    shortcuts: list[subprocess.Popen[bytes]] = []
    roll_back = ToolClone.roll_back

    def shortcut_during_roll_back(self: ToolClone) -> None:
        roll_back(self)
        old_centrum_closing_past_port_timeout.close()
        shortcuts.append(
            subprocess.Popen(
                [sys.executable, str(clone / "run_centrum.py"), "--port", str(port), "--no-browser"],
                cwd=clone,
                env=os.environ | {"PYTHONUTF8": "1"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        centrum_health(port, commit=before)

    monkeypatch.setattr(ToolClone, "roll_back", shortcut_during_roll_back)
    try:
        code = main(
            Restart(port, before, newest, clone, result, False, work).arguments(),
            show_problem=lambda title, text: dialogs.append((title, text)),
        )
        health = centrum_health(port, timeout_s=5)
    finally:
        old_centrum_closing_past_port_timeout.close()
        _close_if_running(port)
        for shortcut in shortcuts:
            shortcut.kill()
            shortcut.wait()

    assert code == 0
    assert dialogs == []
    assert repository.head() == before
    assert health["commit"] == before[:7]
    assert read_result(result) == UpdateResult(NEW_VERSION_FAILED, before, newest, False)


def test_gdy_stare_centrum_odda_port_dopiero_w_trakcie_cofania_opiekun_sam_startuje_stara_wersje(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "PORT_TIMEOUT_S", 0.2)
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
    work = tmp_path / "praca"
    work.mkdir()
    result = clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []
    old_centrum_closing_past_port_timeout = socket.socket()
    old_centrum_closing_past_port_timeout.bind(("127.0.0.1", 0))
    old_centrum_closing_past_port_timeout.listen()
    port = old_centrum_closing_past_port_timeout.getsockname()[1]
    roll_back = ToolClone.roll_back

    def port_released_during_roll_back(self: ToolClone) -> None:
        roll_back(self)
        old_centrum_closing_past_port_timeout.close()

    monkeypatch.setattr(ToolClone, "roll_back", port_released_during_roll_back)
    try:
        code = main(
            Restart(port, before, newest, clone, result, False, work).arguments(),
            show_problem=lambda title, text: dialogs.append((title, text)),
        )
        health = centrum_health(port, timeout_s=5)
        view = _get(port, "/api/tool-update")
    finally:
        old_centrum_closing_past_port_timeout.close()
        _close_if_running(port)

    assert code == 0
    assert dialogs == []
    assert repository.head() == before
    assert health["commit"] == before[:7]
    assert (view["state"], view["after_restart"]) == ("failed", True)
    assert not result.exists()
    starts = [line.split(" ", 1)[1] for line in _log_lines(clone) if line.split(" ", 2)[1] == "start"]
    assert starts == [f"start port={port} wersja={before[:7]} konsola=nie"]


def test_gdy_cofniecie_sie_nie_uda_wynik_nie_mowi_o_poprzedniej_wersji_a_tata_widzi_jedno_okienko(
    tmp_path: Path,
) -> None:
    repository = tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    changes_own_file_so_git_cannot_roll_back = "open('src/narzedzie.py', 'a').write('# zmiana\\n')\nraise SystemExit(1)\n"
    newest = repository.publish(
        {"src/narzedzie.py": "WERSJA = 2\n", "run_centrum.py": changes_own_file_so_git_cannot_roll_back}
    )
    work = tmp_path / "praca"
    work.mkdir()
    assert ToolClone(repository.clone, origin=str(repository.origin)).update().code == UPDATED
    result = repository.clone / "config" / RESULT_FILE
    dialogs: list[tuple[str, str]] = []

    guardian, exits = _guardian_in_background(
        Restart(free_port(), before, newest, repository.clone, result, False, work), dialogs
    )
    guardian.join(timeout=90)

    assert exits == [1]
    assert dialogs == [NOT_STARTED_AFTER_UPDATE]
    assert read_result(result) == UpdateResult(ROLLBACK_FAILED, before, newest, False)
    interrupted = ToolClone(repository.clone).interrupted_update()
    assert interrupted is not None
    assert (interrupted.before, interrupted.after) == (before, newest)


DIRECTORY_REFUSING_RESULT = f"config/{RESULT_FILE}.tmp"


def test_gdy_dysk_nie_przyjmie_wyniku_ok_opiekun_i_tak_startuje_nowa_wersje(tmp_path: Path) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
    (clone / DIRECTORY_REFUSING_RESULT).mkdir()
    work = tmp_path / "praca"
    work.mkdir()
    port = free_port()
    dialogs: list[tuple[str, str]] = []
    try:
        guardian, exits = _guardian_in_background(
            Restart(port, before, newest, clone, clone / "config" / RESULT_FILE, False, work), dialogs
        )
        guardian.join(timeout=90)
        health = centrum_health(port, commit=newest, timeout_s=5)
        view = _get(port, "/api/tool-update")
    finally:
        _close_if_running(port)

    assert exits == [0]
    assert dialogs == []
    assert health["commit"] == newest[:7]
    assert view == {"state": "idle"}
    assert ToolClone(clone).interrupted_update() is None


def test_gdy_dysk_nie_przyjmie_wyniku_po_cofnieciu_startuje_stara_wersja_a_karta_nie_mowi_zaktualizowane(
    tmp_path: Path,
) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    fails_refusing_later_result = f"import os\nos.makedirs({DIRECTORY_REFUSING_RESULT!r}, exist_ok=True)\nraise SystemExit(1)\n"
    newest = repository.publish({"run_centrum.py": fails_refusing_later_result})
    assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
    work = tmp_path / "praca"
    work.mkdir()
    port = free_port()
    dialogs: list[tuple[str, str]] = []
    try:
        guardian, exits = _guardian_in_background(
            Restart(port, before, newest, clone, clone / "config" / RESULT_FILE, False, work), dialogs
        )
        guardian.join(timeout=90)
        health = centrum_health(port, commit=before, timeout_s=5)
        view = _get(port, "/api/tool-update")
    finally:
        _close_if_running(port)

    assert exits == [0]
    assert dialogs == []
    assert repository.head() == before
    assert health["commit"] == before[:7]
    assert view == {"state": "idle"}
    assert ToolClone(clone).interrupted_update() is None


def test_nowa_wersja_ktora_nie_odpowiedziala_opiekun_zatrzymuje_zeby_zwolnila_port_i_pliki_klonu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(restart_guardian, "START_TIMEOUT_S", 0.5)
    started: list[subprocess.Popen[bytes]] = []

    def silent(_restart: Restart) -> subprocess.Popen[bytes]:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        started.append(process)
        return process

    work = tmp_path / "praca"
    work.mkdir()
    restart = Restart(free_port(), None, "b" * 40, tmp_path / "klon", tmp_path / RESULT_FILE, False, work)
    try:
        code = main(restart.arguments(), show_problem=lambda _title, _text: None, start=silent)
        stopped = [process.poll() is not None for process in started]
    finally:
        for process in started:
            process.kill()
            process.wait()

    assert (code, stopped) == (1, [True])
