"""SONDA #1580 (nie do scalenia): czasy pytania o Wydania na runnerze CI."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from rozliczenia.centrum import tool_freshness
from tests.fixtures.centrum import CentrumClient, ToolDirectory, centrum_app
from tests.fixtures.centrum_processes import write_configuration
from tests.fixtures.github_api import github_api, newest_on_main

GITHUB_RELEASES = tool_freshness.github_releases
NEWER = "2" * 40

FRESH = r'''
import ssl, time, urllib.request, sys
sys.path[:0] = ["src", "."]
def ms(f, n=5):
    out = []
    for _ in range(n):
        t = time.perf_counter(); f(); out.append(round((time.perf_counter() - t) * 1000, 1))
    return out
print("ctx", ms(ssl.create_default_context))
print("opener", ms(lambda: urllib.request.build_opener(urllib.request.ProxyHandler({}))))
ctx = ssl.create_default_context()
print("opener_ctx", ms(lambda: urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))))
if hasattr(ssl, "enum_certificates"):
    print("certs", len(ssl.enum_certificates("ROOT")), len(ssl.enum_certificates("CA")))
from tests.fixtures.github_api import github_api, newest_on_main
from rozliczenia.centrum.tool_freshness import releases_from
with github_api(newest_on_main("/repos/t/n", "v9.0.0", "2" * 40)) as api:
    print("releases", ms(lambda: releases_from(api.url + "/repos/t/n", timeout_s=60.0)))
'''


def test_sonda_1580(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lines = []
    for i in range(2):
        out = subprocess.run([sys.executable, "-c", FRESH], capture_output=True, text=True, timeout=120)
        lines.append(f"fresh{i}: {out.stdout} {out.stderr[-500:]}")
    monkeypatch.setattr(tool_freshness, "github_releases", GITHUB_RELEASES)
    for i in range(20):
        tool = ToolDirectory(tmp_path / str(i))
        write_configuration(tool)
        with github_api(newest_on_main("/repos/tata/narzedzie", "v9.0.0", NEWER)) as api:
            monkeypatch.setattr(tool_freshness, "TOOL_API", f"{api.url}/repos/tata/narzedzie")
            t0 = time.perf_counter()
            app = centrum_app(tool, tool_freshness=None)
            t1 = time.perf_counter()
            client = CentrumClient(app)
            configuration = client.get("/api/configuration").json()
            t2 = time.perf_counter()
            client.stop()
        lines.append(
            f"run{i}: app {t1 - t0:.3f}s get {t2 - t1:.3f}s {configuration['freshness']} {configuration['update_offered']} asked {len(api.asked)}"
        )
    pytest.fail("\n".join(lines))
