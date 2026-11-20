from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Final

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from rozliczenia.centrum.scope import CentrumFunction, Scope, Workstation
from tests.fixtures.centrum import CentrumClient, HandRhythm, ToolDirectory, centrum_app

STALE_CZESCI: Final = frozenset(
    {
        "GET /api/health",
        "GET /api/scope",
        "GET /api/settings",
        "PUT /api/settings/folders",
        "POST /api/settings/register/choose",
        "POST /api/settings/register/open",
        "PUT /api/settings/theme",
        "GET /api/settings/history",
        "POST /api/settings/history/{change_id}/undo",
        "GET /api/runs/current",
        "GET /api/runs/events",
        "GET /api/runs/{run_id}/card",
        "POST /api/runs/{run_id}/decision",
        "POST /api/runs/{run_id}/diagnosis",
        "POST /api/runs/{run_id}/report",
        "GET /api/notifications",
        "POST /api/notifications/read",
        "GET /api/dad-notes/runs",
        "POST /api/dad-notes",
        "POST /api/dad-notes/draft",
        "GET /api/configuration",
        "GET /api/tool-update",
        "POST /api/tool-update",
        "POST /api/tool-update/report",
        "POST /api/shutdown",
        "POST /api/view-timings",
    }
)

TRASY_FUNKCJI: Final[Mapping[str, frozenset[str]]] = {
    "periods": frozenset(
        {
            "GET /api/periods",
            "POST /api/periods/{token}/open",
            "POST /api/periods/{token}/worker-settlements/open",
            "POST /api/settings/periods-directory/choose",
            "GET /api/runs/setup",
            "POST /api/runs",
        }
    ),
    "filling": frozenset(
        {
            "GET /api/periods/{token}/collective-file-version",
            "GET /api/periods/{token}/quantities-to-fill",
            "GET /api/periods/{token}/quantities-to-fill/{kind}",
            "GET /api/periods/{token}/without-quantity",
        }
    ),
    "intermax": frozenset({"GET /api/intermax", "GET /api/intermax/days", "POST /api/intermax/run"}),
    "intermax_copies": frozenset({"GET /api/intermax/copies", "POST /api/intermax/copies/restore"}),
    "report_entering": frozenset(
        {
            "GET /api/report-entering",
            "GET /api/report-entering/view",
            "POST /api/report-entering/keep",
            "POST /api/report-entering/request",
            "POST /api/report-entering/run",
        }
    ),
    "reminders": frozenset(
        {
            "PUT /api/settings/reminders",
            "PUT /api/settings/reminders/enabled",
            "POST /api/settings/reminders/preview",
        }
    ),
    "settlement_mailing": frozenset(
        {
            "GET /api/settlement-mailing",
            "POST /api/settlement-mailing/{token}/preview",
            "POST /api/settlement-mailing/{token}/send",
            "PUT /api/settings/settlement-mail",
            "POST /api/settings/settlement-mail/preview",
        }
    ),
    "metrics": frozenset({"GET /api/metrics"}),
    "quantities": frozenset(
        {
            "GET /api/settings/quantity-rules",
            "POST /api/settings/quantity-rules",
            "PUT /api/settings/quantity-rules/{rule_id}",
            "DELETE /api/settings/quantity-rules/{rule_id}",
            "POST /api/settings/quantity-rules/preview",
            "GET /api/settings/quantity-rules/differences",
            "POST /api/settings/quantity-rules/differences/{difference_id}/exception",
            "POST /api/settings/devices",
            "PUT /api/settings/devices/{device_id}",
            "DELETE /api/settings/devices/{device_id}",
            "GET /api/settings/devices/suggestions",
            "GET /api/settings/activity-legend",
            "POST /api/settings/activity-legend",
            "PUT /api/settings/activity-legend/{code_id}",
            "DELETE /api/settings/activity-legend/{code_id}",
            "POST /api/settings/activity-legend/preview",
        }
    ),
    "workers": frozenset(
        {
            "POST /api/settings/workers",
            "PUT /api/settings/workers/{login}",
            "DELETE /api/settings/workers/{login}",
            "GET /api/settings/workers/suggestions",
            "POST /api/settings/workers/{login}/addresses",
            "PUT /api/settings/workers/{login}/switches",
        }
    ),
    "templates": frozenset(),
    "report_inbox": frozenset({"PUT /api/settings/inbox-password"}),
    "autostart": frozenset({"PUT /api/settings/autostart"}),
}

WSZYSTKIE_TRASY: Final = STALE_CZESCI.union(*TRASY_FUNKCJI.values())

BEZ_TRASY: Final = ({"detail": "Not Found"}, {"detail": "Method Not Allowed"})


def _trasy(app: FastAPI) -> frozenset[str]:
    return frozenset(
        f"{method} {context.route.path_format}"
        for context in iter_route_contexts(app.routes)
        if isinstance(context.route, APIRoute)
        for method in context.route.methods or ()
    )


def _zakres(functions: Iterable[str]) -> Scope:
    return Scope(Workstation.DAD, frozenset(CentrumFunction(function) for function in functions))


def _adres(trasa: str) -> tuple[str, str]:
    method, path = trasa.split(" ")
    return method, re.sub(r"\{[^}]+\}", "x", path)


def test_centrum_taty_ma_kazda_funkcje_a_jego_trasy_to_trasy_wszystkich_funkcji_i_stalych_czesci(tmp_path: Path) -> None:
    app = centrum_app(ToolDirectory(tmp_path))
    client = CentrumClient(app)

    functions = client.get("/api/scope").json()["functions"]

    assert (sorted(functions), _trasy(app)) == (sorted(TRASY_FUNKCJI), WSZYSTKIE_TRASY)


@pytest.mark.parametrize("funkcja", list(TRASY_FUNKCJI), ids=list(TRASY_FUNKCJI))
def test_centrum_bez_funkcji_nie_ma_zadnej_jej_trasy_a_ma_trasy_pozostalych_funkcji(tmp_path: Path, funkcja: str) -> None:
    others = [function for function in TRASY_FUNKCJI if function != funkcja]
    app = centrum_app(ToolDirectory(tmp_path), scope=_zakres(others))
    client = CentrumClient(app)

    functions = client.get("/api/scope").json()["functions"]
    answered = {trasa: client.request(*_adres(trasa)).json() for trasa in TRASY_FUNKCJI[funkcja]}

    assert (sorted(functions), _trasy(app)) == (sorted(others), WSZYSTKIE_TRASY - TRASY_FUNKCJI[funkcja])
    assert {trasa: answer for trasa, answer in answered.items() if answer not in BEZ_TRASY} == {}


def test_centrum_bez_zadnej_funkcji_ma_tylko_stale_czesci_i_nie_sprawdza_przypomnien(tmp_path: Path) -> None:
    rhythm = HandRhythm()
    app = centrum_app(ToolDirectory(tmp_path), scope=_zakres(()), reminder_rhythm=rhythm)
    client = CentrumClient(app)
    client.start()

    functions = client.get("/api/scope").json()["functions"]

    assert (functions, _trasy(app), rhythm.check) == ([], STALE_CZESCI, None)


@pytest.mark.parametrize(
    ("funkcje", "sprawdza"),
    [
        pytest.param(None, True, id="zakres-taty"),
        pytest.param([function for function in TRASY_FUNKCJI if function != "reminders"], False, id="bez-przypomnien"),
    ],
)
def test_przypomnienia_co_minute_ruszaja_tylko_w_zakresie_z_funkcja_przypomnien(
    tmp_path: Path, funkcje: list[str] | None, sprawdza: bool
) -> None:
    rhythm = HandRhythm()
    scope = None if funkcje is None else _zakres(funkcje)
    client = CentrumClient(centrum_app(ToolDirectory(tmp_path), scope=scope, reminder_rhythm=rhythm))
    client.start()

    assert (rhythm.check is not None) is sprawdza
