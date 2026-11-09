"""Tworzy własne .venv checkoutu albo worktree z dodatkiem dev; uruchom w nowym worktree przed pierwszym poleceniem Pythona.

``.venv`` głównego checkoutu instaluje edytowalnie ``src`` głównego checkoutu,
więc pytest i skrypty weryfikacyjne uruchomione nim z worktree mogą po cichu
sprawdzać kod z ``main``. Ten skrypt tworzy ``.venv`` w checkoucie, w którym
leży, instaluje go edytowalnie i sprawdza, że ``rozliczenia`` importuje się z
jego ``src``. Używa ``uv``, gdy jest dostępne, a bez niego ``venv`` i ``pip``.
Włącza też bramę ``tools/hooks/pre-push`` (``core.hooksPath``) i sterownik scalania plików generowanych
(``merge=wygenerowane`` w ``.gitattributes``); oba siedzą w konfiguracji repozytorium, wspólnej dla wszystkich worktree.

    py -3 tools/setup_worktree.py              # Windows
    python3 tools/setup_worktree.py            # macOS i Linux
    python3 tools/setup_worktree.py --python 3.12
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import potomne
from repo import ROOT
import repo

VENV = ROOT / ".venv"
EXTRAS = ".[dev]"
HOOKS = "tools/hooks"
MINIMUM_PYTHON = (3, 11)  # requires-python z pyproject.toml
SUPPORTED = sys.version_info >= MINIMUM_PYTHON


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--python",
        default=sys.executable if SUPPORTED else "3.12",
        help="Python dla .venv przy użyciu uv (wersja albo ścieżka); domyślnie ten, który uruchomił skrypt.",
    )
    args = parser.parse_args(argv)

    uv = shutil.which("uv")
    if uv is not None:
        _run([uv, "venv", "--allow-existing", "--python", args.python, str(VENV)])
        _run([uv, "pip", "install", "--python", str(_venv_python()), "-e", EXTRAS])
    elif not SUPPORTED:
        print("BŁĄD: bez uv uruchom skrypt Pythonem 3.11 albo nowszym.", file=sys.stderr)
        return 1
    else:
        venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(VENV)  # jak ``python -m venv``
        _run([str(_venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-e", EXTRAS])

    # Na Windows `#!/usr/bin/env python3` w sh z Git for Windows trafia zwykle na alias Microsoft Store.
    if sys.platform != "win32":
        _gate_pushes()
    _merge_generated(ROOT)

    imported = _imported_package_directory()
    expected = ROOT / "src" / "rozliczenia"
    if imported != expected:
        print(f"BŁĄD: .venv importuje rozliczenia z {imported}, a powinno z {expected}.", file=sys.stderr)
        return 1
    print(f"OK: {VENV} importuje rozliczenia z {expected}.", flush=True)
    _print_work_in_progress()
    return 0


def _gate_pushes() -> None:
    try:
        configured = repo.git(ROOT, "config", "--get", "core.hooksPath").strip()
    except subprocess.CalledProcessError:
        configured = ""  # bez core.hooksPath
    if configured == HOOKS:
        return
    current = ROOT / repo.git(ROOT, "rev-parse", "--git-path", "hooks").strip()
    disabled = sorted(hook.name for hook in current.glob("*") if hook.is_file() and hook.suffix != ".sample")
    if disabled:
        print(f"UWAGA: core.hooksPath={HOOKS} wyłącza hooki z {current}: {', '.join(disabled)}.", file=sys.stderr)
    repo.git(ROOT, "config", "core.hooksPath", HOOKS)
    print(f"OK: push sprawdza {HOOKS}/pre-push.")


def _merge_generated(root: Path) -> None:
    repo.git(root, "config", "merge.wygenerowane.name", "plik generowany: wersja bieżącego HEAD, potem npm run regen")
    repo.git(root, "config", "merge.wygenerowane.driver", "true")


def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _imported_package_directory() -> Path:
    # Spoza checkoutu, żeby katalog bieżący nie zasłonił instalacji z .venv.
    with tempfile.TemporaryDirectory() as outside:
        completed = potomne.run(
            [str(_venv_python()), "-c", "import rozliczenia; print(rozliczenia.__file__)"], cwd=Path(outside)
        )
    completed.check_returncode()
    return Path(completed.stdout.strip()).resolve().parent


def _print_work_in_progress() -> None:
    """Raport ``tools/praca_w_toku.py``: każda sesja zaczyna od tego skryptu, więc widzi inne sesje."""

    try:
        potomne.run([str(_venv_python()), str(ROOT / "tools" / "praca_w_toku.py")], cwd=ROOT, timeout=120, echo=True)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"PRACA W TOKU POMINIĘTA | {error}")


def _run(command: list[str]) -> None:
    potomne.run(command, cwd=ROOT, echo=True).check_returncode()


if __name__ == "__main__":
    raise SystemExit(main())
