from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.track_service import extract_and_clean_tracks
from ..services.track_service import repair_tracks_paths
from ..models import Pista_Video, Pista_Audio
from .router_auth import require_active_membership

router = APIRouter()

@router.post("/extract/{video_hash}")
async def extract_tracks(video_hash: str, nombreuser: str, db: Session = Depends(get_db), force: bool = Query(False)):
    """
    Recibe el hash de un video ya registrado, separa sus pistas,
    las registra y elimina el archivo original.
    """
    require_active_membership(nombreuser, db, video_hash)
    result = extract_and_clean_tracks(video_hash, db, force=force)
    return result


@router.post("/repair/{video_hash}")
async def repair_tracks(video_hash: str, db: Session = Depends(get_db)):
    """Endpoint de reparación para actualizar rutas de pistas o re-extraer si es necesario."""
    return repair_tracks_paths(video_hash, db)


@router.get("/info/{video_hash}")
async def info_tracks(video_hash: str, db: Session = Depends(get_db)):
    pv = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).all()
    pa = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).all()

    def asdict_pv(p):
        return {"hash_pvideo": p.hash_pvideo, "ruta_pvideo": p.ruta_pvideo, "nroframes": p.nroframes}

    def asdict_pa(p):
        return {"hash_paudio": p.hash_paudio, "ruta_paudio": p.ruta_paudio, "frecuencia": p.frecuencia}

    return {"pistas_video": [asdict_pv(x) for x in pv], "pistas_audio": [asdict_pa(x) for x in pa]}