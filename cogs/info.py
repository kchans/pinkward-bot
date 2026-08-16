import discord
from discord import app_commands
from discord.ext import commands

BOT_NAME = "핑크와드봇"
VERSION = "0.1.0"

LEGAL = (
    f"{BOT_NAME} isn't endorsed by Riot Games and doesn't reflect the views or "
    "opinions of Riot Games or anyone officially involved in producing or "
    "managing Riot Games properties. Riot Games, and all associated properties "
    "are trademarks or registered trademarks of Riot Games, Inc."
)

USER_COMMANDS = [
    ("/등록", "내 롤 계정을 이 서버에 연결"),
    ("/내계정", "현재 등록된 계정 확인"),
    ("/등록현황", "서버원의 계정 등록 상태 확인"),
    ("/갱신", "내 최근 전적과 티어 불러오기"),
    ("/오버롤", "내 카드 보기"),
    ("/포지션순위", "특정 포지션의 서버 순위"),
    ("/명예의전당", "티어 순위와 주간 기록"),
    ("/내전", "내전 모집과 자동 팀 배정"),
    ("/내전순위", "내전 전적 순위"),
    ("/정보", "이 안내 보기"),
]

ADMIN_COMMANDS = [
    ("/전체갱신", "서버 전원의 전적 일괄 수집"),
    ("/테스트등록", "디스코드 계정 없이 롤 계정 추가"),
    ("/테스트해제", "가상 참가자 전체 삭제"),
]


def _block(items) -> str:
    return "\n".join(f"`{name}` — {desc}" for name, desc in items)


class Info(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="정보", description="봇 사용법과 고지사항을 봅니다.")
    async def info(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{BOT_NAME} v{VERSION}",
            description="롤 내전과 서버 랭킹을 돕는 봇입니다.\n"
                        "먼저 `/등록` 으로 계정을 연결한 뒤 `/갱신` 을 실행하세요.",
            color=0xE91E63,
        )
        embed.add_field(name="명령어", value=_block(USER_COMMANDS), inline=False)
        embed.add_field(name="관리자 전용", value=_block(ADMIN_COMMANDS), inline=False)
        embed.add_field(
            name="밸런싱 지수 안내",
            value="포지션별 지수는 **내전 팀 배정 전용** 참고값입니다. "
                  "라이엇 공식 랭크를 대체하거나 매치메이킹 등급을 추정하지 않으며, "
                  "이 서버 안에서만 유효합니다.",
            inline=False,
        )
        embed.add_field(name="고지", value=LEGAL, inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Info(bot))