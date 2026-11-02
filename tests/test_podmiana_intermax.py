"""Podmiana INTERMAX (``intermax_replace``): reguły, które Uporządkowanie INTERMAX i przywrócenie Kopii dzielą (#716).

Każda reguła biegnie dla obu rodzajów Kopii INTERMAX (``ordering``, ``restore``): przy tym samym błędzie podmiany oba
procesy zostawiają INTERMAX, folder obok niego i Kopie tak samo. Podmiana czyta i porównuje tylko bajty, więc INTERMAX
to tu bajty, nie skoroszyt; ustawienia taty i treść dnia sprawdzają testy obu procesów. Usterki idą przez
``FaultyDisk``, a Excel to prawdziwy plik blokady ``~$`` obok INTERMAX.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import errno
from pathlib import Path

import pytest

from rozliczenia.intermax_copies import KEPT, Before
from rozliczenia.intermax_file import WriteMismatch
from rozliczenia.intermax_replace import LOCAL_DISK, Refusal, Replaced, Waiting, replace_register
from rozliczenia.workbook_files import Problem, WorkbookError

from tests.fixtures.clock import ManualClock
from tests.fixtures.intermax_disk import FaultyDisk, denied, failing_replace, no_space, partial_copy, writing

NOW = datetime(2026, 10, 26, 14, 5, 7)
ORIGINAL = b"INTERMAX sprzed podmiany"
NEW = b"INTERMAX po podmianie"
NAMES: dict[Before, str] = {
    "ordering": "INTERMAX przed uporządkowaniem 2026-10-26 14-05-07.xlsx",
    "restore": "INTERMAX przed przywróceniem 2026-10-26 14-05-07.xlsx",
}


@pytest.fixture(params=["ordering", "restore"])
def before(request: pytest.FixtureRequest) -> Before:
    kind: Before = request.param
    return kind


@dataclass
class Folders:
    register: Path
    copies: Path
    clock: ManualClock

    @property
    def lock(self) -> Path:
        return self.register.with_name(f"~${self.register.name}")

    def state(self) -> tuple[bytes, list[str], dict[str, bytes]]:
        """Bajty INTERMAX, pliki obok niego i Kopie INTERMAX z bajtami."""

        copies = {path.name: path.read_bytes() for path in self.copies.iterdir()} if self.copies.is_dir() else {}
        return self.register.read_bytes(), sorted(path.name for path in self.register.parent.iterdir()), copies

    def replace(
        self,
        before: Before,
        disk: FaultyDisk | None = None,
        *,
        check: Callable[[bytes], None] | None = None,
        content: bytes = NEW,
    ) -> Replaced | Refusal:
        def same_as_content(written: bytes) -> None:
            if written != content:
                raise WriteMismatch("treść")

        return replace_register(
            self.register,
            ORIGINAL,
            content,
            check or same_as_content,
            before=before,
            copies=self.copies,
            now=lambda: NOW,
            waiting=Waiting(self.clock, self.clock.pause),
            disk=(disk or FaultyDisk()).disk(),
        )


@pytest.fixture
def folders(tmp_path: Path) -> Folders:
    register = tmp_path / "OneDrive" / "ZLECENIA INTERMAX OD 08_11_2021.xlsx"
    register.parent.mkdir()
    register.write_bytes(ORIGINAL)
    return Folders(register, tmp_path / "Kopie INTERMAX", ManualClock(seconds=4000.0))


@contextmanager
def _unchanged(folders: Folders) -> Iterator[None]:
    """INTERMAX bajt w bajt, bez pliku tymczasowego obok i z tymi samymi Kopiami po bloku."""

    state = folders.state()
    yield
    assert folders.state() == state


def _older_copies(folders: Folders, count: int = KEPT) -> list[str]:
    folders.copies.mkdir(exist_ok=True)
    names = [f"INTERMAX przed przywróceniem 2026-10-{day:02d} 08-00-00.xlsx" for day in range(1, count + 1)]
    for name in names:
        (folders.copies / name).write_bytes(name.encode())
    return names


def test_udana_podmiana_zostawia_nowe_bajty_i_kopie_bajtow_sprzed_podmiany(folders: Folders, before: Before) -> None:
    outcome = folders.replace(before)

    assert isinstance(outcome, Replaced)
    assert (outcome.copy.path.name, outcome.copy.before, outcome.copy.moment) == (NAMES[before], before, NOW.astimezone())
    assert outcome.old_copies_kept is False
    assert folders.state() == (NEW, [folders.register.name], {NAMES[before]: ORIGINAL})


def test_po_udanej_podmianie_zostaje_10_najnowszych_kopii(folders: Folders, before: Before) -> None:
    older = _older_copies(folders)

    outcome = folders.replace(before)

    assert isinstance(outcome, Replaced) and outcome.old_copies_kept is False
    assert sorted(folders.state()[2]) == sorted([*older[1:], NAMES[before]])


def test_nieudane_usuniecie_starszej_kopii_to_fakt_przy_podmienionym_intermax(folders: Folders, before: Before) -> None:
    older = _older_copies(folders)

    def stuck(path: Path) -> None:
        raise PermissionError(errno.EACCES, "Kopia otwarta w Excelu")

    outcome = folders.replace(before, FaultyDisk(remove=stuck))

    assert isinstance(outcome, Replaced) and outcome.old_copies_kept is True
    assert folders.register.read_bytes() == NEW
    assert sorted(folders.state()[2]) == sorted([*older, NAMES[before]])


def test_starsza_kopia_usunieta_wczesniej_przez_kogos_innego_nie_jest_kopia_ktora_zostala(
    folders: Folders, before: Before
) -> None:
    older = _older_copies(folders)

    def gone_first(path: Path) -> None:
        path.unlink()  # tata usunął Kopię w Eksploratorze albo OneDrive zsynchronizował jej usunięcie
        LOCAL_DISK.remove(path)

    outcome = folders.replace(before, FaultyDisk(remove=gone_first))

    assert isinstance(outcome, Replaced) and outcome.old_copies_kept is False
    assert sorted(folders.state()[2]) == sorted([*older[1:], NAMES[before]])


def test_kopia_powstaje_tuz_przed_podmiana(folders: Folders, before: Before) -> None:
    copy = folders.copies / NAMES[before]
    seen: list[bytes | None] = []

    def replace(source: Path, target: Path) -> None:
        seen.append(copy.read_bytes() if copy.exists() else None)
        source.replace(target)

    assert isinstance(folders.replace(before, FaultyDisk(replace=replace)), Replaced)
    assert seen == [ORIGINAL]


def test_intermax_otwarty_w_excelu_przed_kopia_to_excel_bez_kopii(folders: Folders, before: Before) -> None:
    folders.lock.write_bytes(b"")

    with _unchanged(folders):
        assert folders.replace(before) is Refusal.EXCEL_HOLDS


def test_odmowa_podmiany_przy_otwartym_excelu_to_excel_bez_czekania_i_bez_kopii(folders: Folders, before: Before) -> None:
    replace, attempts = failing_replace(denied, before=lambda: folders.lock.write_bytes(b""))

    with _unchanged(folders):
        outcome = folders.replace(before, FaultyDisk(replace=replace))
        folders.lock.unlink()

    assert outcome is Refusal.EXCEL_HOLDS
    assert (len(attempts), folders.clock.seconds) == (1, 4000.0)


def test_odmowa_podmiany_bez_excela_po_5_sekundach_to_onedrive_bez_kopii(folders: Folders, before: Before) -> None:
    replace, attempts = failing_replace(denied)

    with _unchanged(folders):
        assert folders.replace(before, FaultyDisk(replace=replace)) is Refusal.ONEDRIVE_HOLDS

    assert (len(attempts), folders.clock.seconds) == (11, 4005.0)


def test_podmiana_po_chwilowej_odmowie_onedrive_sie_udaje(folders: Folders, before: Before) -> None:
    replace, attempts = failing_replace(denied, times=2)

    outcome = folders.replace(before, FaultyDisk(replace=replace))

    assert isinstance(outcome, Replaced)
    assert (len(attempts), folders.clock.seconds) == (3, 4001.0)
    assert folders.state() == (NEW, [folders.register.name], {NAMES[before]: ORIGINAL})


def test_wersja_wgrana_przez_onedrive_w_przerwie_zostaje_a_kopia_znika(folders: Folders, before: Before) -> None:
    worker = b"INTERMAX z poprawka pracownika"
    replace, attempts = failing_replace(denied, before=lambda: folders.register.write_bytes(worker))

    outcome = folders.replace(before, FaultyDisk(replace=replace))

    assert outcome is Refusal.ONEDRIVE_HOLDS
    assert len(attempts) == 1
    assert folders.state() == (worker, [folders.register.name], {})


@pytest.mark.parametrize(
    ("problem", "refusal"),
    [(Problem.OPEN_IN_EXCEL, Refusal.EXCEL_HOLDS), (Problem.INACCESSIBLE, Refusal.ONEDRIVE_HOLDS)],
    ids=["tata otwiera INTERMAX w Excelu", "INTERMAX niedostępny"],
)
def test_intermax_nieczytelny_w_przerwie_przed_ponowna_proba_to_odmowa_bez_kopii(
    folders: Folders, before: Before, problem: Problem, refusal: Refusal
) -> None:
    replace, attempts = failing_replace(denied)

    def read(path: Path) -> bytes:
        if path == folders.register:
            raise WorkbookError(path, problem)
        return path.read_bytes()

    with _unchanged(folders):
        assert folders.replace(before, FaultyDisk(read=read, replace=replace)) is refusal

    assert len(attempts) == 1


def test_inny_blad_podmiany_niz_odmowa_to_zapis_nieudany_bez_czekania_i_bez_kopii(folders: Folders, before: Before) -> None:
    # Excel otwiera INTERMAX tuż przed podmianą, a ta kończy się brakiem miejsca: Excel nie zmienia tej prawdy.
    replace, attempts = failing_replace(no_space, before=lambda: folders.lock.write_bytes(b""))

    with _unchanged(folders):
        outcome = folders.replace(before, FaultyDisk(replace=replace))
        folders.lock.unlink()

    assert outcome is Refusal.WRITE_FAILED
    assert (len(attempts), folders.clock.seconds) == (1, 4000.0)


def test_nieudany_zapis_pliku_tymczasowego_to_zapis_nieudany_bez_kopii(folders: Folders, before: Before) -> None:
    def full(path: Path, content: bytes) -> None:
        raise no_space()

    with _unchanged(folders):
        assert folders.replace(before, FaultyDisk(write=full)) is Refusal.WRITE_FAILED


def test_plik_tymczasowy_ktorego_nie_da_sie_utworzyc_to_zapis_nieudany(tmp_path: Path, before: Before) -> None:
    folders = Folders(tmp_path / "brak folderu" / "INTERMAX.xlsx", tmp_path / "Kopie INTERMAX", ManualClock())

    assert folders.replace(before) is Refusal.WRITE_FAILED
    assert list(tmp_path.iterdir()) == []


def test_niezgodny_zapis_to_zapis_niezgodny_a_kopia_nawet_nie_powstaje(folders: Folders, before: Before) -> None:
    created: list[Path] = []

    def create(path: Path, content: bytes) -> None:
        created.append(path)
        raise AssertionError("Kopia przed zgodnym sprawdzeniem zapisu")

    disk = FaultyDisk(write=writing(lambda data: data[:-1]), create=create)

    with _unchanged(folders):
        assert folders.replace(before, disk) is Refusal.WRITE_MISMATCH

    assert created == []


def test_nieczytelny_plik_tymczasowy_to_zapis_niezgodny_bez_kopii(folders: Folders, before: Before) -> None:
    def unreadable(written: bytes) -> None:
        raise KeyError("xl/workbook.xml")  # openpyxl nie znajduje części skoroszytu

    with _unchanged(folders):
        assert folders.replace(before, check=unreadable) is Refusal.WRITE_MISMATCH


def test_kopia_o_tej_samej_nazwie_zostaje_nietknieta(folders: Folders, before: Before) -> None:
    folders.copies.mkdir()
    (folders.copies / NAMES[before]).write_bytes(b"Kopia sprzed chwili")

    with _unchanged(folders):
        assert folders.replace(before) is Refusal.COPY_EXISTS


def test_kopia_o_tej_samej_nazwie_zostaje_takze_gdy_zapis_kopii_konczy_sie_innym_bledem(
    folders: Folders, before: Before
) -> None:
    folders.copies.mkdir()
    (folders.copies / NAMES[before]).write_bytes(b"Kopia sprzed chwili")

    def locked(path: Path, content: bytes) -> None:
        raise PermissionError(errno.EACCES, "Kopia otwarta w Excelu")

    with _unchanged(folders):
        assert folders.replace(before, FaultyDisk(create=locked)) is Refusal.COPY_EXISTS


def test_kopia_zapisana_przez_kogos_innego_po_sprawdzeniu_nazwy_zostaje(folders: Folders, before: Before) -> None:
    def overtaken(path: Path, content: bytes) -> None:
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"Kopia innego zapisu")
        LOCAL_DISK.create(path, content)

    outcome = folders.replace(before, FaultyDisk(create=overtaken))

    assert outcome is Refusal.COPY_EXISTS
    assert folders.state() == (ORIGINAL, [folders.register.name], {NAMES[before]: b"Kopia innego zapisu"})


def test_folder_kopii_ktorego_nie_da_sie_przeszukac_to_kopia_nieudana(folders: Folders, before: Before) -> None:
    def unsearchable(path: Path) -> bool:
        raise PermissionError(errno.EACCES, "folder Kopii bez dostępu")

    with _unchanged(folders):
        assert folders.replace(before, FaultyDisk(exists=unsearchable)) is Refusal.COPY_FAILED


def test_niepelna_kopia_nie_zostaje(folders: Folders, before: Before) -> None:
    with _unchanged(folders):
        assert folders.replace(before, FaultyDisk(create=partial_copy)) is Refusal.COPY_FAILED


def test_plik_w_miejscu_folderu_kopii_to_kopia_nieudana(folders: Folders, before: Before) -> None:
    folders.copies.write_bytes(b"plik zamiast folderu")

    with _unchanged(folders):
        assert folders.replace(before) is Refusal.COPY_FAILED


@pytest.mark.parametrize("failure", [RuntimeError("błąd w kodzie"), KeyboardInterrupt()], ids=["wyjatek", "przerwanie"])
def test_wyjatek_po_kopii_zostawia_intermax_i_kopie_jak_byly(
    folders: Folders, before: Before, failure: BaseException
) -> None:
    def broken(source: Path, target: Path) -> None:
        raise failure

    with _unchanged(folders), pytest.raises(type(failure)):
        folders.replace(before, FaultyDisk(replace=broken))


def test_kopia_ktorej_nie_da_sie_usunac_nie_zaslania_faktu(folders: Folders, before: Before) -> None:
    replace, _ = failing_replace(denied)

    def stuck(path: Path) -> None:
        raise PermissionError(errno.EACCES, "antywirus trzyma Kopię")

    outcome = folders.replace(before, FaultyDisk(replace=replace, remove=stuck))

    assert outcome is Refusal.ONEDRIVE_HOLDS
    assert folders.state() == (ORIGINAL, [folders.register.name], {NAMES[before]: ORIGINAL})


def test_kopia_ma_chwile_z_zegara_procesu_w_nazwie(folders: Folders, before: Before) -> None:
    later = NOW + timedelta(hours=1)

    outcome = replace_register(
        folders.register,
        ORIGINAL,
        NEW,
        lambda _written: None,
        before=before,
        copies=folders.copies,
        now=lambda: later,
        waiting=Waiting(folders.clock, folders.clock.pause),
    )

    assert isinstance(outcome, Replaced)
    assert outcome.copy.path.name == NAMES[before].replace("14-05-07", "15-05-07")
