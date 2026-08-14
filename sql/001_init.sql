-- 1. 디스코드 서버
create table guilds (
  guild_id      bigint primary key,
  name          text,
  premium_until timestamptz,
  created_at    timestamptz not null default now()
);

-- 2. 롤 계정 (puuid가 유일한 신원)
create table summoners (
  puuid           text primary key,
  game_name       text not null,
  tag_line        text not null,
  platform        text not null default 'kr',
  profile_icon_id int,
  summoner_level  int,
  updated_at      timestamptz not null default now()
);

-- 3. 서버 ↔ 디스코드유저 ↔ 롤계정 연결 (부계정 지원)
create table guild_members (
  guild_id        bigint not null references guilds(guild_id) on delete cascade,
  discord_user_id bigint not null,
  puuid           text   not null references summoners(puuid) on delete cascade,
  is_main         boolean not null default true,
  registered_at   timestamptz not null default now(),
  primary key (guild_id, puuid)
);
create index on guild_members (guild_id, discord_user_id);

-- 4. 티어 스냅샷 (덮어쓰지 않고 쌓는다 = 주간 LP 상승왕의 근거)
create table rank_snapshots (
  id            bigserial primary key,
  puuid         text not null references summoners(puuid) on delete cascade,
  queue_type    text not null,
  tier          text,
  division      text,
  league_points int  not null default 0,
  wins          int  not null default 0,
  losses        int  not null default 0,
  fetched_at    timestamptz not null default now()
);
create index on rank_snapshots (puuid, queue_type, fetched_at desc);

-- 5. 경기 (source로 공식/내전 구분)
create table matches (
  match_id     text primary key,
  source       text not null default 'riot',
  queue_id     int,
  game_mode    text,
  game_start   timestamptz,
  duration_sec int,
  guild_id     bigint references guilds(guild_id) on delete set null,
  raw          jsonb,
  created_at   timestamptz not null default now()
);
create index on matches (game_start desc);
create index on matches (source, guild_id);

-- 6. 참가자별 성적 (통계 쿼리의 주력)
create table match_participants (
  match_id      text not null references matches(match_id) on delete cascade,
  puuid         text not null,
  team_id       int,
  champion_id   int,
  champion_name text,
  position      text,
  kills         int not null default 0,
  deaths        int not null default 0,
  assists       int not null default 0,
  damage_dealt  bigint not null default 0,
  gold_earned   bigint not null default 0,
  cs            int not null default 0,
  vision_score  int not null default 0,
  win           boolean not null,
  primary key (match_id, puuid)
);
create index on match_participants (puuid);

-- 7. 수집 상태 (중복 API 호출 방지)
create table sync_state (
  puuid           text primary key references summoners(puuid) on delete cascade,
  last_match_sync timestamptz,
  last_rank_sync  timestamptz
);