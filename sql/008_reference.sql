create table if not exists reference_metrics (
  position   text not null,
  metric     text not null,
  quantiles  double precision[] not null,
  samples    int not null,
  updated_at timestamptz not null default now(),
  primary key (position, metric)
);
