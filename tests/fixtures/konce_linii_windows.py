"""Końce linii zapisu tekstowego na Windows (komputer taty) w teście na każdym systemie.

Tryb tekstowy Pythona na Windows zapisuje każde ``\\n`` jako ``\\r\\n``, a odczyt tekstowy (``read_text``) zamienia je z
powrotem, więc różnicę widzi tylko porównanie bajtów. ``windows_text_writes`` daje taki zapis także na macOS i Linuksie,
żeby test bajtów pliku padał na Macu tam, gdzie padłby u taty.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def windows_text_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Path.write_text`` bez ``newline`` zapisuje każde ``\\n`` jako ``\\r\\n``, jak na Windows, do końca testu.

    Zapis z podanym ``newline`` i zapis bajtów zostają bez zmian. Zapisu przez ``open`` w trybie tekstowym nie zmienia:
    ten widzi tylko CI na Windows.
    """

    write_text = Path.write_text

    def on_windows(
        self: Path, data: str, encoding: str | None = None, errors: str | None = None, newline: str | None = None
    ) -> int:
        return write_text(self, data, encoding=encoding, errors=errors, newline="\r\n" if newline is None else newline)

    monkeypatch.setattr(Path, "write_text", on_windows)
