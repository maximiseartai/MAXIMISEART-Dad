"""Sekcja Legenda czynności okna Ustawień przez HTTP Centrum (ADR 0038, furtka Wydania z ADR 0032).

Oczekiwane zdania pochodzą z maila taty z 15.11.2026 i wartości domyślnych ADR 0038, nie z kodu.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from rozliczenia.activity_legend import ActivityCode, FixedColumn
from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.centrum.settings.activity_legend import LEGEND, LEGEND_FILE, set_codes
from rozliczenia.centrum.settings.proposal import ReleaseChange
from rozliczenia.centrum.settings.release_changes import RELEASE_CHANGES

from tests.fixtures.centrum import CentrumClient, ToolDirectory, centrum, centrum_app
from tests.fixtures.centrum_processes import PERIOD_MONDAY, preparing_centrum, run_to_end
from atrapy.preparation import register_order, write_collective_template
from atrapy.workbooks import active_worksheet

LEGEND_URL = "/api/settings/activity-legend"
RELEASE_LEGEND = Path(__file__).parents[1] / "src" / "rozliczenia" / "legenda_czynnosci_domyslna.yaml"

MAIL_SENTENCES = [
    "inst#m: 1 w Y.",
    "instmdik (też instmdic): 1 w Y.",
    "instutp#m: # od 1 do 15 → 1 w AL, # od 16 do 30 → 1 w AJ.",
    "instwewrg6#m: # od 1 do 10 → 1 w AK, # od 11 do 15 → 1 w AL, # od 16 do 30 → 1 w AJ.",
    "instwew#m: AF na zielono.",
    "rt2: 1 w AM, AM na czerwono, AF na zielono.",
    "bypas#m: 1 w AM.",
    "spawgnd: 1 w AD.",
    "spawpg: 1 w AB, 70 w Uwagi - kwota (AS), AS na czerwono.",
    "spawez: 1 w AB.",
    "spawmufakan: 1 w AB, 70 w Uwagi - kwota (AS).",
    "spawmufaziem: 1 w AC.",
    "dzielnik1/2 (też dzielnika1/2): 50 w Uwagi - kwota (AS).",
    "pz20m: 480 w Uwagi - kwota (AS).",
]
"""Legenda z Wydania bez Wzorca: kolumna Ilości usług to sama litera, a kwota stoi w ``AS`` nazwanej „Uwagi - kwota”."""


def plain(parts: list[dict[str, Any]]) -> str:
    return "".join(
        part["text"] if part["kind"] == "text" else part["letter"] if part["name"] is None else f"{part['name']} ({part['letter']})"
        for part in parts
    )


def legend(client: CentrumClient) -> tuple[dict[str, str], dict[str, Any] | None]:
    """Zdanie każdego kodu sekcji po id i problem pliku."""

    response = client.get(LEGEND_URL)
    assert response.status_code == 200, response.text
    read = response.json()
    return {code["id"]: plain(code["sentence"]) for code in read["codes"]}, read["problem"]


def history(client: CentrumClient) -> list[dict[str, Any]]:
    response = client.get("/api/settings/history")
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["rows"]
    return rows


def started(tool: ToolDirectory, changes: tuple[ReleaseChange[Any], ...]) -> CentrumClient:
    """Centrum uruchomione jak u taty, z Wydaniem, które niesie zmiany Ustawień ``changes``."""

    client = CentrumClient(centrum_app(tool, release_changes=changes))
    client.start()
    return client


def own_code(identifier: str, **changes: Any) -> ActivityCode:
    """Kod legendy z Wydania o id ``identifier`` ze zmienionymi polami."""

    return replace(next(code for code in DEFAULT_ACTIVITY_LEGEND.codes if code.id == identifier), **changes)


def with_own(*codes: ActivityCode) -> bytes:
    """Plik Legendy czynności taty: legenda z Wydania z kodami ``codes`` w miejscu kodów o tym samym id."""

    by_id = {code.id: code for code in codes}
    return LEGEND.dump(tuple(by_id.get(code.id, code) for code in DEFAULT_ACTIVITY_LEGEND.codes))


def test_kazdy_kod_legendy_z_wydania_jest_w_ustawieniach_jednym_zdaniem_a_bez_wzorca_kolumna_to_litera(tmp_path: Path) -> None:
    sentences, problem = legend(centrum(tmp_path).client)

    assert list(sentences.values()) == MAIL_SENTENCES
    assert problem is None


def test_kolumna_kodu_ma_nazwe_pozycji_cennika_z_wiersza_17_wzorca_pliku_zbiorczego(tmp_path: Path) -> None:
    app = centrum(tmp_path)
    app.tool.config.mkdir(parents=True)
    template = write_collective_template(app.tool.configuration.collective_template)
    workbook = load_workbook(template)
    sheet = active_worksheet(workbook)
    sheet["AB17"], sheet["AL17"] = "Spawanie\nw mufie", "UTP do 15 m"
    workbook.save(template)

    sentences, _ = legend(app.client)

    assert sentences["spawpg"] == "spawpg: 1 w Spawanie w mufie (AB), 70 w Uwagi - kwota (AS), AS na czerwono."
    assert sentences["instutp"].startswith("instutp#m: # od 1 do 15 → 1 w UTP do 15 m (AL), # od 16 do 30 → 1 w ")


def test_legenda_zmieniona_poza_centrum_jest_w_historii_jako_zmiana_spoza_centrum_ze_zdaniem_i_da_sie_ja_cofnac(
    tmp_path: Path,
) -> None:
    app = centrum(tmp_path)
    legend(app.client)
    (app.tool.config / LEGEND_FILE).write_bytes(with_own(own_code("inst", column=FixedColumn("AA"), value=2)))

    changed, _ = legend(app.client)
    [row] = history(app.client)
    undone = app.client.post(f"/api/settings/history/{row['id']}/undo")

    assert changed["inst"] == "inst#m: 2 w AA."
    assert (row["source"], row["file"], row["section"], row["undoable"]) == ("outside", LEGEND_FILE, "kody", True)
    assert [(plain(change["before"]), plain(change["after"])) for change in row["rules"]] == [("inst#m: 1 w Y.", "inst#m: 2 w AA.")]
    assert undone.status_code == 200, undone.text
    assert list(legend(app.client)[0].values()) == MAIL_SENTENCES


def test_zla_legenda_to_zle_ustawienie_z_jednym_zdaniem_a_przygotowanie_liczy_ostatnia_dobra(tmp_path: Path) -> None:
    preparing = preparing_centrum(tmp_path, [{**register_order(1, PERIOD_MONDAY), "CZYNNOŚCI ZREALIZOWANE": "inst20m"}])
    path = ToolDirectory(tmp_path).config / LEGEND_FILE
    path.write_bytes(with_own(own_code("inst", column=FixedColumn("AA"), value=2)))
    legend(preparing.client)
    path.write_bytes(with_own(own_code("inst", column=FixedColumn("AA"), value=2), own_code("spawez", spellings=("spawpg",))))

    sentences, problem = legend(preparing.client)
    run_to_end(preparing, dry_run=False)

    assert problem == {
        "field": None,
        "message": f"Plik {LEGEND_FILE} w folderze config: Zapis „spawpg” ma już kod „spawpg”.",
    }
    assert sentences["inst"] == "inst#m: 2 w AA."
    sheet = active_worksheet(load_workbook(preparing.fixture.collective_file_path))
    assert (sheet["AA18"].value, sheet["Y18"].value) == (2, 0), "Przygotowanie liczyło ostatnią dobrą legendą"
    legend_rows = [row for row in history(preparing.client) if row["file"] == LEGEND_FILE]
    assert [(row["source"], row["refused"]) for row in legend_rows] == [("outside", True)]


RT2_IN_AK = ReleaseChange("2026-12-rt2-w-ak", LEGEND, set_codes(own_code("rt2", column=FixedColumn("AK"))))
"""Jawna zmiana legendy w Wydaniu, np. po odpowiedzi taty, że ``rt2`` daje ``AK``."""


def test_jawna_zmiana_legendy_w_wydaniu_wchodzi_raz_jest_w_historii_z_cofnij_i_po_cofnieciu_nie_wraca(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    first = started(tool, (RT2_IN_AK,))
    applied, _ = legend(first)
    [row] = history(first)
    undone = first.post(f"/api/settings/history/{row['id']}/undo")
    first.stop()
    again = started(tool, (RT2_IN_AK,))
    after_restart, _ = legend(again)
    rows = history(again)
    again.stop()

    assert applied["rt2"] == "rt2: 1 w AK, AM na czerwono, AF na zielono."
    assert (row["source"], row["file"], row["undoable"]) == ("release", LEGEND_FILE, True)
    assert [(plain(change["before"]), plain(change["after"])) for change in row["rules"]] == [
        ("rt2: 1 w AM, AM na czerwono, AF na zielono.", "rt2: 1 w AK, AM na czerwono, AF na zielono.")
    ]
    assert undone.status_code == 200, undone.text
    assert after_restart["rt2"] == "rt2: 1 w AM, AM na czerwono, AF na zielono."
    assert [entry["source"] for entry in rows] == ["tata", "release"]


def test_wydanie_bez_jawnej_zmiany_legendy_nie_rusza_legendy_taty(tmp_path: Path) -> None:
    tool = ToolDirectory(tmp_path)
    tool.config.mkdir(parents=True)
    own = with_own(own_code("rt2", column=FixedColumn("AK")))
    (tool.config / LEGEND_FILE).write_bytes(own)

    client = started(tool, RELEASE_CHANGES)
    sentences, _ = legend(client)
    rows = history(client)
    client.stop()

    assert sentences["rt2"] == "rt2: 1 w AK, AM na czerwono, AF na zielono."
    assert (tool.config / LEGEND_FILE).read_bytes() == own
    assert [row for row in rows if row["file"] == LEGEND_FILE] == []


RELEASE_LEGEND_SHA256 = "459f135ac4fba0b1c9ed3e368ec12e5f82b425d2d2063c3bec3a40da2c66a75e"


def test_legenda_z_wydania_zmienia_sie_tylko_jawna_zmiana_w_wydaniu() -> None:
    """Tata bez własnego pliku legendy liczy legendą z Wydania, więc zmiana jej pliku weszłaby u niego bez wiersza
    Historii i bez „Cofnij” (ADR 0032)."""

    assert hashlib.sha256(RELEASE_LEGEND.read_bytes()).hexdigest() == RELEASE_LEGEND_SHA256, (
        "Legendę czynności taty zmienia w Wydaniu tylko wpis ReleaseChange(<id>, LEGEND, set_codes(...)) w "
        "RELEASE_CHANGES (centrum/settings/release_changes.py), nie zmiana legenda_czynnosci_domyslna.yaml. Skrót zmień "
        "tylko wtedy, gdy żadne Wydanie (tag v*) nie niosło jeszcze tego pliku: git tag --contains <commit pliku>."
    )
