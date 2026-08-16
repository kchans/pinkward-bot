from core.db import pool
from core.tier import tier_score

BASE_PRICE = 1000.0        # 상장가
RETURN_UNIT = 1.00         # 기준 단위만큼 오르면 100%
MAX_TICK_RETURN = 0.25     # 한 회차 최대 변동 ±25% (초과분은 다음 회차로 이월)
FEE = 0.01                 # 매도 수수료
START_CASH = 100000.0       # 시작 자본
DAILY_REWARD = 10000.0     # 출석 보상
DELIST_PRICE = 50.0        # 이 아래면 상장폐지
MIN_ORDER = 100.0          # 최소 매수 금액

# 티어별 기준 단위 — 이만큼 오르면 RETURN_UNIT 만큼 오른다
K_BY_TIER = {
    "IRON": 100, "BRONZE": 100, "SILVER": 100, "GOLD": 100,
    "PLATINUM": 100, "EMERALD": 100, "DIAMOND": 150,
    "MASTER": 250, "GRANDMASTER": 400, "CHALLENGER": 700,
}

KINDS = {"L1": 1.0, "L2": 2.0, "S1": -1.0, "S2": -2.0}
KIND_KO = {"L1": "현물", "L2": "레버리지", "S1": "인버스", "S2": "곱버스"}

LATEST_RANK_SQL = """
select distinct on (r.puuid)
       r.puuid, r.tier, r.division, r.league_points
from rank_snapshots r
where r.queue_type = 'RANKED_SOLO_5x5'
  and r.puuid in (select puuid from guild_members)
order by r.puuid, r.fetched_at desc
"""


def _k(tier: str | None) -> float:
    return float(K_BY_TIER.get(tier or "", 100))


async def ensure_listings() -> int:
    """티어가 확인된 등록 유저를 자동 상장한다."""
    async with pool().acquire() as conn:
        ranks = await conn.fetch(LATEST_RANK_SQL)
        listed = {r["puuid"] for r in
                  await conn.fetch("select puuid from stock_listings")}

        new = 0
        async with conn.transaction():
            for r in ranks:
                if r["puuid"] in listed or not r["tier"]:
                    continue
                score = tier_score(r["tier"], r["division"], r["league_points"])
                await conn.execute(
                    "insert into stock_listings (puuid, last_score) values ($1,$2) "
                    "on conflict (puuid) do nothing", r["puuid"], score)
                for kind in KINDS:
                    await conn.execute(
                        "insert into stock_prices (puuid, kind, price, prev_price) "
                        "values ($1,$2,$3,$3) on conflict do nothing",
                        r["puuid"], kind, BASE_PRICE)
                new += 1
        return new


async def tick() -> dict:
    """시세를 갱신하고 대기 주문을 체결한다. 30분마다 호출."""
    await ensure_listings()

    async with pool().acquire() as conn:
        ranks = {r["puuid"]: r for r in await conn.fetch(LATEST_RANK_SQL)}
        listings = await conn.fetch(
            "select puuid, last_score from stock_listings where not delisted")
        prices = {(p["puuid"], p["kind"]): p["price"] for p in
                  await conn.fetch("select puuid, kind, price from stock_prices")}

        moved = delisted = 0
        async with conn.transaction():
            for lst in listings:
                puuid = lst["puuid"]
                rank = ranks.get(puuid)
                if rank is None or not rank["tier"]:
                    continue

                score = tier_score(rank["tier"], rank["division"],
                                   rank["league_points"])
                delta = score - lst["last_score"]
                k = _k(rank["tier"])

                raw = (delta / k) * RETURN_UNIT
                ret = max(-MAX_TICK_RETURN, min(MAX_TICK_RETURN, raw))
                # 반영한 만큼만 기준점을 옮긴다. 나머지는 다음 회차로 이월된다.
                applied = int(round(ret / RETURN_UNIT * k)) if RETURN_UNIT else delta
                if ret:
                    moved += 1

                dead = False
                for kind, mult in KINDS.items():
                    old = prices.get((puuid, kind), BASE_PRICE)
                    new = max(1.0, old * (1 + ret * mult))
                    await conn.execute(
                        "update stock_prices set price = $1, prev_price = $2 "
                        "where puuid = $3 and kind = $4", new, old, puuid, kind)
                    await conn.execute(
                        "insert into stock_history (puuid, kind, price) "
                        "values ($1,$2,$3)", puuid, kind, new)
                    prices[(puuid, kind)] = new
                    if new < DELIST_PRICE:
                        dead = True

                await conn.execute(
                    "update stock_listings set last_score = $1 where puuid = $2",
                    lst["last_score"] + applied, puuid)

                if dead:
                    await conn.execute(
                        "update stock_listings set delisted = true where puuid = $1",
                        puuid)
                    await conn.execute(
                        "delete from holdings where puuid = $1", puuid)
                    delisted += 1

    filled = await _fill_orders()
    return {"moved": moved, "delisted": delisted, "filled": filled}


async def _fill_orders() -> int:
    """대기 주문을 새 시세로 체결한다."""
    async with pool().acquire() as conn:
        orders = await conn.fetch(
            "select * from stock_orders where status = 'pending' "
            "order by created_at")
        if not orders:
            return 0
        prices = {(p["puuid"], p["kind"]): p["price"] for p in
                  await conn.fetch("select puuid, kind, price from stock_prices")}

        count = 0
        async with conn.transaction():
            for o in orders:
                price = prices.get((o["puuid"], o["kind"]))
                if price is None or price <= 0:
                    await conn.execute(
                        "update stock_orders set status = 'cancelled' where id = $1",
                        o["id"])
                    continue

                if o["side"] == "buy":
                    shares = o["amount"] / price
                    row = await conn.fetchrow(
                        "select shares, avg_cost from holdings "
                        "where guild_id=$1 and discord_user_id=$2 "
                        "  and puuid=$3 and kind=$4",
                        o["guild_id"], o["discord_user_id"], o["puuid"], o["kind"])
                    old_shares = row["shares"] if row else 0.0
                    old_cost = row["avg_cost"] if row else 0.0
                    total = old_shares + shares
                    avg = ((old_shares * old_cost) + o["amount"]) / total
                    await conn.execute(
                        "insert into holdings "
                        "(guild_id, discord_user_id, puuid, kind, shares, avg_cost) "
                        "values ($1,$2,$3,$4,$5,$6) "
                        "on conflict (guild_id, discord_user_id, puuid, kind) "
                        "do update set shares = excluded.shares, "
                        "              avg_cost = excluded.avg_cost",
                        o["guild_id"], o["discord_user_id"], o["puuid"], o["kind"],
                        total, avg)
                else:
                    proceeds = o["amount"] * price * (1 - FEE)
                    await conn.execute(
                        "update wallets set cash = cash + $1 "
                        "where guild_id = $2 and discord_user_id = $3",
                        proceeds, o["guild_id"], o["discord_user_id"])
                    shares = o["amount"]

                await conn.execute(
                    "update stock_orders set status='filled', fill_price=$1, "
                    "fill_shares=$2, filled_at=now() where id=$3",
                    price, shares, o["id"])
                count += 1
        return count


async def get_cash(guild_id: int, user_id: int) -> float:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "insert into wallets (guild_id, discord_user_id, cash) "
            "values ($1,$2,$3) on conflict (guild_id, discord_user_id) "
            "do update set cash = wallets.cash returning cash",
            guild_id, user_id, START_CASH)
    return row["cash"]


async def place_buy(guild_id: int, user_id: int, puuid: str,
                    kind: str, amount: float) -> str | None:
    """예약 매수. 실패 사유를 문자열로 반환, 성공 시 None."""
    if amount < MIN_ORDER:
        return f"최소 주문 금액은 {int(MIN_ORDER):,} 코인입니다."
    cash = await get_cash(guild_id, user_id)
    if cash < amount:
        return f"코인이 부족합니다. 보유 {cash:,.0f}"

    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "select delisted from stock_listings where puuid = $1", puuid)
        if row is None or row["delisted"]:
            return "거래할 수 없는 종목입니다."
        async with conn.transaction():
            await conn.execute(
                "update wallets set cash = cash - $1 "
                "where guild_id=$2 and discord_user_id=$3",
                amount, guild_id, user_id)
            await conn.execute(
                "insert into stock_orders "
                "(guild_id, discord_user_id, puuid, kind, side, amount) "
                "values ($1,$2,$3,$4,'buy',$5)",
                guild_id, user_id, puuid, kind, amount)
    return None


async def place_sell(guild_id: int, user_id: int, puuid: str,
                     kind: str, shares: float) -> str | None:
    async with pool().acquire() as conn:
        row = await conn.fetchrow(
            "select shares from holdings where guild_id=$1 and discord_user_id=$2 "
            "  and puuid=$3 and kind=$4", guild_id, user_id, puuid, kind)
        held = row["shares"] if row else 0.0
        if shares <= 0 or held < shares:
            return f"보유 수량이 부족합니다. 보유 {held:.2f}주"
        async with conn.transaction():
            await conn.execute(
                "update holdings set shares = shares - $1 "
                "where guild_id=$2 and discord_user_id=$3 and puuid=$4 and kind=$5",
                shares, guild_id, user_id, puuid, kind)
            await conn.execute(
                "insert into stock_orders "
                "(guild_id, discord_user_id, puuid, kind, side, amount) "
                "values ($1,$2,$3,$4,'sell',$5)",
                guild_id, user_id, puuid, kind, shares)
    return None