"""Sprawdza, że refaktor nie zmienia wyniku procesów: te same scenariusze syntetyczne na bazie i na HEAD; użyj przy refaktorze src/.

Weryfikacja różnicowa refaktoru: te same scenariusze syntetyczne na commicie bazy i na HEAD dają ten sam wynik.

Użycie (z katalogu repozytorium):

    .venv/bin/python tools/rownowaznosc.py [--baza COMMIT] [--glowa COMMIT] [--scenariusz NAZWA ...]

Całego zachowania procesów nie opisze żaden test, ale da się sprawdzić, że zmiana nic w nim nie zmienia. Narzędzie
buduje raz scenariusze syntetyczne trzech procesów (Przebieg rozliczeń, Przygotowanie pliku zbiorczego,
Uporządkowanie INTERMAX) z fixtures ``tests/fixtures`` i Wzorców z ``tools/syntetyczne_wzorce.py``, także z
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
"""

from __future__ import annotations

import argparse
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
from typing import Literal
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Korzeń repozytorium dla fixtures ``tests.fixtures``, z których powstają scenariusze.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/lib"))

import potomne
from repo import BASE, ROOT
import repo
import syntetyczne_wzorce

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
        from tests.fixtures.settlement import make_fixture, make_preview_fixture

        source, _, config = (make_preview_fixture if unmapped else make_fixture)(folder)
        if change is not None:
            change(source)
        arguments: list[str | Path] = ["--source", source, "--config", config, "--worker-template", folder / "Wzorzec rozliczenia pracownika.xlsx"]
        return [*arguments, "--dry-run"] if preview else arguments

    return build


def _quantities(source: Path) -> None:
    from tests.fixtures.settlement import MARKED, write_quantity_source

    write_quantity_source(source, [MARKED, {"N": 2, "H": "dariusz.fikcyjny2"}, {"J": "nie", "X": 1}])


def _synthetic_worker_template(source: Path) -> None:
    syntetyczne_wzorce.write_settlement_template(source.parents[1] / "Wzorzec rozliczenia pracownika.xlsx", "GODZINA", 128, comments=True)


def _existing_settlements(source: Path) -> None:
    folder = source.parent / f"Rozliczenie pracowników {source.parent.name}"
    folder.mkdir()
    (folder / "zostaje.txt").write_text("plik sprzed uruchomienia\n", encoding="utf-8")


def _not_a_workbook(path: Path) -> None:
    path.write_bytes(b"to nie jest skoroszyt\n")


def _cut(sheet_part: str) -> Callable[[Path], None]:
    def change(path: Path) -> None:
        from tests.fixtures.workbooks import cut_sheet_after_data_rows

        cut_sheet_after_data_rows(path, sheet_part)

    return change


def _undefined_number_format(cell: str) -> Callable[[Path], None]:
    """Komórka ``cell`` dostaje styl z numerem formatu liczby, którego nie ma w stylach skoroszytu (#428)."""

    def change(path: Path) -> None:
        from openpyxl import load_workbook

        from tests.fixtures.workbooks import active_worksheet, rewrite_parts

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
        from tests.fixtures.preparation import (
            COLLECTIVE_FILE_NAME,
            PERIOD,
            incomplete_period_fixture,
            make_dad_layout_fixture,
            make_preparation_fixture,
        )

        made = {"plain": make_preparation_fixture, "dad_layout": make_dad_layout_fixture, "incomplete": incomplete_period_fixture}[fixture](folder)
        if synthetic_templates:
            syntetyczne_wzorce.write_internal_template(made.internal_template_path)
            syntetyczne_wzorce.write_settlement_template(made.collective_template_path, "MIASTO", 128)
        if existing_file:
            made.period_directory.mkdir()
            shutil.copy2(made.collective_template_path, made.period_directory / COLLECTIVE_FILE_NAME)
        if change is not None:
            change(made.register_path)
        arguments: list[str | Path] = [
            "--register", made.register_path,
            "--periods-directory", made.periods_directory,
            "--period", PERIOD,
            "--config", made.config_path,
            "--internal-template", made.internal_template_path,
            "--collective-template", made.collective_template_path,
        ]  # fmt: skip
        return [*arguments, "--dry-run"] if preview else arguments

    return build


def _intermax(change: Callable[[Path], None] | None = None, **register: object) -> Callable[[Path], list[str | Path]]:
    def build(folder: Path) -> list[str | Path]:
        from tests.fixtures.intermax import Intermax

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
    """JSON wyniku bez pól, które zmieniają się z uruchomienia na uruchomienie: czasów, chwil zegara i ścieżek strony.

    ``folders`` od najgłębszego: folder scenariusza przed folderem strony, który go zawiera.
    """

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
    """Różnice plików dwóch folderów scenariusza po uruchomieniu: nazwy i części, bez treści."""

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
    """Buduje wejścia scenariusza w nowym folderze ``folder`` i zwraca argumenty procesu ze ścieżkami względnymi."""

    folder.mkdir(parents=True)
    return [_relative(argument, folder) for argument in scenario.build(folder)]


def run(tree: Path, scenario: Scenario, arguments: Sequence[str], inputs: Path, side: Path) -> Outcome:
    """Uruchamia scenariusz skryptem dla maszyn drzewa ``tree`` na kopii wejść ``inputs`` w folderze strony ``side``."""

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
    """Drukuje linię każdego scenariusza i ostatnią linię wyniku; zwraca kod wyjścia."""

    arguments: dict[str, list[str]] = {}
    for scenario in scenarios:
        try:
            arguments[scenario.name] = built(scenario, work / "wejscia" / scenario.name)
        except ModuleNotFoundError as error:
            if not (error.name or "").startswith("tests.fixtures."):
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


def default_base(repository: Path, head: str | None) -> str:
    """Merge-base ``head`` (bez niego HEAD checkoutu) z ``BASE``."""

    return repo.merge_base(repository, head or "HEAD", BASE)


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    names = [scenario.name for scenario in SCENARIOS]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baza", metavar="COMMIT", help="Commit bazy; domyślnie merge-base HEAD (albo --glowa) z origin/main.")
    parser.add_argument("--glowa", metavar="COMMIT", help="Commit HEAD zamiast drzewa roboczego z niezacommitowanymi zmianami.")
    parser.add_argument("--scenariusz", action="append", choices=names, metavar="NAZWA", help=f"Tylko ten scenariusz; powtórz dla kilku: {', '.join(names)}.")
    args = parser.parse_args(argv)
    scenarios = [scenario for scenario in SCENARIOS if not args.scenariusz or scenario.name in args.scenariusz]
    base = args.baza or default_base(ROOT, args.glowa)
    head = nullcontext(ROOT) if args.glowa is None else potomne.commit_copy(ROOT, args.glowa)
    with tempfile.TemporaryDirectory(prefix="rownowaznosc-") as work, potomne.commit_copy(ROOT, base) as base_tree, head as head_tree:
        return equivalence(base_tree, head_tree, scenarios, Path(work))


if __name__ == "__main__":
    raise SystemExit(main())
