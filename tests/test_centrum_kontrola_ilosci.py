"""Kontrola ilości po Przebiegu rozliczeń z Centrum (ADR 0013, #273), przez HTTP API z fałszywą Skrzynką Zgłoszeń.

Plik zbiorczy jest syntetyczny: wiersze z poprawkami „taty” w N:AP, a wartości w kolumnach, których Kontrola nie
może wysłać, są znacznikami. Żaden test nie łączy się z GitHubem.
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import threading
from typing import Any, Final

import pytest

from rozliczenia.centrum.outbox import Outbox, Post
from rozliczenia.centrum.report_box import Refused, Sent, Unreachable
from rozliczenia.centrum.settings.quantity_rules import RULES_FILE

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
from tests.fixtures.centrum_processes import SettlingCentrum, run_to_end, settling_centrum, write_dad_quantity_rules
from tests.fixtures.potomne import wait_for
from atrapy.settlement import MARKED, CellValue, PERIOD, write_quantity_source

LABEL: Final = "kontrola-ilosci"
LINE = f"- Kontrola ilości okresu: {PERIOD}"

TUE, WED, THU, FRI, MON = (datetime(2026, 9, day) for day in (8, 9, 10, 11, 14))

# Każdy wiersz to jeden przypadek decyzji 9-11; komentarz mówi, co Reguły ilości dają, a co wpisał tata.
TATA_ROWS: list[dict[str, CellValue]] = [
    # zgodny z regułą; zera z Wzorca w N, Q i X to puste
    {"C": "u", "D": "nokia zte", "E": "instalacja", "G": TUE.replace(hour=10, minute=15),
     "V": 1, "T": 1, "O": 1, "Z": 1, "S": 1, "N": 0, "Q": 0, "X": 0},
    # reguła Q 2 (trzy fut przy routerze), tata 1: dwa wiersze z tej samej godziny to jedna grupa
    {"C": "u", "D": "nokia zte 3*fut", "E": "instalacja", "G": TUE.replace(hour=10, minute=5),
     "V": 1, "T": 1, "O": 1, "Z": 1, "P": 1, "Q": 1, "S": 4},
    {"C": "u", "D": "nokia zte 3*fut", "E": "instalacja", "G": TUE.replace(hour=10, minute=40),
     "V": 1, "T": 1, "O": 1, "Z": 1, "P": 1, "Q": 1, "S": 4},
    # usterka w piątek przed 17: bez dodatku, tata wpisał 45 w N
    {"C": "pr", "D": "usterka", "G": FRI.replace(hour=16, minute=30), "V": 1, "AI": 1, "N": 45},
    # reguła daje AK 1, więc AK jest porównywane: tata 0
    {"C": "pr", "D": "technicolor", "G": WED.replace(hour=12), "V": 1, "O": 1, "Z": 1, "S": 1},
    # AK z reguły wpisane przez tatę: zgodne, więc nie liczy się jak kolumna z opisu
    {"C": "pr", "D": "technicolor", "G": WED.replace(hour=15), "V": 1, "O": 1, "Z": 1, "S": 1, "AK": 1},
    # reguła nie daje AK, więc AK taty liczy się jak kolumna z opisu technika, razem z Y
    {"C": "pr", "D": "nokia", "G": WED.replace(hour=13), "V": 1, "Z": 1, "AK": 1, "Y": 1},
    # samo nokia z „akt int” w CZYNNOŚCI: O 1 z reguły, zgodne z tatą
    {"C": "pr", "D": "nokia", "E": "AKT INT", "G": WED.replace(hour=16), "V": 1, "Z": 1, "O": 1},
    # bez reguły: różnica tylko w V, wartość taty w O
    {"C": "u", "D": "przeniesienie", "G": MON.replace(hour=9), "T": 1, "O": 1},
    # bez reguły: słowo w AM to „nieliczbowa”, AM liczy się też jak kolumna z opisu
    {"C": "u", "D": "przeniesienie", "G": MON.replace(hour=9, minute=30), "V": 1, "T": 1, "AM": "dwa"},
    # rozliczany z opisu: bez porównania, AB taty liczy się jak kolumna z opisu
    {"C": "u", "D": "prewencja", "G": THU.replace(hour=8), "AB": 2},
    # DATA zmieniona przez tatę na tekst: bez porównania
    {"C": "pr", "D": "nokia", "G": "wtorek", "V": 1, "Z": 1},
    # liczba tekstem i float równy liczbie to ta liczba; R to pozostała kolumna N:AP
    {"C": "pr", "D": "gniazdo", "G": THU.replace(hour=11), "V": "1", "AE": 1.0, "AP": 1, "R": 3},
    # 1.5 i formuła to „nieliczbowa”
    {"C": "pr", "D": "fut", "G": THU.replace(hour=14), "V": 1, "Q": 1.5, "S": "=1+1"},
]

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


def queued(centrum: SettlingCentrum) -> list[Path]:
    """Kontrole ilości w kolejce, bez ``.json.tmp``, który kolejka zostawia na chwilę przepisania pliku
    (``replace_atomically``, na Windows z ponowieniami zamiany; #885); Logi Uruchomienia mają w niej własne pliki."""

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
    centrum = centrum_with(tmp_path, [TATA_ROWS[0]])

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    assert issue.title == f"Kontrola ilości {PERIOD}: bez różnic"
    assert "- Różnice w kolumnach Reguł ilości: 0\n" in issue.body
    assert "## Różnice" not in issue.body


def test_kontrola_ilosci_liczy_regulami_ilosci_z_ustawien_ktorymi_liczyl_jej_przebieg(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [TATA_ROWS[0]])
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


def test_kontrola_ilosci_nie_ma_adresu_numerow_wykonawcy_daty_ani_czynnosci_zrealizowanych(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [MARKED])

    view = run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    sent = issue.title + issue.body + "".join(issue.comments)
    assert [marker for marker in FORBIDDEN if marker in sent] == []
    assert all(marker in sent for marker in ALLOWED)
    assert "| V | 1 | nieliczbowa | `ZNACZNIK-CZYNNOSCI` | `u ZNACZNIK-UMOWA` | śr 13 | 1 |" in sent
    assert wait_for(lambda: queued(centrum) == [])
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
    # Tabela Kontroli ilości pisze koniec linii komórki jako „⏎”, a „|” jako „\|” (ADR 0025: każdy zapis wartości).
    centrum = centrum_with(tmp_path, [{**MARKED, **forbidden}, {**MARKED, "E": typed}])

    view = run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    # Bez losowego identyfikatora Uruchomienia (32 znaki szesnastkowe), w którym „4321” wypada raz na ~1770 Uruchomień.
    sent = (issue.title + issue.body + "".join(issue.comments)).replace(view["run"]["id"], "")
    assert shown in sent
    assert ("Malachitowa" in sent, "4321" in sent) == (False, False)
    assert sent.endswith(f"## Uwagi techniczne\n\n- Reguła danych: zamaskowano wartość kolumny {column} w: treść Kontroli ilości.\n")


def test_wartosc_adresu_rowna_slowom_tytulu_kontroli_ilosci_jest_zamaskowana_takze_w_tytule(tmp_path: Path) -> None:
    # Tytuł ma dziś tylko token okresu i liczbę różnic, a reguła danych obejmuje cały tekst Kontroli ilości: wartość
    # ADRES, tu równa słowom tytułu, nie wychodzi także w nim. Linia okresu na górze issue to znacznik wątku okresu.
    centrum = centrum_with(tmp_path, [{**MARKED, "B": "Kontrola ilości"}])

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    assert issue.title.startswith(f"[adres] {PERIOD}: ")
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


def test_logi_uruchomienia_ida_do_kolejki_wysylki_przed_kontrola_ilosci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Po wyniku Przebiegu rozliczeń z zapisem Kolejka wysyłki dostaje najpierw Logi Uruchomienia, a dopiero po nich
    Kontrolę ilości: działanie po wyniku, które zawiedzie albo przy którym Centrum zgaśnie, nie zabiera Uruchomieniu jego
    Logów (#871)."""

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


def test_podglad_i_zatrzymanie_nie_tworza_kontroli_ilosci(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)

    preview = run_to_end(centrum, dry_run=True)
    write_quantity_source(centrum.collective_file, [*TATA_ROWS, {"H": "andrzej.nieznany2"}])
    stopped = run_to_end(centrum, dry_run=False)

    assert preview["result"]["ending"] == "finished"
    assert stopped["result"]["ending"] == "stop"
    assert queued(centrum) == []
    assert box(centrum).keys == []
    assert f"etykieta={LABEL}" not in centrum.log_path.read_text(encoding="utf-8")


def repeated(centrum: SettlingCentrum) -> dict[str, Any]:
    """Przebieg tego samego okresu jeszcze raz, po usunięciu Folderu rozliczeń pracowników, jak zrobiłby tata."""

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
    assert wait_for(lambda: queued(centrum) == [])


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


def waiting_for_network(centrum: SettlingCentrum) -> int:
    waiting = f"skrzynka-czeka etykieta={LABEL} okres={PERIOD} przyczyna=brak-sieci"
    return centrum.log_path.read_text(encoding="utf-8").count(waiting)


def test_kontrola_ilosci_bez_sieci_czeka_w_kolejce_i_wychodzi_przy_nastepnym_starcie_centrum(tmp_path: Path) -> None:
    # Bez sieci przez cały czas, a nie na jedną odpowiedź: Logi Uruchomienia budzą kolejkę osobno, więc Kontrola
    # może pójść w jednym albo dwóch przejściach.
    centrum = centrum_with(tmp_path, TATA_ROWS)
    box(centrum).search_failure = Unreachable()

    view = run_to_end(centrum, dry_run=False)

    assert wait_for(lambda: waiting_for_network(centrum) >= 1)
    assert view["result"]["result"] == "OK"
    assert view["result"]["technical_notes"] == [] and view["result"]["warnings"] == []
    [waiting] = queued(centrum)
    assert list(ToolDirectory(tmp_path).queue.parent.iterdir()) == [ToolDirectory(tmp_path).queue]

    before_start = waiting_for_network(centrum)
    centrum.restart()
    with centrum.client:
        assert wait_for(lambda: waiting_for_network(centrum) > before_start)
        assert centrum.client.get("/api/runs/current").json()["state"] == "idle"
    assert queued(centrum) == [waiting]
    assert box(centrum).issues == []

    box(centrum).search_failure = None
    centrum.restart()
    with centrum.client:
        issue = sent_check(centrum)

    assert issue.body == expected_body(view["run"]["id"])
    assert wait_for(lambda: queued(centrum) == [])
    assert list(ToolDirectory(tmp_path).queue.parent.glob("Zgłoszenie *.md")) == []


def test_logi_i_kontrola_ilosci_jednego_przebiegu_czekaja_razem_i_przy_starcie_wychodza_obie(tmp_path: Path) -> None:
    """Logi Uruchomienia i Kontrola ilości jednego Przebiegu rozliczeń mają to samo Uruchomienie, ale inny cel w
    Skrzynce: bez sieci czekają w kolejce razem, a przy następnym starcie Centrum wychodzą obie, bo żadna nie jest
    nowszą wersją drugiej."""

    centrum = centrum_with(tmp_path, TATA_ROWS)
    box(centrum).background = frozenset()  # Logi też bez sieci, a nie w ruchu w tle, który zawsze dochodzi
    box(centrum).search_failure = Unreachable()
    folder = ToolDirectory(tmp_path).queue

    view = run_to_end(centrum, dry_run=False)

    assert wait_for(lambda: "przyczyna=brak-sieci" in centrum.log_path.read_text(encoding="utf-8"))
    assert wait_for(lambda: len(queued(centrum)) == 1 and bool(list(folder.glob("*-logi-uruchomienia-*.json"))))

    box(centrum).search_failure = None
    centrum.restart()
    with centrum.client:
        issue = sent_check(centrum)
        assert box(centrum).wait_until(lambda fake: bool(fake.issues_with("logi-uruchomienia"))), "Logi nie dotarły"
        assert wait_for(lambda: sorted(folder.glob("*.json")) == [])

    assert issue.body == expected_body(view["run"]["id"])
    [logs] = box(centrum).issues_with("logi-uruchomienia")
    assert [view["run"]["id"] in comment for comment in logs.comments] == [True]


def test_ponowienie_przy_starcie_nie_opoznia_startu_centrum(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    box(centrum).search_failure = Unreachable()
    run_to_end(centrum, dry_run=False)
    assert wait_for(lambda: waiting_for_network(centrum) >= 1)
    # Sieć wraca dopiero po końcu kolejki poprzedniego Centrum (restart): jej następne przejście, np. obudzone
    # przez Logi Uruchomienia, wysłałoby Kontrolę samo i zawisło na hold.
    centrum.restart()
    box(centrum).open_hold = hold = threading.Event()
    box(centrum).opening.clear()
    box(centrum).search_failure = None

    # Start na osobnym wątku: start, który czeka na skrzynkę, wisiałby inaczej do końca testu.
    start = threading.Thread(target=centrum.client.__enter__, daemon=True)
    start.start()
    try:
        start.join(10)
        started_while_held = not start.is_alive()
        asked = box(centrum).opening.wait(30)
        health = centrum.client.get("/api/health") if started_while_held else None
    finally:
        hold.set()
        start.join(30)
    try:
        issue = sent_check(centrum)
    finally:
        centrum.client.__exit__(None, None, None)

    assert started_while_held, "start Centrum czekał na skrzynkę"
    assert asked, "ponowienie przy starcie nie zapytało skrzynki"
    assert health is not None and health.status_code == 200
    assert issue.title == f"Kontrola ilości {PERIOD}: 7 różnic"


RULES_URL = "/api/settings/quantity-rules"
# Reguła z edytora: przy składniku „nokia” wpisz jeszcze 1 w Z, obok reguły „nokia” (Z razy liczba „nokia”).
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
    # Dwa wiersze z samym „nokia” (środa 13 i 16) mają po zmianie Z = 2, a tata wpisał 1.
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

    # Usterka w piątek 16:30: po zmianie dodatek N = 45, tak jak wpisał tata.
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


SUGGESTIONS_URL = "/api/settings/devices/suggestions"


def test_podpowiedzi_listy_urzadzen_to_zapisy_zlecen_bez_reguly_z_ostatnich_okresow_i_znikaja_po_dodaniu(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS)
    before = centrum.client.get(SUGGESTIONS_URL).json()
    run_to_end(centrum, dry_run=False)

    suggested = centrum.client.get(SUGGESTIONS_URL).json()
    added = centrum.client.post("/api/settings/devices", json={"name": "przeniesienie", "other_spellings": [], "group": None})

    assert before == {"suggestions": [], "unread": []}
    # „prewencja” jest nieznana, ale zlecenie z nią rozlicza się z opisu, więc ma już swoją regułę.
    assert suggested == {"suggestions": [{"spelling": "przeniesienie", "orders": 2}], "unread": []}
    assert added.status_code == 200, added.text
    assert centrum.client.get(SUGGESTIONS_URL).json() == {"suggestions": [], "unread": []}
