-- Sprints 8-12: semantic retrieval, project memory, diagnostics and durable jobs.

create extension if not exists vector;

alter table public.workspace_index
  add column if not exists embedding vector(1536);

create index if not exists workspace_index_embedding_hnsw_idx
  on public.workspace_index using hnsw (embedding vector_cosine_ops);

create or replace function public.match_workspace_chunks(
  p_user_id uuid,
  p_project_id uuid,
  p_query_embedding vector(1536),
  p_limit integer default 12
)
returns table(
  path text,
  chunk_start integer,
  chunk_end integer,
  content text,
  score double precision
)
language sql
stable
security invoker
as $$
  select wi.path, wi.chunk_start, wi.chunk_end, wi.content,
         1 - (wi.embedding <=> p_query_embedding) as score
  from public.workspace_index wi
  where wi.user_id = p_user_id
    and wi.project_id = p_project_id
    and wi.embedding is not null
  order by wi.embedding <=> p_query_embedding
  limit greatest(1, least(p_limit, 50));
$$;

create table if not exists public.project_memory (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  project_id uuid not null,
  kind text not null default 'decision',
  content text not null,
  source text not null default 'user',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists project_memory_project_idx
  on public.project_memory(user_id, project_id, updated_at desc);
alter table public.project_memory enable row level security;
drop policy if exists project_memory_select_own on public.project_memory;
create policy project_memory_select_own on public.project_memory
  for select to authenticated using (auth.uid() = user_id);

create table if not exists public.platform_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  project_id uuid not null,
  kind text not null,
  status text not null default 'queued',
  payload jsonb not null default '{}'::jsonb,
  result jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create index if not exists platform_jobs_queue_idx
  on public.platform_jobs(status, created_at);
alter table public.platform_jobs enable row level security;
drop policy if exists platform_jobs_select_own on public.platform_jobs;
create policy platform_jobs_select_own on public.platform_jobs
  for select to authenticated using (auth.uid() = user_id);

create table if not exists public.test_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  project_id uuid not null,
  run_id uuid,
  status text not null,
  summary jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists test_runs_project_idx
  on public.test_runs(user_id, project_id, created_at desc);
alter table public.test_runs enable row level security;
drop policy if exists test_runs_select_own on public.test_runs;
create policy test_runs_select_own on public.test_runs
  for select to authenticated using (auth.uid() = user_id);
