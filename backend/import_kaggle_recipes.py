"""
One-time importer: unpacks the Food.com "RAW_recipes" Kaggle dataset
(backend/archive/RAW_recipes.zip) into backend/recipes_raw.jsonl — one clean
JSON object per line, ready for a downstream script to normalize ingredient
quantities/units and fold into meals.json.

Usage:
    python import_kaggle_recipes.py
"""
import ast
import csv
import io
import json
import os
import zipfile

_ARCHIVE_ZIP = os.path.join(os.path.dirname(__file__), "archive", "RAW_recipes.zip")
_OUT_PATH = os.path.join(os.path.dirname(__file__), "recipes_raw.jsonl")

_NUTRITION_FIELDS = [
    "calories", "total_fat_pdv", "sugar_pdv", "sodium_pdv",
    "protein_pdv", "saturated_fat_pdv", "carbohydrates_pdv",
]


def _parse_list(raw: str) -> list:
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return []


def _parse_nutrition(raw: str) -> dict:
    values = _parse_list(raw)
    if len(values) != len(_NUTRITION_FIELDS):
        return {}
    return dict(zip(_NUTRITION_FIELDS, values))


def convert() -> int:
    written = 0
    skipped = 0
    with zipfile.ZipFile(_ARCHIVE_ZIP) as z:
        with z.open("RAW_recipes.csv") as fb:
            f = io.TextIOWrapper(fb, encoding="utf-8")
            reader = csv.DictReader(f)
            with open(_OUT_PATH, "w", encoding="utf-8") as out:
                for row in reader:
                    name = (row.get("name") or "").strip()
                    if not name:
                        skipped += 1
                        continue

                    record = {
                        "id": row.get("id"),
                        "name": name,
                        "minutes": int(row["minutes"]) if row.get("minutes", "").isdigit() else None,
                        "tags": _parse_list(row.get("tags", "[]")),
                        "nutrition": _parse_nutrition(row.get("nutrition", "[]")),
                        "n_steps": int(row["n_steps"]) if row.get("n_steps", "").isdigit() else None,
                        "steps": _parse_list(row.get("steps", "[]")),
                        "description": (row.get("description") or "").strip(),
                        "ingredients": _parse_list(row.get("ingredients", "[]")),
                        "n_ingredients": int(row["n_ingredients"]) if row.get("n_ingredients", "").isdigit() else None,
                    }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    written += 1

                    if written % 25000 == 0:
                        print(f"[import_kaggle_recipes] {written} written...", flush=True)

    print(f"[import_kaggle_recipes] Done. {written} recipes written to {_OUT_PATH}, {skipped} skipped (no name).", flush=True)
    return written


if __name__ == "__main__":
    convert()
