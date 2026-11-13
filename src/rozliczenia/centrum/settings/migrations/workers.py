"""Przeniesienie Konfiguracji wykonawców (``worker_mapping.yaml``) i adresów Wykonawców (``adresy-wykonawcow.yaml``) do
Listy Wykonawców (``wykonawcy.yaml``): zmiana z Wydania ``2026-11-lista-wykonawcow`` (ADR 0032).

Czego nie da się pewnie przenieść, nie znika po cichu: adresy przy loginie spoza Konfiguracji i stary plik adresów,
którego nie da się użyć, trafiają do ``do_rozstrzygniecia`` dla taty, a Konfiguracja, której nie da się użyć, to zmiana
odrzucona z powodem w Historii Ustawień. Plik, którego system nie daje teraz czytać (np. trzyma go antywirus), to
``Later``: treść jest nieznana, a nie zła, więc zmiana wraca przy następnym starcie. Stare pliki zostają w ``config``.

Bez żadnego starego pliku edycja daje pustą listę, czyli tę samą wartość co brak pliku, więc właściciel nie pisze pliku
ani wiersza Historii. Reguły odczytu starych plików są tu, bo to ich jedyny czytelnik: ``schema_version: 1``, mapa ``workers`` login → nazwa
i mapa ``wykonawcy`` login → lista adresów, login po ``normalize_text``, adres po ``casefold``. Reguły nazwy i adresu
sprawdza potem ``WorkerList.of``, ta sama budowa co przy każdym zapisie listy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import yaml

from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.proposal import Edit, Later, Nothing, Proposal, Refuse, ReleaseChange, ReleaseInputs
from rozliczenia.centrum.settings.workers import WORKERS, WORKERS_FILE
from rozliczenia.file_state import file_state
from rozliczenia.text import normalize_text
from rozliczenia.worker_list import AddressesNotMoved, UnmatchedLogin, Unresolved, WorkerEntry, WorkerList, WorkerListProblem
from rozliczenia.worker_reports import Login, SenderAddress

OLD_MAPPING_FILE: Final = "worker_mapping.yaml"
OLD_ADDRESSES_FILE: Final = "adresy-wykonawcow.yaml"


class _Unreadable(Exception):
    """Starego pliku nie dało się teraz przeczytać, choć jest."""


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


def _document(path: Path) -> object | None:
    """Treść YAML starego pliku; ``None``: pliku nie ma. ``_Unreadable``, gdy system go nie oddaje, a ``ValueError`` ze
    zdaniem, gdy to nie jest tekst YAML."""

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
    """Login → nazwa ze starej Konfiguracji wykonawców (pusta, gdy pliku nie ma) albo powód, dla którego nie da się jej
    użyć, bez nazwy i loginu."""

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
    """Login → adresy ze starego pliku adresów (pusty, gdy pliku nie ma) albo powód, dla którego nie da się go użyć, bez
    adresu i loginu; login nie musi być w Konfiguracji wykonawców."""

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


CHANGE: Final = ReleaseChange(id="2026-11-lista-wykonawcow", file=WORKERS, propose=propose)
"""Lista Wykonawców ze starych plików, bez „Cofnij”: cofnięcie zostawiłoby Centrum bez Wykonawców (D8)."""
