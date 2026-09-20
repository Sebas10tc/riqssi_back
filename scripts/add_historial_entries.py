import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.database import SessionLocal
from app.models import Historial

ENTRIES = [
    {"usuario_nombreuser": "sebas10", "video_hash_video": "8e146ade43f1003ab0277b97b25880d13df385ec0a13ee37c7b14d62e3b183c6", "estado": "VISTO"},
    {"usuario_nombreuser": "sebas10", "video_hash_video": "f0a61769093c881e3a6a7be1ec66f730615b13596da665d73a59af44ef7738af", "estado": "VISTO"}
]

if __name__ == '__main__':
    db = SessionLocal()
    try:
        for e in ENTRIES:
            # check exists
            existing = db.query(Historial).filter(Historial.usuario_nombreuser==e['usuario_nombreuser'], Historial.video_hash_video==e['video_hash_video']).first()
            if existing:
                print('exists', e['usuario_nombreuser'], e['video_hash_video'])
                continue
            h = Historial(usuario_nombreuser=e['usuario_nombreuser'], video_hash_video=e['video_hash_video'], estado=e['estado'])
            db.add(h)
        db.commit()
        print('done')
    finally:
        db.close()
