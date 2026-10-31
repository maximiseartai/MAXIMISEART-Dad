"""Strażnik pytest: kod eksploratora przeplotów skilla (``.agents/skills/*/scripts/explore_*.py``) nie wykonuje się w
procesie pytest.

Eksplorator przy defekcie porzuca wątek modelu, który trzyma prawdziwą blokadę do końca procesu, więc w procesie pytest
wiesza cały worker xdist (#651, #660). Test uruchamia go w osobnym procesie z limitem, jak
``tests/test_jedno_uruchomienie_naraz.py``; wyjątki są w ``IN_PROCESS_EXPLORERS`` z powodem.

``tests/conftest.py`` wczytuje ten moduł jako plugin, w procesie pytest i w każdym workerze xdist, a moduł przy
wczytaniu dodaje hook audytu (``sys.addaudithook``). Hook dostaje zdarzenie ``exec`` każdego wykonania kodu modułu:
``import``, ``importlib``, ``runpy``, ``exec_module``, ``exec(compile(...))``, niezależnie od tego, czy wczytuje test,
fixtura, ``conftest.py`` czy pomocnik z ``tests/fixtures``, i czy wywołuje go wprost, w wątku, przez ``submit``,
``partial``, alias albo ``map``. Na kodzie z pliku eksploratora hook rzuca ``EksploratorWProcesie`` przed jego
pierwszą linią, więc eksplorator nie zaczyna biec, a krok testu (przygotowanie, test, sprzątanie), w którym to się
stało, pada z tym komunikatem, także gdy wywołujący złapał wyjątek albo wątek go połknął. Wczytanie przy zbieraniu
(import na górze modułu testu albo ``conftest.py``) wywraca zbieranie tym samym wyjątkiem, chyba że kod go złapie;
eksplorator i wtedy nie biegnie. Moduł, który pomocnik zostawił w ``sys.modules`` po zatrzymanym wczytaniu, kolejny
import oddaje pusty, bez wykonania kodu.

Strażnik nie widzi testu, który nie biegnie (pominięty albo odznaczony), kodu eksploratora z pliku spoza
``.agents/skills/*/scripts/`` (kopia w innym katalogu albo pod inną nazwą), skompilowanego pod inną nazwą pliku albo
wywołanego bez ``exec`` (obiekt kodu jako funkcja), ani kodu, który wykonał się przed tym pluginem (ciało
``tests/conftest.py``), ani nie sprawdza limitu czasu osobnego procesu. Proces potomny z ``fork`` dziedziczy hook, a nowy
interpreter (``subprocess``) go nie ma.
Hooka audytu nie da się zdjąć, więc dodaje go tylko pytest, nigdy kod produktu.
"""

from __future__ import annotations

from collections.abc import Generator
import os
from pathlib import Path
import sys
from types import CodeType
from typing import cast

import pytest

EXPLORERS = ".agents/skills/*/scripts/explore_*.py"
IN_PROCESS_EXPLORERS = {
    "explore_publication": (
        "prowadzi greenlety na wątku testu: nie ma wątku sprawdzenia, który mógłby porzucić z prawdziwą blokadą, "
        "a limit pytest przerywa go jak każdy wiszący test (werdykt #660 r3, punkt 4)"
    ),
}
# Pliki eksploratorów, których kod hook zatrzymał, w kolejności; krok testu zgłasza te, które doszły w jego czasie.
_stopped: list[str] = []


class EksploratorWProcesie(Exception):
    """Kod eksploratora przeplotów miał się wykonać w procesie pytest."""


def _message(paths: list[str]) -> str:
    return (
        f"Kod eksploratora przeplotów miał się wykonać w procesie pytest: {', '.join(dict.fromkeys(paths))}. "
        "Wątek modelu porzucony przez eksplorator trzyma prawdziwą blokadę do końca procesu i wiesza worker (#651). "
        "Uruchom eksplorator w osobnym procesie z limitem, np. subprocess.run([sys.executable, str(EXPLORER), ...], "
        "timeout=..., check=False), jak tests/test_jedno_uruchomienie_naraz.py, albo dopisz go do IN_PROCESS_EXPLORERS "
        "w tests/fixtures/eksplorator_w_procesie.py z powodem, dla którego nie porzuca wątku z blokadą."
    )


def _audit(event: str, args: tuple[object, ...]) -> None:
    if event != "exec":
        return
    path = Path(os.path.abspath(cast(CodeType, args[0]).co_filename))
    if path.match(EXPLORERS) and path.stem not in IN_PROCESS_EXPLORERS:
        _stopped.append(str(path))
        raise EksploratorWProcesie(_message([str(path)]))


sys.addaudithook(_audit)


def _step() -> Generator[None, object, object]:
    before = len(_stopped)
    try:
        return (yield)
    finally:
        if len(_stopped) > before:
            raise EksploratorWProcesie(_message(_stopped[before:]))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item: pytest.Item) -> Generator[None, object, object]:
    return (yield from _step())


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    return (yield from _step())


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item) -> Generator[None, object, object]:
    return (yield from _step())
