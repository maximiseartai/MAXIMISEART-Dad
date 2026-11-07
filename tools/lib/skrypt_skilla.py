"""Kontrakt wywołania skryptów skilli ``verify-*``: katalog runu, katalog przebiegu i warianty.

Skrypt skilla bierze te argumenty tylko z ``Parser`` (pilnuje tego ``tests/test_wywolanie_skryptow_skilli.py``):

- ``--root``: katalog jednego runu. Może leżeć gdziekolwiek, także poza repozytorium; względny liczy się od
  bieżącego katalogu w chwili wywołania, a dalej skrypt widzi już tylko ścieżkę bezwzględną.
- ``--run-dir``: katalog przebiegu runnera, z runami w ``runs/<id>`` i dowodami w ``evidence/<id>``.
  Domyślnie ``.verification`` checkoutu, w którym leży skrypt.
- ``--variant``: lista wariantów, także jako jeden argument ``"existing locked"`` albo ``"--variant existing"``.

Katalog runu zakłada ``create_run_root`` ze znacznikiem ``.katalog-runu``. Sprzątanie i kroki, które piszą do runu,
wymagają znacznika albo pustego katalogu, więc literówka w ``--root`` nie skasuje ani nie zmieni cudzego katalogu.
Sprzątanie usuwa znacznik ostatni, więc po przerwanym sprzątaniu następne wciąż rozpozna run.

Runner, który nic nie sprawdził (``VERIFY SKIP``), kończy się kodem ``SKIPPED``, a nie ``0``, więc pominięcie
nie wygląda dla wywołującego jak dowód.

Podstawa skilla (klucz ``ci:``) z kluczem ``ci-czesci: <n>`` dzieli się w CI na najwyżej n części: plan CI uruchamia
część k z ``MUTACJE_CZESC=k/n`` (``tools/lib/jednostka.py``), a skrypt bierze swoje jednostki (funkcje, zakresy) przez
``part``: k-ty z n kolejnych kawałków w ich kolejności (``Czesc.kawalek``), więc n części sprawdza każdą jednostkę dokładnie raz, a stan,
który jednostka zostawia następnej, zostaje jak w całym przebiegu wewnątrz części.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Any, TypeVar

from jednostka import ZMIENNA_CZESCI, Czesc

T = TypeVar("T")

VERIFICATION = Path(__file__).resolve().parents[2] / ".verification"
MARKER = ".katalog-runu"
EVERY = "all"
SKIPPED = 3


class RunRootError(ValueError):
    """Katalog runu jest zajęty albo nie założyła go fixture skilla."""


def absolute_path(value: str) -> Path:
    if not value.strip():
        raise argparse.ArgumentTypeError("pusta ścieżka")
    return Path(value).expanduser().resolve()


@dataclass(frozen=True)
class _Variants:
    known: tuple[str, ...]
    default: str
    every: tuple[str, ...]

    def resolve(self, given: Sequence[str] | None, parser: argparse.ArgumentParser) -> tuple[str, ...]:
        names = [name for value in given or (self.default,) for name in value.replace(",", " ").split()]
        unknown = [name for name in names if name not in (*self.known, EVERY)]
        if unknown or not names:
            known = ", ".join((*self.known, EVERY))
            parser.error(f"--variant: nieznany wariant {', '.join(unknown) or '(pusty)'}; znane: {known}")
        expanded = (variant for name in names for variant in (self.every if name == EVERY else (name,)))
        return tuple(dict.fromkeys(expanded))


class Parser(argparse.ArgumentParser):
    """``ArgumentParser`` skryptu skilla; argumenty kontraktu dodają tylko jego metody."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._variants: _Variants | None = None

    def add_root(self, help: str) -> None:
        self.add_argument("--root", type=absolute_path, required=True, help=help)

    def add_run_dir(self) -> None:
        self.add_argument(
            "--run-dir",
            type=absolute_path,
            default=VERIFICATION,
            help="katalog przebiegu: runy w runs/<id>, dowody w evidence/<id> (domyślnie .verification checkoutu)",
        )

    def add_variants(self, known: Iterable[str], *, default: str, every: Iterable[str]) -> None:
        """``args.variant`` to krotka wariantów w podanej kolejności; ``all`` to ``every``."""

        variants = self._variants = _Variants(tuple(known), default, tuple(every))
        self.add_argument(
            "--variant",
            nargs="+",
            action="extend",
            metavar="WARIANT",
            help=f"jeden albo kilka z: {', '.join((*variants.known, EVERY))} "
            f"(domyślnie {default}; {EVERY}: {', '.join(variants.every)})",
        )

    def parse_known_args(  # type: ignore[override]
        self, args: Sequence[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> tuple[argparse.Namespace, list[str]]:
        given = sys.argv[1:] if args is None else list(args)
        parsed, rest = super().parse_known_args(list(self._split_joined(given)), namespace)
        if self._variants is not None:
            parsed.variant = self._variants.resolve(parsed.variant, self)
        return parsed, rest

    def _split_joined(self, arguments: Iterable[str]) -> Iterable[str]:
        """``"--variant existing"`` jako jeden argument (zsh nie dzieli ``$a``) to ``--variant=existing``."""

        for argument in arguments:
            option, *value = argument.split(None, 1) or [argument]
            if value and argument.startswith("--") and option in self._option_string_actions:
                yield f"{option}={value[0]}"
            else:
                yield argument


@dataclass(frozen=True)
class Run:
    """Jeden run runnera: ``root`` zakłada fixture i usuwa sprzątanie, ``evidence`` zostaje."""

    root: Path
    evidence: Path


def new_run(run_dir: Path, name: str) -> Run:
    evidence = run_dir / "evidence" / name
    evidence.mkdir(parents=True)
    return Run(run_dir / "runs" / name, evidence)


def create_run_root(root: Path) -> Path:
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise RunRootError(f"katalog runu nie jest pusty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    (root / MARKER).write_text("Katalog runu skilla verify-*; sprzątanie skilla go usuwa.\n", encoding="utf-8")
    return root


def require_run_root(root: Path) -> Path:
    if not (root / MARKER).is_file() and (not root.is_dir() or any(root.iterdir())):
        raise RunRootError(f"{root} nie ma znacznika {MARKER}: nie założyła go fixture skilla")
    return root


def remove_run_root(root: Path) -> None:
    if not root.exists():
        return
    for entry in require_run_root(root).iterdir():
        if entry.name != MARKER:
            _remove(entry)
    (root / MARKER).unlink(missing_ok=True)
    root.rmdir()


def _remove(path: Path) -> None:
    if not path.is_dir() or path.is_symlink():
        try:
            path.unlink()
        except PermissionError:
            _writable_then_retry(os.unlink, str(path), None)
    elif sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_writable_then_retry)
    else:
        shutil.rmtree(path, onerror=_writable_then_retry)


def _writable_then_retry(function: Callable[..., Any], path: str, _: object) -> None:
    """Git na Windowsie zapisuje obiekty tylko do odczytu; usuwanie przechodzi po zdjęciu tej blokady."""

    Path(path).chmod(stat.S_IRWXU)
    function(path)


def part(units: Sequence[T], environment: Mapping[str, str] = os.environ) -> tuple[T, ...]:
    """Jednostki części ``K/N`` z ``MUTACJE_CZESC`` w ``environment``: K-ty z N kolejnych kawałków ``units`` (bez
    zmiennej wszystkie). Zła postać albo N większe od liczby jednostek, przy którym część byłaby pusta, to ``ValueError``."""

    value = environment.get(ZMIENNA_CZESCI)
    if not value:
        return tuple(units)
    try:
        czesc = Czesc.z_tekstu(value)
    except ValueError:
        czesc = None
    if czesc is None or czesc.n > len(units):
        raise ValueError(f"{ZMIENNA_CZESCI} to K/N z 1 <= K <= N <= {len(units)}, nie {value!r}")
    return tuple(czesc.kawalek(units))
