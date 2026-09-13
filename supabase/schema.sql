-- GreenSwap Supabase schema
-- Run this in the Supabase SQL editor.

-- Products with verified eco-certifications (ground truth).
-- Seed from the public EPA Safer Choice / ENERGY STAR product lists.
create table if not exists certified_products (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  brand text,
  category text not null,           -- cleaning, bottles, personal_care, kitchen, other
  price numeric,
  eco_score int not null check (eco_score between 0 and 100),
  certification text,               -- 'EPA Safer Choice', 'ENERGY STAR', ...
  reason text,
  emoji text default '📦',
  created_at timestamptz default now()
);

-- Strong product identifiers. ALTER statements keep existing demo databases
-- upgradeable because CREATE TABLE IF NOT EXISTS does not add new columns.
alter table certified_products add column if not exists retailer text;
alter table certified_products add column if not exists asin text;
alter table certified_products add column if not exists gtin text;
alter table certified_products add column if not exists model_number text;
alter table certified_products add column if not exists sku text;

-- Greener alternatives we can suggest (may overlap with certified_products).
create table if not exists alternatives (
  id text primary key,
  name text not null,
  brand text,
  category text not null,
  price numeric,
  eco_score int not null check (eco_score between 0 and 100),
  trust text not null default 'ai_estimated', -- 'certified' | 'ai_estimated'
  certification text,
  reason text,
  emoji text default '🌿',
  created_at timestamptz default now()
);

alter table alternatives add column if not exists retailer text;
alter table alternatives add column if not exists asin text;
alter table alternatives add column if not exists gtin text;
alter table alternatives add column if not exists model_number text;
alter table alternatives add column if not exists sku text;

create unique index if not exists certified_products_gtin
  on certified_products (gtin) where gtin is not null;
create unique index if not exists alternatives_gtin
  on alternatives (gtin) where gtin is not null;
create unique index if not exists certified_products_retailer_asin
  on certified_products (retailer, asin) where asin is not null;
create unique index if not exists alternatives_retailer_asin
  on alternatives (retailer, asin) where asin is not null;

create index if not exists alternatives_lookup
  on alternatives (category, eco_score desc, price asc);

-- Cache AI estimates so repeat lookups cost nothing.
-- query_hash is a normalized hash of brand + title, so two shoppers viewing
-- the same product share one estimate. This is what keeps per-page LLM
-- spend from scaling linearly with traffic.
create table if not exists ai_estimates (
  id uuid primary key default gen_random_uuid(),
  query_hash text unique not null,
  query text not null,
  category text,
  materials jsonb,
  eco_score int,
  reason text,
  created_at timestamptz default now()
);

-- Cache validity belongs to the scoring/model version and expires so changed
-- evidence does not leave a stale conclusion indefinitely.
alter table ai_estimates add column if not exists method_version text;
alter table ai_estimates add column if not exists model_version text;
alter table ai_estimates add column if not exists evidence_fingerprint text;
alter table ai_estimates add column if not exists expires_at timestamptz;
alter table ai_estimates add column if not exists citations jsonb default '[]'::jsonb;
alter table ai_estimates add column if not exists verified boolean default false;
alter table ai_estimates add column if not exists certification text;

-- RLS: enable, then allow public read on the catalog tables.
-- Without policies, queries return EMPTY results silently rather than erroring.
alter table certified_products enable row level security;
alter table alternatives enable row level security;
alter table ai_estimates enable row level security;

create policy "public read certified" on certified_products
  for select using (true);
create policy "public read alternatives" on alternatives
  for select using (true);

-- ai_estimates is written by the backend with the service key, which bypasses
-- RLS. No public policy is granted, so the cache is not readable from clients.

-- Legacy seed data. The offline demo now uses backend/demo_catalog.py so its
-- evidence and assessments can be versioned and audited with the source code.
insert into alternatives (id, name, brand, category, price, eco_score, trust, certification, reason, emoji) values
  ('alt-leafclean', 'Plant-Based Dish Soap, 40oz', 'LeafClean', 'cleaning', 3.99, 93, 'certified', 'EPA Safer Choice', 'Every ingredient appears on the EPA Safer Chemical Ingredients List.', '🌿'),
  ('alt-barblock', 'Solid Dish Soap Block, Plastic-Free', 'Sudsy Bar', 'cleaning', 3.25, 90, 'ai_estimated', null, 'Solid format ships without a plastic bottle or added water.', '🧼'),
  ('alt-refill', 'Refillable Dish Soap Starter Kit', 'ReFill Co.', 'cleaning', 5.25, 88, 'ai_estimated', null, 'Refill pouches cut plastic packaging by roughly 80%.', '♻️'),
  ('alt-eversip', 'Stainless Steel Bottle, 24oz', 'EverSip', 'bottles', 9.99, 91, 'certified', 'Climate Pledge Friendly', 'Reusable; replaces roughly 150 single-use bottles per year.', '🥤'),
  ('alt-pureflow', 'Glass Bottle with Protective Sleeve', 'PureFlow', 'bottles', 7.49, 84, 'ai_estimated', null, 'Reusable borosilicate glass, fully recyclable at end of life.', '🫙')
on conflict (id) do nothing;
