"""Tymczasowa sonda #1873 (do usunięcia przed przeglądem): czy ``--enable-logging=stderr`` daje Google Chrome okno konsoli
albo ``conhost.exe`` przy rodzicu bez konsoli i ile stderr przeglądarka wypisuje przy starcie i jednej nawigacji."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rozliczenia import efenix_browser

ROOT = Path(__file__).resolve().parents[1]
FLAG = "--enable-logging=stderr"
CASE = r"""
import ctypes, json, os, sys
from ctypes import wintypes
channel, headless, flag, profile = json.loads(sys.argv[1])
os.environ["DEBUG"] = "pw:browser"
from playwright.sync_api import sync_playwright
from atrapy.atrapa_efenix import AtrapaOrder, atrapa_efenix
from rozliczenia.efenix_browser import launch_options

user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32

class ENTRY(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_char * 260)]

def processes():
    snap = kernel32.CreateToolhelp32Snapshot(2, 0)
    entry = ENTRY(); entry.dwSize = ctypes.sizeof(ENTRY); found = {}
    ok = kernel32.Process32First(snap, ctypes.byref(entry))
    while ok:
        found[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.decode(errors="replace").lower())
        ok = kernel32.Process32Next(snap, ctypes.byref(entry))
    kernel32.CloseHandle(snap)
    return found

def tree(root):
    found = processes(); pids = {root}; grew = True
    while grew:
        grew = False
        for pid, (parent, _) in found.items():
            if parent in pids and pid not in pids:
                pids.add(pid); grew = True
    return {pid: found[pid] for pid in pids if pid in found}

def consoles():
    shown = []
    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        name = ctypes.create_unicode_buffer(64); user32.GetClassNameW(hwnd, name, 64)
        if name.value == "ConsoleWindowClass" and user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD(); user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)); shown.append(pid.value)
        return True
    user32.EnumWindows(each, 0)
    return shown

before = consoles()
with atrapa_efenix([AtrapaOrder("901", "9301", "adrian.testowy", "Miasto ul.Testowa 1")]) as atrapa, sync_playwright() as playwright:
    options = launch_options(playwright, channel=channel)
    options["args"] = [a for a in options["args"] if a != "--enable-logging=stderr"] + (["--enable-logging=stderr"] if flag else [])
    context = playwright.chromium.launch_persistent_context(profile, channel=channel, headless=headless, **options)
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(atrapa.url); page.wait_for_load_state()
    every = tree(os.getpid()); names = {pid: name for pid, (_, name) in every.items()}
    conhost = sorted(f"{names.get(every[pid][0], '?')}>{name}" for pid, (_, name) in every.items() if name == "conhost.exe")
    during = consoles()
    context.close()
print(json.dumps({"conhost": conhost, "okna_konsoli_przed": len(before), "okna_konsoli_w_trakcie": len(during),
                  "okna_konsoli_drzewa": len([pid for pid in during if pid in every])}))
"""


@pytest.mark.timeout(560)
@pytest.mark.skipif(sys.platform != "win32", reason="sonda #1873 mierzy Windows")
def test_sonda_1873_konsola_i_stderr_google_chrome(tmp_path: Path) -> None:
    assert efenix_browser.PROFILE_DIRECTORY
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tools" / "lib")])}
    results = []
    for parent in ("pythonw", "python-CREATE_NO_WINDOW"):
        for headless in (False, True):
            for flag in (False, True):
                case = f"chrome-{'bez-okna' if headless else 'okno'}-{'flaga' if flag else 'bez-flagi'}-{parent}"
                interpreter = str(pythonw) if parent == "pythonw" else sys.executable
                flags = 0 if parent == "pythonw" else 0x08000000  # CREATE_NO_WINDOW
                try:
                    done = subprocess.run(
                        [interpreter, "-c", CASE, json.dumps(["chrome", headless, flag, str(tmp_path / f"profil-{case}")])],
                        cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=90, check=False, creationflags=flags,
                    )
                    err_lines = [line for line in done.stderr.splitlines() if "pw:browser" in line and "[err]" in line]
                    outcome = done.stdout.strip().splitlines()[-1] if done.stdout.strip() else f"kod {done.returncode}: {done.stderr.strip()[-200:]}"
                    results.append(f"{case}: {outcome}; stderr przeglądarki {len(err_lines)} linii, {sum(len(line) for line in err_lines)} B; próbka {err_lines[:2]}")
                except subprocess.TimeoutExpired:
                    results.append(f"{case}: zawieszenie 90 s")
    pytest.fail("SONDA 1873\n" + "\n".join(results))
