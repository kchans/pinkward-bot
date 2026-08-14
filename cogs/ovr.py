import discord
from discord import app_commands
from discord.ext import commands

from core.db import pool
from core.ovr import POSITIONS, POSITION_KO, refresh_ovr
from core.tier import tier_label

ICON_URL = ("https://raw.communitydragon.org/latest/plugins/"
            "rcp-be-lol-game-data/global/default/v1/profile-icons/{}.jpg")

BY_DISCORD_SQL = """
select s.puuid, s.game_name, s.tag_line, s.profile_icon_id
from guild_members m join summoners s on s.puuid = m.puuid
where m.guild_id = $1 and m.discord_user_id = $2
order by m.is_main desc limit 1
"""

BY_RIOT_ID_SQL = """
select s.puuid, s.game_name, s.tag_line, s.profile_icon_id
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


def name_of(r) -> str:
    if r["is_virtual"]:
        return f"**{r['display_name'] or r['game_name']}**"
    return f"<@{r['discord_user_id']}>"


class Ovr(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="오버롤", description="포지션별 밸런싱 지수를 봅니다.")
    @app_commands.rename(user="유저", riot_id="라이엇id")
    @app_commands.describe(user="디스코드 유저로 조회",
                           riot_id="이름#태그로 조회 (테스트 계정용)")
    @app_commands.guild_only()
    async def ovr(self, interaction: discord.Interaction,
                  user: discord.Member | None = None,
                  riot_id: str | None = None):
        await interaction.response.defer(thinking=True)

        async with pool().acquire() as conn:
            if riot_id:
                if "#" not in riot_id:
                    await interaction.followup.send("`이름#태그` 형식으로 입력하세요.")
                    return
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

        ratings, games, source = await refresh_ovr(row["puuid"])

        async with pool().acquire() as conn:
            tier = await conn.fetchrow(
                "select tier, division, league_points from rank_snapshots "
                "where puuid = $1 and queue_type = $2 "
                "order by fetched_at desc limit 1",
                row["puuid"],
                "RANKED_SOLO_5x5" if source == "솔로랭크" else "RANKED_FLEX_SR")

        desc = (f"{source} {tier_label(tier['tier'], tier['division'], tier['league_points'])}"
                if tier else "랭크 기록 없음")

        main_pos = max(POSITIONS, key=lambda p: games.get(p, 0))
        best_pos = max(POSITIONS, key=lambda p: ratings[p])

        lines = []
        for p in POSITIONS:
            tags = []
            if p == main_pos and games.get(p, 0) > 0:
                tags.append("주")
            if p == best_pos:
                tags.append("최고")
            mark = f"  [{'/'.join(tags)}]" if tags else ""
            lines.append(
                f"{POSITION_KO[p]:<3} {ratings[p]:>3}   ({games.get(p, 0):>2}판){mark}")

        embed = discord.Embed(
            title=f"{row['game_name']}#{row['tag_line']}",
            description=desc, color=0xE91E63)
        embed.add_field(name="포지션 실력 지수",
                        value="```\n" + "\n".join(lines) + "\n```")
        if row["profile_icon_id"] is not None:
            embed.set_thumbnail(url=ICON_URL.format(row["profile_icon_id"]))
        embed.set_footer(text="최근 50판 + 랭크 티어 기준 · 내전 배정 참고용")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="포지션순위",
                          description="특정 포지션의 서버 순위를 봅니다.")
    @app_commands.rename(position="포지션")
    @app_commands.choices(position=POSITION_CHOICES)
    @app_commands.guild_only()
    async def position_ranking(self, interaction: discord.Interaction,
                               position: app_commands.Choice[str]):
        await interaction.response.defer(thinking=True)

        async with pool().acquire() as conn:
            rows = await conn.fetch(ALL_RATINGS_SQL, interaction.guild_id)

        if not rows:
            await interaction.followup.send(
                "지수 데이터가 없습니다. `/전체갱신` 을 먼저 실행하세요.")
            return

        # 사람별로 묶어 주포지션을 판별한다
        by_player: dict[str, dict] = {}
        for r in rows:
            p = by_player.setdefault(r["puuid"], {"rows": {}, "meta": r})
            p["rows"][r["position"]] = r

        target = position.value
        entries = []
        for puuid, p in by_player.items():
            row = p["rows"].get(target)
            if row is None:
                continue
            main_pos = max(p["rows"], key=lambda pos: p["rows"][pos]["games"])
            is_main = (main_pos == target and p["rows"][main_pos]["games"] > 0)
            entries.append((row, is_main))

        if not entries:
            await interaction.followup.send("해당 포지션의 데이터가 없습니다.")
            return

        entries.sort(key=lambda e: e[0]["ovr"], reverse=True)

        lines = []
        for i, (r, is_main) in enumerate(entries[:20], 1):
            mark = " `주`" if is_main else ""
            lines.append(
                f"`{i:>2}.` {name_of(r)} — **{r['ovr']}** ({r['games']}판){mark}")

        embed = discord.Embed(
            title=f"{interaction.guild.name} · {position.name} 순위",
            description="\n".join(lines), color=0xE91E63)
        embed.set_footer(
            text="`주` 표시는 해당 포지션이 주 라인인 사람 · 내전 배정 참고용")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ovr(bot))