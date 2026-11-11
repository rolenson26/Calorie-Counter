# Recognition accuracy (measured 2026-11-12)

All numbers come from `python -m services.food_classifier --evaluate <folder>`, run on this laptop's CPU.
The full outputs, one line per photo, are in the `accuracy_*.txt` files next to this one.

## 1. Public Indian food photos: the README claim, reproduced

- **Dataset:** the test split of [rajistics/indian_food_images](https://huggingface.co/datasets/rajistics/indian_food_images): 941 photos in 20 classes.
- **Download:** `python -m scripts.export_indian_food`.
- **Classes we have:** 13 of the 20 are foods in our database, which gives **658 photos**.
- **Classes we don't have:** the other 7 (jalebi, kulfi, pav bhaji, …) go into `unknown_food`, **283 photos**. For these the app should not be sure of its answer.

| | Text descriptions only | With Manipuri example photos |
|---|---|---|
| Top-1 (658 photos) | **504 = 76.6 %** | 503 = 76.4 % |
| Top-3 (658 photos) | **609 = 92.6 %** | 607 = 92.2 % |
| Unknown foods *not* answered with "high" confidence | 219 of 283 | 218 of 283 |
| When the level is "high", the top food is right | 424 of 460 (92 %) | 423 of 460 (92 %) |
| Average time per photo | 0.16 s | 0.15 s |

This matches the README's "77 % top-1 / 93 % top-3 on 658 photos".

## 2. Manipuri dishes (Ooti, Eromba, Singju)

- **Photos:** 79 unique photos downloaded by the developer, split with a fixed seed (`scripts/prepare_photos.py`):
  - **60 example photos:** Ooti 17, Eromba 19, Singju 24.
  - **20 held-out test photos:** Ooti 6, Eromba 6, Singju 8. These were never used as examples or for tuning.
- **Tuning:** the settings (top 5 examples, threshold 0.80, weight 200) were chosen by `scripts/calibrate_references.py`. It uses only the example photos, each left out of its own test, plus the 941 public photos.

| 20 held-out photos | Text descriptions only | With example photos |
|---|---|---|
| Top-1 | 35 % (7) | **85 % (17)** |
| Top-3 | 55 % (11) | **95 % (19)** |
| Singju | 4 of 8 | 8 of 8 |

What is still wrong:
- Two Ooti photos are ranked Eromba first and Ooti second. Both are mashed, yellow-green dishes in a bowl.
- One Eromba photo is ranked Dal Makhani first.

**Side effect on other foods.** The example photos pull a few non-Manipuri photos towards a Manipuri dish: 8 of 941. For example, a dark dal makhani becomes Eromba, and some salads and fried rice become Singju. Most of these are unknown foods, or ones the app was already unsure about. The net cost is 1 photo in top-1 and 2 in top-3 out of 658.

## 3. A second, varied test set (Wikimedia Commons)

The `Test Samples` folder sits next to the project, outside the repository. It holds 82 freely licensed Commons photos, plus 6 of the developer's held-back Ooti photos. None of them was used to build or tune anything.

| Group | Result |
|---|---|
| Known foods (68 photos, 22 foods) | **63 % top-1 (43), 87 % top-3 (59)** |
| Eromba, new photos | 4 of 4 top-1 |
| Singju, new photos | 2 of 4 top-1, 4 of 4 top-3 |
| Ooti, held back | 4 of 6 top-1, 6 of 6 top-3 |
| Not food (4) | 4 of 4 rejected |
| Foods not in the app (16: jalebi, gulab jamun, pav bhaji, Manipuri thali) | 15 of 16 not answered with "high" |

- **Why it is lower than the 77 % above:** these photos are more varied (restaurant tables, unusual angles).
- **What gets confused:** similar-looking foods (roti and naan, plain and masala dosa, poha and veg pulao).

## Honest limits

- **Small test set.** 20 Manipuri test photos is small: one photo is worth 5 percentage points.
- **Web photos only.** All photos are from the web, often well lit and styled. Real phone photos at a hostel mess could score lower.
- **Relative confidence.** The "confidence" is relative to the 76 known foods. It is not the probability that the answer is correct.
