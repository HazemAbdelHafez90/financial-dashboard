-- ════════════════════════════════════════════════════════════════════════════
--  HABIT OVERRIDES TABLE
--  Stores per-user merchant → sub-group overrides for the Habits tab.
--  When the user clicks a transaction and picks a group (e.g. "Gas pill → Home
--  Utilities"), a row is upserted here keyed by a normalized description.
--  Mirrors the style of existing tables (category_permissions, profiles).
--  Run once in Supabase SQL Editor.
-- ════════════════════════════════════════════════════════════════════════════

create extension if not exists pgcrypto;

create table if not exists public.habit_overrides (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  norm_desc text not null,          -- normalized merchant key (lowercase, first 1–3 words, no digits)
  group_name text not null,         -- e.g. "Home Utilities", "Subscriptions", "Padel"
  source_example text,              -- the original description the user clicked on (for display/debug)
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, norm_desc)
);

create index if not exists habit_overrides_user_idx
  on public.habit_overrides (user_id);

-- Reuse the existing touch_updated_at() trigger function. Safe to re-create.
create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists habit_overrides_touch on public.habit_overrides;
create trigger habit_overrides_touch
  before update on public.habit_overrides
  for each row execute function public.touch_updated_at();

-- ── Row Level Security ──
-- Each user can read/write only their own overrides.
alter table public.habit_overrides enable row level security;

drop policy if exists "habit_overrides select own" on public.habit_overrides;
create policy "habit_overrides select own"
  on public.habit_overrides
  for select
  using (auth.uid() = user_id);

drop policy if exists "habit_overrides insert own" on public.habit_overrides;
create policy "habit_overrides insert own"
  on public.habit_overrides
  for insert
  with check (auth.uid() = user_id);

drop policy if exists "habit_overrides update own" on public.habit_overrides;
create policy "habit_overrides update own"
  on public.habit_overrides
  for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "habit_overrides delete own" on public.habit_overrides;
create policy "habit_overrides delete own"
  on public.habit_overrides
  for delete
  using (auth.uid() = user_id);

-- Done.
