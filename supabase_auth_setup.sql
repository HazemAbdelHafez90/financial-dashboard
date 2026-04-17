-- Run this once in Supabase SQL Editor.
-- Purpose:
-- 1. Add auth-aware profile and permission tables
-- 2. Split private income data out of month_configs
-- 3. Enforce access with Row Level Security

create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.app_user_permissions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'member')),
  can_manage_budgets boolean not null default false,
  can_manage_months boolean not null default false,
  can_view_wealth boolean not null default false,
  can_view_income boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.category_permissions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  category_name text not null,
  can_view boolean not null default false,
  can_add_expense boolean not null default false,
  can_edit_budget boolean not null default false,
  can_view_analysis boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, category_name)
);

create table if not exists public.month_income (
  month_key text primary key,
  income numeric not null default 0,
  income_usd numeric,
  income_rate numeric,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

insert into public.month_income (month_key, income, income_usd, income_rate)
select
  mc.month_key,
  coalesce(mc.income, 0),
  mc.income_usd,
  mc.income_rate
from public.month_configs mc
on conflict (month_key) do update
set
  income = excluded.income,
  income_usd = excluded.income_usd,
  income_rate = excluded.income_rate;

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create or replace function public.bootstrap_owner_permissions(p_display_name text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_user_id uuid := auth.uid();
begin
  if v_user_id is null then
    raise exception 'Authentication required';
  end if;

  if exists (select 1 from public.app_user_permissions) then
    raise exception 'Owner bootstrap already completed';
  end if;

  insert into public.profiles (id, display_name)
  values (v_user_id, coalesce(nullif(trim(p_display_name), ''), 'Owner'))
  on conflict (id) do update
  set display_name = excluded.display_name;

  insert into public.app_user_permissions (
    user_id,
    role,
    can_manage_budgets,
    can_manage_months,
    can_view_wealth,
    can_view_income
  ) values (
    v_user_id,
    'owner',
    true,
    true,
    true,
    true
  );

  insert into public.category_permissions (
    user_id,
    category_name,
    can_view,
    can_add_expense,
    can_edit_budget,
    can_view_analysis
  )
  select
    v_user_id,
    src.category_name,
    true,
    true,
    true,
    true
  from (
    select category as category_name from public.base_budgets
    union
    select category as category_name from public.expenses
    union
    values
      ('Home'),
      ('Car Instalment'),
      ('Fuel'),
      ('Hazem Personal'),
      ('Abrar'),
      ('Charity'),
      ('Jamila Routines'),
      ('Zain Training'),
      ('Mama'),
      ('Omar Amr')
  ) as src(category_name)
  on conflict (user_id, category_name) do update
  set can_view = excluded.can_view,
      can_add_expense = excluded.can_add_expense,
      can_edit_budget = excluded.can_edit_budget,
      can_view_analysis = excluded.can_view_analysis;
end;
$$;

grant execute on function public.bootstrap_owner_permissions(text) to authenticated;

drop trigger if exists trg_profiles_touch on public.profiles;
create trigger trg_profiles_touch
before update on public.profiles
for each row
execute function public.touch_updated_at();

drop trigger if exists trg_app_user_permissions_touch on public.app_user_permissions;
create trigger trg_app_user_permissions_touch
before update on public.app_user_permissions
for each row
execute function public.touch_updated_at();

drop trigger if exists trg_category_permissions_touch on public.category_permissions;
create trigger trg_category_permissions_touch
before update on public.category_permissions
for each row
execute function public.touch_updated_at();

drop trigger if exists trg_month_income_touch on public.month_income;
create trigger trg_month_income_touch
before update on public.month_income
for each row
execute function public.touch_updated_at();

alter table public.profiles enable row level security;
alter table public.app_user_permissions enable row level security;
alter table public.category_permissions enable row level security;
alter table public.expenses enable row level security;
alter table public.base_budgets enable row level security;
alter table public.month_configs enable row level security;
alter table public.month_income enable row level security;
alter table public.wealth_cash enable row level security;
alter table public.wealth_assets enable row level security;
alter table public.wealth_receivables enable row level security;
alter table public.wealth_snapshots enable row level security;

drop policy if exists "profiles_select_self" on public.profiles;
create policy "profiles_select_self"
on public.profiles
for select
to authenticated
using (auth.uid() = id);

drop policy if exists "profiles_insert_self" on public.profiles;
create policy "profiles_insert_self"
on public.profiles
for insert
to authenticated
with check (auth.uid() = id);

drop policy if exists "profiles_update_self" on public.profiles;
create policy "profiles_update_self"
on public.profiles
for update
to authenticated
using (auth.uid() = id)
with check (auth.uid() = id);

drop policy if exists "app_permissions_select_self" on public.app_user_permissions;
create policy "app_permissions_select_self"
on public.app_user_permissions
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "category_permissions_select_self" on public.category_permissions;
create policy "category_permissions_select_self"
on public.category_permissions
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "expenses_select_by_category_permission" on public.expenses;
create policy "expenses_select_by_category_permission"
on public.expenses
for select
to authenticated
using (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = expenses.category
      and cp.can_view = true
  )
);

drop policy if exists "expenses_insert_by_category_permission" on public.expenses;
create policy "expenses_insert_by_category_permission"
on public.expenses
for insert
to authenticated
with check (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = expenses.category
      and cp.can_add_expense = true
  )
);

drop policy if exists "expenses_update_by_category_permission" on public.expenses;
create policy "expenses_update_by_category_permission"
on public.expenses
for update
to authenticated
using (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = expenses.category
      and cp.can_add_expense = true
  )
)
with check (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = expenses.category
      and cp.can_add_expense = true
  )
);

drop policy if exists "expenses_delete_by_category_permission" on public.expenses;
create policy "expenses_delete_by_category_permission"
on public.expenses
for delete
to authenticated
using (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = expenses.category
      and cp.can_add_expense = true
  )
);

drop policy if exists "base_budgets_select_by_category_permission" on public.base_budgets;
create policy "base_budgets_select_by_category_permission"
on public.base_budgets
for select
to authenticated
using (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = base_budgets.category
      and cp.can_view = true
  )
);

drop policy if exists "base_budgets_write_by_category_permission" on public.base_budgets;
create policy "base_budgets_write_by_category_permission"
on public.base_budgets
for all
to authenticated
using (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = base_budgets.category
      and cp.can_edit_budget = true
  )
)
with check (
  exists (
    select 1
    from public.category_permissions cp
    where cp.user_id = auth.uid()
      and cp.category_name = base_budgets.category
      and cp.can_edit_budget = true
  )
);

drop policy if exists "month_configs_select_authenticated" on public.month_configs;
create policy "month_configs_select_authenticated"
on public.month_configs
for select
to authenticated
using (true);

drop policy if exists "month_configs_manage_by_app_permission" on public.month_configs;
create policy "month_configs_manage_by_app_permission"
on public.month_configs
for all
to authenticated
using (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_manage_months = true
  )
)
with check (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_manage_months = true
  )
);

drop policy if exists "month_income_select_by_permission" on public.month_income;
create policy "month_income_select_by_permission"
on public.month_income
for select
to authenticated
using (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_income = true
  )
);

drop policy if exists "month_income_manage_by_permission" on public.month_income;
create policy "month_income_manage_by_permission"
on public.month_income
for all
to authenticated
using (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_manage_months = true
  )
)
with check (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_manage_months = true
  )
);

drop policy if exists "wealth_cash_by_permission" on public.wealth_cash;
create policy "wealth_cash_by_permission"
on public.wealth_cash
for all
to authenticated
using (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
)
with check (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
);

drop policy if exists "wealth_assets_by_permission" on public.wealth_assets;
create policy "wealth_assets_by_permission"
on public.wealth_assets
for all
to authenticated
using (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
)
with check (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
);

drop policy if exists "wealth_receivables_by_permission" on public.wealth_receivables;
create policy "wealth_receivables_by_permission"
on public.wealth_receivables
for all
to authenticated
using (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
)
with check (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
);

drop policy if exists "wealth_snapshots_by_permission" on public.wealth_snapshots;
create policy "wealth_snapshots_by_permission"
on public.wealth_snapshots
for all
to authenticated
using (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
)
with check (
  exists (
    select 1
    from public.app_user_permissions ap
    where ap.user_id = auth.uid()
      and ap.can_view_wealth = true
  )
);

-- Example grants for your wife after she signs up:
-- replace the email with her real auth email.
--
-- insert into public.profiles (id, display_name)
-- select id, 'Your Wife'
-- from auth.users
-- where email = 'wife@example.com'
-- on conflict (id) do update set display_name = excluded.display_name;
--
-- insert into public.app_user_permissions (user_id, role, can_manage_budgets, can_manage_months, can_view_wealth, can_view_income)
-- select id, 'member', false, false, false, false
-- from auth.users
-- where email = 'wife@example.com'
-- on conflict (user_id) do update
-- set role = excluded.role,
--     can_manage_budgets = excluded.can_manage_budgets,
--     can_manage_months = excluded.can_manage_months,
--     can_view_wealth = excluded.can_view_wealth,
--     can_view_income = excluded.can_view_income;
--
-- insert into public.category_permissions (user_id, category_name, can_view, can_add_expense, can_edit_budget, can_view_analysis)
-- select id, 'Home', true, true, false, true
-- from auth.users
-- where email = 'wife@example.com'
-- on conflict (user_id, category_name) do update
-- set can_view = excluded.can_view,
--     can_add_expense = excluded.can_add_expense,
--     can_edit_budget = excluded.can_edit_budget,
--     can_view_analysis = excluded.can_view_analysis;
