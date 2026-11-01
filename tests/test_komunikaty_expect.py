"""Komunikaty, które widzi tata, jako tekst w ``tests/expected/komunikaty.txt``.

Plik ma próbkę każdej fabryki każdego katalogu z ``tests/fixtures/message_samples.py``, pogrupowaną po katalogu,
z kodem i trzema częściami. Zmiana tekstu Komunikatu zmienia ten plik w tym samym PR, więc diff PR pokazuje,
co tata zobaczy inaczej, obok zmiany kodu.

Katalog to moduł fabryk Komunikatów: ma wpis w ``CATALOGS``, a każda jego publiczna funkcja ma próbkę.
Moduł ``src/``, który tworzy Komunikat poza katalogiem, ma w ``OUTSIDE_CATALOGS`` próbkę każdej funkcji i stałej,
która go tworzy (co liczy się jako utworzenie, mówi ``_creating``), więc i jego tekst trafia do pliku.
Błąd, który fabryka tłumaczy na Komunikat, niesie fakty, a nie zdanie dla taty, więc i jego tekst pisze katalog.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator, Mapping, Sequence, Set
import importlib
import inspect
from pathlib import Path
import pkgutil
from types import ModuleType
import typing

import pytest

import rozliczenia
from rozliczenia import efenix_messages, intermax_messages, settlement_messages
from rozliczenia import preparation_messages as messages
from rozliczenia.centrum import (
    contract,
    diagnosis_messages,
    fill_messages,
    notification_messages,
    report_messages,
    run_cards,
    runs,
    start_problems,
    update_messages,
)
from rozliczenia.message import Message, StopError
from rozliczenia.period_folder import PeriodFolderError, PeriodFolderInaccessible, PeriodFolderLookupError
from rozliczenia.workbook_files import WorkbookError
from rozliczenia.workbook_save import WorkbookSaveError
from rozliczenia.worker_config import WorkerConfigError

from tests.fixtures import message_samples
from tests.fixtures.expect import assert_expected
from tests.fixtures.message_samples import (
    DIAGNOSIS_SAMPLES,
    EFENIX_SAMPLES,
    FILL_SAMPLES,
    INTERMAX_SAMPLES,
    NOTIFICATION_SAMPLES,
    PERIOD,
    PREPARATION_SAMPLES,
    REPORT_SAMPLES,
    SETTLEMENT_SAMPLES,
    START_SAMPLES,
    UPDATE_SAMPLES,
    Samples,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOGS: dict[str, tuple[ModuleType, Samples]] = {
    "Przygotowanie pliku zbiorczego": (messages, PREPARATION_SAMPLES),
    "Przebieg rozliczeń": (settlement_messages, SETTLEMENT_SAMPLES),
    "Start Centrum rozliczeń": (start_problems, START_SAMPLES),
    "Diagnoza": (diagnosis_messages, DIAGNOSIS_SAMPLES),
    "Uzupełnienie pliku zbiorczego": (fill_messages, FILL_SAMPLES),
    "Zgłoszenie": (report_messages, REPORT_SAMPLES),
    "Powiadomienia": (notification_messages, NOTIFICATION_SAMPLES),
    "Aktualizacja narzędzia": (update_messages, UPDATE_SAMPLES),
    "Uporządkowanie INTERMAX": (intermax_messages, INTERMAX_SAMPLES),
    "Wycena w efenix": (efenix_messages, EFENIX_SAMPLES),
}
# Komunikat karty Urwanego Uruchomienia (contract.Message) nie ma kodu; tytuł procesu jest syntetyczny.
OUTSIDE_CATALOGS: dict[str, tuple[ModuleType, Mapping[str, Sequence[Callable[[], Message | contract.Message]]]]] = {
    "Wynik Uruchomienia": (runs, {"_RESULT_NOT_SHOWN": [lambda: runs._RESULT_NOT_SHOWN]}),
    "Karta Urwanego Uruchomienia": (
        run_cards,
        {
            "_interrupted_advice": [
                lambda: run_cards._interrupted_advice("Przygotowanie pliku zbiorczego", PERIOD, dry_run=True),
                lambda: run_cards._interrupted_advice("Przygotowanie pliku zbiorczego", PERIOD, dry_run=False),
            ]
        },
    ),
}


def _source(module: ModuleType) -> str:
    return f"src/{module.__name__.replace('.', '/')}.py"


def _places(statements: list[ast.stmt], prefix: str = "") -> Iterator[tuple[str, ast.stmt]]:
    """Instrukcje modułu z nazwą miejsca: funkcja, ``Klasa.metoda``, stała albo numer wiersza."""

    for statement in statements:
        match statement:
            case ast.ClassDef(name=name, body=body):
                yield from _places(body, f"{prefix}{name}.")
            case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                yield f"{prefix}{name}", statement
            case ast.Assign(targets=[ast.Name(id=name)]) | ast.AnnAssign(target=ast.Name(id=name)):
                yield f"{prefix}{name}", statement
            case _:
                yield f"{prefix}wiersz {statement.lineno}", statement


_PARTS = frozenset({"what", "where", "action"})


def _copies(call: ast.Call, module_names: Set[str]) -> bool:
    """``Message(what=message.what, where=message.where, …)``: każde pole z tego samego pola jednego obiektu funkcji.

    Obiekt to parametr albo zmienna funkcji; nazwa modułu (stała, klasa, import) ma własny tekst, więc kopią nie jest.
    """

    owners = [
        keyword.value.value.id
        for keyword in call.keywords
        if isinstance(keyword.value, ast.Attribute)
        and isinstance(keyword.value.value, ast.Name)
        and keyword.value.attr == keyword.arg
    ]
    return (
        not call.args
        and len(owners) == len(call.keywords)
        and len(set(owners)) == 1
        and owners[0] not in module_names
    )


def _names_part(node: ast.expr) -> bool:
    """Literał słownika z kluczem ``what``, ``where`` albo ``action``."""

    return isinstance(node, ast.Dict) and any(isinstance(key, ast.Constant) and key.value in _PARTS for key in node.keys)


def _rewrites(call: ast.Call) -> bool:
    """``komunikat.model_copy(update={"action": …})`` albo ``replace(komunikat, action=…)``: nowy tekst w kopii.

    ``replace`` liczy się także z rozpakowanym literałem słownika (``replace(komunikat, **{"action": …})``).
    """

    match call.func:
        case ast.Attribute(attr="model_copy"):
            return any(keyword.arg == "update" and _names_part(keyword.value) for keyword in call.keywords)
        case ast.Name(id="replace") | ast.Attribute(attr="replace"):
            return any(
                keyword.arg in _PARTS or (keyword.arg is None and _names_part(keyword.value)) for keyword in call.keywords
            )
        case _:
            return False


def _creating(path: Path) -> set[str]:
    """Miejsca modułu (``_places``), które tworzą Komunikat.

    Tworzy go wywołanie, którego nazwa po rozwiązaniu importów (``Message as M``) albo atrybut (``message.Message``,
    ``contract.Message``) kończy się na ``Message``, budowa modelu z danych (``contract.Message.model_validate(…)``,
    ``model_construct``) i kopia z nowym tekstem części (``_rewrites``). Wywołanie, które tylko przepisuje pola innego
    Komunikatu (``_copies``), nowego tekstu nie tworzy.

    Granica: ``model_copy`` ze słownikiem ``update`` spoza literału (``update=zmiany``, ``update=dict(...)``),
    ``replace`` z rozpakowaną zmienną (``**zmiany``), budowa modelu przez zmienną klasy (``typ = contract.Message``)
    i przepisanie pól obiektu z tekstem, który powstał w funkcji (``t = SimpleNamespace(what="…")``), łapie tylko
    przegląd.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    module_names = (
        set(imported)
        | {statement.name for statement in tree.body if isinstance(statement, ast.ClassDef)}
        | {
            node.id
            for statement in tree.body
            if isinstance(statement, ast.Assign | ast.AnnAssign)
            for node in ast.walk(statement)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
    )

    def creates(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call) or _copies(node, module_names):
            return False
        if _rewrites(node):
            return True
        match node.func:
            case ast.Attribute(value=ast.Name(id=name), attr="model_validate" | "model_construct"):
                return imported.get(name, name).endswith("Message")
            case ast.Attribute(value=ast.Attribute(attr=attr), attr="model_validate" | "model_construct"):
                return attr.endswith("Message")
            case ast.Name(id=name):
                return imported.get(name, name).endswith("Message")
            case ast.Attribute(attr=attr):
                return attr.endswith("Message")
            case _:
                return False

    return {name for name, statement in _places(tree.body) if any(creates(node) for node in ast.walk(statement))}


def _entry(name: str, message: Message | contract.Message) -> list[str]:
    if isinstance(message, Message):
        return [f"{name} [{message.code}]", *(f"  {line}" for line in message.text.splitlines())]
    return [f"{name} [bez kodu]", f"  Co się stało: {message.what}", f"  Gdzie: {message.where}", f"  Co zrobić: {message.action}"]


def _rendered() -> str:
    lines = [
        "# Komunikaty, które widzi tata: próbka każdej fabryki każdego katalogu i każdego Komunikatu spoza katalogów.",
        "# Plik zapisuje tests/test_komunikaty_expect.py; ścieżki w próbkach są syntetyczne.",
    ]
    for catalog, (module, samples) in (CATALOGS | OUTSIDE_CATALOGS).items():
        lines += ["", f"=== {catalog} ({_source(module)}) ==="]
        for factory, factory_samples in samples.items():
            for number, sample in enumerate(factory_samples, start=1):
                variant = f" #{number}" if len(factory_samples) > 1 else ""
                lines += ["", *_entry(f"{factory}{variant}", sample())]
    return "\n".join(lines) + "\n"


def test_kazde_miejsce_tworzace_komunikat_ma_probke_w_pliku_expect() -> None:
    creating = {path.relative_to(ROOT).as_posix(): places for path in (ROOT / "src").rglob("*.py") if (places := _creating(path))}
    outside = {_source(module): set(samples) for module, samples in OUTSIDE_CATALOGS.values()}

    assert set(creating) == {_source(module) for module, _ in CATALOGS.values()} | set(outside)
    assert {path: creating[path] for path in outside} == outside


@pytest.mark.parametrize("catalog", CATALOGS)
def test_probki_pokrywaja_kazda_publiczna_funkcje_katalogu(catalog: str) -> None:
    module, samples = CATALOGS[catalog]
    public = {
        name
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and not name.startswith("_")
    }

    assert set(samples) == public


def test_kazdy_katalog_probek_trafia_do_pliku_expect() -> None:
    sample_sets = {name for name, value in vars(message_samples).items() if name.endswith("_SAMPLES")}

    assert {id(getattr(message_samples, name)) for name in sample_sets} == {id(samples) for _, samples in CATALOGS.values()}


def _engine_modules() -> list[ModuleType]:
    return [importlib.import_module(info.name) for info in pkgutil.walk_packages(rozliczenia.__path__, "rozliczenia.")]


def _factories(modules: Sequence[ModuleType]) -> list[Callable[..., object]]:
    """Funkcje modułów z adnotacją ``-> Message``: fabryki katalogów i ich funkcje prywatne."""

    return [
        function
        for module in modules
        for _, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and function.__annotations__.get("return") in ("Message", Message)
    ]


def _resolved(module: ModuleType, node: ast.expr) -> object:
    """Obiekt nazwy (``StopError``) albo atrybutu (``settlement_messages.collective_file_invalid``) w module."""

    match node:
        case ast.Name(id=name):
            return vars(module).get(name)
        case ast.Attribute(value=value, attr=attr):
            return getattr(_resolved(module, value), attr, None)
        case _:
            return None


def _caught_for_message(module: ModuleType, makers: Sequence[object]) -> Iterator[object]:
    """Typy z ``except`` modułu, którego obsługa woła fabrykę Komunikatu albo tworzy ``StopError``."""

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or handler.type is None:
            continue
        calls = [node.func for node in ast.walk(handler) if isinstance(node, ast.Call)]
        if any(_resolved(module, call) is maker for call in calls for maker in makers):
            kinds = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            yield from (_resolved(module, kind) for kind in kinds)


def _variants(hint: object) -> tuple[object, ...]:
    return typing.get_args(hint) or (hint,)


def test_blad_ktory_proces_tlumaczy_na_komunikat_niesie_fakty_a_nie_tekst() -> None:
    """Wyjątek, z którego powstaje Komunikat, nie przyjmuje ``str``: zdanie dla taty pisze katalog, nie kod błędu.

    Taki wyjątek stoi w sygnaturze fabryki Komunikatu albo w ``except``, którego obsługa woła fabrykę albo tworzy
    ``StopError``. Sprawdzenie widzi parametry ``__init__`` z adnotacją ``str`` (także w unii) w klasach
    ``src/rozliczenia``, a błąd bez własnego ``__init__`` przyjmuje każdy tekst w ``args``, więc nie stoi w sygnaturze
    fabryki. Granica: pole ustawione bez parametru, parametr bez adnotacji, ``except`` na zmiennej (``except errors``),
    ``match`` na złapanym błędzie w obsłudze ``except BaseException``, tekst w dataclass faktu (``SameWorkerFile``
    niesie nazwy z konfiguracji) i błąd bez własnego ``__init__`` tylko w ``except``, którego obsługa przekaże fabryce
    jego tekst (``str(error)``).
    """

    modules = _engine_modules()
    factories = _factories(modules)
    in_signatures = {
        kind for factory in factories for hint in typing.get_type_hints(factory).values() for kind in _variants(hint)
    }
    caught = {kind for module in modules for kind in _caught_for_message(module, [*factories, StopError])}
    errors = {
        kind
        for kind in in_signatures | caught
        if inspect.isclass(kind) and issubclass(kind, BaseException) and kind.__module__.startswith("rozliczenia.")
    }
    with_text = {
        f"{error.__name__}.{parameter}"
        for error in errors
        if inspect.isfunction(error.__init__)
        for parameter, hint in typing.get_type_hints(error.__init__).items()
        if str in _variants(hint)
    } | {f"{error.__name__}.args" for error in errors & in_signatures if not inspect.isfunction(error.__init__)}

    assert with_text == set()
    assert {WorkbookError, WorkerConfigError, PeriodFolderError, PeriodFolderLookupError} <= in_signatures
    assert {PeriodFolderInaccessible, WorkbookSaveError} <= caught


def test_komunikaty_ktore_widzi_tata_odpowiadaja_plikowi_expect() -> None:
    assert_expected(_rendered(), ROOT / "tests" / "expected" / "komunikaty.txt")
