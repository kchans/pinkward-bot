import asyncio

from core.db import init_pool, close_pool, pool

POSITIONS = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
METRICS = ("kpm", "apm", "dpm", "dth", "csm", "gpm", "vsm", "kp", "shr")
STEPS = 21          # 0%, 5%, ..., 100%

SAMPLE_SQL = """
with base as (
    select p.match_id, p.team_id, p.position, p.kills, p.deaths, p.assists,
           p.damage_dealt, p.gold_earned, p.cs, p.vision_score,
           m.duration_sec
    from match_participants p
    join matches m on m.match_id = p.match_id
    where m.source = 'riot' and m.queue_id = 420 and m.duration_sec > 600
      and p.position in ('TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY')
),
teams as (
    select mp.match_id, mp.team_id,
           sum(mp.kills)::float        as tk,
           sum(mp.damage_dealt)::float as td
    from match_participants mp
    where mp.match_id in (select match_id from base)
    group by mp.match_id, mp.team_id
)
select b.position,
       b.kills        / (b.duration_sec / 60.0) as kpm,
       b.assists      / (b.duration_sec / 60.0) as apm,
       b.damage_dealt / (b.duration_sec / 60.0) as dpm,
       b.deaths       / (b.duration_sec / 60.0) as dth,
       b.cs           / (b.duration_sec / 60.0) as csm,
       b.gold_earned  / (b.duration_sec / 60.0) as gpm,
       b.vision_score / (b.duration_sec / 60.0) as vsm,
       (b.kills + b.assists) / greatest(t.tk, 1) as kp,
       b.damage_dealt        / greatest(t.td, 1) as shr
from base b
join teams t on t.match_id = b.match_id and t.team_id = b.team_id
"""


def quantiles(values: list[float], steps: int = STEPS) -> list[float]:
    values = sorted(values)
    n = len(values)
    out = []
    for i in range(steps):
        pos = (n - 1) * i / (steps - 1)
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        out.append(values[lo] * (1 - frac) + values[hi] * frac)
    return out


async def main():
    await init_pool()
    async with pool().acquire() as conn:
        rows = await conn.fetch(SAMPLE_SQL)

    print(f"표본 {len(rows)}행\n")

    buckets: dict[str, dict[str, list[float]]] = {
        p: {m: [] for m in METRICS} for p in POSITIONS}
    for r in rows:
        b = buckets[r["position"]]
        for m in METRICS:
            b[m].append(float(r[m]))

    async with pool().acquire() as conn:
        for position in POSITIONS:
            counts = len(buckets[position]["kpm"])
            print(f"── {position}  ({counts}행)")
            for metric in METRICS:
                q = quantiles(buckets[position][metric])
                print(f"   {metric:<4} 하위5% {q[1]:>8.2f}  중앙 {q[10]:>8.2f}  "
                      f"상위5% {q[19]:>8.2f}")
                await conn.execute(
                    "insert into reference_metrics "
                    "(position, metric, quantiles, samples, updated_at) "
                    "values ($1,$2,$3,$4, now()) "
                    "on conflict (position, metric) do update set "
                    "  quantiles = excluded.quantiles, samples = excluded.samples, "
                    "  updated_at = now()",
                    position, metric, q, counts)
            print()

    await close_pool()
    print("reference_metrics 저장 완료")


asyncio.run(main())