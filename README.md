# AI Food Calorie Counter

Take or upload a photo of a meal. The app suggests what the food is, you confirm it and choose
the portion, and it estimates the calories, protein, carbohydrates, fat and fiber. It then adds the
meal to a daily dashboard. The app is built for Indian food and runs on an ordinary laptop with no GPU.

> **Academic demonstration.** Calorie and nutrient values are approximate estimates for typical
> recipes and portions. They are not medical or dietary advice.

- **AI:** pretrained CLIP ViT-B/32 (zero-shot) recognises 73 foods, and any food you add becomes a new label without retraining.
  On 658 labelled test photos its first suggestion was right 77% of the time, and the right food was in its top 3 for 93%.
- **Confidence levels:** a high-confidence answer is pre-selected. Medium shows the top 3, and low or "not food" asks you to search.
- **Whole plates:** the AI offers 3 to 8 likely foods (more when a plate has several dishes). Tap every food you can see; **+ Add a food** searches for anything it missed, and a food that is not in the database can be created right there. Each food gets its own portion, and they are calculated and saved together as one meal.
- **Phone friendly:** live camera preview (where the browser allows it) with a fallback to the phone's camera app, photo preview with retake, light/dark mode, and cards instead of wide tables on small screens.
- **Meal log:** edit or delete a saved meal, quick-add your recent foods, and old photos that were never saved to a meal are deleted after 24 hours.
- **Portions:** pieces, katori, plate, bowl, cup or exact grams. Grams are never guessed from the photo.
- **Nutrition data:** per 100 g, from the Indian Nutrient Databank (INDB) and USDA FoodData Central, with the source of every food stored.
- **Built with:** Python, Flask, SQLite, HTML/CSS/JavaScript, Bootstrap and Chart.js. It works offline after the first model download.

Design and report: [Architecture & HLD](https://claude.ai/code/artifact/8e9e04f9-55a2-4157-8472-7a6e9f03e6b9) ·
[Project report](https://claude.ai/code/artifact/b5350d5b-3e1e-4d6e-9e4c-bbff821bcce5)

---

## 1. What you need

| | |
|---|---|
| Python | 3.11 or newer (developed and tested with 3.13) |
| Disk space | About 3 GB: AI model 1.2 GB, Python libraries 0.9 GB |
| Memory | 8 GB RAM recommended (the model uses about 1–1.5 GB) |
| Internet | Only for installation and the first start (model download) |
| GPU | Not needed |

## 2. Install (once)

Open PowerShell in the `food-calorie-counter` folder:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # Linux only: avoids a 2 GB GPU build
pip install -r requirements.txt
```

If PowerShell says *running scripts is disabled*, skip `activate` and use the full path instead,
for example `.venv\Scripts\python app.py`, or run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

## 3. Run

```powershell
python app.py
```

Open **http://127.0.0.1:5000** and create an account.

- **The first start downloads the CLIP model (about 1.2 GB) into `models/`.** The website opens
  immediately and shows "The AI model is loading" until the download finishes. Later starts load
  the saved copy in about 5 seconds and need no internet.
- The database `instance/food_calorie.db` is created automatically with 73 foods.

### Use it from your phone (camera)

The live camera preview needs a secure page (HTTPS or `localhost`). Over plain `http://192.168...` the
phone's browser blocks it, so **Take Photo** opens the phone's own camera app instead. Both work.

1. Connect the phone and the laptop to the same Wi-Fi.
2. Start the app with `python app.py --host 0.0.0.0`.
3. Find the laptop's address with `ipconfig` (the IPv4 address, for example `192.168.1.5`).
4. On the phone, open `http://<laptop-address>:5000`, for example `http://192.168.1.5:5000`. **Take Photo** then opens the rear camera.

Windows may ask whether Python can use the network; allow it for private networks.

## 4. How to use

1. **Scan food:** take or upload a photo of a dish or a whole plate (or choose *No photo? Search a food instead*).
2. **Check:** the AI shows its confidence and its likely foods (3 to 8). Tap every food that is on the plate
   (tap again to remove it). For anything missing, tap **+ Add a food** and search; if it is not in the
   database at all, choose **Create "…" as a new food** and enter its values in the pop-up. Each food appears under
   **Your plate** with its own portion. Choose the meal, then press **Calculate Calories**.
3. **Save:** the result shows the total calories, protein, carbs, fat and fiber, plus one row per food.
   **Save** stores all of them together. **Add more from this photo** adds further items later.
4. **Dashboard** shows today's total, what is left of your goal, where the calories come from,
   and the last 7 days. **History** lists past meals and whether the AI was right.
   **Foods** lists every food and lets you add one that is missing.

## 5. Test

```powershell
python -m pytest            # 183 tests, about 20-90 seconds; no GPU needed
```

Check the AI's accuracy on your own photos. Put them in folders named after foods in the
database, then run:

```
my_photos/
├── Idli/           *.jpg
├── Samosa/         *.jpg
├── Roti - Chapati/ *.jpg     (use "-" instead of "/" in folder names)
└── not_food/       *.jpg     (optional: photos that are not food)
```

```powershell
python -m services.food_classifier --evaluate my_photos
python -m services.food_classifier my_photo.jpg      # classify a single photo
```

## 6. Project structure

```
app.py                  builds the Flask app, loads the model in the background
config.py               every setting: upload limit, AI thresholds, paths
routes/pages.py         HTML pages, login/register/logout, private photo route
routes/api.py           JSON API (/api/predict, /api/calculate, /api/food-log, /api/food-log/batch, ...)
services/auth.py        password hashing, login_required
services/image_processor.py   validate, rotate, resize, strip EXIF, save
services/food_classifier.py   CLIP zero-shot recognition and the --evaluate command
services/calorie_calculator.py  portion -> grams -> calories and nutrients
database/schema.sql     the four tables
database/db.py          every SQL query
database/nutrition_data.py   73 foods with per-100 g values and sources
templates/, static/     pages, CSS, JavaScript, Bootstrap and Chart.js (stored locally)
tests/                  183 automated tests
instance/               the database and uploaded photos (created at run time, never public)
models/                 the downloaded CLIP model
```

## 7. Settings

All settings are in `config.py`. Common changes:

| Setting | Default | Meaning |
|---|---|---|
| `HIGH_CONFIDENCE` | 0.60 | At or above this, the top food is pre-selected |
| `LOW_CONFIDENCE` | 0.30 | Below this, the user is asked to search |
| `FOOD_GATE_THRESHOLD` | 0.50 | Below this, the photo "doesn't look like food" |
| `SUGGESTION_MIN_CONFIDENCE` | 0.04 | Besides the top 3, foods scoring at least this are also offered |
| `MAX_SUGGESTIONS` | 8 | Most foods offered after a scan |
| `MAX_CONTENT_LENGTH` | 8 MB | Largest upload |
| `DEFAULT_CALORIE_GOAL` | 2000 | New users' daily goal (each user can change it) |

Set the `SECRET_KEY` environment variable to keep users logged in across restarts. Without it, a new
random key is made at every start.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "The AI model is loading" never ends | The first start downloads 1.2 GB; watch the terminal. Without internet on the first start, the page shows an error. Connect and restart. |
| "Cannot reach the server" | The terminal running `python app.py` was closed. Start it again. |
| iPhone photo rejected on a laptop | HEIC photos are not supported. Export the photo as JPG, or upload it from the iPhone itself (Safari converts it). |
| Phone cannot open the app | Use `--host 0.0.0.0`, the same Wi-Fi, the laptop's IPv4 address, and allow Python through Windows Firewall. |
| Port 5000 is busy | `python app.py --port 5050` |
| Start again with an empty database | Stop the app and delete `instance/food_calorie.db` (and `instance/uploads/`). The database is recreated on the next start. |

## 9. Data sources and credits

- CLIP: Radford et al., *Learning Transferable Visual Models From Natural Language Supervision*, 2021
  ([openai/clip-vit-base-patch32](https://huggingface.co/openai/clip-vit-base-patch32)).
- Indian Nutrient Databank: Vijayakumar A., Dubasi H.B., Awasthi A., Jaacks L.M., *Development of an
  Indian Food Composition Database*, Current Developments in Nutrition, 2024
  ([data](https://github.com/lindsayjaacks/Indian-Nutrient-Databank-INDB-)).
- USDA FoodData Central: FNDDS and SR Legacy ([downloads](https://fdc.nal.usda.gov/download-datasets)).
- Accuracy test photos: [Indian Food Images dataset](https://huggingface.co/datasets/rajistics/indian_food_images) (not included in this project).
- Bootstrap 5.3.8 and Chart.js 4.5.1, both MIT licensed (in `static/vendor/`).
