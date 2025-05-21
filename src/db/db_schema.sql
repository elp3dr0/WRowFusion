CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL, 
    creation_ts TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    start_time TEXT,
    end_time TEXT,
    workout_type TEXT CHECK (workout_type IN ('distance', 'duration', 'open')),
    completed INTEGER DEFAULT 0,    -- 0 not all intervals were completed, 1 all intervals were completed
    intervals INTEGER,               -- number of intervals in the workout (each interval type counts as 1, regardless if it is a work or rest interval)
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id INTEGER NOT NULL,
    interval_number INTEGER NOT NULL,   -- Intervals should be numbered sequentially from 1 for each workout
    start_time TEXT,
    end_time TEXT,
    interval_type TEXT CHECK (interval_type IN ('work', 'rest')) NOT NULL, 
    completed INTEGER DEFAULT 0,     -- 0 interval was not completed, 1 interval was completed
    FOREIGN KEY(workout_id) REFERENCES workouts(id)
)

CREATE TABLE IF NOT EXISTS interval_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interval_id INTEGER NOT NULL,
    ts TEXT NOT NULL,       -- timestamp in UTC, formatted as an ISO8601 string (YYYY-MM-DD HH:MM:SS)
    stroke_rate REAL,       -- instantaneous number of strokes per min
    stroke_count INTEGER    -- total number of strokes since the start of the interval
    distance INTEGER,       -- total distance in metres since the start of the interval
    pace_500m INTEGER,      -- instantaneous pace measured in seconds to travel 500m
    speed_cmps INTEGER,     -- instantaneous speed in centimetres per second
    total_power INTEGER,    -- total watts since the start of the interval
    total_calories INTEGER,  -- total calories since the start of the interval (calories not kcal)
    heart_rate INTEGER,     -- beats per min
    elapsed_time INTEGER,   -- number of seconds since the interval began
    stroke_ratio REAL,       -- duration of recovery phase / duration of drive phase (note waterrower applies a 1.25 factor to drive phase)
    FOREIGN KEY(interval_id) REFERENCES interval_data(id)
);

CREATE TABLE IF NOT EXISTS rr_intervals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interval_id INTEGER NOT NULL,
    ts INTEGER,                 -- UNIX timestamp for efficiency
    rr_intervals_ms INTEGER,     -- RR interval in milliseconds
    FOREIGN KEY(interval_id) REFERENCES intervals(id)
);

CREATE TABLE IF NOT EXISTS hrv_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interval_id INTEGER NOT NULL,
    time_block INTEGER,         -- timestamp (e.g. seconds or minutes) or block number (e.g. arbitrary fixed length of time) since workout began to condense data and smooth out noise, making trends easier to analyse. 
    nn_std_dev REAL,            -- Standard deviation of normal-to-normal intervals (Measures the overall HRV — how much variability there is in your heartbeats over time.)
    rmsq_sd REAL,               -- Root mean square of successive differences (Reflects the short-term HRV, focusing on beat-to-beat variance).
    pct_over_50ms REAL,            -- % of normal-to-normal intervals > 50ms (Another indicator of short-term HRV)
    FOREIGN KEY(interval_id) REFERENCES intervals(id)
)

INSERT OR IGNORE INTO users (id, username) VALUES (0, 'Guest');