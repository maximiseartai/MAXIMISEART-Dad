"""Lista Wykonawców w pliku ``wykonawcy.yaml`` (schemat 1): Wykonawcy i to, co tata ma rozstrzygnąć po przeniesieniu
starych plików (``do_rozstrzygniecia``).

Kształt pliku sprawdza ``parse`` (mapa, schemat, znane pola, typy), a reguły Listy Wykonawców ``WorkerList.of``, ta sama
budowa co w silniku. Brak pliku to pusta lista. Zdanie złego ustawienia nie ma nazwy, loginu ani adresu, bo trafia do
Historii Ustawień i do Zgłoszenia; miejsce mówi pole (``wykonawcy[2].adresy[0]``), złożone tylko ze znanych nazw pól i
numerów (``FieldPath``), a nieznane pole jego numer, bo stary kształt wpisu (``login: Nazwa``) ma login w miejscu pola.

Klucz Historii wpisu to ``wykonawcy[<login>]`` z jednym z jego loginów, a wartość przed i po to cały wpis; wpisy przed i
po paruje wspólny login, bo login należy do jednego Wykonawcy. Zgłoszenie i Logi Centrum dostają tylko, co się zmieniło,
bez loginu, nazwy i adresu (D4 projektu Ustawień).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Final, Literal, assert_never

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import FieldName, FieldPath, FieldProblem, KeyChange, SettingsFile, settings_yaml
from rozliczenia.worker_list import (
    AddressesNotMoved,
    UnmatchedLogin,
    Unresolved,
    Worker,
    WorkerEntry,
    WorkerList,
    WorkerListProblem,
)
from rozliczenia.worker_reports import Login, SenderAddress

WORKERS_FILE: Final = "wykonawcy.yaml"
"""Plik Listy Wykonawców w ``config``; czyta go i pisze tylko ``rozliczenia.centrum.settings``."""

SECTION: Final = "wykonawcy"
_SCHEMA_VERSION: Final = 1
WORKERS_KEY: Final = "wykonawcy"
UNRESOLVED_KEY: Final = "do_rozstrzygniecia"
_TOP: Final = frozenset({"schema_version", WORKERS_KEY, UNRESOLVED_KEY})
_NAME: Final = "nazwa"
_LOGINS: Final = "loginy"
_ADDRESSES: Final = "adresy"
_ACTIVE: Final = "aktywny"
_REMINDERS: Final = "przypomnienia"
_ENTRY: Final = (_NAME, _LOGINS, _ADDRESSES, _ACTIVE, _REMINDERS)
_LOGIN, _REASON, _SENTENCE = "login", "powod", "zdanie"
UnresolvedReason = Literal["login_bez_wykonawcy", "adresy_nieprzeniesione"]
_UNMATCHED: Final[UnresolvedReason] = "login_bez_wykonawcy"
_NOT_MOVED: Final[UnresolvedReason] = "adresy_nieprzeniesione"
_UNRESOLVED_FIELDS: Final[Mapping[UnresolvedReason, frozenset[str]]] = {
    _UNMATCHED: frozenset({_LOGIN, _ADDRESSES, _REASON}),
    _NOT_MOVED: frozenset({_SENTENCE, _REASON}),
}
_UNRESOLVED_HISTORY_KEY: Final = f"{SECTION}.{UNRESOLVED_KEY}"

Document = dict[str, object]


def parse(data: bytes | None) -> WorkerList | FieldProblem:
    """Lista Wykonawców z bajtów pliku; ``None`` (brak pliku) to pusta lista, zła treść to pierwszy problem."""

    if data is None:
        return WorkerList(())
    try:
        document = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(WORKERS_FILE, messages.MAKS_FIXES))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(WORKERS_FILE, messages.MAKS_FIXES))
    if not isinstance(document, dict):
        return FieldProblem(None, messages.damaged(WORKERS_FILE, messages.MAKS_FIXES))
    if document.get("schema_version") != _SCHEMA_VERSION:
        return FieldProblem(None, messages.other_schema(WORKERS_FILE, messages.MAKS_FIXES))
    unknown = next((place for place, key in enumerate(document, 1) if key not in _TOP), None)
    if unknown is not None:
        return FieldProblem(None, messages.unknown_key(WORKERS_FILE, unknown, messages.MAKS_FIXES))
    entries = _entries(document.get(WORKERS_KEY, []))
    if isinstance(entries, FieldProblem):
        return entries
    unresolved = _unresolved(document.get(UNRESOLVED_KEY, []))
    if isinstance(unresolved, FieldProblem):
        return unresolved
    built = WorkerList.of(entries, unresolved)
    if isinstance(built, WorkerListProblem):
        return _problem(built)
    return built


def _entries(value: object) -> list[WorkerEntry] | FieldProblem:
    if not isinstance(value, list):
        return _bad(FieldPath(WORKERS_KEY))
    entries: list[WorkerEntry] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return _bad(FieldPath(WORKERS_KEY, index))
        unknown = next((place for place, key in enumerate(item, 1) if key not in _ENTRY), None)
        if unknown is not None:
            return FieldProblem(FieldPath(WORKERS_KEY, index), messages.worker_unknown_key(WORKERS_FILE, index + 1, unknown))
        name = item.get(_NAME, "")
        if not isinstance(name, str):
            return FieldProblem(FieldPath(WORKERS_KEY, index, _NAME), messages.worker_name_empty())
        logins = _texts(item.get(_LOGINS, []), WORKERS_KEY, index, _LOGINS)
        if isinstance(logins, FieldProblem):
            return logins
        addresses = _texts(item.get(_ADDRESSES, []), WORKERS_KEY, index, _ADDRESSES)
        if isinstance(addresses, FieldProblem):
            return addresses
        active, reminders = item.get(_ACTIVE, True), item.get(_REMINDERS, True)
        if not isinstance(active, bool):
            return _bad(FieldPath(WORKERS_KEY, index, _ACTIVE))
        if not isinstance(reminders, bool):
            return _bad(FieldPath(WORKERS_KEY, index, _REMINDERS))
        entries.append(WorkerEntry(logins, name, addresses, active, reminders))
    return entries


def _bad(place: FieldPath) -> FieldProblem:
    return FieldProblem(place, messages.bad_field(WORKERS_FILE, place, messages.MAKS_FIXES))


def _texts(value: object, first: FieldName, *rest: FieldName | int) -> list[str] | FieldProblem:
    """Lista tekstów pola w miejscu ``first, *rest``; liczba albo pusta wartość w liście to zły wpis tego miejsca."""

    if not isinstance(value, list):
        return _bad(FieldPath(first, *rest))
    for index, item in enumerate(value):
        if not isinstance(item, str):
            return _bad(FieldPath(first, *rest, index))
    return list(value)


def _unresolved(value: object) -> list[Unresolved] | FieldProblem:
    if not isinstance(value, list):
        return _bad(FieldPath(UNRESOLVED_KEY))
    found: list[Unresolved] = []
    for index, item in enumerate(value):
        place = FieldPath(UNRESOLVED_KEY, index)
        reason = next((known for known in _UNRESOLVED_FIELDS if isinstance(item, dict) and item.get(_REASON) == known), None)
        if not isinstance(item, dict) or reason is None or set(item) != _UNRESOLVED_FIELDS[reason]:
            return _bad(place)
        if reason == _NOT_MOVED:
            sentence = item[_SENTENCE]
            if not isinstance(sentence, str):
                return _bad(place)
            found.append(AddressesNotMoved(sentence))
            continue
        login, addresses = item[_LOGIN], _texts(item[_ADDRESSES], UNRESOLVED_KEY, index, _ADDRESSES)
        if isinstance(addresses, FieldProblem):
            return addresses
        parsed = [SenderAddress.of(address) for address in addresses]
        if not isinstance(login, str) or not login.strip() or None in parsed:
            return _bad(place)
        found.append(UnmatchedLogin(Login(login.strip()), tuple(address for address in parsed if address is not None)))
    return found


def _problem(problem: WorkerListProblem) -> FieldProblem:
    item = () if problem.item is None else (problem.item,)
    return FieldProblem(FieldPath(WORKERS_KEY, problem.worker, problem.part, *item), _SENTENCES[problem.kind]())


_SENTENCES: Final = {
    "no_login": messages.worker_without_login,
    "empty_login": messages.worker_login_empty,
    "repeated_login": messages.worker_login_repeated,
    "empty_name": messages.worker_name_empty,
    "invalid_name": messages.worker_name_invalid,
    "too_long_name": messages.worker_name_too_long,
    "same_file": messages.worker_same_file,
    "not_address": messages.worker_address_invalid,
    "repeated_address": messages.worker_address_repeated,
}


def dump(workers: WorkerList) -> str:
    return _dump([_entry(worker) for worker in workers.workers], [_unresolved_entry(item) for item in workers.unresolved])


def _entry(worker: Worker) -> Document:
    return {
        _NAME: worker.name,
        _LOGINS: list(worker.logins),
        _ADDRESSES: [address.shown() for address in worker.addresses],
        _ACTIVE: worker.active,
        _REMINDERS: worker.reminders,
    }


def _unresolved_entry(item: Unresolved) -> Document:
    match item:
        case UnmatchedLogin(login=login, addresses=addresses):
            return {_LOGIN: login, _ADDRESSES: [address.shown() for address in addresses], _REASON: _UNMATCHED}
        case AddressesNotMoved(sentence=sentence):
            return {_REASON: _NOT_MOVED, _SENTENCE: sentence}
        case _:
            assert_never(item)


def diff(before: WorkerList, after: WorkerList) -> tuple[KeyChange, ...]:
    """Klucz na każdy dodany, usunięty albo zmieniony wpis (w kolejności listy po zmianie, potem usunięte) i jeden na
    zmienione ``do_rozstrzygniecia``."""

    changes: list[KeyChange] = []
    paired: set[int] = set()
    for worker in after.workers:
        index = _sharing(before.workers, worker.logins)
        old = None if index is None else before.workers[index]
        if index is not None:
            paired.add(index)
        if old != worker:
            changes.append(KeyChange(_key((old or worker).logins[0]), _text(old), _text(worker)))
    changes += [
        KeyChange(_key(worker.logins[0]), _text(worker), None)
        for index, worker in enumerate(before.workers)
        if index not in paired
    ]
    if before.unresolved != after.unresolved:
        changes.append(KeyChange(_UNRESOLVED_HISTORY_KEY, _unresolved_text(before), _unresolved_text(after)))
    return tuple(changes)


def _sharing(workers: Sequence[Worker], logins: Sequence[Login]) -> int | None:
    return next((index for index, worker in enumerate(workers) if set(worker.logins) & set(logins)), None)


def _key(login: str) -> str:
    return f"{SECTION}[{login}]"


def _text(worker: Worker | None) -> str | None:
    return None if worker is None else json.dumps(_entry(worker), ensure_ascii=False)


def _unresolved_text(workers: WorkerList) -> str | None:
    if not workers.unresolved:
        return None
    return json.dumps([_unresolved_entry(item) for item in workers.unresolved], ensure_ascii=False)


def restore(workers: WorkerList, changes: tuple[KeyChange, ...]) -> WorkerList:
    """``workers`` z każdym wpisem ``changes`` ustawionym na wpis sprzed zmiany: wpis z loginem z klucza albo z wpisu
    przed i po zmianie znika, a wpis sprzed zmiany wraca na jego miejsce (usunięty na koniec). Nieznany klucz zostaje bez
    zmian; listę sprawdza właściciel jak każdą zmianę."""

    entries = [_entry(worker) for worker in workers.workers]
    unresolved = [_unresolved_entry(item) for item in workers.unresolved]
    for change in changes:
        if change.key == _UNRESOLVED_HISTORY_KEY:
            unresolved = _documents(change.before)
            continue
        if not (change.key.startswith(f"{SECTION}[") and change.key.endswith("]")):
            continue
        logins = {change.key[len(SECTION) + 1 : -1]} | _logins(change.before) | _logins(change.after)
        at = next((index for index, entry in enumerate(entries) if logins & set(_listed(entry))), None)
        if at is not None:
            del entries[at]
        before = _documents(change.before)
        if before:
            entries.insert(len(entries) if at is None else at, before[0])
    restored = parse(_dump(entries, unresolved).encode("utf-8"))
    return workers if isinstance(restored, FieldProblem) else restored


def _dump(entries: list[Document], unresolved: list[Document]) -> str:
    document: Document = {"schema_version": _SCHEMA_VERSION, WORKERS_KEY: entries}
    if unresolved:
        document[UNRESOLVED_KEY] = unresolved
    return settings_yaml(document)


def _documents(text: str | None) -> list[Document]:
    if text is None:
        return []
    value = json.loads(text)
    return [item for item in (value if isinstance(value, list) else [value]) if isinstance(item, dict)]


def _logins(text: str | None) -> set[str]:
    return {login for entry in _documents(text) for login in _listed(entry)}


def _listed(entry: Document) -> list[str]:
    logins = entry.get(_LOGINS)
    return [login for login in logins if isinstance(login, str)] if isinstance(logins, list) else []


def reported(change: KeyChange) -> str:
    """Zmiana w Zgłoszeniu bez loginu, nazwy i adresu: dodany, usunięty albo zmieniony Wykonawca z nazwami pól."""

    if change.key == _UNRESOLVED_HISTORY_KEY:
        return f"{SECTION}.{UNRESOLVED_KEY}: {len(_documents(change.before))} → {len(_documents(change.after))}"
    before, after = _documents(change.before), _documents(change.after)
    if not before:
        return "dodano Wykonawcę"
    if not after:
        return "usunięto Wykonawcę"
    fields = [field for field in _ENTRY if before[0].get(field) != after[0].get(field)]
    return f"zmieniono Wykonawcę (pola: {', '.join(fields)})"


def logged(key: str) -> str:
    """Klucz w Logach Centrum: sekcja bez loginu z klucza wpisu."""

    return SECTION if key.startswith(f"{SECTION}[") else key


WORKERS: Final = SettingsFile(
    name=WORKERS_FILE,
    parse=parse,
    dump=dump,
    diff=diff,
    restore=restore,
    reported=reported,
    logged=logged,
    default=WorkerList(()),
)
