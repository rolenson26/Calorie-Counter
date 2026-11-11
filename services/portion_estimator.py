"""
services/portion_estimator.py - estimate how many grams of each chosen food are on the plate.

The idea (added 2026-11-12)
    A photo has no ruler, but a plate is one: most Indian dinner plates (thalis) are about
    27 cm across. CLIPSeg, a second pretrained model built on CLIP, takes a photo and a
    sentence and returns a map of the photo showing WHERE that sentence is (0 to 1 per pixel).
    We ask it for "a plate" and for every food the user put on "Your plate":

        1. Each pixel goes to the food whose map is strongest there (if at least 0.4),
           so two foods never share a pixel. This also shows where each food is.
        2. area of a food (cm2) = its pixels / the plate's pixels x the real plate area
        3. grams = area x typical height (cm) x density (g per cm3), by kind of serving
        4. the answer is kept between 1/4 and 3 standard servings

    When there is no plate in view (a close-up of one bowl), or the food fills the whole
    dish, nothing of known size is in the photo, so we do NOT guess: the standard serving
    is kept and the page says why. The user can always change every number.

Input : an RGB PIL image, and the foods (rows of the foods table) the user chose
Output: dict with method ("plate" or "none"), message, and one item per food:
        food_id, estimated (bool), grams, servings, area_cm2, colour, note
        plus overlay: the photo with each food's area coloured in (a JPEG data URL)
"""
import base64
import io
import math
import re

import torch
from PIL import Image

PLATE_PROMPT = "a plate"          # covered about half of the sample thali photo, as it should
BOWL_PROMPT = "a bowl"            # a close-up of one bowl must not be mistaken for a plate
CONTAINER_PHRASE = re.compile(r"\s+in an? (small )?(bowl|cup|glass|katori)\b")
CONTAINER_START = re.compile(r"\ban? (bowl|cup|glass|plate) of ")

# How thick a food usually lies (cm) and how heavy it is (g per cm3), by its serving unit.
# Checked against the standard servings: a katori of dal is about 8 cm across (50 cm2)
# x 3 cm x 1.0 = 150 g, and a heap of rice covering a third of a thali is about 250 g.
SHAPES = {
    "katori": (3.0, 1.0),     # dal, curry, curd: liquid-like, in a small bowl
    "bowl": (1.8, 0.7),       # rice, upma: a loose heap
    "plate": (1.8, 0.7),      # biryani, pulao, noodles: a loose heap
    "cup": (2.5, 0.8),        # cut fruit
    "piece": (2.0, 0.6),      # idli, samosa, momos
    "slice": (1.0, 0.6),      # pizza
    "fruit": (4.0, 0.9),      # a whole fruit
}
SALAD = (2.5, 0.35)           # shredded or chopped raw vegetables: a high but airy heap
CATEGORY_SHAPES = {
    "Bread": (0.4, 0.6),      # roti, paratha, naan are flat
    "Salad": SALAD,
}
NAME_SHAPES = {"Singju": SALAD}   # a Manipuri salad (category "Manipuri")
NO_ESTIMATE_UNITS = {"glass"}   # the depth of a drink cannot be seen from above

# One colour per food on the photo (and next to its name on the page). Up to 10 foods.
COLOURS = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
           "#42d4f4", "#f032e6", "#9a6324", "#469990", "#800000"]

MESSAGES = {
    "plate": "Measured against a standard {diameter:g} cm plate. These are estimates from one photo: "
             "check each one and change any that look wrong.",
    "no_plate": "No plate is visible, so there is nothing of known size to measure against. "
                "The standard serving is kept: change it if needed.",
    "fills": "The food fills the whole dish, so there is nothing of known size to measure against. "
             "The standard serving is kept: change it if needed.",
    "bowl": "The food is in a bowl, and bowls come in many sizes, so there is nothing of known size "
            "to measure against. The standard serving is kept: change it if needed.",
}


def food_prompt(food):
    """The sentence CLIPSeg looks for: the food's description without 'a photo of' and without
    its container. "steamed white rice, plain boiled rice in a bowl" made CLIPSeg mark a bowl
    (4 % of the sample thali) instead of the heap of rice (17 %); the name alone fails for
    some foods ("dal" was found nowhere), so the description is kept."""
    text = food["ai_prompt"].removeprefix("a photo of ")
    text = CONTAINER_PHRASE.sub("", text)
    return CONTAINER_START.sub("", text).strip(" ,")


def shape_for(food):
    """(height cm, density g/cm3) for a food, or None when it cannot be judged from above."""
    if food["serving_unit"] in NO_ESTIMATE_UNITS:
        return None
    return (NAME_SHAPES.get(food["name"]) or CATEGORY_SHAPES.get(food["category"])
            or SHAPES.get(food["serving_unit"], (2.0, 0.7)))


def grams_for(area_cm2, food, min_servings=0.25, max_servings=3.0):
    """Area on the plate -> grams, kept between min_servings and max_servings, rounded to 5 g."""
    height, density = shape_for(food)
    grams = area_cm2 * height * density
    low, high = min_servings * food["serving_grams"], max_servings * food["serving_grams"]
    grams = min(max(grams, low), high)
    return max(5, round(grams / 5) * 5)


def estimate_from_maps(plate_map, food_maps, foods, settings, bowl_map=None):
    """The whole decision, from CLIPSeg's maps (0-1 per pixel) to grams. No model needed here.

    plate_map : H x W tensor for "a plate"
    food_maps : N x H x W tensor, one map per food, in the same order as `foods`
    settings  : dict with PLATE_DIAMETER_CM, PORTION_FOOD_THRESHOLD, PORTION_PLATE_THRESHOLD,
                PORTION_MIN_PLATE_SHARE, PORTION_MAX_FOOD_SHARE, PORTION_BOWL_RATIO
    bowl_map  : H x W tensor for "a bowl" (optional). If the bowl region is nearly as big as
                the plate region, the dish is a bowl and there is no ruler.
    Returns the result dict (see the module docstring) plus "labels": H x W tensor of food
    positions (-1 = no food), used to draw the overlay.
    """
    strongest, which = food_maps.max(dim=0)
    labels = torch.where(strongest >= settings["PORTION_FOOD_THRESHOLD"], which, torch.full_like(which, -1))
    food_px = [int((labels == i).sum()) for i in range(len(foods))]

    plate_mask = (plate_map >= settings["PORTION_PLATE_THRESHOLD"]) | (labels >= 0)   # food lies on the plate
    plate_px = int(plate_mask.sum())
    plate_share = plate_px / labels.numel()
    food_share = sum(food_px) / plate_px if plate_px else 1.0
    plate_cm2 = math.pi * (settings["PLATE_DIAMETER_CM"] / 2) ** 2
    bowl_share = 0.0
    if bowl_map is not None:
        bowl_share = int((bowl_map >= settings["PORTION_PLATE_THRESHOLD"]).sum()) / labels.numel()

    if plate_share < settings["PORTION_MIN_PLATE_SHARE"]:
        method, reason = "none", "no_plate"
    elif bowl_share >= settings["PORTION_BOWL_RATIO"] * plate_share:
        method, reason = "none", "bowl"
    elif food_share > settings["PORTION_MAX_FOOD_SHARE"]:
        method, reason = "none", "fills"
    else:
        method, reason = "plate", "plate"

    items = []
    for i, food in enumerate(foods):
        item = {"food_id": food["id"], "name": food["name"], "estimated": False,
                "grams": food["serving_grams"], "servings": 1.0, "area_cm2": None,
                "colour": COLOURS[i % len(COLOURS)] if food_px[i] else None, "note": None}
        if method == "plate":
            if shape_for(food) is None:
                item["note"] = "A drink's amount cannot be seen from above"
            elif food_px[i] == 0:
                item["note"] = "Not found in the photo"
            else:
                area = food_px[i] / plate_px * plate_cm2
                grams = grams_for(area, food)
                item.update(estimated=True, grams=grams, area_cm2=round(area),
                            servings=round(grams / food["serving_grams"], 2))
        items.append(item)

    return {
        "method": method,
        "message": MESSAGES[reason].format(diameter=settings["PLATE_DIAMETER_CM"]),
        "plate_share": round(plate_share, 3),
        "bowl_share": round(bowl_share, 3),
        "food_share_of_plate": round(food_share, 3),
        "items": items,
        "labels": labels,
    }


def overlay_data_url(image, labels, colours, alpha=0.45, max_side=640):
    """The photo with each food's pixels tinted in its colour, as a small JPEG data URL."""
    image = image.copy()
    image.thumbnail((max_side, max_side))
    label_image = Image.fromarray((labels + 1).to(torch.uint8).numpy()).resize(image.size, Image.NEAREST)
    tint = Image.new("RGB", image.size)
    mask = Image.new("L", image.size, 0)
    for i, colour in enumerate(colours):
        if colour is None:
            continue
        region = label_image.point(lambda v, wanted=i + 1: 255 if v == wanted else 0)
        tint.paste(colour, mask=region)
        mask.paste(int(255 * alpha), mask=region)
    blended = Image.composite(tint, image, mask)
    buffer = io.BytesIO()
    blended.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


class PortionEstimator:
    """Loads CLIPSeg once and estimates portions for one photo at a time."""

    def __init__(self, model_name, cache_dir=None, settings=None):
        from transformers import CLIPSegForImageSegmentation, CLIPSegProcessor

        def load(cls):
            """Use the copy in models/ if it is there (no network); otherwise download it once."""
            try:
                return cls.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
            except OSError:
                return cls.from_pretrained(model_name, cache_dir=cache_dir)

        self.processor = load(CLIPSegProcessor)
        self.model = load(CLIPSegForImageSegmentation)
        self.model.eval()
        self.settings = settings
        self.maps(Image.new("RGB", (64, 64)), [PLATE_PROMPT, BOWL_PROMPT])   # warm-up: the first real call is then ~3x faster

    @torch.inference_mode()
    def maps(self, image, prompts):
        """One 352 x 352 map (0 to 1 per pixel) for every prompt."""
        inputs = self.processor(text=prompts, images=[image] * len(prompts), padding=True, return_tensors="pt")
        logits = self.model(**inputs).logits
        return logits.reshape(len(prompts), *logits.shape[-2:]).sigmoid()

    def estimate(self, image, foods):
        found = self.maps(image, [PLATE_PROMPT, BOWL_PROMPT] + [food_prompt(food) for food in foods])
        result = estimate_from_maps(found[0], found[2:], foods, self.settings, bowl_map=found[1])
        labels = result.pop("labels")
        colours = [item["colour"] for item in result["items"]]
        result["overlay"] = overlay_data_url(image, labels, colours) if any(colours) else None
        return result


PORTION_SETTING_KEYS = ("PLATE_DIAMETER_CM", "PORTION_FOOD_THRESHOLD", "PORTION_PLATE_THRESHOLD",
                        "PORTION_MIN_PLATE_SHARE", "PORTION_MAX_FOOD_SHARE", "PORTION_BOWL_RATIO")


def estimator_from_config(config):
    """Build a PortionEstimator from config.py settings (a dict such as app.config)."""
    return PortionEstimator(config["PORTION_MODEL_NAME"], config["MODEL_CACHE_DIR"],
                            {key: config[key] for key in PORTION_SETTING_KEYS})
