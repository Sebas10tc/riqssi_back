import os
import hashlib
import cv2 # Para obtener resolución y duración
from fastapi import UploadFile, HTTPException
from .storage_service import persist_file

VIDEO_DIR = "storage/videos"
THUMB_DIR = "storage/thumbnails"

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

async def save_local_video(file: UploadFile):
    # Validar extensión
    if not file.filename.endswith('.mp4'):
        raise HTTPException(status_code=400, detail="Solo se admiten archivos .mp4")

    # Guardar temporalmente para calcular Hash y Metadatos
    temp_path = os.path.join(VIDEO_DIR, file.filename)
    with open(temp_path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    # Calcular Hash SHA-256
    sha256_hash = hashlib.sha256(content).hexdigest()
    
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
        "hash": sha256_hash,
        "filename": file.filename,
        "path": remote_video_path,
        "thumb_path": remote_thumb_path,
        "local_path": temp_path,
        **{key: value for key, value in metadata.items() if key != 'thumb_path'},
    }