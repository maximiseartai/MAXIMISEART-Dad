"""Wtyczka pytest dowodu strażnika (``straznik``, ADR 0042): dopisuje do pliku ``RESULTS`` obok swojej kopii linię
JSON o każdym teście, który padł w fazie wywołania, z tym, czy padł z braku nazwy.

Brak nazwy to ``ImportError`` (także ``ModuleNotFoundError``), ``NameError`` i ``AttributeError`` modułu: test pada
tak na drzewie FAIL, gdy woła nazwę dodaną po FAIL (moduł nowego właściciela, funkcję), a nie na błędzie z ``Gdzie``.
Wtyczka czyta sam wyjątek, a nie tekst raportu, więc format wyjścia z konfiguracji PR go nie zmienia. Dowód ładuje ją
z kopii tego pliku w osobnym katalogu (``-p``), żeby kod PR nie widział reszty ``tools/lib`` bazy. Hak
``pytest_exception_interact`` pytest woła przy każdym padnięciu testu (nie przy pominięciu ani ``xfail``), więc moduł
nie importuje pytest i ``straznik`` może go importować w jobie statusu, który pytest nie ma.
"""

from __future__ import annotations

import json
from pathlib import Path
import types
from typing import Protocol

RESULTS = "wyniki.jsonl"  # plik wyników w katalogu kopii wtyczki


class _Excinfo(Protocol):
    @property
    def value(self) -> BaseException: ...

    @property
    def typename(self) -> str: ...


class _Call(Protocol):
    @property
    def excinfo(self) -> _Excinfo | None: ...


class _Node(Protocol):
    @property
    def nodeid(self) -> str: ...


class _Report(Protocol):
    @property
    def when(self) -> str: ...


def missing_name(error: BaseException) -> bool:
    """Czy wyjątek mówi o nazwie, której drzewo nie ma, a nie o zachowaniu kodu."""

    return isinstance(error, (ImportError, NameError)) or (isinstance(error, AttributeError) and isinstance(getattr(error, "obj", None), types.ModuleType))


def pytest_exception_interact(node: _Node, call: _Call, report: _Report) -> None:
    if report.when == "call" and call.excinfo is not None:
        with Path(__file__).with_name(RESULTS).open("a", encoding="utf-8") as results:
            results.write(json.dumps({"wezel": node.nodeid, "wyjatek": call.excinfo.typename, "brak_nazwy": missing_name(call.excinfo.value)}) + "\n")
