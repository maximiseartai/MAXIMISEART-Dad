"""Hook ``tools/hooks/reczne_wydanie.py``: agent nie zakłada tagu Wydania ``v*`` ani GitHub Release z Basha.

Formy Wydania to formy z docstringu hooka i sondy przeglądów #1403 r1 i #1414 r1–r2, a polecenia zwykłej pracy pochodzą
z historii agentów i z sond fałszywych odmów #1414 r1–r2. Każdy test zachowania uruchamia hook tak jak Claude Code: JSON na
stdin, a odmowa to kod 2 z przyczyną na stderr. Własności Hypothesis biorą oczekiwanie z docstringu hooka, a to, czym
polecenie jest dla powłoki, rozstrzyga ``shlex.split`` i ``bash -n``, niezależne od hooka.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from types import ModuleType

from hypothesis import given, settings
from hypothesis import strategies as st
import pytest
import repo

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "reczne_wydanie.py"
SETTINGS = ROOT / ".claude" / "settings.json"
PROPERTY = settings(derandomize=True, database=None, deadline=None, max_examples=150)
POSIX_PYTHON3 = pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")

# Sondy przeglądów: przechodziły hook (#1403 r1 bez hooka Wydań, #1414 r1 W1 i W2 przez parser czekania).
REVIEW_PROBES = (
    "gh release create v9.9.9 --generate-notes",
    "gh api repos/maximiseartai/MAXIMISEART-Dad/git/refs -f ref=refs/tags/v9.9.9 -f sha=$(git rev-parse HEAD)",
    'git tag -m "Wydanie 9.9.9" v9.9.9',
    'gh api -H "Accept: application/vnd.github+json" repos/o/r/releases -f tag_name=v9.9.9',
    "gh api \\\n  --method POST \\\n  -H 'Accept: application/vnd.github+json' \\\n  /repos/o/r/releases \\\n"
    "  -f tag_name=v9.9.9",
    "git push --no-verify \\\n  origin refs/tags/v9.9.9",
)
# Sondy #1414 r2 W1: podstawienie bez cudzysłowu w środku argumentów nie kończy polecenia, a bash je wykonuje.
SUBSTITUTION_PROBES = (
    "git -C $(git rev-parse --show-toplevel) tag v9.9.9",
    "git tag -m $(date +%F) v9.9.9",
    "git push origin $(git rev-parse HEAD):refs/tags/v9.9.9",
    "git push origin `git rev-parse HEAD`:refs/tags/v9.9.9",
    "git push --no-verify $(git remote | head -1) v9.9.9",
    "gh api repos/o/r/git/refs -f sha=$(git rev-parse HEAD) -f ref=refs/tags/v9.9.9",
    "gh api -X POST repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases -f tag_name=v9.9.9",
    "gh api repos/o/r/releases/$(gh api repos/o/r/releases/tags/v0.8.0 --jq .id) -X DELETE",
    "gh release -R $(gh repo view --json nameWithOwner -q .nameWithOwner) create v9.9.9 --notes x",
    "gh -R $(cat repo.txt) release create v9.9.9",
)
RELEASES = (
    *REVIEW_PROBES,
    *SUBSTITUTION_PROBES,
    # Apostrof w komentarzu, po ``\\`` i w ``$(…)`` albo `` `…` `` w cudzysłowie nie otwiera napisu, który ukryłby
    # dalsze podstawienie.
    "echo x # don't\ngit tag -m $(date +%F) v9.9.9",
    'gh pr comment 1 --body "$(echo "it\'s ok")" && git tag -m $(date +%F) v9.9.9',
    'gh pr comment 1 --body "`echo "it\'s ok"`" && git tag -m $(date +%F) v9.9.9',
    "echo don\\'t && git tag -m $(date +%F) v9.9.9",
    # Nawias w napisie w podstawieniu go nie zamyka.
    "git tag -m $(echo ':)') v9.9.9",
    # Opcja długa nie jest skupieniem flag krótkich: ``n`` z ``--annotate`` nie jest trybem listy (#1414 r2 D3).
    "git tag --annotate v9.9.9",
    # Ostatnia metoda ``gh api`` wygrywa (#1414 r2 D3).
    "gh api -X GET -X POST repos/o/r/releases -f tag_name=v9.9.9",
    # ``\\`` przed nową linią to ``\`` w słowie, a nowa linia kończy polecenie (#1414 r2 D3).
    "echo a\\\\\ngit tag v9.9.9",
    "gh-axi release create v1.0.0",
    "gh release -R maximiseartai/MAXIMISEART-Dad create v9.9.9 --notes x",
    "/opt/homebrew/bin/gh release create v9.9.9",
    "'gh' release create v9.9.9",
    "gh release \\\n  create v9.9.9 --generate-notes",
    "gh release edit v0.8.0 --draft=false",
    "gh release delete v0.8.0 -y",
    "gh release upload v0.8.0 notka.txt",
    "gh api --method POST -H 'Accept: application/vnd.github+json' /repos/o/r/releases -f tag_name=v9.9.9",
    "gh api -H 'X-GitHub-Api-Version: 2022-11-28' repos/o/r/git/refs -f ref=refs/tags/v9.9.9 -f sha=abc",
    "gh api -X POST repos/o/r/releases -f tag_name=v9.9.9",
    "gh api repos/o/r/releases -f tag_name=v9.9.9",
    "gh api --method=PATCH repos/o/r/releases/123 -F draft=false",
    "gh api -XDELETE repos/o/r/git/refs/tags/v0.8.0",
    "gh api repos/o/r/git/refs --input ref.json",
    "gh api repos/o/r/git/refs -F ref=@ref.txt -f sha=abc",
    "gh api repos/o/r/git/refs -f 'ref=refs/tags/v9.9.9' -f sha=abc",
    "gh api repos/o/r/git/refs -f ref=refs/tags/$TAG -f sha=abc",
    "git push --no-verify origin v9.9.9",
    "git push --no-verify -o 'ci skip' origin v9.9.9",
    "git push origin HEAD:refs/tags/v9.9.9",
    "git push origin tag v9.9.9",
    "git push origin tag $TAG",
    "git push origin +v9.9.9",
    "git push --tags",
    "git push origin main --follow-tags",
    "git push --mirror origin",
    "git -C /x -c core.hooksPath=/dev/null push -n origin +v1.0:v1.0",
    "git push origin :refs/tags/v0.8.0",
    "git push origin 'refs/tags/*:refs/tags/*'",
    # Zmienna wpisana w polecenie nie jest sesją narzędzia Wydań.
    "MAXIMISEART_WYDANIE=1 git push --no-verify origin v9.9.9",
    "git tag v9.9.9",
    "git tag -a v9.9.9 -m 'Wydanie 9.9.9'",
    "git tag -a -m 'Wydanie 9.9.9' v9.9.9",
    "git tag -a \\\n  v9.9.9 -m x",
    'git tag -am "Wydanie 9" v9.9.9 abc123',
    "git tag -f v0.8.0 HEAD",
    "git tag -mdone v9.9.9",
    "git tag -amdone v9.9.9",
    # Identyfikator klucza w tej samej opcji: litery ``d`` i ``l`` z ``-udeadbeef`` nie są trybem usunięcia ani listy.
    "git tag -s -udeadbeef v9.9.9",
    "git tag -s -u deadbeef v9.9.9",
    "git tag -sudeadbeef v9.9.9",
    "git tag refs/tags/v9.9.9",
    "git tag $TAG",
    'git tag -s "v9.9.9"',
    "git tag v9.9.9 >/dev/null 2>&1",
    # Przekierowanie w środku polecenia go nie kończy, a pusty napis to słowo (wartość ``-m``).
    "git tag 2>/dev/null v9.9.9",
    "git tag -m '' v9.9.9",
    "cd x && git tag v9.9.9 && git push --no-verify origin v9.9.9",
    "git status\ngit tag v9.9.9",
    "echo x # komentarz\ngit tag v9.9.9",
    # ``#`` w środku słowa nie zaczyna komentarza.
    "gh pr view https://github.com/o/r/pull/1#issuecomment-1; git tag v9.9.9",
    "echo $(git tag v9.9.9)",
    "echo `git tag v9.9.9`",
    "diff <(git tag v9.9.9) x",
    "(git tag v9.9.9)",
    "{ git tag v9.9.9; }",
    "if true; then git tag v9.9.9; fi",
    "timeout 60 gh release create v9.9.9",
    "env -u X FOO=1 git tag v9.9.9",
    "sudo -u max gh release create v9.9.9",
    "nice -n 5 git push --tags",
    "bash -c 'gh release create v9.9.9'",
    "bash -lc 'git tag v9.9.9'",
    "sh -euo pipefail -c \"git push --tags\"",
    "bash -c \"bash -c 'git tag v9.9.9'\"",
    "eval 'git tag v9.9.9'",
    # Niezamknięty cudzysłów: forma Wydania stoi w poleceniu wprost.
    'echo "niezamknięty; git tag v9.9.9',
    "git tag v9.9.9 'niezamknięty",
    "'gh' release create v9.9.9 \"niezamknięty",
)
NOT_RELEASES = (
    "gh pr create --title x --body-file - <<'EOF'\nOdmawia:\ngit tag v9.9.9 i gh release create v9.9.9\nEOF",
    "git commit -m \"$(cat <<'EOF'\nfeat: hook odmawia gh release create v9.9.9 i git tag v9.9.9\nEOF\n)\"",
    "git commit -m 'hook odmawia gh release create v9.9.9 i git push --tags'",
    "gh pr comment 1414 --body 'git tag v9.9.9 przechodzi'",
    "git push -u origin chore/guard-release-tags",
    "git push origin HEAD",
    "git push --force-with-lease origin HEAD:refs/heads/x",
    "git push -o 'ci.skip' origin HEAD",
    # Wartość opcji nie jest refspekiem ani nazwą tagu.
    "git push -o 'v0.8.0 notatka' origin HEAD",
    "git tag -a -m 'v0.8.0 przed rebase' przed-rebase",
    "git push origin verify-centrum",
    "git push origin $BRANCH",
    # Podstawienie bez cudzysłowu w zwykłej pracy (#1414 r2), także w komentarzu, którego bash nie wykonuje.
    "git push -u origin $(git branch --show-current)",
    "git tag -d $(git tag -l 'v9*')",
    "git diff --stat $(git merge-base HEAD origin/main) HEAD",
    "git status # $(git tag v9.9.9)",
    "git push origin HEAD 2>&1 | tail -3",
    ".venv/bin/python tools/wydanie.py plan --plik ~/.t3/notes/wydanie/plan.json",
    ".venv/bin/python tools/wydanie.py wydaj --plan p.json \\\n  --co-nowego c.txt --potwierdzam",
    "gh release list",
    "gh release ls",
    "gh release ls -R MAXIMISEART-AI/MAXIMISEART-Dad-zgloszenia",
    "gh release view v0.8.0",
    "gh release -R maximiseartai/MAXIMISEART-Dad view v0.8.0",
    "gh release 'view' v0.8.0",
    "gh release download v0.8.0",
    "gh release verify v0.8.0",
    "gh release verify-asset v0.8.0 MAXIMISEART.zip",
    "gh release --help",
    "gh release create --help",
    "gh release --help 2>&1 | sed -n '/COMMANDS/,/FLAGS/p'",
    "gh api repos/o/r/releases/latest --jq .tag_name",
    "gh api -X GET repos/o/r/releases -f per_page=5",
    "gh api --method=GET repos/o/r/releases -f per_page=5",
    "gh api repos/o/r/git/refs -f ref=refs/heads/x -f sha=abc",
    # ``HEAD`` to odczyt (#1414 r2 D3).
    "gh api -X HEAD repos/o/r/releases",
    "gh api repos/o/r/issues/1/comments -f body='WERDYKT: PASS'",
    "git tag",
    "git tag -l 'v*'",
    "git tag --list v*",
    "git tag -d v9.9.9",
    "git tag -v v0.8.0",
    "git tag --contains HEAD",
    "git tag --sort=-creatordate | head",
    # Wartość ``--sort`` i ``--format`` w osobnym słowie nie jest nazwą tagu (#1414 r2 D2).
    "git tag --sort version:refname",
    "git tag --sort -version:refname | tail -3",
    "git tag --format '%(refname:short) %(creatordate:short)'",
    "git tag -n5",
    "git tag --merged origin/main",
    "git tag proba-123",
    "git tag -f u68-wip >/dev/null && git reset -q --hard origin/main",
    "git tag -f bez-linii 2> /dev/null; git push origin HEAD >>push.log 2>&1",
    "git push origin feat/x <<<v9.9.9",
    "git fetch origin --tags",
    "git log --oneline v0.8.0..HEAD",
    "git describe --tags",
    "git worktree add --detach ~/.t3/worktrees/wydanie-v0.9.0 abc",
    # Słowo programu jako argument albo w komentarzu nie jest poleceniem.
    "echo git tag v9.9.9",
    "rg -n gh\\ release tools/",
    "rg -n 'gh release|git tag' tools/ docs/",
    "# git tag v9.9.9",
    "git status # gh release create v9.9.9",
    "bash tools/skrypt.sh git tag v9.9.9",
    # Niezamknięty cudzysłów bez formy Wydania.
    "grep -n \"don't",
)


def _hook(stdin: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False, env=env
    )


def _without_release_tool() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name != repo.RELEASE_OVERRIDE}


def _bash(command: str, in_background: bool = False, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    tool_input = {"command": command, "description": "x", "run_in_background": in_background}
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input}
    return _hook(json.dumps(event), _without_release_tool() if env is None else env)


@pytest.mark.parametrize("in_background", [False, True], ids=["pierwszy-plan", "w-tle"])
@pytest.mark.parametrize("command", RELEASES)
def test_reczne_wydanie_dostaje_odmowe_z_droga_przez_narzedzie_wydan(command: str, in_background: bool) -> None:
    hooked = _bash(command, in_background)

    assert hooked.returncode == 2, hooked.stderr
    assert "skill wydanie" in hooked.stderr
    assert "tools/wydanie.py plan" in hooked.stderr
    assert "--no-verify" in hooked.stderr


@pytest.mark.parametrize("command", NOT_RELEASES)
def test_polecenie_obok_wydania_przechodzi_bez_slowa(command: str) -> None:
    hooked = _bash(command)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize("command", REVIEW_PROBES[:2])
def test_sesja_narzedzia_wydan_przechodzi_a_inna_wartosc_zmiennej_nie(command: str) -> None:
    released = _bash(command, env={**os.environ, repo.RELEASE_OVERRIDE: "1"})
    other = _bash(command, env={**os.environ, repo.RELEASE_OVERRIDE: "0"})

    assert (released.returncode, released.stderr) == (0, "")
    assert other.returncode == 2, other.stderr


@pytest.mark.parametrize(
    "stdin",
    ["", "nie json", "[]", '{"tool_input": null}', '{"tool_input": {"command": 5}}', '{"tool_name": "Bash"}', "[" * 1_000_000],
    ids=["pusto", "nie-json", "lista", "null", "liczba", "bez-polecenia", "gleboki-json"],
)
def test_nieczytelne_wejscie_hooka_przechodzi(stdin: str) -> None:
    hooked = _hook(stdin, _without_release_tool())

    assert (hooked.returncode, hooked.stdout) == (0, "")


def _configured(project: Path, command: str) -> list[subprocess.CompletedProcess[str]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    hooks = [hook for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]
    tool_input = {"command": command, "run_in_background": False}
    return [
        subprocess.run(
            hook["command"],
            shell=True,
            input=json.dumps({"tool_name": "Bash", "tool_input": tool_input}),
            env={**_without_release_tool(), "CLAUDE_PROJECT_DIR": str(project)},
            capture_output=True,
            text=True,
            check=False,
            timeout=hook["timeout"],
        )
        for hook in hooks
        if "reczne_wydanie.py" in hook["command"]
    ]


@POSIX_PYTHON3
@pytest.mark.parametrize("command", REVIEW_PROBES)
def test_ustawienia_projektu_odmawiaja_sond_wydania_z_przegladow(command: str) -> None:
    hooked = _configured(ROOT, command)

    assert [(run.returncode, "tools/wydanie.py plan" in run.stderr) for run in hooked] == [(2, True)]


@POSIX_PYTHON3
def test_checkout_bez_skryptu_hooka_wydan_nie_blokuje_basha(tmp_path: Path) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _configured(tmp_path, REVIEW_PROBES[0])

    assert [(run.returncode, run.stderr) for run in hooked] == [(0, "")]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("odmowa_wydania_hook", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


hook = _load()


@dataclass(frozen=True)
class Template:
    """Polecenie ze słowami argumentów, które powłoka czyta tak samo w każdym ujęciu w cudzysłów."""

    words: tuple[str, ...]
    release: bool

    def text(self, quotes: list[str], continuations: list[bool]) -> str:
        parts = []
        for index, word in enumerate(self.words):
            quote = quotes[index] if index < len(quotes) else ""
            needs_quote = quote or (" " in word and "'") or ""
            parts.append(needs_quote + word + needs_quote)
            if index + 1 < len(self.words):
                broken = index < len(continuations) and continuations[index]
                parts.append(" \\\n  " if broken else " ")
        return "".join(parts)


# Formy z docstringu hooka, także z wartością opcji ze spacją przed nazwą tagu albo adresem (#1414 r1 W1).
TEMPLATES = (
    Template(("gh", "release", "create", "v9.9.9", "--notes", "Co nowego"), True),
    Template(("gh", "release", "delete", "v0.8.0", "-y"), True),
    Template(("gh", "api", "-H", "Accept: application/vnd.github+json", "repos/o/r/releases", "-f", "tag_name=v9.9.9"), True),
    Template(("gh", "api", "-X", "POST", "-H", "X-GitHub-Api-Version: 2022-11-28", "repos/o/r/releases"), True),
    Template(("gh", "api", "repos/o/r/git/refs", "-f", "ref=refs/tags/v9.9.9", "-f", "sha=abc"), True),
    Template(("git", "push", "--no-verify", "-o", "ci skip", "origin", "v9.9.9"), True),
    Template(("git", "push", "origin", "+HEAD:refs/tags/v9.9.9"), True),
    Template(("git", "push", "origin", "--tags"), True),
    Template(("git", "tag", "-a", "-m", "Wydanie 9.9.9", "v9.9.9"), True),
    Template(("git", "tag", "-u", "klucz Maksa", "v9.9.9"), True),
    Template(("gh", "release", "view", "v0.8.0"), False),
    Template(("gh", "api", "-H", "Accept: application/vnd.github+json", "-X", "GET", "repos/o/r/releases"), False),
    Template(("gh", "api", "repos/o/r/git/refs", "-f", "ref=refs/heads/x", "-f", "sha=abc"), False),
    Template(("git", "push", "-o", "ci skip", "-u", "origin", "verify-centrum"), False),
    Template(("git", "tag", "-l", "-n", "v*"), False),
    Template(("git", "commit", "-m", "gh release create v9.9.9; git tag v9.9.9"), False),
)


@PROPERTY
@given(
    template=st.sampled_from(TEMPLATES),
    quotes=st.lists(st.sampled_from(("", "'", '"')), max_size=8),
    continuations=st.lists(st.booleans(), max_size=8),
)
def test_cudzyslow_i_lamanie_linii_nie_zmieniaja_werdyktu(
    template: Template, quotes: list[str], continuations: list[bool]
) -> None:
    command = template.text(quotes, continuations)

    assert shlex.split(command.replace("\\\n", "")) == list(template.words)
    assert hook.releases(command) is template.release


@PROPERTY
@given(template=st.sampled_from(TEMPLATES), program=st.sampled_from(("echo", "rg -n", "git commit -m")))
def test_forma_wydania_w_tekscie_argumentu_nie_jest_poleceniem(template: Template, program: str) -> None:
    text = " ".join(template.words)
    searched = f"{program} {shlex.quote(text)} wyniki.log"

    assert shlex.split(searched) == [*shlex.split(program), text, "wyniki.log"]
    assert hook.releases(searched) is False


@pytest.mark.skipif(sys.platform == "win32", reason="na Windows bash to zaślepka WSL, która bez dystrybucji pada")
@pytest.mark.parametrize("template", TEMPLATES, ids=lambda template: " ".join(template.words[:3]))
def test_szablony_wlasnosci_to_poprawne_polecenia_basha(template: Template) -> None:
    command = template.text(["'"] * len(template.words), [True] * len(template.words))

    assert subprocess.run(["bash", "-n", "-c", command], capture_output=True, check=False).returncode == 0
