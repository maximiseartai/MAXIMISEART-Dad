"""Zapisywanie Przebiegu rozliczeń: Folder rozliczeń pracowników powstaje cały albo wcale.

Rozliczenia pracowników powstają w folderze tymczasowym obok Folderu rozliczeń pracowników, w Folderze okresu
(``staged_publication``). Gotowy folder tymczasowy staje się Folderem rozliczeń pracowników jedną zmianą nazwy.
Nienadpisywanie jest sprawdzane przed startem Przebiegu rozliczeń i ponownie tuż przed publikacją.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from . import settlement_messages, staged_publication
from .message import StopError

ResultT = TypeVar("ResultT")

__all__ = ["ensure_worker_settlements_absent", "write_worker_settlements"]


def ensure_worker_settlements_absent(target_directory: Path) -> None:
    """Nienadpisywanie: zatrzymuje Przebieg rozliczeń, jeśli Folder rozliczeń pracowników już istnieje."""

    if target_directory.exists() or target_directory.is_symlink():
        raise StopError(settlement_messages.worker_settlements_exist(target_directory))


def write_worker_settlements(target_directory: Path, write: Callable[[Path], ResultT]) -> ResultT:
    """Publikuje Rozliczenia pracowników zapisane przez ``write`` w folderze tymczasowym.

    ``write`` dostaje folder tymczasowy, a jego wynik wraca bez zmian po publikacji Folderu rozliczeń pracowników.
    Błąd zapisu zatrzymuje Przebieg rozliczeń Komunikatem bez publikacji.
    """

    def publish(staging: Path) -> ResultT:
        results = write(staging)
        ensure_worker_settlements_absent(target_directory)
        try:
            staging.rename(target_directory)
        except OSError as exc:
            raise StopError(settlement_messages.publish_failed(target_directory)) from exc
        return results

    return staged_publication.publish_staged(
        target_directory.parent,
        target_directory.name,
        publish,
        failed=settlement_messages.write_failed(target_directory),
        left=settlement_messages.staging_left,
    )
