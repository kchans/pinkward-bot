import discord
from discord import app_commands
from discord.ext import commands

from core.db import pool
from core.tier import tier_score, tier_label

RANK_SQL = """
select distinct on (r.puuid)
       r.puuid, s.game_name, m.discord_user_id, m.is_virtual, m.display_name,
       r.tier, r.division, r.league_points
from guild_members m
join summoners s      on s.puuid = m.puuid
join rank_snapshots r on r.puuid = m.puuid
where m.guild_id = $1 and r.queue_type = 'RANKED_SOLO_5x5'
order by r.puuid, r.fetched_at desc
"""

WEEKLY_SQL = """
select m.discord_user_id, m.is_virtual, m.display_name, s.game_name,
       count(*)                                as games,
       sum(p.kills)                            as kills,
       sum(case when p.win then 1 else 0 end)  as wins
from guild_members m
join summoners s          on s.puuid = m.puuid
join match_participants p on p.puuid = m.puuid
join matches mt           on mt.match_id = p.match_id
where m.guild_id = $1
  and mt.source = 'riot'
  and mt.game_start >= now() - interval '7 days'
group by m.discord_user_id, m.is_virtual, m.display_name, s.game_name
"""

SCRIM_SQL = """
select p.puuid, m.discord_user_id, m.is_virtual, m.display_name, s.game_name,
       count(*)                                as games,
       sum(case when p.win then 1 else 0 end)  as wins
from match_participants p
join matches mt       on mt.match_id = p.match_id
join guild_members m  on m.puuid = p.puuid and m.guild_id = $1
join summoners s      on s.puuid = p.puuid
where mt.source = 'scrim' and mt.guild_id = $1
group by p.puuid, m.discord_user_id, m.is_virtual, m.display_name, s.game_name
"""

SCRIM_HISTORY_SQL = """
select p.puuid, p.win
from match_participants p
join matches mt on mt.match_id = p.match_id
where mt.source = 'scrim' and mt.guild_id = $1
order by mt.game_start desc
"""

MEDAL = ("1위", "2위", "3위")


def label(r) -> str:
    if r["is_virtual"]:
        return f"**{r['display_name'] or r['game_name']}**"
    return f"<@{r['discord_user_id']}>"


def _top(rows, key, fmt, limit=3):
    ranked = sorted(rows, key=key, reverse=True)[:limit]
    if not ranked:
        return "기록 없음"
    return "\n".join(
        f"`{MEDAL[i]}` {label(r)} — {fmt(r)}" for i, r in enumerate(ranked))


def streaks(history) -> dict[str, tuple[bool, int]]:
    """puuid → (최근 결과가 승리인가, 연속 횟수)"""
    out: dict[str, tuple[bool, int]] = {}
    done: set[str] = set()
    for row in history:                      # 최신순
        puuid, win = row["puuid"], row["win"]
        if puuid in done:
            continue
        if puuid not in out:
            out[puuid] = (win, 1)
        elif out[puuid][0] == win:
            out[puuid] = (win, out[puuid][1] + 1)
        else:
            done.add(puuid)
    return out


class HallOfFame(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="명예의전당", description="이 서버의 랭킹을 보여줍니다.")
    @app_commands.guild_only()
    async def hall_of_fame(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        gid = interaction.guild_id

        async with pool().acquire() as conn:
            ranks = await conn.fetch(RANK_SQL, gid)
            weekly = await conn.fetch(WEEKLY_SQL, gid)

        if not ranks and not weekly:
            await interaction.followup.send(
                "아직 데이터가 없습니다. `/등록` 후 `/전체갱신` 을 실행해주세요.")
            return

        embed = discord.Embed(
            title=f"{interaction.guild.name} 명예의 전당", color=0xE91E63)

        ordered = sorted(
            ranks,
            key=lambda r: tier_score(r["tier"], r["division"], r["league_points"]),
            reverse=True)[:10]
        if ordered:
            lines = [
                f"`{i:>2}.` {label(r)} — "
                f"{tier_label(r['tier'], r['division'], r['league_points'])}"
                for i, r in enumerate(ordered, 1)]
            embed.add_field(name="솔로랭크 티어 순위",
                            value="\n".join(lines), inline=False)

        embed.add_field(
            name="주간 최다 킬",
            value=_top(weekly, lambda r: r["kills"], lambda r: f"{r['kills']}킬"),
            inline=False)
        embed.add_field(
            name="주간 최다 판수",
            value=_top(weekly, lambda r: r["games"], lambda r: f"{r['games']}판"),
            inline=False)

        qualified = [r for r in weekly if r["games"] >= 5]
        embed.add_field(
            name="주간 승률왕 (5판 이상)",
            value=_top(qualified, lambda r: r["wins"] / r["games"],
                       lambda r: f"{round(r['wins'] / r['games'] * 100)}% "
                                 f"({r['wins']}승 {r['games'] - r['wins']}패)"),
            inline=False)

        embed.set_footer(text="최근 7일 · 공식 게임 기준 · /전체갱신 으로 최신화")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="내전순위",
                          description="이 서버의 내전 전적 순위를 보여줍니다.")
    @app_commands.guild_only()
    async def scrim_hall(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        gid = interaction.guild_id

        async with pool().acquire() as conn:
            rows = await conn.fetch(SCRIM_SQL, gid)
            history = await conn.fetch(SCRIM_HISTORY_SQL, gid)

        if not rows:
            await interaction.followup.send(
                "아직 기록된 내전이 없습니다. 내전을 진행하고 승패를 입력해주세요.")
            return

        st = streaks(history)
        MIN_GAMES = 3
        qualified = [r for r in rows if r["games"] >= MIN_GAMES] or list(rows)
        ordered = sorted(
            qualified,
            key=lambda r: (r["wins"] / r["games"], r["games"]),
            reverse=True)[:15]

        lines = []
        for i, r in enumerate(ordered, 1):
            losses = r["games"] - r["wins"]
            rate = round(r["wins"] / r["games"] * 100)
            note = ""
            win, n = st.get(r["puuid"], (False, 0))
            if n >= 2:
                note = f" · **{n}{'연승' if win else '연패'}**"
            lines.append(
                f"`{i:>2}위` {label(r)} — {r['wins']}승 {losses}패 ({rate}%){note}")

        total_games = sum(r["games"] for r in rows) // 10
        embed = discord.Embed(
            title=f"{interaction.guild.name} 내전 순위",
            description="\n".join(lines), color=0xE91E63)
        embed.set_footer(text=f"누적 {total_games}경기 · {MIN_GAMES}판 이상 참가자 기준")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(HallOfFame(bot))