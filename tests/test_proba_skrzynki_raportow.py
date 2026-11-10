"""Próba IMAP (#1234): narzędzie Maksa sprawdza port Skrzynki raportów na skrzynce taty tylko do odczytu.

Narzędzie rozmawia prawdziwym ``imaplib`` portu z lokalną ``AtrapaImap`` (``tools/lib/atrapy/skrzynka_raportow.py``),
bez sieci i bez Gmaila. Test czyta to, co widzi Maks: linie na stdout i kod wyjścia, oraz polecenia, które dostał
serwer. Maile, adresy i numery są syntetyczne.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import email.policy
import imaplib
from pathlib import Path
from typing import Any, Literal

import pytest
import proba_skrzynki_raportow

from rozliczenia import tool_files
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE
from rozliczenia.worker_report_inbox import FETCH_BATCH, INBOX_ACCESS_FILE

from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail

SKRZYNKA = "raporty.taty@przyklad.invalid"
HASLO = "abcdefghijklmnop"
WYKONAWCA = "jan.testowy@przyklad.invalid"
OBCY = "obcy.nadawca@przyklad.invalid"
TATA = timezone(timedelta(hours=1))
WRITES = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"}
# Wszystko, co mail niesie, a czego wynik próby nie może pokazać.
TRESCI = [
    SKRZYNKA,
    HASLO,
    WYKONAWCA,
    OBCY,
    "jan.testowy",
    "Raport 08.11.2026",
    "Raport 09.11.2026",
    "Raport bez daty",
    "Re: Raport",
    "Faktura",
    "40000001",
    "40000003",
    "40000004",
    "gniazdka",
    "odmówił",
    "zleceń",
]


def mail(
    uid: int,
    *,
    temat: str,
    tresc: str = "40000001 tak wymiana gniazdka, usunięto awarię",
    od: str | None = f"Jan Testowy <{WYKONAWCA}>",
    charset: str = "utf-8",
    flagi: tuple[str, ...] = (),
    w_odebranych: bool = True,
) -> AtrapaMail:
    message = EmailMessage(policy=email.policy.SMTP)
    if od is not None:
        message["From"] = od
    message["To"] = SKRZYNKA
    message["Subject"] = temat
    message["Message-ID"] = f"<{uid}@przyklad.invalid>"
    message.set_content(tresc, charset=charset)
    return AtrapaMail(uid, datetime(2026, 11, 9, 18, 5, tzinfo=TATA), message.as_bytes(), flagi, w_odebranych)


def skrzynka_z_raportami() -> list[AtrapaMail]:
    """Siedem maili z dni okna: dwa Raporty Wykonawcy z Wpisem (jeden tylko w folderze wszystkich maili) i jeden bez
    Wpisu, Raport obcego nadawcy, odpowiedź na Raport, mail ze słowem ``raport`` bez nadawcy i faktura bez tego
    słowa."""

    return [
        mail(1, temat="Raport 08.11.2026", flagi=("\\Seen",)),
        mail(2, temat="Raport 09.11.2026", tresc="40000003 tak", od=f"<{OBCY}>"),
        mail(3, temat="Re: Raport 08.11.2026", tresc="40000001 tak"),
        mail(4, temat="Faktura", tresc="do zapłaty", flagi=("\\Seen", "$Etykieta")),
        mail(5, temat="Raport 09.11.2026", tresc="40000004 nie klient odmówił", charset="iso-8859-2", w_odebranych=False),
        mail(6, temat="Raport 09.11.2026", od=None),
        mail(7, temat="Raport 09.11.2026", tresc="dzień bez zleceń"),
    ]


def config(folder: Path, *, adresy: bool = True) -> Path:
    (folder / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\nabcd efgh ijkl mnop\n", encoding="utf-8")
    (folder / tool_files.WORKER_CONFIG.name).write_text(
        "schema_version: 1\nworkers:\n  jan.testowy: Jan Testowy\n", encoding="utf-8"
    )
    if adresy:
        (folder / WORKER_ADDRESSES_FILE).write_text(
            f"schema_version: 1\nwykonawcy:\n  jan.testowy: [{WYKONAWCA}]\n", encoding="utf-8"
        )
    return folder


def lokalnie(port: int) -> Callable[[], imaplib.IMAP4]:
    return lambda: imaplib.IMAP4("127.0.0.1", port)


def proba(capsys: pytest.CaptureFixture[str], folder: Path, connect: Callable[[], imaplib.IMAP4]) -> tuple[int, list[str]]:
    code = proba_skrzynki_raportow.main(["--config", str(folder), "--od", "2026-11-01"], connect=connect)
    out, err = capsys.readouterr()
    assert not err
    assert out.isascii()
    for tresc in TRESCI:
        assert tresc not in out
    return code, out.splitlines()


def test_proba_na_skrzynce_z_raportami_drukuje_same_liczby_i_ostatnia_linie_ok_bez_zmiany_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami()) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines == [
        "SKRZYNKA | folder_wszystkich=6 | odebrane=5 | poza_odebranymi=1",
        "MAILE | przeczytane=5 | pominiete=1 | raporty=4 | wpisy=2 | polskie_znaki=3 | zepsute_znaki=0",
        "PROBLEMY | UnknownNumber=2 | UnknownSender=1",
        "FLAGI | sprawdzone=7 | zmienione=0",
        "PROBA IMAP OK | maile=5 | flagi bez zmian",
    ]
    assert code == 0
    names = {command.split(" ")[0] if not command.startswith("UID ") else command.split(" ")[1] for command in atrapa.commands}
    assert not WRITES & names
    assert 'EXAMINE "INBOX"' in atrapa.commands
    assert any(command.startswith("UID FETCH") and command.endswith("(UID FLAGS)") for command in atrapa.commands)
    assert atrapa.flags == {mail.uid: set(mail.flags) for mail in skrzynka_z_raportami()}


def test_proba_zglasza_flage_zmieniona_miedzy_odczytami(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami(), marks_seen=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[-2:] == [
        "FLAGI | sprawdzone=7 | zmienione=5",
        "PROBA IMAP FAIL | flagi zmienione w 5 mailach",
    ]
    assert code == 1


def test_proba_liczy_mail_znikniety_przed_drugim_odczytem_jako_zmieniony(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    maile = [mail(1, temat="Raport 08.11.2026"), mail(4, temat="Faktura", tresc="do zapłaty")]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile, deletes_read=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert atrapa.deleted == {1}
    assert lines[-2:] == [
        "FLAGI | sprawdzone=2 | zmienione=1",
        "PROBA IMAP FAIL | flagi zmienione w 1 mailach",
    ]
    assert code == 1


@pytest.mark.parametrize("odpowiedz", ["without_fetch", "unsolicited"])
def test_proba_nie_przechodzi_gdy_serwer_nie_oddal_samych_flag_kazdego_wyszukanego_maila(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], odpowiedz: Literal["without_fetch", "unsolicited"]
) -> None:
    with AtrapaImap(
        address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami(), marks_seen=True, flags_reply=odpowiedz
    ) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert (code, lines) == (1, ["PROBA IMAP FAIL | skrzynka niedostepna przy pierwszym odczycie flag: UnexpectedReply"])


class WyszukiwanieZPowtorzonymUid(imaplib.IMAP4):
    """Serwer, który w wyniku ``UID SEARCH`` podaje pierwszy UID dwa razy: flagi ma wtedy mniej maili, niż wyszukano."""

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        status, data = super().uid(command, *args)
        if command == "SEARCH" and data and isinstance(data[0], bytes) and data[0]:
            data = [data[0] + b" " + data[0].split()[0]]
        return status, data


def test_proba_nie_przechodzi_gdy_flagi_ma_mniej_maili_niz_wyszukano(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lambda: WyszukiwanieZPowtorzonymUid("127.0.0.1", atrapa.port))

    assert lines[-2:] == [
        "FLAGI | sprawdzone=1 | zmienione=0",
        "PROBA IMAP FAIL | flagi nie kazdego wyszukanego maila w 2 z 2 odczytow",
    ]
    assert code == 1


class _PierwszaSesjaBezUid1(imaplib.IMAP4):
    """Pierwsza sesja próby, która nie widzi maila UID 1 w ``UID SEARCH``, bo przyszedł tuż po niej."""

    def uid(self, command: str, *args: str) -> tuple[str, list[Any]]:
        status, data = super().uid(command, *args)
        if command == "SEARCH" and data and isinstance(data[0], bytes):
            data = [b" ".join(uid for uid in data[0].split() if uid != b"1")]
        return status, data


def test_proba_nie_przechodzi_gdy_raport_przyszedl_po_pierwszym_odczycie_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Raport, którego pierwszy odczyt flag nie widział, port przeczytał i oznaczył: jego flag nikt nie porównał, więc
    próba nie przechodzi, zamiast dać OK z flagami bez zmian."""

    sesje: list[imaplib.IMAP4] = []

    def connect(port: int) -> imaplib.IMAP4:
        sesje.append(_PierwszaSesjaBezUid1("127.0.0.1", port) if not sesje else imaplib.IMAP4("127.0.0.1", port))
        return sesje[-1]

    maile = [mail(1, temat="Raport 08.11.2026")]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile, marks_seen=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lambda: connect(atrapa.port))

    assert atrapa.flags == {1: {"\\Seen"}}
    assert lines[-2:] == [
        "FLAGI | sprawdzone=0 | zmienione=0",
        "PROBA IMAP FAIL | 1 maili przyszlo w trakcie proby bez pierwszego odczytu flag, uruchom ponownie",
    ]
    assert code == 1


def test_proba_porownuje_flagi_maili_z_kazdej_paczki_odczytu_flag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Flagi czyta się w paczkach po ``FETCH_BATCH`` maili: Raport w drugiej paczce, który port oznaczył jako
    przeczytany, to zmiana flag, a każdy mail ma flagi z obu odczytów."""

    ostatni = FETCH_BATCH + 50
    maile = [*(mail(uid, temat="Faktura", tresc="do zapłaty") for uid in range(1, ostatni)), mail(ostatni, temat="Raport 08.11.2026")]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile, marks_seen=True) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[-2:] == [f"FLAGI | sprawdzone={ostatni} | zmienione=1", "PROBA IMAP FAIL | flagi zmienione w 1 mailach"]
    assert code == 1


@pytest.mark.parametrize(
    ("maile", "liczby"),
    [
        pytest.param(
            [mail(4, temat="Faktura")],
            "maile_z_raport=0, nieznani_nadawcy=0, nierozpoznane_tematy=0, raporty_bez_wpisow=0, wpisy_bez_tak_nie=0",
            id="bez-maila-ze-slowem-raport",
        ),
        pytest.param(
            [mail(3, temat="Raport bez daty")],
            "maile_z_raport=1, nieznani_nadawcy=0, nierozpoznane_tematy=1, raporty_bez_wpisow=0, wpisy_bez_tak_nie=0",
            id="temat-bez-dnia-od-wykonawcy",
        ),
        pytest.param(
            [mail(2, temat="Raport 09.11.2026", tresc="40000003 tak", od=f"<{OBCY}>")],
            "maile_z_raport=1, nieznani_nadawcy=1, nierozpoznane_tematy=0, raporty_bez_wpisow=0, wpisy_bez_tak_nie=0",
            id="adres-spoza-pliku-adresow",
        ),
        pytest.param(
            [mail(7, temat="Raport 09.11.2026", tresc="dzień bez zleceń")],
            "maile_z_raport=1, nieznani_nadawcy=0, nierozpoznane_tematy=0, raporty_bez_wpisow=1, wpisy_bez_tak_nie=0",
            id="raport-wykonawcy-bez-wpisu",
        ),
        pytest.param(
            [mail(1, temat="Raport 08.11.2026", tresc="40000001 t wymiana")],
            "maile_z_raport=1, nieznani_nadawcy=0, nierozpoznane_tematy=0, raporty_bez_wpisow=0, wpisy_bez_tak_nie=1",
            id="wpis-z-litera-t-zamiast-tak",
        ),
    ],
)
def test_proba_bez_rozpoznanego_raportu_wykonawcy_nie_przechodzi_i_mowi_dlaczego_liczbami(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], maile: list[AtrapaMail], liczby: str
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=maile) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[-1] == f"PROBA IMAP FAIL | brak rozpoznanego Raportu wykonawcy od 2026-11-01 ({liczby})"
    assert code == 1


def test_proba_z_jednym_raportem_wykonawcy_z_wpisem_przechodzi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(1, temat="Raport 08.11.2026")]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert (code, lines[-1]) == (0, "PROBA IMAP OK | maile=1 | flagi bez zmian")


@pytest.mark.parametrize(
    ("tresc", "zapisany", "podany", "znak"),
    [
        pytest.param("usunięto awarię", "utf-8", "iso-8859-2", "Ä", id="utf-8-jako-iso-8859-2-Ä"),
        pytest.param("próba", "utf-8", "iso-8859-2", "Ă", id="utf-8-jako-iso-8859-2-Ă"),
        pytest.param("wyświetlacz", "utf-8", "cp1250", "Ĺ", id="utf-8-jako-cp1250-Ĺ"),
        pytest.param("próba", "utf-8", "iso-8859-1", "Ã", id="utf-8-jako-latin-1-Ã"),
        pytest.param("wyświetlacz", "utf-8", "iso-8859-1", "Å", id="utf-8-jako-latin-1-Å"),
        pytest.param("wymiana złącza", "iso-8859-2", "utf-8", "\ufffd", id="iso-8859-2-jako-utf-8-znak-zastepczy"),
    ],
)
def test_proba_zglasza_polskie_litery_zepsute_przez_zly_zestaw_znakow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], tresc: str, zapisany: str, podany: str, znak: str
) -> None:
    # Nadawca zapisał treść w jednym zestawie znaków, a w nagłówku podał inny: polska litera to wtedy ``znak``.
    assert tresc.encode(zapisany).decode(podany, errors="replace").count(znak) >= 1
    zapisany_mail = mail(1, temat="Raport 08.11.2026", tresc=f"40000001 tak {tresc}", charset=zapisany)
    raw = zapisany_mail.raw.replace(f'charset="{zapisany}"'.encode(), f'charset="{podany}"'.encode())
    assert raw != zapisany_mail.raw
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[AtrapaMail(1, zapisany_mail.arrived, raw)]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[1].endswith("| zepsute_znaki=1")
    assert lines[-1] == "PROBA IMAP FAIL | zepsute polskie znaki w 1 mailach"
    assert code == 1


def test_proba_z_odrzuconym_haslem_albo_bez_sieci_konczy_sie_linia_fail_z_powodem_bez_hasla(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = config(tmp_path)
    with AtrapaImap(address=SKRZYNKA, password="inne-haslo", mails=skrzynka_z_raportami()) as atrapa:
        odrzucone = proba(capsys, folder, lokalnie(atrapa.port))

    def bez_sieci_do_gmaila() -> imaplib.IMAP4:
        raise ConnectionRefusedError(f"brak sieci przy {SKRZYNKA}")

    bez_sieci = proba(capsys, folder, bez_sieci_do_gmaila)

    assert odrzucone == (1, ["PROBA IMAP FAIL | Gmail odrzucil haslo aplikacji przy pierwszym odczycie flag"])
    assert bez_sieci == (1, ["PROBA IMAP FAIL | skrzynka niedostepna przy pierwszym odczycie flag: ConnectionRefusedError"])
    assert "LOGIN" in atrapa.commands
    assert "abcd efgh ijkl mnop" not in "".join(atrapa.commands)


def test_proba_bez_pliku_adresow_nie_laczy_sie_ze_skrzynka(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami()) as atrapa:
        code, lines = proba(capsys, config(tmp_path, adresy=False), lokalnie(atrapa.port))

    assert (code, lines) == (1, ["PROBA IMAP FAIL | plik adresow Wykonawcow: missing"])
    assert atrapa.commands == []
