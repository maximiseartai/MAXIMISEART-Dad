from __future__ import annotations

from collections.abc import Sequence
import ctypes
import os
from pathlib import Path
import sys
from typing import NoReturn

WRITABLE_DEVICES = ("/dev/null",)
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
# ZEWNĘTRZNE: numery wywołań landlock_create_ruleset, landlock_add_rule i landlock_restrict_self są wspólne dla architektur (include/uapi/asm-generic/unistd.h, Linux 5.13)
_CREATE_RULESET, _ADD_RULE, _RESTRICT_SELF = 444, 445, 446
_ABI_VERSION_FLAG = 1
_RULE_PATH_BENEATH = 1
_SET_NO_NEW_PRIVS = 38
# ZEWNĘTRZNE: prawa LANDLOCK_ACCESS_FS_* zapisu, od WRITE_FILE (bit 1) do TRUNCATE (bit 14, ABI 3); chmod, chown, czasu i xattr Landlock nie ogranicza (include/uapi/linux/landlock.h)
_WRITE_FILE = 1 << 1
_TRUNCATE = 1 << 14
_TREE_WRITES = _WRITE_FILE | sum(1 << bit for bit in range(4, 14)) | _TRUNCATE
_DEVICE_WRITES = _WRITE_FILE | _TRUNCATE
_LANDLOCK_ABI_WITH_TRUNCATE = 3


class _RulesetAttr(ctypes.Structure):
    _fields_ = (("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64), ("scoped", ctypes.c_uint64))


class _PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = (("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32))


def unavailable() -> str | None:
    if sys.platform == "darwin":
        return None if Path(SANDBOX_EXEC).is_file() else f"brak {SANDBOX_EXEC} na tym macOS"
    if sys.platform == "linux":
        abi = _landlock_abi()
        return None if abi >= _LANDLOCK_ABI_WITH_TRUNCATE else f"jądro bez Landlock ABI {_LANDLOCK_ABI_WITH_TRUNCATE} (Linux 6.2) z prawem obcięcia pliku (ABI {abi})"
    return f"system {sys.platform} bez piaskownicy dowodu"


def prefix(writable: Sequence[Path]) -> tuple[str, ...]:
    if (reason := unavailable()) is not None:
        raise RuntimeError(f"piaskownica: {reason}")
    roots = [os.path.realpath(path) for path in writable]
    if sys.platform == "darwin":
        return (SANDBOX_EXEC, "-p", _profile(len(roots)), *(part for index, root in enumerate(roots) for part in ("-D", f"Z{index}={root}")))
    return (sys.executable, "-I", str(Path(__file__).resolve()), *roots, "--")


def _profile(roots: int) -> str:
    allowed = [*(f'(subpath (param "Z{index}"))' for index in range(roots)), *(f'(literal "{device}")' for device in WRITABLE_DEVICES)]
    return f"(version 1)(allow default)(deny file-write* (require-not (require-any {' '.join(allowed)})))"


def _landlock_abi() -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    return int(libc.syscall(_CREATE_RULESET, None, ctypes.c_size_t(0), ctypes.c_uint32(_ABI_VERSION_FLAG)))


def _confine(arguments: list[str]) -> NoReturn:
    if sys.platform != "linux":
        raise SystemExit(f"piaskownica: Landlock jest tylko na Linuksie, a to {sys.platform}")
    split = arguments.index("--")
    roots, command = arguments[:split], arguments[split + 1 :]
    libc = ctypes.CDLL(None, use_errno=True)

    def checked(result: int, step: str) -> int:
        if result < 0:
            raise SystemExit(f"piaskownica: {step} odmówiło (errno {ctypes.get_errno()})")
        return result

    attributes = _RulesetAttr(_TREE_WRITES, 0, 0)
    ruleset = checked(libc.syscall(_CREATE_RULESET, ctypes.byref(attributes), ctypes.c_size_t(ctypes.sizeof(attributes)), ctypes.c_uint32(0)), "landlock_create_ruleset")
    for path, rights in [*((root, _TREE_WRITES) for root in roots), *((device, _DEVICE_WRITES) for device in WRITABLE_DEVICES)]:
        opened = os.open(path, os.O_PATH | os.O_CLOEXEC)
        try:
            rule = _PathBeneath(rights, opened)
            checked(libc.syscall(_ADD_RULE, ruleset, ctypes.c_int(_RULE_PATH_BENEATH), ctypes.byref(rule), ctypes.c_uint32(0)), f"landlock_add_rule {path}")
        finally:
            os.close(opened)
    checked(libc.prctl(_SET_NO_NEW_PRIVS, 1, 0, 0, 0), "prctl PR_SET_NO_NEW_PRIVS")
    checked(libc.syscall(_RESTRICT_SELF, ruleset, ctypes.c_uint32(0)), "landlock_restrict_self")
    os.close(ruleset)
    os.execv(command[0], command)


if __name__ == "__main__":
    _confine(sys.argv[1:])
