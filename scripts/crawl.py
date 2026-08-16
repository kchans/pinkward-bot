import asyncio
import random
import time

from core.db import init_pool, close_pool, pool
from core.riot import RiotClient, RiotError
from core.sync import _save_match

SOLO_QUEUE = 420

# 티어당 두 구간만 뽑아도 분포가 충분히 잡힌다
BUCKETS = [(t, d) for t in
           ("IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND")
           for d in ("IV", "I")]
APEX = ("MASTER", "GRANDMASTER", "CHALLENGER")

SEEDS_PER_BUCKET = 12       # 구간당 시드 계정 수
MATCHES_PER_SEED = 6        # 시드당 가져올 경기 수


async def seeds_for(riot: RiotClient, tier: str, division: str | None) -> list[str]:
    try:
        if division is None:
            data = await riot.get_apex_league(tier)
            entries = data.get("entries", [])
        else:
            entries = await riot.get_league_page(tier, division, page=1)
    except RiotError as e:
        print(f"  [{tier} {division or ''}] 목록 실패: {e}")
        return []

    puuids = [e["puuid"] for e in entries if e.get("puuid")]
    random.shuffle(puuids)
    return puuids[:SEEDS_PER_BUCKET]


async def main():
    await init_pool()
    riot = RiotClient()
    started = time.time()
    seen: set[str] = set()
    saved = skipped = failed = 0

    buckets = [(t, d) for t, d in BUCKETS] + [(t, None) for t in APEX]

    try:
        for tier, division in buckets:
            label = f"{tier} {division or ''}".strip()
            puuids = await seeds_for(riot, tier, division)
            print(f"[{label}] 시드 {len(puuids)}명")

            for puuid in puuids:
                try:
                    ids = await riot.get_match_ids(
                        puuid, count=MATCHES_PER_SEED, queue=SOLO_QUEUE)
                except RiotError as e:
                    print(f"  매치 목록 실패: {e}")
                    continue

                todo = [m for m in ids if m not in seen]
                seen.update(todo)
                if not todo:
                    continue

                async with pool().acquire() as conn:
                    rows = await conn.fetch(
                        "select match_id from matches "
                        "where match_id = any($1::text[])", todo)
                known = {r["match_id"] for r in rows}
                skipped += len(known)

                for match_id in todo:
                    if match_id in known:
                        continue
                    try:
                        data = await riot.get_match(match_id)
                        await _save_match(data, store_raw=False)
                        saved += 1
                    except RiotError as e:
                        if e.status == 404:
                            continue
                        print(f"  매치 실패 {match_id}: {e}")
                        failed += 1

            elapsed = int(time.time() - started)
            print(f"  누적 저장 {saved} · 기존 {skipped} · 실패 {failed} "
                  f"· 경과 {elapsed // 60}분 {elapsed % 60}초")
    finally:
        await riot.close()
        await close_pool()

    print(f"\n완료 — 새 경기 {saved}건 저장")


asyncio.run(main())