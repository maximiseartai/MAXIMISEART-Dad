from __future__ import annotations

import pytest

from rozliczenia.worker_list import WorkerEntry, WorkerList, WorkerListProblem
from rozliczenia.worker_reports import Login, SenderAddress

JAN = "jan.testowy@przyklad.invalid"
EWA = "ewa.przykladowa@przyklad.invalid"


@pytest.mark.parametrize(
    ("entry", "problem"),
    [
        pytest.param(WorkerEntry(["jan", "  "], "Jan"), WorkerListProblem(0, "loginy", 1, "empty_login"), id="pusty-login"),
        pytest.param(WorkerEntry(["jan", " JAN "], "Jan"), WorkerListProblem(0, "loginy", 1, "repeated_login"), id="login-dwa-razy"),
        pytest.param(
            WorkerEntry(["jan"], "Jan", [JAN, JAN.upper()]), WorkerListProblem(0, "adresy", 1, "repeated_address"), id="adres-dwa-razy"
        ),
    ],
)
def test_pusty_login_albo_login_lub_adres_powtorzony_u_tego_samego_wykonawcy_lamie_regule(
    entry: WorkerEntry, problem: WorkerListProblem
) -> None:
    assert WorkerList.of([entry]) == problem


def test_lista_ma_wykonawcow_w_kolejnosci_wpisow_z_nazwa_bez_spacji_na_brzegach() -> None:
    listed = WorkerList.of([WorkerEntry(["jan"], "  Jan Testowy "), WorkerEntry(["ewa"], "Ewa Przykładowa")])

    assert isinstance(listed, WorkerList), listed
    assert [worker.name for worker in listed.workers] == ["Jan Testowy", "Ewa Przykładowa"]


def test_adresy_nieaktywnego_wykonawcy_wskazuja_jego_login_a_kazdy_login_prowadzi_do_pierwszego() -> None:
    listed = WorkerList.of(
        [WorkerEntry(["jan", "jan.drugi"], "Jan Testowy", [JAN]), WorkerEntry(["ewa"], "Ewa Przykładowa", [EWA], active=False)]
    )

    assert isinstance(listed, WorkerList), listed
    addresses = listed.addresses()
    assert dict(addresses.logins) == {SenderAddress(JAN): Login("jan"), SenderAddress(EWA): Login("ewa")}
    assert [addresses.worker(Login(login)) for login in ("jan", "jan.drugi", "ewa")] == [Login("jan"), Login("jan"), Login("ewa")]
