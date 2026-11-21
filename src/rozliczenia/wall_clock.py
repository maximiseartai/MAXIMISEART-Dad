from __future__ import annotations

from datetime import date, datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def local_now() -> datetime:
    return utc_now().astimezone()


def dad_today() -> date:
    return local_now().date()


def epoch_s() -> float:
    return utc_now().timestamp()
