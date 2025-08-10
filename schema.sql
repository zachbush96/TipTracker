-- Tip Tracker Database Schema (Supabase-safe)

-- Optional: ensure gen_random_uuid() exists (harmless if already present)
-- If your project already supports gen_random_uuid(), this does nothing.
create extension if not exists pgcrypto;

-- DO NOT: ALTER DATABASE ... SET row_security = on;
-- RLS is per-table in Postgres/Supabase.

-- USERS table (profiles). Align id with Supabase Auth user id.
create table if not exists public.users (
  id uuid primary key
    references auth.users (id) on delete cascade,
  email text unique not null,
  name text not null,
  role text not null default 'server' check (role in ('server','manager')),
  restaurant_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- If you want the row to auto-bind to the current auth user without client providing id:
-- (Uncomment if desired; works in Supabase)
-- alter table public.users alter column id set default auth.uid();

-- TIP ENTRIES
create table if not exists public.tip_entries (
  id bigserial primary key,
  user_id uuid not null references public.users(id) on delete cascade,
  cash_tips numeric(10,2) not null default 0 check (cash_tips >= 0),
  card_tips numeric(10,2) not null default 0 check (card_tips >= 0),
  hours_worked numeric(4,2) not null check (hours_worked > 0 and hours_worked <= 24),
  work_date date not null,
  weekday smallint not null check (weekday between 0 and 6), -- 0=Mon .. 6=Sun
  total_tips numeric(10,2) not null default 0,
  tips_per_hour numeric(8,2) not null default 0,
  comments text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Indexes
create index if not exists idx_tip_entries_user_id on public.tip_entries(user_id);
create index if not exists idx_tip_entries_work_date on public.tip_entries(work_date);
create index if not exists idx_tip_entries_weekday on public.tip_entries(weekday);
create index if not exists idx_tip_entries_user_date on public.tip_entries(user_id, work_date);

-- Compute totals/tips_per_hour
create or replace function public.calculate_tip_totals()
returns trigger language plpgsql as $$
begin
  new.total_tips := coalesce(new.cash_tips,0) + coalesce(new.card_tips,0);
  new.tips_per_hour := case
    when coalesce(new.hours_worked,0) > 0 then round(new.total_tips / new.hours_worked, 2)
    else 0
  end;
  new.updated_at := now();
  return new;
end$$;

drop trigger if exists trigger_calculate_tip_totals on public.tip_entries;
create trigger trigger_calculate_tip_totals
before insert or update on public.tip_entries
for each row execute function public.calculate_tip_totals();

-- Generic updated_at helper
create or replace function public.update_updated_at_column()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end$$;

drop trigger if exists trigger_users_updated_at on public.users;
create trigger trigger_users_updated_at
before update on public.users
for each row execute function public.update_updated_at_column();

-- Enable RLS per table
alter table public.users enable row level security;
alter table public.tip_entries enable row level security;

-- USERS RLS
-- Users can select/update/insert only their own row (id must equal auth.uid()).
drop policy if exists "Users can view own record" on public.users;
create policy "Users can view own record" on public.users
  for select using (auth.uid() = id);

drop policy if exists "Users can update own record" on public.users;
create policy "Users can update own record" on public.users
  for update using (auth.uid() = id);

drop policy if exists "Users can insert own record" on public.users;
create policy "Users can insert own record" on public.users
  for insert with check (auth.uid() = id);

-- Managers can view all users in their org (restaurant_id match, or null fallback)
drop policy if exists "Managers can view all users" on public.users;
create policy "Managers can view all users" on public.users
  for select using (
    exists (
      select 1
      from public.users me
      where me.id = auth.uid()
        and me.role = 'manager'
        and (me.restaurant_id = public.users.restaurant_id
             or public.users.restaurant_id is null)
    )
  );

-- TIP_ENTRIES RLS
drop policy if exists "Users can view own tip entries" on public.tip_entries;
create policy "Users can view own tip entries" on public.tip_entries
  for select using (auth.uid() = user_id);

drop policy if exists "Users can insert own tip entries" on public.tip_entries;
create policy "Users can insert own tip entries" on public.tip_entries
  for insert with check (auth.uid() = user_id);

drop policy if exists "Users can update own tip entries" on public.tip_entries;
create policy "Users can update own tip entries" on public.tip_entries
  for update using (auth.uid() = user_id);

drop policy if exists "Users can delete own tip entries" on public.tip_entries;
create policy "Users can delete own tip entries" on public.tip_entries
  for delete using (auth.uid() = user_id);

-- View for stats (RLS applies via underlying tables; don't enable RLS on a view)
create or replace view public.tip_statistics as
select
  te.user_id,
  u.name as user_name,
  u.email as user_email,
  te.work_date,
  te.weekday,
  te.cash_tips,
  te.card_tips,
  te.total_tips,
  te.hours_worked,
  te.tips_per_hour,
  case te.weekday
    when 0 then 'Monday'
    when 1 then 'Tuesday'
    when 2 then 'Wednesday'
    when 3 then 'Thursday'
    when 4 then 'Friday'
    when 5 then 'Saturday'
    when 6 then 'Sunday'
  end as weekday_name
from public.tip_entries te
join public.users u on u.id = te.user_id;

-- NOTE: No ALTER VIEW ... ENABLE ROW LEVEL SECURITY here.
