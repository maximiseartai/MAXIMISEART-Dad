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
    logins: tuple[Login, ...]
    name: str
    addresses: tuple[SenderAddress, ...]
    active: bool
    reminders: bool


@dataclass(frozen=True)
class UnmatchedLogin:
    login: Login
    addresses: tuple[SenderAddress, ...]


@dataclass(frozen=True)
class AddressesNotMoved:
    sentence: str


Unresolved = UnmatchedLogin | AddressesNotMoved


@dataclass(frozen=True)
class WorkerEntry:
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

Part = Literal["loginy", "nazwa", "adresy"]


@dataclass(frozen=True)
class WorkerListProblem:
    worker: int
    part: Part
    item: int | None
    kind: ProblemKind


@dataclass(frozen=True)
class WorkerList:
    workers: tuple[Worker, ...]
    unresolved: tuple[Unresolved, ...] = ()

    @classmethod
    def of(cls, entries: Sequence[WorkerEntry], unresolved: Sequence[Unresolved] = ()) -> WorkerList | WorkerListProblem:
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
        return {login: worker.name for worker in self.workers for login in worker.logins}

    def name_of(self, login: str) -> str | None:
        return self.names().get(normalize_text(login))

    def addresses(self) -> WorkerAddresses:
        return WorkerAddresses(
            {address: worker.logins[0] for worker in self.workers for address in worker.addresses},
            {login: worker.logins[0] for worker in self.workers for login in worker.logins},
        )

    def reminded(self) -> frozenset[Login]:
        return frozenset(login for worker in self.workers if worker.active and worker.reminders for login in worker.logins)
