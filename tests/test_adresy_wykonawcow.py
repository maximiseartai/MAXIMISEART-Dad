"""Plik adresów Wykonawców (ADR 0028): każda reguła pliku daje swój problem, a login musi być w Konfiguracji wykonawców.

Moduł nie zna Komunikatów; to, co zobaczy tata albo Maks, sprawdzą testy procesu Wpisania raportów.
"""

from __future__ import annotations

import errno
from pathlib import Path
from typing import get_args

import pytest

from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE, AddressesError, AddressesProblem, UnknownLogin, load
from rozliczenia.worker_reports import Login, SenderAddress

KONFIGURACJA = {"jan.testowy": "Jan Testowy", "ola.syntetyczna": "Ola Syntetyczna"}


def plik(tmp_path: Path, tresc: str | bytes) -> Path:
    path = tmp_path / WORKER_ADDRESSES_FILE
    path.write_bytes(tresc.encode() if isinstance(tresc, str) else tresc)
    return path


def adres(text: str) -> SenderAddress:
    address = SenderAddress.of(text)
    assert address is not None
    return address


def test_plik_adresow_laczy_kazdy_adres_z_loginem_wykonawcy_bez_wielkosci_liter(tmp_path: Path) -> None:
    path = plik(
        tmp_path,
        "schema_version: 1\nwykonawcy:\n"
        "  ' Jan.Testowy ':\n    - Jan.Testowy@Przyklad.invalid\n    - jan.drugi@przyklad.invalid\n"
        "  ola.syntetyczna: [ola@przyklad.invalid]\n",
    )

    assert load(path, workers=KONFIGURACJA).logins == {
        adres("jan.testowy@przyklad.invalid"): Login("jan.testowy"),
        adres("jan.drugi@przyklad.invalid"): Login("jan.testowy"),
        adres("ola@przyklad.invalid"): Login("ola.syntetyczna"),
    }


def test_ten_sam_login_w_innej_wielkosci_liter_laczy_listy_adresow(tmp_path: Path) -> None:
    path = plik(
        tmp_path,
        "schema_version: 1\nwykonawcy:\n  jan.testowy: [jan@przyklad.invalid]\n  JAN.TESTOWY: [jan.drugi@przyklad.invalid]\n",
    )

    assert set(load(path, workers=KONFIGURACJA).logins.values()) == {Login("jan.testowy")}
    assert len(load(path, workers=KONFIGURACJA).logins) == 2


def test_login_spoza_konfiguracji_wykonawcow_daje_nieznany_login(tmp_path: Path) -> None:
    path = plik(tmp_path, "schema_version: 1\nwykonawcy:\n  jan.testowy: [jan@przyklad.invalid]\n  Ktoś.Obcy: [o@x.invalid]\n")

    with pytest.raises(AddressesError) as raised:
        load(path, workers=KONFIGURACJA)

    assert raised.value.problem == UnknownLogin(Login("ktoś.obcy"))


WERSJA = "schema_version: 1\n"
TRESCI: list[tuple[str, str | bytes]] = [
    ("not_utf8", "schema_version: 1\nwykonawcy:\n  jan.testowy: [jań@przyklad.invalid]\n".encode("cp1250")),
    ("not_yaml", WERSJA + "wykonawcy: [jan.testowy: {\n"),
    ("unsupported_version", "schema_version: 2\nwykonawcy:\n  jan.testowy: [jan@przyklad.invalid]\n"),
    ("unsupported_version", "schema_version: '1'\nwykonawcy:\n  jan.testowy: [jan@przyklad.invalid]\n"),
    ("unsupported_version", "schema_version: true\nwykonawcy:\n  jan.testowy: [jan@przyklad.invalid]\n"),
    ("unsupported_version", "- jan.testowy\n"),
    ("unsupported_version", ""),
    ("no_workers", WERSJA),
    ("no_workers", WERSJA + "wykonawcy: {}\n"),
    ("no_workers", WERSJA + "wykonawcy: [jan.testowy]\n"),
    ("not_address", WERSJA + "wykonawcy:\n  jan.testowy: jan@przyklad.invalid\n"),
    ("not_address", WERSJA + "wykonawcy:\n  jan.testowy: []\n"),
    ("not_address", WERSJA + "wykonawcy:\n  jan.testowy:\n"),
    ("not_address", WERSJA + "wykonawcy:\n  jan.testowy: ['Jan Testowy <jan@przyklad.invalid>']\n"),
    ("not_address", WERSJA + "wykonawcy:\n  jan.testowy: [jan.przyklad.invalid]\n"),
    ("not_address", WERSJA + "wykonawcy:\n  jan.testowy: [123]\n"),
    ("not_address", WERSJA + "wykonawcy:\n  jan.testowy: ['jan@przyklad@invalid']\n"),
    ("repeated_address", WERSJA + "wykonawcy:\n  jan.testowy: [jan@przyklad.invalid]\n  ola.syntetyczna: [JAN@przyklad.invalid]\n"),
    ("repeated_address", WERSJA + "wykonawcy:\n  jan.testowy: [jan@przyklad.invalid, jan@przyklad.invalid]\n"),
]


@pytest.mark.parametrize(("problem", "tresc"), TRESCI, ids=[f"{problem}-{n}" for n, (problem, _) in enumerate(TRESCI)])
def test_zla_tresc_pliku_adresow_daje_swoj_problem(tmp_path: Path, problem: str, tresc: str | bytes) -> None:
    with pytest.raises(AddressesError) as raised:
        load(plik(tmp_path, tresc), workers=KONFIGURACJA)

    assert raised.value.problem == problem


@pytest.mark.parametrize(
    "missing",
    [Path(WORKER_ADDRESSES_FILE), Path("plik") / WORKER_ADDRESSES_FILE, Path("folder")],
    ids=["brak-pliku", "plik-zamiast-folderu", "folder-zamiast-pliku"],
)
def test_brak_pliku_adresow(tmp_path: Path, missing: Path) -> None:
    (tmp_path / "plik").write_text("", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    with pytest.raises(AddressesError) as raised:
        load(tmp_path / missing, workers=KONFIGURACJA)

    assert raised.value.problem == "missing"


def test_plik_adresow_bez_dostepu_jest_niedostepny(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = plik(tmp_path, WERSJA + "wykonawcy:\n  jan.testowy: [jan@przyklad.invalid]\n")

    def busy(self: Path, encoding: str) -> str:
        raise PermissionError(errno.EACCES, "Plik jest używany przez inny proces")

    monkeypatch.setattr(Path, "read_text", busy)
    with pytest.raises(AddressesError) as raised:
        load(path, workers=KONFIGURACJA)

    assert raised.value.problem == "inaccessible"


def test_testy_pliku_adresow_obejmuja_kazdy_problem() -> None:
    tested = {problem for problem, _ in TRESCI} | {"missing", "inaccessible"}

    assert tested | {UnknownLogin} == {*get_args(get_args(AddressesProblem)[0]), UnknownLogin}
