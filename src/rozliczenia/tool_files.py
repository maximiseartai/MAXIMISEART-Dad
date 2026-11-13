"""Układ plików narzędzia na komputerze taty: katalog narzędzia, ``config/`` (ADR 0006), metryki, dziennik, start Centrum.

Jedyne miejsce, które zna nazwy plików narzędzia, adres i port Centrum rozliczeń, polecenie jego startu i adres
repozytorium na GitHubie. Moduł używa tylko biblioteki standardowej, bo czyta go launcher przed FastAPI i opiekun
ponownego startu ze swojej kopii (ADR 0009). Opiekun działa z kopii poza klonem, więc ścieżki klonu liczy od jego
katalogu (``config_dir``, ``start_command``), a nie od ``TOOL_ROOT``.
"""

from __future__ import annotations

from pathlib import Path
import socket
import sys
from typing import Final

# Katalog narzędzia (klon Gita z ``pyproject.toml``), w którym leży pakiet ``src/rozliczenia``.
TOOL_ROOT: Final = Path(__file__).resolve().parents[2]


def config_dir(root: Path) -> Path:
    """Folder ``config`` klonu narzędzia w ``root``: Wzorce, Ustawienia Centrum, pliki stanu."""

    return root / "config"


def log_path(root: Path) -> Path:
    """Dziennik Centrum rozliczeń klonu narzędzia w ``root``; obok niego w ``logs`` leżą Logi Uruchomienia."""

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
"""Pamięć własnych wpisów Wpisania raportów i dzień wdrożenia w ``config`` (ADR 0028)."""
REPORT_ENTERING_RESULT: Final = "wpisanie-raportow-wynik.json"
"""Wynik ostatniego udanego kliknięcia Wpisania raportów dla widoku Raporty w ``config`` (ADR 0028)."""
REPORT_ENTERING_DECISIONS: Final = "wpisanie-raportow-decyzje.json"
"""Decyzje taty „Zostaw moją” Wpisania raportów w ``config`` (ADR 0028)."""
REMINDERS_RESULT: Final = "przypomnienia-wynik.json"
"""Wynik ostatniego sprawdzenia Przypomnień o raporcie dla widoku Raporty w ``config`` (ADR 0030)."""
REMINDERS_SCHEDULES: Final = "przypomnienia-pory.json"
"""Pory, przy których sprawdzała praca Przypomnień o raporcie, od której chwili, w ``config`` (ADR 0032)."""

LOG_PATH: Final = log_path(TOOL_ROOT)

HOST: Final = "127.0.0.1"  # wyłącznie ten komputer (ADR 0004)
DEFAULT_PORT: Final = 47811

REPOSITORY: Final = "maximiseartai/MAXIMISEART-Dad"
REPOSITORY_URL: Final = f"https://github.com/{REPOSITORY}.git"

# Flagi ``run_centrum.py``. Opiekun ze starej kopii startuje nimi nową wersję, więc to kontrakt między wersjami.
PORT_FLAG: Final = "--port"
NO_BROWSER_FLAG: Final = "--no-browser"
NO_DIALOGS_FLAG: Final = "--bez-okienek"


def centrum_script(root: Path) -> Path:
    """Skrypt startu Centrum rozliczeń w klonie narzędzia ``root``: uruchamia go skrót, konsola i opiekun."""

    return root / "run_centrum.py"


def start_command(root: Path, port: int) -> list[str]:
    """Polecenie, którym opiekun startuje Centrum z klonu ``root``: jak skrót, tylko bez karty i bez okienek."""

    return [sys.executable, str(centrum_script(root)), PORT_FLAG, str(port), NO_BROWSER_FLAG, NO_DIALOGS_FLAG]


def listen_locally(port: int) -> socket.socket:
    """Zajmuje port na ``HOST``; ``OSError``, gdy port ma już inny program albo inne Centrum."""

    listener = _bound(port)
    try:
        listener.listen()  # kolejne uruchomienie czeka na health, zamiast dostać odmowę połączenia
    except OSError:
        listener.close()
        raise
    return listener


def port_free(port: int) -> bool:
    """Czy port na ``HOST`` da się teraz zająć tak jak ``listen_locally``."""

    try:
        _bound(port).close()
    except OSError:
        return False
    return True


def _bound(port: int) -> socket.socket:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform != "win32":  # na Windows SO_REUSEADDR pozwoliłby przejąć port działającego programu
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((HOST, port))
    except OSError:
        probe.close()
        raise
    return probe
