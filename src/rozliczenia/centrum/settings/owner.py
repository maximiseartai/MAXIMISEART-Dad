"""Ustawienia Centrum: jedyny czytelnik i pisarz plików Ustawień w ``config``, ich Historii i pamięci (ADR 0032).

Na start obejmuje plik Folderów i motywu (``folders``). ``CentrumSettings`` czyta go przy każdym odczycie od nowa, więc
zmiana działa od razu, a proces dostaje jedną migawkę (``snapshot``) na start Uruchomienia i kończy na jej wartościach.
Zła treść pliku to złe ustawienie (``Bad``) z ostatnią dobrą wartością z pamięci, nigdy wyjątek ani błąd startu.

Każdy odczyt i każdy zapis idzie pod jedną blokadą i zaczyna się od porównania bajtów pliku z pamięcią
(``memory``). Różne bajty to zmiana spoza Centrum: dobra treść dostaje wiersz Historii ``spoza`` i staje się pamięcią,
zła treść daje jeden wiersz ``odrzucono`` na tę samą treść, a pamięć zostaje. Pierwszy odczyt bez pamięci przyjmuje
dobry plik jako stan wyjściowy bez wiersza, więc plik założony ręcznie tam, gdzie Centrum nie pamięta żadnego, też nie
ma wiersza.

Zapis: odczyt z wykryciem zmiany spoza Centrum, zmiana bieżącej wartości (przy złym pliku ostatniej dobrej), ta sama
reguła ``parse`` co dla pliku, atomowa zamiana pliku, pamięć, wiersz Historii i linia w dzienniku Centrum bez wartości.
Wiersz, którego nie da się dopisać, przywraca poprzednią treść pliku i pamięci, więc każda zmiana, która weszła, ma
wiersz. Zgaśnięcie między zamianą pliku a pamięcią daje przy następnym odczycie wiersz ``spoza`` z poprawną różnicą,
tylko ze złym źródłem. Cofnięcie to nowy zapis wartości sprzed zmiany, z tymi samymi sprawdzeniami.

Moduł nie wczytuje FastAPI: czyta go też katalog procesów i gospodarze Uruchomień, a interfejs HTTP jest w
``settings_router``. Narzędzia i Skrypt dla maszyn czytają przez ``read_snapshot``, które niczego nie pisze.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import threading
from typing import Final, TypeVar
import uuid

from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S, replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.settings.files import Bad, FieldProblem, Good, KeyChange, Read, SettingsFile, Unreadable
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings
from rozliczenia.centrum.settings.history import History, HistoryRead, HistoryRow, RowChange, RowSource, SourceKind
from rozliczenia.centrum.settings.memory import Memory, settings_bytes

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
        self._bad_logged: dict[str, bytes] = {}

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
        if isinstance(data, Unreadable):
            self._log.settings_unreadable(cause="dostep")
            return NotSaved()
        observed = self._observed(file, data)
        current = _usable(observed, file)
        text = file.dump(edit(current))
        new = text.encode("utf-8")
        edited = file.parse(new)
        if isinstance(edited, FieldProblem):
            return Refused(edited)
        changes = file.diff(current, edited)
        if not changes and isinstance(observed, Good):
            return Saved(change=None)
        if isinstance(observed, Bad) and data is not None:
            self._memory.keep_rejected(file.name, data, self._now())
        row = self._row(file, changes, "tata", undoes=undoes) if changes else None
        remembered = self._memory.remembered(file.name)
        try:
            replace_atomically(self._config / file.name, new, pause=self._pause)
        except OSError:
            return NotSaved()
        try:
            self._memory.remember(file.name, new)
            if row is not None:
                self._history.append(row)
        except OSError:
            self._put_back(file, data, remembered)
            return NotSaved()
        if row is None:
            return Saved(change=None)
        self._log.settings_changed(file=file.name, keys=tuple(change.key for change in changes), source="tata")
        return Saved(change=row.id)

    def _put_back(self, file: SettingsFile[T], data: bytes | None, remembered: bytes | None) -> None:
        """Poprzednia treść pliku i pamięci po zapisie, którego wiersza nie dało się dopisać; to, czego nie da się
        przywrócić, wyrówna następny odczyt jako zmianę spoza Centrum."""

        try:
            if data is None:
                (self._config / file.name).unlink(missing_ok=True)
            else:
                replace_atomically(self._config / file.name, data, pause=self._pause)
            self._memory.remember(file.name, remembered)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="przywrócenie Ustawień po nieudanym wierszu Historii")

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
        """Wartość pliku o bajtach ``data`` po porównaniu z pamięcią (zmiana spoza Centrum, stan wyjściowy)."""

        parsed = file.parse(data)
        remembered = self._memory.remembered(file.name)
        if data == remembered:
            return _read(parsed, None)
        before = None if remembered is None else file.parse(remembered)
        if isinstance(before, FieldProblem):
            before = None
        if isinstance(parsed, FieldProblem):
            self._outside_bad(file, data, parsed, first=before is None)
            return Bad(parsed, before)
        if before is None:
            self._accept(file, data, ())
        else:
            self._accept(file, data, file.diff(before, parsed))
        return Good(parsed)

    def _accept(self, file: SettingsFile[T], data: bytes | None, changes: tuple[KeyChange, ...]) -> None:
        """Przyjmuje dobrą treść spoza Centrum: wiersz ``spoza`` z różnicą (bez różnicy bez wiersza), potem pamięć."""

        try:
            if changes:
                self._history.append(self._row(file, changes, "spoza", undoes=None))
            self._memory.remember(file.name, data)
        except OSError:
            self._log.settings_external(file=file.name, result="bez-zapisu")
            return
        if changes:
            self._log.settings_external(file=file.name, result="zapisano")

    def _outside_bad(self, file: SettingsFile[T], data: bytes | None, problem: FieldProblem, *, first: bool) -> None:
        """Zła treść: linia w dzienniku raz na treść w tej pracy Centrum, a po dobrej pamięci także wiersz ``odrzucono``
        raz na tę samą treść (porównanie z ostatnim takim wierszem pliku)."""

        content = b"" if data is None else data
        if self._bad_logged.get(file.name) != content:
            self._bad_logged[file.name] = content
            self._log.settings_bad(file=file.name, field=problem.field or "plik")
        if first:
            return
        fingerprint = hashlib.sha256(content).hexdigest()[:16]
        last = next(
            (row for row in self._history.read().rows if row.file == file.name and row.result == "odrzucono"), None
        )
        if last is not None and last.fingerprint == fingerprint:
            return
        row = self._row(file, (), "spoza", undoes=None).model_copy(
            update={"result": "odrzucono", "reason": problem.sentence, "undoable": False, "fingerprint": fingerprint}
        )
        try:
            self._history.append(row)
        except OSError:
            self._log.settings_external(file=file.name, result="bez-zapisu")
            return
        self._log.settings_external(file=file.name, result="odrzucono")

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
    remembered = Memory(config, lambda _: None).remembered(FOLDERS.name)
    usable = None if remembered is None else FOLDERS.parse(remembered)
    return SettingsSnapshot(folders=FOLDERS.default if usable is None or isinstance(usable, FieldProblem) else usable)


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
    return f"{head}{undo} · " + "; ".join(
        f"{change.key}: {file.shown(change.key, change.before)} → {file.shown(change.key, change.after)}"
        for change in row.changes
    )
