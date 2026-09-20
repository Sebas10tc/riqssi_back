from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
import asyncio
import os
import unicodedata
from .database import engine, SessionLocal
from . import models

# Importamos todos los routers que hemos creado
from .api import router_auth, router_video, router_tracks, router_audio_analysis, router_video_analysis, router_link, router_final, router_historial
from .services.membership_reminder_service import run_membership_reminder_loop

# 1. Crear las tablas en la base de datos (Postgres)
# Esto lee el archivo models.py y crea lo que falte en tu DB
models.Base.metadata.create_all(bind=engine)


def _normalize_membership_name(value: str | None) -> str:
    normalized = unicodedata.normalize('NFD', str(value or '').strip().casefold())
    return ''.join(character for character in normalized if unicodedata.category(character) != 'Mn')


def _ensure_default_memberships(connection) -> None:
    default_memberships = [
        {'nombre': 'Gratis', 'precio': '0.00', 'nrovideosdiarios': 2, 'duracionvideopermitida': 1},
        {'nombre': 'Básico', 'precio': '10.00', 'nrovideosdiarios': 5, 'duracionvideopermitida': 3},
        {'nombre': 'Premium', 'precio': '25.00', 'nrovideosdiarios': -1, 'duracionvideopermitida': 8},
    ]

    existing_memberships = connection.execute(text('SELECT nombre FROM membresia')).fetchall()
    existing_names = {_normalize_membership_name(row[0]) for row in existing_memberships}

    for membership in default_memberships:
        if _normalize_membership_name(membership['nombre']) in existing_names:
            continue

        connection.execute(
            text(
                """
                INSERT INTO membresia (nombre, precio, nrovideosdiarios, duracionvideopermitida)
                VALUES (:nombre, :precio, :nrovideosdiarios, :duracionvideopermitida)
                """
            ),
            membership,
        )

    connection.execute(
        text(
            """
            UPDATE membresia
            SET precio = CASE
                    WHEN LOWER(nombre) LIKE '%premium%' THEN 25.00
                    WHEN LOWER(nombre) LIKE '%básico%' OR LOWER(nombre) LIKE '%basico%' THEN 10.00
                    ELSE 0.00
                END,
                nrovideosdiarios = CASE
                    WHEN LOWER(nombre) LIKE '%premium%' THEN -1
                    WHEN LOWER(nombre) LIKE '%básico%' OR LOWER(nombre) LIKE '%basico%' THEN 5
                    ELSE 2
                END,
                duracionvideopermitida = CASE
                    WHEN LOWER(nombre) LIKE '%premium%' THEN 8
                    WHEN LOWER(nombre) LIKE '%básico%' OR LOWER(nombre) LIKE '%basico%' THEN 3
                    ELSE 1
                END
            WHERE LOWER(nombre) LIKE '%premium%'
               OR LOWER(nombre) LIKE '%básico%'
               OR LOWER(nombre) LIKE '%basico%'
               OR LOWER(nombre) LIKE '%gratis%'
            """
        )
    )

with engine.begin() as connection:
    inspector = inspect(connection)
    _ensure_default_memberships(connection)

    user_columns = {column["name"] for column in inspector.get_columns("usuario")}
    if "role" not in user_columns:
        connection.execute(text("ALTER TABLE usuario ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"))
        connection.execute(text("UPDATE usuario SET role = 'admin' WHERE correo = 'sebi2004xd@gmail.com'"))

    payment_columns = {
        column["name"] for column in inspector.get_columns("usuario")
    }
    payment_definitions = {
        "membership": "VARCHAR(20) NOT NULL DEFAULT 'free'",
        "membership_request": "VARCHAR(20)",
        "payment_status": "VARCHAR(20) NOT NULL DEFAULT 'approved'",
        "payment_proof_path": "VARCHAR(250)",
        "payment_operation_code": "VARCHAR(80)",
        "payment_submitted_at": "TIMESTAMP",
        "payment_reviewed_at": "TIMESTAMP",
        "membership_expiration": "TIMESTAMP",
        "membership_reminder_sent_at": "TIMESTAMP",
    }
    for column_name, definition in payment_definitions.items():
        if column_name not in payment_columns:
            connection.execute(text(f"ALTER TABLE usuario ADD COLUMN {column_name} {definition}"))

    connection.execute(
        text(
            """
            UPDATE usuario u
            SET membership = CASE
                WHEN LOWER(m.nombre) LIKE '%premium%' THEN 'premium'
                WHEN LOWER(m.nombre) LIKE '%básico%' OR LOWER(m.nombre) LIKE '%basico%' THEN 'basic'
                ELSE 'free'
            END
            FROM membresia_usuario mu
            JOIN membresia m ON m.idmembresia = mu.membresia_idmembresi
            WHERE mu.usuario_nombreuser = u.nombreuser
              AND u.membership = 'free'
              AND mu.idmembresiauser = (
                  SELECT MAX(mu2.idmembresiauser)
                  FROM membresia_usuario mu2
                  WHERE mu2.usuario_nombreuser = u.nombreuser
              )
            """
        )
    )
    connection.execute(
        text(
            """
            UPDATE usuario u
            SET membership = 'free',
                membership_request = CASE
                    WHEN LOWER(m.nombre) LIKE '%premium%' THEN 'premium'
                    ELSE 'basic'
                END
            FROM membresia_usuario mu
            JOIN membresia m ON m.idmembresia = mu.membresia_idmembresi
            WHERE mu.usuario_nombreuser = u.nombreuser
              AND u.payment_status = 'pending'
              AND (LOWER(m.nombre) LIKE '%premium%' OR LOWER(m.nombre) LIKE '%básico%' OR LOWER(m.nombre) LIKE '%basico%')
              AND mu.idmembresiauser = (
                  SELECT MAX(mu2.idmembresiauser)
                  FROM membresia_usuario mu2
                  WHERE mu2.usuario_nombreuser = u.nombreuser
              )
            """
        )
    )

    video_columns = {column["name"] for column in inspector.get_columns("video")}
    if "video_path" not in video_columns:
        connection.execute(text("ALTER TABLE video ADD COLUMN video_path VARCHAR(250)"))

app = FastAPI(
    title="Deepfake Detection System API",
    description="Sistema modular para detección de deepfakes mediante audio y video",
    version="1.0.0"
)

membership_reminder_task = None


@app.on_event('startup')
async def start_membership_reminders():
    global membership_reminder_task
    interval_seconds = int(os.getenv('MEMBERSHIP_REMINDER_INTERVAL_SECONDS', '86400'))
    membership_reminder_task = asyncio.create_task(
        run_membership_reminder_loop(SessionLocal, interval_seconds)
    )


@app.on_event('shutdown')
async def stop_membership_reminders():
    if membership_reminder_task:
        membership_reminder_task.cancel()
        try:
            await membership_reminder_task
        except asyncio.CancelledError:
            pass

# 2. Configurar CORS (Vital para que React pueda conectarse)
allowed_origins = [
    origin.strip().rstrip('/')
    for origin in os.getenv('FRONTEND_URLS', os.getenv('FRONTEND_URL', 'http://localhost:5173')).split(',')
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Registrar las rutas (Incluyendo la de análisis)
# El 'prefix' ayuda a que las URLs sean ordenadas: /video/upload, /tracks/extract, etc.
app.include_router(router_auth.router, tags=["Autenticación"])
app.include_router(router_link.router, prefix="/links", tags=["Gestión de Links"])
app.include_router(router_video.router, prefix="/video", tags=["Gestión de Videos"])
app.include_router(router_tracks.router, prefix="/tracks", tags=["Procesamiento de Pistas"])
app.include_router(router_video_analysis.router, prefix="/video-analysis", tags=["Análisis de IA Video"])
app.include_router(router_audio_analysis.router, prefix="/audio-analysis", tags=["Análisis de IA Audio"])
app.include_router(router_final.router, prefix="/analysis", tags=["Resultado Final"])
app.include_router(router_historial.router, prefix="/historial", tags=["Historial"])

storage_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "storage"))
if os.path.exists(storage_dir):
    app.mount("/storage", StaticFiles(directory=storage_dir), name="storage")


@app.get("/")
async def root():
    return {"message": "API de Detección de Deepfakes operativa"}