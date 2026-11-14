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
Napis przycisku, który próbka cytuje w „…”, ma wpis w ``UI_TEXTS`` i stoi w jego pliku frontendu, a cytat spoza UI
Centrum rozliczeń ma powód w ``QUOTES_OUTSIDE_UI``.
"""

from __future__ import annotations

import ast
from functools import partial
from collections.abc import Callable, Iterator, Mapping, Sequence, Set
import importlib
import inspect
from pathlib import Path
import pkgutil
import re
from types import ModuleType
import typing
from typing import Final, get_args

import pytest

import rozliczenia
from rozliczenia import (
    efenix_messages,
    intermax_messages,
    report_entering_messages,
    settlement_messages,
    tool_files,
    workbook_messages,
)
from rozliczenia import preparation_messages as messages
from rozliczenia.centrum import (
    diagnosis_messages,
    fill_messages,
    notification_messages,
    refusal,
    reminder_messages,
    report_entering_run,
    report_messages,
    run_cards,
    runs,
    start_problems,
    update_messages,
)
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.settings.files import FieldPath
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.migrations.workers import OLD_ADDRESSES_FILE, OLD_MAPPING_FILE
from rozliczenia.centrum.settings.quantity_rules import DEVICES_FILE, RULES_FILE
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.message import Message, StopError
from rozliczenia.period_folder import PeriodFolderError, PeriodFolderInaccessible, PeriodFolderLookupError
from rozliczenia.workbook_files import WorkbookError
from rozliczenia.workbook_save import WorkbookSaveError

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
    REMINDER_SAMPLES,
    REPORT_ENTERING_SAMPLES,
    REPORT_SAMPLES,
    SETTLEMENT_SAMPLES,
    START_SAMPLES,
    UPDATE_SAMPLES,
    Samples,
)
from tests.fixtures.skladnia import drzewo, pamiec_drzew, wezly
from tests.fixtures.znane_luki import assert_znane_luki, modul, ruff_i_mypy, wymaga_ruff_i_mypy, zapisz

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
    "Wpisanie raportów": (report_entering_messages, REPORT_ENTERING_SAMPLES),
    "Przypomnienia o raporcie": (reminder_messages, REMINDER_SAMPLES),
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
    "Karta Wpisania raportów (zdania)": (
        report_entering_run,
        {"conflict_note": [lambda: report_entering_run.conflict_note(message_samples.CONFLICT_COPY)]},
    ),
    "Ustawienia Centrum (zdania)": (
        settings_messages,
        {
            "not_text": [partial(settings_messages.not_text, SETTINGS_FILE)],
            "damaged": [
                partial(settings_messages.damaged, SETTINGS_FILE),
                partial(settings_messages.damaged, WORKERS_FILE, settings_messages.MAKS_FIXES),
            ],
            "other_schema": [partial(settings_messages.other_schema, SETTINGS_FILE)],
            "unknown_key": [partial(settings_messages.unknown_key, SETTINGS_FILE, 2)],
            "register_path": [settings_messages.register_path],
            "periods_directory_path": [settings_messages.periods_directory_path],
            "unknown_theme": [settings_messages.unknown_theme],
            "bad_field": [
                partial(settings_messages.bad_field, WORKERS_FILE, FieldPath("wykonawcy", 0, "aktywny"), settings_messages.MAKS_FIXES)
            ],
            "worker_unknown_key": [partial(settings_messages.worker_unknown_key, WORKERS_FILE, 1, 1)],
            "worker_without_login": [settings_messages.worker_without_login],
            "worker_login_empty": [settings_messages.worker_login_empty],
            "worker_login_repeated": [settings_messages.worker_login_repeated],
            "worker_name_empty": [settings_messages.worker_name_empty],
            "worker_name_invalid": [settings_messages.worker_name_invalid],
            "worker_name_too_long": [settings_messages.worker_name_too_long],
            "worker_same_file": [settings_messages.worker_same_file],
            "worker_address_invalid": [settings_messages.worker_address_invalid],
            "worker_address_repeated": [settings_messages.worker_address_repeated],
            "worker_unknown": [settings_messages.worker_unknown],
            "worker_list_changed": [settings_messages.worker_list_changed],
            "worker_suggestions_not_set": [settings_messages.worker_suggestions_not_set],
            "worker_suggestions_unreadable": [settings_messages.worker_suggestions_unreadable],
            "worker_rename_old_files": [
                partial(settings_messages.worker_rename_old_files, ("08_14_09_2026",)),
                partial(settings_messages.worker_rename_old_files, ("08_14_09_2026", "01_07_09_2026", "25_31_08_2026")),
            ],
            "workers_not_moved": [
                partial(settings_messages.workers_not_moved, OLD_MAPPING_FILE, "plik nie jest poprawnym YAML")
            ],
            "worker_list_not_created": [settings_messages.worker_list_not_created],
            "worker_list_waiting": [settings_messages.worker_list_waiting],
            "worker_list_unreadable": [settings_messages.worker_list_unreadable],
            "addresses_not_moved": [
                partial(settings_messages.addresses_not_moved, OLD_ADDRESSES_FILE, "ten sam adres stoi dwa razy")
            ],
            "reminders_time": [settings_messages.reminders_time],
            "reminders_empty_morning": [settings_messages.reminders_empty_morning],
            "reminders_empty_evening": [settings_messages.reminders_empty_evening],
            "reminders_overlap": [settings_messages.reminders_overlap],
            "reminders_empty_text": [settings_messages.reminders_empty_text],
            "reminders_unknown_field": [settings_messages.reminders_unknown_field],
            "reminders_without_since": [settings_messages.reminders_without_since],
            "autostart_unsupported": [settings_messages.autostart_unsupported],
            "autostart_unreadable": [settings_messages.autostart_unreadable],
            "unavailable": [partial(settings_messages.unavailable, RULES_FILE)],
            "rule_without_action": [settings_messages.rule_without_action],
            "rule_hour": [settings_messages.rule_hour],
            "needed_by_rules": [partial(settings_messages.needed_by_rules, DEVICES_FILE, "instalacja ręczna")],
            "needed_by_release_rules": [partial(settings_messages.needed_by_release_rules, "wizja")],
            # Zapis usuwa się tylko spośród innych zapisów składnika, a nazwę zmienia się albo usuwa cały składnik.
            "release_component_taken": [
                partial(settings_messages.release_component_taken, "wizja" if how == "zapis" else "instalacja ręczna", "instalacja ręczna", how)
                for how in get_args(settings_messages.TakenAction)
            ],
            "rules_wait_for_release_component": [
                partial(
                    settings_messages.rules_wait_for_release_component,
                    "wizja" if how == "zapis" else "instalacja ręczna",
                    "instalacja ręczna",
                    how,
                )
                for how in get_args(settings_messages.TakenAction)
            ],
            "spelling_taken": [partial(settings_messages.spelling_taken, "wizja", "instalacja ręczna")],
            "component_used_by_rule": [
                partial(
                    settings_messages.component_used_by_rule,
                    "instalacja ręczna",
                    "Jeśli URZĄDZENIA zawierają „instalacja ręczna”, to wpisz 1 w AN.",
                )
            ],
            "rule_needs_component": [
                partial(
                    settings_messages.rule_needs_component,
                    "instalacja ręczna",
                    "Jeśli URZĄDZENIA zawierają „instalacja ręczna”, to wpisz 1 w AN.",
                )
            ],
            "quantity_rules_problem": [
                partial(settings_messages.quantity_rules_problem, RULES_FILE, "Wartość musi być liczbą całkowitą od 1 do 999.")
            ],
        },
    ),
}


# Katalog odmów jest osobno: odmowa to kod HTTP i jedno zdanie, a nie Komunikat z kodem i trzema częściami.
REFUSAL_CATALOG: Final = "Odmowy Centrum rozliczeń"


@pytest.fixture(autouse=True, scope="module")
def drzewa_raz_na_modul() -> Iterator[None]:
    with pamiec_drzew():
        yield


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

    tree = drzewo(path)
    imported = {
        alias.asname or alias.name: alias.name
        for node in wezly(tree)
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

    reason = "Komunikat tworzy tylko moduł z CATALOGS albo OUTSIDE_CATALOGS: przenieś tworzenie do katalogu albo dopisz moduł z próbkami"
    assert set(creating) == {_source(module) for module, _ in CATALOGS.values()} | set(outside), reason
    assert {path: creating[path] for path in outside} == outside, reason


@pytest.mark.parametrize("catalog", [*CATALOGS, REFUSAL_CATALOG])
def test_probki_pokrywaja_kazda_publiczna_funkcje_katalogu(catalog: str) -> None:
    module, samples = CATALOGS[catalog] if catalog in CATALOGS else (refusal, REFUSALS)
    public = {
        name
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and not name.startswith("_")
    }

    assert set(samples) == public, "każda publiczna funkcja katalogu ma próbkę: dopisz ją w message_samples albo zrób funkcję prywatną"


def test_kazdy_katalog_probek_trafia_do_pliku_expect() -> None:
    sample_sets = {name for name, value in vars(message_samples).items() if name.endswith("_SAMPLES")}

    assert {id(getattr(message_samples, name)) for name in sample_sets} == {id(samples) for _, samples in CATALOGS.values()}


def test_odmowe_api_centrum_tworzy_tylko_katalog_odmow() -> None:
    """Klasa ``Refusal`` jako wartość stoi tylko w ``centrum/refusal.py``, więc tylko katalog tworzy odmowę.

    Konstruktor bez dowodu katalogu (``refusal._CATALOG``) i podklasę odrzuca też mypy, a dowód poza katalogiem ruff
    (``TID251``), ale typ gubi klasę wziętą jako wartość, np. ``Refusal.__new__(Refusal)`` (odmowa bez
    ``status_code``, przegląd #1371 r1) i ``get_args(Refusal | None)[0](…)`` (#1179 r2). Te łapie ten test.
    Próbki ``ZNANE_LUKI`` pokazują znane luki: postacie, które przepuszczają wszystkie te mechanizmy, a nazwa próbki
    mówi ich klasę.

    Odwołanie do klasy to jej nazwa, alias importu modułu albo atrybut modułu (``refusal.Refusal``). Poza katalogiem
    odwołanie przechodzi tylko w typie: w adnotacji parametru, zwrotu, pola albo zmiennej, w nawiasach typu i unii
    ``|`` w instrukcji modułu albo klasy poza wywołaniem i lambdą (alias ``Callable[[], Refusal | None]``), w
    ``except``, w drugim argumencie ``isinstance``/``issubclass`` i w argumencie ``exception_handler``.
    Każde inne odwołanie pada, w tym wywołanie, argument wywołania (``partial(Refusal, 500)``), przypisanie do nazwy
    (także lokalnej), element kolekcji, wartość domyślna, klasa bazowa, odwołanie wewnątrz wywołania albo lambdy i
    nawiasy typu albo unia w ciele funkcji (``make = Refusal | Refusal``, ``list[Refusal].__args__[0](…)``).
    """

    assert {module.__name__ for module in _engine_modules() if _refusal_as_value(module)} == {refusal.__name__}, (
        "odmowę żądania API Centrum (Refusal: kod HTTP i zdanie dla taty) tworzy tylko katalog odmów "
        "src/rozliczenia/centrum/refusal.py: dopisz tam fabrykę z próbką w message_samples i wołaj ją, a poza katalogiem "
        "używaj Refusal tylko jako typu (adnotacja, except, isinstance, exception_handler)"
    )


# Znane luki strażnika katalogu odmów (tests/fixtures/znane_luki.py): „klasa, którą przepuszczają mechanizmy: postać” →
# moduł, który tworzy odmowę poza katalogiem, a mimo to przechodzi przez mypy, ruff z konfiguracją src/ i test nazw wyżej.
ZNANE_LUKI: Final = {
    "ufa tłumieniu ruff: _refused zaimportowana z noqa": """\
from rozliczenia.centrum.refusal import Refusal, _refused  # noqa: TID251


def odmowa() -> Refusal:
    return _refused(500, "Zdanie spoza katalogu odmów.")
""",
    "ufa tłumieniu ruff: dowód zaimportowany z noqa": """\
from rozliczenia.centrum.refusal import _CATALOG, Refusal  # noqa: TID251


def odmowa(wzor: Refusal) -> Refusal:
    return type(wzor)(500, "Zdanie spoza katalogu odmów.", _CATALOG)
""",
    "ufa tłumieniu mypy: konstruktor bez dowodu z type: ignore": """\
from rozliczenia.centrum.refusal import Refusal


def odmowa(wzor: Refusal) -> Refusal:
    return type(wzor)(500, "Zdanie spoza katalogu odmów.", None)  # type: ignore[arg-type]  # próbka
""",
    "refleksja po nazwie atrybutu: dowód z getattr modułu": """\
from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import Refusal


def odmowa(wzor: Refusal) -> Refusal:
    return type(wzor)(500, "Zdanie spoza katalogu odmów.", getattr(refusal, "_CATALOG"))
""",
    "typ Any wyłącza mypy: dowód typu Any": """\
from typing import Any, cast

from rozliczenia.centrum.refusal import Refusal


def odmowa(wzor: Refusal) -> Refusal:
    return type(wzor)(500, "Zdanie spoza katalogu odmów.", cast(Any, None))
""",
    "rozpoznaje tylko nazwę globalną modułu: Refusal.__new__ z importem wewnątrz funkcji": """\
def odmowa() -> Exception:
    from rozliczenia.centrum.refusal import Refusal

    return Refusal.__new__(Refusal)
""",
    "klasa wzięta z wartości, nie z nazwy: argument aliasu typu modułu": """\
from typing import get_args

from rozliczenia.centrum.refusal import Refusal

Odmowa = Refusal | None


def odmowa() -> Exception:
    wynik: Exception = get_args(Odmowa)[0](500, "Zdanie spoza katalogu odmów.", None)
    return wynik
""",
    "refleksja po nazwie atrybutu: klasa z getattr modułu": """\
from rozliczenia.centrum import refusal


def odmowa() -> Exception:
    wynik: Exception = getattr(refusal, "Refusal")(500, "Zdanie spoza katalogu odmów.", None)
    return wynik
""",
    "odmowa z gotowej odmowy: copy.copy": """\
import copy

from rozliczenia.centrum.refusal import Refusal, unexpected_failure


def odmowa() -> Refusal:
    return copy.copy(unexpected_failure())
""",
    "odmowa z gotowej odmowy: copy.deepcopy": """\
import copy

from rozliczenia.centrum.refusal import Refusal, unexpected_failure


def odmowa() -> Refusal:
    return copy.deepcopy(unexpected_failure())
""",
    "klasa wzięta z wartości, nie z nazwy: type(wzor).__new__(type(wzor))": """\
from rozliczenia.centrum.refusal import Refusal


def odmowa(wzor: Refusal) -> Refusal:
    return type(wzor).__new__(type(wzor))
""",
    "odmowa z gotowej odmowy: nowe zdanie wpisane w pole": """\
from rozliczenia.centrum.refusal import Refusal, unexpected_failure


def odmowa() -> Refusal:
    wynik = unexpected_failure()
    wynik.message = "Zdanie spoza katalogu odmów."
    return wynik
""",
}


@wymaga_ruff_i_mypy
def test_znane_luki_strazy_katalogu_odmow_przechodza_przez_kazdy_jego_mechanizm(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI, tmp_path)
    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "sonda_luki.py")
    for opis, plik in pliki.items():
        if _refusal_as_value(modul(plik)):
            zgloszenia[opis].append("test_odmowe_api_centrum_tworzy_tylko_katalog_odmow: Refusal jako wartość")

    assert_znane_luki(zgloszenia, "tests/test_komunikaty_expect.py")


# Znane luki strażnika miejsca złego ustawienia (tests/fixtures/znane_luki.py): opis postaci → moduł Ustawień Centrum,
# który kładzie tekst z pliku (nieznany klucz) w miejscu złego ustawienia albo w zdaniu o nim, a mimo to przechodzi przez
# mypy na konstruktorze FieldPath i ruff z konfiguracją src/.
ZNANE_LUKI_FIELD_PATH: Final = {
    "klucz z json.loads jako Any": """\
import json

from rozliczenia.centrum.settings.files import FieldPath


def miejsce(tekst: str) -> FieldPath:
    return FieldPath(json.loads(tekst)["klucz"])
""",
    "klucz przez cast": """\
from typing import cast

from rozliczenia.centrum.settings.files import FieldName, FieldPath


def miejsce(klucz: str) -> FieldPath:
    return FieldPath(cast(FieldName, klucz))
""",
    "klucz z type: ignore": """\
from rozliczenia.centrum.settings.files import FieldPath


def miejsce(klucz: str) -> FieldPath:
    return FieldPath(klucz)  # type: ignore[arg-type]
""",
    "tekst wpisany po budowie": """\
from rozliczenia.centrum.settings.files import FieldPath


def miejsce(klucz: str) -> FieldPath:
    wynik = FieldPath("wykonawcy")
    object.__setattr__(wynik, "text", klucz)
    return wynik
""",
    "tekst przez dataclasses.replace": """\
import dataclasses

from rozliczenia.centrum.settings.files import FieldPath


def miejsce(klucz: str) -> FieldPath:
    return dataclasses.replace(FieldPath("wykonawcy"), text=klucz)
""",
    "zdanie z kluczem w fabryce przyjmującej str": """\
def zle_pole(plik: str, klucz: str) -> str:
    return f"Plik {plik} w folderze config ma złą wartość pola {klucz}. Poprawia go Maks."
""",
}


@wymaga_ruff_i_mypy
def test_znane_luki_miejsca_zlego_ustawienia_przechodza_przez_mypy_i_ruff(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI_FIELD_PATH, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "centrum" / "settings" / "sonda_luki.py")

    assert_znane_luki(zgloszenia, "tests/test_komunikaty_expect.py (ZNANE_LUKI_FIELD_PATH)")


def _refusal_as_value(module: ModuleType) -> bool:
    """Moduł odwołuje się do ``Refusal`` poza typem (``test_odmowe_api_centrum_tworzy_tylko_katalog_odmow``)."""

    tree = drzewo(Path(str(module.__file__)))
    typed = {id(inner) for root in _type_positions(tree) for inner in _type_nodes(root)}
    return any(
        isinstance(node, ast.Name | ast.Attribute) and id(node) not in typed and _resolved(module, node) is refusal.Refusal
        for node in wezly(tree)
    )


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
        for node in wezly(tree)
        if isinstance(node, ast.Call | ast.Lambda)
        for inner in ast.walk(node)
        if inner is not node
    } | {
        id(inner)
        for node in wezly(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        for statement in node.body
        for inner in ast.walk(statement)
    }
    for node in wezly(tree):
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

    tree = drzewo(Path(str(module.__file__)))
    for handler in wezly(tree):
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
    assert {WorkbookError, PeriodFolderError, PeriodFolderLookupError} <= in_signatures
    assert {PeriodFolderInaccessible, WorkbookSaveError} <= caught


def test_komunikaty_ktore_widzi_tata_odpowiadaja_plikowi_expect() -> None:
    assert_expected(_rendered(), ROOT / "tests" / "expected" / "komunikaty.txt")


# Napisy UI Centrum rozliczeń, które Komunikaty cytują w „…”, każdy z plikiem frontendu, w którym tata go widzi.
UI_TEXTS: Final = {
    "Wyślij do Maksa": "frontend/src/components/report-to-maks.tsx",
    "Spróbuj ponownie": "frontend/src/components/report-to-maks.tsx",
    "Co zostanie wysłane": "frontend/src/components/report-to-maks.tsx",
    "Zaktualizuj narzędzie": "frontend/src/components/tool-update.tsx",
    "Zamknij Centrum rozliczeń": "frontend/src/components/close-centrum.tsx",
    "Uzupełnij i zapisz": "frontend/src/lib/pricing.tsx",
    "Uzupełnij bez zapisu": "frontend/src/lib/pricing.tsx",
    "Kontynuuj": "frontend/src/pages/runs/run-dialogs.tsx",
    "Zostaw moją": "frontend/src/pages/worker-reports/day-details.tsx",
    "Zapisz": "frontend/src/pages/settings/devices-section.tsx",
    "Usuń składnik": "frontend/src/pages/settings/devices-section.tsx",
}
# Cytaty Komunikatów, których test nie szuka w pliku frontendu, każdy z powodem: tekst spoza UI Centrum rozliczeń
# albo napis UI w postaci, której ``_ui_text`` nie czyta.
QUOTES_OUTSIDE_UI: Final = {
    "Centrum rozliczeń": "skrót na pulpicie taty, nie napis w UI",
    "Zawsze zachowuj na tym urządzeniu": "polecenie OneDrive w menu Eksploratora plików",
    "Do wyceny": "status zlecenia w efenix",
    "Do akceptacji": "status zlecenia w efenix",
    "???": "wartość komórki z próbki",
    "tsk": "wartość komórki z próbki",
    ".08_14_09_2026.staging-": "początek nazwy folderu tymczasowego z próbki",
    ".Rozliczenie pracowników 08_14_09_2026.staging-": "początek nazwy folderu tymczasowego z próbki",
    tool_files.WORKER_TEMPLATE.name: "nazwa pliku Wzorca w folderze config, na którą tata zmienia placeholder.xlsx",
    "Diagnoza": "napis przycisku w drugiej gałęzi warunku (pages/runs/diagnosis.tsx), postaci, której test nie czyta; sprawdza przegląd",
    "instalacja ręczna": "nazwa składnika z Listy Urządzeń w próbce, dana pliku, nie napis UI",
    "wizja": "nazwa składnika z Listy Urządzeń w próbce, dana pliku, nie napis UI",
}


def _ui_text(text: str) -> re.Pattern[str]:
    """Napis w jednej z form, w których plik TSX pokazuje go tacie jako napis przycisku.

    Test szuka napisu w tych postaciach: tekst dziecka elementu JSX (``<Button>…Kontynuuj</Button>``, także po ikonie
    ``{…}`` i złamany w linii), prop ``label="…"`` albo ``label={"…"}`` (nie ``aria-label``) i właściwość
    ``label: "…"`` obiektu napisów; w propie i właściwości napis stoi w podwójnym cudzysłowie i cały.
    Gdy napisu nie ma w pliku w żadnej z tych postaci, test czerwieni: przycisk zmienił brzmienie albo zniknął.
    Napis przycisku w innej postaci (np. w gałęzi warunku) ma powód w ``QUOTES_OUTSIDE_UI``.
    """

    words = r"\s+".join(re.escape(word) for word in text.split())
    literal = f'"{words}"'
    forms = (
        rf"[>}}]\s*{words}\s*[<{{]",
        rf"(?<![\w-])label=\{{?{literal}\}}?",
        rf"(?<![\w-])label:\s*{literal}",
    )
    return re.compile("|".join(forms))


def test_napis_przycisku_cytowany_w_komunikacie_stoi_w_ui_centrum() -> None:
    """Komunikat, który każe kliknąć „Napis”, nie rozjeżdża się z przyciskiem, który tata widzi w Centrum rozliczeń.

    Cytaty są z próbek wszystkich katalogów (``_rendered``), więc zmiana cytatu w Pythonie albo napisu w pliku TSX
    czerwieni ten test; nowy cytat dostaje wpis w ``UI_TEXTS`` albo powód w ``QUOTES_OUTSIDE_UI``.
    Plik UI ma napis w jednej z postaci: dziecko JSX, ``label="…"``, ``label={"…"}`` albo ``label: "…"``.
    Próbki ``ZNANE_LUKI_NAPISOW_UI`` i ``ZNANE_LUKI_CYTATOW`` pokazują znane luki: postacie, które test przepuszcza bez
    przycisku z cytowanym napisem, a nazwa próbki mówi ich klasę.
    """

    quoted = set(re.findall(r"„([^”]*)”", _rendered()))
    missing_in_ui = {
        text: path for text, path in UI_TEXTS.items() if not _ui_text(text).search((ROOT / path).read_text(encoding="utf-8"))
    }

    assert quoted - UI_TEXTS.keys() - QUOTES_OUTSIDE_UI.keys() == set(), (
        "napis UI cytowany w Komunikacie w „…” stoi w pliku frontendu: dopisz cytat do UI_TEXTS z plikiem, który go "
        "pokazuje, a cytat spoza UI (albo napis w innej postaci, np. w gałęzi warunku) do QUOTES_OUTSIDE_UI z powodem"
    )
    assert (UI_TEXTS.keys() | QUOTES_OUTSIDE_UI.keys()) - quoted == set(), "żaden Komunikat nie cytuje już tego napisu: usuń wpis"
    assert missing_in_ui == {}, (
        "Komunikat cytuje napis, którego plik UI nie pokazuje jako napisu przycisku (dziecko JSX, label=\"…\", label={\"…\"} "
        "albo label: \"…\"): popraw cytat w Komunikacie albo napis w pliku z UI_TEXTS, żeby tata nie szukał przycisku, którego nie ma"
    )


# Znane luki strażnika napisów przycisków (tests/fixtures/znane_luki.py): „klasa, którą przepuszcza test: postać” →
# plik TSX z napisem „Kontynuuj” z UI_TEXTS bez przycisku, który tata widzi, a mimo to przechodzi przez test wyżej jako
# plik tego napisu.
ZNANE_LUKI_NAPISOW_UI: Final = {
    "dopasowuje tekst, nie element przycisku: nagłówek": "export function Okno() {\n  return <h2>Kontynuuj</h2>\n}\n",
    "nie odróżnia komentarza od kodu: przycisk w komentarzu JSX": (
        "export function Okno() {\n  return <div>{/* <Button>Kontynuuj</Button> */}</div>\n}\n"
    ),
    "nie wykonuje warunków JSX: przycisk w gałęzi, która się nie renderuje": (
        "export function Okno() {\n  return <div>{false && <Button>Kontynuuj</Button>}</div>\n}\n"
    ),
    "czyta plik z UI_TEXTS, nie to, czy ktoś go renderuje: przycisk w komponencie, którego nic nie importuje": (
        "export function StareOkno() {\n  return <Button>Kontynuuj</Button>\n}\n"
    ),
}
# Znane luki tego strażnika po stronie Komunikatu: „klasa: postać” → moduł z fabryką, której gałąź cytuje napis spoza
# UI_TEXTS i QUOTES_OUTSIDE_UI, i z krotką PROBKI, której Komunikaty tego cytatu nie mają; test dokłada moduł do
# SENTENCES, więc strażnik czyta go tą samą drogą co katalogi repozytorium.
ZNANE_LUKI_CYTATOW: Final = {
    "widzi tylko Komunikaty z próbek: cytat w gałęzi bez próbki": """\
def komunikat(zapisany: bool) -> str:
    if zapisany:
        return "Plik jest zapisany."
    return "Kliknij „Przycisk, którego nie ma”."


PROBKI = (lambda: komunikat(zapisany=True),)
""",
}


def _zgloszenia_napisow(
    ui_texts: Mapping[str, str], sentences: Mapping[str, tuple[ModuleType, Mapping[str, Sequence[Callable[[], str | None]]]]]
) -> list[str]:
    """Linie zgłoszenia testu napisów przycisków, gdy ``UI_TEXTS`` to ``ui_texts``, a ``SENTENCES`` to ``sentences``."""

    with pytest.MonkeyPatch.context() as podmiana:
        podmiana.setitem(globals(), "UI_TEXTS", ui_texts)
        podmiana.setitem(globals(), "SENTENCES", sentences)
        try:
            test_napis_przycisku_cytowany_w_komunikacie_stoi_w_ui_centrum()
        except AssertionError as blad:
            return [linia.strip() for linia in str(blad).splitlines()]
    return []


def test_znane_luki_strazy_napisow_przyciskow_przechodza_przez_niego(tmp_path: Path) -> None:
    zgloszenia = {}
    for numer, (opis, kod) in enumerate(ZNANE_LUKI_NAPISOW_UI.items()):
        plik = tmp_path / f"znana_luka_{numer}.tsx"
        plik.write_text(kod, encoding="utf-8")
        zgloszenia[opis] = _zgloszenia_napisow({**UI_TEXTS, "Kontynuuj": plik.as_posix()}, SENTENCES)
    for opis, plik in zapisz(ZNANE_LUKI_CYTATOW, tmp_path).items():
        probka = modul(plik)
        zgloszenia[opis] = _zgloszenia_napisow(UI_TEXTS, {**SENTENCES, opis: (probka, {"komunikat": probka.PROBKI})})

    assert_znane_luki(zgloszenia, "tests/test_komunikaty_expect.py (ZNANE_LUKI_NAPISOW_UI, ZNANE_LUKI_CYTATOW)")
