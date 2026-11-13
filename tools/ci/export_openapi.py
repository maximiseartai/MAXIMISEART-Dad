"""Zapisuje kontrakt Centrum rozliczeń (OpenAPI z modeli Pydantic) dla generatora schematów zod.

Uruchamiane przez ``npm run contract`` w ``frontend/``; wynik trafia do
``frontend/src/api/openapi.json`` i jest commitowany razem z wygenerowanymi typami. Trasy i schematy są
posortowane, więc dwie gałęzie, które dodały po trasie, zmieniają różne miejsca pliku.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import FileTypes
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.tool_files import CONFIG_DIR

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "frontend" / "src" / "api" / "openapi.json"


def _sorted(contract: dict[str, Any]) -> dict[str, Any]:
    components = contract.get("components", {})
    return contract | {
        "paths": dict(sorted(contract["paths"].items())),
        "components": components | {"schemas": dict(sorted(components.get("schemas", {}).items()))},
    }


class _NoPlatform:
    """Kontrakt powstaje bez komputera taty: żadna akcja systemowa nie jest wywoływana."""

    def open_path(self, path: Path) -> None:
        raise AssertionError("Eksport kontraktu nie otwiera plików.")

    def choose_file(self, title: str, filetypes: FileTypes) -> Path | None:
        raise AssertionError("Eksport kontraktu nie otwiera okien wyboru.")

    def choose_folder(self, title: str) -> Path | None:
        raise AssertionError("Eksport kontraktu nie otwiera okien wyboru.")


def main(*, output: Path = OUTPUT) -> int:
    log = CentrumLog(Path(os.devnull))  # eksport nie obsługuje żądań, więc niczego nie zapisuje
    app = create_app(
        config=CONFIG_DIR,
        platform=_NoPlatform(),
        log=log,
        shutdown=Shutdown(log),
    )
    contract = _sorted(app.openapi())
    document = json.dumps(contract, ensure_ascii=False, indent=2) + "\n"
    output.write_bytes(document.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
