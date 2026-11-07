"""Wynik referencyjny scenariusza zamrożony z commita i bramka poprawności pomiaru względem niego."""

from __future__ import annotations

import difflib
import hashlib
import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark import SCRIPT, BenchmarkError
from benchmark.lustro import worker_settlements_folder
from benchmark.uruchomienie import Przebieg, remove_worker_settlements, run_przebieg
from repo import ROOT
import repo
from porownanie_rozliczen import CATEGORIES, compare_worker_settlements
from potomne import commit_copy


ORACLE_CATEGORIES = (*CATEGORIES, "liczniki", "komunikaty", "podsumowanie")


REFERENCE_RESULT = "wynik.json"


@dataclass(frozen=True)
class Reference:
    """Zamrożony wynik referencyjny scenariusza z jednego commita."""

    folder: Path
    counters: dict[str, Any]
    result: dict[str, Any]


def reference_folder(references: Path, mirror: Path, worker_template: Path) -> Path:
    """Wyniki referencyjne lustra zamrożone z tym Wzorcem rozliczenia pracownika.

    Lustro nie zależy od Wzorca rozliczenia pracownika (używa go dopiero Przebieg
    rozliczeń), więc klucz wyniku referencyjnego to lustro i odcisk tego Wzorca:
    wynik zamrożony z jednym Wzorcem nigdy nie jest porównywany z pomiarem na innym.
    """

    fingerprint = hashlib.sha256(worker_template.read_bytes()).hexdigest()[:12]
    return references / f"{mirror.name}-wzorzec-{fingerprint}"


def freeze_reference(
    references: Path, mirror: Path, commit: str, config: Path, worker_template: Path
) -> Path:
    """Wynik referencyjny lustra z commita ``commit``: jego Przebieg rozliczeń w tymczasowej kopii commitu."""

    sha = repo.commit(ROOT, commit)
    if sha is None:
        raise BenchmarkError(f"Nie ma commita {commit}.")
    target = reference_folder(references, mirror, worker_template) / sha
    if target.exists():
        raise BenchmarkError(f"Wynik referencyjny {sha[:7]} dla {target.parent.name} już jest: {target}.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="benchmark-referencja-") as scratch_name:
        scratch = Path(scratch_name)
        try:
            with commit_copy(ROOT, sha) as checkout:
                if not (checkout / SCRIPT).is_file():
                    raise BenchmarkError(
                        f"Commit {sha[:7]} nie ma skryptu {SCRIPT.as_posix()}, przez który benchmark uruchamia "
                        "Przebieg rozliczeń. Zamroź wynik referencyjny z commita, który go ma: python tools/benchmark_przebiegu.py "
                        "freeze --commit SHA z tymi samymi --scenario, --templates-dir i --config."
                    )
                przebieg = run_przebieg(checkout, mirror, config, worker_template, scratch)
        except subprocess.CalledProcessError as error:
            raise BenchmarkError(
                f"Nie udało się zbudować commita {sha[:7]} w tymczasowym worktree gita: {error.stderr.strip()}"
            ) from error
        staging = Path(tempfile.mkdtemp(prefix=f".{sha}.staging-", dir=target.parent))
        try:
            worker_settlements = worker_settlements_folder(mirror)
            shutil.copytree(worker_settlements, staging / worker_settlements.name)
            result = {"git_sha": sha, "counters": przebieg.metrics["counters"], "result": przebieg.result}
            (staging / REFERENCE_RESULT).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            staging.rename(target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            remove_worker_settlements(worker_settlements_folder(mirror))
    return target


def _load_reference(folder: Path) -> Reference:
    frozen = json.loads((folder / REFERENCE_RESULT).read_text(encoding="utf-8"))
    if "result" not in frozen:
        raise BenchmarkError(
            f"Wynik referencyjny {folder.name[:7]} ma stary format: linie terminala sprzed przejścia benchmarku "
            f"na skrypt {SCRIPT.as_posix()}. Usuń {folder} i zamroź wynik od nowa: python tools/benchmark_przebiegu.py "
            "freeze --commit SHA z tymi samymi --scenario, --templates-dir i --config, z commita, który ma ten skrypt."
        )
    return Reference(folder, frozen["counters"], frozen["result"])


def find_reference(references: Path, mirror: Path, worker_template: Path, commit: str | None) -> Reference | None:
    """Wynik referencyjny lustra i Wzorca rozliczenia pracownika: wskazany prefiksem commita albo jedyny, jaki jest."""

    folder = reference_folder(references, mirror, worker_template)
    frozen = sorted(
        path for path in folder.glob("*") if not path.name.startswith(".") and (path / REFERENCE_RESULT).is_file()
    )
    if commit is not None:
        matching = [path for path in frozen if path.name.startswith(commit)]
        if len(matching) != 1:
            raise BenchmarkError(
                f"Dla {mirror.name} nie ma wyniku referencyjnego z commita {commit} zamrożonego z tym Wzorcem "
                f"rozliczenia pracownika ({folder.name}); zamroź go przez freeze z tymi samymi Wzorcami."
            )
        return _load_reference(matching[0])
    if len(frozen) > 1:
        raise BenchmarkError(f"Dla {folder.name} jest kilka wyników referencyjnych; wskaż jeden przez --reference.")
    return _load_reference(frozen[0]) if frozen else None


def _line_differences(reference: Sequence[str], candidate: Sequence[str]) -> int:
    matcher = difflib.SequenceMatcher(a=reference, b=candidate, autojunk=False)
    return sum(
        max(end_a - start_a, end_b - start_b)
        for tag, start_a, end_a, start_b, end_b in matcher.get_opcodes()
        if tag != "equal"
    )


def _message_codes(result: dict[str, Any]) -> list[str]:
    stop = result["stop"]
    return [warning["code"] for warning in result["warnings"]] + ([stop["message"]["code"]] if stop else [])


def _summary_lines(result: dict[str, Any]) -> list[str]:
    return json.dumps(result["summary"], ensure_ascii=False, indent=1, sort_keys=True).splitlines()


def check_oracle(reference: Reference, mirror: Path, przebieg: Przebieg) -> dict[str, Any]:
    """Bramka poprawności: liczba różnic w każdej kategorii względem wyniku referencyjnego, bez treści."""

    worker_settlements = worker_settlements_folder(mirror)
    differences = compare_worker_settlements(reference.folder / worker_settlements.name, worker_settlements)
    counters = przebieg.metrics["counters"]
    differences["liczniki"] = sum(
        counters.get(name) != reference.counters.get(name) for name in {*counters, *reference.counters}
    )
    differences["komunikaty"] = _line_differences(_message_codes(reference.result), _message_codes(przebieg.result))
    differences["podsumowanie"] = _line_differences(_summary_lines(reference.result), _summary_lines(przebieg.result))
    return {
        "wynik": "niezgodny" if any(differences.values()) else "zgodny",
        "referencja": reference.folder.name,
        "roznice": {category: differences[category] for category in ORACLE_CATEGORIES},
    }
