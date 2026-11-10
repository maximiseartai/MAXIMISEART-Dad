"""Kopie konfliktu OneDrive obok INTERMAX: wersja pliku, której OneDrive nie umiał połączyć z wersją w chmurze.

Gdy ten sam plik zmieniły dwa komputery, OneDrive zostawia oba: wersja z chmury ma nazwę pliku, a wersja z komputera
dostaje dopisek nazwy komputera przed rozszerzeniem, np. ``Report-JOHNS-SURFACE.txt`` dla ``Report.txt`` (Microsoft
Learn, „Resolve sync issues in OneDrive for work or school”, sekcja „Review conflicts”:
https://learn.microsoft.com/en-us/troubleshoot/sharepoint/sync/troubleshoot-sync-issues). Kopia konfliktu to więc plik
w folderze INTERMAX o nazwie ``<nazwa INTERMAX bez rozszerzenia>-<nazwa komputera><rozszerzenie INTERMAX>``, bez względu
na wielkość liter, jak w Eksploratorze plików. Nazwa komputera zaczyna się i kończy literą albo cyfrą, a w środku ma
też łączniki, podkreślenia i spacje, więc ``… - Kopia.xlsx`` z Eksploratora, plik blokady Excela ``~$…`` i plik
tymczasowy zapisu ``.<nazwa>.….xlsx`` kopią konfliktu nie są. Obie strony błędu kosztują: przeoczona kopia gubi zmiany pracownika taty,
a kopia rozpoznana bez potrzeby tylko zatrzymuje Wpisanie raportów z nazwą pliku, który tata sprawdzi.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Final

__all__ = ["beside"]

_DEVICE: Final = re.compile(r"[^\W_](?:[\w -]*[^\W_])?")
"""Nazwa komputera w dopisku: litery, cyfry, łączniki, podkreślenia i spacje, z literą albo cyfrą na obu brzegach."""


def beside(register: Path) -> tuple[Path, ...]:
    """Kopie konfliktu OneDrive pliku ``register`` w jego folderze, po nazwie; folder, którego nie da się odczytać, nie
    ma kopii, bo odczyt samego INTERMAX daje wtedy własny Komunikat."""

    head, tail = f"{register.stem}-".casefold(), register.suffix.casefold()
    try:
        names = sorted(path.name for path in register.parent.iterdir())
    except OSError:
        return ()
    return tuple(
        register.with_name(name)
        for name in names
        if (folded := name.casefold()).startswith(head)
        and folded.endswith(tail)
        and _DEVICE.fullmatch(folded[len(head) : len(folded) - len(tail)]) is not None
    )
