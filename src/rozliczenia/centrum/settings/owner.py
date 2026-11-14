"""Ustawienia Centrum: jedyny czytelnik i pisarz plików Ustawień w ``config``, ich Historii i pamięci (ADR 0032).

Obejmuje plik Folderów i motywu (``folders``), Listę Wykonawców (``workers``), Przypomnienia o raporcie
(``reminders``), plik dostępu do skrzynki raportów
(``inbox``), który jest sekretem: jego wiersz Historii ma same klucze bez wartości i nie ma „Cofnij”, a pamięć trzyma
tylko odcisk jego treści, bez ostatniej dobrej treści i bez kopii złej treści w ``odrzucone``, przełącznik startu
razem z Windows (``autostart``), którego stan to skrót w folderze Autostart, a nie plik w ``config``, pliki Reguł
ilości i Listy Urządzeń (``quantity_rules``) oraz wyjątki Kontroli ilości (``quantity_exceptions``). Każde ustawienie ma swoje miejsce (``_Place``), z którego właściciel
czyta stan i do którego go zapisuje, a reszta drogi jest wspólna. ``CentrumSettings`` czyta je przy każdym odczycie od
nowa, więc zmiana działa od razu, a proces dostaje jedną migawkę (``snapshot``) na start Uruchomienia i kończy na jej
wartościach.
Zła treść pliku to złe ustawienie (``Bad``) z ostatnią dobrą wartością z pamięci, nigdy wyjątek ani błąd startu.
Reguły ilości i Lista Urządzeń mają do tego jeden wspólny niezmiennik: każde przyjęcie jednego z nich (``_paired``:
odczyt, także bez zapisu w ``read_snapshot``, zapis, cofnięcie) sprawdza go razem z drugim, więc plik, który do drugiego
nie pasuje, jest zły tak samo jak plik z uszkodzoną treścią, a procesy liczą ostatnią dobrą parą. Reguły ilości z
Wydania (tata nie ma pliku reguł) są zawsze dobre, a lista, której brakuje ich składnika, jest zła i procesy biorą ten
składnik z Listy Urządzeń z Wydania; składnik, którego każdy zapis ma lista taty, nie dochodzi, a lista bez niego jest
dobra (``quantity_rules``). Plik, który zaczyna pasować dopiero po zmianie drugiego, ma wtedy wiersz ``spoza`` jak
zmiana jego treści.
Każdy zapis taty pary (formularz sekcji, „Dodaj” z podpowiedzi, „Popraw regułę”, „Cofnij”) idzie przez ``_dad_change``,
które sprawdza go jako zmianę, zanim ``_checked`` zobaczy plik: odmowa mówi, co zmiana psuje (zapis u dwóch składników,
składnik potrzebny regule, reguła bez składnika, zapis, który tata musi zwolnić dla składnika z Wydania), tym samym
zdaniem dla formularza i „Cofnij”, a zdanie reguły ma kolumny z cennika (``column_names``). Przy Regułach ilości z
Wydania zmiana listy dostaje listę uzupełnioną i zapisuje ją uzupełnioną, a pierwszy plik reguł taty zapisuje najpierw
listę, do której pasuje (``quantity_rules.dad_devices_edit``, ``devices_for_dad_rules``, ``dad_rules_problem``).

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

Zmiana taty (zapis albo „Cofnij”), która usuwa loginy z Listy Wykonawców (``SettingsFile.removed_logins``), zapisuje się
dopiero, gdy żaden z nich nie występuje w okresie (``WorkerPeriods``, ADR 0032); inaczej to ``KeptInPeriods`` bez zapisu,
wiersza i pamięci. Okresy sprawdza się poza blokadą, bo pierwsze sprawdzenie czyta Plik zbiorczy każdego okresu, a zapis
po nim odmawia, gdy zmiana usuwa wtedy login, którego nie sprawdzono (lista zmieniła się w tym czasie). Zmiany z Wydania
i zmiany spoza Centrum to zmiany Maksa: okresów nie sprawdzają.

Zmiany z Wydania (``release_changes``) właściciel stosuje przy starcie Centrum, przed pierwszym zapytaniem, tym samym
zapisem co zmianę taty, tylko ze źródłem ``wydanie``. Co już weszło, mówią dwa źródła: pamięć zmian z Wydań i wiersze
Historii z id zmiany. Zmiany stosują się tylko wtedy, gdy oba dają się przeczytać: pamięć, której nie da się przeczytać
(``AppliedUnknown``), albo Historia, której system nie daje teraz czytać (``Unreadable``), wstrzymuje przy tym starcie
każdą zmianę z linią w dzienniku Centrum, a następny start próbuje znowu, bo bez nich zmiana cofnięta przez tatę weszłaby
jeszcze raz. Historię start czyta tylko wtedy, gdy pamięć nie ma którejś zmiany.
Odrzucona migracja, której pliku dalej nie ma (``ReleaseChange.refused_absent``), i migracja, która przy tym starcie
nie doszła do skutku, a jej stare pliki są w ``config`` (``ReleaseChange.waiting``: ``Later``, pamięć albo Historia
nieczytelna, wyjątek, nieudany zapis), dają złe ustawienie bez ostatniej dobrej wartości zamiast wartości domyślnych,
więc tata nie widzi pustej dobrej Listy Wykonawców, a proces bez niej nie startuje; wie o tym tylko praca Centrum po
starcie, który stosował zmiany z Wydania (nie ``read_snapshot``).
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
``settings_router``. Próby skrzynki i Przypomnień (``tools/proba_*``) czytają przez ``read_snapshot``, które niczego
nie pisze; Skrypt dla maszyn czyta Listę Wykonawców regułą ``WORKERS.parse`` bez Historii i pamięci, a Reguły ilości
bierze z Wydania.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re
import threading
from typing import Any, Final, Protocol, TypeVar
import uuid

from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S, replace_atomically
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import Autostart
from rozliczenia.centrum.settings.autostart import AUTOSTART, AutostartPlace, Unsupported
from rozliczenia.centrum.settings.files import (
    Bad,
    FieldProblem,
    Good,
    KeyChange,
    Read,
    RemovedLogins,
    RemovedWhat,
    SettingsFile,
    Unreadable,
)
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
from rozliczenia.centrum.settings.quantity_exceptions import EXCEPTIONS, QuantityException
from rozliczenia.centrum.settings.quantity_rules import (
    DEVICES,
    RULES,
    ColumnNames,
    DevicesEdit,
    dad_devices_edit,
    dad_rules_problem,
    devices_for_dad_rules,
    devices_problem,
    listed_name,
    quantity_rules,
    rules_problem,
    taken_problem,
)
from rozliczenia.centrum.settings.reminders import REMINDERS
from rozliczenia.centrum.settings.workers import WORKERS
from rozliczenia.quantity_engine import Component, DeviceList, QuantityRule, QuantityRules
from rozliczenia.worker_list import WorkerList
from rozliczenia.worker_periods import InPeriod, InRegister, NotInPeriods, Unchecked, WorkerPeriods
from rozliczenia.worker_report_inbox import InboxState
from rozliczenia.worker_reports import ReminderSettings

T = TypeVar("T")

REPORTED_CHANGES: Final = 20
"""Najwyżej tyle najnowszych wierszy Historii podaje Zgłoszenie."""
HISTORY_UNREADABLE: Final = "- Historii Ustawień nie dało się przeczytać"
"""Linia Zgłoszenia zamiast zmian, gdy system nie daje czytać pliku Historii."""
_PairCheck = Callable[[Any], FieldProblem | None]
"""Problem dobrej wartości pliku pary Reguł ilości i Listy Urządzeń razem z drugim plikiem; ``None``: para pasuje."""
_RulesEdit = Callable[[tuple[QuantityRule, ...]], tuple[QuantityRule, ...] | FieldProblem]
"""Zmiana taty Reguł ilości: bieżące reguły → reguły po zmianie albo problem, który jest odmową bez zapisu."""


@dataclass(frozen=True)
class SettingsSnapshot:
    """Wartości Ustawień Centrum z jednej chwili. Foldery i Przypomnienia o raporcie: dobre, a przy złym pliku ostatnie
    dobre albo domyślne. Lista Wykonawców ze złym ustawieniem, bo proces bez ostatniej dobrej listy nie startuje
    (odmowa ``refusal.workers_unusable``)."""

    folders: FolderSettings
    workers: Read[WorkerList] | Unreadable
    inbox: InboxState
    reminders: ReminderSettings
    quantity_rules: QuantityRules
    """Reguły ilości z Listą Urządzeń, którymi liczy Uruchomienie: przy złym pliku albo pliku, który nie pasuje do
    drugiego, ostatnia dobra para."""


@dataclass(frozen=True)
class QuantityRulesView:
    """Reguły ilości dla okna Ustawień: te, którymi liczy następne Uruchomienie, wyjątki Kontroli ilości (przy złym
    pliku ostatnie dobre) i problem każdego pliku (``None``: plik dobry). Plik reguł albo listy, który nie pasuje do
    drugiego, ma problem jak zły plik. Lista Urządzeń, której zapisy ma składnik z Listy Urządzeń z Wydania, a Reguły
    ilości z Wydania liczą bez niego, ma zamiast problemu zdanie o nim (``taken_problem``), a Reguły ilości zdanie, że
    ich zmiana zapisze się dopiero ze zwolnionym zapisem (``devices_for_dad_rules``). ``source_rules``: reguły z pliku
    albo z Wydania, z których powstały te liczone; zmienia je zapis reguł taty."""

    rules: QuantityRules
    rules_problem: FieldProblem | None
    devices_problem: FieldProblem | None
    source_rules: tuple[QuantityRule, ...]
    exceptions: tuple[QuantityException, ...]
    exceptions_problem: FieldProblem | None


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
class KeptInPeriods:
    """Zmiana usunęłaby z Listy Wykonawców login, który występuje w okresie albo którego nie da się teraz sprawdzić
    (``presence``), więc nic się nie zapisało; ``what``: cały Wykonawca albo jego login."""

    presence: InRegister | InPeriod | Unchecked
    what: RemovedWhat


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
        periods: WorkerPeriods,
        column_names: ColumnNames,
    ) -> None:
        """Ustawienia w folderze ``config`` i skrót Centrum w folderze Autostart (``autostart``); ``now`` daje chwilę
        wiersza Historii, a ``pause`` czeka przed kolejną próbą odczytu albo zapisu pliku, który system na chwilę
        trzyma. ``periods`` szuka w okresach loginów, które zmiana taty usuwa z Listy Wykonawców, a ``column_names``
        daje nazwy kolumn z cennika do zdania reguły w odmowie zmiany pary."""

        self._config = config
        self._log = log
        self._now = now
        self._pause = pause
        self._periods = periods
        self._column_names = column_names
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
            EXCEPTIONS.name: _ConfigFile(config / EXCEPTIONS.name, pause),
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
        """Reguły ilości, Lista Urządzeń i wyjątki Kontroli ilości dla okna Ustawień, każdy plik porównany z pamięcią jak
        przy każdym odczycie."""

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

    def change(
        self, file: SettingsFile[T], edit: Callable[[T], T | FieldProblem]
    ) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty: ``edit`` dostaje bieżącą wartość pliku (przy złym pliku ostatnią dobrą) i daje nową albo problem
        zmiany (np. pole formularza sekcji Wykonawcy), który jest odmową bez zapisu."""

        return self._by_dad(file, edit, undoes=None)

    def change_with_used_keys(
        self, file: SettingsFile[T], edit: Callable[[T, frozenset[str]], T | FieldProblem]
    ) -> Saved | Refused | NotSaved:
        """Zapis taty jak ``change``, w którym ``edit`` dostaje też klucze pliku z wierszy Historii (``used_keys``),
        przeczytane pod tą samą blokadą co zapis: nowy wpis dostaje wtedy klucz, którego nie zna żaden wiersz, więc
        „Cofnij” starszego wiersza go nie rusza. Historia, której nie da się przeczytać, to ``NotSaved``."""

        with self._lock:
            keys = self._used_keys(file)
            if isinstance(keys, Unreadable):
                self._log.settings_unreadable(cause="historia")
                return NotSaved()
            return self._dad_change(file, lambda current: edit(current, keys), undoes=None, checked=frozenset())

    def rules_after(self, edit: _RulesEdit) -> QuantityRules | FieldProblem:
        """Reguły ilości z Listą Urządzeń, które da zapis taty zmiany ``edit`` pliku reguł, albo jego odmowa, bez zapisu:
        podgląd zmiany reguły sprawdza tym to samo, co sprawdzi zapis (``_dad_rules``)."""

        with self._lock:
            paired = self._rules_after(edit)
            return paired if isinstance(paired, FieldProblem) else QuantityRules(paired[0], DeviceList(paired[1]))

    def _release(self) -> bool:
        """Procesy liczą Regułami ilości z Wydania: tata nie ma pliku reguł."""

        return self._places[RULES.name].read() is None

    def used_keys(self, file: SettingsFile[Any]) -> frozenset[str] | Unreadable:
        """Klucze, które plik ``file`` ma w wierszach Historii Ustawień, z każdego źródła i wyniku. Linia Historii, której
        nie da się przeczytać, nie daje klucza, ale też nie da się jej cofnąć."""

        with self._lock:
            return self._used_keys(file)

    def _used_keys(self, file: SettingsFile[Any]) -> frozenset[str] | Unreadable:
        history = self._history.read()
        if isinstance(history, Unreadable):
            return history
        return frozenset(change.key for row in history.rows if row.file == file.name for change in row.changes)

    def undo(self, row_id: str) -> Saved | Refused | NotSaved | NotUndoable | KeptInPeriods:
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
        return self._by_dad(file, lambda current: file.restore(current, changes), undoes=row.id)

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
            remembered = self._memory.applied()
            if isinstance(remembered, AppliedUnknown):
                for change in changes:
                    self._log.settings_release(change=change.id, result="bez-pamieci")
                applied: dict[str, Applied] = {}
            else:
                applied = remembered
                self._apply_pending(changes, applied, origin)
            self._absent = {
                change.file.name: sentence
                for change in changes
                if (sentence := _absent_sentence(change, applied, self._config)) is not None
            }

    def _apply_pending(
        self, changes: tuple[ReleaseChange[Any], ...], applied: dict[str, Applied], origin: Callable[[], ReleaseOrigin]
    ) -> None:
        """Zmiany, których pamięć ``applied`` jeszcze nie ma; każda z wynikiem trafia do ``applied`` i do pamięci."""

        pending = [change for change in changes if change.id not in applied]
        if not pending:
            return
        in_history = self._release_rows()
        if isinstance(in_history, Unreadable):
            for change in pending:
                self._log.settings_release(change=change.id, result="bez-historii")
            return
        version: ReleaseOrigin | None = None
        for change in pending:
            done = in_history.get(change.id)
            if done is None:
                version = version or origin()
                try:
                    result = self._apply(change, version)
                except Exception as failure:
                    self._log.unexpected_failure(failure, where=f"zmiana Ustawień z Wydania {change.id}")
                    continue
                if result is None:
                    continue
                done = Applied(at=self._now(), release=version.release, commit=version.commit, result=result)
            applied[change.id] = done
            try:
                self._memory.remember_applied(applied)
            except OSError:
                self._log.settings_release(change=change.id, result="bez-pamieci")

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

    def _apply(self, change: ReleaseChange[T], version: ReleaseOrigin) -> AppliedResult | None:
        """Jedna zmiana z Wydania; ``None`` (zmiana dała ``Later`` albo zapis się nie udał) wraca przy następnym starcie.

        Zmiana Maksa z Wydania nie sprawdza okresów, jak ręczna zmiana w ``config`` (ADR 0032).
        """

        source = FromRelease(release=version.release, commit=version.commit, change=change.id)
        match change.propose(ReleaseInputs(self._observe(change.file), self._config)):
            case Nothing():
                result: AppliedResult | None = "bez-zmian"
            case Later():
                self._log.settings_release(change=change.id, result="pozniej")
                return None
            case Refuse(sentence=sentence):
                result = self._refuse(change.file, source, sentence)
            case Edit(edit=edit, undoable=undoable):
                match self._change(change.file, edit, undoes=None, source=source, undoable=undoable, checked=None):
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
        exceptions = self._observe(EXCEPTIONS)
        usable_rules, usable_devices = _usable(rules, RULES), _usable(devices, DEVICES)
        waiting = devices_for_dad_rules(usable_devices, usable_rules, usable_rules) if self._release() else None
        return QuantityRulesView(
            quantity_rules(usable_rules, usable_devices),
            _problem(rules, RULES) or (waiting if isinstance(waiting, FieldProblem) else None),
            _problem(devices, DEVICES) or taken_problem(usable_rules, usable_devices),
            usable_rules,
            _usable(exceptions, EXCEPTIONS),
            _problem(exceptions, EXCEPTIONS),
        )

    def _checked(self, file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem) -> T | FieldProblem:
        """Wartość pliku w stanie ``data`` z niezmiennikiem pary Reguł ilości i Listy Urządzeń (``_paired``) z bieżącymi
        plikami i pamięcią właściciela."""

        together: Mapping[str, _PairCheck] = {
            RULES.name: self._rules_problem,
            DEVICES.name: self._devices_problem,
        }
        return _paired(file, data, parsed, together)

    def _rules_problem(self, rules: tuple[QuantityRule, ...]) -> FieldProblem | None:
        """Reguły z bieżącą Listą Urządzeń albo z ostatnią dobrą; listy nie porównuje z pamięcią, bo jej przyjęcie
        zależy od przyjęcia reguł."""

        data = self._places[DEVICES.name].read()
        return _rules_problem(rules, data, self._memory.read(DEVICES.name))

    def _devices_problem(self, devices: tuple[Component, ...]) -> FieldProblem | None:
        """Lista z regułami, którymi liczą procesy: reguły przyjmuje się pierwsze."""

        return devices_problem(
            devices,
            _usable(self._observe(RULES), RULES),
            _last_good_devices(self._memory.read(DEVICES.name)),
            release=self._release(),
        )

    def _by_dad(
        self, file: SettingsFile[T], edit: Callable[[T], T | FieldProblem], *, undoes: str | None
    ) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zmiana taty: loginy, które usuwa z Listy Wykonawców, najpierw poza blokadą sprawdza w okresach, potem zapisuje
        z nimi jako sprawdzonymi."""

        with self._lock:
            removed = self._removed_logins(file, edit)
            if removed is None:
                return self._dad_change(file, edit, undoes=undoes, checked=frozenset())
            folders = _usable(self._observe(FOLDERS), FOLDERS)
        presence = self._periods.find(removed.logins, folders.register, folders.periods_directory)
        if not isinstance(presence, NotInPeriods):
            return KeptInPeriods(presence, removed.what)
        with self._lock:
            return self._dad_change(file, edit, undoes=undoes, checked=removed.logins)

    def _dad_change(
        self, file: SettingsFile[T], edit: Callable[[T], T | FieldProblem], *, undoes: str | None, checked: frozenset[str]
    ) -> Saved | Refused | NotSaved:
        """Zapis taty pod blokadą; jedyna droga zapisu taty Listy Urządzeń i Reguł ilości, więc jedyne miejsce, które
        sprawdza go jako zmianę pary i daje odmowę zdaniem o tej zmianie (``_dad_devices``, ``_dad_rules``)."""

        paired: Mapping[str, Callable[..., Saved | Refused | NotSaved]] = {
            DEVICES.name: self._dad_devices,
            RULES.name: self._dad_rules,
        }
        write = paired.get(file.name)
        if write is None:
            return self._change(file, edit, undoes=undoes, source=ByDad(), undoable=True, checked=checked)
        return write(edit, undoes=undoes, checked=checked)

    def _dad_devices(self, edit: DevicesEdit, *, undoes: str | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        """Zmiana taty Listy Urządzeń sprawdzona jako zmiana z regułami, którymi liczy Centrum; przy Regułach ilości z
        Wydania na liście uzupełnionej i zapisana uzupełniona (``dad_devices_edit``)."""

        rules = _usable(self._observe(RULES), RULES)
        changed = dad_devices_edit(edit, rules, self._column_names, release=self._release())
        return self._change(DEVICES, changed, undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _dad_rules(self, edit: _RulesEdit, *, undoes: str | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        """Zmiana taty Reguł ilości sprawdzona jako zmiana z Listą Urządzeń (``_rules_after``). Pierwszy plik reguł taty w
        miejsce Reguł ilości z Wydania zapisuje najpierw listę, do której pasuje (osobny wiersz Historii, jak „ołówek,
        Zapisz” przy składniku z Wydania)."""

        paired = self._rules_after(edit)
        if isinstance(paired, FieldProblem):
            return Refused(paired)
        _, devices = paired
        if devices != _usable(self._observe(DEVICES), DEVICES):
            listed = self._change(DEVICES, lambda _: devices, undoes=None, source=ByDad(), undoable=True, checked=checked)
            if not isinstance(listed, Saved):
                return listed
        return self._change(RULES, edit, undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _rules_after(self, edit: _RulesEdit) -> tuple[tuple[QuantityRule, ...], tuple[Component, ...]] | FieldProblem:
        """Reguły po zmianie taty ``edit`` z Listą Urządzeń, z którą się zapiszą, albo odmowa zdaniem o tej zmianie: przy
        Regułach ilości z Wydania lista dostaje składniki z Wydania, których reguły potrzebują, albo zmiana czeka na
        zapis, który tata musi zwolnić (``devices_for_dad_rules``); reguła bez składnika na liście to jej zdanie ze
        składnikiem nazwanym jak ostatnio na liście (``dad_rules_problem``)."""

        current = _usable(self._observe(RULES), RULES)
        rules = edit(current)
        if isinstance(rules, FieldProblem):
            return rules
        devices = _usable(self._observe(DEVICES), DEVICES)
        if self._release():
            needed = devices_for_dad_rules(devices, rules, current)
            if isinstance(needed, FieldProblem):
                return needed
            devices = needed
        problem = dad_rules_problem(rules, devices, self._column_names, self._listed_name)
        return (rules, devices) if problem is None else problem

    def _listed_name(self, component: str) -> str:
        """Nazwa składnika spoza Listy Urządzeń z wierszy Historii Ustawień listy (``listed_name``)."""

        history = self._history.read()
        rows = () if isinstance(history, Unreadable) else history.rows
        return listed_name(component, (change.change() for row in rows if row.file == DEVICES.name for change in row.changes))

    def _removed_logins(self, file: SettingsFile[T], edit: Callable[[T], T | FieldProblem]) -> RemovedLogins | None:
        """Loginy, które ``edit`` usunąłby teraz z Listy Wykonawców; ``None`` też przy odmowie, którą da ``_change``."""

        if file.removed_logins is None:
            return None
        current = _usable(self._observe(file), file)
        value = edit(current)
        return None if isinstance(value, FieldProblem) else file.removed_logins(current, value)

    def _change(
        self,
        file: SettingsFile[T],
        edit: Callable[[T], T | FieldProblem],
        *,
        undoes: str | None,
        source: RowSource,
        undoable: bool,
        checked: frozenset[str] | None,
    ) -> Saved | Refused | NotSaved:
        """Zapis wartości od ``edit``. ``checked``: loginy, które zmiana może usunąć z Listy Wykonawców, bo sprawdzono je
        w okresach; usunięcie innego to odmowa. ``None``: zmiana Maksa z Wydania, bez sprawdzenia."""

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
        value = edit(current)
        if isinstance(value, FieldProblem):
            return Refused(value)
        new = file.dump(value).encode("utf-8")
        edited = self._checked(file, new, file.parse(new))
        if isinstance(edited, FieldProblem):
            return Refused(edited)
        if checked is not None and file.removed_logins is not None:
            removed = file.removed_logins(current, edited)
            if removed is not None and not removed.logins <= checked:
                return Refused(FieldProblem(None, messages.worker_list_changed()))
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

        parsed = self._checked(file, data, file.parse(data))
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


_UNDOABLE: Final[Mapping[str, SettingsFile[Any]]] = {
    FOLDERS.name: FOLDERS,
    WORKERS.name: WORKERS,
    REMINDERS.name: REMINDERS,
    AUTOSTART.name: AUTOSTART,
    DEVICES.name: DEVICES,
    RULES.name: RULES,
    EXCEPTIONS.name: EXCEPTIONS,
}
"""Pliki, których wiersze Historii da się cofnąć: każdy plik bez sekretu. Każdy plik ma własny typ wartości (stąd
``Any``), a właściciel oddaje wartość tylko temu plikowi, z którego ją wziął."""
_FILES: Final[Mapping[str, SettingsFile[Any]]] = {**_UNDOABLE, INBOX.name: INBOX}
"""Każdy plik właściciela; ``history`` porównuje z pamięcią każdy z nich."""
_SECTION: Final = re.compile(r"[.\[]")
"""Sekcja klucza Historii to jego początek do kropki (``foldery.rejestr_zlecen``) albo nawiasu (``wykonawcy[login]``)."""


def read_snapshot(config: Path) -> SettingsSnapshot:
    """Migawka bez zapisu dla prób skrzynki i Przypomnień (``tools/proba_*``): plik, przy złej treści ostatnia dobra z
    pamięci właściciela; nie dopisuje Historii ani pamięci."""

    remembered_devices = Memory(config, lambda _: None).read(DEVICES.name)
    devices_data = settings_bytes(config / DEVICES.name)
    rules = _read_only(config, RULES, {RULES.name: lambda value: _rules_problem(value, devices_data, remembered_devices)})
    release = settings_bytes(config / RULES.name) is None
    devices = _read_only(
        config,
        DEVICES,
        {DEVICES.name: lambda value: devices_problem(value, rules, _last_good_devices(remembered_devices), release=release)},
    )
    return SettingsSnapshot(
        folders=_read_only(config, FOLDERS),
        workers=_read_only_view(config, WORKERS),
        inbox=inbox.state(_read_only_view(config, INBOX)),
        reminders=_read_only(config, REMINDERS),
        quantity_rules=quantity_rules(rules, devices),
    )


def _read_only(config: Path, file: SettingsFile[T], together: Mapping[str, _PairCheck] | None = None) -> T:
    return _usable(_read_only_view(config, file, together), file)


def _read_only_view(
    config: Path, file: SettingsFile[T], together: Mapping[str, _PairCheck] | None = None
) -> Read[T] | Unreadable:
    """Wartość pliku bez porównania z pamięcią: zła treść z ostatnią dobrą z pamięci właściciela, gdy ją ma;
    ``together``: sprawdzenia pary z plików w ``config`` i pamięci (``_paired``)."""

    data = settings_bytes(config / file.name)
    if isinstance(data, OSError):
        return Unreadable()
    parsed = _paired(file, data, file.parse(data), together or {})
    if not isinstance(parsed, FieldProblem):
        return Good(parsed)
    remembered = Memory(config, lambda _: None).read(file.name)
    good = remembered.good if isinstance(remembered, Remembered) else None
    return _with_secret_value(file, Bad(parsed, None if good is None else _good_value(good, file)), data)


def _paired(
    file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem, together: Mapping[str, _PairCheck]
) -> T | FieldProblem:
    """Wartość pliku w stanie ``data`` z niezmiennikiem pary Reguł ilości i Listy Urządzeń (``together``) dla
    właściciela i ``read_snapshot``; inne pliki mają tylko swój ``parse``. Reguły ilości z Wydania (brak pliku reguł)
    pasować nie muszą: pasować musi do nich lista taty."""

    if data is None and file.name == RULES.name:
        return parsed
    check = together.get(file.name)
    problem = None if check is None or isinstance(parsed, FieldProblem) else check(parsed)
    return parsed if problem is None else problem


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


def _absent_sentence(change: ReleaseChange[Any], applied: Mapping[str, Applied], config: Path) -> str | None:
    """Zdanie złego ustawienia pliku zmiany ``change``, którego nie ma: zmiana została odrzucona albo przy tym starcie nie
    doszła do skutku (nie ma jej w ``applied``), a jej stare pliki są w ``config``; ``None``: brak pliku to wartości
    domyślne."""

    done = applied.get(change.id)
    if done is not None:
        return change.refused_absent if done.result == "odrzucono" else None
    if change.waiting is not None and change.waiting.old_files(config):
        return change.waiting.sentence
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
