from __future__ import annotations

from pathlib import Path
from typing import Final

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.proposal import Edit, Later, Nothing, Proposal, Refuse, ReleaseChange, ReleaseInputs, Waiting
from rozliczenia.centrum.settings.workers import WORKERS, WORKERS_FILE
from rozliczenia.file_state import file_state
from rozliczenia.text import normalize_text
from rozliczenia.worker_list import AddressesNotMoved, UnmatchedLogin, Unresolved, WorkerEntry, WorkerList, WorkerListProblem
from rozliczenia.worker_reports import Login, SenderAddress

OLD_MAPPING_FILE: Final = "worker_mapping.yaml"
OLD_ADDRESSES_FILE: Final = "adresy-wykonawcow.yaml"


class _Unreadable(Exception):
    pass


def propose(inputs: ReleaseInputs[WorkerList]) -> Proposal[WorkerList]:
    config = inputs.config
    if file_state(config / WORKERS_FILE) != "missing":
        return Nothing()
    try:
        mapping = _mapping(config / OLD_MAPPING_FILE)
        addresses = _addresses(config / OLD_ADDRESSES_FILE)
    except _Unreadable:
        return Later("stary plik Wykonawców jest, ale system nie daje go teraz czytać")
    if isinstance(mapping, str):
        return Refuse(messages.workers_not_moved(OLD_MAPPING_FILE, mapping))
    unresolved: list[Unresolved] = []
    if isinstance(addresses, str):
        unresolved.append(AddressesNotMoved(messages.addresses_not_moved(OLD_ADDRESSES_FILE, addresses)))
        addresses = {}
    entries = [
        WorkerEntry([login], name, [address.shown() for address in addresses.get(login, ())]) for login, name in mapping.items()
    ]
    unresolved += [UnmatchedLogin(login, found) for login, found in addresses.items() if login not in mapping]
    built = WorkerList.of(entries, unresolved)
    if isinstance(built, WorkerListProblem):
        return Refuse(messages.workers_not_moved(OLD_MAPPING_FILE, "Wykonawcy z adresami łamią reguły Listy Wykonawców"))
    return Edit(lambda _current: built, undoable=False)


def _old_files(config: Path) -> bool:
    return any(file_state(config / name) != "missing" for name in (OLD_MAPPING_FILE, OLD_ADDRESSES_FILE))


def _document(path: Path) -> object | None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("plik nie jest zapisany w UTF-8") from error
    except OSError as error:
        if file_state(path) == "missing":
            return None
        raise _Unreadable from error
    try:
        document: object = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError("plik nie jest poprawnym YAML") from error
    return document


def _mapping(path: Path) -> dict[Login, str] | str:
    try:
        document = _document(path)
    except ValueError as error:
        return str(error)
    if document is None:
        return {}
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        return "plik nie ma schema_version: 1"
    workers = document.get("workers")
    if not isinstance(workers, dict) or not workers:
        return "plik nie ma Wykonawców pod workers"
    mapping: dict[Login, str] = {}
    for login, name in workers.items():
        if not isinstance(login, str) or not isinstance(name, str):
            return "identyfikator albo nazwa Wykonawcy nie jest tekstem"
        if Login(normalize_text(login)) in mapping:
            return "identyfikator Wykonawcy stoi dwa razy"
        mapping[Login(normalize_text(login))] = name
    return mapping


def _addresses(path: Path) -> dict[Login, tuple[SenderAddress, ...]] | str:
    try:
        document = _document(path)
    except ValueError as error:
        return str(error)
    if document is None:
        return {}
    if not isinstance(document, dict) or type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        return "plik nie ma schema_version: 1"
    entries = document.get("wykonawcy")
    if not isinstance(entries, dict) or not entries:
        return "plik nie ma Wykonawców pod wykonawcy"
    found: dict[Login, list[SenderAddress]] = {}
    seen: set[SenderAddress] = set()
    for key, values in entries.items():
        if not isinstance(values, list) or not values:
            return "któryś Wykonawca nie ma listy adresów"
        for value in values:
            address = SenderAddress.of(value) if isinstance(value, str) else None
            if address is None or not isinstance(value, str) or address.shown() != value.strip().casefold():
                return "któryś wpis nie jest adresem"
            if address in seen:
                return "ten sam adres stoi dwa razy"
            seen.add(address)
            found.setdefault(Login(normalize_text(key)), []).append(address)
    return {login: tuple(addresses) for login, addresses in found.items()}


CHANGE: Final = ReleaseChange(
    id="2026-11-lista-wykonawcow",
    file=WORKERS,
    propose=propose,
    refused_absent=messages.worker_list_not_created(),
    waiting=Waiting(messages.worker_list_waiting(), _old_files),
)
