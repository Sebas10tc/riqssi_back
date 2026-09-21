import os
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUCKETS = {
    'videos': os.getenv('SUPABASE_BUCKET_VIDEOS', 'videos'),
    'audio_tracks': os.getenv('SUPABASE_BUCKET_AUDIO', 'audio_tracks'),
    'video_tracks': os.getenv('SUPABASE_BUCKET_VIDEO_TRACKS', 'video_tracks'),
    'video_frames': os.getenv('SUPABASE_BUCKET_FRAMES', 'video_frames'),
    'thumbnails': os.getenv('SUPABASE_BUCKET_THUMBS', 'thumbnails'),
    'mfcc_data': os.getenv('SUPABASE_BUCKET_MFCC', 'mfcc_data'),
    'payment_proofs': os.getenv('SUPABASE_BUCKET_PAYMENT_PROOFS', 'payment_proofs'),
}


def _client():
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not url or not key:
        return None

    from supabase import create_client
    return create_client(url, key)


def _storage_key(path_value: str | Path) -> tuple[str, str]:
    normalized = str(path_value).replace('\\', '/').lstrip('/')
    if normalized.startswith('storage/'):
        normalized = normalized[len('storage/'):]
    bucket_name, _, object_name = normalized.partition('/')
    if bucket_name not in BUCKETS or not object_name:
        raise ValueError(f'Ruta de almacenamiento inválida: {path_value}')
    return BUCKETS[bucket_name], object_name


def persist_file(local_path: str | Path, storage_path: str | Path) -> str:
    """Upload a generated file and return its stable storage key."""
    normalized_path = str(storage_path).replace('\\', '/').lstrip('/')
    if not normalized_path.startswith('storage/'):
        normalized_path = f'storage/{normalized_path}'

    client = _client()
    if not client:
        logger.info('Storage local fallback: %s', normalized_path)
        return normalized_path

    bucket, object_name = _storage_key(normalized_path)
    try:
        file_size = Path(local_path).stat().st_size
        logger.info('Uploading %s bytes to Supabase bucket=%s object=%s', file_size, bucket, object_name)
        with open(local_path, 'rb') as source:
            client.storage.from_(bucket).upload(
                object_name,
                source.read(),
                {'upsert': 'true', 'content-type': 'application/octet-stream'},
            )
        logger.info('Supabase upload completed: bucket=%s object=%s', bucket, object_name)
        return normalized_path
    except Exception:
        logger.exception('Supabase upload failed: bucket=%s object=%s', bucket, object_name)
        raise


def ensure_local_file(path_value: str | Path) -> str:
    """Return a local path, downloading a remote object when necessary."""
    path_text = str(path_value).replace('\\', '/')
    local_path = Path(path_text) if os.path.isabs(path_text) else PROJECT_ROOT / path_text.lstrip('/')
    if local_path.exists():
        return str(local_path)

    client = _client()
    if not client:
        return str(local_path)

    bucket, object_name = _storage_key(path_text)
    try:
        logger.info('Downloading Supabase object: bucket=%s object=%s', bucket, object_name)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        content = client.storage.from_(bucket).download(object_name)
        local_path.write_bytes(content)
        return str(local_path)
    except Exception:
        logger.exception('Supabase download failed: bucket=%s object=%s', bucket, object_name)
        raise


def delete_file(path_value: str | Path) -> None:
    path_text = str(path_value).replace('\\', '/')
    local_path = Path(path_text) if os.path.isabs(path_text) else PROJECT_ROOT / path_text.lstrip('/')
    if local_path.exists():
        local_path.unlink()

    client = _client()
    if client:
        bucket, object_name = _storage_key(path_text)
        client.storage.from_(bucket).remove([object_name])