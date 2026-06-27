"""Explore richer data sources: per-cat visits (with/without weight) and insights.

Run: docker compose run --rm tracker python src/inspect_visits.py
"""
import asyncio
import inspect
import os
from datetime import datetime, timedelta, timezone

from pylitterbot import Account


async def call(obj, name, *args):
    m = getattr(obj, name, None)
    if not callable(m):
        return f"<no method {name}>"
    try:
        r = m(*args)
        if inspect.isawaitable(r):
            r = await r
        return r
    except Exception as e:
        return f"<error {type(e).__name__}: {e}>"


async def main() -> None:
    account = Account()
    await account.connect(
        username=os.environ["WHISKER_USERNAME"],
        password=os.environ["WHISKER_PASSWORD"],
        load_robots=True,
    )
    try:
        await account.load_pets()
        since = datetime.now(timezone.utc) - timedelta(days=7)

        for pet in account.pets:
            print(f"\n===== Pet {pet.name} =====")
            print("get_visits_since signature:",
                  str(inspect.signature(pet.get_visits_since)) if callable(getattr(pet, "get_visits_since", None)) else "n/a")
            visits = await call(pet, "get_visits_since", since)
            if isinstance(visits, list):
                print(f"get_visits_since(7d) -> {len(visits)} item(s)")
                for v in visits[:6]:
                    print("   ", repr(v))
                    if v is visits[0]:
                        print("    attrs:", [a for a in dir(v) if not a.startswith('_')])
            else:
                print("get_visits_since ->", visits)

        robot = account.robots[0]
        print("\n===== Robot insights =====")
        print("get_insight signature:",
              str(inspect.signature(robot.get_insight)) if callable(getattr(robot, "get_insight", None)) else "n/a")
        insight = await call(robot, "get_insight")
        print("get_insight() ->", repr(insight))
        if insight is not None and not isinstance(insight, str):
            print("insight attrs:", [a for a in dir(insight) if not a.startswith('_')])
            for a in [a for a in dir(insight) if not a.startswith('_')]:
                try:
                    val = getattr(insight, a)
                    if not callable(val):
                        print(f"   {a} = {val!r}")
                except Exception as e:
                    print(f"   {a} -> err {e}")
    finally:
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
