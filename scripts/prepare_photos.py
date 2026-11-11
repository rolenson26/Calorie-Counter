"""
scripts/prepare_photos.py - turn a folder of downloaded dish photos into
reference photos (the AI learns from these) and test photos (used only to
measure accuracy), without ever changing the original files.

    python -m scripts.prepare_photos "D:/path/to/Samples"

Input : Samples/<Food Name>/*.jpg|jpeg|png|webp|avif   (folder name = food name in the database)
Output: data/reference_photos/<Food Name>/NN.jpg     about 75 % of each food's photos
        data/test_photos/<Food Name>/NN.jpg          about 25 %, never used as references

Steps for every photo
    1. Skip exact duplicates (same file bytes, even under another name). A duplicate in
       both groups would make the measured accuracy look better than it really is.
    2. Open with Pillow, apply the EXIF rotation, convert to RGB, shrink the longest side to
       512 px and save as JPEG. CLIP only sees 224 x 224, so nothing useful is lost.
    3. Split with a fixed random seed, so running the script again gives the same split.
"""
import argparse
import hashlib
import random
import shutil
from pathlib import Path

from PIL import Image, ImageOps

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
MAX_SIDE = 512


def unique_photos(folder):
    """The photo files of one food folder, without exact duplicates, in a stable order."""
    seen, photos, duplicates = set(), [], []
    for path in sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTENSIONS):
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        if digest in seen:
            duplicates.append(path.name)
            continue
        seen.add(digest)
        photos.append(path)
    return photos, duplicates


def save_clean_copy(source, target):
    """Open, rotate, convert to RGB, shrink, save as JPEG. Returns False if Pillow cannot read it."""
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(target, "JPEG", quality=90)
        return True
    except Exception as exc:                       # a broken download should not stop the run
        print(f"  could not read {source.name}: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Copy dish photos into reference and test sets.")
    parser.add_argument("source", type=Path, help="folder with one sub-folder per food")
    parser.add_argument("--out", type=Path, default=Path("data"), help="output folder (default: data)")
    parser.add_argument("--test-share", type=float, default=0.25, help="share of photos kept for testing")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    for group in ("reference_photos", "test_photos"):
        shutil.rmtree(args.out / group, ignore_errors=True)    # rebuilt from scratch each time

    for food_dir in sorted(p for p in args.source.iterdir() if p.is_dir()):
        photos, duplicates = unique_photos(food_dir)
        random.Random(args.seed).shuffle(photos)
        n_test = max(1, round(len(photos) * args.test_share))
        groups = {"test_photos": photos[:n_test], "reference_photos": photos[n_test:]}
        counts = {}
        for group, members in groups.items():
            saved = 0
            for path in members:
                saved += save_clean_copy(path, args.out / group / food_dir.name / f"{saved + 1:02d}.jpg")
            counts[group] = saved
        print(f"{food_dir.name:<10} reference {counts['reference_photos']:>2}, test {counts['test_photos']:>2}"
              + (f", duplicates skipped: {', '.join(duplicates)}" if duplicates else ""))


if __name__ == "__main__":
    main()
