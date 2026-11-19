from __future__ import annotations

from collections.abc import Callable
import copy
import dataclasses
from dataclasses import dataclass
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any, Final, get_args

from fastapi.testclient import TestClient
import pytest

from rozliczenia.centrum import diagnosis_messages, refusal, runs
from rozliczenia.centrum.contract import common as common_contract
from rozliczenia.centrum.contract import runs as runs_contract
from rozliczenia.centrum.catalog import CATALOG
from rozliczenia.centrum.efenix_chrome import atrapa_opening
from rozliczenia.centrum.process_kind import HostParts, PathNeed, PeriodProcessKind, PreparedRun, ProcessKind, Start
from rozliczenia.centrum.comment_versions import summary_markdown
from rozliczenia.centrum.contract.common import Message
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.files import FieldProblem
from rozliczenia.centrum.settings_at_start import SettingNeed, SettingsAtStart
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.centrum.run_logs import RunLog
from rozliczenia.centrum.run_logs_guard import guard_logs
from rozliczenia.client_data import empty_memory
from rozliczenia.efenix_pricing import PricingMode
from rozliczenia.report_entering import ReportEnteringParts, ReportStateInMemory
from rozliczenia.run_context import RunContext
from rozliczenia.worker_list import WorkerList
from rozliczenia import tool_files
from tests.fixtures.centrum import ToolDirectory, centrum, finished_view
from tests.fixtures.centrum_intermax import entering_centrum, ordering_centrum
from tests.fixtures.centrum_processes import preparing_centrum, settling_centrum
from tests.fixtures.odczyt_bez_dostepu import reading
from tests.fixtures.znane_luki import assert_znane_luki, modul, zapisz
from atrapy.intermax import Intermax
from atrapy.preparation import PERIOD
from atrapy.settlement import write_worker_list
from atrapy.skrzynka_raportow import FolderInbox
import odtworzenie
import uruchom_proces
from uruchom_proces import ustawienia_z_wydania


def test_katalog_ma_jeden_wpis_kazdego_procesu_centrum() -> None:
    keys = [kind.key for kind in CATALOG.kinds]
    period_keys = [kind.key for kind in CATALOG.kinds if isinstance(kind, PeriodProcessKind)]

    assert sorted(keys) == sorted(get_args(common_contract.ProcessKey))
    assert sorted(period_keys) == sorted(get_args(common_contract.PeriodProcessKey))


def test_wpis_procesu_z_okresem_odmawia_trybow_wyceny_z_innym_pierwszym_niz_tryb_logow_sprzed_trybow() -> None:
    efenix = CATALOG.kind("efenix")
    assert isinstance(efenix, PeriodProcessKind)
    swapped = dataclasses.replace(efenix.view, pricing_modes=tuple(reversed(efenix.view.pricing_modes)))

    with pytest.raises(AssertionError, match="pierwszy tryb"):
        dataclasses.replace(efenix, view=swapped)


_GOTOWE_URUCHOMIENIE: Final = (
    "import contextlib\nimport threading\nimport types\nimport typing\nfrom typing import Any\n\n"
    "from rozliczenia.centrum import process_kind, runs\n"
    "from rozliczenia.centrum.process_kind import PreparedRun\n\ngotowe = object.__new__(PreparedRun)\n\n\n"
    "class Bez:\n    def __init_subclass__(cls, **kwargs: object) -> None:\n        pass\n\n\n"
    "class Polyka:\n    def __init_subclass__(cls, **kwargs: object) -> None:\n"
    "        with contextlib.suppress(TypeError):\n            super().__init_subclass__(**kwargs)\n\n\n"
)
PODKLASY_GOTOWEGO_URUCHOMIENIA: Final = {
    "nazwa z importu": "class Moja(PreparedRun[Any, Any]):\n    pass\n",
    "nazwa z importu pod aliasem": "from rozliczenia.centrum.process_kind import PreparedRun as _G\n\n\nclass Moja(_G):\n    pass\n",
    "atrybut modułu": "class Moja(process_kind.PreparedRun[Any, Any]):\n    pass\n",
    "nazwa przypisana poza importem": "ZLOZ = PreparedRun\n\n\nclass Moja(ZLOZ[Any, Any]):\n    pass\n",
    "type(gotowe)": "class Moja(type(gotowe)):\n    pass\n",
    "type z trzema argumentami": 'Moja = type("Moja", (PreparedRun,), {"conduct": lambda self, interlocutor: None})\n',
    "types.new_class": 'Moja = types.new_class("Moja", (PreparedRun[Any, Any],))\n',
    "baza przed PreparedRun bez super()": "ZLOZ = PreparedRun\n\n\nclass Moja(Bez, ZLOZ[Any, Any]):\n    pass\n",
    "baza przed PreparedRun połyka TypeError": "ZLOZ = PreparedRun\n\n\nclass Moja(Polyka, ZLOZ[Any, Any]):\n    pass\n",
    "type(gotowe) z bazą przed nim bez super()": "class Moja(Bez, type(gotowe)):\n    pass\n",
    "type() z bazą przed PreparedRun": 'Moja = type("Moja", (Bez, PreparedRun), {})\n',
    "types.new_class z metaklasą type w kwds": 'Moja = types.new_class("Moja", (Bez, PreparedRun[Any, Any]), {"metaclass": type})\n',
    "type.__new__ z metaklasą type": 'Moja = type.__new__(type, "Moja", (Bez, PreparedRun), {})\n',
    "type.__new__ z metaklasą PreparedRun bez bazy przed nim": 'Moja = type.__new__(type(PreparedRun), "Moja", (PreparedRun,), {})\n',
    "__init_subclass__ PreparedRun podmienione w biegu": (
        "STARE = PreparedRun.__dict__['__init_subclass__']\n"
        "setattr(PreparedRun, '__init_subclass__', classmethod(lambda cls, **kwargs: None))\n"
        'try:\n    Moja = type("Moja", (PreparedRun,), {})\nfinally:\n    setattr(PreparedRun, "__init_subclass__", STARE)\n'
    ),
}


_ODMOWA_PODKLASY: Final = (
    "nie ma podklas: składa je tylko Catalog.prepared, a rdzeń, plik metryk i silnik procesu podmienia "
    "Catalog.steered, Catalog.with_metrics i Catalog.with_engine"
)


@pytest.mark.parametrize("podklasa", PODKLASY_GOTOWEGO_URUCHOMIENIA.values(), ids=PODKLASY_GOTOWEGO_URUCHOMIENIA.keys())
def test_uruchomienie_gotowe_do_startu_nie_ma_podklas_takze_zrobionych_w_trakcie_dzialania(
    podklasa: str, tmp_path: Path
) -> None:
    plik = tmp_path / "podklasa.py"
    plik.write_text(_GOTOWE_URUCHOMIENIE + podklasa, encoding="utf-8")

    with pytest.raises(TypeError, match=_ODMOWA_PODKLASY):
        modul(plik)


def test_typ_uruchomienia_gotowego_do_startu_w_adnotacji_nie_jest_podklasa(tmp_path: Path) -> None:
    plik = tmp_path / "adnotacja.py"
    plik.write_text(
        _GOTOWE_URUCHOMIENIE + "def start(run: PreparedRun[Any, Any]) -> PreparedRun[Any, Any]:\n    return run\n\n\n"
        "TYPY = [typing.get_origin(typ) for typ in typing.get_type_hints(start).values()]\n",
        encoding="utf-8",
    )

    wykonany = modul(plik)

    assert wykonany.TYPY == [wykonany.PreparedRun, wykonany.PreparedRun]


_WLASNE: Final = "    def conduct(self, interlocutor: object) -> str:\n        return 'własne'\n"
_OMIJA_METAKLASE: Final = (
    'Moja = type.__new__(type(PreparedRun), "Moja", (Bez, PreparedRun), {"conduct": lambda self, interlocutor: "własne"})\n'
)
URUCHOMIENIA_OBOK_KATALOGU: Final = {
    "type.__new__ z metaklasą PreparedRun": _OMIJA_METAKLASE + "uruchomienie = object.__new__(Moja)\n",
    "metaklasa pochodna wołająca type.__new__": (
        'Meta: Any = type("Meta", (type(PreparedRun),), {"__new__": type.__new__})\n'
        'uruchomienie = object.__new__(Meta("Moja", (Bez, PreparedRun), {}))\n'
    ),
    "__new__ metaklasy podmienione w biegu": (
        "META = type(PreparedRun)\nSTARE = META.__dict__['__new__']\nsetattr(META, '__new__', type.__new__)\n"
        'try:\n    Moja = types.new_class("Moja", (Bez, PreparedRun))\nfinally:\n    setattr(META, "__new__", STARE)\n'
        "uruchomienie = object.__new__(Moja)\n"
    ),
    "__bases__ przypisane klasie o układzie PreparedRun": (
        "class Blizniak(typing.Generic[*PreparedRun.__parameters__]):\n    __slots__ = PreparedRun.__slots__\n\n\n"
        f"class Moja(Blizniak):\n    __slots__ = ()\n\n{_WLASNE}\n\n"
        "Moja.__bases__ = (PreparedRun,)\nuruchomienie = object.__new__(Moja)\n"
    ),
    "__class__ obcej klasy o tych samych slotach": (
        f"class Moja(typing.Generic[*PreparedRun.__parameters__]):\n    __slots__ = PreparedRun.__slots__\n\n{_WLASNE}\n\n"
        "uruchomienie = object.__new__(PreparedRun)\nuruchomienie.__class__ = Moja\n"
    ),
}


@pytest.mark.parametrize("kod", URUCHOMIENIA_OBOK_KATALOGU.values(), ids=URUCHOMIENIA_OBOK_KATALOGU.keys())
def test_uruchomienie_w_centrum_startuje_tylko_z_typu_uruchomienia_gotowego_do_startu(kod: str, tmp_path: Path) -> None:
    plik = tmp_path / "obok_katalogu.py"
    plik.write_text(_GOTOWE_URUCHOMIENIE + kod + "\nruns.Run(None, uruchomienie, None, threading)\n", encoding="utf-8")

    with pytest.raises(TypeError, match="nie ma podklas: składa je tylko Catalog.prepared.* Start dostał Moja"):
        modul(plik)


_PODMIANA: Final = (
    "WOLANE: list[str] = []\n\n\nclass BezSlotow:\n    __slots__ = ()\n\n"
    "    def __init_subclass__(cls, **kwargs: object) -> None:\n        pass\n\n\n"
    "def wlasne(self: object, interlocutor: object) -> str:\n    WOLANE.append('własne')\n    return 'własne'\n\n\n"
    'Moja = type.__new__(type(PreparedRun), "Moja", (BezSlotow, PreparedRun), {"__slots__": (), "conduct": wlasne})\n'
)


def _silnik(*_: object, **__: object) -> Any:
    raise AssertionError("w teście odmowy prawdziwy silnik nie biegnie")


def _z_katalogu() -> PreparedRun[Any, Any]:
    paths = {need: Path(f"{need}.xlsx") for need in CATALOG.kind("preparation").path_needs}
    start = Start(paths, period=PERIOD, dry_run=False, settings=ustawienia_z_wydania(WorkerList(())))
    return CATALOG.with_engine(_silnik).prepared("preparation", start, HostParts(), RunContext())


class _Odmowa(Exception):
    ...

class _Gospodarz:
    def failed(self, failure: Exception) -> None:
        raise _Odmowa from failure


_GOSPODARZ: Final[Any] = _Gospodarz()
_BEZ_ZATRZYMAN: Final[Any] = None


class _Katalog:
    def __init__(self, run: PreparedRun[Any, Any]) -> None:
        self._run = run

    def __getattr__(self, name: str) -> Any:
        return getattr(CATALOG, name)

    def with_metrics(self, _metrics: object) -> _Katalog:
        return self

    def prepared(self, *_parts: object) -> PreparedRun[Any, Any]:
        return self._run


def _w_centrum_po_przyjeciu(podklasa: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _z_katalogu()
    uruchomienie = runs.Run(_GOSPODARZ, run, _BEZ_ZATRZYMAN, threading)
    run.__class__ = podklasa
    uruchomienie.work()


def _w_centrum_z_podmienionym_polem(podklasa: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    uruchomienie = runs.Run(_GOSPODARZ, _z_katalogu(), _BEZ_ZATRZYMAN, threading)
    inne = _z_katalogu()
    inne.__class__ = podklasa
    monkeypatch.setattr(uruchomienie, "_prepared", inne)
    uruchomienie.work()


def _w_skrypcie_dla_maszyn(podklasa: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _z_katalogu()
    run.__class__ = podklasa
    monkeypatch.setattr(uruchom_proces, "CATALOG", _Katalog(run))
    uruchom_proces.main(["intermax", "--register", str(tmp_path / "Rejestr.xlsx"), "--metrics", str(tmp_path / "m.jsonl")])


def _w_odtworzeniu(podklasa: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _z_katalogu()
    run.__class__ = podklasa
    logi: Any = SimpleNamespace(run_id="odtworzone", ending="finished")
    odtworzenie._run(logi, run, empty_memory())


def _conduct_z_klasy(podklasa: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _z_katalogu()
    run.__class__ = podklasa
    rozmowca: Any = None
    PreparedRun.conduct(run, rozmowca)


UZYCIA_GOTOWEGO_URUCHOMIENIA: Final = {
    "Run.work: __class__ podmienione po przyjęciu": _w_centrum_po_przyjeciu,
    "Run.work: pole _prepared podmienione po przyjęciu": _w_centrum_z_podmienionym_polem,
    "Skrypt dla maszyn: __class__ podmienione przed conduct": _w_skrypcie_dla_maszyn,
    "odtworzenie z Logów: __class__ podmienione przed conduct": _w_odtworzeniu,
    "PreparedRun.conduct z klasy na obiekcie podklasy": _conduct_z_klasy,
}


@pytest.mark.parametrize("uzycie", UZYCIA_GOTOWEGO_URUCHOMIENIA.values(), ids=UZYCIA_GOTOWEGO_URUCHOMIENIA.keys())
def test_conduct_odmawia_obiektu_podklasy_w_chwili_uzycia(
    uzycie: Callable[[type, Path, pytest.MonkeyPatch], None], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plik = tmp_path / "podmiana.py"
    plik.write_text(_GOTOWE_URUCHOMIENIE + _PODMIANA, encoding="utf-8")
    podmiana = modul(plik)

    with pytest.raises((TypeError, _Odmowa)) as odmowa:
        uzycie(podmiana.Moja, tmp_path, monkeypatch)

    przyczyna = odmowa.value.__cause__ if isinstance(odmowa.value, _Odmowa) else odmowa.value
    assert (podmiana.WOLANE, type(przyczyna), str(przyczyna).rsplit(". ", 1)[-1]) == ([], TypeError, "Start dostał Moja.")
    assert "nie ma podklas: składa je tylko Catalog.prepared" in str(przyczyna)


_UDAJE_START: Final = (
    "    def info(self, run_id: str) -> None:\n        return None\n\n"
    "    def progress_view(self, snapshot: object) -> None:\n        return None\n"
)
ZNANE_LUKI_STARTU: Final = {
    "nowe miejsce użycia: conduct podklasy wołany bez startable": (
        _OMIJA_METAKLASE + "assert object.__new__(Moja).conduct(None) == 'własne'\n"
    ),
    "podmiana w biegu: nazwa PreparedRun w process_kind": (
        _OMIJA_METAKLASE + "process_kind.PreparedRun = Moja\ntry:\n    assert process_kind.startable(object.__new__(Moja)).conduct(None) == 'własne'\n"
        "finally:\n    process_kind.PreparedRun = PreparedRun\n"
    ),
}


def test_znane_luki_odmowy_startu_uruchomienia_obok_katalogu(tmp_path: Path) -> None:
    pliki = zapisz({opis: _GOTOWE_URUCHOMIENIE + kod for opis, kod in ZNANE_LUKI_STARTU.items()}, tmp_path)
    zgloszenia: dict[str, list[str]] = {}
    for opis, plik in pliki.items():
        try:
            modul(plik)
        except TypeError as odmowa:
            zgloszenia[opis] = [f"odmowa: {odmowa}"]
        else:
            zgloszenia[opis] = []

    assert_znane_luki(zgloszenia, "tests/test_katalog_procesow.py (ZNANE_LUKI_STARTU)")


KOPIE_PRZEZ_REPLACE: Final = {
    "dataclasses.replace": lambda gotowe: dataclasses.replace(gotowe, period="2026-11"),
    "copy.replace": lambda gotowe: copy.replace(gotowe, period="2026-11"),
}


@pytest.mark.parametrize("kopia", KOPIE_PRZEZ_REPLACE.values(), ids=KOPIE_PRZEZ_REPLACE.keys())
def test_kopia_gotowego_uruchomienia_przez_replace_rzuca_takze_obok_mypy(kopia: Callable[[Any], object]) -> None:
    bez_pol: Any = object.__new__(PreparedRun)

    with pytest.raises(TypeError, match=r"replace\(\)"):
        kopia(bez_pol)


def test_tryb_z_karty_to_tryb_silnika_wyceny_w_efenix_pod_ta_sama_nazwa() -> None:
    assert {mode.value for mode in PricingMode} == set(get_args(runs_contract.Pricing))


_SETTLEMENT_FILES: Final[dict[PathNeed, Path]] = {
    "collective_file": Path("plik-zbiorczy.xlsx"),
    "worker_template": Path("wzorzec.xlsx"),
}
_ATRAPA: Final = HostParts(efenix=atrapa_opening("http://127.0.0.1:9/index.php"))


@pytest.mark.parametrize(
    ("key", "start", "parts", "error"),
    [
        (
            "settlement",
            Start(
                {"collective_file": Path("plik-zbiorczy.xlsx")},
                period=None,
                dry_run=False,
                settings=ustawienia_z_wydania(WorkerList(())),
            ),
            HostParts(),
            "potrzebuje plików",
        ),
        (
            "preparation",
            Start(
                {
                    "register": Path("rejestr.xlsx"),
                    "periods_directory": Path("okresy"),
                    "internal_template": Path("wewnetrzny.xlsx"),
                    "collective_template": Path("zbiorczy.xlsx"),
                },
                period=None,
                dry_run=True,
                settings=ustawienia_z_wydania(None),
            ),
            HostParts(),
            "potrzebuje okresu",
        ),
        ("efenix", Start({"collective_file": Path("plik-zbiorczy.xlsx")}, None, False, settings=ustawienia_z_wydania(None)), HostParts(), "potrzebuje okna efenix"),
        ("efenix", Start({"collective_file": Path("plik-zbiorczy.xlsx")}, None, True, settings=ustawienia_z_wydania(None)), _ATRAPA, "nie ma Podglądu bez zapisu"),
        (
            "settlement",
            Start(
                _SETTLEMENT_FILES,
                None,
                False,
                pricing="z Przekazaniem",
                settings=ustawienia_z_wydania(WorkerList(())),
            ),
            HostParts(),
            "nie ma trybu z Przekazaniem",
        ),
    ],
    ids=["bez-pliku", "bez-okresu", "bez-okna-efenix", "podglad-bez-podgladu", "tryb-spoza-procesu"],
)
def test_start_bez_potrzeby_procesu_to_blad_gospodarza_a_nie_uruchomienie(
    key: common_contract.ProcessKey, start: Start, parts: HostParts, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        CATALOG.prepared(key, start, parts, RunContext())


_BRAK_W_STARCIE: Final = {
    "workers": "potrzebuje Listy Wykonawców, a start jej nie ma",
    "quantity_rules": "liczy Regułami ilości, a start ich nie ma",
    "activity_legend": "liczy Legendą czynności, a start jej nie ma",
}


_PELNE: Final = ustawienia_z_wydania(WorkerList(()))
_BEZ_USTAWIENIA: Final = {
    "workers": dataclasses.replace(_PELNE, workers=None),
    "quantity_rules": dataclasses.replace(_PELNE, quantity_rules=None),
    "activity_legend": dataclasses.replace(_PELNE, activity_legend=None),
}


def _liczy_w_starcie(kind: ProcessKind[Any, Any]) -> tuple[str, ...]:
    return tuple(ustawienie for ustawienie in get_args(SettingNeed) if ustawienie in kind.needs)


@pytest.mark.parametrize(
    ("kind", "ustawienie"),
    [(kind, ustawienie) for kind in CATALOG.kinds for ustawienie in _liczy_w_starcie(kind)],
    ids=lambda wartosc: wartosc.key if isinstance(wartosc, ProcessKind) else wartosc,
)
def test_start_bez_listy_regul_albo_legendy_ktorymi_proces_liczy_to_blad_gospodarza(
    kind: ProcessKind[Any, Any], ustawienie: str
) -> None:
    start = Start(
        {need: Path(need) for need in kind.path_needs},
        PERIOD if "period" in kind.needs else None,
        False,
        settings=_BEZ_USTAWIENIA[ustawienie],
    )

    with pytest.raises(ValueError, match=f"^{kind.title} {_BRAK_W_STARCIE[ustawienie]}$"):
        CATALOG.prepared(kind.key, start, _ATRAPA, RunContext())


def test_kazde_ustawienie_ze_startu_z_potrzeb_procesu_to_pole_ustawien_ze_startu() -> None:
    assert set(get_args(SettingNeed)) <= {pole.name for pole in dataclasses.fields(SettingsAtStart)}


@pytest.mark.parametrize("kind", CATALOG.kinds, ids=lambda kind: kind.key)
def test_uruchomienie_gotowe_do_startu_ma_tylko_ustawienia_ze_startu_ktorymi_proces_liczy(
    kind: ProcessKind[Any, Any],
) -> None:
    ostrzezenia = (diagnosis_messages.worker_list_last_good("zdanie"),)
    pelne = dataclasses.replace(_PELNE, warnings=ostrzezenia)
    start = Start({need: Path(need) for need in kind.path_needs}, PERIOD if "period" in kind.needs else None, False, settings=pelne)

    czesci = dataclasses.replace(_ATRAPA, reports=ReportEnteringParts(FolderInbox(Path("skrzynka")), ReportStateInMemory()))

    niesione = CATALOG.prepared(kind.key, start, czesci, RunContext()).settings

    assert {need for need in get_args(SettingNeed) if getattr(niesione, need) is not None} == set(_liczy_w_starcie(kind))
    assert niesione.warnings == ostrzezenia


@pytest.mark.parametrize(("chosen", "expected"), [(None, "bez Przekazania"), ("z Przekazaniem", "z Przekazaniem")])
def test_wycena_bez_wybranego_trybu_biegnie_bez_przekazania_jak_przed_trybami(
    chosen: runs_contract.Pricing | None, expected: runs_contract.Pricing
) -> None:
    start = Start(
        {"collective_file": Path("plik-zbiorczy.xlsx")},
        period=None,
        dry_run=False,
        pricing=chosen,
        settings=ustawienia_z_wydania(None),
    )

    prepared = CATALOG.prepared("efenix", start, _ATRAPA, RunContext())

    assert (prepared.inputs.mode.value, prepared.info("u").pricing) == (expected, expected)


_FOLDERY_ZE_STARTU: Final[frozenset[PathNeed]] = frozenset({"periods_directory", "copies_directory"})


def _zaloz(sciezka: Path, folder: bool) -> None:
    if folder:
        sciezka.mkdir()
        (sciezka / "w-folderze.xlsx").write_bytes(b"x")
    else:
        sciezka.write_bytes(b"x")


@pytest.mark.parametrize("pliki_sa", [True, False], ids=["pliki-sa", "plikow-nie-ma"])
@pytest.mark.parametrize("kind", CATALOG.kinds, ids=lambda kind: kind.key)
def test_wejscie_procesu_nie_czyta_nie_listuje_i_nie_zapisuje_plikow_ani_folderow_ze_startu(
    kind: ProcessKind[Any, Any], pliki_sa: bool, tmp_path: Path
) -> None:
    swiat = tmp_path / "taty" / "pliki"
    swiat.mkdir(parents=True)
    sciezki = {need: swiat / need for need in kind.path_needs}
    baza = swiat / "order_base" if "order_base" in kind.needs else None
    skrzynka = swiat / "skrzynka"
    if pliki_sa:
        for need, sciezka in sciezki.items():
            _zaloz(sciezka, need in _FOLDERY_ZE_STARTU)
        if baza is not None:
            _zaloz(baza, folder=False)
        _zaloz(skrzynka, folder=True)
    przed = sorted(tmp_path.rglob("*"))
    start = Start(sciezki, PERIOD if "period" in kind.needs else None, False, settings=_PELNE, order_base=baza)
    czesci = dataclasses.replace(_ATRAPA, reports=ReportEnteringParts(FolderInbox(skrzynka), ReportStateInMemory()))

    with reading(tmp_path) as dostep:
        CATALOG.prepared(kind.key, start, czesci, RunContext())

    assert (dostep.order, dostep.listed, sorted(tmp_path.rglob("*"))) == ([], set(), przed)


def test_kazdy_proces_ma_wlasna_historie_metryk_w_katalogu_narzedzia() -> None:
    assert CATALOG.metrics_paths == {
        "preparation": tool_files.PREPARATION_METRICS,
        "settlement": tool_files.SETTLEMENT_METRICS,
        "efenix": tool_files.EFENIX_METRICS,
        "intermax": tool_files.INTERMAX_METRICS,
        "report_entering": tool_files.REPORT_ENTERING_METRICS,
    }


def _period_setup(key: str) -> Callable[[TestClient], tuple[str | None, Any]]:
    def setup_and_start(client: TestClient) -> tuple[str | None, Any]:
        setup = next(process for process in client.get("/api/runs/setup").json()["processes"] if process["process"] == key)
        return setup["blocker"], client.post("/api/runs", json={"process": key, "period": PERIOD, "mode": "DRY-RUN"})

    return setup_and_start


def _intermax_setup(client: TestClient) -> tuple[str | None, Any]:
    return client.get("/api/intermax").json()["blocker"], client.post("/api/intermax/run")


def _report_entering_setup(client: TestClient) -> tuple[str | None, Any]:
    return client.get("/api/report-entering").json()["blocker"], client.post("/api/report-entering/run")


_SETUP_AND_START: dict[common_contract.ProcessKey, Callable[[TestClient], tuple[str | None, Any]]] = {
    "preparation": _period_setup("preparation"),
    "settlement": _period_setup("settlement"),
    "efenix": _period_setup("efenix"),
    "intermax": _intermax_setup,
    "report_entering": _report_entering_setup,
}


@pytest.mark.parametrize("declaration", CATALOG.kinds, ids=lambda declaration: declaration.key)
def test_bez_ustawien_taty_karta_i_odmowa_startu_mowia_to_samo_co_brakuje(
    tmp_path: Path, declaration: ProcessKind[Any, Any]
) -> None:
    client = centrum(tmp_path).client

    blocker, refused = _SETUP_AND_START[declaration.key](client)

    assert refused.status_code == 409
    assert blocker is not None and blocker.startswith("Najpierw wskaż ")
    assert refused.json()["message"] == blocker


@dataclass(frozen=True)
class _Stopping:
    client: TestClient
    tool: ToolDirectory
    start: Callable[[], Any]


def _stopping_preparation(tmp_path: Path) -> _Stopping:
    preparing = preparing_centrum(tmp_path)
    preparing.engines.fail_summary = True
    return _Stopping(preparing.client, preparing.tool, lambda: preparing.start(dry_run=True))


def _stopping_settlement(tmp_path: Path) -> _Stopping:
    settling = settling_centrum(tmp_path)
    settling.engines.fail_summary = True
    return _Stopping(settling.client, settling.tool, lambda: settling.start(dry_run=True))


def _stopping_efenix(tmp_path: Path) -> _Stopping:
    settling = settling_centrum(tmp_path)
    settling.engines.fail_engine = True
    return _Stopping(
        settling.client,
        settling.tool,
        lambda: settling.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "mode": "RUN"}),
    )


def _stopping_intermax(tmp_path: Path) -> _Stopping:
    ordering = ordering_centrum(tmp_path)
    ordering.engines.fail_summary = True
    return _Stopping(ordering.client, ordering.tool, ordering.start)


def _stopping_report_entering(tmp_path: Path) -> _Stopping:
    entering = entering_centrum(tmp_path, Intermax())
    entering.engines.fail_summary = True
    return _Stopping(entering.client, entering.tool, entering.start)


_STOPPING: dict[common_contract.ProcessKey, Callable[[Path], _Stopping]] = {
    "preparation": _stopping_preparation,
    "settlement": _stopping_settlement,
    "efenix": _stopping_efenix,
    "intermax": _stopping_intermax,
    "report_entering": _stopping_report_entering,
}


def _stopped(key: common_contract.ProcessKey, tmp_path: Path) -> tuple[TestClient, dict[str, Any]]:
    stopping = _STOPPING[key](tmp_path)
    started = stopping.start()
    assert started.status_code == 200, started.json()
    return stopping.client, finished_view(stopping.client)


@pytest.mark.parametrize("declaration", CATALOG.kinds, ids=lambda declaration: declaration.key)
def test_uruchomienie_procesu_ma_te_same_fakty_wpisu_na_karcie_w_logach_historii_i_metrykach(
    tmp_path: Path, declaration: ProcessKind[Any, Any]
) -> None:
    client, view = _stopped(declaration.key, tmp_path)
    run = view["run"]

    card = client.get(f"/api/runs/{run['id']}/card").json()
    (log_file,) = ToolDirectory(tmp_path).run_logs.glob(f"*-{run['id']}.json")
    metrics = client.get("/api/metrics").json()

    assert (run["process"], run["title"]) == (declaration.key, declaration.title)
    assert (run["confirms_readiness"], run["register_name"]) == (
        declaration.view.confirms_readiness,
        declaration.view.register_name,
    )
    assert card["run"] == run
    record = RunLog.model_validate_json(log_file.read_text(encoding="utf-8"))
    assert (record.quantity_rules is not None) is ("quantity_rules" in declaration.needs)
    assert (record.activity_legend is not None) is ("activity_legend" in declaration.needs)
    logs = guard_logs(record, empty_memory())
    assert summary_markdown(logs).startswith(
        f"**Logi Uruchomienia**: {declaration.title}, "
    )
    assert [row["process_label"] for row in metrics["runs"] if row["run_id"] == run["id"]] == [declaration.title]
    assert [row["mode"] for row in metrics["statistics"] if row["process"] == declaration.key] == list(
        declaration.view.modes
    )


@pytest.mark.parametrize("declaration", CATALOG.kinds, ids=lambda declaration: declaration.key)
def test_diagnoza_kazdego_procesu_idzie_w_kolejnosci_wyjasniania(
    tmp_path: Path, declaration: ProcessKind[Any, Any]
) -> None:
    client, view = _stopped(declaration.key, tmp_path)

    diagnosis = client.post(f"/api/runs/{view['run']['id']}/diagnosis").json()
    labels = [check["label"] for check in diagnosis["checks"]]

    assert labels[:2] == ["Ustawienia Centrum", "Pliki w OneDrive"]
    assert labels[-3:] == ["Aktualność narzędzia", "Token do Zgłoszeń", "Dziennik Centrum rozliczeń"]
    assert ("Folder okresu" in labels) is declaration.reads_period_folder
    assert ("Pliki okresu w Excelu" in labels) is declaration.reads_period_folder
    assert any(label.startswith("Wzorzec ") for label in labels) is bool(declaration.templates)


_DAMAGED_WORKERS: Final = settings_messages.damaged(WORKERS_FILE, settings_messages.MAKS_FIXES)


def _centrum_czyta_liste_przed_zepsuciem(stopping: _Stopping, *, z_plikiem_listy: bool) -> None:
    listed = stopping.tool.worker_list
    if z_plikiem_listy and not listed.exists():
        write_worker_list(listed)
    if not z_plikiem_listy:
        listed.unlink(missing_ok=True)
    stopping.client.get("/api/settings")


def _ostrzezenia_o_liscie_tylko_po_starcie_ktory_zaczal_uruchomienie(
    client: TestClient, started: Any
) -> list[dict[str, Any]] | None:
    if started.status_code != 200:
        return None
    return [warning for warning in finished_view(client)["result"]["warnings"] if warning["setting"] == "wykonawcy"]


@pytest.mark.parametrize("last_good", [True, False], ids=["z-ostatnia-dobra", "bez-ostatniej-dobrej"])
@pytest.mark.parametrize("declaration", CATALOG.kinds, ids=lambda declaration: declaration.key)
def test_zla_lista_wykonawcow_wstrzymuje_albo_ostrzega_tylko_proces_ktory_jej_potrzebuje(
    tmp_path: Path, declaration: ProcessKind[Any, Any], last_good: bool
) -> None:
    stopping = _STOPPING[declaration.key](tmp_path)
    _centrum_czyta_liste_przed_zepsuciem(stopping, z_plikiem_listy=last_good)
    stopping.tool.worker_list.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8")

    started = stopping.start()
    refused = started.json()["message"] if started.status_code == 409 else None
    warnings = _ostrzezenia_o_liscie_tylko_po_starcie_ktory_zaczal_uruchomienie(stopping.client, started)

    needed = "workers" in declaration.needs
    last_good_warning = Message.of(diagnosis_messages.worker_list_last_good(_DAMAGED_WORKERS)).model_dump()
    expected: tuple[int, str | None, list[dict[str, Any]] | None] = (
        (409, refusal.workers_unusable(FieldProblem(None, _DAMAGED_WORKERS)).message, None)
        if needed and not last_good
        else (200, None, [last_good_warning] if needed else [])
    )
    assert (started.status_code, refused, warnings) == expected
