import asyncio

from core.db import init_pool, close_pool, pool
from core.stocks import ensure_listings


async def main():
    await init_pool()

    new = await ensure_listings()
    print(f"신규 상장 {new}종목\n")

    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "select l.puuid, s.game_name, s.tag_line, l.last_score, "
            "       p.price, l.delisted "
            "from stock_listings l "
            "join summoners s on s.puuid = l.puuid "
            "join stock_prices p on p.puuid = l.puuid and p.kind = 'L1' "
            "order by l.last_score desc")

    print(f"{'종목':<24} {'점수':>6} {'주가':>10}")
    for r in rows:
        name = f"{r['game_name']}#{r['tag_line']}"
        mark = " (폐지)" if r["delisted"] else ""
        print(f"{name:<24} {r['last_score']:>6} {r['price']:>10,.0f}{mark}")

    await close_pool()


asyncio.run(main())