from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.audio_analysis_service import analyze_audio_track

router = APIRouter()

@router.post("/audio-analyze/{paudio_hash}")
async def analyze_audio(paudio_hash: str, db: Session = Depends(get_db)):
    return analyze_audio_track(paudio_hash, db)