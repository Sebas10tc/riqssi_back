import unicodedata

from app.database import Base, SessionLocal, engine
from app.models import Usuario, Membresia

EXAMPLE_USERNAME = "demo@gmail.com"
EXAMPLE_PASSWORD = "demo1234"


def _normalize_membership_name(value: str | None) -> str:
    normalized = unicodedata.normalize('NFD', str(value or '').strip().casefold())
    return ''.join(character for character in normalized if unicodedata.category(character) != 'Mn')


def _seed_default_memberships(db) -> None:
    default_memberships = [
        {'nombre': 'Gratis', 'precio': 0, 'nrovideosdiarios': 1, 'duracionvideopermitida': 0},
        {'nombre': 'Básico', 'precio': 19, 'nrovideosdiarios': 5, 'duracionvideopermitida': 7},
        {'nombre': 'Premium', 'precio': 49, 'nrovideosdiarios': 20, 'duracionvideopermitida': 30},
    ]

    existing_memberships = db.query(Membresia.nombre).all()
    existing_names = {_normalize_membership_name(name) for (name,) in existing_memberships}

    for membership in default_memberships:
        if _normalize_membership_name(membership['nombre']) in existing_names:
            continue

        db.add(Membresia(**membership))


def main() -> None:
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _seed_default_memberships(db)

        existing_user = db.query(Usuario).filter(Usuario.nombreuser == EXAMPLE_USERNAME).first()
        if existing_user:
            print(f"El usuario '{EXAMPLE_USERNAME}' ya existe")
            db.commit()
            return

        user = Usuario(nombreuser=EXAMPLE_USERNAME, clave=EXAMPLE_PASSWORD, role='user')
        db.add(user)
        db.commit()
        print(f"Usuario creado: {EXAMPLE_USERNAME} / {EXAMPLE_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
