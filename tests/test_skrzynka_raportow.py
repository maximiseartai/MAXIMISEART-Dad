"""Skrzynka raportów (ADR 0028): port czyta maile Wykonawców z Gmaila tylko do odczytu.

Port rozmawia prawdziwym ``imaplib`` z lokalną ``AtrapaImap`` (``tools/lib/atrapy/skrzynka_raportow.py``), bez sieci:
test sprawdza polecenia, które dostał serwer, i wynik, który oddał port. Prawdziwego Gmaila sprawdza próba IMAP (#1234).
Maile są syntetyczne, zbudowane w teście bajt po bajcie, żeby było widać każde kodowanie nagłówka i treści.
"""

from __future__ import annotations

import base64
import codecs
from datetime import date, datetime, timedelta, timezone
import hashlib
import imaplib
from pathlib import Path
import quopri
from typing import Literal

import pydantic
import pytest

from rozliczenia.worker_report_inbox import (
    FETCH_BATCH,
    INBOX_ACCESS_FILE,
    ImapInbox,
    InboxOutcome,
    InboxUnreachable,
    Mails,
    PasswordRejected,
    WorkerReportInbox,
    mail_of,
)
from rozliczenia.worker_reports import MailId, ReportMail, SenderAddress

from atrapy.skrzynka_raportow import AtrapaImap, AtrapaMail, FakeInbox

SKRZYNKA = "raporty.taty@przyklad.invalid"
HASLO = "abcdefghijklmnop"
WYKONAWCA = "jan.testowy@przyklad.invalid"
TATA = timezone(timedelta(hours=1))
WRITES = {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "APPEND"}


def surowy(
    *,
    temat: bytes = b"Raport 08.11.2026",
    tresc: str = "40000001 tak wymiana routera",
    od: bytes | None = b"Jan Testowy <jan.testowy@przyklad.invalid>",
    typ: str = "text/plain",
    charset: str = "utf-8",
    kodowanie: str = "quoted-printable",
    message_id: bytes = b"<1@przyklad.invalid>",
) -> bytes:
    """Mail MIME z jedną częścią: treść w ``charset`` zakodowana ``kodowanie`` (quoted-printable albo base64)."""

    encoded = tresc.encode(charset if charset != "x-nieznany" else "utf-8")
    body = quopri.encodestring(encoded) if kodowanie == "quoted-printable" else base64.encodebytes(encoded)
    headers = [
        *([b"From: " + od] if od is not None else []),
        b"To: " + SKRZYNKA.encode(),
        b"Subject: " + temat,
        b"Message-ID: " + message_id,
        b"MIME-Version: 1.0",
        f"Content-Type: {typ}; charset={charset}".encode(),
        f"Content-Transfer-Encoding: {kodowanie}".encode(),
    ]
    return b"\r\n".join(headers) + b"\r\n\r\n" + body.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


def w_skrzynce(uid: int, raw: bytes, przyszedl: datetime = datetime(2026, 11, 8, 18, 5, tzinfo=TATA)) -> AtrapaMail:
    return AtrapaMail(uid, przyszedl, raw)


def dostep(config: Path, tresc: bytes = f"{SKRZYNKA}\nabcd efgh ijkl mnop\n".encode()) -> Path:
    (config / INBOX_ACCESS_FILE).write_bytes(tresc)
    return config


def port(config: Path, atrapa: AtrapaImap) -> ImapInbox:
    return ImapInbox(config, connect=lambda: imaplib.IMAP4("127.0.0.1", atrapa.port))


def polecenia(atrapa: AtrapaImap) -> list[str]:
    """Nazwy poleceń, które dostał serwer (``UID FETCH`` jako jedna nazwa), bez ``CAPABILITY``.

    ``imaplib`` z Pythona 3.14 bierze możliwości serwera z powitania, a 3.11 pyta o nie osobno: to nie decyzja portu.
    """

    names = [" ".join(command.split(" ")[:2 if command.startswith("UID ") else 1]) for command in atrapa.commands]
    return [name for name in names if name != "CAPABILITY"]


def maile(outcome: InboxOutcome) -> tuple[ReportMail, ...]:
    assert isinstance(outcome, Mails), outcome
    return outcome.mails


def test_skrzynka_raportow_otwiera_folder_wszystkich_maili_tylko_do_odczytu_i_pobiera_maile_bez_flagi_przeczytane(
    tmp_path: Path,
) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowy())]) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert [(mail.subject, mail.text) for mail in maile(outcome)] == [("Raport 08.11.2026", "40000001 tak wymiana routera")]
    assert 'EXAMINE "[Gmail]/Wszystkie wiadomo&AVs-ci"' in atrapa.commands
    assert not WRITES & {name.removeprefix("UID ") for name in polecenia(atrapa)}
    fetches = [command for command in atrapa.commands if command.startswith("UID FETCH")]
    assert any("BODY.PEEK[]" in command for command in fetches)
    assert fetches and all("BODY[" not in command.replace("BODY.PEEK[", "") for command in fetches)
    assert polecenia(atrapa)[-1] == "LOGOUT"


def test_skrzynka_bez_folderu_wszystkich_maili_otwiera_odebrane_tylko_do_odczytu(tmp_path: Path) -> None:
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(7, surowy())], all_folder=False) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert len(maile(outcome)) == 1
    assert 'EXAMINE "INBOX"' in atrapa.commands


def test_skrzynka_raportow_oddaje_maile_ze_slowem_raport_w_temacie_od_dnia_bez_maili_samej_skrzynki_i_liczy_maile_bez_nadawcy(
    tmp_path: Path,
) -> None:
    w_dniu = w_skrzynce(1, surowy(message_id=b"<a@x.invalid>"))
    duze_litery = w_skrzynce(
        2, surowy(temat=b"RAPORT 09.11.2026", message_id=b"<b@x.invalid>"), datetime(2026, 11, 9, 7, 0, tzinfo=TATA)
    )
    bez_slowa = w_skrzynce(3, surowy(temat=b"Faktura za listopad", message_id=b"<c@x.invalid>"))
    dwa_dni_wczesniej = w_skrzynce(4, surowy(message_id=b"<d@x.invalid>"), datetime(2026, 11, 6, 23, 30, tzinfo=TATA))
    od_skrzynki = w_skrzynce(5, surowy(od=f"Tata <{SKRZYNKA.upper()}>".encode(), message_id=b"<e@x.invalid>"))
    bez_nadawcy = w_skrzynce(6, surowy(od=None, message_id=b"<f@x.invalid>"))
    mails = [w_dniu, duze_litery, bez_slowa, dwa_dni_wczesniej, od_skrzynki, bez_nadawcy]

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert isinstance(outcome, Mails), outcome
    assert outcome.skipped == 1
    found = outcome.mails

    assert [(mail.subject, mail.sender, mail.arrived) for mail in found] == [
        ("Raport 08.11.2026", SenderAddress.of(WYKONAWCA), datetime(2026, 11, 8, 18, 5, tzinfo=TATA)),
        ("RAPORT 09.11.2026", SenderAddress.of(WYKONAWCA), datetime(2026, 11, 9, 7, 0, tzinfo=TATA)),
    ]
    assert [mail.id for mail in found] == [MailId.of("<a@x.invalid>"), MailId.of("<b@x.invalid>")]
    assert all(len(mail.id.digest) == 16 and set(mail.id.digest) <= set("abcdefghijklmnop") for mail in found)
    assert found[0].arrived.utcoffset() == datetime(2026, 11, 8, 18, 5).astimezone().utcoffset()


def test_skrzynka_szuka_od_dnia_przed_wskazanym_bo_gmail_liczy_dzien_przyjecia_w_swojej_strefie(tmp_path: Path) -> None:
    # 23:30 UTC 7 listopada to 00:30 8 listopada u taty: Gmail zalicza taki mail do 7 listopada.
    po_polnocy_u_taty = w_skrzynce(1, surowy(), datetime(2026, 11, 7, 23, 30, tzinfo=timezone.utc))

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[po_polnocy_u_taty]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [command for command in atrapa.commands if command.startswith("UID SEARCH")] == ["UID SEARCH SINCE 07-Nov-2026"]
    assert [mail.arrived for mail in found] == [datetime(2026, 11, 8, 0, 30, tzinfo=TATA)]


def test_skrzynka_z_wiecej_maili_niz_paczka_pobierania_oddaje_kazdy_mail(tmp_path: Path) -> None:
    count = 2 * FETCH_BATCH + 1
    mails = [w_skrzynce(uid, surowy(message_id=f"<{uid}@x.invalid>".encode())) for uid in range(1, count + 1)]

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [mail.id for mail in found] == [MailId.of(f"<{uid}@x.invalid>") for uid in range(1, count + 1)]
    fetched = [command.split(" ")[2].split(",") for command in atrapa.commands if command.startswith("UID FETCH")]
    assert fetched and max(len(uids) for uids in fetched) <= FETCH_BATCH


TEMAT = "Raport 08.11.2026 żółć"
TRESC = "40000001 tak wymiana złącza, ąęśźń ŻÓŁĆ"


@pytest.mark.parametrize(
    ("temat", "charset", "kodowanie"),
    [
        (b"=?utf-8?q?Raport_08=2E11=2E2026_=C5=BC=C3=B3=C5=82=C4=87?=", "windows-1250", "quoted-printable"),
        (b"=?windows-1250?b?" + base64.b64encode(TEMAT.encode("windows-1250")) + b"?=", "utf-8", "base64"),
        (b"=?windows-1250?q?Raport_08.11.2026_=BF=F3=B3=E6?=", "windows-1250", "base64"),
        (b"=?utf-8?b?" + base64.b64encode(TEMAT.encode()) + b"?=", "utf-8", "quoted-printable"),
        (b"=?utf-8?b?" + base64.b64encode(TEMAT.encode()) + b"?=", "x-nieznany", "quoted-printable"),
    ],
    ids=["temat-q-utf8-tresc-qp-1250", "temat-b-1250-tresc-b64-utf8", "temat-q-1250-tresc-b64-1250", "temat-b-utf8-tresc-qp-utf8", "nieznany-zestaw-znakow-jako-utf8"],
)
def test_skrzynka_raportow_dekoduje_polski_temat_i_tresc_w_kazdym_kodowaniu(
    tmp_path: Path, temat: bytes, charset: str, kodowanie: str
) -> None:
    raw = surowy(temat=temat, tresc=TRESC, charset=charset, kodowanie=kodowanie)

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(1, raw)]) as atrapa:
        found = maile(port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8)))

    assert [(mail.subject, mail.text.strip()) for mail in found] == [(TEMAT, TRESC)]


HTML = (
    "<html><head><style>p { color: red }</style><script>var x = 1;</script></head><body>"
    "<p>40000001 tak wymiana&nbsp;routera</p><div>40000002   nie\nbrak klienta</div>"
    "<table><tr><td>40000003 tak</td></tr></table><ul><li>montaż</li></ul>Pozdrawiam<br>Jan</body></html>"
)


TEMAT_RAPORTU = b"Subject: Raport 08.11.2026\r\n"
ZEPSUTE = {
    "zestaw-znakow-z-bajtem-zerowym": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU
    + b"Content-Type: text/plain; charset=u\x00f-8\r\n\r\n40000002 nie\r\n",
    "nadawca-jako-grupa": b"From: undiscloFrom: sed-;recipient:;\r\n" + TEMAT_RAPORTU + b"\r\nx\r\n",
    "zestaw-znakow-rfc2231-zawiniety": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU
    + b"Content-Type: text/plain; charset*\n=''\r\n\r\nabc\r\n",
    "nadawca-z-nawiasem-kwadratowym-i-zla-granica": b"From: a@[b.invalid\r\n" + TEMAT_RAPORTU
    + b'Content-Type: multipart/mixed; boundary="x":\r\n\r\n--x\r\nContent-Type: application/pdf\r\n'
    + b"Content-Disposition: attachment; filename=a.pdf\r\n\r\nAAAA\r\n--x-\r\n -",
    "czesc-multipart-bez-granicy": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU
    + b'Content-Type: multipart/alternative; boundary="x"\r\n\r\n--x\r\nContent-Type: multipart/related\r\n\r\n-x--',
    "nadawca-z-niezamknietym-cudzyslowem": b'From: "\n' + TEMAT_RAPORTU + b"\r\nx\r\n",
    "nadawca-z-niezamknietym-nawiasem": b"From: <\r\n" + TEMAT_RAPORTU + b"\r\nx\r\n",
    "message-id-z-nawiasami": b"From: ola@przyklad.invalid\r\n" + TEMAT_RAPORTU + b"Message-ID: <<<\r\n\r\nx\r\n",
    "zalacznik-rfc822-z-zla-granica": b"From: a@\rb.invalid\r\n" + TEMAT_RAPORTU
    + b'Content-Type: multipart/mixed; boundary="\xffx"\r\n\r\n--x\r\nContent-yp: mess]age/rfc822\r\n\r\n'
    + b"From: c@d.pFrom: l\r\nSubject: s\r\n\r\nbody\r\n--x--",
}


@pytest.mark.parametrize("zepsuty", ZEPSUTE.values(), ids=ZEPSUTE.keys())
def test_zepsuty_mail_z_raportem_w_temacie_nie_wywraca_odczytu_skrzynki_tylko_liczy_sie_jako_pominiety(
    tmp_path: Path, zepsuty: bytes
) -> None:
    """Maile, na których pakiet ``email`` Pythona 3.11, 3.12 albo 3.14 zgłaszał wyjątek (fuzz recenzenta #1236).

    Który mail parser umie rozebrać, zależy od wersji, więc test żąda tylko, żeby każdy mail był przeczytany albo
    policzony jako pominięty, a poprawne Raporty przed zepsutym mailem i po nim doszły (skrzynka: zepsuty, dobry,
    zepsuty, dobry).
    """

    dobre = [surowy(message_id=b"<dobry-1@x.invalid>"), surowy(message_id=b"<dobry-2@x.invalid>")]
    mails = [w_skrzynce(1, zepsuty), w_skrzynce(2, dobre[0]), w_skrzynce(3, zepsuty), w_skrzynce(4, dobre[1])]

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert isinstance(outcome, Mails), outcome
    found = {mail.id: (mail.subject, mail.text) for mail in outcome.mails}
    assert [found.get(MailId.of(f"<dobry-{n}@x.invalid>")) for n in (1, 2)] == [
        ("Raport 08.11.2026", "40000001 tak wymiana routera")
    ] * 2
    assert len(outcome.mails) + outcome.skipped == len(mails)
    assert polecenia(atrapa)[-1] == "LOGOUT"


def test_mail_z_zestawem_znakow_z_bajtem_zerowym_czyta_tresc_jako_utf8() -> None:
    mail = mail_of(ZEPSUTE["zestaw-znakow-z-bajtem-zerowym"], datetime(2026, 11, 8, 18, 5, tzinfo=TATA))

    assert mail is not None
    assert mail.text.strip() == "40000002 nie"


def test_mail_tylko_z_html_daje_tekst_z_linia_na_akapit_bez_stylow_i_skryptow() -> None:
    mail = mail_of(surowy(tresc=HTML, typ="text/html"), datetime(2026, 11, 8, 18, 5, tzinfo=TATA))

    assert mail is not None
    assert mail.text == "40000001 tak wymiana routera\n40000002 nie brak klienta\n40000003 tak\nmontaż\nPozdrawiam\nJan"


def test_mail_z_tekstem_i_html_daje_tekst_z_czesci_text_plain() -> None:
    raw = (
        b"From: jan.testowy@przyklad.invalid\r\nSubject: Raport 08.11.2026\r\nMIME-Version: 1.0\r\n"
        b'Content-Type: multipart/alternative; boundary="g"\r\n\r\n'
        b"--g\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>z html</p>\r\n"
        b"--g\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n40000001 tak z tekstu\r\n--g--\r\n"
    )

    mail = mail_of(raw, datetime(2026, 11, 8, 18, 5, tzinfo=TATA))

    assert mail is not None
    assert mail.text.strip() == "40000001 tak z tekstu"
    assert mail.id == MailId.of(hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(
    "tresc",
    [
        f"{SKRZYNKA}\r\nabcd efgh ijkl mnop\r\n".encode("utf-8-sig"),
        f"{SKRZYNKA}\r\nabcd efgh ijkl mnop\r\n".encode("utf-16"),
        codecs.BOM_UTF16_BE + f"{SKRZYNKA}\nabcdefghijklmnop".encode("utf-16-be"),
        f"  {SKRZYNKA.upper()}  \n  abcd efgh ijkl mnop  \n".encode(),
    ],
    ids=["notatnik-bom-utf8", "powershell-utf16-le", "utf16-be", "spacje-i-wielkie-litery"],
)
def test_plik_dostepu_z_notatnika_albo_powershella_otwiera_skrzynke(tmp_path: Path, tresc: bytes) -> None:
    inbox_config = dostep(tmp_path, tresc)

    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=[w_skrzynce(1, surowy())]) as atrapa:
        inbox = port(inbox_config, atrapa)
        state, outcome = inbox.access(), inbox.mails_since(date(2026, 11, 8))

    assert state == "ready"
    assert len(maile(outcome)) == 1


@pytest.mark.parametrize(
    ("tresc", "stan"),
    [
        (None, "missing"),
        (b"", "missing"),
        (f"{SKRZYNKA}\n".encode(), "missing"),
        (b"\nabcd efgh ijkl mnop\n", "missing"),
        (b"raporty.taty\nabcd efgh ijkl mnop\n", "unreadable"),
        (b"Tata <raporty.taty@przyklad.invalid>\nabcd\n", "unreadable"),
        (f"{SKRZYNKA}\nhas\xb3o\n".encode("latin-1"), "unreadable"),
        (f"{SKRZYNKA}\nhasło\n".encode(), "unreadable"),
    ],
    ids=["brak-pliku", "pusty", "bez-hasla", "bez-adresu", "adres-bez-malpy", "adres-z-nazwa", "nie-utf8", "haslo-spoza-ascii"],
)
def test_plik_dostepu_bez_hasla_albo_z_zla_trescia_nie_laczy_sie_ze_skrzynka(
    tmp_path: Path, tresc: bytes | None, stan: str
) -> None:
    if tresc is not None:
        dostep(tmp_path, tresc)

    def no_connection() -> imaplib.IMAP4:
        raise AssertionError("port łączy się ze skrzynką bez pliku dostępu")

    inbox = ImapInbox(tmp_path, connect=no_connection)

    assert inbox.access() == stan
    assert inbox.mails_since(date(2026, 11, 8)) == InboxUnreachable(stan)


def test_odrzucone_haslo_aplikacji_daje_wynik_odrzuconego_hasla_bez_otwarcia_skrzynki(tmp_path: Path) -> None:
    with AtrapaImap(address=SKRZYNKA, password="inne-haslo-maksa", mails=[w_skrzynce(1, surowy())]) as atrapa:
        outcome = port(dostep(tmp_path), atrapa).mails_since(date(2026, 11, 8))

    assert outcome == PasswordRejected()
    assert polecenia(atrapa) == ["LOGIN", "LOGOUT"]


def test_zerwane_polaczenie_i_brak_sieci_daja_wynik_niedostepnej_skrzynki_z_sama_nazwa_bledu(tmp_path: Path) -> None:
    config = dostep(tmp_path)

    with AtrapaImap(address=SKRZYNKA, password=HASLO, cut="greeting") as atrapa:
        cut = port(config, atrapa).mails_since(date(2026, 11, 8))

    def no_network() -> imaplib.IMAP4:
        raise ConnectionRefusedError(f"brak sieci przy {SKRZYNKA}")

    assert cut == InboxUnreachable("IMAP4.abort")
    assert ImapInbox(config, connect=no_network).mails_since(date(2026, 11, 8)) == InboxUnreachable("ConnectionRefusedError")


@pytest.mark.parametrize(
    ("zerwanie", "odmowa", "przyczyna", "do_serwera"),
    [
        (None, "login", "IMAP4.error", ["LOGIN", "LOGOUT"]),
        ("after_login", None, "TimeoutError", ["LOGIN", "LIST", "LOGOUT"]),
        (None, "examine", "UnexpectedReply", ["LOGIN", "LIST", "EXAMINE", "LOGOUT"]),
    ],
    ids=["chwilowa-odmowa-logowania-bez-zlego-hasla", "gmail-milknie-po-zalogowaniu", "odmowa-otwarcia-folderu"],
)
def test_awaria_gmaila_w_trakcie_sesji_daje_wynik_niedostepnej_skrzynki_a_nie_odrzuconego_hasla(
    tmp_path: Path,
    zerwanie: Literal["after_login"] | None,
    odmowa: Literal["login", "examine"] | None,
    przyczyna: str,
    do_serwera: list[str],
) -> None:
    class LimitCzasuPoZalogowaniu(imaplib.IMAP4):
        """Połączenie, któremu limit czasu (w porcie ``TIMEOUT_S``) mija od razu po zalogowaniu, a nie wcześniej."""

        def login(self, user: str, password: str) -> tuple[Literal["OK"], list[bytes]]:
            reply = super().login(user, password)
            self.sock.settimeout(0.01)
            return reply

    mails = [w_skrzynce(1, surowy())]
    with AtrapaImap(address=SKRZYNKA, password=HASLO, mails=mails, cut=zerwanie, refuse=odmowa) as atrapa:
        inbox = ImapInbox(dostep(tmp_path), connect=lambda: LimitCzasuPoZalogowaniu("127.0.0.1", atrapa.port))
        outcome = inbox.mails_since(date(2026, 11, 8))

    assert outcome == InboxUnreachable(przyczyna)
    assert polecenia(atrapa) == do_serwera


def _zlap_wynik(config: Path, scenariusz: str) -> tuple[ImapInbox, InboxOutcome]:
    if scenariusz == "brak-sieci":

        def no_network() -> imaplib.IMAP4:
            raise TimeoutError(f"LOGIN {SKRZYNKA} {HASLO}")

        inbox = ImapInbox(config, connect=no_network)
        return inbox, inbox.mails_since(date(2026, 11, 8))
    password = HASLO if scenariusz == "maile" else "inne-haslo-maksa"
    with AtrapaImap(address=SKRZYNKA, password=password, mails=[w_skrzynce(1, surowy())]) as atrapa:
        inbox = port(config, atrapa)
        return inbox, inbox.mails_since(date(2026, 11, 8))


@pytest.mark.parametrize("scenariusz", ["maile", "odrzucone-haslo", "brak-sieci"])
def test_haslo_aplikacji_nie_wychodzi_z_portu_w_zadnym_wyniku(tmp_path: Path, scenariusz: str) -> None:
    inbox, outcome = _zlap_wynik(dostep(tmp_path), scenariusz)

    texts = [repr(inbox), repr(outcome), str(outcome)]
    if isinstance(outcome, Mails):
        texts += [repr(mail) for mail in outcome.mails] + [mail.subject + mail.text for mail in outcome.mails]
    assert texts and not [text for text in texts if HASLO in text or "abcd efgh" in text]


def test_adres_nadawcy_nie_jest_tekstem_i_nie_pokazuje_sie_w_repr() -> None:
    address = SenderAddress.of("Jan Testowy <Jan.Testowy@Przyklad.invalid>")

    class Pole(pydantic.BaseModel):
        tekst: str

    assert address is not None
    assert address == SenderAddress.of(WYKONAWCA)
    assert len({address, SenderAddress.of(WYKONAWCA)}) == 1
    assert address.shown() == WYKONAWCA
    assert "jan" not in repr(address).casefold()
    with pytest.raises(TypeError, match="shown"):
        str(address)
    with pytest.raises(TypeError, match="shown"):
        f"{address}"
    with pytest.raises(pydantic.ValidationError):
        Pole(tekst=address)  # type: ignore[arg-type]
    niepoprawne = ["", "Jan Testowy", "a@b@c.invalid", '"a@b"@przyklad.invalid', '"a b"@przyklad.invalid', "@x.invalid", "jan@"]
    assert [SenderAddress.of(header) for header in niepoprawne] == [None] * len(niepoprawne)


def test_test_bez_atrapy_skrzynki_raportow_pada_zamiast_laczyc_sie_z_gmailem(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="Skrzynką raportów w Gmailu"):
        ImapInbox(dostep(tmp_path)).mails_since(date(2026, 11, 8))


def test_atrapa_skrzynki_raportow_procesu_oddaje_swoj_wynik_i_zapisuje_dzien_kazdego_odczytu() -> None:
    mail = mail_of(surowy(), datetime(2026, 11, 8, 18, 5, tzinfo=TATA))
    assert mail is not None
    with_mails = FakeInbox([mail])
    rejected = FakeInbox(PasswordRejected(), state="unreadable")
    inboxes: list[WorkerReportInbox] = [with_mails, rejected]

    assert [inbox.mails_since(date(2026, 11, 8)) for inbox in inboxes] == [Mails((mail,), skipped=0), PasswordRejected()]
    assert [inbox.access() for inbox in inboxes] == ["ready", "unreadable"]
    assert with_mails.days == rejected.days == [date(2026, 11, 8)]
