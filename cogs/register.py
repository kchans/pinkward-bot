import discord
from discord import app_commands
from discord.ext import commands

from core.accounts import VIRTUAL_ID, register_account
from core.db import pool
from core.riot import RiotError
from core.tier import tier_label

ICON_URL = ("https://raw.communitydragon.org/latest/plugins/"
            "rcp-be-lol-game-data/global/default/v1/profile-icons/{}.jpg")


def _error_message(e: RiotError, riot_id: str) -> str:
    return {
        404: f"`{riot_id}` 계정을 찾을 수 없습니다.",
        403: "API 키가 만료됐습니다. 봇 관리자에게 알려주세요.",
    }.get(e.status, f"조회 중 오류가 발생했습니다. (코드 {e.status})")


class Register(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="등록", description="내 롤 계정을 등록합니다. (다시 하면 교체)")
    @app_commands.rename(riot_id="라이엇id")
    @app_commands.describe(riot_id="이름#태그 형식 (예: 핑크와드#KR1)")
    @app_commands.guild_only()
    async def register(self, interaction: discord.Interaction, riot_id: str):
        await interaction.response.defer(thinking=True)
        if "#" not in riot_id:
            await interaction.followup.send("형식이 잘못됐습니다. `이름#태그` 로 입력하세요.")
            return
        try:
            acc, summoner, solo = await register_account(
                self.bot.riot, interaction.guild, riot_id, interaction.user.id)
        except RiotError as e:
            await interaction.followup.send(_error_message(e, riot_id))
            return

        embed = discord.Embed(
            title="계정 등록 완료",
            description=f"**{acc['gameName']}#{acc['tagLine']}**",
            color=0xE91E63)
        embed.add_field(name="레벨", value=str(summoner.get("summonerLevel", "?")))
        embed.add_field(
            name="솔로랭크",
            value=(f"{tier_label(solo['tier'], solo['rank'], solo['leaguePoints'])}\n"
                   f"{solo['wins']}승 {solo['losses']}패") if solo else "언랭")
        if summoner.get("profileIconId") is not None:
            embed.set_thumbnail(url=ICON_URL.format(summoner["profileIconId"]))
        embed.set_footer(text=f"{interaction.user.display_name} 님의 계정 · 다시 /등록 하면 교체됩니다")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="내계정", description="현재 등록된 내 계정을 확인합니다.")
    @app_commands.guild_only()
    async def my_account(self, interaction: discord.Interaction):
        async with pool().acquire() as conn:
            row = await conn.fetchrow(
                "select s.game_name, s.tag_line from guild_members m "
                "join summoners s on s.puuid = m.puuid "
                "where m.guild_id = $1 and m.discord_user_id = $2",
                interaction.guild_id, interaction.user.id)
        msg = (f"현재 등록 계정: **{row['game_name']}#{row['tag_line']}**"
               if row else "등록된 계정이 없습니다. `/등록` 을 실행하세요.")
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="테스트등록",
                          description="[관리자] 디스코드 계정 없이 롤 계정을 추가합니다.")
    @app_commands.rename(riot_id="라이엇id", nickname="별명")
    @app_commands.describe(riot_id="이름#태그", nickname="명예의전당에 표시할 이름")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def add_virtual(self, interaction: discord.Interaction,
                          riot_id: str, nickname: str | None = None):
        await interaction.response.defer(thinking=True, ephemeral=True)
        if "#" not in riot_id:
            await interaction.followup.send("형식이 잘못됐습니다. `이름#태그` 로 입력하세요.")
            return
        try:
            acc, _, solo = await register_account(
                self.bot.riot, interaction.guild, riot_id, VIRTUAL_ID,
                display_name=nickname or riot_id.split("#")[0], is_virtual=True)
        except RiotError as e:
            await interaction.followup.send(_error_message(e, riot_id))
            return
        rank = tier_label(solo["tier"], solo["rank"], solo["leaguePoints"]) if solo else "언랭"
        await interaction.followup.send(
            f"가상 참가자 추가: **{acc['gameName']}#{acc['tagLine']}** ({rank})")

    @app_commands.command(name="테스트해제", description="[관리자] 가상 참가자를 전부 삭제합니다.")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    async def clear_virtual(self, interaction: discord.Interaction):
        async with pool().acquire() as conn:
            result = await conn.execute(
                "delete from guild_members where guild_id = $1 and is_virtual",
                interaction.guild_id)
        await interaction.response.send_message(
            f"가상 참가자를 삭제했습니다. ({result})", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Register(bot))