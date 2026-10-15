"""Tests for services/calorie_calculator.py, using the worked examples from the HLD."""
import pytest

from database.nutrition_data import FOODS
from services.calorie_calculator import (
    PortionError, calculate, daily_summary, nutrients_for, portion_to_grams, validate_custom_food,
)


def food_row(name):
    """A food shaped like a database row (the calculator reads the *_per_100g columns)."""
    food = next(f for f in FOODS if f["name"] == name)
    row = {"serving_grams": food["serving_grams"]}
    for key in ("calories", "protein", "carbs", "fat", "fiber"):
        row[f"{key}_per_100g"] = food[key]
    return row


BIRYANI = food_row("Chicken Biryani")     # 104 kcal per 100 g, 1 plate = 250 g
ROTI = food_row("Roti / Chapati")          # 202.3 kcal per 100 g, 1 piece = 40 g


def test_one_plate_of_biryani_matches_the_hld_example():
    result = calculate(BIRYANI, quantity=1)
    assert result == {"grams": 250, "quantity": 1, "calories": 260, "protein": 18.0,
                      "carbs": 34.0, "fat": 6.0, "fiber": 2.8}


def test_three_rotis_matches_the_hld_example():
    assert calculate(ROTI, quantity=3)["calories"] == 243          # 202.3 x 120 / 100 = 242.8


def test_grams_typed_directly():
    assert portion_to_grams(BIRYANI, grams="300") == (300.0, None)
    assert nutrients_for(BIRYANI, 300)["calories"] == 312


@pytest.mark.parametrize("quantity, grams", [(None, None), (1, 100)])
def test_exactly_one_of_quantity_or_grams(quantity, grams):
    with pytest.raises(PortionError):
        portion_to_grams(BIRYANI, quantity=quantity, grams=grams)


@pytest.mark.parametrize("quantity", [0, -1, 0.1, 21, "abc", "nan", "inf", True, [1]])
def test_bad_quantities_are_rejected(quantity):
    with pytest.raises(PortionError):
        portion_to_grams(BIRYANI, quantity=quantity)


@pytest.mark.parametrize("grams", [0, 0.5, 3001, "", "x"])
def test_bad_grams_are_rejected(grams):
    with pytest.raises(PortionError):
        portion_to_grams(BIRYANI, grams=grams)


def test_portion_over_3000_grams_is_rejected():
    with pytest.raises(PortionError, match="3000"):
        portion_to_grams(BIRYANI, quantity=20)                     # 20 x 250 g = 5000 g


def test_daily_summary():
    totals = {"calories": 1260.4, "protein": 50, "carbs": 150, "fat": 40, "fiber": 12}
    summary = daily_summary(totals, goal=2000)
    assert summary["consumed"] == 1260
    assert summary["remaining"] == 740
    assert summary["percent_of_goal"] == 63
    # protein 200 kcal, carbs 600 kcal, fat 360 kcal -> 17%, 52%, 31%
    assert summary["energy_split_percent"] == {"protein": 17, "carbs": 52, "fat": 31}


def test_daily_summary_over_goal_and_empty_day():
    over = daily_summary({"calories": 2300, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}, 2000)
    assert over["remaining"] == -300
    empty = daily_summary({"calories": 0, "protein": 0, "carbs": 0, "fat": 0, "fiber": 0}, 2000)
    assert empty["energy_split_percent"] == {"protein": 0, "carbs": 0, "fat": 0}


GOOD_FOOD = {"name": "Pav Bhaji", "category": "Snack", "serving_unit": "Plate", "serving_grams": "250",
             "calories": "150", "protein": "4", "carbs": "20", "fat": "6", "fiber": "3"}


def test_valid_custom_food_is_cleaned():
    food, errors = validate_custom_food(GOOD_FOOD)
    assert errors == []
    assert food["serving_unit"] == "plate"
    assert food["calories"] == 150.0


@pytest.mark.parametrize("change, message", [
    ({"name": "x"}, "Name"),
    ({"serving_unit": "bucket"}, "Serving unit"),
    ({"calories": "950"}, "kcal per 100 g must be between 0 and 900"),
    ({"protein": "-1"}, "Protein must be between"),
    ({"fat": "abc"}, "Fat must be a number"),
    ({"protein": "40", "carbs": "40", "fat": "30"}, "cannot be more than 100"),
    ({"fiber": "25"}, "Fiber cannot be more than carbs"),
])
def test_invalid_custom_food_is_explained(change, message):
    _, errors = validate_custom_food({**GOOD_FOOD, **change})
    assert any(message in error for error in errors), errors
