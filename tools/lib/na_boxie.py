"""Ciężkie narzędzie repo nigdy nie biegnie na Macu Maksa (decyzja Maksa z 20.11.2026 w #2272): na Macu przenosi się
przy starcie na box boat (skill ``boat``), a gdy box nie wstanie, kończy się kodem ``NIE_WSTAL`` z powodem, bez powrotu
na Maca.

Mac to proces z ``boatbox`` w ``PATH`` (CI, box boat i komputer taty go nie mają) bez ``BOX``, które ``boatbox`` ustawia
w każdym poleceniu na boxie. Ciężkie wejścia (``szybko.py``, ``mutacje.py``, ``mutacje_zmiany.py``,
``benchmark_przebiegu.py`` poza ``comment`` i ``guard``, ``ci_lokalnie.py`` z zadaniem ``pytest`` albo ``mutations``,
``na_scalonych_pr.py`` z poleceniem oraz pytest z więcej niż jednym workerem xdist, przez ``przenies_pytest``
w ``tests/conftest.py``) wołają ``przenies`` po odczycie argumentów i własnych szybkich odmowach. Na
Macu ``przenies`` robi ``os.execvp`` na ``boatbox run`` z tym samym poleceniem w tym samym katalogu, więc wołający dalej
czeka na ten sam proces i dostaje jego wyjście i kod wyjścia. Test scalenia ``tools/scal_pr.py``, którego narzędzie
zostaje na Macu (merge, blokada merge'a), puszcza swój pytest na box przez ``uruchom`` i zabiera z boxa jego junit.

Przenosi się tylko proces, którego nie uruchomiło inne narzędzie repo (``potomne.POTOMEK_NARZEDZIA``): przeniesienie
gubi środowisko, kopię commitu i pliki wołającego, więc potomek narzędzia repo, także narzędzie uruchomione przez test
w sesji pytest, zostaje przy wołającym. Wołający, który sam robi ciężką pracę, przechodzi na box w całości
(``na_scalonych_pr.py`` z poleceniem) albo puszcza ją jawnie przez ``uruchom`` (test scalenia). Jedyny inny wyjątek to
``TUTAJ``, które ustawia wyłącznie ``boatbox run --here`` (Excel, Centrum z prawdziwymi plikami taty, testy tylko na
macOS). Pytest bez workerów albo z jednym zostaje na Macu, bo jest lekki. Decyzja czyta tylko środowisko, ``PATH``
i liczbę workerów pytest, a nie tekst polecenia.

Box widzi to, co wiezie ``boatbox``: HEAD, każdą gałąź lokalną, ``origin/*`` i tag (więc rewizja z argumentów, np. gałąź
rodzica w ``--baza`` albo krótki SHA z innej gałęzi, rozwiązuje się tam jak tutaj) oraz pliki worktree, które widzi
git. Plik ``--plik`` mutacji jedzie w skrypcie. Każde słowo polecenia ``niewidoczne`` rozwiązuje tak, jak rozwiąże je
box, w katalogu, w którym tam biegnie polecenie, i pyta, czy wskaże to samo co tutaj; gdy nie (ścieżka spoza repo,
także względna, dowiązanie spoza repo, ścieżka, którą git ignoruje, reflog albo upstream ``@{…}`` tego Maca, rewizja
przez ref, którego ``boatbox`` nie wiezie), przeniesienie to odmowa ``ODMOWA`` przed startem boxa z nazwą słowa, a nie
bieg, który pada na boxie, liczy co innego albo zostawia wynik poza repo. Polecenie jedzie na box jako plik skryptu
(``boatbox run --file``), który ``boatbox`` wysyła przez stdin, bo jeden argument polecenia na Linuksie boxa ma
najwyżej 128 KiB, a plan mutacji bywa większy. Skrypt biegnie z ``PYTEST_XDIST_AUTO_NUM_WORKERS`` równym liczbie
rdzeni boxa, a ścieżki pod korzeniem repo stają się względne. Pliki, które narzędzie zapisze w repo na boxie, zostają
tam (``boatbox get``).
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from typing import Any, NoReturn, Protocol

import potomne
import repo

BOX = "BOATBOX_BOX"
TUTAJ = "BOATBOX_HERE"
NIE_WSTAL = 75
"""Kod ``boatbox``, gdy box nie wstał, a polecenie nie ruszyło (EX_TEMPFAIL, jak ``box_boat.KOD_WYJSCIA``: powtórz)."""
ODMOWA = 2
"""Kod przeniesienia, którego box nie wykona, bo nie zobaczy słowa polecenia (``niewidoczne``); box nie startuje."""
NIESIONE_REFY = ("HEAD", "refs/heads/", "refs/remotes/origin/", "refs/tags/")
"""Refy, które ``boatbox`` wiezie na box: rewizja przez inny ref (``refs/stash``, notatki) wskazuje tam co innego."""
START_S = 300
"""Tyle ``uruchom`` daje boxowi na start, załadowanie dysku i sync ponad limit samego polecenia."""
ROOT = Path(__file__).resolve().parents[2]
NIESIONE = "$HOME/.boatbox-niesione"
"""Katalog na boxie, do którego ``skrypt`` zapisuje plik niesiony w skrypcie."""
SKRYPTY = Path(tempfile.gettempdir()) / "na-boxie"
"""Katalog na Macu ze skryptami dla ``boatbox run --file``, nazwanymi skrótem treści."""


class Konfiguracja(Protocol):
    """Ta część ``pytest.Config``, której potrzebuje ``przenies_pytest``: moduł importują skrypty workflow na systemowym
    ``python3`` bez pytest."""

    def getoption(self, name: str, default: Any = ...) -> Any: ...


def przeniesc() -> bool:
    """Czy ciężkie wejście przenosi się na box: Mac (``boatbox`` w ``PATH``, nie Windows), nie box (``BOX``), bez
    jawnego wyjątku ``TUTAJ`` i proces, którego nie uruchomiło inne narzędzie repo."""

    if sys.platform == "win32" or potomne.POTOMEK_NARZEDZIA or any(os.environ.get(name) for name in (BOX, TUTAJ)):
        return False
    return shutil.which("boatbox") is not None


def skrypt(words: Sequence[str], cwd: Path, *, root: Path = ROOT, carried: tuple[Path, bytes] | None = None) -> str:
    """Skrypt powłoki dla ``boatbox run --file`` z ``words`` (jak ``sys.orig_argv``): interpreter to ``.venv/bin/python``
    repo, ścieżki bezwzględne pod ``root`` są względne do ``cwd``, a ``cd`` wchodzi do ``cwd`` względem korzenia, gdy
    ``cwd`` leży pod nim. ``carried`` (plik i jego treść) skrypt zapisuje na boxie z heredoc i stawia jego ścieżkę za
    każde słowo, które go nazywa, także po ``=`` w opcji."""

    here = cwd if cwd.is_relative_to(root) else root
    lines = ["set -e", 'export PYTEST_XDIST_AUTO_NUM_WORKERS="$(nproc)"']
    if here != root:
        lines.append(f"cd {shlex.quote(os.path.relpath(here, root))}")
    words = [os.path.relpath(root / ".venv" / "bin" / "python", here), *words[1:]]
    parts = [shlex.quote(words[0])]
    for word in words[1:]:
        option, equals, value = word.partition("=")
        named = [given for given in (word, value if equals else "") if given and carried is not None and (cwd / given).resolve() == carried[0]]
        if carried is not None and named:
            name = re.sub(r"[^A-Za-z0-9._-]", "_", carried[0].name)
            encoded = textwrap.wrap(base64.b64encode(carried[1]).decode(), 76)
            lines += [f'mkdir -p "{NIESIONE}"', f"base64 -d > \"{NIESIONE}/{name}\" <<'NIESIONE'", *encoded, "NIESIONE"]
            parts.append(f'{shlex.quote(option + "=") if named[0] == value else ""}"{NIESIONE}/{name}"')
        elif os.path.isabs(word) and Path(word).is_relative_to(root):
            parts.append(shlex.quote(os.path.relpath(word, here)))
        else:
            parts.append(shlex.quote(word))
    return "\n".join([*lines, "exec " + " ".join(parts)]) + "\n"


def niewidoczne(words: Sequence[str], cwd: Path, *, root: Path = ROOT, carried: Path | None = None) -> list[str]:
    """Słowa ``words`` (bez interpretera) i wartości po ``=`` w opcji, które box rozwiąże inaczej niż tutaj, każde
    z powodem (``_inaczej``), w katalogu, w którym polecenie biegnie na boxie: ``cwd`` pod ``root``, a inaczej ``root``."""

    here = cwd if cwd.is_relative_to(root) else root
    found = []
    for word in words[1:]:
        _, equals, value = word.partition("=")
        for given in (word, value) if equals else (word,):
            if given and (reason := _inaczej(given, here, root, carried)):
                found.append(f"{given} ({reason})")
    return found


def _inaczej(given: str, here: Path, root: Path, carried: Path | None) -> str | None:
    """Czemu box rozwiąże słowo ``given`` inaczej niż tutaj; ``None``, gdy tak samo. Granica ``.venv`` (box ma własne,
    a jego interpreter to dowiązanie spoza repo) patrzy na ścieżkę przed rozwiązaniem dowiązań."""

    if "@{" in given:
        return "reflog albo upstream tego Maca"
    path = Path(os.path.abspath(here / given))
    if (carried is not None and path.resolve() == carried) or path.is_relative_to(root / ".venv"):
        return None
    if not path.is_relative_to(root):
        return "spoza repo"
    if path.exists() or path.is_symlink():
        if not path.resolve().is_relative_to(root):
            return "dowiązanie spoza repo"
        return "ignorowana przez gita" if repo.succeeds(root, "check-ignore", "-q", str(path)) else None
    if given.startswith("-"):
        return None
    done = repo.run_git(root, "rev-parse", "--verify", "-q", "--symbolic-full-name", "--end-of-options", given)
    ref = done.stdout.strip()
    return f"ref {ref}, którego boatbox nie wiezie" if not done.returncode and ref and not ref.startswith(NIESIONE_REFY) else None


def _odmowa(found: Sequence[str]) -> NoReturn:
    """Odmowa ``niewidoczne`` z kodem ``ODMOWA`` przez ``os._exit``: w ``pytest_configure`` ``SystemExit`` byłby
    wewnętrznym błędem pytest, a przed startem boxa nie ma czego sprzątać."""

    print(
        f"NA BOXIE ODMOWA | box nie zobaczy: {', '.join(found)}; ciężkie narzędzie repo nie biegnie na Macu, więc podaj ścieżkę"
        " w repo, którą widzi git (wynik zabierze boatbox get), albo uruchom całość przez boatbox run z danymi na boxie",
        file=sys.stderr,
        flush=True,
    )
    sys.stdout.flush()
    os._exit(ODMOWA)


def plik_skryptu(text: str) -> Path:
    """Plik ``SKRYPTY`` z treścią ``text``, nazwany jej skrótem: równoległe przeniesienia tego samego polecenia (z dwóch
    worktree) dają ten sam plik, więc proces zapisuje go obok i podmienia atomowo, a ``boatbox`` czyta zawsze pełny."""

    SKRYPTY.mkdir(exist_ok=True)
    path = SKRYPTY / f"{hashlib.sha256(text.encode()).hexdigest()[:16]}.sh"
    written = path.with_name(f"{path.name}.{os.getpid()}")
    written.write_text(text, encoding="utf-8")
    os.replace(written, path)
    return path


def _exec(text: str) -> NoReturn:
    print(f"NA BOXIE | ciężkie narzędzie repo nie biegnie na Macu: boatbox run {shlex.join(sys.orig_argv)}", file=sys.stderr, flush=True)
    sys.stdout.flush()
    script = plik_skryptu(text)
    if not Path.cwd().is_relative_to(ROOT):
        os.chdir(ROOT)
    os.execvp("boatbox", ["boatbox", "run", "--file", str(script)])


def przenies(plik: str | os.PathLike[str] | None = None) -> None:
    """Na Macu (``przeniesc``) zastępuje proces przez ``boatbox run --file`` ze skryptem tego samego polecenia; ``plik``
    (wartość ``--plik``) jedzie w skrypcie, gdy istnieje. Inaczej wraca od razu."""

    if not przeniesc():
        return
    carried = (Path(plik).resolve(), Path(plik).read_bytes()) if plik is not None and Path(plik).is_file() else None
    if found := niewidoczne(sys.orig_argv, Path.cwd(), carried=carried[0] if carried else None):
        _odmowa(found)
    _exec(skrypt(sys.orig_argv, Path.cwd(), carried=carried))


def przenies_pytest(config: Konfiguracja) -> None:
    """``przenies`` dla sesji pytest z ``pytest_configure`` kontrolera: przenosi tylko sesję z więcej niż jednym workerem
    xdist (pytest-xdist liczy już ``-n auto`` w ``pytest_cmdline_main``, a przechwytywanie wyjścia pytest jest wtedy
    zawieszone, więc wyjście ``boatbox`` idzie do wołającego)."""

    workers = config.getoption("numprocesses", default=None)
    if isinstance(workers, int) and workers > 1 and przeniesc():
        if found := niewidoczne(sys.orig_argv, Path.cwd()):
            _odmowa(found)
        _exec(skrypt(sys.orig_argv, Path.cwd()))


def uruchom(words: Sequence[str], cwd: Path, *, timeout: float, result: str, into: Path) -> subprocess.CompletedProcess[str]:
    """``words`` na boxie worktree ``cwd`` (``boatbox run --file`` z limitem ``timeout`` ponad ``START_S``), potem plik
    ``result`` (względny do ``cwd``) z boxa do katalogu ``into``, a na końcu usunięcie boxa, bo ``cwd`` to kopia, która
    znika po biegu. Kod ``NIE_WSTAL`` mówi, że box nie wstał, a polecenie nie ruszyło."""

    try:
        script = plik_skryptu(skrypt(words, cwd, root=cwd))
        done = potomne.run(["boatbox", "run", "--file", str(script)], cwd=cwd, timeout=timeout + START_S)
        if done.returncode != NIE_WSTAL:
            potomne.run(["boatbox", "get", result, str(into)], cwd=cwd, timeout=START_S)
        return done
    finally:
        try:
            potomne.run(["boatbox", "rm"], cwd=cwd, timeout=START_S)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"NA BOXIE | box kopii {cwd.name} zostaje do końca swojego czasu życia: {error}", file=sys.stderr, flush=True)
