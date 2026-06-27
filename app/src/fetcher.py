import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import api_contract
import timeutils
import whisker_auth

log = logging.getLogger(__name__)

# The LR4 reports pet weights in POUNDS. Confirmed against known weights:
# Robin 9.67 lb → 4.39 kg (~4.4), Pirata 14.6 lb → 6.62 kg (~6.6).
_LBS_TO_KG = 0.453592


@dataclass
class FetchResult:
    """Everything one fetch cycle learned from the API."""
    visits: list[dict] = field(default_factory=list)       # new readings to store
    api_issues: list[str] = field(default_factory=list)    # contract violations
    firmware: Optional[str] = None
    library_version: Optional[str] = None
    model: Optional[str] = None
    serial: Optional[str] = None
    # Robot-level extras
    cycle_history: list = field(default_factory=list)      # [(date, cycles)] daily, total
    litter_level: Optional[float] = None                   # %
    waste_drawer_level: Optional[float] = None             # %
    is_online: Optional[bool] = None
    last_seen: Optional[datetime] = None                   # Madrid-local


def _cat_key(pet_name: str) -> str:
    """Whisker pet name → internal cat key ('Robin' → 'robin')."""
    return pet_name.strip().lower()


def _library_version() -> Optional[str]:
    try:
        from importlib.metadata import version
        return version("pylitterbot")
    except Exception:  # pragma: no cover - best effort
        return None


async def fetch_new_visits(
    config: dict,
    last_timestamp: Optional[datetime] = None,
) -> FetchResult:
    """Fetch per-cat weight readings newer than last_timestamp, and check the API
    contract while we have the live objects in hand.

    Weight data lives on the Pet objects (account.pets), in POUNDS. The cat is
    identified by Whisker. Returns a FetchResult carrying the new visits plus any
    contract issues and the device/library versions (so main.py can alert and log).

    Auth is by stored token (no password). If there's no valid token, raises
    ``whisker_auth.WhiskerAuthRequired`` so the caller can email the login link.
    """
    account = await whisker_auth.connect_with_token(config, load_robots=True)
    try:
        await account.load_pets()

        known_cats = set(config["cats"].keys())
        visits: list[dict] = []
        summaries: list[dict] = []

        for pet in account.pets:
            cat = _cat_key(pet.name)
            summary = {"name": pet.name, "cat": cat, "readings_kg": [],
                       "error": None, "ok_shape": True}

            try:
                history = await pet.fetch_weight_history(limit=200)
            except Exception as e:  # API method renamed/removed, network, etc.
                summary["error"] = f"{type(e).__name__}: {e}"
                summaries.append(summary)
                log.warning("fetch_weight_history failed for %s: %s", pet.name, e)
                continue

            if not isinstance(history, list):
                summary["ok_shape"] = False
                summaries.append(summary)
                continue

            for m in history:
                ts = getattr(m, "timestamp", None)
                w = getattr(m, "weight", None)
                if ts is None or w is None:
                    summary["ok_shape"] = False
                    continue
                ts = timeutils.to_local(ts)  # API is UTC → store Madrid-local
                w_kg = round(w * _LBS_TO_KG, 3)
                summary["readings_kg"].append(w_kg)
                if cat in known_cats and (last_timestamp is None or ts > last_timestamp):
                    visits.append({"timestamp": ts, "weight_kg": w_kg, "cat": cat})

            summaries.append(summary)
            log.info("Pet %s: %d reading(s) in history", pet.name, len(summary["readings_kg"]))

        issues = api_contract.validate(known_cats, summaries, config)

        robot = account.robots[0] if account.robots else None

        # Robot-level extras: daily box usage + current litter/drawer/online state.
        cycle_history = []
        if robot:
            try:
                insight = await robot.get_insight(days=30)
                cycle_history = [(d, c) for d, c in insight.cycle_history]
            except Exception as e:
                log.warning("get_insight failed: %s", e)

        last_seen = getattr(robot, "last_seen", None) if robot else None
        if last_seen is not None:
            last_seen = timeutils.to_local(last_seen)

        result = FetchResult(
            visits=sorted(visits, key=lambda v: v["timestamp"]),
            api_issues=issues,
            firmware=getattr(robot, "firmware", None) if robot else None,
            library_version=_library_version(),
            model=getattr(robot, "model", None) if robot else None,
            serial=getattr(robot, "serial", None) if robot else None,
            cycle_history=cycle_history,
            litter_level=getattr(robot, "litter_level", None) if robot else None,
            waste_drawer_level=getattr(robot, "waste_drawer_level", None) if robot else None,
            is_online=getattr(robot, "is_online", None) if robot else None,
            last_seen=last_seen,
        )
        log.info("Fetched %d new reading(s); API issues: %d; cycles_days=%d",
                 len(result.visits), len(issues), len(cycle_history))
        return result

    finally:
        await account.disconnect()
