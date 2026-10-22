-- ════════════════════════════════════════════════════════════════════════════
--  RLS LOCKDOWN
--  Problem (found 2026-10-22): old catch-all policies ("Allow all", "open",
--  "public_all") grant the PUBLIC role full read/write on expenses, base_budgets,
--  month_configs and every wealth table. Policies are OR'd, so the category
--  permission policies from supabase_auth_setup.sql had no effect, and anyone
--  with the publishable key in index.html could read, edit or delete all data
--  without signing in.
--
--  Fix:
--    1. is_owner() helper + owner-only "full access" policies, so the owner keeps
--       seeing every category (Transfers, Received, renamed/special ones) that has
--       no category_permissions row.
--    2. Drop the catch-all public policies.
--  Members keep only what category_permissions / app_user_permissions grant.
--  The bank-SMS endpoint uses the service-role key, which bypasses RLS.
--  Run once in Supabase SQL Editor. Safe to re-run.
-- ════════════════════════════════════════════════════════════════════════════

begin;

-- 1. Owner check (security definer so it can read app_user_permissions under RLS)
create or replace function public.is_owner()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.app_user_permissions
    where user_id = auth.uid() and role = 'owner'
  );
$$;

revoke all on function public.is_owner() from public;
grant execute on function public.is_owner() to authenticated;

-- 2. Owner full access on every app table
do $$
declare t text;
begin
  foreach t in array array[
    'expenses', 'base_budgets', 'month_configs', 'month_income',
    'wealth_cash', 'wealth_assets', 'wealth_receivables', 'wealth_snapshots'
  ] loop
    execute format('drop policy if exists "owner_full_access" on public.%I', t);
    execute format(
      'create policy "owner_full_access" on public.%I for all to authenticated
         using (public.is_owner()) with check (public.is_owner())', t);
  end loop;
end $$;

-- 3. Remove the catch-all public policies
drop policy if exists "Allow all"  on public.expenses;
drop policy if exists "Allow all"  on public.base_budgets;
drop policy if exists "Allow all"  on public.month_configs;
drop policy if exists "open"       on public.wealth_cash;
drop policy if exists "open"       on public.wealth_assets;
drop policy if exists "open"       on public.wealth_receivables;
drop policy if exists "public_all" on public.wealth_snapshots;

commit;

-- Check afterwards: should return no rows.
-- select tablename, policyname from pg_policies
-- where schemaname = 'public' and 'public' = any(roles) and tablename <> 'habit_overrides';
