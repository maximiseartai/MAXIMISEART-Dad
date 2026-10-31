"""Wpływ zmiany: ścieżki, którymi checkout różni się od bazy, zmiany, które uruchamiają wszystko, i testy, których dotyczą.

Jedyne miejsce, które odpowiada na pytanie „czego dotyka ta zmiana”; pytają o to ``tools/szybko.py``, plan CI
(``tools/plan_ci.py``), mutacje zmian (``tools/mutacje_zmiany.py``), zakres runu CI (``tools/lib/zakres_runu.py``)
i ``tools/skille_dla_zmiany.py``:

    changed = changed_since(root, "origin/main")    # merge-base, diff --no-renames, nieśledzone
    full = run_all(changed, Context.PR_GATE)         # posortowane ścieżki, przez które biegnie wszystko
    repository = Repository.scan(root)               # pliki checkoutu; graf liczy się raz, przy pierwszym pytaniu
    impact = repository.impact(changed)              # testy dotknięte zmianą, odległości, odcisk testu
    repository.reaching("tools/mutacje.py")          # pliki testów, które sięgają pliku

Zmiana to ścieżki, którymi checkout, razem z niezacommitowanymi i nieśledzonymi plikami, różni się od ``merge-base``
HEAD z bazą; przeniesienie daje starą i nową ścieżkę, a usunięty plik też jest zmianą.

Test jest dotknięty, gdy zmiana obejmuje jego plik albo plik, od którego zależy. Zależności wynikają z samego
kodu, więc świeży worktree wybiera tak samo:

- importy modułów Pythona;
- w ``tests/`` ścieżki i nazwy modułów w napisach, czyli skrypt, który test uruchamia, plik, który czyta, albo
  pliki katalogu; poza ``tests/`` tylko ścieżki z ``/``, i bez zależności dalej;
- pliki z globu (``glob``, ``rglob``, ``iterdir``) na katalogu o znanej nazwie;
- pliki inne niż Python w katalogu pakietu (``centrum/static``) dla każdego modułu tego pakietu.

Zależność przez import i skrypt testu jest przechodnia, a przez katalog, glob i plik danych nie. Odległość pliku to
najmniejsza liczba krawędzi do zmiany: zmieniony plik ma 0, a plik, który czyta zmieniony plik z katalogu, globu albo
danych pakietu, 1.

Zmiana, która w danym kontekście (``Context``) uruchamia wszystko, to wiersz jednej tabeli reguł: ścieżka albo katalog
(z ``/`` na końcu) i konteksty, w których działa. W wyborze testów (``Context.TESTS``) zmiana takiego pliku wybiera
wszystkie testy, odległość liczy się bez niego, a plik, który go importuje albo nazywa, ma najwyżej 2, więc w budżecie
szybko biegnie przed testami bez drogi w grafie; każdy taki plik wchodzi też do odcisku każdego testu. Testy
``STRUCTURE`` graf nie wiąże ze zmianą, więc biegną przy każdej.

Testy, które sięgają pliku (``Repository.reaching``), to inna reguła niż wybór: krawędź katalogu, globu i danych
pakietu prowadzi dalej tylko ze źródeł w ``tests/``, a ścieżka nazwana tylko w narzędziu się nie liczy.

Moduł używa tylko biblioteki standardowej i ``sciezki_w_kodzie``, bo plan CI biegnie systemowym ``python3`` runnera.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
import enum
from functools import cached_property
import hashlib
from pathlib import Path, PurePosixPath
import subprocess
import sys

from sciezki_w_kodzie import Glob, references

__all__ = ["STRUCTURE", "Context", "Impact", "Repository", "changed_since", "run_all", "with_structure"]


class Context(enum.Enum):
    """Kto pyta, czy zmiana uruchamia wszystko; skutek zna pytający, a ścieżki daje tabela reguł."""

    TESTS = "wybór testów"  # tools/szybko.py i mutacje zmian; plik reguły wchodzi do odcisku każdego testu
    PR_GATE = "bramka PR"  # pytest bramki PR w tools/plan_ci.py: wszystkie pliki, E2E i straż czasu (ADR 0020)
    SKILL_STEPS = "kroki skilli"  # tools/lib/zakres_runu.py: każdy krok skilla swojego rodzaju

    def paths(self) -> tuple[str, ...]:
        """Ścieżki reguł kontekstu w kolejności tabeli (katalog kończy ``/``), np. jako pathspec gita."""

        return tuple(rule.path for rule in _RUN_ALL if self in rule.contexts)


@dataclass(frozen=True)
class _Rule:
    """Wiersz tabeli: ``path`` to plik albo katalog zakończony ``/`` (każdy plik pod nim)."""

    path: str
    contexts: frozenset[Context]

    def __post_init__(self) -> None:
        # Bramka PR to wybór testów bez budżetu (ADR 0020), a plik wyboru testów wchodzi do odcisku każdego testu.
        if Context.TESTS in self.contexts and (Context.PR_GATE not in self.contexts or self.path.endswith("/")):
            raise ValueError(f"reguła {self.path} wyboru testów musi być plikiem i działać też w bramce PR")

    def matches(self, path: str) -> bool:
        return path == self.path or (self.path.endswith("/") and path.startswith(self.path))


_TESTS, _GATE, _SKILLS = Context.TESTS, Context.PR_GATE, Context.SKILL_STEPS
# Zmiana członka tabeli zmienia, co biegnie na pull request, więc według ADR 0020 wymaga dowodu z backtestu.
_RUN_ALL = (
    # Konfiguracja pytest i narzędzi (#305).
    _Rule("pyproject.toml", frozenset({_TESTS, _GATE})),
    # Biblioteki testów (#305) i zadania mutacji skilli, które instaluje tylko je (#293).
    _Rule("requirements.txt", frozenset({_TESTS, _GATE, _SKILLS})),
    # conftest każdego testu (#305) i fixture gita, którą wczytuje dla całej sesji (#360).
    _Rule("tests/conftest.py", frozenset({_TESTS, _GATE})),
    _Rule("tests/fixtures/git_config.py", frozenset({_TESTS, _GATE})),
    # Zadania CI (ADR 0020); lokalnie zmiana workflow wybiera testy z grafu (test_zadania_ci czyta ci.yml).
    _Rule(".github/workflows/", frozenset({_GATE})),
    # Zadanie CI mutacji skilli i końce linii kopii, na których biegną jego kroki (#293).
    _Rule(".github/workflows/ci.yml", frozenset({_SKILLS})),
    _Rule(".gitattributes", frozenset({_SKILLS})),
)
# Testy i węzły ``plik::test``, które biegną przy każdej zmianie: reguły z tabel w ``AGENTS.md``,
# ``CODING_STANDARDS.md`` i ``docs/agents/`` oraz testy całego repozytorium, których graf nie wiąże ze zmianą.
STRUCTURE = (
    "tests/test_adr.py",
    "tests/test_decyzje_na_faktach.py",
    "tests/test_dokumenty_regul.py",
    "tests/test_granice_importow.py",
    "tests/test_granice_wyjatkow.py",
    "tests/test_jeden_odczyt_skoroszytu.py",
    "tests/test_jeden_zapis_skoroszytu.py",
    "tests/test_kwarantanna.py",
    "tests/test_mapy_funkcji.py",
    "tests/test_miejsce_skilli.py",
    "tests/test_potomne.py::test_drzewa_procesow_i_kopie_commitow_narzedzi_buduje_tylko_potomne",
    "tests/test_potomne.py::test_polecenia_narzedzi_ktore_trwaja_biegna_przez_potomne_run",
    "tests/test_skille_dla_zmiany.py::test_agents_md_nie_wymienia_skilli_verify",
    "tests/test_skille_dla_zmiany.py::test_kazdy_skill_verify_deklaruje_pilnuje",
    "tests/test_skille_dla_zmiany.py::test_skill_nie_kaze_uruchamiac_przed_pushem_tego_co_liczy_ci",
    "tests/test_skille_dla_zmiany.py::test_skill_z_poleceniami_w_ci_mowi_co_liczy_ci_a_co_zostaje_lokalnie",
    "tests/test_skrypty_bez_instalacji.py",
    "tests/test_slowo_flaky_test.py",
    "tests/test_spis_narzedzi.py",
    "tests/test_struktura_testow.py",
    "tests/test_systemowy_python.py",
    "tests/test_uszkodzone_wejscia.py::test_macierz_obejmuje_kazda_operacje_kontraktu_centrum",
    "tests/test_wycofane_pojecia.py",
    "tests/test_wywolanie_skryptow_skilli.py::test_skrypty_skilli_biora_katalog_runu_warianty_i_sciezki_tylko_z_parsera",
    # Globy ``pilnuje:`` z frontmatteru SKILL.md obejmują całe repozytorium, a graf ich nie widzi.
    "tests/test_mutacje_skilli.py::test_kazdy_glob_pilnuje_trafia_w_plik_repozytorium",
    "tests/test_mutacje_skilli.py::test_kazdy_modul_silnika_jest_w_pilnuje_verify_rozliczenia_albo_na_liscie_wylaczen",
    # Kotwice mutacji skilli leżą w plikach całego repozytorium, a skrypty mutacji na pull request nie biegną.
    "tests/test_mutacje_skilli.py::test_kotwica_kazdej_mutacji_skilla_trafia_w_swoj_plik_dokladnie_raz",
    "tests/test_skille_dla_zmiany.py::test_frontmatter_kazdego_skilla_jest_poprawnym_yaml",
    "tests/test_skille_dla_zmiany.py::test_workflow_skilla_windows_biegnie_dla_tych_samych_sciezek_co_jego_pilnuje",
    # Plan bramki liczy graf zależności całego repozytorium, więc test, który zaczyna zależeć od wszystkiego, rośnie
    # bramkę bez zmiany kodu CI.
    "tests/test_ksztalt_bramki.py",
    # ``.gitignore`` czyta tu ``git check-ignore``, nie Python, więc graf nie wiąże go z tym testem.
    "tests/test_centrum_rozliczen.py::test_lokalne_pliki_taty_sa_poza_gitem",
)
_MODULE_ROOTS = ("src", ".", "tools", "tools/lib", "tools/ci")
_SKILL_SCRIPTS = ".agents/skills/*/scripts"


def changed_since(root: Path, base: str) -> frozenset[str]:
    """Ścieżki, którymi checkout ``root`` (z niezacommitowanymi i nieśledzonymi plikami) różni się od ``merge-base``
    HEAD z ``base``. Nieznana baza: ``subprocess.CalledProcessError`` gita (``cmd[1]`` to ``merge-base``, ``stderr``
    to tekst błędu)."""

    fork = _git(root, "merge-base", "HEAD", base).strip()
    diff = _git(root, "diff", "-z", "--name-only", "--no-renames", fork)
    untracked = _git(root, "ls-files", "-z", "--others", "--exclude-standard")
    return frozenset(path for path in (diff + untracked).split("\0") if path)


def run_all(changed: Iterable[str], context: Context) -> tuple[str, ...]:
    """Posortowane ścieżki ``changed``, przez które w ``context`` biegnie wszystko; pusta krotka, gdy żadnej nie ma."""

    rules = [rule for rule in _RUN_ALL if context in rule.contexts]
    return tuple(sorted(path for path in set(changed) if any(rule.matches(path) for rule in rules)))


def with_structure(tests: Iterable[str]) -> tuple[str, ...]:
    """Posortowane ``tests``, a za nimi ``STRUCTURE`` w jego kolejności bez węzłów ``plik::test``, których plik już jest
    w ``tests``: wybrany plik biegnie raz, cały."""

    chosen = sorted(tests)
    return (*chosen, *(node for node in STRUCTURE if node.partition("::")[0] not in chosen))


@dataclass(frozen=True)
class Impact:
    """Wpływ jednego zbioru zmian w wyborze testów (``Context.TESTS``).

    ``tests``: posortowane pliki testów dotknięte zmianą, a gdy zmiana ma plik reguły wyboru testów, każdy istniejący
    plik testów. ``distances``: plik (także nie test) → odległość od zmiany; kolejność kluczy nie jest kontraktem.
    """

    tests: tuple[str, ...]
    distances: dict[str, int]
    _root: Path = field(repr=False)
    _graph: _Graph = field(repr=False, compare=False)

    def fingerprint(self, test: str) -> str:
        """sha256 wersji Pythona i treści wejść testu (w grafie tej zmiany) oraz plików reguł wyboru testów; brak
        pliku to ``brak pliku``. Zmiana pliku reguły unieważnia odcisk każdego testu."""

        digest = hashlib.sha256(sys.version.encode())
        for path in sorted({*self._graph.inputs_of(test), *Context.TESTS.paths()}):
            try:
                content = (self._root / path).read_bytes()
            except OSError:
                content = b"brak pliku"
            digest.update(f"{path}\0{len(content)}\0".encode() + content)
        return digest.hexdigest()


@dataclass(frozen=True)
class Repository:
    """Pliki checkoutu ``root`` (``git ls-files`` śledzone i nieśledzone nieignorowane) i ich graf zależności: graf
    liczy się raz na zbiór plików, więc jedno repozytorium odpowiada na pytania o wiele zbiorów zmian."""

    root: Path
    _files: frozenset[str] = field(repr=False)
    _graphs: dict[frozenset[str], _Graph] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def scan(cls, root: Path) -> Repository:
        listed = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root, capture_output=True, check=True
        ).stdout.decode("utf-8")
        return cls(root, frozenset(path for path in listed.split("\0") if path))

    def impact(self, changed: frozenset[str]) -> Impact:
        """Wpływ ``changed`` (ścieżki względem ``root``). Usunięte ścieżki zmiany wchodzą do zbioru plików grafu, więc
        test, który importuje usunięty moduł, jest dotknięty, a usunięty plik testu nie jest."""

        graph = self._graph(changed - self._files)
        full = run_all(changed, Context.TESTS)
        # Plik reguły dotyczy każdego testu, a drogę w grafie mają do niego tylko testy, które wymieniają jego nazwę.
        distances = graph.distances_from(changed - set(full))
        readers = {source for source, targets in graph.depends_on.items() if targets & set(full)}
        distances |= {reader: min(distances.get(reader, 2), 2) for reader in readers}
        tests = {path for path in graph.files if _is_test(path) and (self.root / path).is_file()}
        if not full:
            tests &= distances.keys()
        return Impact(tuple(sorted(tests)), distances, self.root, graph)

    def reaching(self, path: str) -> frozenset[str]:
        """Pliki testów, które dochodzą do ``path`` importem albo nazwą pliku, katalogu lub globu w teście albo fixture.

        Tylko taki test uruchamia proces z kodem pliku, którego zapis pokrycia nie widzi (``-I``, kopia narzędzia).
        Plik nazwany tylko w innym narzędziu się nie liczy: ``tests/fixtures/git_repo.py`` kopiuje narzędzia, które
        nazywają inne narzędzia, więc inaczej każdy test z repozytorium Gita sięgałby każdego z nich (#510).
        """

        return self._runners.get(path, frozenset())

    @cached_property
    def _runners(self) -> dict[str, frozenset[str]]:
        graph = self._graph(frozenset())
        found: dict[str, set[str]] = defaultdict(set)
        for test in sorted(path for path in graph.depends_on if _is_test(path)):
            reached, pending = {test}, [test]
            while pending:
                source = pending.pop()
                named = graph.folder_files.get(source, set()) if source.startswith("tests/") else set()
                for target in (graph.depends_on.get(source, set()) | named) - reached:
                    reached.add(target)
                    pending.append(target)
            for path in reached:
                found[path].add(test)
        return {path: frozenset(tests) for path, tests in found.items()}

    def _graph(self, extra: frozenset[str]) -> _Graph:
        if extra not in self._graphs:
            self._graphs[extra] = _Graph.of(self.root, self._files | extra)
        return self._graphs[extra]


@dataclass(frozen=True)
class _Graph:
    """``depends_on`` jest przechodnie (import, skrypt testu), a ``folder_files`` to jeden krok (katalog, glob, dane
    pakietu, ścieżka w narzędziu)."""

    files: frozenset[str]
    depends_on: dict[str, set[str]]
    folder_files: dict[str, set[str]]

    @classmethod
    def of(cls, root: Path, files: frozenset[str]) -> _Graph:
        modules = _modules(files)
        directories = {str(parent) for path in files for parent in PurePosixPath(path).parents if str(parent) != "."}
        in_folder: dict[str, set[str]] = defaultdict(set)
        for file in files:
            in_folder[str(PurePosixPath(file).parent)].add(file)
        package_data = _package_data(files)
        depends_on: dict[str, set[str]] = defaultdict(set)
        folder_files: dict[str, set[str]] = defaultdict(set)
        for path in sorted(files):
            if not _is_python(root, path):
                continue
            try:
                tree = ast.parse((root / path).read_bytes())
            except (OSError, SyntaxError, ValueError):
                continue
            nodes = list(ast.walk(tree))
            for name in _imports(nodes, path):
                depends_on[path] |= _resolve(name, path, modules, files)
            texts, globs = references(nodes)
            test = path.startswith("tests/")
            if not test:
                # Poza testami sama nazwa pliku albo modułu to zwykle nazwa procesu albo pliku w cudzym katalogu.
                texts = {text for text in texts if "/" in text.strip("/")}
            for text in texts:
                if text in modules and test:
                    depends_on[path] |= _resolve(text, path, modules, files)
                # Skrypt, który uruchamia test, zależy dalej od swoich importów; plik wskazany przez narzędzie już nie,
                # a katalog w narzędziu to zwykle lista miejsc do sprawdzenia (``GENERATED``), nie plik, który czyta.
                (depends_on if test else folder_files)[path] |= _files_named(text, files)
                if test:
                    folder_files[path] |= _folder_files(text, in_folder)
            for glob in globs:
                folder_files[path] |= _globbed(glob, files, directories)
            folder_files[path] |= package_data.get(str(PurePosixPath(path).parent), set())
            depends_on[path] |= _packages(path, files)
            depends_on[path].discard(path)
        return cls(files, depends_on, folder_files)

    def inputs_of(self, test: str) -> set[str]:
        found, pending = {test}, [test]
        while pending:
            for target in self.depends_on.get(pending.pop(), set()) - found:
                found.add(target)
                pending.append(target)
        return found | {path for source in found for path in self.folder_files.get(source, set())}

    def distances_from(self, changed: Iterable[str]) -> dict[str, int]:
        back: dict[str, set[str]] = defaultdict(set)
        for source, targets in self.depends_on.items():
            for target in targets:
                back[target].add(source)
        changed = set(changed)
        distances = dict.fromkeys(sorted(changed), 0)
        readers = sorted(source for source, folder in self.folder_files.items() if folder & changed)
        distances |= {reader: 1 for reader in readers if reader not in changed}
        pending = deque(distances)
        while pending:
            target = pending.popleft()
            for source in sorted(back[target] - distances.keys()):
                distances[source] = distances[target] + 1
                pending.append(source)
        return distances


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, encoding="utf-8", check=True)
    return completed.stdout


def _is_python(root: Path, path: str) -> bool:
    if path.endswith(".py"):
        return True
    if PurePosixPath(path).suffix:
        return False
    try:
        with (root / path).open("rb") as file:
            first = file.readline()
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def _module_roots(files: frozenset[str]) -> list[str]:
    skills = {"/".join(PurePosixPath(path).parts[:4]) for path in files if PurePosixPath(path).match(f"{_SKILL_SCRIPTS}/**")}
    return [*_MODULE_ROOTS, *sorted(skills)]


def _modules(files: frozenset[str]) -> dict[str, set[str]]:
    modules: dict[str, set[str]] = defaultdict(set)
    roots = _module_roots(files)
    for path in files:
        if not path.endswith(".py"):
            continue
        parts = PurePosixPath(path).with_suffix("").parts
        for root in roots:
            depth = 0 if root == "." else len(PurePosixPath(root).parts)
            if depth and PurePosixPath(*parts[:depth]) != PurePosixPath(root):
                continue
            names = parts[depth:]
            if names and names[-1] == "__init__":
                names = names[:-1]
            if names:
                modules[".".join(names)].add(path)
    return modules


def _imports(nodes: Iterable[ast.AST], path: str) -> set[str]:
    package = PurePosixPath(path).parent.parts
    names: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            if node.level:
                prefix = ".".join([*package[: len(package) - node.level + 1], *filter(None, [node.module])])
            names.add(prefix)
            names.update(f"{prefix}.{alias.name}" for alias in node.names)
    return {".".join(name.split(".")[:end]) for name in names for end in range(1, name.count(".") + 2)}


def _resolve(name: str, importer: str, modules: Mapping[str, set[str]], files: frozenset[str]) -> set[str]:
    """Moduł obok importującego (skrypt z własnym katalogiem na ``sys.path``) wygrywa z modułem z ``_modules``."""

    here = PurePosixPath(importer).parent / name.replace(".", "/")
    local = {str(candidate) for candidate in (here.with_suffix(".py"), here / "__init__.py") if str(candidate) in files}
    return local or modules.get(name, set())


def _packages(path: str, files: frozenset[str]) -> set[str]:
    parents = PurePosixPath(path).parents
    return {init for parent in parents if (init := str(parent / "__init__.py")) in files}


def _as_path(text: str) -> str | None:
    path = text.strip().replace("\\", "/").strip("/")
    if ("/" in path or "." in path) and path.strip(".") and not any(c.isspace() for c in path):
        return path
    return None


def _files_named(text: str, files: frozenset[str]) -> set[str]:
    if (path := _as_path(text)) is None:
        return set()
    return {file for file in files if file == path or file.endswith("/" + path)}


def _folder_files(text: str, in_folder: Mapping[str, set[str]]) -> set[str]:
    """Pliki leżące wprost w katalogu ``text`` (``in_folder``: katalog → jego pliki)."""

    if (path := _as_path(text)) is None or "/" not in path:
        return set()
    found = {file for folder, inside in in_folder.items() if folder == path or folder.endswith("/" + path) for file in inside}
    # Pakiet test zna przez importy; jego katalog w napisie to ścieżka w repozytorium, które test sam buduje.
    return set() if any(PurePosixPath(file).name == "__init__.py" for file in found) else found


def _globbed(glob: Glob, files: frozenset[str], directories: set[str]) -> set[str]:
    folders = {folder for folder in directories if folder == glob.folder or folder.endswith("/" + glob.folder)}
    depth = len(PurePosixPath(glob.pattern).parts)
    found = set()
    for file in files:
        for folder in folders:
            if file.startswith(folder + "/"):
                inside = PurePosixPath(file[len(folder) + 1 :])
                if inside.match(glob.pattern) and (glob.recursive or "**" in glob.pattern or len(inside.parts) == depth):
                    found.add(file)
    return found


def _package_data(files: frozenset[str]) -> dict[str, set[str]]:
    """Katalog pakietu → jego pliki inne niż Python, także z podkatalogów, które nie są pakietami (``centrum/static``)."""

    packages = {str(PurePosixPath(file).parent) for file in files if PurePosixPath(file).name == "__init__.py"}
    data: dict[str, set[str]] = defaultdict(set)
    for file in files:
        if file.endswith(".py"):
            continue
        parent = PurePosixPath(file).parent
        owner = next((str(folder) for folder in (parent, *parent.parents) if str(folder) in packages), None)
        if owner is not None:
            data[owner].add(file)
    return data


def _is_test(path: str) -> bool:
    pure = PurePosixPath(path)
    return pure.parts[0] == "tests" and pure.name.startswith("test_") and pure.suffix == ".py"
