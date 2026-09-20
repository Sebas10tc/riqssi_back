from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.video_analysis_service import analyze_video_track, validate_video_track

router = APIRouter()

@router.post("/analyze-video/{pvideo_hash}")
async def analyze_video(pvideo_hash: str, db: Session = Depends(get_db)):
    return analyze_video_track(pvideo_hash, db)


@router.post("/validate-video/{pvideo_hash}")
async def validate_video(pvideo_hash: str, db: Session = Depends(get_db)):
    return validate_video_track(pvideo_hash, db)