import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.database import SessionLocal
from app.models import Video

if __name__ == '__main__':
    db = SessionLocal()
    try:
        rows = db.query(Video).limit(50).all()
        if not rows:
            print('NO_VIDEOS')
        for v in rows:
            print(v.hash_video, v.nombrevideo, v.usuario_nombreuser, v.thumbnail_path)
    finally:
        db.close()
