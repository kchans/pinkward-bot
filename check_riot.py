import asyncio

from core.riot import RiotClient

GAME_NAME = "아오 준쌤"   # ← 여기 수정
TAG_LINE = "1213"            # ← 여기 수정 (# 뒤의 태그)


async def main():
    riot = RiotClient()
    try:
        acc = await riot.get_account(GAME_NAME, TAG_LINE)
        print(f"계정 확인: {acc['gameName']}#{acc['tagLine']}")
        print(f"puuid: {acc['puuid'][:16]}...")

        entries = await riot.get_league_entries(acc["puuid"])
        if entries:
            for e in entries:
                print(f"  {e['queueType']}: {e['tier']} {e['rank']} "
                      f"{e['leaguePoints']}LP ({e['wins']}승 {e['losses']}패)")
        else:
            print("  랭크 기록 없음")

        ids = await riot.get_match_ids(acc["puuid"], count=5)
        print(f"최근 매치 {len(ids)}개: {ids[:2]} ...")
    finally:
        await riot.close()


asyncio.run(main())