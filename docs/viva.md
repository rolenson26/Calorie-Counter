# Viva notes: AI Food Calorie Counter

Read this once, then rehearse the demo twice. All numbers here were measured on this laptop on 2026-11-12.

---

## 1. The 30-second pitch

> "You photograph a meal. The AI suggests which foods are on the plate, including three Manipuri dishes:
> Ooti, Eromba and Singju. You confirm the foods and the amount, and it calculates calories, protein,
> carbs, fat and fiber, which go on a daily dashboard. It runs fully offline on an ordinary laptop with
> no GPU, using a pretrained model, CLIP. Nothing was trained. The user always confirms, because a photo
> can't tell you everything. We also tried estimating the amount from the photo, measured it, and
> removed it, because a close-up photo has no scale."

---

## 2. Before the viva (checklist)

```powershell
cd "D:\Brajalen\NIT Manipur\5th Sem\Data Communications\Project\Calorie-Counter"
$env:SECRET_KEY = "any-long-random-text"      # so a restart does not log you out
.venv\Scripts\python app.py                   # wait for "AI model ready" (~15 s)
```

- [ ] Open http://127.0.0.1:5000, create an account, and log one meal, so the dashboard is not empty.
- [ ] Keep these photos ready (all are on this laptop):
  - `static\img\example-thali.jpg`: a plate with many dishes
  - `data\test_photos\Ooti\`, `Eromba\` and `Singju\`: Manipuri dishes the AI **never saw** during setup
  - the `Test Samples` folder next to `Samples`: a mix of foods, plus a few non-food photos
- [ ] Optional, for the phone demo: connect the phone and the laptop to the same hotspot. Then run `python app.py --host 0.0.0.0` and open `http://<laptop IPv4>:5000` on the phone.
- [ ] No internet is needed. The model loads from `models/`; this was checked with the network blocked.

---

## 3. The 5-minute demo

| # | Do | Say |
|---|---|---|
| 1 | Upload `example-thali.jpg` | "A thali has many dishes. CLIP gives one label for the whole photo, so it is unsure (*low*, about 15 %) and lists several likely foods." |
| 2 | Select **Sambar** and **Dal**, then search and add **Steamed Rice** | "The human stays in the loop: I select what is really there, or search the 76 foods." |
| 3 | Set the rice to 1½ bowls, then **Calculate** and **Save** | "Portions are chosen in servings or grams. Nutrition is recalculated on the server, so the browser can't be trusted to send numbers." |
| 4 | Upload an Ooti, Eromba or Singju test photo | "These are Manipuri dishes. CLIP alone got 35 % of them right; with ~20 example photos per dish it gets 85 %. Nothing was trained." |
| 5 | Open **Dashboard**, then **History** | "Daily total against the goal, energy split, last 7 days. History shows whether the AI was right, in its top 3, or corrected." |
| 6 | Optional: upload a non-food photo | "The food gate: it says this doesn't look like food." |
| 7 | If asked about portions | "We tried CLIPSeg with the plate as a ruler. On 81 photos it gave an estimate for only 3, so we removed it (`docs/portion_experiment.md`)." |

---

## 4. How each part works (plain words)

**The pipeline.**
1. Photo
2. Checks: type, size, re-saved as a clean JPEG with GPS removed
3. CLIP: is it food? which food?
4. You choose the foods and the portion
5. Grams × nutrients per 100 g
6. Saved in SQLite
7. Dashboard

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

**Portions.**
- The user chooses ½, 1, 1½, 2 or 3 servings, or types the exact grams.
- Each food has a standard serving, for example 1 bowl of dal = 150 g, 1 roti = 40 g, 1 plate of biryani = 250 g.
- The bowl was called a "katori" before; it was renamed because in Manipur people say bowl.

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
| Speed | ~0.15 s per photo on CPU, after ~15 s to load the model |
| Model | CLIP ViT-B/32, ~600 MB, offline |
| Portion experiment | CLIPSeg gave an estimate for **3 of 81** photos, so it was removed |
| Tests | 192 automated tests (pytest), all passing |

---

## 6. Likely questions, with answers

**Did you train a model?**
No. CLIP is pretrained and used *zero-shot*: new foods are added as sentences. For the Manipuri dishes we added example photos, but we only store their vectors and compare against them. That is few-shot without training, as in Tip-Adapter.

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

**Why doesn't the app estimate the portion from the photo?**
- **What we tried:** CLIPSeg finds each food, and the plate (27 cm) is the ruler.
- **The result:** on a full thali it gave sensible numbers, but on 81 real photos it could estimate only 3.
- **Why:** most photos are close-ups of one bowl, and a close-up has no scale. A 10 cm bowl and an 18 cm bowl look the same. CLIPSeg also could not tell a plate from a bowl.
- **Our decision:** we removed it rather than show invented numbers.
- **What would work:** a reference object such as a coin, depth sensors, or a model trained on portion-labelled data (Nutrition5k).

**What if a food isn't in the database?**
- The AI gives low confidence and the user searches.
- If the food is missing altogether, the user adds it in a pop-up, and it becomes an AI label immediately, without retraining.

**How do you handle a thali with many dishes?**
CLIP gives 3–8 suggestions, the user selects every food present, and all of them are saved together in one transaction.

**Where do the nutrition values come from? Are they exact?**
- INDB 2024 and USDA FoodData Central, with the source record stored for each food.
- They are typical-recipe averages, not exact; oil and ghee vary.
- INDB's deep-fried recipes count all the frying oil as eaten (738 kcal per 100 g for puri), so USDA values were used for fried foods.

**Why SQLite and not MySQL?**
One user per laptop, zero setup, and a single file. The SQL is standard and parameterised, so moving to MySQL or PostgreSQL would be straightforward.

**Does it work without internet?**
Yes. The model loads from `models/`, and Bootstrap and Chart.js are stored locally. We tested by blocking the network.

**Can it run on a phone?**
The phone uses it through the browser while the laptop runs the server, over Wi-Fi or a hotspot. A standalone Android app would need the model converted (ONNX or TFLite); that is future work.

**What would you improve next?**
- More example photos and more regional dishes.
- A larger model, such as SigLIP or CLIP ViT-L.
- Portion estimation with a reference object.
- A mobile app.
- CSRF tokens on the forms.

**Any security weaknesses?**
No CSRF tokens on the login and register forms; they rely on `SameSite=Lax` cookies. There is no rate limiting. Both are known, and listed as limitations.

---

## 7. Honest limitations (say these before they ask)

1. **Whole-photo recognition.** CLIP ranks the whole photo; it does not locate each food on the plate.
2. **Portions are chosen by the user.** Estimating them from one photo was tried and did not work (3 of 81).
3. **Manipuri nutrition values are recipe estimates,** because no lab analysis exists.
4. **Small Manipuri test set:** 20 photos, all from the web.
5. **Relative confidence.** It is not a calibrated probability.
6. **No CSRF tokens or rate limiting.** This is a student demo, not production.
