import sys, traceback, os
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

from app.database import SessionLocal
from app.services.final_analysis_service import process_final_verdict

video_hash = '08ff4a976276c8930343bf9fb6bb2809f104c1f65b5fd5efd3742e56ab1fccdb'
usuario = 'Seb10'

db = SessionLocal()
try:
    res = process_final_verdict(video_hash, db, usuario_nombreuser=usuario)
    print('Result:', res)
except Exception as e:
    print('Exception:', type(e), e)
    traceback.print_exc()
finally:
    db.close()
