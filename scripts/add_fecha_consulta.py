import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.database import engine
from sqlalchemy import text

sql_add = """
ALTER TABLE historial
ADD COLUMN IF NOT EXISTS fecha_consulta TIMESTAMP WITH TIME ZONE DEFAULT now();
"""

sql_update = """
UPDATE historial SET fecha_consulta = now() WHERE fecha_consulta IS NULL;
"""

with engine.connect() as conn:
    conn.execute(text(sql_add))
    conn.execute(text(sql_update))
    conn.commit()

print('Migration applied: fecha_consulta added and populated.')
