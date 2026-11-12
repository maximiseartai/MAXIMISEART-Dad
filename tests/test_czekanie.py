"""Hook ``tools/hooks/czekanie.py``: agent nie czeka blokująco na CI ani w pętli na ``pgrep -f`` i nie robi Wydania ręcznie.

Polecenia czekania pochodzą z historii agentów z 20–25.10.2026 (``calls.jsonl`` pomiaru czasu narzędzi), skrócone
tylko o ``cd`` do worktree i o długie ścieżki; polecenia Wydania to formy z docstringu hooka i sondy z przeglądu #1403.
Każdy test uruchamia hook tak jak Claude Code: JSON na stdin, a odmowa to kod 2 z przyczyną na stderr.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tracemalloc

import pytest
import repo

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "tools" / "hooks" / "czekanie.py"
SETTINGS = ROOT / ".claude" / "settings.json"

CI_LOOPS = (
    "until s=$(gh pr checks 234 --json name,bucket 2>/dev/null) && [ -n \"$s\" ] && [ \"$s\" != \"[]\" ] && "
    "jq -e 'all(.bucket!=\"pending\")' <<<\"$s\" >/dev/null; do sleep 60; done; gh pr checks 234",
    'end=$((SECONDS+590)); while [ $SECONDS -lt $end ]; do s=$(gh pr checks 431 2>/dev/null | grep "^Required CI '
    'status" | cut -f2); [ -n "$s" ] && [ "$s" != pending ] && break; sleep 30; done; echo "required=$s"; '
    "gh pr checks 431 2>/dev/null | cut -f1,2 | sort -k2 | grep -v pass",
    "until ! gh pr checks 263 2>/dev/null | grep -q pending; do sleep 30; done; gh pr checks 263 2>&1 | cut -f1,2",
    'for i in $(seq 1 19); do n=$(gh pr checks 384 2>/dev/null | grep -c pending); [ "$n" -eq 0 ] && break; '
    'sleep 30; done; gh pr checks 384 2>&1 | grep -v "\\tpass\\t"',
    'for i in $(seq 1 10); do st=$(gh run view 40060154965 --json status -q .status); echo "$(date +%H:%M) $st"; '
    '[ "$st" = completed ] && break; sleep 28; done; gh pr checks 355 | grep -v pass',
    'until [ "$(gh run view 39959705242 --json status --jq .status 2>/dev/null)" = "completed" ]; do sleep 10; '
    "done; gh run view 39959705242 --json conclusion,headSha",
    "until c=$(gh run list --branch main --commit 5f6bbaa096e364da0c80672e948d90913c886683 --json "
    "status,conclusion --jq '.[0]|\"\\(.status) \\(.conclusion)\"') && [[ $c == completed* ]]; do sleep 30; done; "
    'echo "$c"',
    "until s=$(gh pr view 225 --json mergeable -q .mergeable); [ \"$s\" != \"UNKNOWN\" ] && "
    '[ "$s" != "CONFLICTING" ]; do sleep 15; done; gh pr view 225 --json mergeable,mergeStateStatus',
    'until [ "$(gh pr view 307 --json state --jq .state)" != "OPEN" ]; do sleep 30; done; '
    "gh pr view 307 --json state,mergedAt --jq '[.state,.mergedAt]|@tsv'",
    "for i in $(seq 1 56); do s=$(gh api repos/MAXIMISEART-AI/MAXIMISEART-Dad/commits/"
    "66f3e0301f6d6f965733d0e1c46baeb90d25c7b3/status --jq '.statuses[] | select(.context==\"Required CI status\") | "
    '.state\' 2>/dev/null | head -1); [ "$s" = success -o "$s" = failure ] && break; sleep 10; done',
    "perl -e 'alarm 570; exec @ARGV' bash -c 'until [ \"$(gh pr view 307 --json state --jq .state 2>/dev/null)\" = "
    '"MERGED" ]; do perl -e "select(undef,undef,undef,30)"; done\'; gh pr view 307 --json state,mergeCommit',
    'L=~/.claude/plugins/cache/pstack/skills/show-me-your-work/scripts/log.sh; $L wiersze.tsv ci "CI pytest/E2E '
    '3.11 czerwone" "Fix Root Causes" "run 39805093290" "push 087c55c, CI LOKALNIE OK"; sleep 30; '
    "until ! gh pr checks 282 2>/dev/null | grep -q pending; do sleep 30; done; gh pr checks 282 | cat",
    # Prawdziwe pętle z jednym zmienionym słowem: sen przez perl jak w pętlach na log i ``done`` jako argument.
    'for i in $(seq 1 19); do n=$(gh pr checks 384 2>/dev/null | grep -c pending); [ "$n" -eq 0 ] && break; '
    "perl -e 'select(undef,undef,undef,30)'; done",
    "until grep -q done $F && ! gh pr checks 282 2>/dev/null | grep -q pending; do sleep 30; done; "
    "gh pr checks 282 2>&1 | cat",
    'for i in 1 2 3 4 5 6 7 8; do o=$(gh pr checks 215 2>&1); if ! echo "$o" | grep -q pending; then break; fi; '
    'sleep 30; done; echo "$o" | cut -f1,2,3',
    # Syntetyczne: ``for`` z licznikiem prób bez ``break``, pętla przed ``&&``, pętla w ``"$(…)"`` z zagnieżdżonym
    # ``$(seq …)`` i pętla po ``then``.
    "for i in $(seq 1 20); do gh pr checks 1 | grep -c pending; sleep 30; done",
    "for i in {1..20}; do gh pr checks 1 | grep -c pending; sleep 30; done",
    "for ((i = 0; i < 20; i++)); do gh pr checks 1 | grep -c pending; sleep 30; done",
    "until ! gh pr checks 1 | grep -q pending; do sleep 30; done && gh pr checks 1",
    's="$(for i in $(seq 1 20); do gh pr checks 1 | grep -q pending || break; sleep 30; done; gh pr checks 1)"',
    "if gh pr view 1 --json state >/dev/null; then until ! gh pr checks 1 | grep -q pending; do sleep 30; done; fi",
    # Skrypt ``-c`` powłoki podanej ścieżką, z opcjami przed ``-c`` i w ``su``.
    "/bin/sh -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "bash -l -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "bash -lc 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "bash -o pipefail -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "su -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "runuser -l x -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "/bin/bash --noprofile --norc -o pipefail -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "bash -ce 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "fish -c 'while true; sleep 30; gh pr checks 1; end'",
    # Słowa przed ``-c`` mogą być dowolne, więc ``-c`` za nazwą skryptu też dostaje odmowę (fałszywą, ale tańszą).
    "bash skrypt.sh -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    # Powłoka tuż za separatorem albo nawiasem.
    "cd x;bash -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "for i in $(seq 20); do gh pr checks 1 | grep -c pending; sleep 30; done",
    "until [ $(for n in 1 2; do gh pr checks $n; done | grep -c pending) = 0 ]; do sleep 30; done",
    # Wyjście z pętli przez ``exit`` i ``return`` zamiast ``break``.
    "for i in 1 2 3 4 5 6 7 8; do gh pr checks 1 | grep -q pending || exit 0; sleep 30; done",
    "f() { for i in 1 2 3 4 5 6 7 8; do gh pr checks 1 | grep -q pending || return 0; sleep 30; done; }; f",
    # ``&>``, ``>&2`` i ``2>&1`` po ``done`` to przekierowania, nie pętla w tle.
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done &>/dev/null",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done &> ci.log; gh pr checks 446",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done >&2",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done > ci.log 2>&1 && gh pr checks 446",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done <&0",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done |& tee ci.log",
    # ``&`` za ``;`` albo nową linią puszcza w tło tylko następne polecenie.
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done; afplay /System/Library/Sounds/Glass.aiff &",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done\nafplay /System/Library/Sounds/Glass.aiff &",
    # ``&`` w grupie za potokiem puszcza w tło tylko tę grupę.
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done | (cat & wait)",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done | { tee ci.log & wait; }",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done | tee >(cat &)",
    # ``{`` bez zamknięcia jest argumentem, więc ``&`` na końcu nie puszcza w tło pętli za ``;``.
    "echo { a; until ! gh pr checks 446 | grep -q pending; do sleep 30; done; echo koniec &",
    # ``\&`` to znak, a nie tło.
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done | sed s/a/\\&/",
)
WATCHES = (
    "timeout 1500 gh pr checks 215 --watch > .audit/swarm-215/lane1-pr-checks.txt 2>&1; echo exit=$?",
    "timeout 540 gh pr checks 330 --watch --interval 60 2>&1 | tail -15; echo \"exit ${pipestatus[1]}\"",
    "timeout 580 gh run watch 40098178470 --exit-status > /dev/null 2>&1; echo rc=$?; "
    'gh pr checks 384 2>&1 | grep -v "pass" | head',
    "gh run watch 39930673572 --interval 30 --exit-status > /dev/null 2>&1; echo exit=$?; date -u +%T",
)
PGREP_LOOPS = (
    'until ! pgrep -f "tools/mutacje.py --plik ~/.t3/notes/arch-2026-10-24/K7/mutacje.json" >/dev/null; '
    "do sleep 20; done; tail -30 ~/.t3/notes/arch-2026-10-24/K7/mutacje.log",
    'until ! pgrep -f "mutacje-r2.json" >/dev/null; do sleep 20; done; '
    'grep -E "^(WYKRYTA|NIEWYKRYTA|MUTACJE)" ~/.t3/notes/arch-2026-10-24/K7/mutacje-r2.log',
    "until ! pgrep -f bench_k7.py >/dev/null && [ -s ~/.t3/notes/arch-2026-10-24/K7/bench.log ]; do sleep 15; "
    "done; tail -5 ~/.t3/notes/arch-2026-10-24/K7/bench.log | cut -c1-300",
    'until ! pgrep -f "gh pr checks 330" >/dev/null; do sleep 15; done; '
    "gh pr checks 330 --json name,bucket -q '.[] | select(.bucket != \"pass\") | .name'",
    'while pgrep -f "pytest -q$" >/dev/null 2>&1 && ! grep -q "passed\\|failed" .scratch/pytest-serial.txt; '
    "do sleep 15; done; tail -1 .scratch/pytest-serial.txt",
    "for i in $(seq 1 19); do pgrep -f mutacje_zmiany.py >/dev/null || break; sleep 30; done; "
    "tail -4 ~/.t3/notes/425/mutacje_zmiany.log",
    "until ! pgrep -l -f mutacje.json >/dev/null; do sleep 5; done",
    "until pgrep -f serve_centrum >/dev/null; do sleep 1; done; curl -s localhost:8765/health",
)
PASSING = (
    "gh pr checks 405 2>&1 | head -20",
    "gh pr checks 405 2>&1 | awk -F'\\t' '{print $1\": \"$2}'; git status --porcelain; git rev-parse HEAD; "
    "gh pr view 405 --json headRefOid -q .headRefOid",
    "gh run view 40129178560 --log-failed 2>&1 | tail -40",
    'until grep -q "^SZYBKO" ~/.t3/notes/noc-2026-10-24/U5/szybko2.log; do sleep 5; done; '
    "tail -6 ~/.t3/notes/noc-2026-10-24/U5/szybko2.log; git rev-parse HEAD; gh pr checks 356 2>&1 | head -20",
    "until grep -q DONE $f; do sleep 15; done; cat $f; gh pr view 439 --json comments "
    "--jq '.comments[]|.body|split(\"\\n\")[0]'",
    'until grep -q "^exit" .audit/swarm-214/ci_lokalnie.log; do sleep 5; done; tail -8 .audit/swarm-214/ci_lokalnie.log',
    "until grep -c \"exit\" /tmp/bench-204/before_after.log | grep -q '^12$'; do sleep 5; done; "
    "cat /tmp/bench-204/before_after.log",
    "timeout 580 sh -c 'until grep -qE \"^MUTACJE\" ~/.t3/notes/arch-2026-10-24/K7b/mutacje.log; do sleep 10; done'; "
    'grep -E "^MUTACJE" ~/.t3/notes/arch-2026-10-24/K7b/mutacje.log',
    "sleep 20; for p in 326 327; do gh pr view $p --json number,mergeable,mergeStateStatus "
    "--jq '\"\\(.number) \\(.mergeable) \\(.mergeStateStatus)\"'; done",
    "sleep 10; for n in 268 269 270 271 272 273 274 276; do gh issue view $n --json number,state "
    "--jq '\"\\(.number) \\(.state)\"'; done",
    'for p in $(pgrep -f "ci_lokalnie.py --do-pierwszego-bledu"); do echo $p; lsof -a -p $p -d cwd -Fn | tail -1; done',
    "pkill -f 'until ! pgrep -f \"ci_lokalnie.py --kazdy-commit\"'; pkill -f 'until grep -qE \"OK\\$|FAIL\"'; "
    'sleep 1; pgrep -fl "ci_lokalnie" || echo "nothing running"',
    'pgrep -lf "Microsoft Excel" ; echo "pgrep=$?"; uptime; '
    "while [ \"$(uptime | awk -F'load averages: ' '{print int($2)}')\" -gt 16 ]; do sleep 20; done; uptime",
    'pgrep -fl "serve_centrum|pytest" | cut -c1-150',
    "for i in $(seq 1 38); do grep -q \"end head round 1\" wydajnosc/przebieg.log && break; "
    "perl -e 'select(undef,undef,undef,15)'; done; cat wydajnosc/przebieg.log",
    "gh run list --branch main --workflow ci.yml -L 4 --json databaseId,status --jq "
    "'.[]|select(.status==\"completed\")|.databaseId' | head -2 | while read id; do gh run view $id --json "
    "jobs,headSha --jq '.headSha[:7]'; done",
    'bash $L .audit/204.tsv babysit "watching CI with gh pr checks --watch instead of watch-pr" '
    '"watch-pr needs bun, which is not installed" "/tmp/bench-204/checks.log" "open"',
    "sed -i '' 's/CI_STATUS_PLACEHOLDER/SUCCESS (zmierzone: `gh pr view 381 --json statusCheckRollup` po "
    "`gh pr checks --watch`)/' ~/.t3/notes/arch-2026-10-24/K6/RAPORT.md",
    "cat > ~/.t3/notes/uzupelnienie-415/418/r2/czekaj.sh <<'EOF'\n#!/bin/zsh\nH=a6246f973bbff04407eb8e6c26917cd527ca3a9d\n"
    "while true; do\n  r=$(gh pr checks 433 --json name,bucket --jq '.[]|select(.name==\"Required CI status\")|"
    ".bucket')\n  [ \"$r\" != pending ] && break\n  sleep 60\ndone\nEOF\nchmod +x ~/.t3/notes/uzupelnienie-415/418/r2/czekaj.sh",
    "git commit -q -m \"docs(agents): nie pisz until gh pr checks; do sleep 30; done, tylko watch_pull_request\"",
    'git -c user.name=v311 commit -q -m "until ! pgrep -f mutacje; do sleep 5; done wisi"',
    # Partie zapytań z sleep jako limitem API: ``for`` po liście i ``while read`` bez wyjścia z pętli i licznika.
    "for id in 39805093290 39772151111 39771042902 39601913795 39601190727; do sleep 2; gh run view $id --json "
    'jobs,headBranch,headSha --jq "(.headBranch) as \\$b | (.headSha[0:7]) as \\$s | .jobs[]|select(.conclusion=='
    '\\"failure\\")|\\"$id \\(\\$b) \\(\\$s) \\(.databaseId) \\(.name)\\"" || echo "$id ERR"; done | '
    "tee -a ~/.t3/notes/noc-2026-10-23/V293/joby-czerwone.txt",
    "for id in 39805093290 39772151111 39771042902 39601913795 39601190727; do sleep 2; gh api "
    '"repos/MAXIMISEART-AI/MAXIMISEART-Dad/actions/runs/$id/jobs?per_page=20" --jq ".jobs[]|select(.conclusion=='
    '\\"failure\\")|\\"$id \\(.head_branch) \\(.head_sha[0:7]) \\(.id) \\(.name)\\"" 2>&1 | head -5; gh api '
    '"repos/MAXIMISEART-AI/MAXIMISEART-Dad/actions/runs/$id" --jq \'"   run: \\(.head_branch) \\(.event) '
    '\\(.conclusion)"\' 2>&1 | head -2; done',
    "while read id ev br sha at; do grep -qx $id $V/.ok && continue; sleep 1; gh api "
    '"repos/MAXIMISEART-AI/MAXIMISEART-Dad/actions/runs/$id/jobs?per_page=100" --jq ".jobs[]|select(.conclusion=='
    '\\"failure\\")|\\"$id $br $sha \\(.id) \\(.name)\\"" || echo "$id ERR"; done < $V/runy-czerwone.txt',
    "for n in $(seq 247 264); do printf \"#%s \" $n; gh pr view $n --json isDraft,statusCheckRollup --jq "
    "'[.isDraft, ([.statusCheckRollup[]|.conclusion]|map(select(.!=\"SUCCESS\"))|length)]|@tsv'; done",
    "for n in $(seq 247 264); do sleep 1; gh pr view $n --json title; done",
    "for n in {247..264}; do sleep 1; gh pr view $n --json title; done",
    "i=444; while [ $i -le 446 ]; do gh pr view $i --json title; i=$((i + 1)); done",
    "while IFS= read -r id; do sleep 2; gh run view $id --json jobs; done < runy.txt",
    "for id in 39805093290 39772151111; do sleep 2; gh run view $id --json jobs; echo exit=$?; done",
    # Próbnik procesów puszczony ``&`` obok pomiaru i ubity ``kill``.
    "(while true; do echo \"$(date +%T) $(pgrep -fl 'serve_centrum|chrome-headless|pytest' | cut -c1-100 | "
    "tr '\\n' ' ')\"; sleep 5; done) > /tmp/wyd165-watch1.log 2>&1 & W=$!; .venv/bin/python "
    ".agents/skills/verify-centrum-rozliczen/scripts/run_centrum_verification.py --feature wydajnosc; kill $W",
    # Syntetyczne: pętla w tle na końcu polecenia, pętla zakończona przed ``sleep`` i wzorce wyszukiwania ze słowem pętli.
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done &",
    "(until ! gh pr checks 446 | grep -q pending; do sleep 30; done) &",
    # ``&`` za potokiem albo listą ``||`` puszcza w tło całą listę razem z pętlą.
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done 2>&1 | tee ci.log &",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done |& tee ci.log & W=$!",
    "until ! gh pr checks 446 | grep -q pending; do sleep 30; done || echo przerwane &",
    # ``&`` za grupą puszcza w tło całą grupę z pętlą.
    "{ until ! gh pr checks 446 | grep -q pending; do sleep 30; done; } &",
    "( until ! gh pr checks 446 | grep -q pending; do sleep 30; done; echo koniec ) > ci.log &",
    # Nawias wzorca ``case`` nie zamyka grupy.
    "case $1 in a) echo a;; esac; until ! gh pr checks 1 | grep -q pending; do sleep 30; done | tee ${LOG} &",
    "for f in a b; do echo $f; done; sleep 10; gh pr checks 1",
    # Samotne ``done`` po zamkniętej pętli nie zamyka jej drugi raz.
    "until test -f x; do echo; done; sleep 5; gh pr checks 1; done",
    "rg -n 'while|until' tools/hooks/czekanie.py; sleep 1; gh pr checks 446",
    'grep -nw "until" tools/hooks/czekanie.py; sleep 1; gh pr checks 446',
    "rg -n '(while)' tools/hooks/czekanie.py; sleep 1; gh pr checks 446",
    'grep -E "^(until)$" tools/hooks/czekanie.py; sleep 1; gh pr checks 446',
    # ``-c`` innego polecenia niż powłoka to nie skrypt: ``grep -c`` liczy wiersze z tym tekstem.
    "grep -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done' ~/.t3/notes/czekanie.log",
    # ``)`` wzorca ``case`` bez ``(`` przed nim zaczyna polecenie bez słowa powłoki, więc ``grep -c`` za nim też.
    "case $1 in a) grep -c 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done' ci.log;; esac",
    # Bez ``-c`` powłoka dostaje w napisie nazwę pliku skryptu albo jego argument.
    "sh -e 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
    "bash backup.sh 'until ! gh pr checks 1 | grep -q pending; do sleep 30; done'",
)

# Sondy przeglądu #1403 r1: obie przechodziły hook bez słowa.
REVIEW_PROBES = (
    "gh release create v9.9.9 --generate-notes",
    "gh api repos/maximiseartai/MAXIMISEART-Dad/git/refs -f ref=refs/tags/v9.9.9 -f sha=$(git rev-parse HEAD)",
)
RELEASES = (
    *REVIEW_PROBES,
    "gh-axi release create v1.0.0",
    "gh release -R maximiseartai/MAXIMISEART-Dad create v9.9.9 --notes x",
    "/opt/homebrew/bin/gh release create v9.9.9",
    "'gh' release create v9.9.9",
    "timeout 60 gh release create v9.9.9",
    "gh release edit v0.8.0 --draft=false",
    "gh release delete v0.8.0 -y",
    "gh release upload v0.8.0 notka.txt",
    "gh api -X POST repos/o/r/releases -f tag_name=v9.9.9",
    "gh api repos/o/r/releases -f tag_name=v9.9.9",
    "gh api --method=PATCH repos/o/r/releases/123 -F draft=false",
    "gh api -XDELETE repos/o/r/git/refs/tags/v0.8.0",
    "gh api repos/o/r/git/refs --input ref.json",
    "gh api repos/o/r/git/refs -F ref=@ref.txt -f sha=abc",
    "gh api repos/o/r/git/refs -f 'ref=refs/tags/v9.9.9' -f sha=abc",
    "gh api repos/o/r/git/refs -f ref=refs/tags/$TAG -f sha=abc",
    "git push --no-verify origin v9.9.9",
    "git push --no-verify origin refs/tags/v9.9.9",
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
    'git tag -am "Wydanie 9" v9.9.9 abc123',
    "git tag -f v0.8.0 HEAD",
    "git tag -mdone v9.9.9",
    "git tag -amdone v9.9.9",
    "git tag refs/tags/v9.9.9",
    "git tag $TAG",
    'git tag -s "v9.9.9"',
    "cd x && git tag v9.9.9 && git push --no-verify origin v9.9.9",
    "bash -c 'gh release create v9.9.9'",
    "echo $(git tag v9.9.9)",
    "echo `git tag v9.9.9`",
    "git tag v9.9.9 >/dev/null 2>&1",
)
NOT_RELEASES = (
    "gh pr create --title x --body-file - <<'EOF'\nOdmawia gh release create v9.9.9 i git tag v9.9.9\nEOF",
    "git commit -m 'hook odmawia gh release create v9.9.9 i git push --tags'",
    "git push -u origin chore/guard-release-tags",
    "git push origin HEAD",
    "git push --force-with-lease origin HEAD:refs/heads/x",
    "git push origin verify-centrum",
    "git push origin $BRANCH",
    ".venv/bin/python tools/wydanie.py plan --plik ~/.t3/notes/wydanie/plan.json",
    ".venv/bin/python tools/wydanie.py wydaj --plan p.json --co-nowego c.txt --potwierdzam",
    "gh release list",
    "gh release view v0.8.0",
    "gh release -R maximiseartai/MAXIMISEART-Dad view v0.8.0",
    "gh release 'view' v0.8.0",
    "gh release download v0.8.0",
    "gh release --help",
    "gh api repos/o/r/releases/latest --jq .tag_name",
    "gh api -X GET repos/o/r/releases -f per_page=5",
    "gh api --method=GET repos/o/r/releases -f per_page=5",
    "gh api repos/o/r/git/refs -f ref=refs/heads/x -f sha=abc",
    "gh api repos/o/r/issues/1/comments -f body=x",
    "git tag",
    "git tag -l 'v*'",
    "git tag --list v*",
    "git tag -d v9.9.9",
    "git tag --contains HEAD",
    "git tag --sort=-creatordate | head",
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
)


def _hook(stdin: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False, env=env
    )


def _bash(
    command: str, in_background: bool = False, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    tool_input = {"command": command, "description": "x", "run_in_background": in_background}
    return _hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input}), env)


def _without_release_tool() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name != repo.RELEASE_OVERRIDE}


@pytest.mark.parametrize("command", CI_LOOPS + WATCHES)
def test_czekanie_na_ci_na_pierwszym_planie_dostaje_odmowe_z_droga_przez_powiadomienie(command: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert "pełny SHA" in hooked.stderr
    assert "watch_pull_request" in hooked.stderr
    assert "run_in_background: true" in hooked.stderr
    assert "t3_background_wait" in hooked.stderr


@pytest.mark.parametrize("command", PGREP_LOOPS)
def test_petla_na_pgrep_dostaje_odmowe_z_powiadomieniem_zadania_w_tle(command: str) -> None:
    hooked = _bash(command)

    assert hooked.returncode == 2, hooked.stderr
    assert "pgrep -f znajduje własną powłokę" in hooked.stderr
    assert "run_in_background: true" in hooked.stderr
    assert "t3_background_wait" in hooked.stderr


@pytest.mark.parametrize("command", PASSING)
def test_inne_polecenie_przechodzi_bez_slowa(command: str) -> None:
    hooked = _bash(command)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize("command", CI_LOOPS + WATCHES + PGREP_LOOPS)
def test_to_samo_czekanie_w_tle_przechodzi(command: str) -> None:
    hooked = _bash(command, in_background=True)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize("in_background", [False, True], ids=["pierwszy-plan", "w-tle"])
@pytest.mark.parametrize("command", RELEASES)
def test_reczne_wydanie_dostaje_odmowe_z_droga_przez_narzedzie_wydan(command: str, in_background: bool) -> None:
    hooked = _bash(command, in_background, env=_without_release_tool())

    assert hooked.returncode == 2, hooked.stderr
    assert "skill wydanie" in hooked.stderr
    assert "tools/wydanie.py plan" in hooked.stderr
    assert "--no-verify" in hooked.stderr


@pytest.mark.parametrize("command", NOT_RELEASES)
def test_polecenie_obok_wydania_przechodzi_bez_slowa(command: str) -> None:
    hooked = _bash(command, env=_without_release_tool())

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize("command", REVIEW_PROBES)
def test_sesja_narzedzia_wydan_przechodzi_a_inna_wartosc_zmiennej_nie(command: str) -> None:
    released = _bash(command, env={**os.environ, repo.RELEASE_OVERRIDE: "1"})
    other = _bash(command, env={**os.environ, repo.RELEASE_OVERRIDE: "0"})

    assert (released.returncode, released.stderr) == (0, "")
    assert other.returncode == 2, other.stderr


def test_sesja_narzedzia_wydan_dalej_nie_czeka_na_ci() -> None:
    hooked = _bash(f"gh release create v9.9.9; {CI_LOOPS[0]}", env={**os.environ, repo.RELEASE_OVERRIDE: "1"})

    assert hooked.returncode == 2
    assert "watch_pull_request" in hooked.stderr


def _configured_timeout() -> float:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    (timeout,) = [hook["timeout"] for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]
    return float(timeout)


def test_limit_hooka_w_ustawieniach_opoznia_polecenie_najwyzej_o_10_s() -> None:
    # Claude Code po limicie puszcza polecenie bez oceny, więc limit to najdłuższe opóźnienie każdego Basha.
    assert 0 < _configured_timeout() <= 10


@pytest.mark.parametrize(
    "command",
    [
        # Wzorzec z zagnieżdżonymi kwantyfikatorami cofa się wykładniczo po ``2>1 2>1 …`` (48 znaków to 14 s).
        "while :; do sleep 1; gh pr checks 1; done " + "2>1" * 2000,
        # Szukanie ``done``, końca listy albo ``&`` od każdej pętli osobno rośnie z kwadratem liczby pętli.
        "until x; do " * 40000 + "sleep 1; gh pr checks 1",
        "until a& do b& done&" * 40000 + "while :; do sleep 1; gh pr checks 1; done",
        "(until x do done)" * 40000 + "(while :; do sleep 1; gh pr checks 1; done)",
        # Ciało każdej pętli przeszukane osobno: pętle zagnieżdżone i niezamknięte razem rosną z kwadratem długości.
        "until x; do " * 40000 + "done; " * 40000 + "while :; do sleep 1; gh pr checks 1; done",
        # Wzorzec, który od każdego wiersza albo każdego ``gh pr checks`` czyta do końca polecenia.
        "while :; do sleep 1; gh pr checks 1; done" + "\n" * 400000,
        "gh pr checks 1 " * 40000 + "\nwhile :; do sleep 1; gh pr checks 1; done",
        "until x; do sleep 1; " + "gh api x " * 40000 + "\ngh pr checks 1; done",
    ],
    ids=[
        "ogon-przekierowan",
        "petle-bez-done",
        "petle-w-tle-bez-srednika",
        "petle-bez-konca-listy",
        "zagniezdzone-bez-sleep",
        "puste-wiersze",
        "zapytania-bez-watch",
        "gh-api-bez-adresu",
    ],
)
def test_hook_ocenia_wejscie_bez_konca_przed_limitem_z_ustawien(command: str) -> None:
    tool_input = {"command": command, "run_in_background": False}

    hooked = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_input": tool_input}),
        capture_output=True,
        text=True,
        check=False,
        timeout=_configured_timeout(),
    )

    assert hooked.returncode == 2, hooked.stderr


def test_hook_trzyma_w_pamieci_jedno_cialo_petli_naraz(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ciała 2000 zagnieżdżonych pętli to razem 24 MB, a 40 000 to 10 GB, których runner Windows nie ma.
    spec = importlib.util.spec_from_file_location("czekanie", HOOK)
    assert spec is not None and spec.loader is not None
    hook = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, hook)
    spec.loader.exec_module(hook)
    command = "until x; do " * 2000 + "sleep 1; gh pr checks 1"

    tracemalloc.start()
    try:
        refusal = hook.judge(command, in_background=False)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert refusal is not None
    assert peak < 100 * len(command)


@pytest.mark.parametrize(
    "stdin",
    [
        "",
        "nie json",
        "[]",
        '{"tool_input": null}',
        '{"tool_input": {"command": 5}}',
        '{"tool_name": "Bash"}',
        # Zagnieżdżenie głębsze niż stos Pythona: w JSON-ie i w poleceniu (``"$(`` w ``"$(`` …). Na Pythonie 3.14
        # runnera CI 100 000 ``[`` kończy się ``ValueError`` na końcu wejścia, nie ``RecursionError`` (#694), a milion
        # przepełnia stos przy każdym skończonym limicie do ok. 140 MB (ok. 144 B stosu na poziom); przy ``ulimit -s
        # unlimited`` na Linuksie mieści się na stosie, kończy ``ValueError``, i test nie odróżnia hooka bez
        # ``RecursionError``. Żadne zadanie CI nie zdejmuje limitu stosu.
        "[" * 1_000_000,
        json.dumps({"tool_input": {"command": '"$(' * 1000 + "until ! gh pr checks 1; do sleep 30; done"}}),
    ],
    ids=["pusto", "nie-json", "lista", "null", "liczba", "bez-polecenia", "gleboki-json", "gleboki-cudzyslow"],
)
def test_nieczytelne_wejscie_hooka_przechodzi(stdin: str) -> None:
    hooked = _hook(stdin)

    assert (hooked.returncode, hooked.stdout) == (0, "")


@pytest.mark.skipif(sys.platform == "win32", reason="zamknięte stdin daje tu sh, którego Windows nie ma")
def test_hook_bez_stdin_przechodzi() -> None:
    # Python bez deskryptora 0 ma ``sys.stdin = None``, a ``json.load(None)`` rzuca ``AttributeError``.
    hooked = subprocess.run(
        ["sh", "-c", 'exec "$0" "$1" <&-', sys.executable, str(HOOK)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


def _configured(project: Path, bash: str = PGREP_LOOPS[0]) -> list[subprocess.CompletedProcess[str]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [hook["command"] for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]
    tool_input = {"command": bash, "run_in_background": False}
    return [
        subprocess.run(
            command,
            shell=True,
            input=json.dumps({"tool_name": "Bash", "tool_input": tool_input}),
            env={**_without_release_tool(), "CLAUDE_PROJECT_DIR": str(project)},
            capture_output=True,
            text=True,
            check=False,
        )
        for command in commands
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_ustawienia_projektu_wpinaja_hook_dla_basha() -> None:
    hooked = _configured(ROOT)

    assert [(run.returncode, "pgrep -f" in run.stderr) for run in hooked] == [(2, True)]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
@pytest.mark.parametrize("command", REVIEW_PROBES)
def test_ustawienia_projektu_odmawiaja_sond_wydania_z_przegladu(command: str) -> None:
    hooked = _configured(ROOT, command)

    assert [(run.returncode, "tools/wydanie.py" in run.stderr) for run in hooked] == [(2, True)]


@pytest.mark.skipif(sys.platform == "win32", reason="python3 na Windows bywa aliasem Microsoft Store")
def test_checkout_bez_skryptu_hooka_nie_blokuje_basha(tmp_path: Path) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _configured(tmp_path)

    assert [(run.returncode, run.stderr) for run in hooked] == [(0, "")]
