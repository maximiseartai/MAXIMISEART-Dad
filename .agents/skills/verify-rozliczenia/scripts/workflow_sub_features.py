from __future__ import annotations

import argparse
import sys
from types import ModuleType

import run_verification

OPIS = """Prints the section ``## Sub-features`` of a feature file from the plan of the variants of its process.

A feature is a process ``WorkflowProcess("<feature>", …)`` of ``run_verification.py``, and its variants are the entries
of ``WORKFLOW_VARIANTS`` on that process once the module has run. The command makes the plan of each variant
(``run_verification.plan``): ``_verify`` runs the variant's workflow, but every step and every change the workflow
makes to the run root between steps is recorded instead of run, with the run's folders as placeholders. So the
section holds what runs, ``cleanup`` and ``self-test`` included, and variants with the same plan share one list. A real
run compares the steps it ran with this plan and fails on a difference, so the variants CI runs prove the plan on every
run; the variants on the real Wzorce run only locally, and nothing compares their plan with a run.

The command refuses a feature name two processes share and a process no variant runs. It does not see a step run
other than through ``_run_step`` or ``_run_process_step``, a change to the run root other than through the two changes
the plan records, nor a branch of a workflow on what an earlier step left, which the plan's placeholder folders never
hold.
"""


class Refusal(Exception):
    """The processes of ``run_verification.py`` give no section for the feature; ``str`` says why and what to do."""


def section(feature: str, workflows: ModuleType = run_verification) -> str:
    """The section of ``feature`` from the processes and variants of ``workflows``."""

    variants = workflows.WORKFLOW_VARIANTS
    processes = {id(each): each for each in vars(workflows).values() if isinstance(each, workflows.WorkflowProcess)}
    processes |= {id(variant.process): variant.process for variant in variants.values()}
    names = [process.feature for process in processes.values()]
    if doubled := sorted({name for name in names if names.count(name) > 1}):
        raise Refusal(f"run_verification.py: two processes are named {', '.join(doubled)}; give each its own feature")
    if idle := sorted(p.feature for p in processes.values() if not any(v.process is p for v in variants.values())):
        raise Refusal(f"run_verification.py: no variant runs {', '.join(idle)}; add one to WORKFLOW_VARIANTS")
    if feature not in names:
        raise Refusal(f"run_verification.py: no WorkflowProcess(\"{feature}\", …); name the process of the feature so")
    plans: dict[tuple[run_verification.PlannedStep, ...], list[str]] = {}
    for name, variant in variants.items():
        if variant.process.feature == feature:
            plans.setdefault(tuple(workflows.plan(name)), []).append(name)
    lines = [
        "## Sub-features",
        "",
        f"Printed by `scripts/workflow_sub_features.py --feature {feature}` from the plan of each variant; refresh the "
        "section with it.",
    ]
    for steps, named in plans.items():
        lines += ["", f"{'Variants' if len(named) > 1 else 'Variant'} {', '.join(f'`{name}`' for name in named)}:", ""]
        lines += [
            f"- `{step.name}`: `{step.command}`, exit {step.expected_exit}."
            if step.expected_exit is not None
            else f"- `{step.name}`: makes {step.command} in the run root."
            for step in steps
        ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=OPIS, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--feature", required=True, help="feature of the map, the first argument of its WorkflowProcess")
    try:
        printed = section(parser.parse_args().feature)
    except Refusal as refusal:
        raise SystemExit(str(refusal)) from None
    # Bytes, so the Windows console (cp1252) neither refuses Polish letters nor turns line ends into CRLF.
    sys.stdout.buffer.write(printed.encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
