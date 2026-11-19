"""``.venv`` głównego checkoutu instaluje edytowalnie ``src`` głównego checkoutu,
więc pytest i skrypty weryfikacyjne uruchomione nim z worktree mogą po cichu
sprawdzać kod z ``main``. Ten skrypt tworzy ``.venv`` w checkoucie, w którym
leży, instaluje go edytowalnie i sprawdza, że ``rozliczenia`` importuje się z
jego ``src``. Używa ``uv``, gdy jest dostępne, a bez niego ``venv`` i ``pip``.
Plik ``.pth`` (``IMPORT_PTH``) daje każdemu Pythonowi z ``.venv`` katalogi importu testów (``repo.IMPORT_ROOTS``),
więc próba ``.venv/bin/python -c "import wplyw_zmiany"`` importuje moduły narzędzi bez ``sys.path`` i ``PYTHONPATH``.
Włącza też bramę ``tools/hooks/pre-push`` (``core.hooksPath``), sterownik scalania plików generowanych
(``merge=wygenerowane`` w ``.gitattributes``) i sterownik scalania skrótów modeli skilli (``merge=model-skilla``, czyli
``tools/przesun_model.py --scal`` Pythonem z ``.venv`` worktree, który scala); wszystkie siedzą w konfiguracji
repozytorium, wspólnej dla wszystkich worktree.

    py -3 tools/setup_worktree.py              # Windows
    python3 tools/setup_worktree.py            # macOS i Linux
    python3 tools/setup_worktree.py --python 3.14
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

OPIS = "Tworzy własne .venv checkoutu albo worktree z dodatkami dev i workflowy; uruchom w nowym worktree przed pierwszym poleceniem Pythona."

VENV = ROOT / ".venv"
EXTRAS = ".[dev,workflowy]"
IMPORT_PTH = "maximiseart_katalogi_importu.pth"
HOOKS = "tools/hooks"
MINIMUM_PYTHON = (3, 13)  # requires-python z pyproject.toml
MINIMUM = ".".join(map(str, MINIMUM_PYTHON))
SUPPORTED = sys.version_info >= MINIMUM_PYTHON
VENV_PYTHON = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=OPIS)
    parser.add_argument(
        "--python",
        default=sys.executable if SUPPORTED else MINIMUM,
        help="Python dla .venv przy użyciu uv (wersja albo ścieżka); domyślnie ten, który uruchomił skrypt.",
    )
    args = parser.parse_args(argv)

    uv = shutil.which("uv")
    if uv is not None:
        _run([uv, "venv", "--allow-existing", "--python", args.python, str(VENV)])
        _run([uv, "pip", "install", "--python", str(_venv_python()), "-e", EXTRAS])
    elif not SUPPORTED:
        print(f"BŁĄD: bez uv uruchom skrypt Pythonem {MINIMUM} albo nowszym.", file=sys.stderr)
        return 1
    else:
        venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(VENV)  # jak ``python -m venv``
        _run([str(_venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-e", EXTRAS])

    # Na Windows `#!/usr/bin/env python3` w sh z Git for Windows trafia zwykle na alias Microsoft Store.
    if sys.platform != "win32":
        _gate_pushes(ROOT)
    _merge_generated(ROOT)
    _merge_model_digests(ROOT, VENV_PYTHON)
    _write_import_roots(_venv_python())

    for module, expected in (("rozliczenia", ROOT / "src" / "rozliczenia"), ("repo", ROOT / "tools" / "lib")):
        imported = _imported_directory(module)
        if imported != expected:
            print(f"BŁĄD: .venv importuje {module} z {imported}, a powinno z {expected}.", file=sys.stderr)
            return 1
    print(f"OK: {VENV} importuje rozliczenia z src i moduły narzędzi z katalogów repo.IMPORT_ROOTS.", flush=True)
    _print_work_in_progress()
    return 0


def _gate_pushes(root: Path) -> None:
    try:
        configured = repo.git(root, "config", "--get", "core.hooksPath").strip()
    except subprocess.CalledProcessError:
        configured = ""  # bez core.hooksPath
    if configured == HOOKS:
        return
    current = root / repo.git(root, "rev-parse", "--git-path", "hooks").strip()
    disabled = sorted(hook.name for hook in current.glob("*") if hook.is_file() and hook.suffix != ".sample")
    if disabled:
        print(f"UWAGA: core.hooksPath={HOOKS} wyłącza hooki z {current}: {', '.join(disabled)}.", file=sys.stderr)
    repo.git(root, "config", "core.hooksPath", HOOKS)
    print(f"OK: push sprawdza {HOOKS}/pre-push.")


def _merge_generated(root: Path) -> None:
    repo.git(root, "config", "merge.wygenerowane.name", "plik generowany: wersja bieżącego HEAD, potem npm run regen")
    repo.git(root, "config", "merge.wygenerowane.driver", "true")


def _merge_model_digests(root: Path, python: str) -> None:
    repo.git(root, "config", "merge.model-skilla.name", "skróty modelu skilla: scalenie definicji, skrót zmieniony po obu stronach z drzewa scalenia")
    repo.git(root, "config", "merge.model-skilla.driver", f"{python} tools/przesun_model.py --scal %O %A %B %P")


def _venv_python() -> Path:
    return ROOT / VENV_PYTHON


def _write_import_roots(python: Path) -> None:
    purelib = _python_output(python, "import sysconfig; print(sysconfig.get_path('purelib'))")
    lines = "".join(f"{ROOT / root}\n" for root in repo.IMPORT_ROOTS)
    (Path(purelib) / IMPORT_PTH).write_text(lines, encoding="utf-8")


def _imported_directory(module: str) -> Path:
    return Path(_python_output(_venv_python(), f"import {module}; print({module}.__file__)")).resolve().parent


def _python_output(python: Path, code: str) -> str:
    # Spoza checkoutu, żeby katalog bieżący nie zasłonił instalacji z .venv.
    with tempfile.TemporaryDirectory() as outside:
        completed = potomne.run([str(python), "-c", code], cwd=Path(outside))
    completed.check_returncode()
    return completed.stdout.strip()


def _print_work_in_progress() -> None:
    """Odpowiedzi ``tools/praca_w_toku.py``: każda sesja zaczyna od tego skryptu, więc dostaje podpowiedź ``--issue``."""

    try:
        potomne.run([str(_venv_python()), str(ROOT / "tools" / "praca_w_toku.py")], cwd=ROOT, timeout=30, echo=True)
    except (OSError, subprocess.TimeoutExpired) as error:
        print(f"PRACA W TOKU POMINIĘTA | {error}")


def _run(command: list[str]) -> None:
    potomne.run(command, cwd=ROOT, echo=True).check_returncode()


if __name__ == "__main__":
    raise SystemExit(main())
