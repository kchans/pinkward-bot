import asyncio
from pathlib import Path

import aiohttp

ICON_DIR = Path("assets/icons")
ICON_DIR.mkdir(parents=True, exist_ok=True)

CD = "https://raw.communitydragon.org/latest/plugins"

TIERS = ["iron", "bronze", "silver", "gold", "platinum", "emerald",
         "diamond", "master", "grandmaster", "challenger"]
POSITIONS = ["top", "jungle", "middle", "bottom", "utility"]

TIER_TEMPLATES = [
    f"{CD}/rcp-fe-lol-static-assets/global/default/images/ranked-mini-crests/{{}}.png",
    f"{CD}/rcp-fe-lol-static-assets/global/default/images/ranked-emblem/emblem-{{}}.png",
    f"{CD}/rcp-fe-lol-shared-components/global/default/{{}}.png",
    f"{CD}/rcp-fe-lol-static-assets/global/default/images/ranked-crests/{{}}.png",
]

POSITION_TEMPLATES = [
    f"{CD}/rcp-fe-lol-parties/global/default/icon-position-{{}}.png",
    f"{CD}/rcp-fe-lol-clash/global/default/assets/images/position-selector/positions/icon-position-{{}}.png",
    f"{CD}/rcp-fe-lol-shared-components/global/default/svg/position-{{}}.svg",
    f"{CD}/rcp-fe-lol-static-assets/global/default/svg/position-{{}}.svg",
]


async def probe(session, url: str) -> bytes | None:
    try:
        async with session.get(url) as r:
            if r.status != 200:
                return None
            data = await r.read()
            return data if len(data) > 200 else None
    except Exception:
        return None


async def find_template(session, templates: list[str], sample: str, label: str):
    for tpl in templates:
        data = await probe(session, tpl.format(sample))
        if data:
            kind = "PNG" if data[:4] == b"\x89PNG" else "SVG/기타"
            print(f"  성공 [{kind}] {tpl.format(sample)}")
            return tpl
        print(f"  실패      {tpl.format(sample)}")
    print(f"  {label}: 쓸 수 있는 주소를 못 찾았습니다")
    return None


async def download_all(session, tpl: str, names: list[str], prefix: str):
    ok = 0
    for name in names:
        data = await probe(session, tpl.format(name))
        if not data:
            print(f"    {name} 실패")
            continue
        ext = "png" if data[:4] == b"\x89PNG" else "svg"
        (ICON_DIR / f"{prefix}-{name}.{ext}").write_bytes(data)
        ok += 1
    print(f"    {ok}/{len(names)}개 저장")


async def main():
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        print("── 티어 엠블럼 탐색")
        tier_tpl = await find_template(session, TIER_TEMPLATES, "gold", "티어")
        if tier_tpl:
            await download_all(session, tier_tpl, TIERS, "tier")

        print("\n── 포지션 아이콘 탐색")
        pos_tpl = await find_template(session, POSITION_TEMPLATES, "top", "포지션")
        if pos_tpl:
            await download_all(session, pos_tpl, POSITIONS, "position")

    print(f"\n저장 위치: {ICON_DIR.resolve()}")


asyncio.run(main())