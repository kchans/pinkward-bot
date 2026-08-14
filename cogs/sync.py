import discord
from discord import app_commands
from discord.ext import commands

from core.db import pool
from core.ovr import refresh_ovr
from core.sync import sync_matches, sync_rank


class Sync(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="갱신", description="내 최근 전적을 불러옵니다.")
    @app_commands.rename(count="개수")
    @app_commands.describe(count="가져올 최근 경기 수 (기본 20, 최대 50)")
    @app_commands.guild_only()
    async def sync(self, interaction: discord.Interaction, count: int = 20):
        await interaction.response.defer(thinking=True)
        count = max(1, min(count, 50))

        async with pool().acquire() as conn:
            row = await conn.fetchrow(
                "select s.puuid, s.game_name, s.tag_line "
                "from guild_members m join summoners s on s.puuid = m.puuid "
                "where m.guild_id = $1 and m.discord_user_id = $2 "
                "order by m.is_main desc limit 1",
                interaction.guild_id, interaction.user.id,
            )
        if row is None:
            await interaction.followup.send("먼저 `/등록` 으로 계정을 연결해주세요.")
            return

        result = await sync_matches(self.bot.riot, row["puuid"], count=count)
        await sync_rank(self.bot.riot, row["puuid"])
        await refresh_ovr(row["puuid"])

        embed = discord.Embed(
            title="전적 갱신 완료",
            description=f"**{row['game_name']}#{row['tag_line']}**",
            color=0xE91E63,
        )
        embed.add_field(name="새로 저장", value=f"{result['fetched']}경기")
        embed.add_field(name="이미 보유", value=f"{result['skipped']}경기")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="전체갱신",
                          description="[관리자] 서버 전체 유저의 전적을 수집합니다.")
    @app_commands.rename(count="개수")
    @app_commands.describe(count="1인당 가져올 경기 수 (기본 30)")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def sync_all(self, interaction: discord.Interaction, count: int = 30):
        await interaction.response.defer(thinking=True)
        count = max(1, min(count, 50))

        async with pool().acquire() as conn:
            rows = await conn.fetch(
                "select s.puuid, s.game_name from guild_members m "
                "join summoners s on s.puuid = m.puuid "
                "where m.guild_id = $1 order by m.registered_at",
                interaction.guild_id)

        if not rows:
            await interaction.followup.send("등록된 계정이 없습니다.")
            return

        total_new, failed = 0, []
        for i, r in enumerate(rows, 1):
            await interaction.edit_original_response(
                content=f"전적 수집 중... ({i}/{len(rows)}) {r['game_name']}")
            try:
                result = await sync_matches(self.bot.riot, r["puuid"], count=count)
                total_new += result["fetched"]
                await sync_rank(self.bot.riot, r["puuid"])
                await refresh_ovr(r["puuid"])
            except Exception as e:
                print(f"[전체갱신] {r['game_name']} 실패: {e}")
                failed.append(r["game_name"])

        msg = f"완료 · {len(rows)}명 처리 · 새 경기 {total_new}개 저장"
        if failed:
            msg += f"\n실패: {', '.join(failed)}"
        await interaction.edit_original_response(content=msg)


async def setup(bot: commands.Bot):
    await bot.add_cog(Sync(bot))