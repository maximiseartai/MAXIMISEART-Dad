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
from typing import Final, NamedTuple, get_args

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
    mailing_messages,
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
from rozliczenia.centrum.settings.activity_legend import LEGEND_FILE
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
_SYNTETYCZNY_PLIK_TATY = workbook_messages.DadWorkbook(
    name="Plik taty", genitive="Pliku taty", dad_file="order_register", unchanged="Nic się nie zmieniło.", again="ponów"
)
OUTSIDE_CATALOGS: dict[str, tuple[ModuleType, Mapping[str, Sequence[Callable[[], Message | common_contract.Message]]]]] = {
    "Plik taty (zdania wspólne)": (
        workbook_messages,
        {
            "open_in_excel": [lambda: workbook_messages.open_in_excel("PLIK_OTWARTY", REGISTER, _SYNTETYCZNY_PLIK_TATY)],
            "not_synced": [lambda: workbook_messages.not_synced("NIEDOSTEPNY_PLIK", REGISTER, _SYNTETYCZNY_PLIK_TATY)],
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
            "worker_undo_breaks_list": [
                partial(settings_messages.worker_undo_breaks_list, settings_messages.worker_same_file(), ("Anna Przykład",)),
                partial(
                    settings_messages.worker_undo_breaks_list,
                    settings_messages.worker_login_repeated(),
                    ("Anna Przykład", "Jan Testowy", "Adam Próbny"),
                ),
                partial(settings_messages.worker_undo_breaks_list, settings_messages.worker_name_empty(), ()),
            ],
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
            "settlement_mail_empty_subject": [settings_messages.settlement_mail_empty_subject],
            "settlement_mail_subject_lines": [settings_messages.settlement_mail_subject_lines],
            "settlement_mail_report_word": [settings_messages.settlement_mail_report_word],
            "settlement_mail_reads_as_report": [settings_messages.settlement_mail_reads_as_report],
            "settlement_mail_unusable": [partial(settings_messages.settlement_mail_unusable, settings_messages.settlement_mail_reads_as_report())],
            "settlement_mail_unknown_field": [settings_messages.settlement_mail_unknown_field],
            "settlement_mail_empty_text": [settings_messages.settlement_mail_empty_text],
            "autostart_unsupported": [settings_messages.autostart_unsupported],
            "autostart_unreadable": [settings_messages.autostart_unreadable],
            "inbox_not_text": [settings_messages.inbox_not_text],
            "inbox_address": [settings_messages.inbox_address],
            "inbox_no_address": [settings_messages.inbox_no_address],
            "inbox_password_text": [settings_messages.inbox_password_text],
            "inbox_password_empty": [settings_messages.inbox_password_empty],
            "unavailable": [partial(settings_messages.unavailable, RULES_FILE)],
            "unreadable": [partial(settings_messages.unreadable, RULES_FILE)],
            "rule_without_action": [settings_messages.rule_without_action],
            "rule_hour": [settings_messages.rule_hour],
            "needed_by_rules": [partial(settings_messages.needed_by_rules, DEVICES_FILE, "instalacja ręczna")],
            "needed_by_release_rules": [partial(settings_messages.needed_by_release_rules, "wizja")],
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
            "component_name_empty": [settings_messages.component_name_empty],
            "spelling_with_star": [partial(settings_messages.spelling_with_star, "2*wizja")],
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
            "activity_legend_problem": [
                partial(settings_messages.activity_legend_problem, LEGEND_FILE, "Brakuje pola „schema_version”.")
            ],
        },
    ),
    "Wysyłka rozliczeń (zdania)": (
        mailing_messages,
        {
            "mailbox_without_access": [mailing_messages.mailbox_without_access],
            "mailbox_password_rejected": [mailing_messages.mailbox_password_rejected],
            "mailbox_unreachable": [mailing_messages.mailbox_unreachable],
            "sent_unread": [mailing_messages.sent_unread],
            "file_open_in_excel": [mailing_messages.file_open_in_excel],
            "file_unreadable": [mailing_messages.file_unreadable],
            "password_rejected": [mailing_messages.password_rejected],
            "no_network": [mailing_messages.no_network],
            "mail_refused": [mailing_messages.mail_refused],
            "worker_list_unusable": [mailing_messages.worker_list_unusable],
            "periods_directory_not_set": [mailing_messages.periods_directory_not_set],
            "periods_directory_missing": [mailing_messages.periods_directory_missing],
        },
    ),
}


REFUSAL_CATALOG: Final = "Odmowy Centrum rozliczeń"


@pytest.fixture(autouse=True, scope="module")
def drzewa_raz_na_modul() -> Iterator[None]:
    with pamiec_drzew():
        yield


def _source(module: ModuleType) -> str:
    return f"src/{module.__name__.replace('.', '/')}.py"


def _places(statements: list[ast.stmt], prefix: str = "") -> Iterator[tuple[str, ast.stmt]]:
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
    return isinstance(node, ast.Dict) and any(isinstance(key, ast.Constant) and key.value in _PARTS for key in node.keys)


def _rewrites(call: ast.Call) -> bool:
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


class Tworzenie(NamedTuple):
    kod: str
    miejsca: frozenset[str]


_KOMUNIKAT = """\
from dataclasses import replace
from types import SimpleNamespace

from rozliczenia import message
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract.common import Message as Karta
from rozliczenia.message import Message
from rozliczenia.message import Message as M
from rozliczenia.message_wzory import WZOR

"""
TWORZENIE_KOMUNIKATU: Final = {
    "wywolanie-klasy-message": Tworzenie(
        'def komunikat() -> Message:\n    return Message("KOD", "Co.", "Gdzie.", "Co zrobić.")\n', frozenset({"komunikat"})
    ),
    "alias-importu-message": Tworzenie(
        'def komunikat() -> Message:\n    return M("KOD", "Co.", "Gdzie.", "Co zrobić.")\n', frozenset({"komunikat"})
    ),
    "atrybut-modulu-message": Tworzenie(
        'def komunikat() -> Message:\n    return message.Message("KOD", "Co.", "Gdzie.", "Co zrobić.")\n',
        frozenset({"komunikat"}),
    ),
    "atrybut-common-contract-message": Tworzenie(
        'def karta() -> Karta:\n    return common_contract.Message(what="Co.", where="Gdzie.", action="Co zrobić.")\n',
        frozenset({"karta"}),
    ),
    "konstruktor-klasy-message": Tworzenie(
        'def komunikat() -> Message:\n    return Message.to_maintainer("KOD", "Co.", "Gdzie.")\n', frozenset({"komunikat"})
    ),
    "budowa-modelu-model-validate": Tworzenie(
        'def karta() -> Karta:\n    return common_contract.Message.model_validate({"what": "Co."})\n', frozenset({"karta"})
    ),
    "budowa-modelu-model-construct-z-aliasu-importu": Tworzenie(
        'def karta() -> Karta:\n    return Karta.model_construct(what="Co.")\n', frozenset({"karta"})
    ),
    "kopia-z-nowa-czescia-model-copy": Tworzenie(
        'def karta(wzor: Karta) -> Karta:\n    return wzor.model_copy(update={"action": "Nowe."})\n', frozenset({"karta"})
    ),
    "kopia-z-nowa-czescia-replace": Tworzenie(
        'def komunikat(wzor: Message) -> Message:\n    return replace(wzor, action="Nowe.")\n', frozenset({"komunikat"})
    ),
    "kopia-z-nowa-czescia-replace-z-rozpakowanym-literalem": Tworzenie(
        'def komunikat(wzor: Message) -> Message:\n    return replace(wzor, **{"action": "Nowe."})\n', frozenset({"komunikat"})
    ),
    "pola-obiektu-modulu-maja-wlasny-tekst": Tworzenie(
        "def karta() -> Karta:\n    return Karta(what=WZOR.what, where=WZOR.where, action=WZOR.action)\n",
        frozenset({"karta"}),
    ),
    "stala-modulu": Tworzenie('ZAPISANY = Message("KOD", "Co.", "Gdzie.", "Co zrobić.")\n', frozenset({"ZAPISANY"})),
    "metoda-klasy": Tworzenie(
        'class Karty:\n    def komunikat(self) -> Message:\n        return Message("KOD", "Co.", "Gdzie.", "Co zrobić.")\n',
        frozenset({"Karty.komunikat"}),
    ),
    "instrukcja-modulu-bez-nazwy": Tworzenie(
        'ZEBRANE: list[Message] = []\nZEBRANE.append(Message("KOD", "Co.", "Gdzie.", "Co zrobić."))\n',
        frozenset({"wiersz 12"}),
    ),
    "kopia-pol-parametru-to-nie-nowy-tekst": Tworzenie(
        "def karta(wzor: Karta) -> Karta:\n    return Karta(what=wzor.what, where=wzor.where, action=wzor.action)\n",
        frozenset(),
    ),
    "kopia-pol-zmiennej-funkcji-to-nie-nowy-tekst": Tworzenie(
        "def karta(wzory: list[Karta]) -> Karta:\n    wzor = wzory[0]\n"
        "    return Karta(what=wzor.what, where=wzor.where, action=wzor.action)\n",
        frozenset(),
    ),
    "model-copy-bez-czesci-komunikatu": Tworzenie(
        'def karta(wzor: Karta) -> Karta:\n    return wzor.model_copy(update={"code": "INNY"})\n', frozenset()
    ),
    "granica-model-copy-ze-slownikiem-ze-zmiennej": Tworzenie(
        'def karta(wzor: Karta) -> Karta:\n    zmiany = {"action": "Nowe."}\n    return wzor.model_copy(update=zmiany)\n',
        frozenset(),
    ),
    "granica-model-copy-ze-slownikiem-z-dict": Tworzenie(
        'def karta(wzor: Karta) -> Karta:\n    return wzor.model_copy(update=dict(action="Nowe."))\n', frozenset()
    ),
    "granica-replace-z-rozpakowana-zmienna": Tworzenie(
        'def komunikat(wzor: Message) -> Message:\n    zmiany = {"action": "Nowe."}\n    return replace(wzor, **zmiany)\n',
        frozenset(),
    ),
    "granica-budowa-modelu-przez-zmienna-klasy": Tworzenie(
        'def karta() -> Karta:\n    typ = common_contract.Message\n    return typ.model_validate({"what": "Co."})\n',
        frozenset(),
    ),
    "granica-kopia-pol-obiektu-z-tekstem-z-funkcji": Tworzenie(
        'def karta() -> Karta:\n    tekst = SimpleNamespace(what="Co.", where="Gdzie.", action="Co zrobić.")\n'
        "    return Karta(what=tekst.what, where=tekst.where, action=tekst.action)\n",
        frozenset(),
    ),
}


@pytest.mark.parametrize(
    ("kod", "miejsca"), [pytest.param(*przypadek, id=opis) for opis, przypadek in TWORZENIE_KOMUNIKATU.items()]
)
def test_miejsce_tworzace_komunikat_to_kazda_postac_tworzenia_a_granice_go_nie_maja(
    tmp_path: Path, kod: str, miejsca: frozenset[str]
) -> None:
    plik = tmp_path / "komunikaty.py"
    plik.write_text(_KOMUNIKAT + kod, encoding="utf-8")

    assert _creating(plik) == miejsca


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


def _sentence_modules() -> list[str]:
    catalogs = {module.__name__ for module, _ in (*CATALOGS.values(), *OUTSIDE_CATALOGS.values())}
    names = (".".join(path.relative_to(ROOT / "src").with_suffix("").parts) for path in sorted((ROOT / "src").rglob("*messages.py")))
    return [name for name in names if name not in catalogs]


@pytest.mark.parametrize("module_name", _sentence_modules())
def test_probki_pokrywaja_kazda_publiczna_funkcje_modulu_zdan(module_name: str) -> None:
    module = importlib.import_module(module_name)
    sampled = {sentence for owner, sentences in SENTENCES.values() if owner is module for sentence in sentences}
    public = {
        name
        for name, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and not name.startswith("_")
    }

    assert sampled == public, "każde publiczne zdanie modułu zdań ma próbkę: dopisz ją w SENTENCES albo zrób funkcję prywatną"


def test_kazdy_katalog_probek_trafia_do_pliku_expect() -> None:
    sample_sets = {name for name, value in vars(message_samples).items() if name.endswith("_SAMPLES")}

    assert {id(getattr(message_samples, name)) for name in sample_sets} == {id(samples) for _, samples in CATALOGS.values()}


def test_odmowe_api_centrum_tworzy_tylko_katalog_odmow() -> None:
    assert {module.__name__ for module in _engine_modules() if _refusal_as_value(module)} == {refusal.__name__}, (
        "odmowę żądania API Centrum (Refusal: kod HTTP i zdanie dla taty) tworzy tylko katalog odmów "
        "src/rozliczenia/centrum/refusal.py: dopisz tam fabrykę z próbką w message_samples i wołaj ją, a poza katalogiem "
        "używaj Refusal tylko jako typu (adnotacja, except, isinstance, exception_handler)"
    )


class Odwolanie(NamedTuple):
    kod: str
    jako_wartosc: bool


_ODMOWA = "from rozliczenia.centrum.refusal import Refusal\n\n\n"
ODWOLANIA_DO_ODMOWY: Final = {
    "adnotacja-parametru": Odwolanie("def obsluz(odmowa: Refusal) -> None:\n    pass\n", False),
    "adnotacja-zwrotu": Odwolanie("def odmowa() -> Refusal | None:\n    return None\n", False),
    "adnotacja-pola-klasy": Odwolanie("class Wynik:\n    odmowa: Refusal | None = None\n", False),
    "adnotacja-zmiennej-modulu": Odwolanie("OSTATNIA: Refusal | None = None\n", False),
    "nawiasy-typu-w-aliasie-modulu": Odwolanie(
        "from collections.abc import Callable\n\nFabryka = Callable[[], Refusal | None]\n", False
    ),
    "unia-w-instrukcji-modulu": Odwolanie("Odmowa = Refusal | None\n", False),
    "except": Odwolanie("def obsluz() -> None:\n    try:\n        pass\n    except Refusal:\n        pass\n", False),
    "drugi-argument-isinstance": Odwolanie(
        "def jest_odmowa(blad: object) -> bool:\n    return isinstance(blad, Refusal)\n", False
    ),
    "drugi-argument-issubclass": Odwolanie(
        "def jest_odmowa(klasa: type) -> bool:\n    return issubclass(klasa, Refusal)\n", False
    ),
    "argument-exception-handler": Odwolanie(
        "from typing import Any\n\n\ndef zarejestruj(app: Any) -> None:\n    app.exception_handler(Refusal)\n", False
    ),
    "atrybut-modulu-w-adnotacji": Odwolanie(
        "from rozliczenia.centrum import refusal\n\n\ndef odmowa() -> refusal.Refusal | None:\n    return None\n", False
    ),
    "alias-importu-modulu-w-adnotacji": Odwolanie(
        "from rozliczenia.centrum import refusal as odmowy\n\n\ndef odmowa() -> odmowy.Refusal | None:\n    return None\n",
        False,
    ),
    "wywolanie": Odwolanie('def odmowa() -> Exception:\n    return Refusal(500, "Zdanie.", None)\n', True),
    "argument-wywolania": Odwolanie("from functools import partial\n\nFABRYKA = partial(Refusal, 500)\n", True),
    "przypisanie-do-nazwy-modulu": Odwolanie("KLASA = Refusal\n", True),
    "przypisanie-lokalne": Odwolanie("def klasa() -> type:\n    wynik = Refusal\n    return wynik\n", True),
    "element-kolekcji": Odwolanie("KLASY = (Refusal,)\n", True),
    "wartosc-domyslna": Odwolanie("def klasa(wybrana: type = Refusal) -> type:\n    return wybrana\n", True),
    "klasa-bazowa": Odwolanie("class Moja(Refusal):\n    pass\n", True),
    "wnetrze-lambdy": Odwolanie(
        "from collections.abc import Callable\n\nKLASA: Callable[[], type] = lambda: Refusal\n", True
    ),
    "wywolanie-w-nawiasach-w-instrukcji-modulu": Odwolanie(
        "from collections import defaultdict\n\nTABELA: defaultdict[str, int] = defaultdict(int)\n"
        "WYNIK = TABELA[repr(Refusal)]\n",
        True,
    ),
    "nawiasy-typu-w-ciele-funkcji": Odwolanie("def klasa() -> object:\n    return list[Refusal].__args__[0]\n", True),
    "unia-w-ciele-funkcji": Odwolanie("def klasa() -> object:\n    return Refusal | Refusal\n", True),
    "refusal-new-bez-status-code": Odwolanie("def odmowa() -> Exception:\n    return Refusal.__new__(Refusal)\n", True),
    "get-args-unii-w-ciele-funkcji": Odwolanie(
        "from typing import get_args\n\n\ndef klasa() -> object:\n    return get_args(Refusal | None)[0]\n", True
    ),
}


@pytest.mark.parametrize(
    ("kod", "jako_wartosc"), [pytest.param(*przypadek, id=opis) for opis, przypadek in ODWOLANIA_DO_ODMOWY.items()]
)
def test_odwolanie_do_odmowy_poza_katalogiem_przechodzi_tylko_jako_typ(tmp_path: Path, kod: str, jako_wartosc: bool) -> None:
    plik = tmp_path / "odwolanie.py"
    plik.write_text(_ODMOWA + kod, encoding="utf-8")

    assert _refusal_as_value(modul(plik)) is jako_wartosc


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


class DrogaDoZapisu(NamedTuple):
    kod: str
    odrzucenie: str


DROGI_DO_ZAPISU_USTAWIEN: Final = {
    "domknięcie trasy z uzupełnieniem listy do change(DEVICES, …)": DrogaDoZapisu(
        """\
from rozliczenia.centrum import device_forms
from rozliczenia.centrum.device_forms import DeviceEdit
from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import DEVICES, devices_for_dad_rules
from rozliczenia.quantity_engine import Component


def zapisz(settings: CentrumSettings, edit: DeviceEdit) -> Saved | Refused | NotSaved | KeptInPeriods:
    view = settings.quantity_rules()

    def applied(current: tuple[Component, ...]) -> tuple[Component, ...] | FieldProblem:
        completed = devices_for_dad_rules(current, view.source_rules, view.source_rules)
        if isinstance(completed, FieldProblem):
            return completed
        changed = device_forms.edited(completed, edit, frozenset())
        return changed if isinstance(changed, tuple | FieldProblem) else current

    return settings.change(DEVICES, applied)
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "funkcja trasy do change(RULES, …)": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import RULES


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings.change(RULES, lambda current: current[1:])
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "funkcja trasy z kluczami Historii do dawnego change_with_used_keys": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import DEVICES


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved:
    return settings.change_with_used_keys(DEVICES, lambda current, keys: current)
""",
        '"CentrumSettings" has no attribute "change_with_used_keys"',
    ),
    "funkcja trasy przez prywatne _with_used_keys": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import DEVICES


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved:
    return settings._with_used_keys(DEVICES, lambda current, keys: current)
""",
        "ruff SLF001",
    ),
    "funkcja trasy do zapisu Listy Urządzeń przez zmianę z Wydania": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings.history import ReleaseOrigin
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.centrum.settings.proposal import Edit, Proposal, ReleaseChange, ReleaseInputs
from rozliczenia.centrum.settings.quantity_rules import DEVICES
from rozliczenia.quantity_engine import Component


def zapisz(settings: CentrumSettings) -> None:
    def propose(inputs: ReleaseInputs[tuple[Component, ...]]) -> Proposal[tuple[Component, ...]]:
        return Edit(lambda current: current[1:])

    settings.apply_release_changes(
        (ReleaseChange("2026-11-trasa", DEVICES, propose),), lambda: ReleaseOrigin(release=None, commit=None)
    )
""",
        'Too many arguments for "apply_release_changes" of "CentrumSettings"',
    ),
    "funkcja trasy do change(FOLDERS, …) (Ustawienia)": DrogaDoZapisu(
        """\
from dataclasses import replace

from rozliczenia.centrum.settings.folders import FOLDERS
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings.change(FOLDERS, lambda current: replace(current, theme="light"))
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "funkcja trasy do change(EXCEPTIONS, …) (Kontrola ilości)": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_exceptions import EXCEPTIONS


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings.change(EXCEPTIONS, lambda current: current[1:])
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "funkcja trasy do change(WORKERS, …) (Wykonawcy)": DrogaDoZapisu(
        """\
from dataclasses import replace

from rozliczenia.centrum.settings import workers
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.workers import WORKERS, WorkerForm


def dodaj(settings: CentrumSettings, form: WorkerForm) -> Saved | Refused | NotSaved | KeptInPeriods:
    uzupelniony = replace(form, addresses=[*form.addresses, "biuro@example.com"])
    return settings.change(WORKERS, lambda current: workers.added(current, uzupelniony))
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "plik pary jako Any przez cast do dawnego change": DrogaDoZapisu(
        """\
from typing import Any, cast

from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import DEVICES


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings.change(cast(Any, DEVICES), lambda current: current)
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "plik pary jako Any przez getattr modułu do dawnego change": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings import quantity_rules
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings.change(getattr(quantity_rules, "DEVICES"), lambda current: current[1:])
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "plik Folderów z nazwą pliku pary do dawnego change (właściciel rozpoznaje parę po nazwie pliku)": DrogaDoZapisu(
        """\
from dataclasses import replace

from rozliczenia.centrum.settings.folders import FOLDERS
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.quantity_rules import DEVICES


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings.change(replace(FOLDERS, name=DEVICES.name), lambda current: current)
""",
        '"CentrumSettings" has no attribute "change"',
    ),
    "funkcja trasy w miejscu polecenia Wykonawców": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings.change_workers(lambda current: current)
""",
        'Argument 1 to "change_workers" of "CentrumSettings" has incompatible type',
    ),
    "funkcja trasy przez prywatne _by_dad": DrogaDoZapisu(
        """\
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.workers import WORKERS


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    return settings._by_dad(WORKERS, lambda current: current, undoes=None)
""",
        "ruff SLF001",
    ),
}

ZNANE_LUKI_POLECENIA_USTAWIEN: Final = {
    "trasa zmienia treść polecenia przed zapisem (typ widzi polecenie, nie jego treść)": """\
from rozliczenia.centrum.contract.quantity_rules import ComponentForm
from rozliczenia.centrum.device_forms import AddComponent
from rozliczenia.centrum.settings.owner import CentrumSettings, NotSaved, Refused, Saved


def dodaj(settings: CentrumSettings, form: ComponentForm) -> Saved | Refused | NotSaved:
    uzupelniony = form.model_copy(update={"other_spellings": [*form.other_spellings, "wizja"]})
    return settings.change_devices(AddComponent(uzupelniony))
""",
    "prywatna droga zapisu przez getattr z nazwą w napisie (SLF001 widzi tylko atrybut, getattr daje Any)": """\
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods, NotSaved, Refused, Saved
from rozliczenia.centrum.settings.workers import WORKERS


def zapisz(settings: CentrumSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
    zapis = getattr(settings, "_by_dad")
    wynik: Saved | Refused | NotSaved | KeptInPeriods = zapis(WORKERS, lambda current: current, undoes=None)
    return wynik
""",
    "drugi właściciel z własną zmianą z Wydania (konstruktor przyjmuje zmiany od każdego wołającego)": """\
from pathlib import Path

from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import Autostart
from rozliczenia.centrum.settings.history import ReleaseOrigin
from rozliczenia.centrum.settings.owner import CentrumSettings
from rozliczenia.centrum.settings.proposal import Edit, Proposal, ReleaseChange, ReleaseInputs
from rozliczenia.centrum.settings.quantity_rules import DEVICES
from rozliczenia.quantity_engine import Component
from rozliczenia.wall_clock import local_now
from rozliczenia.worker_periods import WorkerPeriods


def zapisz(config: Path, log: CentrumLog, autostart: Autostart, periods: WorkerPeriods) -> None:
    def propose(inputs: ReleaseInputs[tuple[Component, ...]]) -> Proposal[tuple[Component, ...]]:
        return Edit(lambda current: current[1:])

    CentrumSettings(
        config,
        log=log,
        now=local_now,
        pause=lambda _: None,
        autostart=autostart,
        periods=periods,
        column_names=lambda: {},
        release_changes=(ReleaseChange("2026-11-trasa", DEVICES, propose),),
        release_origin=lambda: ReleaseOrigin(release=None, commit=None),
    ).apply_release_changes()
""",
}


@wymaga_ruff_i_mypy
def test_funkcja_trasy_do_zapisu_ustawien_nie_przechodzi_mypy_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: droga.kod for opis, droga in DROGI_DO_ZAPISU_USTAWIEN.items()} | ZNANE_LUKI_POLECENIA_USTAWIEN
    pliki = zapisz(probki, tmp_path)

    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_luki.py")

    assert {
        opis: zgloszenia[opis]
        for opis, droga in DROGI_DO_ZAPISU_USTAWIEN.items()
        if not any(droga.odrzucenie in z for z in zgloszenia[opis])
    } == {}
    assert_znane_luki(
        {opis: zgloszenia[opis] for opis in ZNANE_LUKI_POLECENIA_USTAWIEN},
        "tests/test_komunikaty_expect.py (ZNANE_LUKI_POLECENIA_USTAWIEN)",
    )


def _refusal_as_value(module: ModuleType) -> bool:
    tree = drzewo(Path(str(module.__file__)))
    typed = {id(inner) for root in _type_positions(tree) for inner in _type_nodes(root)}
    return any(
        isinstance(node, ast.Name | ast.Attribute) and id(node) not in typed and _resolved(module, node) is refusal.Refusal
        for node in wezly(tree)
    )


def _type_nodes(root: ast.AST) -> Iterator[ast.AST]:
    if isinstance(root, ast.Call | ast.Lambda):
        return
    yield root
    for child in ast.iter_child_nodes(root):
        yield from _type_nodes(child)


def _type_positions(tree: ast.AST) -> Iterator[ast.expr]:
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
    return [
        function
        for module in modules
        for _, function in inspect.getmembers(module, inspect.isfunction)
        if function.__module__ == module.__name__ and function.__annotations__.get("return") in ("Message", Message)
    ]


def _resolved(module: ModuleType, node: ast.expr) -> object:
    match node:
        case ast.Name(id=name):
            return vars(module).get(name)
        case ast.Attribute(value=value, attr=attr):
            return getattr(_resolved(module, value), attr, None)
        case _:
            return None


def _caught_for_message(module: ModuleType, makers: Sequence[object]) -> Iterator[object]:
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


class BledyFabryk(NamedTuple):
    w_sygnaturach: set[object]
    zlapane: set[object]
    z_tekstem: set[str]


def _errors_for_messages(modules: Sequence[ModuleType], own: str) -> BledyFabryk:
    factories = _factories(modules)
    in_signatures = {
        kind for factory in factories for hint in typing.get_type_hints(factory).values() for kind in _variants(hint)
    }
    caught = {kind for module in modules for kind in _caught_for_message(module, [*factories, StopError])}
    errors = {
        kind
        for kind in in_signatures | caught
        if inspect.isclass(kind) and issubclass(kind, BaseException) and kind.__module__.startswith(own)
    }
    with_text = {
        f"{error.__name__}.{parameter}"
        for error in errors
        if inspect.isfunction(error.__init__)
        for parameter, hint in typing.get_type_hints(error.__init__).items()
        if str in _variants(hint)
    } | {f"{error.__name__}.args" for error in errors & in_signatures if not inspect.isfunction(error.__init__)}
    return BledyFabryk(in_signatures, caught, with_text)


def test_blad_ktory_proces_tlumaczy_na_komunikat_niesie_fakty_a_nie_tekst() -> None:
    bledy = _errors_for_messages(_engine_modules(), "rozliczenia.")

    assert bledy.z_tekstem == set()
    assert {WorkbookError, PeriodFolderError, PeriodFolderLookupError} <= bledy.w_sygnaturach
    assert {PeriodFolderInaccessible, WorkbookSaveError} <= bledy.zlapane


_BLAD_Z_TEKSTEM = """\
class Blad(Exception):
    def __init__(self, tekst: str) -> None:
        super().__init__(tekst)
"""
_BLAD_BEZ_INIT = "class Blad(Exception):\n    pass\n"
_FABRYKA_BLEDU = "\n\ndef komunikat(blad: Blad) -> Message:\n    raise NotImplementedError\n"
_FABRYKA = "\n\ndef komunikat() -> Message:\n    raise NotImplementedError\n"
_OBSLUGA = "\n\ndef obsluz() -> Message:\n    try:\n        raise Blad(\"Zdanie.\")\n"
BLEDY_Z_TEKSTEM: Final = {
    "parametr-str-bledu-z-sygnatury-fabryki": (_BLAD_Z_TEKSTEM + _FABRYKA_BLEDU, {"Blad.tekst"}),
    "parametr-unii-ze-str": (_BLAD_Z_TEKSTEM.replace("tekst: str", "tekst: str | None") + _FABRYKA_BLEDU, {"Blad.tekst"}),
    "blad-z-except-ktorego-obsluga-wola-fabryke": (
        _BLAD_Z_TEKSTEM + _FABRYKA + _OBSLUGA + "    except Blad:\n        return komunikat()\n",
        {"Blad.tekst"},
    ),
    "blad-z-except-ktorego-obsluga-tworzy-stoperror": (
        _BLAD_Z_TEKSTEM + _OBSLUGA + "    except Blad as blad:\n        raise StopError(None) from blad\n",
        {"Blad.tekst"},
    ),
    "blad-bez-wlasnego-init-w-sygnaturze-fabryki": (_BLAD_BEZ_INIT + _FABRYKA_BLEDU, {"Blad.args"}),
    "granica-pole-ustawione-bez-parametru": (
        "class Blad(Exception):\n    def __init__(self) -> None:\n        super().__init__()\n"
        "        self.tekst = \"Zdanie dla taty.\"\n" + _FABRYKA_BLEDU,
        set(),
    ),
    "granica-parametr-bez-adnotacji": (_BLAD_Z_TEKSTEM.replace("tekst: str", "tekst") + _FABRYKA_BLEDU, set()),
    "granica-except-na-zmiennej": (
        _BLAD_Z_TEKSTEM + "\n\nBLEDY = (Blad,)" + _FABRYKA + _OBSLUGA + "    except BLEDY:\n        return komunikat()\n",
        set(),
    ),
    "granica-match-na-bledzie-zlapanym-przez-except-baseexception": (
        _BLAD_Z_TEKSTEM
        + _FABRYKA
        + _OBSLUGA
        + "    except BaseException as blad:\n        match blad:\n            case Blad():\n"
        "                return komunikat()\n        raise\n",
        set(),
    ),
    "granica-tekst-w-dataclass-faktu": (
        "from dataclasses import dataclass\n\n\n@dataclass(frozen=True)\nclass Fakt:\n    tekst: str\n\n\n"
        "class Blad(Exception):\n    def __init__(self, fakt: Fakt) -> None:\n        super().__init__(fakt)\n"
        + _FABRYKA_BLEDU,
        set(),
    ),
    "granica-blad-bez-wlasnego-init-tylko-w-except-ktory-podaje-fabryce-jego-tekst": (
        _BLAD_BEZ_INIT
        + "\n\ndef komunikat(tekst: str) -> Message:\n    raise NotImplementedError\n"
        + _OBSLUGA
        + "    except Blad as blad:\n        return komunikat(str(blad))\n",
        set(),
    ),
}


@pytest.mark.parametrize(("kod", "z_tekstem"), [pytest.param(*przypadek, id=opis) for opis, przypadek in BLEDY_Z_TEKSTEM.items()])
def test_blad_z_tekstem_widzi_kazda_droge_bledu_do_komunikatu_a_granice_przechodza(
    tmp_path: Path, kod: str, z_tekstem: set[str]
) -> None:
    plik = tmp_path / "bledy_procesu.py"
    plik.write_text("from rozliczenia.message import Message, StopError\n\n\n" + kod, encoding="utf-8")
    probka = modul(plik)

    assert _errors_for_messages([probka], probka.__name__).z_tekstem == z_tekstem


def test_komunikaty_ktore_widzi_tata_odpowiadaja_plikowi_expect() -> None:
    assert_expected(_rendered(), ROOT / "tests" / "expected" / "komunikaty.txt")


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
    "Zapisz": "frontend/src/pages/settings/setting-row.tsx",
    "Usuń składnik": "frontend/src/pages/settings/devices-section.tsx",
}
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
    "raport": "słowo tematu Raportu wykonawcy (SUBJECT_WORD), nie napis UI",
    "2*wizja": "zapis składnika z gwiazdką w próbce, dana pliku, nie napis UI",
    "schema_version": "nazwa pola pliku legendy czynności w próbce, nie napis UI",
    "Anna Przykład": "nazwa Wykonawcy z Listy Wykonawców w próbce, dana pliku, nie napis UI",
    "Jan Testowy": "nazwa Wykonawcy z Listy Wykonawców w próbce, dana pliku, nie napis UI",
    "Adam Próbny": "nazwa Wykonawcy z Listy Wykonawców w próbce, dana pliku, nie napis UI",
}


def _ui_text(text: str) -> re.Pattern[str]:
    words = r"\s+".join(re.escape(word) for word in text.split())
    literal = f'"{words}"'
    forms = (
        rf"[>}}]\s*{words}\s*[<{{]",
        rf"(?<![\w-])label=\{{?{literal}\}}?",
        rf"(?<![\w-])label:\s*{literal}",
    )
    return re.compile("|".join(forms))


def test_napis_przycisku_cytowany_w_komunikacie_stoi_w_ui_centrum() -> None:
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


NAPISY_W_PLIKU_UI: Final = {
    "dziecko-elementu-jsx": ("Kontynuuj", "<Button>Kontynuuj</Button>", True),
    "dziecko-elementu-jsx-po-ikonie": ("Kontynuuj", "<Button>\n  {ikona}\n  Kontynuuj\n</Button>", True),
    "dziecko-elementu-jsx-zlamane-w-linii": ("Uzupełnij i zapisz", "<Button>\n  Uzupełnij i\n  zapisz\n</Button>", True),
    "prop-label": ("Kontynuuj", '<Pole label="Kontynuuj" />', True),
    "prop-label-w-klamrach": ("Kontynuuj", '<Pole label={"Kontynuuj"} />', True),
    "wlasciwosc-label-obiektu-napisow": ("Kontynuuj", 'const NAPISY = { label: "Kontynuuj" }', True),
    "granica-prop-aria-label": ("Kontynuuj", '<Button aria-label="Kontynuuj" />', False),
    "granica-napis-w-zdaniu": ("Kontynuuj", "<p>Kliknij Kontynuuj, aby przejść dalej.</p>", False),
    "granica-prop-z-dluzszym-napisem": ("Kontynuuj", '<Pole label="Kontynuuj teraz" />', False),
    "granica-prop-w-pojedynczym-cudzyslowie": ("Kontynuuj", "<Pole label='Kontynuuj' />", False),
    "granica-galaz-warunku": ("Diagnoza", '{gotowe ? "Kontynuuj" : "Diagnoza"}', False),
}


@pytest.mark.parametrize(
    ("napis", "tsx", "pokazuje"), [pytest.param(*przypadek, id=opis) for opis, przypadek in NAPISY_W_PLIKU_UI.items()]
)
def test_napis_przycisku_stoi_w_pliku_ui_w_kazdej_postaci_przycisku_a_w_innej_nie(napis: str, tsx: str, pokazuje: bool) -> None:
    assert bool(_ui_text(napis).search(tsx)) is pokazuje


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
