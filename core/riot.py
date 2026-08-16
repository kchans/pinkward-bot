import asyncio
import time
from collections import deque
from urllib.parse import quote

import aiohttp

from core.config import RIOT_API_KEY

REGIONAL = "https://asia.api.riotgames.com"   # 계정·매치
PLATFORM = "https://kr.api.riotgames.com"     # 소환사·티어


class RiotError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"[{status}] {message}")
        self.status = status


class RateLimiter:
    """여러 개의 (횟수, 초) 한도를 동시에 지킨다."""

    def __init__(self, limits):
        self._limits = [(count, window, deque()) for count, window in limits]
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                wait = 0.0
                for count, window, hits in self._limits:
                    while hits and now - hits[0] >= window:
                        hits.popleft()
                    if len(hits) >= count:
                        wait = max(wait, window - (now - hits[0]))
                if wait <= 0:
                    for _, _, hits in self._limits:
                        hits.append(now)
                    return
                await asyncio.sleep(wait)


class RiotClient:
    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        # 개발용 키 기준: 20회/1초, 100회/2분
        self._limiter = RateLimiter([(20, 1.0), (100, 120.0)])

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-Riot-Token": RIOT_API_KEY},
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, url: str, *, params=None, retries: int = 3):
        session = await self._ensure_session()
        for attempt in range(retries):
            await self._limiter.acquire()
            async with session.get(url, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 429:
                    wait = float(resp.headers.get("Retry-After", 1))
                    print(f"[Riot] 호출 제한. {wait}초 대기")
                    await asyncio.sleep(wait + 0.5)
                    continue
                if resp.status >= 500:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise RiotError(resp.status, (await resp.text())[:200])
        raise RiotError(429, "재시도 횟수를 초과했습니다.")

    # ---- 공개 메서드 ----

    async def get_account(self, game_name: str, tag_line: str) -> dict:
        url = f"{REGIONAL}/riot/account/v1/accounts/by-riot-id/{quote(game_name)}/{quote(tag_line)}"
        return await self._get(url)

    async def get_summoner(self, puuid: str) -> dict:
        return await self._get(f"{PLATFORM}/lol/summoner/v4/summoners/by-puuid/{puuid}")

    async def get_league_entries(self, puuid: str) -> list[dict]:
        return await self._get(f"{PLATFORM}/lol/league/v4/entries/by-puuid/{puuid}")

    async def get_match_ids(self, puuid: str, *, count: int = 20,
                            start: int = 0, queue: int | None = None) -> list[str]:
        params = {"start": start, "count": count}
        if queue:
            params["queue"] = queue
        return await self._get(
            f"{REGIONAL}/lol/match/v5/matches/by-puuid/{puuid}/ids", params=params)

    async def get_match(self, match_id: str) -> dict:
        return await self._get(f"{REGIONAL}/lol/match/v5/matches/{match_id}")

    async def get_league_page(self, tier: str, division: str, page: int = 1) -> list:
        return await self._get(
            f"{PLATFORM}/lol/league/v4/entries/RANKED_SOLO_5x5/{tier}/{division}",
            params={"page": page})

    async def get_apex_league(self, tier: str) -> dict:
        path = {"MASTER": "masterleagues",
                "GRANDMASTER": "grandmasterleagues",
                "CHALLENGER": "challengerleagues"}[tier]
        return await self._get(
            f"{PLATFORM}/lol/league/v4/{path}/by-queue/RANKED_SOLO_5x5")