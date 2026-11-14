"""Kolejka Skrzynki Zgłoszeń (``outbox``): wysyłki, które Centrum wysyła samo, w częściach i po porażce skrzynki.

Seam z dwoma wejściami (Kontrola ilości teraz, Logi Uruchomienia od #320), więc podział na części i kolejka są
sprawdzone tu raz, przez ``Post`` i ``Outbox``, na fałszywej skrzynce. Treść ponad 65 536 znaków jest przez HTTP
Centrum nieosiągalna rozsądnym kosztem.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timezone
import gzip
import itertools
import json
from pathlib import Path
import shutil
import sys
import threading
import time
from typing import Final

import pytest

from rozliczenia.centrum.atomic_file import replace_atomically
from rozliczenia.centrum.keyed_box import LIST_LAG_S, OPENING_FILE, BoxState, KeyedBox, NotesFile
from rozliczenia.centrum.log import CentrumLog
from rozliczenia.client_data import Outgoing, logs_text, tool
from rozliczenia.centrum.outbox import (
    DRAIN,
    PART_LIMIT,
    RETRY_S,
    TEXT_LIMIT,
    ArchiveFile,
    Frame,
    KnownIssue,
    NewIssue,
    Outbox,
    PeriodThread,
    Post,
    QueueState,
    Rank,
)
from rozliczenia.centrum.report_box import COMMENT_LIMIT, Refused, Rejected, Sent, Unreachable
from rozliczenia.centrum.reports import report_target

from atrapy.skrzynka import ArchivedFile, BoxArchive, BoxIssue
from tests.fixtures.centrum import FakeReportBox
from tests.fixtures.clock import ManualClock
from tests.fixtures.potomne import wait_for
from atrapy.sluchacz_kolejki import QueueListener
from atrapy.widok_skrzynki import shown
from tests.fixtures.stare_centrum import SharedBox, killed_after_comment, old_centrum, queue_on
from tests.fixtures.plik_kolejki import bieg_do_pliku_kolejki
from tests.fixtures.znane_luki import assert_znane_luki, modul, ruff_i_mypy, wymaga_ruff_i_mypy, zapisz

KEY = "github_pat_SYNTETYCZNY_KLUCZ"
THREAD = PeriodThread(
    label="kontrola-ilosci",
    line=tool("- Kontrola ilości okresu: 08_14_09_2026"),
    closed="new_issue",
    title=tool("Kontrola ilości 08_14_09_2026: 3 różnice"),
)
RUN_ID = "3f2a9c1b8e7d4f0a9b1c2d3e4f5a6b7c"
# Następne Uruchomienia: każda Kontrola ilości to inna wysyłka, z identyfikatorem swojego Uruchomienia.
NEXT_RUN_IDS = ("9b1c2d3e4f5a6b7c3f2a9c1b8e7d4f0a", "c2d3e4f5a6b7c3f2a9c1b8e7d4f0a9b1")


def unframed(_number: int, _count: int, text: Outgoing) -> Outgoing:
    return text


def numbered(number: int, count: int, text: Outgoing) -> Outgoing:
    return tool(f"Część {number}/{count}\n\n") + text


def post(blocks: list[str], *, frame: Frame = numbered, run_id: str = RUN_ID) -> Post:
    return Post.of(THREAD, period="08_14_09_2026", run_id=run_id, blocks=[tool(block) for block in blocks], frame=frame)


ROOT = Path(__file__).resolve().parents[1]


class Queue:
    """Kolejka na folderze w ``tmp_path`` ze skrzynką ``box`` i kluczem ``key`` (``None``: bez klucza).

    ``delivered`` to Uruchomienie i numer issue każdej wysyłki, którą przyjęła skrzynka (``listener``), a ``now`` to
    zegar ścienny komputera (``None``: domyślny zegar kolejki).
    """

    def __init__(
        self,
        tmp_path: Path,
        box: FakeReportBox,
        key: str | None = KEY,
        listener: QueueListener | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.directory = tmp_path / "config" / "zgloszenia" / "kolejka"
        self.opening = tmp_path / "config" / OPENING_FILE
        self.log_path = tmp_path / "logs" / "centrum-rozliczen.log"
        self.box = box
        self.key = key
        self.clock = ManualClock()
        self.now = now
        self.listener = listener or QueueListener()
        self.delivered = self.listener.numbers
        self.outbox = self.restarted()

    def restarted(self) -> Outbox:
        """Kolejka nowego startu Centrum na tym samym folderze."""

        log = CentrumLog(self.log_path)
        notes = NotesFile(self.opening, replace_atomically, log.box_notes_unavailable)
        keyed = KeyedBox(self.box, lambda: self.key, clock=self.clock, opening=notes)
        if self.now is None:
            return Outbox(self.directory, keyed, log, clock=self.clock, listener=self.listener)
        return Outbox(self.directory, keyed, log, clock=self.clock, listener=self.listener, now=self.now)

    def passed(self) -> None:
        """Czeka, aż przejście kolejki, które właśnie ruszyło (``resume``, ``send_in_background``), się skończy."""

        assert not self.outbox.wait_delivered("", THREAD.label, timeout_s=30)

    def queued(self, *texts: str) -> list[str]:
        """Pliki kolejki z poprzedniej pracy Centrum, po jednym na tekst i Uruchomienie, w tej kolejności."""

        self.directory.mkdir(parents=True, exist_ok=True)
        names = [f"20261023T1015{second:02d}000000Z-0001-kontrola-ilosci-3f2a9c1b.json" for second in range(len(texts))]
        run_ids = (RUN_ID, *NEXT_RUN_IDS)[: len(texts)]
        for name, text, run_id in zip(names, texts, run_ids, strict=True):
            (self.directory / name).write_text(post([text], run_id=run_id).to_json(), encoding="utf-8")
        return names

    def files(self) -> list[str]:
        """Pliki kolejki i ich pliki tymczasowe (``*.json.tmp``), bez pliku blokady folderu."""

        return sorted(path.name for path in self.directory.glob("*.json*"))

    def log(self) -> str:
        return self.log_path.read_text(encoding="utf-8") if self.log_path.is_file() else ""


def test_bloki_ktore_sie_mieszcza_ida_w_calosci_w_kolejnosci() -> None:
    first, second, third = "a" * 30_000, "b" * 30_000, "c" * 30_000

    assert post([first, second, third], frame=unframed).parts == (first + second, third)


def test_blok_dluzszy_niz_komentarz_jest_ciety_a_nic_nie_ginie() -> None:
    blocks = ["poczatek\n", "x" * 150_000, "koniec\n"]

    parts = post(blocks, frame=unframed).parts

    assert "".join(parts) == "".join(blocks)
    assert len(parts) == 3
    assert all(len(part) <= COMMENT_LIMIT for part in parts)


def test_czesc_ponad_limit_komentarza_to_blad_programu() -> None:
    with pytest.raises(ValueError, match="komentarzu"):
        Post.of(
            THREAD,
            period="08_14_09_2026",
            run_id=RUN_ID,
            blocks=[tool("x" * 60_000)],
            frame=lambda _number, _count, text: tool("nagłówek " * 1_000) + text,
        )


@pytest.mark.parametrize(
    "run_id",
    ["", "x" * 65, "3f2a9c1b 8e7d4f0a", "3f2a9c1b\n8e7d4f0a"],
    ids=["pusty", "dluzszy-niz-64-znaki", "ze-spacja", "w-dwoch-liniach"],
)
def test_identyfikator_wysylki_pusty_dlugi_ze_spacja_albo_w_dwoch_liniach_to_blad_programu(run_id: str) -> None:
    # Znacznik wysyłki to jedna linia z identyfikatorem jako jednym słowem, w zapasie _MARK_RESERVE każdego komentarza.
    assert Post(THREAD, period="08_14_09_2026", run_id="x" * 64, header=None, parts=(tool("treść"),)).run_id == "x" * 64

    with pytest.raises(ValueError, match="Identyfikator wysyłki"):
        Post(THREAD, period="08_14_09_2026", run_id=run_id, header=None, parts=(tool("treść"),))


def test_granica_tresci_liczy_znaki_a_nie_bajty_takze_z_polskimi_literami() -> None:
    first_line = len(f"{THREAD.line}\n\n")

    def opening(text: str) -> Post:
        return Post(THREAD, period="08_14_09_2026", run_id=RUN_ID, header=None, parts=(tool(text),))

    longest = opening("ą" * (TEXT_LIMIT - first_line))

    assert len(longest.opening()[0]) == TEXT_LIMIT
    assert len(longest.opening()[0].encode("utf-8")) > TEXT_LIMIT
    with pytest.raises(ValueError, match="komentarzu"):
        opening("ą" * (TEXT_LIMIT - first_line + 1))


def test_podzial_na_czesci_liczy_znaki_a_nie_bajty_takze_z_polskimi_literami() -> None:
    first, second = "ą" * 40_000, "ę" * 32_000
    longer = "ą" * 70_000

    assert post([first, second], frame=unframed).parts == (first, second)
    parts = post([longer], frame=unframed).parts
    assert "".join(parts) == longer
    assert len(parts) == 2
    assert all(len(part) <= COMMENT_LIMIT for part in parts)


def test_wysylka_ponad_limit_to_issue_z_pierwsza_czescia_i_komentarze_z_kolejnymi(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    blocks = ["## Różnice\n", "x" * 40_000, "y" * 40_000]

    queue.outbox.post(post(blocks))

    assert queue.box.wait_until(lambda box: bool(box.issues) and len(box.issues[0].comments) == 1)
    [issue] = queue.box.issues_with("kontrola-ilosci")
    assert issue.title == THREAD.title
    assert issue.body.startswith(f"{THREAD.line}\n\nCzęść 1/2\n\n## Różnice\n")
    assert issue.comments == [f"Część 2/2\n\n{'y' * 40_000}"]
    assert wait_for(lambda: queue.files() == [])
    assert "skrzynka-wyslano etykieta=kontrola-ilosci okres=08_14_09_2026 numer=1" in queue.log()
    assert "x" * 10 not in queue.log()


def test_bez_sieci_wysylka_czeka_w_pliku_i_idzie_przy_nastepnej_wysylce_po_kolei_do_issue_okresu(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Unreachable()]))

    queue.outbox.post(post(["pierwsza\n"]))
    assert wait_for(lambda: "przyczyna=brak-sieci" in queue.log())
    [waiting] = queue.files()
    assert waiting.endswith(f"-kontrola-ilosci-{RUN_ID[:8]}.json")
    assert "pierwsza" not in queue.log()
    queue.clock.pause(LIST_LAG_S)  # po zakładaniu bez odpowiedzi KeyedBox tyle nie zakłada issue (#879)

    queue.outbox.post(post(["druga\n"], run_id=NEXT_RUN_IDS[0]))

    assert queue.box.wait_until(lambda box: bool(box.issues) and bool(box.issues[0].comments))
    [issue] = queue.box.issues
    assert issue.body.splitlines()[-1] == "pierwsza"
    assert issue.comments == ["Część 1/1\n\ndruga\n"]
    assert wait_for(lambda: queue.files() == [])


LOGS = PeriodThread(
    label="logi-uruchomienia",
    line=tool("- Logi Uruchomień okresu: 08_14_09_2026"),
    closed="reuse",
    title=tool("Logi Uruchomień 08_14_09_2026"),
)


def test_watek_ktory_zostaje_po_zamknieciu_dostaje_czesci_jako_komentarze_w_zamknietym_issue(tmp_path: Path) -> None:
    closed = BoxIssue(7, LOGS.label, LOGS.title, f"{LOGS.line}\n\nLogi Uruchomień tego okresu.\n")
    box = FakeReportBox(issues=[closed])
    box.close(7)
    queue = Queue(tmp_path, box)

    queue.outbox.post(
        Post.of(LOGS, period="08_14_09_2026", run_id=RUN_ID, blocks=[tool("logi\n")], frame=numbered, header=tool("Nagłówek"))
    )

    assert queue.box.wait_until(lambda box: bool(closed.comments))
    assert queue.box.issues == [closed]
    assert closed.comments == ["Część 1/1\n\nlogi\n"]
    assert wait_for(lambda: queue.files() == [])


def test_bez_klucza_wysylka_czeka_w_pliku_bez_pytania_skrzynki(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(), key=None)

    queue.outbox.post(post(["treść\n"]))

    waiting = "skrzynka-czeka etykieta=kontrola-ilosci okres=08_14_09_2026 przyczyna=brak-klucza"
    assert wait_for(lambda: waiting in queue.log())
    assert len(queue.files()) == 1
    assert queue.box.keys == []


@pytest.mark.parametrize(
    ("failure", "key", "cause"),
    [(None, None, "brak-klucza"), (Unreachable(), KEY, "brak-sieci"), (Refused(), KEY, "odmowa")],
    ids=["brak-klucza", "brak-sieci", "odmowa"],
)
def test_porazka_dla_calej_kolejki_zatrzymuje_przejscie_i_ponawia_je_po_minucie_z_jedna_linia_dziennika(
    tmp_path: Path, failure: Refused | Unreachable | None, key: str | None, cause: str
) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=failure), key=key)
    queue.queued("pierwsza\n", "druga\n", "trzecia\n")

    queue.outbox.resume()
    queue.passed()
    queue.outbox.send_in_background()
    queue.passed()
    queue.clock.advance(RETRY_S)
    queue.passed()

    assert queue.log().count("skrzynka-czeka") == 1
    assert f"skrzynka-czeka etykieta=kontrola-ilosci okres=08_14_09_2026 przyczyna={cause}\n" in queue.log()
    assert len(queue.files()) == 3
    assert (queue.box.issues, queue.clock.wakes) == ([], 1)


def test_po_braku_sieci_kolejka_ponawia_po_minucie_bez_kolejnej_wysylki(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
    queue.outbox.post(post(["treść\n"]))
    queue.passed()
    queue.box.search_failure = None

    queue.clock.advance(RETRY_S - 1)
    queue.passed()
    assert queue.box.issues == []
    queue.clock.advance(1)

    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: queue.files() == [])
    queue.passed()
    assert queue.clock.wakes == 0


def test_stan_kolejki_ma_przyczyne_czekania_budzenie_i_plik_ktorego_nie_dalo_sie_usunac(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Outbox.state``: pamięć, od której zależą następne przejścia, i którą wyrocznia kolejki porównuje między
    harmonogramami zamiast prywatnych pól ``Outbox`` (docs/agents/skille.md, „Co wyrocznia bierze z src”)."""

    hold = threading.Event()
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable(), search_hold=hold))
    assert queue.outbox.state() == QueueState(frozenset(), None, False, False, False, False)
    queue.outbox.post(post(["treść\n"]))
    assert queue.box.searching.wait(30)
    queue.outbox.send_in_background()
    assert queue.outbox.state() == QueueState(frozenset(), None, False, False, True, True)
    hold.set()
    queue.passed()
    assert queue.outbox.state() == QueueState(frozenset(), "brak-sieci", False, True, False, False)

    queue.box.search_failure = None
    unlink = Path.unlink

    def locked(path: Path, missing_ok: bool = False) -> None:
        if path.parent == queue.directory and path.suffix == ".json":
            raise PermissionError("plik otwarty w innym programie")
        unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    queue.clock.advance(RETRY_S)
    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    queue.passed()
    assert queue.outbox.state() == QueueState(frozenset(queue.files()), None, False, False, False, False)
    assert len(queue.files()) == 1


def test_stan_skrzynki_z_kluczem_ma_issue_z_odpowiedzia_i_zakladanie_bez_odpowiedzi_do_uplywu_opoznienia_listy() -> None:
    """``KeyedBox.state``: zapisy, od których zależą następne odpowiedzi skrzynki z kluczem, które wyrocznia kolejki
    porównuje między harmonogramami zamiast prywatnych pól ``KeyedBox``."""

    clock = ManualClock()
    box = FakeReportBox()
    keyed = KeyedBox(box, lambda: KEY, clock=clock)
    assert keyed.state() == BoxState((), (), (), (), (), (), ())

    sent = keyed.open_issue(THREAD.label, "Okres", "treść")
    box.outcomes.append(Unreachable())
    lost = keyed.open_issue("zgloszenie", "Zgłoszenie", "treść")

    assert isinstance(sent, Sent)
    assert isinstance(lost, Unreachable)
    assert keyed.state() == BoxState((), (), (), (), (sent.number,), ("zgloszenie",), ())
    clock.pause(LIST_LAG_S)
    assert keyed.state() == BoxState((), (), (), (), (), (), ())


def test_stan_skrzynki_z_kluczem_ma_liste_przy_ktorej_pliku_zapisow_nie_dalo_sie_odczytac(tmp_path: Path) -> None:
    unreadable = tmp_path / OPENING_FILE
    unreadable.mkdir()  # odczyt folderu rzuca OSError jak plik, który trzyma antywirus
    keyed = KeyedBox(FakeReportBox(), lambda: KEY, clock=ManualClock(), opening=NotesFile(unreadable, replace_atomically))

    keyed.labelled_issues(THREAD.label, include_closed=False)

    assert keyed.state() == BoxState((), (), (), (), (), (), (THREAD.label,))


def test_dziennik_centrum_z_wlasnym_zapisem_daje_mu_kazda_linie_i_nie_pisze_pliku(tmp_path: Path) -> None:
    """``CentrumLog(append=…)``: wyrocznia kolejki dostaje linie dziennika bez pliku, zamiast nadpisywać jego zapis."""

    lines: list[str] = []
    log = CentrumLog(tmp_path / "logs" / "centrum-rozliczen.log", append=lines.append)

    log.unexpected_failure(PermissionError("plik zablokowany"), where=DRAIN)
    log.box_post_queued(label=THREAD.label, period=None)

    assert [line.split(" ", 1)[1] for line in lines] == [
        'nieoczekiwany-wyjatek typ=PermissionError miejsce="wysyłka do Skrzynki Zgłoszeń"',
        f"skrzynka-w-kolejce etykieta={THREAD.label} okres=bez-okresu",
    ]
    assert not (tmp_path / "logs").exists()


def test_kolejne_przejscia_przed_budzeniem_nie_nastawiaja_drugiego_budzenia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
    queue.outbox.post(post(["treść\n"]))
    queue.passed()

    queue.outbox.send_in_background()
    queue.passed()

    assert queue.clock.wakes == 1


def test_kolejka_bez_porazki_nie_nastawia_ponowienia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())

    queue.outbox.post(post(["treść\n"]))

    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    queue.passed()
    assert queue.clock.wakes == 0


def test_odrzucona_tresc_nie_nastawia_ponowienia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Rejected()]))

    queue.outbox.post(post(["treść\n"]))

    assert wait_for(lambda: "przyczyna=odmowa-tresci" in queue.log())
    queue.passed()
    assert queue.clock.wakes == 0


def waiting_causes(queue: Queue) -> list[str]:
    return [line.rsplit("przyczyna=", 1)[1] for line in queue.log().splitlines() if "skrzynka-czeka" in line]


def test_czekanie_trafia_do_dziennika_przy_zmianie_przyczyny(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
    queue.outbox.post(post(["treść\n"]))
    queue.passed()
    queue.clock.advance(RETRY_S)
    queue.passed()
    queue.box.search_failure = Refused()

    queue.clock.advance(RETRY_S)
    queue.passed()

    assert waiting_causes(queue) == ["brak-sieci", "odmowa"]


def test_po_dostarczeniu_ta_sama_przyczyna_czekania_znowu_trafia_do_dziennika(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
    queue.outbox.post(post(["pierwsza\n"]))
    queue.passed()
    queue.box.search_failure = None
    queue.clock.advance(RETRY_S)
    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    queue.passed()
    queue.box.search_failure = Unreachable()

    queue.outbox.post(post(["druga\n"], run_id=NEXT_RUN_IDS[0]))
    queue.passed()

    assert waiting_causes(queue) == ["brak-sieci", "brak-sieci"]


def test_dostarczenie_w_przejsciu_zeruje_przyczyne_czekania_takze_przed_nastepnym_plikiem(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable(), comment_outcomes=[Unreachable()]))
    queue.queued("pierwsza\n", "druga\n")
    queue.outbox.resume()
    queue.passed()
    queue.box.search_failure = None

    queue.clock.advance(RETRY_S)
    queue.passed()

    assert len(queue.box.issues) == 1
    assert waiting_causes(queue) == ["brak-sieci", "brak-sieci"]


def test_przejscie_do_konca_po_braku_sieci_nie_nastawia_ponowienia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
    queue.outbox.post(post(["treść\n"]))
    queue.passed()
    queue.box.search_failure = None
    queue.box.outcomes = [Rejected()]

    queue.clock.advance(RETRY_S)
    queue.passed()

    assert "przyczyna=odmowa-tresci" in queue.log()
    assert queue.clock.wakes == 0


def test_tresc_ktorej_skrzynka_odmawia_zostaje_w_kolejce_a_nastepna_wychodzi_w_tym_samym_przejsciu(
    tmp_path: Path,
) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Rejected()]))
    refused, _sent = queue.queued("odrzucona\n", "przyjęta\n")

    queue.outbox.resume()

    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert queue.box.issues[0].body.splitlines()[-1] == "przyjęta"
    assert wait_for(lambda: queue.files() == [refused])
    assert (
        f"skrzynka-czeka etykieta=kontrola-ilosci okres=08_14_09_2026 przyczyna=odmowa-tresci plik={refused}" in queue.log()
    )
    assert "brak-sieci" not in queue.log()
    for _ in range(2):
        queue.outbox.send_in_background()
        queue.passed()
    assert queue.files() == [refused]
    assert queue.log().count("przyczyna=odmowa-tresci") == 1

    queue.restarted().resume()

    assert queue.box.wait_until(lambda box: len(box.issues[0].comments) == 1)
    assert queue.box.issues[0].comments == ["Część 1/1\n\nodrzucona\n"]
    assert wait_for(lambda: queue.files() == [])


def test_druga_kolejka_na_tym_folderze_nie_wysyla_pliku_w_trakcie_wysylki_pierwszej_ani_nie_nastawia_budzenia(
    tmp_path: Path,
) -> None:
    # Restart Centrum w tym samym procesie: kolejka poprzedniego startu dalej zakłada issue okresu.
    hold = threading.Event()
    queue = Queue(tmp_path, FakeReportBox(open_hold=hold))
    queue.queued("treść\n")
    queue.outbox.resume()
    assert queue.box.opening.wait(30)
    restarted = queue.restarted()

    restarted.resume()
    assert not restarted.wait_delivered("", THREAD.label, timeout_s=30)
    searched = len(queue.box.listed)
    hold.set()
    queue.passed()

    assert (searched, len(queue.box.issues)) == (1, 1)
    assert queue.files() == []
    assert queue.clock.wakes == 0  # nowa kolejka nie przeszła folderu, więc nie ma czego ponawiać


def test_przejscie_pominiete_przez_druga_kolejke_robi_pierwsza_po_swoim(tmp_path: Path) -> None:
    hold = threading.Event()
    queue = Queue(tmp_path, FakeReportBox(search_hold=hold, search_failure=Unreachable()))
    queue.queued("treść\n")
    queue.outbox.resume()
    assert queue.box.searching.wait(30)
    restarted = queue.restarted()
    restarted.resume()
    assert not restarted.wait_delivered("", THREAD.label, timeout_s=30)

    queue.box.search_failure = None  # tylko pytanie, które już trwa, zostaje bez odpowiedzi
    hold.set()

    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: queue.files() == [])


def test_kolejki_starego_i_nowego_centrum_na_jednym_folderze_zakladaja_jedno_issue_okresu_bez_dalszych_budzen(
    tmp_path: Path,
) -> None:
    # Stare Centrum po zwolnieniu portu jeszcze wysyła Kontrolę ilości i kończy się w trakcie, a nowe już startuje na tym
    # samym folderze.
    queue = Queue(tmp_path, FakeReportBox())
    queue.queued("różnice\n")
    box = SharedBox(tmp_path / "skrzynka")
    old = old_centrum(queue.directory, tmp_path / "skrzynka", tmp_path / "logs" / "stare-centrum.log")
    new = queue_on(queue.directory, box, queue.log_path, queue.clock)

    try:
        new.resume()
        assert not new.wait_delivered("", THREAD.label, timeout_s=30)
    finally:
        old.finish()
    queue.clock.advance(seconds=RETRY_S)
    assert not new.wait_delivered("", THREAD.label, timeout_s=30)

    assert [issue["label"] for issue in box.issues()] == ["kontrola-ilosci"]
    assert queue.files() == []
    assert queue.clock.wakes == 0  # przejście z blokadą kończy budzenie po cudzej blokadzie


def test_centrum_zabite_miedzy_przyjeciem_czesci_przez_skrzynke_a_znacznikiem_nie_wysyla_jej_po_starcie_drugi_raz(
    tmp_path: Path,
) -> None:
    # Proces Centrum kończy się, gdy Skrzynka przyjęła część 2 Kontroli ilości, a znacznika dostarczenia jeszcze nie ma.
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    control = post(["x" * 40_000, "y" * 40_000])
    (queue.directory / "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json").write_text(
        control.to_json(), encoding="utf-8"
    )
    killed_after_comment(queue.directory, tmp_path / "skrzynka", tmp_path / "logs" / "stare-centrum.log")
    box = SharedBox(tmp_path / "skrzynka")
    first, second = control.parts
    accepted = [f"{THREAD.line}\n\n{first}", second]
    assert [seen(issue) for issue in box.issues()] == [accepted]
    assert len(queue.files()) == 1, "plik kolejki bez znacznika dostarczenia zostaje po zgaśnięciu"

    restarted = queue_on(queue.directory, box, queue.log_path, queue.clock)
    restarted.resume()

    assert restarted.wait_delivered(RUN_ID, THREAD.label, timeout_s=30)
    assert wait_for(lambda: queue.files() == [])
    assert [seen(issue) for issue in box.issues()] == [accepted]


def seen(issue: dict[str, object]) -> list[str]:
    """Treść i komentarze issue skrzynki w plikach tak, jak widzi je Maks."""

    comments = issue["comments"]
    assert isinstance(comments, list)
    return [shown(str(text)) for text in (issue["body"], *comments)]


def test_start_centrum_bez_folderu_kolejki_go_nie_zaklada_i_nie_nastawia_budzenia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())

    queue.outbox.resume()
    queue.passed()

    assert not queue.directory.exists()
    assert queue.clock.wakes == 0
    assert "nieoczekiwany-wyjatek" not in queue.log()


def test_wysylka_dodana_w_trakcie_przejscia_wychodzi_bez_kolejnego_budzenia(tmp_path: Path) -> None:
    hold = threading.Event()
    queue = Queue(tmp_path, FakeReportBox(search_hold=hold))

    queue.outbox.post(post(["pierwsza\n"]))
    assert queue.box.searching.wait(30), "przejście kolejki nie zaczęło pytać skrzynki"
    queue.outbox.post(post(["druga\n"], run_id=NEXT_RUN_IDS[0]))
    hold.set()

    assert queue.box.wait_until(lambda box: bool(box.issues) and len(box.issues[0].comments) == 1)
    assert queue.box.issues[0].comments == ["Część 1/1\n\ndruga\n"]
    assert wait_for(lambda: queue.files() == [])


def test_gdy_skrzynka_odmawia_szukania_issue_okresu_wysylka_czeka_w_pliku_bez_nowego_issue(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(search_failure=Refused()))

    queue.outbox.post(post(["treść\n"]))

    assert wait_for(lambda: "przyczyna=odmowa\n" in queue.log())
    assert len(queue.files()) == 1
    assert (queue.box.issues, queue.box.keys) == ([], [])


def test_nieudany_komentarz_zostawia_wysylke_w_pliku(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(comment_outcomes=[Unreachable()]))

    queue.outbox.post(post(["x" * 40_000, "y" * 40_000]))

    assert wait_for(lambda: "przyczyna=brak-sieci" in queue.log())
    assert len(queue.files()) == 1


def test_uwaga_ktorej_komentarz_skrzynka_odrzucila_dostaje_reszte_czesci_w_swoim_issue_po_starcie(
    tmp_path: Path,
) -> None:
    queue = Queue(tmp_path, FakeReportBox(comment_outcomes=[Rejected()]))
    note = Post(NewIssue("uwaga-taty", tool("Uwaga taty")), None, RUN_ID, None, (tool("Część 1/2\n\na"), tool("Część 2/2\n\nb")))

    queue.outbox.post(note)
    queue.passed()
    rejected = queue.outbox.rejected(RUN_ID, "uwaga-taty")
    queue.restarted().resume()

    assert wait_for(lambda: queue.files() == [])
    [issue] = queue.box.issues_with("uwaga-taty")
    assert (issue.body, issue.comments) == ("Część 1/2\n\na", ["Część 2/2\n\nb"])
    assert queue.delivered == [(RUN_ID, issue.number)]
    assert (rejected, "przyczyna=odmowa-tresci" in queue.log(), "nieoczekiwany-wyjatek" in queue.log()) == (True, True, False)


def test_wysylka_ktorej_nie_da_sie_zapisac_przepada_bez_wyjatku(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.parent.mkdir(parents=True)
    queue.directory.write_text("plik zamiast folderu", encoding="utf-8")

    queue.outbox.post(post(["treść\n"]))

    assert "nieoczekiwany-wyjatek typ=" in queue.log()
    assert "zapis wysyłki do Skrzynki Zgłoszeń" in queue.log()
    assert queue.box.issues == []


def test_wysylka_zapisana_przez_wersje_z_273_wychodzi_po_starcie(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    shutil.copy(
        ROOT / "tests" / "fixtures" / "kolejka-v1-kontrola-ilosci.json",
        queue.directory / "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json",
    )

    queue.outbox.resume()

    assert queue.box.wait_until(lambda box: bool(box.issues))
    [issue] = queue.box.issues_with("kontrola-ilosci")
    assert issue.title == "Kontrola ilości 08_14_09_2026: 1 różnica"
    assert issue.body == (
        "- Kontrola ilości okresu: 08_14_09_2026\n\n"
        "Kontrola ilości z Centrum rozliczeń (plik kolejki w wersji 1 z #273).\n\n"
        "## Różnice\n\n| Kolumna | Reguła | Tata |\n| --- | --- | --- |\n| Q | 2 | 1 |\n"
    )
    assert wait_for(lambda: queue.files() == [])


def test_uwaga_zapisana_przez_wersje_z_318_wychodzi_po_starcie(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    shutil.copy(
        ROOT / "tests" / "fixtures" / "kolejka-v2-uwaga-taty.json",
        queue.directory / "20261024T001500000000Z-0001-uwaga-taty-7c1e2d3f.json",
    )

    queue.outbox.resume()

    assert queue.box.wait_until(lambda box: bool(box.issues))
    [issue] = queue.box.issues_with("uwaga-taty")
    assert issue.title == "Brakuje ilości przy montażu"
    assert issue.body == "Plik kolejki w wersji 2 z #318.\n\nUwaga ogólna · wersja narzędzia 4900cb9\n"
    assert wait_for(lambda: queue.files() == [])

def test_zapis_urwany_przez_utrate_zasilania_znika_przy_starcie_i_nie_jest_wysylany(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    (queue.directory / "20261023T101500000000Z-0001-kontrola-ilosci-3f2a9c1b.json.tmp").write_text(
        '{"schema_version": 1, "thr', encoding="utf-8"
    )

    queue.outbox.resume()

    assert queue.files() == []
    assert queue.box.keys == []


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"schema_version": 2}',
        post(["x"]).to_json().replace('"schema_version": 3', '"schema_version": 4'),
        post(["x"]).to_json().replace('"kontrola-ilosci"', '"inna-etykieta"'),
        post(["x"]).to_json().replace('"archived": false', '"archived": 0'),
    ],
    ids=["urwany", "nie-obiekt", "bez-celu", "nowszy-schemat", "nieznana-etykieta", "archiwum-nie-tak-ani-nie"],
)
def test_plik_kolejki_ktorego_nie_da_sie_odczytac_zostaje_z_jednym_wpisem_i_nie_wstrzymuje_innych(
    tmp_path: Path, text: str
) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    broken = "00000000T000000000000Z-0001-kontrola-ilosci-3f2a9c1b.json"
    (queue.directory / broken).write_text(text, encoding="utf-8")

    queue.outbox.post(post(["treść\n"]))
    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: queue.files() == [broken])
    queue.outbox.post(post(["druga\n"], run_id=NEXT_RUN_IDS[0]))
    assert queue.box.wait_until(lambda box: len(box.issues[0].comments) == 1)
    assert wait_for(lambda: queue.files() == [broken])

    assert queue.log().count(f"skrzynka-nieczytelny plik={broken}") == 1
    assert "nieoczekiwany-wyjatek" not in queue.log()
    queue.passed()
    assert queue.clock.wakes == 0  # treść nie zmieni się sama, więc ponowienie jej nie pomoże


def locked_reads(monkeypatch: pytest.MonkeyPatch, queue: Queue, times: int | None) -> None:
    """``read_text`` pliku kolejki rzuca ``PermissionError`` ``times`` razy (``None``: zawsze), jak plik, który trzyma
    OneDrive albo antywirus."""

    read_text = Path.read_text
    failures = itertools.count(1)

    def locked(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path.parent == queue.directory and (times is None or next(failures) <= times):
            raise PermissionError("plik otwarty w innym programie")
        return read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", locked)


def test_plik_kolejki_ktorego_raz_nie_da_sie_odczytac_wychodzi_po_minucie_bez_kolejnej_wysylki(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    [name] = queue.queued("treść\n")
    locked_reads(monkeypatch, queue, times=1)

    queue.outbox.resume()
    queue.passed()
    assert (queue.box.issues, queue.files()) == ([], [name])
    queue.clock.advance(RETRY_S)

    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: queue.files() == [])
    queue.passed()
    assert queue.clock.wakes == 0
    assert queue.log().count(f"skrzynka-nieczytelny plik={name}") == 1


def test_plik_kolejki_ktorego_nigdy_nie_da_sie_odczytac_ponawia_co_minute_z_jedna_linia_dziennika(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    [name] = queue.queued("treść\n")
    locked_reads(monkeypatch, queue, times=None)
    queue.outbox.resume()
    queue.passed()

    for _ in range(3):
        assert queue.clock.wakes == 1
        queue.clock.advance(RETRY_S)
        queue.passed()

    assert (queue.box.issues, queue.box.keys, queue.files()) == ([], [], [name])
    [line] = queue.log().splitlines()
    assert f"skrzynka-nieczytelny plik={name}" in line


def run_logs(
    version: str, count: int, *, header: str | None = "Logi Uruchomień okresu.", run_id: str = RUN_ID
) -> Post:
    """Logi Uruchomienia ``run_id`` w ``count`` częściach; ``version`` mówi, po której Diagnozie, a każda Diagnoza
    kolejkuje nowszą wersję tej samej wysyłki (``RunComments.diagnosed``)."""

    parts = tuple(tool(f"Logi {version}, część {number}/{count}\n") for number in range(1, count + 1))
    return Post(LOGS, "08_14_09_2026", run_id, None if header is None else tool(header), parts)


@pytest.mark.parametrize(
    ("header", "older", "newer"),
    [("Logi Uruchomień okresu.", 3, 2), (None, 2, 1)],
    ids=["z-naglowkiem", "nowsza-cala-w-tresci-issue"],
)
def test_logi_sprzed_diagnozy_ktore_dojda_po_logach_z_diagnoza_nie_zostawiaja_w_issue_okresu_zadnej_swojej_czesci(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, header: str | None, older: int, newer: int
) -> None:
    # Bez sieci czekają dwie wersje Logów jednego Uruchomienia, po drugiej Diagnozie o część krótsze niż po pierwszej.
    # Po powrocie sieci plik starszej raz nie daje się odczytać (trzyma go OneDrive), więc nowsza idzie pierwsza. Bez
    # nagłówka nowsza wersja w jednej części jest cała w treści issue, które sama zakłada.
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
    queue.outbox.post(run_logs("po pierwszej Diagnozie", older, header=header))
    queue.passed()
    queue.outbox.post(run_logs("po drugiej Diagnozie", newer, header=header))
    queue.passed()
    queue.box.search_failure = None
    locked_reads(monkeypatch, queue, times=1)

    queue.clock.advance(RETRY_S)
    queue.passed()
    assert len(queue.files()) == 1, "plik starszej wersji czeka na następne przejście"
    queue.clock.advance(RETRY_S)
    queue.passed()

    assert queue.files() == []
    [issue] = queue.box.issues_with(LOGS.label)
    texts = [issue.body, *issue.comments]
    assert [text for text in texts if "po pierwszej Diagnozie" in text] == []
    assert sum(part in text for part in run_logs("po drugiej Diagnozie", newer).parts for text in texts) == newer


def test_logi_sprzed_diagnozy_ktore_dojda_po_logach_z_diagnoza_do_issue_okresu_innego_uruchomienia_go_nie_zmieniaja(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Zwykły przypadek u taty: issue okresu założyło wcześniejsze Uruchomienie, więc znacznik nowszej wersji Logów tego
    # Uruchomienia stoi tylko w jego komentarzach. Starsza wersja dochodzi po nowszej (plik raz trzyma OneDrive) i nie
    # zmienia ani komentarzy, ani adresu Logów Uruchomienia, który pokazuje podgląd Zgłoszenia (``RunComments.link``).
    queue = Queue(tmp_path, FakeReportBox())
    queue.outbox.post(run_logs("wcześniejszego Uruchomienia", 1, run_id=NEXT_RUN_IDS[0]))
    queue.passed()
    queue.box.search_failure = Unreachable()
    queue.outbox.post(run_logs("po pierwszej Diagnozie", 3))
    queue.passed()
    queue.outbox.post(run_logs("po drugiej Diagnozie", 2))
    queue.passed()
    queue.box.search_failure = None
    locked_reads(monkeypatch, queue, times=1)

    queue.clock.advance(RETRY_S)
    queue.passed()
    assert len(queue.files()) == 1, "plik starszej wersji czeka na następne przejście"
    queue.clock.advance(RETRY_S)
    queue.passed()

    assert queue.files() == []
    [issue] = queue.box.issues_with(LOGS.label)
    earlier, *newer = issue.comments
    assert "Logi wcześniejszego Uruchomienia" in earlier
    assert newer == list(run_logs("po drugiej Diagnozie", 2).parts)
    assert queue.outbox.delivered(RUN_ID, LOGS.label) == (
        f"https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/{issue.number}"
        f"#issuecomment-{issue.comment_ids[1]}"
    )


def test_logi_z_diagnoza_ponowione_po_urwanej_odpowiedzi_nie_zmieniaja_komentarzy_uruchomienia_drugi_raz(
    tmp_path: Path,
) -> None:
    # Diagnoza skraca Logi o część: kolejka zmienia komentarz części 1 i opróżnia komentarz części 2, a odpowiedź na
    # opróżnienie się urywa, więc ponowienie po RETRY_S zastaje oba komentarze już w nowszej wersji.
    queue = Queue(tmp_path, FakeReportBox(lost_edit_answers=frozenset({2})))
    queue.outbox.post(run_logs("bez Diagnozy", 2))
    queue.passed()
    queue.outbox.post(run_logs("z Diagnozą", 1))
    queue.passed()
    assert len(queue.files()) == 1, "po urwanej odpowiedzi plik Logów z Diagnozą czeka na ponowienie"

    queue.clock.advance(RETRY_S)
    queue.passed()

    assert queue.files() == []
    [issue] = queue.box.issues_with(LOGS.label)
    first, second = issue.comment_ids
    assert queue.box.edited == [first, second]
    assert issue.comments[0] == run_logs("z Diagnozą", 1).parts[0]
    assert "Logi bez Diagnozy" not in issue.comments[1]


def test_logi_z_diagnoza_po_cofnieciu_zegara_komputera_zmieniaja_komentarz_uruchomienia(tmp_path: Path) -> None:
    # Windows poprawia zegar między wysłaniem Logów a Diagnozą: Diagnoza przychodzi z chwilą sprzed wysłania Logów.
    moments = iter(
        (datetime(2026, 9, 14, 12, 0, 5, tzinfo=timezone.utc), datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc))
    )
    queue = Queue(tmp_path, FakeReportBox(), now=lambda: next(moments))

    queue.outbox.post(run_logs("bez Diagnozy", 2))
    queue.passed()
    queue.outbox.post(run_logs("z Diagnozą", 2))
    queue.passed()

    assert next(moments, None) is None, "kolejka wzięła obie chwile z podanego zegara"
    assert queue.files() == []
    [issue] = queue.box.issues_with(LOGS.label)
    assert issue.comments == list(run_logs("z Diagnozą", 2).parts)


def test_chwila_w_nazwie_pliku_kolejki_jest_w_utc_takze_na_komputerze_w_strefie_taty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nazwa pliku kolejki kończy chwilę literą „Z”, a kolejność wersji po nazwach przetrwa zmianę czasu letniego.
    if sys.platform == "win32":
        pytest.skip("time.tzset jest tylko w systemach POSIX")
    monkeypatch.setenv("TZ", "Europe/Warsaw")
    time.tzset()
    try:
        queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
        before = datetime.now(timezone.utc)
        queue.outbox.post(run_logs("bez sieci", 1))
        after = datetime.now(timezone.utc)
        queue.passed()
    finally:
        monkeypatch.undo()
        time.tzset()

    [name] = queue.files()
    moment = datetime.strptime(name.split("-", 1)[0], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
    assert before <= moment <= after


def test_wersja_zastepcza_z_nastepnego_startu_nie_zmienia_logow_z_wynikiem_ktore_skrzynka_juz_ma(tmp_path: Path) -> None:
    # Logi z wynikiem doszły do Skrzynki, Centrum zgasło, zanim ich dziennik zniknął, a następny start wysyła z dziennika
    # wersję zastępczą tego samego Uruchomienia: późniejszą chwilą, ale niższym stopniem (#871, #910).
    queue = Queue(tmp_path, FakeReportBox())
    queue.outbox.post(run_logs("z wynikiem", 1))
    queue.passed()
    queue.outbox = queue.restarted()

    queue.outbox.post(replace(run_logs("zastępcze", 1), rank=Rank.STAND_IN))
    queue.passed()

    assert queue.files() == []
    [issue] = queue.box.issues_with(LOGS.label)
    assert (issue.comments, queue.box.edited) == (list(run_logs("z wynikiem", 1).parts), [])


def test_bez_sieci_wersja_zastepcza_z_nastepnego_startu_znika_przy_logach_z_wynikiem_bez_wyslania(tmp_path: Path) -> None:
    # Bez sieci Logi z wynikiem czekają w kolejce, a następny start dokłada wersję zastępczą tego samego Uruchomienia z
    # dziennika: po powrocie sieci Skrzynka dostaje tylko Logi z wynikiem, bo mają wyższy stopień (#871, #910).
    queue = Queue(tmp_path, FakeReportBox(search_failure=Unreachable()))
    queue.outbox.post(run_logs("z wynikiem", 1))
    queue.passed()
    queue.outbox = queue.restarted()
    queue.outbox.post(replace(run_logs("zastępcze", 1), rank=Rank.STAND_IN))
    queue.passed()
    waiting = len(queue.files())
    queue.box.search_failure = None

    queue.clock.advance(RETRY_S)  # przejście poprzedniej pracy Centrum albo tej, które przejmie folder kolejki

    assert (waiting, wait_for(lambda: queue.files() == [])) == (2, True)
    [issue] = queue.box.issues_with(LOGS.label)
    assert issue.comments == list(run_logs("z wynikiem", 1).parts)


def test_wyslanej_wysylki_ktorej_nie_da_sie_usunac_skrzynka_nie_dostaje_drugi_raz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    unlink = Path.unlink

    def locked(path: Path, missing_ok: bool = False) -> None:
        if path.parent == queue.directory and path.suffix == ".json":
            raise PermissionError("plik otwarty w innym programie")
        unlink(path, missing_ok=missing_ok)

    def failed_removals() -> int:
        return queue.log().count("usunięcie wysłanej wysyłki")

    monkeypatch.setattr(Path, "unlink", locked)
    queue.outbox.post(post(["pierwsza\n"]))
    assert wait_for(lambda: failed_removals() == 1)
    queue.outbox.post(post(["druga\n"], run_id=NEXT_RUN_IDS[0]))
    assert wait_for(lambda: failed_removals() == 2)
    queue.passed()  # inaczej nowa kolejka zastaje przejście tej i oddaje mu swoje (outbox._claimed)
    queue.restarted().resume()
    assert wait_for(lambda: failed_removals() == 4)
    monkeypatch.setattr(Path, "unlink", unlink)
    queue.restarted().resume()

    assert wait_for(lambda: queue.files() == [])
    [issue] = queue.box.issues
    assert [issue.body.splitlines()[-1], *(comment.splitlines()[-1] for comment in issue.comments)] == [
        "pierwsza",
        "druga",
    ]
    assert queue.log().count("skrzynka-wyslano") == 2
    assert failed_removals() == 4


def test_po_wyslaniu_kolejka_zna_adres_pierwszego_komentarza_uruchomienia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(outcomes=[Unreachable()]))
    logs = PeriodThread(
        label="logi-uruchomienia", line=tool("- Logi Uruchomienia okresu: 08_14_09_2026"), closed="reuse", title=tool("Logi")
    )
    run_logs = Post.of(
        logs, period="08_14_09_2026", run_id=RUN_ID, blocks=[tool("podsumowanie\n")], frame=numbered, header=tool("Logi okresu")
    )

    queue.outbox.post(run_logs)
    assert wait_for(lambda: "przyczyna=brak-sieci" in queue.log())
    waiting = queue.outbox.delivered(RUN_ID, "logi-uruchomienia")
    queue.clock.pause(LIST_LAG_S)  # po zakładaniu bez odpowiedzi KeyedBox tyle nie zakłada issue (#879)
    queue.outbox.resume()
    assert queue.box.wait_until(lambda box: bool(box.issues) and bool(box.issues[0].comments))
    assert wait_for(lambda: queue.outbox.delivered(RUN_ID, "logi-uruchomienia") is not None)

    assert waiting is None
    assert queue.outbox.delivered(RUN_ID, "logi-uruchomienia") == (
        "https://github.com/MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia/issues/1#issuecomment-1"
    )
    assert queue.outbox.delivered(RUN_ID, "kontrola-ilosci") is None
    assert queue.outbox.delivered("inne-uruchomienie", "logi-uruchomienia") is None


FINGERPRINT_LINE = "- Odcisk problemu: 0123456789abcdef"
REPORT = report_target("0123456789abcdef", tool("BRAK_WZORCA: Nie znaleziono wzorca."))
REPORT_BODY = f"Zgłoszenie z Centrum rozliczeń.\n\n## Narzędzie\n\n{FINGERPRINT_LINE}\n"


def report(body: str = REPORT_BODY, *, run_id: str = RUN_ID) -> Post:
    return Post.of(REPORT, period="08_14_09_2026", run_id=run_id, blocks=[tool(body)], frame=unframed)


def test_zgloszenie_to_issue_z_trescia_podgladu_bez_dopisanego_wiersza(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())

    queue.outbox.post(report())

    assert queue.box.wait_until(lambda box: len(box.sent) == 1)
    [issue] = queue.box.sent
    assert (issue.title, issue.body, issue.comments) == (REPORT.title, REPORT_BODY, [])
    assert wait_for(lambda: queue.files() == [])


# Pierwsze Zgłoszenie tego odcisku, już w Skrzynce: inne Uruchomienie, inna Diagnoza.
FIRST_REPORT_BODY = f"Zgłoszenie z Centrum rozliczeń.\n\n- Logi: pierwsze Uruchomienie\n\n## Narzędzie\n\n{FINGERPRINT_LINE}\n"


def test_zgloszenie_z_odciskiem_otwartego_zgloszenia_jest_w_nim_komentarzem_z_cala_trescia(tmp_path: Path) -> None:
    other = BoxIssue(3, "zgloszenie", "inny problem", "- Odcisk problemu: fedcba9876543210\n")
    open_report = BoxIssue(7, "zgloszenie", REPORT.title, FIRST_REPORT_BODY)
    queue = Queue(tmp_path, FakeReportBox(issues=[other, open_report]))

    queue.outbox.post(report())

    assert wait_for(lambda: queue.files() == [])
    assert queue.delivered == [(RUN_ID, 7)]
    assert queue.box.issues == [other, open_report]
    assert (open_report.body, other.comments) == (FIRST_REPORT_BODY, [])
    assert open_report.comments == [f"## Zgłoszenie wróciło\n\n{REPORT_BODY}"]
    assert queue.outbox.delivered(RUN_ID, "zgloszenie") is not None


def test_zgloszenie_ktore_wrocilo_po_urwanej_odpowiedzi_na_komentarz_przychodzi_raz(tmp_path: Path) -> None:
    open_report = BoxIssue(7, "zgloszenie", REPORT.title, FIRST_REPORT_BODY)
    queue = Queue(tmp_path, FakeReportBox(issues=[open_report], lost_comment_answers=1))

    queue.outbox.post(report())
    queue.passed()
    assert len(queue.files()) == 1
    queue.clock.advance(RETRY_S)

    assert wait_for(lambda: queue.files() == [])
    assert queue.box.issues == [open_report]
    assert open_report.comments == [f"## Zgłoszenie wróciło\n\n{REPORT_BODY}"]


def test_zamkniete_zgloszenie_tego_odcisku_nie_jest_przejete(tmp_path: Path) -> None:
    closed = BoxIssue(7, "zgloszenie", REPORT.title, REPORT_BODY)
    box = FakeReportBox(issues=[closed])
    box.close(7)
    queue = Queue(tmp_path, box)

    queue.outbox.post(report())

    assert queue.box.wait_until(lambda box: len(box.sent) == 2)
    assert queue.box.sent[1].body == REPORT_BODY


def test_zerwane_polaczenie_po_zalozeniu_zgloszenia_nie_daje_drugiego_zgloszenia(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(lost_answers=1))

    queue.outbox.post(report())
    queue.passed()
    assert len(queue.files()) == 1
    queue.clock.advance(RETRY_S)

    assert wait_for(lambda: queue.files() == [])
    assert [(issue.body, issue.comments) for issue in queue.box.sent] == [(REPORT_BODY, [])]


def test_zgloszenie_w_wiecej_niz_jednej_czesci_to_blad_programu() -> None:
    longest = REPORT_BODY + "x" * (PART_LIMIT - len(REPORT_BODY))
    assert report(longest).parts == (longest,)

    # Ponowiona wysyłka przejmuje Zgłoszenie, które sama założyła, bez komentarzy, więc część 2 by przepadła (#724).
    with pytest.raises(ValueError, match="jednej części"):
        report(longest + "x")


def test_zgloszenie_bez_wiersza_odcisku_w_tresci_issue_to_blad_programu() -> None:
    with pytest.raises(ValueError, match="wiersz rozpoznawczy"):
        report("Zgłoszenie bez odcisku.\n")


def test_plik_zgloszenia_zapisany_w_kolejce_wychodzi_po_starcie(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(), key=None)
    queue.outbox.post(report())
    queue.passed()
    [waiting] = queue.files()
    assert f"-zgloszenie-{RUN_ID[:8]}.json" in waiting

    queue.key = KEY
    queue.restarted().resume()

    assert queue.box.wait_until(lambda box: len(box.sent) == 1)
    assert (queue.box.sent[0].title, queue.box.sent[0].body) == (REPORT.title, REPORT_BODY)


def report_file(line: str) -> str:
    """Plik kolejki Zgłoszenia, jak go zapisuje Centrum od #426: cel niesie wiersz odcisku problemu ``line``."""

    target = {"kind": "report_issue", "label": "zgloszenie", "line": line, "title": "BRAK_WZORCA: Nie znaleziono wzorca."}
    return json.dumps(
        {
            "schema_version": 2,
            "target": target,
            "period": "08_14_09_2026",
            "run_id": RUN_ID,
            "header": None,
            "parts": [REPORT_BODY],
            "delivered_parts": 0,
            "issue": None,
        }
    )


def test_plik_zgloszenia_z_wierszem_odcisku_trafia_do_otwartego_zgloszenia_tego_odcisku(tmp_path: Path) -> None:
    open_report = BoxIssue(7, "zgloszenie", REPORT.title, FIRST_REPORT_BODY)
    queue = Queue(tmp_path, FakeReportBox(issues=[open_report]))
    queue.directory.mkdir(parents=True)
    (queue.directory / "20261023T101500000000Z-0001-zgloszenie-3f2a9c1b.json").write_text(
        report_file(FINGERPRINT_LINE), encoding="utf-8"
    )

    queue.outbox.resume()

    assert wait_for(lambda: queue.files() == [])
    assert queue.delivered == [(RUN_ID, 7)]
    assert (queue.box.issues, open_report.comments) == ([open_report], [f"## Zgłoszenie wróciło\n\n{REPORT_BODY}"])


def test_plik_zgloszenia_z_samym_odciskiem_bez_jego_wiersza_zostaje_nieczytelny(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    name = "20261023T101500000000Z-0001-zgloszenie-3f2a9c1b.json"
    (queue.directory / name).write_text(report_file("0123456789abcdef"), encoding="utf-8")

    queue.outbox.resume()
    queue.passed()

    assert queue.files() == [name]
    assert queue.log().count(f"skrzynka-nieczytelny plik={name}") == 1
    assert queue.box.issues == []


class FollowingUp(QueueListener):
    """Słuchacz, który po każdej przyjętej Uwadze oddaje kolejce komentarz do jej issue."""

    def delivered(self, post: Post, number: int) -> Sequence[Post]:
        super().delivered(post, number)
        if not isinstance(post.target, NewIssue):
            return ()
        return (Post(KnownIssue("uwaga-taty", number), None, "komentarz", None, (tool("Komentarz po Uwadze"),)),)


def test_wysylka_nastepcza_sluchacza_idzie_w_tym_samym_przejsciu_kolejki(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox(), listener=FollowingUp())

    queue.outbox.post(Post(NewIssue("uwaga-taty", tool("Uwaga taty")), None, RUN_ID, None, (tool("Uwaga"),)))
    queue.passed()

    [issue] = queue.box.issues_with("uwaga-taty")
    assert issue.comments == ["Komentarz po Uwadze"]
    assert queue.delivered == [(RUN_ID, issue.number), ("komentarz", issue.number)]
    assert queue.files() == []


def _unreadable_at_comment_list(queue: Queue, monkeypatch: pytest.MonkeyPatch) -> None:
    """Antywirus trzyma plik zapisów Skrzynki przy liście komentarza: pierwszy odczyt, który ma już issue Uwagi."""

    read_text = Path.read_text
    refused: list[Path] = []

    def held(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        text = read_text(path, encoding=encoding, errors=errors)
        if path == queue.opening and not refused and json.loads(text)["issue"]:
            refused.append(path)
            raise PermissionError(13, "Odmowa dostępu", str(path))
        return text

    monkeypatch.setattr(Path, "read_text", held)


def _unwritable_after_opening(queue: Queue, monkeypatch: pytest.MonkeyPatch) -> None:
    """Antywirus trzyma plik zapisów Skrzynki przy zapisie odpowiedzi na założenie Uwagi: zapis bez odpowiedzi zostaje."""

    write_text = Path.write_text
    refused: list[Path] = []

    def held(path: Path, data: str, encoding: str | None = None, errors: str | None = None, newline: str | None = None) -> int:
        if path.name == f"{OPENING_FILE}.tmp" and not refused and json.loads(data)["issue"]:
            refused.append(path)
            raise PermissionError(13, "Odmowa dostępu", str(path))
        return write_text(path, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", held)


@pytest.mark.parametrize(
    "fault",
    [_unreadable_at_comment_list, _unwritable_after_opening],
    ids=["odczyt-przy-liscie", "zapis-odpowiedzi"],
)
def test_komentarz_do_swiezego_issue_ktorego_lista_nie_pokazuje_czeka_zamiast_porzucenia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: Callable[[Queue, pytest.MonkeyPatch], None]
) -> None:
    """Lista issue jeszcze nie pokazuje Uwagi, którą kolejka właśnie założyła, a plik zapisów Skrzynki nie mówi o niej
    (#915): nie da się go odczytać przy liście komentarza do niej albo nie przyjął odpowiedzi na jej założenie. Kolejka
    nie wie, że issue zniknęło, więc komentarz czeka na budzenie ``RETRY_S``, zamiast przepaść jak do usuniętego issue
    (#402), i trafia do Uwagi raz."""

    queue = Queue(tmp_path, FakeReportBox(list_lag=True), listener=FollowingUp())
    fault(queue, monkeypatch)

    queue.outbox.post(Post(NewIssue("uwaga-taty", tool("Uwaga taty")), None, RUN_ID, None, (tool("Uwaga"),)))
    queue.passed()

    [issue] = queue.box.issues_with("uwaga-taty")
    assert (issue.comments, len(queue.files()), queue.clock.wakes) == ([], 1, 1)
    assert "skrzynka-porzucono" not in queue.log()
    queue.box.list_caught_up()
    queue.clock.advance(RETRY_S)
    queue.passed()
    assert issue.comments == ["Komentarz po Uwadze"]
    assert queue.files() == []


def test_komentarz_do_issue_ktore_lista_juz_pokazuje_dochodzi_takze_bez_odczytu_pliku_zapisow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wstrzymanie (#915) dotyczy tylko numeru, którego lista nie pokazuje: gdy lista issue ma już Uwagę, komentarz do
    niej dochodzi w tym samym przejściu także przy liście, przy której pliku zapisów Skrzynki nie da się odczytać, bo o
    issue na liście nic nie trzeba rozstrzygać."""

    queue = Queue(tmp_path, FakeReportBox(), listener=FollowingUp())
    _unreadable_at_comment_list(queue, monkeypatch)

    queue.outbox.post(Post(NewIssue("uwaga-taty", tool("Uwaga taty")), None, RUN_ID, None, (tool("Uwaga"),)))
    queue.passed()

    [issue] = queue.box.issues_with("uwaga-taty")
    assert "skrzynka-zapisy-niedostepne" in queue.log()
    assert (issue.comments, queue.files(), queue.clock.wakes) == (["Komentarz po Uwadze"], [], 0)


def logs_with_file(run_id: str) -> Post:
    """Logi Uruchomienia ``run_id`` w jednym komentarzu z plikiem do Archiwum Logów okresu, jak ``comment_versions.post_of``."""

    archive = ArchiveFile("logi-08_14_09_2026", "Logi Uruchomień 08_14_09_2026", "Opis.", f"{run_id}.json", logs_text("{}\n"))
    return Post(LOGS, "08_14_09_2026", run_id, tool("Logi okresu"), (tool(f"podsumowanie {run_id}\n"),), archive)


def test_przejscie_w_ktorym_archiwum_odmowilo_nie_pyta_go_o_pliki_nastepnych_logow(tmp_path: Path) -> None:
    """Bez uprawnienia Tokenu do zapisu treści repozytorium każde Uruchomienie okresu czeka w kolejce ze swoim plikiem do
    Archiwum Logów okresu. Przejście, w którym Archiwum odmówiło, nie pyta go już o pliki następnych Logów, a komentarz
    każdych idzie z dopiskiem; następne przejście (budzik ``RETRY_S``) pyta Archiwum znowu raz (#844)."""

    queue = Queue(tmp_path, FakeReportBox(archive_failure=Refused()))
    queue.directory.mkdir(parents=True)
    run_ids = (RUN_ID, *NEXT_RUN_IDS)
    for second, run_id in enumerate(run_ids):
        name = f"20261023T1015{second:02d}000000Z-0001-logi-uruchomienia-{run_id[:8]}.json"
        (queue.directory / name).write_text(logs_with_file(run_id).to_json(), encoding="utf-8")

    queue.outbox.resume()
    queue.passed()

    assert queue.box.archive_requests == 1
    [issue] = queue.box.issues_with(LOGS.label)
    assert [comment.splitlines()[0] for comment in issue.comments] == [f"podsumowanie {run_id}" for run_id in run_ids]
    assert all(f"Plik `{run_id}.json.gz` czeka w Kolejce wysyłki" in comment for run_id, comment in zip(run_ids, issue.comments, strict=True))
    queued = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(queue.directory.glob("*.json"))]
    assert [(entry["delivered_parts"], entry["archived"]) for entry in queued] == [(1, False)] * 3
    asked = len(queue.box.listed)

    queue.clock.advance(RETRY_S)
    queue.passed()

    # Części są już w Skrzynce, więc budzenie pyta tylko Archiwum, a dziennik tej pracy Centrum mówi raz o każdym pliku.
    assert (queue.box.archive_requests, len(queue.box.listed)) == (2, asked)
    assert queue.log().count("przyczyna=odmowa-archiwum") == len(run_ids)


def test_najdluzszy_komentarz_logow_z_plikiem_zostawia_miejsce_na_dopisek_gdy_archiwum_odmowi(tmp_path: Path) -> None:
    """Komentarz Logów z plikiem do Archiwum Logów okresu dostaje dopisek „czeka w Kolejce wysyłki”, gdy Archiwum pliku
    nie przyjmie, więc wysyłka przyjmuje tylko część, która mieści się w komentarzu Skrzynki razem z dopiskiem: z
    najdłuższą przyjętą częścią i odmową Archiwum komentarz z dopiskiem nie przekracza limitu."""

    def logs(length: int) -> Post | None:
        try:
            return replace(logs_with_file(RUN_ID), parts=(tool("ą" * length),))
        except ValueError:
            return None

    accepted, refused = 1, TEXT_LIMIT + 1
    while refused - accepted > 1:
        middle = (accepted + refused) // 2
        accepted, refused = (middle, refused) if logs(middle) is not None else (accepted, middle)
    longest = logs(accepted)
    assert longest is not None
    queue = Queue(tmp_path, FakeReportBox(archive_failure=Refused()))

    queue.outbox.post(longest)
    queue.passed()

    [issue] = queue.box.issues_with(LOGS.label)
    [comment] = issue.comments
    assert "czeka w Kolejce wysyłki" in comment
    assert len(comment) <= TEXT_LIMIT


def test_plik_do_archiwum_z_wysylka_w_dwoch_czesciach_to_blad_programu() -> None:
    with pytest.raises(ValueError, match="Plik do Archiwum okresu idzie z jedną częścią do issue okresu"):
        replace(logs_with_file(RUN_ID), parts=(tool("pierwsza\n"), tool("druga\n")))


def test_logi_z_plikiem_bez_naglowka_maja_w_tresci_nowego_issue_dopisek_ze_plik_czeka(tmp_path: Path) -> None:
    """Bez nagłówka część Logów jest treścią nowego issue okresu, więc tam stoi dopisek o pliku, którego Archiwum
    okresu nie przyjęło."""

    queue = Queue(tmp_path, FakeReportBox(archive_failure=Refused()))

    queue.outbox.post(replace(logs_with_file(RUN_ID), header=None))
    queue.passed()

    [issue] = queue.box.issues_with(LOGS.label)
    assert f"Plik `{RUN_ID}.json.gz` czeka w Kolejce wysyłki" in issue.body
    assert issue.comments == []


# Wersja wysyłki pliku kolejki Logów z poprzedniej pracy Centrum (``queued_logs``): chwila i numer z jego nazwy.
LOGS_VERSION = "20261023T101500000000Z-0001"
LOGS_TAG = "logi-08_14_09_2026"


def queued_logs(queue: Queue) -> None:
    """Logi Uruchomienia ``RUN_ID`` z plikiem do Archiwum w pliku kolejki z poprzedniej pracy Centrum."""

    queue.directory.mkdir(parents=True, exist_ok=True)
    name = f"{LOGS_VERSION}-logi-uruchomienia-{RUN_ID[:8]}.json"
    (queue.directory / name).write_text(logs_with_file(RUN_ID).to_json(), encoding="utf-8")


def test_plik_logow_w_archiwum_ma_etykiete_z_nazwa_i_wersja_wysylki(tmp_path: Path) -> None:
    queue = Queue(tmp_path, FakeReportBox())
    queued_logs(queue)

    queue.outbox.resume()
    queue.passed()

    [archive] = queue.box.archives
    assert [(asset.name, asset.label) for asset in archive.assets] == [
        (f"{RUN_ID}.json.gz", f"{RUN_ID}.json.gz (wersja {LOGS_VERSION})")
    ]


def test_plik_archiwum_z_etykieta_w_innej_postaci_ustepuje_plikowi_wysylki(tmp_path: Path) -> None:
    """Etykieta, z której kolejka nie odczyta wersji (np. dopisana ręcznie), nie jest nowszą wersją wysyłki."""

    stale = ArchivedFile(1, f"{RUN_ID}.json.gz", f"{RUN_ID}.json.gz (wersja dodany ręcznie)", gzip.compress(b"stary\n"))
    archive = BoxArchive(1, LOGS_TAG, "Logi Uruchomień 08_14_09_2026", "Opis.", [stale])
    queue = Queue(tmp_path, FakeReportBox(archives=[archive]))
    queued_logs(queue)

    queue.outbox.resume()
    queue.passed()

    assert queue.box.archived(LOGS_TAG) == {f"{RUN_ID}.json.gz": b"{}\n"}
    assert queue.files() == []


def test_plik_czekajacy_na_archiwum_bez_sieci_zostaje_w_kolejce_i_dochodzi_po_powrocie_sieci(tmp_path: Path) -> None:
    """Plik Logów, którego części już są w Skrzynce, a Archiwum jest nieosiągalne, czeka jak bez sieci (linia dziennika i
    budzenie ``RETRY_S``), a nie znika; gdy sieć wraca, dochodzi do Archiwum z linią dziennika jego okresu."""

    queue = Queue(tmp_path, FakeReportBox(archive_failure=Refused()))
    queued_logs(queue)
    queue.outbox.resume()
    queue.passed()

    queue.box.archive_failure = Unreachable()
    queue.clock.advance(RETRY_S)
    queue.passed()

    assert (len(queue.files()), "przyczyna=brak-sieci" in queue.log()) == (1, True)
    queue.box.archive_failure = None
    queue.clock.advance(RETRY_S)
    queue.passed()
    assert queue.box.archived(LOGS_TAG) == {f"{RUN_ID}.json.gz": b"{}\n"}
    assert queue.files() == []
    assert "skrzynka-archiwum etykieta=logi-uruchomienia okres=08_14_09_2026" in queue.log()


def test_plik_starszego_centrum_ze_znacznikiem_dostarczenia_znika_po_starcie_bez_skrzynki_i_bez_linii_o_archiwum(
    tmp_path: Path,
) -> None:
    """Plik schematu 2 (bez pliku do Archiwum), który stare Centrum oznaczyło jako dostarczony, ale go nie usunęło."""

    queue = Queue(tmp_path, FakeReportBox())
    queue.directory.mkdir(parents=True)
    document = json.loads(post(["treść\n"]).to_json())
    for key in ("archive", "archived", "rank", "state"):
        del document[key]
    document.update(schema_version=2, delivered_parts=1)
    (queue.directory / f"{LOGS_VERSION}-kontrola-ilosci-{RUN_ID[:8]}.json").write_text(json.dumps(document), encoding="utf-8")

    queue.outbox.resume()
    queue.passed()

    assert (queue.files(), queue.box.keys, queue.box.listed) == ([], [], [])
    assert "skrzynka-archiwum" not in queue.log()


def test_kontrole_ilosci_okresu_w_jednym_przejsciu_ida_do_jednego_issue_zanim_lista_je_pokaze(tmp_path: Path) -> None:
    """Lista issue GitHuba pokazuje nowe issue po kilku sekundach (#879). Druga Kontrola ilości okresu, która w tym samym
    przejściu idzie zaraz po tym, jak pierwsza założyła issue okresu, trafia do niego komentarzem."""

    queue = Queue(tmp_path, FakeReportBox(list_lag=True))
    queue.queued("pierwsza\n", "druga\n")

    queue.outbox.resume()
    queue.passed()

    [issue] = queue.box.issues_with(THREAD.label)
    assert issue.body == f"{THREAD.line}\n\nCzęść 1/1\n\npierwsza\n"
    assert issue.comments == ["Część 1/1\n\ndruga\n"]
    assert queue.files() == []


def test_kontrola_ilosci_przy_liscie_bez_odczytu_pliku_zapisow_czeka_na_budzenie_zamiast_drugiego_issue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Antywirus trzyma plik zapisów Skrzynki akurat przy liście drugiej Kontroli ilości okresu, a lista issue jeszcze nie
    pokazuje issue, które założyła pierwsza (#909). Druga czeka na budzenie ``RETRY_S`` i trafia do tego issue."""

    queue = Queue(tmp_path, FakeReportBox(list_lag=True))
    queue.queued("pierwsza\n", "druga\n")
    read_text = Path.read_text
    refused: list[Path] = []

    def held_after_first_issue(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        text = read_text(path, encoding=encoding, errors=errors)
        if path == queue.opening and not refused and json.loads(text)["issue"]:
            refused.append(path)
            raise PermissionError(13, "Odmowa dostępu", str(path))
        return text

    monkeypatch.setattr(Path, "read_text", held_after_first_issue)
    queue.outbox.resume()
    queue.passed()

    assert (len(queue.box.issues), len(queue.files()), queue.clock.wakes) == (1, 1, 1)
    queue.box.list_caught_up()
    queue.clock.advance(RETRY_S)
    queue.passed()
    [issue] = queue.box.issues_with(THREAD.label)
    assert issue.comments == ["Część 1/1\n\ndruga\n"]
    assert queue.files() == []
    assert queue.log().count("skrzynka-zapisy-niedostepne typ=PermissionError") == 1


def test_plik_zapisow_ktorego_nigdy_nie_da_sie_odczytac_wstrzymuje_wysylke_z_jedna_linia_dziennika_do_naprawy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plik zapisów Skrzynki nieczytelny na stałe (#909): kolejka nie zakłada issue, którego zapisu nie może wykluczyć,
    czeka jak bez sieci i ponawia co budzenie, a dziennik mówi raz typ błędu (plik wynika z nazwy zdarzenia); po
    naprawie pliku wysyłka wychodzi."""

    queue = Queue(tmp_path, FakeReportBox())
    queue.queued("treść\n")
    read_text = Path.read_text
    broken = [True]

    def locked(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path == queue.opening and broken[0]:
            raise PermissionError(13, "Odmowa dostępu", str(path))
        return read_text(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", locked)
    queue.outbox.resume()
    queue.passed()
    for _ in range(3):
        assert queue.clock.wakes == 1
        queue.clock.advance(RETRY_S)
        queue.passed()

    assert (queue.box.issues, len(queue.files())) == ([], 1)
    events = [line.split(" ")[1:3] for line in queue.log().splitlines()]
    assert events == [["skrzynka-zapisy-niedostepne", "typ=PermissionError"], ["skrzynka-czeka", f"etykieta={THREAD.label}"]]
    assert "przyczyna=brak-sieci" in queue.log().splitlines()[1]

    broken[0] = False
    queue.clock.advance(RETRY_S)
    assert queue.box.wait_until(lambda box: len(box.issues) == 1)
    assert wait_for(lambda: queue.files() == [])


def test_zgubiona_odpowiedz_na_zalozenie_uwagi_i_nowa_wysylka_zanim_lista_ja_pokaze_nie_daja_drugiego_issue(
    tmp_path: Path,
) -> None:
    """GitHub założył issue Uwagi taty, a odpowiedź zginęła (#879). Nowa wysyłka budzi przejście od razu, zanim lista
    issue pokaże to issue; Uwaga czeka wtedy na budzenie ``RETRY_S`` zamiast założyć drugie issue."""

    queue = Queue(tmp_path, FakeReportBox(lost_answers=1, list_lag=True))
    queue.outbox.post(Post(NewIssue("uwaga-taty", tool("Uwaga taty")), None, RUN_ID, None, (tool("Uwaga"),)))
    queue.passed()

    queue.outbox.post(report())
    queue.passed()

    assert len(queue.box.issues_with("uwaga-taty")) == 1
    queue.box.list_caught_up()
    queue.clock.advance(RETRY_S)
    queue.passed()
    [note] = queue.box.issues_with("uwaga-taty")
    assert (note.body, note.comments) == ("Uwaga", [])
    assert [issue.body for issue in queue.box.sent] == [REPORT_BODY]
    assert queue.files() == []


def test_zgubiona_odpowiedz_na_zalozenie_uwagi_i_start_centrum_zanim_lista_ja_pokaze_nie_daja_drugiego_issue(
    tmp_path: Path,
) -> None:
    """Centrum gaśnie po zgubionej odpowiedzi na założenie issue Uwagi taty i startuje znów, zanim lista issue je pokaże
    (#879): nowe Centrum zna chwilę tamtego zakładania z pliku obok klucza i czeka na budzenie ``RETRY_S``."""

    queue = Queue(tmp_path, FakeReportBox(lost_answers=1, list_lag=True))
    queue.outbox.post(Post(NewIssue("uwaga-taty", tool("Uwaga taty")), None, RUN_ID, None, (tool("Uwaga"),)))
    queue.passed()

    queue.outbox = queue.restarted()
    queue.outbox.resume()
    queue.passed()

    assert len(queue.box.issues_with("uwaga-taty")) == 1
    queue.box.list_caught_up()
    queue.clock.advance(RETRY_S)  # budzi też kolejkę poprzedniego Centrum, która w teście jeszcze żyje
    assert wait_for(lambda: queue.files() == [])
    [note] = queue.box.issues_with("uwaga-taty")
    assert (note.body, note.comments) == ("Uwaga", [])


def test_dwie_uwagi_taty_jedna_po_drugiej_zakladaja_dwa_issue_bez_czekania_na_liste(tmp_path: Path) -> None:
    """Zakładanie, na które przyszła odpowiedź, nie wstrzymuje następnego zakładania z tą etykietą w tym Centrum (#879)."""

    queue = Queue(tmp_path, FakeReportBox(list_lag=True))

    queue.outbox.post(Post(NewIssue("uwaga-taty", tool("Pierwsza")), None, RUN_ID, None, (tool("Pierwsza"),)))
    queue.passed()
    queue.outbox.post(Post(NewIssue("uwaga-taty", tool("Druga")), None, NEXT_RUN_IDS[0], None, (tool("Druga"),)))
    queue.passed()

    assert [note.body for note in queue.box.issues_with("uwaga-taty")] == ["Pierwsza", "Druga"]
    assert queue.files() == []


def test_logi_dwoch_uruchomien_nowego_okresu_w_jednym_przejsciu_ida_do_archiwum_zanim_lista_je_pokaze(
    tmp_path: Path,
) -> None:
    """Lista Archiwów (GitHub Releases) pokazuje nowe Archiwum po kilku sekundach (#887, #879). Drugie Logi nowego okresu
    w tym samym przejściu dokładają plik do Archiwum, które założyły pierwsze, zamiast dostać odmowę drugiego Archiwum
    tego tagu i komentarz z dopiskiem, że plik czeka."""

    queue = Queue(tmp_path, FakeReportBox(list_lag=True))
    queue.directory.mkdir(parents=True)
    run_ids = (RUN_ID, NEXT_RUN_IDS[0])
    for second, run_id in enumerate(run_ids):
        name = f"20261023T1015{second:02d}000000Z-0001-logi-uruchomienia-{run_id[:8]}.json"
        (queue.directory / name).write_text(logs_with_file(run_id).to_json(), encoding="utf-8")

    queue.outbox.resume()
    queue.passed()

    [issue] = queue.box.issues_with(LOGS.label)
    assert not any("czeka w Kolejce wysyłki" in comment for comment in issue.comments)
    assert sorted(queue.box.archived("logi-08_14_09_2026")) == sorted(f"{run_id}.json.gz" for run_id in run_ids)
    assert len(queue.box.archives) == 1
    assert queue.files() == []


_GOTOWA: Final = "from rozliczenia.centrum.outbox import Outbox, Post\n\n"

# Drogi do pliku kolejki obok wysyłki zbudowanej przez konstruktor ``Post`` (przegląd #1660, W1) → zgłoszenie mypy albo
# ruff, które każdą odrzuca w nowym module ``src/rozliczenia/centrum``.
DROGI_OBOK_POST: Final = {
    "własna klasa z to_json": (
        """from rozliczenia.centrum.outbox import Outbox


class Wysylka:
    def to_json(self) -> str:
        return "{}"


def wyslij(kolejka: Outbox, wysylka: Wysylka) -> bool:
    return kolejka.post(wysylka)
""",
        'expected "Post | LogsPost"',
    ),
    "podklasa Post z to_json": (
        """from rozliczenia.centrum.outbox import Post


class Inna(Post):
    def to_json(self) -> str:
        return "{}"
""",
        'Cannot inherit from final class "Post"',
    ),
    "copy.replace": (
        _GOTOWA
        + """import copy


def wyslij(kolejka: Outbox, post: Post) -> bool:
    return kolejka.post(copy.replace(post, run_id=1))
""",
        "`copy.replace` is banned",
    ),
    "replace z modułu copy": (
        _GOTOWA
        + """from copy import replace


def wyslij(kolejka: Outbox, post: Post) -> bool:
    return kolejka.post(replace(post, run_id=1))
""",
        "`copy.replace` is banned",
    ),
    "__replace__ z polem złego typu": (
        _GOTOWA
        + """def wyslij(kolejka: Outbox, post: Post) -> bool:
    return kolejka.post(post.__replace__(run_id=1))
""",
        '"__replace__" of "Post" has incompatible type',
    ),
}

# Znane luki kolejki (tests/fixtures/znane_luki.py): postaci, które zmieniają pole gotowej wysyłki albo dają kolejce
# inny obiekt, a mypy, ruff i plik kolejki (tests/fixtures/plik_kolejki.py) ich nie łapią.
ZNANE_LUKI: Final = {
    # Pole wysyłki z typem str (run_id, period, state) nie jest typem-dowodem, więc plik kolejki bierze każdy napis.
    "object.__setattr__ na gotowej wysyłce: pole str bez typu-dowodu (run_id)": _GOTOWA
    + """def wyslij(kolejka: Outbox, post: Post, komorka: str) -> bool:
    object.__setattr__(post, "run_id", komorka)
    return kolejka.post(post)
""",
}

# Postaci, które bez kontroli dokładnego typu w chwili zapisu (outbox._queue_text) dawałyby plikowi kolejki wartość
# komórki, a z nią dostają odmowę → fragment zgłoszenia biegu przez plik kolejki.
ODMOWY_KOLEJKI: Final = {
    "zapis do __dict__ gotowej wysyłki": (
        _GOTOWA
        + """def wyslij(kolejka: Outbox, post: Post, komorka: str) -> bool:
    post.__dict__["parts"] = (komorka,)
    return kolejka.post(post)
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "setattr to_json na klasie Post": (
        _GOTOWA
        + """def wyslij(kolejka: Outbox, post: Post, komorka: str) -> bool:
    zapamietaj = Post.__dict__["to_json"]
    setattr(Post, "to_json", lambda self: komorka)
    try:
        return kolejka.post(post)
    finally:
        setattr(Post, "to_json", zapamietaj)
""",
        "bieg: plik kolejki bez wartości komórki",
    ),
    "replace z getattr modułu copy": (
        _GOTOWA
        + """import copy


def wyslij(kolejka: Outbox, post: Post, komorka: str) -> bool:
    return kolejka.post(getattr(copy, "replace")(post, parts=(komorka,)))
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "cast innej klasy na Post": (
        _GOTOWA
        + """from typing import cast


def wyslij(kolejka: Outbox, wysylka: object) -> bool:
    return kolejka.post(cast(Post, wysylka))
""",
        "bieg TypeError: Plik kolejki bierze tylko Post i LogsPost, nie Atrapa.",
    ),
    "wartość typu Any": (
        """from typing import Any

from rozliczenia.centrum.outbox import Outbox


def wyslij(kolejka: Outbox, wysylki: dict[str, Any]) -> bool:
    return kolejka.post(wysylki["inna"])
""",
        "bieg TypeError: Plik kolejki bierze tylko Post i LogsPost, nie Atrapa.",
    ),
    "podklasa LogsPost w biegu z własnym to_json": (
        """from typing import Any

from rozliczenia.centrum.comment_versions import LogsPost
from rozliczenia.centrum.outbox import Outbox


def wyslij(kolejka: Outbox, komorka: str) -> bool:
    klasa: Any = type("Moja", (LogsPost,), {"to_json": lambda self: komorka})
    nowa: LogsPost = object.__new__(klasa)
    return kolejka.post(nowa)
""",
        "bieg TypeError: Plik kolejki bierze tylko Post i LogsPost, nie Moja.",
    ),
    "refleksja: przypisanie __class__ LogsPost obiektowi z atrapą wysyłki w slocie": (
        """from rozliczenia.centrum.comment_versions import LogsPost
from rozliczenia.centrum.outbox import Outbox


class Obca:
    __slots__ = ("_LogsPost__post",)


def wyslij(kolejka: Outbox, wysylka: object) -> bool:
    obca = Obca()
    object.__setattr__(obca, "_LogsPost__post", wysylka)
    object.__setattr__(obca, "__class__", LogsPost)
    assert isinstance(obca, LogsPost)
    return kolejka.post(obca)
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
}


class Atrapa:
    """Wysyłka innej klasy niż ``Post`` i ``LogsPost``: pola wysyłki z wartością komórki i własne ``to_json``."""

    target = NewIssue("uwaga-taty", tool("Tytuł"))
    period = None
    run_id = "r"
    header = None
    archive = None
    rank = Rank.OWN

    def __init__(self, komorka: str) -> None:
        self.parts = (komorka,)
        self.komorka = komorka

    def to_json(self) -> str:
        return json.dumps({"komorka": self.komorka}, ensure_ascii=False)


def _w_pliku_kolejki_przez_outbox(plik: Path, katalog: Path) -> list[str]:
    """Bieg próbki, która podaje wysyłkę ``Outbox.post``: kolejka bez wątku wysyłki, więc plik zostaje w ``katalog``."""

    log = CentrumLog(katalog / "centrum-rozliczen.log")
    keyed = KeyedBox(FakeReportBox(), lambda: None, clock=ManualClock(), opening=NotesFile(katalog / OPENING_FILE, replace_atomically, log.box_notes_unavailable))
    kolejka = Outbox(katalog / "kolejka", keyed, log, clock=ManualClock(), listener=QueueListener(), start=lambda drain: None)
    (katalog / "kolejka").mkdir(parents=True)
    argumenty = _argumenty_wysylki() | {"kolejka": kolejka, "wysylka": Atrapa(_KOMORKA), "wysylki": {"inna": Atrapa(_KOMORKA)}}
    return bieg_do_pliku_kolejki(modul(plik), argumenty, _KOMORKA, katalog / "kolejka")


@wymaga_ruff_i_mypy
def test_kolejka_bierze_tylko_wysylke_z_konstruktora_post_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: kod for opis, (kod, _) in DROGI_OBOK_POST.items()} | ZNANE_LUKI
    pliki = zapisz(probki, tmp_path)
    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_kolejki.py")

    assert {opis: zgloszenia[opis] for opis, (_, odrzucenie) in DROGI_OBOK_POST.items() if not any(odrzucenie in z for z in zgloszenia[opis])} == {}
    assert_znane_luki(
        {opis: zgloszenia[opis] + _w_pliku_kolejki_przez_outbox(pliki[opis], tmp_path / f"bieg_{numer}") for numer, opis in enumerate(ZNANE_LUKI)},
        "tests/test_kolejka_skrzynki_zgloszen.py",
    )


@pytest.mark.parametrize("opis", ODMOWY_KOLEJKI.keys())
def test_plik_kolejki_odmawia_wysylki_innego_typu_niz_post_i_logs_post_w_chwili_zapisu(opis: str, tmp_path: Path) -> None:
    """``Outbox.post`` pisze plik kolejki funkcją modułu (``_queue_text``), która bierze tylko wysyłkę dokładnie ``Post``
    albo ``LogsPost`` z tekstem dokładnie ``Outgoing``, więc atrapa, podklasa, ``to_json`` podmienione na klasie i pole
    zmienione po konstruktorze nie dają plikowi wartości komórki (#1551)."""

    kod, odmowa = ODMOWY_KOLEJKI[opis]
    plik = tmp_path / "probka.py"
    plik.write_text(kod, encoding="utf-8")

    zgloszenia = _w_pliku_kolejki_przez_outbox(plik, tmp_path)

    assert len(zgloszenia) == 1 and odmowa in zgloszenia[0], zgloszenia


# Tekst do wysyłki z komórki taty bez strażnika pracy Centrum (ADR 0025, reguła danych): drogi, znane luki i odmowy
# pliku kolejki. Wartość komórki jest syntetyczna.
_KOMORKA: Final = "Syntetyczna Lipowa 5"

_POST = """\
from rozliczenia.centrum.outbox import NewIssue, Post

"""

_PODKLASA_TEKSTU: Final = _POST + """from typing import Any

from rozliczenia.client_data import Outgoing


class Mixin:
    def __init_subclass__(cls, **kwargs: object) -> None:
        pass


def wysylka(komorka: str, cel: NewIssue, post: Post) -> Post:
    tekst: Any = type.__new__(type(Outgoing), "Tekst", (Mixin, Outgoing), {"__new__": lambda cls, t: str.__new__(cls, t)})
"""
"""Początek próbki z podklasą ``Outgoing`` z ``type.__new__`` i bazą przed nim, której ``__init_subclass__`` nie woła
``super()``: taka podklasa omija odmowę ``__init_subclass__`` typu przy jej powstaniu."""

# Znane luki jednej drogi wyjścia (tests/fixtures/znane_luki.py): opis postaci → nowy producent w src/rozliczenia/centrum,
# który daje kolejce wartość z komórki taty bez strażnika pracy Centrum, a przechodzi przez mypy i ruff z konfiguracją src/
# i przez plik kolejki (tests/fixtures/plik_kolejki.py).
ZNANE_LUKI_TEKSTU: Final = {
    "str.__new__ z klasą Outgoing": _POST
    + """from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (str.__new__(Outgoing, komorka),))
""",
    "dowód z getattr modułu": _POST
    + """from rozliczenia import client_data


def wysylka(komorka: str, cel: NewIssue) -> Post:
    tekst = client_data.Outgoing(komorka, getattr(client_data, "_PASSED"))
    return Post(cel, None, "r", None, (tekst,))
""",
    "tool zaimportowane z noqa": _POST
    + """from rozliczenia.client_data import tool  # noqa: TID251


def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (tool(komorka),))
""",
    "parser pliku kolejki z tytułem z komórki": """from rozliczenia.centrum import outbox
from rozliczenia.centrum.outbox import NewIssue, Post


def wysylka(komorka: str, cel: NewIssue) -> Post:
    znaleziony = outbox._target({"label": "zgloszenie", "title": komorka}, "new_issue")
    assert isinstance(znaleziony, NewIssue)
    return Post(cel, None, "r", None, (znaleziony.title,))
""",
    # Kontrola w chwili zapisu pliku kolejki sprawdza typ obiektu tak, jak go zastaje, więc zmiana obiektu, klasy albo
    # modułu sprawdzenia w chwili działania ją omija: jedna próbka na klasę (#1551).
    "zmiana obiektu w chwili działania: przypisanie __class__ Outgoing napisowi obcej podklasy str": _POST
    + """from typing import cast

from rozliczenia.client_data import Outgoing


class Obcy(str):
    __slots__ = ()


def wysylka(komorka: str, cel: NewIssue) -> Post:
    tekst = Obcy(komorka)
    object.__setattr__(tekst, "__class__", Outgoing)
    return Post(cel, None, "r", None, (cast(Outgoing, tekst),))
""",
    "zmiana modułu sprawdzenia w chwili działania: nazwa Outgoing w outbox": """from rozliczenia.centrum import outbox
from rozliczenia.centrum.outbox import KnownIssue, Post


def wysylka(komorka: str) -> str:
    gotowa = Post(KnownIssue("uwaga-taty", 5), None, "r", None, (komorka,))  # type: ignore[arg-type]
    zapamietaj = getattr(outbox, "Outgoing")
    setattr(outbox, "Outgoing", str)
    try:
        return gotowa.to_json()
    finally:
        setattr(outbox, "Outgoing", zapamietaj)
""",
}

# Postaci, które bez kontroli dokładnego typu w chwili użycia (outbox._queue_text, outbox._pack, client_data.Outgoing.__add__)
# dawałyby plikowi kolejki wartość komórki, a z nią dostają odmowę → fragment zgłoszenia biegu.
ODMOWY_TEKSTU: Final = {
    "cast na Outgoing": (
        _POST
        + """from typing import cast

from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (cast(Outgoing, komorka),))
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "wartość typu Any": (
        _POST
        + """from typing import Any


def wysylka(wiersz: dict[str, Any], cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (wiersz["ADRES"],))
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "goły napis z type: ignore": (
        _POST
        + """def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", None, (komorka,))  # type: ignore[arg-type]
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "goły napis w nagłówku z type: ignore": (
        _POST
        + """def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post(cel, None, "r", komorka, (cel.title,))  # type: ignore[arg-type]
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "object.__setattr__ stopnia gotowej wysyłki: atrapa z wartością komórki": (
        """from types import SimpleNamespace

from rozliczenia.centrum.outbox import Post


def wysylka(komorka: str, post: Post) -> Post:
    object.__setattr__(post, "rank", SimpleNamespace(value=komorka))
    return post
""",
        "stopień Rank",
    ),
    "object.__setattr__ na częściach gotowej wysyłki": (
        """from rozliczenia.centrum.outbox import Post


def wysylka(komorka: str, post: Post) -> Post:
    object.__setattr__(post, "parts", (komorka,))
    return post
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "type.__new__ z bazą bez super(): podklasa Outgoing w części": (
        _PODKLASA_TEKSTU + '    return Post(cel, None, "r", None, (tekst(komorka),))\n',
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "przypisanie __bases__ obcej podklasie str: podklasa Outgoing w części": (
        _POST
        + """from typing import Any

from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, cel: NewIssue) -> Post:
    klasa: Any = type("Tekst", (type("Baza", (str,), {"__slots__": ()}),), {"__slots__": ()})
    klasa.__bases__ = (Outgoing,)
    assert issubclass(klasa, Outgoing)
    return Post(cel, None, "r", None, (str.__new__(klasa, komorka),))
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "metaklasa z __eq__ zawsze prawdziwym: podklasa Outgoing w części": (
        _POST
        + """from typing import Any

from rozliczenia.client_data import Outgoing


class Mixin:
    def __init_subclass__(cls, **kwargs: object) -> None:
        pass


class Rowna(type):
    def __eq__(cls, other: object) -> bool:
        return True

    __hash__ = type.__hash__


def wysylka(komorka: str, cel: NewIssue) -> Post:
    klasa: Any = type.__new__(Rowna, "Tekst", (Mixin, Outgoing), {})
    return Post(cel, None, "r", None, (str.__new__(klasa, komorka),))
""",
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "sklejenie prawdziwego Outgoing z podklasą w części": (
        _PODKLASA_TEKSTU + '    return Post(cel, None, "r", None, (post.parts[0] + tekst(komorka),))\n',
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "sklejenie podklasy z prawdziwym Outgoing w części": (
        _PODKLASA_TEKSTU + '    return Post(cel, None, "r", None, (tekst(komorka) + post.parts[0],))\n',
        "bieg TypeError: Plik kolejki bierze tylko tekst Outgoing",
    ),
    "cast: blok Post.of z komórki": (
        _POST
        + """from typing import cast

from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, cel: NewIssue) -> Post:
    return Post.of(cel, period=None, run_id="r", blocks=[cast(Outgoing, komorka)], frame=lambda n, c, t: t)
""",
        "bieg TypeError: Wysyłka bierze tylko bloki Outgoing",
    ),
    "blok Post.of z podklasy Outgoing": (
        _PODKLASA_TEKSTU
        + '    return Post.of(cel, period=None, run_id="r", blocks=[post.parts[0], tekst(komorka)], frame=lambda n, c, t: t)\n',
        "bieg TypeError: Wysyłka bierze tylko bloki Outgoing",
    ),
    "bloki Post.of z innym drugim przebiegiem": (
        _POST
        + """from collections.abc import Iterator
from typing import cast

from rozliczenia.client_data import Outgoing


class Bloki(list[Outgoing]):
    def __init__(self, prawdziwe: list[Outgoing], komorka: str) -> None:
        super().__init__(prawdziwe)
        self.przebiegi = 0
        self.komorka = komorka

    def __iter__(self) -> Iterator[Outgoing]:
        self.przebiegi += 1
        return iter(super().copy() if self.przebiegi == 1 else [cast(Outgoing, self.komorka)])


def wysylka(komorka: str, cel: NewIssue, post: Post) -> Post:
    return Post.of(cel, period=None, run_id="r", blocks=Bloki(list(post.parts), komorka), frame=lambda n, c, t: t)
""",
        "bieg: plik kolejki bez wartości komórki",
    ),
}

_CEL: Final = """\
from rozliczenia.centrum.outbox import NewIssue, OpenIssue, PeriodThread, Post
from rozliczenia.client_data import ForbiddenValues, guarded


def wysylka(komorka: str, pamiec: ForbiddenValues) -> Post:
    tekst = guarded(pamiec, "Uwaga", "treść").text
    return Post({cel}, None, "r", None, (tekst,))
"""
_GOTOWY_CEL: Final = "from rozliczenia.centrum.outbox import NewIssue, Post\n\n\n"

# Drogi do pola tekstowego celu wysyłki z wartością z komórki taty bez strażnika (każde pole każdego celu i ich formy
# siostrzane) → zgłoszenie mypy albo ruff, które każdą odrzuca w nowym module ``src/rozliczenia/centrum``.
DROGI_DO_CELU: Final = {
    **{
        f"{cel.split('(')[0]} {pole} z komórki": (_CEL.format(cel=cel), 'has incompatible type "str"; expected "Outgoing"')
        for pole, cel in (
            ("title", 'NewIssue("uwaga-taty", komorka)'),
            ("line", 'PeriodThread("kontrola-ilosci", komorka, "new_issue", tekst)'),
            ("title", 'PeriodThread("kontrola-ilosci", tekst, "new_issue", komorka)'),
            ("line", 'OpenIssue("zgloszenie", komorka, tekst, tekst)'),
            ("title", 'OpenIssue("zgloszenie", tekst, komorka, tekst)'),
            ("again", 'OpenIssue("zgloszenie", tekst, tekst, komorka)'),
        )
    },
    "podklasa celu": (_GOTOWY_CEL + "class Cel(NewIssue):\n    pass\n", 'Cannot inherit from final class "NewIssue"'),
    "własny cel": (
        _GOTOWY_CEL
        + """from dataclasses import dataclass

from rozliczenia.client_data import Outgoing


@dataclass(frozen=True)
class Cel:
    label: str
    title: str


def wysylka(komorka: str, tekst: Outgoing) -> Post:
    return Post(Cel("uwaga-taty", komorka), None, "r", None, (tekst,))
""",
        'Argument 1 to "Post" has incompatible type "Cel"',
    ),
    "dataclasses.replace celu": (
        _GOTOWY_CEL
        + """import dataclasses


def wysylka(komorka: str, cel: NewIssue) -> NewIssue:
    return dataclasses.replace(cel, title=komorka)
""",
        'Argument "title" to "replace" of "NewIssue" has incompatible type "str"',
    ),
    "__replace__ celu": (
        _GOTOWY_CEL + 'def wysylka(komorka: str, cel: NewIssue) -> NewIssue:\n    return cel.__replace__(title=komorka)\n',
        'Argument "title" to "__replace__" of "NewIssue" has incompatible type "str"',
    ),
    "copy.replace celu": (
        _GOTOWY_CEL + 'import copy\n\n\ndef wysylka(komorka: str, cel: NewIssue) -> NewIssue:\n    return copy.replace(cel, title=komorka)\n',
        "`copy.replace` is banned",
    ),
    "tytuł Uwagi taty z komórki": (
        """from rozliczenia.centrum.case_delivery import note_post
from rozliczenia.centrum.outbox import Post
from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, tekst: Outgoing) -> Post:
    return note_post("n", komorka, tekst, logs_on_the_way=False)
""",
        'Argument 2 to "note_post" has incompatible type "str"; expected "Outgoing"',
    ),
    "tytuł Zgłoszenia z komórki": (
        """from rozliczenia.centrum.outbox import OpenIssue
from rozliczenia.centrum.reports import report_target


def wysylka(komorka: str) -> OpenIssue:
    return report_target("0123456789abcdef", komorka)
""",
        'Argument 2 to "report_target" has incompatible type "str"; expected "Outgoing"',
    ),
}

# Znane luki celu wysyłki (tests/fixtures/znane_luki.py): postaci, które dają polu tekstowemu celu wartość z komórki taty
# bez strażnika, a mypy, ruff i plik kolejki (tests/fixtures/plik_kolejki.py) ich nie łapią.
ZNANE_LUKI_CELU: Final = {
    "str.__new__ z klasą Outgoing w tytule celu": _GOTOWY_CEL
    + """from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, post: Post) -> Post:
    return Post(NewIssue("uwaga-taty", str.__new__(Outgoing, komorka)), None, "r", None, post.parts)
""",
    "zmiana modułu sprawdzenia w chwili działania: sprawdzenie pola Outgoing w outbox": _GOTOWY_CEL
    + """from rozliczenia.centrum import outbox


def wysylka(komorka: str, post: Post) -> str:
    gotowa = Post(NewIssue("uwaga-taty", komorka), None, "r", None, post.parts)  # type: ignore[arg-type]
    zapamietaj = outbox._FIELDS["Outgoing"]
    outbox._FIELDS["Outgoing"] = lambda wartosc: True
    try:
        return gotowa.to_json()
    finally:
        outbox._FIELDS["Outgoing"] = zapamietaj
""",
}

# Postaci, które bez kontroli dokładnego typu celu w chwili zapisu (outbox._target_json) dawałyby polu celu w pliku
# kolejki wartość komórki, a z nią dostają odmowę → fragment zgłoszenia biegu.
ODMOWY_CELU: Final = {
    "object.__setattr__ na gotowym celu": (
        _GOTOWY_CEL
        + """def wysylka(komorka: str, cel: NewIssue, post: Post) -> Post:
    object.__setattr__(cel, "title", komorka)
    return Post(cel, None, "r", None, post.parts)
""",
        "bieg TypeError: Pole celu NewIssue.title w pliku kolejki ma typ str.",
    ),
    "zapis do __dict__ gotowego celu": (
        _GOTOWY_CEL
        + """def wysylka(komorka: str, cel: NewIssue, post: Post) -> Post:
    cel.__dict__["title"] = komorka
    return Post(cel, None, "r", None, post.parts)
""",
        "bieg TypeError: Pole celu NewIssue.title w pliku kolejki ma typ str.",
    ),
    "cast na Outgoing w tytule celu": (
        _GOTOWY_CEL
        + """from typing import cast

from rozliczenia.client_data import Outgoing


def wysylka(komorka: str, post: Post) -> Post:
    return Post(NewIssue("uwaga-taty", cast(Outgoing, komorka)), None, "r", None, post.parts)
""",
        "bieg TypeError: Pole celu NewIssue.title w pliku kolejki ma typ str.",
    ),
    "tytuł celu typu Any": (
        _GOTOWY_CEL
        + """from typing import Any


def wysylka(wiersz: dict[str, Any], post: Post) -> Post:
    return Post(NewIssue("uwaga-taty", wiersz["ADRES"]), None, "r", None, post.parts)
""",
        "bieg TypeError: Pole celu NewIssue.title w pliku kolejki ma typ str.",
    ),
    "etykieta celu typu Any": (
        _GOTOWY_CEL
        + """from typing import Any


def wysylka(wiersz: dict[str, Any], post: Post) -> Post:
    return Post(NewIssue(wiersz["ADRES"], post.parts[0]), None, "r", None, post.parts)
""",
        "bieg TypeError: Pole celu NewIssue.label w pliku kolejki ma typ str.",
    ),
    "type.__new__ z bazą bez super(): podklasa Outgoing w tytule celu": (
        _PODKLASA_TEKSTU + '    return Post(NewIssue("uwaga-taty", tekst(komorka)), None, "r", None, post.parts)\n',
        "bieg TypeError: Pole celu NewIssue.title w pliku kolejki ma typ Tekst.",
    ),
    "podklasa celu w biegu: type() z NewIssue i adnotacją title: int": (
        """from typing import Any

from rozliczenia.centrum.outbox import NewIssue, Post


def wysylka(komorka: str, post: Post) -> Post:
    cel: Any = type("Cel", (NewIssue,), {"__annotations__": {"title": int}})
    return Post(cel("uwaga-taty", komorka), None, "r", None, post.parts)
""",
        "bieg TypeError: Plik kolejki bierze tylko cel z rozliczenia.centrum.outbox, nie Cel.",
    ),
    "przypisanie __bases__ obcej klasie: podklasa NewIssue": (
        """from typing import Any

from rozliczenia.centrum.outbox import NewIssue, Post


def wysylka(komorka: str, post: Post) -> Post:
    cel: Any = type("Cel", (type("Baza", (), {}),), {})
    cel.__bases__ = (NewIssue,)
    return Post(cel("uwaga-taty", komorka), None, "r", None, post.parts)
""",
        "bieg TypeError: Plik kolejki bierze tylko cel z rozliczenia.centrum.outbox, nie Cel.",
    ),
}


def _argumenty_wysylki() -> dict[str, object]:
    """Argumenty funkcji próbki drogi wyjścia, świeże dla każdej próbki, bo próbka zmienia gotową wysyłkę i cel."""

    return {
        "komorka": _KOMORKA,
        "wiersz": {"ADRES": _KOMORKA},
        "cel": NewIssue("uwaga-taty", tool("Tytuł")),
        "post": Post(NewIssue("uwaga-taty", tool("Tytuł")), None, "r", None, (tool("Treść"),)),
    }


def _w_pliku_kolejki(plik: Path) -> list[str]:
    return bieg_do_pliku_kolejki(modul(plik), _argumenty_wysylki(), _KOMORKA)


def test_bieg_znanej_luki_przez_plik_kolejki_zglasza_probke_ktorej_komorka_nie_dochodzi_do_pliku(tmp_path: Path) -> None:
    """Próbka znanej luki przechodzi bieg tylko wtedy, gdy wartość komórki stoi w pliku kolejki; próbka, która wysyła sam
    tekst narzędzia, jest zgłoszeniem, więc nie zostałaby znaną luką (przegląd #1731, runda 1, D1)."""

    plik = tmp_path / "bez_komorki.py"
    plik.write_text(_POST + 'def wysylka(komorka: str, cel: NewIssue) -> Post:\n    return Post(cel, None, "r", None, (cel.title,))\n', encoding="utf-8")

    assert _w_pliku_kolejki(plik) == ["bieg: plik kolejki bez wartości komórki"]


@wymaga_ruff_i_mypy
def test_znane_luki_jednej_drogi_wyjscia_przechodza_przez_mypy_ruff_i_plik_kolejki(tmp_path: Path) -> None:
    pliki = zapisz(ZNANE_LUKI_TEKSTU, tmp_path)
    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_luki.py")

    assert_znane_luki(
        {opis: zgloszenia[opis] + _w_pliku_kolejki(pliki[opis]) for opis in ZNANE_LUKI_TEKSTU},
        "tests/test_kolejka_skrzynki_zgloszen.py (ZNANE_LUKI_TEKSTU)",
    )


@wymaga_ruff_i_mypy
def test_pole_tekstowe_celu_wysylki_z_komorki_bez_straznika_nie_przechodzi_mypy_a_znane_luki_przechodza(tmp_path: Path) -> None:
    probki = {opis: kod for opis, (kod, _) in DROGI_DO_CELU.items()} | ZNANE_LUKI_CELU
    pliki = zapisz(probki, tmp_path)
    zgloszenia = ruff_i_mypy(pliki, sonda=ROOT / "src" / "rozliczenia" / "centrum" / "sonda_celu.py")

    assert {opis: zgloszenia[opis] for opis, (_, odrzucenie) in DROGI_DO_CELU.items() if not any(odrzucenie in z for z in zgloszenia[opis])} == {}
    assert_znane_luki(
        {opis: zgloszenia[opis] + _w_pliku_kolejki(pliki[opis]) for opis in ZNANE_LUKI_CELU}, "tests/test_kolejka_skrzynki_zgloszen.py (ZNANE_LUKI_CELU)"
    )


@pytest.mark.parametrize("opis", [*ODMOWY_TEKSTU, *ODMOWY_CELU])
def test_plik_kolejki_odmawia_tekstu_i_celu_innego_typu_niz_dokladnie_outgoing_w_chwili_uzycia(opis: str, tmp_path: Path) -> None:
    """Plik kolejki (``_queue_text``), bloki ``Post.of`` (``_pack``) i sklejenie (``Outgoing.__add__``) biorą tekst i cel
    dokładnego typu w chwili użycia, a wejście czytają raz, więc podklasa, jakkolwiek powstała, napis spoza strażnika i
    sekwencja z innym drugim przebiegiem nie dają plikowi kolejki wartości komórki (#1551)."""

    kod, odmowa = (ODMOWY_TEKSTU | ODMOWY_CELU)[opis]
    plik = tmp_path / "probka.py"
    plik.write_text(kod, encoding="utf-8")

    zgloszenia = _w_pliku_kolejki(plik)

    assert len(zgloszenia) == 1 and odmowa in zgloszenia[0], zgloszenia
