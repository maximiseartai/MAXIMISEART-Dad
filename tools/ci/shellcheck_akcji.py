"""shellcheck na skryptach ``run:`` akcji złożonych w ``.github/actions``, których actionlint nie czyta.

actionlint sprawdza shellcheckiem tylko ``.github/workflows``. To narzędzie bierze każdy krok ``run:`` z ``shell: bash``
w ``.github/actions/**/action.yml``, zastępuje wyrażenia ``${{ … }}`` podkreśleniami tej samej długości (jak actionlint)
i podaje skrypt shellcheckowi z tymi samymi wyłączonymi regułami co actionlint. Każda uwaga to linia
``<plik>:<linia>: <uwaga shellchecka>``, a kod wyjścia 1 znaczy, że jakaś padła.

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
SCRIPT = "skrypt.sh"
FINDING = re.compile(rf"^.*{re.escape(SCRIPT)}:(\d+):(\d+): (.*)$")


def mapping_value(node: yaml.Node, key: str) -> yaml.Node | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    return next((value for name, value in node.value if isinstance(name, yaml.ScalarNode) and name.value == key), None)


def bash_scripts(action: Path) -> list[tuple[int, str]]:
    """Skrypty kroków ``run:`` z ``shell: bash`` akcji, każdy z numerem linii pliku, na której stoi jego pierwsza linia."""

    root = yaml.compose(action.read_text(encoding="utf-8"))
    steps = mapping_value(mapping_value(root, "runs") or yaml.MappingNode("", []), "steps")
    scripts = []
    for step in steps.value if isinstance(steps, yaml.SequenceNode) else []:
        run, shell = mapping_value(step, "run"), mapping_value(step, "shell")
        if isinstance(run, yaml.ScalarNode) and isinstance(shell, yaml.ScalarNode) and shell.value == "bash":
            # Blok ``|`` zaczyna treść w linii po ``run:``, zwykły napis w linii ``run:`` (start_mark liczy od 0).
            first = run.start_mark.line + (2 if run.style in ("|", ">") else 1)
            scripts.append((first, EXPRESSION.sub(lambda found: "_" * len(found.group()), run.value)))
    return scripts


def findings(shellcheck: Sequence[str], root: Path = ROOT) -> list[str]:
    """Uwagi shellchecka (polecenie ``shellcheck``) o skryptach bash akcji złożonych w ``root``, linie ``<plik>:<linia>: …``."""

    lines = []
    with tempfile.TemporaryDirectory() as folder:
        written = Path(folder) / SCRIPT
        for action in sorted((root / ACTIONS).rglob("action.yml")):
            for first, script in bash_scripts(action):
                written.write_text(script, encoding="utf-8")
                answer = potomne.run(
                    [*shellcheck, "--norc", "--shell", "bash", "--format", "gcc", "--exclude", EXCLUDED, str(written)], cwd=root
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
