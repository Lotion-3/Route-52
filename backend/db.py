import os
import datetime
from typing import Optional

from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")


class Database:
    def __init__(self, url: str = "", key: str = ""):
        self.url = url or SUPABASE_URL
        self.key = key or SUPABASE_KEY
        self.client: Client = create_client(self.url, self.key)

    # ── Meals ────────────────────────────────────────────────────────────────

    def get_meals(self) -> list[dict]:
        resp = self.client.table("meals").select("*").execute()
        return resp.data

    def get_meal(self, meal_id: str) -> Optional[dict]:
        resp = self.client.table("meals").select("*").eq("id", meal_id).execute()
        return resp.data[0] if resp.data else None

    # ── Ingredients ──────────────────────────────────────────────────────────

    def get_ingredients(self) -> list[dict]:
        resp = self.client.table("ingredients").select("*").execute()
        return resp.data

    def get_ingredient_by_name(self, name: str) -> Optional[dict]:
        resp = self.client.table("ingredients").select("*").eq("name", name).execute()
        return resp.data[0] if resp.data else None

    def create_ingredient(
        self,
        name: str,
        canonical_unit: str = "ct",
        density: Optional[float] = None,
        can_size_oz: Optional[float] = None,
        count_to_oz: Optional[float] = None,
    ) -> dict:
        data = {"name": name, "canonical_unit": canonical_unit}
        if density is not None:
            data["density"] = density
        if can_size_oz is not None:
            data["can_size_oz"] = can_size_oz
        if count_to_oz is not None:
            data["count_to_oz"] = count_to_oz
        resp = self.client.table("ingredients").insert(data).execute()
        return resp.data[0]

    def get_or_create_ingredient(self, name: str, **kwargs) -> dict:
        existing = self.get_ingredient_by_name(name)
        if existing:
            return existing
        return self.create_ingredient(name, **kwargs)

    def bulk_create_ingredients(self, ingredients: list[dict]) -> int:
        """Batch insert ingredients, skipping existing names.
        ingredients: [{name, canonical_unit, density, can_size_oz, count_to_oz}, ...]
        Returns count of new rows inserted.
        """
        existing = {r["name"] for r in self.get_ingredients()}
        to_insert = [i for i in ingredients if i["name"] not in existing]
        if not to_insert:
            return 0
        resp = self.client.table("ingredients").insert(to_insert).execute()
        return len(resp.data)

    # ── Stores ───────────────────────────────────────────────────────────────

    def get_all_stores(self) -> list[dict]:
        resp = self.client.table("stores").select("*").execute()
        return resp.data

    def get_stores_by_chain(self, chain: str) -> list[dict]:
        resp = self.client.table("stores").select("*").eq("chain", chain).execute()
        return resp.data

    def bulk_create_stores(self, stores: list[dict]) -> int:
        resp = self.client.table("stores").insert(stores).execute()
        return len(resp.data)

    def clear_stores(self) -> None:
        self.client.table("stores").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    # ── Prices ───────────────────────────────────────────────────────────────

    @staticmethod
    def _current_week() -> int:
        today = datetime.date.today()
        return today.year * 100 + today.isocalendar()[1]

    def get_current_prices(self, store_id: Optional[str] = None) -> list[dict]:
        week = self._current_week()
        query = self.client.table("prices").select("*").eq("week_number", week)
        if store_id:
            query = query.eq("store_id", store_id)
        resp = query.execute()
        return resp.data

    def upsert_price(
        self,
        ingredient_id: str,
        store_id: str,
        unit_price: float,
        product_name: str = "",
        brand: str = "",
        size_str: str = "",
        upc: str = "",
        sold_by: str = "UNIT",
        shelf_price: Optional[float] = None,
    ) -> dict:
        week = self._current_week()
        data = {
            "ingredient_id": ingredient_id,
            "store_id": store_id,
            "unit_price": round(unit_price, 6),
            "product_name": product_name,
            "brand": brand,
            "size_str": size_str,
            "upc": upc,
            "sold_by": sold_by,
            "shelf_price": shelf_price if shelf_price is not None else unit_price,
            "week_number": week,
        }
        resp = (
            self.client.table("prices")
            .upsert(data, on_conflict="ingredient_id,store_id,week_number")
            .execute()
        )
        return resp.data[0] if resp.data else data

    def batch_upsert_prices(self, store_id: str, prices: dict[str, dict]) -> int:
        week = self._current_week()
        records = []
        for ing_name, result in prices.items():
            ing = self.get_or_create_ingredient(ing_name)
            total_cost = result.get("total_cost", 0.0)
            qty = result.get("total_qty", 1) or 1
            unit_price = total_cost / qty if qty else total_cost
            records.append({
                "ingredient_id": ing["id"],
                "store_id": store_id,
                "unit_price": round(unit_price, 6),
                "product_name": result.get("description", ing_name),
                "brand": result.get("brand", ""),
                "size_str": result.get("size_str", ""),
                "upc": "",
                "sold_by": result.get("sold_by", "UNIT"),
                "shelf_price": total_cost,
                "week_number": week,
            })
        if not records:
            return 0
        resp = (
            self.client.table("prices")
            .upsert(records, on_conflict="ingredient_id,store_id,week_number")
            .execute()
        )
        return len(resp.data)

    # ── Coupons ────────────────────────────────────────────────────────────────

    def batch_upsert_coupons(self, postal_code: str, coupons: list[dict]) -> int:
        for c in coupons:
            c["postal_code"] = postal_code
        if not coupons:
            return 0
        resp = self.client.table("coupons").upsert(coupons, on_conflict="postal_code,merchant,item_name,valid_to").execute()
        return len(resp.data)

    def get_coupons_by_postal(self, postal_code: str, merchant: str = "") -> list[dict]:
        query = self.client.table("coupons").select("*").eq("postal_code", postal_code)
        if merchant:
            query = query.eq("merchant", merchant.lower())
        resp = query.execute()
        return resp.data

    # ── Meal Plans ───────────────────────────────────────────────────────────

    def save_meal_plan(self, user_id: str, preferences: dict, meals: list) -> dict:
        data = {"user_id": user_id, "preferences": preferences, "meals": meals}
        resp = self.client.table("meal_plans").insert(data).execute()
        return resp.data[0]

    def get_user_plans(self, user_id: str) -> list[dict]:
        resp = (
            self.client.table("meal_plans")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return resp.data

    def get_plan(self, plan_id: str) -> Optional[dict]:
        resp = self.client.table("meal_plans").select("*").eq("id", plan_id).execute()
        return resp.data[0] if resp.data else None

    def delete_plan(self, plan_id: str) -> None:
        self.client.table("meal_plans").delete().eq("id", plan_id).execute()

    # ── Shopping Routes ──────────────────────────────────────────────────────

    def save_shopping_route(self, plan_id: str, route_data: dict) -> dict:
        data = {
            "plan_id": plan_id,
            "total_cost": route_data.get("total_cost", 0),
            "total_time_minutes": route_data.get("total_time_minutes", 0),
            "route": route_data.get("route", []),
            "cheapest_single_store_name": route_data.get("cheapest_single_store_name", ""),
            "cheapest_single_store_cost": route_data.get("cheapest_single_store_cost", 0),
        }
        resp = self.client.table("shopping_routes").insert(data).execute()
        return resp.data[0]

    def get_shopping_route(self, plan_id: str) -> Optional[dict]:
        resp = (
            self.client.table("shopping_routes")
            .select("*")
            .eq("plan_id", plan_id)
            .execute()
        )
        return resp.data[0] if resp.data else None


db = Database()
