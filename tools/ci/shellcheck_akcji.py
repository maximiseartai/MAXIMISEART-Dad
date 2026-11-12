"""shellcheck na skryptach ``run:`` akcji złożonych w ``.github/actions``, których actionlint nie czyta.

actionlint sprawdza shellcheckiem tylko ``.github/workflows``. To narzędzie bierze każdy krok ``run:`` z ``shell: bash``
albo ``shell: sh`` (także z argumentami, np. ``bash -e {0}``) w ``.github/actions/**/action.yml``, zastępuje wyrażenia
``${{ … }}`` podkreśleniami (jak actionlint, z zachowaniem podziału na linie) i podaje skrypt shellcheckowi z tymi samymi
wyłączonymi regułami co actionlint. Każda uwaga to linia ``<plik>:<linia>: <uwaga shellchecka>``, a kod wyjścia 1 znaczy,
że jakaś padła. W bloku zawijanym ``>`` YAML łączy linie, więc tam numer linii jest przybliżony.

    python tools/ci/shellcheck_akcji.py                          # CI, shellcheck z PATH
    .venv/bin/python tools/ci/shellcheck_akcji.py --shellcheck .venv/bin/shellcheck
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/lib"))

import potomne

ROOT = Path(__file__).resolve().parents[2]
ACTIONS = ".github/actions"
# Reguły, które actionlint wyłącza dla skryptów kroków, bo nie pasują do skryptu wyciętego z YAML.
EXCLUDED = "SC1091,SC2194,SC2050,SC2154,SC2157"
EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.DOTALL)
# Pierwsze słowo ``shell:`` kroku i dialekt, którym shellcheck go czyta.
SHELLS = {"bash": "bash", "sh": "sh"}
SCRIPT = "skrypt.sh"
FINDING = re.compile(rf"^.*{re.escape(SCRIPT)}:(\d+):(\d+): (.*)$")


def mapping_value(node: yaml.Node, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    return next((value for name, value in node.value if isinstance(name, yaml.ScalarNode) and name.value == key), None)


def shell_scripts(action: Path) -> list[tuple[int, str, str]]:
    """Skrypty kroków ``run:`` z powłoką z ``SHELLS``, każdy z numerem linii pliku, na której stoi jego pierwsza linia,
    i dialektem shellchecka."""

    root = yaml.compose(action.read_text(encoding="utf-8"))
    steps = mapping_value(mapping_value(root, "runs") or yaml.MappingNode("", []), "steps")
    scripts = []
    for step in steps.value if isinstance(steps, yaml.SequenceNode) else []:
        run, shell = mapping_value(step, "run"), mapping_value(step, "shell")
        dialect = SHELLS.get(shell.value.split()[0]) if isinstance(shell, yaml.ScalarNode) and shell.value.strip() else None
        if isinstance(run, yaml.ScalarNode) and dialect:
            # Blok ``|`` zaczyna treść w linii po ``run:``, zwykły napis w linii ``run:`` (start_mark liczy od 0).
            first = run.start_mark.line + (2 if run.style in ("|", ">") else 1)
            script = EXPRESSION.sub(lambda found: re.sub(r"[^\n]", "_", found.group()), run.value)
            scripts.append((first, dialect, script))
    return scripts


def findings(shellcheck: Sequence[str], root: Path = ROOT) -> list[str]:
    """Uwagi shellchecka (polecenie ``shellcheck``) o skryptach powłoki akcji złożonych w ``root``, linie ``<plik>:<linia>: …``."""

    lines = []
    with tempfile.TemporaryDirectory() as folder:
        written = Path(folder) / SCRIPT
        for action in sorted((root / ACTIONS).rglob("action.yml")):
            for first, dialect, script in shell_scripts(action):
                # Bez newline= Windows zapisałby \r\n, a shellcheck zgłasza każdy \r w skrypcie (SC1017).
                written.write_text(script, encoding="utf-8", newline="\n")
                answer = potomne.run(
                    [*shellcheck, "--norc", "--shell", dialect, "--format", "gcc", "--exclude", EXCLUDED, str(written)], cwd=root
                )
                lines.extend(_lines(action.relative_to(root).as_posix(), first, answer))
    return lines


def _lines(relative: str, first: int, answer: subprocess.CompletedProcess[str]) -> list[str]:
    """Uwagi jednego skryptu z liniami pliku akcji; shellcheck, który padł bez uwag, to też uwaga."""

    lines = []
    for line in answer.stdout.splitlines():
        found = FINDING.match(line)
        lines.append(f"{relative}:{first + int(found.group(1)) - 1}: {found.group(3)}" if found else f"{relative}: {line}")
    if answer.returncode != 0 and not answer.stdout:
        lines.append(f"{relative}:{first}: shellcheck {answer.returncode}: {answer.stderr.strip()}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--shellcheck", default="shellcheck", help="ścieżka do shellchecka (domyślnie z PATH)")
    arguments = parser.parse_args(argv)
    lines = findings([arguments.shellcheck])
    print("\n".join(lines) if lines else f"SHELLCHECK AKCJI OK | {ACTIONS}")
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
