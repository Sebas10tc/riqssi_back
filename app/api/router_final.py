from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.final_analysis_service import process_final_verdict
from ..models import (
    Video, Historial, Resultado_Total, Resultado_Audio, Resultado_Video,
    Extraccion_Audio, Extraccion_Video, Pista_Audio, Pista_Video,
)
from .router_auth import require_active_membership

router = APIRouter()


def _resultado_total_has_user_column(db: Session) -> bool:
    try:
        columns = inspect(db.get_bind()).get_columns('resultado_total')
        return any(column['name'] == 'usuario_nombreuser' for column in columns)
    except Exception:
        return False

@router.post("/verdict/{video_hash}")
async def get_final_verdict(video_hash: str, db: Session = Depends(get_db), force: bool = Query(False), nombreuser: str | None = Query(None)):
    """Calcula el promedio final y limpia los archivos temporales de storage.

    Si `force=true`, elimina cualquier `Resultado_Total` previo para este video
    y fuerza un nuevo análisis/recalculo.
    """
    if not nombreuser:
        raise HTTPException(status_code=400, detail='Se requiere el usuario para validar la membresía')
    require_active_membership(nombreuser, db)
    has_user_column = _resultado_total_has_user_column(db)

    if force:
        # Eliminar resultado previo si existe. Si se especifica `nombreuser`, sólo ese usuario.
        if has_user_column and nombreuser:
            existing = db.query(Resultado_Total).filter(Resultado_Total.video_hash_video == video_hash, Resultado_Total.usuario_nombreuser == nombreuser).all()
        elif has_user_column:
            existing = db.query(Resultado_Total).filter(Resultado_Total.video_hash_video == video_hash).all()
        else:
            db.execute(text("DELETE FROM resultado_total WHERE video_hash_video = :video_hash"), {"video_hash": video_hash})
            db.commit()
            existing = []

        for r in existing:
            db.delete(r)
        if existing:
            db.commit()

    return process_final_verdict(video_hash, db, usuario_nombreuser=nombreuser)


@router.get("/report/{video_hash}")
async def get_existing_report(video_hash: str, db: Session = Depends(get_db), nombreuser: str | None = Query(None)):
    video = db.query(Video).filter(Video.hash_video == video_hash).first()
    if not video:
        raise HTTPException(status_code=404, detail="Video no encontrado")

    has_user_column = _resultado_total_has_user_column(db)
    if nombreuser and has_user_column:
        result = db.query(Resultado_Total).filter(Resultado_Total.video_hash_video == video_hash, Resultado_Total.usuario_nombreuser == nombreuser).order_by(Resultado_Total.idresultado_total.desc()).first()
    elif has_user_column:
        result = db.query(Resultado_Total).filter(Resultado_Total.video_hash_video == video_hash).order_by(Resultado_Total.idresultado_total.desc()).first()
    else:
        result = db.execute(
            text(
                """
                SELECT idresultado_total, resultadopvideo, resultadopaudio, veredicto_final, etiqueta_final
                FROM resultado_total
                WHERE video_hash_video = :video_hash
                ORDER BY idresultado_total DESC
                LIMIT 1
                """
            ),
            {"video_hash": video_hash},
        ).first()

    # Compatibilidad con análisis antiguos: si el video pertenece al historial
    # del usuario, puede recuperar el resultado global guardado anteriormente.
    if not result and nombreuser and has_user_column:
        has_history = db.query(Historial).filter(
            Historial.video_hash_video == video_hash,
            Historial.usuario_nombreuser == nombreuser,
        ).first()
        if has_history:
            result = db.query(Resultado_Total).filter(
                Resultado_Total.video_hash_video == video_hash,
            ).order_by(Resultado_Total.idresultado_total.desc()).first()

    if not result:
        raise HTTPException(status_code=404, detail="El video todavía no tiene un resultado final para este usuario")

    audio_result = db.query(Resultado_Audio).join(Extraccion_Audio).join(Pista_Audio)\
        .filter(Pista_Audio.video_hash_video == video_hash)\
        .order_by(Resultado_Audio.idresultado_a.desc()).first()
    video_result = db.query(Resultado_Video).join(Extraccion_Video).join(Pista_Video)\
        .filter(Pista_Video.video_hash_video == video_hash)\
        .order_by(Resultado_Video.idresultado_v.desc()).first()

    return {
        "idhistorial": None,
        "estado": "VISTO",
        "fecha_consulta": None,
        "video": {
            "hash_video": video.hash_video,
            "nombrevideo": video.nombrevideo,
            "red_social": video.red_social,
            "duracion": video.duracion,
            "resolucion": video.resolucion,
            "thumbnail_path": video.thumbnail_path,
            "video_path": video.video_path,
            "usuario_nombreuser": video.usuario_nombreuser,
        },
        "resultado_total": {
            "resultadopvideo": result.resultadopvideo,
            "resultadopaudio": result.resultadopaudio,
            "veredicto_final": result.veredicto_final,
            "etiqueta_final": result.etiqueta_final,
            "video": {
                "etiqueta": video_result.etiqueta,
                "confianza": video_result.resultado,
                "probabilidad_fake": video_result.resultado if video_result.etiqueta == "FAKE" else 1 - video_result.resultado,
            } if video_result else None,
            "audio": {
                "etiqueta": audio_result.etiqueta,
                "confianza": audio_result.prediccion_rf,
                "probabilidad_fake": audio_result.prediccion_rf if audio_result.etiqueta == "FAKE" else 1 - audio_result.prediccion_rf,
            } if audio_result else None,
        },
    }