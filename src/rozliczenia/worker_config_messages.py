"""Katalog Komunikatów Konfiguracji wykonawców, jeden dla obu procesów, Diagnozy i Konfiguracji Centrum rozliczeń.

Konfiguracja wykonawców jest wspólna dla Przygotowania pliku zbiorczego i Przebiegu rozliczeń, więc każde miejsce,
które jej nie wczyta, mówi o niej tym samym Komunikatem (``worker_config_problem``). Konfiguracja leży w ``config``
na dysku C jak Wzorce, więc tata rzadko sam usunie przyczynę: każdy Komunikat idzie do Maksa.
"""

from __future__ import annotations

from pathlib import Path

from .message import Message, file_label
from .worker_config import ContentProblem, SameWorkerFile, WorkerConfigError


def worker_config_problem(config_path: Path, error: WorkerConfigError) -> Message:
    """Konfiguracji wykonawców nie da się użyć; poza brakiem pliku Komunikat mówi, co jest nie tak z jego treścią."""

    match error.reason:
        case "inaccessible":
            return _inaccessible(config_path)
        case "missing":
            what = "Nie można odczytać konfiguracji wykonawców."
        case content:
            what = f"Nie można odczytać konfiguracji wykonawców. {_content(content)}"
    return Message.to_maintainer(code="ZLA_KONFIGURACJA_WYKONAWCOW", what=what, where=file_label(config_path))


def _content(problem: ContentProblem) -> str:
    """Co jest nie tak z treścią konfiguracji wykonawców, bez ścieżki pliku."""

    match problem:
        case "not_utf8":
            return "Plik nie jest zapisany w kodowaniu UTF-8."
        case "not_yaml":
            return "Plik nie jest poprawnym YAML."
        case "not_mapping":
            return "Konfiguracja musi być mapą z sekcją workers."
        case "unsupported_version":
            return "Nieobsługiwana wersja konfiguracji."
        case "no_workers":
            return "Konfiguracja workers musi zawierać co najmniej jeden wpis."
        case "not_text_entry":
            return "Konfiguracja zawiera niepoprawny identyfikator lub nazwę pracownika."
        case "empty_entry":
            return "Konfiguracja zawiera pusty identyfikator lub nazwę pracownika."
        case "repeated_id":
            return "Konfiguracja zawiera powtórzony identyfikator pracownika."
        case "invalid_worker_name":
            return "Konfiguracja zawiera nazwę pracownika nieprawidłową dla nazwy pliku."
        case "too_long_worker_name":
            return "Konfiguracja zawiera nazwę pracownika zbyt długą dla nazwy pliku."
        case SameWorkerFile(first=first, second=second):
            return f"Dwóch identyfikatorów wskazuje ten sam plik pracownika: {first} / {second}"


def _inaccessible(config_path: Path) -> Message:
    return Message.to_maintainer(
        code="NIEDOSTEPNA_KONFIGURACJA_WYKONAWCOW",
        what="Nie można teraz odczytać konfiguracji wykonawców. Plik może być zajęty przez inny program.",
        where=file_label(config_path),
    )
