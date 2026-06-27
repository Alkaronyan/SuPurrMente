"""Does get_insight's daily cycle count match the sum of per-cat weight readings?
If yes, every cycle = an identifiable cat visit and we could attribute cycles.

Run: docker compose run --rm tracker python src/inspect_correlation.py
"""
import asyncio
import os
from collections import Counter
from datetime import timezone
from zoneinfo import ZoneInfo

from pylitterbot import Account

MADRID = ZoneInfo("Europe/Madrid")


async def main() -> None:
    account = Account()
    await account.connect(
        username=os.environ["WHISKER_USERNAME"],
        password=os.environ["WHISKER_PASSWORD"],
        load_robots=True,
    )
    try:
        await account.load_pets()
        robot = account.robots[0]

        # Per-cat weight readings per LOCAL (Madrid) day
        per_cat_day = {}
        for pet in account.pets:
            hist = await pet.fetch_weight_history(limit=200)
            c = Counter(m.timestamp.astimezone(MADRID).date() for m in hist)
            per_cat_day[pet.name] = c

        insight = await robot.get_insight(days=14)
        cycles = dict(insight.cycle_history)  # {date: cycle_count}

        names = list(per_cat_day.keys())
        print(f"{'fecha':12} | {'ciclos':>6} | " + " | ".join(f"{n:>7}" for n in names) + " | sum_gatos")
        print("-" * 70)
        all_days = sorted(set(cycles) | {d for c in per_cat_day.values() for d in c}, reverse=True)
        for d in all_days:
            cyc = cycles.get(d, 0)
            counts = [per_cat_day[n].get(d, 0) for n in names]
            print(f"{str(d):12} | {cyc:6} | " + " | ".join(f"{x:7}" for x in counts)
                  + f" | {sum(counts)}")
    finally:
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
