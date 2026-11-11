# Viva notes: AI Food Calorie Counter

Read this once, then rehearse the demo twice. All numbers here were measured on this laptop on 2026-11-12.

---

## 1. The 30-second pitch

> "You photograph a meal. The AI says which foods are on the plate, including three Manipuri dishes:
> Ooti, Eromba and Singju. It measures each food against the plate to estimate the grams, and it
> calculates calories, protein, carbs, fat and fiber, which go on a daily dashboard.
> It runs fully offline on an ordinary laptop with no GPU, using two pretrained models, CLIP and
> CLIPSeg. Nothing was trained. The user always confirms, because a photo can't tell you everything."

---

## 2. Before the viva (checklist)

```powershell
cd "D:\Brajalen\NIT Manipur\5th Sem\Data Communications\Project\Calorie-Counter"
$env:SECRET_KEY = "any-long-random-text"      # so a restart does not log you out
.venv\Scripts\python app.py                   # wait for "AI model ready" and "Portion model ready" (~20 s)
```

- [ ] Open http://127.0.0.1:5000, create an account, and log one meal, so the dashboard is not empty.
- [ ] Keep these photos ready (all are on this laptop):
  - `static\img\example-thali.jpg`: the thali, for the portion estimate
  - `data\test_photos\Singju\` and `data\test_photos\Eromba\`: Manipuri dishes the AI **never saw** during setup
  - any photo of a person or a room, for the "not food" answer
- [ ] Optional, for the phone demo: connect the phone and the laptop to the same hotspot. Then run `python app.py --host 0.0.0.0` and open `http://<laptop IPv4>:5000` on the phone.
- [ ] No internet is needed. Both models load from `models/`; this was checked with the network blocked.

---

## 3. The 5-minute demo

| # | Do | Say |
|---|---|---|
| 1 | Upload `example-thali.jpg` | "A thali has many dishes. CLIP gives one label for the whole photo, so it is unsure (*low*, 15 %) and shows several likely foods." |
| 2 | Tap **Dal**, then search and add **Steamed Rice**, **Curd** and **Palak Paneer** | "The human stays in the loop: I tap what is really there, or search the 76 foods." |
| 3 | Tap **Estimate portions from photo** | "CLIPSeg finds each food on the plate. The plate is my ruler, a standard 27 cm thali. Rice comes to about 195 g, dal 90 g." |
| 4 | Tap **Show what was measured**, then **Show the photo** | "Each colour is one food. This is where the grams come from." |
| 5 | Change one portion, so the label says *Changed by you*, then **Calculate** and **Save** | "The user can always override. Nutrition is recalculated on the server, so the browser can't be trusted to send numbers." |
| 6 | Upload a Singju or Eromba test photo | "These are Manipuri dishes. CLIP alone got 35 % of them right; with ~20 example photos per dish it gets 85 %. Nothing was trained." |
| 7 | Tap **Estimate portions** on the Eromba bowl | "No plate in view, only a bowl, and bowls come in many sizes. So it does **not** guess: it keeps the standard serving and says why." |
| 8 | Open **Dashboard**, then **History** | "Daily total against the goal, energy split, last 7 days. History shows whether the AI was right, in its top 3, or corrected." |
| 9 | Optional: upload a non-food photo | "The food gate: it says this doesn't look like food." |

---

## 4. How each part works (plain words)

**The pipeline.**
1. Photo
2. Checks: type, size, re-saved as a clean JPEG with GPS removed
3. CLIP: is it food? which food?
4. You choose the foods
5. CLIPSeg: how much of each?
6. Grams × nutrients per 100 g
7. Saved in SQLite
8. Dashboard

**CLIP (recognition, `services/food_classifier.py`).**
- CLIP turns a photo into 512 numbers, and a sentence into 512 numbers. A photo and a sentence about the same thing end up close together; this is *cosine similarity*.
- Each food has 3 sentences, which are averaged into one vector ("prompt ensembling").
- The photo is compared with all 76 food vectors, and a softmax turns the scores into confidences.
- **Zero-shot** means it was never trained on our foods. Adding a food means adding a sentence.

**Food gate.** The photo is also compared with 5 "food" sentences and 7 "not food" sentences (person, room, vehicle…). If the food share is below 50 %, it says "doesn't look like food".

**Confidence levels.**

| Level | Rule | What the page does |
|---|---|---|
| high | ≥ 60 % | pre-selects the food |
| medium | 30–60 % | shows the suggestions |
| low or not food | below 30 %, or fails the gate | asks you to search |

When the level is "high", the top food was right 92 % of the time (424 of 460 public photos).

**Few-shot example photos (Manipuri dishes).**
- **The problem:** CLIP has rarely seen "Eromba", so a sentence is not enough.
- **What we store:** the CLIP vectors of ~20 example photos per dish (`data/reference_embeddings.pt`, 125 KB).
- **How it scores:** a new photo is compared with them. If the average of its 5 most similar examples is above 0.80, the dish gets a bonus of 200 × (similarity − 0.80).
- **Why a threshold:** any two food photos look fairly alike (0.6–0.8). Without the threshold, the Manipuri dishes would steal other foods' answers.
- **Origin:** this is the idea behind *Tip-Adapter* (2022), a training-free few-shot method.
- **How the settings were chosen:** by `scripts/calibrate_references.py`, on the example photos (each left out of its own test) and 941 public photos. The 20 test photos were never used for tuning.

**CLIPSeg (portions, `services/portion_estimator.py`).**
- **What it is:** a second pretrained model built on CLIP. Given a photo and a sentence, it returns a map of *where* that sentence is in the photo.
- **What it is asked:** "a plate", "a bowl", and each food you chose. Each pixel goes to the strongest food.
- **Area:** food pixels ÷ plate pixels × the area of a 27 cm plate (573 cm²).
- **Weight:** grams = area × typical height × density.
  - katori (dal, curd): 3 cm × 1.0 g/cm³. Check: an 8 cm katori is 50 cm² × 3 × 1.0 = 150 g = 1 standard katori.
  - rice heap: 1.8 cm × 0.7
  - bread: 0.4 cm × 0.6
  - salad (Singju): 2.5 cm × 0.35
- **Limits:** the result is kept between ¼ and 3 servings.
- **When it does not guess:** there is no plate, the food is in a bowl, the food fills the dish, or it is a drink.

**Nutrition.**
- Per 100 g values come from INDB (the Indian Nutrient Databank, 2024) and USDA FoodData Central. Each food stores its exact source record.
- calories eaten = calories per 100 g × grams / 100.
- The dashboard's energy split uses 4 kcal per gram of protein and of carbs, and 9 kcal per gram of fat.

**Manipuri nutrition.** No published analysis exists, so the values are **recipe estimates**: a typical recipe by weight, built from USDA ingredient values (`recipe()` in `nutrition_data.py`). Ngari has no USDA record, so dried salted fish was used instead.

| Dish | Recipe used | kcal per 100 g |
|---|---|---|
| Ooti | 70 % boiled dried peas, water, spring onion, 1.5 % mustard oil | 97.5 |
| Eromba | 50 % potato, 25 % beans, 5 % ngari, chilli | 69.8 |
| Singju | cabbage, lotus stem, onion, 10 % roasted gram flour, perilla/sesame | 90.0 |

**Database (SQLite, 4 tables).**
- `users`, `foods`, `predictions` (one per photo) and `food_logs` (one per food eaten).
- Nutrients are **copied** into `food_logs` when a meal is saved. Like a bill keeps the price, history doesn't change if a food's values are edited later.

**Security.**
- Passwords are stored as salted hashes, never in plain text.
- Every SQL query is parameterised, which prevents SQL injection.
- Uploads are re-encoded, size-limited and given random names. A photo is shown only to its owner.
- Text on pages is set with `textContent`, never `innerHTML`, which prevents XSS.
- Nutrition is recalculated on the server, so numbers sent by the browser are never trusted.

---

## 5. Numbers to remember

| | |
|---|---|
| Foods | 76 (73 Indian + 3 Manipuri), in 17 categories |
| Public test photos (658, 13 classes) | **77 % top-1, 93 % top-3**: reproduced, not just quoted |
| Manipuri, 20 held-out photos | **35 % → 85 % top-1**, 55 % → 95 % top-3 with example photos |
| Cost to other foods | 504 → 503 of 658 top-1 |
| Speed | ~0.15 s per photo to recognise; 2–8 s to estimate portions (CPU) |
| Models | CLIP ViT-B/32 and CLIPSeg, ~600 MB each, offline |
| Tests | 214 automated tests (pytest), all passing |
| Sample thali estimate | rice 195 g, dal 90 g, curd 160 g, spinach 110 g |

---

## 6. Likely questions, with answers

**Did you train a model?**
No. Both models are pretrained. CLIP is used *zero-shot*: new foods are added as sentences. For the Manipuri dishes we added example photos, but we only store their vectors and compare against them. That is few-shot without training, as in Tip-Adapter.

**Why not train a CNN, such as ResNet, on Indian food?**
- It would need thousands of labelled photos per class and a GPU.
- Every new food would mean retraining.
- CLIP already reaches 77 % top-1 on 658 public photos with zero training, and we keep a human in the loop for the rest.

**What is the confidence percentage?**
A softmax over our 76 foods, so it is *relative*: "how much more like Idli than like the other 75". It is not the probability of being correct. That is why we also show levels, and the level only pre-selects when it is above 60 %.

**How do you know your accuracy numbers are real?**
- The public test set downloads with one command (`scripts/export_indian_food.py`), and `--evaluate` prints a line for every photo. The outputs are in `docs/accuracy_*.txt`.
- The Manipuri test photos were split off with a fixed random seed before anything was tuned. They were never used as examples.

**Why only 20 Manipuri test photos?**
That's what we could collect in the time; 81 photos were downloaded and 2 duplicates removed. It is small: one photo is 5 percentage points. The result is promising, not proven.

**How does portion estimation work, and how accurate is it?**
The plate is the ruler (see section 4). From one photo, assume roughly ±30–50 %, because the photo can't show depth, the plate's real size, or hidden oil. That is why it only *fills in* the grams, the user can change them, and it refuses to guess when there is no plate.

**Why not estimate portions from bowls?**
A bowl can be 8 cm or 18 cm across, so without a known size in the photo any number would be invented. We would rather say "can't tell".

**What if a food isn't in the database?**
- The AI gives low confidence and the user searches.
- If the food is missing altogether, the user creates it in a pop-up, and it becomes an AI label immediately, without retraining.

**How do you handle a thali with many dishes?**
CLIP gives 3–8 suggestions, the user taps every food present, and all of them are saved together in one transaction. The portion step then locates each chosen food separately.

**Where do the nutrition values come from? Are they exact?**
- INDB 2024 and USDA FoodData Central, with the source record stored for each food.
- They are typical-recipe averages, not exact; oil and ghee vary.
- INDB's deep-fried recipes count all the frying oil as eaten (738 kcal per 100 g for puri), so USDA values were used for fried foods.

**Why SQLite and not MySQL?**
One user per laptop, zero setup, and a single file. The SQL is standard and parameterised, so moving to MySQL or PostgreSQL would be straightforward.

**Does it work without internet?**
Yes. The models load from `models/`, and Bootstrap and Chart.js are stored locally. We tested by blocking the network.

**Can it run on a phone?**
The phone uses it through the browser while the laptop runs the server, over Wi-Fi or a hotspot. A standalone Android app would need the models converted (ONNX or TFLite); that is future work.

**What would you improve next?**
- More example photos and more regional dishes.
- A larger model, such as SigLIP or CLIP ViT-L.
- Depth estimation for portions.
- A reference object (a coin or a card) for bowls.
- A mobile app.
- CSRF tokens on the forms.

**Any security weaknesses?**
No CSRF tokens on the login and register forms; they rely on `SameSite=Lax` cookies. There is no rate limiting. Both are known, and listed as limitations.

---

## 7. Honest limitations (say these before they ask)

1. **Whole-photo recognition.** CLIP ranks the whole photo. It locates foods only in the portion step, for the foods you chose.
2. **Portions are rough.** A single photo, an assumed 27 cm plate, typical heights and densities. No estimate for bowls or close-ups.
3. **Manipuri nutrition values are recipe estimates,** because no lab analysis exists.
4. **Small Manipuri test set:** 20 photos, all from the web.
5. **Relative confidence.** It is not a calibrated probability.
6. **No CSRF tokens or rate limiting.** This is a student demo, not production.
