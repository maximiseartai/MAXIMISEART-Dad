"""Kontrakt sekcji Wykonawcy w Ustawieniach Centrum: Lista Wykonawców i to, co tata ma rozstrzygnąć po przeniesieniu
starych plików."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from rozliczenia.centrum.contract.common import Model


class SettingProblem(Model):
    """Złe ustawienie w pliku: pole w pliku (``rejestr_zlecen``, ``wykonawcy[2].adresy[0]``) albo ``None`` dla całego
    pliku i zdanie dla taty."""

    field: str | None
    message: str


class ListedWorker(Model):
    """Wykonawca z Listy Wykonawców: loginy z kolumny WYKONAWCA, nazwa w Rozliczeniu pracownika, adresy Raportów
    wykonawcy, ``active``: nie jest Nieaktywnym Wykonawcą, ``reminders``: dostaje Przypomnienia o raporcie."""

    logins: list[str]
    name: str
    addresses: list[str]
    active: bool
    reminders: bool


class UnmatchedLogin(Model):
    """Adresy przy loginie, którego nie miał żaden Wykonawca starego pliku Wykonawców (``worker_mapping.yaml``)."""

    reason: Literal["login_bez_wykonawcy"]
    login: str
    addresses: list[str]


class AddressesNotMoved(Model):
    """Starego pliku adresów nie dało się przeczytać, więc Wykonawcy przeszli bez adresów; ``message`` mówi dlaczego."""

    reason: Literal["adresy_nieprzeniesione"]
    message: str


Unresolved = Annotated[UnmatchedLogin | AddressesNotMoved, Field(discriminator="reason")]


class WorkerListSetting(Model):
    """Lista Wykonawców: ``good``, ``bad`` (zły plik: ``problem`` i ostatnia dobra lista, a bez niej pusta) albo
    ``unreadable`` (system nie daje teraz czytać pliku: lista pusta, ``problem`` bez pola ze zdaniem dla taty)."""

    state: Literal["good", "bad", "unreadable"]
    workers: list[ListedWorker]
    unresolved: list[Unresolved]
    problem: SettingProblem | None


class WorkerForm(Model):
    """Wykonawca z formularza sekcji Wykonawcy: loginy z kolumny WYKONAWCA (zapisane i dopisane), nazwa w Rozliczeniu
    pracownika i adresy Raportów wykonawcy, tak jak je wpisał tata."""

    logins: list[str]
    name: str
    addresses: list[str]


class WorkerEdit(WorkerForm):
    """Zmiana Wykonawcy z formularza; loginu, którego nie ma już w ``logins``, nie może mieć żaden okres.
    ``rename_confirmed``: tata widział ostrzeżenie o Rozliczeniu pracownika ze starą nazwą i zmienia nazwę mimo to."""

    rename_confirmed: bool = False


class WorkerSwitches(Model):
    """Przełącznik na karcie Wykonawcy, zapisany od razu: ``active`` (``False``: Nieaktywny Wykonawca) albo
    ``reminders`` (Przypomnienia o raporcie); ``None`` zostawia przełącznik."""

    active: bool | None = None
    reminders: bool | None = None
