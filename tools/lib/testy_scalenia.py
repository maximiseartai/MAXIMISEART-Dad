"""Test scalenia łapie PR, który z bieżącą bazą daje czerwony ``main``, choć sam był zielony, bo baza od merge-base PR
zmieniła coś, czego PR używa. Gdy baza od merge-base się nie zmieniła, nie liczy niczego. Inaczej bierze pliki testów
dotknięte i zmianą PR, i zmianą bazy od merge-base, w odległości najwyżej ``MERGE_TEST_DISTANCE`` od każdej z nich
w grafie ``tools/lib/wplyw_zmiany.py`` liczonym na scalonym drzewie: plik testów zmieniony albo zależny wprost od pliku
zmienionego po obu stronach. Gdy takich plików nie ma, nic nie biegnie (liczenie trwało ~1,5 s na merge'ach z 6.11.2026).
Gdy są, biegną pytestem w kopii scalonego drzewa, z jego ``tests/conftest.py``, więc test z kwarantanny
(``tests/fixtures/kwarantanna.py``) nie czerwieni wyniku, jak w CI. Gdy któryś test pada, te same pliki testów biegną
jeszcze raz na drzewie samej bazy, bo czerwony ``main`` nie blokuje merge'ów (ADR 0020): odmowa z nazwami testów
zachodzi tylko wtedy, gdy któryś test pada na scaleniu, a na samej bazie nie (albo nie ma go na bazie). Gdy każdy
padnięty test pada też na samej bazie, PR przechodzi, a linia ``SCAL OK`` wymienia te testy (``na samym main … pada
już: …``). Ten drugi bieg kosztuje tylko po porażce. Pytest, który pada bez nazwy testu, to odmowa z przyczyną ze stderr.
Test scalenia nie biegnie, a linia ``SCAL OK`` mówi dlaczego (``test scalenia pominięty: …``), gdy któraś strona
zmienia plik reguły wyboru testów (``Context.TESTS``: ``conftest.py`` każdego testu, konfiguracja), bo taki plik dotyczy
każdego testu, gdy suma czasów CI tych plików (tor ``czasy_ci.TOR_LOKALNY``, plik bez pomiaru waży medianę) przekracza
``MERGE_TEST_BUDGET_S`` albo gdy czasów CI nie ma. Na merge'ach z 6.11.2026 limit przepuścił pliki do 20 s w CI
(4–8 s na Macu agenta), a zatrzymał pliki od 437 s w CI (93 s na Macu i więcej). Test, który trwa dłużej niż
``MERGE_TEST_TIMEOUT_S``, to odmowa, bo nie dał wyniku.
"""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import czasy_ci
import github
import potomne
from repo import ROOT
import repo
from wplyw_zmiany import Context, Repository, run_all
import wyniki_testow

# Plik testów w tej odległości od zmiany PR i od zmiany bazy (0 to plik zmieniony, 1 zależny wprost).
MERGE_TEST_DISTANCE = 1
# Suma czasów CI plików testu scalenia; Mac agenta liczy je ~5 razy szybciej (6.11.2026: 507 s w CI, 94 s na Macu).
MERGE_TEST_BUDGET_S = 180.0
MERGE_TEST_TIMEOUT_S = 300


class Refused(Exception):
    """Odmowa merge'a z przyczyną z testu scalenia."""


def merge_test(copy: Path, where: str, base: str, head: str) -> str:
    """Dopisek linii ``SCAL OK`` o teście scalenia w ``copy`` ze scalonym drzewem ``base`` i ``head``; pusty, gdy test
    nie był potrzebny. Rzuca ``Refused``, gdy test pada na scaleniu, a na samej bazie nie, albo nie daje wyniku w
    limicie czasu."""

    limit = github.LIMIT_S
    fork = repo.merge_base(ROOT, base, head, timeout=limit)
    base_changed = repo.changed(ROOT, fork, base, timeout=limit)
    if not base_changed:
        return ""
    pull_changed = repo.changed(ROOT, fork, head, timeout=limit)
    if full := run_all(pull_changed | base_changed, Context.TESTS):
        return f" | test scalenia pominięty: zmiana {', '.join(full)} dotyczy każdego testu"
    repository = Repository.scan(copy)
    pull_impact, base_impact = repository.impact(pull_changed), repository.impact(base_changed)
    tests = sorted(
        test
        for test in set(pull_impact.tests) & set(base_impact.tests)
        if max(pull_impact.distances[test], base_impact.distances[test]) <= MERGE_TEST_DISTANCE
    )
    if not tests:
        return ""
    names = ", ".join(tests)
    costs, why = czasy_ci.lokalne(ROOT)
    if why is not None:
        return f" | test scalenia pominięty: brak czasów CI ({why}), plików testów: {len(tests)}"
    cost = sum(costs.s(test) for test in tests)
    if cost > MERGE_TEST_BUDGET_S:
        return f" | test scalenia pominięty: ~{cost:.0f} s w CI ponad limit {MERGE_TEST_BUDGET_S:.0f} s, plików testów: {len(tests)}"
    print(f"== test scalenia z {where} (~{cost:.0f} s w CI): {names}", flush=True)
    started = time.monotonic()
    failed = failed_tests(copy, tests, f"test scalenia z {where}")
    if not failed:
        return f" | test scalenia: {names} przechodzą ({time.monotonic() - started:.0f} s)"
    # Czerwony ``main`` nie blokuje merge'ów (ADR 0020): porażka, która jest już na samej bazie, nie jest winą PR.
    repo.run_git(copy, "read-tree", "-u", "--reset", base).check_returncode()
    on_base = [test for test in tests if (copy / test).is_file() and any(name.partition("::")[0] == test for name in failed)]
    print(f"== te same pliki na samym {where}: {', '.join(on_base) or 'brak'}", flush=True)
    failed_on_base = failed_tests(copy, on_base, f"test scalenia na samym {where}") if on_base else []
    pull_failed = [name for name in failed if name not in failed_on_base]
    already = [name for name in failed if name in failed_on_base]
    if pull_failed:
        also = f" (na samym {where} pada też: {', '.join(already)})" if already else ""
        raise Refused(f"test scalenia z {where} pada: {', '.join(pull_failed)}{also}")
    return f" | test scalenia: {names} bez porażek przez PR, a na samym {where} pada już: {', '.join(already)} ({time.monotonic() - started:.0f} s)"


def failed_tests(copy: Path, tests: Sequence[str], what: str) -> list[str]:
    """Testy z ``tests``, które padły pytestem w ``copy``, po kolei z junit: id testu, a błąd kolekcji plikiem. Rzuca
    ``Refused``, gdy pytest nie daje wyniku w limicie czasu albo pada, nie nazywając testu (wtedy z przyczyną ze stderr,
    np. nieznana opcja)."""

    workers = os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS", str(czasy_ci.WORKERY_LOKALNE))
    with tempfile.TemporaryDirectory() as folder:
        junit = Path(folder, "junit.xml")
        try:
            done = potomne.run(
                [sys.executable, "-m", "pytest", "-q", "-rfE", "-n", "auto", *wyniki_testow.zapis(junit), *tests],
                cwd=copy,
                env={**os.environ, "PYTEST_XDIST_AUTO_NUM_WORKERS": workers},
                timeout=MERGE_TEST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            raise Refused(f"{what} bez wyniku po {MERGE_TEST_TIMEOUT_S} s: {', '.join(tests)}") from None
        if not done.returncode:
            return []
        print(done.stdout.rstrip(), done.stderr.rstrip(), sep="\n", flush=True)
        try:
            results = wyniki_testow.testy(junit)
        except (OSError, ValueError):
            results = []
    if failed := list(dict.fromkeys(name for test in results if test.wynik == "padł" and (name := test.id or test.plik))):
        return failed
    lines = (done.stderr.strip() or done.stdout.strip()).splitlines()
    reason = next((line.strip() for line in reversed(lines) if "error" in line.lower()), lines[-1].strip() if lines else "bez wyjścia")
    raise Refused(f"{what} pada: pytest kod {done.returncode}: {reason}")

