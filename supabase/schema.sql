-- GreenSwap Supabase schema
-- Run this in the Supabase SQL editor.

-- Products with verified eco-certifications (your ground truth).
-- Seed this from public EPA Safer Choice / ENERGY STAR product lists.
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

-- Greener alternatives we can suggest (can overlap with certified_products).
create table if not exists alternatives (
  id uuid primary key default gen_random_uuid(),
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

-- Cache AI estimates so repeat lookups are free and fast.
create table if not exists ai_estimates (
  id uuid primary key default gen_random_uuid(),
  query text unique not null,
  category text,
  materials jsonb,
  eco_score int,
  reason text,
  created_at timestamptz default now()
);

-- RLS: enable and allow public read on catalog tables.
-- (Remember: without policies, queries return EMPTY results silently!)
alter table certified_products enable row level security;
alter table alternatives enable row level security;
alter table ai_estimates enable row level security;

create policy "public read certified" on certified_products
  for select using (true);
create policy "public read alternatives" on alternatives
  for select using (true);

-- Seed data for the demo
insert into alternatives (name, brand, category, price, eco_score, trust, certification, reason, emoji) values
  ('Plant-Based Dish Soap, 40oz', 'LeafClean', 'cleaning', 3.99, 93, 'certified', 'EPA Safer Choice', 'All ingredients on the EPA Safer Chemical Ingredients list.', '🌿'),
  ('Refillable Dish Soap Starter Kit', 'ReFill Co.', 'cleaning', 5.25, 88, 'ai_estimated', null, 'Refill pouches cut plastic packaging by ~80%.', '♻️'),
  ('Stainless Steel Bottle 24oz', 'EverSip', 'bottles', 9.99, 91, 'certified', 'Climate Pledge Friendly', 'Reusable; replaces ~150 plastic bottles per year.', '🥤'),
  ('Glass Bottle with Sleeve', 'PureFlow', 'bottles', 7.49, 84, 'ai_estimated', null, 'Reusable glass; fully recyclable at end of life.', '🫙');
