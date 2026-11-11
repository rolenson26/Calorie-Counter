# PROJECT_STATUS.md — AI Food Calorie Counter Using Food Images

Last updated: **2026-11-12**. This is the short status page.
- Vision, principles, how it works and the decisions log: [FOUNDATION.md](FOUNDATION.md), the page to read first.
- Viva preparation: [docs/viva.md](docs/viva.md).
- Accuracy results: [docs/accuracy.md](docs/accuracy.md).
- The older full handover: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md), written 2026-10-15, so parts of it are outdated.

> This file replaces the audit dated 2026-10-10, which had become outdated (146 tests, no photo cleanup, no media queries, no saved meals). Those points have all changed.

---

## Summary

| Item | Status |
|---|---|
| Overall | Core workflow **photo → AI guess → confirm/correct → portion → calories → save → dashboard/history** works end to end |
| Automated tests | **214 passed**, 0 failed, 0 skipped (`python -m pytest`, run 2026-11-12) |
| Manual testing | Done by the developer with real photos; full browser run in headless Edge at 412 px and 1280 px (2026-11-12, see below) |
| Version control | Git repository: https://github.com/rolenson26/Calorie-Counter. The 2026-11-12 work is on branch `viva-improvements`, not pushed |
| Blockers | None |

## What works

| Area | Notes |
|---|---|
| Accounts | Register, login, logout; salted password hashes; each user sees only their own data |
| Photo input | Upload, drag-and-drop, live camera preview (HTTPS/localhost), phone camera app fallback, preview and retake |
| Image checks | JPG/PNG/WEBP only, 8 MB and 40 MP limits, EXIF rotation, resize, metadata (GPS) removed, random file names |
| AI recognition | CLIP ViT-B/32 zero-shot over the **76 foods** in the database; food/not-food gate; high/medium/low confidence levels; top-3 suggestions. **Reproduced: 77 % top-1 / 93 % top-3 on 658 public photos** |
| Manipuri dishes | Ooti, Eromba, Singju, with few-shot example photos: **35 % → 85 % top-1** on 20 held-out photos. Nutrition values are recipe estimates (no published analysis exists) |
| Portion estimate | CLIPSeg finds each chosen food on the plate; the plate (27 cm) is the ruler; grams are filled in and stay editable; no guess for bowls or close-ups |
| Correction | Search all foods, add a custom food (it becomes an AI label straight away) |
| **Multi-food plates** | The AI offers 3–8 likely foods (top 3 + any scoring ≥ 4 %, `config.py`); tap several; **+ Add a food** tile jumps to search; a missing food can be created in a pop-up on the scan page and goes straight on the plate; each food gets its own portion; total + per-food rows; all saved together (`POST /api/food-log/batch`, all-or-nothing) |
| Nutrition | Calories, protein, carbs, fat, fiber from per-100 g values (INDB/USDA) × user-chosen portion |
| Meal log | Save, edit portion/meal type, delete; quick-add recent foods |
| Dashboard / history | Daily totals vs goal, energy split, last 7 days chart, history up to 31 days |
| Other | Dark mode, mobile layout, unused photos deleted after 24 h, works offline once the model is in `models/` |

## Manual test results (developer, 2026-10-15)

- **Single-food photos:** foods from the 73-food list are recognised well, including from different angles. This was informal testing with no counted accuracy figure.
- **Multi-food photos (3–4 foods on one plate):** previously the user could pick only one food per calculation. **Fixed the same day:** the user can now select several foods in one step (see below).

## Browser check of the multi-food flow (2026-10-15)

Headless Edge at phone width (412 px), the real CLIP model, a throwaway database, and the sample thali photo (`static/img/example-thali.jpg`):
tapped 2 suggestions, tapped one off and on again, added a third food by search, set three different portions (quick button, stepper, typed grams), triggered and checked a per-food error message, calculated (860 kcal, 3 rows), went back and forward (plate kept), saved (3 meals, dashboard total 860), used "Add more from this photo" (empty plate), and checked that a single food still shows the old one-food result. No JavaScript errors.

The README's "77 % top-1 / 93 % top-3 on 658 photos" figure **was reproduced on 2026-11-12** (504 and 609 of 658). See [docs/accuracy.md](docs/accuracy.md).

## Browser check of the whole app (2026-11-12)

The real models ran in headless Edge with a throwaway database, at 412 px and 1280 px. **No console errors.** What was checked:
- **Register.**
- **Thali scan, 4 foods.** The portion estimate gave rice 195 g, dal 90 g, curd 160 g and spinach 110 g. The coloured map toggles with the photo, and editing a portion changes the label to "Changed by you".
- **Calculate and save.**
- **Eromba photo.** The AI was highly confident (99 %). The portion step kept the standard serving because the dish is in a bowl.
- **Dashboard** in dark and light mode. The 7-day chart was checked through Chart.js's own data: bars sit on the right days.
- **History.** The three AI labels are correct. Editing a meal works (61 → 122 kcal), and delete asks for confirmation first.
- **Offline.** Both models load with the network blocked.

## Known limitations

| Limitation | Plan |
|---|---|
| The AI ranks the whole photo against the food list; it does not locate separate items. A longer suggestion list also contains some foods that are not on the plate | The user taps only the right ones |
| Portion estimate is from one photo: it assumes a 27 cm plate and typical heights and densities (roughly ±30–50 %); no estimate for bowls or close-ups | The user checks and can change every number |
| Only 20 held-out Manipuri photos, all from the web | Collect more, including real phone photos |
| Only foods in the database can be recognised | Users can add custom foods |
| Nutrition values are typical-recipe estimates | Disclaimer in app and README |
| No CSRF tokens on login/register/logout forms (only `SameSite=Lax` cookies) | Deferred |
| No rate limiting or security headers | Deferred |
| Users are logged out on restart unless `SECRET_KEY` is set | Documented in README |
| Runs as a Flask server; a standalone Android APK is not feasible with PyTorch | Use the laptop/hotspot setup (`python app.py --host 0.0.0.0`) |

## Deferred / optional

- HLD diagrams and project report. These are not needed to run the program. Draft Mermaid diagrams are in `PROJECT_CONTEXT.md` §5 and §7 if they are needed for submission. Viva notes are done: `docs/viva.md`.
- CSRF protection.
- Removing the duplicate model weight file in `models/` (saves about 600 MB).

## Changes on 2026-11-12 (branch `viva-improvements`)

- **Environment:** the copied `.venv` pointed to a Python that doesn't exist on this PC. It was re-pointed to Python 3.13 (installed with uv), and the CLIP model was downloaded into `models/`.
- **Manipuri dishes:**
  - Ooti, Eromba and Singju added, with recipe-estimate nutrition.
  - Few-shot example photos: `reference_bonus`, `data/reference_embeddings.pt`.
  - Scripts to prepare the photos and calibrate the settings.
  - `init_db` now adds new starter foods to an existing database.
- **Portion estimate from the photo:** `services/portion_estimator.py`, `POST /api/estimate-portions`, and the scan-page button, coloured map and labels.
- **History:** foods in the AI's top 3 show "✓ In the AI's top 3" instead of "Corrected" (fixes I17).
- **Accuracy reproduced** on the public test set (`scripts/export_indian_food.py`, `docs/accuracy.md`).
- **New docs:** `FOUNDATION.md` and `docs/viva.md`.
- **Tests:** 183 → 214.

## Changes on 2026-10-15

- Fixed two corrupted lines in the README's phone-camera section and corrected the test count (164 → 165).
- Replaced this outdated status file.
- Added `PROJECT_CONTEXT.md`.
- Put the project under git and pushed it to GitHub.
- **Multi-food in one step:** "Your plate" on the scan page (`templates/index.html`, `static/js/main.js`, `static/css/style.css`), new `POST /api/food-log/batch` (`routes/api.py`) and `db.add_food_logs` (one transaction), 15 new tests (165 → 180).
- **More suggestions and quick add:** `pick_suggestions` in `services/food_classifier.py` (3–8 foods, settings `SUGGESTION_MIN_CONFIDENCE`, `MAX_SUGGESTIONS`); "+ Add a food" tile; "Create … as a new food" in search results with a pop-up (`templates/_new_food_modal.html`); removed the "AI's top guess / AI suggestion" labels from the result rows. 3 new tests (180 → 183). Browser-checked: the sample thali now offers 6 foods (Dal, which is on the plate, was 6th), a food created in the pop-up lands on the plate and becomes an AI label.

## Commands

```powershell
.venv\Scripts\python app.py                   # http://127.0.0.1:5000
.venv\Scripts\python app.py --host 0.0.0.0    # reachable from phones on the same Wi-Fi
.venv\Scripts\python -m pytest                # 214 tests
```
