import os
import hashlib
import cv2 # Para obtener resolución y duración
from fastapi import UploadFile, HTTPException
from .storage_service import persist_file

VIDEO_DIR = "storage/videos"
THUMB_DIR = "storage/thumbnails"
UPLOAD_CHUNK_SIZE = 1024 * 1024

def get_video_metadata(file_path):
    """Extrae duración, resolución y genera una miniatura."""
    cap = cv2.VideoCapture(file_path)
    if not cap.isOpened():
        return None

    # 1. Obtener Resolución
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    # 2. Obtener Duración
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = int(frame_count / fps) if fps > 0 else 0

    # 3. Generar Miniatura (capturar el primer frame)
    ret, frame = cap.read()
    thumb_name = os.path.basename(file_path).rsplit('.', 1)[0] + ".jpg"
    thumb_path = os.path.join(THUMB_DIR, thumb_name)
    if ret:
        cv2.imwrite(thumb_path, frame)
    
    cap.release()

    return {
        "resolution": f"{width}x{height}",
        "duration": duration,
        "thumb_path": thumb_path
    }

async def save_local_video(file: UploadFile, max_size_bytes: int, plan_name: str):
    # Validar extensión
    if not file.filename or not file.filename.lower().endswith('.mp4'):
        raise HTTPException(status_code=400, detail="Solo se admiten archivos .mp4")

    os.makedirs(VIDEO_DIR, exist_ok=True)
    os.makedirs(THUMB_DIR, exist_ok=True)

    temp_path = os.path.join(VIDEO_DIR, file.filename)
    sha256 = hashlib.sha256()
    file_size = 0
    try:
        with open(temp_path, "wb") as buffer:
            while content := await file.read(UPLOAD_CHUNK_SIZE):
                file_size += len(content)
                if file_size > max_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"El archivo supera el límite de {max_size_bytes // (1024 * 1024)} MB del plan {plan_name}.",
                    )
                buffer.write(content)
                sha256.update(content)
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise

    # Extraer Metadatos
    metadata = get_video_metadata(temp_path)
    
    if not metadata:
        os.remove(temp_path)
        raise HTTPException(status_code=400, detail="No se pudo procesar el archivo de video")

    remote_video_path = persist_file(
        temp_path,
        f'storage/videos/{os.path.basename(temp_path)}',
    )
    remote_thumb_path = (
        persist_file(
            metadata['thumb_path'],
            f"storage/thumbnails/{os.path.basename(metadata['thumb_path'])}",
        )
        if os.path.exists(metadata['thumb_path'])
        else metadata['thumb_path']
    )

    return {
        "hash": sha256.hexdigest(),
        "filename": file.filename,
        "path": remote_video_path,
        "thumb_path": remote_thumb_path,
        "local_path": temp_path,
        **{key: value for key, value in metadata.items() if key != 'thumb_path'},
    }