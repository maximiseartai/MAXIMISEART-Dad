"""One-command proof of Centrum rozliczeń: fixture, launch, doctor, drive in Chromium, cleanup, self-test.

Prints ``VERIFY OK | features=… | evidence=… | scratch_removed=true`` or
``VERIFY FAIL | …``. Scratch lives in ``<run dir>/runs/centrum-<id>`` and is
removed; evidence lives in ``<run dir>/evidence/centrum-<id>`` and is kept.
"""

from __future__ import annotations

from argparse import RawDescriptionHelpFormatter
from collections.abc import Mapping, Sequence
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "tools/lib"))

from drive import DEFAULT_REPEATS, FEATURES
from quiet_machine import MachineBusy, QuietMachine
from skrypt_skilla import Parser, new_run, part

SCRIPTS = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS.parents[3]
STEP_TIMEOUT_SECONDS = 300
# A drive of several features gets this much per feature: `all` (22 features) drove 280-305 s on windows-latest on
# 26.10 and timed out at a fixed STEP_TIMEOUT_SECONDS (CI runs 40309201075 and 40322305317), so its limit grows with
# each feature it drives.
DRIVE_SECONDS_PER_FEATURE = 40
# wydajnosc repeats every scenario in two CPU profiles, so its drive takes minutes.
PERFORMANCE_TIMEOUT_SECONDS = 1800
REQUIRED_EVIDENCE = (
    "fixture.txt",
    "server.txt",
    "doctor.txt",
    "drive.txt",
    "cleanup.txt",
    "self-test.txt",
)
REQUIRED_SCREENSHOTS = {
    "ustawienia": (
        "01-ustawienia-pusty-stan.png",
        "19-ustawienia-jedno-okno-wyboru.png",
        "02-ustawienia-folder-okresow.png",
        "03-ustawienia-rejestr-zlecen.png",
        "18-ustawienia-braki-do-startu.png",
        "04-ustawienia-brak-rejestru.png",
        "05-ustawienia-motyw-jasny.png",
    ),
    "tablica-okresow": (
        "06-tablica-okresow.png",
        "07-tablica-otwieranie.png",
        "1a-tablica-podwojne-klikniecie.png",
        "08-tablica-po-zmianie-na-dysku.png",
        "09-tablica-podpowiedz.png",
        "17-tablica-odczyt-nieudany.png",
        "156-tablica-brakujacy-plik.png",
        "157-tablica-brakujacy-plik-dotyk.png",
    ),
    "uklad-folderow-taty": (
        "15-uklad-taty-tablica.png",
        "16-uklad-taty-otwieranie.png",
    ),
    "konfiguracja": (
        "10-konfiguracja-gotowa.png",
        "11-konfiguracja-tylko-do-odczytu.png",
        "12-konfiguracja-wzorzec-otwarty.png",
        "12a-konfiguracja-wzorzec-niedostepny.png",
        "12b-konfiguracja-wzorzec-dostepny.png",
        "13-konfiguracja-brak-wzorca.png",
        "14-konfiguracja-nieczytelna-konfiguracja-wykonawcow.png",
    ),
    "aktualizacja": (
        "93-aktualizacja-jest-nowsza.png",
        "115-aktualizacja-brak-sieci.png",
        "116-aktualizacja-brak-sieci-zgloszenie.png",
        "94-aktualizacja-postep.png",
        "100-aktualizacja-ponowny-start.png",
        "101-aktualizacja-zaktualizowano.png",
        "96-aktualizacja-najnowsza.png",
        "130-aktualizacja-instalowanie.png",
        "131-aktualizacja-instalacja-nieudana.png",
        "135-aktualizacja-nie-wystartowala-ponowny-start.png",
        "136-aktualizacja-nie-wystartowala.png",
        "137-aktualizacja-nie-wystartowala-konfiguracja.png",
        "132-aktualizacja-start-ze-skrotu.png",
        "138-aktualizacja-ok-przy-starej-wersji.png",
    ),
    "metryki": (
        "20-metryki-karty-okresow.png",
        "21-metryki-wykres.png",
        "2a-metryki-wykres-waski.png",
        "22-metryki-tabela-etapow.png",
        "23-metryki-za-malo-obserwacji.png",
        "24-metryki-historia.png",
        "25-metryki-historia-filtry.png",
        "2b-metryki-rodzaj-zatrzymania.png",
        "26-metryki-nowy-rekord-spoza-centrum.png",
        "27-metryki-pusty-stan.png",
        "28-metryki-wykres-szczegoly-ciemny.png",
        "29-metryki-wykres-szczegoly-jasny.png",
    ),
    "blad-odczytu": (
        "139-blad-odczytu-ustawienia.png",
        "142-blad-odczytu-tablica.png",
        "153-blad-odczytu-okresy-trzy-odczyty.png",
        "154-blad-odczytu-okresy-jednym-kliknieciem.png",
        "143-blad-odczytu-uruchomienia.png",
        "144-blad-odczytu-historia.png",
        "145-blad-odczytu-metryki.png",
        "146-blad-odczytu-konfiguracja.png",
        "141-blad-odczytu-ponowny-odczyt.png",
        "147-blad-odczytu-powiadomienia.png",
        "148-blad-odczytu-uwaga.png",
    ),
    "przygotowanie-pliku-zbiorczego": (
        "30-przygotowanie-nowe-uruchomienie.png",
        "31-przygotowanie-podglad.png",
        "32-przygotowanie-potwierdzenie.png",
        "39-przygotowanie-bez-podgladu.png",
        "33-przygotowanie-decyzja.png",
        "149-przygotowanie-znak-decyzji.png",
        "34-przygotowanie-zatrzymanie.png",
        "3a-przygotowanie-podwojne-klikniecie.png",
        "35-przygotowanie-zapisane.png",
        "3b-przygotowanie-otwieranie.png",
        "36-przygotowanie-status-okresu.png",
        "37-przygotowanie-nienadpisywanie.png",
        "38-przygotowanie-historia.png",
    ),
    "uzupelnienie": (
        "215-uzupelnienie-gotowe.png",
        "216-uzupelnienie-gotowe-potwierdzenie.png",
        "217-uzupelnienie-gotowe-bez-odczytu.png",
        "218-uzupelnienie-gotowe-po-podgladzie.png",
        "220-uzupelnienie-karta.png",
        "221-uzupelnienie-podsumowanie.png",
        "222-uzupelnienie-po-wpisie.png",
        "223-uzupelnienie-blokada-excela.png",
        "224-uzupelnienie-bez-pliku.png",
    ),
    "przebieg-rozliczen": (
        "40-przebieg-nowe-uruchomienie.png",
        "4e-przebieg-krok-uzupelnienie.png",
        "4f-przebieg-krok-wycena.png",
        "4g-przebieg-krok-rozliczenia.png",
        "41-przebieg-podglad.png",
        "42-przebieg-potwierdzenie.png",
        "43-przebieg-na-zywo.png",
        "155-przebieg-znak-uruchomienia.png",
        "44-przebieg-zapisane.png",
        "49-przebieg-otwieranie.png",
        "45-przebieg-status-okresu.png",
        "46-przebieg-nienadpisywanie.png",
        "47-przebieg-wymaga-sprawdzenia.png",
        "47b-przebieg-nieznany-wykonawca.png",
        "48-przebieg-odczyt-po-uruchomieniu.png",
    ),
    "kontrola-ilosci": (
        "150-kontrola-w-kolejce.png",
        "151-kontrola-bez-sieci-po-starcie.png",
        "152-kontrola-start-bez-czekania.png",
    ),
    "diagnoza": (
        "50-diagnoza-dla-taty.png",
        "51-diagnoza-powtorka.png",
        "52-diagnoza-wyjasnienie.png",
        "53-diagnoza-sprawdzono.png",
        "54-diagnoza-inny-komunikat.png",
        "55-diagnoza-do-maksa.png",
        "56-diagnoza-do-maksa-wyjasnienie.png",
        "57-diagnoza-bez-przyczyny.png",
        "58-diagnoza-nieoczekiwany-wyjatek.png",
        "59-diagnoza-nieoczekiwany-wyjatek-zgloszenie.png",
        "59b-diagnoza-klucz-odrzucony.png",
        "59c-diagnoza-konfiguracja-wykonawcow.png",
    ),
    "aktualnosc-i-onedrive": (
        "76-aktualnosc-nowsza-wersja.png",
        "77-aktualnosc-brak-sieci.png",
        "78-onedrive-tylko-w-chmurze.png",
        "81-aktualnosc-propozycja.png",
        "140-aktualnosc-aktualizacja-w-trakcie.png",
        "79-aktualnosc-i-onedrive-przeszly.png",
    ),
    "zgloszenie": (
        "60-zgloszenie-podglad.png",
        "61-zgloszenie-bez-klucza.png",
        "61b-zgloszenie-bez-klucza-powiadomienia.png",
        "62-zgloszenie-konfiguracja-brak-klucza.png",
        "63-zgloszenie-konfiguracja-gotowe.png",
        "63b-zgloszenie-konfiguracja-odrzucony.png",
        "64-zgloszenie-wyslane.png",
        "65-zgloszenie-po-odswiezeniu.png",
        "66-zgloszenie-kolejne-uruchomienie.png",
        "68-zgloszenie-zamkniete-przed-diagnoza.png",
        "69-zgloszenie-zamkniete-po-diagnozie.png",
        "70-zgloszenie-nowe-z-odnosnikiem.png",
        "71-zgloszenie-inny-problem.png",
        "72-zgloszenie-bez-sieci.png",
        "73-zgloszenie-bez-sieci-wyslane.png",
        "74-zgloszenie-odrzucone.png",
        "74b-zgloszenie-odrzucone-powiadomienia.png",
        "75-zgloszenie-odrzucone-po-starcie.png",
    ),
    "uwaga-taty": (
        "170-uwaga-ikona-w-naglowku.png",
        "171-uwaga-puste-okno.png",
        "172-uwaga-dlugi-tekst.png",
        "173-uwaga-wypelniona.png",
        "174-uwaga-token-nie-dziala.png",
        "174b-uwaga-odrzucona.png",
        "174c-uwaga-odrzucona-powiadomienia.png",
        "175-uwaga-wysylanie.png",
        "176-uwaga-wyslana.png",
        "190-uwaga-przycisk-na-karcie.png",
        "191-uwaga-z-karty.png",
        "192-uwaga-przypieta.png",
        "193-uwaga-ogolna-z-karty.png",
        "194-uwaga-historia.png",
        "195-uwaga-z-historii.png",
        "196-uwaga-z-historii-laptop.png",
    ),
    "logi-uruchomienia": (
        "160-logi-podglad.png",
        "161-logi-zatrzymanie.png",
    ),
    "karta-z-logow": (
        "210-karta-przed-zamknieciem.png",
        "211-karta-po-zamknieciu.png",
        "212-karta-przerwana.png",
        "213-karta-z-historii.png",
        "214-karta-bez-logow.png",
    ),
    "uporzadkowanie-intermax": (
        "230-intermax-bez-intermax.png",
        "231-intermax-karta.png",
        "232-intermax-otwarty.png",
        "233-intermax-wynik.png",
        "234-intermax-zatrzymanie-dla-taty.png",
        "235-intermax-do-maksa.png",
        "236-intermax-historia.png",
        "237-intermax-metryki.png",
    ),
    "kopie-intermax": (
        "240-kopie-intermax-lista.png",
        "241-kopie-intermax-ostrzezenie.png",
        "242-kopie-intermax-otwarty.png",
        "243-kopie-intermax-przywrocona.png",
    ),
    "wycena-w-efenix": (
        "260-efenix-karta-startu.png",
        "261-efenix-logowanie.png",
        "262-efenix-postep.png",
        "263-efenix-karta.png",
    ),
    "powiadomienia": (
        "180-powiadomienia-dzwonek.png",
        "181-powiadomienia-kropka.png",
        "182-powiadomienia-widok.png",
        "183-powiadomienia-widok-drugi-motyw.png",
        "184-powiadomienia-brak-sieci.png",
        "201-powiadomienia-plik-niedostepny.png",
        "202-powiadomienia-plik-zapisany.png",
    ),
    "pomiar-u-taty": ("80-pomiar-bez-sladu.png",),
    # Numbered 9x: the feature closes Centrum, so its screenshots are always the last ones.
    "start-i-zamykanie": (
        "90-start-i-zamykanie-karty-w-tle.png",
        "91-start-i-zamykanie-potwierdzenie.png",
        "92-start-i-zamykanie-zamkniete.png",
    ),
    "wydajnosc": (
        "84-wydajnosc-okresy.png",
        "85-wydajnosc-uruchomienia.png",
        "86-wydajnosc-metryki.png",
        "87-wydajnosc-konfiguracja.png",
    ),
}
REQUIRED_FEATURE_EVIDENCE = {
    "wydajnosc": (
        "wydajnosc/raport.json",
        "wydajnosc/raport.txt",
        "wydajnosc/baseline-kandydat.json",
        "wydajnosc/slad-okresy-4x.json",
        "wydajnosc/slad-okresy-6x.json",
        "wydajnosc/slad-metryki-4x.json",
        "wydajnosc/slad-metryki-6x.json",
    ),
}


class VerificationFailure(Exception):
    pass


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def driven(feature: str, environment: Mapping[str, str] = os.environ) -> tuple[str, ...]:
    """The features a run of ``--feature feature`` drives, in order: ``all`` is every feature but ``EXPLICIT_FEATURES``,
    or in CI the part ``MUTACJE_CZESC=k/n`` of them (``skrypt_skilla.part``)."""

    return part(FEATURES, environment) if feature == "all" else (feature,)


def drive_timeout_s(features: Sequence[str]) -> int:
    """How long the drive of ``features`` may run before it counts as hung."""

    if tuple(features) == ("wydajnosc",):
        return PERFORMANCE_TIMEOUT_SECONDS
    return max(STEP_TIMEOUT_SECONDS, DRIVE_SECONDS_PER_FEATURE * len(features))


def _run_step(name: str, arguments: list[str], evidence: Path, timeout: int = STEP_TIMEOUT_SECONDS) -> None:
    command = [sys.executable, *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        (evidence / f"{name}.txt").write_text(f"command: {command}\ntimed out\n", encoding="utf-8")
        raise VerificationFailure(f"{name} timed out") from exc
    (evidence / f"{name}.txt").write_text(
        f"command: {command}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}\nexit_code={completed.returncode}\n",
        encoding="utf-8",
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        raise VerificationFailure(f"{name} returned {completed.returncode}")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


def _launch(run_root: Path, evidence: Path) -> tuple[subprocess.Popen[bytes], str]:
    log = (evidence / "server.txt").open("wb")
    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS / "serve_centrum.py"), "--root", str(run_root), "--port", str(_free_port())],
        cwd=REPO_ROOT,
        env=_environment(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 30
    server_file = run_root / "server.json"
    while True:
        if process.poll() is not None:
            raise VerificationFailure(f"Centrum exited with {process.returncode} before it was ready; see server.txt")
        if server_file.exists():
            url = str(json.loads(server_file.read_text(encoding="utf-8"))["url"])
            try:
                with urllib.request.urlopen(url + "api/health", timeout=2):
                    return process, url
            except OSError:
                pass
        if time.monotonic() > deadline:
            raise VerificationFailure("Centrum was not ready within 30 seconds; see server.txt")
        time.sleep(0.1)


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Stop exactly the server process this run started."""

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _preflight() -> None:
    if not (REPO_ROOT / "src" / "rozliczenia" / "centrum" / "static" / "index.html").exists():
        raise VerificationFailure("the built frontend is missing; run `npm ci && npm run build` in frontend/")
    if importlib.util.find_spec("playwright") is None:
        raise VerificationFailure(
            "Playwright for Python is missing; run `pip install playwright` and `python -m playwright install chromium`"
        )
    # Feature files and PR descriptions name screenshots by number alone.
    owners: dict[str, list[str]] = {}
    for shot in (shot for shots in REQUIRED_SCREENSHOTS.values() for shot in shots):
        owners.setdefault(shot.split("-", 1)[0], []).append(shot)
    shared = {number: shots for number, shots in owners.items() if len(shots) > 1}
    if shared:
        raise VerificationFailure(f"screenshot numbers used twice: {shared}")


def _verify(features: tuple[str, ...], performance: list[str], run_dir: Path) -> Path:
    run = new_run(run_dir, f"centrum-{uuid.uuid4().hex}")
    run_root, evidence = run.root, run.evidence
    print(f"EVIDENCE {evidence}", flush=True)
    process: subprocess.Popen[bytes] | None = None
    try:
        _preflight()
        variant = ["--wariant", "rok-pracy"] if features == ("wydajnosc",) else []
        _run_step("fixture", [str(SCRIPTS / "create_centrum_fixture.py"), "--root", str(run_root), *variant], evidence)
        process, url = _launch(run_root, evidence)
        _run_step("doctor", [str(SCRIPTS / "centrum_doctor.py"), "--root", str(run_root)], evidence)
        _run_step(
            "drive",
            [str(SCRIPTS / "drive_centrum.py"), "--root", str(run_root), "--url", url,
             "--evidence", str(evidence), "--feature", *features, *performance],
            evidence,
            drive_timeout_s(features),
        )
    finally:
        if process is not None:
            _stop(process)
        _run_step("cleanup", [str(SCRIPTS / "centrum_cleanup.py"), "--root", str(run_root)], evidence)
    if run_root.exists():
        raise VerificationFailure(f"scratch was not removed: {run_root}")
    missing = [name for name in REQUIRED_EVIDENCE[:-1] if not (evidence / name).exists()]
    missing += [shot for name in features for shot in REQUIRED_SCREENSHOTS[name] if not (evidence / "screenshots" / shot).exists()]
    missing += [name for feature in features for name in REQUIRED_FEATURE_EVIDENCE.get(feature, ()) if not (evidence / name).exists()]
    if missing:
        raise VerificationFailure(f"evidence is missing: {', '.join(missing)}")
    _run_step("self-test", [str(SCRIPTS / "centrum_self_test.py"), "--evidence-root", str(evidence)], evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__, formatter_class=RawDescriptionHelpFormatter)
    parser.add_run_dir()
    parser.add_argument("--feature", choices=("all", *REQUIRED_SCREENSHOTS), default="all")
    parser.add_argument("--baseline", help="wydajnosc: compare with this baseline instead of the skill's.")
    parser.add_argument(
        "--powtorzenia", type=int, help=f"wydajnosc: repetitions per scenario and profile (default {DEFAULT_REPEATS})."
    )
    args = parser.parse_args(argv)
    # The drive's Polish output in UTF-8 whatever the code page: an English Windows pipe (1252) cannot encode it.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    performance = [] if args.baseline is None else ["--baseline", str(Path(args.baseline).resolve())]
    performance += [] if args.powtorzenia is None else ["--powtorzenia", str(args.powtorzenia)]
    try:
        features = driven(args.feature)
    except ValueError as exc:
        print(f"VERIFY FAIL | features={args.feature} | {exc}", file=sys.stderr)
        return 1
    shown = args.feature if features == driven(args.feature, {}) else ",".join(features)
    machine = QuietMachine()
    # wydajnosc holds the machine alone; every other run waits only for a measurement in progress.
    hold = machine.measurement() if args.feature == "wydajnosc" else machine.run()
    try:
        with hold as waited:
            if waited >= 1:
                print(f"MASZYNA WOLNA | czekano {waited:.0f} s", flush=True)
            evidence = _verify(features, performance, args.run_dir)
    except (VerificationFailure, MachineBusy) as exc:
        print(f"VERIFY FAIL | features={shown} | {exc}", file=sys.stderr)
        return 1
    print(f"VERIFY OK | features={shown} | evidence={evidence} | scratch_removed=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
