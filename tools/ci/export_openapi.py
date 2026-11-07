"""Zapisuje kontrakt Centrum rozliczeń (OpenAPI z modeli Pydantic) dla generatora schematów zod.

Uruchamiane przez ``npm run contract`` w ``frontend/``; wynik trafia do
``frontend/src/api/openapi.json`` i jest commitowany razem z wygenerowanymi typami. Trasy i schematy są
posortowane, więc dwie gałęzie, które dodały po trasie, zmieniają różne miejsca pliku.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, get_args

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rozliczenia.centrum.app import create_app
from rozliczenia.centrum.contract import ApiOperation
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import FileTypes
from rozliczenia.centrum.shutdown import Shutdown
from rozliczenia.tool_files import SETTINGS

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SOURCE = ROOT / "frontend" / "src"
OUTPUT = FRONTEND_SOURCE / "api" / "openapi.json"


# Trasy, których przeglądarka nie mierzy przez `call` (frontend/src/api/client.ts), każda z powodem. Każda inna
# trasa jest w ApiOperation, a każda operacja z ApiOperation ma trasę i przeglądarka woła ją przez `call`.
OUTSIDE_TIMING = {
    "streamRunEvents": "strumień SSE (EventSource) otwarty przez całe życie karty, nie zapytanie z odpowiedzią",
    "recordViewTiming": "sam pomiar widoku, wysyłany po pomiarze; odpowiedź 204 bez treści",
    "getCurrentRun": "przeglądarka bierze bieżące Uruchomienie ze strumienia; trasę czytają testy i weryfikacja",
}
# `call(zSchemat, "operacja", …)` w kodzie przeglądarki.
BROWSER_CALL = re.compile(r"\bcall\(\s*\w+,\s*\"(\w+)\"")


def _timing_problems(operations: set[str]) -> list[str]:
    """Różnice między ApiOperation, trasami kontraktu i operacjami, które przeglądarka woła przez `call`."""

    listed = set(get_args(ApiOperation))
    sources = [path for path in FRONTEND_SOURCE.rglob("*.ts*") if "generated" not in path.parts]
    called = {name for path in sources for name in BROWSER_CALL.findall(path.read_text(encoding="utf-8"))}
    problems = {
        "nazywa operacje bez trasy API": listed - operations,
        "pomija trasy (dopisz je albo dodaj do OUTSIDE_TIMING z powodem)": operations - listed - OUTSIDE_TIMING.keys(),
        "ma operacje, których przeglądarka nie woła przez call": listed - called,
        "pomija operacje, które przeglądarka woła przez call": called - listed,
        "ma operacje z OUTSIDE_TIMING": listed & OUTSIDE_TIMING.keys(),
    }
    stale = OUTSIDE_TIMING.keys() - operations
    lines = [f"ApiOperation w kontrakcie {what}: {', '.join(sorted(names))}" for what, names in problems.items() if names]
    return lines + ([f"OUTSIDE_TIMING nazywa operacje bez trasy API: {', '.join(sorted(stale))}"] if stale else [])


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


def main() -> int:
    log = CentrumLog(Path(os.devnull))  # eksport nie obsługuje żądań, więc niczego nie zapisuje
    app = create_app(
        settings_path=SETTINGS,
        platform=_NoPlatform(),
        log=log,
        shutdown=Shutdown(log),
    )
    contract = _sorted(app.openapi())
    operations = {operation["operationId"] for path in contract["paths"].values() for operation in path.values()}
    problems = _timing_problems(operations)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    document = json.dumps(contract, ensure_ascii=False, indent=2) + "\n"
    OUTPUT.write_bytes(document.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
