"""Start Centrum rozliczeń jako prawdziwy proces w odizolowanym runtime na wolnym porcie."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from rozliczenia.centrum import launcher, restart_guardian
from rozliczenia.centrum.platform import run_console_program
from rozliczenia.centrum.shortcut import SHORTCUT_FILE, Folder, Shortcut, StartupShortcut, shortcuts

from tests.fixtures.fake_cli import fake_cli
from tests.fixtures.centrum import CentrumClient, ToolDirectory, centrum_app
from tests.fixtures.potomne import wait_for, wait_for_value
from tests.fixtures.tool_clone import REPOSITORY_ROOT, copy_centrum_runtime, free_port, centrum_health

COMMIT = "3c1d0a9e5b7f4c2d8e6a1b0f9c8d7e6a5b4c3d2e"
UPDATED_COMMIT = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"


def _check_out(runtime: Path, commit: str) -> None:
    """Klon narzędzia na ``commit`` (odłączony ``HEAD``), jak po pobraniu albo aktualizacji narzędzia."""

    (runtime / ".git").mkdir(exist_ok=True)
    (runtime / ".git" / "HEAD").write_text(commit + "\n", encoding="utf-8")


def _browser_recorder(directory: Path) -> tuple[Path, Path]:
    """Program podstawiony jako przeglądarka (zmienna ``BROWSER``), który zapisuje otwierany adres."""

    record = directory / "otwarte-adresy.txt"
    recorder = fake_cli(
        directory,
        "przegladarka",
        f"import sys\nwith open({str(record)!r}, 'a', encoding='utf-8') as record:\n    record.write(sys.argv[1] + '\\n')\n",
    )
    return recorder, record


def _wait_for_line(path: Path) -> str:
    assert wait_for(lambda: path.exists() and bool(path.read_text(encoding="utf-8").strip()), 10, every=0.1), (
        "Przeglądarka nie dostała adresu Centrum."
    )
    return path.read_text(encoding="utf-8").strip()


@dataclass
class _Console:
    text: str = ""


@contextmanager
def _started(command: list[str], runtime: Path, environment: dict[str, str]) -> Iterator[_Console]:
    """Uruchamia Centrum i po bloku zamyka dokładnie ten proces (z potomkami); konsola jest dostępna po bloku."""

    console = _Console()
    process = subprocess.Popen(
        command,
        cwd=runtime,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        yield console
    finally:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False)
        else:
            process.terminate()
        console.text, _ = process.communicate(timeout=30)


def _environment(browser: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["BROWSER"] = str(browser)
    return environment


def _run_centrum(runtime: Path, port: int) -> list[str]:
    return [sys.executable, str(runtime / "run_centrum.py"), "--port", str(port)]


def _launch_again(runtime: Path, port: int, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _run_centrum(runtime, port),
        cwd=runtime,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def _opened_addresses(path: Path, count: int) -> list[str]:
    """Adresy otwarte w przeglądarce, gdy jest ich już ``count``."""

    done, addresses = wait_for_value(
        lambda: path.read_text(encoding="utf-8").split() if path.exists() else [],
        lambda addresses: len(addresses) >= count,
        10,
        every=0.1,
    )
    assert done, "Przeglądarka nie dostała adresu Centrum."
    return addresses


def test_ponowne_uruchomienie_tylko_otwiera_karte_dzialajacego_centrum(tmp_path: Path) -> None:
    runtime = copy_centrum_runtime(tmp_path / "narzedzie")
    _check_out(runtime, COMMIT)
    browser, opened = _browser_recorder(tmp_path)
    port = free_port()
    environment = _environment(browser)

    with _started(
        [sys.executable, str(runtime / "run_centrum.py"), "--port", str(port)], runtime, environment
    ) as first:
        centrum_health(port)
        _wait_for_line(opened)
        again = _launch_again(runtime, port, environment)
        addresses = _opened_addresses(opened, 2)
        still_serving = centrum_health(port, timeout_s=2)

    assert again.returncode == 0, again.stdout + again.stderr
    assert f"Centrum rozliczeń już działa: http://127.0.0.1:{port}/" in again.stdout
    assert addresses == [f"http://127.0.0.1:{port}/"] * 2
    assert still_serving["service"] == "centrum-rozliczen"
    assert first.text.count(f"Centrum rozliczeń działa: http://127.0.0.1:{port}/") == 1
    assert not ToolDirectory(runtime).settings.exists()


def test_ponowne_uruchomienie_po_przesunieciu_klonu_rozpoznaje_centrum_innej_wersji(tmp_path: Path) -> None:
    runtime = copy_centrum_runtime(tmp_path / "narzedzie")
    _check_out(runtime, COMMIT)
    browser, opened = _browser_recorder(tmp_path)
    port = free_port()
    environment = _environment(browser)

    with _started(
        [sys.executable, str(runtime / "run_centrum.py"), "--port", str(port)], runtime, environment
    ):
        health = centrum_health(port)
        _wait_for_line(opened)
        _check_out(runtime, UPDATED_COMMIT)
        again = _launch_again(runtime, port, environment)
        still_serving = centrum_health(port, timeout_s=2)

    assert {key: health[key] for key in ("service", "commit")} == {"service": "centrum-rozliczen", "commit": COMMIT[:7]}
    assert again.returncode == 1, again.stdout + again.stderr
    assert again.stdout.splitlines()[0] == "Co się stało: Działa już Centrum rozliczeń w innej wersji (3c1d0a9)."
    assert still_serving == health
    assert "kod=INNA_WERSJA_CENTRUM" in ToolDirectory(runtime).log_path.read_text(encoding="utf-8")


def _log_events(runtime: Path) -> list[str]:
    """Nazwy zdarzeń z dziennika Centrum w kolejności wpisów."""

    log = ToolDirectory(runtime).log_path
    return [line.split(" ")[1] for line in log.read_text(encoding="utf-8").splitlines()]


def test_obcy_program_na_porcie_daje_bezpieczny_komunikat_w_trzech_czesciach(tmp_path: Path) -> None:
    runtime = copy_centrum_runtime(tmp_path / "narzedzie")
    browser, opened = _browser_recorder(tmp_path)

    with socket.socket() as foreign_program:
        foreign_program.bind(("127.0.0.1", 0))
        foreign_program.listen()
        foreign_program.settimeout(60)
        port = foreign_program.getsockname()[1]
        with subprocess.Popen(
            _run_centrum(runtime, port),
            cwd=runtime,
            env=_environment(browser),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as launch:
            try:
                # Milczący obcy program sprawdza test w procesie, na skróconym limicie czekania.
                foreign_program.accept()[0].close()
                stdout, stderr = launch.communicate(timeout=60)
            except BaseException:
                launch.kill()
                raise

    assert launch.returncode == 1, stdout + stderr
    assert stdout.splitlines() == [
        f"Co się stało: Centrum rozliczeń nie wystartowało, bo port {port} zajmuje inny program.",
        f"Gdzie: adres http://127.0.0.1:{port}/ na tym komputerze",
        "Co zrobić: Uruchom ponownie komputer i kliknij skrót „Centrum rozliczeń”. Jeśli komunikat wraca, "
        "przekaż go osobie utrzymującej narzędzie.",
    ]
    assert stderr == ""
    assert not opened.exists()
    assert _log_events(runtime) == ["blad-startu"]
    assert "kod=PORT_ZAJETY" in ToolDirectory(runtime).log_path.read_text(encoding="utf-8")


def test_obcy_program_ktory_milczy_nie_wstrzymuje_startu_dluzej_niz_limit_czekania_na_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    wait_s = 0.5
    monkeypatch.setattr(launcher, "_HEALTH_TIMEOUT_S", wait_s)
    monkeypatch.setattr(launcher, "LOG_PATH", tmp_path / "centrum-rozliczen.log")
    exit_codes: list[int] = []

    with socket.socket() as foreign_program:
        foreign_program.bind(("127.0.0.1", 0))
        foreign_program.listen()
        port = foreign_program.getsockname()[1]
        start = threading.Thread(
            target=lambda: exit_codes.append(launcher.main(["--port", str(port), "--no-browser"])), daemon=True
        )
        started = time.monotonic()
        start.start()
        start.join(10)
        took = time.monotonic() - started
        still_waiting = start.is_alive()

    assert not still_waiting
    assert took < wait_s * 1.8
    assert exit_codes == [1]
    assert capsys.readouterr().out.splitlines()[0] == (
        f"Co się stało: Centrum rozliczeń nie wystartowało, bo port {port} zajmuje inny program."
    )


def _close(port: int) -> dict[str, object]:
    origin = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(f"{origin}/api/shutdown", method="POST", headers={"Origin": origin})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 202
        body = json.load(response)
        assert isinstance(body, dict)
        return body


def _windowless(runtime: Path, port: int, *, arguments: tuple[str, ...] | None = None) -> list[str]:
    """Polecenie skrótu: na Windows prawdziwy ``pythonw.exe``, gdzie indziej Python bez ``sys.stdout`` i ``sys.stderr``.

    ``arguments`` to argumenty ``pythonw.exe`` ze skrótu (skrypt i flagi); domyślnie sam ``run_centrum.py`` klonu.
    """

    script, *flags = arguments or (str(runtime / "run_centrum.py"),)
    if sys.platform == "win32":
        return [str(Path(sys.executable).with_name("pythonw.exe")), script, *flags, "--port", str(port)]
    # Tak widzi świat kod pod pythonw: strumienie konsoli to None.
    simulated = f"import runpy, sys; sys.stdout = sys.stderr = None; runpy.run_path({script!r}, run_name='__main__')"
    return [sys.executable, "-c", simulated, *flags, "--port", str(port)]


def test_centrum_bez_konsoli_startuje_rozpoznaje_sie_i_zamyka(tmp_path: Path) -> None:
    runtime = copy_centrum_runtime(tmp_path / "narzedzie")
    browser, opened = _browser_recorder(tmp_path)
    port = free_port()
    environment = _environment(browser)
    first = subprocess.Popen(_windowless(runtime, port), cwd=runtime, env=environment)
    try:
        health = centrum_health(port)
        second = subprocess.run(_windowless(runtime, port), cwd=runtime, env=environment, timeout=60, check=False)
        addresses = _opened_addresses(opened, 2)
        _close(port)
        exit_code = first.wait(timeout=30)
    finally:
        first.kill()
        first.wait()

    assert health["service"] == "centrum-rozliczen"
    assert second.returncode == 0
    assert addresses == [f"http://127.0.0.1:{port}/"] * 2
    assert exit_code == 0
    # Pierwszy start stosuje zmiany Ustawień z Wydania (przeniesienie Listy Wykonawców: bez starych plików bez zmian), a
    # ich wpis czeka na ``start``, więc dziennik startu zaczyna się od niego.
    assert _log_events(runtime) == ["start", "ustawienia-wydanie", "juz-dziala", "zamkniecie", "stop"]
    assert "konsola=nie" in ToolDirectory(runtime).log_path.read_text(encoding="utf-8")



def _shortcut(runtime: Path, folder: Folder) -> Shortcut:
    """Skrót kroku instalacji z ``folder`` dla klonu ``runtime``; test pada, gdy kroku nie ma takiego skrótu."""

    found = [shortcut for shortcut in shortcuts(runtime) if shortcut.folder is folder]
    assert len(found) == 1, f"Krok instalacji zakłada {len(found)} skrótów w folderze {folder}."
    return found[0]


def test_centrum_z_autostartu_startuje_bez_karty_a_skrot_z_pulpitu_otwiera_karte_dzialajacego(tmp_path: Path) -> None:
    runtime = copy_centrum_runtime(tmp_path / "narzedzie")
    browser, opened = _browser_recorder(tmp_path)
    port = free_port()
    environment = _environment(browser)
    startup = _shortcut(runtime, Folder.STARTUP).arguments
    desktop = _shortcut(runtime, Folder.DESKTOP).arguments
    first = subprocess.Popen(_windowless(runtime, port, arguments=startup), cwd=runtime, env=environment)
    try:
        health = centrum_health(port)
        startup_again = subprocess.run(
            _windowless(runtime, port, arguments=startup), cwd=runtime, env=environment, timeout=60, check=False
        )
        opened_before_desktop = opened.exists()
        desktop_click = subprocess.run(
            _windowless(runtime, port, arguments=desktop), cwd=runtime, env=environment, timeout=60, check=False
        )
        addresses = _opened_addresses(opened, 1)
        _close(port)
        exit_code = first.wait(timeout=30)
    finally:
        first.kill()
        first.wait()

    assert health["service"] == "centrum-rozliczen"
    assert (startup_again.returncode, desktop_click.returncode, exit_code) == (0, 0, 0)
    assert not opened_before_desktop, "Skrót z Autostartu otworzył kartę."
    assert addresses == opened.read_text(encoding="utf-8").split() == [f"http://127.0.0.1:{port}/"]
    assert _log_events(runtime) == ["start", "ustawienia-wydanie", "juz-dziala", "juz-dziala", "zamkniecie", "stop"]

_CONSOLE, _NO_CONSOLE = 10, 20
_CONSOLE_PROBE = (
    "import sys; sys.path.insert(0, sys.argv[1]); from rozliczenia.centrum.platform import has_console; "
    f"raise SystemExit({_CONSOLE} if has_console() else {_NO_CONSOLE})"
)


def _in_terminal(command: list[str]) -> int:
    """Kod wyjścia ``command`` w prawdziwej konsoli: nowe okno konsoli w Windows, pseudoterminal gdzie indziej."""

    if sys.platform == "win32":
        return subprocess.run(command, creationflags=subprocess.CREATE_NEW_CONSOLE, timeout=60, check=False).returncode
    import pty

    leader, follower = pty.openpty()
    try:
        return subprocess.run(command, stdin=follower, stdout=follower, stderr=follower, timeout=60, check=False).returncode
    finally:
        os.close(follower)
        os.close(leader)


def test_centrum_od_opiekuna_ponownego_startu_nie_ma_konsoli_a_w_terminalu_i_z_potokiem_ma(tmp_path: Path) -> None:
    probe = [sys.executable, "-c", _CONSOLE_PROBE, str(REPOSITORY_ROOT / "src")]

    seen = {
        "opiekun": restart_guardian._detached(probe, tmp_path).wait(timeout=60),
        "terminal": _in_terminal(probe),
        "potok": subprocess.run(probe, capture_output=True, timeout=60, check=False).returncode,
    }

    assert seen == {"opiekun": _NO_CONSOLE, "terminal": _CONSOLE, "potok": _CONSOLE}


def test_program_konsolowy_z_centrum_ktory_sie_nie_konczy_jest_przerwany_po_limicie_czasu(tmp_path: Path) -> None:
    alive = tmp_path / "zyje.txt"
    # Kończy się sam po 15 s, więc bez limitu czasu test pada na braku TimeoutExpired, a nie wisi.
    hanging = f"import pathlib, time\nfor _ in range(300):\n    pathlib.Path({str(alive)!r}).write_text('tak')\n    time.sleep(0.05)\n"

    with pytest.raises(subprocess.TimeoutExpired):
        run_console_program([sys.executable, "-c", hanging], timeout_s=2)
    alive.unlink(missing_ok=True)

    assert not wait_for(alive.exists, 1, every=0.05), "Program konsolowy żyje po limicie czasu."


@contextmanager
def _input_nobody_writes() -> Iterator[None]:
    """Wejście tego procesu (deskryptor 0) to potok otwarty do zapisu, do którego nikt nie pisze: program, który je
    odziedziczy i czyta, czeka bez końca (pytest daje mu zwykle pusty ``/dev/null``)."""

    read_end, write_end = os.pipe()
    saved = os.dup(0)
    os.dup2(read_end, 0)
    try:
        yield
    finally:
        os.dup2(saved, 0)
        for descriptor in (saved, read_end, write_end):
            os.close(descriptor)


def test_program_konsolowy_z_centrum_ktory_czyta_wejscie_dostaje_jego_koniec_zamiast_czekac() -> None:
    """Pip, Git albo PowerShell pytający o coś w konsoli nie wiesza Centrum: dostaje koniec wejścia."""

    with _input_nobody_writes():
        result = run_console_program([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], timeout_s=5)

    assert (result.returncode, result.stdout.strip()) == (0, "''")


def _read_shortcut(link: Path) -> dict[str, str]:
    """Pola skrótu z WScript.Shell, który czyta ścieżkę w stronie kodowej ANSI: czyta kopię pod nazwą ASCII."""

    with tempfile.TemporaryDirectory() as directory:
        copy = Path(directory) / "skrot.lnk"
        shutil.copyfile(link, copy)
        return _read_ascii_shortcut(copy)


def _read_ascii_shortcut(link: Path) -> dict[str, str]:
    script = (
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false; "
        "$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:SKROT); "
        "@{TargetPath=$l.TargetPath; Arguments=$l.Arguments; WorkingDirectory=$l.WorkingDirectory; "
        "IconLocation=$l.IconLocation} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        env=os.environ | {"SKROT": str(link)},
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        check=True,
    )
    shortcut = json.loads(result.stdout)
    assert isinstance(shortcut, dict)
    return shortcut


@pytest.mark.skipif(sys.platform != "win32", reason="The desktop shortcut and pythonw.exe are Windows-only.")
def test_krok_instalacji_tworzy_skrot_na_pulpicie_i_w_autostarcie_ktore_uruchamiaja_centrum_przez_pythonw(
    tmp_path: Path,
) -> None:
    runtime = copy_centrum_runtime(tmp_path / "narzedzie")
    desktop = tmp_path / "pulpit"
    startup = tmp_path / "autostart"
    desktop.mkdir()
    startup.mkdir()
    browser, opened = _browser_recorder(tmp_path)

    def install() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(runtime / "install_centrum_shortcut.py"),
                "--folder",
                str(desktop),
                "--folder-autostartu",
                str(startup),
            ],
            cwd=runtime,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_environment(browser),
            timeout=120,
            check=False,
        )

    installed, installed_again = install(), install()
    assert (installed.returncode, installed_again.returncode) == (0, 0), installed.stdout + installed_again.stdout
    # Jeden skrót w każdym folderze, o tej samej nazwie: ponowny krok nadpisuje, a nie dokłada.
    on_desktop, in_startup = list(desktop.iterdir()), list(startup.iterdir())
    # Nazwa, którą tata widzi na pulpicie, w każdej stronie kodowej Windows (runner CI ma 1252 bez „ń”).
    assert [path.name for path in on_desktop + in_startup] == ["Centrum rozliczeń.lnk"] * 2
    shortcut = _read_shortcut(on_desktop[0])
    from_startup = _read_shortcut(in_startup[0])
    target = Path(shortcut["TargetPath"])
    icon, index = shortcut["IconLocation"].rsplit(",", 1)

    assert target.name.lower() == "pythonw.exe" and target.is_file()
    assert shortcut["Arguments"] == f'"{runtime / "run_centrum.py"}"'
    assert Path(shortcut["WorkingDirectory"]) == runtime
    assert (Path(icon), index) == (runtime / "src" / "rozliczenia" / "centrum" / "centrum-rozliczen.ico", "0")
    assert from_startup == shortcut | {"Arguments": f'"{runtime / "run_centrum.py"}" "--no-browser"'}

    port = free_port()
    process = subprocess.Popen(
        [str(target), shortcut["Arguments"].strip('"'), "--port", str(port)],
        cwd=shortcut["WorkingDirectory"],
        env=_environment(browser),
    )
    try:
        health = centrum_health(port)
        address = _wait_for_line(opened)
        _close(port)
        exit_code = process.wait(timeout=30)
    finally:
        process.kill()
        process.wait()

    assert health["service"] == "centrum-rozliczen"
    assert address == f"http://127.0.0.1:{port}/"
    assert exit_code == 0


# Flaga CREATE_NO_WINDOW z dokumentacji Windows (Process Creation Flags), wpisana tu, a nie wzięta z kodu Centrum.
_CREATE_NO_WINDOW = 0x08000000


@contextmanager
def _started_programs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[int]]:
    """Flagi ``creationflags`` każdego programu, który ten proces uruchomi w bloku."""

    flags: list[int] = []
    real_popen = subprocess.Popen

    class RecordingPopen(real_popen):  # type: ignore[valid-type, misc]
        def __init__(self, *args: object, **kwargs: object) -> None:
            flags.append(int(kwargs.get("creationflags") or 0))  # type: ignore[call-overload]
            super().__init__(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", RecordingPopen)
        yield flags


@pytest.mark.skipif(sys.platform != "win32", reason="The Startup shortcut and pythonw.exe are Windows-only.")
def test_przelacznik_autostartu_w_ustawieniach_zaklada_ten_sam_skrot_co_krok_instalacji_a_usuniety_recznie_widzi_jako_wylaczony(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop, from_install, from_settings = tmp_path / "pulpit", tmp_path / "autostart-instalacji", tmp_path / "autostart"
    for folder in (desktop, from_install, from_settings):
        folder.mkdir()
    installed = subprocess.run(
        [
            sys.executable,
            str(REPOSITORY_ROOT / "install_centrum_shortcut.py"),
            "--folder",
            str(desktop),
            "--folder-autostartu",
            str(from_install),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    client = CentrumClient(centrum_app(ToolDirectory(tmp_path), autostart=StartupShortcut(from_settings)))

    launched: list[list[int]] = []

    def switch(enabled: bool) -> str:
        with _started_programs(monkeypatch) as flags:
            response = client.put("/api/settings/autostart", json={"enabled": enabled})
        launched.append(flags)
        assert response.status_code == 200, response.text
        state: str = response.json()["settings"]["autostart"]["state"]
        return state

    switched = [switch(True), switch(True)]
    created = sorted(from_settings.iterdir())
    shortcut = _read_shortcut(from_settings / SHORTCUT_FILE)
    (from_settings / SHORTCUT_FILE).unlink()
    removed = client.get("/api/settings").json()["autostart"]["state"]
    outside = client.get("/api/settings/history").json()["rows"][0]
    switched += [switch(True), switch(False)]

    assert installed.returncode == 0, installed.stdout
    assert switched == ["on", "on", "on", "off"]
    # Centrum ze skrótu działa pod pythonw: każdy PowerShell startuje bez okna konsoli, które mignęłoby tacie.
    started = [flag for flags in launched for flag in flags]
    assert started and set(started) == {_CREATE_NO_WINDOW}, launched
    # Włączenie przy skrócie, który już jest, niczego nie zapisuje, więc nie uruchamia PowerShella wcale.
    assert launched[1] == [], launched
    # Dwa włączenia dają jeden skrót o nazwie skrótu z instalacji, a nie dokładają drugiego.
    assert [path.name for path in created] == [SHORTCUT_FILE]
    assert shortcut == _read_shortcut(from_install / SHORTCUT_FILE)
    assert (removed, outside["source"], outside["changes"]) == (
        "off",
        "outside",
        [{"key": "narzedzie.autostart", "before": "wlaczony", "after": "wylaczony"}],
    )
    assert list(from_settings.iterdir()) == []
