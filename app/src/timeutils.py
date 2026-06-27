"""Single source of truth for timezone handling.

Decision: the system stores and displays everything in LOCAL Madrid time
(Europe/Madrid). The Whisker app shows local time, the historical CSV exports are
in local time, so we keep one consistent local clock end to end:

  * API timestamps arrive in UTC  → convert to Madrid (`to_local`).
  * CSV timestamps are naive local → tag as Madrid (`to_local` leaves them).
  * "now" for windows/cutoffs uses Madrid (`now`).

Stored strings keep the `...Z` shape for format compatibility, but the value is
the local Madrid wall-clock, not UTC. ZoneInfo needs the `tzdata` package on slim
images (declared in requirements.txt).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Madrid")


def now() -> datetime:
    """Current time, Madrid-local and timezone-aware."""
    return datetime.now(LOCAL_TZ)


def to_local(dt: datetime) -> datetime:
    """Normalise any datetime to Madrid-local.

    Aware datetimes are converted; naive ones are assumed to already be local
    wall-clock (that is how the CSV exports come) and simply tagged.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)
