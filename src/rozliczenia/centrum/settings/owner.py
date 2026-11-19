"""Ustawienia Centrum: jedyny czytelnik i pisarz plików Ustawień w ``config``, ich Historii i pamięci (ADR 0032).

Obejmuje plik Folderów i motywu (``folders``), Listę Wykonawców (``workers``), Przypomnienia o raporcie
(``reminders``), temat i treść Maila z rozliczeniem (``settlement_mail``), plik dostępu do skrzynki raportów
(``inbox``), który jest sekretem: jego wiersz Historii ma same klucze bez wartości i nie ma „Cofnij”, a pamięć trzyma
tylko odcisk jego treści, bez ostatniej dobrej treści i bez kopii złej treści w ``odrzucone``, przełącznik startu
razem z Windows (``autostart``), którego stan to skrót w folderze Autostart, a nie plik w ``config``, pliki Reguł
ilości i Listy Urządzeń (``quantity_rules``), wyjątki Kontroli ilości (``quantity_exceptions``) i Legendę czynności
(``activity_legend``). Każde ustawienie ma swoje miejsce (``_Place``), z którego właściciel
czyta stan i do którego go zapisuje, a reszta drogi jest wspólna. ``CentrumSettings`` czyta je przy każdym odczycie od
nowa, więc zmiana działa od razu, a proces dostaje jedną migawkę (``snapshot``) na start Uruchomienia i kończy na jej
wartościach.
Zła treść pliku to złe ustawienie (``Bad``) z ostatnią dobrą wartością z pamięci, nigdy wyjątek ani błąd startu.
Plik, którego system nie daje teraz czytać, to ``Unreadable``, a nie wartości domyślne (``_usable``): trasa okna
Ustawień, która odpowiada z jego wartości (``folders``, ``QuantityRulesView.source_rules``, ``rules_after``), i zapis taty,
który sprawdza nim zmianę (``NotSaved.unreadable``), odmawiają wtedy zdaniem o tym pliku. Migawka dla procesu ma w miejscu
nieczytelnego pliku Folderów, Przypomnień o raporcie albo pliku pary Reguł ilości i Listy Urządzeń ``Unreadable`` z
jego nazwą, więc start procesu odmawia tym samym zdaniem, a Logi Urwanego Uruchomienia, praca Przypomnień o raporcie i
odczyty okna Centrum (Tablica okresów, różnice Kontroli ilości, podpowiedzi Wykonawców) mówią, którego pliku nie dało
się przeczytać.
Wołający, który bez pliku odpowiada tacie odmową (Tablica okresów, ścieżki okresu, Uzupełnienie, różnice Kontroli
ilości, otwarcie Rejestru zleceń, podgląd zmiany reguły albo kodu, Wysyłka rozliczeń, start procesu), bierze wartość
nazwą bez przyrostka (``folders``, ``QuantityRulesView.rules``, ``counted_activity_legend``, własności
``SettingsSnapshot``, ``WorkerListRead.counted``): plik, którego system nie daje teraz czytać, to tam odmowa 409 o nim
(``refusal.settings_file_unreadable``, a dla Listy Wykonawców ``refusal.workers_unusable``), a nie treść z Wydania, którą tata wziąłby za niewskazany folder okresów albo za
swoje Reguły ilości; odczyt niczego nie zapisuje, więc ta odmowa nie jest regułą przyjęcia zmiany. Unię z
``Unreadable`` daje tylko nazwa z przyrostkiem ``_or_unreadable``, dla wołającego, który o pliku mówi albo czeka.
``Unreadable`` nie ma podklas, a mypy w ``src/`` ma ``warn_unreachable``, więc gałąź „bez odczytu” przy wartości
bez unii, także z literałem albo konstruktorem z wartościami domyślnymi w niej, nie przechodzi mypy.
Listę Wykonawców migawka i okno Ustawień niosą jako jej odczyt (``WorkerListRead``), bo zła lista bez ostatniej dobrej
to trzeci wynik obok listy i pliku bez odczytu: o nim, o liście dla procesu i o tym, co pokazać, rozstrzyga ten typ, a
nie wołający.
Reguły ilości i Lista Urządzeń mają do tego jeden wspólny niezmiennik: każde przyjęcie jednego z nich (``_paired``:
odczyt, także bez zapisu w ``read_snapshot``, zapis, cofnięcie) sprawdza go razem z drugim, więc plik, który do drugiego
nie pasuje, jest zły tak samo jak plik z uszkodzoną treścią, a procesy liczą ostatnią dobrą parą. Reguły ilości z
Wydania (tata nie ma pliku reguł) są zawsze dobre, a lista, której brakuje ich składnika, jest zła i procesy biorą ten
składnik z Listy Urządzeń z Wydania; składnik, którego każdy zapis ma lista taty, nie dochodzi, a lista bez niego jest
dobra (``quantity_rules``). Plik, który zaczyna pasować dopiero po zmianie drugiego, ma wtedy wiersz ``spoza`` jak
zmiana jego treści. Pliku pary, którego drugiego pliku system nie daje teraz czytać, nikt nie sprawdzi
(``Unreadable`` z ``_paired``): odczyt czeka z werdyktem, bez wiersza Historii i bez pamięci, do odczytu, w którym
oba pliki są czytelne, a zapis to ``NotSaved`` z nazwą drugiego pliku. Treść z Wydania w miejscu drugiego pliku dałaby
Historii wiersz ``odrzucono`` zmiany, która do pliku taty pasuje.
Każdy zapis taty pary (formularz sekcji, „Dodaj” z podpowiedzi, „Popraw regułę”, „Cofnij”) idzie przez ``_dad_change``,
które sprawdza go jako zmianę, zanim ``_checked`` zobaczy plik: odmowa mówi, co zmiana psuje (zapis u dwóch składników,
składnik potrzebny regule, reguła bez składnika, zapis, który tata musi zwolnić dla składnika z Wydania), tym samym
zdaniem dla formularza i „Cofnij”, a zdanie reguły ma kolumny z cennika (``column_names``). Przy Regułach ilości z
Wydania zmiana listy dostaje listę uzupełnioną i zapisuje ją uzupełnioną, a pierwszy plik reguł taty zapisuje najpierw
listę, do której pasuje (``quantity_rules.dad_devices_edit``, ``devices_for_dad_rules``, ``dad_rules_problem``).
Zapis taty Legendy czynności (formularz kodu, „Cofnij”) też idzie przez ``_dad_change``: odmowa to zdanie silnika legendy
o legendzie po zmianie, nie zdanie o złym pliku (``activity_legend.legend_refusal``).

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
from typing import Any, Final, Literal, Protocol, TypeVar, final
import uuid

from rozliczenia.centrum import device_forms, legend_forms, refusal, rule_forms
from rozliczenia.centrum.atomic_file import RETRY_PAUSES_S, replace_atomically
from rozliczenia.centrum.contract.activity_legend import ActivityCodeEdit
from rozliczenia.centrum.contract.quantity_rules import RuleEdit
from rozliczenia.centrum.device_forms import DeviceEdit
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.centrum.platform import Autostart
from rozliczenia.centrum.settings.activity_legend import LEGEND, Codes, activity_legend, code_ids, legend_refusal
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
from rozliczenia.centrum.settings.folders import FOLDERS, FolderSettings, FoldersEdit, dad_folders
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
from rozliczenia.centrum.settings.quantity_exceptions import EXCEPTIONS, QuantityException, with_exception
from rozliczenia.centrum.settings.quantity_rules import (
    DEVICES,
    RULES,
    ColumnNames,
    DevicesEdit,
    dad_devices_edit,
    device_ids,
    dad_rules_problem,
    devices_for_dad_rules,
    devices_problem,
    listed_name,
    quantity_rules,
    rule_ids,
    rules_problem,
    taken_problem,
)
from rozliczenia.centrum.settings.reminders import REMINDERS, RemindersEdit, dad_reminders
from rozliczenia.centrum.settings.settlement_mail import SETTLEMENT_MAIL, WrittenMail, written
from rozliczenia.centrum.settings.workers import WORKERS, AddWorker, WorkersEdit, dad_workers
from rozliczenia.activity_legend import ActivityCode, ActivityLegend
from rozliczenia.quantity_engine import Component, DeviceList, QuantityRule, QuantityRules
from rozliczenia.settlement_mailing import SettlementMailSettings
from rozliczenia.worker_list import Unresolved, Worker, WorkerList
from rozliczenia.worker_periods import InPeriod, InRegister, NotInPeriods, Unchecked, WorkerPeriods
from rozliczenia.worker_report_inbox import InboxState
from rozliczenia.worker_reports import ReminderSettings

T = TypeVar("T")

REPORTED_CHANGES: Final = 20
"""Najwyżej tyle najnowszych wierszy Historii podaje Zgłoszenie."""
HISTORY_UNREADABLE: Final = "- Historii Ustawień nie dało się przeczytać"
"""Linia Zgłoszenia zamiast zmian, gdy system nie daje czytać pliku Historii."""
_RulesEdit = Callable[[tuple[QuantityRule, ...]], tuple[QuantityRule, ...] | FieldProblem]
"""Zmiana taty Reguł ilości: bieżące reguły → reguły po zmianie albo problem, który jest odmową bez zapisu."""


_PairCheck = Callable[[Any], FieldProblem | Unreadable | None]
"""Problem dobrej wartości pliku pary Reguł ilości i Listy Urządzeń razem z drugim plikiem; ``None``: para pasuje, a
``Unreadable``: drugiego pliku system nie daje teraz czytać, więc nie wiadomo."""


@final
@dataclass(frozen=True)
class ShownWorkers:
    """Lista Wykonawców, którą pokazuje okno Ustawień, ze stanem i problemem pliku (``None``: plik dobry): przy złym
    pliku ostatnia dobra, a bez niej i przy pliku bez odczytu pusta. To nie ``WorkerList``, więc odczyt, który z listy
    liczy (start, Przypomnienia o raporcie, Wysyłka rozliczeń, podpowiedzi), jej nie przyjmie (mypy), a listę, którą
    liczy, daje ``WorkerListRead.counted``."""

    state: Literal["good", "bad", "unreadable"]
    workers: tuple[Worker, ...]
    unresolved: tuple[Unresolved, ...]
    problem: FieldProblem | None


@final
@dataclass(frozen=True)
class WorkerListRead:
    """Lista Wykonawców z jednej chwili: którą listą liczy Uruchomienie, co powiedzieć o pliku i co pokazać w oknie.
    Buduje ją właściciel Ustawień z odczytu pliku (``snapshot``, ``read_snapshot``, ``view``), a sam odczyt (dobry, zły
    z ostatnią dobrą listą albo bez niej, bez odczytu) zostaje w środku, więc wołający nie rozstrzyga go po swojemu.
    Zła lista bez ostatniej dobrej to nie pusta lista ani plik bez odczytu, bo proces bez Listy Wykonawców nie startuje,
    a tata ma usłyszeć, co poprawić.

    Klasa nie ma podklas, więc gałąź ``isinstance`` z typem odczytu pliku (``Good``, ``Unreadable``) przy tej wartości
    jest dla mypy martwa (``warn_unreachable`` w ``src/``)."""

    _read: Read[WorkerList] | Unreadable

    def counted(self) -> WorkerList:
        """Lista, którą liczy Uruchomienie: dobra albo przy złym pliku ostatnia dobra. Zła bez ostatniej dobrej to odmowa
        jej zdaniem, a plik, którego system nie daje teraz czytać, odmowa zdaniem o Liście Wykonawców bez odczytu (obie
        ``refusal.workers_unusable``)."""

        match self.counted_or_unreadable():
            case Unreadable():
                raise refusal.workers_unusable(None)
            case FieldProblem() as problem:
                raise refusal.workers_unusable(problem)
            case WorkerList() as workers:
                return workers

    def counted_or_unreadable(self) -> WorkerList | Unreadable | FieldProblem:
        """Lista, którą liczy Uruchomienie, dla wołającego, który bez niej nie odmawia, tylko mówi o tym albo czeka (stan
        okna, ponowienie Przypomnień, próba): zła bez ostatniej dobrej to jej problem, a plik bez odczytu ``Unreadable``
        z jego nazwą."""

        return _counted(self._read, WORKERS)

    def problem(self) -> FieldProblem | Unreadable | None:
        """Problem pliku, także gdy Uruchomienie liczy ostatnią dobrą listą (Diagnoza, blokada karty Wpisania raportów);
        ``None``: plik dobry."""

        match self._read:
            case Good():
                return None
            case Bad(problem=problem):
                return problem
            case Unreadable() as unreadable:
                return unreadable

    def last_good(self) -> FieldProblem | None:
        """Problem złego pliku, gdy Uruchomienie liczy ostatnią dobrą listą (ostrzeżenie startu); ``None``: plik dobry,
        zły bez ostatniej dobrej albo bez odczytu."""

        read = self._read
        return read.problem if isinstance(read, Bad) and read.usable is not None else None

    def shown(self) -> ShownWorkers:
        """Lista dla okna Ustawień (``ShownWorkers``)."""

        match self._read:
            case Good(value=workers):
                return ShownWorkers("good", workers.workers, workers.unresolved, None)
            case Bad(problem=problem, usable=usable):
                listed = WorkerList(()) if usable is None else usable
                return ShownWorkers("bad", listed.workers, listed.unresolved, problem)
            case Unreadable():
                return ShownWorkers("unreadable", (), (), FieldProblem(None, messages.worker_list_unreadable()))


@dataclass(frozen=True)
class SettingsSnapshot:
    """Wartości Ustawień Centrum z jednej chwili. Foldery i Przypomnienia o raporcie: dobre, a przy złym pliku ostatnie
    dobre albo domyślne. Lista Wykonawców jako jej odczyt (``WorkerListRead``), bo proces bez ostatniej dobrej listy nie
    startuje, a ostatnią dobrą liczy z ostrzeżeniem startu.

    Wołający, który bez pliku odmawia, bierze wartość własnością bez przyrostka (``folders``, ``reminders``,
    ``quantity_rules``, ``activity_legend``, ``settlement_mail``, a Listę Wykonawców ``workers.counted()``): plik,
    którego system nie daje teraz czytać, to tam odmowa o nim (``refusal.settings_file_unreadable``, a dla Listy
    Wykonawców ``refusal.workers_unusable``), więc gałęzi „bez odczytu” w jego kodzie nie ma, a literał w takiej gałęzi
    to dla mypy kod martwy. Unię z ``Unreadable`` daje tylko nazwa z przyrostkiem ``_or_unreadable`` (pole albo
    ``workers.counted_or_unreadable()``), dla wołającego, który bez pliku nie odmawia, tylko mówi o nim albo czeka: stan
    karty i okna, Logi, ponowienie w porze, miękka podpowiedź."""

    folders_or_unreadable: FolderSettings | Unreadable
    workers: WorkerListRead
    inbox: InboxState
    reminders_or_unreadable: ReminderSettings | Unreadable
    quantity_rules_or_unreadable: QuantityRules | Unreadable
    """Reguły ilości z Listą Urządzeń, którymi liczy Uruchomienie: przy złym pliku albo pliku, który nie pasuje do
    drugiego, ostatnia dobra para, a przy pliku pary, którego system nie daje teraz czytać, ``Unreadable``."""
    activity_legend_or_unreadable: ActivityLegend | Unreadable
    """Legenda czynności, którą liczy Uruchomienie: przy złym pliku ostatnia dobra, a przy pliku, którego system nie
    daje teraz czytać, ``Unreadable``."""
    settlement_mail_or_unreadable: SettlementMailSettings | Unreadable | FieldProblem
    """Temat i treść Maila z rozliczeniem taty: przy złym pliku ostatnie dobre, a bez nich problem pliku
    (``FieldProblem``), bo mail z tematem i treścią z Wydania nie byłby mailem taty; przy pliku, którego system nie daje
    teraz czytać, ``Unreadable``. Brak pliku to wartości domyślne: tata niczego nie pisał."""

    @property
    def folders(self) -> FolderSettings:
        return _readable(self.folders_or_unreadable)

    @property
    def reminders(self) -> ReminderSettings:
        return _readable(self.reminders_or_unreadable)

    @property
    def quantity_rules(self) -> QuantityRules:
        return _readable(self.quantity_rules_or_unreadable)

    @property
    def activity_legend(self) -> ActivityLegend:
        return _readable(self.activity_legend_or_unreadable)

    @property
    def settlement_mail(self) -> SettlementMailSettings:
        """Temat i treść taty; zła treść bez ostatniej dobrej to odmowa jej zdaniem (``refusal.settlement_mail_unusable``),
        a nie mail z tematem i treścią z Wydania."""

        mail = self.settlement_mail_or_unreadable
        if isinstance(mail, FieldProblem):
            raise refusal.settlement_mail_unusable(mail)
        return _readable(mail)


def _readable(value: T | Unreadable) -> T:
    """Wartość pliku Ustawień, a plik, którego system nie daje teraz czytać, to odmowa o nim."""

    if isinstance(value, Unreadable):
        raise refusal.settings_file_unreadable(value.name)
    return value


@final
@dataclass(frozen=True)
class ShownQuantityRules:
    """Reguły ilości z Listą Urządzeń, które pokazuje okno Ustawień obok problemu pliku: przy pliku pary bez odczytu z
    Wydania. To nie ``QuantityRules``, więc odczyt, który z reguł liczy (podpowiedzi, podgląd, Uruchomienie), ich nie
    przyjmie (mypy), a reguły, którymi liczy, daje ``QuantityRulesView.rules``."""

    rules: tuple[QuantityRule, ...]
    devices: DeviceList


@final
@dataclass(frozen=True)
class ShownActivityLegend:
    """Kody Legendy czynności, które pokazuje okno Ustawień: przy złym pliku ostatnie dobre, przy pliku bez odczytu z
    Wydania. To nie ``ActivityLegend``, więc odczyt, który legendą liczy, jej nie przyjmie (mypy), a legendę, którą
    liczy, daje ``CentrumSettings.counted_activity_legend``."""

    codes: tuple[ActivityCode, ...]


@dataclass(frozen=True)
class QuantityRulesView:
    """Reguły ilości dla okna Ustawień: te, którymi liczy następne Uruchomienie, wyjątki Kontroli ilości (przy złym
    pliku ostatnie dobre) i problem każdego pliku (``None``: plik dobry). Plik reguł albo listy, który nie pasuje do
    drugiego, ma problem jak zły plik. Lista Urządzeń, której zapisy ma składnik z Listy Urządzeń z Wydania, a Reguły
    ilości z Wydania liczą bez niego, ma zamiast problemu zdanie o nim (``taken_problem``), a Reguły ilości zdanie, że
    ich zmiana zapisze się dopiero ze zwolnionym zapisem (``devices_for_dad_rules``). ``source_rules``: reguły z pliku
    albo z Wydania, z których powstały te liczone; zmienia je zapis reguł taty. Pliku reguł, którego system nie daje
    teraz czytać, nikt nie zna (``Unreadable``)."""

    rules_or_unreadable: QuantityRules | Unreadable
    """Reguły, którymi liczy następne Uruchomienie; plik pary, którego system nie daje teraz czytać, to ``Unreadable``
    z jego nazwą, a nie treść z Wydania. Odczyt, który bez nich odmawia, bierze ``rules``."""
    shown: ShownQuantityRules
    """Reguły, które pokazuje okno Ustawień obok problemu pliku (``ShownQuantityRules``)."""
    rules_problem: FieldProblem | None
    devices_problem: FieldProblem | None
    source_rules: tuple[QuantityRule, ...] | Unreadable
    exceptions: tuple[QuantityException, ...]
    exceptions_problem: FieldProblem | None

    @property
    def rules(self) -> QuantityRules:
        """Reguły, którymi liczy następne Uruchomienie; plik pary bez odczytu to odmowa o nim."""

        return _readable(self.rules_or_unreadable)


@dataclass(frozen=True)
class ActivityLegendView:
    """Legenda czynności dla okna Ustawień i problem pliku (``None``: plik dobry). Przy pliku bez odczytu problem mówi,
    że proces nie wystartuje, bo migawka ma wtedy ``Unreadable``."""

    shown: ShownActivityLegend
    """Legenda, którą pokazuje okno Ustawień (``ShownActivityLegend``)."""
    problem: FieldProblem | None
    codes: tuple[ActivityCode, ...] | Unreadable
    """Kody, z których powstała legenda (z pliku, ostatnie dobre albo z Wydania); zmienia je zapis taty. Pliku, którego
    system nie daje teraz czytać, nikt nie zna (``Unreadable``)."""


@dataclass(frozen=True)
class SettlementMailView:
    """Temat i treść Maila z rozliczeniem dla okna Ustawień: odczyt pliku (stan i problem) i to, co stoi w polach."""

    read: Read[SettlementMailSettings] | Unreadable
    shown: WrittenMail
    """Temat i treść w polach okna: dobre albo ostatnie dobre, którymi liczy Wysyłka rozliczeń; bez nich temat i treść
    z pliku taty bez reguł (``written``), od których zaczyna zapis taty, a przy pliku bez odczytu albo bez kształtu pliku
    tematu i treści wartości domyślne. Tylko do pokazania: wartość dla procesu daje migawka."""


@dataclass(frozen=True)
class SettingsView:
    """Ustawienia Centrum dla okna Ustawień: każda sekcja z wartością albo złym ustawieniem."""

    folders: Read[FolderSettings] | Unreadable
    workers: WorkerListRead
    inbox: Read[InboxFile] | Unreadable
    autostart: Read[bool] | Unreadable | Unsupported
    reminders: Read[ReminderSettings] | Unreadable
    settlement_mail: SettlementMailView


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
    """Pliku albo Historii nie dało się przeczytać lub zapisać, więc nic się nie zmieniło. ``unreadable``: plik Ustawień
    (nazwa w ``config``), którym zapis sprawdza zmianę taty (Foldery przy usuwaniu loginu, drugi plik pary Reguł ilości i
    Listy Urządzeń), a którego system nie daje teraz czytać: treść z Wydania w jego miejscu sprawdziłaby zmianę nie tym,
    co tata ma."""

    unreadable: str | None = None


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
        release_changes: tuple[ReleaseChange[Any], ...],
        release_origin: Callable[[], ReleaseOrigin],
    ) -> None:
        """Ustawienia w folderze ``config`` i skrót Centrum w folderze Autostart (``autostart``); ``now`` daje chwilę
        wiersza Historii, a ``pause`` czeka przed kolejną próbą odczytu albo zapisu pliku, który system na chwilę
        trzyma. ``periods`` szuka w okresach loginów, które zmiana taty usuwa z Listy Wykonawców, a ``column_names``
        daje nazwy kolumn z cennika do zdania reguły w odmowie zmiany pary. ``release_changes`` to zmiany z Wydania, a
        ``release_origin`` daje wersję narzędzia do ich wiersza Historii (``apply_release_changes``): dostaje je tylko
        konstruktor, więc kod z właścicielem w ręku nie poda mu zmiany z własną funkcją zapisu obok zapisu taty."""

        self._config = config
        self._log = log
        self._now = now
        self._pause = pause
        self._periods = periods
        self._column_names = column_names
        self._release_changes = release_changes
        self._release_origin = release_origin
        self._memory = Memory(config, pause)
        self._history = History(config, pause)
        self._lock = threading.Lock()
        self._absent: dict[str, str] = {}
        self._places: Mapping[str, _Place] = {
            FOLDERS.name: _ConfigFile(config / FOLDERS.name, pause),
            WORKERS.name: _ConfigFile(config / WORKERS.name, pause),
            REMINDERS.name: _ConfigFile(config / REMINDERS.name, pause),
            SETTLEMENT_MAIL.name: _ConfigFile(config / SETTLEMENT_MAIL.name, pause),
            INBOX.name: _ConfigFile(config / INBOX.name, pause),
            AUTOSTART.name: AutostartPlace(autostart),
            DEVICES.name: _ConfigFile(config / DEVICES.name, pause),
            RULES.name: _ConfigFile(config / RULES.name, pause),
            EXCEPTIONS.name: _ConfigFile(config / EXCEPTIONS.name, pause),
            LEGEND.name: _ConfigFile(config / LEGEND.name, pause),
        }

    def snapshot(self) -> SettingsSnapshot:
        """Wartości dla procesu: raz na start Uruchomienia, który kończy na nich bez względu na późniejsze zmiany."""

        with self._lock:
            folders = _or_unreadable(self._observe(FOLDERS), FOLDERS)
            workers = self._observe(WORKERS)
            inbox_state = inbox.state(self._observe(INBOX))
            reminders = _or_unreadable(self._observe(REMINDERS), REMINDERS)
            mail = _counted(self._observe(SETTLEMENT_MAIL), SETTLEMENT_MAIL)
            rules = self._quantity_rules()
            return SettingsSnapshot(
                folders_or_unreadable=folders,
                workers=WorkerListRead(workers),
                inbox=inbox_state,
                reminders_or_unreadable=reminders,
                quantity_rules_or_unreadable=rules.rules_or_unreadable,
                activity_legend_or_unreadable=self._activity_legend(),
                settlement_mail_or_unreadable=mail,
            )

    def folders(self) -> FolderSettings:
        """Foldery dla odczytu okna, który odpowiada tacie z bieżących Folderów (Tablica okresów, otwarcie Rejestru
        zleceń, podgląd reguły): plik, którego system nie daje teraz czytać, to odmowa o nim
        (``refusal.settings_file_unreadable``), a nie Rejestr i folder niewskazane."""

        return _readable(self.folders_or_unreadable())

    def folders_or_unreadable(self) -> FolderSettings | Unreadable:
        """Foldery dla odczytu okna, który przy pliku bez odczytu nie odmawia, tylko mówi o nim (podpowiedzi)."""

        with self._lock:
            return _or_unreadable(self._observe(FOLDERS), FOLDERS)

    def quantity_rules(self) -> QuantityRulesView:
        """Reguły ilości, Lista Urządzeń i wyjątki Kontroli ilości dla okna Ustawień, każdy plik porównany z pamięcią jak
        przy każdym odczycie."""

        with self._lock:
            return self._quantity_rules()

    def activity_legend(self) -> ActivityLegendView:
        """Legenda czynności dla okna Ustawień, plik porównany z pamięcią jak przy każdym odczycie."""

        with self._lock:
            observed = self._observe(LEGEND)
            codes = _usable(observed, LEGEND)
            shown = ShownActivityLegend(activity_legend(_or_release(observed, LEGEND)).codes)
            return ActivityLegendView(shown, _problem(observed, LEGEND, messages.unreadable), codes)

    def counted_activity_legend(self) -> ActivityLegend:
        """Legenda czynności, którą liczy następne Uruchomienie, jak w migawce, dla odczytu okna (Ilości do uzupełnienia,
        podgląd zmiany kodu) bez reszty migawki; plik porównany z pamięcią jak przy każdym odczycie, a plik bez odczytu
        to odmowa o nim."""

        with self._lock:
            return _readable(self._activity_legend())

    def _activity_legend(self) -> ActivityLegend | Unreadable:
        legend = self._observe(LEGEND)
        return legend if isinstance(legend, Unreadable) else activity_legend(_value(legend, LEGEND))

    def view(self) -> SettingsView:
        with self._lock:
            autostart = self._places[AUTOSTART.name].unsupported()
            return SettingsView(
                folders=self._observe(FOLDERS),
                workers=WorkerListRead(self._observe(WORKERS)),
                inbox=self._observe(INBOX),
                autostart=Unsupported() if autostart is not None else self._observe(AUTOSTART),
                reminders=self._observe(REMINDERS),
                settlement_mail=self._settlement_mail(),
            )

    def _settlement_mail(self) -> SettlementMailView:
        data = self._places[SETTLEMENT_MAIL.name].read()
        if isinstance(data, OSError):
            return SettlementMailView(Unreadable(SETTLEMENT_MAIL.name), _shown_mail(SETTLEMENT_MAIL.default))
        read = self._observed(SETTLEMENT_MAIL, data)
        match read:
            case Good(value=value) | Bad(usable=value) if value is not None:
                shown = _shown_mail(value)
            case _:
                shown = written(data) or _shown_mail(SETTLEMENT_MAIL.default)
        return SettlementMailView(read, shown)

    def change_folders(self, edit: FoldersEdit) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty sekcji Foldery albo motywu (``dad_folders``). Folder okresów od korzenia układu, który listuje
        folder okresów w OneDrive taty, liczy się przed blokadą, więc inne żądania Ustawień na niego nie czekają, i
        tylko przy folderze innym niż bieżący."""

        current = self.folders_or_unreadable()
        before = None if isinstance(current, Unreadable) else current.periods_directory
        return self._by_dad(FOLDERS, dad_folders(edit, before), undoes=None)

    def change_autostart(self, enabled: bool) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty przełącznika startu razem z Windows."""

        return self._by_dad(AUTOSTART, lambda _: enabled, undoes=None)

    def change_inbox_password(self, typed: str) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty hasła skrzynki raportów wpisanego jako ``typed``: puste hasło i plik bez adresu to odmowa
        (``inbox.new_password``), a nowe hasło zastępuje tylko linię hasła pliku."""

        with self._lock:
            password = inbox.new_password(self._observe(INBOX), typed)
        if isinstance(password, FieldProblem):
            return Refused(password)
        return self._by_dad(INBOX, lambda current: inbox.with_password(current, password), undoes=None)

    def change_reminders(self, edit: RemindersEdit) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty Przypomnień o raporcie (``dad_reminders``)."""

        return self._by_dad(REMINDERS, lambda current: dad_reminders(current, edit), undoes=None)

    def change_settlement_mail(self, form: SettlementMailSettings) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty tematu i treści Maila z rozliczeniem (formularz przeczytany regułą pliku)."""

        return self._by_dad(SETTLEMENT_MAIL, lambda _: form, undoes=None)

    def change_workers(self, edit: WorkersEdit) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty Listy Wykonawców (``dad_workers``); loginy, które usuwa, sprawdza w okresach ``_by_dad``,
        ta sama droga co „Cofnij”. Zmiana Wykonawcy z listy (wszystko poza dodaniem) zaczyna od listy, którą liczy
        Uruchomienie, z odczytu zapisu: bez niej to odmowa ``refusal.workers_unusable``, a nie „Tego Wykonawcy nie ma”."""

        unusable = None if isinstance(edit, AddWorker) else refusal.workers_unusable
        return self._by_dad(WORKERS, lambda current: dad_workers(current, edit), undoes=None, unusable=unusable)

    def change_exceptions(self, exception: QuantityException) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zapis taty „To był wyjątek”: wyjątek Kontroli ilości ``exception`` dopisany do pliku wyjątków
        (``with_exception``)."""

        return self._by_dad(EXCEPTIONS, lambda current: with_exception(current, exception), undoes=None)

    def change_devices(self, edit: DeviceEdit) -> Saved | Refused | NotSaved:
        """Zapis taty polecenia sekcji Urządzenia (``device_forms.dad_devices``) z id nowego składnika spoza kluczy
        Historii; parę z regułami i uzupełnienie listy sprawdza ``_dad_change``, ta sama droga co „Cofnij”."""

        return self._with_used_keys(DEVICES, lambda current, keys: device_forms.dad_devices(current, edit, device_ids(keys)))

    def change_rules(self, edit: RuleEdit) -> Saved | Refused | NotSaved:
        """Zapis taty polecenia edytora reguł (``rule_forms.dad_rules``) z id nowej reguły spoza kluczy Historii."""

        return self._with_used_keys(RULES, lambda current, keys: rule_forms.dad_rules(current, edit, rule_ids(keys)))

    def change_legend(self, edit: ActivityCodeEdit) -> Saved | Refused | NotSaved:
        """Zapis taty polecenia formularza kodu (``legend_forms.dad_legend``) z id nowego kodu spoza kluczy Historii;
        legendę po zmianie sprawdza ``_dad_change`` tym samym zdaniem co „Cofnij”."""

        return self._with_used_keys(LEGEND, lambda current, keys: legend_forms.dad_legend(current, edit, code_ids(keys)))

    def _with_used_keys(
        self, file: SettingsFile[T], edit: Callable[[T, frozenset[str]], T | FieldProblem]
    ) -> Saved | Refused | NotSaved:
        """Zapis taty, w którym ``edit`` dostaje też klucze pliku z wierszy Historii (``_used_keys``), przeczytane pod tą
        samą blokadą co zapis: nowy wpis dostaje wtedy klucz, którego nie zna żaden wiersz, więc „Cofnij” starszego
        wiersza go nie rusza. Historia, której nie da się przeczytać, to ``NotSaved``."""

        with self._lock:
            keys = self._used_keys(file)
            if isinstance(keys, Unreadable):
                self._log.settings_unreadable(cause="historia")
                return NotSaved()
            return self._dad_change(file, lambda current: edit(current, keys), undoes=None, checked=frozenset())

    def rules_after(self, edit: RuleEdit) -> QuantityRules | FieldProblem | NotSaved:
        """Reguły ilości z Listą Urządzeń, które da zapis taty polecenia ``edit`` (``change_rules``), albo jego odmowa,
        bez zapisu: podgląd zmiany reguły sprawdza tym to samo, co sprawdzi zapis (``_dad_rules``). Id nowej reguły spoza
        kluczy Historii nadaje dopiero zapis; podgląd go nie pokazuje, a żadna odmowa reguł nie zależy od niego, więc
        Historii nie czyta. Plik pary, którego system nie daje teraz czytać, to ``NotSaved`` z jego nazwą, jak w zapisie."""

        with self._lock:
            paired = self._rules_after(lambda current: rule_forms.dad_rules(current, edit, frozenset()))
            if isinstance(paired, FieldProblem | NotSaved):
                return paired
            return QuantityRules(paired[0], DeviceList(paired[1]))

    def legend_after(self, edit: ActivityCodeEdit) -> ActivityLegend | FieldProblem | NotSaved:
        """Legenda czynności, którą da zapis taty polecenia ``edit`` (``change_legend``), albo jego odmowa, bez zapisu:
        podgląd zmiany kodu sprawdza tym to samo, co sprawdzi zapis (``_dad_legend`` i parser pliku w ``_change``). Id
        nowego kodu spoza kluczy Historii nadaje dopiero zapis, a żadna odmowa legendy od niego nie zależy, więc Historii
        nie czyta. Plik legendy, którego system nie daje teraz czytać, to ``NotSaved`` z jego nazwą, jak w zapisie."""

        with self._lock:
            current = _usable(self._observe_for_change(LEGEND), LEGEND)
            if isinstance(current, Unreadable):
                return NotSaved(LEGEND.name)
            codes = legend_refusal(legend_forms.dad_legend(current, edit, frozenset()))
            if isinstance(codes, FieldProblem):
                return codes
            parsed = LEGEND.parse(LEGEND.dump(codes))
            return parsed if isinstance(parsed, FieldProblem) else activity_legend(parsed)

    def _release(self) -> bool:
        """Procesy liczą Regułami ilości z Wydania: tata nie ma pliku reguł."""

        return self._places[RULES.name].read() is None

    def _used_keys(self, file: SettingsFile[Any]) -> frozenset[str] | Unreadable:
        """Klucze, które plik ``file`` ma w wierszach Historii Ustawień, z każdego źródła i wyniku. Linia Historii, której
        nie da się przeczytać, nie daje klucza, ale też nie da się jej cofnąć."""

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

    def apply_release_changes(self) -> None:
        """Zmiany z Wydania z konstruktora, których pamięć jeszcze nie ma, po kolei; ``release_origin`` daje wersję
        narzędzia do Historii i pyta Gita tylko wtedy, gdy jest co zastosować. Niczego nie podnosi: start Centrum nie pada
        na zmianie z Wydania."""

        changes = self._release_changes
        with self._lock:
            remembered = self._memory.applied()
            if isinstance(remembered, AppliedUnknown):
                for change in changes:
                    self._log.settings_release(change=change.id, result="bez-pamieci")
                applied: dict[str, Applied] = {}
            else:
                applied = remembered
                self._apply_pending(changes, applied, self._release_origin)
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
        source_rules = _usable(rules, RULES)
        usable_rules, usable_devices = _or_release(rules, RULES), _or_release(devices, DEVICES)
        waiting = devices_for_dad_rules(usable_devices, usable_rules, usable_rules) if self._release() else None
        unreadable = next((read for read in (rules, devices) if isinstance(read, Unreadable)), None)
        shown = quantity_rules(usable_rules, usable_devices)
        return QuantityRulesView(
            shown if unreadable is None else unreadable,
            ShownQuantityRules(shown.rules, shown.devices),
            _problem(rules, RULES, messages.unreadable) or (waiting if isinstance(waiting, FieldProblem) else None),
            _problem(devices, DEVICES, messages.unreadable) or taken_problem(usable_rules, usable_devices),
            source_rules,
            _or_release(exceptions, EXCEPTIONS),
            _problem(exceptions, EXCEPTIONS, messages.unavailable),
        )

    def _checked(
        self, file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem
    ) -> T | FieldProblem | Unreadable:
        """Wartość pliku w stanie ``data`` z niezmiennikiem pary Reguł ilości i Listy Urządzeń (``_paired``) z bieżącymi
        plikami i pamięcią właściciela; ``Unreadable``: drugiego pliku pary system nie daje teraz czytać."""

        together: Mapping[str, _PairCheck] = {
            RULES.name: self._rules_problem,
            DEVICES.name: self._devices_problem,
        }
        return _paired(file, data, parsed, together)

    def _rules_problem(self, rules: tuple[QuantityRule, ...]) -> FieldProblem | Unreadable | None:
        """Reguły z bieżącą Listą Urządzeń albo z ostatnią dobrą; listy nie porównuje z pamięcią, bo jej przyjęcie
        zależy od przyjęcia reguł."""

        data = self._places[DEVICES.name].read()
        return _rules_problem(rules, data, self._memory.read(DEVICES.name))

    def _devices_problem(self, devices: tuple[Component, ...]) -> FieldProblem | Unreadable | None:
        """Lista z regułami, którymi liczą procesy: reguły przyjmuje się pierwsze."""

        rules = self._observe(RULES)
        if isinstance(rules, Unreadable):
            return rules
        return devices_problem(
            devices,
            _value(rules, RULES),
            _last_good_devices(self._memory.read(DEVICES.name)),
            release=self._release(),
        )

    def _by_dad(
        self,
        file: SettingsFile[T],
        edit: Callable[[T], T | FieldProblem],
        *,
        undoes: str | None,
        unusable: Callable[[FieldProblem | None], refusal.Refusal] | None = None,
    ) -> Saved | Refused | NotSaved | KeptInPeriods:
        """Zmiana taty: loginy, które usuwa z Listy Wykonawców, najpierw poza blokadą sprawdza w okresach, potem zapisuje
        z nimi jako sprawdzonymi."""

        with self._lock:
            removed = self._removed_logins(file, edit)
            if removed is None:
                return self._dad_change(file, edit, undoes=undoes, checked=frozenset(), unusable=unusable)
            folders = _usable(self._observe(FOLDERS), FOLDERS)
            if isinstance(folders, Unreadable):
                self._log.settings_unreadable(cause="dostep")
                return NotSaved(FOLDERS.name)
        presence = self._periods.find(removed.logins, folders.register, folders.periods_directory)
        if not isinstance(presence, NotInPeriods):
            return KeptInPeriods(presence, removed.what)
        with self._lock:
            return self._dad_change(file, edit, undoes=undoes, checked=removed.logins, unusable=unusable)

    def _dad_change(
        self,
        file: SettingsFile[T],
        edit: Callable[[T], T | FieldProblem],
        *,
        undoes: str | None,
        checked: frozenset[str],
        unusable: Callable[[FieldProblem | None], refusal.Refusal] | None = None,
    ) -> Saved | Refused | NotSaved:
        """Zapis taty pod blokadą; jedyna droga zapisu taty Listy Urządzeń, Reguł ilości i Legendy czynności, więc jedyne
        miejsce, które sprawdza go jako zmianę pary albo legendy i daje odmowę zdaniem o tej zmianie (``_dad_devices``,
        ``_dad_rules``, ``_dad_legend``)."""

        paired: Mapping[str, Callable[..., Saved | Refused | NotSaved]] = {
            DEVICES.name: self._dad_devices,
            RULES.name: self._dad_rules,
            LEGEND.name: self._dad_legend,
        }
        write = paired.get(file.name)
        if write is None:
            return self._change(file, edit, undoes=undoes, source=ByDad(), undoable=True, checked=checked, unusable=unusable)
        return write(edit, undoes=undoes, checked=checked)

    def _dad_legend(self, edit: Callable[[Codes], Codes | FieldProblem], *, undoes: str | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        """Zmiana taty Legendy czynności z odmową zdaniem silnika o legendzie po zmianie (``legend_refusal``)."""

        return self._change(LEGEND, lambda current: legend_refusal(edit(current)), undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _dad_devices(self, edit: DevicesEdit, *, undoes: str | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        """Zmiana taty Listy Urządzeń sprawdzona jako zmiana z regułami, którymi liczy Centrum; przy Regułach ilości z
        Wydania na liście uzupełnionej i zapisana uzupełniona (``dad_devices_edit``). Reguły z Wydania w miejscu pliku
        reguł, którego system nie daje teraz czytać, puściłyby usunięcie składnika, którego potrzebuje reguła taty."""

        rules = _usable(self._observe_for_change(RULES), RULES)
        if isinstance(rules, Unreadable):
            self._log.settings_unreadable(cause="dostep")
            return NotSaved(RULES.name)
        changed = dad_devices_edit(edit, rules, self._column_names, release=self._release())
        return self._change(DEVICES, changed, undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _dad_rules(self, edit: _RulesEdit, *, undoes: str | None, checked: frozenset[str]) -> Saved | Refused | NotSaved:
        """Zmiana taty Reguł ilości sprawdzona jako zmiana z Listą Urządzeń (``_rules_after``). Pierwszy plik reguł taty w
        miejsce Reguł ilości z Wydania zapisuje najpierw listę, do której pasuje (osobny wiersz Historii, jak „ołówek,
        Zapisz” przy składniku z Wydania)."""

        paired = self._rules_after(edit)
        if isinstance(paired, FieldProblem):
            return Refused(paired)
        if isinstance(paired, NotSaved):
            self._log.settings_unreadable(cause="dostep")
            return paired
        _, devices = paired
        if devices != _or_release(self._observe(DEVICES), DEVICES):
            listed = self._change(DEVICES, lambda _: devices, undoes=None, source=ByDad(), undoable=True, checked=checked)
            if not isinstance(listed, Saved):
                return listed
        return self._change(RULES, edit, undoes=undoes, source=ByDad(), undoable=True, checked=checked)

    def _rules_after(
        self, edit: _RulesEdit
    ) -> tuple[tuple[QuantityRule, ...], tuple[Component, ...]] | FieldProblem | NotSaved:
        """Reguły po zmianie taty ``edit`` z Listą Urządzeń, z którą się zapiszą, albo odmowa zdaniem o tej zmianie: przy
        Regułach ilości z Wydania lista dostaje składniki z Wydania, których reguły potrzebują, albo zmiana czeka na
        zapis, który tata musi zwolnić (``devices_for_dad_rules``); reguła bez składnika na liście to jej zdanie ze
        składnikiem nazwanym jak ostatnio na liście (``dad_rules_problem``). Pliku pary, którego system nie daje czytać
        także po ponowieniach (``_observe_for_change``), zmiana nie zna (``NotSaved`` z jego nazwą): lista z Wydania
        sprawdziłaby regułę nie listą taty."""

        current = _usable(self._observe_for_change(RULES), RULES)
        if isinstance(current, Unreadable):
            return NotSaved(RULES.name)
        rules = edit(current)
        if isinstance(rules, FieldProblem):
            return rules
        devices = _usable(self._observe_for_change(DEVICES), DEVICES)
        if isinstance(devices, Unreadable):
            return NotSaved(DEVICES.name)
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
        current = _usable(self._observe_for_change(file), file)
        if isinstance(current, Unreadable):
            return None
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
        unusable: Callable[[FieldProblem | None], refusal.Refusal] | None = None,
    ) -> Saved | Refused | NotSaved:
        """Zapis wartości od ``edit``. ``checked``: loginy, które zmiana może usunąć z Listy Wykonawców, bo sprawdzono je
        w okresach; usunięcie innego to odmowa. ``None``: zmiana Maksa z Wydania, bez sprawdzenia. ``unusable``: odmowa
        zmiany, która zaczyna od wartości, którą liczy Uruchomienie, gdy tego odczytu jej nie daje: zła treść bez ostatniej
        dobrej (jej problem) albo plik bez odczytu także po ponowieniach (``None``)."""

        place = self._places[file.name]
        unsupported = place.unsupported()
        if unsupported is not None:
            return Refused(unsupported)
        data = self._bytes_for_change(place, file.name)
        if isinstance(data, Unreadable) or isinstance(self._memory.read(file.name), Unreadable):
            self._log.settings_unreadable(cause="dostep")
            if isinstance(data, Unreadable) and unusable is not None:
                raise unusable(None)
            return NotSaved()
        observed = self._observed(file, data)
        if isinstance(observed, Bad) and observed.usable is None and unusable is not None:
            raise unusable(observed.problem)
        if isinstance(observed, Bad) and file.secret and observed.usable is None:
            return Refused(observed.problem)
        current = _value(observed, file)
        value = edit(current)
        if isinstance(value, FieldProblem):
            return Refused(value)
        new = file.dump(value)
        edited = self._checked(file, new, file.parse(new))
        if isinstance(edited, Unreadable):
            self._log.settings_unreadable(cause="dostep")
            return NotSaved(edited.name)
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

    def _bytes_for_change(self, place: _Place, name: str) -> bytes | None | Unreadable:
        """Stan przed zmianą pliku ``name``; stan, którego system nie daje czytać, czyta ponownie po kolejnych przerwach."""

        data = place.read()
        for seconds in RETRY_PAUSES_S:
            if not isinstance(data, OSError):
                break
            self._pause(seconds)
            data = place.read()
        return Unreadable(name) if isinstance(data, OSError) else data

    def _observe(self, file: SettingsFile[T]) -> Read[T] | Unreadable:
        data = self._places[file.name].read()
        if isinstance(data, OSError):
            return Unreadable(file.name)
        return self._observed(file, data)

    def _observe_for_change(self, file: SettingsFile[T]) -> Read[T] | Unreadable:
        """Plik pary, którym zapis taty sprawdza zmianę, z tymi samymi ponowieniami co plik zapisywany
        (``_bytes_for_change``): chwilowa blokada (np. OneDrive) nie daje tacie odmowy, którą zapis by przeczekał."""

        data = self._bytes_for_change(self._places[file.name], file.name)
        return data if isinstance(data, Unreadable) else self._observed(file, data)

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
        """Porównanie z pamięcią (``_observed``). Plik pary, którego drugiego pliku system nie daje teraz czytać, czeka z
        werdyktem bez wiersza i bez pamięci (``_pair_waits``), więc odczyt z czytelnym drugim plikiem da jeden wiersz."""

        parsed = self._checked(file, data, file.parse(data))
        remembered = self._memory.read(file.name)
        if isinstance(parsed, Unreadable):
            return _pair_waits(file, parsed, remembered.good if isinstance(remembered, Remembered) else None)
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
    SETTLEMENT_MAIL.name: SETTLEMENT_MAIL,
    AUTOSTART.name: AUTOSTART,
    DEVICES.name: DEVICES,
    RULES.name: RULES,
    EXCEPTIONS.name: EXCEPTIONS,
    LEGEND.name: LEGEND,
}
"""Pliki, których wiersze Historii da się cofnąć: każdy plik bez sekretu. Każdy plik ma własny typ wartości (stąd
``Any``), a właściciel oddaje wartość tylko temu plikowi, z którego ją wziął."""
_FILES: Final[Mapping[str, SettingsFile[Any]]] = {**_UNDOABLE, INBOX.name: INBOX}
"""Każdy plik właściciela; ``history`` porównuje z pamięcią każdy z nich."""
_SECTION: Final = re.compile(r"[.\[]")
"""Sekcja klucza Historii to jego początek do kropki (``foldery.rejestr_zlecen``) albo nawiasu (``wykonawcy[login]``)."""


def read_snapshot(config: Path) -> SettingsSnapshot:
    """Migawka bez zapisu dla prób skrzynki i Przypomnień (``tools/proba_*``): plik, przy złej treści ostatnia dobra z
    pamięci właściciela, a Foldery, Przypomnienia o raporcie i Legenda czynności przy pliku bez odczytu
    ``Unreadable``, jak w migawce Centrum; nie dopisuje Historii ani pamięci."""

    remembered_devices = Memory(config, lambda _: None).read(DEVICES.name)
    devices_data = settings_bytes(config / DEVICES.name)
    rules = _read_only(config, RULES, {RULES.name: lambda value: _rules_problem(value, devices_data, remembered_devices)})
    release = settings_bytes(config / RULES.name) is None
    devices = _read_only(
        config,
        DEVICES,
        {DEVICES.name: lambda value: devices_problem(value, rules, _last_good_devices(remembered_devices), release=release)},
    )
    folders = _or_unreadable(_read_only_view(config, FOLDERS), FOLDERS)
    reminders = _or_unreadable(_read_only_view(config, REMINDERS), REMINDERS)
    codes = _or_unreadable(_read_only_view(config, LEGEND), LEGEND)
    mail = _counted(_read_only_view(config, SETTLEMENT_MAIL), SETTLEMENT_MAIL)
    return SettingsSnapshot(
        folders_or_unreadable=folders,
        workers=WorkerListRead(_read_only_view(config, WORKERS)),
        inbox=inbox.state(_read_only_view(config, INBOX)),
        reminders_or_unreadable=reminders,
        quantity_rules_or_unreadable=quantity_rules(rules, devices),
        activity_legend_or_unreadable=codes if isinstance(codes, Unreadable) else activity_legend(codes),
        settlement_mail_or_unreadable=mail,
    )


def _read_only(config: Path, file: SettingsFile[T], together: Mapping[str, _PairCheck] | None = None) -> T:
    return _or_release(_read_only_view(config, file, together), file)


def _read_only_view(
    config: Path, file: SettingsFile[T], together: Mapping[str, _PairCheck] | None = None
) -> Read[T] | Unreadable:
    """Wartość pliku bez porównania z pamięcią: zła treść z ostatnią dobrą z pamięci właściciela, gdy ją ma;
    ``together``: sprawdzenia pary z plików w ``config`` i pamięci (``_paired``)."""

    data = settings_bytes(config / file.name)
    if isinstance(data, OSError):
        return Unreadable(file.name)
    parsed = _paired(file, data, file.parse(data), together or {})
    if not isinstance(parsed, FieldProblem | Unreadable):
        return Good(parsed)
    remembered = Memory(config, lambda _: None).read(file.name)
    good = remembered.good if isinstance(remembered, Remembered) else None
    if isinstance(parsed, Unreadable):
        return _pair_waits(file, parsed, good)
    return _with_secret_value(file, Bad(parsed, None if good is None else _good_value(good, file)), data)


def _paired(
    file: SettingsFile[T], data: bytes | None, parsed: T | FieldProblem, together: Mapping[str, _PairCheck]
) -> T | FieldProblem | Unreadable:
    """Wartość pliku w stanie ``data`` z niezmiennikiem pary Reguł ilości i Listy Urządzeń (``together``) dla
    właściciela i ``read_snapshot``; inne pliki mają tylko swój ``parse``. Reguły ilości z Wydania (brak pliku reguł)
    pasować nie muszą: pasować musi do nich lista taty. ``Unreadable``: drugiego pliku system nie daje teraz
    czytać, więc nie wiadomo, czy para pasuje."""

    if data is None and file.name == RULES.name:
        return parsed
    check = together.get(file.name)
    problem = None if check is None or isinstance(parsed, FieldProblem) else check(parsed)
    return parsed if problem is None else problem


def _pair_waits(file: SettingsFile[T], partner: Unreadable, good: bytes | None) -> Bad[T]:
    """Plik pary, którego drugiego pliku ``partner`` system nie daje teraz czytać: zdanie o tym pliku i ostatnia dobra
    wartość z pamięci (``good``), bo nie wiadomo, czy nowa treść pasuje do pliku taty."""

    return Bad(FieldProblem(None, messages.unreadable(partner.name)), None if good is None else _good_value(good, file))


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
) -> FieldProblem | Unreadable | None:
    """Reguły z bieżącą Listą Urządzeń (stan ``devices``) albo z jej ostatnią dobrą wartością z pamięci; listy, której
    system nie daje czytać, nikt nie zna (``Unreadable``), a procesy wtedy nie liczą."""

    if isinstance(devices, OSError):
        return Unreadable(DEVICES.name)
    now = DEVICES.parse(devices)
    return rules_problem(rules, None if isinstance(now, FieldProblem) else now, _last_good_devices(remembered))


def _last_good_devices(remembered: Remembered | None | Unreadable) -> tuple[Component, ...]:
    """Ostatnia dobra Lista Urządzeń z pamięci właściciela, którą procesy liczą przy złej liście; bez niej, także gdy
    jej treści ``parse`` dziś nie przyjmuje, lista z Wydania."""

    good = _good_value(remembered.good if isinstance(remembered, Remembered) else None, DEVICES)
    return DEVICES.default if good is None else good


def _good_value(good: bytes | None, file: SettingsFile[T]) -> T | None:
    """Wartość ostatniej dobrej treści z pamięci (``None``: brak pliku, czyli wartości domyślne pliku); treść, której
    ``parse`` dziś nie przyjmuje, to ``None``: ostatniej dobrej wartości taty już nie ma, a treść z Wydania nie jest
    jego wartością."""

    parsed = file.parse(good)
    return None if isinstance(parsed, FieldProblem) else parsed


def _problem(observed: Read[T] | Unreadable, file: SettingsFile[T], unreadable: Callable[[str], str]) -> FieldProblem | None:
    """Problem pliku dla okna Ustawień; ``unreadable`` daje zdanie pliku, którego system nie daje teraz czytać: odmowa
    procesów (``messages.unreadable``) albo treść z Wydania (``messages.unavailable``)."""

    match observed:
        case Good():
            return None
        case Bad(problem=problem):
            return problem
        case Unreadable():
            return FieldProblem(None, unreadable(file.name))


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


def _usable(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T | Unreadable:
    """Wartość, którą liczy Centrum (``_value``); pliku, którego system nie daje teraz czytać, nikt nie zna, więc zostaje
    ``Unreadable``, a nie wartości domyślne, które tata wziąłby za niewskazane ustawienie."""

    match observed:
        case Good() | Bad():
            return _value(observed, file)
        case Unreadable():
            return observed


def _value(read: Read[T], file: SettingsFile[T]) -> T:
    """Dobra wartość, a przy złej treści ostatnia dobra albo domyślna."""

    match read:
        case Good(value=value):
            return value
        case Bad(usable=usable):
            return file.default if usable is None else usable


def _or_unreadable(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T | Unreadable:
    """Wartość dla migawki procesu (``_value``), a plik, którego system nie daje teraz czytać, ``Unreadable`` z jego
    nazwą."""

    return observed if isinstance(observed, Unreadable) else _value(observed, file)


def _counted(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T | Unreadable | FieldProblem:
    """Wartość taty dla migawki procesu: dobra albo ostatnia dobra; złe ustawienie bez niej to jego problem, a nie
    wartości domyślne, a plik, którego system nie daje teraz czytać, ``Unreadable`` z jego nazwą."""

    match observed:
        case Unreadable():
            return observed
        case Good(value=value):
            return value
        case Bad(problem=problem, usable=value):
            return problem if value is None else value


def _shown_mail(mail: SettlementMailSettings) -> WrittenMail:
    return WrittenMail(mail.subject, mail.text)


def _or_release(observed: Read[T] | Unreadable, file: SettingsFile[T]) -> T:
    """Wartość, którą liczą procesy (``_value``): plik, którego system nie daje teraz czytać, ma treść z Wydania, jak mówi
    jego zdanie w oknie Ustawień (``messages.unavailable``)."""

    return file.default if isinstance(observed, Unreadable) else _value(observed, file)


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
