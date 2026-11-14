"""Tymczasowa sonda #1864 (do usunięcia przed przeglądem): który program i wariant zostawia dziennik w katalogu roboczym."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from rozliczenia import efenix_browser

CASE = """
import json, sys
from pathlib import Path
from playwright.sync_api import Error, sync_playwright
channel, headless, kind, profile, arguments = json.loads(sys.argv[1])
outcome = "start"
try:
    with sync_playwright() as playwright:
        if kind == "profil-plik":
            playwright.chromium.launch_persistent_context(profile, channel=channel, headless=headless, args=arguments, timeout=20000).close()
        else:
            playwright.chromium.launch(channel=channel, headless=headless, args=["--enable-automation", *arguments], timeout=20000).close()
except Error as error:
    outcome = "błąd " + str(error).splitlines()[0][:70]
print(outcome)
"""


@pytest.mark.timeout(560)
@pytest.mark.skipif(sys.platform != "win32", reason="sonda #1864 mierzy Windows")
def test_sonda_1864_dziennik_przegladarki_w_katalogu_roboczym(tmp_path: Path) -> None:
    assert efenix_browser.PROFILE_DIRECTORY
    elsewhere = tmp_path / "gdzie-indziej"
    elsewhere.mkdir()
    variants = {"brak": [], "log-file": [f"--log-file={elsewhere / 'przegladarka.log'}"], "disable-logging": ["--disable-logging"]}
    cases = [
        (channel, headless, name, kind)
        for kind in ("profil-plik", "sonda")
        for channel in (None, "chrome")
        for headless in (True, False)
        for name in variants
        if not (kind == "sonda" and not headless)
    ]
    end = time.monotonic() + 420
    results = []
    for channel, headless, name, kind in cases:
        case = f"{channel}-{'bez-okna' if headless else 'okno'}-{name}-{kind}"
        if time.monotonic() > end:
            results.append(f"{case}: niezmierzony (budżet)")
            continue
        working = tmp_path / f"cwd-{case}"
        working.mkdir()
        profile = tmp_path / f"profil-{case}"
        profile.write_text("", encoding="utf-8")
        try:
            done = subprocess.run(
                [sys.executable, "-c", CASE, json.dumps([channel, headless, kind, str(profile), variants[name]])],
                cwd=working, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=False,
            )
            outcome = (done.stdout.strip() or done.stderr.strip()[-120:]).replace("\n", " ")
        except subprocess.TimeoutExpired:
            outcome = "zawieszenie 30 s"
        listing = {path.name: path.read_text(encoding="utf-8", errors="replace")[:120].replace("\n", " ") for path in working.iterdir()}
        results.append(f"{case}: {outcome}; cwd={listing}")
    results.append(f"gdzie-indziej={sorted(path.name for path in elsewhere.iterdir())}")
    pytest.fail("SONDA 1864\n" + "\n".join(results))
