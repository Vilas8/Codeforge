-- Sprint 7: persistent workspace retrieval and agent run history.
create table if not exists public.workspace_index (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  project_id uuid not null,
  path text not null,
  chunk_start integer not null,
  chunk_end integer not null,
  content text not null,
  tokens jsonb not null default '[]'::jsonb,
  content_hash text not null,
  updated_at timestamptz not null default now()
);

create index if not exists workspace_index_project_path_idx
  on public.workspace_index(user_id, project_id, path);
create index if not exists workspace_index_project_updated_idx
  on public.workspace_index(user_id, project_id, updated_at desc);

alter table public.workspace_index enable row level security;
drop policy if exists workspace_index_select_own on public.workspace_index;
create policy workspace_index_select_own on public.workspace_index
  for select to authenticated using (auth.uid() = user_id);

create table if not exists public.agent_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  project_id uuid not null,
  mode text not null,
  workflow text not null default 'standard',
  model text,
  status text not null default 'running',
  metadata jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create index if not exists agent_runs_project_started_idx
  on public.agent_runs(user_id, project_id, started_at desc);

alter table public.agent_runs enable row level security;
drop policy if exists agent_runs_select_own on public.agent_runs;
create policy agent_runs_select_own on public.agent_runs
  for select to authenticated using (auth.uid() = user_id);
