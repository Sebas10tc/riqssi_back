import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import engine
from sqlalchemy import text


with engine.connect() as conn:
    conn.execute(text(
        "ALTER TABLE usuario "
        "ADD COLUMN IF NOT EXISTS videos_analyzed_count INTEGER NOT NULL DEFAULT 0"
    ))
    conn.execute(text(
        "ALTER TABLE membresia "
        "ADD COLUMN IF NOT EXISTS plan_limit INTEGER"
    ))
    conn.execute(text(
        "UPDATE membresia "
        "SET plan_limit = nrovideosdiarios "
        "WHERE plan_limit IS NULL"
    ))
    conn.commit()

print('Migration applied: persistent video counters and plan limits added.')
