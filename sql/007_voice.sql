alter table guilds
  add column if not exists blue_channel_id bigint,
  add column if not exists red_channel_id  bigint;
