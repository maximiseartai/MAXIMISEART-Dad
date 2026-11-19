#!/usr/bin/env python3
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
import os
import re
import sys
from typing import Optional

MENTIONS = re.compile(r"\bkill\b|pkill|killall|pgrep")
NAMED_BY_PATTERN = re.compile(r"pkill|killall|pgrep")
SUBSTITUTION = "\x00"
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
KEYWORDS = frozenset(
    {
        "if",
        "then",
        "else",
        "elif",
        "do",
        "while",
        "until",
        "!",
        "{",
        "}",
        "fi",
        "done",
        "esac",
    }
)
WRAPPERS = frozenset(
    {
        "sudo",
        "doas",
        "env",
        "nohup",
        "timeout",
        "gtimeout",
        "nice",
        "xargs",
        "command",
        "builtin",
        "exec",
        "caffeinate",
        "time",
        "stdbuf",
    }
)
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
KILLERS = frozenset({"pkill", "killall"})
INTERESTING = KILLERS | SHELLS | {"kill", "pgrep", "eval", "trap"}
SCRIPT_OPTION = re.compile(r"-[A-Za-z]*c[A-Za-z]*")
KILL_WITHOUT_SIGNAL = frozenset({"-0", "-l", "-L"})
SIGNAL = re.compile(r"-(?:\d+|(?:SIG)?[A-Z]{2,}[A-Z0-9+-]*)")
WIDENING = re.compile(r"[|()]|\$(?!\Z)")
LITERAL_PID = re.compile(r"\d+|%(?:\d+|%|\+|-)")
BRACKET = re.compile(r"\[\^?\]?[^\]]*\]")


@dataclass(frozen=True)
class Options:
    flags: str
    values: str
    pattern_values: str
    long_flags: frozenset[str]
    long_values: frozenset[str]
    inverting: frozenset[str]


# ZEWNĘTRZNE: opcje pgrep/pkill macOS i procps-ng oraz killall macOS i psmisc (man pgrep, man killall)
PGREP_OPTIONS = Options(
    flags="aAcefHIiLlnoqwx",
    values="dFgGjMNOPQrstuU",
    pattern_values="",
    long_flags=frozenset(
        {
            "--full",
            "--exact",
            "--newest",
            "--oldest",
            "--echo",
            "--count",
            "--ignore-case",
            "--list-name",
            "--list-full",
        }
    ),
    long_values=frozenset(
        {
            "--signal",
            "--parent",
            "--euid",
            "--uid",
            "--group",
            "--pgroup",
            "--session",
            "--terminal",
            "--pidfile",
            "--older",
            "--delimiter",
        }
    ),
    inverting=frozenset({"-v", "--inverse"}),
)
KILLALL_OPTIONS = Options(
    flags="deEgiIlmqrsvwz",
    values="cnotuyZ",
    pattern_values="c",
    long_flags=frozenset(
        {
            "--exact",
            "--ignore-case",
            "--process-group",
            "--interactive",
            "--quiet",
            "--regexp",
            "--verbose",
            "--wait",
        }
    ),
    long_values=frozenset(
        {"--signal", "--user", "--older-than", "--younger-than", "--ns", "--context"}
    ),
    inverting=frozenset(),
)


@dataclass(frozen=True)
class Refusal:
    reason: str


@dataclass(frozen=True)
class Word:
    text: str
    substituted: bool


@dataclass(frozen=True)
class Call:
    name: str
    arguments: tuple[Word, ...]


class Unreadable(Exception):
    pass


def _allowed(project: str) -> str:
    return (
        "Zatrzymaj proces po swoim: TaskStop z ID zadania w tle; kill PID-u zapisanego przy starcie "
        '(polecenie & echo $! > plik.pid, potem kill "$(cat plik.pid)"); albo pkill -f z jednym wzorcem, który zawiera '
        f"absolutną ścieżkę tego worktree, np. pkill -f '{project}/tools/szybko.py'."
    )


class _Scan:
    def __init__(self, text: str, found: list[list[Word]]) -> None:
        self.text, self.found = text, found
        self.command: list[Word] = []
        self.chars: Optional[list[str]] = None
        self.substituted = False
        self.redirect = False
        self.heredocs: list[str] = []

    def scan(self, index: int, nested: bool) -> int:
        text, depth = self.text, 0
        while index < len(text):
            char = text[index]
            if char == "\\":
                if text[index + 1 : index + 2] != "\n":
                    self._char(text[index + 1 : index + 2])
                index += 2
            elif char == "'":
                end = text.find("'", index + 1)
                if end < 0:
                    raise Unreadable
                self._char(text[index + 1 : end])
                index = end + 1
            elif char == '"':
                index = self._double(index + 1)
            elif text.startswith("$(", index):
                index = self._substitution(index + 2)
            elif char == "`":
                index = self._backtick(index + 1)
            elif char == "#" and self.chars is None:
                end = text.find("\n", index)
                index = len(text) if end < 0 else end
            elif char in " \t":
                self._end_word()
                index += 1
            elif char == "\n":
                self._end_command()
                index = self._skip_heredocs(index + 1)
            elif char in "<>":
                index = self._redirection(index)
            elif char in ";&|(":
                self._end_command()
                depth += char == "("
                index += 1
            elif char == ")":
                self._end_command()
                if nested and depth == 0:
                    return index + 1
                depth = max(depth - 1, 0)
                index += 1
            else:
                self._char(char)
                index += 1
        if nested:
            raise Unreadable
        self._end_command()
        return index

    def _char(self, text: str) -> None:
        if self.chars is None:
            self.chars = []
        self.chars.append(text)

    def _end_word(self) -> None:
        if self.chars is not None:
            if self.redirect:
                self.redirect = False
            else:
                self.command.append(Word("".join(self.chars), self.substituted))
        self.chars, self.substituted = None, False

    def _end_command(self) -> None:
        self._end_word()
        if self.command:
            self.found.append(self.command)
        self.command = []

    def _double(self, index: int) -> int:
        text = self.text
        self._char("")
        while index < len(text):
            char = text[index]
            if char == '"':
                return index + 1
            if char == "\\":
                following = text[index + 1 : index + 2]
                if following in ("$", "`", '"', "\\"):
                    self._char(following)
                elif following != "\n":
                    self._char("\\" + following)
                index += 2
            elif text.startswith("$(", index):
                index = self._substitution(index + 2)
            elif char == "`":
                index = self._backtick(index + 1)
            else:
                self._char(char)
                index += 1
        raise Unreadable

    def _substitution(self, index: int) -> int:
        end = _Scan(self.text, self.found).scan(index, nested=True)
        self._char(SUBSTITUTION)
        self.substituted = True
        return end

    def _backtick(self, index: int) -> int:
        text, end = self.text, index
        while end < len(text) and text[end] != "`":
            end += 2 if text[end] == "\\" else 1
        if end >= len(text):
            raise Unreadable
        script = text[index:end].replace("\\`", "`")
        _Scan(script, self.found).scan(0, nested=False)
        self._char(SUBSTITUTION)
        self.substituted = True
        return end + 1

    def _redirection(self, index: int) -> int:
        text = self.text
        if (
            self.chars is not None
            and "".join(self.chars).isdigit()
            and not self.substituted
        ):
            self.chars = None
        self._end_word()
        if text.startswith("<<<", index):
            self.redirect = True
            return index + 3
        if text.startswith("<<", index):
            return self._heredoc(index + 2)
        if text[index + 1 : index + 2] == "(":
            return self._substitution(index + 2)
        while index < len(text) and text[index] in "<>&|":
            index += 1
        if (
            text[index - 1] == "&"
            and index < len(text)
            and (text[index].isdigit() or text[index] == "-")
        ):
            return index + 1
        self.redirect = True
        return index

    def _heredoc(self, index: int) -> int:
        text = self.text
        if text.startswith("-", index):
            index += 1
        while index < len(text) and text[index] in " \t":
            index += 1
        start = index
        while index < len(text) and text[index] not in " \t\n;&|()<>":
            index += 1
        self.heredocs.append(re.sub(r"[\"'\\]", "", text[start:index]))
        return index

    def _skip_heredocs(self, index: int) -> int:
        text = self.text
        for delimiter in self.heredocs:
            while index < len(text):
                end = text.find("\n", index)
                line = text[index:] if end < 0 else text[index:end]
                index = len(text) if end < 0 else end + 1
                if line.strip() == delimiter:
                    break
        self.heredocs = []
        return index


def _program(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _calls(command: str) -> Iterator[Call]:
    found: list[list[Word]] = []
    _Scan(command, found).scan(0, nested=False)
    for words in found:
        call = _call(words)
        if call is None:
            continue
        name, arguments = call
        if name == "eval":
            yield from _calls(" ".join(word.text for word in arguments))
        elif name == "trap":
            if arguments and not arguments[0].text.startswith("-"):
                yield from _calls(arguments[0].text)
        elif name in SHELLS:
            for option, script in zip(arguments, arguments[1:]):
                if SCRIPT_OPTION.fullmatch(option.text):
                    yield from _calls(script.text)
                    break
        else:
            yield Call(name, tuple(arguments))


def _call(words: list[Word]) -> Optional[tuple[str, list[Word]]]:
    index = 0
    while index < len(words) and (
        words[index].text in KEYWORDS or ASSIGNMENT.match(words[index].text)
    ):
        index += 1
    if index == len(words):
        return None
    name = _program(words[index].text)
    if name in WRAPPERS:
        for later in range(index + 1, len(words)):
            if _program(words[later].text) in INTERESTING:
                return _program(words[later].text), words[later + 1 :]
        return None
    return (name, words[index + 1 :]) if name in INTERESTING else None


def _patterns(name: str, texts: list[str]) -> tuple[list[str], Optional[str]]:
    options = KILLALL_OPTIONS if name == "killall" else PGREP_OPTIONS
    patterns: list[str] = []
    index, operands_only = 0, False
    while index < len(texts):
        text = texts[index]
        index += 1
        if operands_only or not text.startswith("-") or text == "-":
            patterns.append(text)
        elif text == "--":
            operands_only = True
        elif SIGNAL.fullmatch(text):
            continue
        elif text.startswith("--"):
            key = text.split("=", 1)[0]
            if key in options.inverting:
                return (
                    patterns,
                    f"z {key} zabija każdy proces, który do wzorca nie pasuje, czyli procesy innych wątków.",
                )
            if key in options.long_values and "=" not in text:
                index += 1
            elif key not in options.long_flags | options.long_values:
                return (
                    patterns,
                    f"z opcją {text}, której hook nie zna, więc nie wie, co zabije.",
                )
        else:
            for position, letter in enumerate(text[1:], start=1):
                if f"-{letter}" in options.inverting:
                    return (
                        patterns,
                        f"z -{letter} zabija każdy proces, który do wzorca nie pasuje, czyli procesy innych wątków.",
                    )
                if letter in options.flags:
                    continue
                if letter not in options.values:
                    return (
                        patterns,
                        f"z opcją {text}, której hook nie zna, więc nie wie, co zabije.",
                    )
                value = text[position + 1 :]
                if not value:
                    value = texts[index] if index < len(texts) else ""
                    index += 1
                if letter in options.pattern_values:
                    patterns.append(value)
                break
    return patterns, None


def _problem(call: Call, project: Optional[str]) -> Optional[str]:
    shown = (
        "pgrep obok kill PID-u ze zmiennej, z podstawienia albo z wejścia"
        if call.name == "pgrep"
        else call.name
    )
    if any(word.substituted for word in call.arguments):
        return (
            f"{shown} z podstawieniem $(…) albo `…` w argumentach: puste podstawienie (np. pgrep bez wyniku) zostawia "
            "wzorzec, który trafia w procesy innych wątków na wspólnym Macu."
        )
    patterns, option = _patterns(call.name, [word.text for word in call.arguments])
    if option is not None:
        return f"{shown} {option}"
    if len(patterns) != 1:
        return f"{shown} bez wzorca albo z więcej niż jednym wzorcem zabija procesy spoza tego worktree."
    (pattern,) = patterns
    if WIDENING.search(pattern):
        return (
            f"wzorzec {shown} ze zmienną ($…) albo z |, (, ) może trafić w procesy spoza tego worktree, "
            "więc wpisz ścieżkę worktree wprost."
        )
    inside = (
        project is not None
        and re.search(
            re.escape(project) + r"(?:/|\$?\Z)", BRACKET.sub(SUBSTITUTION, pattern)
        )
        is not None
    )
    if not inside:
        return (
            f"wzorzec {shown} bez absolutnej ścieżki tego worktree ({project or '$CLAUDE_PROJECT_DIR'}) trafia w procesy "
            "innych wątków na wspólnym Macu."
        )
    return None


def _kill_targets(call: Call) -> Optional[list[Word]]:
    if call.name != "kill":
        return None
    arguments = list(call.arguments)
    texts = [word.text for word in arguments]
    if (texts[:1] and texts[0] in KILL_WITHOUT_SIGNAL) or texts[:2] == ["-s", "0"]:
        return None
    if texts[:1] in (["-s"], ["-n"]):
        arguments = arguments[2:]
    elif texts[:1] and texts[0].startswith("-") and texts[0] != "--":
        arguments = arguments[1:]
    if arguments[:1] and arguments[0].text == "--":
        arguments = arguments[1:]
    return arguments


def _pid_from_elsewhere(targets: list[Word]) -> bool:
    return not targets or any(
        word.substituted or not LITERAL_PID.fullmatch(word.text) for word in targets
    )


def judge(command: str, project: Optional[str]) -> Optional[Refusal]:
    if not MENTIONS.search(command):
        return None
    if project is not None:
        project = project.rstrip("/")
        if not project.startswith("/"):
            project = None
    shown = project or "$CLAUDE_PROJECT_DIR"
    try:
        calls = list(_calls(command))
    except (Unreadable, RecursionError):
        if not NAMED_BY_PATTERN.search(command):
            return None
        return Refusal(
            "Odmowa: polecenia z pkill, killall albo pgrep nie da się odczytać (niezamknięty cudzysłów albo podstawienie). "
            + _allowed(shown)
        )
    kills = [targets for targets in map(_kill_targets, calls) if targets is not None]
    if any(word.text.startswith("-") for targets in kills for word in targets):
        return Refusal(
            "Odmowa: kill z ujemnym PID-em (kill -1, kill -- -<grupa>) zabija wszystkie procesy użytkownika albo całą "
            f"grupę, także procesy innych wątków na wspólnym Macu. {_allowed(shown)}"
        )
    judged = [call for call in calls if call.name in KILLERS]
    if any(_pid_from_elsewhere(targets) for targets in kills):
        judged += [call for call in calls if call.name == "pgrep"]
    for call in judged:
        problem = _problem(call, project)
        if problem is not None:
            return Refusal(f"Odmowa: {problem} {_allowed(shown)}")
    return None


def main() -> int:
    try:
        command = json.load(sys.stdin)["tool_input"]["command"]
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
        return 0
    if not isinstance(command, str):
        return 0
    refusal = judge(command, os.environ.get("CLAUDE_PROJECT_DIR"))
    if refusal is None:
        return 0
    print(refusal.reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
