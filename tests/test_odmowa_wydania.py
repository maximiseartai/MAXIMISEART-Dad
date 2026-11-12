"""Hook ``tools/hooks/reczne_wydanie.py``: agent nie zakłada tagu Wydania ``v*`` ani GitHub Release z Basha.

Formy Wydania to formy z docstringu hooka i sondy przeglądów #1403 r1 i #1414 r1–r4, a polecenia zwykłej pracy pochodzą
z historii agentów i z sond fałszywych odmów #1414 r1–r3. Konstrukcje spoza podzbioru i słowa Wydania pochodzą z docstringu
hooka: polecenie spoza podzbioru ze słowem Wydania dostaje odmowę, a bez niego przechodzi. Każdy test zachowania uruchamia
hook tak jak Claude Code: JSON na stdin, a odmowa to kod 2 z przyczyną na stderr. Własności Hypothesis biorą oczekiwanie
z docstringu hooka, a to, czym polecenie jest dla powłoki, rozstrzyga ``shlex.split`` i ``bash -n``, niezależne od hooka.
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
# Sondy #1414 r3 W1: podstawienie procesu to słowo, a polecenie biegnie dalej.
PROCESS_SUBSTITUTION_PROBES = (
    "git tag -a -F <(printf 'Wydanie\\n') v9.9.9",
    "git tag -F <(echo x) v9.9.9",
    "gh api --input <(jq -n '{tag_name:\"v9.9.9\"}') repos/o/r/releases",
    "gh api -X POST --input <(echo '{}') repos/o/r/releases",
    "git push -o <(echo x) origin v9.9.9",
)
RELEASES = (
    *REVIEW_PROBES,
    *SUBSTITUTION_PROBES,
    *PROCESS_SUBSTITUTION_PROBES,
    "git push origin v9.9.9 2> >(tee push.log)",
    # Podstawienie w cudzysłowie hook ocenia tak samo jak bez niego.
    'X="$(git tag v9.9.9)"',
    'echo "`git tag v9.9.9`"',
    "git tag $'v9.9.9'",
    "echo $'it\\'s'; git tag v9.9.9",
    # Komentarz w podstawieniu kończy się na nowej linii, a ``#`` za podstawieniem jest w środku słowa (#1414 r3 D2).
    "git push origin $(git rev-parse HEAD # it's\n):refs/tags/v9.9.9",
    "echo $(date)# x; git push origin $(git rev-parse HEAD):refs/tags/v9.9.9",
    # Nawias podpowłoki w podstawieniu go nie zamyka (#1414 r3 D3).
    "git push origin $( (git rev-parse HEAD) ):refs/tags/v9.9.9",
    # `` \` `` w `` `…` `` go nie zamyka (#1414 r3 D3): inaczej `` ` `` w komentarzu zamknąłby podstawienie, które
    # połyka refspec z nazwą bez słowa Wydania.
    "git tag -m `echo \\`date\\`` v9.9.9 # `",
    "git push origin `echo \\`git rev-parse HEAD\\``:v9 # `",
    # ``\\`` na końcu komentarza nie łączy linii (#1414 r2 D1), także w pierwszej linii polecenia (#1414 r3 D3).
    "# tag Wydania ręcznie \\\ngit tag v9.9.9",
    "echo start # krok \\\ngh release create v9.9.9 --generate-notes",
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
    "git update-ref refs/tags/v9.9.9 HEAD",
    "git update-ref -m x refs/tags/$T HEAD",
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
    # Spoza podzbioru ze słowem Wydania (#1414 r2 D1, r3 D1 i D2).
    'echo "niezamknięty; git tag v9.9.9',
    "git tag v9.9.9 'niezamknięty",
    "'gh' release create v9.9.9 \"niezamknięty",
    "echo $(\ngit tag v9.9.9",
    "$(which git) tag v9.9.9",
    "$(command -v gh) release create v9.9.9",
    "`which git` tag v9.9.9",
    "git $(echo tag) v9.9.9",
    "gh $(echo release) create v9.9.9",
    "g$(echo i)t tag v9.9.9",
    "G=git; $G tag v9.9.9",
    "$(which git) push origin v9.9.9",
    "git push origin $(case a in a) echo HEAD;; esac):refs/tags/v9.9.9",
    'git commit -m "$(echo "it\'s # done")" && git tag v9.9.9',
    "echo $((1<<2))\ngit tag v9.9.9",
    "echo 'a <<EOF'\ngit tag v9.9.9",
    "function f { git tag v9.9.9; }; f",
    "bash <<'EOF'\ngit tag v9.9.9",
    "echo v9.9.9 | xargs git tag",
    "gh api -X POST $URL -f tag_name=v9.9.9",
    # Słowo Wydania tuż za `` ` `` (#1414 r4 D1).
    "$G `echo tag`",
    # Rozwinięcie nawiasów, napis ANSI-C i locale oraz wzorzec ścieżek: bash i zsh robią z nich inne słowa (#1414 r4 W1).
    "git {tag,v9.9.9}",
    "git {tag,v9.9.9} -m x",
    "git {tag,v9.9.{9..9}}",
    "git push --no-verify origin {v9.9.9,}",
    "git push --no-verify origin HEAD:refs/tag{s/v9.9.9,}",
    "gh {release,create,v9.9.9} --generate-notes",
    "gh api repos/o/r/{releases,} -f tag_name=v9.9.9",
    "git push --no-verify origin $'v9.9.9'",
    "git push --no-verify origin HEAD:$'refs/tags/v9.9.9'",
    'git push --no-verify origin $"v9.9.9"',
    "git push --no-verify origin ?9.9.9",
    "git push origin v[9].9.9",
    # Opcja gita, której hook nie zna, alias z ``-c``, ``tags/`` w refspecu i ``--help`` jako wartość (#1414 r4 W2).
    "git --attr-source HEAD push --no-verify origin v9.9.9",
    "git --attr-source HEAD push --no-verify origin HEAD:refs/tags/v9.9.9",
    "git --attr-source HEAD tag v9.9.9",
    "git -c alias.p=push p --no-verify origin v9.9.9",
    "git -c alias.t=tag t v9.9.9",
    "git -c alias.t='!git tag' t v9.9.9",
    "git -c ALIAS.t=tag t v9.9.9",
    "git --config-env=alias.t=T t v9.9.9",
    "git push --no-verify origin tags/v9.9.9",
    "git push --no-verify origin HEAD:tags/v9.9.9",
    "gh release create v9.9.9 --notes --help",
    "gh release create v9.9.9 --title --help --generate-notes",
    "gh rc v9.9.9",
    # ``git`` i ``gh`` za innym programem (#1414 r4 D2) i zsh, który czyta tekst inaczej niż bash.
    "coproc git tag v9.9.9",
    "coproc T { git tag v9.9.9; }",
    "caffeinate git tag v9.9.9",
    "builtin command git tag v9.9.9",
    "X=git; env $X tag v9.9.9",
    "env ${X:-git} tag v9.9.9",
    "read X <<< git; env $X tag v9.9.9",
    "=git tag v9.9.9",
    "git (tag) v9.9.9",
    "for t (v9.9.9) git tag $t",
    "git push origin v<9-9>.9.9",
    "git push origin $x[1]",
    # Ciało heredoku bez cudzysłowu w ograniczniku: bash wykonuje w nim podstawienie.
    "cat <<EOF\n$(git tag v9.9.9)\nEOF",
    "cat <<EOF\n`git tag v9.9.9`\nEOF",
    # ``<<`` w komentarzu nie otwiera heredoku, więc linie za nim są poleceniem.
    "echo x # <<EOF\ngit tag v9.9.9\nEOF",
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
    # Podstawienie procesu i ``$(…)`` w cudzysłowie w zwykłej pracy (#1414 r3).
    "diff <(git show main:a.py) <(git show HEAD:a.py)",
    "while read t; do echo $t; done < <(git tag -l 'v*')",
    "git commit -m \"$(printf 'fix: don'\"'\"'t tag v9.9.9')\"",
    "gh api repos/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases --jq '.[0].tag_name'",
    "gh api graphql -f query='{ repository(owner:\"o\", name:\"r\") { releases(first:3) { nodes { tagName } } } }'",
    "echo $(( $(git rev-list --count HEAD) + 1 ))",
    "grep -n '^$' release_notes.py",
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
    "git update-ref -d refs/tags/v9.9.9",
    "git update-ref refs/heads/v9 HEAD",
    "git for-each-ref --format='delete %(refname)' refs/tags/v9 | git update-ref --stdin",
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
    # Napis z nazwą programu nie jest poleceniem, a słowo w komentarzu też nie.
    "rg -n gh\\ release tools/",
    "rg -n 'gh release|git tag' tools/ docs/",
    "# git tag v9.9.9",
    "git status # gh release create v9.9.9",
    # Niezamknięty cudzysłów bez formy Wydania.
    "grep -n \"don't",
    # Wzorzec ścieżek to słowo o nieznanej wartości: przy ``-l`` ``git tag`` tylko wypisuje.
    "git tag -l v*",
    "rg -n release tools/*.py",
    # Opcje gita i ``gh`` przed poleceniem, które hook zna (#1414 r4 D1), ``{nazwa}`` ``gh api`` i ``[[``.
    "git -C /x log --grep tag",
    "git --no-pager -c core.hooksPath=/dev/null log --grep release",
    "gh -R o/r pr list --search release",
    "gh api repos/{owner}/{repo}/releases --jq '.[0].tag_name'",
    "[[ -n $t ]] && git log --grep tag",
    "echo \"${t:-brak} ${#t} ${t##*/}\" tag",
    "time git log --grep release",
    "f() { git log --grep tag; }; f",
    "rg -n release .",
    "cat <<EOF\nWydanie: tag v9.9.9 i \\`git tag\\`\nEOF",
    # Ciało heredoku z ogranicznikiem w cudzysłowie to dane, także z ``$(…)``.
    "gh pr comment 1 --body-file - <<'EOF'\n$(git tag v9.9.9)\nEOF",
    "echo =====; git tag -l",
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


# Polecenia spoza podzbioru, który opisuje docstring hooka: tekst, którego hook nie czyta jak bash i zsh, ``git`` i ``gh``
# poza miejscem programu, powłoka i opcje oraz polecenia ``git`` i ``gh``, których hook nie zna. ``{}`` to miejsce
# słowa, a polecenie bez słowa Wydania przechodzi.
OUTSIDE_SUBSET = {
    "rozwinięcie nawiasów": "echo {a,b} {}",
    "ciąg w nawiasach": "echo {1..3} {}",
    "napis ANSI-C": "echo $'a' {}",
    "napis locale": 'echo $"a" {}',
    "arytmetyka": "echo $((1+2)) {}",
    "arytmetyka $[": "echo $[1+2] {}",
    "flaga zsh w ${}": "echo ${(f)x} {}",
    "przekształcenie ${x@P}": "echo ${x@P} {}",
    "znak sterujący": "echo a\x01b {}",
    "=program zsh": "=python3 -c 1 {}",
    "wzorzec liczb zsh": "ls {} <1-9>",
    "nawias w środku polecenia": "echo (a) {}",
    "for zsh z nawiasem": "for x (a) echo {}",
    "wzorzec case": "case x in x) echo {}; esac",
    "dwa operatory bez polecenia": "echo a;; echo {}",
    "tablica": "a=(x y); echo {}",
    "git za innym programem": "xargs git log {}",
    "gh za innym programem": "sudo gh pr view {}",
    "coproc": "coproc git log {}",
    "nazwa gita w przypisaniu": "X=git; echo {}",
    "nazwa gita w ${}": "echo ${X:-git} {}",
    "nazwa gita w celu przekierowania": "read X <<< git; echo {}",
    "bash": "bash -c 'echo {} x'",
    "sh": "sh -c 'echo {} x'",
    "zsh": "zsh -c 'echo {} x'",
    "dash": "dash -c 'echo {} x'",
    "ksh": "ksh -c 'echo {} x'",
    "powłoka za innym programem": "env bash -c 'echo {} x'",
    "eval": "eval 'echo {} x'",
    "trap": "trap 'echo {} x' EXIT",
    "source": "source ./skrypt.sh {}",
    ".": ". ./skrypt.sh {}",
    "alias": "alias l=ls; echo {}",
    "nieznana opcja gita": "git --frobnicate log {}",
    "alias gita z -c": "git -c alias.l=log l {}",
    "nieznane polecenie gita": "git frob {}",
    "nieznana opcja gh": "gh --frob pr view {}",
    "nieznane polecenie gh": "gh frob {}",
    "heredok z podstawieniem": "cat <<EOF\n$(date)\nEOF\necho {}",
    "<< w napisie": "echo '<<EOF'\necho {}\nEOF",
}
UNPARSED = {
    "niezamknięty cudzysłów": 'echo "a {} b',
    "niezamknięty apostrof": "echo {} 'x",
    "niezamknięte podstawienie": "echo $(echo {}",
    "niezamknięty `": "echo `echo {}",
    "niezamknięty heredok": "cat <<EOF\n{}",
    "\\ na końcu": "echo {} \\",
    "program ze zmiennej": "$PY skrypt.py {}",
    "program z podstawienia": "$(which python3) skrypt.py {}",
    "program ze wzorca": "./skrypt*.sh {}",
    "podpolecenie git ze zmiennej": "git $CMD {}",
    "podpolecenie gh z podstawienia": "gh $(echo pr) view {}",
    "gh api z zapisem na adres ze zmiennej": "gh api -X POST $URL -f body='a {} b'",
    "podstawienia głębiej niż MAX_DEPTH": "echo " + "$(echo " * 21 + "{}" + ")" * 21,
    "podstawienia głębiej niż stos Pythona": "echo " + "$(" * 2000 + "{}" + ")" * 2000,
}
# Słowa Wydania z docstringu hooka i słowa obok nich, które nim nie są (słowo w środku dłuższego, wersja bez kropki).
RELEASE_WORDS = (
    *("tag", "release", "v1.2", "x:v0.8", "tag_name=v1.2"),
    *("refs/tags/x", "repos/o/r/git/refs", "repos/o/r/releases", "--tags", "--follow-tags", "--mirror"),
)
NOT_RELEASE_WORDS = ("tagi", "tagów", "release_notes.py", "tag_name=x", "v080", "v3_dziennik", "--mirror-dir", "x")


@pytest.mark.parametrize("word", RELEASE_WORDS)
@pytest.mark.parametrize("template", [*OUTSIDE_SUBSET.values(), *UNPARSED.values()], ids=[*OUTSIDE_SUBSET, *UNPARSED])
def test_polecenie_spoza_podzbioru_ze_slowem_wydania_dostaje_odmowe(template: str, word: str) -> None:
    hooked = _bash(template.replace("{}", word))

    assert hooked.returncode == 2, hooked.stderr
    assert "zapisz je prościej albo rozbij na kilka poleceń" in hooked.stderr
    assert "tools/wydanie.py plan" in hooked.stderr


@pytest.mark.parametrize("word", NOT_RELEASE_WORDS)
@pytest.mark.parametrize("template", [*OUTSIDE_SUBSET.values(), *UNPARSED.values()], ids=[*OUTSIDE_SUBSET, *UNPARSED])
def test_polecenie_spoza_podzbioru_bez_slowa_wydania_przechodzi(template: str, word: str) -> None:
    hooked = _bash(template.replace("{}", word))

    assert (hooked.returncode, hooked.stderr) == (0, "")


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'EOF'\ngit tag v9.9.9 i gh release create v9.9.9\nEOF\n$PY skrypt.py",
        "$PY - <<'EOF'\nprint('tag', 'release')\nEOF",
    ],
    ids=["heredok-obok", "heredok-programu-ze-zmiennej"],
)
def test_slowo_wydania_w_zamknietym_heredoku_nie_liczy_sie_poza_podzbiorem(command: str) -> None:
    hooked = _bash(command)

    assert (hooked.returncode, hooked.stderr) == (0, "")


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
    assert (hook.refusal(command) is not None) is template.release


@PROPERTY
@given(template=st.sampled_from(TEMPLATES), program=st.sampled_from(("echo", "rg -n", "git commit -m")))
def test_forma_wydania_w_tekscie_argumentu_nie_jest_poleceniem(template: Template, program: str) -> None:
    text = " ".join(template.words)
    searched = f"{program} {shlex.quote(text)} wyniki.log"

    assert shlex.split(searched) == [*shlex.split(program), text, "wyniki.log"]
    assert hook.refusal(searched) is None


@pytest.mark.skipif(sys.platform == "win32", reason="na Windows bash to zaślepka WSL, która bez dystrybucji pada")
@pytest.mark.parametrize("template", TEMPLATES, ids=lambda template: " ".join(template.words[:3]))
def test_szablony_wlasnosci_to_poprawne_polecenia_basha(template: Template) -> None:
    command = template.text(["'"] * len(template.words), [True] * len(template.words))

    assert subprocess.run(["bash", "-n", "-c", command], capture_output=True, check=False).returncode == 0
