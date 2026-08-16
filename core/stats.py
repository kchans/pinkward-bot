from core.db import pool
from core.ovr import STAT_QUEUES

SAMPLE = 50
MIN_GAMES = 10

STAT_KO = {
    "attack": "공격", "survive": "생존", "growth": "성장",
    "vision": "시야", "team": "협력", "carry": "캐리",
}

WINRATE_ANCHOR = (0.40, 0.62)

# 실측 분포(reference_metrics)를 못 읽었을 때만 쓰는 예비값
FALLBACK = {
    "TOP":     {"kpm": (.00, .48), "apm": (.00, .41), "dpm": (390, 1418),
                "dth": (.05, .41), "csm": (4.45, 9.31), "gpm": (288, 550),
                "vsm": (.33, 1.31), "kp": (.11, .61), "shr": (.12, .36)},
    "JUNGLE":  {"kpm": (.05, .55), "apm": (.06, .56), "dpm": (264, 1226),
                "dth": (.04, .38), "csm": (4.54, 8.64), "gpm": (325, 581),
                "vsm": (.51, 1.69), "kp": (.25, .76), "shr": (.09, .29)},
    "MIDDLE":  {"kpm": (.04, .53), "apm": (.00, .46), "dpm": (404, 1451),
                "dth": (.04, .41), "csm": (4.56, 9.40), "gpm": (304, 549),
                "vsm": (.32, 1.32), "kp": (.17, .67), "shr": (.13, .36)},
    "BOTTOM":  {"kpm": (.04, .59), "apm": (.04, .49), "dpm": (349, 1509),
                "dth": (.06, .42), "csm": (5.13, 9.70), "gpm": (335, 646),
                "vsm": (.30, 1.22), "kp": (.20, .73), "shr": (.12, .36)},
    "UTILITY": {"kpm": (.00, .32), "apm": (.12, .86), "dpm": (181, 893),
                "dth": (.06, .44), "csm": (0.57, 2.42), "gpm": (247, 409),
                "vsm": (1.14, 4.02), "kp": (.27, .76), "shr": (.05, .23)},
}

STATS_SQL = """
with recent as (
    select p.match_id, p.team_id, p.position, p.win,
           p.kills, p.deaths, p.assists, p.damage_dealt,
           p.gold_earned, p.cs, p.vision_score, m.duration_sec
    from match_participants p
    join matches m on m.match_id = p.match_id
    where p.puuid = $1
      and m.source = 'riot'
      and m.queue_id = any($3::int[])
      and m.duration_sec > 300
      and p.position in ('TOP','JUNGLE','MIDDLE','BOTTOM','UTILITY')
    order by m.game_start desc
    limit $2
),
teams as (
    select mp.match_id, mp.team_id,
           sum(mp.kills)::float        as tk,
           sum(mp.damage_dealt)::float as td
    from match_participants mp
    where mp.match_id in (select match_id from recent)
    group by mp.match_id, mp.team_id
)
select r.position,
       count(*)::int                                  as games,
       sum(r.duration_sec)::float / 60.0              as minutes,
       sum(r.kills)::float                            as kills,
       sum(r.deaths)::float                           as deaths,
       sum(r.assists)::float                          as assists,
       sum(r.damage_dealt)::float                     as damage,
       sum(r.gold_earned)::float                      as gold,
       sum(r.cs)::float                               as cs,
       sum(r.vision_score)::float                     as vision,
       sum(case when r.win then 1 else 0 end)::float  as wins,
       sum(t.tk)::float                               as team_kills,
       sum(t.td)::float                               as team_damage
from recent r
join teams t on t.match_id = r.match_id and t.team_id = r.team_id
group by r.position
"""

TOP_CHAMP_SQL = """
select p.champion_name, count(*)::int as picks
from match_participants p
join matches m on m.match_id = p.match_id
where p.puuid = $1 and m.source = 'riot' and p.champion_name is not null
group by p.champion_name
order by picks desc
limit 1
"""

_reference: dict[tuple[str, str], list[float]] = {}


async def load_reference() -> None:
    """실측 분포를 메모리에 올린다. 봇 실행 중 한 번만."""
    global _reference
    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "select position, metric, quantiles from reference_metrics")
    _reference = {(r["position"], r["metric"]): list(r["quantiles"]) for r in rows}


def _percentile(q: list[float], value: float) -> float:
    """분위수 배열에서 값의 백분위(0~1)를 선형 보간으로 찾는다."""
    if value <= q[0]:
        return 0.0
    if value >= q[-1]:
        return 1.0
    for i in range(1, len(q)):
        if value <= q[i]:
            lo, hi = q[i - 1], q[i]
            frac = 0.0 if hi == lo else (value - lo) / (hi - lo)
            return (i - 1 + frac) / (len(q) - 1)
    return 1.0


def _linear(value: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.5
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def _score(position: str, metric: str, value: float, invert: bool = False) -> float:
    q = _reference.get((position, metric))
    p = _percentile(q, value) if q else _linear(value, *FALLBACK[position][metric])
    if invert:
        p = 1.0 - p
    return 30.0 + 69.0 * p


def compute_stats(rows) -> tuple[dict[str, int], dict, str] | None:
    """주 포지션 경기만으로 6능력치를 계산한다."""
    if not rows:
        return None

    total_games = sum(r["games"] for r in rows)
    main_row = max(rows, key=lambda r: r["games"])
    main = main_row["position"]
    if main_row["games"] < MIN_GAMES:
        return None

    mins = main_row["minutes"] or 1.0
    kpm = main_row["kills"] / mins
    apm = main_row["assists"] / mins
    dpm = main_row["damage"] / mins
    dth = main_row["deaths"] / mins
    csm = main_row["cs"] / mins
    gpm = main_row["gold"] / mins
    vsm = main_row["vision"] / mins
    kp = (main_row["kills"] + main_row["assists"]) / max(main_row["team_kills"], 1.0)
    shr = main_row["damage"] / max(main_row["team_damage"], 1.0)
    wr = main_row["wins"] / main_row["games"]

    def s(metric: str, value: float, invert: bool = False) -> float:
        return _score(main, metric, value, invert)

    stats = {
        "attack":  0.45 * s("kpm", kpm) + 0.55 * s("dpm", dpm),
        "survive": s("dth", dth, True),
        "growth":  0.55 * s("csm", csm) + 0.45 * s("gpm", gpm),
        "vision":  s("vsm", vsm),
        "team":    0.60 * s("kp", kp) + 0.40 * s("apm", apm),
        "carry":   0.60 * s("shr", shr)
                   + 0.40 * (30 + 69 * _linear(wr, *WINRATE_ANCHOR)),
    }
    stats = {k: int(round(max(30, min(99, v)))) for k, v in stats.items()}

    raw = {"games": main_row["games"], "total_games": total_games,
           "winrate": wr, "kp": kp, "share": shr,
           "cspm": csm, "vspm": vsm, "dpm": dpm, "deaths_pm": dth}
    return stats, raw, main


async def player_profile(puuid: str) -> dict | None:
    if not _reference:
        await load_reference()

    async with pool().acquire() as conn:
        rows = await conn.fetch(STATS_SQL, puuid, SAMPLE, STAT_QUEUES)
        champ = await conn.fetchrow(TOP_CHAMP_SQL, puuid)

    result = compute_stats(rows)
    if result is None:
        return None

    stats, raw, main = result
    return {
        "stats": stats,
        "raw": raw,
        "main_position": main,
        "champion": champ["champion_name"] if champ else None,
        "champion_picks": champ["picks"] if champ else 0,
    }