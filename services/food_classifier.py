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
Output: a ClassificationResult (is_food, food_probability, level, top3, suggestions)
        suggestions = the top 3 plus other likely foods (for plates with several dishes)

Few-shot example photos (added 2026-11-12, for the Manipuri dishes)
    CLIP has rarely seen dishes like Eromba, so a sentence is not enough. For such foods we
    keep the vectors of ~20 example photos. A photo that looks very much like a food's
    examples gets a bonus for that food (reference_bonus). Still nothing is trained.

Command line (run from the project folder):
    python -m services.food_classifier photo.jpg [more.jpg ...]
    python -m services.food_classifier --evaluate my_test_photos [--no-references]
        (my_test_photos/<Food Name>/*.jpg, plus an optional my_test_photos/not_food/)
    python -m services.food_classifier --build-references data/reference_photos
        (saves the example-photo vectors to data/reference_embeddings.pt)
"""
import threading
import time
from dataclasses import asdict, dataclass, field

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
    suggestions: list = field(default_factory=list)   # top3 + other likely foods, best first (shown to the user)

    def as_dict(self):
        return asdict(self)


def prompts_for(food):
    """Three sentences per food. Their average vector ("prompt ensembling") is more
    reliable than one sentence: on our test photos top-1 accuracy rose from 73% to 77%."""
    name = food["name"].replace(" / ", " or ")
    return [food["ai_prompt"], f"a photo of {name}, a type of food.", f"a close-up photo of {name}."]


def pick_suggestions(guesses, top_k=3, minimum=0.04, maximum=8):
    """The foods to offer the user: always the first top_k, then any other guess scoring at
    least `minimum`, at most `maximum` in all. `guesses` must be sorted best first.

    CLIP scores the whole photo, it does not find separate items. But when a plate holds
    several dishes, their scores are close to each other, so they tend to pass `minimum`."""
    return [g for i, g in enumerate(guesses) if i < top_k or g.confidence >= minimum][:maximum]


def reference_bonus(image_vector, ref_vectors, ref_owner, n_foods, threshold, weight, top_k=3):
    """Few-shot step: extra score for foods whose example photos look like this photo.

    image_vector : 1 x D photo vector (length 1)
    ref_vectors  : M x D vectors of the example ("reference") photos (length 1)
    ref_owner    : M food positions, ref_owner[j] = which food example photo j shows
    For every food that has examples: similarity = average of its top_k most similar
    example photos. If that is above `threshold`, the food gets
    weight x (similarity - threshold) added to its score; otherwise nothing.

    Why a threshold? Two food photos are always fairly similar to each other (about 0.6-0.8),
    much more than a photo and a sentence (about 0.3). Without a threshold every food
    that has example photos would get a bonus on every photo and "steal" the answer.
    Nothing is trained: adding example photos is the whole learning step (this is the idea
    behind Tip-Adapter, Zhang et al., 2022, a training-free few-shot CLIP method).
    """
    bonus = torch.zeros(n_foods)
    if ref_vectors is None or len(ref_vectors) == 0:
        return bonus
    similarities = (image_vector @ ref_vectors.T)[0]
    for food in ref_owner.unique().tolist():
        own = similarities[ref_owner == food]
        score = own.topk(min(top_k, len(own))).values.mean().item()
        bonus[food] = weight * max(0.0, score - threshold)
    return bonus


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

    def __init__(self, model_name, cache_dir=None, high=0.60, low=0.30, gate=0.50,
                 suggestion_min=0.04, max_suggestions=8,
                 reference_threshold=0.80, reference_weight=100.0, reference_top_k=3):
        # Imported here so that tests and pages that never use the model start quickly.
        from transformers import CLIPModel, CLIPProcessor

        def load(cls):
            """Use the copy in models/ if it is there (no network); otherwise download it once."""
            try:
                return cls.from_pretrained(model_name, cache_dir=cache_dir, local_files_only=True)
            except OSError:
                return cls.from_pretrained(model_name, cache_dir=cache_dir)

        self.model_name = model_name
        self.model = load(CLIPModel)
        self.processor = load(CLIPProcessor)
        self.model.eval()                                  # inference mode: no training
        self.scale = self.model.logit_scale.exp().item()   # CLIP's learned scale (100)
        self.high, self.low, self.gate = high, low, gate
        self.suggestion_min, self.max_suggestions = suggestion_min, max_suggestions
        self.reference_threshold, self.reference_weight = reference_threshold, reference_weight
        self.reference_top_k = reference_top_k

        self._lock = threading.Lock()                      # labels can change while a request runs
        self.foods = []                                    # same order as the rows of food_vectors
        self.food_vectors = torch.empty(0, self.model.config.projection_dim)
        self.gate_vectors = self.encode_text(FOOD_PROMPTS + NOT_FOOD_PROMPTS)
        self.references = {}                               # food name -> N x D vectors of example photos
        self.ref_vectors, self.ref_owner = None, None      # the same, stacked, matched to self.foods

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
            self._match_references()

    def add_food(self, food):
        """Add one new food (for example a custom food) without retraining anything."""
        entry = {"id": food["id"], "name": food["name"], "ai_prompt": food["ai_prompt"]}
        vector = self.food_vectors_for([entry])
        with self._lock:
            self.foods = self.foods + [entry]
            self.food_vectors = torch.cat([self.food_vectors, vector])
            self._match_references()

    # ------------------------------------------------------------ example photos (few-shot)

    def set_references(self, references):
        """Use example photos: {food name: N x D tensor of their vectors}. See reference_bonus."""
        with self._lock:
            self.references = dict(references)
            self._match_references()

    def _match_references(self):
        """Stack the example vectors of the foods we have, remembering which food each belongs to.
        Called with the lock held. Foods are matched by name, ignoring case and punctuation."""
        position = {_key(food["name"]): i for i, food in enumerate(self.foods)}
        vectors, owners = [], []
        for name, food_vectors in self.references.items():
            if _key(name) in position:
                vectors.append(food_vectors)
                owners += [position[_key(name)]] * len(food_vectors)
        if vectors:
            self.ref_vectors, self.ref_owner = torch.cat(vectors), torch.tensor(owners)
        else:
            self.ref_vectors, self.ref_owner = None, None

    def load_references(self, path):
        """Load example-photo vectors saved by save_references. Returns how many foods got examples.
        A missing file is fine (the app then works on text alone)."""
        from pathlib import Path

        path = Path(path)
        if not path.exists():
            return 0
        saved = torch.load(path)
        if saved.get("model") != self.model_name:
            raise ValueError(f"{path} was made with {saved.get('model')}, not {self.model_name}")
        self.set_references(saved["foods"])
        return len(saved["foods"])

    def save_references(self, references, path):
        """Save {food name: vectors} with the model name, so a different model never uses them."""
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"model": self.model_name, "foods": references}, path)

    def build_references(self, folder):
        """Vectors of the photos in folder/<Food Name>/*.jpg -> {food name: N x D tensor}."""
        from services.image_processor import load_image

        references = {}
        for food_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
            photos = sorted(p for p in food_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
            vectors = [self.encode_image(load_image(p, p.name, {"jpg", "jpeg", "png", "webp"}, 40_000_000))
                       for p in photos]
            if vectors:
                references[food_dir.name] = torch.cat(vectors)
        return references

    # ------------------------------------------------------------ prediction

    def _probabilities(self, image_vector, text_vectors, bonus=None):
        """Cosine similarity x 100 (+ the example-photo bonus), then softmax -> probabilities that add up to 1."""
        scores = self.scale * image_vector @ text_vectors.T
        if bonus is not None:
            scores = scores + bonus
        return scores.softmax(dim=-1)[0]

    def food_probabilities(self, image_vector, foods_snapshot=None):
        """Probabilities over all foods for one photo vector (text match + example-photo bonus)."""
        foods, vectors, ref_vectors, ref_owner = foods_snapshot or self._snapshot()
        bonus = reference_bonus(image_vector, ref_vectors, ref_owner, len(foods),
                                self.reference_threshold, self.reference_weight, self.reference_top_k)
        return self._probabilities(image_vector, vectors, bonus)

    def _snapshot(self):
        with self._lock:
            return self.foods, self.food_vectors, self.ref_vectors, self.ref_owner

    def classify(self, image, top_k=3):
        """Answer both questions for one RGB image."""
        start = time.perf_counter()
        image_vector = self.encode_image(image)

        gate = self._probabilities(image_vector, self.gate_vectors)
        food_probability = gate[: len(FOOD_PROMPTS)].sum().item()
        is_food = food_probability >= self.gate

        snapshot = self._snapshot()
        foods = snapshot[0]
        if not foods:
            raise RuntimeError("No foods loaded: call set_foods() first")
        probabilities = self.food_probabilities(image_vector, snapshot)
        best = probabilities.topk(min(max(top_k, self.max_suggestions), len(foods)))
        ranked = [
            Guess(foods[i]["id"], foods[i]["name"], round(p, 4))
            for p, i in zip(best.values.tolist(), best.indices.tolist())
        ]
        top = ranked[:top_k]

        return ClassificationResult(
            is_food=is_food,
            food_probability=round(food_probability, 4),
            level=confidence_level(is_food, top[0].confidence, self.high, self.low),
            top3=top,
            seconds=round(time.perf_counter() - start, 3),
            suggestions=pick_suggestions(ranked, top_k, self.suggestion_min, self.max_suggestions),
        )


# ================================================================ command line

def classifier_from_config(config):
    """Build a FoodClassifier with every AI setting from config.py (a dict or the Config class)."""
    get = config.get if isinstance(config, dict) else lambda key: getattr(config, key)
    return FoodClassifier(
        get("MODEL_NAME"), get("MODEL_CACHE_DIR"),
        get("HIGH_CONFIDENCE"), get("LOW_CONFIDENCE"), get("FOOD_GATE_THRESHOLD"),
        get("SUGGESTION_MIN_CONFIDENCE"), get("MAX_SUGGESTIONS"),
        get("REFERENCE_THRESHOLD"), get("REFERENCE_WEIGHT"), get("REFERENCE_TOP_K"),
    )


def _load_classifier(use_references=True):
    from config import Config
    from database.db import connect, init_db

    conn = connect(Config.DATABASE)
    init_db(conn)
    foods = [dict(row) for row in conn.execute("SELECT id, name, ai_prompt FROM foods")]
    conn.close()

    print(f"Loading {Config.MODEL_NAME} ...")
    start = time.perf_counter()
    classifier = classifier_from_config(Config)
    classifier.set_foods(foods)
    examples = classifier.load_references(Config.REFERENCE_FILE) if use_references else 0
    print(f"Ready in {time.perf_counter() - start:.1f} s with {len(foods)} foods as labels"
          f" ({examples} with example photos)\n")
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
    parser.add_argument("--build-references", action="store_true",
                        help="save the vectors of the example photos in a folder of sub-folders named after foods")
    parser.add_argument("--no-references", action="store_true",
                        help="ignore the example photos (text descriptions only), to compare before/after")
    args = parser.parse_args()
    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:                                    # check before spending seconds loading the model
        parser.error("not found: " + ", ".join(missing))

    clf = _load_classifier(use_references=not (args.no_references or args.build_references))
    if args.build_references:
        from config import Config

        built = clf.build_references(args.paths[0])
        unknown = [name for name in built if _key(name) not in {_key(f["name"]) for f in clf.foods}]
        if unknown:
            parser.error("these folders are not foods in the database: " + ", ".join(unknown))
        clf.save_references(built, Config.REFERENCE_FILE)
        for name, vectors in built.items():
            print(f"{name:<12} {len(vectors)} example photos")
        print(f"Saved to {Config.REFERENCE_FILE}")
    elif args.evaluate:
        _evaluate(clf, args.paths[0])
    else:
        for image_path in args.paths:
            print(f"{image_path.name}: {_describe(clf.classify(_open(image_path)))}")
