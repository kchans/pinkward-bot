import asyncio
import io
from pathlib import Path

import aiohttp
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path("assets/fonts")
CACHE_DIR = Path("assets/cache/champions")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

SPLASH_URL = "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{}_0.jpg"

W, H = 600, 970          # 황금비 1 : 1.617
ART_H = 560
RADIUS = 24
BORDER = 5

BG = (10, 14, 12)
TEXT = (232, 244, 241)
MUTED = (110, 138, 130)
TRACK = (28, 40, 36)

TIER_COLOR = {
    "IRON": (154, 150, 144), "BRONZE": (196, 138, 82), "SILVER": (176, 186, 194),
    "GOLD": (216, 178, 84), "PLATINUM": (47, 179, 160), "EMERALD": (63, 185, 107),
    "DIAMOND": (110, 158, 230), "MASTER": (172, 108, 224),
    "GRANDMASTER": (224, 92, 92), "CHALLENGER": (232, 202, 108),
}
DEFAULT_COLOR = (188, 200, 194)

STAT_ORDER = ["attack", "survive", "growth", "vision", "team", "carry"]
STAT_LABEL = {"attack": "공격", "survive": "생존", "growth": "성장",
              "vision": "시야", "team": "협력", "carry": "캐리"}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"폰트가 없습니다: {path}")
    return ImageFont.truetype(str(path), size)


async def _fetch_art(champion: str) -> Image.Image | None:
    if not champion:
        return None
    path = CACHE_DIR / f"{champion}.jpg"
    if path.exists():
        return Image.open(path).convert("RGB")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(SPLASH_URL.format(champion), timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return None
                data = await r.read()
    except Exception:
        return None
    path.write_bytes(data)
    return Image.open(io.BytesIO(data)).convert("RGB")


def _crop_art(art: Image.Image) -> Image.Image:
    """스플래시(1215x717)를 카드 상단 비율로 잘라낸다."""
    target = W / ART_H
    w, h = art.size
    if w / h > target:
        new_w = int(h * target)
        left = (w - new_w) // 2 + int(new_w * 0.05)   # 챔피언이 살짝 우측에 있다
        left = max(0, min(left, w - new_w))
        art = art.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target)
        art = art.crop((0, 0, w, new_h))
    return art.resize((W, ART_H), Image.LANCZOS)


def _fade(card: Image.Image, top: int, height: int) -> None:
    """아트 하단을 배경색으로 자연스럽게 녹인다."""
    overlay = Image.new("RGB", (W, height), BG)
    mask = Image.new("L", (W, height))
    px = mask.load()
    for y in range(height):
        v = int(255 * (y / max(height - 1, 1)) ** 1.4)
        for x in range(W):
            px[x, y] = v
    card.paste(overlay, (0, top), mask)


def _bar(d: ImageDraw.ImageDraw, x: int, y: int, width: int,
         value: int, color: tuple) -> None:
    d.rounded_rectangle([x, y, x + width, y + 8], 4, fill=TRACK)
    filled = int(width * max(0, min(1, (value - 30) / 69)))
    if filled > 4:
        d.rounded_rectangle([x, y, x + filled, y + 8], 4, fill=color)


def _compose(data: dict, art: Image.Image | None) -> io.BytesIO:
    accent = TIER_COLOR.get(data["tier_key"], DEFAULT_COLOR)
    card = Image.new("RGB", (W, H), BG)

    if art is not None:
        card.paste(_crop_art(art), (0, 0))
    _fade(card, ART_H - 200, 200)

    d = ImageDraw.Draw(card, "RGBA")

    f_ovr = _font("Pretendard-Bold.otf", 76)
    f_pos = _font("Pretendard-Bold.otf", 27)
    f_name = _font("Pretendard-Bold.otf", 44)
    f_region = _font("Pretendard-Bold.otf", 26)
    f_body = _font("Pretendard-SemiBold.otf", 24)
    f_small = _font("Pretendard-SemiBold.otf", 20)
    f_tiny = _font("Pretendard-SemiBold.otf", 17)

    # 좌상단 종합 지수
    d.rounded_rectangle([28, 28, 178, 168], 14, fill=(10, 14, 12, 190))
    d.text((103, 82), str(data["ovr"]), font=f_ovr, fill=accent, anchor="mm")
    d.text((103, 140), data["position"], font=f_pos, fill=TEXT, anchor="mm")

    # 우상단 티어
    tw = d.textlength(data["tier"], font=f_small)
    d.rounded_rectangle([W - 48 - tw, 34, W - 24, 76], 12, fill=(10, 14, 12, 190))
    d.text((W - 36 - tw / 2, 55), data["tier"], font=f_small, fill=accent, anchor="mm")

    # 이름
    d.text((40, 600), data["name"], font=f_name, fill=TEXT)

    # 대표 챔피언 배지
    label = data["badge"]
    lw = d.textlength(label, font=f_region)
    d.rounded_rectangle([40, 668, 40 + lw + 44, 712], 22, fill=accent)
    d.text((62 + lw / 2, 690), label, font=f_region, fill=BG, anchor="mm")
    d.text((40, 726), data["sub"], font=f_tiny, fill=MUTED)

    # 능력치
    d.line([40, 762, W - 40, 762], fill=TRACK, width=2)
    cols = (40, 320)
    for i, key in enumerate(STAT_ORDER):
        x = cols[i % 2]
        y = 786 + (i // 2) * 52
        value = data["stats"][key]
        strong = value >= 80
        d.text((x, y), STAT_LABEL[key], font=f_body,
               fill=accent if strong else MUTED)
        _bar(d, x + 62, y + 10, 118, value, accent if strong else (90, 110, 104))
        d.text((x + 240, y), str(value), font=f_body,
               fill=accent if strong else TEXT, anchor="ra")

    # 하단
    d.text((W - 40, H - 30), "핑크와드봇", font=f_tiny, fill=(58, 78, 72), anchor="ra")

    # 둥근 모서리 + 테두리
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], RADIUS, fill=255)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(card, (0, 0), mask)
    ImageDraw.Draw(out).rounded_rectangle(
        [BORDER // 2, BORDER // 2, W - 1 - BORDER // 2, H - 1 - BORDER // 2],
        RADIUS, outline=accent + (255,), width=BORDER)

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    buf.seek(0)
    return buf


async def render_profile_card(data: dict) -> io.BytesIO:
    art = await _fetch_art(data.get("champion"))
    return await asyncio.to_thread(_compose, data, art)