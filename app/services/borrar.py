from app.database import SessionLocal
from app.models import Pista_Audio, Pista_Video, Resultado_Audio, Resultado_Video
from sqlalchemy import text
from app.services.final_analysis_service import process_final_verdict

VIDEO_HASH = "068fe824175d188fb2156db8e21ca4930dc615840bbac1922bc85c4d6b334118"

db = SessionLocal()

# 1) Ver si hay audio/video asociados
q = text("""
    SELECT v.hash_video, v.nombrevideo, pv.hash_pvideo, pa.hash_paudio
    FROM video v
    LEFT JOIN pista_video pv ON pv.video_hash_video = v.hash_video
    LEFT JOIN pista_audio pa ON pa.video_hash_video = v.hash_video
    WHERE v.hash_video = :video_hash
""")
row = db.execute(q, {"video_hash": VIDEO_HASH}).first()
print("VIDEO EN BD:", row)

# 2) Ver último resultado de audio
res_audio = db.execute(
    text("""
        SELECT ra.idresultado_a, ra.prediccion_rf, ra.etiqueta
        FROM resultado_audio ra
        JOIN extraccion_audio ea ON ea.id_extracciona = ra.extraccion_audio_id_extraccion
        JOIN pista_audio pa ON pa.hash_paudio = ea.pista_audio_hash_paudio
        WHERE pa.video_hash_video = :video_hash
        ORDER BY ra.idresultado_a DESC
        LIMIT 1
    """),
    {"video_hash": VIDEO_HASH},
).first()
print("ULTIMO AUDIO:", res_audio)

# 3) Ver último resultado de video
res_video = db.execute(
    text("""
        SELECT rv.idresultado_v, rv.resultado, rv.etiqueta
        FROM resultado_video rv
        JOIN extraccion_video ev ON ev.id_extraccionv = rv.extraccion_video_id_extraccio
        JOIN pista_video pv ON pv.hash_pvideo = ev.pista_video_hash_pvideo
        WHERE pv.video_hash_video = :video_hash
        ORDER BY rv.idresultado_v DESC
        LIMIT 1
    """),
    {"video_hash": VIDEO_HASH},
).first()
print("ULTIMO VIDEO:", res_video)

# 4) Calcular promedio como lo hace el backend
if res_audio and res_video:
    score_audio = float(res_audio.prediccion_rf if hasattr(res_audio, 'prediccion_rf') else res_audio[1])
    score_video = float(res_video.resultado if hasattr(res_video, 'resultado') else res_video[1])
    promedio = (score_audio + score_video) / 2
    etiqueta = "FAKE" if promedio > 0.5 else "REAL"
    print("SCORE_AUDIO:", score_audio)
    print("SCORE_VIDEO:", score_video)
    print("PROMEDIO:", promedio)
    print("ETIQUETA_FINAL:", etiqueta)

# 5) Ejecutar veredicto final real del backend
print("VEREDICTO_FINAL_BACKEND:")
print(process_final_verdict(VIDEO_HASH, db))

db.close()