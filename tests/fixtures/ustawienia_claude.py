"""Adres Messages API, który wybiera Claude Code: ``env`` z ustawień wygrywa ze środowiskiem procesu.

Atrapy ``claude`` w testach wyroczni (``tests/test_zgoda.py``, ``tests/test_praca_w_tle.py``) pytają tylko ten adres,
więc wyrocznia, która podaje fałszywe API tylko w środowisku procesu, w teście trafia tam, gdzie prawdziwy Claude Code:
5.11.2026 ``env.ANTHROPIC_BASE_URL`` z ``~/.claude/settings.json`` (hub na Macu Maksa) wygrał z adresem fałszywego API w
środowisku i ``claude -p`` wyroczni zapytał prawdziwy model. Źródła od najsłabszego: środowisko procesu, ustawienia
użytkownika (``~/.claude/settings.json``), projektu (``.claude/settings.json``), lokalne (``.claude/settings.local.json``)
i ``--settings`` (kolejność ze strony ustawień Claude Code); ``--setting-sources`` wybiera spośród ``user``,
``project`` i ``local``, a bez niego biorą udział wszystkie. Atrapa ładuje ten plik ze ścieżki, więc importuje tylko
bibliotekę standardową.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path

SOURCES = ("user", "project", "local")


def base_url(argv: Sequence[str], cwd: str, environ: Mapping[str, str]) -> str | None:
    """``ANTHROPIC_BASE_URL``, który wybrałby Claude Code uruchomiony z ``argv`` w ``cwd`` ze środowiskiem ``environ``."""

    chosen = argv[list(argv).index("--setting-sources") + 1].split(",") if "--setting-sources" in argv else SOURCES
    files = {
        "user": Path(environ["HOME"]) / ".claude" / "settings.json",
        "project": Path(cwd) / ".claude" / "settings.json",
        "local": Path(cwd) / ".claude" / "settings.local.json",
    }
    layers = [
        json.loads(files[source].read_text(encoding="utf-8"))
        for source in SOURCES
        if source in chosen and files[source].exists()
    ]
    if "--settings" in argv:
        layers.append(json.loads(argv[list(argv).index("--settings") + 1]))
    url = environ.get("ANTHROPIC_BASE_URL")
    for layer in layers:
        url = layer.get("env", {}).get("ANTHROPIC_BASE_URL", url)
    return url
