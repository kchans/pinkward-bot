alter table guild_members
  add column if not exists display_name text,
  add column if not exists is_virtual boolean not null default false;
