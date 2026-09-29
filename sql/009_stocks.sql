create table if not exists stock_listings (
  puuid      text primary key references summoners(puuid) on delete cascade,
  last_score int not null,
  listed_at  timestamptz not null default now(),
  delisted   boolean not null default false
);

create table if not exists stock_prices (
  puuid      text not null references stock_listings(puuid) on delete cascade,
  kind       text not null,
  price      double precision not null,
  prev_price double precision not null,
  primary key (puuid, kind)
);

create table if not exists stock_history (
  id    bigserial primary key,
  puuid text not null,
  kind  text not null,
  price double precision not null,
  at    timestamptz not null default now()
);
create index if not exists stock_history_idx on stock_history (puuid, kind, at desc);

create table if not exists wallets (
  guild_id        bigint not null references guilds(guild_id) on delete cascade,
  discord_user_id bigint not null,
  cash            double precision not null default 10000,
  created_at      timestamptz not null default now(),
  primary key (guild_id, discord_user_id)
);

create table if not exists holdings (
  guild_id        bigint not null,
  discord_user_id bigint not null,
  puuid           text not null,
  kind            text not null,
  shares          double precision not null default 0,
  avg_cost        double precision not null default 0,
  primary key (guild_id, discord_user_id, puuid, kind)
);

create table if not exists stock_orders (
  id              bigserial primary key,
  guild_id        bigint not null,
  discord_user_id bigint not null,
  puuid           text not null,
  kind            text not null,
  side            text not null,
  amount          double precision not null,
  status          text not null default 'pending',
  fill_price      double precision,
  fill_shares     double precision,
  created_at      timestamptz not null default now(),
  filled_at       timestamptz
);
create index if not exists stock_orders_pending on stock_orders (status, created_at);
