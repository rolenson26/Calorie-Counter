-- schema.sql - the four tables of the AI Food Calorie Counter.
--
-- "IF NOT EXISTS" makes this file safe to run every time the app starts:
-- existing tables and their data are left untouched.
-- CHECK constraints are a last line of defence. The API validates input
-- first, but the database still refuses impossible values.

-- One row per registered person.
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    email               TEXT    NOT NULL UNIQUE COLLATE NOCASE,   -- NOCASE: Ravi@x.com = ravi@x.com
    password_hash       TEXT    NOT NULL,                          -- never the plain password
    daily_calorie_goal  INTEGER NOT NULL DEFAULT 2000
                        CHECK (daily_calorie_goal BETWEEN 800 AND 5000),
    created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- The nutrition database. Every row is also one label the AI can predict.
CREATE TABLE IF NOT EXISTS foods (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    category           TEXT    NOT NULL,
    serving_unit       TEXT    NOT NULL,                  -- piece, katori, bowl, plate, cup, glass, slice, fruit
    serving_grams      REAL    NOT NULL CHECK (serving_grams > 0),
    calories_per_100g  REAL    NOT NULL CHECK (calories_per_100g BETWEEN 0 AND 900),
    protein_per_100g   REAL    NOT NULL CHECK (protein_per_100g  BETWEEN 0 AND 100),
    carbs_per_100g     REAL    NOT NULL CHECK (carbs_per_100g    BETWEEN 0 AND 100),
    fat_per_100g       REAL    NOT NULL CHECK (fat_per_100g      BETWEEN 0 AND 100),
    fiber_per_100g     REAL    NOT NULL CHECK (fiber_per_100g    BETWEEN 0 AND 100),
    ai_prompt          TEXT    NOT NULL,                  -- sentence the CLIP model compares the photo with
    is_custom          INTEGER NOT NULL DEFAULT 0 CHECK (is_custom IN (0, 1)),
    created_by         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    source             TEXT    NOT NULL DEFAULT 'User'
);

-- What the AI said about each uploaded photo.
CREATE TABLE IF NOT EXISTS predictions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    image_path         TEXT    NOT NULL,                  -- e.g. uploads/3f9c2a7e....jpg
    is_food            INTEGER NOT NULL CHECK (is_food IN (0, 1)),
    predicted_food_id  INTEGER REFERENCES foods(id) ON DELETE SET NULL,
    confidence         REAL    CHECK (confidence BETWEEN 0 AND 1),
    confidence_level   TEXT    NOT NULL CHECK (confidence_level IN ('high', 'medium', 'low', 'not_food')),
    top3_json          TEXT,                              -- the top 3 guesses, stored as JSON text
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- What the user actually ate. Nutrient values are copied in at save time
-- (like a bill keeps the price), so history never changes later.
CREATE TABLE IF NOT EXISTS food_logs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    food_id        INTEGER NOT NULL REFERENCES foods(id),
    prediction_id  INTEGER REFERENCES predictions(id) ON DELETE SET NULL,
    meal_type      TEXT    NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    quantity       REAL    CHECK (quantity IS NULL OR quantity BETWEEN 0.25 AND 20),
    grams          REAL    NOT NULL CHECK (grams > 0 AND grams <= 3000),
    calories       REAL    NOT NULL CHECK (calories >= 0),
    protein        REAL    NOT NULL CHECK (protein  >= 0),
    carbs          REAL    NOT NULL CHECK (carbs    >= 0),
    fat            REAL    NOT NULL CHECK (fat      >= 0),
    fiber          REAL    NOT NULL CHECK (fiber    >= 0),
    was_corrected  INTEGER NOT NULL DEFAULT 0 CHECK (was_corrected IN (0, 1)),
    log_date       TEXT    NOT NULL,                      -- YYYY-MM-DD, for "today" queries
    logged_at      TEXT    NOT NULL                       -- YYYY-MM-DD HH:MM:SS
);

-- The dashboard always asks "this user's meals on this date", so index exactly that.
CREATE INDEX IF NOT EXISTS idx_food_logs_user_date ON food_logs (user_id, log_date);
CREATE INDEX IF NOT EXISTS idx_predictions_user    ON predictions (user_id);
