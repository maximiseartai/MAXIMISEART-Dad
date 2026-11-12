"""Próba Przypomnień o raporcie przed Wydaniem (#1353, ADR 0030): narzędzie Maksa liczy przypomnienia, które poszłyby
teraz, i wysyła jedno tylko na adres z polecenia.

Narzędzie czyta INTERMAX z dysku testu i rozmawia prawdziwym ``imaplib`` i ``smtplib`` portu z lokalnymi ``AtrapaImap``
i ``AtrapaSmtp`` (``tools/lib/atrapy/skrzynka_raportow.py``), bez sieci i bez Gmaila. Test czyta to, co widzi Maks:
jedną linię na stdout i kod wyjścia, oraz mail, który przyjął serwer SMTP. Maile, adresy i numery są syntetyczne.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import email
from email.message import EmailMessage
import email.policy
import imaplib
from pathlib import Path
import smtplib

import pytest
import proba_przypomnien

from rozliczenia import tool_files
from rozliczenia.tool_files import REMINDERS_FOOTER, REMINDERS_ROLLOUT
from rozliczenia.worker_addresses import WORKER_ADDRESSES_FILE
from rozliczenia.worker_report_inbox import INBOX_ACCESS_FILE

from atrapy.intermax import NUMBER, Intermax, Order
from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail, AtrapaSmtp

SKRZYNKA = "raporty.taty@przyklad.invalid"
HASLO = "abcdefghijklmnop"
MAKS = "maks.probny@przyklad.invalid"
JAN = "jan.testowy@przyklad.invalid"
ANNA = "anna.probna@przyklad.invalid"
STOPKA = "Pozdrawiam\nTata Testowy\n"
# Środa 11.11.2026 8:30, pora poranna: przypomnienia za 9.11 i 10.11 już się należą (ADR 0030).
RANO = datetime(2026, 11, 11, 8, 30)
WRITES = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"}
# Wszystko o Wykonawcach i zleceniach, czego wynik próby nie może pokazać.
TRESCI = [SKRZYNKA, HASLO, JAN, ANNA, "jan.testowy", "anna.probna", "bartek.obcy", "Jan Testowy", "Anna", "4000000"]


def _zlecenie(dzien: int, godzina: int, wykonawca: str, numer: int) -> Order:
    return Order(datetime(2026, 11, dzien, godzina), wykonawca, numer, cells=((NUMBER, numer),))


# Uporządkowane zlecenia: Jana z 9.11 i 10.11, Anny z 9.11 (za który przysłała Raport) i z 10.11, a Bartka, którego nie
# ma na liście adresów, z 9.11. Należą się więc trzy przypomnienia (Jan 9.11, Jan 10.11, Anna 10.11) dwóm Wykonawcom
# za dwa dni.
INTERMAX = Intermax(
    ordered=(
        _zlecenie(9, 9, "jan.testowy", 40000001),
        _zlecenie(9, 10, "jan.testowy", 40000002),
        _zlecenie(9, 11, "anna.probna", 40000003),
        _zlecenie(9, 12, "bartek.obcy", 40000004),
        _zlecenie(10, 9, "jan.testowy", 40000005),
        _zlecenie(10, 11, "anna.probna", 40000006),
    ),
    raw=(),
)


def _raport_anny() -> AtrapaMail:
    message = EmailMessage(policy=email.policy.SMTP)
    message["From"] = f"Anna Probna <{ANNA}>"
    message["To"] = SKRZYNKA
    message["Subject"] = "Raport 09.11.2026"
    message["Message-ID"] = "<1@przyklad.invalid>"
    message.set_content("40000003 tak montaż")
    return AtrapaMail(1, datetime(2026, 11, 9, 19, 0).astimezone(), message.as_bytes())


@dataclass(frozen=True)
class Klon:
    """Folder ``config`` klonu narzędzia z plikami Maksa i taty, INTERMAX taty i jego folder okresów."""

    config: Path
    intermax: Path
    okresy: Path


def _klon(tmp_path: Path) -> Klon:
    config = tmp_path / "config"
    config.mkdir()
    intermax = tmp_path / "OneDrive" / "ZLECENIA INTERMAX.xlsx"
    intermax.parent.mkdir()
    INTERMAX.write(intermax)
    okresy = tmp_path / "Okresy"
    okresy.mkdir()
    (config / INBOX_ACCESS_FILE).write_text(f"{SKRZYNKA}\nabcd efgh ijkl mnop\n", encoding="utf-8")
    (config / tool_files.WORKER_CONFIG.name).write_text(
        "schema_version: 1\nworkers:\n  jan.testowy: Jan Testowy\n  anna.probna: Anna Probna\n  bartek.obcy: Bartek Obcy\n",
        encoding="utf-8",
    )
    (config / WORKER_ADDRESSES_FILE).write_text(
        f"schema_version: 1\nwykonawcy:\n  jan.testowy: [{JAN}]\n  anna.probna: [{ANNA}]\n", encoding="utf-8"
    )
    (config / REMINDERS_ROLLOUT).write_text("2026-11-09\n", encoding="utf-8")
    (config / REMINDERS_FOOTER).write_text(STOPKA, encoding="utf-8")
    (config / tool_files.SETTINGS.name).write_text(
        f"schema_version: 1\nrejestr_zlecen: '{intermax}'\nfolder_okresow: '{okresy}'\n", encoding="utf-8"
    )
    return Klon(config, intermax, okresy)


@dataclass(frozen=True)
class Gmail:
    """Usterki atrapy Gmaila: hasło skrzynki IMAP i serwera SMTP, zerwane powitanie i odmowa adresatów SMTP."""

    haslo_imap: str = HASLO
    haslo_smtp: str = HASLO
    imap_zerwany: bool = False
    smtp_zerwany: bool = False
    smtp_odmawia: bool = False


GMAIL = Gmail()


@contextmanager
def _gmail(gmail: Gmail = GMAIL) -> Iterator[tuple[AtrapaImap, AtrapaSmtp]]:
    """Skrzynka raportów z Raportem Anny za 9.11 i serwer SMTP; SMTP sprawdza hasło swojej osobnej skrzynki."""

    with (
        AtrapaImap(
            address=SKRZYNKA,
            password=gmail.haslo_imap,
            mails=[_raport_anny()],
            cut="greeting" if gmail.imap_zerwany else None,
        ) as imap,
        AtrapaImap(address=SKRZYNKA, password=gmail.haslo_smtp) as wysylka,
        AtrapaSmtp(
            wysylka,
            cut="greeting" if gmail.smtp_zerwany else None,
            refuse="recipients" if gmail.smtp_odmawia else None,
        ) as serwer,
    ):
        yield imap, serwer


def _proba(
    capsys: pytest.CaptureFixture[str],
    klon: Klon,
    imap: AtrapaImap,
    serwer: AtrapaSmtp,
    *,
    teraz: datetime = RANO,
    do: str = MAKS,
) -> tuple[int, str]:
    code = proba_przypomnien.main(
        ["--config", str(klon.config), "--do", do],
        connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port),
        smtp=lambda: smtplib.SMTP("127.0.0.1", serwer.port, timeout=10),
        now=lambda: teraz.astimezone(),
    )
    out, err = capsys.readouterr()
    assert not err
    assert out.isascii()
    for tresc in [*TRESCI, MAKS]:
        assert tresc not in out, tresc
    [line] = out.splitlines()
    return code, line


def _mail(serwer: AtrapaSmtp) -> tuple[EmailMessage, tuple[str, ...], bytes]:
    [(raw, recipients)] = serwer.received
    message = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(message, EmailMessage)
    return message, recipients, raw


def test_proba_liczy_przypomnienia_i_wysyla_jedno_tylko_na_podany_adres_z_trescia_i_stopka(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Kryterium #1353 (US 57–58): jedna linia z liczbą przypomnień, Wykonawców i dni, które poszłyby teraz, i z
    wynikiem wysyłki; jeden mail z tematem, treścią i stopką prawdziwego przypomnienia idzie tylko na adres z
    polecenia, a INTERMAX i skrzynka zostają bez zmian."""

    klon = _klon(tmp_path)
    before = klon.intermax.read_bytes()
    with _gmail() as (imap, serwer):
        code, line = _proba(capsys, klon, imap, serwer)

    assert (code, line) == (
        0,
        "PROBA PRZYPOMNIEN OK | pora=poranna | przypomnienia=3 | wykonawcy=2 | dni=2 | wyslano 1 na podany adres",
    )
    message, recipients, raw = _mail(serwer)
    assert recipients == (MAKS,)
    assert (message["To"], message["Cc"], message["Bcc"]) == (MAKS, None, None)
    assert message["Subject"] == "Przypomnienie: raport za dzień 09.11.2026"
    body = message.get_body()
    assert body is not None
    text = body.get_content().replace("\r\n", "\n")
    assert text.startswith("Poproszę o wysłanie raportu za dzień 09.11.2026.\n")
    assert text.endswith("12345679 nie brak klienta\n\nPozdrawiam\nTata Testowy\n")
    for wykonawca in (JAN, ANNA, "jan.testowy", "anna.probna"):
        assert wykonawca.encode() not in raw, wykonawca
    assert klon.intermax.read_bytes() == before
    assert not WRITES & {command.split(" ")[0] for command in imap.commands}


def test_proba_bez_naleznych_przypomnien_wysyla_przypomnienie_za_wczoraj_na_podany_adres(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """W nocy przypomnienia nie idą (ADR 0030), więc próba liczy zero, a SMTP, treść i stopkę sprawdza przypomnieniem
    za wczoraj, dalej tylko na adres z polecenia."""

    klon = _klon(tmp_path)
    with _gmail() as (imap, serwer):
        code, line = _proba(capsys, klon, imap, serwer, teraz=datetime(2026, 11, 11, 23, 0))

    assert (code, line) == (
        0,
        "PROBA PRZYPOMNIEN OK | pora=noc | przypomnienia=0 | wykonawcy=0 | dni=0 | wyslano 1 na podany adres",
    )
    message, recipients, _ = _mail(serwer)
    assert (recipients, message["To"], message["Subject"]) == ((MAKS,), MAKS, "Przypomnienie: raport za dzień 10.11.2026")


def test_proba_odmawia_adresu_wykonawcy_bez_wysylki(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Adres z polecenia, który jest na liście adresów Wykonawców, to pomyłka Maksa: próba nic nie wysyła."""

    klon = _klon(tmp_path)
    with _gmail() as (imap, serwer):
        code = proba_przypomnien.main(
            ["--config", str(klon.config), "--do", f"Jan <{JAN.upper()}>"],
            connect=lambda: imaplib.IMAP4("127.0.0.1", imap.port),
            smtp=lambda: smtplib.SMTP("127.0.0.1", serwer.port, timeout=10),
            now=lambda: RANO.astimezone(),
        )
    out, _ = capsys.readouterr()

    assert (code, out) == (
        1,
        "PROBA PRZYPOMNIEN FAIL | pora=poranna | przypomnienia=3 | wykonawcy=2 | dni=2"
        " | podany adres jest na liscie adresow Wykonawcow, mail nie poszedl\n",
    )
    assert (serwer.received, serwer.commands) == ([], [])


def test_proba_bez_stopki_ma_wlasna_linie_i_nie_wysyla(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    klon = _klon(tmp_path)
    (klon.config / REMINDERS_FOOTER).unlink()
    with _gmail() as (imap, serwer):
        code, line = _proba(capsys, klon, imap, serwer)

    assert (code, line) == (
        1,
        "PROBA PRZYPOMNIEN FAIL | pora=poranna | przypomnienia=3 | wykonawcy=2 | dni=2"
        f" | brak stopki config/{REMINDERS_FOOTER}, mail nie poszedl",
    )
    assert serwer.received == []


@pytest.mark.parametrize(
    ("gmail", "powod"),
    [
        (Gmail(haslo_smtp="inne-haslo"), "Gmail odrzucil haslo aplikacji przy wysylce"),
        (Gmail(smtp_zerwany=True), "skrzynka niedostepna przy wysylce: SMTPServerDisconnected"),
        (Gmail(smtp_odmawia=True), "Gmail odmowil wysylki: SMTPRecipientsRefused"),
    ],
    ids=["haslo", "siec", "odmowa"],
)
def test_porazka_wysylki_ma_wlasna_linie_z_liczbami(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], gmail: Gmail, powod: str
) -> None:
    klon = _klon(tmp_path)
    with _gmail(gmail) as (imap, serwer):
        code, line = _proba(capsys, klon, imap, serwer)

    assert (code, line) == (
        1,
        f"PROBA PRZYPOMNIEN FAIL | pora=poranna | przypomnienia=3 | wykonawcy=2 | dni=2 | {powod}",
    )
    assert serwer.received == []


def _bez_pliku(nazwa: str) -> Callable[[Klon], None]:
    return lambda klon: (klon.config / nazwa).unlink()


@pytest.mark.parametrize(
    ("zepsuj", "powod"),
    [
        (_bez_pliku(REMINDERS_ROLLOUT), f"brak dnia wdrozenia przypomnien w config/{REMINDERS_ROLLOUT}"),
        (_bez_pliku(tool_files.SETTINGS.name), "brak INTERMAX albo folderu okresow w Ustawieniach taty"),
        (_bez_pliku(INBOX_ACCESS_FILE), f"brak albo zly plik dostepu config/{INBOX_ACCESS_FILE}"),
        (_bez_pliku(WORKER_ADDRESSES_FILE), "brak albo zly plik adresow Wykonawcow albo Konfiguracja wykonawcow"),
        (lambda klon: klon.okresy.rmdir(), "nieczytelny folder okresow"),
        (lambda klon: klon.intermax.unlink(), "nieczytelny INTERMAX: WorkbookError"),
    ],
    ids=["wdrozenie", "ustawienia", "dostep", "adresy", "okresy", "intermax"],
)
def test_porazka_odczytu_ma_wlasna_linie_bez_wysylki(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], zepsuj: Callable[[Klon], None], powod: str
) -> None:
    klon = _klon(tmp_path)
    zepsuj(klon)
    with _gmail() as (imap, serwer):
        code, line = _proba(capsys, klon, imap, serwer)

    assert (code, line) == (1, f"PROBA PRZYPOMNIEN FAIL | {powod}")
    assert serwer.received == []


@pytest.mark.parametrize(
    ("gmail", "powod"),
    [
        (Gmail(haslo_imap="inne-haslo"), "Gmail odrzucil haslo aplikacji przy odczycie skrzynki"),
        (Gmail(imap_zerwany=True), "skrzynka niedostepna przy odczycie skrzynki: IMAP4.abort"),
    ],
    ids=["haslo", "siec"],
)
def test_porazka_odczytu_skrzynki_ma_wlasna_linie_bez_wysylki(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], gmail: Gmail, powod: str
) -> None:
    klon = _klon(tmp_path)
    with _gmail(gmail) as (imap, serwer):
        code, line = _proba(capsys, klon, imap, serwer)

    assert (code, line) == (1, f"PROBA PRZYPOMNIEN FAIL | {powod}")
    assert serwer.received == []
