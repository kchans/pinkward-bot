import discord
from discord.ext import commands

from core.config import DISCORD_TOKEN, DISCORD_GUILD_IDS
from core.db import init_pool, close_pool
from core.riot import RiotClient

EXTENSIONS = (
    "cogs.register", "cogs.sync", "cogs.hall_of_fame",
    "cogs.ovr", "cogs.scrim", "cogs.info", "cogs.status",
)


class PinkWardBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.riot = RiotClient()

    async def setup_hook(self):
        await init_pool()
        print("DB 연결 완료")

        for ext in EXTENSIONS:
            await self.load_extension(ext)

        for gid in DISCORD_GUILD_IDS:
            guild = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            print(f"서버 {gid} — 슬래시 명령어 {len(synced)}개 등록")

    async def close(self):
        await self.riot.close()
        await close_pool()
        await super().close()


bot = PinkWardBot()


@bot.event
async def on_ready():
    print(f"로그인 성공: {bot.user}")
    print(f"연결된 서버: {[g.name for g in bot.guilds]}")


@bot.tree.command(name="핑", description="봇이 살아있는지 확인합니다.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"퐁! 응답속도 {round(bot.latency * 1000)}ms")


bot.run(DISCORD_TOKEN)