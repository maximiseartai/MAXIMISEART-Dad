"""Jednorazowy krok instalacji: skrót „Centrum rozliczeń” na pulpicie i w Autostarcie (Windows)."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from rozliczenia.centrum.shortcut import main


if __name__ == "__main__":
    raise SystemExit(main())
