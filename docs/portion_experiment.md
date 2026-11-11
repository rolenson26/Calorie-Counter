# Experiment: estimating portion size from the photo (tried and removed, 2026-11-12)

## What was tried

The goal was to estimate how many grams of each food are in the photo, so the user would not have to choose the portion.

- **Model:** CLIPSeg (`CIDAS/clipseg-rd64-refined`, Lüddecke and Ecker, CVPR 2022). It is a pretrained model built on CLIP. Given a photo and a sentence, it returns a map of *where* that sentence is in the photo.
- **Method:** the plate is the ruler.
  1. Ask CLIPSeg for "a plate", "a bowl", and each food the user chose.
  2. Food area = food pixels ÷ plate pixels × the area of a standard 27 cm plate.
  3. grams = area × a typical height × density.
- **When it gave no estimate:** when no plate was in view, when the food was in a bowl (bowls vary in size), or when the food filled the dish (a close-up).
- **Where the code is:** commit `d9b31e4` on branch `viva-improvements` (`services/portion_estimator.py`).

## What happened

On the sample thali photo (`static/img/example-thali.jpg`) the results were plausible: rice 195 g, dal 90 g, curd 160 g, spinach 110 g.

On the developer's 81 downloaded photos of Ooti, Eromba and Singju:

| Result | Photos |
|---|---|
| An estimate was made | **3** (one of them hit the 3-serving maximum, so it was probably wrong) |
| "The food is in a bowl", so no estimate | 68 |
| "The food fills the dish", so no estimate | 9 |
| "No plate visible", so no estimate | 2 |

Two reasons:

1. **A close-up photo has no scale.** Nothing in it says whether the bowl is 10 cm or 18 cm across, so any number of grams would be invented. Most real food photos, and most of these, are close-ups of one dish.
2. **CLIPSeg could not tell a plate from a bowl,** and often could not find the food itself.
   - Its "plate" and "bowl" maps covered almost the same area. For example: 0.89 and 0.88, 0.95 and 0.98.
   - For most Eromba photos it found the food on only 0–8 % of the dish, because it does not know the dish.

## Decision

**Removed.** The feature worked only for photos of a full plate, which were 3 of the 81 test photos. It also cost a second 600 MB model and about 5 seconds of extra start-up. Portions stay a user choice: the quick buttons ½ / 1 / 1½ / 2 / 3 servings, or the exact grams.

## What could work instead (future work)

- **A reference object of known size in every photo,** such as a coin or a card, detected automatically.
- **Depth sensors on phones,** such as LiDAR or dual cameras, to measure volume.
- **Two photos from different angles,** to estimate height.
- **Train a model on a portion-labelled dataset** (for example Nutrition5k, 2021). That needs training and a GPU.
