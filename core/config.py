import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
RIOT_API_KEY = os.getenv("RIOT_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
DISCORD_GUILD_IDS = [
    int(x) for x in os.getenv("DISCORD_GUILD_ID", "").replace(" ", "").split(",") if x
]

for name in ("DISCORD_TOKEN", "RIOT_API_KEY", "DATABASE_URL"):
    if not os.getenv(name):
        raise RuntimeError(f".env 파일에 {name} 값이 없습니다.")