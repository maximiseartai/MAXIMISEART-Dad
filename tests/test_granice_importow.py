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

Wersje komentarza Uruchomienia (``centrum/comment_versions.py``) nie robią I/O: biorą tylko typy i reguły z listy
``PURE_VERSIONS``, więc stopień wersji i los dziennika Wyceny sprawdza test bez plików i wątków. Wysyłkę Logów
Uruchomienia (``Post`` z etykietą ``logi-uruchomienia``) buduje tylko ``comment_versions.post_of``, a samą etykietę
poza typem ``report_box.Label`` zna tylko ``comment_versions.LABEL``; dowód strażnika
reguły danych (``_MINTED``) zna tylko ``run_logs``: inaczej typ Logów po strażniku (``GuardedLogs``) niczego by nie
dowodził, bo dało się go zbudować bez strażnika.

Test czyta AST importów, także względnych, importów w funkcji i pakietów nad modułem. Nowy moduł bez zależności
trafia do ``STDLIB_ONLY`` z powodem. Granica: import przez ``importlib`` albo ``__import__`` z napisu łapie tylko
przegląd, a ``_MINTED`` wzięty przez ``getattr`` z napisu i ``LABEL`` przypisany innej nazwie przed ``Post`` też.
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
# Wersje komentarza Uruchomienia i jedyne, co biorą przy wczytaniu spoza biblioteki standardowej bez I/O: nazwy z modułu.
COMMENT_VERSIONS = "rozliczenia/centrum/comment_versions.py"
PURE_STDLIB = frozenset({"__future__", "collections", "collections.abc", "dataclasses", "typing"})
PURE_VERSIONS = {
    "rozliczenia.centrum": frozenset({"contract"}),
    "rozliczenia.centrum.catalog": frozenset({"declaration_of"}),
    "rozliczenia.centrum.outbox": frozenset({"ArchiveFile", "PeriodThread", "Post", "Rank"}),
    "rozliczenia.centrum.report_box": frozenset({"Label"}),
    "rozliczenia.centrum.version": frozenset({"short_commit"}),
    "rozliczenia.centrum.run_logs": frozenset(
        {"GuardedLogs", "GuardedText", "LoggedDiagnosis", "LoggedMessage", "PricingProgress", "RunLog", "StartedFacts"}
    ),
}
RUN_LOGS = "rozliczenia/centrum/run_logs.py"
RUN_LOGS_LABEL = "logi-uruchomienia"
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


def test_wersje_komentarza_uruchomienia_nie_robia_io_i_biora_tylko_nazwy_z_listy() -> None:
    tree = ast.parse((SRC / COMMENT_VERSIONS).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [ast.unparse(node) for alias in node.names if alias.name not in PURE_STDLIB]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                found.append(ast.unparse(node))
            elif module in PURE_VERSIONS:
                found += [f"{module}.{alias.name}" for alias in node.names if alias.name not in PURE_VERSIONS[module]]
            elif module not in PURE_STDLIB:
                found.append(ast.unparse(node))

    assert not found, "\n".join(
        [
            *sorted(found),
            f"Wersje komentarza Uruchomienia (src/{COMMENT_VERSIONS}) nie robią I/O i biorą spoza biblioteki standardowej "
            "tylko nazwy z PURE_VERSIONS (tests/test_granice_importow.py). Plik, kolejkę i zegar zostaw powłoce, która "
            "woła ten moduł.",
        ]
    )


def _python_files() -> Iterator[Path]:
    for folder in (SRC, ROOT / "tools", ROOT / "tests", ROOT / ".agents" / "skills"):
        yield from sorted(folder.rglob("*.py"))


def test_dowod_straznika_logow_zna_tylko_run_logs() -> None:
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno}"
        for path in _python_files()
        if path != SRC / RUN_LOGS
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (isinstance(node, ast.Name) and node.id == "_MINTED")
        or (isinstance(node, ast.Attribute) and node.attr == "_MINTED")
        or (isinstance(node, ast.alias) and node.name == "_MINTED")
    ]

    assert not found, "\n".join(
        [
            *found,
            f"Dowód strażnika reguły danych (_MINTED) zna tylko src/{RUN_LOGS}: Logi i tekst po strażniku (GuardedLogs, "
            "GuardedText) daje tylko guard_logs i guard_text.",
        ]
    )


def _run_logs_label_names(tree: ast.Module) -> set[str]:
    """Nazwy, pod którymi moduł zna etykietę Logów Uruchomienia (``comment_versions.LABEL``)."""

    return {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "rozliczenia.centrum.comment_versions"
        for alias in node.names
        if alias.name == "LABEL"
    }


def test_wysylke_logow_uruchomienia_buduje_tylko_post_of() -> None:
    found = []
    for path in sorted((SRC / "rozliczenia").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        file = path.relative_to(SRC).as_posix()
        names = {"LABEL"} if file == COMMENT_VERSIONS else _run_logs_label_names(tree)
        if file != COMMENT_VERSIONS:
            in_types = {
                node
                for subscript in ast.walk(tree)
                if isinstance(subscript, ast.Subscript) and ast.unparse(subscript.value) in {"Literal", "typing.Literal"}
                for node in ast.walk(subscript)
            }
            found += [
                f"src/{file}:{node.lineno}: {RUN_LOGS_LABEL!r}"
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and node.value == RUN_LOGS_LABEL and node not in in_types
            ]
        allowed = {
            node
            for function in tree.body
            if file == COMMENT_VERSIONS and isinstance(function, ast.FunctionDef) and function.name == "post_of"
            for node in ast.walk(function)
        }
        for call in ast.walk(tree):
            if call in allowed or not isinstance(call, ast.Call):
                continue
            called = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", "")
            if called not in {"Post", "PeriodThread"}:
                continue
            if any(
                (isinstance(node, ast.Name) and node.id in names)
                or (isinstance(node, ast.Attribute) and node.attr == "LABEL")
                or (isinstance(node, ast.Constant) and node.value == RUN_LOGS_LABEL)
                for node in ast.walk(call)
            ):
                found.append(f"src/{file}:{call.lineno}: {called}(…)")

    assert not found, "\n".join(
        [
            *found,
            "Wysyłkę Logów Uruchomienia (etykieta logi-uruchomienia) buduje tylko post_of z wersji komentarza "
            f"(src/{COMMENT_VERSIONS}), która niesie tylko tekst po strażniku i wybiera stopień (rank_of), a etykietę "
            "zna tylko comment_versions.LABEL.",
        ]
    )
