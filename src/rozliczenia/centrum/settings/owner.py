"""Ustawienia Centrum: jedyny czytelnik i pisarz plików Ustawień w ``config``, ich Historii i pamięci (ADR 0032).

Obejmuje plik Folderów i motywu (``folders``), Listę Wykonawców (``workers``), Przypomnienia o raporcie
(``reminders``), plik dostępu do skrzynki raportów
(``inbox``), który jest sekretem: jego wiersz Historii ma same klucze bez wartości i nie ma „Cofnij”, a pamięć trzyma
tylko odcisk jego treści, bez ostatniej dobrej treści i bez kopii złej treści w ``odrzucone``, przełącznik startu
razem z Windows (``autostart``), którego stan to skrót w folderze Autostart, a nie plik w ``config``, oraz pliki Reguł
ilości i Listy Urządzeń (``quantity_rules``). Każde ustawienie ma swoje miejsce (``_Place``), z którego właściciel
czyta stan i do którego go zapisuje, a reszta drogi jest wspólna. ``CentrumSettings`` czyta je przy każdym odczycie od
nowa, więc zmiana działa od razu, a proces dostaje jedną migawkę (``snapshot``) na start Uruchomienia i kończy na jej
wartościach.
Zła treść pliku to złe ustawienie (``Bad``) z ostatnią dobrą wartością z pamięci, nigdy wyjątek ani błąd startu.
Reguły ilości i Lista Urządzeń mają do tego jeden wspólny niezmiennik: każde przyjęcie jednego z nich (``_checked``: odczyt,
zapis, cofnięcie) sprawdza go razem z drugim, więc plik, który do drugiego nie pasuje, jest zły tak samo jak plik z
uszkodzoną treścią, a procesy liczą ostatnią dobrą parą. Plik, który zaczyna pasować dopiero po zmianie drugiego, ma
wtedy wiersz ``spoza`` jak zmiana jego treści.

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

Zmiany z Wydania (``release_changes``) właściciel stosuje przy starcie Centrum, przed pierwszym zapytaniem, tym samym
zapisem co zmianę taty, tylko ze źródłem ``wydanie``. Co już weszło, mówią dwa źródła: pamięć zmian z Wydań i wiersze
Historii z id zmiany. Zmiany stosują się tylko wtedy, gdy oba dają się przeczytać: pamięć, której nie da się przeczytać
(``AppliedUnknown``), albo Historia, której system nie daje teraz czytać (``Unreadable``), wstrzymuje przy tym starcie
każdą zmianę z linią w dzienniku Centrum, a następny start próbuje znowu, bo bez nich zmiana cofnięta przez tatę weszłaby
jeszcze raz. Historię start czyta tylko wtedy, gdy pamięć nie ma którejś zmiany.
Odrzucona migracja, której pliku dalej nie ma (``ReleaseChange.refused_absent``), i migracja, która przy tym starcie
czeka (``Later``, ``ReleaseChange.waiting_absent``), dają złe ustawienie bez ostatniej dobrej wartości zamiast wartości
domyślnych, więc tata nie widzi pustej dobrej Listy Wykonawców, a proces bez niej nie startuje; wie o tym tylko praca
Centrum, która przy starcie przeczytała pamięć zmian z Wydań (nie ``read_snapshot``).
Każda zmiana z wynikiem (weszła, nic do zmiany, odrzucona) trafia do pamięci i już nie wraca; ``Later``, wyjątek w kodzie
zmiany i zapis, który się nie udał (także wiersz ``odrzucono``, którego nie da się dopisać), wracają przy następnym
starcie. Kolejność to plik → wiersz Historii → pamięć pliku → pamięć zmian z Wydań, a zmianę z wierszem Historii o jej id
(``zapisano`` albo ``odrzucono``) start uznaje za zastosowaną i dopisuje do pamięci, więc przerwa albo nieudany zapis
pamięci po wierszu nie puszcza zmiany drugi raz, także po cofnięciu przez tatę. Przerwa przed wierszem zostawia zmianę
do ponownego zastosowania, a edycja deklaratywna nie daje wtedy drugiej różnicy.
Granice: wynik bez wiersza (nic do zmiany) z nieudanym zapisem pamięci wraca przy następnym starcie, więc wartość, którą
tata potem zmienił, edycja ustawi znowu. Historia czytelna, ale bez wiersza zmiany (linia urwana zgaśnięciem albo plik
zmieniony poza Centrum) przy pamięci bez tej zmiany puszcza ją jeszcze raz, tak samo jak pamięć utracona w całości
(usunięty folder).

Moduł nie wczytuje FastAPI: czyta go też katalog procesów i gospodarze Uruchomień, a interfejs HTTP jest w
``settings_router``. Narzędzia i Skrypt dla maszyn czytają przez ``read_snapshot``, które niczego nie pisze.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re
import threading
from typing import Any, Final, Literal, Protocol, TypeVar
import uuid

from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S, replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import Autostart
from rozliczenia.centrum.settings.autostart import AUTOSTART, AutostartPlace, Unsupported
from rozliczenia.centrum.settings.files import Bad, FieldProblem, Good, KeyChange, Read, SettingsFile, Unreadable
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings
from rozliczenia.centrum.settings import inbox
from rozliczenia.centrum.settings.inbox import INBOX, InboxFile
from rozliczenia.centrum.settings.history import (
    ByDad,
    FromRelease,
    History,
    HistoryRead,
    HistoryRow,
    Outside,
    ReleaseOrigin,
    RowChange,
    RowSource,
)
from rozliczenia.centrum.settings.memory import Applied, AppliedResult, AppliedUnknown, Memory, Remembered, settings_bytes
from rozliczenia.centrum.settings.proposal import Edit, Later, Nothing, Refuse, ReleaseChange, ReleaseInputs
from rozliczenia.centrum.settings import messages
from rozliczenia.centrum.settings.quantity_rules import DEVICES, RULES, devices_problem, quantity_rules, rules_problem
from rozliczenia.centrum.settings.reminders import REMINDERS
from rozliczenia.centrum.settings.workers import WORKERS
from rozliczenia.quantity_engine import Component, QuantityRule, QuantityRules
from rozliczenia.worker_list import WorkerList
from rozliczenia.worker_report_inbox import InboxState
from rozliczenia.worker_reports import ReminderSettings

T = TypeVar("T")

REPORTED_CHANGES: Final = 20
"""Najwyżej tyle najnowszych wierszy Historii podaje Zgłoszenie."""
HISTORY_UNREADABLE: Final = "- Historii Ustawień nie dało się przeczytać"
_Later = Literal["pozniej"]
_LATER: Final[_Later] = "pozniej"
"""Linia Zgłoszenia zamiast zmian, gdy system nie daje czytać pliku Historii."""


@dataclass(frozen=True)
class SettingsSnapshot:
    """Wartości Ustawień Centrum z jednej chwili. Foldery i Przypomnienia o raporcie: dobre, a przy złym pliku ostatnie
    dobre albo domyślne. Lista Wykonawców ze złym ustawieniem, bo proces bez ostatniej dobrej listy nie startuje
    (``workers_usable``)."""

    folders: FolderSettings
    workers: Read[WorkerList] | Unreadable
    inbox: InboxState
    reminders: ReminderSettings
    quantity_rules: QuantityRules
    """Reguły ilości z Listą Urządzeń, którymi liczy Uruchomienie: przy złym pliku albo pliku, który nie pasuje do
    drugiego, ostatnia dobra para."""


@dataclass(frozen=True)
class QuantityRulesView:
    """Reguły ilości dla okna Ustawień: te, którymi liczy następne Uruchomienie, i problem każdego pliku (``None``:
    plik dobry). Plik, który nie pasuje do drugiego, ma problem jak zły plik."""

    rules: QuantityRules
    rules_problem: FieldProblem | None
    devices_problem: FieldProblem | None


@dataclass(frozen=True)
class SettingsView:
    """Ustawienia Centrum dla okna Ustawień: każda sekcja z wartością albo złym ustawieniem."""

    folders: Read[FolderSettings] | Unreadable
    workers: Read[WorkerList] | Unreadable
    inbox: Read[InboxFile] | Unreadable
    autostart: Read[bool] | Unreadable | Unsupported
    reminders: Read[ReminderSettings] | Unreadable


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


class _Place(Protocol):
    """Miejsce stanu jednego ustawienia: plik w ``config`` albo skrót w folderze Autostart."""

    def unsupported(self) -> FieldProblem | None:
        """Odmowa każdej zmiany, gdy tego ustawienia na tym komputerze nie ma; ``None``: ustawienie działa."""

    def read(self) -> bytes | None | OSError:
        """Stan: treść albo ``None`` (brak pliku); ``OSError``, gdy system nie daje go teraz przeczytać."""

    def write(self, data: bytes | None) -> None:
        """Zapisuje stan (``None``: usuwa plik); ``OSError``, gdy się nie udało."""


@dataclass(frozen=True)
class _ConfigFile:
    path: Path
    pause: Callable[[float], None]

    def unsupported(self) -> FieldProblem | None:
        return None

    def read(self) -> bytes | None | OSError:
        return settings_bytes(self.path)

    def write(self, data: bytes | None) -> None:
        if data is None:
            self.path.unlink(missing_ok=True)
        else:
            replace_atomically(self.path, data, pause=self.pause)


class CentrumSettings:
    def __init__(
        self,
        config: Path,
        *,
        log: CentrumLog,
        now: Callable[[], datetime],
        pause: Callable[[float], None],
        autostart: Autostart,
    ) -> None:
        """Ustawienia w folderze ``config`` i skrót Centrum w folderze Autostart (``autostart``); ``now`` daje chwilę
        wiersza Historii, a ``pause`` czeka przed kolejną próbą odczytu albo zapisu pliku, który system na chwilę
        trzyma."""

        self._config = config
        self._log = log
        self._now = now
        self._pause = pause
        self._memory = Memory(config, pause)
        self._history = History(config, pause)
        self._lock = threading.Lock()
        self._absent: dict[str, str] = {}
        self._places: Mapping[str, _Place] = {
            FOLDERS.name: _ConfigFile(config / FOLDERS.name, pause),
            WORKERS.name: _ConfigFile(config / WORKERS.name, pause),
            REMINDERS.name: _ConfigFile(config / REMINDERS.name, pause),
            INBOX.name: _ConfigFile(config / INBOX.name, pause),
            AUTOSTART.name: AutostartPlace(autostart),
            DEVICES.name: _ConfigFile(config / DEVICES.name, pause),
            RULES.name: _ConfigFile(config / RULES.name, pause),
        }

    def snapshot(self) -> SettingsSnapshot:
        """Wartości dla procesu: raz na start Uruchomienia, który kończy na nich bez względu na późniejsze zmiany."""

        with self._lock:
            return SettingsSnapshot(
                folders=_usable(self._observe(FOLDERS), FOLDERS),
                workers=self._observe(WORKERS),
                inbox=inbox.state(self._observe(INBOX)),
                reminders=_usable(self._observe(REMINDERS), REMINDERS),
                quantity_rules=self._quantity_rules().rules,
            )

    def quantity_rules(self) -> QuantityRulesView:
        """Reguły ilości i Lista Urządzeń dla okna Ustawień, każdy plik porównany z pamięcią jak przy każdym odczycie."""

        with self._lock:
            return self._quantity_rules()

    def view(self) -> SettingsView:
        with self._lock:
            autostart = self._places[AUTOSTART.name].unsupported()
            return SettingsView(
                folders=self._observe(FOLDERS),
                workers=self._observe(WORKERS),
                inbox=self._observe(INBOX),
                autostart=Unsupported() if autostart is not None else self._observe(AUTOSTART),
                reminders=self._observe(REMINDERS),
            )

    def change(self, file: SettingsFile[T], edit: Callable[[T], T]) -> Saved | Refused | NotSaved:
        """Zapis taty: ``edit`` dostaje bieżącą wartość pliku (przy złym pliku ostatnią dobrą) i daje nową."""

        with self._lock:
            return self._change(file, edit, undoes=None, source=ByDad(), undoable=True)

    def undo(self, row_id: str) -> Saved | Refused | NotSaved | NotUndoable:
        """Cofnięcie wiersza Historii: nowy zapis taty z wartościami sprzed tej zmiany; cofnięcie cofnięcia też."""

        with self._lock:
            history = self._history.read()
            if isinstance(history, Unreadable):
                self._log.settings_unreadable(cause="historia")
                return NotSaved()
            row = next((row for row in history.rows if row.id == row_id), None)
            if row is None:
                return NotUndoable(known=False)
            file = _UNDOABLE.get(row.file)
            if file is None or not row.undoable or row.result != "zapisano":
                return NotUndoable(known=True)
            changes = row.key_changes()
            return self._undo(file, changes, row.id)

    def history(self) -> HistoryRead | Unreadable:
        """Historia od najnowszego wiersza; najpierw, jak każdy odczyt, porównanie plików z pamięcią, więc zmiana spoza
        Centrum ma już swój wiersz, gdy tata otwiera Historię."""

        with self._lock:
            for file in _FILES.values():
                if self._places[file.name].unsupported() is None:
                    self._observe(file)
            return self._history.read()

    def apply_release_changes(
        self, changes: tuple[ReleaseChange[Any], ...], origin: Callable[[], ReleaseOrigin]
    ) -> None:
        """Zmiany z Wydania, których pamięć jeszcze nie ma, po kolei; ``origin`` daje wersję narzędzia do Historii i
        pyta Gita tylko wtedy, gdy jest co zastosować. Niczego nie podnosi: start Centrum nie pada na zmianie z Wydania."""

        with self._lock:
            applied = self._memory.applied()
            if isinstance(applied, AppliedUnknown):
                for change in changes:
                    self._log.settings_release(change=change.id, result="bez-pamieci")
                return
            waiting = self._apply_pending(changes, applied, origin)
            self._absent = {
                change.file.name: sentence
                for change in changes
                if (sentence := _absent_sentence(change, applied, waiting)) is not None
            }

    def _apply_pending(
        self, changes: tuple[ReleaseChange[Any], ...], applied: dict[str, Applied], origin: Callable[[], ReleaseOrigin]
    ) -> frozenset[str]:
        """Zmiany, których pamięć ``applied`` jeszcze nie ma; każda z wynikiem trafia do ``applied`` i do pamięci.
        Daje id zmian, które dały ``Later``."""

        pending = [change for change in changes if change.id not in applied]
        if not pending:
            return frozenset()
        in_history = self._release_rows()
        if isinstance(in_history, Unreadable):
            for change in pending:
                self._log.settings_release(change=change.id, result="bez-historii")
            return frozenset()
        version: ReleaseOrigin | None = None
        waiting: set[str] = set()
        for change in pending:
            done = in_history.get(change.id)
            if done is None:
                version = version or origin()
                try:
                    result = self._apply(change, version)
                except Exception as failure:
                    self._log.unexpected_failure(failure, where=f"zmiana Ustawień z Wydania {change.id}")
                    continue
                if result == _LATER:
                    waiting.add(change.id)
                    continue
                if result is None:
                    continue
                done = Applied(at=self._now(), release=version.release, commit=version.commit, result=result)
            applied[change.id] = done
            try:
                self._memory.remember_applied(applied)
            except OSError:
                self._log.settings_release(change=change.id, result="bez-pamieci")
        return frozenset(waiting)

    def _release_rows(self) -> dict[str, Applied] | Unreadable:
        """Zmiany z Wydania, które mają wiersz Historii, choć pamięć ich nie ma: wiersz idzie przed pamięcią, więc zmiana z
        wierszem weszła (albo została odrzucona) i nie wraca, także gdy tata ją już cofnął."""

        history = self._history.read()
        if isinstance(history, Unreadable):
            return history
        found: dict[str, Applied] = {}
        for row in history.rows:
            if isinstance(row.source, FromRelease) and row.source.change not in found:
                found[row.source.change] = Applied(
                    at=row.at,
                    release=row.source.release,
                    commit=row.source.commit,
                    result="zastosowano" if row.result == "zapisano" else "odrzucono",
                )
        return found

    def _apply(self, change: ReleaseChange[T], version: ReleaseOrigin) -> AppliedResult | _Later | None:
        """Jedna zmiana z Wydania; ``_LATER`` (zmiana dała ``Later``) i ``None`` wracają przy następnym starcie."""

        source = FromRelease(release=version.release, commit=version.commit, change=change.id)
        match change.propose(ReleaseInputs(self._observe(change.file), self._config)):
            case Nothing():
                result: AppliedResult | None = "bez-zmian"
            case Later():
                self._log.settings_release(change=change.id, result="pozniej")
                return _LATER
            case Refuse(sentence=sentence):
                result = self._refuse(change.file, source, sentence)
            case Edit(edit=edit, undoable=undoable):
                match self._change(change.file, edit, undoes=None, source=source, undoable=undoable):
                    case Saved(change=row):
                        result = "bez-zmian" if row is None else "zastosowano"
                    case Refused(problem=problem):
                        result = self._refuse(change.file, source, problem.sentence)
                    case NotSaved():
                        result = None
        self._log.settings_release(change=change.id, result="bez-zapisu" if result is None else result)
        return result

    def _refuse(self, file: SettingsFile[T], source: FromRelease, sentence: str) -> AppliedResult | None:
        """Wiersz ``odrzucono`` zmiany z Wydania z powodem; ``None``: wiersza nie dało się dopisać, zmiana wraca."""

        row = self._row(file, (), source, undoes=None, undoable=False).model_copy(
            update={"result": "odrzucono", "reason": sentence}
        )
        try:
            self._history.append(row)
        except OSError:
            return None
        return "odrzucono"

    def reported_changes(self, days: int = 30) -> tuple[str, ...]:
        """Linie Zgłoszenia o zmianach z ostatnich ``days`` dni (najwyżej ``REPORTED_CHANGES``, od najnowszej): kiedy,
        skąd, klucze i tylko wartości bez danych osobowych (folder samą nazwą, motyw), sekret samym znacznikiem;
        przy Historii, której system nie daje czytać, jedna linia ``HISTORY_UNREADABLE``."""

        history = self.history()
        if isinstance(history, Unreadable):
            return (HISTORY_UNREADABLE,)
        since = self._now() - timedelta(days=days)
        rows = [row for row in history.rows if row.at >= since][:REPORTED_CHANGES]
        return tuple(_reported(row) for row in rows)

    def _quantity_rules(self) -> QuantityRulesView:
        rules = self._observe(RULES)
        devices = self._observe(DEVICES)
        return QuantityRulesView(
            quantity_rules(_usable(rules, RULES), _usable(devices, DEVICES)), _problem(rules, RULES), _problem(devices, DEVICES)
        )

    def _checked(self, file: SettingsFile[T], parsed: T | FieldProblem) -> T | FieldProblem:
        """Wartość pliku z niezmiennikiem pary Reguł ilości i Listy Urządzeń; inne pliki mają tylko swój ``parse``."""

        together: Mapping[str, Callable[[Any], FieldProblem | None]] = {
            RULES.name: self._rules_problem,
            DEVICES.name: self._devices_problem,
        }
        check = together.get(file.name)
        problem = None if check is None or isinstance(parsed, FieldProblem) else check(parsed)
        return parsed if problem is None else problem

    def _rules_problem(self, rules: tuple[QuantityRule, ...]) -> FieldProblem | None:
        """Reguły z bieżącą Listą Urządzeń albo z ostatnią dobrą; listy nie porównuje z pamięcią, bo jej przyjęcie
        zależy od przyjęcia reguł."""

        data = self._places[DEVICES.name].read()
        return _rules_problem(rules, data, self._memory.read(DEVICES.name))

    def _devices_problem(self, devices: tuple[Component, ...]) -> FieldProblem | None:
        """Lista z regułami, którymi liczą procesy: reguły przyjmuje się pierwsze."""

        return devices_problem(devices, _usable(self._observe(RULES), RULES), _last_good_devices(self._memory.read(DEVICES.name)))

    def _undo(self, file: SettingsFile[T], changes: tuple[KeyChange, ...], row_id: str) -> Saved | Refused | NotSaved:
        return self._change(file, lambda current: file.restore(current, changes), undoes=row_id, source=ByDad(), undoable=True)

    def _change(
        self, file: SettingsFile[T], edit: Callable[[T], T], *, undoes: str | None, source: RowSource, undoable: bool
    ) -> Saved | Refused | NotSaved:
        place = self._places[file.name]
        unsupported = place.unsupported()
        if unsupported is not None:
            return Refused(unsupported)
        data = self._bytes_for_change(place)
        if isinstance(data, Unreadable) or isinstance(self._memory.read(file.name), Unreadable):
            self._log.settings_unreadable(cause="dostep")
            return NotSaved()
        observed = self._observed(file, data)
        if isinstance(observed, Bad) and file.secret and observed.usable is None:
            return Refused(observed.problem)
        current = _usable(observed, file)
        new = file.dump(edit(current)).encode("utf-8")
        edited = self._checked(file, file.parse(new))
        if isinstance(edited, FieldProblem):
            return Refused(edited)
        changes = file.diff(current, edited)
        if not changes and isinstance(observed, Good):
            return Saved(change=None)
        if isinstance(observed, Bad) and data is not None and not file.secret:
            self._memory.keep_rejected(file.name, data, self._now())
        row = self._row(file, changes, source, undoes=undoes, undoable=undoable) if changes else None
        try:
            place.write(new)
        except OSError:
            return NotSaved()
        if row is not None:
            try:
                self._history.append(row)
            except OSError:
                self._put_back(place, data)
                return NotSaved()
        self._remember(file, Remembered(seen=new, good=new))
        if row is None:
            return Saved(change=None)
        keys = tuple(dict.fromkeys(file.logged(change.key) for change in changes))
        self._log.settings_changed(file=file.name, keys=keys, source=source.kind)
        return Saved(change=row.id)

    def _put_back(self, place: _Place, data: bytes | None) -> None:
        """Poprzedni stan po zapisie, którego wiersza nie dało się dopisać; pamięć jeszcze go nie zmieniła. Stan,
        którego nie da się przywrócić, wyrówna następny odczyt jako zmianę spoza Centrum."""

        try:
            place.write(data)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="przywrócenie Ustawień po nieudanym wierszu Historii")

    def _remember(self, file: SettingsFile[T], remembered: Remembered) -> None:
        """Pamięć po wierszu Historii; nieudana daje przy następnym odczycie powtórzony wiersz, nie zmianę bez wiersza.
        Sekretu pamięć nie trzyma: tylko odcisk stanu (``_seen``), bez ostatniej dobrej treści."""

        if file.secret:
            remembered = Remembered(seen=_seen(file, remembered.seen), good=None)
        try:
            self._memory.write(file.name, remembered)
        except OSError as failure:
            self._log.unexpected_failure(failure, where="pamięć Ustawień")

    def _bytes_for_change(self, place: _Place) -> bytes | None | Unreadable:
        """Stan przed zmianą; stan, którego system nie daje czytać, czyta ponownie po kolejnych przerwach."""

        data = place.read()
        for seconds in RETRY_PAUSES_S:
            if not isinstance(data, OSError):
                break
            self._pause(seconds)
            data = place.read()
        return Unreadable() if isinstance(data, OSError) else data

    def _observe(self, file: SettingsFile[T]) -> Read[T] | Unreadable:
        data = self._places[file.name].read()
        if isinstance(data, OSError):
            return Unreadable()
        return self._observed(file, data)

    def _observed(self, file: SettingsFile[T], data: bytes | None) -> Read[T]:
        """Wartość pliku w stanie ``data`` (``None``: brak pliku) po porównaniu z pamięcią: stan wyjściowy bez wiersza,
        ten sam stan bez niczego albo zmiana spoza Centrum z jednym wierszem. Zła treść ma ostatnią dobrą treść z pamięci,
        a bez niej (także po przyjętym braku pliku) ``usable`` ``None``, więc proces bez Listy Wykonawców nie startuje.
        Brak pliku po odrzuconej albo czekającej migracji to złe ustawienie bez ostatniej dobrej wartości (``_absent``)."""

        compared = self._compared(file, data)
        absent = self._absent.get(file.name)
        if data is None and absent is not None:
            return Bad(FieldProblem(None, absent), None)
        return _with_secret_value(file, compared, data)

    def _compared(self, file: SettingsFile[T], data: bytes | None) -> Read[T]:

        parsed = self._checked(file, file.parse(data))
        remembered = self._memory.read(file.name)
        if isinstance(remembered, Unreadable):
            return _read(parsed, None)
        if remembered is None:
            if isinstance(parsed, FieldProblem):
                self._log.settings_bad(file=file.name, field=parsed.place or "plik")
            self._remember(file, Remembered(seen=data, good=None if isinstance(parsed, FieldProblem) else data))
            return _read(parsed, None)
        good = None if remembered.good is None else _good_value(remembered.good, file)
        before = file.default if good is None else good
        if _seen(file, data) == remembered.seen and (isinstance(parsed, FieldProblem) or file.secret or remembered.good == data):
            return _read(parsed, good)
        try:
            self._history.append(self._outside_row(file, data, parsed, before))
        except OSError:
            self._log.settings_external(file=file.name, result="bez-zapisu")
            return _read(parsed, good)
        self._remember(file, Remembered(seen=data, good=remembered.good if isinstance(parsed, FieldProblem) else data))
        if isinstance(parsed, FieldProblem):
            self._log.settings_bad(file=file.name, field=parsed.place or "plik")
            self._log.settings_external(file=file.name, result="odrzucono")
            return Bad(parsed, good)
        self._log.settings_external(file=file.name, result="zapisano")
        return Good(parsed)

    def _outside_row(self, file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem, before: T) -> HistoryRow:
        """Wiersz zmiany spoza Centrum: zła treść ``odrzucono`` z powodem, dobra treść albo brak pliku różnica kluczy od
        ostatniej dobrej wartości (bez różnicy bez „Cofnij”)."""

        if isinstance(parsed, FieldProblem):
            return self._row(file, (), Outside(), undoes=None, undoable=False).model_copy(
                update={"result": "odrzucono", "reason": parsed.sentence, "removed": data is None}
            )
        changes = file.diff(before, parsed)
        return self._row(file, changes, Outside(), undoes=None, undoable=bool(changes)).model_copy(
            update={"removed": data is None}
        )

    def _row(
        self, file: SettingsFile[T], changes: tuple[KeyChange, ...], source: RowSource, *, undoes: str | None, undoable: bool
    ) -> HistoryRow:
        sections = {_SECTION.split(change.key, maxsplit=1)[0] for change in changes}
        return HistoryRow(
            id=uuid.uuid4().hex,
            at=self._now(),
            source=source,
            undoes=undoes,
            file=file.name,
            section=next(iter(sections)) if len(sections) == 1 else None,
            changes=tuple(RowChange(key=change.key, before=None, after=None) if file.secret else RowChange.of(change) for change in changes),
            secret=file.secret,
            undoable=undoable and not file.secret,
            result="zapisano",
            reason=None,
        )


# Każdy plik ma własny typ wartości, a właściciel oddaje wartość tylko temu plikowi, z którego ją wziął.
_UNDOABLE: Final[Mapping[str, SettingsFile[Any]]] = {
    FOLDERS.name: FOLDERS,
    FOLDERS.name: FOLDERS,
    WORKERS.name: WORKERS,
    REMINDERS.name: REMINDERS,
    AUTOSTART.name: AUTOSTART,
    DEVICES.name: DEVICES,
    RULES.name: RULES,
}
"""Pliki, których wiersze Historii da się cofnąć: każdy plik bez sekretu."""
_FILES: Final[Mapping[str, SettingsFile[Any]]] = {**_UNDOABLE, INBOX.name: INBOX}
"""Każdy plik właściciela; ``history`` porównuje z pamięcią każdy z nich."""
_SECTION: Final = re.compile(r"[.\[]")
"""Sekcja klucza Historii to jego początek do kropki (``foldery.rejestr_zlecen``) albo nawiasu (``wykonawcy[login]``)."""


def read_snapshot(config: Path) -> SettingsSnapshot:
    """Migawka bez zapisu dla narzędzi i Skryptu dla maszyn: plik, przy złej treści ostatnia dobra z pamięci właściciela;
    nie dopisuje Historii ani pamięci."""

    remembered_devices = Memory(config, lambda _: None).read(DEVICES.name)
    devices_data = settings_bytes(config / DEVICES.name)
    rules = _read_only(config, RULES, lambda value: _rules_problem(value, devices_data, remembered_devices))
    devices = _read_only(config, DEVICES, lambda value: devices_problem(value, rules, _last_good_devices(remembered_devices)))
    return SettingsSnapshot(
        folders=_read_only(config, FOLDERS),
        workers=_read_only_view(config, WORKERS),
        inbox=inbox.state(_read_only_view(config, INBOX)),
        reminders=_read_only(config, REMINDERS),
        quantity_rules=quantity_rules(rules, devices),
    )


def _read_only(config: Path, file: SettingsFile[T], together: Callable[[T], FieldProblem | None] | None = None) -> T:
    return _usable(_read_only_view(config, file, together), file)


def _read_only_view(
    config: Path, file: SettingsFile[T], together: Callable[[T], FieldProblem | None] | None = None
) -> Read[T] | Unreadable:
    """Wartość pliku bez porównania z pamięcią: zła treść z ostatnią dobrą z pamięci właściciela, gdy ją ma;
    ``together``: problem pliku razem z drugim plikiem pary, jak ``CentrumSettings._checked``."""

    data = settings_bytes(config / file.name)
    if isinstance(data, OSError):
        return Unreadable()
    parsed = file.parse(data)
    if not isinstance(parsed, FieldProblem) and together is not None:
        parsed = together(parsed) or parsed
    if not isinstance(parsed, FieldProblem):
        return Good(parsed)
    remembered = Memory(config, lambda _: None).read(file.name)
    good = remembered.good if isinstance(remembered, Remembered) else None
    return _with_secret_value(file, Bad(parsed, None if good is None else _good_value(good, file)), data)


def _with_secret_value(file: SettingsFile[T], read: Read[T], data: bytes | None) -> Read[T]:
    """Złe ustawienie sekretu z wartością samej złej treści zamiast ostatniej dobrej, której pamięć sekretu nie trzyma:
    od niej zaczyna zapis taty, który naprawia tylko to, co zmienia."""

    if not (file.secret and isinstance(read, Bad)):
        return read
    return Bad(read.problem, None if file.unchecked is None else file.unchecked(data))


def _seen(file: SettingsFile[T], data: bytes | None) -> bytes | None:
    """Stan pliku w pamięci: bajty, a sekretu tylko ich odcisk SHA-256, więc hasła nie ma w ``ustawienia-pamiec``."""

    if data is None or not file.secret:
        return data
    return hashlib.sha256(data).digest()


def _rules_problem(
    rules: tuple[QuantityRule, ...], devices: bytes | None | OSError, remembered: Remembered | None | Unreadable
) -> FieldProblem | None:
    """Reguły z bieżącą Listą Urządzeń (stan ``devices``) albo z jej ostatnią dobrą wartością z pamięci; listę, której
    system nie daje czytać, procesy biorą z Wydania, więc reguły muszą pasować do niej."""

    if isinstance(devices, OSError):
        return rules_problem(rules, None, DEVICES.default)
    now = DEVICES.parse(devices)
    return rules_problem(rules, None if isinstance(now, FieldProblem) else now, _last_good_devices(remembered))


def _last_good_devices(remembered: Remembered | None | Unreadable) -> tuple[Component, ...]:
    """Ostatnia dobra Lista Urządzeń z pamięci właściciela, którą procesy liczą przy złej liście; bez niej lista z Wydania."""

    return _good_value(remembered.good if isinstance(remembered, Remembered) else None, DEVICES)


def _good_value(good: bytes | None, file: SettingsFile[T]) -> T:
    """Wartość ostatniej dobrej treści z pamięci; brak pliku albo treść, której ``parse`` dziś nie przyjmuje, to wartości
    domyślne pliku."""

    parsed = file.parse(good)
    return file.default if isinstance(parsed, FieldProblem) else parsed


def _problem(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> FieldProblem | None:
    match observed:
        case Good():
            return None
        case Bad(problem=problem):
            return problem
        case Unreadable():
            return FieldProblem(None, messages.unavailable(file.name))


def _absent_sentence(change: ReleaseChange[Any], applied: Mapping[str, Applied], waiting: frozenset[str]) -> str | None:
    """Zdanie złego ustawienia pliku zmiany ``change``, którego nie ma: zmiana czeka (``Later``) albo została odrzucona;
    ``None``: brak pliku to wartości domyślne."""

    if change.id in waiting:
        return change.waiting_absent
    if change.id in applied and applied[change.id].result == "odrzucono":
        return change.refused_absent
    return None


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
    head = f"- {row.at:%Y-%m-%d %H:%M} · {_reported_source(row.source)} · {row.file}"
    if row.result == "odrzucono":
        return f"{head} · odrzucono: {row.reason}"
    file = _FILES.get(row.file)
    if row.secret or file is None:
        return f"{head} · zmieniono: " + ", ".join(change.key for change in row.changes)
    undo = " · cofnięcie" if row.undoes is not None else ""
    removed = " · usunięto plik" if row.removed else ""
    return f"{head}{undo}{removed} · " + "; ".join(file.reported(change.change()) for change in row.changes)


def _reported_source(source: RowSource) -> str:
    match source:
        case ByDad():
            return "tata"
        case Outside():
            return "spoza Centrum"
        case FromRelease(release=release, commit=commit, change=change):
            if release is not None:
                return f"Wydanie {release} ({change})"
            return f"{'wersja nieznana' if commit is None else f'commit {commit}'} ({change})"
