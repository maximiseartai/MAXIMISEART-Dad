from __future__ import annotations

from pathlib import Path
import socket
import sys
from typing import Final

TOOL_ROOT: Final = Path(__file__).resolve().parents[2]


def config_dir(root: Path) -> Path:
    return root / "config"


def log_path(root: Path) -> Path:
    return root / "logs" / "centrum-rozliczen.log"


CONFIG_DIR: Final = config_dir(TOOL_ROOT)
WORKER_TEMPLATE: Final = CONFIG_DIR / "Wzorzec rozliczenia pracownika.xlsx"
COLLECTIVE_TEMPLATE: Final = CONFIG_DIR / "Wzorzec pliku zbiorczego.xlsx"
INTERNAL_TEMPLATE: Final = CONFIG_DIR / "Wzorzec rozliczenia wewnętrznego.xlsx"

SETTLEMENT_METRICS: Final = TOOL_ROOT / ".rozliczenia-metrics.jsonl"
PREPARATION_METRICS: Final = TOOL_ROOT / ".przygotowanie-pliku-zbiorczego-metrics.jsonl"
INTERMAX_METRICS: Final = TOOL_ROOT / ".uporzadkowanie-intermax-metrics.jsonl"
EFENIX_METRICS: Final = TOOL_ROOT / ".wycena-efenix-metrics.jsonl"
REPORT_ENTERING_METRICS: Final = TOOL_ROOT / ".wpisanie-raportow-metrics.jsonl"
REPORT_ENTERING_STATE: Final = "wpisanie-raportow-stan.json"
REPORT_ENTERING_RESULT: Final = "wpisanie-raportow-wynik.json"
REPORT_ENTERING_DECISIONS: Final = "wpisanie-raportow-decyzje.json"
REMINDERS_RESULT: Final = "przypomnienia-wynik.json"
REMINDERS_SCHEDULES: Final = "przypomnienia-pory.json"

LOG_PATH: Final = log_path(TOOL_ROOT)

HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 47811

REPOSITORY: Final = "maximiseartai/MAXIMISEART-Dad"
REPOSITORY_URL: Final = f"https://github.com/{REPOSITORY}.git"

PORT_FLAG: Final = "--port"
NO_BROWSER_FLAG: Final = "--no-browser"
NO_DIALOGS_FLAG: Final = "--bez-okienek"


def centrum_script(root: Path) -> Path:
    return root / "run_centrum.py"


def start_command(root: Path, port: int) -> list[str]:
    return [sys.executable, str(centrum_script(root)), PORT_FLAG, str(port), NO_BROWSER_FLAG, NO_DIALOGS_FLAG]


def listen_locally(port: int) -> socket.socket:
    listener = _bound(port)
    try:
        listener.listen()
    except OSError:
        listener.close()
        raise
    return listener


def port_free(port: int) -> bool:
    try:
        _bound(port).close()
    except OSError:
        return False
    return True


def _bound(port: int) -> socket.socket:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform != "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((HOST, port))
    except OSError:
        probe.close()
        raise
    return probe
