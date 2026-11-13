"""HTML treści z pola ``bodyHTML`` GraphQL GitHuba, z którego czyta rejestr korzeni (W1 r1 #1525).

``body_html.json`` trzyma prawdziwe treści tego repozytorium nagrane 13.11.2026 z ``bodyHTML`` (GraphQL) i z HTML
renderera ``POST /markdown`` (``rendered``: treść pod dwiema pierwszymi liniami werdyktu albo cała treść opisu
i issue): werdykt ``FAIL`` #1457 z blokami kodu, które ``bodyHTML`` owija w ``snippet-clipboard-content``, werdykt
``PASS`` #1508 z punktem rozstrzygnięcia kodu, opis scalonego PR #1499 z sekcją ``## Korzeń`` i blokami kodu oraz
issue chwastu #1519 z tabelą wystąpień.

``body_html`` składa ``bodyHTML`` treści atrapy ``gh`` z nagranego HTML renderera tak jak GitHub: dwie pierwsze
niepuste linie werdyktu to dwie linie jednego akapitu, a pod nim HTML treści pod nimi; inna treść to jej HTML.
"""

from __future__ import annotations

from collections.abc import Mapping
import html
import json
from pathlib import Path

SAMPLES: dict[str, dict[str, str]] = json.loads(Path(__file__).with_name("body_html.json").read_text(encoding="utf-8"))
VERDICT = "WERDYKT:"


def body_html(text: str, rendered: Mapping[str, str]) -> str:
    """``bodyHTML`` treści ``text`` z HTML renderera ``rendered`` (treść na HTML); treść bez HTML to ``KeyError``."""

    lines = text.splitlines()
    filled = [index for index, line in enumerate(lines) if line.strip()]
    if not filled:
        return ""
    if not lines[filled[0]].strip().startswith(VERDICT):
        return rendered[text]
    first = "<br>\n".join(html.escape(lines[index].strip()) for index in filled[:2])
    rest = "\n".join(lines[filled[1] + 1 :]) if len(filled) > 1 else ""
    return f'<p dir="auto">{first}</p>\n' + (rendered[rest] if rest.strip() else "")
