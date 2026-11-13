"""Lista Wykonawców (ADR 0032): każdy Wykonawca z loginami z kolumny ``WYKONAWCA``, nazwą w Rozliczeniu pracownika,
adresami Raportów wykonawcy i dwoma przełącznikami, wspólna dla Przebiegu rozliczeń, Przygotowania pliku zbiorczego,
Wpisania raportów i Przypomnień o raporcie.

Listę buduje tylko ``WorkerList.of`` i sprawdza przy tym wszystkie reguły w stałej kolejności, więc lista, którą ma
proces, zawsze je spełnia. Plik ``wykonawcy.yaml`` czyta i pisze właściciel Ustawień Centrum
(``rozliczenia.centrum.settings``); ten moduł nie zna pliku ani zdań dla taty, bo czyta go silnik, który Centrum nie
importuje. Złamaną regułę zgłasza jako ``WorkerListProblem`` z miejscem i rodzajem, bez nazwy, loginu i adresu.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from .period_folder import check_worker_name
from .text import normalize_text
from .worker_reports import Login, SenderAddress, WorkerAddresses

__all__ = [
    "AddressesNotMoved",
    "UnmatchedLogin",
    "Unresolved",
    "Worker",
    "WorkerEntry",
    "WorkerList",
    "WorkerListProblem",
]


@dataclass(frozen=True)
class Worker:
    """Wykonawca z Listy Wykonawców; ``active=False``: Nieaktywny Wykonawca, ``reminders``: dostaje Przypomnienia o
    raporcie, gdy jest aktywny."""

    logins: tuple[Login, ...]
    name: str
    addresses: tuple[SenderAddress, ...]
    active: bool
    reminders: bool


@dataclass(frozen=True)
class UnmatchedLogin:
    """Do rozstrzygnięcia przez tatę: adresy przy loginie, którego nie miał żaden Wykonawca starej Konfiguracji, więc
    przeniesienie nie zgaduje, czyje są."""

    login: Login
    addresses: tuple[SenderAddress, ...]


@dataclass(frozen=True)
class AddressesNotMoved:
    """Do rozstrzygnięcia przez tatę: starego pliku adresów nie dało się przeczytać, więc Wykonawcy przeszli bez adresów;
    ``sentence`` mówi dlaczego, bez adresu i loginu."""

    sentence: str


Unresolved = UnmatchedLogin | AddressesNotMoved


@dataclass(frozen=True)
class WorkerEntry:
    """Wpis przed sprawdzeniem: loginy, nazwa i adresy tak, jak je wpisano."""

    logins: Sequence[str]
    name: str
    addresses: Sequence[str] = ()
    active: bool = True
    reminders: bool = True


ProblemKind = Literal[
    "no_login",
    "empty_login",
    "repeated_login",
    "empty_name",
    "invalid_name",
    "too_long_name",
    "same_file",
    "not_address",
    "repeated_address",
]
"""Wpis bez loginu (``no_login``), login pusty (``empty_login``) albo już użyty, także u innego Wykonawcy
(``repeated_login``), nazwa pusta (``empty_name``) albo taka, która nie może być nazwą pliku Rozliczenia pracownika
(``invalid_name``, ``too_long_name`` według ``check_worker_name``), nazwa, która daje ten sam plik co nazwa wcześniejszego
Wykonawcy (``same_file``), wartość, która nie jest jednym adresem ``lokalna@domena`` (``not_address``), i adres już użyty,
także u innego Wykonawcy (``repeated_address``)."""

Part = Literal["loginy", "nazwa", "adresy"]


@dataclass(frozen=True)
class WorkerListProblem:
    """Pierwsza złamana reguła: numer wpisu (od 0), pole wpisu, pozycja w nim (``None`` dla nazwy) i rodzaj."""

    worker: int
    part: Part
    item: int | None
    kind: ProblemKind


@dataclass(frozen=True)
class WorkerList:
    """Lista Wykonawców w kolejności z pliku i to, co tata ma jeszcze rozstrzygnąć po przeniesieniu starych plików.

    Buduje ją tylko ``of``."""

    workers: tuple[Worker, ...]
    unresolved: tuple[Unresolved, ...] = ()

    @classmethod
    def of(cls, entries: Sequence[WorkerEntry], unresolved: Sequence[Unresolved] = ()) -> WorkerList | WorkerListProblem:
        """Lista z wpisów ``entries`` albo pierwsza złamana reguła; login porównuje ``normalize_text``, a adres
        ``casefold``, więc ``Jan.Testowy`` i ``jan.testowy`` to ten sam login."""

        workers: list[Worker] = []
        logins: set[Login] = set()
        files: set[str] = set()
        addresses: set[SenderAddress] = set()
        for index, entry in enumerate(entries):
            if not entry.logins:
                return WorkerListProblem(index, "loginy", None, "no_login")
            found_logins: list[Login] = []
            for item, value in enumerate(entry.logins):
                login = Login(normalize_text(value))
                if not login:
                    return WorkerListProblem(index, "loginy", item, "empty_login")
                if login in logins:
                    return WorkerListProblem(index, "loginy", item, "repeated_login")
                logins.add(login)
                found_logins.append(login)
            name = entry.name.strip()
            if not normalize_text(name):
                return WorkerListProblem(index, "nazwa", None, "empty_name")
            match check_worker_name(name):
                case "invalid":
                    return WorkerListProblem(index, "nazwa", None, "invalid_name")
                case "too_long":
                    return WorkerListProblem(index, "nazwa", None, "too_long_name")
                case "fine":
                    pass
            if normalize_text(name) in files:
                return WorkerListProblem(index, "nazwa", None, "same_file")
            files.add(normalize_text(name))
            found_addresses: list[SenderAddress] = []
            for item, value in enumerate(entry.addresses):
                address = SenderAddress.of(value)
                if address is None or address.shown() != value.strip().casefold():
                    return WorkerListProblem(index, "adresy", item, "not_address")
                if address in addresses:
                    return WorkerListProblem(index, "adresy", item, "repeated_address")
                addresses.add(address)
                found_addresses.append(address)
            workers.append(Worker(tuple(found_logins), name, tuple(found_addresses), entry.active, entry.reminders))
        return cls(tuple(workers), tuple(unresolved))

    def names(self) -> Mapping[str, str]:
        """Login → nazwa w Rozliczeniu pracownika, każdy login każdego Wykonawcy, w kolejności z listy."""

        return {login: worker.name for worker in self.workers for login in worker.logins}

    def name_of(self, login: str) -> str | None:
        return self.names().get(normalize_text(login))

    def addresses(self) -> WorkerAddresses:
        """Adres → login każdego Wykonawcy, także Nieaktywnego: jego Raport wykonawcy też jest Raportem wykonawcy. Każdy
        login Wykonawcy prowadzi do jego pierwszego loginu, więc Raport wykonawcy trafia też do zleceń spod drugiego."""

        return WorkerAddresses(
            {address: worker.logins[0] for worker in self.workers for address in worker.addresses},
            {login: worker.logins[0] for worker in self.workers for login in worker.logins},
        )

    def reminded(self) -> frozenset[Login]:
        """Loginy aktywnych Wykonawców z włączonymi przypomnieniami: tylko oni dostają Przypomnienia o raporcie."""

        return frozenset(login for worker in self.workers if worker.active and worker.reminders for login in worker.logins)
