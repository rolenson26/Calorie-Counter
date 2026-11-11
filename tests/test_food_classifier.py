"""Tests for services/food_classifier.py.

The first tests need no AI model. The last ones load the real CLIP model, and
are skipped automatically if it has not been downloaded into models/ yet.
"""
import pytest
import torch
from PIL import Image

from config import Config
from services.food_classifier import (FoodClassifier, Guess, confidence_level, pick_suggestions, prompts_for,
                                      reference_bonus)


def unit(*values):
    vector = torch.tensor([values], dtype=torch.float32)
    return vector / vector.norm()


# Example photos of food 1 (two of them) and food 2 (one), in a 2-number "embedding" space.
REF_VECTORS = torch.cat([unit(1, 0), unit(0.95, 0.05), unit(0, 1)])
REF_OWNER = torch.tensor([1, 1, 2])


def test_bonus_only_for_foods_whose_examples_look_alike():
    bonus = reference_bonus(unit(1, 0.02), REF_VECTORS, REF_OWNER, n_foods=3, threshold=0.8, weight=100, top_k=2)
    assert bonus[0] == 0                       # food 0 has no example photos
    assert bonus[1] > 15                       # very similar to food 1's examples (about 0.999)
    assert bonus[2] == 0                       # food 2's example is far away: below the threshold


def test_no_bonus_below_the_threshold_and_none_without_examples():
    halfway = unit(1, 1)                       # similarity about 0.7 to both foods
    assert reference_bonus(halfway, REF_VECTORS, REF_OWNER, 3, threshold=0.8, weight=100).sum() == 0
    assert reference_bonus(halfway, None, None, 3, threshold=0.8, weight=100).sum() == 0


def test_bonus_uses_the_average_of_the_top_k_examples():
    photo = unit(1, 0)
    one = reference_bonus(photo, REF_VECTORS, REF_OWNER, 3, threshold=0.5, weight=1, top_k=1)[1].item()
    two = reference_bonus(photo, REF_VECTORS, REF_OWNER, 3, threshold=0.5, weight=1, top_k=2)[1].item()
    assert one == pytest.approx(0.5)           # best example is identical: 1.0 - 0.5
    assert one > two > 0                       # the second example is a little less similar


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


@needs_model
def test_example_photos_make_their_food_win(classifier, tmp_path):
    """Give 'Banana' example photos of a plain purple square: a purple photo becomes 'Banana'."""
    purple = Image.new("RGB", (300, 300), (110, 40, 150))
    folder = tmp_path / "examples" / "Banana"
    folder.mkdir(parents=True)
    for i, shade in enumerate((140, 150, 160)):
        Image.new("RGB", (300, 300), (110, 40, shade)).save(folder / f"{i}.jpg")
    references = classifier.build_references(tmp_path / "examples")
    assert references["Banana"].shape == (3, 512)

    classifier.save_references(references, tmp_path / "refs.pt")
    assert classifier.load_references(tmp_path / "refs.pt") == 1
    assert classifier.classify(purple).top3[0].name == "Banana"
    classifier.set_references({})                                     # back to text only
    assert classifier.ref_vectors is None
    assert classifier.load_references(tmp_path / "missing.pt") == 0   # no file: text only, no error


def test_shipped_example_photos_match_foods_in_the_database():
    """data/reference_embeddings.pt must only name foods that exist, with 512-number vectors."""
    from database.nutrition_data import FOODS
    from services.food_classifier import _key

    saved = torch.load(Config.REFERENCE_FILE)
    assert saved["model"] == Config.MODEL_NAME
    names = {_key(food["name"]) for food in FOODS}
    for name, vectors in saved["foods"].items():
        assert _key(name) in names, name
        assert vectors.shape[1] == 512 and len(vectors) >= 5
