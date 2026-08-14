create table position_ratings (
  puuid      text not null references summoners(puuid) on delete cascade,
  position   text not null,
  ovr        int  not null,
  games      int  not null default 0,
  updated_at timestamptz not null default now(),
  primary key (puuid, position)
);