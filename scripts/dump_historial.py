import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.database import SessionLocal
from app.models import Historial, Video

if __name__ == '__main__':
    db = SessionLocal()
    try:
        rows = db.query(Historial, Video).join(Video, Historial.video_hash_video == Video.hash_video).all()
        if not rows:
            print('NO_ROWS')
        for h, v in rows:
            print(h.idhistorial, h.usuario_nombreuser, h.video_hash_video, v.nombrevideo)
    finally:
        db.close()
