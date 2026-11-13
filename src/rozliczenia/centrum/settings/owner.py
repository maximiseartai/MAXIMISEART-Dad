"""Ustawienia Centrum: jedyny czytelnik i pisarz plików Ustawień w ``config``, ich Historii i pamięci (ADR 0032).

Na start obejmuje plik Folderów i motywu (``folders``). ``CentrumSettings`` czyta go przy każdym odczycie od nowa, więc
zmiana działa od razu, a proces dostaje jedną migawkę (``snapshot``) na start Uruchomienia i kończy na jej wartościach.
Zła treść pliku to złe ustawienie (``Bad``) z ostatnią dobrą wartością z pamięci, nigdy wyjątek ani błąd startu.

Każdy odczyt i każdy zapis idzie pod jedną blokadą i zaczyna się od porównania stanu pliku (brak pliku albo jego
bajty) z ostatnim stanem przyjętym w pamięci (``memory``). Inny stan to zmiana spoza Centrum i dokładnie jeden wiersz
Historii: ``spoza`` z różnicą kluczy od ostatniej dobrej wartości (przy usuniętym pliku z ``removed``) albo
``odrzucono`` przy złej treści, po którym wartość robocza zostaje ostatnią dobrą. Potem pamięć przyjmuje ten stan, także
złą treść i brak pliku, więc ten sam stan nie daje drugiego wiersza, a powrót do wcześniejszego stanu daje nowy.
Pamięci nie ma tylko przed pierwszym odczytem po Wydaniu: wtedy plik, jaki jest (także zły albo żaden), staje się stanem
wyjściowym bez wiersza, a każda późniejsza zmiana ma już wiersz. Wiersz, którego nie da się dopisać, zostawia pamięć bez
zmiany, więc następny odczyt próbuje znowu; pamięć, której nie da się zapisać po wierszu, daje najwyżej powtórzony
wiersz. Pamięci, której system nie daje teraz czytać, odczyt nie porównuje (bez wiersza i bez zapisu), a zapis taty
odmawia.

Zapis: odczyt z wykryciem zmiany spoza Centrum, zmiana bieżącej wartości (przy złym pliku ostatniej dobrej), ta sama
reguła ``parse`` co dla pliku, atomowa zamiana pliku, wiersz Historii, pamięć i linia w dzienniku Centrum bez wartości.
Wiersz, którego nie da się dopisać, przywraca poprzednią treść pliku, więc każda zmiana, która weszła, ma wiersz.
Zgaśnięcie po zamianie pliku przed wierszem daje przy następnym odczycie wiersz ``spoza`` z poprawną różnicą, tylko ze
złym źródłem, a zgaśnięcie po wierszu przed pamięcią do tego jeszcze powtórzony wiersz ``spoza``; zmiany bez wiersza
nie daje żadne miejsce. Cofnięcie to nowy zapis wartości sprzed zmiany, z tymi samymi sprawdzeniami.

Moduł nie wczytuje FastAPI: czyta go też katalog procesów i gospodarze Uruchomień, a interfejs HTTP jest w
``settings_router``. Narzędzia i Skrypt dla maszyn czytają przez ``read_snapshot``, które niczego nie pisze.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import threading
from typing import Final, TypeVar
import uuid

from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S, replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.settings.files import Bad, FieldProblem, Good, KeyChange, Read, SettingsFile, Unreadable
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings
from rozliczenia.centrum.settings.history import History, HistoryRead, HistoryRow, RowChange, RowSource, SourceKind
from rozliczenia.centrum.settings.memory import Memory, Remembered, settings_bytes

T = TypeVar("T")

REPORTED_CHANGES: Final = 20
"""Najwyżej tyle najnowszych wierszy Historii podaje Zgłoszenie."""


@dataclass(frozen=True)
class SettingsSnapshot:
    """Wartości Ustawień Centrum z jednej chwili: dobre, a przy złym pliku ostatnie dobre albo domyślne."""

    folders: FolderSettings


@dataclass(frozen=True)
class SettingsView:
    """Ustawienia Centrum dla okna Ustawień: każda sekcja z wartością albo złym ustawieniem."""

    folders: Read[FolderSettings] | Unreadable


@dataclass(frozen=True)
class Saved:
    """Zmiana zapisana; ``change``: id jej wiersza Historii, ``None``: zmiana niczego nie zmieniła i nie ma wiersza."""

    change: str | None


@dataclass(frozen=True)
class Refused:
    """Zła wartość: nic się nie zapisało, a ``problem`` mówi, które pole poprawić."""

    problem: FieldProblem


@dataclass(frozen=True)
class NotSaved:
    """Pliku albo Historii nie dało się przeczytać lub zapisać, więc nic się nie zmieniło."""


@dataclass(frozen=True)
class NotUndoable:
    """Wiersza Historii nie da się cofnąć: nie ma go (``known=False``), jest odrzucony albo jest sekretem."""

    known: bool


class CentrumSettings:
    def __init__(
        self, config: Path, *, log: CentrumLog, now: Callable[[], datetime], pause: Callable[[float], None]
    ) -> None:
        """Ustawienia w folderze ``config``; ``now`` daje chwilę wiersza Historii, a ``pause`` czeka przed kolejną próbą
        odczytu albo zapisu pliku, który system na chwilę trzyma."""

        self._config = config
        self._log = log
        self._now = now
        self._pause = pause
        self._memory = Memory(config, pause)
        self._history = History(config, pause)
        self._lock = threading.Lock()

    def snapshot(self) -> SettingsSnapshot:
        """Wartości dla procesu: raz na start Uruchomienia, który kończy na nich bez względu na późniejsze zmiany."""

        with self._lock:
            return SettingsSnapshot(folders=_usable(self._observe(FOLDERS), FOLDERS))

    def view(self) -> SettingsView:
        with self._lock:
            return SettingsView(folders=self._observe(FOLDERS))

    def change(self, file: SettingsFile[T], edit: Callable[[T], T]) -> Saved | Refused | NotSaved:
        """Zapis taty: ``edit`` dostaje bieżącą wartość pliku (przy złym pliku ostatnią dobrą) i daje nową."""

        with self._lock:
            return self._change(file, edit, undoes=None)

    def undo(self, row_id: str) -> Saved | Refused | NotSaved | NotUndoable:
        """Cofnięcie wiersza Historii: nowy zapis taty z wartościami sprzed tej zmiany; cofnięcie cofnięcia też."""

        with self._lock:
            row = next((row for row in self._history.read().rows if row.id == row_id), None)
            if row is None:
                return NotUndoable(known=False)
            file = _FILES.get(row.file)
            if file is None or not row.undoable or row.result != "zapisano":
                return NotUndoable(known=True)
            changes = row.key_changes()
            return self._undo(file, changes, row.id)

    def history(self) -> HistoryRead:
        with self._lock:
            return self._history.read()

    def reported_changes(self, days: int = 30) -> tuple[str, ...]:
        """Linie Zgłoszenia o zmianach z ostatnich ``days`` dni (najwyżej ``REPORTED_CHANGES``, od najnowszej): kiedy,
        skąd, klucze i tylko wartości bez danych osobowych (folder samą nazwą, motyw), sekret samym znacznikiem."""

        since = self._now() - timedelta(days=days)
        rows = [row for row in self.history().rows if row.at >= since][:REPORTED_CHANGES]
        return tuple(_reported(row) for row in rows)

    def _undo(self, file: SettingsFile[T], changes: tuple[KeyChange, ...], row_id: str) -> Saved | Refused | NotSaved:
        return self._change(file, lambda current: file.restore(current, changes), undoes=row_id)

    def _change(self, file: SettingsFile[T], edit: Callable[[T], T], *, undoes: str | None) -> Saved | Refused | NotSaved:
        data = self._bytes_for_change(file)
        if isinstance(data, Unreadable) or isinstance(self._memory.read(file.name), Unreadable):
            self._log.settings_unreadable(cause="dostep")
            return NotSaved()
        observed = self._observed(file, data)
        current = _usable(observed, file)
        new = file.dump(edit(current)).encode("utf-8")
        edited = file.parse(new)
        if isinstance(edited, FieldProblem):
            return Refused(edited)
        changes = file.diff(current, edited)
        if not changes and isinstance(observed, Good):
            return Saved(change=None)
        if isinstance(observed, Bad) and data is not None:
            self._memory.keep_rejected(file.name, data, self._now())
        row = self._row(file, changes, "tata", undoes=undoes) if changes else None
        try:
            replace_atomically(self._config / file.name, new, pause=self._pause)
        except OSError:
            return NotSaved()
        if row is not None:
            try:
                self._history.append(row)
            except OSError:
                self._put_back(file, data)
                return NotSaved()
        self._remember(file, Remembered(seen=new, good=new))
        if row is None:
            return Saved(change=None)
        self._log.settings_changed(file=file.name, keys=tuple(change.key for change in changes), source="tata")
        return Saved(change=row.id)

    def _put_back(self, file: SettingsFile[T], data: bytes | None) -> None:
        """Poprzednia treść pliku po zapisie, którego wiersza nie dało się dopisać; pamięć jeszcze jej nie zmieniła.
        Treść, której nie da się przywrócić, wyrówna następny odczyt jako zmianę spoza Centrum."""

        try:
            if data is None:
                (self._config / file.name).unlink(missing_ok=True)
            else:
                replace_atomically(self._config / file.name, data, pause=self._pause)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="przywrócenie Ustawień po nieudanym wierszu Historii")

    def _remember(self, file: SettingsFile[T], remembered: Remembered) -> None:
        """Pamięć po wierszu Historii; nieudana daje przy następnym odczycie powtórzony wiersz, nie zmianę bez wiersza."""

        try:
            self._memory.write(file.name, remembered)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="pamięć Ustawień")

    def _bytes_for_change(self, file: SettingsFile[T]) -> bytes | None | Unreadable:
        """Bajty pliku przed zmianą; plik, którego system nie daje czytać, czyta ponownie po kolejnych przerwach."""

        data = settings_bytes(self._config / file.name)
        for seconds in RETRY_PAUSES_S:
            if not isinstance(data, OSError):
                break
            self._pause(seconds)
            data = settings_bytes(self._config / file.name)
        return Unreadable() if isinstance(data, OSError) else data

    def _observe(self, file: SettingsFile[T]) -> Read[T] | Unreadable:
        data = settings_bytes(self._config / file.name)
        if isinstance(data, OSError):
            return Unreadable()
        return self._observed(file, data)

    def _observed(self, file: SettingsFile[T], data: bytes | None) -> Read[T]:
        """Wartość pliku w stanie ``data`` (``None``: brak pliku) po porównaniu z pamięcią: stan wyjściowy bez wiersza,
        ten sam stan bez niczego albo zmiana spoza Centrum z jednym wierszem."""

        parsed = file.parse(data)
        remembered = self._memory.read(file.name)
        if isinstance(remembered, Unreadable):
            return _read(parsed, None)
        if remembered is None:
            if isinstance(parsed, FieldProblem):
                self._log.settings_bad(file=file.name, field=parsed.field or "plik")
            self._remember(file, Remembered(seen=data, good=None if isinstance(parsed, FieldProblem) else data))
            return _read(parsed, None)
        before = _good_value(remembered.good, file)
        if data == remembered.seen:
            return _read(parsed, before)
        try:
            self._history.append(self._outside_row(file, data, parsed, before))
        except OSError:
            self._log.settings_external(file=file.name, result="bez-zapisu")
            return _read(parsed, before)
        self._remember(file, Remembered(seen=data, good=remembered.good if isinstance(parsed, FieldProblem) else data))
        if isinstance(parsed, FieldProblem):
            self._log.settings_bad(file=file.name, field=parsed.field or "plik")
            self._log.settings_external(file=file.name, result="odrzucono")
            return Bad(parsed, before)
        self._log.settings_external(file=file.name, result="zapisano")
        return Good(parsed)

    def _outside_row(self, file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem, before: T) -> HistoryRow:
        """Wiersz zmiany spoza Centrum: zła treść ``odrzucono`` z powodem, dobra treść albo brak pliku różnica kluczy od
        ostatniej dobrej wartości (bez różnicy bez „Cofnij”)."""

        if isinstance(parsed, FieldProblem):
            return self._row(file, (), "spoza", undoes=None).model_copy(
                update={"result": "odrzucono", "reason": parsed.sentence, "undoable": False, "removed": data is None}
            )
        row = self._row(file, file.diff(before, parsed), "spoza", undoes=None)
        return row.model_copy(update={"undoable": row.undoable and bool(row.changes), "removed": data is None})

    def _row(
        self, file: SettingsFile[T], changes: tuple[KeyChange, ...], source: SourceKind, *, undoes: str | None
    ) -> HistoryRow:
        sections = {change.key.partition(".")[0] for change in changes}
        return HistoryRow(
            id=uuid.uuid4().hex,
            at=self._now(),
            source=RowSource(kind=source),
            undoes=undoes,
            file=file.name,
            section=next(iter(sections)) if len(sections) == 1 else None,
            changes=tuple(RowChange.of(change) for change in changes) if not file.secret else (),
            secret=file.secret,
            undoable=not file.secret,
            result="zapisano",
            reason=None,
        )


_FILES: Final[dict[str, SettingsFile[FolderSettings]]] = {FOLDERS.name: FOLDERS}


def read_snapshot(config: Path) -> SettingsSnapshot:
    """Migawka bez zapisu dla narzędzi i Skryptu dla maszyn: plik, przy złej treści ostatnia dobra z pamięci właściciela
    albo wartości domyślne; nie dopisuje Historii ani pamięci."""

    data = settings_bytes(config / FOLDERS.name)
    if isinstance(data, OSError):
        return SettingsSnapshot(folders=FOLDERS.default)
    parsed = FOLDERS.parse(data)
    if not isinstance(parsed, FieldProblem):
        return SettingsSnapshot(folders=parsed)
    remembered = Memory(config, lambda _: None).read(FOLDERS.name)
    good = remembered.good if isinstance(remembered, Remembered) else None
    return SettingsSnapshot(folders=_good_value(good, FOLDERS))


def _good_value(good: bytes | None, file: SettingsFile[T]) -> T:
    """Wartość ostatniej dobrej treści z pamięci; brak pliku albo treść, której ``parse`` dziś nie przyjmuje, to wartości
    domyślne pliku."""

    parsed = file.parse(good)
    return file.default if isinstance(parsed, FieldProblem) else parsed


def _read(parsed: T | FieldProblem, usable: T | None) -> Read[T]:
    return Bad(parsed, usable) if isinstance(parsed, FieldProblem) else Good(parsed)


def _usable(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T:
    match observed:
        case Good(value=value):
            return value
        case Bad(usable=usable):
            return file.default if usable is None else usable
        case Unreadable():
            return file.default


def _reported(row: HistoryRow) -> str:
    source = {"tata": "tata", "spoza": "spoza Centrum"}[row.source.kind]
    head = f"- {row.at:%Y-%m-%d %H:%M} · {source} · {row.file}"
    if row.result == "odrzucono":
        return f"{head} · odrzucono: {row.reason}"
    file = _FILES.get(row.file)
    if row.secret or file is None:
        return f"{head} · zmieniono: " + ", ".join(change.key for change in row.changes)
    undo = " · cofnięcie" if row.undoes is not None else ""
    removed = " · usunięto plik" if row.removed else ""
    return f"{head}{undo}{removed} · " + "; ".join(
        f"{change.key}: {file.shown(change.key, change.before)} → {file.shown(change.key, change.after)}"
        for change in row.changes
    )
