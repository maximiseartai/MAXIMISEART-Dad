"""Uwaga taty przypięta do Uruchomienia procesu (ADR 0015, #322) przez HTTP API Centrum z fałszywą Skrzynką."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, Final

import pytest

from rozliczenia import settlement_process
from rozliczenia.centrum.dad_cases import DAD_CASES_FILE
from rozliczenia.centrum.keyed_box import LIST_LAG_S
from rozliczenia.centrum.report_box import REPOSITORY, Refused, Rejected, Unreachable
from rozliczenia.telemetry import MetricsStore

from tests.fixtures.centrum import FakeReportBox, write_report_key
from tests.fixtures.centrum_processes import SettlingCentrum, run_logs_handled, run_to_end, settling_centrum
from tests.fixtures.potomne import wait_for
from tests.fixtures.settlement import PERIOD

TITLE = "Podgląd pokazał dwa razy tego samego Wykonawcę"
BODY = "Na liście Szablonów pracownika jest dwa razy ten sam Wykonawca."
VERSION = "wersja narzędzia 3c1d0a9"
UNKNOWN_RUN = (
    "Tego Uruchomienia nie ma już w historii Centrum rozliczeń. Wybierz inne Uruchomienie albo wyślij Uwagę ogólną."
)


def box(centrum: SettlingCentrum) -> FakeReportBox:
    return centrum.surroundings.report_box


def queued(centrum: SettlingCentrum, label: str | None = None) -> list[Path]:
    pattern = "*.json" if label is None else f"*-{label}-*.json"
    return sorted((centrum.tmp_path / "config" / "zgloszenia" / "kolejka").glob(pattern))


def run_line(centrum: SettlingCentrum, mode: str, result: str) -> str:
    [record] = centrum.metric_records()
    started = datetime.fromisoformat(record["started_at"]).astimezone()
    return f"Uruchomienie: Przebieg rozliczeń · {PERIOD} · {mode} · {result} · {started:%d.%m.%Y, %H:%M} · {VERSION}"


def logs_comment(centrum: SettlingCentrum, run_id: str) -> str:
    assert wait_for(lambda: queued(centrum) == []), "Logi Uruchomienia nie wyszły z kolejki"
    [thread] = box(centrum).background_issues
    position = next(number for number, comment in enumerate(thread.comments, start=1) if run_id in comment)
    return f"https://github.com/{REPOSITORY}/issues/{thread.number}#issuecomment-{position}"


def note(run_id: str) -> dict[str, str]:
    return {"title": TITLE, "body": BODY, "run_id": run_id}


def rejected_logs_line(run_id: str) -> str:
    return (
        f"Logi Uruchomienia: nie dotarły, Skrzynka odrzuciła ich treść (Uruchomienie {run_id}). "
        "Odnośnik przyjdzie w komentarzu, gdy dotrą."
    )


def logs_rejections(centrum: SettlingCentrum) -> int:
    log = centrum.log_path.read_text(encoding="utf-8")
    return log.count(f"etykieta=logi-uruchomienia okres={PERIOD} przyczyna=odmowa-tresci")


def pinned_after_rejected_logs(tmp_path: Path, *, rejected_starts: int) -> tuple[SettlingCentrum, str]:
    """Skrzynka odrzuca Logi podglądu przy ``rejected_starts`` startach Centrum, a przy pierwszym idzie przypięta Uwaga."""

    centrum = settling_centrum(tmp_path)
    box(centrum).background_comment_outcomes.extend([Rejected()] * rejected_starts)
    write_report_key(centrum.tool)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    assert wait_for(lambda: logs_rejections(centrum) == 1), "Skrzynka nie odrzuciła Logów"

    sent = centrum.client.post("/api/dad-notes", json=note(run_id))

    assert sent.json() == {"state": "sent"}
    return centrum, run_id


def test_uwaga_przypieta_do_uruchomienia_niesie_jego_linie_i_odnosnik_do_komentarza_logow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    logs = logs_comment(centrum, run_id)

    draft = centrum.client.post("/api/dad-notes/draft", json=note(run_id))
    sent = centrum.client.post("/api/dad-notes", json=note(run_id))

    assert sent.json() == {"state": "sent"}
    [issue] = box(centrum).issues_with("uwaga-taty")
    expected = f"{BODY}\n\n{run_line(centrum, 'podgląd', 'OK')}\n[Logi Uruchomienia]({logs})"
    assert (issue.title, issue.body) == (TITLE, expected)
    assert draft.json() == {"title": TITLE, "body": expected}


def _as_is(centrum: SettlingCentrum) -> None:
    return None


def _settlements_exist(centrum: SettlingCentrum) -> None:
    centrum.worker_settlements.mkdir()


def _broken_worker_config(centrum: SettlingCentrum) -> None:
    centrum.configuration.worker_config.write_text(":: nie yaml", encoding="utf-8")


RESULTS: Final[dict[str, tuple[Callable[[SettlingCentrum], None], bool, bool, str]]] = {
    "ok": (_as_is, False, True, "podgląd · OK"),
    "do-sprawdzenia": (_as_is, True, True, "podgląd · do sprawdzenia"),
    "zatrzymano-dla-taty": (_settlements_exist, False, False, "zapis · zatrzymano"),
    "blad-do-maksa": (_broken_worker_config, False, False, "zapis · błąd"),
}


@pytest.mark.parametrize(("steer", "unmapped", "dry_run", "words"), RESULTS.values(), ids=RESULTS.keys())
def test_linia_uruchomienia_w_uwadze_nazywa_tryb_i_wynik_jak_karta_uruchomienia(
    tmp_path: Path, steer: Callable[[SettlingCentrum], None], unmapped: bool, dry_run: bool, words: str
) -> None:
    centrum = settling_centrum(tmp_path, include_unmapped=unmapped)
    steer(centrum)
    run_id = run_to_end(centrum, dry_run=dry_run)["run"]["id"]

    draft = centrum.client.post("/api/dad-notes/draft", json={"title": TITLE, "run_id": run_id})

    mode, result = words.split(" · ")
    assert draft.json()["body"] == (
        f"{run_line(centrum, mode, result)}\nLogi Uruchomienia: w drodze (Uruchomienie {run_id})"
    )


def test_uwaga_do_nieznanego_uruchomienia_jest_odrzucona_bez_wysylki(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_to_end(centrum, dry_run=True)

    draft = centrum.client.post("/api/dad-notes/draft", json=note("nieznane-uruchomienie"))
    sent = centrum.client.post("/api/dad-notes", json=note("nieznane-uruchomienie"))

    assert [(draft.status_code, draft.json()), (sent.status_code, sent.json())] == [(404, {"message": UNKNOWN_RUN})] * 2
    assert box(centrum).issues == []
    assert queued(centrum, "uwaga-taty") == []
    assert not (tmp_path / "config" / DAD_CASES_FILE).exists()


def test_uwaga_do_uruchomienia_z_logami_w_kolejce_czeka_i_wychodzi_po_logach_z_odnosnikiem(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    run_logs_handled(centrum)

    draft = centrum.client.post("/api/dad-notes/draft", json=note(run_id)).json()
    sent = centrum.client.post("/api/dad-notes", json=note(run_id))

    assert sent.json() == {"state": "waiting", "waits_for": "key"}
    waiting = f"{run_line(centrum, 'podgląd', 'OK')}\nLogi Uruchomienia: w drodze (Uruchomienie {run_id})"
    assert draft["body"] == f"{BODY}\n\n{waiting}"
    assert box(centrum).issues == []

    write_report_key(centrum.tool)
    centrum.restart()
    with centrum.client:
        assert box(centrum).wait_until(lambda fake: len(fake.issues_with("uwaga-taty")) == 1)
        logs = logs_comment(centrum, run_id)

    [issue] = box(centrum).issues_with("uwaga-taty")
    assert issue.body == f"{BODY}\n\n{run_line(centrum, 'podgląd', 'OK')}\n[Logi Uruchomienia]({logs})"


def test_odnosnik_do_logow_wyslanych_przez_poprzednie_centrum_jest_od_razu_w_uwadze(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(centrum.tool)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    logs = logs_comment(centrum, run_id)

    centrum.restart()
    draft = centrum.client.post("/api/dad-notes/draft", json=note(run_id))

    assert draft.json()["body"].endswith(f"\n[Logi Uruchomienia]({logs})")


def test_okno_uwagi_pokazuje_szesc_najnowszych_uruchomien_z_centrum_i_starsze_zaznaczone(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    own = run_to_end(centrum, dry_run=True)["run"]["id"]
    store = MetricsStore(centrum.metrics_path, settlement_process.PROCESS.counter_names)
    [record] = store.read()
    started = datetime.fromisoformat(record["started_at"])
    remembered = tmp_path / "config" / "centrum-uruchomienia.jsonl"

    def earlier(minutes: int, centrum_line: dict[str, str] | None = None) -> None:
        at = (started - timedelta(minutes=minutes)).isoformat()
        store.append({**record, "started_at": at})
        if centrum_line is not None:
            with remembered.open("a", encoding="utf-8") as lines:
                lines.write(json.dumps({"process": "settlement", "started_at": at, **centrum_line}) + "\n")

    earlier(-1)
    earlier(5, {})
    for hours in range(1, 8):
        earlier(60 * hours, {"run_id": f"starsze-{hours}"})

    def picked(**query: Any) -> list[str | None]:
        response = centrum.client.get("/api/dad-notes/runs", params=query)
        assert response.status_code == 200
        return [run["run_id"] for run in response.json()]

    newest = [own, "starsze-1", "starsze-2", "starsze-3", "starsze-4", "starsze-5"]
    assert picked() == newest
    assert picked(selected="starsze-7") == [*newest, "starsze-7"]
    assert picked(selected="starsze-3") == picked(selected="nieznane") == newest


def test_uwaga_wyslana_przed_logami_dostaje_odnosnik_w_komentarzu_gdy_logi_dotra_po_ponownym_starcie(
    tmp_path: Path,
) -> None:
    centrum, run_id = pinned_after_rejected_logs(tmp_path, rejected_starts=2)
    [issue] = box(centrum).issues_with("uwaga-taty")
    assert issue.body == f"{BODY}\n\n{run_line(centrum, 'podgląd', 'OK')}\n{rejected_logs_line(run_id)}"
    waiting = [f"logi-uruchomienia-{run_id[:8]}.json", f"uwaga-taty-{run_id[:8]}.json"]
    assert wait_for(lambda: [path.name.split("-", 2)[2] for path in queued(centrum)] == waiting)

    centrum.restart()
    with centrum.client:
        assert wait_for(lambda: logs_rejections(centrum) == 2), "Skrzynka nie odrzuciła Logów drugi raz"
    assert [path.name.split("-", 2)[2] for path in queued(centrum)] == waiting
    centrum.restart()
    with centrum.client:
        assert box(centrum).wait_until(lambda fake: issue.comments != [])
        logs = logs_comment(centrum, run_id)

    assert issue.comments == [f"[Logi Uruchomienia]({logs}) dotarły do Skrzynki po tej Uwadze (Uruchomienie {run_id})."]


def test_dwie_uwagi_przypiete_do_roznych_uruchomien_dostaja_odnosniki_do_swoich_logow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    first = run_to_end(centrum, dry_run=True)["run"]["id"]
    second = run_to_end(centrum, dry_run=True)["run"]["id"]
    assert wait_for(lambda: len(queued(centrum, "logi-uruchomienia")) == 2)
    for run_id in (first, second):
        sent = centrum.client.post("/api/dad-notes", json={"title": run_id, "run_id": run_id})
        assert sent.json() == {"state": "waiting", "waits_for": "key"}

    write_report_key(centrum.tool)
    centrum.restart()
    with centrum.client:
        assert box(centrum).wait_until(lambda fake: len(fake.issues_with("uwaga-taty")) == 2)
        links = {run_id: logs_comment(centrum, run_id) for run_id in (first, second)}

    footers = {issue.title: issue.body.splitlines()[-1] for issue in box(centrum).issues_with("uwaga-taty")}
    assert footers == {run_id: f"[Logi Uruchomienia]({links[run_id]})" for run_id in (first, second)}


def test_uwaga_do_uruchomienia_bez_logow_w_kolejce_mowi_ze_nie_powstaly(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    run_id = run_to_end(centrum, dry_run=True)["run"]["id"]
    run_logs_handled(centrum)
    for path in queued(centrum, "logi-uruchomienia"):
        path.unlink()
    write_report_key(centrum.tool)

    sent = centrum.client.post("/api/dad-notes", json=note(run_id))

    assert sent.json() == {"state": "sent"}
    [issue] = box(centrum).issues_with("uwaga-taty")
    missing = f"Logi Uruchomienia: nie powstały albo nie da się ich wysłać (Uruchomienie {run_id})"
    assert issue.body == f"{BODY}\n\n{run_line(centrum, 'podgląd', 'OK')}\n{missing}"
    assert wait_for(lambda: queued(centrum) == [])
    assert issue.comments == []


def test_odrzucone_logi_innego_uruchomienia_nie_zmieniaja_linii_uwagi_bez_logow(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    without_logs = run_to_end(centrum, dry_run=True)["run"]["id"]
    run_logs_handled(centrum)
    for path in queued(centrum, "logi-uruchomienia"):
        path.unlink()
    write_report_key(centrum.tool)
    box(centrum).background_comment_outcomes.append(Rejected())
    rejected = run_to_end(centrum, dry_run=True)["run"]["id"]
    assert wait_for(lambda: logs_rejections(centrum) == 1), "Skrzynka nie odrzuciła Logów"

    sent = centrum.client.post("/api/dad-notes", json=note(without_logs))

    assert sent.json() == {"state": "sent"}
    [issue] = box(centrum).issues_with("uwaga-taty")
    missing = f"Logi Uruchomienia: nie powstały albo nie da się ich wysłać (Uruchomienie {without_logs})"
    assert issue.body.splitlines()[-1] == missing
    assert wait_for(
        lambda: [path.name.split("-", 2)[2] for path in queued(centrum)] == [f"logi-uruchomienia-{rejected[:8]}.json"]
    )


def test_odrzucone_logi_ktore_zniknely_z_kolejki_po_uwadze_daja_komentarz_ze_nie_dotra(tmp_path: Path) -> None:
    centrum, run_id = pinned_after_rejected_logs(tmp_path, rejected_starts=1)
    [issue] = box(centrum).issues_with("uwaga-taty")
    assert wait_for(lambda: len(queued(centrum)) == 2)
    for path in queued(centrum, "logi-uruchomienia"):
        path.unlink()

    centrum.restart()
    with centrum.client:
        assert box(centrum).wait_until(lambda fake: issue.comments != [])

    assert issue.comments == [f"Logi Uruchomienia nie dotrą: Centrum przestało je wysyłać (Uruchomienie {run_id})."]
    assert wait_for(lambda: queued(centrum) == [])


def logs_sent(centrum: SettlingCentrum, run_id: str) -> bool:
    return any(run_id in comment for logs in box(centrum).background_issues for comment in logs.comments)


def test_komentarz_do_usunietego_issue_uwagi_kolejka_porzuca_raz_i_wiecej_o_nie_nie_pyta(tmp_path: Path) -> None:
    centrum, run_id = pinned_after_rejected_logs(tmp_path, rejected_starts=1)
    [issue] = box(centrum).issues_with("uwaga-taty")
    assert wait_for(lambda: len(queued(centrum)) == 2)
    [comment] = queued(centrum, "uwaga-taty")
    assert centrum.client.post("/api/dad-notes", json={"title": "Inna Uwaga"}).json() == {"state": "sent"}
    centrum.tool.report_key.unlink()
    behind = centrum.client.post("/api/dad-notes", json={"title": "Uwaga za komentarzem"})
    assert behind.json() == {"state": "waiting", "waits_for": "key"}
    # Maks usuwa issue Uwagi, gdy lista issue już je pokazuje: usunięte w LIST_LAG_S po założeniu lista issue z etykietą
    # pokazuje z zapisów KeyedBox, więc kolejka porzuca komentarz do niego dopiero po budzeniu (#879).
    centrum.surroundings.clock.pause(LIST_LAG_S)
    box(centrum).issues.remove(issue)
    write_report_key(centrum.tool)

    centrum.restart()
    with centrum.client:
        assert wait_for(lambda: logs_sent(centrum, run_id)), "Logi nie dotarły po ponownym starcie"
        assert wait_for(lambda: queued(centrum) == []), "kolejka nie wysłała wszystkiego po komentarzu do usuniętej Uwagi"
    assert [note.title for note in box(centrum).issues_with("uwaga-taty")] == ["Inna Uwaga", "Uwaga za komentarzem"]

    centrum.restart()
    with centrum.client:
        later = centrum.client.post("/api/dad-notes", json={"title": "Następna Uwaga"})

    assert later.json() == {"state": "sent"}
    assert issue.comments == []
    log = centrum.log_path.read_text(encoding="utf-8").splitlines()
    [dropped] = [line for line in log if "skrzynka-porzucono" in line]
    assert dropped.endswith(f"skrzynka-porzucono etykieta=uwaga-taty plik={comment.name} numer={issue.number}")
    after = log[log.index(dropped) :]
    assert [line for line in after if "skrzynka-czeka etykieta=uwaga-taty" in line] == []


def _without_network(centrum: SettlingCentrum) -> None:
    box(centrum).search_failure = Unreachable()


def _refused_listing(centrum: SettlingCentrum) -> None:
    box(centrum).search_failure = Refused()


def _without_key(centrum: SettlingCentrum) -> None:
    centrum.tool.report_key.unlink()


UNCHECKABLE: Final[dict[str, tuple[Callable[[SettlingCentrum], None], str]]] = {
    "brak-sieci": (_without_network, "brak-sieci"),
    "odmowa-dostepu": (_refused_listing, "odmowa"),
    "brak-klucza": (_without_key, "brak-klucza"),
}


@pytest.mark.parametrize(("steer", "cause"), UNCHECKABLE.values(), ids=UNCHECKABLE.keys())
def test_komentarz_do_issue_uwagi_zostaje_w_kolejce_gdy_nie_da_sie_sprawdzic_czy_issue_jest(
    tmp_path: Path, steer: Callable[[SettlingCentrum], None], cause: str
) -> None:
    centrum, _ = pinned_after_rejected_logs(tmp_path, rejected_starts=1)
    [issue] = box(centrum).issues_with("uwaga-taty")
    assert wait_for(lambda: len(queued(centrum)) == 2)
    [comment] = queued(centrum, "uwaga-taty")
    for logs in queued(centrum, "logi-uruchomienia"):
        logs.unlink()
    box(centrum).issues.remove(issue)
    steer(centrum)

    waiting = f"skrzynka-czeka etykieta=uwaga-taty okres=bez-okresu przyczyna={cause}"
    centrum.restart()
    with centrum.client:
        assert wait_for(lambda: waiting in centrum.log_path.read_text(encoding="utf-8"))

    assert comment in queued(centrum, "uwaga-taty")
    assert "skrzynka-porzucono" not in centrum.log_path.read_text(encoding="utf-8")


def test_druga_przypieta_uwaga_po_odrzuconych_logach_dostaje_odnosnik_takze_zamknieta(tmp_path: Path) -> None:
    centrum = settling_centrum(tmp_path)
    write_report_key(centrum.tool)
    delivered = run_to_end(centrum, dry_run=True)["run"]["id"]
    logs_comment(centrum, delivered)
    assert centrum.client.post("/api/dad-notes", json={"title": "A", "run_id": delivered}).json() == {"state": "sent"}
    box(centrum).background_comment_outcomes.append(Rejected())
    late = run_to_end(centrum, dry_run=True)["run"]["id"]
    assert wait_for(lambda: logs_rejections(centrum) == 1), "Skrzynka nie odrzuciła Logów"
    assert centrum.client.post("/api/dad-notes", json={"title": "B", "run_id": late}).json() == {"state": "sent"}
    first, second = box(centrum).issues_with("uwaga-taty")
    assert second.body.splitlines()[-1] == rejected_logs_line(late)
    box(centrum).close(second.number)

    centrum.restart()
    with centrum.client:
        assert box(centrum).wait_until(lambda fake: second.comments != [])
        logs = logs_comment(centrum, late)

    assert second.comments == [f"[Logi Uruchomienia]({logs}) dotarły do Skrzynki po tej Uwadze (Uruchomienie {late})."]
    assert first.comments == []
