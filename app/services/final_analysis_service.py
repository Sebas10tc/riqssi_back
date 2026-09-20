import os
import shutil
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from ..models import (
    Video, Pista_Audio, Pista_Video, 
    Extraccion_Audio, Extraccion_Video, 
    Resultado_Audio, Resultado_Video, Resultado_Total
)
from .audio_analysis_service import analyze_audio_track
from .video_analysis_service import analyze_video_track


def _resultado_total_has_user_column(db: Session) -> bool:
    try:
        columns = inspect(db.get_bind()).get_columns('resultado_total')
        return any(column['name'] == 'usuario_nombreuser' for column in columns)
    except Exception:
        return False

def process_final_verdict(video_hash: str, db: Session, usuario_nombreuser: str | None = None):
    has_user_column = _resultado_total_has_user_column(db)

    # Si el usuario ya tiene un Resultado_Total para este video, lo devolvemos (cache por usuario)
    if usuario_nombreuser:
        if has_user_column:
            existing_total = db.query(Resultado_Total).filter(
                Resultado_Total.video_hash_video == video_hash,
                Resultado_Total.usuario_nombreuser == usuario_nombreuser,
            ).first()
        else:
            existing_total = db.execute(
                text(
                    """
                    SELECT idresultado_total, resultadopvideo, resultadopaudio, veredicto_final, etiqueta_final
                    FROM resultado_total
                    WHERE video_hash_video = :video_hash
                    LIMIT 1
                    """
                ),
                {"video_hash": video_hash},
            ).first()

        if existing_total:
            if has_user_column:
                veredicto_final = existing_total.veredicto_final
                etiqueta_final = existing_total.etiqueta_final
            else:
                veredicto_final = existing_total.veredicto_final
                etiqueta_final = existing_total.etiqueta_final

            return {
                "status": "cached",
                "veredicto_final": f"{float(veredicto_final):.4f}",
                "etiqueta": etiqueta_final,
            }

    # 1. Obtener resultados de Audio y Video (escogemos el más reciente)
    # Buscamos a través de la cadena de relaciones y ordenamos por id descendente
    res_audio = db.query(Resultado_Audio).join(Extraccion_Audio).join(Pista_Audio)\
        .filter(Pista_Audio.video_hash_video == video_hash).order_by(Resultado_Audio.idresultado_a.desc()).first()

    res_video = db.query(Resultado_Video).join(Extraccion_Video).join(Pista_Video)\
        .filter(Pista_Video.video_hash_video == video_hash).order_by(Resultado_Video.idresultado_v.desc()).first()
    # Requerimos ambos resultados (audio y video) para generar el veredicto final.
    missing = []
    if not res_audio:
        missing.append("audio")
    if not res_video:
        missing.append("video")

    # Si el usuario solicitante no tiene un Resultado_Total propio, forzamos nuevo análisis
    user_has_total = False
    if usuario_nombreuser and has_user_column:
        user_has_total = db.query(Resultado_Total).filter(Resultado_Total.video_hash_video == video_hash, Resultado_Total.usuario_nombreuser == usuario_nombreuser).first() is not None

    if missing or (usuario_nombreuser and not user_has_total):
        # Intentamos ejecutar los análisis faltantes automáticamente.
        # Si no existe la pista correspondiente, reportamos como error.
        # Ejecutar audio incluso si ya existe globalmente si el usuario no tiene su propio resultado
        if "audio" in missing or (usuario_nombreuser and not user_has_total):
            pista_audio = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).first()
            if not pista_audio:
                raise HTTPException(status_code=400, detail="Falta la pista de audio para poder analizar.")
            try:
                analyze_audio_track(pista_audio.hash_paudio, db)
            except HTTPException as e:
                raise HTTPException(status_code=500, detail=f"Error al analizar audio automáticamente: {e.detail}")

        if "video" in missing or (usuario_nombreuser and not user_has_total):
            pista_video = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).first()
            if not pista_video:
                raise HTTPException(status_code=400, detail="Falta la pista de video para poder analizar.")
            try:
                analyze_video_track(pista_video.hash_pvideo, db)
            except HTTPException as e:
                raise HTTPException(status_code=500, detail=f"Error al analizar video automáticamente: {e.detail}")

        # Después de forzar los análisis, reconsultamos los resultados (tomando los más recientes)
        res_audio = db.query(Resultado_Audio).join(Extraccion_Audio).join(Pista_Audio)\
            .filter(Pista_Audio.video_hash_video == video_hash).order_by(Resultado_Audio.idresultado_a.desc()).first()
        res_video = db.query(Resultado_Video).join(Extraccion_Video).join(Pista_Video)\
            .filter(Pista_Video.video_hash_video == video_hash).order_by(Resultado_Video.idresultado_v.desc()).first()

        # Si aún falta alguno, devolvemos error claro.
        still_missing = []
        if not res_audio:
            still_missing.append("audio")
        if not res_video:
            still_missing.append("video")
        if still_missing:
            raise HTTPException(status_code=500, detail=f"No se pudieron generar los análisis faltantes: {' y '.join(still_missing)}")

    # 2. Calcular promedio y etiqueta — ambos resultados existen
    try:
        score_audio = float(res_audio.prediccion_rf)
    except Exception:
        raise HTTPException(status_code=400, detail="Resultado de audio inválido o vacío.")

    try:
        score_video = float(res_video.resultado)
    except Exception:
        raise HTTPException(status_code=400, detail="Resultado de video inválido o vacío.")

    # Cada resultado guarda la confianza de su clase ganadora. Para combinar audio y
    # video debemos llevar ambos valores a la misma escala: probabilidad de FAKE.
    audio_fake_probability = score_audio if res_audio.etiqueta == "FAKE" else 1 - score_audio
    video_fake_probability = score_video if res_video.etiqueta == "FAKE" else 1 - score_video
    veredicto = (audio_fake_probability + video_fake_probability) / 2
    etiqueta = "FAKE" if veredicto >= 0.5 else "REAL"

    # 3. Guardar en Resultado_Total (asociado al usuario que solicitó) — solo si la columna existe
    if has_user_column:
        final_result = Resultado_Total(
            resultadopvideo=score_video,
            resultadopaudio=score_audio,
            veredicto_final=veredicto,
            etiqueta_final=etiqueta,
            video_hash_video=video_hash,
            usuario_nombreuser=usuario_nombreuser
        )
        db.add(final_result)
        db.commit()
    else:
        db.execute(
            text(
                """
                INSERT INTO resultado_total (resultadopvideo, resultadopaudio, veredicto_final, etiqueta_final, video_hash_video)
                VALUES (:resultadopvideo, :resultadopaudio, :veredicto_final, :etiqueta_final, :video_hash_video)
                """
            ),
            {
                "resultadopvideo": score_video,
                "resultadopaudio": score_audio,
                "veredicto_final": veredicto,
                "etiqueta_final": etiqueta,
                "video_hash_video": video_hash,
            },
        )
        db.commit()

    # Nota: no eliminamos archivos compartidos aquí para no afectar a otros usuarios

    return {
        "status": "finalized",
        "veredicto_final": f"{veredicto:.4f}",
        "etiqueta": etiqueta,
        "audio": {
            "etiqueta": res_audio.etiqueta,
            "confianza": f"{score_audio * 100:.2f}%",
            "probabilidad_fake": f"{audio_fake_probability:.4f}",
        },
        "video": {
            "etiqueta": res_video.etiqueta,
            "confianza": f"{score_video * 100:.2f}%",
            "probabilidad_fake": f"{video_fake_probability:.4f}",
        },
        "limpieza": "completada"
    }

def cleanup_storage_files(video_hash: str, db: Session):
    """Elimina físicamente archivos de pistas y extracciones del storage."""
    
    # Obtener rutas de pistas
    p_audio = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video_hash).first()
    p_video = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video_hash).first()
    
    # Obtener rutas de extracciones
    ext_audio = db.query(Extraccion_Audio).filter(Extraccion_Audio.pista_audio_hash_paudio == (p_audio.hash_paudio if p_audio else None)).first()
    ext_video = db.query(Extraccion_Video).filter(Extraccion_Video.pista_video_hash_pvideo == (p_video.hash_pvideo if p_video else None)).first()

    # --- Borrado de Pistas ---
    if p_audio and os.path.exists(p_audio.ruta_paudio):
        os.remove(p_audio.ruta_paudio)
    if p_video and os.path.exists(p_video.ruta_pvideo):
        os.remove(p_video.ruta_pvideo)

    # --- Borrado de Extracciones (CSV y Frames) ---
    if ext_audio and os.path.exists(ext_audio.ruta_mfcc):
        os.remove(ext_audio.ruta_mfcc)
    
    if ext_video and os.path.exists(ext_video.ruta_video_frames):
        # En este flujo ruta_video_frames apunta a un archivo .mp4, no a una carpeta.
        if os.path.isdir(ext_video.ruta_video_frames):
            shutil.rmtree(ext_video.ruta_video_frames)
        else:
            os.remove(ext_video.ruta_video_frames)