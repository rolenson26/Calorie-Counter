"""
services/calorie_calculator.py - portion -> grams -> calories and nutrients.

Plain Python with no database, no Flask and no AI, so it is easy to test and
easy to explain. The API (Part 4) loads a food row from the database, passes
it in here, and gets numbers back.

The two formulas (Modules 4 and 6 of the HLD):
    grams          = quantity x serving_grams        (or the grams the user typed)
    nutrient eaten = nutrient per 100 g x grams / 100

Example: 1 plate of chicken biryani = 250 g, 104 kcal per 100 g
         -> 104 x 250 / 100 = 260 kcal
"""
import math

MIN_QUANTITY, MAX_QUANTITY = 0.25, 20      # servings
MIN_GRAMS, MAX_GRAMS = 1, 3000             # grams eaten in one entry
NUTRIENTS = ("calories", "protein", "carbs", "fat", "fiber")
SERVING_UNITS = ("piece", "bowl", "plate", "cup", "glass", "slice", "fruit")   # "katori" became "bowl" (2026-11-12)


class PortionError(ValueError):
    """The portion or food details sent by the user are missing or out of range."""


def to_number(value, field):
    """Turn JSON/form input into a float, or raise PortionError with a clear message."""
    if isinstance(value, bool):                 # True would otherwise be read as 1
        raise PortionError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PortionError(f"{field} must be a number") from None
    if not math.isfinite(number):               # rejects "nan" and "inf"
        raise PortionError(f"{field} must be a number")
    return number


# --------------------------------------------------------------- Module 4

def portion_to_grams(food, quantity=None, grams=None):
    """Work out how many grams were eaten.

    Send exactly one of:
        quantity - number of servings (1 serving = food["serving_grams"])
        grams    - the weight typed by the user
    Returns (grams, quantity). quantity is None when grams were typed directly.
    """
    if (quantity is None) == (grams is None):
        raise PortionError("Send either quantity (servings) or grams, not both")

    if grams is not None:
        grams = to_number(grams, "grams")
        if not MIN_GRAMS <= grams <= MAX_GRAMS:
            raise PortionError(f"grams must be between {MIN_GRAMS} and {MAX_GRAMS}")
        return grams, None

    quantity = to_number(quantity, "quantity")
    if not MIN_QUANTITY <= quantity <= MAX_QUANTITY:
        raise PortionError(f"quantity must be between {MIN_QUANTITY} and {MAX_QUANTITY} servings")
    grams = quantity * food["serving_grams"]
    if grams > MAX_GRAMS:
        raise PortionError(f"That portion is {grams:.0f} g; one entry can be at most {MAX_GRAMS} g")
    return grams, quantity


# --------------------------------------------------------------- Module 6

def nutrients_for(food, grams):
    """Scale a food's per-100 g values to the grams eaten.

    Calories are rounded to a whole number, the other nutrients to 1 decimal.
    """
    factor = grams / 100
    return {
        "calories": round(food["calories_per_100g"] * factor),
        "protein": round(food["protein_per_100g"] * factor, 1),
        "carbs": round(food["carbs_per_100g"] * factor, 1),
        "fat": round(food["fat_per_100g"] * factor, 1),
        "fiber": round(food["fiber_per_100g"] * factor, 1),
    }


def calculate(food, quantity=None, grams=None):
    """Portion in, everything the result card needs out."""
    grams, quantity = portion_to_grams(food, quantity=quantity, grams=grams)
    result = {"grams": round(grams, 1), "quantity": quantity}
    result.update(nutrients_for(food, grams))
    return result


# --------------------------------------------------------------- dashboard

def daily_summary(totals, goal):
    """Add the numbers the dashboard cards and the doughnut chart need.

    totals: dict with calories, protein, carbs, fat, fiber eaten today.
    The energy split uses 4 kcal per gram of protein and carbs, 9 per gram of fat.
    """
    consumed = round(totals["calories"])
    energy = {
        "protein": 4 * totals["protein"],
        "carbs": 4 * totals["carbs"],
        "fat": 9 * totals["fat"],
    }
    energy_total = sum(energy.values())
    split = {
        name: round(100 * kcal / energy_total) if energy_total else 0
        for name, kcal in energy.items()
    }
    return {
        "goal": goal,
        "consumed": consumed,
        "remaining": goal - consumed,          # negative means over the goal
        "percent_of_goal": round(100 * consumed / goal) if goal else 0,
        "energy_split_percent": split,
    }


# --------------------------------------------------------------- custom foods

def validate_custom_food(data):
    """Check a new food typed in by a user (HLD section 10).

    Returns (food, errors). `food` is a cleaned dict ready for
    db.add_custom_food(); `errors` is a list of messages (empty when valid).
    """
    errors = []
    food = {}

    name = str(data.get("name", "")).strip()
    if not 2 <= len(name) <= 80:
        errors.append("Name must be 2 to 80 characters")
    food["name"] = name

    category = str(data.get("category") or "Other").strip()[:40]
    food["category"] = category or "Other"

    unit = str(data.get("serving_unit", "")).strip().lower()
    if unit not in SERVING_UNITS:
        errors.append("Serving unit must be one of: " + ", ".join(SERVING_UNITS))
    food["serving_unit"] = unit

    # field: (label shown on the form, lowest, highest)
    limits = {
        "serving_grams": ("Grams per serving", MIN_GRAMS, MAX_GRAMS),
        "calories": ("kcal per 100 g", 0, 900),
        "protein": ("Protein", 0, 100),
        "carbs": ("Carbohydrates", 0, 100),
        "fat": ("Fat", 0, 100),
        "fiber": ("Fiber", 0, 100),
    }
    for field, (label, low, high) in limits.items():
        try:
            value = to_number(data.get(field), label)
        except PortionError as exc:
            errors.append(str(exc))
            continue
        if not low <= value <= high:
            errors.append(f"{label} must be between {low} and {high}")
        food[field] = value

    if all(key in food for key in ("protein", "carbs", "fat", "fiber")):
        if food["protein"] + food["carbs"] + food["fat"] > 100:
            errors.append("Protein + carbs + fat cannot be more than 100 g in 100 g of food")
        if food["fiber"] > food["carbs"]:
            errors.append("Fiber cannot be more than carbs")

    return food, errors
