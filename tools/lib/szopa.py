"""Lista dwóch szop (ADR 0034) i podtabela grupy ``PRZEPUSZCZA``: jednostki, których fałszywe „OK” przepuszcza zły kod
produktu. Nocne mutacje psują jak ``src/`` te z nich, które leżą w ``tools/``; skryptów skilli ``.agents/skills/verify-*/``
z tym oznaczeniem nie psują (``CODE`` w ``tools/mutacje_zmiany.py``, ADR 0021)."""

from __future__ import annotations

from pathlib import Path
import tomllib

LISTA = "tools/lib/szopa.toml"
PRZEPUSZCZA = "przepuszcza"


def przepuszczajace(root: Path) -> tuple[str, ...]:
    """Jednostki z oznaczeniem ``PRZEPUSZCZA`` na liście checkoutu ``root``; jej kształt sprawdza ``rozmiar_pr.wpisy``."""

    lista = tomllib.loads((root / LISTA).read_text(encoding="utf-8"))
    return tuple(jednostka for grupa in lista.values() for jednostka in grupa.get(PRZEPUSZCZA, {}))
