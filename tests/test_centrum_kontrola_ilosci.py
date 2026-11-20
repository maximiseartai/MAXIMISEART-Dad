from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import threading
from dataclasses import replace
from typing import Any, Final, NamedTuple

from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import pytest

from rozliczenia.activity_legend_file import DEFAULT_ACTIVITY_LEGEND
from rozliczenia.centrum import refusal
from rozliczenia.centrum.settings.activity_legend import LEGEND, LEGEND_FILE
from rozliczenia.worker_periods import InRegister
from rozliczenia.centrum.outbox import Outbox, Post
from rozliczenia.centrum.report_box import Refused, Sent, Unreachable
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.history import HISTORY_FILE
from rozliczenia.centrum.settings.owner import CentrumSettings, KeptInPeriods
from rozliczenia.centrum.settings.quantity_exceptions import EXCEPTIONS_FILE
from rozliczenia.centrum.settings.quantity_rules import DEVICES_FILE, RULES_FILE

from atrapy.skrzynka import BoxIssue
from tests.fixtures.centrum import (
    REPORT_KEY,
    TOOL_COMMIT,
    FakeReportBox,
    ToolDirectory,
    finished_view,
    without_times,
    write_report_key,
)
from tests.fixtures.centrum_processes import (
    TODAY,
    SettlingCentrum,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
    write_dad_quantity_rules,
)
from tests.fixtures.bez_dostepu import without_reading
from tests.fixtures.odczyt_bez_dostepu import reading
from tests.fixtures.potomne import wait_for
from tests.fixtures.zegar_scienny import MOMENTS, STEP, wall_clock_from
from atrapy import pliki_taty
from atrapy.settlement import MARKED, CellValue, PERIOD, write_quantity_source

LABEL: Final = "kontrola-ilosci"
LINE = f"- Kontrola ilości okresu: {PERIOD}"

TUE, WED, THU, FRI, MON = (datetime(2026, 9, day) for day in (8, 9, 10, 11, 14))

AGREED = "zgodny-z-regula-a-zera-wzorca-w-n-q-x-to-puste"
LATE_FAULT = "usterka-w-piatek-przed-17-bez-dodatku-a-tata-45-w-n"
TATA_CASES: Final[dict[str, dict[str, CellValue]]] = {
    AGREED: {"C": "u", "D": "nokia zte", "E": "instalacja", "G": TUE.replace(hour=10, minute=15),
             "V": 1, "T": 1, "O": 1, "Z": 1, "S": 1, "N": 0, "Q": 0, "X": 0},
    "q-2-z-reguly-przy-trzech-fut-z-routerem-tata-1-pierwszy-wiersz-grupy-tej-samej-godziny": {
        "C": "u", "D": "nokia zte 3*fut", "E": "instalacja", "G": TUE.replace(hour=10, minute=5),
        "V": 1, "T": 1, "O": 1, "Z": 1, "P": 1, "Q": 1, "S": 4},
    "q-2-z-reguly-przy-trzech-fut-z-routerem-tata-1-drugi-wiersz-grupy-tej-samej-godziny": {
        "C": "u", "D": "nokia zte 3*fut", "E": "instalacja", "G": TUE.replace(hour=10, minute=40),
        "V": 1, "T": 1, "O": 1, "Z": 1, "P": 1, "Q": 1, "S": 4},
    LATE_FAULT: {"C": "pr", "D": "usterka", "G": FRI.replace(hour=16, minute=30), "V": 1, "AI": 1, "N": 45},
    "ak-1-z-reguly-porownane-a-tata-0": {"C": "pr", "D": "technicolor", "G": WED.replace(hour=12), "V": 1, "O": 1, "Z": 1, "S": 1},
    "ak-z-reguly-wpisane-przez-tate-zgodne-wiec-nie-jest-kolumna-z-opisu": {
        "C": "pr", "D": "technicolor", "G": WED.replace(hour=15), "V": 1, "O": 1, "Z": 1, "S": 1, "AK": 1},
    "ak-taty-bez-reguly-liczy-sie-jak-kolumna-z-opisu-razem-z-y": {
        "C": "pr", "D": "nokia", "G": WED.replace(hour=13), "V": 1, "Z": 1, "AK": 1, "Y": 1},
    "samo-nokia-z-akt-int-w-czynnosciach-ma-o-1-z-reguly-zgodne-z-tata": {
        "C": "pr", "D": "nokia", "E": "AKT INT", "G": WED.replace(hour=16), "V": 1, "Z": 1, "O": 1},
    "bez-reguly-roznica-tylko-w-v-a-o-to-wartosc-taty": {"C": "u", "D": "przeniesienie", "G": MON.replace(hour=9), "T": 1, "O": 1},
    "bez-reguly-slowo-w-am-to-nieliczbowa-i-kolumna-z-opisu": {
        "C": "u", "D": "przeniesienie", "G": MON.replace(hour=9, minute=30), "V": 1, "T": 1, "AM": "dwa"},
    "rozliczany-z-opisu-bez-porownania-a-ab-taty-to-kolumna-z-opisu": {"C": "u", "D": "prewencja", "G": THU.replace(hour=8), "AB": 2},
    "data-zmieniona-przez-tate-na-tekst-bez-porownania": {"C": "pr", "D": "nokia", "G": "wtorek", "V": 1, "Z": 1},
    "liczba-tekstem-i-float-rowny-liczbie-to-ta-liczba-a-r-to-pozostala-kolumna-n-ap": {
        "C": "pr", "D": "gniazdo", "G": THU.replace(hour=11), "V": "1", "AE": 1.0, "AP": 1, "R": 3},
    "ulamek-i-formula-to-nieliczbowa": {"C": "pr", "D": "fut", "G": THU.replace(hour=14), "V": 1, "Q": 1.5, "S": "=1+1"},
}
TATA_ROWS: Final = list(TATA_CASES.values())


def tata_rows_with(case: str, **cells: CellValue) -> list[dict[str, CellValue]]:
    return [{**row, **cells} if name == case else dict(row) for name, row in TATA_CASES.items()]

DIFFERENCES_HEADER = (
    "| Kolumna | Reguła | Tata | CZYNNOŚCI | UMOWA | Dzień, godzina | Wiersze |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)


def expected_body(run_id: str) -> str:
    return (
        f"{LINE}\n"
        "\n"
        "Kontrola ilości z Centrum rozliczeń: Reguły ilości przeliczone na Pliku zbiorczym, "
        "z którego tata uruchomił Przebieg rozliczeń.\n"
        "\n"
        "- Wiersze danych: 14 (porównane 10, rozliczane z opisu 1, bez reguły 2, bez daty i godziny w DATA 1)\n"
        "- Różnice w kolumnach Reguł ilości: 7\n"
        "- Wiersze z Kodami czynności: 0 (zgodne z legendą 0), różnice legendy: 0, wiersze z Błędem opisu: 0\n"
        "\n"
        "## Różnice\n"
        "\n"
        "### URZĄDZENIA `fut`\n"
        "\n"
        f"{DIFFERENCES_HEADER}"
        "| Q | 1 | nieliczbowa | (puste) | `pr` | czw 14 | 1 |\n"
        "| S | 1 | nieliczbowa | (puste) | `pr` | czw 14 | 1 |\n"
        "\n"
        "### URZĄDZENIA `nokia zte 3*fut`\n"
        "\n"
        f"{DIFFERENCES_HEADER}"
        "| Q | 2 | 1 | `instalacja` | `u` | wt 10 | 2 |\n"
        "\n"
        "### URZĄDZENIA `technicolor`\n"
        "\n"
        f"{DIFFERENCES_HEADER}"
        "| AK | 1 | 0 | (puste) | `pr` | śr 12 | 1 |\n"
        "\n"
        "### URZĄDZENIA `usterka`\n"
        "\n"
        f"{DIFFERENCES_HEADER}"
        "| N | 0 | 45 | (puste) | `pr` | pt 16 | 1 |\n"
        "\n"
        "## Wiersze bez reguły\n"
        "\n"
        "### URZĄDZENIA `przeniesienie` (wiersze: 2)\n"
        "\n"
        f"{DIFFERENCES_HEADER}"
        "| V | 1 | 0 | (puste) | `u` | pon 9 | 1 |\n"
        "\n"
        "| Kolumna | Wartość taty | Wiersze |\n"
        "| --- | --- | --- |\n"
        "| O | 1 | 1 |\n"
        "| AM | nieliczbowa | 1 |\n"
        "\n"
        "## Wiersze bez kodu z wpisem taty\n"
        "\n"
        "| Opis | Wpis taty | Wiersze |\n"
        "| --- | --- | --- |\n"
        "| (puste) | AB 2 | 1 |\n"
        "| (puste) | AM nieliczbowa | 1 |\n"
        "| (puste) | Y 1, AK 1 | 1 |\n"
        "\n"
        "## Kolumny z opisu technika: wiersze wypełnione przez tatę\n"
        "\n"
        "| Y | AB | AD | AJ | AK | AL | AM |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 1 | 1 | 0 | 0 | 1 | 0 | 1 |\n"
        "\n"
        "## Pozostałe kolumny N:AP: wiersze wypełnione przez tatę\n"
        "\n"
        "| R | U | W | X | AA | AC | AF | AH |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |\n"
        "\n"
        "## Narzędzie\n"
        "\n"
        f"- Wersja narzędzia (commit): {TOOL_COMMIT}\n"
        f"- Uruchomienie: {run_id}\n"
    )


def centrum_with(tmp_path: Path, rows: list[dict[str, CellValue]], *, key: bool = True) -> SettlingCentrum:
    centrum = settling_centrum(tmp_path)
    write_quantity_source(centrum.collective_file, rows)
    if key:
        write_report_key(ToolDirectory(tmp_path))
    return centrum


def box(centrum: SettlingCentrum) -> FakeReportBox:
    return centrum.surroundings.report_box


def queued_checks(centrum: SettlingCentrum) -> list[Path]:
    return sorted(centrum.tool.queue.glob(f"*-{LABEL}-*.json"))


def sent_check(centrum: SettlingCentrum) -> BoxIssue:
    assert box(centrum).wait_until(lambda fake: bool(fake.issues_with(LABEL))), "Kontrola ilości nie dotarła"
    [issue] = box(centrum).issues_with(LABEL)
    return issue


def test_przebieg_z_poprawkami_taty_daje_kontrole_ilosci_z_grupami_roznic_i_liczbami(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)

    view = run_to_end(centrum, dry_run=False)

    assert view["result"]["result"] == "OK"
    issue = sent_check(centrum)
    assert (issue.label, issue.title) == (LABEL, f"Kontrola ilości {PERIOD}: 7 różnic")
    assert issue.body == expected_body(view["run"]["id"])
    assert box(centrum).keys == [REPORT_KEY]
    sent = f"skrzynka-wyslano etykieta={LABEL} okres={PERIOD} numer=1"
    assert wait_for(lambda: sent in centrum.log_path.read_text(encoding="utf-8"))


def test_przy_zera_roznic_kontrola_ilosci_tez_powstaje_z_tytulem_bez_roznic(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [TATA_CASES[AGREED]])

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    assert issue.title == f"Kontrola ilości {PERIOD}: bez różnic"
    assert "- Różnice w kolumnach Reguł ilości: 0\n" in issue.body
    assert "## Różnice" not in issue.body


def test_kontrola_ilosci_liczy_regulami_ilosci_z_ustawien_ktorymi_liczyl_jej_przebieg(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [TATA_CASES[AGREED]])
    rule = "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia-router}"
    write_dad_quantity_rules(centrum.tool, RULES_FILE, rule, rule.replace("wartosc: 1", "wartosc: 2"))

    run_to_end(centrum, dry_run=False)

    body = sent_check(centrum).body
    assert "- Różnice w kolumnach Reguł ilości: 1\n" in body
    assert "| Z | 2 | 1 | `instalacja` | `u` | wt 10 | 1 |\n" in body


def test_plik_zbiorczy_bez_naglowka_kolumny_wejscia_daje_kontrole_bez_porownania(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(ToolDirectory(tmp_path))

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    assert issue.title == f"Kontrola ilości {PERIOD}: bez porównania"
    assert "nie ma nagłówka UMOWA, URZĄDZENIA, CZYNNOŚCI, DATA" in issue.body


FORBIDDEN = (
    "ZNACZNIK-MIASTO",
    "ZNACZNIK-ADRES",
    "ZNACZNIK-NUMER-ZL",
    "ZNACZNIK-NUMER-UMOWY",
    "ZNACZNIK-ZREALIZOWANE",
    "ZNACZNIK-AQ",
    "ZNACZNIK-AR",
    "ZNACZNIK-AS",
    "ZNACZNIK-AT",
    "ZNACZNIK-ILOSC",
    "adrian.testowy",
    "Adrian Testowy",
    "2026-09-09",
    "09.09.2026",
    "09.09",
    "13:45",
)
ALLOWED = ("ZNACZNIK-UMOWA", "ZNACZNIK-URZADZENIA", "ZNACZNIK-CZYNNOSCI")
CLOCK_START_WITHOUT_FORBIDDEN = datetime.combine(TODAY, time(12, 7), timezone.utc)


def test_kontrola_ilosci_nie_ma_adresu_numerow_wykonawcy_daty_ani_opisu_technika_wiersza_bez_wpisu_taty(
    tmp_path: Path,
) -> None:
    without_code_or_dad_entry = {**MARKED, "AS": None}
    centrum = centrum_with(tmp_path, [without_code_or_dad_entry])

    view = run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    sent = issue.title + issue.body + "".join(issue.comments)
    assert [marker for marker in FORBIDDEN if marker in sent] == []
    assert all(marker in sent for marker in ALLOWED)
    assert "| V | 1 | nieliczbowa | `ZNACZNIK-CZYNNOSCI` | `u ZNACZNIK-UMOWA` | śr 13 | 1 |" in sent
    assert wait_for(lambda: queued_checks(centrum) == [])
    seen_by_tata = [
        json.dumps(view),
        centrum.client.get("/api/runs/current").text,
        centrum.client.get("/api/metrics?process=settlement").text,
        centrum.log_path.read_text(encoding="utf-8"),
        centrum.metrics_path.read_text(encoding="utf-8"),
        *(path.read_text(encoding="utf-8") for path in (tmp_path / "config").glob("*.json*")),
    ]
    assert [marker for marker in ALLOWED if any(marker in text for text in seen_by_tata)] == []


def test_adres_numer_orange_telefon_i_ulica_wpisane_w_urzadzenia_i_czynnosci_wychodza_zamaskowane_z_uwaga(
    tmp_path: Path,
) -> None:
    address, orange = "Syntetyczna Malachitowa 3/1", "4807654321"
    typed = {**MARKED, "D": f"nokia {address.lower()} {orange}", "E": "tel. 600-123-456 ul. Kwiatowa 5"}
    centrum = centrum_with(tmp_path, [{**MARKED, "B": address, "I": orange}, typed])

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    sent = issue.title + issue.body + "".join(issue.comments)
    leaked = (address.lower(), orange, "600-123-456", "ul. Kwiatowa 5")
    assert [value for value in leaked if value in sent] == []
    assert "`nokia [adres] [numer Orange]`" in sent and "`tel. [telefon] [ulica]`" in sent
    assert sent.endswith(
        "## Uwagi techniczne\n\n"
        "- Reguła danych: zamaskowano wartość kolumny ADRES w: treść Kontroli ilości.\n"
        "- Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: treść Kontroli ilości.\n"
    )


@pytest.mark.parametrize(
    ("forbidden", "typed", "shown", "column"),
    [
        ({"B": "Syntetyczna Malachitowa 3/1"}, "klient Syntetyczna\nMalachitowa 3/1 dzwonić", "`klient [adres] dzwonić`", "ADRES"),
        ({"I": "1-SYN|4321"}, "umowa 1-SYN|4321 aktywna", "`umowa [numer Orange] aktywna`", "NUMER UMOWY/ZLECENIA ORANGE"),
    ],
    ids=["adres-w-dwoch-liniach", "numer-orange-z-kreska"],
)
def test_wartosc_zakazanej_kolumny_w_komorce_ktora_tabela_kontroli_zapisuje_inaczej_wychodzi_zamaskowana(
    tmp_path: Path, forbidden: dict[str, CellValue], typed: str, shown: str, column: str
) -> None:
    centrum = centrum_with(tmp_path, [{**MARKED, **forbidden}, {**MARKED, "E": typed}])

    view = run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    sent_without_random_run_id = (issue.title + issue.body + "".join(issue.comments)).replace(view["run"]["id"], "")
    assert shown in sent_without_random_run_id
    assert ("Malachitowa" in sent_without_random_run_id, "4321" in sent_without_random_run_id) == (False, False)
    assert sent_without_random_run_id.endswith(f"## Uwagi techniczne\n\n- Reguła danych: zamaskowano wartość kolumny {column} w: treść Kontroli ilości.\n")


def test_wartosc_adresu_rowna_slowom_tytulu_kontroli_ilosci_jest_zamaskowana_takze_w_tytule(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [{**MARKED, "B": "Kontrola ilości"}])

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    assert issue.title.startswith(f"[adres] {PERIOD}: ")
    assert issue.body.startswith(f"{LINE}\n")
    assert "- Reguła danych: zamaskowano wartość kolumny ADRES w: tytuł Kontroli ilości.\n" in issue.body


def test_wynik_przebiegu_jest_ten_sam_przy_kazdej_odpowiedzi_skrzynki(tmp_path: Path) -> None:
    without_key = centrum_with(tmp_path / "bez-klucza", TATA_ROWS, key=False)
    expected = run_to_end(without_key, dry_run=False)["result"]
    [expected_record] = without_key.metric_records()
    results, records = [], []
    for answer in (Sent(1), Refused(), Unreachable()):
        centrum = centrum_with(tmp_path / type(answer).__name__, TATA_ROWS)
        box(centrum).outcomes.append(answer)
        results.append(without_times(run_to_end(centrum, dry_run=False)["result"]))
        [record] = centrum.metric_records()
        records.append(without_times(record))

    assert (expected["technical_notes"], expected["warnings"]) == ([], [])
    assert results == [without_times(expected)] * 3
    assert records == [without_times(expected_record)] * 3


def test_logi_uruchomienia_ida_do_kolejki_wysylki_przed_kontrola_ilosci_wiec_centrum_zgasle_w_kontroli_ich_nie_zabiera(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    queued: list[str] = []
    post = Outbox.post

    def queueing(outbox: Outbox, sent: Post) -> bool:
        queued.append(sent.target.label)
        return post(outbox, sent)

    monkeypatch.setattr(Outbox, "post", queueing)

    run_to_end(centrum, dry_run=False)
    sent_check(centrum)

    assert queued == ["logi-uruchomienia", LABEL]


def test_wysylka_w_tle_nie_trzyma_miejsca_uruchomienia_ani_zamkniecia_centrum(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    fake = box(centrum)
    fake.open_hold = hold = threading.Event()

    run_to_end(centrum, dry_run=False)
    assert fake.opening.wait(30), "wysyłka w tle nie zaczęła pytać skrzynki"

    again = centrum.start(dry_run=True)
    assert again.status_code == 200, again.json()
    assert finished_view(centrum.client)["run"]["id"] == again.json()["run"]["id"]
    assert centrum.client.post("/api/shutdown").status_code == 202
    hold.set()
    sent_check(centrum)


AGREED_WITH_RULES: dict[str, CellValue] = {"C": "u", "D": "nokia zte", "E": "instalacja", "G": TUE.replace(hour=10, minute=15),
                               "V": 1, "T": 1, "O": 1, "Z": 1, "S": 1}
LEGEND_CASES: Final[dict[str, dict[str, CellValue]]] = {
    "zgodny-z-legenda-wiec-opis-nie-wychodzi": {**AGREED_WITH_RULES, "K": "Inst20m tak", "Y": 1},
    "spawpg-z-wartosciami-legendy-bez-czerwonego-as": {**AGREED_WITH_RULES, "K": "spawpg", "AB": 1, "AS": 70},
    "rt2-z-ak-taty-zamiast-am-i-samym-zielonym-af-pierwszy": {**AGREED_WITH_RULES, "K": "rt2", "AK": 1},
    "rt2-z-ak-taty-zamiast-am-i-samym-zielonym-af-drugi": {**AGREED_WITH_RULES, "K": "rt2", "AK": 1},
    "blad-opisu-instutp-z-liczba-spoza-przedzialow-z-aj-taty": {**AGREED_WITH_RULES, "K": "instutp40m", "AJ": 1},
    "bez-kodu-i-wpisu-taty-wiec-opis-nie-wychodzi": {**AGREED_WITH_RULES, "K": "montaż gniazda"},
    "bez-kodu-z-kwota-taty-w-as": {**AGREED_WITH_RULES, "K": "listwy", "AS": 220},
    "tekst-w-as-wychodzi-jako-nieliczbowa-a-nie-tekst": {**AGREED_WITH_RULES, "K": "kwota tekstem", "AS": "ZNACZNIK-KWOTA"},
    "bez-wpisu-taty-wiec-opis-nie-wychodzi": {**AGREED_WITH_RULES, "K": "ZNACZNIKBEZWPISU"},
    "bez-kodu-i-bledu-opisu-z-y-taty": {**AGREED_WITH_RULES, "K": "tak", "Y": 1},
}
LEGEND_ROWS: Final = list(LEGEND_CASES.values())
GREEN, RED = "FF92D050", "FFFF0000"


def fill_cells(path: Path, argb_by_address: dict[str, str]) -> None:
    workbook = load_workbook(path)
    try:
        sheet = workbook.active
        assert sheet is not None
        for address, argb in argb_by_address.items():
            sheet[address].fill = PatternFill(patternType="solid", fgColor=argb)
        workbook.save(path)
    finally:
        workbook.close()


def legend_centrum(tmp_path: Path, rows: list[dict[str, CellValue]]) -> SettlingCentrum:
    centrum = centrum_with(tmp_path, rows)
    fill_cells(centrum.collective_file, {"AF20": GREEN, "AF21": GREEN})
    return centrum


def test_kontrola_ilosci_grupuje_roznice_legendy_po_kodzie_z_opisem_technika_kwota_i_kolorem(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    sent = issue.title + issue.body + "".join(issue.comments)
    assert issue.title == f"Kontrola ilości {PERIOD}: 7 różnic"
    assert "- Wiersze z Kodami czynności: 4 (zgodne z legendą 1), różnice legendy: 7, wiersze z Błędem opisu: 1\n" in sent
    assert (
        "\n## Różnice legendy\n"
        "\n### Kody `rt2`\n\n"
        "| Kolumna | Legenda | Tata | Wiersze | Opisy |\n| --- | --- | --- | --- | --- |\n"
        "| AK | 0 | 1 | 2 | `rt2` (2) |\n"
        "| AM | 1 | 0 | 2 | `rt2` (2) |\n"
        "| AM kolor | czerwony | brak | 2 | `rt2` (2) |\n"
        "\n### Kody `spawpg`\n\n"
        "| Kolumna | Legenda | Tata | Wiersze | Opisy |\n| --- | --- | --- | --- | --- |\n"
        "| AS kolor | czerwony | brak | 1 | `spawpg` |\n"
        "\n## Błędy opisu\n\n"
        "| Powód | Wiersze |\n| --- | --- |\n"
        "| kod z liczbą spoza przedziałów (instutp40m) | 1 |\n"
        "\n### Błędy opisu z wpisem taty\n\n"
        "| Opis | Powód | Wpis taty | Wiersze |\n| --- | --- | --- | --- |\n"
        "| `instutp40m` | kod z liczbą spoza przedziałów (instutp40m) | AJ 1 | 1 |\n"
        "\n## Wiersze bez kodu z wpisem taty\n\n"
        "| Opis | Wpis taty | Wiersze |\n| --- | --- | --- |\n"
        "| `kwota tekstem` | AS nieliczbowa | 1 |\n"
        "| `listwy` | AS 220 | 1 |\n"
        "| `tak` | Y 1 | 1 |\n"
    ) in sent
    assert "- Różnice w kolumnach Reguł ilości: 0\n" in sent
    assert [marker for marker in ("Inst20m", "montaż", "ZNACZNIKBEZWPISU", "ZNACZNIK-KWOTA") if marker in sent] == []
    assert [text for text in ("listwy", "montaż") if text in centrum.log_path.read_text(encoding="utf-8")] == []


def test_kontrola_ilosci_liczy_legenda_czynnosci_z_ustawien_ktora_liczyl_jej_przebieg(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [{**AGREED_WITH_RULES, "K": "spawpg", "AB": 1, "AS": 70}])
    fill_cells(centrum.collective_file, {"AS18": RED})
    own = tuple(replace(code, amount=80) if code.id == "spawpg" else code for code in DEFAULT_ACTIVITY_LEGEND.codes)
    (centrum.tool.config / LEGEND_FILE).write_bytes(LEGEND.dump(own))

    run_to_end(centrum, dry_run=False)

    body = sent_check(centrum).body
    assert "- Wiersze z Kodami czynności: 1 (zgodne z legendą 0), różnice legendy: 1, wiersze z Błędem opisu: 0\n" in body
    assert "| AS | 80 | 70 | 1 | `spawpg` |\n" in body


def test_kolumne_regul_ilosci_w_ktora_wpisala_tez_legenda_kontrola_porownuje_z_suma_regul_i_legendy_a_podglad_jak_roznice_regul(
    tmp_path: Path,
) -> None:
    technicolor: dict[str, CellValue] = {"C": "pr", "D": "technicolor", "G": WED.replace(hour=12), "V": 1, "O": 1, "Z": 1, "S": 1, "K": "instwewrg65m"}
    centrum = centrum_with(tmp_path, [{**technicolor, "AK": 2}, {**technicolor, "AK": 1}])

    run_to_end(centrum, dry_run=False)
    preview = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})

    assert (preview["differences_before"], preview["differences_after"]) == (1, 1)
    body = sent_check(centrum).body
    assert "- Różnice w kolumnach Reguł ilości: 0\n" in body
    assert "- Wiersze z Kodami czynności: 2 (zgodne z legendą 1), różnice legendy: 1, wiersze z Błędem opisu: 0\n" in body
    assert "| AK | 2 | 1 | 1 | `instwewrg65m` |\n" in body


def test_kod_obok_zwyklego_opisu_kontrola_porownuje_z_legenda_a_wiersz_bez_kodu_nie_jest_bledem_opisu(tmp_path: Path) -> None:
    centrum = centrum_with(
        tmp_path,
        [{**AGREED_WITH_RULES, "K": "spawpg, wymiana gniazda ZNACZNIKOPISU", "AB": 1, "AS": 70}, {**AGREED_WITH_RULES, "K": "montaż gniazda", "Y": 1}],
    )
    fill_cells(centrum.collective_file, {"AS18": RED})

    run_to_end(centrum, dry_run=False)

    body = sent_check(centrum).body
    assert "- Wiersze z Kodami czynności: 1 (zgodne z legendą 1), różnice legendy: 0, wiersze z Błędem opisu: 0\n" in body
    assert "## Błędy opisu" not in body
    assert (
        "\n## Wiersze bez kodu z wpisem taty\n\n| Opis | Wpis taty | Wiersze |\n| --- | --- | --- |\n"
        "| `montaż gniazda` | Y 1 | 1 |\n"
    ) in body
    assert "ZNACZNIKOPISU" not in body


def test_w_wierszu_bez_reguly_kolumna_wpisana_legenda_nie_jest_wartoscia_taty(tmp_path: Path) -> None:
    unruled: dict[str, CellValue] = {"C": "u", "D": "przeniesienie", "G": MON.replace(hour=9), "V": 1, "T": 1, "Y": 1}
    centrum = centrum_with(tmp_path, [{**unruled, "K": "inst20m", "O": 1}, {**unruled, "K": "Podłączyłem lokal, inst20m"}])

    run_to_end(centrum, dry_run=False)

    body = sent_check(centrum).body
    assert (
        "\n### URZĄDZENIA `przeniesienie` (wiersze: 2)\n"
        "\n| Kolumna | Wartość taty | Wiersze |\n| --- | --- | --- |\n"
        "| O | 1 | 1 |\n"
        "\n## "
    ) in body


def test_kolumne_z_opisu_technika_wpisana_legenda_kontrola_nie_liczy_jako_wypelniona_przez_tate(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [{**AGREED_WITH_RULES, "K": "inst20m", "Y": 1}, {**AGREED_WITH_RULES, "Y": 1}])

    run_to_end(centrum, dry_run=False)

    body = sent_check(centrum).body
    assert (
        "## Kolumny z opisu technika: wiersze wypełnione przez tatę\n\n"
        "| Y | AB | AD | AJ | AK | AL | AM |\n| --- | --- | --- | --- | --- | --- | --- |\n"
        "| 1 | 0 | 0 | 0 | 0 | 0 | 0 |\n"
    ) in body


def test_adres_numer_orange_telefon_i_ulica_w_opisie_technika_wychodza_zamaskowane_z_uwaga(tmp_path: Path) -> None:
    address, orange = "Syntetyczna Malachitowa 3/1", "4807654321"
    described = {**AGREED_WITH_RULES, "K": f"klient {address} umowa {orange} tel. 600-123-456 ul. Kwiatowa 5", "Y": 1}
    centrum = centrum_with(tmp_path, [{**AGREED_WITH_RULES, "B": address, "I": orange}, described])

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    sent = issue.title + issue.body + "".join(issue.comments)
    assert [value for value in (address, orange, "600-123-456", "Kwiatowa") if value in sent] == []
    assert "| `klient [adres] umowa [numer Orange] tel. [telefon] [ulica]` | Y 1 | 1 |\n" in sent
    assert sent.endswith(
        "## Uwagi techniczne\n\n"
        "- Reguła danych: zamaskowano wartość kolumny ADRES w: treść Kontroli ilości.\n"
        "- Reguła danych: zamaskowano wartość kolumny NUMER UMOWY/ZLECENIA ORANGE w: treść Kontroli ilości.\n"
    )


def test_podglad_i_zatrzymanie_nie_tworza_kontroli_ilosci(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)

    preview = run_to_end(centrum, dry_run=True)
    write_quantity_source(centrum.collective_file, [*TATA_ROWS, {"H": "andrzej.nieznany2"}])
    stopped = run_to_end(centrum, dry_run=False)

    assert preview["result"]["ending"] == "finished"
    assert stopped["result"]["ending"] == "stop"
    assert queued_checks(centrum) == []
    assert box(centrum).keys == []
    assert f"etykieta={LABEL}" not in centrum.log_path.read_text(encoding="utf-8")


def repeated(centrum: SettlingCentrum) -> dict[str, Any]:
    shutil.rmtree(centrum.worker_settlements)
    view = run_to_end(centrum, dry_run=False)
    assert view["result"]["result"] == "OK"
    return view


def test_powtorzony_przebieg_okresu_dopisuje_kontrole_jako_komentarz_do_otwartego_issue_okresu(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    first = sent_check(centrum)

    second = repeated(centrum)

    assert box(centrum).wait_until(lambda fake: bool(first.comments)), "druga Kontrola ilości nie dotarła"
    assert [issue.number for issue in box(centrum).issues_with(LABEL)] == [first.number]
    assert first.comments == [expected_body(second["run"]["id"]).removeprefix(f"{LINE}\n\n")]
    assert wait_for(lambda: queued_checks(centrum) == [])


def test_gdy_maks_zamknal_issue_okresu_powtorzony_przebieg_zaklada_nowe(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    first = sent_check(centrum)
    box(centrum).close(first.number)

    second = repeated(centrum)

    assert box(centrum).wait_until(lambda fake: len(fake.issues_with(LABEL)) == 2), "nowe issue okresu nie powstało"
    newer = box(centrum).issues_with(LABEL)[1]
    assert newer.body == expected_body(second["run"]["id"])
    assert first.comments == []


def test_kontrola_ilosci_nie_trafia_do_issue_innego_okresu_ani_innej_etykiety(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    foreign = [
        BoxIssue(1, LABEL, "Kontrola ilości 01_07_09_2026: bez różnic", "- Kontrola ilości okresu: 01_07_09_2026\n"),
        BoxIssue(2, LABEL, f"Kontrola ilości {PERIOD}0", f"- Kontrola ilości okresu: {PERIOD}0\n"),
        BoxIssue(3, "zgloszenie", "BRAK_WZORCA: Nie znaleziono wzorca.", f"## Komunikat\n\n{LINE}\n"),
        BoxIssue(4, "logi-uruchomienia", f"Logi {PERIOD}", f"{LINE}\n"),
    ]
    box(centrum).issues.extend(foreign)

    view = run_to_end(centrum, dry_run=False)

    assert box(centrum).wait_until(lambda fake: len(fake.issues) == 5), "Kontrola ilości nie dotarła"
    assert box(centrum).issues[4].body == expected_body(view["run"]["id"])
    assert [issue.comments for issue in foreign] == [[], [], [], []]


def passes_waiting_for_network(centrum: SettlingCentrum) -> int:
    waiting = f"skrzynka-czeka etykieta={LABEL} okres={PERIOD} przyczyna=brak-sieci"
    return centrum.log_path.read_text(encoding="utf-8").count(waiting)


def test_kontrola_ilosci_bez_sieci_czeka_w_kolejce_i_wychodzi_przy_nastepnym_starcie_centrum(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    box(centrum).search_failure = Unreachable()

    view = run_to_end(centrum, dry_run=False)

    assert wait_for(lambda: passes_waiting_for_network(centrum) >= 1)
    assert view["result"]["result"] == "OK"
    assert view["result"]["technical_notes"] == [] and view["result"]["warnings"] == []
    [waiting] = queued_checks(centrum)
    assert list(ToolDirectory(tmp_path).queue.parent.iterdir()) == [ToolDirectory(tmp_path).queue]

    before_start = passes_waiting_for_network(centrum)
    centrum.restart()
    with centrum.client:
        assert wait_for(lambda: passes_waiting_for_network(centrum) > before_start)
        assert centrum.client.get("/api/runs/current").json()["state"] == "idle"
    assert queued_checks(centrum) == [waiting]
    assert box(centrum).issues == []

    box(centrum).search_failure = None
    centrum.restart()
    with centrum.client:
        issue = sent_check(centrum)

    assert issue.body == expected_body(view["run"]["id"])
    assert wait_for(lambda: queued_checks(centrum) == [])
    assert list(ToolDirectory(tmp_path).queue.parent.glob("Zgłoszenie *.md")) == []


def test_logi_i_kontrola_ilosci_jednego_przebiegu_czekaja_razem_i_przy_starcie_wychodza_obie(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    box(centrum).background = frozenset()
    box(centrum).search_failure = Unreachable()
    folder = ToolDirectory(tmp_path).queue

    view = run_to_end(centrum, dry_run=False)

    assert wait_for(lambda: "przyczyna=brak-sieci" in centrum.log_path.read_text(encoding="utf-8"))
    assert wait_for(lambda: len(queued_checks(centrum)) == 1 and bool(list(folder.glob("*-logi-uruchomienia-*.json"))))

    box(centrum).search_failure = None
    centrum.restart()
    with centrum.client:
        issue = sent_check(centrum)
        assert box(centrum).wait_until(lambda fake: bool(fake.issues_with("logi-uruchomienia"))), "Logi nie dotarły"
        assert wait_for(lambda: sorted(folder.glob("*.json")) == [])

    assert issue.body == expected_body(view["run"]["id"])
    [logs] = box(centrum).issues_with("logi-uruchomienia")
    assert [view["run"]["id"] in comment for comment in logs.comments] == [True]


def network_back_only_in_restarted_centrum_with_held_opening(centrum: SettlingCentrum) -> threading.Event:
    centrum.restart()
    box(centrum).open_hold = hold = threading.Event()
    box(centrum).opening.clear()
    box(centrum).search_failure = None
    return hold


def test_ponowienie_przy_starcie_nie_opoznia_startu_centrum(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    box(centrum).search_failure = Unreachable()
    run_to_end(centrum, dry_run=False)
    assert wait_for(lambda: passes_waiting_for_network(centrum) >= 1)
    hold = network_back_only_in_restarted_centrum_with_held_opening(centrum)

    start_off_test_thread = threading.Thread(target=centrum.client.__enter__, daemon=True)
    start_off_test_thread.start()
    try:
        start_off_test_thread.join(10)
        started_while_held = not start_off_test_thread.is_alive()
        asked = box(centrum).opening.wait(30)
        health = centrum.client.get("/api/health") if started_while_held else None
    finally:
        hold.set()
        start_off_test_thread.join(30)
    try:
        issue = sent_check(centrum)
    finally:
        centrum.client.__exit__(None, None, None)

    assert started_while_held, "start Centrum czekał na skrzynkę"
    assert asked, "ponowienie przy starcie nie zapytało skrzynki"
    assert health is not None and health.status_code == 200
    assert issue.title == f"Kontrola ilości {PERIOD}: 7 różnic"


RULES_URL = "/api/settings/quantity-rules"
NOKIA_Z_ONCE: dict[str, Any] = {
    "scope": "known",
    "conditions": [{"kind": "component", "component": "nokia", "negated": False}],
    "action": {"kind": "fill", "writes": [{"column": "Z", "value": 1, "multiplier": "once", "component": None}]},
}


def previewed(centrum: SettlingCentrum, edit: dict[str, Any]) -> dict[str, Any]:
    response = centrum.client.post(f"{RULES_URL}/preview", json=edit)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def rule_form(centrum: SettlingCentrum, rule_id: str) -> dict[str, Any]:
    form: dict[str, Any] = next(rule["rule"] for rule in centrum.client.get(RULES_URL).json()["rules"] if rule["id"] == rule_id)
    return form


def test_podglad_reguly_liczy_roznice_tym_samym_rachunkiem_co_kontrola_ilosci_przebiegu_z_ta_regula(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    first = sent_check(centrum)

    preview = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})
    assert centrum.client.post(RULES_URL, json=NOKIA_Z_ONCE).status_code == 200
    repeated(centrum)

    assert box(centrum).wait_until(lambda fake: bool(first.comments)), "druga Kontrola ilości nie dotarła"
    assert first.title == f"Kontrola ilości {PERIOD}: {preview['differences_before']} różnic"
    assert f"- Różnice w kolumnach Reguł ilości: {preview['differences_after']}\n" in first.comments[0]
    assert (preview["differences_before"], preview["differences_after"], preview["changed"], preview["changed_as_tata"]) == (
        7,
        9,
        2,
        0,
    )


def test_podglad_pokazuje_wiersze_z_roznica_od_taty_z_suma_dwoch_regul_w_jednej_kolumnie(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)

    preview = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})

    nokia = "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz liczbę „nokia” w Z."
    added = "Jeśli URZĄDZENIA zawierają „nokia”, to wpisz 1 w Z."
    assert "".join(part.get("text", part.get("letter", "")) for part in preview["sentence"]) == added
    assert preview["files"] == [{"period": PERIOD, "rows": len(TATA_ROWS)}]
    shown = [
        (
            row["row"],
            row["devices"],
            row["activities"],
            row["when"],
            [(cell["column"], cell["before"], cell["after"], cell["tata"]) for cell in row["cells"]],
            [
                (total["column"], total["total"], ["".join(part.get("text", part.get("letter", "")) for part in rule["sentence"]) for rule in total["rules"]])
                for total in row["sums"]
            ],
        )
        for row in preview["rows"]
    ]
    assert shown == [
        (24, "nokia", "", "śr 13", [("Z", 1, 2, 1)], [("Z", 2, [nokia, added])]),
        (25, "nokia", "AKT INT", "śr 16", [("Z", 1, 2, 1)], [("Z", 2, [nokia, added])]),
    ]
    assert preview["more"] == 0


def test_podglad_liczy_wiersze_ktore_po_zmianie_beda_tak_jak_wpisal_tata(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    late_fault = rule_form(centrum, "dodatek-usterka-pn-pt")
    late_fault["conditions"][1]["since"] = "16:00"

    preview = previewed(centrum, {"kind": "change", "rule_id": "dodatek-usterka-pn-pt", "rule": late_fault})

    assert (preview["changed"], preview["changed_as_tata"], preview["rows"]) == (1, 1, [])
    assert (preview["differences_before"], preview["differences_after"]) == (7, 6)


def test_podglad_bez_okresu_po_przebiegu_rozliczen_nie_ma_na_czym_policzyc_a_zdanie_reguly_ma(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)

    preview = previewed(centrum, {"kind": "remove", "rule_id": "t-umowa-u"})

    assert preview == {"state": "no_settled_periods", "sentence": None}


def test_podglad_pomija_plik_zbiorczy_ktorego_nie_da_sie_przeczytac_i_nazywa_jego_okres(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    centrum.collective_file.write_bytes(b"to nie jest skoroszyt")

    preview = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})

    assert (preview["state"], preview["files"], preview["unread"], preview["changed"]) == ("ready", [], [PERIOD], 0)


def test_podglad_nie_ma_adresu_numeru_zlecenia_umowy_wykonawcy_ani_daty_dziennej(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [MARKED])
    run_to_end(centrum, dry_run=False)
    contract_rule = rule_form(centrum, "t-umowa-u")
    contract_rule["action"]["writes"][0]["value"] = 2

    response = centrum.client.post(
        f"{RULES_URL}/preview", json={"kind": "change", "rule_id": "t-umowa-u", "rule": contract_rule}
    ).text

    assert [marker for marker in (*FORBIDDEN, "ZNACZNIK-UMOWA") if marker in response] == []
    assert all(marker in response for marker in ("ZNACZNIK-URZADZENIA", "ZNACZNIK-CZYNNOSCI"))


def test_kolejny_podglad_nie_czyta_pliku_zbiorczego_od_nowa_dopoki_jego_znacznik_zapisu_sie_nie_zmieni(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    first = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})

    with reading(centrum.collective_file) as unchanged:
        again = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})
    saved = centrum.collective_file.stat()
    os.utime(centrum.collective_file, ns=(saved.st_atime_ns, saved.st_mtime_ns + 1_000_000_000))
    with reading(centrum.collective_file) as touched:
        after_save = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})

    assert (again, unchanged.seen) == (first, set())
    assert (after_save, touched.seen != set()) == (first, True)


def test_podglad_bierze_cztery_najnowsze_okresy_po_przebiegu_rozliczen_od_najnowszego(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    for token in ("25_31_08_2026", "01_07_09_2026", "15_21_09_2026", "22_28_09_2026"):
        settled_copy(centrum, token)

    preview = previewed(centrum, {"kind": "add", "rule": NOKIA_Z_ONCE})

    assert [file["period"] for file in preview["files"]] == ["22_28_09_2026", "15_21_09_2026", PERIOD, "01_07_09_2026"]
    assert (preview["changed"], preview["differences_before"]) == (2 * 4, 7 * 4)


def test_podglad_liczy_wiersz_ktory_zmiana_reguly_tylko_zostawia_pusty_w_rozliczeniu_pracownika(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    leave_v_empty = {
        "scope": "every",
        "conditions": [{"kind": "activities", "text": "akt int", "negated": False}],
        "action": {"kind": "leave_empty", "columns": ["V"]},
    }

    preview = previewed(centrum, {"kind": "add", "rule": leave_v_empty})

    assert (preview["changed"], preview["changed_as_tata"], preview["rows"]) == (1, 1, [])
    assert (preview["differences_before"], preview["differences_after"]) == (7, 7)


LEGEND_URL = "/api/settings/activity-legend"


def legend_previewed(centrum: SettlingCentrum, edit: dict[str, Any]) -> dict[str, Any]:
    response = centrum.client.post(f"{LEGEND_URL}/preview", json=edit)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def code_form(centrum: SettlingCentrum, code_id: str) -> dict[str, Any]:
    form: dict[str, Any] = next(code["code"] for code in centrum.client.get(LEGEND_URL).json()["codes"] if code["id"] == code_id)
    return form


def shown_legend_rows(preview: dict[str, Any]) -> list[tuple[Any, ...]]:
    return [
        (
            row["row"],
            row["description"],
            row["codes"],
            row["problems"],
            [(cell["kind"], cell["column"], cell["legend"], cell["tata"]) for cell in row["cells"]],
        )
        for row in preview["rows"]
    ]


def legend_saved(centrum: SettlingCentrum, edit: dict[str, Any]) -> dict[str, Any]:
    if edit["kind"] == "add":
        response = centrum.client.post(LEGEND_URL, json=edit["code"])
    elif edit["kind"] == "change":
        response = centrum.client.put(f"{LEGEND_URL}/{edit['code_id']}", json=edit["code"])
    else:
        response = centrum.client.delete(f"{LEGEND_URL}/{edit['code_id']}")
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


class LegendPreviewCounts(NamedTuple):
    differences_before: int
    differences_after: int
    errors_before: int
    errors_after: int
    changed: int
    changed_as_tata: int


LEGEND_EDITS: Final[dict[str, tuple[Callable[[SettlingCentrum], dict[str, Any]], LegendPreviewCounts]]] = {
    "zmiana-kwoty-spawpg-na-80-gdy-tata-wpisal-70-a-instutp40m-zostaje-bledem-opisu": (
        lambda centrum: {"kind": "change", "code_id": "spawpg", "code": code_form(centrum, "spawpg") | {"amount": 80}},
        LegendPreviewCounts(7, 8, 1, 1, 1, 0),
    ),
    "nowy-kod-listwy-daje-220-w-as-jak-tata-wiec-wiersz-ma-kod": (
        lambda centrum: {"kind": "add", "code": {"spellings": ["listwy"], "column": None, "value": 1, "amount": 220, "fills": [], "counts_in_fault": True}},
        LegendPreviewCounts(7, 7, 1, 1, 1, 1),
    ),
    "usuniecie-inst-zostawia-inst20m-tak-bez-kodu-i-bledu-opisu-z-y-taty": (
        lambda centrum: {"kind": "remove", "code_id": "inst"},
        LegendPreviewCounts(7, 7, 1, 1, 1, 0),
    ),
    "przedzial-instutp-do-40-daje-aj-jak-tata-wiec-instutp40m-bez-bledu-opisu": (
        lambda centrum: {
            "kind": "change",
            "code_id": "instutp",
            "code": code_form(centrum, "instutp")
            | {"column": {"kind": "ranges", "ranges": [{"low": 1, "high": 15, "column": "AL"}, {"low": 16, "high": 40, "column": "AJ"}]}},
        },
        LegendPreviewCounts(7, 7, 1, 0, 1, 1),
    ),
}


@pytest.mark.parametrize("kind", LEGEND_EDITS)
def test_podglad_legendy_kazdej_zmiany_liczy_roznice_ktore_kontrola_ilosci_da_po_jej_zapisie(tmp_path: Path, kind: str) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    run_to_end(centrum, dry_run=False)
    first = sent_check(centrum)
    build, expected = LEGEND_EDITS[kind]
    edit = build(centrum)

    preview = legend_previewed(centrum, edit)
    saved = legend_saved(centrum, edit)
    repeated(centrum)

    assert saved["change"] is not None
    assert box(centrum).wait_until(lambda fake: bool(first.comments)), "druga Kontrola ilości nie dotarła"
    assert f"różnice legendy: {preview['differences_before']}, wiersze z Błędem opisu: {preview['errors_before']}\n" in first.body
    assert f"różnice legendy: {preview['differences_after']}, wiersze z Błędem opisu: {preview['errors_after']}\n" in first.comments[0]
    assert LegendPreviewCounts(*(preview[name] for name in LegendPreviewCounts._fields)) == expected


def test_podglad_legendy_pokazuje_wiersz_z_roznica_od_taty_z_opisem_technika_kwota_i_kolorem(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    run_to_end(centrum, dry_run=False)

    preview = legend_previewed(centrum, {"kind": "change", "code_id": "spawpg", "code": code_form(centrum, "spawpg") | {"amount": 80}})

    assert preview["files"] == [{"period": PERIOD, "rows": len(LEGEND_ROWS)}]
    assert shown_legend_rows(preview) == [
        (19, "spawpg", ["spawpg"], [], [("value", "AS", 80, 70), ("fill", "AS", "czerwony", None)]),
    ]
    assert preview["more"] == 0


def test_podglad_legendy_liczy_wiersze_ktore_po_zmianie_beda_tak_jak_wpisal_tata(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    run_to_end(centrum, dry_run=False)
    rt2_as_tata = code_form(centrum, "rt2") | {"column": {"kind": "fixed", "column": "AK"}, "fills": [{"column": "AF", "colour": "zielony"}]}

    preview = legend_previewed(centrum, {"kind": "change", "code_id": "rt2", "code": rt2_as_tata})

    assert (preview["changed"], preview["changed_as_tata"], preview["rows"]) == (2, 2, [])
    assert (preview["differences_before"], preview["differences_after"]) == (7, 1)


def test_podglad_legendy_liczy_zmiane_samych_kolorow_kodu_jako_zmieniony_wiersz(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    run_to_end(centrum, dry_run=False)
    spawpg_as_tata_without_red_as = code_form(centrum, "spawpg") | {"fills": []}

    preview = legend_previewed(centrum, {"kind": "change", "code_id": "spawpg", "code": spawpg_as_tata_without_red_as})

    assert (preview["changed"], preview["changed_as_tata"], preview["rows"]) == (1, 1, [])
    assert (preview["differences_before"], preview["differences_after"]) == (7, 6)


def test_podglad_legendy_pokazuje_wpis_taty_w_wierszu_ktory_po_usunieciu_kodu_jest_bez_kodu(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    run_to_end(centrum, dry_run=False)

    preview = legend_previewed(centrum, {"kind": "remove", "code_id": "inst"})

    assert (preview["changed"], preview["changed_as_tata"]) == (1, 0)
    assert shown_legend_rows(preview) == [(18, "Inst20m tak", [], [], [("value", "Y", 0, 1)])]


def test_podglad_legendy_pokazuje_wiersz_ktory_po_zmianie_ma_blad_opisu_z_powodem_i_wpisem_taty(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [{**AGREED_WITH_RULES, "K": "inst20m bypas5m", "Y": 1, "AM": 1}])
    run_to_end(centrum, dry_run=False)
    bypas = code_form(centrum, "bypas") | {"column": {"kind": "fixed", "column": "Y"}}

    preview = legend_previewed(centrum, {"kind": "change", "code_id": "bypas", "code": bypas})

    assert (preview["errors_before"], preview["errors_after"], preview["changed"], preview["changed_as_tata"]) == (0, 1, 1, 0)
    assert shown_legend_rows(preview) == [
        (18, "inst20m bypas5m", [], ["kolumna Ilości usług trafiona drugi raz (Y: inst, bypas)"], [("value", "Y", 0, 1), ("value", "AM", 0, 1)])
    ]


def test_podglad_legendy_odmawia_tym_samym_zdaniem_przy_polu_co_zapis_bez_zapisu(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    run_to_end(centrum, dry_run=False)
    taken = {"spellings": ["rt2"], "column": None, "value": 1, "amount": 10, "fills": [], "counts_in_fault": True}

    previewed = centrum.client.post(f"{LEGEND_URL}/preview", json={"kind": "add", "code": taken})
    unknown = centrum.client.post(f"{LEGEND_URL}/preview", json={"kind": "remove", "code_id": "nie-ma-takiego"})
    added = centrum.client.post(LEGEND_URL, json=taken)

    assert (previewed.status_code, previewed.json()) == (added.status_code, added.json())
    assert previewed.status_code == 422
    assert unknown.status_code == 404
    assert not (centrum.tool.config / LEGEND_FILE).exists()


@pytest.mark.parametrize("unreadable", [RULES_FILE, DEVICES_FILE])
def test_podglad_legendy_przy_pliku_pary_regul_ilosci_bez_odczytu_to_409_o_tym_pliku_a_nie_podglad_regulami_z_wydania(
    tmp_path: Path, unreadable: str
) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    rule = "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia-router}"
    write_dad_quantity_rules(centrum.tool, RULES_FILE, rule, rule.replace("wartosc: 1", "wartosc: 2"))
    write_dad_quantity_rules(centrum.tool, DEVICES_FILE, "nokia-router", "nokia-router")
    run_to_end(centrum, dry_run=False)

    with without_reading(centrum.tool.config / unreadable):
        response = centrum.client.post(f"{LEGEND_URL}/preview", json={"kind": "remove", "code_id": "rt2"})

    assert (response.status_code, response.json()) == (409, {"message": refusal.settings_file_unreadable(unreadable).message})


@pytest.mark.parametrize(
    ("settled", "expected"),
    [
        pytest.param(True, (409, {"message": refusal.settings_file_unreadable(SETTINGS_FILE).message}), id="foldery_przed_regulami"),
        pytest.param(False, (200, {"state": "no_settled_periods"}), id="brak_okresu_przed_regulami"),
    ],
)
def test_podglad_legendy_przy_regulach_ilosci_bez_odczytu_najpierw_mowi_o_folderach_i_o_braku_okresu(
    tmp_path: Path, settled: bool, expected: tuple[int, dict[str, str]]
) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    rule = "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia-router}"
    write_dad_quantity_rules(centrum.tool, RULES_FILE, rule, rule.replace("wartosc: 1", "wartosc: 2"))
    write_dad_quantity_rules(centrum.tool, DEVICES_FILE, "nokia-router", "nokia-router")
    if settled:
        run_to_end(centrum, dry_run=False)
    unreadable = (RULES_FILE, SETTINGS_FILE) if settled else (RULES_FILE,)

    with ExitStack() as stack:
        for name in unreadable:
            stack.enter_context(without_reading(centrum.tool.config / name))
        response = centrum.client.post(f"{LEGEND_URL}/preview", json={"kind": "remove", "code_id": "rt2"})

    assert (response.status_code, response.json()) == expected


def test_podglad_legendy_bez_okresu_po_przebiegu_rozliczen_nie_ma_na_czym_policzyc(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)

    preview = legend_previewed(centrum, {"kind": "remove", "code_id": "rt2"})

    assert preview == {"state": "no_settled_periods"}


def test_podglad_legendy_pomija_plik_zbiorczy_ktorego_nie_da_sie_przeczytac_i_nazywa_jego_okres(tmp_path: Path) -> None:
    centrum = legend_centrum(tmp_path, LEGEND_ROWS)
    run_to_end(centrum, dry_run=False)
    centrum.collective_file.write_bytes(b"to nie jest skoroszyt")

    preview = legend_previewed(centrum, {"kind": "remove", "code_id": "rt2"})

    assert (preview["state"], preview["files"], preview["unread"], preview["changed"]) == ("ready", [], [PERIOD], 0)


def test_podglad_legendy_ma_opis_technika_po_strazniku_bez_adresu_numerow_zlecenia_ani_daty_dziennej(tmp_path: Path) -> None:
    address, orange = "Malachitowa", "4807654321"
    described_without_code_equal_to_address = {**AGREED_WITH_RULES, "K": f"rt2 klient {orange} tel. 600-123-456 ul. Kwiatowa 5"}
    with_address_that_becomes_code = {**MARKED, "K": f"rt2 {address}"}
    rows = [with_address_that_becomes_code, {**AGREED_WITH_RULES, "B": address, "I": orange}, described_without_code_equal_to_address]
    centrum = centrum_with(tmp_path, rows)
    run_to_end(centrum, dry_run=False)
    added = {"spellings": [address.casefold()], "column": None, "value": 1, "amount": 10, "fills": [], "counts_in_fault": True}

    response = centrum.client.post(f"{LEGEND_URL}/preview", json={"kind": "add", "code": added})

    assert response.status_code == 200, response.text
    leaked = (address, orange, "600-123-456", "Kwiatowa", *FORBIDDEN, "2026-09-08", "08.09", "10:15")
    assert [marker for marker in leaked if marker in response.text] == []
    assert [row["description"] for row in response.json()["rows"]] == ["rt2 [adres]"]


SUGGESTIONS_URL = "/api/settings/devices/suggestions"


def test_podpowiedzi_listy_urzadzen_to_zapisy_zlecen_bez_reguly_z_ostatnich_okresow_i_znikaja_po_dodaniu(tmp_path: Path) -> None:
    two_unknown: dict[str, CellValue] = {"C": "u", "D": "przeniesienie nokia ont x", "G": MON.replace(hour=10), "T": 1}
    centrum = centrum_with(tmp_path, [*TATA_ROWS, two_unknown])
    before = centrum.client.get(SUGGESTIONS_URL).json()
    run_to_end(centrum, dry_run=False)

    suggested = centrum.client.get(SUGGESTIONS_URL).json()
    added = centrum.client.post("/api/settings/devices", json={"name": "przeniesienie", "other_spellings": [], "group": None})

    assert before == {"suggestions": [], "unread": []}
    assert suggested == {
        "suggestions": [{"spelling": "przeniesienie", "orders": 3}, {"spelling": "ont x", "orders": 1}],
        "unread": [],
    }
    assert added.status_code == 200, added.text
    assert centrum.client.get(SUGGESTIONS_URL).json() == {"suggestions": [{"spelling": "ont x", "orders": 1}], "unread": []}


@pytest.mark.parametrize("unreadable", [RULES_FILE, DEVICES_FILE])
def test_podpowiedzi_listy_urzadzen_przy_pliku_pary_bez_odczytu_sa_puste_a_nie_liczone_lista_z_wydania(
    tmp_path: Path, unreadable: str
) -> None:
    two_unknown: dict[str, CellValue] = {"C": "u", "D": "przeniesienie nokia ont x", "G": MON.replace(hour=10), "T": 1}
    centrum = centrum_with(tmp_path, [*TATA_ROWS, two_unknown])
    rule = "{kolumna: Z, wartosc: 1, razy: liczba, skladnik: nokia-router}"
    write_dad_quantity_rules(centrum.tool, RULES_FILE, rule, rule.replace("wartosc: 1", "wartosc: 2"))
    run_to_end(centrum, dry_run=False)
    added = centrum.client.post("/api/settings/devices", json={"name": "przeniesienie", "other_spellings": [], "group": None})
    assert added.status_code == 200, added.text
    assert centrum.client.get(SUGGESTIONS_URL).json() == {"suggestions": [{"spelling": "ont x", "orders": 1}], "unread": []}

    with without_reading(centrum.tool.config / unreadable):
        response = centrum.client.get(SUGGESTIONS_URL)

    assert (response.status_code, response.json()) == (200, {"suggestions": [], "unread": []})


def test_podpowiedzi_listy_urzadzen_przy_pliku_zbiorczym_ktorego_nie_da_sie_przeczytac_maja_jego_okres(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    centrum.collective_file.write_bytes(b"to nie jest skoroszyt")

    assert centrum.client.get(SUGGESTIONS_URL).json() == {"suggestions": [], "unread": [PERIOD]}


DIFFERENCES_URL = f"{RULES_URL}/differences"
NEWER = "15_21_09_2026"
class Difference(NamedTuple):
    period: str
    row: int
    devices: str
    activities: str
    when: str
    column: str
    rule: int
    tata: int | str


TATA_DIFFERENCES = [
    Difference(PERIOD, 19, "nokia zte 3*fut", "instalacja", "wt 10", "Q", 2, 1),
    Difference(PERIOD, 20, "nokia zte 3*fut", "instalacja", "wt 10", "Q", 2, 1),
    Difference(PERIOD, 21, "usterka", "", "pt 16", "N", 0, 45),
    Difference(PERIOD, 22, "technicolor", "", "śr 12", "AK", 1, 0),
    Difference(PERIOD, 26, "przeniesienie", "", "pon 9", "V", 1, 0),
    Difference(PERIOD, 31, "fut", "", "czw 14", "Q", 1, "nieliczbowa"),
    Difference(PERIOD, 31, "fut", "", "czw 14", "S", 1, "nieliczbowa"),
]


def differences(centrum: SettlingCentrum) -> dict[str, Any]:
    response = centrum.client.get(DIFFERENCES_URL)
    assert response.status_code == 200, response.text
    found: dict[str, Any] = response.json()
    return found


def shown(found: dict[str, Any]) -> list[Difference]:
    return [Difference(*(d[name] for name in Difference._fields)) for d in found["differences"]]


def at(found: dict[str, Any], row: int, column: str, period: str = PERIOD) -> dict[str, Any]:
    difference: dict[str, Any] = next(
        d for d in found["differences"] if (d["period"], d["row"], d["column"]) == (period, row, column)
    )
    return difference


def marked_as_exception(centrum: SettlingCentrum, difference: dict[str, Any]) -> dict[str, Any]:
    response = centrum.client.post(f"{DIFFERENCES_URL}/{difference['id']}/exception")
    assert response.status_code == 200, response.text
    saved: dict[str, Any] = response.json()
    return saved


def without(*cells: tuple[int, str]) -> list[Difference]:
    return [difference for difference in TATA_DIFFERENCES if (difference.row, difference.column) not in cells]


def settled_copy(centrum: SettlingCentrum, token: str) -> None:
    folder = centrum.period_parent / token
    folder.mkdir()
    shutil.copyfile(centrum.collective_file, folder / pliki_taty.collective_file_name(token))
    (folder / pliki_taty.worker_settlements_name(token)).mkdir()


def test_roznice_przy_regulach_ilosci_to_roznice_kontroli_ilosci_tego_samego_okresu(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    issue = sent_check(centrum)

    found = differences(centrum)

    assert shown(found) == TATA_DIFFERENCES
    assert issue.title == f"Kontrola ilości {PERIOD}: {len(found['differences'])} różnic"
    assert (found["unread"], found["more"], found["exceptions"]) == ([], 0, 0)


def test_to_byl_wyjatek_odmowiony_jak_usuniecie_loginu_z_okresu_ma_odpowiedz_kazdego_zapisu_ustawien(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    difference = at(differences(centrum), 21, "N")
    kept = KeptInPeriods(InRegister(), "worker")
    monkeypatch.setattr(CentrumSettings, "change_exceptions", lambda _settings, _exception: kept)

    response = centrum.client.post(f"{DIFFERENCES_URL}/{difference['id']}/exception")

    expected = refusal.worker_kept(kept.presence, kept.what)
    assert (response.status_code, response.json()) == (expected.status_code, {"message": expected.message})


def test_to_byl_wyjatek_ukrywa_roznice_po_restarcie_po_kolejnym_przebiegu_i_przy_nowszym_okresie(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)

    saved = marked_as_exception(centrum, at(differences(centrum), 21, "N"))
    centrum.restart()
    with centrum.client:
        restarted = differences(centrum)
        repeated(centrum)
        settled_copy(centrum, NEWER)
        later = differences(centrum)

    assert saved["change"] is not None
    assert (shown(saved["differences"]), saved["differences"]["exceptions"]) == (without((21, "N")), 1)
    assert (shown(restarted), restarted["exceptions"]) == (without((21, "N")), 1)
    newer = [difference._replace(period=NEWER) for difference in TATA_DIFFERENCES]
    assert (shown(later), later["exceptions"]) == ([*newer, *without((21, "N"))], 1)


def test_wyjatek_zostaje_po_zmianie_reguly_a_inny_wpis_taty_w_tej_komorce_to_nowa_roznica(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    marked_as_exception(centrum, at(differences(centrum), 22, "AK"))
    technicolor = rule_form(centrum, "technicolor")
    technicolor["action"]["writes"][2]["value"] = 2

    assert centrum.client.put(f"{RULES_URL}/technicolor", json=technicolor).status_code == 200
    after_rule = differences(centrum)
    write_quantity_source(centrum.collective_file, tata_rows_with("ak-1-z-reguly-porownane-a-tata-0", AK=3))
    after_tata = differences(centrum)

    def ak(found: dict[str, Any]) -> list[tuple[int, int, Any]]:
        return [(d["row"], d["rule"], d["tata"]) for d in found["differences"] if d["column"] == "AK"]

    assert (ak(after_rule), after_rule["exceptions"]) == ([(23, 2, 1)], 1)
    assert (ak(after_tata), after_tata["exceptions"]) == ([(22, 2, 3), (23, 2, 1)], 0)


def in_late_fault(**cells: CellValue) -> Callable[[SettlingCentrum], None]:
    def change(centrum: SettlingCentrum) -> None:
        write_quantity_source(centrum.collective_file, tata_rows_with(LATE_FAULT, **cells))

    return change


def row_above(centrum: SettlingCentrum) -> None:
    write_quantity_source(centrum.collective_file, [TATA_CASES[AGREED], *TATA_ROWS])


@pytest.mark.parametrize(
    ("marked_cell", "change", "back", "hidden"),
    [
        pytest.param((21, "N"), lambda centrum: settled_copy(centrum, NEWER), (NEWER, 21, "N"), 1, id="okres"),
        pytest.param((21, "N"), row_above, (PERIOD, 22, "N"), 0, id="wiersz"),
        pytest.param((31, "Q"), lambda centrum: None, (PERIOD, 31, "S"), 1, id="kolumna-przy-tym-samym-wpisie"),
        pytest.param((21, "N"), in_late_fault(N=46), (PERIOD, 21, "N"), 0, id="wpis-taty"),
        pytest.param((21, "N"), in_late_fault(C="pr 7"), (PERIOD, 21, "N"), 0, id="umowa"),
        pytest.param((21, "N"), in_late_fault(D="usterka gniazdo"), (PERIOD, 21, "N"), 0, id="urzadzenia"),
        pytest.param((21, "N"), in_late_fault(E="wymiana"), (PERIOD, 21, "N"), 0, id="czynnosci"),
        pytest.param((21, "N"), in_late_fault(G=THU.replace(hour=16, minute=30)), (PERIOD, 21, "N"), 0, id="dzien"),
        pytest.param((21, "N"), in_late_fault(G=FRI.replace(hour=16, minute=35)), (PERIOD, 21, "N"), 0, id="godzina"),
    ],
)
def test_wyjatek_ukrywa_tylko_swoja_komorke_a_zmiana_kazdej_rzeczy_ktora_tworzy_roznice_ja_przywraca(
    tmp_path: Path,
    marked_cell: tuple[int, str],
    change: Callable[[SettlingCentrum], None],
    back: tuple[str, int, str],
    hidden: int,
) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    marked_as_exception(centrum, at(differences(centrum), *marked_cell))

    change(centrum)
    found = differences(centrum)

    cells = [(d["period"], d["row"], d["column"]) for d in found["differences"]]
    assert (back in cells, found["exceptions"]) == (True, hidden)


def test_drugi_wyjatek_tej_samej_roznicy_ze_starego_okna_jest_juz_zapisany_bez_drugiego_wiersza_historii(
    tmp_path: Path,
) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    late_fault = at(differences(centrum), 21, "N")
    first = marked_as_exception(centrum, late_fault)

    second = marked_as_exception(centrum, late_fault)

    rows = centrum.client.get("/api/settings/history").json()["rows"]
    assert (first["change"] is not None, second["change"]) == (True, None)
    assert shown(second["differences"]) == without((21, "N"))
    assert [row["id"] for row in rows if row["file"] == EXCEPTIONS_FILE] == [first["change"]]


def test_wyjatek_jednego_z_dwoch_takich_samych_zlecen_nie_ukrywa_drugiego(tmp_path: Path) -> None:
    late_fault = TATA_CASES[LATE_FAULT]
    centrum = centrum_with(tmp_path, [late_fault, late_fault])
    run_to_end(centrum, dry_run=False)

    saved = marked_as_exception(centrum, at(differences(centrum), 18, "N"))

    assert [(d["row"], d["column"]) for d in saved["differences"]["differences"]] == [(19, "N")]


def test_cofnij_wyjatku_w_historii_przywraca_roznice_a_historia_mowi_zdaniem(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    saved = marked_as_exception(centrum, at(differences(centrum), 21, "N"))
    [row] = [row for row in centrum.client.get("/api/settings/history").json()["rows"] if row["id"] == saved["change"]]

    undone = centrum.client.post(f"/api/settings/history/{row['id']}/undo")
    restored = differences(centrum)
    [undo_row] = [found for found in centrum.client.get("/api/settings/history").json()["rows"] if found["undoes"] == row["id"]]
    again = centrum.client.post(f"/api/settings/history/{undo_row['id']}/undo")

    assert (row["file"], row["source"], row["undoable"]) == (EXCEPTIONS_FILE, "tata", True)
    [change] = row["rules"]
    sentence = "".join(part.get("text", part.get("letter", "")) for part in change["after"])
    assert (change["before"], sentence) == (None, f"To był wyjątek: okres {PERIOD}, wiersz 21, N: wpisałeś 45.")
    assert undone.status_code == 200, undone.text
    assert (shown(restored), restored["exceptions"]) == (TATA_DIFFERENCES, 0)
    assert again.status_code == 200, again.text
    assert shown(differences(centrum)) == without((21, "N"))


def test_wyjatek_roznicy_ktorej_juz_nie_ma_to_odmowa_bez_zapisu(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    gone = at(differences(centrum), 21, "N")
    write_quantity_source(centrum.collective_file, tata_rows_with(LATE_FAULT, N=0))
    history_before = centrum.client.get("/api/settings/history").json()

    response = centrum.client.post(f"{DIFFERENCES_URL}/{gone['id']}/exception")

    assert (response.status_code, response.json()) == (404, {"message": refusal.quantity_difference_unknown().message})
    assert not (centrum.tool.config / EXCEPTIONS_FILE).exists()
    assert centrum.client.get("/api/settings/history").json() == history_before


def test_popraw_regule_daje_formularz_nowej_reguly_z_warunkami_z_urzadzen_roznicy_bez_zapisu(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    found = differences(centrum)

    def component(name: str) -> dict[str, Any]:
        return {"kind": "component", "component": name, "negated": False}

    late_fault = at(found, 21, "N")["draft"]
    assert late_fault == {
        "scope": "known",
        "conditions": [component("usterka")],
        "action": {"kind": "fill", "writes": [{"column": "N", "value": 45, "multiplier": "once", "component": None}]},
    }
    assert at(found, 19, "Q")["draft"] == {
        "scope": "known",
        "conditions": [component("nokia-router"), component("fut")],
        "action": None,
    }
    assert at(found, 22, "AK")["draft"] == {"scope": "known", "conditions": [component("technicolor")], "action": None}
    assert at(found, 26, "V")["draft"] == {
        "scope": "unknown",
        "conditions": [{"kind": "devices", "mode": "contains", "text": "przeniesienie", "negated": False}],
        "action": None,
    }
    assert not (centrum.tool.config / RULES_FILE).exists()

    preview = previewed(centrum, {"kind": "add", "rule": late_fault})
    assert centrum.client.post(RULES_URL, json=late_fault).status_code == 200

    assert (preview["changed"], preview["changed_as_tata"]) == (1, 1)
    assert shown(differences(centrum)) == without((21, "N"))


def test_popraw_regule_nie_wpisuje_brakujacej_ilosci_w_p_q_i_s_ktore_narzedzie_liczy_samo(tmp_path: Path) -> None:
    rows = tata_rows_with("q-2-z-reguly-przy-trzech-fut-z-routerem-tata-1-pierwszy-wiersz-grupy-tej-samej-godziny", P=3, Q=5, S=9)
    centrum = centrum_with(tmp_path, rows)
    run_to_end(centrum, dry_run=False)
    found = differences(centrum)

    built_in = [(column, at(found, 19, column)["rule"], at(found, 19, column)["tata"]) for column in "PQS"]
    assert built_in == [("P", 1, 3), ("Q", 2, 5), ("S", 4, 9)]
    assert [at(found, 19, column)["draft"]["action"] for column in "PQS"] == [None, None, None]


def test_lista_roznic_pomija_plik_zbiorczy_ktorego_nie_da_sie_przeczytac_i_nazywa_jego_okres(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    settled_copy(centrum, NEWER)
    centrum.collective_file.write_bytes(b"to nie jest skoroszyt")

    found = differences(centrum)

    assert found["unread"] == [PERIOD]
    assert shown(found) == [difference._replace(period=NEWER) for difference in TATA_DIFFERENCES]


def test_zly_plik_wyjatkow_ma_zdanie_w_sekcji_a_lista_pokazuje_rowniez_roznice_bez_wyjatku(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    run_to_end(centrum, dry_run=False)
    (centrum.tool.config / EXCEPTIONS_FILE).write_text("wyjatki: [", encoding="utf-8")

    found = differences(centrum)

    assert shown(found) == TATA_DIFFERENCES
    assert found["exceptions_problem"] == {"field": None, "message": settings_messages.damaged(EXCEPTIONS_FILE)}


def test_zadna_chwila_zegara_testu_roznic_nie_ma_napisu_z_forbidden() -> None:
    moments = [CLOCK_START_WITHOUT_FORBIDDEN + step * STEP for step in range(MOMENTS)]
    written = [
        text
        for moment in moments
        for text in (moment.isoformat(), moment.isoformat().replace("+00:00", "Z"), repr(moment.timestamp()), moment.astimezone().isoformat())
    ]
    zones = [timezone(timedelta(minutes=minutes)) for minutes in range(-12 * 60, 14 * 60 + 1, 15)]
    for moment in {moments[0].replace(microsecond=0), moments[-1].replace(microsecond=0)}:
        written += [moment.astimezone(zone).strftime(shape) for zone in zones for shape in ("%Y-%m-%dT%H:%M:%S", "%d.%m.%Y %H:%M")]

    assert [marker for marker in FORBIDDEN if any(marker in text for text in written)] == []


def test_roznice_i_wyjatek_w_historii_i_zgloszeniu_nie_maja_adresu_numerow_wykonawcy_daty_ani_tresci_wiersza(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wall_clock_from(monkeypatch, CLOCK_START_WITHOUT_FORBIDDEN)
    centrum = centrum_with(tmp_path, [MARKED])
    run_to_end(centrum, dry_run=False)
    response = centrum.client.get(DIFFERENCES_URL).text
    assert [(d["row"], d["column"]) for d in differences(centrum)["differences"]] == [(18, "T"), (18, "V")]

    marked_as_exception(centrum, at(differences(centrum), 18, "V"))
    shutil.rmtree(centrum.worker_settlements)
    run_id = stopped_for_maks(centrum)
    report = centrum.client.post(f"/api/runs/{run_id}/diagnosis").json()["report"]["body"]
    kept = [
        centrum.client.get("/api/settings/history").text,
        (centrum.tool.config / HISTORY_FILE).read_text(encoding="utf-8"),
        (centrum.tool.config / EXCEPTIONS_FILE).read_text(encoding="utf-8"),
        centrum.log_path.read_text(encoding="utf-8"),
        report,
    ]

    assert [marker for marker in (*FORBIDDEN, "ZNACZNIK-UMOWA") if marker in response] == []
    assert all(marker in response for marker in ("ZNACZNIK-URZADZENIA", "ZNACZNIK-CZYNNOSCI"))
    assert [marker for marker in (*FORBIDDEN, *ALLOWED) if any(marker in text for text in kept)] == []
    assert f"· tata · {EXCEPTIONS_FILE} · dodano wyjątek: okres {PERIOD}, wiersz 18, V, wpis taty nieliczbowa" in report
