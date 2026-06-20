-- ============================================================================
-- BasketBuddy Supabase Schema
-- Run this in the Supabase SQL Editor to create all tables.
-- Idempotent — safe to re-run.
-- ============================================================================

-- Clean slate for re-runs
DROP TABLE IF EXISTS shopping_routes CASCADE;
DROP TABLE IF EXISTS meal_plans CASCADE;
DROP TABLE IF EXISTS prices CASCADE;
DROP TABLE IF EXISTS meals CASCADE;
DROP TABLE IF EXISTS ingredients CASCADE;
DROP TABLE IF EXISTS stores CASCADE;

-- 1. Stores (grocery store locations)
CREATE TABLE stores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chain TEXT NOT NULL,
    name TEXT NOT NULL,
    lat DOUBLE PRECISION NOT NULL,
    lon DOUBLE PRECISION NOT NULL,
    address TEXT DEFAULT '',
    store_api_id TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 2. Ingredients (canonical ingredient catalog)
CREATE TABLE ingredients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,
    canonical_unit TEXT DEFAULT 'ct',
    density DOUBLE PRECISION,  -- oz per fl_oz for dry goods
    can_size_oz DOUBLE PRECISION,  -- standard can size in oz
    count_to_oz DOUBLE PRECISION,  -- oz per count unit
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 3. Prices (weekly snapshot per ingredient per store)
CREATE TABLE prices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ingredient_id UUID NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    store_id UUID NOT NULL REFERENCES stores(id) ON DELETE CASCADE,
    unit_price DOUBLE PRECISION NOT NULL,  -- price per base unit (oz/fl_oz/ct)
    product_name TEXT NOT NULL DEFAULT '',
    brand TEXT DEFAULT '',
    size_str TEXT DEFAULT '',
    upc TEXT DEFAULT '',
    sold_by TEXT DEFAULT 'UNIT',
    shelf_price DOUBLE PRECISION,
    scraped_at TIMESTAMPTZ DEFAULT now(),
    week_number INTEGER NOT NULL,  -- YYYYWW format (e.g. 202617)
    UNIQUE(ingredient_id, store_id, week_number)
);

-- 4. Meals (the meal database, from meals.json)
CREATE TABLE meals (
    id TEXT PRIMARY KEY,  -- e.g. "scrambled-eggs-toast"
    name TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    cuisine TEXT DEFAULT '',
    calories INTEGER DEFAULT 0,
    cook_time_minutes INTEGER DEFAULT 0,
    dietary_tags TEXT[] DEFAULT '{}',
    allergen_tags TEXT[] DEFAULT '{}',
    health_tags TEXT[] DEFAULT '{}',
    ingredients JSONB NOT NULL,
    instructions JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 5. Meal Plans (user-generated)
CREATE TABLE meal_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    preferences JSONB NOT NULL DEFAULT '{}',
    meals JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 6. Shopping Routes (optimization results per plan)
CREATE TABLE shopping_routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id UUID NOT NULL REFERENCES meal_plans(id) ON DELETE CASCADE,
    total_cost DOUBLE PRECISION DEFAULT 0,
    total_time_minutes DOUBLE PRECISION DEFAULT 0,
    route JSONB NOT NULL DEFAULT '[]',
    cheapest_single_store_name TEXT DEFAULT '',
    cheapest_single_store_cost DOUBLE PRECISION DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- Indexes
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_prices_store_week ON prices(store_id, week_number);
CREATE INDEX IF NOT EXISTS idx_prices_ingredient ON prices(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_prices_ingredient_store ON prices(ingredient_id, store_id);
CREATE INDEX IF NOT EXISTS idx_meal_plans_user ON meal_plans(user_id);
CREATE INDEX IF NOT EXISTS idx_shopping_routes_plan ON shopping_routes(plan_id);

-- ============================================================================
-- Row Level Security
-- ============================================================================
ALTER TABLE IF EXISTS stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS ingredients ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS meals ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS meal_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS shopping_routes ENABLE ROW LEVEL SECURITY;

-- Public data: readable by any authenticated user
DROP POLICY IF EXISTS "Anyone can read stores" ON stores;
CREATE POLICY "Anyone can read stores" ON stores FOR SELECT USING (true);
DROP POLICY IF EXISTS "Anyone can read ingredients" ON ingredients;
CREATE POLICY "Anyone can read ingredients" ON ingredients FOR SELECT USING (true);
DROP POLICY IF EXISTS "Anyone can read prices" ON prices;
CREATE POLICY "Anyone can read prices" ON prices FOR SELECT USING (true);
DROP POLICY IF EXISTS "Anyone can read meals" ON meals;
CREATE POLICY "Anyone can read meals" ON meals FOR SELECT USING (true);

-- Meal plans: per-user access
DROP POLICY IF EXISTS "Users read own plans" ON meal_plans;
CREATE POLICY "Users read own plans" ON meal_plans
    FOR SELECT USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users insert own plans" ON meal_plans;
CREATE POLICY "Users insert own plans" ON meal_plans
    FOR INSERT WITH CHECK (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users update own plans" ON meal_plans;
CREATE POLICY "Users update own plans" ON meal_plans
    FOR UPDATE USING (auth.uid() = user_id);
DROP POLICY IF EXISTS "Users delete own plans" ON meal_plans;
CREATE POLICY "Users delete own plans" ON meal_plans
    FOR DELETE USING (auth.uid() = user_id);

-- Shopping routes: access via plan ownership
DROP POLICY IF EXISTS "Users read own routes" ON shopping_routes;
CREATE POLICY "Users read own routes" ON shopping_routes
    FOR SELECT USING (
        auth.uid() = (SELECT user_id FROM meal_plans WHERE id = plan_id)
    );
DROP POLICY IF EXISTS "Users insert own routes" ON shopping_routes;
CREATE POLICY "Users insert own routes" ON shopping_routes
    FOR INSERT WITH CHECK (
        auth.uid() = (SELECT user_id FROM meal_plans WHERE id = plan_id)
    );
DROP POLICY IF EXISTS "Users delete own routes" ON shopping_routes;
CREATE POLICY "Users delete own routes" ON shopping_routes
    FOR DELETE USING (
        auth.uid() = (SELECT user_id FROM meal_plans WHERE id = plan_id)
    );

-- 7. Coupons (weekly flyer / digital coupon deals per postal code)
CREATE TABLE coupons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    merchant TEXT NOT NULL,
    item_name TEXT NOT NULL,
    price DOUBLE PRECISION NOT NULL,
    qty INTEGER DEFAULT 1,
    brand TEXT DEFAULT '',
    description TEXT DEFAULT '',
    image_url TEXT DEFAULT '',
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    keywords TEXT[] DEFAULT '{}',
    postal_code TEXT NOT NULL,
    scraped_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coupons_postal ON coupons(postal_code);
CREATE INDEX IF NOT EXISTS idx_coupons_merchant ON coupons(merchant);

-- 8. Add coupon-source columns to prices
ALTER TABLE prices ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'scraped';
ALTER TABLE prices ADD COLUMN IF NOT EXISTS valid_to TIMESTAMPTZ;

-- RLS for coupons (public read, service_role write)
ALTER TABLE coupons ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Anyone can read coupons" ON coupons FOR SELECT USING (true);

-- Allow the service_role (backend server) full access to all tables
-- (This is the default for service_role; RLS applies to anon/key roles)
