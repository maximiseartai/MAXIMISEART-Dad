"""Komunikat startu: the shortcut finds Dad's port held by another program and says so in a native window."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import socket
import threading

from windows_drive.common import Run, wait_for
import windows_desktop

FEATURE = "komunikat-startu"
# What Dad reads in the window and what the Centrum log he hands Maks says, copied on purpose (docs/agents/skille.md,
# „Co wyrocznia bierze z src”): with ``start_problems`` imported, a changed wording would pass with it.
TITLE = "Centrum rozliczeń"
CODE = "PORT_ZAJETY"


def _port_taken(port: int) -> str:
    return (
        f"Co się stało: Centrum rozliczeń nie wystartowało, bo port {port} zajmuje inny program.\n"
        f"Gdzie: adres http://127.0.0.1:{port}/ na tym komputerze\n"
        "Co zrobić: Uruchom ponownie komputer i kliknij skrót „Centrum rozliczeń”. "
        "Jeśli komunikat wraca, przekaż go osobie utrzymującej narzędzie."
    )


@contextmanager
def _other_program(port: int) -> Iterator[None]:
    """A program on Dad's port that accepts connections and closes them without answering like Centrum."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", port))
    listener.listen()
    stopped = threading.Event()

    def serve() -> None:
        while not stopped.is_set():
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            connection.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        listener.close()
        thread.join(timeout=5)


def drive(run: Run) -> None:
    port = run.facts["port"]
    run.check(windows_desktop.port_owner(port) is None, f"nothing listens on port {port} yet")
    log_before = len(run.log_lines())

    run.harness(f"another program holds port {port} and does not answer like Centrum")
    with _other_program(port):
        run.step(FEATURE, "okienko")
        windows_desktop.start_shortcut(run.shortcut)

        def message_box() -> windows_desktop.Window | None:
            for window in windows_desktop.visible_windows():
                if window.cls == windows_desktop.DIALOG and window.title == TITLE:
                    return window
            return None

        box = wait_for(message_box, timeout_s=60, what=f"the native window {TITLE!r}")
        owners = [process for process in windows_desktop.processes() if process.pid == box.pid]
        run.check(
            len(owners) == 1 and owners[0].name.lower() == "pythonw.exe" and str(run.run_centrum).casefold() in owners[0].command_line.casefold(),
            "the window belongs to the shortcut's pythonw.exe running the tool's run_centrum.py",
        )
        texts = [control.title for control in windows_desktop.controls(box) if control.cls == "Static" and control.title]
        shown = max(texts, key=len, default="").replace("\r\n", "\n")
        print(f"  okienko: {shown!r}", flush=True)
        run.check(shown == _port_taken(port), "the window shows the three-part Komunikat about the taken port")
        others = [window for window in windows_desktop.visible_windows([box.pid]) if window.handle != box.handle]
        run.check(others == [], "the shortcut's process shows no console or other window")
        run.desktop("komunikat-zajety-port")

        run.step(FEATURE, "zamkniecie-okienka")
        windows_desktop.close(box)
        run.check(windows_desktop.wait_until_gone(box, timeout_s=10), "Dad closes the window")
        wait_for(
            lambda: None if any(process.pid == box.pid for process in windows_desktop.processes()) else True,
            timeout_s=15,
            what="the shortcut's process to end",
        )
        print(f"  ok: the shortcut's process {box.pid} ended", flush=True)
        entries = run.log_lines()[log_before:]
        run.check(
            any(f" blad-startu kod={CODE} port={port}" in line for line in entries),
            f"the Centrum log has blad-startu kod={CODE}",
        )
        run.check(windows_desktop.port_owner(port) not in (None, box.pid), "the other program still holds the port")
    run.check(windows_desktop.port_owner(port) is None, f"port {port} is free again")
