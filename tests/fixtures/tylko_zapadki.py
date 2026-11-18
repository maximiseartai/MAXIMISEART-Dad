"""Wtyczka pytest dowodu pustego drzewa zapadek (``tests/test_struktura_testow.py``): zostawia z kolekcji tylko zapadki,
czyli testy, które biorą bazę zmiany z fixture ``baza_zmiany`` (wprost albo przez inną fixture, jak liczy pytest), bez
testów o nazwach z ``BEZ`` (po przecinku). Pozostałe testy pliku zapadek biegną na własnych repozytoriach w ``tmp_path``,
więc baza ich wyniku nie zmienia."""

from __future__ import annotations

import os

import pytest

FIXTURE = "baza_zmiany"
BEZ = "MAXIMISEART_ZAPADKI_BEZ"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    skipped = set(filter(None, os.environ.get(BEZ, "").split(",")))
    kept = [item for item in items if FIXTURE in getattr(item, "fixturenames", ()) and getattr(item, "originalname", item.name) not in skipped]
    dropped = [item for item in items if item not in kept]
    if dropped:
        config.hook.pytest_deselected(items=dropped)
    items[:] = kept
