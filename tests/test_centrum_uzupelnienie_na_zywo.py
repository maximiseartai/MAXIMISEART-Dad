"""Uzupełnienie pliku zbiorczego na żywo (#419, ADR 0016), przez HTTP API jak przeglądarka.

Strona pyta co kilka sekund o znacznik zapisu Pliku zbiorczego i pobiera widok dopiero po jego zmianie. Gdy odczyt
się nie uda, widok przez minutę niesie ostatni dobry stan z godziną odczytu, a potem Komunikat. Minutę odmierza
zegar Centrum testu, nigdy uśpienie.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import shutil
from typing import Any

import pytest
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from rozliczenia import workbook_files
from rozliczenia.centrum.live_file import LastGoodReads
from rozliczenia.input_checks import FILE_READERS
from tests.fixtures.centrum import FakeOneDrive
from tests.fixtures.clock import ManualClock
from tests.fixtures.centrum_processes import PreparingCentrum, Surroundings, preparing_centrum, run_to_end
from atrapy.preparation import PERIOD, register_order

TUE = datetime(2026, 9, 8, 10, 0)
MON = datetime(2026, 9, 14, 9, 0)
VIEW = f"/api/periods/{PERIOD}/quantities-to-fill"
VERSION = f"/api/periods/{PERIOD}/collective-file-version"
LOG_EVENT = "uzupelnienie-odczyt-nieudany"
# Odstęp, co który strona ponawia nieudany odczyt (frontend/src/lib/use-live-file.ts).
POLL_S = 3


def _prepared(tmp_path: Path, *, surroundings: Surroundings | None = None) -> PreparingCentrum:
    # Wiersz 18 z URZĄDZENIAMI, których Reguły ilości nie znają (bez reguły); ostatnie zlecenie w poniedziałek,
    # więc okres jest pełny i Przygotowanie nie czeka na Decyzję taty.
    rows = [{**register_order(1, TUE), "URZĄDZENIA": "przeniesienie"}, {**register_order(2, MON), "URZĄDZENIA": ""}]
    centrum = preparing_centrum(tmp_path, list(rows), surroundings=surroundings)
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    return centrum


def _get(centrum: PreparingCentrum, url: str) -> dict[str, Any]:
    response = centrum.client.get(url)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def _without_rule(view: dict[str, Any]) -> list[tuple[int, bool]]:
    [kind] = (kind for kind in view["kinds"] if kind["kind"] == "without_rule")
    return [(row["row"], row["state"] == "done") for row in kind["rows"]]


def _type_in_excel(path: Path, cell: str, value: int) -> None:
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    sheet[cell] = value
    workbook.save(path)


def _polled(centrum: PreparingCentrum, seconds: int) -> dict[str, Any]:
    """Strona ponawia odczyt co 3 s przez ``seconds`` sekund zegara Centrum; ostatni widok."""

    view: dict[str, Any] = {}
    for _ in range(seconds // POLL_S):
        centrum.surroundings.clock.advance(minutes=POLL_S / 60)
        view = _get(centrum, VIEW)
    return view


def _hidden_for(centrum: PreparingCentrum, seconds: float) -> None:
    """Karta ukryta (albo Excel zasłania przeglądarkę): strona przez ``seconds`` sekund nie pyta serwera."""

    centrum.surroundings.clock.advance(minutes=seconds / 60)


@dataclass
class _SlowOneDrive(FakeOneDrive):
    """OneDrive, który przez ``seconds`` sekund zegara Centrum próbuje pobrać plik tylko w chmurze, zanim odczyt padnie."""

    clock: ManualClock | None = None
    seconds: float = 0

    def attributes(self, path: Path) -> int:
        if self.clock is not None and path in self.online_only:
            self.clock.advance(minutes=self.seconds / 60)
        return super().attributes(path)


def _log_lines(centrum: PreparingCentrum) -> list[str]:
    if not centrum.log_path.exists():
        return []
    return [line for line in centrum.log_path.read_text(encoding="utf-8").splitlines() if LOG_EVENT in line]


def test_sprawdzenie_zapisu_bez_zmian_nie_otwiera_skoroszytu(tmp_path: Path) -> None:
    opened: list[Path] = []

    def counted(path: Path) -> bytes:
        opened.append(path)
        return workbook_files.file_bytes(path)

    centrum = _prepared(tmp_path, surroundings=Surroundings(readers=replace(FILE_READERS, source=counted)))
    shown = _get(centrum, VIEW)["read"]["version"]
    opened.clear()

    answers = [_get(centrum, VERSION)["version"] for _ in range(3)]

    assert shown is not None
    assert answers == [shown] * 3
    assert opened == []
    _get(centrum, VIEW)
    assert opened == [centrum.fixture.collective_file_path]


def test_zapis_taty_zmienia_znacznik_a_widok_niesie_nowy(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    before = _get(centrum, VIEW)["read"]["version"]

    _type_in_excel(centrum.fixture.collective_file_path, "O18", 1)
    changed = _get(centrum, VERSION)["version"]
    view = _get(centrum, VIEW)

    assert changed != before
    assert view["read"]["version"] == changed
    assert _without_rule(view) == [(18, True)]


def test_bez_pliku_zbiorczego_znacznik_jest_pusty(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    centrum.fixture.collective_file_path.unlink()

    assert _get(centrum, VERSION) == {"version": None}


def test_nieudany_odczyt_przez_minute_pokazuje_ostatni_dobry_stan_potem_komunikat(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    good = _get(centrum, VIEW)
    original = path.read_bytes()
    path.write_bytes(b"Excel zapisuje")

    kept = _get(centrum, VIEW)
    still_kept = _polled(centrum, 57)
    shown = _polled(centrum, POLL_S)
    failing_version = _get(centrum, VERSION)["version"]
    path.write_bytes(original)
    back = _get(centrum, VIEW)

    assert kept == {**good, "read": {**good["read"], "retrying": True}}
    assert still_kept == kept
    assert shown["state"] == "problem"
    assert shown["message"]["what"] == "Plik zbiorczy jest uszkodzony albo nie jest skoroszytem Excela."
    # Strona po Komunikacie czyta plik znów dopiero po zmianie tego znacznika.
    assert failing_version is not None
    assert shown["version"] == failing_version
    assert back["state"] == "ready"
    assert back["read"]["retrying"] is False
    assert back["read"]["read_at"] > good["read"]["read_at"]


def test_seria_nieudanych_odczytow_to_jeden_wpis_w_dzienniku(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    original = path.read_bytes()
    path.write_bytes(b"")

    _get(centrum, VIEW)
    assert _polled(centrum, 120)["state"] == "problem"
    path.write_bytes(original)
    _get(centrum, VIEW)
    path.write_bytes(b"")
    _get(centrum, VIEW)

    assert len(_log_lines(centrum)) == 2


def test_blokada_excela_bez_odpowiedzi_systemu_jest_nieznana(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    path.write_bytes(b"to nie jest skoroszyt")
    path.with_name(f"~${path.name}").write_bytes(b"blokada Excela")
    stat = Path.stat

    def denied(self: Path, *, follow_symlinks: bool = True) -> Any:
        # Jak ACL w Windows, której os.access nie widzi: system odmawia odpowiedzi o pliku blokady.
        if self.name.startswith("~$"):
            raise PermissionError(13, "Odmowa dostępu", str(self))
        return stat(self, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", denied)

    assert _get(centrum, VIEW)["state"] == "problem"
    [line] = _log_lines(centrum)
    assert "przyczyna=USZKODZONY_PLIK_ZBIORCZY excel=nieznany typ=BadZipFile" in line


def test_porazka_po_przerwie_i_zapisie_zaczyna_nowa_serie_bez_drugiego_wpisu_tej_samej_przyczyny(
    tmp_path: Path,
) -> None:
    # Tata chowa kartę (albo Excel zasłania przeglądarkę) w trakcie zapisu Excela; plik wraca, ale nikt go nie czyta.
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    good = _get(centrum, VIEW)
    original = path.read_bytes()
    path.write_bytes(b"Excel zapisuje")
    _get(centrum, VIEW)
    path.write_bytes(original)
    _hidden_for(centrum, 30 * 60)

    path.write_bytes(b"Excel zapisuje znowu")
    after_return = _get(centrum, VIEW)

    assert after_return == {**good, "read": {**good["read"], "retrying": True}}
    assert len(_log_lines(centrum)) == 1


def test_inna_przyczyna_po_przerwie_trafia_do_dziennika(tmp_path: Path) -> None:
    # Obie przyczyny bez typu błędu (``typ=-``): dziennik rozróżnia je po kodzie Komunikatu.
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    original = path.read_bytes()
    path.unlink()
    _get(centrum, VIEW)
    _hidden_for(centrum, 24 * 3600)

    path.write_bytes(original)
    workbook = load_workbook(path)
    sheet = workbook.active
    assert isinstance(sheet, Worksheet)
    [header] = (cell for cell in sheet[17] if cell.value == "URZĄDZENIA")
    header.value = None
    workbook.save(path)
    _get(centrum, VIEW)

    assert [line.split(" przyczyna=")[1].split()[0] for line in _log_lines(centrum)] == [
        "BRAK_PLIKU_ZBIORCZEGO", "BRAK_NAGLOWKA_PLIKU_ZBIORCZEGO",
    ]


@pytest.mark.parametrize(("silence", "message"), [(15, True), (16, False)])
def test_cisza_dluzsza_niz_kilka_odstepow_po_zmianie_pliku_zaczyna_nowa_minute(
    tmp_path: Path, silence: int, message: bool
) -> None:
    # Pierwsza porażka w 0 s, druga po ciszy i zapisie, potem strona ponawia co 3 s przez 48 s: ponad minutę od
    # pierwszej porażki, a mniej niż minutę od drugiej.
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    path.write_bytes(b"Excel zapisuje")
    _get(centrum, VIEW)
    _hidden_for(centrum, silence)
    path.write_bytes(b"Excel zapisuje znowu")
    _get(centrum, VIEW)

    after_minute = _polled(centrum, 48)

    assert (after_minute["state"] == "problem") is message


def test_trwala_porazka_ogladana_zrywami_daje_komunikat_po_minucie(tmp_path: Path) -> None:
    # Tata patrzy na stronę 30 s, potem 2 min pisze w Excelu, który zasłania przeglądarkę; plik się nie zmienia.
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    path.write_bytes(b"zepsuty na stale")
    states = [_get(centrum, VIEW)["state"]]
    # Autozapis zapisuje dalej zepsuty plik raz, gdy tata jeszcze patrzy: później znacznik już się nie zmienia.
    centrum.surroundings.clock.advance(minutes=POLL_S / 60)
    path.write_bytes(b"zepsuty na stale po Autozapisie")
    _get(centrum, VIEW)
    for _ in range(3):
        states.append(_polled(centrum, 30)["state"])
        _hidden_for(centrum, 120)

    assert states == ["ready", "ready", "problem", "problem"]
    assert len(_log_lines(centrum)) == 1


def test_bez_dobrego_odczytu_zapisy_zepsutego_pliku_to_jedna_seria(tmp_path: Path) -> None:
    # Bez dobrego odczytu strona od razu pokazuje Komunikat i czyta plik znów dopiero po zapisie taty.
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    path.write_bytes(b"zepsuty od startu Centrum")
    states = [_get(centrum, VIEW)["state"]]
    for save in range(3):
        _hidden_for(centrum, 60)
        path.write_bytes(b"dalej zepsuty" + bytes([save]))
        states.append(_get(centrum, VIEW)["state"])

    assert states == ["problem"] * 4
    assert len(_log_lines(centrum)) == 1


def test_wolny_nieudany_odczyt_daje_komunikat_po_minucie_i_jeden_wpis(tmp_path: Path) -> None:
    # OneDrive przez 13 s pobiera plik tylko w chmurze i nie zdąży, a synchronizacja zmienia jego znacznik między
    # próbami; strona ponawia 3 s po każdej odpowiedzi.
    onedrive = _SlowOneDrive(seconds=13)
    centrum = _prepared(tmp_path, surroundings=Surroundings(onedrive=onedrive))
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    onedrive.clock = centrum.surroundings.clock
    onedrive.online_only.add(path)

    states = []
    for sync in range(4):
        path.write_bytes(bytes(sync))
        states.append(_get(centrum, VIEW)["state"])
        centrum.surroundings.clock.advance(minutes=POLL_S / 60)

    # Próby zaczynają się w 0, 16, 32 i 48 s; czwarta kończy się w 61 s, minutę po początku pierwszej.
    assert states == ["ready", "ready", "ready", "problem"]
    assert len(_log_lines(centrum)) == 1


def test_trwaly_problem_po_komunikacie_zostaje_jedna_seria(tmp_path: Path) -> None:
    # Po Komunikacie strona nie ponawia odczytu, dopóki znacznik się nie zmieni; zapis taty bez naprawy to ta sama seria.
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    path.write_bytes(b"to nie jest skoroszyt")
    _get(centrum, VIEW)
    assert _polled(centrum, 60)["state"] == "problem"
    centrum.surroundings.clock.advance(minutes=10)

    path.write_bytes(b"to dalej nie jest skoroszyt")
    after_save = _get(centrum, VIEW)

    assert after_save["state"] == "problem"
    assert len(_log_lines(centrum)) == 1


def test_po_uruchomieniu_ktore_zmienilo_pliki_okresu_nieudany_odczyt_nie_pokazuje_pliku_sprzed_niego(
    tmp_path: Path,
) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    # Tata usuwa Folder okresu i przygotowuje Plik zbiorczy od nowa; zaraz po zapisie OneDrive go jeszcze trzyma.
    shutil.rmtree(path.parent)
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    path.write_bytes(b"OneDrive synchronizuje")

    view = _get(centrum, VIEW)

    assert view["state"] == "problem"
    assert view["message"]["what"] == "Plik zbiorczy jest uszkodzony albo nie jest skoroszytem Excela."


def test_podglad_bez_zapisu_zostawia_ostatni_dobry_odczyt(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    good = _get(centrum, VIEW)
    run_to_end(centrum, dry_run=True)
    path.write_bytes(b"Excel zapisuje")

    assert _get(centrum, VIEW) == {**good, "read": {**good["read"], "retrying": True}}


def test_po_uruchomieniu_ktore_zmienilo_pliki_okresu_porazka_trafia_do_dziennika_od_nowa(tmp_path: Path) -> None:
    centrum = _prepared(tmp_path)
    path = centrum.fixture.collective_file_path
    _get(centrum, VIEW)
    path.write_bytes(b"Excel zapisuje")
    _get(centrum, VIEW)
    assert len(_log_lines(centrum)) == 1
    shutil.rmtree(path.parent)
    assert run_to_end(centrum, dry_run=False)["result"]["result"] == "WYMAGA_SPRAWDZENIA"
    path.write_bytes(b"OneDrive synchronizuje")

    _get(centrum, VIEW)

    assert len(_log_lines(centrum)) == 2


def test_po_uruchomieniu_z_zapisem_zaden_plik_zbiorczy_nie_pokazuje_odczytu_sprzed_niego(tmp_path: Path) -> None:
    reads: LastGoodReads[str] = LastGoodReads(clock=lambda: 0.0)
    # Tata ogląda Uzupełnienie okresu A, potem okresu B, a potem przygotowuje okres A od nowa.
    files = [tmp_path / "A.xlsx", tmp_path / "B.xlsx"]
    for path in files:
        path.write_bytes(b"zapisany")
        reads.succeeded(path, path.name, reads.attempt(path))

    reads.forget_all()

    assert [reads.failed(path, reads.attempt(path), "USZKODZONY").kept for path in files] == [None, None]
