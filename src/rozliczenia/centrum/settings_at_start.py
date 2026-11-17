"""Ustawienia ze startu: Ustawienia Centrum, którymi liczy jedno Uruchomienie procesu, z chwili jego startu (ADR 0032).

Proces mówi, którymi z nich liczy, potrzebą w ``ProcessKind.needs`` (``SettingNeed``), a nie osobną flagą na każde
Ustawienie. Nazwa potrzeby to nazwa pola ``process_kind.Start`` i, poza ``workers``, pola ``SettingsSnapshot``, więc
sprawdzenie startu w ``Catalog.prepared`` (``missing``), rzut startu na proces (``not_counted``) i odmowa startu przy
pliku bez odczytu (``unreadable``) to po jednej pętli po ``SettingNeed``.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Final, Literal, assert_never, get_args

from rozliczenia.centrum import refusal
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.centrum.settings.owner import SettingsSnapshot, UnreadableFile

SettingNeed = Literal["workers", "quantity_rules", "activity_legend"]
"""Ustawienie ze startu, którym liczy proces: część języka potrzeb (``process_kind.Need``). Kolejność to kolejność
błędów gospodarza i odmów startu."""

_SETTING_NEEDS: Final[tuple[SettingNeed, ...]] = get_args(SettingNeed)


def missing(start: object, needs: Collection[str]) -> str | None:
    """Zdanie błędu gospodarza o pierwszym Ustawieniu ze startu, którym liczy proces o potrzebach ``needs``, a którego
    start ``start`` (``process_kind.Start``) nie ma; ``None``: start ma wszystkie."""

    for need in _SETTING_NEEDS:
        if need in needs and getattr(start, need) is None:
            return _missing(need)
    return None


def not_counted(needs: Collection[str]) -> dict[str, Any]:
    """Pola startu (``process_kind.Start``) z Ustawieniami ze startu, którymi proces o potrzebach ``needs`` nie liczy,
    jako ``None``: rzut startu na proces (``dataclasses.replace``), więc wejście i Logi mają tylko jego Ustawienia."""

    return {need: None for need in _SETTING_NEEDS if need not in needs}


def unreadable(snapshot: SettingsSnapshot, needs: Collection[str]) -> Refusal | None:
    """Odmowa startu procesu o potrzebach ``needs``: plik Ustawienia ze startu, którym proces liczy, a którego system nie
    daje teraz czytać, w kolejności ``SettingNeed``; ``None``, gdy każdy da się czytać."""

    for need in _SETTING_NEEDS:
        value = getattr(snapshot, need)
        if need in needs and isinstance(value, UnreadableFile):
            return refusal.settings_file_unreadable(value.name)
    return None


def _missing(need: SettingNeed) -> str:
    match need:
        case "workers":
            return "potrzebuje Listy Wykonawców, a start jej nie ma"
        case "quantity_rules":
            return "liczy Regułami ilości, a start ich nie ma"
        case "activity_legend":
            return "liczy Legendą czynności, a start jej nie ma"
        case _:
            assert_never(need)
