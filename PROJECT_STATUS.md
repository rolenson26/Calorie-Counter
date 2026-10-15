# PROJECT_STATUS.md — AI Food Calorie Counter Using Food Images

Last updated: **2026-10-15**. This is the short status page. The full handover (architecture, API, database, roadmap, instructions for another assistant) is in [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).

> This file replaces the audit dated 2026-10-10, which had become outdated (146 tests, no photo cleanup, no media queries, no saved meals). Those points have all changed.

---

## Summary

| Item | Status |
|---|---|
| Overall | Core workflow **photo → AI guess → confirm/correct → portion → calories → save → dashboard/history** works end to end |
| Automated tests | **165 passed**, 0 failed, 0 skipped (`python -m pytest`, run 2026-10-15) |
| Manual testing | Done by the developer with real photos (see below) |
| Version control | Git repository: https://github.com/rolenson26/Calorie-Counter |
| Blockers | None |

## What works

| Area | Notes |
|---|---|
| Accounts | Register, login, logout; salted password hashes; each user sees only their own data |
| Photo input | Upload, drag-and-drop, live camera preview (HTTPS/localhost), phone camera app fallback, preview and retake |
| Image checks | JPG/PNG/WEBP only, 8 MB and 40 MP limits, EXIF rotation, resize, metadata (GPS) removed, random file names |
| AI recognition | CLIP ViT-B/32 zero-shot over the **73 foods** in the database; food/not-food gate; high/medium/low confidence levels; top-3 suggestions |
| Correction | Search all foods, add a custom food (it becomes an AI label straight away) |
| Nutrition | Calories, protein, carbs, fat, fiber from per-100 g values (INDB/USDA) × user-chosen portion |
| Meal log | Save, edit portion/meal type, delete; quick-add recent foods |
| Dashboard / history | Daily totals vs goal, energy split, last 7 days chart, history up to 31 days |
| Other | Dark mode, mobile layout, unused photos deleted after 24 h, works offline once the model is in `models/` |

## Manual test results (developer, 2026-10-15)

- **Single-food photos:** foods from the 73-food list are recognised well, including from different angles. This was informal testing with no counted accuracy figure.
- **Multi-food photos (3–4 foods on one plate):** the AI shows the foods it sees among its top-3 suggestions, but the user picks **one** for the calculation. To log the other items, save the first, then press **Add another item from this photo**. This is a known limitation, recorded as future work.

The README's "77 % top-1 / 93 % top-3 on 658 photos" figure cannot be reproduced from the repository, because the test photos are not included.

## Known limitations

| Limitation | Plan |
|---|---|
| One food label per photo (no multi-food detection) | Future work |
| Portion size is chosen by the user, not estimated from the photo | By design |
| Only foods in the database can be recognised | Users can add custom foods |
| Nutrition values are typical-recipe estimates | Disclaimer in app and README |
| No CSRF tokens on login/register/logout forms (only `SameSite=Lax` cookies) | Deferred |
| No rate limiting or security headers | Deferred |
| Users are logged out on restart unless `SECRET_KEY` is set | Documented in README |
| Runs as a Flask server; a standalone Android APK is not feasible with PyTorch | Use the laptop/hotspot setup (`python app.py --host 0.0.0.0`) |

## Deferred / optional

- HLD diagrams, project report, viva notes. These are not needed to run the program. Draft Mermaid diagrams are in `PROJECT_CONTEXT.md` §5 and §7 if they are needed for submission.
- CSRF protection.
- Multi-food detection.
- Removing the duplicate model weight file in `models/` (saves about 600 MB).

## Changes on 2026-10-15

- Fixed two corrupted lines in the README's phone-camera section and corrected the test count (164 → 165).
- Replaced this outdated status file.
- Added `PROJECT_CONTEXT.md`.
- Put the project under git and pushed it to GitHub.

## Commands

```powershell
.venv\Scripts\python app.py                   # http://127.0.0.1:5000
.venv\Scripts\python app.py --host 0.0.0.0    # reachable from phones on the same Wi-Fi
.venv\Scripts\python -m pytest                # 165 tests
```
