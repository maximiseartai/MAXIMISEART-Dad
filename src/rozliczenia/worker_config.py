"""Konfiguracja wykonawców: który identyfikator Wykonawcy z kolumny H to która nazwa w Rozliczeniu pracownika.

Wspólna dla Przebiegu rozliczeń, Przygotowania pliku zbiorczego i ekranu
Konfiguracji w Centrum rozliczeń. Złamaną regułę zgłasza jako
``WorkerConfigError`` z powodem; Komunikat dla taty pisze z niego katalog
procesu.
"""

from __future__ import annotations

from dataclasses import dataclass
import stat
from pathlib import Path
from typing import Literal

import yaml

from . import TOOL_ROOT
from .period_folder import check_worker_name
from .text import normalize_text

__all__ = [
    "ContentProblem",
    "SameWorkerFile",
    "WorkerConfigError",
    "default_config_path",
    "load_worker_mapping",
]



@dataclass(frozen=True)
class SameWorkerFile:
    """Dwa identyfikatory wskazują ten sam plik pracownika: nazwy ``first`` i ``second`` z konfiguracji."""

    first: str
    second: str


ContentProblem = (
    Literal[
        "not_utf8",
        "not_yaml",
        "not_mapping",
        "unsupported_version",
        "no_workers",
        "not_text_entry",
        "empty_entry",
        "repeated_id",
        "invalid_worker_name",
        "too_long_worker_name",
    ]
    | SameWorkerFile
)
"""Plik przeczytany, ale treści nie da się użyć: zapisany w innym kodowaniu niż UTF-8 (``not_utf8``, np. ANSI ze
starego Notatnika albo UTF-16 z PowerShella 5.1), zły YAML (``not_yaml``) albo złamana reguła: plik nie jest mapą
(``not_mapping``), wersja inna niż 1 (``unsupported_version``), brak wpisów ``workers`` (``no_workers``), identyfikator
albo nazwa, które nie są tekstem (``not_text_entry``) albo są puste (``empty_entry``), powtórzony identyfikator
(``repeated_id``), nazwa Wykonawcy, która nie może być nazwą pliku (``invalid_worker_name``, ``too_long_worker_name``
według ``check_worker_name``), i dwa identyfikatory na jeden plik pracownika (``SameWorkerFile``)."""

WorkerConfigProblem = Literal["missing", "inaccessible"] | ContentProblem
"""Brak pliku (``missing``, także folder w jego miejscu), plik, którego system nie oddał (``inaccessible``, np. zajęty
przez inny program albo bez dostępu; to nie zła treść), albo treść, której nie da się użyć (``ContentProblem``)."""


class WorkerConfigError(Exception):
    """Konfiguracji wykonawców nie da się użyć; ``reason`` mówi dlaczego, bez ścieżki pliku i bez zdania dla taty."""

    def __init__(self, reason: WorkerConfigProblem) -> None:
        self.reason: WorkerConfigProblem = reason


def default_config_path() -> Path:
    """Wskazuje Konfigurację wykonawców w katalogu konfiguracji."""

    return TOOL_ROOT / "config" / "worker_mapping.yaml"


def load_worker_mapping(config_path: Path) -> dict[str, str]:
    """Wczytuje mapowanie znormalizowanych identyfikatorów na nazwy, w kolejności z pliku."""

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise _unread(config_path) from exc
    except UnicodeDecodeError as exc:
        raise WorkerConfigError("not_utf8") from exc
    except yaml.YAMLError as exc:
        raise WorkerConfigError("not_yaml") from exc

    if not isinstance(config, dict):
        raise WorkerConfigError("not_mapping")
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        raise WorkerConfigError("unsupported_version")

    workers = config.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise WorkerConfigError("no_workers")

    mapping: dict[str, str] = {}
    seen_names: dict[str, str] = {}
    for source_id, target_name in workers.items():
        if not isinstance(source_id, str) or not isinstance(target_name, str):
            raise WorkerConfigError("not_text_entry")
        normalized_id = normalize_text(source_id)
        display_name = target_name.strip()
        normalized_name = normalize_text(display_name)
        if not normalized_id or not normalized_name:
            raise WorkerConfigError("empty_entry")
        if normalized_id in mapping:
            raise WorkerConfigError("repeated_id")
        name_check = check_worker_name(display_name)
        if name_check == "invalid":
            raise WorkerConfigError("invalid_worker_name")
        if name_check == "too_long":
            raise WorkerConfigError("too_long_worker_name")
        if normalized_name in seen_names:
            raise WorkerConfigError(SameWorkerFile(seen_names[normalized_name], display_name))
        mapping[normalized_id] = display_name
        seen_names[normalized_name] = display_name
    return mapping


def _unread(config_path: Path) -> WorkerConfigError:
    """Plik, którego nie udało się przeczytać: brak pliku albo plik niedostępny, rozpoznane po ``stat`` jak skoroszyt.

    Folder bez dostępu daje ``OSError`` także w ``stat``, więc plik w nim jest niedostępny, a nie brakujący.
    """

    try:
        missing = not stat.S_ISREG(config_path.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        missing = True
    except OSError:
        missing = False
    return WorkerConfigError("missing" if missing else "inaccessible")
