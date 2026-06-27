"""Inspect the LR4 robot object: firmware/version fields, subscription/realtime
methods, and serial/model identifiers. Resolves: push notifications? version log?

Run: docker compose run --rm tracker python src/inspect_robot.py
"""
import asyncio
import os

from pylitterbot import Account


def members(obj):
    return [a for a in dir(obj) if not a.startswith("_")]


async def main() -> None:
    account = Account()
    await account.connect(
        username=os.environ["WHISKER_USERNAME"],
        password=os.environ["WHISKER_PASSWORD"],
        load_robots=True,
    )
    try:
        robot = account.robots[0]
        print("robot type:", type(robot).__name__)
        all_members = members(robot)

        print("\n=== subscription / realtime methods ===")
        print([m for m in all_members if any(k in m.lower()
               for k in ("subscribe", "websocket", "listen", "on_update", "notify", "event", "mqtt", "stream"))])

        print("\n=== version / firmware / identity fields ===")
        keys = ("firmware", "version", "serial", "model", "hardware", "esp", "espfirmware",
                "id", "name", "setup", "manufactured")
        for m in all_members:
            if any(k in m.lower() for k in keys):
                try:
                    v = getattr(robot, m)
                    if not callable(v):
                        print(f"   {m} = {v!r}")
                except Exception as ex:
                    print(f"   {m} -> err {ex}")

        print("\n=== ALL non-callable robot attributes ===")
        for m in all_members:
            try:
                v = getattr(robot, m)
                if not callable(v):
                    sval = repr(v)
                    if len(sval) > 120:
                        sval = sval[:120] + "…"
                    print(f"   {m} = {sval}")
            except Exception as ex:
                print(f"   {m} -> err {ex}")

        print("\n=== callable methods (names only) ===")
        print([m for m in all_members if callable(getattr(robot, m, None))])

        # Account-level subscription?
        print("\n=== Account subscription methods ===")
        print([m for m in members(account) if any(k in m.lower()
               for k in ("subscribe", "websocket", "listen", "event", "monitor"))])
    finally:
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
