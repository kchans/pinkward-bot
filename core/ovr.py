from core.db import pool
from core.tier import tier_score

POSITIONS = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
POSITION_KO = {"TOP": "탑", "JUNGLE": "정글", "MIDDLE": "미드",
               "BOTTOM": "원딜", "UTILITY": "서폿"}

# 큐별 신뢰 가중치 — 진지도가 높을수록 크게 반영한다
QUEUE_WEIGHT = {
    420: 1.00,   # 솔로/듀오 랭크
    440: 0.70,   # 자유 랭크
    400: 0.45,   # 일반 (드래프트)
    430: 0.45,   # 일반 (블라인드)
    490: 0.35,   # 퀵플레이
}
STAT_QUEUES = list(QUEUE_WEIGHT)

SAMPLE = 50          # 최근 몇 판을 볼 것인가
SHRINK = 6           # 가중 표본이 이만큼 쌓여야 보정을 절반 신뢰
PENALTY = 20         # 표본이 없을 때 최대 감점
MAIN_BONUS = 25      # 주포지션 가산 폭
EVEN_SHARE = 0.2     # 5개 포지션 균등 비중(1/5)
FLEX_DISCOUNT = 200  # 자유랭 베이스 할인
UNRANKED_OVR = 45.0  # 랭크 기록이 전혀 없을 때

STATS_SQL = """
with recent as (
    select p.position, mt.queue_id, p.win, p.kills, p.deaths, p.assists
    from match_participants p
    join matches mt on mt.match_id = p.match_id
    where p.puuid = $1
      and mt.source = 'riot'
      and mt.queue_id = any($3::int[])
      and p.position in ('TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY')
    order by mt.game_start desc
    limit $2
)
select position, queue_id,
       count(*)::int as games,
       avg(case when win then 1.0 else 0.0 end)::float as winrate,
       avg((kills + assists)::float / greatest(deaths, 1))::float as kda
from recent
group by position, queue_id
"""

TIER_SQL = """
select distinct on (queue_type)
       queue_type, tier, division, league_points
from rank_snapshots
where puuid = $1 and queue_type in ('RANKED_SOLO_5x5', 'RANKED_FLEX_SR')
order by queue_type, fetched_at desc
"""


def _score_to_ovr(score: float) -> float:
    if score < 0:
        return UNRANKED_OVR
    if score <= 2700:                                  # 아이언4 ~ 다이아1
        return 40 + 48 * (score / 2700)
    return min(99.0, 88 + (score - 2700) / 250)        # 마스터 이상


def base_from_ranks(rows) -> tuple[float, str]:
    """솔랭 우선, 없으면 자유랭(할인 적용), 둘 다 없으면 언랭 기본값."""
    solo = next((r for r in rows if r["queue_type"] == "RANKED_SOLO_5x5"), None)
    if solo:
        return _score_to_ovr(
            tier_score(solo["tier"], solo["division"], solo["league_points"])
        ), "솔로랭크"

    flex = next((r for r in rows if r["queue_type"] == "RANKED_FLEX_SR"), None)
    if flex:
        score = tier_score(flex["tier"], flex["division"], flex["league_points"])
        return _score_to_ovr(max(score - FLEX_DISCOUNT, 0)), "자유랭크"

    return UNRANKED_OVR, "언랭"


def compute(base: float, rows) -> tuple[dict[str, int], dict[str, int]]:
    """큐별 가중치를 적용해 포지션 지수와 실제 판수를 계산한다."""
    agg: dict[str, dict] = {}
    for r in rows:
        w = QUEUE_WEIGHT.get(r["queue_id"], 0.3)
        a = agg.setdefault(r["position"],
                           {"games": 0, "weight": 0.0, "wr": 0.0, "kda": 0.0})
        a["games"] += r["games"]                       # 표시용 실제 판수
        a["weight"] += r["games"] * w                  # 계산용 가중 판수
        a["wr"] += r["winrate"] * r["games"] * w
        a["kda"] += r["kda"] * r["games"] * w

    for a in agg.values():
        if a["weight"] > 0:
            a["wr"] /= a["weight"]
            a["kda"] /= a["weight"]

    games = {p: agg[p]["games"] if p in agg else 0 for p in POSITIONS}
    total_w = sum(a["weight"] for a in agg.values())

    if total_w == 0:
        flat = int(round(max(30, min(99, base - PENALTY))))
        return {p: flat for p in POSITIONS}, games

    own_wr = sum(a["wr"] * a["weight"] for a in agg.values()) / total_w
    own_kda = sum(a["kda"] * a["weight"] for a in agg.values()) / total_w

    out = {}
    for p in POSITIONS:
        a = agg.get(p)
        w = a["weight"] if a else 0.0
        conf = w / (w + SHRINK)        # 가중 표본 신뢰도 0~1
        share = w / total_w            # 가중 점유율

        perf = 0.0
        if a:
            perf = (a["wr"] - own_wr) * 60 + (a["kda"] - own_kda) * 4

        ovr = (base
               + conf * perf                          # 성과 보정
               + MAIN_BONUS * (share - EVEN_SHARE)    # 주포지션 가산
               - PENALTY * (1 - conf))                # 표본 부족 감점
        out[p] = int(round(max(30, min(99, ovr))))

    return out, games


async def refresh_ovr(puuid: str) -> tuple[dict[str, int], dict[str, int], str]:
    async with pool().acquire() as conn:
        rank_rows = await conn.fetch(TIER_SQL, puuid)
        stat_rows = await conn.fetch(STATS_SQL, puuid, SAMPLE, STAT_QUEUES)

    base, source = base_from_ranks(rank_rows)
    ratings, games = compute(base, stat_rows)

    async with pool().acquire() as conn:
        async with conn.transaction():
            for pos, ovr in ratings.items():
                await conn.execute(
                    "insert into position_ratings (puuid, position, ovr, games, updated_at) "
                    "values ($1,$2,$3,$4, now()) "
                    "on conflict (puuid, position) do update set "
                    "  ovr = excluded.ovr, games = excluded.games, updated_at = now()",
                    puuid, pos, ovr, games.get(pos, 0),
                )
    return ratings, games, source