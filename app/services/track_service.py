import os
import hashlib
import subprocess
from pathlib import Path
from venv import logger
import cv2
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..models import Video, Pista_Video, Pista_Audio
from  .video_analysis_service import _resolve_storage_path
from .storage_service import ensure_local_file, persist_file


# Rutas de almacenamiento para pistas
AUDIO_TRACKS_DIR = "storage/audio_tracks"
VIDEO_TRACKS_DIR = "storage/video_tracks"

os.makedirs(AUDIO_TRACKS_DIR, exist_ok=True)
os.makedirs(VIDEO_TRACKS_DIR, exist_ok=True)

def get_file_hash(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)
    return sha256.hexdigest()


def resolve_original_video_path(video_db: Video):
    """Intenta encontrar el archivo original usando la ruta real o el nombre base en storage/videos."""
    if getattr(video_db, "video_path", None):
        direct_path = video_db.video_path
        try:
            local_path = ensure_local_file(direct_path)
            if os.path.exists(local_path):
                return local_path
        except (ValueError, FileNotFoundError):
            pass

        if os.path.isabs(direct_path) and os.path.exists(direct_path):
            return direct_path

        project_root = Path(__file__).resolve().parents[2]
        normalized = str(direct_path).replace("\\", "/")
        relative_candidate = project_root / normalized.lstrip("/")
        if relative_candidate.exists():
            return str(relative_candidate)

    if video_db.nombrevideo:
        videos_dir = Path(VIDEO_TRACKS_DIR).parent / "videos"
        title_candidate = Path(video_db.nombrevideo).stem
        title_matches = sorted(videos_dir.glob(f"{title_candidate}.*"))
        for match in title_matches:
            if match.is_file():
                return str(match)

    if video_db.thumbnail_path:
        thumbnail_candidate = Path(video_db.thumbnail_path)
        original_name = thumbnail_candidate.stem

        videos_dir = Path(VIDEO_TRACKS_DIR).parent / "videos"
        matches = sorted(videos_dir.glob(f"{original_name}.*"))
        for match in matches:
            if match.is_file():
                return str(match)

    raise HTTPException(status_code=404, detail=f"Archivo físico no encontrado en storage/videos para {video_db.nombrevideo}")

def extract_and_clean_tracks(video_hash: str, db: Session, force: bool = False):
    import logging

    logger = logging.getLogger(__name__)
    # 1. Obtener el video de la base de datos
    video_db = db.query(Video).filter(Video.hash_video == video_hash).first()
    if not video_db:
        raise HTTPException(status_code=404, detail="Video no encontrado en la base de datos")

    existing_video_track = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).first()
    existing_audio_track = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).first()
    existing_video_file = _resolve_storage_path(existing_video_track.ruta_pvideo) if existing_video_track else None
    existing_audio_file = _resolve_storage_path(existing_audio_track.ruta_paudio) if existing_audio_track else None

    if (
        not force
        and existing_video_track
        and existing_audio_track
        and existing_video_file
        and os.path.exists(existing_video_file)
        and existing_audio_file
        and os.path.exists(existing_audio_file)
    ):
        return {
            "status": "already_processed",
            "pista_video_hash": existing_video_track.hash_pvideo if existing_video_track else None,
            "pista_audio_hash": existing_audio_track.hash_paudio if existing_audio_track else None,
            "original_deleted": True,
        }

    original_path = resolve_original_video_path(video_db)
    logger.info(f"TRACKS: video localizado {original_path}")
    logger.info(f"TRACKS: iniciando extracción de pistas para {video_hash}")
    def _build_existing_response():
        existing_video_track = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).first()
        existing_audio_track = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).first()
        if not existing_video_track and not existing_audio_track:
            return None

        return {
            "status": "already_processed",
            "pista_video_hash": existing_video_track.hash_pvideo if existing_video_track else None,
            "pista_audio_hash": existing_audio_track.hash_paudio if existing_audio_track else None,
            "original_deleted": True,
        }

    try:
        capture = cv2.VideoCapture(original_path)
        fps = capture.get(cv2.CAP_PROP_FPS) or 0
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        capture.release()
        n_frames = int(frame_count)
        logger.info(f"TRACKS: metadata video obtenida frames={n_frames}")
        n_frames = int(frame_count)

        # --- EXTRACCIÓN DE AUDIO ---
        audio_filename = f"audio_{video_hash[:10]}.wav"
        audio_path = os.path.join(AUDIO_TRACKS_DIR, audio_filename)
        logger.info("TRACKS: iniciando extracción audio")
        audio_result = subprocess.run(
            [
                'ffmpeg', '-y', '-loglevel', 'error', '-threads', '1',
                '-i', original_path, '-vn', '-ac', '1', '-ar', '16000',
                '-c:a', 'pcm_s16le', audio_path,
            ],
            capture_output=True,
            text=True,
        )
        if audio_result.returncode == 0 and os.path.exists(audio_path):
            audio_hash = get_file_hash(audio_path)
            logger.info("TRACKS: subiendo audio a Supabase")
            audio_path = persist_file(audio_path, f"storage/audio_tracks/{audio_filename}")
            frecuencia = 16000
            logger.info(f"TRACKS: extracción de audio completada audio_hash={audio_hash}")
        else:
            audio_path, audio_hash, frecuencia = None, None, 0

        # --- EXTRACCIÓN DE VIDEO (SIN AUDIO) ---
        video_track_filename = f"track_{video_hash[:10]}.mp4"
        video_track_path = os.path.join(VIDEO_TRACKS_DIR, video_track_filename)
        logger.info("TRACKS: iniciando extracción video")
        video_result = subprocess.run(
            [
                'ffmpeg', '-y', '-loglevel', 'error', '-threads', '1',
                '-i', original_path, '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                '-movflags', '+faststart', video_track_path,
            ],
            capture_output=True,
            text=True,
        )
        if video_result.returncode != 0 or not os.path.exists(video_track_path):
            raise HTTPException(
                status_code=400,
                detail=f"No se pudo extraer la pista de video: {video_result.stderr.strip() or 'ffmpeg no generó salida'}",
            )
        video_track_hash = get_file_hash(video_track_path)
        logger.info(f"TRACKS: extracción de video completada video_track_hash={video_track_hash}")
        logger.info("TRACKS: subiendo video a Supabase")
        video_track_path = persist_file(video_track_path, f"storage/video_tracks/{video_track_filename}")
        logger.info("TRACKS: video subido a Supabase")
        # --- GUARDAR EN BASE DE DATOS ---
        # Pista Video
        existing_video_track = db.query(Pista_Video).filter(Pista_Video.hash_pvideo == video_track_hash).first()
        p_video = existing_video_track or Pista_Video(
            hash_pvideo=video_track_hash,
            ruta_pvideo=video_track_path,
            nroframes=str(n_frames),
            video_hash_video=video_hash
        )
        
        # Pista Audio
        p_audio = None
        if audio_hash:
            existing_audio_track = db.query(Pista_Audio).filter(Pista_Audio.hash_paudio == audio_hash).first()
            p_audio = existing_audio_track or Pista_Audio(
                hash_paudio=audio_hash,
                frecuencia=frecuencia,
                ruta_paudio=audio_path,
                video_hash_video=video_hash
            )

        if existing_video_track is None:
            db.add(p_video)
        if p_audio and db.query(Pista_Audio).filter(Pista_Audio.hash_paudio == audio_hash).first() is None:
            db.add(p_audio)

        try:
            logger.info("TRACKS: guardando en BD")
            db.commit()
            logger.info("TRACKS: commit exitoso")
        except IntegrityError:
            db.rollback()
            existing_response = _build_existing_response()
            if existing_response:
                if os.path.exists(original_path):
                    os.remove(original_path)
                return existing_response
            raise

        # --- LIMPIEZA ---
        if os.path.exists(original_path):
            os.remove(original_path) # Eliminar video original solo después de procesar correctamente
        logger.info("TRACKS: proceso completado correctamente")
        return {
            "status": "processed",
            "pista_video_hash": video_track_hash,
            "pista_audio_hash": audio_hash,
            "original_deleted": True
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error procesando pistas: {str(e)}")


def repair_tracks_paths(video_hash: str, db: Session):
    """Intenta reparar rutas de `Pista_Video` y `Pista_Audio` para un video.

    1) Si la pista existe pero el archivo ha sido movido/renombrado, busca en storage/video_tracks y storage/audio_tracks
       por coincidencias del prefijo del hash y actualiza `ruta_pvideo`/`ruta_paudio` en BD.
    2) Si no existen pistas pero existe el video original en storage/videos, llama a `extract_and_clean_tracks`.
    Devuelve un dict con acciones realizadas.
    """
    actions = {"video_updated": False, "audio_updated": False, "extracted": False}

    video_db = db.query(Video).filter(Video.hash_video == video_hash).first()
    if not video_db:
        raise HTTPException(status_code=404, detail="Video no encontrado en la BD")

    # Buscar pistas existentes
    p_video = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).first()
    p_audio = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).first()

    project_root = Path(__file__).resolve().parents[2]

    # Helper para buscar por prefijo
    def find_candidate(folder, prefix):
        folder_path = project_root / folder
        if not folder_path.exists():
            return None
        for f in folder_path.iterdir():
            if f.is_file() and f.name.startswith(prefix):
                return str(f)
        return None

    prefix = video_hash[:10]

    # Reparar pista de video
    if p_video:
        current = p_video.ruta_pvideo or ''
        resolved = os.path.abspath(os.path.join(project_root, current)) if current and not os.path.isabs(current) else current
        if not resolved or not os.path.exists(resolved):
            candidate = find_candidate('storage/video_tracks', f'track_{prefix}')
            if candidate:
                p_video.ruta_pvideo = candidate
                try:
                    db.add(p_video)
                    db.commit()
                    actions['video_updated'] = candidate
                except Exception:
                    db.rollback()

    # Reparar pista de audio
    if p_audio:
        current = p_audio.ruta_paudio or ''
        resolved = os.path.abspath(os.path.join(project_root, current)) if current and not os.path.isabs(current) else current
        if not resolved or not os.path.exists(resolved):
            candidate = find_candidate('storage/audio_tracks', f'audio_{prefix}')
            if candidate:
                p_audio.ruta_paudio = candidate
                try:
                    db.add(p_audio)
                    db.commit()
                    actions['audio_updated'] = candidate
                except Exception:
                    db.rollback()

    # Si no hay pistas, intentar encontrar el original en storage/videos y re-extraer
    if (not p_video and not p_audio) or (not actions['video_updated'] and not actions['audio_updated']):
        # buscar en storage/videos por nombre relacionado con video_db.nombrevideo o por hash
        videos_dir = project_root / 'storage' / 'videos'
        found_original = None
        if videos_dir.exists():
            # Buscar por nombre base
            if video_db.nombrevideo:
                stem = Path(video_db.nombrevideo).stem
                for f in videos_dir.iterdir():
                    if f.is_file() and stem in f.name:
                        found_original = str(f)
                        break
            # Buscar por hash en nombre
            if not found_original:
                for f in videos_dir.iterdir():
                    if f.is_file() and prefix in f.name:
                        found_original = str(f)
                        break

        if found_original:
            # actualizar video.video_path si es necesario
            if not video_db.video_path or not os.path.exists(os.path.abspath(os.path.join(project_root, video_db.video_path))):
                video_db.video_path = found_original
                try:
                    db.add(video_db)
                    db.commit()
                except Exception:
                    db.rollback()

            # Re-extraer pistas
            try:
                extract_and_clean_tracks(video_hash, db)
                actions['extracted'] = True
            except HTTPException as e:
                actions['extracted_error'] = str(e.detail)

    return actions