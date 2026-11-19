"""Stan procesu workera, który test zostawił następnemu testowi w tym samym workerze (#1923, #1783).

Pod xdist testy jednego workera dzielą proces, więc to, co test zostawi w procesie, działa potem w oknie innego testu:
plik w śmieciach zamyka finalizer ``gc``, a jego ``ResourceWarning`` wywraca sąsiada, który łapie ostrzeżenia (#1923), a
wątek zegara śpi w podmianie snu sąsiada (#1783). Który test jest sąsiadem, zmienia każdy nowy podział plików na zadania
CI, więc plugin (``pytest_plugins`` w ``tests/conftest.py``) nie czeka na sąsiada: porównuje stan procesu po pełnym
teardownie testu ze stanem sprzed jego setupu, a test, po którym się różni, kończy się błędem z tym, co zostawił.

Stan to to, co proces trzyma poza stertą Pythona, czyli to, czym działa dalej bez kodu testu:

- deskryptory każdego rodzaju (plik, gniazdo, potok, plik biblioteki C), także te, które zamknąłby dopiero ``gc``;
- wątki z linii testu (``tests/fixtures/linie_watkow.py``), które żyją jeszcze ``WATEK_S`` po teardownie;
- procesy potomne, które żyją jeszcze ``POTOMEK_S`` po teardownie;
- katalog roboczy i zmienne środowiska.

Stan oczekiwany po pełnym teardownie testu daje księga okresu (``_Oczekiwany``). Każda granica, którą pytest daje
pluginowi (wejście i wyjście setupu fixtury zasięgu modułu, klasy, pakietu albo sesji, koniec takiej fixtury, koniec
teardownu testu), zamyka odcinek czasu, a odcinek należy do fixtury, której setup stoi wtedy na szczycie stosu setupów,
albo do testu, gdy stos jest pusty; setup, który biegnie w środku setupu innej fixtury (``request.getfixturevalue``), ma
więc własne odcinki, a nie odcinki tej innej. Stan oczekiwany to stan sprzed setupu testu z nałożonym w kolejności czasu
skutkiem odcinków fixtur (ich zasoby i wartości z końca odcinka) i końców fixtur (dla każdego klucza wartość sprzed
pierwszego odcinka fixtury, który go zmienił, i brak jej zasobów); odcinek testu, także ciało testu pod fixturą żywą od
wcześniejszego testu, i setup, który padł, mają skutek zero. Zasób to deskryptor, wątek albo proces potomny, a wartość
to katalog roboczy albo zmienna środowiska; oba rodzaje idą tą samą księgą. Różnica z końca fixtury ma w błędzie jej
nazwę, a sprawdzenie biegnie w teardownie testu, po którym się skończyła, albo w setupie następnego, gdy fixtura z
``params`` zmienia parametr. Każde sprawdzenie zaczyna nowy okres od stanu po sobie, więc zgłoszony stan nie wraca w
następnym. Plugin widzi stan tylko na granicach odcinków, więc zmiana cofnięta w jednym odcinku jest niewidoczna, a
przypisanie mówi, czyj był szczyt stosu, a nie który kod zmienił stan. Od końca ciała testu i od początku końca takiej
fixtury do sprawdzenia samoczynny ``gc`` stoi (``_hold_gc``), więc plik w śmieciach nie zamyka się w oknie innego testu
i nie znika przed sprawdzeniem. Zasób na całe życie procesu workera (``_ZASOBY_PROCESU``) startuje przed pierwszym
testem, więc jest w stanie sprzed każdego testu.

Po błędzie plugin przywraca każdą wartość do oczekiwanej, więc błąd ma sprawca, a nie każdy następny test workera.
Katalog roboczy, który box boat przeniósł w trakcie biegu (``box_boat.przeniesiony``), nie jest stanem testu: plugin
zgłasza go komunikatem ``box_boat.KOMUNIKAT`` i daje raportowi testu, po którym go zobaczył, własność
``box_boat.WLASNOSC``. Sesja, w której każdy raport, który padł (testu albo kolekcji), ma tę własność, kończy się kodem
``box_boat.KOD_WYJSCIA`` zamiast 1, a ``tools/szybko.py`` kończy się wtedy wynikiem ``SZYBKO INFRA``. Plugin ustawia ten
kod przed innymi ``pytest_sessionfinish``, więc porażka sesji spoza raportów (``DRZEWO REPO`` w ``tests/conftest.py``)
nadpisuje go z powrotem na 1.
Porównanie kosztuje listę deskryptorów i potomków, poniżej 0,5 ms na test; ``gc.collect()``, czekanie na wątki i
potomków oraz opis zasobów biegną tylko wtedy, gdy stan się różni.

Granica porównania to stan poza stertą: zmienna modułu, atrybut podmieniony bez ``monkeypatch``, pamięć podręczna,
``sys.modules``, filtry ostrzeżeń, a poza stertą maska ``umask`` i dyspozycje sygnałów zostają dla sąsiada niewidoczne
dla pluginu, tak jak zmiana stanu zasobu starszego od testu (zadanie w pętli fixtury sesji). Wątek, który uruchomił
wątek starszy od testu, nie należy do linii testu, a wątek i potomek, które kończą się w ciągu ``WATEK_S`` i
``POTOMEK_S``, nie wywracają testu; deskryptor, który wątek starszy od testu otworzył w trakcie testu i trzyma po nim,
liczy się do testu. Gniazdo na macOS nie ma numeru węzła, więc gniazdo zamknięte i otwarte znów pod tym samym numerem
deskryptora wygląda jak to samo. Na Windows nie ma taniej listy deskryptorów ani potomków procesu, więc tam plugin
porównuje tylko wątki, katalog roboczy i środowisko. Stan wspólny wszystkich workerów, czyli pliki w drzewie
repozytorium, porównuje sesja w ``tests/conftest.py`` (``tests/fixtures/drzewo_repo.py``), bo plik w drzewie mógł
zapisać każdy worker. Próbki granicy to ``ZNANE_LUKI`` w ``tests/test_stan_procesu.py``."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from contextlib import suppress
from dataclasses import dataclass, field
import ctypes
import gc
import io
import multiprocessing.forkserver
import multiprocessing.resource_tracker
import os
from pathlib import Path
import socket
import stat
import sys
import threading
import time
from typing import Final
import warnings

import pytest

import box_boat
import potomne
from tests.fixtures.linie_watkow import new_line, threads_since
from tests.fixtures.potomne import wait_for

WATEK_S: Final = 5.0
"""Tyle po teardownie plugin czeka na koniec wątków z linii testu: wątek, który kończy pracę zaraz po teście (kolejka
Zgłoszeń po przejściu), nie wywraca testu, a pętla bez końca (budzik zegara z #1783) tak."""
POTOMEK_S: Final = 5.0
"""Tyle po teardownie plugin czeka na koniec procesów potomnych testu."""
_STANDARD_STREAMS: Final = frozenset({0, 1, 2})
# Przechwytywanie pytest podmienia standardowe strumienie, a pytest ustawia tę zmienną na czas każdego testu.
_ZMIENNE_PYTEST: Final = frozenset({"PYTEST_CURRENT_TEST"})


def _uruchom_zasoby_procesu() -> None:
    """Zasoby, które biblioteka otwiera raz na proces przy pierwszym użyciu i trzyma do jego końca: bez startu przed
    pierwszym testem należałyby do testu, który pierwszy ich użył. Nowy taki zasób dopisz tutaj."""

    if sys.platform == "win32":  # tam plugin nie porównuje deskryptorów ani potomków
        return
    socket.getaddrinfo("localhost", None)  # macOS: połączenia resolvera systemu (mDNSResponder, netsrc)
    potomne.run([sys.executable, "-c", ""], cwd=Path.cwd(), timeout=60)  # strażnik drzew procesów narzędzi
    multiprocessing.resource_tracker.ensure_running()  # proces śledzący zasoby multiprocessing
    multiprocessing.forkserver.ensure_running()  # serwer startu procesów multiprocessing (domyślny od Pythona 3.14)


_ZASOBY_PROCESU: list[Callable[[], None]] = [_uruchom_zasoby_procesu]


@dataclass(frozen=True)
class _Deskryptor:
    numer: int
    rodzaj: str
    urzadzenie: int
    wezel: int


@dataclass(frozen=True)
class _Potomek:
    pid: int


_Zasob = _Deskryptor | _Potomek | threading.Thread
"""Zasób procesu: zostawiony, gdy jest po teście, a nie było go przed nim."""

_KATALOG: Final = ("katalog", "")
"""Klucz wartości katalogu roboczego; klucz zmiennej środowiska to ``("zmienna", nazwa)``."""
_Klucz = tuple[str, str]


@dataclass(frozen=True)
class Stan:
    """Stan procesu w jednej chwili: zasoby, które są, i wartości (katalog roboczy, zmienne środowiska) pod kluczami;
    ``linia`` to numer, od którego ``threads_since`` liczy wątki uruchomione potem."""

    zasoby: frozenset[_Zasob]
    wartosci: frozenset[tuple[_Klucz, str]]
    linia: int


@dataclass(frozen=True)
class _Fixture:
    name: str
    scope: str


@dataclass(frozen=True)
class _Odcinek:
    """Odcinek czasu między dwiema granicami pytest, w którym na szczycie stosu setupów stała fixtura ``fixture``."""

    fixture: _Fixture
    przed: Stan
    po: Stan

    def zasoby(self) -> frozenset[_Zasob]:
        """Nowe zasoby odcinka i wątki jego linii, także uruchomione później przez wątki, które ten odcinek uruchomił."""

        pozniejsze = set(threads_since(self.po.linia))
        watki = (thread for thread in threads_since(self.przed.linia) if thread not in pozniejsze)
        return (self.po.zasoby - self.przed.zasoby) | frozenset(watki)

    def klucze(self) -> frozenset[_Klucz]:
        return frozenset(klucz for klucz, _ in self.po.wartosci ^ self.przed.wartosci)


@dataclass
class _Wlasne:
    """Fixtura szerszego zasięgu i jej odcinki: setup bez odcinków fixtur, których setup biegł w jej środku."""

    fixture: _Fixture
    odcinki: list[_Odcinek] = field(default_factory=list)

    def zasoby(self) -> frozenset[_Zasob]:
        return frozenset().union(*(odcinek.zasoby() for odcinek in self.odcinki))

    def wartosci_sprzed(self) -> dict[_Klucz, str | None]:
        """Wartość każdego klucza, który fixtura zmieniła, sprzed jej pierwszego odcinka, który go zmienił."""

        sprzed: dict[_Klucz, str | None] = {}
        for odcinek in self.odcinki:
            wartosci = dict(odcinek.przed.wartosci)
            for klucz in odcinek.klucze() - sprzed.keys():
                sprzed[klucz] = wartosci.get(klucz)
        return sprzed


@dataclass
class _Ramka:
    """Setup fixtury szerszego zasięgu na stosie: początek jej bieżącego odcinka."""

    wlasne: _Wlasne
    start: Stan


@dataclass
class Zostawione:
    """Różnica stanu procesu: zasoby, które test albo fixtura zostawiły, i klucze z wartością inną niż oczekiwana."""

    zasoby: set[_Zasob] = field(default_factory=set)
    klucze: set[_Klucz] = field(default_factory=set)

    def __bool__(self) -> bool:
        return bool(self.zasoby or self.klucze)


# Stan procesu, bo pod xdist każdy worker ma własne testy i fixtury: stan na początku okresu (przed setupem testu albo
# po ostatnim sprawdzeniu), księga okresu w kolejności czasu (odcinek setupu fixtury szerszego zasięgu albo jej
# koniec), stos setupów fixtur szerszego zasięgu, żywe takie fixtury i stan samoczynnego gc sprzed jego wstrzymania.
_przed_testem: list[Stan] = []
_ksiega: list[_Odcinek | _Wlasne] = []
_stos: list[_Ramka] = []
_wlasne: dict[pytest.FixtureDef[object], _Wlasne] = {}
_held_gc_was_enabled: list[bool] = []


def _hold_gc() -> None:
    """Wstrzymuje samoczynny ``gc`` do najbliższego sprawdzenia: inaczej zebrałby puszczony plik przed nim."""

    if not _held_gc_was_enabled:
        _held_gc_was_enabled.append(gc.isenabled())
        gc.disable()


def _release_gc() -> None:
    # Test, który sam wyłączył gc, zostaje z wyłączonym.
    if _held_gc_was_enabled and _held_gc_was_enabled.pop():
        gc.enable()


# Raporty, które padły w procesie kontrolera sesji (pod xdist dostaje raporty workerów): ``True`` dla raportu testu,
# po którym plugin widział katalog repo przeniesiony przez box.
_porazki: list[bool] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.failed:
        _porazki.append(box_boat.WLASNOSC in dict(report.user_properties))


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.failed:
        _porazki.append(False)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> Generator[None, object, object]:
    """Sesja, której każda porażka to katalog repo przeniesiony przez box, kończy się ``box_boat.KOD_WYJSCIA``. Kod stoi
    przed innymi implementacjami haka, więc ta, która sama wywraca sesję, ustawia go z powrotem na 1."""

    controller = not hasattr(session.config, "workerinput")
    if controller and session.exitstatus == pytest.ExitCode.TESTS_FAILED and _porazki and all(_porazki):
        session.exitstatus = box_boat.KOD_WYJSCIA
    return (yield)


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    while _ZASOBY_PROCESU:
        _ZASOBY_PROCESU.pop()()
    _przed_testem[:] = [stan()]
    _ksiega.clear()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Generator[None, object, object]:
    try:
        return (yield)
    finally:
        _hold_gc()  # ramka testu puściła swoje obiekty; śmieci czekają na sprawdzenie po teardownie


@pytest.hookimpl(wrapper=True)
def pytest_fixture_setup(
    fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest
) -> Generator[None, object, object]:
    _granica()  # setup fixtury biegnie w środku setupu innej (request.getfixturevalue): jej odcinek się tu kończy
    if any(isinstance(wpis, _Wlasne) for wpis in _ksiega):
        # pytest skończył instancję fixtury z params w setupie następnego testu (FixtureDef.execute)
        try:
            _check("przed setupem tego testu")
        finally:
            _release_gc()
    if fixturedef.scope == "function":
        return (yield)
    ramka = _Ramka(_Wlasne(_Fixture(fixturedef.argname, fixturedef.scope)), stan())
    _stos.append(ramka)
    try:
        result = yield
    except BaseException:
        # Stan z setupu, który padł, należy do testu: fixtura nie ma końca, w którym by go zwróciła.
        _zamknij_odcinek(ramka, do_ksiegi=False)
        raise
    else:
        _zamknij_odcinek(ramka)
    finally:
        _stos.pop()
        if _stos:
            _stos[-1].start = stan()
    _wlasne[fixturedef] = ramka.wlasne
    # Finalizery biegną od ostatniego (LIFO), więc ten biegnie pierwszy w finish: gc stoi przez teardown fixtury i
    # puszczenie cached_result aż do sprawdzenia.
    fixturedef.addfinalizer(_hold_gc)
    return result


def _granica() -> None:
    """Granica setupu fixtury: najpierw kończy odcinek fixtury z wierzchu stosu, a dopiero potem plugin sprawdza stan
    (koniec fixtury z ``params``, który pytest robi tuż przed tym setupem) albo otwiera ramkę, więc każdy odcinek należy
    do jednej fixtury."""

    if _stos:
        _zamknij_odcinek(_stos[-1])


def _zamknij_odcinek(ramka: _Ramka, *, do_ksiegi: bool = True) -> None:
    """Kończy bieżący odcinek fixtury z ``ramka``: od początku odcinka do teraz stan zmieniała ona, bo jej setup stał
    na szczycie stosu."""

    teraz = stan()
    if do_ksiegi:
        odcinek = _Odcinek(ramka.wlasne.fixture, ramka.start, teraz)
        ramka.wlasne.odcinki.append(odcinek)
        _ksiega.append(odcinek)
    ramka.start = teraz


def pytest_fixture_post_finalizer(fixturedef: pytest.FixtureDef[object], request: pytest.FixtureRequest) -> None:
    if (wlasne := _wlasne.pop(fixturedef, None)) is not None:
        _ksiega.append(wlasne)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, object, object]:
    """Test, po którego pełnym teardownie proces ma inny stan niż przed jego setupem, kończy się błędem z tym, co
    zostawił, a zasób fixtury szerszego zasięgu także z jej nazwą: inaczej zasób działa w oknie innego testu."""

    _hold_gc()  # także po setupie, który padł przed ciałem testu
    try:
        result = yield
    except BaseException as error:
        # Teardown, który rzuca (także Skipped z pytest.skip, który testu nie czerwieni), też puszcza zasoby: sprawdzenie
        # biegnie przed powrotem gc, a błąd pluginu niesie pierwotny wyjątek jako przyczynę.
        try:
            _check_after(item)
        except AssertionError as found:
            raise found from error
        raise
    else:
        _check_after(item)
    finally:
        _release_gc()
    return result


class _KatalogPrzeniesiony(AssertionError):
    """Katalog roboczy procesu przeniesiony przez box boat (``box_boat.przeniesiony``), a nie zmieniony przez test."""


def _check_after(item: pytest.Item) -> None:
    if isinstance(item, pytest.Function):
        # Ostatnia referencja wartości fixtur; pytest puszcza ją dopiero po hakach teardown (runner.runtestprotocol).
        item.funcargs = {}
    try:
        _check("po tym teście")
    except _KatalogPrzeniesiony:
        # Raport teardown niesie własności testu do kontrolera sesji, także od workera xdist.
        item.user_properties.append((box_boat.WLASNOSC, box_boat.KATALOG_ZWOLNIONY))
        raise


def _check(kiedy: str) -> None:
    """Porównuje stan teraz ze stanem oczekiwanym z księgi okresu, a potem zaczyna nowy okres od stanu po sprawdzeniu,
    więc to, co sprawdzenie już zgłosiło, nie wraca w następnym."""

    przed = _przed_testem[0] if _przed_testem else stan()
    ksiega = list(_ksiega)
    try:
        _porownaj(przed, ksiega, kiedy)
    finally:
        _ksiega.clear()
        _przed_testem[:] = [stan()]


def _porownaj(przed: Stan, ksiega: list[_Odcinek | _Wlasne], kiedy: str) -> None:
    teraz = stan()
    oczekiwane = _Oczekiwany.z_ksiegi(przed, ksiega)
    zostawione = oczekiwane.roznica(teraz)
    if not zostawione:
        return
    teraz_wartosci = dict(teraz.wartosci)
    if _KATALOG in zostawione.klucze and box_boat.przeniesiony(teraz_wartosci.get(_KATALOG, _USUNIETY)):
        _przywroc(zostawione, oczekiwane)
        raise _KatalogPrzeniesiony(
            f"{box_boat.KOMUNIKAT} (katalog roboczy {oczekiwane.wartosci.get(_KATALOG)} → {teraz_wartosci[_KATALOG]})"
        )
    nazwy = {zasob: _opis_zasobu(zasob) for zasob in zostawione.zasoby}  # przed gc, który zamyka deskryptor
    zebrane = _po_czekaniu_i_gc(zostawione)
    if not zostawione:
        return
    opisy = [
        nazwy[zasob] + _stan_zasobu(zasob, zebrane) + _czyj(oczekiwane.wlasciciele.get(zasob), kiedy)
        for zasob in sorted(zostawione.zasoby, key=_kolejnosc)
    ]
    opisy += [
        _opis_klucza(klucz, oczekiwane.wartosci.get(klucz), teraz_wartosci.get(klucz))
        + _czyj(oczekiwane.wlasciciele.get(klucz), kiedy)
        for klucz in sorted(zostawione.klucze)
    ]
    _przywroc(zostawione, oczekiwane)
    raise AssertionError(
        "Test albo jego fixtura zostawiły procesowi workera stan, który działa w oknie następnego testu: "
        + "; ".join(opisy)
        + ". Zamknij plik i gniazdo przez with albo try/finally (skoroszyt openpyxl read_only=True trzyma plik do "
        "workbook.close()), zatrzymaj i dołącz wątek, poczekaj na proces potomny, a katalog roboczy i środowisko "
        "zmieniaj przez monkeypatch (tests/fixtures/stan_procesu.py)."
    )


@dataclass
class _Oczekiwany:
    """Stan oczekiwany na końcu okresu: stan z jego początku z nałożonym w kolejności czasu skutkiem wpisów księgi.
    Odcinek setupu fixtury szerszego zasięgu zostawia jej zasoby i wartości z końca odcinka, koniec takiej fixtury
    wymaga dla każdego jej klucza wartości sprzed jej pierwszego odcinka, który go zmienił, i braku jej zasobów; każdy
    inny odcinek okresu (ciało testu, fixtury funkcji) ma skutek zero."""

    zasoby: set[_Zasob]
    wartosci: dict[_Klucz, str]
    linia: int
    wlasciciele: dict[object, _Fixture] = field(default_factory=dict)

    @classmethod
    def z_ksiegi(cls, przed: Stan, ksiega: list[_Odcinek | _Wlasne]) -> _Oczekiwany:
        oczekiwany = cls(set(przed.zasoby), dict(przed.wartosci), przed.linia)
        for wpis in ksiega:
            if isinstance(wpis, _Odcinek):
                oczekiwany.zasoby |= wpis.zasoby()
                wartosci: dict[_Klucz, str | None] = {klucz: dict(wpis.po.wartosci).get(klucz) for klucz in wpis.klucze()}
            else:
                zasoby = wpis.zasoby()
                oczekiwany.zasoby -= zasoby
                wartosci = wpis.wartosci_sprzed()
                oczekiwany.wlasciciele.update(dict.fromkeys((*zasoby, *wartosci), wpis.fixture))
            for klucz, wartosc in wartosci.items():
                if wartosc is None:
                    oczekiwany.wartosci.pop(klucz, None)
                else:
                    oczekiwany.wartosci[klucz] = wartosc
        return oczekiwany

    def roznica(self, teraz: Stan) -> Zostawione:
        """Zasoby, których nie powinno być, i klucze z inną wartością niż oczekiwana. Wątek bez właściciela liczy się
        tylko z linii okresu: wątek, który uruchomił wątek starszy od testu, do testu nie należy."""

        nowe = teraz.zasoby - self.zasoby
        linia = set(threads_since(self.linia)) if any(isinstance(z, threading.Thread) for z in nowe) else set()
        zasoby = {
            zasob
            for zasob in nowe
            if not isinstance(zasob, threading.Thread) or zasob in linia or zasob in self.wlasciciele
        }
        wartosci = dict(teraz.wartosci)
        klucze = {klucz for klucz in {*self.wartosci, *wartosci} if wartosci.get(klucz) != self.wartosci.get(klucz)}
        return Zostawione(zasoby, klucze)


def _przywroc(zostawione: Zostawione, oczekiwane: _Oczekiwany) -> None:
    """Wartości wracają do oczekiwanych, więc błąd ma tylko sprawca, a nie każdy następny test workera."""

    for klucz in zostawione.klucze:
        _ustaw(klucz, oczekiwane.wartosci.get(klucz))


def _po_czekaniu_i_gc(zostawione: Zostawione) -> set[_Zasob]:
    """Czeka na koniec wątków i potomków, potem zbiera śmieci; zostawia w ``zostawione`` to, co wciąż jest, i zwraca
    deskryptory, które zamknął dopiero ``gc`` (te zostają w ``zostawione``)."""

    termin = time.monotonic() + WATEK_S
    for zasob in zostawione.zasoby:
        if isinstance(zasob, threading.Thread):
            zasob.join(max(termin - time.monotonic(), 0))
    potomki = {zasob for zasob in zostawione.zasoby if isinstance(zasob, _Potomek)}
    wait_for(lambda: not potomki & {_Potomek(pid) for pid in children()}, POTOMEK_S)
    # Deskryptor zamknięty przez wątek, który właśnie się skończył, nie należy do gc.
    zostawione.zasoby &= _zasoby_procesu()
    deskryptory = {zasob for zasob in zostawione.zasoby if isinstance(zasob, _Deskryptor)}
    if not deskryptory:
        return set()
    zebrane: set[_Zasob] = set(left_to_gc(deskryptory))
    zostawione.zasoby &= _zasoby_procesu() | zebrane
    return zebrane


def _kolejnosc(zasob: _Zasob) -> tuple[int, int]:
    if isinstance(zasob, _Deskryptor):
        return (0, zasob.numer)
    if isinstance(zasob, threading.Thread):
        return (1, 0)
    return (2, zasob.pid)


def _opis_zasobu(zasob: _Zasob) -> str:
    if isinstance(zasob, _Deskryptor):
        return _opis_deskryptora(zasob)
    if isinstance(zasob, threading.Thread):
        return f"wątek {zasob.name}"
    return f"proces potomny {zasob.pid}"


def _stan_zasobu(zasob: _Zasob, zebrane: set[_Zasob]) -> str:
    if isinstance(zasob, _Deskryptor):
        return " zamknął dopiero gc" if zasob in zebrane else " otwarty po teście"
    return f" żyje {WATEK_S if isinstance(zasob, threading.Thread) else POTOMEK_S:g} s po teście"


def _opis_klucza(klucz: _Klucz, oczekiwana: str | None, teraz: str | None) -> str:
    if klucz == _KATALOG:
        brak = "" if oczekiwana is None or Path(oczekiwana).is_dir() else " (katalogu oczekiwanego już nie ma)"
        return f"katalog roboczy {oczekiwana} → {teraz or 'katalog usunięty'}{brak}"
    return f"zmienna środowiska {klucz[1]} zmieniona"


def _czyj(fixture: _Fixture | None, kiedy: str) -> str:
    if fixture is None:
        return ""
    return f" (fixtura {fixture.name} zasięgu {fixture.scope}, która skończyła się {kiedy})"


def _ustaw(klucz: _Klucz, wartosc: str | None) -> None:
    if klucz == _KATALOG:
        if wartosc:
            with suppress(FileNotFoundError):  # katalogu oczekiwanego już nie ma; komunikat go nazywa
                os.chdir(wartosc)
    elif wartosc is None:
        os.environ.pop(klucz[1], None)
    else:
        os.environ[klucz[1]] = wartosc


def stan() -> Stan:
    wartosci = {("zmienna", name): value for name, value in os.environ.items() if name not in _ZMIENNE_PYTEST}
    wartosci[_KATALOG] = _katalog_roboczy()
    return Stan(_zasoby_procesu(), frozenset(wartosci.items()), new_line())


_USUNIETY: Final = ""
"""Wartość katalogu roboczego, którego już nie ma: ``os.getcwd()`` rzuca wtedy ``FileNotFoundError``."""


def _katalog_roboczy() -> str:
    try:
        return os.getcwd()
    except FileNotFoundError:
        return _USUNIETY


def _zasoby_procesu() -> frozenset[_Zasob]:
    return frozenset(
        {*descriptors(), *(_Potomek(pid) for pid in children()), *(t for t in threads_since(0) if t.is_alive())}
    )


def descriptors() -> frozenset[_Deskryptor]:
    """Deskryptory procesu poza standardowymi strumieniami; na Windows pusty zbiór, bo nie ma taniej ich listy.
    Przechwytywanie pytest podmienia standardowe strumienie między setupem a teardownem."""

    if sys.platform == "win32":
        return frozenset()
    directory = "/dev/fd" if sys.platform == "darwin" else "/proc/self/fd"
    found: set[_Deskryptor] = set()
    for entry in Path(directory).iterdir():
        numer = int(entry.name)
        if numer in _STANDARD_STREAMS:
            continue
        try:
            info = os.fstat(numer)
        except OSError:  # deskryptor samej listy katalogu jest już zamknięty
            continue
        found.add(_Deskryptor(numer, _rodzaj(info.st_mode), info.st_dev, info.st_ino))
    return frozenset(found)


def _rodzaj(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "plik"
    if stat.S_ISSOCK(mode):
        return "gniazdo"
    if stat.S_ISFIFO(mode):
        return "potok"
    return "deskryptor"


def _opis_deskryptora(deskryptor: _Deskryptor) -> str:
    opis = f"{deskryptor.rodzaj} {deskryptor.numer}"
    if deskryptor.rodzaj != "plik":
        return opis
    try:
        if sys.platform == "darwin":
            import fcntl

            path = fcntl.fcntl(deskryptor.numer, fcntl.F_GETPATH, bytes(1024)).rstrip(b"\0").decode()
        else:
            path = os.readlink(f"/proc/self/fd/{deskryptor.numer}")
    except OSError:  # deskryptor już zamknięty (gc)
        return opis
    return f"{opis} {os.path.realpath(path)}"


def children() -> frozenset[int]:
    """Procesy potomne, które jeszcze działają: bez zakończonych, na które nikt nie czekał (zombie); na Windows pusty."""

    if sys.platform == "win32":
        return frozenset()
    return frozenset(pid for pid in _child_pids() if _dziala(pid))


def _child_pids() -> list[int]:
    if sys.platform == "darwin":
        bufor = (ctypes.c_int * 4096)()
        liczba = _libproc().proc_listchildpids(os.getpid(), bufor, ctypes.sizeof(bufor))
        return list(bufor[: max(liczba, 0)])
    found: list[int] = []
    for task in Path("/proc/self/task").iterdir():
        try:
            found += [int(pid) for pid in (task / "children").read_text().split()]
        except OSError:  # wątek skończył się w trakcie listy
            continue
    return found


_LIBPROC: list[ctypes.CDLL] = []


def _libproc() -> ctypes.CDLL:
    if not _LIBPROC:
        _LIBPROC.append(ctypes.CDLL("/usr/lib/libproc.dylib"))
    return _LIBPROC[0]


def _dziala(pid: int) -> bool:
    if sys.platform == "win32":
        return False
    try:
        # WNOWAIT zostawia zakończony proces temu, kto na niego czeka (subprocess.Popen.wait).
        return os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None
    except ChildProcessError:  # już odebrany
        return False


def left_to_gc(nowe: Iterable[_Deskryptor]) -> set[_Deskryptor]:
    """Deskryptory z ``nowe``, które zamknął dopiero ``gc.collect()``: obiekt w śmieciach albo finalizer śmiecia.

    ``gc.collect()`` zbiera wszystkie śmieci, nie tylko obserwowane: ostrzeżenie obiektu z deskryptorem z ``nowe``
    należy do wyniku pluginu, a każde inne idzie dalej do filtrów i zapisu ostrzeżeń wołającego, jak przy samoczynnym
    ``gc`` w tym miejscu.
    """

    nowe = set(nowe)
    numery = {deskryptor.numer for deskryptor in nowe}
    automatic = gc.isenabled()
    gc.disable()
    try:
        obserwowane = {id(obj) for obj in gc.get_objects() if _numer(obj) in numery}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gc.collect()
    finally:
        if automatic:
            gc.enable()
    for warning in caught:
        if _zrodlo(warning.source) not in obserwowane:
            warnings.warn_explicit(
                warning.message, warning.category, warning.filename, warning.lineno, source=warning.source
            )
    return nowe - descriptors()


def _numer(obj: object) -> int | None:
    if not isinstance(obj, (io.FileIO, socket.socket)):
        return None
    try:
        return obj.fileno()
    except (ValueError, OSError):  # zamknięty, także przez inny wątek w trakcie przeglądu
        return None


def _zrodlo(source: object) -> int | None:
    """``id`` obiektu z deskryptorem pod źródłem ``ResourceWarning``: plik ostrzega z warstwą, którą zamknął finalizer
    (``TextIOWrapper`` → ``.buffer``, bufor → ``.raw``), a gniazdo samo."""

    raw = getattr(getattr(source, "buffer", source), "raw", source)
    return id(raw) if isinstance(raw, (io.FileIO, socket.socket)) else None
