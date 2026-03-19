-- ============================================================
-- Run this once in Supabase SQL Editor:
-- https://supabase.com/dashboard/project/ppxzhhcceivcdxxxwxqh/sql/new
-- ============================================================

-- 1. Add USD income fields to month_configs
ALTER TABLE month_configs ADD COLUMN IF NOT EXISTS income_usd float;
ALTER TABLE month_configs ADD COLUMN IF NOT EXISTS income_rate float;

-- 2. Cash holdings table
CREATE TABLE IF NOT EXISTS wealth_cash (
  id text PRIMARY KEY,
  currency text NOT NULL,
  amount float NOT NULL DEFAULT 0,
  rate float,
  notes text
);

-- 3. Assets table (gold, stocks, etc.)
CREATE TABLE IF NOT EXISTS wealth_assets (
  id text PRIMARY KEY,
  name text NOT NULL,
  type text NOT NULL DEFAULT 'other',
  qty float NOT NULL DEFAULT 0,
  price float NOT NULL DEFAULT 0,
  notes text
);

-- 4. Receivables table (money lent to others)
CREATE TABLE IF NOT EXISTS wealth_receivables (
  id text PRIMARY KEY,
  person text NOT NULL,
  amount float NOT NULL DEFAULT 0,
  currency text NOT NULL DEFAULT 'EGP',
  notes text
);

-- 5. Enable Row Level Security
ALTER TABLE wealth_cash ENABLE ROW LEVEL SECURITY;
ALTER TABLE wealth_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE wealth_receivables ENABLE ROW LEVEL SECURITY;

-- 6. Allow public access (anon key)
CREATE POLICY "open" ON wealth_cash FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "open" ON wealth_assets FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "open" ON wealth_receivables FOR ALL USING (true) WITH CHECK (true);
