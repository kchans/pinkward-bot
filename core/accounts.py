from core.db import pool

VIRTUAL_ID = 0   # 디스코드 계정이 없는 가상 참가자


def member_label(row) -> str:
    """임베드에 표시할 이름. 가상 참가자는 멘션 대신 이름."""
    if row["is_virtual"]:
        return f"**{row['display_name'] or row['game_name']}**"
    return f"<@{row['discord_user_id']}>"


async def register_account(riot, guild, riot_id: str, discord_user_id: int,
                           *, display_name=None, is_virtual=False):
    """라이엇 계정을 조회해 DB에 등록한다."""
    game_name, _, tag_line = riot_id.rpartition("#")
    acc = await riot.get_account(game_name.strip(), tag_line.strip())
    puuid = acc["puuid"]
    summoner = await riot.get_summoner(puuid)
    entries = await riot.get_league_entries(puuid)
    solo = next((e for e in entries if e["queueType"] == "RANKED_SOLO_5x5"), None)

    async with pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "insert into guilds (guild_id, name) values ($1,$2) "
                "on conflict (guild_id) do update set name = excluded.name",
                guild.id, guild.name)
            await conn.execute(
                "insert into summoners "
                "(puuid, game_name, tag_line, profile_icon_id, summoner_level, updated_at) "
                "values ($1,$2,$3,$4,$5, now()) "
                "on conflict (puuid) do update set game_name = excluded.game_name, "
                "  tag_line = excluded.tag_line, profile_icon_id = excluded.profile_icon_id, "
                "  summoner_level = excluded.summoner_level, updated_at = now()",
                puuid, acc["gameName"], acc["tagLine"],
                summoner.get("profileIconId"), summoner.get("summonerLevel"))

            if not is_virtual:
                # 한 사람당 계정 하나. 기존 등록은 교체한다.
                await conn.execute(
                    "delete from guild_members "
                    "where guild_id = $1 and discord_user_id = $2 and puuid <> $3",
                    guild.id, discord_user_id, puuid)

            await conn.execute(
                "insert into guild_members "
                "(guild_id, discord_user_id, puuid, is_main, display_name, is_virtual) "
                "values ($1,$2,$3,$4,$5,$6) "
                "on conflict (guild_id, puuid) do update set "
                "  discord_user_id = excluded.discord_user_id, "
                "  is_main = excluded.is_main, display_name = excluded.display_name, "
                "  is_virtual = excluded.is_virtual",
                guild.id, discord_user_id, puuid,
                not is_virtual, display_name, is_virtual)

            for e in entries:
                if e["queueType"] in ("RANKED_SOLO_5x5", "RANKED_FLEX_SR"):
                    await conn.execute(
                        "insert into rank_snapshots "
                        "(puuid, queue_type, tier, division, league_points, wins, losses) "
                        "values ($1,$2,$3,$4,$5,$6,$7)",
                        puuid, e["queueType"], e["tier"], e["rank"],
                        e["leaguePoints"], e["wins"], e["losses"])

    return acc, summoner, solo