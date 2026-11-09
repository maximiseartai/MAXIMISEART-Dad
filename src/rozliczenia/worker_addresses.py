"""Plik adresów Wykonawców: z których adresów który Wykonawca wysyła Raporty wykonawcy (ADR 0028).

Plik ``config/adresy-wykonawcow.yaml`` poza Gitem prowadzi Maks w kształcie
``{schema_version: 1, wykonawcy: {login: [adres, ...]}}``. Login to identyfikator z ``WYKONAWCA``, który musi być w
Konfiguracji wykonawców. Złamaną regułę ``load`` zgłasza jako ``AddressesError`` z faktem, bez zdania dla taty.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import yaml

from .file_state import file_state
from .text import normalize_text
from .worker_reports import Login, SenderAddress, WorkerAddresses

__all__ = ["WORKER_ADDRESSES_FILE", "AddressesError", "AddressesProblem", "UnknownLogin", "load"]

WORKER_ADDRESSES_FILE: Final = "adresy-wykonawcow.yaml"


@dataclass(frozen=True)
class UnknownLogin:
    """Login z pliku adresów, którego nie ma w Konfiguracji wykonawców."""

    login: Login


AddressesProblem = (
    Literal[
        "missing",
        "inaccessible",
        "not_utf8",
        "not_yaml",
        "unsupported_version",
        "no_workers",
        "not_address",
        "repeated_address",
    ]
    | UnknownLogin
)
"""Brak pliku (``missing``), plik, którego system nie oddał (``inaccessible``), zapis w innym kodowaniu niż UTF-8
(``not_utf8``), zły YAML (``not_yaml``), plik bez ``schema_version: 1`` (``unsupported_version``, także plik, który nie
jest mapą), brak Wykonawców pod ``wykonawcy`` (``no_workers``), login bez listy adresów albo wartość, która nie jest
jednym adresem ``lokalna@domena`` (``not_address``), ten sam adres dwa razy (``repeated_address``) i login spoza
Konfiguracji wykonawców (``UnknownLogin``)."""


class AddressesError(Exception):
    """Pliku adresów nie da się użyć; ``problem`` mówi dlaczego, bez ścieżki pliku, adresu i zdania dla taty."""

    def __init__(self, problem: AddressesProblem) -> None:
        self.problem: AddressesProblem = problem


def load(path: Path, *, workers: Mapping[str, str]) -> WorkerAddresses:
    """Adresy z pliku ``path``; ``workers`` to Konfiguracja wykonawców (``load_worker_mapping``).

    Login porównuje ``normalize_text``, a adres ``casefold``, więc ``Jan.Testowy`` i ``jan.testowy`` to jeden Wykonawca.
    """

    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise AddressesError("missing" if file_state(path) == "missing" else "inaccessible") from error
    except UnicodeDecodeError as error:
        raise AddressesError("not_utf8") from error
    except yaml.YAMLError as error:
        raise AddressesError("not_yaml") from error

    if not isinstance(content, dict) or type(content.get("schema_version")) is not int or content["schema_version"] != 1:
        raise AddressesError("unsupported_version")
    entries = content.get("wykonawcy")
    if not isinstance(entries, dict) or not entries:
        raise AddressesError("no_workers")

    logins: dict[SenderAddress, Login] = {}
    for key, values in entries.items():
        login = Login(normalize_text(key))
        if login not in workers:
            raise AddressesError(UnknownLogin(login))
        if not isinstance(values, list) or not values:
            raise AddressesError("not_address")
        for value in values:
            address = SenderAddress.of(value) if isinstance(value, str) else None
            if address is None or address.shown() != value.strip().casefold():
                raise AddressesError("not_address")
            if address in logins:
                raise AddressesError("repeated_address")
            logins[address] = login
    return WorkerAddresses(logins)
