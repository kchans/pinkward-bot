import asyncio
from pathlib import Path

import aiohttp
from PIL import Image

ICON_DIR = Path("assets/icons")
CD = "https://raw.communitydragon.org/latest/plugins"

CANDIDATES = [
    f"{CD}/rcp-fe-lol-static-assets/global/default/images/ranked-mini-crests/emerald.svg",
    f"{CD}/rcp-fe-lol-static-assets/global/default/images/ranked-emblem/emblem-emerald.png",
    f"{CD}/rcp-fe-lol-static-assets/global/default/images/ranked-crests/emerald.png",
    f"{CD}/rcp-fe-lol-shared-components/global/default/emerald.png",
    f"{CD}/rcp-fe-lol-static-assets/global/default/images/ranked-mini-crests/emerald_mini.png",
]


async def main():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
        for url in CANDIDATES:
            try:
                async with s.get(url) as r:
                    data = await r.read() if r.status == 200 else None
            except Exception:
                data = None
            if data and len(data) > 200:
                kind = "PNG" if data[:4] == b"\x89PNG" else "SVG/기타"
                print(f"성공 [{kind}] {url}")
                if kind == "PNG":
                    (ICON_DIR / "tier-emerald.png").write_bytes(data)
                    print("  → tier-emerald.png 저장")
                break
            print(f"실패      {url}")

    print("\n── 받은 아이콘 크기")
    for f in sorted(ICON_DIR.glob("*.png")):
        with Image.open(f) as im:
            print(f"  {f.name:<26} {im.width}x{im.height}")


asyncio.run(main())