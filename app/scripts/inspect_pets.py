"""Find LR4 pet weight readings in pylitterbot (round 2)."""
import asyncio
import inspect
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
        await account.load_pets()
        print("account.pets after load_pets():", account.pets)

        for p in account.pets:
            print("\n--- Pet ---")
            print("type:", type(p).__name__)
            print("members:", members(p))
            for a in members(p):
                try:
                    v = getattr(p, a)
                    if not callable(v):
                        print(f"   {a} = {v!r}")
                except Exception as ex:
                    print(f"   {a} -> err {ex}")
            # Call any weight/history method
            for mname in members(p):
                low = mname.lower()
                if "weight" in low or "history" in low or "fetch" in low:
                    m = getattr(p, mname)
                    if callable(m):
                        try:
                            sig = str(inspect.signature(m))
                        except (TypeError, ValueError):
                            sig = "(?)"
                        try:
                            r = m()
                            if inspect.isawaitable(r):
                                r = await r
                            sample = r[:5] if isinstance(r, list) else r
                            print(f"   CALL {mname}{sig} -> (len={len(r) if isinstance(r,list) else '?'}) {sample}")
                        except Exception as ex:
                            print(f"   CALL {mname}{sig} error: {ex}")

        robot = account.robots[0]
        print("\nrobot.pet_weight =", getattr(robot, "pet_weight", None))
    finally:
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
