"""Tests for services/portion_estimator.py.

Most tests build CLIPSeg-like maps by hand (a 100 x 100 grid), so the geometry and the
decisions are checked without the model. The last test runs the real CLIPSeg model on the
sample thali and is skipped if the model has not been downloaded.
"""
import math

import pytest
import torch
from PIL import Image

from config import Config
from services.portion_estimator import (estimate_from_maps, food_prompt, grams_for, overlay_data_url,
                                        shape_for)

SETTINGS = {"PLATE_DIAMETER_CM": 27.0, "PORTION_FOOD_THRESHOLD": 0.4, "PORTION_PLATE_THRESHOLD": 0.3,
            "PORTION_MIN_PLATE_SHARE": 0.15, "PORTION_MAX_FOOD_SHARE": 0.75, "PORTION_BOWL_RATIO": 0.7}
PLATE_CM2 = math.pi * 13.5 ** 2                       # 572.6 cm2

RICE = {"id": 1, "name": "Steamed Rice", "category": "Rice", "serving_unit": "bowl", "serving_grams": 150,
        "ai_prompt": "a photo of steamed white rice, plain boiled rice in a bowl"}
DAL = {"id": 2, "name": "Dal", "category": "Dal & Legumes", "serving_unit": "katori", "serving_grams": 150,
       "ai_prompt": "a photo of dal, yellow lentil curry in a bowl"}
LASSI = {"id": 3, "name": "Sweet Lassi", "category": "Dairy & Drinks", "serving_unit": "glass", "serving_grams": 250,
         "ai_prompt": "a photo of sweet lassi, a glass of thick white yogurt drink"}
ROTI = {"id": 4, "name": "Roti / Chapati", "category": "Bread", "serving_unit": "piece", "serving_grams": 40,
        "ai_prompt": "a photo of roti or chapati"}
SINGJU = {"id": 5, "name": "Singju", "category": "Manipuri", "serving_unit": "plate", "serving_grams": 150,
          "ai_prompt": "a photo of singju, a Manipuri salad"}


def box(top, left, size, value=0.9, grid=100):
    """A map that is `value` inside a square and 0 elsewhere."""
    found = torch.zeros(grid, grid)
    found[top:top + size, left:left + size] = value
    return found


def test_prompts_drop_the_photo_words_and_the_container():
    assert food_prompt(RICE) == "steamed white rice, plain boiled rice"
    assert food_prompt(DAL) == "dal, yellow lentil curry"
    assert food_prompt(LASSI) == "sweet lassi, thick white yogurt drink"


def test_grams_follow_area_height_and_density():
    assert grams_for(50, DAL) == 150                    # a katori: 50 cm2 x 3 cm x 1.0
    assert grams_for(100, RICE) == 125                  # 100 x 1.8 x 0.7 = 126 -> rounded to 5 g
    assert grams_for(1, RICE) == 40                     # never below a quarter serving (37.5 -> 40)
    assert grams_for(5000, RICE) == 450                 # never above 3 servings
    assert shape_for(ROTI) == (0.4, 0.6)                # bread is flat
    assert shape_for(SINGJU) == (2.5, 0.35)             # a salad is airy, whatever its category
    assert shape_for(LASSI) is None                     # a drink's depth can't be seen


def test_a_plate_is_the_ruler():
    plate = box(0, 0, 80, 0.8)                          # 6400 px
    rice = box(10, 10, 40)                              # 1600 px = a quarter of the plate
    dal = box(60, 60, 15)                               # 225 px
    result = estimate_from_maps(plate, torch.stack([rice, dal]), [RICE, DAL], SETTINGS, bowl_map=box(60, 60, 15))
    assert result["method"] == "plate"
    rice_item, dal_item = result["items"]
    assert rice_item["area_cm2"] == round(PLATE_CM2 / 4)              # 143 cm2
    assert rice_item["grams"] == grams_for(PLATE_CM2 / 4, RICE) == 180
    assert dal_item["estimated"] and dal_item["grams"] == grams_for(225 / 6400 * PLATE_CM2, DAL)
    assert rice_item["colour"] != dal_item["colour"]


def test_each_pixel_goes_to_the_strongest_food():
    plate = box(0, 0, 80, 0.8)
    rice = box(10, 10, 40, 0.9)
    curd = box(10, 30, 40, 0.6)                         # overlaps the right half of the rice, but weaker
    labels = estimate_from_maps(plate, torch.stack([rice, curd]), [RICE, DAL], SETTINGS)["labels"]
    assert (labels == 0).sum() == 1600                  # rice keeps all its pixels
    assert (labels == 1).sum() == 40 * 20               # curd gets only the part the rice does not cover


@pytest.mark.parametrize("plate, rice, bowl, reason", [
    (box(0, 0, 30, 0.8), box(0, 0, 5), None, "No plate is visible"),               # plate only 9 % of the photo
    (box(0, 0, 80, 0.8), box(0, 0, 75), None, "fills the whole dish"),             # food is 88 % of the plate
    (box(0, 0, 80, 0.8), box(10, 10, 30), box(0, 0, 70, 0.9), "in a bowl"),        # bowl as big as the plate
])
def test_no_ruler_no_guess(plate, rice, bowl, reason):
    result = estimate_from_maps(plate, rice.unsqueeze(0), [RICE], SETTINGS, bowl_map=bowl)
    assert result["method"] == "none"
    assert reason in result["message"]
    item = result["items"][0]
    assert not item["estimated"] and item["grams"] == 150 and item["servings"] == 1.0   # the standard serving


def test_foods_that_cannot_be_measured_keep_their_serving():
    plate = box(0, 0, 80, 0.8)
    maps = torch.stack([box(10, 10, 30), torch.zeros(100, 100), box(50, 50, 10)])
    items = estimate_from_maps(plate, maps, [RICE, DAL, LASSI], SETTINGS)["items"]
    assert items[0]["estimated"]
    assert not items[1]["estimated"] and items[1]["note"] == "Not found in the photo"
    assert not items[2]["estimated"] and "drink" in items[2]["note"]


def test_overlay_is_a_small_jpeg():
    labels = torch.full((100, 100), -1)
    labels[10:40, 10:40] = 0
    url = overlay_data_url(Image.new("RGB", (800, 600), "white"), labels, ["#e6194b"])
    assert url.startswith("data:image/jpeg;base64,")
    assert len(url) < 100_000


PORTION_MODEL = (Config.MODEL_CACHE_DIR / "models--CIDAS--clipseg-rd64-refined").exists()


@pytest.mark.skipif(not PORTION_MODEL, reason="CLIPSeg model not downloaded yet")
def test_real_model_on_the_sample_thali():
    from services.portion_estimator import PORTION_SETTING_KEYS, estimator_from_config

    settings = {key: getattr(Config, key) for key in PORTION_SETTING_KEYS + ("PORTION_MODEL_NAME", "MODEL_CACHE_DIR")}
    estimator = estimator_from_config(settings)
    result = estimator.estimate(Image.open("static/img/example-thali.jpg").convert("RGB"), [RICE, DAL])
    assert result["method"] == "plate"
    rice, dal = result["items"]
    assert rice["estimated"] and 120 <= rice["grams"] <= 300     # the heap of rice: about 190 g
    assert dal["estimated"] and 50 <= dal["grams"] <= 200        # the katori of dal: about 95 g
    assert result["overlay"].startswith("data:image/jpeg")
