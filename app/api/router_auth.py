import os
import smtplib
import secrets
import string
import shutil
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from email.message import EmailMessage

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from dotenv import load_dotenv
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import (
    Usuario,
    Video,
    Historial,
    Membresia,
    Membresia_Usuario,
    Pista_Video,
    Pista_Audio,
    Extraccion_Video,
    Extraccion_Audio,
    Resultado_Video,
    Resultado_Audio,
    Resultado_Total,
    Cancelacion_Membresia,
)
from ..schemas import UsuarioCreate, UsuarioLogin, PasswordRecoveryRequest, PasswordChangeRequest
from ..security import create_access_token, hash_password, verify_password
from ..security import get_current_user, require_admin
from ..services.storage_service import persist_file

router = APIRouter()
PAYMENT_PROOF_DIR = Path(__file__).resolve().parents[2] / 'storage' / 'payment_proofs'
PAYMENT_PROOF_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"), override=True)


def _normalize_email(email: str) -> str:
    return email.strip().casefold()


def generate_temporary_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _normalize_plan_name(plan_value: str | None) -> str:
    normalized = (plan_value or 'gratis').strip().casefold()
    plan_aliases = {
        'gratis': 'gratis',
        'free': 'gratis',
        'basico': 'basico',
        'básico': 'basico',
        'premium': 'premium',
    }

    return plan_aliases.get(normalized, 'gratis')


def _normalize_membership_label(label: str | None) -> str:
    normalized = _normalize_plan_name(label)
    decomposed = unicodedata.normalize('NFD', normalized)
    without_marks = ''.join(character for character in decomposed if unicodedata.category(character) != 'Mn')
    return without_marks


def _canonical_membership(label: str | None) -> str:
    normalized = _normalize_membership_label(label)
    return {'gratis': 'free', 'basico': 'basic', 'premium': 'premium'}.get(normalized, 'free')


def _is_paid_plan(plan_value: str | None) -> bool:
    return _canonical_membership(plan_value) in {'basic', 'premium'}


def _new_membership_expiration(plan_value: str | None):
    return datetime.utcnow() + timedelta(days=30) if _is_paid_plan(plan_value) else None


def _yape_qr_url() -> str:
    return os.getenv('YAPE_QR_URL', '/storage/yape/qr.png')


def _expire_membership_if_needed(user: Usuario, db: Session) -> bool:
    expiration = user.membership_expiration
    if not expiration or expiration.date() >= datetime.utcnow().date():
        return False

    free_membership_id = _get_membership_id_for_plan(db, 'gratis')
    membership_record = (
        db.query(Membresia_Usuario)
        .filter(Membresia_Usuario.usuario_nombreuser == user.nombreuser)
        .order_by(Membresia_Usuario.fechasubscripcion.desc(), Membresia_Usuario.idmembresiauser.desc())
        .first()
    )
    if membership_record and free_membership_id is not None:
        membership_record.membresia_idmembresi = free_membership_id
        membership_record.fechavenc = None
        db.add(membership_record)

    user.payment_status = 'expired'
    user.membership = 'free'
    user.membership_reminder_sent_at = None
    db.add(user)
    db.commit()
    return True


def _get_plan_limits(plan: str, db: Session):
    memberships = db.execute(
        text('SELECT nombre, plan_limit, nrovideosdiarios, duracionvideopermitida FROM membresia')
    ).mappings().all()
    for membership in memberships:
        if _canonical_membership(membership['nombre']) == plan:
            plan_limit = membership['plan_limit']
            if plan_limit is None:
                plan_limit = membership['nrovideosdiarios']
            return plan_limit, membership['duracionvideopermitida']
    return (2, 1) if plan == 'free' else (None, None)


def _enforce_plan_limits(user: Usuario, db: Session, video_hash: str | None = None) -> None:
    plan = user.membership or 'free'
    if user.payment_status in {'canceled', 'expired', 'denied'}:
        plan = 'free'

    _, duration_limit_minutes = _get_plan_limits(plan, db)

    if video_hash and duration_limit_minutes:
        video = db.query(Video).filter(Video.hash_video == video_hash).first()
        if video and video.duracion and video.duracion > duration_limit_minutes * 60:
            raise HTTPException(
                status_code=403,
                detail=f'El video supera el límite de {duration_limit_minutes} minuto(s) del plan {plan}.',
            )


def require_active_membership(nombreuser: str, db: Session, video_hash: str | None = None) -> Usuario:
    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not user:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    _expire_membership_if_needed(user, db)
    plan = user.membership or 'free'
    if _is_paid_plan(plan) and (user.payment_status or 'pending') != 'approved':
        status_message = 'Tu membresía está pendiente de aprobación del pago.'
        raise HTTPException(status_code=402, detail=status_message)
    _enforce_plan_limits(user, db, video_hash)
    return user


def consume_video_analysis(user: Usuario, db: Session) -> None:
    _expire_membership_if_needed(user, db)

    plan = user.membership or 'free'

    if user.payment_status in {'canceled', 'expired', 'denied'}:
        plan = 'free'

    plan_limit, _ = _get_plan_limits(plan, db)

    locked_user = (
        db.query(Usuario)
        .filter(Usuario.nombreuser == user.nombreuser)
        .with_for_update()
        .one()
    )

    analyzed_count = locked_user.videos_analyzed_count or 0

    print("=================================")
    print("USER:", user.nombreuser)
    print("PLAN:", plan)
    print("PLAN_LIMIT:", plan_limit)
    print("ANALYZED_COUNT:", analyzed_count)
    print("=================================")

    if plan_limit is not None and analyzed_count >= plan_limit:
        db.rollback()
        raise HTTPException(
            status_code=403,
            detail='Has alcanzado el límite de tu plan. Actualiza tu membresía para analizar más videos.',
        )


def _require_admin(nombreuser: str | None, db: Session) -> Usuario:
    if not nombreuser:
        raise HTTPException(status_code=403, detail='Se requiere un administrador')
    admin = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not admin or (admin.role or '').lower() != 'admin':
        raise HTTPException(status_code=403, detail='Solo un administrador puede realizar esta acción')
    return admin


def _parse_membership_price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    cleaned_value = str(value).strip().replace(',', '.')
    match = re.search(r'-?\d+(?:\.\d+)?', cleaned_value)
    if not match:
        return None

    try:
        return float(match.group(0))
    except ValueError:
        return None


def _get_membership_id_for_plan(db: Session, plan_value: str | None) -> int | None:
    normalized_plan = _normalize_membership_label(plan_value)

    membership_rows = db.execute(
        text(
            """
            SELECT idmembresia, nombre
            FROM membresia
            ORDER BY idmembresia ASC
            """
        )
    ).mappings().all()

    for membership_row in membership_rows:
        if _normalize_membership_label(membership_row.get('nombre')) == normalized_plan:
            return int(membership_row['idmembresia'])

    fallback_row = membership_rows[0] if membership_rows else None
    return int(fallback_row['idmembresia']) if fallback_row else None


def _assign_membership_to_user(db: Session, nombreuser: str, plan_value: str | None) -> None:
    membership_id = _get_membership_id_for_plan(db, plan_value)
    if membership_id is None:
        return

    existing_membership = (
        db.query(Membresia_Usuario)
        .filter(Membresia_Usuario.usuario_nombreuser == nombreuser)
        .order_by(Membresia_Usuario.fechasubscripcion.desc(), Membresia_Usuario.idmembresiauser.desc())
        .first()
    )

    expires_at = _new_membership_expiration(plan_value)

    if existing_membership:
        existing_membership.membresia_idmembresi = membership_id
        existing_membership.fechavenc = expires_at
        db.add(existing_membership)
        return

    db.add(
        Membresia_Usuario(
            usuario_nombreuser=nombreuser,
            membresia_idmembresi=membership_id,
            fechavenc=expires_at,
        )
    )


def _get_latest_membership_row(db: Session, nombreuser: str):
    return db.execute(
        text(
            """
            SELECT
                mu.fechasubscripcion,
                mu.fechavenc,
                m.idmembresia,
                m.nombre,
                m.precio::text AS precio,
                m.nrovideosdiarios,
                m.duracionvideopermitida
            FROM membresia_usuario mu
            JOIN membresia m ON m.idmembresia = mu.membresia_idmembresi
            WHERE mu.usuario_nombreuser = :nombreuser
            ORDER BY mu.fechasubscripcion DESC, mu.idmembresiauser DESC
            LIMIT 1
            """
        ),
        {"nombreuser": nombreuser},
    ).mappings().first()


def _build_profile_response(user: Usuario, membership_row):
    active_membership = user.membership or _canonical_membership(membership_row['nombre'] if membership_row else 'free')
    return {
        'nombreuser': user.nombreuser,
        'nombre': user.nombre,
        'apellido': user.apellido,
        'correo': user.correo,
        'role': user.role or 'user',
        'membership_code': active_membership,
        'membership_request': user.membership_request,
        'payment_status': user.payment_status or 'approved',
        'payment_operation_code': user.payment_operation_code,
        'membership_expiration': user.membership_expiration.isoformat() if user.membership_expiration else None,
        'membership': {
            'idmembresia': membership_row['idmembresia'] if membership_row else None,
            'nombre': active_membership,
            'precio': _parse_membership_price(membership_row['precio']) if membership_row else None,
            'nrovideosdiarios': membership_row['nrovideosdiarios'] if membership_row else None,
            'duracionvideopermitida': membership_row['duracionvideopermitida'] if membership_row else None,
            'fechavenc': membership_row['fechavenc'].isoformat() if membership_row and membership_row['fechavenc'] else None,
        },
    }


@router.get('/admin/dashboard-summary', tags=['Admin'])
def get_admin_dashboard_summary(db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
    total_users = db.query(func.count(Usuario.nombreuser)).scalar() or 0

    premium_plans = (
        db.query(func.count(func.distinct(Membresia_Usuario.usuario_nombreuser)))
        .join(Membresia, Membresia.idmembresia == Membresia_Usuario.membresia_idmembresi)
        .filter(func.lower(Membresia.nombre).like('%premium%'))
        .scalar()
        or 0
    )

    analyses_done = db.query(func.count(Resultado_Total.idresultado_total)).scalar() or 0
    activity_total = db.query(func.count(Historial.idhistorial)).scalar() or 0

    memberships = db.execute(
        text(
            """
            SELECT idmembresia, nombre, precio::text AS precio, nrovideosdiarios, duracionvideopermitida
            FROM membresia
            ORDER BY idmembresia ASC
            """
        )
    ).mappings().all()

    membership_rows = db.execute(
        text(
            """
            SELECT
                mu.usuario_nombreuser,
                mu.fechavenc,
                mu.fechasubscripcion,
                m.idmembresia,
                m.nombre,
                m.precio::text AS precio,
                m.nrovideosdiarios,
                m.duracionvideopermitida
            FROM membresia_usuario mu
            JOIN membresia m ON m.idmembresia = mu.membresia_idmembresi
            ORDER BY mu.fechasubscripcion DESC, mu.idmembresiauser DESC
            """
        )
    ).mappings().all()
    latest_memberships = {}
    for row in membership_rows:
        if row["usuario_nombreuser"] not in latest_memberships:
            latest_memberships[row["usuario_nombreuser"]] = row

    users = []
    all_users = db.query(Usuario).order_by(Usuario.nombre.asc(), Usuario.nombreuser.asc()).all()
    for user in all_users:
        membership_row = latest_memberships.get(user.nombreuser)
        users.append({
            'nombreuser': user.nombreuser,
            'nombre': user.nombre,
            'apellido': user.apellido,
            'correo': user.correo,
            'role': user.role or 'user',
            'membership_code': user.membership or 'free',
            'membership_request': user.membership_request,
            'payment_status': user.payment_status or 'approved',
            'payment_operation_code': user.payment_operation_code,
            'payment_proof_path': user.payment_proof_path,
            'payment_submitted_at': user.payment_submitted_at.isoformat() if user.payment_submitted_at else None,
            'membership_expiration': user.membership_expiration.isoformat() if user.membership_expiration else None,
            'membership': {
                'idmembresia': membership_row['idmembresia'] if membership_row else None,
                'nombre': user.membership or 'free',
                'precio': _parse_membership_price(membership_row['precio']) if membership_row else None,
                'nrovideosdiarios': membership_row['nrovideosdiarios'] if membership_row else None,
                'duracionvideopermitida': membership_row['duracionvideopermitida'] if membership_row else None,
                'fechavenc': membership_row['fechavenc'].isoformat() if membership_row and membership_row['fechavenc'] else None,
            },
        })

    recent_activity_rows = (
        db.query(Historial, Video, Usuario)
        .join(Video, Historial.video_hash_video == Video.hash_video)
        .join(Usuario, Historial.usuario_nombreuser == Usuario.nombreuser)
        .order_by(Historial.fecha_consulta.desc(), Historial.idhistorial.desc())
        .limit(5)
        .all()
    )

    recent_activity = []
    for historial, video, user in recent_activity_rows:
        recent_activity.append({
            'idhistorial': historial.idhistorial,
            'usuario_nombreuser': historial.usuario_nombreuser,
            'usuario_nombre': user.nombre,
            'usuario_apellido': user.apellido,
            'correo': user.correo,
            'video_hash_video': video.hash_video,
            'video_nombre': video.nombrevideo,
            'estado': historial.estado,
            'fecha_consulta': historial.fecha_consulta.isoformat() if historial.fecha_consulta else None,
            'accion': f'Analizó {video.nombrevideo or video.hash_video}',
        })

    return {
        'total_users': int(total_users),
        'premium_plans': int(premium_plans),
        'analyses_done': int(analyses_done),
        'activity_total': int(activity_total),
        'users': users,
        'memberships': [
            {
                'idmembresia': membership['idmembresia'],
                'nombre': membership['nombre'],
                'precio': _parse_membership_price(membership['precio']) if membership['precio'] is not None else None,
                'nrovideosdiarios': membership['nrovideosdiarios'],
                'duracionvideopermitida': membership['duracionvideopermitida'],
            }
            for membership in memberships
        ],
        'recent_activity': recent_activity,
    }


@router.patch('/admin/users/{nombreuser}/membership', tags=['Admin'])
def update_user_membership(nombreuser: str, payload: dict, db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
    raw_membership_id = payload.get('membresia_id') or payload.get('membership_id')

    if raw_membership_id is None:
        raise HTTPException(status_code=400, detail='Falta membresia_id')

    try:
        membership_id = int(raw_membership_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail='membresia_id inválido')

    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not user:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    membership = db.execute(
        text(
            """
            SELECT idmembresia, nombre
            FROM membresia
            WHERE idmembresia = :membership_id
            """
        ),
        {"membership_id": membership_id},
    ).mappings().first()
    if not membership:
        raise HTTPException(status_code=404, detail='Membresía no encontrada')

    current_membership = (
        db.query(Membresia_Usuario)
        .filter(Membresia_Usuario.usuario_nombreuser == nombreuser)
        .order_by(Membresia_Usuario.fechasubscripcion.desc(), Membresia_Usuario.idmembresiauser.desc())
        .first()
    )

    expires_at = datetime.utcnow() + timedelta(days=30)

    if current_membership:
        current_membership.membresia_idmembresi = membership.idmembresia
        current_membership.fechavenc = expires_at if _is_paid_plan(membership.nombre) else None
        db.add(current_membership)
        user.membership_expiration = expires_at if _is_paid_plan(membership.nombre) else None
        user.payment_status = 'approved' if _is_paid_plan(membership.nombre) else 'approved'
        user.membership_reminder_sent_at = None
        db.add(user)
        db.commit()
        db.refresh(current_membership)
        return {
            'status': 'updated',
            'nombreuser': nombreuser,
            'membership_id': membership.idmembresia,
        }

    new_membership = Membresia_Usuario(
        usuario_nombreuser=nombreuser,
        membresia_idmembresi=membership.idmembresia,
        fechavenc=expires_at,
    )
    db.add(new_membership)
    user.membership_expiration = expires_at if _is_paid_plan(membership.nombre) else None
    user.payment_status = 'approved'
    user.membership_reminder_sent_at = None
    db.add(user)
    db.commit()
    db.refresh(new_membership)

    return {
        'status': 'created',
        'nombreuser': nombreuser,
        'membership_id': membership.idmembresia,
    }


@router.get('/admin/activity', tags=['Admin'])
def get_admin_activity(limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
    rows = (
        db.query(Historial, Video, Usuario)
        .join(Video, Historial.video_hash_video == Video.hash_video)
        .join(Usuario, Historial.usuario_nombreuser == Usuario.nombreuser)
        .order_by(Historial.fecha_consulta.desc(), Historial.idhistorial.desc())
        .limit(limit)
        .all()
    )
    return {
        'activity': [
            {
                'idhistorial': historial.idhistorial,
                'usuario_nombreuser': historial.usuario_nombreuser,
                'usuario_nombre': user.nombre,
                'usuario_apellido': user.apellido,
                'correo': user.correo,
                'video_hash_video': video.hash_video,
                'video_nombre': video.nombrevideo,
                'estado': historial.estado,
                'fecha_consulta': historial.fecha_consulta.isoformat() if historial.fecha_consulta else None,
                'accion': f'Analizó {video.nombrevideo or video.hash_video}',
            }
            for historial, video, user in rows
        ],
    }


def send_recovery_email(recipient_email: str, temporary_password: str) -> None:
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "riqssi10@gmail.com")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    smtp_from_name = os.getenv("SMTP_FROM_NAME", "RIQSSI")
    smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_user)
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

    if not smtp_password:
        raise RuntimeError("Falta configurar SMTP_PASSWORD para enviar correos")

    message = EmailMessage()
    message["Subject"] = "Instrucciones de recuperación de contraseña"
    message["From"] = f"{smtp_from_name} <{smtp_from_email}>"
    message["To"] = recipient_email
    message.set_content(
        """Hola,

Recibimos una solicitud para recuperar tu contraseña en RIQSSI.

Tu nueva contraseña temporal es:

{temporary_password}

Ingresa al sistema con esa contraseña y luego actualízala desde tu perfil.

Si quieres volver a revisar el acceso al sistema, entra desde:
{frontend_url}

Si no solicitaste este cambio, puedes ignorar este correo.

Saludos,
Equipo RIQSSI
""".format(frontend_url=frontend_url, temporary_password=temporary_password)
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def send_membership_expiration_reminder(user: Usuario) -> None:
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', 'riqssi10@gmail.com')
    smtp_password = os.getenv('SMTP_PASSWORD', '')
    smtp_from_name = os.getenv('SMTP_FROM_NAME', 'RIQSSI')
    smtp_from_email = os.getenv('SMTP_FROM_EMAIL', smtp_user)
    qr_url = os.getenv('YAPE_QR_EMAIL_URL') or _yape_qr_url()

    if not smtp_password:
        raise RuntimeError('Falta configurar SMTP_PASSWORD para enviar recordatorios')

    expiration_text = user.membership_expiration.strftime('%d/%m/%Y') if user.membership_expiration else 'próximamente'
    message = EmailMessage()
    message['Subject'] = 'Tu membresía RIQSSI vence pronto'
    message['From'] = f'{smtp_from_name} <{smtp_from_email}>'
    message['To'] = user.correo
    message.set_content(
        f"Hola {user.nombre or user.nombreuser},\n\n"
        f"Tu membresía vence el {expiration_text}. Renueva antes de esa fecha para mantener el acceso a las funciones avanzadas.\n\n"
        f"Código o enlace QR de Yape: {qr_url}\n\n"
        "Después del pago, sube tu comprobante y código de operación desde RIQSSI.\n\n"
        "Saludos,\nEquipo RIQSSI"
    )

    qr_path = Path(qr_url) if not qr_url.startswith(('http://', 'https://', '/storage/')) else Path(__file__).resolve().parents[2] / qr_url.lstrip('/')
    if qr_path.is_file():
        if qr_path.suffix.lower() == '.pdf':
            maintype, subtype = 'application', 'pdf'
        else:
            maintype, subtype = 'image', qr_path.suffix.lstrip('.').lower() or 'png'
        message.add_attachment(qr_path.read_bytes(), maintype=maintype, subtype=subtype, filename=qr_path.name)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(message)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _remove_storage_path(path_value: str | None) -> None:
    if not path_value:
        return

    normalized_path = str(path_value).replace('\\', '/')
    candidate = Path(normalized_path)

    if not candidate.is_absolute():
        candidate = _project_root() / normalized_path.lstrip('/')

    try:
        if candidate.is_dir():
            shutil.rmtree(candidate)
        elif candidate.exists():
            candidate.unlink()
    except Exception:
        pass


def _delete_user_artifacts(db: Session, username: str) -> None:
    videos = db.query(Video).filter(Video.usuario_nombreuser == username).all()

    for video in videos:
        pistas_video = db.query(Pista_Video).filter(Pista_Video.video_hash_video == video.hash_video).all()
        pistas_audio = db.query(Pista_Audio).filter(Pista_Audio.video_hash_video == video.hash_video).all()

        for pista_video in pistas_video:
            extracciones_video = db.query(Extraccion_Video).filter(
                Extraccion_Video.pista_video_hash_pvideo == pista_video.hash_pvideo
            ).all()
            for extraccion in extracciones_video:
                _remove_storage_path(extraccion.ruta_video_frames)
                db.delete(extraccion)

            resultados_video = db.query(Resultado_Video).join(
                Extraccion_Video,
                Resultado_Video.extraccion_video_id_extraccio == Extraccion_Video.id_extraccionv,
            ).filter(Extraccion_Video.pista_video_hash_pvideo == pista_video.hash_pvideo).all()
            for resultado in resultados_video:
                db.delete(resultado)

            _remove_storage_path(pista_video.ruta_pvideo)
            db.delete(pista_video)

        for pista_audio in pistas_audio:
            extracciones_audio = db.query(Extraccion_Audio).filter(
                Extraccion_Audio.pista_audio_hash_paudio == pista_audio.hash_paudio
            ).all()
            for extraccion in extracciones_audio:
                _remove_storage_path(extraccion.ruta_mfcc)
                db.delete(extraccion)

            resultados_audio = db.query(Resultado_Audio).join(
                Extraccion_Audio,
                Resultado_Audio.extraccion_audio_id_extraccion == Extraccion_Audio.id_extracciona,
            ).filter(Extraccion_Audio.pista_audio_hash_paudio == pista_audio.hash_paudio).all()
            for resultado in resultados_audio:
                db.delete(resultado)

            _remove_storage_path(pista_audio.ruta_paudio)
            db.delete(pista_audio)

        resultados_total = db.query(Resultado_Total).filter(Resultado_Total.video_hash_video == video.hash_video).all()
        for resultado in resultados_total:
            db.delete(resultado)

        historial_entries = db.query(Historial).filter(Historial.video_hash_video == video.hash_video).all()
        for historial in historial_entries:
            db.delete(historial)

        _remove_storage_path(video.thumbnail_path)
        _remove_storage_path(video.video_path)
        db.delete(video)

    memberships = db.query(Membresia_Usuario).filter(Membresia_Usuario.usuario_nombreuser == username).all()
    for membership in memberships:
        db.delete(membership)

    remaining_historial = db.query(Historial).filter(Historial.usuario_nombreuser == username).all()
    for historial in remaining_historial:
        db.delete(historial)

    remaining_results = db.query(Resultado_Total).filter(Resultado_Total.usuario_nombreuser == username).all()
    for resultado in remaining_results:
        db.delete(resultado)


@router.delete("/account/{nombreuser}", tags=["Auth"])
async def delete_account(nombreuser: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()

    if current_user.nombreuser != nombreuser:
        raise HTTPException(status_code=403, detail="No puedes eliminar otra cuenta")

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe una cuenta asociada a ese usuario"
        )

    try:
        _delete_user_artifacts(db, nombreuser)
        db.delete(user)
        db.commit()
    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo eliminar la cuenta: {error}"
        )

    return {
        "message": "Cuenta eliminada correctamente",
        "nombreuser": nombreuser,
    }


@router.get("/account/{nombreuser}/profile", tags=["Auth"])
def get_account_profile(nombreuser: str, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()

    if current_user.nombreuser != nombreuser:
        raise HTTPException(status_code=403, detail="No puedes consultar otro perfil")

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe una cuenta asociada a ese usuario"
        )

    _expire_membership_if_needed(user, db)
    membership_row = _get_latest_membership_row(db, nombreuser)
    return _build_profile_response(user, membership_row)

@router.post("/login", tags=["Auth"])
async def login(credentials: UsuarioLogin, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(credentials.correo)
    user = db.query(Usuario).filter(func.lower(Usuario.correo) == normalized_email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo incorrecto"
        )

    if not verify_password(credentials.clave, user.clave):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Contraseña incorrecta"
        )

    if not user.clave.startswith('$2'):
        user.clave = hash_password(credentials.clave)
        db.add(user)
        db.commit()

    _expire_membership_if_needed(user, db)
    membership_row = _get_latest_membership_row(db, user.nombreuser)

    return {
        "message": "Login exitoso",
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": {
            "nombreuser": user.nombreuser,
            "nombre": user.nombre,
            "apellido": user.apellido,
            "correo": user.correo,
            "role": user.role or "user",
            "payment_status": user.payment_status or "approved",
            "membership_expiration": user.membership_expiration.isoformat() if user.membership_expiration else None,
            "membership_request": user.membership_request,
            "membership": {
                "idmembresia": membership_row['idmembresia'] if membership_row else None,
                "nombre": user.membership or 'free',
                "precio": _parse_membership_price(membership_row['precio']) if membership_row else None,
                "nrovideosdiarios": membership_row['nrovideosdiarios'] if membership_row else None,
                "duracionvideopermitida": membership_row['duracionvideopermitida'] if membership_row else None,
                "fechavenc": membership_row['fechavenc'].isoformat() if membership_row and membership_row['fechavenc'] else None,
            },
        }
    }


@router.post("/register", tags=["Auth"], status_code=status.HTTP_201_CREATED)
async def register(payload: UsuarioCreate, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(payload.correo)
    existing_user = db.query(Usuario).filter(
        (Usuario.nombreuser == payload.nombre_usuario) | (func.lower(Usuario.correo) == normalized_email)
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El nombre de usuario o correo ya existe"
        )

    user = Usuario(
        nombreuser=payload.nombre_usuario,
        nombre=payload.nombre,
        apellido=payload.apellido,
        fecha_nacimiento=payload.fecha_nacimiento,
        correo=normalized_email,
        clave=hash_password(payload.clave),
        role='admin' if normalized_email == 'sebi2004xd@gmail.com' else 'user',
    )

    db.add(user)
    try:
        db.flush()
        selected_plan = payload.plan or payload.membresia
        _assign_membership_to_user(db, user.nombreuser, 'gratis')
        user.payment_status = 'pending' if _is_paid_plan(selected_plan) else 'approved'
        user.membership = 'free'
        user.membership_request = _canonical_membership(selected_plan) if _is_paid_plan(selected_plan) else None
        user.membership_expiration = _new_membership_expiration(selected_plan) if not _is_paid_plan(selected_plan) else None
        user.membership_reminder_sent_at = None
        db.commit()
        db.refresh(user)
    except Exception as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registro creado, pero no se pudo asignar la membresía: {error}"
        )

    return {
        "message": "Registro exitoso",
        "user": {
            "nombreuser": user.nombreuser,
            "nombre": user.nombre,
            "apellido": user.apellido,
            "correo": user.correo,
            "role": user.role,
            "plan": selected_plan,
            "membership": {"nombre": user.membership},
            "membership_request": user.membership_request,
            "payment_status": user.payment_status,
            "yape_qr_url": _yape_qr_url() if user.payment_status == 'pending' else None,
        }
    }


@router.post("/recover-password", tags=["Auth"])
async def recover_password(payload: PasswordRecoveryRequest, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(payload.correo)
    user = db.query(Usuario).filter(func.lower(Usuario.correo) == normalized_email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe una cuenta asociada a ese correo"
        )

    temporary_password = generate_temporary_password()
    old_password = user.clave
    user.clave = hash_password(temporary_password)
    db.add(user)
    db.commit()

    try:
        send_recovery_email(user.correo, temporary_password)
    except smtplib.SMTPAuthenticationError:
        user.clave = old_password
        db.add(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Gmail rechazó la autenticación SMTP. "
                "Usa una App Password de Google o verifica que SMTP_USER y SMTP_PASSWORD sean válidos."
            )
        )
    except smtplib.SMTPException as error:
        user.clave = old_password
        db.add(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error SMTP al enviar el correo de recuperación: {error}"
        )
    except RuntimeError as error:
        user.clave = old_password
        db.add(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(error)
        )
    except Exception:
        user.clave = old_password
        db.add(user)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No se pudo enviar el correo de recuperación"
        )

    return {
        "message": "Instrucciones enviadas",
        "correo": user.correo,
    }


@router.post("/change-password", tags=["Auth"])
async def change_password(payload: PasswordChangeRequest, db: Session = Depends(get_db)):
    normalized_email = _normalize_email(payload.correo)
    user = db.query(Usuario).filter(func.lower(Usuario.correo) == normalized_email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existe una cuenta asociada a ese correo"
        )

    if not payload.nueva_clave.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña no puede estar vacía"
        )

    user.clave = hash_password(payload.nueva_clave)
    db.add(user)
    db.commit()

    return {
        "message": "Contraseña actualizada correctamente",
        "correo": user.correo,
    }


@router.get('/admin/system-status', tags=['Admin'])
def get_admin_system_status(db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
    project_root = Path(__file__).resolve().parents[2]
    storage_path = project_root / 'storage'
    audio_model_path = os.getenv('MODEL_PATH_AUDIO', 'models_ML/modelo_audio.pkl')
    video_model_path = os.getenv('MODEL_PATH_VIDEO', 'models_ML/modelo_video.pt')

    def resolve_project_path(path_value: str) -> Path:
        path = Path(path_value)
        return path if path.is_absolute() else project_root / path

    components = {}

    try:
        db.execute(text('SELECT 1'))
        components['database'] = {'status': 'operativo', 'detail': 'Conexión disponible'}
    except Exception:
        components['database'] = {'status': 'error', 'detail': 'No se pudo conectar a la base de datos'}

    components['audio_model'] = {
        'status': 'operativo' if resolve_project_path(audio_model_path).is_file() else 'error',
        'detail': 'Modelo disponible' if resolve_project_path(audio_model_path).is_file() else 'Modelo no encontrado',
    }
    components['video_model'] = {
        'status': 'operativo' if resolve_project_path(video_model_path).is_file() else 'error',
        'detail': 'Modelo disponible' if resolve_project_path(video_model_path).is_file() else 'Modelo no encontrado',
    }

    try:
        total, used, free = shutil.disk_usage(storage_path if storage_path.exists() else project_root)
        free_gb = round(free / (1024 ** 3), 2)
        storage_status = 'error' if free_gb < 1 else 'advertencia' if free_gb < 5 else 'operativo'
        components['storage'] = {
            'status': storage_status,
            'detail': f'{free_gb} GB disponibles',
            'free_gb': free_gb,
        }
    except OSError:
        components['storage'] = {'status': 'error', 'detail': 'No se pudo consultar el almacenamiento'}

    statuses = [component['status'] for component in components.values()]
    overall_status = 'error' if 'error' in statuses else 'advertencia' if 'advertencia' in statuses else 'operativo'

    return {
        'status': overall_status,
        'components': components,
        'checked_at': datetime.utcnow().isoformat() + 'Z',
    }


@router.post('/membership/payment', tags=['Memberships'])
async def submit_membership_payment(
    nombreuser: str = Form(...),
    operation_code: str = Form(...),
    proof: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not user:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    membership = _get_latest_membership_row(db, nombreuser)
    if not user.membership_request or not _is_paid_plan(user.membership_request):
        raise HTTPException(status_code=400, detail='El usuario no tiene una membresía de pago seleccionada')
    if not operation_code.strip():
        raise HTTPException(status_code=400, detail='El código de operación es obligatorio')

    extension = Path(proof.filename or '').suffix.lower()
    if extension not in {'.jpg', '.jpeg', '.png', '.pdf'}:
        raise HTTPException(status_code=400, detail='El comprobante debe ser JPG, PNG o PDF')

    filename = f'{user.nombreuser}_{datetime.utcnow().strftime("%Y%m%d%H%M%S")}{extension}'
    proof_path = PAYMENT_PROOF_DIR / filename
    with proof_path.open('wb') as destination:
        shutil.copyfileobj(proof.file, destination)

    user.payment_status = 'pending'
    user.payment_operation_code = operation_code.strip()
    user.payment_proof_path = persist_file(proof_path, f'storage/payment_proofs/{filename}')
    user.payment_submitted_at = datetime.utcnow()
    user.payment_reviewed_at = None
    user.membership_reminder_sent_at = None
    db.add(user)
    db.commit()
    return {'status': 'pending', 'payment_status': user.payment_status, 'message': 'Comprobante enviado para revisión'}


@router.post('/membership/select', tags=['Memberships'])
def select_membership(payload: dict, db: Session = Depends(get_db)):
    nombreuser = payload.get('nombreuser')
    plan = payload.get('plan')
    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not user:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')
    if _normalize_membership_label(plan) not in {'gratis', 'basico', 'premium'}:
        raise HTTPException(status_code=400, detail='Membresía inválida')

    requested_membership = _canonical_membership(plan)
    active_membership = requested_membership if requested_membership == 'free' else 'free'
    _assign_membership_to_user(db, nombreuser, 'gratis')
    user.membership = active_membership
    user.membership_request = None if requested_membership == 'free' else requested_membership
    user.payment_status = 'pending' if requested_membership != 'free' else 'approved'
    user.membership_expiration = None
    user.membership_reminder_sent_at = None
    user.payment_proof_path = None
    user.payment_operation_code = None
    user.payment_submitted_at = None
    user.payment_reviewed_at = None
    db.add(user)
    db.commit()
    return {
        'status': user.payment_status,
        'plan': requested_membership,
        'yape_qr_url': _yape_qr_url() if user.payment_status == 'pending' else None,
    }


@router.post('/membership/cancel', tags=['Memberships'])
def cancel_membership(payload: dict, db: Session = Depends(get_db)):
    nombreuser = payload.get('nombreuser')
    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not user:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    current_membership = _get_latest_membership_row(db, nombreuser)
    if not _is_paid_plan(user.membership):
        raise HTTPException(status_code=400, detail='Solo puedes cancelar una membresía Básica o Premium')

    free_membership_id = _get_membership_id_for_plan(db, 'gratis')
    if free_membership_id is None:
        raise HTTPException(status_code=500, detail='No existe la membresía Gratis configurada')

    membership_record = (
        db.query(Membresia_Usuario)
        .filter(Membresia_Usuario.usuario_nombreuser == nombreuser)
        .order_by(Membresia_Usuario.fechasubscripcion.desc(), Membresia_Usuario.idmembresiauser.desc())
        .first()
    )
    if membership_record:
        membership_record.membresia_idmembresi = free_membership_id
        membership_record.fechavenc = None
        db.add(membership_record)

    user.payment_status = 'canceled'
    user.membership = 'free'
    user.membership_request = None
    user.payment_reviewed_at = datetime.utcnow()
    user.payment_proof_path = None
    user.payment_operation_code = None
    db.add(user)
    db.add(Cancelacion_Membresia(
        usuario_nombreuser=nombreuser,
        membresia_idmembresia=current_membership['idmembresia'],
        motivo=str(payload.get('motivo') or '').strip()[:250] or None,
    ))
    db.commit()
    return {
        'status': 'canceled',
        'membership': 'gratis',
        'payment_status': user.payment_status,
    }


@router.post('/admin/payments/{nombreuser}/review', tags=['Admin'])
def review_membership_payment(nombreuser: str, payload: dict, db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
    decision = str(payload.get('status', '')).lower()
    if decision not in {'approved', 'rejected'}:
        raise HTTPException(status_code=400, detail="El estado debe ser 'approved' o 'rejected'")

    user = db.query(Usuario).filter(Usuario.nombreuser == nombreuser).first()
    if not user:
        raise HTTPException(status_code=404, detail='Usuario no encontrado')

    requested_membership = user.membership_request
    user.payment_status = decision
    user.payment_reviewed_at = datetime.utcnow()
    if decision == 'approved':
        if not _is_paid_plan(requested_membership):
            raise HTTPException(status_code=400, detail='El usuario no tiene una solicitud de pago pendiente')
        _assign_membership_to_user(db, nombreuser, requested_membership)
        user.membership = _canonical_membership(requested_membership)
        user.membership_expiration = _new_membership_expiration(requested_membership)
        user.membership_reminder_sent_at = None
    else:
        _assign_membership_to_user(db, nombreuser, 'gratis')
        user.membership = 'free'
        user.membership_expiration = None
    db.add(user)
    db.commit()
    return {'status': decision, 'nombreuser': nombreuser, 'payment_status': user.payment_status}