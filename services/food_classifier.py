"""
services/food_classifier.py - recognises food in a photo with CLIP (zero-shot).

The big idea (section 4 of the HLD)
    CLIP turns a photo into 512 numbers, and a sentence into 512 numbers.
    A photo and a sentence that describe the same thing get similar numbers.
    We describe every food in our database with three sentences
    ("a photo of idli, white steamed South Indian rice cakes", ...), average
    them into one vector per food, and the food closest to the photo is the
    prediction. Nothing is trained, so a food added to the database becomes
    a new label straight away.

Two questions are asked about every photo
    1. Food gate : is this food at all?       (food sentences vs non-food sentences)
    2. Which food: which of our foods is it?  (top 3, each with a confidence)

Input : an RGB PIL image (from image_processor)
Output: a ClassificationResult (is_food, food_probability, level, top3)

Command line (run from the project folder):
    python -m services.food_classifier photo.jpg [more.jpg ...]
    python -m services.food_classifier --evaluate my_test_photos
        (my_test_photos/<Food Name>/*.jpg, plus an optional my_test_photos/not_food/)
"""
import threading
import time
from dataclasses import asdict, dataclass

import torch

# Sentences for the food gate. Fruit and drinks are listed so chai or a banana still count as food.
FOOD_PROMPTS = [
    "a photo of food",
    "a photo of a cooked dish on a plate",
    "a close-up photo of a meal",
    "a photo of fruit",
    "a photo of a drink in a glass or cup",
]
NOT_FOOD_PROMPTS = [
    "a photo of a person",
    "a photo of an animal",
    "a screenshot, a document or text",
    "a photo of a room or a building",
    "a photo of a vehicle",
    "a photo of an everyday object",
    "a photo of a landscape",
]


@dataclass
class Guess:
    food_id: int
    name: str
    confidence: float          # 0 to 1, relative to the foods in our list


@dataclass
class ClassificationResult:
    is_food: bool
    food_probability: float    # food-gate score, 0 to 1
    level: str                 # "high", "medium", "low" or "not_food"
    top3: list                 # list of Guess, best first
    seconds: float             # how long the model took

    def as_dict(self):
        return asdict(self)


def prompts_for(food):
    """Three sentences per food. Their average vector ("prompt ensembling") is more
    reliable than one sentence: on our test photos top-1 accuracy rose from 73% to 77%."""
    name = food["name"].replace(" / ", " or ")
    return [food["ai_prompt"], f"a photo of {name}, a type of food.", f"a close-up photo of {name}."]


def confidence_level(is_food, top_confidence, high=0.60, low=0.30):
    """Turn the numbers into the level the page uses (HLD Module 3 table)."""
    if not is_food:
        return "not_food"
    if top_confidence >= high:
        return "high"
    if top_confidence >= low:
        return "medium"
    return "low"


class FoodClassifier:
    """Loads CLIP once and classifies photos against the current list of foods."""

    def __init__(self, model_name, cache_dir=None, high=0.60, low=0.30, gate=0.50):
        # Imported here so that tests and pages that never use the model start quickly.
        from transformers import CLIPModel, CLIPProcessor

        def load(cls):
            """Use the copy in models/ if it is there (no network); otherwise download it once."""
            try:
                return cls.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
            except OSError:
                return cls.from_pretrained(model_name, cache_dir=cache_dir)

        self.model = load(CLIPModel)
        self.processor = load(CLIPProcessor)
        self.model.eval()                                  # inference mode: no training
        self.scale = self.model.logit_scale.exp().item()   # CLIP's learned scale (100)
        self.high, self.low, self.gate = high, low, gate

        self._lock = threading.Lock()                      # labels can change while a request runs
        self.foods = []                                    # same order as the rows of food_vectors
        self.food_vectors = torch.empty(0, self.model.config.projection_dim)
        self.gate_vectors = self.encode_text(FOOD_PROMPTS + NOT_FOOD_PROMPTS)

    # ------------------------------------------------------------ embeddings

    @torch.inference_mode()
    def encode_text(self, sentences):
        """Sentences -> one 512-number vector each, scaled to length 1."""
        inputs = self.processor(text=sentences, return_tensors="pt", padding=True)
        vectors = self.model.get_text_features(**inputs).pooler_output
        return vectors / vectors.norm(dim=-1, keepdim=True)

    @torch.inference_mode()
    def encode_image(self, image):
        """Photo -> one 512-number vector, scaled to length 1.

        The processor resizes to 224 x 224 and normalises the colours the
        way CLIP was trained.
        """
        inputs = self.processor(images=image, return_tensors="pt")
        vector = self.model.get_image_features(**inputs).pooler_output
        return vector / vector.norm(dim=-1, keepdim=True)

    # ------------------------------------------------------------ labels

    def food_vectors_for(self, foods):
        """One vector per food: the average of its three sentence vectors, scaled to length 1."""
        sentences = [sentence for food in foods for sentence in prompts_for(food)]
        vectors = self.encode_text(sentences).reshape(len(foods), -1, self.food_vectors.shape[1])
        averaged = vectors.mean(dim=1)
        return averaged / averaged.norm(dim=-1, keepdim=True)

    def set_foods(self, foods):
        """Use these foods as the labels. Each food needs id, name and ai_prompt."""
        foods = [{"id": f["id"], "name": f["name"], "ai_prompt": f["ai_prompt"]} for f in foods]
        vectors = self.food_vectors_for(foods)
        with self._lock:
            self.foods, self.food_vectors = foods, vectors

    def add_food(self, food):
        """Add one new food (for example a custom food) without retraining anything."""
        entry = {"id": food["id"], "name": food["name"], "ai_prompt": food["ai_prompt"]}
        vector = self.food_vectors_for([entry])
        with self._lock:
            self.foods = self.foods + [entry]
            self.food_vectors = torch.cat([self.food_vectors, vector])

    # ------------------------------------------------------------ prediction

    def _probabilities(self, image_vector, text_vectors):
        """Cosine similarity x 100, then softmax -> probabilities that add up to 1."""
        scores = self.scale * image_vector @ text_vectors.T
        return scores.softmax(dim=-1)[0]

    def classify(self, image, top_k=3):
        """Answer both questions for one RGB image."""
        start = time.perf_counter()
        image_vector = self.encode_image(image)

        gate = self._probabilities(image_vector, self.gate_vectors)
        food_probability = gate[: len(FOOD_PROMPTS)].sum().item()
        is_food = food_probability >= self.gate

        with self._lock:
            foods, vectors = self.foods, self.food_vectors
        if not foods:
            raise RuntimeError("No foods loaded: call set_foods() first")
        probabilities = self._probabilities(image_vector, vectors)
        best = probabilities.topk(min(top_k, len(foods)))
        top = [
            Guess(foods[i]["id"], foods[i]["name"], round(p, 4))
            for p, i in zip(best.values.tolist(), best.indices.tolist())
        ]

        return ClassificationResult(
            is_food=is_food,
            food_probability=round(food_probability, 4),
            level=confidence_level(is_food, top[0].confidence, self.high, self.low),
            top3=top,
            seconds=round(time.perf_counter() - start, 3),
        )


# ================================================================ command line

def _load_classifier():
    from config import Config
    from database.db import connect, init_db

    conn = connect(Config.DATABASE)
    init_db(conn)
    foods = [dict(row) for row in conn.execute("SELECT id, name, ai_prompt FROM foods")]
    conn.close()

    print(f"Loading {Config.MODEL_NAME} ...")
    start = time.perf_counter()
    classifier = FoodClassifier(
        Config.MODEL_NAME, Config.MODEL_CACHE_DIR,
        Config.HIGH_CONFIDENCE, Config.LOW_CONFIDENCE, Config.FOOD_GATE_THRESHOLD,
    )
    classifier.set_foods(foods)
    print(f"Ready in {time.perf_counter() - start:.1f} s with {len(foods)} foods as labels\n")
    return classifier


def _open(path):
    from config import Config
    from services.image_processor import load_image

    return load_image(path, path.name, Config.ALLOWED_EXTENSIONS, Config.MAX_IMAGE_PIXELS)


def _describe(result):
    guesses = ", ".join(f"{g.name} {g.confidence:.0%}" for g in result.top3)
    return f"[{result.level:>8}] food {result.food_probability:.0%} | {guesses} | {result.seconds:.2f} s"


def _key(name):
    """'Roti / Chapati' and the folder name 'Roti - Chapati' both become 'rotichapati'."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _evaluate(classifier, folder):
    """Measure accuracy on a folder of test photos.

    folder/<Food Name>/*.jpg  - photos of a food in the database (top-1 / top-3 accuracy)
    folder/not_food/*.jpg     - photos that are not food (should be rejected by the food gate)
    folder/unknown_food/*.jpg - food that is NOT in the database (the app should ask the
                                user, so any level except "high" counts as handled)
    """
    known = {_key(f["name"]): f["name"] for f in classifier.foods}
    special = ("not_food", "unknown_food")
    rows, times = [], []
    for class_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        expected = class_dir.name if class_dir.name in special else known.get(_key(class_dir.name))
        if expected is None:
            print(f"Skipping folder '{class_dir.name}': no food with that name in the database")
            continue
        for path in sorted(class_dir.iterdir()):
            try:
                result = classifier.classify(_open(path))
            except Exception as exc:                       # a broken file should not stop the run
                print(f"  could not read {path.name}: {exc}")
                continue
            times.append(result.seconds)
            names = [g.name for g in result.top3]
            if expected == "not_food":
                top1 = top3 = not result.is_food
            elif expected == "unknown_food":
                top1 = top3 = result.level != "high"
            else:
                top1 = result.is_food and names[0] == expected
                top3 = result.is_food and expected in names
            rows.append((expected, path.name, result, top1, top3))
            mark = "OK " if top1 else ("top3" if top3 else "MISS")
            print(f"{mark:4} {expected:<22} {_describe(result)}")

    if not rows:
        print("No images found.")
        return
    food_rows = [r for r in rows if r[0] not in special]
    print("\n================ summary ================")
    print(f"Images            : {len(rows)} ({len(food_rows)} of foods in the database)")
    if food_rows:
        print(f"Top-1 accuracy    : {sum(r[3] for r in food_rows) / len(food_rows):.0%}")
        print(f"Top-3 accuracy    : {sum(r[4] for r in food_rows) / len(food_rows):.0%}")
    for name, label in (("not_food", "Non-food rejected "), ("unknown_food", "Unknown food asked")):
        group = [r for r in rows if r[0] == name]
        if group:
            print(f"{label}: {sum(r[3] for r in group)} of {len(group)}")
    print(f"Average time      : {sum(times) / len(times):.2f} s per photo")
    print("By level (how often the top food was right):")
    for level in ("high", "medium", "low", "not_food"):
        in_level = [r for r in food_rows if r[2].level == level]
        if in_level:
            right = sum(r[3] for r in in_level)
            print(f"   {level:<9} {len(in_level):>3} photos, top food right in {right} ({right / len(in_level):.0%})")


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Classify food photos with CLIP.")
    parser.add_argument("paths", nargs="+", type=Path, help="image files, or one folder with --evaluate")
    parser.add_argument("--evaluate", action="store_true",
                        help="measure accuracy on a folder of sub-folders named after foods")
    args = parser.parse_args()
    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:                                    # check before spending seconds loading the model
        parser.error("not found: " + ", ".join(missing))

    clf = _load_classifier()
    if args.evaluate:
        _evaluate(clf, args.paths[0])
    else:
        for image_path in args.paths:
            print(f"{image_path.name}: {_describe(clf.classify(_open(image_path)))}")
