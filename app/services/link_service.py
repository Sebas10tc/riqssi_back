import os
import hashlib
import logging
from pathlib import Path

import cv2
import yt_dlp
import subprocess
from fastapi import HTTPException
from .storage_service import persist_file

logger = logging.getLogger(__name__)

# Rutas por defecto
VIDEO_DIR = "storage/videos"
THUMB_DIR = "storage/thumbnails"
os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(THUMB_DIR, exist_ok=True)

ALLOWED_DOMAINS = ["youtube.com", "youtu.be", "facebook.com", "instagram.com", "twitter.com", "x.com", "reddit.com", "tiktok.com", "vm.tiktok.com"]


def _build_base_ydl_opts():
    return {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        # Titles are display metadata, not safe or stable filesystem names.
        'outtmpl': f'{VIDEO_DIR}/%(id)s.%(ext)s',
        'restrictfilenames': True,
        'writethumbnail': True,
        'quiet': True,
        'no_warnings': True,
        'js_runtimes': {'node': {}},
        'socket_timeout': float(os.getenv('YTDLP_SOCKET_TIMEOUT', '60')),
        'retries': int(os.getenv('YTDLP_RETRIES', '10')),
        'fragment_retries': int(os.getenv('YTDLP_FRAGMENT_RETRIES', '10')),
        'extractor_retries': int(os.getenv('YTDLP_EXTRACTOR_RETRIES', '3')),
        'http_headers': {
            'User-Agent': os.getenv(
                'YTDLP_USER_AGENT',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            ),
            'Accept-Language': 'es-PE,es;q=0.9,en;q=0.8',
        },
    }


def _build_cookie_attempts():
    attempts = []

    cookiefile = os.getenv('YTDLP_COOKIEFILE') or os.getenv('YT_DLP_COOKIEFILE')
    if cookiefile:
        if os.path.isabs(cookiefile):
            attempts.append({'cookiefile': cookiefile})
        else:
            attempts.append({'cookiefile': os.path.abspath(cookiefile)})

    browser = (os.getenv('YTDLP_COOKIE_BROWSER') or os.getenv('YT_DLP_COOKIE_BROWSER') or '').strip().lower()
    profile = (os.getenv('YTDLP_COOKIE_PROFILE') or os.getenv('YT_DLP_COOKIE_PROFILE') or '').strip()

    # Browser cookies are opt-in only. On Windows, automatic DPAPI decryption is
    # fragile, so we only try them when explicitly requested.
    if browser:
        if profile:
            attempts.append({'cookiesfrombrowser': (browser, profile)})
        else:
            attempts.append({'cookiesfrombrowser': (browser,)})

    attempts.append({})
    return attempts


def _build_extractor_attempts(url: str):
    if 'youtube.com' in url.lower() or 'youtu.be' in url.lower():
        return [
            {},
            {'extractor_args': {'youtube': {'player_client': ['web_safari']}}},
            {'extractor_args': {'youtube': {'player_client': ['android']}}},
            {'extractor_args': {'youtube': {'player_client': ['ios']}}},
        ]

    if 'tiktok.com' not in url.lower():
        return [{}]

    # TikTok frequently rejects the webpage client; the mobile API is a
    # compatible fallback supported by the installed yt-dlp extractor.
    return [
        {},
        {'extractor_args': {'tiktok': {'app_info': ['musical_ly/35.1.3/2023501030/0']}}},
        {'extractor_args': {'tiktok': {'app_info': ['trill/35.1.3/2023501030/0']}}},
    ]


def _build_network_attempts():
    attempts = [{}]

    if (os.getenv('YTDLP_FORCE_IPV4') or os.getenv('YT_DLP_FORCE_IPV4') or '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        attempts.append({'source_address': '0.0.0.0'})

    return attempts

def validate_link(url: str):
    if not any(domain in url.lower() for domain in ALLOWED_DOMAINS):
        raise HTTPException(status_code=400, detail="Enlace no permitido. Solo se permiten enlaces a videos de YouTube, Facebook, Instagram, X/Twitter, TikTok o Reddit.")

def get_file_hash(file_path):
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(4096), b""):
            sha256.update(block)
    return sha256.hexdigest()


def _generate_thumbnail_from_video(video_path: str):
    thumbnail_dir = Path(THUMB_DIR)
    thumbnail_dir.mkdir(parents=True, exist_ok=True)

    video_file = Path(video_path)
    thumbnail_path = thumbnail_dir / f"{video_file.stem}.jpg"

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


def _move_thumbnail(candidate: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        try:
            target.unlink()
        except Exception:
            pass
    candidate.replace(target)

def process_video_download(url: str):
    validate_link(url)

    last_error = None
    auth_error_detected = False
    for network_opts in _build_network_attempts():
        for extra_opts in _build_cookie_attempts():
            for extractor_opts in _build_extractor_attempts(url):
                ydl_opts = {**_build_base_ydl_opts(), **network_opts, **extra_opts, **extractor_opts}
                try:
                    logger.info('Download attempt: url=%s extractor_options=%s', url, extractor_opts)
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # 1. Comprobar si es un video y obtener info sin descargar aún
                        info = ydl.extract_info(url, download=False)

                        if 'entries' in info:
                            raise HTTPException(status_code=400, detail="El link debe ser de un video individual, no una lista.")

                        # 2. Descargar
                        download_info = ydl.extract_info(url, download=True)
                    video_path = ydl.prepare_filename(download_info)

                    # After post-processing, yt-dlp may change the extension or
                    # return the thumbnail path. Resolve the actual downloaded video.
                    downloaded_candidates = [
                        Path(download_info.get('filepath', '')),
                        Path(video_path),
                    ]
                    downloaded_candidates.extend(
                        Path(VIDEO_DIR).glob(f"{download_info.get('id', '')}.*")
                    )
                    video_candidates = [
                        candidate for candidate in downloaded_candidates
                        if candidate.is_file() and candidate.suffix.lower() in {'.mp4', '.mkv', '.webm', '.mov', '.avi'}
                    ]
                    if not video_candidates:
                        raise HTTPException(status_code=400, detail="El enlace no contiene un video descargable.")
                    video_path = str(video_candidates[0])
                    logger.info('Video download completed: path=%s size=%s', video_path, Path(video_path).stat().st_size)

                    # 3. Manejar miniatura
                    downloaded_path = Path(video_path)
                    final_thumb = None

                    for suffix in (".jpg", ".jpeg", ".png", ".webp"):
                        candidate = downloaded_path.with_suffix(suffix)
                        if candidate.exists():
                            final_thumb = Path(THUMB_DIR) / candidate.name
                            _move_thumbnail(candidate, final_thumb)
                            break

                    if final_thumb is None:
                        final_thumb = _generate_thumbnail_from_video(video_path)

                    # Ensure we produce an optimized thumbnail stored under THUMB_DIR using the video's hash
                    file_hash = get_file_hash(video_path)
                    optimized_thumb = Path(THUMB_DIR) / f"{file_hash}.jpg"

                    try:
                        # If we have an image candidate, try to load and resize it
                        if final_thumb and final_thumb != "default_thumb.jpg":
                            try:
                                img = cv2.imread(str(final_thumb))
                                if img is not None:
                                    h, w = img.shape[:2]
                                    new_w = 480
                                    new_h = int(h * (new_w / w)) if w > 0 else h
                                    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                                    cv2.imwrite(str(optimized_thumb), resized, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                                else:
                                    # fallback: try ffmpeg to extract a frame
                                    subprocess.run([
                                        'ffmpeg', '-y', '-loglevel', 'error',
                                        '-i', str(video_path), '-ss', '00:00:01', '-vframes', '1',
                                        '-vf', 'scale=480:-1', str(optimized_thumb)
                                    ], check=True)
                            except Exception:
                                # final attempt: extract from video
                                subprocess.run([
                                    'ffmpeg', '-y', '-loglevel', 'error',
                                    '-i', str(video_path), '-ss', '00:00:01', '-vframes', '1',
                                    '-vf', 'scale=480:-1', str(optimized_thumb)
                                ], check=True)
                        else:
                            # No candidate image; extract a frame via ffmpeg
                            subprocess.run([
                                'ffmpeg', '-y', '-loglevel', 'error',
                                '-i', str(video_path), '-ss', '00:00:01', '-vframes', '1',
                                '-vf', 'scale=480:-1', str(optimized_thumb)
                            ], check=True)
                    except Exception:
                        optimized_thumb = None

                    # Final thumb to return: optimized if created, else previous candidate, else default
                    final_thumb_path = str(optimized_thumb) if optimized_thumb and Path(str(optimized_thumb)).exists() else (str(final_thumb) if final_thumb else "default_thumb.jpg")
                    remote_video_path = persist_file(video_path, f"storage/videos/{Path(video_path).name}")
                    remote_thumb_path = (
                        persist_file(final_thumb_path, f"storage/thumbnails/{Path(final_thumb_path).name}")
                        if final_thumb_path != "default_thumb.jpg" and Path(final_thumb_path).is_file()
                        else final_thumb_path
                    )

                    return {
                        "hash": file_hash,
                        "title": download_info.get('title', 'Video'),
                        "platform": download_info.get('extractor_key', 'Desconocido'),
                        "resolution": f"{download_info.get('width')}x{download_info.get('height')}",
                        "duration": int(download_info.get('duration', 0)),
                        "video_path": remote_video_path,
                        "thumb": remote_thumb_path
                    }
                except HTTPException:
                    raise
                except Exception as e:
                    last_error = str(e)
                    logger.exception('Link download pipeline failed after yt-dlp attempt: url=%s', url)
                    error_text = last_error.lower()

                    if 'this video is unavailable' in error_text or 'video unavailable' in error_text:
                        raise HTTPException(
                            status_code=400,
                            detail='YouTube indica que el video no está disponible. Verifica que el enlace sea público y siga activo.',
                        )

                    if 'private video' in error_text or 'sign in to confirm your age' in error_text:
                        auth_error_detected = True
                        continue

                    if (
                    'no video could be found in this tweet' in error_text
                    or 'this tweet does not contain a video' in error_text
                    or 'no se encontró ningún video en este tweet' in error_text
                    or 'does not contain a video' in error_text
                    or 'no video' in error_text
                ):
                        raise HTTPException(
                        status_code=400,
                        detail=(
                            'El enlace no contiene un video descargable. '
                            'Solo se permiten enlaces a videos de YouTube, Facebook, Instagram, X/Twitter, TikTok o Reddit.'
                        ),
                    )

                # Detect common yt-dlp authentication/cookies errors and surface a clear 403
                    if (
                        'sign in to confirm you are not a bot' in error_text
                        or 'use --cookies-from-browser' in error_text
                        or 'authentication required' in error_text
                    ):
                        auth_error_detected = True
                        continue

                    if 'timed out' in error_text or 'timeout' in error_text:
                        continue

                    if 'unexpected response from webpage request' in error_text and 'tiktok' in url.lower():
                        last_error = 'TikTok rechazó la solicitud web. Prueba con un enlace público o configura cookies de TikTok.'
                        continue

                    raise HTTPException(status_code=500, detail=f"Error al procesar el video: {last_error}")

    if auth_error_detected:
        raise HTTPException(
            status_code=403,
            detail=(
                "Autenticación requerida para descargar desde YouTube. "
                "Configura YTDLP_COOKIEFILE con un archivo cookies.txt válido exportado desde tu navegador. "
                "Si quieres usar cookies del navegador directamente, define YTDLP_COOKIE_BROWSER y opcionalmente YTDLP_COOKIE_PROFILE. "
                "Más información: https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp"
            ),
        )

    if 'tiktok.com' in url.lower() and last_error:
        raise HTTPException(
            status_code=503,
            detail=(
                'TikTok no permitió descargar este video. Verifica que el enlace sea público y configura '
                'YTDLP_COOKIEFILE con cookies.txt de TikTok si requiere inicio de sesión.'
            ),
        )

    raise HTTPException(status_code=500, detail=f"Error al procesar el video: {last_error}")