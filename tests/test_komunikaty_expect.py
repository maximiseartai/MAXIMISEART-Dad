"""Komunikaty, które widzi tata, jako tekst w ``tests/expected/komunikaty.txt``.

Plik ma próbkę każdej fabryki każdego katalogu z ``tests/fixtures/message_samples.py``, pogrupowaną po katalogu,
z kodem i trzema częściami. Zmiana tekstu Komunikatu zmienia ten plik w tym samym PR, więc diff PR pokazuje,
co tata zobaczy inaczej, obok zmiany kodu.

Katalog to moduł fabryk Komunikatów: ma wpis w ``CATALOGS``, a każda jego publiczna funkcja ma próbkę.
Moduł ``src/``, który tworzy Komunikat poza katalogiem, ma w ``OUTSIDE_CATALOGS`` próbkę każdej funkcji i stałej,
która go tworzy (co liczy się jako utworzenie, mówi ``_creating``), więc i jego tekst trafia do pliku.
Zdanie dla taty, które karta pokazuje przy Komunikacie (dopisek bez kodu i trzech części), ma próbkę w ``SENTENCES``.
Błąd, który fabryka tłumaczy na Komunikat, niesie fakty, a nie zdanie dla taty, więc i jego tekst pisze katalog.
Odmowę żądania API Centrum rozliczeń (``Refusal``) tworzy tylko katalog odmów ``centrum/refusal.py``, a każda jego
publiczna funkcja ma próbkę w ``REFUSALS``, więc i zdanie odmowy trafia do pliku, z kodem HTTP zamiast kodu Komunikatu.
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
from typing import Final

import pytest

import rozliczenia
from rozliczenia import efenix_messages, intermax_messages, settlement_messages, workbook_messages, worker_config_messages
from rozliczenia import preparation_messages as messages
from rozliczenia.centrum import (
    diagnosis_messages,
    fill_messages,
    notification_messages,
    refusal,
    report_messages,
    run_cards,
    runs,
    start_problems,
    update_messages,
)
from rozliczenia.centrum.contract import common as common_contract
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
    REFUSALS,
    REGISTER,
    REPORT_SAMPLES,
    SETTLEMENT_SAMPLES,
    START_SAMPLES,
    UPDATE_SAMPLES,
    WORKER_CONFIG_SAMPLES,
    Samples,
)

ROOT = Path(__file__).resolve().parents[1]
CATALOGS: dict[str, tuple[ModuleType, Samples]] = {
    "Przygotowanie pliku zbiorczego": (messages, PREPARATION_SAMPLES),
    "Przebieg rozliczeń": (settlement_messages, SETTLEMENT_SAMPLES),
    "Konfiguracja wykonawców": (worker_config_messages, WORKER_CONFIG_SAMPLES),
    "Start Centrum rozliczeń": (start_problems, START_SAMPLES),
    "Diagnoza": (diagnosis_messages, DIAGNOSIS_SAMPLES),
    "Uzupełnienie pliku zbiorczego": (fill_messages, FILL_SAMPLES),
    "Zgłoszenie": (report_messages, REPORT_SAMPLES),
    "Powiadomienia": (notification_messages, NOTIFICATION_SAMPLES),
    "Aktualizacja narzędzia": (update_messages, UPDATE_SAMPLES),
    "Uporządkowanie INTERMAX": (intermax_messages, INTERMAX_SAMPLES),
    "Wycena w efenix": (efenix_messages, EFENIX_SAMPLES),
}
# Komunikat karty Urwanego Uruchomienia (common_contract.Message) nie ma kodu; tytuł procesu jest syntetyczny.
# Zdania wspólne o pliku taty dostają od katalogu kod, plik, ogon i zwrot ponowienia; tu syntetyczne.
_DAD_WORKBOOK = workbook_messages.DadWorkbook("Plik taty", "Pliku taty", "order_register", "Nic się nie zmieniło.", "ponów")
OUTSIDE_CATALOGS: dict[str, tuple[ModuleType, Mapping[str, Sequence[Callable[[], Message | common_contract.Message]]]]] = {
    "Plik taty (zdania wspólne)": (
        workbook_messages,
        {
            "open_in_excel": [lambda: workbook_messages.open_in_excel("PLIK_OTWARTY", REGISTER, _DAD_WORKBOOK)],
            "not_synced": [lambda: workbook_messages.not_synced("NIEDOSTEPNY_PLIK", REGISTER, _DAD_WORKBOOK)],
        },
    ),
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


# Zdania dla taty poza Komunikatem: dopisek, który karta pokazuje przy Komunikacie, bez kodu i trzech części.
SENTENCES: dict[str, tuple[ModuleType, Mapping[str, Sequence[Callable[[], str | None]]]]] = {
    "Wynik Uruchomienia (zdania)": (runs, {"stop_note": [lambda: runs.stop_note("for_maks")]}),
}


# Katalog odmów jest osobno: odmowa to kod HTTP i jedno zdanie, a nie Komunikat z kodem i trzema częściami.
REFUSAL_CATALOG: Final = "Odmowy Centrum rozliczeń"


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
    ``common_contract.Message``) kończy się na ``Message``, konstruktor tej klasy (``Message.to_maintainer(…)``), budowa
    modelu z danych (``common_contract.Message.model_validate(…)``, ``model_construct``) i kopia z nowym tekstem części
    (``_rewrites``). Wywołanie, które tylko przepisuje pola innego
    Komunikatu (``_copies``), nowego tekstu nie tworzy.

    Granica: ``model_copy`` ze słownikiem ``update`` spoza literału (``update=zmiany``, ``update=dict(...)``),
    ``replace`` z rozpakowaną zmienną (``**zmiany``), budowa modelu przez zmienną klasy (``typ = common_contract.Message``)
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
            case ast.Attribute(value=ast.Name(id=name)) if imported.get(name, name) == "Message":
                return True
            case ast.Name(id=name):
                return imported.get(name, name).endswith("Message")
            case ast.Attribute(attr=attr):
                return attr.endswith("Message")
            case _:
                return False

    return {name for name, statement in _places(tree.body) if any(creates(node) for node in ast.walk(statement))}


def _entry(name: str, message: Message | common_contract.Message) -> list[str]:
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
    for catalog, (module, sentences) in SENTENCES.items():
        lines += ["", f"=== {catalog} ({_source(module)}) ==="]
        for factory, sentence_samples in sentences.items():
            for number, sentence in enumerate(sentence_samples, start=1):
                variant = f" #{number}" if len(sentence_samples) > 1 else ""
                lines += ["", f"{factory}{variant} [zdanie]", f"  {sentence()}"]
    lines += ["", f"=== {REFUSAL_CATALOG} ({_source(refusal)}) ==="]
    for factory, refusal_samples in REFUSALS.items():
        for number, refusal_sample in enumerate(refusal_samples, start=1):
            variant = f" #{number}" if len(refusal_samples) > 1 else ""
            refused = refusal_sample()
            lines += ["", f"{factory}{variant} [HTTP {refused.status_code}]", f"  {refused.message}"]
    return "\n".join(lines) + "\n"


def test_kazde_miejsce_tworzace_komunikat_ma_probke_w_pliku_expect() -> None:
    creating = {path.relative_to(ROOT).as_posix(): places for path in (ROOT / "src").rglob("*.py") if (places := _creating(path))}
    outside = {_source(module): set(samples) for module, samples in OUTSIDE_CATALOGS.values()}

    assert set(creating) == {_source(module) for module, _ in CATALOGS.values()} | set(outside)
    assert {path: creating[path] for path in outside} == outside


@pytest.mark.parametrize("catalog", [*CATALOGS, REFUSAL_CATALOG])
def test_probki_pokrywaja_kazda_publiczna_funkcje_katalogu(catalog: str) -> None:
    module, samples = CATALOGS[catalog] if catalog in CATALOGS else (refusal, REFUSALS)
    public = {
        name
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and not name.startswith("_")
    }

    assert set(samples) == public


def test_kazdy_katalog_probek_trafia_do_pliku_expect() -> None:
    sample_sets = {name for name, value in vars(message_samples).items() if name.endswith("_SAMPLES")}

    assert {id(getattr(message_samples, name)) for name in sample_sets} == {id(samples) for _, samples in CATALOGS.values()}


def test_odmowe_api_centrum_tworzy_tylko_katalog_odmow() -> None:
    """Klasa ``Refusal`` jako wartość stoi tylko w ``centrum/refusal.py``, więc tylko katalog tworzy odmowę.

    Odwołanie do klasy to jej nazwa, alias importu modułu albo atrybut modułu (``refusal.Refusal``). Poza katalogiem
    odwołanie przechodzi tylko w typie: w adnotacji parametru, zwrotu, pola albo zmiennej, w nawiasach typu i unii
    ``|`` w instrukcji modułu albo klasy poza wywołaniem i lambdą (alias ``Callable[[], Refusal | None]``), w
    ``except``, w drugim argumencie ``isinstance``/``issubclass`` i w argumencie ``exception_handler``.
    Każde inne odwołanie pada, w tym wywołanie, argument wywołania (``partial(Refusal, 500)``), przypisanie do nazwy
    (także lokalnej), element kolekcji, wartość domyślna, klasa bazowa, odwołanie wewnątrz wywołania albo lambdy i
    nawiasy typu albo unia w ciele funkcji (``make = Refusal | Refusal``, ``list[Refusal].__args__[0](…)``).
    Granica (tylko przegląd): ``getattr`` z napisem (``"Refusal"``), import wewnątrz funkcji, ``type(odmowa)(…)``,
    ``copy``/``replace`` gotowej odmowy i klasa wyjęta z aliasu typu modułu bez odwołania do ``Refusal`` w tym miejscu
    (``ShutdownBlocker.__args__…``).
    """

    def outside_type(module: ModuleType) -> bool:
        tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
        typed = {id(inner) for root in _type_positions(tree) for inner in _type_nodes(root)}
        return any(
            isinstance(node, ast.Name | ast.Attribute) and id(node) not in typed and _resolved(module, node) is refusal.Refusal
            for node in ast.walk(tree)
        )

    assert {module.__name__ for module in _engine_modules() if outside_type(module)} == {refusal.__name__}


def _type_nodes(root: ast.AST) -> Iterator[ast.AST]:
    """Węzły typu w ``root`` bez wnętrza wywołań i lambd, więc ``CACHE[Refusal(500, "x")]`` nie jest typem."""

    if isinstance(root, ast.Call | ast.Lambda):
        return
    yield root
    for child in ast.iter_child_nodes(root):
        yield from _type_nodes(child)


def _type_positions(tree: ast.AST) -> Iterator[ast.expr]:
    """Wyrażenia, w których klasa stoi jako typ, a nie wartość (lista w docstringu strażnika katalogu odmów)."""

    called = {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call | ast.Lambda)
        for inner in ast.walk(node)
        if inner is not node
    } | {
        id(inner)
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for statement in node.body
        for inner in ast.walk(statement)
    }
    for node in ast.walk(tree):
        match node:
            case ast.FunctionDef(args=args, returns=returns) | ast.AsyncFunctionDef(args=args, returns=returns):
                parameters = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
                yield from (parameter.annotation for parameter in parameters if parameter and parameter.annotation)
                if returns is not None:
                    yield returns
            case ast.AnnAssign(annotation=annotation):
                yield annotation
            case ast.Subscript(slice=inner) if id(node) not in called:
                yield inner
            case ast.BinOp(left=left, op=ast.BitOr(), right=right) if id(node) not in called:
                yield from (left, right)
            case ast.ExceptHandler(type=kind) if kind is not None:
                yield kind
            case ast.Call(func=ast.Name(id="isinstance" | "issubclass"), args=[_, kind]):
                yield kind
            case ast.Call(func=ast.Attribute(attr="exception_handler"), args=handled):
                yield from handled
            case _:
                pass


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
