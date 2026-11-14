"""Szeroki ``except`` w Centrum rozliczeń przekazuje złapany wyjątek do dziennika Centrum albo rzuca go dalej.

Ruff BLE001 uznaje za wpis do dziennika tylko ``logging``, a Centrum ma własny dziennik, więc ``pyproject.toml``
wyłącza BLE001 dla ``src/rozliczenia/centrum``, a tę samą regułę z dziennikiem Centrum sprawdza ten test.
``except Exception``, ``except BaseException`` i gołe ``except`` przechodzą, gdy blok woła ``unexpected_failure``
ze złapanym wyjątkiem albo go rzuca. Gołe ``raise`` w zagnieżdżonym ``except`` rzuca wyjątek wewnętrzny, więc się nie
liczy. Blok, który kończy się czym innym, ma wpis w ``OTHER_ENDINGS`` z powodem.
``contextlib.suppress(Exception)`` i typ wyjątku pod inną nazwą są poza testem, tak jak były poza BLE001.

Tłumienie reguły (najczęściej BLE001) ma powód na linii, a liczba tłumień ruff i mypy w każdym katalogu stoi w
``ZAPISANE`` (ADR 0034). Test bierze od narzędzi to, co one same uznają: pliki z ``ruff check --show-files`` i linie
konfiguracji mypy z ``mypy.util.get_mypy_comments``, i liczy tokeny tłumień, nie postacie kodu:

- ``noqa``: komentarz (``tokenize``) z dyrektywą ruff ``# noqa`` także po innym tekście komentarza, plikową
  ``# ruff: noqa`` albo ``# flake8: noqa`` i zakresową ``# ruff: disable[...]``, według ``RUFF``: ruff nie wypisuje
  swoich dyrektyw, a RUF100 zgłasza tylko te bez naruszenia, więc nie widzi ``# noqa: RUF100`` ani plików pod
  ``# ruff: noqa``;
- ``type: ignore``: ``type_ignores`` parsera Pythona, z którego bierze je mypy, i każda linia konfiguracji
  ``# mypy: ``, także w docstringu albo napisie, bo mypy czyta ją z surowych linii pliku.

Napis „noqa” w docstringu albo w napisie nie jest komentarzem, więc się nie liczy, a postacie, których nie ma w
repozytorium, stoją w ``PROBKI``. Czy tłumienie jest zasadne, ocenia przegląd. Próbki ``ZNANE_LUKI`` pokazują
znane luki: zmiany, które dodają tłumienie, a licznik ich nie widzi; nazwa próbki mówi ich klasę.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import functools
import io
from pathlib import Path
import re
import subprocess
import sys
import tokenize
from typing import Final

from tests.fixtures.znane_luki import assert_znane_luki, wymaga_ruff_i_mypy

ROOT = Path(__file__).resolve().parents[1]
CENTRUM = ROOT / "src" / "rozliczenia" / "centrum"
BROAD = frozenset({"Exception", "BaseException"})
NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)
OTHER_ENDINGS = {
    "restart_guardian.py::_rolled_back": "każda porażka cofnięcia kończy się okienkiem dla taty",
    "runs.py::Run.work": "RunHost.failed zapisuje typ wyjątku przez unexpected_failure dziennika Centrum",
}


def _broad(handler: ast.ExceptHandler) -> bool:
    caught = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(name is None or ast.unparse(name).removeprefix("builtins.") in BROAD for name in caught)


def _own_nodes(handler: ast.ExceptHandler) -> Iterator[tuple[ast.AST, bool]]:
    """Węzły bloku ``except`` bez ciał funkcji i klas, z tym, czy stoją w zagnieżdżonym ``except``."""

    pending: list[tuple[ast.AST, bool]] = [(node, False) for node in handler.body]
    while pending:
        node, inner = pending.pop()
        yield node, inner
        pending.extend(
            (child, inner or isinstance(child, ast.ExceptHandler))
            for child in ast.iter_child_nodes(node)
            if not isinstance(child, NESTED)
        )


def _is_caught(node: ast.expr | None, handler: ast.ExceptHandler) -> bool:
    return isinstance(node, ast.Name) and node.id == handler.name


def _ends_at_log_or_raise(handler: ast.ExceptHandler) -> bool:
    for node, inner in _own_nodes(handler):
        if isinstance(node, ast.Raise) and (
            (node.exc is None and not inner) or _is_caught(node.exc, handler) or _is_caught(node.cause, handler)
        ):
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "unexpected_failure"
            and node.args
            and _is_caught(node.args[0], handler)
        ):
            return True
    return False


def _broad_handlers(tree: ast.Module) -> Iterator[tuple[str, ast.ExceptHandler]]:
    """Szerokie bloki ``except`` modułu z nazwą funkcji, w której stoją (``Klasa.metoda``)."""

    def visit(node: ast.AST, scope: tuple[str, ...]) -> Iterator[tuple[str, ast.ExceptHandler]]:
        for child in ast.iter_child_nodes(node):
            inner = (*scope, child.name) if isinstance(child, NESTED) and not isinstance(child, ast.Lambda) else scope
            if isinstance(child, ast.ExceptHandler) and _broad(child):
                yield ".".join(scope) or "<moduł>", child
            yield from visit(child, inner)

    return visit(tree, ())


def test_szeroki_except_w_centrum_konczy_sie_dziennikiem_centrum_albo_ponownym_rzuceniem() -> None:
    problems = []
    unused = dict(OTHER_ENDINGS)
    for path in sorted(CENTRUM.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for where, handler in _broad_handlers(tree):
            key = f"{path.relative_to(CENTRUM).as_posix()}::{where}"
            if _ends_at_log_or_raise(handler):
                continue
            if unused.pop(key, None) is None:
                problems.append(
                    f"{path.relative_to(ROOT).as_posix()}:{handler.lineno} ({where}): szeroki except bez "
                    "unexpected_failure(<złapany wyjątek>, where=...) dziennika Centrum i bez raise; dopisz jedno "
                    f"z nich albo wpis {key!r} z powodem do OTHER_ENDINGS"
                )

    problems.extend(f"OTHER_ENDINGS: {key} nie ma już szerokiego except bez dziennika, usuń wpis" for key in unused)
    assert problems == [], "\n".join(problems)


# Katalog → rodzaj tłumienia → liczba na main. Plik w korzeniu repozytorium liczy się w ".".
ZAPISANE = {
    ".": {"noqa": 0, "type: ignore": 0},
    ".agents/skills": {"noqa": 22, "type: ignore": 13},
    "src": {"noqa": 11, "type: ignore": 7},
    "tests": {"noqa": 3, "type: ignore": 39},
    "tools": {"noqa": 23, "type: ignore": 6},
}

_KODY = r"[A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*"
RUFF = re.compile(
    rf"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa\b(?:\s*:\s*{_KODY})?(?P<powod>[^#]*)"
    rf"|#\s*ruff\s*:\s*disable\[[^\]]*\](?P<powod_zakresu>[^#]*)",
    re.IGNORECASE,
)

# Postać tłumienia, której nie ma w repozytorium → kod pliku w src/ drzewa próbek i liczby, które uznaje narzędzie.
PROBKI: Final = {
    "plikowe # ruff: noqa": ("# ruff: noqa - próbka\nimport os\n", {"noqa": 1, "type: ignore": 0}),
    "plikowe # flake8: noqa": ("# flake8: noqa - próbka\nimport os\n", {"noqa": 1, "type: ignore": 0}),
    "zakresowe # ruff: disable[...]": (
        "# ruff: disable[E501] - próbka\nx = 1\n# ruff: enable[E501]\n",
        {"noqa": 1, "type: ignore": 0},
    ),
    "# mypy: w kolumnie 0": ("# mypy: ignore-errors\nx: int = 1\n", {"noqa": 0, "type: ignore": 1}),
    "# mypy: w docstringu modułu": ('"""Moduł.\n\n# mypy: ignore-errors\n"""\n', {"noqa": 0, "type: ignore": 1}),
    "# mypy: w napisie wielowierszowym": ('y = """\n# mypy: ignore-errors\n"""\n', {"noqa": 0, "type: ignore": 1}),
    "wcięte # mypy:, którego mypy nie czyta": (
        "def f() -> None:\n    # mypy: ignore-errors\n    pass\n",
        {"noqa": 0, "type: ignore": 0},
    ),
    "noqa w docstringu, który nie jest komentarzem": ('"""Moduł # noqa: E501."""\n', {"noqa": 0, "type: ignore": 0}),
}

# Znane luki licznika (tests/fixtures/znane_luki.py): „klasa, którą przepuszcza licznik: zmiana” → pliki drzewa przed
# zmianą i po niej, na których licznik daje te same liczby, choć zmiana dodaje tłumienie. Plik pyproject.toml próbki zastępuje konfigurację
# repozytorium na jej drzewie, a jej ostatnia tabela to [tool.ruff].
_KONFIGURACJA = '[tool.ruff]\ninclude = ["*.py"]\n'
ZNANE_LUKI: Final = {
    "porównuje saldo katalogu, nie linie: noqa usunięte w jednym pliku, nowe dodane w drugim": (
        {"src/a.py": "import os  # noqa: F401 - próbka\n", "src/b.py": "y = 2\n"},
        {"src/a.py": "x = 1\n", "src/b.py": "import sys  # noqa: F401 - próbka\n"},
    ),
    "liczy linie kodu, nie konfigurację: per-file-ignores ruff": (
        {"pyproject.toml": _KONFIGURACJA, "src/a.py": "x = 1\n"},
        {
            "pyproject.toml": _KONFIGURACJA + '\n[tool.ruff.lint.per-file-ignores]\n"src/a.py" = ["F401"]\n',
            "src/a.py": "import os\n",
        },
    ),
    "liczy linie kodu, nie konfigurację: overrides mypy z ignore_errors": (
        {"pyproject.toml": _KONFIGURACJA, "src/a.py": "x: int = 1\n"},
        {
            "pyproject.toml": _KONFIGURACJA + '\n[[tool.mypy.overrides]]\nmodule = ["a"]\nignore_errors = true\n',
            "src/a.py": 'x: int = "1"\n',
        },
    ),
    "czyta tylko pliki, które listuje ruff: noqa w pliku z extend-exclude": (
        {"pyproject.toml": _KONFIGURACJA, "src/a.py": "x = 1\n"},
        {
            "pyproject.toml": _KONFIGURACJA + 'extend-exclude = ["src/b.py"]\n',
            "src/a.py": "x = 1\n",
            "src/b.py": "import os  # noqa: F401 - próbka\n",
        },
    ),
    "czyta tylko pliki, które listuje ruff: type: ignore w pliku, który sprawdza tylko mypy": (
        {"pyproject.toml": _KONFIGURACJA, "src/a.py": "x = 1\n"},
        {
            "pyproject.toml": _KONFIGURACJA + 'extend-exclude = ["src/b.py"]\n',
            "src/a.py": "x = 1\n",
            "src/b.py": 'y: int = "1"  # type: ignore[assignment]\n',
        },
    ),
    # Dekorator typing.no_type_check, drugą postać tej klasy, odrzuca zakaz ruff TID251 (przegląd #1689, W1).
    "liczy komentarze tłumień, nie tłumienie zapisane kodem: gałąź if not TYPE_CHECKING, której mypy nie sprawdza": (
        {"src/a.py": "x = 1\n"},
        {"src/a.py": 'from typing import TYPE_CHECKING\n\nif not TYPE_CHECKING:\n\n    def f() -> int:\n        return "1"\n'},
    ),
}


@dataclass(frozen=True)
class Tlumienie:
    katalog: str
    rodzaj: str
    miejsce: str
    tekst: str
    powod: bool


def _katalog(sciezka: str) -> str:
    return next((katalog for katalog in ZAPISANE if katalog != "." and sciezka.startswith(f"{katalog}/")), ".")


def _pliki(root: Path) -> list[str]:
    """Pliki, które sprawdza ruff z konfiguracją ``root``, względem ``root``."""

    pokazane = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--show-files"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=root,
        check=True,
    )
    return sorted(Path(linia).relative_to(root).as_posix() for linia in pokazane.stdout.splitlines())


@functools.cache
def _tlumienia(root: Path) -> list[Tlumienie]:
    """Każde tłumienie ruff i mypy w plikach ``root``; ``powod`` mówi, czy dyrektywa ruff ma powód na linii."""

    from mypy.util import get_mypy_comments

    znalezione = []
    for nazwa in _pliki(root):
        tekst = (root / nazwa).read_text(encoding="utf-8")
        katalog = _katalog(nazwa)
        linie = tekst.splitlines()
        for token in tokenize.generate_tokens(io.StringIO(tekst).readline):
            if token.type == tokenize.COMMENT:
                for dyrektywa in RUFF.finditer(token.string):
                    powod = dyrektywa.group("powod") or dyrektywa.group("powod_zakresu") or ""
                    miejsce = f"{nazwa}:{token.start[0]}"
                    znalezione.append(Tlumienie(katalog, "noqa", miejsce, token.string, re.search(r"\w", powod) is not None))
        mypy = [numer for numer, _ in get_mypy_comments(tekst)]
        mypy += [ignore.lineno for ignore in ast.parse(tekst, nazwa, type_comments=True).type_ignores]
        znalezione += [Tlumienie(katalog, "type: ignore", f"{nazwa}:{numer}", linie[numer - 1].strip(), True) for numer in mypy]
    return znalezione


def _drzewo(root: Path, pliki: Mapping[str, str]) -> Path:
    """Drzewo z konfiguracją ruff repozytorium i ``pliki``, gotowe dla ``_tlumienia``."""

    root.mkdir()
    (root / "pyproject.toml").write_bytes((ROOT / "pyproject.toml").read_bytes())
    for nazwa, kod in pliki.items():
        (root / nazwa).parent.mkdir(parents=True, exist_ok=True)
        (root / nazwa).write_text(kod, encoding="utf-8")
    return root.resolve()


def _saldo(root: Path) -> Counter[tuple[str, str]]:
    return Counter((tlumienie.katalog, tlumienie.rodzaj) for tlumienie in _tlumienia(root))


@wymaga_ruff_i_mypy
def test_liczba_tlumien_w_kazdym_katalogu_jest_rowna_zapisanej() -> None:
    policzone = _saldo(ROOT)
    rozjazdy = []
    for katalog, rodzaje in ZAPISANE.items():
        for rodzaj, zapisane in rodzaje.items():
            jest = policzone[katalog, rodzaj]
            if jest > zapisane:
                linie = [f"    {t.miejsce}: {t.tekst}" for t in _tlumienia(ROOT) if (t.katalog, t.rodzaj) == (katalog, rodzaj)]
                rozjazdy += [
                    f"{katalog}: {rodzaj} {jest}, a zapisane {zapisane}. Usuń nowe tłumienie albo podnieś liczbę w ZAPISANE"
                    " (tests/test_granice_wyjatkow.py) w tym samym PR, z powodem na linii tłumienia. Tłumienia tego katalogu:",
                    *linie,
                ]
            elif jest < zapisane:
                rozjazdy.append(
                    f"{katalog}: {rodzaj} {jest}, a zapisane {zapisane}. Obniż liczbę w ZAPISANE (tests/test_granice_wyjatkow.py)"
                    f" do {jest}, żeby zapas nie pozwolił dodać tłumienia po cichu."
                )
    assert not rozjazdy, "\n".join(rozjazdy)


@wymaga_ruff_i_mypy
def test_kazde_noqa_ma_powod_na_linii() -> None:
    bez_powodu = [f"{t.miejsce}: {t.tekst}" for t in _tlumienia(ROOT) if t.rodzaj == "noqa" and not t.powod]

    assert not bez_powodu, "\n".join(
        [*bez_powodu, "Dopisz powód po kodach na tej samej linii (# noqa: KOD - powód) albo usuń tłumienie, gdy ruff przechodzi bez niego."]
    )


@wymaga_ruff_i_mypy
def test_licznik_liczy_kazda_postac_tlumienia_ktora_uznaje_ruff_albo_mypy(tmp_path: Path) -> None:
    pliki = {f"src/probka_{numer}.py": kod for numer, (kod, _) in enumerate(PROBKI.values())}
    tlumienia = _tlumienia(_drzewo(tmp_path / "drzewo", pliki))

    policzone = {
        opis: {rodzaj: sum(t.miejsce.startswith(f"{nazwa}:") and t.rodzaj == rodzaj for t in tlumienia) for rodzaj in liczby}
        for nazwa, (opis, (_, liczby)) in zip(pliki, PROBKI.items(), strict=True)
    }
    assert policzone == {opis: liczby for opis, (_, liczby) in PROBKI.items()}
    assert all(t.powod for t in tlumienia if t.rodzaj == "noqa"), tlumienia


@wymaga_ruff_i_mypy
def test_znane_luki_licznika_tlumien_nie_zmieniaja_salda(tmp_path: Path) -> None:
    zgloszenia = {}
    for numer, (opis, (przed, po)) in enumerate(ZNANE_LUKI.items()):
        saldo_przed = _saldo(_drzewo(tmp_path / f"przed_{numer}", przed))
        saldo_po = _saldo(_drzewo(tmp_path / f"po_{numer}", po))
        zgloszenia[opis] = [
            f"licznik {katalog} {rodzaj}: {saldo_przed[katalog, rodzaj]} → {saldo_po[katalog, rodzaj]}"
            for katalog, rodzaj in sorted(saldo_przed | saldo_po)
            if saldo_przed[katalog, rodzaj] != saldo_po[katalog, rodzaj]
        ]

    assert_znane_luki(zgloszenia, "tests/test_granice_wyjatkow.py")
