"""Kopia wejścia w Logach Uruchomienia (pole ``RunLog.input_copy``): pliki taty, które Uruchomienie przeczytało, z
odciskiem i przeczytanymi wierszami po regule danych (``input_copy``).

Schemat Kopii wejścia stoi osobno od reszty Logów (``run_logs``), bo czytają go narzędzia Maksa, które z Logów biorą tylko
Kopię wejścia (odtworzenie Uruchomienia, brama Legendy czynności): zależy tylko od typów Kopii wejścia silnika, a nie od
kontraktu Centrum rozliczeń.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict

from rozliczenia.client_data import READ_VALUES
from rozliczenia.input_copy import CellValue, CopiedFile, CopiedSheet, Typed, TypedKind


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LoggedTyped(_Record):
    """Wartość komórki, której JSON nie odróżnia od tekstu (``input_copy.Typed``): rodzaj i zapis."""

    type: TypedKind
    text: str


LoggedCell = bool | int | float | str | LoggedTyped
"""Wartość niepustej komórki w Kopii wejścia."""


def _cell(value: CellValue) -> LoggedCell:
    return LoggedTyped(type=value.kind, text=value.text) if isinstance(value, Typed) else value


class LoggedRow(_Record):
    """Przeczytany wiersz: numer w arkuszu i niepuste komórki po literze kolumny."""

    row: int
    cells: Annotated[dict[str, LoggedCell], READ_VALUES]


class LoggedSheet(_Record):
    """Przeczytany arkusz: wiersz nagłówka, nagłówki po literze kolumny (bez zakazanych kolumn), wiersze i puste wiersze
    z odczytanego zakresu, które proces liczy (Rejestr zleceń).

    Fakty wklejenia INTERMAX (``input_copy.PasteFacts``) poza wierszami ze śladem przesunięcia, które idą do uwag
    (``RunLog.input_copy_notes``), stoją płasko w arkuszu. ``shifted_row``: przesunięty pierwszy wiersz wklejenia
    INTERMAX, którego komórki Uporządkowanie czyta w pliku dwie kolumny na lewo od nagłówka, a tu stoją pod nim;
    ``None``: bez niego i pliki, które tego pola jeszcze nie miały. ``uncertain_rows``: wiersze wklejenia bez pewnego
    położenia, które mają tylko komórki dozwolone w każdym ich możliwym położeniu. ``last_ordered_row`` i
    ``yellow_row``: ostatni uporządkowany i żółty wiersz nad wklejeniem INTERMAX, od których Planowanie liczy wiersz
    dnia, bez treści; ``None``: bez takiego wiersza, inne pliki i pliki, które tych pól jeszcze nie miały.
    """

    sheet: str
    header_row: int
    columns: dict[str, str]
    rows: list[LoggedRow]
    empty_rows: list[int]
    shifted_row: int | None = None
    uncertain_rows: list[int] = []
    last_ordered_row: int | None = None
    yellow_row: int | None = None

    @classmethod
    def of(cls, sheet: CopiedSheet) -> LoggedSheet:
        paste = sheet.paste
        return cls(
            sheet=sheet.name,
            header_row=sheet.header_row,
            columns=dict(sheet.columns),
            rows=[
                LoggedRow(row=row.number, cells={letter: _cell(value) for letter, value in row.cells.items()})
                for row in sheet.rows
            ],
            empty_rows=list(sheet.empty_rows),
            shifted_row=paste.shifted_row,
            uncertain_rows=list(paste.uncertain_rows),
            last_ordered_row=paste.last_ordered_row,
            yellow_row=paste.yellow_row,
        )


class LoggedFingerprint(_Record):
    """Odcisk pliku: rozmiar i skrót SHA-256 przeczytanych bajtów, chwila zmiany pliku tuż przed odczytem (UTC; ``None``,
    gdy system jej nie oddał)."""

    size: int
    modified_at: datetime | None
    sha256: str


class LoggedInputFile(_Record):
    """Plik taty w Kopii wejścia (``input_copy``): sama nazwa, odcisk i przeczytane arkusze.

    ``folders``: nazwy folderu nad folderem pliku i folderu pliku (``input_copy.CopiedFile.folders``; Komunikaty
    INTERMAX pokazują tylko folder pliku); pusta lista w plikach, które tego pola jeszcze nie miały.
    """

    name: str
    fingerprint: LoggedFingerprint
    sheets: list[LoggedSheet]
    folders: list[str] = []

    @classmethod
    def of(cls, copied: CopiedFile) -> LoggedInputFile:
        fingerprint = copied.fingerprint
        return cls(
            name=copied.name,
            fingerprint=LoggedFingerprint(
                size=fingerprint.size, modified_at=fingerprint.modified_at, sha256=fingerprint.sha256
            ),
            sheets=[LoggedSheet.of(sheet) for sheet in copied.sheets],
            folders=list(copied.folders),
        )
