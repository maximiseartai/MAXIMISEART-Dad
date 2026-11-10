"""Przywracanie Kopii INTERMAX z Konfiguracji Centrum rozliczeń przez HTTP API, jak widzi je przeglądarka (#472).

Konfiguracja wymienia Kopie INTERMAX od najnowszej z datą i godziną z nazwy, a przywrócenie wybranej najpierw robi
Kopię stanu bieżącego ``INTERMAX przed przywróceniem RRRR-MM-DD GG-MM-SS.xlsx``, potem atomowo podmienia INTERMAX
(ADR 0019). Odmowa zostawia INTERMAX i Kopie takie, jak były.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
import os
import sys
import time
from typing import Any
import zipfile

import pytest

from rozliczenia import intermax_copies

from tests.fixtures.intermax_disk import denied, failing_replace, no_space, partial_copy, writing
from tests.fixtures.centrum_intermax import NOW, REGISTER_NAME, Clock, OrderingCentrum, copies, open_in_excel, ordering_centrum
from tests.fixtures.centrum_processes import preparing_centrum
from tests.fixtures.centrum import ToolDirectory, views_until
from atrapy.preparation import PERIOD, incomplete_period_rows

ORDERED = "INTERMAX przed uporządkowaniem 2026-10-26 14-05-07.xlsx"
LATER = NOW + timedelta(hours=2, minutes=30)
BEFORE_RESTORE = "INTERMAX przed przywróceniem 2026-10-26 16-35-07.xlsx"
UNCHANGED = "INTERMAX nie został zmieniony."


def _name(before: str, moment: datetime) -> str:
    return f"INTERMAX przed {before} {moment:%Y-%m-%d %H-%M-%S}.xlsx"


def _kopie(centrum: OrderingCentrum) -> dict[str, bytes]:
    return {name: (centrum.copies / name).read_bytes() for name in copies(centrum)}


def _listed(centrum: OrderingCentrum) -> dict[str, Any]:
    response = centrum.client.get("/api/intermax/copies")
    assert response.status_code == 200, response.json()
    return dict(response.json())


def _restore(centrum: OrderingCentrum, name: str) -> Any:
    return centrum.client.post("/api/intermax/copies/restore", json={"name": name})


def _refused(centrum: OrderingCentrum, name: str) -> dict[str, str]:
    response = _restore(centrum, name)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["state"] == "refused", body
    return dict(body["message"])


def _ordered(tmp_path: Path) -> OrderingCentrum:
    """Centrum po Uporządkowaniu INTERMAX o 14:05:07 z jego Kopią; zegar procesu stoi dalej na 16:35:07."""

    centrum = ordering_centrum(tmp_path)
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    centrum.clock.moments = [LATER]
    return centrum


def _copies_like_tool(centrum: OrderingCentrum, names: list[str]) -> None:
    centrum.copies.mkdir(exist_ok=True)
    for name in names:
        (centrum.copies / name).write_bytes(f"Kopia {name}".encode())


def test_bez_kopii_intermax_konfiguracja_ma_pusta_liste(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)

    assert _listed(centrum) == {"copies": [], "problem": None}


def test_konfiguracja_wymienia_kopie_obu_nazw_od_najnowszej_z_chwila_i_slowami_z_nazwy(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    earlier = datetime(2026, 10, 20, 9, 0, 0)
    _copies_like_tool(
        centrum,
        [
            _name("uporządkowaniem", earlier),
            _name("przywróceniem", NOW),
            _name("uporządkowaniem", NOW),
            _name("przywróceniem", earlier + timedelta(days=3)),
        ],
    )
    # Pliki, których narzędzie nie robi: inna nazwa i nazwa z nieistniejącą datą.
    for other in ("INTERMAX.xlsx", "INTERMAX przed uporządkowaniem 2026-13-01 10-00-00.xlsx"):
        (centrum.copies / other).write_bytes(b"inny plik")

    listed = _listed(centrum)

    assert listed["problem"] is None
    assert [(copy["name"], copy["before"], copy["before_label"]) for copy in listed["copies"]] == [
        (_name("uporządkowaniem", NOW), "ordering", "przed uporządkowaniem"),
        (_name("przywróceniem", NOW), "restore", "przed przywróceniem"),
        (_name("przywróceniem", earlier + timedelta(days=3)), "restore", "przed przywróceniem"),
        (_name("uporządkowaniem", earlier), "ordering", "przed uporządkowaniem"),
    ]
    assert [datetime.fromisoformat(copy["taken_at"]) for copy in listed["copies"]] == [
        NOW.astimezone(),
        NOW.astimezone(),
        (earlier + timedelta(days=3)).astimezone(),
        earlier.astimezone(),
    ]


def test_chwila_kopii_idzie_do_przegladarki_w_utc_takze_na_komputerze_w_strefie_taty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Schemat przeglądarki przyjmuje tylko chwilę w UTC („Z”); na komputerze w UTC każda chwila tak wygląda.
    if sys.platform == "win32":
        pytest.skip("time.tzset jest tylko w systemach POSIX")
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    time.tzset()
    try:
        centrum = ordering_centrum(tmp_path)
        _copies_like_tool(centrum, [ORDERED])

        listed = _listed(centrum)
    finally:
        monkeypatch.undo()
        time.tzset()

    assert listed["copies"][0]["taken_at"] == "2026-10-26T13:05:07Z"


def test_po_uporzadkowaniu_konfiguracja_wymienia_jego_kopie(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)

    assert [copy["name"] for copy in _listed(centrum)["copies"]] == [ORDERED]


def test_folderu_kopii_ktorego_nie_da_sie_odczytac_konfiguracja_nazywa_a_przywrocenie_odmawia(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path)
    centrum.copies.write_bytes(b"")  # plik zamiast folderu Kopii
    before = centrum.register.read_bytes()

    listed = _listed(centrum)
    refused = _refused(centrum, ORDERED)

    expected = {
        "what": f"Nie można teraz odczytać folderu Kopii INTERMAX. {UNCHANGED}",
        "where": f"folder {tmp_path.name}\\Kopie INTERMAX",
        "action": (
            "Odśwież Konfigurację za chwilę. Jeśli błąd wraca, przekaż ten komunikat osobie utrzymującej narzędzie."
        ),
    }
    assert listed == {"copies": [], "problem": expected}
    assert refused == expected
    assert centrum.register.read_bytes() == before


def test_przywrocona_kopia_jest_intermax_bajt_w_bajt_a_stan_sprzed_przywrocenia_nowa_kopia(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    ordered_register = centrum.register.read_bytes()
    kopia = (centrum.copies / ORDERED).read_bytes()

    response = _restore(centrum, ORDERED)

    assert response.status_code == 200
    body = response.json()
    assert (body["state"], body["restored"]["name"], body["warnings"]) == ("restored", ORDERED, [])
    assert centrum.register.read_bytes() == kopia
    assert _kopie(centrum) == {ORDERED: kopia, BEFORE_RESTORE: ordered_register}
    newest, _ = _listed(centrum)["copies"]
    assert [copy["name"] for copy in _listed(centrum)["copies"]] == [BEFORE_RESTORE, ORDERED]
    assert (newest["before"], datetime.fromisoformat(newest["taken_at"])) == ("restore", LATER.astimezone())
    assert [path.name for path in centrum.register.parent.iterdir()] == [REGISTER_NAME]


def test_przywrocenie_mozna_cofnac_przywracajac_kopie_stanu_sprzed_przywrocenia(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    ordered_register = centrum.register.read_bytes()
    assert _restore(centrum, ORDERED).json()["state"] == "restored"
    centrum.clock.moments = [LATER + timedelta(minutes=1)]

    undone = _restore(centrum, BEFORE_RESTORE)

    assert undone.json()["state"] == "restored"
    assert centrum.register.read_bytes() == ordered_register
    assert len(copies(centrum)) == 3


def test_limit_dziesieciu_kopii_obejmuje_obie_nazwy_wedlug_chwili_z_nazwy(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    # Najstarsza jest Kopia przed uporządkowaniem, choć po nazwie „przed przywróceniem” stoi wcześniej w alfabecie.
    oldest = _name("uporządkowaniem", datetime(2026, 10, 1, 8, 0, 0))
    older = [_name("przywróceniem", datetime(2026, 10, day, 8, 0, 0)) for day in range(2, 11)]
    _copies_like_tool(centrum, [oldest, *older])

    restored = _restore(centrum, ORDERED)

    assert restored.json()["state"] == "restored"
    assert copies(centrum) == sorted([*older[1:], ORDERED, BEFORE_RESTORE])
    assert len(copies(centrum)) == 10


def test_gdy_starszych_kopii_nie_da_sie_usunac_przywrocenie_konczy_sie_ostrzezeniem(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    kopia = (centrum.copies / ORDERED).read_bytes()
    stuck = _name("uporządkowaniem", datetime(2026, 9, 1, 8, 0, 0))
    (centrum.copies / stuck).mkdir()  # najstarszej „Kopii” system nie usunie jak pliku
    _copies_like_tool(centrum, [_name("przywróceniem", datetime(2026, 10, day, 8, 0, 0)) for day in range(1, 10)])

    body = _restore(centrum, ORDERED).json()

    assert body["state"] == "restored"
    assert [warning["what"] for warning in body["warnings"]] == [
        "Kopia została przywrócona, ale nie udało się usunąć starszych Kopii INTERMAX."
    ]
    assert centrum.register.read_bytes() == kopia
    assert stuck in copies(centrum)


def test_przywrocenie_odmawia_przy_otwartym_intermax_i_niczego_nie_zmienia(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)
    open_in_excel(centrum.register)

    refused = _refused(centrum, ORDERED)

    assert refused == {
        "what": f"INTERMAX jest otwarty w Excelu. {UNCHANGED}",
        "where": f"plik {REGISTER_NAME}, folder OneDrive",
        "action": (
            "Zapisz i zamknij INTERMAX w Excelu, potem przywróć kopię jeszcze raz. Jeśli Excel jest zamknięty, a "
            f"komunikat wraca, usuń z tego samego folderu pozostawiony plik ~${REGISTER_NAME} i przywróć kopię jeszcze raz."
        ),
    }
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


@dataclass
class OpeningClock(Clock):
    """Zegar procesu, przy którego pytaniu tata otwiera INTERMAX ``opened`` w Excelu (``None``: nie otwiera)."""

    opened: Path | None = None

    def __call__(self) -> datetime:
        if self.opened is not None:
            open_in_excel(self.opened)
        return super().__call__()


def test_intermax_otwarty_w_excelu_w_chwili_kopii_stanu_biezacego_to_odmowa_bez_nowej_kopii(tmp_path: Path) -> None:
    clock = OpeningClock()
    centrum = ordering_centrum(tmp_path, clock=clock)
    assert centrum.run_to_end()["result"]["ending"] == "finished"
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)
    clock.opened = centrum.register

    refused = _refused(centrum, ORDERED)

    assert refused["what"] == f"INTERMAX jest otwarty w Excelu. {UNCHANGED}"
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


def test_nieudana_kopia_stanu_biezacego_niczego_nie_podmienia(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)
    centrum.disk.create = partial_copy

    refused = _refused(centrum, ORDERED)

    assert refused == {
        "what": f"Nie udało się zrobić Kopii obecnego INTERMAX, więc kopia nie została przywrócona. {UNCHANGED}",
        "where": f"folder {tmp_path.name}\\Kopie INTERMAX",
        "action": (
            "Sprawdź, czy na dysku jest wolne miejsce, potem przywróć kopię jeszcze raz. Jeśli błąd wraca, przekaż "
            "ten komunikat osobie utrzymującej narzędzie."
        ),
    }
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


def test_drugie_przywrocenie_w_tej_samej_sekundzie_mowi_ze_kopie_przywrocono_przed_chwila(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    assert _restore(centrum, ORDERED).json()["state"] == "restored"
    centrum.clock.moments = [LATER]  # druga karta przywraca w tej samej sekundzie zegara
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)

    refused = _refused(centrum, BEFORE_RESTORE)

    assert refused == {
        "what": "Przed chwilą przywrócono już kopię INTERMAX, więc ta kopia nie została przywrócona.",
        "where": f"folder {tmp_path.name}\\Kopie INTERMAX",
        "action": "Odśwież Konfigurację i sprawdź listę kopii. Jeśli nadal trzeba, przywróć kopię jeszcze raz.",
    }
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


@pytest.mark.parametrize(
    "name",
    [
        "INTERMAX przed uporządkowaniem 2026-10-01 08-00-00.xlsx",
        f"../OneDrive/{REGISTER_NAME}",
        "INTERMAX.xlsx",
    ],
    ids=["usunieta", "sciezka-poza-folderem", "nie-kopia"],
)
def test_przywrocenie_kopii_ktorej_lista_nie_wymienia_odmawia(tmp_path: Path, name: str) -> None:
    centrum = _ordered(tmp_path)
    (centrum.copies / "INTERMAX.xlsx").write_bytes(b"inny plik")
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)

    refused = _refused(centrum, name)

    assert refused == {
        "what": f"Tej Kopii INTERMAX już nie ma. {UNCHANGED}",
        "where": f"folder {tmp_path.name}\\Kopie INTERMAX, {name}",
        "action": "Odśwież Konfigurację i wybierz kopię z listy.",
    }
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


def _zip_without_workbook(*, relationship: bool = False) -> bytes:
    """Zip bez dokumentu skoroszytu; ``relationship``: relacje paczki wskazują go, ale części nie ma."""

    archive = BytesIO()
    with zipfile.ZipFile(archive, "w") as written:
        written.writestr("[Content_Types].xml", "<Types/>")
        if relationship:
            written.writestr(
                "_rels/.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
                'officeDocument" Target="xl/workbook.xml"/></Relationships>',
            )
        written.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return archive.getvalue()


@pytest.mark.parametrize(
    "damaged",
    [b"to nie jest skoroszyt", _zip_without_workbook(), _zip_without_workbook(relationship=True)],
    ids=["nie-zip", "zip-bez-skoroszytu", "relacja-do-brakujacej-czesci"],
)
def test_uszkodzona_kopia_nie_jest_przywracana(tmp_path: Path, damaged: bytes) -> None:
    centrum = _ordered(tmp_path)
    (centrum.copies / ORDERED).write_bytes(damaged)
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)

    refused = _refused(centrum, ORDERED)

    assert refused == {
        "what": f"Ta Kopia INTERMAX jest uszkodzona, więc nie została przywrócona. {UNCHANGED}",
        "where": f"plik {ORDERED}, folder Kopie INTERMAX",
        "action": "Wybierz inną kopię z listy.",
    }
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


def _with_workbook_in(content: bytes, part: str) -> bytes:
    """Skoroszyt ``content`` z dokumentem skoroszytu w części ``part`` zamiast ``xl/workbook.xml``: relacje paczki go
    wskazują, więc to dalej skoroszyt, tylko zapisany inaczej niż przez Excel."""

    renamed = {"xl/workbook.xml": part, "xl/_rels/workbook.xml.rels": f"xl/_rels/{part.rsplit('/', 1)[1]}.rels"}
    archive = BytesIO()
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as written:
        for info in source.infolist():
            data = source.read(info)
            if info.filename in ("_rels/.rels", "[Content_Types].xml"):
                data = data.replace(b"/xl/workbook.xml", f"/{part}".encode()).replace(b'"xl/workbook.xml"', f'"{part}"'.encode())
            written.writestr(renamed.get(info.filename, info.filename), data)
    return archive.getvalue()


def test_kopia_z_dokumentem_skoroszytu_w_innej_czesci_jest_przywracana(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    kopia = _with_workbook_in((centrum.copies / ORDERED).read_bytes(), "xl/skoroszyt.xml")
    (centrum.copies / ORDERED).write_bytes(kopia)

    response = _restore(centrum, ORDERED)

    assert response.json()["state"] == "restored", response.json()
    assert centrum.register.read_bytes() == kopia


def test_kopia_usunieta_miedzy_lista_a_odczytem_to_komunikat_ze_jej_juz_nie_ma(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = _ordered(tmp_path)
    before = centrum.register.read_bytes()
    listed = intermax_copies.listed

    def deleted_after_listing(directory: Path) -> list[intermax_copies.Copy]:
        found = listed(directory)
        (directory / ORDERED).unlink(missing_ok=True)  # np. tata usuwa ją w Eksploratorze
        return found

    monkeypatch.setattr(intermax_copies, "listed", deleted_after_listing)

    refused = _refused(centrum, ORDERED)

    assert refused == {
        "what": f"Tej Kopii INTERMAX już nie ma. {UNCHANGED}",
        "where": f"folder {tmp_path.name}\\Kopie INTERMAX, {ORDERED}",
        "action": "Odśwież Konfigurację i wybierz kopię z listy.",
    }
    assert (centrum.register.read_bytes(), copies(centrum)) == (before, [])


def test_kopia_otwarta_w_excelu_nie_jest_przywracana(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    before = centrum.register.read_bytes()
    lock = open_in_excel(centrum.copies / ORDERED)

    refused = _refused(centrum, ORDERED)

    assert refused == {
        "what": f"Ta Kopia INTERMAX jest otwarta w Excelu. {UNCHANGED}",
        "where": f"plik {ORDERED}, folder Kopie INTERMAX",
        "action": (
            "Zamknij ją w Excelu bez zapisywania zmian, potem przywróć kopię jeszcze raz. Jeśli Excel jest zamknięty, a "
            f"komunikat wraca, usuń z tego samego folderu pozostawiony plik {lock.name} i przywróć kopię jeszcze raz."
        ),
    }
    assert centrum.register.read_bytes() == before
    assert copies(centrum) == sorted([ORDERED, lock.name])


def test_bez_intermax_pod_sciezka_z_ustawien_przywrocenie_odmawia_i_nie_tworzy_pliku(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    centrum.register.unlink()

    refused = _refused(centrum, ORDERED)

    assert refused == {
        "what": f"Nie znaleziono INTERMAX. {UNCHANGED}",
        "where": f"plik {REGISTER_NAME}, folder OneDrive",
        "action": "Wybierz w Ustawieniach właściwy plik INTERMAX, potem przywróć kopię jeszcze raz.",
    }
    assert not centrum.register.exists()
    assert copies(centrum) == [ORDERED]


def test_bez_wskazanego_intermax_przywrocenie_jest_odrzucone(tmp_path: Path) -> None:
    centrum = ordering_centrum(tmp_path, chosen=False)
    _copies_like_tool(centrum, [ORDERED])

    refused = _restore(centrum, ORDERED)

    assert (refused.status_code, refused.json()) == (409, {"message": "Najpierw wskaż INTERMAX."})


def test_gdy_onedrive_trzyma_intermax_przywrocenie_mowi_o_synchronizacji_i_zostawia_kopie_jak_byly(
    tmp_path: Path,
) -> None:
    centrum = _ordered(tmp_path)
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)
    centrum.disk.replace, attempts = failing_replace(denied)
    started_at = centrum.surroundings.clock.seconds

    refused = _refused(centrum, ORDERED)

    assert refused["what"] == f"OneDrive jeszcze synchronizuje INTERMAX. {UNCHANGED}"
    assert (len(attempts), centrum.surroundings.clock.seconds - started_at) == (11, 5.0)
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)
    assert [path.name for path in centrum.register.parent.iterdir()] == [REGISTER_NAME]


def test_intermax_otwarty_w_excelu_w_chwili_podmiany_to_odmowa_bez_nowej_kopii(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)
    # Windows odmawia podmiany pliku, który trzyma Excel.
    centrum.disk.replace, _ = failing_replace(denied, before=lambda: open_in_excel(centrum.register))

    refused = _refused(centrum, ORDERED)

    assert refused["what"] == f"INTERMAX jest otwarty w Excelu. {UNCHANGED}"
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


def test_nieudany_zapis_obok_intermax_to_odmowa_bez_nowej_kopii(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)
    centrum.disk.replace, _ = failing_replace(no_space)

    refused = _refused(centrum, ORDERED)

    assert refused == {
        "what": f"Nie udało się przywrócić kopii. {UNCHANGED}",
        "where": f"plik {REGISTER_NAME}, folder OneDrive",
        "action": (
            "Sprawdź, czy na dysku jest wolne miejsce, potem przywróć kopię jeszcze raz. Jeśli błąd wraca, przekaż "
            "ten komunikat osobie utrzymującej narzędzie."
        ),
    }
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)


def test_plik_obok_intermax_z_innymi_bajtami_niz_kopia_to_odmowa_bez_podmiany_i_nowej_kopii(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    before, kopie = centrum.register.read_bytes(), _kopie(centrum)
    # Zapis obok INTERMAX gubi ostatni bajt (pełny dysk, antywirus, OneDrive), a odczyt pliku się udaje.
    centrum.disk.write = writing(lambda data: data[:-1])

    refused = _refused(centrum, ORDERED)

    assert refused["what"] == f"Nie udało się przywrócić kopii. {UNCHANGED}"
    assert (centrum.register.read_bytes(), _kopie(centrum)) == (before, kopie)
    assert [path.name for path in centrum.register.parent.iterdir()] == [REGISTER_NAME]


def test_w_trakcie_przywracania_uruchomienie_zamkniecie_i_drugie_przywrocenie_sa_odrzucone(tmp_path: Path) -> None:
    """Także Wpisanie raportów, które pisze do tego samego INTERMAX, nie startuje w trakcie przywracania."""

    centrum = _ordered(tmp_path)
    # Wpisanie raportów bez pliku adresów odmawia startu, zanim zapyta o miejsce „jedno naraz”.
    ToolDirectory(tmp_path).configuration.worker_addresses.touch()
    during: dict[str, Any] = {}

    def replacing(source: Path, target: Path) -> None:
        if not during:
            during["run"] = centrum.client.post("/api/intermax/run")
            during["report_entering"] = centrum.client.post("/api/report-entering/run")
            during["shutdown"] = centrum.client.post("/api/shutdown")
            during["restore"] = _restore(centrum, ORDERED)
        os.replace(source, target)

    centrum.disk.replace = replacing

    restored = _restore(centrum, ORDERED)
    after = centrum.client.post("/api/intermax/run")

    busy = "Trwa przywracanie Kopii INTERMAX. Poczekaj na jego wynik, potem"
    assert restored.json()["state"] == "restored"
    assert {action: (response.status_code, response.json()) for action, response in during.items()} == {
        "run": (409, {"message": f"{busy} uruchom proces."}),
        "report_entering": (409, {"message": f"{busy} uruchom proces."}),
        "shutdown": (409, {"message": f"{busy} zamknij Centrum rozliczeń."}),
        "restore": (409, {"message": f"{busy} przywróć kopię jeszcze raz."}),
    }
    assert after.status_code == 200
    views_until(centrum.client, "finished")


def test_przywrocenie_w_trakcie_uruchomienia_procesu_jest_odrzucone(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    centrum.start(dry_run=False)
    waiting = views_until(centrum.client, "awaiting_decision")[-1]

    refused = centrum.client.post("/api/intermax/copies/restore", json={"name": ORDERED})
    centrum.client.post(f"/api/runs/{waiting['run']['id']}/decision", json={"answer": "abort"})

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "message": (
                f"Trwa Uruchomienie procesu: Przygotowanie pliku zbiorczego, okres {PERIOD}. "
                "Poczekaj na jego wynik w Uruchomieniach, potem przywróć kopię jeszcze raz."
            )
        },
    )


def test_po_przyjetym_zamknieciu_centrum_przywrocenie_jest_odrzucone(tmp_path: Path) -> None:
    centrum = _ordered(tmp_path)
    before = centrum.register.read_bytes()
    assert centrum.client.post("/api/shutdown").status_code == 202

    refused = _restore(centrum, ORDERED)

    assert (refused.status_code, refused.json()) == (
        409,
        {
            "message": (
                "Centrum rozliczeń się zamyka. Kliknij skrót „Centrum rozliczeń” na pulpicie, potem przywróć kopię "
                "jeszcze raz."
            )
        },
    )
    assert centrum.register.read_bytes() == before
