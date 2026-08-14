import ssl

import asyncpg

from core.config import DATABASE_URL

_pool: asyncpg.Pool | None = None


def _ssl_context() -> ssl.SSLContext:
    """Windows 사용자 폴더에 한글이 있으면 asyncpg 기본 SSL 경로 탐색이 깨진다.
    컨텍스트를 직접 만들어 그 경로를 타지 않게 우회한다."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


async def init_pool() -> asyncpg.Pool:
    """봇 시작 시 한 번만 호출한다."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=5,
            command_timeout=30,
            statement_cache_size=0,
            ssl=_ssl_context(),
        )
    return _pool


def pool() -> asyncpg.Pool:
    """이미 만들어진 풀을 꺼내 쓴다."""
    if _pool is None:
        raise RuntimeError("DB 풀이 초기화되지 않았습니다. init_pool()을 먼저 호출하세요.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None