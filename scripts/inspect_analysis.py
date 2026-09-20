import sys
import os

# Asegurar que el paquete `app` sea importable cuando ejecutemos el script
proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if proj_root not in sys.path:
    sys.path.insert(0, proj_root)

from app.database import SessionLocal
from app.models import Video, Pista_Audio, Pista_Video, Extraccion_Audio, Extraccion_Video, Resultado_Audio, Resultado_Video, Resultado_Total

if len(sys.argv) < 2:
    print("Usage: python inspect_analysis.py <video_hash>")
    sys.exit(1)

video_hash = sys.argv[1]

db = SessionLocal()

try:
    video = db.query(Video).filter(Video.hash_video == video_hash).first()
    print("Video:", bool(video))
    if video:
        print("  id:", video.id)
        print("  nombrevideo:", video.nombrevideo)
        print("  usuario:", video.usuario_nombreuser)

    p_audio = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).first()
    print("Pista_Audio:", bool(p_audio))
    if p_audio:
        print("  hash_paudio:", p_audio.hash_paudio)
        print("  ruta_paudio:", p_audio.ruta_paudio)

    p_video = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).first()
    print("Pista_Video:", bool(p_video))
    if p_video:
        print("  hash_pvideo:", p_video.hash_pvideo)
        print("  ruta_pvideo:", p_video.ruta_pvideo)

    ext_audio = None
    if p_audio:
        ext_audio = db.query(Extraccion_Audio).filter(Extraccion_Audio.pista_audio_hash_paudio == p_audio.hash_paudio).first()
    print("Extraccion_Audio:", bool(ext_audio))
    if ext_audio:
        print("  id:", ext_audio.id_extracciona)
        print("  ruta_mfcc:", ext_audio.ruta_mfcc)

    ext_video = None
    if p_video:
        ext_video = db.query(Extraccion_Video).filter(Extraccion_Video.pista_video_hash_pvideo == p_video.hash_pvideo).first()
    print("Extraccion_Video:", bool(ext_video))
    if ext_video:
        print("  id:", ext_video.id_extraccionv)
        print("  ruta_video_frames:", ext_video.ruta_video_frames)

    res_audio = None
    if ext_audio:
        res_audio = db.query(Resultado_Audio).filter(Resultado_Audio.extraccion_audio_id_extraccion == ext_audio.id_extracciona).first()
    print("Resultado_Audio:", bool(res_audio))
    if res_audio:
        print("  prediccion_rf:", res_audio.prediccion_rf)
        print("  etiqueta:", res_audio.etiqueta)

    res_video = None
    if ext_video:
        res_video = db.query(Resultado_Video).filter(Resultado_Video.extraccion_video_id_extraccio == ext_video.id_extraccionv).first()
    print("Resultado_Video:", bool(res_video))
    if res_video:
        print("  resultado:", res_video.resultado)
        print("  etiqueta:", res_video.etiqueta)

    res_total = db.query(Resultado_Total).filter(Resultado_Total.video_hash_video == video_hash).first()
    print("Resultado_Total:", bool(res_total))
    if res_total:
        print("  veredicto_final:", res_total.veredicto_final)
        print("  etiqueta_final:", res_total.etiqueta_final)

finally:
    db.close()
