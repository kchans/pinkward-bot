create table scrims (
  id           bigserial primary key,
  guild_id     bigint not null references guilds(guild_id) on delete cascade,
  channel_id   bigint,
  message_id   bigint,
  host_id      bigint not null,
  status       text not null default 'recruiting',
  games_played int  not null default 0,
  created_at   timestamptz not null default now()
);

create table scrim_participants (
  scrim_id        bigint not null references scrims(id) on delete cascade,
  puuid           text   not null references summoners(puuid) on delete cascade,
  discord_user_id bigint not null,
  team            int,
  position        text,
  locked_position text,
  joined_at       timestamptz not null default now(),
  primary key (scrim_id, puuid)
);
