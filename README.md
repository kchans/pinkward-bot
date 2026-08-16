# PinkWard Bot

A Discord bot for small League of Legends communities. It keeps a server-scoped leaderboard, balances teams for in-house 5v5 custom games, and turns each member's play style into a shareable card.

> 롤 내전을 위한 디스코드 봇입니다. 자동 팀 밸런싱, 능력치 카드, 서버 랭킹을 제공합니다.

---

## Features

**Account linking** — Members link their Riot ID once. The bot resolves it to a PUUID and stores the association per Discord server.

**Match history collection** — Pulls recent matches and stores per-participant results. A background worker keeps this current without any command touching the API.

**Player card** — Six attributes (combat, survival, farming, vision, teamplay, carry) rendered as an image, with the member's most-played champion as the artwork and their tier as the frame colour.

**Per-role index** — A separate score for each of the five roles, used only for drafting custom games.

**Automatic team balancing** — With ten players signed up, the bot evaluates every possible 5v5 split and every valid role assignment inside each team, then proposes the split with the smallest strength gap. Members may lock a preferred role.

**Draft board** — The resulting matchup is rendered as an image with role icons, tier crests, and a side-by-side strength bar.

**Voice channel assignment** — Moves each player into their team's voice channel after the draft.

**Custom game records** — Custom games are not retrievable through the Riot Match API, so the host records the winning side with a button. These are stored with a separate source marker and never mixed into official match statistics.

**Community leaderboard** — Solo queue tier ranking, weekly games played, win rate and kills, scoped to members of that server only.

**Community market** — An in-bot simulation where each listed member is a tradeable symbol whose price follows their ranked progress. See the note below.

---

## How the six attributes are calculated

Every metric is scored as a **percentile against a measured reference distribution**, not against hand-tuned thresholds.

The reference was built by crawling ranked solo queue matches across all ten tiers — 1,208 matches, 13,810 participant rows, roughly 2,700 per role. For each role and metric, quantiles are stored in the database and a player's value is interpolated against them. A score of 30 is the bottom of the distribution, 64 is the median, 99 is the top.

Only the member's **main role** is used, so a top laner who occasionally plays support is not scored against support-inflated vision numbers. Queues are weighted by seriousness: ranked counts fully, normals partially, ARAM is excluded since it has no lane assignments.

The headline number on the card blends the member's ranked tier with their measured performance, so a strong unranked player is not stuck at a floor value and a low-tier player with weak metrics does not outrank them.

---

## How team balancing works

Splitting ten players into two teams of five has 126 distinct outcomes. Within each team, assigning five players to five roles has 120 permutations. That is roughly 30,000 evaluations — small enough to search exhaustively, so the result is always optimal rather than approximate.

For every split, each team receives the role assignment that maximises its own total index. The split whose two totals are closest is chosen. The effect is a draft where nobody is forced badly off-role and the two sides are still even.

Role locks shrink the search space instead of expanding it. A locked role removes every permutation that violates it, and a split with no valid assignment is discarded entirely. The solver returns the twenty closest splits so the host can cycle through alternatives.

### On the index

The per-role index exists only to make in-house custom games more even. It is **not** an alternative to the ranked ladder, it does not estimate matchmaking rating, and it has no meaning outside the Discord server it was calculated in. The bot states this in its `/정보` command.

---

## Community market

Each member with a confirmed solo queue tier is listed as a symbol. Every symbol opens at the same price regardless of tier, and moves with the member's ranked progress normalised by tier, so climbing a division is worth the same at any level.

**This is a simulation with no monetary component.** The in-bot currency cannot be purchased with real money, cannot be exchanged for money or goods, and cannot be transferred between members. There is no wagering on match outcomes: a position is simply held and can be exited at any time, with no settlement tied to a specific game.

Orders are queued and filled at the **next** price update rather than immediately, which removes any advantage from watching a game that is about to end. A per-update movement cap spreads large jumps across several updates.

---

## Tech stack

- Python 3.11
- discord.py 2.7 (Components V2)
- PostgreSQL (asyncpg)
- Pillow for card and draft board rendering
- Riot Games API — `ACCOUNT-V1`, `SUMMONER-V4`, `LEAGUE-V4`, `MATCH-V5`

### Caching and rate limiting

No command calls the Riot API. Commands read from PostgreSQL only. A background worker refreshes ranked entries and matches on a schedule, a few members per cycle.

Match data is immutable, so each match is fetched exactly once and reused permanently — request volume scales with newly played games, not with command usage. Because members of the same community frequently appear in each other's games, overlapping matches are deduplicated and API traffic falls as the database grows.

A single rate limiter is the only path to the API. It enforces both the per-second and per-two-minute application limits with a token bucket, honours `Retry-After` on 429 responses, and backs off exponentially on 5xx. No other code path may make HTTP requests to Riot.

---

## Project structure

```
pinkward-bot/
├── bot.py              # entry point, extension loading, command sync
├── crawl.py            # one-off reference data collection
├── analyze.py          # builds the percentile reference from collected matches
├── core/
│   ├── config.py       # environment variables
│   ├── db.py           # connection pool
│   ├── riot.py         # API client + rate limiter
│   ├── sync.py         # match and rank collection
│   ├── stats.py        # six attributes, percentile scoring
│   ├── ovr.py          # per-role index
│   ├── tier.py         # tier to numeric conversion
│   ├── balance.py      # team balancing solver
│   ├── card.py         # player card and draft board rendering
│   ├── stocks.py       # community market engine
│   ├── champions.py    # Data Dragon champion names
│   ├── accounts.py     # account registration
│   └── ui.py           # Components V2 helpers
├── cogs/
│   ├── register.py     # /등록 /내계정 /테스트등록
│   ├── sync.py         # /갱신 /전체갱신
│   ├── ovr.py          # /오버롤 /포지션순위
│   ├── hall_of_fame.py # /명예의전당 /내전순위
│   ├── scrim.py        # /내전
│   ├── stocks.py       # /시세 /매수 /매도 /자산 /출석 /투자순위
│   ├── scheduler.py    # background refresh loops
│   ├── status.py       # /등록현황
│   └── info.py         # /정보
├── assets/
│   ├── fonts/          # bundled Korean font
│   └── icons/          # tier crests, role icons
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
| `/등록현황` | Who has and hasn't linked an account |
| `/갱신` | Fetch recent matches and rank |
| `/오버롤` | Player card with six attributes |
| `/포지션순위` | Server ranking for one role |
| `/명예의전당` | Tier ranking and weekly records |
| `/내전` | Recruit, balance, and record a custom game |
| `/내전순위` | Custom game win rate ranking |
| `/출석` | Daily currency for the market simulation |
| `/시세` | Market prices |
| `/매수` `/매도` | Queue an order, filled at the next price update |
| `/자산` | Holdings and unrealised gain |
| `/투자순위` | Total asset ranking |
| `/정보` | Command list and legal notice |
| `/전체갱신` | Bulk collection for the whole server (admin) |

---

## Legal

PinkWard Bot isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.