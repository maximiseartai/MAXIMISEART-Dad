"""Skrypty modeli TLA+ skilli i atrapa wyjścia TLC do testów ``tools/lib/model_tlc.py``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

__all__ = ["skrypt_modelu", "wyjscie_tlc"]


def skrypt_modelu(path: Path) -> ModuleType:
    """Skrypt modelu skilla wczytany z pliku (skrypty skilli nie są pakietem); jego ``MODEL`` to ``model_tlc.Model``."""

    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wyjscie_tlc(naruszenie: str | None, *stany: tuple[str, dict[str, str]]) -> str:
    """Wyjście TLC z kontrprzykładem: ``naruszenie`` to niezmiennik, a ``None`` właściwość czasowa; każdy stan to akcja,
    która do niego prowadzi (pierwszy to stan początkowy), i wartości zmiennych (wartość z ``\\n`` stoi na kilku liniach).
    Akcja ``Stuttering`` albo ``Back to state N`` kończy przebieg bez końca."""

    lines = ["Error: Temporal properties were violated." if naruszenie is None else f"Error: Invariant {naruszenie} is violated."]
    for number, (action, variables) in enumerate(stany, start=1):
        if action == "Stuttering":
            lines.append(f"State {number}: Stuttering")
            continue
        if action.startswith("Back to state"):
            lines.append(f"{action}: <Koniec line 9, col 5 to line 9, col 20 of module M>")
            continue
        where = "<Initial predicate>" if number == 1 else f"<{action} line 10, col 5 to line 12, col 30 of module M>"
        lines.append(f"State {number}: {where}")
        lines += [f"/\\ {name} = {value}" for name, value in variables.items()]
    return "\n".join(lines) + "\n"
