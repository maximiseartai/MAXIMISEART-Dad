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

import pytest
import proba_skrzynki_raportow

from rozliczenia import tool_files
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE

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
    Wpisu, Raport obcego nadawcy, mail bez dnia w temacie, mail ze słowem ``raport`` bez nadawcy i faktura bez tego
    słowa."""

    return [
        mail(1, temat="Raport 08.11.2026", flagi=("\\Seen",)),
        mail(2, temat="Raport 09.11.2026", tresc="40000003 tak", od=f"<{OBCY}>"),
        mail(3, temat="Raport bez daty", tresc="40000001 tak"),
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


def test_proba_bez_maili_z_raportem_nie_przechodzi(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[mail(4, temat="Faktura")]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[-1] == "PROBA IMAP FAIL | zaden mail z Raportem od 2026-11-01, podaj wczesniejsze --od"
    assert code == 1


def test_proba_zglasza_polskie_litery_zepsute_przez_zly_zestaw_znakow(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    utf8 = mail(1, temat="Raport 08.11.2026", tresc="40000001 tak usunięto awarię")
    # Nadawca zapisał treść w UTF-8, a w nagłówku podał ISO-8859-2: „ę” to wtedy „Ä™”.
    raw = utf8.raw.replace(b"charset=\"utf-8\"", b"charset=\"iso-8859-2\"")
    assert raw != utf8.raw
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[AtrapaMail(1, utf8.arrived, raw)]) as atrapa:
        code, lines = proba(capsys, config(tmp_path), lokalnie(atrapa.port))

    assert lines[1].endswith("| polskie_znaki=0 | zepsute_znaki=1")
    assert lines[-1] == "PROBA IMAP FAIL | zepsute polskie znaki w 1 mailach"
    assert code == 1


def test_proba_z_odrzuconym_haslem_albo_bez_sieci_konczy_sie_linia_fail_z_powodem_bez_hasla(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = config(tmp_path)
    with AtrapaImap(address=SKRZYNKA, password="inne-haslo", mails=skrzynka_z_raportami()) as atrapa:
        odrzucone = proba(capsys, folder, lokalnie(atrapa.port))
    with AtrapaImap(address=SKRZYNKA, password=HASLO) as zamknieta:
        port = zamknieta.port

    bez_sieci = proba(capsys, folder, lokalnie(port))

    assert odrzucone == (1, ["PROBA IMAP FAIL | Gmail odrzucil haslo aplikacji przy pierwszym odczycie flag"])
    assert bez_sieci == (1, ["PROBA IMAP FAIL | skrzynka niedostepna przy pierwszym odczycie flag: ConnectionRefusedError"])
    assert "LOGIN" in atrapa.commands
    assert "abcd efgh ijkl mnop" not in "".join(atrapa.commands)


def test_proba_bez_pliku_adresow_nie_laczy_sie_ze_skrzynka(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=skrzynka_z_raportami()) as atrapa:
        code, lines = proba(capsys, config(tmp_path, adresy=False), lokalnie(atrapa.port))

    assert (code, lines) == (1, ["PROBA IMAP FAIL | plik adresow Wykonawcow: missing"])
    assert atrapa.commands == []
