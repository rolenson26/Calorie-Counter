"""
scripts/export_indian_food.py - download the public "Indian Food Images" test split and
save it as folders that `python -m services.food_classifier --evaluate` understands.

    python -m scripts.export_indian_food            (needs internet once; plain Python, no extra packages)

Dataset: https://huggingface.co/datasets/rajistics/indian_food_images (941 test photos, 20 classes).
It is read through Hugging Face's public "rows" API, which returns a link to every image.
Classes that are foods in our database go to data/indian_food_test/<Food Name>/.
Classes we do not have (jalebi, kulfi, ...) go to data/indian_food_test/unknown_food/: for those
the app should NOT be sure ("high"), it should ask the user.
"""
import io
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROWS_API = ("https://datasets-server.huggingface.co/rows?dataset=rajistics/indian_food_images"
            "&config=default&split=test&offset={offset}&length=100")

# Dataset class -> food name in database/nutrition_data.py (None = not in our database).
# "Roti - Chapati": a folder name cannot contain "/", and --evaluate matches it to "Roti / Chapati".
CLASS_TO_FOOD = {
    "burger": "Burger", "butter_naan": "Naan", "chai": "Masala Chai", "chapati": "Roti - Chapati",
    "chole_bhature": None, "dal_makhani": "Dal Makhani", "dhokla": "Dhokla", "fried_rice": "Veg Fried Rice",
    "idli": "Idli", "jalebi": None, "kaathi_rolls": None, "kadai_paneer": "Kadai Paneer", "kulfi": None,
    "masala_dosa": "Masala Dosa", "momos": "Momos", "paani_puri": None, "pakode": None, "pav_bhaji": None,
    "pizza": "Pizza", "samosa": "Samosa",
}


def fetch(url, tries=6):
    """GET with retries: the free API sometimes answers 502/429 for a moment."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError):
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def fetch_json(url):
    return json.loads(fetch(url))


def save(job):
    index, url, target = job
    if target.exists():
        return
    data = fetch(url)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(data)).convert("RGB").save(target, "JPEG", quality=90)


def main(out=Path("data/indian_food_test")):
    first = fetch_json(ROWS_API.format(offset=0))
    classes = first["features"][1]["type"]["names"]
    total = first["num_rows_total"]
    jobs, counts = [], {}
    for offset in range(0, total, 100):
        page = first if offset == 0 else fetch_json(ROWS_API.format(offset=offset))
        for item in page["rows"]:
            row = item["row"]
            dataset_class = classes[row["label"]]
            folder = CLASS_TO_FOOD[dataset_class] or "unknown_food"
            jobs.append((item["row_idx"], row["image"]["src"],
                         out / folder / f"{dataset_class}_{item['row_idx']:04d}.jpg"))
            counts[folder] = counts.get(folder, 0) + 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(save, jobs))
    for folder, n in sorted(counts.items()):
        print(f"{folder:<16} {n}")
    print(f"total {sum(counts.values())} photos in {out}")


if __name__ == "__main__":
    main()
