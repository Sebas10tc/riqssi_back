import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

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
    client = _client()
    if not client:
        normalized = str(storage_path).replace('\\', '/')
        return normalized if normalized.startswith('storage/') else 'storage/' + normalized.lstrip('/')

    bucket, object_name = _storage_key(storage_path)
    with open(local_path, 'rb') as source:
        client.storage.from_(bucket).upload(
            object_name,
            source.read(),
            {'upsert': 'true', 'content-type': 'application/octet-stream'},
        )
    return f'storage/{object_name.split("/", 1)[0]}/{object_name.split("/", 1)[1]}'


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
    local_path.parent.mkdir(parents=True, exist_ok=True)
    content = client.storage.from_(bucket).download(object_name)
    local_path.write_bytes(content)
    return str(local_path)


def delete_file(path_value: str | Path) -> None:
    path_text = str(path_value).replace('\\', '/')
    local_path = Path(path_text) if os.path.isabs(path_text) else PROJECT_ROOT / path_text.lstrip('/')
    if local_path.exists():
        local_path.unlink()

    client = _client()
    if client:
        bucket, object_name = _storage_key(path_text)
        client.storage.from_(bucket).remove([object_name])