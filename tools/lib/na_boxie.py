"""Ciężkie narzędzie repo nigdy nie biegnie na Macu Maksa (decyzja Maksa z 20.11.2026 w #2272): uruchomione na Macu
w ogóle nie rusza, tylko kończy się kodem ``ODMOWA`` i jedną linią z gotowym poleceniem ``boatbox`` (skill ``boat``).

Mac to proces z ``boatbox`` w ``PATH`` (CI, box boat i komputer taty go nie mają) bez ``BOX``, które ``boatbox`` ustawia
w każdym poleceniu na boxie, i bez ``TUTAJ``, które ustawia wyłącznie ``boatbox run --here`` (Excel, Centrum
z prawdziwymi plikami taty, testy tylko na macOS). Ciężkie wejścia (``szybko.py``, ``mutacje.py``, ``mutacje_zmiany.py``,
``benchmark_przebiegu.py`` poza ``comment`` i ``guard``, ``ci_lokalnie.py`` z zadaniem ``pytest`` albo ``mutations``,
``na_scalonych_pr.py`` z poleceniem oraz pytest z więcej niż jednym workerem xdist, przez ``odmowa_pytest``
w ``tests/conftest.py``) wołają ``odmowa`` po odczycie argumentów i własnych szybkich odmowach. Odmowa nie czyta
argumentów i niczego nie przenosi: agent sam uruchamia podane polecenie na boxie, a wejście, którego box nie ma, daje
tam jawny błąd, jak przy każdym ``boatbox run``.

Odmawia tylko proces, którego nie uruchomiło inne narzędzie repo (``potomne.POTOMEK_NARZEDZIA``): narzędzie uruchomione
przez test w sesji pytest albo przez inne narzędzie jest częścią pracy wołającego i biegnie tam, gdzie on. Pytest bez
workerów albo z jednym zostaje na Macu, bo jest lekki. Test scalenia ``tools/scal_pr.py``, którego narzędzie zostaje na
Macu (merge, blokada merge'a), puszcza swój pytest na box jawnie przez ``uruchom`` i zabiera z boxa jego junit.
"""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from typing import Any, NoReturn, Protocol

import potomne

BOX = "BOATBOX_BOX"
TUTAJ = "BOATBOX_HERE"
ODMOWA = 78
"""Kod ciężkiego wejścia, które odmówiło na Macu (EX_CONFIG z sysexits.h: złe miejsce uruchomienia), inny niż kody
pytest (0–5) i niż ``NIE_WSTAL``, więc wołający nie bierze go za wynik testu ani za box, który nie wstał."""
NIE_WSTAL = 75
"""Kod ``boatbox``, gdy box nie wstał, a polecenie nie ruszyło (EX_TEMPFAIL, jak ``box_boat.KOD_WYJSCIA``: powtórz)."""
START_S = 300
"""Tyle ``uruchom`` daje boxowi na start, załadowanie dysku i sync ponad limit samego polecenia."""
ROOT = Path(__file__).resolve().parents[2]
WORKERY_BOXA = 'export PYTEST_XDIST_AUTO_NUM_WORKERS="$(nproc)"'
"""Pierwszy krok polecenia ``uruchom``: workery xdist z liczby rdzeni boxa, bo ``czasy_ci.WORKERY_LOKALNE`` liczy Maca."""


class Konfiguracja(Protocol):
    """Ta część ``pytest.Config``, której potrzebuje ``odmowa_pytest``: moduł importują skrypty workflow na systemowym
    ``python3`` bez pytest."""

    def getoption(self, name: str, default: Any = ...) -> Any: ...


def na_macu() -> bool:
    """Czy ciężkie wejście jest na Macu: ``boatbox`` w ``PATH`` (nie Windows), nie na boxie (``BOX``), bez jawnego
    wyjątku ``TUTAJ`` i w procesie, którego nie uruchomiło inne narzędzie repo."""

    if sys.platform == "win32" or potomne.POTOMEK_NARZEDZIA or any(os.environ.get(name) for name in (BOX, TUTAJ)):
        return False
    return shutil.which("boatbox") is not None


def polecenie(words: Sequence[str], cwd: Path, *, root: Path = ROOT) -> str:
    """To samo polecenie do uruchomienia w katalogu repo na boxie: interpreter to ``.venv/bin/python`` repo, a ``cd``
    wchodzi do ``cwd``, gdy leży pod ``root``; reszta słów zostaje, jak jest."""

    here = cwd if cwd.is_relative_to(root) else root
    command = shlex.join([os.path.relpath(root / ".venv" / "bin" / "python", here), *words[1:]])
    return f"cd {shlex.quote(os.path.relpath(here, root))} && {command}" if here != root else command


def _odmowa(extra: str = "") -> NoReturn:
    """Linia odmowy i kod ``ODMOWA`` przez ``os._exit``: w ``pytest_configure`` ``SystemExit`` byłby wewnętrznym błędem
    pytest, a narzędzie jeszcze niczego nie uruchomiło."""

    command = shlex.quote(polecenie(sys.orig_argv, Path.cwd()))
    print(f"CIĘŻKIE NA MACU ODMOWA | uruchom: boatbox run {command}{extra}", file=sys.stderr, flush=True)
    sys.stdout.flush()
    os._exit(ODMOWA)


def odmowa() -> None:
    """Na Macu (``na_macu``) kończy ciężkie wejście odmową z gotowym poleceniem ``boatbox run``; inaczej wraca od razu."""

    if na_macu():
        _odmowa()


def odmowa_pytest(config: Konfiguracja) -> None:
    """``odmowa`` dla sesji pytest z ``pytest_configure`` kontrolera, tylko z więcej niż jednym workerem xdist
    (pytest-xdist liczy już ``-n auto`` w ``pytest_cmdline_main``); pełny pytest agent puszcza w tle przez ``boatbox job``."""

    workers = config.getoption("numprocesses", default=None)
    if isinstance(workers, int) and workers > 1 and na_macu():
        command = shlex.quote(polecenie(sys.orig_argv, Path.cwd()))
        _odmowa(f" (pełny pytest w tle: boatbox job pytest {command}, potem boatbox wait pytest)")


def uruchom(words: Sequence[str], cwd: Path, *, timeout: float, result: str, into: Path) -> subprocess.CompletedProcess[str]:
    """``words`` na boxie worktree ``cwd`` (``boatbox run`` z limitem ``timeout`` ponad ``START_S``), potem plik
    ``result`` (względny do ``cwd``) z boxa do katalogu ``into``, a na końcu usunięcie boxa, bo ``cwd`` to kopia, która
    znika po biegu. Kod ``NIE_WSTAL`` mówi, że box nie wstał, a polecenie nie ruszyło."""

    try:
        command = f"{WORKERY_BOXA} && {polecenie(words, cwd, root=cwd)}"
        done = potomne.run(["boatbox", "run", command], cwd=cwd, timeout=timeout + START_S)
        if done.returncode != NIE_WSTAL:
            potomne.run(["boatbox", "get", result, str(into)], cwd=cwd, timeout=START_S)
        return done
    finally:
        try:
            potomne.run(["boatbox", "rm"], cwd=cwd, timeout=START_S)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"NA BOXIE | box kopii {cwd.name} zostaje do końca swojego czasu życia: {error}", file=sys.stderr, flush=True)
