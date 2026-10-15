"""Checks on the starter nutrition data, so a typing mistake can never reach the app."""
from database.nutrition_data import FOODS

# The foods named in the project brief (roti and chapati are one entry).
REQUIRED = [
    "Steamed Rice", "Dal", "Roti / Chapati", "Plain Paratha", "Chicken Biryani",
    "Chicken Curry", "Paneer Butter Masala", "Samosa", "Plain Dosa", "Masala Dosa",
    "Idli", "Puri", "Chole", "Rajma", "Veg Fried Rice", "Veg Chowmein", "Momos",
    "Green Salad", "Banana", "Apple", "Mango",
]


def test_every_food_from_the_brief_is_present():
    names = {food["name"] for food in FOODS}
    missing = [name for name in REQUIRED if name not in names]
    assert missing == []


def test_names_are_unique_ignoring_case():
    names = [food["name"].lower() for food in FOODS]
    assert len(names) == len(set(names))


def test_values_are_in_valid_ranges():
    for food in FOODS:
        assert food["serving_grams"] > 0, food["name"]
        assert 0 <= food["calories"] <= 900, food["name"]
        for key in ("protein", "carbs", "fat", "fiber"):
            assert 0 <= food[key] <= 100, (food["name"], key)
        assert food["protein"] + food["carbs"] + food["fat"] <= 100, food["name"]


def test_calories_agree_with_macronutrients():
    """Atwater check: 4 kcal/g protein, 4 kcal/g carbs, 9 kcal/g fat, within 15%."""
    for food in FOODS:
        estimate = 4 * food["protein"] + 4 * food["carbs"] + 9 * food["fat"]
        difference = abs(estimate - food["calories"]) / food["calories"]
        assert difference <= 0.15, f"{food['name']}: {estimate:.0f} vs {food['calories']} kcal"


def test_every_food_has_a_prompt_and_a_source():
    for food in FOODS:
        assert food["ai_prompt"].startswith("a photo of "), food["name"]
        assert food["source"].startswith(("INDB ", "USDA ")), food["name"]
