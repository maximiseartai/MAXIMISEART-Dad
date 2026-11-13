"""Hook ``tools/hooks/czekanie.py``: agent nie czeka blokująco na CI ani w pętli na ``pgrep -f`` i nie ponawia runu CI
z pominięciem ``tools/ponow_ci.py``.

Polecenia pochodzą z historii agentów z 20–25.10.2026 (``calls.jsonl`` pomiaru czasu narzędzi), a ponowienia z 5–11.11
(recall klasy K1 hillclimbu CI 12.11), skrócone tylko o ``cd`` do worktree, długie ścieżki i dopiski do notatek. Każdy test uruchamia hook tak jak Claude Code: JSON na stdin, a odmowa to
kod 2 z przyczyną na stderr.
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
    # Komentarz nie zakrywa pętli (sondy przeglądu #1487, runda 1 i 2; w ``${x:-{a} #b}`` zsh agenta liczy klamry).
    "echo $(date)#x && until gh pr checks 1 | grep -q pass; do sleep 30; done",
    "x=$(date)#; until gh pr checks 1 | grep -q pass; do sleep 30; done",
    "echo ${x:-{a} #b}; until gh pr checks 1 | grep -q pass; do sleep 30; done",
    # Runda 3: ``$'\'`` w komentarzu nie otwiera napisu, więc nie zjada następnej linii.
    "# $'\\'\nuntil gh pr checks 1 | grep -q pass; do sleep 30; done",
)
WATCHES = (
    "timeout 1500 gh pr checks 215 --watch > .audit/swarm-215/lane1-pr-checks.txt 2>&1; echo exit=$?",
    "timeout 540 gh pr checks 330 --watch --interval 60 2>&1 | tail -15; echo \"exit ${pipestatus[1]}\"",
    "timeout 580 gh run watch 40098178470 --exit-status > /dev/null 2>&1; echo rc=$?; "
    'gh pr checks 384 2>&1 | grep -v "pass" | head',
    "gh run watch 39930673572 --interval 30 --exit-status > /dev/null 2>&1; echo exit=$?; date -u +%T",
    # Komentarz za poleceniem nie zdejmuje odmowy z samego polecenia.
    "gh run watch 39930673572 --exit-status # do końca runu",
    # Sondy przeglądu #1487, runda 1 i 2: ``#``, za którym powłoka wykonuje polecenie.
    "x=$(date +%s)#; gh run watch 39930673572",
    "echo $((1+1))#; gh pr checks 1 --watch",
    "echo ${x:-{a} #b}; gh run watch 1",
    "[[ x =~ x|#b ]] && gh pr checks 1 --watch",
    # Runda 3: ``$'\'`` w komentarzu nie otwiera napisu, więc nie zjada następnej linii.
    "# $'\\'\ngh run watch 1",
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
# Dziewięć ponowień odbitych „already running” albo „cannot be rerun” (sesje d00be8d7, 41511ae6, e27ed100 ×2,
# 6bc1a081 ×4, 80f3de41) i partia 13 ponowień naraz w awarii DNS runnerów 11.11 (e27ed100, 22:38).
RERUNS = (
    "gh run rerun 41959078147 --job 127020944830 2>&1 | tail -2; echo rerun-requested",
    'gh run rerun 41940851666 --failed 2>&1 | tail -2; echo "rerun zlecony"',
    "gh run rerun --job 130564767610 2>&1 | tail -3",
    "for r in 43037317259 43033018567 43032850682 43034061364; do printf \"$r $(gh run view $r --json status,conclusion "
    "--jq '\"\\(.status)/\\(.conclusion)\"') \"; gh run rerun $r --failed 2>&1 | tail -1; echo; done",
    "gh run rerun 42431729670 --failed 2>&1 | tail -1",
    "gh run view 42431729670 --json status -q .status; gh run rerun 42431729670 --failed 2>&1 | tail -1",
    "gh run rerun 42435998596 --job 128594886949 2>&1 | tail -3; gh run view 42435998596 --json status,jobs --jq "
    "'.status, ([.jobs[]|select(.conclusion==\"failure\")|.name]|join(\", \"))'",
    "for j in 129008722489 129008722741; do gh api --allow-escape-sequences repos/maximiseartai/MAXIMISEART-Dad/actions/jobs/"
    "$j/logs 2>&1 | grep -E 'BŁĄD POBIERANIA|WYKONANIE FAIL' | head -2; done; gh run rerun 42571178441 --failed 2>&1 | tail -1",
    "gh run rerun 43035692960 --failed && echo rerun ok",
    "for r in 43033018567 43035363425 43037317259 43037329237 43037646710 43039417461 43039705347 43042271974 43044422686 "
    '43046293903 43050742878 43050791629 43052656424; do gh run rerun $r --failed && echo "rerun $r"; done',
    # Ta sama decyzja inną drogą: opcje ``gh`` przed poleceniem i między ``run`` a ``rerun`` oraz adres ponowienia
    # w ``gh api`` (sondy przeglądu #1459).
    "gh -R maximiseartai/MAXIMISEART-Dad run rerun 42003129295 --job 127163220031",
    "gh run -R maximiseartai/MAXIMISEART-Dad rerun 43035692960",
    "gh run --repo=maximiseartai/MAXIMISEART-Dad --debug rerun 43035692960",
    "gh 'run' \"rerun\" 43035692960",
    "gh api -X POST repos/maximiseartai/MAXIMISEART-Dad/actions/runs/43035189944/rerun-failed-jobs",
    "gh api --method POST repos/{owner}/{repo}/actions/jobs/130564767610/rerun",
    "gh api -X POST repos/o/r/actions/runs/1/attempts/1/rerun",
    'gh api -X POST "repos/o/r/actions/runs/$RUN/rerun-failed-jobs"',
    "/opt/homebrew/bin/gh run rerun 43035692960",
    # ``#`` w słowie, w cudzysłowie, za ukośnikiem albo w ciele heredoca nie zakrywa polecenia.
    "echo issue#1459 && gh run rerun 43035692960",
    'echo "#1459" && gh run rerun 43035692960',
    "echo ${#RUN} $# \\# && gh run rerun 43035692960",
    "cat <<'EOF' > notatka.md\n# Ponowienie\nEOF\ngh run rerun 43035692960",
    "a=#b; gh run rerun 1",
    "echo ${x#a}; gh run rerun 1",
    "echo a\\\n#x; gh run rerun 1",
    'echo "$(date)"#; gh run rerun 1',
    # Sondy przeglądów #1487 (rundy 1–3): ``#``, za którym bash albo zsh wykonuje polecenie; hook bez ucinania
    # komentarzy odmawia każdej z nich.
    "echo $(date +%s)#; gh run rerun 43035692960",
    "echo `date +%s`#; gh run rerun 43035692960",
    "echo `#x`; gh run rerun 1",
    "git log -1 --format=%h $(git rev-parse HEAD)#; gh run rerun 1",
    'echo "`echo " #"`"; gh run rerun 43035692960',
    "echo ${x:- #}; gh run rerun 1",
    "x=`echo #`; gh run rerun 1",
    "(( 1 #x )); gh run rerun 1",
    "echo $[ # ]; gh run rerun 1",
    "[[ a =~ (a #) ]]; gh run rerun 1",
    "echo a\\ #x; gh run rerun 1",
    'echo "${x:-" #"}"; gh run rerun 1',
    "echo $$'a\\'; gh run rerun 1\necho '",
    "echo ${x:-{} #}; gh run rerun 1",
    "echo $[ a[1] + ##x ]; gh run rerun 1",
    "a=(5); echo $[ a[1] + ##x ]; gh run rerun 1",
    "echo ${x:-[a] #b}; gh run rerun 1",
    "[[ $v =~ ^(ok|done)$|#x ]]; gh run rerun 1",
    # Runda 3: ``$'\'`` w komentarzu albo w bashowych backtickach nie otwiera napisu, więc nie zjada reszty polecenia.
    "# $'\\'\ngh run rerun 1",
    "# zobacz $'\\' w bashu\ngh run rerun 1",
    "true # $'\\'\ngh run rerun 1",
    "echo a #$'\\'\ngh run rerun 1",
    "echo `echo $'\\'`; gh run rerun 1",
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
    # Ponowienie przez narzędzie i ponowienie w prozie: opisie commitu i wzorcu wyszukiwania.
    ".venv/bin/python tools/ponow_ci.py 1303",
    "py -3 tools/ponow_ci.py --run 43035692960",
    'git commit -q -m "docs(agents): nie pisz gh run rerun, tylko tools/ponow_ci.py"',
    'rg -n "gh run rerun" docs/agents/pr-i-ci.md',
    "gh api repos/maximiseartai/MAXIMISEART-Dad/actions/runs/43035189944 --jq .run_attempt",
    "gh api repos/o/r/actions/runs/1 --jq .rerun_url",
    # Ścieżka ze słowem rerun, która nie jest adresem ponowienia Actions.
    "gh api repos/maximiseartai/MAXIMISEART-Dad/contents/tools/rerun.py",
    "gh api repos/maximiseartai/MAXIMISEART-Dad/branches/tools/rerun-ci",
    # Adres ponowienia liczy się tylko za ``gh api``: w argumencie innego polecenia ``gh`` to ścieżka pliku.
    "gh pr comment 1459 --body-file ~/.t3/notes/actions/runs/43035692960/rerun.md",
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


def _hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HOOK)], input=stdin, capture_output=True, text=True, check=False)


def _bash(command: str, in_background: bool = False) -> subprocess.CompletedProcess[str]:
    tool_input = {"command": command, "description": "x", "run_in_background": in_background}
    return _hook(json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": tool_input}))


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


@pytest.mark.parametrize("in_background", [False, True])
@pytest.mark.parametrize("command", RERUNS)
def test_ponowienie_runu_poza_ponow_ci_dostaje_odmowe_z_poleceniem_narzedzia(command: str, in_background: bool) -> None:
    hooked = _bash(command, in_background=in_background)

    assert hooked.returncode == 2, hooked.stderr
    assert "tools/ponow_ci.py N" in hooked.stderr
    assert "--run ID" in hooked.stderr


@pytest.mark.parametrize("command", PASSING)
def test_inne_polecenie_przechodzi_bez_slowa(command: str) -> None:
    hooked = _bash(command)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


@pytest.mark.parametrize("command", CI_LOOPS + WATCHES + PGREP_LOOPS)
def test_to_samo_czekanie_w_tle_przechodzi(command: str) -> None:
    hooked = _bash(command, in_background=True)

    assert (hooked.returncode, hooked.stdout, hooked.stderr) == (0, "", "")


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


def _configured(project: Path) -> list[subprocess.CompletedProcess[str]]:
    entries = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
    commands = [hook["command"] for entry in entries if entry["matcher"] == "Bash" for hook in entry["hooks"]]
    tool_input = {"command": PGREP_LOOPS[0], "run_in_background": False}
    return [
        subprocess.run(
            command,
            shell=True,
            input=json.dumps({"tool_name": "Bash", "tool_input": tool_input}),
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project)},
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
def test_checkout_bez_skryptu_hooka_nie_blokuje_basha(tmp_path: Path) -> None:
    # Sesja trzyma ustawienia ze startu, a checkout sprzed hooka nie ma skryptu; python3 bez pliku kończy się kodem 2.
    hooked = _configured(tmp_path)

    assert [(run.returncode, run.stderr) for run in hooked] == [(0, "")]
