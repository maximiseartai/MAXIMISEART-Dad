"""Przywracanie Kopii INTERMAX z Konfiguracji Centrum rozliczeń: Rejestr zleceń dostaje w całości bajty wybranej Kopii.

``restore`` przywraca Kopię, którą wymienia ``copies``: INTERMAX dostaje jej bajty po Kopii stanu
bieżącego, tą samą podmianą co Uporządkowanie INTERMAX (``intermax_replace``), i tylko nazywa jej fakt Komunikatem
przywracania.
"""

from __future__ import annotations

import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path

from . import intermax_copies, workbook_files
from . import intermax_messages as messages
from .intermax_copies import Copy
from .intermax_replace import LOCAL_DISK, Disk, Refusal, Waiting, WriteMismatch, replace_register
from .message import Message, StopError
from .workbook_files import WorkbookError


@dataclass(frozen=True)
class Restored:
    """Przywrócona Kopia, Kopia stanu sprzed przywrócenia i ostrzeżenia (starsze Kopie zostały)."""

    restored: Copy
    previous: Copy
    warnings: list[Message]


def _parts(content: bytes) -> list[str]:
    """Nazwy części archiwum zip ``content``; bajty, które nie są zipem, nie mają żadnej."""

    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            return archive.namelist()
    except zipfile.BadZipFile:
        return []


def copies(directory: Path) -> list[Copy]:
    """Kopie INTERMAX w ``directory`` od najnowszej (``intermax_copies.listed``); ``StopError``, gdy folderu nie da się
    odczytać: Konfiguracja nie pokaże Kopii, a przywrócenie nie zacznie."""

    try:
        return intermax_copies.listed(directory)
    except OSError as error:
        raise StopError(messages.copies_unreadable(directory)) from error


def restore(
    name: str,
    register: Path,
    directory: Path,
    *,
    now: Callable[[], datetime],
    waiting: Waiting,
    disk: Disk = LOCAL_DISK,
) -> Restored:
    """Przywraca do INTERMAX ``register`` Kopię INTERMAX ``name``, którą ``listed`` wymienia w ``directory``.

    Najpierw powstaje Kopia stanu bieżącego z nazwą ``INTERMAX przed przywróceniem`` z ``now()``, potem INTERMAX
    dostaje atomowo bajty wybranej Kopii, a po udanej podmianie zostaje ``KEPT`` najnowszych Kopii. ``StopError``,
    gdy nie można przywrócić bezpiecznie (INTERMAX otwarty w Excelu albo trzymany przez OneDrive, Kopii nie ma albo
    jest uszkodzona, nie powstała Kopia stanu bieżącego albo w tej samej sekundzie przywrócono już inną Kopię);
    INTERMAX i Kopie zostają wtedy takie, jak były. Nieudane usunięcie starszych Kopii to ostrzeżenie: INTERMAX jest
    już przywrócony.
    """

    chosen = next((copy for copy in copies(directory) if copy.path.name == name), None)
    if chosen is None:
        raise StopError(messages.copy_missing(directory, name))
    try:
        current = workbook_files.workbook_content(register)
    except WorkbookError as error:
        raise StopError(messages.restore_register_unusable(error)) from error
    try:
        content = workbook_files.workbook_content(chosen.path)
    except WorkbookError as error:
        raise StopError(messages.copy_unusable(error)) from error
    if "xl/workbook.xml" not in _parts(content):  # skoroszyt Excela; treści arkuszy nie sprawdza
        raise StopError(messages.copy_damaged(chosen.path))

    def check(written: bytes) -> None:
        if written != content:
            raise WriteMismatch("kopia")

    outcome = replace_register(
        register, current, content, check, before="restore", copies=directory, now=now, waiting=waiting, disk=disk
    )
    if isinstance(outcome, Refusal):
        raise StopError(_refused(outcome, register, directory))
    warnings = [messages.old_copies_kept_after_restore(directory)] if outcome.old_copies_kept else []
    return Restored(chosen, outcome.copy, warnings)


def _refused(refusal: Refusal, register: Path, directory: Path) -> Message:
    match refusal:
        case Refusal.EXCEL_HOLDS:
            return messages.restore_register_open(register)
        case Refusal.ONEDRIVE_HOLDS:
            return messages.restore_register_syncing(register)
        case Refusal.WRITE_FAILED | Refusal.WRITE_MISMATCH:
            return messages.restore_failed(register)
        case Refusal.COPY_FAILED:
            return messages.restore_copy_failed(directory)
        case Refusal.COPY_EXISTS:
            return messages.restored_moment_ago(directory)
