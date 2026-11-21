from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

import mutacja_recenzenta
import repo
import straznik

PLIK = "tools/lib/strazniki_przeniesione.toml"

ZASADY = f"""Strażnik przeniesiony ([ADR 0042](../../docs/adr/0042-straznik-przy-pierwszym-waznym.md), aneks „Strażnik
przeniesiony”): Ważne scalonego PR, którego strażnik z linii ``Strażnik:`` opisu PR przestał łapać błąd na ``main``
(ponowny dowód raportu tygodniowego bez ``DOWÓD OK``: węzeł testu zniknął albo kotwicy mutacji nie ma dokładnie raz),
dostaje nowego strażnika wpisem w ``{PLIK}``, a opis scalonego PR zostaje bez zmian. Wpis to tabela
``["PR/W<n>/r<k>"]`` (Ważne jak w ``--wazne``) z kluczami:

- ``straznik``: selektor z listy ``straznik.FORMS`` poza wyjątkami ``brak - …``, bo wpis nie zwalnia Ważnego z dowodu;
- ``mutacja`` (tylko przy ``pytest <węzeł>``): blok w postaci JSON bloku ``### Mutacja`` recenzenta
  (``mutacja_recenzenta``), który na dzisiejszym kodzie przywraca błąd z Dowodu Ważnego; bez niego dowód bierze
  najnowszy blok tego Ważnego z werdyktów PR, więc wpis go potrzebuje, gdy kotwicy tamtego bloku nie ma na ``main``.

Każdy wpis, który PR dodaje albo zmienia, dostaje przy merge'u dowód warunku 5 ``tools/scal_pr.py``
(``bramka_straznika``): ``tools/na_scalonych_pr.py --straznik <selektor wpisu> --z-commita <HEAD PR> --wazne
PR/W<n>/r<k>``, także w PR bez Ważnego; czy mutacja wpisu przywraca błąd z Dowodu Ważnego, a nie słabszy, sprawdza
recenzent tego PR. Plik czyta się z drzewa commitu, na którym biegnie dowód: ``tools/na_scalonych_pr.py --straznik …
--z-commita REV`` bierze mutację wpisu z ``REV``, gdy selektor to selektor wpisu, a ``tools/rejestr_korzeni_tydzien.py``
strażnika wpisu z ostatniego commitu ``main`` przed końcem tygodnia, w ponownym dowodzie i w odpaleniach strażników.
"""

_KEY = re.compile(r"(\d+)/(W\d+)/r(\d+)")
_FIELDS = frozenset({"straznik", "mutacja"})


@dataclass(frozen=True)
class Moved:
    pull: int
    major: str
    guard: straznik.Guard
    mutation: mutacja_recenzenta.Block | None


def parse(text: str) -> dict[tuple[int, str], Moved]:
    try:
        tables = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{PLIK}: to nie TOML ({error})") from None
    return dict(_entry(key, value) for key, value in tables.items())


def at(root: Path, commit: str) -> dict[tuple[int, str], Moved]:
    data = repo.blob(root, commit, PLIK)
    return {} if data is None else parse(data.decode("utf-8"))


def _entry(key: str, value: object) -> tuple[tuple[int, str], Moved]:
    where = f"{PLIK}: wpis {key!r}"
    if not (found := _KEY.fullmatch(key)):
        raise ValueError(f"{where}: klucz to Ważne PR/W<n>/r<k>, np. 2254/W1/r1")
    if not isinstance(value, dict) or not isinstance(value.get("straznik"), str) or not set(value) <= _FIELDS:
        raise ValueError(f"{where}: tabela z kluczem straznik (selektor) i opcjonalnym mutacja (JSON bloku ### Mutacja), bez innych kluczy")
    try:
        guard = straznik.parse(value["straznik"])
    except ValueError as error:
        raise ValueError(f"{where}: {error}") from None
    if guard.kind in straznik.EXEMPT:
        raise ValueError(f"{where}: {guard} to wyjątek, a wpis przenosi Ważne do strażnika, który ma dowód: wybierz selektor spoza brak - …")
    pull, label, round_ = int(found[1]), found[2], int(found[3])
    text = value.get("mutacja")
    if text is not None and (guard.kind is not straznik.Kind.PYTEST or not isinstance(text, str)):
        raise ValueError(f"{where}: mutacja to tekst JSON bloku ### Mutacja i stoi tylko przy strażniku pytest <węzeł>")
    block = None if text is None else mutacja_recenzenta.Block(label, round_, text)
    if block is not None:
        try:
            mutacja_recenzenta.mutations(block, (str(guard),))
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None
    return (pull, f"{label} r{round_}"), Moved(pull, f"{label} r{round_}", guard, block)
