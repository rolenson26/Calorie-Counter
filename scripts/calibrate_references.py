"""
scripts/calibrate_references.py - choose the settings of the few-shot step (reference_bonus)
and measure what it changes. Uses the real CLIP model and the app's own scoring code.

    python -m scripts.calibrate_references

Photos used (prepared by scripts/prepare_photos.py and scripts/export_indian_food.py):
    data/reference_photos/<Food>/   example photos. For tuning, each one is classified with
                                    itself LEFT OUT of the examples ("leave-one-out"), so it is
                                    always a photo the method has not seen.
    data/indian_food_test/          941 public photos of other Indian foods: these must NOT be
                                    pulled towards a Manipuri dish ("stolen").
    data/test_photos/<Food>/        held-out Manipuri photos. NOT used to choose the settings;
                                    reported at the end as the honest result.
"""
import itertools
from pathlib import Path

import torch

from services.food_classifier import _key, _load_classifier, _open

DATA = Path("data")
CACHE = DATA / "_downloads" / "calibration_vectors.pt"


def photo_vectors(clf, folder):
    """[(food folder name, vector)] for every photo in folder/<name>/."""
    items = []
    for food_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        for path in sorted(food_dir.iterdir()):
            items.append((food_dir.name, clf.encode_image(_open(path))))
    return items


def main():
    clf = _load_classifier()
    if CACHE.exists():
        groups = torch.load(CACHE)
    else:
        print("Computing photo vectors once (about 2 minutes) ...")
        groups = {name: photo_vectors(clf, DATA / name)
                  for name in ("reference_photos", "test_photos", "indian_food_test")}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        torch.save(groups, CACHE)

    position = {_key(f["name"]): i for i, f in enumerate(clf.foods)}
    refs = groups["reference_photos"]
    ref_vectors = torch.cat([v for _, v in refs])
    ref_owner = torch.tensor([position[_key(name)] for name, _ in refs])
    manipuri = set(ref_owner.tolist())
    foods, text_vectors = clf.foods, clf.food_vectors

    def top1(vector, rv, ro):
        return clf.food_probabilities(vector, (foods, text_vectors, rv, ro)).argmax().item()

    def evaluate():
        keep = torch.ones(len(refs), dtype=torch.bool)
        loo_right = 0
        for j, (name, vector) in enumerate(refs):                     # leave-one-out on the examples
            keep[j] = False
            loo_right += top1(vector, ref_vectors[keep], ref_owner[keep]) == position[_key(name)]
            keep[j] = True
        known_right = known_stolen = unknown_stolen = n_known = n_unknown = 0
        for name, vector in groups["indian_food_test"]:
            guess = top1(vector, ref_vectors, ref_owner)
            if name == "unknown_food":
                n_unknown += 1
                unknown_stolen += guess in manipuri
            else:
                n_known += 1
                known_right += guess == position[_key(name)]
                known_stolen += guess in manipuri
        return {"loo": loo_right / len(refs), "known": known_right / n_known,
                "stolen": known_stolen + unknown_stolen, "n_other": n_known + n_unknown}

    def held_out():
        right = sum(top1(v, ref_vectors, ref_owner) == position[_key(n)] for n, v in groups["test_photos"])
        return right / len(groups["test_photos"])

    clf.reference_weight = 0.0
    base = evaluate()
    print(f"\nText only (no examples): examples {base['loo']:.0%}, other Indian foods top-1 {base['known']:.0%}, "
          f"photos pulled to a Manipuri dish {base['stolen']}/{base['n_other']}, "
          f"held-out Manipuri {held_out():.0%}\n")

    print(f"{'k':>2} {'thresh':>6} {'weight':>6} | {'examples':>8} {'other':>6} {'stolen':>6}")
    results = []
    for k, threshold, weight in itertools.product((1, 3, 5), (0.70, 0.75, 0.80, 0.85), (25, 50, 100, 200)):
        clf.reference_top_k, clf.reference_threshold, clf.reference_weight = k, threshold, weight
        r = evaluate()
        results.append(((k, threshold, weight), r))
        print(f"{k:>2} {threshold:>6.2f} {weight:>6} | {r['loo']:>8.0%} {r['known']:>6.0%} {r['stolen']:>6}")

    # Best = most examples right, among settings that pull at most 1 % of other photos and do not
    # lower the other foods' accuracy by more than 1 point.
    allowed = [(p, r) for p, r in results
               if r["stolen"] <= 0.01 * r["n_other"] and r["known"] >= base["known"] - 0.01]
    (k, threshold, weight), r = max(allowed, key=lambda pr: (pr[1]["loo"], -pr[1]["stolen"]))
    clf.reference_top_k, clf.reference_threshold, clf.reference_weight = k, threshold, weight
    print(f"\nChosen: top_k={k}, threshold={threshold}, weight={weight}")
    print(f"  examples (leave-one-out) {r['loo']:.0%}, other Indian foods {r['known']:.0%} "
          f"(was {base['known']:.0%}), pulled {r['stolen']}/{r['n_other']}")
    print(f"  HELD-OUT Manipuri photos: {held_out():.0%} top-1")


if __name__ == "__main__":
    main()
