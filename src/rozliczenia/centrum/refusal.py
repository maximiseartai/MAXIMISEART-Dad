"""Odmowy żądań API Centrum rozliczeń: kod HTTP i zdanie dla taty, które ``create_app`` oddaje jako ``Problem``.

Katalog odmów: każda odmowa Centrum powstaje z fabryki tego modułu, a każda fabryka ma próbkę w
``tests/expected/komunikaty.txt`` (``tests/test_komunikaty_expect.py``), więc zmiana zdania odmowy zmienia ten plik.
Moduł nie wczytuje FastAPI, bo odmawiają też reguły Centrum spoza tras, także katalog procesów
(``tests/test_granice_importow.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal, assert_never, final

from rozliczenia.centrum.contract.common import Problem
from rozliczenia.centrum.settings.files import FieldProblem, RemovedWhat
from rozliczenia.message import explorer_check, refer_if
from rozliczenia.period_folder import PeriodFolderLookupError, PeriodPlace, month_folder_label, period_place_label
from rozliczenia.worker_periods import InPeriod, InRegister, Unchecked


@final
class _Catalog:
    """Typ dowodu, że odmowa powstała w tym katalogu (``_CATALOG``)."""

    __slots__ = ()


_CATALOG: Final = _Catalog()
"""Dowód katalogu odmów: ``Refusal`` bez niego to błąd mypy, a poza tym modułem dowód, ``_Catalog`` i ``_refused``, która
sama wkłada dowód, odrzuca ruff (``TID251``). Odwołanie do ``Refusal`` poza typem łapie
``tests/test_komunikaty_expect.py``, a jego próbki ``ZNANE_LUKI`` pokazują klasy postaci, które przepuszczają wszystkie
te mechanizmy."""


@final
class Refusal(Exception):
    """Serwer odmawia żądania; ``create_app`` zamienia odmowę na odpowiedź ``Problem``. Tworzy ją tylko fabryka tego
    katalogu (``_CATALOG``), a podklasę z własnym konstruktorem bez dowodu odrzuca mypy (``final``)."""

    def __init__(self, status_code: int, message: str, proof: _Catalog, field: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.field = field


def _refused(status_code: int, message: str, field: str | None = None) -> Refusal:
    """Odmowa z dowodem katalogu dla fabryk tego modułu. Poza nim ruff (``TID251``) odrzuca ją jak ``_CATALOG``, bo
    wkłada dowód za wywołującego, więc dałaby odmowę bez fabryki i bez próbki w ``tests/expected/komunikaty.txt``."""

    return Refusal(status_code, message, _CATALOG, field)


# Odmowy akcji na zasobie w OpenAPI: brak zasobu (404) albo zły stan (409), obie jako ``Problem``.
NOT_FOUND_OR_CONFLICT: dict[int | str, dict[str, object]] = {404: {"model": Problem}, 409: {"model": Problem}}

Retry = Literal["start", "update", "restore", "shutdown"]
"""Co tata zrobi, gdy skończy się to, co trwa: uruchomi proces, zaktualizuje narzędzie, przywróci Kopię INTERMAX
jeszcze raz albo zamknie Centrum rozliczeń."""


def _retry(then: Retry) -> str:
    match then:
        case "start":
            return "uruchom proces"
        case "update":
            return "zaktualizuj narzędzie"
        case "restore":
            return "przywróć kopię jeszcze raz"
        case "shutdown":
            return "zamknij Centrum rozliczeń"
        case _:
            assert_never(then)


def not_local_address() -> Refusal:
    return _refused(403, "Centrum rozliczeń odpowiada tylko na adres tego komputera.")


def not_from_centrum_card() -> Refusal:
    return _refused(403, "Tę akcję można wykonać tylko z karty Centrum rozliczeń.")


def unexpected_failure() -> Refusal:
    return _refused(500, "W Centrum rozliczeń wystąpił nieoczekiwany błąd. Odśwież kartę i spróbuj ponownie.")


def period_folder_unreadable(folder: str) -> Refusal:
    """Folderu ``folder`` (nazwa) nie da się odczytać, np. brak dostępu albo OneDrive nie działa."""

    return _refused(500, f"Nie udało się odczytać folderu {folder}. {explorer_check('folder', 'odśwież kartę')}")


def first_choose(settings: Sequence[str]) -> Refusal:
    return _refused(409, f"Najpierw wskaż {' i '.join(settings)}.")


def register_not_chosen() -> Refusal:
    return _refused(409, "Najpierw wybierz Rejestr zleceń w Ustawieniach.")


def register_unavailable(register: str) -> Refusal:
    """System nie odpowiada o Rejestrze zleceń ``register`` (nazwa pliku), np. OneDrive nie działa."""

    return _refused(
        409,
        f"Rejestr zleceń {register} jest teraz niedostępny. {explorer_check('jego folder', 'spróbuj ponownie')}",
    )


def register_missing(register: str) -> Refusal:
    return _refused(404, f"Nie ma Rejestru zleceń {register}. Wybierz właściwy plik w Ustawieniach.")


def settings_not_saved() -> Refusal:
    return _refused(
        500,
        "Nie udało się zapisać Ustawień Centrum w folderze config. "
        + explorer_check("folder", "spróbuj ponownie", read_only=True),
    )


def setting_refused(problem: FieldProblem) -> Refusal:
    """Zła wartość Ustawień Centrum: nic się nie zapisało, a odmowa niesie pole i zdanie, co poprawić."""

    return _refused(422, problem.sentence, problem.place)


def workers_unusable(problem: FieldProblem | None) -> Refusal:
    """Proces nie startuje bez Listy Wykonawców: plik ma złe ustawienie i nie ma ostatniej dobrej listy (``problem``,
    którego zdanie mówi też, kto poprawia plik albo na co czeka przeniesienie) albo system nie daje go teraz czytać
    (``None``)."""

    if problem is None:
        return _refused(
            409, "Nie można teraz odczytać Listy Wykonawców. Zamknij program, który może trzymać plik, i spróbuj ponownie."
        )
    return _refused(
        409, f"Lista Wykonawców ma złe ustawienie: {problem.sentence} Szczegóły są w Ustawieniach, w sekcji Wykonawcy.", problem.place
    )


def worker_kept(presence: InRegister | InPeriod | Unchecked, what: RemovedWhat) -> Refusal:
    """Wykonawcy albo loginu nie da się usunąć (formularzem, „Usuń Wykonawcę” ani „Cofnij”): login ma zlecenia w okresie
    (Rejestr zleceń, Plik zbiorczy) albo nie da się tego teraz sprawdzić. Odmowa proponuje Nieaktywnego Wykonawcę, który
    zostaje na liście (ADR 0032)."""

    who = "Wykonawca" if what == "worker" else "Ten login"
    asked = "Wykonawca" if what == "worker" else "ten login"
    stays = "zostaje na Liście Wykonawców" if what == "worker" else "zostaje przy Wykonawcy"
    inactive = "Gdy Wykonawca już nie pracuje, oznacz go jako nieaktywnego: nie dostanie przypomnień, a jego okresy dalej się rozliczą."
    match presence:
        case InRegister():
            found = f"{who} ma zlecenia w Rejestrze zleceń, więc {stays}."
        case InPeriod(token=token):
            found = f"{who} ma zlecenia w okresie {token}, więc {stays}."
        case Unchecked(place="not_set"):
            found = f"Nie wiadomo, czy {asked} ma zlecenia w okresach: najpierw wskaż Rejestr zleceń i folder okresów."
        case Unchecked(place="register"):
            found = f"Nie da się teraz przeczytać Rejestru zleceń, więc nie wiadomo, czy {asked} ma w nim zlecenia."
        case Unchecked(place="periods_directory"):
            found = f"Nie da się teraz odczytać folderu okresów, więc nie wiadomo, czy {asked} ma zlecenia w okresach."
        case Unchecked(token=token):
            found = (
                f"Nie da się teraz przeczytać Pliku zbiorczego okresu {token}, więc nie wiadomo, czy {asked} ma w "
                "nim zlecenia."
            )
    return _refused(409, f"{found} {inactive}")


def report_entering_without_addresses() -> Refusal:
    """Wpisanie raportów nie startuje, gdy żaden Wykonawca z Listy Wykonawców nie ma adresu: żaden mail nie byłby
    Raportem wykonawcy."""

    return _refused(409, "Na Liście Wykonawców nikt nie ma jeszcze adresu. Dopisz adresy Wykonawców w Ustawieniach.")


def settings_change_unknown() -> Refusal:
    return _refused(404, "Tej zmiany nie ma w Historii Ustawień. Odśwież okno Ustawień.")


def quantity_rule_unknown() -> Refusal:
    """Reguły ilości o tym id nie ma już w regułach, którymi liczy Centrum (np. cofnięta w Historii w innym oknie)."""

    return _refused(404, "Tej reguły już nie ma w Regułach ilości. Odśwież okno Ustawień.")


def device_component_unknown() -> Refusal:
    """Składnika o tym id nie ma już na Liście Urządzeń, którą liczy Centrum (np. cofnięty w Historii w innym oknie)."""

    return _refused(404, "Tego składnika już nie ma na Liście Urządzeń. Odśwież okno Ustawień.")


def quantity_difference_unknown() -> Refusal:
    """Różnicy z Kontroli ilości o tym id nie ma już na liście „Tu wpisałeś inaczej niż reguła” (np. tata poprawił Plik
    zbiorczy albo regułę), więc nie ma czego oznaczyć jako wyjątek."""

    return _refused(404, "Tej różnicy już nie ma na liście. Odśwież okno Ustawień.")


def settings_change_not_undoable() -> Refusal:
    """Wiersz Historii Ustawień bez „Cofnij”: zmiana sekretu albo zła treść spoza Centrum, której Centrum nie przyjęło."""

    return _refused(404, "Tej zmiany nie da się cofnąć.")


def settings_history_unreadable() -> Refusal:
    """Plik Historii Ustawień jest, ale system nie daje go teraz czytać (np. trzyma go OneDrive)."""

    return _refused(500, "Nie udało się odczytać Historii Ustawień. Odśwież okno Ustawień za chwilę.")


def autostart_not_changed() -> Refusal:
    """Skrótu Centrum w folderze Autostart nie dało się założyć ani usunąć albo zmiany nie dało się zapisać w Historii
    Ustawień; skrót zostaje w stanie sprzed przełączenia."""

    return _refused(
        500,
        "Nie udało się zmienić startu Centrum razem z Windows. Spróbuj ponownie. "
        + refer_if("Jeśli komunikat wraca", request="przekaż go"),
    )


def unknown_period() -> Refusal:
    return _refused(404, "Nie ma takiego okresu.")


def period_folder_lookup(error: PeriodFolderLookupError) -> Refusal:
    token = error.period.token
    if not error.locations:
        return _refused(
            404, f"Nie ma folderu {token} w żadnym folderze miesiąca. Załóż go w folderze INEA właściwego miesiąca."
        )
    months = ", ".join(month_folder_label(error.periods_directory, location) for location in error.locations)
    return _refused(409, f"Folder {token} jest w więcej niż jednym folderze miesiąca ({months}). Zostaw go tylko w jednym.")


def place_missing(place: PeriodPlace, period: str) -> Refusal:
    named = "Folder okresu" if place == "period_folder" else f"{period_place_label(place)} okresu"
    return _refused(404, f"{named} {period} jeszcze nie istnieje.")


def worker_settlement_missing(worker: str, period: str) -> Refusal:
    return _refused(404, f"Rozliczenia pracownika {worker} nie ma w okresie {period}.")


def no_forwarding(process: str) -> Refusal:
    """Proces o tytule ``process`` nie ma trybu Wyceny z Przekazaniem do akceptacji."""

    return _refused(409, f"{process} nie ma trybu z Przekazaniem do akceptacji.")


def pricing_without_preview() -> Refusal:
    return _refused(
        409,
        "Wycena w efenix nie ma podglądu bez zapisu. "
        "Uruchom ją przyciskiem „Uzupełnij bez zapisu” albo „Uzupełnij i zapisz”.",
    )


def closing(then: Retry) -> Refusal:
    """Zamknięcie Centrum przyjęte: wątek, który teraz by wystartował, zginąłby z końcem serwera."""

    return _refused(409, f"Centrum rozliczeń się zamyka. Kliknij skrót „Centrum rozliczeń” na pulpicie, potem {_retry(then)}.")


def updating(then: Retry) -> Refusal:
    return _refused(409, f"Trwa aktualizacja narzędzia. Poczekaj na jej wynik, potem {_retry(then)}.")


def restoring(then: Retry) -> Refusal:
    return _refused(409, f"Trwa przywracanie Kopii INTERMAX. Poczekaj na jego wynik, potem {_retry(then)}.")


def running(process: str, period: str, then: Retry) -> Refusal:
    """Trwa Uruchomienie procesu o tytule ``process`` dla okresu ``period``."""

    return _refused(
        409,
        f"Trwa Uruchomienie procesu: {process}, okres {period}. "
        f"Poczekaj na jego wynik w Uruchomieniach, potem {_retry(then)}.",
    )


def update_in_progress() -> Refusal:
    return _refused(409, "Trwa już aktualizacja narzędzia. Poczekaj na jej wynik.")


def update_without_port() -> Refusal:
    """Serwer nie podał portu tego Centrum, a na nim opiekun ponownego startu uruchamia nową wersję."""

    return _refused(
        500,
        "Centrum rozliczeń nie zna swojego portu, więc nie zaktualizuje narzędzia. "
        "Zamknij Centrum rozliczeń i kliknij skrót „Centrum rozliczeń” na pulpicie.",
    )


def run_in_progress(process: str, period: str) -> Refusal:
    """Drugi start, gdy trwa Uruchomienie procesu o tytule ``process`` dla okresu ``period``."""

    return _refused(
        409, f"Trwa już Uruchomienie procesu: {process}, okres {period}. Poczekaj na jego wynik w Uruchomieniach."
    )


def unknown_run() -> Refusal:
    return _refused(404, "Nie ma takiego Uruchomienia procesu.")


def not_awaiting_decision() -> Refusal:
    return _refused(409, "To Uruchomienie procesu nie czeka na decyzję.")


def no_diagnosis() -> Refusal:
    return _refused(409, "Diagnoza jest przy Zatrzymaniu do Maksa albo przy powtórce tego samego Komunikatu.")


def no_report_draft() -> Refusal:
    return _refused(409, "Zgłoszenie powstaje z Diagnozy. Najpierw kliknij „Diagnoza”.")


def no_failed_update() -> Refusal:
    return _refused(409, "Zgłoszenie powstaje po nieudanej aktualizacji narzędzia.")


def metrics_unreadable() -> Refusal:
    return _refused(500, "Nie udało się odczytać plików metryk. Odśwież kartę.")


def history_unreadable() -> Refusal:
    """Uwaga taty: historii Uruchomień nie da się odczytać."""

    return _refused(500, "Nie udało się odczytać historii Uruchomień. Odśwież kartę albo wyślij Uwagę ogólną.")


def run_not_in_history() -> Refusal:
    """Uwaga taty do Uruchomienia, którego nie ma już w historii."""

    return _refused(
        404,
        "Tego Uruchomienia nie ma już w historii Centrum rozliczeń. Wybierz inne Uruchomienie albo wyślij Uwagę ogólną.",
    )


def note_not_queued() -> Refusal:
    return _refused(500, "Uwaga się nie zapisała i nie pójdzie do Maksa. Spróbuj wysłać ją jeszcze raz.")


ReportEnteringFile = Literal["inbox_access"]
"""Plik w ``config``, który prowadzi Maks, bez którego Wpisanie raportów nie startuje: dostęp do skrzynki raportów
(``skrzynka-raportow.txt``)."""


def _report_entering_file(missing: ReportEnteringFile) -> str:
    match missing:
        case "inbox_access":
            return "hasła do skrzynki raportów (plik skrzynka-raportow.txt)"
        case _:
            assert_never(missing)


def report_entering_not_set_up(missing: Sequence[ReportEnteringFile]) -> Refusal:
    """Wpisanie raportów nie startuje bez plików ``missing`` w ``config``; dopisać je może tylko Maks (spec #1224, US 51)."""

    files = " i ".join(_report_entering_file(file) for file in missing)
    return _refused(
        409,
        f"Wpisanie raportów nie jest jeszcze ustawione: w folderze config brakuje {files}. Dopisze je Maks.",
    )


def reports_unreadable() -> Refusal:
    """Widok Raporty: pliku wyniku albo decyzji „Zostaw moją” w ``config`` nie da się odczytać, a zapis decyzji bez
    dawnych przywróciłby ich różnice."""

    return _refused(
        500,
        "Nie udało się odczytać wyniku Wpisania raportów ani decyzji „Zostaw moją”. Odśwież kartę, a gdy to się "
        "powtarza, wyślij Uwagę ogólną.",
    )


def difference_gone() -> Refusal:
    """„Zostaw moją” przy różnicy, której nie ma w wyniku ostatniego kliknięcia (np. widok z kliknięcia sprzed innego)."""

    return _refused(404, "Tej różnicy nie ma w ostatnim Wpisaniu raportów. Odśwież widok Raporty.")
