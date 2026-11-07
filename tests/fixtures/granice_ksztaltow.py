"""Luki granic kształtów jednego eksploratora skilla ``verify-*``: uruchamiany we własnym procesie, drukuje listę zdań
(JSON) i kończy się kodem ``GAPS``, gdy jest niepusta; pusta lista i kod 0 znaczą, że każdy wpis ma mutację tuż za
granicą każdej części swojego kształtu (#920).

Przyjęte ryzyko albo znane ustalenie, które wybacza szerzej, niż mówi jego historia, przepuszcza zepsuty kod jako
znany (#867 runda 3, #916 rundy 1 i 2). Każdy wpis ``ACCEPTED_RISKS`` i ``KNOWN_FINDINGS`` eksploratora (krotka wpisów
albo słownik, którego wartości są wpisami) ma więc:

- ``name`` (tekst) i ``shape``: dataklasę, której każde pole to część kształtu z historii wpisu, a nie predykat
  dopasowany po skutku;
- w ``BOUNDARIES`` dokładnie jednego skryptu ``check_*_mutations.py`` swojego katalogu, pod swoją nazwą i nazwą
  każdej części, co najmniej jedną mutację z tabeli ``MUTATIONS`` tego skryptu, która uruchamia ten eksplorator i kończy
  się linią ``…NOWE NARUSZENIE``: tę samą szkodę z tą jedną częścią inną, niż mówi historia.

Część, której wartość to każdy element jej wyliczenia (``frozenset`` wszystkich elementów jednego ``enum.Enum``), nie
zawęża niczego, więc mutacji za nią nie ma i ``BOUNDARIES`` jej nie wymienia. Że mutacja daje nowe naruszenie, sprawdza
skrypt mutacji w CI ``main`` i nocą; że historia wpisu nie ma części, której kształt nie wymienia, sprawdza tylko
przegląd.

Znanych znalezisk modeli TLA+ (``znane`` w ``model/konfiguracje.json``) strażnik nie czyta: znalezisko modelu to para
obietnica i przyczyna, a przyczynę ustawia w zmiennej historii jedna akcja specyfikacji z jednym warunkiem, więc
wybaczenie nie jest dopasowaniem po skutku, a poszerzyć je może tylko zmiana tej akcji. Że wybacza tylko swoją parę,
sprawdza ``tests/test_model_tlc.py``.

    python tests/fixtures/granice_ksztaltow.py <katalog tools> <plik eksploratora>
"""

from __future__ import annotations

from collections.abc import Mapping
import dataclasses
import enum
import json
from pathlib import Path
import sys
from typing import Any

NEW = "NOWE NARUSZENIE"


def _entries(module: Any, kind: str) -> list[Any]:
    found = getattr(module, kind, ())
    return list(found.values()) if isinstance(found, dict) else list(found)


def _parts(shape: object) -> list[str] | None:
    """Części kształtu, które coś zawężają; ``None``, gdy ``shape`` nie jest dataklasą."""

    if not dataclasses.is_dataclass(shape) or isinstance(shape, type):
        return None
    parts = []
    for field in dataclasses.fields(shape):
        value = getattr(shape, field.name)
        kinds = {type(item) for item in value} if isinstance(value, frozenset) else set()
        [kind] = kinds if len(kinds) == 1 else [None]
        if not (isinstance(kind, type) and issubclass(kind, enum.Enum) and value == frozenset(kind)):
            parts.append(field.name)
    return parts


def gaps(explorer: Path) -> list[str]:
    scripts = explorer.parent
    sys.path.insert(0, str(scripts))
    module = __import__(explorer.stem)
    found: list[str] = []
    entries: dict[str, list[str]] = {}
    for kind in ("ACCEPTED_RISKS", "KNOWN_FINDINGS"):
        for entry in _entries(module, kind):
            name = getattr(entry, "name", None)
            parts = _parts(getattr(entry, "shape", None))
            if not isinstance(name, str) or parts is None:
                found.append(f"{kind} {str(entry)[:80]}: wpis bez nazwy albo bez jawnego kształtu (dataklasa w ``shape``)")
            else:
                entries[name] = parts
    tables = {}
    for script in sorted(scripts.glob("check_*_mutations.py")):
        table = __import__(script.stem)
        if hasattr(table, "BOUNDARIES"):
            tables[script.name] = table
    if not entries and not tables:
        return found
    if len(tables) != 1:
        return [*found, f"BOUNDARIES ma {len(tables)} skryptów mutacji katalogu zamiast jednego: {sorted(tables)}"]
    [(script_name, table)] = tables.items()
    boundaries = table.BOUNDARIES
    found += [f"{script_name}: BOUNDARIES ma wpis {name}, którego eksplorator nie ma" for name in boundaries if name not in entries]
    for name, parts in entries.items():
        listed = boundaries.get(name, {})
        if not isinstance(listed, Mapping):
            found.append(f"{name}: {script_name} daje mutacje wpisu bez części, której każda dotyczy (mapa część → mutacje)")
            continue
        found += [f"{name}: część {part} bez mutacji tuż za granicą w {script_name}" for part in parts if not listed.get(part)]
        found += [f"{name}: {script_name} wymienia część {part}, której kształt nie zawęża" for part in listed if part not in parts]
        for part, mutations in listed.items():
            for mutation in mutations:
                if not (mutation.expected or "").endswith(NEW) or mutation not in table.MUTATIONS:
                    found.append(f"{name}, część {part}: mutacja {mutation.name} nie jest w MUTATIONS albo nie kończy się „{NEW}”")
                if not mutation.command or Path(mutation.command[0]).name != explorer.name:
                    found.append(f"{name}, część {part}: mutacja {mutation.name} nie uruchamia {explorer.name}")
    return found


GAPS = 3
"""Kod wyjścia, gdy eksplorator ma luki; inny niż 0 i 3 to błąd czytania."""

if __name__ == "__main__":
    sys.path.insert(0, sys.argv[1])
    found = gaps(Path(sys.argv[2]).resolve())
    print(json.dumps(found, ensure_ascii=False))
    raise SystemExit(GAPS if found else 0)
