"""Plugin pytest: zadanie CI bierze ze swojego udziału dużego pliku testów tylko jego testy, bez listy id.

    python -m pytest -n auto -p tools.lib.pytest_czesc --czesci czesci.json tests/test_a.py tests/test_b.py

``czesci.json`` to ``{"tests/test_a.py": {"n": 3, "udzialy": [1, 3]}}``: testy pliku posortowane po id idą po
kolei do udziałów 1, 2, 3, 1, 2, …, a zostają te z udziałów 1 i 3. Plik bez wpisu zostaje cały. Zbiór id pliku nie
zależy od innych plików zadania, od kolejności, w jakiej ustawiły testy wcześniejsze hooki, ani od ``PYTHONHASHSEED``,
więc udziały 1..n dzielą plik bez luk i bez powtórzeń w każdym procesie toru, także z testami, których plan nie znał,
a plik z co najmniej n testami ma test w każdym udziale. Lista id w linii poleceń nie wchodzi w grę: 3620 id jednego
pliku przekracza 32 767 znaków linii Windows. Pod xdist każdy worker odznacza to samo, więc kontroler widzi zgodne
kolekcje.
"""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--czesci", type=Path, help="JSON: plik testów -> n i udziały 1..n, które biegną w tym zadaniu.")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    sciezka: Path | None = config.getoption("--czesci")
    if sciezka is None:
        return
    czesci = json.loads(sciezka.read_text(encoding="utf-8"))
    pliki: dict[str, list[str]] = defaultdict(list)
    for item in items:
        pliki[item.nodeid.split("::")[0]].append(item.nodeid)
    # Po kolei, nie crc32 id modulo n: udział bez testów nie zgłasza wyniku i czerwieni Required, a crc32 modulo 3 nie
    # dał żadnego z 7 testów test_kopia_wzorca.py udziałowi 1 (run 40910405317). Po id, nie w kolejności items: hak
    # testów dlugi z tests/conftest.py biegnie przed tym i ustawia je zależnie od wszystkich plików zadania.
    udzial = {nodeid: numer % czesci[plik]["n"] + 1 for plik, nodeids in pliki.items() if plik in czesci for numer, nodeid in enumerate(sorted(nodeids))}
    zostaja: list[pytest.Item] = []
    odznaczone: list[pytest.Item] = []
    for item in items:
        czesc = czesci.get(item.nodeid.split("::")[0])
        (zostaja if czesc is None or udzial[item.nodeid] in czesc["udzialy"] else odznaczone).append(item)
    config.hook.pytest_deselected(items=odznaczone)
    items[:] = zostaja
