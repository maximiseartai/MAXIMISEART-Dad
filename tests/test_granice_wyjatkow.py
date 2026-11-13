"""Szeroki ``except`` w Centrum rozliczeń przekazuje złapany wyjątek do dziennika Centrum albo rzuca go dalej.

Ruff BLE001 uznaje za wpis do dziennika tylko ``logging``, a Centrum ma własny dziennik, więc ``pyproject.toml``
wyłącza BLE001 dla ``src/rozliczenia/centrum``, a tę samą regułę z dziennikiem Centrum sprawdza ten test.
``except Exception``, ``except BaseException`` i gołe ``except`` przechodzą, gdy blok woła ``unexpected_failure``
ze złapanym wyjątkiem albo go rzuca. Gołe ``raise`` w zagnieżdżonym ``except`` rzuca wyjątek wewnętrzny, więc się nie
liczy. Blok, który kończy się czym innym, ma wpis w ``OTHER_ENDINGS`` z powodem.
``contextlib.suppress(Exception)`` i typ wyjątku pod inną nazwą są poza testem, tak jak były poza BLE001.

Tłumienie reguły (najczęściej BLE001) ma powód na linii, a liczba tłumień ruff i mypy w każdym katalogu stoi w
``ZAPISANE`` (ADR 0034), więc każde nowe tłumienie widać w diffie. Test czyta pliki, które sprawdza ruff (``include``
z ``[tool.ruff]`` w ``pyproject.toml``, śledzone i nieśledzone nieignorowane), i liczy tokeny, które narzędzia same
uznają za tłumienie, nie postacie kodu:

- ``noqa``: komentarz (``tokenize``) z dyrektywą ruff ``# noqa`` także po innym tekście komentarza, plikową
  ``# ruff: noqa`` albo ``# flake8: noqa`` i zakresową ``# ruff: disable[...]``;
- ``type: ignore``: ``type_ignores`` parsera Pythona, z którego bierze je mypy, i konfiguracja w linii ``# mypy:``.

Napis „noqa” w docstringu albo w napisie nie jest komentarzem, więc się nie liczy. Czy tłumienie jest zasadne, ocenia
przegląd. Granica: zwolnienie w konfiguracji (``per-file-ignores`` ruff, ``overrides`` mypy) nie stoi na linii kodu,
więc test go nie liczy; widać je w diffie pliku konfiguracji.
"""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Iterator
import functools
import io
from pathlib import Path
import re
import tokenize
import tomllib

from tests.fixtures.git_repo import git

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
    "tools": {"noqa": 22, "type: ignore": 6},
}

_KODY = r"[A-Z]+[0-9]+(?:[\s,]+[A-Z]+[0-9]+)*"
RUFF = re.compile(
    rf"#\s*(?:(?:ruff|flake8)\s*:\s*)?noqa\b(?:\s*:\s*{_KODY})?(?P<powod>[^#]*)"
    rf"|#\s*ruff\s*:\s*disable\[[^\]]*\](?P<powod_zakresu>[^#]*)",
    re.IGNORECASE,
)


def _katalog(sciezka: str) -> str:
    return next((katalog for katalog in ZAPISANE if katalog != "." and sciezka.startswith(f"{katalog}/")), ".")


def _pliki() -> list[str]:
    include = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]["include"]
    wzorce = [f":(glob){wzorzec.removeprefix('/')}" for wzorzec in include]
    return sorted(set(filter(None, git(ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *wzorce).split("\0"))))


@functools.cache
def _tlumienia() -> list[tuple[str, str, str, str, bool]]:
    """Każde tłumienie: katalog, rodzaj, linia ``plik:numer``, tekst komentarza i czy tłumienie ruff ma powód."""

    znalezione = []
    for nazwa in _pliki():
        tekst = (ROOT / nazwa).read_text(encoding="utf-8")
        katalog = _katalog(nazwa)
        for token in tokenize.generate_tokens(io.StringIO(tekst).readline):
            if token.type != tokenize.COMMENT:
                continue
            miejsce = f"{nazwa}:{token.start[0]}"
            for dyrektywa in RUFF.finditer(token.string):
                powod = dyrektywa.group("powod") or dyrektywa.group("powod_zakresu") or ""
                znalezione.append((katalog, "noqa", miejsce, token.string, re.search(r"\w", powod) is not None))
            if token.start[1] == 0 and token.string.startswith("# mypy:"):
                znalezione.append((katalog, "type: ignore", miejsce, token.string, True))
        linie = tekst.splitlines()
        for ignore in ast.parse(tekst, nazwa, type_comments=True).type_ignores:
            znalezione.append((katalog, "type: ignore", f"{nazwa}:{ignore.lineno}", linie[ignore.lineno - 1].strip(), True))
    return znalezione


def test_liczba_tlumien_w_kazdym_katalogu_jest_rowna_zapisanej() -> None:
    tlumienia = _tlumienia()
    policzone = Counter((katalog, rodzaj) for katalog, rodzaj, *_ in tlumienia)
    rozjazdy = []
    for katalog, rodzaje in ZAPISANE.items():
        for rodzaj, zapisane in rodzaje.items():
            jest = policzone[katalog, rodzaj]
            if jest > zapisane:
                linie = [f"    {miejsce}: {komentarz}" for k, r, miejsce, komentarz, _ in tlumienia if (k, r) == (katalog, rodzaj)]
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


def test_kazde_noqa_ma_powod_na_linii() -> None:
    bez_powodu = [f"{miejsce}: {komentarz}" for _, rodzaj, miejsce, komentarz, powod in _tlumienia() if rodzaj == "noqa" and not powod]

    assert not bez_powodu, "\n".join(
        [*bez_powodu, "Dopisz powód po kodach na tej samej linii (# noqa: KOD - powód) albo usuń tłumienie, gdy ruff przechodzi bez niego."]
    )
