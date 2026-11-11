# FOUNDATION.md — AI Food Calorie Counter

The single page to read first. It says **what we are building, why, how it works, and what we have decided**.
For the long audit and handover log, see [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). For the short status page, see [PROJECT_STATUS.md](PROJECT_STATUS.md).

Last updated: **2026-11-11** (the viva is on **2026-11-12**).

---

## 1. What and why

**Problem.** Logging calories by hand is slow, and most tools are built for Western food. Indian meals are often several dishes on one plate (a thali), and regional cuisines such as Manipuri food are missing from these tools altogether.

**What the app does.** You photograph a meal, and the AI suggests which foods are on the plate. You confirm them and set each portion. The app then works out calories, protein, carbs, fat and fiber, and records the meal on a daily dashboard.

**Who it is for**
- *Now:* a graded BTech CSE project at NIT Manipur. It must be demo-ready and defensible in the viva.
- *Later:* individuals tracking their food, with Indian food first and Manipuri dishes included. The long-term wish is a standalone app, so the design must not depend on paid APIs.

**Success for the viva**
- The full flow works live on a laptop and on a phone.
- The developer can explain every part.
- Every claim we make is one we can back with evidence.

---

## 2. Principles (do not break these)

1. **The human stays in the loop.** The AI *proposes* and the user *confirms*. Confidence levels decide how much the app trusts the AI.
2. **Offline, with no API keys.** The models run locally on CPU. Bootstrap and Chart.js are stored in `static/vendor/`, not loaded from a CDN. Internet is needed only for installation and the first model download.
3. **No heavy training.** We use zero-shot and few-shot methods only. A new food is added by describing it, or by giving it example photos, never by retraining a network.
4. **Honest numbers.** Nutrition is an *approximate estimate*, every food cites its source, and the confidence shown is *relative*. We never claim exact calories or universal food recognition.
5. **Keep the architecture.**
   - Flask blueprints for the pages and the API.
   - A services layer.
   - SQLite with no ORM, with all SQL in `database/db.py`.
   - Vanilla JavaScript.
   - **Do not rewrite** working, tested modules.

---

## 3. How it works, end to end

```
Photo (upload / camera)
  │  static/js/main.js  — browser shrinks to ≤1280 px, POST /api/predict
  ▼
Validate + clean re-save         services/image_processor.py  process_upload
  │  JPG/PNG/WEBP, ≤8 MB, ≤40 MP, EXIF-rotate, RGB, ≤1024 px, strip EXIF/GPS, random name
  ▼
AI: food gate + ranking          services/food_classifier.py  FoodClassifier.classify
  │  is it food? → which of our foods? → 3–8 suggestions + confidence level
  ▼
Prediction stored                database/db.py  add_prediction   (predictions table)
  ▼
User builds "Your plate"         static/js/main.js  addFood / removeFood / renderPlate
  │  tap suggestions, "+ Add a food" (search), or create a missing food in a pop-up
  ▼
Portion per food                 services/calorie_calculator.py  portion_to_grams
  │  servings (0.25–20) or grams (1–3000)   ← chosen by the user today
  ▼
Preview                          POST /api/calculate
  ▼
Save all foods together          POST /api/food-log/batch → db.add_food_logs (one transaction)
  │  nutrition is recalculated on the server; numbers from the browser are never trusted
  ▼
Dashboard / History              GET /api/dashboard, /api/history  (dashboard.js, history.js)
```

| Layer | Files |
|---|---|
| App start | `app.py`: `create_app()` builds the app, and the CLIP model loads in a background thread. `/api/predict` returns 503 until the model is ready |
| Settings | `config.py`: thresholds, limits, paths, model name |
| Pages and login | `routes/pages.py`, `services/auth.py` |
| JSON API | `routes/api.py` (contract listed in PROJECT_CONTEXT §8) |
| Nutrition maths | `services/calorie_calculator.py` (pure Python) |
| Photo cleanup | `services/cleanup.py`: deletes scanned photos never saved to a meal, after 24 h |
| Front end | `templates/*.html`, `static/js/*.js`, `static/css/style.css` |
| Tests | `tests/`: 183 pytest tests. API tests use a `FakeClassifier` from `conftest.py` |

---

## 4. The AI, in plain words

**Model:** CLIP ViT-B/32 (`openai/clip-vit-base-patch32`), used **zero-shot**: no training and no fine-tuning.

- **Embeddings.** CLIP turns a photo into 512 numbers, and a sentence into 512 numbers. A photo and a sentence about the same thing end up close together.
- **One vector per food.** Each food has 3 sentences: its own `ai_prompt`, "a photo of X, a type of food." and "a close-up photo of X.". Their vectors are averaged into one; this is called *prompt ensembling*. The project's notes say ensembling raised top-1 accuracy from 73 % to 77 %, but this has not been re-measured (see §6).
- **Scoring.** The photo vector is compared with each food vector (cosine similarity × 100), and a softmax turns the scores into confidences that add up to 1.
- **Food gate.** Before ranking, the photo is scored against 5 food sentences and 7 non-food sentences. If the food share is below 0.50, the photo is classed as `not_food`.
- **Confidence levels.**

  | Level | Rule | What the app does |
  |---|---|---|
  | high | top food ≥ 0.60 | pre-selects the top food |
  | medium | 0.30–0.60 | shows the suggestions |
  | low | below 0.30 | asks the user to search |
  | not_food | fails the gate | asks the user to search |

- **Suggestions.** The top 3, plus any other food scoring ≥ 4 %, up to 8 in all (`pick_suggestions`). On a plate with several dishes, their scores are close together, so more of them pass the 4 % mark.
- **Adding foods.** A food created by a user becomes a label immediately (`FoodClassifier.add_food`).

**Few-shot example photos (added 2026-11-12, for Manipuri dishes).** CLIP has rarely seen Ooti, Eromba or Singju, so a sentence alone gets them right only 35 % of the time. For these foods we store the CLIP vectors of ~20 example photos each, in `data/reference_embeddings.pt` (125 KB). It is built by `python -m services.food_classifier --build-references data/reference_photos`.

How a photo is scored (`reference_bonus`):
1. For each food that has example photos, take the average similarity of its **5 most similar** examples.
2. If that is above **0.80**, add **200 × (similarity − 0.80)** to the food's score.

The threshold matters because two food photos are always fairly alike (~0.6–0.8), much more than a photo and a sentence (~0.3). Without it, every food with examples would get a bonus on every photo. Still nothing is trained; the idea comes from Tip-Adapter (Zhang et al., 2022). The settings were chosen with `scripts/calibrate_references.py`, with every example left out of its own test ("leave-one-out"), and are stored in `config.py`.

**Portion estimate from the photo (added 2026-11-12).** `services/portion_estimator.py` uses a second pretrained model, **CLIPSeg** (`CIDAS/clipseg-rd64-refined`, about 600 MB, built on CLIP). It takes a photo and a sentence and returns a 352×352 map of *where* that sentence is.

When the user taps **Estimate portions from photo**:
1. It asks for "a plate", "a bowl", and each chosen food. The food's prompt is its description without "a photo of" and without "in a bowl"; with that phrase, CLIPSeg marked the bowl instead of the rice.
2. Each pixel goes to the strongest food, if that food scores at least 0.4.
3. Area: food pixels ÷ plate pixels × the area of a standard **27 cm plate**.
4. Weight: grams = area × typical height × density, by serving unit. For example, a katori of dal is 3 cm deep at 1.0 g/cm³. Bread is flat and salad is airy.
5. The result is kept between ¼ and 3 servings and rounded to 5 g.

It gives **no estimate**, and keeps the standard serving with a reason shown, when:
- no plate is visible,
- the dish is a bowl (bowls vary in size),
- the food fills the dish (a close-up), or
- a food is not found, or is a drink.

The page fills in the grams, colours each food on the photo, and the user can change any number. On the sample thali this gives rice 195 g, dal 90 g, curd 160 g and spinach 110 g, in 2–8 s on CPU. It is a single-photo estimate: assume roughly ±30–50 %.

**What it can do:** say which of *its known foods* the photo looks most like, and whether the photo is food at all. It takes about 0.04–0.10 s per photo on CPU, after a load of about 6 s.

**What it cannot do (yet):**
- The *classifier* ranks the **whole photo**. Locating each item happens only in the portion step, for the foods the user chose.
- **Portion size** is estimated only when a plate is in view. Even then it is an estimate: it can't see depth or oil.
- It cannot recognise a food that isn't in the list.
- Its confidence is relative to the known foods. It is not a probability of being correct.

---

## 5. Data model

SQLite file `instance/food_calorie.db`, schema in `database/schema.sql`. Foreign keys are switched on for every connection.

| Table | Holds |
|---|---|
| `users` | account, salted password hash, daily calorie goal (800–5000) |
| `foods` | name (UNIQUE), category, default serving, nutrients per 100 g, `ai_prompt`, `is_custom`, `source` |
| `predictions` | one row per scanned photo: image path, is_food, top food, confidence, level, top-3 JSON |
| `food_logs` | one row per food eaten: grams, nutrients, meal type, `was_corrected`, date |

- **Nutrients are copied into `food_logs` when a meal is saved,** so history never changes if a food row is edited later.
- **Starter data** is in `database/nutrition_data.py`: 76 foods in 17 categories, from INDB (Indian Nutrient Databank) and USDA FoodData Central. Every food stores its exact source record.
- **Manipuri dishes are recipe estimates.** No published nutrient analysis of Ooti, Eromba or Singju exists in INDB, IFCT or journals. Their values are calculated by `recipe()` from a typical recipe by weight and USDA ingredient values. Ngari is represented by dried salted fish and perilla seed by sesame, as the nearest matches. The `source` field lists the recipe.

  | Dish | kcal | Protein (g) | Carbs (g) | Fat (g) | Fiber (g) |
  |---|---|---|---|---|---|
  | Ooti | 97.5 | 5.9 | 15.1 | 1.8 | 5.9 |
  | Eromba | 69.8 | 4.7 | 12.8 | 0.3 | 1.9 |
  | Singju | 90.0 | 5.3 | 13.0 | 2.3 | 3.7 |

  Values are per 100 g.
- **Seeding** (changed 2026-11-12): `init_db` adds any starter food that is missing, matched by name, and leaves existing rows alone. So new foods reach an existing database on the next start.

---

## 6. Current state (2026-11-11)

**Works, with automated tests (183 passing):**
- accounts
- upload and validation
- recognition with confidence levels
- correction and search
- custom foods
- multi-food plates with batch save
- nutrition maths
- edit and delete of meals
- history and dashboard data
- photo cleanup
- error pages
- offline model loading

**Multi-food check.** The code at commit `d2049ee` lets the user tap several suggestions, give each its own portion, and save them together. An earlier version allowed only one food per calculation; that is fixed. What remains is that the AI does not *locate* each food on the plate.

**Not yet verified in a real browser:**
- dashboard charts
- history page
- edit and delete modal
- live camera on a phone
- dark mode and mobile layout

The multi-food scan flow *was* checked in headless Edge at phone width.

**Known issues:**

| ID | Issue | Plan |
|---|---|---|
| I3 | ~~The README's 77 % top-1 on 658 photos can't be reproduced~~ **Reproduced 2026-11-12**: `scripts/export_indian_food.py` downloads the public test split (941 photos; the 13 classes we have total exactly 658). Text-only top-1 = 77 %. Outputs are in `docs/accuracy_*.txt` | Done |
| I4 | No CSRF tokens on the login, register and logout forms | Deferred; list as a limitation |
| I7 | Everyone is logged out on restart unless `SECRET_KEY` is set | Documented |
| I17 | ~~In History, the 2nd and later foods of a plate show "Corrected (AI said …)"~~ **Fixed 2026-11-12**: History now says "✓ In the AI's top 3" for those (`in_ai_top3`, worked out from `predictions.top3_json`). `was_corrected` still means "not the AI's first guess", so the accuracy statistics are unchanged | Done |
| — | No rate limiting or security headers | Deferred |
| — | The model folder holds duplicate weight files (≈600 MB wasted) | Optional cleanup |

---

## 7. Decisions log

| Date | Decision | Why |
|---|---|---|
| ≤2026-10-15 | CLIP zero-shot instead of training a classifier | Runs on a laptop CPU; new foods without retraining |
| ≤2026-10-15 | Indian-food focus; nutrition from INDB and USDA with stored sources | The target users; credibility |
| ≤2026-10-15 | INDB deep-fried recipes not used (USDA used for samosa, puri, …) | INDB counts all the frying oil as eaten |
| ≤2026-10-15 | Gulab jamun, jalebi, pakora and bhatura left out | No reliable per-100 g record found |
| ≤2026-10-15 | Human in the loop through confidence levels | The AI is not always right |
| ≤2026-10-15 | Flask + SQLite + vanilla JS; vendor files stored locally | Simple and offline |
| ≤2026-10-15 | Photos re-encoded (EXIF/GPS removed), random names, shown only to their owner | Privacy |
| ≤2026-10-15 | Nutrients copied into `food_logs` at save time | Stable history |
| 2026-10-15 | Multi-food plate: the user selects several foods and saves them in one transaction | Thalis have several dishes |
| 2026-10-15 | No Android APK; demo by hosting on a laptop and connecting phones over Wi-Fi or a hotspot | PyTorch and Flask can't run on Android as they are |
| 2026-10-15 | HLD, report and CSRF deferred | Not needed to run the program |
| **2026-11-11** | **Stay offline with no API keys**, even though a vision LLM would be easier | Lets the project grow into a standalone app |
| **2026-11-11** | **Add Manipuri dishes: Ooti, Eromba, Singju**, recognised by **few-shot reference photos** (10–20 per dish) on top of CLIP, not by training | CLIP has probably never seen these names; example photos teach it without training |
| **2026-11-11** | **Estimate portions from the photo with CLIPSeg, using the plate as a size reference.** The user can still edit the grams | Portion size is the biggest source of calorie error |
| 2026-11-12 | The developer's 81 downloaded photos (2 duplicates removed → 79) are split with a fixed seed: 60 examples, 20 held-out test photos (`scripts/prepare_photos.py`). The photos stay off GitHub; only their vectors are committed | Honest accuracy; web photos are not ours to publish |
| 2026-11-12 | Few-shot settings: top 5 examples, threshold 0.80, weight 200 | Best leave-one-out accuracy that left other foods' accuracy unchanged and pulled ≤1 % of other photos |
| 2026-11-12 | Manipuri nutrition = recipe estimates from USDA ingredients, labelled as such | No published analysis exists |
| 2026-11-12 | Portion estimate only when a plate is the ruler; for bowls and close-ups, keep the standard serving and say why | An honest "can't tell" beats a confident wrong number |
| 2026-11-12 | CLIPSeg loads after CLIP in the same background thread. If it fails, scanning still works and the button is simply not offered | The core flow must never depend on the new feature |
| 2026-11-12 | Work is committed on branch `viva-improvements`, not pushed | Default branch stays as it was until the developer merges |

---

## 8. Roadmap

Today, in this order. Each step gets its own go-ahead.

| Step | What | Key files | Done when |
|---|---|---|---|
| **1. Manipuri dishes** | Nutrition rows for Ooti, Eromba and Singju (published values, or recipe-based estimates labelled honestly). Make `init_db` insert missing starter foods into existing databases. Use reference photos in `data/reference_photos/<Food>/` to boost a food when the photo closely matches them, with a calibrated threshold so other foods aren't stolen | `database/nutrition_data.py`, `database/db.py`, `services/food_classifier.py` | `--evaluate` on held-out photos shows the 3 dishes recognised, and other foods unaffected |
| **2. Portion estimation** | CLIPSeg finds the plate and each selected food. Food area ÷ plate area × a standard plate size gives cm², and × a typical height × density gives grams, clamped to a sensible range. A coloured overlay shows where each food is. New `POST /api/estimate-portions`. An "Estimate portions from photo" button fills the grams, which stay editable | new `services/portion_estimator.py`, `routes/api.py`, `static/js/main.js`, `templates/index.html`, `config.py`, `app.py` | The sample thali gives plausible grams and an overlay; tests pass |
| **3. Full check and fixes** | Headless browser run of the whole app (dashboard, history, edit and delete, dark mode, phone width). Fix the bugs found and I17. Optionally re-measure accuracy on a public dataset | various | Clean run with screenshots |
| **4. Viva notes** | `docs/viva.md`: how each part works, limitations, likely questions with answers, a 5-minute demo script. Update the README and status page | docs | Ready to rehearse |

**Status 2026-11-12:** Steps 1–4 are **done** and committed on branch `viva-improvements`, which is not pushed. 214 tests pass.

**Later ideas (not for the viva):**
- a stronger recognition model, such as SigLIP or CLIP ViT-L/14
- a mobile app through ONNX Runtime or TFLite
- depth-based portion estimates
- CSRF protection and password reset

---

## 9. Commands (Windows PowerShell, project folder)

```powershell
.venv\Scripts\python app.py                                   # http://127.0.0.1:5000
.venv\Scripts\python app.py --host 0.0.0.0                    # phones on the same Wi-Fi/hotspot
.venv\Scripts\python -m pytest                                # all tests
.venv\Scripts\python -m services.food_classifier photo.jpg    # classify one photo
.venv\Scripts\python -m services.food_classifier --evaluate my_photos   # accuracy on folders named after foods
```

Start with an empty database: stop the app, then delete `instance\food_calorie.db` and `instance\uploads\`.

**Environment note (2026-11-12).** A virtual environment is tied to the PC it was made on. The `.venv` here was copied from another laptop, and its `pyvenv.cfg` pointed to a Python that doesn't exist on this PC. It was fixed by installing Python 3.13 with `uv python install 3.13` and pointing `pyvenv.cfg` (`home`, `executable`) to it; the packages built for 3.13 work unchanged. On a new PC, the clean way is a fresh venv plus `pip install -r requirements.txt`. The CLIP weights in `models/` are not in git, and the first run downloads them (~600 MB).
