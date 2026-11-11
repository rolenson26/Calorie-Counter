"""
database/nutrition_data.py - the starter nutrition database (76 foods, Indian focus, 3 Manipuri).

What it is
    A plain Python list. On the first run, db.init_db() copies every entry into
    the `foods` table. After that, the table is the single source of truth.
    Each food is also one label the AI model can predict (see ai_prompt).

Units
    calories, protein, carbs, fat, fiber are per 100 g of the food as eaten.
    serving_unit / serving_grams are the default portion shown to the user
    (1 bowl = 100-200 g depending on the dish, 1 plate = 250 g, pieces and fruits by typical weight).
    They are household measures checked against INDB and USDA portion
    weights, and the user can always change the portion.

Where the numbers come from (copied from the source files, not retyped)
    INDB - Indian Nutrient Databank, per-100 g values for 1,014 Indian recipes.
        Vijayakumar A, Dubasi HB, Awasthi A, Jaacks LM. "Development of an
        Indian Food Composition Database." Current Developments in Nutrition, 2024.
        https://github.com/lindsayjaacks/Indian-Nutrient-Databank-INDB-
    USDA FNDDS 2021-2023 (FoodData Central, survey foods, released 2024-10-31)
        Used for samosa, puri, plain dosa, medu vada, chicken biryani, momos,
        omelette and fast food. INDB's deep-fried recipes count all the frying
        oil as eaten (for example 738 kcal per 100 g for puri), so they were
        not used.
    USDA SR Legacy (FoodData Central, 2018) - raw fruits, curd, boiled egg.
        https://fdc.nal.usda.gov/download-datasets

    The "source" field of every food names the exact record it came from.

Honest notes for the viva
    * Cooked-dish values depend on the recipe, especially the amount of oil
      or ghee. Treat every number as an approximate estimate.
    * INDB reports available carbohydrate (fibre not included); USDA reports
      total carbohydrate (fibre included). The difference is a few grams.
    * Gulab jamun, jalebi, pakora and bhatura were left out because no
      reliable per-100 g record was found. Users can add them as custom foods.
    * Manipuri dishes (Ooti, Eromba, Singju, added 2026-11-12): no published
      nutrient analysis exists for them (INDB, IFCT and journals were searched).
      Their values are RECIPE ESTIMATES: a typical recipe, by weight, built from
      USDA SR Legacy ingredient values (see MANIPURI_INGREDIENTS and recipe()).
      Ngari (fermented dried fish) has no USDA record, so dried salted fish is
      used as the nearest match; perilla seed is replaced by sesame seed.
"""

# Per 100 g, USDA SR Legacy (NDB number in the key comment):
# (calories, protein, carbs, fat, fiber). Carbs are total carbohydrate (USDA style).
MANIPURI_INGREDIENTS = {
    "split peas, boiled":     (118, 8.34, 21.10, 0.39, 8.3),    # 16086
    "potato, boiled":         (86, 1.71, 20.01, 0.10, 1.8),     # 11367
    "green beans, boiled":    (35, 1.89, 7.88, 0.28, 3.2),      # 11053
    "spring onion":           (32, 1.83, 7.34, 0.19, 2.6),      # 11291
    "green chilli":           (40, 2.00, 9.46, 0.20, 1.5),      # 11670
    "mustard oil":            (884, 0.0, 0.0, 100.0, 0.0),      # 04583
    "cabbage":                (25, 1.28, 5.80, 0.10, 2.5),      # 11109
    "lotus stem":             (74, 2.60, 17.23, 0.10, 4.9),     # 11264
    "onion":                  (40, 1.10, 9.34, 0.10, 1.7),      # 11282
    "coriander leaves":       (23, 2.13, 3.67, 0.52, 2.8),      # 11165
    "roasted gram flour":     (387, 22.39, 57.82, 6.69, 10.8),  # 16157 (besan)
    "perilla seed (sesame)":  (573, 17.73, 23.45, 49.67, 11.8), # 12023, nearest match
    "ngari (dried fish)":     (290, 62.82, 0.0, 2.37, 0.0),     # 15017, nearest match
    "water":                  (0, 0.0, 0.0, 0.0, 0.0),
}


def recipe(name, category, serving_unit, serving_grams, ai_prompt, parts):
    """A food whose per-100 g values are worked out from a recipe.

    `parts` maps an ingredient of MANIPURI_INGREDIENTS to its grams in the recipe.
    Each nutrient = sum(ingredient value x grams) / total grams of the dish.
    """
    total = sum(parts.values())
    keys = ("calories", "protein", "carbs", "fat", "fiber")
    values = {
        key: round(sum(MANIPURI_INGREDIENTS[item][i] * grams for item, grams in parts.items()) / total, 1)
        for i, key in enumerate(keys)
    }
    listed = ", ".join(f"{item} {grams / total:.0%}" for item, grams in parts.items())
    return {"name": name, "category": category, "serving_unit": serving_unit,
            "serving_grams": serving_grams, **values, "ai_prompt": ai_prompt,
            "source": f"USDA SR Legacy ingredients, recipe estimate ({listed})"}


FOODS = [
    # ---- Rice ----
    {"name": "Steamed Rice", "category": "Rice", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 117.2, "protein": 2.6, "carbs": 25.7, "fat": 0.2, "fiber": 1.2,
     "ai_prompt": "a photo of steamed white rice, plain boiled rice in a bowl",
     "source": "INDB ASC113 (Boiled rice)"},
    {"name": "Jeera Rice", "category": "Rice", "serving_unit": "plate", "serving_grams": 250,
     "calories": 135.2, "protein": 2.5, "carbs": 23.6, "fat": 3.2, "fiber": 1.4,
     "ai_prompt": "a photo of jeera rice, white rice cooked with cumin seeds",
     "source": "INDB BFP134 (Cumin pulao)"},
    {"name": "Veg Pulao", "category": "Rice", "serving_unit": "plate", "serving_grams": 250,
     "calories": 113.0, "protein": 2.7, "carbs": 17.5, "fat": 3.3, "fiber": 2.7,
     "ai_prompt": "a photo of vegetable pulao, rice cooked with peas, carrots and spices",
     "source": "INDB ASC115 (Mixed vegetable pulao)"},
    {"name": "Veg Biryani", "category": "Rice", "serving_unit": "plate", "serving_grams": 250,
     "calories": 174.6, "protein": 3.2, "carbs": 18.6, "fat": 9.5, "fiber": 3.3,
     "ai_prompt": "a photo of vegetable biryani, layered spiced rice with vegetables",
     "source": "INDB ASC123 (Vegetable biryani/biriyani)"},
    {"name": "Chicken Biryani", "category": "Rice", "serving_unit": "plate", "serving_grams": 250,
     "calories": 104.0, "protein": 7.2, "carbs": 13.6, "fat": 2.4, "fiber": 1.1,
     "ai_prompt": "a photo of chicken biryani, spiced basmati rice with chicken pieces",
     "source": "USDA FNDDS 2706538 (Biryani with chicken)"},
    {"name": "Mutton Biryani", "category": "Rice", "serving_unit": "plate", "serving_grams": 250,
     "calories": 190.8, "protein": 7.4, "carbs": 22.5, "fat": 7.7, "fiber": 2.4,
     "ai_prompt": "a photo of mutton biryani, spiced basmati rice with mutton pieces",
     "source": "INDB ASC122 (Mutton biryani/biriyani)"},
    {"name": "Curd Rice", "category": "Rice", "serving_unit": "plate", "serving_grams": 250,
     "calories": 195.7, "protein": 5.8, "carbs": 32.9, "fat": 4.3, "fiber": 2.1,
     "ai_prompt": "a photo of curd rice, white rice mixed with yogurt and tempering",
     "source": "INDB ASC126 (Curd rice)"},
    {"name": "Lemon Rice", "category": "Rice", "serving_unit": "plate", "serving_grams": 250,
     "calories": 176.3, "protein": 4.3, "carbs": 21.6, "fat": 7.9, "fiber": 2.5,
     "ai_prompt": "a photo of lemon rice, yellow rice with peanuts and curry leaves",
     "source": "INDB ASC124 (Lemon rice)"},
    {"name": "Veg Khichdi", "category": "Rice", "serving_unit": "bowl", "serving_grams": 200,
     "calories": 143.2, "protein": 5.6, "carbs": 19.6, "fat": 4.5, "fiber": 2.5,
     "ai_prompt": "a photo of khichdi, soft rice and lentil porridge with vegetables",
     "source": "INDB ASC487 (Vegetable khichdi/khichri)"},

    # ---- Bread ----
    {"name": "Roti / Chapati", "category": "Bread", "serving_unit": "piece", "serving_grams": 40,
     "calories": 202.3, "protein": 5.9, "carbs": 35.6, "fat": 3.6, "fiber": 6.3,
     "ai_prompt": "a photo of roti or chapati, a thin round Indian whole-wheat flatbread",
     "source": "INDB ASC096 (Chapati/Roti)"},
    {"name": "Plain Paratha", "category": "Bread", "serving_unit": "piece", "serving_grams": 60,
     "calories": 298.3, "protein": 5.1, "carbs": 30.7, "fat": 16.9, "fiber": 5.4,
     "ai_prompt": "a photo of plain paratha, a layered pan-fried Indian flatbread",
     "source": "INDB ASC097 (Plain parantha/paratha)"},
    {"name": "Aloo Paratha", "category": "Bread", "serving_unit": "piece", "serving_grams": 100,
     "calories": 205.0, "protein": 3.7, "carbs": 23.9, "fat": 10.2, "fiber": 4.2,
     "ai_prompt": "a photo of aloo paratha, a flatbread stuffed with spiced potato",
     "source": "INDB ASC098 (Potato parantha/paratha)"},
    {"name": "Puri", "category": "Bread", "serving_unit": "piece", "serving_grams": 36,
     "calories": 409.0, "protein": 6.8, "carbs": 39.2, "fat": 24.9, "fiber": 3.5,
     "ai_prompt": "a photo of puri, small round puffed deep-fried Indian bread",
     "source": "USDA FNDDS 2707714 (Bread, puri)"},
    {"name": "Naan", "category": "Bread", "serving_unit": "piece", "serving_grams": 90,
     "calories": 286.4, "protein": 8.1, "carbs": 51.8, "fat": 5.0, "fiber": 1.9,
     "ai_prompt": "a photo of naan, a soft leavened Indian flatbread from a tandoor",
     "source": "INDB ASC142 (Naan)"},

    # ---- Dal & Legumes ----
    {"name": "Dal", "category": "Dal & Legumes", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 61.9, "protein": 2.5, "carbs": 5.8, "fat": 3.1, "fiber": 1.6,
     "ai_prompt": "a photo of dal, yellow lentil curry in a bowl",
     "source": "INDB ASC155 (Mixed dal)"},
    {"name": "Moong Dal", "category": "Dal & Legumes", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 50.0, "protein": 2.7, "carbs": 5.9, "fat": 1.7, "fiber": 1.2,
     "ai_prompt": "a photo of moong dal, thin yellow split mung bean lentil soup",
     "source": "INDB ASC151 (Washed moong dal)"},
    {"name": "Chana Dal", "category": "Dal & Legumes", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 99.7, "protein": 4.2, "carbs": 10.0, "fat": 4.6, "fiber": 3.7,
     "ai_prompt": "a photo of chana dal, thick yellow split chickpea lentil curry",
     "source": "INDB OSR142 (Split bengal gram dal)"},
    {"name": "Dal Makhani", "category": "Dal & Legumes", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 74.0, "protein": 3.3, "carbs": 8.0, "fat": 3.1, "fiber": 2.3,
     "ai_prompt": "a photo of dal makhani, creamy dark black lentil curry",
     "source": "INDB OSR139 (Dal makhani)"},
    {"name": "Rajma", "category": "Dal & Legumes", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 143.7, "protein": 6.0, "carbs": 16.4, "fat": 5.8, "fiber": 5.8,
     "ai_prompt": "a photo of rajma, red kidney bean curry",
     "source": "INDB ASC165 (Kidney bean curry)"},
    {"name": "Chole", "category": "Dal & Legumes", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 163.4, "protein": 6.1, "carbs": 20.0, "fat": 6.8, "fiber": 4.7,
     "ai_prompt": "a photo of chole, chickpea curry also called chana masala",
     "source": "INDB ASC162 (Chickpeas curry)"},
    {"name": "Sambar", "category": "Dal & Legumes", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 96.9, "protein": 3.4, "carbs": 10.6, "fat": 4.4, "fiber": 3.5,
     "ai_prompt": "a photo of sambar, South Indian lentil and vegetable stew",
     "source": "INDB ASC167 (Sambar)"},

    # ---- Vegetable Curry ----
    {"name": "Aloo Gobi", "category": "Vegetable Curry", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 106.2, "protein": 1.9, "carbs": 6.0, "fat": 8.1, "fiber": 3.0,
     "ai_prompt": "a photo of aloo gobi, dry potato and cauliflower curry",
     "source": "INDB ASC171 (Potato cauliflower)"},
    {"name": "Bhindi Masala", "category": "Vegetable Curry", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 110.8, "protein": 1.8, "carbs": 4.5, "fat": 9.3, "fiber": 3.6,
     "ai_prompt": "a photo of bhindi masala, stir-fried okra (lady finger)",
     "source": "INDB BFP269 (Okra/Lady's fingers fry)"},
    {"name": "Aloo Matar", "category": "Vegetable Curry", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 100.9, "protein": 3.5, "carbs": 9.7, "fat": 5.1, "fiber": 3.6,
     "ai_prompt": "a photo of aloo matar, potato and green pea curry",
     "source": "INDB ASC190 (Pea potato curry)"},
    {"name": "Aloo Sabzi", "category": "Vegetable Curry", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 89.6, "protein": 1.5, "carbs": 10.4, "fat": 4.5, "fiber": 2.4,
     "ai_prompt": "a photo of aloo sabzi, spiced potato curry",
     "source": "INDB BFP239 (Potato curry)"},
    {"name": "Baingan Bharta", "category": "Vegetable Curry", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 65.1, "protein": 1.4, "carbs": 4.4, "fat": 4.5, "fiber": 3.3,
     "ai_prompt": "a photo of baingan bharta, smoky mashed eggplant curry",
     "source": "INDB ASC177 (Brinjal bhartha)"},

    # ---- Paneer ----
    {"name": "Paneer Butter Masala", "category": "Paneer", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 145.6, "protein": 7.0, "carbs": 9.7, "fat": 8.8, "fiber": 1.5,
     "ai_prompt": "a photo of paneer butter masala, paneer cubes in orange creamy tomato gravy",
     "source": "INDB ASC222 (Paneer in butter sauce)"},
    {"name": "Palak Paneer", "category": "Paneer", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 77.7, "protein": 4.0, "carbs": 4.4, "fat": 4.8, "fiber": 1.9,
     "ai_prompt": "a photo of palak paneer, paneer cubes in green spinach gravy",
     "source": "INDB ASC215 (Spinach paneer)"},
    {"name": "Kadai Paneer", "category": "Paneer", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 108.0, "protein": 4.3, "carbs": 7.3, "fat": 6.8, "fiber": 2.1,
     "ai_prompt": "a photo of kadai paneer, paneer with capsicum and onion in thick masala",
     "source": "INDB ASC226 (Kadhai Paneer)"},
    {"name": "Matar Paneer", "category": "Paneer", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 134.8, "protein": 6.6, "carbs": 9.3, "fat": 7.8, "fiber": 3.3,
     "ai_prompt": "a photo of matar paneer, paneer and green peas curry",
     "source": "INDB ASC191 (Pea paneer curry)"},

    # ---- Non-Veg ----
    {"name": "Chicken Curry", "category": "Non-Veg", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 129.2, "protein": 11.8, "carbs": 3.4, "fat": 7.6, "fiber": 1.4,
     "ai_prompt": "a photo of chicken curry, chicken pieces in brown spicy gravy",
     "source": "INDB ASC240 (Chicken curry)"},
    {"name": "Butter Chicken", "category": "Non-Veg", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 137.0, "protein": 10.9, "carbs": 3.7, "fat": 8.7, "fiber": 1.3,
     "ai_prompt": "a photo of butter chicken, chicken in creamy orange tomato butter gravy",
     "source": "INDB ASC242 (Butter chicken)"},
    {"name": "Tandoori Chicken", "category": "Non-Veg", "serving_unit": "plate", "serving_grams": 200,
     "calories": 145.2, "protein": 16.3, "carbs": 2.3, "fat": 7.9, "fiber": 0.5,
     "ai_prompt": "a photo of tandoori chicken, red roasted chicken legs",
     "source": "INDB ASC241 (Tandoori chicken)"},
    {"name": "Fish Curry", "category": "Non-Veg", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 111.1, "protein": 8.8, "carbs": 3.8, "fat": 6.7, "fiber": 1.9,
     "ai_prompt": "a photo of fish curry, fish pieces in spicy red gravy",
     "source": "INDB ASC246 (Fish curry)"},

    # ---- Egg ----
    {"name": "Egg Curry", "category": "Egg", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 117.5, "protein": 5.4, "carbs": 4.0, "fat": 8.8, "fiber": 2.1,
     "ai_prompt": "a photo of egg curry, boiled eggs in onion tomato gravy",
     "source": "INDB BFP240 (Egg curry)"},
    {"name": "Boiled Egg", "category": "Egg", "serving_unit": "piece", "serving_grams": 50,
     "calories": 155.0, "protein": 12.6, "carbs": 1.1, "fat": 10.6, "fiber": 0.0,
     "ai_prompt": "a photo of boiled eggs, hard-boiled eggs cut in half",
     "source": "USDA SR Legacy 173424 (Egg)"},
    {"name": "Omelette", "category": "Egg", "serving_unit": "piece", "serving_grams": 110,
     "calories": 192.0, "protein": 11.6, "carbs": 0.9, "fat": 15.8, "fiber": 0.0,
     "ai_prompt": "a photo of an omelette, a folded pan-fried egg omelette",
     "source": "USDA FNDDS 2707200 (Egg omelet or scrambled egg, made with oil)"},

    # ---- South Indian ----
    {"name": "Idli", "category": "South Indian", "serving_unit": "piece", "serving_grams": 40,
     "calories": 137.5, "protein": 4.6, "carbs": 28.2, "fat": 0.3, "fiber": 2.3,
     "ai_prompt": "a photo of idli, white steamed South Indian rice cakes",
     "source": "INDB ASC144 (Idli)"},
    {"name": "Plain Dosa", "category": "South Indian", "serving_unit": "piece", "serving_grams": 80,
     "calories": 210.0, "protein": 5.7, "carbs": 37.0, "fat": 4.0, "fiber": 1.8,
     "ai_prompt": "a photo of plain dosa, a thin crispy golden South Indian crepe",
     "source": "USDA FNDDS 2708347 (Dosa, plain)"},
    {"name": "Masala Dosa", "category": "South Indian", "serving_unit": "piece", "serving_grams": 200,
     "calories": 164.6, "protein": 3.3, "carbs": 19.6, "fat": 7.8, "fiber": 2.5,
     "ai_prompt": "a photo of masala dosa, a crispy crepe folded over spiced potato filling",
     "source": "INDB ASC146 (Masala dosa)"},
    {"name": "Uttapam", "category": "South Indian", "serving_unit": "piece", "serving_grams": 100,
     "calories": 255.9, "protein": 6.2, "carbs": 36.3, "fat": 9.0, "fiber": 4.4,
     "ai_prompt": "a photo of uttapam, a thick rice pancake topped with onion and tomato",
     "source": "INDB BFP152 (Uttapam)"},
    {"name": "Medu Vada", "category": "South Indian", "serving_unit": "piece", "serving_grams": 50,
     "calories": 266.0, "protein": 12.8, "carbs": 33.2, "fat": 9.7, "fiber": 5.8,
     "ai_prompt": "a photo of medu vada, crispy doughnut-shaped lentil fritters",
     "source": "USDA FNDDS 2709130 (Vada)"},

    # ---- Breakfast ----
    {"name": "Upma", "category": "Breakfast", "serving_unit": "bowl", "serving_grams": 200,
     "calories": 147.9, "protein": 3.3, "carbs": 16.3, "fat": 7.5, "fiber": 3.2,
     "ai_prompt": "a photo of upma, savoury semolina porridge with vegetables",
     "source": "INDB BFP039 (Semolina upma)"},
    {"name": "Poha", "category": "Breakfast", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 180.5, "protein": 4.9, "carbs": 21.5, "fat": 8.1, "fiber": 3.8,
     "ai_prompt": "a photo of poha, yellow flattened rice with peanuts and onion",
     "source": "INDB BFP045 (Vegetable poha)"},

    # ---- Snack ----
    {"name": "Samosa", "category": "Snack", "serving_unit": "piece", "serving_grams": 100,
     "calories": 310.0, "protein": 5.1, "carbs": 33.2, "fat": 17.5, "fiber": 1.8,
     "ai_prompt": "a photo of samosa, a triangular fried pastry with potato filling",
     "source": "USDA FNDDS 2708730 (Samosa)"},
    {"name": "Dhokla", "category": "Snack", "serving_unit": "piece", "serving_grams": 40,
     "calories": 216.5, "protein": 13.4, "carbs": 30.7, "fat": 5.3, "fiber": 4.9,
     "ai_prompt": "a photo of dhokla, yellow steamed gram flour sponge squares",
     "source": "INDB ASC474 (Dhokla)"},
    {"name": "Veg Sandwich", "category": "Snack", "serving_unit": "piece", "serving_grams": 130,
     "calories": 244.3, "protein": 4.5, "carbs": 23.2, "fat": 15.4, "fiber": 2.4,
     "ai_prompt": "a photo of a vegetable sandwich, bread slices filled with vegetables",
     "source": "INDB ASC036 (Vegetable and mayonnaise sandwich)"},

    # ---- Indo-Chinese ----
    {"name": "Veg Fried Rice", "category": "Indo-Chinese", "serving_unit": "plate", "serving_grams": 250,
     "calories": 120.6, "protein": 4.1, "carbs": 13.4, "fat": 5.4, "fiber": 2.3,
     "ai_prompt": "a photo of vegetable fried rice, Indo-Chinese stir-fried rice",
     "source": "INDB ASC129 (Chinese fried rice)"},
    {"name": "Veg Chowmein", "category": "Indo-Chinese", "serving_unit": "plate", "serving_grams": 250,
     "calories": 129.7, "protein": 3.1, "carbs": 15.4, "fat": 6.4, "fiber": 1.9,
     "ai_prompt": "a photo of vegetable chowmein, Indo-Chinese hakka noodles with vegetables",
     "source": "INDB ASC134 (Vegetable chowmein)"},
    {"name": "Momos", "category": "Indo-Chinese", "serving_unit": "plate", "serving_grams": 150,
     "calories": 113.0, "protein": 6.9, "carbs": 11.1, "fat": 4.6, "fiber": 1.2,
     "ai_prompt": "a photo of momos, a plate of steamed dumplings",
     "source": "USDA FNDDS 2708708 (Wonton, dumpling or pot sticker, steamed)"},
    {"name": "Chilli Chicken", "category": "Indo-Chinese", "serving_unit": "plate", "serving_grams": 200,
     "calories": 198.8, "protein": 9.6, "carbs": 2.9, "fat": 16.6, "fiber": 1.0,
     "ai_prompt": "a photo of chilli chicken, Indo-Chinese fried chicken with peppers and onion",
     "source": "INDB ASC244 (Chilli chicken)"},

    # ---- Fast Food ----
    {"name": "Pizza", "category": "Fast Food", "serving_unit": "slice", "serving_grams": 85,
     "calories": 266.0, "protein": 11.4, "carbs": 33.3, "fat": 9.7, "fiber": 2.3,
     "ai_prompt": "a photo of pizza, a cheese pizza slice",
     "source": "USDA FNDDS 2708614 (Pizza, cheese, from restaurant or fast food, NS as to type of crust)"},
    {"name": "Burger", "category": "Fast Food", "serving_unit": "piece", "serving_grams": 145,
     "calories": 288.0, "protein": 17.5, "carbs": 20.7, "fat": 14.4, "fiber": 0.7,
     "ai_prompt": "a photo of a burger, a patty in a round bun",
     "source": "USDA FNDDS 2706920 (Hamburger, NFS)"},
    {"name": "French Fries", "category": "Fast Food", "serving_unit": "plate", "serving_grams": 110,
     "calories": 289.0, "protein": 3.5, "carbs": 37.2, "fat": 14.0, "fiber": 3.9,
     "ai_prompt": "a photo of french fries, fried potato sticks",
     "source": "USDA FNDDS 2709462 (Potato, french fries, restaurant)"},

    # ---- Dairy & Drinks ----
    {"name": "Curd", "category": "Dairy & Drinks", "serving_unit": "bowl", "serving_grams": 100,
     "calories": 61.0, "protein": 3.5, "carbs": 4.7, "fat": 3.2, "fiber": 0.0,
     "ai_prompt": "a photo of curd, plain white yogurt (dahi) in a bowl",
     "source": "USDA SR Legacy 171284 (Yogurt)"},
    {"name": "Cucumber Raita", "category": "Dairy & Drinks", "serving_unit": "bowl", "serving_grams": 100,
     "calories": 59.1, "protein": 4.0, "carbs": 6.3, "fat": 2.1, "fiber": 0.9,
     "ai_prompt": "a photo of cucumber raita, yogurt with grated cucumber",
     "source": "INDB ASC273 (Cucumber raita)"},
    {"name": "Sweet Lassi", "category": "Dairy & Drinks", "serving_unit": "glass", "serving_grams": 250,
     "calories": 35.7, "protein": 1.3, "carbs": 6.5, "fat": 0.7, "fiber": 0.0,
     "ai_prompt": "a photo of sweet lassi, a glass of thick white yogurt drink",
     "source": "INDB ASC021 (Sweet Lassi)"},
    {"name": "Masala Chai", "category": "Dairy & Drinks", "serving_unit": "cup", "serving_grams": 150,
     "calories": 16.1, "protein": 0.4, "carbs": 2.6, "fat": 0.5, "fiber": 0.0,
     "ai_prompt": "a photo of masala chai, Indian milk tea in a cup",
     "source": "INDB ASC001 (Hot tea)"},

    # ---- Salad ----
    {"name": "Green Salad", "category": "Salad", "serving_unit": "bowl", "serving_grams": 100,
     "calories": 49.9, "protein": 1.3, "carbs": 3.8, "fat": 3.2, "fiber": 1.3,
     "ai_prompt": "a photo of green salad, sliced cucumber, tomato, onion and lettuce",
     "source": "INDB BFP301 (Tossed green salad)"},
    {"name": "Fruit Salad", "category": "Salad", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 78.1, "protein": 0.9, "carbs": 16.0, "fat": 1.2, "fiber": 1.6,
     "ai_prompt": "a photo of fruit salad, a bowl of mixed chopped fruits",
     "source": "INDB ASC265 (Fruit salad)"},

    # ---- Sweet ----
    {"name": "Rasgulla", "category": "Sweet", "serving_unit": "piece", "serving_grams": 50,
     "calories": 118.6, "protein": 1.4, "carbs": 25.8, "fat": 1.7, "fiber": 0.0,
     "ai_prompt": "a photo of rasgulla, white spongy cheese balls in sugar syrup",
     "source": "INDB BFP392 (Rasgulla)"},
    {"name": "Rice Kheer", "category": "Sweet", "serving_unit": "bowl", "serving_grams": 150,
     "calories": 75.0, "protein": 2.3, "carbs": 10.0, "fat": 3.0, "fiber": 0.2,
     "ai_prompt": "a photo of kheer, creamy Indian rice pudding",
     "source": "INDB ASC282 (Rice kheer)"},
    {"name": "Gajar Halwa", "category": "Sweet", "serving_unit": "bowl", "serving_grams": 100,
     "calories": 172.6, "protein": 3.1, "carbs": 18.5, "fat": 9.7, "fiber": 2.7,
     "ai_prompt": "a photo of gajar halwa, orange sweet carrot pudding",
     "source": "INDB ASC295 (Carrot halwa)"},
    {"name": "Besan Ladoo", "category": "Sweet", "serving_unit": "piece", "serving_grams": 35,
     "calories": 476.9, "protein": 8.9, "carbs": 62.6, "fat": 22.8, "fiber": 4.4,
     "ai_prompt": "a photo of besan ladoo, round yellow gram flour sweet balls",
     "source": "INDB ASC343 (Gram flour ladoo)"},

    # ---- Fruit ----
    {"name": "Banana", "category": "Fruit", "serving_unit": "fruit", "serving_grams": 118,
     "calories": 89.0, "protein": 1.1, "carbs": 22.8, "fat": 0.3, "fiber": 2.6,
     "ai_prompt": "a photo of a banana, a yellow banana fruit",
     "source": "USDA SR Legacy 173944 (Bananas)"},
    {"name": "Apple", "category": "Fruit", "serving_unit": "fruit", "serving_grams": 182,
     "calories": 52.0, "protein": 0.3, "carbs": 13.8, "fat": 0.2, "fiber": 2.4,
     "ai_prompt": "a photo of an apple, a red or green apple fruit",
     "source": "USDA SR Legacy 171688 (Apples)"},
    {"name": "Mango", "category": "Fruit", "serving_unit": "cup", "serving_grams": 165,
     "calories": 60.0, "protein": 0.8, "carbs": 15.0, "fat": 0.4, "fiber": 1.6,
     "ai_prompt": "a photo of mango, ripe yellow mango slices or a whole mango",
     "source": "USDA SR Legacy 169910 (Mangos)"},
    {"name": "Orange", "category": "Fruit", "serving_unit": "fruit", "serving_grams": 131,
     "calories": 47.0, "protein": 0.9, "carbs": 11.8, "fat": 0.1, "fiber": 2.4,
     "ai_prompt": "a photo of an orange, a whole or peeled orange fruit",
     "source": "USDA SR Legacy 169097 (Oranges)"},
    {"name": "Papaya", "category": "Fruit", "serving_unit": "cup", "serving_grams": 145,
     "calories": 43.0, "protein": 0.5, "carbs": 10.8, "fat": 0.3, "fiber": 1.7,
     "ai_prompt": "a photo of papaya, orange papaya pieces",
     "source": "USDA SR Legacy 169926 (Papayas)"},
    {"name": "Watermelon", "category": "Fruit", "serving_unit": "cup", "serving_grams": 150,
     "calories": 30.0, "protein": 0.6, "carbs": 7.5, "fat": 0.1, "fiber": 0.4,
     "ai_prompt": "a photo of watermelon, red watermelon slices",
     "source": "USDA SR Legacy 167765 (Watermelon)"},
    {"name": "Grapes", "category": "Fruit", "serving_unit": "cup", "serving_grams": 150,
     "calories": 69.0, "protein": 0.7, "carbs": 18.1, "fat": 0.2, "fiber": 0.9,
     "ai_prompt": "a photo of grapes, a bunch of green or black grapes",
     "source": "USDA SR Legacy 174683 (Grapes)"},
    {"name": "Guava", "category": "Fruit", "serving_unit": "fruit", "serving_grams": 100,
     "calories": 68.0, "protein": 2.5, "carbs": 14.3, "fat": 0.9, "fiber": 5.4,
     "ai_prompt": "a photo of guava, a green guava fruit",
     "source": "USDA SR Legacy 173044 (Guavas)"},
    {"name": "Pomegranate", "category": "Fruit", "serving_unit": "cup", "serving_grams": 175,
     "calories": 83.0, "protein": 1.7, "carbs": 18.7, "fat": 1.2, "fiber": 4.0,
     "ai_prompt": "a photo of pomegranate, red pomegranate seeds",
     "source": "USDA SR Legacy 169134 (Pomegranates)"},

    # ---- Manipuri (recipe estimates, see the note at the top) ----
    recipe("Ooti", "Manipuri", "bowl", 150,
           "a photo of ooti, a Manipuri curry of soft dried peas in thick yellow-green gravy with spring onion",
           {"split peas, boiled": 70, "water": 23.5, "spring onion": 5, "mustard oil": 1.5}),
    recipe("Eromba", "Manipuri", "bowl", 100,
           "a photo of eromba, a Manipuri mash of boiled potato and vegetables with chilli and fermented fish",
           {"potato, boiled": 50, "green beans, boiled": 25, "ngari (dried fish)": 5,
            "green chilli": 5, "spring onion": 5, "water": 10}),
    recipe("Singju", "Manipuri", "plate", 150,
           "a photo of singju, a Manipuri salad of finely shredded cabbage, lotus stem and herbs with gram flour",
           {"cabbage": 55, "lotus stem": 10, "onion": 10, "coriander leaves": 5, "roasted gram flour": 10,
            "perilla seed (sesame)": 3, "ngari (dried fish)": 2, "green chilli": 5}),
]
