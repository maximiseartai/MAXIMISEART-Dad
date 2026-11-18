"""Ustawienia ze startu: Ustawienia Centrum, którymi liczy jedno Uruchomienie procesu, z chwili jego startu (ADR 0032).

Uruchomienie niesie je jedną wartością (``SettingsAtStart``) od startu (``process_kind.Start``) przez Uruchomienie
gotowe do startu (``PreparedRun``) do zakończonego (``runs.EndedRun``). Proces mówi, którymi z nich liczy, potrzebą
w ``ProcessKind.needs`` (``SettingNeed``), a nie osobną flagą na każde Ustawienie. Nazwa potrzeby to nazwa pola
``SettingsAtStart`` i pola ``SettingsSnapshot``, więc sprawdzenie startu w ``Catalog.prepared``
(``SettingsAtStart.missing``), rzut na proces (``SettingsAtStart.for_process``) i odmowa startu przy pliku bez odczytu
(``unreadable``) to po jednej pętli po ``SettingNeed``.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, replace
from typing import Any, Final, Literal, TypedDict, assert_never, get_args

from rozliczenia.activity_legend import ActivityLegend
from rozliczenia.centrum import diagnosis_messages, refusal
from rozliczenia.centrum.refusal import Refusal
from rozliczenia.centrum.run_logs import LoggedActivityLegend, LoggedQuantityRules
from rozliczenia.centrum.settings.files import Bad, Read, Unreadable, usable
from rozliczenia.centrum.settings.owner import SettingsSnapshot, UnreadableFile
from rozliczenia.message import Message
from rozliczenia.quantity_engine import QuantityRules
from rozliczenia.worker_list import WorkerList

SettingNeed = Literal["workers", "quantity_rules", "activity_legend"]
"""Ustawienie ze startu, którym liczy proces: część języka potrzeb (``process_kind.Need``). Kolejność to kolejność
błędów gospodarza i odmów startu."""

_SETTING_NEEDS: Final[tuple[SettingNeed, ...]] = get_args(SettingNeed)


class LoggedSettings(TypedDict):
    """Pola Logów Uruchomienia (``RunLog``) z Ustawień ze startu; mypy sprawdza je z polami ``RunLog`` w ``logs_of``."""

    quantity_rules: LoggedQuantityRules | None
    activity_legend: LoggedActivityLegend | None


@dataclass(frozen=True, kw_only=True)
class SettingsAtStart:
    """Ustawienia ze startu jednego Uruchomienia: skąd bierze je każdy gospodarz i co z nich trafia do wejścia i do Logów.

    ``snapshot``: migawka Ustawień Centrum z chwili startu, z której Logi Uruchomienia biorą pliki procesu, a Diagnoza
    Zatrzymania pliki i Listę Wykonawców. ``workers``: Lista Wykonawców, ``quantity_rules``: Reguły ilości,
    ``activity_legend``: Legenda czynności. ``warnings``: ostrzeżenia startu na kartę i do Logów. Żadne pole nie ma
    wartości domyślnej, więc każdy gospodarz mówi, skąd je ma:

    - Centrum (``process_kind.start_from_settings``) buduje je z migawki Ustawień Centrum (``of_snapshot``): Lista
      Wykonawców dobra, a przy złym pliku ostatnia dobra z ostrzeżeniem startu (``Refusal``, gdy ostatniej dobrej nie
      ma albo pliku nie da się teraz przeczytać); Reguły ilości albo Legenda czynności z pliku bez odczytu to ``None``.
    - Skrypt dla maszyn (``tools/uruchom_proces.py``) bierze Reguły ilości i Legendę czynności z Wydania, a Listę
      Wykonawców z pliku ``--wykonawcy``, bez migawki i bez ostrzeżeń (``uruchom_proces.ustawienia_z_wydania``, z której
      biorą je też wyrocznia ``verify-jedno-uruchomienie-naraz`` i testy).
    - Odtworzenie (``tools/lib/odtworzenie.py``) bierze Reguły ilości, Legendę czynności i ostrzeżenia startu z Logów
      Uruchomienia, a Reguły ilości i Legendę czynności z Wydania tylko dla Logów sprzed ich zapisu, bez migawki. Logi
      nie mają Listy Wykonawców: odtworzenie Wpisania raportów składa ją z loginów Wpisów w Logach, a Przygotowania
      i Przebiegu rozliczeń bierze plik ``wykonawcy.yaml`` folderu Konfiguracji.

    ``Catalog.prepared`` odrzuca start bez Ustawienia, którym proces liczy (``missing``), a te, którymi nie liczy,
    rzutuje na ``None`` (``for_process``), zanim zbuduje wejście procesu, więc wejście i ``PreparedRun`` mają tylko
    Ustawienia procesu. Do Logów idą z nich pliki procesu z migawki, Reguły ilości, Legenda czynności (``logged``)
    i ostrzeżenia startu; samej Listy Wykonawców nie mają Logi żadnego procesu.
    """

    snapshot: SettingsSnapshot | None
    workers: WorkerList | None
    quantity_rules: QuantityRules | None
    activity_legend: ActivityLegend | None
    warnings: tuple[Message, ...]

    @classmethod
    def of_snapshot(cls, snapshot: SettingsSnapshot, needs: Collection[str]) -> SettingsAtStart:
        """Ustawienia ze startu procesu o potrzebach ``needs`` z migawki Ustawień Centrum ``snapshot``: Lista
        Wykonawców tylko procesu, który jej potrzebuje, bo tylko jego start odmawia bez niej; reszta jak w opisie
        klasy."""

        rules, legend = snapshot.quantity_rules_or_unreadable, snapshot.activity_legend_or_unreadable
        return cls(
            snapshot=snapshot,
            workers=_workers_at_start(snapshot.workers) if "workers" in needs else None,
            quantity_rules=None if isinstance(rules, UnreadableFile) else rules,
            activity_legend=None if isinstance(legend, UnreadableFile) else legend,
            warnings=_start_warnings(snapshot, needs),
        )

    def missing(self, needs: Collection[str]) -> str | None:
        """Zdanie błędu gospodarza o pierwszym Ustawieniu ze startu, którym liczy proces o potrzebach ``needs``,
        a którego te Ustawienia nie mają; ``None``: mają wszystkie."""

        for need in _SETTING_NEEDS:
            if need in needs and getattr(self, need) is None:
                return _missing(need)
        return None

    def for_process(self, needs: Collection[str]) -> SettingsAtStart:
        """Te Ustawienia z ``None`` w miejscu każdego, którym proces o potrzebach ``needs`` nie liczy."""

        unused: dict[str, Any] = {need: None for need in _SETTING_NEEDS if need not in needs}
        return replace(self, **unused)

    def logged(self) -> LoggedSettings:
        """Pola Logów Uruchomienia z tych Ustawień; ostrzeżenia startu idą do Komunikatów Logów."""

        rules, legend = self.quantity_rules, self.activity_legend
        return LoggedSettings(
            quantity_rules=None if rules is None else LoggedQuantityRules.of(rules),
            activity_legend=None if legend is None else LoggedActivityLegend.of(legend),
        )

    def counted_rules(self) -> QuantityRules:
        assert self.quantity_rules is not None, "Catalog.prepared sprawdza Reguły ilości procesu, który nimi liczy"
        return self.quantity_rules

    def counted_legend(self) -> ActivityLegend:
        assert self.activity_legend is not None, "Catalog.prepared sprawdza Legendę czynności procesu, który nią liczy"
        return self.activity_legend

    def worker_list(self) -> WorkerList:
        assert self.workers is not None, "Catalog.prepared sprawdza potrzebę workers"
        return self.workers


def unreadable(snapshot: SettingsSnapshot, needs: Collection[str]) -> Refusal | None:
    """Odmowa startu procesu o potrzebach ``needs``: plik Reguł ilości albo Legendy czynności, którym proces liczy,
    a którego system nie daje teraz czytać, w kolejności ``SettingNeed``; ``None``, gdy każdy da się czytać. Lista
    Wykonawców bez odczytu nie jest ``UnreadableFile``, więc tu nie odmawia nigdy: start bez niej odrzuca
    ``SettingsAtStart.of_snapshot``."""

    counted = (("quantity_rules", snapshot.quantity_rules_or_unreadable), ("activity_legend", snapshot.activity_legend_or_unreadable))
    for need, value in counted:
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


def _workers_at_start(workers: Read[WorkerList] | Unreadable) -> WorkerList:
    """Lista Wykonawców dla startu Uruchomienia z migawki Ustawień: dobra, a przy złym ustawieniu ostatnia dobra;
    ``Refusal``, gdy ostatniej dobrej nie ma albo pliku nie da się teraz przeczytać."""

    if isinstance(workers, Unreadable):
        raise refusal.workers_unusable(None)
    found = usable(workers)
    if found is None:
        raise refusal.workers_unusable(workers.problem if isinstance(workers, Bad) else None)
    return found


def _start_warnings(snapshot: SettingsSnapshot, needs: Collection[str]) -> tuple[Message, ...]:
    """Ostrzeżenia startu Uruchomienia procesu o potrzebach ``needs`` z migawki Ustawień Centrum: proces z Listą
    Wykonawców biegnie na ostatniej dobrej liście, bo plik ma złe ustawienie."""

    workers = snapshot.workers
    if "workers" in needs and isinstance(workers, Bad) and workers.usable is not None:
        return (diagnosis_messages.worker_list_last_good(workers.problem.sentence),)
    return ()
