import asyncio

from core.db import init_pool, close_pool


async def main():
    p = await init_pool()
    async with p.acquire() as conn:
        tables = await conn.fetch(
            "select tablename from pg_tables "
            "where schemaname = 'public' order by tablename"
        )
    print("DB 연결 성공")
    print(f"테이블 {len(tables)}개:", ", ".join(t["tablename"] for t in tables))
    await close_pool()


asyncio.run(main())