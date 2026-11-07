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
``PURE_VERSIONS``, więc stopień wersji, los dziennika Wyceny i macierz startu Centrum (``close``) sprawdza test bez
plików i wątków.

Dwa sprawdzenia niżej łapią błąd kodu, który zapomniał strażnika reguły danych albo przerobił gotową wysyłkę Logów
(Logi Urwanego Uruchomienia przed 2ff78b6b3, ``replace`` w przeglądzie #1038). Celowego obejścia nie łapią: to
zostaje przeglądowi.

- Wysyłkę Logów Uruchomienia (``Post`` z etykietą ``logi-uruchomienia``) buduje tylko ``comment_versions.post_of``, a
  jej wynik idzie od razu do kolejki (``<kolejka>.post(post_of(wersja))``), więc nikt go nie zmieni przez
  ``dataclasses.replace``. Nazwę ``post_of`` test rozpoznaje po niej samej, z dowolną bazą i także jako napis, a nie po
  imporcie. Etykietę Logów (``comment_versions.LABEL``) kod poza ``post_of`` tylko podaje kolejce w pytaniu
  ``delivered`` albo ``rejected``, a napis ``logi-uruchomienia`` stoi tylko w ``Literal``.
- Logi i tekst po strażniku (``GuardedLogs``, ``GuardedText``) daje tylko ``guard_logs`` i ``guard_text`` z
  ``run_logs``, inaczej ich typ niczego by nie dowodził. Konstruktor bez dowodu strażnika (``_MINTED``), ``replace``,
  kopię, ``pickle``, zmianę pola, podklasę i wartość innego typu (``Any``) zamyka sam typ albo jego sprawdzenie przy
  uruchomieniu (docstring ``run_logs._MINTED``). Poza ``run_logs`` nazwy tych typów padają tylko w adnotacjach,
  importach i ``isinstance``, a ``_MINTED`` i napis z ich nazwą w żadnej postaci, więc test łapie
  ``object.__new__(GuardedLogs)``, ``object.__setattr__`` slotu i ``cast(GuardedLogs, …)``.

Test czyta AST importów, także względnych, importów w funkcji i pakietów nad modułem. Nowy moduł bez zależności
trafia do ``STDLIB_ONLY`` z powodem. Granica, którą łapie tylko przegląd: nazwa albo napis złożony w trakcie działania
(``importlib``, ``__import__``, ``getattr`` z napisu sklejonego z części), moduł ``comment_versions`` przypisany innej
nazwie poza importem, wysyłka Logów zmieniona w słuchaczu kolejki bez nazwania etykiety (np. po ``run_id``) albo
zbudowana z etykietą wziętą z innej wysyłki (``post.target.label``) oraz celowe obejście strażnika bez nazwy jego typów
(``object.__new__(type(logs))``, zmiana ``__class__``).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
import importlib
from pathlib import Path
import sys
import typing

import pytest

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
        {
            "GuardedLogs",
            "GuardedText",
            "LoggedDiagnosis",
            "LoggedMessage",
            "PricingProgress",
            "RunLog",
            "StartedFacts",
            # strażnik reguły danych: liczy na pamięci ForbiddenValues, bez plików
            "guard_logs",
            "guard_text",
        }
    ),
    # odczyt dysku, który start Centrum podaje macierzy close, jako wartość: typy bez metod, które czytają pliki
    "rozliczenia.centrum.logs_disk": frozenset({"Found", "JournalRead", "LeftJournal", "Missing", "Refused", "Unreadable"}),
    "rozliczenia.client_data": frozenset({"ForbiddenValues"}),
}
RUN_LOGS = "rozliczenia/centrum/run_logs.py"
RUN_LOGS_LABEL = "logi-uruchomienia"
VERSIONS = "rozliczenia.centrum.comment_versions"
# Pytania kolejki, czy wysyłka doszła albo została odrzucona: jedyne, czemu kod poza post_of podaje etykietę Logów.
QUEUE_QUESTIONS = frozenset({"delivered", "rejected"})
# Typy po strażniku reguły danych i ten plik, który je nazywa w swoich regułach.
GUARDED = frozenset({"GuardedLogs", "GuardedText"})
GUARD_CHECK = ROOT / "tests" / "test_granice_importow.py"
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


def _from_module(node: ast.ImportFrom, file: str) -> str:
    """Moduł importu ``from … import`` w pliku ``file`` (``rozliczenia/…``), także względnego."""

    base = node.module or ""
    if not node.level:
        return base
    package = _module_name(file) if file.endswith("__init__.py") else _module_name(file).rpartition(".")[0]
    anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
    return ".".join([*anchor, *([base] if base else [])])


def _imports(file: str) -> Iterator[Import]:
    """Importy pliku z modułami, które wczytują; ``nested`` dla importu w funkcji."""

    tree = ast.parse((SRC / file).read_text(encoding="utf-8"))
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
            base = _from_module(node, file)
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


def _type_nodes(tree: ast.AST) -> set[ast.AST]:
    """Węzły adnotacji (argumentu, wyniku, zmiennej), importów i typu w ``isinstance``: nazwa typu niczego tam nie
    buduje."""

    roots: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            roots.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            roots.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            roots.append(node.annotation)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            roots.append(node)
        elif isinstance(node, ast.Call) and ast.unparse(node.func) == "isinstance" and len(node.args) == 2:
            roots.append(node.args[1])
    return {node for root in roots for node in ast.walk(root)}


def _guard_bypasses(tree: ast.Module) -> list[tuple[int, str]]:
    """Miejsca, z których Logi albo tekst po strażniku mogą powstać albo się zmienić z pominięciem ``guard_logs`` i
    ``guard_text`` drogą, której nie zamyka typ ani jego sprawdzenie przy uruchomieniu (docstring ``run_logs._MINTED``):
    ``_MINTED`` w każdej postaci, także napis; nazwa ``GuardedLogs`` albo ``GuardedText`` (także pod inną nazwą z
    importu i jako atrybut modułu) poza adnotacją, importem i ``isinstance``; napis z tą nazwą (także slot
    ``_GuardedLogs__…``) poza docstringiem. Celowego obejścia bez tych nazw nie łapie (docstring modułu)."""

    names = GUARDED | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in GUARDED and alias.asname
    }
    typed = _type_nodes(tree)
    docstrings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    found = []
    for node in ast.walk(tree):
        if (
            (isinstance(node, ast.Name) and node.id == "_MINTED")
            or (isinstance(node, ast.Attribute) and node.attr == "_MINTED")
            or (isinstance(node, ast.alias) and node.name == "_MINTED")
            or (isinstance(node, ast.Constant) and node.value == "_MINTED")
        ):
            found.append((getattr(node, "lineno", 0), "_MINTED"))
        elif node in typed:
            continue
        elif (isinstance(node, ast.Name) and node.id in names) or (
            isinstance(node, ast.Attribute) and node.attr in GUARDED
        ):
            found.append((node.lineno, ast.unparse(node)))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node not in docstrings
            and any(name in node.value for name in GUARDED)
        ):
            found.append((node.lineno, repr(node.value)))
    return found


def test_logi_i_tekst_po_strazniku_powstaja_tylko_ze_straznika() -> None:
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {code}"
        for path in _python_files()
        if path not in {SRC / RUN_LOGS, GUARD_CHECK}
        for line, code in _guard_bypasses(ast.parse(path.read_text(encoding="utf-8")))
    ]

    assert not found, "\n".join(
        [
            *found,
            f"Logi i tekst po strażniku reguły danych (GuardedLogs, GuardedText) daje tylko guard_logs i guard_text z "
            f"src/{RUN_LOGS}. Poza nim te nazwy padają tylko w adnotacjach, importach i isinstance, a napis z nimi i "
            "dowód strażnika (_MINTED) nigdzie, bo object.__new__, object.__setattr__ i cast typ przepuszcza. Kopia, "
            "replace, zmiana pola, podklasa i wartość innego typu rzucają (docstring _MINTED).",
        ]
    )


# Drogi obok guard_logs i guard_text, których typ nie zamyka (przegląd #1038, rundy 1 i 2, i docstring
# run_logs._MINTED). Podklasę zamyka też __init_subclass__, a cast(Any, …) sprawdzenie przy uruchomieniu (testy w
# tests/test_komentarz_logow_uruchomienia.py).
GUARD_BYPASSES: typing.Final = {
    "nowa-wartosc-bez-konstruktora": "logs = object.__new__(GuardedLogs)",
    "slot-istniejacej-wartosci": 'object.__setattr__(logs, "_GuardedLogs__record", record)',
    "logi-sprzed-straznika-rzutowane": "logs = cast(GuardedLogs, record)",
    "rzutowanie-napisem": 'logs = cast("GuardedLogs", record)',
    "konstruktor-z-modulu": "text = run_logs.GuardedText(text, proof)",
    "nazwa-z-importu-pod-inna-nazwa": (
        "from rozliczenia.centrum.run_logs import GuardedLogs as Logs\nlogs = Logs.__new__(Logs)"
    ),
    "dowod-z-importu": "from rozliczenia.centrum.run_logs import _MINTED",
    "dowod-z-atrybutu-modulu": "proof = run_logs._MINTED",
    "dowod-przez-getattr": 'proof = getattr(run_logs, "_MINTED")',
    "dowod-ze-slownika-modulu": 'proof = vars(run_logs)["_MINTED"]',
    "podklasa": "class Mine(GuardedLogs):\n    pass\n",
    "konstruktor-czesciowy": "make = functools.partial(GuardedLogs)",
    # przegląd #1038, runda 3: isinstance zwalnia tylko typ w drugim argumencie, nie wartość w pierwszym
    "w-isinstance": "ok = isinstance(object.__new__(GuardedLogs), GuardedLogs)",
}


@pytest.mark.parametrize("code", GUARD_BYPASSES.values(), ids=GUARD_BYPASSES.keys())
def test_sprawdzenie_straznika_lapie_kazda_droge_obok_niego_ktorej_typ_nie_zamyka(code: str) -> None:
    assert _guard_bypasses(ast.parse(code))


def test_sprawdzenie_straznika_przepuszcza_typy_po_strazniku_w_adnotacjach_imporcie_isinstance_i_docstringu() -> None:
    code = (
        "from rozliczenia.centrum.run_logs import GuardedLogs, GuardedText\n"
        "def keep(logs: GuardedLogs, text: 'GuardedText | None' = None) -> GuardedLogs:\n"
        '    """Logi po strażniku (``GuardedLogs``) idą dalej bez zmian."""\n'
        "    last: GuardedLogs | None = logs\n"
        "    if not isinstance(logs, GuardedLogs) or not isinstance(text, (GuardedText, type(None))):\n"
        "        raise TypeError\n"
        "    return logs\n"
    )

    assert _guard_bypasses(ast.parse(code)) == []


def _logs_post_breaks(tree: ast.Module, file: str) -> list[tuple[int, str]]:
    """Miejsca pliku ``file``, które mogą zbudować albo przerobić wysyłkę Logów Uruchomienia poza ``post_of``.

    ``post_of`` test rozpoznaje po nazwie, a nie po imporcie: każda nazwa i atrybut ``post_of`` (z dowolną bazą) stoi
    tylko w ``<kolejka>.post(post_of(…))``, więc wynik idzie od razu do kolejki, a nikt go nie zatrzyma, nie zmieni
    (``dataclasses.replace`` na ``Post``) i nie wyśle w innym stopniu. Napis ``"post_of"`` (``getattr``, ``vars``) i
    import ``post_of`` pod inną nazwą to znalezisko.

    Etykietę Logów test rozpoznaje po pochodzeniu, bo ``LABEL`` mają też inne wysyłki (``quantity_check_run.LABEL``):
    import ``LABEL`` z ``comment_versions`` pod dowolną nazwą, także względny, oraz atrybut ``LABEL`` i ``getattr`` z
    napisem ``"LABEL"`` na module ``comment_versions``, czyli na atrybucie ``comment_versions`` (``centrum.…``, pełna
    ścieżka) albo nazwie z importu tego modułu. Tak wybrałem, bo to najprostsza zasada bez fałszywego alarmu: sama
    nazwa ``LABEL`` alarmuje na Kontroli ilości, a sam import (runda 2) przepuszcza atrybut pakietu. Poza
    ``comment_versions`` etykietę kod tylko podaje kolejce w pytaniu, czy wysyłka Logów doszła albo została odrzucona
    (``delivered``, ``rejected``), a w ``comment_versions`` używa jej tylko ``post_of``. Napis ``logi-uruchomienia``
    stoi poza ``comment_versions`` tylko w ``Literal``.
    """

    own = file == COMMENT_VERSIONS
    labels = {"LABEL"} if own else set[str]()
    modules = {"comment_versions"}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _from_module(node, file)
            for alias in node.names:
                if module == VERSIONS and alias.name == "*":
                    found.append((node.lineno, ast.unparse(node)))
                elif module == VERSIONS and alias.name == "LABEL":
                    labels.add(alias.asname or alias.name)
                elif f"{module}.{alias.name}" == VERSIONS:
                    modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            modules |= {alias.asname for alias in node.names if alias.name == VERSIONS and alias.asname}

    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    in_post_of = {
        node
        for function in tree.body
        if own and isinstance(function, ast.FunctionDef) and function.name == "post_of"
        for node in ast.walk(function)
    }
    in_types = {
        node
        for subscript in ast.walk(tree)
        if isinstance(subscript, ast.Subscript) and ast.unparse(subscript.value) in {"Literal", "typing.Literal"}
        for node in ast.walk(subscript)
    }

    def versions_module(node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in modules) or (
            isinstance(node, ast.Attribute) and node.attr == "comment_versions"
        )

    def label(node: ast.AST) -> bool:
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "getattr" and len(node.args) >= 2:
            return versions_module(node.args[0]) and isinstance(node.args[1], ast.Constant) and node.args[1].value == "LABEL"
        return (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in labels) or (
            isinstance(node, ast.Attribute) and node.attr == "LABEL" and versions_module(node.value)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.alias) and node.name == "post_of" and node.asname not in {None, "post_of"}:
            found.append((node.lineno, ast.unparse(node)))
        if not isinstance(node, ast.expr):
            continue
        if label(node):
            if not (node in in_post_of if own else _asks_queue(node, parents)):
                found.append((node.lineno, ast.unparse(node)))
        elif (isinstance(node, ast.Name) and node.id == "post_of") or (
            isinstance(node, ast.Attribute) and node.attr == "post_of"
        ):
            if not _queued_at_once(node, parents):
                found.append((node.lineno, ast.unparse(parents.get(node, node))))
        elif isinstance(node, ast.Constant) and node.value == "post_of":
            found.append((node.lineno, repr(node.value)))
        elif not own and isinstance(node, ast.Constant) and node.value == RUN_LOGS_LABEL and node not in in_types:
            found.append((node.lineno, repr(node.value)))
    return found


def _asks_queue(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """Etykieta jest argumentem pytania kolejki o wysyłkę: ``….delivered(…)`` albo ``….rejected(…)``."""

    call = parents.get(node)
    if isinstance(call, ast.keyword):
        call = parents.get(call)
    return isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr in QUEUE_QUESTIONS


def _queued_at_once(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """``post_of`` wołane i jego wynik jedynym argumentem ``….post(…)`` kolejki."""

    call = parents.get(node)
    queued = parents.get(call) if isinstance(call, ast.Call) and call.func is node else None
    return (
        isinstance(queued, ast.Call)
        and isinstance(queued.func, ast.Attribute)
        and queued.func.attr == "post"
        and queued.args == [call]
        and not queued.keywords
    )


def test_wysylke_logow_uruchomienia_buduje_tylko_post_of() -> None:
    found = [
        f"src/{file}:{line}: {code}"
        for path in sorted((SRC / "rozliczenia").rglob("*.py"))
        for file in [path.relative_to(SRC).as_posix()]
        for line, code in _logs_post_breaks(ast.parse(path.read_text(encoding="utf-8")), file)
    ]

    assert not found, "\n".join(
        [
            *found,
            "Wysyłkę Logów Uruchomienia (etykieta logi-uruchomienia) buduje tylko post_of z wersji komentarza "
            f"(src/{COMMENT_VERSIONS}), która niesie tylko tekst po strażniku i wybiera stopień (rank_of), a jej wynik "
            "idzie od razu do kolejki: outbox.post(post_of(wersja)), bez replace, bez innej nazwy i bez getattr. Etykietę "
            "Logów (comment_versions.LABEL) kod poza post_of tylko podaje kolejce w pytaniu delivered albo rejected.",
        ]
    )


# Wysyłki Logów poza post_of (przegląd #1038: dwie pierwsze to przypadki recenzenta z rundy 1, te z „pakietu” i
# „getattr” z rundy 2).
LOGS_POST_BREAKS: typing.Final = {
    "zastepcza-w-stopniu-logow-z-wynikiem": (
        "from dataclasses import replace\n"
        "from rozliczenia.centrum.comment_versions import OwnLogs, StandInLogs, post_of\n"
        "from rozliczenia.centrum.outbox import Post, Rank\n"
        "def own_from_start(logs):\n"
        "    return replace(post_of(StandInLogs(logs)), rank=Rank.OWN)\n"
    ),
    "komentarz-sprzed-straznika": (
        "from dataclasses import replace\n"
        "from rozliczenia.centrum.comment_versions import OwnLogs, post_of\n"
        "def unguarded(logs, record):\n"
        "    return replace(post_of(OwnLogs(logs)), parts=(record.text + '\\n',))\n"
    ),
    "wysylka-zatrzymana-przed-kolejka": (
        "from rozliczenia.centrum.comment_versions import post_of\n"
        "def send(outbox, version):\n"
        "    post = post_of(version)\n"
        "    outbox.post(post)\n"
    ),
    "wysylka-odlozona-przed-kolejka": (
        "from rozliczenia.centrum.comment_versions import post_of\n"
        "def hold(held, version):\n"
        "    held.append(post_of(version))\n"
    ),
    "post-of-pod-inna-nazwa":"from rozliczenia.centrum import comment_versions as cv\nmake = cv.post_of\n",
    "etykieta-w-nowej-wysylce": (
        "from rozliczenia.centrum.comment_versions import LABEL as RUN_LOGS\n"
        "thread = PeriodThread(label=RUN_LOGS, line='-', closed='reuse', title='t')\n"
    ),
    "etykieta-z-importu-wzglednego": (
        "from . import comment_versions\n"
        "thread = PeriodThread(label=comment_versions.LABEL, line='-', closed='reuse', title='t')\n"
    ),
    "sluchacz-kolejki-zmienia-wysylke-logow": (
        "from dataclasses import replace\n"
        "from rozliczenia.centrum.comment_versions import LABEL\n"
        "def prepare(post, sent):\n"
        "    return replace(post, parts=()) if post.target.label == LABEL else post\n"
    ),
    "etykieta-napisem": "thread = PeriodThread(label='logi-uruchomienia', line='-', closed='reuse', title='t')\n",
    "import-gwiazdki": "from rozliczenia.centrum.comment_versions import *\n",
    "post-of-z-getattr": (
        "from rozliczenia.centrum import comment_versions as cv\n"
        "def send(outbox, version):\n"
        "    make = getattr(cv, 'post_of')\n"
        "    outbox.post(replace(make(version), rank=Rank.OWN))\n"
    ),
    "post-of-ze-slownika-modulu": "def send(outbox, version, cv):\n    outbox.post(vars(cv)['post_of'](version))\n",
    "post-of-atrybutem-pakietu": (
        "from rozliczenia import centrum\n"
        "def send(outbox, version):\n"
        "    outbox.post(replace(centrum.comment_versions.post_of(version), rank=Rank.OWN))\n"
    ),
    "post-of-pelna-sciezka": (
        "import rozliczenia.centrum.comment_versions\n"
        "def send(outbox, version):\n"
        "    outbox.post(replace(rozliczenia.centrum.comment_versions.post_of(version), rank=Rank.OWN))\n"
    ),
    "post-of-z-pakietu-wzglednie": (
        "from .. import centrum\n"
        "def send(outbox, version):\n"
        "    outbox.post(replace(centrum.comment_versions.post_of(version), rank=Rank.OWN))\n"
    ),
    "post-of-z-importu-pod-inna-nazwa": (
        "from rozliczenia.centrum.comment_versions import post_of as make\n"
        "def send(outbox, version):\n"
        "    outbox.post(make(version))\n"
    ),
    "etykieta-atrybutem-pakietu": (
        "from rozliczenia import centrum\n"
        "thread = PeriodThread(label=centrum.comment_versions.LABEL, line='-', closed='reuse', title='t')\n"
    ),
    "etykieta-pelna-sciezka": (
        "import rozliczenia.centrum.comment_versions\n"
        "thread = PeriodThread(label=rozliczenia.centrum.comment_versions.LABEL, line='-', closed='reuse', title='t')\n"
    ),
    "etykieta-z-getattr": (
        "from rozliczenia.centrum import comment_versions as cv\n"
        "thread = PeriodThread(label=getattr(cv, 'LABEL'), line='-', closed='reuse', title='t')\n"
    ),
}


@pytest.mark.parametrize("code", LOGS_POST_BREAKS.values(), ids=LOGS_POST_BREAKS.keys())
def test_sprawdzenie_wysylki_logow_lapie_wysylke_poza_post_of(code: str) -> None:
    assert _logs_post_breaks(ast.parse(code), "rozliczenia/centrum/proba.py")


# Kod, który nie buduje wysyłki Logów (przegląd #1038, runda 1: pierwszy to fałszywy alarm recenzenta).
LOGS_POST_ALLOWED: typing.Final = {
    "etykieta-kontroli-ilosci": (
        "from rozliczenia.centrum import quantity_check_run\n"
        "from rozliczenia.centrum.outbox import PeriodThread\n"
        "def checks_thread(period: str) -> PeriodThread:\n"
        "    return PeriodThread(label=quantity_check_run.LABEL, line=f'- {period}', closed='reuse', title=period)\n"
    ),
    "wersja-od-razu-do-kolejki": (
        "from rozliczenia.centrum.comment_versions import post_of\n"
        "def keep(outbox, version):\n"
        "    return outbox.post(post_of(version))\n"
    ),
    "pytanie-kolejki-o-logi": (
        "from rozliczenia.centrum.comment_versions import LABEL as RUN_LOGS_LABEL\n"
        "def link(sent, run_id):\n"
        "    return sent.delivered(run_id, RUN_LOGS_LABEL) or sent.rejected(run_id, label=RUN_LOGS_LABEL)\n"
    ),
    "etykieta-w-typie": "from typing import Literal\nKind = Literal['logi-uruchomienia', 'kontrola-ilosci']\n",
    "etykieta-kontroli-ilosci-z-getattr": (
        "from rozliczenia.centrum import quantity_check_run\n"
        "thread = PeriodThread(label=getattr(quantity_check_run, 'LABEL'), line='-', closed='reuse', title='t')\n"
    ),
    "wersja-od-razu-do-kolejki-z-pakietu": (
        "from rozliczenia import centrum\n"
        "def keep(self, version):\n"
        "    return self._outbox.post(centrum.comment_versions.post_of(version))\n"
    ),
    "post-of-w-docstringu": 'def keep():\n    """Wysyłka z ``post_of`` idzie od razu do kolejki."""\n',
}


@pytest.mark.parametrize("code", LOGS_POST_ALLOWED.values(), ids=LOGS_POST_ALLOWED.keys())
def test_sprawdzenie_wysylki_logow_przepuszcza_kod_bez_wysylki_logow(code: str) -> None:
    assert _logs_post_breaks(ast.parse(code), "rozliczenia/centrum/proba.py") == []
