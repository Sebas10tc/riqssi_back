from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import os
from .database import engine, SessionLocal
from . import models

# Importamos todos los routers que hemos creado
from .api import router_auth, router_video, router_tracks, router_audio_analysis, router_video_analysis, router_link, router_final, router_historial
from .services.membership_reminder_service import run_membership_reminder_loop

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