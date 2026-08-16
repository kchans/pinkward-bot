import json
from datetime import datetime, timezone

from core.db import pool
from core.riot import RiotClient, RiotError

RANKED_QUEUES = ("RANKED_SOLO_5x5", "RANKED_FLEX_SR")


async def sync_matches(riot: RiotClient, puuid: str, count: int = 20) -> dict:
    """최근 매치를 수집해 DB에 저장한다. 이미 있는 경기는 API를 부르지 않는다."""
    match_ids = await riot.get_match_ids(puuid, count=count)
    if not match_ids:
        return {"fetched": 0, "skipped": 0}

    async with pool().acquire() as conn:
        rows = await conn.fetch(
            "select match_id from matches where match_id = any($1::text[])",
            match_ids,
        )
    known = {r["match_id"] for r in rows}
    todo = [m for m in match_ids if m not in known]

    saved = 0
    for match_id in todo:
        try:
            data = await riot.get_match(match_id)
        except RiotError as e:
            if e.status == 404:      # 커스텀 게임 등 조회 불가
                continue
            raise
        await _save_match(data)
        saved += 1

    async with pool().acquire() as conn:
        await conn.execute(
            "insert into sync_state (puuid, last_match_sync) values ($1, now()) "
            "on conflict (puuid) do update set last_match_sync = now()",
            puuid,
        )

    return {"fetched": saved, "skipped": len(known)}


async def sync_rank(riot: RiotClient, puuid: str) -> None:
    """솔랭·자유랭 티어를 새 스냅샷으로 기록한다."""
    entries = await riot.get_league_entries(puuid)
    async with pool().acquire() as conn:
        async with conn.transaction():
            for e in entries:
                if e["queueType"] in RANKED_QUEUES:
                    await conn.execute(
                        "insert into rank_snapshots "
                        "(puuid, queue_type, tier, division, league_points, wins, losses) "
                        "values ($1,$2,$3,$4,$5,$6,$7)",
                        puuid, e["queueType"], e["tier"], e["rank"],
                        e["leaguePoints"], e["wins"], e["losses"])
            await conn.execute(
                "insert into sync_state (puuid, last_rank_sync) values ($1, now()) "
                "on conflict (puuid) do update set last_rank_sync = now()",
                puuid)


async def _save_match(data: dict, store_raw: bool = True) -> None:
    info = data["info"]
    match_id = data["metadata"]["matchId"]
    started = datetime.fromtimestamp(
        info.get("gameStartTimestamp", info["gameCreation"]) / 1000, tz=timezone.utc
    )

    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "insert into matches "
                "(match_id, source, queue_id, game_mode, game_start, duration_sec, raw) "
                "values ($1, 'riot', $2, $3, $4, $5, $6::jsonb) "
                "on conflict (match_id) do nothing",
                match_id, info.get("queueId"), info.get("gameMode"),
                started, info.get("gameDuration"),
                json.dumps(data) if store_raw else None,
            )
            for p in info["participants"]:
                pos = p.get("teamPosition") or p.get("individualPosition")
                if pos not in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"):
                    pos = None
                await conn.execute(
                    "insert into match_participants "
                    "(match_id, puuid, team_id, champion_id, champion_name, position, "
                    " kills, deaths, assists, damage_dealt, gold_earned, cs, vision_score, win) "
                    "values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) "
                    "on conflict (match_id, puuid) do nothing",
                    match_id, p["puuid"], p.get("teamId"), p.get("championId"),
                    p.get("championName"),
                    pos,
                    p.get("kills", 0), p.get("deaths", 0), p.get("assists", 0),
                    p.get("totalDamageDealtToChampions", 0), p.get("goldEarned", 0),
                    p.get("totalMinionsKilled", 0) + p.get("neutralMinionsKilled", 0),
                    p.get("visionScore", 0), p.get("win", False),
                )