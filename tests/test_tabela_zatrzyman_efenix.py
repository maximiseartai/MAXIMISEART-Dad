"""Tabela decyzji Zatrzymań okna efenix: który wyjątek okna, z jaką częścią strony i przyczyną z zamkniętej listy
(``efenix_window.WindowCause``) daje klasyfikator ``efenix_window.WindowStop.of`` z dowodu awarii.

Wyjątek okna buduje tylko ten klasyfikator, a konstruktora bez jego dowodu nie przepuszcza mypy. Że miejsce okna zbiera
właściwy dowód i przyczyna dochodzi do Logów Uruchomienia, pokazują testy zachowania: ``CHANGED``, ``ANSWERED``,
``UNREAD`` i przegląd odcięć w ``tests/test_wycena_efenix.py``, kontrakt okien w ``tests/test_atrapa_efenix.py`` oraz
hipotezy B–E w ``tests/test_centrum_logi_uruchomienia.py``.
"""

from __future__ import annotations

import pytest

from rozliczenia.efenix_window import (
    BrowserFailure,
    BrowserNotStarted,
    Closed,
    EfenixUnreachable,
    ElementCount,
    Evidence,
    HttpStatus,
    ListOpenFailed,
    LoggedOut,
    LoginExpired,
    LoginSign,
    Operation,
    OtherShape,
    PagePart,
    Shape,
    StatusChangeBlocked,
    UnexpectedPage,
    WindowCause,
    WindowClosed,
    WindowStop,
)

_OPEN = BrowserFailure("Error", Operation.OPEN)


@pytest.mark.parametrize(
    ("part", "evidence", "stop", "stop_part", "cause"),
    [
        pytest.param(PagePart.DATE, LoginSign.REDIRECT, LoggedOut, PagePart.DATE, LoginSign.REDIRECT, id="wylogowanie"),
        pytest.param(
            PagePart.ORDER, Closed.DURING_ACTION, WindowClosed, PagePart.ORDER, Closed.DURING_ACTION, id="zamkniete-okno"
        ),
        pytest.param(
            PagePart.LIST,
            BrowserFailure("Error", Operation.DRIVER),
            BrowserNotStarted,
            None,
            BrowserFailure("Error", Operation.DRIVER),
            id="sterownik-nie-wystartowal",
        ),
        pytest.param(
            PagePart.LIST,
            BrowserFailure("Error", Operation.START),
            BrowserNotStarted,
            None,
            BrowserFailure("Error", Operation.START),
            id="przegladarka-nie-wystartowala",
        ),
        pytest.param(
            PagePart.RESULTS,
            BrowserFailure("TimeoutError", Operation.ANSWER),
            UnexpectedPage,
            PagePart.RESULTS,
            BrowserFailure("TimeoutError", Operation.ANSWER),
            id="blad-przegladarki-w-dzialaniu",
        ),
        pytest.param(
            PagePart.QUANTITY,
            BrowserFailure("Error", None),
            UnexpectedPage,
            PagePart.QUANTITY,
            BrowserFailure("Error", None),
            id="blad-przegladarki-bez-nazwy",
        ),
        pytest.param(
            PagePart.ORDER,
            ElementCount("#data_install", 2),
            UnexpectedPage,
            PagePart.ORDER,
            ElementCount("#data_install", 2),
            id="element-nie-raz",
        ),
        pytest.param(PagePart.EMMETT, HttpStatus(500), UnexpectedPage, PagePart.EMMETT, HttpStatus(500), id="status-http"),
        pytest.param(
            PagePart.ORDER,
            OtherShape(Shape.DATE_TEXT),
            UnexpectedPage,
            PagePart.ORDER,
            OtherShape(Shape.DATE_TEXT),
            id="inna-budowa",
        ),
        pytest.param(
            PagePart.FORWARD,
            StatusChangeBlocked.OTHER_STATUS,
            UnexpectedPage,
            PagePart.FORWARD,
            StatusChangeBlocked.OTHER_STATUS,
            id="straznik-zmiany-statusu",
        ),
        pytest.param(
            PagePart.LIST, ListOpenFailed(_OPEN, False), EfenixUnreachable, PagePart.LIST, _OPEN, id="lista-przed-otwarciem"
        ),
        pytest.param(
            PagePart.LIST, ListOpenFailed(_OPEN, True), UnexpectedPage, PagePart.LIST, _OPEN, id="lista-po-otwarciu"
        ),
        pytest.param(
            PagePart.LIST,
            LoginExpired(_OPEN, 60.0, 30_000),
            EfenixUnreachable,
            PagePart.LIST,
            _OPEN,
            id="limit-logowania-po-dwoch-czasach-okna-ciszy",
        ),
        pytest.param(
            PagePart.LIST,
            LoginExpired(_OPEN, 59.9, 30_000),
            LoggedOut,
            PagePart.LIST,
            LoginSign.NO_LOGIN,
            id="limit-logowania-po-krotszej-ciszy",
        ),
        pytest.param(
            PagePart.LIST,
            LoginExpired(None, 900.0, 30_000),
            LoggedOut,
            PagePart.LIST,
            LoginSign.NO_LOGIN,
            id="limit-logowania-z-odpowiedzia",
        ),
    ],
)
def test_dowod_awarii_okna_efenix_daje_wyjatek_okna_z_tabeli_decyzji(
    part: PagePart, evidence: Evidence, stop: type[WindowStop], stop_part: PagePart | None, cause: WindowCause
) -> None:
    classified = WindowStop.of(part, evidence)

    assert (type(classified), classified.part, classified.cause) == (stop, stop_part, cause)
