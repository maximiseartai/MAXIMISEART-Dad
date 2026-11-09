"""Przywracanie Kopii INTERMAX z Konfiguracji Centrum rozliczeń: Rejestr zleceń dostaje w całości bajty wybranej Kopii.

``restore`` przywraca Kopię, którą wymienia ``copies``: INTERMAX dostaje jej bajty po Kopii stanu
bieżącego, tą samą podmianą co Uporządkowanie INTERMAX (``intermax_replace``), i tylko nazywa jej fakt Komunikatem
przywracania.
"""

from __future__ import annotations

import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

from . import intermax_copies, workbook_files
from . import intermax_messages as messages
from .intermax_copies import Copy
from .intermax_replace import LOCAL_DISK, Disk, Refusal, Waiting, WriteMismatch, replace_register
from .message import Message, StopError
from .workbook_files import WorkbookError
from .workbook_parts import office_document, package_parts


@dataclass(frozen=True)
class Restored:
    """Przywrócona Kopia i ostrzeżenia (starsze Kopie zostały)."""

    restored: Copy
    warnings: list[Message]


def _is_workbook(content: bytes) -> bool:
    """``content`` to skoroszyt Excela: zip, którego relacja dokumentu (``workbook_parts.office_document``) wskazuje
    część w paczce, tak jak przy odczycie Rejestru (``register_file.read``); treści arkuszy nie sprawdza."""

    try:
        with package_parts(content) as parts:
            document = office_document(parts)
            return document is not None and document in parts
    except (zipfile.BadZipFile, zlib.error, KeyError, ElementTree.ParseError):
        return False


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
        raise StopError(messages.register_unusable(error, messages.RESTORE)) from error
    try:
        content = workbook_files.workbook_content(chosen.path)
    except WorkbookError as error:
        raise StopError(messages.copy_unusable(error)) from error
    if not _is_workbook(content):
        raise StopError(messages.copy_damaged(chosen.path))

    def check(written: bytes) -> None:
        if written != content:
            raise WriteMismatch("kopia")

    outcome = replace_register(
        register, current, content, check, before="restore", copies=directory, now=now, waiting=waiting, disk=disk
    )
    if isinstance(outcome, Refusal):
        raise StopError(messages.refused(outcome, register, directory, messages.RESTORE))
    warnings = [messages.old_copies_kept(directory, messages.RESTORE)] if outcome.old_copies_kept else []
    return Restored(chosen, warnings)

