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

from rozliczenia.centrum.report_box import Refused, SendOutcome, Sent, Unreachable

from tests.fixtures.centrum import TOOL_COMMIT, FakeIssue, FakeReportBox, finished_view, without_times
from tests.fixtures.centrum_processes import SettlingCentrum, run_to_end, settling_centrum
from tests.fixtures.potomne import wait_for
from tests.fixtures.settlement import MARKED, CellValue, PERIOD, write_quantity_source

KEY = "github_pat_SYNTETYCZNY_KLUCZ_ZGLOSZEN"
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
        (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")
    return centrum


def box(centrum: SettlingCentrum) -> FakeReportBox:
    return centrum.surroundings.report_box


def queued(centrum: SettlingCentrum) -> list[Path]:
    """Kontrole ilości w kolejce; Logi Uruchomienia mają w niej własne pliki."""

    return sorted((centrum.tmp_path / "config" / "zgloszenia" / "kolejka").glob(f"*-{LABEL}-*"))


def sent_check(centrum: SettlingCentrum) -> FakeIssue:
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
    assert box(centrum).keys == [KEY]
    sent = f"skrzynka-wyslano etykieta={LABEL} okres={PERIOD} numer=1"
    assert wait_for(lambda: sent in centrum.log_path.read_text(encoding="utf-8"))


def test_przy_zera_roznic_kontrola_ilosci_tez_powstaje_z_tytulem_bez_roznic(tmp_path: Path) -> None:
    centrum = centrum_with(tmp_path, [TATA_ROWS[0]])

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    assert issue.title == f"Kontrola ilości {PERIOD}: bez różnic"
    assert "- Różnice w kolumnach Reguł ilości: 0\n" in issue.body
    assert "## Różnice" not in issue.body


def test_plik_zbiorczy_bez_naglowka_kolumny_wejscia_daje_kontrole_bez_porownania(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    (tmp_path / "config" / "zgloszenia-klucz.txt").write_text(KEY + "\n", encoding="utf-8")

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

    run_to_end(centrum, dry_run=False)

    issue = sent_check(centrum)
    sent = issue.title + issue.body + "".join(issue.comments)
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


@pytest.mark.parametrize(
    ("answer", "key"),
    [(Sent(1), True), (Refused(), True), (Unreachable(), True), (None, False)],
    ids=["przyjela", "odmowila", "brak-sieci", "brak-klucza"],
)
def test_wynik_przebiegu_jest_ten_sam_przy_kazdej_odpowiedzi_skrzynki(
    tmp_path: Path, answer: SendOutcome | None, key: bool
) -> None:
    centrum = centrum_with(tmp_path, TATA_ROWS, key=key)
    if answer is not None:
        box(centrum).outcomes.append(answer)

    view = run_to_end(centrum, dry_run=False)

    reference = centrum_with(tmp_path / "bez-skrzynki", TATA_ROWS, key=False)
    expected = run_to_end(reference, dry_run=False)
    assert without_times(view["result"]) == without_times(expected["result"])
    assert view["result"]["technical_notes"] == [] and view["result"]["warnings"] == []
    [record] = centrum.metric_records()
    [expected_record] = reference.metric_records()
    assert without_times(record) == without_times(expected_record)
    assert list((tmp_path / "config" / "zgloszenia").glob("Zgłoszenie *.md")) == []


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
        FakeIssue(1, LABEL, "Kontrola ilości 01_07_09_2026: bez różnic", "- Kontrola ilości okresu: 01_07_09_2026\n"),
        FakeIssue(2, LABEL, f"Kontrola ilości {PERIOD}0", f"- Kontrola ilości okresu: {PERIOD}0\n"),
        FakeIssue(3, "zgloszenie", "BRAK_WZORCA: Nie znaleziono wzorca.", f"## Komunikat\n\n{LINE}\n"),
        FakeIssue(4, "logi-uruchomienia", f"Logi {PERIOD}", f"{LINE}\n"),
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
    assert [path.name for path in (tmp_path / "config" / "zgloszenia").iterdir()] == ["kolejka"]

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
    assert list((tmp_path / "config" / "zgloszenia").glob("Zgłoszenie *.md")) == []


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
