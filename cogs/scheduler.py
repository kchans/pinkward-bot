import logging

from discord.ext import commands, tasks
from dotenv import dotenv_values

from core.db import pool
from core.ovr import refresh_ovr
from core.riot import RiotError
from core.sync import sync_matches, sync_rank

log = logging.getLogger("scheduler")

INTERVAL_MINUTES = 10     # 실행 주기
BATCH = 5                 # 한 번에 갱신할 인원
MATCHES_PER_RUN = 10      # 1인당 확인할 최근 경기 수

DUE_SQL = """
select gm.puuid,
       min(coalesce(ss.last_match_sync, 'epoch'::timestamptz)) as last_sync
from guild_members gm
left join sync_state ss on ss.puuid = gm.puuid
group by gm.puuid
order by last_sync asc
limit $1
"""


class Scheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_refresh.start()

    def cog_unload(self):
        self.auto_refresh.cancel()

    def _reload_key(self) -> None:
        """.env 의 API 키가 바뀌었으면 재시작 없이 반영한다."""
        key = dotenv_values(".env").get("RIOT_API_KEY")
        if key and key != self.bot.riot.key:
            self.bot.riot.key = key
            log.info("API 키를 새로 읽었습니다.")

    @tasks.loop(minutes=INTERVAL_MINUTES)
    async def auto_refresh(self):
        self._reload_key()

        async with pool().acquire() as conn:
            rows = await conn.fetch(DUE_SQL, BATCH)
        if not rows:
            return

        done = 0
        for r in rows:
            puuid = r["puuid"]
            try:
                await sync_rank(self.bot.riot, puuid)
                await sync_matches(self.bot.riot, puuid, count=MATCHES_PER_RUN)
                await refresh_ovr(puuid)
                done += 1
            except RiotError as e:
                if e.status == 403:
                    log.warning("API 키가 만료되었습니다. 이번 주기를 건너뜁니다.")
                    return
                log.warning("갱신 실패 %s — %s", puuid[:12], e)
            except Exception as e:
                log.warning("갱신 오류 %s — %s", puuid[:12], e)

        log.info("자동 갱신 %d/%d명 완료", done, len(rows))

    @auto_refresh.before_loop
    async def before_auto_refresh(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Scheduler(bot))