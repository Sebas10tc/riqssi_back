"""Inserta las membresías por defecto si no existen (no borra ni duplica datos).

Uso desde RIQSSI_BACK (usa el DATABASE_URL activo en el entorno, ej. en Render Shell):
    python scripts/seed_memberships.py
"""

from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import Membresia

DEFAULT_MEMBERSHIPS = (
    {
        "nombre": "Gratis",
        "precio": Decimal("0.00"),
        "nrovideosdiarios": 2,
        "plan_limit": 2,
        "duracionvideopermitida": 1,
    },
    {
        "nombre": "Básico",
        "precio": Decimal("10.00"),
        "nrovideosdiarios": 5,
        "plan_limit": 5,
        "duracionvideopermitida": 3,
    },
    {
        "nombre": "Premium",
        "precio": Decimal("25.00"),
        "nrovideosdiarios": -1,
        "plan_limit": -1,
        "duracionvideopermitida": 8,
    },
)


def seed_memberships() -> None:
    db = SessionLocal()
    try:
        existing_names = {row.nombre for row in db.query(Membresia.nombre).all()}
        created = 0
        for membership in DEFAULT_MEMBERSHIPS:
            if membership["nombre"] in existing_names:
                print(f"Ya existe: {membership['nombre']} (se omite)")
                continue
            db.add(Membresia(**membership))
            created += 1
            print(f"Insertada: {membership['nombre']}")
        db.commit()
        print(f"Listo. Membresías creadas: {created}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_memberships()
