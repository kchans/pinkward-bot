# PinkWard Bot

A Discord bot for small League of Legends communities. It keeps a server-scoped leaderboard and automatically balances teams for in-house 5v5 custom games.

> 롤 내전을 위한 디스코드 봇입니다. 서버 내 랭킹과 포지션 기반 자동 팀 밸런싱을 제공합니다.

---

## Features

**Account linking** — Members link their Riot ID once. The bot resolves it to a PUUID and stores the association per Discord server.

**Server leaderboard** — Solo queue tier ranking, weekly games played, weekly win rate and kills, scoped to members of that server only. No global ranking is produced or published.

**Per-role index** — Each member gets a score for all five roles, derived from their ranked tier and their own role-relative performance. Playing a role often and performing above your personal average raises that role's score; a role you rarely touch is penalised.

**Automatic team balancing** — With ten players signed up, the bot evaluates every possible 5v5 split and every valid role assignment inside each team, then proposes the split with the smallest strength gap. Players can lock a preferred role and the solver treats it as a hard constraint.

**Voice channel assignment** — Moves each player into their team's voice channel after the draft.

**Custom game records** — Custom games are not retrievable through the Riot Match API, so the host records the winner with a button. These are stored separately from official match data and never mixed into official statistics.

---

## How team balancing works

Splitting ten players into two teams of five has 126 distinct outcomes. Within each team, assigning five players to five roles has 120 permutations. That is roughly 30,000 evaluations — small enough to search exhaustively, so the result is always optimal rather than approximate.

For every split, each team receives the role assignment that maximises its own total index. The split whose two totals are closest is chosen. The effect is a draft where nobody is forced badly off-role and the two sides are still even.

Role locks shrink the search space instead of expanding it. A locked role removes every permutation that violates it, and a split with no valid assignment is discarded entirely.

### On the index

The per-role index exists only to make in-house custom games more even. It is **not** an alternative to the ranked ladder, it does not estimate matchmaking rating, and it has no meaning outside the Discord server it was calculated in. The bot states this in its `/정보` command.

Small samples are handled with shrinkage: a role played twice contributes far less than a role played forty times, so a lucky two-game streak cannot inflate a score. Queues are weighted by seriousness — ranked games count fully, normal games count partially, and ARAM is excluded since it has no lane assignments.

---

## Tech stack

- Python 3.11
- discord.py 2.x
- PostgreSQL (asyncpg)
- Riot Games API — `ACCOUNT-V1`, `SUMMONER-V4`, `LEAGUE-V4`, `MATCH-V5`

### Caching and rate limiting

No command calls the Riot API. Commands read from PostgreSQL only.

Match data is immutable, so each match is fetched exactly once and reused permanently. Ranked entries use a one-hour TTL. Because members of the same community frequently appear in each other's games, overlapping matches are deduplicated and API traffic falls as the database grows.

A single rate limiter is the only path to the API. It enforces both the per-second and per-two-minute application limits with a token bucket, honours `Retry-After` on 429 responses, and backs off exponentially on 5xx. No other code path may make HTTP requests to Riot.

---

## Project structure

```
pinkward-bot/
├── bot.py              # entry point, extension loading, command sync
├── core/
│   ├── config.py       # environment variables
│   ├── db.py           # connection pool
│   ├── riot.py         # API client + rate limiter
│   ├── sync.py         # match and rank collection
│   ├── ovr.py          # per-role index calculation
│   ├── tier.py         # tier to numeric conversion
│   ├── balance.py      # team balancing solver
│   └── accounts.py     # account registration
├── cogs/
│   ├── register.py     # /등록 /내계정 /테스트등록
│   ├── sync.py         # /갱신 /전체갱신
│   ├── ovr.py          # /오버롤 /포지션순위
│   ├── hall_of_fame.py # /명예의전당 /내전순위
│   ├── scrim.py        # /내전
│   ├── status.py       # /등록현황
│   └── info.py         # /정보
└── sql/                # schema migrations, applied in order
```

---

## Setup

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Apply the SQL files in `sql/` to your PostgreSQL database in numerical order, then create a `.env` file:

```
DISCORD_TOKEN=
DISCORD_GUILD_ID=          # comma-separated for multiple servers
RIOT_API_KEY=
DATABASE_URL=
```

```bash
python bot.py
```

The bot requires the **Server Members** privileged intent, and the **Move Members** permission for voice channel assignment.

---

## Commands

| Command | Description |
|---|---|
| `/등록` | Link a Riot ID to this server |
| `/내계정` | Show the currently linked account |
| `/갱신` | Fetch recent matches and rank |
| `/오버롤` | Per-role index for a player |
| `/포지션순위` | Server ranking for one role |
| `/명예의전당` | Tier ranking and weekly records |
| `/내전` | Recruit, balance, and record a custom game |
| `/내전순위` | Custom game win rate ranking |
| `/등록현황` | Who has and hasn't linked an account |
| `/정보` | Command list and legal notice |
| `/전체갱신` | Bulk collection for the whole server (admin) |

---

## Legal

PinkWard Bot isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
