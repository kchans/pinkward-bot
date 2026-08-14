import discord
from discord import app_commands
from discord.ext import commands

from core.db import pool

MEMBERS_SQL = """
select gm.discord_user_id, ss.last_match_sync
from guild_members gm
left join sync_state ss on ss.puuid = gm.puuid
where gm.guild_id = $1 and not gm.is_virtual
"""

MAX_SHOW = 35


def mentions(ids: list[int], limit: int = MAX_SHOW) -> str:
    if not ids:
        return "없음"
    text = " ".join(f"<@{i}>" for i in ids[:limit])
    if len(ids) > limit:
        text += f"  외 {len(ids) - limit}명"
    return text


class CallView(discord.ui.View):
    def __init__(self, missing: list[int]):
        super().__init__(timeout=300)
        self.missing = missing

    @discord.ui.button(label="미등록자 호출", style=discord.ButtonStyle.primary)
    async def call(self, interaction: discord.Interaction, _b: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "관리자만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{mentions(self.missing)}\n"
            "아직 롤 계정이 연결되지 않았습니다. "
            "`/등록` 에 `이름#태그` 를 입력해 주세요.")


class Status(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="등록현황",
                          description="서버원의 계정 등록 상태를 봅니다.")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        guild = interaction.guild

        members = [m for m in guild.members if not m.bot]
        if not members:                       # 캐시가 비어 있으면 직접 조회
            members = [m async for m in guild.fetch_members(limit=None) if not m.bot]

        async with pool().acquire() as conn:
            rows = await conn.fetch(MEMBERS_SQL, guild.id)

        registered = {r["discord_user_id"] for r in rows}
        unsynced = {r["discord_user_id"] for r in rows if r["last_match_sync"] is None}

        missing, stale, done = [], [], []
        for m in members:
            if m.id not in registered:
                missing.append(m.id)
            elif m.id in unsynced:
                stale.append(m.id)
            else:
                done.append(m.id)

        virtual = len([r for r in rows if r["discord_user_id"] == 0])

        embed = discord.Embed(
            title=f"{guild.name} 계정 등록 현황",
            description=(f"서버원 **{len(members)}명** 중 "
                         f"등록 **{len(done) + len(stale)}명** · "
                         f"미등록 **{len(missing)}명**"),
            color=0xE91E63,
        )

        if missing:
            embed.add_field(name=f"미등록 · {len(missing)}명",
                            value=mentions(missing), inline=False)
        if stale:
            embed.add_field(
                name=f"전적 미수집 · {len(stale)}명",
                value=mentions(stale) + "\n관리자가 `/전체갱신` 을 실행해 주세요.",
                inline=False)
        if not missing and not stale:
            embed.add_field(name="상태",
                            value="전원 등록과 전적 수집이 완료됐습니다.", inline=False)
        if virtual:
            embed.set_footer(text=f"테스트 계정 {virtual}개는 집계에서 제외했습니다.")

        view = CallView(missing) if missing else None
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Status(bot))