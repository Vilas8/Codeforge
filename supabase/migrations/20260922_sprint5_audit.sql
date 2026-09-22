create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  project_id uuid null references public.projects(id) on delete cascade,
  action text not null,
  status text not null default 'success' check (status in ('success','error','denied')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists audit_logs_user_created_idx on public.audit_logs(user_id, created_at desc);
create index if not exists audit_logs_project_created_idx on public.audit_logs(project_id, created_at desc);

alter table public.audit_logs enable row level security;

create policy "Users can read own audit logs"
on public.audit_logs for select
to authenticated
using (auth.uid() = user_id);
