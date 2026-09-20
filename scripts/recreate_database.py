"""Elimina y recrea todas las tablas de la base de datos RIQSSI.

Uso desde RIQSSI_BACK:
    python scripts/recreate_database.py
    python scripts/recreate_database.py --yes
"""

import argparse
from pathlib import Path
import sys
from decimal import Decimal

# Permite ejecutar el archivo directamente con `python scripts/recreate_database.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine
from app.models import Membresia


DEFAULT_MEMBERSHIPS = (
    {
        "nombre": "Gratis",
        "precio": Decimal("0.00"),
        "nrovideosdiarios": 1,
        "duracionvideopermitida": 0,
    },
    {
        "nombre": "Básico",
        "precio": Decimal("19.00"),
        "nrovideosdiarios": 5,
        "duracionvideopermitida": 7,
    },
    {
        "nombre": "Premium",
        "precio": Decimal("49.00"),
        "nrovideosdiarios": 20,
        "duracionvideopermitida": 30,
    },
)


def recreate_database(seed_memberships: bool = True) -> None:
    print("Eliminando las tablas existentes...")
    Base.metadata.drop_all(bind=engine)

    print("Creando todas las tablas...")
    Base.metadata.create_all(bind=engine)

    if not seed_memberships:
        return

    db = SessionLocal()
    try:
        db.add_all(Membresia(**membership) for membership in DEFAULT_MEMBERSHIPS)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Elimina y recrea el esquema completo de RIQSSI."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="confirma la operación destructiva sin preguntar",
    )
    args = parser.parse_args()

    if not args.yes:
        print("ADVERTENCIA: se eliminarán todos los datos de la base de datos.")
        confirmation = input("Escribe 'RECREAR' para continuar: ").strip()
        if confirmation != "RECREAR":
            print("Operación cancelada.")
            return

    try:
        recreate_database()
    except Exception as error:
        print(f"No se pudo recrear la base de datos: {error}", file=sys.stderr)
        sys.exit(1)

    print("Base de datos recreada correctamente.")
    print("Planes de membresía creados: Gratis, Básico y Premium.")


if __name__ == "__main__":
    main()
