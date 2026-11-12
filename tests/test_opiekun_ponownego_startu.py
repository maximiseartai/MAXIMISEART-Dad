"""Opiekun ponownego startu jako prawdziwy proces: stare Centrum zwalnia port, a opiekun startuje nową wersję.

Klon narzędzia to prawdziwe Centrum rozliczeń w klonie Gita z lokalnym
„origin” zamiast GitHuba. Opiekun działa z kopii sprzed aktualizacji, tak jak
uruchamia go Centrum po udanej Aktualizacji narzędzia.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from rozliczenia.centrum import launcher, restart_guardian

# Prawdziwy ``launch`` z importu: strażnik z conftest podmienia go tylko dla Centrum w testach API.
from rozliczenia.centrum.restart_guardian import Restart, launch, main, prepare
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
from rozliczenia.tool_files import start_command

from tests.fixtures.centrum import ToolDirectory
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
    try:
        _close(port)
    except OSError:
        return
    def stopped() -> bool:
        try:
            _get(port, "/api/health")
        except OSError:
            return True
        return False

    wait_for(stopped, 30, every=0.1)


def _log_lines(clone: Path) -> list[str]:
    return ToolDirectory(clone).log_path.read_text(encoding="utf-8").splitlines()


def test_polecenie_opiekuna_przyjmuje_launcher_kazdej_wersji_jako_start_bez_karty_i_bez_okienek(tmp_path: Path) -> None:
    # Opiekun ze starej kopii startuje nową wersję (ADR 0009), więc postać polecenia jest kontraktem między wersjami:
    # test przypina ją literałem, a nie stałymi z tool_files, które zmieniłyby się razem z nią.
    command = start_command(tmp_path, 47811)
    arguments = launcher.parse_arguments(command[2:])

    assert command == [sys.executable, str(tmp_path / "run_centrum.py"), "--port", "47811", "--no-browser", "--bez-okienek"]
    assert (arguments.port, arguments.no_browser, arguments.bez_okienek) == (47811, True, True)


def test_pliki_narzedzia_na_dysku_taty_maja_w_kazdej_wersji_te_same_nazwy() -> None:
    # Cofnięcie Aktualizacji startuje starą wersję na plikach, które zostawiła nowa (ADR 0009), więc nazwy przypina literał.
    files = {
        "WORKER_CONFIG": tool_files.WORKER_CONFIG,
        "WORKER_TEMPLATE": tool_files.WORKER_TEMPLATE,
        "COLLECTIVE_TEMPLATE": tool_files.COLLECTIVE_TEMPLATE,
        "INTERNAL_TEMPLATE": tool_files.INTERNAL_TEMPLATE,
        "SETTINGS": tool_files.SETTINGS,
        "SETTLEMENT_METRICS": tool_files.SETTLEMENT_METRICS,
        "PREPARATION_METRICS": tool_files.PREPARATION_METRICS,
        "INTERMAX_METRICS": tool_files.INTERMAX_METRICS,
        "EFENIX_METRICS": tool_files.EFENIX_METRICS,
        "REPORT_ENTERING_METRICS": tool_files.REPORT_ENTERING_METRICS,
        "LOG_PATH": tool_files.LOG_PATH,
    }

    assert {name: path.relative_to(tool_files.TOOL_ROOT).as_posix() for name, path in files.items()} == {
        "WORKER_CONFIG": "config/worker_mapping.yaml",
        "WORKER_TEMPLATE": "config/Wzorzec rozliczenia pracownika.xlsx",
        "COLLECTIVE_TEMPLATE": "config/Wzorzec pliku zbiorczego.xlsx",
        "INTERNAL_TEMPLATE": "config/Wzorzec rozliczenia wewnętrznego.xlsx",
        "SETTINGS": "config/centrum-ustawienia.yaml",
        "SETTLEMENT_METRICS": ".rozliczenia-metrics.jsonl",
        "PREPARATION_METRICS": ".przygotowanie-pliku-zbiorczego-metrics.jsonl",
        "INTERMAX_METRICS": ".uporzadkowanie-intermax-metrics.jsonl",
        "EFENIX_METRICS": ".wycena-efenix-metrics.jsonl",
        "REPORT_ENTERING_METRICS": ".wpisanie-raportow-metrics.jsonl",
        "LOG_PATH": "logs/centrum-rozliczen.log",
    }


def test_port_zajety_przez_centrum_przyjmuje_polaczenie_zanim_serwer_zacznie_je_obslugiwac() -> None:
    # Skrót kliknięty w trakcie startu czeka na health w kolejce portu, zamiast dostać odmowę połączenia.
    with tool_files.listen_locally(0) as listener:
        with socket.create_connection(listener.getsockname(), timeout=5):
            pass


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
        guardian = launch(
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
    """Opiekun w wątku testu (prawdziwe procesy Centrum), z okienkiem podstawionym zapisem jego treści."""

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
    # Między startem procesu nowej wersji a zajęciem portu mija 1,5 s, więc skrót zdąży zająć port przed nią.
    slow_start = f"from pathlib import Path; Path({str(started)!r}).touch()\nimport time; time.sleep(1.5)\n"
    newest = repository.publish({"run_centrum.py": slow_start + run_centrum})
    assert ToolClone(repository.clone, origin=str(repository.origin)).update().code == UPDATED
    work = tmp_path / "praca"
    work.mkdir()
    port = free_port()
    dialogs: list[tuple[str, str]] = []
    restart = Restart(port, before, newest, repository.clone, repository.clone / "config" / RESULT_FILE, False, work)
    try:
        guardian, exits = _guardian_in_background(restart, dialogs)
        assert wait_for(started.exists, 60), "Opiekun nie uruchomił nowej wersji."
        # Skrót trzyma port od listen_locally do listener.close() po odczycie dziennika; tu ta chwila trwa 3 s.
        with socket.socket() as shortcut:
            shortcut.bind(("127.0.0.1", port))
            shortcut.listen()
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


def _broken_version(repository: ToolRepository, dialogs: Path) -> dict[str, str]:
    """Nowa wersja z błędem importu: brakuje jej biblioteki.

    Okienko błędu startu tej wersji zapisuje swoją treść do ``dialogs`` zamiast pokazywać się na ekranie.
    """

    app = (repository.publisher / "src/rozliczenia/centrum/app.py").read_text(encoding="utf-8")
    platform = (repository.publisher / "src/rozliczenia/centrum/platform.py").read_text(encoding="utf-8")
    windowless = (
        "\n\ndef show_start_problem(title: str, text: str) -> None:\n"
        f"    with open({str(dialogs)!r}, 'a', encoding='utf-8') as shown:\n"
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
        newest = repository.publish(_broken_version(repository, new_version_dialogs))
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
    # Klon stoi na nowej wersji, dopóki opiekun go nie cofnie, więc skrót starej wersji startuje z drugiej kopii.
    old_copy = tmp_path / "stara-wersja"
    git(tmp_path, "clone", "--quiet", str(repository.origin), str(old_copy))
    started = tmp_path / "nowa-wersja-startuje"
    # Nowa wersja nie startuje: kończy się błędem dopiero wtedy, gdy Centrum ze skrótu już odpowiada.
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


def test_gdy_skrot_zajmie_port_tuz_po_cofnieciu_opiekun_konczy_bez_okienka(tmp_path: Path) -> None:
    started = tmp_path / "stara-wersja-startuje"
    run_centrum = (REPOSITORY_ROOT / "run_centrum.py").read_text(encoding="utf-8")
    # Stara wersja od opiekuna zajmuje port dopiero wtedy, gdy Centrum ze skrótu już odpowiada, więc skrót jest pierwszy.
    # Port trzyma ono do końca testu, więc opiekunowa stara wersja czeka cały _SHORTCUT_HOLDS_PORT_S: tu 0,5 s zamiast 10.
    slow_guardian_start = (
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
        # Prawdziwy limit musi zmieścić się w 30 s, które test daje na koniec starej wersji; dopiero potem skrócony.
        "    assert launcher._SHORTCUT_HOLDS_PORT_S <= 30, launcher._SHORTCUT_HOLDS_PORT_S\n"
        "    launcher._SHORTCUT_HOLDS_PORT_S = 0.5\n"
    )
    repository = centrum_tool_repository(
        tmp_path / "repozytoria", {"run_centrum.py": slow_guardian_start + run_centrum}
    )
    clone = repository.clone
    before = repository.head()
    newest = repository.publish(
        {**_broken_version(repository, tmp_path / "okienka-nowej-wersji.txt"), "run_centrum.py": run_centrum}
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
        # Stara wersja od opiekuna kończy się sama, gdy po _SHORTCUT_HOLDS_PORT_S zastanie Centrum ze skrótu, a ono już
        # odpowiada; limit krótszy niż pytest-timeout minus sprzątanie, więc czekanie bez końca to porażka, nie zawieszenie.
        assert wait_for(
            lambda: "juz-dziala" in [line.split(" ", 2)[1] for line in _log_lines(clone)], 30, every=0.1
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

    with socket.socket() as held:  # stare Centrum (albo inny program) nie oddaje portu
        held.bind(("127.0.0.1", 0))
        held.listen()
        restart = Restart(held.getsockname()[1], before, newest, repository.clone, result, False, work)
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
    held = socket.socket()  # stare Centrum zamyka się dłużej niż PORT_TIMEOUT_S
    held.bind(("127.0.0.1", 0))
    held.listen()
    port = held.getsockname()[1]
    shortcuts: list[subprocess.Popen[bytes]] = []
    roll_back = ToolClone.roll_back

    def shortcut_during_roll_back(self: ToolClone) -> None:
        roll_back(self)
        # Stare Centrum oddaje port w trakcie cofania, a tata klika skrót: dziennika już nie ma, startuje stara wersja.
        held.close()
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
        held.close()
        _close_if_running(port)
        for shortcut in shortcuts:
            shortcut.kill()
            shortcut.wait()

    assert code == 0
    assert dialogs == []
    assert repository.head() == before
    assert health["commit"] == before[:7]
    assert read_result(result) == UpdateResult(NEW_VERSION_FAILED, before, newest, False)


def test_gdy_cofniecie_sie_nie_uda_wynik_nie_mowi_o_poprzedniej_wersji_a_tata_widzi_jedno_okienko(
    tmp_path: Path,
) -> None:
    repository = tool_repository(tmp_path / "repozytoria")
    before = repository.head()
    # Nowa wersja przy starcie zmienia swój plik i kończy się błędem: Git nie cofnie klonu przez tę zmianę.
    newest = repository.publish(
        {
            "src/narzedzie.py": "WERSJA = 2\n",
            "run_centrum.py": "open('src/narzedzie.py', 'a').write('# zmiana\\n')\nraise SystemExit(1)\n",
        }
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


# Katalog w miejscu pliku tymczasowego wyniku: write_result rzuca OSError jak przy pliku zablokowanym przez antywirus.
RESULT_REFUSED = f"config/{RESULT_FILE}.tmp"


def test_gdy_dysk_nie_przyjmie_wyniku_ok_opiekun_i_tak_startuje_nowa_wersje(tmp_path: Path) -> None:
    repository = centrum_tool_repository(tmp_path / "repozytoria")
    clone = repository.clone
    before = repository.head()
    newest = repository.publish({"NOWA_WERSJA.txt": "druga wersja narzędzia\n"})
    assert ToolClone(clone, origin=str(repository.origin)).update().code == UPDATED
    (clone / RESULT_REFUSED).mkdir()
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
    # Nowa wersja nie wystartuje, a przy starcie zostawia przeszkodę: zapis „ok” przechodzi, zapis porażki już nie.
    newest = repository.publish(
        {"run_centrum.py": f"import os\nos.makedirs({RESULT_REFUSED!r}, exist_ok=True)\nraise SystemExit(1)\n"}
    )
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
