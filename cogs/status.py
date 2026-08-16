import discord
from discord import app_commands
from discord.ext import commands

from core.db import pool
from core.ui import ActionButton, panel

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


def call_handler(missing: list[int]):
    async def handler(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "관리자만 사용할 수 있습니다.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{mentions(missing)}\n"
            "아직 롤 계정이 연결되지 않았습니다. "
            "`/등록` 에 `이름#태그` 를 입력해 주세요.")
    return handler


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
        if not members:
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

        sections: list[tuple] = [(
            "현황",
            f"서버원 **{len(members)}명** 중 "
            f"등록 **{len(done) + len(stale)}명** · 미등록 **{len(missing)}명**")]

        if missing:
            sections.append((f"미등록 · {len(missing)}명", mentions(missing)))
        if stale:
            sections.append((f"전적 미수집 · {len(stale)}명",
                             mentions(stale) +
                             "\n관리자가 `/전체갱신` 을 실행해 주세요."))
        if not missing and not stale:
            sections.append(("상태", "전원 등록과 전적 수집이 완료됐습니다."))

        actions = ([ActionButton("미등록자 호출", call_handler(missing),
                                 discord.ButtonStyle.primary)]
                   if missing else None)
        footer = f"테스트 계정 {virtual}개는 집계에서 제외했습니다." if virtual else None

        await interaction.followup.send(
            view=panel(f"{guild.name} 계정 등록 현황", sections,
                       footer=footer, actions=actions))


async def setup(bot: commands.Bot):
    await bot.add_cog(Status(bot))