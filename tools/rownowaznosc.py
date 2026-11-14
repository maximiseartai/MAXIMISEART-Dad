"""Sprawdza, że refaktor nie zmienia wyniku procesów (scenariusze syntetyczne na bazie i HEAD), a z --ast drzew składni src/; użyj przy refaktorze src/.

Weryfikacja różnicowa refaktoru: te same scenariusze syntetyczne na commicie bazy i na HEAD dają ten sam wynik.

Użycie (z katalogu repozytorium):

    .venv/bin/python tools/rownowaznosc.py [--baza COMMIT] [--glowa COMMIT] [--scenariusz NAZWA ...]
    .venv/bin/python tools/rownowaznosc.py --ast [--baza COMMIT] [--glowa COMMIT]

Całego zachowania procesów nie opisze żaden test, ale da się sprawdzić, że zmiana nic w nim nie zmienia. Narzędzie
buduje raz scenariusze syntetyczne trzech procesów (Przebieg rozliczeń, Przygotowanie pliku zbiorczego,
Uporządkowanie INTERMAX) z atrap plików taty ``tools/lib/atrapy`` i Wzorców z ``tools/lib/atrapy/wzorce.py``, także z
Zatrzymaniem i z plikiem uszkodzonym, i uruchamia każdy skryptem dla maszyn ``tools/uruchom_proces.py`` obu stron:

- baza: kopia commitu ``--baza`` (``potomne.commit_copy``), domyślnie merge-base HEAD z ``origin/main``;
- HEAD: drzewo robocze checkoutu razem z niezacommitowanymi zmianami, żeby autor sprawdził zmianę przed commitem,
  a z ``--glowa`` kopia tego commitu.

Każda strona dostaje własną kopię wejść scenariusza i uruchamia swój ``tools/uruchom_proces.py`` ze swoim ``src``,
więc zmiana skryptu dla maszyn też jest zmianą zachowania. Scenariusze biegną najwyżej ``PARALLEL`` naraz.
Te same scenariusze, uruchomione tak samo (``built`` i ``run``), opisuje karta Uruchomienia w plikach expect testu
``tests/test_uruchomienia_expect.py``, więc nowy scenariusz dopisuje też swoją kartę.
Porównanie:

- kod wyjścia i JSON wyniku (``result``, ``summary``, ``warnings`` i ``stop`` z kodem i trzema częściami Komunikatu,
  ``progress``, ``technical_notes``, ``metrics_saved``) z zamaskowanymi polami zmiennymi: czasy (klucze ``*_ms`` i
  liczby z jednostką ``ms``), chwile z zegara (``RRRR-MM-DD GG-MM-SS`` i ISO 8601) i ścieżki folderów strony;
- pliki folderu scenariusza po uruchomieniu, z chwilą w nazwie zamaskowaną (pliki, których nazwy różnią się tylko
  chwilą, dostają numer kolejny, więc dodatkowa kopia jest różnicą): każdy skoroszyt, także Rozliczenie pracownika,
  część po części zipu bez ``docProps/core.xml`` (czas zapisu), inny plik bajtowo. Dwa uruchomienia tego samego kodu
  dają te same części, a porównanie znaczeniowe (``tools/porownanie_rozliczen.py``) nie widzi ochrony arkusza,
  autofiltra ani komentarzy. Ceną jest RÓŻNICA także przy zmianie zapisu bez zmiany znaczenia. Plik metryk leży poza
  folderem scenariusza i nie jest porównywany.

Wynik to tekst bez wartości komórek i pól: jedna linia na scenariusz, ``<scenariusz> | TAK SAMO | <kod i wynik>``
albo ``<scenariusz> | RÓŻNICA | <co się różni>``, a na końcu ``RÓWNOWAŻNOŚĆ OK | <n> scenariuszy`` (kod 0) albo
``RÓWNOWAŻNOŚĆ RÓŻNICA | <scenariusze>`` (kod 1). Scenariusz, którego fixture nie ma w tym checkoucie (checkout
starszy od procesu), daje linię ``BEZ FIXTURE`` i nie wchodzi do wyniku, a gdy żaden scenariusz nie został porównany,
wynik to ``RÓWNOWAŻNOŚĆ NIESPRAWDZONA | 0 scenariuszy`` (kod 2).

W kopii ``tools/na_scalonych_pr.py`` drzewo robocze ma ``tools/`` z innego checkoutu, więc tam podaj obie strony:

    .venv/bin/python tools/na_scalonych_pr.py --ostatnie 5 -- tools/rownowaznosc.py --baza HEAD^1 --glowa HEAD

Z ``--ast`` narzędzie nie uruchamia scenariuszy, tylko porównuje pliki ``src/`` zmienione od bazy (``repo.changed``,
bez wykrywania przeniesień). Plik jest ``TAK SAMO`` tylko wtedy, gdy obie strony kompiluje ``compile`` Pythona, którym
biegnie narzędzie (``refused_by_compiler``), i gdy ich drzewa składni (``ast.dump`` bez pozycji w źródle) po usunięciu
każdej instrukcji, która jest samym napisem (docstringów modułu, klas i funkcji oraz napisów pod przypisaniem), są
równe. Kompilator i parser dostają bajty pliku, więc dekodują je jak interpreter, według deklaracji kodowania i BOM.
Wynik kończy linia ``RÓWNOWAŻNOŚĆ OK | <n> plików`` (kod 0), ``RÓWNOWAŻNOŚĆ RÓŻNICA | <pliki>`` (kod 1) albo, bez
zmienionego pliku, ``RÓWNOWAŻNOŚĆ NIESPRAWDZONA | 0 plików`` (kod 2).

``<plik> | RÓŻNICA | <co>`` dostaje więc: plik, którego kompilator nie przyjmuje po którejkolwiek stronie, z jego
komunikatem (każda reguła kompilacji, także ta, której parser nie sprawdza: miejsce ``from __future__``, ``return``,
``break`` i ``await`` poza swoim miejscem, ``nonlocal`` na poziomie modułu, zduplikowany argument), zmianę drzewa
(także ``from __future__``, inną samotną stałą niż napis, napis jedynej instrukcji ciała zamieniony na ``pass``, inne
znaczenie bajtów po zmianie deklaracji kodowania), plik tylko po jednej stronie (dodany, usunięty, a przeniesiony po
obu) i plik, który nie jest ``.py`` ani ``.pyi``. ``TAK SAMO`` dostaje zmiana komentarzy, także dyrektyw narzędzi
(``# type:``, ``# noqa``, ``# pragma``, ``# mypy:``), które nie działają w biegu, a sprawdzają je ruff, mypy i licznik
tłumień w ``tools/szybko.py``, zmiana samych napisów i sam BOM. Inny Python może kompilować inaczej, więc wynik mówi
o wersji Pythona, którą uruchomiono narzędzie. Tryb nie widzi trzech rzeczy, które sprawdza osobne polecenie:

- docstringu czytanego w biegu: klasy Pydantic i trasy idą do kontraktu (``tools/ci/export_openapi.py``, potem
  ``git diff --exit-code frontend/src/api/openapi.json``), a ``__doc__`` w kodzie znajduje ``git grep -n __doc__ -- src``;
- docstringu definicji z modelem skilla ``verify-*``, którego skrót się zmienia (``tools/przesun_model.py <skill>``);
- pliku spoza ``src/`` (``git diff --name-only <baza> -- . ':!src'``).
"""

from __future__ import annotations

import argparse
import ast
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from dataclasses import dataclass
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Literal, get_args
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import potomne
from atrapy import wzorce
from atrapy.pliki_taty import WORKER_TEMPLATE_NAME
from repo import BASE, ROOT
import repo
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.period_folder import PeriodFolder

PARALLEL = 3
TIMEOUT = 600
TIME = "<CZAS>"
MOMENT = "<CHWILA>"
FOLDER = "<FOLDER>"
_MOMENT = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}[:-]\d{2}[:-]\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_WRITE_TIME = "docProps/core.xml"
# Tyle różnych pól JSON nazywa linia scenariusza, a resztę liczy.
_FIELDS = 5

Process = Literal["settlement", "preparation", "intermax"]
"""Proces ze scenariuszami: klucz procesu katalogu bez Wyceny w efenix, która potrzebuje Atrapy efenix w Chromium, a
scenariusz to tylko pliki w folderze."""
assert set(get_args(Process)) < set(get_args(common_contract.ProcessKey)), "proces scenariusza to klucz procesu katalogu"


@dataclass(frozen=True)
class Scenario:
    name: str
    process: Process
    build: Callable[[Path], Sequence[str | Path]]
    """Buduje wejścia w pustym folderze i zwraca argumenty procesu; ścieżki z folderu stają się względne."""


@dataclass(frozen=True)
class Outcome:
    """Uruchomienie jednej strony: kod wyjścia, zamaskowany JSON (``None``, gdy stdout nie jest JSON) i folder."""

    code: int
    result: object
    folder: Path


# --- scenariusze -----------------------------------------------------------------------------------------------


def _settlement(change: Callable[[Path], None] | None = None, *, preview: bool = False, unmapped: bool = False) -> Callable[[Path], list[str | Path]]:
    def build(folder: Path) -> list[str | Path]:
        from atrapy.settlement import make_fixture, make_preview_fixture

        source, _, config = (make_preview_fixture if unmapped else make_fixture)(folder)
        if change is not None:
            change(source)
        arguments: list[str | Path] = ["--source", source, "--wykonawcy", config, "--worker-template", folder / WORKER_TEMPLATE_NAME]
        return [*arguments, "--dry-run"] if preview else arguments

    return build


def _quantities(source: Path) -> None:
    from atrapy.settlement import MARKED, write_quantity_source

    write_quantity_source(source, [MARKED, {"N": 2, "H": "dariusz.fikcyjny2"}, {"J": "nie", "X": 1}])


def _synthetic_worker_template(source: Path) -> None:
    wzorce.write_settlement_template(source.parents[1] / WORKER_TEMPLATE_NAME, "GODZINA", 128, comments=True)


def _existing_settlements(source: Path) -> None:
    folder = PeriodFolder.from_collective_file(source).worker_settlements
    folder.mkdir()
    (folder / "zostaje.txt").write_text("plik sprzed uruchomienia\n", encoding="utf-8")


def _not_a_workbook(path: Path) -> None:
    path.write_bytes(b"to nie jest skoroszyt\n")


def _cut(sheet_part: str) -> Callable[[Path], None]:
    def change(path: Path) -> None:
        from atrapy.workbooks import cut_sheet_after_data_rows

        cut_sheet_after_data_rows(path, sheet_part)

    return change


def _undefined_number_format(cell: str) -> Callable[[Path], None]:
    """Komórka ``cell`` dostaje styl z numerem formatu liczby, którego nie ma w stylach skoroszytu (#428)."""

    def change(path: Path) -> None:
        from openpyxl import load_workbook

        from atrapy.workbooks import active_worksheet, rewrite_parts

        workbook = load_workbook(path)
        active_worksheet(workbook)[cell].number_format = "0.000"
        workbook.save(path)
        with zipfile.ZipFile(path) as archive:
            found = re.search(rb'<cellXfs count="(\d+)"', archive.read("xl/styles.xml"))
        assert found is not None
        count = int(found[1])

        def undefined(name: str, data: bytes) -> bytes:
            if name == "xl/styles.xml":
                data = data.replace(b'<cellXfs count="%d"' % count, b'<cellXfs count="%d"' % (count + 1), 1)
                return data.replace(b"</cellXfs>", b'<xf numFmtId="250" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>', 1)
            if name.startswith("xl/worksheets/"):
                return re.sub(rb'<c r="%s" s="\d+"' % cell.encode(), b'<c r="%s" s="%d"' % (cell.encode(), count), data, count=1)
            return data

        rewrite_parts(path, undefined)

    return change


def _preparation(
    fixture: Literal["plain", "dad_layout", "incomplete"] = "plain",
    change: Callable[[Path], None] | None = None,
    *,
    preview: bool = False,
    synthetic_templates: bool = False,
    existing_file: bool = False,
) -> Callable[[Path], list[str | Path]]:
    def build(folder: Path) -> list[str | Path]:
        from atrapy.preparation import (
            COLLECTIVE_FILE_NAME,
            PERIOD,
            incomplete_period_fixture,
            make_dad_layout_fixture,
            make_preparation_fixture,
        )

        made = {"plain": make_preparation_fixture, "dad_layout": make_dad_layout_fixture, "incomplete": incomplete_period_fixture}[fixture](folder)
        if synthetic_templates:
            wzorce.write_internal_template(made.internal_template_path)
            wzorce.write_settlement_template(made.collective_template_path, "MIASTO", 128)
        if existing_file:
            made.period_directory.mkdir()
            shutil.copy2(made.collective_template_path, made.period_directory / COLLECTIVE_FILE_NAME)
        if change is not None:
            change(made.register_path)
        arguments: list[str | Path] = [
            "--register", made.register_path,
            "--periods-directory", made.periods_directory,
            "--period", PERIOD,
            "--wykonawcy", made.config_path,
            "--internal-template", made.internal_template_path,
            "--collective-template", made.collective_template_path,
        ]  # fmt: skip
        return [*arguments, "--dry-run"] if preview else arguments

    return build


def _intermax(change: Callable[[Path], None] | None = None, **register: object) -> Callable[[Path], list[str | Path]]:
    def build(folder: Path) -> list[str | Path]:
        from atrapy.intermax import Intermax

        path = folder / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
        Intermax(**register).write(path)  # type: ignore[arg-type]
        if change is not None:
            change(path)
        return ["--register", path, "--copies", folder / "Kopie INTERMAX"]

    return build


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("przebieg", "settlement", _settlement()),
    Scenario("przebieg-podglad", "settlement", _settlement(preview=True)),
    Scenario("przebieg-ilosci", "settlement", _settlement(_quantities)),
    Scenario("przebieg-wzorzec-syntetyczny", "settlement", _settlement(_synthetic_worker_template)),
    Scenario("przebieg-podglad-nieznany-wykonawca", "settlement", _settlement(preview=True, unmapped=True)),
    Scenario("przebieg-nieznany-wykonawca", "settlement", _settlement(unmapped=True)),
    Scenario("przebieg-folder-rozliczen-istnieje", "settlement", _settlement(_existing_settlements)),
    Scenario("przebieg-plik-zbiorczy-nie-skoroszyt", "settlement", _settlement(_not_a_workbook)),
    Scenario("przebieg-plik-zbiorczy-uciety", "settlement", _settlement(_cut("xl/worksheets/sheet1.xml"))),
    Scenario("przebieg-format-bez-definicji-L18", "settlement", _settlement(_undefined_number_format("L18"))),
    Scenario("przebieg-format-bez-definicji-M18", "settlement", _settlement(_undefined_number_format("M18"))),
    Scenario("przebieg-format-bez-definicji-AT18", "settlement", _settlement(_undefined_number_format("AT18"))),
    Scenario("przygotowanie", "preparation", _preparation()),
    Scenario("przygotowanie-podglad", "preparation", _preparation(preview=True)),
    Scenario("przygotowanie-uklad-folderow-taty", "preparation", _preparation("dad_layout")),
    Scenario("przygotowanie-wzorce-syntetyczne", "preparation", _preparation(synthetic_templates=True)),
    Scenario("przygotowanie-niepelny-okres", "preparation", _preparation("incomplete")),
    Scenario("przygotowanie-plik-zbiorczy-istnieje", "preparation", _preparation(existing_file=True)),
    Scenario("przygotowanie-rejestr-nie-skoroszyt", "preparation", _preparation(change=_not_a_workbook)),
    Scenario("przygotowanie-rejestr-uciety", "preparation", _preparation(change=_cut("xl/worksheets/sheet2.xml"))),
    Scenario("intermax", "intermax", _intermax()),
    Scenario("intermax-starszy-arkusz-zolte-komorki", "intermax", _intermax(older_sheet=True, yellow="cells")),
    Scenario("intermax-pierwszy-wiersz-na-miejscu", "intermax", _intermax(shifted=False)),
    Scenario("intermax-kalendarz-1904", "intermax", _intermax(epoch_1904=True)),
    Scenario("intermax-bez-surowych-zlecen", "intermax", _intermax(raw=())),
    Scenario("intermax-rejestr-nie-skoroszyt", "intermax", _intermax(_not_a_workbook)),
)


# --- maskowanie i porównanie -----------------------------------------------------------------------------------


def masked(value: object, folders: Sequence[Path]) -> object:
    """``folders`` od najgłębszego: folder scenariusza przed folderem strony, który go zawiera."""

    if isinstance(value, dict):
        hidden = {key for key in value if key.endswith("_ms")} | ({"value"} if value.get("unit") == "ms" else set())
        return {key: TIME if key in hidden else masked(item, folders) for key, item in value.items()}
    if isinstance(value, list):
        return [masked(item, folders) for item in value]
    if isinstance(value, str):
        for folder in folders:
            # Najpierw postać bez dowiązań: ścieżka względna albo przez dowiązanie (``/var`` → ``/private/var`` na
            # Macu, krótka nazwa ``RUNNER~1`` na Windows) jest końcówką postaci po ``resolve()``.
            for form in dict.fromkeys([str(folder.resolve()), str(folder)]):
                value = value.replace(form, FOLDER)
        return _MOMENT.sub(MOMENT, value)
    return value


def json_differences(base: object, head: object, path: str = "") -> list[str]:
    """Ścieżki pól, które się różnią, bez ich wartości; lista różnej długości to jedna różnica z obiema długościami."""

    if isinstance(base, dict) and isinstance(head, dict):
        found: list[str] = []
        for key in dict.fromkeys([*base, *head]):
            field = f"{path}.{key}" if path else key
            found += [field] if key not in base or key not in head else json_differences(base[key], head[key], field)
        return found
    if isinstance(base, list) and isinstance(head, list):
        if len(base) != len(head):
            return [f"{path} (liczba {len(base)}→{len(head)})"]
        return [found for index, pair in enumerate(zip(base, head, strict=True)) for found in json_differences(*pair, f"{path}[{index}]")]
    return [] if base == head else [path or "JSON"]


def files(folder: Path) -> dict[str, Path]:
    """Pliki folderu według nazwy z zamaskowaną chwilą; drugi i dalszy plik tej samej nazwy dostaje numer ``(2)``."""

    named: dict[str, list[Path]] = {}
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            named.setdefault(_MOMENT.sub(MOMENT, path.relative_to(folder).as_posix()), []).append(path)
    return {f"{name} ({number})" if number > 1 else name: path for name, paths in named.items() for number, path in enumerate(paths, 1)}


def _zip_parts(path: Path) -> dict[str, bytes] | None:
    try:
        with zipfile.ZipFile(path) as archive:
            return {name: archive.read(name) for name in archive.namelist() if name != _WRITE_TIME}
    except zipfile.BadZipFile:
        return None


def _workbook_difference(base: Path, head: Path) -> str | None:
    base_parts, head_parts = _zip_parts(base), _zip_parts(head)
    if base_parts is None or head_parts is None:
        return None if base.read_bytes() == head.read_bytes() else "bajty"
    differing = sorted(name for name in base_parts.keys() | head_parts.keys() if base_parts.get(name) != head_parts.get(name))
    return f"części {', '.join(differing)}" if differing else None


def file_differences(base: Path, head: Path) -> list[str]:
    base_files, head_files = files(base), files(head)
    found = []
    for side, names in (("bazie", base_files.keys() - head_files.keys()), ("HEAD", head_files.keys() - base_files.keys())):
        if names:
            found.append(f"pliki tylko w {side}: {', '.join(sorted(names))}")
    for name in sorted(base_files.keys() & head_files.keys()):
        pair = base_files[name], head_files[name]
        difference = _workbook_difference(*pair) if name.endswith(".xlsx") else None if pair[0].read_bytes() == pair[1].read_bytes() else "bajty"
        if difference:
            found.append(f"{name}: {difference}")
    return found


def _label(outcome: Outcome) -> str:
    result = outcome.result
    if not isinstance(result, dict):
        return f"kod {outcome.code}, bez JSON"
    stop = result.get("stop")
    code = stop.get("message", {}).get("code") if isinstance(stop, dict) else None
    return ", ".join(str(part) for part in (f"kod {outcome.code}", result.get("result"), code) if part)


def compare(name: str, base: Outcome, head: Outcome) -> tuple[str, bool]:
    """Linia scenariusza i czy obie strony dały to samo."""

    found = [f"kod {base.code}→{head.code}"] if base.code != head.code else []
    if base.result is None or head.result is None:
        if base.result != head.result:
            found.append("JSON tylko w " + ("HEAD" if base.result is None else "bazie"))
    else:
        fields = json_differences(base.result, head.result)
        if fields:
            more = f", … (+{len(fields) - _FIELDS})" if len(fields) > _FIELDS else ""
            found.append(f"JSON {', '.join(fields[:_FIELDS])}{more}")
    found += file_differences(base.folder, head.folder)
    if found:
        return f"{name} | RÓŻNICA | {'; '.join(found)}", False
    return f"{name} | TAK SAMO | {_label(base)}", True


# --- uruchomienie ----------------------------------------------------------------------------------------------


def _relative(argument: str | Path, folder: Path) -> str:
    return argument.relative_to(folder).as_posix() if isinstance(argument, Path) else argument


def built(scenario: Scenario, folder: Path) -> list[str]:
    folder.mkdir(parents=True)
    return [_relative(argument, folder) for argument in scenario.build(folder)]


def run(tree: Path, scenario: Scenario, arguments: Sequence[str], inputs: Path, side: Path) -> Outcome:
    folder = side / scenario.name
    shutil.copytree(inputs, folder)
    metrics = side / f"{scenario.name}-metryki.jsonl"
    command = [sys.executable, str(tree / "tools" / "uruchom_proces.py"), scenario.process, *arguments, "--metrics", str(metrics)]
    done = potomne.run(command, cwd=folder, timeout=TIMEOUT)
    try:
        result = masked(json.loads(done.stdout), (folder, side))
    except ValueError:
        result = None
    return Outcome(done.returncode, result, folder)


def equivalence(base_tree: Path, head_tree: Path, scenarios: Sequence[Scenario], work: Path) -> int:
    arguments: dict[str, list[str]] = {}
    for scenario in scenarios:
        try:
            arguments[scenario.name] = built(scenario, work / "wejscia" / scenario.name)
        except ModuleNotFoundError as error:
            if not (error.name or "").startswith("atrapy."):
                raise
            print(f"{scenario.name} | BEZ FIXTURE | {error.name}", flush=True)
    chosen = [scenario for scenario in scenarios if scenario.name in arguments]
    jobs = [(tree, scenario, side) for scenario in chosen for tree, side in ((base_tree, "baza"), (head_tree, "head"))]
    with ThreadPoolExecutor(PARALLEL) as pool:
        outcomes = list(pool.map(lambda job: run(job[0], job[1], arguments[job[1].name], work / "wejscia" / job[1].name, work / job[2]), jobs))
    differing = []
    for index, scenario in enumerate(chosen):
        line, same = compare(scenario.name, outcomes[2 * index], outcomes[2 * index + 1])
        print(line, flush=True)
        if not same:
            differing.append(scenario.name)
    if differing:
        print(f"RÓWNOWAŻNOŚĆ RÓŻNICA | {', '.join(differing)}")
        return 1
    if not chosen:
        print("RÓWNOWAŻNOŚĆ NIESPRAWDZONA | 0 scenariuszy")
        return 2
    print(f"RÓWNOWAŻNOŚĆ OK | {len(chosen)} scenariuszy")
    return 0


def _lone_string(node: ast.AST) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def syntax(source: bytes) -> str:
    """Drzewo składni bajtów ``source`` bez instrukcji, które są samym napisem, i bez pozycji w źródle."""

    tree = ast.parse(source)
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                setattr(node, field, [item for item in value if not _lone_string(item)])
    return ast.dump(tree)


def _source(repository: Path, revision: str | None, path: str) -> bytes | None:
    """Bajty pliku w commicie ``revision``, a bez niego w drzewie roboczym; ``None``, gdy pliku tam nie ma."""

    if revision is None:
        file = repository / path
        return file.read_bytes() if file.is_file() else None
    return repo.blob(repository, revision, path)


def refused_by_compiler(source: bytes, path: str) -> str | None:
    """Komunikat kompilatora tego Pythona, gdy bajty ``source`` pliku ``path`` się nie kompilują; ``None``, gdy się
    kompilują."""

    try:
        compile(source, path, "exec", dont_inherit=True)
    except SyntaxError as refused:
        return refused.msg
    except ValueError as refused:
        return str(refused)
    return None


def _syntax_difference(path: str, base: bytes | None, head: bytes | None) -> str | None:
    if base is None or head is None:
        return "plik tylko w " + ("HEAD" if base is None else "bazie")
    for side, source in (("bazie", base), ("HEAD", head)):
        refused = refused_by_compiler(source, path)
        if refused is not None:
            return f"plik nie kompiluje się w {side}: {refused}"
    return None if syntax(base) == syntax(head) else "drzewo składni"


def syntax_equivalence(repository: Path, base: str, head: str | None) -> int:
    """Linia każdego pliku ``src/`` zmienionego od ``base`` do ``head`` (bez niego do drzewa roboczego) i kod wyniku."""

    paths = sorted(repo.changed(repository, base, head, paths=("src",)))
    differing = []
    for path in paths:
        if Path(path).suffix in {".py", ".pyi"}:
            difference = _syntax_difference(path, _source(repository, base, path), _source(repository, head, path))
        else:
            difference = "nie plik Pythona"
        if difference:
            differing.append(path)
        print(f"{path} | RÓŻNICA | {difference}" if difference else f"{path} | TAK SAMO", flush=True)
    if differing:
        print(f"RÓWNOWAŻNOŚĆ RÓŻNICA | {', '.join(differing)}")
        return 1
    if not paths:
        print("RÓWNOWAŻNOŚĆ NIESPRAWDZONA | 0 plików")
        return 2
    print(f"RÓWNOWAŻNOŚĆ OK | {len(paths)} plików")
    return 0


def default_base(repository: Path, head: str | None) -> str:
    return repo.merge_base(repository, head or "HEAD", BASE)


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    names = [scenario.name for scenario in SCENARIOS]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", metavar="COMMIT", help="Commit bazy; domyślnie merge-base HEAD (albo --glowa) z origin/main.")
    parser.add_argument("--glowa", metavar="COMMIT", help="Commit HEAD zamiast drzewa roboczego z niezacommitowanymi zmianami.")
    chosen = parser.add_mutually_exclusive_group()
    chosen.add_argument("--scenariusz", action="append", choices=names, metavar="NAZWA", help=f"Tylko ten scenariusz; powtórz dla kilku: {', '.join(names)}.")
    chosen.add_argument("--ast", action="store_true", help="Zamiast scenariuszy drzewa składni plików src/ zmienionych od bazy, bez docstringów i komentarzy.")
    args = parser.parse_args(argv)
    scenarios = [scenario for scenario in SCENARIOS if not args.scenariusz or scenario.name in args.scenariusz]
    base = args.baza or default_base(ROOT, args.glowa)
    if args.ast:
        return syntax_equivalence(ROOT, base, args.glowa)
    head = nullcontext(ROOT) if args.glowa is None else potomne.commit_copy(ROOT, args.glowa)
    with tempfile.TemporaryDirectory(prefix="rownowaznosc-") as work, potomne.commit_copy(ROOT, base) as base_tree, head as head_tree:
        return equivalence(base_tree, head_tree, scenarios, Path(work))


if __name__ == "__main__":
    raise SystemExit(main())
