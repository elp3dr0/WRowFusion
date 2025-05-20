import logging
import sqlite3
import os

logger = logging.getLogger(__name__)

SCHEMA_PATH = "/opt/wrowfusion/src/db/db_schema.sql"
DB_PATH = "/opt/wrowfusion/workouts.db"

def load_schema() -> str:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return f.read()
    
def initialise_database():
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
        print(f"Database already exists at {DB_PATH}, skipping initialisation.")
        return
    print(f"Initialising WRowFusion database at {DB_PATH}")
    schema_sql = load_schema()
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema_sql)
    print(f"Database initialised")

if __name__ == "__main__":
    initialise_database()