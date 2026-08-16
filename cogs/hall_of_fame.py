import discord
from discord import app_commands
from discord.ext import commands
from core.ui import ActionButton, panel

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

    # ---------- 빌더 ----------

    async def _hall_panel(self, guild: discord.Guild):
        async with pool().acquire() as conn:
            ranks = await conn.fetch(RANK_SQL, guild.id)
            weekly = await conn.fetch(WEEKLY_SQL, guild.id)

        if not ranks and not weekly:
            return None

        sections: list[tuple] = []
        ordered = sorted(
            ranks,
            key=lambda r: tier_score(r["tier"], r["division"], r["league_points"]),
            reverse=True)[:10]
        if ordered:
            lines = [
                f"`{i:>2}.` {label(r)} — "
                f"{tier_label(r['tier'], r['division'], r['league_points'])}"
                for i, r in enumerate(ordered, 1)]
            sections.append(("솔로랭크 티어 순위", "\n".join(lines)))

        sections.append(("주간 최다 킬",
                         _top(weekly, lambda r: r["kills"],
                              lambda r: f"{r['kills']}킬")))
        sections.append(("주간 최다 판수",
                         _top(weekly, lambda r: r["games"],
                              lambda r: f"{r['games']}판")))

        qualified = [r for r in weekly if r["games"] >= 5]
        sections.append(("주간 승률왕 (5판 이상)",
                         _top(qualified, lambda r: r["wins"] / r["games"],
                              lambda r: f"{round(r['wins'] / r['games'] * 100)}% "
                                        f"({r['wins']}승 {r['games'] - r['wins']}패)")))

        return panel(
            f"{guild.name} 명예의 전당", sections,
            footer="최근 7일 · 공식 게임 기준 · /전체갱신 으로 최신화",
            actions=[
                ActionButton("새로고침", self._refresh_hall),
                ActionButton("내전순위 바로가기", self._show_scrim,
                             discord.ButtonStyle.primary),
            ])

    async def _scrim_panel(self, guild: discord.Guild):
        async with pool().acquire() as conn:
            rows = await conn.fetch(SCRIM_SQL, guild.id)
            history = await conn.fetch(SCRIM_HISTORY_SQL, guild.id)

        if not rows:
            return None

        st = streaks(history)
        min_games = 3
        qualified = [r for r in rows if r["games"] >= min_games] or list(rows)
        ordered = sorted(qualified,
                         key=lambda r: (r["wins"] / r["games"], r["games"]),
                         reverse=True)[:15]

        lines = []
        for i, r in enumerate(ordered, 1):
            losses = r["games"] - r["wins"]
            rate = round(r["wins"] / r["games"] * 100)
            win, n = st.get(r["puuid"], (False, 0))
            note = f" · **{n}{'연승' if win else '연패'}**" if n >= 2 else ""
            lines.append(
                f"`{i:>2}위` {label(r)} — {r['wins']}승 {losses}패 ({rate}%){note}")

        total_games = sum(r["games"] for r in rows) // 10
        return panel(
            f"{guild.name} 내전 순위",
            [("", "\n".join(lines))],
            footer=f"누적 {total_games}경기 · {min_games}판 이상 참가자 기준",
            actions=[
                ActionButton("새로고침", self._refresh_scrim),
                ActionButton("명예의전당 바로가기", self._show_hall,
                             discord.ButtonStyle.primary),
            ])

    
    async def _scrim_panel(self, guild: discord.Guild):
        async with pool().acquire() as conn:
            rows = await conn.fetch(SCRIM_SQL, guild.id)
            history = await conn.fetch(SCRIM_HISTORY_SQL, guild.id)

        if not rows:
            return None

        st = streaks(history)
        min_games = 3
        qualified = [r for r in rows if r["games"] >= min_games] or list(rows)
        ordered = sorted(qualified,
                         key=lambda r: (r["wins"] / r["games"], r["games"]),
                         reverse=True)[:15]

        lines = []
        for i, r in enumerate(ordered, 1):
            losses = r["games"] - r["wins"]
            rate = round(r["wins"] / r["games"] * 100)
            win, n = st.get(r["puuid"], (False, 0))
            note = f" · **{n}{'연승' if win else '연패'}**" if n >= 2 else ""
            lines.append(
                f"`{i:>2}위` {label(r)} — {r['wins']}승 {losses}패 ({rate}%){note}")

        total_games = sum(r["games"] for r in rows) // 10
        return panel(
            f"{guild.name} 내전 순위",
            [("", "\n".join(lines))],
            footer=f"누적 {total_games}경기 · {min_games}판 이상 참가자 기준",
            actions=[
                ActionButton("새로고침", self._refresh_scrim),
                ActionButton("명예의전당 바로가기", self._show_hall,
                             discord.ButtonStyle.primary),
            ])

    # ---------- 버튼 핸들러 ----------

    async def _show_scrim(self, interaction: discord.Interaction):
        view = await self._scrim_panel(interaction.guild)
        if view is None:
            await interaction.response.send_message(
                "아직 기록된 내전이 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(view=view, ephemeral=True)

    async def _show_hall(self, interaction: discord.Interaction):
        view = await self._hall_panel(interaction.guild)
        if view is None:
            await interaction.response.send_message(
                "아직 데이터가 없습니다.", ephemeral=True)
            return
        await interaction.response.send_message(view=view, ephemeral=True)

    async def _refresh_hall(self, interaction: discord.Interaction):
        view = await self._hall_panel(interaction.guild)
        if view is None:
            await interaction.response.send_message(
                "아직 데이터가 없습니다.", ephemeral=True)
            return
        await interaction.response.edit_message(view=view)

    async def _refresh_scrim(self, interaction: discord.Interaction):
        view = await self._scrim_panel(interaction.guild)
        if view is None:
            await interaction.response.send_message(
                "아직 기록된 내전이 없습니다.", ephemeral=True)
            return
        await interaction.response.edit_message(view=view)

    # ---------- 명령어 ----------

    @app_commands.command(name="명예의전당", description="이 서버의 랭킹을 보여줍니다.")
    @app_commands.guild_only()
    async def hall_of_fame(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        view = await self._hall_panel(interaction.guild)
        if view is None:
            await interaction.followup.send(
                "아직 데이터가 없습니다. `/등록` 후 `/전체갱신` 을 실행해주세요.")
            return
        await interaction.followup.send(view=view)

    @app_commands.command(name="내전순위",
                          description="이 서버의 내전 전적 순위를 보여줍니다.")
    @app_commands.guild_only()
    async def scrim_hall(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        view = await self._scrim_panel(interaction.guild)
        if view is None:
            await interaction.followup.send(
                "아직 기록된 내전이 없습니다. 내전을 진행하고 승패를 입력해주세요.")
            return
        await interaction.followup.send(view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(HallOfFame(bot))