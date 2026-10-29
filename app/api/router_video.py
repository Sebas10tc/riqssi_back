from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Form
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Usuario, Video
from ..services.video_service import save_local_video
import datetime

router = APIRouter()

@router.post("/upload")
async def upload_video(
    file: UploadFile = File(...),
    nombreuser: str = Form(...), # Recibido como campo de formulario
    db: Session = Depends(get_db)
):
    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    plan = user.membership or "free"
    if (user.role or "").lower() == "admin":
        plan = "premium"
    elif user.payment_status in {"canceled", "expired", "denied"}:
        plan = "free"
    elif user.membership_expiration and user.membership_expiration.date() < datetime.datetime.utcnow().date():
        plan = "free"

    plan_limits = {
        "free": (3, "Gratis"),
        "gratis": (3, "Gratis"),
        "basic": (4, "Básico"),
        "basico": (4, "Básico"),
        "básico": (4, "Básico"),
        "premium": (5, "Premium"),
    }
    limit_mb, plan_name = plan_limits.get(plan.strip().casefold(), plan_limits["free"])

    # 1. Procesar y guardar el archivo físicamente
    video_info = await save_local_video(file, limit_mb * 1024 * 1024, plan_name)

    # 2. Verificar si el video ya existe por hash
    existing = db.query(Video).filter(Video.hash_video == video_info['hash']).first()
    if existing:
        return {
            "status": "exists",
            "message": "El video ya ha sido cargado previamente",
            "video": {
                "hash_video": existing.hash_video,
                "nombrevideo": existing.nombrevideo,
                "red_social": existing.red_social,
                "duracion": existing.duracion,
                "resolucion": existing.resolucion,
                "thumbnail_path": existing.thumbnail_path,
                "video_path": existing.video_path,
            },
        }

    # 3. Registrar en la base de datos
    nuevo_video = Video(
        hash_video=video_info['hash'],
        nombrevideo=video_info['filename'][:120],
        red_social="Local Upload",
        fechasubida=datetime.datetime.now(),
        resolucion=video_info['resolution'],
        duracion=video_info['duration'],
        thumbnail_path=video_info['thumb_path'],
        video_path=video_info['path'],
        usuario_nombreuser=nombreuser
    )

    db.add(nuevo_video)
    db.commit()
    db.refresh(nuevo_video)

    return {
        "status": "success",
        "video": {
            "hash_video": nuevo_video.hash_video,
            "nombrevideo": nuevo_video.nombrevideo,
            "red_social": nuevo_video.red_social,
            "duracion": nuevo_video.duracion,
            "resolucion": nuevo_video.resolucion,
            "thumbnail_path": nuevo_video.thumbnail_path,
            "video_path": nuevo_video.video_path,
        }
    }