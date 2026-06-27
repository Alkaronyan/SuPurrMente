"""One-off: inspect the raw LR4 activity history to resolve the fetcher TODOs.

Run: docker compose run --rm tracker python scripts/inspect_api.py
Answers: what type are the entries, what attributes do they expose, is there a
per-cat id, what is the weight attribute/unit, and what timespan is returned?
"""
import asyncio
import os
from collections import Counter

from pylitterbot import Account


async def main() -> None:
    account = Account()
    await account.connect(
        username=os.environ["WHISKER_USERNAME"],
        password=os.environ["WHISKER_PASSWORD"],
        load_robots=True,
    )
    try:
        print("robots:", [type(r).__name__ for r in account.robots])
        if not account.robots:
            return
        robot = account.robots[0]
        print("robot name:", getattr(robot, "name", "?"))

        history = await robot.get_activity_history(limit=200)
        print("history length:", len(history))
        if not history:
            return

        # Type distribution of entries
        print("entry types:", Counter(type(e).__name__ for e in history))

        # Dump the first 5 entries in full detail
        for i, e in enumerate(history[:5]):
            print(f"\n--- entry {i} ---")
            print("repr:", repr(e))
            print("type:", type(e).__name__)
            attrs = [a for a in dir(e) if not a.startswith("_")]
            print("public attrs:", attrs)
            for a in attrs:
                try:
                    v = getattr(e, a)
                    if not callable(v):
                        print(f"   {a} = {v!r}")
                except Exception as ex:
                    print(f"   {a} -> error {ex}")

        # Timespan covered
        ts = [getattr(e, "timestamp", None) for e in history]
        ts = [t for t in ts if t]
        if ts:
            print("\ntimespan:", min(ts), "→", max(ts))

        # How many look like weight events
        with_weight = [e for e in history if getattr(e, "weight", None)]
        print("entries with non-zero .weight:", len(with_weight))
    finally:
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
