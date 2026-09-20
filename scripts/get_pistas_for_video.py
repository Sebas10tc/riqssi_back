import sys, os
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

from app.database import SessionLocal
from app.models import Pista_Video, Pista_Audio

if len(sys.argv) < 2:
    print('Usage: get_pistas_for_video.py <video_hash>')
    sys.exit(1)

video_hash = sys.argv[1]
db = SessionLocal()
try:
    pv = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).first()
    pa = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).first()
    if pv:
        print('PISTA_VIDEO', pv.hash_pvideo, pv.ruta_pvideo)
    else:
        print('NO PISTA_VIDEO')
    if pa:
        print('PISTA_AUDIO', pa.hash_paudio, pa.ruta_paudio)
    else:
        print('NO PISTA_AUDIO')
finally:
    db.close()
