"""Legenda czynności (ADR 0038): plik ``legenda-czynnosci.yaml`` w ``config``.

Format pliku i niezmienniki należą do silnika i jego parsera (``activity_legend``, ``activity_legend_file``); tu jest ich
opis dla właściciela Ustawień. Brak pliku to Legenda czynności z Wydania (``DEFAULT_ACTIVITY_LEGEND``). Wartością pliku
są same kody, bo cofnięcie (``restore``) może złożyć wartość, której ``parse`` nie przyjmie, a właściciel sprawdza ją
dopiero przez ``dump`` i ``parse``; legendę, którą liczą procesy, daje z dobrej wartości ``activity_legend``. Klucz
Historii to ``kody.<id>``, a wartość to wpis pliku jako JSON, z którego cofnięcie odtwarza kod.

Legendę taty Wydanie zmienia tylko jawną zmianą (furtka ADR 0032): wpis ``ReleaseChange(<id>, LEGEND, set_codes(...))``
w ``release_changes.RELEASE_CHANGES``. Plik ``legenda_czynnosci_domyslna.yaml`` po pierwszym Wydaniu z legendą się nie
zmienia: tata bez własnego pliku liczy nim, więc jego zmiana weszłaby bez wiersza Historii i bez „Cofnij”.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Final

import yaml

from rozliczenia.activity_legend import ActivityCode, ActivityLegend, LegendProblem, LegendRefused
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND, dump_code, dump_codes, parse_activity_legend, parse_code
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.files import EntriesById, FieldProblem, Good, KeyChange, SettingsFile, settings_yaml
from rozliczenia.centrum.settings.proposal import Edit, Later, Proposal, ReleaseInputs

LEGEND_FILE: Final = "legenda-czynnosci.yaml"
LEGEND_SECTION: Final = "kody"


@lru_cache(maxsize=4)
def _parse(data: bytes | None) -> tuple[ActivityCode, ...] | FieldProblem:
    """Kody z bajtów pliku; ``None`` (brak pliku) to legenda z Wydania. Te same bajty dają ten sam wynik, więc odczyt
    przy każdej migawce nie parsuje pliku od nowa."""

    if data is None:
        return DEFAULT_ACTIVITY_LEGEND.codes
    try:
        document: object = yaml.safe_load(data.decode("utf-8"))
    except UnicodeDecodeError:
        return FieldProblem(None, messages.not_text(LEGEND_FILE))
    except yaml.YAMLError:
        return FieldProblem(None, messages.damaged(LEGEND_FILE))
    legend = parse_activity_legend(document)
    if isinstance(legend, LegendProblem):
        return FieldProblem(None, messages.activity_legend_problem(LEGEND_FILE, legend.message))
    return legend.codes


def _code(entry: object) -> ActivityCode | None:
    code = parse_code(entry)
    return None if isinstance(code, LegendProblem) else code


_ENTRIES: Final = EntriesById[ActivityCode](LEGEND_SECTION, dump_code, _code)


def _reported(change: KeyChange) -> str:
    """Zmiana w Zgłoszeniu: kod nie ma danych osobowych, więc wprost."""

    return f"{change.key}: {'nie ustawiono' if change.before is None else change.before} → {'nie ustawiono' if change.after is None else change.after}"


LEGEND: Final = SettingsFile[tuple[ActivityCode, ...]](
    name=LEGEND_FILE,
    parse=_parse,
    dump=lambda codes: settings_yaml(dump_codes(codes)),
    diff=_ENTRIES.diff,
    restore=_ENTRIES.restore,
    reported=_reported,
    default=DEFAULT_ACTIVITY_LEGEND.codes,
)


def activity_legend(codes: tuple[ActivityCode, ...]) -> ActivityLegend:
    """Legenda czynności, którą liczą procesy, z dobrej wartości pliku (dobrej albo ostatniej dobrej); wartość, której
    legenda nie przyjmuje (tylko spoza ``parse``), to legenda z Wydania."""

    try:
        return ActivityLegend(codes)
    except LegendRefused:
        return DEFAULT_ACTIVITY_LEGEND


Codes = tuple[ActivityCode, ...]


def set_codes(*codes: ActivityCode) -> Callable[[ReleaseInputs[Codes]], Proposal[Codes]]:
    """Zmiana Legendy czynności z Wydania: każdy kod z ``codes`` zastępuje w legendzie taty kod o tym samym ``id`` na jego
    miejscu, a kod, którego tata nie ma, dochodzi na koniec. Edycja jest deklaratywna („ustaw”), więc powtórzona po
    utracie pamięci właściciela nie daje różnicy. Plik ze złą treścią albo bez odczytu to ``Later``: zmiana nie nadpisuje
    pliku taty ostatnią dobrą legendą."""

    def propose(inputs: ReleaseInputs[Codes]) -> Proposal[Codes]:
        if not isinstance(inputs.current, Good):
            return Later("plik Legendy czynności ma złą treść albo nie da się go teraz przeczytać")
        return Edit(lambda current: _with_codes(current, codes))

    return propose


def _with_codes(current: Codes, codes: Codes) -> Codes:
    by_id = {code.id: code for code in codes}
    kept = tuple(by_id.pop(code.id, code) for code in current)
    return (*kept, *by_id.values())
