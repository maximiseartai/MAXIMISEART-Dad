"""Ciężkie narzędzie repo nigdy nie biegnie na Macu Maksa (decyzja Maksa z 20.11.2026 w #2272): na Macu przenosi się
przy starcie na box boat (skill ``boat``), a gdy box nie wstanie, kończy się kodem ``NIE_WSTAL`` z powodem, bez powrotu
na Maca.

Mac to proces z ``boatbox`` w ``PATH`` (CI, box boat i komputer taty go nie mają) bez ``BOX``, które ``boatbox`` ustawia
w każdym poleceniu na boxie. Ciężkie wejścia (``szybko.py``, ``mutacje.py``, ``mutacje_zmiany.py``,
``benchmark_przebiegu.py``, ``ci_lokalnie.py`` z zadaniem ``pytest`` albo ``mutations`` oraz pytest z więcej niż jednym
workerem xdist, przez ``przenies_pytest`` w ``tests/conftest.py``) wołają ``przenies`` zaraz po odczycie argumentów. Na
Macu ``przenies`` robi ``os.execvp`` na ``boatbox run`` z tym samym poleceniem w tym samym katalogu, więc wołający dalej
czeka na ten sam proces i dostaje jego wyjście i kod wyjścia. Test scalenia ``tools/scal_pr.py``, którego narzędzie
zostaje na Macu (merge, blokada merge'a), puszcza swój pytest na box przez ``uruchom`` i zabiera z boxa jego junit.

Wyjątki są tylko jawne: ``TUTAJ``, które ustawia wyłącznie ``boatbox run --here`` (Excel, Centrum z prawdziwymi plikami
taty, testy tylko na macOS), i sesja pytest (``SESJA``, które ``przenies_pytest`` wpisuje do ``os.environ`` sesji, która
zostaje tam, gdzie jest), bo narzędzie uruchomione przez test jest częścią testu. Pytest bez workerów albo z jednym
zostaje na Macu, bo jest lekki. Decyzja czyta tylko środowisko, ``PATH`` i liczbę workerów pytest, a nie tekst polecenia.

Na boxie polecenie biegnie z ``PYTEST_XDIST_AUTO_NUM_WORKERS`` równym liczbie rdzeni boxa, a inne zmienne środowiska
Maca tam nie trafiają. Plik ``--plik`` mutacji jedzie w poleceniu, bo box widzi tylko pliki worktree, które widzi git.
Ścieżki bezwzględne pod korzeniem repo stają się względne; ścieżka po ``=`` w opcji i ścieżka spoza repo zostają, jak są.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from typing import Any, NoReturn, Protocol

BOX = "BOATBOX_BOX"
TUTAJ = "BOATBOX_HERE"
SESJA = "MAXIMISEART_SESJA_PYTEST"
NIE_WSTAL = 75
"""Kod ``boatbox``, gdy box nie wstał, a polecenie nie ruszyło (EX_TEMPFAIL, jak ``box_boat.KOD_WYJSCIA``: powtórz)."""
START_S = 300
"""Tyle ``uruchom`` daje boxowi na start, załadowanie dysku i sync ponad limit samego polecenia."""
ROOT = Path(__file__).resolve().parents[2]
NIESIONE = "$HOME/.boatbox-niesione"
"""Katalog na boxie, do którego ``polecenie`` zapisuje plik niesiony w poleceniu."""


class Konfiguracja(Protocol):
    """Ta część ``pytest.Config``, której potrzebuje ``przenies_pytest``: moduł importują skrypty workflow na systemowym
    ``python3`` bez pytest."""

    def getoption(self, name: str, default: Any = ...) -> Any: ...


def przeniesc() -> bool:
    """Czy ciężkie wejście przenosi się na box: Mac (``boatbox`` w ``PATH``, nie Windows), nie box (``BOX``), bez
    jawnego wyjątku ``TUTAJ`` i poza sesją pytest (``SESJA``)."""

    if sys.platform == "win32" or any(os.environ.get(name) for name in (BOX, TUTAJ, SESJA)):
        return False
    return shutil.which("boatbox") is not None


def polecenie(words: Sequence[str], cwd: Path, *, root: Path = ROOT, carried: tuple[Path, bytes] | None = None) -> str:
    """Polecenie powłoki dla ``boatbox run`` z ``words`` (jak ``sys.orig_argv``): interpreter to ``.venv/bin/python``
    repo, ścieżki bezwzględne pod ``root`` są względne do ``cwd``, a ``cd`` wchodzi do ``cwd`` względem korzenia, gdy
    ``cwd`` leży pod nim. ``carried`` (plik i jego treść) zapisuje plik na boxie i stawia jego ścieżkę za każde słowo,
    które go nazywa, także po ``=`` w opcji."""

    here = cwd if cwd.is_relative_to(root) else root
    steps = ['export PYTEST_XDIST_AUTO_NUM_WORKERS="$(nproc)"']
    if here != root:
        steps.append(f"cd {shlex.quote(os.path.relpath(here, root))}")
    words = [os.path.relpath(root / ".venv" / "bin" / "python", here), *words[1:]]
    parts = [shlex.quote(words[0])]
    for word in words[1:]:
        option, equals, value = word.partition("=")
        named = [given for given in (word, value if equals else "") if given and carried is not None and (cwd / given).resolve() == carried[0]]
        if carried is not None and named:
            name = re.sub(r"[^A-Za-z0-9._-]", "_", carried[0].name)
            steps.append(f'mkdir -p "{NIESIONE}" && printf %s {base64.b64encode(carried[1]).decode()} | base64 -d > "{NIESIONE}/{name}"')
            parts.append(f'{shlex.quote(option + "=") if named[0] == value else ""}"{NIESIONE}/{name}"')
        elif os.path.isabs(word) and Path(word).is_relative_to(root):
            parts.append(shlex.quote(os.path.relpath(word, here)))
        else:
            parts.append(shlex.quote(word))
    return " && ".join([*steps, " ".join(parts)])


def _exec(command: str) -> NoReturn:
    print(f"NA BOXIE | ciężkie narzędzie repo nie biegnie na Macu: boatbox run {shlex.join(sys.orig_argv)}", file=sys.stderr, flush=True)
    sys.stdout.flush()
    if not Path.cwd().is_relative_to(ROOT):
        os.chdir(ROOT)
    os.execvp("boatbox", ["boatbox", "run", command])


def przenies(plik: str | os.PathLike[str] | None = None) -> None:
    """Na Macu (``przeniesc``) zastępuje proces przez ``boatbox run`` z tym samym poleceniem; ``plik`` (wartość
    ``--plik``, tak jak w argumentach) jedzie w poleceniu, gdy istnieje. Inaczej wraca od razu."""

    if not przeniesc():
        return
    carried = (Path(plik).resolve(), Path(plik).read_bytes()) if plik is not None and Path(plik).is_file() else None
    _exec(polecenie(sys.orig_argv, Path.cwd(), carried=carried))


def przenies_pytest(config: Konfiguracja) -> None:
    """``przenies`` dla sesji pytest z ``pytest_configure`` kontrolera: przenosi tylko sesję z więcej niż jednym workerem
    xdist (pytest-xdist liczy już ``-n auto`` w ``pytest_cmdline_main``, a przechwytywanie wyjścia pytest jest wtedy
    zawieszone, więc wyjście ``boatbox`` idzie do wołającego). Sesja, która zostaje, wpisuje ``SESJA`` dla procesów
    swoich testów."""

    workers = config.getoption("numprocesses", default=None)
    if isinstance(workers, int) and workers > 1 and przeniesc():
        _exec(polecenie(sys.orig_argv, Path.cwd()))
    os.environ[SESJA] = "1"


def uruchom(words: Sequence[str], cwd: Path, *, timeout: float, result: str, into: Path) -> subprocess.CompletedProcess[str]:
    """``words`` na boxie worktree ``cwd`` (``boatbox run`` z limitem ``timeout`` ponad ``START_S``), potem plik
    ``result`` (względny do ``cwd``) z boxa do katalogu ``into``, a na końcu usunięcie boxa, bo ``cwd`` to kopia, która
    znika po biegu. Kod ``NIE_WSTAL`` mówi, że box nie wstał, a polecenie nie ruszyło."""

    import potomne

    try:
        done = potomne.run(["boatbox", "run", polecenie(words, cwd, root=cwd)], cwd=cwd, timeout=timeout + START_S)
        if done.returncode != NIE_WSTAL:
            potomne.run(["boatbox", "get", result, str(into)], cwd=cwd, timeout=START_S)
        return done
    finally:
        try:
            potomne.run(["boatbox", "rm"], cwd=cwd, timeout=START_S)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"NA BOXIE | box kopii {cwd.name} zostaje do końca swojego czasu życia: {error}", file=sys.stderr, flush=True)
