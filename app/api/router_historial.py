from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Historial, Video, Resultado_Total
from sqlalchemy import text

router = APIRouter()


def _resultado_total_has_user_column(db: Session) -> bool:
    try:
        columns = inspect(db.get_bind()).get_columns('resultado_total')
        return any(column['name'] == 'usuario_nombreuser' for column in columns)
    except Exception:
        return False


@router.post("/")
def add_historial(entry: dict, db: Session = Depends(get_db)):
    usuario = entry.get("usuario_nombreuser")
    video_hash = entry.get("video_hash_video")
    estado = entry.get("estado", "VISTO")

    if not usuario or not video_hash:
        raise HTTPException(status_code=400, detail="Faltan campos usuario_nombreuser o video_hash_video")

    existing = db.query(Historial).filter(
        Historial.usuario_nombreuser == usuario,
        Historial.video_hash_video == video_hash
    ).first()
    if existing:
        existing.estado = estado
        db.commit()
        return {"status": "updated"}

    nuevo = Historial(usuario_nombreuser=usuario, video_hash_video=video_hash, estado=estado)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"status": "created", "idhistorial": nuevo.idhistorial}


@router.get("/{usuario_nombreuser}")
def get_historial(usuario_nombreuser: str, db: Session = Depends(get_db)):
    has_user_column = _resultado_total_has_user_column(db)

    if not has_user_column:
        sql = text("""
            SELECT h.idhistorial, h.estado, h.fecha_consulta, v.hash_video, v.nombrevideo, v.red_social, v.duracion, v.resolucion, v.thumbnail_path, v.video_path,
                   rt.resultadopvideo, rt.resultadopaudio, rt.veredicto_final, rt.etiqueta_final
            FROM historial h
            JOIN video v ON h.video_hash_video = v.hash_video
            LEFT JOIN resultado_total rt ON rt.video_hash_video = v.hash_video
            WHERE h.usuario_nombreuser = :user
            ORDER BY h.idhistorial DESC
        """)
        rows = db.execute(sql, {"user": usuario_nombreuser}).fetchall()
        result = []
        for r in rows:
            result.append({
                "idhistorial": r.idhistorial,
                "estado": r.estado,
                "fecha_consulta": r.fecha_consulta.isoformat() if r.fecha_consulta else None,
                "video": {
                    "hash_video": r.hash_video,
                    "nombrevideo": r.nombrevideo,
                    "red_social": r.red_social,
                    "duracion": r.duracion,
                    "resolucion": r.resolucion,
                    "thumbnail_path": r.thumbnail_path,
                    "video_path": r.video_path,
                },
                "resultado_total": {
                    "resultadopvideo": r.resultadopvideo,
                    "resultadopaudio": r.resultadopaudio,
                    "veredicto_final": r.veredicto_final,
                    "etiqueta_final": r.etiqueta_final,
                } if r.resultadopvideo is not None or r.resultadopaudio is not None or r.veredicto_final is not None or r.etiqueta_final is not None else None,
            })
        return {"history": result}

    # Try ORM query; fall back to raw SQL if schema is older
    try:
        query = db.query(Historial, Video, Resultado_Total).join(Video, Historial.video_hash_video == Video.hash_video)
        if has_user_column:
            query = query.outerjoin(
                Resultado_Total,
                (Resultado_Total.video_hash_video == Video.hash_video) &
                (Resultado_Total.usuario_nombreuser == Historial.usuario_nombreuser),
            )
        else:
            query = query.outerjoin(Resultado_Total, Resultado_Total.video_hash_video == Video.hash_video)

        rows = query.filter(
            Historial.usuario_nombreuser == usuario_nombreuser
        ).order_by(Historial.idhistorial.desc()).all()

        result = []
        for hist, video, resultado_total in rows:
            result.append({
                "idhistorial": hist.idhistorial,
                "estado": hist.estado,
                "fecha_consulta": hist.fecha_consulta.isoformat() if getattr(hist, 'fecha_consulta', None) else None,
                "video": {
                    "hash_video": video.hash_video,
                    "nombrevideo": video.nombrevideo,
                    "red_social": video.red_social,
                    "duracion": video.duracion,
                    "resolucion": video.resolucion,
                    "thumbnail_path": video.thumbnail_path,
                    "video_path": video.video_path,
                },
                "resultado_total": {
                    "resultadopvideo": resultado_total.resultadopvideo,
                    "resultadopaudio": resultado_total.resultadopaudio,
                    "veredicto_final": resultado_total.veredicto_final,
                    "etiqueta_final": resultado_total.etiqueta_final,
                } if resultado_total else None,
            })

        return {"history": result}

    except Exception:
        # Fallback a SQL raw si falló el ORM (columna faltante, etc.)
        try:
            db.rollback()
        except Exception:
            pass

        if has_user_column:
            sql = text("""
                SELECT h.idhistorial, h.estado, v.hash_video, v.nombrevideo, v.red_social, v.duracion, v.resolucion, v.thumbnail_path, v.video_path,
                       rt.resultadopvideo, rt.resultadopaudio, rt.veredicto_final, rt.etiqueta_final
                FROM historial h
                JOIN video v ON h.video_hash_video = v.hash_video
                LEFT JOIN resultado_total rt ON rt.video_hash_video = v.hash_video AND rt.usuario_nombreuser = h.usuario_nombreuser
                WHERE h.usuario_nombreuser = :user
                ORDER BY h.idhistorial DESC
            """)
        else:
            sql = text("""
                SELECT h.idhistorial, h.estado, v.hash_video, v.nombrevideo, v.red_social, v.duracion, v.resolucion, v.thumbnail_path, v.video_path,
                       rt.resultadopvideo, rt.resultadopaudio, rt.veredicto_final, rt.etiqueta_final
                FROM historial h
                JOIN video v ON h.video_hash_video = v.hash_video
                LEFT JOIN resultado_total rt ON rt.video_hash_video = v.hash_video
                WHERE h.usuario_nombreuser = :user
                ORDER BY h.idhistorial DESC
            """)

        rows = db.execute(sql, {"user": usuario_nombreuser}).fetchall()
        result = []
        for r in rows:
            result.append({
                "idhistorial": r.idhistorial,
                "estado": r.estado,
                "fecha_consulta": None,
                "video": {
                    "hash_video": r.hash_video,
                    "nombrevideo": r.nombrevideo,
                    "red_social": r.red_social,
                    "duracion": r.duracion,
                    "resolucion": r.resolucion,
                    "thumbnail_path": r.thumbnail_path,
                    "video_path": r.video_path,
                },
                "resultado_total": {
                    "resultadopvideo": r.resultadopvideo,
                    "resultadopaudio": r.resultadopaudio,
                    "veredicto_final": r.veredicto_final,
                    "etiqueta_final": r.etiqueta_final,
                } if r.resultadopvideo is not None or r.resultadopaudio is not None or r.veredicto_final is not None or r.etiqueta_final is not None else None,
            })

        return {"history": result}


@router.delete("/{usuario_nombreuser}/{idhistorial}")
def delete_historial_entry(usuario_nombreuser: str, idhistorial: int, db: Session = Depends(get_db)):
    entry = db.query(Historial).filter(
        Historial.idhistorial == idhistorial,
        Historial.usuario_nombreuser == usuario_nombreuser
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrada de historial no encontrada")

    try:
        db.delete(entry)
        db.commit()
        return {"status": "deleted", "idhistorial": idhistorial}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))