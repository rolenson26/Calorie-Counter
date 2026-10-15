"""Tests for services/food_classifier.py.

The first tests need no AI model. The last ones load the real CLIP model, and
are skipped automatically if it has not been downloaded into models/ yet.
"""
import pytest
from PIL import Image

from config import Config
from services.food_classifier import FoodClassifier, Guess, confidence_level, pick_suggestions, prompts_for


@pytest.mark.parametrize("is_food, top, expected", [
    (True, 0.92, "high"),
    (True, 0.60, "high"),
    (True, 0.45, "medium"),
    (True, 0.30, "medium"),
    (True, 0.12, "low"),
    (False, 0.95, "not_food"),        # a confident label means nothing if it isn't food
])
def test_confidence_level(is_food, top, expected):
    assert confidence_level(is_food, top) == expected


def ranked(*scores):
    return [Guess(i, f"Food {i}", score) for i, score in enumerate(scores, start=1)]


def test_one_clear_dish_gives_just_the_top_3():
    picked = pick_suggestions(ranked(0.90, 0.03, 0.02, 0.01, 0.01))
    assert [g.food_id for g in picked] == [1, 2, 3]          # always 3, even below the minimum


def test_a_plate_of_several_dishes_offers_more():
    # Real scores for a plate of aloo matar, khichdi and chana dal: close together.
    picked = pick_suggestions(ranked(0.123, 0.119, 0.072, 0.070, 0.068, 0.065, 0.060, 0.051, 0.051, 0.043, 0.039))
    assert len(picked) == 8                                  # capped at the maximum
    assert pick_suggestions(ranked(0.157, 0.155, 0.143, 0.071, 0.071, 0.046, 0.038)) == \
        ranked(0.157, 0.155, 0.143, 0.071, 0.071, 0.046)     # the 0.038 food is below 4 %


def test_three_sentences_per_food():
    prompts = prompts_for({"name": "Roti / Chapati", "ai_prompt": "a photo of roti or chapati"})
    assert prompts == [
        "a photo of roti or chapati",
        "a photo of Roti or Chapati, a type of food.",
        "a close-up photo of Roti or Chapati.",
    ]


MODEL_DOWNLOADED = (Config.MODEL_CACHE_DIR / "models--openai--clip-vit-base-patch32").exists()
needs_model = pytest.mark.skipif(not MODEL_DOWNLOADED, reason="CLIP model not downloaded yet")

FOODS = [
    {"id": 1, "name": "Idli", "ai_prompt": "a photo of idli, white steamed South Indian rice cakes"},
    {"id": 2, "name": "Banana", "ai_prompt": "a photo of a banana, a yellow banana fruit"},
    {"id": 3, "name": "Pizza", "ai_prompt": "a photo of pizza, a cheese pizza slice"},
]


@pytest.fixture(scope="module")
def classifier():
    clf = FoodClassifier(Config.MODEL_NAME, Config.MODEL_CACHE_DIR)
    clf.set_foods(FOODS)
    return clf


@needs_model
def test_result_has_the_shape_the_api_expects(classifier):
    result = classifier.classify(Image.new("RGB", (300, 300), (230, 200, 60)))
    assert result.level in ("high", "medium", "low", "not_food")
    assert len(result.top3) == 3
    assert {g.food_id for g in result.top3} == {1, 2, 3}
    assert 0.99 <= sum(g.confidence for g in result.top3) <= 1.01     # only 3 labels, so they add up to 1
    assert result.top3[0].confidence >= result.top3[1].confidence
    assert result.suggestions == result.top3                          # with only 3 labels, nothing more to offer


@needs_model
def test_a_new_food_becomes_a_label_without_training(classifier):
    classifier.add_food({"id": 4, "name": "Pav Bhaji", "ai_prompt": "a photo of pav bhaji"})
    assert [f["name"] for f in classifier.foods][-1] == "Pav Bhaji"
    assert classifier.food_vectors.shape == (4, 512)
    result = classifier.classify(Image.new("RGB", (300, 300), (200, 80, 40)))
    assert len(result.top3) == 3
