alter table scrim_participants
  add column if not exists locked_position text;
