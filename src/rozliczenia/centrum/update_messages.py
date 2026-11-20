from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from rozliczenia.centrum.tool_update import (
    LIBRARIES_FAILED,
    LOCAL_CHANGES,
    LOGIN,
    NO_CONNECTION,
    NEW_VERSION_FAILED,
    NO_GIT,
    OTHER_BRANCH,
    ROLLBACK_FAILED,
    UNEXPECTED,
)
from rozliczenia.message import Message

_TOOL: Final = "narzędzie na tym komputerze"
_STILL_WORKS: Final = "Narzędzie działa dalej w poprzedniej wersji."
_TO_MAKS: Final = f"{_STILL_WORKS} Przekaż sprawę Maksowi: kliknij „Wyślij do Maksa”."
_NOT_UPDATED: Final = "Nie zaktualizowano narzędzia:"
_RETRY: Final = "Kliknij „Zaktualizuj narzędzie” jeszcze raz. Jeśli komunikat wraca, kliknij „Wyślij do Maksa”."


def no_git() -> Message:
    return Message(code=NO_GIT, what=f"{_NOT_UPDATED} na tym komputerze nie ma Gita.", where=_TOOL, action=_TO_MAKS)


def no_connection() -> Message:
    return Message(
        code=NO_CONNECTION,
        what=f"{_NOT_UPDATED} brak połączenia z GitHubem.",
        where=_TOOL,
        action=f"{_STILL_WORKS} Sprawdź internet i kliknij „Zaktualizuj narzędzie” jeszcze raz.",
    )


def login_required() -> Message:
    return Message(code=LOGIN, what=f"{_NOT_UPDATED} GitHub prosi o logowanie.", where=_TOOL, action=_TO_MAKS)


def other_branch() -> Message:
    return Message(
        code=OTHER_BRANCH,
        what=f"{_NOT_UPDATED} na tym komputerze jest inna gałąź narzędzia niż main.",
        where=_TOOL,
        action=_TO_MAKS,
    )


def local_changes() -> Message:
    return Message(
        code=LOCAL_CHANGES,
        what=f"{_NOT_UPDATED} ma zmiany zrobione na tym komputerze.",
        where=_TOOL,
        action=_TO_MAKS,
    )


def unexpected_failure() -> Message:
    return Message(
        code=UNEXPECTED,
        what="Nie udało się zaktualizować narzędzia z nieoczekiwanego powodu.",
        where=_TOOL,
        action=f"{_STILL_WORKS} {_RETRY}",
    )


def libraries_failed() -> Message:
    return Message(
        code=LIBRARIES_FAILED,
        what="Nie udało się zainstalować bibliotek nowej wersji narzędzia.",
        where=_TOOL,
        action=f"{_STILL_WORKS} {_RETRY}",
    )


def new_version_failed() -> Message:
    return Message(
        code=NEW_VERSION_FAILED,
        what="Nowa wersja narzędzia nie wystartowała.",
        where=_TOOL,
        action=_TO_MAKS,
    )


def rollback_failed() -> Message:
    return Message(
        code=ROLLBACK_FAILED,
        what="Aktualizacja narzędzia się nie udała i nie dało się przywrócić poprzedniej wersji.",
        where=_TOOL,
        action=_RETRY,
    )


NextAction = Literal["retry", "report"]

_BY_CODE: Final[Mapping[str, tuple[Callable[[], Message], NextAction]]] = {
    NO_GIT: (no_git, "report"),
    NO_CONNECTION: (no_connection, "retry"),
    LOGIN: (login_required, "report"),
    OTHER_BRANCH: (other_branch, "report"),
    LOCAL_CHANGES: (local_changes, "report"),
    UNEXPECTED: (unexpected_failure, "retry"),
    LIBRARIES_FAILED: (libraries_failed, "retry"),
    NEW_VERSION_FAILED: (new_version_failed, "report"),
    ROLLBACK_FAILED: (rollback_failed, "retry"),
}


@dataclass(frozen=True)
class UpdateFailure:
    message: Message
    next_action: NextAction

    @classmethod
    def of(cls, code: str) -> UpdateFailure:
        factory, next_action = _BY_CODE.get(code, _BY_CODE[UNEXPECTED])
        return cls(factory(), next_action)
