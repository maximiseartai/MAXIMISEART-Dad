"""Graf importów ``src/`` trzyma granice, które łamie jeden import.

Silnik nie zależy od Centrum rozliczeń (ADR 0004: Centrum to adapter Uruchomienia procesu). Moduły, z których
Centrum mówi o brakującej bibliotece, importują przy wczytaniu tylko bibliotekę standardową. Kopia opiekuna ponownego
startu (``_COPIED`` w ``restart_guardian.py``) importuje tylko bibliotekę standardową i siebie: moduł spoza kopii
kończy się ``ModuleNotFoundError``, bo pakiet ``rozliczenia`` kopii szuka modułów tylko w niej, a bibliotekę
spoza standardowej aktualizacja, którą opiekun kończy, mogła właśnie zmienić (``pip_install``). Test uruchomienia
kopii (``test_opiekun_ponownego_startu.py``) łapie brak modułu dopiero po minucie czekania na nową wersję, a
bibliotekę spoza standardowej, którą Python ma, przepuszcza.

Model efenix (``tools/lib/model_efenix.py``) importuje tylko bibliotekę standardową, a Atrapa efenix
(``tests/fixtures/atrapa_efenix.py``) tylko ją i model: z nimi testy i narzędzia porównują Wycenę w efenix, więc nie
biorą niczego z kodu pod testem (``src``). Okno w procesie (``tests/fixtures/okno_w_procesie.py``) bierze z kodu pod
testem tylko typy seamu Wyceny w efenix (klasy i aliasy typów z ``efenix_pricing`` i ``efenix_checks``), a decyzje bierze
z modelu: okno, które wołałoby kod Wyceny, przestałoby być niezależną drugą stroną kontraktu z oknem przeglądarki.

Test czyta AST importów, także względnych, importów w funkcji i pakietów nad modułem. Nowy moduł bez zależności
trafia do ``STDLIB_ONLY`` z powodem. Granica: import przez ``importlib`` albo ``__import__`` z napisu łapie tylko
przegląd.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
import typing

SRC = Path(__file__).resolve().parents[1] / "src"
GUARDIAN = SRC / "rozliczenia" / "centrum" / "restart_guardian.py"
ROOT = SRC.parent
# Wyrocznia Wyceny w efenix i moduły spoza biblioteki standardowej, które wolno jej importować.
EFENIX_ORACLE = {
    ROOT / "tools" / "lib" / "model_efenix.py": frozenset[str](),
    ROOT / "tests" / "fixtures" / "atrapa_efenix.py": frozenset({"model_efenix"}),
}
# Okno w procesie i moduły kodu pod testem, z których bierze tylko typy.
WINDOW_IN_PROCESS = ROOT / "tests" / "fixtures" / "okno_w_procesie.py"
WINDOW_SEAM = frozenset({"rozliczenia.efenix_checks", "rozliczenia.efenix_pricing"})
STDLIB_ONLY = {
    "rozliczenia/__init__.py": "pakiet, który wczytuje każdy moduł poniżej",
    "rozliczenia/centrum/__init__.py": "pakiet, który wczytuje każdy moduł Centrum",
    "rozliczenia/message.py": "Komunikat startu o brakującej bibliotece musi działać bez zależności",
    "rozliczenia/decision.py": "moduły procesu biorą z niego rozmowę bez zależności od rdzenia Uruchomienia",
    "rozliczenia/centrum/version.py": "launcher pyta o wersję, zanim wczyta FastAPI",
    "rozliczenia/centrum/log.py": "dziennik Centrum zapisuje błąd startu, gdy brakuje zależności",
    "rozliczenia/centrum/platform.py": "okienko z Komunikatem startu pokazuje też brak zależności",
    "rozliczenia/centrum/tool_update.py": "launcher kończy przerwaną Aktualizację narzędzia, zanim wczyta FastAPI",
    "rozliczenia/centrum/start_problems.py": "jeden z Komunikatów startu mówi o brakujących zależnościach",
    "rozliczenia/centrum/launcher.py": "brak FastAPI albo uvicorn staje się Komunikatem startu; resztę wczytuje w funkcji",
}


@dataclass(frozen=True)
class Import:
    file: str
    line: int
    code: str
    module: str
    nested: bool

    def __str__(self) -> str:
        return f"src/{self.file}:{self.line}: {self.code}"


def _module_name(file: str) -> str:
    parts = file.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _file_of(module: str) -> str | None:
    base = module.replace(".", "/")
    for file in (f"{base}.py", f"{base}/__init__.py"):
        if (SRC / file).is_file():
            return file
    return None


def _modules_loaded(module: str) -> Iterator[str]:
    """``module`` i pakiety nad nim: import modułu wczytuje każdy z nich."""

    parts = module.split(".")
    for end in range(1, len(parts) + 1):
        yield ".".join(parts[:end])


def _imports(file: str) -> Iterator[Import]:
    """Importy pliku z modułami, które wczytują; ``nested`` dla importu w funkcji."""

    tree = ast.parse((SRC / file).read_text(encoding="utf-8"))
    package = _module_name(file) if file.endswith("__init__.py") else _module_name(file).rpartition(".")[0]
    in_function = {
        node
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*anchor, *([base] if base else [])])
            names = [base, *(f"{base}.{alias.name}" for alias in node.names if _file_of(f"{base}.{alias.name}"))]
        else:
            continue
        for name in names:
            for module in _modules_loaded(name):
                yield Import(file, node.lineno, ast.unparse(node), module, node in in_function)


def _is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def _copied() -> tuple[str, ...]:
    for node in ast.parse(GUARDIAN.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "_COPIED":
            assert node.value is not None
            copied = ast.literal_eval(node.value)
            assert isinstance(copied, tuple)
            return copied
    raise AssertionError(f"{GUARDIAN.relative_to(SRC.parent)}: brak listy _COPIED, którą czyta ten test")


def test_silnik_nie_importuje_centrum_rozliczen() -> None:
    found = {
        str(found)
        for path in sorted((SRC / "rozliczenia").glob("*.py"))
        for found in _imports(path.relative_to(SRC).as_posix())
        if found.module == "rozliczenia.centrum"
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Silnik (src/rozliczenia/*.py) nie zależy od Centrum rozliczeń, adaptera Uruchomienia procesu (ADR 0004): "
            "przenieś potrzebny kod do silnika, a Centrum niech importuje go stamtąd.",
        ]
    )


def test_moduly_bez_zaleznosci_wczytuja_tylko_biblioteke_standardowa() -> None:
    allowed = {_module_name(file) for file in STDLIB_ONLY}
    found = {
        f"{found}  ({reason})"
        for file, reason in STDLIB_ONLY.items()
        for found in _imports(file)
        if not found.nested and not _is_stdlib(found.module) and found.module not in allowed
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Moduły z STDLIB_ONLY (tests/test_granice_importow.py, powód przy każdym) przy wczytaniu importują tylko "
            "bibliotekę standardową i siebie nawzajem. Przenieś import do funkcji, która go używa, albo dopisz "
            "moduł bez zależności do STDLIB_ONLY z powodem.",
        ]
    )


def test_kopia_opiekuna_ponownego_startu_importuje_tylko_biblioteke_standardowa_i_siebie() -> None:
    copied = _copied()
    allowed = {_module_name(file) for file in copied}
    found = {
        str(found)
        for file in copied
        for found in _imports(file)
        if not _is_stdlib(found.module) and found.module not in allowed
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Opiekun ponownego startu działa z kopii _COPIED (src/rozliczenia/centrum/restart_guardian.py) bez "
            "bibliotek narzędzia. Dopisz moduł bez zależności do _COPIED albo przenieś kod, który go potrzebuje, "
            "poza moduły kopii.",
        ]
    )


def test_model_i_atrapa_efenix_nie_importuja_kodu_pod_testem() -> None:
    found = {
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}: {ast.unparse(node)}"
        for path, allowed in EFENIX_ORACLE.items()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for module in ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""])
        if (isinstance(node, ast.ImportFrom) and node.level) or not (_is_stdlib(module) or module in allowed)
    }

    assert not found, "\n".join(
        [
            *sorted(found),
            "Model efenix (tools/lib/model_efenix.py) importuje tylko bibliotekę standardową, a Atrapa efenix "
            "(tests/fixtures/atrapa_efenix.py) tylko ją i model: test porównuje z nimi Wycenę w efenix, więc nie biorą "
            "niczego z kodu pod testem. Napisz potrzebny kod w modelu albo w Atrapie.",
        ]
    )


def test_okno_w_procesie_bierze_z_kodu_pod_testem_tylko_typy_seamu() -> None:
    found = []
    for node in ast.walk(ast.parse(WINDOW_IN_PROCESS.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [ast.unparse(node) for alias in node.names if not _is_stdlib(alias.name)]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or not (_is_stdlib(module) or module == "model_efenix" or module in WINDOW_SEAM):
                found.append(ast.unparse(node))
            elif module in WINDOW_SEAM:
                imported = importlib.import_module(module)
                found += [
                    f"{module}.{alias.name}"
                    for alias in node.names
                    if not _is_type(getattr(imported, alias.name))
                ]

    assert not found, "\n".join(
        [
            *sorted(found),
            "Okno w procesie (tests/fixtures/okno_w_procesie.py) bierze z rozliczenia tylko klasy i aliasy typów z "
            "efenix_pricing i efenix_checks, a decyzje z modelu efenix (tools/lib/model_efenix.py).",
        ]
    )


def _is_type(value: object) -> bool:
    """Klasa (także wyliczenie i wyjątek) albo alias typu (``Callable[...]``, unia)."""

    return isinstance(value, type) or typing.get_origin(value) is not None
