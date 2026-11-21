from __future__ import annotations

from pathlib import Path
import re
from typing import Final

from .file_state import folder_entries

__all__ = ["beside"]

# ZEWNĘTRZNE: gdy ten sam plik zmieniły dwa komputery, OneDrive zostawia wersję z chmury pod nazwą pliku, a wersję z komputera z dopiskiem -<nazwa komputera> przed rozszerzeniem, np. Report-JOHNS-SURFACE.txt dla Report.txt, a Eksplorator plików porównuje nazwy bez względu na wielkość liter (Microsoft Learn: Resolve sync issues in OneDrive for work or school, sekcja Review conflicts, https://learn.microsoft.com/en-us/troubleshoot/sharepoint/sync/troubleshoot-sync-issues; Naming Files, Paths, and Namespaces)
_DEVICE: Final = re.compile(r"[^\W_](?:[\w '’-]*[^\W_])?")


def beside(register: Path) -> tuple[Path, ...]:
    head, tail = f"{register.stem}-".casefold(), register.suffix.casefold()
    try:
        names = sorted(entry.name for entry in folder_entries(register.parent) or ())
    except OSError:
        return ()
    return tuple(
        register.with_name(name)
        for name in names
        if (folded := name.casefold()).startswith(head)
        and folded.endswith(tail)
        and _DEVICE.fullmatch(folded[len(head) : len(folded) - len(tail)]) is not None
    )
