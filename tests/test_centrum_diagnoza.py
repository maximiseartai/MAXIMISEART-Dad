"""Rodzaj Zatrzymania, powtórka i Diagnoza w Centrum rozliczeń przez HTTP API, jak widzi je przeglądarka."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Final, NoReturn
from zoneinfo import ZoneInfo

import pytest

from rozliczenia import preparation_messages
from rozliczenia.centrum import diagnosis_messages
from rozliczenia.centrum.outbox import QUEUE_DIRECTORY
from rozliczenia.centrum.settings import messages as settings_messages
from rozliczenia.centrum.settings.workers import WORKERS_FILE
from rozliczenia.centrum.settings.folders import SETTINGS_FILE
from rozliczenia.centrum.settings.history import HISTORY_FILE
from rozliczenia.centrum.report_box import Refused, Unreachable
from rozliczenia.message import Message
from rozliczenia.template_file import TemplateFile
from rozliczenia.wall_clock import local_now
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE

from tests.fixtures.bez_dostepu import NO_ACCESS_ON_WINDOWS, PATH_CHECKS, without_access
from tests.fixtures.centrum import (
    NO_RELEASE,
    ToolDirectory,
    FakeGitHub,
    FakeReportBox,
    finished_view,
    phase_states,
    view_timing,
    views_until,
    write_report_key,
)
from tests.fixtures.centrum_processes import (
    on_register_read,
    PreparingCentrum,
    SettlingCentrum,
    Surroundings,
    preparing_centrum,
    run_logs_handled,
    run_to_end,
    settling_centrum,
    stopped_for_maks,
)
from tests.fixtures.wyciek import zawiera_wartosc
from atrapy.preparation import (
    INTERNAL_SETTLEMENT_NAME,
    PERIOD,
    REGISTER_HEADERS,
    incomplete_period_rows,
    month_periods_folder,
    write_register,
)
from atrapy.settlement import WORKERS, worker_list, write_worker_list


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


NOT_YOUR_FILES = "To nie wynika z Twoich plików."


def test_tylko_zatrzymanie_do_maksa_ma_ton_bledu_i_zdanie_ze_to_nie_wynika_z_plikow_taty(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path, incomplete_period_rows())
    register_lock = lock(centrum.fixture.register_path)
    for_tata, repeated = stop_of(centrum), stop_of(centrum)
    register_lock.unlink()
    declined_view = declined(centrum)
    centrum.fixture.internal_template_path.unlink()
    for_maks = stop_of(centrum)

    results = [for_tata, repeated, declined_view["result"], for_maks]
    assert [(result["stop_kind"], result["tone"], result["stop_note"]) for result in results] == [
        ("for_tata", "stopped", None),
        ("repeated", "stopped", None),
        ("declined", "stopped", None),
        ("for_maks", "failed", NOT_YOUR_FILES),
    ]


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


def test_diagnoza_bierze_ustawienia_ze_startu_uruchomienia_a_nie_zmienione_po_zatrzymaniu(tmp_path: Path) -> None:
    """Diagnoza wyjaśnia Zatrzymanie Uruchomienia, więc sprawdza Rejestr zleceń i folder okresów z jego startu, nawet
    gdy tata zmienił je w Ustawieniach Centrum po Zatrzymaniu."""

    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    elsewhere = tmp_path / "Inny folder"
    chosen_folders(centrum, elsewhere / "ZLECENIA INNE.xlsx", elsewhere)

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Ustawienia taty") == ("passed", "Rejestr zleceń i folder okresów są na miejscu.")


def chosen_folders(centrum: PreparingCentrum, register: Path, periods: Path) -> None:
    """Rejestr zleceń i folder okresów zapisane w sekcji Foldery przed Uruchomieniem, którego Diagnozę test ogląda:
    Diagnoza bierze Ustawienia Centrum ze startu Uruchomienia."""

    saved = centrum.client.put(
        "/api/settings/folders", json={"order_register": str(register), "periods_directory": str(periods)}
    )
    assert saved.status_code == 200, saved.json()


def diagnose(centrum: PreparingCentrum | SettlingCentrum, run_id: str) -> dict[str, Any]:
    response = centrum.client.post(f"/api/runs/{run_id}/diagnosis")
    assert response.status_code == 200, response.json()
    diagnosis: dict[str, Any] = response.json()
    assert "SYN-" not in json.dumps(diagnosis, ensure_ascii=False)
    return diagnosis


def check_states(diagnosis: dict[str, Any]) -> dict[str, str]:
    return {check["label"]: check["state"] for check in diagnosis["checks"]}


def test_diagnoza_bez_przyczyny_na_komputerze_kaze_wyslac_do_maksa(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    assert (diagnosis["explanation"], diagnosis["next_action"], diagnosis["confirms_stop"]) == (NOT_FOUND, "report", False)
    assert set(check_states(diagnosis).values()) == {"passed"}


def explanation_of(message: Message) -> dict[str, str]:
    return {"what": message.what, "where": message.where, "action": message.action}


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_diagnoza_rejestru_w_folderze_bez_dostepu_wyjasnia_niedostepnosc_a_nie_brak_rejestru(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    centrum = preparing_centrum(tmp_path)
    folder = tmp_path / "Rejestr"
    folder.mkdir()
    register = centrum.fixture.register_path.rename(folder / centrum.fixture.register_path.name)
    chosen_folders(centrum, register, centrum.fixture.periods_directory)
    run_id = stopped_for_maks(centrum)
    path_checks(monkeypatch)

    with without_access(folder):
        diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Ustawienia taty") == ("not_checked", "Nie da się teraz odczytać: Rejestr zleceń.")
    assert check(diagnosis, "Pliki w OneDrive") == (
        "not_checked",
        "Nie da się teraz odczytać plików: 1. Pozostałe są na tym komputerze: 2.",
    )
    assert check(diagnosis, "Rejestr zleceń")[0] == "failed"
    assert diagnosis["explanation"]["what"].startswith("Nie można teraz odczytać Rejestru zleceń.")


@NO_ACCESS_ON_WINDOWS
@PATH_CHECKS
def test_diagnoza_folderu_okresow_w_folderze_bez_dostepu_wyjasnia_niedostepnosc_a_nie_brak_folderu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path_checks: Callable[[pytest.MonkeyPatch], None]
) -> None:
    centrum = preparing_centrum(tmp_path)
    onedrive = tmp_path / "OneDrive"
    onedrive.mkdir()
    periods = centrum.fixture.periods_directory.rename(onedrive / centrum.fixture.periods_directory.name)
    chosen_folders(centrum, centrum.fixture.register_path, periods)
    run_id = stopped_for_maks(centrum)
    path_checks(monkeypatch)

    with without_access(onedrive):
        diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Ustawienia taty") == ("not_checked", "Nie da się teraz odczytać: folder okresów.")
    assert diagnosis["explanation"] == explanation_of(preparation_messages.folder_inaccessible(periods))


@NO_ACCESS_ON_WINDOWS
def test_diagnoza_brakujacego_folderu_okresow_wyjasnia_brak_jak_przygotowanie_choc_inny_miesiac_jest_bez_dostepu(
    tmp_path: Path,
) -> None:
    centrum = preparing_centrum(tmp_path)
    year = tmp_path / "Załączniki" / "Rozliczenia 2026"
    (year / "10_Październik_2026" / "INEA").mkdir(parents=True)
    (year / "11_Listopad_2026").mkdir()
    periods = centrum.fixture.periods_directory.rename(year / "11_Listopad_2026" / "INEA")
    (periods / centrum.fixture.period_directory.name).mkdir(exist_ok=True)
    chosen_folders(centrum, centrum.fixture.register_path, periods)
    run_id = stopped_for_maks(centrum)
    periods.rename(year / "11_Listopad_2026" / "INEA-przeniesiony")

    with without_access(year / "10_Październik_2026"):
        diagnosis = diagnose(centrum, run_id)

    assert diagnosis["explanation"] == explanation_of(preparation_messages.periods_directory_missing(periods))


def test_zgloszenie_ma_zmiany_ustawien_z_30_dni_z_folderem_sama_nazwa_bez_sciezki_konta(tmp_path: Path) -> None:
    """Zgłoszenie podaje zmiany Ustawień Centrum z ostatnich 30 dni (ADR 0032), bez danych osobowych: folder i plik
    tylko nazwą, bo pełna ścieżka ma nazwę konta taty."""

    centrum = preparing_centrum(tmp_path)
    account = tmp_path / "Konto Taty Syntetyczne"
    account.mkdir()
    periods = centrum.fixture.periods_directory.rename(account / "Załączniki")
    with (centrum.tool.config / HISTORY_FILE).open("a", encoding="utf-8") as history:
        history.write(_history_row(local_now() - timedelta(days=31), "wyglad.motyw", "dark", "light"))
    chosen_folders(centrum, centrum.fixture.register_path, periods)
    run_id = stopped_for_maks(centrum)

    lines = diagnose(centrum, run_id)["report"]["body"].splitlines()

    at = [f"- {datetime.fromisoformat(row['at']).astimezone():%Y-%m-%d %H:%M} · tata · {SETTINGS_FILE}" for row in _history(centrum)]
    start = lines.index("## Zmiany Ustawień (30 dni)")
    assert lines[start : start + 6] == [
        "## Zmiany Ustawień (30 dni)",
        "",
        f"{at[0]} · foldery.folder_okresow: INEA → Załączniki",
        f"{at[2]} · foldery.folder_okresow: nie ustawiono → INEA",
        f"{at[3]} · foldery.rejestr_zlecen: nie ustawiono → {centrum.fixture.register_path.name}",
        "",
    ]
    assert not zawiera_wartosc("\n".join(lines), account.name)


def test_zgloszenie_podaje_zmiane_listy_wykonawcow_bez_loginu_nazwy_i_adresu(tmp_path: Path) -> None:
    """D4 projektu Ustawień: zmiana Listy Wykonawców w Zgłoszeniu to tylko „dodano”, „usunięto” albo „zmieniono
    Wykonawcę” z nazwami pól, bez loginów, nazw i adresów Wykonawców."""

    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    names = {**WORKERS, "dariusz.fikcyjny2": "Dariusz Zmieniony", "nowy.wykonawca": "Nowy Wykonawca"}
    write_worker_list(centrum.tool.worker_list, worker_list(names, {"nowy.wykonawca": ["nowy@przyklad.invalid"]}))

    body = diagnose(centrum, run_id)["report"]["body"]

    lines = body.splitlines()
    start = lines.index("## Zmiany Ustawień (30 dni)")
    assert lines[start + 2].endswith(
        f"· spoza Centrum · {WORKERS_FILE} · zmieniono Wykonawcę (pola: nazwa); dodano Wykonawcę"
    ), lines[start : start + 4]
    for secret in ("dariusz.fikcyjny2", "Dariusz Zmieniony", "nowy.wykonawca", "Nowy Wykonawca", "nowy@przyklad.invalid"):
        assert not zawiera_wartosc(body, secret), secret
def test_zgloszenie_ma_zmiane_hasla_skrzynki_samym_kluczem_bez_hasla(tmp_path: Path) -> None:
    """Zmiana hasła skrzynki raportów trafia do Zgłoszenia jako „zmieniono: skrzynka.haslo”, bez starego i nowego hasła
    (#1469, D4 projektu Ustawień)."""

    centrum = preparing_centrum(tmp_path)
    access = centrum.tool.config / INBOX_ACCESS_FILE
    access.write_text("raporty@przyklad.invalid\nstare haslo maksa\n", encoding="utf-8")
    centrum.client.get("/api/settings")
    centrum.client.put("/api/settings/inbox-password", json={"password": "nowe haslo taty"})
    chosen_folders(centrum, centrum.fixture.register_path, centrum.fixture.periods_directory)
    run_id = stopped_for_maks(centrum)

    body = diagnose(centrum, run_id)["report"]["body"]

    [secret] = [row for row in _history(centrum) if row["secret"] and row["source"] == "tata"]
    at = f"{datetime.fromisoformat(secret['at']).astimezone():%Y-%m-%d %H:%M}"
    assert f"- {at} · tata · {INBOX_ACCESS_FILE} · zmieniono: skrzynka.haslo" in body.splitlines()
    assert [word for word in ("haslo maksa", "haslo taty", "haslomaksa", "haslotaty") if word in body] == []


def test_zgloszenie_ma_reczna_zmiane_pliku_ustawien_sprzed_chwili_jako_zmiane_spoza_centrum(tmp_path: Path) -> None:
    """Maks zmienia plik Ustawień ręcznie tuż przed Zgłoszeniem i nikt nie czyta Ustawień w międzyczasie: Zgłoszenie
    i tak ma tę zmianę jako „spoza Centrum” (ADR 0032)."""

    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)
    settings = centrum.tool.config / SETTINGS_FILE
    written = settings.read_text(encoding="utf-8")
    assert written.count("motyw: dark\n") == 1
    settings.write_text(written.replace("motyw: dark\n", "motyw: light\n"), encoding="utf-8")

    lines = diagnose(centrum, run_id)["report"]["body"].splitlines()

    [outside] = [row for row in _history(centrum) if row["source"] == "outside"]
    at = f"{datetime.fromisoformat(outside['at']).astimezone():%Y-%m-%d %H:%M}"
    assert f"- {at} · spoza Centrum · {SETTINGS_FILE} · wyglad.motyw: dark → light" in lines


def test_zgloszenie_podaje_chwile_zmiany_ustawien_w_strefie_taty_takze_gdy_jego_strefa_nie_jest_utc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tata i Maks czytają chwilę zmiany w Zgłoszeniu w czasie Polski, a runner CI jest w UTC, więc test wymusza strefę
    taty, w której oba zapisy się różnią."""

    if sys.platform == "win32":
        pytest.skip("time.tzset jest tylko w systemach POSIX")
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    time.tzset()
    try:
        centrum = preparing_centrum(tmp_path)
        centrum.client.put("/api/settings/theme", json={"theme": "light"})
        run_id = stopped_for_maks(centrum)
        lines = diagnose(centrum, run_id)["report"]["body"].splitlines()
    finally:
        monkeypatch.undo()
        time.tzset()

    [theme] = [row for row in _history(centrum) if row["changes"][0]["key"] == "wyglad.motyw"]
    at = datetime.fromisoformat(theme["at"]).astimezone(ZoneInfo("Europe/Warsaw"))
    assert f"- {at:%Y-%m-%d %H:%M} · tata · {SETTINGS_FILE} · wyglad.motyw: dark → light" in lines


def test_zgloszenie_podaje_zmiane_ustawien_z_wydania_z_numerem_wydania_i_id_zmiany(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    at = local_now() - timedelta(days=1)
    with (centrum.tool.config / HISTORY_FILE).open("a", encoding="utf-8") as history:
        history.write(_history_row(at, "wyglad.motyw", "dark", "light", source=RELEASE_SOURCE))
    run_id = stopped_for_maks(centrum)

    lines = diagnose(centrum, run_id)["report"]["body"].splitlines()

    assert f"- {at:%Y-%m-%d %H:%M} · Wydanie 0.9.0 (2026-11-motyw-jasny) · {SETTINGS_FILE} · wyglad.motyw: dark → light" in lines


@NO_ACCESS_ON_WINDOWS
def test_zgloszenie_przy_historii_ustawien_bez_dostepu_mowi_to_zamiast_bez_zmian(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    run_id = stopped_for_maks(centrum)

    with without_access(centrum.tool.config / HISTORY_FILE):
        lines = diagnose(centrum, run_id)["report"]["body"].splitlines()

    start = lines.index("## Zmiany Ustawień (30 dni)")
    assert lines[start : start + 4] == ["## Zmiany Ustawień (30 dni)", "", "- Historii Ustawień nie dało się przeczytać", ""]


def _history(centrum: PreparingCentrum) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = centrum.client.get("/api/settings/history").json()["rows"]
    return rows


RELEASE_SOURCE: Final = {"rodzaj": "wydanie", "wydanie": "0.9.0", "commit": "abc1234", "zmiana": "2026-11-motyw-jasny"}


def _history_row(at: datetime, key: str, before: str, after: str, *, source: dict[str, str] | None = None) -> str:
    """Wiersz Historii Ustawień zapisany wcześniej, z chwilą ``at`` i źródłem ``source``, w formacie pliku
    ``historia-ustawien.jsonl``."""

    row = {
        "v": 1,
        "id": "wiersz-sprzed-okna",
        "kiedy": at.isoformat(),
        "zrodlo": source or {"rodzaj": "tata"},
        "cofa": None,
        "plik": SETTINGS_FILE,
        "sekcja": key.partition(".")[0],
        "zmiany": [{"klucz": key, "przed": before, "po": after}],
        "sekret": False,
        "cofalny": True,
        "wynik": "zapisano",
        "powod": None,
    }
    return json.dumps(row, ensure_ascii=False) + "\n"


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
        ("Lista Wykonawców", "Wykonawców na liście: 3."),
        ("Folder okresu", "Folderu 08_14_09_2026 jeszcze nie ma."),
        ("Pliki okresu w Excelu", "Żaden plik okresu nie jest otwarty w Excelu."),
        ("Aktualność narzędzia", "Najnowsza wersja z GitHuba, commit 3c1d0a9."),
        ("Token do Zgłoszeń", "Na tym komputerze nie ma Tokenu do Zgłoszeń. Zgłoszenie poczeka, aż Maks go wpisze."),
        ("Dziennik Centrum rozliczeń", "Ostatnie wpisy od startu Centrum: 6."),
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
            lambda centrum: centrum.fixture.config_path.write_text("schema_version: 1\nwykonawcy: [", encoding="utf-8"),
            "Lista Wykonawców",
            diagnosis_messages.worker_list_bad(settings_messages.damaged(WORKERS_FILE)).what,
        ),
        (
            lambda centrum: (month_periods_folder(centrum.fixture.periods_directory, "09_Wrzesień_2026") / PERIOD).mkdir(),
            "Folder okresu",
            None,
        ),
    ],
    ids=["brak-rejestru", "brak-folderu-okresow", "uszkodzony-rejestr", "brak-naglowka", "zla-lista-wykonawcow", "folder-okresu-w-miesiacu"],
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
            "Zapisz i zamknij plik w Excelu, potem uruchom ponownie. Jeśli Excel jest zamknięty, a komunikat wraca, "
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

    [folder] = [file for file in row["files"] if file["target"] == "worker_settlements_folder"]
    assert (check(diagnosis, "Pliki okresu w Excelu")[0], folder["count"]) == ("passed", 1)


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
        "Ostatnie wpisy od startu Centrum: 7, w tym nieoczekiwany wyjątek.",
    )


def test_nieoczekiwany_wyjatek_ktory_wraca_w_diagnozie_zostawia_sprawdzenie_niesprawdzone_a_zgloszenie_mozna_wyslac(
    tmp_path: Path,
) -> None:
    def fail_unexpectedly(path: Path) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(source=on_register_read(fail_unexpectedly)))
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]

    diagnosis = diagnose(centrum, run_id)
    report = centrum.client.post(f"/api/runs/{run_id}/report")

    assert check(diagnosis, "Rejestr zleceń") == ("not_checked", "Nie udało się sprawdzić: nieoczekiwany błąd.")
    assert check_states(diagnosis)["Dziennik Centrum rozliczeń"] == "passed"
    assert (diagnosis["explanation"], diagnosis["next_action"]) == (NOT_FOUND, "report")
    assert 'nieoczekiwany-wyjatek typ=RuntimeError miejsce="Diagnoza: Rejestr zleceń"' in diagnosis["report"]["body"]
    assert (report.status_code, report.json()["state"]) == (200, "queued")


@pytest.mark.parametrize(
    ("make_centrum", "template"),
    [(settling_centrum, "Wzorzec rozliczenia pracownika"), (preparing_centrum, "Wzorzec rozliczenia wewnętrznego")],
    ids=["Przebieg rozliczeń", "Przygotowanie pliku zbiorczego"],
)
def test_nieoczekiwany_wyjatek_czytnika_wzorca_w_uruchomieniu_wraca_w_jego_diagnozie(
    tmp_path: Path, make_centrum: Callable[..., Any], template: str
) -> None:
    """Uruchomienie procesu i Diagnoza sprawdzają Wzorzec tym samym ``template_check`` Centrum, więc usterka czytnika
    zatrzymuje Uruchomienie i wraca w jego Diagnozie (#1192 r1: Przygotowanie sprawdzało Wzorzec na dysku bez testu)."""

    def fail_unexpectedly(template: TemplateFile) -> NoReturn:
        raise RuntimeError("nieprzewidziany błąd przy SYN-001")

    centrum = make_centrum(tmp_path, surroundings=Surroundings(template_check=fail_unexpectedly))
    stopped = run_to_end(centrum, dry_run=True)

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    assert (stopped["result"]["ending"], phase_states(stopped)["Sprawdzanie"]) == ("unexpected", "failed")
    assert check(diagnosis, template) == ("not_checked", "Nie udało się sprawdzić: nieoczekiwany błąd.")


def test_wyjatek_przy_sprawdzaniu_jednego_wzorca_nie_ukrywa_wyniku_drugiego(tmp_path: Path) -> None:
    internal_template_failing = False

    def check_template(template: TemplateFile) -> None:
        if internal_template_failing and template.path == centrum.fixture.internal_template_path:
            raise RuntimeError("nieprzewidziany błąd przy SYN-001")
        template.check()

    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(template_check=check_template))
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
        "Ostatnie wpisy od startu Centrum: 7, w tym nieoczekiwany wyjątek.",
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
        "Ostatnie wpisy od startu Centrum: 8, w tym nieoczekiwany wyjątek.",
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

    assert check(diagnosis, "Dziennik Centrum rozliczeń") == ("passed", "Ostatnie wpisy od startu Centrum: 7.")


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
        ("Lista Wykonawców", "passed"),
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
    assert centrum.client.post("/api/runs", json={"process": "efenix", "period": PERIOD, "mode": "RUN"}).status_code == 200
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
    """Pliki taty bez dziennika Centrum i Logów Uruchomienia (``logs``) oraz kolejki Skrzynki Zgłoszeń, bo Centrum
    dopisuje do nich Diagnozę."""

    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not {ToolDirectory(root).log_path.parent.name, QUEUE_DIRECTORY} & set(path.relative_to(root).parts)
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
    write_report_key(centrum.tool)
    centrum.fixture.collective_template_path.unlink()
    stopped = run_to_end(centrum, dry_run=True)
    box_now_answers(centrum, Refused())

    diagnosis = diagnose(centrum, stopped["run"]["id"])

    assert check(diagnosis, "Token do Zgłoszeń") == REFUSED_KEY
    assert diagnosis["explanation"] == stopped["result"]["stops"][0]
    assert f"| Token do Zgłoszeń | nie przeszło | {REFUSED_KEY[1]} |" in diagnosis["report"]["body"]


def test_diagnoza_bez_innej_przyczyny_i_z_odrzuconym_kluczem_nie_znajduje_przyczyny(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)
    box_now_answers(centrum, Refused())

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Token do Zgłoszeń") == REFUSED_KEY
    assert (diagnosis["explanation"], diagnosis["next_action"]) == (NOT_FOUND, "report")


def test_diagnoza_z_tokenem_przyjetym_przez_skrzynke_mowi_ze_skrzynka_go_przyjmuje(tmp_path: Path) -> None:
    centrum = preparing_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = stopped_for_maks(centrum)

    diagnosis = diagnose(centrum, run_id)

    assert check(diagnosis, "Token do Zgłoszeń") == ("passed", "Skrzynka Zgłoszeń przyjmuje Token do Zgłoszeń.")


def test_diagnoza_z_kluczem_bez_sieci_go_nie_sprawdzila(tmp_path: Path) -> None:
    offline = FakeReportBox(search_failure=Unreachable())  # także Logi Uruchomienia nie dochodzą do skrzynki
    centrum = preparing_centrum(tmp_path, surroundings=Surroundings(report_box=offline))
    write_report_key(centrum.tool)
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
        (
            # Chwila z nagłówka jest w UTC, a tata czyta godzinę swojego komputera (tu 3:49 czasu lokalnego).
            FakeGitHub(limited=datetime(2026, 11, 8, 3, 49).astimezone(timezone.utc)),
            "Nie sprawdzono: GitHub chwilowo nie odpowiada na pytania o nową wersję. Centrum sprawdzi ponownie po 03:49.",
        ),
    ],
    ids=["brak-sieci", "bez-gita", "bez-wydania", "limit-githuba"],
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
