import json
import time
from pathlib import Path

import aiohttp

CACHE = Path("assets/cache/champions_ko.json")
VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
CHAMP_URL = "https://ddragon.leagueoflegends.com/cdn/{}/data/ko_KR/champion.json"
TTL = 60 * 60 * 24 * 7          # 일주일

_names: dict[str, str] = {}


async def champion_names() -> dict[str, str]:
    global _names
    if _names:
        return _names
    if CACHE.exists() and time.time() - CACHE.stat().st_mtime < TTL:
        _names = json.loads(CACHE.read_text(encoding="utf-8"))
        return _names

    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(VERSIONS_URL) as r:
                version = (await r.json())[0]
            async with s.get(CHAMP_URL.format(version)) as r:
                data = (await r.json())["data"]
        _names = {key: v["name"] for key, v in data.items()}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(_names, ensure_ascii=False), encoding="utf-8")
    except Exception:
        if CACHE.exists():
            _names = json.loads(CACHE.read_text(encoding="utf-8"))
    return _names


async def korean_name(champion: str | None) -> str:
    if not champion:
        return "미정"
    return (await champion_names()).get(champion, champion) 