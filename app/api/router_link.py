from fastapi import APIRouter, Depends, Body
from sqlalchemy.orm import Session
from pathlib import Path
import logging
import cv2
from urllib.parse import quote
from ..database import get_db
from ..models import Video
from ..services.link_service import process_video_download
from .router_auth import require_active_membership

logger = logging.getLogger(__name__)

router = APIRouter()


def _storage_file_exists(path_value: str | None):
    if not path_value:
        return False

    normalized_path = path_value.replace("\\", "/")
    if normalized_path.startswith("http://") or normalized_path.startswith("https://"):
        return True

    project_root = Path(__file__).resolve().parents[2]

    if normalized_path.lower().startswith("storage/"):
        return (project_root / normalized_path).is_file()

    if normalized_path.startswith("/"):
        return (project_root / normalized_path.lstrip("/")).is_file()

    return (project_root / normalized_path).is_file()


def _generate_thumbnail_from_video(video_path: str | None):
    if not video_path:
        return None

    video_file = Path(video_path)
    if not video_file.is_file():
        return None

    thumbnails_dir = Path(__file__).resolve().parents[2] / "storage" / "thumbnails"
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    thumbnail_path = thumbnails_dir / f"{video_file.stem}.jpg"

    capture = cv2.VideoCapture(str(video_file))
    try:
        if not capture.isOpened():
            return None

        success, frame = capture.read()
        if not success or frame is None:
            return None

        if cv2.imwrite(str(thumbnail_path), frame):
            return str(thumbnail_path)
    finally:
        capture.release()

    return None


def _resolve_thumbnail_source(video: Video):
    if video.thumbnail_path and video.thumbnail_path != "default_thumb.jpg" and _storage_file_exists(video.thumbnail_path):
        return video.thumbnail_path

    videos_dir = Path(__file__).resolve().parents[2] / "storage" / "videos"

    candidates = []
    if video.video_path:
        candidates.append(Path(video.video_path))

    if video.nombrevideo:
        candidates.extend(sorted(videos_dir.glob(f"{Path(video.nombrevideo).stem}.*")))

    for candidate in candidates:
        if candidate and candidate.is_file() and candidate.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            return str(candidate)

    generated_thumbnail = _generate_thumbnail_from_video(video.video_path)
    if generated_thumbnail:
        return generated_thumbnail

    return None

def _build_thumbnail_url(thumbnail_path: str | None):
    if not thumbnail_path:
        return None

    normalized_path = thumbnail_path.replace("\\", "/")
    if normalized_path.startswith("http://") or normalized_path.startswith("https://"):
        return normalized_path

    # Ensure a leading slash for storage-relative paths
    if normalized_path.lower().startswith("storage/"):
        normalized_path = f"/{normalized_path}"

    # If path is under /storage/, URL-encode the tail to handle spaces and unicode
    storage_index = normalized_path.lower().find('/storage/')
    if storage_index >= 0:
        tail = normalized_path[storage_index + len('/storage/'):]
        return f"/storage/{quote(tail, safe='/')}"

    # Fallbacks for various stored path formats
    if normalized_path.lower().startswith("videos/"):
        tail = normalized_path[len('videos/'):]
        return f"/storage/videos/{quote(tail, safe='/')}"

    if normalized_path.lower().startswith("thumbnails/"):
        tail = normalized_path[len('thumbnails/'):]
        return f"/storage/thumbnails/{quote(tail, safe='/')}"

    if "/videos/" in normalized_path.lower():
        videos_index = normalized_path.lower().find("/videos/")
        tail = normalized_path[videos_index + len('/videos/'):]
        return f"/storage/videos/{quote(tail, safe='/')}"

    if "/thumbnails/" in normalized_path.lower():
        thumbnails_index = normalized_path.lower().find("/thumbnails/")
        tail = normalized_path[thumbnails_index + len('/thumbnails/'):]
        return f"/storage/thumbnails/{quote(tail, safe='/')}"

    if normalized_path.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return f"/storage/videos/{quote(normalized_path.split('/')[-1], safe='/')}"

    return None
@router.post("/download")
async def download_video(
    url: str = Body(..., embed=True), 
    nombreuser: str = Body(..., embed=True), # Recibimos el usuario directamente
    db: Session = Depends(get_db)
):
    require_active_membership(nombreuser, db)
    # 1. Lógica de descarga y extracción
    video_data = process_video_download(url)
    
    # 2. Comprobar si ya existe por hash para no duplicar en BD
    existing = db.query(Video).filter(Video.hash_video == video_data['hash']).first()
    if existing:
        thumbnail_source = _resolve_thumbnail_source(existing)
        return {
            "status": "exists",
            "video": {
                "hash_video": existing.hash_video,
                "nombrevideo": existing.nombrevideo,
                "red_social": existing.red_social,
                "duracion": existing.duracion,
                "resolucion": existing.resolucion,
                "thumbnail_path": existing.thumbnail_path,
                "video_path": existing.video_path,
                "thumbnail_url": _build_thumbnail_url(thumbnail_source),
                "usuario_nombreuser": existing.usuario_nombreuser,
            },
        }

    # 3. Guardar en la tabla Video
    nuevo_video = Video(
        hash_video=video_data['hash'],
        nombrevideo=video_data['title'][:120],
        red_social=video_data['platform'],
        duracion=video_data['duration'],
        resolucion=video_data['resolution'],
        thumbnail_path=video_data['thumb'],
        video_path=video_data['video_path'],
        usuario_nombreuser=nombreuser # ID del usuario logeado
    )

    try:
        db.add(nuevo_video)
        db.commit()
        db.refresh(nuevo_video)
    except Exception:
        db.rollback()
        logger.exception('Database insert failed for downloaded video hash=%s', video_data['hash'])
        raise HTTPException(status_code=500, detail='No se pudo registrar el video descargado.')

    thumbnail_source = _resolve_thumbnail_source(nuevo_video)

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
            "thumbnail_url": _build_thumbnail_url(thumbnail_source),
            "usuario_nombreuser": nuevo_video.usuario_nombreuser,
        },
    }