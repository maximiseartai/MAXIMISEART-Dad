"""Rodzaj Zatrzymania, powtórka i Diagnoza w Centrum rozliczeń przez HTTP API, jak widzi je przeglądarka."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, NoReturn

import pytest

from rozliczenia.centrum.report_box import Refused, Unreachable
from rozliczenia.input_checks import FILE_READERS
from rozliczenia.template_file import TemplateFile

from tests.fixtures.centrum import NO_RELEASE, FakeGitHub, FakeReportBox, finished_view, phase_states, view_timing, views_until
from tests.fixtures.centrum_processes import (
    PreparingCentrum,
    SettlingCentrum,
    Surroundings,
    preparing_centrum,
    run_logs_handled,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from tests.fixtures.preparation import (
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    REGISTER_HEADERS,
    incomplete_period_rows,
    month_periods_folder,
    write_register,
)


def lock(path: Path) -> Path:
    """Plik blokady Excela obok skoroszytu, jak przy otwartym albo źle zamkniętym Excelu."""

    lock_file = path.with_name(f"~${path.name}")
    lock_file.touch()
    return lock_file


def stop_of(centrum: PreparingCentrum) -> dict[str, object]:
    result = run_to_end(centrum, dry_run=True)["result"]
    assert result["ending"] != "finished", result
    return dict(result)


def test_zatrzymanie_dla_taty_proponuje_uruchom_ponownie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)

    result = stop_of(centrum)

    assert (result["stop_kind"], result["next_action"], result["diagnosis"]) == ("for_tata", "rerun", None)
    assert (result["headline"], result["opens"]) == ("Do poprawy", "order_register")


def test_brak_rejestru_nie_proponuje_otwarcia_rejestru(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.register_path.unlink()

    result = stop_of(centrum)

    assert (result["stop_kind"], result["headline"], result["opens"]) == ("for_tata", "Do poprawy", None)


def test_zatrzymanie_ktore_kaze_przekazac_komunikat_jest_do_maksa(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.internal_template_path.unlink()

    result = stop_of(centrum)

    assert (result["stop_kind"], result["diagnosis"], result["headline"]) == ("for_maks", "on_request", "Błąd")


def test_nieoczekiwany_wyjatek_jest_do_maksa_a_diagnoza_zaczyna_sie_sama(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.engines.fail_engine = True

    result = stop_of(centrum)

    assert (result["ending"], result["stop_kind"], result["diagnosis"]) == ("unexpected", "for_maks", "automatic")


def test_identyczny_komunikat_przy_ponownym_uruchomieniu_to_powtorka(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)
    stop_of(centrum)

    again = stop_of(centrum)

    assert (again["stop_kind"], again["diagnosis"], again["headline"]) == ("repeated", "on_request", "Do poprawy")


def test_powtorka_trafia_do_historii_metryk_jako_zatrzymanie_dla_taty(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    register_lock = lock(centrum.fixture.register_path)
    first, repeated = stop_of(centrum), stop_of(centrum)
    register_lock.unlink()
    centrum.fixture.internal_template_path.unlink()
    for_maks = stop_of(centrum)

    runs = centrum.client.get("/api/metrics").json()["runs"]

    assert [result["stop_kind"] for result in (first, repeated, for_maks)] == ["for_tata", "repeated", "for_maks"]
    assert [run["stop_kind"] for run in runs] == ["for_maks", "for_tata", "for_tata"]


def test_inny_komunikat_przy_ponownym_uruchomieniu_nie_jest_powtorka(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    register_lock = lock(centrum.fixture.register_path)
    stop_of(centrum)
    register_lock.unlink()
    lock(centrum.fixture.internal_template_path)

    again = stop_of(centrum)

    assert again["stop_kind"] == "for_tata"


def test_uruchomienie_bez_zatrzymania_przerywa_powtorke(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    register_lock = lock(centrum.fixture.register_path)
    stop_of(centrum)
    register_lock.unlink()
    assert run_to_end(centrum, dry_run=True)["result"]["stop_kind"] is None
    lock(centrum.fixture.register_path)

    again = stop_of(centrum)

    assert again["stop_kind"] == "for_tata"


def declined(centrum: PreparingCentrum) -> dict[str, Any]:
    """Uruchom na niepełnym okresie, w którym tata wybiera „Przerwij” w Decyzji taty."""

    centrum.start(dry_run=False)
    view = views_until(centrum.client, "awaiting_decision")[-1]
    assert centrum.client.post(f"/api/runs/{view['run']['id']}/decision", json={"answer": "abort"}).status_code == 200
    return finished_view(centrum.client)


def test_odmowa_w_decyzji_taty_nie_jest_powtorka_i_nie_ma_diagnozy(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    first = declined(centrum)

    again = declined(centrum)
    diagnosis = centrum.client.post(f"/api/runs/{again['run']['id']}/diagnosis")

    assert [(view["result"]["stop_kind"], view["result"]["diagnosis"]) for view in (first, again)] == [
        ("declined", None),
        ("declined", None),
    ]
    assert diagnosis.status_code == 409


def test_odmowa_w_decyzji_taty_przerywa_powtorke(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    register_lock = lock(centrum.fixture.register_path)
    stop_of(centrum)
    register_lock.unlink()
    declined(centrum)
    lock(centrum.fixture.register_path)

    again = stop_of(centrum)

    assert again["stop_kind"] == "for_tata"


def test_restart_centrum_zeruje_pamiec_powtorki(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)
    stop_of(centrum)

    centrum.restart()
    again = stop_of(centrum)

    assert again["stop_kind"] == "for_tata"


NOT_FOUND = {
    "what": "Nie znalazłem przyczyny na tym komputerze.",
    "where": "Diagnoza w Centrum rozliczeń",
    "action": "Wyślij do Maksa.",
}


def diagnose(centrum: PreparingCentrum | SettlingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert response.status_code == 200, response.json()
    diagnosis: dict[str, Any] = response.json()
    assert "SYN-" not in json.dumps(diagnosis, ensure_ascii=False)
    return diagnosis


def check_states(diagnosis: dict[str, Any]) -> dict[str, str]:
    return {check["label"]: check["state"] for check in diagnosis["checks"]}


def with_key(centrum: PreparingCentrum) -> None:
    (centrum.tmp_path / "config" / "zgloszenia-klucz.txt").write_text("github_pat_SYNTETYCZNY\n", encoding="utf-8")


def test_diagnoza_bez_przyczyny_na_komputerze_kaze_wyslac_do_maksa(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    assert (diagnosis["explanation"], diagnosis["next_action"], diagnosis["confirms_stop"]) == (NOT_FOUND, "report", False)
    assert set(check_states(diagnosis).values()) == {"passed"}


def test_diagnoza_dla_zatrzymania_dla_taty_jest_odrzucona(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]

    refused = centrum.client.post(f"/api/runs/{run_id}/diagnosis")

    assert (refused.status_code, refused.json()) == (
        409,
        {"message": "Diagnoza jest przy Zatrzymaniu do Maksa albo przy powtórce tego samego Komunikatu."},
    )


def test_diagnoza_nieznanego_uruchomienia_jest_odrzucona(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)

    refused = centrum.client.post("/api/runs/nieznane/diagnosis")

    assert (refused.status_code, refused.json()) == (404, {"message": "Nie ma takiego Uruchomienia procesu."})


def test_diagnoza_i_zgloszenie_poprzedniego_uruchomienia_sa_odrzucone_w_trakcie_i_po_nastepnym(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    previous = stopped_for_maks(centrum)
    centrum.start(dry_run=False)
    next_run = views_until(centrum.client, "awaiting_decision")[-1]["run"]["id"]

    def refusals() -> list[tuple[int, object]]:
        responses = [centrum.client.post(f"/api/runs/{previous}/{action}") for action in ("diagnosis", "report")]
        return [(response.status_code, response.json()) for response in responses]

    during = refusals()
    centrum.client.post(f"/api/runs/{next_run}/decision", json={"answer": "abort"})
    finished_view(centrum.client)

    assert during == refusals() == [(404, {"message": "Nie ma takiego Uruchomienia procesu."})] * 2


def test_diagnoza_i_zgloszenie_uruchomienia_bez_zatrzymania_sa_odrzucone(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    view = run_to_end(centrum, dry_run=True)
    assert view["result"]["ending"] == "finished"

    refused = [centrum.client.post(f"/api/runs/{view['run']['id']}/{action}") for action in ("diagnosis", "report")]

    assert [(response.status_code, response.json()) for response in refused] == [
        (409, {"message": "Diagnoza jest przy Zatrzymaniu do Maksa albo przy powtórce tego samego Komunikatu."})
    ] * 2


def test_diagnoza_przygotowania_sprawdza_po_kolei_ustawienia_onedrive_rejestr_wzorce_folder_okresu_aktualnosc_i_dziennik(
    tmp_path: Path
) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)

    checks = diagnose(centrum, run_id)["checks"]

    assert [(check["label"], check["detail"]) for check in checks] == [
        ("Ustawienia taty", "Rejestr zleceń i folder okresów są na miejscu."),
        ("Pliki w OneDrive", "Sprawdzone pliki są na tym komputerze: 3."),
        ("Rejestr zleceń", "Nie jest otwarty w Excelu, otwiera się i ma wymagane nagłówki."),
        ("Wzorzec rozliczenia wewnętrznego", "Wzorzec rozliczenia wewnętrznego.xlsx przechodzi Sprawdzanie."),
        ("Wzorzec pliku zbiorczego", "Wzorzec pliku zbiorczego.xlsx przechodzi Sprawdzanie."),
        ("Konfiguracja wykonawców", "Wczytuje się."),
        ("Folder okresu", "Folderu 08_14_09_2026 jeszcze nie ma."),
        ("Pliki okresu w Excelu", "Żaden plik okresu nie jest otwarty w Excelu."),
        ("Aktualność narzędzia", "Najnowsza wersja z GitHuba, commit 3c1d0a9."),
        ("Token do Zgłoszeń", "Na tym komputerze nie ma Tokenu do Zgłoszeń. Zgłoszenie poczeka, aż Maks go wpisze."),
        ("Dziennik Centrum rozliczeń", "Ostatnie wpisy od startu Centrum: 4."),
    ]


def test_powtorka_zatrzymania_dla_taty_wyjasnia_przyczyne_i_proponuje_uruchom_ponownie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    lock(centrum.fixture.register_path)
    stop_of(centrum)
    repeated = run_to_end(centrum, dry_run=True)
    assert repeated["result"]["stop_kind"] == "repeated"

    diagnosis = diagnose(centrum, repeated["run"]["id"])

    assert (diagnosis["next_action"], diagnosis["confirms_stop"]) == ("rerun", True)
    assert diagnosis["explanation"] == repeated["result"]["stops"][0]
    assert diagnosis["explanation"]["what"] == "Rejestr zleceń jest otwarty w Excelu. Nie utworzono żadnego pliku."
    assert check_states(diagnosis)["Rejestr zleceń"] == "failed"


def test_zatrzymanie_do_maksa_bez_wzorca_wyjasnia_brak_wzorca(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    assert diagnosis["explanation"] == stopped["result"]["stops"][0]
    assert diagnosis["explanation"]["where"] == "plik Wzorzec pliku zbiorczego.xlsx, folder config"
    assert diagnosis["next_action"] == "report"
    assert check_states(diagnosis)["Wzorzec rozliczenia wewnętrznego"] == "passed"
    assert check_states(diagnosis)["Wzorzec pliku zbiorczego"] == "failed"


@pytest.mark.parametrize(
    ("break_computer", "label", "what"),
    [
        (
            lambda centrum: centrum.fixture.register_path.unlink(),
            "Ustawienia taty",
            "Nie znaleziono Rejestru zleceń. Nie utworzono żadnego pliku.",
        ),
        (
            lambda centrum: centrum.fixture.periods_directory.rename(centrum.tmp_path / "INEA stary"),
            "Ustawienia taty",
            "Nie znaleziono folderu okresów. Nie utworzono żadnego pliku.",
        ),
        (
            lambda centrum: centrum.fixture.register_path.write_bytes(b"to nie jest skoroszyt"),
            "Rejestr zleceń",
            "Nie można odczytać Rejestru zleceń. Plik jest uszkodzony albo nie jest skoroszytem .xlsx. "
            "Nie utworzono żadnego pliku.",
        ),
        (
            lambda centrum: write_register(
                centrum.fixture.register_path,
                headers=tuple(header for header in REGISTER_HEADERS if header != "SKUTECZNE"),
            ),
            "Rejestr zleceń",
            "W Rejestrze zleceń brakuje wymaganego nagłówka SKUTECZNE. Nie utworzono żadnego pliku.",
        ),
        (
            lambda centrum: centrum.fixture.config_path.write_text("workers: [", encoding="utf-8"),
            "Konfiguracja wykonawców",
            "Nie można odczytać konfiguracji wykonawców. Plik nie jest poprawnym YAML.",
        ),
        (
            lambda centrum: (month_periods_folder(centrum.fixture.periods_directory, "09_Wrzesień_2026") / PERIOD).mkdir(),
            "Folder okresu",
            None,
        ),
    ],
    ids=["brak-rejestru", "brak-folderu-okresow", "uszkodzony-rejestr", "brak-naglowka", "zla-konfiguracja", "folder-okresu-w-miesiacu"],
)
def test_diagnoza_wyjasnia_pierwszym_sprawdzeniem_ktore_nie_przeszlo(
    tmp_path: Path,
    break_computer: Callable[[PreparingCentrum], object],
    label: str,
    what: str | None,
) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    break_computer(centrum)

    diagnosis = diagnose(centrum, run_id)

    if what is None:
        assert (diagnosis["explanation"], check_states(diagnosis)[label]) == (NOT_FOUND, "passed")
    else:
        assert (diagnosis["explanation"]["what"], check_states(diagnosis)[label]) == (what, "failed")
        assert next(check["detail"] for check in diagnosis["checks"] if check["label"] == label) == what


@pytest.mark.parametrize(
    "make_centrum",
    [lambda tmp_path: preparing_centrum(tmp_path), lambda tmp_path: settling_centrum(tmp_path)],
    ids=["przygotowanie", "przebieg"],
)
@pytest.mark.parametrize(
    "broken_config",
    [b"\xff\xfe\x00 nie utf-8", "schema_version: 2\nworkers:\n  a: Wykonawca Testowy\n".encode()],
    ids=["spoza-utf-8", "zly-schemat"],
)
def test_diagnoza_potwierdza_zatrzymanie_procesu_na_uszkodzonej_konfiguracji_wykonawcow(
    tmp_path: Path, make_centrum: Callable[[Path], PreparingCentrum | SettlingCentrum], broken_config: bytes
) -> None:
    centrum = make_centrum(tmp_path)
    if isinstance(centrum, PreparingCentrum):
        centrum.fixture.config_path.write_bytes(broken_config)
    else:
        centrum.configuration.worker_config.write_bytes(broken_config)
    stopped = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    assert (diagnosis["explanation"], diagnosis["confirms_stop"]) == (stopped["result"]["stops"][0], True)
    assert check_states(diagnosis)["Konfiguracja wykonawców"] == "failed"


def test_folder_okresu_w_kilku_miesiacach_wyjasnia_ktory_zostawic(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    for month in ("08_Sierpień_2026", "09_Wrzesień_2026"):
        (month_periods_folder(centrum.fixture.periods_directory, month) / PERIOD).mkdir()

    diagnosis = diagnose(centrum, run_id)

    assert diagnosis["explanation"]["where"] == (
        "Rozliczenia 2026\\08_Sierpień_2026\\INEA, Rozliczenia 2026\\09_Wrzesień_2026\\INEA"
    )
    assert (diagnosis["next_action"], check_states(diagnosis)["Pliki okresu w Excelu"]) == ("rerun", "not_checked")


def test_plik_okresu_otwarty_w_excelu_wyjasnia_jak_go_zamknac(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    centrum.fixture.period_directory.mkdir()
    centrum.fixture.internal_settlement_path.touch()
    lock(centrum.fixture.internal_settlement_path)

    diagnosis = diagnose(centrum, run_id)

    assert diagnosis["explanation"] == {
        "what": "Plik okresu jest otwarty w Excelu.",
        "where": f"plik {INTERNAL_SETTLEMENT_NAME}, folder {PERIOD}",
        "action": (
            "Zapisz i zamknij plik w Excelu, potem uruchom ponownie. Jeśli Excel jest zamknięty, "
            f"usuń z tego samego folderu pozostawiony plik ~${INTERNAL_SETTLEMENT_NAME} i uruchom ponownie."
        ),
    }
    assert diagnosis["next_action"] == "rerun"
    assert next(check for check in diagnosis["checks"] if check["label"] == "Folder okresu")["detail"] == (
        "Pliki okresu: Rozliczenie wewnętrzne."
    )


def test_rozliczenie_pracownika_otwarte_w_excelu_wyjasnia_jak_je_zamknac(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    centrum.worker_settlements.mkdir()
    worker_file = centrum.worker_settlements / f"Rozliczenie {centrum.period_directory.name} - Wykonawca Testowy A.xlsx"
    worker_file.touch()
    lock(worker_file)

    diagnosis = diagnose(centrum, run_id)

    assert (diagnosis["explanation"]["what"], diagnosis["explanation"]["where"]) == (
        "Plik okresu jest otwarty w Excelu.",
        f"plik {worker_file.name}, folder {centrum.worker_settlements.name}",
    )
    assert check(diagnosis, "Pliki okresu w Excelu")[0] == "failed"


def test_diagnoza_sprawdza_w_excelu_te_rozliczenia_pracownika_ktore_liczy_status_okresu(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    centrum.worker_settlements.mkdir()
    (centrum.worker_settlements / f"Rozliczenie {centrum.period_directory.name} - Wykonawca Testowy A.xlsx").touch()
    notes = centrum.worker_settlements / "notatki taty do rozliczeń pracowników z tego okresu.xlsx"
    notes.touch()
    lock(notes)

    diagnosis = diagnose(centrum, run_id)
    [row] = [row for row in centrum.client.get("/api/periods").json()["periods"] if row["token"] == centrum.period_directory.name]

    assert (check(diagnosis, "Pliki okresu w Excelu")[0], row["worker_settlement_count"]) == ("passed", 1)


UNEXPECTED_LOG_ENTRY = "2026-09-16T10:00:00+02:00 nieoczekiwany-wyjatek typ=KeyError miejsce=\"GET /api/periods\"\n"


def test_nieoczekiwany_wyjatek_bez_przyczyny_na_komputerze_kaze_wyslac_do_maksa_a_dziennik_tylko_go_wymienia(
    tmp_path: Path
) -> None:
    centrum = preparing_centrum(tmp_path)
    centrum.engines.fail_engine = True
    stopped = run_to_end(centrum, dry_run=True)
    run_logs_handled(centrum)
    with centrum.log_path.open("a", encoding="utf-8") as log:
        log.write(UNEXPECTED_LOG_ENTRY)

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    assert (diagnosis["explanation"], diagnosis["next_action"]) == (NOT_FOUND, "report")
    assert check(diagnosis, "Dziennik Centrum rozliczeń") == (
        "passed",
        "Ostatnie wpisy od startu Centrum: 5, w tym nieoczekiwany wyjątek.",
    )


def test_nieoczekiwany_wyjatek_ktory_wraca_w_diagnozie_zostawia_sprawdzenie_niesprawdzone_a_zgloszenie_mozna_wyslac(
    tmp_path: Path,
) -> None:
    def fail_unexpectedly(*args: object) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(readers=replace(FILE_READERS, register=fail_unexpectedly)))
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]

    diagnosis = diagnose(centrum, run_id)
    report = centrum.client.post(f"/api/runs/{run_id}/report")

    assert check(diagnosis, "Rejestr zleceń") == ("not_checked", "Nie udało się sprawdzić: nieoczekiwany błąd.")
    assert check_states(diagnosis)["Dziennik Centrum rozliczeń"] == "passed"
    assert (diagnosis["explanation"], diagnosis["next_action"]) == (NOT_FOUND, "report")
    assert 'nieoczekiwany-wyjatek typ=RuntimeError miejsce="Diagnoza: Rejestr zleceń"' in diagnosis["report"]["body"]
    assert (report.status_code, report.json()["state"]) == (200, "queued")


def test_nieoczekiwany_wyjatek_czytnika_wzorca_w_przebiegu_wraca_w_jego_diagnozie(tmp_path: Path) -> None:
    def fail_unexpectedly(template: TemplateFile) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    centrum = settling_centrum(tmp_path, surroundings=Surroundings(readers=replace(FILE_READERS, template=fail_unexpectedly)))
    stopped = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    assert (stopped["result"]["ending"], phase_states(stopped)["Sprawdzanie"]) == ("unexpected", "failed")
    assert check(diagnosis, "Wzorzec rozliczenia pracownika") == (
        "not_checked",
        "Nie udało się sprawdzić: nieoczekiwany błąd.",
    )


def test_wyjatek_przy_sprawdzaniu_jednego_wzorca_nie_ukrywa_wyniku_drugiego(tmp_path: Path) -> None:
    internal_template_failing = False

    def check_template(template: TemplateFile) -> None:
        if internal_template_failing and template.path == centrum.fixture.internal_template_path:
            raise RuntimeError("nieprzewidziany błąd przy SYN-001")
        FILE_READERS.template(template)

    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(readers=replace(FILE_READERS, template=check_template)))
    run_id = stopped_for_maks(centrum)
    internal_template_failing = True
    centrum.fixture.collective_template_path.unlink()

    diagnosis = diagnose(centrum, run_id)

    states = check_states(diagnosis)
    assert (states.get("Wzorzec rozliczenia wewnętrznego"), states.get("Wzorzec pliku zbiorczego")) == (
        "not_checked",
        "failed",
    )
    assert diagnosis["explanation"]["what"] == (
        "Nie znaleziono wzorca, z którego powstają pliki okresu. Nie utworzono żadnego pliku."
    )


def test_pomiary_widokow_po_nieoczekiwanym_wyjatku_nie_wypieraja_go_z_dziennika_w_diagnozie(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    with centrum.log_path.open("a", encoding="utf-8") as log:
        log.write(UNEXPECTED_LOG_ENTRY)
    for _ in range(30):  # tata przeklikuje strony: każdy gotowy widok to wpis pomiaru
        assert centrum.client.post("/api/view-timings", json=view_timing()).status_code == 204

    diagnosis = diagnose(centrum, run_id)

    assert diagnosis["next_action"] == "report"
    assert check(diagnosis, "Dziennik Centrum rozliczeń") == (
        "passed",
        "Ostatnie wpisy od startu Centrum: 5, w tym nieoczekiwany wyjątek.",
    )


def test_urwany_znak_w_dzienniku_nie_blokuje_diagnozy_a_nieoczekiwany_wyjatek_jest_wymieniony(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    with centrum.log_path.open("ab") as log:  # zapis „ł” urwany po pierwszym bajcie, np. przy utracie zasilania
        log.write("2026-09-16T09:59:00+02:00 przebieg-start proces=przygotowanie ".encode() + "ł".encode()[:1] + b"\n")
        log.write(UNEXPECTED_LOG_ENTRY.encode())

    diagnosis = diagnose(centrum, run_id)

    assert diagnosis["next_action"] == "report"
    assert check(diagnosis, "Dziennik Centrum rozliczeń") == (
        "passed",
        "Ostatnie wpisy od startu Centrum: 6, w tym nieoczekiwany wyjątek.",
    )


def test_wyjatek_w_dzienniku_sprzed_startu_centrum_nie_jest_wymieniony(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    previous = centrum.log_path.read_text(encoding="utf-8")
    centrum.log_path.write_text(
        UNEXPECTED_LOG_ENTRY.replace("2026-09-16T10", "2026-09-15T10")
        + "2026-09-16T09:00:00+02:00 start port=47811 wersja=3c1d0a9 konsola=nie\n"
        + previous,
        encoding="utf-8",
    )

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Dziennik Centrum rozliczeń") == ("passed", "Ostatnie wpisy od startu Centrum: 5.")


def test_diagnoza_przebiegu_sprawdza_wzorzec_pracownika_i_plik_zbiorczy(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)

    passing = diagnose(centrum, run_id)
    centrum.collective_file.unlink()
    missing = diagnose(centrum, run_id)

    assert [(check["label"], check["state"]) for check in passing["checks"]] == [
        ("Ustawienia taty", "passed"),
        ("Pliki w OneDrive", "passed"),
        ("Wzorzec rozliczenia pracownika", "passed"),
        ("Konfiguracja wykonawców", "passed"),
        ("Folder okresu", "passed"),
        ("Pliki okresu w Excelu", "passed"),
        ("Aktualność narzędzia", "passed"),
        ("Token do Zgłoszeń", "failed"),
        ("Dziennik Centrum rozliczeń", "passed"),
    ]
    assert check(passing, "Folder okresu") == ("passed", "Pliki okresu: Plik zbiorczy.")
    assert (passing["explanation"], missing["next_action"]) == (NOT_FOUND, "rerun")
    assert missing["explanation"]["what"] == "Nie znaleziono Pliku zbiorczego tego okresu. Nie utworzono żadnego pliku pracownika."


def test_diagnoza_wyceny_w_efenix_wyjasnia_brak_pliku_zbiorczego_komunikatem_wyceny(tmp_path: Path) -> None:
    """Wycena w efenix czyta Plik zbiorczy okresu, więc w jej Diagnozie jego brak to przyczyna Zatrzymania, z
    Komunikatem Wyceny, że w efenix nic się nie zmieniło."""

    centrum = settling_centrum(tmp_path)
    centrum.engines.fail_engine = True
    assert centrum.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "dry_run": False}).status_code == 200
    run_id = finished_view(centrum.client)["run"]["id"]
    run_logs_handled(centrum)

    passing = diagnose(centrum, run_id)
    centrum.collective_file.unlink()
    missing = diagnose(centrum, run_id)

    assert check(passing, "Folder okresu") == ("passed", "Pliki okresu: Plik zbiorczy.")
    assert check(missing, "Folder okresu")[0] == "failed"
    assert (missing["explanation"]["what"], missing["next_action"]) == (
        "Nie znaleziono Pliku zbiorczego. W efenix nic się nie zmieniło.",
        "rerun",
    )


def test_diagnoza_przebiegu_wyjasnia_zly_wzorzec_rozliczenia_pracownika(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    centrum.configuration.worker_template.write_bytes(b"to nie jest skoroszyt")

    diagnosis = diagnose(centrum, run_id)

    assert check_states(diagnosis)["Wzorzec rozliczenia pracownika"] == "failed"
    assert diagnosis["explanation"]["where"] == "plik Wzorzec rozliczenia pracownika.xlsx, folder config"


def test_diagnoza_niczego_nie_zmienia_w_plikach_taty(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    centrum.fixture.period_directory.mkdir()
    centrum.fixture.internal_settlement_path.write_bytes(b"syntetyczny plik okresu")
    lock(centrum.fixture.register_path)
    before = files_of(tmp_path)

    diagnose(centrum, run_id)

    assert files_of(tmp_path) == before


def files_of(root: Path) -> dict[str, bytes]:
    """Każdy plik taty pod ``root`` z treścią.

    Bez dziennika Centrum i Logów Uruchomienia (``logs``) oraz kolejki Skrzynki Zgłoszeń: Centrum dopisuje do nich Diagnozę.
    """

    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not {"logs", "kolejka"} & set(path.relative_to(root).parts)
    }


def check(diagnosis: dict[str, Any], label: str) -> tuple[str, str]:
    found = next(check for check in diagnosis["checks"] if check["label"] == label)
    return found["state"], found["detail"]


REFUSED_KEY = ("failed", "Skrzynka Zgłoszeń odrzuca Token do Zgłoszeń. Zgłoszenie poczeka, aż Maks go wymieni.")


def box_now_answers(centrum: PreparingCentrum, failure: Refused | Unreachable) -> None:
    """Skrzynka od teraz odpowiada ``failure``; przyjęcie klucza przez Logi Uruchomienia z tej pracy Centrum wygasa.

    Najpierw czeka na Logi Uruchomienia: wysłane w tle już po przesunięciu zegara dałyby świeże przyjęcie klucza (#627).
    """

    run_logs_handled(centrum)
    centrum.surroundings.report_box.search_failure = failure
    centrum.surroundings.clock.advance(minutes=10)


def test_diagnoza_pokazuje_odrzucony_klucz_jako_sprawdzenie_a_wyjasnieniem_zostaje_brak_wzorca(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)
    box_now_answers(centrum, Refused())

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    assert check(diagnosis, "Token do Zgłoszeń") == REFUSED_KEY
    assert diagnosis["explanation"] == stopped["result"]["stops"][0]
    assert f"| Token do Zgłoszeń | nie przeszło | {REFUSED_KEY[1]} |" in diagnosis["report"]["body"]


def test_diagnoza_bez_innej_przyczyny_i_z_odrzuconym_kluczem_nie_znajduje_przyczyny(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum)
    box_now_answers(centrum, Refused())

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Token do Zgłoszeń") == REFUSED_KEY
    assert (diagnosis["explanation"], diagnosis["next_action"]) == (NOT_FOUND, "report")


def test_diagnoza_z_tokenem_przyjetym_przez_skrzynke_mowi_ze_skrzynka_go_przyjmuje(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    with_key(centrum)
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Token do Zgłoszeń") == ("passed", "Skrzynka Zgłoszeń przyjmuje Token do Zgłoszeń.")


def test_diagnoza_z_kluczem_bez_sieci_go_nie_sprawdzila(tmp_path: Path) -> None:
    offline = FakeReportBox(search_failure=Unreachable())  # także Logi Uruchomienia nie dochodzą do skrzynki
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(report_box=offline))
    with_key(centrum)
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Token do Zgłoszeń") == (
        "not_checked",
        "Nie sprawdzono: brak połączenia ze Skrzynką Zgłoszeń.",
    )
    assert (diagnosis["explanation"], diagnosis["next_action"]) == (NOT_FOUND, "report")


NEWER_MAIN = "9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b"
NEWER = {
    "what": "Jest nowsza wersja narzędzia.",
    "where": "narzędzie na tym komputerze",
    "action": "Kliknij „Zaktualizuj narzędzie”. Gdy karta Centrum sama się odświeży, uruchom proces ponownie.",
}


def test_rejestr_otwarty_w_excelu_przy_nowszej_wersji_wyjasnia_rejestr_a_aktualizacje_tylko_proponuje(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(github=FakeGitHub(release=NEWER_MAIN)))
    lock(centrum.fixture.register_path)
    stop_of(centrum)
    repeated = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, repeated["run"]["id"])

    assert diagnosis["explanation"] == repeated["result"]["stops"][0]
    assert (diagnosis["confirms_stop"], diagnosis["next_action"], diagnosis["update_proposal"]) == (True, "rerun", True)
    assert check(diagnosis, "Aktualność narzędzia") == ("failed", "Jest nowsza wersja narzędzia.")


def test_nowsza_wersja_bez_innej_przyczyny_wyjasnia_ze_trzeba_zaktualizowac_narzedzie_przyciskiem(
    tmp_path: Path
) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(github=FakeGitHub(release=NEWER_MAIN)))
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    assert (diagnosis["explanation"], diagnosis["next_action"], diagnosis["update_proposal"]) == (NEWER, "update", False)
    assert check(diagnosis, "Aktualność narzędzia") == ("failed", "Jest nowsza wersja narzędzia.")


@pytest.mark.parametrize(
    ("github", "detail"),
    [
        (FakeGitHub(release=None), "Nie sprawdzono: brak połączenia z GitHubem."),
        (FakeGitHub(tool_commit=None), "Nie sprawdzono: narzędzie na tym komputerze nie ma commitu Gita."),
        (FakeGitHub(release=NO_RELEASE), "Nie sprawdzono: na GitHubie nie ma jeszcze żadnego Wydania."),
    ],
    ids=["brak-sieci", "bez-gita", "bez-wydania"],
)
def test_aktualnosc_bez_sieci_albo_bez_gita_nie_jest_sprawdzona_i_nie_jest_przyczyna(
    tmp_path: Path, github: FakeGitHub, detail: str
) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(github=github))
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Aktualność narzędzia") == ("not_checked", detail)
    assert (diagnosis["explanation"], diagnosis["next_action"]) == (NOT_FOUND, "report")


@pytest.mark.parametrize(
    ("github", "offered", "diagnosis_offer"),
    [
        (FakeGitHub(release=NEWER_MAIN), True, ("update", False)),
        (FakeGitHub(), False, ("report", False)),
        (FakeGitHub(release=None), False, ("report", False)),
        (FakeGitHub(release=NO_RELEASE), False, ("report", False)),
        (FakeGitHub(tool_commit=None), False, ("report", False)),
    ],
    ids=["nowsze-wydanie", "aktualna", "brak-sieci", "bez-wydania", "bez-gita"],
)
def test_konfiguracja_i_diagnoza_proponuja_aktualizacje_tylko_przy_nowszym_wydaniu(
    tmp_path: Path, github: FakeGitHub, offered: bool, diagnosis_offer: tuple[str, bool]
) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(github=github))
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)
    configuration = centrum.client.get("/api/configuration").json()

    assert configuration["update_offered"] is offered
    assert (diagnosis["next_action"], diagnosis["update_proposal"]) == diagnosis_offer


def test_brak_sieci_przy_sprawdzaniu_aktualnosci_nie_zmienia_wyjasnienia(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(github=FakeGitHub(release=None)))
    lock(centrum.fixture.register_path)
    stop_of(centrum)
    repeated = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, repeated["run"]["id"])

    assert diagnosis["explanation"] == repeated["result"]["stops"][0]
    assert (diagnosis["confirms_stop"], diagnosis["next_action"], diagnosis["update_proposal"]) == (True, "rerun", False)


ONLY_IN_CLOUD_ACTION = (
    "W Eksploratorze plików kliknij ten plik prawym przyciskiem myszy, wybierz „Zawsze zachowuj na tym urządzeniu”, "
    "poczekaj, aż się pobierze, i uruchom ponownie."
)


def online_only(centrum: PreparingCentrum | SettlingCentrum, path: Path) -> None:
    """OneDrive trzyma ``path`` tylko w chmurze, bez kopii na komputerze taty."""

    onedrive = centrum.surroundings.onedrive
    assert onedrive is not None
    onedrive.online_only.add(path)


def test_rejestr_tylko_w_chmurze_wyjasnia_jak_zachowac_go_na_komputerze(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    online_only(centrum, centrum.fixture.register_path)

    diagnosis = diagnose(centrum, run_id)

    assert diagnosis["explanation"] == {
        "what": "Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.",
        "where": f"plik {centrum.fixture.register_path.name}, folder {tmp_path.name}",
        "action": ONLY_IN_CLOUD_ACTION,
    }
    assert diagnosis["next_action"] == "rerun"
    assert check(diagnosis, "Pliki w OneDrive")[0] == "failed"


@pytest.mark.parametrize(
    "cloud_file",
    [
        lambda centrum: centrum.fixture.register_path,
        lambda centrum: centrum.fixture.collective_template_path,
    ],
    ids=["rejestr", "wzorzec"],
)
def test_plik_tylko_w_chmurze_ktorego_nie_da_sie_otworzyc_wyjasnia_onedrive_a_nie_odczyt(
    tmp_path: Path, cloud_file: Callable[[PreparingCentrum], Path]
) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    path = cloud_file(centrum)
    online_only(centrum, path)
    path.write_bytes(b"bez kopii na komputerze OneDrive nie oddaje skoroszytu")

    diagnosis = diagnose(centrum, run_id)

    assert diagnosis["explanation"] == {
        "what": "Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze.",
        "where": f"plik {path.name}, folder {path.parent.name}",
        "action": ONLY_IN_CLOUD_ACTION,
    }


def test_plik_folderu_okresu_tylko_w_chmurze_jest_przyczyna(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    passing = diagnose(centrum, run_id)
    online_only(centrum, centrum.collective_file)

    diagnosis = diagnose(centrum, run_id)

    assert check(passing, "Pliki w OneDrive") == ("passed", "Sprawdzone pliki są na tym komputerze: 2.")
    assert diagnosis["explanation"]["what"] == "Plik jest tylko w OneDrive w chmurze, bez kopii na tym komputerze."
    assert diagnosis["explanation"]["where"] == f"plik Rozliczenie {PERIOD} - zbiorcze.xlsx, folder {PERIOD}"


def test_rejestr_zlecen_tylko_w_chmurze_nie_jest_przyczyna_zatrzymania_przebiegu(tmp_path: Path) -> None:
    # Przebieg rozliczeń nie czyta Rejestru zleceń, więc jego Diagnoza nie wskazuje Rejestru w OneDrive.
    register = tmp_path / "Rejestr zleceń.xlsx"
    register.write_bytes(b"tylko w chmurze")
    centrum = settling_centrum(tmp_path, register=register)
    run_id = stopped_for_maks(centrum)
    online_only(centrum, register)

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Pliki w OneDrive") == ("passed", "Sprawdzone pliki są na tym komputerze: 2.")
    assert check(diagnosis, "Ustawienia taty") == ("passed", "Folder okresów jest na miejscu.")


def test_pliki_tylko_w_chmurze_sprawdza_tylko_windows(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(onedrive=None))
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    expected = (
        ("passed", "Sprawdzone pliki są na tym komputerze: 3.")
        if sys.platform == "win32"
        else ("not_checked", "Nie sprawdzono: tylko w Windows.")
    )
    assert check(diagnosis, "Pliki w OneDrive") == expected
    assert diagnosis["explanation"] == NOT_FOUND
