import discord
from discord import app_commands
from discord.ext import commands

from core.card import render_profile_card
from core.champions import korean_name
from core.db import pool
from core.ovr import POSITIONS, POSITION_KO, overall_ovr, refresh_ovr
from core.stats import MIN_GAMES, player_profile
from core.tier import tier_label
from core.ui import ActionButton, panel

BY_DISCORD_SQL = """
select s.puuid, s.game_name, s.tag_line
from guild_members m join summoners s on s.puuid = m.puuid
where m.guild_id = $1 and m.discord_user_id = $2
order by m.is_main desc limit 1
"""

BY_RIOT_ID_SQL = """
select s.puuid, s.game_name, s.tag_line
from guild_members m join summoners s on s.puuid = m.puuid
where m.guild_id = $1 and lower(s.game_name) = lower($2)
  and lower(s.tag_line) = lower($3)
limit 1
"""

ALL_RATINGS_SQL = """
select pr.puuid, pr.position, pr.ovr, pr.games,
       s.game_name, m.discord_user_id, m.is_virtual, m.display_name
from position_ratings pr
join guild_members m on m.puuid = pr.puuid and m.guild_id = $1
join summoners s     on s.puuid = pr.puuid
"""

POSITION_CHOICES = [
    app_commands.Choice(name=POSITION_KO[p], value=p) for p in POSITIONS
]


class Ovr(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- 카드 ----------

    @app_commands.command(name="오버롤", description="내 카드를 봅니다.")
    @app_commands.rename(user="유저", riot_id="라이엇id")
    @app_commands.describe(user="디스코드 유저로 조회",
                           riot_id="이름#태그로 조회 (테스트 계정용)")
    @app_commands.guild_only()
    async def ovr(self, interaction: discord.Interaction,
                  user: discord.Member | None = None,
                  riot_id: str | None = None):
        await interaction.response.defer(thinking=True)

        async with pool().acquire() as conn:
            if riot_id and "#" in riot_id:
                gn, _, tl = riot_id.rpartition("#")
                row = await conn.fetchrow(
                    BY_RIOT_ID_SQL, interaction.guild_id, gn.strip(), tl.strip())
                missing = f"`{riot_id}` 는 이 서버에 등록되어 있지 않습니다."
            else:
                target = user or interaction.user
                row = await conn.fetchrow(
                    BY_DISCORD_SQL, interaction.guild_id, target.id)
                missing = f"{target.display_name} 님은 아직 `/등록` 하지 않았습니다."

        if row is None:
            await interaction.followup.send(missing)
            return

        p = await player_profile(row["puuid"])
        if p is None:
            await interaction.followup.send(
                f"표본이 부족합니다. 최소 {MIN_GAMES}판이 필요합니다. "
                "`/갱신` 을 먼저 실행해 주세요.")
            return

        perf = sum(p["stats"].values()) / len(p["stats"])
        await refresh_ovr(row["puuid"], perf=perf)          # 밸런싱용 지수 갱신
        ovr, _ = await overall_ovr(row["puuid"], perf=perf)  # 카드에 쓸 종합 지수
        main = p["main_position"]

        async with pool().acquire() as conn:
            tier_row = await conn.fetchrow(
                "select tier, division, league_points from rank_snapshots "
                "where puuid = $1 and queue_type = 'RANKED_SOLO_5x5' "
                "order by fetched_at desc limit 1",
                row["puuid"])

        champ_ko = await korean_name(p["champion"])
        buf = await render_profile_card({
            "name": row["game_name"],
            "tier": tier_label(tier_row["tier"], tier_row["division"],
                               tier_row["league_points"]) if tier_row else "언랭",
            "tier_key": tier_row["tier"] if tier_row else "",
            "position": POSITION_KO[main],
            "ovr": ovr,
            "badge": champ_ko,
            "sub": f"최다 픽 {p['champion_picks']}판 · "
                   f"{POSITION_KO[main]} {p['raw']['games']}판",
            "stats": p["stats"],
            "champion": p["champion"],
        })

        await interaction.followup.send(
            file=discord.File(buf, filename="card.png"))

    # ---------- 포지션 순위 ----------

    def _switch(self, position: str):
        async def handler(interaction: discord.Interaction):
            view = await self._position_panel(interaction.guild, position)
            if view is None:
                await interaction.response.send_message(
                    "지수 데이터가 없습니다.", ephemeral=True)
                return
            await interaction.response.edit_message(view=view)
        return handler

    async def _position_panel(self, guild: discord.Guild, position: str):
        async with pool().acquire() as conn:
            rows = await conn.fetch(ALL_RATINGS_SQL, guild.id)
        if not rows:
            return None

        by_player: dict[str, dict] = {}
        for r in rows:
            by_player.setdefault(r["puuid"], {})[r["position"]] = r

        entries = []
        for rows_by_pos in by_player.values():
            row = rows_by_pos.get(position)
            if row is None:
                continue
            main_pos = max(rows_by_pos, key=lambda p: rows_by_pos[p]["games"])
            entries.append((row, main_pos == position and row["games"] > 0))

        if not entries:
            body = "이 포지션의 데이터가 없습니다."
        else:
            entries.sort(key=lambda e: e[0]["ovr"], reverse=True)
            lines = []
            for i, (r, is_main) in enumerate(entries[:20], 1):
                name = (f"**{r['display_name'] or r['game_name']}**"
                        if r["is_virtual"] else f"<@{r['discord_user_id']}>")
                mark = " `주`" if is_main else ""
                lines.append(
                    f"`{i:>2}.` {name} — **{r['ovr']}** ({r['games']}판){mark}")
            body = "\n".join(lines)

        buttons = [
            ActionButton(
                POSITION_KO[p], self._switch(p),
                discord.ButtonStyle.primary if p == position
                else discord.ButtonStyle.secondary)
            for p in POSITIONS]

        return panel(f"{guild.name} · {POSITION_KO[position]} 순위",
                     [("", body)],
                     footer="`주` 표시는 해당 포지션이 주 라인인 사람",
                     actions=buttons)

    @app_commands.command(name="포지션순위",
                          description="특정 포지션의 서버 순위를 봅니다.")
    @app_commands.rename(position="포지션")
    @app_commands.choices(position=POSITION_CHOICES)
    @app_commands.guild_only()
    async def position_ranking(self, interaction: discord.Interaction,
                               position: app_commands.Choice[str]):
        await interaction.response.defer(thinking=True)
        view = await self._position_panel(interaction.guild, position.value)
        if view is None:
            await interaction.followup.send(
                "지수 데이터가 없습니다. `/전체갱신` 을 먼저 실행하세요.")
            return
        await interaction.followup.send(view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ovr(bot))